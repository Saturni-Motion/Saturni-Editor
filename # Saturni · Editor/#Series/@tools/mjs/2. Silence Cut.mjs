#!/usr/bin/env node
// Автономный запуск этапа 2 (вырезание пауз и филлеров, см. @instructions/2. Silence Cut.md)
// без Claude — напрямую через @tools/@Premiere Lib.mjs, тем же способом, что 4.0. Looping.mjs и
// 4.2. Background Blur.mjs. Пауза детектируется отдельным Python-скриптом (2. Pause Analyze.py — Demucs
// вокал-изоляция + Silero VAD, без ручного порога dB), сам рез идёт через
// razor_all_tracks + remove_selected_clips(ripple:true) — стандартная механика Premiere,
// не XML-пересборка.
//
// Проверено вживую (2026-09-08) на одной секвенции — работает. Резервная копия — штатный
// механизм runPipeline/backupBin из @tools/@Premiere Lib.mjs: перед стартом весь бин "~"
// клонируется по папкам в "~/⿻/<папка> - ДД.ММ.ГГ ЧЧ:ММ:СС" (та же механика, что и у
// 4.0. Looping.mjs/4.2. Background Blur.mjs) — отдельной копии-референса внутри самой секвенции не
// делаем, сравнивать «было/стало» — через этот бэкап-бин.
//
// ВАЖНО: нельзя запускать одновременно с открытой сессией Claude Code, использующей
// premiere-pro MCP-сервер — оба процесса конкурируют за один и тот же UXP WebSocket порт.
//
// Если что-то падает — окно консоли САМО НЕ ЗАКРОЕТСЯ: печатает "ОШИБКА" со стеком и ждёт
// Enter. Успешное завершение закрывается как раньше, без задержки.
//
// Обычный запуск — через лаунчер "2. Silence Cut.py" в корне проекта (двойной клик,
// статус-бар). Прямой запуск этого файла (для отладки, из корня проекта):
//   node "@tools/mjs/2. Silence Cut.mjs"                          -> все секвенции в бине "~"
//   node "@tools/mjs/2. Silence Cut.mjs" "Имя секвенции 1" "..."   -> только перечисленные
//   Флаги (перед именами секвенций, если есть):
//     --min-kept 0.5        минимальная длина оставленного кусочка речи, сек
//     --min-silence-ms 300  паузы короче не считаются отдельной паузой
//     --pad-start-ms 40     запас ПЕРЕД началом речи (меньше — резче старт)
//     --pad-end-ms 150      запас ПОСЛЕ конца речи (больше — не режет хвост слова)
//
// Перед запуском: сложить утверждённые (после этапа 1) горизонтальные секвенции-моменты
// в бин "~" в Premiere самому — скрипт сам их найдёт и обработает все.
//
// Защищённые клипы (не резать внутри): поставить маркер ПРЯМО НА ИСХОДНИКЕ (через Source
// Monitor — открыть e4.mov/e5.mov, встать на нужное место, `M`) где-то внутри диапазона
// нужного V1-клипа — весь этот клип целиком пропускается, пауза внутри него не ищется и не
// режется. Остальные клипы до/после — режутся как обычно. ВАЖНО: это маркер ИСХОДНОГО
// КЛИПА (`get_clip_markers`, координаты в системе времени самого файла-исходника — те же
// секунды, что inPointSeconds/outPointSeconds клипа), НЕ маркер секвенции (тот привязан к
// таймлайну текущей секвенции и её собственным координатам, это разные вещи в Premiere) —
// маркер секвенции скрипт не проверяет вообще.

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  inspectionTools, advancedTools, selectionTools, trackTargetingTools, utilityTools,
  callClassic, callClassicTool, runPipeline, runCli, stage, checkResultsForFailures, FRAME_SECONDS,
} from "./@Premiere Lib.mjs";
import { readFileSync as __readFileSync } from "node:fs";
const FADES_JSX = __readFileSync(new URL("../1+2/audio_fades.jsx", import.meta.url), "utf8");

const BIN_NAME = "~";
// Секунды, для сопоставления сливеров после razor по startSeconds/endSeconds. ВАЖНО: razor
// снапает каждый рез к ближайшему кадру независимо, а cutGap() режет ДВА раза (gapEnd, потом
// gapStart) — расхождение с запрошенными координатами может накопиться до целого кадра
// (по полкадра на каждый рез), не полкадра. Раньше здесь стояло 0.02 (= половина кадра при
// 25fps) — из-за этого "иногда" (когда обоим резам не повезло) findSliverNodeIds ничего не
// находил, и разрезанный, но не удалённый кусок оставался в таймлайне (баг, 2026-09-09).
const TOLERANCE = FRAME_SECONDS + 0.005;

