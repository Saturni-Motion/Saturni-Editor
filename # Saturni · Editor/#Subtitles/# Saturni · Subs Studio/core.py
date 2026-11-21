# -*- coding: utf-8 -*-
"""
core.py — Subs Studio без окна: SRT (через @tools/@SRT Markers.py, чтобы маркеры ^N #N … в
номерах блоков не терялись), архив сессий, версии, звуковая волна, соседние файлы папки.

Сессия = папка sessions/<имя srt> · <хэш пути>/ :
    meta.json        путь к оригиналу, видео, история версий, id сессии Claude, подсветка
    original.srt     файл как он был при первом открытии в приложении (не трогается никогда)
    versions/        NNN.srt — состояние после каждого применения (Apply / Ctrl+S / Undo / Revert)
    pending.json     неприменённое: ручные правки + голосовые заметки, каретки, отметки на волне
    audio/           записи голосовых правок (wav) — по одной на нажатие микрофона
    applies/NNNN/    один прогон Claude: request.json, result.json, report.md, stream.jsonl, before/after.srt
    chat.jsonl       лента чата сессии (что показывает панель Claude)
"""

import os
import re
import sys
import json
import time
import base64
import hashlib
import subprocess
import importlib.util as _ilu

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # D:\\@Hub
ROOT = os.path.join(HUB, "# Saturni · Editor", "#Series")
TOOLS = os.path.join(ROOT, "@tools")
MODULES = HUB                                        # общие модули: @ Saturni · Voice, @ Saturni · Debug
for _m in ("@ Saturni · Voice", "@ Saturni · Debug"):
    if os.path.join(MODULES, _m) not in sys.path:
        sys.path.insert(0, os.path.join(MODULES, _m))
DATA_DIR = os.path.join(HERE, "data")
SESS_DIR = os.path.join(HERE, "sessions")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
for _d in (DATA_DIR, SESS_DIR, CACHE_DIR):
    os.makedirs(_d, exist_ok=True)

NOWIN = 0x08000000 if os.name == "nt" else 0        # без мигающих консолей при pythonw
VID_EXT = (".mp4", ".mov", ".mkv", ".m4v", ".webm")
PEAK_RATE = 200                                      # точек волны в секунду (5 мс)


def _tool(name, file):
    """Модуль из @tools по пути (в именах пробелы/@ — обычный import не видит)."""
    if name not in sys.modules:
        spec = _ilu.spec_from_file_location(name, os.path.join(TOOLS, file))
        sys.modules[name] = mod = _ilu.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


sm = _tool("srt_markers", "@SRT Markers.py")


