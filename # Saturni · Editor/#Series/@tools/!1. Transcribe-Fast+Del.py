"""Шаблон само-очищающегося скрипта для папки `2. Revised & Finalized` (см. 1. Highlights.md,
раздел «Файлы анализа»). Копия этого файла кладётся в каждую такую папку под тем же именем,
`!1. Transcribe-Fast+Del.py`, при создании стадии 1.

По запуску (Saturni сам, двойным кликом, из этой же папки):
1. Находит в СВОЕЙ папке все видео (финальные ролики, которые Saturni туда положил).
2. Прогоняет по ним `transcribe_plain.run_batch()` — тот же быстрый черновой прогон (без
   выравнивания, large-v3-turbo) и тот же ♥-статус-бар (D:/@Hub/@ Saturni · Status Bar/@StatusBar.py), что и у
   `3.1. Basic Subtitles.py`/`3.1. Subtitles Pipeline.py` — .srt пишется рядом с каждым видео.
3. Только если ВСЕ видео прошли без ошибок (см. `on_success` в `transcribe_plain.run_batch`,
   вызывается из WIN/LOSE-концовки статус-бара) — удаляет сами видеофайлы (srt уже содержит всё
   нужное для сверки таймингов) и в конце удаляет самого себя.

Если что-то упало — ни видео, ни этот скрипт не трогаются (сработает LOSE-концовка статус-бара
с полным traceback в консоли, как у остальных пакетных стадий).
"""
import os
import sys

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi"}
MODEL = "large-v3"  # тот же быстрый прогон, что и для основного srt серии (Вход и подготовка);
# large-v3 (не turbo) + int8, см. transcribe_plain.whisperx_plain() — 2026-09-16, после
# реального A/B-теста скорость сравнима с turbo, а декодер полный, не урезанный


def find_project_root(start):
    d = os.path.abspath(start)
    while True:
        candidate = os.path.join(d, "@tools", "1. Transcribe Plain.py")
        if os.path.isfile(candidate):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError("Не найден корень проекта (@tools/1. Transcribe Plain.py) выше по дереву")
        d = parent


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = find_project_root(here)
    tools_dir = os.path.join(root, "@tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import importlib.util as _ilu   # "1. Transcribe Plain.py": пробелы/точки в имени — грузим по пути
    _spec = _ilu.spec_from_file_location("transcribe_plain", os.path.join(tools_dir, "1. Transcribe Plain.py"))
    tp = sys.modules["transcribe_plain"] = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(tp)

    videos = [
        os.path.join(here, f) for f in os.listdir(here)
        if os.path.splitext(f)[1].lower() in VIDEO_EXT
    ]
    if not videos:
        print("Видео в этой папке не найдено, делать нечего.")
        input("\nНажми Enter, чтобы закрыть...")
        return

    self_path = os.path.abspath(__file__)

    def on_success(done_videos):
        print("\nВсё без ошибок. Удаляю видео...")
        for v in done_videos:
            os.remove(v)
            print(f"  удалено: {os.path.basename(v)}")
        print("\nУдаляю сам себя...")
        os.remove(self_path)

    tp.run_batch(videos, model=MODEL, on_success=on_success)
    # sb.run() внутри run_batch() заканчивается os._exit() — сюда управление
    # не возвращается ни при успехе, ни при ошибке; вся логика после прогона
    # живёт в on_success (см. transcribe_plain.run_batch docstring).


if __name__ == "__main__":
    main()
