#!/usr/bin/env node
// Автономный запуск вертикальной адаптации (этап 4, см.
// @instructions/4.1. Smart Verticals.md) без пошагового участия Claude — та же
// инфраструктура и та же система, что у "2. Silence Cut.mjs" / "4.0. Looping.mjs" /
// "4.2. Background Blur.mjs": секвенции складываются в бин "~", скрипт сам
// бэкапит весь бин целиком перед стартом (через @tools/@Premiere Lib.mjs). ЗАПУСКАТЬ ПОСЛЕ
// "4.0. Looping.mjs" (Saturni, 2026-09-09) — если секвенция должна быть зациклена, петля
// должна быть уже собрана до вертикальной адаптации (см. обработку loop-хвоста ниже).
//
// Пайплайн на одну горизонтальную секвенцию: SED (строго первый шаг, без исключений —
// см. «ОБЯЗАТЕЛЬНЫЙ ЧЕК-ПОЙНТ» в инструкции) → @tools/4.1. VReframe-SED.py (анализ кадрирования
// по рендеру) → дубликат секвенции + ресайз 1080×1920 → Motion Scale 140 + Position на
// каждый клип (пока всё ещё на одной дорожке) → развод чётных умных сцен на V2
// (clone_selection + lift_selection_uxp).
//
// Рендер (`<name> \` 1h.mp4`) ищется рекурсивным обходом папки проекта (рядом с .prproj) —
// секвенция может лежать в "~" плоско, без привязки к бину "Серия N", поэтому
// путь к рендеру не выводится из имени бина. Бин "v" для готовой вертикалки создаётся/
// находится под тем же бином, где физически лежит найденный рендер (обычно "Серия N"); если
// это не удаётся (рендер найден, а такого бина в проекте нет) — "v" создаётся прямо под
// "~".
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
// Обычный запуск — через лаунчер "4.1. Smart Verticals.py" в корне проекта (двойной клик,
// статус-бар). Прямой запуск этого файла (для отладки, из корня проекта):
//   node "@tools/mjs/4.1. Smart Verticals.mjs"                    -> все горизонтальные секвенции в
//     бине "~" (кроме "c", кроме уже собранных 1v, кроме без рендера)
//   node "@tools/mjs/4.1. Smart Verticals.mjs" "4. Вещи" "5. Изгой" -> только перечисленные секвенции
//
// Перед запуском: сложить нужные горизонтальные секвенции в бин "~" в Premiere
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
  callClassicTool, callUxpTool, callClassic, escapeForExtendScript, withRetry,
  runPipeline, runCli, stage, checkResultsForFailures, FRAME_SECONDS, BACKUP_BIN_NAME,
  setParamsBatch, mediaAnalysisTools, listBinSequenceRefs, verifyError,
} from "./@Premiere Lib.mjs";

const BIN_NAME = "~";
const HERE = path.dirname(fileURLToPath(import.meta.url));
// HERE — теперь @tools/mjs/ (файл переехал сюда из корня проекта, 2026-09-11) —
// 4.1. VReframe-SED.py и "!verticals" оба на уровень выше (@tools/): Saturni
// попросил создавать "!verticals" в @tools, не в корне проекта (2026-09-11).
const VREFRAME_SCRIPT = path.join(HERE, "..", "4.1. VReframe-SED.py");
const OUT_DIR = path.join(HERE, "..", "!verticals");
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
// в "~" плоско, без бина "Серия N", поэтому путь к рендеру не выводим из бина. ---
// Все совпадения (для одноимённых роликов из разных папок: "18.09/X ` 1h.mp4" и "22.09/X ` 1h.mp4").
function findAllFilesRecursive(dir, filename, maxDepth = 6, depth = 0, out = []) {
  if (depth > maxDepth) return out;
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  for (const entry of entries) {
    if (entry.isFile() && entry.name === filename) out.push(path.join(dir, entry.name));
  }
  for (const entry of entries) {
    if (entry.isDirectory() && !entry.name.startsWith(".")) {
      findAllFilesRecursive(path.join(dir, entry.name), filename, maxDepth, depth + 1, out);
    }
  }
  return out;
}

// Рендер для секвенции (2026-09-24): при одинаковых именах в разных папках бина ("~/18.09",
// "~/22.09") раньше брался первый попавшийся файл — рендер другой даты. Теперь при нескольких
// совпадениях берём тот, в пути которого есть папка с именем папки бина; не нашли однозначно —
// ошибка, а не догадка.
// Файл, лежащий в дисковой папке ДРУГОЙ папки бина (рендер "18.09/X" для секвенции "22.09/X"),
// не подходит никогда — даже если он единственный (живой случай 2026-09-24: рендер 22.09 убрали
// с диска, и скрипт подхватил 18.09). ALL_BIN_FOLDERS — имена всех папок рабочего бина.
const ALL_BIN_FOLDERS = new Set();
// Бин "s1" = папка на диске "Серия 1"/"Series 1" (Мусор, 2026-10-29: рендеры "1.mp4" лежат в обеих).
const normSeg = (s) => s.toLowerCase().replace(/^(серия|series|s)\s*(?=\d+$)/, "s");
function findRenderFor(projectDir, filename, binFolder) {
  const all = findAllFilesRecursive(projectDir, filename);
  const own = new Set((binFolder || "").split("/").filter(Boolean).map(normSeg));
  const others = [...ALL_BIN_FOLDERS].map(normSeg).filter((f) => !own.has(f));
  const dirs = (f) => f.split(path.sep).slice(0, -1).map(normSeg);
  const valid = all.filter((f) => {
    const d = dirs(f);
    return [...own].some((s) => d.includes(s)) || !others.some((s) => d.includes(s));
  });
  if (valid.length <= 1) return { path: valid[0] || null, foreign: all.filter((f) => !valid.includes(f)) };
  const segs = [...own].reverse();
  for (const seg of segs) {
    const hits = valid.filter((f) => dirs(f).includes(seg));
    if (hits.length === 1) return { path: hits[0] };
  }
  return { path: null, ambiguous: valid };
}

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

