# PostgreSQL and Snowflake backups to Huawei OBS

The project creates local backup files, uploads them to OBS, verifies their bytes,
and deletes local files only after the whole backup unit is verified.

- PostgreSQL: one complete custom-format `.dump` per configured database.
- Snowflake: one `.sql` DDL and one `.parquet` per visible base table.
- Logs and names use Africa/Cairo. A new output directory is created for each run.
- Console and file logging; partial failures return a nonzero exit code.

## Upgrade from the earlier steps

Use this as a complete new code folder. Copy your existing `secret/` directory into
it, or put the code in `/root/Backup` while keeping your existing `secret/`.
No credentials or private keys are included. Existing JSON connection names and
required fields remain supported. Defaults cover the new optional settings.

**The default command now performs upload and cleanup.** Use `--mode local` to
review local files first or `--keep-local` to retain files after verified uploads.

Python 3.11+ and Linux are the deployment target (tested in Python 3.12). From the
project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

If you already have `secret/postgres.json`, `secret/snowflake.json`, and
`secret/obs.json`, keep them. For a new installation only:

```bash
mkdir -p secret
cp examples/postgres.example.json secret/postgres.json
cp examples/snowflake.example.json secret/snowflake.json
cp examples/obs.example.json secret/obs.json
chmod 700 secret
chmod 600 secret/*.json
```

Replace the example values. Put your Snowflake PEM key (e.g. `rsa_key.p8`) under
`secret/` and set `private_key_file` to its filename. An absolute path also works.
The passphrase is for the key file, not the Snowflake user's password. JSON files
are plain text; the folder is excluded from Git and Docker builds.

For PostgreSQL install the same major `pg_dump` and `pg_restore` as the server.
The program detects the server version and looks under
`/usr/lib/postgresql/<major>/bin/` and PATH. Optionally set `pg_dump_path` in the
connection JSON, or `PG_DUMP_PATH` in the environment. System packages are never
installed during a backup. The included Docker image supplies major 18 only.

## Run commands

```bash
# Source and OBS connection check; PostgreSQL also checks client versions.
.venv/bin/python main.py --source postgres --connection production --mode check
.venv/bin/python main.py --source snowflake --connection production --mode check

# Local files only: no OBS credentials, connection, upload or cleanup.
.venv/bin/python main.py --source postgres --connection production --mode local
.venv/bin/python main.py --source snowflake --connection production --mode local

# Full backup: create -> upload -> size/SHA-256 verification -> local cleanup.
.venv/bin/python main.py --source postgres --connection production
.venv/bin/python main.py --source snowflake --connection production

# Full backup while keeping verified local files.
.venv/bin/python main.py --source snowflake --connection production --keep-local
```

`--connection production` selects the JSON key `production` in the chosen source's
configuration. Add more named connection objects to handle additional hosts or
accounts; each invocation processes exactly one named connection.

A check proves login/database access and OBS listing only. It cannot prove that
all table export/DDL/upload permissions are available. Snowflake needs a running
usable warehouse, database/schema USAGE, table SELECT, and privileges for GET_DDL.
PostgreSQL's dump user must be able to read all required database objects. OBS
needs ListBucket, PutObject, GetObject/metadata, and multipart permissions for
large files (including aborting failed multipart uploads).

## Files and destinations

Local output, with a separate run directory for each invocation:

```
backups/postgres/<run>/<database>/<database>_<timestamp>.dump
backups/snowflake/<run>/<database>/<schema>/<table>.sql
backups/snowflake/<run>/<database>/<schema>/<table>.parquet
backups/<source>/<run>/summary.json
logs/<timestamp>.log
```

OBS destination keys:

```
<host>/<database>/YYYY/MM/DD/<database>_<timestamp>.dump
Snowflake/<database>/YYYY/MM/DD/<database>_<schema>_<table>_YYYYMMDD.sql
Snowflake/<database>/YYYY/MM/DD/<database>_<schema>_<table>_YYYYMMDD.parquet
```

A collision adds `_2`, `_3`, etc. to the shared stem. Each successful unit also
has `<stem>.complete.json`, containing each file's object key, byte count and
SHA-256. Incomplete pairs can exist after an interrupted upload; use the matching
completion receipt and run summary when choosing a backup for restore.

Normal object names stay readable; unusual path characters are URL-encoded.
Very long source names may exceed filesystem component limits and fail explicitly.

## Verification, failures and retries

1. PostgreSQL runs `pg_dump` with no schema/table filter, then reads the archive
   with `pg_restore --file /dev/null` (Windows uses its equivalent). This checks
   archive readability, not restoration into a real database.
