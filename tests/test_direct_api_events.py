from concurrent.futures import ThreadPoolExecutor
import base64
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from bkk_active.api_booking import ApiHttpError, BASE, BookingApi
from bkk_active.api_events import DirectApiEvents


class DirectApiEventsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "api.jsonl"
        self.events = DirectApiEvents(folder.name)
        self.connection = Mock()
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.getheaders.return_value = [("Set-Cookie", "private-cookie")]
        self.response.read.return_value = b'{"NAME":"center","token":"private-response"}'
        patcher = patch("bkk_active.api_booking.http.client.HTTPSConnection",
                        return_value=self.connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = BookingApi("Bearer private-token", events=self.events)

    def read(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_raw_request_response_and_permissions(self):
        payload = {"BOOKER_ID": "private-booker", "CARD_ID": "private-card"}
        self.api.request("POST", BASE + "/booking", payload, {"BOOKER_ID": "private-booker"})
        request, response = self.read()
        self.assertEqual(request["headers"]["authorization"], "Bearer private-token")
        self.assertEqual(request["body"], payload)
        self.assertIn("BOOKER_ID=private-booker", request["url"])
        self.assertEqual(response["body"], {"NAME": "center", "token": "private-response"})
        self.assertEqual(response["headers"], [["Set-Cookie", "private-cookie"]])
        self.assertEqual(request["flow_id"], response["flow_id"])
        self.assertIn("timestamp", request)
        self.assertGreaterEqual(response["duration_ms"], 0)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_http_failure_keeps_response_and_error(self):
        self.response.status = 401
        with self.assertRaises(ApiHttpError):
            self.api.request("GET", BASE + "/item/active")
        request, response, error = self.read()
        self.assertEqual(response["status_code"], 401)
        self.assertEqual(response["body"]["token"], "private-response")
        self.assertEqual(error["flow_id"], request["flow_id"])
        self.assertTrue(error["response_received"])

    def test_non_json_is_preserved_without_changing_parse_error(self):
        data = b"not json\xff" * 10000
        self.response.read.return_value = data
        with self.assertRaises((ValueError, UnicodeError)):
            self.api.request("GET", BASE + "/item/active")
        response = self.read()[1]
        self.assertEqual(base64.b64decode(response["body_base64"]), data)

    def test_network_error_is_recorded_and_connection_closed(self):
        self.connection.request.side_effect = TimeoutError("read timed out")
        with self.assertRaises(TimeoutError):
            self.api.request("GET", BASE + "/item/active")
        request, error = self.read()
        self.assertEqual(error["flow_id"], request["flow_id"])
        self.assertEqual(error["error_class"], "TimeoutError")
        self.assertFalse(error["response_received"])
        self.connection.close.assert_called_once()

    def test_concurrent_events_are_complete_json_lines(self):
        with ThreadPoolExecutor(max_workers=7) as pool:
            list(pool.map(lambda number: self.events.write({"event": "test", "number": number}),
                          range(100)))
        self.assertEqual({event["number"] for event in self.read()}, set(range(100)))

    def test_log_disk_failure_does_not_change_request_result(self):
        with patch.object(Path, "open", side_effect=OSError("disk full")), \
                self.assertLogs("bkk-active", level="ERROR"):
            result = self.api.request("POST", BASE + "/booking", {"BOOKER_ID": "private"})
        self.assertEqual(result["token"], "private-response")
        self.connection.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
