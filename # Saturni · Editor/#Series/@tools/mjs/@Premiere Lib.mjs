// Общая инфраструктура для автономных скриптов автоматизации Premiere (без Claude/MCP-протокола).
// Используется 4.0. Looping.mjs и 4.2. Background Blur.mjs. См. @instructions/4.0. Looping.md,
// @instructions/4.1. Smart Verticals.md, память "standalone-loop-script".
//
// ВАЖНО: нельзя запускать одновременно с открытой сессией Claude Code, использующей
// premiere-pro MCP-сервер — оба процесса конкурируют за один и тот же UXP WebSocket
// порт (по умолчанию 7777) и один и тот же файловый CEP-мост.

import { pathToFileURL } from "node:url";
import path from "node:path";
import { readFileSync, appendFileSync } from "node:fs";

export const PKG_ROOT = "D:/@Hub/# Saturni · Editor/#Series/@tools/mcp/premiere-pro-mcp/dist";
const MCP_CONFIG_PATH = "D:/@Hub/# Saturni · Editor/.mcp.json";

// Если PREMIERE_UXP_TOKEN/PORT не заданы в окружении — подхватить их из .mcp.json,
// чтобы не нужно было выставлять переменные окружения вручную при запуске без Claude.
if (!process.env.PREMIERE_UXP_TOKEN) {
  try {
    const config = JSON.parse(readFileSync(MCP_CONFIG_PATH, "utf-8"));
    const env = config.mcpServers?.["premiere-pro"]?.env ?? {};
    if (env.PREMIERE_UXP_TOKEN) process.env.PREMIERE_UXP_TOKEN = env.PREMIERE_UXP_TOKEN;
    // PORT из .mcp.json НЕ берём: 7777 — у MCP Claude, скрипты ходят на 7778 (2026-10-29)
  } catch (e) {
    // молча игнорируем — ensureUxpConnected ниже даст понятную ошибку, если токена всё равно нет
  }
}

async function importDist(relPath) {
  const full = path.join(PKG_ROOT, relPath);
  return import(pathToFileURL(full).href);
}

const { sendCommand } = await importDist("bridge/file-bridge.js");
const { buildScript, escapeForExtendScript } = await importDist("bridge/script-builder.js");
const { UxpWebSocketBridge } = await importDist("bridge/uxp-websocket-bridge.js");
export { escapeForExtendScript };

// Фабрики инструментов — те же самые функции, что стоят за MCP-вызовами (не переизобретаем
// протокол, вызываем ровно тот код, что уже проверен вживую через MCP).
const { getAdvancedTools } = await importDist("tools/advanced.js"); // roll_edit, set_clip_selection
const { getSelectionTools } = await importDist("tools/selection.js"); // deselect_all_clips, select_all_clips
const { getTrackTargetingTools } = await importDist("tools/track-targeting.js"); // remove_selected_clips, set_clip_opacity
const { getInspectionTools } = await importDist("tools/inspection.js"); // get_full_sequence_info
const { getUxpAdvancedWorkflowTools } = await importDist("tools/uxp-advanced-workflows.js"); // transform_track_item_uxp, automate_effect_parameters_uxp, edit_timeline_uxp
const { getUxpTools } = await importDist("tools/uxp.js"); // add_video_transition_uxp, rename_track_uxp
const { getTrackTools } = await importDist("tools/tracks.js"); // add_track
const { getClipboardTools } = await importDist("tools/clipboard.js"); // batch_apply_effect
const { getScriptingTools } = await importDist("tools/scripting.js"); // list_clip_effects
const { getMediaAnalysisTools } = await importDist("tools/media-analysis.js"); // inspect_media_streams, detect_active_picture_bounds (чистый ffmpeg/ffprobe, Premiere не трогает)
const { getMetadataTools } = await importDist("tools/metadata.js"); // get_color_label/set_color_label (по project item — не по клипу таймлайна, см. premiere-mcp-gotchas)
const { getUtilityTools } = await importDist("tools/utility.js"); // get_clip_markers — маркеры НА ИСХОДНИКЕ (Source Monitor), не на секвенции; см. 2. Silence Cut.mjs; rename_project_item
const { getDiscoveryTools } = await importDist("tools/discovery.js"); // find_project_item_by_name, get_selected_clips
const { getMediaTools } = await importDist("tools/media.js"); // create_bin, move_item_to_bin
const { getSequenceTools } = await importDist("tools/sequence.js"); // duplicate_sequence
const { getCompetitorGapTools } = await importDist("tools/competitor-gaps.js"); // set_clip_properties_batch (position, БЕЗ scale — см. 4.1. Smart Verticals.md)
const { getProjectTools } = await importDist("tools/project.js"); // set_active_sequence (по имени ИЛИ id — в отличие от setActiveSequenceById ниже, который матчит только id)
const { getTransitionsTools } = await importDist("tools/transitions.js"); // add_transition_to_clip (классический QE-тул — надёжнее add_video_transition_uxp на F−1-стыке, см. ниже)
const { getKeyframeTools } = await importDist("tools/keyframes.js"); // set_effect_property — по имени эффекта/параметра, без угадывания component/param_index

// --- Классический (CEP-файловый) вызов сырого ExtendScript: то же, что делают
// list_sequences / get_bin_contents / set_active_sequence в MCP-сервере. Экспортирован
// (не только внутренний resolveTargets) — используется в 4.1. Smart Verticals.mjs, чтобы
// найти sequenceID по nodeId project item НАПРЯМУЮ, без __findSequence(idOrName), который
// матчит по имени первый попавшийся элемент project.sequences — при дублирующихся именах
// (частый случай в этом проекте из-за старых бэкап-бинов) может схватить чужую секвенцию
// (см. [[smart-verticals-script]], живой баг 2026-09-10).
export async function callClassic(scriptBody) {
  const result = await sendCommand(buildScript(scriptBody));
  if (!result.success) {
    throw new Error(`CEP-команда провалилась: ${result.error}`);
  }
  return result.data;
}

// timeoutMs 75 с (2026-09-30): при занятом скрипт-движке мост ждёт до max(timeout×4, 120 с), и с
// дефолтом 30 с это давало 120 с — SED (scene_edit_detection) на роликах ~50 с («Дубровский»)
// не успевал и падал «did not finish within 120000ms». Теперь предел 300 с.
const bridgeOptions = { timeoutMs: 75000 }; // временный каталог по умолчанию — тот же, что использует CEP-панель

// --- UXP WebSocket мост. ВАЖНО: это тот же самый сервер, что поднимает MCP-процесс. ---
export const uxpBridge = new UxpWebSocketBridge({
  token: process.env.PREMIERE_UXP_TOKEN,
  port: process.env.PREMIERE_UXP_PORT ? parseInt(process.env.PREMIERE_UXP_PORT, 10) : 7778,   // 7778 — отдельное подключение плагина для скриптов, 7777 у MCP Claude (2026-10-29)
});

