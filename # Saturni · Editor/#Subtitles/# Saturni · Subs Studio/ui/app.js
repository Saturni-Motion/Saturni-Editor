// app.js — Saturni · Subs Studio: список титров (своя каретка у каждого + мини-волна + голосовая правка),
// видео, таймлайн в духе Subtitle Edit, панель чата с Claude, настройки цветов, модуль Saturni · Debug.
// Хоткеи — из Settings.xml Subtitle Edit Saturni.
"use strict";

// ═══════════════════════════ мост к Python ═══════════════════════════
const DEV = location.search.includes("dev");
function api(name, ...args) {
  if (DEV) return fetch("/rpc/" + name, { method: "POST", body: JSON.stringify(args) }).then(r => r.json());
  return window.pywebview.api[name](...args);
}
const handlers = {};
window.__emit = evs => {
  for (const e of evs) {
    if (window.SaturniDebug && SaturniDebug.handle(e.type, e.data)) continue;
    if (/^(rec|level|asr_text)$/.test(e.type) && e.data && chatVoice(e.type, e.data)) continue;
    (handlers[e.type] || (() => {}))(e.data);
  }
};
function on(type, fn) { handlers[type] = fn; }

// ═══════════════════════════ утилиты ═══════════════════════════
const $ = s => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function fmt(ms, full) {
  ms = Math.max(0, Math.round(ms));
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60, x = ms % 1000;
  const mm = h ? `${h}:${String(m).padStart(2, "0")}` : String(m);
  return `${mm}:${String(s).padStart(2, "0")}${full === false ? "" : "." + String(x).padStart(3, "0")}`;
}
function parseTime(str) {
  str = String(str).trim().replace(",", ".");
  if (!str) return null;
  const p = str.split(":").map(Number);
  if (p.some(isNaN)) return null;
  let s = 0;
  for (const v of p) s = s * 60 + v;
  return Math.round(s * 1000);
}
let _uid = 0;
const newId = () => `u${Date.now().toString(36)}${(_uid++).toString(36)}`;

const ICONS = {
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  prev: '<path d="M15 6l-6 6 6 6"/>', next: '<path d="M9 6l6 6-6 6"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  replace: '<path d="M4 8h12l-3-3M20 16H8l3 3"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  play: '<path d="M7 5l12 7-12 7z" fill="currentColor"/>', pause: '<path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor" stroke="none"/>',
  rew: '<path d="M11 6l-7 6 7 6zM20 6l-7 6 7 6z"/>', ffw: '<path d="M13 6l7 6-7 6zM4 6l7 6-7 6z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  up: '<path d="M6 15l6-6 6 6"/>', down: '<path d="M6 9l6 6 6-6"/>',
  send: '<path d="M19 4.5V11a4 4 0 0 1-4 4H5.5"/><path d="M9.5 10.5 5 15l4.5 4.5"/>', archive: '<path d="M3 5h18v4H3zM5 9v10h14V9M10 13h4"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', mergeUp: '<path d="M8 11l4-4 4 4"/>', mergeDown: '<path d="M8 13l4 4 4-4"/>',
  chev: '<path d="M7 10l5 5 5-5"/>',
  disk: '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8.5 4v5h6V4M8 20v-6h8v6"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
};
const icon = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[n] || ""}</svg>`;
function paintIcons(root = document) { root.querySelectorAll("[data-ic]").forEach(i => { i.innerHTML = icon(i.dataset.ic); }); }

function toast(msg, kind = "", ms = 3200) {
  const t = el("div", "toast " + kind, esc(msg));
  $("#toasts").append(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, ms);
}

// ═══════════════════════════ настройки и цвета ═══════════════════════════
const COLOR_KEYS = [            // [переменная, подпись]
  ["accent", "Accent"], ["accent-2", "Accent 2"], ["mark", "Carets & wave marks"], ["playhead", "Playhead"],
  ["note", "Voice edit text & mic"], ["hoverline", "Wave hover line"], ["wave", "Waveform"], ["good", "Changed cues"],
  ["rec", "Recording"], ["bg", "Window background"], ["panel", "Panels"], ["panel-2", "Fields"], ["stage", "Timeline background"],
  ["tl-cue", "Subtitles on the timeline"],
  ["text", "Text"], ["text-2", "Secondary text"],
];
const SET_DEFAULTS = { holdButton: 3, magnetPx: 10, bridgeMs: 200, seekOnSelect: true, followPlayback: true, listFont: 13.5, caretAtEnd: false,
  waveStyle: "solid", waveBar: 3, waveGap: 2, waveRound: true, waveSeg: 3, waveSegGap: 1,
  textStyle: "outline", noteStyle: "outline" };
const PAL = {};
function readPal() {
  const cs = getComputedStyle(document.documentElement);
  for (const k of ["wave", "mark", "playhead", "hoverline", "note", "accent", "accent-2", "good", "text", "muted", "panel-2", "line-2", "faint", "tl-cue"])
    PAL[k] = cs.getPropertyValue("--" + k).trim();
}
function applyColors(colors) {
  const st = document.documentElement.style;
  for (const [k] of COLOR_KEYS) st.removeProperty("--" + k);
  for (const [k, v] of Object.entries(colors || {})) if (v) st.setProperty("--" + k, v);
  readPal(); repaintAll();
}
function applySettings() {
  document.documentElement.style.setProperty("--list-font", (S.set.listFont || 13.5) + "px");
  // вид полей: обводка или серая заливка без обводки — у текста титра и отдельно у правки с микрофоном
  document.body.classList.toggle("ta-fill", S.set.textStyle === "fill");
  document.body.classList.toggle("note-fill", S.set.noteStyle === "fill");
  window.SaturniDebug && SaturniDebug.setHoldButton(S.set.holdButton);
}
function repaintAll() { for (const [id, r] of rows) { r.waveDirty = true; if (r.visible) drawMini(cueById(id), r); } drawTl(); }

// ═══════════════════════════ состояние ═══════════════════════════
const S = {
  file: null, cues: [], byId: new Map(),
  sel: new Set(), cur: null, anchor: null,
  hl: new Set(), dirty: false, hash: null,
  peaks: null, rate: 200, dur: 0,
  undo: [], redo: [], typing: null,
  busy: false, rec: null, waiting: new Set(), partial: null,
  view: { t0: 0, pps: 120 },
  prefs: {}, set: { ...SET_DEFAULTS }, claude: null,
};
const video = $("#video");
const rows = new Map();          // id -> {row, ...refs}

function reindex() { S.byId = new Map(S.cues.map(c => [c.id, c])); S.cues.forEach((c, i) => { c._i = i; }); }
const cueById = id => S.byId.get(id);
const curCue = () => cueById(S.cur);
// после перехода к титру видео стоит на его первом кадре (чуть позже начала), а время считается ровно началом титра
const vt = () => {
  if (!video.src) return S.vtFake || 0;
  const t = (video.currentTime || 0) * 1000;
  return S.seekShow != null && video.paused && Math.abs(t - S.seekAt) < 2 ? S.seekShow : t;
};
// hist — прежние правки титра: [{note, what (как Claude понял), at}]; why — почему последняя не сделана
function mkCue(o) { return { id: o.id || newId(), mk: o.mk || "", start: o.start, end: o.end, text: o.text || "", note: o.note || "", caret: o.caret || null, mark: o.mark || null, hist: o.hist || [], why: o.why || "" }; }

// ── undo / redo (снимки) ──
function snap() { return JSON.stringify({ cues: S.cues.map(({ _i, ...c }) => c), sel: [...S.sel], cur: S.cur }); }
function pushUndo() { S.undo.push(snap()); if (S.undo.length > 300) S.undo.shift(); S.redo = []; }
function restore(json) {
  const d = JSON.parse(json);
  S.cues = d.cues.map(mkCue); reindex();
  S.sel = new Set(d.sel.filter(id => S.byId.has(id))); S.cur = S.byId.has(d.cur) ? d.cur : null;
  changed(true);
}
function undo() { if (!S.undo.length) return; S.redo.push(snap()); restore(S.undo.pop()); }
function redo() { if (!S.redo.length) return; S.undo.push(snap()); restore(S.redo.pop()); }

let pendTimer = null;
function changed(structural, ids) {
  if (structural) renderList(); else (ids || []).forEach(updateRow);
  S.dirty = true;
  updateTop(); drawTl();
  clearTimeout(pendTimer); pendTimer = setTimeout(savePending, 500);
}
function touch(id) { if (S.hl.delete(id)) { const r = rows.get(id); r && r.row.classList.remove("hl"); } }
// неприменённое храним рядом с файлом (sessions/…/pending.json): ручные правки, голосовые правки, их история
// и подсветку изменённого — всё переживает закрытие окна, пока не применено (или 30 дней без открытия)
function savePending() {
  if (!S.file) return Promise.resolve();
  api("set_dirty", S.dirty);
  const keep = S.dirty || S.hl.size || S.cues.some(c => c.note.trim() || c.hist.length);
  const data = keep ? { dirty: S.dirty, hl: [...S.hl], cues: S.cues.map(({ _i, ...c }) => c) } : null;
  return api("pending_save", data);
}
function markDirty() { S.dirty = true; updateTop(); clearTimeout(pendTimer); pendTimer = setTimeout(savePending, 600); }

// ═══════════════════════════ загрузка файла ═══════════════════════════
async function openPath(p) { const r = await api("load", p); if (r) loadResult(r); }
async function openDialog() { await flushBeforeLeave(); const r = await api("open_dialog"); if (r) loadResult(r); }
async function navFile(d) {
  if (!S.file) return;
  await flushBeforeLeave();
  const r = await api("nav", d);
  if (r && r.edge) return toast(d < 0 ? "This is the first file in the folder" : "This is the last file in the folder");
  if (r) loadResult(r);
}
async function flushBeforeLeave() { if (S.rec) await stopRec(); clearTimeout(pendTimer); await savePending(); }

function loadResult(r) {
  if (r.error) return toast(r.error, "err");
  S.file = r; S.hash = r.hash; S.undo = []; S.redo = []; S.dirty = false;
  S.cues = r.cues.map(mkCue);
  S.hl = new Set(r.highlight || []);
  const p = r.pending;
  if (p && p.cues) {
    if (!p.stale) {                                   // своё неприменённое — молча на место
      S.cues = p.cues.map(mkCue); S.dirty = !!p.dirty;
      if (p.hl) S.hl = new Set(p.hl);
    } else {                                          // файл поменяли снаружи: правки и историю — где титры совпали
      const key = c => c.start + "|" + c.text;
      const m = new Map(p.cues.filter(c => (c.note || "").trim() || (c.hist || []).length).map(c => [key(c), c]));
      for (const c of S.cues) { const o = m.get(key(c)); if (o) { c.note = o.note; c.caret = o.caret; c.mark = o.mark; c.hist = o.hist || []; } }
    }
  }
  reindex();
  S.busy = !!r.running; S.noFollow = false;
  S.sel = new Set(); S.cur = S.cues[0]?.id || null; if (S.cur) S.sel.add(S.cur);
  document.body.classList.add("has-file");
  S.peaks = null; S.dur = 0;
  const v = r.video;
  $("#videoWrap").classList.toggle("none", !v);
  if (v) { video.src = "/media?p=" + encodeURIComponent(v.path); S.dur = (v.dur || 0) * 1000; }
  else { video.removeAttribute("src"); video.load(); S.dur = Math.max(0, ...S.cues.map(c => c.end)) + 2000; }
  video.playbackRate = Number($("#rate").value);
  for (const r0 of rows.values()) r0.row.remove();
  rows.clear();
  renderList(); updateTop(); renderChat(r.chat || []); fitView(); drawTl(); countOthers();
  if (S.busy) { live = { anyText: false }; setChatStatus("Working…"); }
  $("#list").scrollTop = 0;
  api("set_dirty", S.dirty);
}

// ═══════════════════════════ шапка ═══════════════════════════
function updateTop() {
  const c = $("#crumb");
  if (!S.file) { c.innerHTML = '<span class="crumb-name">No file</span>'; return; }
  const n = S.cues.filter(c => c.note.trim()).length;
  // имя без расширения и без подписи этапа после «`» («13 ` 1h.srt» → «13»); полное — в подсказке
  const short = S.file.name.replace(/\.[^.]+$/, "").split("`")[0].trim() || S.file.name;
  c.innerHTML = `<span class="crumb-name" title="${esc(S.file.srt)}">${esc(short)}</span><span class="crumb-pos">${S.file.folder.idx + 1}/${S.file.folder.total}</span>`;
  // Save All: несохранённое (здесь или в других файлах) — серая точка справа от слова; Claude работает — крутится пунктир
  const b = $("#applyBtn"), lbl = $("#applyLbl"), others = S.others || 0;
  const why = [S.dirty && "unsaved manual changes", n && `${n} voice edit${n > 1 ? "s" : ""} to apply`, others && `${others} other file${others > 1 ? "s" : ""}`].filter(Boolean).join(" · ");
  b.classList.toggle("busy", S.busy);
  b.classList.toggle("unsaved", !S.busy && !!why);
  b.classList.toggle("idle", !S.busy && !why && !b.classList.contains("done"));
  b.dataset.tip = S.busy ? "Claude is working · click to stop" : why ? `Save all: ${why} · right-click: more` : "Everything is saved · right-click: Save As";
  if (!b.classList.contains("done")) lbl.textContent = "Save All";
  document.querySelector(".listpane").classList.toggle("busy", S.busy);
}
// после сохранения: кнопка гаснет в серое «Done ✓», потом так же плавно в неактивное «Save»
function flashDone() {
  const b = $("#applyBtn"), lbl = $("#applyLbl");
  b.classList.add("swap");
  setTimeout(() => { b.classList.add("done"); b.classList.remove("idle"); lbl.innerHTML = `${icon("check")}Done`; b.classList.remove("swap"); }, 160);
  setTimeout(() => { b.classList.add("swap"); }, 1500);
  setTimeout(() => { b.classList.remove("done"); updateTop(); b.classList.remove("swap"); }, 1680);
}

