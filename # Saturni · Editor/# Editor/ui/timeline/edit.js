// Editing: delete, copy / paste, split, move, tracks.

// ---------- delete: Simple = a cut over the whole file; Pro = out of the chosen tracks
function placeDel() {
  const b = $("del");
  if (!sel || drag && (drag.k === "sel" || drag.k === "rsel")) { b.style.display = "none"; return; }
  const xa = t2x(Math.min(...sel)), xb = t2x(Math.max(...sel)), x = clamp((xa + xb) / 2, 40, tl.clientWidth - 40);
  b.style.display = "inline-flex"; b.style.left = x + "px"; b.style.top = (RULER + 14) + "px";
}
function deleteSel() {
  if (clipSel) return clipPart("delete");
  if (!sel) { deleteClips(); return; }
  const a = clamp(Math.min(...sel), 0, dur), b = clamp(Math.max(...sel), 0, dur);
  remember();
  if (pro()) {
    if (!selLanes || lanes().every(l => selLanes.includes(l.k))) rippleAll(a, b);   // every track: cut out, close the gap
    else lift(a, b, selLanes);                                                     // some tracks: a gap there
    seek(a);
  } else {
    const S = st.S;
    if (a <= S.inT + 1e-6 && b >= S.inT) S.inT = Math.min(b, S.outT);
    else if (b >= S.outT - 1e-6 && a <= S.outT) { S.outT = Math.max(a, S.inT); S.atEnd = false; }
    else addCut(a, b);
    clampFades();
    seek(clamp(b, 0, dur));
  }
  sel = null; selLanes = null; fields();
}
function deleteClips(ids) {
  ids = ids || [...csel]; if (!ids.length) return;
  remember(); st.R.clips = st.R.clips.filter(c => !ids.includes(c.id)); csel.clear(); fields();
}
function rippleDelete() {                        // delete and close the gap on those tracks
  const R = st.R, list = R.clips.filter(c => csel.has(c.id)).sort((a, b) => b.start - a.start); if (!list.length) return;
  remember();
  for (const c of list) {
    const len = c.out - c.in, e = clipEnd(c);
    R.clips = R.clips.filter(q => q !== c);
    for (const q of R.clips) if (q.lane === c.lane && q.start >= e - 1e-6) q.start -= len;
  }
  csel.clear(); fields();
}
let clipB = null;                                // what Copy / Cut took
function copyClips() {
  const list = st.R.clips.filter(c => csel.has(c.id)); if (!list.length) return false;
  clipB = { base: Math.min(...list.map(c => c.start)), items: cp(list) }; return true;
}
function cutClips() { if (copyClips()) deleteClips(); }
function pasteClips(t) {                         // on the same tracks from the playhead on, over what's there
  if (!clipB) return;
  remember();
  const R = st.R, gm = new Map(), made = clipB.items.filter(q => q.src < st.nsrc).map(q => {
    if (!gm.has(q.g)) gm.set(q.g, nextId++);
    if (q.lane >= 0) while (R.lanes.length <= q.lane) R.lanes.push({ fx: null }); else R.nv = Math.max(R.nv, -q.lane);
    const d = { ...cp(q), id: nextId++, g: gm.get(q.g), start: t + q.start - clipB.base, xo: 0 }; R.clips.push(d); return d;
  });
  overwrite(made); csel = new Set(made.map(c => c.id)); fields();
}
function duplicateClips() {
  const keep = clipB; if (!copyClips()) return;
  pasteClips(Math.max(...clipB.items.map(clipEnd))); clipB = keep;
}
function selectAllClips() { csel = new Set(st.R.clips.map(c => c.id)); buttons(); dirty = true; }

