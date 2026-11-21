#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3.2. Auto Tune.py (стадия 3.2, "Auto Tune") — 2026-09-11, Saturni.

Что делает с .srt:
  1. АВТОМАТИЧЕСКИ чинит то, что чисто арифметика, без риска для текста/смысла:
     - butt-join: зазор 0 < gap <= BUTT_S -> следующий титр начинается сразу
       за концом текущего (3. Subtitles.md: "стык <200мс");
     - монотонность: конец текущего титра никогда не заходит за начало
       следующего (клэмп при наезде);
     - нулевая/отрицательная длительность -> +1 кадр (40мс), никогда <=0.
  2. ДОКЛАДЫВАЕТ (не трогает без человека — это судьба текста/смысла, не
     арифметика), сверяясь с калибровкой из 3. Subtitles.md,
     "Калибровка личного порога":
     - титры дольше DURATION_CAP_S — обязательный разрез;
     - доля однословных титров (цель 30-33%);
     - доля титров с "!" (цель 7.1-15.2%);
     - висячий предлог/союз на конце многословного титра без паузы после
       (FUNC_WORDS — та же таблица, что и в subtitles_pipeline.assemble()).

При будущих разборах #analysis ссылаться на этот отчёт вместо
пересчёта вручную — числа те же самые, что откалиброваны в инструкции.

Usage:
    python 3.2. Auto Tune.py file1.srt [dir2] [...] [--no-apply]
--no-apply: только отчёт, файлы не перезаписываются (по умолчанию — чинит и
            перезаписывает исходный .srt, но правит только мехническую часть).
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import importlib.util as _ilu
_TOOLS = HERE


def _tool(name, file):
    """Модуль из @tools по пути: в именах пробелы/точки/@ (2026-10-07), обычный import их не
    видит. Регистрируется под прежним именем модуля — повторная загрузка не нужна."""
    if name not in sys.modules:
        spec = _ilu.spec_from_file_location(name, os.path.join(_TOOLS, file))
        sys.modules[name] = mod = _ilu.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


cp = _tool("subtitles_pipeline", "3.1. Subtitles Pipeline.py")  # ts(), FUNC_WORDS

BUTT_S = 0.35           # зазор меньше 0.35 с -> стык (было 0.2)
DURATION_CAP_S = 1.5    # потолок, обязательный разрез (report only)
ONE_WORD_TARGET = (0.30, 0.33)
BANG_TARGET = (0.071, 0.152)
PAUSE_AFTER_HANGING_S = 0.35   # пауза, оправдывающая висячий предлог/союз

_CUE_RE = re.compile(
    r"(\d+)\s*\r?\n"
    r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)\s*\r?\n"
    r"(.*?)(?=\r?\n\r?\n\d+\s*\r?\n|\s*\Z)",
    re.DOTALL,
)


def _to_sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path):
    text = open(path, encoding="utf-8-sig").read()
    cues = []
    for m in _CUE_RE.finditer(text):
        h1, m1, s1, ms1, h2, m2, s2, ms2 = m.group(2, 3, 4, 5, 6, 7, 8, 9)
        start = _to_sec(h1, m1, s1, ms1)
        end = _to_sec(h2, m2, s2, ms2)
        body = m.group(10).strip("\r\n")
        cues.append([start, end, body])
    return cues


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        for k, (a, b, t) in enumerate(cues, 1):
            fh.write(f"{k}\n{cp.ts(a)} --> {cp.ts(b)}\n{t}\n\n")


def autofix(cues):
    """Мутирует cues (списки [start, end, text]) на месте. Возвращает счётчики."""
    n_zero = n_butt = n_clamp = n_stars = n_dash = 0
    for cue in cues:
        # после ***** пунктуации нет (2026-09-28, разбор 24.09) — чисто механическая правка
        fixed = re.sub(r"\*{5}[.,!?…;:]+", "*****", cue[2])
        if fixed != cue[2]:
            cue[2] = fixed
            n_stars += 1
        # тире не используем вообще (3. Subtitles.md, «Кавычки, тире, дефис»); GigaAM и WhisperX их ставят —
        # чисто механическая правка: после знака — пробел, в начале — убрать, между словами — запятая
        t = cue[2]
        if re.search(r"[—–]", t):
            t = re.sub(r"([.,!?…:;])\s*[—–]+\s*", r"\1 ", t)
            t = re.sub(r"^\s*[—–]+\s*", "", t)
            t = re.sub(r"\s*[—–]+\s*", ", ", t).strip(" ,")
            cue[2] = re.sub(r",\s*,", ",", t)
            n_dash += 1
        if cue[1] <= cue[0]:
            cue[1] = cue[0] + 0.04     # +1 кадр @25fps — никогда не <=0
            n_zero += 1
    for i in range(len(cues) - 1):
        gap = cues[i + 1][0] - cues[i][1]
        if gap < 0:                     # наезд на следующий титр — клэмп
            cues[i][1] = cues[i + 1][0]
            n_clamp += 1
        elif 0 < gap <= BUTT_S:
            cues[i][1] = cues[i + 1][0]
            n_butt += 1
    return {"butt_join": n_butt, "monotonic_clamp": n_clamp, "zero_duration": n_zero,
            "stars_punct": n_stars, "dashes": n_dash}


