#!/usr/bin/env node
// Автономный запуск "Размытие фона" (см. память loop-method.md разд. C и
// @instructions/4.0. Looping.md, "Размытый фон для вертикалок") без Claude — та же
// инфраструктура, что и 4.0. Looping.mjs, через @tools/premiere-lib.mjs.
//
// Фильтр ориентации ОБРАТНЫЙ относительно 4.0. Looping.mjs: обрабатывает ТОЛЬКО
// вертикальные секвенции (height > width) — уже готовые (сцены разведены по V1/V2
// пайплайном 4.1. Smart Verticals.md). Горизонтальные пропускаются автоматически.
//
// Статус (2026-09-05): рецепт проверен вручную через MCP на реальной секвенции «9 ` 1v»
// (ribbon-сборка + пересборка loop-хвоста + все эффекты + Crop/Scale) — сам стандэлон-скрипт
// в этом виде живьём целиком ещё не прогонялся, прогнать один раз под присмотром.
//
// Два прохода: 1) обычная сборка фона (ribbon + пересборка loop-хвоста, если есть + пресет
// BG-blurz`140`) по всем найденным вертикалкам; 2) ПОСЛЕ того как первый проход отработал по
// всем секвенциям — отдельным проходом letterbox-компенсация (Crop/Scale) по исходникам
// обработанных в этом запуске секвенций, с отчётом только по тем видео, где полосы реально
// найдены (см. 4.0. Looping.md, P.S.).
//
// ВАЖНО: нельзя запускать одновременно с открытой сессией Claude Code, использующей
// premiere-pro MCP-сервер — оба процесса конкурируют за один и тот же UXP WebSocket
// порт (по умолчанию 7777) и один и тот же файловый CEP-мост.
//
// Использование:
//   node 4.2. Background Blur.mjs                 -> обработать все вертикальные секвенции в бине "#Processing"
//   node 4.2. Background Blur.mjs "Имя секвенции 1" "Имя секвенции 2" -> только перечисленные

import {
  inspectionTools, selectionTools, trackTools, trackTargetingTools, clipboardTools,
  scriptingTools, mediaAnalysisTools, uxpTools, uxpAdvTools,
  callClassicTool, callUxpTool, withRetry, runPipeline, setActiveSequenceById, shutdown, FRAME_SECONDS,
} from "./@tools/premiere-lib.mjs";

const BIN_NAME = "#Processing";
const BG_TRACK_NAME = "BG-Blur"; // маркер идемпотентности: если V1 уже так называется — пропуск

// list_clip_effects — классический (CEP) тул, отдаёт data строкой JSON, а не объектом
// (в отличие от остальных classic-тулов) — распарсить перед использованием.
async function listClipEffects(nodeId) {
  const data = await callClassicTool(scriptingTools.list_clip_effects, { node_id: nodeId });
  // ⚠️ list_clip_effects сериализует значения "как есть", включая литерал undefined (не
  // строку!) для отсутствующих matchName — невалидный JSON. Заменяем на null перед парсингом.
  const parsed = typeof data === "string"
    ? JSON.parse(data.replace(/:undefined/g, ":null"))
    : data;
  return parsed.data;
}

// --- Letterbox P.S. (см. 4.0. Looping.md): база Motion Scale переднего плана = 140.
// Порог ниже — по тому, НАСКОЛЬКО процентов пришлось поднять Scale относительно базы (не по
// самому Crop%, т.к. у нативно-маленького разрешения кропа вообще нет, а Scale поднимать всё
// равно надо, см. computeLetterboxCrop). Если подъём Scale небольшой — фон (Transform на
// BG-треке) оставляем на базе 140, т.к. блюр и так «дотягивает». Если подъём заметный —
// поднимаем Transform-scale фона до того же значения, что и передний план. Порог не
// задокументирован Saturni точным числом (по одному примеру, 2,5% Crop → +5% Scale → фон не
// трогать), выставлен консервативно — можно поправить вручную после просмотра отчёта. ---
const BASE_MOTION_SCALE = 140;
const SMALL_CROP_THRESHOLD_PERCENT = 6; // порог по подъёму Scale в %, не по Crop% напрямую

