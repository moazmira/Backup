import logging
import os
import subprocess
from pathlib import Path

from psycopg2.extensions import make_dsn


logger = logging.getLogger("backup")


def run_tool(command, settings, env=None):
    result = subprocess.run(
        [str(value) for value in command], env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, errors="replace", timeout=settings.get("dump_timeout", 21600),
    )
    message = result.stderr.strip().replace(settings["password"], "[REDACTED]")
   
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed, exit={result.returncode}: {message}")
    if message:
        logger.warning("%s: %s", Path(command[0]).name, message)


def create_dump(settings, database, path, pg_dump):
    env = {
        **os.environ, "PGPASSWORD": settings["password"],
        "PGCONNECT_TIMEOUT": str(settings.get("connect_timeout", 30)),
        "PGSSLMODE": settings.get("sslmode", "prefer"),
    }

    env.pop("PGOPTIONS", None)
    
    command = [pg_dump, "--host", settings["host"], "--port", str(settings["port"]),
               "--username", settings["user"], "--no-password", "--format=custom",
               "--file", path, "--dbname", make_dsn(dbname=database)]
    logger.info("Creating complete database dump: database=%s file=%s", database, path)
    run_tool(command, settings, env)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("pg_dump produced an empty or missing file")
    logger.info("Dump created: %s bytes=%d", path, path.stat().st_size)

