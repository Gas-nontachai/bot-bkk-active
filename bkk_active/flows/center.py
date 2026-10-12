"""Search for a center and enter its activity list."""
from ..middleware import flow_step
from ..errors import CenterNotFound
from ..ui import bounds
import time
from ..config import PACKAGE
from ..logging_setup import LOGGER, status


@flow_step("center-search")
def search_center(device, config, root):
    LOGGER.info("ค้นหาช่องค้นหาศูนย์บริการ")
    field = next((item for item in root.iter("node")
                  if item.get("package") == PACKAGE
                  and item.get("class") == "android.widget.EditText"
                  and item.get("enabled") == "true" and bounds(item)), None)
    if field is None:
        raise RuntimeError("ไม่พบช่องค้นหาศูนย์บริการ")
    device.tap(field)
    LOGGER.info("พิมพ์ค้นหา: %s", config.center)
    device.set_search_text(config.center)
    root = device.read_ui()
    if not any(item.get("class") == "android.widget.EditText"
               and item.get("text") == config.center for item in root.iter("node")):
        raise RuntimeError("ข้อความในช่องค้นหาไม่ตรงกับชื่อศูนย์")
    device.run("shell", "input", "keyevent", "KEYCODE_BACK")
    deadline = time.monotonic() + 15
    previous_results = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        root = device.read_ui()
        if device.dismiss_dialog(root):
            device.pause()
            continue
        node = next((item for item in root.iter("node")
                     if item.get("package") == PACKAGE
                     and config.center in (item.get("text"), item.get("content-desc"))
                     and item.get("class") != "android.widget.EditText"
                     and item.get("clickable") == "true"
                     and item.get("enabled") == "true" and bounds(item)), None)
        if node is not None:
            LOGGER.info("พบ %s: กดเข้าไป", config.center)
            device.tap(node)
            break
        labels = tuple(item.get("text") or item.get("content-desc")
                       for item in root.iter("node") if item.get("package") == PACKAGE
                       and (item.get("text") or item.get("content-desc")))
        if labels != previous_results:
            stable_since = time.monotonic()
            previous_results = labels
        empty = any(item.get("text") == "ไม่พบข้อมูล" for item in root.iter("node"))
        result_list = next((item for item in root.iter("node")
                            if item.get("package") == PACKAGE
                            and item.get("scrollable") == "true"), None)
        if result_list is not None:
            empty = empty or not any(item.get("text") or item.get("content-desc")
                                     for item in result_list.iter("node"))
        loading = any(item.get("class") == "android.widget.ProgressBar"
                      for item in root.iter("node"))
        if empty and not loading and time.monotonic() - stable_since >= 3:
            LOGGER.info("ไม่มี %s: ค้นหาแล้วไม่พบข้อมูล ปิดแอป", config.center)
            device.run("shell", "am", "force-stop", PACKAGE)
            raise CenterNotFound(f"ไม่มี {config.center}")
        device.pause()
    else:
        raise RuntimeError("ผลค้นหายังไม่ชัดเจน: ไม่พบศูนย์ที่ตรงชื่อหรือข้อความไม่พบข้อมูล")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = device.read_ui()
        if device.dismiss_dialog(root):
            device.pause()
            continue
        labels = [item.get("text", "") for item in root.iter("node")
                  if item.get("package") == PACKAGE]
        if "ไม่สามารถจองเข้าใช้บริการได้" in labels:
            status("แอปแจ้งว่าต้องสมัครสมาชิกศูนย์นี้ จบรอบการทำงาน")
            return
        if "เลือกกิจกรรม" in labels:
            LOGGER.info("เข้าหน้าเลือกกิจกรรมแล้ว")
            break
        device.pause()
    else:
        raise RuntimeError(f"กด {config.center} แล้ว แต่ยังไม่พบหน้าเลือกกิจกรรม")
    return True
