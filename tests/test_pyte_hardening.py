# -*- coding: utf-8 -*-
"""v1.5.7.1 — Terminal: the pyte fork takes the five defects of the dependency audit.

The topical test of the release (ROADMAP v1.5.7.1; the audit — PYTE82_AUDIT.md, the raise-review
section; the ledger entries — AUDIT_PENDING.md N26–N30, which LEAVE the ledger with this release,
their probes becoming the checks below). The theme is the vendored emulator, so every probe runs
through the APPLICATION's own seam — `TerminalScreen.feed()` / `SshmapHistoryScreen` — or through
the canvas contract that reads the same grid (`modules.terminal_widget.char_width()`); nothing here
needs Qt, the network or a PTY.

  * §1 patch 0005 — a grapheme cluster: an emoji sequence (ZWJ, VS16), a keycap and the marks whose
    canonical combining class is 0 (Thai Mn, Devanagari Mc) land WHOLE; before the patch `draw()`
    `break`ed out of the whole data string on the first zero-width code point and dropped the rest
    of the chunk in silence (no exception, no log line — N26);
  * §2 patch 0006 — a malformed CSI: NO final of the fork's CSI table raises for a surplus
    parameter or a stray private marker, the tail of the chunk survives, and the public sequences
    (DECSTBM, CUP, EL) keep their behaviour (N27);
  * §3 patch 0007 — an erase mode the handler does not know (`ESC[3K`, `ESC[4J`) is a no-op that
    marks nothing for redraw, while `0K`/`1K`/`2K`/`3J` and the `ED 3` scrollback reset do not
    move (N28);
  * §4 patch 0008 — DECOM without a scrolling region: VPA and the DSR report neither raise out of
    `feed()` nor go silent (the DSR ANSWERS), and the arithmetic with a region is unchanged (N29);
  * §5 patch 0009 — a resize keeps the cursor inside the new geometry, so the next text is visible
    (a row shrink used to swallow the first line, a width shrink the first character — N30);
  * §6 the CANVAS half of patch 0005: `char_width()` measures a multi-code-point cell with
    `wcswidth` (the same table the grid uses) and a single code point with `wcwidth`, so a run after
    a cluster starts where the grid put it — the CJK layout of v1.2.9 is untouched;
  * §7 the release state (§9 of AGENTS.md) — the version pins and the i18n parity.

Run: python tests/test_pyte_hardening.py   (from the project root) or python tests/run_all.py
"""
from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from wcwidth import wcswidth as _wcswidth, wcwidth as _wcwidth  # noqa: E402

from third_party import pyte          # the fork itself (MANIFEST.md)  # noqa: E402
import modules.terminal_widget as TW  # the canvas half of patch 0005 (headless: pure functions)  # noqa: E402
from modules.terminal_screen import TerminalScreen  # noqa: E402


def lines(scr):
    """screen.display → the lines without the trailing spaces."""
    return [line.rstrip() for line in scr.display]


def app(cols=120, rows=32, history=1000):
    """The application's screen — the seam every probe below goes through."""
    return TerminalScreen(cols, rows, history_lines=history)


def row_text(screen, y=0):
    """One grid row as text (the canvas' own reading of a row)."""
    return "".join(screen.buffer[y][x].data for x in range(screen.columns))


ZWJ_FAMILY = "\U0001f469\u200d\U0001f469"          # 👩‍👩 — two code points + a ZWJ
HEART_VS16 = "\u2764\ufe0f"                        # ❤️ — a base + the emoji presentation selector
KEYCAP_1 = "1\ufe0f\u20e3"                         # 1️⃣ — the Me mark is the point of the M-extend rule


# ════════════════════════════════════════════════════════════════════════════
print("== §1 patch 0005 — a grapheme cluster lands whole (N26: the silent truncation) ==")
# ════════════════════════════════════════════════════════════════════════════

