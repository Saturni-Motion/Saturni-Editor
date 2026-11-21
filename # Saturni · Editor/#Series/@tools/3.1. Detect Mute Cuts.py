"""edges.py <video> : провалы >=18 дБ ниже локальной медианы, с резкостью фронтов
(макс. перепад за 10 мс на входе/выходе). Вырез громкости = ступенька, пауза = спад."""
import subprocess, sys
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")
SR = 16000; W = 0.01
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", sys.argv[1], "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
n = int(SR * W); k = len(x) // n
db = 20 * np.log10(np.sqrt((x[:k*n].reshape(k, n) ** 2).mean(1)) + 1e-9)
h = 100
loc = np.array([np.median(db[max(0, i-h):i+h]) for i in range(k)])
low = db < loc - 18
i = 0
while i < k:
    if low[i]:
        j = i
        while j < k and low[j]: j += 1
        if j - i >= 4:
            a, b = max(i-3, 1), min(j+3, k-1)
            fin = np.min(np.diff(db[a:i+3])); fout = np.max(np.diff(db[j-3:b]))
            print(f"{i*W:6.2f}-{j*W:6.2f} ({(j-i)*W:.2f}s) дно {np.median(db[i:j]):6.1f} / фон {loc[i]:6.1f}  вход {fin:6.1f} дБ/10мс  выход {fout:+6.1f}")
            print("      " + " ".join(f"{v:.0f}" for v in db[max(i-8,0):min(j+8,k)]))
        i = j
    else:
        i += 1
