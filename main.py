from config.settings import load_config
from services.obs_storage import connect_to_obs, upload_dump
from services.postgres_backup import create_dump
from utils.logging_utils import setup_logger


def main():
    logger = setup_logger()
    client = None
    try:
        config = load_config()
        logger.info("Databases requested: %s", ", ".join(config["databases"]))
        client = connect_to_obs(config, logger)
        for database in config["databases"]:
            logger.info("[%s] Starting backup", database)
            dump_file = create_dump(config, database, logger)
            upload_dump(client, config, database, dump_file, logger)
        logger.info("Run completed successfully: %d database(s)", len(config["databases"]))
    except Exception:
        logger.exception("Run failed")
        raise SystemExit(1)
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
