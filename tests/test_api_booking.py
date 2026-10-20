from datetime import date
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bkk_active.api_booking import (
    BASE,
    BookingApi,
    choose_slot,
    extract_session,
    load_session,
    run_api_booking,
    save_session,
)


class ApiBookingTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(session="session.json", center="ศูนย์กีฬาเบญจกิติ",
                                    date=date(2026, 10, 21), start_minute=420, end_minute=480, book=False)
        self.slot = {"ID": "slot-7", "START_TIME": "07:00:00", "END_TIME": "08:00:00",
                     "IS_FULL": False, "REMAINING": 1}
        self.confirmation = {"is_available": True, "booking_header": {
            "booking_date": {"value": "21/10/2569"}, "booking_time": {"value": "07:00 น."},
            "price": {"value": "ไม่มี"}}, "booking_detail": {
                "booking_title": {"value": "สนามแบดมินตัน แบดมินตัน สนาม 1"}}}
        self.booked = {"is_book": True, "booking_data": {"BOOKING_STATUS": "CONFIRMED",
                       "BOOKING_DATE": "2026-10-21", "SLOT_ID": "slot-7"}}

    @staticmethod
    def sample_session():
        return {
            "booking_bearer_token": "Bearer booking-token",
            "review_bearer_token": "Bearer review-token",
            "booker_id": "booker",
            "rating_payload": {
                "TYPE_RATING": "BOOKING",
                "SCORE": 5,
                "COMMENT": "",
                "CARD_ID": "card",
            },
        }

    def setup_api(self):
        api = Mock()
        api.items.side_effect = [[{"ID": "center", "NAME": self.args.center}],
                                 [{"ID": "activity", "NAME": "สนามแบดมินตัน"}],
                                 [{"ID": "court-1", "NAME": "แบดมินตัน สนาม 1"}]]
        api.bookings.return_value = []
        return api

    def run_with(self, api):
        with patch("bkk_active.api_booking.load_session", return_value=self.sample_session()), \
                patch("bkk_active.api_booking.BookingApi", return_value=api):
            return run_api_booking(self.args)

    def test_preview_never_posts(self):
        api = self.setup_api()
        api.request.return_value = [self.slot]
        self.assertEqual(self.run_with(api)["outcome"], "available")
        api.request.assert_called_once_with("GET", BASE + "/item/court-1/slot",
                                            query={"BOOKING_DATE": "2026-10-21"})

    def test_booking_and_review_complete_once(self):
        self.args.book = True
        api = self.setup_api()
        api.request.side_effect = [[self.slot], self.confirmation, self.booked, {"status": "create success"}]
        result = self.run_with(api)
        self.assertEqual((result["outcome"], result["review"]), ("booked", "submitted"))
        calls = api.request.call_args_list
        self.assertEqual([(c.args[0], c.args[1]) for c in calls], [
            ("GET", BASE + "/item/court-1/slot"), ("POST", BASE + "/booking/preconfirm"),
            ("POST", BASE + "/booking"), ("POST", "/rating/api/rating")])
        self.assertEqual(calls[1].args[2], calls[2].args[2])
        self.assertEqual(calls[2].args[2]["SLOT_ID"], "slot-7")

    def test_wrong_confirmation_stops_before_booking(self):
        self.args.book = True
        self.confirmation["booking_header"]["booking_date"]["value"] = "20/10/2569"
        api = self.setup_api()
        api.request.side_effect = [[self.slot], self.confirmation]
        with self.assertRaisesRegex(RuntimeError, "preconfirm"):
            self.run_with(api)
        self.assertEqual(api.request.call_count, 2)

    def test_booking_timeout_is_never_retried(self):
        self.args.book = True
        api = self.setup_api()
        api.request.side_effect = [[self.slot], self.confirmation, TimeoutError()]
        with self.assertRaisesRegex(RuntimeError, "ห้ามส่งซ้ำ"):
            self.run_with(api)
        self.assertEqual(api.request.call_count, 3)

    def test_review_failure_does_not_hide_success_or_rebook(self):
        self.args.book = True
        api = self.setup_api()
        api.request.side_effect = [[self.slot], self.confirmation, self.booked, TimeoutError()]
        result = self.run_with(api)
        self.assertEqual((result["outcome"], result["review"]), ("booked", "failed"))
        self.assertEqual(api.request.call_count, 4)

    def test_existing_booking_blocks_duplicate_but_cancelled_does_not(self):
        for state in ("CONFIRMED", "CANCELLED"):
            api = self.setup_api()
            api.bookings.return_value = [{"BOOKING_DATE": "2026-10-21", "BOOKING_STATUS": state,
                                         "SLOT": {**self.slot, "ITEM_ID": "court-1"}}]
            api.request.return_value = [self.slot]
            result = self.run_with(api)
            self.assertEqual(result["outcome"], "already_booked" if state == "CONFIRMED" else "available")
            self.assertEqual(api.request.call_count, 0 if state == "CONFIRMED" else 1)

    def test_slot_selection_rejects_full_and_overlapping_slots(self):
        bad = [{**self.slot, "IS_FULL": True}, {**self.slot, "REMAINING": 0},
               {**self.slot, "START_TIME": "06:30:00"}, {**self.slot, "END_TIME": "08:30:00"}]
        self.assertIsNone(choose_slot(bad, 420, 480))
        self.assertIs(choose_slot(bad + [self.slot], 420, 480), self.slot)

    @staticmethod
    def raw_log_events():
        return [{
            "event": "request",
            "method": "POST",
            "url": "https://cstd.bangkok.go.th" + path,
            "headers": {
                "Authorization": token,
                "cookie": "private-cookie",
                "user-agent": "private-agent",
            },
            "body": body,
        } for path, token, body in (
            (BASE + "/booking", "Bearer booking-token", {"BOOKER_ID": "booker"}),
            ("/rating/api/rating", "Bearer review-token",
             {"TYPE_RATING": "BOOKING", "SCORE": 5, "COMMENT": "", "CARD_ID": "card"}),
        )]

    def test_extracts_only_required_fields_from_raw_requests(self):
        events = self.raw_log_events()
        with tempfile.TemporaryDirectory() as folder:
            raw_path = Path(folder) / "api.jsonl"
            raw_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            session = extract_session(raw_path)
            self.assertEqual(set(session), set(self.sample_session()))
            self.assertEqual(session["booking_bearer_token"], "Bearer booking-token")
            self.assertEqual(session["review_bearer_token"], "Bearer review-token")
            self.assertNotIn("cookie", json.dumps(session))
            self.assertNotIn("user-agent", json.dumps(session))

    def test_saved_session_is_private_and_loadable(self):
        with tempfile.TemporaryDirectory() as folder:
            raw_path = Path(folder) / "api.jsonl"
            session_path = Path(folder) / "session.json"
            raw_path.write_text(
                "\n".join(json.dumps(event) for event in self.raw_log_events()),
                encoding="utf-8",
            )
            save_session(raw_path, session_path)
            self.assertEqual(load_session(session_path), extract_session(raw_path))
            self.assertEqual(os.stat(session_path).st_mode & 0o777, 0o600)
            self.assertEqual(set(json.loads(session_path.read_text(encoding="utf-8"))),
                             set(self.sample_session()))

    def test_load_session_rejects_extra_fields_without_echoing_secrets(self):
        session = self.sample_session()
        session["extra"] = "must not be accepted"
        session["booking_bearer_token"] = "Bearer secret-booking-token"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.json"
            path.write_text(json.dumps(session), encoding="utf-8")
            with self.assertRaises(RuntimeError) as error:
                load_session(path)
            self.assertNotIn("secret", str(error.exception))
            self.assertNotIn("must not be accepted", str(error.exception))

    def test_load_session_rejects_redacted_token(self):
        session = self.sample_session()
        session["booking_bearer_token"] = "Bearer [REDACTED]"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.json"
            path.write_text(json.dumps(session), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Bearer Token"):
                load_session(path)

    def test_booking_api_uses_only_the_supplied_bearer_token(self):
        api = BookingApi("Bearer booking-token")
        self.assertEqual(api.headers, {"authorization": "Bearer booking-token"})

    def test_expired_session_reports_no_secrets_and_closes_connection(self):
        connection = Mock()
        connection.getresponse.return_value.status = 401
        connection.getresponse.return_value.read.return_value = b'{"token":"private"}'
        with patch("bkk_active.api_booking.http.client.HTTPSConnection", return_value=connection):
            with self.assertLogs("bkk-active", level="INFO") as logs:
                with self.assertRaisesRegex(RuntimeError, "session") as error:
                    BookingApi("Bearer private-token").request("GET", BASE + "/item/active")
        self.assertNotIn("private", str(error.exception))
        self.assertNotIn("private-token", "\n".join(logs.output))
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
