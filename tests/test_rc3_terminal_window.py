# -*- coding: utf-8 -*-
"""v1.1.2RC3 — Terminal windows (ROADMAP v1.1.2RC3, AUDIT §4/§5).

Section 1 — U3 "the arrows do not work in mc" (implemented early, before the RC3 release):
the root cause is confirmed — the full-screen TUIs (mc/vim/htop) on the start send
smkx \x1b[?1h (DECCKM, Application Cursor Keys Mode) and further EXPECT the arrows in
the SS3 form (\\x1bOA…\\x1bOD), not in the CSI (\\x1b[A…). The old handler went hard
CSI — mc did not understand them ("they do not work"), and in the bash under mc the same bytes paged
the history (the symptom from the users' remarks). The fix: TerminalWidget chooses
the sequence by tscreen.application_cursor_keys() (the arrows + Home/End;
PageUp/PageDown/Delete are DECCKM-independent — always CSI ~).

The verified fact of pyte 0.8.2 (a run on the installed version): the private modes
are stored in screen.mode with a 5-bit left shift (set_mode(private=True):
mode << 5) — DECCKM is **32**, not 1; the canonical check from the internet
"1 in screen.mode" never fires. By default DECAWM is enabled
(7<<5=224, the auto-wrap) and DECTCEM (25<<5=800, the cursor is visible). pyte.modes in 0.8.2
has no the DECCKM constant.

Sections 2–4 — U3 the keyboard/thread safety (CSI by default, SS3 on DECCKM,
the feed from the SSH thread in parallel with the read of the mode).

Section 5 — N7: the selection reset when the new output auto-returns the scrollback to the live.
The detection: the pyte HistoryScreen.before_event() on ANY event except prev/next_page
snaps the position back to size (the auto-return), and feed() — the only path
that changes the position without a manual scroll; hence pos_before != pos_after ⇔ the auto-return
happened → widget.clear_selection(). The rationale: the selection coordinates (row, col)
are fixed in the release on the HISTORICAL screen, and after the return they point to
OTHER cells of the live screen — Ctrl+C would copy a foreign text. Without the new output /
without an active selection the behavior of a plain click and Ctrl+C is unchanged (the
regressions are checked: the selection with the live output lives; the Ctrl+C with the selection copies, without —
\x03).

Section 6 — U3 the rest: the wheel passthrough via the config terminal_wheel
("scrollback" the default | "off"). pyte 0.8.2 does not track the mouse modes DECSET
1000/1002/1006, therefore the full SGR passthrough of the wheel into the full-screen TUI is deferred
to v1.2+ (a blind forwarding would pollute the shell without a mouse mode). "off": the wheelEvent
ignores the event — the local scrollback is not scrolled by the wheel, nothing goes
into the PTY; the scrollback stays on Ctrl+Shift+PageUp/PageDown. The key is only the config
(the decision of ROADMAP v1.1.2RC3: without the UI in the settings dialog, the i18n parity 375
is unchanged; with v1.1.2 final the parity 377 — see tests/test_status_parallel.py).

Section 7 — U2: the save/restore of the window sizes (modules/window_geometry.py):
on the close saveGeometry()/saveState() → base64 → ~/.sshmap/config.json
(ui_window_geometry_main / ui_window_geometry_terminal), on the start of MainWindow and
the creation of a terminal window — the restore. A broken value / no key → a no-op + the default
size; both functions never raise (teardown-safe). The offscreen virtual screen
800×800: the test sizes ≤ 700×500, the SIZE is compared (the position drifts +5 on
the simulated menubar), the default of a fresh QMainWindow — 640×480, hence the round-trip
is checked with a non-default 700×500.

Section 8 — the release state: APP_VERSION == "1.1.3" (the pin updated to the final of the series),
the pyproject/requirements pins.

Run:  python tests/test_rc3_terminal_window.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until, check_release_state, cfg_path,
                     write_cfg, clear_cfg, read_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt, QEvent, QPoint, QPointF, QSize
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMainWindow

app = QApplication(sys.argv)

import modules.ssh_terminal as ST
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from modules.ssh_terminal import load_terminal_settings
from modules.window_geometry import save_window_geometry, restore_window_geometry
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# 1. U3: DECCKM storage in pyte + TerminalScreen.application_cursor_keys()
# ════════════════════════════════════════════════════════════
print("== U3: DECCKM state in pyte (headless) ==")

scr = TerminalScreen(columns=80, lines=24)
check("a fresh screen: DECCKM is off", scr.application_cursor_keys() is False)
# A verified pyte 0.8.2 fact: by default in the DECAWM (7<<5=224) + DECTCEM (25<<5=800) modes;
# v1.2.11: SshmapHistoryScreen adds LNM (20) — a bare LF = CR+LF (the xterm behaviour).
check("the default mode = {224, 800, 20} (DECAWM+DECTCEM+LNM; LNM since v1.2.11)",
      scr.screen.mode == {224, 800, 20}, f"got={scr.screen.mode}")

scr.feed(b"\x1b[?1h")   # smkx — turning DECCKM on (this is what mc does on startup)
check("after \\x1b[?1h: application_cursor_keys() is True", scr.application_cursor_keys() is True)
check("the pyte 0.8.2 fact: DECCKM is stored as 32 (1<<5), not 1",
      32 in scr.screen.mode and 1 not in scr.screen.mode, f"got={scr.screen.mode}")

scr.feed(b"\x1b[?1l")   # rmkx — turning DECCKM off
check("after \\x1b[?1l: application_cursor_keys() is False", scr.application_cursor_keys() is False)
check("32 is gone from the mode", 32 not in scr.screen.mode, f"got={scr.screen.mode}")

# A compound sequence (several modes at once — as in real TUI init blocks)
scr.feed(b"\x1b[?1;25h")
check("a compound \\x1b[?1;25h: DECCKM is True (32 and 800 in the mode)",
      scr.application_cursor_keys() is True and {32, 800} <= scr.screen.mode,
      f"got={scr.screen.mode}")
scr.feed(b"\x1b[?1l")   # drop DECCKM for cleanliness downstream


# ════════════════════════════════════════════════════════════
# 2. U3: the keyboard offscreen — CSI by default (the v1.0RC2 regression)
# ════════════════════════════════════════════════════════════
print("== U3: keyboard, DECCKM off (CSI regression) ==")

from _fakes import FakeWidgetThread as FakeThread
FakeThread.sent = []
sent = FakeThread.sent   # the same list — for the checks below


def make_widget(cols=20, lines=5, thread=None):
    s = TerminalScreen(columns=cols, lines=lines)
    return s, TerminalWidget(s, thread if thread is not None else FakeThread())


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


scr, w = make_widget()

# The ordinary mode (bash): the arrows and Home/End — CSI (the v1.0RC2 semantics is preserved)
for label, k, e in (("Up", Qt.Key.Key_Up, b"\x1b[A"),
                    ("Down", Qt.Key.Key_Down, b"\x1b[B"),
                    ("Left", Qt.Key.Key_Left, b"\x1b[D"),
                    ("Right", Qt.Key.Key_Right, b"\x1b[C"),
                    ("Home", Qt.Key.Key_Home, b"\x1b[H"),
                    ("End", Qt.Key.Key_End, b"\x1b[F")):
    sent.clear()
    press_key(w, k)
    check(f"DECCKM off: {label} → {e!r}", sent == [e], f"sent={sent!r}")


# ════════════════════════════════════════════════════════════
# 3. U3: the keyboard offscreen — SS3 under DECCKM (the mc scenario)
# ════════════════════════════════════════════════════════════
print("== U3: keyboard, DECCKM on (SS3, mc scenario) ==")

# "Launch mc": the app sends smkx into the PTY output — pyte records the mode
scr.feed(b"\x1b[?1h")

for label, k, e in (("Up", Qt.Key.Key_Up, b"\x1bOA"),
                    ("Down", Qt.Key.Key_Down, b"\x1bOB"),
                    ("Left", Qt.Key.Key_Left, b"\x1bOD"),
                    ("Right", Qt.Key.Key_Right, b"\x1bOC"),
                    ("Home", Qt.Key.Key_Home, b"\x1bOH"),
                    ("End", Qt.Key.Key_End, b"\x1bOF")):
    sent.clear()
    press_key(w, k)
    check(f"DECCKM on: {label} → {e!r}", sent == [e], f"sent={sent!r}")

# DECCKM is independent: PageUp/PageDown/Delete are always CSI ~, F1–F4 always SS3 (this
# their ordinary encoding), F5 — CSI; Enter/Backspace are unchanged.
for label, k, e in (("PageUp", Qt.Key.Key_PageUp, b"\x1b[5~"),
                    ("PageDown", Qt.Key.Key_PageDown, b"\x1b[6~"),
                    ("Delete", Qt.Key.Key_Delete, b"\x1b[3~"),
                    ("F1", Qt.Key.Key_F1, b"\x1bOP"),
                    ("F4", Qt.Key.Key_F4, b"\x1bOS"),
                    ("F5", Qt.Key.Key_F5, b"\x1b[15~"),
                    ("Enter", Qt.Key.Key_Return, b"\r"),
                    ("Backspace", Qt.Key.Key_Backspace, b"\x7f")):
    sent.clear()
    press_key(w, k)
    check(f"DECCKM on: {label} is independent of the mode → {e!r}", sent == [e], f"sent={sent!r}")

# "Exit mc": rmkx — back to CSI (the shell is back in the normal mode)
scr.feed(b"\x1b[?1l")
for label, k, e in (("Up", Qt.Key.Key_Up, b"\x1b[A"),
                    ("Home", Qt.Key.Key_Home, b"\x1b[H")):
    sent.clear()
    press_key(w, k)
    check(f"after \\x1b[?1l: {label} again → {e!r}", sent == [e], f"sent={sent!r}")

# The mc-session loop: the state follows the app output (on/off/on)
seq_seen = []
for payload in (b"\x1b[?1h", b"\x1b[?1l", b"\x1b[?1h"):
    scr.feed(payload)
    sent.clear()
    press_key(w, Qt.Key.Key_Up)
    seq_seen.append(sent[0] if sent else None)
check("the smkx/rmkx cycle: Up follows the mode (SS3/CSI/SS3)",
      seq_seen == [b"\x1bOA", b"\x1b[A", b"\x1bOA"], f"got={seq_seen!r}")

# terminal_thread=None + DECCKM on — the input is disabled: no exceptions, no bytes
# (plain None, not the FakeThread from make_widget!)
scr0 = TerminalScreen(columns=20, lines=5)
w0 = TerminalWidget(scr0, None)
scr0.feed(b"\x1b[?1h")
try:
    sent.clear()
    press_key(w0, Qt.Key.Key_Up)
    check("thread=None + DECCKM on: no exceptions, nothing is sent", sent == [])
except Exception as e:
    check("thread=None + DECCKM on: no exceptions, nothing is sent", False, repr(e))


# ════════════════════════════════════════════════════════════
# 4. U3: thread safety — feed() from the SSH thread in parallel with reading the mode
# ════════════════════════════════════════════════════════════
print("== U3: thread-safety smoke ==")

scr_t = TerminalScreen(columns=80, lines=24)
stop_flag = {"go": True}


def _feed_loop():
    # Simulating the PTY output: the app often switches modes (smkx/rmkx)
    while stop_flag["go"]:
        scr_t.feed(b"\x1b[?1h")
        scr_t.feed(b"\x1b[?1l")


t = threading.Thread(target=_feed_loop, daemon=True)
t.start()
errors = []
try:
    for _ in range(300):
        scr_t.application_cursor_keys()
except Exception as e:  # pragma: no cover
    errors.append(repr(e))
stop_flag["go"] = False
t.join(timeout=5.0)
check("feed from another thread + the DECCKM read: no exceptions/hangs",
      not t.is_alive() and not errors, f"errors={errors!r} alive={t.is_alive()}")


# ════════════════════════════════════════════════════════════
# 5. N7: the selection is reset when the scrollback auto-returns to live
# ════════════════════════════════════════════════════════════
print("== N7: selection cleared on auto-return to live ==")


from _fakes import FakeSSHThread as _FakeSSHThread


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread   # all the terminal windows in this file — on the fake

_term_windows = []


def make_term_win(alias):
    """The terminal window with the fake thread + the grid synchronization (the acceptance pattern)."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"rc3-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password="pw")
    _term_windows.append(w)
    w.resize(700, 500)   # resizeEvent → singleShot(0) → _sync_grid (a guard on the grid)
    wait_until(lambda: (w._last_cols, w._last_rows) != (120, 32), timeout_ms=3000)
    app.processEvents()
    return w


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


