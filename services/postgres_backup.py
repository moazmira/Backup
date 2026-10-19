import os
import re
import shutil
import subprocess
from pathlib import Path

from connections.postgres import connect_postgres
from storage.obs import transfer_files
from utils.database import select_data
from utils.files import path_component, save_summary


def check_tool_version(executable):
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f"Cannot run PostgreSQL client: {executable}")
    match = re.search(r"(\d+)\.(\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Cannot identify client version: {executable}")
    return int(match.group(1))


def find_pg_tools(settings, major, logger):
    configured = os.getenv("PG_DUMP_PATH") or settings.get("pg_dump_path")
    if configured:
        executable = shutil.which(configured)
        candidates = [Path(executable)] if executable else [Path(configured)]
    else:
        candidates = [Path(f"/usr/lib/postgresql/{major}/bin/pg_dump")]
        detected = shutil.which("pg_dump")
        if detected:
            candidates.append(Path(detected))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        version = check_tool_version(candidate)
        if version != major:
            logger.warning("Skipping pg_dump major=%d; server major=%d", version, major)
            continue
        restore = candidate.with_name("pg_restore.exe" if candidate.suffix == ".exe" else "pg_restore")
        if not restore.is_file() or check_tool_version(restore) != major:
            raise RuntimeError(f"Matching pg_restore missing beside {candidate}")
        logger.info("PostgreSQL client matched: major=%d pg_dump=%s", major, candidate)
        return candidate, restore
    raise RuntimeError(
        f"PostgreSQL {major} pg_dump/pg_restore required. Install matching clients or set pg_dump_path. "
        "Runtime does not install system packages."
    )


def run_tool(command, settings, logger, env=None):
    result = subprocess.run(
        [str(x) for x in command], env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, errors="replace",
        timeout=settings.get("dump_timeout", 21600),
    )
    message = result.stderr.strip().replace(settings["password"], "[REDACTED]")
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed, exit={result.returncode}: {message}")
    if message:
        logger.warning("%s: %s", Path(command[0]).name, message)


def create_dump(settings, database, run_dir, now, logger):
    from psycopg2.extensions import make_dsn

    connection = connect_postgres(settings, database, logger)
    try:
        version_num = int(select_data(connection, "SHOW server_version_num")[0][0])
    finally:
        connection.close()
        logger.info("PostgreSQL version-check connection closed: %s", database)
    major = version_num // 10000
    if major < 10:
        raise ValueError("This project requires PostgreSQL server 10 or newer")
    pg_dump, pg_restore = find_pg_tools(settings, major, logger)
    folder = run_dir / path_component(database)
    folder.mkdir(exist_ok=False)
    path = folder / f"{path_component(database)}_{now:%Y%m%d_%H%M%S_%f}.dump"
    temporary = path.with_suffix(".dump.partial")
    env = {
        **os.environ, "PGPASSWORD": settings["password"],
        "PGCONNECT_TIMEOUT": str(settings.get("connect_timeout", 30)),
        "PGSSLMODE": settings.get("sslmode", "prefer"),
    }
    # Ignore an inherited short statement_timeout from unrelated shell settings.
    env.pop("PGOPTIONS", None)
    command = [pg_dump, "--host", settings["host"], "--port", str(settings["port"]),
               "--username", settings["user"], "--no-password", "--format=custom",
               "--file", temporary, "--dbname", make_dsn(dbname=database)]
    logger.info("Creating complete database dump: database=%s file=%s", database, path)
    try:
        run_tool(command, settings, logger, env)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty or missing file")
        logger.info("Validating dump archive by reading it with pg_restore: %s", database)
        run_tool([pg_restore, "--file", os.devnull, temporary], settings, logger)
        temporary.rename(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    logger.info("Dump created and archive read verified: %s bytes=%d", path, path.stat().st_size)
    return path


def backup_postgres(settings, obs_client, obs_settings, run_dir, now, summary, logger, mode, keep_local):
    for database in settings["databases"]:
        unit = {"database": database, "status": "failed"}
        try:
            path = create_dump(settings, database, run_dir, now, logger)
            unit["local_files"] = [str(path)]
            if mode == "backup":
                base = (f"{path_component(settings['host'])}/{path_component(database)}/"
                        f"{now:%Y/%m/%d}/{path.stem}")
                unit["upload"] = transfer_files(obs_client, obs_settings, [path], base, logger, keep_local)
            unit["status"] = "complete" if mode == "backup" else "local_ready"
            logger.info("Database backup completed: %s", database)
        except Exception:
            logger.exception("Database backup failed: %s; complete local files retained", database)
        summary["units"].append(unit)
        save_summary(run_dir, summary)
