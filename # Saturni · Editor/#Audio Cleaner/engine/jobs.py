"""Jobs: one GPU job at a time; analysis and downloads run beside it. State lives in memory, the UI polls it."""
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d

from . import audio
from .paths import JOBS_DIR, REFS_DIR

JOBS: dict = {}
REFS: dict = {}
_q: "queue.Queue" = queue.Queue()
_gpu = threading.Lock()

STEM_LABELS = {
    "ru": {"vocals": "Вокал", "instrumental": "Музыка", "drums": "Ударные", "bass": "Бас", "other": "Остальное",
           "guitar": "Гитара", "piano": "Клавишные", "nomusic": "Чистый звук", "music": "Убранная музыка"},
    "en": {"vocals": "Vocals", "instrumental": "Music", "drums": "Drums", "bass": "Bass", "other": "Other",
           "guitar": "Guitar", "piano": "Keys", "nomusic": "Clean sound", "music": "Removed music"},
}
STEM_ORDER = ["nomusic", "music", "vocals", "instrumental", "drums", "bass", "guitar", "piano", "other"]


def new_job(name: str) -> dict:
    jid = uuid.uuid4().hex[:10]
    d = JOBS_DIR / jid
    d.mkdir(parents=True, exist_ok=True)
    job = {"id": jid, "name": name, "dir": d, "status": "uploaded", "progress": 0.0,
           "message": "", "outputs": [], "report": None, "match": {}, "analysis": None}
    JOBS[jid] = job
    return job


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "dir" and not k.startswith("_")}


def submit(fn, *args):
    _q.put((fn, args))


def _worker():
    while True:
        fn, args = _q.get()
        try:
            fn(*args)
        except Exception:
            traceback.print_exc()
        finally:
            _q.task_done()


threading.Thread(target=_worker, daemon=True).start()


def _load_refs(ids):
    return {r: audio.load(REFS[r]["wav"]) for r in ids if REFS.get(r, {}).get("status") == "ready"}


# ------------------------------------------------------------------ neural split cache

def _nn_music(job, mix, prog=lambda *a: None, p0=0.0, p1=1.0):
    """BandIt music stem of the original recording, computed once per file."""
    from . import models
    p = job["dir"] / "nn_music.wav"
    if p.exists():
        return audio.load(p)
    with _gpu:
        music = models.bandit_separate(mix, prog, p0, p1)["music"]
    import soundfile as sf
    sf.write(str(p), music.T, audio.SR, subtype="FLOAT")
    return music


PEAKS_PER_SEC = 100


def _save_peaks(path, x):
    """Detailed waveform (100 values per second) so the UI can zoom in."""
    import json
    n = max(1, int(x.shape[-1] / audio.SR * PEAKS_PER_SEC))
    path.write_text(json.dumps(audio.peaks(x, n)), encoding="utf-8")


def _ramp(mask, sec=0.1):
    return uniform_filter1d(mask.astype(np.float32), max(1, int(sec * audio.SR)))


# ------------------------------------------------------------------ main pipeline

# strength level → (margin of the spectral song mask, share of the neural fallback removed)
LEVELS = {"weak": (1.0, 0.6), "soft": (1.5, 0.85), "medium": (2.5, 1.0), "strong": (None, 1.0)}


def _prepare(job, mix, refs, prog):
    """Everything that does not depend on the strength — cached so re-rendering takes seconds."""
    from . import models, refmatch, specmatch
    key = tuple(sorted(refs))
    c = job.get("_cache")
    if c and c["key"] == key:
        return c
    T = mix.shape[-1]
    report = {"refs": {r: {"title": REFS[r]["title"], "segments": []} for r in refs}, "unknown": []}

    # 1. exact copies of the song: precise subtraction
    rest, exact = mix, np.zeros(T, bool)
    if refs:
        prog(0.02, "@exact")
        with _gpu:
            found = refmatch.detect(mix, refs, lambda p: prog(0.02 + 0.06 * p))
        spans = refmatch.assign(mix, refs, found)
        if sum(s["b"] - s["a"] for s in spans) < 3 * audio.SR:
            spans = []  # a second here and there is chance, not the same copy
        if spans:
            prog(0.08, "@subtract")
            with _gpu:
                rest, _, exact = refmatch.subtract(mix, refs, spans, lambda p: prog(0.08 + 0.12 * p))
            for r, segs in refmatch.spans_to_segments(spans).items():
                report["refs"][r]["segments"] += segs

    # 2. neural split of what is left
    prog(0.2, "@separate")
    if exact.any():
        with _gpu:
            music_nn = models.bandit_separate(rest, prog, 0.2, 0.75)["music"]
    else:
        music_nn = _nn_music(job, mix, prog, 0.2, 0.75)

    # 3. other copies of the song: aligned by spectrogram
    matches, spec_active = {}, np.zeros(T, bool)
    if refs:
        prog(0.78, "@spectral")
        with _gpu:
            feat = specmatch.features(music_nn)
            matches = {r: specmatch.match(feat, refs[r], feat.shape[1]) for r in refs}
        for r, segs in matches.items():
            for s in segs:
                a, b = s["a"] / specmatch.FPS, s["b"] / specmatch.FPS
                spec_active[int(a * audio.SR):int(b * audio.SR)] = True
                if exact[int(a * audio.SR):int(b * audio.SR)].mean() < 0.5:
                    report["refs"][r]["segments"].append({"mix_start": a, "mix_end": b, "spectral": True})

    # 4. music no reference explains
    covered = uniform_filter1d((exact | spec_active).astype(np.float32), 2 * audio.SR) > 1e-6
    unknown = refmatch.music_regions(music_nn) & ~covered
    report["unknown"] = refmatch.regions(unknown, 1.5)

    c = {"key": key, "refs": refs, "rest": rest, "exact": exact, "music_nn": music_nn, "matches": matches,
         "spec_active": spec_active, "unknown": unknown, "report": report}
    job["_cache"] = c
    return c


