# -*- coding: utf-8 -*-
"""v1.2.7 — Terminal: double/triple-click selection + context menu (ROADMAP v1.2.7).

  * word_units() (a pure function, no GUI): a word = the maximal run of the non-blank
    cells; the punctuation belongs to the word ("foo,bar" — one); the stub of the wide
    CJK glyph (data=='') belongs to the word ("a中b" — one word on 4 cells);
    the blanks/an empty string → [];
  * the double click — the selection of the WORD (offscreen, the synthetic QMouseEvents;
    the click-count is counted by the widget itself: the QMouseEvent in PySide6 does not carry it):
    the boundaries of the word + selected_text(); the click on a blank — does nothing; the interval
    beyond DOUBLE_CLICK_MS → the counter is reset, a plain click resets the selection;
  * the triple click — the whole LINE (0..columns-1);
  * the drag after the double click — the extension from the FAR end of the word (the
    _click_sel_end anchor), the release at count>=2 does NOT clobber the selection;
  * the context menu of the right click (_build_context_menu — the test seam, without menu.exec()):
    the composition/the order [Copy | Paste | Select all], the Copy is enabled
    only with the selection → the clipboard, the Paste → the bracketed-paste block into the PTY
    (the same path as Ctrl+V; an empty clipboard → nothing; thread=None → disabled),
    the Select all → the whole grid; the right click does not reset the selection; the REAL path of the right click
    (the contextMenuEvent with the real QContextMenuEvent → menu.exec in the global
    coordinates — the regression v1.2.7-fix: globalPos() is already a QPoint, .toPoint() crashed);
    the captions en/ru/zh;
  * i18n: +3 keys terminal.menu.* × en/ru/zh, the parity 422 → 425, the release state.

The Acceptance of the ROADMAP v1.2.7: the double click selects the word, the triple — the line,
the actions of the menu work (the copy with the selection → the clipboard, the paste → the bytes
into the PTY); the full run of the suite exit 0.

Run:  python tests/test_terminal_selection_menu.py   (from the project root) or python tests/run_all.py
"""
import sys
import time

from _common import (bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QEvent, QPointF, QPoint
from PySide6.QtGui import QMouseEvent, QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)

from modules.terminal_screen import TerminalScreen
import modules.terminal_widget as _tw
from modules.terminal_widget import TerminalWidget, selection_cells, word_units


from _fakes import FakeWidgetThread as FakeThread
FakeThread.sent = []
sent = FakeThread.sent   # the same list — for the checks below


_NO_THREAD = object()   # sentinel: an explicit thread=None ≠ "not passed" (the default FakeThread)


def make_widget(cols=20, lines=5, thread=_NO_THREAD):
    scr = TerminalScreen(columns=cols, lines=lines)
    if thread is _NO_THREAD:
        thread = FakeThread()
    return scr, TerminalWidget(scr, thread)


# ── the mouse: the synthetic QMouseEvents (the test_terminal_input.py pattern) ──────────

def lmb_press(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                  Qt.KeyboardModifier.NoModifier))


def lmb_release(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))


def lmb_move(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
                                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier))


def rmb_press(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                  Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
                                  Qt.KeyboardModifier.NoModifier))


def rmb_release(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                    Qt.MouseButton.RightButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))


def double_click(w, r, c):
    """press/release + press/release in one cell (within DOUBLE_CLICK_MS)."""
    lmb_press(w, r, c)
    lmb_release(w, r, c)
    lmb_press(w, r, c)
    lmb_release(w, r, c)


def triple_click(w, r, c):
    double_click(w, r, c)
    lmb_press(w, r, c)
    lmb_release(w, r, c)


# ════════════════════════════════════════════════════════════
# 1. word_units — a pure function (no GUI)
# ════════════════════════════════════════════════════════════
print("== word_units (pure) ==")


def row_of(text, cols=20):
    """The row of pyte Chars from the text (through the real TerminalScreen — the E2E path)."""
    scr = TerminalScreen(columns=cols, lines=2)
    scr.feed(text.encode("utf-8") + b"\r\n")
    rows, _cx, _cy, _hidden = scr.snapshot()
    return rows[0]


