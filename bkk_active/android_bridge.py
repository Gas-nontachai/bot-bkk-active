"""Read accessibility trees through the local helper without uiautomator idle waits."""
import base64
import hashlib
import re
import subprocess
import xml.etree.ElementTree as ET

from .config import PROJECT_ROOT
from .logging_setup import LOGGER

COMPONENT = "local.bkkactive.textinput/local.bkkactive.textinput.TextInput"
_prepared = set()


def parse_dump(output):
    match = re.search(r"^INSTRUMENTATION_RESULT: xml64=(\S+)$", output, re.MULTILINE)
    if not match or "INSTRUMENTATION_CODE: -1" not in output:
        raise RuntimeError(f"ตัวช่วยอ่าน UI ไม่สำเร็จ: {output.strip()}")
    try:
        root = ET.fromstring(base64.b64decode(match.group(1), validate=True))
    except (ValueError, ET.ParseError) as error:
        raise RuntimeError("ข้อมูล UI จากตัวช่วยไม่สมบูรณ์") from error
    if root.tag != "hierarchy" or root.find("node") is None:
        raise RuntimeError("ตัวช่วยยังอ่านหน้าต่างที่พร้อมใช้งานไม่ได้")
    return root


class AndroidBridge:
    def __init__(self, device):
        self.device = device
        self.ready = False
        self.prepared_key = None

    def prepare(self):
        if self.ready:
            return
        directory = PROJECT_ROOT / "tools" / "android-text-input"
        apk = directory / ".build/text-input.apk"
        sources = [directory / name for name in ("TextInput.java", "AndroidManifest.xml", "build.sh")]
        if not apk.exists() or any(source.stat().st_mtime_ns > apk.stat().st_mtime_ns for source in sources):
            LOGGER.info("สร้าง Android bridge สำหรับอ่าน UI เร็ว")
            result = subprocess.run(["sh", str(directory / "build.sh")],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError(f"สร้าง Android bridge ไม่สำเร็จ: {result.stderr.strip()}")
        key = (self.device.adb, self.device.serial, hashlib.sha256(apk.read_bytes()).hexdigest())
        if key not in _prepared:
            # Probe the installed version first; install only on a mismatch or missing helper.
            try:
                output = self.device.run("shell", "am", "instrument", "-w", "-e", "action", "version", COMPONENT)
            except RuntimeError:
                output = ""
            if "BRIDGE_VERSION_3" not in output:
                LOGGER.info("ติดตั้ง Android bridge บน %s", self.device.serial)
                self.device.run("install", "-r", str(apk))
            _prepared.add(key)
        self.prepared_key = key
        self.ready = True

    def read_ui(self):
        self.prepare()
        try:
            output = self.device.run("shell", "am", "instrument", "-w", "-e", "action", "dump", COMPONENT)
            return parse_dump(output)
        except RuntimeError:
            self.ready = False
            _prepared.discard(self.prepared_key)
            raise

    def set_text(self, text):
        self.prepare()
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        output = self.device.run("shell", "am", "instrument", "-w", "-e", "text64", encoded, COMPONENT)
        if "TEXT_SET_OK" not in output:
            raise RuntimeError(f"ป้อนข้อความไม่ได้: {output.strip()}")
