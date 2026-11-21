"""Decoding / encoding through ffmpeg, plus waveform peaks for the UI."""
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def _run(args):
    r = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-800:])
    return r


def to_wav(src: Path, dst: Path):
    """Any audio/video → 44.1 kHz stereo float WAV."""
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "2", "-ar", str(SR),
          "-c:a", "pcm_f32le", str(dst)])


def load(path: Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    assert sr == SR, sr
    return np.ascontiguousarray(data.T)  # (C, T)


def save(path: Path, audio: np.ndarray):
    """Write WAV (16-bit) and a light MP3 for in-browser playback."""
    a = np.clip(audio.T, -1, 1)
    sf.write(str(path.with_suffix(".wav")), a, SR, subtype="PCM_16")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(path.with_suffix(".wav")), "-c:a", "libmp3lame",
          "-b:a", "192k", str(path.with_suffix(".mp3"))])


def peaks(audio: np.ndarray, n: int = 1200) -> list:
    mono = np.abs(audio).max(0)
    if mono.size < n:
        return [round(float(v), 3) for v in mono]
    edges = np.linspace(0, mono.size, n + 1).astype(int)
    p = np.maximum.reduceat(mono, edges[:-1])
    return [round(float(v), 3) for v in p]


def duration(path: Path) -> float:
    return sf.info(str(path)).duration
