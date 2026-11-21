#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2. Silence Cut — GUI-лаунчер для "@tools/mjs/2. Silence Cut.mjs" (сам .mjs не
изменился по логике, только эмиттит структурные события прогресса — см.
@tools/mjs/@Premiere Lib.mjs). 2026-09-11, Saturni.

Двойной клик -> статус-бар (D:/@Hub/@ Saturni · Status Bar/@StatusBar.py, ♥-полоски по этапам, WIN/
LOSE-концовка). Чистый успех -> консоль закрывается сама. Любая ошибка (в т.ч.
исчерпанные флаки-ретраи) -> консоль остаётся открытой до Enter/F, ниже
печатаются подробности (что именно и на какой секвенции сломалось).

Headless-режим — как у самого .mjs, аргументы (включая флаги --min-kept и
т.п.) пробрасываются как есть:
    python "2. Silence Cut.py" --min-kept 0.5 "Имя секвенции 1"
"""
import os
import sys

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


mjs_launcher = _tool("mjs_launcher", "@MJS Launcher.py")

# Канонический порядок этапов (см. шапку "@tools/mjs/2. Silence Cut.mjs") — 10 сердечек
# делятся поровну на 3 этапа.
STAGES = ["Scanning", "Analyzing", "Cutting"]
MJS_PATH = os.path.join("@tools", "mjs", "2. Silence Cut.mjs")

if __name__ == "__main__":
    mjs_launcher.run(MJS_PATH, STAGES, project_root=HERE)
