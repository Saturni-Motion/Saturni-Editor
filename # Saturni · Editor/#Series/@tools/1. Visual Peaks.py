#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Lightweight visual "motion peaks" finder for stage 1 (поиск моментов) — a fast, GPU-free
complement to the text-only transcript pass, for scenes that read as near-empty in dialogue
but are visually intense (physical action, fights, chases — the "немая потасовка" blind spot
documented in @instructions/1. Highlights-Action.md, 2026-09-08/09).

Pure ffmpeg + Python, no ML model, no GPU. One ffmpeg pass computes a per-frame "scene score"
(frame-to-frame visual difference, ffmpeg's own `scene` metric) across the WHOLE video at once
(not capped at 300s/call like the MCP `detect_motion_peaks` tool). Peaks are picked one per
equal time-bucket across the whole runtime (up to `--max-events`, fewer if a bucket has
nothing worth flagging) — a ceiling, not a forced fixed count — and the bar for "worth
flagging" is a PERCENTILE of that video's own score distribution (`--floor-percentile`,
default 75th), not one fixed number for every series (an action-heavy episode and a quiet
dialogue one have very different score ranges — see compute_floor()). ~25x realtime seen on a
real clip at the default scale, so a 42min episode is roughly 1.5-2min — meant to sit alongside
1. Transcribe Plain.py, not replace it.

This does NOT understand what's happening at a peak — it only says "the picture changed a lot
here". A camera pan, a flash, or a hard cut scores just as high as a real fight. A frame is
grabbed at each peak for a human (or Claude, reading the image directly) to actually judge
relevance — that's the point: cheap triage, not a verdict.

Usage:
  python 1. Visual Peaks.py --video "D:\...\~e9.mp4" [--srt "D:\...\~e9.srt"]
    [--max-events 15] [--min-interval-s 20] [--scale 320]

--srt (optional): the quick-pass srt from 1. Transcribe Plain.py — each reported peak gets
annotated with any subtitle text within +-8s, so it's obvious at a glance which peaks are
already covered by dialogue and which are the actual blind spots worth a manual look.

Output: prints one line per peak (time, score, nearby subtitle text or none) and saves one
contact sheet per peak (6 stills over ~12s, tiled 3x2, earlier->later) into
"<video stem>_peaks\" next to the video.
"""
import argparse, os, re, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PTS_RE = re.compile(r"pts_time:([\d.]+)")
SCORE_RE = re.compile(r"lavfi\.scene_score=([\d.]+)")
TS_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")


def scene_scores(video, scale=320):
    """One ffmpeg pass: per-frame scene-change score across the whole file, downscaled for
    speed (decode cost dominates, not resolution — parsing is cheap either way)."""
    cmd = ["ffmpeg", "-i", video, "-vf",
           f"scale={scale}:-2,select='gt(scene,0)',metadata=print:key=lavfi.scene_score",
           "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out, pending_t = [], None
    for line in proc.stderr.splitlines():
        mt = PTS_RE.search(line)
        if mt:
            pending_t = float(mt.group(1))
            continue
        ms = SCORE_RE.search(line)
        if ms and pending_t is not None:
            out.append((pending_t, float(ms.group(1))))
            pending_t = None
    return out


def compute_floor(scored, percentile=75.0):
    """Floor relative to THIS video's own motion, not one fixed number for every series.
    A fixed absolute floor (tried first, 2026-09-09) only ever got calibrated against one
    busy action clip — wrong assumption for a calmer dialogue-heavy episode (real peaks
    could sit below it, floor picks nothing) or an unusually noisy/grainy source (everything
    clears a fixed floor, it stops filtering anything). Percentile of the episode's own score
    distribution adapts automatically: default 75th percentile means only the top quarter of
    this video's own frames are even eligible, whether its overall motion is high or low."""
    if not scored:
        return 0.0
    vals = sorted(s for _, s in scored)
    idx = min(int(len(vals) * percentile / 100.0), len(vals) - 1)
    return vals[idx]


def pick_peaks(scored, max_events=15, min_interval_s=20.0, floor=0.0):
    """Top-1-per-time-bucket peak picking, not a global top-N — a plain global top-N was
    tested on a real 42min episode (2026-09-09) and came back badly skewed: all 15 peaks
    landed in the first ~26min because an action-heavy opening stretch has much higher raw
    scores than anything later, so a real chase scene near the end never made the list at
    all. Splits the video's own span into `max_events` equal time buckets and takes the
    strongest peak (>= floor) in each — same "spread across the whole runtime" principle
    already used for text candidates in 1. Highlights.md. A bucket with nothing above
    floor is simply skipped (never forces a fake pick). `floor` is expected to already be
    calibrated to this video (see compute_floor) — pass 0.0 to disable filtering entirely."""
    if not scored:
        return []
    t_min = min(t for t, _ in scored)
    t_max = max(t for t, _ in scored)
    bucket_s = max((t_max - t_min) / max_events, 1.0)

    picked = []
    for b in range(max_events):
        b_start, b_end = t_min + b * bucket_s, t_min + (b + 1) * bucket_s
        candidates = sorted(
            ((t, s) for t, s in scored if b_start <= t < b_end and s >= floor),
            key=lambda p: p[1], reverse=True,
        )
        for t, score in candidates:
            if any(abs(t - pt) < min_interval_s for pt, _ in picked):
                continue
            picked.append((t, score))
            break
    picked.sort(key=lambda p: p[0])
    return picked


