# -*- coding: utf-8 -*-
"""v1.0 — Terminal v1, final: full acceptance of all RCs + terminal_* config (ROADMAP tasks 9–10).

One run WITHOUT the network covers the Acceptance v1.0 on a simulated TUI output:
  * bash — the prompt + `ls --color` (SGR 34/93/256/truecolor) through the terminal window;
  * vim  — the cursor hiding ESC[?25l, the alternate screen \x1b[?1049h (v1.2.12:
           SshmapHistoryScreen), the full-screen repaint with the colors; the exit \x1b[?1049l —
           the previous screen is restored character by character including the fg/bg (the known
           limitation was closed in v1.2.12, pinned down by the test);
  * htop — the repeating full-screen frames + the dirty render without the timer;
  * the copying — the mouse selection → the clipboard; the Ctrl+C with the selection = the copying,
    without the selection = \\x03 (SIGINT, "it kills top");
  * Ctrl+V — the bracketed paste of the clipboard as a single block.
Plus task 9: the terminal_palette / terminal_font / terminal_font_size /
terminal_history_lines keys from ~/.sshmap/config.json (all optional, the defaults = the current
behavior) + v1.1.1: terminal_max_open (the limit of one's own terminals) and the release state —
_common.check_release_state() (the pin EXPECTED_APP_VERSION — in tests/_common.py),
v1.2.9: TerminalScreen.render() (the HTML path) removed (the dead code since v1.0RC1),
the i18n parity — _common.check_i18n_parity() (the pin EXPECTED_I18N_KEYS; +33 keys v1.1,
+14 in v1.1.1, +2 in v1.1.2RC2: msg.confirm_delete_profile and status.import_resolving;
in v1.1.2RC3 no new keys — terminal_wheel is only the config; +2 in v1.1.2 final:
settings.statuses.max_parallel and status.auto_interval_hint; +21 in v1.1.3: sftp.*).

Run: python tests/test_terminal_acceptance.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_release_state, cfg_path, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import modules.ssh_terminal as ST
import modules.terminal_screen as TS
from modules.terminal_screen import PALETTES
from modules.terminal_widget import TerminalWidget
from models.server import ServerData

D = PALETTES["default"]
NORD = PALETTES["nord"]


# ── the harness: a fake SSH thread (the same API as SSHTerminalThread) — _fakes.py ──
from _fakes import FakeSSHThread as _FakeSSHThread


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread

_windows = []


def make_window(alias):
    """The terminal window with the fake thread + the grid synchronization with the window."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"acc-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password="pw")
    _windows.append(w)
    # v1.1.3: the window is SHOWN (as in production — MainWindow.show()). Without show()
    # an offscreen window processes resize() lazily: a late _sync_grid →
    # tscreen.resize() would have happened after the painted content and shifted
    # it to the edge of the visible grid (vim/1049). show() makes the layout settle
    # BEFORE any output.
    w.show()
    w.resize(700, 500)   # resizeEvent → singleShot(0) → _sync_grid (a guard on the grid)
    wait_until(lambda: (w._last_cols, w._last_rows) != (120, 32), timeout_ms=3000)
    app.processEvents()
    return w


def feed(win, data):
    """The simulation of the SSH-channel output: through output_signal → _on_output (the feed+update)."""
    win.terminal_thread.output_signal.emit(data)
    app.processEvents()


def emit_out(win, data, until_substr=None, timeout_ms=3000):
    feed(win, data)
    if until_substr is not None:
        wait_until(lambda: until_substr in win.widget.visible_text(), timeout_ms=timeout_ms)


# ── the pixel checks (the tests/test_terminal_colors.py pattern) ───────────────
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


def close_enough(rgb, ref, tol=32):
    return all(abs(a - b) <= tol for a, b in zip(rgb, ref))


def ink_count(img, cw, chh, x, y, ref_hex, tol=48):
    """The count of the pixels of the cell (row=y, col=x), close to the ref (the ink/the background of the glyph)."""
    ref = hex_rgb(ref_hex)
    n = 0
    for yy in range(y * chh, (y + 1) * chh):
        for xx in range(x * cw, (x + 1) * cw):
            if close_enough(pixel(img, xx, yy), ref, tol):
                n += 1
    return n


