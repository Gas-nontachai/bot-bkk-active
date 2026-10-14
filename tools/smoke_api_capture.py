"""Exercise the real proxy against local HTTP/HTTPS servers without booking."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bkk_active.api_events import ApiEvents
from bkk_active.config import PROJECT_ROOT


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok","token":"smoke-secret","court":3}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    folder = PROJECT_ROOT / ".api-capture/smoke"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "api.jsonl").unlink(missing_ok=True)
    (folder / ".api-ready").unlink(missing_ok=True)
    (folder / "api-context.json").write_text(json.dumps({
        "step": "smoke-test", "booking_date": "2026-10-15", "court": 3, "attempt": 1}))
    proxy = None
    servers = []
    with tempfile.TemporaryDirectory() as temporary:
        certificate = Path(temporary) / "server.pem"
        key = Path(temporary) / "server.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(certificate), "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            http_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            servers.append(http_server)
            https_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            servers.append(https_server)
            server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_tls.load_cert_chain(certificate, key)
            https_server.socket = server_tls.wrap_socket(https_server.socket, server_side=True)
            for server in servers:
                threading.Thread(target=server.serve_forever, daemon=True).start()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env = os.environ.copy()
            env.update(BKK_API_FOLDER=str(folder), BKK_API_HOSTS="localhost", BKK_API_BODIES="1")
            proxy = subprocess.Popen([
                str(PROJECT_ROOT / ".venv-api/bin/mitmdump"), "--quiet", "--listen-host", "127.0.0.1",
                "--listen-port", str(port), "--set", f"confdir={PROJECT_ROOT / '.api-capture'}",
                "--set", f"ssl_verify_upstream_trusted_ca={certificate}",
                "-s", str(PROJECT_ROOT / "tools/api_capture_addon.py"),
            ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 15
            while not (folder / ".api-ready").exists():
                if proxy.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Proxy failed to start")
                time.sleep(0.05)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", f"http://localhost:{http_server.server_port}/courts?token=smoke-secret")
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["token"] == "smoke-secret"  # Traffic is unmodified.
            connection.close()
            ca = PROJECT_ROOT / ".api-capture/mitmproxy-ca-cert.pem"
            context = ssl.create_default_context(cafile=str(ca))
            connection = http.client.HTTPSConnection("127.0.0.1", port, timeout=10, context=context)
            connection.set_tunnel("localhost", https_server.server_port)
            connection.request("GET", "/courts")
            response = connection.getresponse()
            assert response.status == 200
            response.read()
            connection.close()
            untrusted = http.client.HTTPSConnection("127.0.0.1", port, timeout=10,
                                                     context=ssl.create_default_context())
            untrusted.set_tunnel("localhost", https_server.server_port)
            try:
                untrusted.request("GET", "/courts")
            except ssl.SSLCertVerificationError:
                pass
            else:
                raise AssertionError("Expected untrusted proxy certificate to fail")
            finally:
                untrusted.close()
            deadline = time.monotonic() + 5
            while ApiEvents(folder).summary()["counts"].get("tls_error", 0) == 0:
                assert time.monotonic() < deadline, "TLS failure hook did not log"
                time.sleep(0.05)
            events = [json.loads(line) for line in (folder / "api.jsonl").read_text().splitlines()]
            assert len(events) == 5, events
            assert {item["event"] for item in events} == {"request", "response", "tls_error"}
            assert "smoke-secret" not in (folder / "api.jsonl").read_text()
            assert all(event["context"]["court"] == 3 for event in events)
            assert ApiEvents(folder).summary()["unfinished_requests"] == 0
            print("Real HTTP + HTTPS proxy smoke test passed: 2 requests, 2 responses, 1 TLS failure; redaction and context verified.")
        finally:
            if proxy is not None:
                proxy.terminate()
                try:
                    proxy.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proxy.kill()
                    proxy.wait(timeout=5)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
