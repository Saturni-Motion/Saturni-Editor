# -*- coding: utf-8 -*-
"""
Saturni · Debug — «умная отладка» для наших pywebview-приложений: обводишь область в окне, говоришь
или пишешь, что там поменять; заметки живут поверх окна (привязаны к прокручиваемой панели и к
вкладке/файлу), нумерация сквозная, всё сохраняется в <папка приложения>/⿻/@debug/<дата сессии>/ для Claude.

Подключение к приложению (pywebview + наш локальный HTTP):
  Python:
      sys.path.insert(0, r"D:\\@Hub\\@ Saturni · Debug")
      from saturni_debug import DebugMixin, STATIC_DIR
      class Api(DebugMixin, ...):          # нужны self._window, self._emit(kind, data)
          ...                              # self._rec (Saturni · Voice Recorder) — если есть, берётся он
      self._debug_dir = os.path.join(APP_DIR, "\u2ffb", "@debug")   # или просто APP_DIR
      сервер: отдавать файлы STATIC_DIR по /mod/debug/<файл>
  HTML:  <link rel="stylesheet" href="/mod/debug/debug.css"> <script src="/mod/debug/debug.js"></script>
  JS:    SaturniDebug.init({api, context: () => "<вкладка/файл>", slot: <элемент для кнопки>})
         в обработчике событий из Python первым делом: if (SaturniDebug.handle(type, data)) continue;
         в своих хоткеях/мыши: if (SaturniDebug.owns(e)) return;

Файлы в ⿻/@debug/<дата сессии>/ (current.txt в ⿻/@debug называет текущую сессию; Clear начинает новую):
  debug.json   всё состояние (заметки, контуры, привязка, элементы под областью)
  notes.md     то же для чтения Claude: номер, вкладка, что сказано, какие элементы, картинка
  NN.png       снимок вокруг области с обводкой, но без других заметок: сразу видно, о чём речь
  audio/       записи голоса
  done.json    правки применены: когда, итог и что сделано по каждой заметке (пишет finish_session)

Claude, когда применил правки, закрывает сессию — цифра на шестерёнке пропадает, сессия уходит в историю
(правый клик по жучку на шестерёнке):
  python "D:\\@Hub\\@ Saturni · Debug\\saturni_debug.py" done "<папка программы>" "<done.json>"
  <done.json> = {"summary": "итог одной строкой", "notes": {"1": "что сделано по #1", ...}}
  без файла — сделаны все; заметки, которых нет в "notes", переезжают в новую сессию.
"""

import os
import json
import time
import shutil
import ctypes
import threading
from ctypes import wintypes

STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.join(os.path.dirname(STATIC_DIR), "Saturni · Voice")


def _save_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _notes_md(data, app):
    out = [f"# Saturni · Debug — {app}", "",
           "Правки Saturni к интерфейсу. Каждая заметка: обведённая область (снимок NN.png, обводка видна на нём),",
           "что сказано/написано, вкладка/файл, где была сделана, и элементы под областью (селекторы, текст).",
           "Координаты — относительно панели-якоря (с учётом её прокрутки).", ""]
    for n in sorted(data.get("notes", []), key=lambda x: x["n"]):
        out.append(f"## #{n['n']} — {n.get('ctx') or 'global'}")
        out.append("")
        out.append((n.get("text") or "(пусто)").strip())
        out.append("")
        out.append(f"- якорь: `{n.get('anchor', {}).get('sel', 'document')}`; область в окне: {n.get('bbox')}")
        if n.get("shot"):
            out.append(f"- снимок: {n['shot']}")
        for e in (n.get("elements") or [])[:12]:
            t = (e.get("text") or "").replace("\n", " ")[:80]
            out.append(f"  - `{e.get('sel')}`" + (f" — «{t}»" if t else "") +
                       (f" · {e.get('style')}" if e.get("style") else ""))
        out.append("")
    return "\n".join(out)


def debug_root(path):
    """Папка заметок программы: <программа>\\⿻\\@debug. Принимает папку программы, её ⿻\\@debug
    или старый путь <программа>\\#debug (так его задавали программы раньше)."""
    p = os.path.normpath(path)
    if os.path.basename(p) == "@debug":
        return p
    if os.path.basename(p) == "#debug":
        p = os.path.dirname(p)
    return os.path.join(p, "⿻", "@debug")


def session_dir(root, create=True):
    """Текущая сессия правок: папка с датой начала («2026-11-06 14-30»), имя — в root\\current.txt.
    create=False — только узнать путь, ничего не создавая (None, если сессий ещё не было)."""
    cur = os.path.join(root, "current.txt")
    try:
        name = open(cur, encoding="utf-8").read().strip()
    except OSError:
        name = ""
    if not create:
        return os.path.join(root, name) if name else None
    os.makedirs(root, exist_ok=True)
    if not name:
        name = new_session(root)
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    return d


