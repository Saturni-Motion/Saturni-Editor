// One icon set for the whole window: 24×24, round line 1.8 (filled where it says so; class "solid" = outline that fills on hover). icon(name) -> <svg>;
// <button data-i="name"> gets its icon at start. The same drawings are the references in @ INSTRUCTIONS\Icons\Buttons.

function gearPath() {                             // 8 short rounded teeth around a ring
  const n = 8, R = 9.6, r = 7.4, out = [];
  for (let i = 0; i < n; i++) {
    const a = i / n * Math.PI * 2, w = Math.PI / n * .52;
    for (const [ang, rad] of [[a - w * 1.35, r], [a - w * .7, R], [a + w * .7, R], [a + w * 1.35, r]])
      out.push((12 + Math.cos(ang) * rad).toFixed(2) + " " + (12 + Math.sin(ang) * rad).toFixed(2));
  }
  return "M" + out.join("L") + "Z";
}
const STAR = (x, y, r) => `M${x} ${y - r}Q${x} ${y} ${x + r} ${y}Q${x} ${y} ${x} ${y + r}Q${x} ${y} ${x - r} ${y}Q${x} ${y} ${x} ${y - r}Z`;
const ICONS = {
  scissors: '<circle cx="7" cy="6.5" r="3"/><circle cx="17" cy="6.5" r="3"/><path d="M8.7 9 17.6 21M15.3 9 6.4 21"/>',
  trash: '<g transform="matrix(.92 0 0 .92 .96 .96)" stroke-width="1.96"><path d="M4.5 6.5h15"/><path d="M9 6.5V4.3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2.2"/><path d="M6 6.5l1.1 12.6a1.8 1.8 0 0 0 1.8 1.7h6.2a1.8 1.8 0 0 0 1.8-1.7L18 6.5"/></g>',
  sound: '<path d="M3.5 9.5h3l4-3.5v12l-4-3.5h-3z"/><path d="M14 8h7M14 16h7"/><circle cx="16.5" cy="8" r="1.9" class="hole"/><circle cx="19" cy="16" r="1.9" class="hole"/>',
  effects: `<g class="fill"><path d="${STAR(9.5, 12.5, 8.5)}"/><path d="${STAR(18.5, 5.5, 4.5)}"/><path d="${STAR(19, 19, 3.6)}"/></g>`,
  gear: `<path d="${gearPath()}"/><circle cx="12" cy="12" r="3"/>`,
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  prev: '<path d="M6 5v14"/><path d="M18.5 5.8 9.5 12l9 6.2z"/>',
  next: '<path d="M18 5v14"/><path d="M5.5 5.8 14.5 12l-9 6.2z"/>',
  play: '<path class="solid" d="M8.5 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.7 4.5a.8.8 0 0 0-1.2.7z"/>',
  pause: '<g class="solid"><rect x="6.5" y="5" width="4" height="14" rx="1"/><rect x="13.5" y="5" width="4" height="14" rx="1"/></g>',
  loop: '<path d="m17 2.5 3 3-3 3"/><path d="M4 11.5v-1a5 5 0 0 1 5-5h11"/><path d="m7 21.5-3-3 3-3"/><path d="M20 12.5v1a5 5 0 0 1-5 5H4"/>',
  fit: '<path d="M4 9V5h4M16 5h4v4M20 15v4h-4M8 19H4v-4"/>',
  add: '<path d="M12 5v14M5 12h14"/>',
  reset: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4v4h4"/>',
  chevron: '<path d="m6 9.5 6 6 6-6"/>',
  split: '<path d="M12 3v18"/><path d="m8 8-4 4 4 4M16 8l4 4-4 4"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V5.5a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
  paste: '<rect x="5" y="4.5" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5"/><path d="M9 11h6M9 15h4"/>',
  all: '<path stroke-width="1.5" stroke-linecap="butt" d="M3.75 9V7.5A3.75 3.75 0 0 1 7.5 3.75H9M10.5 3.75h3M15 3.75h1.5a3.75 3.75 0 0 1 3.75 3.75V9M20.25 10.5v3M20.25 15v1.5a3.75 3.75 0 0 1-3.75 3.75H15M13.5 20.25h-3M9 20.25H7.5a3.75 3.75 0 0 1-3.75-3.75V15M3.75 13.5v-3"/>',   // dashes on whole pixels at 16 px (1 px line), see Interface → icons
  keep: '<path d="M7 3v14h14"/><path d="M3 7h14v14"/>',
  music: '<path d="M9 18V5.5l11-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  film: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7.5 5v14M16.5 5v14M3.5 12h4M16.5 12h4"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  left: '<path d="m14.5 6-6 6 6 6"/>',
  right: '<path d="m9.5 6 6 6-6 6"/>',
  save: '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8.5 4v5h6V4M8 20v-6h8v6"/>',
  output: '<rect x="3.5" y="5" width="17" height="12" rx="2"/><path d="M9 21h6M12 17v4"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  file: '<path d="M6 3.5h8l4.5 4.5v11.5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1z"/><path d="M13.5 3.5V8.5h5"/>',
  project: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 13.5h8M8 16.5h5"/>',
  layout: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 13h17M14 4.5V13"/>',
  bug: '<path d="M9.2 7.6a2.8 2.8 0 0 1 5.6 0"/><ellipse cx="12" cy="13.2" rx="4" ry="4.6"/><path d="M8.3 10.4L6.1 9.1Q5.4 8.6 5.3 7.8M8 13.2H4.6M8.3 16L6.1 17.3Q5.4 17.8 5.3 18.6M15.7 10.4l2.2-1.3q.7-.5.8-1.3M16 13.2h3.4M15.7 16l2.2 1.3q.7.5.8 1.3"/>',
};
function icon(name) { return `<svg class="i" viewBox="0 0 24 24">${ICONS[name] || ""}</svg>`; }
function placeIcons(root = document) { for (const el of root.querySelectorAll("[data-i]")) el.innerHTML = icon(el.dataset.i) + (el.dataset.t ? `<span>${el.dataset.t}</span>` : ""); }
placeIcons();