async function applyBgBlurToActiveSequence(name) {
  let info = await callClassicTool(inspectionTools.get_full_sequence_info, {});

  // --- Фильтр ориентации: размытие фона только для ВЕРТИКАЛЬНЫХ секвенций — обратный
  // фильтр относительно 4.0. Looping.mjs (там пропускались вертикалки, тут пропускаем всё
  // остальное). По имени не проверяем — приписки могут быть любые. ---
  if (info.width >= info.height) {
    return { skipped: true, reason: "not_vertical", width: info.width, height: info.height };
  }

  if (info.videoTracks.length < 2) {
    console.log(`  -> ПРОПУСК: меньше 2 видеодорожек (${info.videoTracks.length}) — сцены ещё ` +
      `не разведены по V1/V2 (см. 4.1. Smart Verticals.md), рано для размытия фона.`);
    return { skipped: true, reason: "not_split" };
  }

  if (info.videoTracks[0].name === BG_TRACK_NAME) {
    console.log(`  -> ПРОПУСК: уже обработано (V1 называется "${BG_TRACK_NAME}").`);
    return { skipped: true, reason: "already_processed" };
  }

  // Шаг 0: если на переднем плане уже есть переход — его придётся пересобрать после
  // дублирования (clone_selection переходы срезает). Автоматически умеем пересобирать
  // ТОЛЬКО loop-хвост (переход, чей правый край = конец таймлайна, т.е. последний клип —
  // 1-кадровый дубль лупа, см. 4.0. Looping.mjs) — эта геометрия полностью известна и
  // проверена вживую 2026-09-05 на «9 ` 1v». Любой ДРУГОЙ переход (не у самого конца) —
  // пересборка не реализована, безопаснее пропустить целиком, чем угадывать (тот же
  // принцип, что Шаг 1 в 4.0. Looping.mjs; по факту такие переходы в материале и не
  // встречаются — см. verticals-method.md).
  const totalDuration = info.durationSeconds;
  const allTransitions = [];
  info.videoTracks.forEach((t) => t.transitions.forEach((tr) => allTransitions.push(tr)));
  const loopTailTransitions = allTransitions.filter(
    (tr) => Math.abs(tr.endSeconds - totalDuration) < FRAME_SECONDS / 2
  );
  const otherTransitions = allTransitions.filter(
    (tr) => Math.abs(tr.endSeconds - totalDuration) >= FRAME_SECONDS / 2
  );
  if (otherTransitions.length > 0 || loopTailTransitions.length > 1) {
    console.log(`  -> ПРОПУСК: на переднем плане переход(ы), не похожие на loop-хвост ` +
      `(${otherTransitions.length} прочих, ${loopTailTransitions.length} у конца таймлайна) — ` +
      `авто-пересборка для этого случая не реализована, обработайте вручную (см. ` +
      `4.0. Looping.md, разд. "Размытый фон") и перезапустите.`);
    return { skipped: true, reason: "transitions_not_implemented" };
  }
  const loopTailTransition = loopTailTransitions[0] || null;

  const foregroundTrackCount = info.videoTracks.length;

  // --- Шаг 1: новая дорожка добавляется в САМЫЙ НИЗ (становится V1), весь передний план
  // уезжает на трек вверх (V1→V2, V2→V3…) — подтверждено вживую 2026-09-04. ---
  await callClassicTool(trackTools.add_track, { track_type: "video", count: 1 });

  // --- Шаг 2: собрать сплошную ленту всего переднего плана на новом V1. Передний план
  // теперь на индексах 1..foregroundTrackCount (был 0..foregroundTrackCount-1 до сдвига).
  // Отрицательный video_track_offset работает (подтверждено вживую 2026-09-04). ---
  for (let t = 1; t <= foregroundTrackCount; t++) {
    if (info.videoTracks[t - 1].clips.length === 0) continue; // пустой трек — клонировать нечего
    await withRetry(async () => {
      await callClassicTool(selectionTools.deselect_all_clips, {});
      await callClassicTool(selectionTools.select_all_clips, { track_type: "video", track_index: t });
      await callUxpTool(uxpAdvTools.edit_timeline_uxp, {
        action: "clone_selection", video_track_offset: -t, time_offset_seconds: 0,
      });
    });
  }

  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const bgClips = info.videoTracks[0].clips;
  if (bgClips.length === 0) {
    console.log(`  -> ПРОПУСК: после сборки ленты на новом V1 не оказалось клипов — что-то пошло не так.`);
    return { skipped: true, reason: "ribbon_empty" };
  }
  console.log(`  -> Фон собран сплошной лентой (${bgClips.length} клипов на новом V1).`);

  // --- Пересборка loop-хвоста (если был найден на Шаге 0). clone_selection срезал переход —
  // дубль (последний клип ленты) сейчас снова 1-кадровый без перехода. Пересобираем ТОЧНО
  // так же, как в 4.0. Looping.mjs: временно растягиваем дубль на 2N кадров вперёд (это
  // реальные кадры начала исходного видео — F0, F0+1… — они доступны), добавляем переход
  // полной ширины 2N, затем подрезаем дубль обратно до 1 кадра — переход сам поджимается
  // до N на последнем клипе + 1 на дубле, с правым краем на конце таймлайна. Проверено вживую
  // 2026-09-05 на «9 ` 1v»: пересобранный переход геометрически идентичен исходному. ---
  if (loopTailTransition) {
    const N = Math.round((loopTailTransition.endSeconds - loopTailTransition.startSeconds) / FRAME_SECONDS) - 1;
    const dupIndex = bgClips.length - 1;
    const dup = bgClips[dupIndex];
    if (dup.durationSeconds > 1.5 * FRAME_SECONDS) {
      console.log(`  ⚠ Loop-хвост не пересобран: последний клип ленты длиннее ожидаемого ` +
        `1 кадра (${dup.durationSeconds.toFixed(3)}с) — геометрия не совпала с ожидаемой, ` +
        `добавьте переход вручную.`);
    } else {
      await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
        action: "update", media_type: "video", track_index: 0, clip_index: dupIndex,
        out_seconds: dup.outPointSeconds + (2 * N - 1) * FRAME_SECONDS,
      });
      await callUxpTool(uxpTools.add_video_transition_uxp, {
        video_track_index: 0, clip_index: dupIndex,
        match_name: "AE.ADBE Cross Dissolve New", position: "start",
        duration_seconds: 2 * N * FRAME_SECONDS,
      });
      await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
        action: "update", media_type: "video", track_index: 0, clip_index: dupIndex,
        end_seconds: totalDuration,
      });
      console.log(`  -> Loop-хвост пересобран на новом фоновом треке (N=${N} кадров).`);
    }
  }

  // --- Пресет BG-blurz`140` на все клипы нового V1: Transform + Fast Blur + RGB Split ---
  await callClassicTool(clipboardTools.batch_apply_effect, {
    effect_name: "Transform", target: "track", track_type: "video", track_index: 0,
  });
  await callClassicTool(clipboardTools.batch_apply_effect, {
    effect_name: "Fast Blur", target: "track", track_type: "video", track_index: 0,
  });
  await callClassicTool(clipboardTools.batch_apply_effect, {
    effect_name: "RGB Split", target: "track", track_type: "video", track_index: 0,
  });

  // Индексы компонентов узнаём динамически по matchName на первом клипе (порядок применения
  // детерминирован, но абсолютный индекс компонента зависит от базовых компонентов клипа —
  // Motion/Opacity и т.п. — поэтому не хардкодим номер компонента; номера параметров внутри
  // компонента уже задокументированы и проверены в loop-method.md, берём по displayName —
  // надёжнее, чем полагаться на фиксированный param_index).
  const firstBgClip = bgClips[0];
  const effectsInfo = await listClipEffects(firstBgClip.nodeId);
  const geometryComp = effectsInfo.components.find((c) => c.matchName === "AE.ADBE Geometry");
  const blurComp = effectsInfo.components.find((c) => c.matchName === "AE.ADBE Fast Blur");
  if (!geometryComp || !blurComp) {
    console.log(`  -> Эффекты применены, но не нашёл Transform/Fast Blur среди компонентов первого ` +
      `клипа (Geometry=${!!geometryComp}, FastBlur=${!!blurComp}) — Scale/Blurriness придётся ` +
      `выставить вручную.`);
    return { skipped: false, ribbonBuilt: true, effectsConfigured: false };
  }
  const uniformScaleParam = geometryComp.properties.find((p) => p.displayName === "Uniform Scale");
  const scaleHeightParam = geometryComp.properties.find((p) => p.displayName === "Scale Height");
  const scaleWidthParam = geometryComp.properties.find((p) => p.displayName === "Scale Width");
  const blurrinessParam = blurComp.properties.find((p) => p.displayName === "Blurriness");

  for (let idx = 0; idx < bgClips.length; idx++) {
    const clip = bgClips[idx];
    if (uniformScaleParam) {
      await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
        action: "set_value", media_type: "video", track_index: 0, clip_index: idx,
        component_index: geometryComp.index, param_index: uniformScaleParam.index, value: true,
      });
    }
    if (scaleHeightParam) {
      await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
        action: "set_value", media_type: "video", track_index: 0, clip_index: idx,
        component_index: geometryComp.index, param_index: scaleHeightParam.index, value: 140,
      });
    }
    if (scaleWidthParam) {
      await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
        action: "set_value", media_type: "video", track_index: 0, clip_index: idx,
        component_index: geometryComp.index, param_index: scaleWidthParam.index, value: 140,
      });
    }
    if (blurrinessParam) {
      await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
        action: "set_value", media_type: "video", track_index: 0, clip_index: idx,
        component_index: blurComp.index, param_index: blurrinessParam.index, value: 100,
      });
    }
    await callClassicTool(trackTargetingTools.set_clip_opacity, { node_id: clip.nodeId, opacity: 90 });
  }
  // RGB Split — параметры по умолчанию после свежего наложения уже верные (Horizontal Split=1,
  // Depth Split=0, Vertigo=0, Feather=0), трогать не нужно (подтверждено Saturni 2026-09-04).

  console.log(`  -> Пресет BG-blurz\`140\` применён к ${bgClips.length} клипам фона.`);

  // Маркер идемпотентности — переименовываем новый V1, чтобы повторный запуск скрипта
  // распознал уже обработанную секвенцию и пропустил её (см. проверку выше).
  await callUxpTool(uxpTools.rename_track_uxp, { track_type: "video", track_index: 0, name: BG_TRACK_NAME });

  console.log(`  -> Готово.`);
  return { skipped: false, ribbonBuilt: true, effectsConfigured: true };
}