export async function ensureUxpConnected(timeoutMs = 15000) {
  try {
    await uxpBridge.start();
  } catch (e) {
    if (e && e.code === "EADDRINUSE") {
      // Живой случай 2026-09-23: порт держал node MCP-сервера premiere-pro из открытой
      // сессии Claude — вместо голого "listen EADDRINUSE" говорим, что делать.
      throw new Error(
        `порт ${process.env.PREMIERE_UXP_PORT || 7778} занят — ` +
        `его держит MCP premiere-pro (сессия Claude) или прошлый зависший запуск; ` +
        `закрой его и перезапусти`
      );
    }
    throw e;
  }
  if (uxpBridge.getState().connected) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(
        `UXP-панель не подключилась за ${timeoutMs}мс. Откройте Premiere с проектом, ` +
        `убедитесь что панель (Window > Extensions) запущена, и что никакая сессия Claude Code ` +
        `не держит этот же порт (${uxpBridge.address().port}).`
      ));
    }, timeoutMs);
    uxpBridge.once("connected", () => { clearTimeout(timer); resolve(); });
  });
}

export const metadataTools = getMetadataTools(bridgeOptions);
export const utilityTools = getUtilityTools(bridgeOptions);
export const advancedTools = getAdvancedTools(bridgeOptions);
export const selectionTools = getSelectionTools(bridgeOptions);
export const trackTargetingTools = getTrackTargetingTools(bridgeOptions);
export const inspectionTools = getInspectionTools(bridgeOptions);
export const uxpAdvTools = getUxpAdvancedWorkflowTools(uxpBridge);
export const uxpTools = getUxpTools(uxpBridge);
export const trackTools = getTrackTools(bridgeOptions);
export const clipboardTools = getClipboardTools(bridgeOptions);
export const scriptingTools = getScriptingTools(bridgeOptions);
export const mediaAnalysisTools = getMediaAnalysisTools(bridgeOptions);
export const discoveryTools = getDiscoveryTools(bridgeOptions);
export const mediaTools = getMediaTools(bridgeOptions);
export const sequenceTools = getSequenceTools(bridgeOptions);
export const competitorGapTools = getCompetitorGapTools(bridgeOptions, uxpBridge);
export const projectTools = getProjectTools(bridgeOptions);
export const transitionsTools = getTransitionsTools(bridgeOptions);
export const keyframeTools = getKeyframeTools(bridgeOptions);

// Общий retry для флаки-ошибок бриджа — "The script object is no longer valid" / "rejected an
// action" иногда всплывает на ЛЮБОМ вызове (временная рассинхронизация CEP/UXP-моста с DOM
// Premiere, не потеря данных — тот же самый вызов чуть позже проходит без изменений). Поэтому
// retry встроен на самом низком уровне — в обе функции-обёртки вызова тулов.
export function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

export const RETRYABLE_RE = /no longer valid|rejected an action/i;

export async function withRetry(fn, retries = 3) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (e) {
      const retryable = (e && e.retryable === true) || RETRYABLE_RE.test(e.message || "");
      if (!retryable || attempt >= retries) throw e;
      // ⚠️ Ретрай ОПАСЕН на относительных/неидемпотентных вызовах (move_by_seconds,
      // roll_edit, add_keyframe, clone_selection с time_offset) — если мутация реально
      // прошла, а мост из-за гонки вернул ложную ошибку, повтор применит её ЕЩЁ РАЗ поверх
      // уже применённой (кейфреймы/границы клипов "уезжают" накопительно — живой баг,
      // 2026-09-09, найден при попытке поднять число попыток до 6 с растущим backoff НА
      // ТАКИХ вызовах). Поэтому КОЛИЧЕСТВО попыток по умолчанию не трогаем (3, как было,
      // проверено вживую 2026-09-05) — только для явно абсолютных/идемпотентных вызовов
      // отдельные call-сайты сами передают повышенный retries (см. 4.1., setClipMotionScale).
      // Backoff РАСТЁТ (500мс, 1000мс, 1500мс...) вместо фиксированных 500мс — это НЕ повышает
      // число попыток (тот же риск двойного применения на risky-вызовах), а даёт мосту больше
      // времени на ресинхронизацию между попытками, что на практике снижает саму частоту
      // повторов до исчерпания лимита (2026-09-11, ответ на живые логи "8 попыток не хватало").
      console.log(`  (флаки-ошибка "${e.message}" — повтор ${attempt + 1}/${retries}...)`);
      await sleep(500 * Math.min(attempt + 1, 4));
      // Не только ждём, но и даём Premiere обновить состояние: переоткрываем текущую активную
      // секвенцию (Saturni, 2026-09-24). Сама по себе ничего не меняет в проекте — безопасно
      // и для неидемпотентных вызовов (их число попыток по-прежнему 3, см. выше).
      await resyncBridge();
    }
  }
}

// Переоткрыть активную секвенцию через UXP (sequences.open) — Premiere заново поднимает её
// модель в панели Timeline. Вызовы идут мимо withRetry (иначе рекурсия), любые ошибки
// глотаются: это подстраховка перед повтором, а не отдельный шаг, который может уронить прогон.
export async function resyncBridge() {
  try {
    const active = await callClassic(`
      var s = app.project.activeSequence;
      if (!s) return __error("no active sequence");
      return __result({ id: String(s.sequenceID) });
    `);
    await uxpAdvTools.manage_sequences_uxp.handler({ action: "open", sequence_id: active.id });
    await sleep(300);
  } catch (e) { /* не удалось — просто повторяем как раньше */ }
}

// Классические тулы возвращают {success,data,error} напрямую (это и есть CommandResult
// из sendCommand). UXP-тулы оборачивают результат в {success,data:{backend,result}}.
export async function callClassicTool(tool, args, retries) {
  return withRetry(async () => {
    const res = await tool.handler(args);
    if (!res.success) throw new Error(res.error || "classic tool call failed");
    return res.data;
  }, retries);
}
export async function callUxpTool(tool, args, retries) {
  return withRetry(async () => {
    const res = await tool.handler(args);
    if (!res.success) throw new Error(res.error || "uxp tool call failed");
    return res.data.result;
  }, retries);
}

