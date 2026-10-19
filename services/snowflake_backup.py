from dbqueries.snowflake import TABLES
from services.snowflake_export import export_ddl, export_parquet, quote_identifier
from storage.obs import transfer_files
from utils.database import select_data
from utils.files import path_component, save_summary


def list_tables(connection, database, logger):
    logger.info("Listing visible Snowflake base tables: database=%s", database)
    query = TABLES.format(database=quote_identifier(database))
    tables = select_data(connection, query)
    logger.info("Database %s: %d visible base tables", database, len(tables))
    return tables


def backup_table(connection, database, schema, table, run_dir, now, logger):
    address = ".".join(quote_identifier(x) for x in (database, schema, table))
    folder = run_dir / path_component(database) / path_component(schema)
    folder.mkdir(parents=True, exist_ok=True)
    stem = path_component(table)
    sql_file, parquet_file = folder / (stem + ".sql"), folder / (stem + ".parquet")
    logger.info("Exporting Snowflake table: %s", address)
    export_ddl(connection, address, sql_file, logger)
    rows = export_parquet(connection, address, parquet_file, logger)
    return [sql_file, parquet_file], rows


def backup_snowflake(connection, settings, obs_client, obs_settings, run_dir, now, summary, logger, mode, keep_local):
    for database in settings["databases"]:
        try:
            tables = list_tables(connection, database, logger)
        except Exception:
            summary["units"].append({"database": database, "status": "failed", "stage": "discovery"})
            logger.exception("Table discovery failed: %s", database)
            save_summary(run_dir, summary)
            continue
        if not tables:
            logger.warning("No visible base tables in %s; no data exported", database)
            summary["units"].append({"database": database, "status": "empty", "tables": 0})
            save_summary(run_dir, summary)
        for schema, table in tables:
            unit = {"database": database, "schema": schema, "table": table, "status": "failed"}
            try:
                files, rows = backup_table(connection, database, schema, table, run_dir, now, logger)
                unit.update({"rows": rows, "local_files": [str(p) for p in files]})
                if mode == "backup":
                    stem = "_".join(path_component(x) for x in (database, schema, table)) + f"_{now:%Y%m%d}"
                    base = f"Snowflake/{path_component(database)}/{now:%Y/%m/%d}/{stem}"
                    unit["upload"] = transfer_files(obs_client, obs_settings, files, base, logger, keep_local)
                unit["status"] = "complete" if mode == "backup" else "local_ready"
                logger.info("Table backup completed: %s.%s.%s rows=%d", database, schema, table, rows)
            except Exception:
                logger.exception("Table backup failed: %s.%s.%s; inspect retained files and log", database, schema, table)
            summary["units"].append(unit)
            save_summary(run_dir, summary)
