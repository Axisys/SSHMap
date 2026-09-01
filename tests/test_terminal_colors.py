# -*- coding: utf-8 -*-
"""v1.0RC1 — цветовой движок + посячейный холст (ROADMAP v1.0RC1).

  * resolve_color (headless, без виджетов): brown/brightbrown → yellow/br_yellow
    (SGR 33/93), hex-passthrough 256-цветов и truecolor, опечатка pyte
    'bfightmagenta' (SGR 4;105), default-fallback, структура палитр (black…white + br_*);
  * E2E через pyte: SGR 33/93/38;5;196/38;2;… → Char.fg/bg → resolve_color
    (путь bash `ls --color` из Acceptance v1.0RC1);
  * кэш форматов (fg,bg,атрибуты) → (QPen,QBrush,QFont): hit по одному ключу,
    лимит → clear (TERMINAL.md §5.1);
  * рендер runs (offscreen): split_row_runs (чистая функция: runs/широкие глифы/
    заглушки), пиксельные цвета ячеек (SGR 31/33/93, 41, 256, truecolor),
    блок-курсор через свап + cursor.hidden (ESC[?25l/h), счётчик drawText
    (runs, а не по-символьный рендер);
  * интеграция: SSHTerminalWindow → TerminalWidget, TerminalScreen.render() — deprecated.

Запуск:  python tests/test_terminal_colors.py   (из корня проекта) или python tests/run_all.py
"""
import re
import sys

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from pyte.screens import Char

from modules.terminal_screen import (
    TerminalScreen, PALETTES, resolve_color, DEFAULT_FG_HEX, DEFAULT_BG_HEX,
)
from modules.terminal_widget import TerminalWidget, split_row_runs, is_wide_char


def make_char(data=" ", fg="default", bg="default", bold=False):
    """pyte Char с явными полями (факт №1: поле — italics, не italic)."""
    return Char(data=data, fg=fg, bg=bg, bold=bold, italics=False,
                underscore=False, strikethrough=False, reverse=False, blink=False)


# ════════════════════════════════════════════════════════════
# 1. Цветовой движок (headless) — TERMINAL.md §5.1
# ════════════════════════════════════════════════════════════
print("== resolve_color (headless) ==")
D = PALETTES["default"]

check("None → default fg", resolve_color(None) == DEFAULT_FG_HEX, repr(resolve_color(None)))
check("'default' → default fg", resolve_color("default") == DEFAULT_FG_HEX)
check("brown → yellow (SGR 33)", resolve_color("brown") == D["yellow"], repr(resolve_color("brown")))
check("brightbrown → br_yellow (SGR 93)", resolve_color("brightbrown") == D["br_yellow"])
check("red → палитра", resolve_color("red") == D["red"])
check("brightred → br_red", resolve_color("brightred") == D["br_red"])
check("256-цвет: hex-passthrough 'ff0000'", resolve_color("ff0000") == "#ff0000")
check("truecolor: hex-passthrough '0a141e'", resolve_color("0a141e") == "#0a141e")
check("bfightmagenta → br_magenta (опечатка pyte, SGR 4;105)",
      resolve_color("bfightmagenta") == D["br_magenta"], repr(resolve_color("bfightmagenta")))
check("brightmagenta → br_magenta", resolve_color("brightmagenta") == D["br_magenta"])
check("неизвестное имя → default", resolve_color("chartreuse") == DEFAULT_FG_HEX)
check("чужая палитра уважается", resolve_color("red", PALETTES["dracula"]) == PALETTES["dracula"]["red"])
check("default_hex-параметр", resolve_color(None, D, "#123456") == "#123456")

# структура палитр: black…white + br_* (8+8) — иначе SGR 33/93 уходят в default
for _name, _pal in PALETTES.items():
    _need = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
             "br_black", "br_red", "br_green", "br_yellow", "br_blue",
             "br_magenta", "br_cyan", "br_white")
    _missing = [k for k in _need if k not in _pal]
    _bad = [v for v in _pal.values() if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v))]
    check(f"палитра {_name}: ключи black…white + br_*", not _missing, f"missing={_missing}")
    check(f"палитра {_name}: значения '#rrggbb'", not _bad, f"bad={_bad}")

# ════════════════════════════════════════════════════════════
# 2. E2E через pyte: SGR → Char → resolve_color (путь `ls --color`)
# ════════════════════════════════════════════════════════════
print("== SGR → pyte Char → resolve_color ==")
scr = TerminalScreen(columns=40, lines=5)
scr.feed(b"\x1b[33mY\x1b[93mB\x1b[38;5;196mR\x1b[38;2;10;20;30mT\x1b[0mD")
rows, _cx, _cy, _hidden = scr.snapshot()
r0 = rows[0]

