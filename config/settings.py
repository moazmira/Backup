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
    """Accept existing Snowflake settings and use the proven DER key loader."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    def value(*names):
        for name in names:
            result = os.getenv(name, '').strip()
            if result:
                return result
        return ''
    def required(*names):
        result = value(*names)
        if not result:
            raise ValueError('Missing ' + ' or '.join(names) + ' in .env')
        return result
    databases = [x.strip() for x in required(
        'SNOWFLAKE_DATABASES', 'SNOWFLAKE_BRONZE_DATABASE').split(',') if x.strip()]
    connection = {
        'account': required('SNOWFLAKE_ACCOUNT'),
        'user': required('SNOWFLAKE_USER'),
        'warehouse': required('SNOWFLAKE_BRONZE_WAREHOUSE', 'SNOWFLAKE_WAREHOUSE'),
        'database': databases[0],
        'session_parameters': {'TIMEZONE': 'UTC'},
        'arrow_number_to_decimal': True,
    }
    if value('SNOWFLAKE_ROLE'):
        connection['role'] = value('SNOWFLAKE_ROLE')
    if value('SNOWFLAKE_SCHEMA'):
        connection['schema'] = value('SNOWFLAKE_SCHEMA')
    key_path = value('SNOWFLAKE_PRIVATE_KEY_PATH', 'SNOWFLAKE_PRIVATE_KEY_FILE')
    if key_path:
        from cryptography.hazmat.primitives import serialization
        passphrase = os.getenv('SNOWFLAKE_PRIVATE_KEY_PASSWORD') or None
        with open(key_path, 'rb') as stream:
            key = serialization.load_pem_private_key(
                stream.read(), password=passphrase.encode() if passphrase else None)
        connection['private_key'] = key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption())
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
