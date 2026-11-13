# BKK Active automation

## โครงสร้างโปรเจกต์

```text
open_booking.py             # จุดเริ่มรัน CLI
bkk_active/
  cli.py                    # รับ arguments และเริ่ม retry
  scheduler.py              # ตั้งเวลา/วันทำงานตามเวลาไทย
  runner.py                 # เรียก flow ตามลำดับ
  config.py                 # package, activity, path และค่าคงที่
  device.py                 # ADB, tap, scroll, wait, screenshot
  android_bridge.py         # อ่าน accessibility UI ผ่านตัวช่วย Android แบบเร็ว
  logging_setup.py          # INFO/ERROR พร้อมเวลาไทย
  run_artifacts.py          # โฟลเดอร์รอบรัน ภาพ/UI และ timeline
  middleware.py             # จับภาพ/log ก่อน–หลังขั้นตอนและเมื่อ error
  metrics.py                # จำนวนการอ่าน UI/กด/ภาพ และเวลาต่อขั้นตอน
  retry.py                  # เริ่มใหม่เมื่อค้นหาศูนย์ไม่พบ
  errors.py                 # ประเภท error ที่ใช้ควบคุม retry
  ui.py                     # อ่านและตรวจข้อความใน UI
  policy.py                 # เลือก 1 ช่องตามแอปและจัดอันดับเวลา
  vision.py                 # หาปุ่มสีส้มจากภาพ
  flows/
    launch.py               # เปิดแอป
    booking.py              # จองคิว → สร้างการจองใหม่
    center.py               # ค้นหาศูนย์กีฬา
    activity.py             # เลือกสนามแบดมินตัน
    courts.py               # เปรียบเทียบสนามและเลือกตัวเลือก
    schedule.py             # เลือกวันที่และหาเวลาว่าง
    submit.py               # เลือกเวลาและ Submit การจอง
    payment.py              # กดชำระภายหลังเมื่อมีหน้าชำระเงิน
    review.py               # ส่ง Review และจบ flow
tools/android-text-input/   # source และ build script ตัวช่วยภาษาไทย
tests/                      # tests ตัวเลือกและการส่งต่อระหว่าง flow
logger/                     # ผลแต่ละรอบรัน (ไม่เข้า git)
```

## การทำงาน

สคริปต์ง่าย ๆ สำหรับเปิด BKK Active บน Android emulator เข้าแท็บ **จองคิว**
กด **ตกลง** หากมี dialog แล้วกด **สร้างการจองใหม่**
จากนั้นพิมพ์ **ศูนย์กีฬาเบญจกิติ** ในช่องค้นหา แล้วกดผลลัพธ์ที่ตรงชื่อ
เมื่อถึงหน้า **เลือกกิจกรรม** จะกด **สนามแบดมินตัน**
ลอง **สนามแบดมินตัน 1–7** ตามลำดับ แล้วเลือกวันจอง **วันนี้หรือพรุ่งนี้** ตามเวลาไทย
ในหน้าเวลา จะเลือกช่องสถานะ **ว่าง** แรกที่พบตามลำดับรายการ โดยไม่จำกัดช่วงเวลา
เลือก **1 ช่องจองตามที่แอปกำหนด** ระยะเวลาไม่จำเป็นต้องเท่ากับ 60 นาที
เช่น **09:00–10:00**, **18:20–19:30** หรือ **21:00–21:30** เลือกได้หากแอปแสดงว่าว่าง
เมื่อพบช่องว่างจะเลือกทันทีและหยุดหลังจองได้ 1 ช่อง
ปุ่มสนามที่กดได้ไม่ได้บอกว่าสนามว่าง ต้องตรวจสถานะบนหน้าเวลาเท่านั้น
หลังเลือกเวลา สคริปต์จะตรวจวัน สนาม และเวลาในหน้ายืนยัน แล้วกดปุ่มสีส้มด้านล่างเพื่อ Submit
หาปุ่มจากสีและรูปทรงบนภาพหน้าจอ จึงใช้ได้เมื่อข้อความบนปุ่มเปลี่ยนภาษา
หากทุกสนามไม่มีช่วงที่ตรงเงื่อนไข จะ log ว่าไม่มีแล้วจบ
หากไม่พบสนามแบดมินตันบนหน้ากิจกรรม จะ log แล้วจบ
หากค้นหาศูนย์แล้วไม่พบ จะปิดแอป รอ 2 วินาที แล้วเริ่ม flow ใหม่
retry ได้อีก **3 ครั้ง** รวมรอบแรกเป็น **4 รอบ** หากยังไม่พบจะ log แล้วจบ
retry เฉพาะกรณีค้นหาศูนย์ไม่พบ ก่อนถึงขั้นเลือกเวลาและ Submit
สคริปต์เปิดแอปใหม่ทุกครั้ง และส่งการจองเมื่อเลือกเวลาได้
หากหลัง Submit ขึ้นหน้า **ชำระเงิน** จะตรวจวัน สนาม และเวลา แล้วกด **ชำระภายหลัง**
ปุ่มนี้ค้นจากข้อความโดยตรง และรอหน้า Booking Review ก่อนทำต่อ
เมื่อถึงหน้า **Booking Review** จะกดปุ่มสีส้ม **Review** ตามค่าที่หน้าแอปมีอยู่แล้ว
แล้วจบ flow หลังออกจากหน้ารีวิวหรือได้รับข้อความตอบรับ
แต่ละรอบรันสร้าง `logger/<timestamp>/` ตามเวลาไทย และเก็บ:

