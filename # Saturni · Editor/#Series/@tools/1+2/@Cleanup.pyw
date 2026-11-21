# -*- coding: utf-8 -*-
"""Завершение серии, без консоли: двойной клик в папке «Серия N», Premiere с проектом открыт.
Сначала Premiere: выбранные секвенции едут из папок режимов в общий бин серии, с итоговым номером и режимом в Comment.
Потом файлы: номера подряд, значки снимаются, к имени добавляется « ` 1h», выбор дописывается в основной файл разбора, папки режимов уходят в Корзину.
При любой ошибке показывает окно и останавливается; запустить можно снова. В конце удаляет сам себя.
Копию с настройками кладёт сюда «11. Deploy Cleanup.py»."""
import ctypes
import ctypes.wintypes
import datetime
import json
import os
import re
import subprocess
import tempfile
import traceback
import unicodedata

ANALYSIS_ROOT = r"__ANALYSIS_ROOT__"
TOOLS = r"__TOOLS__"
RUN = "__RUN__"
STEM = "__STEM__"
BIN = "__BIN__"
MOMENTS = __MOMENTS__

VIDEO = {".mp4", ".mov", ".mkv"}
DRAFT = re.compile(r"^\+.*$|^\d+\.\s*(Active|Faster|Medium)$")
HERE = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = 0x08000000


class Stop(Exception):
    """Понятная ошибка для окна: дальше не идём."""


JSX = r"""
var PLAN=__PLAN__,BIN=__BINNAME__,COMMENT="Column.PropertyText.Comment",URI="http://ns.adobe.com/premierePrivateProjectMetaData/1.0/";
function child(b,n,t){for(var i=0;i<b.children.numItems;i++){var c=b.children[i];if(c.name==n&&(t==undefined||c.type==t))return c}return null}
function seqOf(it){for(var i=0;i<app.project.sequences.numSequences;i++){var s=app.project.sequences[i];if(s.projectItem&&s.projectItem.nodeId==it.nodeId)return s}return null}
function comment(it){var c=JSON.parse(it.getProjectColumnsMetadata());for(var i=0;i<c.length;i++)if(c[i].ColumnID==COMMENT)return c[i].ColumnValue;return ""}
function setComment(it,v){if(ExternalObject.AdobeXMPScript===undefined)ExternalObject.AdobeXMPScript=new ExternalObject("lib:AdobeXMPScript");
  XMPMeta.registerNamespace(URI,"premierePrivateProjectMetaData");var x=new XMPMeta(it.getProjectMetadata());x.setProperty(URI,COMMENT,v);it.setProjectMetadata(x.serialize(),[COMMENT])}
var bin=child(app.project.rootItem,BIN,2);
if(!bin)return __result({err:"В проекте нет бина "+BIN});
var bad=[],todo=[];
for(var i=0;i<PLAN.length;i++){var p=PLAN[i],done=child(bin,""+p.new,1);
  if(done&&comment(done)==p.note)continue;
  if(done){bad.push("В бине "+BIN+" уже есть секвенция "+p.new);continue}
  var cat=child(bin,p.cat,2),it=cat?child(cat,""+p.src,1):null;
  if(!it){bad.push("Нет секвенции "+BIN+"\\"+p.cat+"\\"+p.src);continue}
  todo.push({p:p,it:it})}
if(bad.length)return __result({err:bad.join("\n")});
for(var i=0;i<todo.length;i++){var t=todo[i],q=seqOf(t.it);t.it.moveBin(bin);t.it.name=""+t.p.new;if(q)q.name=""+t.p.new;setComment(t.it,t.p.note)}
var out=[];for(var i=0;i<PLAN.length;i++){var it=child(bin,""+PLAN[i].new,1);out.push({n:PLAN[i].new,c:it?comment(it):null})}
app.project.save();
return __result({ok:out});
"""
PING = 'return __result({path:app.project.path});'
ENDS = r"""
var BIN=__BINNAME__,out=[];
function child(b,n,t){for(var i=0;i<b.children.numItems;i++){var c=b.children[i];if(c.name==n&&(t==undefined||c.type==t))return c}return null}
function seqOf(it){for(var i=0;i<app.project.sequences.numSequences;i++){var s=app.project.sequences[i];if(s.projectItem&&s.projectItem.nodeId==it.nodeId)return s}return null}
var bin=child(app.project.rootItem,BIN,2);
if(!bin)return __result({err:"В проекте нет бина "+BIN});
for(var i=0;i<bin.children.numItems;i++){var c=bin.children[i];if(c.type!=2)continue;
  for(var j=0;j<c.children.numItems;j++){var it=c.children[j];if(it.type!=1||!/^\d+$/.test(it.name))continue;
    var q=seqOf(it);if(q)out.push({cat:c.name,n:parseInt(it.name,10),end:parseFloat(q.end)/254016000000})}}
return __result({ok:out});
"""


