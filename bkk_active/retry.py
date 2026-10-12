"""Restart only when center search reports no results."""
import time
from .errors import CenterNotFound
from .logging_setup import LOGGER


def retry_missing_center(action, retries=3):
    for attempt in range(retries + 1):
        LOGGER.info("รอบค้นหาศูนย์ %d/%d (retry %d/%d)", attempt + 1, retries + 1, attempt, retries)
        try:
            return action()
        except CenterNotFound as error:
            if attempt == retries:
                LOGGER.info("%s: ลองซ้ำครบ %d ครั้งแล้ว จบการทำงาน", error, retries)
                return
            LOGGER.info("%s: ปิดแอปแล้ว รอ 2 วินาที ก่อนเริ่ม flow ใหม่ (retry %d/%d)",
                        error, attempt + 1, retries)
            time.sleep(2)