check("SGR 33 → fg='brown' (факт pyte)", r0[0].fg == "brown", repr(r0[0].fg))
check("SGR 93 → fg='brightbrown'", r0[1].fg == "brightbrown", repr(r0[1].fg))
check("38;5;196 → fg='ff0000' (hex, а не '196')", r0[2].fg == "ff0000", repr(r0[2].fg))
check("38;2;10;20;30 → fg='0a141e'", r0[3].fg == "0a141e", repr(r0[3].fg))
check("brown резолвится в жёлтый палитры", resolve_color(r0[0].fg, D) == D["yellow"])
check("brightbrown резолвится в br_yellow", resolve_color(r0[1].fg, D) == D["br_yellow"])
check("256-цвет резолвится в #ff0000", resolve_color(r0[2].fg, D) == "#ff0000")
check("truecolor резолвится в #0a141e", resolve_color(r0[3].fg, D) == "#0a141e")

# bg: SGR 4;105 → 'bfightmagenta' (опечатка самого pyte)
scr2 = TerminalScreen(columns=10, lines=3)
scr2.feed(b"\x1b[4;105mX\x1b[0m")
rows2, *_ = scr2.snapshot()
check("SGR 4;105 → bg='bfightmagenta' (факт pyte)", rows2[0][0].bg == "bfightmagenta",
      repr(rows2[0][0].bg))
check("bfightmagenta резолвится в br_magenta", resolve_color(rows2[0][0].bg, D) == D["br_magenta"])

# cursor.hidden: ESC[?25l/h (vim прячет курсор — факт №8)
scr3 = TerminalScreen(columns=10, lines=3)
scr3.feed(b"\x1b[?25labcd")
_, _, _, h_on = scr3.snapshot()
check("cursor.hidden=True после ESC[?25l", h_on is True)
scr3.feed(b"\x1b[?25h")
_, _, _, h_off = scr3.snapshot()
check("cursor.hidden=False после ESC[?25h", h_off is False)

# snapshot: заглушка широкого глифа (data=='') и clamp курсора на wrap
scr4 = TerminalScreen(columns=6, lines=2)
scr4.feed("a中b".encode("utf-8"))
rows4, *_ = scr4.snapshot()
check("широкий глиф: ячейка '中' + заглушка data==''",
      rows4[0][1].data == "中" and rows4[0][2].data == "",
      f"cells={[c.data for c in rows4[0][:4]]}")
scr5 = TerminalScreen(columns=3, lines=2)
scr5.feed(b"123")
_cx5, _cy5, _h5 = scr5.snapshot()[1:]
check("курсор зажат на wrap (x==columns → columns-1)", (_cx5, _cy5) == (2, 0), f"({_cx5},{_cy5})")

# ════════════════════════════════════════════════════════════
# 3. split_row_runs — runs и широкие глифы (чистая функция, без GUI)
# ════════════════════════════════════════════════════════════
print("== split_row_runs ==")
row = [make_char("a"), make_char("中"), make_char(""), make_char("b")]
runs = split_row_runs(row)
check("a/中/заглушка/b → 3 runs", len(runs) == 3, repr(runs))
check("широкий глиф — отдельный run с is_wide=True", runs[1] == (1, "中", True), repr(runs[1]))
check("заглушка не входит ни в один run", all(t != "" for _, t, _ in runs))

row2 = [make_char("M")] * 10
runs2 = split_row_runs(row2)
check("однородная строка — ОДИН run на 10 символов", runs2 == [(0, "M" * 10, False)], repr(runs2))

row3 = [make_char("R", fg="red"), make_char("G", fg="green")]
runs3 = split_row_runs(row3)
check("разные цвета — разные runs", runs3 == [(0, "R", False), (1, "G", False)], repr(runs3))

row4 = [make_char("中"), make_char(""), make_char("a"), make_char("b")]
runs4 = split_row_runs(row4)
check("после широкого: 'ab' начинается с ячейки 2",
      runs4 == [(0, "中", True), (2, "ab", False)], repr(runs4))

row5 = [make_char("X"), make_char("中"), make_char(""), make_char("Y")]
runs5 = split_row_runs(row5)
check("X + широкий + Y: 3 runs, 'Y' на ячейке 3",
      runs5 == [(0, "X", False), (1, "中", True), (3, "Y", False)], repr(runs5))

row6 = [make_char("a"), make_char("中")]
check("широкий в конце строки — без IndexError",
      split_row_runs(row6) == [(0, "a", False), (1, "中", True)])

row7 = [make_char("中"), make_char("", fg="red"), make_char("c")]
check("заглушка с другим форматом тоже пропускается",
      split_row_runs(row7) == [(0, "中", True), (2, "c", False)], repr(split_row_runs(row7)))

