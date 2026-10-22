import pendulum

from airflow.sdk import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator


with DAG(
    dag_id="postgres_obs_backup",
    start_date=pendulum.datetime(2026, 10, 22, tz="Africa/Cairo"),
    schedule="0 2 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["backup", "postgres", "obs"],
) as dag:

    backup = SSHOperator(
        task_id="postgres_backup",
        ssh_conn_id="backup_server",
        cmd_timeout=None,
        get_pty=True,
        command="""
docker run --rm \
  --env-file /root/Backup/.env \
  -e PG_DUMP_PATH=/usr/bin/pg_dump \
  -e BACKUP_OUTPUT_DIR=/app/backups \
  -e BACKUP_LOG_DIR=/app/logs \
  -v /root/Backup/backups:/app/backups \
  -v /root/Backup/logs:/app/logs \
  obs-backup:latest \
  --source postgres --connection production
""",
    )