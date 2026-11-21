#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vertical reframe analysis — SED-aware, face-based, static-only.

Input: a flat render of a HORIZONTAL sequence + the authoritative list of clip
boundary times (from Premiere Scene Edit Detection, timeline seconds).

Pipeline:
  1. For every internal boundary, compare the frames just before / just after it
     (downscaled grayscale). Similar  -> a pause cut inside one continuous scene.
     Different -> a real scene change. => "smart scenes" = runs of clips between
     real scene changes.
  2. Per smart scene: sample frames, detect FACES (YuNet). Choose ONE target with
     hysteresis (keep the face near the previous target; otherwise the most
     "active" one = most optical-flow motion in its lower third ~ mouth). Never
     average two faces. Fallbacks: torchvision person box -> motion centroid ->
     centre.
  3. Static target per smart scene = median of the per-frame target x.
  4. Convert to Premiere Motion at uniform Scale S% (position is NORMALISED 0..1):
        position_x_norm = (seqW/2 - (tx - srcW/2)*(S/100)) / seqW   (clamped)
        position_y_norm = 0.5

Output JSON: real_boundaries, smart_scenes[{index, start, end, clip_indices,
static_x_norm, track: 'V1'|'V2'}], clips[{index, smart_scene, static_x_norm,
scale, pos_y_norm, track}].
"""
import argparse, json, math, os, subprocess
import numpy as np

YUNET = os.path.join(os.path.dirname(__file__), "models",
                     "face_detection_yunet_2023mar.onnx")


def probe(v):
    d = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", v],
        capture_output=True, text=True).stdout)
    s = d["streams"][0]
    return int(s["width"]), int(s["height"]), float(d["format"]["duration"])


def frame_at(v, t, w, h):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0,t):.3f}", "-i", v,
         "-frames:v", "1", "-vf", f"scale={w}:{h}", "-pix_fmt", "gray",
         "-f", "rawvideo", "-"], capture_output=True)
    b = p.stdout
    if len(b) < w * h:
        return None
    return np.frombuffer(b[:w * h], np.uint8).reshape(h, w)


def read_seg(v, t0, t1, fps, w, h, mode="gray"):
    dur = max(0.0, t1 - t0)
    n = max(1, int(round(dur * fps)))
    px = "gray" if mode == "gray" else "bgr24"
    ch = 1 if mode == "gray" else 3
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", v, "-t", f"{dur:.3f}",
         "-vf", f"fps={fps},scale={w}:{h}", "-pix_fmt", px, "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE)
    fs = w * h * ch
    for i in range(n):
        buf = p.stdout.read(fs)
        if len(buf) < fs:
            break
        a = np.frombuffer(buf, np.uint8)
        yield t0 + i / fps, (a.reshape(h, w) if ch == 1 else a.reshape(h, w, 3))
    p.stdout.close(); p.wait()


def pyscene_cuts(v, thr=27.0):
    from scenedetect import detect, ContentDetector
    try:
        sl = detect(v, ContentDetector(threshold=thr, min_scene_len=3))  # дефолт 15 кадров терял склейку в 0.56 с от начала
    except Exception:
        return []
    return [s[1].get_seconds() for s in sl[:-1]] if sl else []


def classify_boundaries(v, internal_ts, pys, tol=0.30):
    """A SED boundary is a real scene change iff PySceneDetect also found a cut
    within tol seconds of it (visual discontinuity). Otherwise it's a pause-cut
    inside one continuous scene."""
    out = []
    for t in internal_ts:
        near = min((abs(t - c) for c in pys), default=99.0)
        # второй признак (2026-09-25): разница кадров до/после границы. Пауза-рез внутри плана
        # ≤16, смена плана ≥39 (замер на 13 границах) — порог 28. Ловит склейки, которые
        # PySceneDetect пропустил (короткий первый план, похожая картинка).
        a = frame_at(v, t - 0.06, 160, 90); b = frame_at(v, t + 0.02, 160, 90)
        diff, corr = 0.0, 1.0
        if a is not None and b is not None:
            a = a.astype(np.float32); b = b.astype(np.float32)
            # Летербокс (2026-10-29, Мусор: картинка 1920×800 в рендере 1080, тёмная гамма) — чёрные
            # полосы разбавляли разницу, и смена плана давала 15–20 (< 28): серия сливалась в одну
            # умную сцену с одной позицией. Считаем только по строкам картинки + корреляция кадров:
            # смена плана ≤0.10, пауза-рез внутри плана ≥0.19 (замер на 13 границах).
            rows = np.where((a.mean(1) > 12) | (b.mean(1) > 12))[0]
            if len(rows) >= 10:
                a, b = a[rows[0]:rows[-1] + 1], b[rows[0]:rows[-1] + 1]
            diff = float(np.abs(a - b).mean())
            if a.std() > 1 and b.std() > 1:
                corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        out.append(dict(t=round(t, 3), scene_change=near <= tol or diff >= 28.0 or corr <= 0.15,
                        nearest_pyscene=round(near, 2), frame_diff=round(diff, 1), frame_corr=round(corr, 2)))
    return out


_FACE = None
def face_boxes(bgr):
    """Return list of (cx, cy, w, h, score) in pixels of the given bgr frame."""
    global _FACE
    import cv2
    h, w = bgr.shape[:2]
    if _FACE is None:
        # OpenCV не читает ONNX по пути с не-ASCII («# Saturni · Editor», 2026-11-05) —
        # тогда копия модели в ~/.cache/vreframe.
        model = YUNET
        if not model.isascii():
            import shutil
            from pathlib import Path
            d = Path.home() / ".cache" / "vreframe"
            d.mkdir(parents=True, exist_ok=True)
            model = str(d / os.path.basename(YUNET))
            if not os.path.exists(model) or os.path.getsize(model) != os.path.getsize(YUNET):
                shutil.copy2(YUNET, model)
        _FACE = cv2.FaceDetectorYN_create(model, "", (w, h), 0.6, 0.3, 5000)
    _FACE.setInputSize((w, h))
    _, faces = _FACE.detect(bgr)
    out = []
    if faces is not None:
        for f in faces:
            x, y, fw, fh = f[:4]
            out.append((x + fw / 2.0, y + fh / 2.0, fw, fh, float(f[14])))
    return out


_PMODEL = None
def person_cx(gray_small, back):
    global _PMODEL
    import torch, torchvision
    if _PMODEL is None:
        m = torchvision.models.detection.ssdlite320_mobilenet_v3_large(
            weights="DEFAULT").eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        _PMODEL = (m.to(dev), dev, torch)
    m, dev, torch = _PMODEL
    rgb = np.stack([gray_small] * 3, 0).astype(np.float32) / 255.0
    with torch.no_grad():
        o = m([torch.from_numpy(rgb).to(dev)])[0]
    H, W = gray_small.shape
    best = None
    for bx, l, sc in zip(o["boxes"].cpu().numpy(), o["labels"].cpu().numpy(),
                         o["scores"].cpu().numpy()):
        if l != 1 or sc < 0.45:
            continue
        area = (bx[2] - bx[0]) * (bx[3] - bx[1])
        if best is None or area > best[1]:
            best = ((bx[0] + bx[2]) / 2.0 * back, area)
    return best[0] if best else None


def frame_group_and_slices(tx, faces, win):
    """Правки цели по проверке 2026-09-25 (@tools/#4.1. Check Verticals.py, 12 вертикалок):
    1) двойной план, где оба лица С ПЛЕЧАМИ влезают в окно, — центр на всю группу, а не на
       одного (раньше говорящую ведущую справа резало краем, окно стояло на соседе);
    2) лицо не должно разрезаться краем окна: если соседнее заметное лицо попадает в окно
       частично — сдвигаем окно, чтобы оно ушло целиком (или вошло целиком, если так ближе),
       не выпуская главное лицо. faces: (cx, cy, fw, fh, score) в px исходника; win — ширина окна."""
    faces = [f for f in faces if f[4] >= 0.82]   # 0.70-0.74 = ложные «лица» на занавеске
    if not faces:
        return tx
    big = max(f[2] * f[3] for f in faces)
    sig = [f for f in faces if f[2] * f[3] >= 0.35 * big]
    pad = 0.55                                   # плечи/волосы по бокам лица, в ширинах лица
    left = min(f[0] - f[2] * (0.5 + pad) for f in sig)
    right = max(f[0] + f[2] * (0.5 + pad) for f in sig)
    if len(sig) > 1 and right - left <= win * 0.96:
        return (left + right) / 2.0
    main = min(sig, key=lambda f: abs(f[0] - tx))
    m0, m1 = main[0] - main[2] * 0.5, main[0] + main[2] * 0.5
    for f in sig:
        if f is main:
            continue
        f0, f1 = f[0] - f[2] * 0.5, f[0] + f[2] * 0.5
        x0, x1 = tx - win / 2.0, tx + win / 2.0
        if f1 <= x0 or f0 >= x1 or (f0 >= x0 and f1 <= x1):
            continue                                 # целиком снаружи или целиком внутри
        out_shift = (f1 - x0 + 4) if f[0] < tx else -(x1 - f0 + 4)      # выгнать соседа
        in_shift = (f0 - x0 - 4) if f[0] < tx else (f1 - x1 + 4)        # впустить соседа
        for sh_ in sorted((out_shift, in_shift), key=abs):
            nx0, nx1 = x0 + sh_, x1 + sh_
            if nx0 <= m0 - main[2] * 0.15 and nx1 >= m1 + main[2] * 0.15:
                tx += sh_
                break
    return tx


def analyse_scene(v, t0, t1, sw, sh, fps, win=None):
    """Return (static target_x source-px, coverage 0..1 = fraction of frames with
    a real face/person detection). Fallbacks never jump to the frame edge: hold
    the previous target, else use the running mean, else centre."""
    import cv2
    dw = 960; dh = int(round(dw * sh / sw)); back = sw / dw   # bigger -> small faces
    frames = list(read_seg(v, t0, t1, fps, dw, dh, "bgr"))
    if not frames:
        return sw / 2.0, 0.0
    prev_gray = None
    targets = []
    hits = 0
    lock_x = None
    lock_tol = 0.13 * sw
    frame_faces = []
    for _, bgr in frames:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        faces = face_boxes(bgr)
        tx = None
        if faces:
            faces = [(cx * back, cy * (sh / dh), fw * back, fh * (sh / dh), s)
                     for (cx, cy, fw, fh, s) in faces]
            # 2026-09-25, Абу Шоу №3: на общем плане сцены затылки зрителей давали ложные
            # «лица» 0.61-0.79 крупнее настоящего (0.91-0.93) — окно уезжало на зал. Есть
            # уверенное лицо — слабые не участвуют (в тёмных сценах без уверенных — остаются).
            if any(f[4] >= 0.82 for f in faces):
                faces = [f for f in faces if f[4] >= 0.82]
            if lock_x is not None:
                near = [f for f in faces if abs(f[0] - lock_x) <= lock_tol]
                if near:
                    tx = min(near, key=lambda f: abs(f[0] - lock_x))[0]
            if tx is None:
                if len(faces) == 1 or prev_gray is None:
                    tx = max(faces, key=lambda f: f[2] * f[3])[0]
                else:
                    flow = cv2.calcOpticalFlowFarneback(
                        prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                    mag = np.linalg.norm(flow, axis=2)
                    best, bestm = None, -1.0
                    for (cx, cy, fw, fh, s) in faces:
                        x0 = int(max(0, (cx - fw / 2) / back))
                        x1 = int(min(dw, (cx + fw / 2) / back))
                        y0 = int(max(0, cy / (sh / dh)))
                        y1 = int(min(dh, (cy + fh / 2) / (sh / dh)))
                        m = mag[y0:y1, x0:x1].sum() if x1 > x0 and y1 > y0 else 0.0
                        if m > bestm:
                            bestm, best = m, cx
                    tx = best if best is not None else \
                        max(faces, key=lambda f: f[2] * f[3])[0]
            hits += 1
        if tx is not None and faces and win:
            tx = frame_group_and_slices(tx, faces, win)
            frame_faces.append(faces)
        if tx is None:                                       # no face -> person box
            pcx = person_cx(gray, back)
            if pcx is not None:
                tx = pcx; hits += 1
        if tx is None and prev_gray is not None:             # no person -> motion (hands/objects)
            d = np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)).astype(np.uint8)
            d[d < 18] = 0
            col = d.sum(0).astype(np.float64)
            if col.sum() > 6e4:
                xs = np.arange(col.size)
                tx = float((xs * col).sum() / col.sum()) * back
        if tx is None:                                       # nothing -> hold / centre
            tx = lock_x if lock_x is not None else (
                float(np.mean(targets)) if targets else sw / 2.0)
        # soft pull toward centre for extreme targets, then hard clamp to the
        # range that keeps the 9:16 window fully inside the source (no black).
        c = sw / 2.0
        if abs(tx - c) > 0.30 * sw:
            tx = c + (tx - c) * 0.55
        win_half = (dw / 1.0)  # placeholder, real clamp is via to_norm caller
        tx = min(max(tx, 0.16 * sw), 0.84 * sw)
        lock_x = tx
        targets.append(float(tx))
        prev_gray = gray
    cov = hits / max(1, len(frames))
    med = float(np.median(targets))
    if cov < 0.12 and abs(med - sw / 2.0) > 0.25 * sw:
        med = sw / 2.0                                       # nothing reliable -> centre
    elif win and frame_faces:
        # статичная позиция = медиана по кадрам сама может разрезать лицо / уйти с пары —
        # прогоняем ту же проверку группы/разреза от итоговой точки по каждому кадру.
        med = float(np.median([frame_group_and_slices(med, f, win) for f in frame_faces]))
    return med, round(cov, 2)


# ------------------------------------------------------------------------------------------
# Уточнение цели (2026-10-07, стенд на 17 роликах «Околоточного», вариант 13 из 13 — выбран
# по проверке глазами расхождений; разбор: #analysis/Verticals-07.10 (Околоточный)).
# Цель analyse_scene() (поток в нижней половине лица ≈ кто активен/говорит) остаётся главным
# сигналом — он лучше всех угадывал говорящего в двойных планах. Поверх неё:
#  - головы видим не только лицом (YuNet на полном кадре), но и позой YOLO11-pose: профиль,
#    затылок, мелкий общий план;
#  - цель попала на затылок (план «через плечо») -> переключаемся на лицо, повёрнутое к камере;
#  - соседние головы не режем краем окна; пару берём целиком, только если влезает с запасом
#    (≤85% окна), иначе окно на главного;
#  - тот же ракурс, что уже был в ролике, -> та же позиция окна (shot consistency).
# Без ultralytics / модели — тихо остаётся прежний алгоритм (--legacy делает это явно).
POSE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "yolo11s-pose.pt")
_POSE = None
_FACE_FULL = None


def _pose_model():
    global _POSE
    if _POSE is None:
        from ultralytics import YOLO
        import torch
        _POSE = (YOLO(POSE_MODEL), 0 if torch.cuda.is_available() else "cpu")
    return _POSE


def _faces_full(bgr):
    """YuNet на полном кадре (мелкие лица общих планов): (cx, cy, w, h, score)."""
    global _FACE_FULL
    import cv2
    h, w = bgr.shape[:2]
    if _FACE_FULL is None:
        _FACE_FULL = cv2.FaceDetectorYN_create(YUNET, "", (w, h), 0.6, 0.3, 5000)
    _FACE_FULL.setInputSize((w, h))
    _, f = _FACE_FULL.detect(bgr)
    return [] if f is None else [(float(r[0] + r[2] / 2), float(r[1] + r[3] / 2), float(r[2]), float(r[3]), float(r[14]))
                                 for r in f if float(r[14]) >= 0.75]


def _heads(bgr):
    """Головы кадра: dict(x, size, hw — полуширина головы с плечами, facing)."""
    model, dev = _pose_model()
    H = bgr.shape[0]
    hs = []
    r = model.predict(bgr, imgsz=960, conf=0.35, verbose=False, device=dev)[0]
    if r.boxes is not None and len(r.boxes):
        for b, c, kp in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.keypoints.data.cpu().numpy()):
            pts = [k for k in kp[:5] if k[2] >= 0.45]
            bw = b[2] - b[0]
            sh = abs(kp[5][0] - kp[6][0]) if kp[5][2] >= 0.45 and kp[6][2] >= 0.45 else 0
            if pts:
                hx = float(np.mean([k[0] for k in pts]))
                ew = abs(kp[3][0] - kp[4][0]) if kp[3][2] >= 0.45 and kp[4][2] >= 0.45 else 0
                head_w = max(ew, sh * 0.45, bw * 0.28, 30)
            elif c >= 0.5 and (b[3] - b[1]) > 0.25 * H:
                hx = float((b[0] + b[2]) / 2); head_w = max(bw * 0.3, 30)
            else:
                continue
            hs.append(dict(x=hx, size=float(head_w), hw=float(head_w) * 0.95, box=b,
                           facing=bool(kp[0][2] >= 0.5 and (kp[1][2] >= 0.5 or kp[2][2] >= 0.5))))
    for cx, cy, fw, fh, s in _faces_full(bgr):
        m = next((h for h in hs if "box" in h and h["box"][0] <= cx <= h["box"][2] and
                  h["box"][1] - 20 <= cy <= h["box"][1] + 0.45 * (h["box"][3] - h["box"][1])), None)
        if m:
            m.update(x=cx, size=max(m["size"], fw), hw=max(m["hw"], fw * 1.05), facing=True)
        else:
            hs.append(dict(x=cx, size=fw, hw=fw * 1.05, facing=True))
    return hs


def _tracks(frames_heads, tol):
    tracks = []
    for fi, hs in enumerate(frames_heads):
        used = set()
        for h in sorted(hs, key=lambda h: -h["size"]):
            best, bd = None, tol
            for ti, tr in enumerate(tracks):
                if ti in used or tr["last"] < fi - 6:
                    continue
                d = abs(tr["pts"][-1]["x"] - h["x"])
                if d < bd:
                    best, bd = ti, d
            if best is None:
                tracks.append(dict(pts=[h], last=fi)); used.add(len(tracks) - 1)
            else:
                tracks[best]["pts"].append(h); tracks[best]["last"] = fi; used.add(best)
    return tracks


def refine_target(v, t0, t1, tx0, sw, sh, fps, win):
    """Уточнённая статичная цель умной сцены (px исходника) от цели analyse_scene() tx0."""
    frames = [bgr for _, bgr in read_seg(v, t0 + 0.03 if t1 - t0 > 0.2 else t0, t1, fps, sw, sh, "bgr")]
    if not frames:
        return tx0
    trs = _tracks([_heads(f) for f in frames], 0.10 * sw)
    st = []
    for tr in trs:
        p = tr["pts"]
        st.append(dict(x=float(np.median([q["x"] for q in p])), size=float(np.median([q["size"] for q in p])),
                       hw=float(np.median([q["hw"] for q in p])), pres=len(p) / len(frames),
                       facing=float(np.mean([1.0 if q["facing"] else 0.0 for q in p]))))
    cand = [q for q in st if q["pres"] >= 0.25]
    if not cand:
        return tx0
    big = max(q["size"] for q in cand)
    for q in cand:
        q["w"] = q["pres"] * (q["size"] / big) ** 2 * (0.25 + 0.75 * q["facing"])
    near = [q for q in cand if abs(q["x"] - tx0) <= 0.12 * sw]
    if not near:
        return tx0
    main = max(near, key=lambda q: q["w"])
    if main["facing"] < 0.5:                       # затылок на переднем плане -> лицо
        alt = [q for q in cand if q is not main and q["facing"] >= 0.7 and q["size"] >= 0.5 * main["size"]]
        if alt:
            main = max(alt, key=lambda q: q["w"])
    sig = [q for q in cand if q["size"] >= 0.35 * main["size"]]
    left = min(q["x"] - q["hw"] for q in sig); right = max(q["x"] + q["hw"] for q in sig)
    if len(sig) > 1 and right - left <= win * 0.85 and left <= main["x"] <= right:
        return (left + right) / 2.0
    tx = main["x"]
    for q in sorted(sig, key=lambda q: -q["w"]):   # соседей не режем краем окна
        if q is main:
            continue
        x0, x1 = tx - win / 2, tx + win / 2
        f0, f1 = q["x"] - q["hw"] * 0.55, q["x"] + q["hw"] * 0.55
        if f1 <= x0 or f0 >= x1 or (f0 >= x0 and f1 <= x1):
            continue
        for s_ in sorted([(f1 - x0 + 4) if q["x"] < tx else -(x1 - f0 + 4),
                          (f0 - x0 - 4) if q["x"] < tx else (f1 - x1 + 4)], key=abs):
            if tx + s_ - win / 2 <= main["x"] - main["hw"] * 0.6 and tx + s_ + win / 2 >= main["x"] + main["hw"] * 0.6:
                tx += s_; break
    return tx


def shot_consistency(v, smart, win):
    """Монтаж вернулся к тому же ракурсу -> та же позиция окна, что у прошлого появления
    (если не дальше 0.35 окна — иначе в том же ракурсе другой герой)."""
    th = []
    for s in smart:
        g = frame_at(v, (s["start"] + s["end"]) / 2, 64, 36)
        th.append(None if g is None else g.astype(np.int16))
    for i, s in enumerate(smart):
        if th[i] is None or s["end"] - s["start"] < 0.3:
            continue
        for j in range(i - 1, -1, -1):
            if th[j] is not None and float(np.abs(th[i] - th[j]).mean()) < 12 and \
                    abs(s["target_x_src"] - smart[j]["target_x_src"]) < 0.35 * win:
                s["target_x_src"] = smart[j]["target_x_src"]; s["same_shot_as"] = j
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", required=True)
    ap.add_argument("--cuts", required=True, help="JSON list of boundary seconds (incl 0 and end)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seq", default="1080x1920")
    ap.add_argument("--scale", type=float, default=140.0)
    ap.add_argument("--sample-fps", type=float, default=8.0)
    ap.add_argument("--pyscene-thr", type=float, default=27.0)
    ap.add_argument("--match-tol", type=float, default=0.30,
                    help="a SED cut within this many sec of a PySceneDetect cut = real scene change")
    ap.add_argument("--legacy", action="store_true", help="без уточнения цели (алгоритм до 2026-10-07)")
    a = ap.parse_args()
    refine = not a.legacy
    if refine:
        try:
            _pose_model()
        except Exception as e:                       # нет ultralytics/модели — прежний алгоритм
            print(f"[!] уточнение цели выключено: {type(e).__name__}: {e}")
            refine = False

    qw, qh = (int(x) for x in a.seq.lower().split("x"))
    sw, sh, dur = probe(a.render)
    cuts = sorted(set(round(float(c), 3) for c in json.load(open(a.cuts))))
    if cuts[0] > 0.001:
        cuts = [0.0] + cuts
    if cuts[-1] < dur - 0.05:
        cuts = cuts + [round(dur, 3)]

    # classify internal boundaries against PySceneDetect
    pys = pyscene_cuts(a.render, a.pyscene_thr)
    bounds = classify_boundaries(a.render, cuts[1:-1], pys, a.match_tol)
    real_edges = [0.0] + [b["t"] for b in bounds if b["scene_change"]] + [cuts[-1]]

    # clip list (from cuts) and smart-scene grouping
    clips = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
    sfac = a.scale / 100.0
    half = (qw / sfac) / 2.0
    lo, hi = half, sw - half
    if lo > hi:
        lo = hi = sw / 2.0
    def to_norm(tx):
        px = qw / 2.0 - (min(max(tx, lo), hi) - sw / 2.0) * sfac
        return round(px / qw, 4)

    smart = []
    for si in range(len(real_edges) - 1):
        a0, a1 = real_edges[si], real_edges[si + 1]
        cidx = [k for k, (c0, c1) in enumerate(clips)
                if c0 >= a0 - 1e-3 and c1 <= a1 + 1e-3]
        tx, cov = analyse_scene(a.render, a0, a1, sw, sh, a.sample_fps, win=qw / sfac)
        tx_old = tx
        if refine:
            try:
                tx = refine_target(a.render, a0, a1, tx, sw, sh, a.sample_fps, qw / sfac)
            except Exception as e:                   # сбой уточнения — остаётся прежняя цель
                print(f"[!] сцена {si}: уточнение цели не удалось ({type(e).__name__}: {e})")
        smart.append(dict(index=si, start=round(a0, 3), end=round(a1, 3),
                          clip_indices=cidx, target_x_src=round(tx, 1), target_x_legacy=round(tx_old, 1),
                          coverage=cov, track="V2" if (si + 1) % 2 == 0 else "V1"))
    if refine:
        shot_consistency(a.render, smart, qw / sfac)
    for sc in smart:
        sc["static_x_norm"] = to_norm(sc["target_x_src"])
    clip_map = []
    for si, sc in enumerate(smart):
        for k in sc["clip_indices"]:
            clip_map.append(dict(index=k, start=round(clips[k][0], 3),
                                 end=round(clips[k][1], 3), smart_scene=si,
                                 static_x_norm=sc["static_x_norm"],
                                 target_x_src=sc["target_x_src"],
                                 scale=a.scale, pos_y_norm=0.5, track=sc["track"]))

    json.dump(dict(render=os.path.abspath(a.render), src=[sw, sh],
                   duration=round(dur, 3), seq=[qw, qh], scale=a.scale,
                   all_boundaries=cuts, pyscene_cuts=[round(c, 3) for c in pys],
                   boundary_classes=bounds,
                   real_edges=[round(x, 3) for x in real_edges],
                   smart_scenes=smart, clips=clip_map),
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    npause = sum(1 for b in bounds if not b["scene_change"])
    print(f"{os.path.basename(a.render)}: {len(clips)} clips -> {len(smart)} smart scenes "
          f"({npause} pause-cuts merged; {len(pys)} PySceneDetect cuts)")
    for sc in smart:
        print(f"  scene {sc['index']:2d} [{sc['start']:6.2f}-{sc['end']:6.2f}] "
              f"clips {sc['clip_indices']}  x={sc['static_x_norm']}  cov={sc['coverage']}  -> {sc['track']}")


if __name__ == "__main__":
    main()
