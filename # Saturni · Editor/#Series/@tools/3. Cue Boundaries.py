#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Механическая часть сборки титров (этап 3, "Подхват") — реализует ТОЛЬКО тайминговую
математику из 3. Subtitles.md, ничего не решает по тексту/пунктуации/
грамматике (это ручная правка поверх результата этого скрипта). НЕ путать с
assemble() в 3.1. Subtitles Pipeline.py — та функция старая (PAUSE=1.5, INTONATION_GAP=0.6,
MAX_WORDS=4), написана до текущей ревизии инструкции и используется только для
draft.srt (черновой ориентир). Здесь — актуальные калиброванные числа:

  - Порог реальной паузы: 200 мс (не 600 мс, как в assemble()).
  - Стыковка: сырой зазор < 200 мс между словами стягивается (конец N = начало N+1).
  - Сломанный тайминг слова: собственная длительность > 900 мс -> не доверяем end,
    считаем от start по норме ~350 мс/слово (плотность речи из инструкции).
  - Бюджет титра: 400-1000 норма, до 1200 без внутренней паузы, >1500 запрещено
    (кроме пения/чисел — эти случаи размечаются вручную поверх, не тут).
  - Конец титра = конец последнего слова + 80-150 мс (только если после этого титра
    реальная пауза; если слова стыкуются впритык, добавка не нужна).

Выход — ГРУППИРОВКА слов по реальным паузам (никакой текстовой логики: без учёта
пунктуации, ударения, MAX_WORDS) — то есть черновые "куски по паузам", которые
могут быть длиннее бюджета (одна длинная фраза без пауз внутри). Такие куски НЕ
разбиваются здесь автоматически — это тот случай, где нужна ручная разбивка по
смысловой границе (см. инструкцию, п.5 приоритета границ), инструмент про это
только предупреждает (WARN в комментарии), не режет сам вслепую.

Использование:
    python 3. Cue Boundaries.py words.json > boundaries.txt
Вывод — построчно: индекс, [start, end], зазор-до-следующего, текст куска, и,
если кусок длиннее 1500 мс, WARN с предложением ручной разбивки по количеству слов.
"""
import json
import sys

STITCH_THRESHOLD = 0.200   # сырой зазор < этого — не пауза, стягиваем
BROKEN_WORD_MS = 0.900     # собственная длительность слова > этого — сломанный end
WORD_BUDGET_MS = 0.350     # норма мс/слово для пересчёта сломанного end
END_PAD = 0.120            # конец титра = конец слова + 80-150мс (середина диапазона)
HARD_CAP = 1.500


def fix_broken_word_ends(words):
    """Правило 'Технически сломанные тайминги слов': если end-start > 900мс,
    отбрасываем сырой end, считаем новый от start по норме, не залезая на
    начало следующего слова."""
    out = []
    for i, w in enumerate(words):
        start, end = w["start"], w["end"]
        if end - start > BROKEN_WORD_MS:
            new_end = start + WORD_BUDGET_MS
            nxt_start = words[i + 1]["start"] if i + 1 < len(words) else None
            if nxt_start is not None:
                new_end = min(new_end, nxt_start)
            out.append({**w, "end": new_end, "_fixed": True, "_raw_end": end})
        else:
            out.append({**w, "_fixed": False})
    return out


def group_by_pause(words):
    """Группирует слова в куски по реальным паузам (зазор >= 200мс между
    исправленным end одного слова и start следующего). Никакой другой логики
    границы здесь нет — пунктуация/ударение/длина текста решаются вручную."""
    groups = []
    cur = [words[0]] if words else []
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap >= STITCH_THRESHOLD:
            groups.append(cur)
            cur = [words[i]]
        else:
            cur.append(words[i])
    if cur:
        groups.append(cur)
    return groups


def group_span_ms(group):
    return group[-1]["end"] - group[0]["start"]


def main():
    words = json.load(open(sys.argv[1], encoding="utf-8"))
    words = fix_broken_word_ends(words)
    groups = group_by_pause(words)

    for gi, g in enumerate(groups):
        start = g[0]["start"]
        end = g[-1]["end"]
        text = " ".join(w["word"] for w in g)
        span = group_span_ms(g)
        nxt_gap = None
        if gi + 1 < len(groups):
            nxt_gap = groups[gi + 1][0]["start"] - end
        fixed_marks = "".join("*" if w["_fixed"] else "" for w in g)
        warn = ""
        if span > HARD_CAP:
            warn = f"  [WARN длинный кусок {span*1000:.0f}мс, {len(g)} слов — разбить вручную по смыслу]"
        broken = "".join(f" [FIXED w{j}: raw_end={w['_raw_end']:.3f}]"
                          for j, w in enumerate(g) if w.get("_fixed"))
        print(f"{gi:3d}  [{start:8.3f} - {end:8.3f}]  ({span*1000:5.0f}ms)  "
              f"gap_next={nxt_gap*1000:.0f}ms" if nxt_gap is not None else
              f"{gi:3d}  [{start:8.3f} - {end:8.3f}]  ({span*1000:5.0f}ms)  gap_next=END",
              end="")
        print(f"  {text}{warn}{broken}")


if __name__ == "__main__":
    main()
