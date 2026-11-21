# -*- coding: utf-8 -*-
"""server.py — локальный HTTP (127.0.0.1): интерфейс, открытое видео (с Range), слои и миниатюры."""

import os
import mimetypes
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

from render import CACHE_DIR

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
MODULES = {}             # /mod/<имя>/<файл> -> папка общего модуля
ALLOWED = set()          # пути видео, открытых в приложении (только их отдаём по /media)
FONTS_DIR = [None]       # папка шрифтов титров текущего файла (для мгновенного превью в браузере)

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/ttf", ".ttf")


DEV_API = None           # только для `--dev`: JSON-мост к Api для отладки UI в обычном браузере


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        import json
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

    def log_message(self, *a):
        pass

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
            if route.startswith("/ui/") or route.startswith("/assets/"):
                rel = route[4:] if route.startswith("/ui/") else "assets/" + route[8:]
                p = os.path.normpath(os.path.join(UI_DIR, rel))
                if not p.startswith(os.path.normpath(UI_DIR)):
                    return self.send_error(403)
                return self._send_file(p, cache=False)
            if route.startswith("/mod/") and MODULES:          # общие модули: Saturni · Debug, переключатель режимов
                name, _, rel = route[5:].partition("/")
                base = MODULES.get(name)
                p = os.path.normpath(os.path.join(base, rel)) if base else ""
                if not p or not p.startswith(os.path.normpath(base)) or not p.endswith((".js", ".css")):
                    return self.send_error(404)
                return self._send_file(p, cache=False)
            if route.startswith("/cache/"):
                return self._send_file(os.path.join(CACHE_DIR, os.path.basename(route)))
            if route.startswith("/font/") and FONTS_DIR[0]:
                n = os.path.basename(route)
                if n.lower().endswith((".ttf", ".otf", ".woff2")):
                    return self._send_file(os.path.join(FONTS_DIR[0], n), "font/ttf")
                return self.send_error(403)
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
        pass                     # оборванные запросы видео (перемотка) — норма, не шумим


def start(port=0):
    srv = _Server(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
