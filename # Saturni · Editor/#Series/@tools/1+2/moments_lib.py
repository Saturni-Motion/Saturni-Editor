# -*- coding: utf-8 -*-
"""Общее для этапов 1+2: рабочая папка, пути проекта, голос по вокалу Demucs, поиск склеек.
Проект задаётся файлом _work/project.txt: папка сериала, в ней @/<стем>.mp4 и «Серия N»."""
import json, os, subprocess, wave
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
S = os.environ.get("MOMENTS_WORK") or os.path.join(HERE, "_work")
os.makedirs(os.path.join(S, "words"), exist_ok=True)
DIRS = {"Active": "1. Active", "Faster": "2. Faster", "Medium": "3. Medium"}
def rate_of(m):
    return m.get("rate", {3: "🔥", 5: "✨", 2: "\u26a0\ufe0f"}.get(m.get("color"), ""))
def project():
    return open(os.path.join(S, "project.txt"), encoding="utf-8").read().strip()
def video(stem):
    return os.path.join(project(), "@", stem + ".mp4")
def series(num, *rest):
    return os.path.join(project(), f"Серия {num}", *rest)
HOP = 0.01
class Voice:
    def __init__(self, stem, thr_db=-38.0):
        self.parts = []  # (src_a, src_b, rms_db[])
        full = os.path.join(S, "words", f"{stem}_vocals16k.wav")
        if os.path.exists(full):
            self.parts.append((0.0, None, self._load(full)))
        else:
            for tag in "abc":
                p = os.path.join(S, "words", f"{stem}_{tag}_rangesvoc.wav")
                if not os.path.exists(p):
                    continue
                m = json.load(open(os.path.join(S, "words", f"{stem}_{tag}_ranges.json")))
                db = self._load(p)
                for a, b, src in m:
                    self.parts.append((src, src + b - a, db[int(a / HOP):int(b / HOP)]))
        self.thr = thr_db
    def _load(self, p):
        with wave.open(p) as w:
            sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        h = int(sr * HOP); n = len(x) // h
        e = (x[:n * h].reshape(n, h) ** 2).mean(1)
        # сглаживание 30 мс
        e = np.convolve(e, np.ones(3) / 3, "same")
        return 10 * np.log10(e + 1e-10)
    def db(self, a, b):
        for sa, sb, d in self.parts:
            if sa <= a and (sb is None or b <= sb + 0.02):
                return d[int((a - sa) / HOP):int((b - sa) / HOP)]
        return None
    def voiced(self, a, b):
        d = self.db(a, b)
        return None if d is None else d > self.thr
    def spans(self, a, b, min_on=0.04, min_off=0.05):
        """-> [(s,e)] звучащие участки."""
        v = self.voiced(a, b)
        if v is None:
            return None
        idx = np.flatnonzero(np.diff(np.r_[0, v.astype(np.int8), 0]))
        sp = [[a + i * HOP, a + j * HOP] for i, j in zip(idx[::2], idx[1::2])]
        out = []
        for s in sp:
            if out and s[0] - out[-1][1] < min_off:
                out[-1][1] = s[1]
            else:
                out.append(s)
        return [s for s in out if s[1] - s[0] >= min_on]

def fps_rate(path):
    """Частота кадров файла строкой ffprobe («24/1», «30000/1001»)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return r.stdout.strip().split(",")[0]
def fps_of(path):
    """Частота кадров числом. Секвенции проекта идут с той же частотой, что исходник."""
    a, _, b = fps_rate(path).partition("/")
    return float(a) / float(b or 1)
W, H = 160, 90
def analyze(video, fps=None):
    """Кадры уменьшенного видео с частотой самого файла: номер кадра / fps_of(video) = секунды."""
    rate = fps or fps_rate(video)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={rate},scale={W}:{H},format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    prev = None; cors = []; diffs = []
    top, bot = int(H * 0.13), int(H * 0.87)
    while True:
        b = p.stdout.read(W * H)
        if len(b) < W * H:
            break
        f = np.frombuffer(b, dtype=np.uint8).reshape(H, W)[top:bot].astype(np.float32)
        g = (f - f.mean()) / (f.std() + 1.5)
        if prev is not None:
            cors.append(float((g * prev).mean())); diffs.append(float(np.abs(g - prev).mean()))
        else:
            cors.append(1.0); diffs.append(0.0)
        prev = g
    return np.array(cors), np.array(diffs)
def find(c, d):
    cuts = []
    for k in range(2, len(c) - 2):
        win = np.r_[c[max(0, k - 12):k], c[k + 1:k + 13]]
        dw = np.r_[d[max(0, k - 12):k], d[k + 1:k + 13]]
        if c[k] < np.median(win) - 0.3 and c[k] < 0.65 and d[k] > 3 * (np.median(dw) + 0.02):
            if not cuts or k - cuts[-1] > 5:
                cuts.append(k)
    return cuts
