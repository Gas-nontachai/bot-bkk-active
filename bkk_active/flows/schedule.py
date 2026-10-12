"""Select the date and inspect available evening slots."""
from ..middleware import flow_step
from ..config import TIME_RANGE
from ..ui import activity_button, selected_date_matches, ui_labels
from ..policy import available_slot
from ..logging_setup import LOGGER


@flow_step("choose-date")
def choose_date(device, config, root):
    LOGGER.info("เลือกวันที่ %s ตามเวลาไทย", config.date.isoformat())
    if not selected_date_matches(root, config.date):
        node = activity_button(root, str(config.date.day))
        if node is None:
            raise RuntimeError(f"ไม่พบปุ่มวันที่ {config.date.isoformat()} บนแถบวันที่")
        device.tap(node)
        root = device.wait_for(lambda ui: selected_date_matches(ui, config.date),
                        f"ยืนยันวันที่ {config.date.isoformat()} ไม่ได้")
    LOGGER.info("ยืนยันวันที่เลือก: %s", config.date.isoformat())
    return root


@flow_step("find-evening-time")
def find_evening_slot(device, config, root, exact_interval=None):
    previous, unchanged = None, 0
    for attempt in range(41):
        slot = available_slot(root, exact_interval=exact_interval)
        if slot is not None:
            return slot
        current = device.signature(root)
        unchanged = unchanged + 1 if current == previous else 0
        if unchanged >= 2 or not device.scroll_down(root):
            return None
        previous = current
        LOGGER.info("เลื่อนหาเวลาว่าง 18:00–21:00 ครั้งที่ %d", attempt + 1)
        root = device.read_ui()
    raise RuntimeError("เลื่อนหน้าเวลาครบ 40 ครั้ง แต่ยังไม่ถึงท้ายรายการ")


@flow_step("court-schedule")
def open_court(device, config, number, court):
    name = f"สนามแบดมินตัน {number}"
    LOGGER.info("กด %s เพื่อดูเวลาว่าง", name)
    device.tap(court)
    root = device.wait_for(lambda ui: "เลือกจองวัน-เวลา" in ui_labels(ui),
                    f"กด {name} แล้ว แต่ยังไม่พบหน้าเลือกจองวัน-เวลา")
    root = choose_date(device, config, root)
    return device.wait_for(lambda ui: not any(item.get("class") == "android.widget.ProgressBar"
                                       for item in ui.iter("node"))
                    and (any(TIME_RANGE.search(label) for label in ui_labels(ui))
                         or "ไม่พบข้อมูล" in ui_labels(ui)),
                    f"รายการเวลาของ {name} ยังโหลดไม่เสร็จ", initial=root)
