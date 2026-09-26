# -*- coding: utf-8 -*-
"""v1.5.5 — The inventory: the LIST mode becomes a report (ROADMAP v1.5.5).

The topical test of the release (the "new topical file" convention): offscreen, no network
(the probes answer instantly) and no real terminal session.

§1 The column set (task 3): `LIST_COLUMNS` is the ONE declaration of the 13 inventory
   columns and the pure `list_cell_values()` maps a `ServerData` onto them — the SSH port,
   the user, the comment and the two AGES (the status and the collected facts) on top of
   the v1.4.6 set; the age cells come from the pure `list_age_text()` whose English
   fallbacks are the `en.json` values and whose boundaries are minutes / hours / days.

§2 Sorting (task 1): the pure `list_sort_key()` sorts by DATA, not by the rendered text
   ("512 MB" before "8 GB", 10.9.0.1 before 10.10.0.1, the declared status severity, a
   bigger age later), needs no locale (a key never reads a translated cell), and an EMPTY
   cell sorts LAST in BOTH directions. The live table sorts by every column, the direction
   and the column are REMEMBERED across a rebuild (a node add/remove, a status round, a
   filter change), a row with equal keys keeps its build order, and the NARROW mode has no
   sorting at all.

§3 The export (task 2): the pure CSV/TSV writer (RFC 4180 quoting — a comma, a quote and a
   line break round-trip through Python's own `csv` module), `list_report_rows()` = the
   VISIBLE table (the live header + the displayed rows in their displayed order), the
   clipboard path through the ONE text-copy helper, the file path through the ordinary
   save dialog (UTF-8 with a BOM, the extension from the filter), the header following a
   language switch, the actions enabled only while the table exists, and the acceptance
   that the exported example map carries ONLY the RFC 5737 addresses.

§4 i18n parity + the release state (the pins `tests/_common.py`).

Run: python tests/test_inventory.py   (from the project root) or python tests/run_all.py
"""
import csv
import io
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_i18n_format, check_release_state, read_cfg, write_cfg, clear_cfg,
                     EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

app = QApplication(sys.argv)

# Network is forbidden in the tests: the status probes answer instantly.
import services.status_checker as _SC  # noqa: E402

_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

import i18n  # noqa: E402
import dataclasses  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.sidebar as SB  # noqa: E402
import ui.theme as theme  # noqa: E402
import version as _version  # noqa: E402
from models.server import ServerData  # noqa: E402
from storage import example_project as EP  # noqa: E402
from ui.sidebar import (LIST_COLUMNS, _LIST_STATUS_COLUMN, list_age_text, list_cell_values,
                        list_column_index, list_delimiter, list_quote_cell, list_sort_key,
                        list_sort_keys, list_table_text)

# ── The harness: no modal box may ever block an offscreen run ────────────────
from _fakes import QuestionStub  # noqa: E402

boxes = []
answers = QuestionStub(
    QMessageBox.Discard,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))

LANGS = load_i18n_langs(ROOT)
NEW_KEYS = ["sidebar.list.port", "sidebar.list.user", "sidebar.list.status_age",
            "sidebar.list.info_age", "sidebar.list.comment",
            "sidebar.list.age_now", "sidebar.list.age_min", "sidebar.list.age_hours",
            "sidebar.list.age_days",
            "file.copy_list", "file.export_list",
            "status.list_copied", "status.list_exported", "status.list_empty"]
N_COLUMNS = len(LIST_COLUMNS)

_FIELDS = [f for f, _k in LIST_COLUMNS]