// --- Пакетная установка скалярных параметров эффектов ОДНОЙ транзакцией (Saturni,
// 2026-09-24): команда "parameters.setBatch" в нашем UXP-плагине
// (@tools/mcp/premiere-pro-mcp/artifacts/INSTALL_com.ppmcp.premiere.uxp/… — оттуда
// Premiere грузит плагин; исходник-зеркало — uxp-plugin/). Раньше: по одному
// automate_effect_parameters_uxp на КАЖДЫЙ параметр КАЖДОГО клипа (30–140 вызовов на
// секвенцию), и на любом из них Premiere мог отдать "The script object is no longer valid".
// Теперь — один вызов на всю секвенцию. Вызов абсолютный (set value) — повтор целиком
// безопасен, поэтому 12 попыток; неподтверждённое чтением значение тоже повторяем.
// items: [{ trackIndex, clipIndex, componentIndex | componentMatchName,
//           params: [{ index | name, value, optional? }] }]
// Если в Premiere загружена СТАРАЯ версия плагина (команды нет) — бросаем ошибку с
// флагом unsupported: вызывающий код откатывается на прежний поклиповый путь.
const BATCH_CHUNK = 256;
export async function setParamsBatch(items, { mediaType = "video", retries = 12 } = {}) {
  let updated = 0;
  for (let i = 0; i < items.length; i += BATCH_CHUNK) {
    const chunk = items.slice(i, i + BATCH_CHUNK);
    const res = await withRetry(async () => {
      let r;
      try {
        r = await uxpBridge.request("parameters.setBatch", { mediaType, items: chunk });
      } catch (e) {
        if ((e && e.code === "UXP_COMMAND_UNSUPPORTED") || /does not support UXP command/i.test(e.message || "")) {
          const err = new Error("в Premiere загружена старая версия UXP-плагина без parameters.setBatch — перезагрузи плагин");
          err.unsupported = true;
          throw err;
        }
        throw e;
      }
      if (!r || !r.verified) {
        const err = new Error(`пакетная установка не подтвердилась чтением: ${r && r.mismatchCount} ` +
          `расхождений ${JSON.stringify((r && r.mismatches || []).slice(0, 3))}`);
        err.retryable = true;
        throw err;
      }
      return r;
    }, retries);
    updated += res.updated || 0;
  }
  return { updated };
}

export async function selectOnly(nodeId) {
  await callClassicTool(selectionTools.deselect_all_clips, {});
  await callClassicTool(advancedTools.set_clip_selection, { node_id: nodeId, selected: true });
}

export const FRAME_SECONDS = 0.04; // 25 fps (см. допущение в 4.0. Looping.md)

// ВАЖНО: Premiere НЕ гарантирует уникальность имени секвенции — в проекте вполне может
// быть несколько секвенций с одинаковым именем (проверено на практике: бэкапы клонируют
// одноимённые секвенции без переименования). Поэтому единственный надёжный идентификатор —
// sequenceID. Матчинг по имени НЕ используем нигде, кроме как для человекочитаемого лога.

export async function listBinSequenceRefs(binName) {
  // Обходит бин РЕКУРСИВНО (секвенция может лежать на любую глубину вложенных подпапок).
  // Каждый лист сверяется с реальными секвенциями проекта строго по nodeId (через
  // Sequence.projectItem.nodeId), а не по имени — иначе при дублирующихся именах можно
  // случайно взять не ту секвенцию.
  const data = await callClassic(`
    function isBinItem(item) {
      return item.children !== undefined && item.children !== null;
    }
    function findBinByName(parent, name) {
      for (var i = 0; i < parent.children.numItems; i++) {
        var item = parent.children[i];
        if (!isBinItem(item)) continue;
        if (item.name === name) return item;
        var found = findBinByName(item, name);
        if (found) return found;
      }
      return null;
    }
    var bin = findBinByName(app.project.rootItem, "${escapeForExtendScript(binName)}");
    if (!bin) return __error("Bin not found: ${escapeForExtendScript(binName)}");

    // nodeId ProjectItem'а -> sequenceID, строго через обратную ссылку
    var nodeIdToSeqId = {};
    for (var s = 0; s < app.project.sequences.numSequences; s++) {
      var seq = app.project.sequences[s];
      try {
        if (seq.projectItem) nodeIdToSeqId[seq.projectItem.nodeId] = seq.sequenceID;
      } catch (e) {}
    }

    // Длительность секвенции (сек) — вес задачи для ETA статус-бара.
    var nodeIdToDur = {};
    for (var s = 0; s < app.project.sequences.numSequences; s++) {
      var sq = app.project.sequences[s];
      try {
        if (sq.projectItem) nodeIdToDur[sq.projectItem.nodeId] = Number(sq.end) / 254016000000;
      } catch (e) {}
    }

    var refs = [];
    var storeName = "${escapeForExtendScript(BACKUP_BIN_NAME)}";
    // folder — путь папок ОТ рабочего бина ("" = лежит прямо в "~", "Series 10",
    // "Series 10/v"); binNodeId — непосредственная папка-родитель секвенции (туда 4.1.
    // кладёт свою "v", Saturni 2026-09-24).
    function collectSequenceRefs(parent, folder) {
      for (var i = 0; i < parent.children.numItems; i++) {
        var item = parent.children[i];
        if (isBinItem(item)) {
          // Склад бэкапов "⿻" в работу не берём никогда. Штатно он лежит в корне проекта,
          // то есть вне "~", и сюда не попадает — проверка страхует случай, когда его
          // перенесли внутрь рабочего бина (иначе прогон взял бы в работу свои же бэкапы).
          if (item.name === storeName) continue;
          // Папки режимов этапа 1+2 ("1. Active", "2. Faster", "3. Medium") — невыбранные черновики:
          // их секвенции называются так же, как итоговые ("1", "2"…), и подхватили бы чужой рендер.
          if (/^\\d+\\.\\s*(Active|Faster|Medium)$/.test(item.name)) continue;
          collectSequenceRefs(item, folder === "" ? item.name : folder + "/" + item.name);
        } else if (nodeIdToSeqId[item.nodeId] !== undefined) {
          refs.push({
            name: item.name, sequenceId: nodeIdToSeqId[item.nodeId],
            folder: folder, binNodeId: parent.nodeId,
            durationSeconds: nodeIdToDur[item.nodeId] || 0,
          });
        }
        // не-секвенции (просто файлы) молча пропускаются
      }
    }
    collectSequenceRefs(bin, "");
    return __result(refs);
  `);
  return data; // { name, sequenceId, folder, binNodeId, durationSeconds }[]
}

export async function setActiveSequenceById(sequenceId) {
  await callClassic(`
    var seq = null;
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      if (String(app.project.sequences[i].sequenceID) === "${escapeForExtendScript(sequenceId)}") {
        seq = app.project.sequences[i];
        break;
      }
    }
    if (!seq) return __error("Sequence not found by id: ${escapeForExtendScript(sequenceId)}");
    app.project.activeSequence = seq;
    var active = app.project.activeSequence;
    if (!active || active.sequenceID !== seq.sequenceID) {
      return __error("Premiere did not activate the requested sequence");
    }
    return __result({ name: active.name, id: active.sequenceID });
  `);
}