// --- Бин "v" для готовых вертикалок — СВОЙ у каждой папки с горизонталками (Saturni,
// 2026-09-24): "~/Series 10/v", "~/Series 11/v"; горизонталка, лежащая прямо в "~", —
// в "~/v". Раньше (2026-09-22) был один общий "~/v" на весь прогон, и вертикалки разных
// серий сливались в одну кучу. Папка-родитель берётся строго по nodeId (target.binNodeId
// из listBinSequenceRefs), не по имени — одноимённые "Series N"/"v" в проекте встречаются.
// Внутри неё существующая "v" переиспользуется, иначе создаётся; кэш на прогон — одна "v"
// на папку, сколько бы вертикалок туда ни собралось. ---
const V_BIN_BY_PARENT = new Map();

// --- Повтор упавшей секвенции (Saturni, 2026-09-24): runPipeline() восстанавливает саму
// горизонталку из бэкапа, а недособранную "` 1v", которую успел создать этот прогон,
// убираем здесь — иначе alreadyBuilt() на повторе её увидит и пропустит секвенцию. Удаляем
// строго ту, что создали сами (по nodeId из этого прогона), не по имени. ---
const CREATED_DUP_BY_SEQ = new Map(); // sequenceId горизонталки -> nodeId созданной "` 1v" (не имя: имена повторяются)

async function dropHalfBuilt(target) {
  const nodeId = CREATED_DUP_BY_SEQ.get(String(target.sequenceId));
  if (!nodeId) return;
  await callClassic(`
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      var seq = app.project.sequences[i];
      try {
        if (seq.projectItem && seq.projectItem.nodeId === "${escapeForExtendScript(nodeId)}") {
          if (app.project.deleteSequence(seq) === false) return __error("Premiere не дал удалить недособранную вертикалку");
          return __result({ deleted: true });
        }
      } catch (e) {}
    }
    return __result({ deleted: false });
  `);
  CREATED_DUP_BY_SEQ.delete(String(target.sequenceId));
  console.log(`  Недособранная "${target.name} \` 1v" удалена перед повтором.`);
}

async function ensureVBin(parentBinNodeId) {
  if (V_BIN_BY_PARENT.has(parentBinNodeId)) return V_BIN_BY_PARENT.get(parentBinNodeId);
  const data = await callClassic(`
    function isBinItem(item) {
      return item.children !== undefined && item.children !== null;
    }
    function findByNodeId(parent, id) {
      for (var i = 0; i < parent.children.numItems; i++) {
        var item = parent.children[i];
        if (item.nodeId === id) return item;
        if (isBinItem(item)) {
          var found = findByNodeId(item, id);
          if (found) return found;
        }
      }
      return null;
    }
    var id = "${escapeForExtendScript(parentBinNodeId)}";
    var parent = app.project.rootItem.nodeId === id ? app.project.rootItem : findByNodeId(app.project.rootItem, id);
    if (!parent || !isBinItem(parent)) return __error("Папка-родитель не найдена по nodeId: " + id);
    for (var i = 0; i < parent.children.numItems; i++) {
      var child = parent.children[i];
      if (isBinItem(child) && child.name === "v") return __result({ nodeId: child.nodeId, created: false });
    }
    var bin = parent.createBin("v");
    if (!bin) return __error("createBin(\\"v\\") не сработал в папке: " + parent.name);
    return __result({ nodeId: bin.nodeId, created: true });
  `);
  V_BIN_BY_PARENT.set(parentBinNodeId, data.nodeId);
  return data.nodeId;
}

// Вертикалка этой горизонталки лежит в "v" её же папки — ищем только там (2026-09-24):
// поиск по всему "~" находил "18.09/v/X ` 1v" и ложно пропускал одноимённую "22.09/X".
async function alreadyBuiltInFolder(verticalName, parentBinNodeId) {
  const data = await callClassic(`
    function isBinItem(item) { return item.children !== undefined && item.children !== null; }
    function findByNodeId(parent, id) {
      for (var i = 0; i < parent.children.numItems; i++) {
        var item = parent.children[i];
        if (item.nodeId === id) return item;
        if (isBinItem(item)) { var f = findByNodeId(item, id); if (f) return f; }
      }
      return null;
    }
    var id = "${escapeForExtendScript(parentBinNodeId)}";
    var parent = app.project.rootItem.nodeId === id ? app.project.rootItem : findByNodeId(app.project.rootItem, id);
    if (!parent) return __result({ found: false });
    var name = "${escapeForExtendScript(verticalName)}";
    for (var i = 0; i < parent.children.numItems; i++) {
      var c = parent.children[i];
      if (c.name === name) return __result({ found: true });
      if (isBinItem(c) && c.name === "v") {
        for (var j = 0; j < c.children.numItems; j++) {
          if (c.children[j].name === name) return __result({ found: true });
        }
      }
    }
    return __result({ found: false });
  `);
  return !!data.found;
}

