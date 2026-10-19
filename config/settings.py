import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False, interpolate=False)
BACKUP_DIR = Path(os.getenv("BACKUP_OUTPUT_DIR", ROOT / "backups")).resolve()
LOG_DIR = Path(os.getenv("BACKUP_LOG_DIR", ROOT / "logs")).resolve()


def required(name):
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing setting: {name} (check .env)")
    return value


def get_databases(prefix):
    value = required(prefix + "DATABASES")
    databases = [name.strip() for name in value.split(",") if name.strip()]
    if not databases or len(set(databases)) != len(databases):
        raise ValueError(f"{prefix}DATABASES must be a non-empty list without duplicates")
    return databases


def load_postgres_config(connection_name):
    prefix = f"PG_{connection_name.upper()}_"
    settings = {
        "host": required(prefix + "HOST"),
        "port": int(os.getenv(prefix + "PORT", "5432")),
        "user": required(prefix + "USER"),
        "password": required(prefix + "PASSWORD"),
        "databases": get_databases(prefix),
        "sslmode": os.getenv(prefix + "SSLMODE", "prefer"),
        "connect_timeout": int(os.getenv(prefix + "CONNECT_TIMEOUT", "30")),
        "dump_timeout": int(os.getenv(prefix + "DUMP_TIMEOUT", "21600")),
        "pg_dump_path": os.getenv(prefix + "PG_DUMP_PATH") or os.getenv("PG_DUMP_PATH"),
    }
    if not 1 <= settings["port"] <= 65535:
        raise ValueError(prefix + "PORT must be between 1 and 65535")
    if settings["connect_timeout"] < 1 or settings["dump_timeout"] < 1:
        raise ValueError("PostgreSQL timeouts must be positive")
    if settings["sslmode"] not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
        raise ValueError(prefix + "SSLMODE is invalid")
    return settings


def load_snowflake_config(connection_name):
    prefix = f"SNOWFLAKE_{connection_name.upper()}_"
    settings = {
        "account": required(prefix + "ACCOUNT"),
        "user": required(prefix + "USER"),
        "warehouse": required(prefix + "WAREHOUSE"),
        "role": required(prefix + "ROLE"),
        "private_key_file": required(prefix + "PRIVATE_KEY_FILE"),
        "private_key_password": os.getenv(prefix + "PRIVATE_KEY_PASSWORD", ""),
        "databases": get_databases(prefix),
        "connect_timeout": int(os.getenv(prefix + "CONNECT_TIMEOUT", "30")),
        "query_timeout": int(os.getenv(prefix + "QUERY_TIMEOUT", "3600")),
    }
    if settings["connect_timeout"] < 1 or settings["query_timeout"] < 1:
        raise ValueError("Snowflake timeouts must be positive")
    return settings


def load_source_config(source, connection_name):
    if not re.fullmatch(r"[A-Za-z0-9_]+", connection_name):
        raise ValueError("Connection name must contain letters, numbers or underscores")
    if source == "postgres":
        return load_postgres_config(connection_name)
    if source == "snowflake":
        return load_snowflake_config(connection_name)
    raise ValueError("Source must be postgres or snowflake")


def load_obs_config():
    settings = {
        "endpoint": required("OBS_ENDPOINT"),
        "bucket": required("OBS_BUCKET"),
        "access_key_id": required("OBS_ACCESS_KEY_ID"),
        "secret_access_key": required("OBS_SECRET_ACCESS_KEY"),
        "timeout": int(os.getenv("OBS_TIMEOUT", "60")),
        "attempts": int(os.getenv("OBS_ATTEMPTS", "3")),
        "multipart_threshold_mb": int(os.getenv("OBS_MULTIPART_THRESHOLD_MB", "100")),
        "part_size_mb": int(os.getenv("OBS_PART_SIZE_MB", "64")),
        "upload_threads": int(os.getenv("OBS_UPLOAD_THREADS", "2")),
    }
    if not settings["endpoint"].startswith("https://"):
        raise ValueError("OBS_ENDPOINT must start with https://")
    if settings["timeout"] < 1:
        raise ValueError("OBS_TIMEOUT must be positive")
    if settings["attempts"] < 1:
        raise ValueError("OBS_ATTEMPTS must be positive")
    if not 1 <= settings["multipart_threshold_mb"] <= 5000:
        raise ValueError("OBS_MULTIPART_THRESHOLD_MB must be between 1 and 5000")
    if not 5 <= settings["part_size_mb"] <= 5000:
        raise ValueError("OBS_PART_SIZE_MB must be between 5 and 5000")
    if settings["upload_threads"] < 1:
        raise ValueError("OBS_UPLOAD_THREADS must be positive")
    return settings
