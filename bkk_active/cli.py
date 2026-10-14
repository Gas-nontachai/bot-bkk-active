"""Command-line arguments and retry entry point."""
import argparse
from datetime import date, datetime, timedelta
from copy import copy
from contextlib import nullcontext
from zoneinfo import ZoneInfo
from .retry import retry_missing_center
from .runner import run_flow
from .logging_setup import LOGGER, configure_logging, status
from .run_artifacts import RunArtifacts, set_run_artifacts
from .scheduler import parse_time, parse_days, run_schedule
from .api_capture import ApiCapture


def parse_booking_time(value):
    if value == "24:00":
        return 24 * 60
    try:
        parsed = parse_time(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return parsed.hour * 60 + parsed.minute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
    parser.add_argument("--center", default="ศูนย์กีฬาเบญจกิติ", help="ชื่อศูนย์กีฬาที่จะค้นหา")
    parser.add_argument("--date", type=date.fromisoformat,
                        help="วันที่จอง YYYY-MM-DD ต้องเป็นวันนี้หรือพรุ่งนี้ตามเวลาไทย")
    parser.add_argument("--booking-day", choices=("today", "tomorrow", "both"),
                        help="เลือก today/tomorrow หรือ both: ลองวันนี้ก่อนแล้วพรุ่งนี้ (ค่าเริ่มต้น: both)")
    parser.add_argument("--start-time", type=parse_booking_time, dest="start_minute", default=0,
                        metavar="HH:MM", help="เวลาเริ่มเร็วที่สุดที่ต้องการ (ค่าเริ่มต้น: 00:00)")
    parser.add_argument("--end-time", type=parse_booking_time, dest="end_minute", default=24 * 60,
                        metavar="HH:MM", help="เวลาจบช้าที่สุดที่ต้องการ (ค่าเริ่มต้น: 24:00)")
    parser.add_argument("--schedule", type=parse_time, metavar="HH:MM",
                        help="ปล่อยรันทุกวันตามเวลาไทย เช่น 06:00")
    parser.add_argument("--days", type=parse_days, metavar="DAYS",
                        help="วันทำงาน เช่น wed,thu,fri หรือ พ,พฤ,ศ (ค่าเริ่มต้น: ทุกวัน)")
    parser.add_argument("--verbose", action="store_true", help="แสดง log ละเอียดใน terminal ด้วย")
    parser.add_argument("--debug-capture", action="store_true",
                        help="เก็บภาพทุกขั้นตอนแบบละเอียด (ค่าเริ่มต้น: โหมดเร็ว)")
    parser.add_argument("--ui-backend", choices=("bridge", "uiautomator"), default="bridge",
                        help="วิธีอ่านหน้าจอ (ค่าเริ่มต้น: Android bridge แบบเร็ว)")
    parser.add_argument("--capture-api", action="store_true", help="จับ HTTP/HTTPS ผ่าน mitmproxy")
    parser.add_argument("--api-port", type=int, default=8080, help="พอร์ต proxy บนเครื่อง (ค่าเริ่มต้น: 8080)")
    parser.add_argument("--api-host", action="append", help="เก็บเฉพาะ hostname นี้ ระบุซ้ำได้")
    parser.add_argument("--api-bodies", action="store_true", help="เก็บ JSON body พร้อมปิดบังข้อมูลสำคัญ")
    args = parser.parse_args()
    if args.start_minute >= args.end_minute:
        parser.error("--start-time ต้องก่อน --end-time และช่วงเวลาต้องอยู่ภายในวันเดียวกัน")
    if not 1 <= args.api_port <= 65535:
        parser.error("--api-port ต้องอยู่ระหว่าง 1–65535")
    if (args.api_host or args.api_bodies) and not args.capture_api:
        parser.error("--api-host และ --api-bodies ต้องใช้ร่วมกับ --capture-api")
    if args.api_bodies and not args.api_host:
        parser.error("--api-bodies ต้องระบุ --api-host เพื่อจำกัด body ให้เฉพาะ API ที่ต้องการ")
    if args.days is not None and args.schedule is None:
        parser.error("--days ต้องใช้ร่วมกับ --schedule")
    if args.schedule is not None and args.date is not None:
        parser.error("โหมด schedule ใช้ --booking-day today/tomorrow/both แทน --date")
    if args.date is not None and args.booking_day is not None:
        parser.error("เลือกใช้ --date หรือ --booking-day อย่างใดอย่างหนึ่ง")
    today = datetime.now(ZoneInfo("Asia/Bangkok")).date()
    if args.date is not None and args.date not in (today, today + timedelta(days=1)):
        parser.error("จองได้เฉพาะวันนี้หรือพรุ่งนี้ ตามเวลาไทย")
    configure_logging(verbose=args.verbose)
    try:
        if args.schedule is not None:
            return run_schedule(args.schedule, args.days or frozenset(range(7)),
                                lambda day: execute_run(args, day))
        return execute_run(args, today)
    except KeyboardInterrupt:
        status("หยุดการทำงานแล้ว")


def execute_run(args, day):
    config = copy(args)
    offset = 1 if getattr(args, "booking_day", None) == "tomorrow" else 0
    config.date = args.date or (day + timedelta(days=offset))
    config.booking_dates = (config.date,)
    if args.date is None and getattr(args, "booking_day", None) in (None, "both"):
        config.booking_dates = (day, day + timedelta(days=1))
    capture_mode = "debug" if getattr(args, "debug_capture", False) else "fast"
    artifacts = RunArtifacts(capture_mode=capture_mode)
    set_run_artifacts(artifacts)
    configure_logging(artifacts.log_file, verbose=args.verbose)
    LOGGER.info("โฟลเดอร์ผลการรัน: %s", artifacts.folder)
    status("เริ่มทำงาน — ลองจองวันที่ %s",
           ", ".join(target.isoformat() for target in config.booking_dates))
    outcome = "interrupted"
    try:
        capture = ApiCapture(artifacts, config) if getattr(args, "capture_api", False) else nullcontext()
        with capture:
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
