import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from bkk_active.device import AndroidDevice
from bkk_active.metrics import RunMetrics
from bkk_active.middleware import CaptureLoggingMiddleware, flow_step
from bkk_active.run_artifacts import RunArtifacts


class PerformanceTests(unittest.TestCase):
    def test_fast_search_result_capture_reuses_current_valid_xml(self):
        artifacts = Mock(capture_mode="fast")
        device = Mock(adb="adb", serial="test", cache_valid=True)
        device.middleware = CaptureLoggingMiddleware(artifacts)
        root = ET.Element("hierarchy")
        @flow_step("center-search")
        def search(device):
            device.middleware.last_root = root
            return True
        self.assertTrue(search(device))
        device.read_ui.assert_not_called()
        artifacts.capture.assert_called_once_with("adb", "test", root,
                                                  label="center-search-after", force=True)

    def test_loaded_screen_can_satisfy_wait_without_another_dump(self):
        device = object.__new__(AndroidDevice)
        device.read_ui = Mock()
        device.dismiss_dialog = Mock(return_value=False)
        root = ET.Element("hierarchy")
        result = device.wait_for(lambda ui: ui is root, "not ready", initial=root)
        self.assertIs(result, root)
        device.read_ui.assert_not_called()

    def test_fast_step_does_not_add_ui_reads_or_png_captures(self):
        artifacts = Mock(capture_mode="fast")
        device = Mock()
        device.middleware = CaptureLoggingMiddleware(artifacts)
        action = Mock(return_value=42)
        self.assertEqual(flow_step("booking")(action)(device), 42)
        device.read_ui.assert_not_called()
        artifacts.capture.assert_not_called()
        action.assert_called_once_with(device)
        artifacts.metrics.record_step.assert_called_once()

    def test_fast_mode_keeps_xml_and_submit_capture(self):
        artifacts = Mock(capture_mode="fast")
        device = Mock(adb="adb", serial="test")
        middleware = CaptureLoggingMiddleware(artifacts)
        root = ET.Element("hierarchy")
        middleware.observe_ui(device, root)
        artifacts.record_ui.assert_called_once_with(root, "start")
        middleware.before_command(device, ("shell", "input", "tap", "100", "200"))
        artifacts.capture.assert_not_called()
        middleware.current_step = "submit-booking"
        middleware.before_command(device, ("shell", "input", "tap", "100", "200"))
        artifacts.capture.assert_called_once()

    @patch("bkk_active.device.subprocess.run")
    def test_cache_reuses_snapshot_until_navigation_and_polling_stays_fresh(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '<hierarchy/>', '')
        device = object.__new__(AndroidDevice)
        device.adb, device.serial = "adb", "test"
        device.middleware = CaptureLoggingMiddleware()
        device.cached_root, device.cache_valid = None, False
        first = device.read_ui()
        self.assertIs(device.read_ui(cached=True), first)
        self.assertEqual(run.call_count, 1)
        device.read_ui()
        self.assertEqual(run.call_count, 2)
        device.run("shell", "input", "tap", "100", "200")
        device.read_ui(cached=True)
        self.assertEqual(run.call_count, 4)

    def test_summary_contains_counts_outcome_and_step_times(self):
        metrics = RunMetrics()
        metrics.record("ui_read", 2.1)
        metrics.record("tap", 0.03)
        metrics.record_step("booking", 3.2, "completed", 1)
        with tempfile.TemporaryDirectory() as parent:
            folder = Path(parent)
            report = metrics.finish(folder, outcome="center_not_found", attempts=4, capture_mode="fast")
            saved = json.loads((folder / "summary.json").read_text())
            self.assertEqual(saved, report)
            self.assertEqual(saved["counts"]["ui_read"], 1)
            self.assertEqual(saved["operation_seconds"]["tap"], 0.03)
            self.assertEqual(saved["outcome"], "center_not_found")
            self.assertEqual(saved["attempts"], 4)
            self.assertEqual(saved["steps"][0]["name"], "booking")
