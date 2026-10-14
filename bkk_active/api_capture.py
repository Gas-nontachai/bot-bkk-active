"""Start a local proxy and restore Android routing after each run."""
from contextlib import AbstractContextManager
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .api_events import ApiEvents
from .config import PROJECT_ROOT
from .logging_setup import LOGGER, status


class ApiCapture(AbstractContextManager):
    def __init__(self, artifacts, config):
        self.artifacts, self.config = artifacts, config
        self.port = getattr(config, "api_port", 8080)
        self.process = None
        self.reversed = False
        self.proxy_changed = False
        self.previous_proxy = None
        self.adb = os.environ.get("ADB") or shutil.which("adb") or str(
            Path.home() / "Library/Android/sdk/platform-tools/adb")

    def command(self, *args):
        result = subprocess.run([self.adb, "-s", self.config.serial, *args],
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError("ตั้งค่าหรือคืนค่า API proxy ผ่าน ADB ไม่สำเร็จ")
        return result.stdout.strip()

    def __enter__(self):
        configured = os.environ.get("MITMDUMP")
        binary = configured or shutil.which("mitmdump") or str(PROJECT_ROOT / ".venv-api/bin/mitmdump")
        if not Path(binary).is_file():
            raise RuntimeError("ไม่พบ mitmdump: รัน tools/setup_api_capture.sh ก่อนใช้ --capture-api")
        ready = self.artifacts.folder / ".api-ready"
        ready.unlink(missing_ok=True)
        self.artifacts.api_context_file = self.artifacts.folder / "api-context.json"
        self.artifacts.set_api_context(self.config)
        env = os.environ.copy()
        env.update(BKK_API_FOLDER=str(self.artifacts.folder),
                   BKK_API_HOSTS=" ".join(getattr(self.config, "api_host", None) or []),
                   BKK_API_BODIES="1" if getattr(self.config, "api_bodies", False) else "0")
        confdir = PROJECT_ROOT / ".api-capture"
        confdir.mkdir(mode=0o700, exist_ok=True)
        (self.artifacts.folder / "api.jsonl").touch(mode=0o600)
        try:
            if self.command("get-state") != "device":
                raise RuntimeError("อุปกรณ์ยังไม่พร้อมสำหรับจับ API")
            mappings = self.command("reverse", "--list")
            if f"tcp:{self.port}" in mappings.split():
                raise RuntimeError("พอร์ต API capture มี ADB reverse ใช้อยู่แล้ว: เปลี่ยน --api-port")
            self.previous_proxy = self.command("shell", "settings", "get", "global", "http_proxy")
            self.process = subprocess.Popen([
                binary, "--quiet", "--listen-host", "127.0.0.1", "--listen-port", str(self.port),
                "--set", f"confdir={confdir}", "--set", "flow_detail=0",
                "-s", str(PROJECT_ROOT / "tools/api_capture_addon.py"),
            ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 15
            while not ready.exists():
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("เปิด mitmproxy ไม่สำเร็จ: ตรวจ MITMDUMP หรือเปลี่ยน --api-port")
                time.sleep(0.05)
            self.reversed = True
            self.command("reverse", f"tcp:{self.port}", f"tcp:{self.port}")
            # Mark before the write so cleanup also covers an ADB timeout during mutation.
            self.proxy_changed = True
            self.command("shell", "settings", "put", "global", "http_proxy", f"127.0.0.1:{self.port}")
            status("จับ API แล้ว — logger/%s/api.jsonl", self.artifacts.folder.name)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        cleanup_errors = []
        if self.proxy_changed:
            try:
                if self.previous_proxy in ("null", ""):
                    self.command("shell", "settings", "delete", "global", "http_proxy")
                else:
                    self.command("shell", "settings", "put", "global", "http_proxy", self.previous_proxy)
                self.proxy_changed = False
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                cleanup_errors.append("คืนค่า Android http_proxy ไม่สำเร็จ")
        if self.reversed:
            try:
                self.command("reverse", "--remove", f"tcp:{self.port}")
                self.reversed = False
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                cleanup_errors.append("ลบ ADB reverse ไม่สำเร็จ")
        exit_code = self.process.poll() if self.process is not None else None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        report = ApiEvents(self.artifacts.folder).summary()
        report.update(proxy_exit_before_cleanup=exit_code, cleanup_errors=cleanup_errors)
        (self.artifacts.folder / "api-summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.artifacts.api_context_file = None
        if cleanup_errors:
            status("API capture: %s — ตรวจ settings http_proxy และ adb reverse ของอุปกรณ์",
                   "; ".join(cleanup_errors))
        if not report["http_visible"]:
            LOGGER.warning("ยังไม่เห็น HTTP request ผ่าน proxy: ตรวจ certificate และว่าแอปใช้ proxy หรือไม่")
        if exit_code is not None:
            LOGGER.warning("mitmproxy หยุดก่อนจบรอบ: exit=%s ข้อมูล API อาจไม่ครบ", exit_code)

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
