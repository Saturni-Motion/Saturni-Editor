#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
#3. ASR Second Opinion.py — вторая модель распознавания (GigaAM-v3, Сбер) против WhisperX
на местах, которые Saturni исправил в титрах. Отвечает на вопрос: если делать два прогона,
поймала бы вторая модель ошибки первой?

    python "#3. ASR Second Opinion.py" "<папка разбора>\Мусор" "<папка проекта с видео>"

Берёт compare.json из "#3. Subs Compare.py --json" (правки текста: claude → final, время t),
для каждой правки вырезает окно [t−1.5, t+2.5] с "<Серия N>\<n> ` 1h.mp4" (16 кГц моно) и
распознаёт его GigaAM v3_e2e_rnnt (с пунктуацией). Пишет asr_second.txt рядом с compare.json:
    WhisperX/Claude: …   Saturni: …   GigaAM: …   [поймала / нет]

Установка (один раз):
    pip install hydra-core==1.3.* sentencepiece soundfile
    pip install --no-deps git+https://github.com/salute-developers/GigaAM
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MODEL = "v3_e2e_rnnt"
PRE, POST = 1.5, 2.5
norm = lambda s: re.sub(r"[^\wё ]+", "", s.lower().replace("ё", "е")).split()


def main(analysis_dir, video_root):
    import gigaam
    model = gigaam.load_model(MODEL)
    data = json.load(open(os.path.join(analysis_dir, "compare.json"), encoding="utf-8"))
    out, hit, total = [], 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for key, x in data.items():
            ser, n = key.split("\\")[0], key.split("\\")[1][:-4]
            video = os.path.join(video_root, ser, f"{n} ` 1h.mp4")
            for e in x["text_edits"]:
                wav = os.path.join(tmp, "w.wav")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, e['t'] - PRE):.2f}",
                                "-t", f"{PRE + POST:.2f}", "-i", video, "-ac", "1", "-ar", "16000", wav])
                res = model.transcribe(wav)
                text = getattr(res, "text", res)
                fin = norm(e["final"])
                got = bool(fin) and all(w in norm(text) for w in fin)
                wrong = norm(e["claude"])
                total += 1
                hit += got
                out.append(f"{ser}/{n} {e['t']:6.1f}  Claude: {e['claude'] or '∅':<28} Saturni: "
                           f"{e['final']:<28} GigaAM: {text}   [{'поймала' if got else 'нет'}"
                           f"{', тоже ошиблась' if wrong and all(w in norm(text) for w in wrong) else ''}]")
    out.append(f"ИТОГО: GigaAM дала вариант Saturni в {hit} из {total} исправленных мест")
    open(os.path.join(analysis_dir, "asr_second.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
