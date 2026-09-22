# -*- coding: utf-8 -*-
"""v1.4.5 — UI density & first run (ROADMAP v1.4.5): the compact sidebar grid, the first-run
empty state, the live status bar, the legend panel and the splitter-handle rule.

The topical test of the release (the "new topical file" convention): offscreen, no network
(the probes answer instantly) and no real terminal session.

§1 The compact action grid (task 1): the six buttons of `ui/sidebar.py` — the SAME
   attributes/signals/icons/i18n keys as before, in a 2-column × 3-row grid with the compact
   row height; `retranslate()` re-texts them (and their tooltips) and `set_buttons_visible`
   still reflows the block.

§2 The first-run empty state (task 2): visible at 0 servers, the ONE button opens the
   AddServer dialog (the real `_add_server` path), hidden from the first server on, back
   after a batch delete down to zero; the import line carries the REAL File-menu labels; the
   card is mouse-transparent and the button is NOT its child (the click-through rule).

§3 The live status bar (task 3): a click on a status counter filters the sidebar, a second
   click resets, the counters keep the TOTALS, the tag filter ANDs with the status filter,
   the state is transient (never written to config.json) and a status change re-filters.

§4 The legend panel (task 4): the rows follow `theme.ARROW_TYPE_COLORS` / `theme.STATUS_COLORS`,
   the header click collapses it, the View item and the toolbar mirror stay in step, the
   position/visibility/collapsed state round-trip through config.json (a broken value → the
   default) and the panel stays out of the scene (never a scene item).

§5 The splitter handle (task 5): enabled only while BOTH panels are expanded; a collapsed
   container is capped at 18 px — a `setSizes` attempt and an external resize give the whole
   delta to the expanded panel; expanding releases the cap and re-enables the divider.

§6 i18n parity + the release state (the pin `tests/_common.py`).

Run: python tests/test_ui_density.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, read_cfg, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

app = QApplication(sys.argv)

# Network is forbidden in the tests: the status probes answer instantly.
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import i18n
from models.server import ServerData
import ui.main_window as MW
from ui import theme
from ui.sidebar import (_BUTTONS, _BUTTON_COLUMNS, _COMPACT_BUTTON_HEIGHT,
                        _COMPACT_BUTTON_MIN_WIDTH)

# ── The harness ──────────────────────────────────────────────────────────────
# QMessageBox — no modals offscreen: the default answer is Discard (the close path) and the
# deletion scenarios flip it to Yes explicitly.
from _fakes import QuestionStub

boxes = []
answers = QuestionStub(
    QMessageBox.Discard,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))


class _FakeAddServerDialog:
    """The AddServer dialog stub (the `MW.AddServerDialog` seam of the v1.1.4 facade).

    It answers Accepted and hands back a fresh ServerData, so the empty-state button goes
    through the REAL `NodeOpsMixin._add_server()` path (the undo command, the sidebar
    refresh, the empty-state sync) instead of a mocked shortcut.
    """

    instances = []

    def __init__(self, parent=None):
        self._data = ServerData(id=f"uidens{len(_FakeAddServerDialog.instances) + 1:02d}",
                                alias=f"UIdens{len(_FakeAddServerDialog.instances) + 1}",
                                host="10.90.0.1", user="root")
        self._connect_after_accept = False
        _FakeAddServerDialog.instances.append(self)

    def exec(self):
        return QDialog.Accepted

    def get_data(self):
        return self._data


_orig_add_dlg = MW.AddServerDialog
MW.AddServerDialog = _FakeAddServerDialog


def make_main():
    """An offscreen MainWindow with a stopped autosave timer (determinism)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    return w


def add_node(win, nid, alias, host, status="", tags=None):
    """Add a node straight onto the scene (the fixtures of §3 use their own statuses)."""
    data = ServerData(id=nid, alias=alias, host=host, user="root", tags=list(tags or []))
    node = win.scene.add_server(data)
    if status:
        node.set_status(status)
    win.refresh_sidebar()
    return node


