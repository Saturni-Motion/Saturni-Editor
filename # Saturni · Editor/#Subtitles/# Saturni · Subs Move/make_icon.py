# -*- coding: utf-8 -*-
"""make_icon.py — иконка Saturni Subs = иконка Saturni Studio 1-в-1 (saturni2.ico из # Saturni · Batch)
+ две одинаковые «прозрачные» полоски по центру круга (закрашены цветом плитки под ними).
-> ui/subs.ico, ui/subs.png и SVG для шапки (печатается; вставить в ui/index.html .brand-mark).
Запуск: python make_icon.py"""

import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
STUDIO_ICO = r"D:\@Hub\# Saturni · Batch\studio\ui\saturni2.ico"

# полоски в координатах 24×24 (круг Studio: центр 12,12, r 6)
LINE_W, LINE_H, LINE_GAP = 5.2, 1.3, 1.2
LINES = [(12 - LINE_W / 2, 12 - LINE_GAP / 2 - LINE_H), (12 - LINE_W / 2, 12 + LINE_GAP / 2)]   # (x, y)


def with_lines(im):
    """Вырезать полоски в круге: пиксели полосок = цвет плитки в той же строке (градиент вертикальный)."""
    im = im.convert("RGBA")
    w, h = im.size
    k, S = w / 24, 8                               # маска крупно и уменьшить — сглаживание
    mask = Image.new("L", (w * S, h * S), 0)
    d = ImageDraw.Draw(mask)
    for x, y in LINES:
        d.rounded_rectangle((x * k * S, y * k * S, (x + LINE_W) * k * S, (y + LINE_H) * k * S), radius=LINE_H / 2 * k * S, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    tile = Image.new("RGBA", (w, h))
    px, sx = tile.load(), max(1, round(w * .12))     # x левее круга, но внутри плитки
    for yy in range(h):
        c = im.getpixel((sx, yy))
        for xx in range(w):
            px[xx, yy] = c
    return Image.composite(tile, im, mask)


SVG = (
    '<svg viewBox="0 0 24 24" width="30" height="30"><defs>'
    '<mask id="satm"><rect width="24" height="24" fill="#fff"/><circle cx="12" cy="12" r="7.3" fill="#000"/></mask>'
    '<mask id="subl" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24"><rect width="24" height="24" fill="#fff"/>'
    + "".join(f'<rect x="{x:.2f}" y="{y:.2f}" width="{LINE_W}" height="{LINE_H}" rx="{LINE_H / 2}" fill="#000"/>' for x, y in LINES)
    + '</mask></defs><g transform="rotate(-45 12 12)" mask="url(#satm)" fill="currentColor" stroke="currentColor" stroke-width=".8" stroke-linejoin="round">'
    '<polygon points="0.6,12 9.6,9.24 9.6,14.76"/><polygon points="23.4,12 14.4,9.24 14.4,14.76"/></g>'
    '<circle cx="12" cy="12" r="6" fill="currentColor" mask="url(#subl)"/></svg>')

if __name__ == "__main__":
    src = Image.open(STUDIO_ICO)
    sizes = sorted(src.info["sizes"])
    frames = {}
    for s in sizes:
        src.size = s
        frames[s] = with_lines(src.copy())
    big = frames[max(sizes)]
    big.save(os.path.join(UI, "subs.png"))
    big.save(os.path.join(UI, "subs.ico"), sizes=sizes, append_images=[frames[s] for s in sizes if s != max(sizes)])
    print(SVG)
