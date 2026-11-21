#!/usr/bin/env node
// Автономный запуск loop-метода (см. @instructions/4.0. Looping.md, "MCP-метод A")
// без Claude — напрямую через @tools/@Premiere Lib.mjs (те же функции, что стоят за
// MCP-инструментами, вызываются напрямую, без MCP-протокола).
//
// Статус (2026-09-10): Шаги 0, 2, 3, 4, 5, 6 (видео) и аудио-кроссфейд реализованы и
// ПОЛНОСТЬЮ подтверждены вживую как в автоматическом (этот скрипт), так и в ручном
// пошаговом режиме — включая устойчивый переход (см. блок ниже). Аудио берёт ПЕРВЫЙ клип
// A1 и клонирует именно его в конец — не важно, порезано аудио синхронно с видео (много
// клипов) или это один сплошной клип на всю секвенцию (см. 4.0. Looping.md).
// Шаг 1 (снятие переходов у краёв, если они уже есть) НЕ реализован — секвенция с
// существующими переходами на V1 пропускается с понятным сообщением.
// Фильтр ориентации: обрабатывает ТОЛЬКО горизонтальные секвенции (width > height) —
// вертикалки (уже зациклены заранее другим пайплайном) пропускаются автоматически.
//
// ВАЖНО: нельзя запускать одновременно с открытой сессией Claude Code, использующей
// premiere-pro MCP-сервер — оба процесса конкурируют за один и тот же UXP WebSocket
// порт (по умолчанию 7777) и один и тот же файловый CEP-мост.
//
// Обычный запуск — через лаунчер "4.0. Looping.py" в корне проекта (двойной клик,
// статус-бар). Прямой запуск этого файла (для отладки, из корня проекта):
//   node "@tools/mjs/4.0. Looping.mjs"                 -> обработать все секвенции в бине "~"
//   node "@tools/mjs/4.0. Looping.mjs" "Имя секвенции 1" "Имя секвенции 2" -> только перечисленные

import {
  inspectionTools, uxpAdvTools, transitionsTools, trackTargetingTools,
  callClassicTool, callUxpTool, selectOnly, withRetry,
  FRAME_SECONDS, runPipeline, runCli, stage, checkResultsForFailures,
} from "./@Premiere Lib.mjs";

const BIN_NAME = "~";

const DB_0 = 0.17782793939113617; // 0 дБ (10^((0-15)/20)), см. 4.0. Looping.md Шаг 6
const MINUS_30DB_FACTOR = 0.0316227766; // 10^(-30/20)