def _weights(T, default, regions):
    """Per-sample weight of every strength level: regions override the default, with short fades."""
    w = {L: np.zeros(T, np.float32) for L in LEVELS}
    w[default if default in LEVELS else "medium"][:] = 1
    for r in regions or []:
        L = r.get("level")
        if L not in LEVELS:
            continue
        m = np.zeros(T, bool)
        m[max(0, int(r["start"] * audio.SR)):max(0, int(r["end"] * audio.SR))] = True
        if not m.any():
            continue
        m = _ramp(m, 0.03)
        for k in w:
            w[k] *= (1 - m)
        w[L] += m
    return w


def _render(c, nn_fallback, default, regions, prog):
    from . import specmatch
    T = c["rest"].shape[-1]
    keep_exact = 1 - _ramp(c["exact"])
    fb_mask = _ramp(c["unknown"]) if nn_fallback else None
    out = c["rest"].copy()
    w = _weights(T, default, regions)
    used = [L for L in LEVELS if w[L].max() > 1e-4]
    for i, L in enumerate(used):
        prog(0.8 + 0.15 * i / len(used), "@rendering")
        margin, fb = LEVELS[L]
        remove = np.zeros_like(out)
        if c["matches"]:
            if margin is None:
                remove += c["music_nn"] * _ramp(c["spec_active"])[None] * keep_exact[None]
                remove += c["music_nn"] * _ramp(c["exact"])[None]   # leftovers of exact copies too
            else:
                with _gpu:
                    song, _ = specmatch.song_from_music(c["music_nn"], c["refs"], c["matches"], margin)
                remove += song * keep_exact[None]
        if fb_mask is not None:
            remove += fb * c["music_nn"] * fb_mask[None]
        out -= remove * w[L][None]
    return out


def run_job(jid: str, mode: str, ref_ids: list, nn_fallback: bool = True, strength: str = "medium",
            regions: list | None = None):
    from . import models

    job = JOBS[jid]
    d: Path = job["dir"]

    def prog(p, msg=None):
        job["progress"] = round(float(max(0.0, min(1.0, p))), 3)
        if msg:
            job["message"] = msg

    job.update(status="running", progress=0.0, message="@reading", report=None)
    try:
        t_start = time.time()
        mix = audio.load(d / "input.wav")

        if mode in ("stems4", "stems6", "vocals"):
            job["outputs"] = []
            with _gpu:
                stems = models.demucs_separate(mix, mode, prog)
        else:
            c = _prepare(job, mix, _load_refs(ref_ids), prog)
            rest = _render(c, nn_fallback, strength, regions, prog)
            job["report"] = c["report"] if (c["refs"] or c["report"]["unknown"]) else None
            stems = {"nomusic": rest, "music": mix - rest}

        prog(0.96, "@saving")
        outputs = []
        for key in sorted(stems, key=lambda k: STEM_ORDER.index(k) if k in STEM_ORDER else 99):
            audio.save(d / key, stems[key])
            _save_peaks(d / f"peaks_{key}.json", stems[key])
            outputs.append({"key": key})
        job.update(status="done", progress=1.0, outputs=outputs, version=job.get("version", 0) + 1,
                   message=f"@done:{time.time() - t_start:.0f}")
    except Exception as e:
        traceback.print_exc()
        job.update(status="error", message="!" + str(e)[-300:])


# ------------------------------------------------------------------ matching one reference