def load_srt(path):
    if not path or not os.path.exists(path):
        return []
    segs = []
    for block in open(path, encoding="utf-8").read().split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        m = TS_RE.search(lines[1])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text = " ".join(lines[2:]).strip()
        if text:
            segs.append((start, end, text))
    return segs


def nearby_text(segs, t, window=8.0):
    hits = [txt for s, e, txt in segs if s - window <= t <= e + window]
    return " / ".join(hits)[:160] if hits else None


def grab_sheet(video, t, out_path, frames=6, window_s=12.0, cols=3, tile_w=480, lead=0.4):
    """Contact sheet around one peak: `frames` stills spread evenly over `window_s` seconds,
    tiled into ONE jpeg (row-major: left->right, top->bottom = earlier->later).

    Replaces the old single frame (Saturni, 2026-09-22): one still at the exact peak instant
    was often unreadable on its own — on e1 «Околоточный» the two score=1.000 peaks were a
    blown-out white flash and a landscape, and even the one real hit (a prisoner alone in his
    cell right before being strangled) needed context to read. A sequence shows what the
    scene is DOING, not just what one frame looks like.

    The window is skewed so the peak lands ~40% in (`lead`): a little build-up before, more
    of the consequence after. One tiled image instead of N separate files is deliberate —
    Claude reads it in one go, and at the default 3x2 x 480px it is smaller in pixels (so
    cheaper to look at) than a single full-HD frame was."""
    rows = -(-frames // cols)  # ceil
    start = max(t - window_s * lead, 0.0)
    fps = frames / window_s
    vf = f"fps={fps:.6f},scale={tile_w}:-2,tile={cols}x{rows}:padding=4:color=black"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-ss", f"{start:.3f}", "-i", video, "-t", f"{window_s:.3f}",
                     "-vf", vf, "-frames:v", "1", "-q:v", "3", out_path],
                    check=True)
    return start, start + window_s


def ts(t):
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--srt", default=None, help="quick-pass srt for nearby-dialogue annotation (optional)")
    ap.add_argument("--max-events", type=int, default=15)
    ap.add_argument("--min-interval-s", type=float, default=20.0)
    ap.add_argument("--floor-percentile", type=float, default=75.0,
                     help="only frames above this percentile of THIS video's own motion "
                          "score are eligible peaks (default 75 — top quarter). Lower to "
                          "catch more/weaker peaks, raise to be pickier.")
    ap.add_argument("--scale", type=int, default=320)
    ap.add_argument("--sheet-frames", type=int, default=6,
                     help="stills per peak, tiled into one contact sheet (default 6)")
    ap.add_argument("--sheet-window-s", type=float, default=12.0,
                     help="seconds of video the sheet spans around the peak (default 12)")
    ap.add_argument("--sheet-cols", type=int, default=3)
    ap.add_argument("--tile-w", type=int, default=480, help="width of each still in the sheet")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    stem = os.path.splitext(os.path.basename(args.video))[0]
    out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.abspath(args.video)), stem + "_peaks")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[анализ движения] {args.video}")
    scored = scene_scores(args.video, scale=args.scale)
    floor = compute_floor(scored, percentile=args.floor_percentile)
    print(f"  кадров проанализировано: {len(scored)}, порог (p{args.floor_percentile:.0f} этого видео): {floor:.4f}")
    peaks = pick_peaks(scored, max_events=args.max_events, min_interval_s=args.min_interval_s, floor=floor)
    segs = load_srt(args.srt)

    print(f"\n{len(peaks)} пик(ов) движения:")
    for i, (t, score) in enumerate(peaks, 1):
        frame_path = os.path.join(out_dir, f"{i:02d}_{ts(t).replace(':', '-')}.jpg")
        w0, w1 = grab_sheet(args.video, t, frame_path, frames=args.sheet_frames,
                            window_s=args.sheet_window_s, cols=args.sheet_cols, tile_w=args.tile_w)
        txt = nearby_text(segs, t)
        tag = txt if txt else "(без реплик рядом — возможный слепой момент по тексту)"
        print(f"  {i:2d}. {ts(t)}  score={score:.3f}  {tag}")
        print(f"      лист {args.sheet_frames} кадров {ts(w0)}-{ts(w1)}: {frame_path}")

    print(f"\nГотово. Кадры в: {out_dir}")


if __name__ == "__main__":
    main()
