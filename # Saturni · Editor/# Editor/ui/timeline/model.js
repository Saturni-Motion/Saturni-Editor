// The model: tracks of pieces + one layer over the whole timeline; volume lines, fades, joins, rows.

// ---------- the model: tracks of pieces + one layer over the whole timeline (Start/End, cuts, fades, volume)
function bits() { return { fi: 0, fo: 0, fis: 0, fos: 0, xo: 0, vol: { keys: [], level: .5 }, fx: null }; }
function clipsFor(s, pos) {
  const g = nextId++, out = [];
  if (s.video) out.push({ id: nextId++, g, src: s.i, lane: -1, stream: 0, start: pos, in: 0, out: s.still ? STILL : s.duration, ...bits() });
  s.audios.forEach((a, n) => out.push({ id: nextId++, g, src: s.i, lane: n, stream: n, start: pos, in: 0, out: s.duration, ...bits() }));
  return out;
}
function core() { return JSON.stringify({ S: st.S, c: st.R.clips, nv: st.R.nv, l: st.R.lanes, G: st.G, n: st.nsrc, t: st.R.tail || 0 }); }
function snapshot() { return JSON.stringify(st); }
function remember() { undoS.push(snapshot()); redoS = []; buttons(); }
function restore(s) {                            // Simple / Pro is a view, undo stays in the one in use
  const m = st.mode; st = JSON.parse(s); st.mode = m; drag = null; sel = null; selLanes = null; clipSel = null; csel.clear();
  if (kind !== "photo") { document.body.classList.toggle("video", hasV()); document.body.classList.toggle("audio", !hasV()); }
  applyMode(); fields(); layoutAll(); adjShow(); sndShow(); applyAud(); overPeaks = null; dirty = true;
}
function undo() { if (!undoS.length) return; redoS.push(snapshot()); restore(undoS.pop()); }
function redo() { if (!redoS.length) return; undoS.push(snapshot()); restore(redoS.pop()); }
function segs() {                                // the kept parts of the timeline: Start..End minus the cuts
  const S = st.S; let out = [[S.inT, S.outT]];
  for (const [a, b] of S.cuts) out = out.flatMap(([x, y]) => b <= x || a >= y ? [[x, y]] : [[x, a], [b, y]].filter(([p, q]) => q - p > 1e-4));
  return out;
}
function kept() { return segs().reduce((s, [a, b]) => s + b - a, 0); }
function changed() { return kind === "photo" ? JSON.stringify(st.G) !== G0 : core() !== BASE; }
function inCut(t) { return st.S.cuts.find(([a, b]) => t >= a && t < b); }
function addCut(a, b) {
  const all = [...st.S.cuts, [a, b]].sort((p, q) => p[0] - q[0]), m = [];
  for (const c of all) { if (m.length && c[0] <= m[m.length - 1][1] + 1e-6) m[m.length - 1][1] = Math.max(m[m.length - 1][1], c[1]); else m.push([...c]); }
  st.S.cuts = m;
}
function project() { return st.nsrc > 1; }
var dirtyTold = null;
function buttons() {
  const unsaved = saving || (projSaved !== null ? core() !== projSaved : changed());                 // окно спросит перед закрытием (api._on_closing)
  if (unsaved !== dirtyTold) { dirtyTold = unsaved; py("set_dirty", unsaved); }
  if (saving) return;
  $("undo").disabled = !undoS.length; $("redo").disabled = !redoS.length;
  const ok = changed() && (kind === "photo" || kept() > 0);
  $("save").disabled = !ok; $("savemenu").disabled = !ok && kind === "photo";   // a project can be saved any time
  $("save").textContent = project() ? "Save as new…" : "Save";
  $("trash").disabled = !csel.size && !sel && !clipSel;
  $("razor").classList.toggle("on", tool === "razor");
  if (kind === "photo") return;
  const m = $("mix1"); m.style.display = Math.max(NA(), st.R.lanes.length) > 1 ? "inline-flex" : "none"; m.classList.toggle("on", !!st.G.one);
}
function picturePlain() {                        // nothing in the picture changes: it can be copied
  const R = st.R, S = st.S, G = st.G, v = R.clips.filter(c => c.lane < 0);
  return !G.crop && !G.out.fps && !G.out.mbps && JSON.stringify(G.adj) === JSON.stringify(ADJ0) && !S.V.fi && !S.V.fo
    && v.every(c => c.lane === -1 && !c.fi && !c.fo);
}
function fields() {
  if (kind === "photo") { meta(); buttons(); return; }
  recalc();
  if (document.activeElement !== $("st")) $("st").value = fmt(st.S.inT);
  if (document.activeElement !== $("en")) $("en").value = fmt(st.S.outT);
  dropVoices(); meta(); buttons(); dirty = true;
}
function size(b) { return b < 1048576 ? Math.max(1, Math.round(b / 1024)) + " KB" : (b / 1048576).toFixed(b > 1e8 ? 0 : 1) + " MB"; }
function meta() {
  const s = SRC[0]; let parts;
  if (project()) { $("name").textContent = projName || `${st.nsrc} files`; parts = [act().map(x => x.stem).join(", ")]; }
  else if (kind === "photo") parts = [`${s.w}×${s.h}`, s.format, size(s.size)];
  else if (s.video) parts = [`${s.w}×${s.h}`, s.fps ? (+s.fps.toFixed(2)) + " fps" : "", s.vcodec.toUpperCase(), s.vbr ? (s.vbr / 1e6).toFixed(1) + " Mbps" : "",
    s.audios.length ? s.audios.map(a => a.codec.toUpperCase()).join(" + ") : "no sound", size(s.size)];
  else parts = [s.audios[0].codec.toUpperCase(), s.audios[0].br ? Math.round(s.audios[0].br / 1000) + " kbps" : "", (s.audios[0].rate / 1000) + " kHz", size(s.size)];
  if (!project()) $("name").textContent = projName || s.name;
  let h = parts.filter(Boolean).join("  ·  ");
  if (kind !== "photo") { const k = kept(); h += `  ·  <b>${fmt(k)}</b>` + (Math.abs(k - dur) > 1e-3 ? ` of ${fmt(dur)}` : ""); }
  $("meta").innerHTML = h; fadeStrip($("info"));
}

