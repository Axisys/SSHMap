# -*- coding: utf-8 -*-
"""v1.9 — the `OSC 8` link of the canvas: the pure run hit test, the gesture, the allowlist and the underline.
The link rides the CELL (pyte patch 0011, `Char.hyperlink`), so the canvas stores no URI: `link_span()` is the
PURE maximal run of equal URIs around a cell and every reader goes back to the GRID, so an erase takes the
decoration with it. The gesture is `Ctrl`+click while the application tracks the mouse and a PLAIN click while
it does not (`Shift` stays the local-selection override), and the ONE opener door is the shipped
`models.server.is_launchable_url()` allowlist (`http`/`https`; a `file:` link a REMOTE program sent is refused
rather than translated into a local path). Rule — `AGENTS.md` §4.3, §4.4; mechanism — `DOCUMENTATION.md` §64.
"""
import sys

from _common import (bootstrap, check, finish, check_release_state, load_i18n_langs,
                     check_i18n_parity)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from third_party import pyte
import modules.terminal_widget as TW
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget, link_span

# The two payloads a program sends: a launchable link and the `file:` one a REMOTE program may name.
LINK = b"\x1b]8;;https://example.com/docs\x07DOCS\x1b]8;;\x07 plain"
FILE_LINK = b"\x1b]8;;file:///etc/passwd\x07PASSWD\x1b]8;;\x07"


class FakeThread:
    """The fake `SSHTerminalThread`: the recorded sends (the pattern of `test_terminal_mouse.py`)."""

    def __init__(self):
        self.sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


class FakeOpener:
    """The `QDesktopServices` seam: records what the OS was really asked to open."""

    def __init__(self):
        self.opened = []

    def openUrl(self, url):  # noqa: N802 — the Qt spelling
        self.opened.append(url)
        return True


class FakeUrl:
    """The `QUrl` seam: the opened target as text, so the assertion never needs a real Qt URL."""

    def __init__(self, text):
        self.text = str(text)

    def __repr__(self):
        return f"QUrl({self.text!r})"


def press(widget, x, y, mods=Qt.KeyboardModifier.NoModifier):
    """The synthetic press (gotcha #6: a real QMouseEvent, never a hand-made one)."""
    pos = QPointF(x, y)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, pos,
                     widget.mapToGlobal(QPoint(int(x), int(y))),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, mods)
    widget.mousePressEvent(ev)
    return ev