def select_drag(w):
    """The realistic drag selection (0,0)→(2,4) — the pattern of tests/test_terminal_input.py."""
    press_lmb(w, 0, 0)
    move_lmb(w, 1, 2)
    release_lmb(w, 2, 4)


CTRL = Qt.KeyboardModifier.ControlModifier

win_n7 = make_term_win("n7")
for i in range(60):   # ~60 lines of history — the scrollback becomes scrollable
    win_n7.page._on_output(f"hist line {i:03d}\r\n".encode())  # v1.2: the session on the page
app.processEvents()

pos_live, _size = win_n7.tscreen.scroll_info()
check("the fresh output: we are on the live line (at_bottom)", win_n7.tscreen.at_bottom(),
      f"info={win_n7.tscreen.scroll_info()}")

# Scrolling into the history (the GUI path: the wheel/the page up) + a mouse selection
check("scroll_page_up: the position went into the history", win_n7.widget.scroll_page_up() is True)
pos_up, _ = win_n7.tscreen.scroll_info()
check("the history position < live (position < size)", pos_up < pos_live,
      f"up={pos_up} live={pos_live}")
select_drag(win_n7.widget)
check("the selection in the history is active", win_n7.widget.has_selection())

# New output → pyte before_event auto-return to live → N7 resets the selection
win_n7.page._on_output(b"new output line\r\n")  # v1.2: the session on the page
app.processEvents()
pos_after, _ = win_n7.tscreen.scroll_info()
check("the auto-return: the position is back to live", pos_after == pos_live,
      f"after={pos_after} live={pos_live}")
