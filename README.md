# Backup — step 3: local Snowflake exports

Install/update dependencies in your existing virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --source snowflake --connection production
```

Keep existing secret/ files and utils/logger.py. This update contains no credentials.

Snowflake creates two files per visible BASE TABLE across the configured databases:

```
backups/snowflake/<Cairo-run-timestamp>/<DATABASE>/<SCHEMA>/<TABLE>.sql
backups/snowflake/<Cairo-run-timestamp>/<DATABASE>/<SCHEMA>/<TABLE>.parquet
```

- connections/snowflake.py: connection and key loading; enable decimal Arrow results.
  Export query timeout is 3600 seconds instead of the connection-test limit of 30.
- services/snowflake_backup.py: list visible base tables, create a new run directory,
  export each table and log a success/failure summary.
- services/snowflake_export.py: get table DDL, map column types, and write batches
  into a single Snappy-compressed Parquet file per table.
- main.py: select the source and close its connection after the work.

The Snowflake branch does not read OBS settings, connect to OBS, upload, or delete
completed files. PostgreSQL remains at connection checks (including OBS), with no
schema/table discovery or dump added. There are no new CLI arguments.

Data details:
- SQL comes from GET_DDL(TABLE, qualified_name, TRUE). It may contain CREATE OR
  REPLACE and source object dependencies. It is saved only; nothing executes it.
- NUMBER uses Decimal; text, Boolean, binary and DATE keep corresponding Arrow types.
- TIME and TIMESTAMP use text with nine fractional digits to preserve precision
  and date range. TZ includes offset; LTZ uses UTC session display, preserving
  the instant. Source types are embedded in Parquet metadata.
- VARIANT/OBJECT/ARRAY use JSON text. Unsupported types fail the table explicitly.
- Empty tables produce a valid zero-row Parquet with columns and a SQL file.
- Rows are fetched in connector batches; full-table Python lists are not built.
  Connector batch sizes and prefetch still affect memory.
- A temporary .parquet.partial is renamed only after writing and checking footer
  row count against rows written. This does not independently compare source count.

Only visible BASE TABLE objects are included, not views, external or event tables.
Visibility does not prove SELECT/GET_DDL access. Row access and masking policies
apply: exports reflect what the configured role can read, not necessarily all rows
or original unmasked values. No database-wide consistent snapshot is claimed.

Failures retain completed files, remove incomplete Parquet, continue other tables,
and finish with exit code 1 if anything failed. A retained SQL alone is not a
complete table export: confirm matching Parquet and the success log. Empty database
results log a warning. Every run uses a separate directory to avoid overwrites.
Unusual object names are URL-encoded for local paths. Very long names and Windows
reserved/case-colliding filenames may require a Linux export.

Validation performed locally: Parquet conversion, empty tables, partial-file cleanup
and runner orchestration using simulated Snowflake results. No live database export
was performed in the creation environment.
