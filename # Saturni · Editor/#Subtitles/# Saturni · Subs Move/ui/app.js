// app.js — Saturni · Subs Move: маркеры титров (^N #N %N ! @ [] ↑↓←→) с превью 1:1 для 2Stage.
import { icon } from './icons.js';

// ═══════════════════════════ utils ═══════════════════════════
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const media = p => `/media?p=${encodeURIComponent(p)}`;
const msSrt = ms => { ms = Math.max(0, Math.round(ms)); const p = (n, l = 2) => String(n).padStart(l, '0'); return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`; };
const srtMs = s => { const m = /(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})/.exec(s || ''); return m ? ((+m[1] * 60 + +m[2]) * 60 + +m[3]) * 1000 + +m[4].padEnd(3, '0') : null; };
// время в списке — коротко: «1,480», «1:05,123», «1:02:03,450» (часы/минуты — только если есть)
const pad2 = n => String(n).padStart(2, '0');
const tShort = ms => { ms = Math.max(0, Math.round(ms)); const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60, f = String(ms % 1000).padStart(3, '0'); return h ? `${h}:${pad2(m)}:${pad2(s)},${f}` : m ? `${m}:${pad2(s)},${f}` : `${s},${f}`; };
const tParse = v => { const m = /^\s*(?:(?:(\d+):)?(\d+):)?(\d+)(?:[,.](\d{1,3}))?\s*$/.exec(v || ''); return m ? ((+(m[1] || 0) * 60 + +(m[2] || 0)) * 60 + +m[3]) * 1000 + +(m[4] || '0').padEnd(3, '0') : null; };
const tfmt = t => { t = Math.max(0, t || 0); return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}.${String(Math.floor(t * 100 % 100)).padStart(2, '0')}`; };

let API = null;
const api = new Proxy({}, { get: (_, k) => async (...a) => { try { return await API[k](...a); } catch (e) { console.error(k, e); toast({ kind: 'err', title: 'Error', text: String(e?.message || e) }); return null; } } });

// ═══════════════════════════ markers (копия @SRT Markers.py) ═══════════════════════════
const TOKEN_SRC = /\^\s*(-?\d+)|#\s*(?:([wW])\s*(\d*)|(\d+))|%\s*(\d+)|(!)|(@)|\[\s*([wW]?)\s*(\d*)\s*\]|([↑↓←→])\s*(-?\d+)|`\s*(\d+)/.source;
function parseMk(s) {
  const m = { size: null, shadow: null, shadow_white: false, opacity: null, black: false, bold: false, plate: false, plate_white: false, plate_opacity: null, dx: 0, dy: 0, margin: null };
  for (const t of String(s || '').matchAll(new RegExp(TOKEN_SRC, 'g'))) {
    const [, size, shw, shwn, sh, op, black, bold, pw, pn, arrow, an, margin] = t;
    if (size != null) m.size = +size;
    else if (shw) { m.shadow_white = true; if (shwn) m.shadow = clamp(+shwn, 0, 100); }
    else if (sh != null) m.shadow = clamp(+sh, 0, 100);
    else if (op != null) m.opacity = clamp(+op, 0, 100);
    else if (black) m.black = true;
    else if (bold) m.bold = true;
    else if (arrow) { const n = +an; if (arrow === '↑') m.dy -= n; else if (arrow === '↓') m.dy += n; else if (arrow === '←') m.dx -= n; else m.dx += n; }
    else if (margin != null) m.margin = +margin;
    else { m.plate = true; m.plate_white = !!pw; m.plate_opacity = pn ? clamp(+pn, 0, 100) : null; }
  }
  return m;
}
function fmtMk(m) {
  let o = '';
  if (m.margin != null) o += '`' + m.margin;
  const dy = Math.round(m.dy || 0), dx = Math.round(m.dx || 0);
  if (dy < 0) o += '↑' + (-dy); else if (dy > 0) o += '↓' + dy;
  if (dx < 0) o += '←' + (-dx); else if (dx > 0) o += '→' + dx;
  if (m.size) o += '^' + m.size;
  if (m.opacity != null) o += '%' + m.opacity;
  if (m.bold) o += '@';
  if (m.shadow != null || m.shadow_white) o += '#' + (m.shadow_white ? 'w' : '') + (m.shadow == null ? '' : m.shadow);
  if (m.black) o += '!';
  if (m.plate) o += '[' + (m.plate_white ? 'w' : '') + (m.plate_opacity == null ? '' : m.plate_opacity) + ']';
  return o;
}
const canon = s => fmtMk(parseMk(s));
// раздельные маркеры: «H: ↑20[] · V: ↑200[]» (без префикса — для обоих, «V: …» — только вертикаль)
const ORI = /^\s*([HhVvНнВв])\s*:\s*(.*?)\s*$/;
function splitHV(s) {
  let common = null, h = null, v = null;
  for (const seg of String(s || '').split(/[·|]/)) {
    const r = ORI.exec(seg);
    if (r) { if ('HhНн'.includes(r[1])) h = r[2]; else v = r[2]; }
    else if (seg.trim()) common = seg.trim();
  }
  return { h: h ?? common ?? '', v: v ?? common ?? '' };
}
function joinHV(h, v) {
  h = (h || '').trim(); v = (v || '').trim();
  if (h === v) return h;
  return [h ? `H: ${h}` : '', v ? `V: ${v}` : ''].filter(Boolean).join(' · ');
}
const canonFull = s => { const d = splitHV(s); return joinHV(canon(d.h), canon(d.v)); };
const hasHV = s => String(s || '').split(/[·|]/).some(seg => ORI.test(seg));
const mkOf = (b, o = S.orient) => b ? splitHV(b.mk)[o] : '';          // маркеры версии H / V (по умолчанию — выбранной)
function setOri(b, str, o = S.orient) { const d = splitHV(b.mk); d[o] = canon(str); b.mk = joinHV(d.h, d.v); }
const hasMarkers = s => new RegExp(TOKEN_SRC).test(String(s || ''));

// ═══════════════════════════ state ═══════════════════════════
const S = {
  prefs: {}, style: {}, base: {}, glob: {}, file: null, blocks: [], sel: new Set(), cur: null, anchor: null,
  orient: 'h', t: 0, playing: false, dirty: false, hist: [], hi: -1, strips: {}, win: { max: false }, nextId: 1,
};
const G_KEYS = ['shadow_blur', 'shadow_x', 'shadow_y', 'plate_radius', 'plate_pad_x', 'plate_pad_y'];
const OVR = ['font_size', 'text_opacity', 'shadow_opacity', 'shadow_x', 'shadow_y', 'shadow_blur', 'plate_opacity', 'plate_radius', 'plate_pad_x', 'plate_pad_y'];
const eff = k => S.glob[k] ?? S.style[k];
const blk = id => S.blocks.find(b => b.id === id);
const idx = id => S.blocks.findIndex(b => b.id === id);
const cur = () => blk(S.cur);
const selBlocks = () => S.blocks.filter(b => S.sel.has(b.id));
const video = () => master()?.info;                                   // видео главной панели (H, если есть)

// ═══════════════════════════ theme ═══════════════════════════
const mq = matchMedia('(prefers-color-scheme: dark)');
function applyTheme() {
  const t = S.prefs.theme || 'dark', dark = t === 'dark' || (t === 'system' && mq.matches);
  const r = document.documentElement;
  r.dataset.theme = dark ? 'dark' : 'light'; r.dataset.accent = 'blue'; r.dataset.ui = 'minimal';
  api.titlebar(dark, dark ? '#0b0b0f' : '#f1f1f4', dark ? '#f1f1f6' : '#111118', dark ? '#2a2a31' : '#cfcfd8').then(ok => document.body.classList.toggle('native-frame', !!ok));
}
mq.addEventListener('change', () => { if (S.prefs.theme === 'system') applyTheme(); });
const setPref = patch => { Object.assign(S.prefs, patch); return api.prefs_save(patch); };

// ═══════════════════════════ events from Python ═══════════════════════════
window.__emit = evs => { for (const e of evs) try { if (window.SaturniDebug && SaturniDebug.handle(e.type, e.data)) continue; onEvent(e.type, e.data); } catch (err) { console.error(err); } };
function onEvent(type, d) {
  if (type === 'win') { S.win.max = !!d.max; document.body.classList.toggle('maxed', S.win.max); renderWinCtl(); }
  else if (type === 'strip') { if (!d.error) { S.strips[d.orient] = d; if (d.orient === master()?.o) renderTiles(); } }
  else if (type === 'drop') openPath(d[0]);
  else if (type === 'close_request') ACT['win-close']();
}

// ═══════════════════════════ history / dirty ═══════════════════════════
function snap() { return JSON.stringify({ b: S.blocks, g: S.glob }); }
function pushUndo() {
  S.hist = S.hist.slice(0, S.hi + 1); S.hist.push(snap()); S.hi = S.hist.length - 1;
  if (S.hist.length > 200) { S.hist.shift(); S.hi--; }
}
function undo(dir) {
  if (dir < 0) {
    if (S.hi < 0) return;
    if (S.hi === S.hist.length - 1) S.hist.push(snap());
    restore(S.hist[S.hi]); S.hi--;
  } else {
    if (S.hi + 2 >= S.hist.length) return;
    S.hi++; restore(S.hist[S.hi + 1]);
  }
  setDirty(true); renderLeft(); renderInspector(); updateLayer(); renderMarks();
}
function restore(js) {
  const d = JSON.parse(js); S.blocks = d.b; S.glob = d.g || {};
  for (const id of [...S.sel]) if (!blk(id)) S.sel.delete(id);
  if (!blk(S.cur)) S.cur = S.blocks[0]?.id ?? null;
}
function setDirty(v) { if (S.dirty === v) return; S.dirty = v; api.set_dirty(v); renderTop(); renderSaveBtn(); }

