# Simple PostgreSQL dumps

## Project files

- `config/settings.py`: reads the `.env` configuration.
- `utils/logging_utils.py`: creates console and file logs.
- `services/postgres_backup.py`: creates PostgreSQL dumps.
- `services/obs_storage.py`: uploads, verifies, and removes successful local dumps.
- `main.py`: runs the steps in order.

Set the PostgreSQL credentials and comma-separated database names in `.env`.
The script uses `pg_dump` to connect and write one full custom-format dump
per database to `dumps/`. It uploads each dump to
`bucket/PG_HOST/database/YYYY/MM/DD/database_datetime.dump`, verifies the uploaded
size, then removes the local file. If upload or verification fails, the local
file remains in `dumps/`. Each run writes a separate file in `logs/` and
also prints those messages to the terminal.
Log filenames follow `YYYYMMDD_HHMMSS_microseconds_main.log`.

The filename is `database_YYYYMMDD_HHMMSS.dump`, for example
`postgres_20260929_135505.dump`. Another run later on the same day gets a
different timestamp. A repeat within the same second fails instead of
overwriting a dump.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Edit .env, then run:
.venv/bin/python main.py
```

Set every variable in `.env`, including `PG_PORT` and `PG_DUMP_PATH`.
Missing settings stop the run immediately. PostgreSQL 18 servers need a
PostgreSQL 18 or newer pg_dump client.
The OBS credentials need ListBucket, PutObject, and GetObject permissions.
The simple OBS putFile upload supports files up to 5 GiB; larger dumps need
multipart upload.

## Docker on the Linux server

Build a local image from the project directory:

```bash
docker build -t pg-obs-backup:local .
```

The build uses `postgres:18` as the base image for its PostgreSQL 18
`pg_dump`. If that base image is not already local, Docker downloads it
once. This project image is not pushed to a registry.

Create the host directories and configure `.env` first:

```bash
mkdir -p logs dumps
cp .env.example .env
chmod 600 .env
# Edit .env with real credentials and database names.
```

Run one backup in a temporary container:

```bash
docker run --rm --name pg-obs-backup --network host \
  --user "$(id -u):$(id -g)" \
  --env PG_DUMP_PATH=/usr/bin/pg_dump \
  --env TZ=Africa/Cairo \
  --mount "type=bind,src=$(pwd)/.env,dst=/app/.env,readonly" \
  --mount "type=bind,src=$(pwd)/logs,dst=/app/logs" \
  --mount "type=bind,src=$(pwd)/dumps,dst=/app/dumps" \
  pg-obs-backup:local
```

Run the commands while inside the project directory. `--network host` is
for the Linux server and lets a `PG_HOST=127.0.0.1` value reach PostgreSQL
on the host. Logs and any dump retained after a failed upload stay in the
mounted host directories. The container uses its own PostgreSQL 18
`/usr/bin/pg_dump` even if `.env` has a host-specific `PG_DUMP_PATH`.
The two `--env` arguments set the container's pg_dump path and Cairo time;
PostgreSQL and OBS credentials still come from the mounted `.env` file.