check("is_wide_char('中')", is_wide_char("中") is True)
check("is_wide_char('M')", is_wide_char("M") is False)
check("is_wide_char('')", is_wide_char("") is False)

# ════════════════════════════════════════════════════════════
# 4. Кэш форматов (TERMINAL.md §5.1): hit, различие, лимит → clear
# ════════════════════════════════════════════════════════════
print("== format cache ==")
w = TerminalWidget(TerminalScreen(columns=20, lines=5))
f1 = w._format_for("#ff0000", "#0f172a", False, False, False, False)
f2 = w._format_for("#ff0000", "#0f172a", False, False, False, False)
check("один ключ → один и тот же объект (cache hit)", f1 is f2)
f3 = w._format_for("#00ff00", "#0f172a", False, False, False, False)
check("другой fg → другой формат", f3 is not f1)
f4 = w._format_for("#ff0000", "#0f172a", True, False, False, False)
check("bold → другой QFont", f4 is not f1 and f4[2].bold())

w_small = TerminalWidget(TerminalScreen(columns=20, lines=5), format_cache_limit=8)
first_key = ("#000001", "#000000", False, False, False, False)
for i in range(9):
    w_small._format_for(f"#{i:06x}", "#000000", False, False, False, False)
check("лимит 8 → clear при переполнении (первая запись вытеснена)",
      len(w_small._format_cache) <= 8 and first_key not in w_small._format_cache,
      f"size={len(w_small._format_cache)}")

# ════════════════════════════════════════════════════════════
# 5. Рендер runs (offscreen): пиксели ячеек, курсор, широкие глифы
# ════════════════════════════════════════════════════════════
print("== paint (offscreen) ==")


def render_widget(screen):
    """Виджет → QPixmap → QImage + размеры ячейки."""
    w = TerminalWidget(screen)
    cw, chh = w.cell_size
    w.resize(cw * 20, chh * 5)
    img = w.grab().toImage()
    return w, img, cw, chh


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def close_enough(rgb, ref, tol=32):
    return all(abs(a - b) <= tol for a, b in zip(rgb, ref))


def ink_count(img, cw, chh, x, y, ref_hex, tol=48):
    """Число пикселей ячейки, близких к ref (чернила глифа)."""
    ref = hex_rgb(ref_hex)
    n = 0
    for yy in range(y * chh, (y + 1) * chh):
        for xx in range(x * cw, (x + 1) * cw):
            if close_enough(pixel(img, xx, yy), ref, tol):
                n += 1
    return n


