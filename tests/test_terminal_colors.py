# -*- coding: utf-8 -*-
"""v1.0RC1 — the color engine + per-cell canvas (ROADMAP v1.0RC1).

  * resolve_color (headless, no widgets): brown/brightbrown → yellow/br_yellow
    (SGR 33/93), the hex passthrough of 256-color and truecolor, the pyte typo
    'bfightmagenta' (SGR 4;105), the default fallback, the structure of the palettes (black…white + br_*);
  * E2E through pyte: SGR 33/93/38;5;196/38;2;… → Char.fg/bg → resolve_color
    (the bash `ls --color` path of the Acceptance v1.0RC1);
  * the format cache (fg,bg,attributes) → (QPen,QBrush,QFont): a hit by a single key,
    the limit → clear (TERMINAL.md §5.1);
  * the run rendering (offscreen): split_row_runs (a pure function: the runs/the wide glyphs/
    the stubs), the pixel colors of the cells (SGR 31/33/93, 41, 256, truecolor),
    the block cursor via the swap + cursor.hidden (ESC[?25l/h), the drawText counter
    (the runs, not the per-character render);
  * the integration: SSHTerminalWindow → TerminalWidget; v1.2.9: TerminalScreen.render()
    (the HTML path) removed — the absence check of the dead code.

Run:  python tests/test_terminal_colors.py   (from the project root) or python tests/run_all.py
"""
import re
import sys

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from third_party.pyte.screens import Char   # v1.3rc1: the fork (MANIFEST.md)

from modules.terminal_screen import (
    TerminalScreen, PALETTES, resolve_color, DEFAULT_FG_HEX, DEFAULT_BG_HEX,
)
from modules.terminal_widget import TerminalWidget, split_row_runs, is_wide_char


def make_char(data=" ", fg="default", bg="default", bold=False):
    """A pyte Char with explicit fields (fact #1: the field is italics, not italic)."""
    return Char(data=data, fg=fg, bg=bg, bold=bold, italics=False,
                underscore=False, strikethrough=False, reverse=False, blink=False)


# ════════════════════════════════════════════════════════════
# 1. The color engine (headless) — TERMINAL.md §5.1
# ════════════════════════════════════════════════════════════
print("== resolve_color (headless) ==")
D = PALETTES["default"]

check("None → default fg", resolve_color(None) == DEFAULT_FG_HEX, repr(resolve_color(None)))
check("'default' → default fg", resolve_color("default") == DEFAULT_FG_HEX)
check("brown → yellow (SGR 33)", resolve_color("brown") == D["yellow"], repr(resolve_color("brown")))
check("brightbrown → br_yellow (SGR 93)", resolve_color("brightbrown") == D["br_yellow"])
check("red → the palette", resolve_color("red") == D["red"])
check("brightred → br_red", resolve_color("brightred") == D["br_red"])
check("the 256-color: the hex-passthrough 'ff0000'", resolve_color("ff0000") == "#ff0000")
check("truecolor: hex-passthrough '0a141e'", resolve_color("0a141e") == "#0a141e")
check("bfightmagenta → br_magenta (the pyte typo, SGR 4;105)",
      resolve_color("bfightmagenta") == D["br_magenta"], repr(resolve_color("bfightmagenta")))
check("brightmagenta → br_magenta", resolve_color("brightmagenta") == D["br_magenta"])
check("an unknown name → the default", resolve_color("chartreuse") == DEFAULT_FG_HEX)
check("a foreign palette is honoured", resolve_color("red", PALETTES["dracula"]) == PALETTES["dracula"]["red"])
check("the default_hex parameter", resolve_color(None, D, "#123456") == "#123456")

# the palette structure: black…white + br_* (8+8) — otherwise SGR 33/93 fall back to default
for _name, _pal in PALETTES.items():
    _need = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
             "br_black", "br_red", "br_green", "br_yellow", "br_blue",
             "br_magenta", "br_cyan", "br_white")
    _missing = [k for k in _need if k not in _pal]
    _bad = [v for v in _pal.values() if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v))]
    check(f"palette {_name}: the keys black…white + br_*", not _missing, f"missing={_missing}")
    check(f"palette {_name}: the values '#rrggbb'", not _bad, f"bad={_bad}")

