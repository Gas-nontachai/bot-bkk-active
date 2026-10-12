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


def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(BangkokFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