const HERE = path.dirname(fileURLToPath(import.meta.url));
// HERE — теперь @tools/mjs/ (файл переехал сюда из корня проекта, 2026-09-11) —
// 2. Pause Analyze.py лежит на уровень выше (@tools/).
const ANALYZE_SCRIPT = path.join(HERE, "..", "2. Pause Analyze.py");

// --- CLI: числовые флаги (общие для всех клипов прогона) + опциональный явный список имён ---
const rawArgs = process.argv.slice(2);
const opts = { minKept: 0.4, minSilenceMs: 200, padStartMs: 10, padEndMs: 60 };
const seqNames = [];
for (let i = 0; i < rawArgs.length; i++) {
  const a = rawArgs[i];
  if (a === "--min-kept") opts.minKept = parseFloat(rawArgs[++i]);
  else if (a === "--min-silence-ms") opts.minSilenceMs = parseInt(rawArgs[++i], 10);
  else if (a === "--pad-start-ms") opts.padStartMs = parseInt(rawArgs[++i], 10);
  else if (a === "--pad-end-ms") opts.padEndMs = parseInt(rawArgs[++i], 10);
  else seqNames.push(a);
}
process.argv = [process.argv[0], process.argv[1], ...seqNames]; // resolveTargets() в premiere-lib читает голые имена

function runPythonAnalyze(video, inS, outS) {
  // Демукс/ffmpeg внутри 2. Pause Analyze.py печатают много (прогресс-бары, команды) — не
  // пробрасываем это в консоль вживую, копим молча и печатаем только компактную сводку по
  // готовому результату; полный лог сохраняется только на случай ошибки (ниже, в reject).
  return new Promise((resolve, reject) => {
    const proc = spawn("python", [
      ANALYZE_SCRIPT, "--video", video, "--in", String(inS), "--out", String(outS),
      "--min-kept", String(opts.minKept),
      "--min-silence-ms", String(opts.minSilenceMs),
      "--pad-start-ms", String(opts.padStartMs),
      "--pad-end-ms", String(opts.padEndMs),
    ]);
    let out = "", err = "";
    proc.stdout.on("data", (d) => { out += d.toString(); });
    proc.stderr.on("data", (d) => { err += d.toString(); });
    proc.on("close", (code) => {
      if (code !== 0) return reject(new Error(`2. Pause Analyze.py exited ${code}:\n${out}\n${err}`));
      // 2. Pause Analyze.py печатает лог-строки (через subtitles_pipeline.run()) вперемешку
      // с итоговым JSON — JSON гарантированно последняя непустая строка stdout.
      const lines = out.trim().split("\n");
      const last = lines[lines.length - 1];
      try { resolve(JSON.parse(last)); }
      catch (e) { reject(new Error(`Не разобрал JSON от 2. Pause Analyze.py:\n${out}\n${err}`)); }
    });
    proc.on("error", reject);
  });
}

const clipMarkersCache = new Map(); // sourceNodeId -> markers[], чтобы не читать один и тот же источник по многу раз

async function getSourceMarkers(sourceNodeId) {
  if (clipMarkersCache.has(sourceNodeId)) return clipMarkersCache.get(sourceNodeId);
  let markers = [];
  try {
    const data = await callClassicTool(utilityTools.get_clip_markers, { item_id: sourceNodeId });
    markers = data.markers ?? [];
  } catch (e) {
    markers = []; // у исходника нет маркеров вообще — не защищено, режем как обычно
  }
  clipMarkersCache.set(sourceNodeId, markers);
  return markers;
}

async function isProtected(clip) {
  // Координаты маркера — в системе времени ИСХОДНИКА (та же, что inPointSeconds/
  // outPointSeconds клипа), не таймлайна секвенции. Защищает, если попадает внутрь
  // диапазона [inPointSeconds, outPointSeconds] этого конкретного клипа.
  const markers = await getSourceMarkers(clip.sourceNodeId);
  return markers.some((m) => m.startSeconds >= clip.inPointSeconds && m.startSeconds <= clip.outPointSeconds);
}

async function findSliverNodeIds(gapStart, gapEnd) {
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const ids = [];
  const within = (c) => Math.abs(c.startSeconds - gapStart) < TOLERANCE
    && Math.abs(c.endSeconds - gapEnd) < TOLERANCE;
  for (const t of info.videoTracks) for (const c of t.clips) if (within(c)) ids.push(c.nodeId);
  for (const t of info.audioTracks) for (const c of t.clips) if (within(c)) ids.push(c.nodeId);
  return { ids, info };
}

