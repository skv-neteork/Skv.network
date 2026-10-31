#!/usr/bin/env python3
"""Host bridge: POST /run {code} -> ops/sandbox_run.py. API cannot run docker itself."""
import json, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RUN = ["/usr/bin/python3", "/root/skv-core/ops/sandbox_run.py"]

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/run":
            self.send_error(404); return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, 200000))
        try:
            req = json.loads(raw or b"{}")
        except Exception:
            self.send_error(400); return
        payload = json.dumps({"code": str(req.get("code") or "")[:100000], "language": "python"}).encode()
        try:
            p = subprocess.run(RUN, input=payload, capture_output=True, timeout=20)
            out = json.loads(p.stdout.decode() or "{}")
        except Exception as e:
            out = {"stdout": "", "stderr": str(e)[:300], "exit_code": 1, "timed_out": False}
        body = {
            "status": "success" if out.get("exit_code") == 0 and not out.get("timed_out") else "error",
            "stdout": out.get("stdout") or "",
            "stderr": out.get("stderr") or "",
            "exit_code": out.get("exit_code"),
        }
        if out.get("busy"):
            body["busy"] = True; body["error"] = out.get("error") or "sandbox busy"
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        return

ThreadingHTTPServer(("172.18.0.1", 8011), H).serve_forever()