// ═══════════════════════════ список титров ═══════════════════════════
// строки не пересоздаются: существующие переиспользуются, новые вставляются на место — вставка,
// удаление, разбиение мгновенные даже на длинных файлах
function renderList() {
  const list = $("#list");
  for (const [id, r] of rows) if (!S.byId.has(id)) { waveObs && waveObs.unobserve(r.cv); r.row.remove(); rows.delete(id); }
  let prev = null;
  for (const c of S.cues) {
    let r = rows.get(c.id);
    if (!r) r = buildRow(c);
    const expected = prev ? prev.nextSibling : list.firstChild;
    if (r.row !== expected) list.insertBefore(r.row, expected);
    prev = r.row;
    fillRow(c, r);
  }
}

function buildRow(c) {
  const row = el("div", "row");
  row.dataset.id = c.id;
  row.innerHTML = `
    <div class="c-n"><b></b><span class="mk"></span></div>
    <div class="c-t"><div class="tt"><span class="ts" data-k="start"></span><span class="te" data-k="end"></span><span class="dur"></span></div>
      <div class="mg"><button class="mgb" data-m="-1" data-tip="Merge with the previous cue">${icon("mergeUp")}</button><button class="mgb" data-m="1" data-tip="Merge with the next cue">${icon("mergeDown")}</button></div></div>
    <div class="c-w"><canvas width="268" height="76"></canvas></div>
    <div class="c-x"><button class="rst" data-tip="Reset the caret and the wave mark"></button><div class="ta-wrap"><textarea rows="1" spellcheck="false"></textarea><div class="bd"></div></div></div>
    <div class="c-v"><button class="mic" data-tip="Voice edit · click to start/stop · or hold the side mouse button">${icon("mic")}</button>
      <textarea class="note" rows="2" spellcheck="false"></textarea></div>`;
  const r = { row, n: row.querySelector(".c-n b"), mk: row.querySelector(".mk"), ts: row.querySelector(".ts"), te: row.querySelector(".te"),
    dur: row.querySelector(".dur"), cv: row.querySelector("canvas"), ta: row.querySelector(".c-x textarea"), bd: row.querySelector(".bd"),
    mic: row.querySelector(".mic"), note: row.querySelector(".note"), hoverX: null };
  row.querySelectorAll(".mgb").forEach(b => b.addEventListener("click", ev => { ev.stopPropagation(); mergeWith(c.id, +b.dataset.m); }));
  row.querySelector(".rst").addEventListener("click", ev => { ev.stopPropagation(); resetMarks([c.id]); });
  rows.set(c.id, r);
  wireRow(c.id, r);
  waveObs && waveObs.observe(r.cv);
  return r;
}

function fillRow(c, r) {
  r.n.textContent = c._i + 1;
  r.mk.textContent = c.mk || "";
  r.ts.textContent = fmt(c.start); r.te.textContent = fmt(c.end);
  const d = c.end - c.start;
  r.dur.textContent = (d / 1000).toFixed(3) + " s";
  r.dur.classList.toggle("long", d > 2500);
  if (r.ta.value !== c.text) r.ta.value = c.text;
  paintNote(c, r);
  r.mic.classList.toggle("rec", !!(S.rec && S.rec.id === c.id));
  r.mic.classList.toggle("wait", [...waitCue.values()].includes(c.id));
  r.ta.readOnly = S.busy;
  r.row.classList.toggle("sel", S.sel.has(c.id));
  r.row.classList.toggle("cur", S.cur === c.id);
  r.row.classList.toggle("hl", S.hl.has(c.id));
  r.row.classList.toggle("has-mark", hasMark(c));
  paintBackdrop(c, r);
  r.waveDirty = true;
  if (r.visible) drawMini(c, r);
}
// поле правки: итоговый текст + то, что распознаётся прямо сейчас (в том же поле)
// Поле постоянной высоты: при диктовке текст уезжает вверх, поле не растёт. Пока новой правки нет, прошлая
// видна блёклой подсказкой (placeholder); правый клик по полю — вся история правок титра.
function paintNote(c, r) {
  const p = S.partial && S.partial.cue === c.id ? S.partial.text : "";
  const v = p ? (c.note.trim() ? c.note.trim() + " " : "") + p : c.note;
  if (r.note.value !== v && (document.activeElement !== r.note || p)) { r.note.value = v; r.note.scrollTop = r.note.scrollHeight; }
  const last = c.hist.length ? c.hist[c.hist.length - 1] : null;
  r.note.placeholder = last ? last.note : "";
  r.note.classList.toggle("listening", !!p);
  r.note.classList.toggle("filled", !!c.note.trim());
  r.note.classList.toggle("ghost", !c.note.trim() && !!last);
  r.note.title = c.why ? "Not done: " + c.why : "";
}
// каретка, поставленная самим (не авто от клика по таймлайну), или отметка на волне — то, что сбрасывает буллит
const hasMark = c => !!((c.caret && !c.caret.auto) || c.mark);
function resetMarks(ids) {
  for (const id of ids) {
    const c = cueById(id), r = rows.get(id); if (!c) continue;
    c.caret = null; c.mark = null;
    if (r) { if (document.activeElement === r.ta) r.ta.blur(); paintBackdrop(c, r); r.row.classList.remove("has-mark"); r.waveDirty = true; if (r.visible) drawMini(c, r); }
  }
  drawTl(); savePending();
}
function updateRow(id) { const c = cueById(id), r = rows.get(id); if (c && r) fillRow(c, r); }
function updateSelClasses() {
  for (const [id, r] of rows) { r.row.classList.toggle("sel", S.sel.has(id)); r.row.classList.toggle("cur", S.cur === id); }
}

// своя каретка / выделение у каждого титра (видно, когда поле не в фокусе)
function paintBackdrop(c, r) {
  const t = c.text, k = c.caret;
  const s = k ? clamp(Math.min(k.s, k.e), 0, t.length) : 0, e = k ? clamp(Math.max(k.s, k.e), 0, t.length) : 0;
  // каретка в самом конце текста ничего не значит — по умолчанию её не видно (настройка)
  if (!k || k.auto || (s === e && s === t.length && !S.set.caretAtEnd)) { r.bd.innerHTML = esc(t) + "​"; return; }
  r.bd.innerHTML = s === e ? esc(t.slice(0, s)) + '<span class="caret"></span>' + esc(t.slice(s)) + "​"
    : esc(t.slice(0, s)) + "<mark>" + esc(t.slice(s, e)) + "</mark>" + esc(t.slice(e)) + "​";
}

function wireRow(id, r) {
  const c = () => cueById(id);
  r.row.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    if (e.target.closest("textarea, button, canvas, input, .c-t span")) {
      if (!e.ctrlKey && !e.shiftKey) selectCue(id, { keepIfSel: true, seek: !e.target.closest("canvas") });
      return;
    }
    selectCue(id, { ctrl: e.ctrlKey, shift: e.shiftKey, seek: true });
  });
  // правый клик: по правке — её история; по тексту — разрезать в этом месте (сброс каретки — буллит слева от текста)
  r.row.addEventListener("contextmenu", e => {
    if (e.target === r.note) { const cc = c(); if (cc && cc.hist.length) { e.preventDefault(); histMenu(cc, e.clientX, e.clientY); } return; }
    e.preventDefault();
    const cc = c(); if (!cc) return;
    if (e.target !== r.ta || S.busy) return;
    const p = r.ta.selectionStart;                   // правый клик сам ставит каретку туда, где нажали
    selectCue(id, { keepIfSel: true, seek: false });
    showMenu(e.clientX, e.clientY, [
      ["Split here", "Shift+F1", () => { cc.caret = { s: p, e: p }; splitCue("caret"); }, p <= 0 || p >= cc.text.length],
      null,
      ["Merge with previous", "", () => mergeWith(id, -1), !S.cues[cc._i - 1]],
      ["Merge with next", "F2", () => mergeWith(id, 1), !S.cues[cc._i + 1]],
    ]);
  });
  const saveCaret = () => {
    const cc = c(); if (!cc || r.autoSel) return;
    cc.caret = { s: r.ta.selectionStart, e: r.ta.selectionEnd };
    clearTimeout(pendTimer); pendTimer = setTimeout(savePending, 800);
  };
  ["select", "keyup", "mouseup"].forEach(ev => r.ta.addEventListener(ev, saveCaret));
  r.ta.addEventListener("focus", () => { S.typing = null; if (S.cur !== id) selectCue(id, { keepIfSel: true, seek: false }); });
  r.ta.addEventListener("mousedown", () => { S.soft = false; r.ta.classList.remove("soft"); });
  r.note.addEventListener("focus", () => { if (S.cur !== id) selectCue(id, { keepIfSel: true, seek: false }); });
  r.ta.addEventListener("blur", () => { const cc = c(); if (cc) paintBackdrop(cc, r); });
  r.ta.addEventListener("input", () => {
    const cc = c(); if (!cc) return;
    if (S.typing !== id) { S.undo.push(snap()); S.redo = []; S.typing = id; }
    cc.text = r.ta.value; cc.caret = { s: r.ta.selectionStart, e: r.ta.selectionEnd };
    touch(id); markDirty(); drawTl(); updateOverlay();
  });
  r.note.addEventListener("input", () => {
    const cc = c(); if (!cc) return;
    cc.note = r.note.value;
    r.note.classList.toggle("filled", !!cc.note.trim()); r.note.classList.toggle("ghost", !cc.note.trim() && cc.hist.length > 0);
    updateTop(); drawTl();
    clearTimeout(pendTimer); pendTimer = setTimeout(savePending, 500);
  });
  r.mic.addEventListener("click", () => { selectCue(id, { keepIfSel: true, seek: false }); toggleRec(id); });
  [r.ts, r.te].forEach(sp => sp.addEventListener("dblclick", () => editTime(id, sp.dataset.k, sp)));
  r.cv.addEventListener("mousedown", e => miniDown(e, id, r));
  r.cv.addEventListener("mousemove", e => { r.hoverX = e.offsetX / r.cv.clientWidth; drawMini(c(), r); });
  r.cv.addEventListener("mouseleave", () => { r.hoverX = null; drawMini(c(), r); });
}

function editTime(id, k, sp) {
  const c = cueById(id); if (!c || S.busy) return;
  const inp = el("input"); inp.value = fmt(c[k]); sp.replaceWith(inp); inp.focus(); inp.select();
  const done = ok => {
    if (inp._done) return; inp._done = true;
    const v = parseTime(inp.value);
    inp.replaceWith(sp);
    if (ok && v != null && v !== c[k]) {
      pushUndo(); c[k] = v;
      if (c.end <= c.start) { if (k === "start") c.end = c.start + 500; else c.start = Math.max(0, c.end - 500); }
      S.cues.sort((a, b) => a.start - b.start); reindex(); touch(id); changed(true);
    }
  };
  inp.addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
  inp.addEventListener("blur", () => done(true));
}

// ── мини-волна в строке ──
let waveObs = new IntersectionObserver(ents => {
  for (const en of ents) {
    const id = en.target.closest(".row")?.dataset.id, r = rows.get(id);
    if (!r) continue;
    r.visible = en.isIntersecting;
    if (r.visible && r.waveDirty) drawMini(cueById(id), r);
  }
}, { root: $("#list"), rootMargin: "200px" });

// громкость 0…1 в промежутке отсчётов волны [i0, i1)
function peakMax(i0, i1) {
  let m = 0; i1 = Math.min(Math.max(i0 + 1, i1), S.peaks.length);
  for (let i = Math.max(0, i0); i < i1; i++) if (S.peaks[i] > m) m = S.peaks[i];
  return m / 255;
}
// Волна по стилю из настроек: solid — сплошная (столбик на пиксель), bars — столбики с промежутками,
// blocks — столбики, порезанные поперёк на сегменты (как индикатор уровня). Всё на целых пикселях.
// mid — середина, half — максимум вверх/вниз, amp(x0, x1) — громкость под отрезком холста.
function drawWave(g, W, mid, half, amp, minOne) {
  const st = S.set.waveStyle || "solid";
  if (st === "solid") {
    for (let x = 0; x < W; x++) {
      const hh = amp(x, x + 1) * half;
      if (minOne) { const h = Math.max(1, hh * 2); g.fillRect(x, mid - h / 2, 1, h); }
      else if (hh > .3) g.fillRect(x, mid - hh, 1, hh * 2);
    }
    return;
  }
  const bw = Math.max(1, Math.round(S.set.waveBar || 3)), gap = Math.max(1, Math.round(S.set.waveGap || 2)), P = bw + gap;
  const seg = Math.max(1, Math.round(S.set.waveSeg || 3)), sg = Math.max(1, Math.round(S.set.waveSegGap || 1));
  const my = Math.round(mid), r = st === "bars" && S.set.waveRound ? bw / 2 : 0;
  for (let x = 0; x < W; x += P) {
    const a = amp(x, x + P);
    if (st === "bars") {
      const hh = Math.max(1, Math.round(a * half));
      if (r && g.roundRect && hh * 2 > bw) { g.beginPath(); g.roundRect(x, my - hh, bw, hh * 2, r); g.fill(); }
      else g.fillRect(x, my - hh, bw, hh * 2);
      continue;
    }
    // сегменты от середины наружу, симметрично; посередине — промежуток сегментов
    const n = Math.max(1, Math.round(a * half / (seg + sg)));
    for (let k = 0; k < n; k++) {
      const o = Math.floor(sg / 2) + k * (seg + sg);
      g.fillRect(x, my - o - seg, bw, seg);
      g.fillRect(x, my + Math.ceil(sg / 2) + k * (seg + sg), bw, seg);
    }
  }
}
function drawMini(c, r) {
  if (!c) return;
  const cv = r.cv, g = cv.getContext("2d"), W = cv.width, H = cv.height;
  r.waveDirty = false;
  g.clearRect(0, 0, W, H);
  const dur = c.end - c.start;
  if (S.peaks && dur > 0) {
    g.fillStyle = PAL.wave;
    const a0 = c.start / 1000 * S.rate, a1 = c.end / 1000 * S.rate, per = (a1 - a0) / W;
    drawWave(g, W, H / 2, (H - 6) / 2, (x0, x1) => peakMax(Math.floor(a0 + x0 * per), Math.floor(a0 + x1 * per)), true);
  } else { g.fillStyle = PAL.faint; g.fillRect(0, H / 2, W, 1); }
  const t = vt();
  if (t >= c.start && t <= c.end && dur > 0) { g.globalAlpha = .45; g.fillStyle = "#fff"; g.fillRect(Math.round((t - c.start) / dur * W), 0, 1, H); g.globalAlpha = 1; }
  if (c.mark && dur > 0) {
    const xa = (c.mark.a * 1000 - c.start) / dur * W, xb = (c.mark.b * 1000 - c.start) / dur * W;
    if (Math.abs(xb - xa) > 2) { g.globalAlpha = .3; g.fillStyle = PAL.mark; g.fillRect(Math.min(xa, xb), 0, Math.abs(xb - xa), H); g.globalAlpha = 1; }
    g.fillStyle = PAL.mark; g.fillRect(Math.round(xa) - 1, 0, 2, H);
    if (Math.abs(xb - xa) > 2) g.fillRect(Math.round(xb) - 1, 0, 2, H);
  }
  if (r.hoverX != null) { g.fillStyle = PAL.hoverline; g.fillRect(Math.round(r.hoverX * W) - 1, 0, 2, H); }
}
function miniDown(e, id, r) {
  if (e.button !== 0) return;
  e.preventDefault();
  const c = cueById(id); if (!c) return;
  const rect = r.cv.getBoundingClientRect();
  const at = x => (c.start + clamp((x - rect.left) / rect.width, 0, 1) * (c.end - c.start)) / 1000;
  const a = at(e.clientX);
  c.mark = { a, b: a };
  seek(a * 1000);
  drawMini(c, r); drawTl();
  const mv = ev => { c.mark.b = at(ev.clientX); drawMini(c, r); drawTl(); };
  const up = () => {
    removeEventListener("mousemove", mv); removeEventListener("mouseup", up);
    if (c.mark.b < c.mark.a) [c.mark.a, c.mark.b] = [c.mark.b, c.mark.a];
    savePending();
  };
  addEventListener("mousemove", mv); addEventListener("mouseup", up);
}

