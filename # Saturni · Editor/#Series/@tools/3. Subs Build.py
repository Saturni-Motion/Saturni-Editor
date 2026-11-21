#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
3. Subs Build.py — сборка итогового .srt этапа 3 по моей разметке слов (шаг «Подхват» в
3. Subtitles.md). До 2026-09-28 жил во временной папке сессии как build.py.

    python 3. Subs Build.py "<видео.mp4>" <spec.txt>

spec: одна строка = один титр
    a-b | текст          индексы слов из _tmp/<клип>/words.json, включительно
    a | текст
    t1.23-1.80 | текст   явное время (восстановленная реплика, `*****` по вырезу/пику)
    # комментарий

Тайминг (3. Subtitles.md, «Тайминги и паузы», пересмотр 2026-09-28 по разборам 16.09–24.09):
    старт = старт первого слова − 0.08 с (2 кадра — у Saturni титры «отставали»);
    конец = конец последнего слова (не дольше 0.28 + 0.035·букв, ≤ 0.9 с) + 0.02 с;
    зазор до следующего < 0.2 с → стык; старт не раньше конца предыдущего; первый титр с 0.
Пишет <стем>.srt рядом с видео + копию в «2. Claude the Manager» (#analysis/(!) Subtitles-ДД.ММ), затем прогоняет
3.2. Auto Tune.py (стыки, ***** без знаков, висячие предлоги/`не`/союзы, повторы через дефис).
"""
import json, os, re, subprocess, sys, statistics

sys.stdout.reconfigure(encoding="utf-8")
LEAD, TAIL, WORD_CAP, BUTT = 0.08, 0.02, 0.9, 0.2
HERE = os.path.dirname(os.path.abspath(__file__))


def _analysis_dirs():
    """@Analysis Dirs.py — папки разбора в #analysis/(!) Subtitles-ДД.ММ (Saturni, 2026-10-07)."""
    import importlib.util as _ilu
    mod = sys.modules.get("analysis_dirs")
    if mod is None:
        spec = _ilu.spec_from_file_location("analysis_dirs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "@Analysis Dirs.py"))
        mod = sys.modules["analysis_dirs"] = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def main():
    video, spec = sys.argv[1], sys.argv[2]
    stem = os.path.splitext(os.path.basename(video))[0]
    vdir = os.path.dirname(os.path.abspath(video))
    safe = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", stem).strip("_")
    words = json.load(open(os.path.join(vdir, "_tmp", safe, "words.json"), encoding="utf-8"))

    cues = []
    for ln in open(spec, encoding="utf-8"):
        ln = ln.rstrip("\n")
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        rng, text = [x.strip() for x in ln.split("|", 1)]
        if rng.startswith("t"):
            a, b = map(float, rng[1:].split("-"))
            cues.append([a, b, text])
            continue
        a, b = (map(int, rng.split("-")) if "-" in rng else (int(rng), int(rng)))
        w0, w1 = words[a], words[b]
        nb = len(re.sub(r"[^\wё]", "", w1["word"].lower()))
        cap = min(WORD_CAP, 0.28 + 0.035 * nb)           # как в 3.2. Subs Assemble.py (07.10)
        cues.append([w0["start"] - LEAD, min(w1["end"], w1["start"] + cap) + TAIL, text])

    cues.sort(key=lambda c: c[0])
    for i in range(1, len(cues)):
        cues[i][0] = max(cues[i][0], cues[i - 1][0] + 0.04)
    for i in range(len(cues) - 1):
        ns = cues[i + 1][0]
        if cues[i][1] > ns or ns - cues[i][1] < BUTT:
            cues[i][1] = ns
    for c in cues:
        c[0] = max(0.0, c[0])
    if cues and cues[0][0] < 0.5:
        cues[0][0] = 0.001                     # первый титр с 00:00:00,001 (Saturni, 2026-10-07)

    def ts(s):
        ms = int(round(max(s, 0) * 1000))
        h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s_, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s_:02d},{ms:03d}"

    out = "".join(f"{k}\n{ts(a)} --> {ts(b)}\n{t}\n\n" for k, (a, b, t) in enumerate(cues, 1))
    main_path = os.path.join(vdir, stem + ".srt")
    for p in (main_path, os.path.join(_analysis_dirs().backup_dir(video, "2. Claude the Manager"), stem + ".srt")):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(out)

    durs = [b - a for a, b, _ in cues]
    print(f"{stem}: {len(cues)} титров, медиана {statistics.median(durs)*1000:.0f} мс, "
          f">1.2 с: {[(round(b - a, 2), t) for a, b, t in cues if b - a > 1.2]}")
    subprocess.run([sys.executable, os.path.join(HERE, "3.2. Auto Tune.py"), "--no-apply", main_path],
                   env={**os.environ, "PYTHONUTF8": "1"})


if __name__ == "__main__":
    main()
