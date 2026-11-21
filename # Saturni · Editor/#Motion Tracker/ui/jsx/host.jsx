// ExtendScript side of Point Tracker (ES3: no JSON, no Array helpers).

function pt_json(v) {
    if (v === null || v === undefined) return "null";
    var t = typeof v;
    if (t === "number") return isFinite(v) ? String(v) : "null";
    if (t === "boolean") return v ? "true" : "false";
    if (t === "string") {
        return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\r/g, "\\r").replace(/\n/g, "\\n") + '"';
    }
    if (v instanceof Array) {
        var a = [];
        for (var i = 0; i < v.length; i++) a.push(pt_json(v[i]));
        return "[" + a.join(",") + "]";
    }
    var o = [];
    for (var k in v) if (v.hasOwnProperty(k)) o.push(pt_json(k) + ":" + pt_json(v[k]));
    return "{" + o.join(",") + "}";
}

function pt_wrap(fn) {
    try { return pt_json({ ok: true, result: fn() }); }
    catch (e) { return pt_json({ ok: false, error: String(e) + (e.line ? " (line " + e.line + ")" : "") }); }
}

function pt_seq() {
    var s = app.project.activeSequence;
    if (!s) throw "No active sequence";
    return s;
}

function pt_fps(seq) { return 254016000000 / parseFloat(seq.timebase); }

function pt_selectedVideo(seq) {
    var sel = seq.getSelection(), out = [];
    for (var i = 0; i < sel.length; i++) if (sel[i].mediaType === "Video") out.push(sel[i]);
    return out;
}

function pt_trackIndexOf(seq, item) {
    for (var i = 0; i < seq.videoTracks.numTracks; i++) {
        var clips = seq.videoTracks[i].clips;
        for (var j = 0; j < clips.numItems; j++) if (clips[j].nodeId === item.nodeId) return i;
    }
    return -1;
}

function pt_findItemByNode(seq, nodeId) {
    for (var i = 0; i < seq.videoTracks.numTracks; i++) {
        var clips = seq.videoTracks[i].clips;
        for (var j = 0; j < clips.numItems; j++) if (clips[j].nodeId === nodeId) return clips[j];
    }
    return null;
}

function pt_clipInfo(seq, clip) {
    return {
        name: clip.name, nodeId: clip.nodeId,
        start: clip.start.seconds, end: clip.end.seconds, inPoint: clip.inPoint.seconds,
        track: pt_trackIndexOf(seq, clip),
        seqW: seq.frameSizeHorizontal, seqH: seq.frameSizeVertical,
        fps: pt_fps(seq), playhead: seq.getPlayerPosition().seconds
    };
}

function pt_getClipInfo() {
    return pt_wrap(function () {
        var seq = pt_seq(), items = pt_selectedVideo(seq);
        if (!items.length) throw "Select a video clip in the timeline";
        return pt_clipInfo(seq, items[0]);
    });
}

// Set sequence in/out by seconds, verifying which argument form this build accepts.
function pt_setInOut(seq, inT, outT) {
    seq.setInPoint(inT.seconds);
    if (Math.abs(seq.getInPointAsTime().seconds - inT.seconds) > 0.001) seq.setInPoint(inT.ticks);
    seq.setOutPoint(outT.seconds);
    if (Math.abs(seq.getOutPointAsTime().seconds - outT.seconds) > 0.001) seq.setOutPoint(outT.ticks);
}

// Temporarily freeze every animated Motion / Transform property of a clip, so a previous
// track applied to it does not end up in the render. Returns state for pt_restorePositions.
function pt_freezePositions(clip) {
    var saved = [];
    for (var i = 0; i < clip.components.numItems; i++) {
        var c = clip.components[i];
        if (!pt_isMotion(c) && !pt_isTransform(c)) continue;
        for (var j = 0; j < c.properties.numItems; j++) {
            var param = c.properties[j];
            try { if (!param.isTimeVarying()) continue; } catch (e) { continue; }
            var ks = param.getKeys(), keys = [];
            for (var k = 0; k < ks.length; k++) keys.push([ks[k], param.getValueAtKey(ks[k])]);
            param.setTimeVarying(false);
            if (keys.length) param.setValue(keys[0][1], 1);
            saved.push([param, keys]);
        }
    }
    return saved;
}

function pt_restorePositions(saved) {
    for (var i = 0; i < saved.length; i++) {
        var param = saved[i][0], keys = saved[i][1];
        param.setTimeVarying(true);
        for (var k = 0; k < keys.length; k++) {
            param.addKey(keys[k][0]);
            param.setValueAtKey(keys[k][0], keys[k][1], k === keys.length - 1);
        }
    }
}

