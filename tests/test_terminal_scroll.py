# -*- coding: utf-8 -*-
"""v1.0RC3 — PTY resize + scrollback + dirty rendering (ROADMAP v1.0RC3).

  * The scrollback on the ready-made pyte.HistoryScreen (TERMINAL.md §5.4, fact #7; the input
    ONLY with \\r\\n — the convention since v1.0RC3; fact #10 was closed in v1.2.11: LNM is on
    by default, a bare \n = CR+LF): the history grows, prev/next page (a page =
    ceil(lines * ratio)), the auto-return to the live line on the new output (built
    into pyte's before_event), the boundaries (a no-op at the top/bottom), the depth limit;
  * The PTY resize — the guard on the grid change + the ~150 ms debounce (TERMINAL.md §5.5,
    ROADMAP task 6): the fake channel counts the resize_pty calls — 10 resize
    events on one grid → exactly 1 PTY call; the initial invoke_shell stays
    120×32, the first resizeEvent synchronizes with the window; a series of fast grid
    changes coalesces into a SINGLE call with the latest sizes;
  * The keyboard: Ctrl+Shift+PageUp/PageDown → the scrollback (the interception BEFORE the bare
    PageUp/PageDown — the fall-through trap from the ROADMAP), the bare PgUp/PgDn
    remain the forward to the shell (\\x1b[5~/\\x1b[6~ — the semantics of v1.0RC2, the paging
    of less/man); Shift+PgUp without Ctrl and Ctrl+Alt+Shift+PgUp (the AltGr guard) do
    not scroll;
  * The mouse wheel: up → prev_page, down → next_page, a no-op at the boundaries;
    it works even with terminal_thread=None (a local operation);
  * The dirty render (ROADMAP task 8): the 33 ms timer removed — _on_output →
    widget.update() directly (E2E through the window with a fake thread);
  * The cursor blink: its own QTimer in TerminalWidget (the start in showEvent, the stop
    in hideEvent), the phase toggle changes the render of the block cursor;
  * The "Close the terminal" button removed (v1.0RC3): a QPushButton in the window — only on the SFTP tab (v1.1.3) and in the command library panel (v1.3); close_terminal() is kept (the MainWindow's cleanup path).

Run:  python tests/test_terminal_scroll.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QTimer, QSize, QPointF, QPoint, QEventLoop
from PySide6.QtGui import QKeyEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton

app = QApplication(sys.argv)

from third_party import pyte          # v1.3rc1: the fork (MANIFEST.md)

from modules.terminal_screen import (SCROLL_MODE_DEFAULT, SCROLL_MODE_LIVE, SCROLL_MODE_PIN,
                                     TerminalScreen, resolve_scroll_mode)
from modules.terminal_widget import TerminalWidget
import modules.terminal_screen as TS


# ════════════════════════════════════════════════════════════
# 1. Scrollback: pyte.HistoryScreen (headless, no GUI; input only \\r\\n)
# ════════════════════════════════════════════════════════════
print("== HistoryScreen scrollback (headless) ==")

scr = TerminalScreen(columns=40, lines=32, history_lines=100)
check("TerminalScreen creates a pyte.HistoryScreen",
      isinstance(scr.screen, pyte.HistoryScreen), type(scr.screen).__name__)

for i in range(50):
    scr.feed(f"line-{i:02d}\r\n".encode())   # the convention: only \\r\\n (fact №10 was closed in v1.2.11)

pos, size = scr.scroll_info()
check("after the output: on the live line (position == size)", pos == size, f"({pos}, {size})")
check("the history grows (top is not empty)", len(scr.screen.history.top) > 0,
      f"top_len={len(scr.screen.history.top)}")
check("at_bottom() — True on the live line", scr.at_bottom() is True)

top_before = "".join(scr.screen.buffer[0][x].data for x in range(40))
moved = scr.scroll_up()
pos2, _ = scr.scroll_info()
top_after = "".join(scr.screen.buffer[0][x].data for x in range(40))
check("scroll_up() → True, the position moved up", moved is True and pos2 < pos,
      f"({pos} -> {pos2})")
check("a page = ceil(lines * ratio) = 4 lines (32 × 0.1)", pos - pos2 == 4,
      f"delta={pos - pos2}")
check("the visible top row changed (the history is substituted)", top_before != top_after,
      f"before={top_before!r} after={top_after!r}")
check("at_bottom() — False after scrolling up", scr.at_bottom() is False)

# The auto-return to the live line on new output (built into pyte before_event)
scr.feed(b"SNAP-MARKER\r\n")
pos3, _ = scr.scroll_info()
visible = "\n".join("".join(scr.screen.buffer[y][x].data for x in range(40))
                    for y in range(32))
check("new output → the auto-return to live (position == size)", pos3 == size,
      f"({pos3}, {size})")
check("the new output is visible on the screen", "SNAP-MARKER" in visible)

# The boundary: the top of the history — prev_page is a no-op
guard = 0
while scr.scroll_up() and guard < 100:
    guard += 1
top_pos, _ = scr.scroll_info()
check("the top of the history: a further scroll_up() → False (a no-op)",
      scr.scroll_up() is False and scr.scroll_info()[0] == top_pos)

# The boundary: the live line — next_page is a no-op
while scr.scroll_down():
    pass
check("the live line: at_bottom() is True again", scr.at_bottom() is True)
check("the live line: a further scroll_down() → False (a no-op)", scr.scroll_down() is False)

# The history depth limit (deque maxlen = history_lines)
scr_small = TerminalScreen(columns=20, lines=5, history_lines=10)
for i in range(60):
    scr_small.feed(f"s-{i:03d}\r\n".encode())
check("the history depth is bounded (top <= history_lines)",
      len(scr_small.screen.history.top) <= 10,
      f"top_len={len(scr_small.screen.history.top)}")


# ════════════════════════════════════════════════════════════
# 2. PTY resize: a guard on the grid + ~150 ms debounce (an offscreen window)
# ════════════════════════════════════════════════════════════
print("== resize PTY guard + debounce (offscreen) ==")


def spin(ms):
    """Spin the Qt event loop for ~ms (for the debounce timers)."""
    loop = QEventLoop()
    tmr = QTimer()
    tmr.setSingleShot(True)
    tmr.timeout.connect(loop.quit)
    tmr.start(ms)
    loop.exec()


class FakeChannel:
    """The fake paramiko channel counting the calls of resize_pty (ROADMAP v1.0RC3)."""

    def __init__(self):
        self.closed = False
        self.calls = []   # [(width, height), ...]

    def resize_pty(self, width, height):
        self.calls.append((width, height))


import modules.ssh_terminal as ST
from models.server import ServerData

_orig_thread_cls = ST.SSHTerminalThread


class _FakeTerm(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        pass  # without network


ST.SSHTerminalThread = _FakeTerm
win = None
chan = FakeChannel()
try:
    win = ST.SSHTerminalWindow(ServerData(id="rc3w", alias="T", host="127.0.0.1", user="u"), None)
    win.terminal_thread.channel = chan

    check("the initial grid == invoke_shell 120×32 (before the resizeEvent)",
          (win.tscreen.columns, win.tscreen.lines) == (120, 32),
          f"got=({win.tscreen.columns}, {win.tscreen.lines})")
    check("the guard state is initialized for invoke_shell",
          (win._last_cols, win._last_rows) == (120, 32))

    # The first resizeEvent (show → the real window geometry) synchronizes the grid.
    # The recompute is deferred with singleShot(0) — handled inside processEvents: the layout is already
    # it held, the canvas's transitive size is not involved.
    win.show()
    app.processEvents()
    grid1 = (win.tscreen.columns, win.tscreen.lines)
    check("the first resizeEvent synchronized the grid with the window",
          grid1 != (120, 32) and grid1 == (win._last_cols, win._last_rows),
          f"grid={grid1} last=({win._last_cols}, {win._last_rows})")

    wait_until(lambda: len(chan.calls) >= 1, timeout_ms=2000)
    check("the debounce expired → exactly 1 resize_pty call with the grid sizes",
          chan.calls == [grid1], f"calls={chan.calls}")

    # 10 resize events with ONE and the same grid → guard: neither pyte.resize nor the PTY signal
    sz = QSize(win.width(), win.height())
    for _ in range(10):
        win.resizeEvent(QResizeEvent(sz, sz))
    check("10 events with one grid: right away — no new calls", len(chan.calls) == 1,
          f"calls={chan.calls}")
    spin(400)   # we process the deferred singleShot(0) and the debounce — there are still no new calls
    check("10 events with one grid → exactly 1 PTY call (in total)", len(chan.calls) == 1,
          f"calls={chan.calls}")
    check("the grid did not change after the 10 identical events",
          (win.tscreen.columns, win.tscreen.lines) == grid1)

    # The debounce coalesces a series of fast grid changes into ONE call with the last sizes
    win.resize(600, 400)
    app.processEvents()
    grid2 = (win.tscreen.columns, win.tscreen.lines)
    check("the first fast change: the pyte grid updated right away", grid2 != grid1,
          f"grid={grid2}")
    win.resize(700, 500)
    app.processEvents()
    grid3 = (win.tscreen.columns, win.tscreen.lines)
    check("the second fast change: the pyte grid updated again", grid3 != grid2,
          f"grid={grid3}")
    wait_until(lambda: len(chan.calls) >= 2, timeout_ms=2000)
    spin(400)
    check("a series of fast changes → one PTY call with the LATEST sizes",
          len(chan.calls) == 2 and chan.calls[-1] == grid3, f"calls={chan.calls}")

    # A manual pending with a live channel — the debounce consumes it (one call)
    win._pending_pty = grid3
    win._pty_timer.start()
    spin(400)
    check("the pending is consumed by the debounce (the channel is alive)", win._pending_pty is None,
          f"pending={win._pending_pty}")

    # A dead channel — resize_pty is not sent (the channel.closed guard)
    n_before = len(chan.calls)
    chan.closed = True
    win._last_cols, win._last_rows = 1, 1   # to force a "grid change"
    win.resizeEvent(QResizeEvent(sz, sz))
    spin(400)
    check("a closed channel → resize_pty is not called", len(chan.calls) == n_before,
          f"calls={chan.calls}")
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 2b. v1.5.7: the grid computed BEFORE the connection is NOT lost
# ════════════════════════════════════════════════════════════
# The layout runs when the window appears — long before paramiko authenticates — so the
# debounced resize_pty of that pass used to be refused by the `channel is None` guard while
# `_last_cols/_last_rows` were already updated: no further Resize event followed and the PTY
# kept invoke_shell's 120x32 for the whole life of the session (every TUI then drew a 120x32
# screen inside a canvas of another size). The request now WAITS for the channel.
print("== the initial PTY grid survives the connect (v1.5.7) ==")

win2 = None
chan2 = FakeChannel()
try:
    ST.SSHTerminalThread = _FakeTerm
    win2 = ST.SSHTerminalWindow(ServerData(id="rc3x", alias="B", host="127.0.0.1", user="u"), None)
    page2 = win2.page
    check("a fresh session has no channel yet (paramiko is still connecting)",
          page2._pty_channel() is None)

    win2.show()
    app.processEvents()
    grid2 = (win2.tscreen.columns, win2.tscreen.lines)
    spin(400)   # the debounce expires with NO channel — the grid must survive it
    check("the debounce of a NOT-connected session keeps the grid PENDING (it is not dropped)",
          page2._pending_pty == grid2 and chan2.calls == [],
          f"pending={page2._pending_pty} calls={chan2.calls}")

    win2.terminal_thread.channel = chan2   # the transport comes up
    win2.terminal_thread.connected_signal.emit()   # the REAL trigger (the page's slot)
    app.processEvents()
    check("connected_signal hands the pending grid to the PTY (the initial SIGWINCH)",
          chan2.calls == [grid2] and page2._pending_pty is None,
          f"calls={chan2.calls} pending={page2._pending_pty}")
    page2._flush_pty_grid()
    check("a repeated flush is a no-op — the pending value was consumed",
          chan2.calls == [grid2], f"calls={chan2.calls}")

    # The not-laid-out guard: _visible_grid() clamps to 2x1 and that must never reach the PTY.
    n_before2 = len(chan2.calls)
    keep = win2.tscreen.columns, win2.tscreen.lines
    page2.widget.resize(0, 0)
    page2._pending_pty = None
    page2._sync_grid()
    check("_sync_grid ignores a canvas that is not laid out (never a 2x1 PTY grid)",
          (win2.tscreen.columns, win2.tscreen.lines) == keep and page2._pending_pty is None
          and len(chan2.calls) == n_before2,
          f"grid={(win2.tscreen.columns, win2.tscreen.lines)} pending={page2._pending_pty}")
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win2 is not None:
        try:
            win2.close()
            app.processEvents()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 3. Keyboard: Ctrl+Shift+PgUp/PgDn → scrollback, bare ones — to the shell
# ════════════════════════════════════════════════════════════
print("== keyboard: Ctrl+Shift scroll vs bare forward ==")

from _fakes import FakeWidgetThread as FakeThread
FakeThread.sent = []
sent = FakeThread.sent   # the same list — for the checks below


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier

scrk = TerminalScreen(columns=40, lines=10)
for i in range(40):
    scrk.feed(f"line-{i:02d}\r\n".encode())
wk = TerminalWidget(scrk, FakeThread())

# Ctrl+Shift+PageUp → scrollback (intercepted BEFORE bare PageUp/PageDown)
sent.clear()
press_key(wk, Qt.Key.Key_PageUp, mod=CTRL | SHIFT)
check("Ctrl+Shift+PgUp: nothing goes to the shell", sent == [], f"sent={sent!r}")
check("Ctrl+Shift+PgUp: the scrollback goes up (not at_bottom)", scrk.at_bottom() is False)

# Ctrl+Shift+PageDown → back to live
sent.clear()
press_key(wk, Qt.Key.Key_PageDown, mod=CTRL | SHIFT)
check("Ctrl+Shift+PgDn: nothing goes to the shell", sent == [], f"sent={sent!r}")
check("Ctrl+Shift+PgDn: the return to the live line", scrk.at_bottom() is True)

# Bare PageUp/PageDown — a forward to the shell (the v1.0RC2 semantics: less/man paging)
sent.clear()
press_key(wk, Qt.Key.Key_PageUp)
check("a bare PgUp → b'\\x1b[5~' (to the shell)", sent == [b"\x1b[5~"], f"sent={sent!r}")
sent.clear()
press_key(wk, Qt.Key.Key_PageDown)
check("a bare PgDn → b'\\x1b[6~' (to the shell)", sent == [b"\x1b[6~"], f"sent={sent!r}")

# Shift+PgUp WITHOUT Ctrl — also a forward (only Ctrl+Shift is intercepted)
sent.clear()
press_key(wk, Qt.Key.Key_PageUp, mod=SHIFT)
check("Shift+PgUp without Ctrl → b'\\x1b[5~' (the forward)", sent == [b"\x1b[5~"], f"sent={sent!r}")

# The AltGr guard: Ctrl+Alt+Shift+PgUp — nothing is sent and nothing scrolls
pos_before, _ = scrk.scroll_info()
sent.clear()
press_key(wk, Qt.Key.Key_PageUp, mod=CTRL | ALT | SHIFT)
check("Ctrl+Alt+Shift+PgUp (the AltGr guard): nothing is sent", sent == [], f"sent={sent!r}")
check("Ctrl+Alt+Shift+PgUp: the scrollback is untouched", scrk.scroll_info()[0] == pos_before)


# ════════════════════════════════════════════════════════════
# 4. The mouse wheel — the scrollback (including terminal_thread=None)
# ════════════════════════════════════════════════════════════
print("== mouse wheel scrollback ==")


def wheel(w, dy):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)


scrw = TerminalScreen(columns=40, lines=10)
for i in range(40):
    scrw.feed(f"line-{i:02d}\r\n".encode())
ww = TerminalWidget(scrw, FakeThread())

top_before = "".join(scrw.screen.buffer[0][x].data for x in range(40))
wheel(ww, 120)    # up → prev_page
check("the wheel up: the scrollback (not at_bottom)", scrw.at_bottom() is False)
top_after = "".join(scrw.screen.buffer[0][x].data for x in range(40))
check("the wheel up: the visible row changed", top_before != top_after)

wheel(ww, -120)   # down → next_page (to live)
check("the wheel down: the return to the live line", scrw.at_bottom() is True)

pos_b, _ = scrw.scroll_info()
top_now = "".join(scrw.screen.buffer[0][x].data for x in range(40))
wheel(ww, -120)   # on live — a no-op
check("the wheel down at live: a no-op (the position and the screen are unchanged)",
      scrw.scroll_info() == (pos_b, pos_b) and
      "".join(scrw.screen.buffer[0][x].data for x in range(40)) == top_now)

# terminal_thread=None — the scrollback is local, it works without a channel
scrn = TerminalScreen(columns=20, lines=5)
for i in range(30):
    scrn.feed(f"n-{i:02d}\r\n".encode())
wn = TerminalWidget(scrn, None)
wheel(wn, 120)
check("the wheel with terminal_thread=None: the scrollback works", scrn.at_bottom() is False)


# ════════════════════════════════════════════════════════════
# 5. Dirty rendering: the 33 ms timer is removed, _on_output → update() directly
# ════════════════════════════════════════════════════════════
print("== dirty render (no 33ms timer) ==")


class _FakeTermOut(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        self.output_signal.emit(b"rc3-live\r\n")


ST.SSHTerminalThread = _FakeTermOut
win2 = None
try:
    win2 = ST.SSHTerminalWindow(ServerData(id="rc3w2", alias="T2", host="127.0.0.1", user="u"), None)
    check("the 33 ms render timer is removed (no _render_timer/_dirty)",
          not hasattr(win2, "_render_timer") and not hasattr(win2, "_dirty"))
    win2.show()   # the shown window is really repainted (paintEvent)
    app.processEvents()
    wait_until(lambda: "rc3-live" in win2.widget.visible_text(), timeout_ms=1500)
    check("the output rendered without the timer (E2E: the queued signal → _on_output)",
          "rc3-live" in win2.widget.visible_text())
    # the paint hook: last_paint_stats["rows"] > 0 ⇔ paintEvent ran (in _paint)
    check("the canvas was repainted (paintEvent ran — last_paint_stats.rows > 0)",
          win2.widget.last_paint_stats["rows"] > 0,
          f"stats={win2.widget.last_paint_stats}")

    # Integration: the window screen — a HistoryScreen with the scroll API; the close button is removed
    check("the window creates a TerminalScreen on pyte.HistoryScreen",
          isinstance(win2.tscreen.screen, pyte.HistoryScreen))
    check("the scroll API on the window's screen", all(
        hasattr(win2.tscreen, m) for m in ("scroll_up", "scroll_down", "at_bottom", "scroll_info")))
    # v1.0RC3: the "Close terminal" button is removed; v1.1.3: buttons appeared in the window —
    # on the SFTP tab; v1.3: + the command library panel (Add/Edit/Delete);
    # v1.3.3.5: + the "Split Terminal" button in the corner of the session tab bar.
    # The terminal CANVAS itself still contains no QPushButton.
    _stray = [b for b in win2.findChildren(QPushButton)
              if not (win2.sftp_tab.isAncestorOf(b) or win2.cmdlib_panel.isAncestorOf(b))
              and b is not win2.btn_split]
    check("the 'Close terminal' button is removed: a QPushButton only on the SFTP tab, "
          "the cmdlib panel and the split corner",
          not _stray and not win2.widget.findChildren(QPushButton),
          f"stray buttons: {len(_stray)}")
    check("close_terminal() is kept (the MainWindow cleanup path)",
          callable(getattr(win2, "close_terminal", None)))
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win2 is not None:
        try:
            win2.close()
            app.processEvents()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 6. The cursor blink: its own QTimer (start on showEvent / stop on hideEvent)
# ════════════════════════════════════════════════════════════
print("== cursor blink timer ==")


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


scr3 = TerminalScreen(columns=20, lines=5)
scr3.feed(b"X")   # the cursor — on the empty cell (0,1)
# v1.6.2: this section asserts the PHASE render of the historical BLOCK (the whole cell in
# CURSOR_COLOR), so the shape is requested explicitly — the shipped default is the thin bar.
wb = TerminalWidget(scr3, FakeThread(), cursor_style="block")
cw, chh = wb.cell_size
wb.resize(cw * 20, chh * 5)

check("the blink is a QTimer with BLINK_INTERVAL_MS",
      isinstance(wb._blink_timer, QTimer) and wb._blink_timer.interval() == TerminalWidget.BLINK_INTERVAL_MS,
      f"interval={getattr(wb._blink_timer, 'interval', lambda: None)()}")
check("before show(): the timer is not active", not wb._blink_timer.isActive())

wb.show()
app.processEvents()
check("showEvent → the blink timer is active", wb._blink_timer.isActive())

# A real phase switching by the timer (not manually)
wait_until(lambda: not wb._cursor_visible, timeout_ms=1500)
check("the timer really toggles the cursor phase", wb._cursor_visible is False)

# The phase render: the visible cursor — the CURSOR_COLOR block; the invisible phase — the background
cx_, cy_ = cw + cw // 2, chh // 2   # the cell (row=0, col=1) — the cursor position
wb._cursor_visible = True
wb.update()
app.processEvents()
px_on = pixel(wb.grab().toImage(), cx_, cy_)
wb._cursor_visible = False
wb.update()
app.processEvents()
px_off = pixel(wb.grab().toImage(), cx_, cy_)
check("the visible phase: the cursor block CURSOR_COLOR #e2e8f0", px_on == (0xE2, 0xE8, 0xF0),
      f"px={px_on}")
check("the invisible phase: the cursor is not drawn (the background ≠ the cursor color)",
      px_off != px_on and px_off == (0x0F, 0x17, 0x2A), f"px={px_off}")

wb.hide()
app.processEvents()
check("hideEvent → the blink timer is stopped", not wb._blink_timer.isActive())
wb.show()
app.processEvents()
check("a repeated show → the timer is active again", wb._blink_timer.isActive())
wb.hide()
app.processEvents()


# ════════════════════════════════════════════════════════════
# 7. v1.6.4 (ROADMAP task 5): the PINNED scrollback — terminal_scroll = "live" | "pin"
# ════════════════════════════════════════════════════════════
# The opt-in mode where a chunk of output does NOT yank the view: the viewport keeps the LINES
# it shows, which is what a real terminal does. The DEFAULT ("live") is the behaviour every
# earlier release had, and the regression below asserts exactly that.
print("== the pinned scrollback (terminal_scroll) ==")


def lines_of(scr, count=None):
    """The visible grid as text (the lines the user is looking at)."""
    n = scr.lines if count is None else count
    return ["".join(scr.screen.buffer[y][x].data for x in range(scr.columns)).rstrip()
            for y in range(n)]


class CountingHistory(TS.SshmapHistoryScreen):
    """The shipped screen + a counter of the PYTEs PAGE operations (prev_page/next_page).

    The D2 batching exists because those calls used to be spun in a loop (one per page); the
    pinned restore must not reintroduce them, so the topical test counts THEM — never
    milliseconds (the ROADMAP acceptance says so explicitly).
    """
    page_ops = 0

    def prev_page(self):
        type(self).page_ops += 1
        super().prev_page()

    def next_page(self):
        type(self).page_ops += 1
        super().next_page()


_screen_cls = TS.SshmapHistoryScreen
TS.SshmapHistoryScreen = CountingHistory
try:
    check("v1.6.4: the mode validator — 'live' | 'pin' (strip+lower) and ANYTHING else → 'live'",
          resolve_scroll_mode(" live ") == SCROLL_MODE_LIVE
          and resolve_scroll_mode(" PIN ") == SCROLL_MODE_PIN
          and [resolve_scroll_mode(v) for v in ("garbage", "", None, 3, True, "pin!")]
          == [SCROLL_MODE_DEFAULT] * 6
          and SCROLL_MODE_DEFAULT == SCROLL_MODE_LIVE,
          str([resolve_scroll_mode(v) for v in ("live", "pin", "x", None)]))

    # 7a. the DEFAULT mode: the shipped yank is UNCHANGED (the regression the pin is opt-in for)
    _live = TerminalScreen(columns=20, lines=10, history_lines=200)
    for i in range(30):
        _live.feed(("line %02d\r\n" % i).encode())
    _live.scroll_up()
    _live_view = lines_of(_live)
    _live.feed(b"NEW\r\n")
    check("v1.6.4: the DEFAULT 'live' still yanks the view to the new output (the shipped rule)",
          lines_of(_live) != _live_view and _live.at_bottom() is True
          and "NEW" in "\n".join(lines_of(_live)),
          f"{_live_view[:1]} -> {lines_of(_live)[:2]}")

    # the config key: absent or foreign → "live"
    from _common import clear_cfg, merge_cfg
    from modules.ssh_terminal import load_terminal_settings
    clear_cfg()
    check("v1.6.4: no `terminal_scroll` key → 'live' (the declared default is the shipped one)",
          load_terminal_settings()["scroll"] == SCROLL_MODE_LIVE,
          str(load_terminal_settings()["scroll"]))
    merge_cfg({"terminal_scroll": "garbage"})
    check("v1.6.4: a corrupt/foreign `terminal_scroll` → 'live' (never an error)",
          load_terminal_settings()["scroll"] == SCROLL_MODE_LIVE,
          str(load_terminal_settings()["scroll"]))
    merge_cfg({"terminal_scroll": " Pin "})
    check("v1.6.4: ' Pin ' is read as the opt-in mode (the terminal_wheel validation rule)",
          load_terminal_settings()["scroll"] == SCROLL_MODE_PIN,
          str(load_terminal_settings()["scroll"]))
    clear_cfg()

    # 7b. the PIN: the same lines stay, at ANY depth, in a BOUNDED number of page operations
    def pinned_case(rows, history, up_pages, chunk):
        scr = TerminalScreen(columns=20, lines=rows, history_lines=history,
                             scroll_mode=SCROLL_MODE_PIN)
        for i in range(int(history * 0.6)):
            scr.feed(("d%04d\r\n" % i).encode())
        for _ in range(up_pages):
            scr.scroll_up()
        before = lines_of(scr)
        offset = len(scr.screen.history.top)
        CountingHistory.page_ops = 0
        scr.feed(chunk)
        return scr, before, offset, CountingHistory.page_ops

    _pin, _before, _off, _ops_shallow = pinned_case(10, 200, 2, b"CHUNK-A\r\n")
    check("v1.6.4: under 'pin' the SAME lines stay on the screen across a chunk",
          lines_of(_pin) == _before, f"{_before} -> {lines_of(_pin)}")
    check("v1.6.4: ... and the viewport stays OFF the live line (the chunk did not yank it back)",
          _pin.at_bottom() is False and _pin.pinned() is True
          and len(_pin.screen.history.top) == _off,
          f"bottom={_pin.at_bottom()} top={len(_pin.screen.history.top)} off={_off}")

    _deep, _deep_before, _deep_off, _ops_deep = pinned_case(32, 1000, 40, b"CHUNK-B\r\n")
    check("v1.6.4: ... at a DEEP offset too (600 lines of output, 40 page-ups back)",
          lines_of(_deep) == _deep_before, str(lines_of(_deep)[:2]))
    check("v1.6.4: the PAGE OPERATIONS of a chunk are bounded by a constant, not by the depth",
          _ops_shallow <= 2 and _ops_deep <= 2 and _ops_shallow == _ops_deep,
          f"shallow={_ops_shallow} deep={_ops_deep}")

    # the pin's arithmetic equals the live one: the same input yields the same DOCUMENT
    def document(scr):
        s = scr.screen
        rows = ["".join(s.history.top[i][x].data for x in range(s.columns)).rstrip()
                for i in range(len(s.history.top))]
        rows += lines_of(scr)
        rows += ["".join(s.history.bottom[i][x].data for x in range(s.columns)).rstrip()
                 for i in range(len(s.history.bottom))]
        return rows

    _ref = TerminalScreen(columns=20, lines=10, history_lines=200)
    for i in range(120):
        _ref.feed(("d%04d\r\n" % i).encode())
    _ref.feed(b"CHUNK-A\r\n")
    check("v1.6.4: the pinned document is byte-equal to the live one (no phantom line)",
          document(_pin) == document(_ref),
          f"pin={document(_pin)[-4:]} live={document(_ref)[-4:]}")

    # 7c. USER INTENT returns to the live line — a keystroke, a paste and the wheel to the bottom
    class _Thread:
        def __init__(self):
            self.sent = []

        def send_data(self, data):
            self.sent.append(data)

        def stop(self):
            pass

    _tsc = TerminalScreen(columns=20, lines=10, history_lines=200, scroll_mode=SCROLL_MODE_PIN)
    for i in range(30):
        _tsc.feed(("line %02d\r\n" % i).encode())
    _thr = _Thread()
    _wk = TerminalWidget(_tsc, _thr)
    _tsc.scroll_up()
    check("v1.6.4: the pin really holds the viewport off the live line",
          _wk.pinned() is True and _tsc.at_bottom() is False, str(_tsc.scroll_info()))
    press_key(_wk, Qt.Key.Key_A, text="a")
    check("v1.6.4: A KEYSTROKE is user intent → the view returns to the live line",
          _tsc.at_bottom() is True and _thr.sent == [b"a"], f"{_tsc.at_bottom()} {_thr.sent!r}")

    _tsc.scroll_up()
    _thr.sent.clear()
    QApplication.clipboard().setText("pasted command")
    _wk._bracketed_paste()
    check("v1.6.4: a PASTE returns to the live line too (it goes through the same _send)",
          _tsc.at_bottom() is True and len(_thr.sent) == 1 and _thr.sent[0].startswith(b"\x1b[200~"),
          f"{_tsc.at_bottom()} {_thr.sent!r}")

    _tsc.scroll_up()
    _ops_before = CountingHistory.page_ops
    while not _tsc.at_bottom():
        wheel(_wk, -120)
    check("v1.6.4: the WHEEL to the bottom returns to live (the pin has nothing left to hold)",
          _tsc.at_bottom() is True and CountingHistory.page_ops > _ops_before,
          str(_tsc.scroll_info()))

    # 7d. the N7 selection rule: the pin keeps it, the live mode still drops it
    import modules.ssh_terminal as _ST
    from models.server import ServerData
    from modules.terminal_page import TerminalSessionPage
    from _fakes import FakeSSHThread as _FakeThread

    class _FakeTerm(_FakeThread):
        def __init__(self, *a, **k):
            super().__init__("127.0.0.1", "u", 9, "", "")

        def run(self):
            pass

    _orig_cls = _ST.SSHTerminalThread
    _ST.SSHTerminalThread = _FakeTerm
    merge_cfg({"terminal_scroll": "pin"})   # the session reads the key at creation
    try:
        _page = TerminalSessionPage(
            ServerData(id="pin-a", alias="p", host="127.0.0.1", user="u"))
        app.processEvents()
        _ps = _page.tscreen
        for i in range(120):   # the page's grid is 120x32 — the history needs real depth
            _ps.feed(("line %03d\r\n" % i).encode())
        _ps.scroll_up()
        _page.widget._sel_anchor = (2, 0)
        _page.widget._sel_active = (2, 5)
        _page._on_output(b"while reading\r\n")
        check("v1.6.4: a selection made while reading history SURVIVES the chunk under 'pin'",
              _page.widget.has_selection() is True and _ps.at_bottom() is False,
              f"sel={_page.widget.has_selection()} bottom={_ps.at_bottom()}")
        _page.widget._release_pin()
        check("v1.6.4: ... and the return to live drops it (the N7 reasoning, on USER intent)",
              _page.widget.has_selection() is False and _ps.at_bottom() is True)

        # the "live" mode keeps the v1.1.2RC3 rule: the auto-return drops the selection
        _ps.set_scroll_mode(SCROLL_MODE_LIVE)
        _ps.scroll_up()
        _page.widget._sel_anchor = (2, 0)
        _page.widget._sel_active = (2, 5)
        _page._on_output(b"yanks the view\r\n")
        check("v1.6.4: the 'live' mode still resets the selection on the auto-return (N7)",
              _page.widget.has_selection() is False and _ps.at_bottom() is True)
        _page.shutdown()
        app.processEvents()
    finally:
        _ST.SSHTerminalThread = _orig_cls
        clear_cfg()

    # 7e. the find bar's Ctrl+Shift+F → Enter → Esc round trip, in BOTH modes
    def find_round_trip(mode):
        scr = TerminalScreen(columns=20, lines=10, history_lines=200, scroll_mode=mode)
        for i in range(60):
            scr.feed(("line %02d\r\n" % i).encode())
        w = TerminalWidget(scr, None)
        for _ in range(3):
            scr.scroll_up()
        top_before = lines_of(scr)[0]
        w.open_find()
        w._on_find_query("line 05")
        w.find_next()
        moved = lines_of(scr)[0]
        w.close_find(restore=True)
        return top_before, moved, lines_of(scr)[0]

    _lb, _lm, _la = find_round_trip(SCROLL_MODE_LIVE)
    check("v1.6.4: the find round trip lands on the captured lines in the 'live' mode",
          _la == _lb and _lm != _lb, f"{_lb!r} -> {_lm!r} -> {_la!r}")
    _pb, _pm, _pa = find_round_trip(SCROLL_MODE_PIN)
    check("v1.6.4: ... and exactly on them under 'pin' (the saved value is a CONTENT offset)",
          _pa == _pb and _pm != _pb, f"{_pb!r} -> {_pm!r} -> {_pa!r}")
finally:
    TS.SshmapHistoryScreen = _screen_cls

finish()