// ── выделение ──
function selectCue(id, o = {}) {
  if (!cueById(id)) return;
  const prev = S.cur;
  if (o.shift && S.anchor && cueById(S.anchor)) {
    const a = cueById(S.anchor)._i, b = cueById(id)._i;
    S.sel = new Set(S.cues.slice(Math.min(a, b), Math.max(a, b) + 1).map(c => c.id));
  } else if (o.ctrl) {
    S.sel.has(id) && S.sel.size > 1 ? S.sel.delete(id) : S.sel.add(id);
    S.anchor = id;
  } else if (!(o.keepIfSel && S.sel.has(id))) {
    S.sel = new Set([id]); S.anchor = id;
  }
  S.cur = id;
  updateSelClasses();
  if (o.seek && prev !== id && S.set.seekOnSelect) seekCue(cueById(id));
  if (o.scroll) scrollToCue(id);
  if (o.reveal !== false) revealInTl(cueById(id));
  drawTl();
}
function scrollToCue(id) {
  const r = rows.get(id); if (!r) return;
  const L = $("#list"), top = r.row.offsetTop, h = r.row.offsetHeight;
  if (top < L.scrollTop + 10 || top + h > L.scrollTop + L.clientHeight - 10) L.scrollTop = top - L.clientHeight / 3;
}
function moveCur(d, o = {}) {
  if (!S.cues.length) return;
  const i = S.cur ? cueById(S.cur)._i : -1;
  const j = clamp(i + d, 0, S.cues.length - 1);
  selectCue(S.cues[j].id, { seek: true, scroll: true, shift: o.shift });
  if (o.focusText) rows.get(S.cues[j].id)?.ta.focus({ preventScroll: true });
}

// ═══════════════════════════ операции (как в Subtitle Edit) ═══════════════════════════
function splitCue(mode) {                       // 'video' (F1), 'caret' (Shift+F1), 'middle' (Alt+F1)
  const c = curCue(); if (!c || S.busy) return;
  const r = rows.get(c.id);
  if (r && document.activeElement === r.ta) c.caret = { s: r.ta.selectionStart, e: r.ta.selectionEnd };
  const t = c.text, v = vt();
  // каретку, поставленную самим, слушаем; авто-каретку от клика по таймлайну — нет
  const own = c.caret && !c.caret.auto && mode !== "middle";
  let p = own ? clamp(Math.min(c.caret.s, c.caret.e), 0, t.length) : -1;
  const markIn = c.mark && c.mark.a * 1000 > c.start + 30 && c.mark.a * 1000 < c.end - 30;
  const ratioAt = ms => nearestSpace(t, Math.round(t.length * (ms - c.start) / (c.end - c.start)));
  if (p <= 0 || p >= t.length || !t.slice(0, p).trim() || !t.slice(p).trim()) {
    // своей каретки нет — делим «по-умному»: по месту отметки на волне или по видео, иначе посередине
    p = markIn ? ratioAt(c.mark.a * 1000) : mode === "video" && v > c.start + 30 && v < c.end - 30 ? ratioAt(v) : middleSpace(t);
    p = smartCut(t, p);
  }
  const L = t.slice(0, p).trim(), R = t.slice(p).trim();
  if (!L || !R) return toast("Nothing to split: one word only", "err");
  let at;
  if (mode === "video" && v > c.start + 30 && v < c.end - 30) at = v;
  else if (markIn) at = c.mark.a * 1000;
  else at = c.start + (c.end - c.start) * L.length / (L.length + R.length);
  at = Math.round(at);
  pushUndo();
  const n = mkCue({ start: at + 1, end: c.end, text: R });
  c.end = at; c.text = L; c.caret = null; c.mark = null;
  S.cues.splice(c._i + 1, 0, n); reindex();
  touch(c.id);
  S.sel = new Set([n.id]); S.cur = n.id;
  if (r && document.activeElement === r.ta) r.ta.blur();      // после разрезания каретки нет нигде
  changed(true);
}
// служебные слова держатся за соседнее: предлог / союз / «не» — со следующим словом, «же / ли / бы» — с предыдущим
const LEAD = new Set("в во на с со к ко у о об обо от до по за из изо без для при про под подо над надо через перед между и а но или либо да не ни что чтобы как где когда если то".split(" "));
const TAIL = new Set("же ж ли ль бы б".split(" "));
function smartCut(t, p) {
  for (let k = 0; k < 3; k++) {
    const left = t.slice(0, p), m = left.match(/(\S+)\s*$/);
    const w = m && m[1].toLowerCase().replace(/[^\p{L}-]/gu, "");
    if (!m || !LEAD.has(w) || /[.,!?;:…]$/.test(m[1]) || !left.slice(0, m.index).trim()) break;
    p = m.index;                                   // предлог уходит во вторую половину
  }
  const right = t.slice(p), m2 = right.match(/^\s*(\S+)/);
  const w2 = m2 && m2[1].toLowerCase().replace(/[^\p{L}-]/gu, "");
  if (m2 && TAIL.has(w2) && right.slice(m2[0].length).trim()) p += m2[0].length;   // частица — к первой
  return p;
}
function middleSpace(t) { return nearestSpace(t, Math.floor(t.length / 2)); }
function nearestSpace(t, at) {
  let best = -1, bd = 1e9;
  for (let i = 1; i < t.length; i++) if (/\s/.test(t[i]) && Math.abs(i - at) < bd) { best = i; bd = Math.abs(i - at); }
  return best < 0 ? at : best;
}
function mergeCues() {                           // F2: выделено несколько — склеить их, один — со следующим
  if (S.busy) return;
  let ids = S.cues.filter(c => S.sel.has(c.id));
  if (ids.length < 2) { const c = curCue(); if (!c || !S.cues[c._i + 1]) return; ids = [c, S.cues[c._i + 1]]; }
  pushUndo();
  const a = ids[0];
  a.text = ids.map(c => c.text.replace(/\s*\n\s*/g, " ").trim()).filter(Boolean).join(" ");
  a.end = ids[ids.length - 1].end;
  a.note = ids.map(c => c.note.trim()).filter(Boolean).join(" · ");
  a.hist = ids.flatMap(c => c.hist || []);
  a.caret = null; a.mark = null;
  const drop = new Set(ids.slice(1).map(c => c.id));
  S.cues = S.cues.filter(c => !drop.has(c.id)); reindex();
  touch(a.id); S.sel = new Set([a.id]); S.cur = a.id;
  changed(true);
}
function mergeSelected() { if (S.sel.size >= 2) mergeCues(); }
function mergeWith(id, dir) {                    // кнопки ↑ / ↓ в строке и меню таймлайна
  const c = cueById(id); if (!c || S.busy) return;
  const o = S.cues[c._i + dir]; if (!o) return;
  S.sel = new Set([c.id, o.id]); S.cur = dir < 0 ? o.id : c.id;
  mergeCues();
}
// история правок титра: что говорил Saturni и как Claude это понял
function histMenu(c, x, y) {
  showMenu(x, y, c.hist.slice().reverse().map((h, i) => [`${c.hist.length - i}. ${h.note.length > 46 ? h.note.slice(0, 46) + "…" : h.note}`, h.at ? h.at.slice(5) : "", () => histShow(c, c.hist.length - 1 - i)]));
}
function histShow(c, i) {
  const h = c.hist[i];
  modal(`Voice edit ${i + 1} of ${c.hist.length} · cue ${c._i + 1}`,
    `<div class="hist"><div class="hl-lbl">You said</div><div class="hl-say">${esc(h.note)}</div>` +
    `<div class="hl-lbl">Claude understood</div><div class="hl-what">${esc(h.what || "—")}</div>${h.at ? `<div class="hl-at">${esc(h.at)}</div>` : ""}</div>`,
    [["Close", "btn2 pri", null]]);
}
function unbreak() {
  const c = curCue(); if (!c || S.busy || !/\n/.test(c.text)) return;
  pushUndo(); c.text = c.text.replace(/\s*\n\s*/g, " "); touch(c.id); changed(false, [c.id]);
}
function autoBreak() {
  const c = curCue(); if (!c || S.busy) return;
  const t = c.text.replace(/\s*\n\s*/g, " "), p = middleSpace(t);
  if (p <= 0 || p >= t.length) return;
  pushUndo(); c.text = t.slice(0, p).trim() + "\n" + t.slice(p).trim(); touch(c.id); changed(false, [c.id]);
}
function bridgeGaps() {                          // Shift+F3: короткие зазоры — стык 1 мс
  if (S.busy) return;
  const lim = S.set.bridgeMs || 200;
  const list = S.sel.size > 1 ? S.cues.filter(c => S.sel.has(c.id)) : S.cues;
  pushUndo(); let n = 0;
  for (const a of list) {
    const b = S.cues[a._i + 1]; if (!b) continue;
    const gap = b.start - a.end;
    if (gap > 1 && gap < lim) { a.end = b.start - 1; touch(a.id); n++; }
  }
  changed(true); toast(n ? `Bridged ${n} gap(s)` : `No gaps under ${lim} ms`);
}
function setStart(offsetRest) {
  const c = curCue(); if (!c || S.busy) return;
  const t = Math.round(vt()); pushUndo();
  if (offsetRest) { const d = t - c.start; for (let i = c._i; i < S.cues.length; i++) { S.cues[i].start += d; S.cues[i].end += d; } }
  else { c.start = Math.min(t, c.end - 100); }
  touch(c.id); changed(true);
}
function setEnd(goNext) {
  const c = curCue(); if (!c || S.busy) return;
  const t = Math.round(vt()); if (t <= c.start + 50) return toast("Video position is before the cue start", "err");
  pushUndo(); c.end = t; touch(c.id); changed(true);
  if (goNext) moveCur(1);
}
function extend(dir) {
  const c = curCue(); if (!c || S.busy) return;
  const n = S.cues[c._i + dir]; pushUndo();
  if (dir > 0) c.end = n ? n.start - 1 : c.end + 1000; else c.start = n ? n.end + 1 : 0;
  touch(c.id); changed(true);
}
function insertCue(where) {
  if (S.busy || !S.file) return;
  const c = curCue(); let s;
  if (where === "video" || !c) s = Math.round(vt());
  else if (where === "after") s = c.end + 1;
  else s = Math.max(0, c.start - 1501);
  const next = S.cues.find(x => x.start > s);
  const e = Math.max(s + 300, Math.min(s + 1500, next ? next.start - 1 : s + 1500));
  pushUndo();
  const n = mkCue({ start: s, end: e, text: "" });
  S.cues.push(n); S.cues.sort((a, b) => a.start - b.start); reindex();
  S.sel = new Set([n.id]); S.cur = n.id; changed(true);
  rows.get(n.id)?.ta.focus(); scrollToCue(n.id);
}
function deleteSel() {
  if (S.busy || !S.sel.size) return;
  pushUndo();
  const i = Math.min(...[...S.sel].map(id => cueById(id)?._i ?? 1e9));
  S.cues = S.cues.filter(c => !S.sel.has(c.id)); reindex();
  const n = S.cues[Math.min(i, S.cues.length - 1)];
  S.sel = new Set(n ? [n.id] : []); S.cur = n?.id || null; changed(true);
}
function caseSel(upper) {
  const a = document.activeElement; if (!a || a.tagName !== "TEXTAREA" || a.classList.contains("note") || a.closest(".chat")) return;
  const s = a.selectionStart, e = a.selectionEnd; if (s === e) return;
  const v = a.value.slice(s, e); a.setRangeText(upper ? v.toUpperCase() : v.toLowerCase(), s, e, "select");
  a.dispatchEvent(new Event("input"));
}
function italic() {
  const c = curCue(); if (!c || S.busy) return;
  pushUndo(); c.text = /^<i>[\s\S]*<\/i>$/.test(c.text) ? c.text.slice(3, -4) : `<i>${c.text}</i>`; touch(c.id); changed(false, [c.id]);
}

