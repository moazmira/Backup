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


def upload_dump(client, config, database, dump_file, logger):
    # The date is taken from this dump's timestamp.
    date = dump_file.name[len(database) + 1:][:8]
    object_key = (
        f"{config['host']}/{database}/"
        f"{date[:4]}/{date[4:6]}/{date[6:8]}/{dump_file.name}"
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
        # The resumable API requires a file larger than 100 KB.
        if size <= 100 * 1024:
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