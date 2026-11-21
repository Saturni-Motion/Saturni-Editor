#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
#3. ASR Bench.py — сравнение моделей распознавания на ролике, который Saturni уже вычитал.

Эталон — итоговые титры Saturni ("3. Revised & Finalized"), текущая модель — сырой WhisperX
large-v3 ("1. Whisper One Word", до моих правок). Сравниваются (через onnx-asr, без NeMo/torch):
    gigaam-v3-e2e-rnnt          Сбер, русский, с пунктуацией
    nemo-parakeet-tdt-0.6b-v3   NVIDIA, многоязычная
    nemo-canary-1b-v2           NVIDIA, крупнее
Считается на видеокарте (onnxruntime-gpu, CUDA); не влезла в память (Premiere занимает часть из
4 ГБ) — та же модель на процессоре, в отчёте видно где. Звук режется на куски ≤ 20 с по паузам между титрами эталона (GigaAM берёт ≤ 25 с за раз).

Запуск — питоном отдельного окружения (ставится командами из @instructions/3. Subtitles.md):
    "%USERPROFILE%\.cache\venv-asr\Scripts\python.exe" "@tools/#3. ASR Bench.py" <папка разбора серии> <видео> <n>
    напр.  "#Analysis/Subtitles-29.10/Мусор/Серия 1"  "D:/# Video/#Поляна/Мусор/Серия 1/7 ` 1h.mp4"  7

Пишет bench_<n>.txt рядом: WER против эталона (% неверных слов), сколько правок Saturni модель
дала сама, время распознавания, и полный текст каждой модели.
"""
import os
import re
import subprocess
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MODELS = ["gigaam-v3-e2e-rnnt"]   # Parakeet и Canary удалены 29.10: на русском хуже (WER 37% и 40%)
SR = 16000
MAX_CHUNK = 20.0
TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def load_srt(path):
    cues = []
    for b in re.split(r"\n\s*\n", open(path, encoding="utf-8-sig").read().replace("\r", "")):
        m = TS.search(b)
        if m:
            g = list(map(int, m.groups()))
            cues.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                         g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, b[m.end():].strip().replace("\n", " ")))
    return cues


def words(text):
    return re.sub(r"[^\w\s-]+", " ", text.lower().replace("ё", "е")).split()


def wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[-1] / max(1, len(ref))


def chunks(cues):
    """Куски ≤ MAX_CHUNK с, границы — в паузах между титрами эталона."""
    out, s, e = [], None, None
    for a, b, _ in cues:
        if s is None:
            s, e = a, b
        elif b - s > MAX_CHUNK:
            out.append((s, (e + a) / 2))
            s, e = (e + a) / 2, b
        else:
            e = b
    out.append((s, e + 0.3))
    out[0] = (max(0.0, out[0][0] - 0.3), out[0][1])
    return out


def audio(video):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def recognize(model, wav):
    for kw in ({"language": "ru"}, {}):
        try:
            return str(model.recognize(wav, sample_rate=SR, **kw))
        except TypeError:
            continue
    return str(model.recognize(wav))


def main(series_dir, video, n):
    import onnxruntime
    import onnx_asr
    try:
        onnxruntime.preload_dlls()          # CUDA/cuDNN из pip-пакетов nvidia-* окружения
    except Exception:
        pass
    gpu = "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    ref_cues = load_srt(os.path.join(series_dir, "3. Revised & Finalized", f"{n}.srt"))
    ref = words(" ".join(t for _, _, t in ref_cues))
    whisper = " ".join(t for _, _, t in load_srt(os.path.join(series_dir, "1. Whisper One Word", f"{n}.srt")))
    claude = " ".join(t for _, _, t in load_srt(os.path.join(series_dir, "2. Claude the Manager", f"{n}.srt")))
    pcm = audio(video)
    parts = chunks(ref_cues)
    whisper_w = set(words(whisper))
    fixes = [w for w in ref if w not in whisper_w]          # слова, которых Whisper не дал
    results = [("WhisperX large-v3 (сейчас)", whisper, None), ("после моей вычитки", claude, None)]
    for name in MODELS:
        text, tm = None, None
        tries = ([("GPU", ["CUDAExecutionProvider", "CPUExecutionProvider"])] if gpu else []) +                 [("CPU", ["CPUExecutionProvider"])]
        for dev, prov in tries:
            try:
                t0 = time.time()
                model = onnx_asr.load_model(name, providers=prov)
                recognize(model, pcm[:SR])                     # прогрев (первый вызов на GPU долгий)
                t_load = time.time() - t0
                t0 = time.time()
                text = " ".join(recognize(model, pcm[int(a * SR):int(b * SR)]) for a, b in parts)
                tm = (t_load, time.time() - t0, dev)
                del model
                break
            except Exception as e:
                text = f"НЕ ЗАГРУЗИЛАСЬ ({dev}): {e}"
        results.append((name, text, tm))
    dur = len(pcm) / SR
    lines = [f"Ролик {n}: {dur:.1f} с, слов в эталоне {len(ref)}, слов, которых не дал Whisper: {len(fixes)}", ""]
    for name, text, tm in results:
        hyp = words(text)
        got = sum(1 for w in set(fixes) if w in hyp)
        tm_s = f", {tm[2]}: распознавание {tm[1]:.1f} с (×{dur / max(tm[1], 0.01):.0f} быстрее реального), загрузка {tm[0]:.0f} с" if tm else ""
        lines.append(f"{name:<30} WER {wer(ref, hyp) * 100:5.1f}%  поймала правок {got}/{len(set(fixes))}{tm_s}")
    lines.append("")
    for name, text, _ in results:
        lines += [f"== {name}", text, ""]
    out = os.path.join(series_dir, f"bench_{n}.txt")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[:len(results) + 2]))
    print("->", out)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
