import json, subprocess, sys
import numpy as np
from scipy.io import wavfile
sys.stdout.reconfigure(encoding="utf-8")
SR=48000
PUB="../public"; SFX="D:/@Assets/! SFX/"
edl=json.load(open("edl.json",encoding="utf-8")); tr=json.load(open("transcripts.json",encoding="utf-8"))
clips={c["id"]:c for c in edl["clips"]}
TOTAL=edl["TOTAL"]; N=int((TOTAL+1.0)*SR)

def load(path,ss=0,dur=None):
    a=["ffmpeg","-v","error"]+(["-ss",str(ss)] if ss else [])+(["-t",str(dur)] if dur else [])+["-i",path,"-ar",str(SR),"-ac","2","-f","f32le","-"]
    y=np.frombuffer(subprocess.run(a,capture_output=True).stdout,dtype=np.float32)
    return y.reshape(-1,2).T.copy()
def place(bus,x,t,gain=1.0,fin=0.0,fout=0.0):
    x=x*gain; n=x.shape[1]
    if fin>0: k=min(int(fin*SR),n); x[:,:k]*=np.linspace(0,1,k)
    if fout>0: k=min(int(fout*SR),n); x[:,-k:]*=np.linspace(1,0,k)
    i=int(round(t*SR)); j=min(i+n,bus.shape[1]);
    if i<bus.shape[1]: bus[:,i:j]+=x[:,:j-i]
def curve(points):     # [(t,g)] линейная интерполяция → огибающая по SR
    ts=np.arange(N)/SR; P=np.array(points); return np.interp(ts,P[:,0],P[:,1])

# ---------- диалоги ----------
DLG=np.zeros((2,N),dtype=np.float32)
GAIN_DLG=2.0
for cid in ["i01","i02","i03","i04","i05","i06","i07","i08","b01"]:
    c=clips[cid]; x=load(f"{PUB}/{c['file']}"); place(DLG,x,c["at"],GAIN_DLG,fin=0.006,fout=0.006)
c=clips["i_tail"]; place(DLG,load(f"{PUB}/{c['file']}"),c["at"],GAIN_DLG,fin=0.004,fout=0.01)

# карта речи (для приглушения музыки): слова интро → время на таймлайне
speech=[]
for w0,w1,txt,p in tr["intro"]["words"]:
    if "Субтитры" in txt or txt.startswith("«"): continue
    for cid in ["i01","i02","i03","i04","i05","i06","i07","i08"]:
        c=clips[cid]; a=c["ss"]; b=a+c["dur"]
        s=max(w0,a); e=min(w1,b)
        if e>s: speech.append((c["at"]+s-a,c["at"]+e-a))
speech.sort()
merged=[]
for s,e in speech:
    if merged and s-merged[-1][1]<0.35: merged[-1][1]=max(merged[-1][1],e)
    else: merged.append([s,e])
print("речь интро:",[(round(a,2),round(b,2)) for a,b in merged])
ts=np.arange(N)/SR
mask=np.zeros(N)
for s,e in merged: mask[(ts>=s-0.12)&(ts<=e+0.25)]=1
# сглаживание: атака 60 мс, отпускание 300 мс
sm=np.zeros(N); a_att=1-np.exp(-1/(0.06*SR)); a_rel=1-np.exp(-1/(0.30*SR)); v=0.0
for i in range(N):
    m=mask[i]; v+= (a_att if m>v else a_rel)*(m-v); sm[i]=v
duck=sm

# ---------- музыка ----------
mus=load(f"{PUB}/audio/music_bed.wav"); MUS=np.zeros((2,N),dtype=np.float32); place(MUS,mus[:, :int((TOTAL+0.5)*SR)],0)
T_DROP=edl["T_DROP"]; T_S=edl["T_S"]; T_C0=edl["T_C0"]; T_F=edl["T_F"]; T_END=edl["T_END"]
intro_base=np.interp(ts,[0,0.5,12.3,T_DROP-0.04],[0.0,0.42,0.42,0.66])           # подъём к дропу
intro_gain=intro_base*(1-0.5*duck)                                              # речь: −7 дБ
main=curve([(0,0),(T_DROP-0.05,0),(T_DROP-0.04,0.68),(T_S-0.02,0.68),(T_S+0.12,0.06),(T_C0-0.06,0.06),(T_C0-0.01,0.70),
            (T_F,0.70),(T_END-0.9,0.28),(T_END,0.0),(TOTAL+1,0)])
