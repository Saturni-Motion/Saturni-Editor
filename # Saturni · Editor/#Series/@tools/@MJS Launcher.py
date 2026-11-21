#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Общий движок для питон-лаунчеров 4.0-4.4 (Loop / Verticals / BG Blur / RGB / Sharpen).
2026-09-11, Saturni.

Раньше эти четыре .mjs-скрипта запускались напрямую двойным кликом (node.exe
через файловую ассоциацию) — без обёртки окно то закрывалось сразу, то
случайно зависало (флаки-ретраи держали процесс живым дольше обычного), но
никакого осознанного контроля над этим не было. Теперь каждый скрипт остаётся
ровно тем же .mjs (никакой логики не переехало) — рядом просто появляется
python-лаунчер с тем же именем, который запускает .mjs подпроцессом с
SATURNI_QUIET_JSON=1 и рисует прогресс через D:/@Hub/@ Saturni · Status Bar/@StatusBar.py (♥-полоски,
цвета, WIN/LOSE-концовка) вместо голого лога.

Протокол (см. @tools/@Premiere Lib.mjs, emitEvent/stage/markSeqDone/runCli):
каждая протокольная строка на stdout начинается с "PBAR" и дальше — один JSON-
объект {"type": ..., ...}. Всё остальное, что node напечатает мимо этого
протокола (не должно случаться в штатной работе, но мало ли) — не показываем
живьём (чтобы не рвать перерисовку статус-бара, живое "мерцание" консоли,
жалоба Saturni 2026-09-11), а копим и печатаем ПОСЛЕ статус-бара, только если
что-то в итоге упало — см. on_done() в run().

Типы событий:
  batch_start {targets: [{name, weight},...] | [name,...]} -- список секвенций до старта
                                              (weight — длительность секвенции, для ETA)
  seq_start   {seq}                      -- начало секвенции
  stage       {seq, name}                -- смена этапа внутри секвенции
  seq_result  {seq, skipped}             -- Проход-1 конкретной секвенции завершён (НЕ
                                              финал — см. markSeqDone в @Premiere Lib.mjs,
                                              нужно для скриптов с доп. проходом типа 4.2.) —
                                              задача уходит в "waiting": полоска остаётся,
                                              текст этапа гаснет (он уже не идёт)
  seq_requeue {seq, message}             -- флаки-сбой: секвенция будет восстановлена из
                                              бэкапа и прогнана ещё раз в конце пачки
  seq_done    {seq}                      -- секвенция ОКОНЧАТЕЛЬНО готова (успех)
  seq_error   {seq, message, stack, log} -- секвенция упала (батч продолжается дальше)
  fatal       {message, stack, log, label, batchSummary}
                                         -- весь процесс упал вне per-секвенционного try/catch;
                                            batchSummary=true — это лишь итог "N из M упали",
                                            сами ошибки уже пришли через seq_error, игнорируем

