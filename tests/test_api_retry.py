from datetime import date, datetime, time, timedelta
from email.utils import formatdate
import http.client
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import open_booking_api as cli
from bkk_active.api_booking import ApiHttpError, BASE, BookingApi, find_center
from bkk_active.logging_setup import BangkokFormatter, StatusFormatter
from tests import test_api_booking


class CenterRetryTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0
        self.sleeps = []
        self.center = {"ID": "center", "NAME": "target"}
        self.api = Mock()
        self.clock = patch("bkk_active.api_booking.time.monotonic", side_effect=lambda: self.elapsed)
        self.sleep = patch("bkk_active.api_booking.time.sleep", side_effect=self.advance)
        self.clock.start()
        self.sleep.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.sleep.stop)

    def advance(self, seconds):
        self.sleeps.append(seconds)
        self.elapsed += seconds

    def test_empty_then_success_and_logs(self):
        self.api.items.side_effect = [[], [], [self.center]]
        with self.assertLogs("bkk-active", level="INFO") as logs:
            self.assertEqual(find_center(self.api, "target"), self.center)
        self.assertEqual(self.sleeps, [0.5, 0.5])
        self.assertEqual([call.kwargs["timeout"] for call in self.api.items.call_args_list], [5, 4.5, 4])
        output = "\n".join(logs.output)
        for text in ("attempt=1 http_status=200 matches=0 reason=no_matches", "result=success attempts=3"):
            self.assertIn(text, output)

    def test_empty_exhausts_window_without_request_at_deadline(self):
        self.api.items.return_value = []
        with self.assertLogs("bkk-active", level="INFO") as logs:
            with self.assertRaisesRegex(RuntimeError, "5 วินาที"):
                find_center(self.api, "target")
        self.assertEqual(self.api.items.call_count, 10)
        self.assertEqual(self.elapsed, 4.5)
        self.assertIn("result=failure attempts=10", "\n".join(logs.output))

    def test_network_and_temporary_http_errors_retry(self):
        for error in (TimeoutError(), ConnectionResetError(), http.client.RemoteDisconnected(),
                      *(ApiHttpError("temporary", code) for code in (408, 500, 502, 503, 504))):
            with self.subTest(error=error):
                self.api.reset_mock()
                self.api.items.side_effect = [error, [self.center]]
                self.assertEqual(find_center(self.api, "target"), self.center)
                self.assertEqual(self.api.items.call_count, 2)

    def test_auth_other_http_multiple_and_invalid_fail_immediately(self):
        for value in (ApiHttpError("auth", 401), ApiHttpError("auth", 403), ApiHttpError("bad", 400),
                      [self.center, self.center], [{"NAME": "target"}], ValueError("invalid JSON")):
            with self.subTest(value=value):
                self.api.reset_mock()
                self.api.items.side_effect = [value]
                with self.assertLogs("bkk-active", level="INFO") as logs:
                    with self.assertRaises((RuntimeError, ValueError)):
                        find_center(self.api, "target")
                self.assertEqual(self.api.items.call_count, 1)
                self.assertIn("result=failure attempts=1", "\n".join(logs.output))
        self.assertEqual(self.sleeps, [])

    def test_retry_after_seconds_date_invalid_and_beyond_window(self):
        for header, delay in (("2", 2), (formatdate(1002, usegmt=True), 2), ("invalid", 0.5), ("0", 0.5)):
            with self.subTest(header=header), patch("bkk_active.api_booking.time.time", return_value=1000):
                self.elapsed = 0
                self.api.items.side_effect = [ApiHttpError("limited", 429, header), [self.center]]
                find_center(self.api, "target")
                self.assertEqual(self.sleeps[-1], delay)
        self.api.reset_mock()
        self.api.items.side_effect = [ApiHttpError("limited", 429, "10")]
        with self.assertRaises(RuntimeError):
            find_center(self.api, "target")
        self.assertEqual(self.api.items.call_count, 1)

    def test_slow_request_consumes_budget_sequentially(self):
        def request(**kwargs):
            self.elapsed += kwargs["timeout"]
            raise TimeoutError()
        self.api.items.side_effect = request
        with self.assertRaises(RuntimeError):
            find_center(self.api, "target")
        self.assertEqual(self.elapsed, 5)
        self.assertEqual(self.api.items.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_transport_preserves_status_retry_after_and_closes(self):
        for code in (429, 503):
            connection = Mock()
            response = connection.getresponse.return_value
            response.status = code
            response.read1.side_effect = [b'{}', b'']
            response.getheader.return_value = "2"
            with patch("bkk_active.api_booking.http.client.HTTPSConnection", return_value=connection):
                with self.assertRaises(ApiHttpError) as raised:
                    BookingApi("Bearer token").items(timeout=3)
            self.assertEqual((raised.exception.status, raised.exception.retry_after), (code, "2"))
            connection.close.assert_called_once()
            self.assertEqual(connection.sock.settimeout.call_args.args, (3,))

    def test_body_reads_share_request_deadline(self):
        connection = Mock()
        def read(_):
            self.elapsed += 3
            return b' '
        connection.getresponse.return_value.read1.side_effect = read
        with patch("bkk_active.api_booking.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaises(TimeoutError):
                BookingApi("Bearer token").items(timeout=5)
        self.assertEqual(connection.getresponse.return_value.read1.call_count, 2)
        connection.close.assert_called_once()


class ApiLifecycleTests(unittest.TestCase):
    def test_center_retry_continues_preview_and_booking_once(self):
        for book in (False, True):
            fixture = test_api_booking.ApiBookingTests()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            fixture.args.book = book
            api = fixture.setup_api()
            api.items.side_effect = [[], [{"ID": "center", "NAME": fixture.args.center}],
                                     [{"ID": "activity", "NAME": "สนามแบดมินตัน"}],
                                     [{"ID": "court-1", "NAME": "แบดมินตัน สนาม 1"}]]
            api.request.side_effect = [[fixture.slot], fixture.confirmation, fixture.booked,
                                       {"status": "create success"}]
            with patch("bkk_active.api_booking.time.sleep"):
                result = fixture.run_with(api)
            self.assertEqual(result["outcome"], "booked" if book else "available")
            api.bookings.assert_called_once()
            self.assertEqual(sum(call.args[1] == BASE + "/booking" for call in api.request.call_args_list),
                             1 if book else 0)

    def test_run_once_keeps_schedule_dates_fresh_and_fallback(self):
        args = SimpleNamespace(date=None, booking_day="both", book=False)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(cli, "RunArtifacts", return_value=SimpleNamespace(folder=Path(folder), log_file=None)), \
                patch.object(cli, "configure_logging"), \
                patch.object(cli, "datetime") as clock, \
                patch.object(cli, "run_api_booking") as run:
            for day in (date(2026, 10, 26), date(2026, 10, 27)):
                clock.now.return_value.date.return_value = day
                dates = []
                def action(config):
                    dates.append(config.date)
                    return {"outcome": "no_available_slot" if len(dates) == 1 else "available"}
                run.side_effect = action
                self.assertEqual(cli.run_once(args)["outcome"], "available")
                self.assertEqual(dates, [day, day + timedelta(days=1)])
                self.assertIsNone(args.date)

    def test_scheduler_recovers_from_any_round_exception(self):
        for error in (RuntimeError("retry exhausted"), KeyError("unexpected response"), OSError("network")):
            current = datetime(2026, 10, 26, 6, 59, tzinfo=cli.TZ)
            days = []
            def sleep(seconds):
                nonlocal current
                current += timedelta(seconds=seconds)
            def action(args):
                days.append(current.date())
                if len(days) == 1:
                    raise error
                raise KeyboardInterrupt()
            with patch.object(cli, "datetime") as clock, \
                    patch.object(cli.time_module, "sleep", side_effect=sleep), \
                    patch.object(cli, "run_once", side_effect=action), \
                    self.assertLogs("bkk-active", level="ERROR"):
                clock.now.side_effect = lambda tz: current
                clock.combine.side_effect = datetime.combine
                with self.assertRaises(KeyboardInterrupt):
                    cli.run_schedule(SimpleNamespace(schedule=time(7)))
            self.assertEqual(days, [date(2026, 10, 26), date(2026, 10, 27)])

    def test_log_timestamps_include_milliseconds(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        record.created = 0.123
        self.assertEqual(StatusFormatter().format(record), "07:00:00.123 hello")
        self.assertIn("07:00:00.123 +0700", BangkokFormatter().formatTime(record))
