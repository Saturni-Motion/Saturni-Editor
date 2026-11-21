// Drawing the timeline: waves, pieces, volume lines, fades, ruler, playhead, overview strip.

// ---------- waves
function minmax(i, n, a, b) {                     // min/max of source i, stream n between a..b s
  const w = WV[i]; if (!w) return null;
  const arr = w.per[n], sr = w.sr[n]; if (!arr) return null;
  const i0 = Math.max(0, Math.floor(a * sr)), i1 = Math.min(arr.length, Math.floor(b * sr) + 1), stp = Math.max(1, Math.floor((i1 - i0) / 400));
  let mn = 1, mxv = -1;
  for (let j = i0; j < i1; j += stp) { const v = arr[j]; if (v < mn) mn = v; if (v > mxv) mxv = v; }
  return mxv < mn ? null : [mn, mxv];
}
function compMM(ta, tb) {                        // all sound pieces under a..b together (Simple's wave)
  let mn = 1, mxv = -1, any = false;
  for (const c of st.R.clips) {
    if (c.lane < 0 || tb <= c.start || ta >= clipEnd(c)) continue;
    const a = Math.max(ta, c.start), b = Math.min(tb, clipEnd(c)), mm = minmax(c.src, c.stream, c.in + a - c.start, c.in + b - c.start); if (!mm) continue;
    const g = clipG(c, (a + b) / 2); mn = Math.min(mn, mm[0] * g); mxv = Math.max(mxv, mm[1] * g); any = true;
  }
  return any ? [mn, mxv] : null;
}
function drawWaveCol(x, y, h, mm, g, col) {
  const mid = y + h / 2, amp = (h / 2 - 3) * waveZoom;
  const tp = Math.min(h / 2, Math.max(mm[1], 0) * g * amp), bt = Math.min(h / 2, -Math.min(mm[0], 0) * g * amp);
  cx.fillStyle = col; cx.fillRect(x, mid - tp, 1, Math.max(1, tp + bt));
}
function dbGrid(l) {                              // only the numbers: small and frequent, on both halves, inside the row
  const mid = l.y + l.h / 2, amp = (l.h / 2 - 3) * waveZoom, xr = X0() + W() - 3;
  cx.font = "5px Inter, Segoe UI"; cx.textAlign = "right"; cx.fillStyle = hexA(C.grid, .4);
  let lastA = 1e9;
  for (const db of [0, -3, -6, -9, -12, -15, -18, -21, -24, -30, -36, -42, -48, -60]) {
    const a = Math.pow(10, db / 20) * amp; if (a > l.h / 2 - 1 || a < 4 || lastA - a < 6) continue;
    cx.fillText(db, xr, mid - a + 5); cx.fillText(db, xr, mid + a - 1); lastA = a;
  }
  cx.textAlign = "left";
}
function rrect(x, y, w, h, r) { r = Math.min(r, w / 2, h / 2); cx.beginPath(); cx.moveTo(x + r, y); cx.arcTo(x + w, y, x + w, y + h, r); cx.arcTo(x + w, y + h, x, y + h, r); cx.arcTo(x, y + h, x, y, r); cx.arcTo(x, y, x + w, y, r); cx.closePath(); }

