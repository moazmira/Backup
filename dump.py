import os
import subprocess
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def load_config():
    load_dotenv(Path(__file__).with_name(".env"))
    databases = [
        name.strip()
        for name in os.environ["PG_DATABASES"].split(",")
        if name.strip()
    ]
    if not databases:
        raise ValueError("PG_DATABASES is empty")

    return {
        "host": os.environ["PG_HOST"],
        "port": os.getenv("PG_PORT", "5432"),
        "user": os.environ["PG_USER"],
        "password": os.environ["PG_PASSWORD"],
        "databases": databases,
        "pg_dump": os.getenv("PG_DUMP_PATH", "pg_dump"),
    }


def check_connection(config, database):
    with psycopg.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        dbname=database,
        connect_timeout=10,
    ) as connection:
        connection.execute("SELECT 1").fetchone()


def create_dump(config, database):
    output_dir = Path(__file__).with_name("dumps")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_file = output_dir / f"{database}_{timestamp}.dump"

    command = [
        config["pg_dump"],
        "--host", config["host"],
        "--port", config["port"],
        "--username", config["user"],
        "--format=custom",
        "--file", str(dump_file),
        database,
    ]
    env = {**os.environ, "PGPASSWORD": config["password"]}

    try:
        subprocess.run(command, env=env, check=True)
        if dump_file.stat().st_size == 0:
            raise RuntimeError(f"Dump is empty: {dump_file}")
    except Exception:
        dump_file.unlink(missing_ok=True)
        raise

    return dump_file


def main():
    config = load_config()
    for database in config["databases"]:
        print(f"[{database}] Checking connection...", flush=True)
        check_connection(config, database)
        print(f"[{database}] Creating dump...", flush=True)
        dump_file = create_dump(config, database)
        print(f"[{database}] Done: {dump_file} ({dump_file.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    main()
