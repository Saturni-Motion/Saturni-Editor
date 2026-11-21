# -*- coding: utf-8 -*-
r"""Saturni · Editor, эффекты картинки: та же математика, что в шейдере страницы (LUT для видео, numpy для фото)."""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from common import *

# --------------------------------------------------------------------------- picture adjustments
# The page previews these with a WebGL shader; color_fn() below is the same math line for line
# (a video gets it as a 3D LUT, a photo directly), so the saved picture looks like the preview.
# Order everywhere: dispersion -> noise reduction -> clarity -> sharpness -> color -> vignette -> grain.

ADJ_KEYS = ("exp", "bri", "con", "sat", "temp", "tint", "hi", "sh", "wh", "bl",
            "sharp", "clar", "grain", "nr", "vig", "disp")
COLOR_KEYS = ADJ_KEYS[:10]
HUES = [0, 30, 60, 120, 180, 240, 270, 300]        # HSL: red, orange, yellow, green, aqua, blue, purple, magenta


def adj_full(adj) -> dict:
    adj = adj or {}
    a = {k: float(adj.get(k, 0) or 0) for k in ADJ_KEYS}
    h = adj.get("hsl") or {}
    a["hsl"] = {x: [float(v) for v in (h.get(x) or [0] * 8)] for x in "hsl"}
    return a


def color_on(a: dict) -> bool:
    return any(a[k] for k in COLOR_KEYS) or any(any(a["hsl"][x]) for x in "hsl")


def _ss(e0, e1, x):
    import numpy as np
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def rgb2hsl(c):
    import numpy as np
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    mx, mn = c.max(1), c.min(1)
    l, d = (mx + mn) / 2, mx - mn
    s = np.where(d > 1e-6, d / np.maximum(1e-6, 1 - np.abs(2 * l - 1)), 0)
    dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, 60 * np.mod((g - b) / dd, 6), np.where(mx == g, 60 * ((b - r) / dd + 2), 60 * ((r - g) / dd + 4)))
    return np.where(d > 1e-6, h, 0), np.clip(s, 0, 1), l


def hsl2rgb(h, s, l):
    import numpy as np
    C = (1 - np.abs(2 * l - 1)) * s
    X = C * (1 - np.abs(np.mod(h / 60, 2) - 1))
    m = l - C / 2
    z = np.zeros_like(h)
    k = np.floor(np.mod(h, 360) / 60)
    r = np.select([k == 0, k == 1, k == 2, k == 3, k == 4], [C, X, z, z, X], C)
    g = np.select([k == 0, k == 1, k == 2, k == 3, k == 4], [X, C, C, X, z], z)
    b = np.select([k == 0, k == 1, k == 2, k == 3, k == 4], [z, z, X, C, C], X)
    return np.stack([r + m, g + m, b + m], 1)


def color_fn(c, a: dict):
    """c: N x 3 float RGB 0..1 -> adjusted, the shader's colorize() in numpy."""
    import numpy as np
    t, g = a["temp"] / 100, a["tint"] / 100
    lin = np.power(np.clip(c, 0, None), 2.2)
    lin = lin * np.array([np.exp(.25 * t), np.exp(-.2 * g), np.exp(-.25 * t)]) * 2 ** a["exp"]
    c = np.power(np.clip(lin, 0, 1), 1 / 2.2)
    c = np.power(c, 2 ** (-a["bri"] / 100))                      # brightness: the midtones
    L = c @ np.array([.2126, .7152, .0722])
    hi, sh = a["hi"] / 100, a["sh"] / 100
    L1 = L + .5 * _ss(.5, 1, L) * (hi * (1 - L) if hi > 0 else hi * L) \
           + .5 * (1 - _ss(0, .5, L)) * (sh * (1 - L) if sh > 0 else sh * L)
    blk, wht = .15 * a["bl"] / 100, 1 + .15 * a["wh"] / 100        # blacks / whites move the ends
    L2 = blk + L1 * (wht - blk)
    c = np.clip(c + (L2 - L)[:, None], 0, 1)
    c = np.clip((c - .5) * (1 + a["con"] / 100) + .5, 0, 1)
    c = np.clip(c @ np.array(sat_matrix(1 + a["sat"] / 100)).T, 0, 1)
    if any(any(a["hsl"][x]) for x in "hsl"):
        h, s, l = rgb2hsl(c)
        ext = HUES + [360]
        dh, ds, dl = (np.interp(h, ext, [v / 100 for v in a["hsl"][x]] + [a["hsl"][x][0] / 100]) for x in "hsl")
        s0 = s
        h = np.mod(h + dh * 30, 360)
        s = np.clip(s * (1 + ds), 0, 1)
        l = np.clip(l + dl * .5 * s0 * np.where(dl > 0, 1 - l, l), 0, 1)
        c = np.clip(hsl2rgb(h, s, l), 0, 1)
    return c


