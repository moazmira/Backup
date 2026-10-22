import logging
from pathlib import Path

import snowflake.connector

from config.settings import ROOT
from utils.snowflake_export import select_data

logger = logging.getLogger("backup")


def connect_snowflake(settings):

    key_file = Path(settings["private_key_file"]).expanduser()
    if not key_file.is_absolute():
        key_file = ROOT / key_file
    if not key_file.is_file():
        raise FileNotFoundError(f"Snowflake private key not found: {key_file}")
    
    logger.info("Connecting to Snowflake: account=%s", settings["account"])

    connection = snowflake.connector.connect(
        account=settings["account"],
        user=settings["user"],
        warehouse=settings["warehouse"],
        role=settings["role"],
        private_key_file=str(key_file),
        private_key_file_pwd=settings["private_key_password"] or None,
        arrow_number_to_decimal=True,
        login_timeout=settings["connect_timeout"],
        network_timeout=30,
        session_parameters={"TIMEZONE": "UTC", "STATEMENT_TIMEOUT_IN_SECONDS": settings["query_timeout"]},
    )
    try:
        user, role, warehouse = select_data(
            connection, "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()"
        )[0]
        logger.info("Snowflake connected: user=%s role=%s warehouse=%s", user, role, warehouse)
        return connection
    except Exception:
        connection.close()
        raise

