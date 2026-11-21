#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@StatusBar.py — общий консольный статус-бар Saturni: ♥-полоски, оценка времени (est.),
ошибки без спама, полоска на панели задач и W/L-концовка (немое видео поверх экрана + mp3).

Подключение (из-за "@" в имени — по пути):
    spec = importlib.util.spec_from_file_location("status_bar", r"D:\\@Hub\\@ Saturni · Status Bar\\@StatusBar.py")

Скрипт наполняет `tasks` (менять под `lock`) и вызывает run(worker). Задача — словарь:
    name    имя файла целиком (расширение бар прячет сам, длинное режет "…")
    state   "pending" | "running" | "waiting" (ждёт общего второго прохода) | "done" | "error"
            | "notice" (закончена без ошибки, но с пометкой: «уже сделано» и т.п.; жёлтая строка, концовка W)
    prog    0..BAR_WIDTH — сколько ♥ (без точного % — по пройденным этапам)
    status  текст текущего этапа
    frac    0..1 — реальная доля работы (ffmpeg time=); самый точный источник est.
    weight  объём задачи (секунды медиа, размер) — опыт сделанных переносится на остальные
    dur     заранее известное время работы, сек (редко)
    t0      время старта (бар ставит сам)

Тексты статусов, ошибок и заметок:
    - Всегда с большой буквы (бар и сам поднимает первую букву).
    - Свои тексты — как можно короче и сразу понятные: "Encoding", "Already done", "OK — copied as is".
    - Имя не шире NAME_MAX, длинное режется в середине "…" (fit_name: хвост с датой/номером целый).
    - Статус занимает остаток строки, длинный режется "…" одним символом; полный текст ошибок и
      заметок всегда пишется в лог (LOG_DIR), поэтому сокращать на экране не страшно.
    - Ошибки и заметки с одинаковым текстом собираются в одну запись: "Val…04.20.39, 04.24.27  · текст",
      до GROUP_LINES строк имён (продолжение — отступ, статус не влез — своей строкой); сверху не больше
      PROBLEM_ROWS строк вместе с "+ N more…".
    - Заметка (task_notice) — победа: концовка W, окно ждёт Enter, чтобы заметки прочитать.

Удобнее всего так — исключение становится ошибкой этого файла, скрипт идёт дальше:
    for t in sb.tasks:
        with sb.task(t):
            обработать(t)

