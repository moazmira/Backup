# Database Backup

Create local backups, upload them to Huawei OBS, compare uploaded sizes, then delete local files after the entire unit succeeds.

## Run

Keep your current .env and secret/ key files. For a new setup, copy .env.example to .env and fill in its values.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --source postgres --connection production
.venv/bin/python main.py --source snowflake --connection production
```

The connection name selects PG_PRODUCTION_* or SNOWFLAKE_PRODUCTION_* settings. Multiple database names can be comma separated. Use another prefix for another host/account.
PG_DUMP_PATH is the pg_dump executable path. No client version discovery or pg_restore validation runs.
The Snowflake private key remains a separate file; relative key paths resolve from the project folder.

## Code layout

| File | Responsibility |
| --- | --- |
| main.py | Read arguments/settings, lock the run, connect OBS, select source using if/elif, close OBS, return exit status |
| services/postgres_backup.py | Create run folder; dump, upload and clean up each database |
| services/snowflake_backup.py | Create run folder; open Snowflake; save and upload each table; close Snowflake in finally |
| connections/ | Connections to OBS, PostgreSQL and Snowflake |
| utils/backup_paths.py | Create a Cairo-time run folder using a timestamp with microseconds |
| utils/postgres_dump.py | Run pg_dump and check its exit status and nonempty output |
| utils/snowflake_export.py | Metadata queries, SQL identifier quoting, table SQL and Parquet export |
| utils/obs_upload.py | Upload files, check OBS responses and uploaded sizes, write completion marker, delete local files |
| utils/logger.py | Log to terminal and file using Cairo time |
| config/settings.py | Read environment configuration |

There is no run_backup function or utils/sql.py. Imports are at module top.

## Flow

Snowflake processes one table at a time: save SQL definition, save table data to one Parquet file, upload both and a .complete.json receipt, then delete those local files. It then starts the next table.
Parquet data is read using fetch_arrow_batches(); the Connector controls batch sizes. No per-batch progress log is emitted. The first batch supplies the Arrow schema; an empty result uses the Connector's empty Arrow table. NUMBER columns use their declared decimal precision/scale. TIMESTAMP_TZ is exported as text to preserve offsets; other types use Connector Arrow types and safe casts.

PostgreSQL processes one whole database at a time: create a custom-format dump, check success and nonempty output, upload and compare size, upload the receipt, delete local files, then start the next database. Cluster-global roles/tablespaces are not included by pg_dump.

Uploaded files are not downloaded again. No SHA-256 is computed. A matching size does not prove identical content.
Large files use OBS multipart upload; they remain one final object. A failure keeps complete local files. An unsuccessful partial export is removed. A table/database failure is logged and processing continues; any failure produces exit code 1. Successful runs return 0, keyboard interruption returns 130.

Each table or database file is completed on disk before upload. Leave enough disk space for the largest unit. Names are used directly in paths; use ordinary database/schema/table names.

## OBS paths

```text
Snowflake/BRONZE/PUBLIC/YYYY/MM/DD/BRONZE_PUBLIC_USERS_YYYYMMDD.sql
Snowflake/BRONZE/PUBLIC/YYYY/MM/DD/BRONZE_PUBLIC_USERS_YYYYMMDD.parquet
Snowflake/BRONZE/PUBLIC/YYYY/MM/DD/BRONZE_PUBLIC_USERS_YYYYMMDD.complete.json
10.11.5.4/database/YYYY/MM/DD/database_TIMESTAMP.dump
```

Existing names receive _2, _3, etc. A shared local lock prevents overlapping runs using the same backup directory.
The completion receipt lists object keys and sizes. Local folders use timestamps without random suffixes.

The table completion log appears after uploading the pair and receipt:

```text
INFO Table backup completed: BRONZE.PUBLIC.USERS rows=15000000
```

## Docker

```bash
docker build -t obs-backup .
docker run --rm --env-file .env -v "$PWD/secret:/app/secret:ro" -v "$PWD/backups:/app/backups" -v "$PWD/logs:/app/logs" obs-backup --source snowflake --connection production
```

The image supplies PostgreSQL 18 client tools. Live exports, restores, actual Snowflake types/permissions, and OBS access must be tested in your environment. Each table is exported by a separate query; the project does not promise a single cross-table snapshot.
