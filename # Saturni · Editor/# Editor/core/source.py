# -*- coding: utf-8 -*-
r"""Saturni · Editor: один исходный файл (дорожки, волна, прокси, ключевые кадры)."""
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
from settings import *
from audio import *
from video import *

class Source:
    def __init__(self, path: Path, tmp: Path, idx: int):
        self.path, self.tmp, self.idx = path.resolve(), tmp, idx
        self.info = probe(self.path)
        self.proxy_path = None
        self.files: dict[int, Path] = {}
        self.waves: dict[int, bytes] = {}
        self.keys = None
        self.lock = threading.Lock()

    def public(self) -> dict:
        return {**self.info, "i": self.idx, "name": self.path.name, "stem": self.path.stem,
                "ext": self.path.suffix.lower(), "folder": str(self.path.parent)}

    def wave_rate(self, n: int) -> int:
        d = max(self.info["duration"], 0.1)
        return int(max(3000, min(self.info["audios"][n]["rate"] or 48000, 48000, WAVE_SAMPLES / d)))

    def wave(self, n: int) -> bytes:
        """Sound stream n as mono 16-bit WAV at wave_rate(n) (just for drawing the waveform)."""
        with self.lock:
            if n not in self.waves:
                r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.path), "-vn", "-map", f"0:a:{n}",
                                    "-ac", "1", "-ar", str(self.wave_rate(n)), "-c:a", "pcm_s16le", "-f", "wav", "-"],
                                   capture_output=True, creationflags=NO_WINDOW)
                self.waves[n] = r.stdout if r.returncode == 0 else b""
            return self.waves[n]

    def audio_file(self, n: int) -> Path:
        """Sound stream n as a file the page can play: the file itself for a plain audio file, else
        the stream copied out (or turned into AAC when the browser can't play its codec)."""
        with self.lock:
            if n in self.files:
                return self.files[n]
            a = self.info["audios"][n]
            if not self.info["video"] and len(self.info["audios"]) == 1 and self.path.suffix.lower() in PLAYABLE:
                f = self.path
            else:
                ext = COPY_EXT.get(a["codec"])
                f = self.tmp / f"s{self.idx}a{n}{ext or '.m4a'}"
                codec = ["-c:a", "copy"] if ext else ["-c:a", "aac", "-b:a", "256k"]
                r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(self.path), "-vn", "-sn", "-map", f"0:a:{n}",
                                    *codec, str(f)], capture_output=True, creationflags=NO_WINDOW)
                if r.returncode != 0:              # copying failed (odd container): AAC always works
                    f = self.tmp / f"s{self.idx}a{n}.m4a"
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(self.path), "-vn", "-sn", "-map", f"0:a:{n}",
                                    "-c:a", "aac", "-b:a", "256k", str(f)], capture_output=True, creationflags=NO_WINDOW)
            self.files[n] = f
            return f

    def keyframes(self) -> list:
        """Where the video can be cut without re-rendering (read from the packets, nothing decoded)."""
        with self.lock:
            if self.keys is None:
                r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                                    "-of", "csv=p=0", str(self.path)], capture_output=True, text=True, creationflags=NO_WINDOW)
                keys = []
                for line in r.stdout.splitlines():
                    t, _, fl = line.partition(",")
                    if "K" in fl:
                        try:
                            keys.append(float(t))
                        except ValueError:
                            pass
                self.keys = sorted(keys)
            return self.keys

    def proxy(self) -> bool:
        """A light H.264 copy for the preview when WebView2 can't play the original."""
        if self.proxy_path is None:
            out = self.tmp / f"proxy{self.idx}.mp4"
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(self.path), "-map", "0:v:0", "-an",
                                "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                                "-g", "12", "-pix_fmt", "yuv420p", str(out)],
                               capture_output=True, text=True, creationflags=NO_WINDOW)
            if r.returncode != 0:
                return False
            self.proxy_path = out
        return True
