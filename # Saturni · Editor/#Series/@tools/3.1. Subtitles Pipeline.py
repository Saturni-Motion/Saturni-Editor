#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Subtitles pipeline (stage 3) — mechanical part only.

For each input video:
  1. extract audio (ffmpeg) -> stereo 44.1k wav
  2. Demucs htdemucs --two-stems vocals, --overlap 0.5 -> vocals stem
  3. two-pass loudnorm (EBU R128) on the vocal, downmix mono 16k -> whisperx input
  4. WhisperX large-v3 (float16, fallback int8) -> word-level json
  5. emit words.json + draft.srt (auto-grouped) into temp, AND the raw
     one-word-per-cue srt (word_cues(), 1.2s cap) straight into the permanent
     backup folder "1. Whisper One Word" (since 2026-10-07 in #analysis/(!) Subtitles-DD.MM/<project>/<series>/, see @Analysis Dirs.py; Saturni, 2026-09-09
     — backup-folder convention, see 3. Subtitles.md). Bug fixed same
     day: word_cues() existed but was never actually called/written anywhere —
     the docstring claimed a "words.srt" that never got produced.

The human step after this: review draft.srt -> fix ё, hanging words, logical
errors, hallucinations -> write "<video stem>.srt" next to the video AND a
duplicate copy into "2. Claude the Manager" (in the #analysis queue folder,
done by hand, not by this script) -> delete temp.

Temp files go to --workdir (default: system temp), NEVER next to the video.
Usage:
  python 3.1. Subtitles Pipeline.py "D:\\path\\to\\video.mp4" [more videos...] --workdir "D:\\tmp"
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time, traceback

# Console owner (Saturni, 2026-09-11, see D:/@Hub/@ Saturni · Status Bar/@StatusBar.py): while a batch
# runs under the ♥-bar, per-step chatter ("$ ffmpeg ...", "[whisperx] OK", ...)
# would tear through the bar's own \033[H\033[J redraw. _log() is what every
# step below prints through; run_batch() flips _QUIET on for the duration and
# routes the same information into each task's "status" field instead. Direct
# CLI/import use of this module outside run_batch is unaffected (_QUIET stays
# False, _log behaves like plain print()).
_QUIET = False


def _analysis_dirs():
    """@Analysis Dirs.py — папки разбора в #analysis/(!) Subtitles-ДД.ММ (Saturni, 2026-10-07)."""
    import importlib.util as _ilu
    mod = sys.modules.get("analysis_dirs")
    if mod is None:
        spec = _ilu.spec_from_file_location("analysis_dirs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "@Analysis Dirs.py"))
        mod = sys.modules["analysis_dirs"] = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _log(msg):
    if not _QUIET:
        print(msg)


PUNCT_END = tuple(".?!…")
PUNCT_SOFT = tuple(",;:")
CAP = 1.5          # seconds: max on-screen time past speech when a long pause follows
PAUSE = 1.5        # seconds: what counts as a "long pause"
INTONATION_GAP = 0.6  # seconds: gap between words that forces a line break
MAX_WORDS = 4

# Function words that read badly as the LAST word of a multi-word cue (hanging
# preposition/conjunction — 3. Subtitles.md pattern #1, 2026-09-09).
# Shared with @tools/3.2. Auto Tune.py (3.2), which flags cues ending on one of
# these unless a real pause justifies it.
FUNC_WORDS = {"и", "а", "но", "в", "во", "на", "с", "со", "к", "ко", "у",
              "о", "об", "от", "до", "по", "за", "из", "не", "ни", "же",
              "бы", "ли", "то", "что", "как"}

HALLUCINATION_RE = re.compile(
    r"(субтитр|dimatorzok|редактор субтитров|продолжение следует|"
    r"спасибо за просмотр|подписывайтесь|amara\.org|корректор)",
    re.IGNORECASE,
)


def run(cmd, **kw):
    _log("  $ " + " ".join(str(c) for c in cmd))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               HF_HUB_DISABLE_SYMLINKS_WARNING="1")
    # While the ♥-bar owns the console (_QUIET), ffmpeg/Demucs/WhisperX's own
    # progress bars/logs would otherwise print straight to the terminal and
    # tear through render()'s \033[H\033[J redraw (the "мерцание" / stray-log
    # flicker Saturni saw, 2026-09-11) — swallow them; only our own _log()
    # text is meant to reach the screen while a batch is running.
    if _QUIET and "stdout" not in kw and "stderr" not in kw:
        kw["stdout"] = subprocess.DEVNULL
        kw["stderr"] = subprocess.DEVNULL
    return subprocess.run(cmd, check=True, env=env, **kw)


def ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def extract_audio(video, out_wav):
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", video, "-vn", "-ac", "2", "-ar", "44100",
         "-c:a", "pcm_s16le", out_wav])


def demucs_vocals(in_wav, out_dir):
    # GPU 4 ГБ: если параллельно открыты Premiere/Media Encoder/OBS, CUDA падает по памяти
    # (2026-09-24, 14 из 15 роликов упали) — тогда та же модель на процессоре.
    for dev in ("cuda", "cpu"):
        try:
            run(["demucs", "--two-stems", "vocals", "-n", "htdemucs",
                 "-d", dev, "--overlap", "0.5", "-o", out_dir, in_wav])
            break
        except subprocess.CalledProcessError:
            if dev == "cpu":
                raise
            _log("  [demucs cuda] FAILED (likely VRAM busy), retrying on cpu")
    stem = os.path.splitext(os.path.basename(in_wav))[0]
    return os.path.join(out_dir, "htdemucs", stem, "vocals.wav")


# Two-pass EBU R128 loudness normalization (replaces the old flat +N dB boost,
# revision 3.1). Flat gain has no headroom awareness: measured on real
# material it drove a peak to exactly 0 dBFS (clipping edge) on one clip.
# loudnorm instead always lands at the same target loudness with a fixed,
# safe true-peak ceiling, and narrows the gap between quiet and loud speech
# (measured LRA 9.0->7.2 and 7.6->5.7 LU on two test clips) instead of
# shifting everything by the same fixed amount.
LOUDNORM_I = -16     # integrated loudness target, LUFS (typical spoken-word target)
LOUDNORM_TP = -1.5   # true-peak ceiling, dBTP (headroom against inter-sample peaks)
LOUDNORM_LRA = 11    # loudness range target, LU


def _loudnorm_measure(vocals_wav):
    """Pass 1: measure the input's loudness stats (JSON on stderr)."""
    cmd = ["ffmpeg", "-hide_banner", "-i", vocals_wav, "-af",
           f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json",
           "-f", "null", "-"]
    _log("  $ " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                        env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.DOTALL)
    if not m:
        raise RuntimeError("loudnorm pass 1: could not parse measured stats:\n" + r.stderr[-2000:])
    return json.loads(m.group(0))


def loudnorm_mono16k(vocals_wav, out_wav):
    """Two-pass loudnorm on the isolated vocal, downmixed to mono 16k for WhisperX."""
    stats = _loudnorm_measure(vocals_wav)
    af = (f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:"
          f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
          f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
          f"offset={stats['target_offset']}:linear=false,"
          "aformat=sample_rates=16000:channel_layouts=mono")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", vocals_wav, "-af", af, "-c:a", "pcm_s16le", out_wav])


# WhisperX hang guard (ported from tools/1. Transcribe Plain.py, real overnight
# incident 2026-09-07): a noisy/musical stretch can trigger a Whisper
# repetition-hallucination feedback loop — with condition_on_previous_text=True
# (whisperx default) the hallucinated phrase becomes the prompt for every later
# window and the run never terminates (8+h at 100% GPU on a ~2min clip).
#  - --condition_on_previous_text False breaks the loop.
#  - WHISPERX_TIMEOUT_S is a hard wall so a still-pathological file self-aborts
#    in ~25min instead of burning the whole night; on abort we fall through to
#    int8, then (if that also times out) the caller skips this one video.
WHISPERX_TIMEOUT_S = 1500