Без живой консоли (запуск агентом, пайп) — построчный лог вместо экрана, без концовки и
ожидания клавиш, код выхода 1/0. Любое непойманное исключение — одна жёлтая строка на экран,
полный текст в лог (LOG_DIR), окно не закрывается само.
"""

import os
import re
import sys
import math
import time
import threading
import traceback
import subprocess
import unicodedata
import multiprocessing
from contextlib import contextmanager



# region 💠 НАСТРОЙКИ


# --- Полоска ♥ -------------------------------------------------
BAR_WIDTH = 10               # сколько ♥ в полоске
NAME_GAP = 2                 # пробелов между самым длинным именем и ♥
NAME_MAX = 39                # имя не шире: "Valorant Example 2026.11.02-05.17.16(R)"; длиннее — fit_name
PROBLEM_ROWS = 6             # строк ошибок/заметок сверху, вместе с "+ N more…" (он — последняя из них)
GROUP_LINES = 2              # строк имён на запись группы (продолжение — просто отступ)
STATUS_MIN = 12              # статус ошибки/заметки в строке с именами — хотя бы столько знаков, иначе своей строкой
LINE_SPARE = 6               # свободных столбцов у правого края окна
REFRESH = 0.10               # перерисовка экрана, сек
BLINK_ON, BLINK_OFF = 1.0, 0.5   # ⛶ в шапке: видна / погашена, сек
DONE_HOLD = 0.25             # сек: законченная задача ещё видна с полной полоской ♥…
DONE_HOLD_FAST = 0.1         # …а если сама шла меньше DONE_HOLD — только столько
SMOOTH_STAGES = True         # задачи без точного % (по этапам): ♥ плавно ползут между этапами

# --- Очередь параллельных задач (лесенка) ----------------------
# Скорость задачи — по её месту среди идущих: первая SPEEDS[0], вторая SPEEDS[1], третья
# SPEEDS[2]; остальные стоят. Следующая стартует, когда у предыдущей START_AT работы.
# Закончилась первая — все сдвигаются: вторая становится первой и идёт на 100% и т.д.
# Неполная скорость — паузами: задача работает свою долю каждого такта SPEED_TACT.
#   - процессы (ffmpeg и т.п.): задаче поставить t["pid"] — бар сам ставит процесс на паузу;
#   - работа в самом Python: в цикле проверять sb.held(t) и ждать, пока True.
SPEEDS = (1.0, 0.75, 0.4)    # скорость первой, второй, третьей из идущих; дальше — 0
START_AT = 0.2               # доля работы предыдущей задачи, когда стартует следующая
SPEED_TACT = 0.4             # сек: такт «работа + пауза» для неполной скорости
START_GAP_TIMEOUT = 45       # сек: у предыдущей нет прогресса так долго — следующая стартует всё равно

# --- Цвета (HEX) ------------------------------------------------
HEART_HEX = "#C4C4C4"        # заполненное ♥
HEART_DIM_HEX = "#131313"    # пустое ♥ — почти не видно
HEART_GLOW = (0.1, 0.04, 0.01)   # свечение первых пустых ♥ после заполненных (доля яркости)
FRAME_HEX = "#9CFFBD"        # ⛶
ARROW_HEX = "#898FFF"        # →
STATUS_HEX = "#606060"       # текст этапа
EST_HEX = "#808080"          # "00:00 est."
DARK_HEX = "#404040"         # "1/5" и "*" в "est.*"
WARN_HEX = "#FFED80"         # ошибка, буква F, est. перескочил вверх
GOOD_HEX = "#9CFFBD"         # est. перескочил вниз

# --- Оценка времени (est.) --------------------------------------
DEFAULT_TASK_SECONDS = 60    # ничего не известно — столько на файл
HISTORY_RUNS = 10            # сколько прошлых прогонов скрипта учитывать
ETA_SAMPLE_SEC = 3.0         # окно медианы оценок; столько же спиннер на старте
ETA_SNAP_EVERY = 10          # сверять с расчётом на круглых значениях (00:50, 00:40…)
ETA_JUMP_UP_SEC = 10.0       # перескок вверх, если расчёт больше на столько…
ETA_JUMP_DOWN_SEC = 5.0      # …вниз — если меньше на столько
ETA_SIGN_SEC = 0.5           # сколько горит "•" после перескока
ETA_FINAL_SEC = 10.0         # меньше стольких секунд — ровный отсчёт до 00:00
ETA_TRUST_PROGRESS = 0.15    # с этой доли всей работы est. — целиком по общей скорости
ETA_REAL_MIN_FRAC = 0.05     # реальной доле файла верим с 5%
ETA_RECENT_SEC = 6.0         # окно «текущей скорости»
ETA_RECENT_FULL_SEC = 30.0   # остаток, с которого est. — только по текущей скорости
ETA_PAR_EXP_DEFAULT = 0.0    # как скорость файла зависит от числа идущих разом (без истории)

# --- Логи -------------------------------------------------------
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "# Saturni · Editor", "#Series", "@tools", "logs")
TIMINGS_FILE = os.path.join(LOG_DIR, "timings.jsonl")   # история времени прогонов

# --- Концовка W/L -----------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
VID_WIN = os.path.join(_HERE, "# W delivery.mp4")
VID_LOSE = os.path.join(_HERE, "# L delivery.mp4")
AUD_WIN = os.path.join(_HERE, "# W delivery.mp3")     # звук отдельно, видео играет немым
AUD_LOSE = os.path.join(_HERE, "# L delivery.mp3")
# Сдвиг видео относительно звука, сек — у каждой концовки свой. Буквы появляются раньше
# звука — увеличить; позже — уменьшить (в минус: тогда ждёт звук).
ENDING_VIDEO_DELAY_W = 0.6
ENDING_VIDEO_DELAY_L = 0.9
ENDING_WHITE = True          # анимация белым, а не исходным серым
ENDING_ALPHA_GAIN = 3.0      # плотность анимации: прозрачность = яркость кадра × это
ENDING_DIM = 0.15            # затемнение экрана под анимацией (0 — нет, 1 — чёрный)
ENDING_DIM_IN = 0.1         # сек: чёрное появляется к первым буквам
ENDING_DIM_OUT = 1.2         # сек: затухание после последних букв
ENDING_VISIBLE_LUMA = 40     # кадр «с буквами», если его самый яркий пиксель ярче этого
ENDING_MAX_LAG = 0.6         # сек: кадр опоздал больше — пропускается
FFMPEG_EXE = "ffmpeg"

# --- Панель задач -----------------------------------------------
TASKBAR_FX = True            # иконка скрипта и родная полоска прогресса Windows
TB_AUMID_PREFIX = "Saturni.StatusBar"

# endregion



# region 1️⃣ СИМВОЛЫ И ЦВЕТА


HEART = "\u2665"                      # ♥
SEP = "  "
ARROW = " \u2192 "                    # →
FRAME = "\u26F6"                      # ⛶
ETA_DOT = "•"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"               # вместо цифр est., пока нет реальных данных
SPINNER_STEP = 0.1


def _hex_ansi(hex_color):
    """"#RRGGBB" -> ANSI-цвет текста."""
    h = hex_color.lstrip("#")
    return f"\033[38;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


COLOR_HEART = _hex_ansi(HEART_HEX)
COLOR_HEART_DIM = _hex_ansi(HEART_DIM_HEX)
COLOR_FRAME = _hex_ansi(FRAME_HEX)
COLOR_ARROW = _hex_ansi(ARROW_HEX)
COLOR_STATUS = _hex_ansi(STATUS_HEX)
COLOR_EST = _hex_ansi(EST_HEX)
COLOR_EST_STAR = COLOR_COUNT = _hex_ansi(DARK_HEX)
COLOR_F = COLOR_UP = _hex_ansi(WARN_HEX)
COLOR_DOWN = _hex_ansi(GOOD_HEX)
COLOR_RESET = "\033[0m"


def _glow_hearts(empty, lit):
    """Пустые ♥ после заполненных: без заполненных — все тёмные, иначе градиент свечения."""
    if not lit:
        return COLOR_HEART_DIM + HEART * empty
    a = [int(HEART_HEX[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(HEART_DIM_HEX[i:i + 2], 16) for i in (1, 3, 5)]
    out = ""
    for k in range(empty):
        f = HEART_GLOW[k] if k < len(HEART_GLOW) else 0.0
        out += _hex_ansi("#" + "".join(f"{round(y + (x - y) * f):02X}" for x, y in zip(a, b))) + HEART
    return out

# endregion



# region 2️⃣ ЗАДАЧИ


lock = threading.Lock()
tasks = []      # список словарей задач

# До появления задач в шапке "Scanning…"; scan_progress(done, total) даёт "Scanning…  24%  12/50".
_scan = {"done": 0, "total": 0}


def scan_progress(done, total):
    """Report the scan before tasks exist, e.g. 12 of 50 track pages read. Thread-safe."""
    with lock:
        _scan["done"], _scan["total"] = max(0, int(done)), max(0, int(total))


_force_headless = None   # None = определить автоматически; True/False = принудительно


def set_headless(value=True):
    """Принудительно включить/выключить headless-режим (флаг --no-ui у лаунчеров)."""
    global _force_headless
    _force_headless = value


def is_interactive():
    """True, только если есть живая консоль и на вход, и на выход — обычный запуск двойным
    кликом. Пайп/редирект/запуск агентом -> False. Переопределяется set_headless() или
    переменной окружения SATURNI_HEADLESS=1."""
    if _force_headless is not None:
        return not _force_headless
    if os.environ.get("SATURNI_HEADLESS") == "1":
        return False
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def fmt_eta(sec):
    """mm:ss (h:mm:ss от часа); отрицательное — со знаком минус ("-00:42"); nan — "--:--"."""
    if sec != sec:
        return "--:--"
    sign = "-" if sec <= -1 else ""
    sec = abs(int(sec))
    if sec >= 3600:
        return f"{sign}{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
    return f"{sign}{sec // 60:02d}:{sec % 60:02d}"

# endregion



# region 3️⃣ ЛОГИ, ОШИБКИ, ОЧЕРЕДЬ


def log_path(name):
    """@tools/logs/<name>.log — один файл на скрипт, перезаписывается каждым прогоном."""
    safe = re.sub(r'[\\/:*?"<>|`]+', "_", name).strip(" ._") or "log"
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        pass
    return os.path.join(LOG_DIR, safe + ".log")


_logs_started = set()   # логи, в которые этот процесс уже писал (дальше — дописываем)


def write_log(name, text, append=None):
    """Пишет подробности (трейсбеки, сырой вывод) в лог-файл, а не в консоль. Ошибки
    записи глотает — лог не должен ронять сам скрипт. Возвращает путь или None.
    append=None (по умолчанию): первая запись за прогон начинает файл заново, следующие
    дописываются — общая страховка ошибок и сам скрипт не затирают друг друга."""
    path = log_path(name)
    if append is None:
        append = path in _logs_started
    try:
        with open(path, "a" if append else "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        _logs_started.add(path)
        return path
    except OSError:
        return None


_error_log = []   # (имя задачи, полный текст) — run() сам допишет их в лог скрипта


def _headline(text):
    """Одна строка причины из многострочного текста. Строка, кончающаяся на ":" ("FFmpeg
    render error (code N):"), сама ничего не говорит — к ней добавляется последняя строка
    хвоста до трейсбека (там причина: "No such file or directory" и т.п.)."""
    lines = [l.strip() for l in (text or "").splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        return "?"
    head = lines[0]
    if head.endswith(":"):
        tail = []
        for l in lines[1:]:
            if l.startswith("Traceback"):
                break
            tail.append(l)
        if tail:
            head = f"{head} {tail[-1]}"
    return head


def short_error(err):
    """Исключение или текст -> одна короткая строка причины. У исключения — тип, сообщение и
    где упало (файл.py:строка последнего кадра), чтобы сразу было понятно, куда смотреть."""
    if isinstance(err, BaseException):
        msg = _headline(str(err))
        head = f"{type(err).__name__}: {msg}" if msg != "?" else type(err).__name__
        tb = traceback.extract_tb(err.__traceback__) if err.__traceback__ else []
        if tb:
            head += f" ({os.path.basename(tb[-1].filename)}:{tb[-1].lineno})"
        return head
    return _headline(str(err) if err is not None else "")


def _full_error(err):
    if isinstance(err, BaseException):
        return "".join(traceback.format_exception(type(err), err, err.__traceback__))
    return str(err) if err is not None else "?"


def task_error(t, err):
    """Пометить задачу ошибкой: короткая причина в строке задачи, полный текст — в лог
    (run() запишет). Вызывать под lock."""
    t["state"] = "error"
    t["status"] = f"Error: {short_error(err)}"            # shown in full (may wrap)
    t.setdefault("t_done", None)
    if not t.get("t_done"):
        t["t_done"] = time.time()
    _error_log.append((t.get("name", "?"), _full_error(err)))


def task_notice(t, text):
    """Задача закончена без ошибки, но с пометкой (уже сделано, пропущено…): жёлтая строка с
    текстом остаётся на экране, концовка всё равно W, окно ждёт Enter. Вызывать под lock."""
    t["state"] = "notice"
    t["status"] = text
    _error_log.append((t.get("name", "?"), f"Notice: {text}"))   # полный текст — в лог
    if not t.get("t_done"):
        t["t_done"] = time.time()


def _progress_of(t):
    """Доля работы 0..1: реальная frac, иначе по ♥."""
    f = t.get("frac")
    return max(f if isinstance(f, (int, float)) else 0.0, (t.get("prog") or 0) / BAR_WIDTH)


def _speed(t):
    """Скорость задачи по её месту среди идущих (SPEEDS), дальше — 0. Вызывать под lock."""
    if t.get("state") != "running":
        return 1.0
    k = 0
    for x in tasks:
        if x is t:
            break
        if x["state"] == "running":
            k += 1
    return SPEEDS[k] if k < len(SPEEDS) else 0.0


def held(t):
    """True — сейчас такт паузы этой задачи (она идёт не на полной скорости). Без lock."""
    with lock:
        speed = _speed(t)
    return speed < 1.0 and (speed <= 0 or (time.time() % SPEED_TACT) / SPEED_TACT >= speed)


_paused = {}   # pid -> True, пока процесс на паузе


def _set_paused(pid, pause):
    try:
        import psutil
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
        for p in procs:
            p.suspend() if pause else p.resume()
        _paused[pid] = pause
    except Exception:
        _paused.pop(pid, None)


def _throttle_loop(stop):
    """Задачи с t["pid"]: скорость по лесенке паузами процесса, первой идущей — повышенный приоритет."""
    try:
        import psutil
    except ImportError:
        return
    prio = {}
    while not stop.wait(0.05):
        with lock:
            items = [(t, t.get("pid"), t["state"]) for t in tasks if t.get("pid")]
        lead_done = False
        for t, pid, st in items:
            pause = st == "running" and held(t)
            if _paused.get(pid, False) != pause:
                _set_paused(pid, pause)
            if st == "running":
                cls = psutil.NORMAL_PRIORITY_CLASS if lead_done else psutil.ABOVE_NORMAL_PRIORITY_CLASS
                lead_done = True
                if prio.get(pid) != cls:
                    try:
                        for p in [psutil.Process(pid)] + psutil.Process(pid).children(recursive=True):
                            p.nice(cls)
                        prio[pid] = cls
                    except Exception:
                        pass
    _release_all()


def _release_all():
    """Снять все паузы — перед выходом, иначе процесс остался бы замороженным."""
    for pid, paused in list(_paused.items()):
        if paused:
            _set_paused(pid, False)


def _wait_turn(t):
    """Ждать, пока у предыдущей задачи не будет START_AT работы (или она не закончится), но не
    дольше START_GAP_TIMEOUT. При обработке по очереди — без ожидания."""
    with lock:
        idx = next((i for i, x in enumerate(tasks) if x is t), 0)
    if idx == 0:
        return
    prev, since = tasks[idx - 1], time.time()
    while time.time() - since < START_GAP_TIMEOUT:
        with lock:
            st, done = prev["state"], _progress_of(prev)
        if st in ("done", "error", "notice", "waiting") or (st == "running" and done >= START_AT):
            return
        time.sleep(0.05)


@contextmanager
def task(t):
    """with sb.task(t): ... — задача running на время блока, done после, а исключение
    внутри превращается в ошибку ЭТОЙ задачи (скрипт идёт к следующему файлу). Параллельные
    задачи стартуют лесенкой (_wait_turn)."""
    _wait_turn(t)
    with lock:
        t["state"] = "running"
        if not t.get("t0"):
            t["t0"] = time.time()
    try:
        yield t
    except Exception as e:
        with lock:
            task_error(t, e)
    else:
        with lock:
            if t["state"] == "running":
                t["state"] = "done"
                t["t_done"] = time.time()


def _flush_error_log():
    if _error_log:
        write_log(script_name(), "\n\n".join(f"=== {n} ===\n{txt}" for n, txt in _error_log))
        _error_log.clear()


def _is_child_process():
    """Воркер пула (ProcessPoolExecutor / multiprocessing). При импорте в воркере
    parent_process() ещё None, а sys.argv уже подменён на путь скрипта родителя — опознаём по
    флагу запуска."""
    try:
        if multiprocessing.parent_process() is not None:
            return True
        if getattr(multiprocessing.current_process(), "_inheriting", False):
            return True
        return "--multiprocessing-fork" in getattr(sys, "orig_argv", ())
    except Exception:
        return False


def wait_close(prompt="Press Enter to close window…"):
    """Ждать Enter/F перед закрытием окна — только при живой консоли и в главном процессе
    (без консоли input() висел бы вечно, см. HEADLESS MODE)."""
    if _is_child_process() or not is_interactive():
        return
    sys.stdout.write(f"\n{ellipsis(prompt)}\n")
    sys.stdout.flush()
    try:
        import msvcrt
        while True:
            if msvcrt.kbhit() and msvcrt.getch() in (b"\r", b"\n", b"f", b"F"):
                return
            time.sleep(0.05)
    except ImportError:
        try:
            input()
        except EOFError:
            pass


def _yellow_arrow():
    """Жёлтая → как у проблемной задачи; без консоли (лог/пайп) — без ANSI-кодов."""
    return f"{COLOR_F}{ARROW}{COLOR_RESET}" if is_interactive() else ARROW.lstrip()


def fatal(message, code=1):
    """Ранний выход ДО статус-бара (нет файлов, не хватает исходников): одна жёлтая строка,
    ожидание Enter при живой консоли, код выхода."""
    sys.stdout.write(f"\n{_yellow_arrow()}{ellipsis(message)}\n")
    sys.stdout.flush()
    wait_close()
    sys.exit(code)


def _excepthook(exc_type, exc, tb):
    """Непойманное исключение в любом скрипте с `import status_bar`: одна строка на экран,
    трейсбек в лог, окно не закрывается само."""
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc, tb)
    try:
        if exc.__traceback__ is None:
            exc = exc.with_traceback(tb)
        path = write_log(script_name(), "=== непойманная ошибка ===\n" + _full_error(exc))
        if is_interactive():
            sys.stdout.write("\033[?25h")   # вернуть курсор, если статус-бар его спрятал
        sys.stdout.write(f"\n{_yellow_arrow()}Error: {short_error(exc)}\n")
        if path and not is_interactive():
            sys.stdout.write(f"   лог: {path}\n")
        sys.stdout.flush()
    except Exception:
        sys.__excepthook__(exc_type, exc, tb)
    wait_close("Press F to Pay Respects…")


def _thread_excepthook(args):
    # Исключение в постороннем потоке — только в лог (экран рисует главный поток).
    if args.exc_type is SystemExit:
        return
    write_log(script_name(), f"=== ошибка в потоке {getattr(args.thread, 'name', '?')} ===\n"
              + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


sys.excepthook = _excepthook
threading.excepthook = _thread_excepthook

# endregion



# region 4️⃣ ПАНЕЛЬ ЗАДАЧ


# Кнопка на панели задач — иконка самого скрипта, под ней родная полоска прогресса Windows.
# Windows Terminal не даёт сменить иконку окна, поэтому окну даётся своя AppUserModelID (своя
# кнопка): сначала иконка, потом AUMID. Ставится сразу при импорте, до тяжёлых модулей скрипта.
# Окно не трогаем, если в консоли сидит ещё и оболочка (запуск из вкладки cmd/PowerShell).
_TB_SHELLS = {"cmd.exe", "powershell.exe", "pwsh.exe", "bash.exe", "wsl.exe", "nu.exe", "far.exe"}
# hwnd — окно с кнопкой на панели (у Terminal — его окно); icons держим живыми, пока жив процесс
_tb = {"on": False, "last": None, "q": None, "hwnd": None, "icons": []}


def _tb_init():
    """При импорте модуля: иконка скрипта + своя группа на панели задач и поток полоски.
    Только обычный запуск с живой консолью в главном процессе (не headless, не дочерние
    ffmpeg-воркеры пула)."""
    if not (TASKBAR_FX and os.name == "nt") or not is_interactive() or _is_child_process():
        return
    try:
        hwnd = _tb_apply()
        if hwnd:
            _tb_start_progress(hwnd)
            _tb_progress(TB_NORMAL, 1)                   # сразу 1% при открытии
    except Exception:
        pass


def _tb_guid(s):
    import ctypes
    import struct
    h = s.replace("-", "")
    raw = struct.pack("<IHH", int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16)) + bytes.fromhex(h[16:])
    return (ctypes.c_ubyte * 16).from_buffer_copy(raw)


def _tb_com(fn):
    """fn в коротком потоке со своим CoInitialize: shell-функции без COM молча не работают, а
    главный поток скрипта COM-ом не трогаем."""
    import ctypes
    box = []

    def work():
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        try:
            box.append(fn())
        except Exception:
            pass
        finally:
            ole32.CoUninitialize()

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(2.0)
    return box[0] if box else None


def _tb_registry_icons(script, dpi):
    """Быстрый путь (~1 мс против ~40 мс у SHGetFileInfo): DefaultIcon типа файла из реестра
    (у .py — node.exe,0)."""
    import ctypes
    import winreg
    from ctypes import wintypes
    ext = os.path.splitext(script)[1].lower()
    prog = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice") as k:
            prog = winreg.QueryValueEx(k, "ProgId")[0]
    except OSError:
        pass
    try:
        if not prog:
            prog = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ext)
        loc = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, prog + r"\DefaultIcon")
    except OSError:
        return {}
    loc = os.path.expandvars(loc.strip())
    if loc.startswith('"'):
        path, rest = loc[1:].split('"', 1)
        index = rest.lstrip(", ")
    else:
        path, _, index = loc.rpartition(",") if "," in loc else (loc, "", "0")
    try:
        index = int(index or 0)
    except ValueError:
        index = 0
    if "%1" in loc or not os.path.isfile(path):     # %1 — иконка у каждого файла своя
        return {}
    icons = {}
    for kind, px in ((1, 32), (0, 16)):             # ICON_BIG, ICON_SMALL
        ico = wintypes.HICON()
        size = round(px * dpi / 96)
        if ctypes.windll.user32.PrivateExtractIconsW(path, index, size, size, ctypes.byref(ico), None, 1, 0) >= 1 and ico.value:
            icons[kind] = ico.value
    return icons


def _tb_shell_icons(script):
    """Тот же значок через SHGetFileInfo — ровно как в Проводнике (если тип файла рисует иконку
    обработчиком и в реестре готового пути нет)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                    ("dwAttributes", wintypes.DWORD), ("szDisplayName", ctypes.c_wchar * 260),
                    ("szTypeName", ctypes.c_wchar * 80)]

    get = ctypes.windll.shell32.SHGetFileInfoW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
    get.restype = ctypes.c_size_t
    icons = {}
    for kind, flags in ((1, 0x100), (0, 0x101)):    # SHGFI_ICON | LARGEICON / SMALLICON
        sfi = SHFILEINFOW()
        if get(script, 0, ctypes.byref(sfi), ctypes.sizeof(sfi), flags) and sfi.hIcon:
            icons[kind] = sfi.hIcon
    return icons


