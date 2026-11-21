// Panel borders that can be dragged (picture | timeline, picture | Effects) and layout profiles.
// The line lights up with the accent after 1 s of hover. Right-click a border: the saved layouts, Save, Reset.

const GUT_WAIT = 1000;                            // ms of hover before the border lights up
let LAYOUT = { picH: 0, fxW: 300 };               // picH 0 = as big as fits with a 200 px timeline
let LAYOUTS = {}, layoutName = "";
function gutter(cls) {
  const g = document.createElement("div"); g.className = "gut " + cls; document.body.appendChild(g);
  let t = 0;
  g.addEventListener("mouseenter", () => { clearTimeout(t); t = setTimeout(() => g.classList.add("lit"), GUT_WAIT); });
  g.addEventListener("mouseleave", () => { clearTimeout(t); g.classList.remove("lit"); });
  g.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); layoutMenu(ev.clientX, ev.clientY); });
  g.addEventListener("mousedown", ev => {
    if (ev.button) return; ev.preventDefault(); ev.stopPropagation(); g.classList.add("drag");
    const y0 = ev.clientY, x0 = ev.clientX, h0 = $("stage").offsetHeight, w0 = FXW;
    const move = e => {
      if (cls === "h") LAYOUT.picH = Math.max(80, h0 + e.clientY - y0);
      else LAYOUT.fxW = clamp(w0 - (e.clientX - x0), 240, Math.round(innerWidth * .5));
      FXW = LAYOUT.fxW; layoutName = ""; layoutAll();
    };
    const up = () => { g.classList.remove("drag"); removeEventListener("mousemove", move); removeEventListener("mouseup", up); saveLayout(); };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  });
  return g;
}
const gutH = gutter("h"), gutV = gutter("v");
function placeGutters() {                         // called from layoutAll
  const s = $("stage").getBoundingClientRect(), t = $("tlrow").getBoundingClientRect();
  Object.assign(gutH.style, { left: s.left + "px", width: (t.right - s.left) + "px", top: ((s.bottom + t.top) / 2 - 5) + "px" });
  if (document.body.classList.contains("fx")) {
    const a = $("adjust").getBoundingClientRect();
    Object.assign(gutV.style, { left: ((s.right + a.left) / 2 - 5) + "px", top: s.top + "px", height: s.height + "px" });
  }
}
function saveLayout() { FXW = LAYOUT.fxW; py("set_state", "layout", LAYOUT); }
function useLayout(l, name) { LAYOUT = { ...LAYOUT, ...l }; FXW = LAYOUT.fxW; layoutName = name || ""; layoutAll(); saveLayout(); }
function layoutMenu(x, y) {
  const items = Object.keys(LAYOUTS).map(n => [n, n === layoutName ? "check" : "layout", () => useLayout(LAYOUTS[n], n)]);
  if (items.length) items.push(null);
  items.push(["Save this layout", "save", () => {
    let i = 1; while (LAYOUTS["Layout " + i]) i++;
    layoutName = "Layout " + i; LAYOUTS[layoutName] = { ...LAYOUT }; pywebview.api.set_state("layouts", LAYOUTS);
  }]);
  if (layoutName) items.push(["Delete " + layoutName, "trash", () => { delete LAYOUTS[layoutName]; layoutName = ""; pywebview.api.set_state("layouts", LAYOUTS); }]);
  items.push(["Reset layout", "reset", () => useLayout({ picH: 0, fxW: 300 })]);
  menu(items, x, y);
}
function loadLayout(state) { LAYOUTS = state.layouts || {}; LAYOUT = { ...LAYOUT, ...(state.layout || {}) }; FXW = LAYOUT.fxW; }