async function cutGap(gapStart, gapEnd) {
  await callClassicTool(trackTargetingTools.razor_all_tracks, { time_seconds: gapEnd, track_type: "both" });
  await callClassicTool(trackTargetingTools.razor_all_tracks, { time_seconds: gapStart, track_type: "both" });
  const { ids, info } = await findSliverNodeIds(gapStart, gapEnd);
  if (ids.length === 0) {
    // Диагностика: если это снова случится (расхождение больше кадра — не должно после фикса
    // 2026-09-09, TOLERANCE = FRAME_SECONDS), печатаем ближайший реальный клип на V1, чтобы
    // видно было, насколько именно razor разошёлся с запрошенными координатами.
    const nearest = info.videoTracks[0]?.clips
      .map((c) => ({ c, d: Math.abs(c.startSeconds - gapStart) + Math.abs(c.endSeconds - gapEnd) }))
      .sort((a, b) => a.d - b.d)[0];
    const near = nearest
      ? ` (ближайший клип на V1: [${nearest.c.startSeconds.toFixed(3)}, ${nearest.c.endSeconds.toFixed(3)}], разошлось на ${nearest.d.toFixed(3)}с)`
      : "";
    console.log(`    ! не нашёл сливер [${gapStart.toFixed(2)}, ${gapEnd.toFixed(2)}] после razor — пропускаю${near}`);
    return;
  }
  await callClassicTool(selectionTools.deselect_all_clips, {});
  for (const id of ids) {
    await callClassicTool(advancedTools.set_clip_selection, { node_id: id, selected: true });
  }
  await callClassicTool(trackTargetingTools.remove_selected_clips, { ripple: true });
}

async function applyPauseCutToActiveSequence(name) {
  stage(name, "Scanning");
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const v1Clips = info.videoTracks[0].clips.slice().sort((a, b) => a.startSeconds - b.startSeconds);
  if (v1Clips.length === 0) {
    return { skipped: true, reason: "empty_v1" };
  }

  console.log(`  ${v1Clips.length} клип(ов) на V1, анализирую паузы (Demucs + Silero VAD)...`);

  stage(name, "Analyzing");
  const allGaps = [];
  for (const clip of v1Clips) {
    if (await isProtected(clip)) {
      console.log(`  [${clip.startSeconds.toFixed(2)}-${clip.endSeconds.toFixed(2)}] защищён маркером на исходнике — пропускаю`);
      continue;
    }
    const result = await runPythonAnalyze(
      clip.sourceMediaPath, clip.inPointSeconds, clip.outPointSeconds
    );
    console.log(`  [${clip.startSeconds.toFixed(2)}-${clip.endSeconds.toFixed(2)}] ${result.removed.length} пауз(ы)`);
    for (const [srcS, srcE] of result.removed) {
      allGaps.push({
        start: clip.startSeconds + (srcS - clip.inPointSeconds),
        end: clip.startSeconds + (srcE - clip.inPointSeconds),
      });
    }
  }
  console.log(`  Всего пауз к вырезанию: ${allGaps.length}`);

  stage(name, "Cutting");
  // Резать строго справа налево — иначе более ранние правки сдвигают ещё не
  // обработанные тайм-коды дальше по таймлайну (та же логика, что и в 4.0. Looping.mjs).
  allGaps.sort((a, b) => b.start - a.start);
  for (const gap of allGaps) {
    await cutGap(gap.start, gap.end);
  }
  console.log(`  Порезано.`);

  // Аудиопереход Constant Power 2 кадра на каждой склейке звука и в начале/конце (так делает Saturni).
  stage(name, "Audio fades");
  const fadeRes = await callClassic(FADES_JSX + "\nreturn __result(fades(app.project.activeSequence, [0, 1], 2));");
  console.log(`  Аудиопереходы: ${JSON.stringify(fadeRes)}`);

  return { cutsMade: allGaps.length };
}

// Если что-то упало — окно консоли не должно молча закрыться (типичная беда при запуске
// двойным кликом/из ярлыка: процесс падает, окно тут же схлопывается, ошибку прочитать не
// успеваешь). Это теперь делает общий runCli() из @Premiere Lib.mjs (см. хвост файла) — тот
// же паттерн, что и у 4.0-4.3.
async function main() {
  console.log(`Параметры: min-kept=${opts.minKept}с, min-silence=${opts.minSilenceMs}мс, ` +
    `pad-start=${opts.padStartMs}мс, pad-end=${opts.padEndMs}мс\n`);
  // seq_done эмиттится сразу по каждой секвенции внутри runPipeline() (deferDone по
  // умолчанию false — доп. прохода после основного цикла тут нет).
  const results = await runPipeline({ binName: BIN_NAME, applyFn: applyPauseCutToActiveSequence });
  console.log("\nНапоминание: проект НЕ сохранён автоматически — сохранить вручную (Ctrl+S) после проверки.");
  checkResultsForFailures(results);
}

runCli(main);