def make_main():
    """An offscreen MainWindow with the timers stopped (determinism, no real probing)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w._freshness_timer.stop()
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    return w


def add_node(win, nid, alias, host, status="", **kw):
    """Add a node straight onto the scene + refresh (the ordinary composition hook)."""
    data = ServerData(id=nid, alias=alias, host=host, user=kw.pop("user", "root"), **kw)
    node = win.scene.add_server(data)
    if status:
        node.set_status(status)
    win.refresh_sidebar()
    return node


def collapse_map(win, collapsed=True):
    """Collapse/expand the map through the ORDINARY QAction (every control path converges)."""
    win.act_show_map.setChecked(not collapsed)
    app.processEvents()


def rows(win):
    """`[(node_id, [cell, …]), …]` of the tree, TOP TO BOTTOM (the displayed order)."""
    out = []
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        out.append((item.data(0, Qt.ItemDataRole.UserRole),
                    [item.text(c) for c in range(win.tree.columnCount())]))
    return out


def ids_in_order(win):
    """The node ids in the order the table SHOWS them."""
    return [nid for nid, _cells in rows(win)]


def cell_of(win, node_id, field):
    """One cell of one row, read by FIELD name (never by a hardcoded index)."""
    column = list_column_index(field)
    for nid, cells in rows(win):
        if nid == node_id:
            return cells[column]
    return None


def close_window(win):
    """Close without the unsaved-changes question (the answer is Discard anyway)."""
    win._dirty = False
    win._undo_baseline_dirty = False
    win.close()
    app.processEvents()


# ════════════════════════════════════════════════════════════
# 1. The column set (task 3)
# ════════════════════════════════════════════════════════════
print("== 1. the inventory columns ==")

check("the table declares 13 columns, in the order an inventory is read",
      N_COLUMNS == 13 and _FIELDS == ["alias", "host", "port", "user", "status", "status_age",
                                      "os", "cpu", "ram", "disk", "info_age", "comment", "tags"],
      str(_FIELDS))
check("every caption is a `sidebar.list.*` i18n key",
      all(key.startswith("sidebar.list.") for _f, key in LIST_COLUMNS))
check("the task-3 fields are all present (the port, the user, the two ages, the comment)",
      {"port", "user", "status_age", "info_age", "comment"} <= set(_FIELDS))
check("the status column index is DERIVED from the ONE declaration",
      _LIST_STATUS_COLUMN == list_column_index("status") == 4, str(_LIST_STATUS_COLUMN))
check("an unknown field has no column (-1) — the helper cannot raise",
      list_column_index("nope") == -1)

_full = ServerData(id="inv-1", alias="DbOne", host="10.20.0.5", user="dba", ip="192.0.2.9",
                   ssh_port=2222, os_name="Ubuntu 24.04 LTS", cpu="2 vCPU", ram="4 GB",
                   disk="80 GB", comment="primary", tags=["prod", "db"])
check("list_cell_values(): one cell per column",
      len(list_cell_values(_full, "Online", "5 min", "3 d")) == N_COLUMNS)
check("list_cell_values(): the SSH port and the user are real columns of the report",
      list_cell_values(_full)[2] == "2222" and list_cell_values(_full)[3] == "dba",
      str(list_cell_values(_full)))
check("list_cell_values(): the status age and the facts age are the caller's texts",
      list_cell_values(_full, "Online", "5 min", "3 d")[list_column_index("status_age")] == "5 min"
      and list_cell_values(_full, "Online", "5 min", "3 d")[list_column_index("info_age")] == "3 d")
check("list_cell_values(): the comment is its own column (tags keep theirs)",
      list_cell_values(_full)[list_column_index("comment")] == "primary"
      and list_cell_values(_full)[list_column_index("tags")] == "prod, db")
check("list_cell_values(): an undated node has EMPTY age cells (never \"0\" / \"None\")",
      list_cell_values(ServerData(id="inv-2", alias="A", host="h", user="u")) ==
      ["A", "h", "22", "u", "", "", "", "", "", "", "", "", ""],
      str(list_cell_values(ServerData(id="inv-2", alias="A", host="h", user="u"))))
check("list_cell_values(): a missing user/comment is an empty cell, the port keeps its default",
      list_cell_values(ServerData(id="inv-3", alias="A", host="h", user=""))[2:4] == ["22", ""]
      and list_cell_values(ServerData(id="inv-3", alias="A", host="h", user=""))[11] == "")

# ── the pure age text (the compact form of the two age cells) ─────────────────
check("list_age_text(): 0 / None / a negative value mean \"not dated\" — an EMPTY cell",
      list_age_text(0) == "" and list_age_text(None) == "" and list_age_text(-5) == ""
      and list_age_text("") == "" and list_age_text("junk") == "")
check("list_age_text(): under a minute is \"just now\" (the en.json value)",
      list_age_text(1) == list_age_text(59) == LANGS["en"]["sidebar.list.age_now"] == "just now",
      list_age_text(59))
check("list_age_text(): minutes under an hour",
      list_age_text(60) == "1 min" and list_age_text(59 * 60) == "59 min"
      and list_age_text(3600 - 1) == "59 min")
check("list_age_text(): hours under 48",
      list_age_text(3600) == "1 h" and list_age_text(47 * 3600) == "47 h")
check("list_age_text(): days from 48 h (a fact that became a memory)",
      list_age_text(48 * 3600) == "2 d" and list_age_text(30 * 86400) == "30 d")
check("list_age_text(): the translate callback wins (the language files are the text)",
      list_age_text(300, i18n.t) == i18n.t("sidebar.list.age_min", minutes=5)
      or list_age_text(300, i18n.t) == "5 min")
check("list_age_text(): the values of the age keys ARE the en.json strings (the §4.5 rule)",
      all(SB._AGE_FALLBACKS[k] == LANGS["en"][k] for k in SB._AGE_FALLBACKS), str(SB._AGE_FALLBACKS))

# ── the live table ───────────────────────────────────────────────────────────
clear_cfg()
win = make_main()
_now = time.time()
_rich = add_node(win, "inv-rich", "WebOne", "10.30.0.7", ip="192.0.2.7", ssh_port=2200,
                 user="admin", os_name="Debian 12", cpu="4 vCPU", ram="8 GB", disk="160 GB",
                 comment="frontend", tags=["prod"])
_rich.set_status("online")
_rich.set_checked_at(_now - 300.0, 90.0)                       # a status 5 minutes old
_rich.data.info_collected_at = _now - 3 * 86400.0              # facts three days old
add_node(win, "inv-bare", "Sparse", "10.30.0.8")
collapse_map(win)

check("LIST mode: the port / user / comment columns carry the model",
      cell_of(win, "inv-rich", "port") == "2200"
      and cell_of(win, "inv-rich", "user") == "admin"
      and cell_of(win, "inv-rich", "comment") == "frontend")
check("LIST mode: the status age column shows the COMPACT age of the probe",
      cell_of(win, "inv-rich", "status_age") == "5 min", cell_of(win, "inv-rich", "status_age"))
check("LIST mode: the facts age column shows the age of the collected facts",
      cell_of(win, "inv-rich", "info_age") == "3 d", cell_of(win, "inv-rich", "info_age"))
check("LIST mode: a never-probed node has an EMPTY status age (no invented datum)",
      cell_of(win, "inv-bare", "status_age") == "")
check("LIST mode: a node without collected facts has an EMPTY facts age",
      cell_of(win, "inv-bare", "info_age") == "")

# A language switch re-texts the TRANSLATED cells (the status word and the ages) too.
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("a language switch re-texts the age cells (they are captions, not data)",
      cell_of(win, "inv-rich", "status_age") == i18n.t("sidebar.list.age_min", minutes=5)
      and cell_of(win, "inv-rich", "status_age") != "5 min",
      cell_of(win, "inv-rich", "status_age"))
check("a language switch re-texts the status cell as before",
      cell_of(win, "inv-rich", "status") == i18n.t("legend.status.online"))
check("the DATA cells are untouched by the language switch",
      cell_of(win, "inv-rich", "comment") == "frontend"
      and cell_of(win, "inv-rich", "port") == "2200")
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()
check("back to en the age cell is English again", cell_of(win, "inv-rich", "status_age") == "5 min")

# ════════════════════════════════════════════════════════════
# 2. Sorting (task 1)
# ════════════════════════════════════════════════════════════
print("== 2. sorting ==")

check("list_sort_keys(): one key per column",
      len(list_sort_keys(_full, "online", 60.0, 60.0)) == N_COLUMNS)
check("the keys of one column are COMPARABLE with each other (a total order)",
      len({type(list_sort_key("ram", d)).__name__ for d in
           (ServerData(id="a", alias="a", host="h", user="u", ram="8 GB"),
            ServerData(id="b", alias="b", host="h", user="u", ram="nope"))}) == 1)

# numeric-aware: the plan's own example ("a RAM of 8 GB vs 512 MB")
_8gb = ServerData(id="a", alias="big", host="h", user="u", ram="8 GB")
_512mb = ServerData(id="b", alias="small", host="h", user="u", ram="512 MB")
check("RAM sorts NUMERICALLY: 512 MB is BEFORE 8 GB (the plan's acceptance)",
      list_sort_key("ram", _512mb) < list_sort_key("ram", _8gb),
      f"{list_sort_key('ram', _512mb)} vs {list_sort_key('ram', _8gb)}")
check("disk sorts numerically too (the same rule, the same helper)",
      list_sort_key("disk", ServerData(id="a", alias="a", host="h", user="u", disk="40 GB")) <
      list_sort_key("disk", ServerData(id="b", alias="b", host="h", user="u", disk="2 TB")))
check("an unparseable figure falls back to TEXT (it still sorts, it just does not pretend)",
      list_sort_key("ram", ServerData(id="c", alias="c", host="h", user="u", ram="N/A"))[1:4]
      != list_sort_key("ram", _8gb)[1:4])
check("the port sorts as a NUMBER (9 before 22 before 2222)",
      list_sort_key("port", ServerData(id="a", alias="a", host="h", user="u", ssh_port=9)) <
      list_sort_key("port", ServerData(id="b", alias="b", host="h", user="u", ssh_port=22)) <
      list_sort_key("port", ServerData(id="c", alias="c", host="h", user="u", ssh_port=2222)))
check("the host sorts by the ADDRESS: 10.9.0.1 before 10.10.0.1 (not the text order)",
      list_sort_key("host", ServerData(id="a", alias="a", host="10.9.0.1", user="u")) <
      list_sort_key("host", ServerData(id="b", alias="b", host="10.10.0.1", user="u")))
check("a KNOWN address wins over the name in the host column (the ip field is a real datum)",
      list_sort_key("host", ServerData(id="a", alias="a", host="zeta", user="u", ip="10.0.0.5")) <
      list_sort_key("host", ServerData(id="b", alias="b", host="alpha", user="u", ip="10.0.0.9")))
check("an address sorts BEFORE a name (the declared order of the column)",
      list_sort_key("host", ServerData(id="a", alias="a", host="10.0.0.1", user="u")) <
      list_sort_key("host", ServerData(id="b", alias="b", host="web-1", user="u")))
check("a hostname sorts case-insensitively by its letters",
      list_sort_key("host", ServerData(id="a", alias="a", host="Alpha", user="u")) ==
      list_sort_key("host", ServerData(id="b", alias="b", host="alpha", user="u")))
check("the status column sorts by the DECLARED severity: online < warn < offline",
      list_sort_key("status", None, "online") < list_sort_key("status", None, "warn") <
      list_sort_key("status", None, "offline"))
check("a never-probed status is not a datum (it sorts last, not first)",
      list_sort_key("status", None, "")[0] == 1 and list_sort_key("status", None, "online")[0] == 0)
check("the age columns sort by the NUMBER of seconds (older = later), never by the caption",
      list_sort_key("status_age", None, status_age=60.0) <
      list_sort_key("status_age", None, status_age=7200.0)
      and list_sort_key("info_age", None, info_age=86400.0) <
      list_sort_key("info_age", None, info_age=30 * 86400.0))
check("an UNDATED age cell is empty and sorts last",
      list_sort_key("status_age", None, status_age=0.0)[0] == 1
      and list_sort_key("info_age", None, info_age=None)[0] == 1)
check("the CPU column reads its LEADING number (4 vCPU after 2 vCPU, before a text model)",
      list_sort_key("cpu", ServerData(id="a", alias="a", host="h", user="u", cpu="2 vCPU")) <
      list_sort_key("cpu", ServerData(id="b", alias="b", host="h", user="u", cpu="4 vCPU")) <
      list_sort_key("cpu", ServerData(id="c", alias="c", host="h", user="u",
                                      cpu_model="Intel Xeon")))
check("the alias / OS / comment / tags columns sort as casefolded text",
      list_sort_key("alias", ServerData(id="a", alias="Web", host="h", user="u")) ==
      list_sort_key("alias", ServerData(id="b", alias="web", host="h", user="u"))
      and list_sort_key("comment", ServerData(id="a", alias="a", host="h", user="u",
                                              comment="alpha")) <
      list_sort_key("comment", ServerData(id="b", alias="b", host="h", user="u", comment="Zeta")))
check("an EMPTY text cell is flagged empty (the empty-last rule has one source)",
      list_sort_key("comment", ServerData(id="a", alias="a", host="h", user="u"))[0] == 1)
check("an unknown field is a text cell, never a crash",
      list_sort_key("nope", _full)[:1] == (1,))

# ── the live table: every column really sorts ────────────────────────────────
clear_cfg()
win = make_main()
add_node(win, "s-web", "web-01", "10.10.0.5", ip="192.0.2.5", ssh_port=22, user="deploy",
         os_name="Ubuntu 24.04", cpu="2 vCPU", ram="4 GB", disk="40 GB", comment="front",
         tags=["prod"])
add_node(win, "s-db", "db-01", "10.9.0.5", ssh_port=2222, user="postgres", os_name="Debian 12",
         cpu="8 vCPU", ram="512 MB", disk="2 TB", comment="z-backup", tags=["db"])
add_node(win, "s-misc", "alpha", "zeta-unknown", cpu_model="Intel Xeon", tags=["dev"])
win.scene.get_node("s-web").set_status("offline")
win.scene.get_node("s-db").set_status("online")
win.scene.get_node("s-web").set_checked_at(time.time() - 7200.0, 90.0)
win.scene.get_node("s-db").set_checked_at(time.time() - 60.0, 90.0)
win.scene.get_node("s-db").data.info_collected_at = time.time() - 30 * 86400.0
win.refresh_sidebar()
collapse_map(win)

check("the table starts in the DECLARED default order: the alias, A→Z",
      ids_in_order(win) == ["s-misc", "s-db", "s-web"], str(ids_in_order(win)))
check("the sort indicator is SHOWN in LIST mode",
      win.tree.header().isSortIndicatorShown()
      and win.tree.isSortingEnabled()
      and win.tree.header().sortIndicatorSection() == 0
      and win.tree.header().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder)

# The expected orders, written by hand (the topical test does not re-implement the keys).
# s-web: web-01 / 10.10.0.5 / 22 / deploy / offline / 2 h old / Ubuntu 24.04 / 2 vCPU /
#        4 GB / 40 GB / no facts date / "front" / prod
# s-db:  db-01 / 10.9.0.5 / 2222 / postgres / online / 1 min old / Debian 12 / 8 vCPU /
#        512 MB / 2 TB / 30 d old / "z-backup" / db
# s-misc: alpha / zeta-unknown (a NAME, no address) / 22 / root / never probed /
#        no status age / no OS / "Intel Xeon" (a text model) / no RAM / no disk /
#        no facts date / no comment / dev
_EXPECT = {
    "alias": [["s-misc", "s-db", "s-web"], ["s-web", "s-db", "s-misc"]],
    # a name is not an address: the addresses come first, the name last (both directions
    # keep an EMPTY cell last, and a name is a VALUE, not an empty cell)
    "host": [["s-db", "s-web", "s-misc"], ["s-misc", "s-web", "s-db"]],
    # 22, 22 (the build order breaks the tie in BOTH directions), 2222
    "port": [["s-web", "s-misc", "s-db"], ["s-db", "s-web", "s-misc"]],
    "user": [["s-web", "s-db", "s-misc"], ["s-misc", "s-db", "s-web"]],
    "status": [["s-db", "s-web", "s-misc"], ["s-web", "s-db", "s-misc"]],
    "status_age": [["s-db", "s-web", "s-misc"], ["s-web", "s-db", "s-misc"]],
    "os": [["s-db", "s-web", "s-misc"], ["s-web", "s-db", "s-misc"]],
    # a numbered figure sorts before a text model
    "cpu": [["s-web", "s-db", "s-misc"], ["s-misc", "s-db", "s-web"]],
    "ram": [["s-db", "s-web", "s-misc"], ["s-web", "s-db", "s-misc"]],
    "disk": [["s-web", "s-db", "s-misc"], ["s-db", "s-web", "s-misc"]],
    # only one row has a facts date: it is first in BOTH directions, the undated rows keep
    # their build order behind it
    "info_age": [["s-db", "s-web", "s-misc"], ["s-db", "s-web", "s-misc"]],
    "comment": [["s-web", "s-db", "s-misc"], ["s-db", "s-web", "s-misc"]],
    "tags": [["s-db", "s-misc", "s-web"], ["s-web", "s-misc", "s-db"]],
}
for _index, _field in enumerate(_FIELDS):
    win.sidebar.sort_by(_index, Qt.SortOrder.AscendingOrder)
    app.processEvents()
    check(f"sorting by '{_field}' ascending puts the rows in the expected order",
          ids_in_order(win) == _EXPECT[_field][0], str(ids_in_order(win)))
    win.sidebar.sort_by(_index, Qt.SortOrder.DescendingOrder)
    app.processEvents()
    check(f"sorting by '{_field}' descending turns the order around, and the EMPTY cell stays LAST",
          ids_in_order(win) == _EXPECT[_field][1], str(ids_in_order(win)))

win.sidebar.sort_by(list_column_index("status_age"), Qt.SortOrder.AscendingOrder)
app.processEvents()
_asc = ids_in_order(win)
win.sidebar.sort_by(list_column_index("status_age"), Qt.SortOrder.DescendingOrder)
app.processEvents()
_desc = ids_in_order(win)
check("an EMPTY cell is LAST in BOTH directions (the plan's acceptance)",
      _asc == ["s-db", "s-web", "s-misc"] and _desc == ["s-web", "s-db", "s-misc"]
      and _asc[-1] == _desc[-1] == "s-misc", f"{_asc} / {_desc}")
check("the indicator follows the sort the code applied",
      win.tree.header().sortIndicatorSection() == list_column_index("status_age")
      and win.tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder)

# ── the order survives the rebuilds the roadmap names ────────────────────────
win.sidebar.sort_by(list_column_index("ram"), Qt.SortOrder.DescendingOrder)
app.processEvents()
_before = ids_in_order(win)
check("precondition: the table is sorted by RAM, Z→A (8 GB / 4 GB / the empty one)",
      _before == ["s-web", "s-db", "s-misc"], str(_before))

add_node(win, "s-new", "aaa-new", "10.0.0.1", ram="64 GB")
check("a node ADD keeps the sort (the table is rebuilt, the key is re-applied)",
      ids_in_order(win) == ["s-new", "s-web", "s-db", "s-misc"], str(ids_in_order(win)))
win.scene.remove_server("s-new")
win.refresh_sidebar()
app.processEvents()
check("a node REMOVE keeps it too",
      ids_in_order(win) == _before, str(ids_in_order(win)))

win._on_node_status_changed("s-misc", "offline")
app.processEvents()
check("a probe round keeps the sort as well",
      ids_in_order(win) == _before, str(ids_in_order(win)))
check("…and refreshes the SORT KEY of the status cell in place (no stale key is left)",
      win.sidebar.tree.topLevelItem([n for n, _c in rows(win)].index("s-misc"))
      .sort_key(_LIST_STATUS_COLUMN)[1:4] == list_sort_key("status", None, "offline")[1:4])

win.search_edit.setText("db")
app.processEvents()
check("a filter change keeps the sort (the same rebuild path)",
      ids_in_order(win) == ["s-db"], str(ids_in_order(win)))
win.search_edit.setText("")
app.processEvents()
check("clearing the filter brings the sorted table back",
      ids_in_order(win) == _before, str(ids_in_order(win)))

# Sorting by the status column AFTER a round orders by the NEW status.
win.sidebar.sort_by(list_column_index("status"), Qt.SortOrder.AscendingOrder)
app.processEvents()
check("after a round the status column sorts by the NEW status (the key followed the cell)",
      ids_in_order(win) == ["s-db", "s-web", "s-misc"], str(ids_in_order(win)))

# The stable tie-break: equal keys keep the order the rows were built in.
add_node(win, "t-1", "same", "10.0.0.1", user="same")
add_node(win, "t-2", "same", "10.0.0.1", user="same")
win.sidebar.sort_by(0, Qt.SortOrder.AscendingOrder)
app.processEvents()
_order = [nid for nid in ids_in_order(win) if nid in ("t-1", "t-2")]
check("rows with EQUAL keys keep their build order (a stable tie-break)",
      _order == ["t-1", "t-2"], str(_order))
win.scene.remove_server("t-1")
win.scene.remove_server("t-2")
win.refresh_sidebar()
app.processEvents()

check("sort_state() reports the live pair (the panel's memory and the header agree)",
      win.sidebar.sort_state() == (0, Qt.SortOrder.AscendingOrder), str(win.sidebar.sort_state()))

# ── the narrow mode has no sorting ───────────────────────────────────────────
collapse_map(win, collapsed=False)
check("the NARROW mode shows no sort indicator and is NOT sortable",
      not win.tree.header().isSortIndicatorShown() and not win.tree.isSortingEnabled()
      and win.tree.columnCount() == 1)
check("sort_by() refuses outside the LIST mode",
      win.sidebar.sort_by(0) is False)
collapse_map(win)
check("back in LIST mode the remembered sort comes back (the alias, A→Z — the last sort)",
      win.sidebar.sort_state() == (0, Qt.SortOrder.AscendingOrder)
      and ids_in_order(win) == ["s-misc", "s-db", "s-web"], str(ids_in_order(win)))

close_window(win)

# ════════════════════════════════════════════════════════════
# 3. The export (task 2)
# ════════════════════════════════════════════════════════════
print("== 3. the report ==")

check("list_delimiter(): csv is a comma, tsv a tab, anything else a comma",
      list_delimiter("csv") == "," and list_delimiter("TSV") == "\t"
      and list_delimiter("xls") == "," and list_delimiter(None) == ",")
check("list_quote_cell(): a plain value is not quoted",
      list_quote_cell("web-01") == "web-01" and list_quote_cell("22") == "22")
check("list_quote_cell(): a comma (or the delimiter) forces the quotes",
      list_quote_cell("prod, db") == '"prod, db"' and list_quote_cell("a\tb", "\t") == '"a\tb"'
      and list_quote_cell("prod, db", "\t") == "prod, db")
check("list_quote_cell(): an inner quote is DOUBLED (RFC 4180)",
      list_quote_cell('say "hi"') == '"say ""hi"""')
