def connect_postgres(settings, database, logger):
    import psycopg2

    logger.info("Connecting to PostgreSQL: host=%s database=%s", settings["host"], database)
    connection = psycopg2.connect(
        host=settings["host"], port=settings["port"], user=settings["user"],
        password=settings["password"], dbname=database,
        sslmode=settings.get("sslmode", "prefer"),
        connect_timeout=settings.get("connect_timeout", 30),
        options="-c statement_timeout=30000",
    )
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, current_setting('server_version')")
            name, user, version = cursor.fetchone()
        logger.info("PostgreSQL connected: database=%s user=%s version=%s", name, user, version)
        return connection
    except Exception:
        connection.close()
        raise
