from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from services.snowflake_export import export_ddl, export_parquet, quote_identifier

BACKUP_DIR = Path(__file__).resolve().parents[1] / "backups" / "snowflake"


def path_component(name):
    """Keep normal names readable and encode path separators and dots."""
    return quote(name, safe="_").replace(".", "%2E")


def list_tables(connection, database, logger):
    logger.info("Listing Snowflake base tables: database=%s", database)
    query = (
        f"SELECT TABLE_SCHEMA, TABLE_NAME FROM {quote_identifier(database)}.INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA <> 'INFORMATION_SCHEMA' ORDER BY 1, 2"
    )
    with connection.cursor() as cursor:
        cursor.execute(query)
        tables = cursor.fetchall()
    logger.info("Database %s: %d visible base tables", database, len(tables))
    if not tables:
        logger.warning("No visible base tables found: %s", database)
    return tables


def export_databases(connection, databases, logger):
    now = datetime.now(ZoneInfo("Africa/Cairo"))
    run_dir = BACKUP_DIR / now.strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    logger.info("Local export started. Output directory: %s", run_dir)
    successes = failures = 0
    for database in databases:
        try:
            tables = list_tables(connection, database, logger)
        except Exception:
            failures += 1
            logger.exception("Failed to list tables: database=%s", database)
            continue
        for schema, table in tables:
            address = ".".join(quote_identifier(x) for x in (database, schema, table))
            try:
                folder = run_dir / path_component(database) / path_component(schema)
                folder.mkdir(parents=True, exist_ok=True)
                stem = path_component(table)
                logger.info("Exporting table: %s", address)
                export_ddl(connection, address, folder / (stem + ".sql"), logger)
                export_parquet(connection, address, folder / (stem + ".parquet"), logger)
                successes += 1
                logger.info("Table export completed: %s", address)
            except Exception:
                failures += 1
                logger.exception("Table export failed: %s; complete files retained", address)
    logger.info("Local export finished: successful_tables=%d failures=%d output=%s", successes, failures, run_dir)
    if failures:
        raise RuntimeError(f"Local export had {failures} failure(s); see log and {run_dir}")
    return run_dir
