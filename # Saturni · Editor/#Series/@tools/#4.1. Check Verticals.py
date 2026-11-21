#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
#4.1. Check Verticals.py — проверка кадрирования вертикалок 4.1 без рендера из Premiere
(Saturni, 2026-09-25: «пререндерить себе, сверить каждую склейку, насколько удачно получилась»).

Шаг 1 (Premiere, только чтение):
    node "@tools/mjs/#4.1. Dump Vertical Geometry.mjs" geom.json [фильтр имени]
Шаг 2 (без Premiere):
    python "@tools/#4.1. Check Verticals.py" geom.json --project-dir "D:\# Video\#Поляна\Развлечения" --out <папка>

Как считается окно кропа. Вертикалка и горизонталь — один и тот же таймлайн (вертикалка —
дубль горизонтали), поэтому кадр вертикалки в момент t = кусок кадра горизонтального рендера
`<имя> ` 1h.mp4` в тот же момент. Для клипа вертикалки со Scale S и Position X p (норм. 0..1)
и клипа горизонтали с тем же исходником (Scale h, Position X hx) — обратная формула к
verticalPositionX() из 4.1:
    центр окна в пикселях рендера  x_r = hx*1920 + (540 - p*1080) * h / S
    ширина окна                    W   = 1080 * h / S
Лица — YuNet (та же модель, что в 4.1. VReframe-SED.py) на 3 кадрах клипа (начало/середина/конец).

Вердикт на клип:
  ok      — главное лицо (самое крупное) целиком в окне; или лиц нет нигде (пейзаж/общий план);
  offc    — главное лицо в окне, но прижато к краю (центр дальше 30% ширины окна от центра);
  cut     — лицо разрезано краем окна (≥20% ширины лица снаружи);
  miss    — лица в кадре есть, но в окно не попало ни одно (окно на пустом месте);
  two     — одно лицо в окне, другое крупное целиком снаружи (двойной план — выбор неизбежен,
            смотреть глазами, тот ли говорит).
Выход: report.json + report.txt + <вертикалка>.jpg — по строке на клип: горизонтальный кадр с
окном (зелёная рамка) и лицами (красные) + то, что реально видно в вертикалке (3 кадра).
"""
import argparse, json, os, re, subprocess, sys
import numpy as np
import cv2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "face_detection_yunet_2023mar.onnx")
if not YUNET.isascii():   # OpenCV не читает ONNX по не-ASCII пути («# Saturni · Editor», 2026-11-05)
    import shutil
    from pathlib import Path
    _d = Path.home() / ".cache" / "vreframe"
    _d.mkdir(parents=True, exist_ok=True)
    _c = str(_d / os.path.basename(YUNET))
    if not os.path.exists(_c) or os.path.getsize(_c) != os.path.getsize(YUNET):
        shutil.copy2(YUNET, _c)
    YUNET = _c
RW, RH = 1920, 1080          # горизонтальный рендер (всегда 1920x1080, см. инструкцию 4.1)
DW = 960                     # ширина кадра для детекции


def find_render(project_dir, name, folder):
    want = {f"{name} ` 1h.mp4", f"{name}.mp4"}
    hits = []
    for dp, dn, fn in os.walk(project_dir):
        for f in fn:
            if f in want:
                hits.append(os.path.join(dp, f))
    # бин "s1" = папка "Серия 1"/"Series 1" (2026-10-29: "1.mp4" лежит в обеих сериях Мусора)
    norm = lambda x: re.sub(r"^(серия|series|s)\s*(?=\d+$)", "s", x.lower())
    own = [h for h in hits if folder and norm(folder) in [norm(x) for x in h.split(os.sep)]]
    return (own or hits or [None])[0]


def grab(video, t):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={RW}:{RH}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"], capture_output=True)
    if len(p.stdout) < RW * RH * 3:
        return None
    return np.frombuffer(p.stdout[:RW * RH * 3], np.uint8).reshape(RH, RW, 3).copy()


_det = None
def faces(img):
    global _det
    small = cv2.resize(img, (DW, int(RH * DW / RW)))
    if _det is None:
        _det = cv2.FaceDetectorYN.create(YUNET, "", (small.shape[1], small.shape[0]), 0.7, 0.3, 5000)
    _det.setInputSize((small.shape[1], small.shape[0]))
    _, f = _det.detect(small)
    k = RW / DW
    out = []
    if f is not None:
        for r in f:
            x, y, w, h = [float(v) * k for v in r[:4]]
            if w * h >= (RW * 0.025) ** 2 and float(r[-1]) >= 0.82:        # отсекаем мелочь на фоне
                out.append((x, y, w, h, float(r[-1])))
    return out


