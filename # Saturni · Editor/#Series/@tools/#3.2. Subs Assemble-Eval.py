#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
#3.2. Subs Assemble-Eval.py — насколько автосборка 3.2 (3.2. Subs Assemble.py) близка к финалам Saturni.

Берёт все ролики в #analysis/Subtitles-*/ где есть «1. Whisper One Word» + «3. Revised & Finalized»
(и, для сравнения, «2. Claude the Manager»). Для каждого: собирает титры автоматически из
пословного srt и считает по границам титров (пословное выравнивание с финалом):
  precision — доля границ сборки, которые есть и у Saturni;
  recall    — доля границ Saturni, которые угадала сборка;
  висяки    — слово последнее в титре сборки, а у Saturni первое в следующем;
  сдвиг старта — медиана (финал − сборка) по совпавшим стартам.
То же для «2. Claude the Manager» (моя ручная сборка) — базовая линия.

    python #3.2. Subs Assemble-Eval.py [корень #analysis] [--only 16.09]
"""
import difflib, os, statistics, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
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


_sc = _tool("subs_compare", "#3. Subs Compare.py")
load, tokens = _sc.load, _sc.tokens
sa = _tool("subs_assemble", "3.2. Subs Assemble.py")


def score(cues_a, cues_f):
    ta, tf = tokens(cues_a), tokens(cues_f)
    sm = difflib.SequenceMatcher(a=[t[0] for t in ta], b=[t[0] for t in tf], autojunk=False)
    pair = {}
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                pair[i1 + k] = j1 + k
    ba = {i for i, t in enumerate(ta) if t[3] == 0 and i > 0 and i in pair}
    bf = {j for j, t in enumerate(tf) if t[3] == 0 and j > 0}
    inv = set(pair.values())
    bf = {j for j in bf if j in inv}
    hit = sum(1 for i in ba if pair[i] in bf)
    hang = sum(1 for i in pair if ta[i][3] == ta[i][4] - 1 and ta[i][4] > 1 and tf[pair[i]][3] == 0)
    ds = [cues_f[tf[pair[i]][2]]["a"] - cues_a[ta[i][2]]["a"] for i in ba | {0} if i in pair and (pair[i] in bf or pair[i] == 0)]
    return {"p": hit / max(1, len(ba)), "r": hit / max(1, len(bf)), "hang": hang, "cues": len(cues_a),
            "fcues": len(cues_f), "shift": statistics.median(ds) if ds else 0.0}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
        os.path.join(os.path.dirname(HERE), "#analysis")
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else ""
    rows = []
    for dp, dn, fn in sorted(os.walk(root)):
        if os.path.basename(dp) != "1. Whisper One Word" or (only and only not in dp):
            continue
        base = os.path.dirname(dp)
        fin, cl = os.path.join(base, "3. Revised & Finalized"), os.path.join(base, "2. Claude the Manager")
        for f in sorted(fn):
            if not f.endswith(".srt") or not os.path.exists(os.path.join(fin, f)):
                continue
            F = load(os.path.join(fin, f))
            A = [{"a": a, "b": b, "t": t} for a, b, t in sa.build(sa.load_words(os.path.join(dp, f)))]
            C = load(os.path.join(cl, f)) if os.path.exists(os.path.join(cl, f)) else None
            ra, rc = score(A, F), (score(C, F) if C else None)
            rows.append((os.path.relpath(os.path.join(base, f), root), ra, rc))
    agg = lambda k, which: statistics.mean(r[which][k] for r in rows if r[which]) if rows else 0
    for name, ra, rc in rows:
        c = f" | ручная P {rc['p']:.2f} R {rc['r']:.2f} вис {rc['hang']}" if rc else ""
        print(f"{name[:52]:52s} авто P {ra['p']:.2f} R {ra['r']:.2f} вис {ra['hang']:2d} титров {ra['cues']}/{ra['fcues']}{c}")
    n = len(rows)
    ha = sum(r[1]["hang"] for r in rows); hc = sum(r[2]["hang"] for r in rows if r[2])
    ca = sum(r[1]["cues"] for r in rows); cc = sum(r[2]["cues"] for r in rows if r[2])
    print(f"\nРоликов: {n}")
    print(f"АВТО   : precision {agg('p',1):.3f}  recall {agg('r',1):.3f}  висяков {ha} на {ca} титров ({100*ha/max(1,ca):.1f}%)")
    print(f"РУЧНАЯ : precision {agg('p',2):.3f}  recall {agg('r',2):.3f}  висяков {hc} на {cc} титров ({100*hc/max(1,cc):.1f}%)")


if __name__ == "__main__":
    main()
