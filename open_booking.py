#!/usr/bin/env python3
"""เปิด BKK Active เข้าสร้างการจอง แล้วค้นหาและเปิดศูนย์กีฬา ผ่าน ADB."""

import argparse
import base64
from datetime import date, datetime
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

PACKAGE = "go.th.bangkok.cstd"
ACTIVITY = f"{PACKAGE}/com.mfessplayground.cstd.MainActivity"
LOGGER = logging.getLogger("bkk-active")
THAI_MONTHS = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")
TIME_RANGE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})(?!\d)")


class BangkokFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, ZoneInfo("Asia/Bangkok")).strftime(
            "%Y-%m-%d %H:%M:%S %z"
        )


def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(BangkokFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


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


def available_slot(root, start_minute=18 * 60, end_minute=21 * 60, exact_interval=None):
    """อ่านสถานะในแถวเดียวกับเวลา ไม่ตีความ 'ไม่ว่าง' ว่าเป็น 'ว่าง'."""
    choices = []
    for node in root.iter("node"):
        rect = bounds(node)
        if node.get("package") != PACKAGE or not rect:
            continue
        labels = ui_labels(node)
        tokens = [part.strip() for label in labels for part in re.split(r"[,\n]", label)]
        free = any(re.search(r"(?:^|[\s,])ว่าง(?:$|[\s,])", token) for token in tokens)
        if not free or any("ไม่ว่าง" in token for token in tokens):
            continue
        ranges = {tuple(map(int, match.groups())) for label in labels
                  for match in TIME_RANGE.finditer(label)}
        if len(ranges) != 1:
            continue
        h1, m1, h2, m2 = next(iter(ranges))
        begin, end = h1 * 60 + m1, h2 * 60 + m2
        if not (0 <= h1 < 24 and 0 <= h2 <= 24 and m1 < 60 and m2 < 60
                and start_minute <= begin < end <= end_minute and end - begin == 60):
            continue
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        choices.append((begin, area, node, f"{h1:02d}:{m1:02d}–{h2:02d}:{m2:02d}"))
    # ใช้แถวที่เล็กที่สุด ไม่ใช้ container ครอบหน้ามากดแทนแถวที่ disabled
    choices = [choice for choice in choices
               if not any(other[2] is not choice[2] and other[2] in tuple(choice[2].iter())
                          for other in choices)
               and choice[2].get("enabled") != "false"]
    if exact_interval is not None:
        choices = [choice for choice in choices if choice[3] == exact_interval]
    if not choices:
        return None
    _, _, node, label = min(choices, key=lambda choice: (choice[0], choice[1]))
    return node, label


def ranked_courts(choices):
    """เรียงเวลาเริ่มใกล้ 18:00 ที่สุดก่อน แล้วใช้หมายเลขสนามตัดสินเมื่อเวลาเท่ากัน."""
    return sorted(choices, key=lambda choice: (int(choice[1][:2]) * 60 + int(choice[1][3:5]), choice[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
    parser.add_argument("--center", default="ศูนย์กีฬาเบญจกิติ", help="ชื่อศูนย์กีฬาที่จะค้นหา")
    parser.add_argument("--date", type=date.fromisoformat,
                        default=datetime.now(ZoneInfo("Asia/Bangkok")).date(),
                        help="วันที่จอง YYYY-MM-DD (ค่าเริ่มต้นคือวันที่รันตามเวลาไทย)")
    args = parser.parse_args()
    adb = os.environ.get("ADB") or shutil.which("adb")
    if not adb:
        adb = str(Path.home() / "Library/Android/sdk/platform-tools/adb")
    if not Path(adb).is_file():
        raise RuntimeError("ไม่พบ adb: ตั้งค่า ADB เป็น path ของ platform-tools/adb")

    def run(*command):
        result = subprocess.run(
            [adb, "-s", args.serial, *command], capture_output=True,
            text=True, timeout=15,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                               or f"ADB {command} จบด้วย exit code {result.returncode}")
        return result.stdout

    def read_ui():
        run("shell", "uiautomator", "dump", "/sdcard/bkk-active-ui.xml")
        return ET.fromstring(run("shell", "cat", "/sdcard/bkk-active-ui.xml"))

    def booking_tab(root):
        return next((node for node in root.iter("node")
                     if node.get("package") == PACKAGE
                     and node.get("content-desc") == "จองคิว"
                     and node.get("clickable") == "true"
                     and node.get("enabled") == "true"), None)

    def tap(node):
        coords = bounds(node)
        if not coords:
            raise RuntimeError("อ่านตำแหน่งปุ่มไม่ได้")
        x1, y1, x2, y2 = coords
        run("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))

    def dismiss_dialog(root):
        for node in root.iter("node"):
            if (node.get("package") == PACKAGE
                    and "ตกลง" in (node.get("text"), node.get("content-desc"))
                    and node.get("clickable") == "true"
                    and node.get("enabled") == "true"):
                LOGGER.info("พบ dialog: กด ตกลง")
                tap(node)
                return True
        return False

    def wait_for(predicate, message):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            root = read_ui()
            if dismiss_dialog(root):
                time.sleep(1)
                continue
            if predicate(root):
                return root
            time.sleep(1)
        raise RuntimeError(message)

    def scroll_down(root, upward=False):
        scrolls = [node for node in root.iter("node")
                   if node.get("package") == PACKAGE
                   and node.get("scrollable") == "true" and bounds(node)]
        if not scrolls:
            return False
        # แถบวันที่เป็นแนวนอน เลือกรายการสนาม/เวลาที่สูงที่สุด
        node = max(scrolls, key=lambda item: bounds(item)[3] - bounds(item)[1])
        x1, y1, x2, y2 = bounds(node)
        if y2 - y1 < x2 - x1:
            return False
        x = (x1 + x2) // 2
        height = y2 - y1
        begin, end = y2 - height // 10, y1 + height // 5
        if upward:
            begin, end = end, begin
        run("shell", "input", "swipe", str(x), str(begin), str(x), str(end), "450")
        time.sleep(0.5)
        return True

    def signature(root):
        return tuple((node.get("text"), node.get("content-desc"), node.get("bounds"))
                     for node in root.iter("node") if node.get("package") == PACKAGE
                     and bounds(node) and (node.get("text") or node.get("content-desc")))

    def locate_court(number, from_top=False):
        if from_top:
            previous, unchanged = None, 0
            for _ in range(31):
                root = read_ui()
                node = activity_button(root, f"สนามแบดมินตัน {number}")
                if node is not None:
                    return node
                current = signature(root)
                unchanged = unchanged + 1 if current == previous else 0
                if unchanged >= 2 or not scroll_down(root, upward=True):
                    break
                previous = current
            else:
                raise RuntimeError("เลื่อนกลับต้นรายการสนามไม่สำเร็จ")
        previous, unchanged = None, 0
        for attempt in range(31):
            root = read_ui()
            node = activity_button(root, f"สนามแบดมินตัน {number}")
            if node is not None:
                return node
            current = signature(root)
            unchanged = unchanged + 1 if current == previous else 0
            if unchanged >= 2 or not scroll_down(root):
                return None
            previous = current
            LOGGER.info("เลื่อนหาสนามแบดมินตัน %d ครั้งที่ %d", number, attempt + 1)
        raise RuntimeError("เลื่อนหารายชื่อสนามครบ 30 ครั้ง แต่ยังไม่ถึงท้ายรายการ")

    def choose_date(root):
        LOGGER.info("เลือกวันที่ %s ตามเวลาไทย", args.date.isoformat())
        if not selected_date_matches(root, args.date):
            node = activity_button(root, str(args.date.day))
            if node is None:
                raise RuntimeError(f"ไม่พบปุ่มวันที่ {args.date.isoformat()} บนแถบวันที่")
            tap(node)
            root = wait_for(lambda ui: selected_date_matches(ui, args.date),
                            f"ยืนยันวันที่ {args.date.isoformat()} ไม่ได้")
        LOGGER.info("ยืนยันวันที่เลือก: %s", args.date.isoformat())
        return root

    def find_evening_slot(root, exact_interval=None):
        previous, unchanged = None, 0
        for attempt in range(41):
            slot = available_slot(root, exact_interval=exact_interval)
            if slot is not None:
                return slot
            current = signature(root)
            unchanged = unchanged + 1 if current == previous else 0
            if unchanged >= 2 or not scroll_down(root):
                return None
            previous = current
            LOGGER.info("เลื่อนหาเวลาว่าง 18:00–21:00 ครั้งที่ %d", attempt + 1)
            root = read_ui()
        raise RuntimeError("เลื่อนหน้าเวลาครบ 40 ครั้ง แต่ยังไม่ถึงท้ายรายการ")

    def open_court(number, court):
        name = f"สนามแบดมินตัน {number}"
        LOGGER.info("กด %s เพื่อดูเวลาว่าง", name)
        tap(court)
        root = wait_for(lambda ui: "เลือกจองวัน-เวลา" in ui_labels(ui),
                        f"กด {name} แล้ว แต่ยังไม่พบหน้าเลือกจองวัน-เวลา")
        choose_date(root)
        return wait_for(lambda ui: not any(item.get("class") == "android.widget.ProgressBar"
                                           for item in ui.iter("node"))
                        and (any(TIME_RANGE.search(label) for label in ui_labels(ui))
                             or "ไม่พบข้อมูล" in ui_labels(ui)),
                        f"รายการเวลาของ {name} ยังโหลดไม่เสร็จ")

    def back_to_courts():
        LOGGER.info("กลับไปหน้าเลือกสนาม")
        run("shell", "input", "keyevent", "KEYCODE_BACK")
        wait_for(lambda ui: any(re.fullmatch(r"สนามแบดมินตัน [1-7]", label)
                               for label in ui_labels(ui))
                 and "เลือกจองวัน-เวลา" not in ui_labels(ui), "กลับไปหน้าเลือกสนามไม่ได้")

    def select_slot(number, slot):
        node, interval = slot
        LOGGER.info("เลือกสิทธิ์ 1 ชั่วโมง: สนามแบดมินตัน %d วันที่ %s เวลา %s",
                    number, args.date.isoformat(), interval)
        tap(node)
        LOGGER.info("กดเลือกช่วงเวลาแล้ว จบสคริปต์")

    LOGGER.info("เริ่มสคริปต์: อุปกรณ์=%s, ศูนย์=%s, วันที่=%s, เวลา=18:00–21:00",
                args.serial, args.center, args.date.isoformat())
    if run("get-state").strip() != "device":
        raise RuntimeError(f"อุปกรณ์ {args.serial} ยังไม่พร้อม")
    if not run("shell", "pm", "path", PACKAGE).strip().startswith("package:"):
        raise RuntimeError("ยังไม่ได้ติดตั้ง BKK Active")

    LOGGER.info("เปิด BKK Active บน %s", args.serial)
    output = run("shell", "am", "start", "-S", "-W", "-n", ACTIVITY)
    if "Error:" in output or "Exception" in output:
        raise RuntimeError(output.strip())

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        node = booking_tab(root)
        if node is not None:
            LOGGER.info("กดเข้า จองคิว")
            tap(node)
            break
        time.sleep(1)
    else:
        raise RuntimeError("ไม่พบแท็บจองคิวภายในเวลาที่กำหนด ตรวจหน้าจอแอป")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        node = next((item for item in root.iter("node")
                     if item.get("package") == PACKAGE
                     and "สร้างการจองใหม่" in (item.get("text"), item.get("content-desc"))
                     and item.get("clickable") == "true"
                     and item.get("enabled") == "true"), None)
        if node is not None:
            LOGGER.info("กด สร้างการจองใหม่")
            tap(node)
            break
        time.sleep(1)
    else:
        raise RuntimeError("ไม่พบปุ่มสร้างการจองใหม่ ตรวจหน้าจอแอป")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        if any(item.get("package") == PACKAGE
               and item.get("text") == "เลือกศูนย์กีฬา"
               for item in root.iter("node")):
            LOGGER.info("เข้าหน้าเลือกศูนย์กีฬาแล้ว")
            break
        time.sleep(1)
    else:
        raise RuntimeError("กดสร้างการจองใหม่แล้ว แต่ยังไม่พบหน้าเลือกศูนย์กีฬา")

    LOGGER.info("ค้นหาช่องค้นหาศูนย์บริการ")
    field = next((item for item in root.iter("node")
                  if item.get("package") == PACKAGE
                  and item.get("class") == "android.widget.EditText"
                  and item.get("enabled") == "true" and bounds(item)), None)
    if field is None:
        raise RuntimeError("ไม่พบช่องค้นหาศูนย์บริการ")
    tap(field)
    helper_dir = Path(__file__).resolve().parent / "android-text-input"
    apk = helper_dir / ".build/text-input.apk"
    if not apk.exists():
        LOGGER.info("สร้างตัวช่วยป้อนข้อความภาษาไทย")
        result = subprocess.run(["sh", str(helper_dir / "build.sh")],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(f"สร้างตัวช่วยไม่ได้: {result.stderr.strip()}")
    LOGGER.info("ติดตั้งตัวช่วยป้อนข้อความบน %s", args.serial)
    run("install", "-r", str(apk))
    LOGGER.info("พิมพ์ค้นหา: %s", args.center)
    encoded = base64.b64encode(args.center.encode("utf-8")).decode("ascii")
    output = run("shell", "am", "instrument", "-w", "-e", "text64", encoded,
                 "local.bkkactive.textinput/local.bkkactive.textinput.TextInput")
    if "TEXT_SET_OK" not in output:
        raise RuntimeError(f"ป้อนชื่อศูนย์ไม่ได้: {output.strip()}")
    root = read_ui()
    if not any(item.get("class") == "android.widget.EditText"
               and item.get("text") == args.center for item in root.iter("node")):
        raise RuntimeError("ข้อความในช่องค้นหาไม่ตรงกับชื่อศูนย์")
    run("shell", "input", "keyevent", "KEYCODE_BACK")
    deadline = time.monotonic() + 15
    previous_results = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        node = next((item for item in root.iter("node")
                     if item.get("package") == PACKAGE
                     and args.center in (item.get("text"), item.get("content-desc"))
                     and item.get("class") != "android.widget.EditText"
                     and item.get("clickable") == "true"
                     and item.get("enabled") == "true" and bounds(item)), None)
        if node is not None:
            LOGGER.info("พบ %s: กดเข้าไป", args.center)
            tap(node)
            break
        labels = tuple(item.get("text") or item.get("content-desc")
                       for item in root.iter("node") if item.get("package") == PACKAGE
                       and (item.get("text") or item.get("content-desc")))
        if labels != previous_results:
            stable_since = time.monotonic()
            previous_results = labels
        empty = any(item.get("text") == "ไม่พบข้อมูล" for item in root.iter("node"))
        result_list = next((item for item in root.iter("node")
                            if item.get("package") == PACKAGE
                            and item.get("scrollable") == "true"), None)
        if result_list is not None:
            empty = empty or not any(item.get("text") or item.get("content-desc")
                                     for item in result_list.iter("node"))
        loading = any(item.get("class") == "android.widget.ProgressBar"
                      for item in root.iter("node"))
        if empty and not loading and time.monotonic() - stable_since >= 3:
            LOGGER.info("ไม่มี %s: ค้นหาแล้วไม่พบข้อมูล จบสคริปต์", args.center)
            return
        time.sleep(1)
    else:
        raise RuntimeError("ผลค้นหายังไม่ชัดเจน: ไม่พบศูนย์ที่ตรงชื่อหรือข้อความไม่พบข้อมูล")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        labels = [item.get("text", "") for item in root.iter("node")
                  if item.get("package") == PACKAGE]
        if "ไม่สามารถจองเข้าใช้บริการได้" in labels:
            LOGGER.info("กดเข้าศูนย์แล้ว แต่แอปแจ้งว่าไม่สามารถจองเข้าใช้บริการได้: ต้องสมัครสมาชิกศูนย์นี้ จบสคริปต์")
            return
        if "เลือกกิจกรรม" in labels:
            LOGGER.info("เข้าหน้าเลือกกิจกรรมแล้ว")
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"กด {args.center} แล้ว แต่ยังไม่พบหน้าเลือกกิจกรรม")

    LOGGER.info("ค้นหากิจกรรม สนามแบดมินตัน")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        node = activity_button(root)
        if node is not None:
            LOGGER.info("พบกิจกรรม: กด สนามแบดมินตัน")
            tap(node)
            break
        time.sleep(1)
    else:
        LOGGER.info("ไม่มี สนามแบดมินตัน บนหน้ากิจกรรม จบสคริปต์")
        return

    wait_for(lambda ui: any(re.fullmatch(r"สนามแบดมินตัน [1-7]", label)
                           for label in ui_labels(ui)), "ยังไม่พบหน้าเลือกสนามแบดมินตัน")
    LOGGER.info("เข้าหน้าเลือกสนามแล้ว: จะตรวจเวลาว่างทีละสนาม")
    candidates = []
    for number in range(1, 8):
        name = f"สนามแบดมินตัน {number}"
        court = locate_court(number)
        if court is None:
            LOGGER.info("ไม่มี %s ในรายการ ข้ามไปสนามถัดไป", name)
            continue
        root = open_court(number, court)
        LOGGER.info("ตรวจ %s: ต้องว่าง 1 ชั่วโมง ภายใน 18:00–21:00", name)
        slot = find_evening_slot(root)
        if slot is not None:
            _, interval = slot
            LOGGER.info("พบตัวเลือก: %s เวลา %s", name, interval)
            if interval == "18:00–19:00":
                LOGGER.info("พบเวลาเริ่ม 18:00 ตรงเป้าหมาย เลือกทันที")
                select_slot(number, slot)
                return
            candidates.append((number, interval))
            LOGGER.info("เก็บตัวเลือกไว้ แล้วตรวจสนามอื่นเพื่อหาเวลาที่ใกล้ 18:00 กว่า")
        else:
            LOGGER.info("ไม่มีเวลาว่าง 1 ชั่วโมงช่วง 18:00–21:00 ที่ %s", name)
        back_to_courts()

    for number, interval in ranked_courts(candidates):
        LOGGER.info("ตรวจตัวเลือกที่ใกล้ 18:00 ที่สุดอีกครั้ง: สนาม %d เวลา %s", number, interval)
        court = locate_court(number, from_top=True)
        if court is None:
            LOGGER.info("สนาม %d หายจากรายการ ข้ามตัวเลือก", number)
            continue
        root = open_court(number, court)
        slot = find_evening_slot(root, exact_interval=interval)
        if slot is not None:
            select_slot(number, slot)
            return
        LOGGER.info("สนาม %d เวลา %s ไม่ว่างแล้ว ข้ามไปตัวเลือกถัดไป", number, interval)
        back_to_courts()
    LOGGER.info("ไม่มีตัวเลือกที่ยังว่าง 1 ชั่วโมงช่วง 18:00–21:00 วันที่ %s จบสคริปต์", args.date.isoformat())


if __name__ == "__main__":
    configure_logging()
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, ET.ParseError) as error:
        LOGGER.error("ผิดพลาด: %s", error)
        sys.exit(1)
