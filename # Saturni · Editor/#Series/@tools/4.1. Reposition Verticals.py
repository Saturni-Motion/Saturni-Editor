#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
4.1. Reposition Verticals.py — пересчитать Position X уже собранных вертикалок текущей логикой
4.1. VReframe-SED.py, не пересобирая их (2026-09-25: после улучшений кадрирования — группа из двух
лиц, без разрезанных лиц, склейки, пропущенные PySceneDetect).

    node "@tools/mjs/#4.1. Dump Vertical Geometry.mjs" geom.json
    python "@tools/4.1. Reposition Verticals.py" geom.json --project-dir "<папка проекта>" --out pos.json
    node "@tools/mjs/4.1. Apply Positions.mjs" pos.json

Склейки = старты клипов горизонтали (на ней уже применён SED 4.1). Позиция — та же формула,
что verticalPositionX() в 4.1:  p = (540 − (x_r − hx·1920)·S/h) / 1080, кламп по половине
видимой ширины исходника. Клипы вертикалки, которых нет в плане (loop-хвост), не трогаются.
"""
import argparse, json, os, subprocess, sys, tempfile

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


find_render = _tool("check_verticals", "#4.1. Check Verticals.py").find_render

_W = {}
def src_width(media):
    if media not in _W:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                            "-of", "csv=p=0", media], capture_output=True, text=True)
        try:
            _W[media] = int(r.stdout.strip().splitlines()[0])
        except Exception:
            _W[media] = 1920
    return _W[media]


def pos_x(target, S, w, h, hx):
    p = (540.0 - (target - hx * 1920.0) * S / h) / 1080.0
    half = w * S / 100.0 / 2.0
    if half * 2 <= 1080:
        return 0.5
    lo, hi = (1080 - half) / 1080.0, half / 1080.0
    return round(min(max(p, lo), hi), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("--project-dir", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    data = json.load(open(a.geom, encoding="utf-8"))
    items, report = [], []
    for seq in data:
        if a.only and a.only not in seq["name"]:
            continue
        name = seq["name"].replace(" ` 1v", "")
        parts = seq["path"].split("\\")
        folder = parts[parts.index("v") - 1] if "v" in parts and parts[parts.index("v") - 1] != "~" else ""
        render = find_render(a.project_dir, name, folder)
        hcl = seq.get("horizontal") or []
        if not render or not hcl:
            report.append(f"!! {folder}/{seq['name']}: нет рендера/горизонтали"); continue
        cuts = sorted(set(round(c["start"], 3) for c in hcl))
        tmp = tempfile.mkdtemp()
        cj, oj = os.path.join(tmp, "cuts.json"), os.path.join(tmp, "plan.json")
        json.dump(cuts, open(cj, "w"))
        subprocess.run([sys.executable, os.path.join(HERE, "4.1. VReframe-SED.py"), "--render", render, "--cuts", cj, "--out", oj],
                       capture_output=True, env={**os.environ, "PYTHONUTF8": "1"})
        plan = {round(c["start"], 2): c for c in json.load(open(oj, encoding="utf-8"))["clips"]}
        changed = 0
        for c in seq["vertical"]:
            if c["track"] > 2:
                continue
            pe = plan.get(round(c["start"], 2))
            hc = next((h for h in hcl if h["start"] - 0.02 <= c["start"] < h["end"] - 0.02), None)
            if not pe or not hc or not c.get("scale"):
                continue
            new = pos_x(pe["target_x_src"], c["scale"], src_width(c["media"]), hc["scale"] or 100.0,
                        hc["posX"] if hc["posX"] is not None else 0.5)
            if c["posX"] is None or abs(new - c["posX"]) > 0.004:
                items.append({"node_id": c["nodeId"], "position_x": new, "position_y": 0.5, "seq": seq["name"],
                              "folder": folder, "start": c["start"], "old": c["posX"]})
                changed += 1
        report.append(f"{folder}/{seq['name']}: клипов с новой позицией {changed}")
    json.dump(items, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n".join(report))
    for it in items:
        print(f"   {it['folder']}/{it['seq']} {it['start']:6.2f}: {it['old']} -> {it['position_x']}")


if __name__ == "__main__":
    main()
