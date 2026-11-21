// Buttons, keys, the frame loop and the start.

function setCanvas() { const fv = firstV(); if (fv) { CW = fv.w; CH = fv.h; } }

// ---------- controls
for (const id of ["st", "en"]) {
  $(id).addEventListener("change", () => {
    const v = parse($(id).value), S = st.S;
    if (v !== null) { remember(); if (id === "st") S.inT = clamp(snapT(v), 0, S.outT); else { S.outT = clamp(snapT(v), S.inT, dur); S.atEnd = Math.abs(S.outT - dur) < 1e-4; } }
    fields(); $(id).blur();
  });
  $(id).addEventListener("keydown", ev => { if (ev.key === "Enter") ev.target.blur(); ev.stopPropagation(); });
}
function nudge(dir, n = 1) {                      // to the next place the playhead may stand: keyframe, frame; Precise moves by the length of a frame
  const m = phMode();
  if (m === "fast") {
    const list = keyTimes(); let t = ph;
    for (let i = 0; i < n; i++) { const q = dir > 0 ? list.find(k => k > t + 1e-4) : list.findLast(k => k < t - 1e-4); if (q === undefined) break; t = q; }
    return seek(t);
  }
  seek(snapT(clamp(ph + dir * n * step(), 0, dur)));
}
function setTool(t) { tool = t; buttons(); dirty = true; }
$("play").onclick = play;
$("prev").onclick = () => nudge(-1);
$("next").onclick = () => nudge(1);
$("undo").onclick = undo; $("redo").onclick = redo;
$("razor").onclick = () => setTool(tool === "razor" ? "select" : "razor");
$("mix1").onclick = () => { remember(); st.G.one = !st.G.one; buttons(); };
$("trash").onclick = deleteSel;
function setMode(m) {
  if (st.mode === m || kind === "photo") return;
  stop(); st.mode = m; csel.clear(); sel = null; selLanes = null; clipSel = null; vscroll = 0; setTool("select");
  applyMode(); fields(); layoutAll();
}
function applyMode() {
  document.body.classList.toggle("pro", pro());
  for (const b of $("modesw").children) b.classList.toggle("on", b.dataset.m === st.mode);
}
for (const b of $("modesw").children) b.onclick = () => setMode(b.dataset.m);
function setLoop(on) { loop = on; $("loop").classList.toggle("on", loop); }
function setPMode(m) { pmode = m; for (const b of $("pmode").children) b.classList.toggle("on", b.dataset.m === m); seek(snapT(ph)); dirty = true; }
function setPQ(q) { pvq = q; for (const b of $("pq").children) b.classList.toggle("on", +b.dataset.q === q); glDirty = true; }
for (const b of $("pmode").children) b.onclick = () => setPMode(b.dataset.m);
for (const b of $("pq").children) b.onclick = () => setPQ(+b.dataset.q);
$("loop").onclick = () => setLoop(!loop);
$("fit").onclick = () => { v0 = 0; v1 = dur; dirty = true; };
window.__emit = evs => { for (const e of evs) if (window.SaturniDebug) SaturniDebug.handle(e.type, e.data); };
window.addEventListener("keydown", ev => {
  if (window.SaturniDebug && (SaturniDebug.owns(ev) || SaturniDebug.active)) return;     // the debug layer has the keys
  if ($("veil").style.display === "block") { if (ev.key === "Escape") closeCards(); return; }
  const el = ev.target, typing = el.tagName === "SELECT" || el.tagName === "INPUT" && el.type !== "range" && el.type !== "checkbox";
  if (typing) return;
  const k = ev.code.startsWith("Key") ? ev.code.slice(3).toLowerCase() : ev.key.toLowerCase();    // by the key's place: the same on any keyboard layout
  if (ev.ctrlKey && k === "z" && !ev.shiftKey) { ev.preventDefault(); undo(); }
  else if (ev.ctrlKey && (k === "y" || k === "z" && ev.shiftKey)) { ev.preventDefault(); redo(); }
  else if (ev.ctrlKey && ev.shiftKey && k === "s") { ev.preventDefault(); if (kind !== "photo") saveProject(false); }
  else if (ev.ctrlKey && k === "s") { ev.preventDefault(); if (!$("save").disabled) $("save").click(); }
  else if (el.tagName === "INPUT") return;       // a focused slider keeps its arrows
  else if (kind === "photo") { if (ev.key === "Escape") pywebview.api.close(); }
  else if (ev.code === "Space") { ev.preventDefault(); play(); }
  else if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") { ev.preventDefault(); nudge(ev.key === "ArrowLeft" ? -1 : 1, ev.shiftKey ? 10 : 1); }
  else if (pro() && ev.shiftKey && ev.key === "Delete" && csel.size) rippleDelete();
  else if (ev.key === "Delete" || ev.key === "Backspace") deleteSel();
  else if (pro() && ev.ctrlKey && k === "c") { ev.preventDefault(); copyClips(); }
  else if (pro() && ev.ctrlKey && k === "x") { ev.preventDefault(); cutClips(); }
  else if (pro() && ev.ctrlKey && k === "v") { ev.preventDefault(); pasteClips(ph); }
  else if (pro() && ev.ctrlKey && k === "d") { ev.preventDefault(); duplicateClips(); }
  else if (pro() && ev.ctrlKey && k === "a") { ev.preventDefault(); selectAllClips(); }
  else if (pro() && (k === "s" || ev.ctrlKey && k === "k")) { ev.preventDefault(); const t = snapT(ph); ph = t; splitAt(t); }
  else if (k === "c") setTool("razor");
  else if (k === "v") setTool("select");
  else if (k === "i") { remember(); st.S.inT = Math.min(snapT(ph), st.S.outT); clampFades(); fields(); }
  else if (k === "o") { remember(); st.S.outT = Math.max(snapT(ph), st.S.inT); st.S.atEnd = Math.abs(st.S.outT - dur) < 1e-4; clampFades(); fields(); }
  else if (ev.key === "Home") seek(st.S.inT);
  else if (ev.key === "End") seek(st.S.outT);
  else if (k === "l") setLoop(!loop);
  else if (k === "f") $("fit").click();
  else if (ev.key === "Escape") { if (sel || csel.size || clipSel || tool !== "select") { sel = null; selLanes = null; clipSel = null; csel.clear(); setTool("select"); dirty = true; } else pywebview.api.close(); }
});
window.addEventListener("resize", () => layoutAll());
let meterLive = false;
(function frame() {
  if (st && kind === "photo" && glDirty) renderGL($("pic"));
  if (st && kind !== "photo") {
    tick(); sync(ph); applyLook(); growDrop();
    if (hasV()) renderGL(shownEl);
    if (dirty) { draw(); dirty = false; phDirty = false; } else if (phDirty) { drawHead(); phDirty = false; }
    if (NA() && (playing || meterLive)) meterLive = drawMeter();
  }
  requestAnimationFrame(frame);
})();

