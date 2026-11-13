# เริ่มจากศูนย์: emulator ที่ root ได้ → ติดตั้ง BKK Active → เก็บ session

คู่มือนี้ใช้ Android Studio บน macOS ไม่ต้องมีมือถือ root เดิม
เป้าหมายคือเตรียม emulator สำหรับเก็บ session แล้วส่งต่อให้คนถัดไปทำตามได้
เมื่อได้ `session.json` แล้ว บอต API ไม่ต้องเปิด emulator ค้างไว้

> สถานะ: ตรวจคำสั่งกับโค้ด capture ของ repo และเอกสารผู้ผลิตแล้ว
> ยังไม่ได้ทดสอบติดตั้งใหม่ครบทุกขั้นกับ BKK Active เวอร์ชันปัจจุบัน
> Android image, รุ่นแอป และสถาปัตยกรรม CPU อาจทำให้ผลต่างกัน

## 1. เตรียมเครื่อง

ติดตั้ง [Android Studio](https://developer.android.com/studio) และ Python 3
เปิด Android Studio → SDK Manager แล้วติดตั้ง Android SDK Platform-Tools,
Android Emulator และ Android SDK Command-line Tools (latest)

เปิด terminal ที่โฟลเดอร์ repo แล้วตั้งค่า (ทำใหม่เมื่อเปิด terminal ใหม่):

```sh
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"
adb version
emulator -list-avds
python3 --version
```

หาก SDK อยู่ที่อื่น ให้ใช้ path ที่ SDK Manager แสดง

## 2. สร้าง emulator ที่ใช้ adb root ได้

Android Studio → Device Manager → Create Virtual Device → เลือก Pixel
เลือก **Android 13 / API 33, Google APIs** และตั้งชื่อ `BKK_Session_API_33`
Mac Apple Silicon เลือก `arm64-v8a`; Mac Intel เลือก `x86_64`
หากไม่เห็น image ให้ดูรายการ image เพิ่มเติมในหน้าสร้าง device

**อย่าเลือก Google Play** เพราะ production image ปิด `adb root`
Google APIs มี Google Play services แต่ไม่มี Play Store; จึงติดตั้งแอปด้วย APK ในขั้นถัดไป
เริ่มที่ API 33 เพื่อใช้แนวทาง system CA ในคู่มือนี้ หากแอปต้องการ Android ใหม่กว่า
ต้องตรวจวิธีติดตั้ง CA สำหรับ image นั้นใหม่ ไม่ควรใช้คำสั่งนี้กับทุกเวอร์ชันโดยถือว่าเหมือนกัน

ปิด AVD นี้ก่อนหากเปิดจาก Android Studio แล้ว จากนั้นเปิดผ่าน terminal:

```sh
emulator -avd BKK_Session_API_33 -port 5556 -writable-system -no-snapshot
```

เปิด terminal อีกหน้าต่าง กลับมาที่ repo และตั้ง PATH ตามขั้นที่ 1 แล้วรัน:

```sh
export SERIAL=emulator-5556
adb -s "$SERIAL" wait-for-device
adb -s "$SERIAL" shell getprop sys.boot_completed
adb -s "$SERIAL" root
adb -s "$SERIAL" wait-for-device
adb -s "$SERIAL" shell id
```

รอให้ `sys.boot_completed` เป็น `1` ก่อนทำต่อ และ `id` ต้องมี `uid=0(root)`
ถ้าขึ้น `adbd cannot run as root in production builds` ให้สร้าง AVD ใหม่ด้วย image ที่รองรับ root
ไม่จำเป็นต้องติดตั้ง Magisk สำหรับแนวทางนี้
ถ้าพอร์ต 5556 ถูกใช้อยู่ เลือกพอร์ตคู่ที่ว่างและเปลี่ยน SERIAL ให้ตรง

ทุกครั้งที่จะเก็บ session ให้เปิดด้วยคำสั่ง `-writable-system -no-snapshot` ด้านบน
ไม่ใช้ `-wipe-data` เพราะจะลบแอปและข้อมูลล็อกอินใน AVD

## 3. เตรียม APK และติดตั้ง BKK Active

repo ไม่ได้แจก APK หรือดาวน์โหลดแอปให้อัตโนมัติ
ใช้ APK จากผู้พัฒนา/แหล่งทางการ หรือดึงจากอุปกรณ์ของคุณที่ติดตั้งแอปผ่าน Play Store แล้ว
**เครื่องต้นทางไม่จำเป็นต้อง root** แต่ต้องเปิด USB debugging และอนุญาต ADB
หากไม่มีมือถือ ใช้ AVD อีกตัวที่เป็น Google Play เพื่อติดตั้งจาก Store แล้วดึง APK ได้
AVD นั้นมีไว้เป็นแหล่ง APK ส่วน AVD สำหรับ capture ใช้ตัวที่สร้างในขั้นที่ 2

ดู serial ต้นทางด้วย `adb devices` แล้วรันใน terminal เดิม:

```sh
export SOURCE_SERIAL='ใส่-serial-เครื่องต้นทาง'
mkdir -p .api-capture/apks
adb -s "$SOURCE_SERIAL" shell pm path go.th.bangkok.cstd
```

ต้องเห็นอย่างน้อย `package:/.../base.apk` หากไม่พบ ตรวจว่าติดตั้ง BKK Active แล้ว
ดึง **ทุกไฟล์** ที่ `pm path` รายงาน เพราะแอปจาก Store อาจเป็น split APK:

```sh
adb -s "$SOURCE_SERIAL" shell pm path go.th.bangkok.cstd > .api-capture/apks/package-paths.txt
while IFS= read -r line; do
  apk_path=$(printf '%s' "$line" | tr -d '\r' | sed 's/^package://')
  [ -n "$apk_path" ] || continue
  adb -s "$SOURCE_SERIAL" pull "$apk_path" ".api-capture/apks/$(basename "$apk_path")" || break
done < .api-capture/apks/package-paths.txt
adb -s "$SERIAL" install-multiple .api-capture/apks/*.apk
```

ใช้โฟลเดอร์ APK ว่างสำหรับแต่ละรุ่น/เครื่องต้นทาง อย่าปน split ของคนละรุ่น
ตรวจว่าดึงครบและคำสั่งติดตั้งจบด้วย `Success` ก่อนทำต่อ
ถ้ามี APK เดี่ยวที่เตรียมไว้แล้ว ใช้แทนขั้นดึงไฟล์:

```sh
adb -s "$SERIAL" install /absolute/path/to/bkk-active.apk
```

เปิดแอปจากไอคอน แล้วตรวจ package:

```sh
adb -s "$SERIAL" shell pm path go.th.bangkok.cstd
```

APK ต้องรองรับ CPU และ Android ของ emulator ถ้าขึ้น `INSTALL_FAILED_NO_MATCHING_ABIS`
ให้ใช้ APK ที่รองรับ ABI ของ AVD; split จากมือถือ ARM อาจใช้กับ Intel AVD ไม่ได้
ถ้า `INSTALL_FAILED_MISSING_SPLIT` ให้ดึง split ให้ครบ
ถ้าแอปเปิดไม่ได้/บังคับอัปเดต ต้องแก้ความเข้ากันได้ก่อนเริ่ม capture
การดึง APK ไม่ได้คัดลอกบัญชีหรือ session ต้องล็อกอินบน AVD ใหม่เอง

## 4. ติดตั้งเครื่องมือ capture และสร้าง CA

จากโฟลเดอร์ repo:

```sh
sh tools/setup_api_capture.sh
.venv-api/bin/mitmdump --listen-host 127.0.0.1 --listen-port 8080 --set confdir=.api-capture
```

รอ proxy เปิดแล้วกด Ctrl+C ขั้นนี้สร้าง CA ใน `.api-capture/`
ใช้ CA ของ repo นี้ เพราะ capture ตั้ง `confdir` ที่เดียวกัน ไม่ใช่ `~/.mitmproxy/`
หากพอร์ตไม่ว่าง ให้หยุด proxy เดิมหรือเลือกพอร์ตอื่นสำหรับขั้นสร้าง CA

## 5. ติดตั้ง CA เป็น system certificate

คำสั่งส่วนนี้เปลี่ยน system ของ **AVD ทดสอบที่สร้างไว้เท่านั้น**
ตรวจ SERIAL อีกครั้ง และทำหลังหยุด capture เพราะการ reboot ตัด ADB reverse

```sh
adb -s "$SERIAL" root
adb -s "$SERIAL" wait-for-device
adb -s "$SERIAL" shell avbctl disable-verification
adb -s "$SERIAL" reboot
adb -s "$SERIAL" wait-for-device
```

รอให้ Android บูตเสร็จ แล้วรัน:

```sh
adb -s "$SERIAL" root
adb -s "$SERIAL" wait-for-device
adb -s "$SERIAL" remount
```

ถ้า remount ขอ reboot ให้ reboot รอจนบูตเสร็จ แล้วทำ `root` และ `remount` ซ้ำ
ต้อง remount สำเร็จก่อนคัดลอก CA:

```sh
export CA_HASH=$(openssl x509 -in .api-capture/mitmproxy-ca-cert.pem -subject_hash_old -noout)
cp .api-capture/mitmproxy-ca-cert.pem ".api-capture/$CA_HASH.0"
adb -s "$SERIAL" push ".api-capture/$CA_HASH.0" "/system/etc/security/cacerts/$CA_HASH.0"
adb -s "$SERIAL" shell chmod 644 "/system/etc/security/cacerts/$CA_HASH.0"
adb -s "$SERIAL" reboot
adb -s "$SERIAL" wait-for-device
```

หลังบูตเสร็จ เปิด Settings → Security → Encryption & credentials → Trusted credentials
(ชื่อเมนูอาจต่างกัน) ตรวจว่า **mitmproxy อยู่ในแท็บ System**
ถ้า `Read-only file system` ให้ตรวจว่าเปิดด้วย `-writable-system` และ remount สำเร็จ
ถ้า image นี้ใช้คำสั่งดังกล่าวไม่ได้ ให้หยุดและตรวจเอกสาร image แทนการฝืนทำขั้นถัดไป

## 6. เก็บ session

หยุดบอต/scheduler ของบัญชีนี้ แล้วเปิด capture:

```sh
python3 open_booking.py --capture-only --serial "$SERIAL" \
  --api-host cstd.bangkok.go.th --api-raw
```

เปิด BKK Active ล็อกอิน แล้วดูว่ามี HTTP request ใน capture จริง
root และ system CA ไม่รับประกันว่าแอปจะยอมให้จับ HTTPS หากมี pinning
ถ้าพบ `tls_error` หรือ `http_visible: false` ให้ตรวจ CA/proxy ก่อน
โปรเจกต์ไม่มีระบบข้าม certificate pinning อัตโนมัติ

ทำต่อด้วย [คู่มือสร้าง session ใหม่ ขั้นตอนที่ 4–6](renew-api-session.md#ขั้นตอน)
**extract ปัจจุบันต้องมีการจองและส่งรีวิวจริง** ใน raw log รอบเดียวกัน
ล็อกอินอย่างเดียวยังสร้าง session ไม่ได้ เมื่อเก็บครบ กด Ctrl+C เพื่อคืนค่า proxy
แล้วใช้ path รอบ capture ที่ terminal รายงาน:

```sh
python3 tools/extract_api_session.py logger/<รอบรัน>/api.jsonl
```

คำสั่งนี้เขียนทับ `session.json` หลังตรวจรูปแบบผ่าน ไม่ได้ตรวจ token กับ server
จากนั้นใช้ `--session session.json` กับบอต API ตาม [README](../README.md)
อย่ารันคำสั่งจองเพื่อทดสอบโดยไม่ตั้งใจ เพราะบอตส่งการจองจริง

## ส่งต่องานและแก้ปัญหา

- บันทึกชื่อ AVD, API level, ABI, รุ่นแอป/แหล่ง APK และวันที่ capture ที่ทดสอบสำเร็จ
  ไม่ใส่ token หรือข้อมูลบัญชีในเอกสารส่งต่อ
- `.api-capture/` มี private key ของ CA และ APK; `logger/` มี raw log;
  `session.json` มีข้อมูลรับรอง อย่าแชร์หรือ commit แม้โฟลเดอร์หลักจะถูก gitignore แล้ว
  ถ้าใช้ชื่อ session อื่น ต้องจัดการไม่ให้เข้า git เอง
- ถ้าลบ `.api-capture/` แล้วสร้าง CA ใหม่ ต้องติดตั้ง CA ใหม่ใน AVD ด้วย
- ถ้าหยุด capture แบบบังคับแล้วเน็ตในแอปไม่ทำงาน ตรวจ
  `adb -s "$SERIAL" shell settings get global http_proxy` และ
  `adb -s "$SERIAL" reverse --list` ก่อน
  หากก่อน capture ไม่มี proxy อื่น ให้คืนค่าด้วย
  `adb -s "$SERIAL" shell settings put global http_proxy :0` และ
  `adb -s "$SERIAL" reverse --remove tcp:8080`
  หากเคยใช้ proxy อื่น ให้คืนค่าของเดิมแทน (เปลี่ยนพอร์ตหากใช้ `--api-port`)
- การติดตั้ง helper ภาษาไทย/Android Build Tools ใน README จำเป็นสำหรับ UI bot
  แต่ไม่ต้องใช้สำหรับการเปิดแอปเองใน `--capture-only`

อ้างอิง: [Android AVD](https://developer.android.com/studio/run/managing-avds),
[mitmproxy system CA](https://docs.mitmproxy.org/stable/howto/install-system-trusted-ca-android/)
(เอกสาร mitmproxy ระบุว่าคำสั่ง writable-system สำหรับ API >28 ทดสอบบน API 29/30;
API 33 ในคู่มือนี้ยังต้องยืนยันกับ image ที่เลือกจริง)
