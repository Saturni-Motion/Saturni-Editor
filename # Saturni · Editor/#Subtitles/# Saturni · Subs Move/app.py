# -*- coding: utf-8 -*-
"""
app.py — окно Subs Studio (pywebview / WebView2): маркеры титров для #2Stage-рендеров.
Запуск: двойной клик по «# Saturni · Subs Move/# Saturni · Subs Move.pyw» (можно передать путь к .srt / видео).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "#Series", "@tools")
for p in (HERE, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    try:   # своя группа на панели задач — со своей иконкой
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Saturni.Subs")
    except Exception:
        pass

    import webview
    import server
    from api import Api, DATA_DIR

    dev = "--dev" in sys.argv
    srv, port = server.start(8766 if dev else 0)
    api = Api(port)
    if dev:                    # отладка UI в браузере: http://127.0.0.1:8766/?dev
        import time
        api._dev = []
        server.DEV_API = api
        print(f"DEV: http://127.0.0.1:{port}/?dev", flush=True)
        while True:
            time.sleep(3600)
    pl = (api._prefs.get("placement") or {}).get("rect")
    w, h = (pl[2] - pl[0], pl[3] - pl[1]) if pl else (1500, 920)
    dark = api._prefs.get("theme", "dark") != "light"
    window = webview.create_window(
        "Saturni · Subs Move", url=f"http://127.0.0.1:{port}/", js_api=api, width=w, height=h,
        x=pl[0] if pl else None, y=pl[1] if pl else None,
        min_size=(1100, 680), background_color="#0b0b0f" if dark else "#f1f1f4",
        text_select=False, zoomable=False, frameless=True, easy_drag=False, shadow=False)   # без большой тени: вместо неё тонкая обводка (DWM border)
    api._attach(window)

    def on_loaded():
        try:
            from webview.dom import DOMEventHandler

            def on_drop(e):
                files = (e.get("dataTransfer") or {}).get("files") or []
                paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
                if paths:
                    api._on_drop(paths)
            window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass

    window.events.loaded += on_loaded
    window.events.shown += lambda: api._win_style()
    window.events.maximized += api._on_maximized
    window.events.restored += api._on_restored
    window.events.closing += api._on_closing

    icon = os.path.join(HERE, "ui", "subs.ico")
    webview.start(debug="--debug" in sys.argv, gui="edgechromium", icon=icon if os.path.exists(icon) else None,
                  storage_path=os.path.join(DATA_DIR, "webview"), private_mode=False)
    try:
        srv.shutdown()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