// ═══════════════════════════ TOP BAR ═══════════════════════════
function renderTop() {
  const th = S.prefs.theme || 'dark';
  $('#tbTools').innerHTML = `<button class="ibtn" data-act="theme" data-tip="Theme: ${th}" data-kb="Ctrl+T">${icon({ system: 'monitor', light: 'sun', dark: 'moon' }[th], 18)}</button>`
    + `<button class="ibtn" data-act="settings" data-tip="Settings · Ctrl+click: Debug">${icon('settings', 18)}</button>`;
  const ch = $('.brand-chev'); if (ch && !ch.innerHTML) ch.innerHTML = icon('down', 13);
  $('#tbCenter').innerHTML = S.file ? `<div class="crumb">${S.dirty ? '<i class="dirty" data-tip="Unsaved changes"></i>' : ''}<b class="nowrap">${esc(S.file.name)}</b><span class="muted">${S.blocks.length} blocks</span></div>` : '';
}
function renderWinCtl() {
  $('#wctl').innerHTML = `<span class="tb-sep"></span>
    <button class="wbtn" data-act="win-min" data-tip="Minimize">${icon('wmin', 16)}</button>
    <button class="wbtn" data-act="win-max" data-tip="${S.win.max ? 'Restore' : 'Maximize'}">${icon(S.win.max ? 'wrestore' : 'wmax', 14)}</button>
    <button class="wbtn close" data-act="win-close" data-tip="Close">${icon('x', 16)}</button>`;
}

// ═══════════════════════════ LEFT: blocks ═══════════════════════════
function rowHtml(b, i) {
  const c = [S.sel.has(b.id) ? 'sel' : '', b.id === S.cur ? 'cur' : '', b.id === S.liveId ? 'live' : ''].join(' ');
  return `<div class="sb ${c}" data-id="${b.id}" data-has="${b.mk ? 1 : 0}">
    <span class="sb-n">${i + 1}</span><div class="sb-c"><div class="sb-r1"><span class="sb-t"><span class="ed" data-f="start">${tShort(b.start)}</span><span class="sb-dash">–</span><span class="ed" data-f="end">${tShort(b.end)}</span></span><span class="sb-mk ed" data-f="mk">${esc(b.mk)}</span><button class="sb-copy" data-act="copy-row" data-tip="Copy markers">${icon('copy', 13)}</button></div>
    <div class="sb-x ed" data-f="text">${esc(b.text)}</div></div></div>`;
}
function renderLeft() {
  const el = $('#sideLeft');
  const keep = $('#blist')?.scrollTop || 0;
  el.innerHTML = `<div class="side-h"><h3>Subtitles</h3><span class="cnt">${S.sel.size > 1 ? `${S.sel.size} selected · ` : ''}${S.blocks.length || ''}</span></div>
    <div class="blist" id="blist" tabindex="0">${S.blocks.map(rowHtml).join('')}</div>
    <div class="side-foot"><button class="btn hov" data-act="open" data-tip="Open .srt or video (or drop it on the window)" data-kb="Ctrl+O">${icon('folderopen', 16)}Open</button></div>`;
  $('#blist').scrollTop = keep;
}
function patchRows(ids) {
  for (const id of ids) {
    const b = blk(id), r = $(`.sb[data-id="${id}"]`); if (!b || !r) continue;
    const mk = $('.sb-mk', r); if (!mk.classList.contains('editing')) mk.textContent = b.mk;
    r.dataset.has = b.mk ? 1 : 0;
  }
}
function paintSel() {
  $$('.sb').forEach(r => { const id = +r.dataset.id; r.classList.toggle('sel', S.sel.has(id)); r.classList.toggle('cur', id === S.cur); });
  const c = $('#sideLeft .cnt'); if (c) c.textContent = `${S.sel.size > 1 ? `${S.sel.size} selected · ` : ''}${S.blocks.length}`;
}
function select(id, { add, range, seek = true, keep } = {}) {
  if (id == null) return;
  if (range && S.anchor != null) {
    const a = idx(S.anchor), b = idx(id);
    if (!add) S.sel.clear();
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) S.sel.add(S.blocks[i].id);
  } else if (add) {
    if (S.sel.has(id) && S.sel.size > 1) S.sel.delete(id); else S.sel.add(id);
    S.anchor = id;
  } else if (!keep) { S.sel = new Set([id]); S.anchor = id; }
  S.cur = S.sel.has(id) ? id : [...S.sel][0] ?? null;
  paintSel(); renderInspector(); renderMarks();
  if (seek) { const b = cur(); if (b) seekTo(b.start / 1000 + Math.min(0.08, (b.end - b.start) / 2000)); }
  $(`.sb[data-id="${S.cur}"]`)?.scrollIntoView({ block: 'nearest' });
}

// inline-редактирование по двойному клику
function editField(el) {
  const r = el.closest('.sb'), b = blk(+r.dataset.id), f = el.dataset.f;
  if (!b || el.classList.contains('editing')) return;
  const orig = f === 'mk' ? b.mk : f === 'text' ? b.text : tShort(b[f]);
  el.textContent = orig; el.contentEditable = 'plaintext-only'; el.classList.add('editing'); el.focus();
  const rg = document.createRange(); rg.selectNodeContents(el); const s = getSelection(); s.removeAllRanges(); s.addRange(rg);
  let done = false;
  const finish = ok => {
    if (done) return; done = true;
    el.contentEditable = 'false'; el.classList.remove('editing');
    const v = el.innerText.replace(/ /g, ' ').replace(/\n+$/, '');
    if (ok && v !== orig) {
      if (f === 'mk') { pushUndo(); b.mk = canonFull(v); }
      else if (f === 'text') { if (!v.trim()) { toast({ kind: 'warn', title: 'Empty text', text: 'Use Delete to remove a block' }); } else { pushUndo(); b.text = v.trim(); } }
      else {
        const ms = tParse(v);
        if (ms == null) toast({ kind: 'warn', title: 'Wrong time', text: 'Format: 1,480 · 1:05,480 · 1:02:05,480' });
        else { pushUndo(); b[f] = ms; if (b.end < b.start) [b.start, b.end] = [b.end, b.start]; }
      }
      setDirty(true);
    }
    el.textContent = f === 'mk' ? b.mk : f === 'text' ? b.text : tShort(b[f]);
    if (b.id === S.cur) renderInspector();
    renderMarks(); updateLayer();
  };
  el.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter' && !(f === 'text' && e.shiftKey)) { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  el.addEventListener('blur', () => finish(true), { once: true });
}

// ═══════════════════════════ STAGE ═══════════════════════════
const P = {};                                     // панели предпросмотра: { h: Pane, v: Pane }
const panes = () => Object.values(P);
const master = () => P.h || P.v || null;          // «главная» панель — по ней таймлайн и длительность
const activePane = () => P[S.orient] || master();
const FAM_R = "'SubReg','Fira Sans Extra Condensed',sans-serif";
const FAM_B = "'SubBold','Fira Sans Extra Condensed SemiBold','Fira Sans Extra Condensed',sans-serif";
const PV = new Map(), PVR = new Map();            // точные слои libass: запросы / готовые результаты
const MC = document.createElement('canvas').getContext('2d');

function renderStage() {
  const el = $('#stageWrap');
  panes().forEach(p => p.destroy()); for (const k of Object.keys(P)) delete P[k];
  if (!S.file) {
    el.innerHTML = `<div class="hero-empty"><div class="he-card"><div class="he-ic">${icon('type', 30)}</div>
      <h2>Open subtitles or a video</h2><p style="white-space:nowrap">Find the subtitles and video you want to process.</p>
      <button class="btn primary lg" data-act="open">${icon('folderopen', 17)}Open</button></div></div>`;
    return;
  }
  const vids = S.file.videos, os = ['h', 'v'].filter(o => vids[o]);
  for (const o of os) P[o] = new Pane(o, vids[o]);
  if (!P[S.orient]) S.orient = os[0] || 'h';
  const v = video(), both = os.length > 1;
  el.innerHTML = `<div class="stage-top"><span class="fname">${esc(v ? v.path.split(/[\\/]/).pop() : 'No video with this name')}</span><div class="grow"></div>
      <div class="meta">${v ? `<span class="chip">${icon('video', 12)}${v.w}×${v.h} · ${tfmt(v.dur).slice(0, -3)}</span>` : ''}
      ${both ? `<div class="seg sm" id="oriSeg"><span class="pill"></span><button data-act="orient" data-o="h" class="${S.orient === 'h' ? 'on' : ''}" data-tip="Edit the horizontal version (H)">H</button><button data-act="orient" data-o="v" class="${S.orient === 'v' ? 'on' : ''}" data-tip="Edit the vertical version (V)">V</button></div>` : ''}
      <button class="ibtn sm" data-act="reveal" data-tip="Show in Explorer">${icon('external', 14)}</button></div></div>
    <div id="stMain" style="flex:1;display:flex;flex-direction:column;min-height:0"><div class="canvas dual ${both ? '' : 'one'}" id="canvas"></div></div>
    <div class="stage-bottom tlbar"><button class="ibtn tl-play" data-act="play" data-tip="Play / pause" data-kb="Space">${icon(S.playing ? 'pause' : 'play', 17)}</button>
      <div class="tl" id="tl"><div class="tl-tiles" id="tlTiles"></div><div class="tl-shade"></div><div id="tlSel"></div><div class="tl-blocks" id="tlBlocks"></div><div class="tl-head" id="tlHead"></div></div>
      <span class="tl-time" id="tlTime"></span></div>`;
  movePillSeg();
  const cv = $('#canvas');
  if (os.length) {
    cv.innerHTML = os.map(o => P[o].html(both)).join('');
    for (const p of panes()) p.attach($(`.pbox[data-o="${p.o}"]`, cv));
    master().el.insertAdjacentHTML('beforeend', `<div class="floatbar">
        <button class="ibtn sm" data-act="zoom-out" data-tip="Zoom out">${icon('zout', 15)}</button><span class="zoomv" id="zoomv">100%</span><button class="ibtn sm" data-act="zoom-in" data-tip="Zoom in">${icon('zin', 15)}</button>
        <button class="ibtn sm" data-act="fit" data-tip="Reset view" data-kb="F">${icon('fit', 15)}</button>
        <button class="ibtn sm" data-act="loupe" data-tip="Zoom to subtitle" data-kb="Z">${icon('loupe', 15)}</button>
        <span class="sep"></span><button class="ibtn sm ${document.body.classList.contains('focus') ? 'on' : ''}" data-act="focus" data-tip="Full-window preview" data-kb="\\">${icon('focus', 15)}</button></div>`);
    new ResizeObserver(layoutPanes).observe(cv);
    layoutPanes(); updateLayer();
  } else cv.innerHTML = `<div class="insp-empty" style="padding-top:20vh">${icon('video', 28)}<p>No video next to the subtitles</p></div>`;
  bindTimeline(); renderTiles(); renderMarks(); updateHead();
  const m = master(); if (m && !S.strips[m.o]) api.strip(m.o);
}
function movePillSeg() {
  const seg = $('#oriSeg'); if (!seg) return;
  requestAnimationFrame(() => { const on = $('button.on', seg), p = $('.pill', seg); if (on && p) { p.style.left = on.offsetLeft + 'px'; p.style.width = on.offsetWidth + 'px'; } });
}
function layoutPanes() {
  const cv = $('#canvas'); if (!cv) return;
  if (panes().length > 1) { const r = cv.getBoundingClientRect(); cv.style.setProperty('--vw', Math.round(Math.min(r.height * 9 / 16, r.width * .5)) + 'px'); }
  panes().forEach(p => { if (p.fitted) p.fit(false); });
}
function setOrient(o) {
  if (!P[o] || S.orient === o) return;
  S.orient = o;
  $$('.pbox').forEach(b => b.classList.toggle('active', b.dataset.o === o));
  $$('#oriSeg button').forEach(b => b.classList.toggle('on', b.dataset.o === o)); movePillSeg();
  updateZoomLabel(); renderInspector();
}
function updateZoomLabel() { const zv = $('#zoomv'), p = activePane(); if (zv && p) zv.textContent = Math.round(p.s * 100) + '%'; }

