# -*- coding: utf-8 -*-
r"""Saturni · Editor: локальный сервер — страница (# Editor\ui), файлы с Range, звук, волна."""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from common import *
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from api import Api

UI_DIR = APP_DIR / "ui"

# --------------------------------------------------------------------------- local server
# The page, the files (with Range, so the players can seek), the sound streams and the waveform
# data come from 127.0.0.1: a big video never has to pass through the JS bridge.

def serve(api: Api) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_bytes(self, data: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                route = self.path.split("?")[0]
                if route == "/" or route.startswith("/ui/"):
                    f = (UI_DIR / ("index.html" if route == "/" else route[4:])).resolve()
                    if f.is_file() and UI_DIR.resolve() in f.parents:      # ui and its folders only
                        ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                                 ".svg": "image/svg+xml"}.get(f.suffix, "application/octet-stream")
                        return self.send_bytes(f.read_bytes(), ctype + "; charset=utf-8")
                    self.send_error(404)
                    return
                if route == "/load":                                  # the start data without waiting for the JS bridge
                    return self.send_bytes(json.dumps(api.load(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                if route.startswith("/mod/debug/") and DEBUG_STATIC:
                    f = Path(DEBUG_STATIC) / Path(route[11:]).name
                    if f.is_file():
                        ctype = {".js": "text/javascript", ".css": "text/css"}.get(f.suffix, "application/octet-stream")
                        return self.send_bytes(f.read_bytes(), ctype + "; charset=utf-8")
                    self.send_error(404)
                    return
                m = re.fullmatch(r"/src/(\d+)/(media|proxy|a/\d+|wave/\d+)", route)
                if not m or int(m.group(1)) >= len(api.sources):
                    self.send_error(404)
                    return
                s, what = api.sources[int(m.group(1))], m.group(2)
                if what.startswith("wave/"):
                    return self.send_bytes(s.wave(int(what[5:])), "audio/wav")
                f = s.path if what == "media" else s.proxy_path if what == "proxy" else s.audio_file(int(what[2:]))
                if not f:
                    self.send_error(404)
                    return
                size = f.stat().st_size
                a, b = 0, size - 1
                m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
                if m and (m.group(1) or m.group(2)):
                    if m.group(1):
                        a = int(m.group(1))
                        b = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                    else:
                        a = max(0, size - int(m.group(2)))
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
                else:
                    self.send_response(200)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if f.suffix.lower() in (".mkv", ".webm"):
                    ctype = "video/webm" if what in ("media", "proxy") else "audio/webm"
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(b - a + 1))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(f, "rb") as fh:
                    fh.seek(a)
                    left = b - a + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionError, OSError):
                pass

    ThreadingHTTPServer.request_queue_size = 64            # the page asks for all its scripts at once; 5 drops some
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
