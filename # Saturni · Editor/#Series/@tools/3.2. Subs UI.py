#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3.2. Subs UI.py — window of stage 3.2 "Build subtitles" (2026-09-28, Saturni's design: variant 2
"sidebar", English UI). Minimal dark/light grey, blue only as accent, no frames except buttons.

  • top-right: theme toggle (left click = dark/light; right click = colour settings for every
    role, saved to 3.2. Subs UI-Settings.json) and, left of it, show/hide the log panel;
  • list: one line per file (name + dim description), × on hover removes it, × next to
    "Files" clears the list;
  • sidebar: "Folder" (folder with plus) and "Video" (plus) — grey icon, white text, icon turns
    blue on hover; option "Overwrite existing .srt";
  • bottom line: status · progress bar · round "Build subtitles".

Videos (.mp4/.mov/.mkv) or folders → autonomous build of `<name>.srt` next to the video
(@tools/3.2. Subs Assemble.py) + check (@tools/3.2. Auto Tune.py). A ready .srt → check + autofix only.
"""
import json, os, queue, sys, threading, traceback
import tkinter as tk
from tkinter import filedialog, colorchooser, font as tkfont

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
SETTINGS = os.path.join(HERE, "3.2. Subs UI-Settings.json")

import importlib.util as _ilu
_TOOLS = HERE


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



DEFAULTS = {
    "dark": {"Background": "#1E1F22", "Sidebar": "#232428", "Log panel": "#232428", "Hover": "#2B2D31",
             "Divider": "#2C2E33", "Toggle off": "#3F4147", "Text": "#DBDEE1",
             "Muted text": "#949BA4", "Dim text": "#6D727A", "Accent": "#3B82F6"},
    "light": {"Background": "#FFFFFF", "Sidebar": "#F4F5F7", "Log panel": "#F4F5F7", "Hover": "#F1F2F4",
              "Divider": "#E6E8EB", "Toggle off": "#C9CDD3", "Text": "#16181D",
              "Muted text": "#636A75", "Dim text": "#9AA0A8", "Accent": "#2563EB"},
}
OK, WARN, ERR = "#34C759", "#FFB340", "#FF5F57"
FONT, ICONS = "Segoe UI", "Segoe Fluent Icons"
IC = {"folder": "", "video": "", "go": "", "x": "", "sun": "",
      "moon": "", "log": ""}
VIDEO_EXT = (".mp4", ".mov", ".mkv")
C = dict(DEFAULTS["dark"])


def load_settings():
    s = {"theme": "dark", "log": True, "colors": {"dark": {}, "light": {}}}
    try:
        s.update(json.load(open(SETTINGS, encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        json.dump(s, open(SETTINGS, "w", encoding="utf-8"), indent=1)
    except Exception:
        pass


def _rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _shade(c, k):
    return "#" + "".join(f"{max(0, min(255, int(v * k))):02x}" for v in _rgb(c))


def _rr(w, h, r, fill, bg, ss=3):
    from PIL import Image, ImageDraw, ImageTk
    img = Image.new("RGB", (w * ss, h * ss), _rgb(bg))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=min(r, h // 2) * ss, fill=_rgb(fill))
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))


class BigButton(tk.Canvas):
    """Sidebar action: grey icon + text; on hover only the icon turns blue."""

    def __init__(self, master, text, icon, command, width, height=46):
        super().__init__(master, width=width, height=height, bg=master["bg"], highlightthickness=0, cursor="hand2")
        self.text, self.icon, self.command, self.w, self.h = text, icon, command, width, height
        self.fi, self.f = tkfont.Font(family=ICONS, size=17), tkfont.Font(family=FONT, size=12)
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<Button-1>", lambda e: self.command())
        self._draw(False)

    def _draw(self, hover):
        self.delete("all")
        self.create_text(4, self.h // 2, text=self.icon, anchor="w", font=self.fi,
                         fill=C["Accent"] if hover else C["Muted text"])
        self.create_text(42, self.h // 2, text=self.text, anchor="w", font=self.f, fill=C["Text"])


class IconButton(tk.Canvas):
    def __init__(self, master, icon, command, size=28, icon_size=12, tip=None, right=None):
        super().__init__(master, width=size, height=size, bg=master["bg"], highlightthickness=0, cursor="hand2")
        self.icon, self.command, self.s, self.f = icon, command, size, tkfont.Font(family=ICONS, size=icon_size)
        self.active = False
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<Button-1>", lambda e: self.command())
        if right:
            self.bind("<Button-3>", lambda e: right())
        self._draw(False)

    def set_icon(self, icon, active=None):
        self.icon = icon
        if active is not None:
            self.active = active
        self._draw(False)

    def _draw(self, hover):
        self.delete("all")
        col = C["Accent"] if (hover or self.active) else C["Muted text"]
        self.create_text(self.s // 2, self.s // 2, text=self.icon, font=self.f, fill=col)


class PillButton(tk.Canvas):
    def __init__(self, master, text, icon, command, height=34):
        self.f, self.fi = tkfont.Font(family=FONT, size=10, weight="bold"), tkfont.Font(family=ICONS, size=10)
        w = self.fi.measure(icon) + 8 + self.f.measure(text) + 44
        super().__init__(master, width=w, height=height, bg=master["bg"], highlightthickness=0, cursor="hand2")
        self.text, self.icon, self.command, self.w, self.h = text, icon, command, w, height
        self.enabled, self.hover, self._img = True, False, None
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())
        self._draw()

    def _set(self, h):
        self.hover = h
        self._draw()

    def set_enabled(self, on):
        self.enabled = on
        self.config(cursor="hand2" if on else "arrow")
        self._draw()

    def _draw(self):
        self.delete("all")
        fill = C["Accent"] if self.enabled else C["Toggle off"]
        if self.hover and self.enabled:
            fill = _shade(fill, 1.12)
        self._img = _rr(self.w, self.h, self.h // 2, fill, self["bg"])
        self.create_image(0, 0, image=self._img, anchor="nw")
        fg = "#FFFFFF" if self.enabled else C["Muted text"]
        x0 = (self.w - (self.fi.measure(self.icon) + 8 + self.f.measure(self.text))) // 2
        self.create_text(x0, self.h // 2, text=self.icon, font=self.fi, fill=fg, anchor="w")
        self.create_text(x0 + self.fi.measure(self.icon) + 8, self.h // 2, text=self.text, font=self.f, fill=fg, anchor="w")


class Switch(tk.Canvas):
    def __init__(self, master, text, value=False, on_change=None):
        self.f = tkfont.Font(family=FONT, size=9)
        super().__init__(master, width=38 + self.f.measure(text), height=22, bg=master["bg"],
                         highlightthickness=0, cursor="hand2")
        self.text, self.value, self.on_change, self._imgs = text, value, on_change, []
        self.bind("<Button-1>", lambda e: self.flip())
        self._draw()

    def flip(self):
        self.value = not self.value
        self._draw()
        if self.on_change:
            self.on_change(self.value)

    def _draw(self):
        from PIL import Image, ImageDraw, ImageTk
        self.delete("all")
        track = _rr(28, 16, 8, C["Accent"] if self.value else C["Toggle off"], self["bg"])
        k = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
        ImageDraw.Draw(k).ellipse([0, 0, 35, 35], fill=(255, 255, 255, 255))
        knob = ImageTk.PhotoImage(k.resize((12, 12), Image.LANCZOS))
        self._imgs = [track, knob]
        self.create_image(0, 3, image=track, anchor="nw")
        self.create_image(14 if self.value else 2, 5, image=knob, anchor="nw")
        self.create_text(38, 11, text=self.text, anchor="w", font=self.f,
                         fill=C["Text"] if self.value else C["Muted text"])


class Bar(tk.Canvas):
    def __init__(self, master, height=4):
        super().__init__(master, height=height, bg=master["bg"], highlightthickness=0)
        self.h, self.frac = height, 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, frac):
        self.frac = max(0.0, min(1.0, frac))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        self.create_rectangle(0, 0, w, self.h, fill=C["Hover"], outline="")
        if self.frac > 0:
            self.create_rectangle(0, 0, int(w * self.frac), self.h, fill=C["Accent"], outline="")


class App:
    SIDE_W = 176

    def __init__(self, preset=None):
        self.cfg = load_settings()
        sa = _tool("subs_assemble", "3.2. Subs Assemble.py")
        self.sa = sa
        self.root = tk.Tk()
        self.root.title("3.2 · Build subtitles")
        self.root.geometry("720x560")
        self.root.minsize(620, 440)
        self.items, self.q, self.running = [], queue.Queue(), False
        self.overwrite = False
        self.status_text, self.progress = "Ready", 0.0
        self.log_lines = [("Report appears here after the build.\n", "mut")]
        self._apply_palette()
        self._build()
        for p in preset or []:
            self._add(p)
        self.root.after(80, self._poll)

    # ---------- theme
    def _apply_palette(self):
        global C
        th = self.cfg["theme"]
        C = dict(DEFAULTS[th])
        C.update(self.cfg["colors"].get(th, {}))

    def _toggle_theme(self):
        self.cfg["theme"] = "light" if self.cfg["theme"] == "dark" else "dark"
        save_settings(self.cfg)
        self._rebuild()

    def _toggle_log(self):
        self.cfg["log"] = not self.cfg["log"]
        save_settings(self.cfg)
        self._rebuild()

    def _rebuild(self):
        self._apply_palette()
        for w in self.root.winfo_children():
            w.destroy()
        items = self.items
        self.items = []
        self._build()
        for it in items:
            self.items.append(it)
            self._row(it)
        self._count()

    def _colors_dialog(self):
        th = self.cfg["theme"]
        win = tk.Toplevel(self.root)
        win.title(f"Colors · {th}")
        win.configure(bg=C["Background"])
        win.resizable(False, False)
        win.transient(self.root)
        tk.Label(win, text=f"Colors — {th} theme", bg=C["Background"], fg=C["Text"],
                 font=(FONT, 12, "bold")).pack(anchor="w", padx=18, pady=(14, 8))
        grid = tk.Frame(win, bg=C["Background"])
        grid.pack(padx=18, pady=(0, 8))
        swatches = {}

        def pick(role):
            cur = self.cfg["colors"].setdefault(th, {}).get(role, DEFAULTS[th][role])
            res = colorchooser.askcolor(color=cur, parent=win, title=role)
            if res and res[1]:
                self.cfg["colors"][th][role] = res[1].upper()
                save_settings(self.cfg)
                self._rebuild()
                win.destroy()
                self._colors_dialog()

        for r, role in enumerate(DEFAULTS[th]):
            val = self.cfg["colors"].get(th, {}).get(role, DEFAULTS[th][role])
            tk.Label(grid, text=role, bg=C["Background"], fg=C["Text"], font=(FONT, 10), anchor="w", width=14).grid(row=r, column=0, sticky="w", pady=3)
            sw = tk.Canvas(grid, width=44, height=20, bg=val, highlightthickness=1,
                           highlightbackground=C["Divider"], cursor="hand2")
            sw.grid(row=r, column=1, padx=10)
            sw.bind("<Button-1>", lambda e, role=role: pick(role))
            tk.Label(grid, text=val, bg=C["Background"], fg=C["Muted text"], font=("Consolas", 9)).grid(row=r, column=2, sticky="w")
            swatches[role] = sw

        def reset():
            self.cfg["colors"][th] = {}
            save_settings(self.cfg)
            self._rebuild()
            win.destroy()
            self._colors_dialog()
        bot = tk.Frame(win, bg=C["Background"])
        bot.pack(fill=tk.X, padx=18, pady=(4, 16))
        tk.Label(bot, text="Reset to defaults", bg=C["Background"], fg=C["Accent"], font=(FONT, 10),
                 cursor="hand2").pack(side=tk.LEFT)
        bot.winfo_children()[-1].bind("<Button-1>", lambda e: reset())
        tk.Label(bot, text="Close", bg=C["Background"], fg=C["Muted text"], font=(FONT, 10),
                 cursor="hand2").pack(side=tk.RIGHT)
        bot.winfo_children()[-1].bind("<Button-1>", lambda e: win.destroy())

    # ---------- layout
    def _build(self):
        BG, P = C["Background"], 18
        self.root.configure(bg=BG)
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill=tk.X, padx=(P, 10), pady=(12, 10))
        tk.Label(head, text="Build subtitles", bg=BG, fg=C["Text"], font=(FONT, 14, "bold")).pack(side=tk.LEFT)
        tk.Label(head, text="3.2", bg=BG, fg=C["Accent"], font=(FONT, 14, "bold")).pack(side=tk.LEFT, padx=(8, 0))
        dark = self.cfg["theme"] == "dark"
        IconButton(head, IC["sun"] if dark else IC["moon"], self._toggle_theme, right=self._colors_dialog).pack(side=tk.RIGHT)
        IconButton(head, IC["log"], self._toggle_log).pack(side=tk.RIGHT, padx=(0, 2))
        head.winfo_children()[-1].set_icon(IC["log"], active=self.cfg["log"])
        tk.Frame(self.root, bg=C["Divider"], height=1).pack(fill=tk.X)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)
        side = tk.Frame(body, bg=C["Sidebar"], width=self.SIDE_W + 2 * P)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)
        tk.Frame(body, bg=C["Divider"], width=1).pack(side=tk.RIGHT, fill=tk.Y)
        left = tk.Frame(body, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # list header: "Files · N" + clear-all ×
        lh = tk.Frame(left, bg=BG)
        lh.pack(fill=tk.X, padx=(P, 12), pady=(10, 4))
        self.count_lbl = tk.Label(lh, text="Files", bg=BG, fg=C["Muted text"], font=(FONT, 9))
        self.count_lbl.pack(side=tk.LEFT)
        self.clear_btn = IconButton(lh, IC["x"], self._clear, size=20, icon_size=8)
        self.clear_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.cv = tk.Canvas(left, bg=BG, highlightthickness=0)
        self.lf = tk.Frame(self.cv, bg=BG)
        self.lf.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self._win = self.cv.create_window((0, 0), window=self.lf, anchor="nw")
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._win, width=e.width))
        self.cv.pack(fill=tk.BOTH, expand=True, padx=(P - 8, 8))
        self.cv.bind_all("<MouseWheel>", lambda e: self.cv.yview_scroll(int(-e.delta / 120), "units"))
        self.empty = tk.Label(self.lf, text="Add videos after 3.1\nor a folder with them", bg=BG,
                              fg=C["Dim text"], font=(FONT, 10), justify="center")
        self.empty.pack(pady=70)
        self.empty_shown = True

        # sidebar
        sb = C["Sidebar"]
        inner = tk.Frame(side, bg=sb)
        inner.pack(fill=tk.BOTH, expand=True, padx=P, pady=(14, 14))
        BigButton(inner, "Folder", IC["folder"], self._add_folder, self.SIDE_W).pack(anchor="w")
        BigButton(inner, "Video", IC["video"], self._add_files, self.SIDE_W).pack(anchor="w", pady=(2, 0))
        tk.Frame(inner, bg=C["Divider"], height=1).pack(fill=tk.X, pady=14)
        self.sw_over = Switch(inner, "Overwrite existing .srt", self.overwrite,
                              on_change=lambda v: setattr(self, "overwrite", v))
        self.sw_over.pack(anchor="w")

        # bottom line: status · progress · Build
        tk.Frame(self.root, bg=C["Divider"], height=1).pack(fill=tk.X)
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill=tk.X, padx=P, pady=10)
        self.status = tk.Label(foot, text=self.status_text, bg=BG, fg=C["Muted text"], font=(FONT, 9),
                               anchor="w", width=15)
        self.status.pack(side=tk.LEFT)
        self.go = PillButton(foot, "Build subtitles", IC["go"], self._start)
        self.go.pack(side=tk.RIGHT)
        self.bar = Bar(foot)
        self.bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 16))
        self.root.after(50, lambda: self.bar.set(self.progress))
        if self.running:
            self.go.set_enabled(False)

        self.log = tk.Text(self.root, height=6, bg=C["Log panel"], fg=C["Text"], relief="flat", font=("Consolas", 9),
                           wrap="word", padx=P, pady=10, highlightthickness=0, bd=0)
        for tag, col in (("ok", OK), ("warn", WARN), ("err", ERR), ("mut", C["Muted text"])):
            self.log.tag_configure(tag, foreground=col)
        if self.cfg["log"]:
            self.log.pack(fill=tk.X)
        for s, tag in self.log_lines:
            self.log.insert(tk.END, s, tag)
        self.log.config(state="disabled")

    # ---------- list
    def _classify(self, p):
        if p.lower().endswith(".srt"):
            return "srt", ".srt check"
        src = self.sa.find_input(p)
        return "video", (None if not src else "words.json" if src.endswith(".json") else "3.1 words")

    def _add(self, p):
        p = os.path.normpath(p)
        if os.path.isdir(p):
            import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
            sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
            if sb is None:
                _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
                sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(sb)
            for f in sorted((os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(VIDEO_EXT)),
                            key=lambda f: sb.natural_sort_key(os.path.basename(f))):
                self._add(f)
            return
        if not os.path.isfile(p) or any(it["path"] == p for it in self.items):
            return
        kind, inp = self._classify(p)
        ready = kind == "srt" or bool(inp)
        it = {"path": p, "kind": kind, "input": inp, "state": ("ready" if ready else "no 3.1"),
              "state_col": None if ready else ERR}
        self.items.append(it)
        self._row(it)
        self._count()

    def _row(self, it):
        BG = C["Background"]
        if self.empty_shown:
            self.empty.pack_forget()
            self.empty_shown = False
        row = tk.Frame(self.lf, bg=BG)
        row.pack(fill=tk.X)
        name = os.path.splitext(os.path.basename(it["path"]))[0].replace(" ` 1h", "")
        desc = os.path.basename(os.path.dirname(it["path"])) + " · " + (it["input"] or "no 3.1 words")
        l1 = tk.Label(row, text=name, bg=BG, fg=C["Text"], font=(FONT, 10, "bold"), anchor="w")
        l1.pack(side=tk.LEFT, padx=(8, 0), pady=6)
        l2 = tk.Label(row, text=desc, bg=BG, fg=C["Dim text"], font=(FONT, 8), anchor="w")
        l2.pack(side=tk.LEFT, padx=(8, 0))
        xb = tk.Label(row, text=IC["x"], bg=BG, fg=BG, font=(ICONS, 8), cursor="hand2")
        xb.pack(side=tk.RIGHT, padx=(6, 8))
        badge = tk.Label(row, text=it["state"], bg=BG, fg=it["state_col"] or C["Muted text"], font=(FONT, 9))
        badge.pack(side=tk.RIGHT)
        paint = [row, l1, l2, badge, xb]
        it.update(row=row, badge=badge, xb=xb, paint=paint)

        def color(bg, it=it, show_x=False):
            for w in it["paint"]:
                w.configure(bg=bg)
            it["xb"].configure(fg=C["Muted text"] if show_x else bg)
        for w in paint:
            w.bind("<Enter>", lambda e, it=it: color(C["Hover"], it, True))
            w.bind("<Leave>", lambda e, it=it: color(C["Background"], it, False))
        xb.bind("<Enter>", lambda e, it=it: (color(C["Hover"], it, True), it["xb"].configure(fg=ERR)))
        xb.bind("<Button-1>", lambda e, it=it: self._remove(it))

    def _count(self):
        self.count_lbl.config(text=f"Files · {len(self.items)}" if self.items else "Files")
        if not self.items and not self.empty_shown:
            self.empty.pack(pady=70)
            self.empty_shown = True

    def _add_files(self):
        for p in filedialog.askopenfilenames(parent=self.root, title="Videos after 3.1 or ready .srt",
                                             filetypes=[("Video and subtitles", "*.mp4 *.mov *.mkv *.srt"), ("All files", "*.*")]):
            self._add(p)

    def _add_folder(self):
        d = filedialog.askdirectory(parent=self.root, title="Folder with videos")
        if d:
            self._add(d)

    def _remove(self, it):
        if self.running:
            return
        it["row"].destroy()
        self.items.remove(it)
        self._count()

    def _clear(self):
        if self.running:
            return
        for it in self.items:
            it["row"].destroy()
        self.items.clear()
        self._count()

    # ---------- work
    def _log(self, s, tag=None):
        self.log_lines.append((s, tag))
        self.log.config(state="normal")
        self.log.insert(tk.END, s, tag)
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def _start(self):
        if self.running or not self.items:
            return
        self.running = True
        self.go.set_enabled(False)
        self.log_lines = []
        self.log.config(state="normal"); self.log.delete("1.0", tk.END); self.log.config(state="disabled")
        threading.Thread(target=self._worker, args=(list(self.items), self.overwrite), daemon=True).start()

    def _worker(self, items, over):
        auto_tune = _tool("auto_tune", "3.2. Auto Tune.py")
        n, ok_n = len(items), 0
        for k, it in enumerate(items):
            name = os.path.splitext(os.path.basename(it["path"]))[0].replace(" ` 1h", "")
            short = name if len(name) <= 8 else name[:7] + "…"
            self.q.put(("status", f"{k + 1} of {n} · {short}", k / n))
            try:
                if it["kind"] == "srt":
                    cues = auto_tune.parse_srt(it["path"])
                    fixes = auto_tune.autofix(cues)
                    if sum(fixes.values()):
                        auto_tune.write_srt(cues, it["path"])
                    self.q.put(("row", it, "checked", OK))
                    self.q.put(("report", name, auto_tune.analyze(cues)))
                else:
                    src = self.sa.find_input(it["path"])
                    if not src:
                        self.q.put(("row", it, "no 3.1", ERR))
                        self.q.put(("line", f"✕ {name} — no words from 3.1\n", "err"))
                        continue
                    out = os.path.splitext(it["path"])[0] + ".srt"
                    if os.path.exists(out) and not over:
                        self.q.put(("row", it, "exists", WARN))
                        self.q.put(("line", f"• {name} — .srt already exists, skipped\n", "warn"))
                        continue
                    self.sa.assemble_file(src, out, it["path"])
                    st = auto_tune.analyze(auto_tune.parse_srt(out))
                    cov = self.sa.coverage(src, it["path"])
                    low = cov is not None and cov < 0.4
                    self.q.put(("row", it, "low speech" if low else "built", WARN if low else OK))
                    self.q.put(("report", name, st))
                    if low:
                        self.q.put(("line", f"   speech covers only {cov * 100:.0f}% of the clip — check manually\n", "warn"))
                ok_n += 1
            except Exception as e:
                self.q.put(("row", it, "error", ERR))
                self.q.put(("line", f"✕ {name} — {e}\n{traceback.format_exc(limit=2)}", "err"))
        self.q.put(("status", f"Done: {ok_n} of {n}", 1.0))
        self.q.put(("done",))

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "status":
                    self.status_text, self.progress = m[1], m[2]
                    self.status.config(text=m[1], fg=C["Text"])
                    self.bar.set(m[2])
                elif m[0] == "row":
                    it = m[1]
                    it["state"], it["state_col"] = m[2], m[3]
                    if it in self.items and it["badge"].winfo_exists():
                        it["badge"].config(text=m[2], fg=m[3])
                elif m[0] == "line":
                    self._log(m[1], m[2])
                elif m[0] == "report":
                    _, name, st = m
                    self._log("✓ ", "ok")
                    self._log(f"{name}  ")
                    self._log(f"{st['n']} cues · median {st['median_ms']} ms · single-word "
                              f"{st['one_word_pct'] * 100:.0f}%\n", "mut")
                    for key, label in (("over_cap", "longer than 1.5 s"), ("hanging", "hanging word"),
                                       ("repeats", "repeat without hyphen")):
                        if st.get(key):
                            self._log(f"   {label}: {len(st[key])} — " + "; ".join(repr(t) for *_, t in st[key][:2]) + "\n", "warn")
                elif m[0] == "done":
                    self.running = False
                    self.go.set_enabled(True)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def run(self):
        self.root.mainloop()


def launch(preset=None):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            h = ctypes.windll.kernel32.GetConsoleWindow()
            if h:
                ctypes.windll.user32.ShowWindow(h, 0)
        except Exception:
            pass
    App(preset).run()


if __name__ == "__main__":
    launch(sys.argv[1:])
