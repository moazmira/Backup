import os
from pathlib import Path
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = Path(os.getenv("BACKUP_OUTPUT_DIR", ROOT / "backups")).resolve()
LOG_DIR = Path(os.getenv("BACKUP_LOG_DIR", ROOT / "logs")).resolve()

load_dotenv(ROOT / ".env", override=False, interpolate=False)

def get_databases(prefix):
    value = os.getenv(prefix + "DATABASES")
    databases = [name.strip() for name in value.split(",") if name.strip()]
    if not databases or len(set(databases)) != len(databases):
        raise ValueError(f"{prefix}DATABASES must be a non-empty list without duplicates")
    return databases


def load_postgres_config(connection_name):
    prefix = f"PG_{connection_name.upper()}_"
    settings = {
        "host": os.getenv(prefix + "HOST"),
        "port": int(os.getenv(prefix + "PORT", "5432")),
        "user": os.getenv(prefix + "USER"),
        "password": os.getenv(prefix + "PASSWORD"),
        "databases": get_databases(prefix),
        "sslmode": os.getenv(prefix + "SSLMODE", "prefer"),
        "connect_timeout": int(os.getenv(prefix + "CONNECT_TIMEOUT", "30")),
        "dump_timeout": int(os.getenv(prefix + "DUMP_TIMEOUT", "21600")),
        "pg_dump_path": os.getenv(prefix + "PG_DUMP_PATH") or os.getenv("PG_DUMP_PATH"),
    }
    return settings


def load_snowflake_config():
    settings = {
        "account": os.getenv("SNOWFLAKE_ACCOUNT"),
        "user": os.getenv("SNOWFLAKE_USER"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
        "role": os.getenv("SNOWFLAKE_ROLE"),
        "private_key_file": os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE"),
        "private_key_password": os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSWORD", ""),
        "databases": get_databases("SNOWFLAKE_"),
        "connect_timeout": int(os.getenv("SNOWFLAKE_CONNECT_TIMEOUT", "30")),
        "query_timeout": int(os.getenv("SNOWFLAKE_QUERY_TIMEOUT", "3600")),
    }
    return settings


def load_source_config(source, connection_name=None):
    if source == "postgres":
        if not connection_name:
            raise ValueError("--connection is required for postgres")
        return load_postgres_config(connection_name)

    elif source == "snowflake":
        return load_snowflake_config()

    raise ValueError("Source must be postgres or snowflake")


def load_obs_config():
    settings = {
        "endpoint": os.getenv("OBS_ENDPOINT"),
        "bucket": os.getenv("OBS_BUCKET"),
        "access_key_id": os.getenv("OBS_ACCESS_KEY_ID"),
        "secret_access_key": os.getenv("OBS_SECRET_ACCESS_KEY"),
        "timeout": int(os.getenv("OBS_TIMEOUT", "60")),
        "attempts": int(os.getenv("OBS_ATTEMPTS", "3")),
        "multipart_threshold_mb": int(os.getenv("OBS_MULTIPART_THRESHOLD_MB", "100")),
        "part_size_mb": int(os.getenv("OBS_PART_SIZE_MB", "64")),
        "upload_threads": int(os.getenv("OBS_UPLOAD_THREADS", "2")),
    }
    return settings