```text
logger/2026-10-12_23-00-00_123456/
  run.log           # แต่ละเวลาทำอะไร รวม error และ traceback
  screenshots/      # ภาพ PNG ตามลำดับ เวลา ขั้นตอน และหมายเลข retry
  ui/               # XML ของหน้าจอ ใช้แก้ selector/ตำแหน่งปุ่ม
  timeline.jsonl    # เวลา ขั้นตอน retry และ path ภาพ/XML ที่จับคู่กัน
  summary.json      # เวลารวม ผลจบ จำนวนคำสั่ง/ภาพ และเวลาของแต่ละขั้นตอน
```

ค่าเริ่มต้นเป็น **โหมดเร็ว** เก็บ XML เมื่อหน้าจอเปลี่ยน
เก็บภาพเฉพาะผลค้นหา ก่อนกดในขั้นตอน Submit/Review ผลหลังจอง/รีวิว และ error
การกดปุ่มทั่วไปและการ polling ไม่ต้องรอ screenshot ก่อนทุกครั้ง
การ retry ทั้ง 4 รอบอยู่ในโฟลเดอร์ timestamp เดียวกัน ภาพระบุ `attempt-01` ถึง `attempt-04`
ภาพหน้าจอที่เหมือนเดิมในขั้นตอนเดียวกันจะไม่ถูกเก็บซ้ำในทุกครั้งที่ polling

แต่ละ flow ใช้ `@flow_step("ชื่อขั้นตอน")` จาก `middleware.py`
middleware บันทึกเริ่ม–จบ ระยะเวลาที่ใช้ และ traceback เมื่อเกิด error
โหมด debug จะจับภาพก่อน/หลังทุกขั้นตอน เมื่อ UI เปลี่ยน และก่อนคำสั่งกด เลื่อน หรือปิดแอป
ขั้นตอนย่อยมีชื่อเช่น `court-list/court-schedule/choose-date` เพื่อไล่เหตุการณ์ได้
การเก็บภาพล้มเหลวจะถูก log เป็น WARNING และไม่ทำให้การกด Submit/Review ถูกเรียกซ้ำ
ถ้ายืนยันผลไม่ได้ จะ log ERROR และหยุดโดยไม่กด Submit ซ้ำ

`summary.json` สรุปเวลารวม ผลจบ จำนวนรอบ retry จำนวนการอ่าน UI/ADB/กด/เลื่อน/จับภาพ
พร้อมเวลาของแต่ละ operation และแต่ละขั้นตอน ใช้เปรียบเทียบรอบรันในอนาคตได้
เวลา operation/ขั้นตอนบางส่วนซ้อนกัน เช่น เวลาอ่าน UI รวมเวลา ADB จึงไม่ควรนำมาบวกเป็นเวลารวม
ใน `timeline.jsonl` รายการที่มีเฉพาะ XML จะมี `screenshot: null`

โหมด debug สำหรับเก็บภาพละเอียด:

```sh
python3 open_booking.py --debug-capture
```

ค่าเริ่มต้นอ่าน UI ผ่าน Android accessibility bridge ซึ่งไม่ต้องรอ idle แบบ `uiautomator dump`
ตัวช่วยเดิมสำหรับป้อนภาษาไทยรองรับการอ่าน UI ด้วย และติดตั้งเฉพาะเมื่อเวอร์ชันไม่ตรง
หาก bridge อ่านไม่ได้ จะ fallback เป็น uiautomator สำหรับรอบนั้นและบันทึกเหตุผลใน log
สามารถเลือกวิธีเดิมเองเพื่อ debug/เปรียบเทียบด้วย:

```sh
python3 open_booking.py --ui-backend uiautomator
```

ใช้ snapshot เดิมในจุดที่ไม่มีการนำทางคั่น
ลดช่วงพัก polling เป็น 0.15 วินาทีและ swipe เป็น 250ms ส่วน Submit ยังตรวจวัน สนาม และเวลาก่อนกด
ภาพยืนยันที่สำคัญยังเก็บแบบรอให้เสร็จ และการกด Submit/Review ยังเกิดเพียงครั้งเดียว
summary แยกเวลาของ `bridge_ui_read`, `legacy_ui_read` และ `bridge_ui_failure` เพื่อดูว่ามี fallback หรือไม่

ต้องมี Python 3, Android SDK Platform Tools และติดตั้ง BKK Active บน emulator
ครั้งแรกสคริปต์จะ build และติดตั้ง APK ตัวช่วยป้อนภาษาไทยจาก source ใน `tools/android-text-input/`
ใช้ Android SDK Build Tools 36.0.0, platform android-36 และ Java จาก Android Studio
ตั้ง `ANDROID_SDK_ROOT` และ `JAVA_HOME` ได้หากติดตั้งไว้ที่อื่น ตัวช่วยไม่มีหน้าแอปและไม่เปลี่ยนคีย์บอร์ด

```sh
python3 open_booking.py
```

## ปล่อยรันตาม Schedule

ทุกวันเวลา 06:00 ตามเวลาไทย:

```sh
python3 open_booking.py --schedule 06:00
```

เฉพาะวันพุธ พฤหัสบดี และศุกร์:

```sh
python3 open_booking.py --schedule 06:00 --days wed,thu,fri
```

ใช้ตัวย่อไทยได้เช่นกัน:

```sh
python3 open_booking.py --schedule 06:00 --days พ,พฤ,ศ
```

วันอื่นใช้ `mon,tue,wed,thu,fri,sat,sun` หรือ `จ,อ,พ,พฤ,ศ,ส,อา`
ค่าเริ่มต้นคือทุกวัน โปรแกรมจะรอรอบถัดไปและทำงานต่อเนื่องจนกด **Ctrl+C**
เปิด terminal, emulator และเครื่องไว้ หากปิดโปรแกรม schedule จะหยุด
ถ้าต้องการกัน Mac sleep ขณะโปรแกรมเปิด สามารถรันด้วย:

```sh
caffeinate -i python3 open_booking.py --schedule 06:00 --days wed,thu,fri
```

แต่ละรอบคำนวณวันจองจากวันที่ทำงานจริงตาม `Asia/Bangkok` และสร้าง `logger/<timestamp>/` ใหม่
ค่าเริ่มต้นตรวจวันนี้ก่อน หากไม่พบเวลาว่างครบทั้ง 7 สนาม จะตรวจพรุ่งนี้ต่อ
หยุดหลังจองได้ 1 ช่อง หากต้องการตรวจเฉพาะพรุ่งนี้ทุกครั้ง ใช้:

```sh
python3 open_booking.py --schedule 06:00 --booking-day tomorrow
```
รอบที่ทำงานอยู่จะไม่ซ้อนกัน หากเกิด error จะเก็บรายละเอียดแล้วรอรอบถัดไป
หากเริ่มโปรแกรมหลังเวลาที่ตั้ง จะรอวันถัดไปที่เลือกไว้
หากเครื่องตื่นช้ากว่าเวลารอบเกิน 5 นาที จะข้ามรอบนั้น โดยไม่ทำย้อนหลัง
โหมด schedule ใช้ร่วมกับ `--date` ไม่ได้

terminal แสดงเฉพาะสถานะ เช่น รอรอบถัดไป กำลังค้นหาศูนย์ กำลังจอง และจบรอบ
log ละเอียดทั้งหมดรวม traceback และภาพยังอยู่ใน `logger/`
เพิ่ม `--verbose` เพื่อดู log ละเอียดใน terminal ด้วย

```sh
python3 open_booking.py --schedule 06:00 --verbose
```

ค่าเริ่มต้นคือ `emulator-5554` หากใช้อุปกรณ์อื่น:

```sh
python3 open_booking.py --serial emulator-5556
```