def analyze(cues):
    n = len(cues)
    if n == 0:
        return {"n": 0}
    durations_ms = sorted(int(round((b - a) * 1000)) for a, b, _ in cues)
    mid = n // 2
    median_ms = durations_ms[mid] if n % 2 else (durations_ms[mid - 1] + durations_ms[mid]) // 2
    over_cap = [(i, a, b, t) for i, (a, b, t) in enumerate(cues, 1)
                if (b - a) > DURATION_CAP_S]
    one_word = sum(1 for _, _, t in cues if len(t.split()) == 1)
    with_bang = sum(1 for _, _, t in cues if "!" in t)

    hanging = []
    for i, (a, b, t) in enumerate(cues):
        words = t.split()
        if len(words) < 2:
            continue
        last = words[-1].lower().strip(".,!?…;:—-")
        if last not in cp.FUNC_WORDS:
            continue
        if re.search(r"[.!?…]$", words[-1]):   # «Это как?», «Надо же.» — конец предложения, не висяк
            continue
        if last in ("же", "бы", "ли", "то"):     # частицы законно стоят в конце («не в гнезде же»)
            continue
        # 2026-09-28 (разборы 16.09-24.09): пауза больше НЕ оправдывает висячий предлог/`не`/союз —
        # Saturni переносил их все. Проверка жёсткая; PAUSE_AFTER_HANGING_S оставлен для истории.
        hanging.append((i + 1, a, b, t))

    # повтор одного слова подряд через запятую/пробел -> должен быть через дефис (Иди-иди, Стоп-стоп-стоп)
    repeats = []
    for i, (a, b, t) in enumerate(cues):
        ws = [w.lower().strip(".,!?…;:") for w in t.split()]
        if any(ws[k] and ws[k] == ws[k + 1] for k in range(len(ws) - 1)):
            repeats.append((i + 1, a, b, t))

    return {
        "n": n, "median_ms": median_ms, "over_cap": over_cap,
        "one_word_pct": one_word / n, "bang_pct": with_bang / n,
        "hanging": hanging, "repeats": repeats,
    }


def report(path, stats, fixes):
    try:
        sys.path.insert(0, HERE)
        import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
        sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
        if sb is None:
            _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
            sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(sb)
        COLOR_STATUS, COLOR_FRAME, COLOR_RESET, COLOR_ARROW = sb.COLOR_STATUS, sb.COLOR_FRAME, sb.COLOR_RESET, sb.COLOR_ARROW
    except Exception:
        COLOR_STATUS = COLOR_FRAME = COLOR_RESET = COLOR_ARROW = ""

    print(f"\n{COLOR_FRAME}⛶{COLOR_RESET} {path}")
    if stats["n"] == 0:
        print("  пусто или не распозналось как .srt")
        return

    total_fix = sum(fixes.values())
    if total_fix:
        print(f"  {COLOR_STATUS}автопочинка: стык x{fixes['butt_join']}, "
              f"клэмп x{fixes['monotonic_clamp']}, "
              f"нулевая длительность x{fixes['zero_duration']}, "
              f"знаки после ***** x{fixes.get('stars_punct', 0)}, "
              f"тире убрано x{fixes.get('dashes', 0)}{COLOR_RESET}")
    else:
        print(f"  {COLOR_STATUS}автопочинка: правок не потребовалось{COLOR_RESET}")

    ow = stats["one_word_pct"] * 100
    bg = stats["bang_pct"] * 100
    ow_ok = ONE_WORD_TARGET[0] * 100 <= ow <= ONE_WORD_TARGET[1] * 100
    bg_ok = BANG_TARGET[0] * 100 <= bg <= BANG_TARGET[1] * 100
    print(f"  титров: {stats['n']}, медиана {stats['median_ms']} мс")
    print(f"  однословных: {ow:.1f}% (цель 30-33%){'  OK' if ow_ok else '  <-- проверить'}")
    print(f"  с «!»: {bg:.1f}% (цель 7.1-15.2%){'  OK' if bg_ok else '  <-- проверить'}")

    if stats["over_cap"]:
        print(f"  {COLOR_ARROW}>1.5с — обязательный разрез человеком:{COLOR_RESET}")
        for i, a, b, t in stats["over_cap"]:
            print(f"    #{i} {cp.ts(a)} ({int(round((b - a) * 1000))} мс): {t!r}")
    if stats["hanging"]:
        print(f"  {COLOR_ARROW}висячий предлог/`не`/союз в конце титра — перенести в следующий:{COLOR_RESET}")
        for i, a, b, t in stats["hanging"]:
            print(f"    #{i} {cp.ts(a)}: {t!r}")
    if stats.get("repeats"):
        print(f"  {COLOR_ARROW}повтор слова — писать через дефис (Иди-иди):{COLOR_RESET}")
        for i, a, b, t in stats["repeats"]:
            print(f"    #{i} {cp.ts(a)}: {t!r}")