export function timestampTag() {
  // Формат "ЧЧ:ММ:СС ДД.ММ.ГГ", пример: "06:18:03 22.09.26" (Saturni, 2026-09-22 — раньше
  // было "050926-041754", затем коротко жил вариант с датой впереди). Имя бина в Premiere —
  // обычная строка, двоеточия допустимы, это не путь на диске.
  const d = new Date();
  const p2 = (n) => String(n).padStart(2, "0");
  return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())} ` +
    `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.${p2(d.getFullYear() % 100)}`;
}

// Постоянный бин-склад бэкапов (Saturni, 2026-09-22) — заведён в корне проекта вручную,
// скрипты только находят его по имени и кладут туда папки бэкапов.
export const BACKUP_BIN_NAME = "⿻";

// --- Бэкап (Saturni, 2026-09-22 — новая схема). Рабочий бин теперь "~", и бэкапы больше
// НЕ кладутся рядом с ним одной папкой "#Processing <дата>", а складываются в постоянный
// бин-склад "⿻" (он уже заведён в корне проекта — мы его НАХОДИМ, а не создаём), причём
// каждая папка верхнего уровня бэкапится отдельно под своим именем:
//   "~/Серия 2"  ->  "⿻/Серия 2\`15:36:25 16.09.26"
// Секвенции, лежащие в "~" плоско (без папки "Серия N"), собираются в общую папку
// "⿻/~\`<время дата>".
// Секвенции клонируются через Sequence.clone() (нативный API — та же операция, что и
// duplicate_sequence в MCP), клон переносится в зеркальную папку бэкапа через
// ProjectItem.moveBin(). Бины просто пересоздаются структурно через createBin(). ---
export async function backupBin(binName) {
  const tag = timestampTag();
  const data = await callClassic(`
    function isBinItem(item) {
      return item.children !== undefined && item.children !== null;
    }
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
    var sourceBin = findBin(app.project.rootItem, "${escapeForExtendScript(binName)}");
    if (!sourceBin) return __error("Bin not found: ${escapeForExtendScript(binName)}");

    // Склад бэкапов "⿻" — ПОСТОЯННЫЙ бин, он уже заведён в проекте (обычно в корне,
    // Saturni, 2026-09-22). Не создаём его каждый раз заново, а находим существующий по
    // имени где угодно в дереве и берём его id; создаём в корне только если его вдруг нет.
    var storeName = "${escapeForExtendScript(BACKUP_BIN_NAME)}";
    var store = findBin(app.project.rootItem, storeName);
    if (!store) store = app.project.rootItem.createBin(storeName);
    if (!store) return __error("createBin failed for backup store bin");

    var warnings = [];
    var seqMap = {};

    // nodeId ProjectItem'а -> Sequence — матчинг СТРОГО по nodeId, а не по имени:
    // имена секвенций в Premiere не обязаны быть уникальными, было проверено на
    // практике (несколько одноимённых одновременно после серии бэкапов).
    var nodeIdToSeq = {};
    for (var si = 0; si < app.project.sequences.numSequences; si++) {
      var s0 = app.project.sequences[si];
      try { if (s0.projectItem) nodeIdToSeq[s0.projectItem.nodeId] = s0; } catch (e) {}
    }

    // Клонирование ОДНОЙ секвенции в destBin. Вынесено из mirror() отдельной функцией,
    // потому что секвенции могут лежать и плоско в корне "~" (без папки "Серия N").
    function mirrorOne(child, destBin) {
        var seq = nodeIdToSeq[child.nodeId];
        if (!seq) {
          warnings.push("Пропущен не-секвенция лист: " + child.name);
          return;
        }
        // ВАЖНО: Premiere НЕ следит за уникальностью имён секвенций — двух "X Copy"
        // может быть сколько угодно с разными sequenceID. Поэтому находим новую
        // секвенцию строго по diff'у sequenceID (до/после), а затем берём её
        // ProjectItem напрямую через newSeq.projectItem — штатное обратное свойство
        // (используется и в rename_project_item), без поиска по дереву/имени вообще.
        var beforeSeqIds = {};
        for (var s2 = 0; s2 < app.project.sequences.numSequences; s2++) {
          beforeSeqIds[app.project.sequences[s2].sequenceID] = true;
        }
        seq.clone();
        var newSeq = null;
        for (var s2 = 0; s2 < app.project.sequences.numSequences; s2++) {
          var cs = app.project.sequences[s2];
          if (!beforeSeqIds[cs.sequenceID]) { newSeq = cs; break; }
        }
        if (!newSeq) {
          warnings.push("Не удалось найти клон-секвенцию для: " + child.name);
          return;
        }
        var clonedItem = newSeq.projectItem;
        if (!clonedItem) {
          warnings.push("У клона нет projectItem: " + child.name);
          return;
        }
        // Убираем автоматическую приписку "Copy" — бэкап должен называться идентично
        // оригиналу (уникальность имени внутри бэкап-бина не нужна, это разные бины).
        clonedItem.name = child.name;
        // оригинал -> его копия в бэкапе: из неё runPipeline() восстанавливает упавшую
        // секвенцию перед повторным прогоном (Saturni, 2026-09-24).
        seqMap[String(seq.sequenceID)] = String(newSeq.sequenceID);
        clonedItem.moveBin(destBin);
        // Sequence.clone() открывает вкладку таймлайна для клона — закрываем её сразу,
        // чтобы бэкапы не захламляли UI (сама секвенция в проекте остаётся, .close()
        // только закрывает панель, см. close_sequence в premiere-pro-mcp).
        try { newSeq.close(); } catch (e) {}
    }

    // Рекурсивное зеркалирование содержимого одной папки.
    function mirror(srcBin, destBin) {
      // снимок ДО клонирования: clone() кладёт копию в srcBin и меняет его
      // children "на лету" — итерируемся по замороженному списку.
      var childItems = [];
      for (var i = 0; i < srcBin.children.numItems; i++) childItems.push(srcBin.children[i]);

      for (var i = 0; i < childItems.length; i++) {
        var child = childItems[i];
        if (isBinItem(child)) {
          var newSub = destBin.createBin(child.name);
          mirror(child, newSub);
          continue;
        }
        mirrorOne(child, destBin);
      }
    }

    // Снимок детей "~" ДО создания папок бэкапа — иначе новые папки внутри "⿻" не мешают,
    // но сам список children меняется по ходу клонирования (clone() кладёт копию рядом).
    var tag = "${escapeForExtendScript(tag)}";
    var topItems = [];
    for (var i = 0; i < sourceBin.children.numItems; i++) topItems.push(sourceBin.children[i]);

    var createdNames = [];
    var flatBin = null; // ленивая папка для секвенций, лежащих в "~" плоско
    for (var i = 0; i < topItems.length; i++) {
      var top = topItems[i];
      if (isBinItem(top)) {
        if (top.name === storeName) continue; // склад бэкапов сам себя не бэкапит
        var destName = top.name + "\`" + tag;
        var dest = store.createBin(destName);
        if (!dest) { warnings.push("createBin не сработал для: " + destName); continue; }
        createdNames.push(destName);
        mirror(top, dest);
        continue;
      }
      if (!nodeIdToSeq[top.nodeId]) continue; // не-секвенция в корне "~" — молча пропускаем
      if (!flatBin) {
        var flatName = "${escapeForExtendScript(binName)}\`" + tag;
        flatBin = store.createBin(flatName);
        if (!flatBin) { warnings.push("createBin не сработал для: " + flatName); continue; }
        createdNames.push(flatName);
      }
      mirrorOne(top, flatBin);
    }

    return __result({ backupBinNames: createdNames, warnings: warnings, seqMap: seqMap });
  `);
  return data; // { backupBinNames: string[], warnings: string[], seqMap: {origId: backupId} }
}

// --- Восстановление упавшей секвенции из бэкапа ЭТОГО прогона (Saturni, 2026-09-24):
// копия бэкапа клонируется ещё раз (сам бэкап остаётся нетронутым), клон получает ровно
// исходное имя (без "Copy"), кладётся в ту же папку, что и оригинал, а испорченный
// оригинал удаляется. Возвращает новый sequenceId — секвенция "как была до прогона". ---
export async function restoreFromBackup(target, backupSeqId) {
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
    function seqById(id) {
      for (var i = 0; i < app.project.sequences.numSequences; i++) {
        if (String(app.project.sequences[i].sequenceID) === id) return app.project.sequences[i];
      }
      return null;
    }
    var orig = seqById("${escapeForExtendScript(target.sequenceId)}");
    var backup = seqById("${escapeForExtendScript(backupSeqId)}");
    if (!backup) return __error("Копия в бэкапе не найдена: ${escapeForExtendScript(backupSeqId)}");
    var parentBin = null;
    var binId = "${escapeForExtendScript(target.binNodeId || "")}";
    if (binId) parentBin = findByNodeId(app.project.rootItem, binId);
    if (!parentBin && orig && orig.projectItem) {
      // режим явных имён — папки нет, кладём в рабочий бин по имени
      var stack = [app.project.rootItem];
      while (stack.length && !parentBin) {
        var b = stack.pop();
        for (var i = 0; i < b.children.numItems; i++) {
          var c = b.children[i];
          if (!isBinItem(c)) continue;
          if (c.name === "${escapeForExtendScript(target.workBin || "~")}") { parentBin = c; break; }
          stack.push(c);
        }
      }
    }
    if (!parentBin) return __error("Не нашёл папку для восстановленной секвенции");

    var before = {};
    for (var i = 0; i < app.project.sequences.numSequences; i++) before[app.project.sequences[i].sequenceID] = true;
    backup.clone();
    var fresh = null;
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      var s = app.project.sequences[i];
      if (!before[s.sequenceID]) { fresh = s; break; }
    }
    if (!fresh || !fresh.projectItem) return __error("Не удалось клонировать копию из бэкапа");
    fresh.projectItem.name = "${escapeForExtendScript(target.name)}";
    fresh.projectItem.moveBin(parentBin);
    try { fresh.close(); } catch (e) {}
    if (orig) {
      var accepted = app.project.deleteSequence(orig);
      if (accepted === false) return __error("Premiere не дал удалить испорченную секвенцию");
    }
    return __result({ sequenceId: String(fresh.sequenceID) });
  `);
  return data.sequenceId;
}

