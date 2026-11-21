// Saturni · Subs: одно приложение, два режима — Studio (основной) и Move. Окно одно, у каждого режима
// своя страница и свой Api: здесь окно-общий Api (studio, move, subs_switch) подменяется Api режима
// страницы, чтобы app.js режима работал как раньше. Переключатель кладётся в шапку (элемент .subs-modes).
(function () {
  "use strict";
  const MODE = document.documentElement.dataset.subs;           // "studio" | "move"
  function swap() {
    const R = window.pywebview && window.pywebview.api;
    if (!R || !R[MODE] || window.__subs) return;
    window.__subs = R;
    window.pywebview.api = R[MODE];
  }
  swap();
  addEventListener("pywebviewready", swap);                     // раньше обработчика app.js: скрипт подключён до него

  function mount() {
    const box = document.querySelector(".subs-modes");
    if (!box) return;
    box.innerHTML = '<span class="lens"></span><button data-subs-mode="studio">Studio</button><button data-subs-mode="move">Move</button>';
    const lens = box.querySelector(".lens"), on = box.querySelector(`[data-subs-mode="${MODE}"]`);
    on.classList.add("on");
    const place = b => { lens.style.width = b.offsetWidth + "px"; lens.style.transform = `translateX(${b.offsetLeft}px)`; };
    requestAnimationFrame(() => place(on));
    document.fonts && document.fonts.ready.then(() => place(on));
    box.addEventListener("click", async e => {
      const b = e.target.closest("[data-subs-mode]");
      if (!b || b.dataset.subsMode === MODE || !window.__subs) return;
      place(b);
      box.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      const r = await window.__subs.subs_switch(b.dataset.subsMode);
      if (!r || !r.ok) {                                          // несохранённое или занято — остаёмся
        place(on); box.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === on));
        const msg = r && r.why === "unsaved" ? "Save the markers first" : "Claude is still applying the edits";
        box.title = msg; box.classList.add("no"); setTimeout(() => { box.classList.remove("no"); box.title = ""; }, 1600);
      }
    });
  }
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", mount); else mount();
})();
