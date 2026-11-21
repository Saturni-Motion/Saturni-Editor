# -*- coding: utf-8 -*-
"""Монтажный вид сцены: python "4. Scene View.py" e3 a-b [a-b ...] (время в секундах или мм:сс).
Строка = звучащий кусок голоса с текстом; между ними длина паузы; | смена кадра; (шум) если в паузе громко."""
import sys, json, subprocess
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from moments_lib import Voice, S, video, series
st = sys.argv[1]
v = Voice(st); cuts = np.array(json.load(open(S + rf"\words\{st}_cuts.json"))["cuts"])
words = [w for w in json.load(open(S + rf"\words\{st}.json", encoding="utf-8"))["words"] if w['e'] - w['s'] < 4]
def tm(x):
    return int(x.split(":")[0]) * 60 + float(x.split(":")[1]) if ":" in x else float(x)
for r in sys.argv[2:]:
    a, b = [tm(x) for x in r.split("-")]
    sp = v.spans(a, b, min_off=0.14)
    print(f"=== {r} ({a:.0f}-{b:.0f})")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", video(st), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
    mix = np.frombuffer(raw, dtype=np.float32)
    def mdb(x, y):
        s = mix[int((x - a) * 8000):int((y - a) * 8000)]
        return round(float(10 * np.log10((s ** 2).mean() + 1e-10))) if len(s) else 0
    prev = a
    for x, y in sp + [[b, b]]:
        g = x - prev
        cc = [float(c) for c in cuts if prev - 0.02 <= c <= x + 0.02]
        if g >= 0.14 or cc:
            print(f"      .. {g:.2f}с шум{mdb(prev, x)}" + "".join(f" |{c:.2f}" for c in cc))
        if y > x:
            ws = [w['w'] for w in words if x - 0.12 <= w['s'] < y - 0.05]
            ci = [float(c) for c in cuts if x < c < y]
            print(f"{x:8.2f}-{y:8.2f} {' '.join(ws)}" + ("  " + "".join(f"|{c:.2f} " for c in ci) if ci else ""))
        prev = y