def grab(win):
    w = win.widget
    cw, chh = w.cell_size
    img = w.grab().toImage()
    return img, cw, chh


# ── the config ~/.sshmap/config.json (the HOME is isolated by the bootstrap) ───────────────
# ════════════════════════════════════════════════════════════
# 0. Release state (pins — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

check("v1.2.9: TerminalScreen.render() (the HTML path) is removed — the dead code since v1.0RC1",
      not hasattr(TS.TerminalScreen, "render"))

check_i18n_parity(load_i18n_langs(ROOT))

# ════════════════════════════════════════════════════════════
# 1. bash: the prompt + ls --color (SGR 34/93/256/truecolor) through the window
# ════════════════════════════════════════════════════════════
print("== bash ==")

clear_cfg()
win = make_window("bash")
# Input — \r\n only (the convention since v1.0RC3; fact №10 was closed in v1.2.11: LNM is now
# is enabled by default and a bare \n = CR+LF, but the \r\n convention remains).
bash_out = (
    b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ls --color=auto\r\n"
    # row 1: docs(0–3, SGR 34) '  ' notes.txt(6–14, SGR 93) '  ' all.xml(17–23, 38;5;196)
    #        '  ' secret.key(26–35, 38;2;200;100;50)
    b"\x1b[0;34mdocs\x1b[0m  \x1b[93mnotes.txt\x1b[0m  \x1b[38;5;196mall.xml\x1b[0m"
    b"  \x1b[38;2;200;100;50msecret.key\x1b[0m\r\n"
    b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ "
)
emit_out(win, bash_out, until_substr="secret.key")

txt = win.widget.visible_text()
check("bash: the prompt + the ls output are visible on the canvas",
      all(s in txt for s in ("root@master", "ls --color=auto", "docs",
                             "notes.txt", "all.xml", "secret.key")), txt[:120])

img, cw, chh = grab(win)
check("bash: the prompt — the green ink (SGR 1;32)",
      ink_count(img, cw, chh, 0, 0, D["green"]) >= 5,
      f"ink={ink_count(img, cw, chh, 0, 0, D['green'])}")
check("bash: 'docs' — the blue ink (SGR 34)",
      ink_count(img, cw, chh, 0, 1, D["blue"]) >= 5,
      f"ink={ink_count(img, cw, chh, 0, 1, D['blue'])}")
check("bash: 'notes.txt' — the bright-yellow ink (SGR 93 → br_yellow)",
      ink_count(img, cw, chh, 6, 1, D["br_yellow"]) >= 5,
      f"ink={ink_count(img, cw, chh, 6, 1, D['br_yellow'])}")
check("bash: 'all.xml' — the 256-color #ff0000 (38;5;196, the hex-passthrough)",
      ink_count(img, cw, chh, 17, 1, "#ff0000") >= 5,
      f"ink={ink_count(img, cw, chh, 17, 1, '#ff0000')}")
check("bash: 'secret.key' — truecolor #c86432 (38;2;200;100;50)",
      ink_count(img, cw, chh, 26, 1, "#c86432", tol=24) >= 5,
      f"ink={ink_count(img, cw, chh, 26, 1, '#c86432', tol=24)}")
win.close()

# ════════════════════════════════════════════════════════════
# 2. vim: ESC[?25l + the alternate screen (v1.2.12) + a full-screen repaint;
#    exit \x1b[?1049l — the previous screen is restored character by character
# ════════════════════════════════════════════════════════════
print("== vim ==")

win = make_window("vim")
# v1.6.2: the pixel checks of this section count the ink of the whole cursor CELL, so the
# historical BLOCK is requested explicitly (the application's default shape is the thin bar).
win.widget.set_cursor_style("block")
# The shell prompt BEFORE vim — the main screen that must be saved and restored.
emit_out(win, b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ vim notes.txt\r\n",
         until_substr="vim notes.txt")