async function alreadyBuilt(verticalName) {
  // ВАЖНО: искать нужно только внутри поддерева BIN_NAME ("~"), НЕ по всему
  // проекту — find_project_item_by_name матчит вообще любой элемент с таким именем, а
  // старые авто-бэкапы регулярно содержат такое же имя из прошлых прогонов. Раньше это
  // давало ложный "already_built" и намертво блокировало легитимный повторный запуск
  // после удаления текущей "` 1v" — подтверждено вживую 2026-09-10.
  // Ветку склада бэкапов "⿻" пропускаем явно: штатно он лежит в корне проекта (вне "~") и
  // сюда не попадает, но если его перенесут внутрь "~" — баг вернулся бы в полном объёме.
  try {
    const contents = await callClassicTool(inspectionTools.get_bin_contents, {
      bin_id: BIN_NAME, recursive: true,
    });
    const stack = [...(contents.items || [])];
    while (stack.length > 0) {
      const item = stack.pop();
      if (item.type === "bin" && item.name === BACKUP_BIN_NAME) continue;
      if (item.name === verticalName) return true;
      if (item.children) stack.push(...item.children);
    }
    return false;
  } catch (e) {
    return false; // бин не прочитался — не блокируем прогон из-за этого
  }
}

// --- Развод V1/V2: применить Motion Scale=140 на клип (component AE.ADBE Motion) ---
// --- Геометрия вертикалки (Saturni, 2026-09-24) -----------------------------------------------
// ЭТАЛОН: исходник 1920x1080 на Scale 140 в кадре 1080x1920 -> видимая картинка 2688x1512,
// полосы по 204 px сверху/снизу. Для ЛЮБОГО исходника масштаб подбирается так, чтобы видимая
// картинка (без запечённых полос) была той же высоты REF_PICTURE_H = 1512 px — тогда доля полос
// одинаковая у всех роликов:
//     S = REF_PICTURE_H / activeH * 100,   activeH = codedH * (1 - 2*crop/100)
// 1080p -> 140; 4K -> 70; 1440p -> 105; 720p -> 210; нативно-широкий 1920x800 -> 189.
// Запечённые полосы (letterbox внутри кадра) режутся тут же, Crop Top/Bottom в Motion, тем же
// правилом, что в 4.2. (процент округляется вверх до 0,5) — Проход 2 в 4.2. даёт те же числа.
// ПОЛОЖЕНИЕ: 4.1. VReframe-SED.py находит цель в координатах рендера горизонтали (1920 px); точка
// рендера x_r переводится в точку исходника через масштаб h и позицию hx клипа В ГОРИЗОНТАЛИ
// (Saturni иногда двигает масштаб 4K-клипов), затем ставится в центр кадра 1080:
//     p = (540 - (x_r - hx*1920) * S / h) / 1080,  clamp так, чтобы по бокам не было пустоты.
// Для 1080p на 100/центр это ровно старая формула (540 - (x_r-960)*1.4)/1080.
const REF_PICTURE_H = (1080 * SCALE) / 100; // 1512

// Масштаб/позиция/медиа каждого клипа V1 горизонтали (после SED — клипы уже нарезаны).
async function readClipGeometry(sequenceId) {
  const data = await callClassic(`
    var seq = null;
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      if (String(app.project.sequences[i].sequenceID) === "${escapeForExtendScript(sequenceId)}") { seq = app.project.sequences[i]; break; }
    }
    if (!seq) return __error("Sequence not found by id: ${escapeForExtendScript(sequenceId)}");
    var out = [];
    var tr = seq.videoTracks[0];
    for (var c = 0; c < tr.clips.numItems; c++) {
      var clip = tr.clips[c], mot = null, sc = null, sh = null, pos = null, media = "";
      for (var k = 0; k < clip.components.numItems; k++) if (clip.components[k].matchName === "AE.ADBE Motion") mot = clip.components[k];
      if (mot) {
        for (var j = 0; j < mot.properties.numItems; j++) {
          var pr = mot.properties[j];
          try {
            if (pr.displayName === "Scale") sc = Number(pr.getValue());
            if (pr.displayName === "Scale Height") sh = Number(pr.getValue());
            if (pr.displayName === "Position") { var v = pr.getValue(); pos = Number(v[0]); }
          } catch (e) {}
        }
      }
      try { media = clip.projectItem.getMediaPath(); } catch (e) {}
      out.push({ start: clip.start.seconds, scale: sc !== null ? sc : sh, posX: pos, media: media });
    }
    return __result(out);
  `);
  const map = new Map();
  for (const c of data || []) map.set(Math.round(c.start * 1000) / 1000, c);
  return map;
}

