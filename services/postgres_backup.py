from os import path
from pathlib import Path
import logging

from utils.backup_paths import create_run
from utils.obs_upload import transfer_files
from utils.postgres_dump import create_dump

logger = logging.getLogger("backup")


def backup_postgres(settings, obs_client, obs_settings):
    now, run_dir = create_run("postgres")
    logger.info("Backup started: source=postgres output=%s", run_dir)

    for database in settings["databases"]:
        temporary = None

        try:
            pg_dump = Path(settings["pg_dump_path"]).expanduser()

            folder = run_dir / database
            folder.mkdir()

            file_path = folder / f"{database}_{now:%Y%m%d_%H%M%S_%f}.dump"
            temporary = file_path.with_suffix(".dump.partial")

            create_dump(settings, database, temporary, pg_dump)
            temporary.rename(file_path)

            base_key =base_key = f"Postgres/{settings['host']}/{database}/{now:%Y/%m/%d}/{file_path.stem}"

            transfer_files(obs_client, obs_settings, [file_path], base_key)

            logger.info("Database backup completed: %s", database)

        except Exception:
            logger.exception("Database backup failed: %s", database)

        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)