# The defect: everything after the sequence used to be dropped. The trailing "B" is the witness.
for _text, _what in ((f"A{HEART_VS16}B", "a heart + VS16"),
                     (f"A{ZWJ_FAMILY}B", "a ZWJ family emoji"),
                     (f"A{KEYCAP_1}B", "a keycap (Me, class 0)"),
                     ("a\u0e01\u0e31b", "a Thai vowel sign (Mn, class 0)"),
                     ("x\u0915\u093ey", "a Devanagari matra (Mc, class 0)")):
    _t = app(20, 3)
    _t.feed(_text.encode("utf-8"))
    _line = lines(_t.screen)[0]
    check(f"§1 {_what} survives as a whole line (was: the chunk tail was dropped)",
          _line == _text, repr(_line))

# The canvas reads the same text: the grid row carries the cluster and the text after it.
_t = app(20, 3)
_t.feed(f"ab{ZWJ_FAMILY}cd".encode("utf-8"))
check("§1 the grid row carries the cluster and the text after it",
      row_text(_t.screen).startswith(f"ab{ZWJ_FAMILY}cd"), repr(row_text(_t.screen)))

# The NFC merge of 0.8.2 is preserved: a decomposed stream produces the composed cell, so a search
# over TerminalScreen.text_lines() finds what a user types.
_t = app(20, 3)
_t.feed("A\u0301B".encode("utf-8"))
check("§1 a combining mark is still merged with NFC (\"A\" + U+0301 → ONE cell \"Á\")",
      lines(_t.screen)[0] == "\u00c1B" and len(_t.screen.buffer[0][0].data) == 1
      and _t.screen.cursor.x == 2,
      f"{row_text(_t.screen)!r} cursor={_t.screen.cursor.x}")

# A wide cluster occupies TWO cells and leaves the placeholder the canvas skips.
_t = app(20, 3)
_t.feed(f"a{ZWJ_FAMILY}".encode("utf-8"))
check("§1 a wide cluster is ONE cell + the placeholder, and the cursor moved by its WIDTH",
      _t.screen.buffer[0][1].data == ZWJ_FAMILY and _t.screen.buffer[0][2].data == ""
      and _t.screen.cursor.x == 3,
      repr([_t.screen.buffer[0][x].data for x in range(4)]) + f" x={_t.screen.cursor.x}")

# The find bar / the transcript read the joined cell data: a search for the cluster's text works.
check("§1 text_lines() contains the cluster exactly once",
      sum(line.count(ZWJ_FAMILY) for line in _t.text_lines()) == 1,
      repr([line for line in _t.text_lines() if ZWJ_FAMILY in line]))

# display() no longer asserts on a cluster (upstream's `assert sum(map(wcwidth, char[1:])) == 0`).
_w = pyte.HistoryScreen(20, 3)
try:
    pyte.ByteStream(_w).feed(f"a{ZWJ_FAMILY}b".encode("utf-8"))
    _display_exc = ""
except Exception as _e:  # noqa: BLE001
    _display_exc = repr(_e)
check("§1 display() does not raise on a cluster (the old assert refused a multi-code-point cell)",
      _display_exc == "", _display_exc)


# ════════════════════════════════════════════════════════════════════════════
print("== §2 patch 0006 — a malformed CSI is ignored, not raised (N27) ==")
# ════════════════════════════════════════════════════════════════════════════

_finals = sorted(pyte.Stream(pyte.Screen(10, 5)).csi)
_crashes = []
for _final in _finals:
    for _seq in (f"\x1b[?0{_final}", f"\x1b[1;2{_final}"):
        try:
            pyte.Stream(pyte.Screen(10, 5)).feed(_seq)
        except Exception as _e:  # noqa: BLE001
            _crashes.append((_seq, repr(_e)))
check(f"§2 no final of the CSI table ({len(_finals)}) raises — surplus parameter or private marker",
      not _crashes, str(_crashes[:2]))

# The same shape through the application's seam (a TUI's exit sequence is what a user sees).
_app_crashes = []
for _seq in (b"\x1b[1;2A", b"\x1b[?0A", b"\x1b[1;2;3H", b"\x1b[0;0@"):
    _t = app(20, 5)
    try:
        _t.feed(_seq)
    except Exception as _e:  # noqa: BLE001
        _app_crashes.append((_seq, repr(_e)))
check("§2 the same four malformed sequences raise nothing through TerminalScreen.feed",
      not _app_crashes, str(_app_crashes))

