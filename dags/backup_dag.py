import pendulum

from airflow.sdk import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator


with DAG(
    dag_id="obs_backup",
    start_date=pendulum.datetime(2026, 10, 22, tz="Africa/Cairo"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["backup", "obs"],
) as dag:

    postgres_backup = SSHOperator(
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

    snowflake_backup = SSHOperator(
        task_id="snowflake_backup",
        trigger_rule="all_done",
        ssh_conn_id="backup_server",
        cmd_timeout=None,
        get_pty=True,
        command="""
docker run --rm \
  --env-file /root/Backup/.env \
  -e SNOWFLAKE_PRIVATE_KEY_FILE=/app/secret/rsa_key.p8 \
  -e BACKUP_OUTPUT_DIR=/app/backups \
  -e BACKUP_LOG_DIR=/app/logs \
  -v /root/Backup/secret:/app/secret:ro \
  -v /root/Backup/backups:/app/backups \
  -v /root/Backup/logs:/app/logs \
  obs-backup:latest \
  --source snowflake
""",
    )

    postgres_backup >> snowflake_backup