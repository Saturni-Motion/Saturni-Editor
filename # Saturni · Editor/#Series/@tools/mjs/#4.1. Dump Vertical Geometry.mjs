// Выгрузка геометрии вертикалок для проверки кадрирования (@tools/#4.1. Check Verticals.py).
// Только чтение (ExtendScript), ничего в проекте не меняет. Запускать, когда никакой другой
// скрипт не гоняет Premiere.
//
//   node "#4.1. Dump Vertical Geometry.mjs" <out.json> [фильтр имени]
//
// Для каждой секвенции "<имя> ` 1v" из "~/<папка>/v" (или "~/v") пишет клипы V1/V2 вертикалки
// (start/end таймлайна, Scale, Position X норм., Crop Top/Bottom, путь исходника) и клипы
// одноимённой горизонтали из той же папки (Scale, Position X) — из них #4.1. Check Verticals.py
// восстанавливает окно кропа в координатах горизонтального рендера.
import { writeFileSync } from "node:fs";
import { callClassic } from "./@Premiere Lib.mjs";

const outPath = process.argv[2];
const filter = process.argv[3] || "";
if (!outPath) { console.error("usage: node #4.1. Dump Vertical Geometry.mjs <out.json> [filter]"); process.exit(2); }

const data = await callClassic(`
  var P = app.project, out = [], BS = String.fromCharCode(92);
  function motion(clip) {
    var r = { scale: null, posX: null, cropT: 0, cropB: 0 };
    for (var k = 0; k < clip.components.numItems; k++) {
      var c = clip.components[k]; if (c.matchName !== "AE.ADBE Motion") continue;
      for (var j = 0; j < c.properties.numItems; j++) {
        var pr = c.properties[j], n = pr.displayName, v = null;
        try { v = pr.getValue(); } catch (e) { continue; }
        if (n === "Scale" || (n === "Scale Height" && r.scale === null)) r.scale = Number(v);
        else if (n === "Position") r.posX = Number(v[0]);
        else if (n === "Crop Top") r.cropT = Number(v);
        else if (n === "Crop Bottom") r.cropB = Number(v);
      }
    }
    return r;
  }
  function clips(seq, maxTracks) {
    var a = [];
    for (var t = 0; t < Math.min(seq.videoTracks.numTracks, maxTracks); t++) {
      var tr = seq.videoTracks[t];
      for (var c = 0; c < tr.clips.numItems; c++) {
        var cl = tr.clips[c], m = motion(cl), media = "";
        try { media = cl.projectItem.getMediaPath(); } catch (e) {}
        a.push({ track: t + 1, start: cl.start.seconds, end: cl.end.seconds, inPoint: cl.inPoint.seconds,
                 scale: m.scale, posX: m.posX, cropT: m.cropT, cropB: m.cropB, media: media, name: cl.name, nodeId: cl.nodeId });
      }
    }
    return a;
  }
  var byPath = {};
  for (var s = 0; s < P.sequences.numSequences; s++) {
    var q = P.sequences[s], p = "";
    try { p = q.projectItem.treePath; } catch (e) { continue; }
    byPath[p] = q;
  }
  for (var p in byPath) {
    var q = byPath[p];
    if (q.name.indexOf(" \` 1v") < 0) continue;
    if (p.indexOf(BS + "~" + BS) < 0 || p.indexOf(BS + "v" + BS) < 0) continue;
    if (${JSON.stringify(filter)} && q.name.indexOf(${JSON.stringify(filter)}) < 0) continue;
    var hName = q.name.replace(" \` 1v", "");
    var hPath = p.replace(BS + "v" + BS + q.name, BS + hName);
    var h = byPath[hPath] || null;
    out.push({ name: q.name, path: p, horizontalPath: hPath,
               w: q.frameSizeHorizontal, hgt: q.frameSizeVertical,
               vertical: clips(q, 3), horizontal: h ? clips(h, 1) : null });
  }
  return __result(out);
`);
writeFileSync(outPath, JSON.stringify(data, null, 1), "utf-8");
console.log(`${data.length} вертикалок -> ${outPath}`);
process.exit(0);
