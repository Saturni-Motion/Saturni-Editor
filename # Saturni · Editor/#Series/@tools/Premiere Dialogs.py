# -*- coding: utf-8 -*-
r"""Окна-диалоги Premiere, которые держат скрипты (ExtendScript ждёт, пока их закроют).

    python "Premiere Dialogs.py"                 список диалогов + снимок каждого в _dialogs\<hwnd>.png
    python "Premiere Dialogs.py" enter [часть заголовка]    нажать кнопку по умолчанию (OK / Да)
    python "Premiere Dialogs.py" escape [часть заголовка]   отмена / закрыть
    python "Premiere Dialogs.py" auto            закрыть Enter-ом только известные безопасные (ошибки, предупреждения)
    python "Premiere Dialogs.py" watch [минут]   то же раз в 5 с в фоне; незнакомые — снимок и строка в _dialogs\log.txt

Окно не выводится вперёд и фокус не забирается: клавиша уходит сообщением прямо в окно, снимок — PrintWindow."""
import ctypes
import ctypes.wintypes as W
import os
import sys
import time

import psutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")



# region 💠 НАСТРОЙКИ


SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "1+2", "_work", "_dialogs")   # снимки диалогов
SAFE = ("File Import Failure", "Error", "Warning", "Media Offline", "Missing", "Unsupported",
        "Ошибка", "Предупреждение")       # заголовки, которые auto закрывает Enter-ом (там одна кнопка OK)
IGNORE = ("Encoding", "Rendering", "Exporting", "Conforming", "Progress")   # окна прогресса: закрываются сами
PROCESS = "adobe premiere pro.exe"

# endregion



# region 1️⃣ ПОИСК И КЛАВИШИ


u = ctypes.windll.user32
g = ctypes.windll.gdi32
KEYS = {"enter": (0x0D, 0x1C), "escape": (0x1B, 0x01)}


def dialogs():
    """Видимые окна-диалоги Premiere: (hwnd, заголовок, ширина, высота). Главное окно не берётся."""
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == PROCESS}
    out = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        pid = W.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(h) and u.GetWindow(h, 4):     # есть владелец = диалог
            t = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(h, t, 512)
            r = W.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            if r.right - r.left > 50 and r.bottom - r.top > 50 and not t.value.startswith(IGNORE):
                out.append((h, t.value, r.right - r.left, r.bottom - r.top))
        return True

    u.EnumWindows(cb, 0)
    return out


def children(h):
    res = []

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(c, _):
        if u.IsWindowVisible(c):
            res.append(c)
        return True

    u.EnumChildWindows(h, cb, 0)
    return res


def press(h, key):
    """Клавиша в окно без фокуса: и в само окно, и в его видимые части (в Premiere кнопки нарисованы внутри них)."""
    vk, sc = KEYS[key]
    for t in [h] + children(h):
        u.PostMessageW(t, 0x100, vk, 1 | (sc << 16))
        u.PostMessageW(t, 0x101, vk, 1 | (sc << 16) | (3 << 30))
        time.sleep(0.4)
        if not u.IsWindow(h) or not u.IsWindowVisible(h):
            return True
    return not u.IsWindow(h) or not u.IsWindowVisible(h)


def snapshot(h, w, hh):
    """Снимок окна через PrintWindow — окно не трогается, работает и за другими окнами."""
    os.makedirs(SHOTS, exist_ok=True)
    from PIL import Image
    dc = u.GetWindowDC(h)
    mem = g.CreateCompatibleDC(dc)
    bmp = g.CreateCompatibleBitmap(dc, w, hh)
    g.SelectObject(mem, bmp)
    u.PrintWindow(h, mem, 2)
    buf = ctypes.create_string_buffer(w * hh * 4)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD), ("biBitCount", W.WORD),
                    ("biCompression", W.DWORD), ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                    ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    g.GetDIBits(mem, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(h, dc)
    p = os.path.join(SHOTS, f"{h}.png")
    Image.frombuffer("RGBA", (w, hh), buf, "raw", "BGRA", 0, 1).convert("RGB").save(p)
    return p

# endregion



# region 2️⃣ ЗАПУСК


def watch(minutes):
    """Фоновый сторож на время долгой работы: безопасные закрывает, про незнакомые пишет один раз."""
    seen, end = set(), time.time() + minutes * 60
    os.makedirs(SHOTS, exist_ok=True)
    log = os.path.join(SHOTS, "log.txt")
    while time.time() < end:
        for h, title, w, hh in dialogs():
            if any(x.lower() in title.lower() for x in SAFE):
                shot = snapshot(h, w, hh)
                line = f"{time.strftime('%H:%M:%S')} «{title}» закрыт Enter: {press(h, 'enter')}, снимок {shot}"
            elif h not in seen:
                line = f"{time.strftime('%H:%M:%S')} «{title}» НЕЗНАКОМЫЙ, не трогаю, снимок {snapshot(h, w, hh)}"
            else:
                continue
            seen.add(h)
            open(log, "a", encoding="utf-8").write(line + "\n")
            print(line, flush=True)
        time.sleep(5)


def main():
    act = sys.argv[1] if len(sys.argv) > 1 else "list"
    if act == "watch":
        return watch(float(sys.argv[2]) if len(sys.argv) > 2 else 600)
    part = " ".join(sys.argv[2:]).lower()
    found = dialogs()
    if not found:
        print("диалогов нет")
        return
    for h, title, w, hh in found:
        if act == "list":
            print(f"{h}  «{title}»  {w}×{hh}  снимок {snapshot(h, w, hh)}")
        elif act in KEYS and part in title.lower():
            print(f"«{title}»: {act} →", "закрыт" if press(h, act) else "ОСТАЛСЯ")
        elif act == "auto":
            if any(s.lower() in title.lower() for s in SAFE):
                print(f"«{title}»: enter →", "закрыт" if press(h, "enter") else "ОСТАЛСЯ")
            else:
                print(f"«{title}»: неизвестный, не трогаю, снимок {snapshot(h, w, hh)}")


if __name__ == "__main__":
    main()

# endregion