def new_session(root):
    os.makedirs(root, exist_ok=True)
    name = time.strftime("%Y-%m-%d %H-%M")
    if os.path.isdir(os.path.join(root, name)) and os.listdir(os.path.join(root, name)):   # та же минута
        name = time.strftime("%Y-%m-%d %H-%M-%S")
    with open(os.path.join(root, "current.txt"), "w", encoding="utf-8") as f:
        f.write(name)
    return name


def _read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def finish_session(root, done=None, summary=""):
    """Claude применил правки. done = {"N": "что сделано"} (None — сделаны все).
    Сессия остаётся своей папкой (история) с done.json; несделанные заметки переезжают в новую сессию,
    а если сделано всё — текущей сессии нет и цифра на шестерёнке пропадает."""
    cur = session_dir(root, create=False)
    data = _read_json(os.path.join(cur, "debug.json")) if cur else None
    if not data or not data.get("notes"):
        return "нет заметок"
    notes = data["notes"]
    done = {str(k): v or "" for k, v in (done if done is not None else {n["n"]: "" for n in notes}).items()}
    _save_json(os.path.join(cur, "done.json"), {"at": time.strftime("%Y-%m-%d %H:%M"), "summary": summary, "notes": done})
    keep = [n for n in notes if str(n["n"]) not in done]
    if not keep:
        with open(os.path.join(root, "current.txt"), "w", encoding="utf-8") as f:
            f.write("")
        return f"сделано {len(done)}, заметок больше нет"
    nd = os.path.join(root, new_session(root))
    os.makedirs(nd, exist_ok=True)
    for n in keep:
        if n.get("shot") and os.path.isfile(os.path.join(cur, n["shot"])):
            shutil.copy2(os.path.join(cur, n["shot"]), os.path.join(nd, n["shot"]))
    data = dict(data, notes=keep)
    _save_json(os.path.join(nd, "debug.json"), data)
    try:
        app = open(os.path.join(cur, "notes.md"), encoding="utf-8").readline().split("—", 1)[1].strip()
    except Exception:
        app = "app"
    with open(os.path.join(nd, "notes.md"), "w", encoding="utf-8") as f:
        f.write(_notes_md(data, app))
    return f"сделано {len(done)}, осталось {len(keep)}: " + ", ".join(f"#{n['n']}" for n in keep)


