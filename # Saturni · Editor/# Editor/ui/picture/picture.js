// Picture: fit, zoom, crop, aspect ratios.

// ---------- picture: fit, zoom, crop, drag = move in time
let FXW = 300;                                   // the Effects panel's width in the right column
let vr = { x: 0, y: 0, w: 1, h: 1 }, zv = 1, panX = 0, panY = 0, CW = 0, CH = 0;   // CW x CH: the picture's size
function hasPic() { return kind === "photo" || hasV(); }
function layoutAll() {
  const stg = $("stage"), ovr = $("over"), root = document.documentElement.style;
  const x0 = X0(), w = W(), xr = PAD + 1 + 30;       // right: the timeline's own padding + the meter column
  ovr.style.marginLeft = x0 + "px"; ovr.style.width = w + "px"; ovr.style.background = hexA(C.overviewBg, .28);
  root.setProperty("--xr", (kind === "photo" ? 0 : xr) + "px"); root.setProperty("--tl0", x0 + "px");
  if (hasPic()) {
    const body = document.body, cs = getComputedStyle(body), gap = 8;
    const fixed = $("top").offsetHeight + document.querySelector(".row").offsetHeight + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    let aw, left, avail;
    if (kind === "photo") { aw = body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight); left = 0; avail = innerHeight - fixed - gap * 2; }
    else { aw = w; left = x0; avail = innerHeight - fixed - 200 - 20 - gap * 4; }   // the same in Simple and Advanced: the picture stays put
    const fx = document.body.classList.contains("fx"), rightEdge = body.clientWidth - parseFloat(cs.paddingRight);
    if (fx) aw = Math.min(aw, rightEdge - FXW - gap - left - (kind === "photo" ? parseFloat(cs.paddingLeft) : 0));
    if (kind !== "photo" && LAYOUT.picH) avail = Math.min(LAYOUT.picH, innerHeight - fixed - 110 - 20 - gap * 4);   // dragged: the timeline may get down to 110 px
    const h = Math.max(80, Math.min(aw * 9 / 16, avail)), pw = h * 16 / 9, ml = kind === "photo" ? (aw - pw) / 2 : left;
    Object.assign(stg.style, { width: pw + "px", height: h + "px", marginLeft: ml + "px" });
    root.setProperty("--x0", ml + "px");
    const ac = $("addcol"), sr = stg.getBoundingClientRect(), br = body.getBoundingClientRect(), mr = $("meter").getBoundingClientRect();
    Object.assign(ac.style, { left: (mr.left - br.left) + "px", top: (sr.top - br.top) + "px", width: mr.width + "px", height: h + "px" });   // the "+" and the meter: one column
    if (fx) Object.assign($("adjust").style, { left: (rightEdge - FXW) + "px", top: sr.top + "px", width: FXW + "px", height: h + "px", right: "auto", maxHeight: "none" });
  } else root.setProperty("--x0", x0 + "px");
  layoutPic(); overPeaks = null; dirty = true; meterLive = true; fadeStrip($("info")); placeGutters();
}
function placeEl(el) { Object.assign(el.style, { left: vr.x + "px", top: vr.y + "px", width: vr.w + "px", height: vr.h + "px" }); }
function layoutPic() {
  if (!hasPic() || !CW) return;
  const sw = $("stage").clientWidth, sh = $("stage").clientHeight, a = CW / CH;
  let w = sw, h = sw / a; if (h > sh) { h = sh; w = sh * a; }
  w *= zv; h *= zv;
  vr = { x: (sw - w) / 2 + panX, y: (sh - h) / 2 + panY, w, h };
  for (const el of $("view").children) placeEl(el);
  placeEl($("black"));
  cropShow(); glDirty = true;
}
function cr() { return st.G.crop || { x: 0, y: 0, w: CW, h: CH }; }
let cropHot = false;
function cropShow() {
  if (!hasPic() || !CW) return;
  const c = cr(), k = vr.w / CW, el = $("crop");
  Object.assign(el.style, { left: vr.x + c.x * k + "px", top: vr.y + c.y * k + "px", width: c.w * k + "px", height: c.h * k + "px" });
  const ev2 = v => kind !== "photo" ? Math.round(v / 2) * 2 : Math.round(v);
  $("vsize").textContent = (st.G.crop ? `${ev2(c.w)} × ${ev2(c.h)}  of ${CW} × ${CH}` : `${CW} × ${CH}`) + (zv > 1.001 ? `  ·  ${Math.round(zv * 100)}%` : "");
  $("vsize").style.display = st.G.crop || cropHot || cdrag && cdrag.h !== "click" && cdrag.h !== "pan" && cdrag.h !== "scrub" ? "block" : "none";
}
function setCrop(c) {
  c = { x: Math.round(c.x), y: Math.round(c.y), w: Math.round(c.w), h: Math.round(c.h) };
  st.G.crop = c.x <= 0 && c.y <= 0 && c.w >= CW && c.h >= CH ? null : c;
  cropShow(); buttons(); glDirty = true;
}
const RATIOS = [["Free", null], ["Original", "orig"], ["1:1", 1], ["16:9", 16 / 9], ["9:16", 9 / 16], ["4:3", 4 / 3], ["3:4", 3 / 4], ["4:5", 4 / 5], ["5:4", 5 / 4], ["3:2", 3 / 2], ["2:3", 2 / 3], ["21:9", 21 / 9]];
let ratio = null, rdrag = null;
function fadeStrip(b) { b.classList.toggle("fl", b.scrollLeft > 2); b.classList.toggle("fr", b.scrollLeft < b.scrollWidth - b.clientWidth - 2); }
function fadeRatios() { fadeStrip($("ratios")); }
const RATIOS_MS = 5000;                          // the ratios under the picture: shown while cropping, gone 5 s after the last touch
let ratiosT = 0;
function showRatios() {
  const box = $("ratios"); if (!box.children.length) return;
  box.classList.add("show"); fadeRatios(); clearTimeout(ratiosT);
  ratiosT = setTimeout(function hide() { if (box.matches(":hover") || rdrag) ratiosT = setTimeout(hide, 600); else box.classList.remove("show"); }, RATIOS_MS);
}
let idrag = null;                                // the file name and its details: wider than the room, they fade; held and moved, they slide
$("info").addEventListener("wheel", ev => { ev.preventDefault(); $("info").scrollLeft += (ev.deltaY || ev.deltaX) * 1.2; }, { passive: false });
$("info").addEventListener("scroll", () => fadeStrip($("info")));
$("info").addEventListener("mousedown", ev => { idrag = { x: ev.clientX, s: $("info").scrollLeft }; });
window.addEventListener("mousemove", ev => { if (idrag) $("info").scrollLeft = idrag.s - (ev.clientX - idrag.x); });
window.addEventListener("mouseup", () => idrag = null);
function buildRatios() {
  const box = $("ratios"); if (box.children.length) return;
  for (const [n, r] of RATIOS) {
    const b = document.createElement("button"); b.textContent = n; b.dataset.n = n; if (n === "Free") b.classList.add("on");
    b.onclick = () => {
      if (rdrag && rdrag.moved) return;
      showRatios();
      for (const x of box.children) x.classList.toggle("on", x === b);
      if (r === null) { ratio = null; return; }
      ratio = r === "orig" ? CW / CH : r;
      remember();
      let w = CW, h = w / ratio; if (h > CH) { h = CH; w = h * ratio; }
      setCrop({ x: (CW - w) / 2, y: (CH - h) / 2, w, h });
    };
    box.appendChild(b);
  }
  box.addEventListener("wheel", ev => { ev.preventDefault(); box.scrollLeft += (ev.deltaY || ev.deltaX) * 1.2; fadeRatios(); }, { passive: false });
  box.addEventListener("scroll", fadeRatios);
  box.addEventListener("mousedown", ev => { ev.stopPropagation(); rdrag = { x: ev.clientX, s: box.scrollLeft, moved: false }; });
  window.addEventListener("mousemove", ev => { if (!rdrag) return; const d = ev.clientX - rdrag.x; if (Math.abs(d) > 3) rdrag.moved = true; box.scrollLeft = rdrag.s - d; });
  window.addEventListener("mouseup", () => { if (rdrag) setTimeout(() => rdrag = null, 0); });
  box.addEventListener("mouseenter", showRatios);
  box.classList.add("seg"); segLens(box); fadeRatios();
}
$("cropreset").onclick = () => { if (!st.G.crop) return; remember(); setCrop({ x: 0, y: 0, w: CW, h: CH }); };
$("zfit").onclick = () => { zv = 1; panX = panY = 0; layoutPic(); };
$("stage").addEventListener("wheel", ev => {
  ev.preventDefault();
  const r = $("stage").getBoundingClientRect(), mxp = ev.clientX - r.left - r.width / 2, myp = ev.clientY - r.top - r.height / 2;
  const nz = clamp(zv * ((ev.deltaY || ev.deltaX) < 0 ? 1.2 : 1 / 1.2), 1, 16), k = nz / zv;
  panX = mxp - (mxp - panX) * k; panY = myp - (myp - panY) * k;
  zv = nz; if (zv === 1) panX = panY = 0; layoutPic();
}, { passive: false });

