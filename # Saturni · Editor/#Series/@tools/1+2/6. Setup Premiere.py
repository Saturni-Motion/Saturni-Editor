# -*- coding: utf-8 -*-
"""Папки режимов и нумерованные секвенции: python "6. Setup Premiere.py" s3=13 s4=13.
Бин серии в корне проекта (нет — создаётся), внутри: 1. Active, 2. Faster, 3. Medium. Нумерованные из корня бина едут в 1. Active.
Новые секвенции — только копии шаблона: бин «s» в корне проекта, в нём секвенция «1.» (папка выгрузки,
шаблон рендера, размеры дорожек — всё как настроил Saturni). Нет шаблона «s» — копия секвенции «e» с предупреждением:
у копий «e» в старых проектах сохранялась чужая папка выгрузки. После — проверка: python "12. Check Export.py"."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from moments_lib import S, HERE, DIRS, video, fps_of
NEED = {a.split("=")[0]: int(a.split("=")[1]) for a in sys.argv[1:]}
JSX = r"""var NEED=__NEED__,CATS=__CATS__,FPS=__FPS__,log=[];
function child(b,n,t){for(var i=0;i<b.children.numItems;i++){var c=b.children[i];if(c.name==n&&(t==undefined||c.type==t))return c}return null}
function seqOf(it){for(var i=0;i<app.project.sequences.numSequences;i++){var s=app.project.sequences[i];if(s.projectItem&&s.projectItem.nodeId==it.nodeId)return s}return null}
for(var k in NEED){
  var b=child(app.project.rootItem,k,2);
  if(!b)b=app.project.rootItem.createBin(k);
  var bins=[];for(var i=0;i<CATS.length;i++)bins.push(child(b,CATS[i],2)||b.createBin(CATS[i]));
  var root=[];for(var i=0;i<b.children.numItems;i++){var c=b.children[i];if(c.type==1&&/^\d+$/.test(c.name))root.push(c)}
  for(var i=0;i<root.length;i++)root[i].moveBin(bins[0]);
  var tmpl=null,sb=child(app.project.rootItem,"s",2);
  if(sb)for(var i=0;i<sb.children.numItems;i++){var c=sb.children[i];if(c.type==1&&/^1\.\s*$/.test(c.name)){tmpl=seqOf(c);break}}
  if(!tmpl){for(var i=0;i<app.project.sequences.numSequences;i++)if(app.project.sequences[i].name=="e")tmpl=app.project.sequences[i];
    if(tmpl)log.push("ВНИМАНИЕ: нет шаблона s / «1.» — копии от «e», проверить папку выгрузки и шаблон рендера")}
  if(!tmpl){log.push("в проекте нет ни шаблона s / «1.», ни секвенции e");continue}
  // частота шаблона — как у исходника, если разница в целых кадрах (29,97 и 30 — одно и то же)
  if(FPS[k]){var ts=tmpl.getSettings(),tf=1/ts.videoFrameRate.seconds;
    if(Math.round(tf)!=Math.round(FPS[k])){var f=new Time();f.ticks=String(Math.round(254016000000/FPS[k]));ts.videoFrameRate=f;tmpl.setSettings(ts);
      log.push("шаблон "+tmpl.name+": "+tf.toFixed(3)+" → "+FPS[k].toFixed(3)+" fps, как у исходника")}}
  var made=0;
  for(var c=0;c<bins.length;c++)for(var n=1;n<=NEED[k];n++){
    if(child(bins[c],""+n,1))continue;
    tmpl.clone();var ns=null;
    for(var i=app.project.sequences.numSequences-1;i>=0;i--){var s=app.project.sequences[i];if(s.name==tmpl.name+" Copy"){ns=s;break}}
    if(!ns){log.push("нет копии "+CATS[c]+" "+n);break}
    ns.name=""+n;ns.projectItem.name=""+n;ns.projectItem.moveBin(bins[c]);made++;
  }
  log.push(k+": создано "+made);
}
app.project.save();
return __result(log);
"""
p = os.path.join(S, "_setup.jsx")
FPS = {}
for k in NEED:                                    # s3 → e3.mp4
    v = video("e" + k[1:])
    if os.path.exists(v):
        FPS[k] = fps_of(v)
open(p, "w", encoding="utf-8").write(JSX.replace("__FPS__", json.dumps(FPS)).replace("__NEED__", json.dumps(NEED)).replace("__CATS__", json.dumps(list(DIRS.values()), ensure_ascii=False)))
print(subprocess.run(["node", "pp.mjs", p, "120000"], cwd=HERE, capture_output=True, text=True, encoding="utf-8").stdout)
