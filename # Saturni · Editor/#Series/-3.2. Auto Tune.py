#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3.2. Auto Tune — стадия 3.2: АВТОНОМНАЯ сборка титров + проверка (переделано 2026-09-28, Saturni:
«3.1 делает основу, 3.2 — полноценный сбор, как делает Claude, только скриптом; Claude потом правит
то, что жёстко не пропишешь»).

Двойной клик → окно (@tools/3.2. Subs UI.py, тёмное, голубо-синий акцент): добавь видео после 3.1
(или папку) → «Собрать титры» → рядом с каждым видео готовый `<имя>.srt`:
  • нарезка по смысловым группам (предлог/«не»/союз/определение не отрываются), паузы, бюджет
    времени ~750 мс, однословные — только самостоятельные слова — @tools/3.2. Subs Assemble.py;
  • тайминг −80 мс / +20 мс, стыки, «ё», повторы через дефис, ***** без знаков, отсев галлюцинаций;
  • сразу проверка @tools/3.2. Auto Tune.py: >1.5 с, висячие слова, доли однословных/«!».
Готовый .srt в списке — только проверка и автопочинка (как старый 3.2).
Уже существующий `<имя>.srt` без галочки «Перезаписать готовые» не трогается.

Что остаётся человеку/Claude: смысл сцены (отсылки, согласование), «!»/«?» по интонации,
пропущенные реплики, мат по вырезам громкости, пение.
Точность по разборам #analysis (63 ролика, границы титров против финалов Saturni):
precision 0.83 / recall 0.84 (ручная сборка Claude — 0.88 / 0.90), медиана 781 мс, однословных 32% —
`python "@tools/#3.2. Subs Assemble-Eval.py"`.

Headless (для Claude):
    python "-3.2. Auto Tune.py" "<видео или .srt или папка>" [...] [--overwrite] [--no-apply]
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "@tools"))
import importlib.util as _ilu
_TOOLS = os.path.join(HERE, "@tools")


def _tool(name, file):
    """Модуль из @tools по пути: в именах пробелы/точки/@ (2026-10-07), обычный import их не
    видит. Регистрируется под прежним именем модуля — повторная загрузка не нужна."""
    if name not in sys.modules:
        spec = _ilu.spec_from_file_location(name, os.path.join(_TOOLS, file))
        sys.modules[name] = mod = _ilu.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


VIDEO_EXT = (".mp4", ".mov", ".mkv")


def expand(paths):
    import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
    sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
    if sb is None:
        _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
        sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(sb)
    out = []
    for p in paths:
        if os.path.isdir(p):
            fs = [os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(VIDEO_EXT)]
            out += sorted(fs, key=lambda f: sb.natural_sort_key(os.path.basename(f)))
        elif os.path.isfile(p):
            out.append(p)
        else:
            print(f"[!] Не найдено: {p}")
    return out


def headless(argv):
    auto_tune = _tool("auto_tune", "3.2. Auto Tune.py")
    sa = _tool("subs_assemble", "3.2. Subs Assemble.py")
    over = "--overwrite" in argv
    apply = "--no-apply" not in argv
    paths = expand([a for a in argv if not a.startswith("--")])
    srt_to_check = []
    for p in paths:
        if p.lower().endswith(".srt"):
            srt_to_check.append(p)
            continue
        src = sa.find_input(p)
        if not src:
            print(f"✕ {os.path.basename(p)}: нет words.json / «1. Whisper One Word» — сначала 3.1")
            continue
        out = os.path.splitext(p)[0] + ".srt"
        if os.path.exists(out) and not over:
            print(f"• {os.path.basename(out)} уже есть — пропущен (--overwrite)")
            continue
        cues = sa.assemble_file(src, out, p)
        cov = sa.coverage(src, p)
        note = f", речь только на {cov * 100:.0f}% ролика — проверить вручную" if cov is not None and cov < 0.4 else ""
        print(f"✓ {os.path.basename(out)}: {len(cues)} титров ({'words.json' if src.endswith('.json') else 'one-word'}){note}")
        srt_to_check.append(out)
    if srt_to_check:
        auto_tune.run(srt_to_check, apply=apply)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        headless(args)
    else:
        try:
            subs_ui = _tool("subs_ui", "3.2. Subs UI.py")
            subs_ui.launch()
        except Exception:
            import traceback
            traceback.print_exc()
            input("\nНажми Enter, чтобы закрыть...")