def load_json(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ═══════════════════════════ SRT ═══════════════════════════
def read_srt(path):
    """-> (cues, newline). cue = {id, mk, start, end, text}; время в мс (int)."""
    raw = open(path, "rb").read().decode("utf-8-sig", errors="replace")
    newline = "\r\n" if "\r\n" in raw else "\n"
    cues = []
    for i, b in enumerate(sm.parse_srt(raw), 1):
        cues.append({"id": f"c{i}", "mk": b["mk"] or "", "start": int(b["start"]), "end": int(b["end"]),
                     "text": "\n".join(b["lines"])})
    return cues, newline


def srt_text(cues, newline="\r\n"):
    return sm.write_srt([{"mk": c.get("mk") or "", "start": c["start"], "end": c["end"], "text": c["text"]}
                         for c in cues], newline)


def write_srt(path, cues, newline="\r\n"):
    data = srt_text(cues, newline)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    os.replace(tmp, path)


def file_hash(path):
    try:
        return hashlib.sha1(open(path, "rb").read()).hexdigest()[:16]
    except Exception:
        return None


def validate_cues(cues):
    """Проверка результата Claude перед записью. -> (ok, msg, normalized)."""
    out = []
    try:
        for c in cues:
            s, e = int(round(float(c["start"]))), int(round(float(c["end"])))
            t = str(c.get("text", "")).replace("\r\n", "\n").strip()
            if e <= s:
                return False, f"cue {c.get('id')}: end <= start", None
            out.append({"id": str(c.get("id") or ""), "mk": c.get("mk") or "", "start": s, "end": e, "text": t})
    except Exception as ex:
        return False, f"bad cue format: {ex}", None
    out.sort(key=lambda c: c["start"])
    seen = set()
    for i, c in enumerate(out):
        if not c["id"] or c["id"] in seen:
            c["id"] = f"n{i + 1}_{int(time.time() * 1000) % 100000}"
        seen.add(c["id"])
    return True, "", out


# ═══════════════════════════ видео рядом с srt ═══════════════════════════
def find_video(srt):
    base = os.path.splitext(srt)[0]
    cands = [base]
    if base.endswith("` 1h"):
        cands.append(base[:-2] + "1v")
    if base.endswith("` 1v"):
        cands.append(base[:-2] + "1h")
    for b in cands:
        for e in VID_EXT:
            if os.path.exists(b + e):
                return b + e
    return None


def srt_for(path):
    """Путь, брошенный в окно: .srt как есть, видео -> .srt рядом с тем же именем."""
    base, ext = os.path.splitext(os.path.abspath(path))
    if ext.lower() == ".srt":
        return base + ext
    if ext.lower() in VID_EXT:
        return base + ".srt"
    return None


def _natkey(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def folder_srts(srt):
    d = os.path.dirname(srt)
    try:
        names = sorted((n for n in os.listdir(d) if n.lower().endswith(".srt")), key=_natkey)
    except Exception:
        return []
    return [os.path.join(d, n) for n in names]


def neighbor(srt, delta):
    lst = folder_srts(srt)
    key = os.path.normcase(os.path.abspath(srt))
    idx = next((i for i, p in enumerate(lst) if os.path.normcase(p) == key), None)
    if not lst:
        return None
    if idx is None:                           # открытый файл унесли из папки: список перечитан — первый (назад — последний)
        return lst[0] if delta > 0 else lst[-1]
    j = idx + delta
    return lst[j] if 0 <= j < len(lst) else None


# ═══════════════════════════ звуковая волна ═══════════════════════════
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                        "-of", "json", path], capture_output=True, creationflags=NOWIN)
    try:
        d = json.loads(r.stdout.decode("utf-8", "ignore"))
        v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
        num, _, den = str(v.get("r_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0
        return {"dur": float(d["format"].get("duration") or 0), "codec": v.get("codec_name", ""),
                "w": v.get("width"), "h": v.get("height"), "fps": round(fps, 3) if 1 < fps < 241 else None}
    except Exception:
        return None


def peaks(video):
    """Огибающая волны: PEAK_RATE точек/с, максимум |амплитуды| 0..255 -> base64. Кэш по пути+mtime."""
    st = os.stat(video)
    key = hashlib.sha1(f"{os.path.normcase(video)}|{st.st_mtime}|{st.st_size}|{PEAK_RATE}|v2".encode()).hexdigest()[:20]
    cp = os.path.join(CACHE_DIR, f"peaks_{key}.b64")
    if os.path.exists(cp):
        return open(cp, "r").read()
    import numpy as np
    sr = 8000
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, creationflags=NOWIN)
    a = np.abs(np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)) / 32768.0
    hop = sr // PEAK_RATE
    n = len(a) // hop
    if n == 0:
        return ""
    m = a[:n * hop].reshape(n, hop).max(axis=1)
    ref = float(np.percentile(m, 99.9)) or 1.0                 # нормировка по почти-максимуму: редкий пик не сжимает всё
    m = np.clip(m / ref, 0, 1) * 0.92
    b64 = base64.b64encode((m * 255).astype(np.uint8).tobytes()).decode("ascii")
    open(cp, "w").write(b64)
    return b64


# ═══════════════════════════ сессии ═══════════════════════════
def session_dir(srt):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(srt)).encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r'[<>:"/\\|?*]', "_", os.path.splitext(os.path.basename(srt))[0])[:60]
    return os.path.join(SESS_DIR, f"{stem} · {key}")


