# -*- coding: utf-8 -*-
"""Пословный транскрипт всей серии: Demucs кусками -> loudnorm -> WhisperX large-v3 с выравниванием по 8-минутным
кускам (граница — в самой тихой точке). Итог: words/<стем>.json {words:[{w,s,e,score}], segs:[{s,e,t}]},
words/<стем>_vocals16k.wav — голос для анализа пауз."""
import importlib.util as u, json, math, os, shutil, subprocess, sys, wave
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
T = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(T, "1+2"))
from moments_lib import S
OUT = os.path.join(S, "words")
sys.path.insert(0, T)
def load(name, f):
    sp = u.spec_from_file_location(name, os.path.join(T, f)); m = u.module_from_spec(sp); sys.modules[name] = m; sp.loader.exec_module(m); return m
TP = load("tp", "1. Transcribe Plain.py")
P = TP._tool("subtitles_pipeline", "3.1. Subtitles Pipeline.py") if hasattr(TP, "_tool") else load("p", "3.1. Subtitles Pipeline.py")
CH = 480
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_SYMLINKS_WARNING="1")

def run_wx(wav, od):
    for ct, dev in (("int8", "cuda"), ("int8", "cpu")):
        cmd = ["whisperx", wav, "--model", "large-v3", "--language", "ru", "--device", dev, "--batch_size", "4", "--vad_onset", "0.35",
               "--condition_on_previous_text", "False", "--output_format", "json", "--output_dir", od, "--compute_type", ct]
        try:
            p = subprocess.run(cmd, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1500)
            js = os.path.join(od, os.path.splitext(os.path.basename(wav))[0] + ".json")
            if p.returncode == 0 and os.path.exists(js):
                return js
        except subprocess.TimeoutExpired:
            print("  timeout", wav, dev, flush=True)
    raise RuntimeError("whisperx failed " + wav)

def main(video):
    stem = os.path.splitext(os.path.basename(video))[0]
    out_js = os.path.join(OUT, stem + ".json")
    if os.path.exists(out_js):
        print(stem, "already"); return
    d = os.path.join(OUT, "_" + stem); os.makedirs(d, exist_ok=True)
    norm = os.path.join(OUT, stem + "_vocals16k.wav")
    if not os.path.exists(norm):
        a = os.path.join(d, "audio.wav"); P.extract_audio(video, a); print(stem, "audio", flush=True)
        voc = TP.demucs_vocals_chunked(a, os.path.join(d, "demucs")); print(stem, "demucs", flush=True)
        P.loudnorm_mono16k(voc, norm); print(stem, "norm", flush=True)
    with wave.open(norm) as w:
        n, sr = w.getnframes(), w.getframerate(); pcm = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    dur = n / sr
    # границы кусков — самые тихие 100-мс окна около кратных CH
    bounds = [0.0]
    t = CH
    while t < dur - 60:
        a, b = int((t - 20) * sr), int((t + 20) * sr)
        hop = sr // 10
        e = np.array([np.abs(pcm[i:i + hop]).mean() for i in range(a, b, hop)])
        bounds.append((a + int(e.argmin()) * hop + hop // 2) / sr)
        t = bounds[-1] + CH
    bounds.append(dur)
    words, segs = [], []
    for i in range(len(bounds) - 1):
        t0, t1 = bounds[i], bounds[i + 1]
        wav = os.path.join(d, f"p{i}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", norm, "-c", "copy", wav], check=True)
        js = run_wx(wav, d)
        j = json.load(open(js, encoding="utf-8"))
        for w in j.get("word_segments", []):
            if "start" in w and "end" in w:
                words.append({"w": w["word"].strip(), "s": round(w["start"] + t0, 3), "e": round(w["end"] + t0, 3), "c": round(float(w.get("score") or 0), 2)})
        for s in j.get("segments", []):
            segs.append({"s": round(s["start"] + t0, 2), "e": round(s["end"] + t0, 2), "t": s["text"].strip()})
        print(stem, f"chunk {i + 1}/{len(bounds) - 1} words {len(words)}", flush=True)
    json.dump({"words": words, "segs": segs, "dur": dur}, open(out_js, "w", encoding="utf-8"), ensure_ascii=False)
    shutil.rmtree(d, ignore_errors=True)   # промежуточный звук: больше гигабайта на серию, нужен только во время распознавания
    print(stem, "DONE", len(words), flush=True)

for v in sys.argv[1:]:
    main(v)