def lut_cube(a: dict, n: int = 33) -> str:
    import numpy as np
    v = np.linspace(0, 1, n)
    b, g, r = np.meshgrid(v, v, v, indexing="ij")                  # .cube: red changes fastest
    out = color_fn(np.stack([r.ravel(), g.ravel(), b.ravel()], 1), a)
    return f"LUT_3D_SIZE {n}\n" + "\n".join(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in out)


def sat_matrix(s: float) -> list[list[float]]:
    return [[0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
            [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
            [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s]]


def vignette_mask(w: int, h: int, k: float):
    import numpy as np
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x + .5 - w / 2) / (w / 2)) ** 2 + ((y + .5 - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    return 1 - k * np.clip((r - .4) / .6, 0, 1)


def _blur(ch, radius: float):
    """About a Gaussian: three box blurs along each axis (running sums, edges repeated)."""
    import numpy as np
    r = max(1, int(round(radius)))
    out = np.asarray(ch, np.float32)
    for axis in (0, 1):
        for _ in range(3):
            p = np.concatenate([np.repeat(out.take([0], axis), r + 1, axis), out, np.repeat(out.take([-1], axis), r, axis)], axis)
            c = np.cumsum(p, axis, dtype=np.float64)
            n = out.shape[axis]
            out = ((c.take(range(2 * r + 1, 2 * r + 1 + n), axis) - c.take(range(0, n), axis)) / (2 * r + 1)).astype(np.float32)
    return out


def _scale_center(ch, k: float):
    """The plane sampled at center + (p - center) * k (k > 1 shrinks it; the edge repeats)."""
    import numpy as np
    h, w = ch.shape
    ys = np.clip(np.round((np.arange(h) + .5 - h / 2) * k + h / 2 - .5).astype(int), 0, h - 1)
    xs = np.clip(np.round((np.arange(w) + .5 - w / 2) * k + w / 2 - .5).astype(int), 0, w - 1)
    return ch[ys][:, xs]


def adjust_array(img, adj: dict):
    """img: float32 RGB 0..1, H x W x 3 -> the same steps as the preview shader."""
    import numpy as np
    a = adj_full(adj)
    H, W = img.shape[:2]
    if a["disp"]:
        k = a["disp"] / 100 * .01
        img = np.stack([_scale_center(img[..., 0], 1 + k), img[..., 1], _scale_center(img[..., 2], 1 - k)], -1)
    if a["nr"]:
        bl = np.stack([_blur(img[..., i], 1.2) for i in range(3)], -1)
        img = img + (bl - img) * a["nr"] / 100
    if a["clar"]:
        L = img @ np.array([.2126, .7152, .0722], np.float32)
        img = img + (a["clar"] / 100 * .8 * (L - _blur(L, max(1.0, .006 * W))))[..., None]
    if a["sharp"]:
        s = a["sharp"] / 100 * .5
        p = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
        img = (1 + 4 * s) * img - s * (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])
    img = np.clip(img, 0, 1)
    if color_on(a):
        flat = img.reshape(-1, 3)
        for i in range(0, len(flat), 1 << 20):                      # in pieces: big photos stay light
            flat[i:i + (1 << 20)] = color_fn(flat[i:i + (1 << 20)], a)
        img = flat.reshape(H, W, 3)
    if a["vig"]:
        img = img * vignette_mask(W, H, a["vig"] / 100 * .9)[..., None]
    if a["grain"]:
        img = img + (np.random.default_rng(7).random((H, W), np.float32) - .5)[..., None] * a["grain"] / 100 * .2
    return np.clip(img, 0, 1)
