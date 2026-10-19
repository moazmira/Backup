import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from connections.postgres import connect_postgres
from dbqueries import select_data

logger = logging.getLogger("backup")


def tool_version(executable):
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=15)
    match = re.search(r"(\d+)\.(\d+)", result.stdout)
    if result.returncode or not match:
        raise RuntimeError(f"Cannot identify PostgreSQL client version: {executable}")
    return int(match.group(1))


def get_pg_tools(settings, database):
    connection = connect_postgres(settings, database)
    try:
        server_major = int(select_data(connection, "SHOW server_version_num")[0][0]) // 10000
    finally:
        connection.close()
    if server_major < 10:
        raise ValueError("This project requires PostgreSQL server 10 or newer")
    configured = settings.get("pg_dump_path")
    if configured:
        candidates = [Path(shutil.which(configured) or configured)]
    else:
        candidates = [Path(f"/usr/lib/postgresql/{server_major}/bin/pg_dump")]
        detected = shutil.which("pg_dump")
        if detected:
            candidates.append(Path(detected))
        candidates.extend(sorted(Path("/usr/lib/postgresql").glob("*/bin/pg_dump"), reverse=True))
    for pg_dump in candidates:
        if not pg_dump.is_file():
            continue
        client_major = tool_version(pg_dump)
        if client_major < server_major:
            continue
        pg_restore = pg_dump.with_name("pg_restore.exe" if pg_dump.suffix == ".exe" else "pg_restore")
        if not pg_restore.is_file() or tool_version(pg_restore) != client_major:
            raise RuntimeError(f"Matching pg_restore missing beside {pg_dump}")
        logger.info("PostgreSQL server major=%d client major=%d pg_dump=%s", server_major, client_major, pg_dump)
        return pg_dump, pg_restore
    raise RuntimeError(f"Install pg_dump >= {server_major} and its matching pg_restore, or set PG_DUMP_PATH")


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
