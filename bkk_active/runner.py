"""Orchestrate the booking steps in order."""
from .device import AndroidDevice
from .flows.launch import launch
from .flows.booking import open_booking
from .flows.center import search_center
from .flows.activity import select_activity
from .flows.courts import choose_court_slot
from .flows.submit import select_slot


def run_flow(config):
    device = AndroidDevice(config.serial, ui_backend=getattr(config, "ui_backend", "bridge"))
    launch(device, config)
    root = open_booking(device, config)
    if not search_center(device, config, root):
        return "membership_required"
    if not select_activity(device, config):
        return "activity_not_found"
    choice = choose_court_slot(device, config)
    if choice is not None:
        number, slot = choice
        select_slot(device, config, number, slot)
        return "completed"
    return "no_available_slot"
