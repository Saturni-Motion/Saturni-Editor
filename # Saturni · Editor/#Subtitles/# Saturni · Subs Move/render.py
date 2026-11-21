# -*- coding: utf-8 -*-
"""
render.py — превью титра 1:1 с рендером 2Stage и миниатюры для таймлайна.

Слой титра рисует тот же libass (ffmpeg subtitles) по тем же строкам ASS, что и
srt_markers.events_from_srt(): один раз на чёрном, один раз на белом фоне, альфа и
цвет восстанавливаются из пары кадров — получается PNG с прозрачностью, который
кладётся поверх видео в приложении.
"""

import os
import json
import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import sys
import importlib.util as _ilu
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "#Series", "@tools")


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


sm = _tool("srt_markers", "@SRT Markers.py")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

NOWIN = 0x08000000 if os.name == "nt" else 0       # без мигающих консолей ffmpeg при pythonw


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, creationflags=NOWIN, **kw)


def escape_path(path):
    """Как в 2Stage: путь для опций фильтра subtitles."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", r"\'").replace(",", r"\,")


def probe(path):
    r = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=width,height,r_frame_rate,codec_name:format=duration", "-of", "json", path])
    try:
        d = json.loads(r.stdout.decode("utf-8", "ignore"))
        s = d["streams"][0]
        num, _, den = s.get("r_frame_rate", "25/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 25.0
        return {"w": int(s["width"]), "h": int(s["height"]), "fps": round(fps, 3) or 25.0,
                "dur": float(d["format"].get("duration") or 0), "codec": s.get("codec_name", "")}
    except Exception:
        return None


def fonts_dir_for(path):
    """Папка со шрифтами титров: @adds рядом с файлом (или выше), иначе стандартная."""
    d = os.path.dirname(os.path.abspath(path)) if path else ""
    for _ in range(3):
        if d and os.path.isdir(os.path.join(d, "@adds")):
            return os.path.join(d, "@adds")
        d = os.path.dirname(d)
    return sm.DEFAULT_ADDS


# ═══════════════════════════ слой титра ═══════════════════════════
_lock = threading.Lock()


def layer(mk, text, orient, style, fonts_dir):
    """Отрендерить один блок -> {name, x, y, w, h, W, H} (координаты ASS) или {empty}."""
    W, H = (1920, 1080) if orient == "h" else (1080, 1920)
    st = dict(style)
    st.setdefault("_style_fs", st["font_size"])
    st["font_file"] = os.path.join(fonts_dir, os.path.basename(st["font_file"]))
    st["bold_file"] = os.path.join(fonts_dir, os.path.basename(st["bold_file"]))
    lines = (text or "").replace("\r\n", "\n").split("\n")
    base_y = st["base_y_h"] if orient == "h" else st["base_y_v"]
    ev = sm.block_events(sm.parse_markers(mk), lines, "0:00:00.00", "0:00:05.00", H, W // 2, base_y, st)
    ass = sm.ass_header(W, H, st) + "".join(ev)
    key = hashlib.sha1((ass + fonts_dir + "|yuv3").encode("utf-8")).hexdigest()[:16]
    name = f"L{key}.png"
    meta_p = os.path.join(CACHE_DIR, f"L{key}.json")
    if os.path.exists(meta_p) and os.path.exists(os.path.join(CACHE_DIR, name)):
        with open(meta_p, "r", encoding="utf-8") as f:
            return json.load(f)

    ass_p = os.path.join(CACHE_DIR, f"L{key}.ass")
    with open(ass_p, "w", encoding="utf-8") as f:
        f.write(ass)
    sub = f"subtitles=L{key}.ass:fontsdir='{escape_path(fonts_dir)}'"
    # фон — yuv, как у настоящего видео: в RGB-режиме libass считает «чёрное» ≈14, а не 0,
    # и превью выходило светлее/мутнее рендера. Оба фона одним кадром (vstack) — сырым потоком, без PNG.
    cmd = ["ffmpeg", "-v", "error", "-y", "-threads", "2",
           "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d=1,format=yuv444p",
           "-f", "lavfi", "-i", f"color=c=white:s={W}x{H}:d=1,format=yuv444p",
           "-filter_complex", f"[0:v]{sub},format=rgb24[a];[1:v]{sub},format=rgb24[b];[a][b]vstack",
           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = _run(cmd, cwd=CACHE_DIR)
    try:
        os.remove(ass_p)
    except OSError:
        pass
    if r.returncode != 0 or len(r.stdout) != W * H * 6:
        raise RuntimeError("ffmpeg: " + r.stderr.decode("utf-8", "ignore").strip()[-400:])

    import numpy as np
    from PIL import Image
    raw = np.frombuffer(r.stdout, dtype=np.uint8).reshape(2 * H, W, 3)
    k, w = raw[:H], raw[H:]
    diff = w.astype(np.int16) - k.astype(np.int16)               # (1−α)·255 по каждому каналу
    alpha = np.clip(1.0 - diff.mean(axis=2) / 255.0, 0, 1).astype(np.float32)
    ys, xs = np.nonzero(alpha > 0.003)
    if not len(xs):
        meta = {"empty": True, "W": W, "H": H}
    else:
        x0, x1 = max(0, xs.min() - 2), min(W, xs.max() + 3)
        y0, y1 = max(0, ys.min() - 2), min(H, ys.max() + 3)
        a = alpha[y0:y1, x0:x1]
        rgb = np.where(a[..., None] > 0.003, k[y0:y1, x0:x1].astype(np.float32) / np.maximum(a[..., None], 1e-3), 0)
        out = np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)
        Image.fromarray(out, "RGBA").save(os.path.join(CACHE_DIR, name), optimize=False, compress_level=1)
        meta = {"name": name, "x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0), "W": W, "H": H}
    with open(meta_p, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return meta


# ═══════════════════════════ миниатюры таймлайна ═══════════════════════════
STRIP_N = 40
STRIP_H = 96


def strip(video, info):
    """Спрайт из STRIP_N кадров по длине видео (в один ряд). -> имя файла в кэше."""
    st = os.stat(video)
    key = hashlib.sha1(f"{video}|{st.st_size}|{st.st_mtime}|{STRIP_N}|{STRIP_H}".encode("utf-8")).hexdigest()[:16]
    name = f"S{key}.jpg"
    out = os.path.join(CACHE_DIR, name)
    if os.path.exists(out):
        return name
    from PIL import Image
    import io
    dur = max(0.1, info.get("dur") or 1)
    tw = max(16, int(round(STRIP_H * info["w"] / max(1, info["h"]))))

    def grab(i):
        t = (i + 0.5) / STRIP_N * dur
        r = _run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                  "-vf", f"scale={tw}:{STRIP_H}", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"])
        try:
            return Image.open(io.BytesIO(r.stdout)).convert("RGB")
        except Exception:
            return Image.new("RGB", (tw, STRIP_H), (20, 20, 26))

    with ThreadPoolExecutor(4) as ex:
        frames = list(ex.map(grab, range(STRIP_N)))
    sprite = Image.new("RGB", (tw * STRIP_N, STRIP_H))
    for i, fr in enumerate(frames):
        sprite.paste(fr.resize((tw, STRIP_H)), (i * tw, 0))
    sprite.save(out, quality=80)
    return name


def clean_cache(max_files=4000):
    """Не даём кэшу слоёв расти бесконечно — удаляем самые старые."""
    try:
        files = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR)]
        if len(files) <= max_files:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[:len(files) - max_files]:
            os.remove(p)
    except Exception:
        pass