def close_window(win):
    """Close without the unsaved-changes question (the answer is Discard anyway)."""
    win._dirty = False
    win._undo_baseline_dirty = False
    win.close()
    app.processEvents()


# ════════════════════════════════════════════════════════════
# 1. The compact action grid (task 1)
# ════════════════════════════════════════════════════════════
print("== 1. the compact action grid ==")

clear_cfg()
# The "Settings" button opens the modal settings hub (offscreen `exec()` would block): the
# slot is replaced at the CLASS level BEFORE the window is built, so the connection the
# panel makes in _setup_ui lands on the recorder.
_clicks = {"add": 0, "settings": 0, "delete": 0}
_orig_settings_slot = MW.MainWindow._open_settings_dialog
MW.MainWindow._open_settings_dialog = lambda self: _clicks.__setitem__(
    "settings", _clicks["settings"] + 1)
try:
    win = make_main()
finally:
    MW.MainWindow._open_settings_dialog = _orig_settings_slot

check("the six buttons still exist under their public attributes",
      all(getattr(win, attr, None) is not None for attr, *_r in _BUTTONS))
check("the buttons live in the grid: 2 columns × 3 rows (v1.4.5)",
      win.sidebar.buttons_grid.count() == 6 and _BUTTON_COLUMNS == 2,
      f"count={win.sidebar.buttons_grid.count()} columns={_BUTTON_COLUMNS}")
_positions = {}
for _i, (_attr, *_r) in enumerate(_BUTTONS):
    _item = win.sidebar.buttons_grid.getItemPosition(_i)
    _positions[_attr] = _item
check("the grid places the six buttons on three rows of two (row/column of each widget)",
      sorted({p[0] for p in _positions.values()}) == [0, 1, 2]
      and sorted({p[1] for p in _positions.values()}) == [0, 1],
      str(_positions))
check("the compact row height is the dense one (< the full-width 34 px of v1.1.2RC2)",
      all(getattr(win, a).minimumHeight() == _COMPACT_BUTTON_HEIGHT for a, *_r in _BUTTONS)
      and _COMPACT_BUTTON_HEIGHT < 34,
      f"height={_COMPACT_BUTTON_HEIGHT}")
check("the alignment rule survived the compaction (text-align: left + padding-left)",
      all("text-align: left" in getattr(win, a).styleSheet()
          and "padding-left" in getattr(win, a).styleSheet() for a, *_r in _BUTTONS))
# A QPushButton's minimumSizeHint IS its sizeHint (the whole label), so two columns of
# buttons would have set the SIDEBAR's minimum width to the sum of two labels (~428 px —
# measured) and the splitter could never return to its 250/950 default. The cells carry an
# explicit small minimum instead, and the panel stays as shrinkable as it always was.
check("the compact cells keep the sidebar SHRINKABLE (a small explicit width minimum)",
      all(getattr(win, a).minimumWidth() == _COMPACT_BUTTON_MIN_WIDTH
          and _COMPACT_BUTTON_MIN_WIDTH < 100 for a, *_r in _BUTTONS)
      and win.sidebar.minimumSizeHint().width() <= win.SIDEBAR_MIN_WIDTH,
      f"panel_min={win.sidebar.minimumSizeHint().width()} "
      f"cell={_COMPACT_BUTTON_MIN_WIDTH} sidebar_min={win.SIDEBAR_MIN_WIDTH}")
check("every button keeps its vector icon and carries its full label as a tooltip",
      all(not getattr(win, a).icon().isNull() for a, *_r in _BUTTONS)
      and all(getattr(win, a).toolTip() == i18n.t(_key) for a, _ic, _key, _ru in _BUTTONS),
      str({a: getattr(win, a).toolTip() for a, *_r in _BUTTONS}))

