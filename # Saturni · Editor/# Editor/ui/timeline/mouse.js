// Timeline mouse: hits, drags, the overview strip.

// ---------- timeline mouse
function envHit(E, off, l, x, y, tag, xa, xb) {  // a volume line's keys, handles, the line itself
  if (y < l.y - 6 || y > l.y + l.h + 6 || x < xa - 6 || x > xb + 6) return null;
  const bot = l.y + l.h;
  for (let i = 0; i < E.keys.length; i++) {
    const k = E.keys[i], kx = t2x(k.t + off), ky = bot - k.v * l.h;
    if (k.s) for (const sgn of [-1, 1]) { const hx = t2x(k.t + off + sgn * k.hx), hy = bot - (k.v + sgn * k.hv) * l.h; if (Math.hypot(x - hx, y - hy) < 6) return { k: "hnd", E, off, l, tag, i, sgn }; }
    if (Math.hypot(x - kx, y - ky) < 7) return { k: "key", E, off, l, tag, i };
  }
  if (y > l.y && y < bot && x >= xa && x <= xb && Math.abs(y - (bot - envV(E, x2t(x) - off) * l.h)) < 4) return { k: "line", E, off, l, tag };
  return null;
}
function fadeHit(Fo, a, b, l, x, y, tag, bot) {
  const fp = fadePoints(Fo, a, b, l, bot), R0 = { F: Fo, a, b, l, tag, bot };
  for (const [d, k] of [[fp.di, "fis"], [fp.do_, "fos"]]) if (d && Math.hypot(x - d[0], y - d[1]) < 7) return { k, ...R0 };
  if (bot ? y >= l.y + l.h - 17 : y <= l.y + 17) {
    if (x >= fp.xi - 2 && x <= fp.xi + 18) return { k: "fi", ...R0 };
    if (x >= fp.xo - 18 && x <= fp.xo + 2) return { k: "fo", ...R0 };
  }
  return null;
}
function hit(x, y) {
  if (x < X0() - 4) return { k: y < RULER ? "none" : "hdr", l: (laneAt(y) || {}).k };
  const S = st.S, t = x2t(x);
  if (y < RULER) {
    const big = hover === "ph";                   // only inside the drop itself: the trim flags come first everywhere else
    if (Math.abs(x - t2x(ph)) < (big ? 7.5 : 4.5) && y >= RULER - (big ? 18 : 10)) return { k: "ph" };
    if (pro() && y >= RULER - 15) {
      const up = hasV() && (y < RULER - 7 || !NA()), F = up ? S.V : S;
      if (hasV() || NA()) {
        const R0 = { F, a: S.inT, b: S.outT, tag: up ? "gv" : "g", bot: !up, l: { y: RULER - 30, h: 60 } }, xi = t2x(S.inT + F.fi), xo = t2x(S.outT - F.fo);
        if (x > xi + 1 && x <= xi + 11) return { k: "fi", ...R0 };
        if (x < xo - 1 && x >= xo - 11) return { k: "fo", ...R0 };
      }
    }
    if (Math.abs(x - t2x(S.inT)) < 5) return { k: "in" };
    if (Math.abs(x - t2x(S.outT)) < 5) return { k: "out" };
    return { k: "ruler" };
  }
  if (!pro()) {
    if (tool === "razor") return { k: "razor" };
    const l = lanes()[0], x0 = X0(), xe = x0 + W();
    if (hasV()) { const f = fadeHit(S.V, S.inT, S.outT, l, x, y, "gv", false); if (f) return f; }
    if (NA()) { const f = fadeHit(S, S.inT, S.outT, l, x, y, "g", true); if (f) return f; }
    if (NA()) { const e = envHit(S, 0, l, x, y, "S", x0, xe); if (e) return e; }
    if (Math.abs(x - t2x(S.inT)) < 4) return { k: "in" };
    if (Math.abs(x - t2x(S.outT)) < 4) return { k: "out" };
    return { k: "wave" };
  }
  const l = laneAt(y); if (!l) return { k: "empty" };
  const tol = 6 / W() * (v1 - v0), near = st.R.clips.filter(q => q.lane === l.k && t >= q.start - tol && t < clipEnd(q) + tol);
  const c = near.find(q => csel.has(q.id)) || near.find(q => t >= q.start && t < clipEnd(q)) || near[0];   // a selected piece wins at a join
  if (!c) return { k: "empty", l };
  if (tool === "razor") return { k: "razor", c, l };
  let joint = null;
  for (const q of st.R.clips) {                   // joins (transitions) between touching sound pieces
    if (q.lane !== l.k || q.lane < 0) continue; const n = nextAdj(q); if (!n) continue;
    const xj = t2x(clipEnd(q)), hw = Math.max(6, t2x(clipEnd(q) + q.xo / 2) - xj);
    if (Math.abs(x - xj) < hw && y > l.y + l.h / 4 && y < l.y + l.h * .75) {
      if (q.xo) return { k: "trans", c: q, l };
      if (!csel.has(q.id) && !csel.has(n.id)) return { k: "joint", c: q, l };
      joint = q;                                  // beside a selected piece: a drag moves its edge, a click makes the transition
    }
  }
  const xa = t2x(c.start), xb = t2x(clipEnd(c)), y1 = l.y + 1, h1 = l.h - 2, cl = { y: y1, h: h1 };
  if (xb - xa >= 26 && h1 >= 16) { const f = fadeHit(c, c.start, clipEnd(c), cl, x, y, "c" + c.id, c.lane >= 0); if (f) return { ...f, c }; }
  if (c.lane >= 0 && h1 > 26) { const e = envHit(c.vol, c.start, cl, x, y, "c" + c.id, xa, xb); if (e) return { ...e, c }; }
  if (Math.abs(x - xa) < 6) return { k: "edge", c, e: "l", l, joint };
  if (Math.abs(x - xb) < 6) return { k: "edge", c, e: "r", l, joint };
  if (y < l.y + Math.max(8, l.h * .3)) return { k: "crange", c, l };
  return { k: "clip", c, l };
}
function edgeSnap(raw, i, e, edge0) {             // a piece's edge lands where the playhead may: in Fast, on the keyframes of its own file
  const m = phMode(); if (m === "precise") return raw;
  if (m === "frames") return Math.round(raw * fps) / fps;
  const c = i.c, keys = KF[c.src], s0 = e === "l" ? i.in : i.out;
  return c.lane < 0 && keys && keys.length ? edge0 + nearKey(keys, s0 + raw - edge0) - s0 : keySnap(raw);
}
let extSide = "r";
function armExtend(side) { extSide = side; setTool("extend"); }
function shiftAllT(d) {                          // everything later by d: room at the start
  const S = st.S;
  for (const c of st.R.clips) c.start += d;
  if (S.outT) S.outT += d;
  S.cuts = S.cuts.map(([a, b]) => [a + d, b + d]); S.keys = S.keys.map(k => ({ ...k, t: k.t + d }));
}
function vOn(l, y) { return clamp((l.y + l.h - y) / l.h, 0, 1); }
function lanesBetween(y0, y1) {
  const L = lanes(), a = Math.min(y0, y1), b = Math.max(y0, y1);
  const ks = L.filter(l => l.y + l.h >= a && l.y <= b).map(l => l.k);
  return ks.length ? ks : L.map(l => l.k);
}
tl.addEventListener("mousedown", ev => {
  if (ev.button !== 0) return;
  closeMenus();
  if (tool === "extend") { remember(); drag = { k: "extend", side: extSide, x0: ev.offsetX, tail0: st.R.tail || 0, head: 0, perPx: (v1 - v0) / W() }; return; }
  const x = ev.offsetX, y = ev.offsetY, hh = hit(x, y), t = x2t(x), k = hh.k;
  if (k === "none") return;
  if (k !== "crange") clipSel = null;
  if (k === "hdr") { drag = { k: "vscroll", y0: y, s0: vscroll }; return; }
  if (k === "ph") { drag = { k: "ph" }; seek(snapT(t)); }
  else if (k === "ruler") { if (pro()) drag = { k: "rsel", x0: x, t0: snapT(t) }; else { drag = { k: "ph" }; seek(snapT(t)); } }
  else if (k === "fi" || k === "fo") {
    remember(); const F = hh.F;
    drag = { k, F, a: hh.a, b: hh.b, tag: hh.tag, c: hh.c, l: hh.l, bot: hh.bot, y0: y, s0: F[k + "s"], off: (k === "fi" ? hh.a + F.fi : hh.b - F.fo) - t };
  }
  else if (k === "fis" || k === "fos") { remember(); drag = { k, F: hh.F, a: hh.a, b: hh.b, l: hh.l, tag: hh.tag, bot: hh.bot }; }
  else if (k === "key" && ev.altKey) { remember(); hh.E.keys.splice(hh.i, 1); }
  else if (k === "key" && ev.ctrlKey) {
    remember(); const kk = hh.E.keys[hh.i];
    if (kk.s) kk.s = false; else { const nb = hh.E.keys[hh.i + 1] || hh.E.keys[hh.i - 1]; kk.s = true; kk.hx = nb ? Math.abs(nb.t - kk.t) / 3 : (v1 - v0) / 20; kk.hv = 0; }
  }
  else if (k === "key") { remember(); drag = { k: "key", E: hh.E, off: hh.off, l: hh.l, tag: hh.tag, i: hh.i, c: hh.c }; }
  else if (k === "hnd") { remember(); drag = { k: "hnd", E: hh.E, off: hh.off, l: hh.l, tag: hh.tag, i: hh.i, sgn: hh.sgn }; }
  else if (k === "line" && ev.ctrlKey) {
    remember(); const E = hh.E, nk = { t: snapT(t) - hh.off, v: envV(E, t - hh.off), s: false, hx: 0, hv: 0 };
    E.keys.push(nk); E.keys.sort((a, b) => a.t - b.t); drag = { k: "key", E, off: hh.off, l: hh.l, tag: hh.tag, i: E.keys.indexOf(nk), c: hh.c };
  }
  else if (k === "line") {
    remember(); const E = hh.E; let i = 0; while (i < E.keys.length && E.keys[i].t <= t - hh.off) i++;
    drag = { k: "line", E, off: hh.off, l: hh.l, tag: hh.tag, t, y0: y, base: E.keys.length ? null : E.level, idx: [i - 1, i].filter(j => j >= 0 && j < E.keys.length), vs: E.keys.map(q => q.v) };
  }
  else if (k === "in" || k === "out") { remember(); drag = { k }; }
  else if (k === "joint" || k === "trans") {
    remember(); const c = hh.c; if (k === "joint") c.xo = 1 / fpsOr30();
    drag = { k: "trans", c, x0: x, side: x < t2x(clipEnd(c)) ? -1 : 1, px0: Math.max(5, t2x(clipEnd(c) + c.xo / 2) - t2x(clipEnd(c))) };
  }
  else if (k === "razor") { const tt = snapT(t); ph = tt; splitAt(tt, ev.shiftKey || !hh.c ? null : [hh.c]); setTool("select"); }       // one cut, then the usual cursor
  else if (k === "crange") { csel.clear(); csel.add(hh.c.id); clipSel = { id: hh.c.id, a: snapT(t), b: snapT(t) }; drag = { k: "crange", c: hh.c, x0: x }; }
  else if ((k === "clip" || k === "edge") && !ev.ctrlKey) {
    const c = hh.c; sel = null; selLanes = null;
    if (ev.shiftKey) { csel.has(c.id) ? csel.delete(c.id) : csel.add(c.id); }
    else if (!csel.has(c.id)) { csel.clear(); csel.add(c.id); }             // one click = this piece only
    remember();
    if (k === "edge") {
      const e = hh.e, edge0 = e === "l" ? c.start : clipEnd(c);
      const items = st.R.clips.filter(q => csel.has(q.id) && Math.abs((e === "l" ? q.start : clipEnd(q)) - edge0) < 1e-6).map(q => {
        const o = st.R.clips.filter(p => p !== q && p.lane === q.lane), nb = ev.altKey ? (e === "l" ? prevAdj(q) : nextAdj(q)) || null : null;   // Alt: the whole join moves
        return { c: q, start: q.start, in: q.in, out: q.out, keys: cp(q.vol.keys), nb, n0: nb && { start: nb.start, in: nb.in, out: nb.out, keys: cp(nb.vol.keys) },
          lo: Math.max(0, ...o.filter(p => clipEnd(p) <= q.start + 1e-4).map(clipEnd)), hi: Math.min(Infinity, ...o.filter(p => p.start >= clipEnd(q) - 1e-4).map(p => p.start)) };
      });
      drag = { k: "edge", e, items, edge0, off: edge0 - t, x0: x, joint: hh.joint };
    }
    else {
      let items = st.R.clips.filter(q => csel.has(q.id));
      if (ev.altKey) { const gm = new Map(); items = items.map(q => { if (!gm.has(q.g)) gm.set(q.g, nextId++); const d = { ...cp(q), id: nextId++, g: gm.get(q.g) }; st.R.clips.push(d); return d; }); csel = new Set(items.map(q => q.id)); }
      drag = { k: "move", items: items.map(q => ({ c: q, start: q.start, lane: q.lane })), t0: t, y0: y };
    }
  }
  else {                                         // empty space (or Ctrl on a piece): a range on the rows under the mouse
    if (pro() && !ev.shiftKey) csel.clear();
    drag = { k: "sel", x0: x, y0: y, t0: snapT(t) };
  }
  fields();
});
window.addEventListener("mousemove", ev => {
  const r = tl.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
  if (!drag) {
    const inside = x >= 0 && y >= 0 && x <= r.width && y <= r.height, hh = inside ? hit(x, y) : null;
    const hk = !hh ? null : hh.k === "key" ? `key${hh.tag}:${hh.i}` : ["fi", "fo", "fis", "fos"].includes(hh.k) ? hh.tag + hh.k
      : hh.k === "hdr" ? "hdr" + hh.l : hh.k === "joint" || hh.k === "trans" ? "j" + hh.c.id : hh.k;
    if (hk !== hover) { hover = hk; dirty = true; }
    const k = hh && hh.k;
    if (tool === "extend") { tl.style.cursor = "col-resize"; return; }
    tl.style.cursor = k === "edge" && ev.altKey ? "col-resize" : ["in", "out", "edge", "trans"].includes(k) ? "ew-resize" : k === "fi" || k === "fo" ? "move" : k === "fis" || k === "fos" ? "ns-resize" : k === "ph" || k === "none" ? "default"
      : k === "ruler" ? (pro() ? "text" : "pointer") : k === "hdr" ? "ns-resize" : k === "key" || k === "hnd" ? "move" : k === "line" ? (ev.ctrlKey ? "copy" : "ns-resize")
      : k === "joint" ? "copy" : k === "razor" ? "crosshair" : k === "crange" ? "text" : k === "clip" ? (ev.altKey ? "copy" : ev.ctrlKey ? "text" : "grab") : "text";
    return;
  }
  const t = snapT(x2t(x)), S = st.S;
  if (drag.k === "extend") {
    const d = (x - drag.x0) * drag.perPx;
    if (drag.side === "r") st.R.tail = Math.max(0, drag.tail0 + d);
    else { const want = Math.max(0, -d); shiftAllT(want - drag.head); drag.head = want; }
    fields(); v0 = 0; v1 = dur;
  }
  else if (drag.k === "vscroll") { vscroll = drag.s0 - (y - drag.y0); clampScroll(); }
  else if (drag.k === "ph") seek(t);
  else if (drag.k === "rsel" && (drag.moved || Math.abs(x - drag.x0) > 3)) { drag.moved = true; sel = [drag.t0, t]; selLanes = null; csel.clear(); }
  else if (drag.k === "in") { S.inT = Math.min(t, S.outT); clampFades(); fields(); }
  else if (drag.k === "out") { S.outT = Math.max(t, S.inT); S.atEnd = Math.abs(S.outT - dur) < 1e-4; clampFades(); fields(); }
  else if (drag.k === "fi" || drag.k === "fo") {               // sideways = the length, up / down = the curve (it follows the mouse)
    const Fo = drag.F, a = drag.c ? drag.c.start : drag.a, b = drag.c ? clipEnd(drag.c) : drag.b, tt = x2t(x) + drag.off;
    if (drag.k === "fi") Fo.fi = clamp(tt - a, 0, b - a - Fo.fo); else Fo.fo = clamp(b - tt, 0, b - a - Fo.fi);
    const dy = y - drag.y0, far = Math.abs(dy) - 4;
    Fo[drag.k + "s"] = far > 0 ? clamp(drag.s0 + (drag.bot ? 1 : -1) * Math.sign(dy) * far / (Math.max(50, drag.l.h) / 2), -1, 1) : drag.s0;
    fields();
  }
  else if (drag.k === "fis" || drag.k === "fos") {          // the middle dot follows the mouse: the curve through it
    const g = clamp((drag.bot ? y - drag.l.y : drag.l.y + drag.l.h - y) / drag.l.h, .02, .98);
    drag.F[drag.k] = shapeFor(g); buttons();
  }
  else if (drag.k === "key") {
    const E = drag.E, k = E.keys[drag.i], lo = drag.i > 0 ? E.keys[drag.i - 1].t + 1e-3 : (drag.c ? 0 : 0), hi = drag.i < E.keys.length - 1 ? E.keys[drag.i + 1].t - 1e-3 : (drag.c ? drag.c.out - drag.c.in : dur);
    k.t = clamp(t - drag.off, lo, hi); k.v = vOn(drag.l, y); buttons();
  }
  else if (drag.k === "hnd") { const k = drag.E.keys[drag.i]; k.hx = Math.max(0, drag.sgn * (x2t(x) - drag.off - k.t)); k.hv = drag.sgn * (vOn(drag.l, y) - k.v); buttons(); }
  else if (drag.k === "line") {
    const E = drag.E, dv = (drag.y0 - y) / drag.l.h;
    if (drag.base !== null) E.level = clamp(drag.base + dv, 0, 1); else for (const j of drag.idx) E.keys[j].v = clamp(drag.vs[j] + dv, 0, 1);
    buttons();
  }
  else if (drag.k === "trans") {                 // at the very join it goes away; a stretch of 1 frame around the smallest size, then it grows
    const c = drag.c, j = clipEnd(c), n = nextAdj(c), F = 1 / fpsOr30(), big = n ? 2 * Math.min(c.out - c.in, n.out - n.in) : .01;
    const px = Math.max(0, drag.px0 + drag.side * (x - drag.x0)), pxF = t2x(j + F / 2) - t2x(j), stick = Math.max(14, pxF + 6);
    c.xo = px < 2 ? 0 : px <= stick ? F : clamp(F + 2 * (px - stick) / W() * (v1 - v0), F, big);
    buttons();
  }
  else if (drag.k === "crange") { clipSel.b = clamp(t, drag.c.start, clipEnd(drag.c)); clipSel.a = clamp(clipSel.a, drag.c.start, clipEnd(drag.c)); }
  else if (drag.k === "move") {
    const skip = new Set(drag.items.map(i => i.c.id));
    let d = x2t(x) - drag.t0; d = Math.max(d, -Math.min(...drag.items.map(i => i.start)));
    if (fps && phMode() !== "precise") d = Math.round(d * fps) / fps;        // whole frames: pieces line up exactly
    const lead = drag.items.reduce((a, i) => i.start < a.start ? i : a, drag.items[0]), len = lead.c.out - lead.c.in;
    const s1 = snapEdges(lead.start + d, skip), e1 = snapEdges(lead.start + d + len, skip);
    if (s1 !== lead.start + d) d = s1 - lead.start; else if (e1 !== lead.start + d + len) d = e1 - lead.start - len;
    const allA = drag.items.every(i => i.lane >= 0), allV = drag.items.every(i => i.lane < 0);
    const L = lanes(), R = st.R;
    let dl = 0;
    if (allA || allV) {                          // to another track of the same kind, or a new one past the last
      const same = L.filter(l => allA ? l.k >= 0 : l.k < 0), from = same.findIndex(l => l.k === drag.items[0].lane);
      let to = same.findIndex(l => y >= l.y && y < l.y + l.h);
      if (to < 0) to = allA ? (y >= same[same.length - 1].y + same[same.length - 1].h ? same.length : from) : (y < same[0].y ? -1 : from);
      dl = to - from;
    }
    for (const i of drag.items) {
      i.c.start = Math.max(0, i.start + d);
      if (allA) { const nl = Math.max(0, i.lane + dl); while (R.lanes.length <= nl) R.lanes.push({ fx: null }); i.c.lane = nl; }
      if (allV) { const idx = -i.lane - 1 - dl; const nl = -(Math.max(0, idx) + 1); while (R.nv < -nl) R.nv++; i.c.lane = nl; }
    }
    fields();
  }
  else if (drag.k === "edge") {
    if (Math.abs(x - drag.x0) > 2) drag.moved = true;
    if (drag.moved) {
      const I = drag.items, skip = new Set(); for (const i of I) { skip.add(i.c.id); if (i.nb) skip.add(i.nb.id); }
      const raw = x2t(x) + drag.off, near = snapEdges(raw, skip), d = (near !== raw ? near : edgeSnap(raw, I[0], drag.e, drag.edge0)) - drag.edge0;
      for (const i of I) {
        const c = i.c, len = i.out - i.in, nb = i.nb, n = i.n0, MIN = .02;
        if (drag.e === "l") {                      // it stops at the neighbour; with Alt the neighbour's end follows
          const dd = nb ? clamp(d, Math.max(-i.in, MIN - (n.out - n.in)), Math.min(len - MIN, SRC[nb.src].duration - n.out)) : clamp(d, Math.max(-i.in, i.lo - i.start), len - MIN);
          c.start = i.start + dd; c.in = i.in + dd; c.vol.keys = i.keys.map(k => ({ ...k, t: k.t - dd }));
          if (nb) nb.out = n.out + dd;
        } else {
          const room = SRC[c.src].duration - i.out, dd = nb ? clamp(d, Math.max(MIN - len, -n.in), Math.min(room, n.out - n.in - MIN)) : clamp(d, MIN - len, Math.min(room, i.hi - i.start - len));
          c.out = i.out + dd;
          if (nb) { nb.start = n.start + dd; nb.in = n.in + dd; nb.vol.keys = n.keys.map(k => ({ ...k, t: k.t - dd })); }
        }
        for (const q of nb ? [c, nb] : [c]) { const l2 = q.out - q.in; q.fi = Math.min(q.fi || 0, l2); q.fo = Math.min(q.fo || 0, l2 - q.fi); }
      }
      fields();
    }
  }
  else if (drag.k === "sel" && (drag.moved || Math.abs(x - drag.x0) > 3)) { drag.moved = true; sel = [drag.t0, t]; selLanes = pro() ? lanesBetween(drag.y0, y) : null; }
  if (drag.k !== "ph") dirty = true;
});
window.addEventListener("mouseup", () => {
  if (!drag) return;
  if (drag.k === "sel" || drag.k === "rsel") { if (!drag.moved) { sel = null; selLanes = null; seek(drag.t0); } else if (Math.abs(sel[1] - sel[0]) < 1e-4) { sel = null; selLanes = null; } }
  if (drag.k === "crange" && clipSel && Math.abs(clipSel.a - clipSel.b) < 1e-4) { clipSel = null; seek(drag.c.start + Math.max(0, x2t(drag.x0) - drag.c.start)); }
  if (drag.k === "move") { overwrite(drag.items.map(i => i.c)); dropEmptyLanes(); }
  if (drag.k === "edge" && drag.joint && !drag.moved) drag.joint.xo = 1 / fpsOr30();         // a click on the join: a transition of 1 frame
  if (drag.k === "move" || drag.k === "edge") for (const c of st.R.clips) if (c.xo && !nextAdj(c)) c.xo = 0;      // pulled apart: no join any more
  if (!["sel", "rsel", "ph", "vscroll", "crange"].includes(drag.k) && undoS.length && undoS[undoS.length - 1] === snapshot()) undoS.pop();
  if (drag.k === "extend") { setTool("select"); v0 = 0; v1 = dur; }
  drag = null; fields();
});
tl.addEventListener("wheel", ev => {
  ev.preventDefault();
  const dy = ev.deltaY || ev.deltaX, span = v1 - v0;
  if (pro() && ev.offsetX < X0() - 4) {                          // on the track names
    const l = laneAt(ev.offsetY);
    if (ev.altKey && l) { const hs = st.R.hs; hs[l.k] = clamp((hs[l.k] || 1) * (dy < 0 ? 1.15 : 1 / 1.15), .4, 6); }
    else vscroll += dy;
    clampScroll(); dirty = true; return;
  }
  if (pro()) {                                   // Premiere: wheel = along the time, Alt = zoom, Ctrl = up / down the tracks, Shift = wave height
    if (ev.shiftKey) waveZoom = clamp(waveZoom * (dy < 0 ? 1.25 : .8), .25, 32);
    else if (ev.ctrlKey) { vscroll += dy; clampScroll(); }
    else if (ev.altKey) { const t = x2t(ev.offsetX), k = dy < 0 ? .8 : 1.25, ns = Math.max(Math.min(span * k, dur), Math.min(dur, .02)); v0 = t - (t - v0) * ns / span; v1 = v0 + ns; }
    else { const d = dy / W() * span * 1.5; v0 += d; v1 += d; }
  } else {
    if (ev.ctrlKey) waveZoom = clamp(waveZoom * (dy < 0 ? 1.25 : .8), .25, 32);
    else if (ev.shiftKey || Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) { const d = dy / W() * span; v0 += d; v1 += d; }
    else { const t = x2t(ev.offsetX), k = dy < 0 ? .8 : 1.25, ns = Math.max(Math.min(span * k, dur), Math.min(dur, .02)); v0 = t - (t - v0) * ns / span; v1 = v0 + ns; }
  }
  clampView(); dirty = true;
}, { passive: false });
let odrag = null;
function overT(ev) { const r = ov.getBoundingClientRect(); return (ev.clientX - r.left) / r.width * dur; }
function overTo(ev) { const s = v1 - v0; v0 = overT(ev) - odrag.off; v1 = v0 + s; clampView(); dirty = true; }
$("over").addEventListener("mousedown", ev => {
  if (ev.target.tagName === "INPUT") return;
  const t = overT(ev), s = v1 - v0; odrag = { off: t >= v0 && t <= v1 ? t - v0 : s / 2 }; overTo(ev);   // outside the view: it comes here
});
window.addEventListener("mousemove", ev => { if (odrag) overTo(ev); });
window.addEventListener("mouseup", () => odrag = null);
$("del").addEventListener("mousedown", ev => ev.stopPropagation());
$("del").onclick = deleteSel;