def _tb_console_shared(k32):
    """В консоли сидит ещё и оболочка (запуск из открытой вкладки cmd / PowerShell)."""
    import ctypes
    from ctypes import wintypes
    arr = (wintypes.DWORD * 32)()
    n = k32.GetConsoleProcessList(arr, 32)
    for pid in arr[:min(n, 32)]:
        h = k32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        buf, size = ctypes.create_unicode_buffer(260), wintypes.DWORD(260)
        ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        k32.CloseHandle(h)
        if ok and os.path.basename(buf.value).lower() in _TB_SHELLS:
            return True
    return False


def _tb_set_aumid(hwnd, aumid):
    import ctypes
    from ctypes import wintypes

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("p", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", ctypes.c_ubyte * 16), ("pid", wintypes.DWORD)]

    def work():
        ps = ctypes.c_void_p()
        sh = ctypes.windll.shell32.SHGetPropertyStoreForWindow
        sh.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        if sh(hwnd, ctypes.byref(_tb_guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")), ctypes.byref(ps)) or not ps.value:
            return
        vt = ctypes.cast(ctypes.cast(ps, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vt[6])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
        buf = ctypes.create_unicode_buffer(aumid)
        pv = PROPVARIANT(vt=31, p=ctypes.cast(buf, ctypes.c_void_p))     # VT_LPWSTR
        key = PROPERTYKEY(_tb_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5)   # AppUserModel_ID
        set_value(ps, ctypes.byref(key), ctypes.byref(pv))
        release(ps)

    _tb_com(work)


def _tb_apply():
    """Заголовок = имя скрипта, иконка скрипта + своя группа на панели задач. Возвращает hwnd
    окна с кнопкой (для полоски) или None, если консоли нет."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GetConsoleWindow.restype = wintypes.HWND
    u32.GetWindow.restype = wintypes.HWND
    u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    con = k32.GetConsoleWindow()
    if not con:
        return None
    hwnd = u32.GetWindow(con, 4) or con              # GW_OWNER: у Terminal — его окно
    _tb["hwnd"] = hwnd
    if _tb_console_shared(k32):                      # иконка/заголовок остались бы там после выхода
        return hwnd
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not os.path.isfile(script):
        return hwnd
    # заголовок окна/вкладки — имя скрипта, а не "C:\WINDOWS\py.exe"
    k32.SetConsoleTitleW(os.path.splitext(os.path.basename(script))[0])
    try:
        dpi = u32.GetDpiForWindow(hwnd) or 96
    except Exception:
        dpi = 96
    # без запасной иконки: не нашлась — кнопка остаётся Terminal, это сразу видно
    icons = _tb_registry_icons(script, dpi) or _tb_com(lambda: _tb_shell_icons(script)) or {}
    u32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
                                        ctypes.c_ssize_t, wintypes.UINT, wintypes.UINT,
                                        ctypes.c_void_p]
    # Ждём, пока окно реально примет иконку (до 3 с, SMTO_NORMAL), и только потом AUMID:
    # если Terminal ещё занят созданием окна и WM_SETICON не успел, новая кнопка
    # появилась бы со стандартной иконкой и переключилась позже.
    ok_all = bool(icons)
    for kind, ico in icons.items():
        _tb["icons"].append(ico)
        ok = u32.SendMessageTimeoutW(hwnd, 0x80, kind, ico, 0x0, 3000, None)   # WM_SETICON
        ok_all = ok_all and bool(ok)
    # сначала иконка, потом AUMID: новая кнопка сразу появляется с нашей иконкой
    if ok_all and hwnd != con:
        _tb_set_aumid(hwnd, f"{TB_AUMID_PREFIX}.{os.getpid()}")
    return hwnd


TB_NONE, TB_BUSY, TB_NORMAL, TB_ERROR, TB_PAUSED = 0, 1, 2, 4, 8   # TBPF_*: 8 — жёлтая


def _tb_start_progress(hwnd):
    """Свой поток с ITaskbarList3 (COM-объект живёт в потоке, где создан): render() только
    кладёт состояние в очередь и не ждёт."""
    import queue
    q = queue.Queue()

    def work():
        import ctypes
        import uuid
        from ctypes import wintypes
        ctypes.windll.ole32.CoInitialize(None)
        g = lambda s: (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)
        tbl = ctypes.c_void_p()
        hr = ctypes.windll.ole32.CoCreateInstance(
            ctypes.byref(g("56FDF344-FD6D-11d0-958A-006097C9A090")), None, 1,
            ctypes.byref(g("ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf")), ctypes.byref(tbl))
        if hr or not tbl.value:
            _tb["on"] = False
            return
        vt = ctypes.cast(ctypes.cast(tbl, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vt[3])(tbl)              # HrInit
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND,
                                       ctypes.c_ulonglong, ctypes.c_ulonglong)(vt[9])
        set_state = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_int)(vt[10])
        cur = None
        while True:
            state, pct = q.get()
            try:
                # состояние — только при смене: повторный SetProgressState на каждый % давал
                # мерцание полоски
                if state != cur:
                    set_state(tbl, hwnd, state)
                    cur = state
                if state in (TB_NORMAL, TB_ERROR, TB_PAUSED):
                    set_value(tbl, hwnd, pct, 100)
            finally:
                q.task_done()

    _tb["q"] = q
    _tb["on"] = True
    threading.Thread(target=work, daemon=True, name="taskbar").start()


def _tb_progress(state, pct=0):
    """Родная полоска под кнопкой (TB_*); повторы того же состояния не шлются."""
    if not _tb["on"] or (state, pct) == _tb["last"]:
        return
    _tb["last"] = (state, pct)
    _tb["q"].put((state, pct))


def _tb_flush(timeout=0.5):
    """Дождаться, пока полоска применится — перед os._exit, иначе последнее состояние теряется."""
    q, end = _tb["q"], time.time() + timeout
    while q is not None and _tb["on"] and q.unfinished_tasks and time.time() < end:
        time.sleep(0.02)


def _tb_finish(failed):
    _tb_progress(TB_PAUSED, 100) if failed else _tb_progress(TB_NONE)   # LOSE — жёлтая
    _tb_flush()


_tb_init()

# endregion



# region 5️⃣ ОЦЕНКА ВРЕМЕНИ


def text_width(s):
    """Ширина строки в клетках консоли: комбинируемые символы (перечёркивание у ♥⃥) и
    вариационные селекторы — 0, широкие (CJK/эмодзи) — 2, остальное — 1."""
    w = 0
    for ch in s:
        if unicodedata.combining(ch) or ch in ("‍", "︎", "️"):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


_max_parallel = 0   # максимум задач, реально шедших одновременно
_config = {"script": None, "default_task_seconds": None, "real_progress": False}
_history_cache = {}  # script -> (сек на единицу weight | None, сек на файл | None)
# Показанное est. тикает секунда в секунду и сверяется с расчётом только на круглых значениях
# (00:50, 00:40…): перескок при заметной разнице, с цветной "•"; после 00:10 — ровный отсчёт.
_eta_show = {"anchor": None, "t": None, "real": False, "samples": [],
             "checked": 0.0, "sign": None, "sign_until": 0.0}


def _eta_reset(real=False):
    _eta_show.update(anchor=None, t=None, real=real, samples=[], sign=None, sign_until=0.0)
    _work_hist.clear()


def _eta_jump(st, diff, now):
    """Сдвинуть показанное на целое число секунд; при любом видимом сдвиге — "•"."""
    step = round(diff)
    if step == 0:
        return
    st["anchor"] += step
    st["sign"] = "+" if step > 0 else "-"
    st["sign_until"] = now + ETA_SIGN_SEC


def _eta_display(raw, now):
    """Показанное est.: тикает ровно, сверяется с расчётом raw только на круглых значениях."""
    st = _eta_show
    st["samples"].append((now, now + raw))            # храним прогноз МОМЕНТА окончания
    st["samples"] = [s for s in st["samples"] if s[0] > now - ETA_SAMPLE_SEC]
    if st["anchor"] is None:
        st.update(anchor=raw, t=now, checked=now, final=False, prev_int=int(raw))
        return raw
    shown = st["anchor"] - (now - st["t"])
    target = _median([f for t, f in st["samples"]]) - now
    if st.get("final"):
        # финиш: простой отсчёт до 00:00 и дальше висит на 00:00 — без сверок и подгонок.
        # Исключение: расчёт говорит, что осталось ещё больше ETA_FINAL_SEC сверх показанного
        # (файл явно застрял / был недооценён) — "•", перескок и выход из финиша.
        if now - st["checked"] >= ETA_SNAP_EVERY:
            st["checked"] = now
            if target - max(shown, 0.0) >= ETA_FINAL_SEC:
                _eta_jump(st, target - shown, now)
                st["final"] = False
                shown = st["anchor"] - (now - st["t"])
                st["prev_int"] = int(shown)
                return shown
        return max(shown, 0.0)
    cur = int(shown)
    if cur != st["prev_int"] and cur % ETA_SNAP_EVERY == 0 and cur >= ETA_FINAL_SEC:
        # на экране только что стало xx:x0 — сверка с расчётом, мелкая разница не в счёт
        st["checked"] = now
        diff = target - shown
        if diff > ETA_JUMP_UP_SEC or diff < -ETA_JUMP_DOWN_SEC:
            _eta_jump(st, diff, now)
    shown = st["anchor"] - (now - st["t"])
    st["prev_int"] = int(shown)
    if shown < ETA_FINAL_SEC:
        st["final"] = True                     # дальше — ровный отсчёт до 00:00
    return shown


def eta_sign(now=None):
    """"+" / "-" — est. только что перескочил вверх/вниз (горит ETA_SIGN_SEC), иначе None.
    На экране это "est.•" жёлтая/зелёная (_sign_mark)."""
    now = now or time.time()
    st = _eta_show
    return st["sign"] if st["sign"] and now < st["sign_until"] else None


def _sign_mark(sign):
    if sign == "+":
        return f"{COLOR_UP}{ETA_DOT}{COLOR_RESET}"
    if sign == "-":
        return f"{COLOR_DOWN}{ETA_DOT}{COLOR_RESET}"
    return ""


def configure(script=None, default_task_seconds=None, real_progress=None):
    """script — имя для истории времени (по умолчанию — имя запущенного .py);
    default_task_seconds — стартовая прикидка "сколько занимает один файл", пока нет ни
    завершённых в этом прогоне, ни истории прошлых прогонов;
    real_progress=True — скрипт сам даёт реальную долю (frac, ffmpeg): прикидки и история
    тогда не показываются вообще, до первых реальных данных est. = "--:--"."""
    if real_progress is not None:
        _config["real_progress"] = bool(real_progress)
    if script:
        _config["script"] = script
    if default_task_seconds:
        _config["default_task_seconds"] = float(default_task_seconds)


def script_name():
    if _config["script"]:
        return _config["script"]
    return os.path.splitext(os.path.basename(sys.argv[0] or "script"))[0] or "script"


def _weight(t):
    w = t.get("weight")
    return float(w) if isinstance(w, (int, float)) and w > 0 else None


def _task_seconds(t):
    """Сколько заняла задача (завершённая или ждущая второго прохода), иначе None.
    Штатно пропущенные (skipped — "уже вертикалка" и т.п., доли секунды) не считаются:
    иначе они занижали бы среднее время на файл."""
    if t.get("skipped"):
        return None
    end = t.get("t_wait") or (t.get("t_done") if t["state"] == "done" else None)
    if end and t.get("t0") and end >= t["t0"]:
        return end - t["t0"]
    return None


def _has_real(t):
    f = t.get("frac")
    return isinstance(f, (int, float)) or bool(t.get("dur"))


def _history(script):
    """(сек на единицу weight, сек на файл) по последним HISTORY_RUNS прогонам скрипта."""
    if script in _history_cache:
        return _history_cache[script]
    import json
    runs = []
    try:
        with open(TIMINGS_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("script") == script:
                    runs.append(rec)
    except OSError:
        pass
    per_file, per_weight = [], []
    for rec in runs[-HISTORY_RUNS:]:
        for fi in rec.get("files", []):
            if fi.get("state") not in ("done", "waiting") or not fi.get("seconds"):
                continue
            per_file.append(fi["seconds"])
            if fi.get("weight"):
                per_weight.append(fi["seconds"] / fi["weight"])
    # Медиана, не среднее: один сбойный файл (упал за 2с, завис на
    # 10 минут, прогон с повторами) не должен тянуть прогноз для всех остальных.
    result = (_median(per_weight), _median(per_file))
    _history_cache[script] = result
    return result


def _median(values):
    if not values:
        return None
    v = sorted(values)
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def _model(now):
    """Модель "время на файл": (сек на единицу weight | None, сек на файл). Источники по
    приоритету: завершённые в этом прогоне -> проекция по реальной доле идущих -> история
    прошлых прогонов -> стартовая прикидка скрипта -> DEFAULT_TASK_SECONDS."""
    per_file, per_weight = [], []
    for t in tasks:
        sec = _task_seconds(t)
        if sec is None:
            continue
        per_file.append(sec)
        w = _weight(t)
        if w:
            per_weight.append(sec / w)
    if per_file:
        # медиана по завершённым в этом прогоне — один выброс не сбивает прогноз остальных
        return _median(per_weight), _median(per_file)

    proj_w, proj_f = [], []
    for t in tasks:
        f = t.get("frac")
        if t["state"] == "running" and isinstance(f, (int, float)) and f >= ETA_REAL_MIN_FRAC and t.get("t0"):
            el = now - t["t0"]
            if el > 0:
                total = el / f
                proj_f.append(total)
                if _weight(t):
                    proj_w.append(total / _weight(t))
    if proj_f:
        return (sum(proj_w) / len(proj_w) if proj_w else None), sum(proj_f) / len(proj_f)

    h_rate, h_file = _history(script_name())
    if h_file:
        return h_rate, h_file
    return None, _config["default_task_seconds"] or DEFAULT_TASK_SECONDS


_work_hist = []        # (время, сделанный объём, сколько задач шло) за последние ETA_RECENT_SEC

# Скорость одного файла при n идущих разом: v(n) = S1 · n^(a−1). a = 1 — у каждого своя
# скорость, a = 0 — процессор общий (файлов меньше — каждый быстрее). a подбирается по истории.
_par_exp_cache = {}
_conc_hist = []        # (время, сколько задач шло) — точка при каждом изменении


def _par_exp(script):
    """Показатель a по прошлым прогонам скрипта, где все файлы шли разом (параллельность ≥
    числа файлов, ≥2 файлов): подбор по сетке 0..1 — моделируем, когда закончил бы каждый
    файл при данном a, масштаб скорости у каждого прогона свой (нагрузка на комп разная)."""
    if script in _par_exp_cache:
        return _par_exp_cache[script]
    import json
    runs = []
    try:
        with open(TIMINGS_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("script") != script or (rec.get("parallel") or 1) < rec.get("count", 0):
                    continue
                files = [(fi["weight"], fi["seconds"]) for fi in rec.get("files", [])
                         if fi.get("state") == "done" and fi.get("weight") and fi.get("seconds")]
                if len(files) >= 2 and len(files) == rec.get("count"):
                    runs.append(files)
    except OSError:
        pass
    runs = runs[-HISTORY_RUNS:]
    # без истории: ffmpeg-скрипты (real_progress) — процессор общий; остальные — как раньше
    best = ETA_PAR_EXP_DEFAULT if _config["real_progress"] else 1.0
    if len(runs) >= 2:
        best_err = None
        for k in range(21):
            a = k / 20
            err = 0.0
            for files in runs:
                fins = _sim_finishes([w for w, _ in files], 1.0, a)
                logs = [math.log(fi / s) for fi, (_, s) in zip(fins, files)]
                c = sum(logs) / len(logs)
                err += sum((x - c) ** 2 for x in logs)
            if best_err is None or err < best_err:
                best, best_err = a, err
    _par_exp_cache[script] = best
    return best


def _sim_finishes(works, s1, a):
    """Все файлы стартуют разом; момент окончания каждого при v(n) = s1·n^(a−1)."""
    rem = list(works)
    act = set(range(len(rem)))
    fin = [0.0] * len(rem)
    t = 0.0
    while act:
        v = s1 * len(act) ** (a - 1)
        m = min(rem[i] for i in act)
        t += m / v
        for i in list(act):
            rem[i] -= m
            if rem[i] <= 1e-9:
                fin[i] = t
                act.discard(i)
    return fin


def _sim_remaining(left_running, left_pending, s1, a, slots):
    """Сколько секунд до конца: идущие доделывают свой объём, ждущие встают на
    освободившиеся потоки (их slots); скорость файла зависит от того, сколько идёт разом."""
    active = [r for r in left_running if r > 0]
    pending = list(left_pending)
    t = 0.0
    while active or pending:
        while pending and len(active) < slots:
            active.append(pending.pop(0))
        v = s1 * len(active) ** (a - 1)
        m = min(active)
        t += m / v
        active = [r - m for r in active if r - m > 1e-9]
    return t


def _conc_track(now, n):
    if not _conc_hist or _conc_hist[-1][1] != n:
        _conc_hist.append((now, n))


def _conc_integral(t_from, now, a):
    """∫ n(t)^a dt от t_from до now — "сколько поточной работы" было бы при S1 = 1."""
    if not _conc_hist:
        return 0.0
    total = 0.0
    for i, (t, n) in enumerate(_conc_hist):
        lo = t_from if i == 0 else max(t, t_from)
        hi = _conc_hist[i + 1][0] if i + 1 < len(_conc_hist) else now
        if hi > lo and n > 0:
            total += (hi - lo) * n ** a
    return total


def _work_split():
    """Для est. по объёму: (сделано, всего, остатки идущих, остатки ждущих) в единицах weight,
    или None — если не у всех задач есть weight, нет ни одной реальной доли frac или идёт
    задача без frac (её сделанное неизвестно — общая скорость вышла бы заниженной)."""
    if not tasks or any(_weight(t) is None for t in tasks):
        return None
    if not any(isinstance(t.get("frac"), (int, float)) for t in tasks):
        return None
    if any(t["state"] == "running" and not isinstance(t.get("frac"), (int, float)) for t in tasks):
        return None
    total = done = 0.0
    left_running, left_pending = [], []
    for t in tasks:
        w, st = _weight(t), t["state"]
        f = t.get("frac")
        f = min(max(f, 0.0), 1.0) if isinstance(f, (int, float)) else 0.0
        if st in ("done", "waiting"):
            total += w
            done += w
        elif st in ("error", "notice"):        # упавшая больше не работает: её остаток — 0
            total += w * f
            done += w * f
        else:
            total += w
            done += w * f
            (left_running if st == "running" else left_pending).append(w * (1 - f))
    return done, total, left_running, left_pending


def _recent_eta(now):
    """Остаток по текущей скорости (последние ETA_RECENT_SEC) или None: средняя за прогон
    отстаёт, если рендер под конец ускорился или замедлился."""
    split = _work_split()
    if split is None:
        return None
    done, _, left_running, left_pending = split
    _work_hist.append((now, done, len(left_running)))
    while _work_hist and _work_hist[0][0] < now - ETA_RECENT_SEC:
        _work_hist.pop(0)
    t_old, d_old, _ = _work_hist[0]
    if now - t_old < ETA_RECENT_SEC / 2 or done <= d_old:
        return None
    a = _par_exp(script_name())
    # скорость одного потока: объём за окно / Σ dt · n^a
    unit = sum((_work_hist[i + 1][0] - _work_hist[i][0]) * max(1, _work_hist[i][2]) ** a
               for i in range(len(_work_hist) - 1))
    if unit <= 0:
        return None
    par = max(1, _max_parallel, len(left_running))
    return _sim_remaining(left_running, left_pending, (done - d_old) / unit, a, par)


def _throughput(now):
    """(остаток по общей скорости прогона, уверенность 0..1) или None. Скорость = весь
    сделанный объём / всё время с начала — копится, поэтому чем дольше прогон, тем ровнее."""
    split = _work_split()
    t0s = [t["t0"] for t in tasks if t.get("t0")]
    if split is None or not t0s:
        return None
    done, total, left_running, left_pending = split
    if total <= 0 or done <= 0 or now - min(t0s) < 5:
        return None
    a = _par_exp(script_name())
    unit = _conc_integral(min(t0s), now, a)
    if unit <= 0:
        return None
    par = max(1, _max_parallel, len(left_running))
    return (_sim_remaining(left_running, left_pending, done / unit, a, par),
            min(1.0, (done / total) / ETA_TRUST_PROGRESS))


def estimate_remaining(now=None):
    """(секунды до конца — в минус, если оценку перебрали; starred) или (None, False), когда
    незавершённых задач нет. starred — без реальных данных, время по модели «на файл».
    Источники: реальная доля файла -> общая скорость прогона -> время на файл (этот прогон,
    история в TIMINGS_FILE, прикидка скрипта). Вызывать под lock."""
    now = now or time.time()
    raw, starred = _estimate_raw(now)
    if raw is None:
        _eta_reset()
        return None, False
    # Первые реальные данные (ffmpeg уже идёт пару секунд / первый файл готов) — показываем их
    # сразу, без знака и без сверки со стартовой прикидкой (она может быть в разы мимо).
    real_now = any(_task_seconds(t) is not None or (
        t["state"] == "running" and isinstance(t.get("frac"), (int, float)) and t["frac"] >= ETA_REAL_MIN_FRAC
        and t.get("t0")) for t in tasks)
    if not real_now and _config["real_progress"]:
        return float("nan"), False             # реальных данных ещё нет — "--:-- est."
    # Первые ETA_SAMPLE_SEC после старта (и пока ничего не запущено) без реальных данных — тоже
    # спиннер: ещё не видно, сколько задач идёт параллельно, и прикидка "все по очереди"
    # показывала 02:09 вместо 00:30.
    t0s = [t["t0"] for t in tasks if t.get("t0")]
    if not real_now and (not t0s or now - min(t0s) < ETA_SAMPLE_SEC):
        return float("nan"), False
    if real_now and not _eta_show["real"]:
        _eta_reset(real=True)
    thr = _throughput(now)
    if thr is not None:
        thr_eta, trust = thr
        raw = thr_eta * trust + raw * (1 - trust)
    recent = _recent_eta(now)
    if recent is not None:
        # Чем ближе конец, тем больше веса текущей скорости: средняя за весь прогон ровная, но
        # отстаёт, когда рендер под конец ускорился/замедлился. С ETA_RECENT_FULL_SEC остатка и
        # меньше — только текущая; на длинном остатке её вес мал (est. остаётся спокойным).
        w = min(1.0, ETA_RECENT_FULL_SEC / max(recent, 1.0))
        raw = raw * (1 - w) + recent * w
    return _eta_display(raw, now), starred


def _estimate_raw(now):
    """Мгновенная (несглаженная) оценка: модель "время на файл" + реальные доли идущих."""
    global _max_parallel
    running = [t for t in tasks if t["state"] == "running"]
    _max_parallel = max(_max_parallel, len(running))
    _conc_track(now, len(running))
    rate_w, per_file = _model(now)

    def expected(t):
        if t.get("dur"):
            return t["dur"]
        w = _weight(t)
        return rate_w * w if (rate_w and w) else per_file

    left_running, left_pending = [], []
    for t in tasks:
        st = t["state"]
        if st == "running":
            el = now - t["t0"] if t.get("t0") else 0.0
            f = t.get("frac")
            if isinstance(f, (int, float)) and f >= ETA_REAL_MIN_FRAC and el > 0:
                left_running.append(el * (1 - min(f, 1.0)) / f)
            else:
                left_running.append(expected(t) - el)   # обратный отсчёт, может уйти в минус
        elif st == "pending":
            left_pending.append(expected(t))
    if not left_running and not left_pending:
        return None, False
    starred = not any(_has_real(t) for t in tasks)
    if not left_pending and all(r <= 0 for r in left_running):
        return max(left_running), starred      # все перебрали оценку — est. в минус
    # Раскладываем остатки по потокам, как пул: идущие доделывают своё, ждущие встают на
    # освободившийся поток. Остатки здесь — секунды при ТЕКУЩЕМ числе
    # идущих файлов; когда их станет меньше, каждый пойдёт быстрее (_par_exp, 2026-10-10).
    par = max(1, _max_parallel, len(left_running))
    a = _par_exp(script_name())
    n_now = max(1, len(running))
    return _sim_remaining(left_running, left_pending, n_now ** (1 - a), a, par), starred


def record_timings():
    """Дописывает итог прогона в @tools/logs/timings.jsonl — по ним потом усредняем время
    на файл и правим стартовые прикидки."""
    import json
    files = []
    with lock:
        for t in tasks:
            sec = _task_seconds(t)
            if sec is None and t["state"] == "error" and t.get("t0") and t.get("t_done"):
                sec = t["t_done"] - t["t0"]
            files.append({"name": t["name"], "state": "skipped" if t.get("skipped") else t["state"],
                          "weight": _weight(t),
                          "seconds": round(sec, 1) if sec is not None else None})
        t0s = [t["t0"] for t in tasks if t.get("t0")]
        ends = [t.get("t_done") or t.get("t_wait") for t in tasks
                if t.get("t_done") or t.get("t_wait")]
        # Параллельность — по реальному пересечению интервалов задач (в headless-режиме
        # estimate_remaining() не вызывается, и _max_parallel оставался 0).
        events = []
        for t in tasks:
            end = t.get("t_wait") or t.get("t_done")
            if t.get("t0") and end:
                events += [(t["t0"], 1), (end, -1)]
        cur = peak = 0
        for _, d in sorted(events, key=lambda e: (e[0], e[1])):
            cur += d
            peak = max(peak, cur)
        parallel = max(peak, _max_parallel, 1)
    if not files:
        return
    rec = {
        "script": script_name(),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(files),
        "done": sum(1 for f in files if f["state"] == "done"),
        "errors": sum(1 for f in files if f["state"] == "error"),
        "wall_seconds": round(max(ends) - min(t0s), 1) if (t0s and ends) else None,
        "parallel": parallel,
        "files": files,
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(TIMINGS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass

# endregion



# region 6️⃣ ЭКРАН


_NATURAL_RE = re.compile(r"(\d+)|(\D+)")


def natural_sort_key(s):
    """Ключ сортировки, где "2. X" раньше "10. X": sorted(items, key=natural_sort_key)."""
    return [(0, int(part)) if part.isdigit() else (1, part.lower())
            for part in _NATURAL_RE.findall(s) for part in part if part]


def _stamp_times(now):
    """Проставляет t0/t_wait/t_done по смене состояния, если вызывающий код не сделал
    этого сам — ETA не должен зависеть от аккуратности каждого потребителя."""
    for t in tasks:
        st = t["state"]
        if st in ("running", "waiting", "done") and not t.get("t0"):
            t["t0"] = now
        if st == "waiting" and not t.get("t_wait"):
            t["t_wait"] = now
        if st in ("done", "error", "notice") and not t.get("t_done"):
            t["t_done"] = now


# Строка идущей задачи помещается в одну строку окна: имя и этап режутся "…". Текст ошибки
# не режется никогда. Расширение файла в имени не показывается.


def console_cols() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 90


def display_name(name: str) -> str:
    """Task name without a trailing file extension (any kind, nothing hard-coded)."""
    base, ext = os.path.splitext(name)
    if base.strip() and 2 <= len(ext) <= 6 and ext[1:].isalnum():
        return base
    return name


def fit(text: str, limit: int) -> str:
    """Shorten text to `limit` display columns with "…"."""
    text = ellipsis(text)
    if text_width(text) <= limit:
        return text
    out = ""
    for ch in text:
        if text_width(out + ch) > limit - 1:
            break
        out += ch
    return out.rstrip() + "…"


def console_rows() -> int:
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 30


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def ellipsis(text: str) -> str:
    """"..." -> "…" одним символом."""
    return str(text).replace("...", "…")


def plain_line(text: str) -> str:
    """Text without ANSI colour codes, with all whitespace runs (line breaks too) -> one space."""
    return ellipsis(re.sub(r"\s+", " ", _ANSI_RE.sub("", str(text))).strip())


def _rows_of(line: str, cols: int) -> int:
    """Console rows a line takes (an error text may wrap)."""
    return max(1, -(-text_width(_ANSI_RE.sub("", line)) // max(1, cols)))


# Список не выше окна: иначе при перерисовке ушедшее вверх остаётся на экране. Не влезает —
# сначала идущие, потом ошибки, потом ждущие; остальное — строкой "+ N more…".
_KEEP_ORDER = {"running": 0, "waiting": 0, "error": 1, "notice": 1, "pending": 2}


def _fit_height(entries, max_rows, cols):
    """entries — (state, [строки], сколько задач). Не выше max_rows: сначала идущие, потом ждущие;
    остальное — строкой "+ N more…" (N — сколько задач спрятано)."""
    def rows(lines):
        return sum(_rows_of(l, cols) for l in lines)
    if sum(rows(ls) for _, ls, _ in entries) <= max_rows:
        return [l for _, ls, _ in entries for l in ls]
    budget = max_rows - 1                    # одна строка на "+ N more…"
    ranked = sorted(range(len(entries)), key=lambda i: (_KEEP_ORDER.get(entries[i][0], 2), i))
    keep = set()
    for i in ranked:
        h = rows(entries[i][1])
        if h <= budget:
            keep.add(i)
            budget -= h
    hidden = sum(n for i, (_, _, n) in enumerate(entries) if i not in keep)
    lines = [l for i, (_, ls, _) in enumerate(entries) if i in keep for l in ls]
    lines.append(_more_line(hidden))
    return lines


def _more_line(n):
    # под именами (они начинаются после "<стрелка> "), как ещё одна строка списка
    return " " * (len(ARROW) + 1) + f"{COLOR_STATUS}+ {n} more…{COLOR_RESET}"


def _shown_prog(t, now):
    """Сколько ♥ рисовать. С точной долей (frac) — как есть. По этапам — между рывками ♥ плавно
    ползут со скоростью прошлых этапов (до первого — по прикидке времени на файл), но не дальше
    чем на шаг прошлого этапа минус одно ♥ и никогда назад. Вызывать под lock."""
    real = max(0, min(BAR_WIDTH, int(t.get("prog") or 0)))
    if not SMOOTH_STAGES or isinstance(t.get("frac"), (int, float)) or t["state"] != "running":
        return real
    sm = t.setdefault("_smooth", {"real": 0, "since": t.get("t0") or now, "step": 0, "shown": 0})
    if real != sm["real"]:                       # новый этап: запомнить шаг и момент
        if real > sm["real"]:
            sm["step"] = real - sm["real"]
        sm["real"], sm["since"] = real, now
    start = t.get("t0") or now
    if real > 0 and sm["since"] > start:
        per_heart = (sm["since"] - start) / real             # по прошлым этапам
    else:
        per_heart = (_model(now)[1] or DEFAULT_TASK_SECONDS) / BAR_WIDTH   # прикидка
    ahead = (now - sm["since"]) / per_heart if per_heart > 0 else 0
    cap = real + max(0, (sm["step"] or 3) - 1)               # не обгонять следующий этап
    shown = min(cap, BAR_WIDTH - 1, real + int(ahead))
    sm["shown"] = max(sm["shown"], real, shown)
    return min(BAR_WIDTH, sm["shown"])


def _holding(t, now):
    """Законченная задача ещё показывается с полной полоской: DONE_HOLD, а если сама шла
    меньше DONE_HOLD — DONE_HOLD_FAST."""
    end, start = t.get("t_done"), t.get("t0")
    if t["state"] != "done" or not end:
        return False
    hold = DONE_HOLD if (start and end - start >= DONE_HOLD) else DONE_HOLD_FAST
    return now - end < hold


def fit_name(name, limit=NAME_MAX):
    """Имя не шире limit. Хвост с цифрами (дата, номер: "2026.11.02-05.17.16(R)") остаётся целым,
    режутся слова перед ним, по границе слова, где можно: "Valorant Bigname…2026.11.02-05.17.16(R)".
    Нет такого хвоста или он сам длинный — режется середина."""
    if text_width(name) <= limit:
        return name
    m = re.search(r"\S*\d\S*$", name)
    tail = m.group(0) if m else ""
    if tail and text_width(tail) <= limit - 4:
        head = name[:m.start()].rstrip()
        room = limit - text_width(tail) - 1
        cut = head
        while text_width(cut) > room:
            cut = cut[:-1]
        if cut != head and head[len(cut)] != " " and " " in cut.strip():
            cut = cut.rstrip().rsplit(" ", 1)[0]     # не рвать слово посередине
        return cut.rstrip() + "…" + tail
    half = (limit - 1) // 2
    head = name
    while text_width(head) > limit - 1 - half:
        head = head[:-1]
    return head + "…" + name[-half:]


def _cap(text):
    """Статус всегда с большой буквы."""
    text = str(text)
    return text[:1].upper() + text[1:]


def _group_items(names):
    """Имена одной группы без общего начала и конца: ("Val…", ["04.20.39", "04.24.27"]).
    Общее начало режется по " ", "-" или "_", общий конец — с первого знака не буквы и не цифры ("(R)")."""
    pre = os.path.commonprefix(names)
    pre = pre[:max(pre.rfind(c) for c in " -_") + 1]
    suf = os.path.commonprefix([n[::-1] for n in names])[::-1]
    suf = suf[next((k for k, ch in enumerate(suf) if not ch.isalnum()), len(suf)):]
    items = [n[len(pre):len(n) - len(suf)] or n for n in names]
    lead = (pre.strip()[:3] + "…") if pre.strip() else ""
    return lead, items


def _group_lines(names, status, arrow, width):
    """Задачи с одним и тем же текстом ошибки/заметки — одна запись до GROUP_LINES строк:
    " →  Val…04.20.39, 04.24.27, …," / "    05.58.11  · Skipped: OK" (продолжение — просто отступ).
    Статус после имён — в той же строке, режется "…", но не короче STATUS_MIN; места меньше — своей
    строкой "    · текст". Статус целиком,
    если влезает, иначе режется "…"; имена, которые не влезли, — "…" (полный список — в логе)."""
    room = width - (len(ARROW) + 1)
    cont = " " * (len(ARROW) + 1)
    if len(names) == 1:                    # одно имя — целиком (до NAME_MAX), статус на остаток
        name = fit_name(names[0])
        status = fit(_cap(plain_line(status)), max(12, room - text_width(name) - 4))
        return [f"{arrow} {name}  {COLOR_STATUS}· {status}{COLOR_RESET}"]
    full = _cap(plain_line(status))
    min_tail = 4 + min(STATUS_MIN, text_width(full))      # "  · " + хотя бы STATUS_MIN знаков статуса
    lead, items = _group_items(names)
    rows, cur = [], lead
    for it in items:
        piece = it if cur in ("", lead) else ", " + it
        last_row = len(rows) == GROUP_LINES - 1
        if text_width(cur + piece) <= room - (min_tail + 1 if last_row else 1):   # +1 — под "," или "…"
            cur += piece
        elif last_row:
            cur += "…"
            break
        else:
            rows.append(cur + ",")
            cur = it
    rows.append(cur)
    out = [f"{arrow} {rows[0]}"] + [cont + r for r in rows[1:]]
    free = room - text_width(rows[-1]) - 4
    if free >= min(STATUS_MIN, text_width(full)):     # статус в той же строке, длинный — "…"
        out[-1] += f"  {COLOR_STATUS}· {fit(full, free)}{COLOR_RESET}"
    else:                                  # имена заняли всю строку — статус своей строкой
        out.append(f"{cont}{COLOR_STATUS}· {fit(full, room - 2)}{COLOR_RESET}")
    return out


def _task_lines(max_rows=None):
    """Строки задач.
    Сверху — ошибки и заметки: задачи с одинаковым текстом собраны в одну запись (_group_lines),
    не больше PROBLEM_ROWS строк, последняя из них — "+ N more…", если не влезло. Ниже — идущие и ждущие.
    Колонка ♥ одна на всех: самое длинное имя + NAME_GAP пробелов. Имя не шире NAME_MAX (fit_name),
    статус — на оставшееся место строки, длинный режется "…" одним символом; полный текст ошибок
    и заметок — в логе (LOG_DIR). Вызывать под lock."""
    cols = console_cols()
    width = cols - LINE_SPARE
    free = max(40, cols - (len(ARROW) + 1 + NAME_GAP + BAR_WIDTH + 3 + LINE_SPARE))
    name_max = min(NAME_MAX, int(free * 0.55))
    now = time.time()
    arrow_ok = f"{COLOR_ARROW}{ARROW}{COLOR_RESET}"
    arrow_bad = f"{COLOR_F}{ARROW}{COLOR_RESET}"   # проблемная задача — жёлтая, как "F"

    groups = {}                                    # (state, текст) -> имена, по порядку появления
    for t in tasks:
        if t["state"] in ("error", "notice"):
            key = (t["state"], plain_line(t.get("status", "")))
            groups.setdefault(key, []).append(display_name(t["name"]))
    blocks = [_group_lines(names, status, arrow_bad, width) for (st, status), names in groups.items()]
    sizes = [len(n) for n in groups.values()]
    problem_lines, hidden = [], 0
    if sum(len(b) for b in blocks) <= PROBLEM_ROWS:
        problem_lines = [l for b in blocks for l in b]
    else:                                  # не влезает — последняя из PROBLEM_ROWS строк "+ N more…"
        for b, n in zip(blocks, sizes):
            if not hidden and len(problem_lines) + len(b) <= PROBLEM_ROWS - 1:
                problem_lines += b
            else:
                hidden += n
        problem_lines.append(_more_line(hidden))

    rest = [t for t in tasks if t["state"] not in ("error", "notice")
            and not (t["state"] == "done" and not _holding(t, now))]
    names = [fit_name(display_name(t["name"]), name_max) for t in rest]
    name_w = max((text_width(n) for n in names), default=0)
    status_max = max(12, width - (len(ARROW) + 1 + name_w + NAME_GAP + BAR_WIDTH + 3))
    entries = []
    for t, name in zip(rest, names):
        st = t["state"]
        name_cell = name + " " * (name_w - text_width(name) + NAME_GAP)
        if st == "pending":                    # ещё не стартовала — только тёмные ♥
            bar = f"{COLOR_HEART_DIM}{HEART * BAR_WIDTH}{COLOR_RESET}"
        else:
            prog = BAR_WIDTH if st == "done" else _shown_prog(t, now)
            bar = f"{COLOR_HEART}{HEART * prog}{_glow_hearts(BAR_WIDTH - prog, prog)}{COLOR_RESET}"
        # этап виден у всех, кроме законченных: свой этап, а без него — что задача ждёт
        stage = t.get("status") or ("" if st == "done" else "В очереди")
        if st == "done" or not stage:
            line = f"{arrow_ok} {name_cell}{bar}".rstrip()
        else:
            line = f"{arrow_ok} {name_cell}{bar} {COLOR_STATUS}· {fit(_cap(stage), status_max)}{COLOR_RESET}"
        entries.append((st, [line], 1))
    if max_rows is None:
        return problem_lines + [l for _, ls, _ in entries for l in ls]
    left = max(2, max_rows - sum(_rows_of(l, cols) for l in problem_lines))
    return problem_lines + _fit_height(entries, left, cols)


def overall_percent():
    """% в шапке — сколько всей работы сделано, а не только целиком готовых файлов
   . Каждый файл — равная
    доля; у идущего берётся его реальная доля (frac), иначе ♥-прогресс (prog). Файл с
    ошибкой считается обработанным. 100% — только когда все задачи завершены. Вызывать под lock."""
    if not tasks:
        return 100
    total = 0.0
    for t in tasks:
        st = t["state"]
        if st in ("done", "waiting", "error", "notice"):
            total += 1.0
        elif st == "running":
            f = t.get("frac")
            if not isinstance(f, (int, float)):
                f = (t.get("prog") or 0) / BAR_WIDTH
            total += max(0.0, min(1.0, f))
    pct = int(total / len(tasks) * 100)
    if pct >= 100 and any(t["state"] in ("pending", "running") for t in tasks):
        pct = 99
    return pct


def render():
    """Крутится, пока не все задачи в tasks завершены (done/error).
    Ничего не знает о том, ЧТО именно считает прогресс — только читает
    поля state/prog/has_pct/status/frac/weight/dur/t0 из tasks."""
    while True:
        with lock:
            now = time.time()
            _stamp_times(now)
            total = len(tasks)
            # "waiting" (своя часть сделана, ждёт общего второго прохода) считается в Done —
            # иначе у 4.2. все 12 секвенций уже собраны, а шапка минутами врёт "0% (0/12)".
            done = sum(1 for t in tasks if t["state"] in ("done", "waiting", "notice"))

            pct = overall_percent()

            # моргание: BLINK_ON видна, BLINK_OFF погашена; the last frame (everything
            # done/error) always shows it — it used to freeze in the "off" phase
            finished = total > 0 and all(t["state"] in ("done", "error", "notice") for t in tasks)
            frame_visible = finished or now % (BLINK_ON + BLINK_OFF) < BLINK_ON
            frame_glyph = FRAME if frame_visible else " "
            frame_c = f"{COLOR_FRAME}{frame_glyph}{COLOR_RESET}"

            # total==0 значит задачи ЕЩЁ не пришли (например для @tools/@MJS Launcher.py —
            # окно между стартом процесса и первым событием "batch_start" от node) — а не
            # "0 из 0 сделано" (жалоба Saturni, 2026-09-11). "est." — всегда, пока есть
            # незавершённые; "est.*" — модель по файлам без реальных данных; перебор — в минус.
            if total == 0:
                header = f"\n {frame_c}  Scanning…"
                if _scan["total"]:
                    sp = min(100, _scan["done"] * 100 // _scan["total"])
                    header += f"{SEP}{sp}%{SEP}{COLOR_COUNT}{_scan['done']}/{_scan['total']}{COLOR_RESET}"
            else:
                # "Done: 5%  1/5": проценты без ведущего нуля, счёт — тёмный.
                header = f"\n {frame_c}  Done: {pct}%{SEP}{COLOR_COUNT}{done}/{total}{COLOR_RESET}"
                eta, starred = estimate_remaining(now)
                if eta is not None and eta == eta:
                    # "*" half as visible as "est." itself
                    star = f"{COLOR_EST_STAR}*" if starred else ""
                    header += f"{SEP}{COLOR_EST}{fmt_eta(eta)} est.{star}{COLOR_RESET}"
                    header += _sign_mark(eta_sign(now))
                elif eta is not None:
                    # nan — у скрипта с реальным прогрессом данных ещё нет (первые 5% файла):
                    # вместо цифр крутится спиннер "⠋⠋:⠋⠋ est.".
                    c = SPINNER[int(now / SPINNER_STEP) % len(SPINNER)]
                    header += f"{SEP}{COLOR_EST}{c}{c}:{c}{c} est.{COLOR_RESET}"
            lines = [header, ""]
            # header = 2 rows ("\n" + text), blank row, the final "\n", one spare row
            lines.extend(_task_lines(max_rows=max(3, console_rows() - 4)))

            out = "\n".join(lines)
            all_fin = (total > 0 and all(t["state"] in ("done", "error", "notice") for t in tasks)
                       and not any(_holding(t, now) for t in tasks))
            # пока идёт — всегда обычная (жёлтая — только итог LOSE, в _tb_finish), минимум 1%:
            # полоска видна с открытия окна, а не с первого процента
            _tb_progress(TB_NORMAL, max(1, pct) if total else 1)

        sys.stdout.write("\033[H\033[J" + out + "\n")
        sys.stdout.flush()

        if all_fin:
            return
        time.sleep(REFRESH)


def render_plain():
    """Headless-аналог render(): без ANSI и перерисовки экрана — одна строка на каждое
    РЕАЛЬНОЕ изменение (старт задачи, смена статуса, done/error), с временем от начала.
    Читает те же поля tasks по тому же контракту, выходит, когда всё done/error."""
    t_start = time.time()
    seen = {}            # idx -> (state, status), что уже напечатано
    last_total = -1
    while True:
        with lock:
            total = len(tasks)
            snapshot = [(i, t["name"], t["state"], t.get("status") or "") for i, t in enumerate(tasks)]
            done = sum(1 for t in tasks if t["state"] in ("done", "notice"))
            all_fin = total > 0 and all(t["state"] in ("done", "error", "notice") for t in tasks)
        stamp = f"[{fmt_eta(time.time() - t_start)}]"
        lines = []
        if total != last_total and total > 0:
            lines.append(f"{stamp} задач: {total}")
            last_total = total
        for i, name, state, status in snapshot:
            if state == "pending" or seen.get(i) == (state, status):
                continue
            seen[i] = (state, status)
            mark = {"running": "..", "waiting": "--", "done": "OK", "error": "!!", "notice": "i "}.get(state, state)
            lines.append(f"{stamp} {mark} {name}" + (f" · {status}" if status else ""))
        if all_fin:
            lines.append(f"{stamp} Done: {done}/{total}")
        if lines:
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
        if all_fin:
            return
        time.sleep(0.5)

# endregion



# region 7️⃣ ЗВУК КОНЦОВКИ


def play_audio(path):
    """Проигрывает mp3 (без видео). Основной путь — Windows MCI: измерено на
    реальных файлах, расхождение по времени ~0.2с. ffpyplayer для этого не
    годится: тест показал +1.2..1.8с СВЕРХ настоящей длины трека (стабильно
    "доигрывает" после конца), поэтому используется только как fallback,
    если MCI не смог открыть файл."""
    if not os.path.isfile(path):
        sys.stdout.write(f"\n[!] Аудио не найдено: {path}\n")
        sys.stdout.flush()
        return

    if _play_audio_mci(path):
        return

    try:
        _play_audio_ffpyplayer(path)
        return
    except Exception:
        pass

    sys.stdout.write("\n[!] Не удалось проиграть аудио; открываю в системном плеере.\n")
    sys.stdout.flush()
    try:
        os.startfile(path)
        time.sleep(3)
    except Exception:
        pass


def _play_audio_ffpyplayer(path):
    """Fallback. ffpyplayer иногда не шлёт 'eof' вовремя для чисто аудио-файлов
    и начинает "дублировать"/повторять хвост дорожки. Подстраховываемся
    таймером по известной длительности — что наступит раньше (eof или
    таймер), то и стопает."""
    from ffpyplayer.player import MediaPlayer
    player = MediaPlayer(path, ff_opts={"sync": "audio"})
    try:
        duration = None
        meta_deadline = time.time() + 2.0
        while time.time() < meta_deadline:
            duration = player.get_metadata().get("duration")
            if duration:
                break
            time.sleep(0.05)

        start = time.time()
        while True:
            if duration and (time.time() - start) >= duration + 0.3:
                break
            frame, val = player.get_frame()
            if val == "eof":
                break
            if frame is None:
                time.sleep(0.01)
                continue
            time.sleep(min(val, 0.1) if isinstance(val, float) and val > 0 else 0.01)
    finally:
        try:
            player.close_player()
        except Exception:
            pass


def _play_audio_mci(path):
    """Возвращает True, если удалось проиграть через MCI."""
    import ctypes
    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"statusbar_{os.getpid()}"

    def _cmd(command):
        buf = ctypes.create_unicode_buffer(256)
        err = mci(command, buf, len(buf), None)
        return err, buf.value

    err, _ = _cmd(f'open "{path}" alias {alias}')
    if err:
        err, _ = _cmd(f'open "{path}" type mpegvideo alias {alias}')
    if err:
        return False

    try:
        _cmd(f"play {alias} wait")   # блокирует до конца воспроизведения
    finally:
        _cmd(f"close {alias}")
    return True

# endregion



# region 8️⃣ КОНЦОВКА W/L


def spawn_ending(which):
    """Запускает воспроизведение видео+звука в отдельном процессе, полностью
    оторванном от текущей консоли (DETACHED_PROCESS + CREATE_BREAKAWAY_FROM_JOB),
    чтобы закрытие консоли не убило ролик вместе с ней."""
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    args = [sys.executable, os.path.abspath(__file__), "--play-ending", which]
    try:
        subprocess.Popen(args, creationflags=flags, close_fds=True,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    except OSError:
        # брейкэвей из job-объекта запрещён (редкие окружения) — пробуем без него
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, creationflags=flags, close_fds=True,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


def play_ending(video_path, audio_path, delay=0.0):
    """Немое видео (оверлей) + отдельный mp3. Звук стартует, когда видео готово к первому кадру
    (иначе при непрогретом кэше звук ушёл бы вперёд). delay > 0 — видео позже звука, < 0 — звук
    позже видео."""
    audio_thread_box = {}
    started = threading.Event()

    def start_audio():
        if started.is_set():
            return
        started.set()
        if delay < 0:
            time.sleep(-delay)
        if audio_path:
            th = threading.Thread(target=play_audio, args=(audio_path,), daemon=True)
            th.start()
            audio_thread_box["t"] = th

    if not video_path or not os.path.isfile(video_path):
        sys.stdout.write(f"\n[!] Видео не найдено: {video_path}\n")
        sys.stdout.flush()
        start_audio()
    else:
        try:
            _play_overlay(video_path, on_ready=start_audio, delay=max(0.0, delay))
        except Exception as e:
            sys.stdout.write(f"\n[!] Оверлей недоступен ({e}); открываю видео в системном плеере (со своим звуком).\n")
            sys.stdout.flush()
            start_audio()        # звук всё равно должен прозвучать
            try:
                os.startfile(video_path)
            except Exception:
                pass

    start_audio()   # подстраховка: если оверлей завершился раньше первого кадра

    audio_thread = audio_thread_box.get("t")
    if audio_thread is not None:
        audio_thread.join()      # чтобы звук не обрубался, если видео короче


def _find_ffmpeg():
    if os.path.isfile(FFMPEG_EXE):
        return FFMPEG_EXE
    from shutil import which
    return which(FFMPEG_EXE)


def _bake_alpha_video(path, sw, sh):
    """Один раз через ffmpeg: альфа = яркость × ENDING_ALPHA_GAIN, цвет премультиплицирован
    (белый или исходный), кадр под размер экрана. Кэш рядом с видео (*.bake_*.mov), пока
    исходник не менялся; в рантайме остаётся только копирование кадра."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    base = os.path.splitext(path)[0]
    cache = f"{base}.bake_{sw}x{sh}_luma_{ENDING_ALPHA_GAIN}{'_w' if ENDING_WHITE else ''}.mov"
    try:
        if os.path.getmtime(cache) >= os.path.getmtime(path):
            return cache
    except OSError:
        pass
    lut = f"lut=c0='min(255,val*{ENDING_ALPHA_GAIN})'"
    fit = (f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,"
           f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=black")
    if ENDING_WHITE:   # премультиплицированный белый: R=G=B=альфа
        vf = f"{fit},format=gray,{lut},split[c][a];[c]format=gbrp[c2];[c2][a]alphamerge,format=gbrap"
    else:
        vf = (f"{fit},split[c][g];[g]format=gray,{lut}[a];[c]format=gbrp[c2];"
              f"[c2][a]alphamerge,premultiply=inplace=1,format=gbrap")
    try:
        subprocess.run([ffmpeg, "-y", "-i", path, "-vf", vf, "-an", "-c:v", "qtrle", cache],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        try:
            os.remove(cache)
        except OSError:
            pass
        return None
    return cache


def _visible_span(path):
    """(первая, последняя) секунда, где в ролике есть что-то видимое; None — не удалось."""
    import json, re
    cache = os.path.splitext(path)[0] + ".span.json"
    try:
        if os.path.getmtime(cache) >= os.path.getmtime(path):
            d = json.load(open(cache, encoding="utf-8"))
            if d.get("luma") == ENDING_VISIBLE_LUMA:
                return d["first"], d["last"]
    except (OSError, ValueError, KeyError):
        pass
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        out = subprocess.run(
            [ffmpeg, "-v", "error", "-i", path, "-vf",
             "signalstats,metadata=print:key=lavfi.signalstats.YMAX:file=-", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return None
    t, vis = None, []
    for line in out.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"YMAX=([\d.]+)", line)
        if m and t is not None and float(m.group(1)) > ENDING_VISIBLE_LUMA:
            vis.append(t)
    if not vis:
        return None
    span = (vis[0], vis[-1] + 1 / 30)
    try:
        json.dump({"first": span[0], "last": span[1], "luma": ENDING_VISIBLE_LUMA},
                  open(cache, "w", encoding="utf-8"))
    except OSError:
        pass
    return span


def _frame_to_bgra(pil, np):
    """Запасной путь без запечённого файла: RGB-кадр -> премультиплицированный BGRA."""
    arr = np.asarray(pil, dtype=np.float32)
    alpha = np.clip((0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])
                    * ENDING_ALPHA_GAIN, 0, 255)
    premul = (np.repeat(alpha[..., None], 3, axis=2) if ENDING_WHITE
              else arr * (alpha[..., None] / 255.0))
    bgra = np.empty(arr.shape[:2] + (4,), dtype=np.uint8)
    bgra[..., 0], bgra[..., 1], bgra[..., 2] = premul[..., 2], premul[..., 1], premul[..., 0]
    bgra[..., 3] = alpha
    return bgra.tobytes()


def _play_overlay(path, on_ready=None, delay=0.0):
    """Видео на весь экран, без рамок, поверх рабочего стола.
    Попиксельная альфа через Win32 UpdateLayeredWindow — настоящий Screen
    по чёрному фону, без потери полупрозрачности."""
    import ctypes
    from ctypes import wintypes
    import numpy as np
    from PIL import Image
    from ffpyplayer.player import MediaPlayer

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    # --- корректные типы для хэндлов на 64-бит ---
    LRESULT = ctypes.c_ssize_t
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)

    WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
    WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00000008, 0x00000080
    ULW_ALPHA, VK_ESCAPE = 0x00000002, 0x1B

    hInst = kernel32.GetModuleHandleW(None)

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    def _wndproc(hwnd, msg, wp, lp):
        if msg == 0x0002:                       # WM_DESTROY
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    wndproc = WNDPROC(_wndproc)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    cls_name = f"StatusBarOverlay_{os.getpid()}"
    wc = WNDCLASS()
    wc.lpfnWndProc = wndproc
    wc.hInstance = hInst
    wc.lpszClassName = cls_name
    gdi32.GetStockObject.restype = wintypes.HGDIOBJ
    wc.hbrBackground = gdi32.GetStockObject(4)          # BLACK_BRUSH — фон окна затемнения

    user32.RegisterClassW.restype = wintypes.ATOM
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]

    user32.RegisterClassW(ctypes.byref(wc))

    # затемнение — отдельное окно ПОД анимацией (создано раньше -> ниже по z-порядку)
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_byte, wintypes.DWORD]
    dim_hwnd = None
    if ENDING_DIM > 0:
        dim_hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            cls_name, "overlay-dim", WS_POPUP | WS_VISIBLE,
            0, 0, sw, sh, None, None, hInst, None)
        user32.SetLayeredWindowAttributes(dim_hwnd, 0, 0, 2)   # LWA_ALPHA, сначала прозрачно
    dim_state = {"a": -1}

    def set_dim(level):
        if not dim_hwnd:
            return
        a = max(0, min(255, int(round(255 * ENDING_DIM * level))))
        if a != dim_state["a"]:
            dim_state["a"] = a
            user32.SetLayeredWindowAttributes(dim_hwnd, 0, a, 2)

    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        cls_name, "overlay", WS_POPUP | WS_VISIBLE,
        0, 0, sw, sh, None, None, hInst, None)

    screen_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = sw, -sh         # top-down DIB
    bmi.biPlanes, bmi.biBitCount = 1, 32
    bmi.biCompression = 0                       # BI_RGB

    ppv = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), 0, ctypes.byref(ppv), None, 0)
    old_obj = gdi32.SelectObject(mem_dc, hbmp)

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                    ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]

    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]

    blend = BLENDFUNCTION(0, 0, 255, 1)         # AC_SRC_OVER, AC_SRC_ALPHA
    pos = wintypes.POINT(0, 0)
    size = wintypes.SIZE(sw, sh)
    src = wintypes.POINT(0, 0)
    buf_len = sw * sh * 4

    # если получилось запечь альфа-канал через ffmpeg — декодируем сразу готовый
    # премультиплицированный BGRA под размер экрана, без математики на кадр
    baked = _bake_alpha_video(path, sw, sh)
    use_baked = baked is not None
    src_path = baked if use_baked else path
    out_fmt = "bgra" if use_baked else "rgb24"

    # "an": True -> не декодировать звук самого видео (звук идёт отдельным mp3)
    player = MediaPlayer(src_path, ff_opts={"out_fmt": out_fmt, "sync": "video", "an": True})
    msg = wintypes.MSG()

    if on_ready is not None:
        on_ready()      # декодер готов -> теперь можно стартовать отдельный звук

    t_start = None     # время (time.time()) показа самого первого кадра
    pts0 = None         # его pts, точка отсчёта видео-таймлайна
    t_dim0 = time.time()
    span = _visible_span(path)   # (первые, последние буквы) в секундах ролика
    duration = None

    def dim_level(now):
        """Чёрное: к первым буквам уже полностью, держится до последних, потом затухает."""
        if span is None:   # не смогли измерить — по длине файла, как раньше
            lvl = min(1.0, (now - t_dim0) / ENDING_DIM_IN) if ENDING_DIM_IN > 0 else 1.0
            if duration and t_start is not None:
                left = t_start + duration - now
                if left < ENDING_DIM_OUT:
                    lvl = min(lvl, max(0.0, left / ENDING_DIM_OUT))
            return lvl
        v = (now - t_start) if t_start is not None else 0.0   # время внутри ролика
        first, last = span
        if v < first:
            lvl = 1.0 - (first - v) / ENDING_DIM_IN if ENDING_DIM_IN > 0 else 1.0
        elif v <= last:
            lvl = 1.0
        else:
            lvl = 1.0 - (v - last) / ENDING_DIM_OUT if ENDING_DIM_OUT > 0 else 0.0
        return max(0.0, min(1.0, lvl))

    try:
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                if msg.message == 0x0012:      # WM_QUIT
                    raise StopIteration
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
                break

            if duration is None:
                try:
                    duration = float(player.get_metadata().get("duration") or 0) or None
                except Exception:
                    duration = None
            set_dim(dim_level(time.time()))
            if span is not None and t_start is not None and                     time.time() - t_start > span[1] + ENDING_DIM_OUT:
                break   # дальше в ролике только чёрное — закрываем, звук доиграет сам

            frame, val = player.get_frame()
            if val == "eof":
                break
            if frame is None:
                time.sleep(0.005)
                continue

            img, pts = frame
            now = time.time()
            if t_start is None:
                # сдвиг применяем только один раз, к точке отсчёта — иначе
                # он добавляется к каждому кадру и таймлайн никогда не
                # "догоняет" реальное время (видео тормозит до ~5-10 fps)
                t_start, pts0 = now + delay, pts
            target = t_start + (pts - pts0)
            lag = now - target

            if lag > ENDING_MAX_LAG:
                # сильно отстали от таймлайна — пропускаем кадр, а не
                # рендерим весь "хвост" рывком в конце ролика
                time.sleep(0.001)
                continue
            if lag < 0:
                time.sleep(-lag)

            w, h = img.get_size()
            data = bytes(img.to_bytearray()[0])

            if use_baked:
                # уже готовый премультиплицированный BGRA ровно под экран —
                # никакой обработки, чистый memcpy
                if (w, h) != (sw, sh) or len(data) < buf_len:
                    continue    # не должно происходить: baked-файл уже под этот экран
                raw = data
            else:
                try:
                    pil = Image.frombytes("RGB", (w, h), data)
                except ValueError:
                    continue

                if (w, h) != (sw, sh):
                    scale = min(sw / w, sh / h)
                    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                    pil = pil.resize((nw, nh), Image.BILINEAR)
                    canvas = Image.new("RGB", (sw, sh), (0, 0, 0))
                    canvas.paste(pil, ((sw - nw) // 2, (sh - nh) // 2))
                    pil = canvas

                raw = _frame_to_bgra(pil, np)

            ctypes.memmove(ppv, raw, min(len(raw), buf_len))
            user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(pos),
                                       ctypes.byref(size), mem_dc, ctypes.byref(src),
                                       0, ctypes.byref(blend), ULW_ALPHA)
    except StopIteration:
        pass
    finally:
        # затемнение досвечивает до нуля, если ролик кончился раньше расчёта
        if dim_hwnd and dim_state["a"] > 0:
            a0, t0 = dim_state["a"] / (255 * ENDING_DIM), time.time()
            fade = 0.35
            while time.time() - t0 < fade:
                set_dim(a0 * (1 - (time.time() - t0) / fade))
                time.sleep(0.01)
            set_dim(0)
        try:
            player.close_player()
        except Exception:
            pass
        gdi32.SelectObject(mem_dc, old_obj)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)
        user32.DestroyWindow(hwnd)
        if dim_hwnd:
            user32.DestroyWindow(dim_hwnd)
        user32.UnregisterClassW(cls_name, hInst)


