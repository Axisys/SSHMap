# -*- coding: utf-8 -*-
"""v1.2.13 — the mouse wheel in the full-screen TUI (SGR/X10 passthrough) (ROADMAP v1.2.13, PYTE82_AUDIT.md batch C).

  * The headless matrix of the modes: the DECSET 1000/1002/1003 × 1006 — mouse_tracking() ==
    (enabled, sgr); the 1006 ALONE → (False, True) (the xterm semantics: 1006 — only
    the encoding of the reports, without the 1000/1002/1003 there are no mouse events — the correction
    of the acceptance of the ROADMAP); \x1b[?…l — the disable; the RIS (\x1bc) clears the modes;
    the htop-style toggle during the session (the read on every event — no cache);
  * The offscreen Qt with a fake thread (the pattern test_terminal_input.py): the wheel with
    1006 → into send_data goes EXACTLY \x1b[<64;{col};{row}M (up=64, down=65 — ctlseqs:
    the buttons 4/5 = the event codes of the buttons 1/2 + 64), with the 1002 without 1006 → X10 \x1b[M +
    [96|97, 32+col, 32+row]; the coordinates are clamped to the grid; the X10 additionally — in the
    protocol limit 223 (=255−32, the ctlseqs "Extended coordinates": the extensions only through
    the UTF-8 1005 / the SGR 1006);
  * The alt without the tracking → a no-op (the regression v1.2.12: nothing in the PTY, the scrollback is untouched,
    the event is not consumed — the propagation is harmless, no ancestor-QScrollArea);
  * The passthrough is prior to terminal_wheel="off"; "off" without the tracking — the event.ignore
    + nothing is sent (the regression v1.1.2RC3);
  * The scrollback regression (without the modes): up → prev_page, down → next_page;
  * The multi-input: the bytes of the wheel do NOT pass the hub.broadcast (the coordinates are session-local)
    — with the active hub and a foreign session in the registry only the source receives them;
  * terminal_thread=None + the tracking — without exceptions.

Run:  python tests/test_terminal_mouse.py   (from the project root) or python tests/run_all.py
"""
import sys

from _common import (bootstrap, check, finish, check_release_state, load_i18n_langs,
                     check_i18n_parity)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QPointF, QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from third_party import pyte          # v1.3rc1: the fork (MANIFEST.md)

from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from modules.multi_input import MultiInputHub


class FakeThread:
    """The fake SSHTerminalThread: send_data(b) — into the list (the pattern of test_terminal_input.py)."""

    def __init__(self):
        self.sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


def make_wheel(pos_x, pos_y, angle_dy=120):
    """The synthetic QWheelEvent in the coordinates of the widget (the pattern of test_terminal_scroll.py)."""
    return QWheelEvent(QPointF(pos_x, pos_y), QPointF(pos_x, pos_y), QPoint(0, 0),
                       QPoint(0, angle_dy), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)


# ════════════════════════════════════════════════════════════
# 1. Headless: the DECSET 1000/1002/1003 × 1006 mouse-mode matrix
# ════════════════════════════════════════════════════════════
print("== headless: mouse_tracking() mode matrix ==")

scr = TerminalScreen(columns=80, lines=24)
check("a fresh screen: mouse_tracking() == (False, False)",
      scr.mouse_tracking() == (False, False), str(scr.mouse_tracking()))

# 1006 ALONE — encoding, not tracking (the corrected acceptance, ROADMAP v1.2.13)
scr.feed(b"\x1b[?1006h")
check("the 1006 alone → (False, True): the SGR-encoding without the 1000/1002/1003 tracking is not enabled",
      scr.mouse_tracking() == (False, True), str(scr.mouse_tracking()))
scr.feed(b"\x1b[?1006l")

