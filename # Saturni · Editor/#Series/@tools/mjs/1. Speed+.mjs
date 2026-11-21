import { callClassic } from "./@Premiere Lib.mjs";
const stems = process.argv.slice(2);
const body = `
var S = 1.5, out = [];
function findSeq(n){ for (var i=0;i<app.project.sequences.numSequences;i++){ var s=app.project.sequences[i]; if (s.name==n) return s;} return null; }
function findItem(root,n){ for (var i=0;i<root.children.numItems;i++){ var c=root.children[i]; if (c.name==n) return c; if (c.type==2){ var r=findItem(c,n); if(r) return r;} } return null; }
var bin = findItem(app.project.rootItem,"@");
var stems = ${JSON.stringify(stems)};
for (var k=0;k<stems.length;k++){
  var st = stems[k], orig = findSeq(st), tmpl = findSeq("e"), item = findItem(bin, st+".mp4");
  if (findSeq(st+"+")) { out.push(st+": exists"); continue; }
  var before = app.project.sequences.numSequences; tmpl.clone();
  var ns = app.project.sequences[app.project.sequences.numSequences-1];
  for (var i=0;i<app.project.sequences.numSequences;i++){ var s=app.project.sequences[i]; if (s.name=="e Copy"){ ns=s; } }
  ns.name = st+"+"; ns.projectItem.name = st+"+"; ns.projectItem.moveBin(bin);
  app.project.activeSequence = ns;
  ns.videoTracks[0].overwriteClip(item, 0);
  qe.project.init(); var q = qe.project.getActiveSequence();
  var qv = q.getVideoTrackAt(0).getItemAt(0), qa = q.getAudioTrackAt(0).getItemAt(0);
  qv.setSpeed(S, "", false, false, false); qa.setSpeed(S, "", false, false, false);
  var mediaDur = item.getOutPoint().seconds - item.getInPoint().seconds;
  var newEnd = mediaDur / S;
  var vc = ns.videoTracks[0].clips[0], ac = ns.audioTracks[0].clips[0];
  var info = "end before trim " + vc.end.seconds;
  if (vc.end.seconds > newEnd + 0.05) { var t = new Time(); t.seconds = newEnd; vc.end = t; ac.end = t; }
  var m = orig.markers, mk = m.getFirstMarker(), n = 0;
  while (mk) {
    var a = mk.start.seconds / S, b = mk.end.seconds / S;
    var nm = ns.markers.createMarker(a); nm.end = b;
    nm.name = mk.name; nm.setColorByIndex(mk.getColorByIndex()); n++;
    mk = m.getNextMarker(mk);
  }
  out.push(st+"+: "+info+", end now "+ns.videoTracks[0].clips[0].end.seconds.toFixed(2)+" (target "+newEnd.toFixed(2)+"), speed "+ns.videoTracks[0].clips[0].getSpeed()+", markers "+n);
}
app.project.save();
return __result(out);
`;
console.log(await callClassic(body));
process.exit(0);
