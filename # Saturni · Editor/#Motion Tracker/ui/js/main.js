/* Saturni · Motion Tracker: one page for two hosts.
   CEP (Premiere panel): clip from the timeline, Python tracker as a child process, keyframes via ExtendScript.
   APP (# Saturni · Motion Tracker.pyw window): a video file, the tracker inside the app, Apply = render a new file.
   The Premiere extensions folder links to this folder (junction), so there is one copy of the code. */
(function () {
  "use strict";

  var CEP = !!window.__adobe_cep__;
  var nodeRequire = CEP ? (typeof require === "function" ? require : (window.cep_node && window.cep_node.require)) : null;
  var fs, path, os, spawn, EXT_DIR, TRACKER_PY, TMP_DIR, APP_DIR;
  if (CEP) {
    fs = nodeRequire("fs"); path = nodeRequire("path"); os = nodeRequire("os"); spawn = nodeRequire("child_process").spawn;
    EXT_DIR = path.dirname(decodeURIComponent(location.pathname).replace(/^\/([A-Za-z]:)/, "$1"));
    try { EXT_DIR = fs.realpathSync(EXT_DIR); } catch (e) {}          // through the junction to #Motion Tracker\ui
    APP_DIR = path.dirname(EXT_DIR);
    TRACKER_PY = path.join(APP_DIR, "core", "tracker.py");
    TMP_DIR = path.join(os.tmpdir(), "PointTracker");
  }

  var $ = function (id) { return document.getElementById(id); };
  var ui = {
    prepare: $("btnPrepare"), attach: $("btnAttach"), stabilize: $("btnStabilize"), clearBox: $("btnClearBox"),
    canvas: $("canvas"), strip: $("strip"), viewer: $("viewer"), frameLabel: $("frameLabel"),
    status: $("status"), progress: $("progress"), settingsBtn: $("btnSettings"), settings: $("settings"),
    hideOthers: $("hideOthers"), ignoreKeys: $("ignoreKeys"), python: $("python"),
    reduce: $("chipReduce"), smooth: $("chipSmooth")
  };
  var ctx = ui.canvas.getContext("2d"), sctx = ui.strip.getContext("2d");

  var S = {
    clip: null,     // clip info from host (sequence seconds)
    info: null,     // video info from python
    frame: 0, img: null,
    box: null,      // feature box, full-res pixels {x,y,w,h}, placed on frame S.boxFrame
    margin: null,   // search margin on each side, full-res pixels {x,y}
    boxFrame: 0,
    track: null,    // {ref, points:[[x,y,conf,scale,angle]], key}
    adapt: "low",
    view: { zoom: 1, cx: 0, cy: 0 }, // view center in preview pixels
    busy: false
  };

  // ---------- settings (per-viewer conveniences) ----------
  function loadSetting(k, d) { try { var v = localStorage.getItem("pt." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }
  function saveSetting(k, v) { try { localStorage.setItem("pt." + k, JSON.stringify(v)); } catch (e) {} }
  ui.hideOthers.classList.toggle("on", loadSetting("hideOthers", false));
  ui.ignoreKeys.classList.toggle("on", loadSetting("ignoreKeys", false));
  ui.python.value = loadSetting("python", "python");
  [ui.hideOthers, ui.ignoreKeys].forEach(function (b) {
    b.addEventListener("click", function () { saveSetting(b.id, b.classList.toggle("on")); });
  });
  ui.python.addEventListener("change", function () { saveSetting("python", ui.python.value); stopPython(); });

  ui.settingsBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    var open = !ui.settings.classList.contains("open");
    ui.settings.classList.toggle("open", open);
    ui.settingsBtn.classList.toggle("open", open);
  });
  document.addEventListener("mousedown", function (e) {
    if (!ui.settings.contains(e.target) && !ui.settingsBtn.contains(e.target)) {
      ui.settings.classList.remove("open"); ui.settingsBtn.classList.remove("open");
    }
  });

  // ---------- chips ----------
  // Liquid-glass switches. Every chosen item is a capsule; each group of neighbouring capsules is drawn as ONE
  // outline (one fill, one rim), so there is never a seam. Turning an item on next to a chosen neighbour simply
  // stretches the neighbour's capsule over it (and back when turned off). Between two chosen neighbours the
  // capsules melt: the outline is the smooth union of their distance fields, so they reach for each other with a
  // neck — twice as fast as a stretch. Single-choice rows: the capsule travels to the new item, stretching over both.
  var NS = "http://www.w3.org/2000/svg", INSET = 3, NECK = 12, MOVE_MS = 420, gradIds = 0;
  var easeOut = function (t) { return 1 - Math.pow(1 - t, 3); };
  var easeSharp = function (t) { return 1 - Math.pow(1 - t, 4); };            // quick start, long soft finish
  var softBubble = function (t) { var c = 0.7; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); };

  // opts: { ease: end of a stretch or travel, speed: 1 = MOVE_MS }
  function Liquid(row, single, onChange, opts) {
    opts = opts || {};
    var endEase = opts.ease || easeSharp, base = MOVE_MS / (opts.speed || 1);
    var items = Array.prototype.slice.call(row.querySelectorAll(".seg-item"));
    var on = function (i) { return items[i].classList.contains("on"); };
    var L = function (i) { return items[i].offsetLeft; };
    var Rt = function (i) { return items[i].offsetLeft + items[i].offsetWidth; };
    var H = function () { return items[0].offsetHeight; };
    var cut = function (i) { return (Rt(i - 1) + L(i)) / 2; };   // items overlap by 2×INSET; joined capsules meet halfway
    var svg = document.createElementNS(NS, "svg"), id = "lq" + gradIds++;
    svg.setAttribute("class", "liquid"); row.insertBefore(svg, row.firstChild);
    svg.innerHTML = '<defs><linearGradient id="' + id + 'f" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" class="fs0"/><stop offset="1" class="fs1"/></linearGradient>' +
      '<linearGradient id="' + id + 'r" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0" class="rs0"/><stop offset=".3" class="rs1"/><stop offset=".6" class="rs2"/><stop offset="1" class="rs3"/></linearGradient></defs>';
    var blobs = items.map(function () { return { l: 0, r: 0, rad: 0 }; }), neck = 0, run = null;

    function target(i, st) {   // the capsule of item i for a set of chosen items
      var R = H() / 2, c = (L(i) + Rt(i)) / 2;
      if (!st[i]) return { l: c, r: c, rad: 0 };
      return { l: i > 0 && st[i - 1] ? cut(i) - R : L(i) + INSET, r: i < items.length - 1 && st[i + 1] ? cut(i + 1) + R : Rt(i) - INSET, rad: R };
    }
    function targets(st) { return items.map(function (_, i) { return target(i, st); }); }
    function dist(b, x, y) {   // signed distance to a horizontal capsule centred on y = 0
      var rad = Math.min(b.rad, (b.r - b.l) / 2); if (rad <= 0.2) return 1e9;
      var qx = Math.max(Math.abs(x - (b.l + b.r) / 2) - ((b.r - b.l) / 2 - rad), 0);
      return Math.sqrt(qx * qx + y * y) - rad;
    }
    function smin(a, b, k) { var h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k / 4; }
    function field(x, y) {
      var d = 1e9;
      for (var n = 0; n < blobs.length; n++) d = neck ? smin(d, dist(blobs[n], x, y), neck) : Math.min(d, dist(blobs[n], x, y));
      return d;
    }
    function draw() {
      var R = H() / 2, w = row.offsetWidth, xs = [], hs = [], x, n;
      svg.setAttribute("width", w); svg.setAttribute("height", H());
      // half-height of the outline at every x, clamped to R so joined capsules stay flat-sided
      for (x = -4; x <= w + 4; x += 0.5) {
        var h = 0;
        if (field(x, 0) < 0) {
          var lo = 0, hi = R + neck;
          for (n = 0; n < 14; n++) { var m = (lo + hi) / 2; if (field(x, m) < 0) lo = m; else hi = m; }
          h = Math.min(lo, R);
        }
        xs.push(x); hs.push(h);
      }
      var paths = [], cur = null;
      hs.forEach(function (hh, i) { if (hh > 0.05) { if (!cur) paths.push(cur = []); cur.push(i); } else cur = null; });
      paths = paths.map(function (run) {
        var top = run.map(function (i) { return xs[i].toFixed(2) + "," + (R - hs[i]).toFixed(2); });
        var bot = run.slice().reverse().map(function (i) { return xs[i].toFixed(2) + "," + (R + hs[i]).toFixed(2); });
        return "M" + top.join("L") + "L" + bot.join("L") + "Z";
      });
      var groups = svg.querySelectorAll("g");
      for (n = groups.length; n < paths.length; n++) {
        var g = document.createElementNS(NS, "g");
        g.innerHTML = '<path class="fill" fill="url(#' + id + 'f)"/><path class="rim" stroke="url(#' + id + 'r)"/>';
        svg.appendChild(g);
      }
      groups = svg.querySelectorAll("g");
      for (n = 0; n < groups.length; n++) {
        var d = paths[n] || "";
        groups[n].style.display = d ? "" : "none";
        groups[n].children[0].setAttribute("d", d); groups[n].children[1].setAttribute("d", d);
      }
    }
    // from → to over dur; keep: the capsules after the move (one that only hid inside its neighbour is dropped)
    function animate(dur, ease, from, to, keep, k) {
      if (run) run.stop();
      keep = keep || to; neck = k || 0;
      var t0 = performance.now(), alive = true;
      function tick(now) {
        if (!alive) return;
        var t = Math.min(1, (now - t0) / dur), e = ease(t);
        blobs = t >= 1 ? keep : from.map(function (a, i) {
          return { l: a.l + (to[i].l - a.l) * e, r: a.r + (to[i].r - a.r) * e, rad: a.rad + (to[i].rad - a.rad) * e };
        });
        if (t >= 1) { alive = false; neck = 0; }
        draw();
        if (alive) requestAnimationFrame(tick);
      }
      tick(t0);
      run = { stop: function () { if (alive) { alive = false; neck = 0; blobs = keep; draw(); } } };
    }
    function state() { return items.map(function (_, i) { return on(i); }); }
    function place() { if (run) run.stop(); blobs = targets(state()); draw(); }

    items.forEach(function (it, k) {
      it.addEventListener("click", function () {
        var from = blobs.map(function (b) { return { l: b.l, r: b.r, rad: b.rad }; });
        if (single) { if (on(k)) return; items.forEach(function (o) { o.classList.toggle("on", o === it); }); }
        else it.classList.toggle("on");
        var st = state(), to = targets(st), R = H() / 2;
        if (single) {
          var a = from.findIndex(function (b) { return b.rad > 0; }), dur = base * 1.2, half = dur * 0.45;
          if (a >= 0 && a !== k) {   // travel: stretch over both items, then settle on the new one
            var mid = to.map(function (b, i) { return i === k ? { l: Math.min(from[a].l, to[k].l), r: Math.max(from[a].r, to[k].r), rad: R } : { l: b.l, r: b.l, rad: 0 }; });
            from[k] = { l: from[a].l, r: from[a].r, rad: from[a].rad };
            from[a] = { l: (from[a].l + from[a].r) / 2, r: (from[a].l + from[a].r) / 2, rad: 0 };
            animate(half, easeOut, from, mid);
            setTimeout(function () { animate(dur - half, endEase, blobs.map(function (b) { return { l: b.l, r: b.r, rad: b.rad }; }), to); }, half);
          } else animate(dur, endEase, from, to);
        } else {
          var left = k > 0 && st[k - 1], right = k < items.length - 1 && st[k + 1];
          if (left && right) animate(base / 2, easeOut, from, to, to, NECK);   // between two: they melt, twice as fast
          else if (left || right) {
            // next to a chosen neighbour: its capsule stretches over this item (or back); this item's own capsule
            // starts / ends as the neighbour's rounded end, hidden inside it
            var x = left ? Rt(k - 1) - INSET : L(k + 1) + INSET;
            var hidden = left ? { l: x - 2 * R, r: x, rad: R } : { l: x, r: x + 2 * R, rad: R };
            if (st[k]) from[k] = hidden; else to[k] = hidden;
            animate(base, endEase, from, to, targets(st));
          } else animate(base, endEase, from, to);
        }
        if (onChange) onChange(it);
      });
    });
    return { place: place };
  }
  var segItems = Array.prototype.slice.call(document.querySelectorAll("#propChips .seg-item"));
  var liquids = [
    Liquid($("propChips"), false),
    Liquid($("keyChips"), false, null, { ease: softBubble, speed: 1.25 }),
    Liquid($("adaptChips"), true, function (it) { S.adapt = it.getAttribute("data-adapt"); })
  ];
  function placeAll() { liquids.forEach(function (l) { l.place(); }); }
  window.addEventListener("resize", placeAll);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(placeAll);
  placeAll();
  function props() {
    return segItems.filter(function (c) { return c.classList.contains("on"); })
      .map(function (c) { return c.getAttribute("data-prop"); }).join("");
  }

  // ---------- status bar with hover tips ----------
  var statusText = $("statusText");
  var statusMsg = { text: statusText.textContent, kind: "" }, tipEl = null;
  function renderStatus() {
    var text = tipEl ? tipEl.getAttribute("data-tip") : statusMsg.text, kind = tipEl ? "tip" : statusMsg.kind;
    text = text.replace(/\s*\n+\s*/g, "  ·  ");
    ui.status.className = kind;
    if (statusText.textContent !== text) { statusText.textContent = text; marquee.reset(); }
    else marquee.measure();
  }

  // One-line status: centered when it fits; otherwise it holds, scrolls to the end, holds, jumps back.
  // It can also be dragged left/right by hand.
  var marquee = (function () {
    var HOLD = 1600, SPEED = 22; // ms, px per second
    var offset = 0, max = 0, phase = "hold", since = 0, last = 0, dragX = null, dragOff = 0;
    function applyOffset() { statusText.style.transform = "translateX(" + (-offset) + "px)"; }
    function measure() {
      max = Math.max(0, statusText.offsetWidth - ui.status.clientWidth);
      ui.status.classList.toggle("overflow", max > 0);
      offset = Math.min(offset, max); applyOffset();
    }
    function reset() { offset = 0; phase = "hold"; since = performance.now(); measure(); }
    function tick(now) {
      var dt = Math.min(100, now - (last || now)); last = now;
      if (max > 0 && dragX === null) {
        if (phase === "hold" && now - since > HOLD) phase = "scroll";
        else if (phase === "scroll") {
          offset = Math.min(max, offset + SPEED * dt / 1000);
          if (offset >= max) { phase = "end"; since = now; }
          applyOffset();
        } else if (phase === "end" && now - since > HOLD) { offset = 0; phase = "hold"; since = now; applyOffset(); }
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
    ui.status.addEventListener("mousedown", function (e) {
      if (max <= 0) return;
      dragX = e.clientX; dragOff = offset;
      ui.status.classList.add("dragging"); e.preventDefault();
    });
    window.addEventListener("mousemove", function (e) {
      if (dragX === null) return;
      offset = Math.max(0, Math.min(max, dragOff - (e.clientX - dragX))); applyOffset();
    });
    window.addEventListener("mouseup", function () {
      if (dragX === null) return;
      dragX = null; ui.status.classList.remove("dragging");
      phase = offset >= max ? "end" : "hold"; since = performance.now() + HOLD; // give time to read
    });
    window.addEventListener("resize", measure);
    return { reset: reset, measure: measure };
  })();
  function status(text, kind) { statusMsg = { text: text, kind: kind || "" }; renderStatus(); }
  // Tips: shown at once from an empty status, switch after 1 s between elements, stay 2 s after
  // leaving (time to reach the status bar), and freeze while the pointer is on the status bar.
  var tipTimer = null, pendingTip = null;
  function scheduleTip(el) {
    if (el === pendingTip && (tipTimer || el === tipEl)) return;
    clearTimeout(tipTimer); tipTimer = null; pendingTip = el;
    if (el === tipEl) return;
    var delay = !el ? 2000 : tipEl ? 1000 : 0;
    if (!delay) { tipEl = el; renderStatus(); return; }
    tipTimer = setTimeout(function () { tipTimer = null; tipEl = pendingTip; renderStatus(); }, delay);
  }
  document.addEventListener("mouseover", function (e) {
    if (drag || ui.status.classList.contains("dragging")) return;
    if ($("statusBar").contains(e.target) && !ui.settingsBtn.contains(e.target)) {
      clearTimeout(tipTimer); tipTimer = null; pendingTip = tipEl; // keep what is shown
      return;
    }
    scheduleTip(e.target.closest ? e.target.closest("[data-tip]") : null);
  });
  document.addEventListener("mouseleave", function () { scheduleTip(null); });
  function progress(frac) { ui.progress.style.width = frac == null ? "0" : Math.round(frac * 100) + "%"; }

  function refreshButtons() {
    ui.prepare.disabled = S.busy;
    ui.attach.disabled = ui.stabilize.disabled = S.busy || !S.box || !S.info;
    ui.clearBox.style.visibility = S.info ? "visible" : "hidden";
  }

  // ---------- ExtendScript bridge ----------
  function host(fn, args) {
    var code = fn + "(" + (args || []).map(function (a) { return JSON.stringify(a); }).join(",") + ")";
    return new Promise(function (resolve, reject) {
      window.__adobe_cep__.evalScript(code, function (res) {
        var r;
        try { r = JSON.parse(res); } catch (e) { return reject(new Error("Premiere replied: " + res)); }
        r.ok ? resolve(r.result) : reject(new Error(r.error));
      });
    });
  }

  // ---------- Python process ----------
  var py = null, pyBuf = "", pyNext = 1, pyPending = {}, pyReady = null;

  function startPython() {
    if (pyReady) return pyReady;
    pyReady = new Promise(function (resolve, reject) {
      var proc = spawn(ui.python.value || "python", ["-I", TRACKER_PY], { windowsHide: true });
      py = proc;
      var stderr = "";
      proc.stdout.setEncoding("utf8");
      proc.stdout.on("data", function (chunk) {
        pyBuf += chunk;
        var nl;
        while ((nl = pyBuf.indexOf("\n")) >= 0) {
          var line = pyBuf.slice(0, nl); pyBuf = pyBuf.slice(nl + 1);
          if (!line.trim()) continue;
          var m; try { m = JSON.parse(line); } catch (e) { continue; }
          if (m.ready) { resolve(); continue; }
          var p = pyPending[m.id]; if (!p) continue;
          if (m.progress != null) { p.onProgress && p.onProgress(m.progress, m.total); continue; }
          delete pyPending[m.id];
          m.ok ? p.resolve(m.result) : p.reject(new Error(m.error));
        }
      });
      proc.stderr.on("data", function (d) { stderr += d; });
      proc.on("error", function (e) {
        pyReady = null; py = null;
        reject(new Error("Could not start Python (" + e.message + "). Set its path in settings."));
      });
      proc.on("exit", function () {
        var err = new Error("Python exited: " + (stderr.trim().split("\n").pop() || "no message"));
        Object.keys(pyPending).forEach(function (id) { pyPending[id].reject(err); });
        pyPending = {}; pyReady = null; py = null;
        reject(err);
      });
    });
    return pyReady;
  }

  function stopPython() { if (py) { try { py.kill(); } catch (e) {} } py = null; pyReady = null; }

  // APP: the tracker runs inside the window's Python; progress comes back through window.__ptMsg.
  var appPending = {}, appNext = 1;
  window.__ptMsg = function (m) { var p = appPending[m.id]; if (p && m.progress != null) p(m.progress, m.total); };
  function appApi() { return window.pywebview && window.pywebview.api; }

  function pyCall(cmd, params, onProgress) {
    if (!CEP) {
      var id = "a" + appNext++;
      appPending[id] = onProgress || null;
      return Promise.resolve(appApi().call(id, cmd, params || {})).then(function (r) {
        delete appPending[id];
        if (!r || !r.ok) throw new Error(r ? r.error : "No answer from the tracker");
        return r.result;
      });
    }
    return startPython().then(function () {
      return new Promise(function (resolve, reject) {
        var id = pyNext++;
        pyPending[id] = { resolve: resolve, reject: reject, onProgress: onProgress };
        py.stdin.write(JSON.stringify(Object.assign({ id: id, cmd: cmd }, params || {})) + "\n");
      });
    });
  }

  if (CEP) window.addEventListener("beforeunload", stopPython);

  // ---------- export preset ----------
  function findPreset() {
    var rel = path.join("MediaIO", "systempresets", "3F3F3F3F_4D6F6F56", "H264 Match Source - High bitrate.epr");
    var root = "C:\\Program Files\\Adobe", dirs = [];
    try { dirs = fs.readdirSync(root); } catch (e) {}
    dirs = dirs.filter(function (d) { return /^Adobe Premiere Pro/i.test(d); }).sort().reverse();
    for (var i = 0; i < dirs.length; i++) {
      var p = path.join(root, dirs[i], rel);
      if (fs.existsSync(p)) return p;
    }
    throw new Error("Export preset \"H264 Match Source - High bitrate.epr\" not found");
  }

  function cleanTmp() {
    try {
      if (!fs.existsSync(TMP_DIR)) fs.mkdirSync(TMP_DIR, { recursive: true });
      fs.readdirSync(TMP_DIR).forEach(function (f) {
        if (/^clip_\d+\.mp4$/.test(f)) { try { fs.unlinkSync(path.join(TMP_DIR, f)); } catch (e) {} }
      });
    } catch (e) {}
  }

  // ---------- prepare ----------
  ui.prepare.addEventListener("click", function () {
    S.busy = true; refreshButtons();
    var out;
    Promise.resolve().then(function () {
      if (!CEP) return Promise.resolve(appApi().open_video()).then(function (v) {     // APP: a video file
        if (!v) throw new Error("cancel");
        out = v.path;
        return { name: v.name, start: 0, playhead: 0, fps: v.fps, seqW: v.width, seqH: v.height };
      });
      cleanTmp();
      out = path.join(TMP_DIR, "clip_" + Date.now() + ".mp4");
      status("Rendering clip… Premiere may freeze for a moment.");
      progress(null);
      return host("pt_exportClip", [out, findPreset(), ui.hideOthers.classList.contains("on"), ui.ignoreKeys.classList.contains("on")]);
    }).then(function (clip) {
      S.clip = clip;
      status("Reading frames…");
      progress(0);
      return pyCall("open", { path: out }, function (d, t) { progress(t ? d / t : 0); });
    }).then(function (info) {
      S.info = info; S.track = null; S.box = null; S.margin = null;
      var idx = Math.round((S.clip.playhead - S.clip.start) * S.clip.fps);
      if (idx < 0 || idx >= info.frames) idx = 0;
      ui.viewer.classList.add("ready"); // PREPARE CLIP moves to the corner
      S.view.cx = 0;
      setZoom(1);
      var msg = "\"" + S.clip.name + "\" — " + info.frames + " frames, " + info.width + "×" + info.height +
        ". Drag from the center of a high-contrast detail to place the box.";
      if (info.width !== S.clip.seqW || info.height !== S.clip.seqH)
        status(msg + "\nRender size differs from the sequence (" + S.clip.seqW + "×" + S.clip.seqH + ").", "warn");
      else status(msg, "ok");
      return showFrame(idx);
    }).catch(function (e) {
      if (e.message === "cancel") return;
      if (/Select a video clip/.test(e.message)) { flashNoClip(); status("Select a clip in the timeline first.", "warn"); }
      else status(e.message, "err");
    }).then(function () {
      S.busy = false; progress(null); refreshButtons(); drawStrip();
    });
  });
  // Nothing selected: the button itself says so for a moment, on grey.
  var flashTimer = null;
  function flashNoClip() {
    var label = ui.prepare.querySelector("span");
    clearTimeout(flashTimer);
    ui.prepare.classList.add("nosel"); label.textContent = "No clip selected";
    flashTimer = setTimeout(function () { ui.prepare.classList.remove("nosel"); label.textContent = "Prepare clip"; }, 1800);
  }

  // ---------- frames ----------
  var frameReq = 0;
  function showFrame(i) {
    if (!S.info) return Promise.resolve();
    i = Math.max(0, Math.min(S.info.frames - 1, i | 0));
    S.frame = i;
    updateFrameLabel(); drawStrip();
    var my = ++frameReq;
    return pyCall("frame", { index: i }).then(function (r) {
      if (my !== frameReq) return;
      return new Promise(function (res) {
        var img = new Image();
        img.onload = function () { if (my === frameReq) { S.img = img; draw(); } res(); };
        img.src = "data:image/jpeg;base64," + r.jpeg;
      });
    }).catch(function (e) { status(e.message, "err"); });
  }

  function updateFrameLabel() {
    if (!S.info) return;
    var txt = (S.frame + 1) + " / " + S.info.frames;
    if (S.track) txt += "  ·  " + Math.round(S.track.points[S.frame][2] * 100) + "%";
    ui.frameLabel.textContent = txt;
  }

  // ---------- frame strip ----------
  function fitCanvas(c) {
    var dpr = window.devicePixelRatio || 1;
    var w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    return { w: w, h: h, dpr: dpr };
  }
  function roundRect(g, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    g.beginPath();
    g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
  }
  function drawStrip() {
    var c = fitCanvas(ui.strip), g = sctx, d = c.dpr;
    g.clearRect(0, 0, c.w, c.h);
    var n = S.info ? S.info.frames : 60;
    var pad = 6 * d, top = 6 * d, bh = c.h - 12 * d, slot = (c.w - 2 * pad) / n;
    var bw = Math.max(1, Math.min(2 * d, slot * 0.3));
    ui.frameLabel.style.left = (pad + 0.5 * slot - bw / 2) / d + "px"; // counter starts where the first bar does
    // Bars glow yellow around the box frame, fading over the neighbouring frames.
    var sigma = Math.max(1.4, 5 * d / slot), YEL = [255, 210, 63];
    for (var i = 0; i < n; i++) {
      var rgb = [255, 255, 255], a = 0.22; // faint white until tracked
      if (S.track) {
        var cf = S.track.points[i][2];
        rgb = cf < 0.6 ? [255, 107, 97] : cf < 0.8 ? [242, 181, 74] : [90, 166, 255];
        a = 0.95;
      }
      if (S.info && S.box) {
        var dd = i - S.boxFrame, wy = Math.exp(-dd * dd / (2 * sigma * sigma));
        rgb = rgb.map(function (v, j) { return Math.round(v + (YEL[j] - v) * wy); });
        a = a + (1 - a) * wy;
      }
      if (S.info && i === S.frame) a = 1;
      var bx = pad + (i + 0.5) * slot - bw / 2;
      g.fillStyle = "rgba(0,0,0,.1)"; // faint 1 px outline
      roundRect(g, bx - d, top - d, bw + 2 * d, bh + 2 * d, bw / 2 + d); g.fill();
      g.fillStyle = "rgba(" + rgb.join(",") + "," + a.toFixed(3) + ")";
      roundRect(g, bx, top, bw, bh, bw / 2); g.fill();
    }
    if (!S.info) return;
    var x = pad + (S.frame + 0.5) * slot; // playhead
    g.fillStyle = "rgba(0,0,0,.25)";
    roundRect(g, x - 2 * d, 2 * d, 4 * d, c.h - 4 * d, 2 * d); g.fill();
    g.fillStyle = "#fff";
    roundRect(g, x - d, 3 * d, 2 * d, c.h - 6 * d, d); g.fill();
  }
  var stripDrag = false;
  function stripFrame(e) {
    var r = ui.strip.getBoundingClientRect(), pad = 6, n = S.info.frames;
    return Math.floor((e.clientX - r.left - pad) / ((r.width - 2 * pad) / n));
  }
  ui.strip.addEventListener("mousedown", function (e) {
    if (!S.info) return;
    stripDrag = true; showFrame(stripFrame(e));
  });
  window.addEventListener("mousemove", function (e) {
    if (stripDrag) { var f = stripFrame(e); if (f !== S.frame) showFrame(f); }
  });
  window.addEventListener("mouseup", function () { stripDrag = false; });

  // ---------- view: zoom & pan ----------
  // Coordinates: "full" = render pixels (tracking space); "prev" = preview image pixels; "cv" = canvas pixels.
  function k() { return S.info ? S.info.previewWidth / S.info.width : 1; }
  function viewScale() {
    var c = fitCanvas(ui.canvas);
    return Math.min(c.w / S.info.previewWidth, c.h / S.info.previewHeight) * S.view.zoom; // canvas px per preview px
  }
  function clampView() {
    var c = fitCanvas(ui.canvas), s = viewScale(), iw = S.info.previewWidth, ih = S.info.previewHeight;
    var hx = c.w / (2 * s), hy = c.h / (2 * s);
    S.view.cx = Math.max(Math.min(hx, iw / 2), Math.min(Math.max(iw - hx, iw / 2), S.view.cx));
    S.view.cy = Math.max(Math.min(hy, ih / 2), Math.min(Math.max(ih - hy, ih / 2), S.view.cy));
  }
  function fullToCv(x, y) {
    var c = fitCanvas(ui.canvas), s = viewScale(), kk = k();
    return { x: (x * kk - S.view.cx) * s + c.w / 2, y: (y * kk - S.view.cy) * s + c.h / 2 };
  }
  function cvToFull(x, y) {
    var c = fitCanvas(ui.canvas), s = viewScale(), kk = k();
    return { x: ((x - c.w / 2) / s + S.view.cx) / kk, y: ((y - c.h / 2) / s + S.view.cy) / kk };
  }
  function eventCv(e) {
    var r = ui.canvas.getBoundingClientRect(), c = fitCanvas(ui.canvas);
    return { x: (e.clientX - r.left) * c.w / r.width, y: (e.clientY - r.top) * c.h / r.height };
  }
  // Zoom keeping the canvas point `at` (default: center) fixed.
  function setZoom(z, at) {
    if (!S.info) return;
    z = Math.max(1, Math.min(16, z));
    var c = fitCanvas(ui.canvas);
    at = at || { x: c.w / 2, y: c.h / 2 };
    var anchor = S.view.cx ? cvToFull(at.x, at.y) : null;
    S.view.zoom = z;
    if (!anchor || z === 1) {
      S.view.cx = S.info.previewWidth / 2; S.view.cy = S.info.previewHeight / 2;
    } else {
      var s = viewScale(), kk = k();
      S.view.cx = anchor.x * kk - (at.x - c.w / 2) / s;
      S.view.cy = anchor.y * kk - (at.y - c.h / 2) / s;
    }
    clampView(); draw();
  }
  ui.canvas.addEventListener("wheel", function (e) {
    if (!S.info) return;
    e.preventDefault();
    setZoom(S.view.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), eventCv(e));
  }, { passive: false });
  window.addEventListener("resize", function () { if (S.info) clampView(); draw(); drawStrip(); });

  // ---------- drawing ----------
  // Feature box and search box on the current frame (they follow the track once tracked).
  function rects() {
    if (!S.box) return null;
    var dx = 0, dy = 0;
    if (S.track) {
      var p = S.track.points[S.frame], r = S.track.points[S.track.ref];
      dx = p[0] - r[0]; dy = p[1] - r[1];
    }
    var b = S.box, m = S.margin;
    return {
      f: { x: b.x + dx, y: b.y + dy, w: b.w, h: b.h },
      s: { x: b.x + dx - m.x, y: b.y + dy - m.y, w: b.w + 2 * m.x, h: b.h + 2 * m.y }
    };
  }
  function rectCv(r) {
    var a = fullToCv(r.x, r.y), b = fullToCv(r.x + r.w, r.y + r.h);
    return { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y };
  }

  function draw() {
    var c = fitCanvas(ui.canvas);
    ctx.clearRect(0, 0, c.w, c.h);
    if (!S.img || !S.info) return;
    var s = viewScale(), lw = c.dpr;
    ctx.imageSmoothingEnabled = S.view.zoom < 3;
    var o = fullToCv(0, 0);
    ctx.drawImage(S.img, o.x, o.y, S.info.previewWidth * s, S.info.previewHeight * s);

    if (S.track) {
      ctx.lineWidth = lw; ctx.strokeStyle = "rgba(47,140,255,.85)";
      ctx.beginPath();
      S.track.points.forEach(function (p, i) {
        var q = fullToCv(p[0], p[1]);
        i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y);
      });
      ctx.stroke();
      S.track.points.forEach(function (p) {
        var q = fullToCv(p[0], p[1]);
        ctx.fillStyle = p[2] < 0.6 ? "#ff6b61" : p[2] < 0.8 ? "#f2b54a" : "rgba(90,166,255,.95)";
        ctx.beginPath(); ctx.arc(q.x, q.y, 1.6 * lw, 0, Math.PI * 2); ctx.fill();
      });
    }

    var R = rects();
    if (!R) return;
    var sr = rectCv(R.s), fr = rectCv(R.f), hs = 3 * lw, cx = fr.x + fr.w / 2, cy = fr.y + fr.h / 2, a = 5 * lw;
    var cross = function () { ctx.beginPath(); ctx.moveTo(cx - a, cy); ctx.lineTo(cx + a, cy); ctx.moveTo(cx, cy - a); ctx.lineTo(cx, cy + a); ctx.stroke(); };
    crispDashRect(sr.x, sr.y, sr.w, sr.h, Math.max(1, Math.round(lw)), "rgba(255,255,255,.85)");
    handles(sr, "rgba(255,255,255,.95)", hs, lw);
    stroke(1.5 * lw, "#ffd23f", [], function () { ctx.strokeRect(fr.x, fr.y, fr.w, fr.h); cross(); });
    handles(fr, "#ffd23f", hs, lw);
  }
  // Чёткий пунктир (как crispDash в Saturni · Debug): штрих 3, промежуток 2 в целых пикселях экрана (×k),
  // линия по серединам пикселей. На прямых штрихи одинаковые и стоят по середине стороны (70 %), остаток
  // уходит в углы — там штрихи поровну (100 %). Все 4 угла одинаковые: если не выходит — рамка на 1 меньше.
  function crispDashRect(x, y, w, h, k, color) {
    var dash = 3, gap = 2, END = 1.5;
    x = Math.round(x / k) + .5; y = Math.round(y / k) + .5; w = Math.round(w / k) - 1; h = Math.round(h / k) - 1;
    if (w < 2 || h < 2) return;
    function side(a, b) {
      var L = b - a - 2 * END, n = L >= dash ? Math.floor((L + gap) / (dash + gap)) : 0;
      if (!n) return { k: 0, start: 0, s: (b - a) / 2, e: (b - a) / 2 };
      var rest = L - (n * dash + (n - 1) * gap), pre = Math.floor(rest / 2);
      return { k: n, start: a + END + pre, s: END + pre, e: END + rest - pre };
    }
    var H = side(x, x + w), V = side(y, y + h), i, p;
    if (H.s !== H.e) { w--; H = side(x, x + w); }
    if (V.s !== V.e) { h--; V = side(y, y + h); }
    ctx.save(); ctx.scale(k, k); ctx.lineWidth = 1; ctx.strokeStyle = color; ctx.lineCap = "butt"; ctx.lineJoin = "miter";
    ctx.globalAlpha = .7; ctx.setLineDash([]); ctx.beginPath();
    for (i = 0, p = H.start; i < H.k; i++, p += dash + gap) { ctx.moveTo(p, y); ctx.lineTo(p + dash, y); ctx.moveTo(p, y + h); ctx.lineTo(p + dash, y + h); }
    for (i = 0, p = V.start; i < V.k; i++, p += dash + gap) { ctx.moveTo(x, p); ctx.lineTo(x, p + dash); ctx.moveTo(x + w, p); ctx.lineTo(x + w, p + dash); }
    ctx.stroke(); ctx.globalAlpha = 1;
    var fH = H.k ? 1 : .5, fV = V.k ? 1 : .5;
    function corner(e1, f1, e2, f2, pts) {
      var R = e1 + e2, q = dash / gap + 1, n = Math.max(1, Math.round((R / gap + 1 - f1 - f2) / q)), g = R / (n * q - 1 + f1 + f2);
      ctx.setLineDash([g * dash / gap, g]); ctx.lineDashOffset = -g * f1;
      ctx.beginPath(); ctx.moveTo(pts[0], pts[1]); ctx.lineTo(pts[2], pts[3]); ctx.lineTo(pts[4], pts[5]); ctx.stroke();
    }
    corner(V.s, fV, H.s, fH, [x, y + V.s, x, y, x + H.s, y]);
    corner(H.e, fH, V.s, fV, [x + w - H.e, y, x + w, y, x + w, y + V.s]);
    corner(V.e, fV, H.e, fH, [x + w, y + h - V.e, x + w, y + h, x + w - H.e, y + h]);
    corner(H.s, fH, V.e, fV, [x + H.s, y + h, x, y + h, x, y + h - V.e]);
    ctx.restore();
  }
  function stroke(width, color, dash, path) {
    ctx.setLineDash(dash); ctx.lineWidth = width; ctx.strokeStyle = color; path(); ctx.setLineDash([]);
  }
  function handles(r, color, hs, o) {
    [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h],
     [r.x + r.w / 2, r.y], [r.x + r.w / 2, r.y + r.h], [r.x, r.y + r.h / 2], [r.x + r.w, r.y + r.h / 2]]
      .forEach(function (p) {
        ctx.fillStyle = "rgba(0,0,0,.5)"; ctx.fillRect(p[0] - hs - o, p[1] - hs - o, 2 * (hs + o), 2 * (hs + o));
        ctx.fillStyle = color; ctx.fillRect(p[0] - hs, p[1] - hs, 2 * hs, 2 * hs);
      });
  }

  // ---------- box editing (always symmetric around the box center) ----------
  function edgesAt(r, p, tol) {
    var inX = p.x >= r.x - tol && p.x <= r.x + r.w + tol, inY = p.y >= r.y - tol && p.y <= r.y + r.h + tol;
    if (!inX || !inY) return null;
    var e = {
      l: Math.abs(p.x - r.x) <= tol, r: Math.abs(p.x - (r.x + r.w)) <= tol,
      t: Math.abs(p.y - r.y) <= tol, b: Math.abs(p.y - (r.y + r.h)) <= tol
    };
    return e.l || e.r || e.t || e.b ? e : null;
  }
  function inside(r, p) { return p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.h; }

  function hitTest(p) {
    var R = rects();
    if (!R) return { mode: "new" };
    var tol = 6 * (window.devicePixelRatio || 1), fr = rectCv(R.f), sr = rectCv(R.s);
    var e = edgesAt(fr, p, tol);
    if (e) return { mode: "feature", edges: e };
    e = edgesAt(sr, p, tol);
    if (e) return { mode: "search", edges: e };
    if (inside(fr, p)) return { mode: "move" };
    return { mode: "pan" };
  }
  function cursorFor(h) {
    if (h.mode === "move") return "move";
    if (h.mode === "new") return "crosshair";
    if (h.mode === "pan") return "grab";
    var e = h.edges;
    if ((e.l && e.t) || (e.r && e.b)) return "nwse-resize";
    if ((e.r && e.t) || (e.l && e.b)) return "nesw-resize";
    return e.l || e.r ? "ew-resize" : "ns-resize";
  }

  // Editing after tracking: keep the box where it is on the current frame and drop the track.
  function bakeBox() {
    if (!S.track) return;
    S.box = rects().f; S.boxFrame = S.frame; S.track = null;
    updateFrameLabel(); drawStrip();
  }

  var drag = null, MIN = 6;
  ui.canvas.addEventListener("mousedown", function (e) {
    if (!S.info) return;
    var p = eventCv(e);
    var h = e.button === 1 ? { mode: "pan" } : hitTest(p);
    if (e.button !== 0 && e.button !== 1) return;
    e.preventDefault();
    if (h.mode === "pan") {
      drag = { mode: "pan", start: p, cx: S.view.cx, cy: S.view.cy };
      ui.canvas.style.cursor = "grabbing";
      return;
    }
    if (S.busy) return;
    bakeBox();
    var f = cvToFull(p.x, p.y);
    drag = { mode: h.mode, edges: h.edges, start: f };
    if (h.mode === "move") drag.box = Object.assign({}, S.box);
    if (h.mode === "new") S.boxFrame = S.frame;
  });
  ui.canvas.addEventListener("dblclick", function (e) {
    if (!S.info || S.busy || !S.box) return;
    var p = eventCv(e);
    if (hitTest(p).mode !== "pan") return;
    bakeBox();
    var f = cvToFull(p.x, p.y);
    S.box = { x: f.x - S.box.w / 2, y: f.y - S.box.h / 2, w: S.box.w, h: S.box.h };
    S.boxFrame = S.frame;
    draw(); drawStrip(); refreshButtons();
  });
  window.addEventListener("mousemove", function (e) {
    if (stripDrag) return;
    var p = eventCv(e);
    if (!drag) {
      if (S.info && e.target === ui.canvas) ui.canvas.style.cursor = cursorFor(hitTest(p));
      return;
    }
    if (drag.mode === "pan") {
      var s = viewScale();
      S.view.cx = drag.cx - (p.x - drag.start.x) / s;
      S.view.cy = drag.cy - (p.y - drag.start.y) / s;
      clampView(); draw();
      return;
    }
    var f = cvToFull(p.x, p.y), b = S.box, cx, cy;
    if (drag.mode === "new") {
      var w = 2 * Math.abs(f.x - drag.start.x), h = 2 * Math.abs(f.y - drag.start.y);
      S.box = { x: drag.start.x - w / 2, y: drag.start.y - h / 2, w: w, h: h };
      S.margin = { x: Math.max(w, MIN) * 0.75, y: Math.max(h, MIN) * 0.75 };
    } else if (drag.mode === "move") {
      S.box = { x: drag.box.x + f.x - drag.start.x, y: drag.box.y + f.y - drag.start.y, w: drag.box.w, h: drag.box.h };
    } else if (drag.mode === "feature") {
      cx = b.x + b.w / 2; cy = b.y + b.h / 2;
      var nw = drag.edges.l || drag.edges.r ? Math.max(MIN, 2 * Math.abs(f.x - cx)) : b.w;
      var nh = drag.edges.t || drag.edges.b ? Math.max(MIN, 2 * Math.abs(f.y - cy)) : b.h;
      S.box = { x: cx - nw / 2, y: cy - nh / 2, w: nw, h: nh };
    } else if (drag.mode === "search") {
      cx = b.x + b.w / 2; cy = b.y + b.h / 2;
      if (drag.edges.l || drag.edges.r) S.margin.x = Math.max(2, Math.abs(f.x - cx) - b.w / 2);
      if (drag.edges.t || drag.edges.b) S.margin.y = Math.max(2, Math.abs(f.y - cy) - b.h / 2);
    }
    draw();
  });
  window.addEventListener("mouseup", function (e) {
    if (!drag) return;
    var wasNew = drag.mode === "new";
    drag = null;
    if (wasNew && S.box && (S.box.w < MIN || S.box.h < MIN)) {
      // a plain click places a default-size box around the clicked point
      var c = { x: S.box.x + S.box.w / 2, y: S.box.y + S.box.h / 2 }, d = Math.max(24, S.info.width / 40);
      S.box = { x: c.x - d / 2, y: c.y - d / 2, w: d, h: d };
      S.margin = { x: d * 0.75, y: d * 0.75 };
    }
    if (S.info && e.target === ui.canvas) ui.canvas.style.cursor = cursorFor(hitTest(eventCv(e)));
    draw(); drawStrip(); refreshButtons();
  });
  ui.clearBox.addEventListener("click", function () {
    S.box = null; S.margin = null; S.track = null;
    updateFrameLabel(); draw(); drawStrip(); refreshButtons();
  });

  document.addEventListener("keydown", function (e) {
    if (!S.info || S.busy || e.target.tagName === "INPUT") return;
    var step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") { showFrame(S.frame - step); e.preventDefault(); }
    if (e.key === "ArrowRight") { showFrame(S.frame + step); e.preventDefault(); }
  });

  // ---------- tracking ----------
  function trackKey() {
    var b = S.box, m = S.margin;
    return [S.boxFrame, b.x, b.y, b.w, b.h, m.x, m.y, S.adapt].map(function (v) { return typeof v === "number" ? v.toFixed(2) : v; }).join("|");
  }
  function ensureTrack() {
    var key = trackKey();
    if (S.track && S.track.key === key) return Promise.resolve(S.track);
    status("Tracking…"); progress(0);
    var b = S.box, m = S.margin;
    return pyCall("track", {
      ref: S.boxFrame, x: b.x, y: b.y, w: b.w, h: b.h,
      margins: [m.x, m.y, m.x, m.y], adapt: S.adapt, minConf: 0.8
    }, function (d, t) { progress(d / t); drawStrip(); }).then(function (r) {
      r.key = key;
      S.track = r;
      updateFrameLabel(); draw(); drawStrip();
      return r;
    });
  }

  // Gaussian smoothing of x, y, scale and angle (confidence untouched).
  function smoothPoints(points, sigma) {
    var rad = Math.ceil(sigma * 2.5), w = [];
    for (var j = -rad; j <= rad; j++) w.push(Math.exp(-j * j / (2 * sigma * sigma)));
    return points.map(function (p, i) {
      var acc = [0, 0, 0, 0], ws = 0;
      for (var j = -rad; j <= rad; j++) {
        var q = points[i + j]; if (!q) continue;
        var wj = w[j + rad]; ws += wj;
        acc[0] += q[0] * wj; acc[1] += q[1] * wj; acc[2] += q[3] * wj; acc[3] += q[4] * wj;
      }
      return [acc[0] / ws, acc[1] / ws, p[2], acc[2] / ws, acc[3] / ws];
    });
  }

  function apply(mode) {
    var pr = props();
    if (!pr) { status("Choose at least one of Position, Scale, Rotation.", "warn"); return; }
    S.busy = true; refreshButtons();
    ensureTrack().then(function (tr) {
      status("Writing keyframes…"); progress(null);
      var pts = ui.smooth.classList.contains("on") ? smoothPoints(tr.points, 1.6) : tr.points;
      if (!CEP) {                                      // APP: render a new file next to the video
        status(mode === "attach" ? "Choose a picture to attach…" : "Rendering…"); progress(0);
        var rid = "r" + appNext++;
        appPending[rid] = function (d, t) { progress(t ? d / t : 0); status("Rendering… " + d + " / " + t); };
        return Promise.resolve(appApi().render(rid, mode, pr, pts, tr.ref, window.ptKeepSound())).then(function (r) {
          delete appPending[rid];
          if (!r) { status("Cancelled."); return; }
          if (!r.ok) throw new Error(r.error);
          status("Saved: " + r.name, "ok");
        });
      }
      // Rendered frames match the sequence frame size, so track pixels are sequence pixels.
      var kx = S.clip.seqW / S.info.width, ky = S.clip.seqH / S.info.height;
      var data = S.clip.start + "|" + S.clip.fps + "|" + pts.map(function (p) {
        return (p[0] * kx).toFixed(3) + "," + (p[1] * ky).toFixed(3) + "," + p[3].toFixed(5) + "," + p[4].toFixed(4);
      }).join(";");
      var low = tr.points.filter(function (p) { return p[2] < 0.6; }).length;
      return host("pt_apply", [data, mode, pr, tr.ref, ui.reduce.classList.contains("on")]).then(function (rep) {
        status(rep.join("\n") + (low ? "\n" + low + " unreliable frames (red) — consider a different detail or a larger search area." : ""),
          low ? "warn" : "ok");
      });
    }).catch(function (e) { status(e.message, "err"); })
      .then(function () { S.busy = false; progress(null); refreshButtons(); });
  }
  ui.attach.addEventListener("click", function () { apply("attach"); });
  ui.stabilize.addEventListener("click", function () { apply("stabilize"); });

  // ---------- APP: words and settings of the standalone window ----------
  if (!CEP) {
    var label = function (b, text, tip) { b.querySelector("span").textContent = text; b.setAttribute("data-tip", tip); };
    label(ui.prepare, "Open video", "Open a video file and load its frames.");
    label(ui.attach, "Render motion", "Render the video with a picture (PNG) that follows the tracked point.");
    label(ui.stabilize, "Render stabilized", "Render the video stabilized around the tracked point.");
    [ui.hideOthers, ui.ignoreKeys, ui.reduce, ui.python.parentNode].forEach(function (el) { el.style.display = "none"; });
    var keepSound = document.createElement("button");
    keepSound.className = "gt"; keepSound.id = "keepSound"; keepSound.textContent = "Keep the sound";
    keepSound.setAttribute("data-tip", "Copy the video's sound into the rendered file.");
    keepSound.classList.toggle("on", loadSetting("keepSound", true));
    keepSound.addEventListener("click", function () { saveSetting("keepSound", keepSound.classList.toggle("on")); });
    ui.settings.appendChild(keepSound);
    window.ptKeepSound = function () { return keepSound.classList.contains("on"); };
    status("Open a video, then drag from a high-contrast detail to place the box.");
  }

  // ---------- Saturni · Debug: Ctrl+click (or right-click) the gear ----------
  if (!CEP) {
    var dcss = document.createElement("link"); dcss.rel = "stylesheet"; dcss.href = "/mod/debug/debug.css"; document.head.appendChild(dcss);
    var djs = document.createElement("script"); djs.src = "/mod/debug/debug.js";
    djs.onload = function () {
      window.__emit = function (evs) { evs.forEach(function (e) { SaturniDebug.handle(e.type, e.data); }); };
      var go = function () {
        SaturniDebug.init({ api: function (n) { var a = [].slice.call(arguments, 1); return appApi()[n].apply(null, a); },
          app: "Saturni · Motion Tracker", context: function () { return S.clip ? S.clip.name : ""; }, gear: "#btnSettings" });
      };
      appApi() ? go() : window.addEventListener("pywebviewready", go);
    };
    document.head.appendChild(djs);
  } else {
    var DEBUG_DIR = path.join(APP_DIR, "⿻", "@debug"), OVERLAY = path.join(path.dirname(path.dirname(path.dirname(APP_DIR))), "@ Saturni · Debug", "overlay.py");
    var openDebug = function () {
      var py = (ui.python.value || "python").replace(/python(\.exe)?$/i, "pythonw$1");
      spawn(py, [OVERLAY, "--dir", DEBUG_DIR, "--app", "Saturni · Motion Tracker"], { detached: true, windowsHide: true }).unref();
    };
    var gear = ui.settingsBtn;
    gear.addEventListener("click", function (e) { if (e.ctrlKey) { e.stopImmediatePropagation(); e.preventDefault(); openDebug(); } }, true);
    gear.addEventListener("contextmenu", function (e) { e.preventDefault(); openDebug(); });
    gear.style.position = "relative";
    var badge = document.createElement("span");
    badge.style.cssText = "position:absolute;top:-5px;right:-6px;width:12px;height:12px;border-radius:50%;background:#16161c;color:#ffd166;" +
      "font:700 8px/12px Inter,'Segoe UI',sans-serif;text-align:center;pointer-events:none;display:none";
    gear.appendChild(badge);
    var countNotes = function () {
      var n = 0;
      try { var cur = fs.readFileSync(path.join(DEBUG_DIR, "current.txt"), "utf8").trim();                 // текущая сессия правок
        n = (JSON.parse(fs.readFileSync(path.join(DEBUG_DIR, cur, "debug.json"), "utf8")).notes || []).length; } catch (e) {}
      badge.textContent = n > 99 ? "99" : n; badge.style.display = n ? "block" : "none";
    };
    countNotes(); setInterval(countNotes, 2000);
  }

  refreshButtons();
  draw(); drawStrip();
})();