# The matrix: every tracking mode × 1006
for n in (1000, 1002, 1003):
    s = TerminalScreen(columns=40, lines=10)
    s.feed(f"\x1b[?{n}h".encode())
    check(f"the DECSET {n} alone → (True, False)", s.mouse_tracking() == (True, False),
          str(s.mouse_tracking()))
    s.feed(b"\x1b[?1006h")
    check(f"the DECSET {n}+1006 → (True, True)", s.mouse_tracking() == (True, True),
          str(s.mouse_tracking()))
    s.feed(f"\x1b[?{n}l".encode())
    check(f"the {n} is off, the 1006 remains → (False, True)", s.mouse_tracking() == (False, True),
          str(s.mouse_tracking()))
    s.feed(b"\x1b[?1006l")
    check(f"all are off → (False, False)", s.mouse_tracking() == (False, False),
          str(s.mouse_tracking()))

# Several tracking modes at once
s2 = TerminalScreen(columns=40, lines=10)
s2.feed(b"\x1b[?1000h\x1b[?1002h")
check("1000+1002 → (True, False)", s2.mouse_tracking() == (True, False), str(s2.mouse_tracking()))

# the htop style: enabling/disabling during a session — a read per event (no cache)
s3 = TerminalScreen(columns=40, lines=10)
s3.feed(b"\x1b[?1003h\x1b[?1006h")
check("the htop-start: the 1003+1006 → (True, True)", s3.mouse_tracking() == (True, True),
      str(s3.mouse_tracking()))
s3.feed(b"\x1b[?1003l\x1b[?1006l")
check("the htop-exit: the repeated read of the same screen → (False, False) (no cache)",
      s3.mouse_tracking() == (False, False), str(s3.mouse_tracking()))

# RIS (\x1bc — NOT \x1b[c): a full reset clears the mouse modes
s4 = TerminalScreen(columns=40, lines=10)
s4.feed(b"\x1b[?1003h\x1b[?1006h")
s4.feed(b"\x1bc")
check("RIS (\\x1bc): the mouse-modes are reset → (False, False)",
      s4.mouse_tracking() == (False, False), str(s4.mouse_tracking()))


# ════════════════════════════════════════════════════════════
# 2. Offscreen Qt: SGR passthrough (exactly \x1b[<64;{col};{row}M)
# ════════════════════════════════════════════════════════════
print("== offscreen: SGR passthrough ==")

scrw = TerminalScreen(columns=40, lines=12)
for i in range(30):
    scrw.feed(f"line-{i:02d}\r\n".encode())   # the history exists (the scrollback regression below)
thread = FakeThread()
scrw.feed(b"\x1b[?1000h\x1b[?1006h")
w = TerminalWidget(scrw, thread)
cw, chh = w.cell_size

# The center of the cell (col=5, row=3): the pixels (4*cw + cw//2, 2*chh + chh//2) → x//cw+1=5, y//chh+1=3
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
w.wheelEvent(ev)
check("the wheel up at the 1006: exactly b'\\x1b[<64;5;3M'", thread.sent == [b"\x1b[<64;5;3M"],
      repr(thread.sent))
check("the event is consumed (accept)", ev.isAccepted() is True)

thread.sent.clear()
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=-120)
w.wheelEvent(ev)
check("the wheel down at the 1006: exactly b'\\x1b[<65;5;3M'", thread.sent == [b"\x1b[<65;5;3M"],
      repr(thread.sent))

check("the scrollback is untouched (at_bottom)", scrw.at_bottom() is True)

# The mouse position BEYOND the grid (the widget is wider/taller than the grid by the metric rounding remainder) → clamped to [1..40]×[1..12]
thread.sent.clear()
ev = make_wheel(cw * 42 + cw // 2, chh * 15 + chh // 2, angle_dy=120)
w.wheelEvent(ev)
check("the coordinates beyond the grid are clamped: b'\\x1b[<64;40;12M'", thread.sent == [b"\x1b[<64;40;12M"],
      repr(thread.sent))


# ════════════════════════════════════════════════════════════
# 3. Offscreen Qt: X10-passthrough (\x1b[M + [96|97, 32+col, 32+row])
# ════════════════════════════════════════════════════════════
print("== offscreen: X10 passthrough ==")

scrx = TerminalScreen(columns=40, lines=12)
threadx = FakeThread()
scrx.feed(b"\x1b[?1002h")   # tracking WITHOUT 1006 → X10
wx = TerminalWidget(scrx, threadx)
cw, chh = wx.cell_size

ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wx.wheelEvent(ev)
check("the X10 up: exactly b'\\x1b[M' + [96, 37, 35] ",
      threadx.sent == [b"\x1b[M" + bytes([96, 32 + 5, 32 + 3])], repr(threadx.sent))

threadx.sent.clear()
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=-120)
wx.wheelEvent(ev)
check("the X10 down: exactly b'\\x1b[M' + [97, 37, 35] ",
      threadx.sent == [b"\x1b[M" + bytes([97, 32 + 5, 32 + 3])], repr(threadx.sent))

