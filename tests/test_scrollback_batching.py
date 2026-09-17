# -*- coding: utf-8 -*-
"""v1.2.14 — Scrollback: batching of the auto-return to the live line (PYTE82_AUDIT.md batch D2).

The thematic test of the theme of the release (ROADMAP v1.2.14): the pyte.HistoryScreen.before_event
for every event of the SSH thread except prev_page/next_page spun next_page() in a loop —
on a deep history up to ~250 iterations, each O(lines) (the D1 measurement v1.2.12: 68–73 ms/chunk
against ~42 on the live line; the feed goes through the queued signal into the GUI thread). Now — one
bulk operation with the same arithmetic as in next_page (screens.py): O(lines) once.

Headless: the synthetic byte sequences + the real htop chunk (19 KB) into the
TerminalScreen (without Qt, without the network). The functional asserts; the time — only in the
report of the measurement, WITHOUT the hard ms asserts (ROADMAP v1.2.14):

  * the wiring: the override before_event exists and is picked up by the wrapper by name
    (before_event is not in HistoryScreen._wrapped);
  * the basic auto-return (k ≤ lines): the page up → the event → position == size;
  * the deep history + the chunk (the D1 scenario): 120×32, history=1000, ~1050 lines,
    the user at the top edge (position=32/1000) → the feed of the htop chunk — the position
    is back to size, bottom is empty, the grid is equal to the reference without the scroll
    character by character (including the fg/bg and the cursor); the time of the chunk — in the report;
  * the equivalence to the next_page() loop: several geometries (k ≤ lines AND k >> lines) —
    the full state (position, top, bottom, the buffer character by character, the cursor) is identical
    to the stock loop of pyte;
  * prev_page/next_page — a no-op: the manual scroll by the wheel/PgUp-PgDn step by step,
    is not reset by the auto-return;
  * the boundaries: the event on the live line (a no-op), the empty history, history_lines=0,
    two chunks in a row, the enter into the alt from a deep history (the regression v1.2.12).

Run: python tests/test_scrollback_batching.py   (from the project root) or python tests/run_all.py
"""
import math
import sys
import time

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from third_party import pyte  # noqa: E402   # v1.3rc1: the fork (MANIFEST.md)

import modules.terminal_screen as TS  # noqa: E402
from modules.terminal_screen import SshmapHistoryScreen, TerminalScreen  # noqa: E402
from _bench_history import load_chunk  # noqa: E402  (the same htop chunk as in the D1 measurement)


def to_top(t):
    """scroll_up() to the top edge of the history (a no-op at the edge)."""
    guard = 0
    while t.scroll_up() and guard < 10000:
        guard += 1


def line_key(line):
    """The row of pyte → the comparable key: ((col, data, fg, bg), ...) by the ascending col."""
    return tuple((x, line[x].data, line[x].fg, line[x].bg) for x in sorted(line))


def full_state(t):
    """The full state of the HistoryScreen for the comparison of the bulk path with the pyte loop."""
    scr = t.screen
    return {
        "pos": (scr.history.position, scr.history.size),
        "top": [line_key(l) for l in scr.history.top],
        "bottom": [line_key(l) for l in scr.history.bottom],
        "buffer": [line_key(scr.buffer[y]) for y in range(scr.lines)],
        "cursor": (scr.cursor.x, scr.cursor.y, bool(scr.cursor.hidden)),
    }


def grid_key(t):
    """The snapshot of the grid for the "the grid is correct": (the rows with the data/fg/bg, the cursor)."""
    rows, cx, cy, hidden = t.snapshot()
    return ([[ (ch.data, ch.fg, ch.bg) for ch in row ] for row in rows], (cx, cy, hidden))


# ════════════════════════════════════════════════════════════
# 0. Wiring: the override exists and is picked up by the wrapper by name
# ════════════════════════════════════════════════════════════
print("== wiring ==")

