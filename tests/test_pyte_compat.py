# -*- coding: utf-8 -*-
"""v1.2.11 — Terminal: pyte 0.8.2 compatibility (private SGR + LNM).

Headless (no Qt): `SshmapHistoryScreen(pyte.HistoryScreen)` in `modules/terminal_screen.py` has two
overrides. (1) Private SGR (`CSI ? … m`) are IGNORED — the verified fact of `MANIFEST.md`: in pyte 0.8.2
`\x1b[?4m` (Vim 9+, upstream issue #202) raises a TypeError out of `feed()` and the tail of the chunk is
lost (the parser is reset and `_on_output`'s `except Exception: return` swallows it). Upstream merged the
fix (PR #203), and the override with the same semantics stays until the pin rises to pyte 0.8.3.
(2) LNM (mode 20) is ON by default, so a bare LF is CR+LF (the xterm behaviour): `Screen.reset()` restores `_DEFAULT_MODE` without LNM, hence the explicit restoration in `__init__` and in `reset()`, while an explicit `\x1b[20h` / `\x1b[20l` from the remote program still works. Note the plan's typo: the sequences are written there as `\x1b[2h` / `\x1b[2l`, but LNM is mode 20, and the RIS is `ESC c` (`\x1bc`) — NOT the CSI DA `\x1b[c`, which does not call `Screen.reset()` at all."""
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from third_party import pyte          # v1.3rc1: the fork (MANIFEST.md)

from modules.terminal_screen import TerminalScreen, SshmapHistoryScreen


def lines(scr):
    """screen.display → a list of lines without trailing spaces (a headless snapshot)."""
    return [line.rstrip() for line in scr.screen.display]


# ════════════════════════════════════════════════════════════
# 1. The subclass is in place: TerminalScreen creates an SshmapHistoryScreen
# ════════════════════════════════════════════════════════════
print("== SshmapHistoryScreen wiring (headless) ==")

scr = TerminalScreen(columns=40, lines=5, history_lines=10)
check("TerminalScreen creates an SshmapHistoryScreen",
      isinstance(scr.screen, SshmapHistoryScreen), type(scr.screen).__name__)
check("…and it is still a pyte.HistoryScreen (the scrollback duck-typing)",
      isinstance(scr.screen, pyte.HistoryScreen))
check("LNM is on in the default mode after the constructor",
      pyte.modes.LNM in scr.screen.mode, str(sorted(scr.screen.mode)))


# ════════════════════════════════════════════════════════════
# 2. Private SGR (A1): \x1b[?4m — no TypeError, the chunk tail is preserved
# ════════════════════════════════════════════════════════════
print("== private SGR (Vim 9+) ==")

scr2 = TerminalScreen(columns=40, lines=5, history_lines=10)
disp_before = lines(scr2)
mode_before = set(scr2.screen.mode)
cur_before = (scr2.screen.cursor.x, scr2.screen.cursor.y, scr2.screen.cursor.hidden)
detail_exc = ""
try:
    scr2.feed(b"\x1b[?4m")          # Vim 9+ (upstream issue #202): in 0.8.2 — a TypeError from feed()
except Exception as e:              # noqa: BLE001
    detail_exc = repr(e)
check("feed(b'\\x1b[?4m') — no exceptions (0.8.2 had a TypeError)", detail_exc == "", detail_exc)
check("display is unchanged", lines(scr2) == disp_before, repr(lines(scr2)))
check("the mode is unchanged", set(scr2.screen.mode) == mode_before, str(sorted(scr2.screen.mode)))
check("the cursor is unchanged (x, y, hidden)",
      (scr2.screen.cursor.x, scr2.screen.cursor.y, scr2.screen.cursor.hidden) == cur_before,
      f"{(scr2.screen.cursor.x, scr2.screen.cursor.y, scr2.screen.cursor.hidden)} vs {cur_before}")

# A regression on the chunk tail loss: after a private SGR the parser must live on.
scr3 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr3.feed(b"AB\x1b[?4mCD\r\n")
check("the chunk tail is preserved: b'AB\\x1b[?4mCD\\r\\n' → the line \"ABCD\"",
      lines(scr3)[0] == "ABCD", repr(lines(scr3)[0]))

# A Private SGR with several parameters — also ignored.
scr3b = TerminalScreen(columns=40, lines=5, history_lines=10)
scr3b.feed(b"X\x1b[?4;11mY\r\n")
check("private SGR with parameters (\\x1b[?4;11m): the tail is preserved → \"XY\"",
      lines(scr3b)[0] == "XY", repr(lines(scr3b)[0]))

# An ordinary (non-private) SGR is not touched by the override.
scr4 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr4.feed(b"\x1b[31mR\x1b[0m")
check("a plain SGR works: \\x1b[31m → fg='red'", scr4.screen.buffer[0][0].fg == "red",
      repr(scr4.screen.buffer[0][0].fg))
check("SGR 0 resets the rendition (the main-path safety check)",
      scr4.screen.buffer[0][1].fg == "default", repr(scr4.screen.buffer[0][1].fg))


# ════════════════════════════════════════════════════════════
# 3. LNM by default (A2): a bare LF = CR+LF; explicit SM/RM 20 and RIS
# ════════════════════════════════════════════════════════════
print("== LNM default ==")

scr5 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr5.feed(b"ab\ncd")
check("a bare LF = CR+LF: b'ab\\ncd' → [\"ab\", \"cd\"]",
      lines(scr5)[:2] == ["ab", "cd"], repr(lines(scr5)[:2]))

# An explicit LNM disable by the remote program (RM 20): a bare LF is again without CR.
scr6 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr6.feed(b"\x1b[20lab\ncd")
check("after \\x1b[20l: LNM is off (the mode does not contain 20)",
      pyte.modes.LNM not in scr6.screen.mode, str(sorted(scr6.screen.mode)))
check("after \\x1b[20l: a bare LF without CR — cd at offset x=2",
      lines(scr6)[:2] == ["ab", "  cd"], repr(lines(scr6)[:2]))

# An explicit enable (SM 20) returns the xterm behaviour.
scr6.feed(b"\x1b[20h")
check("after \\x1b[20h: LNM is back in the mode", pyte.modes.LNM in scr6.screen.mode,
      str(sorted(scr6.screen.mode)))
scr6.feed(b"ef\ngh")
check("after \\x1b[20h: a bare LF is CR+LF again — \"gh\" at x=0 on the new line",
      lines(scr6)[1:3] == ["  cdef", "gh"], repr(lines(scr6)[1:3]))

# RIS (ESC c — NOT ESC [ c): a full reset — LNM comes back (the subclass reset()).
scr7 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr7.feed(b"\x1bcab\ncd")
check("after RIS (\\x1bc): LNM is restored", pyte.modes.LNM in scr7.screen.mode,
      str(sorted(scr7.screen.mode)))
check("after RIS: a bare LF is CR+LF again → [\"ab\", \"cd\"]",
      lines(scr7)[:2] == ["ab", "cd"], repr(lines(scr7)[:2]))

# v1.2.12 (verified by a run): \\x1b[c — that is CSI DA, not RIS: Screen.reset()
# is not called at all (the screen is NOT cleared). We pin the fact — so a typo
# "ESC [ c" was no longer masked by a false-positive check.
scr8 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr8.feed(b"stale\r\n")
scr8.feed(b"\x1b[c")
check("\\x1b[c (CSI DA) does NOT reset the screen (this is not RIS)",
      "stale" in scr8.screen.display[0], repr(scr8.screen.display[0]))


# ════════════════════════════════════════════════════════════
# 4. Release state + i18n parity (no new keys — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

finish()
