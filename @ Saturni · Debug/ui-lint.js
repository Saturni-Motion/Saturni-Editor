// Saturni · UI lint — автоматическая проверка окна на типичные ошибки интерфейса, которые делает ИИ.
// Запуск: вставить в страницу (evaluate_js / консоль) и вызвать SaturniLint.run() → список находок,
// SaturniLint.show() — то же, плюс красные рамки на странице (SaturniLint.clear() убирает).
// Проверяет только видимые элементы. Пороги в пикселях CSS.
(function () {
  "use strict";
  const L = window.SaturniLint = {};
  const TOL = 1;                                         // допуск центра, px
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05; };
  // Элемент не «за краем окна», если его обрезает прокручиваемый родитель (виртуальная сетка) или родитель прозрачен (спрятанная зона).
  const clippedOrInvisible = (el, r) => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (+s.opacity < 0.05) return true;
      if (/(auto|scroll|hidden|clip)/.test(s.overflowY + s.overflowX)) {
        const p = e.getBoundingClientRect();
        if (r.bottom > p.bottom + 1 || r.right > p.right + 1) return true;
      }
    }
    return false;
  };
  const path = el => { const p = []; for (let e = el; e && e !== document.body && p.length < 4; e = e.parentElement)
    p.unshift(e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.classList[0] ? "." + e.classList[0] : "")); return p.join(" > "); };
  const label = el => (el.getAttribute("title") || el.getAttribute("data-tip") || el.textContent || "").trim().slice(0, 30);

  // Видимое содержимое кнопки: текстовые узлы (по самим буквам) и значки (svg, img, иконочный шрифт).
  function contentBox(el) {
    let b = null;
    const add = r => { if (r.width < 0.5 || r.height < 0.5) return;
      b = b ? { l: Math.min(b.l, r.left), t: Math.min(b.t, r.top), r: Math.max(b.r, r.right), b: Math.max(b.b, r.bottom) }
            : { l: r.left, t: r.top, r: r.right, b: r.bottom }; };
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: n => n.nodeType === 1 && n !== el && (!vis(n) || n.matches(".sdbg-badge, .saturni-lint"))   // счётчик Debug — не содержимое
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    for (let n = w.currentNode; n; n = w.nextNode()) {
      if (n.nodeType === 3 && n.textContent.trim()) {
        const rg = document.createRange(); rg.selectNodeContents(n);
        const s = getComputedStyle(n.parentElement), rr = rg.getBoundingClientRect();
        // Оптический центр строки = середина заглавных: от базовой линии до высоты «H» (хвосты y/p не считаются).
        // Базовая линия: прямоугольник текста начинается с верха области шрифта, ниже на подъём шрифта — базовая линия
        // (так в любом раскладе, в том числе когда текст лежит прямо во flex-кнопке).
        const font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
        const base = rr.top + glyphMetrics(font, "H").fa;
        if (/Segoe (Fluent|MDL2)|icon/i.test(s.fontFamily)) {           // значок из иконочного шрифта: по самому знаку
          const g = glyphMetrics(font, n.textContent.trim());
          add({ left: rr.left, right: rr.right, top: base - g.asc, bottom: base + g.desc, width: rr.width, height: g.asc + g.desc });
        } else {
          const cap = glyphMetrics(font, "H").asc;
          add({ left: rr.left, right: rr.right, top: base - cap, bottom: base, width: rr.width, height: cap });
        }
      } else if (n.nodeType === 1 && /^(svg|img|canvas)$/i.test(n.tagName)) add(n.getBoundingClientRect());
    }
    return b;
  }
  const cv = document.createElement("canvas").getContext("2d");
  function glyphMetrics(font, text) {
    cv.font = font;
    const m = cv.measureText(text);
    return { asc: m.actualBoundingBoxAscent, desc: m.actualBoundingBoxDescent, fa: m.fontBoundingBoxAscent, fd: m.fontBoundingBoxDescent };
  }

  L.run = function () {
    const out = [];
    const push = (el, kind, msg) => out.push({ kind, msg, el: path(el), label: label(el), node: el });
    const btns = [...document.querySelectorAll("button, [role=button], .btn, .ibtn, .tbtn, .seg-item")].filter(vis);

    for (const el of btns) {
      const r = el.getBoundingClientRect(), s = getComputedStyle(el), c = contentBox(el);
      if (c && s.display !== "inline") {
        const just = s.justifyContent, align = s.textAlign;
        const dy = ((c.t + c.b) / 2) - (r.top + r.height / 2);
        if (Math.abs(dy) > TOL) push(el, "center-y", `содержимое не по центру по вертикали на ${dy.toFixed(1)} px`);
        // по горизонтали проверяем только то, что задумано по центру: значок без текста или равные поля слева и справа
        const iconOnly = !el.textContent.trim() && el.querySelector("svg,img");
        const sym = Math.abs(parseFloat(s.paddingLeft) - parseFloat(s.paddingRight)) < 0.5;
        const centred = iconOnly || (sym && (/center/.test(just) || align === "center"));
        if (centred) { const dx = ((c.l + c.r) / 2) - (r.left + r.width / 2);
          if (Math.abs(dx) > TOL) push(el, "center-x", `содержимое не по центру по горизонтали на ${dx.toFixed(1)} px`); }
        if (c.l < r.left - 0.5 || c.r > r.right + 0.5 || c.t < r.top - 0.5 || c.b > r.bottom + 0.5)
          push(el, "overflow", "содержимое вылезает за кнопку");
      }
      if (el.textContent.trim() && s.lineHeight === "normal") push(el, "line-height", "line-height: normal — центр зависит от шрифта, нужен line-height:1");
      if (!/Inter/i.test(s.fontFamily) && el.textContent.trim() && !/Segoe (Fluent|MDL2)/i.test(s.fontFamily))
        push(el, "font", `шрифт не Inter: ${s.fontFamily.split(",")[0]}`);
      if (/gradient/.test(s.backgroundImage)) push(el, "style", "градиент на кнопке (правило: заливка ровным цветом или без заливки)");
      if (r.left % 1 || r.top % 1) { if (/dashed|dotted/.test(s.borderStyle)) push(el, "subpixel", "пунктир на дробных координатах — будет мыльным"); }
    }

    // Кнопки одного ряда разной высоты
    const rows = new Map();
    for (const el of btns) { if (el.closest(".menu, .sdbg-gmenu")) continue;
      const key = el.parentElement; if (!rows.has(key)) rows.set(key, []); rows.get(key).push(el); }
    for (const [, list] of rows) {
      const hs = [...new Set(list.map(e => Math.round(e.getBoundingClientRect().height)))];
      if (list.length > 1 && hs.length > 1 && Math.max(...hs) - Math.min(...hs) > 2)
        push(list[0], "row-height", `кнопки в одном ряду разной высоты: ${hs.join(", ")} px`);
    }

    // Текст, обрезанный без многоточия, и элементы за краем окна
    for (const el of document.querySelectorAll("body *")) {
      if (!vis(el) || el.children.length) continue;
      const s = getComputedStyle(el), r = el.getBoundingClientRect();
      if (el.scrollWidth > el.clientWidth + 1 && s.overflow !== "visible" && s.textOverflow !== "ellipsis" && el.textContent.trim())
        push(el, "clip", "текст обрезан без многоточия");
      if (r.right > innerWidth + 1 || r.bottom > innerHeight + 1) if (s.position !== "fixed" && !el.closest("[style*=overflow], .scroll, .list") && !clippedOrInvisible(el, r))
        push(el, "offscreen", "элемент за краем окна");
    }

    // Эмодзи вместо значков
    for (const el of btns) if (/\p{Extended_Pictographic}/u.test(el.textContent)) push(el, "emoji", "эмодзи вместо значка");
    return out;
  };

  L.show = function () {
    L.clear();
    const res = L.run();
    for (const f of res) {
      const r = f.node.getBoundingClientRect(), d = document.createElement("div");
      d.className = "saturni-lint";
      d.style.cssText = `position:fixed;left:${r.left - 2}px;top:${r.top - 2}px;width:${r.width + 4}px;height:${r.height + 4}px;` +
        "outline:2px solid #ff4d4d;z-index:2147483647;pointer-events:none";
      d.title = f.msg; document.body.appendChild(d);
    }
    return res.map(f => `${f.kind}\t${f.el}\t«${f.label}»\t${f.msg}`).join("\n") || "чисто";
  };
  L.clear = () => document.querySelectorAll(".saturni-lint").forEach(e => e.remove());
  L.report = () => JSON.stringify(L.run().map(f => ({ kind: f.kind, el: f.el, label: f.label, msg: f.msg })));
})();
