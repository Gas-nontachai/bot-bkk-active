"""Run at a Bangkok wall-clock time on selected weekdays, without overlap."""
from datetime import datetime, time as wall_time, timedelta
import re
import time
from zoneinfo import ZoneInfo

from .logging_setup import LOGGER, status

BANGKOK = ZoneInfo("Asia/Bangkok")
DAY_NAMES = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")
DAY_ALIASES = (
    ("mon", "monday", "จ", "จันทร์"),
    ("tue", "tuesday", "อ", "อังคาร"),
    ("wed", "wednesday", "พ", "พุธ"),
    ("thu", "thursday", "พฤ", "พฤหัส", "พฤหัสบดี"),
    ("fri", "friday", "ศ", "ศุกร์"),
    ("sat", "saturday", "ส", "เสาร์"),
    ("sun", "sunday", "อา", "อาทิตย์"),
)


def parse_time(value):
    if not re.fullmatch(r"\d{1,2}:\d{2}", value):
        raise ValueError("เวลาใช้รูปแบบ HH:MM เช่น 06:00")
    hour, minute = map(int, value.split(":"))
    try:
        return wall_time(hour, minute)
    except ValueError as error:
        raise ValueError("เวลาต้องอยู่ระหว่าง 00:00–23:59") from error


def parse_days(value):
    value = value.strip().lower()
    if value in ("all", "daily", "ทุกวัน"):
        return frozenset(range(7))
    aliases = {alias: number for number, names in enumerate(DAY_ALIASES) for alias in names}
    selected = set()
    for token in value.split(","):
        token = token.strip().replace(".", "")
        if token.startswith("วัน"):
            token = token[3:]
        if token not in aliases:
            raise ValueError(f"ไม่รู้จักวัน '{token}' ใช้ mon,tue,wed,thu,fri,sat,sun หรือ จ,อ,พ,พฤ,ศ,ส,อา")
        selected.add(aliases[token])
    return frozenset(selected)


def next_run(now, at, days):
    if not days or any(day not in range(7) for day in days):
        raise ValueError("ต้องเลือกวันทำงานอย่างน้อยหนึ่งวัน")
    now = now.astimezone(BANGKOK)
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        candidate = datetime.combine(day, at, tzinfo=BANGKOK)
        if day.weekday() in days and candidate >= now:
            return candidate
    raise RuntimeError("คำนวณรอบถัดไปไม่ได้")


def run_schedule(at, days, action, *, now_fn=None, sleep_fn=None):
    now_fn = now_fn or (lambda: datetime.now(BANGKOK))
    sleep_fn = sleep_fn or time.sleep
    status("เปิด schedule %s วัน%s (เวลาไทย) — หยุดด้วย Ctrl+C",
           at.strftime("%H:%M"), ", ".join(DAY_NAMES[day] for day in sorted(days)))
    earliest = now_fn()
    while True:
        scheduled = next_run(max(now_fn(), earliest), at, days)
        status("รอรอบถัดไป: %s (เวลาไทย)", scheduled.strftime("%Y-%m-%d %H:%M"))
        while (remaining := (scheduled - now_fn()).total_seconds()) > 0:
            sleep_fn(min(remaining, 60))
        current = now_fn()
        # A laptop waking much later should wait for the next slot, not backfill bookings.
        if current > scheduled + timedelta(minutes=5):
            status("พลาดรอบ %s เกิน 5 นาที ข้ามไปรอบถัดไป", scheduled.strftime("%Y-%m-%d %H:%M"))
            earliest = current
            continue
        try:
            action(current.astimezone(BANGKOK).date())
        except Exception:
            LOGGER.exception("รอบ schedule มี error จะรอรอบถัดไป")
        # Even an instant run at exactly HH:MM must never run the same slot twice.
        earliest = max(now_fn(), scheduled + timedelta(microseconds=1))
