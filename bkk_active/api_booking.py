"""Book through the observed reservation API using a locally captured session."""
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from datetime import datetime
from email.utils import parsedate_to_datetime
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
import time
import threading
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

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


class ApiHttpError(RuntimeError):
    def __init__(self, message, status, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class BookingApi:
    def __init__(self, bearer_token, *, events=None):
        self.headers = {"authorization": bearer_token}
        self.events = events

    def request(self, method, path, payload=None, query=None, *, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        connection = http.client.HTTPSConnection(HOST, timeout=20 if timeout is None else timeout)
        headers = {**self.headers, "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        target = path + ("?" + urlencode(query) if query else "")
        flow_id = uuid4().hex if self.events is not None else None
        started = time.perf_counter()
        response_logged = False
        if self.events is not None:
            self.events.write({"event": "request", "flow_id": flow_id, "method": method,
                               "url": "https://" + HOST + target,
                               "headers": {"Host": HOST, "Accept-Encoding": "identity",
                                           **({"Content-Length": str(len(body))} if body is not None
                                              else {"Content-Length": "0"} if method in ("POST", "PUT", "PATCH") else {}),
                                           **headers},
                               "body": payload, "body_bytes": len(body or b"")})
        try:
            connection.request(method, target, body=body, headers=headers)
            if deadline is None:
                response = connection.getresponse()
                data = response.read()
            else:
                socket = connection.sock
                def remaining_timeout():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("API request deadline exceeded")
                    socket.settimeout(remaining)

                remaining_timeout()
                response = connection.getresponse()
                chunks = []
                while True:
                    remaining_timeout()
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
            if self.events is not None:
                self.events.response(flow_id, response, data,
                                     round((time.perf_counter() - started) * 1000, 3))
                response_logged = True
            LOGGER.info("API %s %s: HTTP %d", method, path, response.status)
            if response.status in (401, 403):
                raise ApiHttpError("API ไม่อนุญาตให้เข้าถึง: session อาจหมดอายุ ให้จับ raw log ใหม่",
                                   response.status)
            if response.status == 404 and method == "GET" and path == BASE + "/booking":
                if json.loads(data).get("message") == "Data not found":
                    return []
            if response.status not in (200, 201):
                raise ApiHttpError(f"API {method} {path}: HTTP {response.status}",
                                   response.status, response.getheader("Retry-After"))
            return json.loads(data)
        except Exception as error:
            if self.events is not None:
                self.events.write({"event": "error", "flow_id": flow_id,
                                   "error_class": type(error).__name__, "error": str(error),
                                   "response_received": response_logged,
                                   "duration_ms": round((time.perf_counter() - started) * 1000, 3)})
            raise
        finally:
            connection.close()

    def items(self, parent=None, *, timeout=None):
        path = BASE + "/item/" + (quote(parent, safe="") + "/active" if parent else "active")
        result = self.request("GET", path, query={"lang": "th"}, timeout=timeout)
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


def find_center(api, name, *, metrics=None):
    started = time.monotonic()
    deadline = started + 30
    attempts = 0
    success = False
    try:
        while (remaining := deadline - time.monotonic()) > 0:
            attempts += 1
            http_status, count, reason = None, None, ""
            delay = 0.5
            try:
                items = api.items(timeout=remaining)
                http_status = 200
                matches = [item for item in items if item.get("NAME") == name]
                count = len(matches)
                if count:
                    center = named(matches, name)
                    success = True
                    return center
                reason = "no_matches"
            except ApiHttpError as error:
                http_status = error.status
                reason = f"http_{http_status}"
                if http_status != 429 and http_status not in (408, 500, 502, 503, 504):
                    raise
                if http_status == 429 and error.retry_after:
                    try:
                        delay = max(delay, float(error.retry_after))
                    except ValueError:
                        try:
                            retry_at = parsedate_to_datetime(error.retry_after).timestamp()
                            delay = max(delay, retry_at - time.time())
                        except (TypeError, ValueError, OverflowError):
                            pass
            except (OSError, http.client.HTTPException):
                reason = "temporary_network_error"
            except (RuntimeError, ValueError):
                reason = "multiple_matches" if count and count > 1 else "invalid_response"
                raise
            finally:
                status("Center search attempt=%d http_status=%s matches=%s reason=%s elapsed=%.3fs",
                       attempts, http_status, count, reason or "found", time.monotonic() - started)
            remaining = deadline - time.monotonic()
            if delay >= remaining:
                break
            if metrics is not None:
                metrics["retries"].append(reason)
            time.sleep(delay)
        raise RuntimeError(f"ค้นหาศูนย์ไม่สำเร็จภายใน 30 วินาที: {name}")
    finally:
        status("Center search result=%s attempts=%d elapsed=%.3fs",
               "success" if success else "failure", attempts, time.monotonic() - started)


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


def booking_amount(value):
    if value == "ไม่มี":
        return "0"
    if isinstance(value, (str, int, float)) and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?(?: บาท)?", str(value)):
        return value
    return None


# Synchronize accounts even when callers use different session files in this process.
_ACCOUNT_GUARD = threading.Lock()
_ACCOUNT_LOCKS = {}
_BOOKED_DATES = set()
_PENDING_BOOKINGS = {}


def _event(metrics, event, **fields):
    status("API performance %s", json.dumps({
        "event": event, "date": metrics["date"], "elapsed_ms": round((time.perf_counter() - metrics["started"]) * 1000, 3),
        **fields,
    }, ensure_ascii=False))


def _wait_rate_limit(metrics, stop=None):
    deadline = time.monotonic() + 5
    while True:
        with metrics["rate_lock"]:
            delay = metrics["retry_at"] - time.monotonic()
        if delay <= 0:
            return
        if delay > deadline - time.monotonic():
            raise ApiHttpError("API rate limit exceeds retry budget", 429)
        if stop is None:
            time.sleep(delay)
        elif stop.wait(delay):
            raise CancelledError()


def _retry(metrics, operation, *args, _stop=None, **kwargs):
    for attempt in range(3):
        if _stop is not None and _stop.is_set():
            raise CancelledError()
        _wait_rate_limit(metrics, _stop)
        try:
            return operation(*args, **kwargs)
        except (OSError, http.client.HTTPException, ApiHttpError) as error:
            if _stop is not None and _stop.is_set():
                raise CancelledError() from None
            if isinstance(error, ApiHttpError) and error.status not in (408, 429, 500, 502, 503, 504):
                raise
            reason = f"http_{error.status}" if isinstance(error, ApiHttpError) else type(error).__name__
            delay = 0.5 * 2 ** attempt
            if isinstance(error, ApiHttpError) and error.retry_after:
                try:
                    delay = max(delay, float(error.retry_after))
                except ValueError:
                    try:
                        delay = max(delay, parsedate_to_datetime(error.retry_after).timestamp() - time.time())
                    except (TypeError, ValueError, OverflowError):
                        pass
            if isinstance(error, ApiHttpError) and error.status == 429:
                with metrics["rate_lock"]:
                    metrics["retry_at"] = max(metrics["retry_at"], time.monotonic() + delay)
            _event(metrics, "request_error", error_class=reason, attempt=attempt + 1)
            if attempt == 2 or delay > 5:
                raise
            metrics["retries"].append(reason)
            if _stop is None:
                time.sleep(delay)
            elif _stop.wait(delay):
                raise CancelledError()


def _confirmed(data, day, slot_id, expected):
    return (isinstance(data, dict) and data.get("BOOKING_STATUS") == "CONFIRMED"
            and data.get("BOOKING_DATE") == day and data.get("SLOT_ID") == slot_id
            and all(data[key] == value for key, value in expected.items() if key in data))


def _reconcile(api, booker, marker, metrics):
    if (not isinstance(marker, dict)
            or any(not isinstance(marker.get(key), str) or not marker[key]
                   for key in ("date", "court_id", "slot_id"))):
        raise RuntimeError("รูปแบบ pending marker ไม่ถูกต้อง ห้ามส่งซ้ำก่อนตรวจรายการจอง")
    bookings = _retry(metrics, api.bookings, booker)
    for booking in bookings:
        slot = booking.get("SLOT") or {}
        if not isinstance(slot, dict):
            raise RuntimeError("รูปแบบรายการจองจาก API ไม่ถูกต้อง")
        if slot.get("ITEM_ID", marker["court_id"]) != marker["court_id"]:
            continue
        slot_id = booking.get("SLOT_ID", slot.get("ID"))
        if booking.get("BOOKING_DATE") != marker["date"] or slot_id != marker["slot_id"]:
            continue
        if _confirmed({**booking, "SLOT_ID": slot_id}, marker["date"], marker["slot_id"],
                      {"BOOKER_ID": booker, "ITEM_ID": marker["court_id"]}):
            return booking
    # An empty listing may be eventually consistent; it cannot prove a POST failed.
    return None


def run_api_booking(args):
    metrics = {"started": time.perf_counter(), "retries": [], "outcome": "error",
               "rate_lock": threading.Lock(), "retry_at": 0, "date": args.date.isoformat()}
    scheduled = getattr(args, "scheduled_at", None)
    _event(metrics, "execution_started", scheduled_at=scheduled.isoformat() if scheduled else None)
    try:
        session = getattr(args, "prepared_session", None) or load_session(args.session)
        booker = session["booker_id"]
        with _ACCOUNT_GUARD:
            lock = _ACCOUNT_LOCKS.setdefault(booker, threading.Lock())
        with lock if args.book else nullcontext():
            key = (booker, args.date.isoformat())
            if key in _BOOKED_DATES:
                result = {"outcome": "already_booked", "date": key[1]}
            else:
                result = _run_api_booking(args, session, metrics)
            if args.book and result["outcome"] in ("booked", "already_booked"):
                _BOOKED_DATES.add(key)
            metrics["outcome"] = result["outcome"]
            return result
    except Exception as error:
        _event(metrics, "execution_error", error_class=type(error).__name__)
        raise
    finally:
        _event(metrics, "execution_finished", outcome=metrics["outcome"], retry_count=len(metrics["retries"]))


def _availability(api, courts, day, metrics):
    pool = ThreadPoolExecutor(max_workers=len(courts))
    futures = {}
    stop = threading.Event()
    _event(metrics, "availability_started", concurrent_requests=len(courts))
    try:
        for court in courts:
            future = pool.submit(_retry, metrics, api.request, "GET",
                                 BASE + "/item/" + quote(court["ID"], safe="") + "/slot",
                                 query={"BOOKING_DATE": day}, timeout=5, _stop=stop)
            futures[future] = court
        first = True
        for future in as_completed(futures):
            if first:
                _event(metrics, "first_availability_response")
                first = False
            try:
                slots = future.result()
            except (OSError, http.client.HTTPException, RuntimeError, ValueError) as error:
                yield futures[future], None, error
            else:
                yield futures[future], slots, None
    finally:
        stop.set()
        for future in futures:
            future.cancel()
        # Running reads have a deadline; booking must not wait for slower courts.
        pool.shutdown(wait=False, cancel_futures=True)


def _run_api_booking(args, session, metrics):
    booker = session["booker_id"]
    api = BookingApi(session["booking_bearer_token"], events=getattr(args, "api_events", None))
    pending = _PENDING_BOOKINGS.get(booker, Path(str(args.session) + ".pending-booking.json"))
    if args.book and pending.exists():
        marker = json.loads(pending.read_text(encoding="utf-8"))
        reconciled = _reconcile(api, booker, marker, metrics)
        if reconciled is None:
            metrics["outcome"] = "confirmation_unknown"
            raise RuntimeError("มีผลยืนยันจองที่ยังไม่ชัดเจน ห้ามส่งซ้ำก่อนตรวจรายการจอง")
        pending.unlink()
        _PENDING_BOOKINGS.pop(booker, None)
        if marker["date"] == args.date.isoformat():
            return {"outcome": "already_booked", "date": marker["date"]}
    discovery_started = time.perf_counter()
    center = find_center(api, args.center, metrics=metrics)
    activity = named(_retry(metrics, api.items, center["ID"], timeout=5), "สนามแบดมินตัน")
    courts = [item for item in _retry(metrics, api.items, activity["ID"], timeout=5)
              if re.fullmatch(r"แบดมินตัน สนาม [1-7]", item.get("NAME", ""))]
    if any(not isinstance(court.get("ID"), str) or not court["ID"] for court in courts):
        raise RuntimeError("API ส่งสนามที่ไม่มี ID")
    courts = list({court["ID"]: court for court in courts}.values())
    _event(metrics, "court_discovery", duration_ms=round((time.perf_counter() - discovery_started) * 1000, 3),
           courts=len(courts))
    if not courts:
        raise RuntimeError("API ไม่พบสนามแบดมินตัน 1–7")
    day = args.date.isoformat()
    for booking in _retry(metrics, api.bookings, booker):
        if booking.get("BOOKING_DATE") == day and booking.get("BOOKING_STATUS") != "CANCELLED":
            status("มีรายการจองวันนี้อยู่แล้ว จึงไม่ส่งจองเพิ่ม")
            return {"outcome": "already_booked", "date": day}
    availability = _availability(api, courts, day, metrics)
    try:
        return _consume_availability(args, session, api, center, activity, availability, metrics)
    finally:
        availability.close()


def _consume_availability(args, session, api, center, activity, availability, metrics):
    day = args.date.isoformat()
    booker, rating = session["booker_id"], session["rating_payload"]
    pending = _PENDING_BOOKINGS.get(booker, Path(str(args.session) + ".pending-booking.json"))
    first_eligible = True
    first_booking = True
    last_error = None
    for court, slots, error in availability:
        if error is not None:
            if isinstance(error, ApiHttpError) and error.status in (401, 403, 429):
                raise error
            last_error = error
            continue
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
            _event(metrics, "first_eligible_court")
            status("โหมดตรวจสอบเท่านั้น ยังไม่ได้ส่ง preconfirm หรือยืนยันจอง")
            return result
        try:
            confirmation = _retry(metrics, api.request, "POST", BASE + "/booking/preconfirm",
                                  payload, {"lang": "th"}, timeout=5)
        except ApiHttpError as error:
            if error.status in (401, 403):
                raise
            last_error = error
            continue
        if not isinstance(confirmation, dict):
            raise RuntimeError("รูปแบบ preconfirm ไม่ถูกต้อง จึงไม่ส่งยืนยัน")
        try:
            header = confirmation.get("booking_header", {})
            price = header.get("price", {}).get("value")
            checks = {
                "availability": confirmation.get("is_available") is True,
                "date": header.get("booking_date", {}).get("value") == args.date.strftime("%d/%m/") + str(args.date.year + 543),
                "time": header.get("booking_time", {}).get("value") == slot["START_TIME"][:5] + " น.",
                "court_title": confirmation.get("booking_detail", {}).get("booking_title", {}).get("value") == payload["BOOKING_TITLE"],
                "free_price": getattr(args, "allow_paid", False) or price == "ไม่มี",
            }
            expected = {**payload, "CENTER_ID": center["ID"], "ITEM_ID": court["ID"]}
            for data in (confirmation, confirmation.get("booking_data", {})):
                checks["identifiers"] = checks.get("identifiers", True) and all(
                    data[key] == value for key, value in expected.items() if key in data
                )
            failed = [key for key, valid in checks.items() if not valid]
        except (AttributeError, TypeError):
            raise RuntimeError("รูปแบบ preconfirm ไม่ถูกต้อง จึงไม่ส่งยืนยัน") from None
        if failed:
            status("Booking result=preconfirm_rejected checks=%s amount=%s payment_status=unknown",
                   ",".join(failed), booking_amount(price))
            if set(failed) <= {"availability", "free_price"}:
                continue
            raise RuntimeError("ข้อมูล preconfirm ไม่ตรง จึงไม่ส่งยืนยัน: " + ",".join(failed))

        if first_eligible:
            _event(metrics, "first_eligible_court")
            first_eligible = False
        _wait_rate_limit(metrics)
        # Persist before POST: a lost response must also block retries after restart.
        try:
            with pending.open("x", encoding="utf-8") as marker:
                json.dump({"date": day, "court_id": court["ID"], "slot_id": slot["ID"]}, marker)
                marker.flush()
                os.fsync(marker.fileno())
        except FileExistsError:
            raise RuntimeError("มีผลยืนยันจองที่ยังไม่ชัดเจน ห้ามส่งซ้ำก่อนตรวจรายการจอง") from None
        _PENDING_BOOKINGS[booker] = pending
        booking_started = time.perf_counter()
        if first_booking:
            scheduled = getattr(args, "scheduled_at", None)
            _event(metrics, "first_booking_request", ms_after_scheduled=(
                round((datetime.now(scheduled.tzinfo) - scheduled).total_seconds() * 1000, 3)
                if scheduled else None))
            first_booking = False
        try:
            booked = api.request("POST", BASE + "/booking", payload, {"lang": "th"}, timeout=20)
            if isinstance(booked, dict) and booked.get("is_book") is False and not booked.get("booking_data"):
                pending.unlink()
                _PENDING_BOOKINGS.pop(booker, None)
                _event(metrics, "booking_response", outcome="rejected",
                       latency_ms=round((time.perf_counter() - booking_started) * 1000, 3))
                continue
            data = booked.get("booking_data") if isinstance(booked, dict) else None
            if not (isinstance(booked, dict) and booked.get("is_book") is True
                    and _confirmed(data, day, slot["ID"], expected)):
                raise RuntimeError("ผลยืนยันการจองไม่ครบหรือไม่ตรง")
        except (OSError, http.client.HTTPException, ValueError, RuntimeError) as error:
            _event(metrics, "booking_response", outcome="unknown", error_class=type(error).__name__,
                   latency_ms=round((time.perf_counter() - booking_started) * 1000, 3))
            metrics["outcome"] = "confirmation_unknown"
            try:
                data = _reconcile(api, booker, {"date": day, "court_id": court["ID"], "slot_id": slot["ID"]}, metrics)
            except (OSError, http.client.HTTPException, ValueError, RuntimeError):
                data = None
            if data is None:
                status("Booking result=confirmation_unknown amount=%s payment_status=unknown", booking_amount(price))
                raise RuntimeError("ส่งยืนยันจองแล้วแต่ผลยังไม่ชัดเจน ห้ามส่งซ้ำก่อนตรวจรายการจอง") from None
            _event(metrics, "booking_reconciled", outcome="booked")
        else:
            _event(metrics, "booking_response", outcome="booked",
                   latency_ms=round((time.perf_counter() - booking_started) * 1000, 3))
        _BOOKED_DATES.add((booker, day))
        try:
            pending.unlink()
        except OSError:
            LOGGER.warning("จองสำเร็จแล้ว แต่ยังลบ pending marker ไม่สำเร็จ")
        else:
            _PENDING_BOOKINGS.pop(booker, None)
        result["outcome"] = "booked"
        # Only log parsed monetary values and known statuses, never raw API text.
        amount = booking_amount(data.get("PRICE", price))
        payment = data.get("PAYMENT_STATUS")
        if payment not in ("PAID", "UNPAID", "PENDING", "NOT_REQUIRED"):
            payment = "unknown"
        result.update(amount=amount, payment_status=payment)
        status("Booking result=booked amount=%s payment_status=%s", amount, payment)
        status("API ยืนยันจองสำเร็จ %s %s", court["NAME"], interval)
        # A review failure must never obscure the confirmed booking or retry it.
        try:
            response = BookingApi(session["review_bearer_token"], events=getattr(args, "api_events", None)).request(
                "POST", "/rating/api/rating", rating
            )
            if not isinstance(response, dict) or response.get("status") != "create success":
                raise RuntimeError("API ยังไม่ยืนยันผลรีวิว")
        except (OSError, http.client.HTTPException, ValueError, RuntimeError):
            result["review"] = "failed"
            LOGGER.warning("จองสำเร็จแล้ว แต่ส่งรีวิวไม่สำเร็จ")
        else:
            result["review"] = "submitted"
            status("ส่งรีวิวผ่าน API สำเร็จ")
        return result
    if last_error is not None:
        raise last_error
    status("ไม่พบช่องว่างที่เข้าเงื่อนไขในช่วงเวลาที่ระบุ")
    return {"outcome": "no_available_slot", "date": day}
