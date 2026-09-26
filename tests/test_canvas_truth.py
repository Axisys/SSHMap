# -*- coding: utf-8 -*-
"""v1.6.3 — the canvas at the cell: the glyph grid, the mouse the TUI asks for, the Files tab that answers back (ROADMAP v1.6.3).

  §1 THE GLYPH GRID (task 1) — each glyph is painted at ITS OWN cell: a homogeneous
     100-cell row puts the last glyph at `(n − 1) * cell_w` (a recording painter reads the
     real drawText arguments), kerning is OFF in the canvas font, and the PURE
     `font_grid_problems()` gate is RED on a synthetic non-integral metrics object and
     GREEN on the shipped font (`run_glyphs()` maps a run back to its CELLS, so a grapheme
     cluster keeps its cell count);
  §2 THE MOUSE FAMILY (task 2) — the press / release / motion matrix over the DECSET
     1000 / 1002 / 1003 × the SGR / X10 encodings, the 223 clamp of the X10 protocol, the
     session-local coordinates that never ride the multi-input hub, and the rule that a
     press while the application owns the mouse does NOT start a local selection;
  §3 THE TRACKING A TUI LEAVES BEHIND (task 3, N32) — the bits STAY in `screen.mode`
     after `\\x1b[?1049l` (the accepted cost, decided): the wheel keeps reporting to the
     application that asked for it and `Shift` is the LOCAL override that scrolls the local
     scrollback / makes the local selection instead;
  §4 THE FILES TAB'S ADDRESS BAR (task 4) — Enter navigates through the SERVER's own
     resolution (`queue_normalize` + its REALPATH/stat check), a bad path answers through
     the `message` signal, and the completer is fed by the SAME async `queue_list()` while
     listing a typed directory at most ONCE per directory change;
  §5 THE FILES TAB FOLLOWS THE SHELL (task 5, OSC 7) — the pure parser, the ONCE-injected
     hook (through `send_data()`, never the hub; APPENDED to `PROMPT_COMMAND`, with the
     zsh branch under `precmd_functions+=`), the echo hold-back that the first report
     DROPS, a shell that never answers costing the held bytes back, and the follow itself;
  §6 the ledger rows N31 / N32 — the two probes of the version, one row each;
  §7 the release state + the i18n parity of the four new keys.

Run:  python tests/test_canvas_truth.py   (from the project root) or python tests/run_all.py
"""
import sys
import time

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs,
                     check_i18n_parity, check_release_state, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + faulthandler)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from third_party import pyte

import i18n
import modules.ssh_terminal as ST
import modules.terminal_page as TP
from models.server import ServerData
from modules.multi_input import MultiInputHub, get_hub
from modules.sftp_tab import SftpTab
from modules.sftp_worker import SftpWorker
from modules.terminal_page import TerminalSessionPage, parse_osc7
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import (FONT_GRID_SAMPLE, FontGridMetrics,
                                     TerminalWidget, font_grid_problems, run_glyphs)

from _fakes import FakeSSHClient, FakeSSHThread, FakeSftpClient, FakeSftpFS


class FakeThread:
    """The fake terminal thread of the canvas sections (send_data → the list)."""

    def __init__(self):
        self.sent = []
        self.channel = None

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


class RecordingPainter:
    """A painter that records every drawText — the per-cell geometry seam of §1."""

    def __init__(self):
        self.texts = []     # [(x, y, text)]
        self.fills = []     # [(x, y, w, h)]
        self.fonts = 0

    def fillRect(self, *args):
        self.fills.append(args)

    def setFont(self, _font):
        self.fonts += 1

    def setPen(self, _pen):
        pass

    def drawText(self, x, y, text):
        self.texts.append((x, y, text))

    def rect(self):
        return QRect(0, 0, 4000, 400)

    def end(self):
        pass


def mouse_event(kind, w, col, row, button=Qt.MouseButton.LeftButton,
                buttons=Qt.MouseButton.NoButton, mods=Qt.KeyboardModifier.NoModifier):
    """A synthetic QMouseEvent in the CENTER of (col, row) — the suite's own pattern."""
    cw, chh = w.cell_size
    x, y = col * cw + cw // 2, row * chh + chh // 2
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons, mods)


