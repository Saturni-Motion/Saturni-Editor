# -*- coding: utf-8 -*-
"""
@SRT Markers.py — маркеры в строке номера блока SRT -> оформление титра в ASS.

Используется рендером #2Stage-*.py и мини-приложением Subs Move (# Saturni · Subs Move/ в корне):
превью в приложении строится этой же функцией и тем же libass — 1:1 с рендером.

    3 %50@#100[w]
    00:00:01,480 --> 00:00:02,393
    моменты.

Маркеры (после номера блока, в любом порядке):
    ^N            кегль: +N к стандартному (^-N — меньше)
    #N            непрозрачность тени 0..100 (по умолчанию 80 — это Sub_Shadow_Alpha "33"); #0 — без тени
    #w  #wN       белая тень (N — её непрозрачность)
    %N            непрозрачность текста 0..100 (по умолчанию 100)
    !             без тени, чёрный текст
    @             SemiBold
    [] [N] [w] [wN]   подложка: тёмная / белая (w), N — непрозрачность подложки 0..100
    ↑N ↓N ←N →N   сдвиг блока от базовой позиции, px (в базе 1920×1080 / 1080×1920)
    ` N           (старое, как было в 2Stage) отступ низа титра от нижнего края кадра, px

Раздельно для горизонтали и вертикали:  «3 H: ↑20[] · V: ↑200[]»  или  «3 V: ↑200[]»
(без префикса — для обоих; ориентация рендера определяется по разрешению: res_y > res_x -> V).

Подключение к #2Stage-*.py (две строки):
    sm = _tool("srt_markers", "@SRT Markers.py")   # вверху, рядом с rb = _tool("render_batch", ...)
    ...
    # в srt_to_ass() вместо цикла по блокам SRT:
    ass_lines += sm.events_from_srt(srt_path, res_x, res_y, center_x, curr_sub_y, sm.style_from(globals()))

Блоки без маркеров дают ровно те же строки ASS, что и старый цикл — значения по умолчанию
берутся из констант самого скрипта (Sub_Font_Size, Sub_Shadow_Alpha, Sub_Shadow_Offset, ...).
Общие значения можно поменять из Subs Studio (кнопка Resettings) — они пишутся в
srt_markers.json рядом с этим файлом и тогда действуют на все 2Stage-рендеры.
"""

import os
import re
import json

HERE = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_PATH = os.path.join(HERE, "@SRT Markers.json")
DEFAULT_ADDS = r"D:\# Video\#Поляна\@Render\@adds"

# Значения по умолчанию = то, что сейчас стоит в #2Stage-Rutube.py / Premier.py.
DEFAULTS = {
    "font_name": "Fira Sans Extra Condensed",
    "font_file": os.path.join(DEFAULT_ADDS, "FiraSansExtraCondensed-Regular.ttf"),
    "bold_name": "Fira Sans Extra Condensed SemiBold",
    "bold_file": os.path.join(DEFAULT_ADDS, "FiraSansExtraCondensed-SemiBold.ttf"),
    "font_size": 70,
    "text_opacity": 100,
    "shadow_alpha": "33",        # как в скрипте: ASS-альфа тела тени ("00" видимая, "FF" прозрачная)
    "shadow_opacity": 80,        # то же в процентах непрозрачности: 255·(1−0.8) = 51 = 0x33
    "shadow_x": 2, "shadow_y": 2,
    "shadow_blur": 2,
    "shadow_bord": None,         # Rutube: \bord0 + \3a в строке тени; Premier — без них (None)
    "shadow_bord_alpha": "33",
    "plate_opacity": 50,         # как [plate] в Saturni · Batch
    "plate_radius": 20,
    "plate_pad_x": 24,
    "plate_pad_y": 10,
    "base_y_h": 920,             # Sub_Y_Pos_H / Sub_Y_Pos_V — только для приложения
    "base_y_v": 1520,
}
# что можно переопределить из приложения (srt_markers.json)
OVERRIDABLE = ("font_size", "text_opacity", "shadow_opacity", "shadow_x", "shadow_y", "shadow_blur",
               "plate_opacity", "plate_radius", "plate_pad_x", "plate_pad_y")

