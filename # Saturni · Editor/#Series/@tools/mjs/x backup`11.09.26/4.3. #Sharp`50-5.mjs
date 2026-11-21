#!/usr/bin/env node
// Автономное точечное наложение резкости (Unsharp Mask: Amount 50 / Radius 5 / Threshold 0,
// см. экспортированный пресет @instructions/xSharp`50-5.prfpset — .prfpset сам не
// импортируется, эффект и параметры выставляются напрямую через классические тулы, это
// надёжнее и не требует парсинга формата пресета) на все секвенции в бине "#Processing".
// Запускать ПОСЛЕДНИМ, после 4.0. Looping.mjs → 4.1. Smart Verticals.mjs →
// 4.2. Background Blur.mjs (Saturni, 2026-09-10).
//
// Правило применения:
//   - горизонтальная секвенция (width > height, результат 4.0.) — эффект на ВСЕ клипы всех
//     видеодорожек.
//   - вертикальная секвенция (height > width, результат 4.1./4.2., трек V1 = "BG-Blur") —
//     эффект на все клипы КРОМЕ V1: резкость на размытом фоне не нужна и портит блюр.
//     Секвенция без второй видеодорожки (4.2. ещё не прогнан) пропускается с сообщением.
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
// Использование:
//   node "4.3. #Sharp`50-5.mjs"                 -> все секвенции в бине "#Processing" (рекурсивно)
//   node "4.3. #Sharp`50-5.mjs" "Имя 1" "Имя 2"  -> только перечисленные

import {
  inspectionTools, selectionTools, advancedTools, clipboardTools, keyframeTools,
  callClassicTool, runPipeline, shutdown,
} from "./@tools/premiere-lib.mjs";

const BIN_NAME = "#Processing";
const EFFECT_NAME = "Unsharp Mask";
const AMOUNT = 50, RADIUS = 5, THRESHOLD = 0;

async function applySharpToClips(clips) {
  const todo = clips.filter((c) => !c.effects.includes(EFFECT_NAME));
  if (todo.length === 0) return { applied: 0, skipped: clips.length };

  await callClassicTool(selectionTools.deselect_all_clips, {});
  for (const c of todo) {
    await callClassicTool(advancedTools.set_clip_selection, { node_id: c.nodeId, selected: true });
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

async function applySharpToActiveSequence() {
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const isVertical = info.height > info.width;

  let clips = [];
  if (isVertical) {
    // Пропускаем V1 только если это ДЕЙСТВИТЕЛЬНО фоновый трек от 4.2. Background Blur.mjs
    // (называется строго "BG-Blur", см. BG_TRACK_NAME там) — а не просто "любая вертикалка
    // с ≥2 дорожками": вертикалка, собранная 4.1. Smart Verticals.mjs, но ЕЩЁ не прогнанная
    // через 4.2., тоже имеет 2+ дорожки (V1/V2 — обычный передний план, разведённый по
    // сценам), и в этом случае V1 — реальные кадры, которые НУЖНО резать, а не блюр.
    if (info.videoTracks[0]?.name !== "BG-Blur") {
      console.log(`  ⚠ Вертикалка, но V1 не называется "BG-Blur" — похоже, "4.2. Background ` +
        `Blur.mjs" ещё не прогнан. Обрабатываю ВСЕ дорожки как передний план (ничего не блюрю).`);
      for (const t of info.videoTracks) clips.push(...t.clips);
    } else {
      // V1 — фоновая размытая лента, резкость туда не нужна. Всё остальное — да.
      for (let t = 1; t < info.videoTracks.length; t++) clips.push(...info.videoTracks[t].clips);
    }
  } else {
    for (const t of info.videoTracks) clips.push(...t.clips);
  }

  if (clips.length === 0) {
    console.log(`  -> ПРОПУСК: клипов для обработки не нашлось.`);
    return { skipped: true, reason: "no_clips" };
  }

  const { applied, skipped } = await applySharpToClips(clips);
  console.log(`  -> ${isVertical ? "Вертикалка (без V1)" : "Горизонталка"}: резкость применена ` +
    `к ${applied} клипам` + (skipped > 0 ? `, пропущено ${skipped} (уже обработаны).` : "."));
  return { skipped: false, applied, alreadyDone: skipped };
}

async function main() {
  await runPipeline({ binName: BIN_NAME, applyFn: applySharpToActiveSequence });
  await shutdown();
}

main().catch(async (err) => {
  console.log("\n========================================");
  console.log("ОШИБКА (исключение в main()) — скрипт остановился.");
  console.log("========================================");
  console.error(err);
  console.log("========================================");
  try { await shutdown(); } catch (e) { /* мост уже мог быть недоступен */ }
  process.exit(1);
});
