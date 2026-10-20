from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from bkk_active.config import PACKAGE
from bkk_active.flows.review import submit_review
from bkk_active.ui import review_button


def page(ready=True):
    root = ET.Element("hierarchy")
    ET.SubElement(root, "node", package=PACKAGE, text="รีวิวการจองคิว")
    if ready:
        ET.SubElement(root, "node", package=PACKAGE, text="รีวิว", enabled="true",
                      clickable="true", bounds="[107,2291][976,2400]")
    return root


class ReviewTests(unittest.TestCase):
    def test_waits_for_review_button_at_screen_bottom_and_submits_once(self):
        loading, ready = page(False), page()
        finished = ET.Element("node", package=PACKAGE, text="ขอบคุณ")
        device = Mock()

        def wait(predicate, message, initial):
            self.assertIs(initial, loading)
            self.assertFalse(predicate(loading))
            self.assertTrue(predicate(ready))
            return ready

        device.wait_for.side_effect = wait
        device.read_ui.return_value = finished
        submit_review(device, SimpleNamespace(), loading)
        device.tap.assert_called_once_with(review_button(ready))
        device.screenshot_raw.assert_not_called()

    def test_disabled_button_is_not_ready(self):
        root = page()
        root[-1].set("enabled", "false")
        self.assertIsNone(review_button(root))
        device = Mock()
        device.wait_for.side_effect = RuntimeError("not ready")
        with self.assertRaises(RuntimeError):
            submit_review(device, SimpleNamespace(), root)
        device.tap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