// ---------- start
async function loadWaves(i) {
  const s = SRC[i], w = { sr: [], per: [] }; WV[i] = w;
  if (s.video) py("keyframes", i).then(k => { KF[i] = k.sort((a, b) => a - b); seek(snapT(ph)); dirty = true; });
  for (let n = 0; n < s.audios.length; n++) {
    const ab = await (await fetch(`/src/${i}/wave/${n}`)).arrayBuffer(), rate = wavRate(ab);
    if (ab.byteLength > 44) { const buf = await new OfflineAudioContext(1, 1, rate).decodeAudioData(ab); w.per[n] = buf.getChannelData(0); w.sr[n] = buf.sampleRate; }
    overPeaks = null; dirty = true;
  }
}
function wavRate(ab) {                           // the sample rate from the WAV header ("fmt " chunk)
  const d = new DataView(ab);
  for (let p = 12; p + 8 <= ab.byteLength; p += 8 + d.getUint32(p + 4, true))
    if (d.getUint32(p, false) === 0x666d7420) return d.getUint32(p + 12, true);
  return 48000;
}
(async () => {
  const info = await (await fetch("/load")).json();
  SRC = info.sources; C = { ...info.colors }; O = { ...info.options };
  loadLayout(info.state || {});
  DEF = { colors: info.defColors, options: info.defOptions, names: info.colorNames };
  kind = SRC[0].kind;
  st = { nsrc: 1, mode: "simple", S: { inT: 0, outT: 0, atEnd: true, cuts: [], keys: [], level: .5, fi: 0, fo: 0, fis: 0, fos: 0, V: { fi: 0, fo: 0, fis: 0, fos: 0 } },
         R: { clips: [], nv: 0, lanes: [], hs: {} }, G: { crop: null, adj: cp(ADJ0), aud: cp(AUD0), out: { fps: 0, mbps: 0 }, one: false } };
  G0 = JSON.stringify(st.G);
  applyColors(); document.title = "Saturni · Editor"; document.body.classList.add(kind);
  if (window.SaturniDebug) SaturniDebug.init({ api: (n, ...a) => py(n, ...a), app: "Saturni · Editor",
    context: () => SRC.length ? SRC[0].name + (st && st.mode === "pro" ? " · Advanced" : "") : "", gear: "#setb" });
  if (kind === "photo") { CW = SRC[0].w; CH = SRC[0].h; const p = $("pic"); p.style.display = "block"; p.onload = () => glDirty = true; p.src = "/src/0/media"; buildRatios(); fields(); layoutAll(); buildAdjust(); return; }
  const s0 = SRC[0];
  st.R.nv = s0.video ? 1 : 0; st.R.lanes = s0.audios.map(() => ({ fx: null })); st.R.clips = clipsFor(s0, 0);
  recalc(); st.S.outT = dur; BASE = core();
  setCanvas(); if (hasV()) buildRatios();
  buildAdjust(); setLoop(!!O.loop); setPMode(O.playMode || "fast"); setPQ(O.preview || 1);
  fields(); v0 = 0; v1 = dur; layoutAll();
  if (info.project) restoreProject(info.project);
  await loadWaves(0); meterLive = true;
})();
