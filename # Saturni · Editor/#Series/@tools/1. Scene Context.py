#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Визуально-звуковой контекст для ОДНОГО кандидата стадии 1 (см. 1. Highlights.md,
раздел «Файлы анализа»/«Визуальный+звуковой контекст»).

Проблема, которую это решает (Saturni, 2026-09-16): черновой текстовый прогон
(1. Transcribe Plain.py) режет серию на сегменты без всякого понятия о сцене — сосед по тексту
может оказаться совсем другой ситуацией, а дочитывать по одной сухой расшифровке, реально ли
это смешно, часто невозможно ("тут вообще хрен поймёшь по сухому тексту"). Полноценное
понимание сцены (та же локация/тот же разговор) — не дешёвая задача (см. инструкцию, обсуждение
про SED = просто детект склеек, а не сцен), поэтому этот скрипт НЕ пытается сам решить, где
сцена — вместо этого он даёт мне (Claude) сырьё, чтобы судить самому:

1. **Реальные склейки внутри диапазона кандидата** (PySceneDetect ContentDetector — та же
   библиотека и тот же принцип, что уже использует `4.1. VReframe-SED.py` для вертикалки; НЕ детект
   сцен, только детект резкой смены картинки) + кадр на каждую такую точку — визуальный якорь,
   по которому видно, сменилась ли обстановка/ракурс между двумя соседними по тексту репликами.
2. **Контур громкости вокала по каждому srt-сегменту** (Demucs-вокал — то же самое разделение,
   что и в основном пайплайне, просто ради разделения тут его не удаляем сразу) — дешёвый
   намёк на интонацию/энергию (смех, крик, ровный тон), без реальной диаризации.

Кэш склеек на весь эпизод — "<video-stem>__cuts.json" рядом с видео (ContentDetector-скан
всего файла занимает время сравнимое с 1. Visual Peaks.py; считается один раз на серию,
переиспользуется для всех кандидатов этой же серии).

Usage:
  python 1. Scene Context.py --video "D:\...\e8.mov" --srt "1. Богдан.srt" [--out-dir ...]
    [--pad-s 3] [--threshold 27.0]

--srt: srt-файл ОДНОГО кандидата (как в `1. Claude the Highlighter/<стем>/`) — диапазон
берётся как [первый старт, последний конец] этого файла, не нужно указывать вручную.

