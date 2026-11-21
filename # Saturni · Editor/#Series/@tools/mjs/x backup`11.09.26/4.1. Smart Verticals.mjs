#!/usr/bin/env node
// Автономный запуск вертикальной адаптации (этап 4, см.
// @instructions/4.1. Smart Verticals.md) без пошагового участия Claude — та же
// инфраструктура и та же система, что у "2. Silence Cut.mjs" / "4.0. Looping.mjs" /
// "4.2. Background Blur.mjs": секвенции складываются в бин "#Processing", скрипт сам
// бэкапит весь бин целиком перед стартом (через @tools/premiere-lib.mjs). ЗАПУСКАТЬ ПОСЛЕ
// "4.0. Looping.mjs" (Saturni, 2026-09-09) — если секвенция должна быть зациклена, петля
// должна быть уже собрана до вертикальной адаптации (см. обработку loop-хвоста ниже).
//
// Пайплайн на одну горизонтальную секвенцию: SED (строго первый шаг, без исключений —
// см. «ОБЯЗАТЕЛЬНЫЙ ЧЕК-ПОЙНТ» в инструкции) → @tools/vreframe_sed.py (анализ кадрирования
// по рендеру) → дубликат секвенции + ресайз 1080×1920 → Motion Scale 140 + Position на
// каждый клип (пока всё ещё на одной дорожке) → развод чётных умных сцен на V2
// (clone_selection + lift_selection_uxp).
//
// Рендер (`<name> \` 1h.mp4`) ищется рекурсивным обходом папки проекта (рядом с .prproj) —
// секвенция может лежать в "#Processing" плоско, без привязки к бину "Серия N", поэтому
// путь к рендеру не выводится из имени бина. Бин "v" для готовой вертикалки создаётся/
// находится под тем же бином, где физически лежит найденный рендер (обычно "Серия N"); если
// это не удаётся (рендер найден, а такого бина в проекте нет) — "v" создаётся прямо под
// "#Processing".
//
// НЕ реализовано (сознательно, как и в 4.0./4.2. для их нереализованных случаев —
// безопаснее пропустить с сообщением, чем угадывать): секвенция с НАСТОЯЩИМ видеопереходом
// не у самого конца таймлайна (правило 2а инструкции) — такое ни разу не встречалось в
// реальном материале (там только аудиокроссфейды). Loop-хвост (переход у самого конца,
// 1-кадровый дубль от 4.0. Looping.mjs) — обрабатывается: дубль остаётся на той же дорожке,
// что и предыдущий клип, с той же Motion-позицией, что у самой первой умной сцены.
//
// ВАЖНО: нельзя запускать одновременно с открытой сессией Claude Code, использующей
// premiere-pro MCP-сервер — оба процесса конкурируют за один и тот же UXP WebSocket порт.
//
// Использование (из корня проекта):
//   node "4.1. Smart Verticals.mjs"                    -> все горизонтальные секвенции в
//     бине "#Processing" (кроме "c", кроме уже собранных 1v, кроме без рендера)
//   node "4.1. Smart Verticals.mjs" "4. Вещи" "5. Изгой" -> только перечисленные секвенции
//
// Перед запуском: сложить нужные горизонтальные секвенции в бин "#Processing" в Premiere
// самому (как для "2. Silence Cut.mjs") — скрипт сам их найдёт и обработает все.
//
// Статус (2026-09-10): прогнана вживую, рабочая. Известные фиксы: (1) automate_effect_
// parameters_uxp флакует чаще обычного сразу после переключения вкладки секвенции —
// setClipMotionScale() использует повышенный retry (8 вместо стандартных 3, вызов
// идемпотентный — абсолютный set_value); (2) мелкие "умные сцены" (couple кадров — SED-
// артефакт или loop-хвост) получают ненадёжный crop от анализа по 1-2 кадрам — теперь
// приравниваются к соседней группе на уровне плана (см. блок после Шага 2); (3) правило
// про переходы — если между двумя умными сценами есть видеопереход, обе стороны остаются
// на V1, отсчёт V1/V2 после них начинается заново (см. блок после Шага 2).

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  inspectionTools, selectionTools, advancedTools, discoveryTools, mediaTools,
  sequenceTools, utilityTools, competitorGapTools, uxpAdvTools, uxpTools, projectTools,
  callClassicTool, callUxpTool, callClassic, escapeForExtendScript,
  withRetry, runPipeline, shutdown, FRAME_SECONDS,
} from "./@tools/premiere-lib.mjs";