def whisperx(in_wav, out_dir):
    base = ["whisperx", in_wav, "--model", "large-v3", "--language", "ru",
            "--device", "cuda", "--batch_size", "4",
            "--vad_onset", "0.35",
            "--condition_on_previous_text", "False",
            "--output_format", "json", "--output_dir", out_dir,
            "--print_progress", "True"]
    stem = os.path.splitext(os.path.basename(in_wav))[0]
    out_json = os.path.join(out_dir, stem + ".json")
    # Последняя ступень — та же large-v3 на процессоре (int8), когда VRAM занят другими
    # программами (2026-09-24). Медленнее, но модель и качество те же.
    for ctype, dev in (("float16", "cuda"), ("int8", "cuda"), ("int8", "cpu")):
        cmd = [("cpu" if a == "cuda" and dev == "cpu" else a) for a in base]
        try:
            run(cmd + ["--compute_type", ctype], timeout=WHISPERX_TIMEOUT_S)
            if not os.path.exists(out_json):
                raise subprocess.CalledProcessError(0, cmd, "no json written")
            _log(f"  [whisperx {dev} compute_type={ctype}] OK")
            break
        except subprocess.CalledProcessError:
            _log(f"  [whisperx compute_type={ctype}] FAILED, trying next")
        except subprocess.TimeoutExpired:
            _log(f"  [whisperx compute_type={ctype}] TIMED OUT after "
                 f"{WHISPERX_TIMEOUT_S}s (likely repetition-hallucination loop), "
                 f"trying next")
    return out_json


def load_words(json_path):
    d = json.load(open(json_path, encoding="utf-8"))
    words = []
    for w in d.get("word_segments", []):
        if "start" not in w or "end" not in w:
            continue
        txt = str(w["word"]).strip()
        if not txt:
            continue
        words.append({"word": txt, "start": float(w["start"]),
                      "end": float(w["end"]), "score": w.get("score")})
    return words


def drop_trailing_hallucinations(words):
    """Remove trailing junk lines that sit far after real speech.

    BUG FIXED (2026-09-10, same class as tools/1. Transcribe Plain.py's 2026-09-08
    fix): the old body scanned `" ".join(kept[i:])` from i=0 upward — at i=0
    that string is the WHOLE transcript, which of course contains the trailing
    junk, so it matched on the first iteration and returned kept[:0], wiping
    every cue (empty srt) instead of just the tail. Fix: walk the cut point
    BACKWARD from the end and stop as soon as a word does NOT look like junk,
    so only the contiguous hallucinated run at the very end is removed."""
    kept = list(words)
    tail = kept[-6:]
    if not tail or not HALLUCINATION_RE.search(" ".join(x["word"] for x in tail)):
        return kept, []
    # Junk "sits far after real speech": look for the last silence gap >= 1.5s
    # within the final 15 words and treat the run after it as the tail. Bounded
    # and gap-gated on purpose — if there's no clean gap, leave it for the human
    # review pass rather than risk eating real speech (the old code's failure).
    lo = max(1, len(kept) - 15)
    cut = None
    for i in range(len(kept) - 1, lo - 1, -1):
        if kept[i]["start"] - kept[i - 1]["end"] >= 1.5:
            cut = i
            break
    if cut is None or not HALLUCINATION_RE.search(
            " ".join(x["word"] for x in kept[cut:])):
        _log("  [hallucination] trailing junk detected but no clean gap to cut "
             "at — left in place for human review")
        return kept, []
    removed = kept[cut:]
    _log("  [hallucination removed] " +
         repr(" ".join(x["word"] for x in removed)))
    return kept[:cut], removed


def word_cues(words):
    cues = []
    for i, w in enumerate(words):
        start, end = w["start"], w["end"]
        if end - start > CAP:      # single word never lasts >1.2s -> trim glued silence
            end = start + CAP
        nxt = words[i + 1]["start"] if i + 1 < len(words) else None
        if nxt is not None and end > nxt:
            end = nxt
        cues.append((start, end, w["word"]))
    if cues:
        cues[0] = (0.0, cues[0][1], cues[0][2])
    return cues


