# -*- coding: utf-8 -*-
"""Эдитовые нарезки (Edit Cuts): python "13. Edit Cuts.py" <spec.json> [--dry] [--list] [--replace] [имена].
--replace — пересобрать уже созданную секвенцию (старая удаляется).
Спека — список нарезок: {"name", "bin": "s1|s2|s1+2", "cat": "Смешное|Ностальгия", "pieces": [...], "music": {...}}.
Кусок: {"say": "e1", "t": 1053, "text": "Хороший труп, не гнилой."} — фраза по тексту рядом с t (сек),
края подрезаются в тишину голоса и не оставляют микрокадров у склеек; можно "pad": [до, после].
{"pic": "e2", "t": 1000, "len": 2.5} — картинка без звука: план, в котором кадр t, обрезанный до len вокруг t.
{"raw": "e1", "a": [s, e]} — кусок со звуком как есть. "music": {"src": "e2", "a": [s, e]} — звук на A2 под всю нарезку.
Секвенции — копии «edit» из бина #edits, частота как у исходника, лежат в #edits/<bin>/<cat>."""
import difflib, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from moments_lib import S, HERE, Voice, video, fps_of

FRAME = 1 / 24
_cache = {}


def ep(st):
    if st not in _cache:
        w = json.load(open(os.path.join(S, "words", st + ".json"), encoding="utf-8"))["words"]
        c = json.load(open(os.path.join(S, "words", st + "_cuts.json")))
        _cache[st] = dict(words=w, cuts=c["cuts"], fps=c["fps"], V=Voice(st))
    return _cache[st]


def norm(s):
    return re.sub(r"[^\w ]", "", s.lower().replace("ё", "е")).split()


def find_phrase(st, t, text):
    E = ep(st); W = E["words"]; want = norm(text); n = len(want)
    best = (0, None, None)
    for i, w in enumerate(W):
        if w["s"] < t - 6 or w["s"] > t + 30:
            continue
        for m in (n - 2, n - 1, n, n + 1, n + 2):
            if m < 1 or i + m > len(W):
                continue
            got = norm(" ".join(x["w"] for x in W[i:i + m]))
            r = difflib.SequenceMatcher(None, got, want).ratio()
            if r > best[0] + 1e-9:
                best = (r, i, i + m - 1)
    return best


def quiet(st, x, w=0.1):
    d = ep(st)["V"].db(x - w, x + w)
    if d is None or not len(d):
        return x
    import numpy as np
    return x - w + int(np.argmin(d)) * 0.01


def loud(st, a, b):
    V = ep(st)["V"]; d = V.db(a, b)
    return d is not None and len(d) and d.max() > V.thr + 14


def avoid_micro(st, a, b, lim=0.3):
    """Не оставлять пару кадров чужого плана у края. Если в этих кадрах звучит слово — кусок продлевается
    за склейку (новый план держится хотя бы 0.25 с), а не обрезает слово."""
    for c in ep(st)["cuts"]:
        if a < c < a + lim:
            a = min(a, c - 0.25) if loud(st, a, c) else c
        if b - lim < c < b:
            b = max(b, c + 0.25) if loud(st, c, b) else c
    return a, b


def fr(x, fps):
    return round(round(x * fps) / fps, 4)


def voice_edges(st, a, b, tight):
    """Края по голосу: WhisperX тянет последнее слово на паузу. tight — паузы длиннее TIGHT_GAP внутри фразы вырезаются."""
    sp = ep(st)["V"].spans(a, b, min_off=0.15) or []
    sp = [s for s in sp if s[1] - s[0] >= 0.06]
    if not sp:
        return [(a, b)]
    groups = [[sp[0][0], sp[0][1]]]
    for x, y in sp[1:]:
        if tight and x - groups[-1][1] > TIGHT_GAP:
            groups.append([x, y])
        else:
            groups[-1][1] = y
    return [(max(a, quiet(st, x - 0.1, 0.05)), min(b, quiet(st, y + 0.14, 0.06))) for x, y in groups]


TIGHT_GAP = 0.4     # паузы длиннее внутри фразы вырезаются (Saturni резал от ~0,44 с)
END_HOLD = 0.2


