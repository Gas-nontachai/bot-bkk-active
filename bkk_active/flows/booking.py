"""Open booking tab and create a new booking."""
from ..middleware import flow_step
from ..ui import booking_tab
import time
from ..config import PACKAGE
from ..logging_setup import LOGGER


@flow_step("booking")
def open_booking(device, config):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        root = device.read_ui()
        if device.dismiss_dialog(root):
            device.pause()
            continue
        node = booking_tab(root)
        if node is not None:
            LOGGER.info("กดเข้า จองคิว")
            device.tap(node)
            break
        device.pause()
    else:
        raise RuntimeError("ไม่พบแท็บจองคิวภายในเวลาที่กำหนด ตรวจหน้าจอแอป")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = device.read_ui()
        if device.dismiss_dialog(root):
            device.pause()
            continue
        node = next((item for item in root.iter("node")
                     if item.get("package") == PACKAGE
                     and "สร้างการจองใหม่" in (item.get("text"), item.get("content-desc"))
                     and item.get("clickable") == "true"
                     and item.get("enabled") == "true"), None)
        if node is not None:
            LOGGER.info("กด สร้างการจองใหม่")
            device.tap(node)
            break
        device.pause()
    else:
        raise RuntimeError("ไม่พบปุ่มสร้างการจองใหม่ ตรวจหน้าจอแอป")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = device.read_ui()
        if device.dismiss_dialog(root):
            device.pause()
            continue
        if any(item.get("package") == PACKAGE
               and item.get("text") == "เลือกศูนย์กีฬา"
               for item in root.iter("node")):
            LOGGER.info("เข้าหน้าเลือกศูนย์กีฬาแล้ว")
            break
        device.pause()
    else:
        raise RuntimeError("กดสร้างการจองใหม่แล้ว แต่ยังไม่พบหน้าเลือกศูนย์กีฬา")
    return root
