# -*- coding: utf-8 -*-
"""
Saturni · Voice / recorder.py — запись голоса и распознавание в фоне для любых наших приложений
(Subs Studio, модуль Saturni · Debug, …). Подключение:

    sys.path.insert(0, r"D:\\@Hub\\@ Saturni · Voice")
    from recorder import Recorder
    rec = Recorder(emit)            # emit(kind, data) — события в UI
    rec.start(rec_id, owner_id, path_base);  rec.stop()

События: rec {state on|off|error}, level {v 0..1}, asr_text {text, final}, asr {asr ready|loading|error}.
Если owner_id начинается с "dbg:", к имени события добавляется префикс "dbg_" — так голос модуля
отладки не путается с голосом самого приложения (один микрофон и одно распознавание на процесс).

· Микрофон открывается при первой записи и остаётся открытым: нет задержки на старте, кольцевой
  буфер 300 мс перед нажатием идёт в запись (первый слог не теряется).
· Пока идёт запись, раз в ~0.7 с текущий кусок уходит в GigaAM — текст появляется по ходу речи.
· Запись никогда не ждёт распознавания: задания встают в очередь.
· start(..., blocks=True): речь режется на блоки по паузам. Законченный блок сразу уходит в финальную
  обработку, а частичные результаты считаются только по текущему блоку — диктовка длинного текста не
  замедляется. asr_text тогда несёт seg (номер блока): final=True значит, что блок готов.
Распознавание — asr_worker.py питоном ~/.cache/venv-asr (onnx-asr + GigaAM-v3).
"""

import os
import json
import time
import wave
import threading
import subprocess
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NOWIN = 0x08000000 if os.name == "nt" else 0
SR = 16000
PREROLL = 0.3
PARTIAL_EVERY = 0.7
BLOCK_MIN, BLOCK_MAX, PAUSE = 2.5, 15.0, 1.1    # блоки: не короче, не длиннее, какая тишина их разделяет (короче — режет на обычных паузах речи)
ASR_PY = os.path.join(os.path.expanduser("~"), ".cache", "venv-asr", "Scripts", "python.exe")   # onnx-asr + GigaAM, тяжёлое — на C


class AsrClient:
    def __init__(self, on_result, on_status):
        self.on_result, self.on_status = on_result, on_status
        self.proc = None
        self.ready = False
        self.lock = threading.Lock()
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        if not os.path.exists(ASR_PY):
            self.on_status({"asr": "missing", "msg": "No ~/.cache/venv-asr — voice recognition unavailable"})
            return
        self.on_status({"asr": "loading"})
        try:
            self.proc = subprocess.Popen([ASR_PY, "-u", os.path.join(HERE, "asr_worker.py")], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWIN,
                                         encoding="utf-8", bufsize=1, env=dict(os.environ, PYTHONUTF8="1"))
        except Exception as e:
            self.on_status({"asr": "error", "msg": str(e)})
            return
        for line in self.proc.stdout:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("ready"):
                self.ready = True
                self.on_status({"asr": "ready"})
            elif "job" in d:
                self.on_result(d)
        self.ready = False
        self.on_status({"asr": "error", "msg": "Recognition process stopped"})

    def submit(self, job, path, final):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return False
            try:
                self.proc.stdin.write(json.dumps({"job": job, "path": path, "final": final}) + "\n")
                self.proc.stdin.flush()
                return True
            except Exception:
                return False

    def close(self):
        try:
            self.proc and self.proc.kill()
        except Exception:
            pass


