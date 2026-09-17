# -*- coding: utf-8 -*-
"""v1.2.9 — full wcwidth(3) for CJK (ROADMAP "Terminal hygiene", task 2).

It replaces the `east_asian_width` W/F heuristic of v1.0RC1 (the known limitation of v1.0 is closed):
the width of a glyph — THE SAME library `wcwidth` as pyte 0.8.2 itself for the layout of the grid
(pyte.screens: `from wcwidth import wcwidth`), therefore the classification of the canvas always
matches how pyte places the glyphs into the cells (+ the stub after a wide one).

  * char_width() — the full table of wcwidth(3): the wide (CJK/Fullwidth/Hangul/kana/emoji) = 2;
    the narrow AND the ambiguous (wcwidth(3): the Ambiguous category = the narrow, the C locale) = 1;
    the zero-width (the combining marks, the variation selectors) = 0; the control (-1) is clamped to 0;
    the empty string (the stub) = 0; the multi-character cell (the NFC cluster of pyte) — the sum;
  * is_wide_char() — char_width == 2; the cross-check against the wcwidth library by the sample;
    the heuristic unicodedata.east_asian_width is not in the module anymore (the hygiene);
  * the E2E through the real TerminalScreen: the grid is laid out exactly by wcwidth
    ("a中b" = [a][中][''][b], the stub — the width 0; the total width = wcswidth),
    the NFC composite cluster "e"+U+0301 → ONE cell 'é' of the width 1 (the regression: the old
    heuristic counted the combining mark as narrow → the width would be 2);
  * split_row_runs/word_units on the CJK lines: the stub is not in any run,
    a wide glyph at the end of the line — without an IndexError; "a中b" = one word on 4 cells
    (the semantics of v1.2.7 under the full wcwidth).

Headless: the Qt widgets are not created (the TerminalScreen — headless-friendly, the pure functions
of terminal_widget.py — without the GUI). Run:  python tests/test_wcwidth_cjk.py   (from the project root)
or python tests/run_all.py
"""
import inspect

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from wcwidth import wcwidth as _wcwidth, wcswidth as _wcswidth

from modules.terminal_screen import TerminalScreen
import modules.terminal_widget as TW
from modules.terminal_widget import char_width, is_wide_char, split_row_runs, word_units


# ════════════════════════════════════════════════════════════
# 1. char_width — the full wcwidth(3) table (wide/narrow/ambiguous/zero)
# ════════════════════════════════════════════════════════════
print("== char_width: the wcwidth(3) table ==")

# WIDE = 2: CJK ideographs, Fullwidth (EAW F), Hangul, kana, CJK punctuation, emoji.
WIDE_CHARS = {
    "中": "a CJK ideograph",
    "\uff21": "Fullwidth 'A' (EAW F)",
    "한": "a Hangul syllable",
    "あ": "kana (hiragana)",
    "、": "ideographic comma (EAW W)",
    "\u3000": "fullwidth space (EAW F)",
    "\U0001F600": "emoji U+1F600",
}
for ch, name in WIDE_CHARS.items():
    check(f"wide: {name} → 2", char_width(ch) == 2, repr(char_width(ch)))

# NARROW = 1: ASCII and Latin.
NARROW_CHARS = {"a": "ASCII", "é": "precomposed é (U+00E9)", "\uff71": "halfwidth katakana 'a' (EAW H)"}
for ch, name in NARROW_CHARS.items():
    check(f"narrow: {name} → 1", char_width(ch) == 1, repr(char_width(ch)))

# AMBIGUOUS = 1: the Ambiguous category in wcwidth(3) — NARROW (C locale). The old heuristic
# east_asian_width W/F did not count them wide either — the behaviour is preserved, now by
# the full table, not by a subset.
AMBIGUOUS_CHARS = {
    "¿": "inverted '?'",
    "°": "degree sign",
    "\u2116": "numero sign №",
    "α": "greek alpha",
}
for ch, name in AMBIGUOUS_CHARS.items():
    check(f"ambiguous: {name} → 1 (narrow)", char_width(ch) == 1, repr(char_width(ch)))

# ZERO-WIDTH = 0: combining marks and variation selectors. A KEY shift against the old
# heuristics: their EAW = 'A'/'M', the W/F check gave "narrow" (1) — the cluster was inflated.
check("zero-width: combining acute U+0301 → 0", char_width("\u0301") == 0, repr(char_width("\u0301")))
check("zero-width: variation selector-1 U+FE0F → 0", char_width("\ufe0f") == 0, repr(char_width("\ufe0f")))

# Controls: wcwidth returns -1 — clamped to 0 (a cell carries no controls,
# but the function must be safe for any content).
check("control BEL U+0007 (-1) → clamped to 0", char_width("\x07") == 0, repr(char_width("\x07")))

# An empty line — a stub after a wide glyph (pyte: data == '') → 0.
check("an empty string (the stub) → 0", char_width("") == 0, repr(char_width("")))

# A multi-character cell: pyte NFC-merges the combining mark into the previous cell —
# the width = the sum over characters (exactly like pyte's per-character draw()). "e"+U+0301 → "é":
# 1 + 0 = 1. The old heuristic: 1 + 1 = 2 (wide! — the regression was closed in v1.2.9).
cluster = "e\u0301"
check("the NFC cluster 'e'+U+0301 → 1 (not 2 as with the old heuristic)", char_width(cluster) == 1,
      repr(char_width(cluster)))

# ════════════════════════════════════════════════════════════
# 2. is_wide_char — the same table as pyte's (the wcwidth library)
# ════════════════════════════════════════════════════════════
print("== is_wide_char: cross-check against the wcwidth library ==")

