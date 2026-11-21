// Saturni · Debug — «умная отладка» поверх приложения. Подключение — см. saturni_debug.py.
// Режим (кнопка 🐞 или Ctrl+Shift+D): выделить область мышью (скруглённый прямоугольник, круг, от руки)
// → заметка с номером; клик без протяжки проходит в приложение, колесо прокручивает то, что под курсором.
// Рисунки ручкой — отдельный слой. Заметки, обводки и нижний бар можно таскать; заметка — это номер
// слева и поле текста постоянного размера (меняется только за край). Заметка привязана к прокручиваемой
// панели под областью и к «контексту» приложения (вкладка/файл). Голос: кнопка 🎤 или держать кнопку мыши
// (по умолчанию 4-ю) над заметкой; речь делится на блоки по паузам, каждый блок дообрабатывается сам,
// новую запись можно начинать, не дожидаясь предыдущей. Режим «весь экран»: окно разворачивается на
// снимок экрана, и выделять можно что угодно, не только своё приложение. Всё лежит в <приложение>/⿻/@debug/<дата сессии>/.
(function () {
  "use strict";
  const D = window.SaturniDebug = { active: false };
  let cfg = null, root, svg, catchEl, bubs, bar, toggleBtn, pop, scrImg;
  let state = { next_n: 1, notes: [], marks: [] };
  const live = new Map();          // n -> {bub, el (якорь), pend[]}
  let drawing = null, openN = null, rec = null, saveT = null, raf = 0, zTop = 10, moving = null, screenMode = false;
  let lastOnly = load("sdbg-last", false), fade = load("sdbg-fade", true), mouse = [-1e4, -1e4];
  const pen = load("sdbg-pen", { kind: "pen", color: "#ff4d4d", size: 4 });
  let tool = load("sdbg-tool", "rect");                      // mouse | rect | ellipse | free | pen
  let shape = load("sdbg-shape", tool === "ellipse" || tool === "free" ? tool : "rect");   // чем выделяет «область»
  // цвет ручки — точка на полосе: радуга слева, справа после розового — поле белого, потом через серый к чёрному
  const HUES = [[0, "#ff4d4d"], [.1, "#ffa94d"], [.2, "#ffd166"], [.31, "#5be08f"], [.42, "#4dd8e0"], [.53, "#4db2ff"],
    [.64, "#8f6bff"], [.74, "#ff5ccf"], [.81, "#ffffff"], [.86, "#ffffff"], [.98, "#000000"], [1, "#000000"]];
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  function colorAt(t) {
    let i = 1; while (i < HUES.length - 1 && HUES[i][0] < t) i++;
    const [p0, c0] = HUES[i - 1], [p1, c1] = HUES[i], k = Math.min(1, Math.max(0, (t - p0) / (p1 - p0 || 1)));
    const a = rgb(c0), b = rgb(c1);
    return "#" + a.map((v, j) => Math.round(v + (b[j] - v) * k).toString(16).padStart(2, "0")).join("");
  }
  function hueOf(c) {                    // ближайшая точка полосы к цвету (для старых настроек)
    let best = 0, bd = 1e9; const x = rgb(/^#[0-9a-f]{6}$/i.test(c || "") ? c : "#ff4d4d");
    for (let t = 0; t <= 1; t += .005) { const y = rgb(colorAt(t)), d = x.reduce((s, v, j) => s + (v - y[j]) ** 2, 0); if (d < bd) { bd = d; best = t; } }
    return best;
  }

  function load(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }
  function keep(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* только удобство */ } }
  // Значки — по системе из «Interface → Значки кнопок»: сетка 24, рисунок в квадрате 3–21, линия 1.8 круглая.
  // В баре значки 18 px (кнопки 34), в меню и заметках — как задано в CSS. Образцы — @ INSTRUCTIONS\Icons\Buttons.
  const ic = (body, extra = "") => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra}>${body}</svg>`;
  const ic16 = (body, w = 1.25) => `<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="butt" stroke-linejoin="round">${body}</svg>`;
  const BUG = ic('<path d="M9.2 7.6a2.8 2.8 0 0 1 5.6 0"/><ellipse cx="12" cy="13.2" rx="4" ry="4.6"/><path d="M8.3 10.4L6.1 9.1Q5.4 8.6 5.3 7.8M8 13.2H4.6M8.3 16L6.1 17.3Q5.4 17.8 5.3 18.6M15.7 10.4l2.2-1.3q.7-.5.8-1.3M16 13.2h3.4M15.7 16l2.2 1.3q.7.5.8 1.3"/>');
  const MIC = ic('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>');
  // корзина по образцу Saturni: крышка с ручкой, пустой корпус, бока чуть сходятся книзу; чуть меньше соседей (×0.92)
  const BIN = ic('<g transform="matrix(.92 0 0 .92 .96 .96)" stroke-width="1.96"><path d="M4.5 6.5h15"/><path d="M9 6.5V4.3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2.2"/><path d="M6 6.5l1.1 12.6a1.8 1.8 0 0 0 1.8 1.7h6.2a1.8 1.8 0 0 0 1.8-1.7L18 6.5"/></g>');
  const EYE = '<path d="M2.5 12c2.1-4.2 5.5-6.5 9.5-6.5s7.4 2.3 9.5 6.5c-2.1 4.2-5.5 6.5-9.5 6.5S4.6 16.2 2.5 12z"/>';
  const I = {
    // области — пунктиром. Прямоугольник рисует тот же crispDash, что и рамки (сетка 18 = пиксели значка, штрих 2, промежуток 2);
    // круг и блоб — в сетке 16, 8 штрихов, концы плоские. Блоб — по образцу Saturni (неровный, вмятина снизу).
    rect: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="butt">${crispDash(2, 2, 14, 14, 3, 2, 2)}</svg>`,
    ellipse: ic16('<circle cx="8" cy="8" r="5.5" stroke-dasharray="2.42 1.9" stroke-dashoffset="1.21"/>'),
    free: ic16('<path d="M4.45 3.33C5.09 3.17 6.68 3.36 7.71 3.59C8.74 3.82 9.77 4.13 10.64 4.73C11.5 5.33 12.45 6.47 12.91 7.17C13.38 7.88 13.51 8.15 13.4 8.96C13.29 9.77 12.83 11.48 12.26 12.05C11.69 12.62 10.64 12.35 9.99 12.38C9.33 12.4 9.12 12.16 8.36 12.21C7.6 12.27 6.27 12.84 5.43 12.7C4.59 12.57 3.79 11.86 3.31 11.4C2.84 10.94 2.54 10.64 2.57 9.94C2.59 9.23 3.26 8.07 3.48 7.17C3.69 6.28 3.7 5.21 3.87 4.57C4.03 3.93 3.81 3.49 4.45 3.33Z" stroke-dasharray="2.33 1.83"/>'),
    // ручка рисует сплошные фигуры — и значки у них сплошные
    prect: ic('<rect x="4" y="4" width="16" height="16" rx="3"/>'), pcircle: ic('<circle cx="12" cy="12" r="8"/>'),
    // стилус, как курсор-ручка Windows: корпус наискось без черточки, остриё вниз-влево
    eraser: ic('<path d="m7 21-4.3-4.3a2.4 2.4 0 0 1 0-3.4l9.6-9.6a2.4 2.4 0 0 1 3.4 0l5.6 5.6a2.4 2.4 0 0 1 0 3.4L13 21z"/><path d="M22 21H7M5 11l9 9"/>'),
    pen: ic('<g transform="rotate(45 12 12)"><path d="M9.9 4.6a2.1 2.1 0 0 1 4.2 0v12.2L12 22.4l-2.1-5.6z"/></g>'),
    // курсор-стрелка
    mouse: ic('<path d="M5.5 4 19 11.4l-6 1.6-2.7 6.4z"/>'),
    chev: '<svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>',
    check: ic('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
    eye: ic(EYE + '<circle cx="12" cy="12" r="3"/>'),
    screen: ic('<rect x="3.5" y="5" width="17" height="12" rx="2"/><path d="M9 21h6M12 17v4"/>'),
    folder: ic('<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'), bin: BIN,
    done: ic('<path stroke-width="2.4" stroke-linejoin="miter" d="m4.5 12.5 5 5L19.5 7"/>').replace('width="18" height="18"', 'width="22" height="22"'),   // «Готово» — крупная жирная галочка
    left: ic('<path d="m14.5 6-6 6 6 6"/>'),
    dots: ic('<g fill="currentColor" stroke="none"><circle cx="5.5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="18.5" cy="12" r="2"/></g>'),   // три жирные точки: подробности
    down: ic('<path d="m6 9.5 6 6 6-6"/>'), up: ic('<path d="m6 14.5 6-6 6 6"/>'),
  };

  // gear: шестерёнка настроек приложения (элемент или селектор). Ctrl+клик — отладка, правый клик — меню
  // с пунктом Debug, на углу — число заметок. Без gear — старая кнопка-жучок в slot (или в углу окна).
  // screen: сразу открыть «весь экран» (окно-накладка для приложений без WebView), onExit — при выходе.
  D.init = async function (o) {
    cfg = Object.assign({ holdButton: 3, app: "app", context: () => "", slot: null, gear: null, screen: false, onExit: null }, o);
    build();
    try { const s = await cfg.api("debug_load"); if (s && s.notes) state = Object.assign({ marks: [] }, s); } catch (e) { /* пусто */ }
    if (cfg.gear) D.gear(cfg.gear);
    count();
    addEventListener("keydown", onKey, true);
    addEventListener("mousedown", onHoldDown, true);
    addEventListener("mouseup", onHoldUp, true);
    if (cfg.screen) { D.toggle(true); setScreen(true); }
  };

  // ── шестерёнка ──
  let gearSel = null, gmenu = null;
  const gearEl = () => typeof gearSel === "string" ? document.querySelector(gearSel) : gearSel;
  const onGear = e => { const g = gearEl(); return g && e.target && e.target.nodeType === 1 && g.contains(e.target); };
  D.gear = function (g) {
    gearSel = g;
    addEventListener("click", e => {
      if (e.ctrlKey && onGear(e)) { e.preventDefault(); e.stopImmediatePropagation(); D.toggle(); }
    }, true);
    addEventListener("mousedown", e => { if (e.ctrlKey && e.button === 0 && onGear(e)) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
    addEventListener("contextmenu", e => {
      if (!onGear(e)) return;
      e.preventDefault(); e.stopImmediatePropagation();
      if (e.target.closest(".sdbg-bugb")) openHistory(); else openGearMenu(e.clientX, e.clientY);
    }, true);
    addEventListener("mousedown", e => {
      if (gmenu && gmenu.style.display !== "none" && !gmenu.contains(e.target)) gmenu.style.display = "none";
      if (hist && hist.style.display !== "none" && !hist.contains(e.target) && !e.target.closest(".sdbg-bugb")) hist.style.display = "none";
    }, true);
    addEventListener("keydown", e => { if (e.key === "Escape" && hist && hist.style.display !== "none") { e.stopImmediatePropagation(); hist.style.display = "none"; } }, true);
    // правки применены (Claude закрыл сессию) — заметки и цифра уходят без перезапуска программы
    addEventListener("focus", refresh);
    setInterval(() => { if (!document.hidden) refresh(); }, 15000);
    new MutationObserver(badge).observe(document.body, { childList: true, subtree: true });   // приложение перерисовало шапку
    badge();
  };
  function openGearMenu(x, y) {
    if (!gmenu) {
      gmenu = document.createElement("div"); gmenu.className = "sdbg-gmenu";
      gmenu.addEventListener("click", e => {
        const a = e.target.closest("[data-g]")?.dataset.g; if (!a) return;
        gmenu.style.display = "none";
        if (a === "debug") D.toggle(); else cfg.api("debug_reveal");
      });
      document.body.append(gmenu);
    }
    const n = state.notes.length;
    gmenu.innerHTML = `<button data-g="debug">${BUG}<span>Debug</span><em>${n ? n + " · " : ""}Ctrl+click</em></button>` +
      (n ? `<button data-g="folder">${I.folder}<span>Notes folder</span></button>` : "");
    gmenu.style.display = "flex";
    gmenu.style.left = Math.round(Math.max(4, Math.min(x, innerWidth - gmenu.offsetWidth - 4))) + "px";
    gmenu.style.top = Math.round(Math.max(4, Math.min(y, innerHeight - gmenu.offsetHeight - 4))) + "px";
  }
  async function refresh() {
    if (!cfg || D.active || drawing) return;
    let s; try { s = await cfg.api("debug_load"); } catch (e) { return; }
    if (!s || !s.notes || s.notes.map(n => n.n).join() === state.notes.map(n => n.n).join()) return;
    live.forEach(l => l.bub && l.bub.remove()); live.clear();
    state = Object.assign({ marks: [] }, s); count(); renderBubbles();
  }
  // История: правый клик по жучку — прошлые сессии правок; в сессии — заметки со снимками и что по ним сделано.
  let hist = null;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const when = name => { const m = /^(\d{4})-(\d\d)-(\d\d) (\d\d)-(\d\d)/.exec(name); return m ? `${+m[3]} ${MON[m[2] - 1]} ${m[4]}:${m[5]}` : name; };
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  async function openHistory() {
    if (!hist) {
      hist = document.createElement("div"); hist.className = "sdbg-hist";
      hist.addEventListener("click", e => {
        const s = e.target.closest("[data-s]"), back = e.target.closest("[data-back]"), img = e.target.closest("img");
        if (s) openSession(s.dataset.s);
        else if (back) openHistory();
        else if (e.target.closest("[data-el]")) {
          const on = hist.classList.toggle("els"), b = e.target.closest("[data-el]");
          b.classList.toggle("on", on); b.title = `${on ? "Hide" : "Show"} the elements under each note`; keep("sdbg-hist-el", on);
        }
        else if (e.target.closest(".tx")) e.target.closest(".tx").classList.toggle("open");
        else if (img) { const v = document.createElement("div"); v.className = "sdbg-view"; v.innerHTML = `<img src="${img.src}">`; v.onmousedown = () => v.remove(); document.body.append(v); }
      });
      document.body.append(hist);
    }
    let list = []; try { list = await cfg.api("debug_history") || []; } catch (e) { /* пусто */ }
    hist.innerHTML = `<div class="hd">Past notes</div>` + (list.length ? list.map(s =>
      `<button data-s="${esc(s.name)}"><span class="t">${when(s.name)}</span><em>${plural(s.count, "note")}</em>${s.done ? I.check : '<i class="nd"></i>'}` +
      (s.summary ? `<small>${esc(s.summary)}</small>` : "") + `</button>`).join("") : `<div class="none">No past notes yet</div>`);
    showHist();
  }
  async function openSession(name) {
    let notes = []; try { notes = await cfg.api("debug_history_open", name) || []; } catch (e) { /* пусто */ }
    const els = load("sdbg-hist-el", false);
    hist.classList.toggle("els", els);
    hist.innerHTML = `<div class="hd2"><button class="back" data-back>${I.left}<span>${when(name)}</span></button>` +
      `<button class="tg${els ? " on" : ""}" data-el title="${els ? "Hide" : "Show"} the elements under each note">${I.dots}</button>` +
      `<em>${plural(notes.length, "note")}</em></div><div class="notes">` +
      notes.map(n => `<div class="nt"><div class="h"><b>#${n.n}</b><span>${esc(n.ctx)}</span>${n.applied ? I.check : ""}</div>` +
        `<p class="tx" title="Click to expand">${esc(n.text) || '<span class="mt">(empty)</span>'}</p>` + (n.what ? `<p class="w">${esc(n.what)}</p>` : "") +
        (n.shot ? `<img src="${n.shot}" alt="">` : "") +
        (n.elements.length ? `<div class="el">${n.elements.map(e => `<code>${esc(e.sel)}</code>${e.text ? " " + esc(e.text) : ""}`).join("<br>")}</div>` : "") + `</div>`).join("") + `</div>`;
    showHist();
  }
  function showHist() {
    const g = gearEl(), r = g.getBoundingClientRect();
    hist.style.display = "flex";
    hist.style.left = Math.round(Math.max(4, Math.min(r.right - hist.offsetWidth, innerWidth - hist.offsetWidth - 4))) + "px";
    hist.style.top = Math.round(Math.min(r.bottom + 6, innerHeight - hist.offsetHeight - 4)) + "px";
  }
  // На шестерёнке: число заметок — жёлтая цифра у правого края значка (левым краем прижата, лишние цифры уходят вправо);
  // мышь в правом верхнем углу кнопки — вместо цифры жучок на той же строке (клик — отладка, правый клик — история).
  const BUGI = '<svg viewBox="3.4 3.6 17.2 16.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9.2 7.6a2.8 2.8 0 0 1 5.6 0"/><ellipse cx="12" cy="13.2" rx="4" ry="4.6"/><path d="M8.3 10.4L6.1 9.1Q5.4 8.6 5.3 7.8M8 13.2H4.6M8.3 16L6.1 17.3Q5.4 17.8 5.3 18.6M15.7 10.4l2.2-1.3q.7-.5.8-1.3M16 13.2h3.4M15.7 16l2.2 1.3q.7.5.8 1.3"/></svg>';
  function badge() {
    const g = gearEl(); if (!g) return;
    if (getComputedStyle(g).position === "static") g.style.position = "relative";
    let b = g.querySelector(":scope > .sdbg-badge"), k = g.querySelector(":scope > .sdbg-bugb");
    if (!k) {
      k = document.createElement("span"); k.className = "sdbg-bugb"; k.innerHTML = BUGI; k.title = "Debug notes · right-click: past notes";
      k.addEventListener("click", e => { e.preventDefault(); e.stopImmediatePropagation(); g.classList.remove("sdbg-corner"); D.toggle(); }, true);
      k.addEventListener("mousedown", e => { e.preventDefault(); e.stopImmediatePropagation(); }, true);
      g.append(k);
      // угол: правая верхняя треть кнопки и сам жучок
      const zone = e => { const r = g.getBoundingClientRect(); return (e.clientX > r.right - r.width * .38 && e.clientY < r.top + r.height * .38) || k.contains(e.target); };
      g.addEventListener("mousemove", e => g.classList.toggle("sdbg-corner", zone(e)));
      g.addEventListener("mouseleave", () => g.classList.remove("sdbg-corner"));
    }
    const ic = g.querySelector("svg:not(.sdbg-bugb svg)"), gr = g.getBoundingClientRect(), ir = ic && ic.getBoundingClientRect();
    const x = Math.round(ir && ir.width ? ir.right - gr.left - 1 : gr.width * .73);
    k.style.left = x + 1 + "px";                     // жучок — с начала цифр, на 1 px правее
    const n = state.notes.length;
    if (!n) { if (b) b.remove(); return; }
    if (!b) { b = document.createElement("span"); b.className = "sdbg-badge"; g.append(b); }
    b.style.left = x + "px";
    if (b.textContent !== String(n)) b.textContent = n;
  }
  D.setHoldButton = b => { if (cfg) cfg.holdButton = b; };
  // событие принадлежит отладке — приложение его не обрабатывает
  D.owns = e => {
    if (!root) return false;
    if (e && e.target && e.target.nodeType === 1 && root.contains(e.target)) return true;
    if (root.contains(document.activeElement)) return true;
    return D.active && e && /^mouse|auxclick/.test(e.type) && (e.button === 3 || e.button === 4);
  };
  D.toggle = on => {
    D.active = on ?? !D.active;
    root.classList.toggle("on", D.active);
    toggleBtn && toggleBtn.classList.toggle("on", D.active);
    if (!D.active) { closeBub(); cancelDraw(); if (rec) stopRec(); hidePop(); if (screenMode) setScreen(false); if (cfg.onExit) cfg.onExit(); }
    else placeBar();
    renderBubbles();
    if (D.active && !raf) loop();
  };

  // ── каркас ──
  function build() {
    root = document.createElement("div"); root.id = "sdbg-root";
    const b = (a, t, i) => `<button class="sdbg-ib" data-a="${a}" title="${t}">${i}</button>`;
    const dd = (a, t) => `<button class="sdbg-dd" data-m="${a}" title="${t}">${I.chev}</button>`;     // стрелка: меню без правого клика
    root.innerHTML = `<img class="sdbg-scr" alt=""><div class="sdbg-catch"></div><svg class="sdbg-svg"></svg><div class="sdbg-bubs"></div>
      <div class="sdbg-bar"><span class="sdbg-pair">${b("t:mouse", "Use the app — clicks go to the interface", I.mouse)}${b("t:area", "Mark an area for a note", I[shape])}${dd("area", "Area shape")}</span>
        <i class="sp"></i>${b("t:pen", "Pen", I.pen)}${dd("pen", "Pen shape, size and color")}
        <i class="sp"></i>${b("hide", "Notes to show", I.eye)}${dd("eye", "Hide the notes, dim")}${b("screen", "Mark anywhere on the screen", I.screen)}${b("folder", "Open the notes folder", I.folder)}${b("clear", "Clear all the notes", I.bin)}
        <i class="sp"></i>${b("exit", "Done", I.done)}</div><div class="sdbg-pop"></div>`;
    document.body.append(root);
    catchEl = root.querySelector(".sdbg-catch"); svg = root.querySelector(".sdbg-svg"); bubs = root.querySelector(".sdbg-bubs");
    bar = root.querySelector(".sdbg-bar"); pop = root.querySelector(".sdbg-pop"); scrImg = root.querySelector(".sdbg-scr");
    dashBorder(bar, 11);
    bar.addEventListener("click", e => {
      const m = e.target.closest("[data-m]")?.dataset.m;
      if (m) { e.stopPropagation(); return pop.style.display === "flex" && pop.dataset.m === m ? hidePop() : openPop(m); }
      barAct(e.target.closest("[data-a]")?.dataset.a);
    });
    bar.addEventListener("mousedown", e => { if (!e.target.closest("button")) dragBar(e); });
    for (const [a, m] of [["t:pen", "pen"], ["t:area", "area"], ["hide", "eye"]])
      bar.querySelector(`[data-a="${a}"]`).addEventListener("contextmenu", e => { e.preventDefault(); e.stopPropagation(); openPop(m); });
    pop.addEventListener("mousedown", e => e.stopPropagation());
    catchEl.addEventListener("pointerdown", onDown);
    catchEl.addEventListener("mousemove", onHover);
    catchEl.addEventListener("dblclick", e => passThrough(e, "dblclick"));
    catchEl.addEventListener("contextmenu", e => { e.preventDefault(); passThrough(e, "contextmenu"); });
    catchEl.addEventListener("wheel", onWheel, { passive: false });
    toggleBtn = document.createElement("button");
    toggleBtn.className = "sdbg-toggle"; toggleBtn.title = "Debug notes · Ctrl+Shift+D";
    toggleBtn.innerHTML = BUG + '<span class="c"></span>';
    toggleBtn.addEventListener("click", () => D.toggle());
    if (cfg.gear || cfg.screen) { /* кнопки-жучка нет: вход через шестерёнку */ }
    else if (cfg.slot) cfg.slot.append(toggleBtn);
    else { toggleBtn.style.cssText = "position:fixed;left:8px;bottom:8px;z-index:10001"; document.body.append(toggleBtn); }
    showTool(); eyeState();
  }
  function barAct(a) {
    if (!a) return;
    if (a.startsWith("t:")) { tool = a === "t:area" ? shape : a.slice(2); keep("sdbg-tool", tool); showTool(); hidePop(); return; }
    if (a === "exit") D.toggle(false);
    if (a === "folder") cfg.api("debug_reveal");
    if (a === "screen") setScreen(!screenMode);
    if (a === "hide") { lastOnly = !lastOnly; keep("sdbg-last", lastOnly); eyeState(); renderBubbles(); }
    if (a === "clear" && (state.notes.length || state.marks.length) && confirm(`Clear all ${state.notes.length} notes and start numbering from 1? They go to the archive folder.`)) {
      cfg.api("debug_clear"); state = { next_n: 1, notes: [], marks: [] }; live.forEach(l => l.bub && l.bub.remove()); live.clear(); count(); renderBubbles();
    }
  }
  const btn = a => bar.querySelector(`[data-a="${a}"]`);
  // глаз: сам переключает «все заметки» ↔ «только последняя»; скрыть все — галочкой в его меню
  function eyeState() {
    const e = btn("hide"), h = root.classList.contains("hide-notes");
    e.classList.toggle("on", lastOnly || h);
    e.title = h ? "Notes are hidden · menu: show them" : lastOnly ? "Showing only the last note · click: all notes" : "Showing all notes · click: only the last";
  }
  function showTool() {
    btn("t:mouse").classList.toggle("on", tool === "mouse");
    btn("t:pen").classList.toggle("on", tool === "pen");
    btn("t:area").classList.toggle("on", ["rect", "ellipse", "free"].includes(tool));
    btn("t:area").innerHTML = I[shape];
    catchEl && catchEl.classList.toggle("pass", tool === "mouse");
  }
  function placeBar() {
    const w = bar.offsetWidth, h = bar.offsetHeight;
    const x = bar.dataset.x ? +bar.dataset.x : Math.round((innerWidth - w) / 2), y = bar.dataset.y ? +bar.dataset.y : innerHeight - h - 56;   // выше панели задач Windows
    bar.style.left = Math.round(Math.max(4, Math.min(x, innerWidth - w - 4))) + "px"; bar.style.top = Math.round(Math.max(4, Math.min(y, innerHeight - h - 4))) + "px";
  }
  function follow(e, move, end) {       // зажатая мышь: move(dx, dy, ev), потом end(сдвинулись ли)
    const x0 = e.clientX, y0 = e.clientY; let went = false;
    // события указателя, не мыши: после preventDefault на pointerdown браузер не шлёт mouseup — перетаскивание «залипало»
    const mv = ev => { const dx = ev.clientX - x0, dy = ev.clientY - y0; if (!went && Math.hypot(dx, dy) < 4) return; went = true; move(dx, dy, ev); };
    const up = () => { removeEventListener("pointermove", mv, true); removeEventListener("pointerup", up, true); removeEventListener("pointercancel", up, true); end && end(went); };
    addEventListener("pointermove", mv, true); addEventListener("pointerup", up, true); addEventListener("pointercancel", up, true);
  }
  function dragBar(e) {
    e.preventDefault(); const r = bar.getBoundingClientRect();
    follow(e, (dx, dy) => { bar.dataset.x = r.left + dx; bar.dataset.y = r.top + dy; placeBar(); });
  }
  // меню у стрелки (или по правому клику): форма области, ручка, какие заметки показывать
  function openPop(m = "pen") {
    pop.dataset.m = m;
    const tick = on => `<span class="tk">${on ? I.check : ""}</span>`;
    if (m === "area") {
      pop.innerHTML = [["rect", "Rectangle"], ["ellipse", "Circle"], ["free", "Free shape"]]
        .map(([k, l]) => `<button data-k="${k}" class="${shape === k ? "on" : ""}">${I[k]}${l}</button>`).join("");
      pop.onclick = e => { const k = e.target.closest("[data-k]")?.dataset.k; if (!k) return; shape = tool = k; keep("sdbg-shape", shape); keep("sdbg-tool", tool); showTool(); hidePop(); };
    } else if (m === "eye") {
      pop.innerHTML = `<button data-k="hide">${tick(root.classList.contains("hide-notes"))}Hide the notes</button><hr>` +
        `<button data-k="fade">${tick(fade)}Dim notes until the cursor is on them</button>`;
      pop.onclick = e => {
        const k = e.target.closest("[data-k]")?.dataset.k; if (!k) return;
        if (k === "hide") { root.classList.toggle("hide-notes"); eyeState(); place(); }
        if (k === "fade") { fade = !fade; keep("sdbg-fade", fade); place(); }
        openPop("eye");
      };
    } else {
      // толщина — ползунок и рядом кружок-превью настоящего размера и цвета; цвет — полоса от белого через радугу до чёрного
      pen.hue = hueOf(pen.color);   // место на полосе — по цвету (полоса могла поменяться)
      pop.innerHTML = `<button data-k="pen">${I.pen}Pen</button><button data-k="rect">${I.prect}Rectangle</button><button data-k="ellipse">${I.pcircle}Circle</button><button data-k="erase">${I.eraser}Eraser</button>
        <div class="szr"><input class="size" type="range" min="1" max="24" step="0.1" value="${pen.size}" title="Size"><svg class="pv" width="26" height="26"><circle cx="13" cy="13"/></svg></div>
        <input class="hue" type="range" min="0" max="1000" step="1" value="${Math.round(pen.hue * 1000)}" title="Color" style="background:linear-gradient(90deg,${HUES.map(([p, c]) => `${c} ${p * 100}%`).join(",")})">
        <button data-k="clear">${I.bin}Clear the drawing</button>`;
      const pv = pop.querySelector(".pv circle"), hue = pop.querySelector(".hue"), size = pop.querySelector(".size");
      const mark = () => {
        pop.querySelectorAll("[data-k]").forEach(b => b.classList.toggle("on", b.dataset.k === pen.kind));
        // превью — svg-кружок с постоянным центром: растёт ровно во все стороны (div по целым пикселям прыгал то вниз, то влево)
        pv.setAttribute("r", pen.size / 2); pv.setAttribute("fill", pen.color); hue.style.setProperty("--c", pen.color);
        size.style.setProperty("--p", (pen.size - 1) / 23 * 100 + "%");
      };
      mark();
      pop.onclick = e => {
        const k = e.target.closest("[data-k]")?.dataset.k;
        if (k === "clear") { state.marks = state.marks.filter(mk => !markVisible(mk)); save(); hidePop(); return; }
        if (k) { pen.kind = k; tool = "pen"; showTool(); hidePop(); }
        keep("sdbg-pen", pen); mark();
      };
      // шаг 0.1 — ползунок едет плавно, как у цвета (с шагом 1 на 23 деления он прыгал)
      pop.querySelector(".size").oninput = e => { pen.size = Math.round(e.target.value * 10) / 10; keep("sdbg-pen", pen); mark(); };
      hue.oninput = e => { pen.hue = e.target.value / 1000; pen.color = colorAt(pen.hue); keep("sdbg-pen", pen); mark(); };
    }
    pop.style.display = "flex";
    const r = (bar.querySelector(`[data-m="${m}"]`) || btn("t:pen")).getBoundingClientRect();
    pop.style.left = Math.round(Math.max(4, Math.min(r.left - 14, innerWidth - pop.offsetWidth - 4))) + "px"; pop.style.top = Math.round(Math.max(4, r.top - pop.offsetHeight - 10)) + "px";
  }
  function hidePop() { pop.style.display = "none"; }
  function count() {
    const n = state.notes.length, c = toggleBtn.querySelector(".c");
    c.textContent = n; c.classList.toggle("has", n > 0);
    if (gearSel) badge();
  }
  function save() { count(); clearTimeout(saveT); saveT = setTimeout(() => cfg.api("debug_save", state, cfg.app), 300); }

  // ── весь экран: снимок экрана под заметками, окно на весь экран ──
  async function setScreen(on) {
    if (on === screenMode) return;
    closeBub(); hidePop();
    if (on) {
      root.classList.add("shot");
      const r = await cfg.api("debug_screen_start");
      root.classList.remove("shot");
      if (!r || !r.url) return;
      scrImg.src = r.url; scrImg.style.display = "block"; screenMode = true;
    } else { screenMode = false; scrImg.style.display = "none"; scrImg.removeAttribute("src"); cfg.api("debug_screen_stop"); }
    btn("screen").classList.toggle("on", screenMode); bar.dataset.x = bar.dataset.y = "";
    setTimeout(() => { placeBar(); renderBubbles(); }, 300);
  }

  // ── геометрия ──
  const under = (x, y) => screenMode ? [] : document.elementsFromPoint(x, y).filter(e => !root.contains(e) && e !== root);
  function scroller(el) {
    for (; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      const cs = getComputedStyle(el);
      if (/(auto|scroll)/.test(cs.overflowY + cs.overflowX) && (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2)) return el;
    }
    return null;
  }
  const NOISY = /^(sel|cur|hl|live|found|on|off|rec|wait|has|filled|drag|open|busy|hover|active|focus|max|booting|has-file)$/;
  function selOf(el) {
    if (!el || el === document.body || el === document.documentElement) return "body";
    const parts = [];
    for (; el && el.nodeType === 1 && el !== document.body; el = el.parentElement) {
      if (el.id) { parts.unshift("#" + CSS.escape(el.id)); break; }
      let s = el.tagName.toLowerCase();
      const cls = [...el.classList].filter(c => !NOISY.test(c)).slice(0, 2);
      if (cls.length) s += "." + cls.map(c => CSS.escape(c)).join(".");
      const p = el.parentElement;
      if (p) { const sib = [...p.children].filter(c => c.tagName === el.tagName); if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(el) + 1})`; }
      parts.unshift(s);
    }
    return parts.join(" > ");
  }
  function inPoly(x, y, pts) {
    let ins = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) ins = !ins;
    }
    return ins;
  }
  function bboxOf(pts) {
    let a = 1e9, b = 1e9, c = -1e9, d = -1e9;
    for (const [x, y] of pts) { a = Math.min(a, x); b = Math.min(b, y); c = Math.max(c, x); d = Math.max(d, y); }
    return [a, b, c - a, d - b];
  }
  function distTo(x, y, P) {            // расстояние до контура
    let best = 1e9;
    for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
      const [ax, ay] = P[j], [bx, by] = P[i], dx = bx - ax, dy = by - ay, u = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy || 1)));
      best = Math.min(best, Math.hypot(x - ax - dx * u, y - ay - dy * u));
    }
    return best;
  }
  // начало координат якоря во вьюпорте (с учётом прокрутки) и видимая область для обрезки
  function frame(note) {
    const L = live.get(note.n) || {};
    if (note.anchor.sel === "body") return { ox: 0, oy: 0, clip: [0, 0, innerWidth, innerHeight] };
    if (!L.el || !L.el.isConnected) { L.el = document.querySelector(note.anchor.sel); live.set(note.n, L); }
    const el = L.el;
    if (!el || !el.getClientRects().length) return null;
    const r = el.getBoundingClientRect();
    return { ox: r.left - el.scrollLeft, oy: r.top - el.scrollTop, clip: [r.left, r.top, r.width, r.height] };
  }
  const ctxNow = () => cfg.context();
  function visibleNotes() {
    const list = state.notes.filter(n => screenMode ? n.screen : !n.screen && (n.global || n.ctx === ctxNow()));
    return lastOnly ? list.slice(-1) : list;
  }
  const markVisible = m => screenMode ? m.screen : !m.screen && (m.global !== false || m.ctx === ctxNow());
  function zoneAt(x, y) {               // за контур обводки можно взять и перенести
    for (const note of visibleNotes().slice().reverse()) {
      const f = frame(note); if (!f) continue;
      if (distTo(x, y, note.pts.map(([px, py]) => [px + f.ox, py + f.oy])) < 6) return note;
    }
    return null;
  }

  // ── рисование ──
  function onHover(e) { if (!drawing && !moving) catchEl.style.cursor = tool === "mouse" ? "default" : !root.classList.contains("hide-notes") && zoneAt(e.clientX, e.clientY) ? "move" : ""; }
  addEventListener("mousemove", e => { mouse = [e.clientX, e.clientY]; }, true);
  function onDown(e) {
    if (e.button !== 0) return;
    e.preventDefault(); hidePop(); closeBub();
    if (tool === "mouse") {                          // режим «мышь»: всё нажимается в самом интерфейсе
      const x0 = e.clientX, y0 = e.clientY;
      const up = ev => { removeEventListener("pointerup", up); if (!screenMode && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) passThrough(ev, "click"); };
      return addEventListener("pointerup", up);
    }
    const z = !root.classList.contains("hide-notes") && zoneAt(e.clientX, e.clientY);
    if (z) return moveZone(z, e);
    const kind = tool === "pen" ? pen.kind : tool;
    if (kind === "erase") return erase(e);
    drawing = { tool, kind, pts: [[e.clientX, e.clientY]], x0: e.clientX, y0: e.clientY, sm: [e.clientX, e.clientY] };
    // ручка: линия сглаживается на ходу — точка догоняет курсор с запаздыванием (SMOOTH), дрожь руки и ступеньки пикселей
    // уходят; точки хранятся с десятыми долями, без округления до пикселя (иначе ступеньки возвращаются)
    const SMOOTH = .3;
    // после отпускания линия ещё раз сглаживается: каждая точка — к среднему соседей (концы на месте), times раз
    const relax = (P, times) => { for (let t = 0; t < times; t++) P = P.map((p, i) => i && i < P.length - 1 ? [(P[i - 1][0] + 2 * p[0] + P[i + 1][0]) / 4, (P[i - 1][1] + 2 * p[1] + P[i + 1][1]) / 4] : p); return P; };
    const mv = ev => {
      const list = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [ev];
      for (const q of list.length ? list : [ev]) {
        const p = drawing.pts[drawing.pts.length - 1];
        if (kind === "rect" || kind === "ellipse") drawing.pts = [drawing.pts[0], [q.clientX, q.clientY]];
        else if (tool === "pen") {
          const s = drawing.sm; s[0] += (q.clientX - s[0]) * SMOOTH; s[1] += (q.clientY - s[1]) * SMOOTH;
          if (Math.hypot(s[0] - p[0], s[1] - p[1]) > 1.2) drawing.pts.push([s[0], s[1]]);
        }
        else if (Math.hypot(q.clientX - p[0], q.clientY - p[1]) > 3) drawing.pts.push([q.clientX, q.clientY]);
      }
    };
    const up = ev => {
      removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
      const d = drawing; drawing = null;
      if (!d) return;
      if (d.tool === "pen" && d.kind === "pen") { d.pts.push([ev.clientX, ev.clientY]); d.pts = relax(d.pts, 4); }   // конец — где отпустил; доглаживаем
      const [, , w, h] = bboxOf(d.pts);
      if (w < 10 && h < 10) { if (!screenMode) passThrough(ev, "click"); return; }
      if (d.tool === "pen") { state.marks.push({ kind: d.kind, color: pen.color, size: pen.size, pts: d.pts.map(p => p.map(v => Math.round(v * 10) / 10)), ctx: ctxNow(), global: true, screen: screenMode }); save(); }
      else createNote(d.kind === "free" ? d.pts : outline(d.kind, d.pts), d.kind);
    };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  }
  // ластик: провёл по рисунку — стираются штрихи, которых коснулся (заметки не трогает)
  function erase(e) {
    const hit = (x, y) => {
      const before = state.marks.length;
      state.marks = state.marks.filter(m => {
        if (!markVisible(m)) return true;
        const P = m.kind === "pen" ? m.pts : outline(m.kind, m.pts), r = Math.max(8, m.size / 2 + 5);
        if (P.length === 1) return Math.hypot(x - P[0][0], y - P[0][1]) >= r;
        for (let i = 1; i < P.length + (m.kind === "pen" ? 0 : 1); i++) {      // у ручки линия открытая, у фигур — замкнутая
          const [ax, ay] = P[i - 1], [bx, by] = P[i % P.length], dx = bx - ax, dy = by - ay;
          const u = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy || 1)));
          if (Math.hypot(x - ax - dx * u, y - ay - dy * u) < r) return false;
        }
        return true;
      });
      if (state.marks.length !== before) { save(); place(); }
    };
    hit(e.clientX, e.clientY);
    follow(e, (dx, dy, ev) => hit(ev.clientX, ev.clientY));
  }
  function outline(kind, [a, b]) {      // контур прямоугольника / круга как обычные точки
    const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]), w = Math.abs(a[0] - b[0]), h = Math.abs(a[1] - b[1]);
    if (kind === "rect") return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
    return Array.from({ length: 48 }, (_, i) => [x + w / 2 + w / 2 * Math.cos(i * Math.PI / 24), y + h / 2 + h / 2 * Math.sin(i * Math.PI / 24)]);
  }
  function moveZone(note, e) {
    moving = note; const pts = note.pts.map(p => [...p]), pos = note.pos && [...note.pos];
    follow(e, (dx, dy) => { note.pts = pts.map(([x, y]) => [Math.round(x + dx), Math.round(y + dy)]); if (pos) note.pos = [pos[0] + dx, pos[1] + dy]; },
      went => { moving = null; if (went) { note.bbox = bboxOf(note.pts).map(Math.round); save(); } else { const o = { clientX: e.clientX, clientY: e.clientY }; if (!screenMode) passThrough(o, "click"); } });
  }
  function cancelDraw() { drawing = null; }
  function passThrough(e, kind) {
    const el = under(e.clientX, e.clientY)[0];
    if (!el) return;
    const o = { clientX: e.clientX, clientY: e.clientY, bubbles: true, cancelable: true, button: kind === "contextmenu" ? 2 : 0, ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey };
    if (kind === "dblclick" || kind === "contextmenu") { el.dispatchEvent(new MouseEvent(kind, o)); return; }
    el.dispatchEvent(new MouseEvent("mousedown", o));
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable) el.focus();
    el.dispatchEvent(new MouseEvent("mouseup", o));
    el.dispatchEvent(new MouseEvent("click", o));
  }
  function onWheel(e) {
    e.preventDefault();
    const els = under(e.clientX, e.clientY); if (!els.length) return;
    const w = new WheelEvent("wheel", { deltaX: e.deltaX, deltaY: e.deltaY, deltaMode: e.deltaMode, clientX: e.clientX, clientY: e.clientY,
      ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, bubbles: true, cancelable: true });
    if (els[0].dispatchEvent(w)) { const s = scroller(els[0]); s && s.scrollBy(e.deltaX, e.deltaY); }
  }

  function describe(el, withStyle) {
    const d = { sel: selOf(el) };
    const t = (el.value !== undefined && typeof el.value === "string" ? el.value : (el.children.length <= 4 ? el.innerText : "")) || "";
    if (t.trim()) d.text = t.trim().slice(0, 120);
    if (el.dataset && Object.keys(el.dataset).length) d.data = { ...el.dataset };
    if (withStyle) { const cs = getComputedStyle(el); d.style = `color ${cs.color}; bg ${cs.backgroundColor}; font ${cs.fontSize} ${cs.fontWeight}`; }
    return d;
  }
  function createNote(pts, shape) {
    const [bx, by, bw, bh] = bboxOf(pts);
    const cx = bx + bw / 2, cy = by + bh / 2;
    const first = under(cx, cy)[0] || document.body;
    const sc = screenMode ? null : scroller(first);
    const anchor = sc ? { sel: selOf(sc) } : { sel: "body" };
    const n = { n: state.next_n++, ctx: screenMode ? "Screen" : ctxNow(), global: !sc, screen: screenMode, shape, anchor, created: new Date().toLocaleString(), text: "",
      pts: [], bbox: [Math.round(bx), Math.round(by), Math.round(bw), Math.round(bh)], elements: [], shot: null };
    if (sc && !document.querySelector(anchor.sel)) { n.anchor = { sel: "body" }; n.global = true; }
    const f = sc && n.anchor.sel !== "body" ? (() => { const r = sc.getBoundingClientRect(); return { ox: r.left - sc.scrollLeft, oy: r.top - sc.scrollTop }; })() : { ox: 0, oy: 0 };
    n.pts = pts.map(([x, y]) => [Math.round(x - f.ox), Math.round(y - f.oy)]);
    // что под областью: сетка точек внутри контура
    const seen = new Set();
    for (let i = 0; i <= 6; i++) for (let j = 0; j <= 6; j++) {
      const x = bx + bw * i / 6, y = by + bh * j / 6;
      if (!inPoly(x, y, pts)) continue;
      for (const el of under(x, y).slice(0, 2)) {
        if (seen.has(el) || el === document.body || el === document.documentElement) continue;
        seen.add(el); n.elements.push(describe(el, n.elements.length < 4));
        if (n.elements.length >= 16) break;
      }
    }
    state.notes.push(n); save(); renderBubbles();
    // снимок — только интерфейс и обводка, другие заметки его не закрывают; потом открываем заметку
    root.classList.add("shot");
    // заметка открывается всегда: и если снимок не удался, и если он завис (тогда через 1,5 с)
    let opened = false;
    // заметка открывается и сразу слушает: остаётся только нажать микрофон, когда договорил (просьба Saturni)
    const open = () => { if (opened) return; opened = true; root.classList.remove("shot"); openBub(n.n); startRec(n.n); };
    setTimeout(open, 1500);
    requestAnimationFrame(() => requestAnimationFrame(async () => {
      let r = null;
      try { r = await cfg.api("debug_shot", n.n, n.bbox, devicePixelRatio || 1, screenMode); } catch (e) { console.error("debug_shot", e); }
      if (typeof r === "string" && /\.png$/.test(r)) { n.shot = r; save(); }
      open();
    }));
    place();
  }

  // ── заметки ──
  const putEnd = e => { const r = document.createRange(); r.selectNodeContents(e); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); };
  function bubble(note) {
    const L = live.get(note.n) || { pend: [] };
    L.pend = L.pend || [];
    if (L.bub) return L.bub;
    const b = document.createElement("div");
    b.className = "sdbg-bub";
    b.innerHTML = `<div class="side"><span class="n">${note.n}</span><button class="rd mic" title="Dictate (or hold the mouse button)">${MIC}</button><button class="rd del" title="Delete the note">${BIN}</button></div>
      <div class="box"><div class="scroll"><span class="e" contenteditable="plaintext-only" spellcheck="false"></span> <span class="lv"></span></div><button class="jump"></button></div>`;
    const e = b.querySelector(".e"), box = b.querySelector(".box"), sc = b.querySelector(".scroll");
    if (note.size) { box.style.width = note.size[0] + "px"; box.style.height = note.size[1] + "px"; }
    e.textContent = note.text;
    b.classList.toggle("sdbg-empty", !note.text);
    e.addEventListener("input", () => { note.text = e.innerText.replace(/\n$/, ""); if (!note.text) e.textContent = ""; b.classList.toggle("sdbg-empty", !note.text); save(); jump(b); });
    sc.addEventListener("mousedown", ev => {           // клик в пустое место поля — каретка в конец текста, всегда видна
      if (b.classList.contains("open") && ev.target !== e && ev.button === 0) { ev.preventDefault(); e.focus(); putEnd(e); }
    });
    e.addEventListener("keydown", ev => { if (ev.key === "Escape") { ev.preventDefault(); closeBub(); } });
    sc.addEventListener("scroll", () => jump(b));
    box.addEventListener("mousemove", ev => { const k = edgeOf(box, ev); box.style.cursor = k === "se" ? "nwse-resize" : k === "e" ? "ew-resize" : k === "s" ? "ns-resize" : ""; });
    b.addEventListener("mousedown", ev => {
      ev.stopPropagation(); b.style.zIndex = ++zTop;      // нажатая заметка всегда сверху
      if (ev.button !== 0 || ev.target.closest(".rd,.jump")) return;
      const k = edgeOf(box, ev);
      if (k) return resize(note, box, k, ev);
      if (b.classList.contains("open") && ev.target.closest(".scroll")) return;
      if (!b.classList.contains("open")) ev.preventDefault();
      const r = b.getBoundingClientRect();
      follow(ev, (dx, dy) => { note.pos = [Math.round(r.left + dx), Math.round(r.top + dy)]; }, went => { if (went) save(); else if (!b.classList.contains("open")) openBub(note.n); });
    });
    b.querySelector(".mic").addEventListener("click", ev => { ev.stopPropagation(); rec && rec.n === note.n ? stopRec() : startRec(note.n); });
    b.querySelector(".del").addEventListener("click", ev => {
      ev.stopPropagation(); if (rec && rec.n === note.n) stopRec();
      state.notes = state.notes.filter(x => x.n !== note.n); b.remove(); live.delete(note.n); openN = null;
      state.next_n = state.notes.reduce((m, x) => Math.max(m, x.n), 0) + 1;     // номера идут подряд, без дыр в конце
      save(); renderBubbles();
    });
    b.querySelector(".jump").addEventListener("click", ev => { ev.stopPropagation(); sc.scrollTo({ top: atEnd(sc) ? 0 : sc.scrollHeight, behavior: "smooth" }); });
    dashBorder(box, 10);
    bubs.append(b);
    L.bub = b; live.set(note.n, L);
    return b;
  }
  const atEnd = sc => sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 3;
  function edgeOf(box, ev) {            // размер поля меняется только за его край
    const r = box.getBoundingClientRect(), e = r.right - ev.clientX < 7, s = r.bottom - ev.clientY < 7;
    return e && s ? "se" : e ? "e" : s ? "s" : "";
  }
  function resize(note, box, k, ev) {
    ev.preventDefault(); const w = box.offsetWidth, h = box.offsetHeight;
    follow(ev, (dx, dy) => {
      if (k !== "s") box.style.width = Math.max(140, w + dx) + "px";
      if (k !== "e") box.style.height = Math.max(46, h + dy) + "px";
    }, went => { if (went) { note.size = [box.offsetWidth, box.offsetHeight]; save(); } });
  }
  function jump(b) {                    // еле заметная кнопка: вниз, а внизу — наверх
    const sc = b.querySelector(".scroll"), j = b.querySelector(".jump"), over = sc.scrollHeight > sc.clientHeight + 3;
    j.classList.toggle("show", over && b.classList.contains("open")); j.innerHTML = atEnd(sc) ? I.up : I.down;
  }
  function openBub(n) {
    closeBub(); openN = n;
    const L = live.get(n); if (!L || !L.bub) return;
    L.bub.classList.add("open"); L.bub.style.zIndex = ++zTop;
    const e = L.bub.querySelector(".e"), sc = L.bub.querySelector(".scroll"); e.focus(); putEnd(e); sc.scrollTop = sc.scrollHeight; jump(L.bub);
  }
  function closeBub() {
    if (openN == null) return;
    if (rec && rec.n === openN) stopRec();        // вышел из заметки — микрофон выключается
    const L = live.get(openN);
    if (L && L.bub) { L.bub.classList.remove("open"); L.bub.querySelector(".scroll").scrollTop = 0; jump(L.bub); }
    openN = null; document.activeElement && root.contains(document.activeElement) && document.activeElement.blur();
  }
  function renderBubbles() {
    const vis = new Set(D.active ? visibleNotes().map(n => n.n) : []);
    for (const note of state.notes) { const b = bubble(note); b.style.display = vis.has(note.n) ? "" : "none"; }
    place();
  }

  function smooth(P) {                  // ручка: плавная кривая через середины отрезков
    if (P.length < 3) return `M${P.map(p => p.join(",")).join("L")}`;
    let d = `M${P[0][0]},${P[0][1]}`;
    for (let i = 1; i < P.length - 1; i++) d += `Q${P[i][0]},${P[i][1]} ${(P[i][0] + P[i + 1][0]) / 2},${(P[i][1] + P[i + 1][1]) / 2}`;
    const z = P[P.length - 1]; return d + `L${z[0]},${z[1]}`;
  }
  // Пунктир прямоугольной рамки: штрих 3, промежуток 2, линия 1 px по серединам пикселей.
  // На прямых все штрихи и промежутки строго одинаковые (3 и 2), целой длины от целого пикселя — чёткие, без дырок;
  // ряд стоит по середине стороны. Сторона редко делится на 5 нацело — остаток (0–4 px) уходит в углы: угол — это
  // кусочек прямой до дуги + дуга + кусочек после, и на нём свои штрихи поровну (там они и так сглажены, разница не видна).
  // Ни один штрих прямой не заходит на дугу. Классы: ds — прямые, 80 %; dc — углы, 100 % (сглаживание съедает яркость).
  // Тоньше 1 px линию нарисовать нельзя: экран красит пиксель целиком, только бледнее — «тоньше» = «прозрачнее».
  function crispDash(x, y, w, h, r, dash = DASH[0], gap = DASH[1]) {
    x = Math.round(x) + .5; y = Math.round(y) + .5; w = Math.round(w) - 1; h = Math.round(h) - 1;
    r = Math.max(0, Math.min(Math.round(r), Math.floor(w / 2), Math.floor(h / 2)));
    const END = 1.5;                                          // от дуги до первого штриха минимум 1.5 — конец на целом пикселе
    const side = (a, b) => {                                  // прямая от a до b (оба на .5): где ряд штрихов и сколько остаётся углам
      const L = b - a - 2 * END, k = L >= dash ? Math.floor((L + gap) / (dash + gap)) : 0;
      if (!k) return { k: 0, start: 0, s: (b - a) / 2, e: (b - a) / 2 };
      const rest = L - (k * dash + (k - 1) * gap), pre = Math.floor(rest / 2);
      return { k, start: a + END + pre, s: END + pre, e: END + rest - pre };
    };
    // все четыре угла одинаковые: остаток стороны должен делиться поровну на оба конца. Нечётный — рамка
    // подрастает на 1 px (crispDash.grow = [+w, +h]; элемент под рамкой подгоняется под неё, см. dashBorder)
    let H = side(x + r, x + w - r), V = side(y + r, y + h - r), dw = 0, dh = 0;
    if (H.s !== H.e) { w++; dw = 1; H = side(x + r, x + w - r); }
    if (V.s !== V.e) { h++; dh = 1; V = side(y + r, y + h - r); }
    crispDash.grow = [dw, dh];
    let s = "";
    for (let i = 0, p = H.start; i < H.k; i++, p += dash + gap) s += `M${p} ${y}H${p + dash}M${p} ${y + h}H${p + dash}`;
    for (let i = 0, p = V.start; i < V.k; i++, p += dash + gap) s += `M${x} ${p}V${p + dash}M${x + w} ${p}V${p + dash}`;
    // угол: от конца последнего штриха одной стороны до начала первого штриха другой; штрих = 1.5 промежутка.
    // На конце у штриха прямой — целый промежуток; если на стороне штрихов нет (короткая) и там встречаются два угла —
    // у каждого половина, иначе посередине стороны два промежутка подряд = дырка.
    const La = Math.PI * r / 2, A = (ex, ey) => r ? `A${r} ${r} 0 0 1 ${ex} ${ey}` : `L${ex} ${ey}`;
    const fH = H.k ? 1 : .5, fV = V.k ? 1 : .5;
    const corner = (e1, f1, e2, f2, d) => {
      const R = e1 + La + e2, k = dash / gap + 1;
      const n = Math.max(1, Math.round((R / gap + 1 - f1 - f2) / k)), g = R / (n * k - 1 + f1 + f2), dl = g * dash / gap;
      return `<path class="dc" stroke-dasharray="${dl.toFixed(3)} ${g.toFixed(3)}" stroke-dashoffset="${(-g * f1).toFixed(3)}" d="${d}"/>`;
    };
    const c =
      corner(V.s, fV, H.s, fH, `M${x} ${y + r + V.s}V${y + r}${A(x + r, y)}H${x + r + H.s}`) +
      corner(H.e, fH, V.s, fV, `M${x + w - r - H.e} ${y}H${x + w - r}${A(x + w, y + r)}V${y + r + V.s}`) +
      corner(V.e, fV, H.e, fH, `M${x + w} ${y + h - r - V.e}V${y + h - r}${A(x + w - r, y + h)}H${x + w - r - H.e}`) +
      corner(H.s, fH, V.e, fV, `M${x + r + H.s} ${y + h}H${x + r}${A(x, y + h - r)}V${y + h - r - V.e}`);
    return c + `<path class="ds" d="${s}"/>`;
  }
  // рамка-пунктир у элемента (бар, поле заметки): svg поверх его прозрачной рамки 1 px, перерисовка при смене размера
  function dashBorder(el, r) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("class", "sdbg-dash");
    el.append(s);
    const draw = () => {
      let w = el.offsetWidth, h = el.offsetHeight;
      if (!w || !h) return;                                 // ещё не на экране
      let html = crispDash(0, 0, w, h, r);
      const [dw, dh] = crispDash.grow;
      if (dw || dh) {                                       // подгоняем элемент: углы рамки должны быть одинаковыми
        if (dw) el.style.width = w + dw + "px";
        if (dh) el.style.height = h + dh + "px";
        w = el.offsetWidth; h = el.offsetHeight; html = crispDash(0, 0, w, h, r);
      }
      s.setAttribute("width", w); s.setAttribute("height", h); s.innerHTML = html;
    };
    new ResizeObserver(draw).observe(el); draw();
  }
  // Чёткий пунктир для рамок самих программ (все, где подключён Debug). В CSS вместо `border: 1px dashed C` пишем
  // `border: 1px solid transparent; --crisp-dash: C` (смена цвета на hover/.over — тоже через --crisp-dash).
  // Толщина = border-width, только целая (1 или 2); скругление = border-radius. Рисуется фоновой картинкой
  // svg — работает и у textarea, и у блоков, чьё содержимое перезаписывается. Размер элемента не трогаем:
  // если для одинаковых углов рамке не хватает 1 px — она на 1 px меньше справа/снизу.
  D.crispDash = crispDash;
  const crisp = { sels: "", els: new Set(), raf: 0, probe: null };
  function crispScan() {
    const sels = new Set();
    const walk = rules => { for (const r of rules) {
      if (r.cssRules) walk(r.cssRules);
      if (r.selectorText && r.style && r.style.getPropertyValue("--crisp-dash"))
        r.selectorText.split(",").forEach(s => sels.add(s.replace(/::?[a-z-]+(\([^)]*\))?/gi, "").trim() || "*"));
    } };
    for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) {} }
    sels.delete("*"); sels.delete("");
    crisp.sels = [...sels].join(",");
  }
  function crispColor(c) {
    if (!crisp.probe) { crisp.probe = document.createElement("i"); crisp.probe.hidden = true; document.documentElement.append(crisp.probe); }
    crisp.probe.style.color = ""; crisp.probe.style.color = c;
    return crisp.probe.style.color ? getComputedStyle(crisp.probe).color : "";
  }
  function crispDraw(el) {
    if (!el.isConnected) { crisp.els.delete(el); return; }
    const cs = getComputedStyle(el), raw = cs.getPropertyValue("--crisp-dash").trim();
    const w = el.offsetWidth, h = el.offsetHeight, c = raw && parseFloat(cs.borderTopWidth) ? crispColor(raw) : "";
    const k = Math.max(1, Math.round(parseFloat(cs.borderTopWidth) || 1)), r = parseFloat(cs.borderTopLeftRadius) || 0;
    const key = [w, h, k, r, c].join();
    if (el._cdKey === key) return;
    el._cdKey = key;
    if (!c || !w || !h || /,\s*0\)$|^transparent$/.test(c)) {   // рамки нет — убираем только свою картинку
      if (el._cdUrl && el.style.backgroundImage === el._cdUrl) el.style.backgroundImage = el._cdBase || "";
      el._cdUrl = ""; return;
    }
    let W = Math.floor(w / k), H = Math.floor(h / k), p = crispDash(0, 0, W, H, r / k);
    const [dw, dh] = crispDash.grow;
    if (dw || dh) p = crispDash(0, 0, W - dw, H - dh, r / k);
    p = p.replace(/class="ds"/g, 'stroke-opacity=".7"').replace(/class="dc"/g, "");
    const svgs = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><g transform="scale(${k})" fill="none" style="stroke:${c}" stroke-width="1">${p}</g></svg>`;
    const url = `url("data:image/svg+xml,${encodeURIComponent(svgs)}")`;
    if (el._cdBase === undefined) {                          // свой фон элемента (картинка/градиент) остаётся под рамкой
      const b = cs.backgroundImage; el._cdBase = b && b !== "none" ? b : "";
      Object.assign(el.style, { backgroundOrigin: "border-box", backgroundClip: "border-box" });
    }
    el.style.backgroundImage = el._cdBase ? `${url},${el._cdBase}` : url;
    el._cdUrl = el.style.backgroundImage;
    if (!el._cdBase) Object.assign(el.style, { backgroundRepeat: "no-repeat", backgroundPosition: "0 0", backgroundSize: "auto" });
  }
  const crispRO = "ResizeObserver" in window ? new ResizeObserver(es => es.forEach(e => crispDraw(e.target))) : null;
  function crispTick() {
    crisp.raf = 0;
    if (crisp.sels) for (const el of document.querySelectorAll(crisp.sels))
      if (!crisp.els.has(el) && !el.closest("#sdbg-root")) { crisp.els.add(el); crispRO && crispRO.observe(el); }
    crisp.els.forEach(crispDraw);
  }
  const crispLater = () => { if (!crisp.raf) crisp.raf = requestAnimationFrame(crispTick); };
  function crispStart() {
    crispScan(); crispTick();
    new MutationObserver(ms => { if (ms.some(m => !(m.target.closest && m.target.closest("#sdbg-root")))) crispLater(); })
      .observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "data-ui", "data-theme"] });
    ["pointerover", "pointerout", "focusin", "focusout", "dragenter", "dragleave", "drop"].forEach(t => document.addEventListener(t, crispLater, true));
    addEventListener("load", () => { crispScan(); crispLater(); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", crispStart); else setTimeout(crispStart);
  const R = 10;                        // скругление обводки: как у поля заметки
  const DASH = [3, 2];                  // все пунктиры отладки: штрих и промежуток, px
  function rectPath(x, y, w, h) {
    const r = Math.min(R, w / 2, h / 2);
    return `M${x + r},${y}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${2 * r - w}a${r},${r} 0 0 1 ${-r},${-r}v${2 * r - h}a${r},${r} 0 0 1 ${r},${-r}z`;
  }
  function shapePath(kind, P) {
    if (kind === "rect") { const [x, y, w, h] = bboxOf(P); return rectPath(x, y, w, h); }
    return `M${P.map(p => p.join(",")).join("L")}Z`;
  }
  // обводка области: прямоугольник — заливка отдельно, штрихи чётким пунктиром; круг и свободная — обычный пунктир
  function outlineHtml(cls, kind, P, attrs) {
    if (kind !== "rect") return `<path class="${cls}" ${attrs} d="${shapePath(kind, P)}"/>`;
    const [x, y, w, h] = bboxOf(P), r = Math.min(R, w / 2, h / 2);
    const st = crispDash(x, y, w, h, r), [dw, dh] = crispDash.grow;     // рамка могла подрасти на 1 px — заливка вместе с ней
    return `<g class="${cls} crisp" ${attrs}><path class="fl" d="${rectPath(Math.round(x), Math.round(y), Math.round(w) + dw, Math.round(h) + dh)}"/><g class="st">${st}</g></g>`;
  }
  function markHtml(m) {
    const st = `stroke="${m.color}" stroke-width="${m.size}"`, k = m.kind;
    const d = k === "pen" ? smooth(m.pts) : k === "rect" ? shapePath("rect", m.pts) : shapePath("ellipse", outline("ellipse", m.pts));
    return `<path class="mk" ${st} d="${d}"/>`;
  }
  function place() {
    if (!D.active) { svg.innerHTML = ""; return; }
    let html = "", defs = "";
    const hidden = root.classList.contains("hide-notes");
    for (const m of state.marks) if (markVisible(m)) html += markHtml(m);
    for (const note of visibleNotes()) {
      const L = live.get(note.n); const b = L && L.bub;
      const f = frame(note);
      if (!f) { if (b) b.style.display = "none"; continue; }
      const P = note.pts.map(([x, y]) => [x + f.ox, y + f.oy]);
      const [bx, by, bw, bh] = bboxOf(P), [cx, cy, cw, ch] = f.clip;
      const outside = bx > cx + cw || by > cy + ch || bx + bw < cx || by + bh < cy;
      if (b) b.style.display = outside ? "none" : "";
      if (outside) continue;
      // далеко от курсора — заметка тает, чтобы не мешать выделять рядом; навёлся или открыта — видна полностью
      // приглушена; полностью видна, только когда курсор прямо на ней (область или поле), открыта или пишет.
      // Раньше светлела уже рядом, по расстоянию — Saturni: «не рядом, а когда прямо навожу»
      let op = 1;
      if (fade && openN !== note.n && !(rec && rec.n === note.n)) {
        const [mx, my] = mouse, br = b && b.style.display !== "none" ? b.getBoundingClientRect() : null;
        const inside = (x, y, w, h) => mx >= x && mx <= x + w && my >= y && my <= y + h;
        op = inside(bx, by, bw, bh) || (br && inside(br.left, br.top, br.width, br.height)) ? 1 : .3;
      }
      if (b) b.style.opacity = op.toFixed(2);
      defs += `<clipPath id="sdbg-c${note.n}"><rect x="${cx}" y="${cy}" width="${cw}" height="${ch}"/></clipPath>`;
      html += outlineHtml(`sh${openN === note.n ? " act" : ""}`, note.shape, P, `opacity="${op.toFixed(2)}" clip-path="url(#sdbg-c${note.n})"`);
      if (b && !hidden) {
        const w = b.offsetWidth, h = b.offsetHeight;
        let x, y;
        if (note.pos) [x, y] = note.pos;
        else {
          x = bx + bw + 8; y = by - 4;
          if (x + w > innerWidth - 6) x = Math.max(6, bx - w - 8);
        }
        y = Math.min(Math.max(y, 6), innerHeight - h - 6); x = Math.min(Math.max(x, 6), innerWidth - w - 6);
        b.style.left = Math.round(x) + "px"; b.style.top = Math.round(y) + "px";
      }
    }
    const d = drawing;
    if (d && d.pts.length > 1) {
      if (d.tool === "pen") html += markHtml({ kind: d.kind, color: pen.color, size: pen.size, pts: d.pts });
      else if (d.kind === "free") html += `<path class="draw" d="M${d.pts.map(p => p.join(",")).join("L")}"/>`;
      else html += outlineHtml("draw", d.kind, outline(d.kind, d.pts), "");
    }
    svg.innerHTML = `<defs>${defs}</defs>${html}`;
  }
  function loop() {
    raf = 0;
    if (!D.active) { svg.innerHTML = ""; return; }
    renderVisibility(); place();
    raf = requestAnimationFrame(loop);
  }
  let lastCtx = null;
  function renderVisibility() {          // сменилась вкладка/файл — показать её заметки
    const c = ctxNow();
    if (c !== lastCtx) { lastCtx = c; renderBubbles(); }
  }

  // ── голос ──
  function noteAt(x, y) {
    const el = document.elementFromPoint(x, y);
    const b = el && el.closest && el.closest(".sdbg-bub");
    if (b) for (const [n, L] of live) if (L.bub === b) return n;
    for (const note of visibleNotes().slice().reverse()) {
      const f = frame(note); if (!f) continue;
      if (inPoly(x, y, note.pts.map(([px, py]) => [px + f.ox, py + f.oy]))) return note.n;
    }
    return openN;
  }
  function onHoldDown(e) {
    if (!D.active || (e.button !== 3 && e.button !== 4)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.button !== cfg.holdButton || rec) return;
    const n = noteAt(e.clientX, e.clientY);
    if (n != null) { if (openN !== n) openBub(n); startRec(n); }
  }
  function onHoldUp(e) {
    if (!D.active || (e.button !== 3 && e.button !== 4)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.button === cfg.holdButton && rec) stopRec();
  }
  function micShow(n, on) {
    const L = live.get(n), b = L && L.bub; if (!b) return;
    b.classList.toggle("rec", on); b.querySelector(".mic").classList.toggle("rec", on); showLive(n);
  }
  async function startRec(n) {
    if (rec) { if (rec.n === n) return; await stopRec(); }      // другая заметка: прежняя запись закрывается и обрабатывается сама
    const r = rec = { n, rid: null };
    micShow(n, true);
    const rid = await cfg.api("debug_rec_start", n);
    if (!rid) { if (rec === r) rec = null; micShow(n, false); return; }
    r.rid = rid; if (r.stopAsap) { r.stopAsap = false; finishRec(r); }
  }
  async function finishRec(r) { if (rec === r) rec = null; micShow(r.n, false); await cfg.api("debug_rec_stop"); }
  async function stopRec() {
    const r = rec; if (!r) return;
    micShow(r.n, false);
    if (!r.rid) { r.stopAsap = true; rec = null; return; }
    await finishRec(r);
  }
  // блоки речи заметки по порядку: сырой текст (серый, курсив) → готовый (встаёт в заметку)
  function blockOf(L, d) {
    const key = `${d.rec}:${d.seg ?? 0}`;
    let p = L.pend.find(x => x.key === key);
    if (!p) { p = { key, rec: d.rec, seg: d.seg ?? 0, text: "", done: false }; L.pend.push(p); L.pend.sort((a, b) => a.rec === b.rec ? a.seg - b.seg : a.rec < b.rec ? -1 : 1); }
    return p;
  }
  function showLive(n) {
    const L = live.get(n), b = L && L.bub; if (!b) return;
    const raw = L.pend.map(p => p.text).filter(Boolean).join(" "), lv = b.querySelector(".lv"), sc = b.querySelector(".scroll"), talking = !!(rec && rec.n === n);
    lv.textContent = raw; lv.classList.toggle("wait", !talking && L.pend.length > 0);
    b.classList.toggle("pend", L.pend.length > 0);
    if (b.classList.contains("open")) sc.scrollTop = sc.scrollHeight;
    jump(b);
  }
  D.handle = function (type, d) {
    if (!type || !type.startsWith("dbg_")) return false;
    const n = parseInt(String(d.cue || "").slice(4), 10);
    const note = state.notes.find(x => x.n === n), L = live.get(n), b = L && L.bub;
    const kind = type.slice(4);
    if (kind === "level" && b) b.querySelector(".mic").style.setProperty("--lv", d.v);   // свечение дышит с голосом
    if (kind === "rec" && b) {
      if (d.state === "error") { if (rec && rec.n === n) rec = null; micShow(n, false); alert(d.msg); }
      if (d.state === "off" && !(rec && rec.n === n)) micShow(n, false);
    }
    if (kind === "asr_text" && note && L) {
      const p = blockOf(L, d);
      if (d.text) p.text = d.text.trim();
      if (d.final) p.done = true;
      while (L.pend.length && L.pend[0].done) {
        const q = L.pend.shift();
        if (q.text) {
          note.text = (note.text.trim() ? note.text.trim() + " " : "") + q.text;
          if (b) { const e = b.querySelector(".e"), f = document.activeElement === e; e.textContent = note.text; b.classList.remove("sdbg-empty"); if (f) putEnd(e); }
          save();
        }
      }
      showLive(n);
    }
    return true;
  };

  function onKey(e) {
    if (e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d" || e.code === "KeyD")) { e.preventDefault(); e.stopImmediatePropagation(); D.toggle(); return; }
    if (!D.active) return;
    if (e.ctrlKey && e.code === "KeyZ" && !root.contains(document.activeElement) && state.marks.some(markVisible)) {   // убрать последний штрих
      e.preventDefault(); e.stopImmediatePropagation();
      for (let i = state.marks.length - 1; i >= 0; i--) if (markVisible(state.marks[i])) { state.marks.splice(i, 1); break; }
      save(); return;
    }
    if (e.key === "Escape") {
      e.preventDefault(); e.stopImmediatePropagation();
      if (openN != null) closeBub(); else if (drawing) cancelDraw(); else D.toggle(false);
    }
  }
})();