# the signals still fire from the compact cells (the panel -> window wiring is untouched):
# Add (the fake dialog), Settings (the recorded slot) and Delete (nothing selected -> the
# stubbed information box).
win.sidebar.add_server_clicked.connect(lambda: _clicks.__setitem__("add", _clicks["add"] + 1))
win.sidebar.delete_selected_clicked.connect(
    lambda: _clicks.__setitem__("delete", _clicks["delete"] + 1))
win.btn_add.click()
win.btn_settings.click()
win.btn_delete.click()
app.processEvents()
check("the button signals still fire from the compact cells (add / settings / delete)",
      _clicks == {"add": 1, "settings": 1, "delete": 1}, str(_clicks))
check("the Add button really opened the dialog and created its server",
      win.scene.node_count() == 1, str(win.scene.node_count()))
# clean up the node the click created (the empty state of §2 is a fresh window)
win._dirty = False
win._undo_baseline_dirty = False

# the UI language switch re-texts the buttons AND their tooltips
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("retranslate(): the compact buttons follow the language (text + tooltip)",
      win.btn_add.text() == i18n.t("btn.add_server")
      and win.btn_add.toolTip() == i18n.t("btn.add_server")
      and win.btn_add.text() != "Add Server",
      f"{win.btn_add.text()!r} / {win.btn_add.toolTip()!r}")
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()
check("back to en: the label and the tooltip are restored",
      win.btn_add.text() == i18n.t("btn.add_server"))

# the button block can still be hidden/shown as a whole (the v1.1.1 option)
win.sidebar.set_buttons_visible(False)
app.processEvents()
check("set_buttons_visible(False): the whole compact grid is hidden",
      all(not getattr(win, a).isVisible() for a, *_r in _BUTTONS))
win.sidebar.set_buttons_visible(True)
app.processEvents()
check("set_buttons_visible(True): the six cells are back",
      all(getattr(win, a).isVisible() for a, *_r in _BUTTONS))

close_window(win)

# ════════════════════════════════════════════════════════════
# 2. The first-run empty state (task 2)
# ════════════════════════════════════════════════════════════
print("== 2. the first-run empty state ==")

clear_cfg()
win = make_main()
overlay = win.empty_state

check("0 servers: the hint is visible (the card AND its button)",
      overlay.is_state_visible() and overlay.isVisible()
      and overlay.btn_add_first.isVisible(),
      f"state={overlay.is_state_visible()} card={overlay.isVisible()} "
      f"btn={overlay.btn_add_first.isVisible()}")