def assemble(words):
    """Rough auto-grouping into 2-4 word lines. Human review required after."""
    lines = []
    cur = []
    for i, w in enumerate(words):
        cur.append(w)
        tok = w["word"]
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap_next = (nxt["start"] - w["end"]) if nxt else 999
        brk = False
        if tok.endswith(PUNCT_END):
            brk = True
        elif tok.endswith(PUNCT_SOFT) and len(cur) >= 2:
            brk = True
        elif len(cur) >= MAX_WORDS:
            brk = True
        elif gap_next > INTONATION_GAP and len(cur) >= 2:
            brk = True
        if brk:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)

    # merge a lonely leading function word / single short word forward
    merged = []
    for ln in lines:
        if (len(ln) == 1 and ln[0]["word"].lower().strip(".,!?…;:") in FUNC_WORDS
                and merged):
            merged[-1].extend(ln)
        else:
            merged.append(ln)
    lines = merged

    cues = []
    for j, ln in enumerate(lines):
        start = ln[0]["start"]
        last = ln[-1]
        natural_end = last["end"]
        nxt_line = lines[j + 1] if j + 1 < len(lines) else None
        nxt_start = nxt_line[0]["start"] if nxt_line else None
        # 1.2s cap when a long pause follows
        if nxt_start is not None and (nxt_start - natural_end) > PAUSE:
            end = min(natural_end, last["start"] + CAP)
        elif nxt_start is None:
            end = min(natural_end, last["start"] + CAP)
        else:
            end = natural_end
        # butt to next line unless a real pause
        if nxt_start is not None and 0 <= (nxt_start - end) <= 0.35:
            end = nxt_start
        text = " ".join(x["word"] for x in ln)
        cues.append((start, end, text))
    if cues:
        cues[0] = (0.0, cues[0][1], cues[0][2])
    return cues


POWERSHELL_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


# DEAD CODE — kept only for the postmortem in the docstring. The launcher is now
# a self-contained ".pyw" written in setup_backup_folders(); there is no .ps1 and
# no .lnk any more (copy_srt_to_finalizer.ps1 was deleted 2026-09-10).
def create_lnk(lnk_path, target, working_dir, arguments=""):
    """Windows .lnk via PowerShell's WScript.Shell COM object — avoids adding
    pywin32/winshell just for this.

    BUG FIXED (2026-09-09, caught by live test before shipping, two rounds):
    a Cyrillic .lnk filename ("Собрать титры.lnk") reliably failed with
    `FileNotFoundException` on .Save() and left a corrupt zero-target .lnk
    behind. First guess (command-line ANSI round-trip via `-Command "..."`)
    was wrong — switching to a UTF-8-BOM temp .ps1 run with `-File` did NOT
    fix it either. Isolated with a direct A/B probe: an ASCII .lnk filename
    always succeeds, a Cyrillic one always fails, no matter how the script
    reaches PowerShell — WScript.Shell's CreateShortcut/.Save() itself can't
    handle non-ASCII in the shortcut's OWN file path (legacy COM/WSH
    limitation, unrelated to our script's encoding).

    Fix: create the .lnk under a throwaway ASCII name via COM, then rename
    it to the real (possibly Cyrillic) name with Python's own os.rename —
    Python uses the wide-char Windows API directly for that, no COM/ANSI
    involved, so Cyrillic there is completely fine."""
    ascii_name = "_tmp_shortcut.lnk"
    ascii_path = os.path.join(os.path.dirname(lnk_path), ascii_name)
    ps = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{ascii_path}')\n"
        f"$s.TargetPath = '{target}'\n"
        f"$s.Arguments = '{arguments}'\n"
        f"$s.WorkingDirectory = '{working_dir}'\n"
        f"$s.Save()\n"
    )
    fd, tmp_ps1 = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    try:
        with open(tmp_ps1, "w", encoding="utf-8-sig") as fh:
            fh.write(ps)
        run([POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_ps1])
    finally:
        os.remove(tmp_ps1)
    if os.path.exists(lnk_path):
        os.remove(lnk_path)
    os.rename(ascii_path, lnk_path)