check("wiring: SshmapHistoryScreen overrides before_event",
      SshmapHistoryScreen.before_event is not pyte.HistoryScreen.before_event,
      f"{SshmapHistoryScreen.before_event.__qualname__}")
check("wiring: before_event is NOT in HistoryScreen._wrapped (the wrapper calls it by name)",
      "before_event" not in pyte.HistoryScreen._wrapped,
      str(sorted(a for a in pyte.HistoryScreen._wrapped if "event" in a)))

# Functionally: the parser really calls the subclass override on every event.
_t0 = TerminalScreen(columns=40, lines=10)
for i in range(30):
    _t0.feed(b"w-%02d\r\n" % i)
to_top(_t0)
assert _t0.scroll_info()[0] < 1000, "the test scroll-up did not work"
_calls = []
_orig_before = SshmapHistoryScreen.before_event


def _spy(self, event):
    _calls.append(event)
    _orig_before(self, event)


SshmapHistoryScreen.before_event = _spy
try:
    _t0.feed(b"SPY\r\n")
finally:
    SshmapHistoryScreen.before_event = _orig_before
check("wiring: the Stream wrapper calls the subclass before_event by name (the events passed through the spy)",
      "draw" in _calls and len(_calls) > 1, f"events={_calls[:8]}…")
check("wiring: after the event — the auto-return to live (position == size)",
      _t0.scroll_info()[0] == _t0.scroll_info()[1], str(_t0.scroll_info()))


# ════════════════════════════════════════════════════════════
# 1. Basic auto-return (k ≤ lines) — the v1.0RC3 behaviour is preserved
# ════════════════════════════════════════════════════════════
print("== basic auto-return (k <= lines) ==")

t = TerminalScreen(columns=40, lines=32, history_lines=100)
for i in range(50):
    t.feed(b"line-%02d\r\n" % i)
check("basic: scrolled up by a page (position < size)", t.scroll_up() is True and t.at_bottom() is False,
      str(t.scroll_info()))
t.feed(b"SNAP-MARKER\r\n")
check("basic: a new event → the auto-return to live (position == size)",
      t.at_bottom() is True, str(t.scroll_info()))
visible = "\n".join(t.screen.display)
check("basic: the new output is visible on the live line", "SNAP-MARKER" in visible)


# ════════════════════════════════════════════════════════════
# 2. Deep history + a chunk (the D1 scenario): the position at size, the grid is correct
# ════════════════════════════════════════════════════════════
print("== deep history + htop chunk (D1 scenario) ==")

COLUMNS, LINES, HIST = 120, 32, 1000
chunk, chunk_src = load_chunk()


def build_deep(n_lines=1050):
    t = TerminalScreen(COLUMNS, LINES, history_lines=HIST)
    for i in range(n_lines):
        t.feed(b"history line %d\r\n" % i)
    return t


# The measurement (the time — only in the report, no ms asserts).
t_timed = build_deep()
to_top(t_timed)
pos, size = t_timed.scroll_info()
page = max(1, int(math.ceil(LINES * TS.SCROLL_RATIO)))
expected_pages = (size - pos) / float(page)
check("the deep history: the user is at the top edge (position == lines)",
      pos == LINES and size == HIST, f"({pos}, {size})")

REPEATS = 3
best_ms = None
for _ in range(REPEATS):
    to_top(t_timed)                     # the worst case before each measurement
    t0 = time.perf_counter()
    t_timed.feed(chunk)
    dt = (time.perf_counter() - t0) * 1000.0
    best_ms = dt if best_ms is None else min(best_ms, dt)
print(f"  the measurement report: the htop chunk {len(chunk)} B ({chunk_src}) at the top edge "
      f"(position={pos}/{size}, expected next_page ≈ {expected_pages:.0f}) → "
      f"{best_ms:.2f} ms/chunk (best of {REPEATS}; without the batching it was 68–73 ms — the D1 measurement v1.2.12)")

