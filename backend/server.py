"""Entry point of the application tier: stdlib HTTP server + static file serving for the frontend tier.

    python -m backend.server --data data/full --port 8000
"""
import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from edu_support import db
from .api import Api
from .services import Services, Clock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.join(ROOT, "frontend")
MAX_BODY = 64 * 1024


def make_handler(api):
    class H(BaseHTTPRequestHandler):
        server_version = "EduSupport/1.0"

        def log_message(self, fmt, *a):
            if os.environ.get("QUIET") != "1":
                sys.stderr.write("%s %s\n" % (self.command, self.path))

        def _send(self, status, payload=None, raw=None, ctype="application/json; charset=utf-8"):
            data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _static(self):
            path = self.path.split("?", 1)[0]
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(FRONT, rel))
            if not (full == FRONT or full.startswith(FRONT + os.sep)) or not os.path.isfile(full):
                if "." not in os.path.basename(rel):  # SPA fallback for client-side routes
                    full = os.path.join(FRONT, "index.html")
                else:
                    return self._send(404, {"error": {"code": "NOT_FOUND", "message": "file not found"}})
            with open(full, "rb") as fh:
                self._send(200, raw=fh.read(), ctype=(mimetypes.guess_type(full)[0] or "application/octet-stream") + ("; charset=utf-8" if full.endswith((".html", ".js", ".css")) else ""))

        def _api(self):
            body = b""
            if self.command == "POST":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._send(400, {"error": {"code": "BAD_LENGTH", "message": "invalid Content-Length"}})
                if n > MAX_BODY:
                    return self._send(413, {"error": {"code": "BODY_TOO_LARGE", "message": "request body exceeds %d bytes" % MAX_BODY}})
                body = self.rfile.read(n) if n else b""
            status, payload = api.handle(self.command, self.path, body)
            self._send(status, payload)

        def do_GET(self):
            self._api() if self.path.startswith("/api/") else self._static()

        do_HEAD = do_GET

        def do_POST(self):
            if self.path.startswith("/api/"):
                self._api()
            else:
                self._send(405, {"error": {"code": "METHOD_NOT_ALLOWED", "message": "POST only under /api"}})

        def do_PUT(self):
            self._send(405, {"error": {"code": "METHOD_NOT_ALLOWED", "message": "method not supported"}})

        do_DELETE = do_PATCH = do_PUT
    return H


def build_app(data_dir, db_path=None, now=None):
    data_dir = os.path.abspath(data_dir)
    csv_dir = os.path.join(data_dir, "csv")
    db_path = db_path or os.path.join(data_dir, "app.db")
    rebuilt = db.ensure_database(db_path, csv_dir)
    gt = os.path.join(data_dir, "ground_truth")
    clock = Clock(datetime.strptime(now, "%Y-%m-%d %H:%M:%S") if now else None)
    svc = Services(db_path, gt if os.path.isdir(gt) else None, clock)
    return svc, rebuilt


def main(argv=None):
    ap = argparse.ArgumentParser(description="Student & Faculty Support Routing - application server")
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "full"), help="folder produced by datagen.generate")
    ap.add_argument("--db", default=None, help="SQLite file (default: <data>/app.db)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--now", default=os.environ.get("APP_NOW"), help="freeze the application clock 'YYYY-MM-DD HH:MM:SS'")
    a = ap.parse_args(argv)
    svc, rebuilt = build_app(a.data, a.db, a.now)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(Api(svc)))
    print("database %s; serving http://%s:%d  (Ctrl+C to stop)" % ("rebuilt from CSV" if rebuilt else "ready", a.host, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
