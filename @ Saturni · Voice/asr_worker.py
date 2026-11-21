# -*- coding: utf-8 -*-
"""
asr_worker.py — распознавание голосовых правок для Subs Studio. Запускается приложением питоном
~/.cache/venv-asr (там onnx-asr + GigaAM-v3 e2e с пунктуацией), живёт всё время работы окна.

Протокол (строки JSON):
  stdin  {"job": "<id>", "path": "<.f32 моно 16 кГц>", "final": true|false}
  stdout {"ready": true} | {"job": "<id>", "text": "...", "final": bool} | {"job": ..., "error": "..."}
Работает на процессоре: видеопамять обычно занята Premiere, а короткая фраза и так ~0.3 с.
Для частичных результатов приложение само шлёт не больше одного задания на запись за раз.
"""
import sys
import json
import numpy as np

SR = 16000
WIN = 20.0          # GigaAM берёт ≤ 25 с за раз — длинную диктовку режем по самому тихому месту


def out(d):
    sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def pieces(pcm):
    n, step = len(pcm), int(WIN * SR)
    if n <= int(24 * SR):
        return [pcm]
    res, i = [], 0
    while n - i > int(24 * SR):
        lo, hi = i + int((WIN - 5) * SR), i + step
        frame = int(0.05 * SR)
        seg = pcm[lo:hi]
        k = len(seg) // frame
        e = (seg[:k * frame].reshape(k, frame) ** 2).mean(axis=1)
        cut = lo + int(np.argmin(e)) * frame + frame // 2
        res.append(pcm[i:cut])
        i = cut
    res.append(pcm[i:])
    return res


def main():
    import onnxruntime
    import onnx_asr
    try:
        onnxruntime.preload_dlls()
    except Exception:
        pass
    model = onnx_asr.load_model("gigaam-v3-e2e-rnnt", providers=["CPUExecutionProvider"])
    model.recognize(np.zeros(SR, dtype=np.float32), sample_rate=SR)       # прогрев
    out({"ready": True})
    for line in sys.stdin:
        try:
            job = json.loads(line.lstrip("﻿"))
        except Exception:
            continue
        try:
            pcm = np.fromfile(job["path"], dtype=np.float32)
            if len(pcm) < SR * 0.3:
                out({"job": job["job"], "text": "", "final": job.get("final", False)})
                continue
            texts = [str(model.recognize(p, sample_rate=SR)).strip() for p in pieces(pcm)]
            out({"job": job["job"], "text": " ".join(t for t in texts if t), "final": job.get("final", False)})
        except Exception as e:
            out({"job": job.get("job"), "error": str(e), "final": job.get("final", False)})


if __name__ == "__main__":
    main()
