#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4.3. #RGB`1% — GUI-лаунчер для "4.3. #RGB`1%.mjs": RGB Split (Horizontal Split = 1) на клипы
фона вертикалок (V1 = "BG-Blur" после 4.2.). Saturni, 2026-10-01: RGB вынесен из 4.2 отдельным
этапом. Двойной клик -> статус-бар; уже обработанные клипы пропускаются.

Headless-режим — как у самого .mjs, аргументы пробрасываются как есть:
    python "4.3. #RGB`1%.py" "Имя секвенции 1" "Имя секвенции 2"
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

STAGES = ["Scanning", "Splitting"]

MJS_PATH = os.path.join("@tools", "mjs", "4.3. #RGB`1%.mjs")

if __name__ == "__main__":
    mjs_launcher.run(MJS_PATH, STAGES, project_root=HERE)
