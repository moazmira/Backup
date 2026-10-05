"""Snowflake table exports using existing OBS configuration/services."""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import snowflake.connector
from filelock import FileLock

from services.obs_storage import exists, upload_verified

ROOT = Path(__file__).resolve().parents[1]

def identifier(value):
    return '"' + value.replace('"', '""') + '"'

def component(value):
    # Preserve normal Snowflake names; escape path separators and unsafe characters.
    return quote(value, safe='_').replace('.', '%2E')

def export_table(connection, address, path):
    with connection.cursor() as cursor:
        cursor.execute('DESC TABLE ' + address)
        columns = cursor.fetchall()
    fields, expressions = [], []
    for column in columns:
        name, sqltype = column[0], column[1].upper()
        expr = identifier(name)
        if sqltype.startswith('NUMBER('):
            precision, scale = map(int, sqltype[7:-1].split(','))
            arrow_type = pa.decimal128(precision, scale)
        elif sqltype.startswith(('VARCHAR', 'CHAR', 'TEXT', 'STRING')):
            arrow_type = pa.string()
        elif sqltype.startswith(('FLOAT', 'DOUBLE', 'REAL')):
            arrow_type = pa.float64()
        elif sqltype.startswith('BOOLEAN'):
            arrow_type = pa.bool_()
        elif sqltype.startswith('BINARY'):
            arrow_type = pa.binary()
        elif sqltype == 'DATE':
            arrow_type = pa.date32()
        elif sqltype.startswith('TIMESTAMP_NTZ'):
            arrow_type = pa.timestamp('ns')
        elif sqltype.startswith(('TIMESTAMP_TZ', 'TIMESTAMP_LTZ', 'TIME')):
            # Explicit text preserves fractional precision and TZ offset.
            fmt = 'HH24:MI:SS.FF9' if sqltype.startswith('TIME(') else 'YYYY-MM-DD"T"HH24:MI:SS.FF9 TZH:TZM'
            expr = f"TO_CHAR({expr}, '{fmt}')"
            arrow_type = pa.string()
        elif sqltype in ('VARIANT', 'OBJECT', 'ARRAY'):
            expr = f'TO_JSON({expr})'
            arrow_type = pa.string()
        else:
            raise ValueError(f'Unsupported type {sqltype} for {name}; table not exported')
        fields.append(pa.field(name, arrow_type, nullable=column[3] == 'Y'))
        expressions.append(expr + ' AS ' + identifier(name))
    schema = pa.schema(fields, metadata={b'snowflake_columns': json.dumps(
        [{'name': c[0], 'type': c[1]} for c in columns]).encode()})
    rows = 0
    temporary = path.with_suffix('.parquet.partial')
    # A single SELECT gives one consistent table result. All batches go to one file.
    try:
        with connection.cursor() as cursor, pq.ParquetWriter(temporary, schema, compression='snappy') as writer:
            cursor.execute('SELECT ' + ', '.join(expressions) + ' FROM ' + address)
            for batch in cursor.fetch_arrow_batches():
                if batch is None:
                    continue
                batch = batch.cast(schema, safe=True)
                writer.write_table(batch)
                rows += batch.num_rows
        if pq.ParquetFile(temporary).metadata.num_rows != rows:
            raise RuntimeError('Local Parquet row count mismatch')
        temporary.replace(path)
        return rows
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

def backup_snowflake(client, config, logger):
    workspace = ROOT / 'work'
    workspace.mkdir(exist_ok=True)
    # FileLock supports Windows and Linux; remote naming requires a single host writer.
    with FileLock(str(workspace / 'snowflake.lock'), timeout=0):
        now = datetime.now(ZoneInfo('Africa/Cairo'))
        run_dir = workspace / now.strftime('%Y%m%d_%H%M%S_%f')
        run_dir.mkdir()
        connection = snowflake.connector.connect(**config['snowflake_connection'])
        failures = successes = 0
        try:
            for database in config['snowflake_databases']:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(f'SELECT TABLE_SCHEMA, TABLE_NAME FROM {identifier(database)}.INFORMATION_SCHEMA.TABLES '
                            "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA <> 'INFORMATION_SCHEMA' ORDER BY 1, 2")
                        tables = cursor.fetchall()
                    logger.info('Database %s: %s visible base tables', database, len(tables))
                    for schema, table in tables:
                        address = '.'.join(map(identifier, (database, schema, table)))
                        try:
                            base = '_'.join(map(component, (database, schema, table))) + '_' + now.strftime('%Y%m%d')
                            prefix = f'Snowflake/{component(database)}/{now:%Y/%m/%d}/'
                            suffix = 1
                            while True:
                                stem = base + (f'_{suffix}' if suffix > 1 else '')
                                if not any(exists(client, config['obs_bucket'], prefix + stem + ext)
                                           for ext in ('.parquet', '.sql')):
                                    break
                                suffix += 1
                            parquet = run_dir / (stem + '.parquet')
                            ddl = run_dir / (stem + '.sql')
                            logger.info('Exporting %s', address)
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT GET_DDL('TABLE', %s, TRUE)", (address,))
                                ddl.write_text(cursor.fetchone()[0] + '\n', encoding='utf-8')
                            rows = export_table(connection, address, parquet)
                            for path in (ddl, parquet):
                                upload_verified(client, config['obs_bucket'], prefix + path.name, path, logger)
                            parquet.unlink()
                            ddl.unlink()
                            successes += 1
                            logger.info('SUCCESS %s rows=%s; local files deleted', address, rows)
                        except Exception:
                            failures += 1
                            logger.exception('FAILED %s; complete local files retained in %s', address, run_dir)
                except Exception:
                    failures += 1
                    logger.exception('Database discovery failed: %s', database)
            logger.info('Snowflake finished: %s successful tables; %s failures', successes, failures)
            if failures:
                raise RuntimeError(f'Snowflake backup completed with {failures} failure(s)')
        finally:
            connection.close()