g0 = win.tscreen.snapshot()   # (rows, cx, cy, hidden) — a snapshot with colors BEFORE entering alt

# The cursor at the end — on the EMPTY line 4: the cursor pixel checks must go by
# a cell without glyphs (in the offscreen environment a font without glyphs draws "tofu" in the color
# default_fg, which matches CURSOR_COLOR — the check on the lines with text
# would have been incorrect).
# vim enters the alternate screen (v1.2.12): \x1b[?25l + \x1b[?1049h + a full-screen
# a repaint with the colors (the work buffer — a fresh empty one, the main one is saved).
emit_out(win, b"\x1b[?25l\x1b[?1049h\x1b[2J\x1b[H\x1b[41m vim session \x1b[0m\r\nvim content line\x1b[5H",
         until_substr="vim session")

check("vim: in the alternate screen (the in_alt_screen is True)", win.tscreen.in_alt_screen() is True)
rows, cx, cy, hidden = win.tscreen.snapshot()
check("vim: the cursor is hidden (ESC[?25l)", hidden is True)
check("vim: the cursor is on the empty line 4 (the position for the pixel check)",
      (cx, cy) == (0, 4), f"cursor=({cx},{cy})")

img, cw, chh = grab(win)
cur_ink = ink_count(img, cw, chh, cx, cy, TerminalWidget.CURSOR_COLOR, tol=16)
check("vim: the block cursor is NOT drawn while hidden", cur_ink == 0, f"ink={cur_ink}")
red_bg = ink_count(img, cw, chh, 5, 0, D["red"], tol=32)
check("vim: SGR 41 — the red background of the line ' vim session '", red_bg >= 10, f"ink={red_bg}")
check("vim: the alt screen — a separate buffer (the shell prompt is not visible on the grid)",
      "vim notes.txt" not in win.widget.visible_text())