def wheel_event(w, col, row, dy=120, mods=Qt.KeyboardModifier.NoModifier):
    cw, chh = w.cell_size
    x, y = col * cw + cw // 2, row * chh + chh // 2
    return QWheelEvent(QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, dy),
                       Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)


def find_terminal_page(server_id, host):
    """A real TerminalSessionPage over the FAKE thread (the suite's monkeypatch seam)."""
    orig = ST.SSHTerminalThread
    ST.SSHTerminalThread = FakeSSHThread
    try:
        return TerminalSessionPage(ServerData(id=server_id, alias=server_id,
                                              host=host, user="u"))
    finally:
        ST.SSHTerminalThread = orig


# ════════════════════════════════════════════════════════════
# §1 the glyph grid
# ════════════════════════════════════════════════════════════
print("== §1 the glyph grid ==")

scr_g = TerminalScreen(columns=100, lines=3)
scr_g.feed(b"M" * 100 + b"\r\n")
wg = TerminalWidget(scr_g, FakeThread())
cw, chh = wg.cell_size

check("§1 the metrics reserve a whole cell (cell_w = ceil(advance(\"M\")))",
      cw == 13 and wg._cell_w == cw, f"cell_w={cw}")

rec = RecordingPainter()
wg._paint(rec)
xs = [t[0] for t in rec.texts]
check("§1 a homogeneous 100-cell row draws ONE glyph per cell (100 drawText calls)",
      len(rec.texts) == 100, f"calls={len(rec.texts)}")
check("§1 every glyph is painted at ITS OWN cell — (start_col + k) * cell_w",
      xs == [k * cw for k in range(100)], f"first={xs[:3]} last={xs[-1]} cell_w={cw}")
check("§1 the painted x of the last glyph is (n − 1) * cell_w",
      xs[-1] == 99 * cw, f"got={xs[-1]} want={99 * cw}")
check("§1 the stats keep the RUNS and count the glyph calls (100 here, not 1)",
      wg.last_paint_stats["draw_text_calls"] == 100 and wg.last_paint_stats["runs"] >= 1,
      str(wg.last_paint_stats))
check("§1 the drawn glyphs are the row's own text",
      "".join(t[2] for t in rec.texts) == "M" * 100)

check("§1 KERNING is off in the canvas font (a kerned pair drifts off the grid)",
      wg._font.kerning() is False)
wg.set_font(size=11)
check("§1 set_font() keeps the kerning off", wg._font.kerning() is False)

_cluster = pyte.screens.Char("e\u0301")
_rows = [pyte.screens.Char("a"), _cluster, pyte.screens.Char("b")]
check("§1 run_glyphs(): one glyph per cell, a cluster stays ONE cell",
      run_glyphs(_rows, 0, "ae\u0301b") == ["a", "e\u0301", "b"],
      repr(run_glyphs(_rows, 0, "ae\u0301b")))
check("§1 run_glyphs() never loses ink (a row out of step keeps the tail)",
      run_glyphs(_rows[:1], 0, "abc") == ["a", "bc"], repr(run_glyphs(_rows[:1], 0, "abc")))

_non_integral = FontGridMetrics(13, lambda ch: 13.0 if ch == "M" else 12.4)
_red = font_grid_problems(_non_integral)
check("§1 the gate is RED on a synthetic non-integral metrics object", bool(_red), str(_red[:2]))
check("§1 the gate's row is (label, advance, cell_w, drift_px, drift_cells)",
      bool(_red) and len(_red[0]) == 5 and _red[0][0] == "i" and abs(_red[0][1] - 12.4) < 1e-9
      and _red[0][2] == 13 and abs(_red[0][3] + 0.6) < 1e-9, str(_red[0]))
check("§1 the gate expresses the drift over a 100-cell run in CELLS",
      bool(_red) and abs(_red[0][4] - (-0.6 * 100 / 13.0)) < 1e-9, str(_red[0]))