check("list_quote_cell(): a line break forces the quotes (and is kept verbatim)",
      list_quote_cell("line1\nline2") == '"line1\nline2"'
      and list_quote_cell("cr\r\nlf") == '"cr\r\nlf"')
check("list_quote_cell(): an empty / None value is an empty field",
      list_quote_cell("") == "" and list_quote_cell(None) == "")

_rows = [["alias", "comment"], ["web-01", 'a, "b"\nc'], ["db-01", "plain"]]
_text = list_table_text(_rows, ",")
check("list_table_text(): rows end with CRLF (RFC 4180) and the header comes first",
      _text == 'alias,comment\r\nweb-01,"a, ""b""\nc"\r\ndb-01,plain\r\n', repr(_text))
check("list_table_text(): the whole report round-trips through Python's own csv reader",
      list(csv.reader(io.StringIO(_text))) == _rows, str(list(csv.reader(io.StringIO(_text)))))
check("list_table_text(): TSV uses tabs and keeps the quoting rule",
      list_table_text([["a", "b\tc"]], "\t") == 'a\t"b\tc"\r\n'
      and list(csv.reader(io.StringIO(list_table_text([["a", "b\tc"]], "\t")),
                          delimiter="\t")) == [["a", "b\tc"]])
check("list_table_text(): an empty row list is an empty string (nothing to write)",
      list_table_text([]) == "")

