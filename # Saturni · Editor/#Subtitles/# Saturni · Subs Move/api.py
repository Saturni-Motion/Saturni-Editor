# -*- coding: utf-8 -*-
"""api.py — мост JS <-> Python для Subs Studio: файлы, превью, сохранение, окно."""

import os
import json
import time
import shutil
import ctypes
import threading
from ctypes import wintypes

import sys
import importlib.util as _ilu
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "#Series", "@tools")


def _tool(name, file):
    """Модуль из @tools по пути: в именах пробелы/точки/@ (2026-10-07), обычный import их не
    видит. Регистрируется под прежним именем модуля — повторная загрузка не нужна."""
    if name not in sys.modules:
        spec = _ilu.spec_from_file_location(name, os.path.join(_TOOLS, file))
        sys.modules[name] = mod = _ilu.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


sm = _tool("srt_markers", "@SRT Markers.py")
import render
import server

DATA_DIR = render.DATA_DIR
PREFS_PATH = os.path.join(DATA_DIR, "prefs.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backup")
VID_EXT = (".mp4", ".mov", ".mkv", ".m4v", ".webm")

DEFAULT_PREFS = {
    "theme": "dark", "ui": "minimal", "accent": "blue", "last_file": None, "placement": None,
    "presets": [
        {"id": "p-dark", "name": "Dark", "mk": "[]", "icon": "moon"},
        {"id": "p-light", "name": "Light", "mk": "[w]!", "icon": "sun"},
        {"id": "p-flat", "name": "Flat", "mk": "#0", "icon": "square"},
    ],
}


def _load_json(p, default):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(p, data):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ── буфер обмена Windows (текст) ──
_u32, _k32 = ctypes.windll.user32, ctypes.windll.kernel32
_k32.GlobalAlloc.restype = wintypes.HGLOBAL
_k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_k32.GlobalLock.restype = ctypes.c_void_p
_k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_u32.GetClipboardData.restype = wintypes.HANDLE
_u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


def clip_get():
    if not _u32.OpenClipboard(None):
        return ""
    try:
        h = _u32.GetClipboardData(13)            # CF_UNICODETEXT
        if not h:
            return ""
        p = _k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            _k32.GlobalUnlock(h)
    finally:
        _u32.CloseClipboard()


def clip_set(text):
    data = (text or "").encode("utf-16-le") + b"\0\0"
    if not _u32.OpenClipboard(None):
        return False
    try:
        _u32.EmptyClipboard()
        h = _k32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
        p = _k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        _k32.GlobalUnlock(h)
        _u32.SetClipboardData(13, h)
        return True
    finally:
        _u32.CloseClipboard()


