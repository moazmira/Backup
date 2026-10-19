import hashlib
import json
import time
from pathlib import Path


def checked(response, action):
    status = response.status
    if status is None or not 200 <= status < 300:
        raise RuntimeError(f"{action}: HTTP {status}; {response.errorCode}: {response.errorMessage}")
    return response


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_exists(client, bucket, key):
    response = client.getObjectMetadata(bucket, key)
    if response.status == 404:
        return False
    checked(response, "Check existing object")
    return True


def select_object_stem(client, bucket, base, extensions):
    """The shared local run lock serializes writers; use _2, _3 on reruns."""
    suffix = 1
    while True:
        stem = base if suffix == 1 else f"{base}_{suffix}"
        if not any(object_exists(client, bucket, stem + ext) for ext in extensions):
            return stem
        suffix += 1


def verify_upload(client, bucket, key, path, expected_hash, logger):
    metadata = checked(client.getObjectMetadata(bucket, key), "Read uploaded metadata")
    size = path.stat().st_size
    if int(metadata.body.contentLength) != size:
        raise RuntimeError(f"Uploaded size mismatch: {key}")
    verification = path.with_name(path.name + ".verify")
    try:
        checked(client.getObject(bucket, key, downloadPath=str(verification)), "Download for verification")
        if verification.stat().st_size != size or sha256_file(verification) != expected_hash:
            raise RuntimeError(f"Uploaded SHA-256 mismatch: {key}")
    finally:
        verification.unlink(missing_ok=True)
    logger.info("Upload verified: obs://%s/%s bytes=%d SHA256=%s", bucket, key, size, expected_hash)


def upload_verified(client, settings, key, path, logger):
    bucket = settings["bucket"]
    size = path.stat().st_size
    digest = sha256_file(path)
    if object_exists(client, bucket, key):
        raise FileExistsError(f"Refusing to overwrite obs://{bucket}/{key}")
    logger.info("Uploading: %s -> obs://%s/%s bytes=%d", path, bucket, key, size)
    # SDK request retries handle transient upload errors. Do not blindly retry an
    # ambiguous upload by overwriting an object that may already have completed.
    if size < settings.get("multipart_threshold_mb", 100) * 1024 * 1024:
        response = client.putFile(bucket, key, str(path))
    else:
        response = client.uploadFile(
            bucketName=bucket, objectKey=key, uploadFile=str(path),
            partSize=settings.get("part_size_mb", 64) * 1024 * 1024,
            taskNum=settings.get("upload_threads", 2), enableCheckpoint=False,
        )
    checked(response, "Upload file")
    for attempt in range(1, settings.get("attempts", 3) + 1):
        try:
            verify_upload(client, bucket, key, path, digest, logger)
            return {"key": key, "bytes": size, "sha256": digest}
        except Exception:
            if attempt == settings.get("attempts", 3):
                raise
            logger.warning("Verification retry %d for %s", attempt, key)
            time.sleep(min(attempt * 2, 10))


def transfer_files(client, settings, files, base_key, logger, keep_local=False):
    """Upload the whole unit, publish a completion receipt, then clean up."""
    bucket = settings["bucket"]
    extensions = [path.suffix for path in files] + [".complete.json"]
    stem = select_object_stem(client, bucket, base_key, extensions)
    receipts = []
    for path in files:
        receipts.append(upload_verified(client, settings, stem + path.suffix, path, logger))
    marker = files[0].with_name(files[0].stem + ".complete.json")
    marker.write_text(json.dumps({"status": "complete", "files": receipts}, indent=2) + "\n", encoding="utf-8")
    marker_receipt = upload_verified(client, settings, stem + ".complete.json", marker, logger)
    # No original file is deleted unless every object, including the receipt,
    # has passed a downloaded checksum comparison.
    if not keep_local:
        for path in [*files, marker]:
            path.unlink()
            logger.info("Local file deleted: %s", path)
    return {"files": receipts, "completion": marker_receipt, "local_files_kept": keep_local}