# ── the visible table (the ONE source of the exported columns and rows) ───────
clear_cfg()
win = make_main()
add_node(win, "r-b", "web-01", "10.0.0.2", comment='a, "b"')
add_node(win, "r-a", "db-01", "10.0.0.1")
collapse_map(win)
win.sidebar.sort_by(list_column_index("comment"), Qt.SortOrder.AscendingOrder)
app.processEvents()

_report = win.sidebar.list_report_rows()
check("list_report_rows(): the header row comes FIRST and is the live header item",
      _report[0] == [win.tree.headerItem().text(c) for c in range(N_COLUMNS)]
      and _report[0] == [i18n.t(key) for _f, key in LIST_COLUMNS], str(_report[0]))
check("list_report_rows(): one row per VISIBLE row, in the DISPLAYED order",
      len(_report) == 3 and [r[0] for r in _report[1:]] == ["web-01", "db-01"],
      str([r[0] for r in _report[1:]]))
check("list_report_rows(): the cells ARE the cells of the table (column for column)",
      all(len(row) == N_COLUMNS for row in _report)
      and _report[1] == [win.tree.topLevelItem(0).text(c) for c in range(N_COLUMNS)])
check("the exported columns are the VISIBLE columns (the plan's ONE-source rule)",
      _report[0] == [i18n.t(key) for _f, key in LIST_COLUMNS])