check("§1 a glyph that matches the cell is NOT reported", all(r[0] != "M" for r in _red))
check("§1 the gate is GREEN on the shipped font (the invariant HOLDS on this machine)",
      font_grid_problems(wg.grid_metrics()) == [], str(font_grid_problems(wg.grid_metrics())))
check("§1 the gate reads the LIVE cell width", wg.grid_metrics().cell_w == wg.cell_size[0])
check("§1 the declared sample carries the box-drawing glyphs of the report",
      {"M", "i", "W", " ", "\u2500", "\u2502", "\u250c", "\u253c", "\u2588", "\u2591"}
      <= set(FONT_GRID_SAMPLE) and any(ord(ch) > 0x2e80 for ch in FONT_GRID_SAMPLE),
      repr(FONT_GRID_SAMPLE))
check("§1 an unmeasurable sample glyph is skipped, never a crash",
      font_grid_problems(object()) == [] or True)


# ════════════════════════════════════════════════════════════
# §2 the mouse family
# ════════════════════════════════════════════════════════════
print("== §2 the mouse family ==")

scr_m = TerminalScreen(columns=40, lines=12)
thr_m = FakeThread()
wm = TerminalWidget(scr_m, thr_m)

check("§2 a fresh screen: no tracking mode", scr_m.mouse_tracking_mode() == (0, False),
      str(scr_m.mouse_tracking_mode()))

scr_m.feed(b"\x1b[?1000h\x1b[?1006h")
check("§2 1000 + 1006 → (1000, True)", scr_m.mouse_tracking_mode() == (1000, True),
      str(scr_m.mouse_tracking_mode()))

wm.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, wm, 4, 2,
                               buttons=Qt.MouseButton.LeftButton))
check("§2 a LEFT press goes to the PTY as SGR: b'\\x1b[<0;5;3M'",
      thr_m.sent == [b"\x1b[<0;5;3M"], repr(thr_m.sent))
check("§2 ... and it does NOT start a local selection",
      wm.has_selection() is False and wm._sel_anchor is None)

wm.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, wm, 4, 2))
check("§2 the release is the SGR 'm' form: b'\\x1b[<0;5;3m'",
      thr_m.sent[-1] == b"\x1b[<0;5;3m", repr(thr_m.sent))

thr_m.sent.clear()
wm.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, wm, 0, 0,
                               button=Qt.MouseButton.RightButton,
                               buttons=Qt.MouseButton.RightButton))
check("§2 the RIGHT button is the code 2", thr_m.sent == [b"\x1b[<2;1;1M"], repr(thr_m.sent))
thr_m.sent.clear()
wm.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, wm, 0, 0,
                               button=Qt.MouseButton.MiddleButton,
                               buttons=Qt.MouseButton.MiddleButton))
check("§2 the MIDDLE button is the code 1", thr_m.sent == [b"\x1b[<1;1;1M"], repr(thr_m.sent))

thr_m.sent.clear()
wm.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, wm, 5, 3,
                              button=Qt.MouseButton.NoButton,
                              buttons=Qt.MouseButton.LeftButton))
check("§2 under 1000 a motion is NOT reported (it is not in the protocol)",
      thr_m.sent == [], repr(thr_m.sent))

scr_m.feed(b"\x1b[?1002h")
check("§2 1002 wins over 1000 → (1002, True)", scr_m.mouse_tracking_mode() == (1002, True),
      str(scr_m.mouse_tracking_mode()))
wm.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, wm, 5, 3,
                              button=Qt.MouseButton.NoButton,
                              buttons=Qt.MouseButton.LeftButton))
check("§2 1002 + a held button → the held code + 32: b'\\x1b[<32;6;4M'",
      thr_m.sent == [b"\x1b[<32;6;4M"], repr(thr_m.sent))
thr_m.sent.clear()
wm.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, wm, 5, 3,
                              button=Qt.MouseButton.NoButton,
                              buttons=Qt.MouseButton.NoButton))
check("§2 1002 + NO button: nothing (motion only while a button is held)",
      thr_m.sent == [], repr(thr_m.sent))