def resolve(p, tight=False):
    if "say" in p:
        st = p["say"]; W = ep(st)["words"]
        r, i, j = find_phrase(st, p["t"], p["text"])
        if i is None:
            return None, f"не найдено: {p['text']}"
        a0 = W[i]["s"] - 0.4
        # конец: оценка длины последнего слова по буквам + пауза после реплики (у Saturni медиана 0,14 с) —
        # дальше по голосу не тянуть: там чужие голоса и музыка (Saturni срезал такие хвосты в эдитах)
        nb = len(re.sub(r"[^\w]", "", W[j]["w"]))
        b0 = min(W[j]["e"] + 0.7, W[j]["s"] + max(0.35, 0.09 * nb + 0.15) + END_HOLD)
        if j + 1 < len(W):
            b0 = min(b0, W[j + 1]["s"] - 0.03)          # не цеплять следующее слово
        if i > 0:
            a0 = max(a0, W[i - 1]["e"] + 0.03)
        fps = ep(st)["fps"]
        got = " ".join(x["w"] for x in W[i:j + 1])
        note = "" if r >= 0.75 else f"  [?] похоже на {r:.2f}: «{got}»"
        out = []
        starts = [x["s"] for x in W[i:j + 1]]
        for a, b in voice_edges(st, a0, b0, p.get("tight", tight)):
            if out and not any(a - 0.2 <= x <= b for x in starts):
                continue                                  # шум или вдох после фразы, а не слова
            if b - a >= 0.25:
                out.append(dict(src=st, a=[fr(a, fps), fr(b, fps)], audio=True, label=got if not out else "  ↳ после паузы"))
        return out, note
    if "pic" in p:
        st = p["pic"]; cuts = ep(st)["cuts"]; t = p["t"]; L = p.get("len", 2.5)
        prev = max([c for c in cuts if c <= t + 0.05] or [0.0]); nxt = min([c for c in cuts if c > t + 0.05] or [t + L])
        a, b = prev, nxt
        if b - a > L:
            a = max(prev, min(t - L / 2, nxt - L)); b = a + L
        fps = ep(st)["fps"]
        return [dict(src=st, a=[fr(a, fps), fr(b, fps)], audio=False, label=f"кадр {int(t // 60)}:{t % 60:04.1f}")], ""
    if "raw" in p:
        fps = ep(p["raw"])["fps"]
        return [dict(src=p["raw"], a=[fr(p["a"][0], fps), fr(p["a"][1], fps)], audio=p.get("audio", True), label="кусок")], ""


M = 0.28    # смена кадра не ближе к краю куска (как в 5. Cut)


def cuts_in(st, a, b):
    return [c for c in ep(st)["cuts"] if a < c < b]


def jl(ps):
    """J/L-каты на стыках кусков со звуком: звук режется по голосу, а шов картинки уходит на смену кадра рядом —
    картинка соседнего куска продлевается, если в продлении нет своей смены кадра. Иначе — предупреждение."""
    warn = []
    for p in ps:
        p["v"] = list(p["a"]); p["vt"] = [p["t"], round(p["t"] + p["a"][1] - p["a"][0], 4)]
    for i in range(1, len(ps)):
        a, b = ps[i - 1], ps[i]
        if not (a["audio"] and b["audio"]):
            continue
        fps = ep(b["src"])["fps"]
        cb = cuts_in(b["src"], b["a"][0] + 0.001, b["a"][0] + M)
        ca = cuts_in(a["src"], a["a"][1] - M, a["a"][1] - 0.001)
        if cb:
            sh = fr(cb[-1] - b["a"][0], fps)
            if not cuts_in(a["src"], a["a"][1] - 0.001, a["a"][1] + sh + M):
                b["v"][0] += sh; b["vt"][0] += sh; a["v"][1] += sh; a["vt"][1] += sh     # J: звук раньше картинки
                continue
        if ca:
            sh = fr(a["a"][1] - ca[0], fps)
            if not cuts_in(b["src"], b["a"][0] - sh - M, b["a"][0] + 0.001):
                a["v"][1] -= sh; a["vt"][1] -= sh; b["v"][0] -= sh; b["vt"][0] -= sh     # L: картинка уходит раньше звука
                continue
        if cb or ca:
            warn.append(f"  [!] микрокадр у стыка {i}: {b['src']} {b['a'][0]:.2f}")
    for p in ps:
        p["v"] = [round(x, 4) for x in p["v"]]; p["vt"] = [round(x, 4) for x in p["vt"]]
    return warn


COMMENT_JSX = r'''
function setComment(it,v){var C="Column.PropertyText.Comment",U="http://ns.adobe.com/premierePrivateProjectMetaData/1.0/";
  if(ExternalObject.AdobeXMPScript===undefined)ExternalObject.AdobeXMPScript=new ExternalObject("lib:AdobeXMPScript");
  XMPMeta.registerNamespace(U,"premierePrivateProjectMetaData");var x=new XMPMeta(it.getProjectMetadata());x.setProperty(U,C,v);it.setProjectMetadata(x.serialize(),[C])}
'''
FADES_JSX = open(os.path.join(HERE, "audio_fades.jsx"), encoding="utf-8").read()