# ════════════════════════════════════════════════════════════
# 2. E2E via pyte: SGR → Char → resolve_color (the `ls --color` path)
# ════════════════════════════════════════════════════════════
print("== SGR → pyte Char → resolve_color ==")
scr = TerminalScreen(columns=40, lines=5)
scr.feed(b"\x1b[33mY\x1b[93mB\x1b[38;5;196mR\x1b[38;2;10;20;30mT\x1b[0mD")
rows, _cx, _cy, _hidden = scr.snapshot()
r0 = rows[0]

check("SGR 33 → fg='brown' (the pyte fact)", r0[0].fg == "brown", repr(r0[0].fg))
check("SGR 93 → fg='brightbrown'", r0[1].fg == "brightbrown", repr(r0[1].fg))
check("38;5;196 → fg='ff0000' (the hex, not '196')", r0[2].fg == "ff0000", repr(r0[2].fg))
check("38;2;10;20;30 → fg='0a141e'", r0[3].fg == "0a141e", repr(r0[3].fg))
check("brown resolves to the yellow of the palette", resolve_color(r0[0].fg, D) == D["yellow"])
check("brightbrown resolves to the br_yellow", resolve_color(r0[1].fg, D) == D["br_yellow"])
check("the 256-color resolves to the #ff0000", resolve_color(r0[2].fg, D) == "#ff0000")
check("the truecolor resolves to the #0a141e", resolve_color(r0[3].fg, D) == "#0a141e")

# bg: SGR 4;105 → 'bfightmagenta' (a typo in pyte itself)
scr2 = TerminalScreen(columns=10, lines=3)
scr2.feed(b"\x1b[4;105mX\x1b[0m")
rows2, *_ = scr2.snapshot()
check("SGR 4;105 → bg='bfightmagenta' (the pyte fact)", rows2[0][0].bg == "bfightmagenta",
      repr(rows2[0][0].bg))
check("bfightmagenta resolves to the br_magenta", resolve_color(rows2[0][0].bg, D) == D["br_magenta"])

# cursor.hidden: ESC[?25l/h (vim hides the cursor — fact №8)
scr3 = TerminalScreen(columns=10, lines=3)
scr3.feed(b"\x1b[?25labcd")
_, _, _, h_on = scr3.snapshot()
check("cursor.hidden=True after ESC[?25l", h_on is True)
scr3.feed(b"\x1b[?25h")
_, _, _, h_off = scr3.snapshot()
check("cursor.hidden=False after ESC[?25h", h_off is False)

# snapshot: the stub of a wide glyph (data=='') and the cursor clamp on wrap
scr4 = TerminalScreen(columns=6, lines=2)
scr4.feed("a中b".encode("utf-8"))
rows4, *_ = scr4.snapshot()
check("the wide glyph: the cell '中' + the stub data==''",
      rows4[0][1].data == "中" and rows4[0][2].data == "",
      f"cells={[c.data for c in rows4[0][:4]]}")
scr5 = TerminalScreen(columns=3, lines=2)
scr5.feed(b"123")
_cx5, _cy5, _h5 = scr5.snapshot()[1:]
check("the cursor is clamped on the wrap (x==columns → columns-1)", (_cx5, _cy5) == (2, 0), f"({_cx5},{_cy5})")

# ════════════════════════════════════════════════════════════
# 3. split_row_runs — runs and wide glyphs (a pure function, no GUI)
# ════════════════════════════════════════════════════════════
print("== split_row_runs ==")
row = [make_char("a"), make_char("中"), make_char(""), make_char("b")]
runs = split_row_runs(row)
check("a/中/the stub/b → the 3 runs", len(runs) == 3, repr(runs))
check("the wide glyph — a separate run with is_wide=True", runs[1] == (1, "中", True), repr(runs[1]))
check("the stub is in no run", all(t != "" for _, t, _ in runs))

row2 = [make_char("M")] * 10
runs2 = split_row_runs(row2)
check("a homogeneous line — ONE run of 10 characters", runs2 == [(0, "M" * 10, False)], repr(runs2))

row3 = [make_char("R", fg="red"), make_char("G", fg="green")]
runs3 = split_row_runs(row3)
check("different colors — different runs", runs3 == [(0, "R", False), (1, "G", False)], repr(runs3))

