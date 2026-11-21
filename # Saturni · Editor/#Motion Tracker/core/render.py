# -*- coding: utf-8 -*-
"""Saturni · Motion Tracker без Premiere: рендер по треку.

Точка трека кадра i: [x, y, conf, scale, angleDeg], scale/angle — подобие от опорного кадра ref к кадру i
(так их считает tracker.py: x_i = A_i (x_ref - c_ref) + p_i, A_i = scale * поворот(angle), y вниз).

stabilize — каждый кадр выворачивается к опорному: опорная деталь стоит на месте (края — чёрные).
attach    — картинка (PNG с прозрачностью) стоит центром на детали опорного кадра и двигается вместе с ней.
props: "p" позиция, "s" масштаб, "r" поворот — какие части движения применять.
Кадры идут в ffmpeg (NVENC, если есть, иначе x264); звук копируется из исходника.
"""
import math
import os
import subprocess

import cv2
import numpy as np

NO_WINDOW = 0x08000000


def _affine(pt, ref, props):
    """A (2x2) и сдвиг p кадра по точке трека с учётом выбранных частей движения."""
    s = pt[3] if "s" in props else 1.0
    a = math.radians(pt[4]) if "r" in props else 0.0
    A = s * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    p = np.array(pt[:2], dtype=np.float64) if "p" in props else np.array(ref[:2], dtype=np.float64)
    return A, p


def _ffmpeg(out, w, h, fps, src, sound, codec):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.6f}", "-i", "-"]
    if sound:
        cmd += ["-i", src, "-map", "0:v", "-map", "1:a?", "-c:a", "aac", "-b:a", "320k", "-shortest"]
    cmd += (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "18"] if codec == "nvenc" else ["-c:v", "libx264", "-crf", "17", "-preset", "medium"])
    cmd += ["-pix_fmt", "yuv420p", out]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)


def _load_overlay(path, w, h):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError("Cannot read the picture: " + path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    k = min(1.0, w / img.shape[1], h / img.shape[0])                 # не больше кадра
    if k < 1:
        img = cv2.resize(img, (int(img.shape[1] * k), int(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
    return img


def render(src, out, points, ref, mode, props, overlay=None, sound=True, progress=None):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video: " + src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = len(points)
    r = points[ref]
    c_ref = np.array(r[:2], dtype=np.float64)
    ov = _load_overlay(overlay, w, h) if mode == "attach" else None
    if ov is not None:
        o_c = np.array([(ov.shape[1] - 1) / 2.0, (ov.shape[0] - 1) / 2.0])
        ov_rgb, ov_a = ov[:, :, :3].astype(np.float32), ov[:, :, 3:].astype(np.float32) / 255.0

    for codec in ("nvenc", "x264"):
        proc = _ffmpeg(out, w, h, fps, src, sound, codec)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        i, failed = 0, False
        while i < n:
            ok, frame = cap.read()
            if not ok:
                break
            A, p = _affine(points[i], r, props)
            if mode == "stabilize":
                # выход x <- кадр i в точке A (x - c_ref) + p
                M = np.hstack([A, (p - A @ c_ref).reshape(2, 1)])
                frame = cv2.warpAffine(frame, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
            else:
                # пиксель картинки u -> A (u - o_c) + p
                M = np.hstack([A, (p - A @ o_c).reshape(2, 1)])
                rgb = cv2.warpAffine(ov_rgb, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
                a = cv2.warpAffine(ov_a, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)[:, :, None]
                frame = (frame.astype(np.float32) * (1 - a) + rgb * a).clip(0, 255).astype(np.uint8)
            try:
                proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                failed = True
                break
            i += 1
            if progress and (i % 10 == 0 or i == n):
                progress(i, n)
        try:
            proc.stdin.close()
        except OSError:
            pass
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() == 0 and not failed:
            cap.release()
            return {"frames": i, "codec": codec}
        if codec == "x264":
            cap.release()
            raise RuntimeError("ffmpeg: " + (err.strip().splitlines() or ["failed"])[-1])
    cap.release()