// --- Резолвинг целевого списка секвенций внутри бина (рекурсивно) или по явным именам ---
// Натуральная сортировка по имени ("2. Инновации" < "10. X", а не наоборот, как при обычном
// строковом сравнении) — секвенции/входные файлы везде обрабатываются по возрастанию номера
// (Saturni, 2026-09-11), а не в порядке, в котором они лежат в бине/переданы аргументами.
function naturalCompare(a, b) {
  const re = /(\d+)|(\D+)/g;
  const pa = String(a).match(re) || [];
  const pb = String(b).match(re) || [];
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const xa = pa[i] ?? "", xb = pb[i] ?? "";
    const na = Number(xa), nb = Number(xb);
    if (xa !== "" && xb !== "" && !isNaN(na) && !isNaN(nb)) {
      if (na !== nb) return na - nb;
    } else if (xa !== xb) {
      return xa < xb ? -1 : 1;
    }
  }
  return 0;
}
export function sortByNameNatural(items, nameKey = "name") {
  return items.slice().sort((a, b) => naturalCompare(a[nameKey], b[nameKey]));
}

// Сначала по папке, потом по имени (Saturni, 2026-09-24): секвенции, лежащие прямо в "~"
// (folder ""), идут первыми, дальше папки по возрастанию номера ("Series 10" < "Series 11"),
// внутри папки — секвенции по номеру. Иначе "1. Дарят шутки" (Series 10) и "1. Забыла"
// (Series 11) перемешивались через одну.
export function sortTargets(items) {
  return items.slice().sort((a, b) => {
    const fa = a.folder || "", fb = b.folder || "";
    if (fa !== fb) {
      if (fa === "") return -1;
      if (fb === "") return 1;
      const byFolder = naturalCompare(fa, fb);
      if (byFolder !== 0) return byFolder;
    }
    return naturalCompare(a.name, b.name);
  });
}

