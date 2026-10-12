"""Command-line arguments and retry entry point."""
import argparse
from datetime import date, datetime
from copy import copy
from zoneinfo import ZoneInfo
from .retry import retry_missing_center
from .runner import run_flow
from .logging_setup import LOGGER, configure_logging, status
from .run_artifacts import RunArtifacts, set_run_artifacts
from .scheduler import parse_time, parse_days, run_schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
    parser.add_argument("--center", default="ศูนย์กีฬาเบญจกิติ", help="ชื่อศูนย์กีฬาที่จะค้นหา")
    parser.add_argument("--date", type=date.fromisoformat,
                        help="วันที่จอง YYYY-MM-DD (ค่าเริ่มต้นคือวันที่รันตามเวลาไทย)")
    parser.add_argument("--schedule", type=parse_time, metavar="HH:MM",
                        help="ปล่อยรันทุกวันตามเวลาไทย เช่น 06:00")
    parser.add_argument("--days", type=parse_days, metavar="DAYS",
                        help="วันทำงาน เช่น wed,thu,fri หรือ พ,พฤ,ศ (ค่าเริ่มต้น: ทุกวัน)")
    parser.add_argument("--verbose", action="store_true", help="แสดง log ละเอียดใน terminal ด้วย")
    parser.add_argument("--debug-capture", action="store_true",
                        help="เก็บภาพทุกขั้นตอนแบบละเอียด (ค่าเริ่มต้น: โหมดเร็ว)")
    args = parser.parse_args()
    if args.days is not None and args.schedule is None:
        parser.error("--days ต้องใช้ร่วมกับ --schedule")
    if args.schedule is not None and args.date is not None:
        parser.error("โหมด schedule ใช้วันที่ทำงานจริง จึงใช้ร่วมกับ --date ไม่ได้")
    configure_logging(verbose=args.verbose)
    try:
        if args.schedule is not None:
            return run_schedule(args.schedule, args.days or frozenset(range(7)),
                                lambda day: execute_run(args, day))
        day = args.date or datetime.now(ZoneInfo("Asia/Bangkok")).date()
        return execute_run(args, day)
    except KeyboardInterrupt:
        status("หยุดการทำงานแล้ว")


def execute_run(args, day):
    config = copy(args)
    config.date = day
    capture_mode = "debug" if getattr(args, "debug_capture", False) else "fast"
    artifacts = RunArtifacts(capture_mode=capture_mode)
    set_run_artifacts(artifacts)
    configure_logging(artifacts.log_file, verbose=args.verbose)
    LOGGER.info("โฟลเดอร์ผลการรัน: %s", artifacts.folder)
    status("เริ่มทำงาน วันที่ %s", day.isoformat())
    outcome = "interrupted"
    try:
        result = retry_missing_center(lambda: run_flow(config), retries=3)
        outcome = str(result or "finished")
        status("จบรอบ — log: logger/%s/", artifacts.folder.name)
        return result
    except Exception:
        outcome = "error"
        status("รอบนี้มี error — ดูรายละเอียดที่ logger/%s/", artifacts.folder.name)
        raise
    finally:
        try:
            report = artifacts.metrics.finish(artifacts.folder, outcome=outcome,
                                             attempts=artifacts.attempt, capture_mode=capture_mode)
            LOGGER.info("สรุปผลการรัน: %s", report)
        except OSError as error:
            LOGGER.warning("บันทึก summary.json ไม่สำเร็จ: %s", error)
        finally:
            set_run_artifacts(None)
