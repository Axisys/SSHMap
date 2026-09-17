# -*- coding: utf-8 -*-
"""v1.0RC2 — keyboard + selection/copy (ROADMAP v1.0RC2).

  * selection_cells (a pure function, no GUI): the single-line/multi-line/
    the inverted boundaries/one cell/the whole grid/the column clamp; a regression on
    the draft error #4 (TERMINAL.md §3) — the coordinates are ALWAYS (row, col),
    the line-by-line order: the column interpretation of the draft ((col, row)) does not give
    the same set of cells;
  * the keyboard (an offscreen widget + a fake thread): the full F1–F12 table
    (the xterm sequences SS3/CSI), PageUp/PageDown, Home/End/Delete
    (the semantics of the old SSHTerminalTextEdit are preserved), the basic RC1 set
    (the printable/utf-8/Return/Backspace/Tab/Shift+Tab/Esc/the arrows); the Ctrl+C without the selection →
    b'\\x03' (the Acceptance: "Ctrl+C kills top"); the Ctrl+D → \\x04, the Ctrl+Z → \\x1a;
    the AltGr guard (Ctrl+Alt held → nothing is sent — TERMINAL.md §3.12);
  * Tab/Shift+Tab by the FULL path (QApplication.sendEvent through notify, §2b):
    the regression v1.2.9-fix — Qt 6 intercepts them BEFORE the keyPressEvent
    (the focus-change mechanism), the \t/\x1b[Z must reach the channel, and the focus must stay
    on the terminal (the mc scenario: the series of Tabs without the focus drift);
  * the bracketed paste Ctrl+V (the move from v0.9.4): the multi-line clipboard with
    mixed EOL — a SINGLE block \\x1b[200~...\\x1b[201~ with the normalized
    line breaks; an empty clipboard → nothing is sent;
  * the mouse selection + the copying (offscreen, the synthetic QMouseEvents):
    the LMB drag in both directions, a plain click = the selection reset, the Ctrl+C with the
    selection → the copy of the multi-line text to the clipboard (the Acceptance),
    without the selection → \\x03; the drag beyond the grid → the clamp; the semi-transparent
    highlight renders (the pixels + the stats).

Run:  python tests/test_terminal_input.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

app = QApplication(sys.argv)

from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget, selection_cells


# ════════════════════════════════════════════════════════════
# 1. selection_cells — a pure function (a regression for draft error №4)
# ════════════════════════════════════════════════════════════
print("== selection_cells (pure) ==")

check("the single-line: (2,1)-(2,5) → the 5 cells",
      selection_cells((2, 1), (2, 5), 10) == [(2, c) for c in range(1, 6)],
      repr(selection_cells((2, 1), (2, 5), 10)))

exp_multi = ([(1, c) for c in range(3, 8)] +
             [(r, c) for r in (2, 3) for c in range(8)] +
             [(4, c) for c in range(0, 8)])
check("the multi-line: (1,3)-(4,7) cols=8 — the first one from the col 3, the middle ones the full width, the last one up to the col 7",
      selection_cells((1, 3), (4, 7), 8) == exp_multi,
      f"got={selection_cells((1, 3), (4, 7), 8)}")

check("the inverted bounds: (4,7)-(1,3) → the same set",
      selection_cells((4, 7), (1, 3), 8) == exp_multi,
      f"got={selection_cells((4, 7), (1, 3), 8)}")

check("one cell: (0,0)-(0,0)", selection_cells((0, 0), (0, 0), 5) == [(0, 0)])

check("the whole grid 3x10 → the 30 cells",
      len(selection_cells((0, 0), (2, 9), 10)) == 30
      and selection_cells((0, 0), (2, 9), 10)[-1] == (2, 9))

check("the clamp of the columns: c2=99 → cols-1",
      selection_cells((0, 0), (1, 99), 8) == [(r, c) for r in (0, 1) for c in range(8)],
      f"got={selection_cells((0, 0), (1, 99), 8)}")

# A REGRESSION for error №4 (TERMINAL.md §3): the draft stored (col, row) and compared
# as a tuple — column order. start=(0,5), end=(2,1), cols=8: line by line this is
# line 0 with col 5..7, line 1 in full, line 2 up to col 1 (13 cells).
cells4 = selection_cells((0, 5), (2, 1), 8)
exp4 = ([(0, c) for c in range(5, 8)] + [(1, c) for c in range(8)]
        + [(2, c) for c in range(2)])
check("the regression №4: the line-by-line order (row-major), not the column one",
      cells4 == exp4, f"got={cells4}")
check("the regression №4: the cells of the column interpretation of the draft are absent",
      (3, 0) not in cells4 and (0, 6) in cells4 and len(cells4) == 13, f"got={cells4}")

check("columns=0 → [] (defensive)", selection_cells((0, 0), (2, 5), 0) == [])


# ════════════════════════════════════════════════════════════
# 2. Keyboard: the full table (offscreen + a fake thread)
# ════════════════════════════════════════════════════════════
print("== keyboard (offscreen) ==")

from _fakes import FakeWidgetThread as FakeThread
FakeThread.sent = []
sent = FakeThread.sent   # the same list — for the checks below


def make_widget(cols=20, lines=5, thread=None):
    scr = TerminalScreen(columns=cols, lines=lines)
    return scr, TerminalWidget(scr, thread if thread is not None else FakeThread())


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier

scr, w = make_widget()

# F1–F12 — the full table (xterm: F1–F4 SS3, F5–F12 CSI)
f_keys = [Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3, Qt.Key.Key_F4,
          Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7, Qt.Key.Key_F8,
          Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11, Qt.Key.Key_F12]
f_expect = [b"\x1bOP", b"\x1bOQ", b"\x1bOR", b"\x1bOS", b"\x1b[15~", b"\x1b[17~",
            b"\x1b[18~", b"\x1b[19~", b"\x1b[20~", b"\x1b[21~", b"\x1b[23~", b"\x1b[24~"]
for i, (k, e) in enumerate(zip(f_keys, f_expect), 1):
    sent.clear()
    press_key(w, k)
    check(f"F{i} → {e!r}", sent == [e], f"sent={sent!r}")

# PageUp/PageDown/Home/End/Delete (Home/End/Delete — the SSHTerminalTextEdit semantics)
for label, k, e in (("PageUp", Qt.Key.Key_PageUp, b"\x1b[5~"),
                    ("PageDown", Qt.Key.Key_PageDown, b"\x1b[6~"),
                    ("Home", Qt.Key.Key_Home, b"\x1b[H"),
                    ("End", Qt.Key.Key_End, b"\x1b[F"),
                    ("Delete", Qt.Key.Key_Delete, b"\x1b[3~")):
    sent.clear()
    press_key(w, k)
    check(f"{label} → {e!r}", sent == [e], f"sent={sent!r}")

# The basic set (moved from RC1): printable/utf-8 and the function keys
for ch in ("a", "é"):
    sent.clear()
    press_key(w, ord(ch), text=ch)
    check(f"the printable {ch!r} → utf-8", sent == [ch.encode("utf-8")], f"sent={sent!r}")

for label, k, e in (("Return", Qt.Key.Key_Return, b"\r"),
                    ("Enter", Qt.Key.Key_Enter, b"\r"),
                    ("Backspace", Qt.Key.Key_Backspace, b"\x7f"),
                    ("Tab", Qt.Key.Key_Tab, b"\t"),
                    ("Shift+Tab", Qt.Key.Key_Backtab, b"\x1b[Z"),
                    ("Esc", Qt.Key.Key_Escape, b"\x1b"),
                    ("Left", Qt.Key.Key_Left, b"\x1b[D"),
                    ("Right", Qt.Key.Key_Right, b"\x1b[C"),
                    ("Up", Qt.Key.Key_Up, b"\x1b[A"),
                    ("Down", Qt.Key.Key_Down, b"\x1b[B")):
    sent.clear()
    press_key(w, k)
    check(f"{label} → {e!r}", sent == [e], f"sent={sent!r}")

# Ctrl+C WITHOUT a selection → SIGINT (Acceptance: "Ctrl+C kills top")
sent.clear()
press_key(w, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C without the selection → b'\\x03'", sent == [b"\x03"], f"sent={sent!r}")

# Ctrl+D / Ctrl+Z (explicit, as in RC1)
for label, k, e in (("Ctrl+D", Qt.Key.Key_D, b"\x04"), ("Ctrl+Z", Qt.Key.Key_Z, b"\x1a")):
    sent.clear()
    press_key(w, k, mod=CTRL)
    check(f"{label} → {e!r}", sent == [e], f"sent={sent!r}")

# The AltGr guard (TERMINAL.md §3.12): on Windows AltGr = Ctrl+Alt — nothing is sent
for label, k in (("C", Qt.Key.Key_C), ("D", Qt.Key.Key_D), ("V", Qt.Key.Key_V),
                 ("Z", Qt.Key.Key_Z), ("2", Qt.Key.Key_2)):
    sent.clear()
    press_key(w, k, mod=CTRL | ALT)
    check(f"AltGr-guard: Ctrl+Alt+{label} → nothing is sent", sent == [], f"sent={sent!r}")

# terminal_thread=None — the input is disabled, no exceptions
scr0, w0 = make_widget(thread=None)
try:
    press_key(w0, Qt.Key.Key_Return)
    press_key(w0, Qt.Key.Key_F1)
    press_key(w0, ord("x"), text="x")
    check("terminal_thread=None: the keys do not crash and send nothing", True)
except Exception as e:
    check("terminal_thread=None: the keys do not crash and send nothing", False, repr(e))


# ════════════════════════════════════════════════════════════
# 2b. Tab/Shift+Tab — the FULL delivery path (the v1.2.9-fix regression)
#     Qt 6 intercepts bare Tab/Shift+Tab at the focus-change level BEFORE
#     keyPressEvent (QWidget docs: "To force those keys to be processed
#     by your widget, you must reimplement QWidget::event()"). A direct call
#     keyPressEvent (the table above) this path did NOT cover — so the bug survived
#     from v1.0RC2 to v1.2.9: in a real window Tab drove focus across buttons/tabs,
#     and \t never reached the shell (bash autocompletion, mc panels).
#     Here — QApplication.sendEvent (via notify) + a second focusable
#     widget in the same window = a real focus chain.
# ════════════════════════════════════════════════════════════
print("== Tab/Shift+Tab focus retention (full delivery path) ==")


class _FocusThread:
    def __init__(self):
        self.sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


def _focus_setup():
    """TerminalWidget + a button in one window (the focus chain), the focus — on the canvas."""
    scr_ = TerminalScreen(columns=20, lines=5)
    th = _FocusThread()
    w_ = TerminalWidget(scr_, th)
    btn = QPushButton("next")
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.addWidget(w_)
    lay.addWidget(btn)
    host.resize(400, 200)
    host.show()
    app.processEvents()
    w_.setFocus()
    app.processEvents()
    return w_, th, btn, host


w_f, th_f, _btn_f, host_f = _focus_setup()

ev_tab = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_Tab),
                   Qt.KeyboardModifier.NoModifier, "\t")
QApplication.sendEvent(w_f, ev_tab)
app.processEvents()
check("Tab (the full path): \\t reached the channel", th_f.sent == [b"\t"], f"sent={th_f.sent!r}")
check("Tab (the full path): the focus STAYED on the terminal (did not go to the button)",
      app.focusWidget() is w_f, f"focus={app.focusWidget()}")

ev_btab = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_Backtab),
                    Qt.KeyboardModifier.ShiftModifier, "")
QApplication.sendEvent(w_f, ev_btab)
app.processEvents()
check("Shift+Tab (the full path): \\x1b[Z reached the channel",
      th_f.sent == [b"\t", b"\x1b[Z"], f"sent={th_f.sent!r}")
check("Shift+Tab (the full path): the focus stayed on the terminal", app.focusWidget() is w_f,
      f"focus={app.focusWidget()}")

# The mc scenario: Tab series — the focus does not drift, every \t reaches the channel
for _ in range(3):
    QApplication.sendEvent(w_f, QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_Tab),
                                          Qt.KeyboardModifier.NoModifier, "\t"))
    app.processEvents()
check("the 5 Tabs in a row: the focus is stable on the terminal", app.focusWidget() is w_f)
check("the 5 Tabs in a row: the 5 × \\t in the channel (the mc panels are switched)", len(th_f.sent) == 5,
      f"sent={th_f.sent!r}")

host_f.close()
app.processEvents()


# ════════════════════════════════════════════════════════════
# 3. Bracketed paste Ctrl+V (moved from v0.9.4)
# ════════════════════════════════════════════════════════════
print("== bracketed paste Ctrl+V ==")

scr, w = make_widget()
cb = app.clipboard()
cb.setText("one\r\ntwo\nthree")   # mixed EOL — normalized to \n
sent.clear()
press_key(w, Qt.Key.Key_V, mod=CTRL)
check("Ctrl+V: the multi-line buffer — a SINGLE block with the normalized line breaks",
      sent == [b"\x1b[200~one\ntwo\nthree\x1b[201~"], f"sent={sent!r}")

cb.setText("")
sent.clear()
press_key(w, Qt.Key.Key_V, mod=CTRL)
check("Ctrl+V with the empty buffer → nothing is sent", sent == [], f"sent={sent!r}")


# ════════════════════════════════════════════════════════════
# 4. Mouse selection + copy (synthetic QMouseEvent)
# ════════════════════════════════════════════════════════════
print("== mouse selection + copy ==")


def press_lmb(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                  Qt.KeyboardModifier.NoModifier))


def move_lmb(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
                                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier))


def release_lmb(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))


scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
cw, chh = w.cell_size
w.resize(cw * 20, chh * 5)

# a drag (0,0) → (2,4): row 0 entirely, row 1 entirely, row 2 up to col 4
press_lmb(w, 0, 0)
move_lmb(w, 1, 2)
release_lmb(w, 2, 4)
exp_sel = selection_cells((0, 0), (2, 4), 20)
check("the drag (0,0)→(2,4): the selection is active", w.has_selection())
check("the anchor/the end are stored as (row, col)",
      (w._sel_anchor, w._sel_active) == ((0, 0), (2, 4)),
      f"got=({w._sel_anchor}, {w._sel_active})")
check("the cells of the selection = selection_cells()", w._selected_cells() == exp_sel,
      f"got={w._selected_cells()}")

# Acceptance: copying a multi-line selection
exp_text = "hello world\nsecond line\nthird"   # line 2 cols 0..4 → 'third' (5 characters)
check("selected_text: the multi-line text, \\n, the trailing spaces are trimmed",
      w.selected_text() == exp_text, repr(w.selected_text()))

sent.clear()
ok = w.copy_selection()
check("copy_selection() → True", ok is True)
check("the clipboard == the multi-line selection", app.clipboard().text() == exp_text,
      repr(app.clipboard().text()))

# Ctrl+C with a selection — copies (the v0.9.3 semantics), nothing goes into the channel
sent.clear()
press_key(w, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C with the selection → nothing into the channel", sent == [], f"sent={sent!r}")
check("Ctrl+C with the selection → the clipboard is updated", app.clipboard().text() == exp_text)

# An inverted drag (2,4) → (0,0): the same cells
w.clear_selection()
press_lmb(w, 2, 4)
move_lmb(w, 1, 0)
release_lmb(w, 0, 0)
check("the inverted drag (2,4)→(0,0) → the same cells", w._selected_cells() == exp_sel,
      f"got={w._selected_cells()}")

# A simple click (without a drag) — the selection is reset; Ctrl+C is SIGINT again
w.clear_selection()
press_lmb(w, 1, 3)
release_lmb(w, 1, 3)
check("a plain click (without the drag) → no selection", not w.has_selection())
sent.clear()
press_key(w, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C after the plain click → b'\\x03' (kills the top)", sent == [b"\x03"],
      f"sent={sent!r}")

# A drag beyond the grid — clamped to the last cell (4,19)
w.clear_selection()
press_lmb(w, 0, 0)
far = QPointF(30 * cw, 30 * chh)   # far beyond the widget/grid boundary
w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, far, far, Qt.MouseButton.NoButton,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
check("the drag beyond the grid → the clamp to (4,19)", w._sel_active == (4, 19),
      f"got={w._sel_active}")
w.clear_selection()


# ════════════════════════════════════════════════════════════
# 5. The selection highlight (an offscreen render)
# ════════════════════════════════════════════════════════════
print("== selection highlight (offscreen) ==")


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


scr2, w2 = make_widget(cols=20, lines=5)   # an empty screen — a clean background
cw2, chh2 = w2.cell_size
w2.resize(cw2 * 20, chh2 * 5)
img_base = w2.grab().toImage()
px_base = pixel(img_base, 5 * cw2 + cw2 // 2, 2 * chh2 + chh2 // 2)

press_lmb(w2, 1, 0)
move_lmb(w2, 2, 5)
release_lmb(w2, 3, 9)   # (1,0)-(3,9): row 1 full width (20), row 2 full (20), row 3 up to col 9 (10)
img_sel = w2.grab().toImage()
px_sel = pixel(img_sel, 5 * cw2 + cw2 // 2, 2 * chh2 + chh2 // 2)
check("the highlight: the chosen pixel differs from the background", px_sel != px_base,
      f"base={px_base} sel={px_sel}")
r_, g_, b_ = px_sel
check("the highlight: the bluish overlay (b > r and b > g on the dark background)",
      b_ > r_ + 20 and b_ > g_ + 20, f"sel={px_sel}")
check("the paint stats: the cells of the selection are counted (20+20+10 = 50)",
      w2.last_paint_stats["selection_cells"] == 50, f"stats={w2.last_paint_stats}")


# ════════════════════════════════════════════════════════════
# 6. Integration: SSHTerminalWindow → TerminalWidget with the selection API
# ════════════════════════════════════════════════════════════
print("== SSHTerminalWindow integration ==")
import modules.ssh_terminal as ST
from models.server import ServerData


class _FakeTerm(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        pass  # without network


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeTerm
win = None
try:
    win = ST.SSHTerminalWindow(ServerData(id="rc2w", alias="T", host="127.0.0.1", user="u"), None)
    check("the window creates the TerminalWidget with the selection/copying API",
          isinstance(win.widget, TerminalWidget)
          and all(hasattr(win.widget, m) for m in
                  ("has_selection", "copy_selection", "selected_text",
                   "clear_selection", "_selected_cells")))
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass

finish()
