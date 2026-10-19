import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_DIR = Path(os.getenv("BACKUP_SECRET_DIR", ROOT / "secret")).resolve()
BACKUP_DIR = Path(os.getenv("BACKUP_OUTPUT_DIR", ROOT / "backups")).resolve()
LOG_DIR = Path(os.getenv("BACKUP_LOG_DIR", ROOT / "logs")).resolve()


def read_json(filename):
    path = SECRET_DIR / filename
    try:
        with path.open(encoding="utf-8") as stream:
            settings = json.load(stream)
    except FileNotFoundError:
        raise ValueError(f"Missing settings file: {path}") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {filename}, line {error.lineno}") from None
    if not isinstance(settings, dict):
        raise ValueError(f"{filename} must contain a JSON object")
    return settings


def require_fields(settings, fields, label):
    for field in fields:
        value = settings.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}: {field} must be a non-empty string")


def positive_integer(settings, key, default, minimum=1, maximum=None):
    value = settings.get(key, default)
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{key} must be an integer between {minimum} and {maximum or 'no upper limit'}")
    settings[key] = value


def load_source_config(source, connection_name):
    if source not in ("postgres", "snowflake"):
        raise ValueError("Source must be postgres or snowflake")
    connections = read_json(f"{source}.json")
    if connection_name not in connections:
        raise ValueError(f"Connection '{connection_name}' not found in {source}.json")
    settings = connections[connection_name]
    if not isinstance(settings, dict):
        raise ValueError("Connection settings must be a JSON object")
    fields = ("host", "user", "password") if source == "postgres" else (
        "account", "user", "warehouse", "role", "private_key_file")
    require_fields(settings, fields, source)
    databases = settings.get("databases")
    if not isinstance(databases, list) or not databases:
        raise ValueError("databases must be a non-empty list")
    if any(not isinstance(name, str) or not name.strip() for name in databases):
        raise ValueError("Each database must be a non-empty string")
    if len(set(databases)) != len(databases):
        raise ValueError("Duplicate database names")
    positive_integer(settings, "connect_timeout", 30)
    if source == "postgres":
        positive_integer(settings, "port", 5432, maximum=65535)
        positive_integer(settings, "dump_timeout", 21600)
        settings.setdefault("sslmode", "prefer")
        if settings["sslmode"] not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
            raise ValueError("Invalid PostgreSQL sslmode")
    else:
        positive_integer(settings, "query_timeout", 3600)
        if not isinstance(settings.get("private_key_password", ""), str):
            raise ValueError("private_key_password must be a string")
    return settings


def load_obs_config():
    settings = read_json("obs.json")
    require_fields(settings, ("endpoint", "bucket", "access_key_id", "secret_access_key"), "OBS")
    if not settings["endpoint"].startswith("https://"):
        raise ValueError("OBS endpoint must start with https://")
    positive_integer(settings, "timeout", 60)
    positive_integer(settings, "attempts", 3, maximum=10)
    positive_integer(settings, "multipart_threshold_mb", 100, maximum=5000)
    positive_integer(settings, "part_size_mb", 64, minimum=5, maximum=5000)
    positive_integer(settings, "upload_threads", 2, maximum=16)
    return settings
