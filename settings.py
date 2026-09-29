import os
from pathlib import Path

from dotenv import load_dotenv


def load_config():
    load_dotenv(Path(__file__).with_name(".env"))
    host = os.environ["PG_HOST"].strip()
    if not host or "/" in host or "\\" in host or host in (".", ".."):
        raise ValueError("PG_HOST must be a valid single folder name")
    databases = [
        name.strip()
        for name in os.environ["PG_DATABASES"].split(",")
        if name.strip()
    ]
    if not databases:
        raise ValueError("PG_DATABASES is empty")

    return {
        "host": host,
        "port": os.getenv("PG_PORT", "5432"),
        "user": os.environ["PG_USER"],
        "password": os.environ["PG_PASSWORD"],
        "databases": databases,
        "pg_dump": os.getenv("PG_DUMP_PATH", "pg_dump"),
        "obs_bucket": os.environ["OBS_BUCKET"],
        "obs_endpoint": os.environ["OBS_ENDPOINT"],
        "obs_access_key": os.environ["OBS_ACCESS_KEY_ID"],
        "obs_secret_key": os.environ["OBS_SECRET_ACCESS_KEY"],
    }


