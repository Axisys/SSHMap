# -*- coding: utf-8 -*-
"""v1.4.6 — List mode: collapsing the map = server parameters (ROADMAP v1.4.6).

The topical test of the release (the "new topical file" convention): offscreen, no network
(the probes answer instantly) and no real terminal session.

§1 The adaptive columns (`ui/sidebar.py`): collapsing the map switches the tree to the wide
   LIST layout — 8 columns, visible headers with the `sidebar.list.*` labels, interactive
   (draggable) sections, and the panel's own minimum width untouched; expanding restores the
   narrow one-column view with NO residual column state.

§2 The cell mapping (`list_cell_values()` — a pure function, no Qt) and the live rows of a
   window: one cell per column, the values straight from `ServerData`, an EMPTY field is an
   empty cell (never "None"), the host cell carries the IP in parentheses, the CPU cell falls
   back to `cpu_model`, the tags are comma-joined.

§3 The mode switch is idempotent and stable: off → on → off keeps the item set and the
   selection, `refresh_sidebar()` in wide mode never duplicates a row, and a repeated
   `set_list_mode()` with the same value reports "nothing changed".

§4 Row actions in wide mode: the context menu offers every `CONTEXT_MENU_ITEMS` action and the
   row double click follows the pinned `ui_node_double_click` semantics ("properties" opens the
   AddServer dialog, "connect" opens the SSH dialog) while the NARROW mode keeps the v0.9.9.4
   reveal-on-map behaviour.

§5 The filters in wide mode: the search field and the tag combo narrow the TABLE exactly as
   they narrow the narrow tree (and the v1.4.5 status filter ANDs with them).

§6 The v1.2.4.1 invariants survive: "both panels collapsed" is still refused with
   `status.collapse_both_forbidden`, and the refusal never switches list mode off.

§7 Persistence: the mode IS `ui_map_collapsed` (nothing new is written) — a new window with
   the key starts in LIST mode and the collapse/expand round-trip reaches config.json.

§8 A status probe refreshes the STATUS CELL in place (no rebuild of the rows), a language
   switch re-texts the headers without throwing away a dragged width, and no column state is
   ever persisted.

§9 i18n parity + the release state (the pin `tests/_common.py`).

Run: python tests/test_list_mode.py   (from the project root) or python tests/run_all.py
"""
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHeaderView, QMessageBox

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
from ui.sidebar import (LIST_COLUMNS, CONTEXT_MENU_ITEMS, _LIST_STATUS_COLUMN,
                        list_cell_values)

# ── The harness ──────────────────────────────────────────────────────────────
from _fakes import CaptureMenu, QuestionStub

boxes = []
answers = QuestionStub(
    QMessageBox.Discard,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))

N_COLUMNS = len(LIST_COLUMNS)          # 8 — alias | host (IP) | status | OS | CPU | RAM | DISK | tags