# ============================================================
#  --suggest: DP boundary cutter ported from
#  its now-deleted "split.py" (was "@tools/# Auto Subtitles/", originally
#  "Арифметика 1 (тест нарезки)") — the same dynamic-program that measured
#  83.6% recall against Saturni's real cuts, see @tools/#3. Autosubtitles-Test.md
#  for the writeup. Never touches the real "<stem>.srt" — it
#  only ever writes a sibling "*.auto_tune_draft.srt" for human review, per
#  that file's "Обязательное условие внедрения" (a draft is never delivered
#  as the result). 2026-09-11.
# ============================================================

END_P = tuple(".!?…")
SOFT_P = tuple(",;:")


def _dp_cuts(words_ms, target=750, soft_max=1200, hard_max=1500, pause_cut=200,
             use_punct=True):
    """words_ms: [(start_ms, end_ms, text), ...]. Returns a set of word
    indices that are the LAST word of a cue (i.e. a boundary follows)."""
    n = len(words_ms)
    INF = float("inf")

    def cue_cost(i, j):
        d = words_ms[j][1] - words_ms[i][0]
        c = ((d - target) / target) ** 2
        if d > hard_max:
            c += 50.0 + (d - hard_max) / 100.0
        if d > soft_max:
            c += ((d - soft_max) / 300.0) ** 2 * 5
        if d < 300:
            c += 4.0
        return c

    def brk_cost(j):
        if j == n - 1:
            return 0.0
        gap = words_ms[j + 1][0] - words_ms[j][1]
        if gap >= pause_cut:
            return 0.0
        if not use_punct:
            return 1.0
        w = words_ms[j][2]
        if w.endswith(END_P):
            return 0.15
        if w.endswith(SOFT_P):
            return 0.55
        return 1.0

    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(n):
        for i in range(j, -1, -1):
            if words_ms[j][1] - words_ms[i][0] > hard_max and j > i:
                break
            if best[i] == INF:
                continue
            c = cue_cost(i, j)
            # a real pause INSIDE a cue is never allowed — a pause always
            # breaks a cue, same rule as everywhere else in this pipeline
            bad = any(words_ms[k + 1][0] - words_ms[k][1] >= pause_cut
                      for k in range(i, j))
            if bad:
                continue
            v = best[i] + c + brk_cost(j)
            if v < best[j + 1]:
                best[j + 1] = v
                back[j + 1] = i
    cuts, j = set(), n
    while j > 0:
        i = back[j]
        cuts.add(j - 1)
        j = i
    cuts.discard(n - 1)   # implicit — the last word always ends the transcript
    return cuts


def suggest_from_words_json(json_path, out_path=None):
    """Draft-only re-cut of a raw words.json (from subtitles_pipeline's _tmp,
    before it's deleted) using the DP boundary cutter. Writes and returns
    (out_path, cues) — never the real "<stem>.srt"."""
    words = json.load(open(json_path, encoding="utf-8"))
    wms = [(int(round(w["start"] * 1000)), int(round(w["end"] * 1000)), w["word"])
           for w in words]
    cuts = _dp_cuts(wms)
    cues = []
    start_i = 0
    for end_i in sorted(cuts) + [len(wms) - 1]:
        if end_i < start_i:
            continue
        group = wms[start_i:end_i + 1]
        if group:
            a, b = group[0][0] / 1000.0, group[-1][1] / 1000.0
            cues.append([a, b, " ".join(g[2] for g in group)])
        start_i = end_i + 1
    if out_path is None:
        out_path = os.path.splitext(json_path)[0] + ".auto_tune_draft.srt"
    write_srt(cues, out_path)
    return out_path, cues


def run(paths, apply=True):
    for path in paths:
        cues = parse_srt(path)
        if apply:
            fixes = autofix(cues)
            if sum(fixes.values()):
                write_srt(cues, path)
        else:
            fixes = {"butt_join": 0, "monotonic_clamp": 0, "zero_duration": 0}
        stats = analyze(cues)
        report(path, stats, fixes)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("srt", nargs="+", help=".srt файлы (или words.json с --suggest)")
    ap.add_argument("--no-apply", action="store_true",
                     help="только отчёт, не перезаписывать файлы")
    ap.add_argument("--suggest", action="store_true",
                     help="вход — words.json (из _tmp/<clip>/, ДО удаления папки); "
                          "вместо анализа .srt предлагает нарезку DP-алгоритмом "
                          "(см. @tools/#3. Autosubtitles-Test.md) и пишет её в отдельный "
                          "'<имя>.auto_tune_draft.srt' — черновик, реальный .srt "
                          "не трогает, доводит человек")
    a = ap.parse_args()
    if a.suggest:
        for jp in a.srt:
            out_path, cues = suggest_from_words_json(jp)
            print(f"[suggest] {jp} -> {out_path}  ({len(cues)} cues)")
            stats = analyze(cues)
            report(out_path, stats, {"butt_join": 0, "monotonic_clamp": 0, "zero_duration": 0})
    else:
        run(a.srt, apply=not a.no_apply)


if __name__ == "__main__":
    main()
