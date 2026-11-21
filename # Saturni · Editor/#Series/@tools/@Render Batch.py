#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Render Batch.py — общий статус-бар (♥, est., концовка) для ffmpeg-скриптов рендера
"D:\\# Video\\#Поляна\\@Render\\#2Stage-*.py" (2026-10-01: раньше у каждого был свой tqdm —
"Done: 1/8 — 01:22" и "--> имя •••••••").

Скрипт оставляет свою логику рендера, а UI отдаёт сюда:

    sys.path.insert(0, r"D:\\@Hub\\# Saturni · Editor\\#Series\\@tools")
    rb = _tool("render_batch", "@Render Batch.py")   # _tool: загрузка по пути, см. #2Stage-Rutube.py
    ...
    rb.run(process_project, tasks, script="#2Stage-Rutube", weights=..., max_workers=None)

process_project(*task, q) — top-level функция скрипта (её запускает ProcessPoolExecutor),
первый элемент task — task_id (имя строки на экране). Шлёт в q кортежи
(msg, task_id, val, extra):
    ('start', id, 0, None)          — начал
    ('stage', id, 0, "2hl")          — текущий этап (текст справа от ♥)
    ('progress', id, +pct, None)     — прибавка процентов 0..100 (по ffmpeg time=)
    ('done', id, 0, None)
    ('error', id, _, "текст")        — короткая причина на экран, весь текст в лог

Ошибки: всё общее — в status_bar.py (task_error/short_error, перехват непойманных
исключений, окно не закрывается само). Здесь только ffmpeg-специфика: доля из time=.
"""

import os
import sys
import time
import threading
import multiprocessing

import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
if sb is None:
    _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
    sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(sb)

# после статус-бара: он при импорте ставит иконку окна и должен успеть раньше, чем Terminal
# покажет свою кнопку (2026-10-10)
from concurrent.futures import ProcessPoolExecutor  # noqa: E402


# Лесенка (см. START_AT в @StatusBar.py): ролик стартует, когда у предыдущего START_AT работы
# (или он закончил); скорость дальше держит статус-бар паузами процесса по t["pid"].
START_GAP_TIMEOUT = sb.START_GAP_TIMEOUT


def _make_callback(task_ids, gates=None):
    pct_by_id = {t_id: 0 for t_id in task_ids}
    idx_by_id = {t_id: i for i, t_id in enumerate(task_ids)}
    gap_pct = sb.START_AT * 100

    def release_next(idx):
        if gates and idx + 1 < len(gates):
            gates[idx + 1].set()

    def callback(msg, t_id, val=0, extra=None):
        idx = idx_by_id.get(t_id)
        if idx is None:
            return
        if msg == 'start' and gates:
            # подстраховка: этап без процентов не должен держать очередь вечно
            tm = threading.Timer(START_GAP_TIMEOUT, release_next, (idx,))
            tm.daemon = True
            tm.start()
        if msg in ('done', 'error') or (msg == 'progress' and pct_by_id[t_id] + (val or 0) >= gap_pct):
            release_next(idx)
        with sb.lock:
            t = sb.tasks[idx]
            if msg == 'start':
                t['state'] = 'running'
                t['t0'] = time.time()
                t['frac'] = 0.0
            elif msg == 'stage':
                t['status'] = f"{extra}…"
            elif msg == 'pid':
                t['pid'] = val            # статус-бар держит лесенку паузой этого процесса
            elif msg == 'progress':
                pct_by_id[t_id] = min(100, pct_by_id[t_id] + (val or 0))
                t['prog'] = round(pct_by_id[t_id] / 100 * sb.BAR_WIDTH)
                t['frac'] = pct_by_id[t_id] / 100   # реальная доля — источник est.
            elif msg == 'done':
                t['state'] = 'done'
            elif msg == 'error':
                sb.task_error(t, extra or "неизвестная ошибка")

    return callback


def _guarded(process_fn, task, q, gate=None):
    """Обёртка в рабочем процессе: исключение, не пойманное самим скриптом, тоже становится
    'error' задачи, а не тихо теряется в pool.map. gate — ждать своей очереди старта."""
    try:
        q.put(('pid', task[0], os.getpid(), None))
        if gate is not None:
            gate.wait()
        return process_fn(*task, q)
    except Exception:
        import traceback
        q.put(('error', task[0], 100, traceback.format_exc()))
        return False


def run(process_fn, tasks, script, weights=None, default_task_seconds=120, max_workers=None):
    """Запускает tasks в пуле процессов под статус-баром. Не возвращается (os._exit в sb.run).
    weights: {task_id: секунды медиа × число рендеров} — объём задачи для est."""
    task_ids = [t[0] for t in tasks]
    weights = weights or {}
    sb.configure(script=script, default_task_seconds=default_task_seconds, real_progress=True)
    sb.tasks[:] = [
        {"n": i + 1, "name": t_id, "state": "pending", "has_pct": True, "prog": 0,
         "status": "", "weight": weights.get(t_id) or None, "t0": None}
        for i, t_id in enumerate(task_ids)
    ]

    def worker():
        # Упадёт пул целиком — незавершённые задачи станут ошибками сами (sb._safe_worker).
        workers = min(max_workers or os.cpu_count() or 1, len(tasks)) or 1
        with multiprocessing.Manager() as manager:
            q = manager.Queue()
            gates = [manager.Event() for _ in tasks]
            gates[0].set()
            callback = _make_callback(task_ids, gates)
            listener = threading.Thread(
                target=lambda: [callback(*i) for i in iter(q.get, 'exit')], daemon=True)
            listener.start()
            with ProcessPoolExecutor(workers) as pool:
                list(pool.map(_guarded, [process_fn] * len(tasks), tasks, [q] * len(tasks), gates))
            q.put('exit')
            listener.join(timeout=5)

    sb.run(worker)


def pause_exit(code=1, message=None):
    """Ранний выход ДО статус-бара (нет файлов / не хватает исходников)."""
    if message:
        sb.fatal(message, code)
    sb.wait_close()
    sys.exit(code)
