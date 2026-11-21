#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plain (sentence-level) transcript for STORY ANALYSIS, not final subtitles.

Unlike 3.1. Subtitles Pipeline.py (per-word, tight timing budget, for finished
short clips), this script just runs WhisperX large-v3 WITHOUT forced
word-alignment and dumps its own sentence/phrase-level segments straight to
SRT. Many words per line is fine here — the point is to read the plot and
get approximate timing of events for full ~25min raw episodes, not to
deliver broadcast subtitles. See 2026-09-07 conversation ("этап 1, поиск
моментов для серий 4/5").

Reuses extract_audio / demucs_vocals / loudnorm_mono16k from
3.1. Subtitles Pipeline.py (identical audio prep — Demucs vocal isolation still
helps recognition accuracy even though we don't need word-precise timing).

Usage:
  python 1. Transcribe Plain.py "D:\\...\\e4.mov" [more videos...]
    [--model large-v3-turbo] [--target-seg-s 7]

--target-seg-s (default 7, lowered from 10 on 2026-09-16, Saturni — wanted finer granularity for
scene-boundary hunting; picked 5 first, then settled on 7): whisperx's own segments can run 30s+ (avg ~35s
seen on a real 42min episode) — too coarse for scanning for moment boundaries.
Segments longer than this are cut further on sentence punctuation with time
distributed proportionally by character count (approximate, no realignment —
see resplit_segment()). Lower it for more (finer) timestamps, raise it back
toward whisperx's natural segment size to turn this off.

Output: "<video stem>.srt" next to each video. Temp files in "_tmp_plain"
next to the video, deleted after each file finishes.
"""
import argparse, json, math, os, re, shutil, subprocess, sys, time, traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import importlib.util as _ilu
_TOOLS = os.path.dirname(os.path.abspath(__file__))


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


cp = _tool("subtitles_pipeline", "3.1. Subtitles Pipeline.py")
# ниже обычный from-import: модуль уже в sys.modules под этим именем
from subtitles_pipeline import (
    run, ts, extract_audio, demucs_vocals, loudnorm_mono16k, HALLUCINATION_RE,
    PIPELINE_STAGES, STAGE_PROG,
)
# _log/_QUIET reused from subtitles_pipeline (cp._QUIET), not a local flag — this
# module's `run` IS subtitles_pipeline.run, whose DEVNULL-redirect-while-quiet
# behavior reads cp._QUIET, so toggling a separate local flag here would do
# nothing. run_batch() below flips cp._QUIET for the duration, same contract
# subtitles_pipeline's own run_batch() already uses.
_log = cp._log

# Long raw episodes (~40min+) crashed Demucs here (2026-09-08, ~e9.mp4, 42min):
# numpy._core._exceptions._ArrayMemoryError ("Unable to allocate 855. MiB"),
# reproducibly, right when it saves the full-length vocals array — even with
# ~9GB RAM free system-wide. Shorter episodes (~20-25min, e4/e5) never hit this;
# looks like Windows/CUDA virtual-address-space fragmentation around a single
# large (~850MB+) numpy allocation in this environment, not real memory
# pressure. Fix: split into chunks before handing off to Demucs, keeping each
# chunk's own array comfortably under the size that failed, then concatenate
# the vocal stems back together. Local to this script (not touched in
# 3.1. Subtitles Pipeline.py's demucs_vocals) — that shared function already works
# fine for shorter clips elsewhere (subtitles/verticals pipelines), no need to
# risk it.
CHUNK_S = 900  # 15 min


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def demucs_vocals_chunked(audio_wav, out_dir):
    dur = probe_duration(audio_wav)
    if dur <= CHUNK_S * 1.5:
        return demucs_vocals(audio_wav, out_dir)  # short enough, behaves exactly as before

    os.makedirs(out_dir, exist_ok=True)
    n_chunks = math.ceil(dur / CHUNK_S)
    piece_vocals = []
    for i in range(n_chunks):
        t0 = i * CHUNK_S
        piece_in = os.path.join(out_dir, f"piece_{i}.wav")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", str(t0), "-i", audio_wav, "-t", str(CHUNK_S),
             "-c", "copy", piece_in])
        piece_vocals.append(demucs_vocals(piece_in, os.path.join(out_dir, f"d{i}")))

    listfile = os.path.join(out_dir, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as fh:
        for p in piece_vocals:
            fh.write(f"file '{os.path.abspath(p)}'\n")
    out_wav = os.path.join(out_dir, "vocals_full.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", out_wav])
    return out_wav


def whisperx_plain(in_wav, out_dir, model="large-v3"):
    base = ["whisperx", in_wav, "--model", model, "--language", "ru",
            "--device", "cuda", "--batch_size", "4",
            "--vad_onset", "0.35", "--no_align",
            # condition_on_previous_text=False: without it, a long noisy/musical
            # stretch can make Whisper hallucinate a repeated phrase, which then
            # primes every subsequent window as context and runs away for hours
            # (real incident 2026-09-07 on e5.mov: hung 8+h at 100% GPU on a
            # 23-min file that should take ~1min with turbo). Breaks that feedback.
            "--condition_on_previous_text", "False",
            "--output_format", "json", "--output_dir", out_dir,
            "--print_progress", "True"]
    # int8 first, not float16 (2026-09-16, after a real A/B test on a 127s clip: large-v3+int8
    # ran in ~38s vs large-v3+float16's ~90s for the whisperx step alone — same full decoder as
    # float16, just faster inference — with no consistent accuracy difference found on this
    # material; float16 stays as the fallback for GPUs/drivers where int8 kernels misbehave).
    for ctype in ("int8", "float16"):
        try:
            run(base + ["--compute_type", ctype])
            _log(f"  [whisperx compute_type={ctype}] OK")
            break
        except subprocess.CalledProcessError:
            _log(f"  [whisperx compute_type={ctype}] FAILED, trying next")
    stem = os.path.splitext(os.path.basename(in_wav))[0]
    return os.path.join(out_dir, stem + ".json")


# Зависание WhisperX на целой серии (2026-10-01, «Околоточный» e5, 45 мин): 38+ мин при 100% GPU
# и 3.1 ГБ VRAM вместо обычных ~8 мин — повтор истории с e5.mov 2026-09-07, хотя
# condition_on_previous_text=False уже стоит. Лечится дроблением: WhisperX по кускам
# WX_CHUNK_S с таймаутом на кусок; завис кусок — он же половинками; сегменты склеиваются со сдвигом.
WX_CHUNK_S = 600
WX_TIMEOUT_S = 900


def _whisperx_once(in_wav, out_dir, model, timeout_s):
    base = ["whisperx", in_wav, "--model", model, "--language", "ru",
            "--device", "cuda", "--batch_size", "4", "--vad_onset", "0.35", "--no_align",
            "--condition_on_previous_text", "False",
            "--output_format", "json", "--output_dir", out_dir, "--compute_type", "int8"]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_SYMLINKS_WARNING="1")
    _log("  $ " + " ".join(base))
    p = subprocess.Popen(base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        p.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        return None
    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, base)
    return os.path.join(out_dir, os.path.splitext(os.path.basename(in_wav))[0] + ".json")


def whisperx_chunked(in_wav, out_dir, model="large-v3", chunk_s=WX_CHUNK_S, depth=0):
    """Сегменты [{start,end,text}] всей записи; WhisperX по кускам chunk_s с таймаутом."""
    dur = probe_duration(in_wav)
    segs = []
    t = 0.0
    k = 0
    while t < dur - 0.05:
        piece = os.path.join(out_dir, f"wx_{depth}_{k}.wav")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-t", f"{chunk_s:.3f}",
             "-i", in_wav, "-c", "copy", piece])
        js = _whisperx_once(piece, out_dir, model, WX_TIMEOUT_S * chunk_s / WX_CHUNK_S)
        if js is None:
            if depth >= 2:
                raise RuntimeError(f"WhisperX завис на куске {t:.0f}-{t + chunk_s:.0f} с даже после дробления")
            _log(f"  [whisperx] завис на куске {t:.0f}+{chunk_s:.0f} с — дроблю пополам")
            sub = os.path.join(out_dir, f"sub_{depth}_{k}")
            os.makedirs(sub, exist_ok=True)
            part = whisperx_chunked(piece, sub, model, chunk_s / 2, depth + 1)
        else:
            part = load_segments(js)
        segs += [{"start": s["start"] + t, "end": s["end"] + t, "text": s["text"]} for s in part]
        t += chunk_s
        k += 1
    return segs


def load_segments(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    segs = []
    for s in d.get("segments", []):
        txt = str(s.get("text", "")).strip()
        if not txt or "start" not in s or "end" not in s:
            continue
        segs.append({"start": float(s["start"]), "end": float(s["end"]), "text": txt})
    return segs


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:])\s+")


def resplit_segment(seg, target_s):
    """Cut one whisperx segment into finer sub-segments so the quick-pass srt gives
    closer-together timestamps to scan (Saturni, 2026-09-08: ~70 segments across a
    ~42min episode, avg ~35s/segment, was too coarse for finding moment boundaries).

    No word-level alignment is available here (--no_align, on purpose — keeps this
    pass fast, see module docstring), so this is a PROPORTIONAL split: cut the
    segment's text on sentence-enders (. ! ? …), falling back to commas/semicolons
    if there's no sentence break, then distribute the segment's already-known
    [start, end] across the pieces by character-length share. Approximate, not
    exact — fine for reading roughly where something happens, not for a cut point
    (the real cut-point tool is stage 2, `2. Silence Cut.mjs`, on isolated audio).

    BUG FIXED (2026-09-09): the first version split on EVERY sentence-ender in one shot
    and never checked the resulting piece durations against target_s at all — target_s
    only gated whether to start splitting, not how far. On a real 42min episode this gave
    531 pieces with a 2.7s MEDIAN (43 of them under 1s) regardless of whether target_s was
    10, 8, or 6 — target_s wasn't actually controlling granularity. Fixed by splitting into
    elementary sentence pieces first, then greedily re-merging consecutive pieces back up
    toward target_s (see _merge_to_target) — now target_s actually sets the resulting pace."""
    start, end = seg["start"], seg["end"]
    if end - start <= target_s:
        return [seg]

    parts = [p for p in SENTENCE_SPLIT_RE.split(seg["text"].strip()) if p.strip()]
    if len(parts) <= 1:
        parts = [p for p in CLAUSE_SPLIT_RE.split(seg["text"].strip()) if p.strip()]
    if len(parts) <= 1:
        return [seg]  # nothing sensible to split on — leave as one segment

    total_chars = sum(len(p) for p in parts)
    dur = end - start
    fine, t = [], start
    for i, p in enumerate(parts):
        piece_end = end if i == len(parts) - 1 else min(end, t + dur * len(p) / total_chars)
        fine.append({"start": t, "end": piece_end, "text": p.strip()})
        t = piece_end
    return _merge_to_target(fine, target_s)


def _merge_to_target(fine, target_s):
    """Greedily re-merge elementary (sentence-level) pieces into groups whose duration is
    close to target_s — keep folding the next piece in as long as the running group is
    still under target_s. Bounds granularity from BELOW (no more 0.3s fragments) as well as
    from above (no worse than one piece past target_s)."""
    merged = [dict(fine[0])]
    for p in fine[1:]:
        cur = merged[-1]
        if cur["end"] - cur["start"] < target_s:
            cur["end"] = p["end"]
            cur["text"] = cur["text"] + " " + p["text"]
        else:
            merged.append(dict(p))
    return merged


def drop_trailing_hallucinations(segs):
    # Walk backward from the very end and cut only the contiguous run of
    # hallucination-matching segments right at the tail (e.g. a repeated
    # "Продолжение следует..." after an outro card) — stop at the first
    # segment (from the end) that does NOT match, keep everything before it.
    #
    # BUG FIXED (2026-09-08, real incident on ~e9.mp4): the old version checked
    # `HALLUCINATION_RE.search(" ".join(kept[i:]))` starting from i=0 — since
    # that joined string is the WHOLE transcript and already contains the
    # hallucination text near the end, it matched on the very first iteration
    # (i=0) regardless of where the hallucination actually started, wiping out
    # every segment (0 segments written to the srt) instead of just the tail.
    kept = list(segs)
    cut_at = len(kept)
    for i in range(len(kept) - 1, -1, -1):
        if HALLUCINATION_RE.search(kept[i]["text"]):
            cut_at = i
        else:
            break
    if cut_at == len(kept):
        return kept, []
    removed = kept[cut_at:]
    _log("  [hallucination removed] " + repr(" ".join(x["text"] for x in removed)))
    return kept[:cut_at], removed


def write_srt(segs, path):
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        for k, s in enumerate(segs, 1):
            fh.write(f"{k}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}\n\n")


def process(video, workroot, model="large-v3", target_seg_s=7.0, status_cb=None):
    """status_cb(text, prog), if given, drives a status_bar task's status text
    + ♥-bar fill (prog: 0..status_bar.BAR_WIDTH, out of PIPELINE_STAGES reused
    from subtitles_pipeline — same 5 stages, same 2-hearts-per-stage spacing).
    Optional and side-effect-free for plain CLI/import use without a bar."""
    def _st(text, prog=None):
        if status_cb:
            status_cb(text, prog)

    stem = os.path.splitext(os.path.basename(video))[0]
    d = os.path.join(workroot, re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", stem).strip("_") or "clip")
    os.makedirs(d, exist_ok=True)
    _log(f"\n=== {video}\n    temp: {d}")

    audio = os.path.join(d, "audio.wav")
    normed = os.path.join(d, "whisperx_in.wav")
    _st("Извлечение аудио (ffmpeg)…", STAGE_PROG["extract"])
    extract_audio(video, audio)
    _st("Demucs — отделение вокала от музыки…", STAGE_PROG["demucs"])
    vocals = demucs_vocals_chunked(audio, os.path.join(d, "demucs"))
    _st("Нормализация громкости (loudnorm)…", STAGE_PROG["loudnorm"])
    loudnorm_mono16k(vocals, normed)
    _st("WhisperX — распознавание речи (быстрый прогон)…", STAGE_PROG["whisperx"])
    segs = whisperx_chunked(normed, d, model=model)
    segs = [p for s in segs for p in resplit_segment(s, target_seg_s)]
    segs, removed = drop_trailing_hallucinations(segs)
    _st("Сборка чернового srt…", STAGE_PROG["assemble"])
    out_srt = os.path.join(os.path.dirname(os.path.abspath(video)), stem + ".srt")
    write_srt(segs, out_srt)
    _log(f"    segments: {len(segs)}  ->  {out_srt}")
    shutil.rmtree(d, ignore_errors=True)
    return out_srt


def run_batch(videos, model="large-v3", target_seg_s=7.0, workdir=None, on_success=None):
    """Same status_bar-driven batch pattern as subtitles_pipeline.run_batch()
    (2026-09-16, Saturni — for `!transcribe+cleanup.py` in `2. Revised &
    Finalized/`, see 1. Highlights.md): one ♥-bar task per video,
    per-stage text/progress via process()'s status_cb, WIN/LOSE overlay
    ending once every video is done/error. One bad clip must not sink the
    batch.

    on_success(videos), if given, is called with the full (sorted) video list
    ONLY when every clip finished without error — used by the cleanup
    launcher to delete the source videos + itself. NOTE: sb.run() ends in
    os._exit() and never returns to this function's own `return` below (same
    caveat as subtitles_pipeline.run_batch) — any code that must run after a
    successful batch belongs in on_success, not after this call."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
    sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
    if sb is None:
        _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
        sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(sb)

    videos = sorted(videos, key=lambda v: sb.natural_sort_key(os.path.basename(v)))
    # Прикидка на одну серию ~24 мин: реально e10 заняла ~12 мин (2026-09-21).
    sb.configure(script="transcribe_plain", default_task_seconds=720)

    sb.tasks[:] = [
        # weight = размер файла (ETA пропорционально объёму, см. status_bar.py)
        {"n": i, "name": os.path.splitext(os.path.basename(v))[0], "state": "pending",
         "has_pct": True, "prog": 0, "status": "",
         "weight": (os.path.getsize(v) if os.path.isfile(v) else None),
         "t0": None, "t_done": None}
        for i, v in enumerate(videos, 1)
    ]
    failed = []

    def _status(idx, text, prog):
        with sb.lock:
            sb.tasks[idx]["status"] = text
            if prog is not None:
                sb.tasks[idx]["prog"] = prog

    def worker():
        cp._QUIET = True
        try:
            for i, v in enumerate(videos):
                with sb.lock:
                    sb.tasks[i]["state"] = "running"
                    sb.tasks[i]["t0"] = time.time()
                try:
                    root = workdir or os.path.join(os.path.dirname(os.path.abspath(v)), "_tmp_plain")
                    os.makedirs(root, exist_ok=True)
                    try:
                        process(v, root, model=model, target_seg_s=target_seg_s,
                                status_cb=lambda t, p, i=i: _status(i, t, p))
                    finally:
                        shutil.rmtree(root, ignore_errors=True)
                    with sb.lock:
                        sb.tasks[i]["state"] = "done"
                        sb.tasks[i]["t_done"] = time.time()
                except Exception as e:
                    tb = traceback.format_exc()
                    with sb.lock:
                        sb.tasks[i]["state"] = "error"
                        sb.tasks[i]["status"] = f"Ошибка: {type(e).__name__}: {e}"[:160]
                        sb.tasks[i]["t_done"] = time.time()
                    failed.append((v, e, tb))
        finally:
            cp._QUIET = False

    def on_done(_had_failures):
        # На экране — только строки упавших видео; трейсбеки — в лог-файл (2026-09-24).
        if failed:
            sb.write_log("transcribe_plain", "\n\n".join(f"=== {v} ===\n{tb}" for v, e, tb in failed))
            if not sb.is_interactive():
                print(f"\n{len(failed)} video(s) FAILED — tracebacks in {sb.log_path('transcribe_plain')}")
        elif on_success:
            on_success(videos)

    sb.run(worker, on_done=on_done)   # does not return — os._exit() at the end
    return [v for v, _, _ in failed]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--target-seg-s", type=float, default=7.0)
    ap.add_argument("--workdir", default=None,
                    help="temp root; default: '_tmp_plain' next to each video")
    ap.add_argument("--no-ui", action="store_true",
                    help="force headless mode: plain line log, no ♥-screen, no ending video, "
                         "no key wait, exit code 1 on failure. Auto-enabled anyway when "
                         "stdin/stdout is not a real console (pipe, redirect, agent run) — "
                         "see status_bar.is_interactive().")
    a = ap.parse_args()
    if a.no_ui:
        os.environ["SATURNI_HEADLESS"] = "1"
    run_batch(a.videos, model=a.model, target_seg_s=a.target_seg_s, workdir=a.workdir)


if __name__ == "__main__":
    main()
