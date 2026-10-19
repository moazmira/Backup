import logging

import pyarrow as pa
import pyarrow.parquet as pq

from dbqueries import select_data
from dbqueries.snowflake import GET_DDL, export_query

logger = logging.getLogger("backup")


def export_ddl(connection, address, path):
    logger.info("Creating SQL file: %s", path)
    ddl = select_data(connection, GET_DDL, (address,))[0][0]
    if not isinstance(ddl, str) or not ddl.strip():
        raise RuntimeError(f"Empty DDL for {address}")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(ddl.rstrip() + "\n")
    logger.info("SQL file created: %s", path)


def numeric_schema(schema, columns):
    """Only NUMBER needs normalization: Connector integer width varies by batch,
    and its empty-table NUMBER type defaults to int64, even for scaled decimals.
    Other Arrow types are used directly; no full type mapping is maintained.
    """
    for index, column in enumerate(columns):
        sqltype = column[1].upper()
        if sqltype.startswith("NUMBER("):
            precision, scale = map(int, sqltype[7:-1].split(","))
            schema = schema.set(index, schema.field(index).with_type(pa.decimal128(precision, scale)))
    return schema


def export_parquet(connection, address, path):
    logger.info("Creating Parquet file: %s", path)
    if path.exists():
        raise FileExistsError(f"Export file already exists: {path}")
    query, columns = export_query(connection, address)
    temporary = path.with_suffix(".parquet.partial")
    rows = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            batches = (batch for batch in cursor.fetch_arrow_batches() if batch is not None)
            first = next(batches, None)
            # On an empty result only, request the Connector's empty Arrow table.
            initial = first if first is not None else cursor.fetch_arrow_all(force_return_table=True)
            schema = numeric_schema(initial.schema, columns)
            with pq.ParquetWriter(temporary, schema, compression="snappy", version="2.6") as writer:
                if first is not None:
                    writer.write_table(first.cast(schema, safe=True))
                    rows += first.num_rows
                    logger.info("Parquet progress: table=%s rows_written=%d", address, rows)
                for batch in batches:
                    writer.write_table(batch.cast(schema, safe=True))
                    rows += batch.num_rows
                    logger.info("Parquet progress: table=%s rows_written=%d", address, rows)
        if pq.ParquetFile(temporary).metadata.num_rows != rows:
            raise RuntimeError(f"Parquet row count mismatch for {address}")
        temporary.rename(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    logger.info("Parquet file created: %s rows=%d bytes=%d", path, rows, path.stat().st_size)
    return rows
