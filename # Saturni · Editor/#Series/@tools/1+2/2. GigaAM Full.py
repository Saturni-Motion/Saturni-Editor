# -*- coding: utf-8 -*-
"""GigaAM по всей серии: куски до 18 с режутся в паузах голоса, итог words/<стем>_giga.json [{s,e,t}]. Запуск из ~/.cache/venv-asr."""
import json, os, sys, wave
import numpy as np
import onnx_asr
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
S = os.environ.get("MOMENTS_WORK") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_work")
m = onnx_asr.load_model("gigaam-v3-e2e-rnnt", providers=["CPUExecutionProvider"])
for st in sys.argv[1:]:
    with wave.open(os.path.join(S, "words", f"{st}_vocals16k.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    h = 160; n = len(x) // h
    db = 10 * np.log10((x[:n * h].reshape(n, h) ** 2).mean(1) + 1e-10)
    v = db > -38
    idx = np.flatnonzero(np.diff(np.r_[0, v.astype(np.int8), 0]))
    sp = [[i * 0.01, j * 0.01] for i, j in zip(idx[::2], idx[1::2])]
    mg = []
    for a, b in sp:
        if mg and a - mg[-1][1] < 0.25:
            mg[-1][1] = b
        else:
            mg.append([a, b])
    mg = [s for s in mg if s[1] - s[0] > 0.12]
    chunks = []
    for a, b in mg:
        if chunks and b - chunks[-1][0] < 18 and a - chunks[-1][1] < 1.2:
            chunks[-1][1] = b
        else:
            chunks.append([a, b])
    out = []
    for a, b in chunks:
        i0, i1 = int(max(0, a - 0.15) * 16000), int((b + 0.15) * 16000)
        seg = x[i0:i1]
        for k in range(0, len(seg), 20 * 16000):
            t = str(m.recognize(seg[k:k + 20 * 16000].copy(), sample_rate=16000)).strip()
            if t:
                out.append({"s": round(a + k / 16000, 2), "e": round(min(b, a + (k + 20 * 16000) / 16000), 2), "t": t})
    json.dump(out, open(os.path.join(S, "words", f"{st}_giga.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(st, len(chunks), "кусков", len(out), flush=True)