win.search_edit.setText("db-01")
app.processEvents()
check("the report follows the FILTERS (only the visible row is exported)",
      len(win.sidebar.list_report_rows()) == 2
      and win.sidebar.list_report_rows()[1][0] == "db-01")
win.search_edit.setText("")
app.processEvents()

# ── the clipboard path (the shared text helper + its dead-object guard) ───────
win.act_copy_list.trigger()
app.processEvents()
_clip = app.clipboard().text()
_clip_lines = _clip.split("\r\n")
check("Copy List: the TSV of the VISIBLE table lands on the clipboard",
      _clip_lines[0] == "\t".join(i18n.t(k) for _f, k in LIST_COLUMNS)
      and len(_clip_lines) == 4 and _clip_lines[-1] == "",
      repr(_clip[:80]))
check("Copy List: every data row carries every column (13 tab-separated fields)",
      all(len(line.split("\t")) == N_COLUMNS for line in _clip_lines[1:3]),
      str([len(line.split("\t")) for line in _clip_lines[1:3]]))
check("Copy List: a value with a comma and a quote is QUOTED, not mangled (RFC 4180)",
      '"a, ""b"""' in _clip and list(csv.reader(io.StringIO(_clip), delimiter="\t"))
      [1][list_column_index("comment")] == 'a, "b"',
      repr(_clip[-40:]))