// ---------- drawing
function draw() {
  const dpr = devicePixelRatio || 1, cw = tl.clientWidth, h = tl.clientHeight;
  if (tl.width !== Math.round(cw * dpr) || tl.height !== Math.round(h * dpr)) { tl.width = Math.round(cw * dpr); tl.height = Math.round(h * dpr); }
  cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, cw, h);
  clampScroll();
  const L = lanes(), x0 = X0(), w = W();
  cx.save(); cx.beginPath(); cx.rect(0, RULER + 2, cw, h - RULER - 2); cx.clip();    // rows scroll under the ruler
  for (const l of L) { cx.fillStyle = C.timeline; cx.fillRect(x0, l.y, w, l.h); }
  if (pro()) drawPro(L); else drawSimple(L[0]);
  drawGlobal(L);
  if (sel) {
    const xa = t2x(Math.min(...sel)), xb = t2x(Math.max(...sel));
    for (const l of L) {
      if (selLanes && !selLanes.includes(l.k)) continue;
      cx.fillStyle = hexA(C.selection, .2); cx.fillRect(xa, l.y, xb - xa, l.h);
      cx.fillStyle = hexA(C.selection, .8); cx.fillRect(Math.round(xa), l.y, 1, l.h); cx.fillRect(Math.round(xb), l.y, 1, l.h);
    }
  }
  const S = st.S;
  if (!pro() && NA()) { drawEnv(S, 0, L[0], x0, x0 + w, "S"); }
  if (!pro()) {                                   // the top arcs = picture, the bottom arcs = sound
    if (hasV()) drawFades(S.V, S.inT, S.outT, L[0], x0, x0 + w, "gv", false);
    if (NA()) drawFades(S, S.inT, S.outT, L[0], x0, x0 + w, "g", true);
  } else if (L.length) {                          // the whole file's fades over all the tracks; their handles are in the ruler
    const a = L[0], z = L[L.length - 1], l = { y: a.y, h: z.y + z.h - a.y };
    if (hasV()) drawFades(S.V, S.inT, S.outT, l, x0, x0 + w, "gv", false, true);
    if (NA()) drawFades(S, S.inT, S.outT, l, x0, x0 + w, "g", true, true);
  }
  cx.restore();
  drawRuler(cw);
  drawTrim();
  if (baseC.width !== tl.width || baseC.height !== tl.height) { baseC.width = tl.width; baseC.height = tl.height; }
  bx.clearRect(0, 0, baseC.width, baseC.height); bx.drawImage(tl, 0, 0);       // all but the playhead: playback only redraws that
  drawPlayhead();
  placeDel(); drawOverview();
}
let phFrame = 0;
function drawHead() {                            // the playhead moved, nothing else did
  const dpr = devicePixelRatio || 1;
  cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, tl.width, tl.height); cx.drawImage(baseC, 0, 0);
  cx.setTransform(dpr, 0, 0, dpr, 0, 0); drawPlayhead();
  if (++phFrame % 6 === 0) drawOverview();
}
function drawSimple(l) {
  const S = st.S, x0 = X0(), w = W();
  if (NA()) {
    dbGrid(l); cx.font = "10px Inter, Segoe UI"; cx.textAlign = "left";
    cx.fillStyle = hexA(C.text, hover === "hdrS" ? .85 : .45); cx.fillText("A", PAD + 2, l.y + 14);
  }
  for (let x = 0; x < w; x++) {
    const ta = x2t(x0 + x), tb = x2t(x0 + x + 1); if (tb <= 0 || ta >= dur) continue;
    const mm = compMM(ta, tb); if (!mm) continue;
    const t = (ta + tb) / 2;
    drawWaveCol(x0 + x, l.y, l.h, mm, globalG(t), t >= S.inT && t <= S.outT && !inCut(t) ? C.keep : C.removed);
  }
  // where one piece (file) ends and the next begins
  cx.font = "10px Inter, Segoe UI"; cx.textAlign = "left";
  const marks = st.R.clips.filter(c => c.lane === (hasV() ? -1 : 0)).sort((a, b) => a.start - b.start);
  if (marks.length > 1 || project()) marks.forEach((c, i) => {
    const x = t2x(c.start); if (x < x0 - 1 || x > x0 + w) return;
    if (i) { cx.fillStyle = hexA(C.text, .3); cx.fillRect(Math.round(x), l.y, 1, l.h); }
    cx.fillStyle = hexA(C.text, .45); cx.fillText(SRC[c.src].stem, x + 4, l.y + 24);
  });
}
function drawGlobal(L) {                         // Start / End and the cuts over every row
  const S = st.S, x0 = X0(), w = W(), top = L.length ? Math.min(...L.map(l => l.y)) : RULER, bot = L.length ? Math.max(...L.map(l => l.y + l.h)) : tl.clientHeight;
  cx.fillStyle = "rgba(0,0,0,.42)";
  const xi = t2x(S.inT), xo = t2x(S.outT);
  if (xi > x0) cx.fillRect(x0, top, Math.min(xi, x0 + w) - x0, bot - top);
  if (xo < x0 + w) cx.fillRect(Math.max(xo, x0), top, x0 + w - Math.max(xo, x0), bot - top);
  if (!pro()) { cx.fillStyle = hexA(C.keep, .05); cx.fillRect(xi, top, xo - xi, bot - top); }
  for (const [a, b] of S.cuts) {
    const xa = t2x(a), xb = t2x(b); if (xb < 0 || xa > x0 + w) continue;
    cx.fillStyle = hexA(C.cut, .08); cx.fillRect(xa, top, xb - xa, bot - top);
    cx.save(); cx.beginPath(); cx.rect(xa, top, xb - xa, bot - top); cx.clip();
    cx.strokeStyle = hexA(C.cut, .2); cx.lineWidth = 1;
    for (let x = xa - (bot - top); x < xb; x += 8) { cx.beginPath(); cx.moveTo(x, bot); cx.lineTo(x + bot - top, top); cx.stroke(); }
    cx.restore();
  }
}
function drawPro(L) {
  const R = st.R, x0 = X0(), w = W();
  cx.font = "10px Inter, Segoe UI"; cx.textAlign = "left";
  for (const l of L) {
    cx.fillStyle = hexA(C.text, hover === "hdr" + l.k ? .85 : .45); cx.fillText(laneName(l.k), PAD + 2, l.y + Math.min(14, l.h - 6));
  }
  for (const c of R.clips) {
    const l = L.find(q => q.k === c.lane); if (!l) continue;
    const xa = t2x(c.start), xb = t2x(clipEnd(c)); if (xb < x0 || xa > x0 + w) continue;
    const on = csel.has(c.id), y = l.y + 1, hh = l.h - 2;
    cx.save(); rrect(xa + .5, y, xb - xa - 1, hh, 5); cx.clip();
    cx.fillStyle = hexA(on ? C.accent : C.clip, c.lane < 0 ? (on ? .42 : .3) : (on ? .26 : .12)); cx.fillRect(xa, y, xb - xa, hh);
    if (c.lane >= 0) for (let x = Math.floor(Math.max(xa, x0)); x < Math.min(xb, x0 + w); x++) {
      const t = x2t(x), s0 = c.in + t - c.start, mm = minmax(c.src, c.stream, s0, s0 + (v1 - v0) / w); if (!mm) continue;
      drawWaveCol(x, y, hh, mm, clipG(c, t) * globalG(t), C.keep);
    }
    if (clipSel && clipSel.id === c.id) {          // a part chosen inside the piece
      const a = t2x(Math.min(clipSel.a, clipSel.b)), b = t2x(Math.max(clipSel.a, clipSel.b));
      cx.fillStyle = hexA(C.selection, .3); cx.fillRect(a, y, b - a, hh);
      cx.fillStyle = hexA(C.selection, .9); cx.fillRect(Math.round(a), y, 1, hh); cx.fillRect(Math.round(b), y, 1, hh);
    }
    cx.font = "10px Inter, Segoe UI"; cx.fillStyle = hexA(C.text, on ? .95 : .7); cx.fillText(SRC[c.src].stem, xa + (c.lane < 0 ? 19 : 6), y + Math.min(13, hh - 4));
    if (c.lane >= 0 && hh > 26) drawEnv(c.vol, c.start, { k: c.id, y, h: hh }, Math.max(xa, x0), Math.min(xb, x0 + w), "c" + c.id);
    if (xb - xa >= 26 && hh >= 16) drawFades(c, c.start, clipEnd(c), { y, h: hh }, xa, xb, "c" + c.id, c.lane >= 0);
    cx.restore();
    if (on) { cx.save(); cx.shadowColor = hexA(C.accent, .8); cx.shadowBlur = 8; rrect(xa + 1, y + .5, xb - xa - 2, hh - 1, 5); cx.strokeStyle = C.accent; cx.lineWidth = 2; cx.stroke(); cx.restore(); }
    else { rrect(xa + .5, y + .5, xb - xa - 1, hh - 1, 5); cx.strokeStyle = hexA(C.clip, .5); cx.lineWidth = 1; cx.stroke(); }
  }
  for (const l of L) if (l.k >= 0 && l.h >= 40) dbGrid(l);
  for (const c of R.clips) {                     // joins between touching sound pieces: their transition
    if (c.lane < 0) continue;
    const n = nextAdj(c); if (!n) continue;
    const l = L.find(q => q.k === c.lane); if (!l) continue;
    const xj = t2x(clipEnd(c)), hw = Math.max(5, (t2x(clipEnd(c) + c.xo / 2) - xj)), on = hover === "j" + c.id || drag && drag.k === "trans" && drag.c === c;
    if (!c.xo && !on) continue;
    const ty = l.y + l.h / 4, th = l.h / 2;
    rrect(xj - hw, ty, hw * 2, th, 4); cx.fillStyle = c.xo ? hexA(C.fade, on ? .55 : .35) : hexA(C.fade, .2); cx.fill();
    cx.strokeStyle = hexA(C.fade, .9); cx.lineWidth = 1; cx.stroke();
    cx.beginPath(); cx.moveTo(xj - hw + 2, ty + 3); cx.lineTo(xj + hw - 2, ty + th - 3); cx.moveTo(xj - hw + 2, ty + th - 3); cx.lineTo(xj + hw - 2, ty + 3); cx.stroke();
  }
}
function drawEnv(E, off, l, xa, xb, tag) {       // a volume line (E's times + off = timeline): thin, faint dark edge, keys
  const bot = l.y + l.h;
  cx.beginPath();
  for (let x = xa; x <= xb; x += 2) { const y = bot - envV(E, x2t(x) - off) * l.h; x === xa ? cx.moveTo(x, y) : cx.lineTo(x, y); }
  cx.strokeStyle = "rgba(0,0,0,.16)"; cx.lineWidth = 1.6; cx.stroke();
  cx.strokeStyle = C.volume; cx.lineWidth = .6; cx.stroke();
  E.keys.forEach((k, i) => {
    const x = t2x(k.t + off), y = bot - k.v * l.h; if (x < xa - 10 || x > xb + 10) return;
    if (k.s) for (const sgn of [-1, 1]) {
      const hxp = t2x(k.t + off + sgn * k.hx), hyp = bot - (k.v + sgn * k.hv) * l.h;
      cx.strokeStyle = hexA(C.volume, .5); cx.lineWidth = .8; cx.beginPath(); cx.moveTo(x, y); cx.lineTo(hxp, hyp); cx.stroke();
      cx.beginPath(); cx.arc(hxp, hyp, 2.5, 0, 7); cx.fillStyle = C.volume; cx.fill(); cx.strokeStyle = "rgba(0,0,0,.4)"; cx.lineWidth = 1; cx.stroke();
    }
    const r = hover === `key${tag}:${i}` || drag && drag.k === "key" && drag.tag === tag && drag.i === i ? 5 : 4;
    cx.beginPath();
    if (k.s) cx.arc(x, y, r, 0, 7); else { cx.moveTo(x, y - r); cx.lineTo(x + r, y); cx.lineTo(x, y + r); cx.lineTo(x - r, y); cx.closePath(); }
    cx.fillStyle = C.volume; cx.fill(); cx.strokeStyle = "rgba(0,0,0,.45)"; cx.lineWidth = 1; cx.stroke();
  });
  if (drag && (drag.k === "line" || drag.k === "key") && drag.tag === tag) {
    const tt = drag.k === "key" ? E.keys[drag.i].t : drag.t - off, y = bot - envV(E, tt) * l.h, lb = g2db(v2g(envV(E, tt))) + " dB";
    cx.font = "11px Inter, Segoe UI"; cx.textAlign = "left"; const tw = cx.measureText(lb).width + 10, lx = clamp(t2x(tt + off) + 10, X0(), X0() + W() - tw);
    cx.fillStyle = "rgba(0,0,0,.7)"; cx.fillRect(lx, y - 20, tw, 16); cx.fillStyle = C.volume; cx.fillText(lb, lx + 5, y - 8);
  }
}
const FIN = 2;                                    // the fade handles sit this far inside the corner
function fadeArc(x, y, isIn, bot, on, r0 = 14) {   // the fade handle: a concave corner, its point towards the outer corner of the row
  const r = on ? r0 + 2 : r0, dx = isIn ? 1 : -1, dy = bot ? -1 : 1, X = x + dx * FIN, Y = y + dy * FIN;
  cx.beginPath(); cx.moveTo(X + dx * r, Y); cx.lineTo(X, Y + dy * r); cx.lineCap = "round";
  cx.strokeStyle = "rgba(0,0,0,.5)"; cx.lineWidth = 3.4; cx.stroke();
  cx.strokeStyle = hexA(C.fade, on ? 1 : .9); cx.lineWidth = on ? 2 : 1.5; cx.stroke(); cx.lineCap = "butt";
}
function fadePoints(Fo, a, b, l, bot) {           // where the handles of a fade are drawn / grabbed; the sound's curve is the picture's mirrored
  const mid = (t, s) => { const g = fcurve(.5, s); return [t2x(t), bot ? l.y + g * l.h : l.y + l.h - g * l.h]; };
  return { xi: t2x(a + Fo.fi), xo: t2x(b - Fo.fo), di: Fo.fi > 0 ? mid(a + Fo.fi / 2, Fo.fis) : null, do_: Fo.fo > 0 ? mid(b - Fo.fo / 2, Fo.fos) : null };
}
function drawFades(Fo, a, b, l, xmin, xmax, tag, bot, lineOnly) {
  const Y = g => bot ? l.y + g * l.h : l.y + l.h - g * l.h, edge = bot ? l.y + l.h : l.y;
  for (const [p, q] of [[a, a + Fo.fi], [b - Fo.fo, b]]) {
    if (q - p <= 0) continue;
    const xa = clamp(t2x(p), xmin, xmax), xb = clamp(t2x(q), xmin, xmax); if (xb <= xa) continue;
    const line = () => { for (let x = xa; x < xb + 1; x++) { const xx = Math.min(x, xb); cx.lineTo(xx, Y(fadeG(Fo, x2t(xx), a, b))); } };
    cx.beginPath(); cx.moveTo(xa, edge); line(); cx.lineTo(xb, edge); cx.closePath(); cx.fillStyle = "rgba(0,0,0,.25)"; cx.fill();
    cx.beginPath(); cx.moveTo(xa, Y(fadeG(Fo, x2t(xa), a, b))); line();
    cx.strokeStyle = "rgba(0,0,0,.6)"; cx.lineWidth = 3; cx.stroke();          // stays visible over a bright wave
    cx.strokeStyle = C.fade; cx.lineWidth = 1.4; cx.stroke();
  }
  if (lineOnly) return;
  const fp = fadePoints(Fo, a, b, l, bot), on = k => hover === tag + k || drag && drag.tag === tag && drag.k === k;
  if (fp.xi >= xmin - 2 && fp.xi <= xmax) fadeArc(fp.xi, edge, true, bot, on("fi"));
  if (fp.xo >= xmin && fp.xo <= xmax + 2) fadeArc(fp.xo, edge, false, bot, on("fo"));
  for (const [d, k] of [[fp.di, "fis"], [fp.do_, "fos"]]) {    // a dot in the middle of the curve: drag it up / down
    if (!d || d[0] < xmin || d[0] > xmax) continue;
    cx.beginPath(); cx.arc(d[0], d[1], on(k) ? 4.5 : 3.5, 0, 7);
    cx.fillStyle = C.fade; cx.fill(); cx.strokeStyle = "rgba(0,0,0,.45)"; cx.lineWidth = 1; cx.stroke();
  }
}
function drawRuler(cw) {
  cx.fillStyle = hexA(C.ruler, .5); cx.font = "11px Inter, Segoe UI"; cx.textAlign = "left";
  const w = W(), span = v1 - v0, steps = [.001, .005, .01, .05, .1, .25, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const sp = steps.find(q => span / q <= Math.max(4, w / 110)) || 1200;
  const lab = t => sp < 1 ? fmt(t) : fmt(t).replace(/\.000$/, "");
  let lastEnd = -1; const endVisible = v1 >= dur - 1e-6, endX = t2x(dur);
  for (let t = Math.ceil(v0 / sp) * sp; t <= v1 + 1e-9; t += sp) {
    const x = Math.round(t2x(t)); if (Math.abs(t - dur) < 1e-6) continue;
    cx.fillRect(x, RULER - 5, 1, 5);
    const lb = lab(t), tw = cx.measureText(lb).width;
    if (endVisible && x + 3 + tw > endX - 40) continue;
    if (x + 3 > lastEnd + 4 && x + 3 + tw < cw) { cx.fillText(lb, x + 3, RULER - 9); lastEnd = x + 3 + tw; }
  }
  if (endVisible) { const x = Math.round(endX), lb = fmt(dur).replace(/\.000$/, ""), tw = cx.measureText(lb).width; cx.fillRect(x - 1, RULER - 7, 1, 7); cx.fillText(lb, x - 4 - tw, RULER - 9); }
  const m = phMode();                             // what the playhead can land on
  if (m === "fast") {
    cx.fillStyle = hexA(C.fade, .85); const list = keyTimes().filter(t => t >= v0 && t <= v1);
    if (list.length * 5 < w) for (const t of list) cx.fillRect(Math.round(t2x(t)), RULER - 4, 1, 4);
  } else if (m === "frames" && t2x(1 / fps) - t2x(0) >= 5) {
    cx.fillStyle = hexA(C.fade, .6);
    for (let f = Math.ceil(v0 * fps); f / fps <= v1; f++) cx.fillRect(Math.round(t2x(f / fps)), RULER - 3, 1, 3);
  }
  if (pro()) {                                    // the whole file's fades live on the ruler in Pro: picture above, sound below
    const S = st.S, on = (tag, k) => hover === tag + k || drag && drag.k === k && drag.tag === tag;
    if (hasV()) { fadeArc(t2x(S.inT + S.V.fi), RULER - 15, true, false, on("gv", "fi"), 7); fadeArc(t2x(S.outT - S.V.fo), RULER - 15, false, false, on("gv", "fo"), 7); }
    if (NA()) { fadeArc(t2x(S.inT + S.fi), RULER, true, true, on("g", "fi"), 7); fadeArc(t2x(S.outT - S.fo), RULER, false, true, on("g", "fo"), 7); }
  }
}
function drawTrim() {                            // Start / End: thin flags in the ruler and a thin line down
  const S = st.S, bot = tl.clientHeight;
  for (const [t, k] of [[S.inT, "in"], [S.outT, "out"]]) {
    const x = Math.round(t2x(t)); if (x < -10 || x > tl.clientWidth + 10) continue;
    const on = hover === k || drag && drag.k === k;
    cx.fillStyle = hexA(C.trim, on ? .95 : .55); cx.fillRect(x, RULER, 1, bot - RULER);
    cx.fillStyle = hexA(C.trim, on ? 1 : .85); cx.fillRect(x - 1, 3, 3, RULER - 3);
  }
}
let phGrow = 0, phLast = 0, phLeft = 0;           // 0 = the small drop, 1 = the big one; phLeft: when the mouse left it
const DROP_UP = 220, DROP_DOWN = 520, DROP_WAIT = 700;   // ms: grows slowly, shrinks slower and only after a pause
function growDrop() {
  const on = hover === "ph" || drag && drag.k === "ph", now = performance.now(), dt = Math.min(50, now - phLast); phLast = now;
  if (on) phLeft = 0; else if (!phLeft) phLeft = now;
  if (!on && now - phLeft < DROP_WAIT) return;           // stays as it is for a moment after the mouse left
  const want = on ? 1 : 0;
  if (Math.abs(want - phGrow) < .004) { if (phGrow !== want) { phGrow = want; phDirty = true; } return; }
  phGrow += (want - phGrow) * (1 - Math.exp(-dt / (want > phGrow ? DROP_UP : DROP_DOWN) * 2.3)); phDirty = true;
}
function drawPlayhead() {
  const px = Math.round(t2x(ph)), xp = px + .5, bot = tl.clientHeight;
  if (px < -10 || px > tl.clientWidth + 10) return;
  cx.save(); cx.shadowColor = "rgba(0,0,0,.6)"; cx.shadowBlur = 4;
  cx.fillStyle = C.playhead; cx.fillRect(px, RULER - 2, 1, bot - RULER + 2);
  const r = 3.3 + 3.3 * phGrow, cy = RULER - r * 1.5;   // small at rest: the trim lines stay easy to grab
  cx.beginPath(); cx.moveTo(xp, RULER); cx.bezierCurveTo(xp - r * .2, RULER - r * .45, xp - r, cy + r * .7, xp - r, cy);
  cx.arc(xp, cy, r, Math.PI, 0); cx.bezierCurveTo(xp + r, cy + r * .7, xp + r * .2, RULER - r * .45, xp, RULER);
  cx.shadowColor = "rgba(0,0,0,.75)"; cx.shadowBlur = 9; cx.fill();
  cx.shadowBlur = 0; cx.strokeStyle = "rgba(255,255,255,.9)"; cx.lineWidth = .9 + .3 * phGrow; cx.stroke();
  cx.restore();
}
let overPeaks = null, KF = [];
function drawOverview() {
  const dpr = devicePixelRatio || 1, w = ov.clientWidth, h = ov.clientHeight;
  if (ov.width !== Math.round(w * dpr)) { ov.width = Math.round(w * dpr); ov.height = Math.round(h * dpr); overPeaks = null; }
  ox.setTransform(dpr, 0, 0, dpr, 0, 0); ox.clearRect(0, 0, w, h);
  if (!pro()) {
    if (!overPeaks || overPeaks.length !== w) { overPeaks = new Float32Array(w); for (let x = 0; x < w; x++) { const mm = compMM(x / w * dur, (x + 1) / w * dur); overPeaks[x] = mm ? Math.max(-mm[0], mm[1]) : 0; } }
    for (let x = 0; x < w; x++) { const t = (x + .5) / w * dur; ox.fillStyle = t >= st.S.inT && t <= st.S.outT && !inCut(t) ? hexA(C.overview, .14) : hexA(C.removed, .22); const a = Math.min(1, overPeaks[x]) * h * .8; ox.fillRect(x, (h - a) / 2, 1, Math.max(1, a)); }
  } else {
    const L = [...Array.from({ length: st.R.nv }, (_, i) => -(st.R.nv - i)), ...st.R.lanes.map((_, i) => i)], lh = h / Math.max(1, L.length);
    for (const c of st.R.clips) { const j = L.indexOf(c.lane); ox.fillStyle = hexA(C.overview, csel.has(c.id) ? .3 : .13); ox.fillRect(c.start / dur * w, j * lh + 1, (c.out - c.in) / dur * w, Math.max(1, lh - 2)); }
    ox.fillStyle = "rgba(0,0,0,.45)"; ox.fillRect(0, 0, st.S.inT / dur * w, h); ox.fillRect(st.S.outT / dur * w, 0, w, h);
  }
  if (v1 - v0 < dur - 1e-6) {                     // the view: only while zoomed in
    const vx = v0 / dur * w, vw = Math.max(3, (v1 - v0) / dur * w);
    ox.fillStyle = hexA(C.overviewView, .42); ox.fillRect(vx, 0, vw, h);
  }
  ox.fillStyle = C.playhead; ox.fillRect(Math.round(ph / dur * w), 0, 1, h);
}