# A functional comparison: a fresh pair of screens, the chunk exactly ONCE.
t_deep = build_deep()
t_ref = build_deep()                    # the reference: WITHOUT scrolling — a chunk on the live line
to_top(t_deep)
t_deep.feed(chunk)
t_ref.feed(chunk)

check("the deep history + the chunk: the position is back to size (the live line)",
      t_deep.at_bottom() is True, str(t_deep.scroll_info()))
check("the deep history + the chunk: the bottom is empty (all the lines are returned to the top/buffer)",
      len(t_deep.screen.history.bottom) == 0, f"bottom_len={len(t_deep.screen.history.bottom)}")
check("the deep history + the chunk: the top is fully restored (== capacity)",
      len(t_deep.screen.history.top) == HIST, f"top_len={len(t_deep.screen.history.top)}")
check("the deep history + the chunk: the grid is correct — the full state (pos/top/bottom/buffer/cursor) "
      "is identical to the reference without the scroll",
      full_state(t_deep) == full_state(t_ref))


# ════════════════════════════════════════════════════════════
# 3. Equivalence with pyte's standard next_page() loop (full state)
# ════════════════════════════════════════════════════════════
print("== equivalence with pyte next_page() loop ==")


def twin_case(cols, lines, hist, printed, ups, label):
    """Two identical screens: A — the bulk auto-return by the event; B — the stock loop
    of next_page() to the live. The full state after the same chunk must match."""
    ta = TerminalScreen(columns=cols, lines=lines, history_lines=hist)
    tb = TerminalScreen(columns=cols, lines=lines, history_lines=hist)
    for i in range(printed):
        payload = b"row-%04d\r\n" % i
        ta.feed(payload)
        tb.feed(payload)
    for _ in range(ups):
        if not ta.scroll_up():
            break
    # A: the bulk path — one event triggers the auto-return, then the chunk is processed
    ta.feed(b"END-MARK\r\n")
    # B: the reference — pyte's standard loop (next_page via the wrapper; before_event is a no-op for it)
    while tb.screen.history.position < tb.screen.history.size:
        tb.screen.next_page()
    tb.feed(b"END-MARK\r\n")
    ok = full_state(ta) == full_state(tb) and ta.at_bottom() is True
    check(f"the equivalence ({label}): the bulk return == the next_page() loop (pos/top/bottom/buffer/cursor)",
          ok, f"A={ta.scroll_info()} B={tb.scroll_info()}")
    return ok


twin_case(40, 32, 100, 50, 1, "k=4 <= lines=32")
twin_case(40, 32, 100, 80, 5, "k=20 <= lines=32")
twin_case(20, 5, 50, 200, 9999, "k=45 >> lines=5 (a small grid)")
twin_case(120, 32, 1000, 1050, 9999, "D1: k=968 >> lines=32 (the worst case)")
twin_case(80, 24, 300, 400, 77, "k=77 > lines=24 (a partial scroll)")


# ════════════════════════════════════════════════════════════
# 4. prev_page/next_page — no-op: manual scrolling is not reset by the auto-return
# ════════════════════════════════════════════════════════════
print("== manual paging is not hijacked ==")

tp = TerminalScreen(columns=40, lines=10, history_lines=50)
for i in range(30):
    tp.feed(b"n-%02d\r\n" % i)
tp.scroll_up()
tp.scroll_up()                        # the page = ceil(10*0.1) = 1 line → position 48
check("the manual scroll: scrolled up by 2 pages (position == size − 2)",
      tp.scroll_info() == (48, 50), str(tp.scroll_info()))
tp.screen.next_page()                 # the wheel down — ONE page, not the whole way to live
check("the manual scroll: next_page — step by step (one page, NOT a jump to live)",
      tp.scroll_info()[0] == 49, str(tp.scroll_info()))
tp.feed(b"Y\r\n")                     # only the event returns the rest of the path
check("the manual scroll: the next event brings it to live", tp.at_bottom() is True,
      str(tp.scroll_info()))