// --- Проход 2: letterbox-компенсация. Отдельная функция, а не часть Прохода 1, по прямому
// требованию Saturni: сначала все вертикалки должны полностью обработаться и об этом должно
// быть явно сказано в консоли, ТОЛЬКО ПОТОМ начинается проверка/правка Crop/Scale. ---

// Кэш по media_path — один и тот же исходный горизонтал может стоять за несколькими
// вертикалками (разные секвенции того же ролика), незачем гонять ffmpeg повторно.
//
// Два разных случая, оба требуют Scale, но НЕ оба требуют Crop:
// - coded_height === 1080 и обнаружены реальные полосы → ЗАПЕЧЁННЫЙ letterbox: и Crop
//   (убрать полосы), и Scale (компенсировать потерю площади от кропа).
// - coded_height < 1080 → это НЕ letterbox, а собственное нативное разрешение источника
//   (проверено Saturni: «Дэдпул и Росомаха» 1920×800, «Человек-паук» 1920×896 — реальных
//   полос там нет). Полосы НЕ кропаем (нечего кропать), но Scale всё равно нужен — видео
//   меньше кадра сцены (1080), его нужно растянуть до нужной высоты, иначе по краям пустота.
async function computeLetterboxCrop(mediaPath, cache) {
  if (cache.has(mediaPath)) return cache.get(mediaPath);
  let result = null;
  try {
    const streams = await callClassicTool(mediaAnalysisTools.inspect_media_streams, { media_path: mediaPath });
    const videoStream = streams.streams.find((s) => s.codec_type === "video");
    if (videoStream && videoStream.coded_height === 1080) {
      const bounds = await callClassicTool(mediaAnalysisTools.detect_active_picture_bounds, {
        media_path: mediaPath, sample_seconds: 60,
      });
      const barPx = Math.round((videoStream.coded_height - bounds.activePicture.height) / 2);
      if (barPx > 0) {
        const cropPercent = Math.ceil(((100 * barPx) / videoStream.coded_height) * 2) / 2; // до 0,5 ВВЕРХ
        const fgScale = Math.round(BASE_MOTION_SCALE / (1 - (2 * cropPercent) / 100));
        result = { mode: "letterbox", barPx, cropPercent, fgScale };
      }
    } else if (videoStream && videoStream.coded_height < 1080) {
      const fillFactor = 1080 / videoStream.coded_height;
      const fgScale = Math.round(BASE_MOTION_SCALE * fillFactor);
      result = { mode: "native_fill", barPx: 0, cropPercent: 0, fgScale, codedHeight: videoStream.coded_height };
    }
    if (result) {
      const scaleBumpPercent = 100 * (result.fgScale / BASE_MOTION_SCALE - 1);
      result.bgScale = scaleBumpPercent > SMALL_CROP_THRESHOLD_PERCENT ? result.fgScale : BASE_MOTION_SCALE;
    }
  } catch (e) {
    console.log(`  ⚠ Не удалось проверить letterbox/разрешение для "${mediaPath}": ${e.message}`);
  }
  cache.set(mediaPath, result);
  return result;
}

