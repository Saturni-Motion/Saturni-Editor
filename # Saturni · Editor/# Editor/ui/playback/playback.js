// Playback: every piece has its own player; Web Audio mixes (piece -> track -> master).

// ---------- playback: every piece has its own player; Web Audio mixes (piece -> track -> master)
let actx = null, an = null, mbuf = new Float32Array(2048), inBus, master = null, nEnv, laneIn = [], clock0 = 0, perf0 = 0, shownEl = null;
const voices = new Map(), proxied = new Set();
function mediaUrl(i) { return `/src/${i}/${proxied.has(i) ? "proxy" : "media"}`; }
function fxChain() {                             // EQ -> gain -> compressor -> makeup -> limiter, like the saved file
  const hp = actx.createBiquadFilter(), lp = actx.createBiquadFilter(), ls = actx.createBiquadFilter(), hs = actx.createBiquadFilter();
  ls.type = "lowshelf"; ls.frequency.value = 100; hs.type = "highshelf"; hs.frequency.value = 3000;
  const g = actx.createGain(), comp = actx.createDynamicsCompressor(), mk = actx.createGain(), lim = actx.createDynamicsCompressor();
  const ch = [hp, lp, ls, hs, g, comp, mk, lim]; for (let i = 0; i < ch.length - 1; i++) ch[i].connect(ch[i + 1]);
  const set = a => {
    a = a || AUD0;
    hp.type = a.hp > 0 ? "highpass" : "allpass"; hp.frequency.value = a.hp > 0 ? a.hp : 20; hp.Q.value = Math.SQRT1_2;
    lp.type = a.lp > 0 ? "lowpass" : "allpass"; lp.frequency.value = a.lp > 0 ? a.lp : 20000; lp.Q.value = Math.SQRT1_2;
    ls.gain.value = a.bass; hs.gain.value = a.treble; g.gain.value = Math.pow(10, a.gain / 20);
    comp.threshold.value = a.comp ? a.cth : 0; comp.ratio.value = a.comp ? a.crat : 1; comp.knee.value = 2.8;
    comp.attack.value = a.catk / 1000; comp.release.value = a.crel / 1000; mk.gain.value = a.comp ? Math.pow(10, a.cmk / 20) : 1;
    lim.threshold.value = a.lim ? a.lceil : 0; lim.ratio.value = a.lim ? 20 : 1; lim.knee.value = 0; lim.attack.value = .001; lim.release.value = a.lrel / 1000;
  };
  set(null); return { inp: hp, out: lim, set };
}
function laneNode(k) {
  while (laneIn.length <= k) { const f = fxChain(); f.out.connect(inBus); laneIn.push(f); }
  return laneIn[k];
}
function videoVoice(key, i) {
  if (voices.has(key)) return voices.get(key);
  if (SRC[i].still) {                            // a picture: a player that has nothing to play
    const img = new Image(); img.draggable = false; Object.assign(img, { paused: true, pause() {}, play: async () => {}, load() {} });
    img.onload = () => glDirty = true; img.src = `/src/${i}/media`; $("view").appendChild(img); placeEl(img);
    const v = { el: img, kind: "v", src: i }; voices.set(key, v); return v;
  }
  const el = document.createElement("video"); el.muted = true; el.preload = "auto"; el.playsInline = true; el.src = mediaUrl(i);
  $("view").appendChild(el); placeEl(el);
  const fix = async () => {
    if (proxied.has(i) || el.dataset.p) return; el.dataset.p = 1; $("vmsg").style.display = "flex";
    const r = await py("proxy", i);
    if (!r.ok) { $("vmsg").textContent = "No preview for this video"; return; }
    $("vmsg").style.display = "none"; proxied.add(i);
    for (const v of voices.values()) if (v.kind === "v" && v.src === i) v.el.src = mediaUrl(i);
  };
  el.addEventListener("error", fix); el.addEventListener("loadedmetadata", () => { if (!el.videoWidth) fix(); });
  const v = { el, kind: "v", src: i }; voices.set(key, v); return v;
}
function audioVoice(key, c) {
  if (voices.has(key)) return voices.get(key);
  const el = new Audio(`/src/${c.src}/a/${c.stream}`); el.preload = "auto";
  const v = { el, kind: "a", src: c.src, cid: c.id }; voices.set(key, v); connectVoice(v); return v;
}
function connectVoice(v) {
  if (!actx || v.node || v.kind !== "a") return;
  const s = actx.createMediaElementSource(v.el); v.node = actx.createGain(); v.fx = fxChain();
  s.connect(v.node); v.node.connect(v.fx.inp);
  const c = st.R.clips.find(q => q.id === v.cid); v.fx.set(c && c.fx); v.fx.out.connect(laneNode(c ? c.lane : 0).inp); v.lane = c ? c.lane : 0;
}
function dropVoices() {                          // players of pieces that are gone
  const ids = new Set(st.R.clips.map(c => c.id));
  for (const [k, v] of voices) {
    const id = +k.slice(1); if (ids.has(id)) continue;
    v.el.pause(); v.el.removeAttribute("src"); v.el.load(); if (v.el.parentNode) v.el.remove();
    if (v.fx) try { v.fx.out.disconnect(); } catch (_) {}
    voices.delete(k);
  }
  if (actx) for (const v of voices.values()) {    // a piece moved to another track: re-route it
    if (v.kind !== "a" || !v.fx) continue; const c = st.R.clips.find(q => q.id === v.cid);
    if (c && c.lane !== v.lane) { try { v.fx.out.disconnect(); } catch (_) {} v.fx.out.connect(laneNode(c.lane).inp); v.lane = c.lane; }
  }
}
function initAudio() {
  if (actx) return;
  actx = new AudioContext();
  inBus = actx.createGain(); nEnv = actx.createGain(); master = fxChain();
  inBus.connect(nEnv); nEnv.connect(master.inp); master.out.connect(actx.destination);
  const sp = actx.createChannelSplitter(2); master.out.connect(sp);
  an = [0, 1].map(i => { const a = actx.createAnalyser(); a.fftSize = 2048; sp.connect(a, i); return a; });
  for (const v of voices.values()) connectVoice(v);
  applyAud();
}
function applyAud() {
  if (!actx) return;
  master.set(st.G.aud);
  st.R.lanes.forEach((l, k) => laneNode(k).set(l.fx));
  for (const v of voices.values()) if (v.kind === "a" && v.fx) { const c = st.R.clips.find(q => q.id === v.cid); v.fx.set(c && c.fx); }
}
function wanted(T) {                             // which players should run, and where in their own file
  const out = [], top = topVideoAt(T);
  if (top) out.push({ key: "v" + top.id, kind: "v", c: top, t: top.in + T - top.start });
  if (playing) for (const c of st.R.clips) if (c.lane >= 0 && T >= c.start && T < clipEnd(c)) out.push({ key: "c" + c.id, kind: "a", c, t: c.in + T - c.start });
  return out;
}
function sync(T) {
  const keys = new Set(); let shown = null;
  for (const w of wanted(T)) {
    const v = w.kind === "v" ? videoVoice(w.key, w.c.src) : audioVoice(w.key, w.c); keys.add(w.key);
    if (w.kind === "v") shown = v;
    if (playing) {
      if (v.el.paused) { if (Math.abs(v.el.currentTime - w.t) > .03) v.el.currentTime = w.t; v.el.play().catch(() => {}); }
      else {                                     // small drifts: nudge the speed; big ones: jump
        const d = w.t - v.el.currentTime;
        if (Math.abs(d) > .4) { v.el.currentTime = w.t; v.el.playbackRate = 1; }
        else v.el.playbackRate = Math.abs(d) > .03 ? clamp(1 + d * 2, .8, 1.2) : 1;
      }
    } else if (w.kind === "v") {
      if (!v.el.paused) v.el.pause();
      if (Math.abs(v.el.currentTime - w.t) > .5 / fpsOr30() && !v.el.seeking) v.el.currentTime = w.t;
    }
  }
  for (const [k, v] of voices) {
    if (!keys.has(k) && !v.el.paused) v.el.pause();
    if (v.kind === "v") v.el.style.visibility = v === shown ? "visible" : "hidden";
  }
  shownEl = shown ? shown.el : null;
}
function seek(t) { ph = t; if (playing) { clock0 = t; perf0 = performance.now(); } phDirty = true; }
function firstIn() { const s = segs(); return s.length ? s[0][0] : st.S.inT; }
function play() {
  if (kind === "photo") return;
  if (playing) return stop();
  const S = st.S; if (!segs().length) return;
  if (ph < S.inT || ph >= S.outT - 1e-3 || inCut(ph)) ph = inCut(ph) && ph < S.outT ? inCut(ph)[1] : firstIn();
  if (NA()) { initAudio(); if (actx.state === "suspended") actx.resume(); }
  clock0 = ph; perf0 = performance.now(); playing = true; setPlayIcon();
}
function stop() { playing = false; for (const v of voices.values()) { if (!v.el.paused) v.el.pause(); v.el.playbackRate = 1; } setPlayIcon(); dirty = true; }
function setPlayIcon() { $("play").innerHTML = icon(playing ? "pause" : "play"); }
function tick() {
  if (!playing) return;
  let T = clock0 + (performance.now() - perf0) / 1000;
  const S = st.S, c = inCut(T);
  if (c) { T = c[1]; clock0 = T; perf0 = performance.now(); }
  if (T >= S.outT) { if (loop) { T = firstIn(); clock0 = T; perf0 = performance.now(); } else { stop(); T = S.outT; } }
  ph = T; phDirty = true;
}
function applyLook() {                           // volumes and fades on the sound, fades on the picture
  if (actx) {
    const now = actx.currentTime;
    nEnv.gain.setTargetAtTime(globalG(ph), now, .004);
    for (const v of voices.values()) if (v.kind === "a" && v.node) { const c = st.R.clips.find(q => q.id === v.cid); if (c) v.node.gain.setTargetAtTime(clipG(c, clamp(ph, c.start, clipEnd(c) - 1e-6)), now, .004); }
  }
  if (hasV()) $("black").style.opacity = 1 - picG(ph);
}