# ════════════════════════════════════════════════════════════
# 5. Boundaries and regressions
# ════════════════════════════════════════════════════════════
print("== edges & regressions ==")

# An event on the live line with a full history — a no-op of the bulk path, nothing breaks.
te = TerminalScreen(columns=40, lines=10, history_lines=20)
for i in range(60):
    te.feed(b"e-%02d\r\n" % i)
g_before = grid_key(te)
te.feed(b"LIVE-EVENT\r\n")
check("the live line + a full history: the event does not change the position (== size)",
      te.at_bottom() is True, str(te.scroll_info()))
check("the live line + a full history: the output is visible, the grid is alive",
      "LIVE-EVENT" in "\n".join(te.screen.display))

# An empty history — the event without errors.
tf = TerminalScreen(columns=20, lines=5)
tf.feed(b"hello\r\n")
check("an empty history: the event without errors, position == size (the 0-line scrollback is not broken)",
      tf.at_bottom() is True, str(tf.scroll_info()))

# history_lines=0 — the user disabled the scrollback (deque maxlen=0).
tg = TerminalScreen(columns=20, lines=5, history_lines=0)
for i in range(10):
    tg.feed(b"z-%d\r\n" % i)
check("history_lines=0: the feed works, position == size == 0",
      tg.scroll_info() == (0, 0), str(tg.scroll_info()))

# Two chunks in a row from a deep history — the state does not drift.
th = TerminalScreen(columns=80, lines=16, history_lines=200)
trh = TerminalScreen(columns=80, lines=16, history_lines=200)
for i in range(150):
    p = b"m-%03d\r\n" % i
    th.feed(p)
    trh.feed(p)
trh.feed(chunk[:len(chunk) // 2])       # the reference — without scrolling, both half-chunks in a row
to_top(th)
th.feed(chunk[:len(chunk) // 2])
check("two chunks in a row from the deep history: the position is at live after the first",
      th.at_bottom() is True, str(th.scroll_info()))
to_top(th)
th.feed(chunk[len(chunk) // 2:])
trh.feed(chunk[len(chunk) // 2:])
check("two chunks in a row from the deep history: the position is at live after the second",
      th.at_bottom() is True, str(th.scroll_info()))
check("two chunks in a row: the grid == the reference without the scroll (no state drift)",
      grid_key(th) == grid_key(trh))

# Entering alt from a deep history (the v1.2.12 regression via the bulk path).
ta = TerminalScreen(columns=80, lines=10, history_lines=200)
for i in range(50):
    ta.feed(b"HIST %d\r\n" % i)
to_top(ta)
ta.feed(b"\x1b[?1049h\x1b[2J\x1b[Halt-frame\r\n")
check("entering alt from the deep history: the bulk auto-return worked (position == size)",
      ta.scroll_info()[0] == 200, str(ta.scroll_info()))
check("entering alt from the deep history: alt is active, the grid = the TUI",
      ta.in_alt_screen() is True and "alt-frame" in "\n".join(ta.screen.display))
ta.feed(b"\x1b[?1049l")
check("leaving alt: the main screen is in place (HIST is visible)",
      ta.in_alt_screen() is False and "HIST" in "\n".join(ta.screen.display))

# dirty after the bulk return — all the lines (as in next_page).
td = TerminalScreen(columns=40, lines=10, history_lines=50)
for i in range(30):
    td.feed(b"d-%02d\r\n" % i)
to_top(td)
td.feed(b"Z\r\n")
check("the dirty after the bulk return = all the lines",
      td.screen.dirty == set(range(10)), f"dirty={sorted(td.screen.dirty)}")


# ════════════════════════════════════════════════════════════
# 6. Release state + i18n parity (no new keys — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_release_state(ROOT)
check_i18n_parity(load_i18n_langs(ROOT))

finish()
