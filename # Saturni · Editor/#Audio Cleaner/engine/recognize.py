"""Automatic song recognition (Shazam) and finding a full copy of each song to use as reference."""
import asyncio
import difflib
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
CLIP_S = 10
STEP_S = 10


def _clips(mix: np.ndarray):
    T = mix.shape[-1]
    mono = mix.mean(0)
    for t in range(0, max(1, int(T / SR) - 3), STEP_S):
        seg = mono[t * SR:(t + CLIP_S) * SR]
        if len(seg) > 3 * SR and np.sqrt((seg ** 2).mean()) > 1e-3:
            yield t, seg


async def _recognize_all(mix, progress):
    from shazamio import Shazam
    sh = Shazam()
    clips = list(_clips(mix))
    sem = asyncio.Semaphore(3)
    done = 0
    tmp = Path(tempfile.mkdtemp(prefix="stemstudio_"))

    async def one(t, seg):
        nonlocal done
        p = tmp / f"c{t}.wav"
        sf.write(p, seg[::1], SR, subtype="PCM_16")
        async with sem:
            res = None
            for attempt in range(3):
                try:
                    res = await sh.recognize(str(p))
                    break
                except Exception:
                    await asyncio.sleep(1.5 * (attempt + 1))
        p.unlink(missing_ok=True)
        done += 1
        progress(done / max(1, len(clips)))
        tr = (res or {}).get("track")
        if not tr:
            return None
        return {"t": t, "key": tr.get("key"), "title": tr.get("title"), "artist": tr.get("subtitle"),
                "cover": (tr.get("images") or {}).get("coverart")}

    hits = await asyncio.gather(*(one(t, s) for t, s in clips))
    return [h for h in hits if h and h["key"]]


def recognize(mix: np.ndarray, progress=lambda p: None):
    """→ [{key, title, artist, cover, times:[t…]}] ordered by first appearance."""
    hits = asyncio.run(_recognize_all(mix, progress))
    tracks = {}
    for h in hits:
        tr = tracks.setdefault(h["key"], {k: h[k] for k in ("key", "title", "artist", "cover")} | {"times": []})
        tr["times"].append(h["t"])
    return sorted(tracks.values(), key=lambda t: t["times"][0])


# ------------------------------------------------------------------ finding a full copy

def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|official|video|audio|lyrics?|music|ncs|release|feat\.?|ft\.?|hd|copyright free", " ", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def candidates(title, artist, n=6):
    """Search SoundCloud and YouTube; best-looking matches first (SoundCloud first: downloads more reliably)."""
    import yt_dlp
    q = f"{artist} {title}"
    found = []
    for prefix, src in (("scsearch5", "sc"), ("ytsearch4", "yt")):
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as y:
                res = y.extract_info(f"{prefix}:{q}", download=False)
        except Exception:
            continue
        for e in res.get("entries") or []:
            if not e or not e.get("id"):
                continue
            url = f"https://www.youtube.com/watch?v={e['id']}" if src == "yt" else e.get("url")
            name = _norm(e.get("title"))
            score = difflib.SequenceMatcher(None, _norm(title), name).ratio()
            if _norm(title) and _norm(title) in name:
                score += 0.5
            if any(w in (e.get("title") or "").lower() for w in ("remix", "cover", "slowed", "sped up", "nightcore", "8d", "live")) \
                    and not any(w in title.lower() for w in ("remix", "live")):
                score -= 0.6
            found.append({"src": src, "id": str(e["id"]), "url": url, "title": e.get("title"),
                          "score": score + (0.05 if src == "sc" else 0)})
    found.sort(key=lambda c: -c["score"])
    return found[:n]
