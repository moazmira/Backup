import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("backup")


def checked(response, action):
    status = response.status
    if status is None or not 200 <= status < 300:
        raise RuntimeError(f'{action}: HTTP {status}; {response.errorCode}: {response.errorMessage}')
    return response

def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def object_exists(client, bucket, key):
    response = client.getObjectMetadata(bucket, key)
    if response.status == 404:
        return False
    checked(response, 'Check existing object')
    return True

def select_object_name(client, bucket, base, extensions):
    """The shared local run lock serializes writers; use _2, _3 on reruns."""
    suffix = 1
    while True:
        base_name = base if suffix == 1 else f'{base}_{suffix}'
        if not any((object_exists(client, bucket, base_name + ext) for ext in extensions)):
            return base_name
        suffix += 1

def verify_upload(client, bucket, key, path, expected_hash):
    metadata = checked(client.getObjectMetadata(bucket, key), 'Read uploaded metadata')
    size = path.stat().st_size
    if int(metadata.body.contentLength) != size:
        raise RuntimeError(f'Uploaded size mismatch: {key}')
    verification = path.with_name(path.name + '.verify')
    try:
        checked(client.getObject(bucket, key, downloadPath=str(verification)), 'Download for verification')
        if verification.stat().st_size != size or sha256_file(verification) != expected_hash:
            raise RuntimeError(f'Uploaded SHA-256 mismatch: {key}')
    finally:
        verification.unlink(missing_ok=True)
    logger.info('Upload verified: obs://%s/%s bytes=%d SHA256=%s', bucket, key, size, expected_hash)

def upload_verified(client, settings, key, path):
    bucket = settings['bucket']
    size = path.stat().st_size
    digest = sha256_file(path)
    if object_exists(client, bucket, key):
        raise FileExistsError(f'Refusing to overwrite obs://{bucket}/{key}')
    logger.info('Uploading: %s -> obs://%s/%s bytes=%d', path, bucket, key, size)
    if size < settings.get('multipart_threshold_mb', 100) * 1024 * 1024:
        response = client.putFile(bucket, key, str(path))
    else:
        response = client.uploadFile(
            bucketName=bucket, objectKey=key, uploadFile=str(path),
            partSize=settings.get("part_size_mb", 64) * 1024 * 1024,
            taskNum=settings.get("upload_threads", 2), enableCheckpoint=False,
        )
    checked(response, 'Upload file')
    for attempt in range(1, settings.get('attempts', 3) + 1):
        try:
            verify_upload(client, bucket, key, path, digest)
            return {'key': key, 'bytes': size, 'sha256': digest}
        except Exception:
            if attempt == settings.get('attempts', 3):
                raise
            logger.warning('Verification retry %d for %s', attempt, key)
            time.sleep(min(attempt * 2, 10))

def transfer_files(client, settings, files, base_key):
    """Upload the whole unit, publish a completion receipt, then clean up."""
    bucket = settings['bucket']
    extensions = [path.suffix for path in files] + ['.complete.json']
    base_name = select_object_name(client, bucket, base_key, extensions)
    receipts = []
    for path in files:
        receipts.append(upload_verified(client, settings, base_name + path.suffix, path))
    marker = files[0].with_name(files[0].stem + '.complete.json')
    marker.write_text(json.dumps({'status': 'complete', 'files': receipts}, indent=2) + '\n', encoding='utf-8')
    upload_verified(client, settings, base_name + '.complete.json', marker)
    for path in [*files, marker]:
        path.unlink()
        logger.info("Local file deleted: %s", path)
