import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import LOG_DIR

CAIRO = ZoneInfo("Africa/Cairo")


class CairoFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, CAIRO).strftime("%Y-%m-%d %H:%M:%S")


def setup_logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now(CAIRO):%Y%m%d_%H%M%S_%f}.log"
    logger = logging.getLogger("backup")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    formatter = CairoFormatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.info("Run started. Cairo timezone. Log file: %s", log_file)
    return logger
