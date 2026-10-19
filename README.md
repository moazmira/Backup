# Database backups — simplified version

One workflow: create files -> upload to Huawei OBS -> verify -> delete local files.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --source postgres --connection production
.venv/bin/python main.py --source snowflake --connection production
```

Python 3.11+; Linux deployment target. No `--mode` or `--keep-local` flags. Every
run performs the full backup. Failed units keep complete local files; independent
units continue, and any failure returns exit code 1. Logs use Africa/Cairo.

## Credentials and multiple hosts

For a new installation, copy `.env.example` to `.env` and fill it locally:

```bash
cp .env.example .env
chmod 600 .env
```

Do not overwrite an existing configured `.env`. All settings/credentials come from
this file or existing process environment variables (environment wins). JSON
configuration is no longer read. See MIGRATION.md for exact old-to-new mappings.
Dotenv interpolation is disabled so `${...}` inside passwords stays literal.
Quote values containing spaces or `#`; use python-dotenv quoting rules for quotes
inside passwords. No passwords or private keys are included in the deliverable.

`production` selects `PG_PRODUCTION_*` or `SNOWFLAKE_PRODUCTION_*`. To add a second
host, use another prefix, e.g. `PG_ANALYTICS_*`, and run `--connection analytics`.
Each prefix includes `DATABASES=db1,db2`. One command selects one host/account.

The Snowflake private key remains a separate PEM `.p8` file, such as
`secret/rsa_key.p8`. Its **path and passphrase** are in `.env`. Relative paths are
resolved from the project directory, independent of the current working folder.
Old JSON files may be kept offline but are not read. Never commit actual secrets.

## Backup contents and paths

PostgreSQL: one full custom-format dump per database, with no table/schema filter.
Includes schema, data, functions, triggers, indexes and other database-level
objects handled by pg_dump. Roles/tablespaces are cluster globals and are outside
this database dump. Matching pg_restore must be installed beside the selected
pg_dump. The client can be the same or a newer major than the server (server 10+,
subject to pg_dump's supported versions). No system packages are installed by the
backup. Set PG_DUMP_PATH if needed; Docker includes client 18 only. A dump from a
newer client is not guaranteed to restore to an older target server.

Snowflake: SQL DDL and one Parquet file per visible BASE TABLE. Multiple schemas
with the same table name have separate folders and names. Views, external/event
tables and other account objects are outside the table export.

OBS:

```
10.11.5.4/<database>/YYYY/MM/DD/<database>_<timestamp>.dump
Snowflake/<database>/<schema>/YYYY/MM/DD/<database>_<schema>_<table>_YYYYMMDD.sql
Snowflake/<database>/<schema>/YYYY/MM/DD/<database>_<schema>_<table>_YYYYMMDD.parquet
```

Snowflake's new schema folder applies to both files and `.complete.json`.
PostgreSQL's host/database/date structure is unchanged. Dots in host IPs stay
readable. Repeated names receive `_2`, `_3`, etc.; old OBS files are not moved.

Local files are under `backups/<source>/<run>/`; logs are under `logs/`. There is
no `summary.json`. `.complete.json` on OBS is retained: it lists verified object
keys, sizes and hashes, proving that the unit's upload/verification finished.

## Important behavior retained

- Local shared FileLock prevents overlapping processes using the same backups
  directory. Independent machines/filesystems must not write the same namespace;
  object existence checks are not distributed atomic reservations.
- Multipart at 100 MB by default; 64 MB parts, two upload workers. SDK assembles one
  final object. All values can be changed via the optional OBS variables in .env.
- Uploaded size and SHA-256 are verified with a full temporary download. Allow
  disk space for the largest file plus its verification copy, and download costs.
- SQL/Parquet stay local until both and the completion receipt are verified.
  Verification can retry; an ambiguous upload failure is not blindly overwritten.
- PostgreSQL reads the complete archive with pg_restore before upload. This is
  not a real restore test. Partial dump files are not finalized/uploaded.
- Secrets are never deliberately logged. Logs include paths, database/table names
  and driver error details, so treat logs as operational data.

## Arrow simplification

Removed `get_column_type`, `get_column_expression` and the full type-mapping
builder. The export schema comes from the first Arrow batch; only an empty result
uses `fetch_arrow_all(force_return_table=True)` to obtain an empty typed table.
Data is otherwise fetched in batches and written to one Parquet file.

A small NUMBER-only normalization remains: integer widths vary by batch and the
Connector's empty NUMBER schema defaults to int64 even for scaled decimals.
NUMBER uses its declared precision/scale as Decimal, preserving large integers
and fractions across batches. Other types use the Connector's Arrow schema.

DATE, TIME and NTZ/LTZ timestamps use native Arrow types. Nanosecond fractions
are not truncated. Safe casts reject incompatible ranges/precision rather than
silently losing values. If timestamp representations vary incompatibly between
batches (e.g. extreme dates outside nanosecond range), that table fails explicitly
and its complete local SQL is retained; review the error before retrying.
TIMESTAMP_TZ alone uses explicit text with nine fractional digits and per-row
UTC offset, since Arrow has a single timezone per column. JSON/structured values
use the Connector's representation. The SQL file defines original Snowflake types;
there is no extra source-type metadata document.

Exports obey masking/row-access policies and reflect the configured role's view.
GET_DDL and SELECT are separate; avoid concurrent schema changes. No database-wide
multi-table consistent snapshot is claimed. Unsupported Connector/Parquet types
fail the table rather than silently being discarded.

## Logs, tests and deployment

`setup_logger()` runs once in main. Other files use
`logging.getLogger("backup")`, so there are no logger parameters or extra log files
on import. The final log records success/failure counts; no separate summary.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

25 tests passed locally (Python 3.12), including native timestamps, scaled/large
numbers, empty tables, schema paths, multipart selection and failure cleanup.
Tests create real Parquet files but simulate database/OBS services. A real isolated
restore remains necessary. Docker is included; build and run as follows:

```bash
docker build -t database-backup:local .
mkdir -p logs backups secret
docker run --rm --network host \
  --mount "type=bind,src=$(pwd)/.env,dst=/app/.env,readonly" \
  --mount "type=bind,src=$(pwd)/secret,dst=/app/secret,readonly" \
  --mount "type=bind,src=$(pwd)/logs,dst=/app/logs" \
  --mount "type=bind,src=$(pwd)/backups,dst=/app/backups" \
  database-backup:local --source snowflake --connection production
```

The .env and keys are mounted at runtime, not copied into the image. Use the same
host backups mount for all scheduled containers to share the lock. Tests are not
copied into the image. Docker/live external services were not run in the creation
environment. Cron/SSH commands remain the same: use the absolute venv interpreter
and source/connection arguments, with no mode. Keep server scheduling in the
intended timezone. Backup retention and scheduler failure notification remain
operational settings outside this code.
