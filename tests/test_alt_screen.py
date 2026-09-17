# -*- coding: utf-8 -*-
"""v1.2.12 — Terminal: alternate screen (private modes 47/1047/1048/1049).

The thematic test of the theme of the release (ROADMAP v1.2.12, the PYTE82_AUDIT.md pack B):
the SshmapHistoryScreen implements the alternate screen that pyte 0.8.2 does not have
(the modes were inert bits of screen.mode with the <<5 shift, no handlers).
The semantics — per the upstream PR #212 (closed without a merge, the author dwgx; the code of pyte is LGPL-3.0 —
the attribution in the comment to the code), differentially verified against tmux 3.6b
and GNU screen. Headless: the synthetic byte sequences into the TerminalScreen
(without Qt, without the network):

  * the round-trip (the main): the shell output → the snapshot G0 with the colors;
    \x1b[?1049h\x1b[2J\x1b[H + the "TUI frame" → the grid = the TUI; \x1b[?1049l → the grid
    is equal to G0 character by character (including the fg/bg) and the cursor;
  * the matrix of the enters/exits over ALL the combinations of {47, 1047, 1048, 1049}
    (the enter a → the exit b — always the return to the main screen) + the re-enter is idempotent;
  * the cross exit: 1049h … 47l → the exit (one in_alt flag, not four);
  * the double enter: 1049h 1049h → the main screen is not lost, one exit returns;
  * the cursor: (5,3) → 1049h (NOT homed) → the TUI drives the cursor → 1049l → again (5,3);
    for 47/1047 — NOT restored (pinned down by the specification);
  * the history isolation: 50+ lines in the alt (scrolling past the edge) → the exit → the TUI lines
    are not in the scrollback (like less in a real terminal);
  * the RIS (ESC c — NOT ESC [ c, this is the CSI DA) inside the alt → the main screen, everything clean,
    the modes are the defaults;
  * the resize in the alt: the enter at 120 columns → resize(80) → the exit → the lines of the main
    screen are cut down to 80 (no "over-wide" restoration);
  * the enter during the history viewing: the auto-return to the live fired, the alt is active.

Run: python tests/test_alt_screen.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from third_party import pyte          # v1.3rc1: the fork (MANIFEST.md)
from third_party.pyte import screens as P

import modules.terminal_screen as TS
from modules.terminal_screen import SshmapHistoryScreen, TerminalScreen


def make(cols=120, lines=32, history_lines=1000):
    return TerminalScreen(columns=cols, lines=lines, history_lines=history_lines)


def rows(t):
    """The snapshot of the grid (the rows from the snapshot)."""
    return t.snapshot()[0]


def empty_grid(t):
    """The fully default grid columns×lines (the empty buffer)."""
    d = P.Char(data=" ", fg="default", bg="default")
    return [[d] * t.columns for _ in range(t.lines)]


# Shell output with colors (SGR 1;32 / 1;34 / 34 / 93 / 256-color) — the "main screen".
SHELL = (b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ls\r\n"
         b"\x1b[0;34mdocs\x1b[0m  \x1b[93mnotes.txt\x1b[0m  \x1b[38;5;196mall.xml\x1b[0m\r\n"
         b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ")

# "The TUI frame": a full repaint + the frame + the colored lines.
TUI_FRAME = (b"\x1b[2J\x1b[H"
             b"+-----------------------------+\r\n"
             b"| TUI frame (alt screen)      |\r\n"
             b"|\x1b[41m red bar \x1b[0m                    |\r\n"
             b"+-----------------------------+\r\n"
             b"\x1b[7;1H\x1b[36mcursor parked here\x1b[0m")


# ════════════════════════════════════════════════════════════
# 0. Wiring: the constant, the accessors, the bits in mode
# ════════════════════════════════════════════════════════════
print("== wiring ==")

check("wiring: ALTSCREEN_MODES = (47, 1047, 1048, 1049) — the private codes BEFORE the <<5 shift",
      SshmapHistoryScreen.ALTSCREEN_MODES == (47, 1047, 1048, 1049),
      str(SshmapHistoryScreen.ALTSCREEN_MODES))

t = make()
check("wiring: a fresh screen — in_alt_screen() False, screen.in_alt False",
      t.in_alt_screen() is False and t.screen.in_alt is False)
t.feed(b"\x1b[?1049h")
check("wiring: the bit lands in mode as before (1049 << 5 = 33568)",
      (1049 << 5) in t.screen.mode, str(sorted(t.screen.mode)))
t.feed(b"\x1b[?1049l")
check("wiring: after the exit the bit is cleared", (1049 << 5) not in t.screen.mode)


# ════════════════════════════════════════════════════════════
# 1. Round-trip (the main one): shell → G0 with colors; TUI in alt; return character by character
# ════════════════════════════════════════════════════════════
print("== round-trip ==")

t = make()
t.feed(SHELL)
g0 = t.snapshot()   # (rows, cx, cy, hidden) — a snapshot with colors BEFORE entering alt

t.feed(b"\x1b[?1049h")
check("round-trip: 1049h → in_alt True", t.in_alt_screen() is True)
check("round-trip: the working buffer is EMPTY after the entry (the TUI has not drawn yet)",
      rows(t) == empty_grid(t))

t.feed(TUI_FRAME)
txt = "\n".join(t.screen.display)
check("round-trip: the grid = the TUI (frame + 'red bar'), no shell content",
      "TUI frame (alt screen)" in txt and "red bar" in txt
      and "root@master" not in txt, txt[:80])

t.feed(b"\x1b[?1049l")
check("round-trip: 1049l → in_alt False", t.in_alt_screen() is False)
g1 = t.snapshot()
check("round-trip: the grid equals G0 character by character (including fg/bg)", g1[0] == g0[0])
check("round-trip: the cursor and hidden are restored", (g1[1], g1[2], g1[3]) == (g0[1], g0[2], g0[3]),
      f"got=({g1[1]},{g1[2]},{g1[3]}) want=({g0[1]},{g0[2]},{g0[3]})")


# ════════════════════════════════════════════════════════════
# 2. The enter/exit matrix: all pairs {47, 1047, 1048, 1049} + idempotency
# ════════════════════════════════════════════════════════════
print("== matrix ==")

MODES = (47, 1047, 1048, 1049)
matrix_ok = True
detail = ""
for a in MODES:
    for b in MODES:
        tm = make(80, 24)
        tm.feed(SHELL)
        r0 = rows(tm)
        tm.feed(("\x1b[?%dh" % a).encode())
        if not tm.in_alt_screen():
            matrix_ok = False
            detail = f"enter {a}: in_alt False"
            break
        tm.feed(b"\x1b[2J\x1b[H" + b"TUI " + str(a).encode() + b"\r\n")
        tm.feed(("\x1b[?%dl" % b).encode())
        if tm.in_alt_screen() or rows(tm) != r0:
            matrix_ok = False
            detail = f"{a}h→{b}l: in_alt={tm.in_alt_screen()} grid_changed={rows(tm) != r0}"
            break
    if not matrix_ok:
        break
check("the 4×4 matrix: entry a → exit b (any combination) — always a return to the main screen",
      matrix_ok, detail)

# A repeated entry is idempotent: the second h does NOT clobber the saved main buffer.
tm = make(80, 24)
tm.feed(SHELL)
r0 = rows(tm)
tm.feed(b"\x1b[?1049h")
saved_ref = tm.screen._saved_buffer
tm.feed(b"\x1b[?1047h")   # a repeated entry (by another code) — idempotent
check("a repeated entry is idempotent: the saved main buffer is not replaced",
      tm.screen._saved_buffer is saved_ref and tm.in_alt_screen() is True)
tm.feed(b"\x1b[?1049l")   # ONE exit returns
check("repeated entry: a single exit returns the main screen",
      rows(tm) == r0 and tm.in_alt_screen() is False)

# A cross exit: 1049h … 47l → exit (one in_alt flag, not four).
tm = make(80, 24)
tm.feed(SHELL)
r0 = rows(tm)
tm.feed(b"\x1b[?1049h")
check("cross exit: 1049h → in_alt True", tm.in_alt_screen() is True)
tm.feed(b"\x1b[?47l")
check("cross exit: 47l exits the screen entered via 1049h (one flag)",
      tm.in_alt_screen() is False and rows(tm) == r0)

# A double entry: 1049h 1049h → the main screen is not lost, one exit returns.
tm = make(80, 24)
tm.feed(SHELL)
r0 = rows(tm)
tm.feed(b"\x1b[?1049h\x1b[?1049h")
check("double entry: in_alt True, the main buffer is kept (a single _saved_buffer)",
      tm.in_alt_screen() is True and isinstance(tm.screen._saved_buffer, dict))
tm.feed(b"\x1b[?1049l")
check("double entry: a single exit returns the main screen",
      rows(tm) == r0 and tm.in_alt_screen() is False)


# ════════════════════════════════════════════════════════════
# 3. Cursor: 1048/1049 save/restore; 47/1047 — no (per the specification)
# ════════════════════════════════════════════════════════════
print("== cursor ==")

tm = make()
tm.feed(b"\x1b[4;6H")   # CUP 4;6 → (x=5, y=3)
check("the cursor is set to (5,3)", tm.snapshot()[1:3] == (5, 3))
tm.feed(b"\x1b[?1049h")
check("1049h: the cursor is NOT homed on entry (the TUI sends CUP itself) — it stays at (5,3)",
      tm.snapshot()[1:3] == (5, 3), str(tm.snapshot()[1:3]))
tm.feed(b"\x1b[2J\x1b[H" + TUI_FRAME)   # The TUI drives the cursor: CUP 7;1 + 18 characters of output → (18,6)
check("in alt: the TUI dragged the cursor to (18,6)", tm.snapshot()[1:3] == (18, 6), str(tm.snapshot()[1:3]))
tm.feed(b"\x1b[?1049l")
check("1049l: the cursor is back at (5,3) — saved in a separate field _alt_cursor",
      tm.snapshot()[1:3] == (5, 3), str(tm.snapshot()[1:3]))

for m in (47, 1047):
    tm = make()
    tm.feed(b"\x1b[4;6H")
    tm.feed(("\x1b[?%dh" % m).encode())
    tm.feed(b"\x1b[2J\x1b[H\x1b[10;20H")   # The TUI drives the cursor → (19, 9)
    tm.feed(("\x1b[?%dl" % m).encode())
    check("cursor: %d — NOT restored (the xterm spec: only 1048/1049); "
          "it stayed at the TUI position (19,9)" % m,
          tm.snapshot()[1:3] == (19, 9), str(tm.snapshot()[1:3]))


# ════════════════════════════════════════════════════════════
# 4. History isolation: TUI lines do not enter the scrollback (like less)
# ════════════════════════════════════════════════════════════
print("== history isolation ==")

tm = make(80, 10, history_lines=200)
for i in range(40):
    tm.feed(b"MAIN %d\r\n" % i)
top_before = len(tm.screen.history.top)
pos_before, size_before = tm.scroll_info()

tm.feed(b"\x1b[?1049h")
for i in range(60):          # 60 lines with a 10-line alt — scrolling past the edge
    tm.feed(b"TUI-%d\r\n" % i)
check("in alt: the lines scrolled past the edge do NOT land in history.top",
      len(tm.screen.history.top) == top_before,
      f"{len(tm.screen.history.top)} vs {top_before}")

tm.feed(b"\x1b[?1049l")
check("after the exit: the history did not grow, the position is unchanged",
      len(tm.screen.history.top) == top_before and tm.scroll_info() == (pos_before, size_before),
      str((len(tm.screen.history.top),) + tm.scroll_info()))

while tm.scroll_up():
    pass
check("scrollback: NO TUI lines in the history (like less in a real terminal)",
      "TUI-" not in "\n".join(tm.screen.display))


# ════════════════════════════════════════════════════════════
# 5. RIS (ESC c) inside alt: a full reset + exit, the modes are default
# ════════════════════════════════════════════════════════════
print("== RIS in alt ==")

tm = make()
tm.feed(SHELL)
tm.feed(b"\x1b[?1049h" + TUI_FRAME)
check("RIS: before the reset — in alt, the grid = the TUI", tm.in_alt_screen() is True
      and "TUI frame" in "\n".join(tm.screen.display))
tm.feed(b"\x1bc")   # RIS = ESC c (NOT \x1b[c — that is CSI DA)
check("RIS in alt: the exit from alt (in_alt False)", tm.in_alt_screen() is False)
check("RIS in alt: the main screen is cleared by the regular reset() — the grid is fully default",
      rows(tm) == empty_grid(tm))
check("RIS in alt: the modes are default (+LNM v1.2.11): mode == {DECAWM, DECTCEM, LNM}",
      tm.screen.mode == {pyte.modes.DECAWM, pyte.modes.DECTCEM, pyte.modes.LNM},
      str(sorted(tm.screen.mode)))
check("RIS in alt: the history is cleared as usual (top is empty, position == size)",
      len(tm.screen.history.top) == 0 and tm.scroll_info()[0] == tm.scroll_info()[1])


# ════════════════════════════════════════════════════════════
# 6. Resize in alt: exit clips the saved buffer to the current width
# ════════════════════════════════════════════════════════════
print("== resize in alt ==")

tm = make(120, 32)
tm.feed(b"A" * 100 + b"\r\nshort line\r\n")   # the line is WIDER than the future width (80)
tm.feed(b"\x1b[?1049h")
tm.resize(80, 32)                              # a resize during alt
check("resize in alt: the grid is 80 columns now", tm.screen.columns == 80)
tm.feed(b"\x1b[2J\x1b[H" + b"B" * 80 + b"\r\n")
tm.feed(b"\x1b[?1049l")
disp = tm.screen.display
check("resize in alt: the main-screen lines are clipped to 80 (row 0 = the first 80 'A')",
      disp[0] == "A" * 80 and len(disp[0]) == 80, repr(disp[0][:90]))
check("resize in alt: no over-wide restoration (all the line keys < columns)",
      all(max(line, default=-1) < tm.screen.columns for line in tm.screen.buffer.values()))
check("resize in alt: the content is preserved (row 1 = 'short line')",
      disp[1].startswith("short line"), repr(disp[1][:20]))


# ════════════════════════════════════════════════════════════
# 7. Entering while viewing history: the auto-return to live fired, alt is active
# ════════════════════════════════════════════════════════════
print("== entry while viewing history ==")

tm = make(80, 10, history_lines=200)
for i in range(50):
    tm.feed(b"HIST %d\r\n" % i)
check("entry while viewing history: scrolled back (position < size)",
      tm.scroll_up() is True and tm.scroll_info()[0] < 200, str(tm.scroll_info()))
tm.feed(b"\x1b[?1049h" + TUI_FRAME)
check("entry while viewing history: the auto-return to live fired (position == size)",
      tm.scroll_info()[0] == 200, str(tm.scroll_info()))
check("entry while viewing history: alt is active, the grid = the TUI",
      tm.in_alt_screen() is True and "TUI frame" in "\n".join(tm.screen.display))
tm.feed(b"\x1b[?1049l")
check("the exit after the entry from the history: the main screen is in place",
      tm.in_alt_screen() is False and "HIST" in "\n".join(tm.screen.display))


# ════════════════════════════════════════════════════════════
# 8. Release state + i18n parity (no new keys — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_release_state(ROOT)
check_i18n_parity(load_i18n_langs(ROOT))

finish()
