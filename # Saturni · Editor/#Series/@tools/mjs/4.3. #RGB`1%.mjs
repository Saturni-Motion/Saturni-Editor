#!/usr/bin/env node
// 4.3. #RGB`1% — RGB Split (Horizontal Split = 1, остальное по умолчанию) на клипы ФОНА
// вертикалок (V1 = "BG-Blur" после 4.2. Background Blur.mjs). Saturni, 2026-10-01: RGB вынесен
// из 4.2 в отдельный этап — с ним рендер в разы дольше, и не всем роликам он нужен.
// Порядок этапов: 4.0. Looping → 4.1. Smart Verticals → 4.2. Background Blur → 4.3. #RGB`1% →
// 4.4. #Sharp`50-5.
//
// Только вертикальные секвенции и только V1 = "BG-Blur" (без блюра — секвенция требует
// внимания: сначала 4.2). batch_apply_effect НЕ идемпотентен (второй вызов добавит второй
// инстанс) — поэтому RGB ставится только клипам, где его ещё нет. В конце — проверка: на каждом
// клипе фона ровно один RGB Split, на основных дорожках RGB нет. Не сошлось — повтор с чистой
// копии из бэкапа (см. runPipeline в @Premiere Lib.mjs).
//
// Обычный запуск — лаунчер "4.3. #RGB`1%.py" в корне проекта. Отладка:
//   node "@tools/mjs/4.3. #RGB`1%.mjs"                 -> все секвенции в бине "~"
//   node "@tools/mjs/4.3. #RGB`1%.mjs" "Имя 1" "Имя 2"  -> только перечисленные

import {
  inspectionTools, selectionTools, advancedTools, clipboardTools,
  callClassicTool, callClassic, runPipeline, runCli, stage, checkResultsForFailures,
  setParamsBatch, verifyError,
} from "./@Premiere Lib.mjs";

const BIN_NAME = "~";
const BG_TRACK_NAME = "BG-Blur";
const EFFECT_NAME = "RGB Split";
const MATCH_NAME = "AE.Impact_RGB_Split_FX";
const HORIZONTAL_SPLIT = 1;

async function applyRgbToActiveSequence(name) {
  stage(name, "Scanning");
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  if (!(info.height > info.width)) return { skipped: true, reason: "not_vertical" };
  const bg = info.videoTracks[0];
  if (!bg || bg.name !== BG_TRACK_NAME) {
    return { skipped: true, lose: true, reason: "no_bg_blur",
      loseMessage: `V1 не "${BG_TRACK_NAME}" — сначала 4.2. Background Blur` };
  }
  const todo = bg.clips.filter((c) => !c.effects.includes(EFFECT_NAME));
  const done = bg.clips.length - todo.length;

  stage(name, "Splitting");
  if (todo.length) {
    await callClassicTool(selectionTools.deselect_all_clips, {});
    if (done === 0) {
      await callClassicTool(selectionTools.select_all_clips, { track_type: "video", track_index: 0 });
    } else {
      for (const c of todo) await callClassicTool(advancedTools.set_clip_selection, { node_id: c.nodeId, selected: true });
    }
    await callClassicTool(clipboardTools.batch_apply_effect, { effect_name: EFFECT_NAME, target: "selected" });
    await callClassicTool(selectionTools.deselect_all_clips, {});
  }
  // Horizontal Split = 1 явно (по умолчанию и так 1 — но не полагаемся). Пакетом, одной транзакцией.
  await setParamsBatch(bg.clips.map((_, i) => ({
    trackIndex: 0, clipIndex: i, componentMatchName: MATCH_NAME,
    params: [{ name: "Horizontal Split", value: HORIZONTAL_SPLIT, optional: true }],
  })));

  await verifyRgb(bg.clips.length);
  console.log(`  -> RGB Split на фоне: добавлен ${todo.length}, уже был ${done}; проверено.`);
  return { skipped: false, applied: todo.length, alreadyDone: done };
}

async function verifyRgb(expectedClips) {
  const bad = await callClassic(`
    var q = app.project.activeSequence, bad = [], t0 = q.videoTracks[0];
    if (t0.clips.numItems !== ${expectedClips}) bad.push("на фоне " + t0.clips.numItems + " клипов вместо ${expectedClips}");
    var wrong = 0, split = 0;
    for (var c = 0; c < t0.clips.numItems; c++) {
      var cl = t0.clips[c], n = 0;
      for (var k = 0; k < cl.components.numItems; k++) {
        var comp = cl.components[k]; if (comp.matchName !== "${MATCH_NAME}") continue;
        n++;
        for (var j = 0; j < comp.properties.numItems; j++)
          if (comp.properties[j].displayName === "Horizontal Split" && Math.abs(comp.properties[j].getValue() - ${HORIZONTAL_SPLIT}) > 0.001) split++;
      }
      if (n !== 1) wrong++;
    }
    if (wrong) bad.push("RGB Split не ровно один у " + wrong + " клипов фона");
    if (split) bad.push("Horizontal Split не ${HORIZONTAL_SPLIT} у " + split);
    var fg = 0;
    for (var t = 1; t < q.videoTracks.numTracks; t++)
      for (var c = 0; c < q.videoTracks[t].clips.numItems; c++) {
        var cl = q.videoTracks[t].clips[c];
        for (var k = 0; k < cl.components.numItems; k++) if (cl.components[k].matchName === "${MATCH_NAME}") fg++;
      }
    if (fg) bad.push("RGB Split на основных дорожках: " + fg);
    return __result(bad);
  `);
  if (bad.length) throw verifyError(bad.join("; "));
}

async function main() {
  const results = await runPipeline({ binName: BIN_NAME, applyFn: applyRgbToActiveSequence });
  checkResultsForFailures(results);
}

runCli(main);