JSX = r'''
var E=__E__,log=[];
function child(b,n,t){for(var i=0;i<b.children.numItems;i++){var c=b.children[i];if(c.name==n&&(t==undefined||c.type==t))return c}return null}
function seqOf(it){for(var i=0;i<app.project.sequences.numSequences;i++){var s=app.project.sequences[i];if(s.projectItem&&s.projectItem.nodeId==it.nodeId)return s}return null}
function findItem(root,n){for(var i=0;i<root.children.numItems;i++){var c=root.children[i];if(c.name==n&&c.type==1)return c;if(c.type==2){var r=findItem(c,n);if(r)return r}}return null}
function T(x){var t=new Time();t.seconds=x;return t}
var root=app.project.rootItem,eb=child(root,"#edits",2);
if(!eb)return __result({err:"нет бина #edits"});
var tmplItem=child(eb,"edit",1),tmpl=tmplItem?seqOf(tmplItem):null;
if(!tmpl)return __result({err:"нет шаблона #edits/edit"});
var b1=child(eb,E.bin,2)||eb.createBin(E.bin),b2=child(b1,E.cat,2)||b1.createBin(E.cat);
var old=child(b2,E.name,1);
if(old){if(!E.replace)return __result({err:"уже есть "+E.bin+"/"+E.cat+"/"+E.name});var os=seqOf(old);if(os)app.project.deleteSequence(os)}
tmpl.clone();var q=null;
for(var i=app.project.sequences.numSequences-1;i>=0;i--){var s=app.project.sequences[i];if(s.name==tmpl.name+" Copy"){q=s;break}}
if(!q)return __result({err:"клон не найден"});
q.name=E.name;q.projectItem.name=E.name;q.projectItem.moveBin(b2);
var st=q.getSettings();var fr=new Time();fr.ticks=String(Math.round(254016000000/E.fps));st.videoFrameRate=fr;q.setSettings(st);
app.project.activeSequence=q;
var items={};
for(var i=0;i<E.p.length;i++){var p=E.p[i],it=items[p.src]||(items[p.src]=findItem(root,p.src+".mp4"));
  if(!it)return __result({err:"нет исходника "+p.src});
  it.setInPoint(p.a[0]+0.002,4);it.setOutPoint(p.a[1]+0.002,4);q.videoTracks[0].overwriteClip(it,p.t);}
if(E.music){var it=items[E.music.src]||(items[E.music.src]=findItem(root,E.music.src+".mp4"));
  it.setInPoint(E.music.a[0]+0.002,4);it.setOutPoint(E.music.a[1]+0.002,4);q.audioTracks[1].overwriteClip(it,0);}
for(var k in items){items[k].clearInPoint();items[k].clearOutPoint()}
var A=q.audioTracks[0].clips,mute=[];
for(var i=0;i<E.p.length;i++)if(!E.p[i].audio)mute.push(E.p[i].t);
for(var i=A.numItems-1;i>=0;i--){var c=A[i];for(var j=0;j<mute.length;j++)if(Math.abs(c.start.seconds-mute[j])<0.03){c.remove(false,false);break}}
var V=q.videoTracks[0].clips;
for(var i=0;i<V.numItems;i++){var cs=V[i].components;for(var j=0;j<cs.numItems;j++)if(cs[j].matchName=="AE.ADBE Motion"){var ps=cs[j].properties;for(var k=0;k<ps.numItems;k++)if(ps[k].displayName=="Scale")ps[k].setValue(E.scale,true)}}
for(var i=1;i<E.p.length&&i<V.numItems;i++){var cur=E.p[i],prev=E.p[i-1],sh=cur.vt[0]-cur.t;
  if(Math.abs(sh)<0.001)continue;
  var a=V[i-1],b=V[i];
  if(sh>0){b.start=T(cur.vt[0]);b.inPoint=T(cur.v[0]);a.end=T(prev.vt[1]);a.outPoint=T(prev.v[1]);}
  else{a.end=T(prev.vt[1]);a.outPoint=T(prev.v[1]);b.start=T(cur.vt[0]);b.inPoint=T(cur.v[0]);}}
var fd=fades(q,[0,1],2);
setComment(q.projectItem,E.note);
var d=function(tr){var o=[];for(var i=0;i<tr.clips.numItems;i++){var c=tr.clips[i];o.push([c.start.seconds,c.end.seconds,c.inPoint.seconds,c.outPoint.seconds])}return o};
return __result({v:d(q.videoTracks[0]),a:d(q.audioTracks[0]),m:d(q.audioTracks[1]),fps:1/q.getSettings().videoFrameRate.seconds,fades:fd});
'''


def fill_scale(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(","))
    return round(max(1920 / w, 1080 / h) * 100, 2)


