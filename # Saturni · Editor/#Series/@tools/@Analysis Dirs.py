# -*- coding: utf-8 -*-
"""
@Analysis Dirs — где лежат папки разбора (Saturni, 2026-10-07).

Бэкапы этапов 1 и 3 больше НЕ кладутся в папки серий проекта. Они сразу создаются в
#analysis в папке-очереди:
    #analysis/(!) Subtitles-ДД.ММ/<Проект>/<Серия N>/1. Whisper One Word | 2. Claude the Manager | 3. Revised & Finalized
    #analysis/(!) Highlights-ДД.ММ (Жанр)/...
«(!)» значит «разбор ещё не проводился, на очереди». После разбора папка переименовывается
без «(!)» (см. @instructions/#analysis-subtitles.md / #analysis-highlights.md).

    queue_dir("Subtitles")                     -> путь к «(!) Subtitles-<сегодня>» (создаёт)
    series_rel(video)                          -> «<Проект>/<Серия N>» (две последние папки видео)
    backup_dir(video, "1. Whisper One Word")   -> папка бэкапа этого видео в сегодняшней очереди
    find_backup(video, "1. Whisper One Word")  -> самый свежий <стем>.srt этого видео в любой
                                                  папке Subtitles-* (в очереди или разобранной)
"""
import glob
import os
import time

ROOT = r"D:\@Hub\# Saturni · Editor\#Series\#analysis"
QUEUE = "(!) "
STAGE3 = ("1. Whisper One Word", "2. Claude the Manager", "3. Revised & Finalized")


def queue_dir(kind="Subtitles", suffix="", date=None, create=True):
    """«(!) <kind>-ДД.ММ[ <suffix>]». Уже разобранная папка той же даты не переиспользуется."""
    date = date or time.strftime("%d.%m")
    name = f"{QUEUE}{kind}-{date}" + (f" {suffix}" if suffix else "")
    path = os.path.join(ROOT, name)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def series_rel(video):
    d = os.path.dirname(os.path.abspath(video))
    return os.path.join(os.path.basename(os.path.dirname(d)), os.path.basename(d))


def backup_dir(video, which, kind="Subtitles", create=True):
    path = os.path.join(queue_dir(kind, create=create), series_rel(video), which)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def setup_stage3(video):
    """Три папки этапа 3 для этого видео в сегодняшней очереди."""
    for w in STAGE3:
        backup_dir(video, w)


def find_backup(video, which, kind="Subtitles"):
    stem = os.path.splitext(os.path.basename(video))[0]
    pat = os.path.join(glob.escape(ROOT), f"*{kind}-*", glob.escape(series_rel(video)), which, glob.escape(stem) + ".srt")
    hits = glob.glob(pat)
    return max(hits, key=os.path.getmtime) if hits else None
