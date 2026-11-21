# -*- coding: utf-8 -*-
"""
Иконки программ Saturni из одного образца.

Образец — `Saturni.ico` (синяя плитка с белой планетой, как у Saturni · Batch). Знак программы вырезается внутри круга планеты
цветом плитки (как две полоски у Saturni · Subs). Координаты знаков — в сетке 24×24: круг планеты — центр (12, 12), радиус 6.

  python "# Make Icon.py"            — пересобрать все иконки ниже в эту папку (и зелёные ножницы для меню Nilesoft)
Каждая иконка: <Имя>.ico (16…256) и <Имя>.png (256) для просмотра.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "Saturni.ico")
S = 8                                                   # рисовать крупно и уменьшать — гладкие края


def subs(d, k):
    """Заголовок и строка под ним по центру: нижняя тоньше и короче (Saturni · Subs)."""
    w, h = 5.2, 1.3                                     # верхняя строка
    w2, h2 = 4.3, 0.95                                  # нижняя строка
    gap = 1.2
    x0, y0 = 12 - w / 2, 12 - (h + gap + h2) / 2        # блок из двух строк по центру круга
    d.rounded_rectangle((x0 * k, y0 * k, (x0 + w) * k, (y0 + h) * k), radius=h / 2 * k, fill=255)
    y1 = y0 + h + gap
    d.rounded_rectangle(((12 - w2 / 2) * k, y1 * k, (12 + w2 / 2) * k, (y1 + h2) * k), radius=h2 / 2 * k, fill=255)


def tracker(d, k):
    """Рамка слежения: четыре уголка с круглыми концами и точка в центре (Saturni · Motion Tracker)."""
    a, b, t, ln = 9.6, 14.4, 0.8, 1.6                   # квадрат по осям линий, толщина, длина плеча уголка
    for x, sx in ((a, 1), (b, -1)):
        for y, sy in ((a, 1), (b, -1)):
            pts = [(x + sx * ln, y), (x, y), (x, y + sy * ln)]
            d.line([(px * k, py * k) for px, py in pts], fill=255, width=round(t * k), joint="curve")
            for px, py in (pts[0], pts[2]):
                d.ellipse(((px - t / 2) * k, (py - t / 2) * k, (px + t / 2) * k, (py + t / 2) * k), fill=255)
    r = 0.85
    d.ellipse(((12 - r) * k, (12 - r) * k, (12 + r) * k, (12 + r) * k), fill=255)


# Ножницы — векторная перерисовка референса в сетке 512 (симметричны относительно x = 256).
RING, RING_OUT, RING_IN = (156.0, 127.0), 81.4, 53.2          # центр левого кольца, внешний и внутренний радиус
BLADE = [(228.6, 166.3), (168.2, 210.9), (256.4, 335.9), (306.6, 407.2), (338.3, 453.6), (355.3, 472.8),
         (370.6, 458.2), (385.8, 415.3), (382.2, 386.6), (343.1, 330.9), (283.8, 245.9)]   # переднее лезвие: от левого кольца вниз вправо
GAP = [(187, 270), (253, 351), (272, 351), (226, 262)]        # клин зазора по диагонали: шире у оси, сходится к низу
PIVOT, PIVOT_R = (256.4, 263.9), 15.0                          # ось и белая точка


def smooth(pts, n=3):
    """Скруглить кончик лезвия (Чайкин по точкам 3…9 контура); верх лезвия у кольца остаётся прямым."""
    tip = pts[3:10]
    for _ in range(n):
        tip = [tip[0]] + [q for a, b in zip(tip, tip[1:])
                          for q in ((.75 * a[0] + .25 * b[0], .75 * a[1] + .25 * b[1]), (.25 * a[0] + .75 * b[0], .25 * a[1] + .75 * b[1]))] + [tip[-1]]
    return pts[:3] + tip + pts[10:]


def draw_scissors(d, k, ox, oy, sc, ink=255, bg=0):
    """Ножницы: точка (x, y) сетки 512 попадает в ((ox + x·sc)·k, (oy + y·sc)·k)."""
    P = lambda pts: [((ox + x * sc) * k, (oy + y * sc) * k) for x, y in pts]
    u = sc * k

    def ring(cx):
        for r, c in ((RING_OUT, ink), (RING_IN, bg)):
            (x, y), = P([(cx, RING[1])])
            d.ellipse((x - r * u, y - r * u, x + r * u, y + r * u), fill=c)
    ring(512 - RING[0])
    d.polygon(P(smooth([(512 - x, y) for x, y in BLADE])), fill=ink)      # заднее лезвие
    d.polygon(P(GAP), fill=bg)                                     # клин-зазор: заднее лезвие уходит под переднее
    d.polygon(P(smooth(BLADE)), fill=ink)                                  # переднее лезвие
    ring(RING[0])
    (x, y), = P([PIVOT])
    d.ellipse((x - PIVOT_R * u, y - PIVOT_R * u, x + PIVOT_R * u, y + PIVOT_R * u), fill=bg)


def scissors(d, k):
    """Ножницы внутри круга планеты (Saturni · Editor)."""
    h = 7.0                                                        # высота знака в сетке 24 (круг — диаметр 12)
    sc = h / 426
    draw_scissors(d, k, 12 - 256 * sc, 12 - 259 * sc, sc)


GREEN = (132, 255, 175, 255)                            # #84FFAF — зелёный пунктов меню Nilesoft


def menu_scissors(path, sizes=(16, 20, 24, 32, 48, 64, 256)):
    """Зелёные ножницы на прозрачном — значок пункта Saturni · Editor в меню Nilesoft (рамки BMP: читаются везде)."""
    frames = []
    for s in sizes:
        k = s / 24 * S
        m = Image.new("L", (s * S, s * S), 0)
        sc = 23.0 / 426
        draw_scissors(ImageDraw.Draw(m), k, 12 - 256 * sc, 12 - 259 * sc, sc)
        im = Image.new("RGBA", m.size, GREEN)
        im.putalpha(m)
        frames.append(im.resize((s, s), Image.LANCZOS))
    frames[-1].save(path, sizes=[(s, s) for s in sizes], append_images=frames[:-1], bitmap_format="bmp")
    frames[-1].save(path.replace(".ico", ".png"))
    return path


ICONS = {"Saturni · Subs": subs, "Saturni · Motion Tracker": tracker, "Saturni · Editor": scissors}


def cut(im, draw):
    """Вырезать знак в круге: пиксели знака = цвет плитки в той же строке (градиент плитки вертикальный)."""
    im = im.convert("RGBA")
    w, h = im.size
    k = w / 24 * S
    mask = Image.new("L", (w * S, h * S), 0)
    draw(ImageDraw.Draw(mask), k)
    mask = mask.resize((w, h), Image.LANCZOS)
    tile = Image.new("RGBA", (w, h))
    px, sx = tile.load(), max(1, round(w * .12))         # левее круга, но внутри плитки
    for y in range(h):
        c = im.getpixel((sx, y))
        for x in range(w):
            px[x, y] = c
    return Image.composite(tile, im, mask)


def build(name, draw):
    src = Image.open(BASE)
    sizes = sorted(src.info["sizes"])
    frames = {}
    for s in sizes:
        src.size = s
        frames[s] = cut(src.copy(), draw)
    big = frames[max(sizes)]
    big.save(os.path.join(HERE, name + ".png"))
    big.save(os.path.join(HERE, name + ".ico"), sizes=sizes, append_images=[frames[s] for s in sizes if s != max(sizes)])
    return os.path.join(HERE, name + ".ico")


if __name__ == "__main__":
    for n, f in ICONS.items():
        print(build(n, f))
    print(menu_scissors(os.path.join(HERE, "Saturni · Editor (menu).ico")))
