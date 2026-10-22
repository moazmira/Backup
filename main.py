import argparse
import logging
from filelock import FileLock

from config.settings import BACKUP_DIR, load_obs_config, load_source_config
from connections.obs import connect_obs

from services.postgres_backup import backup_postgres
from services.snowflake_backup import backup_snowflake

from utils.logger import setup_logger

logger = logging.getLogger("backup")


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL/Snowflake backups to Huawei OBS")
    parser.add_argument("--source", required=True, choices=("postgres", "snowflake"))
    parser.add_argument("--connection")
    args = parser.parse_args()

    setup_logger()
    try:
        settings = (args.source, args.connection)
        obs_settings = load_obs_config()

        logger.info("Selected source=%s connection=%s", args.source, args.connection)

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        
        #postgres.lock and snowflake.lock are used to prevent concurrent backups of the same source
        lock_file = BACKUP_DIR / f".{args.source}.lock"
        with FileLock(str(lock_file), timeout=0):
            client = connect_obs(obs_settings)

        try:
            settings = load_source_config(args.source, args.connection)
            obs_settings = load_obs_config()

            logger.info("Selected source=%s", args.source)

            BACKUP_DIR.mkdir(parents=True, exist_ok=True)

            with FileLock(str(BACKUP_DIR / ".backup.lock"), timeout=0):
                client = connect_obs(obs_settings)

                try:
                    if args.source == "postgres":
                        backup_postgres(settings, client, obs_settings)

                    elif args.source == "snowflake":
                        backup_snowflake(settings, client, obs_settings)

                finally:
                    client.close()
                    logger.info("OBS connection closed")

            return 0

        except KeyboardInterrupt:
            logger.error("Backup interrupted")
            return 130

    except Exception:
        logger.exception("Backup failed")
        return 1
    
if __name__ == "__main__":
    raise SystemExit(main())
