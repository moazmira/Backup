# PostgreSQL to Huawei OBS

This script makes one full custom-format dump per named database on each run.
It checks that the file is nonempty and that `pg_restore --list` can read its
catalog. After uploading, it compares the OBS object's size with the local
file size. The local file is deleted only if all checks succeed. Failures
retain the local file in `work/`; each run writes a separate log in `logs/`.

## Linux setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Edit `.env` to enter the PostgreSQL connection, comma-separated database
names, OBS keys, and paths to PostgreSQL client programs. Check the paths with
`which pg_dump` and `which pg_restore`. The pg_dump major version must be
compatible with the server; use PostgreSQL 18 tools for a PostgreSQL 18 server.

```bash
.venv/bin/python backup.py
```

Example object path:
`metadata-daily-backups/postgres/2026/09/29/postgres_20260929_123456_123456_a1b2c3d4.dump`.
The timestamp uses Cairo time. Microseconds and a random suffix prevent
repeat runs from overwriting earlier dumps. The script exits nonzero if any
database fails, but continues to try the remaining databases.

This is a full database dump, not a schema-only dump. The OBS account needs
PutObject and GetObject permission to upload and verify metadata. Single-file
uploads here are limited to 5 GiB by the OBS API; larger dumps need multipart
upload. A catalog check and size match do not replace a test restore.