// геометрия титра в пикселях видео (те же формулы, что у libass/плашки в @SRT Markers.py)
function geom(b, o) {
  const info = S.file.videos[o], W = info.w, H = info.h, m = parseMk(mkOf(b, o));
  const fs = eff('font_size') + (m.size || 0), em = fs * 1000 / 1200;
  const lines = String(b.text || '').split('\n'), n = lines.length;
  const baseY = o === 'v' ? S.style.base_y_v : S.style.base_y_h;
  const x = Math.floor(W / 2) + (m.dx || 0), y = (m.margin != null ? H - m.margin : baseY) + (m.dy || 0);
  MC.font = `${em}px ${m.bold ? FAM_B : FAM_R}`;
  const widths = lines.map(l => MC.measureText(l).width), w = Math.max(0, ...widths);
  const baseLast = y - fs * 265 / 1200;
  return { m, W, H, fs, em, lines, n, x, y, widths, w, baseLast, top: baseLast - (n - 1) * fs - .70 * em, bot: baseLast + .14 * em };
}

class Pane {
  constructor(o, info) { this.o = o; this.info = info; this.W = info.w; this.H = info.h; this.s = 1; this.tx = 0; this.ty = 0; this.fitS = 1; this.fitted = true; this.bbox = null; this.key = null; this.exT = 0; this.drag = null; }
  html(both) {
    const v = this.info;
    return `<div class="pbox ${this.o === S.orient ? 'active' : ''}" data-o="${this.o}"><div class="pane"><div class="world" style="width:${v.w}px;height:${v.h}px">
      <video class="base" src="${media(v.path)}" width="${v.w}" height="${v.h}" preload="auto" playsinline></video>
      <div class="layer" style="width:${v.w}px;height:${v.h}px"><canvas class="live" width="${v.w}" height="${v.h}"></canvas><img class="mk hide" draggable="false"><div class="hl"></div></div></div></div>
      ${both ? `<span class="ptag">${this.o.toUpperCase()}</span>` : ''}</div>`;
  }
  attach(el) {
    this.el = el; this.paneEl = $('.pane', el); this.world = $('.world', el); this.vid = $('video', el); this.layerEl = $('.layer', el);
    this.cv = $('canvas.live', el); this.ctx = this.cv.getContext('2d'); this.img = $('img.mk', el); this.hl = $('.hl', el);
    this.vid.addEventListener('loadedmetadata', () => { this.vid.currentTime = S.t; });
    if (this === master()) {
      this.vid.addEventListener('seeked', () => { if (!S.playing) { S.t = this.vid.currentTime; updateHead(); updateLive(); } });
      this.vid.addEventListener('ended', () => setPlaying(false));
    }
    this.bind();
  }
  destroy() { clearTimeout(this.exT); if (this.vid) { try { this.vid.pause(); this.vid.removeAttribute('src'); this.vid.load(); } catch { } } }
  paneSize() { return this.paneEl ? [this.paneEl.clientWidth, this.paneEl.clientHeight] : [800, 600]; }
  fit(anim = true) {
    const [pw, ph] = this.paneSize(), dual = panes().length > 1;
    if (dual) {                                                          // два кадра: оба ровно по центру своей панели — зум идёт в центр кадра
      this.fitS = this.o === 'h' ? .5 : Math.min((pw - 20) / this.W, (ph - 20) / this.H);   // H — зум 50%, V — во весь размер
      this.s = this.fitS; this.tx = (pw - this.W * this.s) / 2; this.ty = (ph - this.H * this.s) / 2;
    } else {
      const bottom = 64, pad = 20;                                       // один кадр: место под панелью управления
      this.fitS = Math.min((pw - pad * 2) / this.W, (ph - pad - bottom) / this.H, 4);
      this.s = this.fitS; this.tx = (pw - this.W * this.s) / 2; this.ty = (ph - bottom + pad - this.H * this.s) / 2;
    }
    this.fitted = true; this.apply(anim);
  }
  zoomAt(f, cx, cy, anim) {
    const ns = clamp(this.s * f, this.fitS * .5, 12);
    this.tx = cx - (cx - this.tx) * (ns / this.s); this.ty = cy - (cy - this.ty) * (ns / this.s); this.s = ns;
    this.fitted = false; this.apply(anim);
  }
  zoomTo(x, y, w, h) {
    const [pw, ph] = this.paneSize();
    const ns = clamp(Math.min((pw * .7) / w, (ph * .45) / h), this.fitS, 12);
    this.s = ns; this.tx = pw / 2 - (x + w / 2) * ns; this.ty = (ph - 60) / 2 - (y + h / 2) * ns;
    this.fitted = false; this.apply(true);
  }
  apply(anim) {
    this.world.classList.toggle('anim', !!anim);
    this.world.style.transform = `translate(${this.tx}px,${this.ty}px) scale(${this.s})`;
    if (this === activePane()) updateZoomLabel();
    if (this.bbox) this.hl.style.borderWidth = (1.5 / this.s) + 'px';
    if (anim) setTimeout(() => this.world?.classList.remove('anim'), 460);
  }
  setBBox(x, y, w, h) {
    this.bbox = { x, y, w, h };
    Object.assign(this.hl.style, { left: (x - 4) + 'px', top: (y - 4) + 'px', width: (w + 8) + 'px', height: (h + 8) + 'px', borderWidth: (1.5 / this.s) + 'px', transform: '' });
    this.hl.classList.add('show');
  }
  clear() { this.ctx.clearRect(0, 0, this.W, this.H); this.img.classList.add('hide'); this.hl.classList.remove('show'); this.bbox = null; this.layerEl.style.transform = ''; }

  // ── мгновенный слой: рисуем титр сами в canvas (пока libass считает точный) ──
  drawLive(b) {
    const g = geom(b, this.o), m = g.m, c = this.ctx;
    c.clearRect(0, 0, this.W, this.H); c.textAlign = 'center'; c.textBaseline = 'alphabetic'; c.font = `${g.em}px ${m.bold ? FAM_B : FAM_R}`;
    let x0 = g.x - g.w / 2, x1 = g.x + g.w / 2, y0 = g.top, y1 = g.bot;
    if (m.plate) {
      const padX = eff('plate_pad_x'), padY = eff('plate_pad_y'), r = eff('plate_radius'), pop = m.plate_opacity ?? eff('plate_opacity');
      x0 = g.x - g.w / 2 - padX; x1 = g.x + g.w / 2 + padX; y0 = g.top - padY; y1 = g.bot + padY;
      c.save(); c.globalAlpha = pop / 100; c.fillStyle = m.plate_white ? '#fff' : '#000';
      c.beginPath(); c.roundRect(x0, y0, x1 - x0, y1 - y0, Math.min(r, (x1 - x0) / 2, (y1 - y0) / 2)); c.fill(); c.restore();
    }
    const sh = m.black ? 0 : (m.shadow ?? eff('shadow_opacity'));
    if (sh > 0) {
      c.save(); c.globalAlpha = sh / 100; c.fillStyle = m.shadow_white ? '#fff' : '#000'; c.filter = `blur(${eff('shadow_blur')}px)`;
      g.lines.forEach((l, i) => c.fillText(l, g.x + eff('shadow_x'), g.baseLast - (g.n - 1 - i) * g.fs + eff('shadow_y')));
      c.restore();
    }
    c.save(); c.globalAlpha = (m.opacity ?? eff('text_opacity')) / 100; c.fillStyle = m.black ? '#000' : '#fff';
    g.lines.forEach((l, i) => c.fillText(l, g.x, g.baseLast - (g.n - 1 - i) * g.fs)); c.restore();
    this.img.classList.add('hide');
    this.setBBox(x0, y0, x1 - x0, y1 - y0);
  }
  // ── точный слой libass (то же, что в рендере) ──
  placeExact(r, key) {
    if (!r || !r.url) { this.clear(); return; }
    const k = this.W / r.W, bb = { x: r.x * k, y: r.y * k, w: r.w * k, h: r.h * k };
    const pre = new Image();
    pre.onload = () => {
      if (this.key !== key) return;
      this.img.src = r.url; this.img.classList.remove('hide');
      Object.assign(this.img.style, { left: bb.x + 'px', top: bb.y + 'px', width: bb.w + 'px', height: bb.h + 'px' });
      this.ctx.clearRect(0, 0, this.W, this.H); this.setBBox(bb.x, bb.y, bb.w, bb.h);
    };
    pre.src = r.url;
  }
  show(b) {
    clearTimeout(this.exT);
    if (!b) { this.key = null; this.clear(); return; }
    const key = pvKey(b, this.o); this.key = key;
    const hit = PVR.get(key);
    if (hit) { this.placeExact(hit, key); return; }
    this.drawLive(b);                                                    // мгновенно
    this.exT = setTimeout(async () => {                                  // точный — когда движение остановилось
      const r = await layerFor(b, this.o);
      if (this.key !== key || !r || r.error) return;
      this.placeExact(r, key);
      const i = idx(b.id); for (const n of [S.blocks[i + 1], S.blocks[i + 2]]) if (n) layerFor(n, this.o);   // наперёд
    }, 140);
  }

