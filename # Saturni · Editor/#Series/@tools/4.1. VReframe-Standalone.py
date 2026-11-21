#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vertical reframe (stage 4) — standalone, no Premiere.

Input: a rendered HORIZONTAL video (16:9). Output:
  * <base>.mp4          — finished 9:16 vertical with a calm smoothed pan
  * <base>.vreframe.json — analysis for later Premiere Motion internalisation

Method:
  1. PySceneDetect (content / pixel match, NOT time) -> real scene cuts.
     Each interval between cuts is one continuous "scene" for reframing.
  2. Per scene: track subject (torchvision person detector) and/or motion
     (frame-diff centroid), build a calm horizontal path
     (velocity cap + pull-to-median + deadzone), clamp to the valid window.
  3. Convert to Premiere Motion geometry at the given uniform Scale S%:
       visible_src_w = seqW / (S/100)
       position_x_px = seqW/2 - (target_x_src - srcW/2) * (S/100)     [seq px]
       position_x_norm = position_x_px / seqW      <-- Premiere wants 0..1 !
       position_y_norm = 0.5
     (Scale is a %, not a coordinate — passed through as-is.)
  4. Render the vertical by cropping the SAME source (frame-accurate to it).

The JSON stores, per scene and per 0.1s keyframe, position_x_norm plus one
static median — the static value is what set_clip_properties(_batch) needs when
pushing into Premiere (that MCP path is static-per-clip; keyframe paths need the
UXP backend).
"""
import argparse, json, math, os, subprocess
import numpy as np


def geom(src_w, src_h, seq_w, seq_h, scale_pct):
    s = scale_pct / 100.0
    half = (seq_w / s) / 2.0
    lo, hi = half, src_w - half
    if lo > hi:
        lo = hi = src_w / 2.0
    def px(tx):
        return seq_w / 2.0 - (min(max(tx, lo), hi) - src_w / 2.0) * s
    def inv(p):
        return src_w / 2.0 - (p - seq_w / 2.0) / s
    return dict(s=s, lo=lo, hi=hi, px=px, inv=inv,
                sw=src_w, sh=src_h, qw=seq_w, qh=seq_h, scale=scale_pct)


def scene_cuts(video, thresh):
    from scenedetect import detect, ContentDetector
    sl = detect(video, ContentDetector(threshold=thresh))
    return [s[0].get_seconds() for s in sl]  # scene START times; [0] == 0.0


def read_gray(video, t0, t1, fps, w, h):
    dur = max(0.0, t1 - t0)
    n = max(1, int(round(dur * fps)))
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-i", video,
         "-t", f"{dur:.3f}", "-vf", f"fps={fps},scale={w}:{h}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    fs = w * h
    for i in range(n):
        b = p.stdout.read(fs)
        if len(b) < fs:
            break
        yield t0 + i / fps, np.frombuffer(b, np.uint8).reshape(h, w)
    p.stdout.close(); p.wait()


_M = None
def _model():
    global _M
    if _M is None:
        import torch, torchvision
        m = torchvision.models.detection.ssdlite320_mobilenet_v3_large(
            weights="DEFAULT").eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        _M = (m.to(dev), dev, torch)
    return _M


def persons(gray, back):
    """All detected people as (cx_src, area_frac, x0_src, x1_src)."""
    m, dev, torch = _model()
    rgb = np.stack([gray] * 3, 0).astype(np.float32) / 255.0
    with torch.no_grad():
        o = m([torch.from_numpy(rgb).to(dev)])[0]
    H, W = gray.shape
    out = []
    for b, l, sc in zip(o["boxes"].cpu().numpy(), o["labels"].cpu().numpy(),
                        o["scores"].cpu().numpy()):
        if l != 1 or sc < 0.45:
            continue
        out.append(((b[0] + b[2]) / 2.0 * back,
                    (b[2] - b[0]) * (b[3] - b[1]) / (W * H),
                    b[0] * back, b[2] * back))
    return out


def motion_profile(prev, cur, sw):
    """Per-source-column motion mass (len sw) and its centroid x, or (None,None,0)."""
    d = np.abs(cur.astype(np.int16) - prev.astype(np.int16)).astype(np.uint8)
    d[d < 18] = 0
    col = d.sum(0).astype(np.float64)
    tot = col.sum()
    if tot < 8e5:
        return None, None, 0.0
    xs = np.arange(col.size)
    cx = (xs * col).sum() / tot / col.size * sw
    prof = np.interp(np.linspace(0, col.size - 1, sw), np.arange(col.size), col)
    return prof, cx, float(tot)


def pick_target(ppl, prof, mcx, sw):
    """Choose the horizontal target: the ACTIVE person (most motion inside their
    box -> usually the one talking/gesturing), else biggest person, else motion,
    else centre."""
    if ppl:
        if prof is not None:
            scored = []
            for cx, a, x0, x1 in ppl:
                i0, i1 = int(max(0, x0)), int(min(sw, x1))
                mmass = prof[i0:i1].sum() if i1 > i0 else 0.0
                scored.append((mmass + 0.15 * a * prof.sum(), cx))  # motion + slight size prior
            scored.sort(reverse=True)
            if scored[0][0] > 0:
                return scored[0][1]
        return max(ppl, key=lambda p: p[1])[0]          # biggest
    if mcx is not None:
        return mcx
    return sw / 2.0


def smooth(ts, xs, win, max_vel, pull, dead):
    ts = np.asarray(ts, float); xs = np.asarray(xs, float)
    if len(xs) < 3:
        return xs
    med = float(np.median(xs))
    xs = med + (xs - med) * (1.0 - pull)
    dt = float(np.median(np.diff(ts))) or 0.125
    k = max(3, (int(round(win / dt)) | 1))
    ker = np.hanning(k); ker /= ker.sum()
    sm = np.convolve(np.pad(xs, k // 2, mode="edge"), ker, "valid")
    out = sm.copy()
    for i in range(1, len(out)):
        if abs(out[i] - out[i - 1]) < dead:
            out[i] = out[i - 1]
        dv = out[i] - out[i - 1]
        lim = max_vel * (ts[i] - ts[i - 1])
        if abs(dv) > lim:
            out[i] = out[i - 1] + math.copysign(lim, dv)
    return out


def analyse(video, dur, g, cuts, mode, sfps, det_w, win, max_vel, pull, dead):
    sw, sh = g["sw"], g["sh"]
    dh = int(round(det_w * sh / sw)); back = sw / det_w
    use_person = mode in ("person", "blend")
    use_motion = mode in ("motion", "blend")
    bounds = sorted(set([0.0] + [c for c in cuts if 0 < c < dur] + [dur]))
    scenes = []
    for si in range(len(bounds) - 1):
        t0, t1 = bounds[si], bounds[si + 1]
        ts, xs, prev = [], [], None
        for t, fr in read_gray(video, t0, t1, sfps, det_w, dh):
            ppl = persons(fr, back) if use_person else []
            prof = mcx = None
            if use_motion and prev is not None:
                prof, mcx, _ = motion_profile(prev, fr, sw)
            prev = fr
            if mode == "motion":
                x = mcx if mcx is not None else sw / 2.0
            else:
                x = pick_target(ppl, prof if mode == "blend" else None, mcx, sw)
            ts.append(t); xs.append(float(x))
        xs = np.clip(smooth(ts, xs, win, max_vel, pull, dead), g["lo"], g["hi"])
        kf = []
        stp = max(2, int(round((t1 - t0) * 10)))
        for j in range(stp + 1):
            tt = t0 + (t1 - t0) * j / stp
            xp = float(np.interp(tt, ts, xs)) if len(ts) > 1 else sw / 2
            kf.append([round(tt, 3), round(g["px"](xp) / g["qw"], 4)])
        med = float(np.median(xs)) if len(xs) else sw / 2
        scenes.append(dict(start=round(t0, 3), end=round(t1, 3),
                           static_x_norm=round(g["px"](med) / g["qw"], 4),
                           keyframes_x_norm=kf))
    return scenes


def render(video, dur, scenes, g, out_mp4):
    import cv2
    s = g["s"]; sw, sh, qw, qh = g["sw"], g["sh"], g["qw"], g["qh"]
    vis_w = int(round(qw / s)); vis_h = min(int(round(qh / s)), sh)
    scw, sch = int(round(vis_w * s)), int(round(vis_h * s))
    xo, yo = (qw - scw) // 2, (qh - sch) // 2
    allkf = np.array([p for sc in scenes for p in sc["keyframes_x_norm"]])
    tmp = out_mp4 + ".v.mp4"
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (qw, qh))
    rd = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", video, "-vf", "fps=25,scale=%d:%d" % (sw, sh),
         "-pix_fmt", "bgr24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    fs = sw * sh * 3
    nfr = int(round(dur * 25))
    for i in range(nfr):
        b = rd.stdout.read(fs)
        if len(b) < fs:
            break
        fr = np.frombuffer(b, np.uint8).reshape(sh, sw, 3)
        t = i / 25.0
        pn = float(np.interp(t, allkf[:, 0], allkf[:, 1]))
        tx = g["inv"](pn * qw)
        x0 = min(max(0, int(round(tx - vis_w / 2.0))), sw - vis_w)
        y0 = max(0, (sh - vis_h) // 2)
        crop = cv2.resize(fr[y0:y0 + vis_h, x0:x0 + vis_w], (scw, sch),
                          interpolation=cv2.INTER_AREA)
        cv = np.zeros((qh, qw, 3), np.uint8)
        cv[yo:yo + sch, xo:xo + scw] = crop
        vw.write(cv)
    rd.stdout.close(); rd.wait(); vw.release()
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", tmp, "-i", video,
         "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "medium",
         "-crf", "19", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         out_mp4], check=True)
    os.remove(tmp)


def out_names(source):
    """<dir>/<name> 1v.mp4 next to source; <name> 1v.json basename for --json-dir.
    ' 1h' at the end of the stem -> ' 1v'; otherwise append ' 1v'."""
    d = os.path.dirname(os.path.abspath(source))
    stem = os.path.splitext(os.path.basename(source))[0]
    vstem = stem[:-2] + "1v" if stem.rstrip().endswith("1h") else stem + " 1v"
    return os.path.join(d, vstem + ".mp4"), vstem + ".json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="rendered horizontal 16:9 video")
    ap.add_argument("--json-dir", default=r"D:\# Video\#Поляна\@Render\x\!verticals",
                    help="where the <name> 1v.json analysis file goes")
    ap.add_argument("--seq", default="1080x1920")
    ap.add_argument("--scale", type=float, default=140.0)
    ap.add_argument("--mode", default="blend", choices=["person", "motion", "blend"])
    ap.add_argument("--sample-fps", type=float, default=8.0)
    ap.add_argument("--det-w", type=int, default=640)
    ap.add_argument("--sd-threshold", type=float, default=27.0)
    ap.add_argument("--smooth-win", type=float, default=1.4)
    ap.add_argument("--max-vel", type=float, default=95.0)
    ap.add_argument("--center-pull", type=float, default=0.45)
    ap.add_argument("--deadzone", type=float, default=14.0)
    ap.add_argument("--no-video", action="store_true", help="analysis json only")
    a = ap.parse_args()

    qw, qh = (int(x) for x in a.seq.lower().split("x"))
    out_mp4, json_name = out_names(a.source)
    os.makedirs(a.json_dir, exist_ok=True)
    pj = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", a.source],
        capture_output=True, text=True).stdout)
    sw, sh = int(pj["streams"][0]["width"]), int(pj["streams"][0]["height"])
    dur = float(pj["format"]["duration"])
    g = geom(sw, sh, qw, qh, a.scale)

    cuts = scene_cuts(a.source, a.sd_threshold)
    scenes = analyse(a.source, dur, g, cuts, a.mode, a.sample_fps, a.det_w,
                     a.smooth_win, a.max_vel, a.center_pull, a.deadzone)
    outj = os.path.join(a.json_dir, json_name)
    json.dump({"source": os.path.abspath(a.source), "src": [sw, sh],
               "duration": round(dur, 3), "seq": [qw, qh], "scale": a.scale,
               "pos_y_norm": 0.5, "mode": a.mode,
               "params": dict(sd_threshold=a.sd_threshold, smooth_win=a.smooth_win,
                              max_vel=a.max_vel, center_pull=a.center_pull,
                              deadzone=a.deadzone),
               "scene_cuts": [round(c, 3) for c in cuts],
               "scenes": scenes}, open(outj, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{os.path.basename(a.source)}: {len(scenes)} scenes, cuts={len(cuts)} -> {outj}")

    if not a.no_video:
        render(a.source, dur, scenes, g, out_mp4)
        print("  vertical:", out_mp4)


if __name__ == "__main__":
    main()
