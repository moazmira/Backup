import json
from datetime import datetime
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

from config.settings import BACKUP_DIR


def cairo_now():
    return datetime.now(ZoneInfo("Africa/Cairo"))


def path_component(name):
    return quote(name, safe="_").replace(".", "%2E")


def create_run(source):
    now = cairo_now()
    run_dir = BACKUP_DIR / source / (now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    return now, run_dir


def save_summary(run_dir, summary):
    temporary = run_dir / "summary.json.partial"
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(run_dir / "summary.json")
