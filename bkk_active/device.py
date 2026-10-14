"""ADB commands, UI polling, navigation, and artifact capture."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from .config import PACKAGE
from .logging_setup import LOGGER
from .ui import bounds, is_busy_screen
from .errors import AppBusy
from .run_artifacts import get_run_artifacts
from .middleware import CaptureLoggingMiddleware
from .android_bridge import AndroidBridge


class AndroidDevice:
    def __init__(self, serial, ui_backend="bridge"):
        self.serial = serial
        self.middleware = CaptureLoggingMiddleware(get_run_artifacts())
        self.cached_root = None
        self.cache_valid = False
        self.ui_backend = ui_backend
        self.bridge = AndroidBridge(self)
        self.bridge_failed = False
        self.adb = os.environ.get('ADB') or shutil.which('adb')
        if not self.adb:
            self.adb = str(Path.home() / 'Library/Android/sdk/platform-tools/adb')
        if not Path(self.adb).is_file():
            raise RuntimeError('ไม่พบ adb: ตั้งค่า ADB เป็น path ของ platform-tools/adb')

    def run(self, *command):
        self.middleware.before_command(self, command)
        if command[:2] in (("shell", "input"), ("shell", "am")) or command[0] == "install":
            self.cache_valid = False
        started = time.perf_counter()
        try:
            result = subprocess.run(
                [self.adb, "-s", self.serial, *command], capture_output=True,
                text=True, timeout=15,
            )
        finally:
            self.record_metric("adb_command", time.perf_counter() - started)
            if command[:3] == ("shell", "input", "tap"):
                self.record_metric("tap", time.perf_counter() - started)
            elif command[:3] == ("shell", "input", "swipe"):
                self.record_metric("swipe", time.perf_counter() - started)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                               or f"ADB {command} จบด้วย exit code {result.returncode}")
        return result.stdout

    def record_metric(self, category, elapsed):
        artifacts = self.middleware.artifacts
        if artifacts is not None:
            artifacts.metrics.record(category, elapsed)

    def pause(self, seconds=1):
        time.sleep(seconds if self.middleware.debug_capture else min(seconds, 0.15))

    def read_ui(self, *, cached=False):
        if cached and self.cache_valid:
            self.record_metric("ui_cache_hit", 0)
            self.check_busy_screen(self.cached_root)
            return self.cached_root
        started = time.perf_counter()
        try:
            if getattr(self, "ui_backend", "uiautomator") == "bridge" and not self.bridge_failed:
                try:
                    root = self.bridge.read_ui()
                    self.record_metric("bridge_ui_read", time.perf_counter() - started)
                except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
                    self.record_metric("bridge_ui_failure", time.perf_counter() - started)
                    LOGGER.warning("Android bridge ใช้ไม่ได้ กลับไปอ่าน UI แบบเดิม: %s", error)
                    self.bridge_failed = True
                    root = self.read_ui_legacy()
            else:
                root = self.read_ui_legacy()
        finally:
            self.record_metric("ui_read", time.perf_counter() - started)
        self.cached_root, self.cache_valid = root, True
        self.middleware.observe_ui(self, root)
        self.check_busy_screen(root)
        return root

    def check_busy_screen(self, root):
        if not self.middleware.reading_snapshot and is_busy_screen(root):
            raise AppBusy("พบหน้ารอผู้ใช้บริการจำนวนมากของแอป")

    def read_ui_legacy(self):
        started = time.perf_counter()
        try:
            xml = self.run("shell", "uiautomator dump /sdcard/bkk-active-ui.xml >/dev/null && cat /sdcard/bkk-active-ui.xml")
            return ET.fromstring(xml)
        finally:
            self.record_metric("legacy_ui_read", time.perf_counter() - started)

    def set_search_text(self, text):
        self.bridge.set_text(text)

    def screenshot_raw(self):
        started = time.perf_counter()
        try:
            image = subprocess.run([self.adb, "-s", self.serial, "exec-out", "screencap"],
                                   capture_output=True, timeout=15)
            if image.returncode:
                raise RuntimeError("อ่านภาพหน้าจอไม่ได้")
            return image.stdout
        finally:
            self.record_metric("raw_capture", time.perf_counter() - started)

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

    def wait_for(self, predicate, message, initial=None):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            root = initial if initial is not None else self.read_ui()
            initial = None
            if is_busy_screen(root):
                raise AppBusy("พบหน้ารอผู้ใช้บริการจำนวนมากของแอป")
            if self.dismiss_dialog(root):
                self.pause()
                continue
            if predicate(root):
                return root
            self.pause()
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
        duration = "450" if self.middleware.debug_capture else "250"
        self.run("shell", "input", "swipe", str(x), str(begin), str(x), str(end), duration)
        self.pause(0.5)
        return True

    def signature(self, root):
        return tuple((node.get("text"), node.get("content-desc"), node.get("bounds"))
                     for node in root.iter("node") if node.get("package") == PACKAGE
                     and bounds(node) and (node.get("text") or node.get("content-desc")))

