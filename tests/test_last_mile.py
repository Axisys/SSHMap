# -*- coding: utf-8 -*-
"""v1.6.8 — The last mile, closing the line: the gesture the map already had, and the problem
set it already knew.

The topical file of the CLOSING release of the 1.6 line (ROADMAP v1.6.8). ONE theme:
**nothing new to know — only to reach.** The application already knew how to draw a
connection by `Shift`+dragging from a card (since v0.7), and it already DECLARED which cards
need attention (`graphics.node_group.is_in_trouble()`, v1.5.4) — but neither could be FOUND
or TAKEN OUT: the gesture had no row in any menu, the two node pickers of the dialog could
not be typed into, and the "problems" set stayed on the canvas. The release adds ONE row, ONE
sentence, ONE search rule and ONE report, all of them built on shipped machinery.

Sections:
  §1 THE ROW: "Connect to…" in the MAP's node menu and in the sidebar's `CONTEXT_MENU_ITEMS`,
     both calling the SAME `_add_connection(default_source_id=…)` the drag gesture calls (one
     undo command, the prefill, and the unmanaged card is NOT gated — the verb needs no login);
  §2 THE HINT: the first screen's sentence about the gesture and the tooltip of the registry
     action `edit.add_connection`, ONE composer and ONE key, with the action's REAL label
     inside it (the v1.4.5 rule) — plus the two refusals the plan fixed (no per-card line, no
     second wording);
  §3 THE SEARCHABLE PICKERS (`dialogs/connection_dialog.py`): the pure `match_index()` rule
     (exact, then the first case-insensitive substring over alias AND host), the `QCompleter`
     of both fields, the no-match answer that KEEPS the previous selection, the provider
     callback (the dialog knows no scene) and the unchanged `get_connection()` contract;
  §4 THE REPORT'S PURE HALF (`storage/export_problems.py`): the declared columns, the rows the
     PREDICATE keeps (warn / offline / stale), the reason vocabulary, the RFC-4180 quoting
     through the SHARED writer, and the `[]` answer of a map with nothing to report;
  §5 THE ACTION AND ITS REPORTS: ONE registry action with an EMPTY default in the Export
     menu's DATA group, the empty map and the all-clear map in their OWN sentences (no file),
     and the written file on a map that really has problems;
  §6 THE LINE'S CLOSING AUDIT: ONE entry per fact the 1.6 line DECLARED, re-read against the
     shipped source — a drift is a defect, and none was found here;
  §7 the i18n parity and the release state.

Run: python tests/test_last_mile.py   (from the project root) or python tests/run_all.py
"""
import csv
import io
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, EXPECTED_APP_VERSION,
                     EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation + offscreen)

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMenu  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import version as _version  # noqa: E402
import i18n  # noqa: E402
from i18n import t as _t  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import storage.export_problems as EP  # noqa: E402
from models.server import ServerData  # noqa: E402
from graphics.node_group import is_in_trouble  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402
from dialogs.connection_dialog import ConnectionDialog, match_index  # noqa: E402
from ui import sidebar as SB  # noqa: E402
from ui import unmanaged as UM  # noqa: E402
from ui.empty_state import EmptyStateOverlay, connect_hint_text  # noqa: E402

# ── The harness: no modal box may ever block an offscreen run ────────────────
BOXES = []
MW.QMessageBox.critical = staticmethod(lambda *a, **k: BOXES.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: BOXES.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: BOXES.append(("information",)))

LANGS = load_i18n_langs(ROOT)

#: The THIRTEEN keys of the release — the ONE list §7 iterates.
NEW_KEYS = (
    # the row (task 1)
    "ctx.connect_to",
    # the hint (task 2)
    "empty.state.connect_hint",
    # the picker (task 3)
    "connection.no_match",
    # the report (tasks 4/5)
    "file.export_problems",
    "report.problems.alias", "report.problems.host", "report.problems.status",
    "report.problems.reason", "report.problems.checked", "report.problems.stale",
    "status.problems_exported", "status.problems_no_nodes", "status.problems_none",
)