const BIN_NAME = "#Processing";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const VREFRAME_SCRIPT = path.join(HERE, "@tools", "vreframe_sed.py");
const OUT_DIR = path.join(HERE, "!verticals");
const SEQ_W = 1080, SEQ_H = 1920, SCALE = 140;
const RENDER_DURATION_TOLERANCE_S = 0.5; // рендер устарел (Saturni менял скорость и т.п.) — просить перерендерить

function runChild(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, opts);
    let out = "", err = "";
    proc.stdout?.on("data", (d) => { out += d.toString(); });
    proc.stderr?.on("data", (d) => { err += d.toString(); });
    proc.on("close", (code) => {
      if (code !== 0) return reject(new Error(`${cmd} exited ${code}:\n${out}\n${err}`));
      resolve({ out, err });
    });
    proc.on("error", reject);
  });
}

async function ffprobeDuration(file) {
  const { out } = await runChild("ffprobe", [
    "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", file,
  ]);
  const v = parseFloat(out.trim());
  if (!Number.isFinite(v)) throw new Error(`ffprobe не вернул длительность для "${file}": ${out}`);
  return v;
}

async function runVreframeSed(renderPath, cutsPath, outPath) {
  await runChild("py", [
    "-3", VREFRAME_SCRIPT,
    "--render", renderPath, "--cuts", cutsPath, "--out", outPath,
    "--seq", `${SEQ_W}x${SEQ_H}`, "--scale", String(SCALE),
  ], { env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" } });
}

// --- Рекурсивный поиск рендера по имени файла под папкой проекта — секвенция может лежать
// в "#Processing" плоско, без бина "Серия N", поэтому путь к рендеру не выводим из бина. ---
function findFileRecursive(dir, filename, maxDepth = 6, depth = 0) {
  if (depth > maxDepth) return null;
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return null; }
  for (const entry of entries) {
    if (entry.isFile() && entry.name === filename) return path.join(dir, entry.name);
  }
  for (const entry of entries) {
    if (entry.isDirectory() && !entry.name.startsWith(".")) {
      const found = findFileRecursive(path.join(dir, entry.name), filename, maxDepth, depth + 1);
      if (found) return found;
    }
  }
  return null;
}

// --- Бин "v" для готовой вертикалки — сначала пробуем под бином рендера (обычно "Серия N"),
// если такого бина в проекте вообще нет — падаем на "#Processing" (плоское хранение). ---
async function ensureVBin(preferredParentBinName) {
  for (const parent of [preferredParentBinName, BIN_NAME]) {
    if (!parent) continue;
    try {
      const info = await callClassicTool(inspectionTools.get_bin_contents, {
        bin_id: `${parent}/v`, recursive: false, limit: 1,
      });
      return info.binNodeId;
    } catch (e) { /* бина "v" тут нет — пробуем создать */ }
    try {
      const created = await callClassicTool(mediaTools.create_bin, { name: "v", parent_bin: parent });
      return created.nodeId;
    } catch (e) { /* самого parent-бина нет в проекте — пробуем следующий вариант */ }
  }
  throw new Error(`Не удалось найти/создать бин "v" ни под "${preferredParentBinName}", ни под "${BIN_NAME}".`);
}

async function alreadyBuilt(verticalName) {
  // ВАЖНО: искать нужно только внутри поддерева BIN_NAME ("#Processing"), НЕ по всему
  // проекту — find_project_item_by_name матчит вообще любой элемент с таким именем, а
  // старые авто-бэкапы ("#Processing DDMMYY-HHMMSS", соседи BIN_NAME, не его потомки)
  // регулярно содержат такое же имя из прошлых прогонов. Раньше это давало ложный
  // "already_built" и намертво блокировало легитимный повторный запуск после удаления
  // текущей "` 1v" — подтверждено вживую 2026-09-10.
  try {
    const contents = await callClassicTool(inspectionTools.get_bin_contents, {
      bin_id: BIN_NAME, recursive: true,
    });
    const stack = [...(contents.items || [])];
    while (stack.length > 0) {
      const item = stack.pop();
      if (item.name === verticalName) return true;
      if (item.children) stack.push(...item.children);
    }
    return false;
  } catch (e) {
    return false; // бин не прочитался — не блокируем прогон из-за этого
  }
}

// --- Развод V1/V2: применить Motion Scale=140 на клип (component AE.ADBE Motion) ---
async function setClipMotionScale(clipIndex) {
  // Абсолютный set_value — идемпотентен, поэтому здесь безопасно повышенное число попыток
  // (8/500мс вместо глобальных 3) — этот вызов на практике флакует чаще, чем остальные
  // (2026-09-10, живой баг на "1. Снайперы ` 1v": 3 попыток не хватало на нескольких клипах
  // подряд сразу после переключения вкладки секвенции).
  const first = await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "set_value", media_type: "video", track_index: 0, clip_index: clipIndex,
    component_index: 1, param_index: 1, value: SCALE,
  }, 8);
  if (first.paramName === "Scale Height") {
    // Motion уже несимметричен после ресайза 16:9->9:16 (артефакт scale-to-frame,
    // см. инструкцию) — param_index=1 адресует уже не общий Scale, а Height; дополнительно
    // выставляем Width на тот же component, иначе кадр останется растянут по одной оси.
    await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
      action: "set_value", media_type: "video", track_index: 0, clip_index: clipIndex,
      component_index: 1, param_index: 2, value: SCALE,
    }, 8);
    await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
      action: "set_value", media_type: "video", track_index: 0, clip_index: clipIndex,
      component_index: 1, param_index: 3, value: SCALE,
    }, 8);
  }
}

