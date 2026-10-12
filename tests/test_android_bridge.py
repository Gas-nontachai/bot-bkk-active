import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from bkk_active.android_bridge import AndroidBridge, parse_dump
from bkk_active.device import AndroidDevice
from bkk_active.middleware import CaptureLoggingMiddleware


class AndroidBridgeTests(unittest.TestCase):
    def test_dump_preserves_thai_labels_and_clickable_bounds(self):
        xml = ('<hierarchy><node package="go.th.bangkok.cstd" text="จองคิว" '
               'clickable="true" enabled="true" bounds="[10,20][100,200]"/></hierarchy>')
        encoded = base64.b64encode(xml.encode()).decode()
        root = parse_dump(f"INSTRUMENTATION_RESULT: xml64={encoded}\nINSTRUMENTATION_CODE: -1\n")
        self.assertEqual(root[0].get("text"), "จองคิว")
        self.assertEqual(root[0].get("bounds"), "[10,20][100,200]")

    def test_bad_or_empty_dump_is_rejected(self):
        for xml in ("<hierarchy/>", "<unexpected/>", "not xml"):
            encoded = base64.b64encode(xml.encode()).decode()
            with self.assertRaises(RuntimeError):
                parse_dump(f"INSTRUMENTATION_RESULT: xml64={encoded}\nINSTRUMENTATION_CODE: -1")
        with self.assertRaises(RuntimeError):
            parse_dump("INSTRUMENTATION_RESULT: error=failed\nINSTRUMENTATION_CODE: 0")

    def test_bridge_failure_falls_back_without_repeating_actions(self):
        device = object.__new__(AndroidDevice)
        device.middleware = CaptureLoggingMiddleware()
        device.ui_backend = "bridge"
        device.bridge_failed = False
        device.bridge = Mock()
        device.bridge.read_ui.side_effect = RuntimeError("bridge unavailable")
        device.cached_root, device.cache_valid = None, False
        root = ET.fromstring('<hierarchy><node text="จองคิว"/></hierarchy>')
        device.read_ui_legacy = Mock(return_value=root)
        with self.assertLogs("bkk-active", level="WARNING"):
            self.assertIs(device.read_ui(), root)
        self.assertIs(device.read_ui(), root)
        device.bridge.read_ui.assert_called_once()
        self.assertEqual(device.read_ui_legacy.call_count, 2)

    def test_matching_helper_version_is_not_reinstalled_on_every_device(self):
        with tempfile.TemporaryDirectory() as parent, \
                patch("bkk_active.android_bridge.PROJECT_ROOT", Path(parent)), \
                patch("bkk_active.android_bridge._prepared", set()):
            directory = Path(parent) / "tools/android-text-input"
            directory.mkdir(parents=True)
            for name in ("TextInput.java", "AndroidManifest.xml", "build.sh"):
                (directory / name).write_text("source")
            (directory / ".build").mkdir()
            (directory / ".build/text-input.apk").write_bytes(b"apk")
            device = Mock(adb="adb", serial="test")
            device.run.return_value = "INSTRUMENTATION_RESULT: result=BRIDGE_VERSION_3"
            AndroidBridge(device).prepare()
            AndroidBridge(device).prepare()
            device.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
