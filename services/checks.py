from connections.postgres import connect_postgres
from connections.snowflake import connect_snowflake
from services.postgres_backup import find_pg_tools
from utils.database import select_data


def check_source(source, settings, logger):
    if source == "postgres":
        for database in settings["databases"]:
            connection = connect_postgres(settings, database, logger)
            try:
                major = int(select_data(connection, "SHOW server_version_num")[0][0]) // 10000
                find_pg_tools(settings, major, logger)
            finally:
                connection.close()
    else:
        connection = connect_snowflake(settings, logger)
        try:
            for database in settings["databases"]:
                address = '"' + database.replace('"', '""') + '"'
                with connection.cursor() as cursor:
                    cursor.execute("USE DATABASE " + address)
                logger.info("Snowflake database accessible: %s", database)
        finally:
            connection.close()
    logger.info("Source checks completed; export/restore permissions are not tested by this check")
