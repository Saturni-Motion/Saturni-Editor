// Switches (.seg): a thin outline around the items, no fill; the chosen item sits under a light glass lens
// that flows to the next one (stretches a little on the way, no bounce). Works by itself: any .seg whose
// button gets the class "on" moves its lens.

const LENS_MS = 360;
function segLens(seg) {
  if (seg.__lens) return;
  const lens = document.createElement("i"); lens.className = "lens"; seg.prepend(lens); seg.__lens = lens;
  let at = null;                                  // {x, w} where the lens stands now
  const place = animate => {
    const b = seg.querySelector("button.on");
    if (!b) { lens.style.opacity = 0; at = null; return; }
    if (!seg.offsetWidth) return;                 // hidden now: placed when it shows (ResizeObserver)
    const to = { x: b.offsetLeft, w: b.offsetWidth };
    if (at && to.x === at.x && to.w === at.w && lens.style.opacity === "1") return;
    if (animate && at && lens.style.opacity === "1") {
      const lo = Math.min(at.x, to.x), hi = Math.max(at.x + at.w, to.x + to.w), lead = to.x > at.x;
      lens.animate([
        { left: at.x + "px", width: at.w + "px" },
        { left: (lead ? lo + (hi - lo) * .18 : lo) + "px", width: (hi - lo) * .82 + "px", transform: "scaleY(.9)", offset: .45 },
        { left: to.x + "px", width: to.w + "px" }], { duration: LENS_MS, easing: "cubic-bezier(.45,0,.2,1)" });
    }
    Object.assign(lens.style, { left: to.x + "px", width: to.w + "px", opacity: 1 }); at = to;
  };
  new MutationObserver(() => place(true)).observe(seg, { subtree: true, attributes: true, attributeFilter: ["class"], childList: true });
  new ResizeObserver(() => { at = null; place(false); }).observe(seg);
  place(false);
}
function initSegs(root = document) { for (const s of root.querySelectorAll(".seg")) segLens(s); }
initSegs();