def setup_backup_folders(video):
    """Три папки этапа 3 для видео — с 2026-10-07 НЕ рядом с видео, а в очереди разбора
    #analysis/(!) Subtitles-ДД.ММ/<Проект>/<Серия>/ (Saturni: в папках серий не должно быть
    файлов анализа). 1. Whisper One Word пишет этот скрипт, 2. Claude the Manager — сборка,
    3. Revised & Finalized наполняет Claude при разборе (копирует финалы Saturni из папки
    серии). Кнопки-.pyw больше не кладём: «! Collect & Diss.a.pear.pyw» лежит в @tools."""
    _analysis_dirs().setup_stage3(video)


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        for k, (a, b, t) in enumerate(cues, 1):
            fh.write(f"{k}\n{ts(a)} --> {ts(b)}\n{t}\n\n")


# 5 real stages per clip, spread evenly over status_bar.BAR_WIDTH=10 hearts
# (2 per stage) so run_batch()'s ♥-bar actually fills in as process() moves
# along, instead of sitting on "..." the whole time (Saturni, 2026-09-11).
PIPELINE_STAGES = ["extract", "demucs", "loudnorm", "whisperx", "assemble"]
STAGE_PROG = {name: (i + 1) * (10 // len(PIPELINE_STAGES))
              for i, name in enumerate(PIPELINE_STAGES)}


def gigaam_second(d, raw_dir, stem):
    """Второе мнение GigaAM-v3 (с 2026-10-29): расхождения с WhisperX -> "<stem> · GigaAM.txt"
    рядом с сырым пословным srt. Отдельное окружение ~/.cache/venv-asr; нет его или упало —
    титры всё равно собираются, только без подсказки."""
    here = os.path.dirname(os.path.abspath(__file__))
    py = os.path.join(os.path.expanduser("~"), ".cache", "venv-asr", "Scripts", "python.exe")
    wav, wj = os.path.join(d, "whisperx_in.wav"), os.path.join(d, "words.json")
    if not (os.path.exists(py) and os.path.exists(wav) and os.path.exists(wj)):
        _log("    [gigaam] пропущено: нет venv-asr или whisperx_in.wav")
        return
    out = os.path.join(raw_dir, f"{stem} · GigaAM.txt")
    try:
        r = subprocess.run([py, os.path.join(here, "3.1. GigaAM Second.py"), wav, wj, out],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        _log("    [gigaam] " + (r.stdout.strip() or r.stderr.strip()[-500:]))
    except Exception as e:
        _log(f"    [gigaam] ошибка: {e}")


def prepare(video, workroot, _st):
    """Первая половина ролика: ffmpeg → Demucs → loudnorm (всё до WhisperX). Возвращает ctx;
    ctx["resumed"] — words.json/draft.srt уже лежат в _tmp от прошлого прогона."""
    stem = os.path.splitext(os.path.basename(video))[0]
    safe = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", stem).strip("_") or "clip"
    d = os.path.join(workroot, safe)
    os.makedirs(d, exist_ok=True)
    _log(f"\n=== {video}\n    temp: {d}")
    ctx = {"video": video, "stem": stem, "d": d, "resumed": False,
           "normed": os.path.join(d, "whisperx_in.wav")}   # loudnorm mono 16k, WhisperX input

    # Resume guard (2026-09-10): if a previous run already got through the heavy
    # part (Demucs + WhisperX) for this clip, its words.json/draft.srt are still
    # in _tmp — reuse them and just re-emit the permanent backups. Lets a batch
    # that died on the trailing .lnk step be re-run without redoing GPU work.
    if os.path.exists(os.path.join(d, "words.json")) and os.path.exists(os.path.join(d, "draft.srt")):
        ctx["resumed"] = True
        return ctx

    audio = os.path.join(d, "audio.wav")           # for Demucs
    _st("Извлечение аудио (ffmpeg)…", STAGE_PROG["extract"])
    extract_audio(video, audio)
    _st("Demucs — отделение вокала от музыки…", STAGE_PROG["demucs"])
    vocals = demucs_vocals(audio, os.path.join(d, "demucs"))
    _st("Нормализация громкости (loudnorm)…", STAGE_PROG["loudnorm"])
    loudnorm_mono16k(vocals, ctx["normed"])
    return ctx


def finish(ctx, js, _st):
    """Вторая половина ролика: json WhisperX (None — резюме из words.json) → words.json,
    draft.srt, сырые пословные титры в «1. Whisper One Word», второе мнение GigaAM."""
    video, stem, d = ctx["video"], ctx["stem"], ctx["d"]
    if js is None:
        _st("Резюме — переиспользую words.json…", STAGE_PROG["whisperx"])
        _log("    [resume] words.json + draft.srt already present — skipping "
             "ffmpeg/Demucs/WhisperX, re-emitting backups only.")
        words = json.load(open(os.path.join(d, "words.json"), encoding="utf-8"))
    else:
        words = load_words(js)
        words, removed = drop_trailing_hallucinations(words)
        json.dump(words, open(os.path.join(d, "words.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        with open(os.path.join(d, "words.txt"), "w", encoding="utf-8") as fh:
            for i, w in enumerate(words):
                fh.write(f"{i:3} {w['start']:8.3f} {w['end']:8.3f} "
                         f"{w['end']-w['start']:6.3f}  {w['word']}\n")
        _st("Сборка чернового srt…", STAGE_PROG["assemble"])
        write_srt(assemble(words), os.path.join(d, "draft.srt"))

    # Permanent backups, not temp — three folders next to the video
    # (Saturni, 2026-09-09, see setup_backup_folders() docstring).
    setup_backup_folders(video)
    raw_dir = _analysis_dirs().backup_dir(video, "1. Whisper One Word")
    write_srt(word_cues(words), os.path.join(raw_dir, stem + ".srt"))
    _st("GigaAM — второе мнение…", STAGE_PROG["assemble"])
    gigaam_second(d, raw_dir, stem)

    _log(f"    words: {len(words)}  ->  {d}\\draft.srt  (REVIEW BY HUMAN)")
    _log(f"    raw per-word backup -> {raw_dir}\\{stem}.srt")
    return d


def whisperx_batch(ctxs, workroot):
    """Один запуск WhisperX на всю пачку (2026-10-29): CLI сам перебирает файлы, а large-v3,
    VAD и модель выравнивания грузит ОДИН раз, а не на каждый ролик. Параметры те же, что у
    whisperx(). Возвращает {индекс в ctxs: путь json}; кого нет — распознаётся по-старому."""
    bdir = os.path.join(workroot, "_whisperx_batch")
    os.makedirs(bdir, exist_ok=True)
    wavs = []
    for k, c in enumerate(ctxs):
        w = os.path.join(bdir, f"{k:03d}.wav")
        shutil.copyfile(c["normed"], w)
        wavs.append(w)
    base = ["whisperx", *wavs, "--model", "large-v3", "--language", "ru",
            "--device", "cuda", "--batch_size", "4",
            "--vad_onset", "0.35",
            "--condition_on_previous_text", "False",
            "--output_format", "json", "--output_dir", bdir,
            "--print_progress", "True"]
    done = {}
    for ctype, dev in (("float16", "cuda"), ("int8", "cuda"), ("int8", "cpu")):
        cmd = [("cpu" if a == "cuda" and dev == "cpu" else a) for a in base]
        try:
            run(cmd + ["--compute_type", ctype], timeout=WHISPERX_TIMEOUT_S * len(wavs))
        except subprocess.CalledProcessError:
            _log(f"  [whisperx batch compute_type={ctype}] FAILED, trying next")
            continue
        except subprocess.TimeoutExpired:
            _log(f"  [whisperx batch compute_type={ctype}] TIMED OUT, trying next")
            continue
        for k, c in enumerate(ctxs):
            src = os.path.join(bdir, f"{k:03d}.json")
            if os.path.exists(src):
                dst = os.path.join(c["d"], "whisperx_in.json")
                shutil.move(src, dst)
                done[k] = dst
        _log(f"  [whisperx batch {dev} compute_type={ctype}] OK: {len(done)}/{len(wavs)}")
        break
    shutil.rmtree(bdir, ignore_errors=True)
    return done


def process(video, workroot, status_cb=None):
    """workroot: a '_tmp' folder next to the video. Per-clip subdir inside it.
    Caller deletes workroot at the end. Один ролик целиком; пачку run_batch() гонит по
    фазам (prepare всех → whisperx_batch → finish каждого).

    status_cb(text, prog), if given, is called before/after each major step —
    used by run_batch() to drive a status_bar task's "status" text AND its
    ♥-bar fill (prog: 0..status_bar.BAR_WIDTH, out of PIPELINE_STAGES below).
    Optional and side-effect-free for callers that don't pass it (plain CLI
    use)."""
    def _st(text, prog=None):
        if status_cb:
            status_cb(text, prog)

    ctx = prepare(video, workroot, _st)
    if ctx["resumed"]:
        return finish(ctx, None, _st)
    _st("WhisperX — распознавание речи (large-v3)…", STAGE_PROG["whisperx"])
    return finish(ctx, whisperx(ctx["normed"], ctx["d"]), _st)


def _file_size(path):
    try:
        return os.path.getsize(path) or None
    except OSError:
        return None


def run_batch(videos, workdir=None):
    """Batch entry point used by both the CLI (main(), below) and the "3.1.
    Basic Subtitles" GUI launcher at the project root. Drives the whole
    batch through D:/@Hub/@ Saturni · Status Bar/@StatusBar.py: one ♥-bar task per video, per-step
    text (see process()'s status_cb calls) instead of scrolling prints, and
    the WIN/LOSE overlay ending once every video is done/error (2026-09-11,
    Saturni — see 3. Subtitles.md).

    One bad clip must not sink a 20+ video batch — same contract as before,
    just reported through the bar instead of a bare try/except loop.
    Returns the list of failed video paths (empty on full success)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
    sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
    if sb is None:
        _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
        sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(sb)

    def _display_name(v):
        # Просто имя без расширения — render() больше НЕ печатает "{n}. " перед
        # именем (2026-09-11), так что обрезать собственный ведущий "N. " файла
        # больше не нужно (раньше это делалось, чтобы не задваивалось "1. 1. Шило
        # на мило ` 1h.mp4" — сейчас без нумерации строки собственный номер файла
        # наоборот нужно оставлять, это и есть желаемое отображаемое имя).
        return os.path.splitext(os.path.basename(v))[0]

    # Натуральная сортировка ("2." раньше "10.") — на случай, если видео пришли
    # явным списком аргументов (headless), а не через уже отсортированный
    # glob() в "3.1. Basic Subtitles.py" (Saturni, 2026-09-11).
    videos = sorted(videos, key=lambda v: sb.natural_sort_key(os.path.basename(v)))
    # Прикидка на один ролик до первой готовой/истории прогонов (грубо, 2026-09-24).
    sb.configure(script="subtitles_pipeline", default_task_seconds=150)

    sb.tasks[:] = [
        # has_pct=True from the start: process() reports real stage progress
        # via status_cb (STAGE_PROG, 2 hearts per stage out of BAR_WIDTH=10),
        # so the bar actually fills in instead of sitting on "..." (2026-09-11).
        # weight = размер файла: опыт уже обработанных видео переносится на остальные
        # пропорционально их объёму (ETA, см. status_bar.py, 2026-09-24).
        {"n": i, "name": _display_name(v), "state": "pending",
         "has_pct": True, "prog": 0, "status": "",
         "weight": _file_size(v), "t0": None, "t_done": None}
        for i, v in enumerate(videos, 1)
    ]
    failed = []          # [(video, exception, traceback_str), ...]

    def _status(idx, text, prog):
        with sb.lock:
            sb.tasks[idx]["status"] = text
            if prog is not None:
                sb.tasks[idx]["prog"] = prog

    def worker():
        global _QUIET
        _QUIET = True
        def fail(i, e):   # one bad clip must not sink the batch
            tb = traceback.format_exc()
            with sb.lock:
                sb.tasks[i]["state"] = "error"
                sb.tasks[i]["status"] = f"Ошибка: {type(e).__name__}: {e}"[:160]
                sb.tasks[i]["t_done"] = time.time()
            failed.append((videos[i], e, tb))

        try:
            # Фаза 1 — звук всех роликов (ffmpeg → Demucs → loudnorm). EVERYTHING for a
            # clip inside the try — os.makedirs() used to sit outside it (2026-09-11 bug):
            # if it raised, the exception killed this whole daemon thread silently and
            # every remaining clip's task stayed stuck on "running" forever.
            ctxs = {}
            for i, v in enumerate(videos):
                with sb.lock:
                    sb.tasks[i]["state"] = "running"
                    sb.tasks[i]["t0"] = time.time()
                try:
                    root = workdir or os.path.join(os.path.dirname(os.path.abspath(v)), "_tmp")
                    os.makedirs(root, exist_ok=True)
                    ctxs[i] = prepare(v, root, lambda t, p, i=i: _status(i, t, p))
                    if not ctxs[i]["resumed"]:
                        _status(i, "Ждёт общего прогона WhisperX…", STAGE_PROG["loudnorm"])
                except Exception as e:
                    fail(i, e)

            # Фаза 2 — один запуск WhisperX на всех: модели грузятся один раз (2026-10-29).
            todo = [i for i, c in ctxs.items() if not c["resumed"]]
            jsons = {}
            if todo:
                for i in todo:
                    _status(i, f"WhisperX — общий прогон ({len(todo)} шт.)…", STAGE_PROG["whisperx"])
                try:
                    root = workdir or os.path.join(os.path.dirname(os.path.abspath(videos[todo[0]])), "_tmp")
                    got = whisperx_batch([ctxs[i] for i in todo], root)
                    jsons = {todo[k]: js for k, js in got.items()}
                except Exception as e:
                    _log(f"  [whisperx batch] ошибка, распознаю по одному: {e}")

            # Фаза 3 — каждый ролик: (не дал общий прогон json — WhisperX по-старому) → сборка.
            for i, c in ctxs.items():
                st = lambda t, p, i=i: _status(i, t, p)
                try:
                    js = None
                    if not c["resumed"]:
                        js = jsons.get(i)
                        if js is None:
                            st("WhisperX — распознавание речи (large-v3)…", STAGE_PROG["whisperx"])
                            js = whisperx(c["normed"], c["d"])
                    finish(c, js, st)
                    with sb.lock:
                        sb.tasks[i]["state"] = "done"
                        sb.tasks[i]["t_done"] = time.time()
                except Exception as e:
                    fail(i, e)
        finally:
            _QUIET = False

    def on_done(_had_failures):
        # На экране — только строки упавших видео (жёлтая стрелка + последняя ошибка);
        # полные трейсбеки — в @tools/logs/subtitles_pipeline.log (Saturni, 2026-09-24:
        # не спамить консоль при ошибках).
        if failed:
            sb.write_log("subtitles_pipeline", "\n\n".join(f"=== {v} ===\n{tb}" for v, e, tb in failed))
        if not sb.is_interactive():
            # Напоминания — для агента (headless-запуск), не для экрана Saturni.
            print("\nNOTE: delete the _tmp folder(s) after the final .srt files are written.")
            print('NOTE: after review, write "<stem>.srt" next to the video AND a copy into '
                  '"2. Claude the Manager" in #analysis/(!) Subtitles-DD.MM (see 3. Subtitles.md).')
            if failed:
                print(f"NOTE: {len(failed)} video(s) failed — tracebacks in "
                      f"{sb.log_path('subtitles_pipeline')}")

    sb.run(worker, on_done=on_done)   # does not return — os._exit() at the end
    return [v for v, _, _ in failed]   # unreachable, kept for callers that stub sb in tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--workdir", default=None,
                    help="temp root; default: '_tmp' next to each video")
    a = ap.parse_args()
    run_batch(a.videos, workdir=a.workdir)


if __name__ == "__main__":
    main()