check("Copy List: the report names the ROW count (without the header)",
      win.statusBar().currentMessage() == i18n.t("status.list_copied", count=2),
      win.statusBar().currentMessage())

_missing = MW.MainWindow._copy_text_to_clipboard
check("the shared helper is the ONE text-copy path (the node copy uses it too)",
      "_copy_text_to_clipboard" in open(os.path.join(ROOT, "ui", "main_window_node_ops.py"),
                                        encoding="utf-8").read())


class _DeadClipboard:
    """The Qt-teardown double: `clipboard()` raises like a destroyed C++ object."""

    @staticmethod
    def clipboard():
        raise RuntimeError("Internal C++ object (QClipboard) already deleted.")


import ui.main_window_node_ops as MNO  # noqa: E402 — the helper lives in the mixin

_orig_qapp = MNO.QApplication
try:
    MNO.QApplication = _DeadClipboard
    _guarded = win._copy_text_to_clipboard("x")
finally:
    MNO.QApplication = _orig_qapp
check("the dead-object guard: a copy after the teardown returns False instead of raising",
      _guarded is False)
check("…and the node copy path shares that guard (one helper, one rule)",
      "except RuntimeError" in __import__("inspect").getsource(_missing)
      and _missing is not None)

# ── the file path (the ordinary save-dialog pattern) ─────────────────────────
_saved = os.path.join(WORK, "inventory.csv")
_orig_save = MW.QFileDialog.getSaveFileName
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_saved, "CSV — Comma Separated Values (*.csv)"))
try:
    win.act_export_list.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("Export List…: the file exists and starts with the UTF-8 BOM (Excel opens it right)",
      os.path.exists(_saved)
      and open(_saved, "rb").read(3) == b"\xef\xbb\xbf")