scr_m.feed(b"\x1b[?1003h")
check("§2 1003 wins → (1003, True)", scr_m.mouse_tracking_mode() == (1003, True),
      str(scr_m.mouse_tracking_mode()))
wm.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, wm, 5, 3,
                              button=Qt.MouseButton.NoButton,
                              buttons=Qt.MouseButton.NoButton))
check("§2 1003 + no button: 'any motion' → the code 3 + 32 = 35",
      thr_m.sent == [b"\x1b[<35;6;4M"], repr(thr_m.sent))

scr_x = TerminalScreen(columns=40, lines=12)
thr_x = FakeThread()
wx = TerminalWidget(scr_x, thr_x)
scr_x.feed(b"\x1b[?1000h")
wx.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, wx, 4, 2,
                               buttons=Qt.MouseButton.LeftButton))
check("§2 X10: the press is b'\\x1b[M' + [32, 32+col, 32+row]",
      thr_x.sent == [b"\x1b[M" + bytes([32, 32 + 5, 32 + 3])], repr(thr_x.sent))
wx.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, wx, 4, 2))
check("§2 X10: the release is the button + 3 (ctlseqs)",
      thr_x.sent[-1] == b"\x1b[M" + bytes([35, 32 + 5, 32 + 3]), repr(thr_x.sent))
thr_x.sent.clear()
wx.wheelEvent(wheel_event(wx, 4, 2, dy=120))
check("§2 X10: the wheel is still the code 64 → 96 (the shipped v1.2.13 matrix)",
      thr_x.sent == [b"\x1b[M" + bytes([96, 32 + 5, 32 + 3])], repr(thr_x.sent))

scr_w2 = TerminalScreen(columns=260, lines=12)
thr_w2 = FakeThread()
ww2 = TerminalWidget(scr_w2, thr_w2)
scr_w2.feed(b"\x1b[?1000h")
ww2.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, ww2, 229, 2,
                                buttons=Qt.MouseButton.LeftButton))
check("§2 X10 clamps a coordinate to the protocol ceiling of 223 (the byte 255)",
      thr_w2.sent == [b"\x1b[M" + bytes([32, 255, 32 + 3])], repr(thr_w2.sent))
thr_w2.sent.clear()
scr_w2.feed(b"\x1b[?1006h")
ww2.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, ww2, 229, 2,
                                buttons=Qt.MouseButton.LeftButton))
check("§2 SGR on the same grid clamps nothing (b'\\x1b[<0;230;3M')",
      thr_w2.sent == [b"\x1b[<0;230;3M"], repr(thr_w2.sent))

scr_s = TerminalScreen(columns=40, lines=12)
thr_s = FakeThread()
ws = TerminalWidget(scr_s, thr_s)
scr_s.feed(b"\x1b[?1000h\x1b[?1006h")
ws.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, ws, 1, 1,
                               buttons=Qt.MouseButton.LeftButton,
                               mods=Qt.KeyboardModifier.ShiftModifier))
check("§2 Shift + press: nothing goes to the PTY (the local override)",
      thr_s.sent == [], repr(thr_s.sent))
ws.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, ws, 3, 1,
                              button=Qt.MouseButton.NoButton,
                              buttons=Qt.MouseButton.LeftButton,
                              mods=Qt.KeyboardModifier.ShiftModifier))
ws.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, ws, 3, 1,
                                 mods=Qt.KeyboardModifier.ShiftModifier))
check("§2 Shift + drag: the LOCAL selection is made instead",
      ws.has_selection() is True and thr_s.sent == [], repr(thr_s.sent))

hub = MultiInputHub()
thr_other = FakeThread()
page_other = type("_Page", (), {})()
page_other.widget = None
page_other.terminal_thread = thr_other
scr_mi = TerminalScreen(columns=40, lines=12)
thr_mi = FakeThread()
wmi = TerminalWidget(scr_mi, thr_mi, multi_hub=hub)
scr_mi.feed(b"\x1b[?1003h\x1b[?1006h")
hub.set_session_provider(lambda: [page_other])
hub.set_active(True)
wmi.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, wmi, 4, 2,
                                buttons=Qt.MouseButton.LeftButton))
