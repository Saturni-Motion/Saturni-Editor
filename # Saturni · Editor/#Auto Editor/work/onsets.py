import numpy as np, subprocess, json
p="D:/# Audio/Sleep Token - Jaws.mp3"; a0=60.0; a1=100.0; sr=22050
raw=subprocess.run(["ffmpeg","-v","error","-ss",str(a0),"-t",str(a1-a0),"-i",p,"-ac","1","-ar",str(sr),"-f","f32le","-"],capture_output=True).stdout
y=np.frombuffer(raw,dtype=np.float32); hop=256; n=(len(y)-2048)//hop; win=np.hanning(2048)
S=np.array([np.abs(np.fft.rfft(y[i*hop:i*hop+2048]*win)) for i in range(n)]); fr=sr/hop
L=np.log1p(S*5); fl=np.maximum(0,np.diff(L,axis=0,prepend=L[:1])).sum(1)
t=np.arange(n)/fr+a0
th=np.percentile(fl,90)
pk=[(round(float(t[i]),3),round(float(fl[i]),1)) for i in range(2,n-2) if fl[i]>th and fl[i]==fl[i-3:i+4].max()]
json.dump(pk,open("onsets.json","w"))
print(len(pk), pk[:5])