check("the scrollback is untouched (at_bottom)", scrx.at_bottom() is True)


# ════════════════════════════════════════════════════════════
# 4. The X10 protocol limit of 223 (an ultrawide grid of >223 columns)
# ════════════════════════════════════════════════════════════
print("== X10 protocol limit 223 (ultrawide grid) ==")

scrwide = TerminalScreen(columns=260, lines=12)   # the grid is wider than the protocol limit
threadw = FakeThread()
scrwide.feed(b"\x1b[?1000h")   # X10 (without 1006)
ww = TerminalWidget(scrwide, threadw)
cw, chh = ww.cell_size

# The cell col=230 (>223) → clamped to 223: the byte = 32+223 = 255
ev = make_wheel(cw * 229 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
ww.wheelEvent(ev)
check("the X10: col=230 > 223 → the clamp to the protocol limit (the byte 255)",
      threadw.sent == [b"\x1b[M" + bytes([96, 255, 35])], repr(threadw.sent))

# SGR on the same grid — no clamping (no limits)
threadw.sent.clear()
scrwide.feed(b"\x1b[?1006h")
ev = make_wheel(cw * 229 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
ww.wheelEvent(ev)
check("the SGR on the same wide grid: without the clamp — b'\\x1b[<64;230;3M'",
      threadw.sent == [b"\x1b[<64;230;3M"], repr(threadw.sent))


# ════════════════════════════════════════════════════════════
# 5. The alt screen WITHOUT tracking → a no-op (the v1.2.12 gate regression)
# ════════════════════════════════════════════════════════════
print("== alt screen without tracking: no-op ==")

scra = TerminalScreen(columns=40, lines=12)
threada = FakeThread()
wa = TerminalWidget(scra, threada)
for i in range(30):
    scra.feed(f"a-{i:02d}\r\n".encode())
pos_before = scra.scroll_info()
scra.feed(b"\x1b[?1049h")   # the alt screen, the mouse modes are NOT enabled
check("in the alt (the in_alt_screen True)", scra.in_alt_screen() is True)

ev = make_wheel(5, 5, angle_dy=120)
ev.setAccepted(False)   # a synthetic QWheelEvent is born accepted=True (a PySide6 quirk) — we reset it for observation
wa.wheelEvent(ev)
check("the alt without the tracking: nothing goes into the PTY", threada.sent == [], repr(threada.sent))
check("the alt without the tracking: the scrollback is untouched", scra.scroll_info() == pos_before)
check("the alt without the tracking: the event is NOT consumed (the propagation, as in the v1.2.12)",
      ev.isAccepted() is False)
scra.feed(b"\x1b[?1049l")

# Alt + tracking → passthrough (a TUI with mouse modes owns the grid and awaits reports)
threada.sent.clear()
scra.feed(b"\x1b[?1049h\x1b[?1003h\x1b[?1006h")
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wa.wheelEvent(ev)
check("the alt + the tracking: the wheel goes into the PTY (SGR)", threada.sent == [b"\x1b[<64;5;3M"],
      repr(threada.sent))
scra.feed(b"\x1b[?1003l\x1b[?1006l\x1b[?1049l")


# ════════════════════════════════════════════════════════════
# 6. Passthrough takes priority over terminal_wheel="off" (+ the "off" regression)
# ════════════════════════════════════════════════════════════
print("== wheel_mode='off' vs passthrough ==")

scro = TerminalScreen(columns=40, lines=12)
threado = FakeThread()
wo = TerminalWidget(scro, threado, wheel_mode="off")
for i in range(30):
    scro.feed(f"o-{i:02d}\r\n".encode())
scro.feed(b"\x1b[?1000h\x1b[?1006h")

ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wo.wheelEvent(ev)
check("the tracking + 'off': the passthrough is prior — the bytes in the PTY",
      threado.sent == [b"\x1b[<64;5;3M"], repr(threado.sent))
check("... and the scrollback is untouched", scro.at_bottom() is True)

# 'off' WITHOUT tracking — the v1.1.2RC3 regression: event.ignore, nothing is sent, no scrolling
scro.feed(b"\x1b[?1000l\x1b[?1006l")
threado.sent.clear()
pos_before = scro.scroll_info()
ev = make_wheel(5, 5, angle_dy=120)
wo.wheelEvent(ev)
check("'off' without the tracking: the event.ignore (not consumed)", ev.isAccepted() is False)
check("'off' without the tracking: nothing goes into the PTY", threado.sent == [], repr(threado.sent))
check("'off' without the tracking: the scrollback is untouched", scro.scroll_info() == pos_before)


# ════════════════════════════════════════════════════════════
# 7. Scrollback regression (without mouse modes — the v1.0RC3 behaviour)
# ════════════════════════════════════════════════════════════
print("== scrollback regression (no modes) ==")

scrs = TerminalScreen(columns=40, lines=12)
threads_ = FakeThread()
ws = TerminalWidget(scrs, threads_)
for i in range(30):
    scrs.feed(f"s-{i:02d}\r\n".encode())

ev = make_wheel(5, 5, angle_dy=120)
ws.wheelEvent(ev)
check("without the modes: the wheel up → the scrollback (not the at_bottom)", scrs.at_bottom() is False)
check("without the modes: nothing goes into the PTY", threads_.sent == [], repr(threads_.sent))

ev = make_wheel(5, 5, angle_dy=-120)
ws.wheelEvent(ev)
check("the wheel down → the return to the live line", scrs.at_bottom() is True)


# ════════════════════════════════════════════════════════════
# 8. Multi Input: wheel bytes do NOT pass the broadcast (session-local coordinates)
# ════════════════════════════════════════════════════════════
print("== multi-input: wheel bypasses hub.broadcast ==")

hub = MultiInputHub()   # an explicit hub — a test seam (isolation from the application singleton)
thread_other = FakeThread()
page_other = type("_Page", (), {})()
page_other.widget = None                    # NOT the source → the broadcast would not pass it
page_other.terminal_thread = thread_other

scrmi = TerminalScreen(columns=40, lines=12)
threadmi = FakeThread()
wmi = TerminalWidget(scrmi, threadmi, multi_hub=hub)
for i in range(30):
    scrmi.feed(f"m-{i:02d}\r\n".encode())
scrmi.feed(b"\x1b[?1000h\x1b[?1006h")

hub.set_session_provider(lambda: [page_other])
hub.set_active(True)
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wmi.wheelEvent(ev)
check("the wheel: the bytes in its OWN session", threadmi.sent == [b"\x1b[<64;5;3M"], repr(threadmi.sent))
check("the wheel: is NOT broadcast'ed into the other sessions (the coordinates are session-local)",
      thread_other.sent == [], repr(thread_other.sent))
hub.reset()


# ════════════════════════════════════════════════════════════
# 9. terminal_thread=None + tracking — no exceptions
# ════════════════════════════════════════════════════════════
print("== thread=None guard ==")

scrn = TerminalScreen(columns=40, lines=12)
wn = TerminalWidget(scrn, None)
scrn.feed(b"\x1b[?1003h")   # X10 tracking, no thread
try:
    wn.wheelEvent(make_wheel(5, 5, angle_dy=120))
    ok = True
except Exception as e:  # noqa: BLE001
    ok = False
    print(f"  (exception: {e!r})")
check("terminal_thread=None + the tracking: the wheel does not crash", ok)


# ════════════════════════════════════════════════════════════
# 10. Release state + i18n parity
# ════════════════════════════════════════════════════════════
print("== release state + i18n parity ==")

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)

finish()
