# -*- coding: utf-8 -*-
"""
Saturni · Debug для приложений без WebView (tkinter, AutoHotkey): снимок экрана под курсором и
окно на весь экран поверх него с тем же Debug, что и в остальных приложениях. Заметки — в папку приложения.

  pythonw overlay.py --dir "<папка приложения>" --app "Saturni · Properties"   (заметки — в её ⿻\\@debug)

Из tkinter проще через tk_debug.attach_gear(шестерёнка, папка приложения, имя).
"""
import argparse
import base64
import ctypes
import http.server
import io
import json
import os
import sys
import threading
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from saturni_debug import DebugMixin, debug_root, session_dir  # noqa: E402

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Saturni · Debug</title>
<link rel="stylesheet" href="/mod/debug/debug.css">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden;font:13px Inter,"Segoe UI",sans-serif;color:#ddd}</style></head>
<body><script src="/mod/debug/debug.js"></script><script>
const api = (m, ...a) => window.pywebview.api[m](...a);
window.__emit = (t, d) => SaturniDebug.handle(t, d);
window.addEventListener("pywebviewready", () => SaturniDebug.init({ api, app: %s, screen: true, onExit: () => api("close") }));
</script></body></html>"""


class MI(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("mon", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


def monitor_under_cursor():
    u = ctypes.windll.user32
    pt = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(pt))
    u.MonitorFromPoint.restype = ctypes.c_void_p
    mi = MI()
    mi.size = ctypes.sizeof(MI)
    u.GetMonitorInfoW(ctypes.c_void_p(u.MonitorFromPoint(pt, 2)), ctypes.byref(mi))
    m = mi.mon
    return m.left, m.top, m.right, m.bottom


class Api(DebugMixin):
    def __init__(self, debug_dir, shot, css_w):
        self._debug_dir = debug_dir
        self._shot, self._scr_css_w = shot, css_w
        self._window = None

    def _emit(self, kind, data):
        if self._window:
            self._window.evaluate_js(f"window.__emit({json.dumps(kind)}, {json.dumps(data, ensure_ascii=False)})")

    def debug_screen_start(self):          # снимок уже сделан до появления окна
        buf = io.BytesIO()
        self._shot.save(buf, "JPEG", quality=92)
        return {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                "w": self._shot.width, "h": self._shot.height}

    def debug_screen_stop(self):
        return True

    def close(self):
        threading.Timer(.15, lambda: self._window.destroy()).start()
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--app", default="app")
    a = ap.parse_args()
    from PIL import ImageGrab
    import webview
    box = monitor_under_cursor()
    shot = ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
    shot.save(os.path.join(session_dir(debug_root(a.dir)), "screen.png"))
    w, h = box[2] - box[0], box[3] - box[1]
    k = ctypes.windll.user32.GetDpiForSystem() / 96 or 1
    api = Api(a.dir, shot, shot.width / k)
    page = (PAGE % json.dumps(a.app)).encode("utf-8")

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_GET(self):
            if self.path.startswith("/mod/debug/"):
                f = os.path.join(HERE, os.path.basename(self.path.split("?")[0]))
                body = open(f, "rb").read() if os.path.isfile(f) else b""
                ctype = "text/css" if f.endswith(".css") else "application/javascript"
            else:
                body, ctype = page, "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api._window = webview.create_window("Saturni · Debug", f"http://127.0.0.1:{srv.server_address[1]}/", js_api=api,
                                        x=int(box[0] / k), y=int(box[1] / k), width=int(w / k), height=int(h / k),
                                        frameless=True, on_top=True, background_color="#000000")
    webview.start(gui="edgechromium", private_mode=False, storage_path=os.path.join(debug_root(a.dir), "webview"))


if __name__ == "__main__":
    main()