row4 = [make_char("中"), make_char(""), make_char("a"), make_char("b")]
runs4 = split_row_runs(row4)
check("after the wide one: 'ab' starts from the cell 2",
      runs4 == [(0, "中", True), (2, "ab", False)], repr(runs4))

row5 = [make_char("X"), make_char("中"), make_char(""), make_char("Y")]
runs5 = split_row_runs(row5)
check("X + the wide one + Y: the 3 runs, 'Y' on the cell 3",
      runs5 == [(0, "X", False), (1, "中", True), (3, "Y", False)], repr(runs5))

row6 = [make_char("a"), make_char("中")]
check("the wide one at the end of the line — no IndexError",
      split_row_runs(row6) == [(0, "a", False), (1, "中", True)])

row7 = [make_char("中"), make_char("", fg="red"), make_char("c")]
check("the stub with a different format is skipped as well",
      split_row_runs(row7) == [(0, "中", True), (2, "c", False)], repr(split_row_runs(row7)))

check("is_wide_char('中')", is_wide_char("中") is True)
check("is_wide_char('M')", is_wide_char("M") is False)
check("is_wide_char('')", is_wide_char("") is False)

# ════════════════════════════════════════════════════════════
# 4. The format cache (TERMINAL.md §5.1): a hit, a difference, the limit → clear
# ════════════════════════════════════════════════════════════
print("== format cache ==")
w = TerminalWidget(TerminalScreen(columns=20, lines=5))
f1 = w._format_for("#ff0000", "#0f172a", False, False, False, False)
f2 = w._format_for("#ff0000", "#0f172a", False, False, False, False)
check("one key → the same object (the cache hit)", f1 is f2)
f3 = w._format_for("#00ff00", "#0f172a", False, False, False, False)
check("a different fg → a different format", f3 is not f1)
f4 = w._format_for("#ff0000", "#0f172a", True, False, False, False)
check("bold → a different QFont", f4 is not f1 and f4[2].bold())

w_small = TerminalWidget(TerminalScreen(columns=20, lines=5), format_cache_limit=8)
first_key = ("#000001", "#000000", False, False, False, False)
for i in range(9):
    w_small._format_for(f"#{i:06x}", "#000000", False, False, False, False)
check("the limit 8 → the clear on the overflow (the first entry is evicted)",
      len(w_small._format_cache) <= 8 and first_key not in w_small._format_cache,
      f"size={len(w_small._format_cache)}")

# ════════════════════════════════════════════════════════════
# 5. Rendering runs (offscreen): cell pixels, the cursor, wide glyphs
# ════════════════════════════════════════════════════════════
print("== paint (offscreen) ==")


def render_widget(screen, cursor_style=None):
    """A widget → QPixmap → QImage + the sizes of the cell.

    `cursor_style` (v1.6.2): the cursor SHAPE of the canvas. The application's default is the
    thin bar now, so the checks that assert the historical BLOCK painting ask for `"block"`
    explicitly — the shape is an INPUT of the canvas, not an accident of the default.
    """
    w = (TerminalWidget(screen) if cursor_style is None
         else TerminalWidget(screen, cursor_style=cursor_style))
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
    """The count of the pixels of the cell, close to the ref (the ink of the glyph)."""
    ref = hex_rgb(ref_hex)
    n = 0
    for yy in range(y * chh, (y + 1) * chh):
        for xx in range(x * cw, (x + 1) * cw):
            if close_enough(pixel(img, xx, yy), ref, tol):
                n += 1
    return n


