import json, math, sys
sys.stdout.reconfigure(encoding="utf-8")
FPS=25; M0=54.61; T_DROP=14.84; H=0.443; T_END=31.36
onsets=json.load(open("onsets.json"))
def fr(t): return round(t*FPS)/FPS
def snap(t_plan,tol=0.08):
    m=M0+t_plan; c=[(abs(o-m),-s,o) for o,s in onsets if abs(o-m)<=tol]
    if not c: return fr(t_plan)
    return math.floor((c and sorted(c)[0][2]-M0)*FPS+1e-6)/FPS
P=[]  # (id,item,src,ss,at,dur,audio)
def add(id_,src,ss,at,dur,**kw): P.append(dict(id=id_,src=src,ss=round(ss,3),at=round(at,3),dur=round(dur,3),**kw))
# интро 1:1
for i,(a,b,at) in enumerate([(707.36,710.52,0.0),(710.96,712.6,3.16),(712.6,714.04,4.8),(715.12,716.48,6.24),(724.12,726.24,7.6),(726.52,729.32,9.72),(733.68,734.48,12.52),(735.16,736.68,13.32)]):
    add(f"i{i+1:02d}","e2.mp4",a,at,b-a,zone="intro",audio=True)
# A: 14 полудолей, 6 планов подлиннее
A=[("a01","e2.mp4",854.15,2),("a02","e2.mp4",700.36,3),("a03","e7.mov",281.40,2),("a04","e4.mov",167.20,2),("a05","e7.mov",1035.56,3),("a06","e7.mov",389.60,2)]
t=T_DROP; hp=0
for id_,src,ss,u in A:
    hp+=u; tn=fr(T_DROP+hp*H); add(id_,src,ss,t,tn-t,zone="A",punch=True); t=tn
T_S=t
T_C0=snap(23.38)
add("b01","e4.mov",341.85,T_S,T_C0-T_S,zone="line",audio=True)
C=[("c01","e7.mov",308.40,3),("c02","e2.mp4",835.76,2),("c03","e2.mp4",837.92,2),("c04","e2.mp4",1092.44,2),("c05","e3.mp4",131.40,2),("c06","e10.mov",1141.50,3)]
hp=0; t=T_C0
for id_,src,ss,u in C:
    hp+=u; tn=snap(T_C0+hp*H); extra=dict(freeze=0.12) if id_=="c03" else {}
    add(id_,src,ss,t,tn-t,zone="C",punch=True,**extra); t=tn
T_F=t; add("f01","e2.mp4",704.70,T_F,T_END-T_F,zone="final",slow=0.5)
for p in P: print(p["id"],p["src"],"ss",p["ss"],"at",p["at"],"dur",p["dur"],p.get("freeze",""),"punch" if p.get("punch") else "")
print("T_S",T_S,"T_C0",T_C0,"T_F",T_F,"T_END",T_END,"shots",len(P))
json.dump(dict(plan=P,T_DROP=T_DROP,T_S=T_S,T_C0=T_C0,T_F=T_F,T_END=T_END,M0=M0),open("plan_v3.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