check("the hint does not block the canvas: the card is mouse-transparent",
      overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
check("the ONE interactive piece is a SIBLING (a child of the view, not of the card)",
      overlay.btn_add_first.parentWidget() is win.view
      and not overlay.findChildren(QPushButton),
      f"parent={overlay.btn_add_first.parentWidget()}")
check("the button carries the v1.4.5 label", 
      overlay.btn_add_first.text() == i18n.t("empty.state.add_first"),
      overlay.btn_add_first.text())
check("the hint line points at the REAL File-menu labels (never a copy)",
      i18n.t("file.import_servers") in overlay.hint_text()
      and i18n.t("file.import_ssh_config") in overlay.hint_text(),
      overlay.hint_text())
check("the card is placed inside the view (a floating child, not a scene item)",
      0 <= overlay.x() and overlay.x() + overlay.width() <= win.view.width()
      and not any(it is overlay for it in win.scene.items()))

# a narrow map (the sidebar minimum + the map minimum) must not push the card off the canvas
win.resize(430, 800)
app.processEvents()
check("a narrow map: the card and its button stay inside the view (the sentences elide)",
      overlay.x() >= 0 and overlay.x() + overlay.width() <= win.view.width()
      and overlay.btn_add_first.x() + overlay.btn_add_first.width() <= win.view.width(),
      f"card={overlay.geometry()} btn={overlay.btn_add_first.geometry()} "
      f"view={win.view.width()}")
win.resize(1200, 800)
app.processEvents()

# the button opens the ordinary AddServer path -> a node -> the hint goes away
_before = len(_FakeAddServerDialog.instances)
QTest.mouseClick(overlay.btn_add_first, Qt.MouseButton.LeftButton)
app.processEvents()
check("the button opened the AddServer dialog and added its server",
      len(_FakeAddServerDialog.instances) == _before + 1 and win.scene.node_count() == 1,
      f"dialogs={len(_FakeAddServerDialog.instances)} nodes={win.scene.node_count()}")
check("with the first server the hint is hidden (both widgets)",
      not overlay.is_state_visible() and not overlay.isVisible()
      and not overlay.btn_add_first.isVisible())
check("the reference to the button survives the hide (no teardown)",
      overlay.btn_add_first.text() == i18n.t("empty.state.add_first"))

# a batch delete down to zero brings it back
for _n in win.scene.nodes():
    _n.setSelected(True)
answers.answer = QMessageBox.Yes
win._delete_selected_nodes()
answers.answer = QMessageBox.Discard
app.processEvents()
check("batch-deleting down to zero shows the hint again",
      win.scene.node_count() == 0 and overlay.is_state_visible() and overlay.isVisible(),
      f"nodes={win.scene.node_count()} state={overlay.is_state_visible()}")

# a full project load / a direct scene change is the same hook
add_node(win, "uidens-load", "Loaded", "10.90.1.1")
check("adding a server by any path (not only the button) hides the hint",
      not overlay.is_state_visible())
win.scene.remove_server("uidens-load")
win.refresh_sidebar()
check("removing the last server shows it again", overlay.is_state_visible())

# the sentence follows the language switch (and the card is re-placed for its new width)
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("the hint follows a language switch",
      overlay.btn_add_first.text() == i18n.t("empty.state.add_first")
      and i18n.t("file.import_servers") in overlay.hint_text(),
      overlay.hint_text())
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()

close_window(win)

# ════════════════════════════════════════════════════════════
# 3. The live status bar: the status filter (task 3)
# ════════════════════════════════════════════════════════════
print("== 3. the live status bar ==")

clear_cfg()
win = make_main()
add_node(win, "uidens-on", "OnlineOne", "10.91.0.1", status="online", tags=["prod"])
add_node(win, "uidens-warn", "WarnOne", "10.91.0.2", status="warn")
add_node(win, "uidens-off", "OfflineOne", "10.91.0.3", status="offline", tags=["prod"])

check("three clickable counters (one per status) + the servers/connections label",
      set(win.status_filter_labels) == {"online", "warn", "offline"}
      and win.counts_label.text() == i18n.t("status.counts", servers=3, connections=0),
      f"labels={sorted(win.status_filter_labels)} counts={win.counts_label.text()!r}")
check("each counter shows its own total",
      win.status_filter_labels["offline"].text() == i18n.t("statusbar.filter.offline", count=1)
      and win.status_filter_labels["online"].text() == i18n.t("statusbar.filter.online", count=1)
      and win.status_filter_labels["warn"].text() == i18n.t("statusbar.filter.warn", count=1),
      str({s: l.text() for s, l in win.status_filter_labels.items()}))
check("the counters explain the gesture in a tooltip",
      win.status_filter_labels["offline"].toolTip() == i18n.t("statusbar.filter.tooltip"))
check("no filter is applied out of the box",
      win._status_filter == "" and not any(l.is_active() for l in win.status_filter_labels.values()))

_cfg_before = read_cfg({})

# a click on "Offline: 1" -> only the offline node in the tree
QTest.mouseClick(win.status_filter_labels["offline"], Qt.MouseButton.LeftButton)
app.processEvents()
_rows = [win.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
         for i in range(win.tree.topLevelItemCount())]
check("a click on the offline counter filters the tree to the offline node",
      _rows == ["uidens-off"], str(_rows))
check("the filter is visible: the counter is marked active",
      win.status_filter_labels["offline"].is_active()
      and not win.status_filter_labels["online"].is_active())
check("the active filter is reported in the status bar",
      win.statusBar().currentMessage() == i18n.t("statusbar.filter.active",
                                                 status=i18n.t("legend.status.offline")),
      win.statusBar().currentMessage())
check("the counters still show the TOTALS (a filter is a view, not a fact)",
      win.counts_label.text() == i18n.t("status.counts", servers=3, connections=0)
      and win.status_filter_labels["online"].text()
      == i18n.t("statusbar.filter.online", count=1))

# a second click -> reset
QTest.mouseClick(win.status_filter_labels["offline"], Qt.MouseButton.LeftButton)
app.processEvents()
check("a second click resets the filter (the full list is back)",
      win._status_filter == "" and win.tree.topLevelItemCount() == 3
      and not win.status_filter_labels["offline"].is_active(),
      f"filter={win._status_filter!r} rows={win.tree.topLevelItemCount()}")

# the status filter ANDs with the tag filter
_idx = win.tag_filter.findData("prod")
win.tag_filter.setCurrentIndex(_idx)
app.processEvents()
check("the tag filter alone keeps the two tagged nodes",
      win.tree.topLevelItemCount() == 2, str(win.tree.topLevelItemCount()))
QTest.mouseClick(win.status_filter_labels["online"], Qt.MouseButton.LeftButton)
app.processEvents()
_rows = [win.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
         for i in range(win.tree.topLevelItemCount())]
check("tag AND status: only the node that passes both stays",
      _rows == ["uidens-on"], str(_rows))
win.tag_filter.setCurrentIndex(0)   # "All tags"
QTest.mouseClick(win.status_filter_labels["online"], Qt.MouseButton.LeftButton)
app.processEvents()
check("the tag combo is back to 'All tags' and the status filter is off",
      win.tree.topLevelItemCount() == 3 and win._status_filter == "")

# a status change re-filters the tree while a filter is active
QTest.mouseClick(win.status_filter_labels["offline"], Qt.MouseButton.LeftButton)
app.processEvents()
check("the offline filter is on: 1 row", win.tree.topLevelItemCount() == 1)
win._on_node_status_changed("uidens-on", "offline")
app.processEvents()
check("a node that BECOMES offline joins the filtered tree (and the counters follow)",
      win.tree.topLevelItemCount() == 2
      and win.status_filter_labels["offline"].text()
      == i18n.t("statusbar.filter.offline", count=2),
      f"rows={win.tree.topLevelItemCount()}")
QTest.mouseClick(win.status_filter_labels["offline"], Qt.MouseButton.LeftButton)
app.processEvents()

check("the filter is TRANSIENT: nothing about it was written to config.json",
      read_cfg({}) == _cfg_before, str(read_cfg({})))

close_window(win)

# ════════════════════════════════════════════════════════════
# 4. The legend panel (task 4)
# ════════════════════════════════════════════════════════════
print("== 4. the legend panel ==")

clear_cfg()
win = make_main()
legend = win.legend

_rows = legend.rows()
_types = [(k, c) for kind, k, c in _rows if kind == "item" and k.startswith("connection.type.")]
_statuses = [(k, c) for kind, k, c in _rows if kind == "item" and k.startswith("legend.status.")]
check("the legend lists the SIX connection types of the theme, in the theme's order",
      [k for k, _c in _types] == [f"connection.type.{t}" for t in theme.ARROW_TYPE_COLORS],
      str([k for k, _c in _types]))
check("every type row carries the colour the map itself paints",
      [c for _k, c in _types] == list(theme.ARROW_TYPE_COLORS.values()),
      str([c for _k, c in _types]))
check("the legend lists the THREE statuses with their card colours",
      [k for k, _c in _statuses] == [f"legend.status.{s}" for s in theme.STATUS_COLORS]
      and [c for _k, c in _statuses] == list(theme.STATUS_COLORS.values()),
      str(_statuses))
check("the two section captions are present",
      [k for kind, k, _c in _rows if kind == "section"] == ["legend.connections",
                                                            "legend.statuses"])
check("the legend is a child of the view and NOT a scene item (out of the exports)",
      legend.parentWidget() is win.view
      and not any(it is legend for it in win.scene.items()))

# the View item + the toolbar mirror
check("the View menu carries a checkable 'Legend' item, checked with the panel",
      win.act_show_legend.isCheckable() and win.act_show_legend.isChecked()
      and legend.isVisible() and not win.act_show_legend.icon().isNull())
check("the toolbar mirrors the same state (and owns no sequence — the v1.3.3.3 rule)",
      win._legend_toolbar_btn.isCheckable()
      and win._legend_toolbar_btn.isChecked() == win.act_show_legend.isChecked()
      and win._legend_toolbar_btn.shortcut().isEmpty(),
      str(win._legend_toolbar_btn.shortcut().toString()))
check("the registry owns the action (an EMPTY default: assignable, no key)",
      win._hotkey_targets.get("view.toggle_legend") == [win.act_show_legend]
      and win.act_show_legend.shortcut().isEmpty())

# hide it from the menu -> the panel follows and the state is persisted
win.act_show_legend.setChecked(False)
app.processEvents()
check("unchecking the View item hides the panel",
      not legend.isVisible() and i18n.load_config().get("ui_legend") is False)
check("the toolbar mirror followed the menu item (blocked signals, no loop)",
      not win._legend_toolbar_btn.isChecked())
# show it again from the TOOLBAR (the mirror drives the owner)
win._legend_toolbar_btn.setChecked(True)
app.processEvents()
check("clicking the toolbar button shows the panel and re-checks the menu item",
      legend.isVisible() and win.act_show_legend.isChecked()
      and i18n.load_config().get("ui_legend") is True)
check("the toolbar button owns no sequence after the live toggle either",
      win._legend_toolbar_btn.shortcut().isEmpty())

# the collapse gesture: a click on the title band
_open_h = legend.height()
QTest.mouseClick(legend, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(8, 6))
app.processEvents()
check("a click on the title band folds the panel down to the band",
      legend.is_collapsed() and legend.height() == legend.HEADER_H < _open_h
      and i18n.load_config().get("ui_legend_collapsed") is True,
      f"h={legend.height()} open={_open_h}")
QTest.mouseClick(legend, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(8, 6))
app.processEvents()
check("a second click unfolds it (and persists the open state)",
      not legend.is_collapsed() and legend.height() == _open_h
      and i18n.load_config().get("ui_legend_collapsed") is False)

# the drag gesture (a press in the body, a move, a release) persists the position
_start = legend.pos()
QTest.mousePress(legend, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(20, legend.height() - 6))
QTest.mouseMove(legend, QPoint(20 + 90, legend.height() - 6 + 40))
app.processEvents()
QTest.mouseRelease(legend, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(20 + 90, legend.height() - 6 + 40))
app.processEvents()
_saved = i18n.load_config().get("ui_legend_position")
check("dragging the panel moves it and persists {x, y}",
      legend.pos() != _start and isinstance(_saved, dict) and _saved.get("x") == legend.x()
      and _saved.get("y") == legend.y(),
      f"start={_start} now={legend.pos()} saved={_saved}")

win._dirty = False
win.close()
app.processEvents()

# the config round-trip: a new window restores visibility / collapsed / position
merge_position = {"x": 60, "y": 120}
write_cfg({"ui_legend": False, "ui_legend_collapsed": True, "ui_legend_position": merge_position,
           "language": "en"})
win2 = make_main()
check("a new window applies the saved state (hidden + folded + the saved spot)",
      not win2.act_show_legend.isChecked() and not win2.legend.isVisible()
      and win2.legend.is_collapsed() and win2.legend.pos() == QPoint(60, 120),
      f"visible={win2.legend.isVisible()} collapsed={win2.legend.is_collapsed()} "
      f"pos={win2.legend.pos()}")
close_window(win2)

# a broken value -> the default (visible, unfolded, the bottom-left corner)
write_cfg({"ui_legend": "yes", "ui_legend_collapsed": 1, "ui_legend_position": ["a", "b"]})
win3 = make_main()
check("a broken ui_legend* value falls back to the default (visible, unfolded)",
      win3.legend.isVisible() and not win3.legend.is_collapsed()
      and win3._legend_pos is None)
check("with no saved position the panel sits in the bottom-LEFT corner (the free one)",
      win3.legend.x() == win3.LEGEND_MARGIN
      and win3.legend.y() + win3.legend.height() <= win3.view.height(),
      f"pos={win3.legend.pos()} view={win3.view.width()}x{win3.view.height()}")
# a saved spot outside the view is clamped, not obeyed
win3._legend_pos = QPoint(10 ** 5, 10 ** 5)
win3._position_legend()
check("a saved position outside the view is clamped inside it",
      win3.legend.x() + win3.legend.width() <= win3.view.width()
      and win3.legend.y() + win3.legend.height() <= win3.view.height(),
      f"pos={win3.legend.pos()} view={win3.view.width()}x{win3.view.height()}")
check("the legend follows the theme switch (its colours are read live)",
      callable(getattr(win3.legend, "refresh_theme", None)))
win3.refresh_theme()
check("refresh_theme() walks the legend without raising",
      True, "")

# the panel must not take part in "fit to content"
add_node(win3, "uidens-fit", "FitNode", "10.92.0.1")
win3.legend.setVisible(True)
_rect_before = win3.view.content_bounding_rect()
win3._fit_to_content()
app.processEvents()
check("the legend is not part of the map content the fit frames",
      win3.view.content_bounding_rect() == _rect_before,
      f"{_rect_before} -> {win3.view.content_bounding_rect()}")

close_window(win3)

# ════════════════════════════════════════════════════════════
# 5. The splitter handle (task 5)
# ════════════════════════════════════════════════════════════
print("== 5. the splitter handle ==")

STRIP_W = 18
clear_cfg()
win = make_main()
handle = win._splitter.handle(0)

check("both panels expanded: the handle is ENABLED",
      handle.isEnabled() and win._sidebar_container.maximumWidth() > STRIP_W
      and win._map_container.maximumWidth() > STRIP_W)
check("the handle explains its rule in a tooltip",
      handle.toolTip() == i18n.t("view.splitter_handle_tooltip"), handle.toolTip())

# collapse the sidebar -> the handle is disabled and the container is capped at 18 px
win.act_show_sidebar.setChecked(False)
app.processEvents()
check("the sidebar collapsed: the handle is DISABLED",
      not handle.isEnabled() and win._sidebar_collapsed)
check("the collapsed container is capped at the strip width (the invariant)",
      win._sidebar_container.maximumWidth() == STRIP_W
      and win._sidebar_container.width() == STRIP_W,
      f"max={win._sidebar_container.maximumWidth()} w={win._sidebar_container.width()}")

# a setSizes attempt cannot stretch the strip any more (the drift this release fixes)
win._splitter.setSizes([500, 700])
app.processEvents()
check("setSizes([500, …]) cannot stretch the collapsed strip (it stays 18 px)",
      win._sidebar_container.width() == STRIP_W,
      f"w={win._sidebar_container.width()}")
# an external resize gives the whole delta to the expanded panel
_width_before = win._map_container.width()
win.resize(1500, 800)
app.processEvents()
check("an external window resize keeps the strip at 18 px and grows the expanded panel",
      win._sidebar_container.width() == STRIP_W
      and win._map_container.width() > _width_before,
      f"strip={win._sidebar_container.width()} map={win._map_container.width()} "
      f"(was {_width_before})")

# expanding releases the cap and re-enables the divider
win.act_show_sidebar.setChecked(True)
app.processEvents()
check("expanding the sidebar re-enables the handle and releases the width cap",
      handle.isEnabled() and win._sidebar_container.maximumWidth() > STRIP_W
      and win._sidebar_container.minimumWidth() == win.SIDEBAR_MIN_WIDTH,
      f"max={win._sidebar_container.maximumWidth()} "
      f"min={win._sidebar_container.minimumWidth()}")
check("the expanded panel is free again within its minimum",
      win._sidebar_container.width() >= win.SIDEBAR_MIN_WIDTH,
      str(win._sidebar_container.width()))

# the same rule for the map, AND the "both can never be collapsed" invariant
win.act_show_map.setChecked(False)
app.processEvents()
check("the map collapsed: the handle is disabled and the map container is 18 px",
      not handle.isEnabled() and win._map_container.maximumWidth() == STRIP_W
      and win._map_container.width() == STRIP_W)
win.act_show_sidebar.setChecked(False)   # forbidden: both would be strips
app.processEvents()
check("the second collapse is still refused (the v1.2.4.1 rule survives)",
      not win._sidebar_collapsed and win.act_show_sidebar.isChecked()
      and win.statusBar().currentMessage() == i18n.t("status.collapse_both_forbidden"))
win.act_show_map.setChecked(True)
app.processEvents()
check("after expanding the map the divider is enabled again (both panels back)",
      handle.isEnabled() and win._map_container.maximumWidth() > STRIP_W)
close_window(win)

# the height cap survives a restart (the state is applied after the splitter restore)
write_cfg({"ui_sidebar_collapsed": True, "language": "en"})
win4 = make_main()
check("a window starting with a collapsed sidebar disables the handle and caps the container",
      not win4._splitter.handle(0).isEnabled()
      and win4._sidebar_container.maximumWidth() == STRIP_W
      and win4._sidebar_container.width() == STRIP_W,
      f"enabled={win4._splitter.handle(0).isEnabled()} "
      f"max={win4._sidebar_container.maximumWidth()}")
win4.act_show_sidebar.setChecked(True)
app.processEvents()
check("expanding it restores the divider for the session",
      win4._splitter.handle(0).isEnabled()
      and win4._sidebar_container.maximumWidth() > STRIP_W)
close_window(win4)
MW.AddServerDialog = _orig_add_dlg

# ════════════════════════════════════════════════════════════
# 6. i18n parity + the release state
# ════════════════════════════════════════════════════════════
print("== 6. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
new_keys = ["empty.state.title", "empty.state.add_first", "empty.state.import_hint",
            "statusbar.filter.online", "statusbar.filter.warn", "statusbar.filter.offline",
            "statusbar.filter.tooltip", "statusbar.filter.active",
            "legend.title", "legend.connections", "legend.statuses",
            "legend.status.online", "legend.status.warn", "legend.status.offline",
            "legend.tooltip", "view.toggle_legend", "view.splitter_handle_tooltip"]
missing = [k for k in new_keys
           if any(not str(langs[c].get(k, "")).strip() for c in langs)]
check(f"the {len(new_keys)} v1.4.5 keys are present and non-empty in every language",
      not missing, str(missing))
check("status.counts lost its status figures (they are widgets of their own now)",
      "{online}" not in langs["en"]["status.counts"]
      and "{servers}" in langs["en"]["status.counts"]
      and all("{count}" in langs[c][f"statusbar.filter.{s}"]
              for c in langs for s in ("online", "warn", "offline")))
check("the import hint carries both placeholders in every language",
      all("{import_txt}" in langs[c]["empty.state.import_hint"]
          and "{import_ssh}" in langs[c]["empty.state.import_hint"] for c in langs))
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
