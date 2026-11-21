# -*- coding: utf-8 -*-
"""
winframe.py — окно без рамки, но с «настоящим» поведением Windows.

pywebview делает frameless-окно как WS_POPUP: у такого окна нет системной анимации
свернуть/развернуть, а «развернуть» закрывает панель задач. Здесь окну возвращаются
стили обычного окна (WS_CAPTION | WS_THICKFRAME), а рамка убирается через
WM_NCCALCSIZE: клиентская область = всё окно. В итоге:
  · развернуть/свернуть — штатная анимация Windows, Win+стрелки, прилипание к краям;
  · развёрнутое окно занимает рабочую область (панель задач видна), углы прямые.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
comctl32 = ctypes.windll.comctl32
dwmapi = ctypes.windll.dwmapi

LRESULT = ctypes.c_ssize_t
SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, ctypes.c_size_t,
                                  ctypes.c_ssize_t, ctypes.c_size_t, ctypes.c_size_t)
comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
comctl32.SetWindowSubclass.restype = wintypes.BOOL
comctl32.DefSubclassProc.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
comctl32.DefSubclassProc.restype = LRESULT
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
user32.MonitorFromRect.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]

WM_NCCALCSIZE, WM_SYSCOMMAND = 0x0083, 0x0112
SC_MINIMIZE, SC_MAXIMIZE, SC_RESTORE = 0xF020, 0xF030, 0xF120
GWL_STYLE = -16
WS_FRAME = 0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000   # CAPTION|THICKFRAME|MIN|MAX|SYSMENU


class _MI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _proc(hwnd, msg, wp, lp, _uid, _ref):
    try:
        if msg == WM_NCCALCSIZE and lp:
            if user32.IsZoomed(hwnd):
                # развёрнутое окно вылезает за экран на толщину рамки — ставим ровно рабочую область
                rc = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT))
                mi = _MI()
                mi.cbSize = ctypes.sizeof(_MI)
                if user32.GetMonitorInfoW(user32.MonitorFromRect(rc, 2), ctypes.byref(mi)):
                    w = mi.rcWork
                    rc[0].left, rc[0].top, rc[0].right, rc[0].bottom = w.left, w.top, w.right, w.bottom
            return 0                        # рамки нет: клиентская область = всё окно
    except Exception:
        pass
    return comctl32.DefSubclassProc(hwnd, msg, wp, lp)


_cb = SUBCLASSPROC(_proc)                   # ссылка должна жить, пока живо окно


def install(hwnd):
    """Вызывать в UI-потоке окна. True — системная рамка подключена."""
    if not comctl32.SetWindowSubclass(hwnd, _cb, 1, 0):
        return False
    st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, st | WS_FRAME)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)  # FRAMECHANGED
    return True


def zoomed(hwnd):
    return bool(user32.IsZoomed(hwnd))


def command(hwnd, sc):
    user32.PostMessageW(hwnd, WM_SYSCOMMAND, sc, 0)


def corners(hwnd, rounded):
    v = ctypes.c_int(2 if rounded else 1)   # DWMWCP_ROUND / DWMWCP_DONOTROUND
    dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(v), 4)
