import argparse
import logging
from filelock import FileLock

from services.snowflake_backup import backup_snowflake

from config.settings import BACKUP_DIR, load_obs_config, load_source_config

from connections.obs import connect_obs
from connections.snowflake import connect_snowflake

from utils.files import create_run
from utils.logger import setup_logger

logger = logging.getLogger("backup")


def run_backup(args, settings, obs_client, obs_settings):
    now, run_dir = create_run(args.source)

    logger.info("Backup started: source=%s output=%s", args.source, run_dir)

    if args.source == "postgres":
        from services.postgres_backup import backup_postgres
        failures = backup_postgres(settings, obs_client, obs_settings, run_dir, now)
    else:
        connection = connect_snowflake(settings)
        try:
            failures = backup_snowflake(connection, settings, obs_client, obs_settings, run_dir, now)
        finally:
            connection.close()

            logger.info("Snowflake connection closed")

    logger.info("Run finished: failed_units=%d", failures)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL/Snowflake backups to Huawei OBS")
    parser.add_argument("--source", required=True, choices=("postgres", "snowflake"))
    parser.add_argument("--connection", required=True)
    args = parser.parse_args()
    setup_logger()
    try:
        settings = load_source_config(args.source, args.connection)
        obs_settings = load_obs_config()

        logger.info("Selected source=%s connection=%s", args.source, args.connection)

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        with FileLock(str(BACKUP_DIR / ".backup.lock"), timeout=0):
            client = connect_obs(obs_settings)
            try:
                return run_backup(args, settings, client, obs_settings)
            finally:
                client.close()

                logger.info("OBS connection closed")
                
    except KeyboardInterrupt:
        logger.error("Run interrupted; inspect retained local files")
        return 130
    except Exception:
        logger.exception("Run failed; inspect the log before retrying")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
