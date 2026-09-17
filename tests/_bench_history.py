# -*- coding: utf-8 -*-
"""v1.2.12 the D1 measurement (the PYTE82_AUDIT.md pack D): the overhead of the HistoryScreen wrappers
on a deep history — the worst case of the auto-return to the live line.

NOT part of the suite (files with the _ prefix are skipped by run_all.py). The protocol (D1):
  * TerminalScreen(120, 32, history_lines=1000); print ~1050 history lines;
  * scroll_up() to the top edge — the user is at the top of the history (the worst case:
    the before_event auto-return spins next_page() up to ~250 times in ONE feed);
  * the measurement of the feed of an htop-like chunk (~19 KB) → ms;
  * the baseline lines: the same chunk on the live line (no history to return to) +
    the plain pyte.Screen without the history;
  * the expected number of next_page ≈ (size − position) / ceil(lines × ratio)
    (~250 on a deep history, ratio=0.1 → a page = 4 lines).

The numbers — into CHANGELOG/ROADMAP ("measured on …, v1.2.12"); the pain threshold ~20–50 ms per
chunk on a deep history — the trigger of v1.2.14 (the batching of the auto-return).

v1.2.14: the batching is released (the override before_event in SshmapHistoryScreen) — the scenario A
must be ≈ B (measured: A = 42.7 ms against B = 42.4 ms, the overhead 0.25 ms). The script
stays the regression monitor: if A is again > 50 ms or A−B is large — check the override.

The htop chunk: pyte/tests/captured/htop.input from the master-checkout F:\\PythonAI\\pyte
(~19 KB); no file — a synthetic htop-like chunk of the same size.

Run: python tests/_bench_history.py   (from the project root)
"""
import math
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from third_party import pyte  # noqa: E402   # v1.3rc1: the fork (MANIFEST.md)
from modules.terminal_screen import TerminalScreen  # noqa: E402

COLUMNS, LINES = 120, 32
HISTORY_LINES = 1000
HISTORY_PRINTED = 1050        # ~1050 lines of history (filling the deque at 1000)
CHUNK_TARGET = 19000          # htop.input — ~19 KB
REPEATS = 5                   # the best of the N measurements

HTOP_INPUT_CANDIDATES = [
    os.path.join(os.path.dirname(ROOT), "pyte", "tests", "captured", "htop.input"),
]


def load_chunk():
    """An htop-like chunk of ~19 KB: a real pyte capture or synthetic data."""
    for path in HTOP_INPUT_CANDIDATES:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            return data, path
    # The synthetic: repeated full-screen htop frames (ESC[2J + the SGR headers).
    header = (b"\x1b[7m\x1b[46m\x1b[30m PID USER PR NI VIRT RES SHR S %CPU %MEM "
              b"TIME+ COMMAND \x1b[0m\r\n")
    body = b""
    pid = 1
    while len(body) < LINES * 55:
        body += (b"%-7d %-8s %3d %3d %6d %6d %5d S %5.1f %5.1f %7s python\r\n"
                 % (pid, b"root", 20, 0, 1048576, 52428 + pid * 137, 26214,
                    float(pid % 9), float(1 + pid % 7), b"0:0%d.%d" % (pid % 10, pid % 9)))
        pid += 1
    frame = b"\x1b[2J\x1b[H" + header + body
    n = max(1, CHUNK_TARGET // len(frame))
    return frame * n, "<synthetic htop-like>"


def to_top(t):
    """scroll_up() to the top edge of the history (a no-op at the edge)."""
    while t.scroll_up():
        pass


def measure(t, chunk, repeats=REPEATS, at_top=True):
    """The best chunk-delivery time (ms); with at_top — the return to the top
    of the history before each measurement (the worst case)."""
    best = None
    for _ in range(repeats):
        if at_top:
            to_top(t)
        t0 = time.perf_counter()
        t.feed(chunk)
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None else min(best, dt)
    return best


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    chunk, chunk_src = load_chunk()

    print("SSHMap bench D1 (v1.2.12): HistoryScreen overhead with a deep history")
    print(f"  machine : {platform.system()} {platform.release()}, "
          f"Python {sys.version.split()[0]}, pyte {getattr(pyte, '__version__', '0.8.2 (installed)')}")
    # The page size — the same arithmetic as in pyte HistoryScreen.next_page:
    # int(math.ceil(lines * ratio)) (ratio=SCROLL_RATIO=0.1).
    page = max(1, int(math.ceil(LINES * 0.1)))
    print(f"  screen  : {COLUMNS}x{LINES}, history_lines={HISTORY_LINES}, ratio=0.1 "
          f"(page = {page} lines)")
    print(f"  chunk   : {len(chunk)} bytes ({chunk_src})")

    # Scenario A: a deep history, the user at the TOP boundary (the worst case).
    t_deep = TerminalScreen(COLUMNS, LINES, history_lines=HISTORY_LINES)
    for i in range(HISTORY_PRINTED):
        t_deep.feed(b"history line %d\r\n" % i)
    to_top(t_deep)
    pos, size = t_deep.scroll_info()
    expected_pages = (size - pos) / float(page)
    ms_deep = measure(t_deep, chunk)
    print(f"  A deep history (user at top): position={pos}/{size}, "
          f"expected next_page ≈ {expected_pages:.0f} → {ms_deep:.2f} ms/chunk")

    # Scenario B: the same chunk on the live line (no auto-return needed).
    t_live = TerminalScreen(COLUMNS, LINES, history_lines=HISTORY_LINES)
    for i in range(HISTORY_PRINTED):
        t_live.feed(b"history line %d\r\n" % i)
    ms_live = measure(t_live, chunk, at_top=False)   # on the live line: the auto-return is not needed
    print(f"  B live line (no auto-return) : {ms_live:.2f} ms/chunk")

    # Scenario C: a bare pyte.Screen without history (the lower bound of the cost).
    plain = pyte.Screen(COLUMNS, LINES)
    plain_stream = pyte.ByteStream(plain)

    def measure_plain():
        best = None
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            plain_stream.feed(chunk)
            dt = (time.perf_counter() - t0) * 1000.0
            best = dt if best is None else min(best, dt)
        return best

    ms_plain = measure_plain()
    print(f"  C plain pyte.Screen (no history): {ms_plain:.2f} ms/chunk")

    overhead = ms_deep - ms_live
    # v1.2.14: the auto-return batching is released — scenario A must be ≈ B (the feed goes
    # in the GUI thread via a queued signal; the D2 pain threshold was > ~20–50 ms per chunk).
    # A deviation A from B or A > 50 ms — a regression of the before_event override.
    verdict = ("BATCHING REGRESSION (A >> B or A > 50 ms) — check the "
               "before_event override in SshmapHistoryScreen (v1.2.14)" if overhead > 5 or ms_deep > 50
               else "OK: A ≈ B — the auto-return batching works (v1.2.14)")
    print(f"  overhead A−B (cost of ~{expected_pages:.0f} next_page): {overhead:.2f} ms; "
          f"A = {ms_deep:.2f} ms/chunk with a deep history → {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
