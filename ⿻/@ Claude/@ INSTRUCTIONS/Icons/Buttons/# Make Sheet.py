# -*- coding: utf-8 -*-
"""Пересобирает «! All icons.png» — лист всех значков кнопок этой папки, чтобы видеть набор целиком.

  python "# Make Sheet.py"

Берёт все *.svg рядом, рисует плитки (значок, название из имени файла, под ним имя в коде — ключ из
Editor ui\\kit\\icons.js, если рисунок там есть), снимает страницу через Edge headless. Запускать после
каждого добавленного или изменённого значка.
"""
import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path



# region 💠 НАСТРОЙКИ


# --- Лист -------------------------------------------------------
COLS = 6                     # плиток в ряду
TILE_W, TILE_H = 150, 105    # размер плитки
GAP, PAD = 14, 22            # промежуток между плитками и поле вокруг
OUT = "! All icons.png"      # имя готового листа

# endregion



# region 1️⃣ ПУТИ


HERE = Path(__file__).resolve().parent
HUB = HERE.parents[4]                                                   # Buttons → Icons → @ INSTRUCTIONS → @ Claude → ⿻ → Hub
ICONS_JS = HUB / "# Saturni · Editor" / "# Editor" / "ui" / "kit" / "icons.js"


def edge():
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
        p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if p.exists():
            return str(p)
    raise SystemExit("Edge не найден")

# endregion



# region 2️⃣ СТРАНИЦА


def inner(svg):
    """Содержимое <svg>…</svg> и его атрибуты обводки (у Play / Pause своя заливка)."""
    m = re.search(r"<svg\b([^>]*)>(.*)</svg>", svg, re.S)
    return (m.group(2).strip(), m.group(1)) if m else ("", "")


def page(files):
    tiles = []
    for f in files:
        body, attrs = inner(f.read_text(encoding="utf-8"))
        name = f.stem
        tiles.append({"name": name, "body": body, "fill": 'fill="currentColor"' in attrs and 'fill="none"' not in attrs})
    rows = (len(tiles) + COLS - 1) // COLS
    w = PAD * 2 + COLS * TILE_W + (COLS - 1) * GAP
    h = PAD * 2 + rows * TILE_H + (rows - 1) * GAP
    js = ICONS_JS.as_uri() if ICONS_JS.exists() else ""
    doc = f"""<!doctype html><meta charset="utf-8">
<style>
html, body {{ margin: 0; background: #0f1012; }}
.grid {{ display: grid; grid-template-columns: repeat({COLS}, {TILE_W}px); gap: {GAP}px; padding: {PAD}px; }}
.t {{ height: {TILE_H}px; box-sizing: border-box; border: 1px solid rgba(233,234,236,.1); border-radius: 10px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 6px; color: #e9eaec; text-align: center; padding: 0 8px; }}
.t svg {{ width: 28px; height: 28px; margin-bottom: 4px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }}
.t b {{ font: 600 13px/1.15 Inter, "Segoe UI", sans-serif; }}
.t code {{ font: 11px/1 Consolas, monospace; color: rgba(233,234,236,.5); min-height: 11px; }}
</style>
<script src="{js}"></script>
<div class="grid" id="g"></div>
<script>
const T = {json.dumps(tiles, ensure_ascii=False)};
const norm = s => String(s).replace(/\\s+/g, "").replace(/"/g, "'");
const map = typeof ICONS === "object" ? ICONS : {{}};
for (const t of T) {{
  // имя в коде: тот же рисунок в icons.js, иначе слово из названия файла, совпадающее с ключом
  let key = Object.keys(map).find(k => norm(map[k]) === norm(t.body)) || "";
  if (!key) {{ const words = t.name.toLowerCase().split(/[^a-z]+/); key = Object.keys(map).find(k => words.includes(k)) || ""; }}
  const d = document.createElement("div"); d.className = "t";
  d.innerHTML = `<svg viewBox="0 0 24 24" ${{t.fill ? 'fill="currentColor"' : ""}}>${{t.body}}</svg><b></b><code></code>`;
  d.querySelector("b").textContent = t.name; d.querySelector("code").textContent = key;
  document.getElementById("g").append(d);
}}
</script>"""
    return doc, w, h

# endregion



# region 3️⃣ СНИМОК


def main():
    files = sorted(p for p in HERE.glob("*.svg"))
    doc, w, h = page(files)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "sheet.html"
        f.write_text(doc, encoding="utf-8")
        out = HERE / OUT
        subprocess.run([edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                        "--force-device-scale-factor=1", f"--window-size={w},{h}", "--virtual-time-budget=2000",
                        f"--screenshot={out}", f.as_uri()], capture_output=True, timeout=60)
    print(f"{OUT}: {len(files)} значков")


if __name__ == "__main__":
    main()

# endregion