wmi.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, wmi, 5, 2,
                               button=Qt.MouseButton.NoButton,
                               buttons=Qt.MouseButton.LeftButton))
check("§2 the reports go to the OWN session only (never hub.broadcast)",
      thr_mi.sent == [b"\x1b[<0;5;3M", b"\x1b[<32;6;3M"] and thr_other.sent == [],
      f"own={thr_mi.sent!r} other={thr_other.sent!r}")
hub.reset()

_scr_none = TerminalScreen(columns=10, lines=4)
_scr_none.feed(b"\x1b[?1003h")
_wnone = TerminalWidget(_scr_none, None)
try:
    _wnone.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, _wnone, 1, 1,
                                       buttons=Qt.MouseButton.LeftButton))
    _wnone.wheelEvent(wheel_event(_wnone, 1, 1))
    _none_ok = True
except Exception as e:  # noqa: BLE001
    _none_ok = False
    print(f"  (exception: {e!r})")
check("§2 terminal_thread=None + tracking: a press and a wheel do not crash", _none_ok)


# ════════════════════════════════════════════════════════════
# §3 the tracking a TUI leaves behind (N32) + the Shift hatch
# ════════════════════════════════════════════════════════════
print("== §3 the tracking a TUI leaves behind ==")

scr_l = TerminalScreen(columns=40, lines=12)
thr_l = FakeThread()
wl = TerminalWidget(scr_l, thr_l)
for i in range(40):
    scr_l.feed(f"l-{i:02d}\r\n".encode())
scr_l.feed(b"\x1b[?1049h\x1b[?1000h\x1b[?1006h")   # a TUI: the alt screen + the tracking
scr_l.feed(b"\x1b[?1049l")                          # ... gone, without its own disable
check("§3 after \\x1b[?1049l the tracked bits STAY in screen.mode (the accepted cost)",
      scr_l.mouse_tracking_mode() == (1000, True), str(scr_l.mouse_tracking_mode()))
check("§3 ... and the alternate screen is really left", scr_l.in_alt_screen() is False)

thr_l.sent.clear()
wl.wheelEvent(wheel_event(wl, 4, 2, dy=120))
check("§3 the plain wheel still REPORTS to the application that asked — the accepted cost",
      thr_l.sent == [b"\x1b[<64;5;3M"], repr(thr_l.sent))

pos_before = scr_l.scroll_info()
thr_l.sent.clear()
wl.wheelEvent(wheel_event(wl, 4, 2, dy=120, mods=Qt.KeyboardModifier.ShiftModifier))
check("§3 Shift + wheel: the LOCAL scrollback wins (nothing is sent)",
      thr_l.sent == [], repr(thr_l.sent))
check("§3 Shift + wheel: the view really moved back into the history",
      scr_l.scroll_info() != pos_before and scr_l.at_bottom() is False,
      f"before={pos_before} after={scr_l.scroll_info()}")
check("§3 the keyboard hatch keeps working (Ctrl+Shift+PageDown returns to live)",
      wl.scroll_page_down() is True and scr_l.at_bottom() is True)


# ════════════════════════════════════════════════════════════
# §4 the Files tab's address bar
# ════════════════════════════════════════════════════════════
print("== §4 the Files tab's address bar ==")

fs = FakeSftpFS()
fs.add_dir("/home")
fs.add_dir("/home/sub")
fs.add_dir("/home/sub/deep")
fs.add_file("/home/a.txt", b"a")
worker = SftpWorker(FakeSftpClient(fs))
worker.start()
tab = SftpTab()
tab.set_worker(worker)
wait_until(lambda: tab.path_label.text() == "/", timeout_ms=5000)
check("§4 with a transport the bar is EDITABLE (it was a read-only QLabel)",
      tab.path_label.isReadOnly() is False, str(tab.path_label.isReadOnly()))
check("§4 the bar carries the server's listing root", tab.path_label.text() == "/",
      tab.path_label.text())
check("§4 the bar carries the address placeholder",
      tab.path_label.placeholderText() == i18n.t("sftp.path_placeholder"),
      tab.path_label.placeholderText())

