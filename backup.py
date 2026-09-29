import os
from obs import ObsClient

bucket = "metadata-daily-backups"
endpoint = "https://obs.af-north-1.myhuaweicloud.com"

access_key = os.environ["OBS_ACCESS_KEY_ID"]
secret_key = os.environ["OBS_SECRET_ACCESS_KEY"]

client = ObsClient(
    access_key_id=access_key,
    secret_access_key=secret_key,
    server=endpoint,
)

try:
    result = client.listObjects(bucket, max_keys=5)

    if result.status < 300:
        print(f"Connected to {bucket}")
        for obj in result.body.contents:
            print(obj.key)
    else:
        print(f"OBS error {result.status}: {result.errorCode} - {result.errorMessage}")
finally:
    client.close()