emit_out(win, b"\x1b[?25h")
rows, cx, cy, hidden = win.tscreen.snapshot()
check("vim: the cursor is visible again (ESC[?25h)", hidden is False)
img, cw, chh = grab(win)
p = pixel(img, cx * cw + cw // 2, cy * chh + chh // 2)
check("vim: the block cursor is drawn at the cursor position",
      close_enough(p, hex_rgb(TerminalWidget.CURSOR_COLOR), tol=16), f"got={p}")

# v1.2.12 (known limitation closed): \x1b[?1049l — exit from the alt screen: the previous
# the screen is restored character by character including fg/bg (SshmapHistoryScreen; the semantics —
# upstream PR #212, verified differentially against tmux 3.6b and GNU screen).
emit_out(win, b"\x1b[?1049l")
check("vim: the exit from the alt screen (the in_alt_screen is False)", win.tscreen.in_alt_screen() is False)
g1 = win.tscreen.snapshot()
check("vim: the previous screen is restored character by character including the fg/bg (the snapshot == G0)",
      g1 == g0, f"cursor=({g1[1]},{g1[2]}) hidden={g1[3]}")
check("vim: 'vim session' is gone, the shell prompt is back",
      "vim session" not in win.widget.visible_text()
      and "vim notes.txt" in win.widget.visible_text())
win.close()

# ════════════════════════════════════════════════════════════
# 3. htop: repeated full-screen frames + a dirty render without a timer
# ════════════════════════════════════════════════════════════
print("== htop ==")

win = make_window("htop")


def _htop_frame(i):
    return (b"\x1b[2J\x1b[H\x1b[1mTASKS: 3\x1b[0m  \x1b[38;5;45mLOAD AVG: " + str(i).encode()
            + b"\x1b[0m\r\n\x1b[46m CPU bar " + b"#" * i + b" \x1b[0m\r\n\x1b[?25l")


for i in (1, 2, 3):
    emit_out(win, _htop_frame(i))

txt = win.widget.visible_text()
check("htop: the LAST frame is rendered", "LOAD AVG: 3" in txt and "CPU bar ###" in txt,
      txt[:80])
check("htop: the old frames are replaced (ESC[2J)", "LOAD AVG: 1" not in txt)

rows, cx, cy, hidden = win.tscreen.snapshot()
check("htop: the cursor is hidden while the TUI is running", hidden is True)

img, cw, chh = grab(win)
cyan_bg = ink_count(img, cw, chh, 0, 1, D["cyan"], tol=32)
check("htop: SGR 46 — the light-blue background of the CPU bar", cyan_bg >= 10, f"ink={cyan_bg}")

check("the dirty render: the 33 ms timer is removed (no _render_timer/_dirty)",
      not hasattr(win, "_render_timer") and not hasattr(win, "_dirty"))
check("the dirty render: the paintEvent passed on the output (last_paint_stats.rows > 0)",
      win.widget.last_paint_stats["rows"] > 0, str(win.widget.last_paint_stats))
win.close()

# ════════════════════════════════════════════════════════════
# 4. Copying: mouse selection + Ctrl+C (copy/SIGINT) + Ctrl+V (bracketed paste)
# ════════════════════════════════════════════════════════════
print("== copy / Ctrl+C / Ctrl+V ==")

CTRL = Qt.KeyboardModifier.ControlModifier


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


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


win = make_window("copy")
emit_out(win, b"alpha beta gamma\r\ndelta epsilon zeta\r\neta theta iota kappa",
         until_substr="kappa")

# a drag (0,0) → (1,4): row 0 entirely + row 1 from col 0 to col 4 INCLUSIVE
w = win.widget
press_lmb(w, 0, 0)
move_lmb(w, 1, 2)
release_lmb(w, 1, 4)
check("the copying: the mouse selection is active", w.has_selection())
exp_sel = "alpha beta gamma\ndelta"
check("the copying: selected_text() — the multi-line text (row-major)",
      w.selected_text() == exp_sel, repr(w.selected_text()))

sent_before = len(win.terminal_thread.channel.sent)
w.copy_selection()
cb = app.clipboard()
check("the copying: the clipboard == the selection", cb.text() == exp_sel, repr(cb.text()))

press_key(w, Qt.Key.Key_C, mod=CTRL)  # Ctrl+C WITH a selection → a copy, not SIGINT
check("Ctrl+C with the selection: nothing goes into the channel (the copying, not \\x03)",
      len(win.terminal_thread.channel.sent) == sent_before,
      repr(win.terminal_thread.channel.sent[sent_before:]))
check("Ctrl+C with the selection: the clipboard is updated", cb.text() == exp_sel)

w.clear_selection()
press_key(w, Qt.Key.Key_C, mod=CTRL)  # Ctrl+C WITHOUT a selection → SIGINT ("kills top")
check("Ctrl+C without the selection → b'\\x03' (SIGINT)",
      win.terminal_thread.channel.sent[-1] == b"\x03",
      repr(win.terminal_thread.channel.sent[-1]))

cb.setText("restart\nservice nginx")  # Ctrl+V — a bracketed paste as a single block
press_key(w, Qt.Key.Key_V, mod=CTRL)
check("Ctrl+V: the clipboard goes as a SINGLE bracketed block (\\x1b[200~…\\x1b[201~)",
      win.terminal_thread.channel.sent[-1] == b"\x1b[200~restart\nservice nginx\x1b[201~",
      repr(win.terminal_thread.channel.sent[-1]))
cb.setText("")
win.close()

# ════════════════════════════════════════════════════════════
# 5. Task 9: the terminal_* keys from ~/.sshmap/config.json
# ════════════════════════════════════════════════════════════
print("== config: terminal_* keys ==")

from modules.ssh_terminal import load_terminal_settings

# v1.1: load_terminal_settings() also returns close_behavior
# ("close" by default; "ask" — confirmation for closing an active session);
# v1.1.1: + max_open (the limit of own terminals, default 4);
# v1.2.2: + mode (the display mode: "windows" the default | "tabs" — the dock on the map).
clear_cfg()
s = load_terminal_settings()
check("no config → the defaults (the palette default, pt 10, the history 1000 — the scrollback is on, close_behavior=close, max_open=4, wheel=scrollback, mode=windows, cursor=bar, scroll=live, follow_cwd=False)",
      s == {"palette": None, "font_family": "", "font_size": None,
            "history_lines": TS.DEFAULT_HISTORY_LINES, "close_behavior": "close",
            "max_open": 4, "wheel": "scrollback", "mode": "windows",
            "cursor": "bar", "scroll": "live", "follow_cwd": False}, str(s))

write_cfg({"terminal_palette": " nord ", "terminal_font": " Consolas ",
              "terminal_font_size": 12, "terminal_history_lines": 50})
s = load_terminal_settings()
check("the valid values are read (the trimming of the spaces)",
      s == {"palette": "nord", "font_family": "Consolas", "font_size": 12,
            "history_lines": 50, "close_behavior": "close", "max_open": 4,
            "wheel": "scrollback", "mode": "windows", "cursor": "bar", "scroll": "live",
            "follow_cwd": False}, str(s))

write_cfg({"terminal_palette": 42, "terminal_font": 7,
              "terminal_font_size": "big", "terminal_history_lines": -5})
s = load_terminal_settings()
check("the broken values (the foreign types / out of the range) → the defaults",
      s == {"palette": None, "font_family": "", "font_size": None,
            "history_lines": TS.DEFAULT_HISTORY_LINES, "close_behavior": "close",
            "max_open": 4, "wheel": "scrollback", "mode": "windows",
            "cursor": "bar", "scroll": "live", "follow_cwd": False}, str(s))

# v1.1.1: terminal_max_open — the limit of own terminals (default 4, the range 1..32)
write_cfg({"terminal_max_open": 8})
check("v1.1.1: the terminal_max_open=8 is read", load_terminal_settings()["max_open"] == 8)
write_cfg({"terminal_max_open": "many"})
check("v1.1.1: the broken terminal_max_open (str) → the default 4",
      load_terminal_settings()["max_open"] == 4)
write_cfg({"terminal_max_open": 99})
check("v1.1.1: the terminal_max_open out of the range (99) → the default 4",
      load_terminal_settings()["max_open"] == 4)

# v1.2.2: terminal_mode — the display mode ("windows" the default | "tabs" — the dock on the map);
# the validation following the pattern of the other keys (a corrupt value/a foreign type → the default)
write_cfg({"terminal_mode": "tabs"})
check("v1.2.2: the terminal_mode='tabs' is read", load_terminal_settings()["mode"] == "tabs")
write_cfg({"terminal_mode": " TABS "})
check("v1.2.2: terminal_mode ' TABS ' (strip+lower) → 'tabs'",
      load_terminal_settings()["mode"] == "tabs")
write_cfg({"terminal_mode": 123})
check("v1.2.2: the broken terminal_mode (int) → the default 'windows'",
      load_terminal_settings()["mode"] == "windows")

write_cfg({"terminal_close_behavior": " ask "})
check("v1.1: the terminal_close_behavior='ask' is read (the trimming of the spaces)",
      load_terminal_settings()["close_behavior"] == "ask")

write_cfg({"terminal_close_behavior": "yell"})
check("v1.1: the broken terminal_close_behavior → the default 'close'",
      load_terminal_settings()["close_behavior"] == "close")

write_cfg({"terminal_history_lines": 0})
check("the explicit terminal_history_lines=0 — the scrollback is off (a deliberate choice)",
      load_terminal_settings()["history_lines"] == 0)

# v1.1.2RC3 (U3 remainder): terminal_wheel — "scrollback" (the default) | "off";
# the full wheel SGR passthrough in a TUI is deferred to v1.2+ (pyte does not track DECSET
# 1000/1002/1006). The key is config only — no UI in the settings dialog.
write_cfg({"terminal_wheel": "off"})
check("v1.1.2RC3: the terminal_wheel='off' is read", load_terminal_settings()["wheel"] == "off")
write_cfg({"terminal_wheel": "bogus"})
check("v1.1.2RC3: the broken terminal_wheel → the default 'scrollback'",
      load_terminal_settings()["wheel"] == "scrollback")

# v1.6.3 (task 5): terminal_follow_cwd — the OSC 7 follow of the Files tab. OPT-IN: only a
# REAL bool turns it on (the tab's checkbox is the UI; the key is not a settings-hub row).
write_cfg({"terminal_follow_cwd": True})
check("v1.6.3: the terminal_follow_cwd=True is read",
      load_terminal_settings()["follow_cwd"] is True)
write_cfg({"terminal_follow_cwd": "yes"})
check("v1.6.3: a broken terminal_follow_cwd → OFF (never a hook the user did not ask for)",
      load_terminal_settings()["follow_cwd"] is False)

# A window with a full config: the nord palette + Consolas 12 + the history depth of 50
write_cfg({"terminal_palette": "nord", "terminal_font": "Consolas",
              "terminal_font_size": 12, "terminal_history_lines": 50})
win = make_window("cfg")
check("the config: the palette nord is applied to the canvas", win.widget._palette_name == "nord",
      win.widget._palette_name)
check("the config: _bg_color = the default_bg of the palette nord",
      win.widget._bg_color.name().lower() == NORD["default_bg"],
      win.widget._bg_color.name())
img, cw, chh = grab(win)
# The pixel — over the COMPLETELY empty line 15 (line 0 is occupied by the block cursor at (0,0),
# lines with text in offscreen render "tofu" — the background between glyphs is not deterministic).
bg = pixel(img, cw // 2, 15 * chh + chh // 2)
check("the config: the screen background on the canvas = the default_bg of the palette nord (#2e3440)",
      close_enough(bg, hex_rgb(NORD["default_bg"]), tol=8), f"got={bg}")
check("the config: the font Consolas 12 is applied",
      win.widget._font.family() == "Consolas" and win.widget._font.pointSize() == 12,
      f"{win.widget._font.family()} pt{win.widget._font.pointSize()}")
for _ in range(200):
    win.tscreen.feed(b"x\r\n")
pos, size = win.tscreen.scroll_info()
check("the config: the history depth 50 (the deque limit terminal_history_lines)",
      size == 50 and pos == 50, f"pos={pos} size={size}")
win.close()

# An unknown palette → silently stays "default" (set_palette() False)
write_cfg({"terminal_palette": "neon"})
win = make_window("cfgbad")
check("the config: the unknown palette → 'default' (without an error)",
      win.widget._palette_name == "default", win.widget._palette_name)
img, cw, chh = grab(win)
bg = pixel(img, cw // 2, 15 * chh + chh // 2)   # an empty line — a clean background
check("the config: the background is the default palette (#0f172a)",
      close_enough(bg, hex_rgb(D["default_bg"]), tol=8), f"got={bg}")
win.close()

# Corrupt values in the window → the defaults (pt 10, history 1000)
write_cfg({"terminal_palette": 42, "terminal_font_size": "big",
              "terminal_history_lines": -5})
win = make_window("cfgbad2")
check("the config: the broken values → the font pt 10 (the default)",
      win.widget._font.pointSize() == 10, f"pt{win.widget._font.pointSize()}")
for _ in range(1200):
    win.tscreen.feed(b"x\r\n")
pos, size = win.tscreen.scroll_info()
check("the config: the broken terminal_history_lines → the default 1000 (the scrollback is on)",
      size == TS.DEFAULT_HISTORY_LINES and pos == size, f"pos={pos} size={size}")
win.close()

# No config at all → the behaviour AFTER RC3: a HistoryScreen with the built-in depth
clear_cfg()
win = make_window("cfgnone")
for _ in range(1200):
    win.tscreen.feed(b"x\r\n")
pos, size = win.tscreen.scroll_info()
check("the config is absent → the default: the scrollback is on, the depth 1000 (the RC3 behavior)",
      size == TS.DEFAULT_HISTORY_LINES and pos == size, f"pos={pos} size={size}")
win.close()

# ════════════════════════════════════════════════════════════
# Cleanup
# ════════════════════════════════════════════════════════════
ST.SSHTerminalThread = _orig_thread_cls
clear_cfg()
for w in _windows:
    try:
        w.close()
    except Exception:
        pass

finish()
