// Shared state and small helpers: time <-> x, snapping, the view.

const $ = id => document.getElementById(id);
// The Python bridge comes ~0.5 s after the page; the start doesn't wait for it (/load and the waves come over HTTP).
const PY = new Promise(r => window.pywebview && pywebview.api && pywebview.api.load ? r() : addEventListener("pywebviewready", r, { once: true }));
async function py(name, ...a) { await PY; return pywebview.api[name](...a); }
const baseC = document.createElement("canvas"), bx = baseC.getContext("2d");
const tl = $("tlc"), cx = tl.getContext("2d"), ov = $("overc"), ox = ov.getContext("2d"), mt = $("meter"), mx = mt.getContext("2d");
const RULER = 24, PAD = 4, HDR = 26;            // ruler on top; HDR = the track names column (kept in both modes)
let SRC = [], C = {}, O = {}, DEF = null, WV = [];
let st = null, BASE = "", G0 = "";               // st: everything that gets saved (undoable)
let sel = null, selLanes = null, clipSel = null, ph = 0, playing = false, loop = false, pmode = "precise", pvq = 1, waveZoom = 1, tool = "select";
let undoS = [], redoS = [], dirty = true, phDirty = false, drag = null, hover = null, csel = new Set();
let v0 = 0, v1 = 1, dur = 1, fps = 0, kind = "audio", nextId = 1, vscroll = 0;
const cp = o => JSON.parse(JSON.stringify(o)), STILL = 5;   // a picture starts this long, in seconds
const AUDX = { comp: 0, cth: -18, crat: 3, catk: 10, crel: 150, cmk: 0, lim: 0, lceil: -1, lrel: 60 };
const AUD0 = { gain: 0, hp: 0, lp: 0, bass: 0, treble: 0, ...AUDX };
const ADJ0 = { exp: 0, bri: 0, con: 0, sat: 0, temp: 0, tint: 0, hi: 0, sh: 0, wh: 0, bl: 0, sharp: 0, clar: 0, grain: 0, nr: 0, vig: 0, disp: 0,
               hsl: { h: [0, 0, 0, 0, 0, 0, 0, 0], s: [0, 0, 0, 0, 0, 0, 0, 0], l: [0, 0, 0, 0, 0, 0, 0, 0] } };

// ---------- helpers
function fmt(t) { t = Math.max(0, t); const m = Math.floor(t / 60), r = t - m * 60; return m + ":" + r.toFixed(3).padStart(6, "0"); }
function parse(s) { const p = s.trim().split(":").map(Number); if (p.some(isNaN)) return null; return p.length === 1 ? p[0] : p[0] * 60 + p[1]; }
function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
function hexA(h, a) { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; }
function pro() { return st.mode === "pro"; }
function X0() { return PAD + HDR; }
function W() { return tl.clientWidth - X0() - PAD; }                // the time axis' width
function x2t(x) { return v0 + (x - X0()) / W() * (v1 - v0); }
function t2x(t) { return X0() + (t - v0) / (v1 - v0) * W(); }
function phMode() { return fps ? pmode : "precise"; }  // no picture: nothing to snap to
function keyIdx(keys, u) { let lo = 0, hi = keys.length; while (lo < hi) { const m = (lo + hi) >> 1; if (keys[m] < u) lo = m + 1; else hi = m; } return lo; }
function nearKey(keys, u) { const i = keyIdx(keys, u), a = keys[i - 1], b = keys[i]; return a === undefined ? b : b === undefined ? a : u - a < b - u ? a : b; }
function keyTimes() {                            // the timeline's keyframes, with the starts and ends of the pieces of V1
  const out = [];
  for (const c of st.R.clips) {
    if (c.lane !== -1) continue;
    out.push(c.start, clipEnd(c));
    for (const k of KF[c.src] || []) if (k >= c.in && k <= c.out) out.push(c.start + k - c.in);
  }
  return out.sort((a, b) => a - b);
}
function keySnap(t) {
  const list = st.R.clips.filter(c => c.lane === -1);
  if (list.some(c => !KF[c.src])) return Math.min(dur, Math.round(t * fps) / fps);   // keyframes still loading
  let best = t, bd = 1e9;
  const put = q => { const d = Math.abs(q - t); if (d < bd) { bd = d; best = q; } };
  for (const c of list) {
    put(c.start); put(clipEnd(c));
    const keys = KF[c.src], u = clamp(c.in + t - c.start, c.in, c.out), i = keyIdx(keys, u);
    for (const k of [keys[i - 1], keys[i]]) if (k !== undefined && k >= c.in && k <= c.out) put(c.start + k - c.in);
  }
  return best;
}
function snapT(t) {
  t = clamp(t, 0, dur); const m = phMode();
  return m === "frames" ? Math.min(dur, Math.round(t * fps) / fps) : m === "fast" ? keySnap(t) : t;
}
function step() { return fps ? 1 / fps : 0.01; }
function clampView() { const len = Math.max(Math.min(v1 - v0, dur), Math.min(dur, 0.01)); if (v0 < 0) v0 = 0; if (v0 + len > dur) v0 = Math.max(0, dur - len); v1 = v0 + len; }
function act() { return SRC.slice(0, st.nsrc); }
function NA() { return Math.max(0, ...act().map(s => s.audios.length)); }
function hasV() { return act().some(s => s.video); }
function firstV() { return act().find(s => s.video); }
function clipEnd(c) { return c.start + c.out - c.in; }
function fpsOr30() { return fps || 30; }
function recalc() {
  const R = st.R, old = dur;
  dur = Math.max(0.01, ...R.clips.map(clipEnd)) + (R.tail || 0);
  const S = st.S;
  if (S.atEnd || S.outT > dur) S.outT = dur;
  S.inT = Math.min(S.inT, S.outT);
  const fv = firstV(); fps = fv ? fv.fps : 0;
  if (Math.abs(old - dur) > 1e-9) clampView();
}
