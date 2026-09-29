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
    # The date is taken from this dump's timestamp so the path matches its name.
    date = dump_file.name[len(database) + 1:][:8]
    object_key = (
        f"{config['host']}/{database}/"
        f"{date[:4]}/{date[4:6]}/{date[6:8]}/{dump_file.name}"
    )
    bucket = config["obs_bucket"]
    size = dump_file.stat().st_size
    if size > 5 * 1024**3:
        raise RuntimeError("Dump exceeds the 5 GiB single-upload limit")
    existing = client.listObjects(bucket, prefix=object_key, max_keys=1)
    if not 200 <= existing.status < 300:
        raise RuntimeError(
            f"OBS object check failed: HTTP {existing.status} "
            f"{existing.errorCode}: {existing.errorMessage}"
        )
    if any(item.key == object_key for item in existing.body.contents):
        raise FileExistsError(f"OBS object already exists: obs://{bucket}/{object_key}")
    logger.info("[%s] Uploading to obs://%s/%s", database, bucket, object_key)

    result = client.putFile(bucket, object_key, str(dump_file))
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
        raise RuntimeError(f"OBS size mismatch: local={size}, uploaded={remote_size}")

    logger.info("[%s] Upload verified: %d bytes", database, remote_size)
    dump_file.unlink()
    logger.info("[%s] Local dump deleted", database)