class _MI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class _WP(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", wintypes.RECT)]


_u32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
_u32.MonitorFromRect.restype = wintypes.HANDLE
_u32.MonitorFromWindow.restype = wintypes.HANDLE
_u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


def _monitor_info(h):
    mi = _MI()
    mi.cbSize = ctypes.sizeof(_MI)
    return mi if h and _u32.GetMonitorInfoW(h, ctypes.byref(mi)) else None


class Api:
    def __init__(self, port):
        self._port = port
        self._window = None
        self._native_frame = False
        self._dirty = False
        self._force_close = False
        self._backed_up = set()
        self._file = None
        self._events, self._ev_lock = [], threading.Lock()
        self._dev = None          # --dev: события копятся для опроса по HTTP
        prefs = dict(DEFAULT_PREFS)
        prefs.update(_load_json(PREFS_PATH, {}))
        self._prefs = prefs
        threading.Thread(target=self._emit_loop, daemon=True).start()
        threading.Thread(target=render.clean_cache, daemon=True).start()

    # ── инфраструктура ──
    def _attach(self, window):
        self._window = window

    def _emit(self, kind, data=None):
        with self._ev_lock:
            self._events.append({"type": kind, "data": data})

    def _emit_loop(self):
        while True:
            time.sleep(0.08)
            if not self._window and self._dev is None:
                continue
            with self._ev_lock:
                evs, self._events = self._events, []
            if evs and self._dev is not None:
                self._dev.extend(evs)
                continue
            if evs:
                try:
                    self._window.evaluate_js(f"window.__emit && window.__emit({json.dumps(evs, ensure_ascii=False)})")
                except Exception:
                    pass

    def _save_prefs(self):
        try:
            _save_json(PREFS_PATH, self._prefs)
        except Exception:
            pass

    # ── JS: старт, настройки ──
    def init(self):
        return {"prefs": self._prefs, "style": self._style(), "base": sm.style_from(overrides=False),
                "custom": True, "start_file": self._start_file()}

    def _start_file(self):
        import sys
        for a in sys.argv[1:]:
            if not a.startswith("--") and os.path.exists(a):
                return a
        lf = self._prefs.get("last_file")
        return lf if lf and os.path.exists(lf) else None

    def _style(self):
        st = sm.style_from()
        return {k: v for k, v in st.items() if not k.startswith("_")}

    def prefs_save(self, patch):
        self._prefs.update(patch or {})
        self._save_prefs()
        return True

    # ── файлы ──
    def open_dialog(self):
        import webview
        start = os.path.dirname(self._file["srt"]) if self._file else (os.path.dirname(self._prefs.get("last_file") or "") or "")
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, directory=start, allow_multiple=False,
                                            file_types=("Subtitles or video (*.srt;*.mp4;*.mov;*.mkv;*.m4v;*.webm)", "All files (*.*)"))
        if not r:
            return None
        return self.load(r[0] if isinstance(r, (list, tuple)) else r)

    @staticmethod
    def _find_video(base):
        for e in VID_EXT:
            if os.path.exists(base + e):
                return base + e
        return None

    def load(self, path):
        path = os.path.abspath(path)
        base, ext = os.path.splitext(path)
        ext = ext.lower()
        srt, videos = None, {}
        if ext == ".srt":
            srt = path
        elif ext in VID_EXT:
            srt = base + ".srt"
            if not os.path.exists(srt) and base.endswith("` 1v") and os.path.exists(base[:-2] + "1h.srt"):
                srt = base[:-2] + "1h.srt"
        else:
            return {"error": f"Unsupported file: {os.path.basename(path)}"}
        sbase = os.path.splitext(srt)[0]
        cands = [path] if ext in VID_EXT else []
        for b in (sbase, sbase[:-2] + "1v" if sbase.endswith("` 1h") else None,
                  sbase[:-2] + "1h" if sbase.endswith("` 1v") else None):
            v = self._find_video(b) if b else None
            if v and v not in cands:
                cands.append(v)
        for v in cands:
            info = render.probe(v)
            if not info:
                continue
            o = "v" if info["h"] > info["w"] else "h"
            if o not in videos:
                info["path"] = v
                videos[o] = info
                server.allow(v)
        blocks, newline = [], "\r\n"
        if os.path.exists(srt):
            raw = open(srt, "rb").read()
            text = raw.decode("utf-8-sig", errors="replace")
            newline = "\r\n" if "\r\n" in text else "\n"
            for i, b in enumerate(sm.parse_srt(text)):
                blocks.append({"mk": sm.canon(b["mk"]) if b["mk"] else "",
                               "mk_raw": b["mk"], "start": b["start"], "end": b["end"], "text": "\n".join(b["lines"])})
        elif not videos:
            return {"error": "No subtitles or video found"}
        first = "v" if ext in VID_EXT and videos.get("v", {}).get("path") == path else ("h" if "h" in videos else ("v" if videos else None))
        self._file = {"srt": srt, "newline": newline, "videos": videos}
        server.FONTS_DIR[0] = render.fonts_dir_for(srt)
        self._prefs["last_file"] = srt if os.path.exists(srt) else path
        self._save_prefs()
        return {"srt": srt, "srt_exists": os.path.exists(srt), "name": os.path.basename(srt), "videos": videos,
                "orient": first, "blocks": blocks, "fonts_dir": render.fonts_dir_for(srt)}

    def save(self, blocks, globals_=None):
        if not self._file:
            return {"ok": False, "msg": "No file"}
        srt = self._file["srt"]
        try:
            if os.path.exists(srt) and srt not in self._backed_up:   # копия оригинала — один раз за сеанс
                os.makedirs(BACKUP_DIR, exist_ok=True)
                stem = os.path.splitext(os.path.basename(srt))[0]
                shutil.copy2(srt, os.path.join(BACKUP_DIR, f"{stem}`{time.strftime('%H-%M-%S %d.%m.%y')}.srt"))
                self._backed_up.add(srt)
            data = sm.write_srt(blocks, self._file["newline"])
            tmp = srt + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(data)
            os.replace(tmp, srt)
            if globals_:
                ov = sm.load_overrides()
                ov.update({k: v for k, v in globals_.items() if v is not None})
                sm.save_overrides(ov)
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        self._dirty = False
        return {"ok": True, "style": self._style()}

    def resettings(self, values):
        """Новые значения по умолчанию -> @SRT Markers.json (действуют на все 2Stage-рендеры)."""
        try:
            ov = sm.load_overrides()
            ov.update({k: v for k, v in (values or {}).items() if k in sm.OVERRIDABLE and v is not None})
            sm.save_overrides(ov)
            return {"ok": True, "style": self._style()}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def preview(self, mk, text, orient, style_patch=None, fonts_dir=None):
        st = sm.style_from()
        for k, v in (style_patch or {}).items():
            if k in sm.OVERRIDABLE and v is not None:
                if k == "shadow_opacity" and v != st["shadow_opacity"]:
                    st["shadow_alpha"] = st["shadow_bord_alpha"] = sm._op_to_alpha(v)
                st[k] = v
        try:
            r = render.layer(mk or "", text or "", orient or "h", st, fonts_dir or sm.DEFAULT_ADDS)
            if r.get("name"):
                r["url"] = "/cache/" + r["name"]
            return r
        except Exception as e:
            return {"error": str(e)}

    def strip(self, orient):
        v = (self._file or {}).get("videos", {}).get(orient)
        if not v:
            return None

        def go():
            try:
                self._emit("strip", {"orient": orient, "url": "/cache/" + render.strip(v["path"], v), "n": render.STRIP_N})
            except Exception as e:
                self._emit("strip", {"orient": orient, "error": str(e)})
        threading.Thread(target=go, daemon=True).start()
        return True

    def clipboard_get(self):
        return clip_get()

    def clipboard_set(self, text):
        return clip_set(text)

    def reveal(self, path=None):
        import subprocess
        p = path or (self._file or {}).get("srt")
        if p and os.path.exists(p):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        return True

    def set_dirty(self, d):
        self._dirty = bool(d)
        return True

    # ── окно: своя шапка, перемещение, размер, запоминание места ──
    def _hwnd(self):
        return int(self._window.native.Handle.ToInt64())

    def _ui(self, fn):
        try:
            from System import Action
            self._window.native.BeginInvoke(Action(fn))
        except Exception:
            fn()

    def _win_style(self):
        try:
            import winframe
            hwnd = self._hwnd()

            def frame():
                try:
                    self._native_frame = winframe.install(hwnd)
                    self._restore_place(hwnd)
                    winframe.corners(hwnd, not winframe.zoomed(hwnd))
                    # DWM не рисует свою рамку и большую тень окна — контур рисуем сами (CSS), тень остаётся лёгкой
                    v = ctypes.c_int(1)                              # DWMWA_NCRENDERING_POLICY = DWMNCRP_DISABLED
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(v), 4)
                    self._emit("win", {"max": winframe.zoomed(hwnd)})
                except Exception:
                    pass
            self._ui(frame)
        except Exception:
            pass
        try:
            ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "subs.ico")

            def set_icon():
                import System.Drawing
                self._window.native.Icon = System.Drawing.Icon(ico)
            self._ui(set_icon)
        except Exception:
            pass

    def _restore_place(self, hwnd):
        """Окно туда же, где закрыли: тот же монитор, размер, развёрнуто или нет."""
        pl = self._prefs.get("placement") or {}
        r = pl.get("rect")
        if r and len(r) == 4:
            rc = wintypes.RECT(*r)
            if _u32.MonitorFromRect(ctypes.byref(rc), 0):        # MONITOR_DEFAULTTONULL: монитор ещё есть
                _u32.SetWindowPos(hwnd, 0, r[0], r[1], r[2] - r[0], r[3] - r[1], 0x0004 | 0x0010)
                if pl.get("max"):
                    import winframe
                    winframe.command(hwnd, winframe.SC_MAXIMIZE)
                return
        mi = _monitor_info(_u32.MonitorFromWindow(hwnd, 2))    # иначе — по центру рабочей области
        rw = wintypes.RECT()
        _u32.GetWindowRect(hwnd, ctypes.byref(rw))
        if mi:
            w, h = rw.right - rw.left, rw.bottom - rw.top
            a = mi.rcWork
            _u32.SetWindowPos(hwnd, 0, a.left + max(0, (a.right - a.left - w) // 2),
                              a.top + max(0, (a.bottom - a.top - h) // 2), 0, 0, 0x0001 | 0x0004 | 0x0010)

    def _store_place(self):
        try:
            hwnd = self._hwnd()
            wp = _WP()
            wp.length = ctypes.sizeof(_WP)
            if not _u32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
                return
            mx = wp.showCmd == 3 or bool(_u32.IsZoomed(hwnd))
            if not mx and not _u32.IsIconic(hwnd):
                rc = wintypes.RECT()
                _u32.GetWindowRect(hwnd, ctypes.byref(rc))
            else:                                # rcNormalPosition — в координатах рабочей области
                rc = wp.rcNormalPosition
                mi = _monitor_info(_u32.MonitorFromRect(ctypes.byref(rc), 2))
                if mi:
                    dx, dy = mi.rcWork.left - mi.rcMonitor.left, mi.rcWork.top - mi.rcMonitor.top
                    rc = wintypes.RECT(rc.left + dx, rc.top + dy, rc.right + dx, rc.bottom + dy)
            if rc.right - rc.left >= 600 and rc.bottom - rc.top >= 400:
                self._prefs["placement"] = {"rect": [rc.left, rc.top, rc.right, rc.bottom], "max": mx}
        except Exception:
            pass

    def win_state(self):
        try:
            import winframe
            return {"max": winframe.zoomed(self._hwnd())}
        except Exception:
            return {"max": False}

    def win_drag(self):
        hwnd = self._hwnd()

        def go():
            _u32.ReleaseCapture()
            _u32.SendMessageW(hwnd, 0x0112, 0xF012, 0)
        self._ui(go)
        return True

    def win_size(self, edge):
        code = {"l": 1, "r": 2, "t": 3, "tl": 4, "tr": 5, "b": 6, "bl": 7, "br": 8}.get(edge)
        if not code:
            return False
        hwnd = self._hwnd()

        def go():
            _u32.ReleaseCapture()
            _u32.SendMessageW(hwnd, 0x0112, 0xF000 + code, 0)
        self._ui(go)
        return True

    def win_min(self):
        import winframe
        winframe.command(self._hwnd(), winframe.SC_MINIMIZE)
        return True

    def win_max(self):
        import winframe
        hwnd = self._hwnd()
        mx = not winframe.zoomed(hwnd)
        winframe.command(hwnd, winframe.SC_MAXIMIZE if mx else winframe.SC_RESTORE)
        return mx

    def _on_maximized(self):
        try:
            import winframe
            winframe.corners(self._hwnd(), False)
        except Exception:
            pass
        self._emit("win", {"max": True})

    def _on_restored(self):
        try:
            import winframe
            mx = winframe.zoomed(self._hwnd())
            winframe.corners(self._hwnd(), not mx)
            self._emit("win", {"max": mx})
        except Exception:
            pass

    def win_close(self):
        """Закрыть без вопросов (JS уже спросил про несохранённое)."""
        self._force_close = True
        self._store_place()
        self._save_prefs()
        threading.Thread(target=self._window.destroy, daemon=True).start()
        return True

    def titlebar(self, dark, bg, fg, border=None):
        try:
            hwnd, dwm = self._hwnd(), ctypes.windll.dwmapi

            def set_(attr, val):
                v = ctypes.c_int(val)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

            def cref(h):
                h = h.lstrip("#")
                return int(h[0:2], 16) | (int(h[2:4], 16) << 8) | (int(h[4:6], 16) << 16)
            set_(20, 1 if dark else 0)
            set_(34, cref(border or bg))            # DWMWA_BORDER_COLOR — тонкая обводка окна
            return True
        except Exception:
            return False

    def _on_closing(self):
        """Системное закрытие (Alt+F4, панель задач): несохранённое — спросить в UI."""
        if self._dirty and not self._force_close:
            self._emit("close_request")
            return False
        self._store_place()
        self._save_prefs()
        return True

    def _on_drop(self, paths):
        self._emit("drop", paths)
