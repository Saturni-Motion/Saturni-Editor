import json, subprocess, sys, os
sys.stdout.reconfigure(encoding="utf-8")
V="D:/# Video/#Поляна/Олдскул (2 сезон)/@"
# (id, файл, начало, конец) — диапазоны из секвенции highlights + окно интро edit2, с запасом
H=[("h01","e2.mp4",693.48,695.52),("h02","e2.mp4",700.36,702.12),("h03","e2.mp4",704.28,705.56),
("h04","e2.mp4",835.76,836.92),("h05","e2.mp4",837.92,839.04),("h06","e2.mp4",1092.44,1093.68),
("h07","e2.mp4",1158.96,1160.6),("h08","e3.mp4",131.16,133.0),("h09","e3.mp4",181.32,182.88),
("h10","e4.mov",167.08,168.28),("h11","e4.mov",174.96,176.08),("h12","e4.mov",177.2,178.36),("h13","e4.mov",342.12,343.6),
("h14","e7.mov",281.4,282.8),("h15","e7.mov",298.72,299.64),("h16","e7.mov",389.44,390.92),("h17","e7.mov",1035.56,1037.0),
("h18","e7.mov",1041.36,1042.44),("h19","e7.mov",1277.12,1278.44),("h20","e8.mov",931.92,933.16),("h21","e8.mov",936.84,937.76),
("h22","e7.mov",307.8,310.76),("h23","e10.mov",1140.96,1144.52),("h24","e11.mov",71.96,72.8),("h25","e1.mp4",361.2,362.96),
("h26","e2.mp4",854.08,855.2),("h27","e7.mov",1286.4,1287.96),("intro","e2.mp4",706.0,737.0)]
PAD=0.8
os.makedirs("tw",exist_ok=True)
from faster_whisper import WhisperModel
try:
    m=WhisperModel("large-v3-turbo",device="cuda",compute_type="int8_float16"); print("cuda",flush=True)
except Exception as e:
    print("cuda fail",e,flush=True); m=WhisperModel("large-v3-turbo",device="cpu",compute_type="int8")
out={}
for id_,f,a,b in H:
    a0=max(0,a-(0 if id_=="intro" else PAD)); b0=b+(0 if id_=="intro" else PAD)
    wav=f"tw/{id_}.wav"
    subprocess.run(["ffmpeg","-v","error","-y","-ss",str(a0),"-t",str(b0-a0),"-i",f"{V}/{f}","-vn","-ac","1","-ar","16000",wav],check=True)
    segs,_=m.transcribe(wav,language="ru",word_timestamps=True,vad_filter=False,condition_on_previous_text=False,beam_size=5)
    words=[]
    for s in segs:
        for w in (s.words or []):
            words.append([round(a0+w.start,2),round(a0+w.end,2),w.word.strip(),round(w.probability,2)])
    out[id_]={"src":f,"range":[a,b],"window":[round(a0,2),round(b0,2)],"words":words}
    print(id_,f,a,b,"|"," ".join(w[2] for w in words),flush=True)
json.dump(out,open("transcripts.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("DONE",flush=True)