def move(widget, x, y):
    """The synthetic motion — the hover's own event."""
    pos = QPointF(x, y)
    ev = QMouseEvent(QEvent.Type.MouseMove, pos,
                     widget.mapToGlobal(QPoint(int(x), int(y))),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    widget.mouseMoveEvent(ev)
    return ev


def render(widget):
    """One offscreen paint of the canvas as an image (the underline is a PAINT effect)."""
    pm = QPixmap(widget.size())
    pm.fill(Qt.GlobalColor.black)
    painter = QPainter(pm)
    widget._paint(painter)
    painter.end()
    return pm.toImage()


# ════════════════════════════════════════════════════════════
# 1. The PURE hit test: a link is a RUN of the row
# ════════════════════════════════════════════════════════════
print("== the pure hit test (`link_span`) ==")

row = [pyte.screens.Char(" ") for _ in range(10)]
for x in range(2, 6):
    row[x] = pyte.screens.Char("x", hyperlink="https://a.example")
row[6] = pyte.screens.Char("x", hyperlink="https://b.example")

check("the span is the maximal RUN of equal URIs around the cell",
      link_span(row, 3) == (2, 5, "https://a.example"), str(link_span(row, 3)))
check("a cell of the second link answers its OWN run", link_span(row, 6) == (6, 6, "https://b.example"),
      str(link_span(row, 6)))
check("a cell without a link answers None (the press falls through)",
      link_span(row, 0) is None and link_span(row, 7) is None, str(link_span(row, 0)))
check("a col outside the row answers None (never an IndexError)",
      link_span(row, -1) is None and link_span(row, 99) is None and link_span(None, 0) is None)


# ════════════════════════════════════════════════════════════
# 2. The gesture and the allowlist (offscreen Qt, a fake thread)
# ════════════════════════════════════════════════════════════
print("== the widget: the hit test, the gesture and the allowlist ==")

scr = TerminalScreen(columns=40, lines=6)
thread = FakeThread()
w = TerminalWidget(scr, thread)
w.resize(40 * w.cell_size[0], 6 * w.cell_size[1])
scr.feed(LINK)
cw, ch = w.cell_size
opener = FakeOpener()

_orig_url, _orig_open = TW.QUrl, TW.QDesktopServices
TW.QUrl, TW.QDesktopServices = FakeUrl, opener
try:
    middle = QPoint(int(1.5 * cw), int(0.5 * ch))
    outside = QPoint(int(8 * cw), int(0.5 * ch))

    check("`link_uri_at` finds the URI of the linked run",
          w.link_uri_at(middle) == "https://example.com/docs", w.link_uri_at(middle))
    check("`link_uri_at` answers \"\" outside the link", w.link_uri_at(outside) == "",
          repr(w.link_uri_at(outside)))

    check("`row_cells()` is the ONE-row reader beside `snapshot()` (an unusable index is empty)",
          len(scr.row_cells(0)) == 40 and scr.row_cells(-1) == [] and scr.row_cells(None) == []
          and scr.row_cells("x") == [] and len(scr.snapshot()[0][0]) == 40,
          f"{len(scr.row_cells(0))} cells")

    # The hover asks about ONE ROW: `snapshot()` copies the WHOLE grid under the lock, and a
    # pointer crossing the canvas would pay that per motion event.
    _reads = []
    _orig_snapshot, _orig_row_cells = scr.snapshot, scr.row_cells

    def _counted_snapshot():
        _reads.append("snapshot")
        return _orig_snapshot()

    def _counted_row(row):
        _reads.append(("row", row))
        return _orig_row_cells(row)

    scr.snapshot, scr.row_cells = _counted_snapshot, _counted_row
    try:
        w._hover_cell = None
        _reads.clear()
        w._refresh_hover(middle)
        _on_link = list(_reads)
        w._hover_cell = None
        _reads.clear()
        w._refresh_hover(outside)
        _off_link = list(_reads)
    finally:
        scr.snapshot, scr.row_cells = _orig_snapshot, _orig_row_cells
    check("the link hover reads ONE ROW of the live grid, never the whole snapshot",
          _on_link == [("row", 0)] and _off_link == [("row", 0)],
          f"on={_on_link} off={_off_link}")

    ev = press(w, 1.5 * cw, 0.5 * ch)
    check("a PLAIN click opens the link while the application is NOT tracking the mouse",
          len(opener.opened) == 1 and opener.opened[0].text == "https://example.com/docs",
          str(opener.opened))
    check("…and the press is CONSUMED (no selection starts, nothing goes to the PTY)",
          ev.isAccepted() and w._sel_anchor is None and thread.sent == [],
          f"accepted={ev.isAccepted()} anchor={w._sel_anchor} sent={thread.sent}")

    opener.opened.clear()
    w._sel_anchor = w._sel_active = None
    thread.sent.clear()
    scr.feed(b"\x1b[?1000h\x1b[?1006h")            # NOW the application tracks the mouse
    ev = press(w, 1.5 * cw, 0.5 * ch)
    check("with the mouse TRACKED a plain click is the application's (reported, not opened)",
          opener.opened == [] and thread.sent == [b"\x1b[<0;2;1M"], f"{opener.opened} {thread.sent}")
    check("…and the link did not eat the report", ev.isAccepted())

    thread.sent.clear()
    ev = press(w, 1.5 * cw, 0.5 * ch, Qt.KeyboardModifier.ControlModifier)
    check("`Ctrl`+click under tracking opens the link and consumes the press",
          len(opener.opened) == 1 and thread.sent == [] and ev.isAccepted(),
          f"{opener.opened} sent={thread.sent}")

    opener.opened.clear()
    scr.feed(b"\x1b[?1000l\x1b[?1006l")
    press(w, 1.5 * cw, 0.5 * ch, Qt.KeyboardModifier.ControlModifier)
    check("`Ctrl`+click outside tracking opens it too (ONE gesture, either state)",
          len(opener.opened) == 1, str(opener.opened))

    opener.opened.clear()
    press(w, 8 * cw, 0.5 * ch)
    check("a click on a cell WITHOUT a link is not consumed by the link branch (the selection starts)",
          opener.opened == [] and w._sel_anchor is not None, str(w._sel_anchor))
    w._sel_anchor = w._sel_active = None

    scr2 = TerminalScreen(columns=40, lines=6)
    w2 = TerminalWidget(scr2, FakeThread())
    w2.resize(40 * cw, 6 * ch)
    scr2.feed(FILE_LINK)
    opener.opened.clear()
    ev = press(w2, 1.5 * cw, 0.5 * ch)
    check("a `file:` link is REFUSED by the shipped allowlist — the OS is never asked",
          opener.opened == [], str(opener.opened))
    check("…and the click still belongs to the link (consumed, no selection)",
          ev.isAccepted() and w2._sel_anchor is None)

    # ════════════════════════════════════════════════════════
    # 3. The hover: a CELL, a hand and the underline of the RUN
    # ════════════════════════════════════════════════════════
    print("== the hover and the underline ==")

    move(w, 1.5 * cw, 0.5 * ch)
    check("a motion over the link sets the hover CELL", w._hover_cell == (0, 1), str(w._hover_cell))
    check("…and the pointing hand", w.cursor().shape() == Qt.CursorShape.PointingHandCursor,
          str(w.cursor().shape()))

    clean = render(w)          # the same widget, hover CLEARED — the "no underline" reference
    w._hover_cell = None
    plain = render(w)
    again = render(w)          # a SECOND paint of the same un-hovered state
    w._hover_cell = (0, 1)
    hovered = render(w)
    band = ch - max(1, ch // 12)          # the hovered cell is (row 0, col 1) → its underline row
    thick = max(1, ch // 12)
    check("…and two paints of the same un-hovered state are identical (the band is the hover, not noise)",
          all(again.pixel(x, band) == plain.pixel(x, band) for x in range(40 * cw)))
    inside = [x for x in range(8 * cw) if hovered.pixel(x, band) != plain.pixel(x, band)]
    outside = [x for x in range(8 * cw, 12 * cw)
               if hovered.pixel(x, band) != plain.pixel(x, band)]
    check("the underline is painted over the linked RUN only",
          bool(inside) and not outside, f"inside={len(inside)} outside={len(outside)}")
    check("…the ink is a real emphasis of the cell (the LINK_COLOR alpha blended over it)",
          inside and (hovered.pixelColor(min(inside), band).blue()
                      > plain.pixelColor(min(inside), band).blue() + 40),
          f"{hovered.pixelColor(min(inside), band).getRgb()} vs "
          f"{plain.pixelColor(min(inside), band).getRgb()}")
    diffs = [(x, y) for y in range(6 * ch) for x in range(40 * cw)
             if hovered.pixel(x, y) != plain.pixel(x, y)]
    rows = sorted({y for _x, y in diffs})
    check("…and the ONLY difference between the two paints is that band of the hovered row",
          bool(diffs) and all(band <= y < band + thick for y in rows), f"{len(diffs)} px, rows {rows}")
    check("an offscreen paint of the hovered canvas drew the whole size (the render is not a stub)",
          clean.width() == 40 * cw and clean.height() == 6 * ch,
          f"{clean.width()}x{clean.height()}")

    move(w, 8 * cw, 0.5 * ch)
    check("a motion off the link clears the hover and the hand",
          w._hover_cell is None and w.cursor().shape() != Qt.CursorShape.PointingHandCursor,
          f"{w._hover_cell} {w.cursor().shape()}")

    move(w, 1.5 * cw, 0.5 * ch)
    w.leaveEvent(QEvent(QEvent.Type.Leave))
    check("leaving the canvas clears the hover too",
          w._hover_cell is None and w.cursor().shape() != Qt.CursorShape.PointingHandCursor)

    # ════════════════════════════════════════════════════════
    # 4. The link dies WITH the cell (the URI is read from the grid)
    # ════════════════════════════════════════════════════════
    print("== the link dies with the cell ==")

    scr3 = TerminalScreen(columns=40, lines=6)
    w3 = TerminalWidget(scr3, FakeThread())
    w3.resize(40 * cw, 6 * ch)
    scr3.feed(LINK)
    move(w3, 1.5 * cw, 0.5 * ch)
    check("the hover is live on the link", w3._hover_cell is not None, str(w3._hover_cell))
    _before = scr3.snapshot()[0][0]          # `snapshot()` answers (rows, cursor_x, cursor_y, hidden)
    check("the four cells of the link carry the URI on the grid (the paint check is not vacuous)",
          [getattr(c, "hyperlink", "") for c in _before[:4]] == ["https://example.com/docs"] * 4,
          str([getattr(c, "hyperlink", "") for c in _before[:4]]))
    scr3.feed(b"\x1b[2J")
    w3._hover_cell = (0, 1)          # the cell is still hovered, the grid changed under it
    after = render(w3)
    w3._hover_cell = None
    blank = render(w3)
    check("an erased link paints NO underline (the URI is read from the grid, never stored)",
          not [x for x in range(8 * cw) if after.pixel(x, band) != blank.pixel(x, band)])
    check("a click after the erase opens nothing",
          (opener.opened.clear(), press(w3, 1.5 * cw, 0.5 * ch), opener.opened == [])[2],
          str(opener.opened))
    _after = scr3.snapshot()[0][0]
    check("…because the ERASE dropped the link from the cell itself (the BCE half of the cycle)",
          all(getattr(c, "hyperlink", "") == "" for c in _after) and len(_after) == 40,
          f"{len(_after)} cells, "
          f"{[getattr(c, 'hyperlink', '') for c in _after[:3]]}")
    check("an EMPTY target is refused before the OS is asked",
          w.open_link("") is False and opener.opened == [], str(opener.opened))

    class _RaisingOpener:
        """An OS that refuses to answer: the door must swallow it (a link is never a crash)."""

        def openUrl(self, url):  # noqa: N802 — the Qt spelling
            raise RuntimeError("no desktop session")

    opener.opened.clear()          # the raising seam records nothing; the shipped one is restored below
    TW.QDesktopServices = _RaisingOpener()
    check("an opener that RAISES is a refused link (never an exception out of the canvas)",
          w.open_link("https://example.com/docs") is False)
    TW.QDesktopServices = opener
finally:
    TW.QUrl, TW.QDesktopServices = _orig_url, _orig_open


# ════════════════════════════════════════════════════════════
# 5. Release state + i18n parity
# ════════════════════════════════════════════════════════════
print("== release state + i18n parity ==")

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)

finish()