// --- Шаг 1 — снять авто-переходы (0.08с/2 кадра) у ГОЛОВЫ первого и ХВОСТА последнего
// клипа аудиодорожки (Premiere сам их подставляет при импорте — не связаны с лупом). Прямого
// инструмента нет — обходной путь ПОДТВЕРЖДЁН ВЖИВУЮ 2026-09-10: razor_all_tracks на
// внутреннем крае перехода → удалить образовавшийся 1-сливер → растянуть соседний клип
// обратно до исходной длины (in_seconds для головы, out_seconds для хвоста). Внутренние
// переходы между остальными клипами не трогаются (razor/remove адресуются точечно по
// времени/nodeId). Затрагивает ТОЛЬКО audio (video-край в норме без переходов — если они
// там есть, applyLoopToActiveSequence и так пропускает секвенцию раньше, см. ниже).
async function removeEdgeAudioTransitions(totalDuration) {
  let info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const a1 = info.audioTracks[0];
  if (!a1 || a1.clips.length === 0) return;

  const headT = a1.transitions.find((t) => t.startSeconds < FRAME_SECONDS / 2);
  if (headT) {
    const originalIn = a1.clips[0].inPointSeconds;
    await callClassicTool(trackTargetingTools.razor_all_tracks, {
      time_seconds: headT.endSeconds, track_type: "audio",
    });
    await callClassicTool(inspectionTools.get_full_sequence_info, {}).then(async (fresh) => {
      const sliver = fresh.audioTracks[0].clips[0]; // [0, headT.endSeconds]
      await selectOnly(sliver.nodeId);
      await callClassicTool(trackTargetingTools.remove_selected_clips, { ripple: false });
    });
    await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
      action: "update", media_type: "audio", track_index: 0, clip_index: 0,
      in_seconds: originalIn,
    });
    console.log(`  -> Снят авто-переход в начале A1 (было 0-${headT.endSeconds.toFixed(2)}с).`);
  }

  // Свежий снимок — индексы/nodeId после головной правки выше могли сдвинуться.
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const a1b = info.audioTracks[0];
  const tailT = a1b.transitions.find((t) => t.endSeconds > totalDuration - FRAME_SECONDS / 2);
  if (tailT) {
    const lastIdx = a1b.clips.length - 1;
    const originalOut = a1b.clips[lastIdx].outPointSeconds;
    await callClassicTool(trackTargetingTools.razor_all_tracks, {
      time_seconds: tailT.startSeconds, track_type: "audio",
    });
    await callClassicTool(inspectionTools.get_full_sequence_info, {}).then(async (fresh) => {
      const clips = fresh.audioTracks[0].clips;
      const sliver = clips[clips.length - 1]; // [tailT.startSeconds, totalDuration]
      await selectOnly(sliver.nodeId);
      await callClassicTool(trackTargetingTools.remove_selected_clips, { ripple: false });
    });
    await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
      action: "update", media_type: "audio", track_index: 0, clip_index: lastIdx,
      out_seconds: originalOut,
    });
    console.log(`  -> Снят авто-переход в конце A1 (было ${tailT.startSeconds.toFixed(2)}-${totalDuration.toFixed(2)}с).`);
  }
}