def _prewarm_bakes():
    """Запекает оба варианта видео в фоне, пока крутится реальный прогресс —
    к моменту показа кэш обычно уже готов, и не приходится ждать ffmpeg
    прямо перед стартом звука/видео."""
    try:
        import ctypes
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        return
    for p in (VID_WIN, VID_LOSE):
        if p and os.path.isfile(p):
            _bake_alpha_video(p, sw, sh)

# endregion



# region 9️⃣ ЗАПУСК


def _safe_worker(worker):
    """Страховка run(): упал worker — его незавершённые задачи становятся ошибками с причиной
    (а не вечный экран "Scanning…"/♥ без движения); worker вернулся, а задачи так и не
    закончены — тоже ошибка. Задач ещё нет — строка с именем скрипта."""
    def wrapped():
        crash = None
        try:
            worker()
        except BaseException as e:   # noqa: BLE001 — любой сбой должен дойти до экрана
            crash = e
        with lock:
            if crash is not None and not tasks:
                tasks.append({"n": 1, "name": script_name(), "state": "pending",
                              "prog": 0, "status": "", "t0": None})
            for t in tasks:
                if t["state"] in ("pending", "running"):
                    task_error(t, crash if crash is not None else
                               "скрипт закончил работу, а этот файл так и не завершился")
            if not tasks:
                tasks.append({"n": 1, "name": script_name(), "state": "done",
                              "prog": 0, "status": "", "t0": None})
    return wrapped


