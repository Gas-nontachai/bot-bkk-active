"""Validate device and launch BKK Active."""
from ..config import ACTIVITY
from ..config import PACKAGE
from ..logging_setup import LOGGER


def launch(device, config):
    LOGGER.info("เริ่มสคริปต์: อุปกรณ์=%s, ศูนย์=%s, วันที่=%s, เวลา=18:00–21:00",
                config.serial, config.center, config.date.isoformat())
    if device.run("get-state").strip() != "device":
        raise RuntimeError(f"อุปกรณ์ {config.serial} ยังไม่พร้อม")
    if not device.run("shell", "pm", "path", PACKAGE).strip().startswith("package:"):
        raise RuntimeError("ยังไม่ได้ติดตั้ง BKK Active")

    LOGGER.info("เปิด BKK Active บน %s", config.serial)
    output = device.run("shell", "am", "start", "-S", "-W", "-n", ACTIVITY)
    if "Error:" in output or "Exception" in output:
        raise RuntimeError(output.strip())