# The point of the whole class: the tail of the CHUNK survives (the TypeError used to abort
# feed() and with it everything the read carried after the sequence).
_t = app(40, 5)
_t.feed(b"\x1b[1;2A" + b"after the malformed CSI")
check("§2 the tail of the chunk is drawn after a malformed CSI",
      lines(_t.screen)[0] == "after the malformed CSI", repr(lines(_t.screen)[0]))

# The PUBLIC sequences are byte-for-byte untouched.
_t = app(20, 5)
_t.feed(b"\x1b[1;5r")
check("§2 the public DECSTBM still sets the region (vim/less splits)",
      (_t.screen.margins.top, _t.screen.margins.bottom) == (0, 4), str(_t.screen.margins))
_t = app(20, 5)
_t.feed(b"\x1b[3;4HX")
check("§2 the public CUP still positions the cursor",
      lines(_t.screen)[2].strip() == "X", repr(lines(_t.screen)[2]))
_t = app(20, 5)
_t.feed(b"abcdef\x1b[3G\x1b[0K")
check("§2 the public EL 0 still erases to the end of the line",
      lines(_t.screen)[0] == "ab", repr(lines(_t.screen)[0]))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 patch 0007 — an erase mode the handler does not know is a no-op (N28) ==")
# ════════════════════════════════════════════════════════════════════════════

for _seq, _what in ((b"\x1b[3K", "EL 3 (xterm gives Ps = 3 to ED)"), (b"\x1b[4J", "ED 4")):
    _t = app(20, 5)
    try:
        _t.feed(b"abc" + _seq)
        _exc = ""
    except Exception as _e:  # noqa: BLE001
        _exc = repr(_e)
    check(f"§3 {_what} is a no-op: no exception and the line untouched",
          _exc == "" and lines(_t.screen)[0] == "abc",
          f"{_exc!r} line={lines(_t.screen)[0]!r}")

# A refused mode marks NO line for redraw (the `dirty` ordering of the patch).
_t = app(20, 5)
_t.feed(b"\x1b[2J")                      # a full redraw, so the dirty set is meaningful
_clean = set(_t.screen.dirty)
_t.feed(b"\x1b[3K\x1b[4J")
check("§3 a refused erase mode adds nothing to screen.dirty",
      set(_t.screen.dirty) <= _clean, f"{sorted(_t.screen.dirty)} vs {sorted(_clean)}")

# The public erase modes keep their behaviour.
_t = app(20, 5)
_t.feed(b"abcdef\x1b[4G\x1b[2K")
check("§3 the public EL 2 still erases the whole line", lines(_t.screen)[0] == "",
      repr(lines(_t.screen)[0]))
_t = app(20, 5)
_t.feed(b"abcdef\x1b[1;3H\x1b[1K")
check("§3 the public EL 1 still erases to the left of the cursor (inclusive)", lines(_t.screen)[0] == "   def",
      repr(lines(_t.screen)[0]))
_t = app(20, 5)
_t.feed(b"abcdef\x1b[0J")
check("§3 the public ED 0 leaves the line it starts on alone", lines(_t.screen)[0] == "abcdef",
      repr(lines(_t.screen)[0]))
_t = app(20, 3)
_t.feed(b"one\r\ntwo\r\nthree\r\nfour")
_scrolled = len(_t.screen.history.top)
_t.feed(b"\x1b[3J")
check("§3 the public ED 3 still drops the scrollback (the HistoryScreen rule)",
      _scrolled > 0 and not _t.screen.history.top,
      f"top before={_scrolled}, after={len(_t.screen.history.top)}")


# ════════════════════════════════════════════════════════════════════════════
print("== §4 patch 0008 — DECOM without a scrolling region cannot raise (N29) ==")
# ════════════════════════════════════════════════════════════════════════════

for _seq, _what in ((b"\x1b[?6h\x1b[5d", "VPA (cursor_to_line)"),
                    (b"\x1b[?6h\x1b[6n", "the DSR cursor-position report")):
    _t = app(20, 5)
    try:
        _t.feed(_seq)
        _exc = ""
    except Exception as _e:  # noqa: BLE001
        _exc = repr(_e)
    check(f"§4 DECOM, no region: {_what} raises nothing out of feed()", _exc == "", _exc)

