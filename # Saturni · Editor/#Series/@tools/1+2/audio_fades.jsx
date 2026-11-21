// Аудиопереход на каждой склейке звука + в начале и в конце дорожки: Constant Power, 2 кадра, по центру склейки.
// Так делает Saturni в готовых роликах. Вставляется в JSX скриптов 1+2 (7. Layout, 13. Edit Cuts, 14. Audio Fades).
// fades(seq, [номера аудиодорожек], кадров) → {added, total} по дорожкам. Уже стоящие переходы не дублируются.
function __fadeName(){return "Constant Power"}
function fades(seq, tracks, frames){
  app.enableQE();
  var out = [];
  var qs = null;
  var prev = app.project.activeSequence;
  app.project.activeSequence = seq;
  qs = qe.project.getActiveSequence();
  var tr = qe.project.getAudioTransitionByName(__fadeName());
  if (!tr) { var L = qe.project.getAudioTransitionList(); for (var i = 0; i < L.numItems; i++) if (L[i].name == __fadeName()) tr = L[i]; }
  if (!tr) return {err: "нет перехода " + __fadeName()};
  for (var t = 0; t < tracks.length; t++) {
    var ti = tracks[t];
    var dom = seq.audioTracks[ti];
    if (!dom || dom.clips.numItems == 0) { out.push({track: ti, added: 0, total: 0}); continue; }
    var have = {};
    for (var k = 0; k < dom.transitions.numItems; k++) { var x = dom.transitions[k]; have[Math.round((x.start.seconds + x.end.seconds) * 500)] = 1; }
    var q = qs.getAudioTrackAt(ti), items = [];
    for (var k = 0; k < q.numItems; k++) { var it = q.getItemAt(k); if (it && it.type != "Empty") items.push(it); }
    var before = dom.transitions.numItems, clips = dom.clips;
    for (var k = 0; k < items.length && k < clips.numItems; k++) {
      var c = clips[k];
      var mid0 = Math.round(c.start.seconds * 1000), mid1 = Math.round(c.end.seconds * 1000);
      var nearStart = false, nearEnd = false;
      for (var key in have) { var m = +key; if (Math.abs(m - mid0) < 60) nearStart = true; if (Math.abs(m - mid1) < 60) nearEnd = true; }
      var gapBefore = k == 0 || Math.abs(clips[k - 1].end.seconds - c.start.seconds) > 0.01;
      if (gapBefore && !nearStart) { try { items[k].addTransition(tr, true, String(frames), "0", 0.5, false, true); } catch (e) {} }
      if (!nearEnd) { try { items[k].addTransition(tr, false, String(frames), "0", 0.5, false, true); } catch (e) {} }
    }
    out.push({track: ti, added: dom.transitions.numItems - before, total: dom.transitions.numItems, clips: clips.numItems});
  }
  if (prev) app.project.activeSequence = prev;
  return out;
}
