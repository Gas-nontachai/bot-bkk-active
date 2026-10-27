
#!/usr/bin/env python3
"""Read availability or explicitly book through the BKK Active API."""

import argparse
from copy import copy
from datetime import date, datetime, time, timedelta
import http.client
import json
import sys
import time as time_module
from zoneinfo import ZoneInfo

from bkk_active.api_booking import run_api_booking
from bkk_active.cli import parse_booking_time
from bkk_active.logging_setup import configure_logging, LOGGER, status
from bkk_active.run_artifacts import RunArtifacts


TZ = ZoneInfo("Asia/Bangkok")


def parse_schedule(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "รูปแบบ --schedule ต้องเป็น HH:MM เช่น 06:00"
        )


def resolve_dates(args):
    today = datetime.now(TZ).date()

    if args.date is not None:
        return [args.date]

    if args.booking_day == "today":
        return [today]

    if args.booking_day == "tomorrow":
        return [today + timedelta(days=1)]

    if args.booking_day == "both":
        return [today, today + timedelta(days=1)]

    raise RuntimeError("ไม่ได้ระบุวันที่จอง")


def run_once(args):
    args = copy(args)
    artifacts = RunArtifacts()
    configure_logging(artifacts.log_file)

    results = []
    dates = resolve_dates(args)
    today = datetime.now(TZ).date()

    status(
        "เริ่มบอต API — %s",
        "จองจริง" if args.book else "ตรวจเวลาว่าง"
    )

    try:
        for booking_date in dates:
            if booking_date not in (
                today,
                today + timedelta(days=1)
            ):
                raise RuntimeError(
                    "จองได้เฉพาะวันนี้หรือพรุ่งนี้ตามเวลาไทย"
                )

            args.date = booking_date
            status("ตรวจสอบวันที่ %s", booking_date)

            result = run_api_booking(args)
            results.append(result)

            outcome = result["outcome"]

            # Only fall back if today's slots are all unavailable.
            if outcome != "no_available_slot":
                break

        summary = {
            "mode": "book" if args.book else "preview",
            "results": results,
            "outcome": results[-1]["outcome"],
        }

        return summary

    finally:
        summary_path = artifacts.folder / "summary.json"
        summary_path.write_text(
            json.dumps(
                {"results": results},
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )
        status("จบรอบ API — log: %s", artifacts.folder)


def run_schedule(args):
    status("ตั้งเวลาทำงานทุกวัน %s (Asia/Bangkok)", args.schedule)

    while True:
        now = datetime.now(TZ)

        target = datetime.combine(
            now.date(),
            args.schedule,
            tzinfo=TZ
        )

        if target <= now:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()

        status("รอบถัดไป: %s", target.isoformat())

        time_module.sleep(wait_seconds)

        try:
            result = run_once(args)
            status("ผลการทำงาน: %s", result["outcome"])
        except Exception:
            LOGGER.exception("บอต API ทำงานไม่สำเร็จ จะรอรอบถัดไป")

        # Continue to the next day's schedule.


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--session", required=True, help="ไฟล์ session.json ที่ผ่านการตรวจสอบ")

    parser.add_argument(
        "--center",
        default="ศูนย์กีฬาเบญจกิติ"
    )

    parser.add_argument(
        "--date",
        type=date.fromisoformat
    )

    parser.add_argument(
        "--schedule",
        type=parse_schedule,
        help="เวลารันทุกวัน เช่น 06:00 (Asia/Bangkok)"
    )

    parser.add_argument(
        "--booking-day",
        choices=["today", "tomorrow", "both"],
        help="เลือกวันที่จองโดยคำนวณใหม่ทุกครั้ง"
    )

    parser.add_argument(
        "--start-time",
        dest="start_minute",
        type=parse_booking_time,
        required=True
    )

    parser.add_argument(
        "--end-time",
        dest="end_minute",
        type=parse_booking_time,
        required=True
    )

    parser.add_argument(
        "--book",
        action="store_true",
        help="ส่งจองจริง (ค่าเริ่มต้นเป็น Preview)"
    )

    parser.add_argument(
        "--allow-paid", action="store_true",
        help="อนุญาตการจองที่มีค่าบริการด้วย (ชำระเงินเองภายหลัง)"
    )

    args = parser.parse_args()

    if args.date and args.booking_day:
        parser.error(
            "ห้ามใช้ --date ร่วมกับ --booking-day"
        )

    if args.schedule and not args.booking_day:
        parser.error(
            "--schedule ต้องใช้ร่วมกับ --booking-day"
        )

    if args.schedule and args.date:
        parser.error(
            "--schedule ไม่รองรับ --date แบบตายตัว"
        )

    if not args.date and not args.booking_day:
        parser.error(
            "ต้องระบุ --date หรือ --booking-day"
        )

    if args.start_minute >= args.end_minute:
        parser.error(
            "--start-time ต้องก่อน --end-time"
        )

    if args.schedule:
        configure_logging()
        status("บอต API เริ่มทำงานแล้ว")
        run_schedule(args)
    else:
        run_once(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nหยุดบอต API")
    except (
        RuntimeError,
        OSError,
        http.client.HTTPException,
        ValueError
    ) as error:
        LOGGER.error("บอต API หยุด: %s", error)
        sys.exit(1)
