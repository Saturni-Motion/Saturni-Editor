import json, math, os, subprocess, sys
import numpy as np, cv2
sys.stdout.reconfigure(encoding="utf-8")
V="D:/# Video/#Поляна/Олдскул (2 сезон)/@"
FPS=25; F=1/FPS
PUB="../public"; os.makedirs(f"{PUB}/clips",exist_ok=True); os.makedirs(f"{PUB}/audio",exist_ok=True)
MUSIC_SRC="D:/# Audio/Sleep Token - Jaws.mp3"
M0=54.61                       # музыка в секунде 0 таймлайна = 54.61 с трека → дроп 69.41 с ↔ 14.80 (+1 кадр)
T_DROP=14.84
H=0.443                        # полу-доля (0.886 с = доля при ~135 BPM в половинном счёте)
onsets=json.load(open("onsets.json"))

def fr(t): return round(t*FPS)/FPS
def snap(t_plan, tol=0.08):
    m=M0+t_plan
    c=[(abs(o-m),-s,o) for o,s in onsets if abs(o-m)<=tol]
    if not c: return fr(t_plan)
    o=sorted(c)[0][2]
    return math.floor((o-M0)*FPS+1e-6)/FPS      # режем на кадр раньше/в момент удара

clips=[]   # порядок = порядок на таймлайне
def add(id_,src,ss,at,dur,**kw):
    clips.append(dict(id=id_,src=src,ss=ss,at=round(at,3),dur=round(dur,3),**kw))

# ---------- ИНТРО: 1:1 клипы пользователя из edit2 (аудио + видео) ----------
intro=[(707.36,710.52,0.0),(710.96,712.6,3.16),(712.6,714.04,4.8),(715.12,716.48,6.24),(724.12,726.24,7.6),
       (726.52,729.32,9.72),(733.68,734.48,12.52),(735.16,736.2,13.32)]
for i,(a,b,at) in enumerate(intro): add(f"i{i+1:02d}","e2.mp4",a,at,b-a,zone="intro",audio=True)
# строб: 4 вспышки по 0.08 с с чёрными промежутками (как у пользователя); звук идёт целиком отдельным куском
for i,(a,at) in enumerate([(736.24,14.40),(736.36,14.52),(736.48,14.64),(736.6,14.76)]):
    add(f"s{i+1}","e2.mp4",a,at,0.08,zone="intro",audio=False,strobe=True)
add("i_tail","e2.mp4",736.2,14.36,0.48,zone="intro",audio=True,videoless=True)   # звук 736.2–736.68 непрерывно

# ---------- СЕГМЕНТ A: от дропа до «вдоха» (14 полудолей) ----------
A=[("a01","e2.mp4",854.15,2,"hero"),("a01b","e2.mp4",700.40,2,None),("a02","e7.mov",281.40,2,None),("a03","e4.mov",167.30,2,None),
   ("a04","e7.mov",1035.56,2,None),("a05","e4.mov",175.10,1,None),("a06","e7.mov",1041.50,1,None),
   ("a07","e4.mov",177.40,1,None),("a08","e7.mov",389.70,1,None)]
t=T_DROP; hp=0
for id_,src,ss,units,tag in A:
    tn=fr(T_DROP+(hp+units)*H) if id_!="a08" else fr(T_DROP+14*H)
    add(id_,src,ss,t,tn-t,zone="main",tag=tag); t=tn; hp+=units
T_S=t                                   # ≈ 21.04
# ---------- «ВДОХ»: единственная реплика, музыка приглушена ----------
T_C0=snap(23.38)                        # возвращение тяжёлой части
add("b01","e4.mov",341.85,T_S,T_C0-T_S,zone="main",audio=True,tag="line")
# ---------- СЕГМЕНТ C: вторая тяжёлая часть, склейки на онсеты ----------
C=[("c01","e7.mov",308.90,2),("c02","e2.mp4",835.76,2),("c03","e2.mp4",837.92,2),("c04","e2.mp4",1159.05,1),
   ("c05","e2.mp4",1092.70,1),("c06","e3.mp4",131.50,1),("c07","e1.mp4",361.40,1),("c08","e11.mov",72.10,1),
   ("c09","e10.mov",1141.90,2),("c10","e8.mov",932.00,2),("c11","e8.mov",936.84,2),("c12","e2.mp4",693.60,2)]