_TOKEN = re.compile(r"\^\s*(?P<size>-?\d+)|#\s*(?:(?P<shw>[wW])\s*(?P<shwn>\d*)|(?P<sh>\d+))|%\s*(?P<op>\d+)|(?P<black>!)|(?P<bold>@)"
                    r"|\[\s*(?P<pw>[wW]?)\s*(?P<pn>\d*)\s*\]|(?P<arrow>[↑↓←→])\s*(?P<an>-?\d+)|`\s*(?P<margin>\d+)")


# ═══════════════════════════ маркеры ═══════════════════════════
_ORI = re.compile(r"^\s*([HhVvНнВв])\s*:\s*(.*?)\s*$")


def split_hv(s):
    """«H: ↑20[] · V: ↑200[]» -> {'h': '↑20[]', 'v': '↑200[]'}.
    Без префикса — для обоих; «V: ↑200[]» — только для вертикали (горизонталь без маркеров)."""
    common, h, v = None, None, None
    for seg in re.split(r"[·|]", s or ""):
        r = _ORI.match(seg)
        if r:
            if r.group(1) in "HhНн":
                h = r.group(2)
            else:
                v = r.group(2)
        elif seg.strip():
            common = seg.strip()
    return {"h": h if h is not None else (common or ""), "v": v if v is not None else (common or "")}


def join_hv(h, v):
    """Обратно в строку: одинаковые -> без префикса, иначе «H: … · V: …» (пустые не пишутся)."""
    h, v = (h or "").strip(), (v or "").strip()
    if h == v:
        return h
    return " · ".join(p for p in ([f"H: {h}"] if h else []) + ([f"V: {v}"] if v else []))


def pick(s, orient):
    """Маркеры для ориентации 'h' / 'v'."""
    return split_hv(s)["v" if orient == "v" else "h"]


def canon(s):
    """Каноническая запись полной строки маркеров (обе ориентации)."""
    d = split_hv(s)
    return join_hv(format_markers(parse_markers(d["h"])), format_markers(parse_markers(d["v"])))


def parse_markers(s):
    """«↑150[]» -> dict. Нераспознанные символы игнорируются."""
    m = {"size": None, "shadow": None, "shadow_white": False, "opacity": None, "black": False, "bold": False,
         "plate": False, "plate_white": False, "plate_opacity": None, "dx": 0, "dy": 0, "margin": None}
    for t in _TOKEN.finditer(s or ""):
        g = t.groupdict()
        size, op, black, bold, pw, pn, arrow, an, margin = (g[k] for k in ("size", "op", "black", "bold", "pw", "pn", "arrow", "an", "margin"))
        if size is not None:
            m["size"] = int(size)
        elif g["shw"]:                          # #w / #wN — белая тень (N — непрозрачность)
            m["shadow_white"] = True
            if g["shwn"]:
                m["shadow"] = max(0, min(100, int(g["shwn"])))
        elif g["sh"] is not None:
            m["shadow"] = max(0, min(100, int(g["sh"])))
        elif op is not None:
            m["opacity"] = max(0, min(100, int(op)))
        elif black:
            m["black"] = True
        elif bold:
            m["bold"] = True
        elif arrow:
            n = int(an)
            if arrow == "↑":
                m["dy"] -= n
            elif arrow == "↓":
                m["dy"] += n
            elif arrow == "←":
                m["dx"] -= n
            else:
                m["dx"] += n
        elif margin is not None:
            m["margin"] = int(margin)
        else:                                   # подложка
            m["plate"] = True
            m["plate_white"] = bool(pw)
            m["plate_opacity"] = max(0, min(100, int(pn))) if pn else None
    return m


def format_markers(m):
    """dict -> каноническая строка маркеров (тот же порядок, что в Subs Studio)."""
    o = ""
    if m.get("margin") is not None:
        o += f"`{m['margin']}"
    dy, dx = int(m.get("dy") or 0), int(m.get("dx") or 0)
    if dy < 0:
        o += f"↑{-dy}"
    elif dy > 0:
        o += f"↓{dy}"
    if dx < 0:
        o += f"←{-dx}"
    elif dx > 0:
        o += f"→{dx}"
    if m.get("size"):
        o += f"^{m['size']}"
    if m.get("opacity") is not None:
        o += f"%{m['opacity']}"
    if m.get("bold"):
        o += "@"
    if m.get("shadow") is not None or m.get("shadow_white"):
        o += "#" + ("w" if m.get("shadow_white") else "") + ("" if m.get("shadow") is None else str(m["shadow"]))
    if m.get("black"):
        o += "!"
    if m.get("plate"):
        o += "[" + ("w" if m.get("plate_white") else "") + ("" if m.get("plate_opacity") is None else str(m["plate_opacity"])) + "]"
    return o


