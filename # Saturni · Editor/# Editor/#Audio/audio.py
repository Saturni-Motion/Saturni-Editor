# -*- coding: utf-8 -*-
r"""Saturni · Editor, звук: параметры кодирования, цепочка звуковых эффектов, громкость, раскладка каналов."""
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

from common import *

def audio_args(a: dict, k: int, has_video: bool) -> list[str]:
    """Output audio stream k in the source stream's codec; lossy ones at its bitrate (320k when unknown)."""
    c, br = a["codec"], a["br"]
    kbps = f"{max(32, round(br / 1000)) if br else 320}k"
    s = f":a:{k}"
    if c == "mp3":
        return [f"-c{s}", "libmp3lame", f"-b{s}", kbps]
    if c == "aac":
        return [f"-c{s}", "aac", f"-b{s}", kbps]
    if c == "opus":
        return [f"-c{s}", "libopus", f"-b{s}", kbps]
    if c == "vorbis":
        return [f"-c{s}", "libvorbis", f"-b{s}", kbps]
    if c == "flac":
        return [f"-c{s}", "flac"]
    if c.startswith("pcm_"):
        return [f"-c{s}", c]
    return [f"-c{s}", "aac", f"-b{s}", kbps] if has_video else []


def fx_chain(a) -> list[str]:
    """Gain, low / high cut, bass / treble, compressor, limiter: the page's sound panel as filters."""
    if not a:
        return []
    f = []
    if float(a.get("gain", 0)):
        f.append(f"volume={float(a['gain']):.2f}dB")
    if float(a.get("hp", 0)):
        f.append(f"highpass=f={float(a['hp']):.1f}")
    if float(a.get("lp", 0)):
        f.append(f"lowpass=f={float(a['lp']):.1f}")
    if float(a.get("bass", 0)):
        f.append(f"bass=g={float(a['bass']):.2f}:f=100:t=s:w=1")
    if float(a.get("treble", 0)):
        f.append(f"treble=g={float(a['treble']):.2f}:f=3000:t=s:w=1")
    if a.get("comp"):
        f.append(f"acompressor=threshold={float(a['cth']):.1f}dB:ratio={float(a['crat']):.2f}:knee=2.8:"
                 f"attack={float(a['catk']):.2f}:release={float(a['crel']):.1f}:makeup={10 ** (max(0.0, float(a['cmk'])) / 20):.4f}")
    if a.get("lim"):
        f.append(f"alimiter=limit={max(0.0625, 10 ** (float(a['lceil']) / 20)):.4f}:attack=5:release={float(a['lrel']):.1f}:level=0")
    return f


def vol_filters(env) -> list[str]:
    """A volume line [[t, gain], ...] (straight pieces) as a per-frame volume expression."""
    if not env or all(abs(g - 1) < 1e-4 for _, g in env):
        return []
    terms = []
    for (t0, g0), (t1, g1) in zip(env, env[1:]):
        if t1 - t0 <= 1e-9:
            continue
        sl = (g1 - g0) / (t1 - t0)
        terms.append(f"gte(t,{t0:.6f})*lt(t,{t1:.6f})*({g0:.6f}+(t-{t0:.6f})*{sl:.6f})")
    terms.append(f"gte(t,{env[-1][0]:.6f})*{env[-1][1]:.6f}")
    if len(env) == 1:
        terms = [f"{env[0][1]:.6f}"]
    return ["asetnsamples=n=64:p=0", f"volume='{'+'.join(terms)}':eval=frame"]


def layout_name(ch: int) -> str:
    return {1: "mono", 2: "stereo", 3: "2.1", 4: "quad", 6: "5.1", 8: "7.1"}.get(ch, "stereo")
