#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
3.2. Subs Assemble.py — автономная сборка титров этапа 3 (движок стадии «3.2»), 2026-09-28.

Вход — пословный вывод стадии 3.1: `_tmp/<клип>/words.json` (если ещё есть) или постоянный
бэкап `1. Whisper One Word/<имя>.srt`. Выход — готовый `<имя>.srt` рядом с видео.

Что делает (правила — @instructions/3. Subtitles.md, калибровка — разборы #analysis 16–24.09):
  1. Чистка: хвостовые галлюцинации («Субтитры сделал…»), «ё» в частых словах, повторы одного
     слова подряд → через дефис («Иди-иди»), ***** без знаков.
  2. Связи между соседними словами — морфология (pymorphy3): предлог / «не» / союз не отрываются
     от следующего слова, определение — от своего существительного, имя — от отчества, частицы
     «же/ли/бы» — от предыдущего; конец предложения и пауза — хорошие места для разреза.
  3. Нарезка — динамическое программирование: цель ~0.55 с + штраф кусков < 0.5 с и короткого первого титра, мягкий потолок 1.2 с, жёсткий 1.5 с,
     ≤ 29 символов; пауза ≥ 200 мс — граница, КРОМЕ пауз внутри смысловой группы; однословный
     титр — только если слово самостоятельное (междометие, «!»/«?», короткий ответ, обращение).
  4. Тайминг: старт = старт первого слова − 80 мс, конец = конец последнего слова (не больше
     0.28 + 0.035·букв, ≤ 0.9 с) + 20 мс, зазор < 200 мс — стык, первый титр с 0,001.
     Короткие куски (< 0.5 с) и однословный первый титр штрафуются — Saturni их склеивает (07.10).
  4а. Текст: «б/ж/шо» → «бы/же/что», «чё» → «что»/«чего», отчества полностью (Егорыч → Егорович),
     «Ой,»/«Добрый день,» целым титром → «!».
  5. Пунктуация на концах: запятая перед длинной паузой → точка + заглавная у следующего.

Чего НЕ делает (это остаётся человеку/Claude): исправления по смыслу сцены, «!»/«?» по
интонации, восстановление пропущенных реплик, мат по вырезам громкости (`*****`), пение.

    python 3.2. Subs Assemble.py <видео.mp4 | words.json | one-word.srt> [--out путь.srt]
"""
import argparse, json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))

LEAD, TAIL, WORD_CAP = 0.08, 0.02, 0.9
TARGET, SOFT_MAX, HARD_MAX = 0.55, 1.2, 1.5     # длительность в нарезке — с потолком по длине слова (07.10)
PAUSE = 0.20
CHARS_SOFT, CHARS_HARD = 29, 36
INF = float("inf")
CUE_PEN, ONE_PEN, NOCUT_BASE, GLUE_MID = 0.0, 0.3, 0.6, 1.5   # калибруются #3.2. Subs Assemble-Eval.py
# 2026-10-07 (разборы Subtitles-30.09 / 07.10): Saturni режет реже — короткие куски (< SHORT_DUR)
# почти всегда склеивает с соседом, особенно в начале ролика; конец перед паузой — по длине слова.
SHORT_DUR, SHORT_PEN, FIRST_PEN = 0.5, 0.3, 3.0
END_BASE, END_PER_CHAR = 0.28, 0.035      # конец последнего слова перед паузой: старт + 0.28 + 0.035·букв
FIRST_START = 0.001                        # самый первый титр — с 00:00:00,001 (Saturni, 2026-10-07)
# Разбор «Каменской»: концовки фраз выходили короче звука, мелкие зазоры 0.2–0.3 с
# Saturni склеивает, запятых слишком много — точку ставить чаще, по паузе и по длине фразы.
END_HOLD = 0.1           # последнее слово перед паузой чуть тянется в тишину (больше — титр висит в паузе)
JOIN = 0.35              # зазор между титрами меньше этого — стык (было 0.20)
PERIOD_GAP = 0.35        # запятая перед паузой от 0.35 с → точка (было 0.6)
PERIOD_RUN, PERIOD_RUN_GAP = 2.5, 0.25   # фраза без точки дольше 2.5 с — точка уже на паузе от 0.25 с

HALLU = re.compile(r"(субтитр|dimatorzok|редактор субтитров|продолжение следует|спасибо за просмотр|"
                   r"подписывайтесь|amara\.org|корректор)", re.I)
YO = {"еще": "ещё", "ее": "её", "идем": "идём", "пойдем": "пойдём", "берем": "берём", "живем": "живём",
      "ждем": "ждём", "поедем": "поедем", "нашел": "нашёл", "пошел": "пошёл", "ушел": "ушёл",
      "пришел": "пришёл", "зашел": "зашёл", "вышел": "вышел", "черт": "чёрт", "четко": "чётко",
      "причем": "причём", "плечо": "плечо", "все-таки": "всё-таки", "твое": "твоё", "мое": "моё",
      "свое": "своё", "нее": "неё", "вернемся": "вернёмся", "разберемся": "разберёмся", "поймешь": "поймёшь",
      "знаешь": "знаешь", "идет": "идёт", "придет": "придёт", "пойдет": "пойдёт", "ведет": "ведёт",
      "несет": "несёт", "берет": "берёт", "живет": "живёт", "ждет": "ждёт", "жжет": "жжёт",
      "течет": "течёт", "зовет": "зовёт", "поет": "поёт", "пьет": "пьёт", "бьет": "бьёт", "льет": "льёт",
      "шьет": "шьёт", "дает": "даёт", "встает": "встаёт", "устает": "устаёт", "узнает": "узнаёт",
      "елки": "ёлки", "легкий": "лёгкий", "тяжелый": "тяжёлый", "веселый": "весёлый", "зеленый": "зелёный",
      "черный": "чёрный", "желтый": "жёлтый", "звезды": "звёзды", "вперед": "вперёд", "полет": "полёт",
      "самолет": "самолёт", "отчет": "отчёт", "счет": "счёт", "учет": "учёт", "расчет": "расчёт"}
# «б/ж» отдельным словом → «бы/же»; «чё/шо» → «что» («чего» в вопросе-реплике); отчества полностью
# (Saturni, 2026-10-07: «Иван Егорыч» → «Иван Егорович»).
SHORT_FORMS = {"б": "бы", "ж": "же", "шо": "что"}
PATR_FULL = {"егорыч": "егорович", "иваныч": "иванович", "петрович": "петрович", "палыч": "павлович",
             "михалыч": "михайлович", "саныч": "александрович", "николаич": "николаевич", "сергеич": "сергеевич",
             "андреич": "андреевич", "василич": "васильевич", "степаныч": "степанович", "семёныч": "семёнович",
             "семеныч": "семёнович", "петрович": "петрович", "аркадьич": "аркадьевич", "григорьич": "григорьевич",
             "максимыч": "максимович", "борисыч": "борисович", "фёдорыч": "фёдорович", "федорыч": "фёдорович",
             "тимофеич": "тимофеевич", "матвеич": "матвеевич", "евсеич": "евсеевич", "игнатьич": "игнатьевич",
             "кузьмич": "кузьмич", "ильич": "ильич", "лукич": "лукич", "фомич": "фомич"}
GREET = re.compile(r"^(добрый (день|вечер|утро)|доброе утро|здравствуй(те)?|здорово|привет|спасибо|благодарю(\s+вас)?)$", re.I)
SELF_STANDING = {"да", "нет", "ага", "угу", "ой", "ах", "ох", "эй", "спасибо",
                 "пожалуйста", "привет", "пока", "здравствуйте", "стоп", "всё", "все", "ладно", "хорошо",
                 "конечно", "точно", "правда", "зря", "блин", "господи", "боже", "класс", "ого"}
CONJ_HEAD = {"и", "а", "но", "или", "что", "чтобы", "если", "когда", "потому", "как", "да", "либо",
             "то", "где", "куда", "откуда", "который", "которая", "которое", "которые", "которого",
             "которой", "которую", "которым", "чем", "так", "тем", "зато", "однако", "поэтому", "хотя",
             "пока", "раз", "ведь", "причём", "причем", "будто", "словно"}
PERS = {"я", "ты", "он", "она", "оно", "мы", "вы", "они", "мне", "тебе", "ему", "ей", "нам", "вам", "им",
        "меня", "тебя", "его", "её", "ее", "нас", "вас", "их", "это", "кто", "никто", "все", "всё"}
LEAD_PRCL = {"просто", "всё-таки", "все-таки", "даже", "только", "уже", "ещё", "еще", "вот", "вон", "лишь",
             "именно", "прямо", "почти", "совсем", "очень", "слишком", "так", "столько", "сколько", "как"}
PARTICLE_TAIL = {"же", "ж", "ли", "ль", "бы", "б"}

_MORPH = None


def morph():
    global _MORPH
    if _MORPH is None:
        import pymorphy3
        _MORPH = pymorphy3.MorphAnalyzer()
    return _MORPH


def bare(t):
    return re.sub(r"[^\wё*-]+", "", t.lower().replace("ё", "е"))


def ends_sentence(t):
    return bool(re.search(r"[.!?…]$", t.rstrip("»\")")))


def ends_soft(t):
    return bool(re.search(r"[,;:]$", t.rstrip("»\")")))


# ---------------------------------------------------------------- ввод
TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def load_words(src):
    if src.lower().endswith(".json"):
        d = json.load(open(src, encoding="utf-8"))
        ws = d.get("word_segments", d) if isinstance(d, dict) else d
        out = []
        for w in ws:
            if "start" in w and "end" in w and str(w.get("word", "")).strip():
                out.append([float(w["start"]), float(w["end"]), str(w["word"]).strip()])
        return out
    out = []
    txt = open(src, encoding="utf-8-sig").read().replace("\r", "")
    for block in re.split(r"\n\s*\n", txt):
        ls = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(ls):
            m = TS.search(l)
            if m:
                g = list(map(int, m.groups()))
                t = " ".join(ls[i + 1:]).strip()
                if t:
                    out.append([g[0]*3600+g[1]*60+g[2]+g[3]/1000, g[4]*3600+g[5]*60+g[6]+g[7]/1000, t])
                break
    return out


def _analysis_dirs():
    """@Analysis Dirs.py — папки разбора в #analysis/(!) Subtitles-ДД.ММ (Saturni, 2026-10-07)."""
    import importlib.util as _ilu
    mod = sys.modules.get("analysis_dirs")
    if mod is None:
        spec = _ilu.spec_from_file_location("analysis_dirs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "@Analysis Dirs.py"))
        mod = sys.modules["analysis_dirs"] = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def find_input(video):
    """words.json из _tmp (полные тайминги) → иначе «1. Whisper One Word/<имя>.srt» (#analysis)."""
    d, stem = os.path.dirname(os.path.abspath(video)), os.path.splitext(os.path.basename(video))[0]
    safe = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", stem).strip("_")
    for p in (os.path.join(d, "_tmp", safe, "words.json"),
              _analysis_dirs().find_backup(video, "1. Whisper One Word"),   # с 07.10 в #analysis
              os.path.join(d, "1. Whisper One Word", stem + ".srt")):        # старые проекты
        if p and os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- чистка
def clean(words):
    # хвостовая галлюцинация: последние слова после паузы ≥ 1.5 с, совпадающие с шаблоном
    for k in range(len(words) - 1, max(0, len(words) - 12), -1):
        if words[k][0] - words[k - 1][1] >= 1.5 and HALLU.search(" ".join(w[2] for w in words[k:])):
            words = words[:k]
            break
    words = [w for w in words if not HALLU.fullmatch(bare(w[2]) or "x")]
    # «ё»
    for w in words:
        m = re.match(r"^([^\wё]*)([\wё-]+)(.*)$", w[2], re.I)
        if m and m.group(2).lower() in YO:
            rep = YO[m.group(2).lower()]
            if m.group(2)[0].isupper():
                rep = rep[0].upper() + rep[1:]
            w[2] = m.group(1) + rep + m.group(3)
    # повтор слова подряд → через дефис
    out = []
    for w in words:
        if out and bare(w[2]) and bare(out[-1][2]).split("-")[-1] == bare(w[2]) and w[0] - out[-1][1] < 0.35 \
                and not ends_sentence(out[-1][2]):
            prev = re.sub(r"[,;:]$", "", out[-1][2])
            out[-1] = [out[-1][0], w[1], prev + "-" + re.sub(r"^[^\wё]+", "", w[2]).lower()]
            continue
        out.append(list(w))
    # ***** без знаков
    for w in out:
        w[2] = re.sub(r"\*{5}[.,!?…;:]+", "*****", w[2])
    # б/ж/шо, чё, отчества
    for k, w in enumerate(out):
        m = re.match(r"^([^\wё]*)([\wё-]+)(.*)$", w[2], re.I)
        if not m:
            continue
        core, low = m.group(2), m.group(2).lower()
        new = None
        if low in SHORT_FORMS:
            new = SHORT_FORMS[low]
        elif low in ("чё", "че"):
            # «Вы чё?», «А чё?», «чё вы?» — «чего»; «чё вы думали» — «что»
            nxt = out[k + 1][2] if k + 1 < len(out) else ""
            new = "чего" if m.group(3).startswith("?") or (bare(nxt) in PERS and nxt.rstrip().endswith("?")) else "что"
        elif low in PATR_FULL:
            new = PATR_FULL[low]
        if new and new != low:
            if core[0].isupper():
                new = new[0].upper() + new[1:]
            w[2] = m.group(1) + new + m.group(3)
    return out


# ---------------------------------------------------------------- связи
def parse(t):
    b = bare(t).strip("-")
    if not b or "*" in b:
        return None
    return morph().parse(b)[0]


def glue(words):
    """glue[k] — цена разреза МЕЖДУ словом k и k+1 (0 — хорошее место; INF — нельзя)."""
    P = [parse(w[2]) for w in words]
    g = []
    for k in range(len(words) - 1):
        a, b = words[k][2], words[k + 1][2]
        pa, pb = P[k], P[k + 1]
        ba, bb = bare(a), bare(b)
        gap = words[k + 1][0] - words[k][1]
        if ends_sentence(a):
            c = -1.0
        elif ends_soft(a):
            c = -0.3
        else:
            c = NOCUT_BASE
        tag_a = pa.tag if pa else None
        tag_b = pb.tag if pb else None
        hard = False
        if not ends_sentence(a) and not ends_soft(a):
            if tag_a and "PREP" in tag_a:
                hard = True                                          # предлог + его слово
            elif ba in ("не", "ни"):
                hard = True                                          # не + глагол/слово
            elif ba in CONJ_HEAD and tag_a and ("CONJ" in tag_a or ba in ("что", "как", "то")):
                c += 6.0                                             # союз — в начало следующего
            elif tag_a and tag_b and ({"ADJF", "PRTF", "NUMR"} & set(str(tag_a).replace(" ", ",").split(","))
                                      or ("NPRO" in tag_a and ba in {"наш", "ваш", "мой", "твой", "свой", "этот", "тот",
                                                                     "наша", "ваша", "моя", "твоя", "эта", "та", "это",
                                                                     "эти", "этого", "этой", "этим", "эту", "нашим", "нашего"})) \
                    and ("NOUN" in tag_b or "ADJF" in tag_b):
                c += 5.0                                             # определение + существительное
            elif tag_a and tag_b and "NOUN" in tag_a and "NOUN" in tag_b and tag_b.case == "gent":
                c += 2.5                                             # укол кактуса, чувство вины
            elif tag_a and tag_b and "Name" in tag_a and "Patr" in tag_b:
                hard = True                                          # имя + отчество
            elif ba in LEAD_PRCL and tag_b and ({"ADJF", "ADJS", "ADVB", "COMP", "PRED", "NUMR", "VERB", "INFN", "NOUN", "PRCL"}
                                                  & set(str(tag_b).replace(" ", ",").split(","))):
                c += GLUE_MID                                        # очень страшно, только хуже, просто Пшки
            elif ba in PERS and tag_b and ({"VERB", "ADJS", "PRTS", "PRED", "ADVB"} & set(str(tag_b).replace(" ", ",").split(","))
                                           or bb in ("не", "ни", "же", "бы", "с", "со", "за")):
                c += GLUE_MID                                        # вы потом склеите, я тупая, мы с ним
            elif tag_a and tag_b and "VERB" in tag_a and "INFN" in tag_b:
                c += GLUE_MID                                        # хотела пообщаться
            if bb in PARTICLE_TAIL and gap < 0.5:
                hard = True                                          # «же/ли/бы» — к предыдущему
        if hard:
            g.append(INF)
            continue
        if gap >= PAUSE:
            c -= 1.2 + min(1.5, (gap - PAUSE) * 3)                   # пауза — граница
        g.append(c)
    return g, P


# ---------------------------------------------------------------- нарезка
def standalone(w, p):
    b = bare(w[2])
    if not b:
        return True
    if re.search(r"[!?]$", w[2]) or b in SELF_STANDING or "*" in b:
        return True
    if p and ("INTJ" in p.tag or "Name" in p.tag or "Surn" in p.tag):
        return True
    if w[1] - w[0] >= 0.6:
        return True
    return False


def segment(words, g, P):
    n = len(words)
    caps = [min(WORD_CAP, END_BASE + END_PER_CHAR * len(bare(w[2]).replace("-", ""))) for w in words]
    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(n):
        chars = 0
        for i in range(j, -1, -1):
            chars += len(words[i][2]) + (1 if i < j else 0)
            dur = min(words[j][1], words[j][0] + caps[j]) - words[i][0]   # тот же потолок, что у конца титра
            if (dur > HARD_MAX + 0.6 or chars > CHARS_HARD + 10) and i < j:
                break
            if best[i] == INF:
                continue
            # внутри титра: пауза ≥ PAUSE допустима только внутри смысловой группы
            bad = 0.0
            for k in range(i, j):
                gap = words[k + 1][0] - words[k][1]
                if gap >= PAUSE and g[k] != INF and g[k] < 4.0:
                    bad += 3.0 + gap * 4
            if i == 0:
                bad *= 0.3                                           # в начале ролика склеивает и через паузу (07.10)
            c = ((dur - TARGET) / TARGET) ** 2
            if dur > SOFT_MAX:
                c += ((dur - SOFT_MAX) / 0.3) ** 2 * 1.5
            if dur > HARD_MAX:
                c += 25 + (dur - HARD_MAX) * 20
            if chars > CHARS_SOFT:
                c += (chars - CHARS_SOFT) * 0.8
            if chars > CHARS_HARD:
                c += 30
            if i == j and not standalone(words[i], P[i]):
                c += ONE_PEN                                         # обломок группы — склеить
            if dur < SHORT_DUR and not (i == 0 and j == n - 1):
                c += SHORT_PEN * ((SHORT_DUR - dur) / SHORT_DUR) ** 2 * 4   # слишком короткий кусок
            if i == 0 and j < n - 1 and (i == j or dur < 0.6):
                c += FIRST_PEN                                       # в начале зрителю не нужна быстрая смена
            cut = 0.0 if j == n - 1 else g[j]
            if cut == INF:
                continue
            v = best[i] + c + bad + cut + CUE_PEN                     # цена каждого титра
            if v < best[j + 1]:
                best[j + 1], back[j + 1] = v, i
    cues, j = [], n
    while j > 0:
        i = back[j]
        cues.append((i, j - 1))
        j = i
    return cues[::-1]


# ---------------------------------------------------------------- сборка
class Voice:
    """Громкость голоса по звуку ролика (полоса 200–3500 Гц, кадр 10 мс). Нужна потому, что WhisperX
    растягивает слова на паузы: по его таймингам пауз почти нет, а «по длине слова» конец часто
    обрезается раньше звука. По громкости видно, где голос реально кончился и сколько длится тишина."""
    STEP, MIN_SIL = 0.01, 0.12

    def __init__(self, video):
        import subprocess
        import numpy as np
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                              "-af", "highpass=f=200,lowpass=f=3500", "-f", "s16le", "-"],
                             capture_output=True).stdout
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        n = 160
        x = x[:len(x) // n * n].reshape(-1, n)
        db = 10 * np.log10((x ** 2).mean(axis=1) + 1.0)
        lo, hi = np.percentile(db, 10), np.percentile(db, 90)
        self.quiet = db < lo + 0.45 * (hi - lo)            # тишина: ниже 45% пути от пола к речи (подобрано по правкам Saturni)
        self.n = len(db)

    def _i(self, t):
        return max(0, min(self.n - 1, int(t / self.STEP)))

    def voice_end(self, t0, t_max):
        """Где после t0 голос стихает (начало тишины ≥ MIN_SIL), но не позже t_max."""
        need = int(self.MIN_SIL / self.STEP)
        i, stop, run = self._i(t0), self._i(t_max), 0
        while i < stop:
            run = run + 1 if self.quiet[i] else 0
            if run >= need:
                return (i - run + 1) * self.STEP
            i += 1
        return t_max

    def silence(self, t0, t1):
        """Самая длинная тишина между t0 и t1 (секунды)."""
        best = run = 0
        for i in range(self._i(t0), self._i(t1)):
            run = run + 1 if self.quiet[i] else 0
            best = max(best, run)
        return best * self.STEP

    def unheard(self, words, min_len=0.5):
        """Куски, где голос есть, а слов нет (пропуски распознавания): [(начало, конец)]."""
        busy = [False] * self.n
        for w in words:      # WhisperX тянет слово на соседнюю речь — длину слова оценить по буквам
            end = min(w[1], w[0] + 0.2 + 0.08 * len(bare(w[2])))
            for i in range(self._i(w[0] - 0.15), self._i(end + 0.15) + 1):
                busy[i] = True
        out, start = [], None
        for i in range(self.n):
            on = (not self.quiet[i]) and not busy[i]
            if on and start is None:
                start = i
            elif not on and start is not None:
                if (i - start) * self.STEP >= min_len:
                    out.append((start * self.STEP, i * self.STEP))
                start = None
        return out


VOICE_TAIL = 0.08        # после того как голос стих — ещё чуть-чуть держать титр


def build(words, voice=None):
    words = clean(words)
    if not words:
        return []
    g, P = glue(words)
    spans = segment(words, g, P)
    cues, pause = [], []
    for i, j in spans:
        text = " ".join(w[2] for w in words[i:j + 1])
        a = words[i][0] - LEAD
        nb = len(bare(words[j][2]).replace("-", ""))
        cap = min(WORD_CAP, END_BASE + END_PER_CHAR * nb)            # раздутый конец WhisperX — по длине слова
        b = min(words[j][1], words[j][0] + cap) + TAIL
        nxt = words[j + 1][0] if j + 1 < len(words) else None
        if voice is not None:
            # конец — где голос реально стих; пауза — настоящая тишина до следующего слова
            lim = nxt if nxt is not None else words[j][0] + 3.0
            ve = voice.voice_end(words[j][0] + 0.12, lim)
            b = max(b, min(ve + VOICE_TAIL, lim))
            p = voice.silence(words[j][0] + 0.12, nxt + 0.05) if nxt is not None else 9.0
        else:
            p = nxt - words[j][1] if nxt is not None else 9.0
            if p >= PAUSE:
                b += END_HOLD                                        # хвост фразы не обрезать
        cues.append([a, b, text])
        pause.append(p)
    run_start = cues[0][0] if cues else 0.0
    # запятая перед длинной паузой → точка, следующая с заглавной; после конца предложения — заглавная
    for k in range(len(cues)):
        if cues[k][2].endswith(","):
            body = cues[k][2][:-1]
            # междометие/приветствие целым титром — «!» (Ой! Добрый день!), Saturni 2026-10-07 —
            # только если дальше пауза или конец: «Добрый день, / сударыня» — это одна фраза
            gap_next = cues[k + 1][0] - cues[k][1] if k + 1 < len(cues) else 9.0
            if gap_next >= 0.3 and (GREET.match(body) or all(bare(t) in {"ой", "ах", "ох", "эй", "эх", "ай", "о", "э"}
                                                             for t in body.split())):
                cues[k][2] = body + "!"
        if k + 1 < len(cues) and cues[k][2].endswith(","):
            run = cues[k][1] - run_start
            if pause[k] >= PERIOD_GAP or (run >= PERIOD_RUN and pause[k] >= PERIOD_RUN_GAP):
                cues[k][2] = cues[k][2][:-1] + "."
        if ends_sentence(cues[k][2]) and k + 1 < len(cues):
            run_start = cues[k + 1][0]
        if k > 0 and ends_sentence(cues[k - 1][2]) and cues[k][2][:1].islower():
            cues[k][2] = cues[k][2][0].upper() + cues[k][2][1:]
    # тайминг: монотонность, стыки, первый с нуля
    for k in range(1, len(cues)):
        cues[k][0] = max(cues[k][0], cues[k - 1][0] + 0.04)
    for k in range(len(cues) - 1):
        ns = cues[k + 1][0]
        if cues[k][1] > ns or ns - cues[k][1] < JOIN:
            cues[k][1] = ns
    for c in cues:
        c[0] = max(0.0, c[0])
    if cues[0][0] < 0.5:
        cues[0][0] = FIRST_START
        c[1] = max(c[1], c[0] + 0.04)
    return cues


def ts(s):
    ms = int(round(max(s, 0) * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s_, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s_:02d},{ms:03d}"


def write_srt(cues, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        for k, (a, b, t) in enumerate(cues, 1):
            fh.write(f"{k}\n{ts(a)} --> {ts(b)}\n{t}\n\n")


def coverage(src, video):
    """Доля ролика, покрытая распознанными словами (грубо: от первого до последнего слова / длительность).
    None — длительность не узнать."""
    import subprocess
    try:
        d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  video], capture_output=True, text=True).stdout.strip())
    except Exception:
        return None
    ws = load_words(src)
    if not ws or d <= 0:
        return 0.0 if d > 0 else None
    speech = sum(min(w[1], w[0] + 1.0) - w[0] for w in ws)
    return min(1.0, speech / (d * 0.55))       # живая речь занимает ~55% хронометража ролика


