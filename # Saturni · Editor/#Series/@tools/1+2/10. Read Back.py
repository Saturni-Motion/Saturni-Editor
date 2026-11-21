# -*- coding: utf-8 -*-
"""GigaAM читает готовые рендеры: запуск из ~/.cache/venv-asr, python "10. Read Back.py" 3 Active (серия, режим) → текст каждого ролика."""
import glob, os, re, subprocess, sys
import numpy as np
import onnx_asr
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
S = os.environ.get("MOMENTS_WORK") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_work")
root = os.path.join(open(os.path.join(S, "project.txt"), encoding="utf-8").read().strip(), f"Серия {sys.argv[1]}", {"Active": "1. Active", "Faster": "2. Faster", "Medium": "3. Medium"}[sys.argv[2]])
m = onnx_asr.load_model("gigaam-v3-e2e-rnnt", providers=["CPUExecutionProvider"])
for p in sorted(glob.glob(os.path.join(glob.escape(root), "*.mp4")), key=lambda x: int(re.match(r"\d+", os.path.basename(x)).group())):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).copy()
    t = [str(m.recognize(x[i:i + 18 * 16000], sample_rate=16000)) for i in range(0, len(x), 18 * 16000)]
    print(os.path.basename(p).split(" ")[0], ":", " ".join(t), flush=True)
