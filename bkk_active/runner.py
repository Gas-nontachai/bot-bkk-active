"""Orchestrate the booking steps in order."""
from copy import copy
from .device import AndroidDevice
from .flows.launch import launch
from .flows.booking import open_booking
from .flows.center import search_center
from .flows.activity import select_activity
from .flows.courts import CourtProgress, choose_court_slot
from .flows.submit import select_slot
from .logging_setup import status
from .config import PACKAGE
from .errors import AppBusy


def enter_courts(device, config):
    launch(device, config)
    root = open_booking(device, config)
    if not search_center(device, config, root):
        return "membership_required"
    if not select_activity(device, config):
        return "activity_not_found"
    return None


def run_flow(config):
    device = AndroidDevice(config.serial, ui_backend=getattr(config, "ui_backend", "bridge"))
    entered = False
    for target in getattr(config, "booking_dates", (config.date,)):
        booking = copy(config)
        booking.date = target
        booking.court_progress = CourtProgress()
        status("ตรวจเวลาว่างวันที่ %s", target.isoformat())
        restarts, reopen = 0, not entered
        while True:
            try:
                if reopen:
                    outcome = enter_courts(device, booking)
                    if outcome is not None:
                        return outcome
                    entered = True
                    reopen = False
                choice = choose_court_slot(device, booking)
                break
            except AppBusy:
                if restarts >= 3:
                    raise RuntimeError("พบหน้ารอซ้ำหลังเปิดแอปใหม่ครบ 3 ครั้ง จบรอบ")
                restarts += 1
                status("พบหน้ารอ — เปิดแอปใหม่ครั้งที่ %d/3 แล้วตรวจต่อวันที่ %s สนาม %d",
                       restarts, target.isoformat(), min(booking.court_progress.next_court, 7))
                device.run("shell", "am", "force-stop", PACKAGE)
                entered = False
                reopen = True
        if choice is not None:
            number, slot = choice
            select_slot(device, booking, number, slot)
            return "completed"
    return "no_available_slot"