def assemble_file(src, out, video=None):
    """video — ролик: по его звуку уточняются концы фраз и паузы (без него — только по таймингам слов)."""
    voice = None
    if video and os.path.exists(video):
        try:
            voice = Voice(video)
        except Exception as e:
            print(f"  [!] звук ролика не прочитан ({e}) — концы по таймингам слов")
    words = load_words(src)
    cues = build(words, voice)
    if voice is not None:
        for a, b in voice.unheard(words):
            print(f"  [?] {int(a // 60)}:{a % 60:05.2f}–{int(b // 60)}:{b % 60:05.2f} голос без слов — дослушать (и сверить с GigaAM)")
    write_srt(cues, out)
    return cues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--out"); ap.add_argument("--video")
    a = ap.parse_args()
    src, out, video = a.src, a.out, a.video
    if src.lower().endswith((".mp4", ".mov", ".mkv")):
        video = src
        inp = find_input(src)
        if not inp:
            sys.exit(f"нет words.json / «1. Whisper One Word» для {src} — сначала 3.1")
        out = out or os.path.splitext(src)[0] + ".srt"
        src = inp
    out = out or os.path.splitext(src)[0] + ".assembled.srt"
    cues = assemble_file(src, out, video)
    print(f"{os.path.basename(out)}: {len(cues)} титров")


if __name__ == "__main__":
    main()
