import json

import pyarrow as pa
import pyarrow.parquet as pq

from queries.snowflake import GET_DDL
from utils.database import select_data


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def get_column_type(name, sqltype):
    """Map one Snowflake column type to its Parquet representation."""
    if sqltype.startswith("NUMBER("):
        precision, scale = map(int, sqltype[7:-1].split(","))
        return pa.decimal128(precision, scale)
    if sqltype.startswith(("VARCHAR", "CHAR", "TEXT", "STRING")):
        return pa.string()
    if sqltype.startswith(("FLOAT", "DOUBLE", "REAL")):
        return pa.float64()
    if sqltype.startswith("BOOLEAN"):
        return pa.bool_()
    if sqltype.startswith("BINARY"):
        return pa.binary()
    if sqltype == "DATE":
        return pa.date32()
    if sqltype.startswith(("TIMESTAMP", "TIME")) or sqltype in ("VARIANT", "OBJECT", "ARRAY"):
        return pa.string()
    raise ValueError(f"Unsupported type {sqltype} in column {name}")


def get_column_expression(name, sqltype):
    """Prepare one SELECT expression, including any text conversion."""
    expression = quote_identifier(name)
    if sqltype.startswith(("TIMESTAMP", "TIME")):
        if sqltype.startswith("TIMESTAMP_NTZ"):
            fmt = 'YYYY-MM-DD"T"HH24:MI:SS.FF9'
        elif sqltype.startswith("TIMESTAMP"):
            fmt = 'YYYY-MM-DD"T"HH24:MI:SS.FF9 TZH:TZM'
        else:
            fmt = "HH24:MI:SS.FF9"
        expression = f"TO_CHAR({expression}, '{fmt}')"
    elif sqltype in ("VARIANT", "OBJECT", "ARRAY"):
        expression = f"TO_JSON({expression})"
    return expression + " AS " + quote_identifier(name)


def build_export_schema(columns):
    """Collect column types and SELECT expressions for one table."""
    fields, expressions = [], []
    for column in columns:
        name, sqltype = column[0], column[1].upper()
        fields.append(pa.field(name, get_column_type(name, sqltype), nullable=column[3] == "Y"))
        expressions.append(get_column_expression(name, sqltype))
    metadata = json.dumps([{"name": c[0], "type": c[1]} for c in columns]).encode("utf-8")
    return pa.schema(fields, metadata={b"snowflake_columns": metadata}), expressions


def export_ddl(connection, address, path, logger):
    logger.info("Creating SQL file: %s", path)
    ddl = select_data(connection, GET_DDL, (address,))[0][0]
    if not isinstance(ddl, str) or not ddl.strip():
        raise RuntimeError(f"Empty DDL for {address}")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(ddl.rstrip() + "\n")
    logger.info("SQL file created: %s", path)


def export_parquet(connection, address, path, logger):
    logger.info("Creating Parquet file: %s", path)
    if path.exists():
        raise FileExistsError(f"Export file already exists: {path}")
    columns = select_data(connection, "DESC TABLE " + address)
    schema, expressions = build_export_schema(columns)
    temporary = path.with_suffix(".parquet.partial")
    rows = 0
    try:
        with connection.cursor() as cursor, pq.ParquetWriter(
            temporary, schema, compression="snappy"
        ) as writer:
            cursor.execute("SELECT " + ", ".join(expressions) + " FROM " + address)
            for batch in cursor.fetch_arrow_batches():
                if batch is None:
                    continue
                writer.write_table(batch.cast(schema, safe=True))
                rows += batch.num_rows
                logger.info("Parquet progress: table=%s rows_written=%d", address, rows)
        if pq.ParquetFile(temporary).metadata.num_rows != rows:
            raise RuntimeError(f"Parquet row count mismatch for {address}")
        temporary.rename(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    logger.info("Parquet file created: %s rows=%d bytes=%d", path, rows, path.stat().st_size)
    return rows
