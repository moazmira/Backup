import logging

logger = logging.getLogger("backup")


def connect_obs(settings):
    import certifi
    from obs import ObsClient
    logger.info('Connecting to OBS bucket: %s', settings['bucket'])
    client = ObsClient(access_key_id=settings['access_key_id'], secret_access_key=settings['secret_access_key'], server=settings['endpoint'], timeout=settings.get('timeout', 60), ssl_verify=certifi.where())
    try:
        result = client.listObjects(settings['bucket'], max_keys=1)
        if result.status is None or not 200 <= result.status < 300:
            raise RuntimeError(f'OBS connection failed: HTTP {result.status}; {result.errorCode}: {result.errorMessage}')
        logger.info('OBS bucket accessible: %s', settings['bucket'])
        return client
    except Exception:
        client.close()
        raise
