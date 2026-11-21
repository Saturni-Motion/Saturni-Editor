// Effects and Sound panels.

// ---------- picture adjustments (the top button) and sound (the button on the left / right-click)
const pm = v => (v > 0 ? "+" : "") + Math.round(v);
const PIC_SL = [["exp", "Exposure", -3, 3, .05, v => (v > 0 ? "+" : "") + v.toFixed(2)], ["bri", "Brightness", -100, 100, 1, pm],
  ["con", "Contrast", -100, 100, 1, pm], ["sat", "Saturation", -100, 100, 1, pm],
  ["temp", "Temperature", -100, 100, 1, pm, "linear-gradient(90deg,#4d8fff,#777 50%,#ffc04d)"],
  ["tint", "Tint", -100, 100, 1, pm, "linear-gradient(90deg,#4dd96b,#777 50%,#d94dd0)"],
  ["hi", "Highlights", -100, 100, 1, pm], ["sh", "Shadows", -100, 100, 1, pm], ["wh", "Whites", -100, 100, 1, pm], ["bl", "Blacks", -100, 100, 1, pm],
  ["sharp", "Sharpness", 0, 100, 1, pm], ["clar", "Clarity", -100, 100, 1, pm], ["grain", "Grain", 0, 100, 1, pm],
  ["nr", "Noise reduction", 0, 100, 1, pm], ["vig", "Vignette", 0, 100, 1, pm], ["disp", "Dispersion", 0, 100, 1, pm]];
const dBf = v => (v > 0 ? "+" : "") + (+v).toFixed(1) + " dB", msf = v => (v < 10 ? (+v).toFixed(1) : Math.round(v)) + " ms";
const AUD_SL = [["gain", "Gain", -20, 20, .5, dBf], ["bass", "Bass", -12, 12, .5, v => (v > 0 ? "+" : "") + (+v).toFixed(1)],
  ["treble", "Treble", -12, 12, .5, v => (v > 0 ? "+" : "") + (+v).toFixed(1)], ["hp", "Low cut", 0, 400, 5, v => v ? Math.round(v) + " Hz" : "off"],
  ["lp", "High cut", 0, 20000, 100, v => v ? (v / 1000).toFixed(1) + " k" : "off"]];
const COMP_SL = [["cth", "Threshold", -60, 0, .5, dBf], ["crat", "Ratio", 1, 20, .1, v => (+v).toFixed(1) + ":1"], ["catk", "Attack", .1, 200, .1, msf],
  ["crel", "Release", 10, 2000, 5, msf], ["cmk", "Makeup", 0, 24, .5, dBf]];
