import unittest
import struct
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from datetime import date

from bkk_active.config import PACKAGE
from bkk_active.errors import CenterNotFound
from bkk_active.ui import (activity_button, confirmation_matches, court_button,
                           is_court_list, is_review_page, selected_date_matches)
from bkk_active.policy import available_slot, ranked_courts
from bkk_active.retry import retry_missing_center
from bkk_active.vision import orange_submit_center
from bkk_active.flows.schedule import choose_date


def node(**attributes):
    defaults = {"package": PACKAGE, "enabled": "true", "bounds": "[200,500][1000,700]"}
    defaults.update(attributes)
    return ET.Element("node", defaults)


def schedule(*entries):
    root = node(bounds="[0,0][1080,2400]", clickable="true")
    for index, (interval, status) in enumerate(entries):
        card = node(bounds=f"[200,{500 + index * 220}][1000,{700 + index * 220}]", clickable="true")
        card.append(node(text=interval))
        card.append(node(text=status))
        root.append(card)
    return root


class BookingSelectionTests(unittest.TestCase):
    def test_choose_tomorrow_taps_day_and_waits_for_selected_date(self):
        root = node()
        tomorrow = node(clickable="true", **{"content-desc": "15, พฤ."})
        tomorrow.append(node(text="15"))
        root.extend((tomorrow, node(text="14 ตุลาคม")))
        updated = node()
        updated.append(node(text="15 ตุลาคม"))
        device = Mock()

        def wait_for(predicate, message):
            self.assertFalse(predicate(root))
            self.assertTrue(predicate(updated))
            return updated

        device.wait_for.side_effect = wait_for
        self.assertIs(choose_date(device, type("Config", (), {"date": date(2026, 10, 15)})(), root), updated)
        device.tap.assert_called_once_with(tomorrow)

    def test_choose_today_keeps_already_selected_date(self):
        root = node()
        root.append(node(text="14 ตุลาคม"))
        device = Mock()
        self.assertIs(choose_date(device, type("Config", (), {"date": date(2026, 10, 14)})(), root), root)
        device.tap.assert_not_called()
        device.wait_for.assert_not_called()

    def test_court_cards_support_both_names_and_exact_numbers(self):
        for name in ("แบดมินตัน สนาม", "สนามแบดมินตัน"):
            with self.subTest(name=name):
                root = node()
                wrong = node(text=f"{name} 10", clickable="true")
                card = node(clickable="true")
                card.append(node(text=f"{name} 1"))
                root.extend((wrong, card))
                self.assertTrue(is_court_list(root))
                self.assertIs(court_button(root, 1), card)
                self.assertIsNone(court_button(root, 2))
                root.append(node(text="เลือกจองวัน-เวลา"))
                self.assertFalse(is_court_list(root))

    def test_activity_and_other_court_numbers_are_not_court_list(self):
        for label in ("สนามแบดมินตัน", "แบดมินตัน สนาม 10", "สนามแบดมินตัน 10"):
            root = node()
            root.append(node(text=label, clickable="true"))
            self.assertFalse(is_court_list(root))
            self.assertIsNone(court_button(root, 1))

    def test_confirmation_accepts_current_court_name(self):
        root = node()
        for text in ("Confirm Booking", "14/10/2569", "18:00 น.", "แบดมินตัน สนาม 2"):
            root.append(node(text=text))
        self.assertTrue(confirmation_matches(root, date(2026, 10, 14), 2, "18:00–19:00"))
        self.assertFalse(confirmation_matches(root, date(2026, 10, 14), 1, "18:00–19:00"))

    def test_slots_can_start_at_nonzero_minutes(self):
        root = schedule(("19:00 - 20:00", "ว่าง"), ("18:20 - 19:20", "ว่าง"))
        self.assertEqual(available_slot(root)[1], "18:20–19:20")

    def test_court_ranking_compares_minutes_not_only_hours(self):
        self.assertEqual(ranked_courts([(1, "18:40–19:40"), (2, "18:20–19:20")])[0],
                         (2, "18:20–19:20"))

    @patch("bkk_active.retry.time.sleep")
    def test_missing_center_retries_three_times_after_first_attempt(self, sleep):
        calls = []
        def action():
            calls.append(1)
            raise CenterNotFound("ไม่มีศูนย์")
        retry_missing_center(action)
        self.assertEqual(len(calls), 4)
        self.assertEqual(sleep.call_count, 3)

    @patch("bkk_active.retry.time.sleep")
    def test_retry_stops_when_flow_finishes(self, sleep):
        calls = []
        def action():
            calls.append(1)
            if len(calls) < 3:
                raise CenterNotFound("ไม่มีศูนย์")
            return "finished"
        self.assertEqual(retry_missing_center(action), "finished")
        self.assertEqual(len(calls), 3)

    def test_submit_or_other_errors_do_not_restart_flow(self):
        calls = []
        def action():
            calls.append(1)
            raise RuntimeError("ผล Submit ไม่ชัดเจน")
        with self.assertRaises(RuntimeError):
            retry_missing_center(action)
        self.assertEqual(len(calls), 1)

    def test_review_screen_recognized_in_both_languages(self):
        for title in ("Booking Review", "ประเมินการจอง", "รีวิวการจอง"):
            root = node()
            root.append(node(text=title))
            self.assertTrue(is_review_page(root))
        root = node()
        root.append(node(text="Confirm Booking"))
        root.append(node(text="Submit"))
        self.assertFalse(is_review_page(root))

    def test_confirmation_requires_correct_court_date_and_time(self):
        root = node()
        for text in ("Confirm Booking", "13/10/2569", "18:00 น.", "สนามแบดมินตัน 2"):
            root.append(node(text=text))
        self.assertTrue(confirmation_matches(root, date(2026, 10, 13), 2, "18:00–19:00"))
        self.assertFalse(confirmation_matches(root, date(2026, 10, 13), 1, "18:00–19:00"))
        self.assertFalse(confirmation_matches(root, date(2026, 10, 12), 2, "18:00–19:00"))
        self.assertFalse(confirmation_matches(root, date(2026, 10, 13), 2, "19:00–20:00"))

    def test_time_selection_screen_is_not_confirmation(self):
        root = node()
        for text in ("เลือกจองวัน-เวลา", "13/10/2569", "18:00", "สนามแบดมินตัน 2"):
            root.append(node(text=text))
        self.assertFalse(confirmation_matches(root, date(2026, 10, 13), 2, "18:00–19:00"))

    @staticmethod
    def screen(buttons):
        width, height = 200, 400
        pixels = bytearray(bytes((255, 255, 255, 255)) * width * height)
        for x1, y1, x2, y2 in buttons:
            for y in range(y1, y2):
                for x in range(x1, x2):
                    position = (y * width + x) * 4
                    pixels[position:position + 4] = bytes((255, 85, 0, 255))
        return struct.pack("<4I", width, height, 1, 1) + pixels

    def test_orange_button_ignores_orange_header_element(self):
        self.assertEqual(orange_submit_center(self.screen([(20, 70, 100, 100),
                                                          (20, 330, 180, 355)])), (100, 342))

    def test_ambiguous_or_missing_orange_button_stops(self):
        for buttons in ([], [(20, 270, 180, 295), (20, 330, 180, 355)]):
            with self.assertRaises(RuntimeError):
                orange_submit_center(self.screen(buttons))

    def test_app_defined_slot_can_last_seventy_minutes(self):
        root = schedule(("19:00 - 20:00", "ว่าง"), ("18:20 - 19:30", "ว่าง"))
        self.assertEqual(available_slot(root)[1], "18:20–19:30")

    def test_global_ranking_prefers_earlier_time_on_later_court(self):
        self.assertEqual(ranked_courts([(1, "20:00–21:00"), (3, "19:00–20:00"),
                                       (7, "18:00–19:00")])[0], (7, "18:00–19:00"))

    def test_recheck_requires_original_time_to_still_be_free(self):
        root = schedule(("19:00 - 20:00", "ไม่ว่าง"), ("20:00 - 21:00", "ว่าง"))
        self.assertIsNone(available_slot(root, exact_interval="19:00–20:00"))

    def test_busy_and_morning_slots_are_not_selected(self):
        root = schedule(("5:00 - 6:00", "ว่าง"), ("18:00 - 19:00", "ไม่ว่าง"),
                        ("19:00 - 20:00", "ว่าง"))
        selected, interval = available_slot(root)
        self.assertIs(selected, root[2])
        self.assertEqual(interval, "19:00–20:00")

    def test_interval_must_fit_fully_within_evening_window(self):
        root = schedule(("17:30 - 18:30", "ว่าง"), ("20:30 - 21:30", "ว่าง"),
                        ("21:00 - 22:00", "ว่าง"))
        self.assertIsNone(available_slot(root))

    def test_end_at_21_is_allowed_and_earliest_free_slot_wins(self):
        root = schedule(("20:00 – 21:00", "ว่าง"), ("18:00 - 19:00", "ว่าง"))
        self.assertEqual(available_slot(root)[1], "18:00–19:00")

    def test_busy_label_in_same_row_overrides_free_label(self):
        root = schedule(("18:00 - 19:00", "ว่าง"))
        root[0].append(node(text="ไม่ว่าง"))
        self.assertIsNone(available_slot(root))

    def test_disabled_card_is_not_selected(self):
        root = schedule(("18:00 - 19:00", "ว่าง"))
        root[0].set("enabled", "false")
        self.assertIsNone(available_slot(root))

    def test_activity_uses_exact_name_not_evening_variant(self):
        root = node()
        root.append(node(text="แบดมินตัน รอบเย็น", clickable="true"))
        card = node(clickable="true")
        card.append(node(text="สนามแบดมินตัน"))
        root.append(card)
        self.assertIs(activity_button(root), card)

    def test_date_requires_day_and_month(self):
        root = node()
        root.append(node(text="อังคาร 13 ตุลาคม"))
        self.assertTrue(selected_date_matches(root, date(2026, 10, 13)))
        self.assertFalse(selected_date_matches(root, date(2026, 10, 12)))
        self.assertFalse(selected_date_matches(root, date(2026, 11, 13)))


if __name__ == "__main__":
    unittest.main()