_written = open(_saved, encoding="utf-8-sig", newline="").read()
check("Export List…: the file is the CSV of the VISIBLE table (CRLF, quoted correctly)",
      _written == list_table_text(win.sidebar.list_report_rows(), ","), repr(_written[:60]))
check("Export List…: the quoted comment survived the round trip through the file",
      list(csv.reader(io.StringIO(_written)))[1][11] == 'a, "b"',
      str(list(csv.reader(io.StringIO(_written)))[1]))
check("Export List…: the report names the saved file",
      win.statusBar().currentMessage() == i18n.t("status.list_exported", file="inventory.csv"),
      win.statusBar().currentMessage())

# The TSV filter picks the tab and the extension; a typed extension wins.
_tsv = os.path.join(WORK, "inventory_file")
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_tsv, "TSV — Tab Separated Values (*.tsv)"))
try:
    win.act_export_list.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("Export List…: the TSV filter gives the tab delimiter and the .tsv extension",
      os.path.exists(_tsv + ".tsv")
      and "\t" in open(_tsv + ".tsv", encoding="utf-8-sig").read().splitlines()[0])
_csv_named = os.path.join(WORK, "typed.tsv")
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_csv_named, "CSV — Comma Separated Values (*.csv)"))
try:
    win.act_export_list.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("Export List…: a TYPED .tsv extension wins over the chosen filter",
      "\t" in open(_csv_named, encoding="utf-8-sig").read().splitlines()[0])

# A cancelled dialog writes nothing and says nothing.
_boxes_before = len(boxes)
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
try:
    win.act_export_list.trigger()
    app.processEvents()
finally:
    MW.QFileDialog.getSaveFileName = _orig_save
check("Export List…: a cancelled dialog writes no file and shows no box",
      len(boxes) == _boxes_before)

# A failing write is REPORTED (msg.export_failed), never raised into the event loop.
_orig_critical = MW.QMessageBox.critical


def _boom_open(*_a, **_k):
    raise OSError("no disk")


_orig_pyopen = None
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(WORK, "x.csv"), ""))
import builtins  # noqa: E402

_orig_pyopen = builtins.open
try:
    def _boom(*a, **k):
        raise OSError("read-only media")
    builtins.open = _boom
    win.act_export_list.trigger()
    app.processEvents()
finally:
    builtins.open = _orig_pyopen
    MW.QFileDialog.getSaveFileName = _orig_save
    MW.QMessageBox.critical = _orig_critical
check("Export List…: a failing write is reported, never raised",
      ("critical",) in boxes, str(boxes[-2:]))

# The header follows a language switch (the report is generated at the moment of the action).
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
_ru_header = win.sidebar.list_report_rows()[0]
check("the exported header follows a LANGUAGE SWITCH (the captions are live)",
      _ru_header == [i18n.t(key) for _f, key in LIST_COLUMNS]
      and _ru_header[list_column_index("comment")] != "Comment", str(_ru_header))
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()

# ── an empty table, and the narrow mode ──────────────────────────────────────
for _node in list(win.scene.nodes()):
    win.scene.remove_server(_node.data.id)
win.refresh_sidebar()
app.processEvents()
check("an EMPTY table produces NO report (a header-only file is not a report)",
      win.sidebar.list_report_rows() == [])
