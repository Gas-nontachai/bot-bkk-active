from datetime import date, datetime, time, timedelta, timezone
import unittest

from bkk_active.scheduler import BANGKOK, next_run, parse_days, parse_time, run_schedule


class FakeClock:
    def __init__(self, now):
        self.current = now

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.current += timedelta(seconds=seconds)


class SchedulerTests(unittest.TestCase):
    def test_time_and_days_allow_thai_and_english(self):
        self.assertEqual(parse_time("6:00"), time(6))
        self.assertEqual(parse_days("wed,thu,fri"), frozenset((2, 3, 4)))
        self.assertEqual(parse_days("พ.,พฤ.,ศ."), frozenset((2, 3, 4)))
        self.assertEqual(parse_days("วันพุธ,วันศุกร์"), frozenset((2, 4)))
        self.assertEqual(parse_days("ทุกวัน"), frozenset(range(7)))

    def test_invalid_schedule_inputs_rejected(self):
        for value in ("24:00", "06:60", "6", "06:00:00"):
            with self.assertRaises(ValueError):
                parse_time(value)
        for value in ("", "fry", "wed,"):
            with self.assertRaises(ValueError):
                parse_days(value)

    def test_next_slot_uses_bangkok_timezone_and_selected_days(self):
        now = datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)  # Tuesday 06:00 in Bangkok
        self.assertEqual(next_run(now, time(6), parse_days("wed,thu,fri")),
                         datetime(2026, 10, 14, 6, tzinfo=BANGKOK))

    def test_start_after_scheduled_time_waits_until_next_day(self):
        now = datetime(2026, 10, 12, 6, 0, 1, tzinfo=BANGKOK)
        self.assertEqual(next_run(now, time(6), parse_days("all")).date(), date(2026, 10, 13))

    def test_instant_runs_do_not_repeat_same_day_and_pass_fresh_date(self):
        clock = FakeClock(datetime(2026, 10, 12, 6, tzinfo=BANGKOK))
        days = []
        def action(day):
            days.append(day)
            if len(days) == 2:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_schedule(time(6), parse_days("all"), action, now_fn=clock.now, sleep_fn=clock.sleep)
        self.assertEqual(days, [date(2026, 10, 12), date(2026, 10, 13)])

    def test_long_run_does_not_overlap_or_backfill_missed_days(self):
        clock = FakeClock(datetime(2026, 10, 12, 6, tzinfo=BANGKOK))
        days = []
        def action(day):
            days.append(day)
            if len(days) == 1:
                clock.current += timedelta(hours=26)
            else:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_schedule(time(6), parse_days("all"), action, now_fn=clock.now, sleep_fn=clock.sleep)
        self.assertEqual(days, [date(2026, 10, 12), date(2026, 10, 14)])

    def test_failed_run_waits_for_next_day(self):
        clock = FakeClock(datetime(2026, 10, 12, 6, tzinfo=BANGKOK))
        days = []
        def action(day):
            days.append(day)
            if len(days) == 1:
                raise RuntimeError("ADB disconnected")
            raise KeyboardInterrupt
        with self.assertLogs("bkk-active", level="ERROR"):
            with self.assertRaises(KeyboardInterrupt):
                run_schedule(time(6), parse_days("all"), action, now_fn=clock.now, sleep_fn=clock.sleep)
        self.assertEqual(days, [date(2026, 10, 12), date(2026, 10, 13)])

    def test_sleeping_machine_skips_slot_more_than_five_minutes_late(self):
        clock = FakeClock(datetime(2026, 10, 12, 5, 59, tzinfo=BANGKOK))
        first_sleep = True
        def sleep(seconds):
            nonlocal first_sleep
            if first_sleep:
                clock.current += timedelta(hours=2)
                first_sleep = False
            else:
                clock.sleep(seconds)
        days = []
        def action(day):
            days.append(day)
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_schedule(time(6), parse_days("all"), action, now_fn=clock.now, sleep_fn=sleep)
        self.assertEqual(days, [date(2026, 10, 13)])


if __name__ == "__main__":
    unittest.main()