def verdict(fs, x0, x1):
    if not fs:
        return "ok", None
    W = x1 - x0
    main = max(fs, key=lambda f: f[2] * f[3])
    def inside_frac(f):
        a, b = f[0], f[0] + f[2]
        return max(0.0, min(b, x1) - max(a, x0)) / f[2]
    fr = [inside_frac(f) for f in fs]
    full_in = [f for f, q in zip(fs, fr) if q >= 0.8]
    sliced = [f for f, q in zip(fs, fr) if 0.2 <= q < 0.8 and f[2] * f[3] >= 0.35 * main[2] * main[3]]
    if sliced:
        return "cut", None
    if not full_in:
        return "miss", None
    big_out = [f for f, q in zip(fs, fr) if q < 0.2 and f[2] * f[3] >= 0.5 * main[2] * main[3]]
    tgt = max(full_in, key=lambda f: f[2] * f[3])
    off = abs((tgt[0] + tgt[2] / 2) - (x0 + x1) / 2) / W
    if big_out:
        return "two", off
    if off > 0.30:
        return "offc", off
    return "ok", off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = json.load(open(a.geom, encoding="utf-8"))
    report, lines = [], []
    for seq in data:
        name = seq["name"].replace(" ` 1v", "")
        parts = seq["path"].split("\\")
        folder = parts[parts.index("v") - 1] if "v" in parts and parts.index("v") > 0 and parts[parts.index("v") - 1] != "~" else ""
        render = find_render(a.project_dir, name, folder)
        if not render or not seq.get("horizontal"):
            lines.append(f"!! {seq['name']}: нет рендера/горизонтали"); continue
        hclips = seq["horizontal"]
        rows, res = [], []
        vclips = sorted([c for c in seq["vertical"] if c["track"] <= 2], key=lambda c: c["start"])
        for i, c in enumerate(vclips):
            dur = c["end"] - c["start"]
            if dur < 0.08:
                continue
            ts = [c["start"] + min(0.2, dur / 4), (c["start"] + c["end"]) / 2, c["end"] - min(0.2, dur / 4)]
            hc = next((h for h in hclips if h["start"] - 0.02 <= ts[1] < h["end"] + 0.02), None)
            h = (hc or {}).get("scale") or 100.0
            hx = (hc or {}).get("posX") if (hc or {}).get("posX") is not None else 0.5
            S, p = c["scale"] or 100.0, c["posX"] if c["posX"] is not None else 0.5
            W = 1080.0 * h / S
            xr = hx * RW + (540.0 - p * 1080.0) * h / S
            x0, x1 = xr - W / 2, xr + W / 2
            vs, fr_imgs = [], []
            for t in ts:
                img = grab(render, t)
                if img is None:
                    continue
                fs = faces(img)
                vs.append(verdict(fs, x0, x1))
                fr_imgs.append((img, fs))
            order = ["cut", "miss", "two", "offc", "ok"]
            worst = min((v[0] for v in vs), key=order.index) if vs else "?"
            res.append({"i": i, "track": c["track"], "start": round(c["start"], 2), "end": round(c["end"], 2),
                        "scale": S, "posX": p, "win": [round(x0), round(x1)], "verdicts": [v[0] for v in vs], "worst": worst})
            if fr_imgs:
                img, fs = fr_imgs[len(fr_imgs) // 2]
                th = img.copy()
                cv2.rectangle(th, (int(x0), 0), (int(x1), RH - 1), (0, 255, 0), 8)
                for f in fs:
                    cv2.rectangle(th, (int(f[0]), int(f[1])), (int(f[0] + f[2]), int(f[1] + f[3])), (0, 0, 255), 6)
                th = cv2.resize(th, (384, 216))
                col = {"ok": (0, 160, 0), "offc": (0, 200, 255), "two": (255, 160, 0), "cut": (0, 0, 255), "miss": (0, 0, 255)}.get(worst, (128, 128, 128))
                cv2.putText(th, f"#{i} {c['start']:.2f}-{c['end']:.2f} V{c['track']} {worst}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
                cv2.putText(th, f"#{i} {c['start']:.2f}-{c['end']:.2f} V{c['track']} {worst}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
                crops = []
                for im, _ in fr_imgs:
                    a0, a1 = int(max(0, x0)), int(min(RW, x1))
                    cr = im[:, a0:a1] if a1 > a0 + 4 else np.zeros((RH, 16, 3), np.uint8)
                    crops.append(cv2.resize(cr, (max(8, int(216 * cr.shape[1] / RH)), 216)))
                row = np.hstack([th] + [np.pad(x, ((0, 0), (4, 0), (0, 0))) for x in crops])
                rows.append(row)
        if rows:
            wmax = max(r.shape[1] for r in rows)
            sheet = np.vstack([np.pad(r, ((0, 4), (0, wmax - r.shape[1]), (0, 0))) for r in rows])
            cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(os.path.join(a.out, (folder + " - " if folder else "") + seq["name"].replace(" ` ", " ") + ".jpg"))
        bad = [r for r in res if r["worst"] in ("cut", "miss")]
        warn = [r for r in res if r["worst"] in ("two", "offc")]
        lines.append(f"{(folder + '/') if folder else ''}{seq['name']}: клипов {len(res)}, ok {sum(r['worst']=='ok' for r in res)}, "
                     f"внимание {len(warn)}, плохо {len(bad)}")
        for r in bad + warn:
            lines.append(f"    #{r['i']} {r['start']:.2f}-{r['end']:.2f} V{r['track']} {r['worst']} {r['verdicts']} окно {r['win']}")
        report.append({"name": seq["name"], "render": render, "clips": res})
    json.dump(report, open(os.path.join(a.out, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(a.out, "report.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