  bind() {
    const el = this.el;
    el.addEventListener('wheel', e => { e.preventDefault(); const r = this.paneEl.getBoundingClientRect(); this.zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top); }, { passive: false });
    el.addEventListener('dblclick', e => { if (!e.target.closest('.floatbar')) this.fit(); });
    el.addEventListener('pointerdown', e => {
      if ((e.button !== 0 && e.button !== 1) || e.target.closest('.floatbar')) return;
      setOrient(this.o);
      if (e.target === this.hl && e.button === 0 && S.liveId != null) {
        if (S.playing) setPlaying(false);
        this.drag = { kind: 'layer', x: e.clientX, y: e.clientY, dx: 0, dy: 0 }; pushUndo();
      } else { this.drag = { kind: 'pan', x: e.clientX, y: e.clientY, tx: this.tx, ty: this.ty }; el.classList.add('panning'); }
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener('pointermove', e => {
      const drag = this.drag; if (!drag) return;
      if (drag.kind === 'pan') { this.tx = drag.tx + e.clientX - drag.x; this.ty = drag.ty + e.clientY - drag.y; this.fitted = false; this.apply(); return; }
      const fine = e.ctrlKey ? .2 : 1;
      let dx = (e.clientX - drag.x) / this.s * fine, dy = (e.clientY - drag.y) / this.s * fine;
      let gv = $('.snapv', this.world); if (!gv) { this.world.insertAdjacentHTML('beforeend', '<div class="snapv"></div>'); gv = $('.snapv', this.world); }
      let sv = false;
      if (this.bbox && !e.altKey) { const thr = 9 / this.s, cx = this.bbox.x + this.bbox.w / 2 + dx; if (Math.abs(cx - this.W / 2) < thr) { dx += this.W / 2 - cx; sv = true; } }
      gv.style.cssText = `left:${this.W / 2}px;width:${1.5 / this.s}px;opacity:${sv ? 1 : 0}`;
      drag.dx = dx; drag.dy = dy;
      this.layerEl.style.transform = `translate(${dx}px,${dy}px)`;
      this.hl.classList.add('drag');
      let rd = $('.drag-read', el); if (!rd) { el.insertAdjacentHTML('beforeend', '<div class="drag-read"></div>'); rd = $('.drag-read', el); }
      const m = parseMk(mkOf(blk(S.liveId), this.o));
      const nx = m.dx + Math.round(dx), ny = m.dy + Math.round(dy);
      rd.textContent = `X ${nx > 0 ? '+' : ''}${nx}   Y ${ny > 0 ? '+' : ''}${ny}`;
      const er = el.getBoundingClientRect(); rd.style.left = (e.clientX - er.left) + 'px'; rd.style.top = (e.clientY - er.top) + 'px';
    });
    const end = () => {
      const drag = this.drag; if (!drag) return; this.drag = null;
      el.classList.remove('panning');
      if (drag.kind !== 'layer') return;
      $('.drag-read', el)?.remove(); $$('.snapv', this.world).forEach(x => x.remove());
      this.hl.classList.remove('drag');
      const ddx = Math.round(drag.dx), ddy = Math.round(drag.dy);
      this.layerEl.style.transform = '';
      if (ddx || ddy) {
        const live = S.liveId, ids = S.sel.has(live) ? [...S.sel] : [live];
        if (!S.sel.has(live)) select(live, { seek: false });
        for (const id of ids) { const b = blk(id), m = parseMk(mkOf(b, this.o)); m.dx += ddx; m.dy += ddy; setOri(b, fmtMk(m), this.o); }
        setDirty(true); patchRows(ids); renderInspector(); updateLayer();
      } else { S.hi--; S.hist.pop(); }
    };
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
  }
}

// ── слои ──
function pvKey(b, o) { return [o, mkOf(b, o), b.text, OVR.map(eff).join(',')].join('\u0001'); }
function layerFor(b, o) {
  const k = pvKey(b, o);
  if (!PV.has(k)) {
    const patch = {}; for (const g of OVR) if (S.glob[g] != null) patch[g] = S.glob[g];
    PV.set(k, api.preview(mkOf(b, o), b.text, o, patch, S.file.fonts_dir).then(r => { if (!r || r.error) { PV.delete(k); if (r?.error) toast({ kind: 'err', title: 'Preview failed', text: r.error }); } else PVR.set(k, r); return r; }));
  }
  return PV.get(k);
}
function updateLayer() { const b = blk(S.liveId); panes().forEach(p => p.show(b)); }
async function loadFonts() {
  const mk = (name, file) => { const f = new FontFace(name, `url(/font/${encodeURIComponent(String(file).split(/[\\/]/).pop())})`); document.fonts.add(f); return f.load().catch(() => null); };
  await Promise.all([mk('SubReg', S.style.font_file), mk('SubBold', S.style.bold_file)]);
}
function activeAt(t) { const ms = t * 1000; return S.blocks.find(b => ms >= b.start && ms < b.end) || null; }
function updateLive() {
  const b = activeAt(S.t), id = b?.id ?? null;
  if (id === S.liveId) return;
  S.liveId = id;
  $$('.sb.live').forEach(r => r.classList.remove('live'));
  if (id != null) { const r = $(`.sb[data-id="${id}"]`); r?.classList.add('live'); if (S.playing) r?.scrollIntoView({ block: 'nearest' }); }
  if (!S.playing && id != null && S.sel.size <= 1 && id !== S.cur) select(id, { seek: false });
  updateLayer();
}

// ── таймлайн ──
const dur = () => video()?.dur || (S.blocks.length ? S.blocks[S.blocks.length - 1].end / 1000 : 1);
function seekTo(t) {
  S.t = clamp(t, 0, Math.max(0, dur() - 0.001));
  panes().forEach(p => { p.vid.currentTime = S.t; });
  updateHead(); updateLive();
}
function updateHead() {
  const h = $('#tlHead'); if (h) h.style.left = (S.t / dur() * 100) + '%';
  const tm = $('#tlTime'); if (tm) tm.innerHTML = `${tfmt(S.t)} <small>/ ${tfmt(dur())}</small>`;
}
function renderTiles() {
  const m = master(), box = $('#tlTiles'), st = m && S.strips[m.o], v = video(); if (!box) return;
  if (!st || !v) { box.innerHTML = ''; return; }
  const n = Math.max(4, Math.round(box.clientWidth / (box.clientHeight * v.w / v.h || 1)));
  box.innerHTML = Array.from({ length: n }, (_, i) => { const j = Math.min(st.n - 1, Math.floor((i + .5) / n * st.n)); return `<i style="background-image:url('${st.url}');background-size:${st.n * 100}% 100%;background-position:${st.n > 1 ? j / (st.n - 1) * 100 : 0}% 0"></i>`; }).join('');
}
function renderMarks() {
  const bl = $('#tlBlocks'), sl = $('#tlSel'); if (!bl) return;
  const D = dur() * 1000;
  bl.innerHTML = S.blocks.length > 1500 ? '' : S.blocks.map(b => `<i class="${S.sel.has(b.id) ? 's' : ''}" style="left:${b.start / D * 100}%;width:max(1px,calc(${(b.end - b.start) / D * 100}% - 1px))"></i>`).join('');
  sl.innerHTML = selBlocks().slice(0, 60).map(b => `<div class="tl-sel" style="left:${b.start / D * 100}%;width:${(b.end - b.start) / D * 100}%"></div>`).join('');
}
function bindTimeline() {
  const tl = $('#tl'); if (!tl) return;
  let on = false;
  const at = e => { const r = tl.getBoundingClientRect(); return clamp((e.clientX - r.left) / r.width, 0, 1) * dur(); };
  tl.addEventListener('pointerdown', e => { on = true; tl.setPointerCapture(e.pointerId); if (S.playing) setPlaying(false); seekTo(at(e)); });
  tl.addEventListener('pointermove', e => { if (on) seekTo(at(e)); });
  tl.addEventListener('pointerup', () => { on = false; });
  new ResizeObserver(debounce(renderTiles, 80)).observe(tl);
}
function setPlaying(p) {
  const m = master(); if (!m) return;
  S.playing = p;
  if (p) {
    panes().forEach(x => x.vid.play());
    let last = 0;
    const loop = ts => {
      if (!S.playing) return;
      S.t = m.vid.currentTime;
      if (ts - last > 400) { last = ts; for (const x of panes()) if (x !== m && Math.abs(x.vid.currentTime - S.t) > .08) x.vid.currentTime = S.t; }   // вертикальное видео не отстаёт
      updateHead(); updateLive(); requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  } else {
    panes().forEach(x => x.vid.pause());
    S.t = m.vid.currentTime; panes().forEach(x => { if (x !== m) x.vid.currentTime = S.t; });
    updateHead(); updateLive();
  }
  const pb = $('[data-act="play"]'); if (pb) pb.innerHTML = icon(p ? 'pause' : 'play', 17);
}

// ═══════════════════════════ INSPECTOR ═══════════════════════════
const FIELDS = {
  dx: { get: m => m.dx, set: (m, v) => { m.dx = v; }, def: () => 0, auto: m => !m.dx },
  dy: { get: m => m.dy, set: (m, v) => { m.dy = v; }, def: () => 0, auto: m => !m.dy },
  size: { get: m => eff('font_size') + (m.size || 0), set: (m, v) => { m.size = (v - eff('font_size')) || null; }, def: () => eff('font_size'), auto: m => !m.size },
  opacity: { get: m => m.opacity ?? eff('text_opacity'), set: (m, v) => { m.opacity = v === eff('text_opacity') ? null : v; }, def: () => eff('text_opacity'), auto: m => m.opacity == null },
  shadow: { get: m => m.shadow ?? eff('shadow_opacity'), set: (m, v) => { m.shadow = v === eff('shadow_opacity') ? null : v; if (v > 0) m.black = false; }, def: () => eff('shadow_opacity'), auto: m => m.shadow == null },
  plate_opacity: { get: m => m.plate_opacity ?? eff('plate_opacity'), set: (m, v) => { m.plate_opacity = v === eff('plate_opacity') ? null : v; m.plate = true; }, def: () => eff('plate_opacity'), auto: m => m.plate_opacity == null },
};
for (const g of G_KEYS) FIELDS[g] = { glob: true, get: () => eff(g), def: () => S.style[g], auto: () => S.glob[g] == null };

function fld(k, label, o = {}) {
  const F = FIELDS[k], m = parseMk(mkOf(cur()));
  const val = F.get(m), auto = F.auto(m);
  const tip = (o.tip || label) + (F.glob ? ' — global: all subtitles, all 2Stage renders (saved with Save)' : '') + ' · drag the label · Ctrl finer · double-click resets';
  return `<label class="fld ${auto ? 'auto' : ''} ${F.glob ? 'glob' : ''}" data-k="${k}" data-min="${o.min ?? -9999}" data-max="${o.max ?? 9999}" data-sens="${o.sens || .5}">
    <span class="fl" data-tip="${esc(tip)}">${esc(label)}</span><input type="text" inputmode="decimal" value="${val}" spellcheck="false"></label>`;
}
const eye = (k, on, tip) => `<button class="eye ${on ? 'on' : ''}" data-act="sw" data-k="${k}" data-tip="${tip || (on ? 'Turn off' : 'Turn on')}">${icon(on ? 'eye' : 'eyeoff', 14)}</button>`;
const tseg = (k, opts, val) => `<div class="tseg">${opts.map(([v, t]) => `<button class="${String(val) === String(v) ? 'on' : ''}" data-act="set" data-k="${k}" data-v="${v}">${t}</button>`).join('')}</div>`;

function renderInspector() {
  const el = $('#sideRight'), keep = $('#inspScroll')?.scrollTop || 0, b = cur();
  const foot = `<div class="side-foot"><button class="btn hov" id="saveBtn" data-act="save" data-tip="Write markers into the .srt" data-kb="Ctrl+S" ${S.file ? '' : 'disabled'}></button></div>`;
  if (!b) {
    el.innerHTML = `<div class="insp-h"><h3>Properties</h3></div><div class="side-scroll"></div>${foot}`;
    renderSaveBtn(); return;
  }
  const m = parseMk(mkOf(b)), multi = S.sel.size > 1;
  const sh = !m.black && m.shadow !== 0, presets = S.prefs.presets || [];
  const prev = S.blocks[idx(b.id) - 1];
  el.innerHTML = `
    <div class="insp-h"><h3>Properties ${multi ? `<span class="sel-note"> · ${S.sel.size} blocks</span>` : ''}</h3>
      <button class="ibtn sm" data-act="undo" data-tip="Undo" data-kb="Ctrl+Z">${icon('undo', 15)}</button>
      <button class="ibtn sm" data-act="redo" data-tip="Redo" data-kb="Ctrl+Shift+Z">${icon('redo', 15)}</button>
      <button class="ibtn sm" data-act="reset-all" data-tip="Clear markers of this version (H / V) in the selected blocks">${icon('reset', 15)}</button></div>
    <div class="side-scroll" id="inspScroll">
    <div class="sec"><div class="sec-h"><span class="sec-t">Text</span>${m.margin != null ? `<span class="sel-note" data-tip="Old marker \` N: bottom margin from the frame edge, px">bottom ${m.margin}px</span>` : ''}<span class="sp"></span>${tseg('black', [[false, 'White'], [true, 'Black']], m.black)}</div>
      <div class="frow c4u">${fld('opacity', 'Opacity', { min: 0, max: 100, sens: .4, tip: 'Text opacity (%N)' })}${fld('size', 'Size', { min: 8, max: 400, sens: .2, tip: 'Font size; standard + ^N' })}${fld('dx', 'X', { sens: 1, tip: 'Shift X, px (←N →N)' })}${fld('dy', 'Y', { sens: 1, tip: 'Shift Y, px (↑N ↓N)' })}</div>
      <div class="line"><div class="tseg"><button class="${m.bold ? 'on' : ''}" data-act="set" data-k="bold" data-v="${!m.bold}" data-tip="${m.bold ? 'SemiBold on (@) — click for Regular' : 'Regular — click for SemiBold (@)'}">Semibold</button></div></div></div>

    <div class="sec ${sh ? '' : 'off'}"><div class="sec-h"><button class="sec-t" data-act="sw" data-k="shadow">Shadow</button>${eye('shadow', sh, m.black ? 'Black text has no shadow (!)' : '')}<span class="sp"></span>${tseg('shadow_white', [[false, 'Black'], [true, 'White']], m.shadow_white)}</div>
      <div class="frow c4u">${fld('shadow', 'Opacity', { min: 0, max: 100, sens: .4, tip: 'Shadow opacity (#N)' })}${fld('shadow_blur', 'Blur', { min: 0, max: 40, sens: .1 })}${fld('shadow_x', 'X', { min: -40, max: 40, sens: .1, tip: 'Shadow offset X' })}${fld('shadow_y', 'Y', { min: -40, max: 40, sens: .1, tip: 'Shadow offset Y' })}</div>
</div>

    <div class="sec ${m.plate ? '' : 'off'}"><div class="sec-h"><button class="sec-t" data-act="sw" data-k="plate">Background</button>${eye('plate', m.plate)}<span class="sp"></span>${tseg('plate_white', [[false, 'Black'], [true, 'White']], m.plate_white)}</div>
      <div class="frow c4u">${fld('plate_opacity', 'Opacity', { min: 0, max: 100, sens: .4, tip: 'Plate opacity ([N])' })}${fld('plate_radius', 'Radius', { min: 0, max: 80, sens: .2 })}${fld('plate_pad_x', 'pX', { min: 0, max: 120, sens: .3, tip: 'Plate padding X' })}${fld('plate_pad_y', 'pY', { min: 0, max: 80, sens: .3, tip: 'Plate padding Y' })}</div>
</div>

    </div>
    <div class="insp-foot"><div class="frow-q"><span class="ql">Presets</span>
      <div class="line presets">${presets.map(p => `<button class="pchip" data-act="preset" data-id="${esc(p.id)}" data-tip="${esc(p.mk || 'no markers')} · right-click to delete">${icon(p.icon || 'bookmark', 12)}${esc(p.name)}</button>`).join('') || '<span class="cl">No presets yet</span>'}</div>
      <button class="ibtn sm" data-act="preset-save" data-tip="Save current markers as a preset">${icon('plus', 13)}</button></div>
    <div class="frow-q"><span class="ql">Quicks</span>
      <div class="qk">
        <button class="qbtn" data-act="like-prev" ${prev ? '' : 'disabled'} data-tip="Markers of the previous block">${icon('history', 12)}</button>
        <button class="qbtn" data-act="to-all" data-tip="Apply these markers to all blocks">${icon('checksq', 13)}</button>
        <button class="qbtn" data-act="copy-mk" data-tip="Copy markers" data-kb="Ctrl+C">${icon('copy', 13)}</button>
        <button class="qbtn" data-act="paste-mk" data-tip="Paste markers into the selected blocks" data-kb="Ctrl+V">${icon('paste', 13)}</button>
        <button class="qbtn" data-act="resettings" data-tip="Resettings: make these values the defaults for all subtitles (@SRT Markers.json)">${icon('gearrefresh', 12)}</button>
      </div></div></div>${foot}`;
  $('#inspScroll').scrollTop = keep;
  renderSaveBtn();
}
function renderSaveBtn() {
  const b = $('#saveBtn'); if (!b) return;
  b.innerHTML = `${S.dirty ? '<i class="dot"></i>' : icon('save', 16)}Save`;
  b.disabled = !S.file;
}
function liveMk() { }

// изменение поля -> во все выделенные блоки
function applyField(k, v, { live } = {}) {
  const F = FIELDS[k];
  if (F.glob) { if (v === S.style[k]) delete S.glob[k]; else S.glob[k] = v; }
  else for (const b of selBlocks()) { const m = parseMk(mkOf(b)); F.set(m, v); setOri(b, fmtMk(m)); }
  setDirty(true); patchRows([...S.sel]); liveMk(); updateLayer();
  if (!live) renderInspector();
}
function patchMarkers(fn) {
  pushUndo();
  for (const b of selBlocks()) { const m = parseMk(mkOf(b)); fn(m, b); setOri(b, fmtMk(m)); }
  setDirty(true); patchRows([...S.sel]); renderInspector(); updateLayer();
}
function setMk(ids, mk, whole = true) {
  pushUndo();
  for (const id of ids) { const b = blk(id); if (b) { if (whole) b.mk = canonFull(mk); else setOri(b, mk); } }
  setDirty(true); patchRows(ids); renderInspector(); updateLayer();
}
const fldParse = (f, text) => { const v = parseFloat(String(text).replace(',', '.')); return Number.isNaN(v) ? null : clamp(Math.round(v), +f.dataset.min, +f.dataset.max); };

// ═══════════════════════════ file ═══════════════════════════
async function confirmUnsaved() {
  if (!S.dirty) return true;
  return new Promise(res => {
    const m = openModal({ title: 'Save changes?', icon: 'save', body: `<p style="margin:0">Markers in <b>${esc(S.file?.name)}</b> are not saved yet.</p>`,
      foot: `<button class="btn" data-r="cancel">Cancel</button><button class="btn" data-r="discard">Don't save</button><button class="btn primary" data-r="save">${icon('save', 15)}Save</button>`,
      onClose: () => res(false) });
    m.el.addEventListener('click', async e => {
      const r = e.target.closest('[data-r]')?.dataset.r; if (!r) return;
      if (r === 'cancel') return m.close();
      if (r === 'save' && !(await doSave())) return;
      m.close(true); res(true);
    });
  });
}
async function openPath(p) {
  if (!p || !(await confirmUnsaved())) return;
  const r = await api.load(p); if (r) afterLoad(r);
}
function afterLoad(r) {
  if (r.error) return toast({ kind: 'warn', title: 'Not opened', text: r.error });
  if (S.playing) setPlaying(false);
  S.file = r; S.orient = r.orient || 'h'; S.blocks = r.blocks.map(b => ({ id: S.nextId++, mk: b.mk, start: b.start, end: b.end, text: b.text }));
  S.sel = new Set(); S.cur = null; S.anchor = null; S.hist = []; S.hi = -1; S.liveId = undefined; S.t = 0; S.strips = {}; PV.clear(); PVR.clear();
  loadFonts().then(() => updateLayer());
  setDirty(false);
  if (!r.srt_exists) toast({ kind: 'warn', title: 'No subtitles', text: `${r.name} not found next to the video` });
  else if (!Object.keys(r.videos).length) toast({ kind: 'warn', title: 'No video', text: 'No video with the same name — preview is off' });
  renderTop(); renderLeft(); renderStage();
  if (S.blocks.length) select(S.blocks[0].id); else renderInspector();
  const changed = r.blocks.filter(b => b.mk_raw && b.mk_raw !== b.mk).length;
  if (changed) toast({ title: 'Markers normalized', text: `${changed} block(s) will be written in the canonical order on Save` });
}
async function doSave() {
  if (!S.file) return false;
  const r = await api.save(S.blocks.map(b => ({ mk: b.mk, start: b.start, end: b.end, text: b.text })), Object.keys(S.glob).length ? S.glob : null);
  if (!r?.ok) { toast({ kind: 'err', title: 'Not saved', text: r?.msg }); return false; }
  S.style = r.style; S.glob = {}; S.file.srt_exists = true;
  setDirty(false); renderInspector();
  toast({ kind: 'good', title: 'Saved', text: S.file.name });
  return true;
}

// ═══════════════════════════ markers clipboard ═══════════════════════════
async function copyMk() {
  const b = cur(); if (!b) return;
  await api.clipboard_set(b.mk);
  toast({ kind: 'good', title: 'Markers copied', text: b.mk || '(no markers)' });
}
async function pasteMk() {
  if (!S.sel.size) return;
  let t = (await api.clipboard_get() || '').trim().split(/\r?\n/)[0].replace(/^\s*\d+\s*/, '');
  if (t && !hasMarkers(t)) return toast({ kind: 'warn', title: 'No markers in the clipboard', text: t.slice(0, 60) });
  const whole = hasHV(t);
  setMk([...S.sel], whole ? canonFull(t) : canon(t), whole);
  toast({ kind: 'good', title: `Markers pasted: ${S.sel.size}${whole ? '' : ' · ' + S.orient.toUpperCase()}`, text: (whole ? canonFull(t) : canon(t)) || '(cleared)' });
}

// ═══════════════════════════ block operations ═══════════════════════════
function delBlocks() {
  if (!S.sel.size) return;
  pushUndo();
  const first = Math.min(...[...S.sel].map(idx));
  S.blocks = S.blocks.filter(b => !S.sel.has(b.id));
  setDirty(true); S.sel.clear();
  renderLeft(); renderTop(); S.liveId = undefined; updateLive();
  const n = S.blocks[Math.min(first, S.blocks.length - 1)]; if (n) select(n.id); else { S.cur = null; renderInspector(); renderMarks(); }
}
function mergeBlocks() {
  const list = selBlocks(); if (list.length < 2) return;
  pushUndo();
  const f = list[0];
  f.start = Math.min(...list.map(b => b.start)); f.end = Math.max(...list.map(b => b.end));
  f.text = list.map(b => b.text).join(' ');
  S.blocks = S.blocks.filter(b => b === f || !S.sel.has(b.id));
  setDirty(true); S.liveId = undefined;
  renderLeft(); renderTop(); select(f.id, { seek: false }); updateLive();
}
function splitBlock() {
  const b = cur(); if (!b) return;
  const words = b.text.split(/\s+/).filter(Boolean);
  const tms = S.t * 1000;
  const at = tms > b.start + 20 && tms < b.end - 20 ? Math.round(tms) : Math.round((b.start + b.end) / 2);
  let a = b.text, c = b.text;
  if (words.length > 1) {
    const frac = (at - b.start) / (b.end - b.start), total = b.text.length;
    let best = 1, bd = 1e9, pos = 0;
    for (let i = 1; i < words.length; i++) { pos = words.slice(0, i).join(' ').length; const d = Math.abs(pos / total - frac); if (d < bd) { bd = d; best = i; } }
    a = words.slice(0, best).join(' '); c = words.slice(best).join(' ');
  }
  pushUndo();
  const nb = { id: S.nextId++, mk: b.mk, start: at, end: b.end, text: c };
  b.end = at; b.text = a;
  S.blocks.splice(idx(b.id) + 1, 0, nb);
  setDirty(true); S.liveId = undefined;
  renderLeft(); renderTop(); select(b.id, { seek: false }); updateLive(); renderMarks();
}

// ═══════════════════════════ modals / menus / toasts ═══════════════════════════
function openModal({ title, icon: ic, body, foot, onClose }) {
  const w = document.createElement('div'); w.className = 'modal-veil';
  w.innerHTML = `<div class="modal"><div class="modal-h">${ic ? `<span class="mi">${icon(ic, 18)}</span>` : ''}<h2>${esc(title)}</h2><button class="ibtn" data-close>${icon('x', 17)}</button></div><div class="modal-b">${body}</div>${foot ? `<div class="modal-f">${foot}</div>` : ''}</div>`;
  $('#overlayRoot').appendChild(w);
  let closed = false;
  const close = silent => { if (closed) return; closed = true; w.classList.add('out'); setTimeout(() => w.remove(), 200); if (!silent) onClose?.(); };
  w.addEventListener('pointerdown', e => { if (e.target === w) close(); });
  w.addEventListener('click', e => { if (e.target.closest('[data-close]')) close(); });
  w._close = close;
  return { el: w, close };
}
function closeTop() {
  const m = $$('.menu'); if (m.length) { m.forEach(x => x.remove()); return true; }
  const v = $$('.modal-veil:not(.out)'); if (v.length) { v[v.length - 1]._close(); return true; }
  return false;
}
function menu(x, y, items) {
  $$('.menu').forEach(m => m.remove());
  const m = document.createElement('div'); m.className = 'menu';
  m.innerHTML = items.map((it, i) => it === '-' ? '<hr>' : `<button data-i="${i}" class="${it.danger ? 'danger' : ''}" ${it.disabled ? 'disabled style="opacity:.4"' : ''}>${icon(it.icon || 'dots', 15)}<span>${esc(it.label)}</span>${it.kb ? `<kbd>${it.kb}</kbd>` : ''}</button>`).join('');
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, innerWidth - r.width - 8) + 'px'; m.style.top = (y + r.height > innerHeight - 8 ? y - r.height : y) + 'px';
  m.addEventListener('click', e => { const b = e.target.closest('button[data-i]'); if (!b || b.disabled) return; m.remove(); items[+b.dataset.i].fn?.(); });
  setTimeout(() => document.addEventListener('pointerdown', function h(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('pointerdown', h); } }), 0);
}
function toast({ title, text = '', kind = 'info', timeout = 3600 }) {
  const el = document.createElement('div'); el.className = `toast ${kind}`;
  el.innerHTML = `<span class="ti">${icon({ good: 'check', err: 'alert', warn: 'alert', info: 'info' }[kind] || 'info', 15)}</span><div class="tt"><b>${esc(title)}</b>${text ? `<small>${esc(text)}</small>` : ''}</div><button class="ibtn sm">${icon('x', 13)}</button>`;
  $('#toasts').appendChild(el);
  const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 250); };
  $('button', el).onclick = close; setTimeout(close, timeout);
  const all = $$('.toast'); if (all.length > 4) all[0].remove();
}
function promptModal(title, value, cb) {
  const m = openModal({ title, body: `<input class="input" id="pmIn" value="${esc(value)}" spellcheck="false">`, foot: `<button class="btn" data-close>Cancel</button><button class="btn primary" id="pmOk">OK</button>` });
  const inp = $('#pmIn', m.el); inp.focus(); inp.select();
  const ok = () => { const v = inp.value.trim(); m.close(true); if (v) cb(v); };
  $('#pmOk', m.el).onclick = ok;
  inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') ok(); if (e.key === 'Escape') m.close(); });
}
function blockMenu(e) {
  const n = S.sel.size, b = cur();
  menu(e.clientX, e.clientY, [
    { label: n > 1 ? `Paste markers → ${n}` : 'Paste markers', icon: 'paste', kb: 'Ctrl+V', fn: pasteMk },
    { label: 'Copy markers', icon: 'copy', kb: 'Ctrl+C', disabled: !b, fn: copyMk },
    { label: 'Clear markers', icon: 'eraser', fn: () => setMk([...S.sel], '') },
    '-',
    { label: 'Merge', icon: 'merge', kb: 'Ctrl+M', disabled: n < 2, fn: mergeBlocks },
    { label: 'Split at playhead', icon: 'scissors', kb: 'Ctrl+K', disabled: n !== 1, fn: splitBlock },
    { label: n > 1 ? `Delete ${n}` : 'Delete', icon: 'trash', kb: 'Del', danger: true, fn: delBlocks },
  ]);
}