check("N7: the selection is cleared after the auto-return", not win_n7.widget.has_selection())

# Regression: Ctrl+C AFTER the N7 reset — SIGINT (the selection is already gone)
win_n7.terminal_thread.channel.sent.clear()
press_key(win_n7.widget, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C after the N7 reset → b'\\x03'", win_n7.terminal_thread.channel.sent == [b"\x03"],
      f"sent={win_n7.terminal_thread.channel.sent!r}")

# Regression: output at the live position (without the auto-return) — the selection LIVES
select_drag(win_n7.widget)
check("the selection at live is active", win_n7.widget.has_selection())
win_n7.page._on_output(b"more output at live\r\n")  # v1.2: the session on the page
app.processEvents()
check("the output at live (the position unchanged) → the selection is kept",
      win_n7.widget.has_selection())

# Regression: Ctrl+C with an active selection — a copy, nothing in the PTY (v0.9.3)
win_n7.terminal_thread.channel.sent.clear()
press_key(win_n7.widget, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C with a selection → nothing into the channel", win_n7.terminal_thread.channel.sent == [])
check("the clipboard got the selected text", app.clipboard().text() != "")
win_n7.widget.clear_selection()

# E2E: the same path via output_signal (a queued signal from the SSH thread)
check("scroll_page_up (E2E): into the history", win_n7.widget.scroll_page_up() is True)
select_drag(win_n7.widget)
win_n7.terminal_thread.output_signal.emit(b"signal-driven line\r\n")
app.processEvents()
check("E2E through output_signal: the auto-return + the selection reset",
      not win_n7.widget.has_selection())


# ════════════════════════════════════════════════════════════
# 6. U3 remainder: the wheel — the terminal_wheel config ("scrollback" | "off")
# ════════════════════════════════════════════════════════════
print("== wheel: config validation + wheelEvent modes ==")
# ── the key validation (load_terminal_settings) ────────────────────────────────
clear_cfg()
check("wheel: no key → the default 'scrollback'", load_terminal_settings()["wheel"] == "scrollback")
write_cfg({"terminal_wheel": "off"})
check("wheel: 'off' → 'off'", load_terminal_settings()["wheel"] == "off")
write_cfg({"terminal_wheel": " OFF "})
check("wheel: ' OFF ' (strip+lower) → 'off'", load_terminal_settings()["wheel"] == "off")
write_cfg({"terminal_wheel": "garbage"})
check("wheel: a broken value → the default 'scrollback'",
      load_terminal_settings()["wheel"] == "scrollback")
write_cfg({"terminal_wheel": 123})
check("wheel: a foreign type (int) → the default 'scrollback'",
      load_terminal_settings()["wheel"] == "scrollback")


def wheel_event(dy):
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


# ── the widget: "off" — the wheel neither scrolls nor sends to the PTY ──────────────────────
scr_off = TerminalScreen(columns=80, lines=24)
w_off = TerminalWidget(scr_off, FakeThread(), wheel_mode="off")
for i in range(60):
    scr_off.feed(f"line {i:03d}\r\n".encode())
check("wheel off: the scrollback is filled (scroll_up works directly)",
      scr_off.scroll_up() is True)
pos_b, size_off = scr_off.scroll_info()
sent.clear()
ev_up = wheel_event(+120)
w_off.wheelEvent(ev_up)
pos_a, _ = scr_off.scroll_info()
check("wheel off: the wheel up does NOT scroll the local scrollback", pos_b == pos_a,
      f"before={pos_b} after={pos_a}")
check("wheel off: the event is not consumed (event.ignore)", not ev_up.isAccepted())
check("wheel off: nothing went into the PTY", sent == [])
ev_dn = wheel_event(-120)
w_off.wheelEvent(ev_dn)
check("wheel off: the wheel down is ignored as well, the position is the same",
      not ev_dn.isAccepted() and scr_off.scroll_info() == (pos_b, size_off))

# ── the widget: "scrollback" (the default) — the wheel scrolls the local scrollback ─────
scr_sb = TerminalScreen(columns=80, lines=24)
w_sb = TerminalWidget(scr_sb, FakeThread())   # wheel_mode is not set → the default
check("wheel: the widget without the parameter — the default mode 'scrollback'",
      w_sb._wheel_mode == "scrollback")
check("wheel: a broken parameter value → 'scrollback'",
      TerminalWidget(TerminalScreen(columns=80, lines=24), FakeThread(),
                     wheel_mode="bogus")._wheel_mode == "scrollback")
for i in range(60):
    scr_sb.feed(f"line {i:03d}\r\n".encode())
check("scrollback: at the live line", scr_sb.at_bottom())
ev_up2 = wheel_event(+120)
w_sb.wheelEvent(ev_up2)
pos_up2, _ = scr_sb.scroll_info()
check("scrollback: the wheel up scrolls into the history + accept",
      pos_up2 < _size and ev_up2.isAccepted(), f"pos={pos_up2}")
ev_dn2 = wheel_event(-120)
w_sb.wheelEvent(ev_dn2)
check("scrollback: the wheel down returns to live + accept",
      scr_sb.at_bottom() and ev_dn2.isAccepted())

# ── the terminal window: the mode is read from the config on creation ──────────────────
write_cfg({"terminal_wheel": "off"})
win_w_off = ST.SSHTerminalWindow(
    ServerData(id="rc3-w-off", alias="w-off", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_w_off)
check("the window: terminal_wheel='off' → widget._wheel_mode == 'off'",
      win_w_off.widget._wheel_mode == "off")
clear_cfg()
win_w_def = ST.SSHTerminalWindow(
    ServerData(id="rc3-w-def", alias="w-def", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_w_def)
check("the window: no key → widget._wheel_mode == 'scrollback' (the default)",
      win_w_def.widget._wheel_mode == "scrollback")


# ════════════════════════════════════════════════════════════
# 7. U2: saving/restoring window sizes
# ════════════════════════════════════════════════════════════
print("== U2: window geometry save/restore ==")

_geo_windows = []


def plain_main_win():
    w = QMainWindow()   # without a parent — we hold the reference so the C++ object does not go into the GC
    _geo_windows.append(w)
    app.processEvents()
    return w


# ── the helper round-trip: save → restore into a fresh window (a non-default size) ───
clear_cfg()
w_a = plain_main_win()
w_a.resize(700, 500)   # the QMainWindow default — 640×480, hence the restoration is visible
app.processEvents()
check("U2: save_window_geometry → True", save_window_geometry("rc3_test_key", w_a) is True)
_val = read_cfg({}).get("rc3_test_key")
check("U2: the value — a dict {geometry, state} (the base64 strings)",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}
      and bool(_val["geometry"]) and bool(_val["state"]), f"got={_val!r}")

w_b = plain_main_win()
check("U2: restore_window_geometry → True", restore_window_geometry("rc3_test_key", w_b) is True)
check("U2: the 700×500 size is restored (not the default 640×480)",
      w_b.size() == QSize(700, 500), f"got={w_b.size()}")

# ── the broken values / a foreign type / no key → a no-op + False ──────────────────
write_cfg({"rc3_test_key": {"geometry": "!!!not-base64", "state": "zzz"}})
w_c = plain_main_win()
check("U2: a broken base64 → False", restore_window_geometry("rc3_test_key", w_c) is False)
check("U2: a broken value — the size stays the default 640×480",
      w_c.size() == QSize(640, 480), f"got={w_c.size()}")

write_cfg({"rc3_test_key": "just-a-string"})
w_d = plain_main_win()
check("U2: the value is not a dict → False", restore_window_geometry("rc3_test_key", w_d) is False)

clear_cfg()
w_e = plain_main_win()
check("U2: no key → False + the default size",
      restore_window_geometry("rc3_test_key", w_e) is False
      and w_e.size() == QSize(640, 480), f"got={w_e.size()}")

# ── E2E the terminal window: closeEvent saves, a new window restores ─────
clear_cfg()
win_t1 = ST.SSHTerminalWindow(
    ServerData(id="rc3-geo-1", alias="geo-1", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_t1)
win_t1.resize(640, 480)   # the terminal window default — 800×600, the restoration is visible
app.processEvents()
_ev_close = QCloseEvent()
win_t1.closeEvent(_ev_close)
check("U2: the terminal's closeEvent is accepted (no 'ask' dialog)", _ev_close.isAccepted())
_val = read_cfg({}).get("ui_window_geometry_terminal")
check("U2: the ui_window_geometry_terminal key is written {geometry, state}",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}, f"got={_val!r}")

win_t2 = ST.SSHTerminalWindow(
    ServerData(id="rc3-geo-2", alias="geo-2", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_t2)
app.processEvents()
check("U2: the new terminal window restored 640×480 (the default 800×600)",
      win_t2.size() == QSize(640, 480), f"got={win_t2.size()}")

# ── E2E the main window: closeEvent saves, a new MainWindow restores ─
clear_cfg()
mw1 = MW.MainWindow()
_geo_windows.append(mw1)
mw1.resize(700, 500)   # the main window default — 1200×850 (offscreen: clamped to 800×800)
app.processEvents()
_ev_close2 = QCloseEvent()
mw1.closeEvent(_ev_close2)
check("U2: the MainWindow's closeEvent is accepted (_dirty=False → no dialog)", _ev_close2.isAccepted())
_val = read_cfg({}).get("ui_window_geometry_main")
check("U2: the ui_window_geometry_main key is written {geometry, state}",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}, f"got={_val!r}")

mw2 = MW.MainWindow()
_geo_windows.append(mw2)
app.processEvents()
check("U2: the new MainWindow restored 700×500 (the default 1200×850)",
      mw2.size() == QSize(700, 500), f"got={mw2.size()}")

clear_cfg()


# ════════════════════════════════════════════════════════════
# 8. Release state (pins — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

finish()
