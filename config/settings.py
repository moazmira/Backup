import json
from pathlib import Path

SECRET_DIR = Path(__file__).resolve().parents[1] / "secret"


def read_json(filename):
    path = SECRET_DIR / filename
    try:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        raise ValueError(f"Missing settings file: {path}") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {filename}, line {error.lineno}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{filename} must contain a JSON object")
    return data


def require_fields(settings, fields, label):
    for field in fields:
        value = settings.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}: {field} must be a non-empty string")


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
        raise ValueError(f"{source}: databases must be a non-empty list")
    if any(not isinstance(name, str) or not name.strip() for name in databases):
        raise ValueError(f"{source}: each database must be a non-empty string")
    if len(set(databases)) != len(databases):
        raise ValueError(f"{source}: duplicate database names")
    if source == "postgres":
        port = settings.get("port")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("postgres: port must be an integer between 1 and 65535")
    elif not isinstance(settings.get("private_key_password", ""), str):
        raise ValueError("snowflake: private_key_password must be a string")
    return settings


def load_obs_config():
    settings = read_json("obs.json")
    require_fields(settings, ("endpoint", "bucket", "access_key_id", "secret_access_key"), "OBS")
    return settings
