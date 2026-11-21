# -*- coding: utf-8 -*-
"""Проверка папки выгрузки и шаблона рендера у секвенций: python "12. Check Export.py" <проект.prproj | папка проекта> [--all].
Читает сохранённый .prproj (сначала сохранить проект). У каждой секвенции Premiere хранит свои настройки экспорта —
копия секвенции наследует их от шаблона, поэтому чужая папка из старого проекта расползается по всем копиям.
Показывает секвенции, у которых папка не RENDER_DIR или шаблон не PRESET. --all — показать все."""
import glob, gzip, html, json, os, re, sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RENDER_DIR = r"D:\# Video\#Поляна\@Render"
PRESET = "# H.264`10"          # пресет «# H_1.epr»


def project_file(arg):
    if os.path.isfile(arg):
        return arg
    files = [f for f in glob.glob(os.path.join(arg, "*.prproj"))]
    return max(files, key=os.path.getmtime) if files else None


def export_of(block):
    m = re.search(r"<ExportSettings\.Info\.SaveAsFile>(.*?)</", block, re.S)
    out = json.loads(m.group(1)).get("OutPath", "") if m else ""
    m = re.search(r"<ExportSettings\.ExportedPreset\.SaveAsFile>(.*?)</ExportSettings\.ExportedPreset\.SaveAsFile>", block, re.S)
    preset = ""
    if m:
        n = re.search(r"<PresetName>(.*?)</PresetName>", html.unescape(m.group(1)))
        preset = n.group(1) if n else ""
    return out, preset


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    p = project_file(args[0] if args else ".")
    if not p:
        sys.exit("нет .prproj")
    x = gzip.open(p).read().decode("utf-8", "replace")
    rows, own = [], []
    for m in re.finditer(r"<Sequence ObjectUID=.*?</Sequence>", x, re.S):
        b = m.group(0)
        names = re.findall(r"<Name>([^<]*)</Name>", b)
        if "<ExportSettings.Info.SaveAsFile>" not in b:
            own.append(names[-1] if names else "?")      # своих настроек нет — берёт настройки проекта
            continue
        out, preset = export_of(b)
        rows.append((names[-1] if names else "?", os.path.dirname(out), preset))
    pr = x.find("<Project ObjectID")
    proj_out, proj_preset = export_of(x[pr:x.find("</Project>", pr)]) if pr >= 0 else ("", "")
    for n in own:
        rows.append((n, os.path.dirname(proj_out), proj_preset))
    bad = [r for r in rows if os.path.normcase(r[1].replace("\\\\?\\", "")) != os.path.normcase(RENDER_DIR) or r[2] != PRESET]
    print(f"{os.path.basename(p)}: секвенций {len(rows)}, с чужой папкой или шаблоном {len(bad)}")
    print(f"  без своих настроек (берут из проекта): {len(own)}")
    print(f"  по умолчанию в проекте: {os.path.dirname(proj_out) or '—'} | {proj_preset or 'шаблон не записан'}")
    print("  папки:", "; ".join(f"{d or '—'} ×{n}" for d, n in Counter(r[1] for r in rows).most_common(5)))
    print("  шаблоны:", "; ".join(f"{s or 'не записан'} ×{n}" for s, n in Counter(r[2] for r in rows).most_common(5)))
    for name, d, s in (rows if "--all" in sys.argv else bad):
        print(f"  {name}: {d or '—'} | {s or 'шаблон не записан'}")


if __name__ == "__main__":
    main()
