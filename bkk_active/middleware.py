"""Capture and log flow boundaries, UI changes, actions, and errors."""
from contextlib import contextmanager
from functools import wraps
import subprocess
import time
import xml.etree.ElementTree as ET

from .errors import CenterNotFound
from .logging_setup import LOGGER, status


class CaptureLoggingMiddleware:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts
        self.current_step = "start"
        self.last_root = None
        self.last_error = None
        self.reading_snapshot = False

    @property
    def debug_capture(self):
        # Unconfigured test/fake artifact providers retain the full-capture behavior.
        return getattr(self.artifacts, "capture_mode", "debug") != "fast"

    def _capture(self, device, label, root=None, force=False):
        if self.artifacts is None:
            return
        try:
            if root is None:
                self.reading_snapshot = True
                try:
                    root = device.read_ui()
                finally:
                    self.reading_snapshot = False
            self.artifacts.capture(device.adb, device.serial, root, label=label, force=force)
        except (RuntimeError, OSError, subprocess.TimeoutExpired, ET.ParseError) as error:
            LOGGER.warning("เก็บภาพ %s ไม่สำเร็จ: %s", label, error)

    def observe_ui(self, device, root):
        self.last_root = root
        if not self.reading_snapshot:
            if self.artifacts is not None and not self.debug_capture:
                try:
                    self.artifacts.record_ui(root, self.current_step)
                except OSError as error:
                    LOGGER.warning("เก็บ XML ขั้นตอน %s ไม่สำเร็จ: %s", self.current_step, error)
            else:
                self._capture(device, self.current_step, root)

    def before_command(self, device, command):
        # Observe navigation commands, not repeated XML reads or queries.
        if command[:2] == ("shell", "input"):
            action = "input-" + command[2]
        elif command[:3] == ("shell", "am", "force-stop"):
            action = "close-app"
        elif command[:3] == ("shell", "am", "start"):
            action = "launch-app"
        else:
            return
        LOGGER.info("ทำงาน [%s]: %s", self.current_step, " ".join(command))
        critical = action == "close-app" or (action == "input-tap" and
                    any(step in self.current_step for step in ("submit-booking", "review")))
        if self.debug_capture or critical:
            self._capture(device, f"{self.current_step}-before-{action}", self.last_root, force=True)

    @contextmanager
    def step(self, device, name):
        previous = self.current_step
        self.current_step = name if previous == "start" else f"{previous}/{name}"
        label = self.current_step
        if self.artifacts is not None:
            self.artifacts.set_step(label)
        started = time.monotonic()
        LOGGER.info("เริ่มขั้นตอน %s", label)
        if previous == "start" or name == "review":
            descriptions = {"launch": "เปิดแอป", "booking": "เข้าหน้าจอง",
                            "center-search": "ค้นหาศูนย์กีฬา", "activity": "เลือกแบดมินตัน",
                            "court-list": "ตรวจสอบสนามและเวลาว่าง", "submit-booking": "ยืนยันการจอง",
                            "review": "ส่งรีวิว"}
            status("กำลัง%s", descriptions.get(name, name))
        if self.debug_capture:
            self._capture(device, f"{label}-before", force=True)
        outcome = "completed"
        try:
            yield
        except CenterNotFound:
            outcome = "center_not_found"
            # The close-app command already captures search results before closing.
            LOGGER.info("ขั้นตอน %s: ไม่พบศูนย์ ใช้เวลา %.2f วินาที", label, time.monotonic() - started)
            raise
        except Exception as error:
            outcome = "error"
            if error is not self.last_error:
                self.last_error = error
                LOGGER.exception("ขั้นตอน %s ล้มเหลว หลัง %.2f วินาที", label, time.monotonic() - started)
                self._capture(device, f"{label}-error", force=True)
            raise
        else:
            if self.debug_capture or name in ("center-search", "submit-booking", "review"):
                root = self.last_root if (not self.debug_capture and
                        getattr(device, "cache_valid", False)) else None
                self._capture(device, f"{label}-after", root, force=True)
            LOGGER.info("จบขั้นตอน %s ใช้เวลา %.2f วินาที", label, time.monotonic() - started)
        finally:
            if self.artifacts is not None:
                self.artifacts.metrics.record_step(label, time.monotonic() - started,
                                                   outcome, self.artifacts.attempt)
            self.current_step = previous
            if self.artifacts is not None:
                self.artifacts.step = previous


def flow_step(name):
    """Decorate a flow without changing its result or retry/submit behavior."""
    def decorate(function):
        @wraps(function)
        def wrapped(device, *args, **kwargs):
            middleware = getattr(device, "middleware", None)
            if not isinstance(middleware, CaptureLoggingMiddleware):
                return function(device, *args, **kwargs)
            label = name(device, *args, **kwargs) if callable(name) else name
            with middleware.step(device, label):
                return function(device, *args, **kwargs)
        return wrapped
    return decorate
