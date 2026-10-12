#!/usr/bin/env python3
"""เปิด BKK Active แล้วเข้าแท็บจองคิว ผ่าน ADB (ใช้ Python standard library)."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PACKAGE = "go.th.bangkok.cstd"
ACTIVITY = f"{PACKAGE}/com.mfessplayground.cstd.MainActivity"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
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
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
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
        coords = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if not coords:
            raise RuntimeError("อ่านตำแหน่งปุ่มไม่ได้")
        x1, y1, x2, y2 = map(int, coords.groups())
        run("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))

    def dismiss_dialog(root):
        for node in root.iter("node"):
            if (node.get("package") == PACKAGE
                    and "ตกลง" in (node.get("text"), node.get("content-desc"))
                    and node.get("clickable") == "true"
                    and node.get("enabled") == "true"):
                print("พบ dialog: กด ตกลง…", flush=True)
                tap(node)
                return True
        return False

    if run("get-state").strip() != "device":
        raise RuntimeError(f"อุปกรณ์ {args.serial} ยังไม่พร้อม")
    if not run("shell", "pm", "path", PACKAGE).strip().startswith("package:"):
        raise RuntimeError("ยังไม่ได้ติดตั้ง BKK Active")

    print(f"เปิด BKK Active บน {args.serial}…", flush=True)
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
            print("กดเข้า จองคิว…", flush=True)
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
        node = booking_tab(root)
        booking_page = any(item.get("package") == PACKAGE
                           and item.get("text") == "การจองของคุณ"
                           for item in root.iter("node"))
        if booking_page or (node is not None and node.get("selected") == "true"):
            print("สำเร็จ: เข้าหน้าจองคิวแล้ว")
            return
        time.sleep(1)
    raise RuntimeError("กดแล้ว แต่ยังยืนยันไม่ได้ว่าเข้าแท็บจองคิวสำเร็จ ตรวจหน้าจอแอป")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, ET.ParseError) as error:
        print(f"ผิดพลาด: {error}", file=sys.stderr)
        sys.exit(1)