// ═══════════════════════════ видео ═══════════════════════════
function seek(ms) { S.seekShow = null; if (!video.src) { S.vtFake = ms; drawTl(); return; } video.currentTime = Math.max(0, ms / 1000); drawTl(); }
// К началу титра: кадр, что показан на времени «начало», почти всегда последний кадр предыдущего титра.
// Встаём в середину первого кадра, который начинается не раньше начала титра; время при этом показываем ровно началом.
function seekCue(c) {
  if (!video.src) return seek(c.start);
  const f = 1000 / (S.file?.video?.fps || 25), at = Math.ceil(c.start / f - 1e-6) * f + f / 2;
  video.currentTime = at / 1000; S.seekAt = at; S.seekShow = c.start; drawTl(); tick();
}
function playPause() { if (!video.src) return; video.paused ? video.play() : video.pause(); }
let stopAt = null;
function playRange(a, b) { if (!video.src) return; stopAt = b; video.currentTime = a / 1000; video.play(); }
video.addEventListener("play", () => { S.seekShow = null; S.noFollow = false; $("#playIc").innerHTML = icon("pause"); loop(); });   // новый запуск — снова следим
video.addEventListener("pause", () => { $("#playIc").innerHTML = icon("play"); stopAt = null; drawTl(); });
video.addEventListener("seeked", () => { drawTl(); tick(); });
video.addEventListener("loadedmetadata", () => { if (video.duration) { S.dur = video.duration * 1000; fitView(); drawTl(); } });
$("#rate").addEventListener("change", e => { video.playbackRate = Number(e.target.value); });

let lastLive = null;
function tick() {
  const t = vt();
  $("#vtime").textContent = fmt(t);
  $("#tlTime").textContent = fmt(t);
  if (stopAt != null && t >= stopAt) { video.pause(); stopAt = null; }
  updateOverlay();
  const live = S.cues.find(c => t >= c.start && t <= c.end)?.id || null;
  if (live !== lastLive) {
    if (lastLive) { const r = rows.get(lastLive); if (r) { r.row.classList.remove("live"); drawMini(cueById(lastLive), r); } }
    if (live) { rows.get(live)?.row.classList.add("live"); if (!video.paused && S.set.followPlayback && !S.noFollow) scrollToCue(live); }
    lastLive = live;
  }
  if (live) { const r = rows.get(live); if (r && r.visible) drawMini(cueById(live), r); }
}
// Титр поверх видео рисует тот же libass с тем же стилем, что рендер (Subs Move / 2Stage): PNG с прозрачностью,
// кладётся в координатах кадра. Пока картинка готовится — виден прошлый вид; рендера нет — простой текст.
const LAYER = new Map();             // "mk|text" -> {url, x, y, w, h, W, H} | {empty} | "wait" | "fail"
let layerShown = null;
function layerKey(c) { return (c.mk || "") + "|" + c.text; }
let layerT = 0;
function askLayer(c, now) {
  const k = layerKey(c);
  if (LAYER.has(k) || !S.file?.video) return;
  // пока печатаешь — рендер не на каждую букву, а когда остановился
  if (!now && S.typing === c.id) { clearTimeout(layerT); layerT = setTimeout(() => { askLayer(c, true); }, 450); return; }
  LAYER.set(k, "wait");
  api("sub_layer", c.mk || "", c.text).then(r => {
    LAYER.set(k, r && !r.error && (r.path || r.empty) ? { ...r, url: r.path ? "/media?p=" + encodeURIComponent(r.path) : null } : "fail");
    updateOverlay();
  }).catch(() => { LAYER.set(k, "fail"); updateOverlay(); });
}
function placeLayer(L) {
  const img = $("#subImg"), box = $("#videoWrap"), vw = video.videoWidth, vh = video.videoHeight;
  if (!vw || !vh) return;
  const s = Math.min(box.clientWidth / vw, box.clientHeight / vh), dw = vw * s, dh = vh * s;
  const ox = (box.clientWidth - dw) / 2, oy = (box.clientHeight - dh) / 2, kx = dw / L.W, ky = dh / L.H;
  Object.assign(img.style, { left: ox + L.x * kx + "px", top: oy + L.y * ky + "px", width: L.w * kx + "px", height: L.h * ky + "px" });
}
function updateOverlay() {
  const t = vt();
  const c = S.cues.find(c => t >= c.start && t <= c.end);
  const ov = $("#subOv"), img = $("#subImg");
  let txt = c ? c.text.replace(/<\/?i>/g, "") : "", L = null;
  if (c && S.file?.video) {
    askLayer(c);
    const n = S.cues[c._i + 1]; if (n) askLayer(n);        // следующий — заранее
    L = LAYER.get(layerKey(c));
    if (L === "wait" || L === undefined) L = layerShown && layerShown.cue === c.id ? layerShown.L : null;
    if (L !== "fail") txt = "";                         // простой текст — только если рендер не получился
  }
  if (ov.textContent !== txt) ov.textContent = txt;
  const show = L && L !== "fail" && L !== "wait" && L.url;
  img.hidden = !show;
  if (show) { if (img.dataset.src !== L.url) { img.src = L.url; img.dataset.src = L.url; } placeLayer(L); layerShown = { cue: c.id, L }; }
}
new ResizeObserver(() => { if (layerShown && !$("#subImg").hidden) placeLayer(layerShown.L); }).observe($("#videoWrap"));
function loop() {
  tick();
  if (!video.paused) {
    const t = vt(), v = S.view, W = tlW();
    if (!dragTl && !S.noFollow && (t / 1000 < v.t0 || t / 1000 > v.t0 + W / v.pps * .92)) v.t0 = Math.max(0, t / 1000 - W / v.pps * .1);
    drawTl(true);
    requestAnimationFrame(loop);
  }
}

// ═══════════════════════════ таймлайн ═══════════════════════════
const tlBase = $("#tlBase"), tlTop = $("#tlTop"), tlBox = $("#tlBox");
const RULER = 18;
let dragTl = null, hoverTl = null;
const tlW = () => tlBox.clientWidth;
const x2t = x => S.view.t0 + x / S.view.pps;
const t2x = t => (t - S.view.t0) * S.view.pps;
function resizeTl() {
  const dpr = window.devicePixelRatio || 1;
  for (const c of [tlBase, tlTop]) { c.width = Math.round(tlBox.clientWidth * dpr); c.height = Math.round(tlBox.clientHeight * dpr); }
  drawTl();
}
new ResizeObserver(resizeTl).observe(tlBox);
function fitView() {
  const W = tlW() || 1000, d = Math.max(S.dur, 1000) / 1000;
  S.view.pps = clamp(S.prefs.zoom || 120, 4, 2000);
  if (d * S.view.pps < W) S.view.pps = Math.max(4, W / d);
  S.view.t0 = 0;
}
function zoom(f, aroundX) {
  const v = S.view, x = aroundX ?? tlW() / 2, t = x2t(x);
  v.pps = clamp(v.pps * f, Math.max(2, tlW() / Math.max(1, S.dur / 1000) * .9), 3000);
  v.t0 = Math.max(0, t - x / v.pps);
  S.prefs.zoom = v.pps; api("prefs_save", { zoom: v.pps });
  drawTl();
}
function zoomFit() {
  const ids = S.cues.filter(c => S.sel.has(c.id));
  const W = tlW();
  if (ids.length > 1) {
    const a = ids[0].start / 1000, b = ids[ids.length - 1].end / 1000;
    S.view.pps = clamp(W / ((b - a) * 1.2), 4, 3000); S.view.t0 = Math.max(0, a - (b - a) * .1);
  } else { S.view.pps = Math.max(2, W / Math.max(1, S.dur / 1000)); S.view.t0 = 0; }
  drawTl();
}
function revealInTl(c) {
  if (!c) return;
  const v = S.view, W = tlW(), a = c.start / 1000, b = c.end / 1000;
  if (a < v.t0 || b > v.t0 + W / v.pps) v.t0 = Math.max(0, a - W / v.pps * .3);
  const end = Math.max(S.dur, ...S.cues.map(x => x.end)) / 1000;
  v.t0 = clamp(v.t0, 0, Math.max(0, end - W / v.pps));        // за концом файла пустоты нет: волна прижата к правому краю
}

let rafTl = 0;
function drawTl(fromLoop) {
  if (fromLoop) { paintTl(); return; }
  if (!rafTl) rafTl = requestAnimationFrame(() => { rafTl = 0; paintTl(); });
}
function paintTl() {
  const dpr = window.devicePixelRatio || 1, W = tlW(), H = tlBox.clientHeight;
  if (!W || !H) return;
  const g = tlBase.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const v = S.view, t0 = v.t0, t1 = x2t(W);
  // линейка: короткие засечки только в своей полосе
  g.fillStyle = PAL["panel-2"]; g.fillRect(0, 0, W, RULER);
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find(s => s * v.pps >= 70) || 600;
  g.fillStyle = PAL.muted; g.font = "10.5px Cascadia Mono, Consolas, monospace"; g.textBaseline = "middle";
  for (let s = Math.floor(t0 / step) * step; s <= t1; s += step) {
    const x = Math.round(t2x(s));
    g.fillRect(x, RULER - 6, 1, 6);
    g.fillText(fmt(s * 1000, step < 1), x + 4, RULER / 2 - 1);
  }
  const top = RULER, h = H - RULER, mid = top + h / 2;
  if (S.peaks) {
    g.fillStyle = PAL.wave;
    drawWave(g, W, mid, h / 2 - 4, (x0, x1) => peakMax(Math.floor((t0 + x0 / v.pps) * S.rate), Math.floor((t0 + x1 / v.pps) * S.rate)), false);
  } else if (S.file && S.file.video) { g.fillStyle = PAL.muted; g.fillText("Building waveform…", 12, mid); }
  // титры: тонкие края; соседи встык (зазор ≤ 1 мс) — общая тонкая линия
  g.font = "600 11.5px Inter, Segoe UI, sans-serif"; g.textBaseline = "top";
  if (S.range) {                                  // выделенный промежуток под новый титр
    const ra = t2x(Math.min(S.range.a, S.range.b) / 1000), rb = t2x(Math.max(S.range.a, S.range.b) / 1000);
    g.fillStyle = "#ffffff12"; g.fillRect(ra, top, rb - ra, h);
    g.fillStyle = "#ffffff66"; g.fillRect(Math.round(ra), top, 1, h); g.fillRect(Math.round(rb), top, 1, h);
  }
  const tNow = vt();
  for (const c of S.cues) {
    const a = c.start / 1000, b = c.end / 1000;
    if (b < t0 || a > t1) continue;
    const xa = Math.round(t2x(a)), xb = Math.round(t2x(b)), w = Math.max(1, xb - xa);
    const sel = S.sel.has(c.id), cur = S.cur === c.id, hl = S.hl.has(c.id), playing = tNow >= c.start && tNow <= c.end;
    const prev = S.cues[c._i - 1], joined = prev && c.start - prev.end <= 1;   // встык с предыдущим — общая линия
    g.fillStyle = hl ? PAL.good + "30" : (PAL["tl-cue"] || "#ffffff") + "16"; g.fillRect(xa, top, w, h);
    if (sel || playing) { g.fillStyle = cur ? "#ffffff24" : sel ? "#ffffff16" : "#ffffff10"; g.fillRect(xa, top, w, h); }   // выделение — светлее
    g.fillStyle = hl ? PAL.good : (sel ? "#ffffff99" : "#ffffff55");
    if (!joined) g.fillRect(xa, top, 1, h);
    g.fillRect(xb, top, 1, h);
    if (w > 18) {
      g.save(); g.beginPath(); g.rect(xa + 4, top, w - 8, h); g.clip();
      g.fillStyle = PAL.text; g.globalAlpha = .5; g.fillText(`${c._i + 1}`, xa + 5, top + 4);
      g.globalAlpha = .92;
      c.text.replace(/<\/?i>/g, "").split("\n").forEach((ln, k) => g.fillText(ln, xa + 5, top + 19 + k * 14));
      g.restore();
    }
    if (c.note.trim()) { g.fillStyle = PAL.note; g.beginPath(); g.arc(xb - 7, top + 8, 3.5, 0, 7); g.fill(); }
    if (c.mark) {
      const ma = t2x(c.mark.a), mb = t2x(c.mark.b);
      if (mb - ma > 2) { g.globalAlpha = .25; g.fillStyle = PAL.mark; g.fillRect(ma, top, mb - ma, h); g.globalAlpha = 1; }
      g.fillStyle = PAL.mark; g.fillRect(Math.round(ma), top, 1, h);
    }
  }
  const gt = tlTop.getContext("2d");
  gt.setTransform(dpr, 0, 0, dpr, 0, 0);
  gt.clearRect(0, 0, W, H);
  const px = t2x(vt() / 1000);
  if (px >= -2 && px <= W + 2) {
    gt.fillStyle = PAL.playhead; gt.fillRect(Math.round(px) - 1, 0, 2, H);
    gt.beginPath(); gt.moveTo(px - 5, 0); gt.lineTo(px + 5, 0); gt.lineTo(px, 7); gt.fill();
  }
  if (hoverTl != null && !dragTl) { gt.globalAlpha = .5; gt.fillStyle = PAL.hoverline; gt.fillRect(Math.round(hoverTl), RULER, 1, H - RULER); gt.globalAlpha = 1; }
}

