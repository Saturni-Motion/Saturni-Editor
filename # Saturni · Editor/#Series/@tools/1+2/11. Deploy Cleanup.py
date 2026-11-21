# -*- coding: utf-8 -*-
"""Положить «# Cleanup.pyw» в папку серии: python "11. Deploy Cleanup.py" e3 "Highlights-02.11 (Мусор)". Вызывать после рендера."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from moments_lib import S, HERE, series, rate_of
st, run = sys.argv[1], sys.argv[2]
spec = json.load(open(os.path.join(S, f"spec_{st}.json"), encoding="utf-8"))
moments = {m["n"]: {"name": m["name"], "rate": rate_of(m)} for m in spec}
root = os.path.join(os.path.dirname(os.path.dirname(HERE)), "#Analysis")
c = open(os.path.join(HERE, "@Cleanup.pyw"), encoding="utf-8").read()
for a, b in (("__ANALYSIS_ROOT__", root), ("__TOOLS__", HERE), ("__RUN__", run), ("__STEM__", st), ("__BIN__", "s" + st[1:]), ("__MOMENTS__", repr(moments))):
    c = c.replace(a, b)
out = series(st[1:], "# Cleanup.pyw")
open(out, "w", encoding="utf-8").write(c)
print("готово", out)
