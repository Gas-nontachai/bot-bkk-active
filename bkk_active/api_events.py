"""Privacy-conscious API events; usable without installing mitmproxy."""
from datetime import datetime
import base64
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

REDACTED = "[REDACTED]"
SENSITIVE = re.compile(
    r"token|authorization|cookie|password|passwd|secret|credential|session|api.?key|"
    r"email|phone|mobile|address|name|citizen|national|passport|birth|user.?id|member|account", re.I)
SAFE_HEADERS = {"content-type", "content-length", "retry-after"}


def redact(value):
    if isinstance(value, dict):
        return {key: REDACTED if SENSITIVE.search(str(key)) else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if (re.search(r"\S+@\S+|Bearer\s+|eyJ[a-zA-Z0-9_-]+\.", value, re.I)
                or re.search(r"(?<!\d)\d{9,}(?!\d)", value)):
            return REDACTED
    return value


def safe_url(url):
    parts = urlsplit(url)
    public_item = (parts.hostname == "cstd.bangkok.go.th" and re.fullmatch(
        r"/reservation/api/reservation/item/[0-9a-fA-F-]{1,64}/(?:active|slot)", parts.path))
    path = parts.path if public_item else "/".join(REDACTED if (SENSITIVE.search(segment)
                    or re.fullmatch(r"\d{5,}|[\w-]{24,}", segment)
                    or "@" in segment) else segment for segment in parts.path.split("/"))
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port is not None:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, path,
                      urlencode([(key, value if (public_item and key == "BOOKING_DATE"
                                  and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) else REDACTED)
                                 for key, value in parse_qsl(parts.query, keep_blank_values=True)]), ""))


def message_info(message, include_bodies=False, raw=False):
    headers = {key.lower(): value for key, value in message.headers.items()
               if raw or key.lower() in SAFE_HEADERS}
    info = {"headers": headers, "body_bytes": len(message.raw_content or b"")}
    if raw:
        content = message.content or b""
        try:
            info["body"] = json.loads(content)
        except (ValueError, UnicodeError):
            info["body_base64"] = base64.b64encode(content).decode("ascii")
        return info
    if not include_bodies:
        return info
    content = message.content or b""
    content_type = headers.get("content-type", "").lower()
    if len(content) > 65536:
        info["body_omitted"] = "over_64_kib"
    elif "json" in content_type:
        try:
            info["body"] = redact(json.loads(content))
        except (ValueError, UnicodeError):
            info["body_omitted"] = "invalid_json"
    elif "application/x-www-form-urlencoded" in content_type:
        # Values may be opaque tokens, so omit every form value.
        info["body"] = {key: REDACTED for key, _ in parse_qsl(content.decode("utf-8", "replace"))}
    else:
        info["body_omitted"] = "unsupported_content_type"
    return info


class ApiEvents:
    def __init__(self, folder, hosts=(), include_bodies=False, raw=False):
        self.folder = Path(folder)
        self.hosts = {host.lower() for host in hosts}
        self.include_bodies = include_bodies
        self.raw = raw

    def allowed(self, host):
        return not self.hosts or host.lower() in self.hosts

    def context(self):
        try:
            return json.loads((self.folder / "api-context.json").read_text())
        except (OSError, ValueError):
            return {}

    def write(self, event):
        event["timestamp"] = datetime.now(ZoneInfo("Asia/Bangkok")).isoformat()
        with (self.folder / "api.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False) + "\n")

    def request(self, flow):
        if not self.allowed(flow.request.host):
            return
        context = self.context()
        flow.metadata["bkk_api_context"] = context
        self.write({"event": "request", "flow_id": flow.id, "context": context,
                    "method": flow.request.method,
                    "url": flow.request.pretty_url if self.raw else safe_url(flow.request.pretty_url),
                    **message_info(flow.request, self.include_bodies, self.raw)})

    def finished(self, flow, failed=False):
        if "bkk_api_context" not in flow.metadata:
            return
        end = flow.response.timestamp_end if flow.response is not None else getattr(flow.error, "timestamp", None)
        begin = flow.request.timestamp_start
        event = {"event": "error" if failed else "response", "flow_id": flow.id,
                 "context": flow.metadata["bkk_api_context"],
                 "duration_ms": round((end - begin) * 1000, 2) if end is not None else None}
        if failed:
            event["error"] = "connection_or_protocol_error"
        else:
            event["status_code"] = flow.response.status_code
            event.update(message_info(flow.response, self.include_bodies, self.raw))
        self.write(event)

    def tls_failed(self, data, side):
        host = data.context.server.address[0] if data.context.server.address else ""
        if self.allowed(host):
            self.write({"event": "tls_error", "side": side, "host": host,
                        "context": self.context(), "error": "tls_handshake_failed"})

    def summary(self):
        counts = {}
        pending = set()
        statuses = {}
        try:
            for line in (self.folder / "api.jsonl").read_text().splitlines():
                event = json.loads(line)
                kind = event["event"]
                counts[kind] = counts.get(kind, 0) + 1
                if kind == "request":
                    pending.add(event["flow_id"])
                elif kind in ("response", "error"):
                    pending.discard(event["flow_id"])
                if "status_code" in event:
                    key = str(event["status_code"])
                    statuses[key] = statuses.get(key, 0) + 1
        except FileNotFoundError:
            pass
        return {"counts": counts, "status_codes": statuses,
                "unfinished_requests": len(pending),
                "scope": "proxy traffic; package attribution is unavailable",
                "http_visible": counts.get("request", 0) > 0}
