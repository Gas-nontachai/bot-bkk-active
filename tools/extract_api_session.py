#!/usr/bin/env python3
"""Extract the minimum booking credentials from a raw API capture."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkk_active.api_booking import save_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_log", type=Path, help="api.jsonl raw จากรอบที่จองและรีวิว")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("session.json"),
        help="ไฟล์ session ที่จะสร้าง (ค่าเริ่มต้น: ./session.json)",
    )
    args = parser.parse_args()
    output = save_session(args.raw_log, args.output)
    print(f"บันทึก session ที่ตรวจสอบแล้ว: {output}")
    print("ไฟล์นี้มี Bearer Token และข้อมูลบัญชี ห้ามแชร์หรือ commit")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"สร้าง session ไม่สำเร็จ: {error}", file=sys.stderr)
        sys.exit(1)
