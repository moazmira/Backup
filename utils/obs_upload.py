import logging
from xmlrpc import client


logger = logging.getLogger("backup")


def check_obs_response(response, action):
    status = response.status
    if status is None or not 200 <= status < 300:
        raise RuntimeError(f'{action}: HTTP {status}; {response.errorCode}: {response.errorMessage}')
    return response


def check_uploaded_size(client, bucket, key, path):
    metadata = check_obs_response(
        client.getObjectMetadata(bucket, key),"Read uploaded metadata",
    )

    local_size = path.stat().st_size
    uploaded_size = int(metadata.body.contentLength)

    if uploaded_size != local_size:
        return 0

    logger.info("Uploaded size matched: %s bytes=%d", key, local_size)
    return 1



def upload_file(client, settings, key, path):
    bucket = settings['bucket']
    size = path.stat().st_size

    logger.info('Uploading: %s -> obs://%s/%s bytes=%d', path, bucket, key, size)

    if size < 250 * 1024 * 1024:

        response = client.putFile(bucket, key, str(path))
    else:
        response = client.uploadFile(
            bucketName=bucket, 
            objectKey=key, 
            uploadFile=str(path),
            partSize=150 * 1024 * 1024,
            taskNum=3, 
            enableCheckpoint=False,
        )

    check_obs_response(response, "Upload file")

    size_matches = check_uploaded_size(client, bucket, key, path)

    if size_matches == 0:
        raise RuntimeError(f"Uploaded size mismatch: {key}")

    return 1

def transfer_files(client, settings, files, base_key):
    for file_path in files:
        key = base_key + file_path.suffix
        upload_file(client, settings, key, file_path)

    for file_path in files:
        file_path.unlink()
        logger.info("Local file deleted: %s", file_path)

        