async function applyLetterboxToSequence(name, sequenceId, cache) {
  await setActiveSequenceById(sequenceId);
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const bgTrack = info.videoTracks.find((t) => t.name === BG_TRACK_NAME);
  if (!bgTrack || bgTrack.clips.length === 0) return null;

  const foregroundTracks = info.videoTracks.filter((t) => t.name !== BG_TRACK_NAME);
  const firstFgClip = foregroundTracks.flatMap((t) => t.clips)[0];
  if (!firstFgClip || !firstFgClip.sourceMediaPath) return null;

  const crop = await computeLetterboxCrop(firstFgClip.sourceMediaPath, cache);
  if (!crop) return null; // ни полос, ни нестандартного разрешения — в отчёт не попадает, ничего не трогаем

  // Индексы компонентов/параметров переднего плана — дискавер по первому клипу (не полагаемся
  // на данные из Прохода 1: секвенция с тех пор переактивировалась, старые ссылки протухли бы).
  const fgEffects = await listClipEffects(firstFgClip.nodeId);
  const motionComp = fgEffects.components.find((c) => c.matchName === "AE.ADBE Motion");
  if (!motionComp) {
    console.log(`  ⚠ "${name}": не нашёл компонент Motion на переднем плане — Crop/Scale пропущен.`);
    return null;
  }
  const scaleParam = motionComp.properties.find((p) => p.displayName === "Scale");
  const cropTopParam = motionComp.properties.find((p) => p.displayName === "Crop Top");
  const cropBottomParam = motionComp.properties.find((p) => p.displayName === "Crop Bottom");

  // Crop Top/Bottom ставим ТОЛЬКО в режиме "letterbox" (реальные запечённые полосы есть,
  // что кропать) — в режиме "native_fill" кропать нечего, там только Scale.
  const paramsToSet = [scaleParam && [scaleParam.index, crop.fgScale]];
  if (crop.cropPercent > 0) {
    paramsToSet.push(cropTopParam && [cropTopParam.index, crop.cropPercent]);
    paramsToSet.push(cropBottomParam && [cropBottomParam.index, crop.cropPercent]);
  }
  for (const track of foregroundTracks) {
    for (let idx = 0; idx < track.clips.length; idx++) {
      for (const [paramIndex, value] of paramsToSet.filter(Boolean)) {
        await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
          action: "set_value", media_type: "video", track_index: track.index, clip_index: idx,
          component_index: motionComp.index, param_index: paramIndex, value,
        });
      }
    }
  }

  // Фон (Transform Scale) — тоже дискавер заново, свежими индексами.
  const bgEffects = await listClipEffects(bgTrack.clips[0].nodeId);
  const geometryComp = bgEffects.components.find((c) => c.matchName === "AE.ADBE Geometry");
  if (geometryComp) {
    const scaleHeightParam = geometryComp.properties.find((p) => p.displayName === "Scale Height");
    const scaleWidthParam = geometryComp.properties.find((p) => p.displayName === "Scale Width");
    for (let idx = 0; idx < bgTrack.clips.length; idx++) {
      for (const param of [scaleHeightParam, scaleWidthParam].filter(Boolean)) {
        await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
          action: "set_value", media_type: "video", track_index: bgTrack.index, clip_index: idx,
          component_index: geometryComp.index, param_index: param.index, value: crop.bgScale,
        });
      }
    }
  }

  return { name, mediaPath: firstFgClip.sourceMediaPath, ...crop };
}

