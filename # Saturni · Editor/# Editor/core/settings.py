# -*- coding: utf-8 -*-
r"""Saturni · Editor: цвета и параметры. Значения Saturni лежат в # Editor\@settings.json, их пишет панель Settings."""
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

from common import APP_DIR

DEFAULT_COLORS = {
    "bg": "#0f1012", "panel": "#1b1c20", "text": "#e9eaec", "accent": "#3d9bff", "stage": "#000000",
    "timeline": "#17181b", "ruler": "#7c7f86", "playhead": "#3d9bff", "keep": "#8fe0ad", "removed": "#45474c",
    "cut": "#ff6b6b", "selection": "#3d9bff", "trim": "#8fe0ad", "volume": "#ffffff", "fade": "#c59bff",
    "grid": "#ffffff", "clip": "#5b8def", "meterLow": "#5fae7d", "meterMid": "#d9c66a", "meterHigh": "#e0705f",
    "overview": "#3d9bff", "overviewBg": "#1a1b1f", "overviewView": "#7cc8ff",
}
DEFAULT_OPTIONS = {"photoQuality": 0, "playMode": "fast", "preview": 1, "loop": False, "meterMin": -60, "meterMax": 6, "overwrite": False}

SETTINGS_FILE = APP_DIR / "@settings.json"
try:
    _saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
except Exception:
    _saved = {}
COLORS = {**DEFAULT_COLORS, **_saved.get("colors", {})}          # a color added later still gets its default
OPTIONS = {**DEFAULT_OPTIONS, **_saved.get("options", {})}
STATE = _saved.get("state", {})            # what the window remembers by itself: layouts, recent files and projects


def write_settings(colors: dict, options: dict) -> None:
    data = {"colors": {k: colors.get(k, d).lower() for k, d in DEFAULT_COLORS.items()}, "options": options, "state": STATE}
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def write_state(key: str, value) -> None:
    STATE[key] = value
    write_settings(COLORS, OPTIONS)


def remember_recent(path: Path, key: str = "recent", keep: int = 12) -> None:
    """Newest first, no repeats, only what still exists."""
    p = str(path)
    STATE[key] = [p] + [q for q in STATE.get(key, []) if q != p and Path(q).exists()][:keep - 1]
    write_settings(COLORS, OPTIONS)


COLOR_NAMES = {
    "bg": "Window background", "panel": "Menus and panels", "text": "Text and icons", "accent": "Accent (buttons)",
    "stage": "Behind the picture", "timeline": "Timeline background", "ruler": "Ruler: time marks",
    "playhead": "Playhead", "keep": "Kept wave", "removed": "Removed wave", "cut": "Cut-out stripes",
    "selection": "Selection", "trim": "Start / End", "volume": "Volume line and keys", "fade": "Fades",
    "grid": "Wave dB numbers", "clip": "Clips on tracks (Pro)", "meterLow": "Meter: quiet",
    "meterMid": "Meter: loud (−18 dB)", "meterHigh": "Meter: hot (−6 dB)",
    "overview": "Strip: wave", "overviewBg": "Strip: background", "overviewView": "Strip: view",
}
