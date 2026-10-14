import argparse

from config.settings import load_obs_config, load_source_config
from utils.logger import setup_logger


def main():
    parser = argparse.ArgumentParser(description="Step 1: validate backup settings only")
    parser.add_argument("--source", choices=("postgres", "snowflake"), required=True)
    parser.add_argument("--connection", required=True)
    args = parser.parse_args()
    logger = setup_logger()
    try:
        logger.info("Reading %s settings", args.source)
        source_config = load_source_config(args.source, args.connection)
        logger.info("Connection selected: %s", args.connection)
        logger.info("Databases: %s", ", ".join(source_config["databases"]))
        logger.info("Reading OBS settings")
        obs_config = load_obs_config()
        logger.info("OBS bucket: %s", obs_config["bucket"])
        logger.info("Settings structure validated. No network connections or backups performed.")
        logger.info("Placeholder values are examples; credentials and key file have not been verified.")
        return 0
    except (ValueError, OSError) as error:
        logger.error("Settings validation failed: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