async function main() {
  const results = await runPipeline({ binName: BIN_NAME, applyFn: applyBgBlurToActiveSequence });
  console.log("Вертикалки обработаны — проверяю letterbox-компенсацию (Crop/Scale)...\n");

  const processed = results.filter((r) => r.result && r.result.skipped === false);
  const cache = new Map();
  const cropped = [];
  for (const r of processed) {
    const outcome = await applyLetterboxToSequence(r.name, r.sequenceId, cache);
    if (outcome) cropped.push(outcome);
  }

  if (cropped.length === 0) {
    console.log("Ни полос, ни нестандартного разрешения не обнаружено — Crop/Scale не потребовались.");
  } else {
    console.log(`Crop/Scale применены к ${cropped.length} секвенции(ям):`);
    cropped.forEach((c) => {
      if (c.mode === "letterbox") {
        console.log(`  - ${c.name}: запечённый letterbox, полосы ${c.barPx}px, ` +
          `Crop Top/Bottom ${c.cropPercent}%, Motion Scale ${BASE_MOTION_SCALE}→${c.fgScale}, ` +
          `фон Transform Scale ${c.bgScale} (источник: ${c.mediaPath})`);
      } else {
        console.log(`  - ${c.name}: нативное разрешение источника ${c.codedHeight}p (не letterbox, ` +
          `без Crop), Motion Scale ${BASE_MOTION_SCALE}→${c.fgScale}, фон Transform Scale ${c.bgScale} ` +
          `(источник: ${c.mediaPath})`);
      }
    });
  }
}

main()
  .catch((err) => {
    console.error(`\nОшибка: ${err.message}`);
    process.exitCode = 1;
  })
  .finally(shutdown);
