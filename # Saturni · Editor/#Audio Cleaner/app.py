"""Saturni · Audio Cleaner desktop app: the backend runs in a thread, the UI in a native window (WebView2)."""
import ctypes
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import uvicorn
import webview

import server
from engine import jobs

sys.path.insert(0, str(server.DEBUG_DIR))
try:                                          # Saturni · Debug: Ctrl+click the gear
    from saturni_debug import DebugMixin
except Exception:
    DebugMixin = object

TITLE = "Saturni · Audio Cleaner"
ICON = HERE / "assets" / "icon.ico"
MEDIA = ("Audio and video (*.wav;*.mp3;*.flac;*.m4a;*.aac;*.ogg;*.opus;*.mp4;*.mov;*.mkv;*.avi;*.webm)",
         "All files (*.*)")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Api(DebugMixin):
    """Called from the page as window.pywebview.api.*"""

    def __init__(self):
        self.window = None
        self._debug_dir = str(HERE / "⿻" / "@debug")

    @property
    def _window(self):          # Saturni · Debug reads it
        return self.window

    def _emit(self, kind, data=None):
        import json
        if self.window:
            self.window.evaluate_js(f"window.__emit && window.__emit({json.dumps([{'type': kind, 'data': data}], ensure_ascii=False)})")

    def pick_file(self):
        r = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=MEDIA)
        return r[0] if r else None

    def save_stem(self, jid, key, ext, lang="en"):
        src = server.stem_path(jid, key, ext)
        name = server.stem_filename(jid, key, ext, lang)
        r = self.window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name,
                                           file_types=(f"{ext.upper()} (*.{ext})",))
        if not r:
            return False
        dst = r if isinstance(r, str) else r[0]
        shutil.copyfile(src, dst)
        return True

    def save_all(self, jid, ext, lang="en"):
        r = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if not r:
            return False
        folder = Path(r[0] if not isinstance(r, str) else r)
        for o in jobs.JOBS[jid]["outputs"]:
            shutil.copyfile(server.stem_path(jid, o["key"], ext), folder / server.stem_filename(jid, o["key"], ext, lang))
        return True


def style_window():
    """Dark title bar + our icon (WinForms window of pywebview)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, TITLE)
        if not hwnd:
            return
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        color = ctypes.c_int(0x00120D0B)  # caption colour (BGR) = page background
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        if ICON.exists():
            for size, which in ((16, 0), (32, 1)):
                h = user32.LoadImageW(None, str(ICON), 1, size, size, 0x10)
                user32.SendMessageW(hwnd, 0x80, which, h)
    except Exception:
        pass


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Saturni.AudioCleaner")
    except Exception:
        pass
    port = free_port()
    cfg = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.05)

    api = Api()
    win = webview.create_window(TITLE, f"http://127.0.0.1:{port}/", js_api=api, width=1080, height=800,
                                min_size=(720, 560), background_color="#0B0D12")
    api.window = win
    win.events.shown += lambda: threading.Timer(0.05, style_window).start()
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(Path.home() / ".stemstudio" / "webview"))


if __name__ == "__main__":
    main()
