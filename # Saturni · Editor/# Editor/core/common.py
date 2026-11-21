# -*- coding: utf-8 -*-
r"""Saturni · Editor: общие константы, пути программы, Корзина, Saturni · Debug."""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]          # # Editor
HUB = APP_DIR.parents[1]                               # D:\@Hub
DEBUG_DIR = str(HUB / "@ Saturni · Debug")
try:                                          # Saturni · Debug: notes drawn over the window (Ctrl+click the gear)
    sys.path.insert(0, DEBUG_DIR)
    from saturni_debug import DebugMixin, STATIC_DIR as DEBUG_STATIC
except Exception:
    DebugMixin, DEBUG_STATIC = object, None

NO_WINDOW = 0x08000000      # CREATE_NO_WINDOW: no console flashing up for ffmpeg
WAVE_SAMPLES = 20_000_000   # waveform data per stream at most this long (rate lowered for long files)
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MEDIA_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
PLAYABLE = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac"}       # the browser plays these files as they are
PROJECT_EXT = ".sedit"       # a project: the files used and everything done to them (JSON)
COPY_EXT = {"aac": ".m4a", "mp3": ".mp3", "opus": ".webm", "vorbis": ".webm", "flac": ".flac"}



def recycle(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    op = SHFILEOPSTRUCTW(None, 3, str(path) + "\0", None, 0x40 | 0x10 | 0x04 | 0x400, False, None, None)
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))      # FO_DELETE + ALLOWUNDO = Recycle Bin



def interp(pts: list, t: float) -> float:
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, g0), (t1, g1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return g0 if t1 - t0 <= 1e-9 else g0 + (g1 - g0) * (t - t0) / (t1 - t0)
    return pts[-1][1]