# bg: SGR 41 — fillRect покрывает ячейку целиком (детерминированно)
scr_bg = TerminalScreen(columns=20, lines=5)
scr_bg.feed(b"\x1b[41mR\x1b[0m")
_wbg, img_bg, cw, chh = render_widget(scr_bg)
got_bg = pixel(img_bg, cw // 2, chh // 2)
check("SGR 41: ячейка залита красным палитры", close_enough(got_bg, hex_rgb(D["red"])),
      f"got={got_bg} want={D['red']}")

# fg: SGR 31/33/93 + 256 + truecolor — Acceptance «ls --color»
scr = TerminalScreen(columns=20, lines=5)
scr.feed(b"\x1b[31mR\x1b[33mY\x1b[93mB\x1b[38;5;196mP\x1b[38;2;1;2;3mT\x1b[0m")
_w, img, cw, chh = render_widget(scr)
check("SGR 31: 'R' — красные чернила", ink_count(img, cw, chh, 0, 0, D["red"]) >= 5,
      f"ink={ink_count(img, cw, chh, 0, 0, D['red'])}")
check("SGR 33: 'Y' — жёлтые чернила (brown→yellow)", ink_count(img, cw, chh, 1, 0, D["yellow"]) >= 5,
      f"ink={ink_count(img, cw, chh, 1, 0, D['yellow'])}")
check("SGR 93: 'B' — bright-жёлтые чернила", ink_count(img, cw, chh, 2, 0, D["br_yellow"]) >= 5,
      f"ink={ink_count(img, cw, chh, 2, 0, D['br_yellow'])}")
check("38;5;196: 'P' — чернила #ff0000", ink_count(img, cw, chh, 3, 0, "#ff0000") >= 5)
check("38;2;1;2;3: 'T' — чернила #010203 (truecolor)", ink_count(img, cw, chh, 4, 0, "#010203", tol=24) >= 5)

# default-текст
scr_def = TerminalScreen(columns=20, lines=5)
scr_def.feed(b"hello")
_wd, img_d, cw, chh = render_widget(scr_def)
check("default-текст — чернила default_fg", ink_count(img_d, cw, chh, 0, 0, D["default_fg"]) >= 5)

# блок-курсор через свап: после "abc" курсор на (3,0) — пустая ячейка залита
scr_c = TerminalScreen(columns=20, lines=5)
scr_c.feed(b"abc")
_wc, img_c, cw, chh = render_widget(scr_c)
cur_rgb = hex_rgb(TerminalWidget.CURSOR_COLOR)
got_cur = pixel(img_c, 3 * cw + cw // 2, chh // 2)
check("блок-курсор: ячейка залита цветом курсора", close_enough(got_cur, cur_rgb, tol=16),
      f"got={got_cur} want={TerminalWidget.CURSOR_COLOR}")

# курсор над глифом: угол ячейки — цвет курсора, глиф перерисован цветом фона
scr_c3 = TerminalScreen(columns=20, lines=5)
scr_c3.feed(b"a\x1b[1;1H")   # курсор на 'a'
_wc3, img_c3, cw, chh = render_widget(scr_c3)
corner = pixel(img_c3, 1, 1)
check("курсор над глифом: угол ячейки — цвет курсора", close_enough(corner, cur_rgb, tol=8),
      f"got={corner}")
bg_ink = ink_count(img_c3, cw, chh, 0, 0, D["default_bg"])
check("курсор над глифом: глиф перерисован цветом фона", bg_ink >= 5, f"ink={bg_ink}")

# cursor.hidden (ESC[?25l) — блок НЕ рисуется
scr_h = TerminalScreen(columns=20, lines=5)
scr_h.feed(b"\x1b[?25labcd")   # скрыт, курсор на (4,0)
_wh, img_h, cw, chh = render_widget(scr_h)
got_h = pixel(img_h, 4 * cw + cw // 2, chh // 2)
check("cursor.hidden: блока в ячейке курсора нет", not close_enough(got_h, cur_rgb, tol=16),
      f"got={got_h}")

# широкие глифы: X(0) 中(1) заглушка(2) Y(3) Z(4) — 'Y' на ячейке 3, 'Z' на 4
scr_w = TerminalScreen(columns=20, lines=5)
scr_w.feed("X中YZ".encode("utf-8"))
_ww, img_w, cw, chh = render_widget(scr_w)
check("после широкого глифа: 'Y' на ячейке 3 (чернила default_fg)",
      ink_count(img_w, cw, chh, 3, 0, D["default_fg"]) >= 5,
      f"ink={ink_count(img_w, cw, chh, 3, 0, D['default_fg'])}")
check("'Z' на ячейке 4", ink_count(img_w, cw, chh, 4, 0, D["default_fg"]) >= 5)

# runs, а не по-символьные drawText: счётчик вызовов paintEvent'а
scr_r = TerminalScreen(columns=10, lines=3)
scr_r.feed(b"MMMMMMMMMM\r\n")   # строка из 10 одинаковых → 1 run → 1 drawText
_wr, _img_r, _cw, _chh = render_widget(scr_r)
check("однородная строка — один drawText (runs)",
      _wr.last_paint_stats["draw_text_calls"] == 1, f"stats={_wr.last_paint_stats}")

scr_r2 = TerminalScreen(columns=10, lines=3)
scr_r2.feed(b"\x1b[31mRR\x1b[32mGG\x1b[0m")   # два цвета → два drawText
_wr2, _img_r2, _cw, _chh = render_widget(scr_r2)
check("два цвета — два drawText", _wr2.last_paint_stats["draw_text_calls"] == 2,
      f"stats={_wr2.last_paint_stats}")

# ════════════════════════════════════════════════════════════
# 6. Интеграция: SSHTerminalWindow → TerminalWidget (задача 3 RC1)
# ════════════════════════════════════════════════════════════
print("== SSHTerminalWindow integration ==")
import inspect

import modules.ssh_terminal as ST
from models.server import ServerData


class _FakeTerm(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        pass  # без сети


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeTerm
win = None
try:
    win = ST.SSHTerminalWindow(ServerData(id="rc1w", alias="T", host="127.0.0.1", user="u"), None)
    check("окно создаёт TerminalWidget", isinstance(win.widget, TerminalWidget))
    check("у окна нет self.edit (HTML-путь заменён)", not hasattr(win, "edit"))

    win._on_output(b"hello")
    wait_until(lambda: "hello" in win.widget.visible_text(), timeout_ms=1500)
    check("байты → pyte → холст (visible_text)", "hello" in win.widget.visible_text(),
          f"text={win.widget.visible_text()!r}"[:200])

    doc = inspect.getdoc(ST.TerminalScreen.render) or ""
    check("TerminalScreen.render() помечен DEPRECATED", "DEPRECATED" in doc, doc[:80])
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass

finish()