let cdrag = null;
function stagePt(ev) { const r = $("stage").getBoundingClientRect(); return { x: (ev.clientX - r.left - vr.x) / vr.w * CW, y: (ev.clientY - r.top - vr.y) / vr.h * CH, sx: ev.clientX - r.left, sy: ev.clientY - r.top }; }
function cropHit(p) {
  const c = cr(), k = vr.w / CW, tol = 12 / k;
  const nx = p.x > c.x - tol && p.x < c.x + c.w + tol, ny = p.y > c.y - tol && p.y < c.y + c.h + tol;
  if (!nx || !ny) return null;
  const l = Math.abs(p.x - c.x) < tol, r = Math.abs(p.x - c.x - c.w) < tol, t = Math.abs(p.y - c.y) < tol, b = Math.abs(p.y - c.y - c.h) < tol;
  const s = (t ? "n" : b ? "s" : "") + (l ? "w" : r ? "e" : "");
  return s || (p.x > c.x && p.x < c.x + c.w && p.y > c.y && p.y < c.y + c.h ? "move" : null);
}
const CUR = { n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize", ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize" };
$("stage").addEventListener("mousemove", ev => {
  if (cdrag || !CW) return;
  const h = cropHit(stagePt(ev)), edge = !!(h && h !== "move");
  if (edge !== cropHot) { cropHot = edge; $("crop").classList.toggle("hot", edge); cropShow(); }
  $("stage").style.cursor = edge ? CUR[h] : h === "move" && st.G.crop ? "move" : zv > 1 ? "grab" : kind === "photo" ? "default" : "ew-resize";
});
$("stage").addEventListener("mouseleave", () => { if (!cdrag) { cropHot = false; $("crop").classList.remove("hot"); cropShow(); } });
$("stage").addEventListener("mousedown", ev => {
  if (ev.button > 1 || !CW) return;
  const p = stagePt(ev); let h = cropHit(p);
  if (ev.button === 1 || zv > 1 && (!h || h === "move" && !st.G.crop)) h = "pan";          // zoomed in: move the view
  else if (!h || h === "move" && !st.G.crop) h = kind === "photo" ? "click" : "scrub";      // not zoomed: drag = move through the video
  cdrag = { h, p0: p, c0: { ...cr() }, before: snapshot(), moved: false, px: panX, py: panY, t0: ph };
  if (h !== "pan" && h !== "click" && h !== "scrub") showRatios();
  if (ev.button === 1) ev.preventDefault();
});
window.addEventListener("mousemove", ev => {
  if (!cdrag) return;
  const p = stagePt(ev), d = cdrag;
  if (!d.moved && Math.hypot(p.sx - d.p0.sx, p.sy - d.p0.sy) < 3) return;
  d.moved = true;
  if (d.h === "click") return;
  if (d.h === "scrub") { seek(snapT(clamp(d.t0 + (p.sx - d.p0.sx) / $("stage").clientWidth * (v1 - v0), 0, dur))); return; }
  if (d.h === "pan") { panX = d.px + p.sx - d.p0.sx; panY = d.py + p.sy - d.p0.sy; layoutPic(); return; }
  const c0 = d.c0, MIN = 16;
  if (d.h === "move") { if (!st.G.crop) return; setCrop({ ...c0, x: clamp(c0.x + p.x - d.p0.x, 0, CW - c0.w), y: clamp(c0.y + p.y - d.p0.y, 0, CH - c0.h) }); return; }
  let L = c0.x, T = c0.y, R = c0.x + c0.w, B = c0.y + c0.h;
  const hn = d.h.includes("n"), hs = d.h.includes("s"), hw = d.h.includes("w"), he = d.h.includes("e");
  if (hw) L = clamp(p.x, 0, R - MIN); if (he) R = clamp(p.x, L + MIN, CW);
  if (hn) T = clamp(p.y, 0, B - MIN); if (hs) B = clamp(p.y, T + MIN, CH);
  if (ratio) {
    let w = R - L, h = B - T;
    if ((hw || he) && (hn || hs)) {
      const ax = hw ? c0.x + c0.w : c0.x, ay = hn ? c0.y + c0.h : c0.y;
      w = Math.max(w, h * ratio); w = Math.min(w, (hw ? ax : CW - ax), (hn ? ay : CH - ay) * ratio); h = w / ratio;
      L = hw ? ax - w : ax; T = hn ? ay - h : ay;
    } else if (hw || he) {
      const cy = c0.y + c0.h / 2; w = Math.min(w, CH * ratio); h = w / ratio;
      const ax = hw ? c0.x + c0.w : c0.x; w = Math.min(w, hw ? ax : CW - ax); h = w / ratio;
      L = hw ? ax - w : ax; T = clamp(cy - h / 2, 0, CH - h);
    } else {
      const cxm = c0.x + c0.w / 2; h = Math.min(h, CW / ratio); w = h * ratio;
      const ay = hn ? c0.y + c0.h : c0.y; h = Math.min(h, hn ? ay : CH - ay); w = h * ratio;
      T = hn ? ay - h : ay; L = clamp(cxm - w / 2, 0, CW - w);
    }
    R = L + w; B = T + h;
  }
  setCrop({ x: L, y: T, w: R - L, h: B - T });
});
window.addEventListener("mouseup", () => {
  if (!cdrag) return;
  const d = cdrag; cdrag = null; cropHot = false; $("crop").classList.remove("hot"); cropShow();
  if (d.h === "pan") return;
  if (!d.moved && (d.h === "scrub" || d.h === "click")) { play(); return; }       // a click on the picture: play / pause
  if (d.h === "scrub" || d.h === "click") return;
  if (d.moved && d.before !== snapshot()) { undoS.push(d.before); redoS = []; buttons(); }
});