// ═══════════════════════════ actions ═══════════════════════════
const ACT = {
  'win-min': () => api.win_min(),
  'win-max': async () => { S.win.max = !!(await api.win_max()); document.body.classList.toggle('maxed', S.win.max); renderWinCtl(); },
  'win-close': async () => { if (await confirmUnsaved()) api.win_close(); },
  settings: el => { const r = el.getBoundingClientRect(), th = S.prefs.theme || 'dark';
    const set = t => () => { setPref({ theme: t }); applyTheme(); renderTop(); };
    menu(r.right - 200, r.bottom + 6, [
      { label: 'Dark theme', icon: th === 'dark' ? 'check' : 'moon', fn: set('dark') },
      { label: 'Light theme', icon: th === 'light' ? 'check' : 'sun', fn: set('light') },
      { label: 'Like Windows', icon: th === 'system' ? 'check' : 'monitor', fn: set('system') }]); },
  theme: () => { const o = ['dark', 'light', 'system']; setPref({ theme: o[(o.indexOf(S.prefs.theme || 'dark') + 1) % 3] }); applyTheme(); renderTop(); },
  'brand-menu': el => { const r = el.getBoundingClientRect(); menu(r.left, r.bottom + 6, [
    { label: 'Open file…', icon: 'folderopen', kb: 'Ctrl+O', fn: ACT.open },
    { label: 'Show in Explorer', icon: 'folder', disabled: !S.file, fn: ACT.reveal },
    { label: 'Reload from disk', icon: 'refresh', disabled: !S.file, fn: () => openPath(S.file.srt) },
    '-', { label: 'Save', icon: 'save', kb: 'Ctrl+S', disabled: !S.file, fn: doSave }]); },
  open: async () => { if (!(await confirmUnsaved())) return; const r = await api.open_dialog(); if (r) afterLoad(r); },
  reveal: () => api.reveal(),
  save: () => doSave(),
  orient: el => setOrient(el.dataset.o),
  'copy-row': async el => { const b = blk(+el.closest('.sb').dataset.id); if (!b || !b.mk) return; await api.clipboard_set(b.mk); toast({ kind: 'good', title: 'Markers copied', text: b.mk }); },
  play: () => setPlaying(!S.playing),
  'zoom-in': () => { const p = activePane(); if (!p) return; const [w, h] = p.paneSize(); p.zoomAt(1.4, w / 2, h / 2, true); },
  'zoom-out': () => { const p = activePane(); if (!p) return; const [w, h] = p.paneSize(); p.zoomAt(1 / 1.4, w / 2, h / 2, true); },
  fit: () => panes().forEach(p => p.fit()),
  loupe: () => { const p = activePane(); if (p?.bbox) p.zoomTo(p.bbox.x, p.bbox.y, p.bbox.w, p.bbox.h); },
  focus: () => { document.body.classList.toggle('focus'); $$('[data-act="focus"]').forEach(b => b.classList.toggle('on', document.body.classList.contains('focus'))); },
  undo: () => undo(-1), redo: () => undo(1),
  set: el => { let v = el.dataset.v; v = v === 'true' ? true : v === 'false' ? false : v; const k = el.dataset.k; patchMarkers(m => { m[k] = v; if (k === 'plate_white') m.plate = true; if (k === 'black' && v && m.shadow === 0) m.shadow = null; }); },
  sw: el => {
    const k = el.dataset.k, m0 = parseMk(mkOf(cur()));
    if (k === 'shadow') { const on = !(!m0.black && m0.shadow !== 0); patchMarkers(m => { if (on) { m.shadow = null; m.black = false; } else m.shadow = 0; }); }
    else if (k === 'plate') patchMarkers(m => { m.plate = !m0.plate; if (!m.plate) { m.plate_white = false; m.plate_opacity = null; } });
  },
  'reset-all': () => setMk([...S.sel], '', false),
  'copy-mk': copyMk, 'paste-mk': pasteMk,
  'like-prev': () => { const p = S.blocks[idx(S.cur) - 1]; if (p) setMk([...S.sel], p.mk); },
  'to-all': () => { const b = cur(); if (!b) return; setMk(S.blocks.map(x => x.id), b.mk); toast({ kind: 'good', title: `Applied to all ${S.blocks.length} blocks`, text: b.mk || '(no markers)' }); },
  preset: el => { const p = (S.prefs.presets || []).find(x => x.id === el.dataset.id); if (!p) return; const pm = parseMk(splitHV(p.mk)[S.orient]); patchMarkers(m => { for (const [k, v] of Object.entries(pm)) if (v !== null && v !== false && v !== 0) m[k] = v; if (pm.shadow === 0) m.shadow = 0; }); },
  'preset-save': () => { const b = cur(); if (!b) return; promptModal(`Preset name for “${mkOf(b) || 'no markers'}”`, '', name => { const presets = [...(S.prefs.presets || []), { id: 'p' + Date.now(), name, mk: mkOf(b), icon: 'bookmark' }]; setPref({ presets }); renderInspector(); }); },
  resettings: () => {
    const b = cur(); if (!b) return;
    const m = parseMk(mkOf(b));
    const vals = { font_size: eff('font_size') + (m.size || 0), text_opacity: m.opacity ?? eff('text_opacity'), shadow_opacity: m.shadow ?? eff('shadow_opacity'), plate_opacity: m.plate_opacity ?? eff('plate_opacity') };
    for (const g of G_KEYS) vals[g] = eff(g);
    const changes = Object.entries(vals).filter(([k, v]) => v !== S.style[k]);
    if (!changes.length) return toast({ title: 'Nothing to change', text: 'These values already are the defaults' });
    const md = openModal({ title: 'Make these the defaults?', icon: 'gearrefresh',
      body: `<p style="margin:0 0 10px">Written to <b>@SRT Markers.json</b> and used by every 2Stage render for blocks without these markers:</p>
        <div class="arch-list">${changes.map(([k, v]) => `<div><span class="mono" style="flex:1">${k}</span><span class="muted">${S.style[k]}</span>${icon('arrow', 12)}<b>${v}</b></div>`).join('')}</div>`,
      foot: `<button class="btn" data-close>Cancel</button><button class="btn primary" id="rsOk">${icon('check', 15)}Save defaults</button>` });
    $('#rsOk', md.el).onclick = async () => {
      const r = await api.resettings(Object.fromEntries(changes)); if (!r?.ok) return toast({ kind: 'err', title: 'Not saved', text: r?.msg });
      md.close(true); S.style = r.style; S.glob = {};
      patchMarkers(mm => { mm.size = null; mm.opacity = null; mm.shadow = mm.shadow === 0 ? 0 : null; mm.plate_opacity = null; });
      toast({ kind: 'good', title: 'Defaults updated', text: `${changes.length} values → @SRT Markers.json` });
    };
  },
};

