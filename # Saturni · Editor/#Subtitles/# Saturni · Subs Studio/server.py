# -*- coding: utf-8 -*-
"""server.py — локальный HTTP (127.0.0.1): интерфейс и открытое видео (с Range для перемотки)."""

import os
import json
import mimetypes
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
ALLOWED = set()          # только открытые в приложении видео / записи голоса отдаём по /media
DEV_API = None           # `--dev`: JSON-мост к Api для отладки UI в обычном браузере
MODULES = {}             # /mod/<имя>/<файл> -> папка общего модуля (@Hub), например debug

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("audio/wav", ".wav")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        if DEV_API is None or not self.path.startswith("/rpc/"):
            return self.send_error(404)
        name = self.path[5:]
        n = int(self.headers.get("Content-Length") or 0)
        args = json.loads(self.rfile.read(n) or b"[]") if n else []
        if name == "__events":
            out, DEV_API._dev[:] = list(DEV_API._dev), []
        elif name.startswith("_") or not hasattr(DEV_API, name):
            return self.send_error(404)
        else:
            try:
                out = getattr(DEV_API, name)(*args)
            except Exception as e:
                out = {"error": str(e)}
        body = json.dumps(out, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype=None, cache=True):
        if not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end, status = 0, size - 1, 200
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                else:
                    start = max(0, size - int(b))
                end = min(end, size - 1)
                status = 206
            except ValueError:
                pass
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 18, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, BrokenPipeError, OSError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        route = unquote(u.path)
        try:
            if route in ("/", "/index.html"):
                return self._send_file(os.path.join(UI_DIR, "index.html"), "text/html; charset=utf-8", False)
            if route.startswith("/ui/"):
                p = os.path.normpath(os.path.join(UI_DIR, route[4:]))
                if not p.startswith(os.path.normpath(UI_DIR)):
                    return self.send_error(403)
                return self._send_file(p, cache=False)
            if route.startswith("/mod/") and MODULES:
                name, _, rel = route[5:].partition("/")
                base = MODULES.get(name)
                if not base:
                    return self.send_error(404)
                p = os.path.normpath(os.path.join(base, rel))
                if not p.startswith(os.path.normpath(base)) or not p.endswith((".js", ".css")):
                    return self.send_error(403)
                return self._send_file(p, cache=False)
            if route == "/media":
                p = (parse_qs(u.query).get("p") or [""])[0]
                if os.path.normcase(os.path.abspath(p)) not in ALLOWED:
                    return self.send_error(403)
                return self._send_file(p, cache=False)
            self.send_error(404)
        except Exception:
            try:
                self.send_error(500)
            except Exception:
                pass


def allow(path):
    ALLOWED.add(os.path.normcase(os.path.abspath(path)))


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass                     # оборванные запросы видео (перемотка) — норма


def start(port=0):
    srv = _Server(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
