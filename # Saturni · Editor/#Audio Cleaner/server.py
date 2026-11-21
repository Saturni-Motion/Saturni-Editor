"""Saturni · Audio Cleaner backend (FastAPI). The desktop window (app.py) shows web/index.html served from here."""
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from engine import audio, jobs
from engine.paths import REFS_DIR

HERE = Path(__file__).parent
DEBUG_DIR = HERE.parents[1] / "@ Saturni · Debug"     # Hub/@ Saturni · Debug
app = FastAPI()


@app.get("/mod/debug/{name}")
def debug_file(name: str):
    p = DEBUG_DIR / Path(name).name
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/api/info")
def info():
    import torch
    return {"gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}


# ------------------------------------------------------------------ jobs

def _new_job_from(src: Path, name: str, remove_src: bool):
    job = jobs.new_job(name)
    try:
        audio.to_wav(src, job["dir"] / "input.wav")
    except Exception:
        raise HTTPException(400, "@bad_file")
    finally:
        if remove_src:
            src.unlink(missing_ok=True)
    mix = audio.load(job["dir"] / "input.wav")
    job["duration"] = mix.shape[-1] / audio.SR
    job["peaks"] = audio.peaks(mix, 1000)
    return jobs.public(job)


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    tmp = jobs.JOBS_DIR / f"up_{uuid.uuid4().hex[:8]}{Path(file.filename).suffix}"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return _new_job_from(tmp, file.filename, True)


class PathReq(BaseModel):
    path: str


@app.post("/api/open")
def open_path(req: PathReq):
    """Desktop mode: the file is read straight from disk, no copying through HTTP."""
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(404, "@no_file")
    return _new_job_from(p, p.name, False)


class ProcessReq(BaseModel):
    mode: str
    refs: list[str] = []
    nn_fallback: bool = True
    strength: str = "medium"
    regions: list[dict] = []


@app.post("/api/job/{jid}/process")
def process(jid: str, req: ProcessReq):
    job = jobs.JOBS.get(jid) or _404()
    if req.mode not in ("stems4", "stems6", "vocals", "speech"):
        raise HTTPException(400, "bad mode")
    job.update(status="queued", progress=0, message="@queued", mode=req.mode)
    jobs.submit(jobs.run_job, jid, req.mode, req.refs, req.nn_fallback, req.strength, req.regions)
    return {"ok": True}


@app.post("/api/job/{jid}/analyze")
def analyze(jid: str):
    job = jobs.JOBS.get(jid) or _404()
    if not job.get("analysis") or job["analysis"]["status"] == "error":
        job["analysis"] = {"status": "running", "progress": 0, "message": "@listening", "tracks": []}
        threading.Thread(target=jobs.run_analysis, args=(jid,), daemon=True).start()
    return {"ok": True}


@app.get("/api/job/{jid}")
def job_state(jid: str):
    return jobs.public(jobs.JOBS.get(jid) or _404())


@app.get("/api/job/{jid}/input.mp3")
def job_input(jid: str):
    job = jobs.JOBS.get(jid) or _404()
    mp3 = job["dir"] / "input.mp3"
    if not mp3.exists():
        audio._run(["ffmpeg", "-y", "-v", "error", "-i", str(job["dir"] / "input.wav"),
                    "-c:a", "libmp3lame", "-b:a", "160k", str(mp3)])
    return FileResponse(mp3, media_type="audio/mpeg")


def stem_path(jid: str, key: str, ext: str) -> Path:
    job = jobs.JOBS.get(jid) or _404()
    if ext not in ("wav", "mp3") or not key.isalnum():
        _404()
    p = job["dir"] / f"{key}.{ext}"
    if not p.exists():
        _404()
    return p


def stem_filename(jid: str, key: str, ext: str, lang: str = "en") -> str:
    job = jobs.JOBS[jid]
    labels = jobs.STEM_LABELS.get(lang, jobs.STEM_LABELS["en"])
    return f"{Path(job['name']).stem} — {labels.get(key, key)}.{ext}"


@app.get("/api/job/{jid}/file/{key}.{ext}")
def job_file(jid: str, key: str, ext: str, dl: int = 0, lang: str = "en"):
    p = stem_path(jid, key, ext)
    return FileResponse(p, media_type="audio/wav" if ext == "wav" else "audio/mpeg",
                        filename=stem_filename(jid, key, ext, lang) if dl else None)


@app.get("/api/job/{jid}/peaks/{key}")
def job_peaks(jid: str, key: str):
    job = jobs.JOBS.get(jid) or _404()
    if not key.isalnum():
        _404()
    p = job["dir"] / f"peaks_{key}.json"
    if not p.exists():
        _404()
    return FileResponse(p, media_type="application/json")


@app.post("/api/job/{jid}/match/{rid}")
def match(jid: str, rid: str):
    if jid not in jobs.JOBS or rid not in jobs.REFS:
        _404()
    jobs.JOBS[jid]["match"][rid] = {"status": "checking", "segments": []}
    threading.Thread(target=jobs.run_match, args=(jid, rid), daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ references

def _search_one(prefix, q, src):
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True,
                               "logger": jobs._Quiet()}) as y:
            res = y.extract_info(f"{prefix}:{q}", download=False)
    except Exception:
        return []
    out = []
    for e in res.get("entries") or []:
        if not e or not e.get("id"):
            continue
        if src == "yt":
            url, thumb = f"https://www.youtube.com/watch?v={e['id']}", f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg"
        else:
            url = e.get("url")
            th = [t for t in e.get("thumbnails") or [] if (t.get("width") or 0) >= 100]
            thumb = th[0]["url"] if th else None
        out.append({"src": src, "id": str(e["id"]), "url": url, "title": e.get("title"),
                    "channel": e.get("channel") or e.get("uploader"), "duration": e.get("duration"), "thumb": thumb})
    return out