document.addEventListener('click', e => {
  const a = e.target.closest('[data-act]'); if (!a || a.disabled) return;
  const fn = ACT[a.dataset.act]; if (fn) fn(a, e);
});
document.addEventListener('contextmenu', e => {
  const r = e.target.closest('.sb');
  if (r && !e.target.closest('.editing')) { e.preventDefault(); const id = +r.dataset.id; if (!S.sel.has(id)) select(id); return blockMenu(e); }
  const pc = e.target.closest('.pchip');
  if (pc) { e.preventDefault(); return menu(e.clientX, e.clientY, [{ label: 'Delete preset', icon: 'trash', danger: true, fn: () => { setPref({ presets: (S.prefs.presets || []).filter(p => p.id !== pc.dataset.id) }); renderInspector(); } }]); }
  if (!e.target.closest('input, .editing')) e.preventDefault();
});

// ── список: клик, Shift/Ctrl, протяжка мышью, двойной клик ──
let lsel = null;
document.addEventListener('pointerdown', e => {
  const r = e.target.closest('#blist .sb'); if (!r || e.button !== 0 || e.target.closest('.editing, .sb-copy')) return;
  const id = +r.dataset.id;
  if (e.shiftKey) select(id, { range: true, add: e.ctrlKey });
  else if (e.ctrlKey) select(id, { add: true });
  else { select(id); lsel = { from: id }; }
});
document.addEventListener('pointermove', e => {
  if (!lsel || !(e.buttons & 1)) { lsel = null; return; }
  const r = document.elementFromPoint(e.clientX, e.clientY)?.closest('#blist .sb'); if (!r) return;
  const id = +r.dataset.id; if (id === lsel.last) return; lsel.last = id;
  const a = idx(lsel.from), b = idx(id);
  S.sel = new Set(S.blocks.slice(Math.min(a, b), Math.max(a, b) + 1).map(x => x.id));
  paintSel(); renderMarks();
});
document.addEventListener('pointerup', () => { if (lsel?.last != null && lsel.last !== lsel.from) renderInspector(); lsel = null; });
document.addEventListener('dblclick', e => {
  const ed = e.target.closest('#blist .ed'); if (ed) return editField(ed);
  const fl = e.target.closest('#sideRight .fld .fl');
  if (fl) { const f = fl.closest('.fld'), F = FIELDS[f.dataset.k]; pushUndo(); applyField(f.dataset.k, F.def()); }
});

