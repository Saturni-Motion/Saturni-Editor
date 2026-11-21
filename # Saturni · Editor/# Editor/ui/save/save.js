// Saving, Save as new, adding files.

// ---------- saving: everything goes out on the output's own time line
let saving = false;
let sayT = 0;
function say(t, err) {                           // fades in, stays a moment, fades out
  const m = $("msg"); clearTimeout(sayT); m.className = (err ? "err " : "") + (t ? "show" : "");
  if (t) { m.textContent = t; sayT = setTimeout(() => m.classList.remove("show"), err ? 6000 : 2800); }
}
function exportPlan() {
  const R = st.R, S = st.S, fv = firstV();
  const plan = { nsrc: st.nsrc, crop: st.G.crop, adj: st.G.adj, aud: st.G.aud, out: st.G.out, canvas: fv ? { w: fv.w, h: fv.h, fps: fv.fps } : null, nOut: st.G.one ? 1 : NA(), fast: phMode() === "fast" };
  const map = []; let pos = 0; for (const [a, b] of segs()) { map.push([a, b, pos]); pos += b - a; }
  plan.T = pos;
  const outT = t => { for (const [a, b, o] of map) if (t >= a - 1e-9 && t <= b + 1e-9) return o + t - a; return null; };
  const pieces = (c, withEnv) => {
    const res = [];
    for (const [a, b, o] of map) {
      const lo = Math.max(a, c.start), hi = Math.min(b, clipEnd(c)); if (hi - lo < 1e-4) continue;
      const p = { src: c.src, stream: c.stream, start: o + lo - a, in: c.in + lo - c.start, out: c.in + hi - c.start };
      if (withEnv) {
        const ts = new Set([lo, hi]); envTimes(ts, c.vol, c.start, lo, hi); fadeTimes(ts, c, c.start, clipEnd(c), lo, hi);
        const n = nextAdj(c), pv = prevAdj(c);
        if (c.xo && n) addRange(ts, clipEnd(c) - c.xo / 2, clipEnd(c), 16, lo, hi);
        if (pv && pv.xo) addRange(ts, c.start, c.start + pv.xo / 2, 16, lo, hi);
        p.env = thin([...ts].sort((x, y) => x - y).map(t => [t - lo, clipG(c, Math.min(t, clipEnd(c) - 1e-6))]));
        if (p.env.every(e => Math.abs(e[1] - 1) < 1e-6)) delete p.env;
        if (c.fx) p.fx = c.fx;
      }
      res.push(p);
    }
    return res;
  };
  plan.vlanes = Array.from({ length: R.nv }, (_, i) => ({ clips: R.clips.filter(c => c.lane === -(i + 1)).flatMap(c => pieces(c, false)) }));
  plan.alanes = R.lanes.map((l, k) => ({ fx: l.fx, clips: R.clips.filter(c => c.lane === k).flatMap(c => pieces(c, true)) }));
  const g = [], pf = [];
  for (const [a, b, o] of map) {
    const ts = new Set([a, b]); envTimes(ts, S, 0, a, b); fadeTimes(ts, S, S.inT, S.outT, a, b);
    for (const t of [...ts].sort((x, y) => x - y)) g.push([o + t - a, globalG(t)]);
    const tp = new Set([a, b, Math.max(a, b - 1e-4)]); fadeTimes(tp, S.V, S.inT, S.outT, a, b);
    for (const c of R.clips) if (c.lane < 0) { fadeTimes(tp, c, c.start, clipEnd(c), a, b); if (c.start > a && c.start < b) { tp.add(c.start); tp.add(c.start - 1e-4); } }
    for (const t of [...tp].sort((x, y) => x - y)) pf.push([o + t - a, picG(t)]);
  }
  plan.genv = thin(g); plan.pfade = pf.some(p => p[1] < .9999) ? thin(pf) : null;
  return plan;
}
async function save(mode, extra = {}) {
  stop(); closeMenus(); closeCards();
  saving = true;
  for (const b of document.querySelectorAll("button")) b.disabled = true;
  const sb = $("save"), bar = $("splitsv"), pct = v => sb.innerHTML = `<span>${Math.floor(v)}%</span>`;
  sb.style.width = sb.offsetWidth + "px"; bar.classList.add("busy"); pct(0); bar.style.setProperty("--p", "0%"); say("");   // the button keeps its size
  const timer = setInterval(async () => { const p = await pywebview.api.progress(); bar.style.setProperty("--p", p.pct + "%"); pct(p.pct); }, 200);
  const q = kind === "photo" ? { mode, nsrc: 1, crop: st.G.crop, adj: st.G.adj, ...extra } : { mode, ...exportPlan(), ...extra };
  const r = await pywebview.api.save(q);
  clearInterval(timer); saving = false;
  bar.classList.remove("busy"); bar.style.removeProperty("--p");
  if (!r.ok) say(r.msg, true);
  if (r.ok) { sb.classList.remove("primary"); sb.textContent = "Done ✓"; setTimeout(() => pywebview.api.close(), hasV() ? 1800 : 900); }
  else { sb.style.width = ""; for (const b of document.querySelectorAll("button")) b.disabled = false; buttons(); }
}
function closeMenus() { $("smenu").style.display = "none"; $("ctx").style.display = "none"; }
function openMenu() {
  const m = $("smenu"), s = $("savemenu").getBoundingClientRect();
  const items = project() ? [["m_quick", "save", "Save as new (from the first file)"]]
    : [["m_new", "save", "Save as new…"]];
  if (hasV()) items.push(null, ["m_out", "output", "Output…"]);
  if (kind !== "photo") items.push(null, ["m_proj", "project", projSaved !== null ? "Save project" : "Save project…", "Ctrl+Shift+S"]);
  if (projSaved !== null) items.push(["m_projas", "project", "Save project as…"]);
  m.innerHTML = items.map(i => i ? `<button id="${i[0]}">${icon(i[1])}${i[2]}${i[3] ? `<small>${i[3]}</small>` : ""}</button>` : "<hr>").join("");
  if ($("m_new")) $("m_new").onclick = () => openSaveAs();
  if ($("m_quick")) $("m_quick").onclick = () => save("new", { name: SRC[0].stem + " (edit)", auto: true, keepProps: true, props: 0 });
  if ($("m_proj")) $("m_proj").onclick = () => saveProject(false);
  if ($("m_projas")) $("m_projas").onclick = () => saveProject(true);
  if ($("m_out")) $("m_out").onclick = () => { closeMenus(); openOut(); };
  m.style.display = "flex";
  const r = m.getBoundingClientRect(); m.style.left = clamp(s.right - r.width, 8, innerWidth - r.width - 8) + "px"; m.style.top = (s.top - r.height - 8) + "px";
}
function openSaveAs(keep) {
  closeMenus(); hideSound();
  const pj = project();
  if (!keep) {
    $("sa_name").value = SRC[0].stem + " (edit)"; $("sa_del").checked = false; $("sa_keep").checked = true; $("sa_keepone").checked = true;
    $("sa_props").innerHTML = act().map((s, i) => `<option value="${i}">${s.name}</option>`).join("");
  }
  $("sa_ext").textContent = SRC[0].ext;
  $("sa_names").innerHTML = pj ? "Name from:" + act().map((s, i) => `<button data-i="${i}" title="${s.name}">${s.stem}</button>`).join("") : "";
  for (const b of $("sa_names").querySelectorAll("button")) b.onclick = () => { $("sa_name").value = act()[+b.dataset.i].stem; checkName(); };
  $("sa_names").style.display = pj ? "flex" : "none";
  $("sa_proprow").style.display = pj ? "flex" : "none"; $("sa_keep1").style.display = pj ? "none" : "flex";
  $("sa_dellbl").textContent = pj ? "Move the originals to the Recycle Bin" : "Move the original to the Recycle Bin";
  $("sa_outrow").style.display = hasV() ? "flex" : "none"; if (hasV()) $("sa_out").textContent = "Output: " + outText();
  $("veil").style.display = "block"; $("saveas").style.display = "flex"; checkName(); $("sa_name").focus(); if (!keep) $("sa_name").select();
}
async function checkName() {
  const n = $("sa_name").value.trim(), bad = !n || /[<>:"/\\|?*]/.test(n);
  const del = $("sa_del").checked ? act().map((_, i) => i) : [];
  const ex = !bad && await pywebview.api.exists(n, SRC[0].ext, del);
  $("sawarn").textContent = bad ? "Not a valid file name" : ex ? "A file with this name already exists" : "";
  $("sa_ok").disabled = bad || ex;
}
$("sa_name").addEventListener("input", checkName);
$("sa_del").addEventListener("change", checkName);
$("sa_name").addEventListener("keydown", ev => { if (ev.key === "Enter" && !$("sa_ok").disabled) $("sa_ok").click(); if (ev.key === "Escape") closeCards(); ev.stopPropagation(); });
$("sa_cancel").onclick = closeCards;
$("sa_outb").onclick = openOut;
$("sa_ok").onclick = () => save("new", { name: $("sa_name").value.trim(), keepProps: project() ? $("sa_keep").checked : $("sa_keepone").checked,
  props: project() ? +$("sa_props").value : 0, delOrig: $("sa_del").checked });
$("veil").onclick = () => {                      // a click outside keeps what was done (Cancel undoes it)
  if ($("settings").style.display === "flex") saveSettings();
  else if ($("outc").style.display === "flex") $("o_ok").click();
  else closeCards();
};
$("save").onclick = () => project() ? openSaveAs() : save("replace");
$("save").addEventListener("contextmenu", ev => { ev.preventDefault(); openMenu(); });
$("save").addEventListener("mousedown", ev => { if (ev.button === 2) ev.stopPropagation(); });
$("savemenu").onclick = () => { $("smenu").style.display === "flex" ? closeMenus() : openMenu(); };
$("savemenu").addEventListener("mousedown", ev => ev.stopPropagation());
$("smenu").addEventListener("mousedown", ev => ev.stopPropagation());
$("cancel").onclick = () => pywebview.api.close();

// ---------- adding files: they go after the end of the timeline, on their tracks
async function addFiles() {
  stop();
  const r = await pywebview.api.add_files();
  if (r.bad.length) say("Can't add: " + r.bad.join(", "), true);
  if (!r.added.length) return;
  remember();
  const R = st.R; let pos = dur;
  for (const s of r.added) {
    SRC[s.i] = s; st.nsrc = s.i + 1;
    if (s.video && !R.nv) R.nv = 1;
    while (R.lanes.length < s.audios.length) R.lanes.push({ fx: null });
    R.clips.push(...clipsFor(s, pos)); pos += s.still ? STILL : s.duration;
  }
  if (!CW) setCanvas();
  document.body.classList.toggle("video", hasV()); document.body.classList.toggle("audio", !hasV());
  if (hasV()) buildRatios();
  overPeaks = null; fields(); $("fit").click(); layoutAll();
  for (const s of r.added) loadWaves(s.i);
}
$("addb").onclick = addFiles; $("addcol").onclick = addFiles;
async function addAudio(k) {                     // onto that track at the playhead; it's taken: the next free one, or a new one
  stop();
  const r = await pywebview.api.add_files(true);
  if (r.bad.length) say("Can't add: " + r.bad.join(", "), true);
  if (!r.added.length) return;
  remember();
  const R = st.R; let pos = ph;
  for (const s of r.added) {
    SRC[s.i] = s; st.nsrc = s.i + 1;
    const g = nextId++, e = pos + s.duration; let lane = k;
    s.audios.forEach((_, n) => {
      while (R.clips.some(c => c.lane === lane && c.start < e - 1e-4 && clipEnd(c) > pos + 1e-4)) lane++;
      while (R.lanes.length <= lane) R.lanes.push({ fx: null, keep: true });
      R.clips.push({ id: nextId++, g, src: s.i, lane, stream: n, start: pos, in: 0, out: s.duration, ...bits() }); lane++;
    });
    pos = e;
  }
  overPeaks = null; fields(); layoutAll();
  for (const s of r.added) loadWaves(s.i);
}