check("«hello world» → [(0,4),(6,10)]", word_units(row_of("hello world")) == [(0, 4), (6, 10)],
      repr(word_units(row_of("hello world"))))
check("the blanks at the edges / in a row: '  ab  cd  ' → [(2,3),(6,7)]",
      word_units(row_of("  ab  cd  ")) == [(2, 3), (6, 7)],
      repr(word_units(row_of("  ab  cd  "))))
check("the punctuation is inside the word: 'foo,bar' → one word [(0,6)]",
      word_units(row_of("foo,bar")) == [(0, 6)], repr(word_units(row_of("foo,bar"))))
check("an empty string → []", word_units(row_of("")) == [])
check("blanks only → []", word_units(row_of("   ")) == [])
# CJK: a wide glyph = a cell + a stub (data=='') — the stub BELONGS to the word
cjk_row = row_of("a中b")
check("CJK 'a中b': 4 cells (the glyph + the stub), one word [(0,3)]",
      [ch.data for ch in cjk_row[:4]] == ["a", "中", "", "b"] and word_units(cjk_row) == [(0, 3)],
      f"row={[ch.data for ch in cjk_row[:6]]} units={word_units(cjk_row)}")
check("CJK between words: 'x a中b y' → [(0,0),(2,5),(7,7)]",
      word_units(row_of("x a中b y")) == [(0, 0), (2, 5), (7, 7)],
      repr(word_units(row_of("x a中b y"))))