function pt_exportClip(outPath, presetPath, hideOthers, ignoreKeys) {
    return pt_wrap(function () {
        var seq = pt_seq(), items = pt_selectedVideo(seq);
        if (!items.length) throw "Select a video clip in the timeline";
        var clip = items[0], info = pt_clipInfo(seq, clip);
        if (!new File(presetPath).exists) throw "Export preset not found: " + presetPath;
        var oldIn = seq.getInPointAsTime(), oldOut = seq.getOutPointAsTime();
        var muted = [], frozen = [], res;
        try {
            if (ignoreKeys) frozen = pt_freezePositions(clip);
            if (hideOthers) {
                for (var i = 0; i < seq.videoTracks.numTracks; i++) {
                    if (i === info.track) continue;
                    var tr = seq.videoTracks[i];
                    muted.push([i, tr.isMuted()]);
                    tr.setMute(1);
                }
            }
            pt_setInOut(seq, clip.start, clip.end);
            var f = new File(outPath);
            if (f.exists) f.remove();
            res = seq.exportAsMediaDirect(outPath, presetPath, app.encoder.ENCODE_IN_TO_OUT);
        } finally {
            for (var m = 0; m < muted.length; m++) seq.videoTracks[muted[m][0]].setMute(muted[m][1] ? 1 : 0);
            pt_setInOut(seq, oldIn, oldOut);
            pt_restorePositions(frozen);
        }
        if (!new File(outPath).exists) throw "Export produced no file (" + res + ")";
        info.exportResult = String(res);
        return info;
    });
}

function pt_findComp(item, test) {
    for (var i = 0; i < item.components.numItems; i++) {
        var c = item.components[i];
        if (test(c)) return c;
    }
    return null;
}

function pt_isMotion(c) { return c.matchName === "AE.ADBE Motion"; }

function pt_isTransform(c) {
    return /Geometry/i.test(c.matchName) ||
        /^(Transform|Преобразовать|Преобразование|Трансформирование)$/i.test(c.displayName);
}

function pt_findParam(comp, names, fallbackIndex) {
    for (var i = 0; i < comp.properties.numItems; i++) {
        var p = comp.properties[i];
        for (var n = 0; n < names.length; n++) if (p.displayName === names[n]) return p;
    }
    return comp.properties[fallbackIndex];
}

// On speed-changed clips Premiere evaluates effect keyframes one sequence frame late, so keys
// are placed one frame earlier (measured on a 50% clip: residual jitter dropped from ~12 px to ~1 px).
var PT_SPEED_SHIFT = -1;
var PT_POS_NAMES =["Position", "Положение", "Позиция"];

function pt_addTransform(seq, item) {
    app.enableQE();
    var ti = pt_trackIndexOf(seq, item);
    var qt = qe.project.getActiveSequence().getVideoTrackAt(ti), qitem = null;
    for (var k = 0; k < qt.numItems; k++) {
        var q = qt.getItemAt(k);
        if (q.type !== "Empty" && Math.abs(q.start.secs - item.start.seconds) < 0.002) { qitem = q; break; }
    }
    if (!qitem) throw "Could not locate the clip to add Transform; add the Transform effect manually";
    var names = ["Transform", "Преобразовать", "Преобразование", "Трансформирование"], eff = null;
    for (var n = 0; n < names.length && !eff; n++) eff = qe.project.getVideoEffectByName(names[n]);
    if (!eff) throw "Transform effect not found; add it to the clip manually";
    qitem.addVideoEffect(eff);
    var fresh = pt_findItemByNode(seq, item.nodeId) || item;
    var comp = pt_findComp(fresh, pt_isTransform);
    if (!comp) throw "Transform was not added; add it to the clip manually";
    return comp;
}

function pt_clipFrameSize(seq, item) {
    try {
        var md = item.projectItem.getProjectMetadata();
        var m = /VideoInfo>\s*(\d+)\s*x\s*(\d+)/.exec(md);
        if (m) return [parseInt(m[1], 10), parseInt(m[2], 10)];
    } catch (e) {}
    return [seq.frameSizeHorizontal, seq.frameSizeVertical];
}

function pt_timeAt(sec) { var t = new Time(); t.seconds = sec; return t; }

function pt_currentValue(param, clipTime) {
    return param.isTimeVarying() ? param.getValueAtTime(pt_timeAt(clipTime)) : param.getValue();
}

// Transform effect parameter order (stable across UI languages).
var PT_T_ANCHOR = 0, PT_T_POS = 1, PT_T_UNIFORM = 2, PT_T_SCALE = 3, PT_T_ROT = 7;

function pt_setStatic(param, v) {
    if (param.isTimeVarying()) param.setTimeVarying(false);
    param.setValue(v, 1);
}