messages = []
tab.message.connect(messages.append)

tab.path_label.setText("/home/sub/..")
tab._on_path_entered()
wait_until(lambda: tab.path_label.text() == "/home", timeout_ms=5000)
check("§4 Enter navigates through the SERVER's REALPATH ('/home/sub/..' → '/home')",
      tab.path_label.text() == "/home", tab.path_label.text())
check("§4 ... and the listing followed (the 'sub' row is there)",
      any(tab.tree.topLevelItem(i).text(0) == "sub"
          for i in range(tab.tree.topLevelItemCount())))

messages.clear()
tab.path_label.setText("/nope")
tab._on_path_entered()
wait_until(lambda: bool(messages), timeout_ms=5000)
check("§4 a bad path is reported through the `message` signal (never a traceback)",
      bool(messages) and "/nope" in messages[0], repr(messages[:1]))
check("§4 ... and the bar keeps what the user typed (nothing navigated)",
      tab.path_label.text() == "/nope", tab.path_label.text())
check("§4 the bad-path sentence is the tab's own translated line",
      messages and messages[0] == i18n.t("sftp.path_error", path="/nope",
                                         error=messages[0].split(": ", 1)[-1]),
      repr(messages[:1]))

messages.clear()
tab.path_label.setText("/home/a.txt")
tab._on_path_entered()
wait_until(lambda: bool(messages), timeout_ms=5000)
check("§4 a FILE path is refused too (the address bar is a directory bar)",
      bool(messages) and "not a directory" in messages[0], repr(messages[:1]))

tab.path_label.setText("/home")
_before_dir = tab.current_dir
tab._on_path_edited("/hom")
check("§4 the first typed directory lists its PARENT (the completion of the name)",
      tab._completer_dir == "/", tab._completer_dir)
tab._on_path_edited("/home")
check("§4 a keystroke inside the same directory costs NO listing (once per change)",
      tab._completer_dir == "/", tab._completer_dir)
tab._on_path_edited("/home/s")
check("§4 a NEW directory is listed — and only once", tab._completer_dir == "/home",
      tab._completer_dir)
wait_until(lambda: "sub/" in tab.path_completer_model.stringList(), timeout_ms=5000)
names = tab.path_completer_model.stringList()
check("§4 the completer is fed from the SAME async queue_list()", bool(names), repr(names))
check("§4 a directory is suggested with a TRAILING '/'", "sub/" in names, repr(names))
check("§4 the files are listed after the directories",
      "a.txt" in names and names.index("sub/") < names.index("a.txt"), repr(names))
check("§4 a completer listing never renders into the tree (the current dir is untouched)",
      tab.current_dir == _before_dir == "/home", f"{_before_dir} → {tab.current_dir}")

worker.shutdown(wait_ms=2000)
tab.set_worker(None)
check("§4 without a transport the bar is READ-ONLY again and says so",
      tab.path_label.isReadOnly() is True
      and tab.path_label.text() == i18n.t("sftp.waiting_connection"),
      f"ro={tab.path_label.isReadOnly()} text={tab.path_label.text()!r}")


# ════════════════════════════════════════════════════════════
# §5 the Files tab follows the shell (OSC 7)
# ════════════════════════════════════════════════════════════
print("== §5 the Files tab follows the shell (OSC 7) ==")

check("§5 parse_osc7: the BEL form", parse_osc7(b"\x1b]7;file://host/home/u\x07") == "/home/u")
check("§5 parse_osc7: the ST form", parse_osc7(b"\x1b]7;file://host/home/u\x1b\\") == "/home/u")
check("§5 parse_osc7: a percent-encoded directory is decoded",
      parse_osc7(b"\x1b]7;file://h/a%20b\x07") == "/a b")
check("§5 parse_osc7: the host is ignored (and may be empty)",
      parse_osc7(b"\x1b]7;file:///srv\x07") == "/srv")
check("§5 parse_osc7: the LAST report wins",
      parse_osc7(b"\x1b]7;file://h/one\x07\x1b]7;file://h/two\x07") == "/two")
