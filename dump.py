import os
import logging
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

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


def setup_logger():
    log_dir = Path(__file__).with_name("logs")
    log_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file = log_dir / f"dump_{run_id}_{uuid.uuid4().hex[:6]}.log"

    logger = logging.getLogger("postgres_dump")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.info("Run started. Log file: %s", log_file)
    return logger


def create_dump(config, database, logger):
    output_dir = Path(__file__).with_name("dumps")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
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

    logger.info("[%s] Connecting and creating dump: %s", database, dump_file)
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"pg_dump failed (exit {result.returncode}): {result.stderr.strip()}")
        if not dump_file.exists() or dump_file.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty or missing dump")
    except Exception:
        dump_file.unlink(missing_ok=True)
        raise

    logger.info("[%s] PostgreSQL connection successful (pg_dump completed)", database)
    logger.info("[%s] Dump created successfully: %s (%d bytes)",
                database, dump_file, dump_file.stat().st_size)
    return dump_file


def main():
    logger = setup_logger()
    try:
        config = load_config()
        logger.info("Databases requested: %s", ", ".join(config["databases"]))
        for database in config["databases"]:
            logger.info("[%s] Starting backup", database)
            create_dump(config, database, logger)
        logger.info("Run completed successfully: %d database(s)", len(config["databases"]))
    except Exception:
        logger.exception("Run failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
