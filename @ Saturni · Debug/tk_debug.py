# -*- coding: utf-8 -*-
"""
Saturni · Debug в приложениях на tkinter: та же шестерёнка, что и в WebView-приложениях.
Ctrl+клик по шестерёнке — отладка (накладка overlay.py поверх снимка экрана), правый клик — меню
с пунктом Debug, у угла шестерёнки — число заметок (жёлтая цифра), в самом углу при наведении — жучок.

  sys.path.insert(0, <Hub>\\@ Saturni · Debug); import tk_debug
  tk_debug.attach_gear(gear_widget, app_dir, "Saturni · Имя")
"""
import json
import os
import subprocess
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saturni_debug import debug_root, session_dir  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _count(debug_dir):
    """Заметок в текущей сессии (debug_dir — папка программы, её ⿻\\@debug или старый #debug)."""
    try:
        with open(os.path.join(session_dir(debug_root(debug_dir), create=False), "debug.json"), encoding="utf-8") as f:
            return len(json.load(f).get("notes", []))
    except Exception:
        return 0


def open_debug(app_dir, app):
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    subprocess.Popen([exe if os.path.exists(exe) else sys.executable, os.path.join(HERE, "overlay.py"),
                      "--dir", debug_root(app_dir), "--app", app], creationflags=0x08000000)


def attach_gear(gear, app_dir, app, bg_dark="#16161c", fg="#ffd166"):
    debug_dir = debug_root(app_dir)
    gear.bind("<Control-Button-1>", lambda e: (open_debug(app_dir, app), "break")[1])

    def menu(e):
        m = tk.Menu(gear, tearoff=0, bg="#121218", fg="#c8c8d0", activebackground="#121218", activeforeground="#ffffff",
                    bd=0, relief="flat", font=("Segoe UI", 10))
        n = _count(debug_dir)
        m.add_command(label=f"  Debug        {str(n) + ' · ' if n else ''}Ctrl+click", command=lambda: open_debug(app_dir, app))
        if n:
            m.add_command(label="  Notes folder", command=lambda: subprocess.Popen(["explorer", os.path.normpath(debug_dir)]))
        m.tk_popup(e.x_root, e.y_root)
        return "break"
    gear.bind("<Button-3>", menu)

    # число заметок — просто жёлтая цифра у правого края значка; мышь в правом верхнем углу кнопки —
    # вместо цифры жучок на той же строке (как в debug.js): клик — отладка, правый клик — прошлые сессии правок
    parent = gear.master
    try:
        pbg = parent.cget("bg")
    except tk.TclError:
        pbg = "#000000"
    st = {"n": -1, "corner": False}
    num = tk.Label(parent, text="", fg=fg, bg=pbg, bd=0, padx=0, pady=0, font=("Inter", 7, "bold"), anchor="w")
    k = 13 / 16.2                                                     # жучок 13 px высотой, viewBox 3.4 3.6 17.2 16.2
    W, H = 14, 13
    bug = tk.Canvas(parent, width=W, height=H, bg=pbg, highlightthickness=0, bd=0, cursor="hand2")
    P = lambda *xy: [(v - (3.4 if i % 2 == 0 else 3.6)) * k for i, v in enumerate(xy)]   # noqa: E731
    lw = 1.8 * k
    bug.create_arc(*P(9.2, 4.8, 14.8, 10.4), start=0, extent=180, style="arc", outline=fg, width=lw)
    bug.create_oval(*P(8, 8.6, 16, 17.8), outline=fg, width=lw)
    for a in ((8.3, 10.4, 6.1, 9.1, 5.3, 7.8), (8, 13.2, 4.6, 13.2), (8.3, 16, 6.1, 17.3, 5.3, 18.6),
              (15.7, 10.4, 17.9, 9.1, 18.7, 7.8), (16, 13.2, 19.4, 13.2), (15.7, 16, 17.9, 17.3, 18.7, 18.6)):
        bug.create_line(*P(*a), fill=fg, width=lw, capstyle="round", joinstyle="round", smooth=len(a) > 4)
    bug.bind("<Button-1>", lambda e: open_debug(app_dir, app))

    def history(e):                                                    # прошлые сессии: папка со снимками и notes.md
        root = debug_root(app_dir)
        cur = os.path.basename(session_dir(root, create=False) or "")
        m = tk.Menu(gear, tearoff=0, bg="#121218", fg="#c8c8d0", activebackground="#121218", activeforeground="#ffffff",
                    bd=0, relief="flat", font=("Segoe UI", 10))
        try:
            names = [x for x in sorted(os.listdir(root), reverse=True) if x != cur and os.path.isfile(os.path.join(root, x, "debug.json"))]
        except OSError:
            names = []
        for name in names[:20]:
            d = os.path.join(root, name)
            mark = "✓ " if os.path.isfile(os.path.join(d, "done.json")) else "   "
            m.add_command(label=f"  {mark}{name.replace('-', ':', 3).replace(':', '-', 2)}",
                          command=lambda d=d: subprocess.Popen(["explorer", os.path.normpath(d)]))
        if not names:
            m.add_command(label="  No past notes yet", state="disabled")
        m.tk_popup(e.x_root, e.y_root)
        return "break"
    bug.bind("<Button-3>", history)

    def place():
        if not gear.winfo_ismapped():
            num.place_forget(); bug.place_forget(); return
        x, y, w = gear.winfo_x(), gear.winfo_y(), gear.winfo_width()
        nx = x + w // 2 + 7                                            # где начинаются цифры
        if st["corner"]:
            num.place_forget()
            mid = y + 2 + num.winfo_reqheight() // 2                   # середина строки цифр
            bug.place(x=nx + 1, y=mid - H // 2)
            tk.Misc.lift(bug)                                          # у Canvas lift() — это подъём фигур
        else:
            bug.place_forget()
            if st["n"] > 0:
                num.configure(text=str(st["n"]))
                num.place(x=nx, y=y + 2)
                num.lift()
            else:
                num.place_forget()
    def motion(e):
        corner = e.x > gear.winfo_width() * .62 and e.y < gear.winfo_height() * .38
        if corner != st["corner"]:
            st["corner"] = corner; place()

    def leave(e):
        def later():                                                   # мышь могла перейти на сам жучок
            px, py = gear.winfo_pointerxy()
            over = gear.winfo_containing(px, py)
            if over not in (gear, bug):
                st["corner"] = False; place()
        gear.after(80, later)
    gear.bind("<Motion>", motion, add="+")
    gear.bind("<Leave>", leave, add="+")
    bug.bind("<Leave>", leave)

    def refresh():
        if not gear.winfo_exists():
            return
        n = _count(debug_dir)
        if n != st["n"]:
            st["n"] = n
        place()
        gear.after(1500, refresh)
    gear.after(300, refresh)
