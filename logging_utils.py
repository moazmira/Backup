import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logger():
    log_dir = Path(__file__).with_name("logs")
    log_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file = log_dir / f"{run_id}_{Path(__file__).stem}.log"

    logger = logging.getLogger("postgres_dump")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.info("Run started. Log file: %s", log_file)
    return logger