# bg: SGR 41 — fillRect covers the cell entirely (deterministically)
scr_bg = TerminalScreen(columns=20, lines=5)
scr_bg.feed(b"\x1b[41mR\x1b[0m")
_wbg, img_bg, cw, chh = render_widget(scr_bg)
got_bg = pixel(img_bg, cw // 2, chh // 2)
check("SGR 41: the cell is painted with the red of the palette", close_enough(got_bg, hex_rgb(D["red"])),
      f"got={got_bg} want={D['red']}")

# v1.2.10rc3 (a cosmetic audit bug): a TUI app paints the empty line explicitly
# with spaces under its own color (the mc/mcedit viewer area — uniformly gray in xterm).
# a whitespace-only run without ink, but a fillRect at bg != default_bg (the real chain
# TerminalScreen→TerminalWidget; before the fix: bg='white' in the grid, #0f172a on the canvas).
scr_ws = TerminalScreen(columns=20, lines=5)
scr_ws.feed(b"\x1b[47m" + b" " * 20 + b"\x1b[0m\r\n")
rows_ws, *_ = scr_ws.snapshot()
check("the grid: the spaces under the SGR 47 carry the bg='white' (the pyte fact)",
      rows_ws[0][5].bg == "white", repr(rows_ws[0][5].bg))
_wws, img_ws, cw, chh = render_widget(scr_ws)
got_ws1 = pixel(img_ws, 5 * cw + cw // 2, chh // 2)      # the cursor after \r\n at (0,1) — line 0 is intact
got_ws2 = pixel(img_ws, 12 * cw + cw // 2, chh // 2)     # the homogeneity across the whole line
check("the SGR 47 spaces: the cell is painted with the white of the palette (not the default_bg)",
      close_enough(got_ws1, hex_rgb(D["white"]), tol=8), f"got={got_ws1} want={D['white']}")
check("the SGR 47 spaces: the line is homogeneous (the cell 12 = the cell 5)",
      close_enough(got_ws2, hex_rgb(D["white"]), tol=8), f"got={got_ws2}")

# Regression: an UNPAINTED empty line (without SGR) — the render matches xterm:
# the basic fill, no extra fillRect.
scr_sp = TerminalScreen(columns=20, lines=5)
_wsp, img_sp, cw, chh = render_widget(scr_sp)   # the cursor at (0,0) — we look at line 3
got_sp = pixel(img_sp, 7 * cw + cw // 2, 3 * chh + chh // 2)
check("an unpainted empty line: the base fill, the default_bg",
      close_enough(got_sp, hex_rgb(D["default_bg"]), tol=4), f"got={got_sp} want={D['default_bg']}")

# fg: SGR 31/33/93 + 256 + truecolor — Acceptance «ls --color»
scr = TerminalScreen(columns=20, lines=5)
scr.feed(b"\x1b[31mR\x1b[33mY\x1b[93mB\x1b[38;5;196mP\x1b[38;2;1;2;3mT\x1b[0m")
_w, img, cw, chh = render_widget(scr)
check("SGR 31: 'R' — the red ink", ink_count(img, cw, chh, 0, 0, D["red"]) >= 5,
      f"ink={ink_count(img, cw, chh, 0, 0, D['red'])}")
check("SGR 33: 'Y' — the yellow ink (brown→yellow)", ink_count(img, cw, chh, 1, 0, D["yellow"]) >= 5,
      f"ink={ink_count(img, cw, chh, 1, 0, D['yellow'])}")
check("SGR 93: 'B' — the bright-yellow ink", ink_count(img, cw, chh, 2, 0, D["br_yellow"]) >= 5,
      f"ink={ink_count(img, cw, chh, 2, 0, D['br_yellow'])}")
check("38;5;196: 'P' — the ink #ff0000", ink_count(img, cw, chh, 3, 0, "#ff0000") >= 5)
check("38;2;1;2;3: 'T' — the ink #010203 (the truecolor)", ink_count(img, cw, chh, 4, 0, "#010203", tol=24) >= 5)

# the default text
scr_def = TerminalScreen(columns=20, lines=5)
scr_def.feed(b"hello")
_wd, img_d, cw, chh = render_widget(scr_def)
check("the default text — the ink of the default_fg", ink_count(img_d, cw, chh, 0, 0, D["default_fg"]) >= 5)

# the block cursor via the swap: after "abc" the cursor is at (3,0) — the empty cell is filled
# (v1.6.2: the BLOCK is requested explicitly — the application's default shape is the thin bar)
scr_c = TerminalScreen(columns=20, lines=5)
scr_c.feed(b"abc")
_wc, img_c, cw, chh = render_widget(scr_c, cursor_style="block")
cur_rgb = hex_rgb(TerminalWidget.CURSOR_COLOR)
got_cur = pixel(img_c, 3 * cw + cw // 2, chh // 2)
check("the block cursor: the cell is painted with the cursor color", close_enough(got_cur, cur_rgb, tol=16),
      f"got={got_cur} want={TerminalWidget.CURSOR_COLOR}")

# the cursor over a glyph: the cell corner — the cursor color, the glyph is repainted with the background color
scr_c3 = TerminalScreen(columns=20, lines=5)
scr_c3.feed(b"a\x1b[1;1H")   # the cursor over 'a'
_wc3, img_c3, cw, chh = render_widget(scr_c3, cursor_style="block")
corner = pixel(img_c3, 1, 1)
check("the cursor over the glyph: the corner of the cell — the cursor color", close_enough(corner, cur_rgb, tol=8),
      f"got={corner}")
bg_ink = ink_count(img_c3, cw, chh, 0, 0, D["default_bg"])
check("the cursor over the glyph: the glyph is repainted with the background color", bg_ink >= 5, f"ink={bg_ink}")

# cursor.hidden (ESC[?25l) — the block is NOT drawn
scr_h = TerminalScreen(columns=20, lines=5)
scr_h.feed(b"\x1b[?25labcd")   # hidden, the cursor at (4,0)
_wh, img_h, cw, chh = render_widget(scr_h, cursor_style="block")
got_h = pixel(img_h, 4 * cw + cw // 2, chh // 2)
check("cursor.hidden: the block is NOT in the cell of the cursor", not close_enough(got_h, cur_rgb, tol=16),
      f"got={got_h}")

# the wide glyphs: X(0) 中(1) the stub(2) Y(3) Z(4) — 'Y' on cell 3, 'Z' on 4
scr_w = TerminalScreen(columns=20, lines=5)
scr_w.feed("X中YZ".encode("utf-8"))
_ww, img_w, cw, chh = render_widget(scr_w)
check("after the wide glyph: 'Y' on the cell 3 (the ink of the default_fg)",
      ink_count(img_w, cw, chh, 3, 0, D["default_fg"]) >= 5,
      f"ink={ink_count(img_w, cw, chh, 3, 0, D['default_fg'])}")
check("'Z' on the cell 4", ink_count(img_w, cw, chh, 4, 0, D["default_fg"]) >= 5)

# the runs and the cell painting: v1.6.3 — the RUN is still the fill/format unit, while the
# text is drawn GLYPH BY GLYPH at its own cell (the wandering-column fix), so the counter now
# reads "one call per glyph of the run" (tests/test_canvas_truth.py owns the geometry).
scr_r = TerminalScreen(columns=10, lines=3)
scr_r.feed(b"MMMMMMMMMM\r\n")   # a line of 10 identical glyphs → 1 run → 10 drawText
_wr, _img_r, _cw, _chh = render_widget(scr_r)
check("a homogeneous line — ONE run, a drawText per glyph (v1.6.3)",
      _wr.last_paint_stats["draw_text_calls"] == 10, f"stats={_wr.last_paint_stats}")

scr_r2 = TerminalScreen(columns=10, lines=3)
scr_r2.feed(b"\x1b[31mRR\x1b[32mGG\x1b[0m")   # two colors → two runs → 4 drawText
_wr2, _img_r2, _cw, _chh = render_widget(scr_r2)
check("two colors — two runs, a drawText per glyph (v1.6.3)",
      _wr2.last_paint_stats["draw_text_calls"] == 4,
      f"stats={_wr2.last_paint_stats}")

# ════════════════════════════════════════════════════════════
# 6. Integration: SSHTerminalWindow → TerminalWidget (RC1 task 3)
# ════════════════════════════════════════════════════════════
print("== SSHTerminalWindow integration ==")
import modules.ssh_terminal as ST
from models.server import ServerData


class _FakeTerm(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        pass  # without network


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeTerm
win = None
try:
    win = ST.SSHTerminalWindow(ServerData(id="rc1w", alias="T", host="127.0.0.1", user="u"), None)
    check("the window creates the TerminalWidget", isinstance(win.widget, TerminalWidget))
    check("the window has no self.edit (the HTML path is replaced)", not hasattr(win, "edit"))

    win.page._on_output(b"hello")  # v1.2: the session on the page
    wait_until(lambda: "hello" in win.widget.visible_text(), timeout_ms=1500)
    check("the bytes → the pyte → the canvas (visible_text)", "hello" in win.widget.visible_text(),
          f"text={win.widget.visible_text()!r}"[:200])

    check("v1.2.9: TerminalScreen.render() (the HTML path) is removed — the dead code since v1.0RC1",
          not hasattr(ST.TerminalScreen, "render"))
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass

finish()
