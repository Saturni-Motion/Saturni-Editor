// Обёртка: node pp.mjs <файл.jsx> — выполнить ExtendScript в Premiere через мост скриптов (порт 7778)
import { readFileSync } from "node:fs";
import { callClassic } from "../mjs/@Premiere Lib.mjs";
const code = readFileSync(process.argv[2], "utf8");
const timer = setTimeout(() => { console.log("TIMEOUT"); process.exit(2); }, Number(process.argv[3] || 120000));
try {
  const r = await callClassic(code);
  clearTimeout(timer);
  console.log(typeof r === "string" ? r : JSON.stringify(r));
  process.exit(0);
} catch (e) { console.log("ERR", e.message); process.exit(1); }
