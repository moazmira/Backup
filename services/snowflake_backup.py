import logging

from tomlkit import table

from connections.snowflake import connect_snowflake

from utils.backup_paths import create_run
from utils.obs_upload import transfer_files
from utils.snowflake_export import save_table_sql, save_table_parquet, get_tables

logger = logging.getLogger("backup")


def save_table_files(connection, database, schema, table, run_dir):
    
    address = f'"{database}"."{schema}"."{table}"'    

    folder = run_dir / database / schema
    
    folder.mkdir(parents=True, exist_ok=True)
    
    sql_file = folder / (table + ".sql")
    
    parquet_file = folder / (table + ".parquet")

    logger.info("Exporting Snowflake table: %s", address)

    save_table_sql(connection, address, sql_file)

    rows = save_table_parquet(connection, address, parquet_file)

    return [sql_file, parquet_file], rows


def backup_snowflake(settings, obs_client, obs_settings):
    now, run_dir = create_run("snowflake")
    logger.info("Backup started: source=snowflake output=%s", run_dir)

    connection = connect_snowflake(settings)

    try:
        for database in settings["databases"]:
            try:
                tables = get_tables(connection, database)

            except Exception:
                logger.exception("Table discovery failed: %s", database)
                continue

            for schema, table in tables:
                try:
                    files, rows = save_table_files(
                        connection, database, schema, table, run_dir
                    )

                    base_name = "_".join((database, schema, table)) + (
                        f"_{now:%Y%m%d_%H%M%S_%f}"
                    )

                    base_key = (
                        f"Snowflake/{database}/{schema}/"
                        f"{now:%Y/%m/%d}/{base_name}"
                    )

                    transfer_files(
                        obs_client, obs_settings, files, base_key
                    )

                    logger.info(
                        "Table backup completed: %s.%s.%s rows=%d",
                        database, schema, table, rows,
                    )

                except Exception:
                    logger.exception(
                        "Table backup failed: %s.%s.%s",
                        database, schema, table,
                    )

    finally:
        connection.close()
        logger.info("Snowflake connection closed")