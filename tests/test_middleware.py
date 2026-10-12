import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from bkk_active.errors import CenterNotFound
from bkk_active.middleware import CaptureLoggingMiddleware, flow_step


class FakeDevice:
    def __init__(self):
        self.adb = "adb"
        self.serial = "test"
        self.artifacts = Mock()
        self.middleware = CaptureLoggingMiddleware(self.artifacts)
        self.root = ET.Element("hierarchy")

    def read_ui(self):
        self.middleware.observe_ui(self, self.root)
        return self.root


class MiddlewareTests(unittest.TestCase):
    def test_wrapped_step_preserves_result_and_executes_once(self):
        device = FakeDevice()
        action = Mock(return_value="result")
        wrapped = flow_step("submit")(action)
        self.assertEqual(wrapped(device), "result")
        action.assert_called_once_with(device)
        labels = [call.kwargs["label"] for call in device.artifacts.capture.call_args_list]
        self.assertEqual(labels, ["submit-before", "submit-after"])
        self.assertEqual(device.middleware.current_step, "start")

    def test_original_exception_is_preserved_even_if_capture_fails(self):
        device = FakeDevice()
        device.artifacts.capture.side_effect = RuntimeError("screenshot failed")
        error = RuntimeError("submit result unknown")
        action = Mock(side_effect=error)
        with self.assertLogs("bkk-active", level="WARNING"):
            with self.assertRaises(RuntimeError) as caught:
                flow_step("submit")(action)(device)
        self.assertIs(caught.exception, error)
        action.assert_called_once_with(device)
        self.assertEqual(device.middleware.current_step, "start")

    def test_nested_steps_restore_parent_and_capture_error_once(self):
        device = FakeDevice()
        @flow_step("review")
        def review(device):
            raise RuntimeError("review rejected")
        @flow_step("booking")
        def booking(device):
            review(device)
        with self.assertLogs("bkk-active", level="ERROR") as logs:
            with self.assertRaises(RuntimeError):
                booking(device)
        self.assertEqual(len(logs.output), 1)
        labels = [call.kwargs["label"] for call in device.artifacts.capture.call_args_list]
        self.assertIn("booking/review-error", labels)
        self.assertNotIn("booking-error", labels)
        self.assertEqual(device.middleware.current_step, "start")

    def test_center_not_found_still_reaches_retry_handler(self):
        device = FakeDevice()
        action = Mock(side_effect=CenterNotFound("missing"))
        with self.assertRaises(CenterNotFound):
            flow_step("center-search")(action)(device)
        action.assert_called_once_with(device)


if __name__ == "__main__":
    unittest.main()
