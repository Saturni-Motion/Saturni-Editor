#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#4.1. Compare Verticals.py — сверка вертикалок: мои (после 4.1/4.2) против итоговых Saturni.

Оба входа — выгрузки "#4.1. Dump Vertical Geometry.mjs" (только чтение Premiere):
    claude.json — сразу после моего прогона 4.1 → 4.2 (до правок Saturni);
    user.json   — когда Saturni закончил правки.

    python "#4.1. Compare Verticals.py" claude.json user.json <out_dir>

Пишет в out_dir:
    diff.txt   — по каждой вертикалке клипы, где центр кадра сдвинут ≥ MIN_SHIFT px исходника
                 (окно вертикалки = 571 px из 1920) или поменялись границы/Scale;
    cmpN.jpg   — кадры из середины таких клипов (сдвиг ≥ SHEET_SHIFT): красная рамка — моё
                 окно, зелёная — Saturni. Кадр берётся из "<N> ` 1h.mp4" в папке «Серия N»
                 рядом с «@» исходника.
Сводку причин пишу сам в #Analysis/Verticals-DD.MM/#Verticals-[DD.MM].md.
"""
import io
import json
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw

MIN_SHIFT = 40       # px исходника — меньше считаем «то же самое»
SHEET_SHIFT = 150    # px — в раскадровку только явная смена объекта (окно = 571 px)
WIN = 1080           # ширина вертикального кадра
THUMB = 480


def load(path):
    return {x["path"].split("~")[1]: x for x in json.load(open(path, encoding="utf-8"))}


def center(c):
    """x исходника 1920 в центре вертикального кадра."""
    return 960 + (WIN / 2 - c["posX"] * WIN) / (c["scale"] / 100)


def render_for(key, seq):
    m = re.match(r"\\s(\d+)\\v\\(\S+)", key)
    media = next((c["media"] for c in seq["vertical"] if c.get("media")), "")
    root = os.path.dirname(os.path.dirname(media))           # ...\<проект>\@\e1.mp4 -> проект
    return os.path.join(root, f"Серия {m.group(1)}", f"{m.group(2)} ` 1h.mp4"), f"s{m.group(1)}/{m.group(2)}"


def frame(video, t):
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                          "-vf", f"scale={THUMB}:-1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGB") if png else None


def main(claude_json, user_json, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    mine, user = load(claude_json), load(user_json)
    lines, tiles, moved, total = [], [], 0, 0
    win_src = WIN / 1.89
    for key, u in user.items():
        if key not in mine:
            lines.append(f"{key}: нет в моей выгрузке")
            continue
        video, label = render_for(key, u)
        mv = [c for c in mine[key]["vertical"] if c["track"] > 1]   # V1 = фон BG-Blur
        uv = [c for c in u["vertical"] if c["track"] > 1]
        rows = []
        for c in uv:
            mid = (c["start"] + c["end"]) / 2
            mm = [x for x in mv if x["start"] <= mid < x["end"]]
            if not mm:
                rows.append(f"   {c['start']:6.2f}-{c['end']:6.2f} новый клип (у меня нет)")
                continue
            x = mm[0]
            d = center(c) - center(x)
            total += 1
            same_cut = abs(x["start"] - c["start"]) < 0.05 and abs(x["end"] - c["end"]) < 0.05
            if abs(d) >= MIN_SHIFT or not same_cut or c["scale"] != x["scale"]:
                moved += abs(d) >= MIN_SHIFT
                rows.append(f"   {c['start']:6.2f}-{c['end']:6.2f} V{c['track']} центр {center(x):5.0f} -> "
                            f"{center(c):5.0f} (Δ{d:+5.0f}px)"
                            + (f" scale {c['scale']}" if c["scale"] != x["scale"] else "")
                            + ("" if same_cut else f" (у меня {x['start']:.2f}-{x['end']:.2f})"))
            if abs(d) >= SHEET_SHIFT and os.path.exists(video):
                im = frame(video, mid)
                if im is None:
                    continue
                f, dr = THUMB / 1920, ImageDraw.Draw(im)
                for cx, col in ((center(x), (255, 60, 60)), (center(c), (60, 255, 60))):
                    dr.rectangle([(cx - win_src / 2) * f, 2, (cx + win_src / 2) * f, im.height - 3],
                                 outline=col, width=3)
                dr.rectangle([0, 0, 150, 16], fill=(0, 0, 0))
                dr.text((3, 2), f"{label} {mid:.1f}s d{d:+.0f}", fill=(255, 255, 255))
                tiles.append(im)
        lines.append(f"{label}: клипов {len(uv)} (у меня {len(mv)}), изменено {len(rows)}")
        lines += rows
    lines.append(f"ИТОГО: сдвинуто ≥{MIN_SHIFT}px {moved} из {total}")
    open(os.path.join(out_dir, "diff.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    cols = 4
    for p in range(0, len(tiles), 16):
        chunk = tiles[p:p + 16]
        h = chunk[0].height
        sheet = Image.new("RGB", (THUMB * cols, h * ((len(chunk) + cols - 1) // cols)))
        for i, t in enumerate(chunk):
            sheet.paste(t, ((i % cols) * THUMB, (i // cols) * h))
        sheet.save(os.path.join(out_dir, f"cmp{p // 16}.jpg"), quality=80)
    print("\n".join(lines[-1:]), f"| раскадровок: {len(tiles)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
