import logging
import os

from storage.obs import transfer_files
from utils.files import path_component
from utils.postgres_tools import get_pg_tools, run_tool

logger = logging.getLogger("backup")


def create_dump(settings, database, path, pg_dump):
    from psycopg2.extensions import make_dsn

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


def validate_dump(settings, path, pg_restore):
    logger.info("Validating dump archive: %s", path)
    run_tool([pg_restore, "--file", os.devnull, path], settings)
    logger.info("Dump archive read verified: %s", path)


def backup_postgres(settings, obs_client, obs_settings, run_dir, now):
    successes = failures = 0
    for database in settings["databases"]:
        temporary = None
        try:
            pg_dump, pg_restore = get_pg_tools(settings, database)
            folder = run_dir / path_component(database)
            folder.mkdir(exist_ok=False)
            path = folder / f"{path_component(database)}_{now:%Y%m%d_%H%M%S_%f}.dump"
            temporary = path.with_suffix(".dump.partial")
            create_dump(settings, database, temporary, pg_dump)
            validate_dump(settings, temporary, pg_restore)
            temporary.rename(path)
            base_key = (f"{path_component(settings['host'])}/{path_component(database)}/"
                        f"{now:%Y/%m/%d}/{path.stem}")
            transfer_files(obs_client, obs_settings, [path], base_key)
            successes += 1
            logger.info("Database backup completed: %s", database)
        except Exception:
            failures += 1
            logger.exception("Database backup failed: %s; inspect retained files and log", database)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    logger.info("PostgreSQL finished: successful_databases=%d failed_databases=%d", successes, failures)
    return failures
