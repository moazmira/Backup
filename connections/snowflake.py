from pathlib import Path

from config.settings import SECRET_DIR


def load_private_key(settings, logger):
    from cryptography.hazmat.primitives import serialization

    path = Path(settings["private_key_file"]).expanduser()
    if not path.is_absolute():
        path = SECRET_DIR / path
    logger.info("Loading Snowflake private key")
    password = settings.get("private_key_password") or None
    with path.open("rb") as stream:
        key = serialization.load_pem_private_key(
            stream.read(), password=password.encode() if password else None
        )
    private_key = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    logger.info("Snowflake private key loaded")
    return private_key


def connect_snowflake(settings, logger):
    import snowflake.connector

    private_key = load_private_key(settings, logger)
    logger.info("Connecting to Snowflake: account=%s", settings["account"])
    connection = snowflake.connector.connect(
        account=settings["account"],
        user=settings["user"],
        warehouse=settings["warehouse"],
        role=settings["role"],
        private_key=private_key,
        arrow_number_to_decimal=True,
        login_timeout=settings.get("connect_timeout", 30),
        network_timeout=30,
        session_parameters={"TIMEZONE": "UTC", "STATEMENT_TIMEOUT_IN_SECONDS": settings.get("query_timeout", 3600)},
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
            user, role, warehouse = cursor.fetchone()
            logger.info("Snowflake connected: user=%s role=%s warehouse=%s", user, role, warehouse)
        return connection
    except Exception:
        connection.close()
        raise