@app.get("/api/search")
def search(q: str):
    from concurrent.futures import ThreadPoolExecutor
    q = q.strip()
    if not q:
        return []
    with ThreadPoolExecutor(2) as ex:
        a, b = ex.submit(_search_one, "ytsearch5", q, "yt"), ex.submit(_search_one, "scsearch5", q, "sc")
        a, b = a.result(), b.result()
    out = []
    for i in range(max(len(a), len(b))):
        out += b[i:i + 1] + a[i:i + 1]
    return out


@app.get("/api/preview")
def preview(url: str):
    """Stream a search result as MP3 through ffmpeg, to hear it before adding."""
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "format": "bestaudio/best",
                               "logger": jobs._Quiet()}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(502, jobs.short_err(e))
    headers = "".join(f"{k}: {v}\r\n" for k, v in (info.get("http_headers") or {}).items())
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-headers", headers, "-i", info["url"], "-t", "600",
                          "-vn", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=0x08000000)

    def gen():
        try:
            while chunk := p.stdout.read(32768):
                yield chunk
        finally:
            p.kill()

    return StreamingResponse(gen(), media_type="audio/mpeg")


class AddRef(BaseModel):
    src: str
    id: str
    url: str
    title: str
    job: str | None = None


def _after_ready(rid, jid):
    if jid and jid in jobs.JOBS and jobs.REFS[rid].get("status") == "ready":
        jobs.run_match(jid, rid)


@app.post("/api/refs")
def add_ref(req: AddRef):
    rid = f"{req.src}_" + "".join(ch for ch in req.id if ch.isalnum() or ch in "-_")
    wav = REFS_DIR / f"{rid}.wav"
    ref = jobs.REFS.get(rid)
    if (ref and ref["status"] == "ready") or wav.exists():
        jobs.REFS[rid] = ref = {"id": rid, "title": req.title, "status": "ready", "wav": wav, "progress": 1.0}
        if req.job:
            jobs.JOBS[req.job]["match"][rid] = {"status": "checking", "segments": []}
            threading.Thread(target=_after_ready, args=(rid, req.job), daemon=True).start()
        return _pub_ref(ref)
    ref = {"id": rid, "title": req.title, "status": "downloading", "progress": 0.0}
    jobs.REFS[rid] = ref

    def go():
        jobs.fetch_ref(rid, req.url)
        _after_ready(rid, req.job)

    threading.Thread(target=go, daemon=True).start()
    return _pub_ref(ref)


def _ref_from_file(src: Path, title: str, job: str | None, remove_src: bool):
    rid = "f_" + uuid.uuid4().hex[:10]
    wav = REFS_DIR / f"{rid}.wav"
    try:
        audio.to_wav(src, wav)
    except Exception:
        raise HTTPException(400, "@bad_file")
    finally:
        if remove_src:
            src.unlink(missing_ok=True)
    ref = {"id": rid, "title": title, "status": "ready", "wav": wav, "progress": 1.0}
    jobs.REFS[rid] = ref
    if job and job in jobs.JOBS:
        jobs.JOBS[job]["match"][rid] = {"status": "checking", "segments": []}
        threading.Thread(target=_after_ready, args=(rid, job), daemon=True).start()
    return _pub_ref(ref)


@app.post("/api/refs/upload")
def upload_ref(file: UploadFile = File(...), job: str | None = None):
    tmp = REFS_DIR / f"up_{uuid.uuid4().hex[:8]}{Path(file.filename).suffix}"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return _ref_from_file(tmp, Path(file.filename).stem, job, True)


class RefPathReq(BaseModel):
    path: str
    job: str | None = None


@app.post("/api/refs/open")
def open_ref(req: RefPathReq):
    p = Path(req.path)
    if not p.is_file():
        raise HTTPException(404, "@no_file")
    return _ref_from_file(p, p.stem, req.job, False)


@app.get("/api/refs/{rid}")
def ref_state(rid: str):
    return _pub_ref(jobs.REFS.get(rid) or _404())


@app.get("/api/refs/{rid}/audio")
def ref_audio(rid: str):
    ref = jobs.REFS.get(rid) or _404()
    if ref.get("status") != "ready":
        _404()
    mp3 = Path(ref["wav"]).with_suffix(".mp3")
    if not mp3.exists():
        audio._run(["ffmpeg", "-y", "-v", "error", "-i", str(ref["wav"]), "-c:a", "libmp3lame",
                    "-b:a", "160k", str(mp3)])
    return FileResponse(mp3, media_type="audio/mpeg")


def _pub_ref(ref):
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in ref.items() if k != "wav"}


def _404():
    raise HTTPException(404, "not found")