gain_m=np.where(ts<T_DROP-0.045,intro_gain,main)
MUS*=gain_m.astype(np.float32)

# ---------- SFX ----------
SFXB=np.zeros((2,N),dtype=np.float32)
def sfx(file,at,gain,onset=0.0,dur=None,fin=0,fout=0.05):
    x=load(SFX+file,0,dur); place(SFXB,x,at-onset,gain,fin=fin,fout=fout)
# синтез райзера: шум с восходящим фильтром + тон, пик ровно на дропе
T=2.44; n=int(T*SR); rng=np.random.default_rng(7)
noise=rng.standard_normal(n); blk=2048; hop=512; win=np.hanning(blk); out=np.zeros(n+blk)
freqs=np.fft.rfftfreq(blk,1/SR)
for s in range(0,n-blk,hop):
    tt=s/n; fc=300*2**(5*tt); mask_f=np.exp(-(np.log2(np.maximum(freqs,1)/fc))**2/(2*0.7**2))
    out[s:s+blk]+=np.fft.irfft(np.fft.rfft(noise[s:s+blk]*win)*mask_f)*win
out=out[:n]; env=(np.arange(n)/n)**2.2
tone=np.sin(2*np.pi*np.cumsum(220*2**(3*np.arange(n)/n)/SR))*0.25
r=(out/np.abs(out).max()*0.9+tone)*env; r=r/np.abs(r).max()*0.8
riser=np.stack([r,r]).astype(np.float32)
place(SFXB,riser,T_DROP-T,0.5,fin=0.02,fout=0.0)
sfx("! check old/bass.drop.mp3",T_DROP-0.02,0.5,onset=0.06,dur=4.0,fout=0.6)
sfx("# Editors Pack/!Cinematic Hit Sound Effect.mp3",T_DROP,0.45,onset=1.86,dur=6.0,fout=1.0)
sfx("cut-loud.mp3",T_S-0.02,0.7,onset=0.02)
sfx("impulse-little.mp3",T_C0-0.02,0.6,onset=0.0,dur=1.0,fout=0.3)
c3=clips["c03"]; click=c3["at"]+c3["dur"]-c3["freeze"]
sfx("camera-shot-reload.mp3",click,0.9,onset=0.06,dur=1.0,fout=0.2)
sfx("impulse-out-echo.mp3",T_F-0.5,0.45,onset=0.0,dur=3.0,fout=0.8)
sfx("#stone-crash.mp3",T_END,0.6,onset=0.02,dur=1.2,fout=0.3)

mix=DLG+MUS+SFXB
pk=np.abs(mix).max(); print("peak before limiter",round(float(pk),3))
# мягкий лимитер (tanh) только если пик выше 0.98
if pk>0.95: mix=np.tanh(mix*(0.95/pk)*1.15)/np.tanh(1.15)*0.97
mix=mix[:, :int((TOTAL)*SR)]
wavfile.write(f"{PUB}/audio/mix.wav",SR,(mix.T*32767).astype(np.int16))
# отчёт по уровням
def db(x): return 20*np.log10(np.sqrt((x**2).mean())+1e-9)
def seg(name,a,b):
    i,j=int(a*SR),int(b*SR)
    print(f"{name:22s} {a:5.1f}-{b:5.1f}  диалог {db(DLG[:,i:j]):6.1f}  музыка {db(MUS[:,i:j]):6.1f}  sfx {db(SFXB[:,i:j]):6.1f}  ИТОГ {db(mix[:,i:j]):6.1f} dBFS")
seg("интро речь",0.6,12.4); seg("строб+райзер",12.4,14.84); seg("дроп A",14.84,21.0); seg("реплика",21.1,23.3); seg("тяжёлая C",23.4,31.7); seg("финал",31.76,33.4)
np.save("duck.npy",duck.astype(np.float32))
