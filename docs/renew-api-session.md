# วิธีสร้าง API session ใหม่เมื่อหมดอายุ

ตอนนี้บอตยังไม่มี login หรือ refresh token อัตโนมัติ หาก session หมดอายุ
ต้องล็อกอินในแอป จับ raw API log แล้วสร้าง `session.json` ใหม่
ตอนรันบอตผ่าน API ใช้เพียงไฟล์ session ไม่ต้องเปิด device ค้างไว้

หากยังไม่มี device หรือ emulator ที่พร้อมใช้งาน ให้เริ่มที่
[คู่มือตั้งค่า emulator และติดตั้ง BKK Active จากศูนย์](setup-rooted-emulator.md)

## ต้องใช้เครื่อง root ไหม

ใช้ emulator ตัวเดิมที่ตั้งค่าให้แอปเชื่อถือ CA ของ mitmproxy แล้วจะสะดวกที่สุด
หากการติดตั้ง system CA ใน emulator นั้นต้องใช้ root ให้ใช้ emulator ที่รองรับ root
ไม่จำเป็นต้อง root มือถือจริงเพื่อรันบอตผ่าน API

เงื่อนไขสำคัญคือแอปต้องยอมรับ CA และส่ง traffic ผ่าน proxy ได้
การ root อย่างเดียวไม่ได้รับประกันว่าจะจับ HTTPS ได้ หากแอปมี certificate pinning
ระบบนี้ไม่ได้ข้าม pinning อัตโนมัติ

## ขั้นตอน

รันคำสั่งจากโฟลเดอร์โปรเจกต์ และหยุดบอตหรือ scheduler ของบัญชีนี้ก่อน
เพื่อไม่ให้มีการจองพร้อมกับขั้นตอนเก็บ session ใหม่

1. เชื่อมต่อ device แล้วดู serial:

   ```sh
   adb devices
   ```

2. หากยังไม่ได้ติดตั้งเครื่องมือ capture ให้ติดตั้งครั้งแรก:

   ```sh
   sh tools/setup_api_capture.sh
   ```

   แอปต้องเชื่อถือ CA ของ mitmproxy ด้วย ดูหัวข้อจับ API ใน README
   หาก emulator เดิมตั้งค่าไว้แล้ว ไม่ต้องติดตั้งใหม่ทุกครั้งที่ token หมดอายุ

3. เปิด capture โดยเปลี่ยน `emulator-5556` เป็น serial ของ device:

   ```sh
   python3 open_booking.py --capture-only \
     --serial emulator-5556 \
     --api-host cstd.bangkok.go.th --api-raw
   ```

4. เปิดแอปและล็อกอินใหม่บน device แล้วทำรายการจองและส่งรีวิวที่ต้องการจริง
   ตัว extract ปัจจุบันต้องมี request `POST /reservation/api/booking`
   และ `POST /rating/api/rating` ใน raw log เดียวกัน การล็อกอินอย่างเดียวยังไม่พอ

   **ขั้นตอนนี้มีการจองและส่งรีวิวจริง** โหมด `--capture-only` เพียงเก็บ traffic
   ไม่ได้กดจองให้ และไม่ได้จำลองหรือยกเลิกรายการให้

5. กด Ctrl+C ใน terminal เพื่อหยุด capture และคืนค่า proxy แล้วสร้าง session:

   ```sh
   python3 tools/extract_api_session.py logger/<รอบรัน>/api.jsonl
   ```

   เปลี่ยน `<รอบรัน>` เป็นโฟลเดอร์ capture จริง คำสั่งนี้เขียนทับ `session.json`
   หลังตรวจรูปแบบข้อมูลผ่าน หากต้องการเก็บแยก ใช้:

   ```sh
   python3 tools/extract_api_session.py logger/<รอบรัน>/api.jsonl \
     --output session-new.json
   ```

6. ใช้ไฟล์ใหม่กับคำสั่งบอตเดิมผ่าน `--session session.json`
   หรือ `--session session-new.json` ตามไฟล์ที่สร้าง แล้วเริ่ม scheduler ใหม่

## ข้อจำกัดและการตรวจปัญหา

- HTTP 401/403 หมายถึง API ไม่อนุญาต อาจเกิดจาก session หมดอายุหรือสิทธิ์บัญชี
  ไม่ใช่หลักฐานว่า token หมดอายุเสมอไป
- หาก capture แจ้ง `tls_error` หรือ `http_visible: false` ยังยืนยันการจับ API ไม่ได้
  ให้ตรวจ CA และการเชื่อมต่อ proxy ก่อน extract
- หาก extract แจ้งว่าขาดรายการจอง/รีวิว ให้ตรวจว่าเลือก raw log รอบที่มีทั้งสอง request
  และเปิด `--api-raw` แล้ว
- การ extract สำเร็จยืนยันรูปแบบข้อมูลเท่านั้น ไม่ได้ตรวจว่า token ยังใช้กับเซิร์ฟเวอร์ได้
  และยังไม่มีข้อมูลยืนยันอายุ token หรือวิธี refresh ของแอป
- `api.jsonl` แบบ raw และ `session.json` มีข้อมูลรับรองและข้อมูลส่วนตัว
  ห้ามแชร์หรือ commit ไฟล์เหล่านี้

แนวทางพัฒนาต่อคือศึกษาคำขอ login/refresh ของแอปก่อน จึงค่อยเพิ่มการต่ออายุ
โดยไม่ต้องทำรายการจองใหม่ ปัจจุบันยังไม่มีฟีเจอร์นี้