class Recorder:
    """Одна активная запись за раз."""

    def __init__(self, emit):
        self._emit_raw = emit
        self.stream = None
        self.pre = deque(maxlen=int(PREROLL * SR / 160) + 2)
        self.cur = None                 # {rec, cue, frames[], base, inflight, last}
        self.lock = threading.Lock()
        self.level = 0.0
        self.asr = AsrClient(self._on_result, lambda d: emit("asr", d))
        self.jobs = {}
        threading.Thread(target=self._tick, daemon=True).start()

    def emit(self, kind, data):
        if str(data.get("cue", "")).startswith("dbg:"):
            kind = "dbg_" + kind
        self._emit_raw(kind, data)

    # ── микрофон ──
    def _ensure_stream(self):
        if self.stream:
            return
        import sounddevice as sd
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=160, callback=self._cb)
        self.stream.start()

    def _cb(self, indata, frames, t, status):
        x = indata[:, 0].copy()
        self.level = max(self.level * 0.6, float(np.sqrt(np.mean(x * x))) if len(x) else 0.0)
        with self.lock:
            if self.cur is not None:
                self.cur["frames"].append(x)
            else:
                self.pre.append(x)

    # ── запись ──
    def start(self, rec_id, cue_id, path_base, blocks=False):
        try:
            self._ensure_stream()
        except Exception as e:
            self.emit("rec", {"rec": rec_id, "cue": cue_id, "state": "error", "msg": f"Microphone: {e}"})
            return False
        with self.lock:
            if self.cur is not None:
                return False
            self.cur = {"rec": rec_id, "cue": cue_id, "frames": list(self.pre), "base": path_base,
                        "inflight": False, "last": 0.0, "blocks": blocks, "seg": 0, "seg_from": 0, "peak": 0.0}
            self.pre.clear()
        self.emit("rec", {"rec": rec_id, "cue": cue_id, "state": "on"})
        return True

    def stop(self):
        with self.lock:
            cur, self.cur = self.cur, None
        if not cur:
            return None
        pcm = np.concatenate(cur["frames"]) if cur["frames"] else np.zeros(0, np.float32)
        os.makedirs(os.path.dirname(cur["base"]), exist_ok=True)
        if cur["blocks"]:
            cur["closed"] = cur["seg"]
            ok = self._cut(cur, len(cur["frames"]), True)
            wav = cur["base"] + ".wav"
            self._wav(wav, pcm)
            self.emit("rec", {"rec": cur["rec"], "cue": cur["cue"], "state": "off", "dur": round(len(pcm) / SR, 2), "wav": wav, "queued": ok})
            return cur["rec"]
        wav = cur["base"] + ".wav"
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
        f32 = cur["base"] + ".f32"
        pcm.astype(np.float32).tofile(f32)
        job = cur["rec"] + ":final"
        self.jobs[job] = {"rec": cur["rec"], "cue": cur["cue"], "f32": f32}
        ok = self.asr.submit(job, f32, True)
        self.emit("rec", {"rec": cur["rec"], "cue": cur["cue"], "state": "off", "dur": round(len(pcm) / SR, 2),
                          "wav": wav, "queued": ok})
        if not ok:
            self.emit("asr_text", {"rec": cur["rec"], "cue": cur["cue"], "text": "", "final": True,
                                   "error": "Recognition not running"})
        return cur["rec"]

    @staticmethod
    def _wav(path, pcm):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())

    def _cut(self, cur, upto, last=False):
        """Кадры от начала блока до upto — законченный блок: сразу в финальное распознавание."""
        seg, frames = cur["seg"], cur["frames"][cur["seg_from"]:upto]
        cur["seg"], cur["seg_from"], cur["peak"] = seg + 1, upto, 0.0
        f32 = f"{cur['base']}.b{seg}.f32"
        os.makedirs(os.path.dirname(f32), exist_ok=True)
        (np.concatenate(frames) if frames else np.zeros(0, np.float32)).astype(np.float32).tofile(f32)
        job = f"{cur['rec']}:b{seg}"
        self.jobs[job] = {"rec": cur["rec"], "cue": cur["cue"], "f32": f32, "seg": seg, "last": last, "base": cur["base"]}
        ok = self.asr.submit(job, f32, True)
        if not ok:
            self.jobs.pop(job, None)
            self.emit("asr_text", {"rec": cur["rec"], "cue": cur["cue"], "seg": seg, "text": "", "final": True, "error": "Recognition not running"})
        return ok

    def _block_end(self, cur, frames):
        """Где закончить текущий блок: пауза в речи или, если блок слишком длинный, самое тихое место."""
        n, start = len(frames), cur["seg_from"]
        if (n - start) * 160 < BLOCK_MIN * SR:
            return None
        e = np.array([float(np.sqrt(np.mean(f * f))) for f in frames[max(start, n - 300):]])
        cur["peak"] = max(cur["peak"], float(e.max()) if len(e) else 0.0)
        tail = int(PAUSE * SR / 160)
        if len(e) >= tail and e[-tail:].max() < max(0.006, cur["peak"] * 0.12):
            return n
        if (n - start) * 160 >= BLOCK_MAX * SR:
            return max(start, n - len(e)) + int(np.argmin(e))
        return None

    def _tick(self):
        while True:
            time.sleep(0.06)
            cur = self.cur
            if cur is None:
                continue
            self.emit("level", {"rec": cur["rec"], "cue": cur["cue"], "v": round(min(1.0, self.level * 6), 3)})
            now = time.time()
            if self.asr.ready and not cur["inflight"] and now - cur["last"] >= PARTIAL_EVERY:
                with self.lock:
                    if self.cur is not cur:
                        continue
                    frames = list(cur["frames"])
                if cur["blocks"]:
                    end = self._block_end(cur, frames)
                    if end:
                        self._cut(cur, end)
                    frames = frames[cur["seg_from"]:]
                if len(frames) * 160 < SR * 0.5:
                    continue
                path = cur["base"] + ".part.f32"
                os.makedirs(os.path.dirname(path), exist_ok=True)
                np.concatenate(frames).astype(np.float32).tofile(path)
                job = f"{cur['rec']}:p{int(now * 1000)}"
                self.jobs[job] = {"rec": cur["rec"], "cue": cur["cue"], "cur": cur, "seg": cur["seg"]}
                cur["inflight"], cur["last"] = True, now
                if not self.asr.submit(job, path, False):
                    cur["inflight"] = False

    def _on_result(self, d):
        info = self.jobs.pop(d["job"], None)
        if not info:
            return
        if "cur" in info:
            c = info["cur"]
            c["inflight"] = False
            if c["blocks"]:                          # сырой текст блока; последний показываем и после остановки — он полный
                if info["seg"] < c["seg"] and info["seg"] != c.get("closed"):
                    return
                self.emit("asr_text", {"rec": info["rec"], "cue": info["cue"], "seg": info["seg"], "text": d.get("text", ""), "final": False})
                return
            if c is not self.cur:                    # запись уже закончилась — ждём финал
                return
        elif "seg" in info:                          # готовый блок
            for f in [info["f32"]] + ([info["base"] + ".part.f32"] if info.get("last") else []):
                try:
                    os.remove(f)
                except Exception:
                    pass
            self.emit("asr_text", {"rec": info["rec"], "cue": info["cue"], "seg": info["seg"], "text": d.get("text", ""), "final": True, "error": d.get("error")})
            return
        else:
            for ext in (".f32", ".part.f32"):        # финал: служебные куски больше не нужны, wav остаётся
                try:
                    os.remove(info["f32"][:-4] + ext)
                except Exception:
                    pass
        self.emit("asr_text", {"rec": info["rec"], "cue": info["cue"], "text": d.get("text", ""),
                               "final": bool(d.get("final")), "error": d.get("error")})

    def close(self):
        try:
            self.stream and self.stream.close()
        except Exception:
            pass
        self.asr.close()