Успех целиком -> WIN-концовка, консоль закрывается сама. Любая ошибка -> LOSE: на
экране остаются ТОЛЬКО проблемные строки (жёлтая стрелка + последняя ошибка), без
дампа логов/стеков (Saturni, 2026-09-24: "не заспамливать, подытожить последнюю ошибку
по проблемным и всё"). Полный человеческий лог node + стеки пишутся в файл
@tools/logs/<скрипт>.log (перезаписывается каждый прогон) — для разбора, не для экрана.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import importlib.util as _ilu   # @StatusBar.py: из-за "@" в имени обычный import невозможен
sb = sys.modules.get("status_bar")   # уже загружен — тот же самый (общие tasks/lock)
if sb is None:
    _spec = _ilu.spec_from_file_location("status_bar", r"D:\@Hub\@ Saturni · Status Bar\@StatusBar.py")
    sb = sys.modules["status_bar"] = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(sb)

PBAR_MARK = "PBAR"

# Стартовая прикидка "сколько секунд занимает одна секвенция" — только пока нет ни одной
# завершённой в этом прогоне и нет истории прошлых прогонов в @tools/logs/timings.jsonl.
# Грубые числа на глаз (2026-09-24) — после пары прогонов их заменит реальная история;
# потом по timings.jsonl можно усреднить и поправить здесь.
DEFAULT_SECONDS_PER_SEQ = {
    "2. Silence Cut.mjs": 60,
    "4.0. Looping.mjs": 30,
    "4.1. Smart Verticals.mjs": 120,
    "4.2. Background Blur.mjs": 90,
    "4.3. #RGB`1%.mjs": 20,
    "4.4. #Sharp`50-5.mjs": 20,
}


def run(mjs_filename, canonical_stages, project_root=None):
    """mjs_filename: имя .mjs-файла (лежит в корне проекта, рядом с этим лаунчером).
    canonical_stages: упорядоченный список "канонических" имён этапов для расчёта
    заполнения ♥-полоски (10 сердечек, поровну на кол-во этапов). Конкретное событие
    "stage" может прийти с более длинным именем ("Sharpening H"/"Sharpening V" — оба
    приводятся к канону "Sharpening" по startswith) — по канону считаем прогресс, текст
    статуса показываем как пришёл от node. Не возвращается (os._exit внутри sb.run())."""
    root = project_root or os.path.dirname(HERE)
    script_path = os.path.join(root, mjs_filename)
    total_stages = len(canonical_stages)
    hearts_for = {
        stage_name: round((i + 1) * sb.BAR_WIDTH / total_stages)
        for i, stage_name in enumerate(canonical_stages)
    }

    seq_index = {}
    fatal = {"message": None}
    raw_lines = []   # прорвавшийся мимо протокола текст — только в лог-файл
    log_name = os.path.splitext(os.path.basename(mjs_filename))[0]
    log_file = sb.log_path(log_name)
    sb.configure(script=log_name,
                 default_task_seconds=DEFAULT_SECONDS_PER_SEQ.get(os.path.basename(mjs_filename)))
    try:
        open(log_file, "w", encoding="utf-8").close()   # новый прогон — чистый лог
    except OSError:
        pass

    def _ensure_task(seq_key, weight=None, name=None):
        # seq_key — служебный ключ секвенции из node (key "#N"; у старых скриптов — имя).
        # На экране — только name: одноимённые секвенции из разных папок идут отдельными
        # строками, без подписей папок (Saturni, 2026-09-24).
        if seq_key not in seq_index:
            idx = len(sb.tasks)
            seq_index[seq_key] = idx
            sb.tasks.append({
                "n": idx + 1, "name": name or seq_key, "state": "pending",
                "has_pct": True, "prog": 0, "status": "",
                "weight": weight, "t0": None, "t_done": None,
            })
        return seq_index[seq_key]

    def _canonical(stage_name):
        if stage_name in hearts_for:
            return stage_name
        for canon in canonical_stages:
            if stage_name.startswith(canon):
                return canon
        return None

    def _short(msg):
        """Одна строка ошибки для экрана — первая непустая строка сообщения."""
        first = next((ln.strip() for ln in str(msg or "?").splitlines() if ln.strip()), "?")
        return f"Ошибка: {first}"[:160]

    def handle_event(ev):
        etype = ev.get("type")
        if etype == "batch_start":
            with sb.lock:
                for target in ev.get("targets", []):
                    if isinstance(target, dict):
                        _ensure_task(target.get("key") or target.get("name"), target.get("weight"),
                                     target.get("name"))
                    else:
                        _ensure_task(target)
        elif etype == "seq_start":
            with sb.lock:
                idx = _ensure_task(ev["seq"])
                sb.tasks[idx]["state"] = "running"
                sb.tasks[idx]["t0"] = time.time()
        elif etype == "stage":
            with sb.lock:
                idx = _ensure_task(ev["seq"])
                t = sb.tasks[idx]
                if t["state"] in ("waiting", "pending"):
                    t["state"] = "running"   # второй проход (4.2. Cropping) снова её взял
                t["status"] = ev["name"] + "\u2026"
                canon = _canonical(ev["name"])
                if canon is not None:
                    t["prog"] = hearts_for[canon]
        elif etype == "seq_result":
            with sb.lock:
                idx = _ensure_task(ev["seq"])
                t = sb.tasks[idx]
                if ev.get("skipped"):
                    t["skipped"] = True   # штатный пропуск — не учитывать в среднем времени на файл
                if t["state"] == "running":
                    t["state"] = "waiting"
                    t["t_wait"] = time.time()
                    t["status"] = ""
        elif etype == "seq_requeue":
            # Флаки-сбой: секвенция отложена на повтор в конце пачки (из бэкапа) — не ошибка,
            # пока не упала и повторно; до своей очереди просто ждёт как ещё не начатая.
            with sb.lock:
                idx = _ensure_task(ev["seq"])
                t = sb.tasks[idx]
                t["state"] = "pending"
                t["status"] = ""
                t["prog"] = 0
                t["t0"] = None
        elif etype == "seq_done":
            with sb.lock:
                idx = _ensure_task(ev["seq"])
                sb.tasks[idx]["state"] = "done"
                sb.tasks[idx]["t_done"] = time.time()
        elif etype == "seq_error":
            with sb.lock:
                idx = _ensure_task(ev["seq"])
                sb.tasks[idx]["state"] = "error"
                sb.tasks[idx]["status"] = _short(ev.get("message"))
                sb.tasks[idx]["t_done"] = time.time()
        elif etype == "fatal":
            # batchSummary — это только итог "N из M секвенций упали": сами ошибки уже
            # показаны в своих строках, повторять их отдельной простынёй не нужно.
            if not ev.get("batchSummary"):
                fatal["message"] = ev.get("message") or ev.get("label") or "?"

    def worker():
        env = dict(os.environ, SATURNI_QUIET_JSON="1", SATURNI_LOG_FILE=log_file)
        args = sys.argv[1:]  # проброс явных имён секвенций, если заданы (как у самого .mjs)
        proc = subprocess.Popen(
            ["node", script_path] + list(args), cwd=root, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(PBAR_MARK):
                try:
                    handle_event(json.loads(line[len(PBAR_MARK):]))
                except json.JSONDecodeError:
                    raw_lines.append(line)
            else:
                # Прорвавшийся мимо протокола сырой текст (не должно случаться штатно) —
                # не показываем живьём (мерцание), только в лог-файл.
                raw_lines.append(line)
        proc.wait()
        crashed = proc.returncode != 0
        if raw_lines:
            sb.write_log(log_name, "\n--- вывод мимо протокола ---\n" + "\n".join(raw_lines),
                         append=True)

        with sb.lock:
            any_seq_error = any(t["state"] == "error" for t in sb.tasks)
            if not sb.tasks:
                # Совсем ранний сбой (упал ДО batch_start — не подключился к UXP, занят порт) —
                # без задачи render() крутился бы вечно (all_fin требует total>0).
                sb.tasks.append({
                    "n": 1, "name": log_name,
                    "state": "error" if (crashed or fatal["message"]) else "done",
                    "has_pct": False, "prog": 0,
                    "status": _short(fatal["message"] or "процесс завершился, не начав ни одной секвенции"),
                    "t0": None, "t_done": None,
                })
            else:
                for t in sb.tasks:
                    if t["state"] in ("running", "waiting"):
                        if fatal["message"]:
                            t["state"] = "error"
                            t["status"] = _short(fatal["message"])
                        elif crashed and not any_seq_error:
                            t["state"] = "error"
                            t["status"] = "Ошибка: процесс node завершился с ошибкой"
                        else:
                            t["state"] = "done"
                        t["t_done"] = time.time()
                    elif t["state"] == "pending":
                        if fatal["message"] or crashed:
                            # процесс остановился раньше, чем дошёл до этой секвенции
                            t["state"] = "error"
                            t["status"] = "Не обработана — процесс остановился раньше."
                        else:
                            t["state"] = "done"

    sb.tasks[:] = []
    sb.run(worker)  # не возвращается; итог — сами строки задач, без дампа логов


if __name__ == "__main__":
    print("Это общий движок лаунчеров — запускай конкретный файл "
          "(\"4.0. Looping.py\", \"4.1. Smart Verticals.py\", ...), не этот.")
