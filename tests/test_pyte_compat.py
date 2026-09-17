# -*- coding: utf-8 -*-
"""v1.2.11 — Terminal: pyte 0.8.2 compatibility (private SGR + LNM).

(ROADMAP v1.2.11, the PYTE82_AUDIT.md pack A.)

Headless (without Qt): the subclass SshmapHistoryScreen(pyte.HistoryScreen) in
modules/terminal_screen.py — two overrides:
  * the private SGR (CSI ? … m) are ignored: the verified fact #12 — in pyte 0.8.2
    \x1b[?4m (Vim 9+, the upstream issue #202) → the TypeError from feed(), and the tail of the chunk
    AFTER the sequence is lost (the parser is reset; the except Exception: return
    in _on_output swallows the exception). In master the fix is already merged (PR #203, 2025-09-02) —
    the override with the same semantics stays until the pin is raised to pyte 0.8.3;
  * LNM (mode 20) is on by default: a bare LF = CR+LF (the xterm behavior).
    Screen.reset() resets the mode to _DEFAULT_MODE WITHOUT LNM → the explicit restoration
    in __init__ and in reset() (after the RIS ESC c); the explicit \x1b[20h/\x1b[20l (SM/RM 20)
    from the remote program still work.

The note: in PYTE82_AUDIT.md/ROADMAP the sequences are written as \x1b[2h/\x1b[2l —
a typo of the plan; the LNM is mode 20 (pyte.modes.LNM = 20), and pyte 0.8.2 toggles it
exactly by SM/RM 20 (verified by a run: \x1b[2l touches bit 2, not 20).

v1.2.12 (the correction): the RIS is ESC c (\x1bc), NOT ESC [ c (\x1b[c) — the last
pyte 0.8.2 parses it as the CSI DA (report_device_attributes, a no-op): verified by a run,
\x1b[c does not call the Screen.reset() at all. The check "the LNM after the RIS" below is corrected
to the real bytes + the fact about \x1b[c is pinned down (before the check was a false positive).

Run: python tests/test_pyte_compat.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

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