เปลี่ยนชื่อศูนย์ที่ค้นหาด้วย `--center "ชื่อศูนย์กีฬา"`
ค่าเริ่มต้น `--booking-day both` ตรวจวันนี้ก่อน แล้วพรุ่งนี้ตามเขต `Asia/Bangkok`
เปลี่ยนไปพรุ่งนี้เฉพาะเมื่อวันนี้ไม่พบเวลาว่างครบทั้ง 7 สนาม และหยุดหลังจองได้ 1 ช่อง
เลือกวันเดียวด้วย `--booking-day today` หรือ `--booking-day tomorrow`
หรือระบุ `--date YYYY-MM-DD` สำหรับการรันครั้งเดียว โดยต้องเป็นวันนี้หรือพรุ่งนี้เท่านั้น
เมื่อระบุวันเดียว จะตรวจเฉพาะวันนั้น หากเกิด error จะหยุดตาม flow

```sh
python3 open_booking.py --booking-day today
python3 open_booking.py --booking-day tomorrow
python3 open_booking.py --booking-day both
```
วันที่ต้องมีปุ่มบนแถบวันที่ และสคริปต์ต้องอ่านวัน/เดือนที่เลือกได้ก่อนเลือกเวลา
กำหนดช่วงเวลาที่ต้องการด้วย `--start-time` และ `--end-time`:

```sh
python3 open_booking.py --booking-day both --start-time 18:00 --end-time 21:00
```

เลือกช่องว่างแรกที่เริ่มไม่ก่อน 18:00 และจบไม่หลัง 21:00 เช่น 18:20–19:30 เลือกได้
แต่ 20:30–21:30 ไม่ได้ เลือกเพียง 1 ช่องตามช่วงที่แอปกำหนด ไม่ได้จองเต็ม 18:00–21:00
ไม่ระบุเวลาเท่ากับ 00:00–24:00; ระบุเฉพาะขอบเริ่มหรือขอบจบก็ได้
เวลาต้องเป็น `HH:MM` และเริ่มก่อนจบภายในวันเดียวกัน รองรับ `--end-time 24:00`
ตัวเลือกนี้ใช้กับทั้งวันนี้ พรุ่งนี้ และโหมด schedule ได้

หากพบหน้ารอ “กรุณารอสักครู่ / โปรดอย่าออกจากหน้านี้” เพราะผู้ใช้บริการจำนวนมาก
ระหว่างค้นหาศูนย์หรือดูตาราง สคริปต์จะปิดแอปด้วย `force-stop` แล้วเปิดใหม่
กลับไปตรวจวันที่และสนามที่ค้าง โดยเก็บผลสนามที่ตรวจแล้วไว้ในรอบเดิม
เปิดใหม่ได้สูงสุด 3 ครั้งต่อวันที่ตรวจ หากยังเจอหน้ารอจะจบรอบพร้อม error
หากเจอหน้ารอระหว่างเลือกเวลา ก่อนถึงหน้ายืนยัน จะเปิดใหม่และตรวจสนามเดิมต่อได้
หลังส่งคำสั่ง Submit แล้วจะไม่เปิดใหม่หรือกด Submit ซ้ำ
ความคืบหน้านี้เก็บในหน่วยความจำ หากหยุดโปรแกรมแล้วรันใหม่จะเริ่มตรวจตั้งแต่ต้น
ทุกขั้นตอนบันทึก INFO log พร้อมวันที่และเวลาเขต `Asia/Bangkok` (+0700) ลง `run.log` อัตโนมัติ

### บอตจองผ่าน API โดยตรง

ใช้ Python standard library ไม่ต้องเปิด emulator ขณะเรียก API ก่อนใช้ครั้งแรก
แยกข้อมูล session ที่จำเป็นจาก capture ของบัญชีคุณที่มีการจองและรีวิว
(ต้องใช้ `--api-raw` เพื่อให้ Authorization ไม่ถูกปิดบัง):

```sh
python3 tools/extract_api_session.py \
  logger/<รอบที่มีการจองและรีวิว>/api.jsonl
```

สคริปต์สร้าง `session.json` ซึ่งเก็บเฉพาะ Booking/Review Bearer Token,
`BOOKER_ID` และ Rating Payload พร้อมตั้ง permission ให้เจ้าของอ่าน/เขียนเท่านั้น
raw log เดิมไม่ถูกแก้ไข; ห้ามแชร์ raw log หรือ `session.json`
ถ้าต้องการเก็บไฟล์ session ที่ path อื่น ใช้ `--output /path/to/session.json`
แล้วส่ง path นั้นให้ `--session`