async function setPositionsBatched(items) {
  // set_clip_properties_batch принимает максимум 16 элементов за вызов.
  for (let i = 0; i < items.length; i += 16) {
    await callClassicTool(competitorGapTools.set_clip_properties_batch, {
      items: items.slice(i, i + 16),
    });
  }
}

async function buildVerticalForSequence(name, projectDir) {
  // --- Рендер и его длительность — до любых мутаций секвенции. Ищем рекурсивно под папкой
  // проекта — секвенция лежит в "#Processing" плоско, без бина "Серия N" в имени. ---
  const renderPath = findFileRecursive(projectDir, `${name} \` 1h.mp4`);
  if (!renderPath) {
    console.log(`  -> ПРОПУСК: не нашёл рендер "${name} \` 1h.mp4" нигде под "${projectDir}" — отрендерить сначала.`);
    return { skipped: true, reason: "no_render" };
  }
  const seriesBinName = path.basename(path.dirname(renderPath));

  // --- sequenceId активной секвенции — нужен для duplicate_sequence (по имени можно
  // ошибиться при неуникальных именах, см. предупреждение в premiere-lib.mjs). ---
  const active = await callClassicTool(discoveryTools.get_active_sequence, {});
  const sequenceId = active.id;

  let info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const renderDur = await ffprobeDuration(renderPath);
  if (Math.abs(renderDur - info.durationSeconds) > RENDER_DURATION_TOLERANCE_S) {
    console.log(`  -> ПРОПУСК: рендер устарел (рендер ${renderDur.toFixed(2)}с, секвенция ` +
      `${info.durationSeconds.toFixed(2)}с) — перерендерить и повторить.`);
    return { skipped: true, reason: "stale_render", renderDur, seqDur: info.durationSeconds };
  }

  // --- Настоящие видеопереходы (не loop-хвост) — не реализовано, см. заголовок файла ---
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
    console.log(`  -> ПРОПУСК: настоящий видеопереход не у конца таймлайна ` +
      `(${otherTransitions.length} прочих, ${loopTailTransitions.length} у конца) — ` +
      `правило 2а инструкции не реализовано, обработайте вручную.`);
    return { skipped: true, reason: "transitions_not_implemented" };
  }

  // --- Шаг 1: SED строго первый, на ОРИГИНАЛЬНОЙ горизонтальной секвенции (уже активна) ---
  await callClassicTool(selectionTools.deselect_all_clips, {});
  await callClassicTool(selectionTools.select_all_clips, { track_type: "video" });
  await callClassicTool(advancedTools.scene_edit_detection, {
    action: "ApplyCuts", sensitivity: "MediumSensitivity", apply_cuts_to_linked_audio: false,
  });

  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const v1Clips = info.videoTracks[0].clips.slice().sort((a, b) => a.startSeconds - b.startSeconds);
  const cuts = [...v1Clips.map((c) => c.startSeconds), info.durationSeconds];

  // --- Шаг 2: анализ кадрирования (vreframe_sed.py, автономный, без Premiere) ---
  const slug = name.replace(/[\\/:*?"<>|`]/g, "_");
  const tmpDir = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), `verticals-${slug}-`));
  const cutsPath = path.join(tmpDir, "cuts.json");
  fs.writeFileSync(cutsPath, JSON.stringify(cuts));
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const outPath = path.join(OUT_DIR, `${name} \` 1v.json`);
  try {
    await runVreframeSed(renderPath, cutsPath, outPath);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
  const analysis = JSON.parse(fs.readFileSync(outPath, "utf-8"));
  const plan = analysis.clips.slice().sort((a, b) => a.start - b.start);
  if (plan.length !== v1Clips.length) {
    console.log(`  -> ПРОПУСК: vreframe_sed.py вернул ${plan.length} клипов, а на V1 их ` +
      `${v1Clips.length} — расхождение, не продолжаю вслепую.`);
    return { skipped: true, reason: "clip_count_mismatch", planLen: plan.length, v1Len: v1Clips.length };
  }

  // --- Мелкие "умные сцены" (обычно 1-2 кадра — SED-артефакт где-то в середине, либо
  // loop-хвост от 4.0. Looping.mjs) — анализ кадрирования по паре кадров ненадёжен и даёт
  // случайный crop, что в готовой вертикалке выглядит как дёрганый мелкий клип с чужим
  // кадрированием (жалоба Saturni, 2026-09-10). Приравниваем crop такой группы к соседней
  // (более длинной) — приоритет ПРЕДЫДУЩЕЙ, для мелкой группы в самом начале секвенции
  // берём следующую. Правки только на уровне плана (JSON), физические клипы на таймлайне
  // не трогаем — резать/сращивать их напрямую рискованно (см. живой эксперимент в истории
  // чата: transform_track_item_uxp без ripple создаёт оверлап, roll_edit отказывается
  // схлопывать клип до 0 длины).
  const MIN_SCENE_SECONDS = 3 * FRAME_SECONDS; // короче — считаем мусорным артефактом
  const groupOrder = [];
  const groupSpan = new Map(); // smart_scene -> {start, end}
  for (const p of plan) {
    if (!groupSpan.has(p.smart_scene)) {
      groupSpan.set(p.smart_scene, { start: p.start, end: p.end });
      groupOrder.push(p.smart_scene);
    } else {
      const g = groupSpan.get(p.smart_scene);
      g.start = Math.min(g.start, p.start);
      g.end = Math.max(g.end, p.end);
    }
  }
  for (let gi = 0; gi < groupOrder.length; gi++) {
    const sc = groupOrder[gi];
    const g = groupSpan.get(sc);
    if (g.end - g.start >= MIN_SCENE_SECONDS) continue;
    const donorSc = gi > 0 ? groupOrder[gi - 1] : groupOrder[gi + 1];
    if (donorSc === undefined) continue; // единственная группа на всю секвенцию — оставляем как есть
    const donorX = plan.find((p) => p.smart_scene === donorSc).static_x_norm;
    for (const p of plan) if (p.smart_scene === sc) p.static_x_norm = donorX;
    console.log(`  Мелкая умная сцена #${sc} (${(g.end - g.start).toFixed(3)}с) — crop приравнен к соседней #${donorSc}.`);
  }

  // --- Loop-хвост (последний клип на V1, ~1 кадр, дубль первого клипа от 4.0. Looping.mjs) —
  // ОТДЕЛЬНОЕ жёсткое правило поверх общей логики выше: crop дубля должен ВСЕГДА совпадать
  // именно с crop самого первого клипа секвенции (не с соседним клипом перед ним), иначе
  // луп дёргается на стыке конец→начало — Saturni, 2026-09-10. Общая логика "мелкая сцена
  // = crop соседа" этого не гарантирует (соседом дубля обычно является предпоследний клип,
  // а не первый), поэтому здесь принудительно переопределяем ещё раз. ---
  const lastV1Clip = v1Clips[v1Clips.length - 1];
  if (lastV1Clip.durationSeconds <= 1.5 * FRAME_SECONDS && plan.length >= 2) {
    const lastScene = plan[plan.length - 1].smart_scene;
    const firstX = plan[0].static_x_norm;
    for (const p of plan) if (p.smart_scene === lastScene) p.static_x_norm = firstX;
    console.log(`  Loop-хвост — crop принудительно приравнен к самому первому клипу секвенции.`);
  }

  // --- Правило: если умная сцена накрыта видеопереходом (началом, концом или целиком —
  // в реальном материале это, как правило, loop-хвост от 4.0. Looping.mjs, который
  // vreframe_sed.py обычно сливает с предыдущим клипом В ОДНУ умную сцену, а не оставляет
  // границей между двумя разными — поэтому проверяем пересечение с переходом у КАЖДОЙ
  // сцены отдельно, а не только "на стыке двух групп"), она принудительно остаётся на V1,
  // а чётность V1/V2 для дальнейших сцен считается заново от неё (Saturni, 2026-09-10).
  // Переопределяет track, изначально расставленный vreframe_sed.py по чистой чётности
  // индекса умной сцены. ---
  let nextIsV2 = false;
  for (let gi = 0; gi < groupOrder.length; gi++) {
    const sc = groupOrder[gi];
    const g = groupSpan.get(sc);
    const touchesTransition = allTransitions.some((tr) =>
      tr.startSeconds < g.end + FRAME_SECONDS / 2 && tr.endSeconds > g.start - FRAME_SECONDS / 2);
    let track;
    if (touchesTransition) {
      track = "V1";
      nextIsV2 = false; // отсчёт начинается заново: следующая сцена снова кандидат на V1
      console.log(`  Умная сцена #${sc} накрыта видеопереходом — принудительно на V1, отсчёт V1/V2 сброшен.`);
    } else {
      track = nextIsV2 ? "V2" : "V1";
      nextIsV2 = !nextIsV2;
    }
    for (const p of plan) if (p.smart_scene === sc) p.track = track;
  }

  // --- Шаг 3: дубликат секвенции + ресайз 1080x1920 ---
  // ВАЖНО (Saturni, 2026-09-10, настоящий корень "ресайз-бага" ниже): раньше искали свежий
  // дубль по имени (`find_project_item_by_name({name: "<name> Copy"})`) — та же болезнь, что
  // была у alreadyBuilt() до фикса: ищет по ВСЕМУ проекту, а не только среди только что
  // созданного. Живой эксперимент подтвердил: `seq.clone()` кладёт копию в КОРЕНЬ ПРОЕКТА, а
  // НЕ в бин оригинала (несмотря на интуицию) — и в этом проекте от прошлых упавших/тестовых
  // прогонов там же валяются osиротевшие "<name> Copy" (скрипт падал ПОСЛЕ clone(), но ДО
  // rename). find_project_item_by_name("<name> Copy") мог схватить ОДИН ИЗ НИХ вместо
  // реального нового дубля — тогда весь Шаг 3 работал не с той секвенцией, а настоящий новый
  // дубль оставался горизонтальным и неучтённым (это и было "ресайз не сохраняется"). Находим
  // новый элемент надёжно — diff'ом КОРНЯ ПРОЕКТА (list_project_items, туда падает клон) до/
  // после duplicate_sequence, без всякого поиска по имени.
  const beforeClone = await callClassicTool(discoveryTools.list_project_items, {});
  const beforeIds = new Set((beforeClone || []).map((it) => it.nodeId));
  await callClassicTool(sequenceTools.duplicate_sequence, { sequence_id: sequenceId });
  const afterClone = await callClassicTool(discoveryTools.list_project_items, {});
  const newItems = (afterClone || []).filter((it) => !beforeIds.has(it.nodeId));
  if (newItems.length !== 1) {
    throw new Error(
      `После duplicate_sequence ожидали ровно 1 новый элемент в корне проекта, нашли ` +
      `${newItems.length} (${newItems.map((i) => i.name).join(", ")}) — не продолжаю вслепую, ` +
      `проверьте вручную (возможно, скопились осиротевшие "<name> Copy" от прошлых упавших ` +
      `прогонов — удалите их).`
    );
  }
  const copyItem = newItems[0];
  const newName = `${name} \` 1v`;
  await callClassicTool(utilityTools.rename_project_item, { item_id: copyItem.nodeId, new_name: newName });
  const vBinNodeId = await ensureVBin(seriesBinName);
  await callClassicTool(mediaTools.move_item_to_bin, { item_id: copyItem.nodeId, target_bin: vBinNodeId });

  // sequenceID резолвим НАПРЯМУЮ по nodeId project item (copyItem — уже железно правильный,
  // найден выше через diff бина), а НЕ через set_active_sequence(newName) — та же болезнь с
  // поиском по имени (см. комментарий у diff-фикса выше). Сырой ExtendScript через сопоставление
  // seq.projectItem.nodeId — единственный надёжный способ связать project item с sequenceID.
  const dupGuid = (await callClassic(`
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      var seq = app.project.sequences[i];
      try {
        if (seq.projectItem && seq.projectItem.nodeId === "${escapeForExtendScript(copyItem.nodeId)}") {
          return __result({ id: seq.sequenceID });
        }
      } catch (e) {}
    }
    return __error("Секвенция для project item nodeId ${escapeForExtendScript(copyItem.nodeId)} не найдена в app.project.sequences.");
  `)).id;
  await callClassicTool(projectTools.set_active_sequence, { sequence_id: dupGuid });
  // automate_effect_parameters_uxp (и другие UXP-тулы без sequence_id) работают по секвенции,
  // реально ОТКРЫТОЙ на вкладке Timeline в UI — а не по classic-DOM activeSequence, которую
  // мы только что переключили выше. Без этого шага они продолжают адресовать предыдущую
  // (открытую) секвенцию, что даёт "The script object is no longer valid." на несовпадающих
  // индексах клипов (2026-09-09, живой баг на "1. Снайперы").
  // РЕСАЙЗ (Saturni, 2026-09-10, живой баг — до конца не побеждён, см. подробности ниже).
  // Наблюдалось многократно: и manage_sequence_settings_uxp (UXP), и классический
  // set_sequence_resolution иногда репортят success и ДАЖЕ подтверждаются немедленным
  // readback'ом внутри ЭТОГО ЖЕ процесса — но по факту секвенция остаётся горизонтальной
  // при проверке из свежего процесса/сессии. Похоже на ту же природу, что и остальные
  // "the script object is no longer valid" баги этой сессии: classic-DOM ссылка на только
  // что созданный/переименованный/перемещённый project item ещё не устаканилась к моменту
  // вызова. Смягчаем паузой ПЕРЕД ресайзом (в дополнение к обычной паузе после) и повтором
  // set_active_sequence на каждой попытке — полностью не устраняет проблему (замечена даже
  // после этого фикса), но снижает частоту. Финальный readback обязателен, падаем явной
  // ошибкой, если не подтвердилось — тихая порча результата хуже явного облома.
  await new Promise((r) => setTimeout(r, 1000));
  let resizeOk = false;
  for (let attempt = 1; attempt <= 3 && !resizeOk; attempt++) {
    await callClassicTool(projectTools.set_active_sequence, { sequence_id: dupGuid });
    await callClassicTool(utilityTools.set_sequence_resolution, { width: SEQ_W, height: SEQ_H });
    await new Promise((r) => setTimeout(r, 1000 * attempt));
    const afterResize = await callClassicTool(inspectionTools.get_full_sequence_info, { sequence_id: dupGuid });
    resizeOk = afterResize.width === SEQ_W && afterResize.height === SEQ_H;
    if (!resizeOk) {
      console.log(`  (ресайз не подтвердился с попытки ${attempt}/3 — по факту ` +
        `${afterResize.width}x${afterResize.height}, пробую ещё раз...)`);
    }
  }
  if (!resizeOk) {
    throw new Error(
      `Ресайз секвенции "${newName}" (id ${dupGuid}) не подтвердился после 3 попыток — ожидали ` +
      `${SEQ_W}x${SEQ_H}. Известный неустранённый баг (см. комментарий выше) — попробуйте ` +
      `перезапустить скрипт заново или сделать ресайз вручную в Premiere и продолжить руками.`
    );
  }
  await callUxpTool(uxpAdvTools.manage_sequences_uxp, { action: "open", sequence_id: dupGuid });
  // Даём мосту CEP/UXP "устаканиться" после переключения вкладки + ресайза, прежде чем
  // начинать частые per-clip вызовы automate_effect_parameters_uxp (2026-09-09, живой баг).
  await new Promise((r) => setTimeout(r, 1500));

  // --- Шаг 5 (сначала!) — Motion Scale 140 + Position на каждый клип, пока все на одной
  // дорожке (адресация по track 0 / clip_index проще — см. инструкцию) ---
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const dupClips = info.videoTracks[0].clips.slice().sort((a, b) => a.startSeconds - b.startSeconds);
  const round3 = (x) => Math.round(x * 1000) / 1000;
  const positionItems = [];
  for (let i = 0; i < dupClips.length; i++) {
    const clip = dupClips[i];
    const planEntry = plan.find((p) => round3(p.start) === round3(clip.startSeconds));
    if (!planEntry) {
      console.log(`  ⚠ Не нашёл в плане клип, начинающийся на ${clip.startSeconds.toFixed(3)}с — пропускаю его Motion.`);
      continue;
    }
    await setClipMotionScale(i);
    positionItems.push({ node_id: clip.nodeId, position_x: planEntry.static_x_norm, position_y: 0.5 });
  }
  await setPositionsBatched(positionItems);
  console.log(`  -> Motion Scale ${SCALE} + Position выставлены на ${dupClips.length} клипов.`);

  // --- Шаг 4 — развод чётных умных сцен на V2 ---
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const freshClips = info.videoTracks[0].clips.slice().sort((a, b) => a.startSeconds - b.startSeconds);
  const v2NodeIds = [];
  for (let i = 0; i < freshClips.length; i++) {
    const planEntry = plan.find((p) => round3(p.start) === round3(freshClips[i].startSeconds));
    if (planEntry && planEntry.track === "V2") v2NodeIds.push(freshClips[i].nodeId);
  }

  if (v2NodeIds.length > 0) {
    await callClassicTool(selectionTools.deselect_all_clips, {});
    for (const id of v2NodeIds) {
      await callClassicTool(advancedTools.set_clip_selection, { node_id: id, selected: true });
    }
    const selected = await callClassicTool(discoveryTools.get_selected_clips, {});
    if (selected.length !== v2NodeIds.length) {
      console.log(`  ⚠ Выделено ${selected.length} клипов вместо ожидаемых ${v2NodeIds.length} — ` +
        `продолжаю, но проверь результат вручную.`);
    }
    // Тот же флаки-мост, что и в setClipMotionScale — повышенный retry (8 вместо 3),
    // вызов на практике либо полностью проходит, либо полностью отклоняется до мутации
    // (не было ни разу замечено частичного клонирования при повторе), см. заголовок файла
    // (Saturni, 2026-09-10).
    await callUxpTool(uxpAdvTools.edit_timeline_uxp, {
      action: "clone_selection", video_track_offset: 1, time_offset_seconds: 0,
    }, 8);
    await callUxpTool(uxpTools.lift_selection_uxp, { expected_sequence_guid: dupGuid }, 8);
    console.log(`  -> ${v2NodeIds.length} клипов разведены на V2.`);
  } else {
    console.log(`  -> Ни одного клипа на V2 не потребовалось (одна умная сцена на всю секвенцию).`);
  }

  return { skipped: false, clips: dupClips.length, v2: v2NodeIds.length, verticalName: newName };
}

