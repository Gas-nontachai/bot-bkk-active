from datetime import date, datetime
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from bkk_active.cli import execute_run, main


class CliTests(unittest.TestCase):
    def test_capture_only_enables_capture_and_rejects_schedule(self):
        with patch("sys.argv", ["open_booking.py", "--capture-only", "--api-host", "api.test", "--api-bodies"]), \
                patch("bkk_active.cli.configure_logging"), \
                patch("bkk_active.cli.execute_run") as execute:
            main()
            self.assertTrue(execute.call_args.args[0].capture_api)
        with patch("sys.argv", ["open_booking.py", "--capture-only", "--schedule", "07:00"]), \
                patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                main()

    def test_manual_capture_never_runs_booking_and_cleans_up(self):
        args = SimpleNamespace(serial="test", date=None, verbose=False,
                               capture_only=True, capture_api=True)
        for stopped in (False, True):
            with self.subTest(proxy_stopped=stopped), \
                    patch("bkk_active.cli.RunArtifacts"), \
                    patch("bkk_active.cli.configure_logging"), \
                    patch("bkk_active.cli.set_run_artifacts"), \
                    patch("bkk_active.cli.ApiCapture") as capture, \
                    patch("bkk_active.cli.time.sleep", side_effect=KeyboardInterrupt), \
                    patch("bkk_active.cli.run_flow") as flow:
                capture.return_value = MagicMock()
                capture.return_value.process.poll.return_value = 1 if stopped else None
                with self.assertRaises(RuntimeError if stopped else KeyboardInterrupt):
                    execute_run(args, date(2026, 10, 20))
                flow.assert_not_called()
                capture.return_value.__exit__.assert_called_once()

    def test_booking_time_window_defaults_and_custom_bounds(self):
        for options, expected in (([], (0, 1440)),
                                  (["--start-time", "18:00", "--end-time", "21:00"], (1080, 1260)),
                                  (["--start-time", "18:20"], (1100, 1440)),
                                  (["--end-time", "10:30"], (0, 630)),
                                  (["--end-time", "24:00"], (0, 1440))):
            with self.subTest(options=options), \
                    patch("sys.argv", ["open_booking.py"] + options), \
                    patch("bkk_active.cli.configure_logging"), \
                    patch("bkk_active.cli.execute_run") as execute:
                main()
                config = execute.call_args.args[0]
                self.assertEqual((config.start_minute, config.end_minute), expected)

    def test_invalid_or_overnight_booking_windows_are_rejected(self):
        for options in (["--start-time", "24:00"], ["--end-time", "24:01"],
                        ["--start-time", "18:60"], ["--start-time", "18"],
                        ["--start-time", "21:00", "--end-time", "18:00"],
                        ["--start-time", "18:00", "--end-time", "18:00"]):
            with self.subTest(options=options), \
                    patch("sys.argv", ["open_booking.py"] + options), \
                    patch("sys.stderr", io.StringIO()), \
                    patch("bkk_active.cli.execute_run") as execute:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                execute.assert_not_called()

    def test_booking_day_modes_and_explicit_date(self):
        today, tomorrow = date(2026, 12, 31), date(2027, 1, 1)
        for mode, explicit, expected in ((None, None, (today, tomorrow)),
                                         ("both", None, (today, tomorrow)),
                                         ("today", None, (today,)),
                                         ("tomorrow", None, (tomorrow,)),
                                         (None, tomorrow, (tomorrow,))):
            args = SimpleNamespace(serial="test", date=explicit, booking_day=mode, verbose=False)
            with self.subTest(mode=mode, explicit=explicit), \
                    patch("bkk_active.cli.RunArtifacts"), \
                    patch("bkk_active.cli.configure_logging"), \
                    patch("bkk_active.cli.set_run_artifacts"), \
                    patch("bkk_active.cli.run_flow") as flow:
                execute_run(args, today)
                self.assertEqual(flow.call_args.args[0].booking_dates, expected)

    def test_tomorrow_is_recomputed_for_each_scheduled_run(self):
        args = SimpleNamespace(serial="test", center="center", date=None,
                               booking_day="tomorrow", verbose=False)
        with patch("bkk_active.cli.RunArtifacts"), \
                patch("bkk_active.cli.configure_logging"), \
                patch("bkk_active.cli.set_run_artifacts"), \
                patch("bkk_active.cli.run_flow") as flow:
            execute_run(args, date(2026, 10, 13))
            execute_run(args, date(2026, 10, 14))
        self.assertEqual([call.args[0].date for call in flow.call_args_list],
                         [date(2026, 10, 14), date(2026, 10, 15)])

    def test_explicit_dates_outside_today_and_tomorrow_are_rejected(self):
        for invalid in ("2026-10-12", "2026-10-15"):
            with patch("sys.argv", ["open_booking.py", "--date", invalid]), \
                    patch("sys.stderr", io.StringIO()), \
                    patch("bkk_active.cli.datetime") as clock, \
                    patch("bkk_active.cli.execute_run") as execute:
                clock.now.return_value = datetime(2026, 10, 13, 6)
                with self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(error.exception.code, 2)
            execute.assert_not_called()

    def test_explicit_tomorrow_date_is_preserved(self):
        args = SimpleNamespace(serial="test", center="center", date=date(2026, 10, 14),
                               booking_day=None, verbose=False)
        with patch("bkk_active.cli.RunArtifacts"), \
                patch("bkk_active.cli.configure_logging"), \
                patch("bkk_active.cli.set_run_artifacts"), \
                patch("bkk_active.cli.run_flow") as flow:
            execute_run(args, date(2026, 10, 13))
        self.assertEqual(flow.call_args.args[0].date, date(2026, 10, 14))

    def test_each_scheduled_run_gets_its_own_date_and_artifact_folder(self):
        args = SimpleNamespace(serial="test", center="center", date=None, verbose=False)
        first = Mock(folder=Path("logger/first"))
        second = Mock(folder=Path("logger/second"))
        with patch("bkk_active.cli.RunArtifacts", side_effect=[first, second]), \
                patch("bkk_active.cli.configure_logging") as configure, \
                patch("bkk_active.cli.set_run_artifacts"), \
                patch("bkk_active.cli.run_flow") as flow:
            execute_run(args, date(2026, 10, 13))
            execute_run(args, date(2026, 10, 14))
        self.assertEqual([call.args[0].date for call in flow.call_args_list],
                         [date(2026, 10, 13), date(2026, 10, 14)])
        self.assertIsNone(args.date)
        self.assertEqual([call.args[0] for call in configure.call_args_list], [first.log_file, second.log_file])

    def test_fixed_date_cannot_be_used_in_recurring_schedule(self):
        with patch("sys.argv", ["open_booking.py", "--schedule", "06:00", "--date", "2026-10-13"]), \
                patch("sys.stderr", io.StringIO()), \
                patch("bkk_active.cli.run_schedule") as schedule:
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 2)
        schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
