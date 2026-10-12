"""Timestamped logs in Bangkok time."""
from datetime import datetime
import logging
import sys
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger("bkk-active")


class BangkokFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, ZoneInfo("Asia/Bangkok")).strftime(
            "%Y-%m-%d %H:%M:%S %z"
        )


def configure_logging(log_file=None):
    for existing in LOGGER.handlers[:]:
        LOGGER.removeHandler(existing)
        existing.close()
    formatter = BangkokFormatter("%(asctime)s [%(levelname)s] %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    if log_file is not None:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