// Размер исходника + запечённые полосы; кэш на прогон по пути файла.
const SOURCE_GEOM = new Map();
async function sourceGeometry(mediaPath) {
  if (SOURCE_GEOM.has(mediaPath)) return SOURCE_GEOM.get(mediaPath);
  let g = null;
  try {
    const streams = await callClassicTool(mediaAnalysisTools.inspect_media_streams, { media_path: mediaPath });
    const vs = streams.streams.find((s) => s.codec_type === "video");
    const w = vs.coded_width || vs.width, h = vs.coded_height || vs.height;
    let barPx = 0;
    try {
      const bounds = await callClassicTool(mediaAnalysisTools.detect_active_picture_bounds, {
        media_path: mediaPath, sample_seconds: 60,
      });
      barPx = Math.max(0, Math.round((h - bounds.activePicture.height) / 2));
    } catch (e) {
      console.log(`  ⚠ Не удалось проверить запечённые полосы в "${mediaPath}": ${e.message} — считаю, что их нет.`);
    }
    const cropPercent = barPx > 0 ? Math.ceil(((100 * barPx) / h) * 2) / 2 : 0; // до 0,5 вверх, как в 4.2.
    const activeH = h * (1 - (2 * cropPercent) / 100);
    const scale = Math.round((REF_PICTURE_H / activeH) * 100);
    g = { w, h, barPx, cropPercent, scale };
  } catch (e) {
    console.log(`  ⚠ Не удалось прочитать разрешение "${mediaPath}": ${e.message}`);
  }
  SOURCE_GEOM.set(mediaPath, g);
  return g;
}

function verticalPositionX(targetXRender, geom, hScale, hPosX) {
  const S = geom.scale;
  const h = hScale > 0 ? hScale : 100;
  const hx = Number.isFinite(hPosX) ? hPosX : 0.5;
  const p = (SEQ_W / 2 - (targetXRender - hx * 1920) * S / h) / SEQ_W;
  const halfW = (geom.w * S) / 100 / 2; // половина видимой ширины (кроп только сверху/снизу)
  if (halfW * 2 <= SEQ_W) return 0.5;
  const lo = (SEQ_W - halfW) / SEQ_W, hi = halfW / SEQ_W;
  return Math.round(Math.min(Math.max(p, lo), hi) * 10000) / 10000;
}

async function setClipMotionScale(clipIndex, value = SCALE) {
  // Абсолютный set_value — идемпотентен, поэтому здесь безопасно повышенное число попыток
  // (12/растущий backoff вместо глобальных 3) — этот вызов на практике флакует чаще, чем
  // остальные (2026-09-10, живой баг на "1. Снайперы ` 1v": 3 попыток не хватало на нескольких
  // клипах подряд сразу после переключения вкладки секвенции; 2026-09-11, живой баг на
  // "6. Вертолёт": даже 8 попыток по 500мс не хватило — подняли до 12, и withRetry теперь сам
  // растягивает интервал между попытками, см. премьер-lib.mjs).
  const first = await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
    action: "set_value", media_type: "video", track_index: 0, clip_index: clipIndex,
    component_index: 1, param_index: 1, value,
  }, 12);
  if (first.paramName === "Scale Height") {
    // Motion уже несимметричен после ресайза 16:9->9:16 (артефакт scale-to-frame,
    // см. инструкцию) — param_index=1 адресует уже не общий Scale, а Height; дополнительно
    // выставляем Width на тот же component, иначе кадр останется растянут по одной оси.
    await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
      action: "set_value", media_type: "video", track_index: 0, clip_index: clipIndex,
      component_index: 1, param_index: 2, value,
    }, 12);
    await callUxpTool(uxpAdvTools.automate_effect_parameters_uxp, {
      action: "set_value", media_type: "video", track_index: 0, clip_index: clipIndex,
      component_index: 1, param_index: 3, value,
    }, 12);
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

