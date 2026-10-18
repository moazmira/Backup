import argparse

from config.settings import load_obs_config, load_source_config
from connections.obs import connect_obs
from connections.postgres import connect_postgres
from connections.snowflake import connect_snowflake
from utils.logger import setup_logger


def main():
    parser = argparse.ArgumentParser(description="Local Snowflake export or PostgreSQL connection check")
    parser.add_argument("--source", choices=("postgres", "snowflake"), required=True)
    parser.add_argument("--connection", required=True)
    args = parser.parse_args()
    logger = setup_logger()
    try:
        logger.info("Reading %s settings", args.source)
        source_config = load_source_config(args.source, args.connection)
        logger.info("Connection selected: %s", args.connection)
        logger.info("Databases: %s", ", ".join(source_config["databases"]))
        if args.source == "postgres":
            for database in source_config["databases"]:
                connection = connect_postgres(source_config, database, logger)
                try:
                    logger.info("PostgreSQL connection check completed: %s", database)
                finally:
                    connection.close()
                    logger.info("PostgreSQL connection closed: %s", database)
        else:
            from services.snowflake_backup import export_databases

            connection = connect_snowflake(source_config, logger)
            try:
                export_databases(connection, source_config["databases"], logger)
            finally:
                connection.close()
                logger.info("Snowflake connection closed")
            return 0

        logger.info("Reading OBS settings")
        obs_config = load_obs_config()
        logger.info("OBS bucket: %s", obs_config["bucket"])
        client = connect_obs(obs_config, logger)
        try:
            logger.info("OBS connection check completed")
        finally:
            client.close()
            logger.info("OBS connection closed")
        logger.info("All connection checks completed successfully")
        return 0
    except Exception:
        logger.exception("Run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