// ---------- Pro editing
function splitClip(c, t) {                       // -> the right half (a new piece); the volume line is split too
  if (t <= c.start + 1e-4 || t >= clipEnd(c) - 1e-4) return null;
  const u = t - c.start, v = envV(c.vol, u), keys = c.vol.keys;
  const d = { ...cp(c), id: nextId++, in: c.in + u, start: t, fi: 0, fis: 0 };
  d.vol = { level: c.vol.level, keys: keys.length ? [{ t: 0, v, s: false, hx: 0, hv: 0 }, ...keys.filter(k => k.t > u).map(k => ({ ...k, t: k.t - u }))] : [] };
  c.vol.keys = keys.length ? [...keys.filter(k => k.t < u), { t: u, v, s: false, hx: 0, hv: 0 }] : [];
  c.out = c.in + u; c.fo = 0; c.fos = 0; c.xo = 0;
  st.R.clips.push(d); return d;
}
function splitAt(t, only) {                      // selected pieces, or the given ones, or everything under t
  const pool = only || (csel.size ? st.R.clips.filter(c => csel.has(c.id)) : st.R.clips);
  const list = pool.filter(c => t > c.start + 1e-4 && t < clipEnd(c) - 1e-4), g = new Map(), rights = [];
  if (!list.length) return;
  remember();
  for (const c of list) { const d = splitClip(c, t); if (!d) continue; if (!g.has(c.g)) g.set(c.g, nextId++); d.g = g.get(c.g); rights.push(d.id); }
  if (rights.length) csel = new Set(rights);    // the piece after the cut is the one selected now
  fields();
}
function shiftGlobal(a, b) {                     // the timeline lost a..b: move Start/End, cuts and the whole-file line
  const S = st.S, d = b - a, f = t => t >= b ? t - d : t > a ? a : t;
  S.inT = f(S.inT); S.outT = f(S.outT);
  S.cuts = S.cuts.map(([p, q]) => [f(p), f(q)]).filter(([p, q]) => q - p > 1e-4);
  S.keys = S.keys.filter(k => k.t <= a || k.t >= b).map(k => k.t >= b ? { ...k, t: k.t - d } : k);
}
function rippleAll(a, b) { lift(a, b, null); for (const c of st.R.clips) if (c.start >= b - 1e-6) c.start -= b - a; shiftGlobal(a, b); }
function lift(a, b, only) {                      // remove a..b from some tracks (null: all), nothing moves
  const R = st.R, on = c => !only || only.includes(c.lane);
  for (const c of [...R.clips]) if (on(c)) splitClip(c, a);
  for (const c of [...R.clips]) if (on(c)) splitClip(c, b);
  R.clips = R.clips.filter(c => !(on(c) && c.start >= a - 1e-6 && clipEnd(c) <= b + 1e-6));
}
function clipPart(what) {                        // the part chosen inside a piece: delete it, or keep only it
  const c = st.R.clips.find(q => q.id === clipSel.id); if (!c) { clipSel = null; return; }
  const a = Math.max(c.start, Math.min(clipSel.a, clipSel.b)), b = Math.min(clipEnd(c), Math.max(clipSel.a, clipSel.b));
  remember();
  const right = splitClip(c, b), mid = splitClip(c, a) || c;
  if (what === "delete") st.R.clips = st.R.clips.filter(q => q !== mid);
  else { st.R.clips = st.R.clips.filter(q => q !== c || q === mid).filter(q => q !== right); if (mid !== c) st.R.clips = st.R.clips.filter(q => q !== c); }
  clipSel = null; csel.clear(); fields();
}
function overwrite(moved) {                      // a dropped piece replaces what was under it on its track
  const R = st.R, ids = new Set(moved.map(c => c.id));
  for (const m of moved) {
    const a = m.start, b = clipEnd(m);
    for (const c of [...R.clips]) {
      if (ids.has(c.id) || c.lane !== m.lane || clipEnd(c) <= a + 1e-6 || c.start >= b - 1e-6) continue;
      if (c.start < a && clipEnd(c) > b) { const d = splitClip(c, b); if (d) d.g = nextId++; }
      if (c.start < a) { c.out = c.in + a - c.start; c.fo = Math.min(c.fo, c.out - c.in); continue; }
      if (clipEnd(c) > b) { const u = b - c.start; c.vol.keys = c.vol.keys.map(k => ({ ...k, t: k.t - u })); c.in += u; c.start = b; c.fi = Math.min(c.fi, c.out - c.in); continue; }
      R.clips = R.clips.filter(x => x !== c);
    }
  }
  R.clips = R.clips.filter(c => c.out - c.in > 1e-4);
}
function snapEdges(t, skip) {                     // pull to the playhead, 0, Start/End and piece edges within 8 px
  const tol = 8 / W() * (v1 - v0); let best = t, bd = tol;
  const cand = [0, ph, st.S.inT, st.S.outT]; for (const c of st.R.clips) if (!skip.has(c.id)) cand.push(c.start, clipEnd(c));
  for (const q of cand) if (Math.abs(q - t) < bd) { bd = Math.abs(q - t); best = q; }
  return best;
}
function addTrack(type, above) {
  remember(); const R = st.R;
  if (type === "v") {
    if (above !== undefined) { for (const c of R.clips) if (c.lane < 0 && c.lane < -above + 1) c.lane--; }
    R.nv++;
  } else R.lanes.push({ fx: null, keep: true });
  fields(); clampScroll();
}
function deleteTrack(k) {
  const R = st.R;
  remember();
  R.clips = R.clips.filter(c => c.lane !== k);
  if (k < 0) { for (const c of R.clips) if (c.lane < k) c.lane++; R.nv = Math.max(0, R.nv - 1); delete R.hs[k]; }
  else { R.lanes.splice(k, 1); for (const c of R.clips) if (c.lane > k) c.lane--; }
  csel.clear(); fields(); clampScroll();
}
function dropEmptyLanes() {                      // tracks made while dragging go away again when left empty
  const R = st.R;
  while (R.lanes.length > Math.max(1, NA()) && !R.clips.some(c => c.lane === R.lanes.length - 1) && !R.lanes[R.lanes.length - 1].keep) R.lanes.pop();
  while (R.nv > 1 && !R.clips.some(c => c.lane === -R.nv) && !R.vkeep) R.nv--;
}
