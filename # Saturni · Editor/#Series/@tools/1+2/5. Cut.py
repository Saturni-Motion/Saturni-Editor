# -*- coding: utf-8 -*-
"""Резка момента по правилам Saturni: python "5. Cut.py" e3 → edl/e3_Active.json, _Faster, _Medium + сводка.
Спецификация — spec_<стем>.json: [{n,name,color,keep:[[a,b,"AFM"?]],hold:[[t,cap]],air:[[a,b]]}]."""
import json, math, re, sys
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from moments_lib import Voice, S, video, series, rate_of, fps_of
FPS = fps_of(video(sys.argv[1]))   # секвенции идут с частотой исходника
MODES = {
    # minp — с какой паузы режем; head/tail — запас у голоса; end — хвост в конце ролика; margin — смена кадра не ближе к краю куска
    "Active": dict(minp=.75, head=.06, tail=.24, end=.60, margin=.28, hold=1.5),
    "Faster": dict(minp=.34, head=.03, tail=.13, end=.60, margin=.28, hold=.0),
    "Medium": dict(minp=.50, head=.04, tail=.18, end=.60, margin=.28, hold=1.0),
}
def fl(x): return math.floor(x * FPS + 1e-6) / FPS
def ce(x): return math.ceil(x * FPS - 1e-6) / FPS
def rn(x): return round(x * FPS) / FPS
stem = sys.argv[1]
V = Voice(stem)
cuts = np.array(json.load(open(S + rf"\words\{stem}_cuts.json"))["cuts"])
words = [w for w in json.load(open(S + rf"\words\{stem}.json", encoding="utf-8"))["words"] if w['e'] - w['s'] < 4]
spec = json.load(open(S + rf"\spec_{stem}.json", encoding="utf-8"))
segs = json.load(open(S + rf"\words\{stem}.json", encoding="utf-8"))["segs"]
NOWORD_MAX = 0.6       # звук без слов длиннее — не речь
MIN_TAIL = 0.10        # после конца голоса — не меньше: тихие конечные согласные («яд», «проверим») ниже порога голоса
def speech(a, b):
    sp = V.spans(a, b, min_off=0.14) or []
    out = []
    for x, y in sp:
        y2 = float(y); x2 = float(x)
        has_word = any(x2 - 0.12 <= w['s'] < y2 for w in words)
        # звук без единого слова длиннее NOWORD_MAX — вздох, шум, музыка: Saturni такие куски вырезает как паузу
        if has_word or 0.3 <= y2 - x2 < NOWORD_MAX:
            out.append([x2, y2])
        elif out and x2 - out[-1][1] < 0.25:
            out[-1][1] = y2       # хвост слова, а не шум
    return out
def quiet(t, w=0.15):
    """Край разметки — в самую тихую точку голоса рядом (±w), чтобы не резать слово соседней фразы."""
    d = V.db(t - w, t + w)
    if d is None or not len(d):
        return t
    return round(t - w + int(np.argmin(d)) * 0.01, 3)
def quiet_end(t, w=0.15):
    """Конец разметки: тихая точка только чуть раньше или позже — назад не дальше 0,03 с, чтобы не съесть конец слова."""
    d = V.db(t - 0.03, t + w)
    if d is None or not len(d):
        return t
    return round(t - 0.03 + int(np.argmin(d)) * 0.01, 3)
def finish_phrase(b):
    """Разметка кончилась на начатом слове — дотянуть до конца этого слова по голосу.
    Так не теряется последнее слово («Я вам не | верю», «что я его | сдам»), если конец разметки поставлен рано:
    WhisperX растягивает конец последнего слова фразы на паузу, поэтому длину слова считаем по буквам.
    Слово считается начатым, только если оно началось до конца разметки; конец никогда не заходит на следующее слово."""
    for k in range(len(words) - 1, -1, -1):
        w = words[k]
        if w['s'] >= b + 0.15:
            continue
        if w['s'] < b - 0.8:
            return b
        if w['s'] > b + 0.03:          # слово после конца разметки — это уже следующая реплика, даже впритык
            return b
        if any(re.search(r"[.!?…]$", x['w']) and b - 0.35 < x['e'] <= w['s'] + 0.02 for x in words[max(0, k - 3):k]):
            return b                   # разметка сразу после конца предложения — новое предложение не дотягиваем
        break
    else:
        return b
    cap = w['s'] + max(0.35, 0.09 * len(w['w'].strip('.,!?…:;»«"')) + 0.15)
    if k + 1 < len(words):
        cap = min(cap, words[k + 1]['s'] - 0.04)
    if cap <= b:
        return b
    end = None
    for x, y in (V.spans(w['s'] - 0.05, cap + 0.3, min_off=0.15) or []):
        if x <= (end if end is not None else w['s'] + 0.1):
            end = float(y)
    return max(b, min(end, cap)) if end else b
