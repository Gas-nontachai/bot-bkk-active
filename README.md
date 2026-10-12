# BKK Active automation

สคริปต์ง่าย ๆ สำหรับเปิด BKK Active บน Android emulator เข้าแท็บ **จองคิว**
กด **ตกลง** หากมี dialog แล้วกด **สร้างการจองใหม่**
สคริปต์เปิดแอปใหม่ทุกครั้ง และหยุดที่หน้า **เลือกศูนย์กีฬา** ยังไม่ได้เลือกหรือยืนยันการจอง

ต้องมี Python 3, Android SDK Platform Tools และติดตั้ง BKK Active บน emulator

```sh
python3 open_booking.py
```

ค่าเริ่มต้นคือ `emulator-5554` หากใช้อุปกรณ์อื่น:

```sh
python3 open_booking.py --serial emulator-5556
```

สคริปต์หา `adb` จาก PATH หรือ `~/Library/Android/sdk/platform-tools/adb`
สามารถตั้ง path เองด้วย `ADB=/path/to/adb python3 open_booking.py`

ปุ่มถูกค้นจากชื่อใน UI แล้วคำนวณตำแหน่งกดตามหน้าจอปัจจุบัน
เมื่อไม่พบปุ่มหรือยืนยันหน้าเลือกศูนย์กีฬาไม่ได้ สคริปต์จะจบด้วย exit code 1
หากมี dialog ที่มีปุ่ม **ตกลง** สคริปต์จะกดปิดอัตโนมัติ
การปิดข้อความยืนยันตัวตนไม่ได้เปลี่ยนสถานะการยืนยันตัวตนของบัญชี