export async function resolveTargets(binName, cliArgs) {
  if (cliArgs.length > 0) {
    // Сначала — среди секвенций рабочего бина (2026-09-25, живой баг: поиск по всему проекту
    // взял одноимённую копию из бэкапа "⿻", а у неё нет папки бина → 4.1 отверг правильный
    // рендер как «чужой»). Из бина берём и folder/binNodeId, как в режиме без аргументов.
    try {
      const inBin = await listBinSequenceRefs(binName);
      const hits = inBin.filter((r) => cliArgs.includes(r.name));
      if (hits.length > 0 && cliArgs.every((n) => hits.some((r) => r.name === n))) {
        console.log(`Список секвенций задан явно (${cliArgs.length} шт.) — найдены в бине "${binName}".`);
        return sortTargets(hits);
      }
    } catch (e) { /* бина нет — ниже поиск по всему проекту */ }
    // ВНИМАНИЕ: при дублирующихся именах в проекте этот режим неоднозначен — возьмёт
    // первую секвенцию с таким именем в порядке project.sequences. Надёжен только
    // пока имена в проекте уникальны. Предпочтительный режим — без аргументов.
    console.log(`Список секвенций задан явно (${cliArgs.length} шт.), проверка по проекту...`);
    console.log(`  (внимание: при дублях имени возможна неоднозначность — см. режим по бину)`);
    const data = await callClassic(`
      var wanted = ${JSON.stringify(cliArgs)};
      var found = [];
      var missing = [];
      for (var w = 0; w < wanted.length; w++) {
        var hit = null;
        for (var i = 0; i < app.project.sequences.numSequences; i++) {
          if (app.project.sequences[i].name === wanted[w]) { hit = app.project.sequences[i]; break; }
        }
        if (hit) found.push({ name: hit.name, sequenceId: hit.sequenceID });
        else missing.push(wanted[w]);
      }
      return __result({ found: found, missing: missing });
    `);
    if (data.missing.length > 0) {
      throw new Error(`Секвенции не найдены в проекте: ${data.missing.join(", ")}`);
    }
    return sortByNameNatural(data.found);
  }

  console.log(`Аргументы не переданы — беру все секвенции из бина "${binName}" (рекурсивно).`);
  const targets = await listBinSequenceRefs(binName);
  if (targets.length === 0) {
    throw new Error(
      `В бине "${binName}" не нашлось ни одной настоящей секвенции. ` +
      `Проверьте имя бина и что нужные элементы — секвенции, а не клипы.`
    );
  }
  return sortTargets(targets);
}

// --- Общий каркас main(): подключение, бэкап, резолвинг целей, обработка по одной.
// deferDone: true — НЕ считать успешный applyFn финалом секвенции (не эмиттить seq_done
// сразу) — только для скриптов с доп. проходом ПОСЛЕ основного цикла (4.2. Background
// Blur.mjs, летербокс-проход); тогда main() сам зовёт markSeqDone() после всех проходов. ---
const FAKED_FLAKY = new Set();