def run(worker, on_done=None):
    """worker работает в отдельном потоке и наполняет/меняет `tasks`. run() рисует экран, пока
    все задачи не станут done/error, играет W/L-концовку и завершает процесс (os._exit —
    код после run() не выполнится; итоговую сводку класть в on_done(failed), он вызывается
    перед концовкой). Без живой консоли — построчный лог, без концовки, код выхода 1/0."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    worker = _safe_worker(worker)
    stop_throttle = threading.Event()
    threading.Thread(target=_throttle_loop, args=(stop_throttle,), daemon=True).start()

    if not is_interactive():
        threading.Thread(target=worker, daemon=True).start()
        render_plain()
        stop_throttle.set()
        _release_all()
        record_timings()
        _flush_error_log()
        failed = any(t["state"] == "error" for t in tasks)
        if on_done is not None:
            try:
                on_done(failed)
            except Exception as e:
                print(f"[!] on_done callback raised: {type(e).__name__}: {e}")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1 if failed else 0)

    os.system("")                       # включить ANSI-последовательности в Windows
    sys.stdout.write("\033[?25l")       # спрятать курсор

    threading.Thread(target=_prewarm_bakes, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()

    try:
        render()
    finally:
        stop_throttle.set()
        _release_all()
        sys.stdout.write("\033[?25h")   # вернуть курсор
        sys.stdout.flush()
    record_timings()
    _flush_error_log()

    failed = any(t["state"] == "error" for t in tasks)
    _tb_finish(failed)
    if on_done is not None:
        try:
            on_done(failed)
        except Exception as e:
            print(f"[!] on_done callback raised: {type(e).__name__}: {e}")
    time.sleep(0.4)

    if failed:
        sys.stdout.write(f"\nPress {COLOR_F}F{COLOR_RESET} to Pay Respects…\n")
        sys.stdout.flush()

        def _wait_key():
            # Enter ИЛИ F закрывают консоль в любой момент, не дожидаясь
            # конца видео/звука
            try:
                import msvcrt
                while True:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if ch in (b"\r", b"\n", b"f", b"F"):
                            break
                    time.sleep(0.05)
            except Exception:
                try:
                    input()
                except EOFError:
                    pass
            _tb_progress(TB_NONE)               # запуск из вкладки с оболочкой — не оставлять полоску
            _tb_flush()
            os._exit(0)

        threading.Thread(target=_wait_key, daemon=True).start()
        play_ending(VID_LOSE, AUD_LOSE, ENDING_VIDEO_DELAY_L)
        _wait_key()                      # видео/звук закончились -> просто ждём Enter/F дальше
    elif any(t["state"] == "notice" for t in tasks):
        spawn_ending("win")             # победа, но с пометками — окно ждёт F/Enter, чтобы их прочитать
        sys.stdout.write(f"\nPress {COLOR_F}F{COLOR_RESET} to Pay Respects…\n")
        sys.stdout.flush()
        try:
            import msvcrt
            while msvcrt.getch() not in (b"\r", b"\n", b"f", b"F"):
                pass
        except Exception:
            pass
        _tb_progress(TB_NONE)
        _tb_flush()
        os._exit(0)
    else:
        spawn_ending("win")             # ролик доиграет уже в отдельном процессе
        os._exit(0)                     # консоль закрывается сразу, не дожидаясь ролика

# endregion


if __name__ == "__main__":
    # скрытый режим: используется только spawn_ending() для отдельного,
    # оторванного от консоли процесса-плеера — сюда заходить руками не нужно
    if len(sys.argv) >= 3 and sys.argv[1] == "--play-ending":
        if sys.argv[2] == "win":
            play_ending(VID_WIN, AUD_WIN, ENDING_VIDEO_DELAY_W)
        else:
            play_ending(VID_LOSE, AUD_LOSE, ENDING_VIDEO_DELAY_L)
