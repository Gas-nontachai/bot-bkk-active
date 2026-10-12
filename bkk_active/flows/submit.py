"""Validate the booking summary and submit once."""
from ..middleware import flow_step
from ..ui import confirmation_matches, is_review_page, ui_labels
from ..vision import orange_submit_center
from .review import submit_review
import time
from ..logging_setup import LOGGER


@flow_step("submit-booking")
def select_slot(device, config, number, slot):
    node, interval = slot
    LOGGER.info("เลือกสิทธิ์ 1 ชั่วโมง: สนามแบดมินตัน %d วันที่ %s เวลา %s",
                number, config.date.isoformat(), interval)
    device.tap(node)
    LOGGER.info("รอหน้ายืนยันการจอง")
    root = device.wait_for(lambda ui: confirmation_matches(ui, config.date, number, interval),
                    "ไม่พบหน้ายืนยันที่วัน สนาม และเวลาตรงกับตัวเลือก จึงไม่ได้กด Submit")
    LOGGER.info("ตรวจข้อมูลยืนยันตรงกัน: วันที่=%s สนาม=%d เวลา=%s",
                config.date.isoformat(), number, interval)
    raw = device.screenshot_raw()
    x, y = orange_submit_center(raw)
    LOGGER.info("กดปุ่ม Submit สีส้มที่ (%d, %d)", x, y)
    device.run("shell", "input", "tap", str(x), str(y))
    booking_logged = False
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        root = device.read_ui()
        text = " ".join(ui_labels(root)).lower()
        failed = any(word in text for word in ("ไม่สำเร็จ", "ผิดพลาด", "ไม่สามารถ", "failed"))
        success = (any(word in text for word in ("จองสำเร็จ", "การจองสำเร็จ", "booking successful", "booking confirmed"))
                   or ("การจองของคุณ" in ui_labels(root)
                       and confirmation_matches(root, config.date, number, interval)))
        if failed:
            raise RuntimeError(f"แอปแจ้งข้อผิดพลาดหลัง Submit: {text}")
        if is_review_page(root):
            LOGGER.info("ถึงหน้า Booking Review หลัง Submit การจอง")
            submit_review(device, config, root)
            return
        if success and not booking_logged:
            LOGGER.info("จองสำเร็จ: สนาม %d วันที่ %s เวลา %s", number, config.date.isoformat(), interval)
            booking_logged = True
        if device.dismiss_dialog(root):
            LOGGER.info("ปิด dialog หลัง Submit รอตรวจผลการจอง")
        device.pause()
    if booking_logged:
        raise RuntimeError("จองสำเร็จแล้ว แต่ไม่พบหน้า Booking Review จึงยังส่งรีวิวไม่ได้")
    raise RuntimeError("กด Submit แล้ว แต่ยังยืนยันผลไม่ได้ เก็บภาพไว้และไม่กด Submit ซ้ำ")
