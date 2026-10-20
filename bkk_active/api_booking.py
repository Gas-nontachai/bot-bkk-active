"""Book through the observed reservation API using a locally captured session."""
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urlencode, urlsplit

from .logging_setup import LOGGER, status

HOST = "cstd.bangkok.go.th"
BASE = "/reservation/api/reservation"


def _load_session_from_log(path):
    booking, review = None, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if not isinstance(event, dict) or not isinstance(event.get("url"), str):
            continue
        url = urlsplit(event["url"])
        if (event.get("event") != "request" or event.get("method") != "POST"
                or url.scheme != "https" or url.hostname != HOST):
            continue
        if url.path == BASE + "/booking":
            booking = event
        elif url.path == "/rating/api/rating":
            review = event
    if not booking or not review:
        raise RuntimeError("ต้องใช้ raw log ที่มี POST จองและส่งรีวิวสำเร็จครบ")
    for event in (booking, review):
        headers = event.get("headers", {})
        auth = next((value for key, value in (headers.items() if isinstance(headers, dict) else ())
                     if isinstance(key, str) and key.lower() == "authorization"), "")
        if not isinstance(auth, str):
            raise RuntimeError("raw log ไม่มี Authorization ที่ถูกต้อง")
        if not auth.startswith("Bearer ") or "[REDACTED]" in auth:
            raise RuntimeError("raw log ไม่มี Bearer token ที่ใช้ได้ ให้จับ session ใหม่")
    booking_body = booking.get("body", {})
    rating = review.get("body", {})
    if not isinstance(booking_body, dict) or not isinstance(rating, dict):
        raise RuntimeError("raw log ไม่มี body ที่ถูกต้อง")
    booker = booking_body.get("BOOKER_ID")
    if (not isinstance(booker, str) or not booker or booker == "[REDACTED]"
            or rating.get("TYPE_RATING") != "BOOKING" or not rating.get("CARD_ID")
            or rating.get("CARD_ID") == "[REDACTED]"):
        raise RuntimeError("raw log ไม่มีรหัสผู้จอง/บัตรที่ครบถ้วน")
    return booking["headers"], booker, review["headers"], rating


SESSION_KEYS = {
    "booking_bearer_token",
    "review_bearer_token",
    "booker_id",
    "rating_payload",
}


