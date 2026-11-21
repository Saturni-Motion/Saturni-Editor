// Settings and the Output card.

// ---------- settings (written into the script itself)
function applyColors() {
  const r = document.documentElement.style;
  for (const [k, v] of [["--bg", C.bg], ["--panel", C.panel], ["--text", C.text], ["--accent", C.accent], ["--stage", C.stage]]) r.setProperty(k, v);
  overPeaks = null; dirty = true;
  if (st) layoutAll();
}
let setBackup = null;
const CGROUPS = [["Window", ["bg", "panel", "text", "accent", "stage"]],
  ["Timeline", ["timeline", "ruler", "playhead", "selection", "trim", "keep", "removed", "cut", "volume", "fade", "grid", "clip"]],
  ["Whole-file strip", ["overview", "overviewBg", "overviewView"]], ["Level meter", ["meterLow", "meterMid", "meterHigh"]]];
function fillSettings(c, o) {
  const list = $("clist"); list.innerHTML = "";
  for (const [title, keys] of CGROUPS) {
    const cp_ = document.createElement("div"); cp_.className = "cap"; cp_.textContent = title; list.appendChild(cp_);
    const grid = document.createElement("div"); grid.className = "cgrid"; list.appendChild(grid);
    for (const k of keys) {
      const row = document.createElement("div"); row.className = "crow";
      row.innerHTML = `<span>${DEF.names[k] || k}</span><input class="hex" spellcheck="false"><input type="color">`;
      const hex = row.querySelector(".hex"), col = row.querySelector("[type=color]");
      hex.value = col.value = c[k];
      col.addEventListener("input", () => { C[k] = hex.value = col.value; applyColors(); });
      hex.addEventListener("change", () => { if (/^#[0-9a-f]{6}$/i.test(hex.value)) { C[k] = col.value = hex.value.toLowerCase(); applyColors(); } else hex.value = C[k]; });
      grid.appendChild(row);
    }
  }
  $("o_pq").value = o.photoQuality || ""; $("o_mode").value = o.playMode; $("o_prev").value = String(o.preview); $("o_loop").checked = o.loop; $("o_over").checked = !!o.overwrite;
  $("o_mmin").value = o.meterMin; $("o_mmax").value = o.meterMax;
}
function openSettings() { hideSound(); setBackup = { c: { ...C }, o: { ...O } }; fillSettings(C, O); $("veil").style.display = "block"; $("settings").style.display = "flex"; }
function closeCards() { $("veil").style.display = "none"; for (const id of ["settings", "saveas", "outc"]) $(id).style.display = "none"; }
$("setb").onclick = openSettings;
$("s_cancel").onclick = () => { C = setBackup.c; O = setBackup.o; applyColors(); closeCards(); };
$("s_def").onclick = () => { C = { ...DEF.colors }; applyColors(); fillSettings(C, DEF.options); };
async function saveSettings() {
  const lo = clamp(Math.round(+$("o_mmin").value || -60), -120, -6);
  O = { photoQuality: +$("o_pq").value || 0, playMode: $("o_mode").value, preview: +$("o_prev").value, loop: $("o_loop").checked,
        meterMin: lo, meterMax: clamp(Math.round(+$("o_mmax").value), lo + 6, 24), overwrite: $("o_over").checked };
  meterLive = true;
  const r = await pywebview.api.save_settings(C, O);
  if (r.ok) closeCards(); else say(r.msg, true);
}
$("s_save").onclick = saveSettings;

// ---------- output (video): frame rate and bitrate
const FPS_LIST = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60];
function outText() { const fv = firstV(), o = st.G.out; return `${o.fps || +fv.fps.toFixed(3)} fps  ·  ${o.mbps ? o.mbps + " Mbps" : (fv.vbr ? (fv.vbr / 1e6).toFixed(1) + " Mbps (original)" : "original bitrate")}`; }
function openOut() {
  const fv = firstV(), s = $("o_fps");
  s.innerHTML = `<option value="0">Original (${+fv.fps.toFixed(3)})</option>` + FPS_LIST.map(f => `<option value="${f}">${f}</option>`).join("");
  s.value = String(st.G.out.fps || 0); $("o_brorig").checked = !st.G.out.mbps; $("o_brlbl").textContent = `Original${fv.vbr ? " (" + (fv.vbr / 1e6).toFixed(1) + ")" : ""}`;
  $("o_mbps").value = st.G.out.mbps || (fv.vbr ? (fv.vbr / 1e6).toFixed(1) : 8); $("o_mbps").disabled = !st.G.out.mbps;
  $("outc").dataset.back = $("saveas").style.display === "flex" ? "1" : "";
  $("saveas").style.display = "none"; $("veil").style.display = "block"; $("outc").style.display = "flex";
}
$("o_brorig").onchange = () => { $("o_mbps").disabled = $("o_brorig").checked; };
$("o_ok").onclick = () => {
  const o = { fps: +$("o_fps").value || 0, mbps: $("o_brorig").checked ? 0 : Math.max(.2, +$("o_mbps").value || 0) };
  if (JSON.stringify(o) !== JSON.stringify(st.G.out)) { remember(); st.G.out = o; }
  const back = $("outc").dataset.back; closeCards(); if (back) openSaveAs(true); buttons();
};
