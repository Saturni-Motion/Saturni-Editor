# -*- coding: utf-8 -*-
"""
# Saturni · Subs.pyw — одно приложение для титров: Studio (редактор и голосовые правки, основной режим)
и Move (маркеры для #2Stage-рендеров). Переключатель Studio | Move — в шапке окна.

Окно одно; у каждого режима свой сервер, своя страница и свой Api из его папки
(`# Saturni · Subs Studio`, `# Saturni · Subs Move`). Окну отдаётся общий Api: `studio`, `move`
и `subs_switch(mode)`; страница режима берёт свой (`@shared/modes.js`). События шлёт только
активный режим. Можно передать путь к .srt / видео: он открывается в Studio.
Отладка: python "# Saturni · Subs.pyw" --debug
"""
import importlib
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.join(HERE, "# Saturni · Subs Studio")
MOVE = os.path.join(HERE, "# Saturni · Subs Move")
SHARED = os.path.join(HERE, "@shared")
TOOLS = os.path.join(os.path.dirname(HERE), "#Series", "@tools")
PREFS = os.path.join(HERE, "@subs.json")                 # последний режим
CLASH = ("server", "api", "winframe", "app")             # одинаковые имена модулей в обеих папках


def load_part(folder):
    """Модули режима из его папки: у Studio и Move есть свои server/api/winframe с одинаковыми именами."""
    for n in CLASH:
        sys.modules.pop(n, None)
    sys.path.insert(0, folder)
    try:
        server = importlib.import_module("server")
        api = importlib.import_module("api")
    finally:
        sys.path.remove(folder)
    server.MODULES = getattr(server, "MODULES", None) or {}
    server.MODULES["subs"] = SHARED
    return server, api


class SubsApi:
    """Api окна: оба режима (window.pywebview.api.studio / .move) и переключение."""

    def __init__(self, studio, move, ports, mode):
        self.studio, self.move = studio, move
        self._ports, self._mode, self._window = ports, mode, None

    def _url(self, m):
        return f"http://127.0.0.1:{self._ports[m]}/"

    def _active(self):
        return getattr(self, self._mode)

    def subs_mode(self):
        return self._mode

    def subs_switch(self, mode):
        if mode not in ("studio", "move") or mode == self._mode:
            return {"ok": True}
        if self._mode == "move" and getattr(self.move, "_dirty", False):
            return {"ok": False, "why": "unsaved"}
        if self._mode == "studio" and getattr(self.studio, "_run", None):
            return {"ok": False, "why": "busy"}
        cur = self._active()._prefs.get("last_file")        # тот же файл открывается и в другом режиме
        if cur and os.path.exists(cur):
            getattr(self, mode)._prefs["last_file"] = cur
        self._mode = mode
        try:
            json.dump({"mode": mode}, open(PREFS, "w", encoding="utf-8"))
        except OSError:
            pass
        url = self._url(mode)                               # переход — после ответа странице, иначе ответ некуда вернуть
        threading.Timer(.05, lambda: self._window.load_url(url)).start()
        return {"ok": True}


def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Saturni.Subs")
    except Exception:
        pass
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    sys.path.insert(0, STUDIO)                             # core.py (только у Studio) и общие модули Hub
    import core
    s_server, s_api = load_part(STUDIO)
    m_server, m_api = load_part(MOVE)
    m_server.MODULES["debug"] = s_api.STATIC_DIR            # Debug на странице Move — через Api Studio
    sys.path.insert(0, MOVE)                               # render.py (только у Move) для отложенных импортов
    import webview

    s_srv, s_port = s_server.start(0)
    m_srv, m_port = m_server.start(0)
    studio, move = s_api.Api(s_port), m_api.Api(m_port)
    try:
        mode = json.load(open(PREFS, encoding="utf-8")).get("mode", "studio")
    except Exception:
        mode = "studio"
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    if files:
        mode = "studio"
    if "--move" in sys.argv:                               # старый ярлык Subs Move
        mode = "move"
    api = SubsApi(studio, move, {"studio": s_port, "move": m_port}, mode)

    def gate(part, name):                                  # события страницы шлёт только её режим (и Debug)
        orig = part._emit
        part._emit = lambda kind, data=None: orig(kind, data) if api._mode == name or str(kind).startswith("dbg") else None
    gate(studio, "studio")
    gate(move, "move")

    pl = (studio._prefs.get("placement") or {}).get("rect")
    w, h = (pl[2] - pl[0], pl[3] - pl[1]) if pl else (1600, 960)
    window = webview.create_window(
        "Saturni · Subs", url=api._url(mode), js_api=api, width=w, height=h,
        x=pl[0] if pl else None, y=pl[1] if pl else None, min_size=(1100, 680), background_color="#0b0b0f",
        text_select=True, zoomable=False, frameless=True, easy_drag=False, shadow=False)
    api._window = window
    studio._attach(window)
    move._attach(window)

    def on_loaded():
        try:
            from webview.dom import DOMEventHandler

            def on_drop(e):
                fs = (e.get("dataTransfer") or {}).get("files") or []
                paths = [f.get("pywebviewFullPath") for f in fs if f.get("pywebviewFullPath")]
                if paths:
                    api._active()._on_drop(paths)
            window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass

    def on_closing():
        if not api._active()._on_closing():
            return False
        other = move if api._mode == "studio" else studio
        try:
            other._save_prefs()
            if other is studio:
                studio._rec.close()
        except Exception:
            pass
        return True

    window.events.loaded += on_loaded
    window.events.shown += lambda: api._active()._win_style()
    window.events.maximized += lambda: api._active()._on_maximized()
    window.events.restored += lambda: api._active()._on_restored()
    window.events.closing += on_closing

    icon = os.path.join(STUDIO, "ui", "subs.ico")
    webview.start(debug="--debug" in sys.argv, gui="edgechromium", icon=icon if os.path.exists(icon) else None,
                  storage_path=os.path.join(core.DATA_DIR, "webview"), private_mode=False)
    for srv in (s_srv, m_srv):
        try:
            srv.shutdown()
        except Exception:
            pass
    os._exit(0)


if __name__ == "__main__":
    main()
