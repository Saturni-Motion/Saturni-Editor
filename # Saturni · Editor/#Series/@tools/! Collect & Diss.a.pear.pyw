# -*- coding: utf-8 -*-
"""! Collect & Diss.a.pear — копирует все .srt из папки уровнем выше в папку, где лежит сам
скрипт, и при успехе удаляет себя. С 2026-10-07 НЕ раскладывается по папкам: лежит в @tools
на стоянке. Финалы для разбора Claude сам копирует из папок серий в
#analysis/(!) Subtitles-ДД.ММ/<Проект>/<Серия>/3. Revised & Finalized (см. #analysis-subtitles.md)."""
import os, sys, shutil, ctypes

def _err(msg):
    ctypes.windll.user32.MessageBoxW(0, msg, "! Collect & Diss.a.pear", 0x10)

try:
    here = os.path.dirname(os.path.abspath(__file__))
    video_dir = os.path.dirname(here)
    srt = [e.path for e in os.scandir(video_dir)
           if e.is_file() and e.name.lower().endswith(".srt")]
    if not srt:
        _err("В папке с видео нет ни одного .srt:\n" + video_dir)
        sys.exit(1)
    for f in srt:
        shutil.copy2(f, os.path.join(here, os.path.basename(f)))
    try:
        os.remove(os.path.abspath(__file__))
    except OSError:
        pass
except Exception as e:
    _err(f"{type(e).__name__}: {e}")
    sys.exit(1)
