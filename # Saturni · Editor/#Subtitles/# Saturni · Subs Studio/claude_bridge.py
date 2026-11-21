# -*- coding: utf-8 -*-
"""
claude_bridge.py — Claude Code в фоне (claude.exe -p) для кнопки Apply Edits и панели чата.

Каждый прогон — отдельный процесс `claude -p` с потоковым JSON (stream-json + partial messages):
мышление, текст и вызовы инструментов сразу уходят в панель чата приложения и в stream.jsonl.
Продолжение разговора — `--resume <session_id>` (id хранится в meta.json сессии файла), рабочая
папка всегда папка сессии (resume привязан к ней).

claude.exe: из PATH, иначе свежий из %LOCALAPPDATA%/Claude-Data/*/claude-code/<версия>/*/claude.exe
(CLI, который ставит десктопное приложение Claude). Нужен один раз вход: claude.exe /login.
"""

import os
import glob
import json
import shutil
import threading
import subprocess

from core import HERE, ROOT, NOWIN

PROMPT_FILE = os.path.join(HERE, "CLAUDE_APPLY.md")
TOOLS_ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep", "Bash(ffmpeg:*)", "Bash(ffprobe:*)", "Bash(python:*)"]


def find_claude(pref=None):
    if pref and os.path.exists(pref):
        return pref
    p = shutil.which("claude")
    if p:
        return p
    c = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Claude-Data", "*", "claude-code", "*", "*", "claude.exe"))
    c += glob.glob(os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe"))
    return max(c, key=os.path.getmtime) if c else None


def _env():
    env = dict(os.environ, PYTHONUTF8="1")
    for k in list(env):
        if k.startswith("CLAUDECODE") or k in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            env.pop(k, None)
    return env


def _short(inp):
    """Вызов инструмента одной строкой для чата."""
    if not isinstance(inp, dict):
        return str(inp)[:160]
    for k in ("command", "file_path", "pattern", "path", "url", "description"):
        if inp.get(k):
            return str(inp[k])[:200]
    return json.dumps(inp, ensure_ascii=False)[:200]


class Run:
    """Один прогон. on(kind, data): kind = start|delta|block|tool|tool_result|done|error."""

    def __init__(self, exe, cwd, prompt, model, resume, on, log_path, add_dirs=(), effort=None):
        self.on, self.log_path = on, log_path
        self.proc = None
        self.stopped = False
        args = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--permission-mode", "acceptEdits", "--allowedTools", *TOOLS_ALLOWED,
                "--append-system-prompt-file", PROMPT_FILE, "--add-dir", ROOT]
        for d in add_dirs:
            if d and os.path.isdir(d):
                args += ["--add-dir", d]
        if model:
            args += ["--model", model]
        if effort:
            args += ["--effort", effort]
        if resume:
            args += ["--resume", resume]
        self.args, self.cwd, self.prompt = args, cwd, prompt
        threading.Thread(target=self._go, daemon=True).start()

    def stop(self):
        self.stopped = True
        try:
            self.proc and self.proc.kill()
        except Exception:
            pass

    def _go(self):
        try:
            self.proc = subprocess.Popen(self.args, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, creationflags=NOWIN, env=_env(),
                                         encoding="utf-8", errors="replace", bufsize=1)
        except Exception as e:
            self.on("error", {"msg": f"Cannot start Claude: {e}"})
            return
        try:
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
        except Exception:
            pass
        err_buf = []
        threading.Thread(target=lambda: err_buf.extend(self.proc.stderr.read().splitlines()[-30:]), daemon=True).start()
        result = None
        session_id = None
        log = open(self.log_path, "a", encoding="utf-8")
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                log.write(line + "\n")
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                t = ev.get("type")
                if ev.get("session_id"):
                    session_id = ev["session_id"]
                if t == "system" and ev.get("subtype") == "init":
                    self.on("start", {"session_id": session_id, "model": ev.get("model")})
                elif t == "stream_event":
                    e = ev.get("event") or {}
                    if e.get("type") == "content_block_start":
                        cb = e.get("content_block") or {}
                        self.on("block", {"block": cb.get("type"), "index": e.get("index")})
                    elif e.get("type") == "content_block_delta":
                        d = e.get("delta") or {}
                        if d.get("type") == "text_delta":
                            self.on("delta", {"channel": "text", "text": d.get("text", "")})
                        elif d.get("type") == "thinking_delta":
                            self.on("delta", {"channel": "thinking", "text": d.get("thinking", "")})
                elif t == "assistant":
                    for c in (ev.get("message") or {}).get("content") or []:
                        if c.get("type") == "tool_use":
                            self.on("tool", {"name": c.get("name"), "input": _short(c.get("input"))})
                elif t == "user":
                    for c in (ev.get("message") or {}).get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                            txt = c.get("content")
                            if isinstance(txt, list):
                                txt = " ".join(x.get("text", "") for x in txt if isinstance(x, dict))
                            self.on("tool_result", {"error": True, "text": str(txt)[:300]})
                elif t == "result":
                    result = ev
        finally:
            log.close()
        self.proc.wait()
        if self.stopped:
            self.on("error", {"msg": "Stopped", "session_id": session_id})
            return
        if result is None:
            self.on("error", {"msg": "Claude exited without result. " + " ".join(err_buf[-5:]), "session_id": session_id})
            return
        text = result.get("result") or ""
        if result.get("is_error"):
            if "login" in text.lower():
                text = ("Claude CLI is not logged in. Once, in a terminal, run:\n"
                        f"\"{self.args[0]}\"\nand type /login there.")
            self.on("error", {"msg": text, "session_id": session_id})
            return
        self.on("done", {"text": text, "session_id": session_id, "cost": result.get("total_cost_usd"),
                         "ms": result.get("duration_ms")})