export async function runPipeline({ binName, applyFn, deferDone = false, beforeRetry = null }) {
  console.log("Подключаюсь к UXP-панели Premiere...");
  await ensureUxpConnected();
  console.log("UXP подключен.\n");

  // Один открытый проект (2026-09-25): при двух проектах activeSequence общая на весь Premiere,
  // UXP начинал сыпать "The script object is no longer valid" (лечилось только перезапуском),
  // а после перезапуска активным оказался другой проект — прогон ушёл не туда.
  const opened = await callClassic(`
    var a = []; for (var i = 0; i < app.projects.numProjects; i++) a.push(app.projects[i].name);
    return __result({ active: app.project.name, all: a });
  `);
  console.log(`Проект: ${opened.active}`);
  if (opened.all.length > 1) {
    throw new Error(`в Premiere открыто ${opened.all.length} проекта (${opened.all.join(", ")}) — ` +
      `оставь открытым только нужный и запусти снова`);
  }

  console.log(`Делаю бэкап бина "${binName}"...`);
  const backup = await backupBin(binName);
  if (backup.backupBinNames.length === 0) {
    console.log(`Бэкапить нечего — в "${binName}" нет ни папок, ни секвенций.`);
  } else {
    console.log(`Бэкап создан в "${BACKUP_BIN_NAME}": ` +
      backup.backupBinNames.map((n) => `"${n}"`).join(", "));
  }
  if (backup.warnings.length > 0) {
    console.log("Предупреждения при бэкапе:");
    backup.warnings.forEach((w) => console.log(`  - ${w}`));
  }
  console.log("");

  const cliArgs = process.argv.slice(2);
  const targets = await resolveTargets(binName, cliArgs);
  targets.forEach((t, i) => { t.key = `#${i + 1}`; });

  console.log(`\nБудут обработаны ${targets.length} секвенций:`);
  targets.forEach((t, i) => console.log(
    `  ${i + 1}. ${t.folder ? t.folder + "/" : ""}${t.name}  (id: ${t.sequenceId})`));
  console.log("");
  emitEvent("batch_start", {
    targets: targets.map((t) => ({ key: t.key, name: t.name, weight: t.durationSeconds || null })),
  });

  // Одна секвенция — в своём try/catch: упавшая (флаки, исчерпанные ретраи, зависший модал)
  // не обрывает весь батч (тот же принцип, что в @tools/3.1. Subtitles Pipeline.py: "one bad clip
  // must not sink the batch"). Возвращает { result } или { error }.
  async function processTarget(target) {
    drainLogBuffer(); // буфер копит только текущую секвенцию (полный лог и так в файле)
    console.log(`=== ${target.name} (id: ${target.sequenceId}) ===`);
    setCurrentSeq(target);
    emitEvent("seq_start", { seq: seqKey(target) });
    try {
      await setActiveSequenceById(target.sequenceId);
      // setActiveSequenceById — только classic-DOM указатель; видимую вкладку Timeline
      // открываем по-настоящему через UXP (sequences.open), иначе Saturni не видит, что
      // скрипт вообще что-то делает (2026-09-09).
      try {
        await callUxpTool(uxpAdvTools.manage_sequences_uxp, { action: "open", sequence_id: target.sequenceId });
      } catch (e) {
        console.log(`  (не удалось открыть вкладку Timeline в UI — продолжаю всё равно: ${e.message})`);
      }
      // Тестовый переключатель (2026-09-24): SATURNI_TEST_FLAKY="<имя секвенции>" — один раз
      // имитирует флаки-сбой моста ПОСЛЕ реальной обработки этой секвенции, чтобы вживую
      // проверить повтор из бэкапа. Без переменной окружения не делает ничего.
      const result = await applyFn(target.name, target.sequenceId, target);
      if (process.env.SATURNI_TEST_FLAKY === target.name && !FAKED_FLAKY.has(target.name)) {
        FAKED_FLAKY.add(target.name);
        throw new Error("The script object is no longer valid. (тестовая имитация)");
      }
      return { result };
    } catch (err) {
      console.log(`  !! ОШИБКА при обработке "${target.name}": ${err.message}`);
      logToFile(err.stack || String(err));
      return { error: err };
    }
  }

  function finish(target, outcome, results, index) {
    const { result, error } = outcome;
    if (error) {
      const log = drainLogBuffer();
      emitEvent("seq_error", { seq: seqKey(target), message: error.message, stack: error.stack, log });
      results[index] = { ...target, result: { skipped: false, error: error.message } };
    } else if (result && result.skipped && result.lose) {
      // "Пропуск", который требует внимания Saturni (нет рендера, рендер устарел, ручной
      // случай не реализован) — не тихий skip, а та же обработка, что у ошибки (2026-09-11).
      const message = result.loseMessage || `требует внимания (${result.reason})`;
      const log = drainLogBuffer();
      console.log(`  !! ТРЕБУЕТ ВНИМАНИЯ "${target.name}": ${message}`);
      emitEvent("seq_error", { seq: seqKey(target), message, log });
      results[index] = { ...target, result: { ...result, error: message } };
    } else {
      results[index] = { ...target, result };
      // seq_done эмиттим СРАЗУ по готовности секвенции (живой баг 2026-09-11: иначе готовые
      // висели на последнем этапе до конца батча). Только 4.2. (deferDone=true, доп.
      // летербокс-проход) финалит сама, через main()+markSeqDone().
      emitEvent("seq_result", { seq: seqKey(target), skipped: !!(result && result.skipped) });
      if (!deferDone) markSeqDone(seqKey(target), { skipped: !!(result && result.skipped) });
    }
  }

  const results = new Array(targets.length);
  const retryQueue = []; // [{ index, target, error }]
  for (let i = 0; i < targets.length; i++) {
    const target = targets[i];
    const outcome = await processTarget(target);
    // Сбой, после которого есть смысл начать секвенцию заново с чистой копии (флаки моста,
    // таймаут Premiere, проваленная финальная проверка — см. isPipelineRetryable). Логические
    // ошибки и lose-пропуски (нет рендера и т.п.) повторять бессмысленно — сразу в итог, но
    // недоделанная секвенция всё равно откатывается к исходнику (см. ниже).
    if (outcome.error && isPipelineRetryable(outcome.error)) {
      console.log(`  -> сбой, повторю "${target.name}" в конце пачки с чистой копии из бэкапа.`);
      emitEvent("seq_requeue", { seq: seqKey(target), message: outcome.error.message });
      retryQueue.push({ index: i, target, error: outcome.error });
      continue;
    }
    if (outcome.error) await rollbackToOriginal(target, outcome.error);
    finish(target, outcome, results, i);
  }

  // --- Повтор упавших (Saturni 2026-09-24, расширено 2026-10-01): секвенция возвращается к
  // состоянию ДО прогона из бэкапа этого же прогона (restoreFromBackup — чистая копия, исходное
  // имя, та же папка; испорченная удаляется), плюс уборка побочных результатов конкретного
  // скрипта (beforeRetry — например, недособранная "` 1v" у 4.1.). До PIPELINE_RETRY_ROUNDS
  // кругов; между кругами — пересинхронизация моста и пауза. Не вышло — секвенция всё равно
  // остаётся в исходном виде (чистая копия из бэкапа), а не полуобработанной. ---
  for (const { index, target, error } of retryQueue) {
    let current = { ...target, originalSequenceId: target.sequenceId }, lastError = error, outcome = null;
    for (let round = 1; round <= PIPELINE_RETRY_ROUNDS; round++) {
      try {
        if (beforeRetry) await beforeRetry(current);
        const newId = await restoreClean(current);
        current = { ...current, sequenceId: newId };
        console.log(`=== Повтор ${round}/${PIPELINE_RETRY_ROUNDS} "${target.name}": восстановлена из бэкапа (новый id ${newId}) ===`);
      } catch (e) {
        console.log(`  !! Повтор "${target.name}" невозможен: ${e.message}`);
        logToFile(e.stack || String(e));
        outcome = { error: lastError };
        break;
      }
      await resyncBridge();
      await sleep(1000 * round);
      outcome = await processTarget(current);
      if (!outcome.error) break;
      lastError = outcome.error;
      if (!isPipelineRetryable(outcome.error)) break;
    }
    if (outcome && outcome.error) await rollbackToOriginal(current, outcome.error);
    finish(current, outcome || { error: lastError }, results, index);
  }
  console.log("\nГотово.");
  return results;

  async function restoreClean(t) {
    const backupId = backup.seqMap && backup.seqMap[String(target_original_id(t))];
    if (!backupId) throw new Error("в бэкапе этого прогона нет копии этой секвенции");
    return restoreFromBackup({ ...t, workBin: binName }, backupId);
  }
  // Ключ бэкапа — id секвенции ДО прогона; у восстановленных копий id новый, поэтому помним исходный.
  function target_original_id(t) { return t.originalSequenceId || t.sequenceId; }
  async function rollbackToOriginal(t, err) {
    try {
      if (!(backup.seqMap && backup.seqMap[String(target_original_id(t))])) return;
      if (beforeRetry) await beforeRetry(t);
      const newId = await restoreClean(t);
      console.log(`  -> "${t.name}" не удалась (${err.message}) — возвращена исходная версия из бэкапа (id ${newId}).`);
    } catch (e) {
      console.log(`  !! Не удалось вернуть исходную версию "${t.name}": ${e.message} — смотри бэкап в "${BACKUP_BIN_NAME}".`);
      logToFile(e.stack || String(e));
    }
  }
}

// Сбой уровня пачки: флаки моста, таймаут Premiere (занят/модальное окно) и проваленная
// финальная проверка скрипта (err.retryable = true) — всё это лечится повтором с чистой копии.
// НЕ путать с withRetry: там повтор ОДНОГО вызова, и таймауты туда сознательно не входят.
export const PIPELINE_RETRY_ROUNDS = Number(process.env.SATURNI_RETRY_ROUNDS || 2);
const PIPELINE_RETRY_RE = /no longer valid|rejected an action|did not finish within|timed out/i;
export function isPipelineRetryable(err) {
  return !!(err && (err.retryable === true || PIPELINE_RETRY_RE.test(err.message || "")));
}
// Ошибка финальной проверки — повторяемая на уровне пачки.
export function verifyError(message) {
  const e = new Error(`проверка не пройдена: ${message}`);
  e.retryable = true;
  return e;
}

export async function shutdown() {
  await uxpBridge.stop();
}

// --- Прогресс-протокол для GUI-лаунчеров (см. @tools/@MJS Launcher.py, статус-бар из
// D:/@Hub/@ Saturni · Status Bar/@StatusBar.py). Когда скрипт запущен НАПРЯМУЮ (node "4.x....mjs" вручную) —
// SATURNI_QUIET_JSON не выставлена, всё работает ровно как раньше: console.log печатает
// как обычно, emitEvent() ничего не делает. Когда запускает python-лаунчер — он выставляет
// SATURNI_QUIET_JSON=1 в окружении дочернего процесса; тогда console.log ПЕРЕХВАТЫВАЕТСЯ
// (складывается в буфер вместо печати — иначе построчный человеческий лог рвёт \033[H\033[J
// перерисовку статус-бара на стороне питона, живое "мерцание" консоли, 2026-09-11), а
// структурные события (смена этапа, начало/конец секвенции, фатальная ошибка) уходят одной
// JSON-строкой за раз через process.stdout.write с уникальным префиксом-меткой — так
// питон-сторона отличает протокольную строку от случайно прорвавшегося сырого текста.
export const QUIET_JSON = process.env.SATURNI_QUIET_JSON === "1";
const PBAR_MARK = "PBAR";

