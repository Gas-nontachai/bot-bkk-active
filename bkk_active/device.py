"""ADB commands, UI polling, navigation, and artifact capture."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from .config import PACKAGE
from .logging_setup import LOGGER
from .ui import bounds
from .run_artifacts import get_run_artifacts
from .middleware import CaptureLoggingMiddleware


class AndroidDevice:
    def __init__(self, serial):
        self.serial = serial
        self.middleware = CaptureLoggingMiddleware(get_run_artifacts())
        self.adb = os.environ.get('ADB') or shutil.which('adb')
        if not self.adb:
            self.adb = str(Path.home() / 'Library/Android/sdk/platform-tools/adb')
        if not Path(self.adb).is_file():
            raise RuntimeError('ไม่พบ adb: ตั้งค่า ADB เป็น path ของ platform-tools/adb')

    def run(self, *command):
        self.middleware.before_command(self, command)
        result = subprocess.run(
            [self.adb, "-s", self.serial, *command], capture_output=True,
            text=True, timeout=15,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                               or f"ADB {command} จบด้วย exit code {result.returncode}")
        return result.stdout

    def read_ui(self):
        self.run("shell", "uiautomator", "dump", "/sdcard/bkk-active-ui.xml")
        root = ET.fromstring(self.run("shell", "cat", "/sdcard/bkk-active-ui.xml"))
        self.middleware.observe_ui(self, root)
        return root

    def tap(self, node):
        coords = bounds(node)
        if not coords:
            raise RuntimeError("อ่านตำแหน่งปุ่มไม่ได้")
        x1, y1, x2, y2 = coords
        LOGGER.info("กดหน้าจอที่ (%d, %d)", (x1 + x2) // 2, (y1 + y2) // 2)
        self.run("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))

    def dismiss_dialog(self, root):
        for node in root.iter("node"):
            if (node.get("package") == PACKAGE
                    and "ตกลง" in (node.get("text"), node.get("content-desc"))
                    and node.get("clickable") == "true"
                    and node.get("enabled") == "true"):
                LOGGER.info("พบ dialog: กด ตกลง")
                self.tap(node)
                return True
        return False

    def wait_for(self, predicate, message):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            root = self.read_ui()
            if self.dismiss_dialog(root):
                time.sleep(1)
                continue
            if predicate(root):
                return root
            time.sleep(1)
        raise RuntimeError(message)

    def scroll_down(self, root, upward=False):
        scrolls = [node for node in root.iter("node")
                   if node.get("package") == PACKAGE
                   and node.get("scrollable") == "true" and bounds(node)]
        if not scrolls:
            return False
        # แถบวันที่เป็นแนวนอน เลือกรายการสนาม/เวลาที่สูงที่สุด
        node = max(scrolls, key=lambda item: bounds(item)[3] - bounds(item)[1])
        x1, y1, x2, y2 = bounds(node)
        if y2 - y1 < x2 - x1:
            return False
        x = (x1 + x2) // 2
        height = y2 - y1
        begin, end = y2 - height // 10, y1 + height // 5
        if upward:
            begin, end = end, begin
        self.run("shell", "input", "swipe", str(x), str(begin), str(x), str(end), "450")
        time.sleep(0.5)
        return True

    def signature(self, root):
        return tuple((node.get("text"), node.get("content-desc"), node.get("bounds"))
                     for node in root.iter("node") if node.get("package") == PACKAGE
                     and bounds(node) and (node.get("text") or node.get("content-desc")))

