def connect_obs(settings, logger):
    import certifi
    from obs import ObsClient

    logger.info("Connecting to OBS bucket: %s", settings["bucket"])
    client = ObsClient(
        access_key_id=settings["access_key_id"],
        secret_access_key=settings["secret_access_key"],
        server=settings["endpoint"],
        timeout=30,
        ssl_verify=certifi.where(),
    )
    try:
        result = client.listObjects(settings["bucket"], max_keys=1)
        if not 200 <= result.status < 300:
            raise RuntimeError(
                f"OBS bucket check failed: HTTP {result.status}; "
                f"{result.errorCode}: {result.errorMessage}"
            )
        logger.info("OBS bucket accessible: %s (list permission verified)", settings["bucket"])
        return client
    except Exception:
        client.close()
        raise
