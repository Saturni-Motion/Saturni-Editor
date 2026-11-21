# -*- coding: utf-8 -*-
r"""Saturni · Editor, видео: разбор файла (ffprobe), параметры кодирования, сохранение без перекодирования."""
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
from audio import *
from effects import *

# --------------------------------------------------------------------------- probing

def probe(path: Path) -> dict:
    if path.suffix.lower() in PHOTO_EXT:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            fmt = im.format or path.suffix[1:].upper()
            w, h = ImageOps.exif_transpose(im).size
        return {"kind": "photo", "duration": 0, "w": w, "h": h, "format": fmt, "size": path.stat().st_size,
                "audios": [], "video": False, "cover": False}
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, encoding="utf-8", creationflags=NO_WINDOW)
    j = json.loads(out.stdout or "{}")
    fm = j.get("format") or {}
    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    cover = any(s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic") for s in streams)
    audios = []
    for s in (s for s in streams if s.get("codec_type") == "audio"):
        tags = s.get("tags") or {}
        audios.append({"n": len(audios), "codec": s.get("codec_name", ""), "ch": int(s.get("channels") or 2),
                       "rate": int(s.get("sample_rate") or 48000), "br": int(s.get("bit_rate") or 0),
                       "title": tags.get("title") or ""})
    dur = float(fm.get("duration") or 0)
    size = path.stat().st_size
    if audios and not v and not audios[0]["br"]:
        audios[0]["br"] = int(fm.get("bit_rate") or 0)
    info = {"kind": "video" if v else "audio", "duration": dur, "cover": cover, "audios": audios,
            "video": bool(v), "size": size, "vcodec": "", "w": 0, "h": 0, "fps": 0.0, "vbr": 0}
    if v:
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        rot = 0
        for sd in v.get("side_data_list") or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        rot = rot or int((v.get("tags") or {}).get("rotate") or 0)
        if abs(rot) % 180 == 90:                      # ffmpeg turns the picture on output: crop sees it turned
            w, h = h, w
        num, _, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
        if not 1 <= fps <= 240:
            num, _, den = (v.get("r_frame_rate") or "30/1").partition("/")
            fps = float(num) / float(den or 1)
        vbr = int(v.get("bit_rate") or 0)
        if not vbr:                                    # mkv / webm keep no per-stream bitrate: the rest of the file
            total = int(fm.get("bit_rate") or 0) or (int(size * 8 / dur) if dur else 0)
            vbr = max(0, total - sum(a["br"] or 128000 for a in audios))
        info.update(vcodec=v.get("codec_name", ""), w=w, h=h, fps=round(fps, 3), vbr=vbr, pix=v.get("pix_fmt", ""))
    return info


def video_args(info: dict, ext: str, bitrate: int) -> list[str]:
    """The source's codec family at a predictable average bitrate (VBR capped at 1.5x)."""
    b = max(200_000, int(bitrate or 8_000_000))
    rate = ["-b:v", str(b), "-maxrate", str(int(b * 1.5)), "-bufsize", str(b * 2)]
    if ext == ".webm" or info["vcodec"] in ("vp9", "vp8", "av1") and ext == ".mkv":
        return ["-c:v", "libvpx-vp9", "-b:v", str(b), "-row-mt", "1", "-pix_fmt", "yuv420p"]
    if info["vcodec"] == "hevc":
        return ["-c:v", "libx265", "-preset", "medium", *rate, "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
    return ["-c:v", "libx264", "-preset", "medium", *rate, "-pix_fmt", "yuv420p"]


def copy_plan(q: dict, used: list):
    """Can the picture go out as it is (no re-render)? Only when nothing in it changes: one video
    track without gaps, same format everywhere, no crop / look / fades / new fps or bitrate.
    A copied piece can only start on a keyframe. Fast: the piece starts at the keyframe before the
    cut, so the file keeps a little more, and the sound is moved to match. Exact: such a cut means
    a full render. -> (pieces to copy or None, seconds added)"""
    if not q.get("canvas"):
        return None, 0
    o, a = q.get("out") or {}, adj_full(q.get("adj"))
    lanes = q.get("vlanes") or []
    if q.get("crop") or o.get("fps") or o.get("mbps") or color_on(a) or any(a[k] for k in ADJ_KEYS[10:]) \
            or any(g < .9999 for _, g in q.get("pfade") or []) or not lanes or any(l["clips"] for l in lanes[1:]):
        return None, 0
    v = [c for c in sorted(lanes[0]["clips"], key=lambda c: c["start"]) if c["out"] - c["in"] >= .0005]
    if not v:
        return None, 0
    first, ext = used[v[0]["src"]].info, used[0].path.suffix.lower()
    mp4 = {".mp4", ".mov", ".m4v"}
    tol = 1.5 / (first["fps"] or 30)
    pos = 0.0
    for c in v:
        i = used[c["src"]].info, used[c["src"]].path.suffix.lower()
        if any(i[0].get(k) != first.get(k) for k in ("vcodec", "w", "h", "fps", "pix")) \
                or not (i[1] == ext or i[1] in mp4 and ext in mp4) or abs(c["start"] - pos) > tol:
            return None, 0
        pos = c["start"] + c["out"] - c["in"]
    if abs(pos - float(q["T"])) > tol:
        return None, 0
    half, moves = .5 / (first["fps"] or 30), []
    for c in v:
        keys = used[c["src"]].keyframes()
        before = [k for k in keys if k <= c["in"] + half]
        if not before:
            return None, 0
        moves.append((c, before[-1], max(0.0, c["in"] - before[-1])))
    if any(d > half for _, _, d in moves) and not q.get("fast"):
        return None, 0
    added = 0.0
    if any(d > half for _, _, d in moves):           # stretch the time line at each cut, the sound follows
        stretch = [(c["start"], d) for c, _, d in moves if d > half]
        shift = lambda t: t + sum(d for at, d in stretch if at <= t + 1e-6)
        for lane in q.get("alanes") or []:
            for p in lane["clips"]:
                d = next((d for at, d in stretch if abs(at - p["start"]) < 1e-3), 0)
                linked = d and any(c["src"] == p["src"] and abs(c["in"] - p["in"]) < 1e-3 for c, _, _ in moves)
                p["start"] = shift(p["start"])
                if linked:                           # its own sound starts earlier with the picture
                    e = min(d, p["in"])
                    p["in"] -= e
                    p["start"] -= e
                    if p.get("env"):
                        p["env"] = [[0, p["env"][0][1]]] + [[t + e, g] for t, g in p["env"]]
        if q.get("genv"):
            g = [[shift(t), v_] for t, v_ in q["genv"]]
            q["genv"] = ([[0, g[0][1]]] if g[0][0] > 0 else []) + g
        added = sum(d for _, d in stretch)
        q["T"] = float(q["T"]) + added
    pieces = []
    for c, key, d in moves:
        info = used[c["src"]].info
        pieces.append({"src": c["src"], "in": key if d > half or c["in"] > 0 else 0, "out": c["out"],
                       "end": c["out"] >= info["duration"] - tol})
    return pieces, added
