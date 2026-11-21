# -*- coding: utf-8 -*-
"""Рендер: python "8. Render.py" e3 Active [номера]. Пропускает готовые файлы нужной длины, проверяет длительность, ставит значок оценки."""
import json, os, subprocess, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moments_lib import S, HERE, series, DIRS
st, mode = sys.argv[1], sys.argv[2]
only = set(int(x) for x in sys.argv[3:])
num = st[1:]
bin_ = "s" + num + "\\" + DIRS[mode]
out_dir = series(num, DIRS[mode])
os.makedirs(out_dir, exist_ok=True)
edl = json.load(open(S + rf"\edl\{st}_{mode}.json", encoding="utf-8"))
EPR = r"C:\Users\SATURNi\Documents\Adobe\Adobe Media Encoder\26.0\Presets\# H_1.epr"   # пресет «# H.264`10», 10 Мбит/с
TPL = r'''
function findSeqPath(path){for(var i=0;i<app.project.sequences.numSequences;i++){var s=app.project.sequences[i];var p="";try{p=s.projectItem.treePath}catch(e){}if(p.slice(-path.length)==path)return s}return null}
var q=findSeqPath(__P__);if(!q)return __result({err:"нет"});
app.project.activeSequence=q;
var t0=new Date().getTime();
var r=q.exportAsMediaDirect(__O__,__E__,0);
return __result({res:r,ms:new Date().getTime()-t0});
'''
def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)
for m in edl:
    if only and m['n'] not in only: continue
    out = os.path.join(out_dir, f"{m['n']}.mp4")
    final = os.path.join(out_dir, f"{m['n']} {m['rate']}.mp4" if m['rate'] else f"{m['n']}.mp4")   # Premiere пишет без значка: 🔥 ломает путь в ExtendScript; метку « ` 1h» ставит Cleanup
    if os.path.exists(final) and abs(dur(final) - m['dur']) < 0.09 and not os.environ.get("RENDER_FORCE"):   # RENDER_FORCE=1 — рендерить заново
        print("есть", final, flush=True); continue
    jsx = os.path.join(S, "_ren.jsx")
    open(jsx, "w", encoding="utf-8").write(TPL.replace("__P__", json.dumps(f"\\{bin_}\\{m['n']}", ensure_ascii=False)).replace("__O__", json.dumps(out, ensure_ascii=False)).replace("__E__", json.dumps(EPR, ensure_ascii=False)))
    t0 = time.time()
    r = subprocess.run(["node", "pp.mjs", jsx, "600000"], cwd=HERE, capture_output=True, text=True, encoding="utf-8")
    d = dur(out) if os.path.exists(out) else 0
    ok = abs(d - m['dur']) < 0.09
    print(f"{bin_}/{m['n']} {m['name']}: {m['dur']:.2f} файл {d:.2f} за {time.time() - t0:.0f}с", "ОК" if ok else ("ОШИБКА " + r.stdout[:200]), flush=True)
    if ok and final != out:
        os.replace(out, final)
