#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3.1. Basic Subtitles — GUI-лаунчер для @tools/3.1. Subtitles Pipeline.py (стадия 3
пайплайна). 2026-09-11, Saturni.

Двойной клик -> окно выбора (@tools/@File Picker.py): Add Files... / Add
Folder(s)... / Remove / Clear слева-справа, OK/Cancel снизу. Сама обработка
НЕ стартует по одному выбору — только по нажатию OK. Из папки берутся только
`*1h.mp4` верхнего уровня (тот же паттерн, что и во всём остальном пайплайне);
файлы, добавленные явно через Add Files..., идут как есть, без фильтра по
имени. После OK — обычный (не .pyw) файл, поэтому виден терминал: в нём и
разворачивается статус-бар из D:/@Hub/@ Saturni · Status Bar/@StatusBar.py (♥-полоски, цвета,
видео/аудио-концовка по завершении батча).

Headless-режим — для Claude: передай пути аргументами командной строки, и
окно выбора вообще не появится, сразу батч:
    python "3.1. Basic Subtitles.py" "D:\\...\\Серия 5" "D:\\...\\clip 1h.mp4"
"""
import glob
import os
import sys

# 2026-09-11 (Saturni): без этого — на дефолтной кодовой странице Windows-
# консоли (cp1251/1252, до chcp 65001) ЛЮБОЙ print() с кириллицей ниже (в т.ч.
# "Отменено.", "Ничего обрабатывать...", даже текст самого traceback) падает
# с UnicodeEncodeError — необработанным, консоль закрывается мгновенно, ни
# разу не показав, в чём дело. status_bar.run() чинит это для себя, но только
# после того, как дошло до cp.run_batch() — до этого момента (picker, resolve)
# кодировка ещё дефолтная. Реально воспроизведено вживую при разборе бага
# "консоль вылетает раньше, чем успеваю прочитать".
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


cp = _tool("subtitles_pipeline", "3.1. Subtitles Pipeline.py")
import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
if sb is None:
    _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
    sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(sb)

VIDEO_GLOB = "*1h.mp4"
FILE_TYPES = [("Видео", "*.mp4 *.mov *.mkv"), ("Все файлы", "*.*")]


def resolve(paths):
    """Файлы -> как есть. Папки -> *1h.mp4 верхнего уровня (не рекурсивно)."""
    videos, seen = [], set()
    for p in paths:
        if os.path.isdir(p):
            # Натуральная сортировка ("2." раньше "10.") — обычный sorted() по
            # строкам расставил бы их наоборот (Saturni, 2026-09-11).
            found = sorted(glob.glob(os.path.join(p, VIDEO_GLOB)),
                            key=lambda f: sb.natural_sort_key(os.path.basename(f)))
            if not found:
                print(f"[!] В папке ничего не нашлось по маске {VIDEO_GLOB}: {p}")
            for f in found:
                if f not in seen:
                    seen.add(f)
                    videos.append(f)
        elif os.path.isfile(p):
            if p not in seen:
                seen.add(p)
                videos.append(p)
        else:
            print(f"[!] Не найдено: {p}")
    return videos


def main():
    argv_paths = sys.argv[1:]
    if argv_paths:
        raw = argv_paths     # headless: пути пришли явно (в т.ч. от Claude)
    else:
        pick = _tool("file_picker", "@File Picker.py").pick
        raw = pick("3.1. Basic Subtitles", FILE_TYPES,
                    folder_glob_hint=f"Из папки берутся только {VIDEO_GLOB} верхнего уровня.")
        if raw is None:
            print("Отменено.")
            return

    videos = resolve(raw)
    if not videos:
        print("Ничего обрабатывать — не найдено ни одного видео.")
        return

    print(f"К обработке: {len(videos)} видео")
    for v in videos:
        print("  -", v)

    cp.run_batch(videos)   # не возвращается — статус-бар, затем концовка, os._exit()


if __name__ == "__main__":
    # 2026-09-11 (Saturni): любой РАННИЙ выход из main() — «Отменено»,
    # «Ничего обрабатывать» (например, папку уже переименовали/убрали из неё
    # видео после финализации), или необработанное исключение до старта
    # cp.run_batch() — раньше закрывал консоль МГНОВЕННО, ни разу не
    # дожидаясь клавиши. Настоящий батч (cp.run_batch()) сам не возвращается
    # и уже держит консоль до F/Enter при ошибке — это касается только
    # путей, которые до него не дошли. Пауза — только в интерактивном
    # режиме (двойной клик, без аргументов); headless-вызовы от Claude
    # (аргументы путей) не блокируются ожиданием ввода.
    _interactive = len(sys.argv) == 1
    try:
        main()
    except Exception:
        import traceback
        print("\n!!! НЕОЖИДАННАЯ ОШИБКА !!!\n")
        traceback.print_exc()
        if _interactive:
            input("\nНажми Enter, чтобы закрыть...")
        raise
    else:
        if _interactive:
            input("\nНажми Enter, чтобы закрыть...")