# ════════════════════════════════════════════════════════════
# 2. Double click — word selection (offscreen)
# ════════════════════════════════════════════════════════════
print("== double-click → word ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
cw, chh = w.cell_size
w.resize(cw * 20, chh * 5)

# The first (simple) click — no selection; the second within the interval — the word
lmb_press(w, 0, 7)      # count=1
lmb_release(w, 0, 7)    # a simple click (a press/release in one cell) → a reset
check("a plain click → no selection", not w.has_selection())
lmb_press(w, 0, 7)      # count=2 (the same cell, within DOUBLE_CLICK_MS) → _select_word
check("a double click (press): the selection is active", w.has_selection())
check("the click counter == 2", w._click_count == 2, f"count={w._click_count}")
check("the word 'world' bounds = (0,6)-(0,10)",
      (w._sel_anchor, w._sel_active) == ((0, 6), (0, 10)),
      f"got=({w._sel_anchor}, {w._sel_active})")
check("selected_text() == «world»", w.selected_text() == "world", repr(w.selected_text()))
lmb_release(w, 0, 7)    # a release at count>=2 does NOT clobber the selection
check("the release after a double click → the selection survives",
      (w._sel_anchor, w._sel_active) == ((0, 6), (0, 10)) and w.has_selection(),
      f"got=({w._sel_anchor}, {w._sel_active})")

# A double click on a space — does nothing (the selection is not changed/created)
w.clear_selection()
double_click(w, 0, 15)
check("a double click on a blank → nothing happens", not w.has_selection())

# An interval larger than DOUBLE_CLICK_MS → the counter was reset: "double" = two simple clicks
w.clear_selection()
lmb_press(w, 0, 7)
lmb_release(w, 0, 7)
w._last_click_ms = time.monotonic() * 1000.0 - 2000.0   # simulating a pause (ms; a test hook)
lmb_press(w, 0, 7)
check("a pause > DOUBLE_CLICK_MS → the count was reset to 1", w._click_count == 1,
      f"count={w._click_count}")
lmb_release(w, 0, 7)
check("a plain click after the pause → the selection is reset", not w.has_selection())

# ════════════════════════════════════════════════════════════
# 3. Triple click — line selection (offscreen)
# ════════════════════════════════════════════════════════════
print("== triple-click → line ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
w.resize(cw * 20, chh * 5)

triple_click(w, 1, 2)
check("a triple click: the selection is active", w.has_selection())
check("the line bounds = (1,0)-(1,19)",
      (w._sel_anchor, w._sel_active) == ((1, 0), (1, 19)),
      f"got=({w._sel_anchor}, {w._sel_active})")
check("selected_text() == 'second line' (the trailing blanks are trimmed)",
      w.selected_text() == "second line", repr(w.selected_text()))

# A triple click on the last line — no row clamp is needed, but the grid bounds are exact
triple_click(w, 4, 19)
check("a triple click on the empty line 4 → (4,0)-(4,19), the text is empty",
      (w._sel_anchor, w._sel_active) == ((4, 0), (4, 19)) and w.selected_text() == "",
      f"got=({w._sel_anchor}, {w._sel_active}) text={w.selected_text()!r}")

# ════════════════════════════════════════════════════════════
# 4. Drag after a double click — from the far end of the word (offscreen)
# ════════════════════════════════════════════════════════════
print("== drag after double-click ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
w.resize(cw * 20, chh * 5)

lmb_press(w, 0, 7)
lmb_release(w, 0, 7)
lmb_press(w, 0, 7)      # count=2: the word (0,6)-(0,10); a click near the left edge → the right end is the anchor
check("the drag anchor = the far (right) end of the word", w._click_sel_end == (0, 10),
      f"got={w._click_sel_end}")
lmb_move(w, 2, 3)        # a drag down-left: the anchor = the fixed end, the end = (2,3)
check("drag: the anchor moved to the fixed end", w._sel_anchor == (0, 10), f"got={w._sel_anchor}")
lmb_release(w, 2, 3)
exp = selection_cells((0, 10), (2, 3), 20)
check("a drag after the double click → the cells selection_cells((0,10),(2,3))",
      w._selected_cells() == exp and w.has_selection(), f"got={w._selected_cells()}")

# A click near the right edge of the word → the left end is the anchor
w.clear_selection()
lmb_press(w, 0, 9)
lmb_release(w, 0, 9)
lmb_press(w, 0, 9)      # "world": col=9, start=6, end=10 → 9-6=3 > 10-9=1 → the anchor (0,6)
check("a click near the right edge → the anchor is the left end of the word", w._click_sel_end == (0, 6),
      f"got={w._click_sel_end}")
lmb_release(w, 0, 9)

# ════════════════════════════════════════════════════════════
# 5. The right-click context menu (the _build_context_menu test seam)
# ════════════════════════════════════════════════════════════
print("== context menu (RMB) ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
w.resize(cw * 20, chh * 5)
cb = app.clipboard()

# The composition and the order: [Copy | Paste | Select all] (en — the default)
menu = w._build_context_menu()
check("the menu is a QMenu with 3 items", isinstance(menu, QMenu) and len(menu.actions()) == 3,
      f"actions={len(menu.actions())}")
texts = [a.text() for a in menu.actions()]
check("the order/labels en: Copy | Paste | Select All",
      texts == ["Copy", "Paste", "Select All"], repr(texts))

# Copy — disabled WITHOUT a selection
act_copy, act_paste, act_all = menu.actions()
check("Copy without a selection → disabled", not act_copy.isEnabled())

# A word selection → enabled; the trigger → the clipboard (Acceptance)
double_click(w, 0, 7)
menu = w._build_context_menu()
act_copy = menu.actions()[0]
check("Copy with a selection → enabled", act_copy.isEnabled())
cb.setText("")
sent.clear()
act_copy.trigger()
check("the Copy trigger → the clipboard == 'world'", cb.text() == "world", repr(cb.text()))
check("the Copy trigger → nothing went to the PTY", sent == [], f"sent={sent!r}")

# A right-click does not reset the selection (a press/release RightButton — past the LMB logic)
rmb_press(w, 0, 7)
rmb_release(w, 0, 7)
check("the RMB → the selection is not reset", w.has_selection() and w.selected_text() == "world")

# v1.2.7-fix (a manual-testing regression): the REAL right-click path — contextMenuEvent
# with a real QContextMenuEvent it must call menu.exec() in the global coordinates.
# Before, .toPoint() on a QPoint (QContextMenuEvent's globalPos() already returns a QPoint,
# and not a QPointF) raised an AttributeError, which the except swallowed silently → "a right-click does nothing
# does". A spy via the module global _tw.QMenu: the class-attribute assignment
# QMenu.exec = f in PySide6 6.11 — a silent no-op (verified), and _build_context_menu
# takes the QMenu from its own module global.
_ctx_exec_calls = []


class _SpyCtxMenu(QMenu):
    def exec(self, pos=None):  # noqa: A003 — the QMenu.exec signature
        _ctx_exec_calls.append(pos)
        return 0


_saved_qmenu = _tw.QMenu
_tw.QMenu = _SpyCtxMenu
try:
    w.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                         QPoint(12, 34), QPoint(567, 89)))
finally:
    _tw.QMenu = _saved_qmenu
check("the real RMB path: contextMenuEvent → menu.exec is called (the v1.2.7-fix regression)",
      len(_ctx_exec_calls) == 1, f"calls={_ctx_exec_calls!r}")
check("the real RMB path: exec got the global coordinates of the event",
      bool(_ctx_exec_calls) and _ctx_exec_calls[0] == QPoint(567, 89),
      f"got={_ctx_exec_calls!r}")

# Paste into the PTY — a bracketed-paste block (the same path as Ctrl+V; Acceptance: the bytes in the PTY)
cb.setText("ls -la\r\npwd")
sent.clear()
menu = w._build_context_menu()
act_paste = menu.actions()[1]
check("Paste with a live thread → enabled", act_paste.isEnabled())
act_paste.trigger()
check("the Paste trigger → exactly \\x1b[200~ls -la\\npwd\\x1b[201~ into the PTY",
      sent == [b"\x1b[200~ls -la\npwd\x1b[201~"], f"sent={sent!r}")

cb.setText("")
sent.clear()
w._build_context_menu().actions()[1].trigger()
check("Paste with an empty clipboard → nothing is sent", sent == [], f"sent={sent!r}")

# Select all — the whole visible grid (Acceptance)
w.clear_selection()
menu = w._build_context_menu()
act_all = menu.actions()[2]
check("Select All is always enabled", act_all.isEnabled())
act_all.trigger()
check("select_all: the bounds (0,0)-(4,19)",
      (w._sel_anchor, w._sel_active) == ((0, 0), (4, 19)),
      f"got=({w._sel_anchor}, {w._sel_active})")
# The empty lines 3–4 enter the rectangle → two empty lines as a tail (the drag semantics)
check("selected_text() = all the lines, \\n, the tails trimmed",
      w.selected_text() == "hello world\nsecond line\nthird row\n\n", repr(w.selected_text()))

# thread=None: Paste is disabled (the input is off), Copy/Select all work
scr0, w0 = make_widget(thread=None)
menu0 = w0._build_context_menu()
check("thread=None: Paste → disabled", not menu0.actions()[1].isEnabled())
check("thread=None: Select All → enabled", menu0.actions()[2].isEnabled())
menu0.actions()[2].trigger()
check("thread=None: select_all works locally",
      (w0._sel_anchor, w0._sel_active) == ((0, 0), (4, 19)),
      f"got=({w0._sel_anchor}, {w0._sel_active})")

# The menu labels in ru/zh (the i18n terminal.menu.*)
import i18n as _i18n
saved_lang = _i18n.get_current_language()
try:
    _i18n.set_language("ru")
    texts_ru = [a.text() for a in w._build_context_menu().actions()]
    check("the ru labels",
          texts_ru == ["Копировать", "Вставить", "Выделить всё"], repr(texts_ru))
    _i18n.set_language("zh")
    texts_zh = [a.text() for a in w._build_context_menu().actions()]
    check("the zh labels",
          texts_zh == ["复制", "粘贴", "全选"], repr(texts_zh))
finally:
    _i18n.set_language(saved_lang)

# ════════════════════════════════════════════════════════════
# 6. i18n parity + release state
# ════════════════════════════════════════════════════════════
print("== i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
for code in ("en", "ru", "zh"):
    for key in ("terminal.menu.copy", "terminal.menu.paste", "terminal.menu.select_all"):
        check(f"i18n {code}: {key} is not empty", bool(langs[code].get(key)),
              repr(langs[code].get(key)))
check_release_state(ROOT)

finish()