Output: печатает отчёт (склейки+кадры, сегменты+громкость) и пишет
"<имя srt без расширения>-context.md" рядом с srt (или в --out-dir), плюс кадры в
"<то же имя>_frames/".
"""
import argparse, json, os, re, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import importlib.util as _ilu
_TOOLS = os.path.dirname(os.path.abspath(__file__))


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


_sp = _tool("subtitles_pipeline", "3.1. Subtitles Pipeline.py")  # тот же audio prep
extract_audio, demucs_vocals = _sp.extract_audio, _sp.demucs_vocals

TS_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")


def load_srt(path):
    segs = []
    for block in open(path, encoding="utf-8").read().split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        m = TS_RE.search(lines[1])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text = " ".join(lines[2:]).strip()
        segs.append({"start": start, "end": end, "text": text})
    return segs


def ts(t):
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def real_cuts_for_video(video, threshold=27.0):
    """Полный скан видео на реальные склейки (PySceneDetect ContentDetector), кэшируется
    рядом с видео — один раз на серию, а не один раз на кандидата (кандидатов в серии обычно
    5-10, пересчитывать для каждого дорого и не нужно)."""
    cache = os.path.splitext(video)[0] + "__cuts.json"
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    from scenedetect import detect, ContentDetector
    print(f"  [scenedetect] полный скан {video} (один раз на серию, кэш -> {cache})...")
    scenes = detect(video, ContentDetector(threshold=threshold))
    cuts = [s[1].get_seconds() for s in scenes[:-1]] if scenes else []
    json.dump(cuts, open(cache, "w", encoding="utf-8"))
    return cuts


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return float(out.stdout.strip())


def grab_frame(video, t, out_path):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-ss", f"{max(0, t):.3f}", "-i", video,
                     "-frames:v", "1", "-q:v", "2", out_path], check=True)


def segment_rms_db(wav_path, start, end):
    dur = max(0.05, end - start)
    # encoding/errors explicit (2026-09-16 bug, found live): ffmpeg's stderr can contain a byte
    # that isn't valid under the default locale codec (cp1252 on this machine) — text=True alone
    # decodes with that default and the reader thread dies with UnicodeDecodeError, silently
    # leaving p.stderr as None (crashes re.search downstream). Same fix already used by
    # 3.1. Subtitles Pipeline.py's loudnorm measurement and 1. Visual Peaks.py's scene_scores().
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "info",
         "-ss", f"{max(0, start):.3f}", "-t", f"{dur:.3f}", "-i", wav_path,
         "-af", "astats=metadata=0", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"RMS level dB:\s*(-?[\d.]+)", p.stderr)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--srt", required=True, help="srt одного кандидата (диапазон берётся из него)")
    ap.add_argument("--out-dir", default=None, help="по умолчанию — папка srt-файла")
    ap.add_argument("--pad-s", type=float, default=3.0,
                     help="запас по краям диапазона для склеек/кадров (сек)")
    ap.add_argument("--threshold", type=float, default=27.0,
                     help="порог ContentDetector — тот же, что в 4.1. VReframe-SED.py")
    args = ap.parse_args()

    segs = load_srt(args.srt)
    if not segs:
        print("Пустой или нечитаемый srt — нечего анализировать.")
        sys.exit(1)
    duration = probe_duration(args.video)
    range_start = max(0.0, segs[0]["start"] - args.pad_s)
    # Клампить к реальной длительности видео (2026-09-16 bug, найден живьём): последний кандидат
    # серии может кончаться у самого края файла — +pad_s тогда просит кадр ПОСЛЕ конца видео,
    # ffmpeg падает (нет такого времени). max(0.05, ...) — не схлопнуть диапазон в отрицательную
    # длину на совсем коротком хвосте.
    range_end = min(segs[-1]["end"] + args.pad_s, max(segs[-1]["end"], duration - 0.05))

    srt_stem = os.path.splitext(os.path.basename(args.srt))[0]
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.srt))
    frames_dir = os.path.join(out_dir, srt_stem + "_frames")
    os.makedirs(frames_dir, exist_ok=True)

    # 1. Реальные склейки внутри диапазона + кадр на каждую (плюс кадр на старт/конец диапазона).
    print(f"[визуальный проход] {ts(range_start)} – {ts(range_end)}")
    all_cuts = real_cuts_for_video(args.video, threshold=args.threshold)
    in_range = [c for c in all_cuts if range_start <= c <= range_end]
    anchor_times = sorted(set([range_start] + in_range + [range_end]))

    frames = []
    for i, t in enumerate(anchor_times):
        fp = os.path.join(frames_dir, f"{i:02d}_{ts(t).replace(':', '-')}.jpg")
        grab_frame(args.video, t, fp)
        frames.append((t, fp))
    print(f"  реальных склеек в диапазоне: {len(in_range)}, кадров сохранено: {len(frames)}")

    # 2. Громкость вокала по каждому сегменту srt.
    print("[звуковой проход] Demucs — отделение вокала...")
    tmp_dir = os.path.join(out_dir, srt_stem + "_tmp_audio")
    os.makedirs(tmp_dir, exist_ok=True)
    slice_audio = os.path.join(tmp_dir, "slice.wav")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-ss", f"{range_start:.3f}", "-t", f"{range_end - range_start:.3f}",
                     "-i", args.video, "-vn", "-ac", "2", "-ar", "44100",
                     "-c:a", "pcm_s16le", slice_audio], check=True)
    vocals = demucs_vocals(slice_audio, os.path.join(tmp_dir, "demucs"))

    levels = []
    for s in segs:
        db = segment_rms_db(vocals, s["start"] - range_start, s["end"] - range_start)
        levels.append(db)
    known = [d for d in levels if d is not None]
    median = sorted(known)[len(known) // 2] if known else None

    def tag(db):
        if db is None or median is None:
            return ""
        if db >= median + 3:
            return "  [громче обычного]"
        if db <= median - 3:
            return "  [тише обычного]"
        return ""

    # Отчёт — и в консоль, и в файл рядом с srt (не только в чат — см. highlights-apply-immediately).
    lines = [f"# Визуально-звуковой контекст: {srt_stem}", ""]
    lines.append(f"Диапазон: {ts(range_start)} – {ts(range_end)}  "
                  f"(медиана громкости вокала: {median:.1f} dB)" if median is not None
                  else f"Диапазон: {ts(range_start)} – {ts(range_end)}")
    lines.append("")
    lines.append("## Сегменты (текст + громкость)")
    for s, db in zip(segs, levels):
        db_txt = f"{db:.1f} dB" if db is not None else "н/д"
        lines.append(f"- **{ts(s['start'])}–{ts(s['end'])}** ({db_txt}){tag(db)}  {s['text']}")
    lines.append("")
    lines.append("## Кадры (реальные склейки + границы диапазона)")
    for t, fp in frames:
        marker = " (склейка)" if range_start < t < range_end and t in in_range else ""
        lines.append(f"- {ts(t)}{marker} — `{os.path.relpath(fp, out_dir)}`")

    report_path = os.path.join(out_dir, f"{srt_stem}-context.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n" + "\n".join(lines))
    print(f"\nГотово. Отчёт: {report_path}")
    print(f"Кадры: {frames_dir}")


if __name__ == "__main__":
    main()
