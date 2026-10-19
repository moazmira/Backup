import logging

from dbqueries import select_data
from dbqueries.snowflake import TABLES, quote_identifier
from services.snowflake_export import export_ddl, export_parquet
from storage.obs import transfer_files
from utils.files import path_component

logger = logging.getLogger("backup")


def list_tables(connection, database):
    tables = select_data(connection, TABLES.format(database=quote_identifier(database)))
    logger.info("Database %s: %d visible base tables", database, len(tables))
    if not tables:
        logger.warning("No visible base tables in %s; no data exported", database)
    return tables


def backup_table(connection, database, schema, table, run_dir):
    address = f"{quote_identifier(database)}.{quote_identifier(schema)}.{quote_identifier(table)}"
    folder = run_dir / path_component(database) / path_component(schema)
    folder.mkdir(parents=True, exist_ok=True)
    base_name = path_component(table)
    sql_file = folder / (base_name + ".sql")
    parquet_file = folder / (base_name + ".parquet")
    logger.info("Exporting Snowflake table: %s", address)
    export_ddl(connection, address, sql_file)
    rows = export_parquet(connection, address, parquet_file)
    return [sql_file, parquet_file], rows


def backup_snowflake(connection, settings, obs_client, obs_settings, run_dir, now):
    successes = failures = 0
    for database in settings["databases"]:
        try:
            tables = list_tables(connection, database)
        except Exception:
            failures += 1
            logger.exception("Table discovery failed: %s", database)
            continue
        for schema, table in tables:
            try:
                files, rows = backup_table(connection, database, schema, table, run_dir)
                base_name = "_".join(path_component(value) for value in (database, schema, table)) + f"_{now:%Y%m%d}"
                base_key = f"Snowflake/{path_component(database)}/{path_component(schema)}/{now:%Y/%m/%d}/{base_name}"
                transfer_files(obs_client, obs_settings, files, base_key)
                successes += 1
                logger.info("Table backup completed: %s.%s.%s rows=%d", database, schema, table, rows)
            except Exception:
                failures += 1
                logger.exception("Table backup failed: %s.%s.%s; inspect retained files and log", database, schema, table)
    logger.info("Snowflake finished: successful_tables=%d failed_tables=%d", successes, failures)
    return failures