# A DSR nobody answers desynchronises every later reply — the report must COME OUT.
_answers = []
_t = app(20, 5)
_t.screen.write_process_input = _answers.append
_t.feed(b"\x1b[?6h\x1b[1;1H\x1b[6n")
check("§4 DECOM, no region: the DSR really answers \"1;1R\" (no silence)",
      _answers == ["\x1b[1;1R"], repr(_answers))

# The direct call the ledger's probe names.
_scr = pyte.Screen(10, 5)
_scr.set_mode(pyte.modes.DECOM)
try:
    _scr.cursor_to_line(3)
    _direct_exc = ""
except Exception as _e:  # noqa: BLE001
    _direct_exc = repr(_e)
check("§4 the direct Screen.cursor_to_line(3) under DECOM raises nothing", _direct_exc == "",
      _direct_exc)

# With a REGION the arithmetic is byte-for-byte what it was.
_t = app(20, 6)
_t.feed(b"\x1b[2;4r\x1b[?6h\x1b[2d")
check("§4 DECOM WITH a region: VPA 2 → line 2 of the region (y=2)", _t.screen.cursor.y == 2,
      str(_t.screen.cursor.y))
_answers = []
_t = app(20, 6)
_t.screen.write_process_input = _answers.append
_t.feed(b"\x1b[2;4r\x1b[?6h\x1b[3;1H\x1b[6n")
check("§4 DECOM WITH a region: the DSR answer is relative to the region (3;1R)",
      _answers == ["\x1b[3;1R"], repr(_answers))
_answers = []
_t = app(20, 6)
_t.screen.write_process_input = _answers.append
_t.feed(b"\x1b[3;2H\x1b[6n")
check("§4 without DECOM the DSR answer is absolute (3;2R)", _answers == ["\x1b[3;2R"],
      repr(_answers))


# ════════════════════════════════════════════════════════════════════════════
print("== §5 patch 0009 — a resize keeps the cursor (and the next text) inside (N30) ==")
# ════════════════════════════════════════════════════════════════════════════

# The row shrink: the first line printed afterwards used to land on a phantom row.
_t = app(120, 32)
_t.feed(b"".join(b"line %d\r\n" % n for n in range(20)))
_before_y = _t.screen.cursor.y
_t.resize(60, 12)
check("§5 a row shrink puts the cursor (y=20 before) inside the new 12 rows",
      _before_y == 20 and _t.screen.cursor.y < 12,
      f"y was {_before_y}, now {_t.screen.cursor.y} in {_t.screen.lines} rows")
_t.feed(b"VISIBLE\r\n")
check("§5 the first text after a row shrink is VISIBLE (was: swallowed)",
      any("VISIBLE" in line for line in lines(_t.screen)), repr(lines(_t.screen)[:4]))

# The width shrink: the first character used to be lost and the line broken.
_t = app(120, 32)
_t.feed(b"x" * 100)
_before_x = _t.screen.cursor.x
_t.resize(60, 32)
check("§5 a width shrink puts the cursor (x=100 before) inside the new 60 columns",
      _before_x == 100 and _t.screen.cursor.x < 60,
      f"x was {_before_x}, now {_t.screen.cursor.x} in {_t.screen.columns} columns")
_t.feed(b"Z")
check("§5 the text after a width shrink is VISIBLE (was: the first character was lost)",
      "Z" in row_text(_t.screen), repr(row_text(_t.screen)[-6:]))

# The invariant the report states, on both axes, for a plain pyte Screen too.
_scr = pyte.Screen(120, 32)
pyte.Stream(_scr).feed("".join(f"line {n}\r\n" for n in range(20)))
_scr.resize(lines=12, columns=60)
check("§5 the resize invariant holds: 0 <= cursor.y < lines and 0 <= cursor.x <= columns",
      0 <= _scr.cursor.y < _scr.lines and 0 <= _scr.cursor.x <= _scr.columns,
      f"({_scr.cursor.x}, {_scr.cursor.y}) in {_scr.columns}x{_scr.lines}")

