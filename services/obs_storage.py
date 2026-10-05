from obs import ObsClient


def connect_to_obs(config, logger):
    client = ObsClient(
        access_key_id=config["obs_access_key"],
        secret_access_key=config["obs_secret_key"],
        server=config["obs_endpoint"],
    )
    # A real API request confirms that the credentials and bucket are usable.
    try:
        result = client.listObjects(config["obs_bucket"], max_keys=1)
        if not 200 <= result.status < 300:
            raise RuntimeError(
                f"OBS connection failed: HTTP {result.status} "
                f"{result.errorCode}: {result.errorMessage}"
            )
    except Exception:
        client.close()
        raise
    logger.info("Connected to OBS bucket: %s", config["obs_bucket"])
    return client


def upload_dump(client, config, database, dump_file, logger, dump_timestamp):
    # Use the same timestamp that was used to name the dump.
    object_key = (
        f"{config['host']}/{database}/"
        f"{dump_timestamp:%Y/%m/%d}/{dump_file.name}"
    )

    bucket = config["obs_bucket"]
    size = dump_file.stat().st_size

    # Keep this file beside the dump so another attempt can resume.
    checkpoint_file = dump_file.with_name(
        dump_file.name + ".upload_checkpoint"
    )

    existing = client.listObjects(
        bucket, prefix=object_key, max_keys=1
    )
    if not 200 <= existing.status < 300:
        raise RuntimeError(
            f"OBS object check failed: HTTP {existing.status} "
            f"{existing.errorCode}: {existing.errorMessage}"
        )

    if any(item.key == object_key for item in existing.body.contents):
        raise FileExistsError(
            f"OBS object already exists: obs://{bucket}/{object_key}"
        )

    logger.info(
        "[%s] Uploading %d bytes to obs://%s/%s",
        database, size, bucket, object_key,
    )

    try:
        # The resumable API requires a file larger than 800 MB.
        if size <= 800 * 1024 * 1024:
            result = client.putFile(
                bucket, object_key, str(dump_file)
            )
        else:
            result = client.uploadFile(
                bucketName=bucket,
                objectKey=object_key,
                uploadFile=str(dump_file),
                partSize=512 * 1024 * 1024,    # 512 MB per part
                taskNum=4,                  # 4 parallel uploads
                enableCheckpoint=True,
                checkpointFile=str(checkpoint_file),
            )

        if not 200 <= result.status < 300:
            raise RuntimeError(
                f"OBS upload failed: HTTP {result.status} "
                f"{result.errorCode}: {result.errorMessage}"
            )

        metadata = client.getObjectMetadata(bucket, object_key)
        if not 200 <= metadata.status < 300:
            raise RuntimeError(
                f"OBS verification failed: HTTP {metadata.status} "
                f"{metadata.errorCode}: {metadata.errorMessage}"
            )

        remote_size = int(metadata.body.contentLength)
        if remote_size != size:
            raise RuntimeError(
                f"OBS size mismatch: local={size}, "
                f"uploaded={remote_size}"
            )

    except Exception:
        logger.exception(
            "[%s] Upload or verification failed. "
            "Local dump retained: %s. Checkpoint path: %s",
            database, dump_file, checkpoint_file,
        )
        raise

    logger.info(
        "[%s] Upload verified: %d bytes", database, remote_size
    )

    dump_file.unlink()
    checkpoint_file.unlink(missing_ok=True)
    logger.info("[%s] Local dump deleted", database)


# Shared file upload helpers used by Snowflake exports.
import hashlib
import time

def checked(response, action):
    if not 200 <= response.status < 300:
        raise RuntimeError(f'{action}: HTTP {response.status}; code={response.errorCode}')
    return response

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def exists(client, bucket, key):
    response = client.getObjectMetadata(bucket, key)
    if response.status == 404:
        return False
    checked(response, 'Check object')
    return True

def upload_verified(client, bucket, key, path, logger):
    # Multipart upload still creates ONE object, not separate Parquet parts.
    for attempt in range(1, 4):
        verification = path.with_suffix(path.suffix + '.verify')
        try:
            if path.stat().st_size <= 800 * 1024 * 1024:
                response = client.putFile(bucket, key, str(path))
            else:
                response = client.uploadFile(bucket, key, str(path),
                    partSize=512 * 1024 * 1024, taskNum=2, enableCheckpoint=False)
            checked(response, 'Upload')
            checked(client.getObject(bucket, key, downloadPath=str(verification)),
                    'Verification download')
            if verification.stat().st_size != path.stat().st_size or digest(verification) != digest(path):
                raise RuntimeError('Uploaded object checksum mismatch')
            logger.info('Verified obs://%s/%s SHA256=%s', bucket, key, digest(path))
            return
        except Exception:
            if attempt == 3:
                raise
            logger.warning('Upload/verification retry %s for %s', attempt, path.name)
            time.sleep(attempt * 2)
        finally:
            verification.unlink(missing_ok=True)

