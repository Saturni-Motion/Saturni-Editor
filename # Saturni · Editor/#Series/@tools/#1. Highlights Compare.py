#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
#1. Highlights Compare.py — сверка этапа 1: готовые ролики Saturni против моих кандидатов
(#analysis/Highlights-*, см. @instructions/#analysis-highlights.md).

    python #1. Highlights Compare.py --source e10.srt --finals "<папка с .srt финалов>" \
        --claude "<папка 1. Claude the Highlighter/e10>" [--json out.json]

Каждую реплику финала ищем в srt исходника по совпадению слов (окно по нормализованным словам,
доля совпавших триграмм/слов) → время в исходнике. Финал ускорен (110%) и порезан на паузах —
поэтому по тексту, не по звуку. Реплики, найденные подряд, склеиваются в «куски» исходника
(разрыв > gap-s = новый кусок). Затем для каждого финала: какой мой кандидат перекрывается, на
сколько секунд раньше/позже вход и выход, какие куски финала вне всех кандидатов.
"""
import argparse, json, os, re, sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
W = re.compile(r"[\wё]+", re.U)


def load(path):
    out = []
    txt = open(path, encoding="utf-8-sig").read().replace("\r", "")
    for block in re.split(r"\n\s*\n", txt):
        ls = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(ls):
            m = TS.search(l)
            if m:
                g = list(map(int, m.groups()))
                out.append((g[0]*3600+g[1]*60+g[2]+g[3]/1000, g[4]*3600+g[5]*60+g[6]+g[7]/1000, " ".join(ls[i+1:])))
                break
    return out


def norm(t):
    return [w.replace("ё", "е") for w in W.findall(t.lower())]


def mmss(t):
    return f"{int(t//60):02d}:{t%60:05.2f}"


def build_index(src):
    words = []   # (word, time)
    for a, b, t in src:
        ws = norm(t)
        for k, w in enumerate(ws):
            words.append((w, a + (b - a) * k / max(1, len(ws))))
    return words


_POS = {}


def locate(ws, index, prev_t=None):
    """Лучшее место фразы ws в индексе: максимум совпавших слов в окне той же длины (+2)."""
    if len(ws) < 2:
        return None
    n = len(ws); need = Counter(ws); best = (0, None)
    L = n + 2
    pos = _POS.get(id(index))
    if pos is None:
        pos = {}
        for i, (w, _) in enumerate(index):
            pos.setdefault(w, []).append(i)
        _POS[id(index)] = pos
    starts = set()
    for k, w in enumerate(ws):
        for p_ in pos.get(w, ()):
            if 0 <= p_ - k < len(index):
                starts.add(p_ - k)
    for i in sorted(starts):
        win = Counter(w for w, _ in index[i:i + L])
        hit = sum(min(c, win[w]) for w, c in need.items())
        score = hit / n
        if prev_t is not None and abs(index[i][1] - prev_t) < 90:
            score += 0.05          # лёгкое предпочтение близким к предыдущей реплике местам
        if score > best[0]:
            best = (score, i)
    if best[1] is None or best[0] < 0.6:
        return None
    i = best[1]
    return index[i][1], index[min(len(index) - 1, i + n - 1)][1], round(best[0], 2)


def spans_for_final(fin, index, gap_s=8.0):
    pts, prev = [], None
    for a, b, t in fin:
        r = locate(norm(t), index, prev)
        if r:
            pts.append((r[0], r[1], t)); prev = r[1]
    pts.sort()
    spans = []
    for s, e, t in pts:
        if spans and s - spans[-1][1] <= gap_s:
            spans[-1][1] = max(spans[-1][1], e); spans[-1][2] += 1
        else:
            spans.append([s, e, 1])
    return [s for s in spans if s[2] >= 2 or (s[1] - s[0]) > 2], len(pts), len(fin)


def claude_cands(folder):
    out = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".srt"):
            c = load(os.path.join(folder, f))
            if c:
                out.append((f[:-4], c[0][0], c[-1][1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True); ap.add_argument("--finals", required=True)
    ap.add_argument("--claude", required=True); ap.add_argument("--json")
    a = ap.parse_args()
    index = build_index(load(a.source))
    cands = claude_cands(a.claude)
    res = []
    for f in sorted(os.listdir(a.finals)):
        if not f.endswith(".srt"):
            continue
        fin = load(os.path.join(a.finals, f))
        spans, found, total = spans_for_final(fin, index)
        if not spans:
            res.append({"final": f, "spans": [], "found": found, "total": total}); continue
        s0, s1 = min(s[0] for s in spans), max(s[1] for s in spans)
        ov = []
        for name, c0, c1 in cands:
            o = max(0, min(c1, s1) - max(c0, s0))
            if o > 0:
                ov.append({"cand": name, "c0": c0, "c1": c1, "overlap": round(o, 1),
                           "in_delta": round(s0 - c0, 1), "out_delta": round(s1 - c1, 1)})
        ov.sort(key=lambda x: -x["overlap"])
        outside = [(round(s[0], 1), round(s[1], 1)) for s in spans
                   if not any(c0 - 3 <= s[0] and s[1] <= c1 + 3 for _, c0, c1 in cands)]
        res.append({"final": f, "found": found, "total": total, "src_in": s0, "src_out": s1,
                    "spans": [(round(x, 1), round(y, 1), n) for x, y, n in spans], "overlaps": ov,
                    "outside_candidates": outside})
    if a.json:
        json.dump({"results": res, "candidates": cands}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in res:
        print(f"\n## {r['final']}  (найдено реплик {r['found']}/{r['total']})")
        if not r["spans"]:
            print("   не найден в исходнике"); continue
        print(f"   исходник {mmss(r['src_in'])}–{mmss(r['src_out'])}, куски: " +
              ", ".join(f"{mmss(x)}–{mmss(y)}({n})" for x, y, n in r["spans"]))
        for o in r["overlaps"][:3]:
            print(f"   ≈ {o['cand']} [{mmss(o['c0'])}–{mmss(o['c1'])}] перекрытие {o['overlap']}с, "
                  f"вход {o['in_delta']:+}с, выход {o['out_delta']:+}с")
        if not r["overlaps"]:
            print("   ⚠ ни одного моего кандидата")
        if r["outside_candidates"]:
            print(f"   куски вне кандидатов: {r['outside_candidates']}")
    used = {o["cand"] for r in res for o in r.get("overlaps", []) if o["overlap"] > 5}
    print("\nМои кандидаты без финала:", [c[0] for c in cands if c[0] not in used])


if __name__ == "__main__":
    main()
