import unittest
from datetime import date
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bkk_active.runner import run_flow
from bkk_active.config import PACKAGE
from bkk_active.flows.courts import back_to_courts, choose_court_slot


def screen(title, arrow=True):
    root = ET.Element("hierarchy")
    ET.SubElement(root, "node", package=PACKAGE, text=title)
    if arrow:
        button = ET.SubElement(root, "node", {
            "package": PACKAGE, "content-desc": "\uf12f", "clickable": "true",
            "enabled": "true", "bounds": "[54,269][133,347]",
        })
    else:
        button = None
    return root, button


class RunnerTests(unittest.TestCase):
    def test_back_to_courts_taps_app_arrow_and_waits_for_court_list(self):
        root, button = screen("เลือกจองวัน-เวลา")
        courts, _ = screen("แบดมินตัน สนาม 1", arrow=False)
        device = Mock()
        device.read_ui.return_value = root

        def wait_for(predicate, message):
            self.assertFalse(predicate(root))
            self.assertTrue(predicate(courts))
            return courts

        device.wait_for.side_effect = wait_for
        back_to_courts(device, SimpleNamespace())
        device.tap.assert_called_once_with(button)
        device.run.assert_not_called()
        device.wait_for.assert_called_once()

    def test_back_to_courts_does_not_navigate_past_court_list(self):
        root, _ = screen("แบดมินตัน สนาม 1")
        device = Mock()
        device.read_ui.return_value = root
        back_to_courts(device, SimpleNamespace())
        device.tap.assert_not_called()
        device.run.assert_not_called()

    def test_back_to_courts_stops_if_arrow_missing_or_wrong_page(self):
        for title, arrow in (("เลือกจองวัน-เวลา", False), ("เลือกกิจกรรม", True)):
            with self.subTest(title=title):
                device = Mock()
                device.read_ui.return_value = screen(title, arrow)[0]
                with self.assertRaises(RuntimeError):
                    back_to_courts(device, SimpleNamespace())
                device.tap.assert_not_called()
                device.run.assert_not_called()
                device.wait_for.assert_not_called()

    def test_blocked_center_does_not_select_or_submit(self):
        config = SimpleNamespace(serial="emulator-test", date=date(2026, 10, 14))
        with patch("bkk_active.runner.AndroidDevice"), \
                patch("bkk_active.runner.launch"), \
                patch("bkk_active.runner.open_booking"), \
                patch("bkk_active.runner.search_center", return_value=None), \
                patch("bkk_active.runner.select_activity") as activity, \
                patch("bkk_active.runner.select_slot") as submit:
            run_flow(config)
        activity.assert_not_called()
        submit.assert_not_called()

    def test_selected_slot_is_passed_to_submit_once(self):
        config = SimpleNamespace(serial="emulator-test", date=date(2026, 10, 14))
        slot = (object(), "18:00–19:00")
        with patch("bkk_active.runner.AndroidDevice") as device_class, \
                patch("bkk_active.runner.launch"), \
                patch("bkk_active.runner.open_booking"), \
                patch("bkk_active.runner.search_center", return_value=True), \
                patch("bkk_active.runner.select_activity", return_value=True), \
                patch("bkk_active.runner.choose_court_slot", return_value=(3, slot)), \
                patch("bkk_active.runner.select_slot") as submit:
            run_flow(config)
        submit.assert_called_once()
        submitted_device, booking, number, selected = submit.call_args.args
        self.assertIs(submitted_device, device_class.return_value)
        self.assertEqual((booking.date, number, selected), (config.date, 3, slot))

    def test_both_days_falls_back_only_when_today_has_no_slot(self):
        today, tomorrow = date(2026, 10, 14), date(2026, 10, 15)
        config = SimpleNamespace(serial="test", date=today, booking_dates=(today, tomorrow))
        slot = (object(), "18:00–19:00")
        cases = (([None, (3, slot)], "completed", [today, tomorrow], tomorrow),
                 ([(3, slot)], "completed", [today], today),
                 ([None, None], "no_available_slot", [today, tomorrow], None))
        for choices, expected, dates, submitted_date in cases:
            with self.subTest(choices=choices), \
                    patch("bkk_active.runner.AndroidDevice") as device, \
                    patch("bkk_active.runner.launch"), \
                    patch("bkk_active.runner.open_booking"), \
                    patch("bkk_active.runner.search_center", return_value=True), \
                    patch("bkk_active.runner.select_activity", return_value=True), \
                    patch("bkk_active.runner.choose_court_slot", side_effect=choices) as choose, \
                    patch("bkk_active.runner.select_slot") as submit:
                self.assertEqual(run_flow(config), expected)
                self.assertEqual([call.args[1].date for call in choose.call_args_list], dates)
                if submitted_date is None:
                    submit.assert_not_called()
                else:
                    submit.assert_called_once()
                    self.assertEqual(submit.call_args.args[1].date, submitted_date)
                device.assert_called_once()
                self.assertEqual(config.date, today)

    def test_booking_error_does_not_try_another_day(self):
        config = SimpleNamespace(serial="test", date=date(2026, 10, 14),
                                 booking_dates=(date(2026, 10, 14), date(2026, 10, 15)))
        with patch("bkk_active.runner.AndroidDevice"), \
                patch("bkk_active.runner.launch"), \
                patch("bkk_active.runner.open_booking"), \
                patch("bkk_active.runner.search_center", return_value=True), \
                patch("bkk_active.runner.select_activity", return_value=True), \
                patch("bkk_active.runner.choose_court_slot", return_value=(1, (object(), "18:00–19:00"))) as choose, \
                patch("bkk_active.runner.select_slot", side_effect=RuntimeError("Submit result unclear")) as submit:
            with self.assertRaises(RuntimeError):
                run_flow(config)
        choose.assert_called_once()
        submit.assert_called_once()

    def test_later_court_at_18_wins_over_first_court_at_20(self):
        device = Mock()
        config = SimpleNamespace()
        later = (object(), "20:00–21:00")
        preferred = (object(), "18:00–19:00")
        with patch("bkk_active.flows.courts.locate_court", return_value=object()), \
                patch("bkk_active.flows.courts.open_court"), \
                patch("bkk_active.flows.courts.find_evening_slot", side_effect=[later, preferred]), \
                patch("bkk_active.flows.courts.back_to_courts") as back:
            choice = choose_court_slot(device, config)
        self.assertEqual(choice, (2, preferred))
        self.assertEqual(back.call_count, 1)

    def test_app_slot_starting_at_18_is_selected_without_fixed_end_time(self):
        device = Mock()
        config = SimpleNamespace()
        slot = (object(), "18:00–19:10")
        with patch("bkk_active.flows.courts.locate_court", return_value=object()), \
                patch("bkk_active.flows.courts.open_court"), \
                patch("bkk_active.flows.courts.find_evening_slot", return_value=slot) as find, \
                patch("bkk_active.flows.courts.back_to_courts") as back:
            choice = choose_court_slot(device, config)
        self.assertEqual(choice, (1, slot))
        find.assert_called_once()
        back.assert_not_called()


if __name__ == "__main__":
    unittest.main()
