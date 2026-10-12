"""Restart only when center search reports no results."""
import time
from .errors import CenterNotFound
from .logging_setup import LOGGER, status
from .run_artifacts import get_run_artifacts


def retry_missing_center(action, retries=3):
    for attempt in range(retries + 1):
        artifacts = get_run_artifacts()
        if artifacts is not None:
            artifacts.attempt = attempt + 1
        LOGGER.info("รอบค้นหาศูนย์ %d/%d (retry %d/%d)", attempt + 1, retries + 1, attempt, retries)
        try:
            return action()
        except CenterNotFound as error:
            if attempt == retries:
                status("%s: ลองซ้ำครบ %d ครั้งแล้ว จบการทำงาน", error, retries)
                return "center_not_found"
            LOGGER.info("%s: ปิดแอปแล้ว รอ 2 วินาที ก่อนเริ่ม flow ใหม่ (retry %d/%d)",
                        error, attempt + 1, retries)
            status("ไม่พบศูนย์ กำลังลองใหม่ %d/%d", attempt + 1, retries)
            time.sleep(2)
