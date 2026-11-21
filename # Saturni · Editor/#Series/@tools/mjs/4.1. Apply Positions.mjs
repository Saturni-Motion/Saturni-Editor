// Применить Position X из 4.1. Reposition Verticals.py к клипам вертикалок (по nodeId).
//   node "4.1. Apply Positions.mjs" pos.json
// set_clip_properties_batch ищет клипы только в АКТИВНОЙ секвенции — поэтому по очереди
// открываем каждую вертикалку (по пути "~/<папка>/v/<имя>", не по имени — имена повторяются).
import { readFileSync } from "node:fs";
import { callClassic, callClassicTool, competitorGapTools } from "./@Premiere Lib.mjs";

const all = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const groups = new Map();
for (const i of all) {
  const k = `${i.folder}|${i.seq}`;
  if (!groups.has(k)) groups.set(k, []);
  groups.get(k).push({ node_id: i.node_id, position_x: i.position_x, position_y: i.position_y });
}
for (const [k, items] of groups) {
  const [folder, seq] = k.split("|");
  const ok = await callClassic(`
    var BS = String.fromCharCode(92), want = BS + "~" + BS + (${JSON.stringify(folder)} ? ${JSON.stringify(folder)} + BS : "") + "v" + BS + ${JSON.stringify(seq)};
    for (var s = 0; s < app.project.sequences.numSequences; s++) { var q = app.project.sequences[s], p = "";
      try { p = q.projectItem.treePath; } catch (e) { continue; }
      if (p.length >= want.length && p.substring(p.length - want.length) === want) {
        app.project.openSequence(q.sequenceID);
        return __result(app.project.activeSequence.sequenceID === q.sequenceID);
      } }
    return __result(false);
  `);
  if (!ok) { console.log(`!! не открылась ${folder}/${seq}`); continue; }
  for (let i = 0; i < items.length; i += 16) {
    await callClassicTool(competitorGapTools.set_clip_properties_batch, { items: items.slice(i, i + 16) });
  }
  console.log(`${folder}/${seq}: Position X на ${items.length} клипов`);
}
process.exit(0);