hp=0; t=T_C0
for id_,src,ss,units in C:
    tn=snap(T_C0+(hp+units)*H); 
    extra={}
    if id_=="c03": extra=dict(freeze=0.12,click=True)
    add(id_,src,ss,t,tn-t,zone="main",**extra); t=tn; hp+=units
T_F=t
T_END=33.40
add("f01","e2.mp4",704.70,T_F,T_END-T_F,zone="final",slow=0.5)
TOTAL=fr(T_END+0.2)

# ---------- вырезаем клипы (точно по кадрам) ----------
def probe_face(path):
    cap=cv2.VideoCapture(path); n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); pts=[]
    det=cv2.FaceDetectorYN.create("D:/@Hub/# Saturni · Editor/#Series/@tools/models/face_detection_yunet_2023mar.onnx","",(1920,1080),0.6)
    for k in (0.15,0.5,0.85):
        cap.set(cv2.CAP_PROP_POS_FRAMES,int(n*k)); ok,img=cap.read()
        if not ok: continue
        det.setInputSize((img.shape[1],img.shape[0])); _,faces=det.detect(img)
        if faces is not None and len(faces):
            f=max(faces,key=lambda z:z[2]*z[3]); pts.append(((f[0]+f[2]/2)/img.shape[1],(f[1]+f[3]/2)/img.shape[0],f[2]/img.shape[1]))
    cap.release()
    if not pts: return (0.5,0.42,0.1)
    a=np.mean(pts,axis=0); return tuple(round(float(x),3) for x in a)

for c in clips:
    out=f"{PUB}/clips/{c['id']}.mp4"; c["file"]=f"clips/{c['id']}.mp4"
    dur=c["dur"]; ss=c["ss"]
    if c.get("slow"):
        need=dur*c["slow"]+0.2
        cmd=["ffmpeg","-v","error","-y","-ss",str(ss),"-t",f"{need:.3f}","-i",f"{V}/{c['src']}","-an",
             "-vf",f"setpts={1/c['slow']}*PTS,minterpolate=fps=25:mi_mode=mci:mc_mode=aobmc:vsbmc=1,fps=25","-t",f"{dur+0.2:.3f}",
             "-c:v","libx264","-crf","12","-preset","fast","-pix_fmt","yuv420p","-r","25",out]
    else:
        vf="fps=25,format=yuv420p"
        aud=["-c:a","aac","-b:a","256k","-ar","48000","-ac","2"] if c.get("audio") else ["-an"]
        if c.get("videoless"): 
            cmd=["ffmpeg","-v","error","-y","-ss",str(ss),"-t",f"{dur:.3f}","-i",f"{V}/{c['src']}","-vn","-ar","48000","-ac","2",out.replace(".mp4",".wav")]
            c["file"]=f"clips/{c['id']}.wav"
        else:
            cmd=["ffmpeg","-v","error","-y","-ss",str(ss),"-t",f"{dur+ (0.2 if c.get('freeze') else 0):.3f}","-i",f"{V}/{c['src']}","-vf",vf,"-c:v","libx264","-crf","12","-preset","fast","-r","25","-g","25"]+aud+[out]
    subprocess.run(cmd,check=True)
    if not c.get("videoless"):
        c["face"]=probe_face(out) if not c.get("slow") or True else None
    print(c["id"],c["src"],c["ss"],"@",c["at"],"dur",c["dur"],c.get("face"))
json.dump(dict(clips=clips,T_DROP=T_DROP,T_S=T_S,T_C0=T_C0,T_F=T_F,T_END=T_END,TOTAL=TOTAL,M0=M0),open("edl.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("T_S",T_S,"T_C0",T_C0,"T_F",T_F,"END",T_END)