async function applyVerticalToActiveSequence(name, projectDir) {
  if (name === "c") {
    console.log(`  -> ПРОПУСК: служебная секвенция "c".`);
    return { skipped: true, reason: "reserved_name" };
  }
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  if (info.height >= info.width) {
    console.log(`  -> ПРОПУСК: не горизонтальная (${info.width}x${info.height}) — уже вертикалка.`);
    return { skipped: true, reason: "not_horizontal" };
  }
  if (await alreadyBuilt(`${name} \` 1v`)) {
    console.log(`  -> ПРОПУСК: "${name} \` 1v" уже существует.`);
    return { skipped: true, reason: "already_built" };
  }

  const result = await buildVerticalForSequence(name, projectDir);
  if (!result.skipped) {
    await callClassicTool(projectTools.save_project, {});
  }
  return result;
}

async function main() {
  const projectInfo = await callClassicTool(discoveryTools.get_project_info, {});
  const projectDir = path.dirname(projectInfo.path);

  const results = await runPipeline({
    binName: BIN_NAME,
    applyFn: (name) => applyVerticalToActiveSequence(name, projectDir),
  });

  console.log("\nИтог:");
  results.forEach((r) => {
    if (r.result.skipped) console.log(`  - ${r.name}: пропущена (${r.result.reason})`);
    else console.log(`  - ${r.name}: собрана -> "${r.result.verticalName}" (${r.result.clips} клипов, ${r.result.v2} на V2)`);
  });
  console.log("\nНапоминание: проект сохраняется автоматически после каждой собранной секвенции, " +
    "но финальную проверку и Ctrl+S после отсмотра всё равно сделать самому.");
}

async function waitForEnter(promptText) {
  process.stdout.write(promptText);
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once("data", resolve);
  });
}

async function reportFatal(label, err) {
  console.error("\n\n========================================");
  console.error(`ОШИБКА (${label}) — скрипт остановился.`);
  console.error("========================================");
  console.error(err && err.stack ? err.stack : err);
  console.error("========================================");
  try { await shutdown(); } catch (e) { /* соединение и так уже нерабочее */ }
  await waitForEnter("\nНажми Enter, чтобы закрыть окно...");
  process.exit(1);
}

process.on("unhandledRejection", (err) => reportFatal("необработанное исключение внутри промиса", err));

try {
  await main();
  await shutdown();
} catch (err) {
  await reportFatal("исключение в main()", err);
}
