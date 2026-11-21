# -*- coding: utf-8 -*-
r"""Saturni · Editor: the welcome window — opened from the shortcut without a file. Recent projects and files, Open file."""
import os
import subprocess
import sys
from pathlib import Path

import webview

from common import APP_DIR, MEDIA_EXT, PHOTO_EXT, PROJECT_EXT, PLAYABLE
from settings import COLORS, STATE, write_state

ICON = {                                                    # the same drawings as ui/kit/icons.js
    "project": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 13.5h8M8 16.5h5"/>',
    "video": '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7.5 5v14M16.5 5v14M3.5 12h4M16.5 12h4"/>',
    "audio": '<path d="M9 18V5.5l11-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    "photo": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="m4 17.5 5-5 4 4 2.5-2.5 4.5 4.5"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
}


def kind_of(p: Path) -> str:
    e = p.suffix.lower()
    return "project" if e == PROJECT_EXT else "photo" if e in PHOTO_EXT else "audio" if e in PLAYABLE else "video"


class WelcomeApi:
    def __init__(self, script: Path):
        self.script = script

    def items(self):
        out = {}
        for key in ("projects", "recent"):
            out[key] = [{"path": p, "name": Path(p).name, "folder": str(Path(p).parent), "kind": kind_of(Path(p))}
                        for p in STATE.get(key, []) if Path(p).is_file()][:8]
        return out

    def open(self, path: str):
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
        subprocess.Popen([str(pyw), str(self.script), path], cwd=str(self.script.parent))
        webview.windows[0].destroy()

    def pick(self):
        exts = ";".join(f"*{e}" for e in sorted(MEDIA_EXT | PHOTO_EXT | {PROJECT_EXT}))
        got = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, file_types=(f"Media and projects ({exts})", "All files (*.*)"))
        if got:
            self.open(got[0])

    def close(self):
        webview.windows[0].destroy()

    def forget(self, path: str):
        for key in ("projects", "recent"):
            if path in STATE.get(key, []):
                write_state(key, [p for p in STATE[key] if p != path])
        return True


def page() -> str:
    css = (APP_DIR / "ui" / "app.css").read_text(encoding="utf-8")
    icons = "{" + ",".join(f'"{k}":\'{v}\'' for k, v in ICON.items()) + "}"
    vars_ = f':root{{--bg:{COLORS["bg"]};--panel:{COLORS["panel"]};--text:{COLORS["text"]};--accent:{COLORS["accent"]};}}'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Saturni · Editor</title><style>{css}{vars_}
body {{ padding:22px 22px 18px; gap:14px; }}
#head {{ display:flex; align-items:center; gap:10px; }}
#head h1 {{ margin:0; font-size:16px; font-weight:600; line-height:1; flex:1; }}
#open {{ height:32px; padding:0 14px; }}
.lists {{ flex:1; min-height:0; overflow:auto; display:flex; flex-direction:column; gap:4px; }}
.lists .cap {{ margin:6px 0 2px 4px; }}
.it {{ display:grid; grid-template-columns:20px minmax(0,1fr) 24px; align-items:center; gap:10px; height:44px; padding:0 4px 0 10px;
       border-radius:8px; cursor:pointer; transition:background .18s ease; }}
.it:hover {{ background:var(--hover); }}
.it svg.i {{ color:var(--dim); }}
.it:hover > svg.i {{ color:var(--text); }}
.it .t {{ display:flex; flex-direction:column; gap:4px; min-width:0; }}
.it .n, .it .f {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; line-height:1; }}
.it .f {{ font-size:11px; color:var(--dim); }}
.it .x {{ width:24px; height:24px; padding:0; justify-content:center; opacity:0; }}
.it:hover .x {{ opacity:1; }}
.it .x svg.i {{ width:14px; height:14px; }}
#empty {{ color:var(--dim); text-align:center; margin-top:60px; line-height:1.5; }}
</style></head><body>
<div id="head"><h1>Saturni · Editor</h1><button id="open" class="primary">Open file…</button></div>
<div class="lists" id="lists"></div>
<script>
const I = {icons}, ic = n => `<svg class="i" viewBox="0 0 24 24">${{I[n]}}</svg>`, esc = s => s.replace(/[&<>"]/g, c => "&#" + c.charCodeAt(0) + ";");
async function fill() {{
  const d = await pywebview.api.items(), box = document.getElementById("lists"); box.innerHTML = "";
  for (const [key, title] of [["projects", "Projects"], ["recent", "Recent files"]]) {{
    if (!d[key].length) continue;
    box.insertAdjacentHTML("beforeend", `<div class="cap">${{title}}</div>`);
    for (const f of d[key]) {{
      const el = document.createElement("div"); el.className = "it"; el.title = f.path;
      el.innerHTML = `${{ic(f.kind)}}<span class="t"><span class="n">${{esc(f.name)}}</span><span class="f">${{esc(f.folder)}}</span></span><button class="x ic" title="Remove from the list">${{ic("close")}}</button>`;
      el.onclick = () => pywebview.api.open(f.path);
      el.querySelector(".x").onclick = ev => {{ ev.stopPropagation(); pywebview.api.forget(f.path).then(fill); }};
      box.appendChild(el);
    }}
  }}
  if (!box.children.length) box.innerHTML = '<div id="empty">Open a video, a sound or a picture.<br>Recent files and projects show up here.</div>';
}}
document.getElementById("open").onclick = () => pywebview.api.pick();
addEventListener("keydown", e => {{ if (e.key === "Escape") pywebview.api.close(); if (e.ctrlKey && e.code === "KeyO") {{ e.preventDefault(); pywebview.api.pick(); }} }});
addEventListener("pywebviewready", fill);
</script></body></html>"""


def welcome(script: Path, title: str, box) -> None:
    api = WelcomeApi(script)
    x, y, w, h = box
    webview.create_window(title, html=page(), js_api=api, x=x, y=y, width=w, height=h, min_size=(420, 360), background_color=COLORS["bg"])