2. Snowflake reads column definitions, exports DDL and streams connector Arrow
   batches into a single Snappy-compressed Parquet file. It compares the footer's
   row count to rows written. This is not a separate source row-count query.
3. OBS uploads use `putFile` below the threshold, and SDK multipart `uploadFile`
   above it. Multipart still produces one final object, not multiple backup files.
4. Every uploaded file is checked by size and a complete verification download
   with SHA-256 comparison. Temporary verification copies are then removed.
5. The completion receipt is uploaded and verified only after all unit files.
   Original local files are deleted only after all these checks succeed.

Allow disk for the exported table/dump **plus a full extra copy of the largest
file** during verification. Full verification adds download time and any applicable
network charges. OBS SDK performs request-level retries; verification retries are
controlled by `attempts`. An ambiguous upload failure stops that unit rather than
blindly overwriting a possibly completed object. A new run generates fresh data;
old local files/checkpoints are not resumed automatically. Remote partial units
are not deleted automatically. Configure OBS lifecycle rules for abandoned
multipart uploads as an operations task if required.

A table/database failure is logged and other independent units continue. The run
ends with exit code 1 if a unit failed. Run summaries are updated after each unit;
status remains `running` after an uncatchable process/host termination. Completed
local files are retained on export/upload/verification failure; incomplete Parquet
or dump files are removed on ordinary exceptions. Cleanup failures are reported
as failures even if the remote receipt exists; inspect the log. No remote object
is deleted by this project.

Exit codes: 0 successful, 1 failed, 2 CLI usage error, 130 keyboard interruption.
Empty Snowflake discovery is a warning and recorded as `empty`, not proof that an
otherwise inaccessible database contains no tables.

## Concurrency and scope

Run one writer against a destination namespace. A FileLock on
`backups/.backup.lock` prevents overlapping runs **sharing the same output
filesystem**. All scheduled Docker containers must bind-mount the same output
directory. Separate machines/filesystems writing the same OBS names are not
supported: existence checks and puts are not a distributed atomic reservation.
Schedule multiple named connections sequentially on the same host.

The Snowflake export includes visible `BASE TABLE` objects only. Views, external
and event tables, tasks, procedures, stages, users, grants and other account-level
objects are outside this table backup. Row access/masking policies apply to the
configured role. Each table SELECT has its own result; tables are not a single
consistent database-wide snapshot. GET_DDL and data extraction are separate, so
avoid schema changes during the backup window. GET_DDL can include policy/tag
references whose dependencies must be available during restore.

NUMBER is preserved as Decimal. TIME/TIMESTAMP are exported as explicit text with
nine fractional digits; LTZ is displayed in UTC to preserve the instant. VARIANT,
OBJECT and ARRAY use JSON text. Original Snowflake types are stored in Parquet
metadata. Unsupported types (e.g. GEOGRAPHY/VECTOR) fail explicitly rather than
silently dropping/coercing columns. See `docs/RESTORE.md` for conversion examples.

A PostgreSQL dump covers one database; roles and tablespaces are cluster globals
and are not created by pg_dump. This is a logical export, not WAL/PITR or a whole
cluster physical backup. Restore permissions, extensions and dependencies must
be prepared separately.

## Code map for review

| File | Responsibility |
| --- | --- |
| `main.py` | CLI, shared run lock, source selection, summary and client cleanup |
| `config/settings.py` | Paths, JSON loading, validation and defaults |
| `connections/` | PostgreSQL, Snowflake/key and OBS connections |
| `dbqueries/snowflake.py` | Small Snowflake metadata SQL statements |
| `utils/database.py` | `select_data()` for small metadata results |
| `services/postgres_backup.py` | Version matching, full dump and archive check |
| `services/snowflake_backup.py` | Database/table loop and file group upload |
| `services/snowflake_export.py` | Types, SELECT expressions, SQL and Parquet files |
| `storage/obs.py` | Object naming, upload, checksum, receipt and cleanup |
| `utils/logger.py` | Cairo console/file logging |
| `utils/files.py` | Run directories, names and summary persistence |

Review order: settings -> connections -> metadata helpers -> file creation ->
OBS transfer -> runners -> main -> Docker/scheduling.

## Tests and deployment

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests create real Parquet files and simulate database/OBS responses, failures,
cleanup and version checks. They do not connect to live services. See
`VALIDATION.md` for tested versions and limits, `docs/DEPLOYMENT.md` for Docker
and cron, and `docs/RESTORE.md` for manual isolated restore validation.

Optional path overrides (read before starting Python): `BACKUP_SECRET_DIR`,
`BACKUP_OUTPUT_DIR`, `BACKUP_LOG_DIR`. Defaults are project-local directories.