def overlap_with_moments(ps):
    """Доля звука нарезки из одного обычного момента (EDL Active). Больше 60% — это повтор обычного ролика
    («За козла ответишь» почти целиком был обычным роликом Серии 2 — Saturni его не взял)."""
    import glob
    best = (0.0, None)
    tot = sum(p["a"][1] - p["a"][0] for p in ps if p["audio"]) or 1
    for f in glob.glob(os.path.join(S, "edl", "e*_Active.json")):
        st = os.path.basename(f).split("_")[0]
        for m in json.load(open(f, encoding="utf-8")):
            lo, hi = m["pieces"][0]["a"][0] - 3, m["pieces"][-1]["a"][1] + 3
            o = sum(max(0, min(p["a"][1], hi) - max(p["a"][0], lo)) for p in ps if p["audio"] and p["src"] == st)
            if o / tot > best[0]:
                best = (o / tot, f"{st} №{m['n']} «{m['name']}»")
    return best


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    spec = json.load(open(args[0], encoding="utf-8"))
    only = set(args[1:]); dry = "--dry" in sys.argv
    report = []
    for e in spec:
        if only and e["name"] not in only:
            continue
        ps, t = [], 0.0
        notes = []
        for p in e["pieces"]:
            rs, note = resolve(p, e.get("tight", False))
            if rs is None:
                notes.append(note); continue
            if note:
                notes.append(note)
            ps.extend(rs)
        # края всей нарезки — без микрокадров (тут соседа нет, J/L не сделать)
        if ps and ps[0]["audio"]:
            f0 = ep(ps[0]["src"])["fps"]; a, _ = avoid_micro(ps[0]["src"], ps[0]["a"][0], ps[0]["a"][1]); ps[0]["a"][0] = fr(a, f0)
        if ps and ps[-1]["audio"]:
            f1 = ep(ps[-1]["src"])["fps"]; _, b = avoid_micro(ps[-1]["src"], ps[-1]["a"][0], ps[-1]["a"][1]); ps[-1]["a"][1] = fr(b, f1)
        for r in ps:
            r["t"] = round(t, 4); t += r["a"][1] - r["a"][0]
        notes += jl(ps)
        share, mom = overlap_with_moments(ps)
        if share > 0.6:
            notes.append(f"  [!] {share * 100:.0f}% звука из одного обычного момента {mom} — повтор обычного ролика, лучше другое")
        music = None
        if e.get("music"):
            m = e["music"]; music = dict(src=m["src"], a=[m["a"][0], min(m["a"][1], m["a"][0] + t)])
        line = f"{e['bin']}/{e['cat']}/{e['name']}: {t:.1f} с, кусков {len(ps)}"
        print(line, flush=True)
        for n in notes:
            print(n)
        if "--list" in sys.argv:
            for r in ps:
                print(f"   {r['src']} {int(r['a'][0] // 60)}:{r['a'][0] % 60:05.2f} {r['a'][1] - r['a'][0]:.2f}с  {r['label']}")
        report.append(dict(name=e["name"], bin=e["bin"], cat=e["cat"], dur=round(t, 2), pieces=ps, music=music, notes=notes))
        if dry:
            continue
        E = dict(name=e["name"], bin=e["bin"], cat=e["cat"], p=ps, music=music, replace="--replace" in sys.argv,
                 note=f"Эдит · {e['bin']} / {e['cat']} / {e['name']}", fps=fps_of(video(ps[0]["src"])),
                 scale=fill_scale(video(ps[0]["src"])))
        jsx = os.path.join(S, "_ec.jsx")
        open(jsx, "w", encoding="utf-8").write(FADES_JSX + COMMENT_JSX + JSX.replace("__E__", json.dumps(E, ensure_ascii=False)))
        r = subprocess.run(["node", "pp.mjs", jsx, "180000"], cwd=HERE, capture_output=True, text=True, encoding="utf-8")
        try:
            o = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            print("  ОШИБКА", r.stdout[:300], r.stderr[:300]); continue
        if "err" in o:
            print("  ОШИБКА", o["err"]); continue
        want_a = sum(1 for p in ps if p["audio"])
        ok = len(o["v"]) == len(ps) and len(o["a"]) == want_a and abs(o["a"][-1][1] - t) < 0.06 if o["a"] else len(o["v"]) == len(ps)
        jl_bad = [i for i, (got, p) in enumerate(zip(o["v"], ps)) if max(abs(got[0] - p["vt"][0]), abs(got[1] - p["vt"][1])) > 0.03]
        if jl_bad:
            ok = False; print("  картинка не на месте у кусков", jl_bad[:5])
        nj = sum(1 for p in ps if abs(p["vt"][0] - p["t"]) > 0.001)
        print(f"  Premiere: V{len(o['v'])} A{len(o['a'])} музыка {len(o['m'])}, J/L {nj}, переходы {o.get('fades')}, {o['fps']:.0f} fps",
              "ОК" if ok else "РАСХОЖДЕНИЕ", flush=True)
    json.dump(report, open(os.path.join(S, "edit_cuts_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
