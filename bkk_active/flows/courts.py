"""Compare courts and return one app-defined slot closest to 18:00."""
from ..middleware import flow_step
import re
from ..ui import activity_button, ui_labels
from ..policy import ranked_courts
from .schedule import open_court, find_evening_slot
from ..logging_setup import LOGGER, status


@flow_step("locate-court")
def locate_court(device, config, number, from_top=False):
    if from_top:
        previous, unchanged = None, 0
        for _ in range(31):
            root = device.read_ui(cached=True)
            node = activity_button(root, f"สนามแบดมินตัน {number}")
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
        node = activity_button(root, f"สนามแบดมินตัน {number}")
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
    device.run("shell", "input", "keyevent", "KEYCODE_BACK")
    device.wait_for(lambda ui: any(re.fullmatch(r"สนามแบดมินตัน [1-7]", label)
                           for label in ui_labels(ui))
             and "เลือกจองวัน-เวลา" not in ui_labels(ui), "กลับไปหน้าเลือกสนามไม่ได้")


@flow_step("court-list")
def choose_court_slot(device, config):
    device.wait_for(lambda ui: any(re.fullmatch(r"สนามแบดมินตัน [1-7]", label)
                           for label in ui_labels(ui)), "ยังไม่พบหน้าเลือกสนามแบดมินตัน")
    LOGGER.info("เข้าหน้าเลือกสนามแล้ว: จะตรวจเวลาว่างทีละสนาม")
    candidates = []
    for number in range(1, 8):
        name = f"สนามแบดมินตัน {number}"
        court = locate_court(device, config, number)
        if court is None:
            LOGGER.info("ไม่มี %s ในรายการ ข้ามไปสนามถัดไป", name)
            continue
        root = open_court(device, config, number, court)
        LOGGER.info("ตรวจ %s: เลือก 1 ช่องที่ว่าง ภายใน 18:00–21:00", name)
        slot = find_evening_slot(device, config, root)
        if slot is not None:
            _, interval = slot
            LOGGER.info("พบตัวเลือก: %s เวลา %s", name, interval)
            if interval.startswith("18:00–"):
                LOGGER.info("พบเวลาเริ่ม 18:00 ตรงเป้าหมาย เลือกทันที")
                return number, slot
            candidates.append((number, interval))
            LOGGER.info("เก็บตัวเลือกไว้ แล้วตรวจสนามอื่นเพื่อหาเวลาที่ใกล้ 18:00 กว่า")
        else:
            LOGGER.info("ไม่มีช่องว่างช่วง 18:00–21:00 ที่ %s", name)
        back_to_courts(device, config)

    for number, interval in ranked_courts(candidates):
        LOGGER.info("ตรวจตัวเลือกที่ใกล้ 18:00 ที่สุดอีกครั้ง: สนาม %d เวลา %s", number, interval)
        court = locate_court(device, config, number, from_top=True)
        if court is None:
            LOGGER.info("สนาม %d หายจากรายการ ข้ามตัวเลือก", number)
            continue
        root = open_court(device, config, number, court)
        slot = find_evening_slot(device, config, root, exact_interval=interval)
        if slot is not None:
            return number, slot
        LOGGER.info("สนาม %d เวลา %s ไม่ว่างแล้ว ข้ามไปตัวเลือกถัดไป", number, interval)
        back_to_courts(device, config)
    status("ไม่มีช่องว่างช่วง 18:00–21:00 วันที่ %s จบสคริปต์", config.date.isoformat())