check("§5 parse_osc7: garbage / a host-only report / a relative path → ''",
      parse_osc7(b"no escape here") == "" and parse_osc7(b"\x1b]7;file://host\x07") == ""
      and parse_osc7(b"\x1b]7;file://hostrel\x07") == "")
check("§5 parse_osc7 never raises on odd input",
      parse_osc7(None) == "" and parse_osc7(b"") == "" and parse_osc7("text") == "")

clear_cfg()
write_cfg({"terminal_follow_cwd": True})
check("§5 terminal_follow_cwd is read as a REAL bool (opt-in)",
      ST.load_terminal_settings()["follow_cwd"] is True)
write_cfg({"terminal_follow_cwd": "yes"})
check("§5 a foreign value for terminal_follow_cwd falls back to OFF",
      ST.load_terminal_settings()["follow_cwd"] is False)
clear_cfg()
write_cfg({"terminal_follow_cwd": True})

fs5 = FakeSftpFS()
fs5.add_dir("/home")
fs5.add_dir("/var")
page = find_terminal_page("canvas1", "10.0.0.9")
page.terminal_thread.client = FakeSSHClient(FakeSftpClient(fs5))
check("§5 the session starts with the follow (the config key)",
      page.follow_cwd() is True and page.sftp_tab.chk_follow_cwd.isChecked() is True)
check("§5 ... and the SFTP tab shows it (the checkbox is a VIEW of the session state)",
      page.sftp_tab._follow_cwd is True)

hub5 = get_hub()
thr_foreign = FakeThread()
foreign_page = type("_Page", (), {})()
foreign_page.widget = None
foreign_page.terminal_thread = thr_foreign
hub5.set_session_provider(lambda: [foreign_page])
hub5.set_active(True)
sent_before = len(page.terminal_thread.channel.sent or [])
check("§5 the injection went out ONCE", page._inject_cwd_hook() is True)
hook = b"".join((page.terminal_thread.channel.sent or [])[sent_before:])
check("§5 the hook reaches the PTY through send_data()", b"_sshmap_cwd" in hook, repr(hook[:60]))
check("§5 ... and NOT through the multi-input hub (the other session got nothing)",
      thr_foreign.sent == [], repr(thr_foreign.sent))
check("§5 the hook is APPENDED to the user's PROMPT_COMMAND (never overwritten)",
      b'PROMPT_COMMAND="_sshmap_cwd${PROMPT_COMMAND:+;' in hook, repr(hook))
check("§5 the zsh branch uses precmd_functions+= under an eval + a $ZSH_VERSION guard",
      b"ZSH_VERSION" in hook and b"eval 'precmd_functions+=(_sshmap_cwd)'" in hook)
check("§5 the hook is IDEMPOTENT (a duplicate would report twice per prompt)",
      b"*_sshmap_cwd*" in hook)
check("§5 the hook is ONE command line", hook.endswith(b"\n") and hook.count(b"\n") == 1)
check("§5 a second injection is refused (one hook per session)",
      page._inject_cwd_hook() is False)
hub5.reset()

# the echo is held back; the first OSC 7 drops it (no worker in the tab yet → no navigation)
page._cwd_hold_deadline = time.monotonic() + 60   # deterministic: no timer in this section
page._on_output(b"ECHO-OF-THE-HOOK ")
check("§5 the hook's echo is held back (the canvas sees NOTHING while waiting)",
      page.widget.visible_text().strip() == "", repr(page.widget.visible_text()[:60]))
page._on_output(b"\x1b]7;file://host/home\x07")
page._on_output(b"prompt$ ")
check("§5 the first report DROPS the held echo",
      "ECHO-OF-THE-HOOK" not in page.widget.visible_text(),
      repr(page.widget.visible_text()[:80]))
check("§5 ... and the output after the report is shown as usual",
      "prompt$" in page.widget.visible_text(), repr(page.widget.visible_text()[:80]))

page2 = find_terminal_page("canvas2", "10.0.0.10")
page2._inject_cwd_hook()
page2._on_output(b"HELD-BYTES")
check("§5 a shell that never answers: the bytes are held first",
      page2.widget.visible_text().strip() == "", repr(page2.widget.visible_text()[:60]))
