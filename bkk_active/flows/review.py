"""Submit the existing review form and finish."""
from ..middleware import flow_step
from ..ui import is_review_page, ui_labels
from ..vision import orange_submit_center
import time
from ..logging_setup import LOGGER, status


@flow_step("review")
def submit_review(device, config, root):
    raw = device.screenshot_raw()
    x, y = orange_submit_center(raw)
    LOGGER.info("กดปุ่ม Review สีส้มที่ (%d, %d)", x, y)
    device.run("shell", "input", "tap", str(x), str(y))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        root = device.read_ui()
        labels = ui_labels(root)
        text = " ".join(labels).lower()
        if any(word in text for word in ("ไม่สำเร็จ", "ผิดพลาด", "ไม่สามารถ", "failed")):
            raise RuntimeError(f"แอปแจ้งข้อผิดพลาดหลัง Review: {text}")
        if (labels and not is_review_page(root)) or any(word in text for word in (
                "รีวิวสำเร็จ", "ประเมินสำเร็จ", "review submitted", "ขอบคุณ", "thank you")):
            status("ส่ง Review แล้วและออกจากหน้ารีวิว/ได้รับข้อความตอบรับ จบ flow")
            device.dismiss_dialog(root)
            return
        if device.dismiss_dialog(root):
            LOGGER.info("ปิด dialog หลัง Review รอตรวจผล")
        device.pause()
    raise RuntimeError("กด Review แล้ว แต่ยังไม่ออกจากหน้ารีวิว เก็บภาพไว้และไม่กดซ้ำ")
