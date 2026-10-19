# Linux deployment

## Existing server

Keep the same connection JSON files and key under `secret/`. Install requirements
in the project's virtual environment, then start with `--mode check` and
`--mode local`. A real backup uploads and deletes verified local copies by default.
For inspection, add `--keep-local` to a full backup.

Use the interpreter's absolute path for cron; no run.sh is required. Verify that
PostgreSQL client major matches your server before scheduling. On Ubuntu the
package name is `postgresql-client-18` for an 18 server; package availability
requires your configured package repositories. Do not substitute an older client.

## Docker

The Dockerfile supplies PostgreSQL 18 clients and supports Snowflake too. For
other server majors, provide matching clients in a separate image/build; the
runtime deliberately refuses a mismatched major.

From the project directory:

```bash
docker build -t database-backup:local .
mkdir -p logs backups secret

docker run --rm --network host \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$(pwd)/secret,dst=/app/secret,readonly" \
  --mount "type=bind,src=$(pwd)/logs,dst=/app/logs" \
  --mount "type=bind,src=$(pwd)/backups,dst=/app/backups" \
  database-backup:local --source snowflake --connection production --mode check
```

Replace `snowflake` with `postgres`, or use `--mode local`. Remove `--mode check`
for full upload/verification/cleanup. Use container paths for absolute key files;
`rsa_key.p8` in the configuration resolves under `/app/secret/` automatically.
Linux host networking lets PostgreSQL host `127.0.0.1` address the Docker host.
An absolute Windows pg_dump path in JSON is overridden by Docker's PG_DUMP_PATH.

The build copies only source code and dependencies; secret/runtime folders never
enter the image. Mounts keep logs, retained backups, summaries and the shared run
lock on the host. No image was built/pushed/deployed from this delivery environment.

## Twice-daily cron in Cairo

`crontab` uses the scheduler/server timezone. Confirm with `timedatectl`. On a
server already using Africa/Cairo, this runs at midnight and noon Cairo:

```cron
0 0,12 * * * cd /root/Backup && /root/Backup/.venv/bin/python main.py --source postgres --connection production >> /root/Backup/logs/cron-postgres.log 2>&1
30 0,12 * * * cd /root/Backup && /root/Backup/.venv/bin/python main.py --source snowflake --connection production >> /root/Backup/logs/cron-snowflake.log 2>&1
```

Create logs/ before scheduling. Cairo daylight-saving changes are handled by the
server scheduler if its timezone is Africa/Cairo. TZ in Python controls log/naming
timestamps, not cron's trigger time. If the server uses another timezone, configure
the scheduler's supported timezone mechanism or translate the schedule; do not
assume a fixed UTC offset. Overlapping runs sharing the same backups directory
fail fast and log a lock error instead of writing concurrently. Offset schedules
by enough time for real workloads; the above 30-minute spacing is an example.

For additional connections, add commands with different `--connection` values
and schedule sequentially. For Airflow, use the same CLI in DockerOperator with
bind mounts for secret, logs and backups; configure its failure callback in your
Airflow project. No Airflow installation or existing DAG is modified here.

OBS bucket retention and backup-log retention are operational choices; this code
does not remove remote backups or old run summaries automatically.
