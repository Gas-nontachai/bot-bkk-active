"""Errors that control flow retry decisions."""


class CenterNotFound(RuntimeError):
    pass


class AppBusy(RuntimeError):
    """The app displays its blocking high-traffic waiting screen."""


class SlotSelectionBusy(AppBusy):
    """Busy while opening confirmation, before any Submit command was sent."""