เริ่มด้วยโหมดอ่านเวลาว่าง (ไม่มี POST):

```sh
python3 open_booking_api.py \
  --session session.json \
  --center "ศูนย์กีฬาเบญจกิติ" \
  --date 2026-10-21 \
  --start-time 06:00 \
  --end-time 07:00
```

เพิ่ม `--book` เพื่อจองจริงและส่งรีวิวตามข้อมูลจากรอบต้นแบบ:

```sh
python3 open_booking_api.py \
  --session session.json \
  --center "ศูนย์กีฬาเบญจกิติ" \
  --date 2026-10-21 \
  --start-time 06:00 \
  --end-time 07:00 \
  --book
```

ตัวอย่างแรกเป็น preview และไม่ส่ง POST; `--book` ในตัวอย่างที่สองจึงส่งจองจริง
โหมดจองจริงแสดงช่วงเวลาที่ค้นหา สรุปจำนวนช่องที่ API แจ้งเต็มและเวลาว่างของแต่ละสนาม
โดยแสดงใหม่เมื่อสถานะเปลี่ยน พร้อมสรุปภาษาไทยเมื่อไม่พบช่องที่ผ่านเงื่อนไข
`run.log` ไม่แสดง GET ตรวจเวลาที่สำเร็จซ้ำ ๆ; รายละเอียดคำขอเหล่านี้ยังอยู่ใน `api.jsonl`
ทุกรอบเก็บ request/response ดิบอัตโนมัติใน `logger/<รอบ>/api.jsonl` ไม่ต้องเพิ่ม flag
รวม URL/query, headers (รวม Authorization), payload, HTTP status, response body และ error
ใช้ `flow_id` จับคู่ request/response ของคำขอที่ทำงานพร้อมกัน พร้อม timestamp และ duration
body ที่ไม่ใช่ JSON เก็บเป็น `body_base64` โดยไม่ตัดขนาดข้อมูล
ไฟล์นี้ไม่มีการปิดบัง token หรือข้อมูลส่วนตัว ตั้งสิทธิ์ `0600`; ห้ามแชร์ไฟล์นี้
หากบันทึกไฟล์ไม่สำเร็จ บอตจะแจ้ง error และทำงานต่อเพื่อไม่ให้กระทบผลจอง
เลือกหนึ่งช่องว่างที่อยู่ภายในช่วงเวลาที่ระบุ ไม่ได้จองเต็มช่วงเวลา
บอตค้น ID ศูนย์/กิจกรรม/สนามใหม่จาก API และตรวจรายการจองเดิมของทั้งวัน
หากมีรายการที่ยังไม่ยกเลิกในวันนั้น จะไม่จองเพิ่ม แม้อยู่คนละสนามหรือคนละช่วงเวลา
ตรวจเวลาว่างพร้อมกัน N คำขอสำหรับ N สนาม โดยเริ่ม preconfirm ทันทีที่สนามแรกตอบว่ามีช่องว่าง
ไม่ต้องรอสนามที่เหลือ; ใช้ thread pool จาก standard library และส่งยืนยันทีละคำขอต่อบัญชี
ตรวจ preconfirm ให้วัน เวลา สนามตรงกันและไม่มีค่าบริการ ก่อนส่งยืนยัน
ถ้าสนามไม่ว่างแล้วหรือมีค่าบริการที่ไม่อนุญาต จะลองสนามถัดไป
ถ้า API ยืนยัน `is_book=false` และไม่มี booking data จะถือว่าปฏิเสธและลองสนามถัดไป
ข้อมูล preconfirm อื่นที่ไม่ตรงยังทำให้หยุดเพื่อความปลอดภัย
เพิ่ม `--allow-paid` ร่วมกับ `--book` เพื่ออนุญาตทั้งการจองฟรีและมีค่าบริการ
flag นี้ยกเว้นเฉพาะเงื่อนไขราคาฟรี การตรวจข้อมูลอื่นยังเหมือนเดิม
บอตไม่ชำระเงินให้ ผู้ใช้ต้องชำระเงินเองภายหลัง; log แสดงผลจอง จำนวนเงินเมื่ออ่านได้
และสถานะชำระเงินจาก API (`unknown` หากไม่มีข้อมูลที่รองรับ)
จะแสดงว่าจองสำเร็จเมื่อผลยืนยันสุดท้ายมี `is_book=true`, `BOOKING_STATUS=CONFIRMED`
พร้อมวันที่และ slot ตรงกันเท่านั้น; HTTP 200 จาก preconfirm ไม่ถือว่าจองสำเร็จ
หากส่งยืนยันแล้ว timeout หรือผลไม่ชัดเจน จะอ่านรายการจองจริงเพื่อตรวจวันที่และ slot
หากพบรายการ CONFIRMED ที่ตรงกัน จะรายงานสำเร็จและไม่ส่งจองซ้ำ
โหมดจองหลายสนามพร้อมกันไม่สร้างไฟล์ `pending-booking` เพิ่มที่ root
เมื่อสนามใดจองสำเร็จ จะหยุดค้นหาและส่งคำขอใหม่ แต่คำขอที่ส่งไปแล้วอาจยังรอคำตอบ
หากผลยังไม่ชัดเจน ให้ตรวจรายการจองในแอปก่อนรันซ้ำ เพราะไม่มีไฟล์กันส่งซ้ำหลังปิดโปรแกรม
ไฟล์ pending จากเวอร์ชันเดิมยังถูกตรวจสอบก่อนเริ่มจอง
Scheduler ยังทำงานรอบถัดไป แม้ยังมีสถานะที่ตรวจไม่ได้
Lock ป้องกันบัญชีเดียวกันภายใน process นี้ รวมถึงใช้ session คนละไฟล์
ควรรันเพียง process เดียวต่อบัญชี; ไม่มี lock ข้าม process หรือข้ามเครื่อง
ถ้าส่งรีวิวไม่สำเร็จ ผลยังแสดงว่าจองสำเร็จและไม่ส่งจองซ้ำ
ผลและ log อยู่ใน `logger/<รอบรัน>/`; ตัวบอตไม่พิมพ์หรือคัดลอก token ไป log ใหม่
รองรับการจองวันนี้/พรุ่งนี้เท่านั้น และยังไม่มี login/refresh token อัตโนมัติ
หาก session หมดอายุ ต้องล็อกอินและจับ raw log ใหม่ แล้วสร้าง `session.json` ใหม่
หากยังไม่มี device ที่ root ได้ เริ่มที่ [คู่มือตั้งค่า emulator และติดตั้งแอปจากศูนย์](docs/setup-rooted-emulator.md)