// край под курсором; у двух титров встык берётся тот край, с чьей стороны стоит курсор
function hitTl(x, y) {
  if (y < RULER) return { kind: "ruler" };
  const t = x2t(x) * 1000, edge = 6 / S.view.pps * 1000, tie = 2 / S.view.pps * 1000;
  let best = null;
  for (const c of S.cues) {
    if (t < c.start - edge || t > c.end + edge) continue;
    for (const [kind, et] of [["start", c.start], ["end", c.end]]) {
      const d = Math.abs(t - et); if (d > edge) continue;
      const own = kind === "start" ? t >= et : t <= et;            // курсор внутри своего титра
      const score = d - (own ? tie : 0);
      if (!best || score < best.score) best = { kind, c, d, score };
    }
  }
  if (best) return best;
  const c = S.cues.find(c => t >= c.start && t <= c.end);
  return c ? { kind: "body", c } : { kind: "empty" };
}
// клик по титру на таймлайне: выделить, каретку в его текст — в слово под курсором, отметку на волне туда же
function clickCueAt(c, tms) {
  selectCue(c.id, { scroll: true, reveal: false });
  seek(tms);
  c.mark = { a: tms / 1000, b: tms / 1000 };
  const r = rows.get(c.id);
  if (r && !S.busy) {
    const t = c.text, ratio = clamp((tms - c.start) / Math.max(1, c.end - c.start), 0, 1);
    let p = Math.round(t.length * ratio);
    if (p > 0 && p < t.length) p = nearestSpace(t, p);
    // каретка «авто»: её не видно и разрезание её не слушает — жёлтая каретка только та, что поставил сам
    c.caret = { s: p, e: p, auto: true };
    r.autoSel = true; setTimeout(() => { r.autoSel = false; }, 60);
    r.ta.focus({ preventScroll: true }); r.ta.setSelectionRange(p, p);
    S.soft = true;                                  // фокус дан кликом по таймлайну: пробел — воспроизведение
    r.ta.classList.add("soft");
  }
  updateRow(c.id); drawTl(); savePending();
}
function addCueRange(a, b) {                     // новый титр на выделенный промежуток (или на всю паузу)
  if (S.busy || !S.file) return;
  a = Math.round(a); b = Math.round(b);
  const prev = S.cues.filter(c => c.end <= a + 1).pop(), next = S.cues.find(c => c.start >= b - 1);
  a = Math.max(a, prev ? prev.end + 1 : 0); b = Math.min(b, next ? next.start - 1 : b);
  if (b - a < 50) return toast("No room for a subtitle here", "err");
  pushUndo();
  const n = mkCue({ start: a, end: b, text: "" });
  S.cues.push(n); S.cues.sort((x, y) => x.start - y.start); reindex();
  S.sel = new Set([n.id]); S.cur = n.id; S.range = null; changed(true);
  rows.get(n.id)?.ta.focus(); scrollToCue(n.id);
}
function gapAround(t) {                          // пауза вокруг точки: от конца предыдущего до начала следующего
  const prev = S.cues.filter(c => c.end <= t).pop(), next = S.cues.find(c => c.start >= t);
  return [prev ? prev.end + 1 : 0, next ? next.start - 1 : Math.max(t + 1500, S.dur || t + 1500)];
}
function placePlus() {                           // «+» над выделенным промежутком
  const b = $("#tlPlus");
  if (!S.range || Math.abs(S.range.b - S.range.a) < 30) { b.hidden = true; return; }
  const a = Math.min(S.range.a, S.range.b), z = Math.max(S.range.a, S.range.b);
  const x = (t2x(a / 1000) + t2x(z / 1000)) / 2;
  if (x < 0 || x > tlW()) { b.hidden = true; return; }
  b.hidden = false; b.style.left = Math.round(x - 12) + "px"; b.style.top = (RULER + 6) + "px";
}
const magnetMs = () => (S.set.magnetPx || 0) / S.view.pps * 1000;
tlTop.addEventListener("mousemove", e => {
  const r = tlTop.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  hoverTl = x;
  if (!dragTl) {
    const h = hitTl(x, y);
    tlTop.style.cursor = h.kind === "start" || h.kind === "end" ? "ew-resize" : "default";
  }
  drawTl();
});
tlTop.addEventListener("mouseleave", () => { hoverTl = null; drawTl(); });
tlTop.addEventListener("mousedown", e => {
  if (e.button !== 0 || !S.file) return;
  const r = tlTop.getBoundingClientRect(), x0 = e.clientX - r.left, y0 = e.clientY - r.top;
  const h = hitTl(x0, y0);
  const tAt = ev => x2t(ev.clientX - r.left) * 1000;
  if (document.activeElement && /^(TEXTAREA|INPUT)$/.test(document.activeElement.tagName)) document.activeElement.blur();
  if (h.kind === "ruler" || (S.busy && h.kind !== "body")) {
    seek(tAt(e)); dragTl = { kind: "scrub" };
  } else if (h.kind === "empty") {                // протяжка по пустому месту — выделить промежуток под новый титр
    const [lo, hi] = gapAround(tAt(e));
    S.range = { a: tAt(e), b: tAt(e) }; dragTl = { kind: "range", x0, lo, hi }; placePlus();
  } else if (h.kind === "body") {
    const group = S.sel.has(h.c.id) ? S.cues.filter(c => S.sel.has(c.id)) : [h.c];
    dragTl = { kind: "move", c: h.c, group, orig: group.map(c => [c.start, c.end]), t0: tAt(e), moved: false, x0 };
    if (e.ctrlKey || e.shiftKey) selectCue(h.c.id, { ctrl: e.ctrlKey, shift: e.shiftKey, reveal: false });
  } else {
    const c = h.c, neighbor = h.kind === "start" ? S.cues[c._i - 1] : S.cues[c._i + 1];
    const roll = e.altKey && neighbor ? neighbor : null;
    dragTl = { kind: h.kind, c, roll, orig: [c.start, c.end], rollOrig: roll ? [roll.start, roll.end] : null, moved: false, t0: tAt(e), x0 };
  }
  const mv = ev => {
    const t = tAt(ev), d = dragTl;
    if (d.kind === "scrub") { seek(t); return; }
    if (d.kind === "range") { S.range.b = clamp(t, d.lo, d.hi); d.moved = Math.abs(ev.clientX - r.left - d.x0) >= 3; placePlus(); drawTl(); return; }
    if (S.busy) return;
    if (!d.moved && Math.abs(ev.clientX - r.left - d.x0) < 3) return;
    if (!d.moved) { pushUndo(); d.moved = true; }
    const mg = magnetMs();
    if (d.kind === "move") {
      let dt = Math.round(t - d.t0);
      const first = d.group[0], last = d.group[d.group.length - 1];
      const prev = S.cues[first._i - 1], next = S.cues[last._i + 1];
      const prevOut = prev && !d.group.includes(prev), nextOut = next && !d.group.includes(next);
      // магнит: рядом с соседом — встать встык (1 мс)
      if (prevOut) { const gap = d.orig[0][0] + dt - prev.end; if (gap > 1 && gap < mg) dt -= gap - 1; }
      if (nextOut) { const gap = next.start - (d.orig[d.orig.length - 1][1] + dt); if (gap > 1 && gap < mg) dt += gap - 1; }
      const minDt = -(d.orig[0][0] - (prevOut ? prev.end + 1 : 0));
      const maxDt = nextOut ? (next.start - 1) - d.orig[d.orig.length - 1][1] : 1e12;
      dt = clamp(dt, minDt, maxDt);
      d.group.forEach((c, k) => { c.start = d.orig[k][0] + dt; c.end = d.orig[k][1] + dt; touch(c.id); updateRow(c.id); });
    } else if (d.kind === "start") {
      const c = d.c, prev = S.cues[c._i - 1];
      let v = Math.round(clamp(t, 0, c.end - 50));
      if (d.roll) { v = Math.max(v, d.roll.start + 50); d.roll.end = v - (d.orig[0] - d.rollOrig[1]); touch(d.roll.id); updateRow(d.roll.id); }
      else if (prev) { if (v - prev.end < mg) v = prev.end + 1; v = Math.max(v, prev.end + 1); }
      c.start = v; touch(c.id); updateRow(c.id);
    } else if (d.kind === "end") {
      const c = d.c, next = S.cues[c._i + 1];
      let v = Math.round(Math.max(t, c.start + 50));
      if (d.roll) { v = Math.min(v, d.roll.end - 50); d.roll.start = v + (d.rollOrig[0] - d.orig[1]); touch(d.roll.id); updateRow(d.roll.id); }
      else if (next) { if (next.start - v < mg) v = next.start - 1; v = Math.min(v, next.start - 1); }
      if (S.dur) v = Math.min(v, S.dur);
      c.end = v; touch(c.id); updateRow(c.id);
    }
    drawTl(); updateOverlay();
  };
  const up = ev => {
    removeEventListener("mousemove", mv); removeEventListener("mouseup", up);
    const d = dragTl; dragTl = null;
    if (!d) return;
    if (d.kind === "range") { if (!d.moved) { S.range = null; seek(tAt(ev)); } placePlus(); drawTl(); return; }
    if (d.moved) { markDirty(); drawTl(); }
    else if (d.kind !== "scrub" && d.c && !ev.ctrlKey && !ev.shiftKey) clickCueAt(d.c, tAt(ev));   // один клик — выделить
  };
  addEventListener("mousemove", mv); addEventListener("mouseup", up);
});
// колесо: прокрутка до конца файла (последний титр у правого края); Alt+колесо — можно дальше; Ctrl — зум
tlTop.addEventListener("wheel", e => {
  e.preventDefault();
  const r = tlTop.getBoundingClientRect();
  if (e.ctrlKey) return zoom(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - r.left);
  if (!video.paused) S.noFollow = true;
  const d = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) / S.view.pps;
  const span = tlW() / S.view.pps, end = Math.max(S.dur, ...S.cues.map(c => c.end)) / 1000;
  const max = Math.max(0, e.altKey ? end - span * .5 : end - span);
  S.view.t0 = clamp(S.view.t0 + d * 1.2, 0, Math.max(max, Math.min(S.view.t0, max + span)));
  if (!e.altKey && S.view.t0 > max) S.view.t0 = Math.max(max, S.view.t0 - Math.abs(d * 1.2));
  placePlus(); drawTl();
}, { passive: false });
// Alt + колесо вне таймлайна ничего не прокручивает
addEventListener("wheel", e => { if (e.altKey && e.target !== tlTop) { e.preventDefault(); e.stopPropagation(); } }, { capture: true, passive: false });
$("#list").addEventListener("wheel", () => { if (!video.paused) S.noFollow = true; }, { passive: true });
tlTop.addEventListener("contextmenu", e => {
  e.preventDefault();
  const r = tlTop.getBoundingClientRect(), x = e.clientX - r.left, h = hitTl(x, e.clientY - r.top);
  const t = x2t(x) * 1000;
  if (h.c && !S.sel.has(h.c.id)) selectCue(h.c.id, { reveal: false });
  const items = [];
  if (!h.c) {
    const inRange = S.range && t >= Math.min(S.range.a, S.range.b) && t <= Math.max(S.range.a, S.range.b);
    if (inRange) items.push(["Add subtitle for the selection", "", () => addCueRange(Math.min(S.range.a, S.range.b), Math.max(S.range.a, S.range.b))]);
    items.push(["Add subtitle filling the gap", "Insert", () => { const [a, b] = gapAround(t); addCueRange(a, b); }]);
  } else {
    items.push(["Split at playhead", "F1", () => splitCue("video")], null);
    if (S.sel.size >= 2) items.push(["Merge selected", "F2", mergeCues]);
    items.push(["Merge with previous", "", () => mergeWith(h.c.id, -1), !S.cues[h.c._i - 1]]);
    items.push(["Merge with next", "F2", () => mergeWith(h.c.id, 1), !S.cues[h.c._i + 1]], null);
    items.push(["Record voice edit", "", () => toggleRec(h.c.id)], null);
    items.push(["Delete", "Del", deleteSel, !S.sel.size]);
  }
  showMenu(e.clientX, e.clientY, items);
});

// ═══════════════════════════ голос ═══════════════════════════
async function startRec(id) {
  if (S.rec || !S.file) return;
  if (!cueById(id)) return;
  if (S.partial && S.partial.cue !== id && ![...waitCue.values()].includes(S.partial.cue)) dropPartial(S.partial.cue);
  S.rec = { id, rec: null };
  const rec = await api("rec_start", id);
  if (!rec) { S.rec = null; return; }
  S.rec.rec = rec;
  if (S.rec.stopAsap) stopRec();
}
async function stopRec() {
  if (!S.rec) return;
  if (!S.rec.rec) { S.rec.stopAsap = true; return; }
  S.rec = null;
  await api("rec_stop");
}
function toggleRec(id) { if (S.rec) { const same = S.rec.id === id; stopRec(); if (!same) setTimeout(() => startRec(id), 120); } else startRec(id); }
const waitCue = new Map();      // запись -> титр, пока её финальный текст распознаётся
function dropPartial(cue) { if (S.partial && S.partial.cue === cue) { S.partial = null; const c = cueById(cue), r = rows.get(cue); c && r && paintNote(c, r); } }
function paintWait(cue) { const r = rows.get(cue); r && r.mic.classList.toggle("wait", [...waitCue.values()].includes(cue)); }
on("rec", d => {
  const r = rows.get(d.cue);
  if (d.state === "on") { r?.mic.classList.add("rec"); }
  if (d.state === "off") {
    r?.mic.classList.remove("rec"); r?.mic.style.setProperty("--lv", 0);
    if (d.queued) {
      S.waiting.add(d.rec); waitCue.set(d.rec, d.cue); paintWait(d.cue);
      // финал не пришёл (распознавание упало / пустая запись) — не висеть «обработкой» вечно
      setTimeout(() => { if (waitCue.has(d.rec)) { S.waiting.delete(d.rec); waitCue.delete(d.rec); dropPartial(d.cue); paintWait(d.cue); } }, 30000);
    } else dropPartial(d.cue);
  }
  if (d.state === "error") { toast(d.msg, "err"); S.rec = null; }
});
on("level", d => { const r = rows.get(d.cue); r?.mic.style.setProperty("--lv", d.v); });
on("asr_text", d => {
  const c = cueById(d.cue), r = rows.get(d.cue);
  if (!d.final) {
    if (d.text) { S.partial = { cue: d.cue, text: d.text }; c && r && paintNote(c, r); }
    return;
  }
  S.waiting.delete(d.rec); waitCue.delete(d.rec); paintWait(d.cue);
  if (S.partial && S.partial.cue === d.cue) S.partial = null;
  if (d.error) toast("Recognition: " + d.error, "err");
  if (!c) { if (d.text) toast(`Voice edit for a cue that no longer exists: "${d.text}"`, "", 6000); return; }
  if (d.text) c.note = (c.note.trim() ? c.note.trim() + " " : "") + d.text.trim();
  if (r) { paintNote(c, r); if (document.activeElement === r.note) r.note.value = c.note; r.note.scrollTop = r.note.scrollHeight; }
  updateTop(); drawTl(); savePending();
});
on("asr", d => { if (d.asr === "missing" || d.asr === "error") toast(d.msg || "Voice recognition unavailable", "err", 6000); });

