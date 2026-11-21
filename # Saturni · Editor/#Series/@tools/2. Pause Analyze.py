#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Pause/filler analysis for stage 2 (вырезание пауз и филлеров).

Given a source video and a [in, out] range (seconds — normally the
in/out of an approved moment's clip on V1), finds real speech-vs-silence
boundaries and returns the ranges that should be KEPT (speech, with a
safety margin) and the ranges in between that should be CUT (pauses).

Not a standalone stage — called per-clip by 2. Silence Cut.mjs (the Premiere-side
orchestrator, see @instructions/2. Silence Cut.md). Prints one JSON object to
stdout: {"kept": [[s,e], ...], "removed": [[s,e], ...]} in ABSOLUTE seconds
of the SOURCE media (same coordinate space as inPointSeconds/outPointSeconds
from get_full_sequence_info) — not relative to the extracted snippet.

Why Silero VAD, not a loudness/dB threshold:
Saturni's own ask (2026-09-08) was explicit — no manual dB knob, the tool
should work out each clip's own loudness on its own. A fixed-threshold
approach (like the existing auto-editor-based script, `audio:threshold=7%`,
see #notes-pause-removal.md) can't tell voice from loud background music —
it either under-cuts (music mistaken for speech) or over-cuts (quiet dialogue
mistaken for silence), and needs constant per-clip tuning. Silero VAD is a
trained speech classifier, not a level threshold — it adapts per-clip on its
own. Cutting still always happens on the ORIGINAL unmodified audio; Demucs
vocal isolation is only used to help the VAD *see* speech clearly through
music/noise, exactly like the existing subtitles pipeline already does for
WhisperX (same reasoning, see @tools/3.1. Subtitles Pipeline.py).

Usage:
  python 2. Pause Analyze.py --video "D:\...\e4.mov" --in 479.28 --out 534.56
    [--min-kept 0.5] [--min-silence-ms 300] [--pad-start-ms 40] [--pad-end-ms 150]

Padding around each detected speech chunk is intentionally ASYMMETRIC (Saturni, 2026-09-08):
a small pad before the chunk starts (don't leave much dead air before the good part begins),
a bigger pad after it ends (never clip the tail of a word/reaction). Silero's own
`speech_pad_ms` is symmetric, so this is applied manually after getting raw (unpadded)
timestamps from it — see `analyze()`.

Requires: ffmpeg, demucs (already used by 3.1. Subtitles Pipeline.py /
1. Transcribe Plain.py), torch (already installed for WhisperX/Demucs).
First run downloads the Silero VAD model via torch.hub (needs internet
once; cached afterwards in the default torch hub cache, same idea as the
WhisperX/align models already cached locally — see [[highlights-search-tooling]]).
"""
import argparse, json, os, shutil, sys, tempfile

import numpy as np
from scipy.io import wavfile

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


_sp = _tool("subtitles_pipeline", "3.1. Subtitles Pipeline.py")  # тот же audio prep
run, demucs_vocals = _sp.run, _sp.demucs_vocals

# Extra context decoded on each side of the requested [in, out] window so the
# VAD isn't starved of context right at the boundary (a speech chunk that
# starts a few frames before `in` shouldn't get its onset clipped/misread as
# silence). Discarded again after analysis — the returned ranges are always
# clamped to the true [in, out] the caller asked for.
BOUNDARY_PAD_S = 0.6


def extract_range(video, t0, t1, out_wav):
    """Extract [t0, t1] (source seconds) from `video` as a stereo 44.1kHz wav.
    Input-seeked (fast) — a little slop at the very edge is fine, that's what
    BOUNDARY_PAD_S is for; we're feeding a VAD, not cutting picture with this."""
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{max(0.0, t0):.3f}", "-i", video, "-t", f"{max(0.0, t1 - t0):.3f}",
         "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out_wav])


def load_silero():
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad", model="silero_vad", force_reload=False,
        trust_repo=True,
    )
    get_speech_timestamps, _, _, _, _ = utils  # read_audio (3rd) NOT used, see read_audio_16k
    return model, get_speech_timestamps


def read_audio_16k(path):
    """Load a wav as mono float32 @16kHz for Silero VAD, without torchaudio's I/O backend
    (broken in this environment — torchaudio 2.8 shipped with zero registered backends,
    it now expects torchcodec, which isn't installed; same warning seen from whisperx runs).
    Demucs's own output is plain PCM wav, so plain scipy + torch resample is enough."""
    sr, data = wavfile.read(path)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    else:
        data = data.astype(np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1)  # downmix to mono
    wav = torch.from_numpy(data)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)  # pure compute, no I/O backend needed
    return wav


def analyze(video, in_s, out_s, min_kept_s, min_silence_ms, pad_start_ms, pad_end_ms):
    win0 = max(0.0, in_s - BOUNDARY_PAD_S)
    win1 = out_s + BOUNDARY_PAD_S
    pad_start_s, pad_end_s = pad_start_ms / 1000.0, pad_end_ms / 1000.0

    tmp = tempfile.mkdtemp(prefix="pause_analyze_")
    try:
        raw_wav = os.path.join(tmp, "audio.wav")
        extract_range(video, win0, win1, raw_wav)
        vocals_wav = demucs_vocals(raw_wav, tmp)

        model, get_speech_timestamps = load_silero()
        wav = read_audio_16k(vocals_wav)
        # speech_pad_ms=0 here on purpose — Silero's own padding is symmetric, we want
        # asymmetric (small before, bigger after), applied by hand right below instead.
        speech = get_speech_timestamps(
            wav, model, sampling_rate=16000,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=0,
        )
        # -> absolute source seconds, asymmetric pad applied, clamped to [in_s, out_s]
        segs = []
        for s in speech:
            a = win0 + s["start"] / 16000.0 - pad_start_s
            b = win0 + s["end"] / 16000.0 + pad_end_s
            a, b = max(a, in_s), min(b, out_s)
            if b > a:
                segs.append([a, b])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not segs:
        # Nothing detected as speech (shouldn't normally happen on an approved
        # moment) — keep the whole range untouched rather than risk deleting
        # real content on a VAD failure.
        return {"kept": [[in_s, out_s]], "removed": []}

    # Merge any kept segment shorter than min_kept_s into its neighbour —
    # never leave an isolated sliver on its own (Saturni's 500ms floor,
    # matches what's actually observed in his own manual cuts, see
    # @instructions/2. Silence Cut.md).
    merged = [segs[0]]
    for a, b in segs[1:]:
        prev = merged[-1]
        if (a - prev[1]) <= 0 or (prev[1] - prev[0]) < min_kept_s or (b - a) < min_kept_s:
            prev[1] = b  # swallow the gap — treat as one continuous kept range
        else:
            merged.append([a, b])

    removed = [[merged[i][1], merged[i + 1][0]] for i in range(len(merged) - 1)]
    return {"kept": merged, "removed": removed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--in", dest="in_s", type=float, required=True)
    ap.add_argument("--out", dest="out_s", type=float, required=True)
    ap.add_argument("--min-kept", type=float, default=0.5,
                    help="Minimum kept-speech-segment length in seconds (default 0.5, "
                         "per Saturni's own floor — matches his real manual cuts).")
    ap.add_argument("--min-silence-ms", type=int, default=300,
                    help="Gaps shorter than this are NOT treated as a separate pause "
                         "(merged into the surrounding speech) — default 300ms.")
    ap.add_argument("--pad-start-ms", type=int, default=40,
                    help="Padding BEFORE each speech chunk starts — kept small on purpose "
                         "(default 40ms), a sharp start reads better than dead air.")
    ap.add_argument("--pad-end-ms", type=int, default=150,
                    help="Padding AFTER each speech chunk ends — kept generous (default "
                         "150ms), so a cut never clips the tail of a word/reaction.")
    args = ap.parse_args()

    global torch, torchaudio
    import torch, torchaudio  # noqa: E402  (deferred: only needed once we actually run)

    result = analyze(args.video, args.in_s, args.out_s, args.min_kept,
                      args.min_silence_ms, args.pad_start_ms, args.pad_end_ms)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
