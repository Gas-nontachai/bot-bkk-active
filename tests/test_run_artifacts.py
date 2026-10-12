import json
import logging
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from bkk_active.logging_setup import LOGGER, configure_logging
from bkk_active.run_artifacts import RunArtifacts


class RunArtifactsTests(unittest.TestCase):
    def test_quiet_terminal_keeps_details_and_traceback_in_file(self):
        old_handlers, old_level, old_propagate = LOGGER.handlers[:], LOGGER.level, LOGGER.propagate
        LOGGER.handlers.clear()
        output = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as parent, patch("sys.stdout", output):
                path = Path(parent) / "run.log"
                configure_logging(path)
                LOGGER.info("ภาพหน้าจอ: example.png")
                LOGGER.info("กำลังค้นหาศูนย์", extra={"terminal_status": True})
                try:
                    raise RuntimeError("test failure")
                except RuntimeError:
                    LOGGER.exception("เกิด error")
                self.assertIn("กำลังค้นหาศูนย์", output.getvalue())
                self.assertNotIn("example.png", output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())
                self.assertIn("example.png", path.read_text())
                self.assertIn("Traceback", path.read_text())
        finally:
            for handler in LOGGER.handlers[:]:
                LOGGER.removeHandler(handler)
                handler.close()
            LOGGER.handlers.extend(old_handlers)
            LOGGER.setLevel(old_level)
            LOGGER.propagate = old_propagate

    @patch("bkk_active.run_artifacts.subprocess.run")
    def test_screenshots_ui_and_index_share_a_run_folder(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b"\x89PNG\r\n\x1a\nimage")
        with tempfile.TemporaryDirectory() as parent:
            artifacts = RunArtifacts(parent)
            root = ET.fromstring('<hierarchy><node text="ค้นหา" /></hierarchy>')
            artifacts.set_step("center-search")
            artifacts.capture("adb", "emulator-test", root)
            artifacts.capture("adb", "emulator-test", root)
            self.assertEqual(run.call_count, 1)
            artifacts.attempt = 2
            artifacts.capture("adb", "emulator-test", root)
            self.assertEqual(run.call_count, 2)
            events = [json.loads(line) for line in artifacts.index_file.read_text().splitlines()]
            self.assertEqual([event["attempt"] for event in events], [1, 2])
            for event in events:
                self.assertTrue((artifacts.folder / event["screenshot"]).is_file())
                self.assertEqual(ET.parse(artifacts.folder / event["ui"]).getroot()[0].get("text"), "ค้นหา")
                self.assertTrue(event["timestamp"].endswith("+07:00"))

    def test_log_file_keeps_timestamp_and_thai_action(self):
        old_handlers, old_level, old_propagate = LOGGER.handlers[:], LOGGER.level, LOGGER.propagate
        LOGGER.handlers.clear()
        try:
            with tempfile.TemporaryDirectory() as parent:
                path = Path(parent) / "run.log"
                configure_logging(path)
                LOGGER.info("กดจองคิว")
                self.assertIn("+0700 [INFO] กดจองคิว", path.read_text(encoding="utf-8"))
        finally:
            for handler in LOGGER.handlers[:]:
                LOGGER.removeHandler(handler)
                handler.close()
            LOGGER.handlers.extend(old_handlers)
            LOGGER.setLevel(old_level)
            LOGGER.propagate = old_propagate

    @patch("bkk_active.run_artifacts.subprocess.run")
    def test_invalid_screenshot_is_not_indexed_as_success(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b"not-a-png")
        with tempfile.TemporaryDirectory() as parent:
            artifacts = RunArtifacts(parent)
            with self.assertRaises(RuntimeError):
                artifacts.capture("adb", "test", ET.Element("hierarchy"))
            self.assertFalse(artifacts.index_file.exists())
            self.assertEqual(list(artifacts.screenshots.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