// Полный человеческий лог (включая флаки-ретраи и стеки) в QUIET-режиме пишется в файл,
// путь даёт лаунчер через SATURNI_LOG_FILE (@tools/logs/<скрипт>.log) — на экран он больше
// не попадает вообще (Saturni, 2026-09-24: "не заспамливать скрипт при ошибках").
const LOG_FILE = process.env.SATURNI_LOG_FILE || null;
export function logToFile(line) {
  if (!LOG_FILE) return;
  try { appendFileSync(LOG_FILE, line + "\n", "utf-8"); } catch (e) { /* лог не должен ронять скрипт */ }
}

let logBuffer = [];
const realConsoleLog = console.log.bind(console);
if (QUIET_JSON) {
  console.log = (...args) => {
    const line = args.map((a) => (typeof a === "string" ? a : String(a))).join(" ");
    logBuffer.push(line);
    logToFile(line);
  };
}

// Забирает и очищает накопленный буфер человеческих логов — вызывается при закрытии этапа/
// секвенции (успех — буфер просто отбрасывается вызывающим) или при ошибке (буфер уходит
// в payload события, чтобы питон-лаунчер мог показать "что именно происходило" перед сбоем).
export function drainLogBuffer() {
  const buf = logBuffer;
  logBuffer = [];
  return buf;
}

export function emitEvent(type, payload = {}) {
  if (!QUIET_JSON) return;
  process.stdout.write(PBAR_MARK + JSON.stringify({ type, ...payload }) + "\n");
}

// После runPipeline() отдельные секвенции могли упасть без обрыва всего батча (см. выше) —
// но батч в целом всё равно должен считаться неуспешным (процесс должен упасть/остаться
// открытым в QUIET_JSON-режиме, п.4 запроса Saturni). Вызывать сразу после runPipeline().
export function checkResultsForFailures(results) {
  const failed = results.filter((r) => r.result && r.result.error);
  if (failed.length > 0) {
    const err = new Error(
      `${failed.length} из ${results.length} секвенции(й) завершились с ошибкой: ` +
      failed.map((f) => f.name).join(", ")
    );
    // Только итог — сами ошибки уже ушли по одной через seq_error. runCli() по этому флагу
    // не печатает баннер со стеком и не шлёт отдельный "fatal" (раньше это был дубль-спам).
    err.batchSummary = true;
    throw err;
  }
}

// Короткий алиас для смены этапа внутри applyFn — имена этапов см. в шапке каждого скрипта
// (4.0: Scanning/Duplicating/Trimming/Blending, 4.1: Scanning/Reframing/Building/
// Positioning/Grouping, 4.2: Scanning/Duplicating/Relooping/Blurring/Cropping,
// 4.3: Scanning/Sharpening H/Sharpening V).
export function stage(seqName, stageName) {
  emitEvent("stage", { seq: CURRENT_KEY || seqName, name: stageName });
}

// Служебный ключ секвенции для событий статус-бара (2026-09-24): одноимённые секвенции из
// разных папок раньше склеивались лаунчером в одну строку — события шли по имени.
// На экране по-прежнему только имя (Saturni: без подписей папок), ключ — порядковый номер
// в отсортированном списке целей. target.name не трогаем.
let CURRENT_KEY = null;
export function seqKey(target) {
  return (target && (target.key || target.name)) || "";
}
export function setCurrentSeq(target) {
  CURRENT_KEY = target ? seqKey(target) : null;
}

// Финальный маркер "секвенция окончательно готова" — только его питон-лаунчер трактует как
// сигнал "скрыть задачу из статус-бара" (см. контракт tasks/render() в D:/@Hub/@ Saturni · Status Bar/@StatusBar.py).
// Вызывается из main() каждого скрипта, а не из runPipeline() — см. комментарий у "seq_result".
export function markSeqDone(seqName, extra = {}) {
  emitEvent("seq_done", { seq: seqName, ...extra });
}

// --- Единая обёртка входной точки: заменяет разнобойные `main().catch(...)`/
// `runPipeline(...).catch().finally()`/ручной reportFatal+waitForEnter (было только в 4.1.)
// хвосты во всех 4.x-скриптах. В обычном режиме (запуск напрямую, `node "4.x....mjs"`)
// ведёт себя как проверенный вживую паттерн 4.1.: печатает баннер ошибки И ждёт Enter,
// прежде чем закрыть окно (п.4 запроса Saturni — держать консоль открытой на любой
// необработанной ошибке, закрывать сразу только при чистом успехе). Ловит и
// unhandledRejection — раньше это было только в 4.1., теперь одинаково во всех скриптах.
// В QUIET_JSON-режиме (запущено из питон-лаунчера) вместо печати+ожидания эмиттит одно
// событие "fatal" с текстом ошибки, стеком и накопленным логом и сразу завершается —
// "держать окно открытым" в этом режиме делает питон-лаунчер (см. @tools/@MJS Launcher.py),
// а не сам node-процесс (стдин которого лаунчеру не пробрасывается).
export async function runCli(mainFn) {
  const onFatal = async (label, err) => {
    const log = drainLogBuffer();
    const batchSummary = !!(err && err.batchSummary);
    logToFile(`=== ${label}: ${err && err.message} ===`);
    if (!batchSummary && err && err.stack) logToFile(err.stack);
    if (QUIET_JSON) {
      emitEvent("fatal", { message: err && err.message, stack: err && err.stack, log, label, batchSummary });
    } else if (batchSummary) {
      realConsoleLog(`\n${err.message}`);
    } else {
      realConsoleLog("\n\n========================================");
      realConsoleLog(`ОШИБКА (${label}) — скрипт остановился.`);
      realConsoleLog("========================================");
      realConsoleLog(err && err.stack ? err.stack : String(err));
      realConsoleLog("========================================");
    }
    try { await shutdown(); } catch (e) { /* мост уже мог быть недоступен */ }
    if (!QUIET_JSON) {
      process.stdout.write("\nНажми Enter, чтобы закрыть окно...");
      await new Promise((resolve) => {
        process.stdin.resume();
        process.stdin.once("data", resolve);
      });
    }
    process.exit(1);
  };

  process.on("unhandledRejection", (err) => { onFatal("необработанное исключение внутри промиса", err); });

  try {
    await mainFn();
    await shutdown();
    process.exit(0);
  } catch (err) {
    await onFatal("исключение в main()", err);
  }
}
