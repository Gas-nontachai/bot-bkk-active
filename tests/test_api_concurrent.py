from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import threading
import time as clock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import open_booking_api as cli
from bkk_active.api_booking import ApiHttpError, BASE, run_api_booking
from tests import test_api_booking


class ConcurrentApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_api_booking.ApiBookingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.args = self.fixture.args
        self.args.book = True
        self.api = self.fixture.setup_api()
        self.courts = [{"ID": f"court-{n}", "NAME": f"แบดมินตัน สนาม {n}"} for n in range(1, 4)]
        self.api.items.side_effect = [
            [{"ID": "center", "NAME": self.args.center}],
            [{"ID": "activity", "NAME": "สนามแบดมินตัน"}], self.courts,
        ]
        self.posts = []

    def response(self, method, path, payload=None, query=None, **kwargs):
        if path.endswith("/slot"):
            return [self.fixture.slot]
        if path.endswith("/preconfirm"):
            confirmation = deepcopy(self.fixture.confirmation)
            confirmation["booking_detail"]["booking_title"]["value"] = payload["BOOKING_TITLE"]
            return confirmation
        if path == BASE + "/booking":
            self.posts.append(payload)
            return self.fixture.booked
        return {"status": "create success"}

    def run_bot(self):
        return self.fixture.run_with(self.api)

    def test_all_courts_start_together_and_booking_does_not_wait_for_slow_reads(self):
        started = threading.Barrier(3)
        release = threading.Event()
        finished = threading.Event()
        original = self.response

        def request(method, path, *args, **kwargs):
            if path.endswith("/slot"):
                started.wait(timeout=2)
                if "court-1/" not in path:
                    release.wait(timeout=2)
                    finished.set()
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        try:
            before = clock.perf_counter()
            self.assertEqual(self.run_bot()["outcome"], "booked")
            self.assertLess(clock.perf_counter() - before, 1)
            self.assertFalse(finished.is_set())
            self.assertEqual(len(self.posts), 1)
        finally:
            release.set()
            finished.wait(timeout=2)

    def test_definitive_rejection_attempts_next_court_once(self):
        original = self.response

        def request(method, path, *args, **kwargs):
            if path == BASE + "/booking" and not self.posts:
                self.posts.append(args[0])
                return {"is_book": False}
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        self.assertEqual(self.run_bot()["outcome"], "booked")
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(len({post["BOOKING_TITLE"] for post in self.posts}), 2)

    def test_two_callers_same_account_never_submit_twice(self):
        self.api.request.side_effect = self.response
        with patch("bkk_active.api_booking.load_session", return_value=self.fixture.sample_session()), \
                patch("bkk_active.api_booking.BookingApi", return_value=self.api), \
                ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run_api_booking, [self.args, self.args]))
        self.assertCountEqual([result["outcome"] for result in results], ["booked", "already_booked"])
        self.assertEqual(len(self.posts), 1)

    def test_timeout_reconciles_success_before_any_other_booking(self):
        self.api.bookings.side_effect = [[], [self.fixture.booked["booking_data"]]]
        original = self.response

        def request(method, path, *args, **kwargs):
            if path == BASE + "/booking":
                self.posts.append(args[0])
                raise TimeoutError()
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        self.assertEqual(self.run_bot()["outcome"], "booked")
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.api.bookings.call_count, 2)
        self.assertFalse(Path(self.args.session + ".pending-booking.json").exists())

    def test_empty_reconciliation_is_unknown_and_blocks_other_courts(self):
        original = self.response

        def request(method, path, *args, **kwargs):
            if path == BASE + "/booking":
                self.posts.append(args[0])
                raise TimeoutError()
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        with self.assertRaisesRegex(RuntimeError, "ห้ามส่งซ้ำ"):
            self.run_bot()
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.api.bookings.call_count, 2)
        self.assertTrue(Path(self.args.session + ".pending-booking.json").exists())

    def test_restart_reconciles_pending_success_without_post(self):
        Path(self.args.session + ".pending-booking.json").write_text(json.dumps({
            "date": self.args.date.isoformat(), "court_id": "court-1", "slot_id": "slot-7",
        }))
        self.api.bookings.return_value = [self.fixture.booked["booking_data"]]
        self.assertEqual(self.run_bot()["outcome"], "already_booked")
        self.api.request.assert_not_called()

    def test_existing_booking_other_court_and_time_still_blocks_date(self):
        self.api.bookings.return_value = [{
            "BOOKING_DATE": self.args.date.isoformat(), "BOOKING_STATUS": "CONFIRMED",
            "SLOT": {"ITEM_ID": "court-99", "START_TIME": "20:00:00", "END_TIME": "21:00:00"},
        }]
        self.assertEqual(self.run_bot()["outcome"], "already_booked")
        self.api.request.assert_not_called()

    def test_full_slots_log_thai_summary_and_outside_window_availability(self):
        full = {**self.fixture.slot, "IS_FULL": True, "REMAINING": 0}
        early = {**self.fixture.slot, "ID": "early", "START_TIME": "05:00:00", "END_TIME": "06:00:00"}
        self.api.request.return_value = [full, early]
        with self.assertLogs("bkk-active", level="INFO") as logs:
            self.assertEqual(self.run_bot()["outcome"], "no_available_slot")
        output = "\n".join(logs.output)
        self.assertIn("API แจ้งเต็ม 1 ช่อง", output)
        self.assertIn("เวลาว่างทั้งหมด: 05:00–06:00", output)
        self.assertIn("จองไม่ได้ — ไม่พบช่องว่างที่ผ่านเงื่อนไข", output)
        self.assertEqual(output.count("API แจ้งเต็ม"), len(self.courts))
        from bkk_active.logging_setup import StatusFilter
        terminal = "\n".join(record.getMessage() for record in logs.records if StatusFilter().filter(record))
        self.assertIn("เริ่มจองสนามสำหรับวันที่", terminal)
        self.assertIn("พบศูนย์แล้ว", terminal)
        self.assertIn("พบสนามแบดมินตัน 3 สนาม", terminal)
        self.assertIn("จบรอบ ใช้เวลา", terminal)
        self.assertNotIn("API performance", terminal)
        self.assertNotIn("Center search", terminal)
        self.assertIn("API performance", output)
        self.assertFalse(self.posts)

    def test_no_availability_and_preview_never_post(self):
        for preview, slots, expected in ((False, [], "no_available_slot"),
                                         (True, [self.fixture.slot], "available")):
            self.setUp()
            self.args.book = not preview
            self.api.request.return_value = slots
            self.assertEqual(self.run_bot()["outcome"], expected)
            self.assertTrue(all(call.args[0] == "GET" for call in self.api.request.call_args_list))
            if not preview:
                self.assertEqual(self.api.request.call_count, 3)

    def test_paid_court_is_skipped_for_next_free_court(self):
        original = self.response
        seen = []

        def request(method, path, *args, **kwargs):
            response = original(method, path, *args, **kwargs)
            if path.endswith("/preconfirm"):
                seen.append(args[0]["BOOKING_TITLE"])
                if len(seen) == 1:
                    response["booking_header"]["price"]["value"] = "100 บาท"
            return response

        self.api.request.side_effect = request
        self.assertEqual(self.run_bot()["outcome"], "booked")
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(self.posts), 1)
        self.assertNotEqual(self.posts[0]["BOOKING_TITLE"], seen[0])

    def test_availability_retry_is_bounded_and_classified(self):
        self.courts[:] = self.courts[:1]
        attempts = []
        original = self.response

        def request(method, path, *args, **kwargs):
            if path.endswith("/slot"):
                attempts.append(path)
                if len(attempts) == 1:
                    raise ApiHttpError("limited", 429, "0")
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        with self.assertLogs("bkk-active", level="INFO") as logs:
            self.assertEqual(self.run_bot()["outcome"], "booked")
        output = "\n".join(logs.output)
        self.assertIn('"retry_count": 1', output)
        self.assertIn('"error_class": "http_429"', output)
        self.assertEqual(len(attempts), 2)

    def test_retry_after_beyond_budget_does_not_retry(self):
        self.api.request.side_effect = ApiHttpError("limited", 429, "60")
        with self.assertRaises(ApiHttpError):
            self.run_bot()
        self.assertLessEqual(self.api.request.call_count, 3)
        self.assertEqual(self.posts, [])

    def test_performance_events_include_scheduled_kpi_and_outcome(self):
        self.args.scheduled_at = datetime.now(cli.TZ) - timedelta(seconds=1)
        self.api.request.side_effect = self.response
        with self.assertLogs("bkk-active", level="INFO") as logs:
            self.run_bot()
        events = [json.loads(line.split("API performance ")[1]) for line in logs.output if "API performance " in line]
        by_name = {event["event"]: event for event in events}
        for name in ("execution_started", "court_discovery", "availability_started",
                     "first_availability_response", "first_eligible_court", "first_booking_request",
                     "booking_response", "execution_finished"):
            self.assertIn(name, by_name)
            self.assertGreaterEqual(by_name[name]["elapsed_ms"], 0)
        self.assertEqual(by_name["availability_started"]["concurrent_requests"], 3)
        self.assertGreaterEqual(by_name["first_booking_request"]["ms_after_scheduled"], 1000)
        self.assertEqual(by_name["execution_finished"]["outcome"], "booked")

    def test_unknown_outcome_blocks_same_account_using_another_session_file(self):
        original = self.response

        def request(method, path, *args, **kwargs):
            if path == BASE + "/booking":
                self.posts.append(args[0])
                raise TimeoutError()
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        with self.assertRaisesRegex(RuntimeError, "ห้ามส่งซ้ำ"):
            self.run_bot()
        other = copy(self.args)
        other.session += ".other"
        with patch("bkk_active.api_booking.load_session", return_value=self.fixture.sample_session()), \
                patch("bkk_active.api_booking.BookingApi", return_value=self.api):
            with self.assertRaisesRegex(RuntimeError, "ห้ามส่งซ้ำ"):
                run_api_booking(other)
        self.assertEqual(len(self.posts), 1)

    def test_cancelled_listing_cannot_prove_an_ambiguous_new_post_failed(self):
        original = self.response
        cancelled = {**self.fixture.booked["booking_data"], "BOOKING_STATUS": "CANCELLED"}
        self.api.bookings.side_effect = [[], [cancelled]]

        def request(method, path, *args, **kwargs):
            if path == BASE + "/booking":
                self.posts.append(args[0])
                raise TimeoutError()
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        with self.assertRaisesRegex(RuntimeError, "ห้ามส่งซ้ำ"):
            self.run_bot()
        self.assertEqual(len(self.posts), 1)

    def test_preconfirm_unavailable_attempts_another_court(self):
        original = self.response
        confirmations = []

        def request(method, path, *args, **kwargs):
            response = original(method, path, *args, **kwargs)
            if path.endswith("/preconfirm"):
                confirmations.append(args[0]["BOOKING_TITLE"])
                if len(confirmations) == 1:
                    response["is_available"] = False
            return response

        self.api.request.side_effect = request
        self.assertEqual(self.run_bot()["outcome"], "booked")
        self.assertEqual(len(confirmations), 2)
        self.assertEqual(len(self.posts), 1)
        self.assertNotEqual(self.posts[0]["BOOKING_TITLE"], confirmations[0])

    def test_duplicate_court_ids_are_not_attempted_twice(self):
        self.courts.append(self.courts[0])
        original = self.response

        def request(method, path, *args, **kwargs):
            if path == BASE + "/booking":
                self.posts.append(args[0])
                return {"is_book": False}
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        self.assertEqual(self.run_bot()["outcome"], "no_available_slot")
        self.assertEqual(len(self.posts), 3)
        self.assertEqual(len({post["BOOKING_TITLE"] for post in self.posts}), 3)

    def test_rate_limit_from_one_court_delays_preconfirm_for_other_courts(self):
        original = self.response
        limited = threading.Event()
        first_error = []
        preconfirms = []

        def request(method, path, *args, **kwargs):
            if "court-1/slot" in path and not first_error:
                first_error.append(clock.monotonic())
                limited.set()
                raise ApiHttpError("limited", 429, "0")
            if path.endswith("/slot"):
                limited.wait(timeout=2)
                clock.sleep(0.02)
            if path.endswith("/preconfirm"):
                preconfirms.append(clock.monotonic())
            return original(method, path, *args, **kwargs)

        self.api.request.side_effect = request
        self.assertEqual(self.run_bot()["outcome"], "booked")
        self.assertGreaterEqual(preconfirms[0] - first_error[0], 0.49)

    def test_read_retries_recover_from_network_timeout_and_server_errors(self):
        for error in (ConnectionResetError(), TimeoutError(), ApiHttpError("temporary", 503)):
            with self.subTest(error=error):
                self.setUp()
                self.courts[:] = self.courts[:1]
                original = self.response
                failed = []

                def request(method, path, *args, **kwargs):
                    if path.endswith("/slot") and not failed:
                        failed.append(True)
                        raise error
                    return original(method, path, *args, **kwargs)

                self.api.request.side_effect = request
                self.assertEqual(self.run_bot()["outcome"], "booked")
                self.assertEqual(len(self.posts), 1)

    def test_scheduler_prepares_session_before_execution_and_keeps_running(self):
        now = datetime(2026, 10, 27, 6, 59, tzinfo=cli.TZ)
        preparations, executions = [], []

        def sleep(seconds):
            nonlocal now
            now += timedelta(seconds=seconds)

        def prepare(path):
            preparations.append(now)
            return self.fixture.sample_session()

        def execute(args):
            executions.append(now)
            self.assertEqual(args.prepared_session, self.fixture.sample_session())
            self.assertEqual(args.scheduled_at, now)
            if len(executions) == 2:
                raise KeyboardInterrupt()
            return {"outcome": "booked"}

        with patch.object(cli, "datetime") as dt, patch.object(cli, "load_session", side_effect=prepare), \
                patch.object(cli.time_module, "sleep", side_effect=sleep), \
                patch.object(cli, "run_once", side_effect=execute):
            dt.now.side_effect = lambda tz: now
            dt.combine.side_effect = datetime.combine
            with self.assertRaises(KeyboardInterrupt):
                cli.run_schedule(SimpleNamespace(session=self.args.session, schedule=time(7)))
        self.assertEqual(len(executions), 2)
        for prepared, executed in zip(preparations, executions):
            self.assertEqual((executed - prepared).total_seconds(), 30)
