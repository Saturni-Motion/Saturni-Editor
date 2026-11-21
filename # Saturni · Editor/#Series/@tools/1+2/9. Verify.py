# -*- coding: utf-8 -*-
"""Проверка монтажа и рендеров: python "9. Verify.py" e3 e4
1) EDL: рез не по голосу, запас у смены кадра, паузы на швах. 2) Файл: формат, чёрные кадры, короткие планы, длинная тишина."""
import json, os, re, subprocess, sys
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from moments_lib import Voice, S, video, series, DIRS
import moments_lib as shots2
def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:format=duration,bit_rate", "-of", "json", p], capture_output=True, text=True)
    return json.loads(r.stdout)
def filt(p, f):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", p, "-vf", f, "-an", "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stderr
def silences(p, d=0.7):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", p, "-af", f"silencedetect=n=-45dB:d={d}", "-vn", "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", r.stderr)]
tot = 0; bad = 0
sumrow = {}
for st in sys.argv[1:]:
    num = st[1:]
    V = Voice(st); cuts = np.array(json.load(open(S + rf"\words\{st}_cuts.json"))["cuts"])
    for mode in DIRS:
        edl = json.load(open(S + rf"\edl\{st}_{mode}.json", encoding="utf-8"))
        seams = []
        for m in edl:
            prob = []
            P = m['pieces']
            for i, p in enumerate(P):
                a0, a1 = p['a']
                # рез по голосу: на границе куска голос звучит и продолжается за границей
                d0 = V.db(a0 - 0.06, a0 + 0.0); d1 = V.db(a1, a1 + 0.06)
                if i and d0 is not None and (d0 > -30).mean() > 0.6:
                    prob.append(f"вход в голос {a0:.2f}")
                if i + 1 < len(P) and d1 is not None and (d1 > -30).mean() > 0.6:
                    prob.append(f"выход из голоса {a1:.2f}")
                # паузы на швах
                if i + 1 < len(P):
                    sp = V.spans(a0, a1) or []; nx = V.spans(*P[i + 1]['a']) or []
                    if sp and nx:
                        seams.append((a1 - sp[-1][1]) + (nx[0][0] - P[i + 1]['a'][0]))
                # планы
                v0, v1 = p['v']
                cc = [float(c) for c in cuts if v0 + 0.02 < c < v1 - 0.02]
                if cc and cc[0] - v0 < 0.26 and i:
                    prob.append(f"план {cc[0] - v0:.2f} на входе {v0:.2f}")
                if cc and v1 - cc[-1] < 0.26 and i + 1 < len(P):
                    prob.append(f"план {v1 - cc[-1]:.2f} на выходе {v1:.2f}")
            f = series(num, DIRS[mode], f"{m['n']} {m['rate']}.mp4" if m['rate'] else f"{m['n']}.mp4")
            tot += 1
            if not os.path.exists(f):
                print(st, mode, m['n'], "НЕТ ФАЙЛА"); bad += 1; continue
            pr = probe(f)
            vs = next(s for s in pr['streams'] if s['codec_type'] == 'video'); au = [s for s in pr['streams'] if s['codec_type'] == 'audio']
            dur = float(pr['format']['duration'])
            if (vs['width'], vs['height'], vs['r_frame_rate']) != (1920, 1080, shots2.fps_rate(video(st))) or not au or abs(dur - m['dur']) > 0.09:
                prob.append(f"формат {vs['width']}x{vs['height']} {vs['r_frame_rate']} звук {len(au)} длина {dur:.2f}/{m['dur']:.2f}")
            bl = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", filt(f, "crop=1920:800,blackdetect=d=0.04:pix_th=0.02:pic_th=0.995"))
            if bl:
                prob.append("чёрное " + str(bl[:3]))
            sl = [s for s in silences(f) if s > 1.0]
            if sl:
                prob.append("тишина " + str(sl[:4]))
            # короткие планы в готовом файле
            c, d = shots2.analyze(f); fc = shots2.find(c, d)
            fr = shots2.fps_of(f)
            short = [(fc[i] / fr, (fc[i + 1] - fc[i]) / fr) for i in range(len(fc) - 1) if fc[i + 1] - fc[i] < 6]
            if short:
                prob.append("короткие планы " + str([(round(a, 2), round(b, 2)) for a, b in short[:4]]))
            print(f"{st} {mode} {m['n']:2d} {m['name']:<26} {dur:5.1f}с", "ОК" if not prob else prob[:6], flush=True)
            bad += bool(prob)
        s = np.array(seams)
        sumrow[f"{st} {mode}"] = (len(s), round(float(np.median(s)), 2), round(float(np.percentile(s, 90)), 2))
print("всего", tot, "с замечаниями", bad)
print("тишина на швах (кол-во, медиана, 90%):", sumrow)
