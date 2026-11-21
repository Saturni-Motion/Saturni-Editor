#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
#3. Subs Compare.py — сверка «что сдал Claude» (2. Claude the Manager) с «как поправил Saturni»
(3. Revised & Finalized) для разбора #analysis/Subtitles-*. Пословное выравнивание (difflib) по
нормализованным словам, дальше:
  * правки текста (замены/вставки/удаления слов) с контекстом;
  * сегментация: где Saturni разрезал/склеил титры и КАКИЕ слова перенёс через границу
    (висячие предлоги/союзы, слова, что по смыслу вместе);
  * тайминг: сдвиг старта/конца титров, у которых граница совпала (старт = то же слово);
  * пунктуация на конце слова (. ! ? , … и её отсутствие);
  * общая статистика обоих файлов.

    python #3. Subs Compare.py <папка разбора> [--json out.json]
Ищет рекурсивно пары <...>/2. Claude the Manager/X.srt ↔ <...>/3. Revised & Finalized/X.srt.
"""
import argparse, difflib, json, os, re, statistics, sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
WORD = re.compile(r"[\wёЁ*]+(?:[-'][\wёЁ]+)*", re.U)
FUNC = set("в во на с со к ко по о об обо у за из от до для без под над при про через и а но или да же ли бы то не ни что как так вот ну".split())


def load(path):
    cues = []
    txt = open(path, encoding="utf-8-sig").read().replace("\r", "")
    for block in re.split(r"\n\s*\n", txt):
        ls = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(ls):
            m = TS.search(l)
            if m:
                g = list(map(int, m.groups()))
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                cues.append({"a": a, "b": b, "t": " ".join(ls[i + 1:]).strip()})
                break
    return cues


def tokens(cues):
    out = []   # (norm, raw_with_punct, cue_idx, pos_in_cue, n_in_cue)
    for ci, c in enumerate(cues):
        raw = c["t"].split()
        ws = []
        for r in raw:
            m = WORD.findall(r)
            if not m:
                if ws:
                    ws[-1] = (ws[-1][0], ws[-1][1] + " " + r)
                continue
            ws.append(("".join(m).lower().replace("ё", "е"), r))
        for k, (n, r) in enumerate(ws):
            out.append((n, r, ci, k, len(ws)))
    return out


def punct_end(raw):
    m = re.search(r"([.!?,…:;]+|\.\.\.)[\"»)]*$", raw)
    return m.group(1) if m else ""


def stats(cues):
    d = [c["b"] - c["a"] for c in cues]
    words = [len(tokens([c])) for c in cues]
    return {
        "cues": len(cues),
        "median_ms": int(statistics.median(d) * 1000) if d else 0,
        "one_word_pct": round(100 * sum(1 for w in words if w == 1) / max(1, len(cues)), 1),
        "excl_pct": round(100 * sum(1 for c in cues if "!" in c["t"]) / max(1, len(cues)), 1),
        "hanging_func_end": sum(1 for c in cues if len(c["t"].split()) > 1 and
                                WORD.findall(c["t"].split()[-1].lower()) and
                                WORD.findall(c["t"].split()[-1].lower())[0] in FUNC and
                                not punct_end(c["t"].split()[-1])),
    }


def compare(cp, fp):
    C, F = load(cp), load(fp)
    tc, tf = tokens(C), tokens(F)
    sm = difflib.SequenceMatcher(a=[t[0] for t in tc], b=[t[0] for t in tf], autojunk=False)
    text_edits, punct = [], []
    pair = {}                                   # claude token idx -> final token idx (equal words)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                pair[i1 + k] = j1 + k
        else:
            ctx_c = " ".join(t[1] for t in tc[max(0, i1 - 3):i1])
            text_edits.append({"op": op, "claude": " ".join(t[1] for t in tc[i1:i2]),
                               "final": " ".join(t[1] for t in tf[j1:j2]), "ctx": ctx_c,
                               "t": round(C[tc[i1][2]]["a"] if i1 < len(tc) else C[-1]["a"], 2) if C else 0})
    # пунктуация на совпавших словах
    for i, j in pair.items():
        pc, pf = punct_end(tc[i][1]), punct_end(tf[j][1])
        if pc != pf:
            punct.append({"word": tf[j][1], "claude": pc or "∅", "final": pf or "∅", "t": round(C[tc[i][2]]["a"], 2)})
    # сегментация: начало титра = первое слово титра
    c_start = {i for i, t in enumerate(tc) if t[3] == 0}
    f_start = {j for j, t in enumerate(tf) if t[3] == 0}
    seg = []
    moved_words = Counter()
    inv = {j: i for i, j in pair.items()}
    for i in sorted(pair):
        j = pair[i]
        cs, fs = i in c_start, j in f_start
        if cs == fs:
            continue
        # тип: Saturni склеил (у Claude граница, у финала нет) или разрезал
        kind = "merge" if cs else "split"
        # перенос одного слова: граница сдвинута на соседнее слово
        shift = None
        if cs and (j + 1) in f_start and (i + 1) in pair and pair[i + 1] == j + 1 and (i + 1) not in c_start:
            shift = ("вперёд", tc[i][1])      # слово i ушло в конец предыдущего титра
        if cs and j - 1 >= 0 and (j - 1) in f_start and (j - 1) in inv and (inv[j - 1]) not in c_start:
            shift = ("назад", tf[j - 1][1])     # слово перед i ушло в начало этого титра
        seg.append({"kind": kind, "word": tf[j][1], "prev": tf[j - 1][1] if j else "",
                    "claude_cue": C[tc[i][2]]["t"], "final_cue": F[tf[j][2]]["t"], "t": round(C[tc[i][2]]["a"], 2),
                    "shift": shift})
    # висячие: слово, которое у Claude было ПОСЛЕДНИМ в титре, а у Saturni стало ПЕРВЫМ следующего
    hang = []
    for i in sorted(pair):
        j = pair[i]
        c_last = tc[i][3] == tc[i][4] - 1 and tc[i][4] > 1
        f_first = tf[j][3] == 0
        if c_last and f_first:
            hang.append({"word": tc[i][1], "claude_cue": C[tc[i][2]]["t"], "final_next": F[tf[j][2]]["t"],
                         "t": round(C[tc[i][2]]["a"], 2)})
            moved_words[tc[i][0]] += 1
    # обратное: у Claude слово первое в титре, у Saturni — последнее предыдущего
    glue_back = []
    for i in sorted(pair):
        j = pair[i]
        if tc[i][3] == 0 and tc[i][4] > 1 and tf[j][3] == tf[j][4] - 1 and tf[j][4] > 1:
            glue_back.append({"word": tc[i][1], "claude_cue": C[tc[i][2]]["t"], "final_prev": F[tf[j][2]]["t"],
                              "t": round(C[tc[i][2]]["a"], 2)})
    # тайминг совпавших стартов/концов
    ds, de = [], []
    for i in c_start:
        if i in pair and pair[i] in f_start:
            ds.append(F[tf[pair[i]][2]]["a"] - C[tc[i][2]]["a"])
    c_end = {i for i, t in enumerate(tc) if t[3] == t[4] - 1}
    f_end = {j for j, t in enumerate(tf) if t[3] == t[4] - 1}
    for i in c_end:
        if i in pair and pair[i] in f_end:
            de.append(F[tf[pair[i]][2]]["b"] - C[tc[i][2]]["b"])
    return {"claude": stats(C), "final": stats(F), "text_edits": text_edits, "punct": punct, "seg": seg,
            "hang": hang, "glue_back": glue_back, "start_shift": ds, "end_shift": de,
            "matched_words": len(pair), "claude_words": len(tc), "final_words": len(tf)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--json")
    a = ap.parse_args()
    res = {}
    for dp, dn, fn in os.walk(a.root):
        if os.path.basename(dp) != "2. Claude the Manager":
            continue
        fin = os.path.join(os.path.dirname(dp), "3. Revised & Finalized")
        for f in sorted(fn):
            if f.endswith(".srt") and os.path.exists(os.path.join(fin, f)):
                key = os.path.relpath(os.path.join(os.path.dirname(dp), f), a.root)
                res[key] = compare(os.path.join(dp, f), os.path.join(fin, f))
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, r in res.items():
        ss = r["start_shift"]
        print(f"{k}: титров {r['claude']['cues']}->{r['final']['cues']}, правок текста {len(r['text_edits'])}, "
              f"пунктуации {len(r['punct'])}, границ {len(r['seg'])}, висячих {len(r['hang'])}, "
              f"сдвиг старта медиана {statistics.median(ss)*1000 if ss else 0:.0f} мс (n={len(ss)})")


if __name__ == "__main__":
    main()