// ── поля инспектора: ввод, Enter, колесо, стрелки, протяжка по подписи ──
document.addEventListener('change', e => {
  const f = e.target.closest?.('#sideRight .fld[data-k]'); if (!f || e.target.tagName !== 'INPUT') return;
  const v = fldParse(f, e.target.value); pushUndo(); applyField(f.dataset.k, v ?? FIELDS[f.dataset.k].def());
});
document.addEventListener('keydown', e => {
  const f = e.target.closest?.('#sideRight .fld[data-k]'); if (!f || e.target.tagName !== 'INPUT') return;
  e.stopPropagation();
  if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
  if (e.key === 'Escape') { e.target.blur(); }
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault(); if (!f._u) { pushUndo(); f._u = 1; }
    const v = fldParse(f, (parseFloat(e.target.value) || 0) + (e.shiftKey ? 10 : 1) * (e.key === 'ArrowUp' ? 1 : -1));
    e.target.value = v; f.classList.remove('auto'); applyField(f.dataset.k, v, { live: true });
    clearTimeout(f._t); f._t = setTimeout(() => { f._u = 0; renderInspector(); }, 600);
  }
}, true);
document.addEventListener('wheel', e => {
  const f = e.target.closest?.('#sideRight .fld[data-k]'); if (!f) return;
  e.preventDefault();
  const inp = $('input', f); if (!f._u) { pushUndo(); f._u = 1; }
  const v = fldParse(f, (parseFloat(inp.value) || 0) + (e.shiftKey ? 10 : 1) * (e.deltaY < 0 ? 1 : -1));
  inp.value = v; f.classList.remove('auto'); applyField(f.dataset.k, v, { live: true });
  clearTimeout(f._t); f._t = setTimeout(() => { f._u = 0; renderInspector(); }, 600);
}, { passive: false });
document.addEventListener('pointerdown', e => {
  const fl = e.target.closest?.('#sideRight .fld[data-k] .fl'); if (!fl || e.button !== 0) return;
  const f = fl.closest('.fld'), inp = $('input', f), sens = +f.dataset.sens || .5;
  e.preventDefault(); fl.setPointerCapture(e.pointerId);
  let ax = e.clientX, av = parseFloat(inp.value) || 0, fine = e.ctrlKey, moved = false;
  document.body.classList.add('scrubbing');
  const mv = ev => {
    if (!!ev.ctrlKey !== fine) { fine = !!ev.ctrlKey; ax = ev.clientX; av = parseFloat(inp.value) || 0; }
    const dx = ev.clientX - ax; if (Math.abs(dx) < 1 && !moved) return;
    if (!moved) pushUndo(); moved = true;
    const v = fldParse(f, av + dx * sens * (fine ? .1 : 1)); inp.value = v; f.classList.remove('auto');
    applyField(f.dataset.k, v, { live: true });
  };
  const up = () => {
    fl.removeEventListener('pointermove', mv); fl.removeEventListener('pointerup', up); fl.removeEventListener('pointercancel', up);
    document.body.classList.remove('scrubbing');
    if (moved) renderInspector(); else inp.focus();
  };
  fl.addEventListener('pointermove', mv); fl.addEventListener('pointerup', up); fl.addEventListener('pointercancel', up);
});