# ═══════════════════════════ SRT ═══════════════════════════
_TS = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})")


def srt_ms(t):
    m = _TS.search(t or "")
    if not m:
        return 0
    h, mi, s, ms = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0"))


def ms_srt(ms):
    ms = max(0, int(round(ms)))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ass_time(srt_time):
    """Ровно как convert_srt_time() в 2Stage: «00:00:00,872» -> «0:00:00.87» (сотые обрезаются)."""
    srt_time = srt_time.strip().replace(",", ".")
    parts = srt_time.split(":")
    if len(parts) == 3:
        return f"{int(parts[0])}:{parts[1]}:{parts[2][:5]}"
    return "0:00:00.00"


def ms_ass(ms):
    return ass_time(ms_srt(ms))


def parse_srt(content):
    """Текст SRT -> список блоков {num, mk, start, end, start_raw, end_raw, lines}.
    Разбивка — как в 2Stage (пустая строка между блоками, нужен '-->' во второй строке)."""
    out = []
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        if "-->" in lines[0]:                   # блок без номера
            lines = [""] + lines
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        r = re.match(r"\s*(\d*)\s*(.*?)\s*$", lines[0])
        a, b = lines[1].split("-->", 1)
        out.append({"num": int(r.group(1)) if r.group(1) else None, "mk": r.group(2),
                    "start_raw": a.strip(), "end_raw": b.strip(), "start": srt_ms(a), "end": srt_ms(b),
                    "lines": lines[2:]})
    return out


def write_srt(blocks, newline="\r\n"):
    """Блоки {mk, start, end, text} -> текст SRT (номера по порядку, маркеры через пробел)."""
    parts = []
    for i, b in enumerate(blocks, 1):
        mk = (b.get("mk") or "").strip()
        text = (b.get("text") or "").replace("\r\n", "\n").strip("\n")
        parts.append("\n".join([f"{i} {mk}" if mk else str(i), f"{ms_srt(b['start'])} --> {ms_srt(b['end'])}", text]))
    return newline.join("\n\n".join(parts).split("\n")) + newline


# ═══════════════════════════ стиль ═══════════════════════════
def load_overrides():
    try:
        with open(OVERRIDES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k in OVERRIDABLE}
    except Exception:
        return {}


def save_overrides(d):
    d = {k: v for k, v in d.items() if k in OVERRIDABLE}
    tmp = OVERRIDES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OVERRIDES_PATH)


def _alpha_to_op(a):
    try:
        return int(round((1 - int(a, 16) / 255) * 100))
    except Exception:
        return DEFAULTS["shadow_opacity"]


def _op_to_alpha(op):
    return f"{int(round(255 * (1 - max(0, min(100, op)) / 100))):02X}"


