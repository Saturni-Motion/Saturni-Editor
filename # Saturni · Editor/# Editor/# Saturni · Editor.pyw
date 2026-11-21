"""# Saturni · Editor (was Cut Media): trim, cut, crop and adjust audio, video and photos; several files make a mini project.

Explorer menu "Open Editor" on a file (SATURNi.nss) -> pythonw this.pyw "<file>"; a .sedit project opens the same way.
The shortcut without a file: the welcome window (recent projects and files, Open file).
Ctrl+Shift+D (or Ctrl+click the gear) = Saturni · Debug: draw around a spot, say / write what to change;
notes go to ⿻/@debug next to this script, one folder per session.
One model in both modes: tracks of pieces + one layer over the whole timeline (Start / End flags in
the ruler, cuts, fades, a volume line). Simple shows the tracks mixed into one row; Advanced shows them.
Advanced: click = one piece (Shift adds), drag = move (Alt = copy, onto other / new tracks), edges = trim,
the top band of a piece = choose a part of it, C = cut tool, S = split at the playhead, Delete;
drag in the ruler = a range over all tracks; right-click = Split here / Delete / piece or track sound /
add or delete tracks; joins between touching sound pieces take a transition. Pieces keep their own
volume line (Ctrl+click = key), fades (corner wedges, the middle dot = curve) and sound effects.
Wheel in Advanced: time; Alt = zoom, Ctrl = up / down the tracks, Shift = wave height.
Save replaces the file; its menu = Save as new / Save, keep the original ("<name> @orig").
The Settings panel (gear) writes @settings.json next to this file. Ctrl+click the gear = Saturni · Debug.
"""
# Code by folders (on sys.path, plain module names): core (common, settings, source, api, server), ui (page),
# #Video (video.py), #Audio (audio.py), #Image (image.py), @Effects (effects.py), @Transitions (to come).
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _d in ("core", "#Video", "#Audio", "#Image", "@Effects"):
    sys.path.insert(0, str(HERE / _d))

import webview  # noqa: E402

from api import Api  # noqa: E402
from server import serve  # noqa: E402
from settings import COLORS  # noqa: E402


ICON = HERE / "cut.ico"


def set_icon(title: str) -> None:
    """Green scissors in the title bar and on the taskbar (pywebview can't set it on Windows)."""
    import ctypes
    u = ctypes.windll.user32
    for _ in range(100):                                    # the window may still be appearing
        hwnd = u.FindWindowW(None, title)
        if hwnd:
            break
        time.sleep(0.05)
    if not hwnd or not ICON.exists():
        return
    for size, which in ((16, 0), (32, 1)):                  # ICON_SMALL, ICON_BIG
        h = u.LoadImageW(None, str(ICON), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            u.SendMessageW(hwnd, 0x80, which, h)            # WM_SETICON


def window_box(kind: str) -> tuple[int, int, int, int]:
    """Centred on the work area. Video / photo: the window grows around a 16:9 picture area
    as big as the screen allows; audio: a wide strip."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    r = wintypes.RECT()
    u.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)          # SPI_GETWORKAREA (no taskbar)
    k = u.GetDpiForSystem() / 96 if u.IsProcessDPIAware() else 1.0
    L, T, Wa, Ha = r.left / k, r.top / k, (r.right - r.left) / k, (r.bottom - r.top) / k
    fw, fh = 16, 39                                                # window frame and title bar
    if kind == "audio":
        w, h = min(1080, Wa - 40), min(470, Ha - 40)
    else:
        ew = 12 + (0 if kind == "photo" else 26 + 8 + 1 + 30)        # body padding, names column, timeline sides, meter
        eh = 22 + 32 + 46 + (16 if kind == "photo" else 20 + 200 + 32)
        pw = min(1100, Wa - 40 - ew - fw, (Ha - 30 - eh - fh) * 16 / 9)
        w, h = pw + ew + fw, pw * 9 / 16 + eh + fh
    return int(L + (Wa - w) / 2), int(T + (Ha - h) / 2), int(w), int(h)


def main():
    import ctypes
    # its own taskbar group, so the taskbar shows this window's icon, not Python's
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SATURNi.Editor")
    title = "Saturni · Editor"
    if len(sys.argv) < 2 or not Path(sys.argv[1]).is_file():         # from the shortcut: recent files and projects
        from welcome import welcome
        x, y, w, h = window_box("audio")
        welcome(Path(__file__).resolve(), title, (x + (w - 560) // 2, y + (h - 520) // 2, 560, 520))
        webview.start(set_icon, (title,))
        return
    path = Path(sys.argv[1]).resolve()
    api = Api(path)
    srv = serve(api)
    x, y, w, h = window_box(api.sources[0].info["kind"])
    api._window = webview.create_window(title, url=f"http://127.0.0.1:{srv.server_address[1]}/", js_api=api, x=x, y=y, width=w, height=h,
                          min_size=(860, 460), background_color=COLORS["bg"])
    api._window.events.closing += api._on_closing    # несохранённые правки — спросить перед закрытием
    try:
        webview.start(set_icon, (title,))
    finally:
        srv.shutdown()
        shutil.rmtree(api.tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
