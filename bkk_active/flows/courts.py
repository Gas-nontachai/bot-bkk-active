"""Inspect courts in order and return the first available slot."""
from dataclasses import dataclass
from ..middleware import flow_step
from ..ui import back_button, court_button, is_court_list, ui_labels
from .schedule import open_court, find_available_slot
from ..logging_setup import LOGGER, status
from ..policy import time_window_label


@dataclass
class CourtProgress:
    next_court: int = 1


@flow_step("locate-court")
def locate_court(device, config, number, from_top=False):
    if from_top:
        previous, unchanged = None, 0
        for _ in range(31):
            root = device.read_ui(cached=True)
            node = court_button(root, number)
            if node is not None:
                return node
            current = device.signature(root)
            unchanged = unchanged + 1 if current == previous else 0
            if unchanged >= 2 or not device.scroll_down(root, upward=True):
                break
            previous = current
        else:
            raise RuntimeError("เลื่อนกลับต้นรายการสนามไม่สำเร็จ")
    previous, unchanged = None, 0
    for attempt in range(31):
        root = device.read_ui(cached=(attempt == 0))
        node = court_button(root, number)
        if node is not None:
            return node
        current = device.signature(root)
        unchanged = unchanged + 1 if current == previous else 0
        if unchanged >= 2 or not device.scroll_down(root):
            return None
        previous = current
        LOGGER.info("เลื่อนหาสนามแบดมินตัน %d ครั้งที่ %d", number, attempt + 1)
    raise RuntimeError("เลื่อนหารายชื่อสนามครบ 30 ครั้ง แต่ยังไม่ถึงท้ายรายการ")


@flow_step("back-to-courts")
def back_to_courts(device, config):
    LOGGER.info("กลับไปหน้าเลือกสนาม")
    root = device.read_ui()
    if is_court_list(root):
        return
    if "เลือกจองวัน-เวลา" not in ui_labels(root):
        raise RuntimeError("ไม่ได้อยู่หน้าเลือกจองวัน-เวลา จึงกลับไปหน้าเลือกสนามไม่ได้")
    button = back_button(root)
    if button is None:
        raise RuntimeError("ไม่พบปุ่มย้อนกลับของแอปบนหน้าเลือกจองวัน-เวลา")
    device.tap(button)
    device.wait_for(is_court_list, "กลับไปหน้าเลือกสนามไม่ได้")


@flow_step("court-list")
def choose_court_slot(device, config):
    progress = getattr(config, "court_progress", None)
    if progress is None:
        progress = CourtProgress()
    device.wait_for(is_court_list, "ยังไม่พบหน้าเลือกสนามแบดมินตัน")
    LOGGER.info("เข้าหน้าเลือกสนามแล้ว: จะตรวจเวลาว่างทีละสนาม")
    for number in range(progress.next_court, 8):
        name = f"สนามแบดมินตัน {number}"
        court = locate_court(device, config, number)
        if court is None:
            LOGGER.info("ไม่มี %s ในรายการ ข้ามไปสนามถัดไป", name)
            progress.next_court = number + 1
            continue
        root = open_court(device, config, number, court)
        LOGGER.info("ตรวจ %s: เลือกช่องว่างแรกที่พบ %s", name, time_window_label(config))
        slot = find_available_slot(device, config, root)
        if slot is not None:
            _, interval = slot
            LOGGER.info("พบช่องว่าง: %s เวลา %s เลือกทันที", name, interval)
            return number, slot
        else:
            LOGGER.info("ไม่มีช่องว่าง %s ที่ %s", time_window_label(config), name)
        progress.next_court = number + 1
        back_to_courts(device, config)

    status("ไม่มีช่องว่าง %s วันที่ %s จบการตรวจวันนี้", time_window_label(config), config.date.isoformat())