// боковая кнопка мыши (по умолчанию 4-я = «назад»): держишь — правка для титра под курсором (или текущего)
const isSide = b => b === 3 || b === 4;
addEventListener("mousedown", e => {
  if (!isSide(e.button)) return;
  if (window.SaturniDebug && SaturniDebug.active) return;      // в режиме отладки кнопка принадлежит отладке
  e.preventDefault(); e.stopPropagation();
  if (e.button !== S.set.holdButton || S.rec) return;
  let id = e.target.closest?.(".row")?.dataset.id;
  if (!id && e.target === tlTop) { const r = tlTop.getBoundingClientRect(); id = hitTl(e.clientX - r.left, e.clientY - r.top).c?.id; }
  id = id || S.cur;
  if (!id) return;
  if (id !== S.cur) selectCue(id, { seek: false, scroll: true });
  startRec(id);
}, true);
addEventListener("mouseup", e => {
  if (!isSide(e.button)) return;
  if (window.SaturniDebug && SaturniDebug.active) return;
  e.preventDefault(); e.stopPropagation();
  if (e.button === S.set.holdButton) stopRec();
}, true);
addEventListener("auxclick", e => { if (isSide(e.button)) e.preventDefault(); }, true);
addEventListener("blur", () => { if (S.rec) stopRec(); });

// ═══════════════════════════ Apply / Claude ═══════════════════════════
async function waitRecognition() {
  if (S.rec) await stopRec();
  const t0 = Date.now();
  while (S.waiting.size && Date.now() - t0 < 20000) await new Promise(r => setTimeout(r, 150));
}
function stateForApply() {
  return { cues: S.cues.map(c => ({ id: c.id, mk: c.mk, start: c.start, end: c.end, text: c.text, note: c.note, caret: c.caret, mark: c.mark, hist: c.hist })) };
}
async function doApply() {
  if (!S.file) return;
  if (S.busy) return stopClaude();
  await waitRecognition();
  const st = stateForApply();
  const n = st.cues.filter(c => (c.note || "").trim()).length;
  if (!n && !S.dirty) { updateTop(); return; }          // сохранять нечего: кнопка и так серая
  await savePending();
  const r = await api("apply", st);
  updateTop();
  if (!r.ok) return toast(r.msg || "Failed", "err");
  if (r.manual) { afterWrite(r.hash); flashDone(); return; }
  S.sent = new Map(st.cues.filter(c => (c.note || "").trim()).map(c => [c.id, c.note]));   // что ушло Claude
  addMsg({ role: "user", kind: "apply", text: `Apply — ${n} voice edit${n > 1 ? "s" : ""}`,
    notes: st.cues.map((c, i) => ({ n: i + 1, note: (c.note || "").trim() })).filter(x => x.note) });
  S.busy = true; live = { anyText: false }; setChatStatus("Working…"); updateTop(); for (const id of rows.keys()) updateRow(id);
}
// Save All: этот файл — как раньше (ручные правки сразу, голосовые — Claude), остальные файлы с неприменённым — в фоне:
// только ручные пишутся сразу, с голосовыми встают в очередь Claude
async function saveAll() {
  if (!S.file) return;
  if (S.busy) return stopClaude();
  await waitRecognition(); await savePending();
  const n = S.cues.filter(c => c.note.trim()).length;
  if (n || S.dirty) await doApply();
  if (S.others) {
    const r = await api("save_all");
    if (r && !r.ok) toast(r.msg || "Failed", "err");
    S.others = 0;
    if (!n && !S.dirty && r && r.ok) flashDone();
  }
  updateTop();
}
async function countOthers() {
  const files = await api("pending_files");
  S.others = S.file ? (files || []).filter(f => f.srt !== S.file.srt).length : 0;
  updateTop();
}
async function applyAll() {                      // голосовые правки во всех файлах — по очереди
  if (S.busy) return;
  await waitRecognition(); await savePending();
  const r = await api("apply_all");
  if (!r.ok) return toast(r.msg || "Failed", "err");
  toast(`Applying voice edits in ${r.files} file${r.files > 1 ? "s" : ""}, one by one`, "", 4000);
}
function stopClaude() {
  modal("Stop Claude?", "The edits stay in their fields; nothing is applied.", [["Keep working", "btn2", null], ["Stop", "btn2 pri", () => api("claude_stop")]]);
}
function afterWrite(hash) { S.dirty = false; S.hash = hash; for (const id of rows.keys()) updateRow(id); updateTop(); savePending(); }
async function saveManual() {
  if (!S.file || S.busy) return;
  if (!S.dirty) return;
  const r = await api("save", stateForApply().cues);
  if (!r.ok) return toast(r.msg || "Failed", "err");
  afterWrite(r.hash); flashDone();
}
async function saveAs() {
  if (!S.file) return;
  const r = await api("save_as", stateForApply().cues);
  if (r.ok) toast("Saved as " + r.path, "ok", 5000); else if (!r.cancel) toast(r.msg || "Failed", "err");
}
async function sendChat() {
  const ta = $("#chatIn"), txt = ta.value.trim();
  if (!txt || !S.file || S.busy) return;
  await waitRecognition();
  const r = await api("apply", stateForApply(), txt);
  if (!r.ok) return toast(r.msg || "Failed", "err");
  ta.value = "";
  addMsg({ role: "user", kind: "chat", text: txt });
  S.busy = true; live = { anyText: false }; setChatStatus("Working…"); updateTop();
}

let live = null;
function renderChat(items) {
  const b = $("#chatB"); b.textContent = "";
  if (!items.length) b.append(el("div", "msg intro", "Apply sends the voice edits to Claude. You can also write here."));
  items.forEach(addMsg);
  b.scrollTop = b.scrollHeight;
  setChatStatus();
}
function md(s) {
  const lines = esc(s).split("\n"); let out = "", list = null;
  for (let ln of lines) {
    ln = ln.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    const m = ln.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)/);
    if (m) { if (!list) { out += "<ul>"; list = true; } out += `<li>${m[1]}</li>`; continue; }
    if (list) { out += "</ul>"; list = null; }
    out += ln.trim() ? `<p>${ln}</p>` : "";
  }
  return out + (list ? "</ul>" : "");
}
function addMsg(m) {
  const b = $("#chatB");
  const stick = b.scrollTop + b.clientHeight >= b.scrollHeight - 30;
  let e;
  const st = b.querySelector(":scope > .status");                 // строка «что сейчас происходит» всегда последняя
  if (m.role === "user" && m.kind === "apply") {
    e = el("div", "msg user apply", `<div class="uh">${esc(m.text)}</div>`);
    if (m.notes?.length) e.append(el("div", "notes", m.notes.map(n => `<div><b>${n.n}</b><span>${esc(n.note)}</span></div>`).join("")));
  } else if (m.role === "user") {
    e = el("div", "msg user", esc(m.text));
  } else if (m.kind === "thinking") {
    e = thinkEl(); e._raw = (e._raw ? e._raw + "\n\n" : "") + m.text; e.querySelector(".tx").textContent = e._raw;
    if (e.isConnected) return e;
  } else if (m.kind === "tool") e = el("div", "msg tool", esc(m.text));
  else if (m.kind === "error") e = el("div", "msg error", esc(m.text));
  else if (m.role === "app") e = el("div", "msg app " + (m.kind === "info" ? "info" : ""), esc(m.text));
  else e = el("div", "msg text", md(m.text));
  if (st) b.insertBefore(e, st); else b.append(e);
  if (stick) b.scrollTop = b.scrollHeight;
  return e;
}
// мышление: одна свёрнутая серая строка «Thinking», по клику — весь текст; подряд идущие куски — в неё же
function thinkEl() {
  const b = $("#chatB"), kids = [...b.children].filter(x => !x.classList.contains("status")), last = kids[kids.length - 1];
  if (last && last.classList.contains("thinking")) return last;
  const e = el("div", "msg thinking", `<div class="th">${icon("chev")}<span>Thinking</span></div><div class="tx"></div>`);
  e.querySelector(".th").addEventListener("click", () => e.classList.toggle("open"));
  e._raw = "";
  return e;
}
// текущее действие Claude — серой строкой в конце ленты (как в Claude Code), пока он работает
function setChatStatus(t) {
  const b = $("#chatB");
  let s = b.querySelector(":scope > .status");
  $("#chatSt").textContent = S.claude ? "" : "Claude CLI not found";
  if (!t) { if (s) s.remove(); return; }
  if (!s) { s = el("div", "msg status"); b.append(s); }
  s.textContent = t;
  b.scrollTop = b.scrollHeight;
}
function endLiveBlocks() { $("#chatB").querySelectorAll(".live-text, .live-think").forEach(x => x.classList.remove("live-text", "live-think")); }
on("claude", d => {
  const b = $("#chatB");
  const mine = !d.srt || (S.file && d.srt === S.file.srt);      // прогон другого файла: в этом чате его не показываем
  if (!mine) {
    if (d.kind === "begin") toast(`Claude: applying edits in ${d.srt.split(/[\\/]/).pop()}`, "", 3000);
    if (d.kind === "done" && d.applied && d.applied.ok) toast(`${d.name}: ${d.applied.note}`, "ok", 4000);
    if (d.kind === "error") toast(`${d.name || ""}: ${d.msg}`, "err", 5000);
    return;
  }
  if (d.kind === "begin") { S.busy = true; live = { anyText: false }; setChatStatus("Working…"); updateTop(); return; }
  if (d.kind === "start") { setChatStatus("Thinking…"); return; }
  if (d.kind === "block") { endLiveBlocks(); return; }
  if (d.kind === "delta") { streamDelta(d); return; }
  if (d.kind === "tool") { endLiveBlocks(); addMsg({ role: "claude", kind: "tool", text: `${d.name}: ${d.input}` }); setChatStatus(`Using ${d.name}…`); return; }
  if (d.kind === "tool_result") { if (d.error) addMsg({ role: "claude", kind: "tool", text: "⚠ " + d.text }); return; }
  if (d.kind === "done" || d.kind === "error") {
    const streamedText = live && live.anyText;
    S.busy = false; live = null; setChatStatus(); endLiveBlocks();
    if (d.kind === "error") addMsg({ role: "claude", kind: "error", text: d.msg });
    else if (!streamedText && d.text) addMsg({ role: "claude", kind: "text", text: d.text });
    if (d.applied) takeApplied(d.applied);
    updateTop(); for (const id of rows.keys()) updateRow(id);
    b.scrollTop = b.scrollHeight;
  }
});
function streamDelta(d) {
  const b = $("#chatB");
  const stick = b.scrollTop + b.clientHeight >= b.scrollHeight - 30;
  const isT = d.channel === "thinking";
  if (!isT && live) live.anyText = true;
  let e;
  if (isT) {
    e = thinkEl(); if (!e.isConnected) { const st = b.querySelector(":scope > .status"); st ? b.insertBefore(e, st) : b.append(e); }
    e._raw += d.text; e.querySelector(".tx").textContent = e._raw;
  } else {
    e = [...b.querySelectorAll(".live-text")].pop();
    if (!e) { e = el("div", "msg text live-text"); e._raw = ""; const st = b.querySelector(":scope > .status"); st ? b.insertBefore(e, st) : b.append(e); }
    e._raw += d.text; e.innerHTML = md(e._raw);
  }
  if (stick) b.scrollTop = b.scrollHeight;
  setChatStatus(isT ? "Thinking…" : "Writing…");
}
function takeApplied(a) {
  if (!a.ok) return toast(a.msg || "Result rejected", "err", 6000);
  const now = new Map(S.cues.map(c => [c.id, c])), sent = S.sent || new Map();
  pushUndo();
  // сервер уже перенёс применённые правки в историю; если за время работы надиктовано новое — оставить его
  S.cues = a.cues.map(n => {
    const o = now.get(n.id), fresh = o && o.note.trim() && o.note !== sent.get(n.id);
    return mkCue(fresh ? { ...n, note: o.note, caret: o.caret, mark: o.mark } : n);
  });
  S.sent = null;
  reindex();
  S.hl = new Set(a.changed || []);
  S.sel = new Set([...S.sel].filter(id => S.byId.has(id)));
  if (!S.byId.has(S.cur)) S.cur = S.cues[0]?.id || null;
  S.dirty = false; S.hash = a.hash;
  renderList(); updateTop(); drawTl(); savePending();
  addMsg({ role: "app", kind: "applied", text: a.note });
  const un = a.unresolved || [];
  if (un.length) toast(`${un.length} edit${un.length > 1 ? "s" : ""} not done — the reason is on the edit field`, "err", 6000);
}

