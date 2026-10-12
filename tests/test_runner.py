import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bkk_active.runner import run_flow
from bkk_active.flows.courts import choose_court_slot


class RunnerTests(unittest.TestCase):
    def test_blocked_center_does_not_select_or_submit(self):
        config = SimpleNamespace(serial="emulator-test")
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
        config = SimpleNamespace(serial="emulator-test")
        slot = (object(), "18:00–19:00")
        with patch("bkk_active.runner.AndroidDevice") as device_class, \
                patch("bkk_active.runner.launch"), \
                patch("bkk_active.runner.open_booking"), \
                patch("bkk_active.runner.search_center", return_value=True), \
                patch("bkk_active.runner.select_activity", return_value=True), \
                patch("bkk_active.runner.choose_court_slot", return_value=(3, slot)), \
                patch("bkk_active.runner.select_slot") as submit:
            run_flow(config)
        submit.assert_called_once_with(device_class.return_value, config, 3, slot)

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
