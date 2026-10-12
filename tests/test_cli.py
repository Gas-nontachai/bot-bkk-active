from datetime import date
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bkk_active.cli import execute_run, main


class CliTests(unittest.TestCase):
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