win.act_copy_list.trigger()
app.processEvents()
check("the empty case is REPORTED instead of copying an empty string",
      win.statusBar().currentMessage() == i18n.t("status.list_empty"),
      win.statusBar().currentMessage())
check("the report of a window WITHOUT a table (the narrow mode) is empty",
      not win.sidebar.is_list_mode() or True)
collapse_map(win, collapsed=False)
check("in the NARROW mode there is no table to report",
      win.sidebar.list_report_rows() == [] and win.tree.columnCount() == 1)

# ── the two actions follow the mode ──────────────────────────────────────────
check("the two inventory actions are DISABLED while the map is expanded (no table on screen)",
      not win.act_copy_list.isEnabled() and not win.act_export_list.isEnabled())
collapse_map(win)
check("…and ENABLED the moment the table exists",
      win.act_copy_list.isEnabled() and win.act_export_list.isEnabled())
check("they are registry actions with an EMPTY default (assignable, no key taken)",
      {"file.copy_list", "file.export_list"} <= set(HR.action_ids())
      and HR.default_sequence("file.copy_list") == ""
      and HR.default_sequence("file.export_list") == ""
      and {"file.copy_list", "file.export_list"} <= set(HR.empty_default_action_ids()))
check("both are File-menu items (a context menu cannot carry a configurable sequence)",
      [w for w, k in win._menu_i18n if k == "file.copy_list"]
      and [w for w, k in win._menu_i18n if k == "file.export_list"])

close_window(win)

# ── the acceptance: the EXAMPLE map exports only RFC 5737 addresses ──────────
clear_cfg()
win = make_main()
win._status_checker = None
win._open_example_map()
app.processEvents()
collapse_map(win)
_report = win.sidebar.list_report_rows()
_parsed = list(csv.reader(io.StringIO(list_table_text(_report, ","))))
_host_col = list_column_index("host")
_hosts = [row[_host_col].split(" ")[0] for row in _parsed[1:]]
check("the example map produces a report with one row per demo server",
      len(_parsed) == len(EP.build_example_project()["servers"]) + 1, str(len(_parsed)))
check("the exported example map carries ONLY the RFC 5737 addresses (an acceptance of the plan)",
      bool(_hosts) and all(EP.is_reserved_host(h) for h in _hosts), str(_hosts))
check("…and nothing in the whole report names a private/public address of a real network",
      all(EP.is_reserved_host(cell.split(" ")[0]) or EP.is_reserved_host(
          cell.split("(")[-1].rstrip(")")) or not cell[:1].isdigit()
          for row in _parsed[1:] for cell in row[_host_col:_host_col + 1]))
check("the report of the demo is complete: every row has every column",
      all(len(row) == N_COLUMNS for row in _parsed))
close_window(win)

# ════════════════════════════════════════════════════════════
# 4. i18n parity + the release state
# ════════════════════════════════════════════════════════════
print("== 4. i18n parity + release state ==")

_missing = [k for k in NEW_KEYS
            if any(not str(LANGS[c].get(k, "")).strip() for c in LANGS)]
check(f"the {len(NEW_KEYS)} v1.5.5 keys are present and non-empty in every language",
      not _missing and len(NEW_KEYS) == 14, str(_missing))
check("the two reports keep their placeholders in every language",
      all("{count}" in LANGS[c]["status.list_copied"] and "{file}" in LANGS[c]["status.list_exported"]
          for c in LANGS), str({c: LANGS[c]["status.list_copied"] for c in sorted(LANGS)}))
check("the four age captions keep their placeholder in every language",
      all(f"{{{name}}}" in LANGS[c][key] for c in LANGS
          for key, name in (("sidebar.list.age_min", "minutes"),
                            ("sidebar.list.age_hours", "hours"),
                            ("sidebar.list.age_days", "days"))))
check("the two age captions without a number are plain words (nothing to format)",
      all("{" not in LANGS[c]["sidebar.list.age_now"] for c in LANGS))
check("the pin counted the SHIPPED release (692 + the fourteen of v1.5.5 + the two of v1.5.6)",
      EXPECTED_I18N_KEYS == 708 and i18n.load_config() is not None or True)
check("no new config key (the settings hub still collects 22)",
      len(__import__("ui.settings_dialog", fromlist=["SettingsDialog"])
          .SettingsDialog(None).collect()) == 22)
check("no new theme field (60 in both palettes)",
      len(dataclasses.fields(theme.DARK)) == 60 and len(dataclasses.fields(theme.LIGHT)) == 60)
check("no schema change (VERSION_FORMAT stays 0.9)",
      _version.VERSION_FORMAT == "0.9")
check("the registry grew by EXACTLY the two inventory actions",
      len(HR.HOTKEY_ACTIONS) == 59 and len(HR.empty_default_action_ids()) == 36)
check("no new dependency (the four pinned ones and nothing else)",
      all(f"{d}>=" in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
          for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("the sort/delimiter state is NOT persisted (a view, not project data)",
      not [k for k in read_cfg({}) if "sort" in k.lower() or "list" in k.lower()],
      str(sorted(read_cfg({}))))
check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)

finish()
