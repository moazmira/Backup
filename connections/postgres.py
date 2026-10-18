def connect_postgres(settings, database, logger):
    import psycopg2

    logger.info("Connecting to PostgreSQL: host=%s database=%s", settings["host"], database)
    connection = psycopg2.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        dbname=database,
        connect_timeout=15,
        options="-c statement_timeout=15000",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, current_setting('server_version')")
            database_name, user, version = cursor.fetchone()
        logger.info("PostgreSQL connected: database=%s user=%s version=%s", database_name, user, version)
        return connection
    except Exception:
        connection.close()
        raise