# A resize to the SAME size is still the documented no-op, and a growing resize does not move.
_t = app(40, 10)
_t.feed(b"\x1b[6;7H")
_before = (_t.screen.cursor.x, _t.screen.cursor.y)
_t.resize(40, 10)
check("§5 a same-size resize is still a no-op for the cursor",
      (_t.screen.cursor.x, _t.screen.cursor.y) == _before,
      str((_t.screen.cursor.x, _t.screen.cursor.y)))
_t.resize(80, 20)
check("§5 a growing resize leaves the cursor where it was",
      (_t.screen.cursor.x, _t.screen.cursor.y) == _before,
      str((_t.screen.cursor.x, _t.screen.cursor.y)))


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the canvas contract of patch 0005 — char_width() == the grid's table ==")
# ════════════════════════════════════════════════════════════════════════════

check("§6 a single code point is measured with wcwidth (the 0.8.2 table, unchanged)",
      all(TW.char_width(ch) == max(0, _wcwidth(ch)) for ch in "aM \u4e2d\u2764"),
      str([(ch, TW.char_width(ch)) for ch in "aM \u4e2d\u2764"]))
check("§6 an empty cell (the placeholder) is 0 wide", TW.char_width("") == 0)
check("§6 a multi-code-point cell is measured with wcswidth — the table the GRID uses",
      all(TW.char_width(c) == max(0, _wcswidth(c)) for c in (ZWJ_FAMILY, HEART_VS16, KEYCAP_1)),
      str([(c, TW.char_width(c), _wcswidth(c)) for c in (ZWJ_FAMILY, HEART_VS16, KEYCAP_1)]))
check("§6 ...and the per-code-point sum would have been WRONG for the ZWJ family (2 vs 4)",
      sum(max(0, _wcwidth(c)) for c in ZWJ_FAMILY) == 4 and TW.char_width(ZWJ_FAMILY) == 2,
      f"sum={sum(max(0, _wcwidth(c)) for c in ZWJ_FAMILY)} char_width={TW.char_width(ZWJ_FAMILY)}")
check("§6 is_wide_char() marks the wide cells (CJK, the ZWJ family, the keycap) and no others",
      TW.is_wide_char("\u4e2d") and TW.is_wide_char(ZWJ_FAMILY) and TW.is_wide_char(KEYCAP_1)
      and not TW.is_wide_char("a") and not TW.is_wide_char(""),
      str([(c, TW.char_width(c)) for c in ("\u4e2d", ZWJ_FAMILY, KEYCAP_1, "a", "")]))

# The run painter walks the row with this function: a cluster must be its own wide run, and the cell
# after the placeholder must not be swallowed.
_t = app(20, 3)
_t.feed(f"a{ZWJ_FAMILY}b".encode("utf-8"))
_rows, _cx, _cy, _hidden = _t.snapshot()
_runs = TW.split_row_runs(_rows[0])
_wide = [(x, text) for x, text, is_wide in _runs if is_wide]
check("§6 split_row_runs() makes the cluster ONE wide run at the grid column the grid used",
      len(_wide) == 1 and _wide[0][0] == 1 and _wide[0][1] == ZWJ_FAMILY, str(_wide))
check("§6 the run after the placeholder resumes at the column the grid put it in",
      any(x == 3 and text.startswith("b") for x, text, is_wide in _runs if not is_wide),
      str([(x, text) for x, text, _w in _runs]))

# The CJK layout of v1.2.9 is untouched: a wide glyph = 2 cells + the stub, total = wcswidth.
_t = app(20, 3)
_t.feed("a\u4e2db".encode("utf-8"))
_rows, _cx, _cy, _hidden = _t.snapshot()
check("§6 the CJK E2E is unchanged: 'a中b' = [a][中][''][b] and the total width is wcswidth",
      [_rows[0][x].data for x in range(4)] == ["a", "\u4e2d", "", "b"]
      and sum(TW.char_width(_rows[0][x].data) for x in range(4)) == _wcswidth("a\u4e2db") == 4,
      repr([_rows[0][x].data for x in range(4)]))


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

finish()