async function buildVerticalForSequence(name, projectDir, parentBinNodeId, binFolder) {
  stage(name, "Scanning");
  // --- Рендер и его длительность — до любых мутаций секвенции. Ищем рекурсивно под папкой
  // проекта — секвенция лежит в "~" плоско, без бина "Серия N" в имени. ---
  let found = findRenderFor(projectDir, `${name} \` 1h.mp4`, binFolder);
  // Рендер без суффикса (2026-09-25, папка "✅ 25.09": "Абу Шоу №3.mp4") — запасной вариант,
  // только если "` 1h"-версии нет совсем.
  if (!found.path && !found.ambiguous) {
    const plain = findRenderFor(projectDir, `${name}.mp4`, binFolder);
    if (plain.path || plain.ambiguous) found = plain;
  }
  if (found.ambiguous) {
    return {
      skipped: true, lose: true, reason: "ambiguous_render",
      loseMessage: `несколько рендеров "${name} \` 1h.mp4", не понял, какой к этой секвенции: ` +
        found.ambiguous.join(" | "),
    };
  }
  const renderPath = found.path;
  if (!renderPath) {
    // lose:true — требует действия Saturni (отрендерить), не штатный пропуск (Saturni, 2026-09-11).
    return {
      skipped: true, lose: true, reason: "no_render",
      loseMessage: `не нашёл рендер "${name} \` 1h.mp4"` + (binFolder ? ` в папке "${binFolder}"` : "") +
        ` под "${projectDir}"` + (found.foreign && found.foreign.length ? ` (есть только в другой папке: ${found.foreign.join(" | ")})` : "") +
        ` — отрендерить сначала`,
    };
  }
  // --- sequenceId активной секвенции — нужен для duplicate_sequence (по имени можно
  // ошибиться при неуникальных именах, см. предупреждение в @Premiere Lib.mjs). ---
  const active = await callClassicTool(discoveryTools.get_active_sequence, {});
  const sequenceId = active.id;

  let info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const renderDur = await ffprobeDuration(renderPath);
  if (Math.abs(renderDur - info.durationSeconds) > RENDER_DURATION_TOLERANCE_S) {
    // lose:true — требует действия Saturni (перерендерить), не штатный пропуск (2026-09-11).
    return {
      skipped: true, lose: true, reason: "stale_render", renderDur, seqDur: info.durationSeconds,
      loseMessage: `рендер устарел (рендер ${renderDur.toFixed(2)}с, секвенция ` +
        `${info.durationSeconds.toFixed(2)}с) — перерендерить и повторить`,
    };
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
  // Видеопереходы в середине (правило 2а) с 2026-10-07 обрабатываются ниже, при разводе V1/V2.
  if (loopTailTransitions.length > 1) {
    // lose:true — требует ручной обработки Saturni, не штатный пропуск (2026-09-11).
    return {
      skipped: true, lose: true, reason: "transitions_not_implemented",
      loseMessage: `настоящий видеопереход не у конца таймлайна (${otherTransitions.length} ` +
        `прочих, ${loopTailTransitions.length} у конца) — правило 2а инструкции не ` +
        `реализовано, обработайте вручную`,
    };
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

  // --- Шаг 2: анализ кадрирования (4.1. VReframe-SED.py, автономный, без Premiere) ---
  stage(name, "Reframing");
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
    // lose:true — расхождение анализа с реальным таймлайном, требует разбора (2026-09-11).
    return {
      skipped: true, lose: true, reason: "clip_count_mismatch",
      planLen: plan.length, v1Len: v1Clips.length,
      loseMessage: `4.1. VReframe-SED.py вернул ${plan.length} клипов, а на V1 их ` +
        `${v1Clips.length} — расхождение, не продолжаю вслепую`,
    };
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
    const donor = plan.find((p) => p.smart_scene === donorSc);
    for (const p of plan) if (p.smart_scene === sc) { p.static_x_norm = donor.static_x_norm; p.target_x_src = donor.target_x_src; }
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
    const firstX = plan[0].static_x_norm, firstT = plan[0].target_x_src;
    for (const p of plan) if (p.smart_scene === lastScene) { p.static_x_norm = firstX; p.target_x_src = firstT; }
    console.log(`  Loop-хвост — crop принудительно приравнен к самому первому клипу секвенции.`);
  }

  // --- Правило: если умная сцена накрыта видеопереходом (началом, концом или целиком —
  // в реальном материале это, как правило, loop-хвост от 4.0. Looping.mjs, который
  // 4.1. VReframe-SED.py обычно сливает с предыдущим клипом В ОДНУ умную сцену, а не оставляет
  // границей между двумя разными — поэтому проверяем пересечение с переходом у КАЖДОЙ
  // сцены отдельно, а не только "на стыке двух групп"), она принудительно остаётся на V1,
  // а чётность V1/V2 для дальнейших сцен считается заново от неё (Saturni, 2026-09-10).
  // Переопределяет track, изначально расставленный 4.1. VReframe-SED.py по чистой чётности
  // индекса умной сцены. ---
  let nextIsV2 = false;
  for (let gi = 0; gi < groupOrder.length; gi++) {
    const sc = groupOrder[gi];
    const g = groupSpan.get(sc);
    const touchesTransition = allTransitions.some((tr) =>
      tr.startSeconds < g.end + FRAME_SECONDS / 2 && tr.endSeconds > g.start - FRAME_SECONDS / 2);
    let track;
    // Переход в середине ролика (правило 2а инструкции, 2026-10-07): обе стороны перехода —
    // одна дорожка (V1, иначе clone/lift разорвёт переход), вторая часть слот не занимает —
    // после группы счёт продолжается со следующего слота (V2).
    const touchesMid = otherTransitions.some((tr) =>
      tr.startSeconds < g.end + FRAME_SECONDS / 2 && tr.endSeconds > g.start - FRAME_SECONDS / 2);
    if (touchesMid) {
      track = "V1";
      nextIsV2 = true;
      console.log(`  Умная сцена #${sc} у видеоперехода в середине — на V1 вместе с соседом по переходу (правило 2а).`);
    } else if (touchesTransition) {
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
  stage(name, "Building");
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
  const hGeom = await readClipGeometry(sequenceId); // масштаб/позиция/медиа клипов горизонтали, до дубля
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
  CREATED_DUP_BY_SEQ.set(String(sequenceId), copyItem.nodeId); // для уборки перед повтором (dropHalfBuilt)
  const newName = `${name} \` 1v`;
  await callClassicTool(utilityTools.rename_project_item, { item_id: copyItem.nodeId, new_name: newName });
  const vBinNodeId = await ensureVBin(parentBinNodeId);
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
  // Частота кадров вертикалки = частота её горизонтали (дубль её наследует): секвенции проекта
  // идут с частотой исходника (24, 25, 30…), доли вроде 29,97 не меняются. Здесь только проверка, что дубль её сохранил.
  const fps = await callClassic(`
    var seq = null, src = null;
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      var s = app.project.sequences[i];
      if (String(s.sequenceID) === "${escapeForExtendScript(dupGuid)}") seq = s;
    }
    if (!seq) return __error("Sequence not found by id: ${escapeForExtendScript(dupGuid)}");
    return __result({ after: 254016000000 / Number(seq.timebase) });
  `);
  console.log(`  -> fps ${Math.round(fps.after * 1000) / 1000} (как у горизонтали).`);

  await callUxpTool(uxpAdvTools.manage_sequences_uxp, { action: "open", sequence_id: dupGuid });
  // Даём мосту CEP/UXP "устаканиться" после переключения вкладки + ресайза, прежде чем
  // начинать частые per-clip вызовы automate_effect_parameters_uxp (2026-09-09, живой баг).
  await new Promise((r) => setTimeout(r, 1500));

  // --- Шаг 5 (сначала!) — Motion Scale 140 + Position на каждый клип, пока все на одной
  // дорожке (адресация по track 0 / clip_index проще — см. инструкцию) ---
  stage(name, "Positioning");
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const dupClips = info.videoTracks[0].clips.slice().sort((a, b) => a.startSeconds - b.startSeconds);
  const round3 = (x) => Math.round(x * 1000) / 1000;
  const positionItems = [];
  const scaleClipIndexes = [];
  const scaleByIndex = new Map();
  const cropByIndex = new Map();
  const geomNotes = new Set();
  for (let i = 0; i < dupClips.length; i++) {
    const clip = dupClips[i];
    const planEntry = plan.find((p) => round3(p.start) === round3(clip.startSeconds));
    if (!planEntry) {
      console.log(`  ⚠ Не нашёл в плане клип, начинающийся на ${clip.startSeconds.toFixed(3)}с — пропускаю его Motion.`);
      continue;
    }
    scaleClipIndexes.push(i);
    const hc = hGeom.get(round3(clip.startSeconds));
    const geom = hc && hc.media ? await sourceGeometry(hc.media) : null;
    let posX = planEntry.static_x_norm;
    if (geom) {
      scaleByIndex.set(i, geom.scale);
      if (geom.cropPercent > 0) cropByIndex.set(i, geom.cropPercent);
      if (Number.isFinite(planEntry.target_x_src)) {
        posX = verticalPositionX(planEntry.target_x_src, geom, hc.scale, hc.posX);
      }
      geomNotes.add(`${geom.w}x${geom.h}` + (geom.cropPercent ? ` полосы ${geom.barPx}px -> Crop ${geom.cropPercent}%` : "") +
        ` -> Scale ${geom.scale}`);
    } else {
      scaleByIndex.set(i, SCALE); // исходник не прочитался — эталонные 140, как раньше
      geomNotes.add(`исходник не прочитан -> Scale ${SCALE}`);
    }
    positionItems.push({ node_id: clip.nodeId, position_x: posX, position_y: 0.5 });
  }
  // Scale 140 — ОДНОЙ транзакцией на все клипы (parameters.setBatch, 2026-09-24), а не
  // вызовом на клип: это было главное место падений "no longer valid". Motion = компонент 1
  // (как и раньше); параметры по имени: uniform "Scale", либо после артефакта
  // scale-to-frame раздельные "Scale Height"/"Scale Width" — какие есть, те и ставим.
  try {
    await setParamsBatch(scaleClipIndexes.map((i) => ({
      trackIndex: 0, clipIndex: i, componentIndex: 1,
      params: [
        { name: "Scale", value: scaleByIndex.get(i), optional: true },
        { name: "Scale Height", value: scaleByIndex.get(i), optional: true },
        { name: "Scale Width", value: scaleByIndex.get(i), optional: true },
        ...(cropByIndex.has(i) ? [
          { name: "Crop Top", value: cropByIndex.get(i) },
          { name: "Crop Bottom", value: cropByIndex.get(i) },
        ] : []),
      ],
    })));
  } catch (e) {
    if (!e.unsupported) throw e;
    console.log(`  (${e.message} — ставлю Scale по одному клипу, как раньше)`);
    if (cropByIndex.size) {
      throw new Error("нужен Crop запечённых полос, а плагин без parameters.setBatch — перезагрузи UXP-плагин");
    }
    for (const i of scaleClipIndexes) await setClipMotionScale(i, scaleByIndex.get(i));
  }
  await setPositionsBatched(positionItems);
  console.log(`  -> Motion Scale + Position выставлены на ${dupClips.length} клипов (${[...geomNotes].join("; ")}).`);

  // Даём мосту "отдышаться" после длинного цикла per-clip automate_effect_parameters_uxp
  // выше — живой баг 2026-09-11: сразу за ним clone_selection стабильно (не флаки, 4 из 4
  // секвенций подряд) падал даже после 12 попыток. Сам по себе retry-с-переустановкой-
  // выделения (см. ниже) — главный фикс, эта пауза — дополнительная подстраховка, тот же
  // принцип, что уже есть после переключения вкладки+ресайза (см. выше по файлу).
  await new Promise((r) => setTimeout(r, 1000));

  // --- Шаг 4 — развод чётных умных сцен на V2 ---
  stage(name, "Grouping");
  info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  const freshClips = info.videoTracks[0].clips.slice().sort((a, b) => a.startSeconds - b.startSeconds);
  const v2NodeIds = [];
  for (let i = 0; i < freshClips.length; i++) {
    const planEntry = plan.find((p) => round3(p.start) === round3(freshClips[i].startSeconds));
    if (planEntry && planEntry.track === "V2") v2NodeIds.push(freshClips[i].nodeId);
  }

  if (v2NodeIds.length > 0) {
    // ⚠️ ИСПРАВЛЕНО (2026-09-11, живой баг — 100%-но воспроизводимый на 4 секвенциях подряд,
    // не флаки): выбор клипов (классический CEP-мост) и сам clone_selection (UXP-мост) ДОЛЖНЫ
    // перевыполняться ВМЕСТЕ на каждой попытке — то же самое, что уже проверено и работает в
    // 4.2. Background Blur.mjs (см. её Шаг 2). Раньше выбор делался ОДИН раз снаружи, а
    // ретраились только сами UXP-вызовы — если мост CEP/UXP рассинхронизировался хоть раз
    // (после тяжёлого цикла automate_effect_parameters_uxp на Positioning — см. выше), ЛЮБОЕ
    // число попыток clone_selection било по одному и тому же протухшему выделению и не могло
    // восстановиться (12/12 попыток — не помогало). lift_selection_uxp НЕ включаем в этот же
    // retry-блок — она отдельная операция над уже смонтированными на V2 клипами, а не над
    // исходным выделением; если засунуть её в тот же блок, повтор ПОСЛЕ того как
    // clone_selection уже реально прошёл заново продублировал бы клипы на V2 (см. заголовок
    // файла — clone_selection либо полностью проходит, либо полностью отклоняется, но только
    // САМ ПО СЕБЕ — компаунд из двух разных мутаций такой гарантии уже не даёт).
    await withRetry(async () => {
      await callClassicTool(selectionTools.deselect_all_clips, {});
      for (const id of v2NodeIds) {
        await callClassicTool(advancedTools.set_clip_selection, { node_id: id, selected: true });
      }
      const selected = await callClassicTool(discoveryTools.get_selected_clips, {});
      if (selected.length !== v2NodeIds.length) {
        // Текст ошибки НАРОЧНО содержит "no longer valid" — withRetry() матчит retryable
        // ошибки регуляркой по подстроке (см. премьер-lib.mjs), а несовпадение количества
        // выделенных клипов — тот же симптом рассинхронизации моста, тоже должен ретраиться.
        throw new Error(
          `Выделено ${selected.length} клипов вместо ожидаемых ${v2NodeIds.length} — похоже, ` +
          `мост рассинхронизировался (та же природа, что "The script object is no longer ` +
          `valid") — переустанавливаю выделение и пробую снова.`
        );
      }
      await callUxpTool(uxpAdvTools.edit_timeline_uxp, {
        action: "clone_selection", video_track_offset: 1, time_offset_seconds: 0,
      });
    }, 12);
    await callUxpTool(uxpTools.lift_selection_uxp, { expected_sequence_guid: dupGuid }, 12);
    console.log(`  -> ${v2NodeIds.length} клипов разведены на V2.`);
  } else {
    console.log(`  -> Ни одного клипа на V2 не потребовалось (одна умная сцена на всю секвенцию).`);
  }

  // --- Финальная проверка (Saturni, 2026-10-01): живой случай «Феерверк» — вертикалка без
  // Motion считалась готовой, и повтор её пропускал. Не сошлось — verifyError: runPipeline
  // уберёт недособранную (dropHalfBuilt), вернёт горизонталь из бэкапа и соберёт заново. ---
  const expected = new Map();
  for (const i of scaleClipIndexes) {
    const pos = positionItems.find((p) => p.node_id === dupClips[i].nodeId);
    expected.set(round3(dupClips[i].startSeconds), {
      scale: scaleByIndex.get(i), crop: cropByIndex.get(i) || 0, posX: pos ? pos.position_x : null,
    });
  }
  await verifyVertical(expected, dupClips.length, v2NodeIds.length);
  console.log(`  -> Проверено: ${dupClips.length} клипов, Scale/Position/Crop на месте.`);

  return { skipped: false, clips: dupClips.length, v2: v2NodeIds.length, verticalName: newName };
}

async function verifyVertical(expected, totalClips, v2Count) {
  const got = await callClassic(`
    var q = app.project.activeSequence, out = { w: q.frameSizeHorizontal, h: q.frameSizeVertical, tracks: [] };
    for (var t = 0; t < Math.min(2, q.videoTracks.numTracks); t++) {
      var tr = q.videoTracks[t], clips = [];
      for (var c = 0; c < tr.clips.numItems; c++) {
        var cl = tr.clips[c], v = { start: cl.start.seconds, scale: null, posX: null, crop: 0 };
        for (var k = 0; k < cl.components.numItems; k++) {
          var comp = cl.components[k]; if (comp.matchName !== "AE.ADBE Motion") continue;
          for (var j = 0; j < comp.properties.numItems; j++) {
            var p = comp.properties[j], n = p.displayName;
            if (n === "Scale" || (n === "Scale Height" && v.scale === null)) v.scale = p.getValue();
            else if (n === "Position") { var pv = p.getValue(); v.posX = pv[0]; }
            else if (n === "Crop Top") v.crop = p.getValue();
          }
        }
        clips.push(v);
      }
      out.tracks.push(clips);
    }
    return __result(out);
  `);
  const bad = [];
  if (got.w !== 1080 || got.h !== 1920) bad.push(`кадр ${got.w}x${got.h}`);
  const all = [].concat(...got.tracks);
  if (all.length !== totalClips) bad.push(`клипов ${all.length} вместо ${totalClips}`);
  if ((got.tracks[1] || []).length !== v2Count) bad.push(`на V2 ${(got.tracks[1] || []).length} вместо ${v2Count}`);
  let off = 0;
  for (const c of all) {
    const e = expected.get(Math.round(c.start * 1000) / 1000);
    if (!e) continue;
    if (c.scale === null || Math.abs(c.scale - e.scale) > 0.5) off++;
    else if (e.posX !== null && (c.posX === null || Math.abs(c.posX - e.posX) > 0.003)) off++;
    else if (Math.abs((c.crop || 0) - e.crop) > 0.05) off++;
  }
  if (off) bad.push(`Motion не совпал у ${off} клипов`);
  if (bad.length) throw verifyError(bad.join("; "));
}

async function applyVerticalToActiveSequence(name, projectDir, target) {
  if (name === "c") {
    console.log(`  -> ПРОПУСК: служебная секвенция "c".`);
    return { skipped: true, reason: "reserved_name" };
  }
  const info = await callClassicTool(inspectionTools.get_full_sequence_info, {});
  if (info.height >= info.width) {
    console.log(`  -> ПРОПУСК: не горизонтальная (${info.width}x${info.height}) — уже вертикалка.`);
    return { skipped: true, reason: "not_horizontal" };
  }
  const built = target && target.binNodeId
    ? await alreadyBuiltInFolder(`${name} \` 1v`, target.binNodeId)
    : await alreadyBuilt(`${name} \` 1v`);
  if (built) {
    console.log(`  -> ПРОПУСК: "${name} \` 1v" уже существует.`);
    return { skipped: true, reason: "already_built" };
  }

  // Папка-родитель горизонталки; в режиме явных имён (без обхода бина) её нет — тогда
  // "v" кладётся прямо в рабочий бин "~", как было до 2026-09-24.
  let parentBinNodeId = target && target.binNodeId;
  if (!parentBinNodeId) {
    parentBinNodeId = (await callClassic(`
      function isBinItem(item) { return item.children !== undefined && item.children !== null; }
      function findBin(parent, name) {
        for (var i = 0; i < parent.children.numItems; i++) {
          var item = parent.children[i];
          if (!isBinItem(item)) continue;
          if (item.name === name) return item;
          var found = findBin(item, name);
          if (found) return found;
        }
        return null;
      }
      var bin = findBin(app.project.rootItem, "${escapeForExtendScript(BIN_NAME)}");
      if (!bin) return __error("Bin not found: ${escapeForExtendScript(BIN_NAME)}");
      return __result({ nodeId: bin.nodeId });
    `)).nodeId;
  }
  const result = await buildVerticalForSequence(name, projectDir, parentBinNodeId, target && target.folder);
  if (!result.skipped) {
    await callClassicTool(projectTools.save_project, {});
  }
  return result;
}

async function main() {
  try {
    for (const r of await listBinSequenceRefs(BIN_NAME)) {
      for (const seg of (r.folder || "").split("/").filter(Boolean)) if (seg !== "v") ALL_BIN_FOLDERS.add(seg);
    }
  } catch (e) { /* без списка папок — поиск рендера как раньше */ }
  const projectInfo = await callClassicTool(discoveryTools.get_project_info, {});
  const projectDir = path.dirname(projectInfo.path);

  const results = await runPipeline({
    binName: BIN_NAME,
    applyFn: (name, _sequenceId, target) => applyVerticalToActiveSequence(name, projectDir, target),
    beforeRetry: dropHalfBuilt,
  });

  // Итог — только проблемные (Saturni, 2026-09-24: успешные перечислять не нужно, и без
  // напоминаний). В обычном запуске через лаунчер это и так уходит только в лог-файл.
  const problems = results.filter((r) => r.result.error);
  if (problems.length > 0) {
    console.log("\nПроблемы:");
    problems.forEach((r) => console.log(`  → ${r.name}: ${r.result.error}`));
  }
  // seq_done эмиттится сразу по каждой секвенции внутри runPipeline() (deferDone по
  // умолчанию false — доп. прохода после основного цикла тут нет).
  checkResultsForFailures(results);
}

runCli(main);