def _match(job, mix, rid, music_nn=None):
    """Exact match first; if the copy differs, match by spectrogram on the neural music stem."""
    from . import refmatch, specmatch
    ref = audio.load(REFS[rid]["wav"])
    refs = {rid: ref}
    with _gpu:
        found = refmatch.detect(mix, refs)
    spans = refmatch.assign(mix, refs, found) if found[rid] else []
    segs = refmatch.spans_to_segments(spans).get(rid, [])
    exact_sec = sum(s["mix_end"] - s["mix_start"] for s in segs)
    if music_nn is None:
        music_nn = _nn_music(job, mix)
    with _gpu:
        feat = specmatch.features(music_nn)
        sm = specmatch.match(feat, ref, feat.shape[1])
    spec_sec = specmatch.coverage(sm)
    score = 2 * exact_sec + sum(s["n"] * max(0.0, s["score"] - specmatch.NULL_SCORE) for s in sm) * 10
    segs = segs + [{"mix_start": s["a"] / specmatch.FPS, "mix_end": s["b"] / specmatch.FPS, "spectral": True}
                   for s in sm]
    ok = exact_sec >= 3 or (spec_sec >= 4 and sum(s["n"] for s in sm) >= 6)
    return {"status": "found" if ok else "not_found", "segments": segs if ok else [],
            "exact": exact_sec >= 3, "score": score}


def run_match(jid: str, rid: str):
    """Check right after a reference is added: does it play in this recording, and where?"""
    job = JOBS.get(jid)
    ref = REFS.get(rid)
    if not job or not ref or ref.get("status") != "ready":
        return
    job["match"][rid] = {"status": "checking", "segments": []}
    try:
        job["match"][rid] = _match(job, audio.load(job["dir"] / "input.wav"), rid)
    except Exception as e:
        traceback.print_exc()
        job["match"][rid] = {"status": "error", "segments": [], "error": str(e)[-200:]}


# ------------------------------------------------------------------ automatic analysis

def run_analysis(jid: str):
    """Recognise songs with Shazam, fetch full copies and keep the one that lines up best."""
    from . import recognize

    job = JOBS[jid]
    an = {"status": "running", "progress": 0.0, "message": "@listening", "tracks": []}
    job["analysis"] = an
    try:
        mix = audio.load(job["dir"] / "input.wav")
        tracks = recognize.recognize(mix, lambda p: an.update(progress=0.3 * p))
        if not tracks:
            an.update(status="done", progress=1.0, message="@no_songs")
            return
        an["tracks"] = [{"key": t["key"], "title": t["title"], "artist": t["artist"], "cover": t["cover"],
                         "status": "searching", "ref": None} for t in tracks]
        an["message"] = "@separate"
        music_nn = _nn_music(job, mix, lambda p, *_: an.update(progress=0.3 + 0.3 * p))
        for i, (t, row) in enumerate(zip(tracks, an["tracks"])):
            an["progress"] = 0.6 + 0.4 * i / len(tracks)
            best, tried = None, 0
            for c in recognize.candidates(t["title"], t["artist"]):
                if tried >= 3:
                    break
                rid = f"{c['src']}_" + "".join(ch for ch in c["id"] if ch.isalnum() or ch in "-_")
                row["status"] = "downloading"
                if REFS.get(rid, {}).get("status") != "ready":
                    REFS[rid] = {"id": rid, "title": f"{t['artist']} — {t['title']}", "status": "downloading", "progress": 0.0}
                    if (REFS_DIR / f"{rid}.wav").exists():
                        REFS[rid].update(status="ready", wav=REFS_DIR / f"{rid}.wav", progress=1.0)
                    else:
                        fetch_ref(rid, c["url"])
                if REFS[rid].get("status") != "ready":
                    continue
                tried += 1
                REFS[rid].update(title=f"{t['artist']} — {t['title']}", cover=t["cover"], auto=True)
                row["status"] = "checking"
                m = _match(job, mix, rid, music_nn)
                if m["status"] == "found" and (best is None or m["score"] > best[1]["score"]):
                    best = (rid, m)
                if m.get("exact"):
                    break  # the very same copy — can't do better
            if best:
                job["match"][best[0]] = best[1]
                row.update(status="found", ref=best[0])
            else:
                row["status"] = "no_source"
        an.update(status="done", progress=1.0, message="")
    except Exception as e:
        traceback.print_exc()
        an.update(status="error", message="!" + str(e)[-200:])


# ------------------------------------------------------------------ references

def fetch_ref(rid: str, url: str):
    import yt_dlp

    ref = REFS[rid]
    out = REFS_DIR / rid
    try:
        def hook(d):
            if d.get("status") == "downloading" and d.get("total_bytes"):
                ref["progress"] = d["downloaded_bytes"] / d["total_bytes"]

        opts = {"format": "bestaudio/best", "outtmpl": str(out) + "_src.%(ext)s", "quiet": True,
                "no_warnings": True, "noplaylist": True, "noprogress": True, "progress_hooks": [hook],
                "logger": _Quiet()}
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            src = Path(y.prepare_filename(info))
        audio.to_wav(src, out.with_suffix(".wav"))
        src.unlink(missing_ok=True)
        ref.update(status="ready", wav=out.with_suffix(".wav"), progress=1.0,
                   duration=audio.duration(out.with_suffix(".wav")))
    except Exception as e:
        ref.update(status="error", error=short_err(e))


class _Quiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def short_err(e):
    s = str(e)
    if "not a bot" in s or "Sign in" in s:
        return "@yt_bot"
    return s.replace("ERROR: ", "")[:200]