def make_main():
    """An offscreen MainWindow that opens no socket (the test_unmanaged pattern)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    win.resize(1100, 760)
    win.show()
    app.processEvents()
    return win


def close_window(win):
    win._dirty = False
    win._undo_baseline_dirty = False
    win.close()
    app.processEvents()


def labels_of(menu) -> dict:
    """{action text: QAction} of a QMenu (the menu checks read the live widget)."""
    return {a.text(): a for a in menu.actions()}


class FakeNode:
    """A duck-typed card for the PURE half of the report (no Qt item, no scene)."""

    def __init__(self, node_id="n", alias="a", host="h", status="", stale=False, age=""):
        class _Data:
            pass
        self.data = _Data()
        self.data.id = node_id
        self.data.alias = alias
        self.data.host = host
        self.status = status
        self.is_stale = bool(stale)
        self._age = age

    def freshness_text(self):
        return self._age


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the row: 'Connect to…' in BOTH node menus (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the sidebar's declaration gained ONE row in the `ctx.*` family",
      ("connect_to", "ctx.connect_to") in SB.CONTEXT_MENU_ITEMS, str(SB.CONTEXT_MENU_ITEMS))
check("§1 ... and it sits with the two SSH rows (all three answer 'connect this server')",
      [e[0] for e in SB.CONTEXT_MENU_ITEMS if e is not None][:3]
      == ["ssh", "external", "connect_to"],
      str([e[0] for e in SB.CONTEXT_MENU_ITEMS if e is not None][:3]))
check("§1 the gate is NOT touched: drawing a link needs no login on the host",
      "connect_to" not in UM.GATED_ACTIONS and UM.action_blocked("connect_to", None) is False,
      str(sorted(UM.GATED_ACTIONS)))

win = make_main()
_src_node = win.scene.add_server(ServerData(id="lm-a", alias="web-1", host="10.10.0.1",
                                            user="ops", x=0.0, y=0.0))
_target = win.scene.add_server(ServerData(id="lm-b", alias="db-1", host="10.10.0.2",
                                          user="dba", x=900.0, y=0.0))
app.processEvents()

# ── the MAP's node menu ──────────────────────────────────────────────────────
_map_menu = win.view.build_context_menu(_src_node.card_rect_scene().center())
_rows = labels_of(_map_menu)
check("§1 the MAP's node menu offers the row (the same `ctx.connect_to` key)",
      _t("ctx.connect_to") in _rows, str(sorted(_rows)))
check("§1 ... and it is ENABLED (a plain node verb, ungated)",
      _rows[_t("ctx.connect_to")].isEnabled() is True)

# ── the SIDEBAR's row menu ───────────────────────────────────────────────────
_side_menu = QMenu(win)
win.sidebar.fill_context_menu(_side_menu, _src_node)
_side_rows = labels_of(_side_menu)
check("§1 the sidebar's row menu offers the SAME row",
      _t("ctx.connect_to") in _side_rows, str(sorted(_side_rows)))
check("§1 ... enabled as well (one declaration, two menus)",
      _side_rows[_t("ctx.connect_to")].isEnabled() is True)

# ── the row really creates the connection the DRAG creates ──────────────────
_calls = []


class _FakeConnDialog:
    """The real dialog is modal: capture its prefill and answer with a valid pair."""

    def __init__(self, nodes, parent=None, default_source_id=None, default_target_id=None,
                 default_type=None, nodes_provider=None):
        _calls.append({"source": default_source_id, "target": default_target_id,
                       "provider": nodes_provider})
        self._src = default_source_id or "lm-a"
        self._tgt = default_target_id or ("lm-b" if self._src != "lm-b" else "lm-a")

    def exec(self):
        return QDialog.Accepted

    def get_connection(self):
        return (self._src, self._tgt, "row-label", "ssh", False)


_orig_dlg = MW.ConnectionDialog
MW.ConnectionDialog = _FakeConnDialog
try:
    _undo_before = win.undo_stack.count()
    _rows[_t("ctx.connect_to")].trigger()
    app.processEvents()
finally:
    MW.ConnectionDialog = _orig_dlg
check("§1 the map row calls `_add_connection(default_source_id=…)` — the drag's OWN path",
      len(_calls) == 1 and _calls[0]["source"] == "lm-a" and _calls[0]["target"] is None,
      str(_calls))
check("§1 the created connection is the one the command writes (ONE undo step)",
      win.undo_stack.count() == _undo_before + 1
      and any(a.source.data.id == "lm-a" and a.target.data.id == "lm-b"
              for a in win.scene.arrows()),
      f"undo={win.undo_stack.count()} arrows={len(win.scene.arrows())}")

# ── the sidebar row goes through the SAME entry point (and selects first) ────
_calls.clear()
_orig_dlg = MW.ConnectionDialog
MW.ConnectionDialog = _FakeConnDialog
try:
    win.sidebar._actions["connect_to"](_target)
    app.processEvents()
finally:
    MW.ConnectionDialog = _orig_dlg
check("§1 the sidebar row opens the dialog with THAT row's node as the source",
      len(_calls) == 1 and _calls[0]["source"] == "lm-b", str(_calls))
check("§1 ... and the row's node is the SELECTION (the 'select first, then act' rule)",
      win.scene.get_selected_node() is _target,
      str(getattr(win.scene.get_selected_node(), "data", None)))

# A guard rail the plan did NOT ask for but the row needs: a prefilled SOURCE must not
# pre-select itself as the TARGET (the dialog would open on its own refusal).
_dlg = ConnectionDialog([_src_node, _target], None, default_source_id="lm-a")
check("§1 a source-only prefill does NOT pre-select itself as the target",
      _dlg.source.currentData() == "lm-a" and _dlg.target.currentData() != "lm-a",
      f"{_dlg.source.currentData()} / {_dlg.target.currentData()}")
_dlg2 = ConnectionDialog([_src_node, _target], None, default_source_id="lm-b",
                         default_target_id="lm-a")
check("§1 ... while an EXPLICIT drag prefill is untouched (both directions keep working)",
      _dlg2.source.currentData() == "lm-b" and _dlg2.target.currentData() == "lm-a")
_dlg.deleteLater()
_dlg2.deleteLater()
_map_menu.deleteLater()
_side_menu.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the hint: the gesture named where it is discovered (task 2) ==")
# ════════════════════════════════════════════════════════════════════════════

_hint = _t("empty.state.connect_hint", add_connection=_t("edit.add_connection"))
check("§2 the sentence names the Shift+drag gesture AND the menu row",
      "Shift" in _hint and _t("edit.add_connection") in _hint, _hint)
check("§2 ONE composer: `connect_hint_text()` is the sentence, not a copy",
      connect_hint_text() == _hint, connect_hint_text())
_overlay = EmptyStateOverlay(win.view)
check("§2 the first screen renders exactly that sentence (`connect_text()`)",
      _overlay.connect_text() == _hint, _overlay.connect_text())
_overlay.place(900, 700)
check("§2 the card GREW for the third line (the height formula follows the lines)",
      _overlay.height() > 0 and "hint_fm.height() + 2 + hint_fm.height()"
      in open(os.path.join(ROOT, "ui", "empty_state.py"), encoding="utf-8").read())
_overlay.deleteLater()

_conn_act = win._hotkey_targets.get("edit.add_connection", [None])[0]
check("§2 the registry action `edit.add_connection` carries the SAME words as a tooltip",
      _conn_act is not None and _conn_act.toolTip() == _hint,
      repr(getattr(_conn_act, "toolTip", lambda: None)()))
check("§2 ... so the two surfaces are ONE key, ONE function (they cannot drift)",
      win._connect_hint_text() == connect_hint_text() == _hint)
check("§2 the hint is NOT a per-card tooltip (the refusal of the plan)",
      "connect_hint" not in open(os.path.join(ROOT, "graphics", "server_node.py"),
                                 encoding="utf-8").read())


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the searchable pickers (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

_TEXTS = ["web-1 (10.10.0.1)", "db-1 (db.internal)", "cache (192.168.5.7)"]
check("§3 the pure rule: an EXACT text wins (tier 1)",
      match_index(_TEXTS, "db-1 (db.internal)") == 1)
check("§3 ... then the FIRST case-insensitive SUBSTRING match (tier 2)",
      match_index(_TEXTS, "DB") == 1 and match_index(_TEXTS, "web") == 0)
check("§3 ... matching on the HOST as well as the alias (one string carries both)",
      match_index(_TEXTS, "192.168") == 2 and match_index(_TEXTS, "internal") == 1)
check("§3 ... and -1 when nothing carries the query (tier 3) / the query is blank",
      match_index(_TEXTS, "nope") == -1 and match_index(_TEXTS, "") == -1
      and match_index(_TEXTS, "   ") == -1)

_pick = ConnectionDialog([_src_node, _target], None, default_source_id="lm-a")
check("§3 both pickers are TYPEABLE (the defect: they could not be typed into)",
      _pick.source.isEditable() and _pick.target.isEditable())
_completer = _pick.source.completer()
check("§3 ONE completer per field, over the combo's own model (no second list)",
      _completer is not None and _completer.model() is _pick.source.model())
check("§3 the rule is case-insensitive SUBSTRING (the SftpTab precedent)",
      _completer.caseSensitivity() == _completer.caseSensitivity().CaseInsensitive
      and bool(_completer.filterMode() & _completer.filterMode().MatchContains),
      f"{_completer.caseSensitivity()} / {_completer.filterMode()}")
check("§3 the popup is the completion mode (it opens on the FIRST keystroke)",
      _completer.completionMode() == _completer.completionMode().PopupCompletion)
_completer.setCompletionPrefix("1")           # ONE keystroke
check("§3 one keystroke already answers (the popup has candidates)",
      _completer.completionCount() >= 1, str(_completer.completionCount()))
_completer.setCompletionPrefix("db")
check("§3 the completion itself matches the alias and the host",
      _completer.completionCount() == 1
      and _completer.currentCompletion().startswith("db-1"),
      _completer.currentCompletion())

_pick.source.setEditText("nope")
_pick.settle_picker(_pick.source)
check("§3 a NO-MATCH query keeps the PREVIOUS selection (never an empty picker)",
      _pick.source.currentData() == "lm-a", str(_pick.source.currentData()))
check("§3 ... and SAYS so in its own sentence (`connection.no_match`)",
      _pick.no_match_label.isHidden() is False
      and _t("connection.no_match").split("{")[0][:18]
      in _pick.no_match_label.text(),
      repr(_pick.no_match_label.text()))
_pick.source.setEditText("db")
_pick.settle_picker(_pick.source)
check("§3 a matching query settles onto the node it names",
      _pick.source.currentData() == "lm-b" and _pick.no_match_label.isHidden() is True,
      str(_pick.source.currentData()))
check("§3 `get_connection()` settles first: a half-typed query never reaches the command",
      _pick.source.setEditText("cache") or _pick.get_connection()[0] == "lm-b",
      str(_pick.get_connection()[:2]))
_pick.deleteLater()

_provider_calls = []


def _nodes_provider():
    _provider_calls.append(1)
    return [_src_node, _target]


_pick2 = ConnectionDialog([], None, nodes_provider=_nodes_provider, default_source_id="lm-b")
check("§3 the pickers are fed from the LIVE scene through the callback (no scene in the dialog)",
      _provider_calls == [1] and _pick2.source.count() == 2
      and _pick2.source.currentData() == "lm-b", str(_provider_calls))


def _broken_provider():
    raise RuntimeError("no scene")


_pick3 = ConnectionDialog([_src_node], None, nodes_provider=_broken_provider)
check("§3 a broken provider never empties a picker (the list the caller passed stands)",
      _pick3.source.count() == 1, str(_pick3.source.count()))
_pick2.deleteLater()
_pick3.deleteLater()
check("§3 the dialog imports no scene module (the module + callbacks discipline)",
      "map_scene" not in open(os.path.join(ROOT, "dialogs", "connection_dialog.py"),
                              encoding="utf-8").read())


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the report's pure half (task 4) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the columns are declared ONCE (five, in reading order)",
      [f for f, _k in EP.PROBLEM_COLUMNS] == ["alias", "host", "status", "reason", "checked"],
      str(EP.PROBLEM_COLUMNS))
check("§4 ... and they are the report's OWN captions (not the inventory's columns)",
      all(k.startswith("report.problems.") for _f, k in EP.PROBLEM_COLUMNS))
check("§4 the predicate is IMPORTED, never restated (ONE rule for lens, aggregate, report)",
      EP.is_in_trouble is is_in_trouble
      and "def is_in_trouble" not in open(os.path.join(ROOT, "storage", "export_problems.py"),
                                          encoding="utf-8").read())

_healthy = FakeNode("h", "web-1", "10.0.0.1", status="online", age="checked just now")
_offline = FakeNode("o", "db-1", "10.0.0.2", status="offline", age="checked 4 min ago")
_stale = FakeNode("s", "cache", "10.0.0.3", status="online", stale=True, age="checked 2 h ago")
_warn = FakeNode("w", "edge", "10.0.0.4", status="warn", stale=True, age="checked 9 min ago")
_unchecked = FakeNode("u", "new", "10.0.0.5", status="")
_unmanaged = FakeNode("m", "neighbour", "192.0.2.9", status="", stale=False)
_FIXTURE = [_healthy, _offline, _stale, _warn, _unchecked, _unmanaged]

check("§4 the predicate keeps warn / offline / stale and NOTHING else",
      EP.problem_nodes(_FIXTURE) == [_offline, _stale, _warn],
      str([n.data.id for n in EP.problem_nodes(_FIXTURE)]))
check("§4 an UNMANAGED, never-probed card is NEVER in the problem set (falls out of the predicate)",
      _unmanaged not in EP.problem_nodes(_FIXTURE)
      and is_in_trouble(_unmanaged.status, _unmanaged.is_stale) is False)
check("§4 an UNCHECKED card is not trouble either (there is no measurement to call a problem)",
      _unchecked not in EP.problem_nodes(_FIXTURE))

_rows_fixture = EP.problem_report_rows(_FIXTURE, _t)
check("§4 the report is the header plus ONE row per card in trouble",
      len(_rows_fixture) == 4 and _rows_fixture[0] == EP.problem_headers(_t),
      str(len(_rows_fixture)))
check("§4 every row carries exactly the declared column count",
      all(len(r) == len(EP.PROBLEM_COLUMNS) for r in _rows_fixture))
check("§4 the STATUS cell reuses the legend's own words (no fourth spelling)",
      _rows_fixture[1][2] == _t("legend.status.offline")
      and _rows_fixture[2][2] == _t("legend.status.online"),
      str([r[2] for r in _rows_fixture[1:]]))
check("§4 the REASON is the predicate's vocabulary: the status and/or the stale mark",
      _rows_fixture[1][3] == _t("legend.status.offline")
      and _rows_fixture[2][3] == _t("report.problems.stale")
      and _rows_fixture[3][3]
      == f"{_t('legend.status.warn')} \u00b7 {_t('report.problems.stale')}",
      str([r[3] for r in _rows_fixture[1:]]))
check("§4 a green-but-stale card's reason is the STALE mark alone ('Online' is not a reason)",
      EP.problem_reason("online", True, _t) == _t("report.problems.stale")
      and EP.problem_reason("online", False, _t) == "")
check("§4 the age column is the card's OWN sentence (one vocabulary for the age)",
      _rows_fixture[1][4] == "checked 4 min ago", _rows_fixture[1][4])

_quoted = FakeNode("q", 'a, "b"', "10.0.0.9", status="offline")
_text = EP.problem_report_text([_quoted], ",", _t)
check("§4 the SHARED RFC-4180 writer quotes an alias carrying a comma and a quote",
      list(csv.reader(io.StringIO(_text)))[1][0] == 'a, "b"', repr(_text))
check("§4 ... and the TSV form uses the tab (one writer, two delimiters)",
      "\t" in EP.problem_report_text([_quoted], "\t", _t).splitlines()[0])
check("§4 an all-clear map answers [] — never a header with nothing under it",
      EP.problem_report_rows([_healthy, _unchecked], _t) == [])
check("§4 an empty map answers [] as well (the caller tells the two apart by the scene)",
      EP.problem_report_rows([], _t) == [] and EP.problem_report_rows(None, _t) == [])
check("§4 a duck-typed entry without a freshness method still yields an empty cell",
      EP.problem_report_rows([FakeNode("x", "y", "z", status="warn")], _t)[1][4] == "")


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the action and its reports (task 5) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§5 ONE registry action, in the file family, with an EMPTY default",
      HR.HOTKEY_ACTIONS["file.export_problems"]["label"] == "file.export_problems"
      and HR.HOTKEY_ACTIONS["file.export_problems"]["default"] == ""
      and HR.action_family("file.export_problems") == "file",
      str(HR.HOTKEY_ACTIONS.get("file.export_problems")))
check("§5 it is an EXPORT action like its two report siblings (same family, same shape)",
      [aid for aid in ("file.copy_list", "file.export_list", "file.export_connections",
                       "file.export_problems") if aid in HR.HOTKEY_ACTIONS]
      == ["file.copy_list", "file.export_list", "file.export_connections",
          "file.export_problems"])
_export_menu = None
for _menu in win.menuBar().findChildren(QMenu):
    if _menu.title().replace("&", "") == _t("menu.export"):
        _export_menu = _menu
        break
check("§5 the action lives in the Export menu next to the connection report",
      _export_menu is not None
      and _t("file.export_problems") in [a.text() for a in _export_menu.actions()],
      str([a.text() for a in _export_menu.actions()]) if _export_menu else "no menu")
check("§5 the window exposes it as a real QAction (the hotkey target)",
      getattr(win, "act_export_problems", None) is not None)

# ── an EMPTY map: its own sentence, no file, no dialog ──────────────────────
_empty_win = make_main()
_orig_save = MW.QFileDialog.getSaveFileName
_dialog_calls = []
MW.QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (_dialog_calls.append(1), ("", ""))[1])
try:
    _empty_win.act_export_problems.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("§5 an empty map reports ITS OWN sentence (no file, not even a dialog)",
      _empty_win.statusBar().currentMessage() == _t("status.problems_no_nodes")
      and not _dialog_calls, _empty_win.statusBar().currentMessage())
close_window(_empty_win)

# ── a map where nothing needs attention: the OTHER sentence ─────────────────
_healthy_node = win.scene.add_server(ServerData(id="lm-h", alias="fine", host="10.10.0.9",
                                                user="ops", x=300.0, y=300.0))
_healthy_node.set_status("online")
app.processEvents()
MW.QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (_dialog_calls.append(1), ("", ""))[1])
try:
    win.act_export_problems.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("§5 an all-clear map reports the OTHER sentence (and still writes no file)",
      win.statusBar().currentMessage() == _t("status.problems_none")
      and len(_dialog_calls) == 0, win.statusBar().currentMessage())

# ── a map that really has problems: the file ────────────────────────────────
_problem_node = win.scene.add_server(ServerData(id="lm-p", alias='db, "1"', host="10.10.0.7",
                                                user="dba", x=600.0, y=300.0))
_problem_node.set_status("offline")
app.processEvents()
check("§5 the window's own lens and the report agree about WHO is on the list",
      sorted(n.data.id for n in win._trouble_nodes())
      == sorted(n.data.id for n in EP.problem_nodes(win.scene.nodes())),
      f"{[n.data.id for n in win._trouble_nodes()]} vs "
      f"{[n.data.id for n in EP.problem_nodes(win.scene.nodes())]}")
_saved = os.path.join(WORK, "problems.csv")
MW.QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (_dialog_calls.append(1), (_saved,
                                               "CSV — Comma Separated Values (*.csv)"))[1])
try:
    win.act_export_problems.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("§5 the file is written, with the BOM (an alias in the user's own alphabet)",
      os.path.exists(_saved)
      and open(_saved, "rb").read(3) == b"\xef\xbb\xbf")
_written = open(_saved, encoding="utf-8-sig", newline="").read()
check("§5 the file is the report of the SCENE (header + one row per problem), quoting included",
      list(csv.reader(io.StringIO(_written)))[0] == EP.problem_headers(_t)
      and list(csv.reader(io.StringIO(_written)))[1][0] == 'db, "1"',
      repr(_written[:80]))
check("§5 the report names the saved file in its own sentence",
      win.statusBar().currentMessage()
      == _t("status.problems_exported", file="problems.csv"),
      win.statusBar().currentMessage())

# ── a cancelled dialog: nothing written, nothing said, no crash ─────────────
_boxes_before = len(BOXES)
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
try:
    win.act_export_problems.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("§5 a cancelled dialog writes nothing and shows no box",
      len(BOXES) == _boxes_before and win.statusBar().currentMessage()
      != _t("status.problems_exported", file=""), str(BOXES))


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the line's closing audit — the facts the 1.6 line DECLARED (task 6) ==")
# ════════════════════════════════════════════════════════════════════════════

def _src(*parts) -> str:
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


# (1) the bulk edit's TRI-STATE and its ONE command (v1.6)
import dialogs.bulk_edit_dialog as BED  # noqa: E402
import modules.undo_commands as UC  # noqa: E402

check("§6 audit 1: the bulk edit's tri-state is declared once and its ONE command exists",
      BED.FIELD_STATES == ("unchanged", "set", "clear")
      and BED.BULK_FIELDS == ("tags", "comment", "quick_launch")
      and hasattr(UC, "CmdEditSelected") and callable(BED.changes_for),
      f"{BED.FIELD_STATES}")

# (2) the card density's measured height and its free band (v1.6)
check("§6 audit 2: the card density is ONE declared pair and the compact card drops the info block",
      __import__("ui.theme", fromlist=["x"]).DENSITIES == ("normal", "compact")
      and "_is_compact" in _src("graphics", "server_node.py")
      and "_info.hide()" in _src("graphics", "server_node.py")
      and "58 + info + 12" in _src("graphics", "server_node.py"))

# (3) the parallel-link offsets of one endpoint pair (v1.6)
check("§6 audit 3: the parallel links of ONE pair are numbered by ONE owner, keyed unordered",
      hasattr(win.scene, "refresh_connection_offsets")
      and hasattr(win.scene, "pair_arrows")
      and callable(getattr(win.scene, "connection_pair_key"))
      and win.scene.connection_pair_key("b", "a") == win.scene.connection_pair_key("a", "b")
      == ("a", "b"),
      str(win.scene.connection_pair_key("b", "a")))

# (4) the background's TWO gestures on the undo stack (v1.6)
check("§6 audit 4: both background gestures are commands on the ONE stack",
      hasattr(UC, "CmdMoveBackground") and hasattr(UC, "CmdResizeBackground")
      and issubclass(UC.CmdMoveBackground, UC._MapCommand)
      and issubclass(UC.CmdResizeBackground, UC._MapCommand))

# (5) the arrangement's PURE geometry (v1.6)
import graphics.node_group as NG  # noqa: E402

check("§6 audit 5: the arrangement geometry is PURE (no Qt item, no scene) and has one gap",
      callable(NG.arrange_positions) and NG.ARRANGE_MODES == ("vertical", "horizontal", "rows")
      and NG.ARRANGE_GAP > 0.0 and NG.resolve_arrange_mode("nonsense") == NG.ARRANGE_VERTICAL)

# (6) the toolbar's declaration (v1.6)
_TB = getattr(MW, "_VIEW_TOOLBAR_ITEMS", ())
check("§6 audit 6: the view toggles are ONE declaration of six items, wired by ONE pair",
      len(_TB) == 6 and len(getattr(MW, "_VIEW_TOOLBAR_ACTIONS", {})) == 6
      and "view.toggle_bookmarks" in [item[0] for item in _TB],
      f"{len(_TB)} items")

# (7) the glyph grid's gate (v1.6.3)
import modules.terminal_widget as TW  # noqa: E402

_grid = win.view  # the widget factory needs a canvas; the gate itself is pure
from modules.terminal_widget import TerminalWidget  # noqa: E402

_widget = TerminalWidget.__new__(TerminalWidget)  # no QApplication widget needed for metrics
check("§6 audit 7: the glyph grid has a PURE gate over a DECLARED sample and tolerance",
      callable(TW.font_grid_problems) and len(TW.FONT_GRID_SAMPLE) >= 8
      and TW.FONT_GRID_TOLERANCE_PX > 0.0 and TW.FONT_GRID_RUN_CELLS >= 10,
      f"{len(TW.FONT_GRID_SAMPLE)} glyphs")

# (8) the mouse family's ONE encoder and the Shift override (v1.6.3)
check("§6 audit 8: ONE mouse encoder, ONE routing predicate and the Shift local override",
      callable(getattr(TW.TerminalWidget, "_send_mouse", None))
      and callable(getattr(TW.TerminalWidget, "_mouse_reports_to_pty", None))
      and callable(getattr(TW.TerminalWidget, "_mouse_local_override", None))
      and TW.TerminalWidget.MOUSE_X10_LIMIT == 223
      and TW.TerminalWidget.MOUSE_MOTION_FLAG == 32)

# (9) the terminal_scroll pin's USER-INTENT rule (v1.6.4)
import modules.terminal_screen as TS  # noqa: E402

_pin_src = _src("modules", "terminal_widget.py")
check("§6 audit 9: the pin is released on USER INTENT (a keystroke) and never on output",
      "def _release_pin" in _pin_src and "self._release_pin()" in _pin_src
      and TS.SCROLL_MODE_PIN == "pin" and TS.SCROLL_MODE_DEFAULT == "live"
      and TS.resolve_scroll_mode("nonsense") == TS.SCROLL_MODE_DEFAULT
      and callable(getattr(TS.SshmapHistoryScreen, "pin_begin", None)))

# (10) the named managed QThreads (v1.6.4)
_names = {_src("modules", "ssh_worker.py"): "SSHWorker",
          _src("modules", "sftp_worker.py"): "SftpWorker",
          _src("modules", "ssh_terminal.py"): "SSHTerminalThread",
          _src("modules", "plugin_runner.py"): "PluginCommandRunner"}
check("§6 audit 10: every managed worker NAMES itself (one objectName per worker class)",
      all(f'setObjectName("{name}")' in text for text, name in _names.items()),
      str([n for t, n in _names.items() if f'setObjectName("{n}")' not in t]))

# (11) the activity mark of an inactive session (v1.6.4)
_page_src = _src("modules", "terminal_page.py")
check("§6 audit 11: the tab mark is a SHAPE in a fixed slot, owned by the page",
      "ACTIVITY_ICON_PX" in _page_src and "def activity_tab_icon" in _page_src
      and "def note_output" in _page_src and "def set_activity" in _page_src)

# (12) the command history's MARKED secret (v1.6.4)
import modules.command_history as CH  # noqa: E402

check("§6 audit 12: the secret mark is a field of the history file that survives a fold",
      CH.SECRET_FIELD == "secret" and callable(CH.looks_like_secret)
      and callable(CH.merge_entries) and CH.MAX_ENTRIES_PER_SERVER > 0
      and CH.looks_like_secret("export TOKEN=hunter2") is not None)

# (13) the unmanaged card's ONE gate and its skip set (v1.6.5)
check("§6 audit 13: ONE gate table over the SSH verbs and a skip set that never probes them",
      UM.GATED_ACTIONS == {"ssh", "external", "collect_info", "check_status", "diagnose",
                           "ping", "ql_command"}
      and UM.action_blocked("ping", None) is False
      and "unmanaged" not in _src("services", "status_checker.py"))

# (14) the manual mode's declared horizon (v1.6.6)
import services.status_checker as SC  # noqa: E402

check("§6 audit 14: the manual cadence is a SENTINEL plus a declared one-day horizon",
      SC.MANUAL_INTERVAL_SEC == 0 and SC.MANUAL_STALE_SEC == 86400.0
      and callable(SC.resolve_interval_sec) and callable(SC.is_manual_interval)
      and SC.is_manual_interval(SC.MANUAL_INTERVAL_SEC) is True
      and SC.is_manual_interval(30) is False
      and callable(getattr(SC.StatusChecker, "set_manual_only", None))
      and callable(getattr(SC.StatusChecker, "stale_threshold_s", None)))

# (15) the two-mount disk read (v1.6.6)
import services.system_info_collector as SIC  # noqa: E402

check("§6 audit 15: the disk read asks for a mount, parses two rows and refuses a share by name",
      SIC.DISK_MOUNT_TOKEN and SIC.DISK_MOUNT_DEFAULT and "nfs" in SIC.NETWORK_FS_TYPES
      and callable(SIC.parse_disk_report) and callable(SIC.parse_disk_presence)
      and callable(SIC.resolve_disk_answer)
      and SIC.resolve_disk_answer([], False)["note"] == SIC.DISK_NOTE_MISSING
      and SIC.DISK_REFUSAL_NETWORK == "network",
      str(SIC.resolve_disk_answer([], False)))

# (16) the figures the line DECLARED and did not move
check("§6 audit 16: no pinned figure moved — LIST_COLUMNS is still 13 and VERSION_FORMAT is 0.9",
      len(SB.LIST_COLUMNS) == 13 and _version.VERSION_FORMAT == "0.9"
      and len(getattr(MW, "MODULE_FACADE_SEAMS", ())) > 0,
      f"{len(SB.LIST_COLUMNS)} columns")

close_window(win)


# ════════════════════════════════════════════════════════════════════════════
print("== §7 i18n parity and the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check(f"§7 the {len(NEW_KEYS)} keys of v1.6.8 are present and non-empty in EVERY language",
      all(str(LANGS[c].get(k, "")).strip() for k in NEW_KEYS for c in sorted(LANGS)),
      str([(c, k) for k in NEW_KEYS for c in sorted(LANGS)
           if not str(LANGS[c].get(k, "")).strip()][:4]))
check("§7 the hint's placeholder is the SAME in every language (one {add_connection})",
      all("{add_connection}" in LANGS[c]["empty.state.connect_hint"] for c in sorted(LANGS)))
check("§7 the no-match sentence carries BOTH placeholders in every language",
      all("{query}" in LANGS[c]["connection.no_match"]
          and "{name}" in LANGS[c]["connection.no_match"] for c in sorted(LANGS)))
check("§7 the report's captions are the SAME set in every language (the parity pin)",
      all(all(LANGS[c].get(k, "").strip() for k in NEW_KEYS) for c in sorted(LANGS)))
check_i18n_parity(LANGS)
check_i18n_format(LANGS)

check("§7 the pin counts the SHIPPED release (828 + the 13 keys of v1.6.8)",
      EXPECTED_I18N_KEYS == 841 and EXPECTED_I18N_KEYS == 828 + 13, str(EXPECTED_I18N_KEYS))
check("§7 EXPECTED_APP_VERSION is the release this file describes",
      EXPECTED_APP_VERSION == "1.6.8", EXPECTED_APP_VERSION)
check("§7 the registry grew by exactly ONE action (60 -> 61) and it is an EMPTY default",
      len(HR.HOTKEY_ACTIONS) == 61
      and "file.export_problems" in HR.empty_default_action_ids(),
      f"{len(HR.HOTKEY_ACTIONS)} actions")
check_release_state(ROOT)

finish()