async function historyModal() {
  if (!S.file) return;
  const vs = await api("versions");
  const body = vs.length ? `<div class="vlist">${vs.slice().reverse().map(v => `<div><b>v${v.n}</b><span class="w">${esc(v.why)}</span><span class="a">${esc(v.at)}</span></div>`).join("")}</div>`
    : "No versions yet — they appear after the first save.";
  modal("History", body, [
    ["Open archive folder", "btn2", () => api("reveal_session")],
    ["Undo last apply", "btn2", () => histStep("undo"), vs.length < 2],
    ["Revert to original", "btn2 danger", () => histStep("original")],
    ["Close", "btn2 pri", null],
  ]);
}
async function histStep(kind) {
  if (S.busy) return;
  const r = await api("history_step", kind);
  if (!r.ok) return toast(r.msg || "Failed", "err");
  pushUndo();
  const notes = new Map(S.cues.filter(c => c.note.trim()).map(c => [c.start + "|" + c.text, c]));
  S.cues = r.cues.map(c => { const o = notes.get(c.start + "|" + c.text); return mkCue(o ? { ...c, note: o.note, caret: o.caret, mark: o.mark } : c); });
  reindex(); S.sel = new Set(); S.cur = S.cues[0]?.id; afterWrite(r.hash); renderList(); drawTl();
  toast(kind === "original" ? "Reverted to original" : "Last apply undone", "ok");
}

// ═══════════════════════════ настройки ═══════════════════════════
function settingsModal() {
  const cs = getComputedStyle(document.documentElement);
  const hex = v => { v = v.trim(); if (/^#[0-9a-f]{6}$/i.test(v)) return v; if (/^#[0-9a-f]{3}$/i.test(v)) return "#" + [...v.slice(1)].map(x => x + x).join("");
    const m = v.match(/\d+(\.\d+)?/g); return m ? "#" + m.slice(0, 3).map(x => (+x | 0).toString(16).padStart(2, "0")).join("") : "#000000"; };
  const colors = { ...(S.prefs.colors || {}) };
  const s = S.set;
  const body = `
    <div class="set-sec">Colors — change applies everywhere</div>
    <div class="set-grid">${COLOR_KEYS.map(([k, l]) => `<label class="set-row"><span>${l}</span><input type="color" data-c="${k}" value="${hex(cs.getPropertyValue("--" + k))}"></label>`).join("")}</div>
    <div class="set-sec">Editing</div>
    <div class="set-grid">
      <label class="set-row"><span>Voice: hold mouse button</span><select data-s="holdButton"><option value="3">Mouse 4 (back)</option><option value="4">Mouse 5 (forward)</option></select></label>
      <label class="set-row"><span>Timeline magnet, px</span><input class="num" type="number" min="0" max="60" data-s="magnetPx"></label>
      <label class="set-row"><span>Bridge gaps under, ms (Shift+F3)</span><input class="num" type="number" min="1" max="2000" data-s="bridgeMs"></label>
      <label class="set-row"><span>Subtitle text size, px</span><input class="num" type="number" min="10" max="22" step=".5" data-s="listFont"></label>
      <label class="set-row"><span>Selecting a cue moves the video to it</span><input type="checkbox" data-s="seekOnSelect"></label>
      <label class="set-row"><span>List follows playback</span><input type="checkbox" data-s="followPlayback"></label>
      <label class="set-row set-wide"><span>Keep the caret visible when it stands at the very end of the text</span><input type="checkbox" data-s="caretAtEnd"></label>
    </div>
    <div class="set-sec">Design</div>
    <div class="set-grid">
      <label class="set-row"><span>Subtitle text field</span><select data-s="textStyle"><option value="outline">Outline</option><option value="fill">Gray fill</option></select></label>
      <label class="set-row"><span>Voice edit field and mic</span><select data-s="noteStyle"><option value="outline">Outline</option><option value="fill">Gray fill</option></select></label>
    </div>
    <div class="set-sec">Waveform</div>
    <div class="set-grid">
      <label class="set-row"><span>Style</span><select data-s="waveStyle"><option value="solid">Solid</option><option value="bars">Bars</option><option value="blocks">Segments</option></select></label>
      <label class="set-row" data-w="bars blocks"><span>Bar width, px</span><input class="num" type="number" min="1" max="8" data-s="waveBar"></label>
      <label class="set-row" data-w="bars blocks"><span>Gap between bars, px</span><input class="num" type="number" min="1" max="6" data-s="waveGap"></label>
      <label class="set-row" data-w="bars"><span>Rounded bars</span><input type="checkbox" data-s="waveRound"></label>
      <label class="set-row" data-w="blocks"><span>Segment height, px</span><input class="num" type="number" min="1" max="8" data-s="waveSeg"></label>
      <label class="set-row" data-w="blocks"><span>Gap between segments, px</span><input class="num" type="number" min="1" max="4" data-s="waveSegGap"></label>
    </div>
    <div class="set-sec">Claude</div>
    <div class="set-grid">
      <label class="set-row"><span>Model</span><select data-p="model"><option value="opus">Opus</option><option value="sonnet">Sonnet</option></select></label>
      <label class="set-row"><span>Effort</span><select data-p="effort"><option value="">Default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="max">Max</option></select></label>
      <label class="set-row set-wide"><span>Claude CLI path (empty = find automatically)</span></label>
      <input class="set-wide" data-p="claude_exe" spellcheck="false" placeholder="${esc(S.claude || "")}">
    </div>`;
  modal("Settings", body, [
    ["Reset colors", "btn2", () => { S.prefs.colors = {}; applyColors({}); api("prefs_save", { colors: {} }); setTimeout(settingsModal, 0); }],
    ["Done", "btn2 pri", null],
  ], () => {
    const m = $("#modal .modal"); m.classList.add("wide");
    m.querySelectorAll("[data-c]").forEach(i => i.addEventListener("input", () => { colors[i.dataset.c] = i.value; applyColors(colors); }));
    m.querySelectorAll("[data-s]").forEach(i => {
      const k = i.dataset.s, v = s[k];
      if (i.type === "checkbox") i.checked = !!v; else i.value = v;
      i.addEventListener(i.type === "checkbox" ? "change" : "input", () => {
        s[k] = i.type === "checkbox" ? i.checked : (isNaN(+i.value) ? i.value : Number(i.value));
        applySettings(); for (const [id, r] of rows) paintBackdrop(cueById(id), r);
        if (k.startsWith("wave")) { waveRows(); repaintAll(); }
      });
    });
    // у волны видны только настройки выбранного стиля
    const waveRows = () => m.querySelectorAll("[data-w]").forEach(r => { r.hidden = !r.dataset.w.split(" ").includes(s.waveStyle); });
    waveRows();
    m.querySelectorAll("[data-p]").forEach(i => {
      i.value = S.prefs[i.dataset.p] || "";
      i.addEventListener("change", () => { S.prefs[i.dataset.p] = i.value || null; if (i.dataset.p === "model") $("#model").value = i.value; });
    });
  }, () => {                                    // закрыли окно — сохранить
    S.prefs.colors = colors;
    api("prefs_save", { colors, settings: S.set, model: S.prefs.model, effort: S.prefs.effort || null, claude_exe: S.prefs.claude_exe || null });
    applyColors(colors); applySettings();
  });
}

// ═══════════════════════════ поиск / замена ═══════════════════════════
const F = { hits: [], i: -1 };
function openFind(repl) {
  const fb = $("#findbar"); fb.hidden = false; fb.classList.toggle("repl", !!repl);
  const a = document.activeElement;
  const sel = a?.tagName === "TEXTAREA" ? a.value.slice(a.selectionStart, a.selectionEnd) : "";
  if (sel && !sel.includes("\n")) $("#fFind").value = sel;
  $("#fFind").focus(); $("#fFind").select(); runFind();
}
function closeFind() { $("#findbar").hidden = true; F.hits.forEach(id => rows.get(id)?.row.classList.remove("found")); F.hits = []; }
function rx() {
  const q = $("#fFind").value; if (!q) return null;
  return new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $("#fCase").checked ? "g" : "gi");
}
function runFind() {
  F.hits.forEach(id => rows.get(id)?.row.classList.remove("found"));
  const r = rx(); F.hits = r ? S.cues.filter(c => { r.lastIndex = 0; return r.test(c.text); }).map(c => c.id) : [];
  F.hits.forEach(id => rows.get(id)?.row.classList.add("found"));
  F.i = -1; $("#fCnt").textContent = r ? `${F.hits.length} found` : "";
}
function findStep(d) {
  if (!F.hits.length) runFind();
  if (!F.hits.length) return;
  const curI = S.cur ? cueById(S.cur)._i : -1;
  if (F.i < 0) { F.i = d > 0 ? F.hits.findIndex(id => cueById(id)._i > curI) : F.hits.length - 1 - [...F.hits].reverse().findIndex(id => cueById(id)._i < curI); if (F.i < 0 || F.i >= F.hits.length) F.i = 0; }
  else F.i = (F.i + d + F.hits.length) % F.hits.length;
  const id = F.hits[F.i]; selectCue(id, { seek: true, scroll: true });
  const r = rows.get(id), re = rx(); re.lastIndex = 0; const m = re.exec(cueById(id).text);
  if (r && m) { cueById(id).caret = { s: m.index, e: m.index + m[0].length }; paintBackdrop(cueById(id), r); }
  $("#fCnt").textContent = `${F.i + 1} / ${F.hits.length}`;
}
function replOne() {
  const id = F.hits[F.i]; if (!id) return findStep(1);
  const c = cueById(id), re = rx(); re.lastIndex = 0;
  pushUndo(); c.text = c.text.replace(new RegExp(re.source, re.flags.replace("g", "")), $("#fRepl").value); touch(id); changed(false, [id]);
  runFind(); findStep(1);
}
function replAll() {
  const re = rx(); if (!re || S.busy) return;
  pushUndo(); let n = 0;
  for (const c of S.cues) { const t = c.text.replace(re, () => (n++, $("#fRepl").value)); if (t !== c.text) { c.text = t; touch(c.id); } }
  changed(true); runFind(); toast(`Replaced ${n}`);
}
$("#fFind").addEventListener("input", runFind);
$("#fCase").addEventListener("change", runFind);
$("#fFind").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); findStep(e.shiftKey ? -1 : 1); } if (e.key === "Escape") closeFind(); });
$("#fRepl").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); replOne(); } if (e.key === "Escape") closeFind(); });

function gotoLine() {
  modal("Go to subtitle number", `<input id="gl" placeholder="1 – ${S.cues.length}">`, [["Cancel", "btn2", null], ["Go", "btn2 pri", () => {
    const n = parseInt($("#gl").value, 10); if (n >= 1 && n <= S.cues.length) selectCue(S.cues[n - 1].id, { seek: true, scroll: true });
  }]], () => $("#gl").focus());
}

// ═══════════════════════════ меню, модалки, подсказки ═══════════════════════════
function showMenu(x, y, items) {
  const m = $("#menu"); m.textContent = "";
  for (const it of items) {
    if (!it) { m.append(el("hr")); continue; }
    const [label, key, fn, disabled] = it;
    const b = el("button", "", `<span>${esc(label)}</span>${key ? `<kbd>${esc(key)}</kbd>` : ""}`);
    b.disabled = !!disabled;
    b.addEventListener("click", () => { hideMenu(); fn(); });
    m.append(b);
  }
  m.hidden = false;
  const r = m.getBoundingClientRect();
  m.style.left = clamp(x, 4, innerWidth - r.width - 4) + "px";
  m.style.top = clamp(y, 4, innerHeight - r.height - 4) + "px";
}
function hideMenu() { $("#menu").hidden = true; }
addEventListener("mousedown", e => { if (!e.target.closest("#menu")) hideMenu(); });
function modal(title, body, buttons, onShow, onClose) {
  const v = $("#modal"); v.textContent = "";
  const m = el("div", "modal", `<h2>${esc(title)}</h2><div class="mb">${body}</div>`);
  const f = el("div", "mf");
  const close = () => { if (v.hidden) return; v.hidden = true; onClose && onClose(); };
  for (const [label, cls, fn, dis] of buttons) {
    const b = el("button", cls, esc(label)); b.disabled = !!dis;
    b.addEventListener("click", () => { close(); fn && fn(); }); f.append(b);
  }
  m.append(f); v.append(m); v.hidden = false;
  v.onclick = e => { if (e.target === v) close(); };
  m.addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Escape") close(); if (e.key === "Enter" && e.target.tagName !== "SELECT") f.lastChild.click(); });
  onShow && onShow();
}
const tip = $("#tooltip"); let tipT;
document.addEventListener("mouseover", e => {
  const t = e.target.closest?.("[data-tip]"); clearTimeout(tipT); tip.classList.remove("on");
  if (!t) return;
  tipT = setTimeout(() => {
    tip.textContent = t.dataset.tip; const r = t.getBoundingClientRect(); tip.classList.add("on");
    const w = tip.offsetWidth; tip.style.left = clamp(r.left + r.width / 2 - w / 2, 4, innerWidth - w - 4) + "px";
    tip.style.top = (r.bottom + 6 + tip.offsetHeight > innerHeight ? r.top - tip.offsetHeight - 6 : r.bottom + 6) + "px";
  }, 450);
});

function brandMenu() {
  const r = $("#brand").getBoundingClientRect();
  showMenu(r.left, r.bottom + 4, [
    ["Open…", "Ctrl+O", openDialog],
    ["Show file in Explorer", "", () => api("reveal"), !S.file],
    ["Open archive folder", "", () => api("reveal_session"), !S.file],
    null,
    ["Save manual changes", "Ctrl+S", saveManual, !S.file],
    ["Save As…", "", saveAs, !S.file],
    null,
    ["Go to subtitle…", "Ctrl+G", gotoLine, !S.file],
    ["Bridge small gaps", "Shift+F3", bridgeGaps, !S.file],
    ["Settings…", "", settingsModal],
    ["Toggle light / dark", "", toggleTheme],
    ["Reload window", "", () => location.reload()],
  ]);
}
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t; api("prefs_save", { theme: t }); themeBar(); readPal(); repaintAll();
}
function themeBar() { const dark = document.documentElement.dataset.theme === "dark"; try { api("titlebar", dark, dark ? "#2a2a33" : "#d0d0da"); } catch (e) { /* dev */ } }