def style_from(g=None, overrides=True):
    """Стиль из констант скрипта (globals() #2Stage-*.py) + srt_markers.json.
    Без аргументов — значения по умолчанию (как в Rutube)."""
    g = g or {}
    st = dict(DEFAULTS)
    if g.get("Sub_Font_Name"):
        st["font_name"] = g["Sub_Font_Name"]
        st["bold_name"] = g["Sub_Font_Name"] + " SemiBold"
    if g.get("Sub_Font_Path"):
        st["font_file"] = g["Sub_Font_Path"]
        st["bold_file"] = re.sub(r"-Regular(\.\w+)$", r"-SemiBold\1", g["Sub_Font_Path"])
    if g.get("Sub_Font_Size"):
        st["font_size"] = g["Sub_Font_Size"]
    if g.get("Sub_Shadow_Alpha"):
        st["shadow_alpha"] = g["Sub_Shadow_Alpha"]
        st["shadow_opacity"] = _alpha_to_op(g["Sub_Shadow_Alpha"])
    if g.get("Sub_Shadow_Offset") is not None:
        st["shadow_x"] = st["shadow_y"] = g["Sub_Shadow_Offset"]
    if g.get("Sub_Shadow_Blur") is not None:
        st["shadow_blur"] = g["Sub_Shadow_Blur"]
    if "Sub_Shadow_Bord" in g:
        st["shadow_bord"] = g["Sub_Shadow_Bord"]
        st["shadow_bord_alpha"] = g.get("Sub_Shadow_Bord_Alpha", st["shadow_alpha"])
    if g.get("Sub_Y_Pos_H"):
        st["base_y_h"] = g["Sub_Y_Pos_H"]
    if g.get("Sub_Y_Pos_V"):
        st["base_y_v"] = g["Sub_Y_Pos_V"]
    st["_style_fs"] = st["font_size"]           # кегль в Style: строке скрипта — \fs только если отличается
    if overrides:
        ov = load_overrides()
        if "shadow_opacity" in ov and ov["shadow_opacity"] != st["shadow_opacity"]:
            st["shadow_alpha"] = st["shadow_bord_alpha"] = _op_to_alpha(ov["shadow_opacity"])
        st.update(ov)
    return st


# ═══════════════════════════ замер текста (для подложки) ═══════════════════════════
_fonts = {}


def _font(path, fs):
    """PIL-шрифт того же размера, что у libass: libass масштабирует так, что
    usWinAscent+usWinDescent = Fontsize, PIL — по em. Отсюда пересчёт."""
    key = (path, fs)
    if key not in _fonts:
        from PIL import ImageFont
        em = fs
        try:
            from fontTools.ttLib import TTFont
            t = TTFont(path, lazy=True)
            em = fs * t["head"].unitsPerEm / (t["OS/2"].usWinAscent + t["OS/2"].usWinDescent)
        except Exception:
            em = fs / 1.2
        _fonts[key] = (ImageFont.truetype(path, max(1, int(round(em * 4)))), em)   # ×4 — точнее замер
    return _fonts[key]


def text_box(lines, path, fs):
    """Ширины строк и метрики (px в координатах ASS)."""
    try:
        f, em = _font(path, fs)
        widths = [f.getlength(ln) / 4 for ln in lines]
    except Exception:
        em = fs / 1.2
        widths = [len(ln) * fs * 0.36 for ln in lines]
    return widths, em


def _rrect(x0, y0, x1, y1, r):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    k = r * 0.4477                               # 1 − 0.5523: безье-четверть окружности
    f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")
    p = [f"m {f(x0 + r)} {f(y0)}", f"l {f(x1 - r)} {f(y0)}",
         f"b {f(x1 - k)} {f(y0)} {f(x1)} {f(y0 + k)} {f(x1)} {f(y0 + r)}", f"l {f(x1)} {f(y1 - r)}",
         f"b {f(x1)} {f(y1 - k)} {f(x1 - k)} {f(y1)} {f(x1 - r)} {f(y1)}", f"l {f(x0 + r)} {f(y1)}",
         f"b {f(x0 + k)} {f(y1)} {f(x0)} {f(y1 - k)} {f(x0)} {f(y1 - r)}", f"l {f(x0)} {f(y0 + r)}",
         f"b {f(x0)} {f(y0 + k)} {f(x0 + k)} {f(y0)} {f(x0 + r)} {f(y0)}"]
    return " ".join(p)