// ── своя шапка окна ──
let lastHdr = 0;
document.addEventListener('pointerdown', e => {
  if (e.button !== 0) return;
  const edge = e.target.closest?.('#rsz i'); if (edge) { e.preventDefault(); api.win_size(edge.dataset.edge); return; }
  if (!e.target.closest?.('.topbar') || e.target.closest('button, input, a, .chip, .menu')) return;
  const now = Date.now(); if (now - lastHdr < 350) { lastHdr = 0; ACT['win-max'](); return; }
  lastHdr = now; api.win_drag();
});

// ── подсказки ──
let tipT = 0;
const tipEl = () => $('#tooltip');
document.addEventListener('mouseover', e => {
  const el = e.target.closest('[data-tip]'); clearTimeout(tipT);
  if (!el) { tipEl().classList.remove('on'); return; }
  tipT = setTimeout(() => {
    if (!el.isConnected || document.body.classList.contains('scrubbing')) return;
    const t = tipEl(), r = el.getBoundingClientRect();
    t.innerHTML = `${esc(el.dataset.tip)}${el.dataset.kb ? `<span class="kb">${esc(el.dataset.kb)}</span>` : ''}`; t.classList.add('on');
    const tr = t.getBoundingClientRect();
    let x = r.left + r.width / 2 - tr.width / 2, y = r.bottom + 8;
    if (y + tr.height > innerHeight - 8) y = r.top - tr.height - 8;
    t.style.left = clamp(x, 8, innerWidth - tr.width - 8) + 'px'; t.style.top = y + 'px';
  }, 450);
});
document.addEventListener('pointerdown', () => { clearTimeout(tipT); tipEl().classList.remove('on'); });

// ── клавиатура ──
let nudgeT = null;
document.addEventListener('keydown', e => {
  if (window.SaturniDebug && (SaturniDebug.owns(e) || SaturniDebug.active)) return;     // клавиши у отладки
  const t = e.target, typing = t.matches('input, textarea, [contenteditable="true"], [contenteditable="plaintext-only"]');
  const k = e.key, ctrl = e.ctrlKey || e.metaKey, lk = k.toLowerCase();
  if (k === 'Escape') { if (closeTop()) return e.preventDefault(); if (typing) return t.blur(); if (document.body.classList.contains('focus')) return ACT.focus(); return; }
  if (ctrl && ['s', 'ы'].includes(lk)) { e.preventDefault(); return doSave(); }
  if (ctrl && ['o', 'щ'].includes(lk)) { e.preventDefault(); return ACT.open(); }
  if (ctrl && ['t', 'е'].includes(lk)) { e.preventDefault(); return ACT.theme(); }
  if ($('.modal-veil:not(.out)') || typing || !S.file) return;
  if (ctrl && ['z', 'я'].includes(lk)) { e.preventDefault(); return undo(e.shiftKey ? 1 : -1); }
  if (ctrl && ['y', 'н'].includes(lk)) { e.preventDefault(); return undo(1); }
  if (ctrl && ['c', 'с'].includes(lk)) { if (getSelection().toString()) return; e.preventDefault(); return copyMk(); }
  if (ctrl && ['v', 'м'].includes(lk)) { e.preventDefault(); return pasteMk(); }
  if (ctrl && ['a', 'ф'].includes(lk)) { e.preventDefault(); S.sel = new Set(S.blocks.map(b => b.id)); paintSel(); renderInspector(); renderMarks(); return; }
  if (ctrl && ['m', 'ь'].includes(lk)) { e.preventDefault(); return mergeBlocks(); }
  if (ctrl && ['k', 'л'].includes(lk)) { e.preventDefault(); return splitBlock(); }
  if (ctrl) return;
  if (e.altKey && k.startsWith('Arrow')) {
    e.preventDefault(); if (!S.sel.size) return;
    const st = e.shiftKey ? 25 : 5; if (!nudgeT) pushUndo();
    for (const b of selBlocks()) { const m = parseMk(mkOf(b)); if (k === 'ArrowLeft') m.dx -= st; if (k === 'ArrowRight') m.dx += st; if (k === 'ArrowUp') m.dy -= st; if (k === 'ArrowDown') m.dy += st; setOri(b, fmtMk(m)); }
    setDirty(true); patchRows([...S.sel]); liveMk(); updateLayer();
    clearTimeout(nudgeT); nudgeT = setTimeout(() => { nudgeT = null; renderInspector(); }, 400); return;
  }
  if (k === ' ') { e.preventDefault(); return setPlaying(!S.playing); }
  if (k === 'ArrowDown' || k === 'ArrowUp') { e.preventDefault(); const i = idx(S.cur) + (k === 'ArrowDown' ? 1 : -1); const b = S.blocks[clamp(i, 0, S.blocks.length - 1)]; if (b) select(b.id, { range: e.shiftKey }); return; }
  if (k === 'ArrowLeft' || k === 'ArrowRight') { e.preventDefault(); if (S.playing) setPlaying(false); const fps = video()?.fps || 25; return seekTo(S.t + (k === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 1 : 1 / fps)); }
  if (k === 'Delete') return delBlocks();
  if (k === '\\') return ACT.focus();
  if (['f', 'а'].includes(lk)) return ACT.fit();
  if (['z', 'я'].includes(lk)) return ACT.loupe();
  if (k === 'Home') return seekTo(0);
});

// ── drag & drop ──
let dragDepth = 0;
document.addEventListener('dragenter', e => { if (![...(e.dataTransfer?.types || [])].includes('Files')) return; dragDepth++; $('#dropVeil').classList.add('on'); $('#dvIc').innerHTML = icon('folderopen', 30); });
document.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('#dropVeil').classList.remove('on'); });
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => { e.preventDefault(); dragDepth = 0; $('#dropVeil').classList.remove('on'); });

// ═══════════════════════════ START ═══════════════════════════
let booted = false;
async function boot() {
  if (booted || !window.pywebview?.api?.init) return;
  booted = true; API = window.pywebview.api;
  const r = await API.init();
  S.prefs = r.prefs; S.style = r.style; S.base = r.base;
  document.body.classList.add('custom-tb');
  applyTheme(); renderTop(); renderWinCtl(); renderLeft(); renderStage(); renderInspector();
  if (window.SaturniDebug && window.__subs) SaturniDebug.init({ api: (n, ...a) => window.__subs.studio[n](...a),   // Debug живёт в Api Studio
    app: 'Saturni · Subs', context: () => 'Move' + (S.file ? ' · ' + S.file.name : ''), gear: '[data-act="settings"]' });
  api.win_state().then(w => { if (w) { S.win.max = !!w.max; document.body.classList.toggle('maxed', S.win.max); renderWinCtl(); } });
  requestAnimationFrame(() => document.body.classList.remove('booting'));
  if (r.start_file) { const f = await api.load(r.start_file); if (f && !f.error) afterLoad(f); }
}
window.addEventListener('pywebviewready', boot);
if (window.pywebview?.api?.init) boot();
// отладка в обычном браузере: python "# Saturni · Subs Move.pyw" --dev -> http://127.0.0.1:8766/?dev
if (new URLSearchParams(location.search).has('dev')) setTimeout(() => {
  if (booted) return;
  const rpc = async (k, a) => (await fetch('/rpc/' + k, { method: 'POST', body: JSON.stringify(a) })).json();
  window.pywebview = { api: new Proxy({}, { get: (_, k) => (...a) => rpc(k, a) }) };
  window.__dbg = { S, P, blk, geom, layerFor, PVR, pvKey, parseMk, mkOf, eff, select, setPlaying, seekTo };
  boot();
  setInterval(async () => { const ev = await rpc('__events', []); if (ev.length) window.__emit(ev); }, 250);
}, 300);
