import os
import logging
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from obs import ObsClient


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
        "obs_bucket": os.environ["OBS_BUCKET"],
        "obs_endpoint": os.environ["OBS_ENDPOINT"],
        "obs_access_key": os.environ["OBS_ACCESS_KEY_ID"],
        "obs_secret_key": os.environ["OBS_SECRET_ACCESS_KEY"],
    }


def setup_logger():
    log_dir = Path(__file__).with_name("logs")
    log_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_file = output_dir / f"{database}_{timestamp}_{uuid.uuid4().hex[:6]}.dump"

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


def connect_to_obs(config, logger):
    client = ObsClient(
        access_key_id=config["obs_access_key"],
        secret_access_key=config["obs_secret_key"],
        server=config["obs_endpoint"],
    )
    # A real API request confirms that the credentials and bucket are usable.
    try:
        result = client.listObjects(config["obs_bucket"], max_keys=1)
        if not 200 <= result.status < 300:
            raise RuntimeError(
                f"OBS connection failed: HTTP {result.status} "
                f"{result.errorCode}: {result.errorMessage}"
            )
    except Exception:
        client.close()
        raise
    logger.info("Connected to OBS bucket: %s", config["obs_bucket"])
    return client


def upload_dump(client, config, database, dump_file, logger):
    # The date is taken from this dump's timestamp so the path matches its name.
    date = dump_file.name[len(database) + 1:][:8]
    object_key = f"{database}/{date[:4]}/{date[4:6]}/{date[6:8]}/{dump_file.name}"
    bucket = config["obs_bucket"]
    size = dump_file.stat().st_size
    if size > 5 * 1024**3:
        raise RuntimeError("Dump exceeds the 5 GiB single-upload limit")
    logger.info("[%s] Uploading to obs://%s/%s", database, bucket, object_key)

    result = client.putFile(bucket, object_key, str(dump_file))
    if not 200 <= result.status < 300:
        raise RuntimeError(
            f"OBS upload failed: HTTP {result.status} "
            f"{result.errorCode}: {result.errorMessage}"
        )

    metadata = client.getObjectMetadata(bucket, object_key)
    if not 200 <= metadata.status < 300:
        raise RuntimeError(
            f"OBS verification failed: HTTP {metadata.status} "
            f"{metadata.errorCode}: {metadata.errorMessage}"
        )
    remote_size = int(metadata.body.contentLength)
    if remote_size != size:
        raise RuntimeError(f"OBS size mismatch: local={size}, uploaded={remote_size}")

    logger.info("[%s] Upload verified: %d bytes", database, remote_size)
    dump_file.unlink()
    logger.info("[%s] Local dump deleted", database)


def main():
    logger = setup_logger()
    client = None
    try:
        config = load_config()
        logger.info("Databases requested: %s", ", ".join(config["databases"]))
        client = connect_to_obs(config, logger)
        for database in config["databases"]:
            logger.info("[%s] Starting backup", database)
            dump_file = create_dump(config, database, logger)
            upload_dump(client, config, database, dump_file, logger)
        logger.info("Run completed successfully: %d database(s)", len(config["databases"]))
    except Exception:
        logger.exception("Run failed")
        raise SystemExit(1)
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