# ═══════════════════════════ ASS ═══════════════════════════
def block_events(m, text_lines, start_ass, end_ass, res_y, cx, base_y, st):
    """Строки Dialogue одного блока. m — dict из parse_markers()."""
    text = "\\N".join(text_lines)
    y = (res_y - m["margin"]) if m.get("margin") is not None else base_y
    x, y = cx + int(m.get("dx") or 0), y + int(m.get("dy") or 0)
    fs = st["font_size"] + int(m.get("size") or 0)
    extra = ""                                   # теги поверх стиля — пусто у блока без маркеров
    if fs != st["_style_fs"]:
        extra += f"\\fs{fs}"
    if m.get("bold"):
        extra += f"\\fn{st['bold_name']}"
    out = []
    an = "\\an2" if st.get("align", 2) == 2 else ""       # align=5 (Иви): центр по точке \pos, стиль без \an-тега

    if m.get("plate"):
        widths, em = text_box(text_lines, st["bold_file"] if m.get("bold") else st["font_file"], fs)
        n, w = len(text_lines), max(widths or [0])
        desc = fs * 265 / 1200                   # нижний вынос (Fira: winDescent/(winAscent+winDescent))
        base_last = (y + n * fs / 2 - desc) if st.get("align", 2) == 5 else (y - desc)   # базовая линия нижней строки
        top = base_last - (n - 1) * fs - 0.70 * em - st["plate_pad_y"]
        bot = base_last + 0.14 * em + st["plate_pad_y"]
        x0, x1 = x - w / 2 - st["plate_pad_x"], x + w / 2 + st["plate_pad_x"]
        pop = m["plate_opacity"] if m.get("plate_opacity") is not None else st["plate_opacity"]
        col = "FFFFFF" if m.get("plate_white") else "000000"
        out.append(f"Dialogue: 0,{start_ass},{end_ass},TS_Shadow,,0,0,0,,"
                   f"{{\\an7\\pos(0,0)\\bord0\\shad0\\blur0\\1c&H{col}&\\1a&H{_op_to_alpha(pop)}&\\p1}}"
                   f"{_rrect(x0, top, x1, bot, st['plate_radius'])}\n")

    sh = 0 if m.get("black") else (m["shadow"] if m.get("shadow") is not None else st["shadow_opacity"])
    if sh > 0:
        a = st["shadow_alpha"] if m.get("shadow") is None else _op_to_alpha(sh)
        sc = "FFFFFF" if m.get("shadow_white") else "000000"       # #w — белая тень
        if st.get("shadow_bord") is not None:   # формат Rutube
            ba = st["shadow_bord_alpha"] if m.get("shadow") is None else a
            tags = f"{an}\\c&H{sc}&\\3c&H{sc}&\\bord{st['shadow_bord']}\\1a&H{a}&\\3a&H{ba}&\\blur{st['shadow_blur']}"
        else:                                    # формат Premier
            tags = f"{an}\\c&H{sc}&\\1a&H{a}&\\blur{st['shadow_blur']}"
        out.append(f"Dialogue: 0,{start_ass},{end_ass},TS_Shadow,,0,0,0,,"
                   f"{{{tags}\\pos({x + st['shadow_x']},{y + st['shadow_y']}){extra}}}{text}\n")

    tx = extra
    if m.get("black"):
        tx += "\\c&H000000&"
    op = m["opacity"] if m.get("opacity") is not None else st["text_opacity"]
    if op != 100:
        tx += f"\\1a&H{_op_to_alpha(op)}&"
    out.append(f"Dialogue: 1,{start_ass},{end_ass},TS_Text,,0,0,0,,{{{an}\\pos({x},{y}){tx}}}{text}\n")
    return out


def events_from_srt(srt_path, res_x, res_y, center_x, base_y, st=None):
    """Все Dialogue-строки титров из SRT (замена цикла в srt_to_ass() у 2Stage)."""
    st = dict(st or style_from())
    st.setdefault("_style_fs", st["font_size"])
    if not os.path.exists(srt_path):
        return []
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    out = []
    orient = "v" if res_y > res_x else "h"      # раздельные маркеры H: … · V: …
    for b in parse_srt(content):
        if not b["lines"]:
            continue
        out += block_events(parse_markers(pick(b["mk"], orient)), b["lines"], ass_time(b["start_raw"]), ass_time(b["end_raw"]),
                            res_y, center_x, base_y, st)
    return out


def ass_header(res_x, res_y, st):
    """Шапка ASS с теми же стилями титров, что в 2Stage (для превью в приложении)."""
    fs = st.get("_style_fs", st["font_size"])
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TS_Text,{st['font_name']},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H1A000000,0,0,0,0,100,100,0,0,1,0,0,2,0,0,0,1
Style: TS_Shadow,{st['font_name']},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H1A000000,0,0,0,0,100,100,0,0,1,0,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
