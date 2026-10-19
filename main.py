import argparse

from filelock import FileLock

from config.settings import BACKUP_DIR, load_obs_config, load_source_config
from connections.obs import connect_obs
from utils.files import cairo_now, create_run, save_summary
from utils.logger import setup_logger


def run_backup(args, settings, obs_client, obs_settings, logger):
    now, run_dir = create_run(args.source)
    summary = {
        "source": args.source, "connection": args.connection, "mode": args.mode,
        "started_at": now.isoformat(timespec="seconds"), "status": "running", "units": [],
    }
    save_summary(run_dir, summary)
    logger.info("Backup started: source=%s mode=%s output=%s", args.source, args.mode, run_dir)
    try:
        if args.source == "postgres":
            from services.postgres_backup import backup_postgres
            backup_postgres(settings, obs_client, obs_settings, run_dir, now, summary, logger, args.mode, args.keep_local)
        else:
            from connections.snowflake import connect_snowflake
            from services.snowflake_backup import backup_snowflake
            connection = connect_snowflake(settings, logger)
            try:
                backup_snowflake(connection, settings, obs_client, obs_settings, run_dir, now, summary, logger, args.mode, args.keep_local)
            finally:
                connection.close()
                logger.info("Snowflake connection closed")
        failures = sum(unit["status"] == "failed" for unit in summary["units"])
        summary["status"] = "failed" if failures else "complete"
        successful = sum(unit["status"] in ("complete", "local_ready") for unit in summary["units"])
        logger.info("Run finished: successful_units=%d failed_units=%d summary=%s", successful, failures, run_dir / "summary.json")
        return 1 if failures else 0
    except BaseException:
        summary["status"] = "interrupted_or_failed"
        raise
    finally:
        summary["finished_at"] = cairo_now().isoformat(timespec="seconds")
        save_summary(run_dir, summary)


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL/Snowflake backups to Huawei OBS")
    parser.add_argument("--source", required=True, choices=("postgres", "snowflake"))
    parser.add_argument("--connection", required=True)
    parser.add_argument("--mode", choices=("check", "local", "backup"), default="backup",
                        help="check connections; local files only; backup uploads and verifies (default)")
    parser.add_argument("--keep-local", action="store_true", help="Keep verified local files after upload")
    args = parser.parse_args()
    logger = setup_logger()
    client = None
    try:
        logger.info("Selected source=%s connection=%s mode=%s", args.source, args.connection, args.mode)
        settings = load_source_config(args.source, args.connection)
        # One writer, including distinct connection profiles, per shared output
        # directory. All scheduled containers must mount this same directory.
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        with FileLock(str(BACKUP_DIR / ".backup.lock"), timeout=0):
            obs_settings = None
            if args.mode in ("check", "backup"):
                obs_settings = load_obs_config()
                client = connect_obs(obs_settings, logger)
            if args.mode == "check":
                from services.checks import check_source
                check_source(args.source, settings, logger)
                logger.info("Connection checks completed successfully")
                return 0
            return run_backup(args, settings, client, obs_settings, logger)
    except KeyboardInterrupt:
        logger.error("Run interrupted; complete local files retained")
        return 130
    except Exception:
        logger.exception("Run failed; inspect the log and run summary before retrying")
        return 1
    finally:
        if client is not None:
            client.close()
            logger.info("OBS connection closed")


if __name__ == "__main__":
    raise SystemExit(main())