// ---------- volume, fades, joins
function v2g(v) { return v >= .5 ? Math.pow(10, (v - .5) / .5 * 12 / 20) : Math.pow(v / .5, 3); }   // top = +12 dB
function g2db(g) { if (g <= 1e-5) return "−∞"; const d = 20 * Math.log10(g); return (d >= 0 ? "+" : "") + d.toFixed(1); }
function bez(a, b) {
  const L = b.t - a.t;
  const p1 = a.s ? [a.t + clamp(a.hx, 0, L), a.v + a.hv] : [a.t, a.v];
  const p2 = b.s ? [b.t - clamp(b.hx, 0, L), b.v - b.hv] : [b.t, b.v];
  return [[a.t, a.v], p1, p2, [b.t, b.v]];
}
function bpt(P, u) { const w = 1 - u; return [0, 1].map(i => w * w * w * P[0][i] + 3 * w * w * u * P[1][i] + 3 * w * u * u * P[2][i] + u * u * u * P[3][i]); }
function envV(E, t) {                            // E = {keys, level}; t in E's own time
  const k = E.keys; if (!k.length) return E.level;
  if (t <= k[0].t) return k[0].v; if (t >= k[k.length - 1].t) return k[k.length - 1].v;
  let i = 0; while (i < k.length - 2 && k[i + 1].t <= t) i++;
  const a = k[i], b = k[i + 1];
  if (!a.s && !b.s) return a.v + (b.v - a.v) * (t - a.t) / Math.max(1e-9, b.t - a.t);
  const P = bez(a, b); let lo = 0, hi = 1;
  for (let n = 0; n < 24; n++) { const m = (lo + hi) / 2; if (bpt(P, m)[0] < t) lo = m; else hi = m; }
  return clamp(bpt(P, (lo + hi) / 2)[1], 0, 1);
}
function fcurve(x, s) { return Math.pow(Math.sin(Math.PI / 2 * clamp(x, 0, 1)), Math.pow(2, -2 * s)); }   // s: -1..1, 0 = equal power
function fadeG(Fo, t, a, b) {
  let g = 1;
  if (Fo.fi > 0 && t < a + Fo.fi) g *= fcurve((t - a) / Fo.fi, Fo.fis);
  if (Fo.fo > 0 && t > b - Fo.fo) g *= fcurve((b - t) / Fo.fo, Fo.fos);
  return g;
}
function shapeFor(g) { const p = Math.log(clamp(g, .01, .99)) / Math.log(Math.SQRT1_2); return clamp(-Math.log2(p) / 2, -1, 1); }   // the curve that passes g at the middle
function nextAdj(c) { return st.R.clips.find(q => q !== c && q.lane === c.lane && Math.abs(q.start - clipEnd(c)) < 1e-4); }
function prevAdj(c) { return st.R.clips.find(q => q !== c && q.lane === c.lane && Math.abs(clipEnd(q) - c.start) < 1e-4); }
function clipG(c, t) {                           // a piece's own volume line, fades and joins
  let g = v2g(envV(c.vol, t - c.start)) * fadeG(c, t, c.start, clipEnd(c));
  if (c.xo > 0 && nextAdj(c)) { const d = c.xo / 2, e = clipEnd(c); if (t > e - d) g *= fcurve((e - t) / d, 0); }
  const p = prevAdj(c); if (p && p.xo > 0) { const d = p.xo / 2; if (t < c.start + d) g *= fcurve((t - c.start) / d, 0); }
  return g;
}
function globalG(t) { const S = st.S; return v2g(envV(S, t)) * fadeG(S, t, S.inT, S.outT); }
function clipAtT(lane, t) { return st.R.clips.find(c => c.lane === lane && t >= c.start && t < clipEnd(c)); }
function topVideoAt(t) { for (let v = st.R.nv; v >= 1; v--) { const c = clipAtT(-v, t); if (c) return c; } return null; }
function picG(t) { const S = st.S, c = topVideoAt(t); return fadeG(S.V, t, S.inT, S.outT) * (c ? fadeG(c, t, c.start, clipEnd(c)) : 1); }
function clampFades() { const S = st.S, n = S.outT - S.inT; for (const F of [S, S.V]) { F.fi = Math.min(F.fi, n); F.fo = Math.min(F.fo, n - F.fi); } }
function thin(list) { return list.filter((p, i) => i === 0 || i === list.length - 1 || !(Math.abs(p[1] - list[i - 1][1]) < 1e-6 && Math.abs(p[1] - list[i + 1][1]) < 1e-6)); }
function addRange(ts, p, q, n, a, b) { for (let i = 0; i <= n; i++) { const t = p + (q - p) * i / n; if (t >= a && t <= b) ts.add(t); } }
function envTimes(ts, E, off, a, b) {            // where a volume line needs points (E's times + off = timeline)
  const k = E.keys;
  for (let i = 0; i < k.length; i++) { const t = k[i].t + off; if (t >= a && t <= b) ts.add(t); if (i < k.length - 1 && k[i + 1].t + off > a && t < b) addRange(ts, t, k[i + 1].t + off, 24, a, b); }
}
function fadeTimes(ts, Fo, s, e, a, b) {
  if (Fo.fi > 0) addRange(ts, s, s + Fo.fi, 32, a, b);
  if (Fo.fo > 0) addRange(ts, e - Fo.fo, e, 32, a, b);
}

