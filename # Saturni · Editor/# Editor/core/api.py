# -*- coding: utf-8 -*-
r"""Saturni · Editor: всё, что вызывает страница (window.pywebview.api.*), и сохранение результата."""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import webview

from common import *
from settings import *
from audio import *
from video import *
from image import *
from effects import *
from source import Source

class Api(DebugMixin):
    def __init__(self, path: Path):
        self.tmp = Path(tempfile.mkdtemp(prefix="saturni_editor_"))
        self.project, self.project_path = None, None
        if path.suffix.lower() == PROJECT_EXT:             # a project: its files, then its state goes to the page
            data = json.loads(path.read_text(encoding="utf-8"))
            missing = [f for f in data["files"] if not Path(f).is_file()]
            if missing:
                raise FileNotFoundError("Missing: " + ", ".join(Path(f).name for f in missing))
            self.sources = []
            for f in data["files"]:
                self._new_source(Path(f))
            self.project, self.project_path = data, path
            remember_recent(path, "projects")
        else:
            self.sources = [Source(path, self.tmp, 0)]
            remember_recent(path)
        self.prog = {"pct": 0}
        self._debug_dir = str(APP_DIR / "⿻" / "@debug")
        self._window = None
        self._events, self._ev_lock = [], threading.Lock()
        threading.Thread(target=self._emit_loop, daemon=True).start()

    # ---- events to the page (the debug module's voice notes use them)
    def _emit(self, kind, data=None):
        with self._ev_lock:
            self._events.append({"type": kind, "data": data})

    def _emit_loop(self):
        while True:
            time.sleep(0.05)
            if not self._window:
                continue
            with self._ev_lock:
                evs, self._events = self._events, []
            if evs:
                try:
                    self._window.evaluate_js(f"window.__emit && window.__emit({json.dumps(evs, ensure_ascii=False)})")
                except Exception:
                    pass

    # ---- data for the page
    def load(self):
        return {"sources": [s.public() for s in self.sources], "colors": COLORS, "options": OPTIONS,
                "defColors": DEFAULT_COLORS, "defOptions": DEFAULT_OPTIONS, "colorNames": COLOR_NAMES, "state": STATE,
                "project": self.project and {"state": self.project["state"], "name": self.project_path.stem}}

    def save_project(self, state: dict, as_new: bool = False):
        """The files and everything done to them, in one small JSON file next to the first file."""
        path = self.project_path
        if as_new or not path:
            first = self.sources[0].path
            got = webview.windows[0].create_file_dialog(webview.SAVE_DIALOG, directory=str(first.parent),
                                                        save_filename=first.stem + PROJECT_EXT,
                                                        file_types=(f"Saturni · Editor project (*{PROJECT_EXT})",))
            if not got:
                return {"ok": False}
            path = Path(got if isinstance(got, str) else got[0])
            if path.suffix.lower() != PROJECT_EXT:
                path = path.with_suffix(PROJECT_EXT)
        data = {"app": "Saturni · Editor", "version": 1, "files": [str(s.path) for s in self.sources], "state": state}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        self.project, self.project_path = data, path
        remember_recent(path, "projects")
        return {"ok": True, "name": path.stem}

    def set_state(self, key: str, value):
        """Layouts and the like: kept in @settings.json without asking."""
        if key in ("layouts", "layout"):
            write_state(key, value)
        return True

    def wave_rate(self, i: int, n: int):
        return self.sources[i].wave_rate(n)

    def proxy(self, i: int):
        return {"ok": self.sources[i].proxy()}

    def keyframes(self, i: int):
        s = self.sources[i]
        return s.keyframes() if s.info["video"] and not s.info.get("still") else []

    def progress(self):
        return self.prog

    def add_files(self, audio_only=False):
        exts = ";".join(f"*{e}" for e in sorted(PLAYABLE if audio_only else MEDIA_EXT | PHOTO_EXT))
        paths = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                                      directory=str(self.sources[0].path.parent),
                                                      file_types=(f"{'Audio' if audio_only else 'Media'} ({exts})", "All files (*.*)"))
        added, bad = [], []
        for p in paths or []:
            p = Path(p)
            if p.suffix.lower() not in MEDIA_EXT | PHOTO_EXT:
                bad.append(p.name)
                continue
            try:
                added.append(self._new_source(p).public())
            except Exception:
                bad.append(p.name)
        return {"added": added, "bad": bad}

    def _new_source(self, p: Path) -> Source:
        s = Source(p, self.tmp, len(self.sources))
        if s.info["kind"] == "photo" and self.sources:     # a picture next to others: a video that stands still, as long as you stretch it
            s.info = {**s.info, "kind": "video", "video": True, "still": True, "duration": 3600.0, "fps": 30.0,
                      "vcodec": "image", "vbr": 0, "pix": ""}
        if s.info["kind"] != "photo" and s.info["duration"] <= 0:
            raise ValueError(p.name)
        self.sources.append(s)
        return s

    def exists(self, name: str, ext: str, deleting: list):
        f = self.sources[0].path.parent / (name + ext)
        gone = {self.sources[i].path.resolve() for i in deleting}
        return f.exists() and f.resolve() not in gone

    # ---- settings: # Editor\@settings.json
    def save_settings(self, colors: dict, options: dict):
        try:
            for k, v in colors.items():
                if k not in DEFAULT_COLORS or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v)):
                    raise ValueError(f"bad color {k}={v}")
            low = max(-120, min(-6, int(options["meterMin"])))
            opts = {"photoQuality": max(0, min(100, int(options["photoQuality"]))),
                    "playMode": options["playMode"] if options["playMode"] in ("fast", "frames", "precise") else "fast",
                    "preview": int(options["preview"]) if int(options["preview"]) in (1, 2, 4) else 1,
                    "loop": bool(options["loop"]), "meterMin": low,
                    "meterMax": max(low + 6, min(24, int(options["meterMax"]))),
                    "overwrite": bool(options.get("overwrite"))}
            write_settings(colors, opts)
            COLORS.update(colors)
            OPTIONS.update(opts)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # ---- saving
    def save(self, q: dict):
        first = self.sources[0].path
        used = self.sources[:int(q.get("nsrc", 1))]
        mode = q.get("mode", "replace")
        props = used[int(q.get("props", 0))] if int(q.get("props", 0)) < len(used) else used[0]
        keep = bool(q.get("keepProps", True)) or mode != "new"
        if mode == "new":
            name = q["name"]
            out = first.parent / (name + first.suffix)
            if q.get("auto"):                          # quick "save as new": the next free name
                k = 2
                while out.exists():
                    out = first.parent / f"{name} ({k}){first.suffix}"
                    k += 1
            dele = {s.path.resolve() for s in used} if q.get("delOrig") else set()
            if out.exists() and out.resolve() not in dele:
                return {"ok": False, "msg": f"'{out.name}' already exists"}
        else:
            out = first
        tmpdir = Path(tempfile.mkdtemp(prefix="saturni_editor_", dir=first.parent))
        tmp = tmpdir / ("out" + first.suffix)
        self.prog = {"pct": 0}
        try:
            if used[0].info["kind"] == "photo":
                r = self.save_photo(q, tmp, keep)
            else:
                r = self.save_media(q, used, props, tmp, tmpdir, keep)
            if r:
                return r
            kept = mode == "replace" and not OPTIONS.get("overwrite")
            if kept:                                   # the original lies in the @ folder, the new file takes its name
                box = first.parent / "@"
                box.mkdir(exist_ok=True)
                bak, k = box / first.name, 2
                while bak.exists():
                    bak = box / f"{first.stem} ({k}){first.suffix}"
                    k += 1
                os.replace(first, bak)
            if mode == "new" and q.get("delOrig"):
                for s in used:
                    recycle(s.path)
            os.replace(tmp, out)
            self.prog = {"pct": 100}
            msg = f"Saved as {out.name}" if mode == "new" else "Saved, the original is in @" if kept else "Saved"
            return {"ok": True, "msg": msg + (f" · {self.note}" if getattr(self, "note", "") else "")}
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def save_photo(self, q: dict, tmp: Path, keep: bool):
        import numpy as np
        from PIL import Image, ImageOps, JpegImagePlugin
        src_path = self.sources[0].path
        with Image.open(src_path) as src:
            fmt, info = src.format, dict(src.info)
            quality = jpeg_quality(src) if fmt == "JPEG" else 0
            sampling = JpegImagePlugin.get_sampling(src) if fmt == "JPEG" else -1
            im = ImageOps.exif_transpose(src)
            exif = im.getexif()
        if q.get("crop"):
            c = q["crop"]
            im = im.crop((int(c["x"]), int(c["y"]), int(c["x"]) + int(c["w"]), int(c["y"]) + int(c["h"])))
        adj = adj_full(q.get("adj"))
        if color_on(adj) or any(adj[k] for k in ADJ_KEYS[10:]):
            alpha = im.getchannel("A") if im.mode in ("RGBA", "LA") else None
            a = np.asarray(im.convert("RGB"), dtype=np.float32) / 255
            im = Image.fromarray((adjust_array(a, adj) * 255 + .5).astype(np.uint8), "RGB")
            if alpha is not None:
                im.putalpha(alpha)
        if fmt == "JPEG" and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        kw = {}
        if keep:
            if 0x0112 in exif:
                exif[0x0112] = 1                         # already turned upright
            if len(exif):
                kw["exif"] = exif.tobytes()
            if info.get("icc_profile"):
                kw["icc_profile"] = info["icc_profile"]
            if info.get("xmp") and fmt in ("JPEG", "PNG", "WEBP", "TIFF"):
                kw["xmp"] = info["xmp"]
            if info.get("dpi"):
                kw["dpi"] = info["dpi"]
        forced = int(OPTIONS.get("photoQuality", 0))
        if fmt == "JPEG":                                # same quality and chroma layout as the original
            kw.update(quality=forced or quality, subsampling=sampling if sampling >= 0 else 0)
        elif fmt == "WEBP":
            if src_path.read_bytes()[12:16] == b"VP8L":   # lossless WebP stays lossless
                kw.update(lossless=True)
            else:
                kw.update(quality=forced or 90)
        elif fmt == "TIFF" and info.get("compression"):
            kw.update(compression=info["compression"])
        im.save(tmp, format=fmt, **kw)                  # PNG / BMP: lossless, nothing to choose
        return None

    def save_media(self, q: dict, used: list, props: Source, tmp: Path, tmpdir: Path, keep: bool):
        """The picture is copied when it doesn't change (only the sound is rendered), else all is rendered."""
        self.note = ""
        v1 = (q.get("vlanes") or [{"clips": []}])[0]["clips"]
        tail = float(q.get("T") or 0) - max((c["start"] + c["out"] - c["in"] for c in v1), default=0)
        if q.get("canvas") and tail < .05 and not any(s.info.get("still") for s in used):    # empty time or a picture: rendered
            plan = json.loads(json.dumps(q))
            pieces, added = copy_plan(plan, used)
            if pieces:
                if not self.render(plan, used, props, tmp, tmpdir, keep, pieces):
                    self.note = "video copied" + (f", cuts moved to keyframes (+{added:.2f} s)" if added > .001 else "")
                    return None
                tmp.unlink(missing_ok=True)            # couldn't be copied after all: the full way
            self.note = "video rendered"
        return self.render(q, used, props, tmp, tmpdir, keep, None)

    def render(self, q: dict, used: list, props: Source, tmp: Path, tmpdir: Path, keep: bool, vcopy):
        """The plan comes from the page, already on the output's own time line:
        vlanes (V1 first) and alanes of pieces {src, start, in, out[, stream, env, fx]}, the whole
        file's volume (genv) and picture fade (pfade), the master sound effects (aud).
        vcopy: pieces to copy as they are instead of rendering the picture."""
        T = float(q["T"])
        if T <= 0.0005:
            return {"ok": False, "msg": "Nothing left to save"}
        parts, maps, codec, extra_in = [], [], [], []
        canvas = q.get("canvas")
        out_ext = used[0].path.suffix.lower()

        # --- picture copied: the pieces joined without touching them
        if canvas and vcopy:
            one = vcopy[0]
            if len(vcopy) == 1 and one["in"] <= 0 and one["end"]:
                maps += ["-map", f"{one['src']}:v:0"]
            else:
                rows = []
                for c in vcopy:
                    path = str(used[c["src"]].path).replace("\\", "/").replace("'", "'\\''")
                    rows += [f"file '{path}'", f"inpoint {c['in']:.6f}"] + ([] if c["end"] else [f"outpoint {c['out']:.6f}"])
                (tmpdir / "cut.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
                extra_in = ["-f", "concat", "-safe", "0", "-i", "cut.txt"]
                maps += ["-map", f"{len(used)}:v:0"]
            codec += ["-c:v", "copy"]
            if out_ext in (".mp4", ".mov", ".m4v"):
                codec += ["-movflags", "+faststart"]

        # --- picture: every video track as one strip (gaps: black on V1, see-through above), stacked
        elif canvas:
            W, H = int(canvas["w"]) // 2 * 2, int(canvas["h"]) // 2 * 2
            FPS = float((q.get("out") or {}).get("fps") or canvas["fps"] or 30)
            strips = []
            for li, lane in enumerate(q.get("vlanes") or [{"clips": []}]):
                top = li > 0
                pix = "yuva420p" if top else "yuv420p"
                gap = (lambda d: f"color=c=black@0:s={W}x{H}:r={FPS}:d={d:.6f},format=yuva420p,setsar=1") if top \
                    else (lambda d: f"color=c=black:s={W}x{H}:r={FPS}:d={d:.6f},format=yuv420p,setsar=1")
                segs, cur = [], 0.0
                for c in sorted(lane["clips"], key=lambda c: c["start"]):
                    a, b = float(c["in"]), float(c["out"])
                    if b - a < 0.0005:
                        continue
                    if c["start"] - cur > 0.0005:
                        segs.append(gap(c["start"] - cur))
                    segs.append(f"[{c['src']}:v:0]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS,fps={FPS},"
                                f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:-1:-1:color=black,"
                                f"setsar=1,format={pix}")
                    cur = c["start"] + b - a
                if T - cur > 0.0005:
                    segs.append(gap(T - cur))
                if top and len(segs) == 1 and "black@0" in segs[0]:
                    continue                                # an empty upper track adds nothing
                for k, s in enumerate(segs):
                    parts.append(f"{s}[v{li}s{k}]")
                parts.append("".join(f"[v{li}s{k}]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[vl{li}]")
                strips.append(f"vl{li}")
            last = strips[0]
            for j, s in enumerate(strips[1:]):              # the upper track covers the lower one
                parts.append(f"[{last}][{s}]overlay=format=auto:shortest=1[vo{j}]")
                last = f"vo{j}"
            parts.append(f"[{last}]format=yuv420p[vc]")
            chain, w, h, last = [], W, H, "vc"
            if q.get("crop"):
                c = q["crop"]
                w, h = int(c["w"]) // 2 * 2, int(c["h"]) // 2 * 2
                chain.append(f"crop={w}:{h}:{int(c['x']) // 2 * 2}:{int(c['y']) // 2 * 2}")
            a = adj_full(q.get("adj"))
            pf = q.get("pfade") or []
            fade = len(pf) > 1 and any(g < 0.9999 for _, g in pf)
            if a["disp"]:                               # red drawn smaller, blue bigger, from the middle
                k = a["disp"] / 100 * .01
                w1, h1 = round(w / (1 + k)), round(h / (1 + k))
                w2, h2 = round(w / (1 - k)), round(h / (1 - k))
                px, py = (w - w1) // 2, (h - h1) // 2
                parts.append(f"[{last}]{','.join(chain + ['format=gbrp'])},extractplanes=g+b+r[dg][db][dr]")
                parts.append(f"[dr]scale={w1}:{h1},setsar=1,pad={w}:{h}:{px}:{py},"
                             f"fillborders=left={px}:right={w - w1 - px}:top={py}:bottom={h - h1 - py}:mode=smear[dr2]")
                parts.append(f"[db]scale={w2}:{h2},setsar=1,crop={w}:{h}[db2]")
                parts.append("[dg][db2][dr2]mergeplanes=0x001020:gbrp[vd]")
                chain, last = [], "vd"
            if a["nr"]:
                n = a["nr"] / 100
                chain.append(f"hqdn3d={4 * n:.2f}:{3 * n:.2f}:{6 * n:.2f}:{4.5 * n:.2f}")
            if a["clar"]:
                size = max(3, min(13, 2 * round(.006 * w) + 1))      # ffmpeg's unsharp allows 13 x 13 at most
                chain.append(f"unsharp=lx={size}:ly={size}:la={a['clar'] / 100:.3f}:cx=3:cy=3:ca=0")
            if a["sharp"] or color_on(a) or fade or a["vig"]:
                chain.append("format=gbrp")
                if a["sharp"]:
                    s = round(a["sharp"] / 100 * .5 * 100)
                    mtx = f"0 -{s} 0 -{s} {100 + 4 * s} -{s} 0 -{s} 0"
                    chain.append(":".join([f"convolution=0m='{mtx}'", f"1m='{mtx}'", f"2m='{mtx}'",
                                           "0rdiv=0.01", "1rdiv=0.01", "2rdiv=0.01"]))
                if color_on(a):
                    (tmpdir / "look.cube").write_text(lut_cube(a), encoding="utf-8")
                    chain.append("lut3d=file=look.cube:interp=tetrahedral")
                if fade:                                  # the fades' own curves, frame by frame
                    lines, prev = [], None
                    for f in range(int(T * FPS) + 2):
                        t = f / FPS
                        g = interp(pf, t)
                        if prev is None or abs(g - prev) > 1e-4:
                            lines.append(f"{t:.6f} colorchannelmixer@pf rr {g:.5f}, colorchannelmixer@pf gg {g:.5f}, "
                                         f"colorchannelmixer@pf bb {g:.5f};")
                            prev = g
                    (tmpdir / "pf.txt").write_text("\n".join(lines), encoding="utf-8")
                    chain.append("sendcmd=f=pf.txt,colorchannelmixer@pf=rr=1:gg=1:bb=1")
            if chain:
                parts.append(f"[{last}]{','.join(chain)}[vx]")
                last = "vx"
            if a["vig"]:
                import numpy as np
                from PIL import Image
                Image.fromarray((vignette_mask(w, h, a["vig"] / 100 * .9) * 255 + .5).astype(np.uint8), "L").save(tmpdir / "vig.png")
                extra_in = ["-loop", "1", "-i", "vig.png"]
                parts.append(f"[{len(used)}:v]format=gbrp[mk];[{last}]format=gbrp[vg];[vg][mk]blend=all_mode=multiply:shortest=1[vm]")
                last = "vm"
            grain = f",noise=alls={round(a['grain'] / 100 * 25)}:allf=t" if a["grain"] else ""
            parts.append(f"[{last}]format=yuv420p{grain}[vo]")
            maps += ["-map", "[vo]"]
            first_v = next(s for s in used if s.info["video"])
            br = int(float((q.get("out") or {}).get("mbps") or 0) * 1e6) or first_v.info["vbr"]
            codec += video_args(first_v.info, out_ext, br)
            if out_ext in (".mp4", ".mov", ".m4v"):
                codec += ["-movflags", "+faststart"]

        # --- sound: each track = its pieces (own volume, fades, effects) one after another, then the
        # track's effects, the whole file's volume line + fades, the master effects
        master = fx_chain(q.get("aud"))
        genv = vol_filters(q.get("genv"))
        n_out = int(q.get("nOut") or 99)
        outs = []
        mixing = any(l["clips"] for l in (q.get("alanes") or [])[n_out:])
        for k, lane in enumerate(q.get("alanes") or []):
            clips = [c for c in sorted(lane["clips"], key=lambda c: c["start"]) if c["out"] - c["in"] >= 0.0005]
            if not clips:
                continue
            a0 = used[clips[0]["src"]].info["audios"][clips[0]["stream"]]
            c = clips[0]                               # an untouched sound stream isn't re-encoded
            if len(clips) == 1 and not (mixing or master or genv or lane.get("fx") or c.get("env") or c.get("fx")) \
                    and c["in"] < .001 and c["start"] < .001 and abs(T - c["out"]) < .02 \
                    and abs(c["out"] - used[c["src"]].info["duration"]) < .02 and used[c["src"]].path.suffix.lower() == out_ext:
                outs.append((k, None, a0, c))
                continue
            R, L = a0["rate"], layout_name(a0["ch"])
            fmt = f"aformat=sample_fmts=fltp:sample_rates={R}:channel_layouts={L}"
            segs, cur = [], 0.0
            for c in clips:
                a, b = float(c["in"]), float(c["out"])
                if c["start"] - cur > 0.0005:
                    segs.append(f"anullsrc=r={R}:cl={L},atrim=duration={c['start'] - cur:.6f},{fmt}")
                f = [f"[{c['src']}:a:{c['stream']}]atrim=start={a:.6f}:end={b:.6f}", "asetpts=PTS-STARTPTS", fmt]
                segs.append(",".join(f + vol_filters(c.get("env")) + fx_chain(c.get("fx"))))
                cur = c["start"] + b - a
            if T - cur > 0.0005:
                segs.append(f"anullsrc=r={R}:cl={L},atrim=duration={T - cur:.6f},{fmt}")
            for j, s in enumerate(segs):
                parts.append(f"{s}[a{k}s{j}]")
            parts.append("".join(f"[a{k}s{j}]" for j in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[a{k}c]")
            post = fx_chain(lane.get("fx")) + genv + master
            parts.append(f"[a{k}c]{','.join(post) or 'anull'}[ao{k}]")
            outs.append((k, f"ao{k}", a0, None))
        real = [o for o in outs if o[0] < n_out] or outs[:1]
        extra = [o for o in outs if o not in real]
        if extra:                                      # tracks added in Pro go into the first output track
            parts.append(f"[{real[0][1]}]" + "".join(f"[{o[1]}]" for o in extra)
                         + f"amix=inputs={len(extra) + 1}:normalize=0:duration=longest[amx]")
            real[0] = (real[0][0], "amx", real[0][2], None)
        for k_out, (k, label, a0, same) in enumerate(real):
            if same:
                maps += ["-map", f"{same['src']}:a:{same['stream']}"]
                codec += [f"-c:a:{k_out}", "copy"]
            else:
                maps += ["-map", f"[{label}]"]
                codec += audio_args(a0, k_out, bool(canvas))
            if keep and k < len(props.info["audios"]):
                codec += [f"-map_metadata:s:a:{k_out}", f"{props.idx}:s:a:{k}"]
        if not canvas and keep and props.info["cover"]:
            maps += ["-map", f"{props.idx}:v?"]
            codec += ["-c:v", "copy"]
            if out_ext in (".m4a", ".mp4"):
                codec += ["-disposition:v", "attached_pic"]   # the cover stays a cover, not a video
        if not canvas and out_ext == ".mp3":
            codec += ["-id3v2_version", "3"]
        cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
        for s in used:
            cmd += [*(["-loop", "1"] if s.info.get("still") else []), "-i", str(s.path)]
        script = tmpdir / "graph.txt"                  # long graphs: from a file, not the command line
        script.write_text(";\n".join(parts), encoding="utf-8")
        cmd += [*extra_in, *(["-/filter_complex", "graph.txt"] if parts else []), *maps, *codec,
                *(["-t", f"{T:.6f}"] if vcopy else []),
                "-map_metadata", str(props.idx) if keep else "-1", str(tmp)]
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(tmpdir),
                              creationflags=NO_WINDOW)
        err = []
        threading.Thread(target=lambda: err.extend(pr.stderr), daemon=True).start()
        for line in pr.stdout:
            m = re.match(r"out_time_us=(\d+)", line)
            if m:
                self.prog = {"pct": min(99, int(m.group(1)) / 1e6 / T * 100)}
        pr.wait()
        if pr.returncode != 0 or not tmp.exists():
            return {"ok": False, "msg": (err[-1].strip() if err else "ffmpeg failed")}
        return None

    def close(self):
        self._dirty = False                       # закрытие из самой страницы (после сохранения) — без вопросов
        webview.windows[0].destroy()

    # ---- закрытие с несохранённым: страница сообщает, есть ли правки или идёт сохранение
    def set_dirty(self, d):
        self._dirty = bool(d)
        return True

    def _on_closing(self):
        if not getattr(self, "_dirty", False):
            return True
        import ctypes
        r = ctypes.windll.user32.MessageBoxW(None, "There are unsaved edits in this file.\n\nClose without saving?",
                                             "Saturni · Editor", 0x04 | 0x30 | 0x100 | 0x40000)   # YESNO, WARNING, DEFBUTTON2, TOPMOST
        return r == 6                             # IDYES
