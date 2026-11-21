#!/usr/bin/env node
// Автономное точечное наложение резкости (Unsharp Mask: Amount 50 / Radius 5 / Threshold 0,
// см. экспортированный пресет @instructions/xSharp`50-5.prfpset — .prfpset сам не
// импортируется, эффект и параметры выставляются напрямую через классические тулы, это
// надёжнее и не требует парсинга формата пресета) на все секвенции в бине "~".
// Запускать ПОСЛЕДНИМ, после 4.0. Looping.mjs → 4.1. Smart Verticals.mjs →
// 4.2. Background Blur.mjs (Saturni, 2026-09-10).
//
// Правило применения:
//   - горизонтальная секвенция (width > height, результат 4.0.) — эффект на ВСЕ клипы всех
//     видеодорожек.
//   - вертикальная секвенция (height > width, результат 4.1./4.2.) — эффект на все клипы
//     КРОМЕ V1 ВСЕГДА, вне зависимости от того, как называется трек: резкость на фоне не
//     нужна и портит блюр. Имя трека НЕ проверяем — 4.2. Background Blur.mjs иногда падает
//     до шага переименования (rename_track_uxp), но ribbon на V1 к этому моменту уже собран
//     и обработан, так что V1 в вертикалке — всегда фон, называется он "BG-Blur" или нет.
//
// ВАЖНО, идемпотентность (проверено вживую 2026-09-10): batch_apply_effect НЕ идемпотентен —
// повторный вызов на клипе, где Unsharp Mask уже есть, добавляет ВТОРОЙ независимый инстанс
// поверх первого (со значениями по умолчанию Amount=0), а не обновляет существующий. Поэтому
// каждый клип фильтруется по факту "Unsharp Mask" уже в его списке эффектов (из
// get_full_sequence_info) — обрабатываются только клипы, где эффекта ещё нет.
//
// ВАЖНО: нельзя запускать одновременно с открытой сессией Claude Code, использующей
// premiere-pro MCP-сервер — оба процесса конкурируют за один и тот же UXP WebSocket порт.
//
// Обычный запуск — через лаунчер "4.4. #Sharp`50-5.py" в корне проекта (двойной клик,
// статус-бар). Прямой запуск этого файла (для отладки, из корня проекта):
//   node "@tools/mjs/4.4. #Sharp`50-5.mjs"                 -> все секвенции в бине "~" (рекурсивно)
//   node "@tools/mjs/4.4. #Sharp`50-5.mjs" "Имя 1" "Имя 2"  -> только перечисленные

import {
  inspectionTools, selectionTools, advancedTools, clipboardTools, keyframeTools,
  callClassicTool, runPipeline, runCli, stage, checkResultsForFailures,
} from "./@Premiere Lib.mjs";

const BIN_NAME = "~";
const EFFECT_NAME = "Unsharp Mask";
const AMOUNT = 50, RADIUS = 5, THRESHOLD = 0;

async function applySharpToClips(clips) {
  const todo = clips.filter((c) => !c.effects.includes(EFFECT_NAME));
  if (todo.length === 0) return { applied: 0, skipped: clips.length };

  // Выделяем не по одному клипу, а сразу всей дорожкой (select_all_clips), чтобы не гонять
  // set_clip_selection на каждый клип по отдельности — это заметно быстрее. Клипы, которые
  // уже обработаны (идемпотентность), после этого снимаем с выделения точечно — на практике
  // такое бывает редко (перезапуск после частичного сбоя), так что точечных снятий немного.
  const alreadyDone = clips.filter((c) => c.effects.includes(EFFECT_NAME));
  const trackIndices = [...new Set(todo.map((c) => c.trackIndex))];

  await callClassicTool(selectionTools.deselect_all_clips, {});
  for (const ti of trackIndices) {
    await callClassicTool(selectionTools.select_all_clips, { track_type: "video", track_index: ti });
  }
  for (const c of alreadyDone) {
    if (trackIndices.includes(c.trackIndex)) {
      await callClassicTool(advancedTools.set_clip_selection, { node_id: c.nodeId, selected: false });
    }
  }
  await callClassicTool(clipboardTools.batch_apply_effect, { effect_name: EFFECT_NAME, target: "selected" });
  for (const c of todo) {
    await callClassicTool(keyframeTools.set_effect_property, {
      node_id: c.nodeId, effect_name: EFFECT_NAME, property_name: "Amount", value: AMOUNT,
    });
    await callClassicTool(keyframeTools.set_effect_property, {
      node_id: c.nodeId, effect_name: EFFECT_NAME, property_name: "Radius", value: RADIUS,
    });
    await callClassicTool(keyframeTools.set_effect_property, {
      node_id: c.nodeId, effect_name: EFFECT_NAME, property_name: "Threshold", value: THRESHOLD,
    });
  }
  return { applied: todo.length, skipped: clips.length - todo.length };
}

async function applySharpToActiveSequence(name) {
  stage(name, "Scanning");
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const isVertical = info.height > info.width;

  let clips = [];
  if (isVertical) {
    // V1 у вертикалки — всегда фон (ribbon от 4.2. Background Blur.mjs), резкость туда не
    // нужна и портит блюр. Имя трека не проверяем (см. комментарий в шапке файла) — пропускаем
    // индекс 0 безусловно.
    for (let t = 1; t < info.videoTracks.length; t++) {
      const track = info.videoTracks[t];
      clips.push(...track.clips.map((c) => ({ ...c, trackIndex: track.index })));
    }
  } else {
    for (const t of info.videoTracks) {
      clips.push(...t.clips.map((c) => ({ ...c, trackIndex: t.index })));
    }
  }

  if (clips.length === 0) {
    console.log(`  -> ПРОПУСК: клипов для обработки не нашлось.`);
    return { skipped: true, reason: "no_clips" };
  }

  stage(name, isVertical ? "Sharpening V" : "Sharpening H");
  const { applied, skipped } = await applySharpToClips(clips);
  console.log(`  -> ${isVertical ? "Вертикалка (без V1)" : "Горизонталка"}: резкость применена ` +
    `к ${applied} клипам` + (skipped > 0 ? `, пропущено ${skipped} (уже обработаны).` : "."));
  return { skipped: false, applied, alreadyDone: skipped };
}

async function main() {
  // seq_done эмиттится сразу по каждой секвенции внутри runPipeline() (deferDone по
  // умолчанию false — доп. прохода после основного цикла тут нет).
  const results = await runPipeline({ binName: BIN_NAME, applyFn: applySharpToActiveSequence });
  checkResultsForFailures(results);
}

runCli(main);
