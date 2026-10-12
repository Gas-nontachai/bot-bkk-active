#!/usr/bin/env python3
"""เปิด BKK Active เข้าสร้างการจอง แล้วค้นหาและเปิดศูนย์กีฬา ผ่าน ADB."""

import argparse
import base64
from datetime import datetime
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
    parser.add_argument("--center", default="ศูนย์กีฬาเบญจกิติ", help="ชื่อศูนย์กีฬาที่จะค้นหา")
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

    LOGGER.info("เริ่มสคริปต์: อุปกรณ์=%s, ศูนย์=%s", args.serial, args.center)
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

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = read_ui()
        if dismiss_dialog(root):
            time.sleep(1)
            continue
        app_nodes = [item for item in root.iter("node") if item.get("package") == PACKAGE]
        if app_nodes and not any(item.get("text") == "เลือกกิจกรรม" for item in app_nodes):
            LOGGER.info("กดสนามแบดมินตันและออกจากหน้าเลือกกิจกรรมแล้ว จบสคริปต์")
            return
        time.sleep(1)
    raise RuntimeError("กดสนามแบดมินตันแล้ว แต่ยังไม่ออกจากหน้าเลือกกิจกรรม")


if __name__ == "__main__":
    configure_logging()
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, ET.ParseError) as error:
        LOGGER.error("ผิดพลาด: %s", error)
        sys.exit(1)