// ---------- lanes (the timeline's rows)
function laneName(k) { return k === "S" ? "" : k < 0 ? "V" + (-k) : "A" + (k + 1); }
function lanes() {
  const h = tl.clientHeight, top = RULER + 2, L = [];
  if (!pro()) { L.push({ k: "S", y: top, h: h - top }); return L; }
  const R = st.R, na = R.lanes.length, nv = R.nv, gap = 3, hs = R.hs || (R.hs = {});
  const base = Math.max(34, (h - top - nv * (22 + gap) - gap * na) / Math.max(1, na));
  let y = top - vscroll;
  for (let v = nv; v >= 1; v--) { const lh = 22 * (hs[-v] || 1); L.push({ k: -v, y, h: lh }); y += lh + gap; }
  for (let n = 0; n < na; n++) { const lh = base * (hs[n] || 1); L.push({ k: n, y, h: lh }); y += lh + gap; }
  return L;
}
function clampScroll() {
  if (!pro()) { vscroll = 0; return; }
  const L = lanes(); if (!L.length) { vscroll = 0; return; }
  const last = L[L.length - 1], full = last.y + last.h + vscroll - (RULER + 2);
  vscroll = clamp(vscroll, 0, Math.max(0, full - (tl.clientHeight - RULER - 2)));
}
function laneAt(y) { return lanes().find(l => y >= l.y && y < l.y + l.h); }
