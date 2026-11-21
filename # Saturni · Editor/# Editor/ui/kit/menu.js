// Right-click menus.

// ---------- right-click menus
function menu(items, x, y) {                     // items: [label, icon, fn] | null (line)
  const m = $("ctx");
  m.innerHTML = ""; for (const it of items) {
    if (!it) { m.appendChild(document.createElement("hr")); continue; }
    const b = document.createElement("button"); b.innerHTML = `${icon(it[1])}${it[0]}${it[3] ? `<small>${it[3]}</small>` : ""}`; b.onclick = () => { closeMenus(); it[2](); }; m.appendChild(b);
  }
  m.style.display = "flex"; const r = m.getBoundingClientRect();
  m.style.left = clamp(x, 4, innerWidth - r.width - 4) + "px"; m.style.top = clamp(y, 4, innerHeight - r.height - 4) + "px";
}
$("ctx").addEventListener("mousedown", ev => ev.stopPropagation());
tl.addEventListener("contextmenu", ev => {
  ev.preventDefault();
  const x = ev.offsetX, y = ev.offsetY, hh = hit(x, y), t = snapT(x2t(x));
  if (hh.k === "key") { remember(); hh.E.keys.splice(hh.i, 1); fields(); return; }
  const ext = hh.k === "hdr" || hh.k === "none" ? null : v0 < 1e-6 && Math.abs(x - t2x(0)) < 18 ? ["Add empty time at the start", "left", () => armExtend("l")]
    : v1 > dur - 1e-6 && Math.abs(x - t2x(dur)) < 18 ? ["Add empty time at the end", "right", () => armExtend("r")] : null;
  if (!pro() && hh.k !== "hdr") return ext ? menu([ext], ev.clientX, ev.clientY) : undefined;
  const splitHere = only => () => { ph = t; splitAt(t, only); };
  const paste = ["Paste", "paste", () => { ph = t; pasteClips(t); }, "Ctrl+V"];
  if (hh.k === "hdr" && hh.l === "S") return menu([["Sound Effects", "sound", () => openSound({ type: "master" })], null, ["Add audio…", "music", () => addAudio(0)]], ev.clientX, ev.clientY);
  if (hh.k === "hdr" && hh.l !== undefined) {
    const k = hh.l, items = [];
    if (k >= 0) items.push(["Track Sound Effects", "sound", () => openSound({ type: "lane", k })], ["Add audio…", "music", () => addAudio(k)], null);
    items.push(["Add video track", "film", () => addTrack("v")], ["Add sound track", "music", () => addTrack("a")], null,
      ["Delete track " + laneName(k), "trash", () => deleteTrack(k)]);
    return menu(items, ev.clientX, ev.clientY);
  }
  if (hh.k === "trans") return menu([["Remove transition", "close", () => { remember(); hh.c.xo = 0; fields(); }]], ev.clientX, ev.clientY);
  const c = hh.c, items = [];
  if (clipSel && c && clipSel.id === c.id) items.push(["Delete this part", "trash", () => clipPart("delete")], ["Keep only this part", "keep", () => clipPart("keep")], null);
  if (c) {
    if (!csel.has(c.id)) { csel.clear(); csel.add(c.id); dirty = true; }
    items.push(["Split here", "split", splitHere(csel.size > 1 ? null : [c]), "S"], null,
      ["Cut", "scissors", cutClips, "Ctrl+X"], ["Copy", "copy", copyClips, "Ctrl+C"]);
    if (clipB) items.push(paste);
    items.push(["Duplicate", "copy", duplicateClips, "Ctrl+D"], null, ["Delete", "trash", () => deleteClips(), "Del"], ["Ripple Delete", "trash", rippleDelete, "Shift+Del"],
      ["Select All", "all", selectAllClips, "Ctrl+A"]);
    if (c.lane >= 0) items.push(null, ["Sound Effects", "sound", () => openSound({ type: "clip", id: c.id })]);
  } else {
    items.push(["Split all tracks here", "split", () => { csel.clear(); splitHere(null)(); }]);
    if (clipB) items.push(paste);
    items.push(["Select All", "all", selectAllClips, "Ctrl+A"]);
  }
  if (sel) items.push(null, ["Delete the range", "trash", deleteSel]);
  if (ext) items.push(null, ext);
  menu(items, ev.clientX, ev.clientY); buttons();
});
