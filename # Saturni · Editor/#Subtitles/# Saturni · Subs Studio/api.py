# -*- coding: utf-8 -*-
"""api.py — мост JS <-> Python для Subs Studio: файлы, сессии, запись голоса, Claude, окно."""

import os
import json
import time
import shutil
import ctypes
import threading
from ctypes import wintypes

import core
import server
import claude_bridge
from recorder import Recorder                         # @Hub/Saturni · Voice
from saturni_debug import DebugMixin, STATIC_DIR      # @Hub/Saturni · Debug

server.MODULES["debug"] = STATIC_DIR
PREFS_PATH = os.path.join(core.DATA_DIR, "prefs.json")
DEFAULT_PREFS = {"theme": "dark", "last_file": None, "placement": None, "model": "opus", "effort": None,
                 "claude_exe": None, "list_w": None, "video_h": None, "tl_h": None, "zoom": 120,
                 "colors": {}, "settings": {}}


class _MI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class _WP(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", wintypes.RECT)]


_u32 = ctypes.windll.user32
_MOVE_DIR = os.path.join(os.path.dirname(core.HERE), "# Saturni · Subs Move")


def _move_render():
    """render.py из Subs Move (рендер слоя титра 1:1 с 2Stage) — по пути: в имени папки пробелы и «·»."""
    import sys
    import importlib.util
    if "subs_move_render" not in sys.modules:
        spec = importlib.util.spec_from_file_location("subs_move_render", os.path.join(_MOVE_DIR, "render.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["subs_move_render"] = mod
    return sys.modules["subs_move_render"]
_u32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
_u32.MonitorFromRect.restype = wintypes.HANDLE
_u32.MonitorFromWindow.restype = wintypes.HANDLE
_u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


def _monitor_info(h):
    mi = _MI()
    mi.cbSize = ctypes.sizeof(_MI)
    return mi if h and _u32.GetMonitorInfoW(h, ctypes.byref(mi)) else None


class Api(DebugMixin):
    def __init__(self, port):
        self._port = port
        self._debug_dir = os.path.join(core.HERE, "⿻", "@debug")
        self._window = None
        self._events, self._ev_lock = [], threading.Lock()
        self._dev = None
        self._sess = None            # core.Session открытого файла
        self._file = None            # {srt, video, newline}
        self._run = None             # активный прогон Claude
        self._run_ctx = None
        self._queue = []             # «применить во всех файлах»: файлы в очереди
        self._force_close = False
        prefs = dict(DEFAULT_PREFS)
        prefs.update(core.load_json(PREFS_PATH, {}) or {})
        self._prefs = prefs
        self._rec = Recorder(self._emit)
        threading.Thread(target=self._emit_loop, daemon=True).start()
        threading.Thread(target=core.purge_old_sessions, daemon=True).start()   # данные файлов старше 30 дней — в Корзину

    # ── инфраструктура ──
    def _attach(self, window):
        self._window = window

    def _emit(self, kind, data=None):
        with self._ev_lock:
            self._events.append({"type": kind, "data": data})

    def _emit_loop(self):
        while True:
            time.sleep(0.04)
            if not self._window and self._dev is None:
                continue
            with self._ev_lock:
                evs, self._events = self._events, []
            if not evs:
                continue
            if self._dev is not None:
                self._dev.extend(evs)
                continue
            try:
                self._window.evaluate_js(f"window.__emit && window.__emit({json.dumps(evs, ensure_ascii=False)})")
            except Exception:
                pass

    def _save_prefs(self):
        try:
            core.save_json(PREFS_PATH, self._prefs)
        except Exception:
            pass

    # ── старт, настройки ──
    def init(self):
        exe = claude_bridge.find_claude(self._prefs.get("claude_exe"))
        return {"prefs": self._prefs, "start_file": self._start_file(), "claude": exe}

    def _start_file(self):
        import sys
        for a in sys.argv[1:]:
            if not a.startswith("--") and os.path.exists(a):
                return a
        lf = self._prefs.get("last_file")
        return lf if lf and os.path.exists(lf) else None

    def prefs_save(self, patch):
        self._prefs.update(patch or {})
        self._save_prefs()
        return True

    # ── файлы ──
    def open_dialog(self):
        import webview
        start = os.path.dirname(self._file["srt"]) if self._file else os.path.dirname(self._prefs.get("last_file") or "")
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, directory=start or "", allow_multiple=False,
                                            file_types=("Subtitles or video (*.srt;*.mp4;*.mov;*.mkv;*.m4v;*.webm)",
                                                        "All files (*.*)"))
        if not r:
            return None
        return self.load(r[0] if isinstance(r, (list, tuple)) else r)

    def load(self, path):
        srt = core.srt_for(path)
        if not srt:
            return {"error": f"Unsupported file: {os.path.basename(path)}"}
        if not os.path.exists(srt):
            return {"error": f"No subtitles next to the video: {os.path.basename(srt)}"}
        try:
            cues, newline = core.read_srt(srt)
        except Exception as e:
            return {"error": f"Cannot read {os.path.basename(srt)}: {e}"}
        video = core.find_video(srt)
        vinfo = None
        if video:
            server.allow(video)
            vinfo = core.probe(video) or {}
            vinfo["path"] = video
        sess = core.Session(srt)
        self._sess = sess
        self._file = {"srt": srt, "video": video, "newline": newline, "vinfo": vinfo}
        self._prefs["last_file"] = srt
        self._save_prefs()
        cur_hash = core.file_hash(srt)
        hl = set(sess.meta.get("highlight") or [])
        lst = core.folder_srts(srt)
        key = os.path.normcase(srt)
        idx = next((i for i, p in enumerate(lst) if os.path.normcase(p) == key), 0)
        if video:
            threading.Thread(target=self._peaks, args=(video,), daemon=True).start()
        return {"srt": srt, "name": os.path.basename(srt), "dir": os.path.dirname(srt), "video": vinfo,
                "cues": cues, "highlight": [c["id"] for c in cues if core.highlight_sig(c) in hl],
                "pending": sess.load_pending(cur_hash), "hash": cur_hash,
                "folder": {"idx": idx, "total": len(lst)},
                "chat": sess.chat_history(), "versions": len(sess.meta["versions"]),
                "session_dir": sess.dir, "claude_session": sess.meta.get("claude_session"),
                "running": bool(self._run_ctx and os.path.normcase(self._run_ctx["file"]["srt"]) == os.path.normcase(srt)),
                "busy_other": bool(self._run_ctx) and not (self._run_ctx and os.path.normcase(self._run_ctx["file"]["srt"]) == os.path.normcase(srt))}

    def sub_layer(self, mk, text):
        """Титр поверх видео — тем же рендером, что у Subs Move и 2Stage (libass, тот же стиль и шрифты):
        PNG с прозрачностью и его место в кадре {path, x, y, w, h, W, H} или {empty}."""
        try:
            rd = _move_render()
            vi = (self._file or {}).get("vinfo") or {}
            if not self._file or not self._file.get("video"):
                return {"error": "no video"}
            orient = "v" if (vi.get("w") and vi.get("h") and vi["h"] > vi["w"]) else "h"
            mk = rd.sm.canon(mk) if mk else ""
            r = rd.layer(mk, text or "", orient, rd.sm.style_from(), rd.fonts_dir_for(self._file["srt"]))
            if r.get("name"):
                r["path"] = os.path.join(rd.CACHE_DIR, r["name"])
                server.allow(r["path"])
            return r
        except Exception as e:
            return {"error": str(e)}

    def _peaks(self, video):
        try:
            b64 = core.peaks(video)
            self._emit("peaks", {"video": video, "b64": b64, "rate": core.PEAK_RATE})
        except Exception as e:
            self._emit("peaks", {"video": video, "error": str(e)})

    def nav(self, delta):
        if not self._file:
            return None
        p = core.neighbor(self._file["srt"], int(delta))
        return self.load(p) if p else {"edge": True}

    def pending_save(self, data):
        if not self._sess:
            return False
        if data:
            data["base_hash"] = core.file_hash(self._file["srt"])
            data["saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._sess.save_pending(data)
        return True

    def _write(self, cues, why, sess=None, file=None):
        sess, file = sess or self._sess, file or self._file
        srt, nl = file["srt"], file["newline"]
        if not sess.meta["versions"] and os.path.exists(srt):
            sess.add_version(core.read_srt(srt)[0], nl, "Before first change")
        core.write_srt(srt, cues, nl)
        n = sess.add_version(cues, nl, why)
        return {"ok": True, "hash": core.file_hash(srt), "version": n}

    def save(self, cues, why="Manual save"):
        """Сохранение без Claude: подсветка изменённого и заметки остаются (их хранит pending)."""
        if not self._file:
            return {"ok": False, "msg": "No file"}
        ok, msg, norm = core.validate_cues(cues)
        if not ok:
            return {"ok": False, "msg": msg}
        try:
            return self._write(norm, why)
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def save_as(self, cues):
        import webview
        if not self._file:
            return {"ok": False}
        r = self._window.create_file_dialog(webview.SAVE_DIALOG, directory=os.path.dirname(self._file["srt"]),
                                            save_filename=os.path.basename(self._file["srt"]),
                                            file_types=("SubRip (*.srt)",))
        if not r:
            return {"ok": False, "cancel": True}
        path = r[0] if isinstance(r, (list, tuple)) else r
        if not path.lower().endswith(".srt"):
            path += ".srt"
        ok, msg, norm = core.validate_cues(cues)
        if not ok:
            return {"ok": False, "msg": msg}
        core.write_srt(path, norm, self._file["newline"])
        return {"ok": True, "path": path}

    def _set_highlight(self, cues, sess=None):
        sess = sess or self._sess
        sess.meta["highlight"] = [core.highlight_sig(c) for c in cues]
        sess.save_meta()

    def history_step(self, kind):
        """kind = 'undo' (вернуть состояние до последнего применения) | 'original'."""
        if not self._sess:
            return {"ok": False}
        if kind == "original":
            p = self._sess.p("original.srt")
            if not os.path.exists(p):
                return {"ok": False, "msg": "No original copy"}
            cues = core.read_srt(p)[0]
            why = "Revert to original"
        else:
            cues = self._sess.version_cues(2)
            if cues is None:
                return {"ok": False, "msg": "Nothing to undo"}
            why = f"Undo (back to version {len(self._sess.meta['versions']) - 1})"
        r = self._write(cues, why)
        self._set_highlight([])
        r["cues"] = cues
        return r

    def versions(self):
        return self._sess.meta["versions"] if self._sess else []

    # ── голос ──
    def rec_start(self, cue_id):
        if not self._sess:
            return None
        rid = f"r{int(time.time() * 1000)}"
        base = self._sess.p("audio", f"{cue_id}_{time.strftime('%H-%M-%S')}_{rid[-4:]}")
        return rid if self._rec.start(rid, cue_id, base) else None

    def rec_stop(self):
        return self._rec.stop()

    def media_url(self, path):
        if path and os.path.exists(path):
            server.allow(path)
            return f"/media?p={path}"
        return None

    # ── Claude ──
    # Прогон привязан к СВОЕМУ файлу (сессия + путь в ctx): можно уйти на другой файл, результат всё равно
    # ляжет туда, откуда его запустили. Очередь — «применить во всех файлах»: прогоны по одному.
    def claude_status(self):
        return {"exe": claude_bridge.find_claude(self._prefs.get("claude_exe")), "busy": self._run is not None,
                "srt": (self._run_ctx or {}).get("file", {}).get("srt"), "queue": [q["srt"] for q in self._queue]}

    def _request(self, state, mode, file, message=None):
        cues = []
        for i, c in enumerate(state.get("cues") or [], 1):
            d = {"id": c["id"], "n": i, "start": int(c["start"]), "end": int(c["end"]), "mk": c.get("mk") or "",
                 "text": c.get("text", "")}
            note = (c.get("note") or "").strip() if mode == "apply" else ""   # в чате заметки не применяем
            if note:
                d["note"] = note
                cr = c.get("caret")
                if cr:
                    t = d["text"]
                    s, e = max(0, min(len(t), cr.get("s", 0))), max(0, min(len(t), cr.get("e", 0)))
                    d["caret"] = {"pos": e, "sel_start": s, "sel_end": e, "selected": t[s:e],
                                  "before": t[max(0, s - 25):s], "after": t[e:e + 25]}
                if c.get("mark"):
                    d["mark"] = {"start": round(c["mark"]["a"], 3), "end": round(c["mark"]["b"], 3)}
                if c.get("hist"):                                         # прежние правки этого титра — контекст
                    d["history"] = [{"note": h.get("note", ""), "what": h.get("what", "")} for h in c["hist"][-3:]]
            cues.append(d)
        return {"srt": file["srt"], "video": file.get("video"), "mode": mode, "message": message, "cues": cues}

    def apply(self, state, message=None):
        """Apply (state с заметками) или сообщение из чата (message) для открытого файла."""
        if not self._file:
            return {"ok": False, "msg": "No file"}
        if self._run:
            return {"ok": False, "msg": "Claude is busy"}
        mode = "chat" if message else "apply"
        if mode == "apply" and not any((c.get("note") or "").strip() for c in state.get("cues") or []):
            return dict(self.save(state.get("cues") or [], "Manual changes"), manual=True)
        return self._start(self._sess, dict(self._file), state, mode, message)

    def pending_files(self):
        return core.sessions_with_notes()

    def save_all(self):
        """Save All: все остальные файлы с неприменённым (открытый сохраняет страница сама).
        Только ручные правки — пишутся сразу; есть голосовые — в очередь Claude (он сохранит и ручные)."""
        cur = (self._file or {}).get("srt")
        saved, queued = 0, []
        for f in core.sessions_with_notes():
            srt = f["srt"]
            if srt == cur:
                continue
            if f["n"]:
                queued.append({"srt": srt})
                continue
            try:
                sess = core.Session(srt)
                pend = sess.load_pending(core.file_hash(srt))
                if not pend or pend.get("stale"):
                    continue
                ok, msg, norm = core.validate_cues(pend.get("cues") or [])
                if not ok:
                    continue
                file = {"srt": srt, "newline": core.read_srt(srt)[1]}
                r = self._write(norm, "Save All", sess, file)
                pend["dirty"] = False
                pend["base_hash"] = r["hash"]
                keep = pend.get("hl") or any((c.get("note") or "").strip() or c.get("hist") for c in pend.get("cues") or [])
                sess.save_pending(pend if keep else None)
                saved += 1
            except Exception:
                continue
        have = {q["srt"] for q in self._queue}
        self._queue += [q for q in queued if q["srt"] not in have]
        if not self._run:
            self._next_in_queue()
        return {"ok": True, "saved": saved, "queued": len(queued)}

    def apply_all(self):
        """Все файлы с неприменёнными голосовыми правками — по очереди (открытый первым)."""
        if self._run:
            return {"ok": False, "msg": "Claude is busy"}
        files = core.sessions_with_notes()
        cur = (self._file or {}).get("srt")
        files.sort(key=lambda f: f["srt"] != cur)
        self._queue = [{"srt": f["srt"]} for f in files]
        if not self._queue:
            return {"ok": False, "msg": "No voice edits in any file"}
        n = len(self._queue)
        self._next_in_queue()
        return {"ok": True, "files": n}

    def _next_in_queue(self):
        while self._queue and not self._run:
            srt = self._queue.pop(0)["srt"]
            try:
                sess = core.Session(srt)
                pend = sess.load_pending(core.file_hash(srt))
                if not pend or pend.get("stale") or not any((c.get("note") or "").strip() for c in pend.get("cues") or []):
                    continue
                file = {"srt": srt, "video": core.find_video(srt), "newline": core.read_srt(srt)[1]}
                r = self._start(sess, file, {"cues": pend["cues"]}, "apply", None)
                if not r.get("ok"):
                    self._emit("claude", {"kind": "error", "srt": srt, "msg": r.get("msg", "")})
            except Exception as e:
                self._emit("claude", {"kind": "error", "srt": srt, "msg": str(e)})

    def _start(self, sess, file, state, mode, message):
        exe = claude_bridge.find_claude(self._prefs.get("claude_exe"))
        if not exe:
            return {"ok": False, "msg": "Claude CLI not found"}
        d = sess.new_apply_dir()
        req = self._request(state, mode, file, message)
        core.save_json(os.path.join(d, "request.json"), req)
        if os.path.exists(file["srt"]):
            shutil.copy2(file["srt"], os.path.join(d, "before.srt"))
        notes = [c for c in req["cues"] if c.get("note")]
        if mode == "apply":
            prompt = (f"Применить голосовые правки к титрам. Папка прогона: {d}\n"
                      f"Прочитай request.json, внеси правки ({len(notes)} шт.), запиши result.json туда же "
                      f"и коротко отчитайся.")
            sess.chat_log({"role": "user", "kind": "apply", "text": f"Apply — {len(notes)} voice edit(s)",
                           "notes": [{"n": c["n"], "note": c["note"]} for c in notes]})
        else:
            prompt = (f"Сообщение Saturni из панели чата: {message}\n\nТекущее состояние титров — request.json в "
                      f"папке {d}. Если для ответа нужно менять титры — запиши result.json в ту же папку "
                      f"(все титры), иначе просто ответь.")
            sess.chat_log({"role": "user", "kind": "chat", "text": message})
        ctx = {"dir": d, "t0": time.time(), "req": req, "state": state, "mode": mode, "text": "", "thinking": "",
               "sess": sess, "file": file}
        self._run_ctx = ctx
        srt = file["srt"]

        def on(kind, data):
            if kind == "start" and data.get("session_id"):
                sess.meta["claude_session"] = data["session_id"]
                sess.save_meta()
            elif kind == "delta":
                ctx[data["channel"]] = ctx.get(data["channel"], "") + data["text"]
            elif kind == "tool":
                sess.chat_log({"role": "claude", "kind": "tool", "text": f"{data['name']}: {data['input']}"})
            elif kind in ("done", "error"):
                self._finish(ctx, kind, data)
                return
            self._emit("claude", {"kind": kind, "srt": srt, **data})

        self._run = claude_bridge.Run(exe, sess.dir, prompt, self._prefs.get("model"), sess.meta.get("claude_session"), on,
                                      os.path.join(d, "stream.jsonl"), add_dirs=[os.path.dirname(srt)],
                                      effort=self._prefs.get("effort"))
        self._emit("claude", {"kind": "begin", "srt": srt, "mode": mode, "dir": d, "queue": len(self._queue)})
        return {"ok": True, "started": True, "dir": d}

    def _finish(self, ctx, kind, data):
        sess, file = ctx["sess"], ctx["file"]
        if self._run_ctx is ctx:
            self._run_ctx = None
            self._run = None
        if data.get("session_id"):
            sess.meta["claude_session"] = data["session_id"]
            sess.save_meta()
        if ctx.get("thinking"):
            sess.chat_log({"role": "claude", "kind": "thinking", "text": ctx["thinking"]})
        applied = None
        if kind == "done":
            text = data.get("text") or ctx.get("text") or ""
            sess.chat_log({"role": "claude", "kind": "text", "text": text})
            try:
                open(os.path.join(ctx["dir"], "report.md"), "w", encoding="utf-8").write(text)
            except Exception:
                pass
            applied = self._take_result(ctx)
        else:
            sess.chat_log({"role": "claude", "kind": "error", "text": data.get("msg", "")})
            if data.get("msg") == "Stopped":
                self._queue = []
        self._emit("claude", {"kind": kind, "srt": file["srt"], "name": os.path.basename(file["srt"]),
                              **data, "applied": applied, "queue": len(self._queue)})
        self._next_in_queue()

    def _take_result(self, ctx):
        sess, file = ctx["sess"], ctx["file"]
        rp = os.path.join(ctx["dir"], "result.json")
        if not os.path.exists(rp) or os.path.getmtime(rp) < ctx["t0"]:
            return None
        res = core.load_json(rp, None)
        if not isinstance(res, dict) or not isinstance(res.get("cues"), list):
            sess.chat_log({"role": "app", "kind": "error", "text": "result.json is broken — nothing applied"})
            return {"ok": False, "msg": "result.json is broken"}
        ok, msg, cues = core.validate_cues(res["cues"])
        if not ok:
            sess.chat_log({"role": "app", "kind": "error", "text": f"Result rejected: {msg}"})
            return {"ok": False, "msg": msg}
        before = {c["id"]: c for c in ctx["req"]["cues"]}
        changed = [c for c in cues if c["id"] not in before or any(
            before[c["id"]][k] != c[k] for k in ("start", "end", "text"))]
        w = self._write(cues, "Claude: " + ("Apply" if ctx["mode"] == "apply" else "chat"), sess, file)
        shutil.copy2(file["srt"], os.path.join(ctx["dir"], "after.srt"))
        self._set_highlight(changed, sess)
        unresolved = res.get("unresolved") or []
        un_ids = {u.get("id") if isinstance(u, dict) else u for u in unresolved}
        resolved = set(i for i in (res.get("resolved") or [c["id"] for c in ctx["req"]["cues"] if c.get("note")])
                       if i not in un_ids)
        what = {}
        for ch in res.get("changes") or []:
            if isinstance(ch, dict) and ch.get("id"):
                what[ch["id"]] = (what.get(ch["id"], "") + " " + str(ch.get("what", ""))).strip()
        # заметки → история титра (что сказано + как Claude понял); несделанные остаются заметками
        old = {c["id"]: c for c in ctx["state"].get("cues") or []}
        now = time.strftime("%Y-%m-%d %H:%M")
        merged = []
        for c in cues:
            o = old.get(c["id"]) or {}
            note = (o.get("note") or "").strip()
            hist = list(o.get("hist") or [])
            item = dict(c, note="", caret=None, mark=None, hist=hist)
            if note and c["id"] in resolved:
                hist.append({"note": note, "what": what.get(c["id"], ""), "at": now})
            elif note:
                item.update(note=o.get("note", ""), caret=o.get("caret"), mark=o.get("mark"))
            merged.append(item)
        for u in unresolved:                                               # почему не сделано — тоже в историю
            if isinstance(u, dict):
                for m in merged:
                    if m["id"] == u.get("id") and m["note"]:
                        m["why"] = u.get("why", "")
        sess.save_pending({"dirty": False, "cues": merged, "hl": [c["id"] for c in changed],
                           "base_hash": w["hash"], "saved": time.strftime("%Y-%m-%d %H:%M:%S")})
        note = f"Applied: {len(changed)} cue(s) changed · version {w['version']}"
        if unresolved:
            note += f" · {len(unresolved)} not done"
        sess.chat_log({"role": "app", "kind": "applied", "text": note})
        return {"ok": True, "cues": merged, "changed": [c["id"] for c in changed], "resolved": sorted(resolved),
                "unresolved": unresolved, "hash": w["hash"], "version": w["version"], "note": note}

    def claude_stop(self):
        self._queue = []
        if self._run:
            self._run.stop()
        return True

    def claude_new_chat(self):
        if self._sess:
            self._sess.meta["claude_session"] = None
            self._sess.save_meta()
            self._sess.chat_log({"role": "app", "kind": "info", "text": "New Claude conversation"})
        return True

    # ── проводник ──
    def reveal(self, path=None):
        import subprocess
        p = path or (self._file or {}).get("srt")
        if p and os.path.isdir(p):
            subprocess.Popen(["explorer", os.path.normpath(p)])
        elif p and os.path.exists(p):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        return True

    def reveal_session(self):
        return self.reveal(self._sess.dir) if self._sess else False

    # ── окно: своя шапка, перемещение, размер, запоминание места (как в Subs Move) ──
    def _hwnd(self):
        return int(self._window.native.Handle.ToInt64())

    def _ui(self, fn):
        try:
            from System import Action
            self._window.native.BeginInvoke(Action(fn))
        except Exception:
            fn()

    def _win_style(self):
        try:
            import winframe
            hwnd = self._hwnd()

            def frame():
                try:
                    winframe.install(hwnd)
                    self._restore_place(hwnd)
                    winframe.corners(hwnd, not winframe.zoomed(hwnd))
                    v = ctypes.c_int(1)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(v), 4)
                    self._emit("win", {"max": winframe.zoomed(hwnd)})
                except Exception:
                    pass
            self._ui(frame)
        except Exception:
            pass
        try:
            ico = os.path.join(core.HERE, "ui", "subs.ico")

            def set_icon():
                import System.Drawing
                self._window.native.Icon = System.Drawing.Icon(ico)
            self._ui(set_icon)
        except Exception:
            pass

    def _restore_place(self, hwnd):
        pl = self._prefs.get("placement") or {}
        r = pl.get("rect")
        if r and len(r) == 4:
            rc = wintypes.RECT(*r)
            if _u32.MonitorFromRect(ctypes.byref(rc), 0):
                _u32.SetWindowPos(hwnd, 0, r[0], r[1], r[2] - r[0], r[3] - r[1], 0x0004 | 0x0010)
                if pl.get("max"):
                    import winframe
                    winframe.command(hwnd, winframe.SC_MAXIMIZE)

                    # окно иногда ещё не готово принять команду (WebView2 дорисовывается) — проверить и повторить
                    def again(n=4):
                        if winframe.zoomed(hwnd) or _u32.IsIconic(hwnd):
                            return              # развернулось — дальше не трогаем (Saturni может сразу свернуть сам)
                        winframe.command(hwnd, winframe.SC_MAXIMIZE)
                        if n:
                            threading.Timer(.35, again, (n - 1,)).start()
                    threading.Timer(.35, again).start()
                return
        mi = _monitor_info(_u32.MonitorFromWindow(hwnd, 2))
        rw = wintypes.RECT()
        _u32.GetWindowRect(hwnd, ctypes.byref(rw))
        if mi:
            w, h = rw.right - rw.left, rw.bottom - rw.top
            a = mi.rcWork
            _u32.SetWindowPos(hwnd, 0, a.left + max(0, (a.right - a.left - w) // 2),
                              a.top + max(0, (a.bottom - a.top - h) // 2), 0, 0, 0x0001 | 0x0004 | 0x0010)

    def _store_place(self):
        try:
            hwnd = self._hwnd()
            wp = _WP()
            wp.length = ctypes.sizeof(_WP)
            if not _u32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
                return
            # свёрнутое из развёрнутого: showCmd = 2, но флаг WPF_RESTORETOMAXIMIZED (2) помнит, что оно было на весь экран
            mx = wp.showCmd == 3 or bool(_u32.IsZoomed(hwnd)) or (bool(_u32.IsIconic(hwnd)) and bool(wp.flags & 2))
            if not mx and not _u32.IsIconic(hwnd):
                rc = wintypes.RECT()
                _u32.GetWindowRect(hwnd, ctypes.byref(rc))
            else:
                rc = wp.rcNormalPosition
                mi = _monitor_info(_u32.MonitorFromRect(ctypes.byref(rc), 2))
                if mi:
                    dx, dy = mi.rcWork.left - mi.rcMonitor.left, mi.rcWork.top - mi.rcMonitor.top
                    rc = wintypes.RECT(rc.left + dx, rc.top + dy, rc.right + dx, rc.bottom + dy)
            if rc.right - rc.left >= 600 and rc.bottom - rc.top >= 400:
                self._prefs["placement"] = {"rect": [rc.left, rc.top, rc.right, rc.bottom], "max": mx}
        except Exception:
            pass

    def win_drag(self):
        hwnd = self._hwnd()

        def go():
            _u32.ReleaseCapture()
            _u32.SendMessageW(hwnd, 0x0112, 0xF012, 0)
        self._ui(go)
        return True

    def win_size(self, edge):
        code = {"l": 1, "r": 2, "t": 3, "tl": 4, "tr": 5, "b": 6, "bl": 7, "br": 8}.get(edge)
        if not code:
            return False
        hwnd = self._hwnd()

        def go():
            _u32.ReleaseCapture()
            _u32.SendMessageW(hwnd, 0x0112, 0xF000 + code, 0)
        self._ui(go)
        return True

    def win_min(self):
        import winframe
        winframe.command(self._hwnd(), winframe.SC_MINIMIZE)
        return True

    def win_max(self):
        import winframe
        hwnd = self._hwnd()
        mx = not winframe.zoomed(hwnd)
        winframe.command(hwnd, winframe.SC_MAXIMIZE if mx else winframe.SC_RESTORE)
        return mx

    def _on_maximized(self):
        try:
            import winframe
            winframe.corners(self._hwnd(), False)
        except Exception:
            pass
        self._emit("win", {"max": True})

    def _on_restored(self):
        try:
            import winframe
            mx = winframe.zoomed(self._hwnd())
            winframe.corners(self._hwnd(), not mx)
            self._emit("win", {"max": mx})
        except Exception:
            pass

    def titlebar(self, dark, border):
        try:
            hwnd, dwm = self._hwnd(), ctypes.windll.dwmapi

            def set_(attr, val):
                v = ctypes.c_int(val)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            h = border.lstrip("#")
            set_(20, 1 if dark else 0)
            set_(34, int(h[0:2], 16) | (int(h[2:4], 16) << 8) | (int(h[4:6], 16) << 16))
            return True
        except Exception:
            return False

    def win_close(self):
        self._force_close = True
        self._store_place()
        self._save_prefs()
        if self._run:
            self._run.stop()
        self._rec.close()
        threading.Thread(target=self._window.destroy, daemon=True).start()
        return True

    def set_dirty(self, d):
        """Страница сообщает, есть ли несохранённые ручные правки: тогда закрытие окна спрашивает."""
        self._dirty = bool(d)
        return True

    def _on_closing(self):
        if (self._run or getattr(self, "_dirty", False)) and not self._force_close:
            self._emit("close_request", {"busy": bool(self._run), "dirty": bool(getattr(self, "_dirty", False))})
            return False
        self._store_place()
        self._save_prefs()
        self._rec.close()
        return True

    def _on_drop(self, paths):
        self._emit("drop", paths)
