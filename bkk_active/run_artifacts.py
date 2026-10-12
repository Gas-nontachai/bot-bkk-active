"""Per-run screenshots, UI snapshots, and a chronological artifact index."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from .config import PROJECT_ROOT
from .logging_setup import LOGGER
from .metrics import RunMetrics

_active_run = None


def get_run_artifacts():
    return _active_run


def set_run_artifacts(artifacts):
    global _active_run
    _active_run = artifacts


class RunArtifacts:
    def __init__(self, parent=None, *, capture_mode="fast"):
        parent = Path(parent) if parent is not None else PROJECT_ROOT / "logger"
        timestamp = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d_%H-%M-%S_%f")
        self.folder = parent / timestamp
        self.screenshots = self.folder / "screenshots"
        self.ui = self.folder / "ui"
        self.screenshots.mkdir(parents=True, exist_ok=False)
        self.ui.mkdir()
        self.log_file = self.folder / "run.log"
        self.index_file = self.folder / "timeline.jsonl"
        self.step = "start"
        self.attempt = 1
        self.sequence = 0
        self.last_snapshot = None
        self.last_ui = None
        self.capture_mode = capture_mode
        self.metrics = RunMetrics()

    def set_step(self, label):
        self.step = label
        LOGGER.info("ขั้นตอน: %s", label)

    def capture(self, adb, serial, root, label=None, force=False):
        label = label or self.step
        xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        fingerprint = (self.attempt, label, hashlib.sha256(xml).hexdigest())
        if not force and fingerprint == self.last_snapshot:
            return self.folder
        self.sequence += 1
        now = datetime.now(ZoneInfo("Asia/Bangkok"))
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "screen"
        name = f"{self.sequence:04d}_attempt-{self.attempt:02d}_{now:%H-%M-%S-%f}_{safe_label}"
        xml_path = self.ui / f"{name}.xml"
        png_path = self.screenshots / f"{name}.png"
        xml_path.write_bytes(xml)
        started = time.perf_counter()
        try:
            image = subprocess.run([adb, "-s", serial, "exec-out", "screencap", "-p"],
                                   capture_output=True, timeout=15)
        finally:
            self.metrics.record("png_capture", time.perf_counter() - started)
        if image.returncode or not image.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("บันทึกภาพหน้าจอ PNG ไม่สำเร็จ")
        png_path.write_bytes(image.stdout)
        event = {"timestamp": now.isoformat(), "step": label, "sequence": self.sequence,
                 "attempt": self.attempt,
                 "screenshot": str(png_path.relative_to(self.folder)),
                 "ui": str(xml_path.relative_to(self.folder))}
        with self.index_file.open("a", encoding="utf-8") as index:
            index.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.last_snapshot = fingerprint
        LOGGER.info("ภาพขั้นตอน %s: %s", label, png_path)
        return self.folder

    def record_ui(self, root, label=None):
        """Persist changed XML without requesting a screenshot from the emulator."""
        started = time.perf_counter()
        label = label or self.step
        xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        fingerprint = (self.attempt, label, hashlib.sha256(xml).hexdigest())
        if fingerprint == self.last_ui:
            return
        self.sequence += 1
        now = datetime.now(ZoneInfo("Asia/Bangkok"))
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "screen"
        name = f"{self.sequence:04d}_attempt-{self.attempt:02d}_{now:%H-%M-%S-%f}_{safe_label}.xml"
        path = self.ui / name
        path.write_bytes(xml)
        event = {"timestamp": now.isoformat(), "step": label, "sequence": self.sequence,
                 "attempt": self.attempt, "screenshot": None,
                 "ui": str(path.relative_to(self.folder))}
        with self.index_file.open("a", encoding="utf-8") as index:
            index.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.last_ui = fingerprint
        self.metrics.record("xml_saved", time.perf_counter() - started)