def premiere(code, timeout):
    """Выполнить скрипт в Premiere через мост. Нет связи — Stop."""
    fd, path = tempfile.mkstemp(suffix=".jsx", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        r = subprocess.run(["node", "pp.mjs", path, str(timeout * 1000)], cwd=TOOLS, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout + 15, creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise Stop("Не запустился node или нет папки инструментов:\n" + TOOLS)
    except subprocess.TimeoutExpired:
        raise Stop("Premiere не ответил. Он открыт и панель плагина загружена?")
    finally:
        os.remove(path)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    if last.startswith("{"):
        return json.loads(last)
    raise Stop("Нет связи с Premiere. Открой проект и запусти снова.\n\n" + (last or r.stderr[-400:]))


def clean(name):
    """Убрать значки любого рода, бэктик остаётся: это категория Sk."""
    kept = "".join(c for c in name if unicodedata.category(c) != "So" and c != "️")
    return re.sub(r" {2,}", " ", kept)


def number(name):
    m = re.match(r"\s*(\d+)", clean(name))
    return int(m.group(1)) if m else None


def numbered_files():
    groups = {}
    for f in os.listdir(HERE):
        if os.path.isfile(os.path.join(HERE, f)) and number(f) is not None:
            groups.setdefault(number(f), []).append(f)
    return groups


def draft_folders():
    return sorted(d for d in os.listdir(HERE) if os.path.isdir(os.path.join(HERE, d)) and DRAFT.match(d))


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def seq_ends():
    """Длина каждой нумерованной секвенции в папках режимов бина серии: {(папка, номер): секунды}."""
    res = premiere(ENDS.replace("__BINNAME__", json.dumps(BIN, ensure_ascii=False)), 120)
    if "err" in res:
        raise Stop("Premiere: " + res["err"])
    return {(e["cat"], e["n"]): e["end"] for e in res["ok"]}


def source_of(path, name, folders, ends):
    """Откуда ролик. 1) Тот же размер, что у рендера в папке режима (копия). 2) Длина файла = длина секвенции
    с тем же номером в одной из папок режимов Premiere (ролик перерендерили из секвенции, может быть, с правками).
    3) Файл перенесли: режим — папка, где этого номера не стало."""
    size = os.path.getsize(path)
    for d in sorted(folders, key=lambda x: x.startswith("+")):
        root = os.path.join(HERE, d)
        for f in os.listdir(root):
            p = os.path.join(root, f)
            if os.path.isfile(p) and os.path.getsize(p) == size and number(f) is not None:
                return d.lstrip("+"), number(f)
    n = number(name)
    dur = duration(path)
    modes = [d for d in folders if not d.startswith("+")]
    if dur:
        near = sorted((abs(ends[(d, n)] - dur), d) for d in modes if (d, n) in ends)
        if near and near[0][0] < 0.05 and (len(near) == 1 or near[1][0] - near[0][0] > 0.02):
            return near[0][1], n
    missing = [d for d in modes if not any(number(f) == n for f in os.listdir(os.path.join(HERE, d)))]
    if len(missing) == 1:
        return missing[0], n
    got = ", ".join(f"{d}: {ends[(d, n)]:.2f} с" for d in modes if (d, n) in ends)
    raise Stop(f"Не понял, из какого режима ролик «{name}» ({dur or 0:.2f} с).\nСеквенции №{n} в Premiere: {got}.\n"
               "Длина файла должна совпасть с длиной секвенции, из которой он отрендерен. Ничего не изменено.")


def make_plan(folders, ends):
    groups = numbered_files()
    plan = []
    for new, old in enumerate(sorted(groups), 1):
        video = next((f for f in groups[old] if os.path.splitext(f)[1].lower() in VIDEO), None)
        if video:
            cat, src = source_of(os.path.join(HERE, video), video, folders, ends)
            m = MOMENTS.get(src, {})
            # Comment: откуда ролик — режим, серия, номер в разметке, название (номера после выбора меняются)
            note = f"{cat} · {STEM} №{src} «{m.get('name', '?')}»"
            plan.append({"new": new, "src": src, "cat": cat, "note": note})
    return groups, plan


def check_project():
    path = premiere(PING, 40).get("path", "")
    if os.path.normcase(os.path.dirname(path)) != os.path.normcase(os.path.dirname(HERE)):
        raise Stop(f"В Premiere открыт другой проект:\n{path}")


def apply_premiere(plan):
    code = JSX.replace("__PLAN__", json.dumps(plan, ensure_ascii=False)).replace("__BINNAME__", json.dumps(BIN, ensure_ascii=False))
    res = premiere(code, 120)
    if "err" in res:
        raise Stop("Premiere: ничего не перенесено.\n\n" + res["err"])
    wrong = [r["n"] for r, p in zip(res["ok"], plan) if r["c"] != p["note"]]
    if wrong:
        raise Stop(f"Premiere: не сошлись секвенции {wrong}. Файлы не тронуты, проверь бин {BIN}.")


TAG = chr(96) + " 1h"          # метка сдачи: «1 ` 1h.mp4»


def final_name(new, f):
    """Новый номер, без значка, с меткой сдачи перед расширением: «5 🔥.mp4» → «1 ` 1h.mp4»."""
    base, ext = os.path.splitext(clean(f))
    stem = base[len(re.match(r"\s*\d+", base).group()):].strip()
    if TAG not in stem:
        stem = (stem + " " + TAG).strip()
    return f"{new} {stem}{ext}"


def renumber(groups):
    pairs = []
    for new, old in enumerate(sorted(groups), 1):
        for f in groups[old]:
            pairs.append((f, final_name(new, f)))
    finals = [b.casefold() for _, b in pairs]
    if len(finals) != len(set(finals)):
        raise Stop("Два файла получат одно имя. Проверь, нет ли одного ролика дважды.")
    for i, (f, _) in enumerate(pairs):
        os.rename(os.path.join(HERE, f), os.path.join(HERE, f"~renum{i}.tmp"))
    for i, (_, n) in enumerate(pairs):
        os.rename(os.path.join(HERE, f"~renum{i}.tmp"), os.path.join(HERE, n))


def run_dir():
    for name in (f"(!) {RUN}", RUN):
        p = os.path.join(ANALYSIS_ROOT, name)
        if os.path.isdir(p):
            return p
    p = os.path.join(ANALYSIS_ROOT, f"(!) {RUN}")
    os.makedirs(p)
    return p


def write_choice(plan):
    """Выбор — в основной файл разбора, анализ потом продолжается там же."""
    path = os.path.join(run_dir(), f"#{RUN}.md")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else f"# Разбор {RUN}\n"
    head = f"## Выбор {STEM}"
    if head in text:
        return
    taken = {p["src"] for p in plan}
    lines = ["", f"{head} ({datetime.date.today():%d.%m.%Y})", "", f"Взято {len(plan)} из {len(MOMENTS)}.", "",
             "| Итог | № | Момент | Режим | Пометка |", "|---|---|---|---|---|"]
    for p in plan:
        m = MOMENTS.get(p["src"], {})
        lines.append(f"| {p['new']} | {p['src']} | {m.get('name', '?')} | {p['cat']} | {m.get('rate', '')} |")
    rest = [n for n in sorted(MOMENTS) if n not in taken]
    if rest:
        lines += ["", "Не взято:", ""] + [f"- {n}. {MOMENTS[n]['name']} {MOMENTS[n].get('rate', '')}".rstrip() for n in rest]
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n" + "\n".join(lines) + "\n")
    # то же в JSON: итоговый номер → режим и номер в разметке (для сравнения готовых роликов с моими версиями)
    with open(os.path.join(run_dir(), f"choice_{STEM}.json"), "w", encoding="utf-8") as f:
        json.dump([dict(p, name=MOMENTS.get(p["src"], {}).get("name", "")) for p in plan], f, ensure_ascii=False, indent=1)


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.wintypes.HWND), ("wFunc", ctypes.wintypes.UINT), ("pFrom", ctypes.wintypes.LPCWSTR),
                ("pTo", ctypes.wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", ctypes.wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.wintypes.LPCWSTR)]


def to_recycle(path):
    FO_DELETE, ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, path + "\0", None, ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted:
        raise Stop(f"Не удалось удалить папку, код {code}:\n{path}\nЗакрой её в Проводнике и запусти снова.")


def refresh():
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def main():
    folders = draft_folders()
    if not folders:
        raise Stop("Рядом нет папок режимов, значит, серия уже завершена.")
    check_project()
    groups, plan = make_plan(folders, seq_ends())
    if not plan:
        raise Stop("В папке серии нет выбранных роликов.")
    apply_premiere(plan)
    renumber(groups)
    write_choice(plan)
    for d in folders:
        to_recycle(os.path.join(HERE, d))
    refresh()
    ctypes.windll.user32.MessageBoxW(0, f"Роликов по порядку: {len(plan)}\nPremiere: бин {BIN} обновлён, проект сохранён\n"
                                        f"Выбор записан в #{RUN}.md\nПапки режимов в Корзине: {len(folders)}", "Серия готова", 0x40)
    os.remove(os.path.abspath(__file__))


if __name__ == "__main__":
    try:
        main()
    except Stop as e:
        ctypes.windll.user32.MessageBoxW(0, str(e), "Серия: остановлено", 0x30)
    except Exception:
        ctypes.windll.user32.MessageBoxW(0, traceback.format_exc(), "Серия: ошибка", 0x10)