// --- Механика лупа (шаги 1-6 из 4.0. Looping.md, "MCP-метод A") ---
// ПОЛНОСТЬЮ ПОДТВЕРЖДЕНО ВЖИВУЮ 2026-09-10 (видео+аудио, включая F−1 и 6-кадровый переход,
// прогнано на чистой копии от начала до конца с полным readback-контролем) — см. память
// "standalone-loop-script". НАСТОЯЩАЯ причина прошлых провалов с пропадающим переходом —
// НЕ фокус UXP-вкладки и НЕ тайминг, а субтиковая погрешность плавающей точки: два
// независимых transform_track_item_uxp-трима (конец последнего клипа и начало дубля)
// визуально дают "встык" (например 40.92 vs 40.919999999996...), но отличаются на ~1 тик —
// и Premiere из-за этого молча отказывается строить переход (и UXP-, и classic QE-тул
// одинаково возвращают "успех", реально ничего не добавляя). Фикс — snapDupToLastClipEnd()
// ниже: перечитать оба реальных края и, если они не бит-в-бит совпадают, довыровнять дубль
// move_by_seconds на точную разницу ПЕРЕД добавлением перехода. С этим фиксом переход
// встаёт и переживает финальную обрезку дубля до 1 кадра без единой лишней паузы или
// повторного reopenTab — они не были нужны, это был ложный след.
// Шаг 1 (снятие переходов у краёв) НЕ реализован — если у секвенции уже есть переходы на
// первом/последнем клипе, скрипт останавливается с понятным сообщением вместо угадывания.
async function applyLoopToActiveSequence(name, sequenceId) {
  stage(name, "Scanning");
  let info = await callClassicTool(inspectionTools.get_full_sequence_info, {});

  // --- Фильтр ориентации: луп-метод только для ГОРИЗОНТАЛЬНЫХ секвенций. По имени не
  // проверяем — приписки могут быть любые (Saturni, 2026-09-05). Сверяем реальное разрешение
  // секвенции (width/height из get_full_sequence_info, т.е. frameSizeHorizontal/Vertical).
  // Вертикалка (height > width, обычно 1080×1920) уже зациклена заранее в другом пайплайне —
  // трогать её луп-методом не нужно (и опасно: там уже есть переход, что упало бы на Шаге 1).
  if (info.height > info.width) {
    return { skipped: true, reason: "not_horizontal", width: info.width, height: info.height };
  }

  const firstClipRaw = info.videoTracks[0].clips[0];
  const in0 = firstClipRaw.inPointSeconds;
  const marginFrames = Math.floor(in0 / FRAME_SECONDS);

  if (marginFrames < 3) {
    // Правило Saturni 2026-09-05: без ≥3 кадров запаса наплыв не построить. Тихий пропуск,
    // без лога — это штатный случай (короткие клипы без запаса встречаются часто), а не ошибка.
    return { skipped: true, reason: "insufficient_head_margin", marginFrames };
  }
  const N = marginFrames >= 5 ? 5 : marginFrames; // Шаг 0

  const v1 = info.videoTracks[0];
  if (v1.transitionCount > 0) {
    // НЕ штатный тихий пропуск — требует ручного вмешательства Saturni, поэтому lose:true
    // (runPipeline() превращает такой skip в полноценную ошибку: лог + консоль держится
    // открытой, см. п.6 запроса Saturni, 2026-09-11).
    return {
      skipped: true, lose: true, reason: "step1_not_implemented",
      loseMessage: "на V1 уже есть переход(ы) — авто-снятие переходов (Шаг 1) в скрипте " +
        "не реализовано, обработайте вручную и перезапустите",
    };
  }
  const firstClip = v1.clips[0];
  const lastClip = v1.clips[v1.clips.length - 1];
  const lastClipIndex = v1.clips.length - 1;
  const totalDuration = info.durationSeconds;

  // --- Шаг 1 (аудио) — снять авто-переходы у краёв A1, если есть, ДО дубля/клонов ---
  await removeEdgeAudioTransitions(totalDuration);

  // --- Шаг 2: дубль первого V-клипа в конец ---
  stage(name, "Duplicating");
  await withRetry(async () => {
    await selectOnly(firstClip.nodeId);
    await callUxpTool(uxpAdvTools.edit_timeline_uxp, {
      action: "clone_selection", video_track_offset: 0, time_offset_seconds: totalDuration,
    });
  });

  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const v1clips = info.videoTracks[0].clips;
  const dupIndex = v1clips.length - 1;
  const dupVideo = v1clips[dupIndex];

  // --- Шаг 3 (видео): подвинуть стык на F−1 БЕЗ roll_edit ---
  stage(name, "Trimming");
  // roll_edit двигает только позицию соседнего клипа, НЕ его source in/out — создаёт
  // рассогласование duration≠out-in, которое вскрывается только на финальном триме
  // (переход пропадал). Вместо этого — два САМОсогласованных трима (каждый двигает СВОЮ
  // пару end/out или start/in синхронно): подрезаем lastClip.end на F−1, и НЕЗАВИСИМО
  // подрезаем dupIndex.in на F−1 (оба сдвинуты на одну и ту же F — стык получается встык).
  await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
    action: "update", media_type: "video", track_index: 0, clip_index: lastClipIndex,
    end_seconds: totalDuration - FRAME_SECONDS,
  });
  await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
    action: "update", media_type: "video", track_index: 0, clip_index: dupIndex,
    in_seconds: dupVideo.inPointSeconds - FRAME_SECONDS,
  });

  // --- Снап стыка (КЛЮЧЕВОЙ фикс, найден вживую 2026-09-10) ---
  // Два независимых трима выше визуально дают "встык", но из-за плавающей точки могут
  // отличаться на ~1 тик (например lastClip.end=40.92 ровно, а dup.start=40.919999999996...).
  // Premiere из-за этой микроскопической щели молча отказывается строить переход на этом
  // стыке — ни UXP-, ни classic QE-тул не дают ошибки, просто ничего не добавляют.
  // Перечитываем оба реальных края и, если не совпадают бит-в-бит, довыравниваем дубль
  // move_by_seconds на точную разницу.
  // ⚠️ Снапим АБСОЛЮТНЫМ start_seconds (не относительным move_by_seconds на вычисленную
  // разницу двух double) — относительный сдвиг на вычисленную суб-тиковую дельту
  // (~3.9e-12с) сам округляется вниз до 0 тиков и НЕ применяется (проверено вживую
  // 2026-09-10: скрипт с move_by_seconds(delta) не снапнул стык и переход снова не встал).
  // Абсолютное присвоение start_seconds = точное значение конца соседа заставляет API
  // само посчитать целевой тик от абсолютного числа, а не от вычитания двух почти
  // одинаковых double — так стык гарантированно совпадает бит-в-бит.
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const freshLast = info.videoTracks[0].clips[lastClipIndex];
  const freshDup = info.videoTracks[0].clips[dupIndex];
  if (freshLast.endSeconds !== freshDup.startSeconds) {
    await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
      action: "update", media_type: "video", track_index: 0, clip_index: dupIndex,
      start_seconds: freshLast.endSeconds,
    });
  }

  // --- Шаг 6 (видео): переход, пока дубль ещё полной длины ---
  stage(name, "Blending");
  // Classic QE-тул (add_transition_to_clip), не UXP-версия — обе одинаково надёжны при
  // точном стыке (после снапа выше), но именно classic-путь проверен вживую до конца
  // (включая survival финального трима до 1 кадра).
  await callClassicTool(transitionsTools.add_transition_to_clip, {
    node_id: dupVideo.nodeId, transition_name: "Cross Dissolve", position: "start",
    duration_seconds: 2 * N * FRAME_SECONDS,
  });

  // --- Шаг 4/5 (видео): подрезка дубля до 1 кадра ---
  // Переход, поставленный НА этом стыке, переживает эту обрезку без проблем — проверено
  // вживую (readback после трима: transitionCount не падает до 0).
  await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
    action: "update", media_type: "video", track_index: 0, clip_index: dupIndex,
    end_seconds: totalDuration,
  });

  console.log(`  -> Видео-луп собран (N=${N} кадров перехода).`);

  // ⚠️ Обязательно свежий снимок ПОСЛЕ всех видео-правок (трим/переход/трим) —
  // старый `info` (снятый сразу после клонирования на Шаге 2) содержит ссылки на клипы,
  // которые успели протухнуть из-за последующих структурных правок секвенции ("The script
  // object is no longer valid" — воспроизводилось стабильно, не флаки, найдено 2026-09-05).
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});

  // --- Аудио: берём ПЕРВЫЙ клип A1 независимо от того, сколько всего клипов на
  // дорожке — не важно, порезано аудио синхронно с видео (несколько клипов) или
  // это один сплошной клип на всю секвенцию (один клип). В обоих случаях логика
  // идентична видео: клонируем именно первый клип в конец, дальше та же механика
  // (Saturni, 2026-09-05: "какая разница, порезана дорожка или нет, если начало
  // точно такое же — переносим в конец и делаем всё то же самое").
  const a1clips = info.audioTracks[0].clips;
  if (a1clips.length === 0) {
    console.log(`  -> Аудио-кроссфейд ПРОПУЩЕН: на A1 нет клипов. Видео-луп уже готов.`);
    return { skipped: false, N, audioSkipped: true };
  }
  const audioClip = a1clips[0]; // клонируем именно его — источник F0
  const lastAudioIndex = a1clips.length - 1;
  const lastAudioClip = a1clips[lastAudioIndex]; // а кроссфейд-фейд-аут ставим на ПОСЛЕДНИЙ клип A1
  const targetOut = audioClip.inPointSeconds; // F0, source-домен — для трима A2 (это ВЕРНО)
  const targetIn = targetOut - (N + 1) * FRAME_SECONDS;

  await withRetry(async () => {
    await selectOnly(audioClip.nodeId);
    await callUxpTool(uxpAdvTools.edit_timeline_uxp, {
      action: "clone_selection", audio_track_offset: 1, time_offset_seconds: totalDuration,
    });
  });

  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const a2clips = info.audioTracks[1].clips;
  const a2Index = a2clips.length - 1;

  // ⚠️ in_seconds и out_seconds ОБЯЗАТЕЛЬНО раздельными вызовами — вместе крашится
  // на audio-клипах (nullptr), см. 4.0. Looping.md Шаг 3 "Случай Б".
  await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
    action: "update", media_type: "audio", track_index: 1, clip_index: a2Index,
    in_seconds: targetIn,
  });
  await callUxpTool(uxpAdvTools.transform_track_item_uxp, {
    action: "update", media_type: "audio", track_index: 1, clip_index: a2Index,
    out_seconds: targetOut,
  });

  // Свежий снимок — нужны РЕАЛЬНЫЕ timeline-границы A2-дубля после трима, не пересчитывать
  // вручную (см. keyframeTime ниже, ему нужен АКТУАЛЬНЫЙ startSeconds клипа).
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const a2Dup = info.audioTracks[1].clips[a2Index];

  // --- Кроссфейд громкости (кейфреймы), делать последним ---
  // ⚠️ Фейд-аут ставится на ПОСЛЕДНИЙ клип A1 (lastAudioIndex), а не на клип 0 —
  // 0 совпадает с последним только когда на A1 один клип; при нескольких клипах
  // (аудио порезано синхронно с видео) это разные клипы (баг найден 2026-09-05
  // на реальном многоклиповом A1 — кейфреймы уезжали на первый клип).
  const a1Vol = await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "inspect", media_type: "audio", track_index: 0, clip_index: lastAudioIndex,
    component_index: 0, param_index: 1,
  });
  const v0 = typeof a1Vol.value === "number" ? a1Vol.value : DB_0;
  const vMinus30 = v0 * MINUS_30DB_FACTOR;

  // ⚠️ ДОМЕН time_seconds для add_keyframe — НЕ timeline (startSeconds/endSeconds) и НЕ
  // напрямую inPointSeconds/outPointSeconds, а (inPointSeconds + смещение_по_таймлайну) ×
  // speed. Подтверждено экспериментом 2026-09-09 (get_value_at_time интерполировал только
  // в этом домене). Старая версия скрипта передавала lastAudioClip.outPointSeconds/targetIn/
  // targetOut (сырые source-секунды БЕЗ ×speed и без привязки к смещению на таймлайне)
  // напрямую как time_seconds — кейфреймы улетали далеко за пределы секвенции ("аудио
  // уезжало куда-то"). См. память "standalone-loop-script"/"premiere-mcp-gotchas".
  const keyframeTime = (clip, timelineSeconds) =>
    (clip.inPointSeconds + (timelineSeconds - clip.startSeconds)) * clip.speed;

  const fadeOutStart = lastAudioClip.endSeconds - (N + 1) * FRAME_SECONDS;
  await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "add_keyframe", media_type: "audio", track_index: 0, clip_index: lastAudioIndex,
    component_index: 0, param_index: 1,
    time_seconds: keyframeTime(lastAudioClip, fadeOutStart), value: v0, interpolation: "linear",
  });
  await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "add_keyframe", media_type: "audio", track_index: 0, clip_index: lastAudioIndex,
    component_index: 0, param_index: 1,
    time_seconds: keyframeTime(lastAudioClip, lastAudioClip.endSeconds), value: vMinus30, interpolation: "linear",
  });
  await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "add_keyframe", media_type: "audio", track_index: 1, clip_index: a2Index,
    component_index: 0, param_index: 1,
    time_seconds: keyframeTime(a2Dup, a2Dup.startSeconds), value: vMinus30, interpolation: "linear",
  });
  await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "add_keyframe", media_type: "audio", track_index: 1, clip_index: a2Index,
    component_index: 0, param_index: 1,
    time_seconds: keyframeTime(a2Dup, a2Dup.endSeconds), value: v0, interpolation: "linear",
  });

  console.log(`  -> Аудио-кроссфейд собран.`);
  return { skipped: false, N, audioSkipped: false };
}

async function main() {
  // seq_done эмиттится сразу по каждой секвенции внутри runPipeline() (deferDone по
  // умолчанию false — доп. прохода после основного цикла тут нет).
  const results = await runPipeline({ binName: BIN_NAME, applyFn: applyLoopToActiveSequence });
  checkResultsForFailures(results);
}

runCli(main);
