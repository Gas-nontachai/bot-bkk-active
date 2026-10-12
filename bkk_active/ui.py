"""Selectors and checks against Android UI hierarchies."""
import re
from .config import PACKAGE, THAI_MONTHS


def bounds(node):
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def activity_button(root, name="สนามแบดมินตัน"):
    """เลือกการ์ดชื่อตรงกัน เพื่อไม่กดรายการแบดมินตัน รอบเย็น."""
    parents = {child: parent for parent in root.iter() for child in parent}
    for node in root.iter("node"):
        if node.get("package") != PACKAGE:
            continue
        text = node.get("text", "").strip()
        description = node.get("content-desc", "").split(",", 1)[0].strip()
        if name not in (text, description):
            continue
        candidate = node
        while candidate is not None:
            if (candidate.get("clickable") == "true"
                    and candidate.get("enabled") == "true" and bounds(candidate)):
                return candidate
            candidate = parents.get(candidate)
    return None


def ui_labels(root):
    return [value.strip() for node in root.iter("node") if node.get("package") == PACKAGE
            for key in ("text", "content-desc") if (value := node.get(key, ""))]


def selected_date_matches(root, target):
    # หน้าตามภาพแสดงวันและเดือนของวันที่เลือกใต้แถบวันที่
    pattern = re.compile(rf"(?<!\d){target.day}\s+{THAI_MONTHS[target.month - 1]}(?!\S)")
    labels = ui_labels(root)
    return any(pattern.search(label) for label in labels) or bool(pattern.search(" ".join(labels)))


def confirmation_matches(root, target, court_number, interval):
    labels = ui_labels(root)
    if any(title in labels for title in ("เลือกจองวัน-เวลา", "เลือกกิจกรรม", "เลือกศูนย์กีฬา")):
        return False
    if is_payment_page(root) or is_review_page(root):
        return False
    return booking_details_match(root, target, court_number, interval)


def booking_details_match(root, target, court_number, interval):
    text = " ".join(ui_labels(root))
    date_ok = selected_date_matches(root, target) or any(
        re.search(rf"(?<!\d)0?{target.day}[/.-]0?{target.month}[/.-]{year}(?!\d)", text)
        for year in (target.year, target.year + 543))
    court_ok = bool(re.search(rf"สนามแบดมินตัน\s*{court_number}(?!\d)", text)
                    or re.search(rf"badminton(?: court)?[^,\n]*?\b{court_number}\b", text, re.I))
    begin = interval.split("–")[0]
    hour, minute = map(int, begin.split(":"))
    time_ok = bool(re.search(rf"(?<!\d)0?{hour}:{minute:02d}(?!\d)", text))
    return bool(date_ok and court_ok and time_ok)


def payment_later_button(root):
    parents = {child: parent for parent in root.iter() for child in parent}
    names = ("ชำระภายหลัง", "ชำระเงินภายหลัง", "pay later")
    for node in root.iter("node"):
        if node.get("package") != PACKAGE or node.get("enabled") == "false":
            continue
        labels = (node.get("text", "").strip().lower(),
                  node.get("content-desc", "").split(",", 1)[0].strip().lower())
        if not any(label in names for label in labels):
            continue
        candidate = node
        while candidate is not None:
            if candidate.get("enabled") == "false":
                break
            # A full-page container also contains the orange pay-now button.
            if any(label.lower() in ("ชำระเงิน", "pay now") for label in ui_labels(candidate)):
                break
            if candidate.get("clickable") == "true" and bounds(candidate):
                return candidate
            candidate = parents.get(candidate)
    return None


def is_payment_page(root):
    labels = [label.lower() for label in ui_labels(root)]
    return (any(title in labels for title in ("ชำระเงิน", "payment", "payments"))
            and any(name in labels for name in ("ชำระภายหลัง", "ชำระเงินภายหลัง", "pay later")))


def is_review_page(root):
    labels = [label.lower() for label in ui_labels(root)]
    return any(title in label for label in labels for title in (
        "booking review", "รีวิวการจอง", "ประเมินการจอง", "ให้คะแนนการจอง",
        "ประเมินความพึงพอใจ")) or ("review" in labels and "booking rating" in labels)


def booking_tab(root):
    return next((node for node in root.iter("node")
                 if node.get("package") == PACKAGE
                 and node.get("content-desc") == "จองคิว"
                 and node.get("clickable") == "true"
                 and node.get("enabled") == "true"), None)