// ═══════════════════════════ кнопки ═══════════════════════════
const ACTS = {
  "open": openDialog, "prev-file": () => navFile(-1), "next-file": () => navFile(1),
  "find": () => openFind(false), "replace": () => openFind(true), "find-next": () => findStep(1), "find-prev": () => findStep(-1),
  "find-close": closeFind, "repl-one": replOne, "repl-all": replAll,
  "history": historyModal, "apply": saveAll, "settings": settingsModal, "chat-mic": toggleChatRec,
  "reset-marks": () => resetMarks(S.cues.filter(hasMark).map(c => c.id)),
  "tl-plus": () => S.range && addCueRange(Math.min(S.range.a, S.range.b), Math.max(S.range.a, S.range.b)),
  "play": playPause, "back500": () => seek(vt() - 500), "fwd500": () => seek(vt() + 500),
  "zoom-in": () => zoom(1.4), "zoom-out": () => zoom(1 / 1.4), "zoom-fit": zoomFit,
  "chat-send": sendChat, "chat-new": async () => { await api("claude_new_chat"); addMsg({ role: "app", kind: "info", text: "New Claude conversation" }); },
  "session-dir": () => api("reveal_session"),
  "win-min": () => api("win_min"), "win-max": async () => { const m = await api("win_max"); document.body.classList.toggle("max", m); },
  "win-close": () => closeWin(),
};
document.addEventListener("click", e => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const f = ACTS[b.dataset.act]; f && f();
});
$("#brand").addEventListener("click", brandMenu);
$("#applyBtn").addEventListener("contextmenu", async e => {
  e.preventDefault();
  const x = e.clientX, y = e.clientY;
  await savePending();
  const files = (await api("pending_files")).filter(f => f.n), n = files.reduce((s, f) => s + f.n, 0);
  showMenu(x, y, [
    ["Apply voice edits in this file", "Ctrl+Enter", doApply, !S.cues.some(c => c.note.trim()) || S.busy],
    [files.length ? `Apply voice edits in all files · ${files.length} file${files.length > 1 ? "s" : ""}, ${n} edit${n > 1 ? "s" : ""}` : "Apply voice edits in all files", "", applyAll, !files.length || S.busy],
    null,
    ["Save manual changes only", "Ctrl+S", saveManual, !S.file || !S.dirty],
    ["Save As…", "", saveAs, !S.file],
  ]);
});
// диктовка в поле чата: тот же микрофон, текст встаёт в поле сообщения
let chatRec = null;
async function toggleChatRec() {
  if (chatRec) { chatRec = null; $("#chatMic").classList.remove("rec"); await api("rec_stop"); return; }
  if (S.rec || !S.file) return;
  const rid = await api("rec_start", "chat");
  if (rid) { chatRec = rid; $("#chatMic").classList.add("rec"); }
}
function chatVoice(type, d) {
  if (d.cue !== "chat") return false;
  const ta = $("#chatIn");
  if (type === "level") $("#chatMic").style.setProperty("--lv", d.v);
  if (type === "rec" && d.state !== "on") $("#chatMic").classList.remove("rec");
  if (type === "asr_text") {
    if (!d.final) { ta.placeholder = d.text || "…"; return true; }
    ta.placeholder = "Message Claude about this file…";
    if (d.text) { ta.value = (ta.value.trim() ? ta.value.trim() + " " : "") + d.text.trim(); }
  }
  return true;
}
// клик мимо полей ввода снимает с них фокус — иначе пробел для воспроизведения уходит в текст
addEventListener("mousedown", e => {
  const a = document.activeElement, t = e.target;
  if (!a || !/^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName)) return;
  if (t.closest && t.closest("textarea, input, select, [contenteditable], .modal, .menu, #sdbg-root, .findbar, .c-t")) return;
  if (t === tlTop) return;                        // таймлайн решает сам (клик по титру ставит каретку в его текст)
  a.blur();
}, true);
$("#model").addEventListener("change", e => { S.prefs.model = e.target.value; api("prefs_save", { model: e.target.value }); });
$("#chatIn").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });
// закрыть окно: если Claude работает или есть несохранённые ручные правки — спросить
async function closeWin(force) {
  if (!force && (S.busy || S.dirty)) {
    const what = [S.dirty && "There are unsaved changes in this file.", S.busy && "Claude is still applying the edits."].filter(Boolean).join(" ");
    const btns = [["Cancel", "btn2", null], ["Close without saving", "btn2 danger", () => closeWin(true)]];
    if (S.dirty && !S.busy) btns.push(["Save and close", "btn2 pri", async () => { await saveManual(); closeWin(true); }]);
    return modal("Close Subs Studio?", esc(what) + (S.cues.some(c => c.note.trim()) ? " Voice edits are kept until you apply them." : ""), btns);
  }
  await flushBeforeLeave(); api("win_close");
}
on("close_request", () => closeWin());
on("win", d => document.body.classList.toggle("max", !!d.max));
on("drop", paths => { $("#dropVeil").classList.remove("on"); if (paths[0]) flushBeforeLeave().then(() => openPath(paths[0])); });
addEventListener("dragenter", () => $("#dropVeil").classList.add("on"));
$("#dropVeil").addEventListener("dragleave", () => $("#dropVeil").classList.remove("on"));
addEventListener("drop", e => { e.preventDefault(); $("#dropVeil").classList.remove("on"); });
addEventListener("dragover", e => e.preventDefault());
on("peaks", d => {
  if (!S.file?.video || d.video !== S.file.video.path) return;
  if (d.error) return toast("Waveform: " + d.error, "err");
  const bin = atob(d.b64); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  S.peaks = a; S.rate = d.rate;
  repaintAll();
});

$("#tbDrag").addEventListener("mousedown", e => { if (e.button === 0) api("win_drag"); });
$("#tbDrag").addEventListener("dblclick", () => ACTS["win-max"]());
document.querySelectorAll("#rsz i").forEach(i => i.addEventListener("mousedown", e => { e.preventDefault(); api("win_size", i.dataset.edge); }));

document.querySelectorAll(".split").forEach(sp => sp.addEventListener("mousedown", e => {
  e.preventDefault(); sp.classList.add("drag");
  const kind = sp.dataset.split, root = document.documentElement.style;
  const mv = ev => {
    if (kind === "list") { const w = clamp(ev.clientX, 420, innerWidth - 360); root.setProperty("--list-w", w + "px"); S.prefs.list_w = w; }
    if (kind === "video") { const rp = document.querySelector(".rightpane").getBoundingClientRect(); const h = clamp(ev.clientY - rp.top, 140, rp.height - 240); root.setProperty("--video-h", h + "px"); S.prefs.video_h = h; }
    if (kind === "tl") { const h = clamp(innerHeight - ev.clientY, 110, innerHeight - 360); root.setProperty("--tl-h", h + "px"); S.prefs.tl_h = h; }
  };
  const up = () => { sp.classList.remove("drag"); removeEventListener("mousemove", mv); removeEventListener("mouseup", up);
    api("prefs_save", { list_w: S.prefs.list_w, video_h: S.prefs.video_h, tl_h: S.prefs.tl_h }); };
  addEventListener("mousemove", mv); addEventListener("mouseup", up);
}));

// ═══════════════════════════ горячие клавиши (как в Subtitle Edit у Saturni) ═══════════════════════════
function inText() { const a = document.activeElement; return a && (a.tagName === "TEXTAREA" || a.tagName === "INPUT" || a.tagName === "SELECT"); }
addEventListener("keydown", e => {
  if (!$("#modal").hidden) return;
  if (window.SaturniDebug && (SaturniDebug.owns(e) || (SaturniDebug.active && e.key === "Escape"))) return;
  const k = e.key, C = e.ctrlKey, A = e.altKey, Sh = e.shiftKey;
  // с Ctrl/Alt буква берётся по клавише, а не по раскладке: Ctrl+Z на русской — тоже отмена
  const key = (C || A) && /^Key[A-Z]$/.test(e.code) ? e.code.slice(3) : (k.length === 1 ? k.toUpperCase() : k);
  const combo = (C ? "C+" : "") + (A ? "A+" : "") + (Sh ? "S+" : "") + key;
  // фокус в тексте дан кликом по таймлайну: пробел — воспроизведение; начал печатать — фокус настоящий
  if (S.soft) {
    if (combo === " " && document.activeElement?.closest?.(".c-x")) { e.preventDefault(); e.stopPropagation(); playPause(); return; }
    if (!["Shift", "Control", "Alt", "Meta"].includes(k)) { S.soft = false; document.querySelectorAll("textarea.soft").forEach(x => x.classList.remove("soft")); }
  }
  const txt = inText();
  const ar = document.activeElement?.closest?.(".row");
  if (ar && ar.dataset.id !== S.cur && cueById(ar.dataset.id)) selectCue(ar.dataset.id, { keepIfSel: true, seek: false });
  const map = {
    "F1": () => splitCue("video"), "S+F1": () => splitCue("caret"), "A+F1": () => splitCue("middle"),
    "F2": mergeCues, "C+S+M": mergeSelected, "F3": unbreak, "C+R": autoBreak,
    "S+F3": bridgeGaps, "S+F4": () => { const c = curCue(); if (c) seek(Math.abs(vt() - c.start) < 30 ? c.end : c.start); },
    "F9": () => setStart(true), "C+ ": () => setStart(true), "F10": () => setEnd(true), "F11": () => setStart(false), "F12": () => setEnd(false),
    "S+F10": () => { const c = curCue(); if (c) playRange(Math.max(0, c.start - 1000), c.end); },
    "C+F5": () => { const ids = S.cues.filter(c => S.sel.has(c.id)); if (ids.length) playRange(ids[0].start, ids[ids.length - 1].end); },
    "C+P": playPause, "C+A+P": () => video.pause(),
    "A+ArrowLeft": () => seek(vt() - 500), "A+ArrowRight": () => seek(vt() + 500),
    "C+Q": () => seek(vt() - 100), "C+E": () => seek(vt() + 100),
    "A+Enter": () => moveCur(1, { focusText: txt }), "A+ArrowDown": () => moveCur(1, { focusText: txt }), "A+ArrowUp": () => moveCur(-1, { focusText: txt }),
    "C+L": () => S.cur && scrollToCue(S.cur), "C+G": gotoLine,
    "C+F": () => openFind(false), "C+H": () => openFind(true), "C+F3": () => findStep(1),
    "C+O": openDialog, "C+S": saveManual, "C+A+S": saveAs,
    "C+Z": undo, "C+Y": redo, "C+S+Z": redo,
    "C+U": () => caseSel(false), "C+S+U": () => caseSel(true), "C+I": italic,
    "Insert": () => insertCue("video"), "A+Insert": () => insertCue("after"), "C+S+Insert": () => insertCue("before"),
    "C+S+E": () => extend(1), "A+S+E": () => extend(-1), "C+S+W": () => extend(1), "A+S+W": () => extend(-1),
    "C+PageUp": () => navFile(-1), "C+PageDown": () => navFile(1),
    "C+Enter": doApply,
    "Escape": () => { if (!$("#findbar").hidden) closeFind(); else if (txt) document.activeElement.blur(); hideMenu(); },
  };
  const textOnly = {
    " ": playPause, "Delete": deleteSel, "ArrowDown": () => moveCur(1), "ArrowUp": () => moveCur(-1),
    "S+ArrowDown": () => moveCur(1, { shift: true }), "S+ArrowUp": () => moveCur(-1, { shift: true }),
    "ArrowLeft": () => seek(vt() - 1000), "ArrowRight": () => seek(vt() + 1000),
    "C+A": () => { S.sel = new Set(S.cues.map(c => c.id)); updateSelClasses(); drawTl(); },
    "Enter": () => S.cur && rows.get(S.cur)?.ta.focus(),
  };
  let f = map[combo];
  if (!f && !txt) f = textOnly[combo];
  if (txt && ["C+Z", "C+Y", "C+S+Z"].includes(combo) && document.activeElement.closest?.(".chat, .findbar, .modal")) f = null;
  if (f) { e.preventDefault(); e.stopPropagation(); f(); return; }
  if (/^F\d+$/.test(k) || (C && "RPUGHLOSJNTW".includes(key) && !txt)) e.preventDefault();
}, true);

// ═══════════════════════════ старт ═══════════════════════════
async function boot() {
  paintIcons();
  const r = await api("init");
  S.prefs = r.prefs || {}; S.claude = r.claude;
  S.set = { ...SET_DEFAULTS, ...(S.prefs.settings || {}) };
  document.documentElement.dataset.theme = S.prefs.theme || "dark";
  const st = document.documentElement.style;
  if (S.prefs.list_w) st.setProperty("--list-w", S.prefs.list_w + "px");
  if (S.prefs.video_h) st.setProperty("--video-h", S.prefs.video_h + "px");
  if (S.prefs.tl_h) st.setProperty("--tl-h", S.prefs.tl_h + "px");
  $("#model").value = S.prefs.model || "opus";
  applyColors(S.prefs.colors || {});
  if (window.SaturniDebug) SaturniDebug.init({ api, app: "Saturni · Subs Studio", context: () => (S.file ? S.file.name : ""),
    gear: '[data-act="settings"]', holdButton: S.set.holdButton });
  applySettings();
  document.body.classList.remove("booting");
  themeBar(); setChatStatus(); resizeTl();
  if (!S.claude) addMsg({ role: "app", kind: "error", text: "Claude CLI not found — Apply with voice edits won't work. Saving still works." });
  if (r.start_file) openPath(r.start_file);
}
if (DEV) {
  boot();
  setInterval(async () => { const evs = await api("__events"); if (evs && evs.length) window.__emit(evs); }, 120);
} else if (window.pywebview && window.pywebview.api) boot();
else addEventListener("pywebviewready", boot);
