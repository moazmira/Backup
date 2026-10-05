import os
from pathlib import Path

from dotenv import load_dotenv


def load_config():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
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
        "port": os.environ["PG_PORT"],
        "user": os.environ["PG_USER"],
        "password": os.environ["PG_PASSWORD"],
        "databases": databases,
        "pg_dump": os.environ["PG_DUMP_PATH"],
        "obs_bucket": os.environ["OBS_BUCKET"],
        "obs_endpoint": os.environ["OBS_ENDPOINT"],
        "obs_access_key": os.environ["OBS_ACCESS_KEY_ID"],
        "obs_secret_key": os.environ["OBS_SECRET_ACCESS_KEY"],
    }


def load_snowflake_config():
    """Snowflake-only runs do not require PG_* variables."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    def required(name):
        value = os.getenv(name, '').strip()
        if not value:
            raise ValueError(f'Missing {name} in .env')
        return value
    databases = [x.strip() for x in required('SNOWFLAKE_DATABASES').split(',') if x.strip()]
    connection = {
        'account': required('SNOWFLAKE_ACCOUNT'),
        'user': required('SNOWFLAKE_USER'),
        'role': required('SNOWFLAKE_ROLE'),
        'warehouse': required('SNOWFLAKE_WAREHOUSE'),
        'session_parameters': {'TIMEZONE': 'UTC'},
        'arrow_number_to_decimal': True,
    }
    if os.getenv('SNOWFLAKE_PRIVATE_KEY_FILE'):
        connection['private_key_file'] = os.getenv('SNOWFLAKE_PRIVATE_KEY_FILE')
        if os.getenv('SNOWFLAKE_PRIVATE_KEY_PASSWORD'):
            connection['private_key_file_pwd'] = os.getenv('SNOWFLAKE_PRIVATE_KEY_PASSWORD')
    else:
        connection['password'] = required('SNOWFLAKE_PASSWORD')
    return {
        'snowflake_databases': databases,
        'snowflake_connection': connection,
        'obs_bucket': required('OBS_BUCKET'),
        'obs_endpoint': required('OBS_ENDPOINT'),
        'obs_access_key': required('OBS_ACCESS_KEY_ID'),
        'obs_secret_key': required('OBS_SECRET_ACCESS_KEY'),
    }