ดูขั้นตอนใน [คู่มือสร้าง session ใหม่](docs/renew-api-session.md)

การค้นหาศูนย์ผ่าน API จะลองซ้ำห่างกัน 500 ms ภายในกรอบ 30 วินาที พบแล้วไปต่อทันที
เมื่อไม่พบชื่อศูนย์ หรือเกิด network error / HTTP 408, 500, 502, 503, 504
HTTP 429 จะรอตาม `Retry-After` (วินาทีหรือ HTTP-date); ถ้าต้องรอเกินกรอบ จะจบรอบนั้น
ชื่อซ้ำ, ข้อมูลผิดรูปแบบ และ authentication error จะหยุดทันที
กลไก retry ค้นหาศูนย์เดิมยังอยู่ ส่วนอ่านกิจกรรม/สนาม/เวลาว่าง/รายการจองและ preconfirm
ลองได้สูงสุด 3 ครั้ง โดยพัก 0.5 และ 1 วินาที (timeout ต่อคำขออ่านสนาม 5 วินาที)
HTTP 429 จะใช้ช่วงพักร่วมกันระหว่างคำขอของรอบนั้น และเคารพ `Retry-After`
หากต้องรอเกินกรอบ 5 วินาที จะไม่ retry คำขอนั้น; ไม่ retry POST ยืนยันจองอัตโนมัติ
Log มี timestamp ระดับ millisecond พร้อม attempt, HTTP status, match count, เหตุผลและเวลาที่ใช้
ใช้ `--schedule 07:00 --booking-day both` เพื่อทำงานทุกวันตามเวลาไทย
Scheduler โหลดและตรวจ session ล่วงหน้า 30 วินาที แล้วใช้ข้อมูลนั้นในรอบรัน
ยังค้น court IDs ใหม่ตอนรัน เพราะไม่มีสัญญาอายุข้อมูลที่รับรองให้ cache ได้อย่างปลอดภัย
HTTP client เดิมเปิด connection แยกต่อคำขอ จึงใช้กับ thread pool ได้โดยไม่แชร์ socket
แม้รอบหนึ่งสำเร็จ ไม่พบสนาม หรือมีข้อผิดพลาด Scheduler จะรอวันถัดไปและคำนวณวันที่จองใหม่

ตรวจประสิทธิภาพรอบ 07:00 จาก `logger/<รอบรัน>/run.log` ด้วย:

```sh
rg 'API performance' logger/<รอบรัน>/run.log
```

แต่ละบรรทัดมี JSON หลัง `API performance` และใช้ `perf_counter()` วัด `elapsed_ms`:

- `execution_started`: เวลา `scheduled_at` ที่ตั้งไว้
- `court_discovery`: `duration_ms` และจำนวน `courts`
- `availability_started`: `concurrent_requests` ควรเท่ากับจำนวนสนามที่ไม่ซ้ำ
- `first_availability_response`, `first_eligible_court`: เวลาจากเริ่มรอบถึงผลแรก
- `first_booking_request`: KPI `ms_after_scheduled` คือเวลาหลัง 07:00 เมื่อใช้ `--schedule 07:00`
- `booking_response`: `latency_ms`, outcome และ error class หากมี
- `execution_finished`: เวลารวม `elapsed_ms`, `retry_count` และ outcome สุดท้าย

เปรียบเทียบ `ms_after_scheduled` ระหว่างรอบที่มีสนามเข้าเงื่อนไข โดยดู retry/error ประกอบ
ค่า `elapsed_ms` ของ `first_booking_request` ไม่จำเป็นต้องรอ availability ของทุกสนามครบ
รอบ preview หรือไม่มีสนามเข้าเงื่อนไขจะไม่มี event ส่งจอง; อย่าใช้ HTTP 200 แทนผล `booked`
หากรันโดยไม่ตั้ง schedule ค่า `ms_after_scheduled` จะเป็น null
ทดสอบโดยไม่เรียก API จริงได้ด้วย `python3 -m unittest discover -s tests -q`

### จับ API ระหว่างรัน

ติดตั้ง mitmproxy แยกภายในโปรเจกต์ (ครั้งแรกต้องมีอินเทอร์เน็ต):

```sh
sh tools/setup_api_capture.sh
python3 open_booking.py --capture-api --booking-day both
```

โหมดนี้เริ่ม proxy บน `127.0.0.1:8080`, เชื่อมอุปกรณ์ด้วย `adb reverse`
และตั้ง Android `http_proxy` ชั่วคราว เมื่อจบรอบหรือกด Ctrl+C จะคืนค่า proxy เดิม
และลบ reverse ที่สร้างไว้ หากพอร์ตชน ให้ระบุ `--api-port 18080`
ใช้ mitmdump ที่ติดตั้งเองได้ผ่าน `MITMDUMP=/path/to/mitmdump`
โหมดปกติที่ไม่ใส่ `--capture-api` ไม่ต้องติดตั้ง mitmproxy

ผลอยู่ในโฟลเดอร์ log รอบเดียวกัน:

- `api.jsonl`: request, response, status code, duration, connection error และ TLS error
- `api-context.json`: ขั้นตอน วันจอง สนาม และรอบ retry ปัจจุบัน
- `api-summary.json`: จำนวนเหตุการณ์ แยก HTTP status และ request ที่ยังไม่จบ

request และ response ใช้ `flow_id` เดียวกัน พร้อม context ณ ตอนส่ง request
จึงยังเทียบกับสนามเดิมได้แม้ response มาถึงหลังเปลี่ยนหน้าจอ
context เป็นการเทียบตามเวลา ไม่ใช่การยืนยันว่า request นั้นเป็นของสนามหรือแอปนั้น
Android proxy เป็นของทั้งอุปกรณ์: ค่าเริ่มต้นบันทึก metadata ของทุก hostname ที่ผ่าน proxy
เมื่อทราบ API hostname แล้วให้กรองด้วย `--api-host` (ระบุซ้ำได้):

```sh
python3 open_booking.py --capture-api --api-host api.example.com
python3 open_booking.py --capture-api --api-host api.example.com --api-bodies
```

`api.example.com` เป็นตัวอย่าง ต้องเปลี่ยนเป็น hostname ที่พบจริง
หากต้องการกดแอปเองโดยไม่รันบอตจอง ใช้ `--capture-only` (เปิด capture ให้ด้วย):

```sh
python3 open_booking.py --capture-only --serial emulator-5556 --api-host cstd.bangkok.go.th --api-bodies
```

เปิดแอปและกดใช้งานเองบนอุปกรณ์ที่ระบุ ผลอยู่ใน `logger/<รอบรัน>/api.jsonl`
เปิด terminal นี้ไว้ แล้วกด Ctrl+C เพื่อหยุดและคืนค่า proxy; ใช้ร่วมกับ `--schedule` ไม่ได้
อุปกรณ์ยังต้องเชื่อถือ CA ของ mitmproxy ตามคำอธิบายด้านล่าง

