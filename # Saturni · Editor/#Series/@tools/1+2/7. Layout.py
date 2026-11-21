# -*- coding: utf-8 -*-
"""Разложить EDL в Premiere: python "7. Layout.py" e3 Active [номера]. Секвенции лежат в бине серии, в папках режимов. Читка секвенции сверяется с EDL."""
import json, subprocess, sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moments_lib import S, HERE, DIRS, video
st, mode = sys.argv[1], sys.argv[2]
only = set(int(x) for x in sys.argv[3:])
bin_ = "s" + st[1:] + "\\" + DIRS[mode]
edl = json.load(open(S + rf"\edl\{st}_{mode}.json", encoding="utf-8"))
COMMENT_JSX = r'''
function setComment(it,v){var C="Column.PropertyText.Comment",U="http://ns.adobe.com/premierePrivateProjectMetaData/1.0/";
  if(ExternalObject.AdobeXMPScript===undefined)ExternalObject.AdobeXMPScript=new ExternalObject("lib:AdobeXMPScript");
  XMPMeta.registerNamespace(U,"premierePrivateProjectMetaData");var x=new XMPMeta(it.getProjectMetadata());x.setProperty(U,C,v);it.setProjectMetadata(x.serialize(),[C])}
'''
FADES_JSX = open(os.path.join(HERE, "audio_fades.jsx"), encoding="utf-8").read()   # аудиопереход 2 кадра на каждой склейке
TPL = r'''
function allSeq(){var o=[];for(var i=0;i<app.project.sequences.numSequences;i++){var s=app.project.sequences[i];var p="";try{p=s.projectItem.treePath}catch(e){}o.push({s:s,p:p})}return o}
function findSeqPath(path){var a=allSeq();for(var i=0;i<a.length;i++)if(a[i].p.slice(-path.length)==path)return a[i].s;return null}
function findItem(root,n){for(var i=0;i<root.children.numItems;i++){var c=root.children[i];if(c.name==n)return c;if(c.type==2){var r=findItem(c,n);if(r)return r}}return null}
function T(x){var t=new Time();t.seconds=x;return t}
function clear(q){for(var t=0;t<2;t++){var tr=t?q.audioTracks:q.videoTracks;for(var k=0;k<tr.numTracks;k++){var c=tr[k].clips;for(var i=c.numItems-1;i>=0;i--){c[i].remove(false,false)}}}}
var E=__E__,q=findSeqPath(E.path),it=findItem(app.project.rootItem,E.item);
if(!q)return __result({err:"нет секвенции "+E.path});
if(!it)return __result({err:"нет исходника "+E.item});
app.project.activeSequence=q;
clear(q);
for(var i=0;i<E.p.length;i++){var p=E.p[i];it.setInPoint(p.a[0]+0.002,4);it.setOutPoint(p.a[1]+0.002,4);q.videoTracks[0].overwriteClip(it,p.t[0]);}
if(E.scale!=100){var V0=q.videoTracks[0].clips;for(var i=0;i<V0.numItems;i++){var cs=V0[i].components;for(var j=0;j<cs.numItems;j++)if(cs[j].matchName=="AE.ADBE Motion"){var ps=cs[j].properties;for(var k=0;k<ps.numItems;k++)if(ps[k].displayName=="Scale")ps[k].setValue(E.scale,true)}}}
it.clearInPoint();it.clearOutPoint();
var V=q.videoTracks[0].clips;
for(var i=1;i<E.p.length;i++){
  var cur=E.p[i],prev=E.p[i-1],sh=cur.vt[0]-cur.t[0];
  if(Math.abs(sh)<0.001)continue;
  var a=V[i-1],b=V[i];
  if(sh>0){b.start=T(cur.vt[0]);b.inPoint=T(cur.v[0]);a.end=T(prev.vt[1]);a.outPoint=T(prev.v[1]);}
  else{a.end=T(prev.vt[1]);a.outPoint=T(prev.v[1]);b.start=T(cur.vt[0]);b.inPoint=T(cur.v[0]);}
}
var fd=fades(q,[0],2);
if(E.note)setComment(q.projectItem,E.note);
var d=function(tr){var o=[];for(var i=0;i<tr.clips.numItems;i++){var c=tr.clips[i];o.push([c.start.seconds,c.end.seconds,c.inPoint.seconds,c.outPoint.seconds])}return o};
return __result({v:d(q.videoTracks[0]),a:d(q.audioTracks[0]),fades:fd});
'''
def fill_scale(path):
    """Масштаб, при котором исходник закрывает кадр 1920×1080 без полей (лишнее срезается по краям)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(","))
    return round(max(1920 / w, 1080 / h) * 100, 2)
SCALE = fill_scale(video(st))
bad = 0
for m in edl:
    if only and m['n'] not in only: continue
    E = dict(path=f"\\{bin_}\\{m['n']}", item=st + ".mp4", p=m['pieces'], scale=SCALE,
             note=f"{mode} · {st} №{m['n']} «{m['name']}»")
    jsx = os.path.join(S, "_lay.jsx")
    open(jsx, "w", encoding="utf-8").write(FADES_JSX + COMMENT_JSX + TPL.replace("__E__", json.dumps(E, ensure_ascii=False)))
    r = subprocess.run(["node", "pp.mjs", jsx, "120000"], cwd=HERE, capture_output=True, text=True, encoding="utf-8")
    try:
        o = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print("ОШИБКА", m['n'], r.stdout[:300], r.stderr[:300]); bad += 1; continue
    if 'err' in o:
        print("ОШИБКА", m['n'], o); bad += 1; continue
    errs = []
    if len(o['v']) != len(m['pieces']) or len(o['a']) != len(m['pieces']):
        errs.append(f"клипов V{len(o['v'])} A{len(o['a'])} из {len(m['pieces'])}")
    else:
        for i, p in enumerate(m['pieces']):
            for got, want in ((o['v'][i], p['vt'] + p['v']), (o['a'][i], p['t'] + p['a'])):
                if max(abs(x - y) for x, y in zip(got, want)) > 0.021:
                    errs.append(f"кусок {i + 1}: {got} != {want}")
    print(f"{bin_}/{m['n']} {m['name']}: {m['dur']:.2f}с кусков {len(m['pieces'])}", "ОК" if not errs else errs[:3], flush=True)
    bad += bool(errs)
print("итог ошибок", bad)
