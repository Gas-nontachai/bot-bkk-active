"""Command-line arguments and retry entry point."""
import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo
from .retry import retry_missing_center
from .runner import run_flow
from .logging_setup import LOGGER, configure_logging
from .run_artifacts import RunArtifacts, set_run_artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
    parser.add_argument("--center", default="ศูนย์กีฬาเบญจกิติ", help="ชื่อศูนย์กีฬาที่จะค้นหา")
    parser.add_argument("--date", type=date.fromisoformat,
                        default=datetime.now(ZoneInfo("Asia/Bangkok")).date(),
                        help="วันที่จอง YYYY-MM-DD (ค่าเริ่มต้นคือวันที่รันตามเวลาไทย)")
    args = parser.parse_args()
    artifacts = RunArtifacts()
    set_run_artifacts(artifacts)
    configure_logging(artifacts.log_file)
    LOGGER.info("โฟลเดอร์ผลการรัน: %s", artifacts.folder)
    try:
        result = retry_missing_center(lambda: run_flow(args), retries=3)
        LOGGER.info("จบการทำงาน ดู log และภาพได้ที่ %s", artifacts.folder)
        return result
    finally:
        set_run_artifacts(None)