def _validate_session(session):
    if not isinstance(session, dict) or set(session) != SESSION_KEYS:
        raise RuntimeError("รูปแบบ session ไม่ถูกต้อง: ต้องมีเฉพาะข้อมูล Booking/Review ที่กำหนด")
    for key in ("booking_bearer_token", "review_bearer_token"):
        token = session[key]
        if (not isinstance(token, str) or not token.startswith("Bearer ")
                or not token[7:] or token != token.strip()
                or any(char.isspace() for char in token[7:])
                or any(marker in token for marker in ("[REDACTED]", "******"))):
            raise RuntimeError("session ไม่มี Bearer Token ที่ใช้ได้")
    booker = session["booker_id"]
    if (not isinstance(booker, str) or not booker or booker != booker.strip()
            or booker in ("[REDACTED]", "******")):
        raise RuntimeError("session ไม่มี BOOKER_ID ที่ใช้ได้")
    rating = session["rating_payload"]
    if (not isinstance(rating, dict) or rating.get("TYPE_RATING") != "BOOKING"
            or not isinstance(rating.get("CARD_ID"), str) or not rating["CARD_ID"]
            or rating["CARD_ID"] in ("[REDACTED]", "******")):
        raise RuntimeError("session ไม่มี Rating Payload ที่ใช้ได้")
    try:
        json.dumps(rating, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Rating Payload ใน session ไม่ใช่ JSON ที่ถูกต้อง") from error
    return session


def load_session(path):
    try:
        session = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("รูปแบบ session.json ไม่ถูกต้อง") from error
    return _validate_session(session)


def extract_session(raw_log_path):
    booking_headers, booker, review_headers, rating = _load_session_from_log(raw_log_path)
    booking_token = next((value for key, value in booking_headers.items()
                          if isinstance(key, str) and key.lower() == "authorization"), None)
    review_token = next((value for key, value in review_headers.items()
                         if isinstance(key, str) and key.lower() == "authorization"), None)
    return _validate_session({
        "booking_bearer_token": booking_token,
        "review_bearer_token": review_token,
        "booker_id": booker,
        "rating_payload": rating,
    })


def save_session(raw_log_path, session_path):
    session = extract_session(raw_log_path)
    output = Path(session_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".session-", suffix=".tmp", dir=output.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as session_file:
            json.dump(session, session_file, ensure_ascii=False, indent=2)
            session_file.write("\n")
        os.replace(temporary_path, output)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
    return output


class BookingApi:
    def __init__(self, bearer_token):
        self.headers = {"authorization": bearer_token}

    def request(self, method, path, payload=None, query=None):
        connection = http.client.HTTPSConnection(HOST, timeout=20)
        headers = {**self.headers, "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        target = path + ("?" + urlencode(query) if query else "")
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            LOGGER.info("API %s %s: HTTP %d", method, path, response.status)
            if response.status in (401, 403):
                raise RuntimeError("API ไม่อนุญาตให้เข้าถึง: session อาจหมดอายุ ให้จับ raw log ใหม่")
            if response.status == 404 and method == "GET" and path == BASE + "/booking":
                if json.loads(data).get("message") == "Data not found":
                    return []
            if response.status not in (200, 201):
                raise RuntimeError(f"API {method} {path}: HTTP {response.status}")
            return json.loads(data)
        finally:
            connection.close()

    def items(self, parent=None):
        path = BASE + "/item/" + (quote(parent, safe="") + "/active" if parent else "active")
        result = self.request("GET", path, query={"lang": "th"})
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise RuntimeError("รูปแบบรายการศูนย์/สนามจาก API ไม่ถูกต้อง")
        return result

    def bookings(self, booker):
        result = self.request("GET", BASE + "/booking", query={"BOOKER_ID": booker, "lang": "th"})
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise RuntimeError("รูปแบบรายการจองจาก API ไม่ถูกต้อง")
        return result


def named(items, name):
    matches = [item for item in items if item.get("NAME") == name]
    if len(matches) != 1 or not isinstance(matches[0].get("ID"), str):
        raise RuntimeError(f"หารายการชื่อตรงกันเพียงรายการเดียวไม่ได้: {name}")
    return matches[0]


def minute(value):
    if value == "24:00:00":
        return 1440
    parsed = datetime.strptime(value, "%H:%M:%S")
    if parsed.second:
        raise RuntimeError("API ส่งเวลาที่ไม่ได้ลงท้ายด้วยวินาที 00")
    return parsed.hour * 60 + parsed.minute


def choose_slot(slots, begin, end):
    for slot in slots:
        if not isinstance(slot, dict):
            raise RuntimeError("รูปแบบช่องเวลาจาก API ไม่ถูกต้อง")
        if (slot.get("IS_FULL") is False and isinstance(slot.get("REMAINING"), int)
                and slot["REMAINING"] > 0
                and begin <= minute(slot["START_TIME"]) < minute(slot["END_TIME"]) <= end):
            if not isinstance(slot.get("ID"), str) or not slot["ID"]:
                raise RuntimeError("API ส่งช่องเวลาที่ไม่มี ID")
            return slot
    return None


def run_api_booking(args):
    session = load_session(args.session)
    booker = session["booker_id"]
    rating = session["rating_payload"]
    api = BookingApi(session["booking_bearer_token"])
    center = named(api.items(), args.center)
    activity = named(api.items(center["ID"]), "สนามแบดมินตัน")
    courts = [item for item in api.items(activity["ID"])
              if re.fullmatch(r"แบดมินตัน สนาม [1-7]", item.get("NAME", ""))]
    if not courts:
        raise RuntimeError("API ไม่พบสนามแบดมินตัน 1–7")
    day = args.date.isoformat()
    court_ids = {court["ID"] for court in courts}
    for booking in api.bookings(booker):
        slot = booking.get("SLOT", {})
        if (booking.get("BOOKING_DATE") == day and booking.get("BOOKING_STATUS") != "CANCELLED"
                and slot.get("ITEM_ID") in court_ids
                and args.start_minute <= minute(slot["START_TIME"]) < minute(slot["END_TIME"]) <= args.end_minute):
            status("มีรายการจองช่วงนี้อยู่แล้ว จึงไม่ส่งจองเพิ่ม")
            return {"outcome": "already_booked", "date": day}
    for court in courts:
        slots = api.request("GET", BASE + "/item/" + quote(court["ID"], safe="") + "/slot",
                            query={"BOOKING_DATE": day})
        if not isinstance(slots, list):
            raise RuntimeError("รูปแบบช่องเวลาจาก API ไม่ถูกต้อง")
        slot = choose_slot(slots, args.start_minute, args.end_minute)
        if slot is None:
            continue
        interval = slot["START_TIME"][:5] + "–" + slot["END_TIME"][:5]
        status("API พบ %s %s วันที่ %s เวลา %s", args.center, court["NAME"], day, interval)
        payload = {"BOOKING_DATE": day, "SLOT_ID": slot["ID"],
                   "BOOKING_TITLE": activity["NAME"] + " " + court["NAME"], "BOOKER_ID": booker}
        result = {"outcome": "available", "center": args.center, "court": court["NAME"],
                  "date": day, "interval": interval, "court_id": court["ID"], "slot_id": slot["ID"]}
        if not args.book:
            status("โหมดตรวจสอบเท่านั้น ยังไม่ได้ส่ง preconfirm หรือยืนยันจอง")
            return result
        confirmation = api.request("POST", BASE + "/booking/preconfirm", payload, {"lang": "th"})
        if not isinstance(confirmation, dict):
            raise RuntimeError("รูปแบบ preconfirm ไม่ถูกต้อง จึงไม่ส่งยืนยัน")
        header = confirmation.get("booking_header", {})
        if not (confirmation.get("is_available") is True
                and header.get("booking_date", {}).get("value") == args.date.strftime("%d/%m/") + str(args.date.year + 543)
                and header.get("booking_time", {}).get("value") == slot["START_TIME"][:5] + " น."
                and header.get("price", {}).get("value") == "ไม่มี"
                and confirmation.get("booking_detail", {}).get("booking_title", {}).get("value") == payload["BOOKING_TITLE"]):
            raise RuntimeError("ข้อมูล preconfirm ไม่ตรง หรือไม่ใช่การจองฟรี จึงไม่ส่งยืนยัน")
        try:
            booked = api.request("POST", BASE + "/booking", payload, {"lang": "th"})
            if not isinstance(booked, dict):
                raise RuntimeError("รูปแบบผลยืนยันการจองไม่ถูกต้อง")
            data = booked.get("booking_data", {})
            if not (booked.get("is_book") is True and data.get("BOOKING_STATUS") == "CONFIRMED"
                    and data.get("BOOKING_DATE") == day and data.get("SLOT_ID") == slot["ID"]):
                raise RuntimeError("ผลยืนยันการจองไม่ครบหรือไม่ตรง")
        except (OSError, http.client.HTTPException, ValueError, RuntimeError) as error:
            raise RuntimeError("ส่งยืนยันจองแล้วแต่ผลยังไม่ชัดเจน ห้ามส่งซ้ำก่อนตรวจรายการจอง") from error
        result["outcome"] = "booked"
        status("API ยืนยันจองสำเร็จ %s %s", court["NAME"], interval)
        # A review failure must never obscure the confirmed booking or retry it.
        try:
            response = BookingApi(session["review_bearer_token"]).request(
                "POST", "/rating/api/rating", rating
            )
            if not isinstance(response, dict) or response.get("status") != "create success":
                raise RuntimeError("API ยังไม่ยืนยันผลรีวิว")
        except (OSError, http.client.HTTPException, ValueError, RuntimeError) as error:
            result["review"] = "failed"
            LOGGER.warning("จองสำเร็จแล้ว แต่ส่งรีวิวไม่สำเร็จ: %s", error)
        else:
            result["review"] = "submitted"
            status("ส่งรีวิวผ่าน API สำเร็จ")
        return result
    status("ไม่พบช่องว่างในช่วงเวลาที่ระบุครบทั้ง 7 สนาม")
    return {"outcome": "no_available_slot", "date": day}
