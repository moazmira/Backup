from datetime import datetime
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

from config.settings import BACKUP_DIR


def path_component(name):
    if name in (".", ".."):
        return name.replace(".", "%2E")
    return quote(name, safe="_.")


def create_run(source):
    now = datetime.now(ZoneInfo("Africa/Cairo"))
    run_dir = BACKUP_DIR / source / (now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    return now, run_dir