check("is_wide_char('中') — True", is_wide_char("中") is True)
check("is_wide_char('a') — False", is_wide_char("a") is False)
check("is_wide_char('¿') (ambiguous) — False", is_wide_char("¿") is False)
check("is_wide_char('') (the stub) — False", is_wide_char("") is False)

# Sampling: the canvas classification = the pyte layout classification (one table).
SAMPLE = list(WIDE_CHARS) + list(NARROW_CHARS) + list(AMBIGUOUS_CHARS) + ["\u0301", "\ufe0f"]
_mismatch = [c for c in SAMPLE if is_wide_char(c) != (_wcwidth(c) == 2)]
check("is_wide_char == (wcwidth(ch) == 2) over a sample of %d characters" % len(SAMPLE),
      not _mismatch, repr(_mismatch))

# Hygiene: the unicodedata.east_asian_width heuristic is no longer in the module (task 2) —
# nor an import, nor an attribute access (historical mentions in a docstring are allowed).
_src = inspect.getsource(TW)
check("the unicodedata.east_asian_width heuristic is removed from terminal_widget.py",
      "import unicodedata" not in _src and ".east_asian_width" not in _src,
      "remnants of the heuristic found")

# ════════════════════════════════════════════════════════════
# 3. E2E via a real TerminalScreen: the pyte grid = the wcwidth table
# ════════════════════════════════════════════════════════════
print("== E2E: the pyte layout == wcwidth ==")

scr = TerminalScreen(columns=20, lines=3)
scr.feed("a中b".encode("utf-8"))
rows, _cx, _cy, _hidden = scr.snapshot()
line0 = rows[0]

check("'a中b': 4 cells occupied — [a][中][''][b]",
      [c.data for c in line0[:4]] == ["a", "中", "", "b"],
      repr([c.data for c in line0[:6]]))
check("'a中b': the cell widths 1/2/0/1",
      [char_width(c.data) for c in line0[:4]] == [1, 2, 0, 1],
      repr([char_width(c.data) for c in line0[:4]]))
check("'a中b': the total width = wcswidth('a中b') = 4",
      sum(char_width(c.data) for c in line0[:4]) == _wcswidth("a中b") == 4,
      repr(sum(char_width(c.data) for c in line0[:4])))
check("'a中b': the wide glyph — is_wide_char over the cell data",
      is_wide_char(line0[1].data) and not is_wide_char(line0[2].data))

# The NFC cluster: pyte merges "e"+U+0301 into ONE cell 'é' — width 1, not 2.
scr2 = TerminalScreen(columns=20, lines=3)
scr2.feed("e\u0301b".encode("utf-8"))
rows2, _cx2, _cy2, _h2 = scr2.snapshot()
line2 = rows2[0]
check("'e'+U+0301+b: the NFC merge — the cell 0 = 'é' (2 characters)", line2[0].data == "é",
      repr(line2[0].data))
check("'e'+U+0301+b: the width of the merged cell = 1 (the old heuristic would give 2)",
      char_width(line2[0].data) == 1, repr(char_width(line2[0].data)))
check("'e'+U+0301+b: 'b' is in the next cell", line2[1].data == "b", repr(line2[1].data))

# Ambiguous symbols occupy exactly ONE cell each (they do not balloon to wide).
scr3 = TerminalScreen(columns=20, lines=3)
scr3.feed("¿°\u2116α".encode("utf-8"))
rows3, _cx3, _cy3, _h3 = scr3.snapshot()
line3 = rows3[0]
check("'¿°№α': 4 characters = exactly 4 cells (the ambiguous ones are not wide)",
      [c.data for c in line3[:4]] == ["¿", "°", "\u2116", "α"] and line3[4].data == " ",
      repr([c.data for c in line3[:5]]))

# ════════════════════════════════════════════════════════════
# 4. split_row_runs / word_units on CJK lines (pure functions)
# ════════════════════════════════════════════════════════════
print("== split_row_runs / word_units: CJK ==")

runs = split_row_runs(line0)
check("«a中b»: 3 runs — [a] | [中 wide] | [b…]", len(runs) == 3, repr(runs))
check("'a中b': the wide run — (1, '中', True)", runs[1] == (1, "中", True), repr(runs[1]))
check("'a中b': the stub (x=2) is in no run",
      all(r[0] != 2 for r in runs) and "".join(r[1] for r in runs).replace(" ", "") == "a中b",
      repr(runs))

# A wide glyph at the END of the line: x += 2 goes past len(row) — no IndexError.
scr4 = TerminalScreen(columns=6, lines=3)
scr4.feed("     中".encode("utf-8"))
rows4, _cx4, _cy4, _h4 = scr4.snapshot()
runs4 = split_row_runs(rows4[0])
check("a wide glyph at the end of the line (x=5, cols=6): no IndexError", len(runs4) >= 1, repr(runs4))
check("a wide glyph at the end of the line: the last run — (5, '中', True)",
      runs4[-1] == (5, "中", True), repr(runs4[-1]))

# word_units (v1.2.7): the stub of a wide glyph belongs to the WORD — "a中b" = one
# a word across 4 cells (0..3), not two words with a break at the stub.
units = word_units(line0)
check("'a中b': one word across 4 cells [(0, 3)]", units == [(0, 3)], repr(units))

# A space separator around CJK: "中 a" — two words (a stub in the first).
scr5 = TerminalScreen(columns=10, lines=3)
scr5.feed("中 a".encode("utf-8"))
rows5, _cx5, _cy5, _h5 = scr5.snapshot()
units5 = word_units(rows5[0])
check("'中 a': two words [(0, 1), (3, 3)]", units5 == [(0, 1), (3, 3)], repr(units5))

finish()
