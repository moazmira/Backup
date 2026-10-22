from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import BACKUP_DIR


def create_run(source):
    now = datetime.now(ZoneInfo("Africa/Cairo"))
    run_dir = BACKUP_DIR / source / now.strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True)
    return now, run_dir