const LIM_SL = [["lceil", "Ceiling", -12, 0, .1, dBf], ["lrel", "Release", 1, 1000, 1, msf]];
const HSL_C = ["#ff3b3b", "#ff9a2e", "#ffe03b", "#3bd16b", "#3bd9d9", "#3b7bff", "#9a4dff", "#ff4dd2"], HSL_N = ["Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta"];
let hslSel = 0, sndTarget = { type: "master" };
function slider(box, get, set, def, label, lo, hi, stp, f, grad, after) {
  const row = document.createElement("div"); row.className = "sl";
  row.innerHTML = `<span>${label}</span><input type="range" min="${lo}" max="${hi}" step="${stp}"><output></output>`;
  const inp = row.querySelector("input");
  if (grad) { inp.classList.add("grad"); inp.style.setProperty("--g", grad); }
  inp._get = get; inp._f = f;
  inp.addEventListener("pointerdown", () => remember());
  inp.addEventListener("pointerup", () => { if (undoS.length && undoS[undoS.length - 1] === snapshot()) { undoS.pop(); buttons(); } inp.blur(); });
  inp.addEventListener("input", () => { set(+inp.value); inp.nextElementSibling.textContent = f(+inp.value); after(); buttons(); });
  inp.addEventListener("dblclick", () => { if (get() === def) return; remember(); set(def); inp.value = def; inp.nextElementSibling.textContent = f(def); after(); buttons(); });
  box.appendChild(row);
}
function cap(box, t) { const c = document.createElement("div"); c.className = "cap"; c.textContent = t; box.appendChild(c); return c; }
function buildAdjust() {
  const box = $("adjlist"); box.innerHTML = "";
  for (const [k, label, lo, hi, stp, f, grad] of PIC_SL) slider(box, () => st.G.adj[k], v => st.G.adj[k] = v, ADJ0[k], label, lo, hi, stp, f, grad, applyAdj);
  cap(box, "HSL");
  const sw = document.createElement("div"); sw.className = "hsw";
  HSL_C.forEach((c, i) => { const d = document.createElement("i"); d.style.background = c; d.title = HSL_N[i]; d.onclick = () => { hslSel = i; adjShow(); }; sw.appendChild(d); });
  box.appendChild(sw);
  for (const [k, label] of [["h", "Hue"], ["s", "Saturation"], ["l", "Lightness"]]) slider(box, () => st.G.adj.hsl[k][hslSel], v => st.G.adj.hsl[k][hslSel] = v, 0, label, -100, 100, 1, pm, null, applyAdj);
  adjShow();
}
function adjShow() {
  for (const inp of document.querySelectorAll("#adjlist input[type=range]")) { const v = inp._get(); inp.value = v; inp.nextElementSibling.textContent = inp._f(v); }
  document.querySelectorAll(".hsw i").forEach((d, i) => d.classList.toggle("on", i === hslSel));
  applyAdj();
}
function applyAdj() {
  const a = st.G.adj;
  if (glOk) { $("view").style.filter = ""; $("vig").style.background = "none"; }
  else {
    $("view").style.filter = `brightness(${Math.pow(2, a.exp)}) contrast(${1 + a.con / 100}) saturate(${1 + a.sat / 100})`;
    const k = a.vig / 100 * .9;
    $("vig").style.background = k ? `radial-gradient(ellipse farthest-corner at center, rgba(0,0,0,0) 40%, rgba(0,0,0,${k}) 100%)` : "none";
  }
  glDirty = true;
}
function sndObj(make) {                          // the sound settings being edited: master, one track or one piece
  const t = sndTarget;
  if (t.type === "lane") { const l = st.R.lanes[t.k]; if (!l) return st.G.aud; if (!l.fx && make) l.fx = cp(AUD0); return l.fx || AUD0; }
  if (t.type === "clip") { const c = st.R.clips.find(q => q.id === t.id); if (!c) return st.G.aud; if (!c.fx && make) c.fx = cp(AUD0); return c.fx || AUD0; }
  return st.G.aud;
}
function openSound(target) {
  sndTarget = target || { type: "master" };
  $("sndtarget").textContent = sndTarget.type === "lane" ? "· track A" + (sndTarget.k + 1) : sndTarget.type === "clip" ? "· this clip" : "· all tracks";
  buildSound(); $("sound").style.display = "flex"; $("sndb").classList.add("on");
}
function buildSound() {
  const box = $("sndlist"); box.innerHTML = "";
  const g = k => () => sndObj(false)[k], s = k => v => { sndObj(true)[k] = v; };
  for (const [k, label, lo, hi, stp, f] of AUD_SL) slider(box, g(k), s(k), AUD0[k], label, lo, hi, stp, f, null, applyAud);
  for (const [flag, title, list] of [["comp", "Compressor", COMP_SL], ["lim", "Limiter", LIM_SL]]) {
    const c = cap(box, title); const lb = document.createElement("label"); lb.className = "ck"; lb.innerHTML = `<input type="checkbox">On`; c.appendChild(lb);
    const ck = lb.querySelector("input"); ck.dataset.flag = flag;
    ck.onchange = () => { remember(); sndObj(true)[flag] = ck.checked ? 1 : 0; sndShow(); applyAud(); buttons(); ck.blur(); };
    const grp = document.createElement("div"); grp.className = "grp"; grp.dataset.flag = flag; box.appendChild(grp);
    for (const [k, label, lo, hi, stp, f] of list) slider(grp, g(k), s(k), AUD0[k], label, lo, hi, stp, f, null, applyAud);
  }
  sndShow();
}
function sndShow() {
  if ($("sound").style.display !== "flex" && !$("sndlist").children.length) return;
  const o = sndObj(false);
  for (const inp of document.querySelectorAll("#sndlist input[type=range]")) { const v = inp._get(); inp.value = v; inp.nextElementSibling.textContent = inp._f(v); }
  document.querySelectorAll("#sndlist .grp").forEach(g => g.style.opacity = o[g.dataset.flag] ? 1 : .4);
  document.querySelectorAll("#sndlist .cap input").forEach(c => c.checked = !!o[c.dataset.flag]);
}
// Effects stand in the right column, in the place of the "+": the picture makes room; they stay open until closed
function showAdjust(on) { $("adjust").style.display = on ? "flex" : "none"; $("adjb").classList.toggle("on", on); document.body.classList.toggle("fx", on); if (st) layoutAll(); }
function hideAdjust() { if (document.body.classList.contains("fx")) showAdjust(false); }
function hideSound() { $("sound").style.display = "none"; $("sndb").classList.remove("on"); }
$("adjb").onclick = () => showAdjust(!document.body.classList.contains("fx"));
$("sndb").onclick = () => { if ($("sound").style.display === "flex") hideSound(); else openSound({ type: "master" }); };
for (const id of ["adjb", "sndb", "adjust", "sound"]) $(id).addEventListener("mousedown", ev => ev.stopPropagation());
$("adjreset").onclick = () => { remember(); st.G.adj = cp(ADJ0); adjShow(); buttons(); };
$("sndreset").onclick = () => {
  remember(); const t = sndTarget;
  if (t.type === "lane" && st.R.lanes[t.k]) st.R.lanes[t.k].fx = null;
  else if (t.type === "clip") { const c = st.R.clips.find(q => q.id === t.id); if (c) c.fx = null; }
  else st.G.aud = cp(AUD0);
  sndShow(); applyAud(); buttons();
};
window.addEventListener("mousedown", () => { hideSound(); closeMenus(); });
