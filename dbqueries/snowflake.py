from dbqueries import select_data

TABLES = """
SELECT TABLE_SCHEMA, TABLE_NAME
FROM {database}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
  AND TABLE_SCHEMA <> 'INFORMATION_SCHEMA'
ORDER BY TABLE_SCHEMA, TABLE_NAME
"""
GET_DDL = "SELECT GET_DDL('TABLE', %s, TRUE)"


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def export_query(connection, address):
    columns = select_data(connection, "DESC TABLE " + address)
    expressions = []
    for column in columns:
        name, sqltype = column[0], column[1].upper()
        quoted = quote_identifier(name)
        # Arrow has a single timezone per column, whereas Snowflake TZ can have
        # different offsets in different rows. Preserve those offsets explicitly.
        if sqltype.startswith("TIMESTAMP_TZ"):
            quoted = f"TO_CHAR({quoted}, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF9 TZH:TZM') AS {quoted}"
        expressions.append(quoted)
    return "SELECT " + ", ".join(expressions) + " FROM " + address, columns
