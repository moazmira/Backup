def select_data(connection, query, params=None):
    """Fetch small metadata results. The caller owns the connection."""
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()
