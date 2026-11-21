#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@File Picker.py — общее окно выбора файлов/папок для root-скриптов стадий
пайплайна ("3.1. Basic Subtitles.py", "3.2. Auto Tune.py"), 2026-09-11.

Список слева (Listbox, множественный выбор), Add Files.../Add Folder(s).../
Remove/Clear справа, OK/Cancel снизу. OK ничего не запускает сам по себе —
только закрывает окно и отдаёт итоговый список путей вызывающему коду; сама
обработка стартует уже после, в main() лаунчера.

"Add Folder(s)..." даёт добавить НЕСКОЛЬКО папок подряд: обычный Windows-
диалог не умеет мульти-выбор папок в одном окне, поэтому он открывается в
цикле — Cancel в диалоге просто заканчивает добавление, а не закрывает всё
окно (это отдельное состояние от главного Cancel)."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox


def pick(title, file_types, folder_glob_hint="", geometry="640x420"):
    """Показывает окно выбора. Возвращает список путей (файлы и/или папки,
    в порядке добавления) или None, если нажали Cancel / закрыли крестиком.

    file_types: список (label, pattern) для askopenfilenames, например
        [("Видео", "*.mp4 *.mov *.mkv"), ("Все файлы", "*.*")]
    folder_glob_hint: короткая подсказка в статусной строке под списком,
        например "из папки берутся только *1h.mp4 верхнего уровня"."""
    root = tk.Tk()
    root.title(title)
    root.geometry(geometry)

    items = []

    frame = tk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    listbox = tk.Listbox(frame, selectmode=tk.EXTENDED)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar = tk.Scrollbar(frame, command=listbox.yview)
    scrollbar.pack(side=tk.LEFT, fill=tk.Y)
    listbox.config(yscrollcommand=scrollbar.set)

    side = tk.Frame(frame)
    side.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

    def refresh():
        listbox.delete(0, tk.END)
        for p in items:
            tag = "\U0001F4C1 " if os.path.isdir(p) else "\U0001F3AC "
            listbox.insert(tk.END, tag + p)

    def add_files():
        paths = filedialog.askopenfilenames(title="Выбери один или несколько файлов",
                                             filetypes=file_types, parent=root)
        for p in paths:
            if p not in items:
                items.append(p)
        refresh()

    def add_folders():
        # Один клик = одна папка (2026-09-11: цикл "выбрал -> сразу открылось
        # снова" читался как баг/самозапуск, не как "добавь ещё" — если нужно
        # несколько папок, жми кнопку несколько раз, как и Add Files... можно
        # жать повторно).
        d = filedialog.askdirectory(title="Выбери папку", parent=root)
        if not d:
            return
        if d not in items:
            items.append(d)
        refresh()

    def remove_sel():
        for i in reversed(listbox.curselection()):
            del items[i]
        refresh()

    def clear_all():
        items.clear()
        refresh()

    tk.Button(side, text="Add Files...", width=16, command=add_files).pack(pady=(0, 4))
    tk.Button(side, text="Add Folder(s)...", width=16, command=add_folders).pack(pady=4)
    tk.Button(side, text="Remove", width=16, command=remove_sel).pack(pady=4)
    tk.Button(side, text="Clear", width=16, command=clear_all).pack(pady=4)

    if folder_glob_hint:
        tk.Label(root, text=folder_glob_hint, fg="#666666",
                 anchor="w").pack(fill=tk.X, padx=12)

    bottom = tk.Frame(root)
    bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))

    result = {"ok": False}

    def on_ok():
        if not items:
            messagebox.showwarning(title, "Список пуст — добавь файлы или папки.")
            return
        result["ok"] = True
        root.destroy()

    def on_cancel():
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    tk.Button(bottom, text="Cancel", width=12, command=on_cancel).pack(side=tk.RIGHT)
    tk.Button(bottom, text="OK", width=12, command=on_ok).pack(side=tk.RIGHT, padx=(0, 8))

    root.mainloop()
    return list(items) if result["ok"] else None
