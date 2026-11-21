#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
3.1. GigaAM Second.py — второе мнение для титров (Saturni, 2026-10-29). Запускает
"3.1. Subtitles Pipeline.py" питоном окружения ~/.cache/venv-asr (onnx-asr + onnxruntime-gpu), сам по
себе не нужен.

    ~/.cache/venv-asr/Scripts/python.exe "3.1. GigaAM Second.py" <whisperx_in.wav> <words.json> <out.txt>

Распознаёт тот же очищенный голос (Demucs + loudnorm, 16 кГц моно) моделью GigaAM-v3 e2e
(Сбер), сравнивает со словами WhisperX и пишет в out.txt только РАСХОЖДЕНИЯ:
    12.34  Whisper: «вот эти»  →  GigaAM: «да что бутылки»
Почему так (разбор 29.10, Серия 1/7): где модели согласны, у Whisper осталось 4 ошибочных слова
на ролик; из 8 расхождений 7 оказались настоящими ошибками Whisper. Значит, при вычитке
проверять в первую очередь расхождения, а вариант выбирать по смыслу сцены. Модель не главная:
у Whisper тайминги слов, у GigaAM только текст.
Стилевые различия (чё/что, здрасте/здравствуйте, ё/е, дефисы) расхождением не считаются.
"""
import difflib
import json
import re
import subprocess
import sys

import numpy as np

MODEL = "gigaam-v3-e2e-rnnt"
SR = 16000
MAX_CHUNK = 20.0   # GigaAM берёт ≤ 25 с за раз; режем в самых длинных паузах между словами
SAME = {"чё": "что", "че": "что", "чо": "что", "здрасте": "здрасьте", "здравствуйте": "здрасьте",
        "щас": "сейчас", "ща": "сейчас"}


def norm(w):
    w = re.sub(r"[^\w]+", "", w.lower().replace("ё", "е"))
    return SAME.get(w, w)


def chunks(words, total):
    out, start = [], 0.0
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and words[j + 1]["end"] - start <= MAX_CHUNK:
            j += 1
        if j + 1 >= len(words):
            out.append((start, total, i, len(words)))
            break
        # граница — самая длинная пауза во второй половине куска
        k = max(range(max(i, (i + j) // 2), j + 1), key=lambda n: words[n + 1]["start"] - words[n]["end"])
        cut = (words[k]["end"] + words[k + 1]["start"]) / 2
        out.append((start, cut, i, k + 1))
        start, i = cut, k + 1
    return out


def main(wav, words_json, out_txt):
    import onnxruntime
    import onnx_asr
    try:
        onnxruntime.preload_dlls()
    except Exception:
        pass
    words = json.load(open(words_json, encoding="utf-8"))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    pcm = np.frombuffer(raw, dtype=np.float32)
    prov = (["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "CUDAExecutionProvider" in onnxruntime.get_available_providers() else ["CPUExecutionProvider"])
    model = onnx_asr.load_model(MODEL, providers=prov)
    lines, full = [], []
    for a, b, i, j in chunks(words, len(pcm) / SR):
        text = str(model.recognize(pcm[int(a * SR):int(b * SR)], sample_rate=SR))
        full.append(text)
        W = words[i:j]
        G = [g for g in text.replace("-", " ").replace("—", " ").split() if norm(g)]
        wn = [norm(w["word"]) for w in W]
        gn = [norm(g) for g in G]
        sm = difflib.SequenceMatcher(None, wn, gn, autojunk=False)
        for op, x1, x2, y1, y2 in sm.get_opcodes():
            if op == "equal":
                continue
            t = W[x1]["start"] if x1 < len(W) else (W[-1]["end"] if W else a)
            wt = " ".join(w["word"] for w in W[x1:x2]) or "∅"
            gt = " ".join(G[y1:y2]) or "∅"
            lines.append(f"{t:7.2f}  Whisper: «{wt}»  →  GigaAM: «{gt}»")
    with open(out_txt, "w", encoding="utf-8") as fh:
        fh.write(f"# GigaAM-v3 — расхождения с WhisperX ({len(lines)}). Проверить каждое по смыслу сцены.\n")
        fh.write("\n".join(lines) + "\n\n# Полный текст GigaAM:\n" + " ".join(full) + "\n")
    print(f"GigaAM: расхождений {len(lines)} -> {out_txt}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