class DebugMixin:
    _debug_dir = None
    _debug_lock = threading.Lock()

    # ── хранение: <программа>\⿻\@debug\<дата сессии>\ ──
    def _dbg_root(self):
        return debug_root(self._debug_dir or os.getcwd())

    def _dbg_dir(self):
        return session_dir(self._dbg_root())

    def debug_load(self):
        try:                                     # только читаем: папка заметок появляется с первой заметкой
            with open(os.path.join(session_dir(self._dbg_root(), create=False), "debug.json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"next_n": 1, "notes": []}

    def debug_save(self, data, app="app"):
        with self._debug_lock:
            d = self._dbg_dir()
            _save_json(os.path.join(d, "debug.json"), data)
            with open(os.path.join(d, "notes.md"), "w", encoding="utf-8") as f:
                f.write(_notes_md(data, app))
        return True

    def debug_clear(self):
        """Clear: текущая сессия остаётся своей папкой с датой, начинается новая, нумерация с 1."""
        new_session(self._dbg_root())
        return True

    # ── история: прошлые сессии (правый клик по жучку на шестерёнке) ──
    def debug_history(self):
        root = self._dbg_root()
        cur = os.path.basename(session_dir(root, create=False) or "")
        out = []
        try:
            names = sorted(os.listdir(root), reverse=True)
        except OSError:
            return out
        for name in names:
            d = os.path.join(root, name)
            if name == cur or not os.path.isdir(d):
                continue
            data = _read_json(os.path.join(d, "debug.json"), {})
            if not data.get("notes"):
                continue
            done = _read_json(os.path.join(d, "done.json"))
            out.append({"name": name, "count": len(data["notes"]), "done": bool(done),
                        "at": (done or {}).get("at", ""), "summary": (done or {}).get("summary", "")})
        return out

    def debug_history_open(self, name):
        import base64
        d = os.path.join(self._dbg_root(), os.path.basename(name))
        data = _read_json(os.path.join(d, "debug.json"), {})
        done = (_read_json(os.path.join(d, "done.json")) or {}).get("notes", {})
        out = []
        for n in sorted(data.get("notes", []), key=lambda x: x["n"]):
            shot = ""
            p = os.path.join(d, n.get("shot") or "")
            if n.get("shot") and os.path.isfile(p):
                with open(p, "rb") as f:
                    shot = "data:image/png;base64," + base64.b64encode(f.read()).decode()
            out.append({"n": n["n"], "ctx": n.get("ctx") or "", "text": (n.get("text") or "").strip(), "shot": shot,
                        "applied": str(n["n"]) in done, "what": done.get(str(n["n"]), ""),
                        "elements": [{"sel": e.get("sel"), "text": (e.get("text") or "")[:60]} for e in (n.get("elements") or [])[:4]]})
        return out

    def debug_reveal(self):
        import subprocess
        subprocess.Popen(["explorer", os.path.normpath(self._dbg_root())])
        return True

    # ── снимок области ──
    def debug_shot(self, n, rect, dpr=1.0, screen=False):
        """rect = [x, y, w, h] в CSS-пикселях клиентской области окна; сохраняет NN.png с полями.
        screen: область на снимке экрана (режим «весь экран»)."""
        try:
            from PIL import Image, ImageGrab
            if screen:
                pad = 90
                x, y, w, h = [float(v) for v in rect]
                with Image.open(os.path.join(self._dbg_dir(), "screen.png")) as im:
                    k = im.width / (self._scr_css_w or im.width)
                    box = (max(0, int((x - pad) * k)), max(0, int((y - pad) * k)), min(im.width, int((x + w + pad) * k)), min(im.height, int((y + h + pad) * k)))
                    name = f"{int(n):02d}.png"
                    im.crop(box).save(os.path.join(self._dbg_dir(), name))
                return name
            hwnd = int(self._window.native.Handle.ToInt64())
            pt = wintypes.POINT(0, 0)
            ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
            rc = wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rc))
            pad = 90
            x, y, w, h = [float(v) for v in rect]
            l = max(0, int((x - pad) * dpr)); t = max(0, int((y - pad) * dpr))
            r = min(rc.right, int((x + w + pad) * dpr)); b = min(rc.bottom, int((y + h + pad) * dpr))
            img = ImageGrab.grab(bbox=(pt.x + l, pt.y + t, pt.x + r, pt.y + b), all_screens=True)
            name = f"{int(n):02d}.png"
            img.save(os.path.join(self._dbg_dir(), name))
            return name
        except Exception as e:
            return {"error": str(e)}

    # ── весь экран: снимок экрана, на который можно наносить заметки ──
    _scr_css_w = 0

    def debug_screen_start(self):
        """Окно прячется, снимается монитор под ним, окно разворачивается на весь экран; снимок — фон для заметок."""
        import base64
        import io
        from PIL import ImageGrab
        try:
            class MI(ctypes.Structure):
                _fields_ = [("size", wintypes.DWORD), ("mon", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
            u = ctypes.windll.user32
            hwnd = int(self._window.native.Handle.ToInt64())
            mi = MI(); mi.size = ctypes.sizeof(MI)
            u.MonitorFromWindow.restype = ctypes.c_void_p
            u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            u.GetMonitorInfoW(ctypes.c_void_p(u.MonitorFromWindow(hwnd, 2)), ctypes.byref(mi))
            self._window.hide()
            time.sleep(.3)
            m = mi.mon
            img = ImageGrab.grab(bbox=(m.left, m.top, m.right, m.bottom), all_screens=True).convert("RGB")
            self._window.show()
            img.save(os.path.join(self._dbg_dir(), "screen.png"))
            self._window.toggle_fullscreen()
            k = (u.GetDpiForWindow(hwnd) or 96) / 96
            self._scr_css_w = img.width / k
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=92)
            return {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "w": img.width, "h": img.height}
        except Exception as e:
            try:
                self._window.show()
            except Exception:
                pass
            return {"error": str(e)}

    def debug_screen_stop(self):
        try:
            self._window.toggle_fullscreen()
        except Exception:
            pass
        return True

    # ── голос (общий Recorder приложения или свой) ──
    def _dbg_rec(self):
        rec = getattr(self, "_rec", None)
        if rec is None:
            import sys
            if VOICE_DIR not in sys.path:
                sys.path.insert(0, VOICE_DIR)
            from recorder import Recorder
            rec = self._rec = Recorder(self._emit)
        return rec

    def debug_rec_start(self, n):
        rid = f"d{int(time.time() * 1000)}"
        base = os.path.join(self._dbg_dir(), "audio", f"{int(n):02d}_{time.strftime('%H-%M-%S')}")
        return rid if self._dbg_rec().start(rid, f"dbg:{n}", base, blocks=True) else None

    def debug_rec_stop(self):
        return self._dbg_rec().stop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "done":      # закрыть сессию правок (см. начало файла)
        spec = _read_json(sys.argv[3], {}) if len(sys.argv) > 3 else {}
        print(finish_session(debug_root(sys.argv[2]), spec.get("notes"), spec.get("summary", "")))
    else:
        print('python saturni_debug.py done "<папка программы>" ["<done.json>"]')