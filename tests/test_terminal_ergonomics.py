# -*- coding: utf-8 -*-
"""v1.6.4 — the cheap batch: the thread names, the marked secret, the Ctrl+wheel zoom and the activity dot.

The topical file of the release (ROADMAP v1.6.4). Five small items, one theme: **the application
stops being silent about what it is doing** — Qt's abort message names the worker it is about to
kill, the command history marks the entry that may carry a secret instead of losing it, the wheel
zooms the font where it used to do nothing, and a session that produced output while the user was
looking elsewhere says so. The SCROLLBACK mode of the same version lives in its own home,
`tests/test_terminal_scroll.py` (the scrollback already owns that file) — §5 below only asserts
the one seam the two features share.

Sections:
  §1 the THREAD NAMES (task 1): every managed QThread reports a non-empty `objectName()` — the
     one Qt prints in "QThread: Destroyed while thread '' is still running", the abort the orphan
     registries exist to prevent — and the name is the class name the registry and the log use;
  §2 the MARKED SECRET (task 2): the DECIDED rule — the entry is WRITTEN and MARKED. The declared
     pattern list, the single write path, the panel's row marker with its tooltip, and the ONE
     invariant the mark must survive: `merge_entries()` keeps it when EITHER side carries it
     (a fold, a dedup and the per-server cap), while a file written before this version loads as
     unmarked;
  §3 `Ctrl`+wheel = the FONT ZOOM (task 3): the modifier that used to be read nowhere, ±1 pt,
     clamped to the range `terminal_font_size` validates, applied through `set_font()` (the
     metrics and the grid follow), written DEBOUNCED by one timer and reported in the status
     line — while a plain wheel still scrolls and a `Shift`+wheel in a tracking TUI still reports;
  §4 the ACTIVITY mark (task 4): a session that is not the visible one gets a mark in its tab
     strip after output, the mark clears when the tab is focused, the tooltip is its second
     channel and the tab width does not move — in BOTH containers (the window and the dock);
  §5 the release state (the pins, the i18n parity of the three new keys).

Run:  python tests/test_terminal_ergonomics.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, EXPECTED_APP_VERSION,
                     EXPECTED_I18N_KEYS, translation_keys, i18n_lang_codes, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation + offscreen inside)

from PySide6.QtCore import Qt, QPointF, QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
import modules.command_history as CH
from models.server import ServerData
from modules.terminal_screen import (SCROLL_MODE_DEFAULT, SCROLL_MODE_LIVE, SCROLL_MODE_PIN,
                                     TerminalScreen, resolve_scroll_mode)
from modules.terminal_widget import (CURSOR_STYLE_DEFAULT, FONT_SIZE_MAX, FONT_SIZE_MIN,
                                     TerminalWidget)
from modules.terminal_page import (ACTIVITY_ICON_PX, TerminalSessionPage,
                                   activity_tab_icon, render_session_activity)
from modules.terminal_dock import TerminalDockContent

from _fakes import FakeSSHThread as _FakeThread

# every page/window of this file runs on the fake thread (the _fakes.py seam)
_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread


class CanvasThread:
    """The minimal fake the CANVAS needs (send_data + stop — the test_terminal_mouse pattern)."""

    def __init__(self, *a, **k):
        self.sent = []

    def send_data(self, data):
        self.sent.append(data)

    def stop(self):
        pass


def spin(ms=30):
    """Process the events for ~ms (the debounce timers of the zoom)."""
    wait_until(lambda: False, timeout_ms=ms)


def icon_has_ink(icon) -> bool:
    """Does a tab icon really draw something? (an unmarked slot is fully transparent)"""
    img = icon.pixmap(ACTIVITY_ICON_PX, ACTIVITY_ICON_PX).toImage()
    return any(img.pixelColor(x, y).alpha() > 0
               for x in range(img.width()) for y in range(img.height()))


def wheel(w, dy, mod=Qt.KeyboardModifier.NoModifier):
    """The synthetic QWheelEvent in the widget's coordinates (the test_terminal_mouse pattern)."""
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, mod, Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the thread names (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

from modules.ssh_worker import SSHWorker
from modules.sftp_worker import SftpWorker
from modules.plugin_runner import PluginCommandRunner
from modules.plugin_manager import PluginRecord, _HookWorker

_worker = SSHWorker("127.0.0.1", "u", 22)
_term = _orig_thread_cls("127.0.0.1", "u", 22)
_sftp = SftpWorker(None)
_runner = PluginCommandRunner([], "echo hi")
_hook = _HookWorker(PluginRecord("demo"), "status_probe", ())
_workers = (_worker, _term, _sftp, _runner, _hook)
check("§1 every MANAGED QThread names itself — the five of the orphan-worker registries",
      [w.objectName() for w in _workers] == ["SSHWorker", "SSHTerminalThread", "SftpWorker",
                                             "PluginCommandRunner", "_HookWorker"],
      str([(type(w).__name__, w.objectName()) for w in _workers]))
check("§1 the names are non-empty and distinct (a journal line identifies the worker)",
      len({w.objectName() for w in _workers}) == 5 and all(w.objectName() for w in _workers),
      str([w.objectName() for w in _workers]))


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the marked secret (task 2) ==")
# ════════════════════════════════════════════════════════════════════════════

_SHAPES = (
    ("mysql -psecret1 db", True),                       # -p<value>
    ("sshpass -p hunter2 ssh root@h", True),            # -p <value>
    ("mysql --password=abc db", True),                  # --password=
    ("mysqldump -u root -p'quo ted' db", True),
    ('curl -H "Authorization: Bearer sk-abc" url', True),   # Bearer <value>
    ("export API_KEY=abcdef", True),                    # api_key=
    ("export ACCESS_KEY: abcdef", True),                # access_key:
    ("export TOKEN=abcdef", True),
    ("export SECRET=abcdef", True),
    ("sudo passwd: hunter2", True),                     # passwd:
    ("cat <<EOF\n-----BEGIN RSA PRIVATE KEY-----", True),   # a pasted PEM block
    ("df -h", False),                                   # ordinary entries
    ("git commit -m 'fix the pass word'", False),
    ("python -c 'print(1)'", False),
    ("ls -la /etc", False),
    ("", False),
)
_wrong = [s for s, want in _SHAPES if CH.looks_like_secret(s) is not want]
check("§2 the declared shapes are marked and an ordinary command is NOT (the pattern list)",
      not _wrong, str(_wrong))
check("§2 the DECLARED list is the module's single source and the predicate never raises",
      len(CH.SECRET_PATTERNS) == 6
      and all(hasattr(p, "search") for p in CH.SECRET_PATTERNS)
      and CH.looks_like_secret(None) is False and CH.looks_like_secret(42) is False
      and CH.looks_like_secret(b"x") is False, str(len(CH.SECRET_PATTERNS)))

_hist_dir = os.path.join(WORK, "ergonomics_history")
os.makedirs(_hist_dir, exist_ok=True)
_store = CH.CommandHistoryStore("erg-1", directory=_hist_dir)
_store.record("mysql -psecret1 db", timestamp=1000)
_store.record("df -h", timestamp=1001)
_rows = {e["cmd"]: e for e in _store.load()}
check("§2 record() writes the SECRET entry AND marks it (the DECIDED rule: never dropped)",
      _rows["mysql -psecret1 db"][CH.SECRET_FIELD] is True
      and _rows["mysql -psecret1 db"]["cmd"] == "mysql -psecret1 db",
      str(_rows["mysql -psecret1 db"]))
check("§2 ... and an ordinary entry stays unmarked",
      _rows["df -h"][CH.SECRET_FIELD] is False, str(_rows["df -h"]))

with open(_store.path, encoding="utf-8") as f:
    _doc = json.load(f)
_raw = {e["cmd"]: e for e in _doc["commands"]}
check("§2 the FIELD is additive in ONE direction: only the marked entry carries it in the file",
      _raw["mysql -psecret1 db"].get(CH.SECRET_FIELD) is True
      and CH.SECRET_FIELD not in _raw["df -h"],
      str(_doc["commands"]))

# the FOLD is where a flag dies: the timestamp and the count merge arithmetically
_fold = CH.merge_entries([{"cmd": "mysql -psecret1 db", "last": 10, "count": 1}],
                         [{"cmd": "mysql -psecret1 db", "last": 20, "count": 1,
                           "secret": True}])
_fold2 = CH.merge_entries([{"cmd": "mysql -psecret1 db", "last": 10, "count": 1, "secret": True}],
                          [{"cmd": "mysql -psecret1 db", "last": 20, "count": 1}])
check("§2 a fold keeps the mark when EITHER side carries it — in BOTH orders",
      len(_fold) == 1 and _fold[0][CH.SECRET_FIELD] is True and _fold[0]["count"] == 2
      and _fold2[0][CH.SECRET_FIELD] is True,
      f"{_fold} / {_fold2}")

# a file written BEFORE this version: the field is simply absent
_pre = os.path.join(_hist_dir, "prefix.json")
with open(_pre, "w", encoding="utf-8") as f:
    json.dump({"format": 1, "commands": [
        {"cmd": "mysql -psecret1 db", "last": 5, "count": 1}]}, f)
_pre_store = CH.CommandHistoryStore("erg-pre", path=_pre)
check("§2 a pre-fix entry loads as UNMARKED (the field is absent, never required)",
      _pre_store.load()[0][CH.SECRET_FIELD] is False, str(_pre_store.load()))
_pre_store.record("mysql -psecret1 db", timestamp=9)
check("§2 ... and the next real send MARKS the same row (the fold ORs the two sides)",
      _pre_store.load()[0][CH.SECRET_FIELD] is True
      and _pre_store.load()[0]["count"] == 2, str(_pre_store.load()))

_dupes = [{"cmd": "mysql -psecret1 db", "last": 5, "count": 1},
          {"cmd": "mysql -psecret1 db", "last": 9, "count": 1, "secret": True}]
_folded, _removed = CH.dedup_entries(_dupes)
_capped = CH.sort_entries([{"cmd": f"c-{i:04d}", "last": i, "count": 1,
                            "secret": i == CH.MAX_ENTRIES_PER_SERVER + 3}
                           for i in range(CH.MAX_ENTRIES_PER_SERVER + 5)])
check("§2 the mark survives the DEDUP and the per-server CAP (neither rebuilds an entry)",
      _removed == 1 and _folded[0][CH.SECRET_FIELD] is True
      and all(CH.SECRET_FIELD in e for e in _capped)
      and any(e[CH.SECRET_FIELD] for e in _capped)
      and len(_capped) == CH.MAX_ENTRIES_PER_SERVER, f"{_folded} / {len(_capped)}")

_panel = CH.CommandHistoryPanel(store=_store)
app.processEvents()
_marks = {}
for _i in range(_panel.tree.topLevelItemCount()):
    _item = _panel.tree.topLevelItem(_i)
    _marks[_item.text(0)] = (icon_has_ink(_item.icon(0)), _item.toolTip(0))
check("§2 the panel's ROW MARKER is a shape on the marked row and the transparent slot elsewhere",
      _marks["mysql -psecret1 db"][0] is True and _marks["df -h"][0] is False,
      str({k: v[0] for k, v in _marks.items()}))
check("§2 ... and the TOOLTIP is the second channel (the sentence, under the full command)",
      CH.get_translator()("terminal.history.secret_tooltip") in _marks["mysql -psecret1 db"][1]
      and _marks["mysql -psecret1 db"][1].startswith("mysql -psecret1 db\n")
      and _marks["df -h"][1] == "df -h",
      str(_marks["mysql -psecret1 db"][1]))
_panel.deleteLater()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 Ctrl+wheel = the font zoom (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier

_zs = TerminalScreen(columns=40, lines=10)
_zs.feed(b"\r\n".join(b"line-%02d" % i for i in range(40)) + b"\r\n")
_zw = TerminalWidget(_zs, CanvasThread())
_base = _zw.font_size()
wheel(_zw, 120, CTRL)
check("§3 Ctrl+wheel UP steps the point size by exactly 1 pt",
      _zw.font_size() == _base + 1, f"{_base} -> {_zw.font_size()}")
wheel(_zw, -120, CTRL)
check("§3 Ctrl+wheel DOWN steps it back (the gesture is symmetric)",
      _zw.font_size() == _base, str(_zw.font_size()))
check("§3 the new size goes through set_font(): the CELL metrics and the format cache follow",
      _zw.cell_size == (max(1, int(_zw.cell_size[0])), _zw.cell_size[1])
      and _zw._font.kerning() is False and _zw._format_cache == {},
      str(_zw.cell_size))

wheel(_zw, 120, CTRL | ALT)
check("§3 Ctrl+Alt+wheel (the AltGr guard) is NOT the zoom", _zw.font_size() == _base,
      str(_zw.font_size()))

_scr_zoom = TerminalScreen(columns=40, lines=10)
_scr_zoom.feed(b"a\r\nb\r\n")
_wz2 = TerminalWidget(_scr_zoom, CanvasThread())
_wz2.set_font(size=FONT_SIZE_MIN)
wheel(_wz2, -120, CTRL)
_floor = _wz2.font_size()
_wz2.set_font(size=FONT_SIZE_MAX)
wheel(_wz2, 120, CTRL)
check(f"§3 the range is the one `terminal_font_size` validates: clamped at {FONT_SIZE_MIN} "
      f"and at {FONT_SIZE_MAX} pt",
      _floor == FONT_SIZE_MIN and _wz2.font_size() == FONT_SIZE_MAX,
      f"{_floor} / {_wz2.font_size()}")

# the three shipped wheel behaviours are UNCHANGED by the new branch
_scroll = TerminalScreen(columns=40, lines=10)
for i in range(40):
    _scroll.feed(("line-%02d\r\n" % i).encode())
_ws = TerminalWidget(_scroll, CanvasThread())
wheel(_ws, 120)
check("§3 a PLAIN wheel still scrolls the scrollback (the routing below the zoom branch)",
      _scroll.at_bottom() is False and _ws.font_size() == 10, str(_scroll.scroll_info()))

_track = TerminalScreen(columns=40, lines=10)
for i in range(40):
    _track.feed(("t-%02d\r\n" % i).encode())
_track.feed(b"\x1b[?1000h\x1b[?1006h")   # the TUI asks for the mouse
_ft = CanvasThread()
_wt = TerminalWidget(_track, _ft)
wheel(_wt, 120)
check("§3 a wheel in a TRACKING TUI still reports to the PTY (v1.6.3 is untouched)",
      _ft.sent == [b"\x1b[<64;1;1M"] and _track.at_bottom() is True
      and _wt.font_size() == 10, f"sent={_ft.sent!r}")
_ft.sent.clear()
wheel(_wt, 120, SHIFT)
check("§3 ... and Shift is STILL the local override (it scrolls instead of reporting)",
      _ft.sent == [] and _track.at_bottom() is False and _wt.font_size() == 10,
      f"sent={_ft.sent!r} at_bottom={_track.at_bottom()}")

# the page's half: the status line, the grid and the DEBOUNCED key write
clear_cfg()
_node = ServerData(id="erg-zoom", alias="z", host="127.0.0.1", user="u")
_page = TerminalSessionPage(_node)
app.processEvents()
_page.widget.zoom_font(+2)
_applied = _page.widget.font_size()
check("§3 the PAGE reports the new size in the session's status line (ONE status write)",
      _page.session_status == i18n.t("terminal.font_zoom", size=_applied),
      f"{_page.session_status!r} vs {_applied}")
check("§3 the key is NOT written on the first notch (the write is DEBOUNCED)",
      i18n.load_config().get("terminal_font_size") is None,
      str(i18n.load_config().get("terminal_font_size")))
wait_until(lambda: i18n.load_config().get("terminal_font_size") is not None, timeout_ms=2500)
check("§3 ... and the debounce writes `terminal_font_size` exactly once, with the live size",
      i18n.load_config().get("terminal_font_size") == _applied
      and _page.widget._format_cache == {},
      str(i18n.load_config().get("terminal_font_size")))
_page.shutdown()
app.processEvents()
clear_cfg()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the activity mark of an inactive session (task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

_node_a = ServerData(id="erg-a", alias="alpha", host="10.98.1.1", user="root")
_node_b = ServerData(id="erg-b", alias="beta", host="10.98.1.2", user="root")

_win = ST.SSHTerminalWindow(_node_a, None)
_win.add_session(_node_b)
app.processEvents()
_pa, _pb = _win.session_tabs.widget(0), _win.session_tabs.widget(1)
check("§4 both tabs carry the FIXED icon slot from birth (a mark can never resize a tab)",
      not icon_has_ink(_win.session_tabs.tabIcon(0))
      and not icon_has_ink(_win.session_tabs.tabIcon(1)),
      "fresh tabs render an empty slot")

_win.session_tabs.setCurrentIndex(1)   # beta is on screen
app.processEvents()
_width_before = _win.session_tabs.tabBar().tabRect(0).width()
_pa._on_output(b"build finished\r\n")
app.processEvents()
check("§4 output on a NON-VISIBLE session marks its tab (the window container)",
      _pa.has_activity is True and _pb.has_activity is False,
      f"a={_pa.has_activity} b={_pb.has_activity}")
check("§4 the mark is DRAWN (a filled dot) and the VISIBLE tab keeps its empty slot",
      icon_has_ink(_win.session_tabs.tabIcon(0))
      and not icon_has_ink(_win.session_tabs.tabIcon(1)),
      "tab 0 marked, tab 1 not")
check("§4 the mark leaves the tab WIDTH unchanged (the slot was already there)",
      _win.session_tabs.tabBar().tabRect(0).width() == _width_before,
      f"{_width_before} -> {_win.session_tabs.tabBar().tabRect(0).width()}")
check("§4 the TOOLTIP is the mark's second channel",
      _win.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_new_output")
      and _win.session_tabs.tabToolTip(1) == i18n.t("terminal.tab_close_tooltip"),
      f"{_win.session_tabs.tabToolTip(0)!r} / {_win.session_tabs.tabToolTip(1)!r}")

_pa._on_output(b"more output\r\n")
check("§4 a second chunk does not stack a second mark (the state is a bool)",
      _pa.has_activity is True and _win.session_tabs.tabToolTip(0)
      == i18n.t("terminal.tab_new_output"))

_win.session_tabs.setCurrentIndex(0)   # focus the marked tab
app.processEvents()
check("§4 focusing the tab CLEARS the mark and restores the ordinary tooltip",
      _pa.has_activity is False and not icon_has_ink(_win.session_tabs.tabIcon(0))
      and _win.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      f"{_pa.has_activity} / {_win.session_tabs.tabToolTip(0)!r}")

_pa._on_output(b"while visible\r\n")
app.processEvents()
check("§4 output on the VISIBLE session never marks it (the rule's other half)",
      _pa.has_activity is False and not icon_has_ink(_win.session_tabs.tabIcon(0)))

_win.close()
app.processEvents()

# the dock — the SAME rule through the other container
_dock = TerminalDockContent()
_dock.add_session(_node_a)
_dock.add_session(_node_b)
app.processEvents()
_da, _db = _dock.session_tabs.widget(0), _dock.session_tabs.widget(1)
_dock.session_tabs.setCurrentIndex(1)
_dock_width = _dock.session_tabs.tabBar().tabRect(0).width()
_da._on_output(b"tail -f keeps talking\r\n")
app.processEvents()
check("§4 the DOCK marks a non-visible session too (one rule, both containers)",
      _da.has_activity is True and icon_has_ink(_dock.session_tabs.tabIcon(0))
      and _dock.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_new_output")
      and _dock.session_tabs.tabBar().tabRect(0).width() == _dock_width,
      f"{_da.has_activity} / {_dock.session_tabs.tabToolTip(0)!r}")
_dock.session_tabs.setCurrentIndex(0)
app.processEvents()
check("§4 the dock clears the mark when its tab is focused",
      _da.has_activity is False and not icon_has_ink(_dock.session_tabs.tabIcon(0)),
      str(_da.has_activity))
check("§4 the container answers the ONE visibility question (session_is_visible)",
      _dock.session_is_visible(_da) is True and _dock.session_is_visible(_db) is False)
check("§4 the mark is a SHAPE plus a tooltip — the transparent slot is a real icon of the same size",
      not activity_tab_icon(False).pixmap(ACTIVITY_ICON_PX, ACTIVITY_ICON_PX).isNull()
      and not activity_tab_icon(True).pixmap(ACTIVITY_ICON_PX, ACTIVITY_ICON_PX).isNull()
      and icon_has_ink(activity_tab_icon(True)) and not icon_has_ink(activity_tab_icon(False)))
for _p in (_da, _db):
    _p.shutdown()
app.processEvents()

# the split pane has no tab strip — the renderer refuses it instead of raising
_nopane = ServerData(id="erg-pane", alias="pane", host="10.98.1.3", user="root")
_pane = TerminalSessionPage(_nopane, with_sftp=False, with_status_line=False, split=True)
check("§4 a SPLIT PANE (no tab) is refused by the renderer, never an error",
      render_session_activity(_dock.session_tabs, _pane, i18n.t) is False)
check("§4 ... and the pane's state is still its own (the host hook is duck-typed)",
      _pane.set_activity(True) is True and _pane.has_activity is True
      and _pane.set_activity(True) is True)
_pane.shutdown()
app.processEvents()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 the version pin is the version this file describes",
      EXPECTED_APP_VERSION == "1.6.5", EXPECTED_APP_VERSION)
check("§5 the i18n pin counts the SHIPPED release (786 + the 3 keys of the cheap batch"
      " + the 11 of v1.6.5 — the unmanaged card)",
      EXPECTED_I18N_KEYS == 800 and EXPECTED_I18N_KEYS == 789 + 11, str(EXPECTED_I18N_KEYS))
check_release_state(ROOT)

_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
_NEW_KEYS = ("terminal.tab_new_output", "terminal.font_zoom", "terminal.history.secret_tooltip")
check("§5 the three new keys are present and non-empty in every discovered language",
      all(str(_langs[c].get(k, "")).strip() for k in _NEW_KEYS for c in _langs),
      str({c: [k for k in _NEW_KEYS if not str(_langs[c].get(k, "")).strip()] for c in _langs}))
check("§5 the zoom's sentence keeps its `{size}` placeholder in every language",
      all("{size}" in str(_langs[c].get("terminal.font_zoom", "")) for c in _langs),
      str({c: _langs[c].get("terminal.font_zoom") for c in sorted(_langs)}))
check("§5 the two config keys of the release exist and stay config-only",
      callable(ST.load_terminal_settings) and "scroll" in ST.load_terminal_settings()
      and SCROLL_MODE_DEFAULT == SCROLL_MODE_LIVE,
      str(sorted(ST.load_terminal_settings())))
check("§5 the history file's mark does NOT move the PROJECT schema (VERSION_FORMAT stays 0.9)",
      __import__("version").VERSION_FORMAT == "0.9"
      and CH.SECRET_FIELD == "secret")

# cleanup: the fake thread class back, the sessions of this file closed
ST.SSHTerminalThread = _orig_thread_cls

finish()
