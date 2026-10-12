"""Select the badminton activity."""
from ..middleware import flow_step
from ..ui import activity_button
import time
from ..logging_setup import LOGGER, status


@flow_step("activity")
def select_activity(device, config):
    LOGGER.info("ค้นหากิจกรรม สนามแบดมินตัน")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = device.read_ui()
        if device.dismiss_dialog(root):
            device.pause()
            continue
        node = activity_button(root)
        if node is not None:
            LOGGER.info("พบกิจกรรม: กด สนามแบดมินตัน")
            device.tap(node)
            break
        device.pause()
    else:
        status("ไม่มี สนามแบดมินตัน บนหน้ากิจกรรม จบสคริปต์")
        return
    return True
