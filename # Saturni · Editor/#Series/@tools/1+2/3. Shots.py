# -*- coding: utf-8 -*-
"""Склейки серии: python "3. Shots.py" e3 e4 → words/<стем>_cuts.json. Кадр нормируется по яркости, поэтому видны склейки в тёмных сценах."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from moments_lib import S, video, analyze, find, fps_of
for st in sys.argv[1:]:
    c, d = analyze(video(st))
    fps = fps_of(video(st))
    cuts = [round(k / fps, 3) for k in find(c, d)]
    json.dump({"fps": fps, "cuts": cuts, "frames": len(c)}, open(os.path.join(S, "words", st + "_cuts.json"), "w"))
    print(st, "склеек", len(cuts), flush=True)