def make_main():
    """An offscreen MainWindow with a stopped autosave timer (determinism)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    return w


def add_node(win, nid, alias, host, status="", **kw):
    """Add a node straight onto the scene + refresh (the ordinary composition hook)."""
    data = ServerData(id=nid, alias=alias, host=host, user="root", **kw)
    node = win.scene.add_server(data)
    if status:
        node.set_status(status)
    win.refresh_sidebar()
    return node


def rows(win):
    """`[(node_id, [cell, …]), …]` of the tree, top to bottom."""
    out = []
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        out.append((item.data(0, Qt.ItemDataRole.UserRole),
                    [item.text(c) for c in range(win.tree.columnCount())]))
    return out


def row_of(win, node_id):
    """The cells of ONE row (or None when the row is filtered out)."""
    for nid, cells in rows(win):
        if nid == node_id:
            return cells
    return None


def item_of(win, node_id):
    """The QTreeWidgetItem of one node (or None)."""
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.data(0, Qt.ItemDataRole.UserRole) == node_id:
            return item
    return None


def collapse_map(win, collapsed=True):
    """Collapse/expand the map through the ORDINARY QAction (every control path converges)."""
    win.act_show_map.setChecked(not collapsed)
    app.processEvents()


def close_window(win):
    """Close without the unsaved-changes question (the answer is Discard anyway)."""
    win._dirty = False
    win._undo_baseline_dirty = False
    win.close()
    app.processEvents()


# ════════════════════════════════════════════════════════════
# 1. The adaptive columns (tasks 1 + 2)
# ════════════════════════════════════════════════════════════
print("== 1. the adaptive columns ==")

clear_cfg()
win = make_main()

check("out of the box the map is expanded and the tree is NARROW (one column, no header)",
      win.tree.columnCount() == 1 and win.tree.isHeaderHidden()
      and not win.sidebar.is_list_mode())
check("the LIST layout is the 8 columns of the plan (alias | host (IP) | status | OS | CPU | RAM | DISK | tags)",
      [f for f, _k in LIST_COLUMNS] == ["alias", "host", "status", "os", "cpu", "ram", "disk", "tags"],
      str([f for f, _k in LIST_COLUMNS]))
check("every column header is an i18n key of the `sidebar.list.*` family",
      all(key.startswith("sidebar.list.") for _f, key in LIST_COLUMNS))

add_node(win, "lm-1", "WebOne", "10.10.0.1", tags=["prod"])
collapse_map(win)

check("collapsing the map switches the panel to LIST mode",
      win.sidebar.is_list_mode() and win._map_collapsed)
check("the tree now carries the full column set", win.tree.columnCount() == N_COLUMNS,
      f"columns={win.tree.columnCount()}")
check("the header is VISIBLE and carries the translated labels",
      not win.tree.isHeaderHidden()
      and [win.tree.headerItem().text(c) for c in range(N_COLUMNS)]
      == [i18n.t(key) for _f, key in LIST_COLUMNS],
      str([win.tree.headerItem().text(c) for c in range(N_COLUMNS)]))
check("the header is not the English fallback (a real translation is applied)",
      i18n.t("sidebar.list.host") == "Host (IP)"
      and win.tree.headerItem().text(1) == i18n.t("sidebar.list.host"),
      win.tree.headerItem().text(1))
check("the column widths are DRAGGABLE (QTreeWidget's interactive sections)",
      all(win.tree.header().sectionResizeMode(c) == QHeaderView.ResizeMode.Interactive
          for c in range(N_COLUMNS)))
check("the panel stays as shrinkable as before (the table does not raise its minimum)",
      win.sidebar.minimumSizeHint().width() <= win.SIDEBAR_MIN_WIDTH,
      f"panel_min={win.sidebar.minimumSizeHint().width()} sidebar_min={win.SIDEBAR_MIN_WIDTH}")

# ── back to the narrow view: no residual column state ─────────────────────────
collapse_map(win, collapsed=False)
check("expanding the map returns the tree to the narrow view",
      win.tree.columnCount() == 1 and win.tree.isHeaderHidden()
      and not win.sidebar.is_list_mode())
check("no residual header text survives the return",
      win.tree.headerItem().text(0) == "" and win.tree.headerItem().text(1) == "",
      repr(win.tree.headerItem().text(0)))
check("the narrow row is the v0.9.9.4 caption again (alias (host) + the [tags] suffix)",
      row_of(win, "lm-1") == ["WebOne  (10.10.0.1)  [prod]"], str(row_of(win, "lm-1")))

# ════════════════════════════════════════════════════════════
# 2. The cell mapping — the pure function and the live rows
# ════════════════════════════════════════════════════════════
print("== 2. the cell mapping ==")

# ── the pure function (no Qt, no scene) ───────────────────────────────────────
_full = ServerData(id="pure-1", alias="DbOne", host="10.20.0.5", user="root", ip="192.168.5.5",
                   os_name="Ubuntu 24.04 LTS", cpu="2 vCPU", ram="4 GB", disk="80 GB",
                   tags=["prod", "db"])
check("list_cell_values(): one cell per LIST_COLUMNS entry",
      len(list_cell_values(_full, "Online")) == N_COLUMNS)
check("list_cell_values(): every value comes from ServerData",
      list_cell_values(_full, "Online") == [
          "DbOne", "10.20.0.5 (192.168.5.5)", "Online", "Ubuntu 24.04 LTS",
          "2 vCPU", "4 GB", "80 GB", "prod, db"],
      str(list_cell_values(_full, "Online")))
check("list_cell_values(): the status cell is the caller's translated text (empty = not probed)",
      list_cell_values(_full, "")[_LIST_STATUS_COLUMN] == ""
      and list_cell_values(_full, "Warn")[_LIST_STATUS_COLUMN] == "Warn")
check("list_cell_values(): the CPU falls back to the auto-collected cpu_model",
      list_cell_values(ServerData(id="p2", alias="A", host="h", user="u",
                                  cpu_model="Intel Xeon E5"), "")[4] == "Intel Xeon E5")
check("list_cell_values(): host == ip is not repeated in parentheses",
      list_cell_values(ServerData(id="p3", alias="A", host="10.0.0.1", user="u",
                                  ip="10.0.0.1"), "")[1] == "10.0.0.1")
check("list_cell_values(): an empty model gives EMPTY cells, never the string \"None\"",
      list_cell_values(ServerData(id="p4", alias="A", host="h", user="u"), "") ==
      ["A", "h", "", "", "", "", "", ""],
      str(list_cell_values(ServerData(id="p4", alias="A", host="h", user="u"), "")))
check("list_cell_values(): blank tag entries are dropped from the joined cell",
      list_cell_values(ServerData(id="p5", alias="A", host="h", user="u",
                                  tags=["", "  ", "prod"]), "")[7] == "prod")

# ── the live rows of a window ─────────────────────────────────────────────────
clear_cfg()
win = make_main()
win.scene.add_server(ServerData(id="lm-rich", alias="DbMain", host="10.30.0.7", user="root",
                                ip="172.16.0.9", os_name="Debian 12", cpu="4 vCPU",
                                ram="8 GB", disk="160 GB", cpu_model="AMD EPYC",
                                tags=["prod", "db"]))
win.scene.add_server(ServerData(id="lm-bare", alias="Sparse", host="10.30.0.8", user="root"))
win.scene.get_node("lm-rich").set_status("online")
win.scene.get_node("lm-bare").set_status("warn")
win.refresh_sidebar()
collapse_map(win)

check("a fully described node fills every column from ServerData",
      row_of(win, "lm-rich") == ["DbMain", "10.30.0.7 (172.16.0.9)", i18n.t("legend.status.online"),
                                 "Debian 12", "4 vCPU", "8 GB", "160 GB", "prod, db"],
      str(row_of(win, "lm-rich")))
check("a node with empty fields has EMPTY cells (not \"None\", not the alias repeated)",
      row_of(win, "lm-bare") == ["Sparse", "10.30.0.8", i18n.t("legend.status.warn"),
                                 "", "", "", "", ""],
      str(row_of(win, "lm-bare")))
check("the status column carries the READY legend.status.* words (no fourth translation)",
      row_of(win, "lm-rich")[_LIST_STATUS_COLUMN] == i18n.t("legend.status.online")
      and row_of(win, "lm-bare")[_LIST_STATUS_COLUMN] == i18n.t("legend.status.warn"))
check("the node id still travels in column 0 (the selection sync reads it there)",
      sorted(nid for nid, _cells in rows(win)) == ["lm-bare", "lm-rich"], str(rows(win)))
check("the status dot icon is still painted on the row (the v0.8.0 marker survives)",
      all(not win.tree.topLevelItem(i).icon(0).isNull()
          for i in range(win.tree.topLevelItemCount())))

# ════════════════════════════════════════════════════════════
# 3. The switch is idempotent and stable (task 2)
# ════════════════════════════════════════════════════════════
print("== 3. idempotency and stability ==")

check("set_list_mode(True) a second time reports \"nothing changed\"",
      win.sidebar.set_list_mode(True) is False and win.sidebar.is_list_mode())
check("_sync_list_mode() with the mode already applied does not rebuild the rows",
      win._sync_list_mode() is None and win.sidebar.is_list_mode())

_before = {nid: cells for nid, cells in rows(win)}
win.scene.get_node("lm-bare").setSelected(True)
app.processEvents()

collapse_map(win, collapsed=False)
collapse_map(win, collapsed=True)
collapse_map(win, collapsed=False)
collapse_map(win, collapsed=True)
check("off → on → off → on is stable: the same rows, no duplicates, no losses",
      {nid: cells for nid, cells in rows(win)} == _before and win.tree.topLevelItemCount() == 2,
      str(rows(win)))
check("the selection survives every switch (the tree follows the scene)",
      win.tree.currentItem() is not None
      and win.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == "lm-bare")
check("the map is collapsed and the mode with it",
      win._map_collapsed and win.sidebar.is_list_mode() and win.tree.columnCount() == N_COLUMNS)

_n = win.tree.topLevelItemCount()
win.refresh_sidebar()
win.refresh_sidebar()
check("refresh_sidebar() in wide mode is idempotent (no row is duplicated)",
      win.tree.topLevelItemCount() == _n == 2 and win.tree.columnCount() == N_COLUMNS,
      f"count={win.tree.topLevelItemCount()} columns={win.tree.columnCount()}")

# ════════════════════════════════════════════════════════════
# 4. Row actions in wide mode (task 3)
# ════════════════════════════════════════════════════════════
print("== 4. row actions in wide mode ==")

_expected_menu = [i18n.t(entry[1]) for entry in CONTEXT_MENU_ITEMS if entry is not None]
_captured = []
CaptureMenu.captured = _captured
_orig_menu_cls = MW.QMenu
MW.QMenu = CaptureMenu
try:
    _item = item_of(win, "lm-rich")
    _rect = win.tree.visualItemRect(_item)
    win.tree.customContextMenuRequested.emit(QPoint(int(_rect.center().x()), int(_rect.center().y())))
    app.processEvents()
finally:
    MW.QMenu = _orig_menu_cls

_menu = _captured[-1] if _captured else None
_labels = [a.text() for a in _menu.actions() if not a.isSeparator()] if _menu else []
check("right-clicking a row of the wide TABLE still opens the row context menu",
      _menu is not None, f"captured={len(_captured)}")
check("the wide-mode row menu offers EVERY CONTEXT_MENU_ITEMS action",
      all(label in _labels for label in _expected_menu),
      f"missing={[l for l in _expected_menu if l not in _labels]} got={_labels}")

# ── the double click follows the pinned ui_node_double_click semantics ────────
_dialogs = {"properties": 0, "connect": 0}
_orig_add_dlg = MW.AddServerDialog


class _FakeAddServerDialog:
    """The editor seam: it counts the call and answers Rejected (nothing is written)."""

    def __init__(self, parent=None, edit_data=None):
        _dialogs["properties"] += 1
        self._data = edit_data

    def exec(self):
        return QDialog.Rejected

    def get_data(self):
        return self._data


MW.AddServerDialog = _FakeAddServerDialog
_orig_run_connect = MW.MainWindow._run_ssh_connect
MW.MainWindow._run_ssh_connect = lambda self, node, *a, **k: _dialogs.__setitem__(
    "connect", _dialogs["connect"] + 1)
try:
    win._node_double_click_mode = "properties"
    win._on_tree_item_double_click(item_of(win, "lm-rich"), 0)
    app.processEvents()
    check("LIST mode, ui_node_double_click=properties: the row double click opens the editor",
          _dialogs == {"properties": 1, "connect": 0}, str(_dialogs))
    check("the row's node is selected by the same gesture (the tree and the scene agree)",
          win.scene.get_selected_node() is not None
          and win.scene.get_selected_node().data.id == "lm-rich")

    win._node_double_click_mode = "connect"
    win._on_tree_item_double_click(item_of(win, "lm-rich"), 0)
    app.processEvents()
    check("LIST mode, ui_node_double_click=connect: the row double click opens the SSH dialog",
          _dialogs == {"properties": 1, "connect": 1}, str(_dialogs))

    # the NARROW mode keeps the v0.9.9.4 semantics: select + reveal, no dialog
    collapse_map(win, collapsed=False)
    win._on_tree_item_double_click(item_of(win, "lm-rich"), 0)
    app.processEvents()
    check("NARROW mode: the double click only selects/reveals (no editor, no SSH dialog)",
          _dialogs == {"properties": 1, "connect": 1}
          and win.scene.get_selected_node().data.id == "lm-rich",
          str(_dialogs))
    check("NARROW mode: the map is expanded, so the reveal path had a map to center on",
          not win._map_collapsed and not win.sidebar.is_list_mode())
    collapse_map(win)
finally:
    MW.AddServerDialog = _orig_add_dlg
    MW.MainWindow._run_ssh_connect = _orig_run_connect

# ════════════════════════════════════════════════════════════
# 5. The filters in wide mode (task 3)
# ════════════════════════════════════════════════════════════
print("== 5. search + tag filter in wide mode ==")

check("both nodes are listed", win.tree.topLevelItemCount() == 2)

win.search_edit.setText("dbmain")
app.processEvents()
check("the search filters the wide TABLE by alias",
      [nid for nid, _c in rows(win)] == ["lm-rich"], str(rows(win)))
win.search_edit.setText("172.16.0.9")
app.processEvents()
check("the search matches the IP of the host cell too",
      [nid for nid, _c in rows(win)] == ["lm-rich"], str(rows(win)))
win.search_edit.setText("")
app.processEvents()
check("clearing the search brings the table back",
      win.tree.topLevelItemCount() == 2 and win.tree.columnCount() == N_COLUMNS)

win.tag_filter.setCurrentIndex(win.tag_filter.findData("prod"))
app.processEvents()
check("the tag filter narrows the wide table to the tagged node",
      [nid for nid, _c in rows(win)] == ["lm-rich"], str(rows(win)))
check("a filtered wide table keeps the full column set (the layout is a mode, not a filter)",
      win.tree.columnCount() == N_COLUMNS and not win.tree.isHeaderHidden())

# the v1.4.5 status filter ANDs with it
win._on_status_filter_clicked("warn")
app.processEvents()
check("tag AND status in wide mode: the two filters intersect (nothing is left)",
      win.tree.topLevelItemCount() == 0, str(rows(win)))
win._on_status_filter_clicked("warn")   # reset the status filter
win.tag_filter.setCurrentIndex(0)       # reset the tag filter
app.processEvents()
check("resetting both filters lists the two nodes again",
      win.tree.topLevelItemCount() == 2 and win._status_filter == ""
      and win.tag_filter.currentIndex() == 0)

# ════════════════════════════════════════════════════════════
# 6. The "both panels" rule survives (v1.2.4.1)
# ════════════════════════════════════════════════════════════
print("== 6. both panels collapsed is still forbidden ==")

check("the map is collapsed (list mode is on)", win._map_collapsed and win.sidebar.is_list_mode())
win.act_show_sidebar.setChecked(False)   # forbidden — the sidebar holds the list
app.processEvents()
check("collapsing the sidebar next to it is refused with the v1.2.4.1 status hint",
      not win._sidebar_collapsed and win.act_show_sidebar.isChecked()
      and win.statusBar().currentMessage() == i18n.t("status.collapse_both_forbidden"),
      win.statusBar().currentMessage())
check("the refusal leaves the table intact (the list is still there to be seen)",
      win.sidebar.is_list_mode() and not win.sidebar.isHidden()
      and win.tree.columnCount() == N_COLUMNS)

collapse_map(win, collapsed=False)
check("the map expanded back: the sidebar can be collapsed again (the rule is about BOTH)",
      not win._map_collapsed)
win.act_show_sidebar.setChecked(False)
app.processEvents()
check("with the map expanded the sidebar collapses as before (no list-mode drift)",
      win._sidebar_collapsed and not win.sidebar.is_list_mode()
      and win.tree.columnCount() == 1)
win.act_show_sidebar.setChecked(True)
app.processEvents()
check("both panels are expanded and the tree is narrow again",
      not win._sidebar_collapsed and not win._map_collapsed
      and not win.sidebar.is_list_mode() and win.tree.columnCount() == 1)

close_window(win)

# ════════════════════════════════════════════════════════════
# 7. Persistence: the mode IS ui_map_collapsed (task 2)
# ════════════════════════════════════════════════════════════
print("== 7. persistence round-trip ==")

clear_cfg()
win = make_main()
collapse_map(win)
check("collapsing the map writes ui_map_collapsed=True (the v1.2.4.1 key, merge write)",
      i18n.load_config().get("ui_map_collapsed") is True)
collapse_map(win, collapsed=False)
check("expanding it writes False back",
      i18n.load_config().get("ui_map_collapsed") is False)
close_window(win)

write_cfg({"ui_map_collapsed": True, "language": "en"})
win2 = make_main()
check("a window starting with a collapsed map starts in LIST mode",
      win2._map_collapsed and win2.sidebar.is_list_mode()
      and win2.tree.columnCount() == N_COLUMNS and not win2.tree.isHeaderHidden(),
      f"collapsed={win2._map_collapsed} list={win2.sidebar.is_list_mode()} "
      f"columns={win2.tree.columnCount()}")
check("the mode is not a second persisted key (only ui_map_collapsed is written)",
      not [k for k in read_cfg({}) if "list" in k.lower() or "column" in k.lower()],
      str(sorted(read_cfg({}))))
win2.act_show_map.setChecked(True)
app.processEvents()
check("expanding from the restored state returns the narrow view",
      not win2.sidebar.is_list_mode() and win2.tree.columnCount() == 1
      and read_cfg({}).get("ui_map_collapsed") is False)
close_window(win2)

# ════════════════════════════════════════════════════════════
# 8. A live status update + a language switch in LIST mode
# ════════════════════════════════════════════════════════════
print("== 8. live status + language switch ==")

clear_cfg()
win = make_main()
add_node(win, "lm-live", "LiveOne", "10.40.0.1")
collapse_map(win)
check("the row starts with an EMPTY status cell (never probed)",
      row_of(win, "lm-live")[_LIST_STATUS_COLUMN] == "", str(row_of(win, "lm-live")))

win._on_node_status_changed("lm-live", "online")
app.processEvents()
check("a probe result updates the STATUS CELL in place (the row is not rebuilt)",
      row_of(win, "lm-live")[_LIST_STATUS_COLUMN] == i18n.t("legend.status.online"),
      str(row_of(win, "lm-live")))
win._on_node_status_changed("lm-live", "offline")
app.processEvents()
check("the next round re-texts it (online → offline)",
      row_of(win, "lm-live")[_LIST_STATUS_COLUMN] == i18n.t("legend.status.offline"))

win.tree.setColumnWidth(0, 321)          # a user-dragged width
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("a language switch re-texts the column headers in LIST mode",
      [win.tree.headerItem().text(c) for c in range(N_COLUMNS)]
      == [i18n.t(key) for _f, key in LIST_COLUMNS]
      and win.tree.headerItem().text(0) != "Alias",
      str([win.tree.headerItem().text(c) for c in range(N_COLUMNS)]))
check("the dragged width is NOT thrown away by the retranslate",
      win.tree.columnWidth(0) == 321, str(win.tree.columnWidth(0)))
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()
check("back to en the headers are the English labels again",
      win.tree.headerItem().text(0) == "Alias" == i18n.t("sidebar.list.alias"))
check("no column state is ever persisted (a layout, not project data)",
      not [k for k in read_cfg({}) if "list" in k.lower() or "column" in k.lower()],
      str(sorted(read_cfg({}))))

close_window(win)

# ════════════════════════════════════════════════════════════
# 9. i18n parity + the release state
# ════════════════════════════════════════════════════════════
print("== 9. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
new_keys = [f"sidebar.list.{field}" for field in
            ("alias", "host", "status", "os", "cpu", "ram", "disk", "tags")]
missing = [k for k in new_keys
           if any(not str(langs[c].get(k, "")).strip() for c in langs)]
check(f"the {len(new_keys)} v1.4.6 keys are present and non-empty in every language",
      not missing, str(missing))
check("the two splitter items name their state pair in every language (the VALUES changed, "
      "the keys did not)",
      all("/" in str(langs[c][k]) for c in langs
          for k in ("view.toggle_map", "view.toggle_sidebar")))
check("the status words of the table are the EXISTING legend.status.* keys (no new spelling)",
      all(f"legend.status.{s}" in langs[c] for c in langs for s in ("online", "warn", "offline"))
      and not any(k.startswith("sidebar.list.status.") for k in langs["en"]))
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
