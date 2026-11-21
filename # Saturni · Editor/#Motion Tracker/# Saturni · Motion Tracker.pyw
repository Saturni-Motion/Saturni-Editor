# -*- coding: utf-8 -*-
"""
# Saturni · Motion Tracker.pyw — трекер точки без Premiere: открыть видео, поставить рамку на деталь,
отследить, отрендерить стабилизацию или картинку, которая следует за деталью.

Та же страница (`ui\\`), что и у панели Premiere: папка плагина в Premiere — ссылка (junction) на `ui\\`,
так что правки делаются в одном месте. Движок слежения общий — `core\\tracker.py`, рендер — `core\\render.py`.
Ctrl+клик (или правый клик) по шестерёнке — Saturni · Debug, заметки в `⿻\\@debug\\`.
"""
import http.server
import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI = HERE / "ui"
sys.path.insert(0, str(HERE / "core"))
DEBUG_DIR = HERE.parents[1] / "@ Saturni · Debug"                  # Hub/@ Saturni · Debug
sys.path.insert(0, str(DEBUG_DIR))
try:
    from saturni_debug import DebugMixin
except Exception:
    DebugMixin = object

import webview  # noqa: E402

import render  # noqa: E402
import tracker  # noqa: E402

VIDEO_TYPES = ("Video (*.mp4;*.mov;*.mkv;*.webm;*.m4v;*.avi;*.mxf)", "All files (*.*)")


class Api(DebugMixin):
    def __init__(self):
        self._window = None
        self._debug_dir = str(HERE / "⿻" / "@debug")
        self._path = None
        self._lock = threading.Lock()
        tracker.send = self._send                                    # progress of open/track -> the page

    # ---- to the page
    def _js(self, code):
        if self._window:
            try:
                self._window.evaluate_js(code)
            except Exception:
                pass

    def _send(self, obj):
        self._js(f"window.__ptMsg && window.__ptMsg({json.dumps(obj)})")

    def _emit(self, kind, data=None):                                  # Saturni · Debug voice notes
        self._js(f"window.__emit && window.__emit({json.dumps([{'type': kind, 'data': data}], ensure_ascii=False)})")

    # ---- page calls
    def open_video(self):
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=VIDEO_TYPES)
        if not r:
            return None
        import cv2
        p = r[0]
        cap = cv2.VideoCapture(p)
        info = {"path": p, "name": os.path.basename(p), "fps": cap.get(cv2.CAP_PROP_FPS) or 25.0,
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
        cap.release()
        self._path = p
        return info

    def call(self, rid, cmd, params):
        with self._lock:                                             # one tracker command at a time, as in the panel
            try:
                return {"ok": True, "result": tracker.COMMANDS[cmd]({**(params or {}), "id": rid})}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def render(self, rid, mode, props, points, ref, sound=True):
        src = self._path or tracker.state.get("path")
        if not src:
            return {"ok": False, "error": "Open a video first"}
        overlay = None
        if mode == "attach":
            r = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Pictures (*.png;*.jpg;*.jpeg;*.webp)",))
            if not r:
                return None
            overlay = r[0]
        stem, _ = os.path.splitext(os.path.basename(src))
        name = f"{stem} ` {'stabilized' if mode == 'stabilize' else 'motion'}.mp4"
        r = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.dirname(src), save_filename=name,
                                            file_types=("MP4 (*.mp4)",))
        if not r:
            return None
        out = r if isinstance(r, str) else r[0]
        try:
            render.render(src, out, points, int(ref), mode, props, overlay, bool(sound),
                          lambda d, t: self._send({"id": rid, "progress": d, "total": t}))
            return {"ok": True, "name": os.path.basename(out), "path": out}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def serve():
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            route = self.path.split("?")[0]
            if route.startswith("/mod/debug/"):
                f = DEBUG_DIR / Path(route[11:]).name
            else:
                f = (UI / route.lstrip("/")) if route != "/" else UI / "index.html"
                f = f.resolve()
                if UI.resolve() not in f.parents and f != UI.resolve() / "index.html":
                    return self.send_error(403)
            if not f.is_file():
                return self.send_error(404)
            body = f.read_bytes()
            ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}.get(f.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Saturni.MotionTracker")
    except Exception:
        pass
    api = Api()
    srv = serve()
    api._window = webview.create_window("Saturni · Motion Tracker", f"http://127.0.0.1:{srv.server_address[1]}/", js_api=api,
                                        width=980, height=820, min_size=(520, 560), background_color="#141517")
    icon = HERE / "assets" / "tracker.ico"
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(HERE / "data" / "webview"),
                  icon=str(icon) if icon.exists() else None)
    srv.shutdown()


if __name__ == "__main__":
    main()