// Replace all keys of `param` with one key per index in `idxs`.
function pt_writeKeys(param, idxs, timeOf, valueOf) {
    param.setTimeVarying(false);
    param.setTimeVarying(true);
    for (var j = 0; j < idxs.length; j++) {
        var tm = pt_timeAt(timeOf(idxs[j]));
        param.addKey(tm);
        param.setValueAtKey(tm, valueOf(idxs[j]), j === idxs.length - 1);
    }
}

function pt_isPixels(v) { return Math.abs(v[0]) > 2 || Math.abs(v[1]) > 2; }

// Ramer–Douglas–Peucker over frames: linear interpolation between kept keys stays within
// tolerance on every frame (position px, scale ratio, degrees), for the properties being written.
var PT_REDUCE_TOL = { pos: 0.35, scale: 0.001, rot: 0.05 }; // pos per axis: <= 0.5 px overall
function pt_reduceKeys(pts, i0, i1, doPos, doScale, doRot) {
    var keep = {}, stack = [[i0, i1]];
    keep[i0] = keep[i1] = true;
    while (stack.length) {
        var seg = stack.pop(), a = seg[0], b = seg[1], worst = 0, at = -1;
        for (var k = a + 1; k < b; k++) {
            var u = (k - a) / (b - a), e = 0;
            for (var d = 0; d < 4; d++) {
                var use = d < 2 ? doPos : d === 2 ? doScale : doRot;
                if (!use) continue;
                var tol = d < 2 ? PT_REDUCE_TOL.pos : d === 2 ? PT_REDUCE_TOL.scale : PT_REDUCE_TOL.rot;
                e = Math.max(e, Math.abs(pts[a][d] + (pts[b][d] - pts[a][d]) * u - pts[k][d]) / tol);
            }
            if (e > worst) { worst = e; at = k; }
        }
        if (worst > 1) { keep[at] = true; stack.push([a, at]); stack.push([at, b]); }
    }
    var out = [];
    for (var j = i0; j <= i1; j++) if (keep[j]) out.push(j);
    return out;
}
// data:  "t0|fps|x,y,s,a;..." — per sequence frame i (time t0 + i/fps): position in sequence
//        pixels, scale and angle (degrees, clockwise) relative to the reference frame.
// mode:  "attach" (target follows the point) | "stabilize" (target cancels the motion)
// props: string with any of "p", "s", "r" — Position, Scale, Rotation
// reduce: keep only the keys needed to stay within PT_REDUCE_TOL of every tracked frame
function pt_apply(data, mode, props, refIndex, reduce) {
    return pt_wrap(function () {
        var parts = data.split("|"), t0 = parseFloat(parts[0]), fps = parseFloat(parts[1]);
        var raw = parts[2].split(";"), pts = [];
        for (var i = 0; i < raw.length; i++) {
            var v = raw[i].split(",");
            pts.push([parseFloat(v[0]), parseFloat(v[1]), parseFloat(v[2]), parseFloat(v[3])]);
        }
        var doPos = props.indexOf("p") >= 0, doScale = props.indexOf("s") >= 0, doRot = props.indexOf("r") >= 0;
        if (!doPos && !doScale && !doRot) throw "Choose at least one of Position, Scale, Rotation";
        var seq = pt_seq(), W = seq.frameSizeHorizontal, H = seq.frameSizeVertical;
        var targets = pt_selectedVideo(seq), report = [];
        if (!targets.length) throw "Select the clip(s) to apply the track to";

        for (var ti = 0; ti < targets.length; ti++) {
            var tg = targets[ti], tStart = tg.start.seconds, tEnd = tg.end.seconds, tIn = tg.inPoint.seconds;
            var i0 = Math.max(0, Math.ceil((tStart - t0) * fps - 1e-4));
            var i1 = Math.min(pts.length - 1, Math.floor((tEnd - t0) * fps - 1e-4));
            if (i1 < i0) { report.push(tg.name + ": does not overlap the tracked range"); continue; }
            var r = (refIndex >= i0 && refIndex <= i1) ? refIndex : i0;
            // Keyframe times are source-media seconds. With a speed change, scripting reports
            // inPoint already divided by speed, so: media = speed * (inPoint + offset in sequence).
            var speed = 1;
            try { speed = tg.getSpeed(); } catch (e) {}
            if (!(speed > 0)) speed = 1;
            try { if (tg.isSpeedReversed()) { report.push(tg.name + ": reversed speed is not supported"); continue; } } catch (e) {}
            var shift = (Math.abs(speed - 1) > 1e-6 ? PT_SPEED_SHIFT : 0) / fps;
            var timeOf = function (idx) { return speed * (tIn + (t0 + idx / fps - tStart) + shift); };

            var idxs = [];
            if (reduce) idxs = pt_reduceKeys(pts, i0, i1, doPos || mode === "stabilize", doScale, doRot); // stabilize always keys the anchor
            else for (var k = i0; k <= i1; k++) idxs.push(k);

            var motion = pt_findComp(tg, pt_isMotion);
            var comp = pt_findComp(tg, pt_isTransform) || pt_addTransform(seq, tg);
            var P = comp.properties, tr = timeOf(r);

            // Transform works in the clip's own pixel frame, before Motion places it in the sequence.
            var size = pt_clipFrameSize(seq, tg), cw = size[0], ch = size[1];
            var ms = motion ? pt_currentValue(motion.properties[1], tr) : 100;
            ms = (typeof ms === "number" && ms > 0) ? ms / 100 : 1;
            var mpos = motion ? pt_currentValue(motion.properties[0], tr) : [0.5, 0.5];
            var manc = motion ? pt_currentValue(motion.properties[5], tr) : [0.5, 0.5];
            var mposPx = pt_isPixels(mpos) ? mpos : [mpos[0] * W, mpos[1] * H];
            var mancPx = pt_isPixels(manc) ? manc : [manc[0] * cw, manc[1] * ch];
            // Tracked point of frame k in the clip's pixel frame.
            var q = function (k) {
                return [(pts[k][0] - mposPx[0]) / ms + mancPx[0], (pts[k][1] - mposPx[1]) / ms + mancPx[1]];
            };

            // Current Transform: out = P0 + M0 (in - A0), M0 = rotation r0 * scale s0.
            var P0n = pt_currentValue(P[PT_T_POS], tr), A0n = pt_currentValue(P[PT_T_ANCHOR], tr);
            var posPx = pt_isPixels(P0n), ancPx = pt_isPixels(A0n);
            var P0 = posPx ? P0n : [P0n[0] * cw, P0n[1] * ch], A0 = ancPx ? A0n : [A0n[0] * cw, A0n[1] * ch];
            var baseScale = pt_currentValue(P[PT_T_SCALE], tr), baseRot = pt_currentValue(P[PT_T_ROT], tr);
            if (!(typeof baseScale === "number" && baseScale > 0)) baseScale = 100;
            if (typeof baseRot !== "number") baseRot = 0;
            var s0 = baseScale / 100, r0 = baseRot * Math.PI / 180;
            // Anchor that puts the pivot on clip point v without changing the current result.
            var anchorFor = function (v) {
                var dx = v[0] - P0[0], dy = v[1] - P0[1], c = Math.cos(-r0), s = Math.sin(-r0);
                return [A0[0] + (c * dx - s * dy) / s0, A0[1] + (s * dx + c * dy) / s0];
            };
            var normP = function (v) { return posPx ? v : [v[0] / cw, v[1] / ch]; };
            var normA = function (v) { return ancPx ? v : [v[0] / cw, v[1] / ch]; };
            if (doScale) pt_setStatic(P[PT_T_UNIFORM], true);
            var written = [];

            if (mode === "attach") {
                // Pivot on the tracked point: the target follows it and scales/rotates around it.
                pt_setStatic(P[PT_T_ANCHOR], normA(anchorFor(q(r))));
                if (doPos) {
                    pt_writeKeys(P[PT_T_POS], idxs, timeOf, function (k) { return normP(q(k)); });
                    written.push("Position");
                } else {
                    pt_setStatic(P[PT_T_POS], normP(q(r)));
                }
                if (doScale) {
                    pt_writeKeys(P[PT_T_SCALE], idxs, timeOf, function (k) { return baseScale * pts[k][2] / pts[r][2]; });
                    written.push("Scale");
                }
                if (doRot) {
                    pt_writeKeys(P[PT_T_ROT], idxs, timeOf, function (k) { return baseRot + pts[k][3] - pts[r][3]; });
                    written.push("Rotation");
                }
            } else {
                // Stabilize: the pivot follows the tracked point; it is pinned where it was on the box frame.
                pt_writeKeys(P[PT_T_ANCHOR], idxs, timeOf, function (k) { return normA(anchorFor(q(k))); });
                if (doPos) {
                    pt_setStatic(P[PT_T_POS], normP(q(r)));
                    written.push("Position");
                } else {
                    pt_writeKeys(P[PT_T_POS], idxs, timeOf, function (k) { return normP(q(k)); });
                }
                if (doScale) {
                    pt_writeKeys(P[PT_T_SCALE], idxs, timeOf, function (k) { return baseScale * pts[r][2] / pts[k][2]; });
                    written.push("Scale");
                }
                if (doRot) {
                    pt_writeKeys(P[PT_T_ROT], idxs, timeOf, function (k) { return baseRot - (pts[k][3] - pts[r][3]); });
                    written.push("Rotation");
                }
            }
            // Effect Controls does not redraw keyframes added by script until the selection changes.
            try { tg.setSelected(0, 1); tg.setSelected(1, 1); } catch (e) {}
            report.push(tg.name + ": " + idxs.length + " keyframes (" + written.join(", ") + ")");
        }
        return report;
    });
}
