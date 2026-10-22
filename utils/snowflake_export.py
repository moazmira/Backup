import logging
from multiprocessing import connection
from os import name
from unittest import result

import pyarrow as pa
import pyarrow.parquet as pq



def select_data(connection, query, params=None):
    """Read small metadata results using an already-open connection."""
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()



logger = logging.getLogger("backup")

TABLES = """
SELECT TABLE_SCHEMA, TABLE_NAME
FROM {database}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
  AND TABLE_SCHEMA <> 'INFORMATION_SCHEMA'
ORDER BY TABLE_SCHEMA, TABLE_NAME
"""
GET_DDL = "SELECT GET_DDL('TABLE', %s, TRUE)"



def get_tables(connection, database):
    tables = select_data(connection,TABLES.format(database=f'"{database}"'),)

    logger.info("Database %s: %d visible base tables", database, len(tables))

    if not tables:
        logger.warning("No visible base tables in %s; no data exported", database)
    return tables


def build_select_query(connection, address):
    columns = select_data(connection, "DESC TABLE " + address)
    expressions = []

    for column in columns:
        name = column[0]
        sqltype = column[1].upper()
        quoted = f'"{name}"'

        if sqltype.startswith("TIMESTAMP_TZ"):
            quoted = (
                f"TO_CHAR({quoted}, "
                f"'YYYY-MM-DD\"T\"HH24:MI:SS.FF9 TZH:TZM') "
                f"AS {quoted}"
            )

        expressions.append(quoted)

    query = "SELECT " + ", ".join(expressions) + " FROM " + address

    return {
        "query": query,
        "columns": columns,
    }



def save_table_sql(connection, address, path):

    logger.info("Creating SQL file: %s", path)

    ddl = select_data(connection, GET_DDL, (address,))[0][0]
    
    with path.open("x", encoding="utf-8") as stream:
        stream.write(ddl.rstrip() + "\n")
    logger.info("SQL file created: %s", path)


def set_numeric_column_types(column_types, columns):
    for index, column in enumerate(columns):
        sqltype = column[1].upper()

        if sqltype.startswith("NUMBER("):
            precision, scale = map(int, sqltype[7:-1].split(","))

            numeric_type = pa.decimal128(precision, scale)
            updated_column = column_types.field(index).with_type(numeric_type)
            column_types = column_types.set(index, updated_column)

    return column_types

def save_table_parquet(connection, address, path):
    logger.info("Creating Parquet file: %s", path)

    result = build_select_query(connection, address)
    query = result["query"]
    columns = result["columns"]

    temporary = path.with_suffix(".parquet.partial")
    rows = 0
    writer = None

    try:
        with connection.cursor() as cursor:
            cursor.execute(query)

            try:
                for batch in cursor.fetch_arrow_batches():
                    if batch is None:
                        continue

                    if writer is None:
                        column_types = set_numeric_column_types(
                            batch.schema, columns
                        )

                        writer = pq.ParquetWriter(
                            temporary,
                            column_types,
                            compression="snappy",
                            version="2.6",
                        )

                    writer.write_table(
                        batch.cast(column_types, safe=True)
                    )
                    rows += batch.num_rows

                if writer is None:
                    empty_table = cursor.fetch_arrow_all(
                        force_return_table=True
                    )

                    column_types = set_numeric_column_types(
                        empty_table.schema, columns
                    )

                    writer = pq.ParquetWriter(
                        temporary,
                        column_types,
                        compression="snappy",
                        version="2.6",
                    )

            finally:
                if writer is not None:
                    writer.close()

        written_rows = pq.ParquetFile(temporary).metadata.num_rows

        if written_rows != rows:
            raise RuntimeError(f"Parquet row count mismatch: {address}")

        temporary.rename(path)

    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    logger.info("Parquet file created: %s rows=%d", path, rows)
    return rows