def shots(a, b):
    return [float(c) for c in cuts if a < c < b]
def build(m, mode):
    P = MODES[mode]
    pieces = []  # [start,end,speech_first,speech_last]
    keeps = [k for k in m["keep"] if len(k) < 3 or mode[0] in k[2]]
    for k in keeps:
        b1 = finish_phrase(k[1])
        b = quiet(k[1]) if b1 == k[1] else quiet_end(b1)   # слово не дотягивали — край как раньше, в тишину рядом
        nw = next((w['s'] for w in words if w['s'] > k[1] + 0.03), None)
        if nw is not None and b > nw - 0.03:
            b = max(k[1], nw - 0.03)                    # не заходить на следующее слово
        a = quiet(k[0])
        sp = speech(a, b)
        if not sp:
            pieces.append([a, b, a, b]); continue
        cur = None
        for i, (x, y) in enumerate(sp):
            if cur is None:
                cur = [max(a, x - P["head"]), None, x, y]
            else:
                px = cur[3]; g = x - px
                air = any(ar[0] <= px and x <= ar[1] and (mode != "Faster") for ar in m.get("air", []))
                hold = next((h for h in m.get("hold", []) if px - 0.05 <= h[0] <= x + 0.05), None)
                cap = (hold[1] * (P["hold"] or 1.0) if hold and (P["hold"] or len(hold) > 2) else None)
                if air:
                    cur[3] = y; continue
                if cap:
                    if g <= cap + 0.08:
                        cur[3] = y; continue
                    cur[1] = px + cap - P["head"]
                    pieces.append(cur); cur = [x - P["head"], None, x, y]; continue
                if g < P["minp"] or g - P["head"] - P["tail"] < 0.08:
                    cur[3] = y; continue
                cur[1] = px + max(P["tail"], MIN_TAIL)
                pieces.append(cur); cur = [x - P["head"], None, x, y]
        cur[1] = min(b + MIN_TAIL if nw is None else min(b + MIN_TAIL, max(b, nw - 0.03)), cur[3] + max(P["tail"], MIN_TAIL))
        pieces.append(cur)
    pieces[-1][1] = min(pieces[-1][3] + P["end"], max(k[1] for k in keeps) + 2.0)
    if m.get("end"):
        pieces[-1][1] = m["end"] if mode != "Faster" else pieces[-1][1]
    # хвост в конце не цепляет начало следующей реплики (её первое слово после конца разметки)
    kend = max(k[1] for k in keeps)
    nxt = [w['s'] for w in words if w['s'] >= kend - 0.15 and w['s'] > pieces[-1][3] - 0.02]
    if nxt and pieces[-1][1] > nxt[0] - 0.06:
        pieces[-1][1] = max(pieces[-1][3], nxt[0] - 0.06)
    # и не цепляет голос следующей реплики, если слова у неё размечены позже, чем она звучит
    after = [x for x, y in (V.spans(pieces[-1][3] + 0.12, pieces[-1][1], min_off=0.05) or [])
             if y - x >= 0.12 and x > pieces[-1][3] + 0.15]          # новый голос после тишины, а не продолжение слова
    if after and kend < after[0] + 0.3:
        pieces[-1][1] = max(pieces[-1][3] + 0.04, after[0] - 0.04)
    # куски короче 0.4 с — слить с соседом нельзя без потери; оставляем, но предупреждаем
    warn = []
    # кадры
    for p in pieces:
        p[0] = fl(p[0]); p[1] = ce(p[1])
    for i in range(len(pieces) - 1):
        if pieces[i][1] > pieces[i + 1][0]:
            pieces[i][1] = pieces[i + 1][0]
    # запас у смены кадра
    M = P["margin"]
    shift = [0.0] * (len(pieces) + 1)  # сдвиг шва картинки относительно шва звука (+ = картинка позже звука)
    for i, p in enumerate(pieces):
        s, e, fs, ls = p
        c = shots(s + 0.001, min(s + M, e))
        if c:
            c0 = c[-1]
            if c0 <= fs + 0.04 or i == 0 and c0 <= fs + 0.1:
                p[0] = rn(c0)                                   # вход ровно по смене кадра
            elif i > 0 and not shots(pieces[i - 1][1] - 0.001, pieces[i - 1][1] + (c0 - s) + M):
                shift[i] = rn(c0 - s)                           # звук раньше картинки (J-кат)
            elif i > 0 and c0 - M > pieces[i - 1][1] and not shots(c0 - M - 0.001, s):
                p[0] = fl(c0 - M)                               # начать раньше: прошлый план целиком виден ≥ M, без микрокадра
            else:
                warn.append(f"кадр через {c0 - s:.2f} после входа куска {i + 1} ({s:.2f})")
        s, e, fs, ls = p
        c = shots(max(s + 0.001, e - M), e)
        if c:
            c0 = c[0]
            if c0 >= ls + 0.06:
                p[1] = rn(c0)                                   # конец ровно по смене кадра (не раньше хвоста слова)
            elif c0 >= ls - 0.02:
                # смена кадра на хвосте слова: картинка уходит по смене кадра, звук дозвучивает (L-кат); нельзя — как раньше, по смене
                if i + 1 < len(pieces) and not shots(pieces[i + 1][0] - (e - c0) - M, pieces[i + 1][0] + 0.001):
                    shift[i + 1] = -rn(e - c0)
                else:
                    p[1] = rn(c0)
            elif i + 1 < len(pieces) and not shots(pieces[i + 1][0] - (e - c0) - M, pieces[i + 1][0] + 0.001):
                shift[i + 1] = -rn(e - c0)                      # картинка уходит раньше звука (L-кат)
            elif i + 1 < len(pieces) and c0 + M < pieces[i + 1][0] and not shots(e, c0 + M + 0.001):
                p[1] = ce(c0 + M)                               # закончить позже: новый план виден ≥ M, без микрокадра
            elif i + 1 < len(pieces):
                warn.append(f"кадр за {e - c0:.2f} до конца куска {i + 1} ({e:.2f})")
            else:
                warn.append(f"кадр за {e - c0:.2f} до конца ролика ({e:.2f}), голос до {ls:.2f}")
    # таймлайн
    t = 0.0; out = []
    T = [0.0]
    for p in pieces:
        t += p[1] - p[0]; T.append(rn(t))
    for i, p in enumerate(pieces):
        v0 = T[i] + shift[i]; v1 = T[i + 1] + shift[i + 1]
        out.append(dict(t=[T[i], T[i + 1]], a=[rn(p[0]), rn(p[1])], vt=[rn(v0), rn(v1)], v=[rn(p[0] + shift[i]), rn(p[1] + shift[i + 1])]))
    for o in out:
        if o['t'][1] - o['t'][0] < 0.5:
            warn.append(f"короткий кусок {o['t'][1] - o['t'][0]:.2f} ({o['a'][0]})")
    return dict(n=m["n"], name=m["name"], color=m.get("color", 5), rate=rate_of(m), mode=mode, dur=rn(t), pieces=out, warn=warn,
                text=" ".join(w['w'] for w in words if any(o['a'][0] - 0.02 <= w['s'] < o['a'][1] - 0.04 for o in out)))
if __name__ == "__main__":
    import os
    os.makedirs(S + r"\edl", exist_ok=True)
    res = {}
    for mode in MODES:
        res[mode] = [build(m, mode) for m in spec]
        json.dump(res[mode], open(S + rf"\edl\{stem}_{mode}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    for i, m in enumerate(spec):
        print(f"{m['n']:2d}. {m['name']:<26}", "  ".join(f"{k} {res[k][i]['dur']:5.1f} ({len(res[k][i]['pieces'])})" for k in MODES))
        for k in MODES:
            for w in res[k][i]["warn"]:
                print(f"     {k}!", w)
