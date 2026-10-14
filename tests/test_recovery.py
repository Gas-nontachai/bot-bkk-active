from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from bkk_active.config import PACKAGE
from bkk_active.device import AndroidDevice
from bkk_active.errors import AppBusy, SlotSelectionBusy
from bkk_active.flows.submit import select_slot
from bkk_active.middleware import CaptureLoggingMiddleware
from bkk_active.runner import run_flow
from bkk_active.ui import is_busy_screen


def busy_screen():
    root = ET.Element("hierarchy")
    ET.SubElement(root, "node", package=PACKAGE, text=(
        "กรุณารอสักครู่\nโปรดอย่าออกจากหน้านี้\n"
        "หากมีผู้ใช้บริการพร้อมกันจำนวนมาก\nอาจใช้เวลา 5-10 นาที"))
    return root


class RecoveryTests(unittest.TestCase):
    def test_busy_opening_confirmation_is_retryable_before_submit(self):
        device = Mock()
        device.wait_for.side_effect = AppBusy('busy')
        config = SimpleNamespace(date=date(2026, 10, 14))
        with self.assertRaises(SlotSelectionBusy):
            select_slot(device, config, 1, (object(), '11:00–12:00'))
        device.run.assert_not_called()
        device.screenshot_raw.assert_not_called()

    def test_busy_before_confirmation_resumes_the_same_court(self):
        config = SimpleNamespace(serial='test', date=date(2026, 10, 14))
        opened = []
        slot = (object(), '11:00–12:00')
        with ExitStack() as stack:
            device, launch, _, submit = self.setup_flow(stack, config)
            stack.enter_context(patch('bkk_active.flows.courts.open_court',
                                     side_effect=lambda device, booking, number, court: opened.append(number)))
            stack.enter_context(patch('bkk_active.flows.courts.find_available_slot', return_value=slot))
            submit.side_effect = [SlotSelectionBusy('before Submit'), None]
            self.assertEqual(run_flow(config), 'completed')
            self.assertEqual(opened, [1, 1])
            device.run.assert_called_once_with('shell', 'am', 'force-stop', PACKAGE)
            self.assertEqual(launch.call_count, 2)

    def test_blocking_message_is_distinct_from_empty_schedule(self):
        self.assertTrue(is_busy_screen(busy_screen()))
        for text in ("ไม่พบข้อมูล", "กรุณารอสักครู่", "เลือกจองวัน-เวลา"):
            root = ET.Element("hierarchy")
            ET.SubElement(root, "node", package=PACKAGE, text=text)
            self.assertFalse(is_busy_screen(root))

    def test_busy_read_is_recorded_and_snapshot_can_still_be_captured(self):
        device = object.__new__(AndroidDevice)
        device.middleware = CaptureLoggingMiddleware(Mock(capture_mode="fast"))
        device.ui_backend = "uiautomator"
        root = busy_screen()
        device.read_ui_legacy = Mock(return_value=root)
        with self.assertRaises(AppBusy):
            device.read_ui()
        device.middleware.artifacts.record_ui.assert_called_once_with(root, "start")
        with self.assertRaises(AppBusy):
            device.read_ui(cached=True)
        device.middleware.reading_snapshot = True
        self.assertIs(device.read_ui(), root)

    def test_busy_initial_root_cannot_be_accepted_as_empty_schedule(self):
        device = object.__new__(AndroidDevice)
        device.dismiss_dialog = Mock()
        with self.assertRaises(AppBusy):
            device.wait_for(lambda ui: True, "loaded", initial=busy_screen())
        device.dismiss_dialog.assert_not_called()

    def setup_flow(self, stack, config):
        device = stack.enter_context(patch("bkk_active.runner.AndroidDevice")).return_value
        launch = stack.enter_context(patch("bkk_active.runner.launch"))
        stack.enter_context(patch("bkk_active.runner.open_booking"))
        stack.enter_context(patch("bkk_active.runner.search_center", return_value=True))
        stack.enter_context(patch("bkk_active.runner.select_activity", return_value=True))
        stack.enter_context(patch("bkk_active.flows.courts.locate_court", return_value=object()))
        back = stack.enter_context(patch("bkk_active.flows.courts.back_to_courts"))
        submit = stack.enter_context(patch("bkk_active.runner.select_slot"))
        return device, launch, back, submit

    def test_restart_resumes_failed_court_and_selects_first_free_slot(self):
        config = SimpleNamespace(serial="test", date=date(2026, 10, 14))
        opened = []
        later = (object(), "20:00–21:00")

        def open_court(device, booking, number, court):
            opened.append(number)
            if opened == [1, 2, 3]:
                raise AppBusy("busy")
            return number

        def find_slot(device, booking, root, exact_interval=None):
            return later if root == 3 else None

        with ExitStack() as stack:
            device, launch, _, submit = self.setup_flow(stack, config)
            stack.enter_context(patch("bkk_active.flows.courts.open_court", side_effect=open_court))
            stack.enter_context(patch("bkk_active.flows.courts.find_available_slot", side_effect=find_slot))
            self.assertEqual(run_flow(config), "completed")
            self.assertEqual(opened, [1, 2, 3, 3])
            device.run.assert_called_once_with("shell", "am", "force-stop", PACKAGE)
            self.assertEqual(launch.call_count, 2)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[2:], (3, later))

    def test_busy_return_navigation_resumes_next_court(self):
        config = SimpleNamespace(serial="test", date=date(2026, 10, 14))
        opened = []
        with ExitStack() as stack:
            _, _, back, _ = self.setup_flow(stack, config)
            back.side_effect = [AppBusy("busy")] + [None] * 6
            stack.enter_context(patch("bkk_active.flows.courts.open_court",
                                     side_effect=lambda device, booking, number, court: opened.append(number)))
            stack.enter_context(patch("bkk_active.flows.courts.find_available_slot", return_value=None))
            self.assertEqual(run_flow(config), "no_available_slot")
            self.assertEqual(opened, list(range(1, 8)))

    def test_busy_initial_navigation_can_restart(self):
        config = SimpleNamespace(serial="test", date=date(2026, 10, 14))
        with ExitStack() as stack:
            device, _, _, submit = self.setup_flow(stack, config)
            stack.enter_context(patch("bkk_active.runner.enter_courts", side_effect=[AppBusy("busy"), None]))
            stack.enter_context(patch("bkk_active.runner.choose_court_slot", return_value=None))
            self.assertEqual(run_flow(config), "no_available_slot")
            device.run.assert_called_once_with("shell", "am", "force-stop", PACKAGE)
            submit.assert_not_called()

    def test_tomorrow_recovery_keeps_date_and_stops_at_restart_limit(self):
        today, tomorrow = date(2026, 10, 14), date(2026, 10, 15)
        config = SimpleNamespace(serial="test", date=today, booking_dates=(today, tomorrow))
        opened = []

        def open_court(device, booking, number, court):
            opened.append((booking.date, number))
            if booking.date == tomorrow:
                raise AppBusy("busy")

        with ExitStack() as stack:
            device, launch, _, submit = self.setup_flow(stack, config)
            stack.enter_context(patch("bkk_active.flows.courts.open_court", side_effect=open_court))
            stack.enter_context(patch("bkk_active.flows.courts.find_available_slot", return_value=None))
            with self.assertRaisesRegex(RuntimeError, "ครบ 3 ครั้ง"):
                run_flow(config)
            self.assertEqual(opened, [(today, n) for n in range(1, 8)] + [(tomorrow, 1)] * 4)
            self.assertEqual(device.run.call_count, 3)
            self.assertEqual(launch.call_args.args[1].date, tomorrow)
            submit.assert_not_called()

    def test_busy_after_submit_does_not_restart_or_resubmit(self):
        config = SimpleNamespace(serial="test", date=date(2026, 10, 14))
        with ExitStack() as stack:
            device, launch, _, submit = self.setup_flow(stack, config)
            stack.enter_context(patch("bkk_active.runner.choose_court_slot",
                                     return_value=(1, (object(), "18:00–19:00"))))
            submit.side_effect = AppBusy("busy after submit")
            with self.assertRaises(AppBusy):
                run_flow(config)
            launch.assert_called_once()
            device.run.assert_not_called()
            submit.assert_called_once()