ค่าเริ่มต้นไม่เก็บ body, Authorization หรือ Cookie และปิดบังค่า query string
ยกเว้น URL `cstd.bangkok.go.th/reservation/api/reservation/item/<ID>/active` และ `/slot`
ที่เก็บ ID รายการศูนย์/สนาม และ `BOOKING_DATE` รูปแบบ `YYYY-MM-DD` ไว้เพื่อเทียบกับการจอง
`--api-bodies` ต้องระบุ hostname: เก็บเฉพาะ JSON ไม่เกิน 64 KiB พร้อมปิดบัง key
เช่น token, password, email, phone, name และ user ID; form values ถูกปิดบังทั้งหมด
เนื้อหาแบบอื่นจะไม่เก็บ การปิดบัง JSON อาศัยชื่อ key และรูปแบบค่า จึงควรตรวจไฟล์ก่อนแชร์
โหมดปกติไม่สร้างไฟล์ raw flow หรือ HAR ที่มีข้อมูลรับรองเต็ม ๆ

หากต้องการข้อมูลครบโดยไม่ปิดบัง ใช้ `--api-raw` แทน `--api-bodies`:

```sh
python3 open_booking.py --capture-only --serial emulator-5556 --api-host cstd.bangkok.go.th --api-raw
```

โหมดนี้เก็บ URL, query, headers รวม Authorization/Cookie และ body โดยไม่จำกัด 64 KiB
JSON เก็บใน `body`; เนื้อหาอื่นเก็บใน `body_base64` ซึ่งถอดกลับเป็น bytes ได้
ไฟล์ `api.jsonl` มีข้อมูลรับรองและข้อมูลส่วนตัวจริง ให้เก็บไว้ในเครื่องและไม่แชร์หรือ commit
ถ้าไม่ระบุ `--api-host` จะเก็บทุก hostname ที่ผ่าน proxy

HTTPS ต้องให้แอปยอมรับ CA ของ mitmproxy ก่อนจึงเห็น request/response
CA สาธารณะอยู่ที่ `.api-capture/mitmproxy-ca-cert.cer` หลังเปิด proxy ครั้งแรก
Android รุ่นใหม่อาจไม่ยอมรับ CA ที่ติดตั้งผ่าน Settings สำหรับแอปนี้
ดู [วิธีติดตั้ง system CA บน emulator](https://docs.mitmproxy.org/stable/howto/install-system-trusted-ca-android/)
และ [ข้อจำกัด certificate pinning](https://docs.mitmproxy.org/stable/concepts/certificates/)
ระบบนี้ไม่แก้ APK หรือข้าม certificate pinning อัตโนมัติ
หากเห็น `tls_error` หรือ `http_visible: false` แปลว่ายังยืนยันการจับ API ไม่ได้
ถ้าแอปไม่ใช้ Android proxy หรือเรียกผ่านช่องทางอื่น traffic นั้นจะไม่อยู่ในไฟล์นี้

ทดสอบตัวจับ API กับ HTTP/HTTPS จำลองในเครื่องโดยไม่เปิดแอปหรือจองจริง:

```sh
.venv-api/bin/python tools/smoke_api_capture.py
```

หากต้องการสำเนา log ละเอียดอีกไฟล์:

```sh
python3 open_booking.py --verbose | tee booking.log
```

สคริปต์หา `adb` จาก PATH หรือ `~/Library/Android/sdk/platform-tools/adb`
สามารถตั้ง path เองด้วย `ADB=/path/to/adb python3 open_booking.py`

ปุ่มถูกค้นจากชื่อใน UI แล้วคำนวณตำแหน่งกดตามหน้าจอปัจจุบัน
เมื่อเกิดข้อผิดพลาดจะมี ERROR log และ exit code 1
หากสำเร็จหรือค้นหาแล้วไม่พบศูนย์ สคริปต์จบด้วย exit code 0
หากมี dialog ที่มีปุ่ม **ตกลง** สคริปต์จะกดปิดอัตโนมัติ
การปิดข้อความยืนยันตัวตนไม่ได้เปลี่ยนสถานะการยืนยันตัวตนของบัญชี
หากเลือกศูนย์แล้วแอปแจ้งว่าต้องสมัครสมาชิก สคริปต์จะ log เหตุผลและหยุด

## ทดสอบ

```sh
python3 -m unittest discover -s tests -v
```