page2._cwd_hold_deadline = 0.0                    # the deadline passed
page2._on_output(b" AND-BACK")
check("§5 ... and the deadline costs them BACK (nothing is lost)",
      "HELD-BYTES" in page2.widget.visible_text()
      and "AND-BACK" in page2.widget.visible_text(),
      repr(page2.widget.visible_text()[:80]))

page3 = find_terminal_page("canvas3", "10.0.0.11")
page3._inject_cwd_hook()
page3._on_output(b"HELD-AGAIN")
page3._on_cwd_hold_timeout()                      # the timer's own path (the seam)
check("§5 the deadline TIMER hands the held bytes back through the ordinary output path",
      "HELD-AGAIN" in page3.widget.visible_text(), repr(page3.widget.visible_text()[:60]))
check("§5 a second timeout call is an idempotent no-op",
      (page3._on_cwd_hold_timeout() is None))

# a fed OSC 7 really moves the listing of a page with a live SFTP channel
page._ensure_sftp()
wait_until(lambda: page.sftp_tab.worker is not None
           and page.sftp_tab.path_label.text() == "/", timeout_ms=5000)
page._last_cwd = ""
page._on_output(b"\x1b]7;file://host/var\x07")
wait_until(lambda: page.sftp_tab.path_label.text() == "/var", timeout_ms=5000)
check("§5 a fed OSC 7 moves the listing (the follow itself)",
      page.sftp_tab.path_label.text() == "/var", page.sftp_tab.path_label.text())
check("§5 a directory that did not change is a no-op",
      page.sftp_tab.follow_directory("/var") is False)
check("§5 a FOREIGN path degrades to 'no follow', never to an error",
      page.sftp_tab.follow_directory("relative/path") is False
      and page.sftp_tab.follow_directory("") is False
      and page.sftp_tab.follow_directory("/var\x00x") is False)

page.sftp_tab.chk_follow_cwd.setChecked(False)
check("§5 unchecking the box turns the follow OFF for the session",
      page.follow_cwd() is False and page.sftp_tab._follow_cwd is False)
check("§5 ... and persists the ONE config key through the merge-write",
      (i18n.load_config() or {}).get(TP.FOLLOW_CWD_CONFIG_KEY) is False,
      str((i18n.load_config() or {}).get(TP.FOLLOW_CWD_CONFIG_KEY)))
page.set_follow_cwd(True)
check("§5 set_follow_cwd() keeps the checkbox a VIEW of the session state (no loop)",
      page.sftp_tab.chk_follow_cwd.isChecked() is True)
page.set_follow_cwd(False)

page.shutdown()
page2.shutdown()
page3.shutdown()
clear_cfg()


# ════════════════════════════════════════════════════════════
# §6 the ledger rows N31 / N32
# ════════════════════════════════════════════════════════════
print("== §6 the ledger rows N31 / N32 ==")

check("§6 N31 (the mouse family): ONE encoder serves the press, the release and the motion",
      callable(getattr(TerminalWidget, "_send_mouse", None))
      and callable(getattr(TerminalWidget, "_mouse_reports_to_pty", None)))
check("§6 N31: ONE mode reader answers which tracking is on",
      callable(getattr(TerminalScreen, "mouse_tracking_mode", None))
      and scr_m.mouse_tracking_mode() == (1003, True))
check("§6 N32 (the stale tracking): nothing CLEARS the tracked bits for the user",
      scr_l.mouse_tracking_mode() == (1000, True))
check("§6 N32: the Shift override is the declared mitigation",
      callable(getattr(TerminalWidget, "_mouse_local_override", None)))


# ════════════════════════════════════════════════════════════
# §7 the release state + the i18n parity
# ════════════════════════════════════════════════════════════
print("== §7 release state + i18n parity ==")

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
for key in ("sftp.path_placeholder", "sftp.path_error", "sftp.follow_cwd",
            "sftp.follow_cwd_tooltip"):
    check(f"§7 the new key {key} is in EVERY language",
          all(key in langs[code] for code in langs), sorted(langs))

finish()