class Session:
    def __init__(self, srt):
        self.srt = os.path.abspath(srt)
        self.dir = session_dir(self.srt)
        os.makedirs(os.path.join(self.dir, "versions"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "audio"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "applies"), exist_ok=True)
        self.meta_path = os.path.join(self.dir, "meta.json")
        self.meta = load_json(self.meta_path, None) or {
            "srt": self.srt, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "versions": [],
            "claude_session": None, "highlight": []}
        self.meta["srt"] = self.srt
        orig = os.path.join(self.dir, "original.srt")
        if not os.path.exists(orig) and os.path.exists(self.srt):
            import shutil
            shutil.copy2(self.srt, orig)
        self.save_meta()

    def p(self, *a):
        return os.path.join(self.dir, *a)

    def save_meta(self):
        save_json(self.meta_path, self.meta)

    # ── неприменённое ──
    def load_pending(self, cur_hash):
        d = load_json(self.p("pending.json"), None)
        if not d:
            return None
        if d.get("base_hash") and cur_hash and d["base_hash"] != cur_hash:
            d["stale"] = True                 # файл поменяли снаружи — заметки покажем, правки нет
        return d

    def save_pending(self, data):
        if data is None:
            try:
                os.remove(self.p("pending.json"))
            except FileNotFoundError:
                pass
            return
        save_json(self.p("pending.json"), data)

    # ── версии ──
    def add_version(self, cues, newline, why):
        n = len(self.meta["versions"]) + 1
        name = f"{n:03d}.srt"
        with open(self.p("versions", name), "w", encoding="utf-8", newline="") as f:
            f.write(srt_text(cues, newline))
        self.meta["versions"].append({"n": n, "file": name, "why": why, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.save_meta()
        return n

    def version_cues(self, idx_from_end):
        """1 = последняя версия, 2 = предпоследняя…; None — нет такой."""
        v = self.meta["versions"]
        if len(v) < idx_from_end:
            return None
        return read_srt(self.p("versions", v[-idx_from_end]["file"]))[0]

    def new_apply_dir(self):
        ex = [d for d in os.listdir(self.p("applies")) if d.isdigit()]
        n = max([int(d) for d in ex] or [0]) + 1
        d = self.p("applies", f"{n:04d}")
        os.makedirs(d, exist_ok=True)
        return d

    def chat_log(self, item):
        item = dict(item, at=time.strftime("%H:%M:%S"))
        with open(self.p("chat.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def chat_history(self, limit=400):
        try:
            lines = open(self.p("chat.jsonl"), encoding="utf-8").read().splitlines()[-limit:]
            return [json.loads(x) for x in lines if x.strip()]
        except Exception:
            return []


def highlight_sig(c):
    return f"{c['start']}|{c['text']}"


# ═══════════════════════════ корзина и старые сессии ═══════════════════════════
def recycle(path):
    """В Корзину (SHFileOperation с FOF_ALLOWUNDO), не насовсем."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    op = SHFILEOPSTRUCTW(None, 3, os.path.abspath(path) + "\0\0", None, 0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0      # FO_DELETE; ALLOWUNDO|NOCONFIRMATION|SILENT|NOERRORUI


def purge_old_sessions(days=30):
    """Данные файлов, которые не открывали `days` дней (заметки, подсветка, версии), — в Корзину."""
    limit = time.time() - days * 86400
    for name in os.listdir(SESS_DIR):
        d = os.path.join(SESS_DIR, name)
        if not os.path.isdir(d):
            continue
        last = max((os.path.getmtime(os.path.join(d, f)) for f in ("meta.json", "pending.json", "chat.jsonl")
                    if os.path.exists(os.path.join(d, f))), default=os.path.getmtime(d))
        if last < limit:
            try:
                recycle(d)
            except Exception:
                pass


def sessions_with_notes():
    """Файлы с неприменённым: голосовые правки (n) или несохранённые ручные (dirty) — [{srt, name, n, dirty}]."""
    out = []
    for name in os.listdir(SESS_DIR):
        d = os.path.join(SESS_DIR, name)
        pend, meta = load_json(os.path.join(d, "pending.json"), None), load_json(os.path.join(d, "meta.json"), None)
        if not pend or not meta or not os.path.exists(meta.get("srt", "")):
            continue
        n = sum(1 for c in pend.get("cues") or [] if (c.get("note") or "").strip())
        dirty = bool(pend.get("dirty"))
        if (n or dirty) and not (pend.get("base_hash") and pend["base_hash"] != file_hash(meta["srt"])):
            out.append({"srt": meta["srt"], "name": os.path.basename(meta["srt"]), "n": n, "dirty": dirty})
    return out
