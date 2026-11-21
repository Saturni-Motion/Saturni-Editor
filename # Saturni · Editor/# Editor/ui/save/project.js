// Projects: the files and everything done to them in one .sedit file (Save project in the Save menu, Ctrl+Shift+S).
// Opening one (from the welcome window or Explorer) brings back the tracks, cuts, effects and the view.

let projName = "", projSaved = null;              // projSaved: core() at the last project save; null = not a project yet
function restoreProject(p) {
  st = p.state; projName = p.name; projSaved = core();
  nextId = 1 + Math.max(0, ...st.R.clips.flatMap(c => [c.id, c.g || 0]));
  document.body.classList.remove("audio", "video"); kind = hasV() ? "video" : "audio"; document.body.classList.add(kind);
  recalc(); setCanvas(); if (hasV()) buildRatios();
  applyMode(); fields(); v0 = 0; v1 = dur; layoutAll(); buttons();
  for (let i = 1; i < SRC.length; i++) loadWaves(i);
}
async function saveProject(asNew) {
  closeMenus();
  const r = await pywebview.api.save_project(JSON.parse(snapshot()), !!asNew);
  if (!r.ok) { if (r.msg) say(r.msg, true); return; }
  projName = r.name; projSaved = core(); fields(); buttons();
}
