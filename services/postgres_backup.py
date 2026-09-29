import os
import subprocess
from datetime import datetime
from pathlib import Path


def create_dump(config, database, logger):
    output_dir = Path(__file__).resolve().parents[1] / "dumps"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_file = output_dir / f"{database}_{timestamp}.dump"
    if dump_file.exists():
        raise FileExistsError(f"Dump already exists: {dump_file}")

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

