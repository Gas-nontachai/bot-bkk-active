"""Read-only mitmproxy addon. No traffic or authentication is modified."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkk_active.api_events import ApiEvents


class ApiCaptureAddon:
    def __init__(self):
        self.events = ApiEvents(os.environ["BKK_API_FOLDER"],
                                os.environ.get("BKK_API_HOSTS", "").split(),
                                os.environ.get("BKK_API_BODIES") == "1",
                                raw=os.environ.get("BKK_API_RAW") == "1")

    def running(self):
        (self.events.folder / ".api-ready").touch()

    def request(self, flow):
        self.events.request(flow)

    def response(self, flow):
        self.events.finished(flow)

    def error(self, flow):
        self.events.finished(flow, failed=True)

    def tls_failed_client(self, data):
        self.events.tls_failed(data, "client")

    def tls_failed_server(self, data):
        self.events.tls_failed(data, "server")


addons = [ApiCaptureAddon()]
