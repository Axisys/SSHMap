"""v1.6 — the map at scale: bulk editing, density, arrangement and the connections out.

ROADMAP v1.6 (the release's topical file):
  #1 the BULK EDIT of the selection — `dialogs/bulk_edit_dialog.py`, the tri-state fields
     and ONE `CmdEditSelected` (apply → undo → every node byte-equal);
  #2 the CARD DENSITY — the `density` value of the nested `theme` config object and the
     compact branch of `ServerNode.update_appearance()` (the height formula and the free
     band hold in BOTH modes);
  #3 the PARALLEL LINKS between one endpoint pair — the offset index owned by `MapScene`,
     the distinct path AND hit zone of three links, and the duplicate that is no longer
     refused in silence;
  #4 the BACKGROUND image joins the undo stack — `CmdMoveBackground` / `CmdResizeBackground`;
  #5 the CONNECTION report — the columns declared once, the rows built by the pure
     `storage/export_connections.py` and quoted by the SHARED RFC-4180 writer;
  #6 the AUTO-ARRANGEMENT of a group's members — the pure `arrange_positions()`, the three
     modes, ONE `CmdArrangeGroup` and the folded-group refusal;
  #7 the ACTIVITY panel's toolbar mirror — the fifth member of the view cluster, taken in
     both directions.

Run: python tests/test_map_scale.py   (from the project root) or python tests/run_all.py
"""
import copy
import json
import os
import sys

from _common import bootstrap, check, finish, check_i18n_parity, check_i18n_format, clear_cfg

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + offscreen Qt)

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.theme as theme  # noqa: E402
from models.server import ServerData  # noqa: E402
from modules.undo_commands import (CmdArrangeGroup, CmdEditSelected,  # noqa: E402
                                   CmdMoveBackground, CmdResizeBackground)
from dialogs.bulk_edit_dialog import (BulkEditDialog, bulk_change_values, changes_for,  # noqa: E402
                                      parse_tags)
from graphics.connection_arrow import PAIR_OFFSET_STEP, pair_offset_steps  # noqa: E402
from graphics.node_group import (ARRANGE_HORIZONTAL, ARRANGE_ROWS, ARRANGE_VERTICAL,  # noqa: E402
                                 arrange_positions, resolve_arrange_mode)
from storage.export_connections import (CONNECTION_COLUMNS, connection_record,  # noqa: E402
                                        connection_report_rows, connection_report_text)


def new_window():
    """A MainWindow with the autosave timer stopped (no event loop in the tests)."""
    clear_cfg()
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.show()
    app.processEvents()
    return w


def close_window(win):
    """Close a window WITHOUT its "unsaved changes?" prompt (an offscreen hang otherwise).

    The v1.6 sections push real commands, so the window is dirty by design; `_dirty = False`
    is the pattern the suite uses before `close()`.
    """
    try:
        win._dirty = False
        win._undo_baseline_dirty = False
        win.close()
        win.destroy()
    except Exception:  # noqa: BLE001 — the cleanup must not fail the topical file
        pass


def node_data(node):
    """The three fields a bulk edit owns, as a comparable tuple."""
    return (list(getattr(node.data, "tags", None) or []),
            str(getattr(node.data, "comment", "") or ""),
            copy.deepcopy(list(getattr(node.data, "quick_launch", None) or [])))


# ════════════════════════════════════════════════════════════
# 1. The bulk edit: the tri-state, ONE command, a byte-equal undo (task 1)
# ════════════════════════════════════════════════════════════
print("== §1 the bulk edit of the selection ==")

check("bulk: parse_tags trims, drops the empties and folds the case-insensitive duplicates",
      parse_tags(" web , prod ,, WEB , db ") == ["web", "prod", "db"],
      str(parse_tags(" web , prod ,, WEB , db ")))

_sample = ServerData(id="bulk0001", alias="bulk-1", host="10.70.0.1", user="root",
                     tags=["keep-me"], comment="old comment",
                     quick_launch=[{"type": "url", "name": "old", "value": "http://old"}])

check("bulk: an all-unchanged mapping is a byte-equal no-op (nothing is written)",
      bulk_change_values(_sample, {f: ("unchanged", None)
                                   for f in ("tags", "comment", "quick_launch")})
      == {"tags": ["keep-me"], "comment": "old comment",
          "quick_launch": [{"type": "url", "name": "old", "value": "http://old"}]})
check("bulk: the result never aliases the model (fresh lists)",
      bulk_change_values(_sample, {})["tags"] is not _sample.tags
      and bulk_change_values(_sample, {})["quick_launch"] is not _sample.quick_launch)

_changes = {"tags": ("set", "prod, web"), "comment": ("unchanged", None),
            "quick_launch": ("clear", None)}
_new = bulk_change_values(_sample, _changes)
check("bulk: 'replace' writes the typed value, 'clear' empties the field, 'unchanged' keeps it",
      _new["tags"] == ["prod", "web"] and _new["comment"] == "old comment"
      and _new["quick_launch"] == [], str(_new))
check("bulk: changes_for() answers None when the edit changes nothing (no empty stack entry)",
      changes_for(_sample, {"tags": ("set", "keep-me"), "comment": ("unchanged", None),
                            "quick_launch": ("unchanged", None)}) is None
      and changes_for(_sample, _changes) is not None)
check("bulk: an unknown state is 'leave unchanged', never a silent write",
      bulk_change_values(_sample, {"tags": ("nonsense", "x")})["tags"] == ["keep-me"])

_win = new_window()
_nodes = [ServerData(id=f"blk{i:04d}", alias=f"blk-{i}", host=f"10.71.0.{i}", user="root",
                     tags=["a"], comment=f"c{i}")
          for i in range(3)]
_scene_nodes = [_win.scene.add_server(d) for d in _nodes]
_before = [node_data(n) for n in _scene_nodes]
_edits = []
for _node in _scene_nodes:
    _pair = changes_for(_node.data, _changes)
    if _pair is not None:
        _edits.append((_node, _pair[0], _pair[1]))
check("bulk: the window-side entry list has one entry per node that really changes",
      len(_edits) == 3, str(len(_edits)))

_win._push_command(CmdEditSelected(_win, _edits))
app.processEvents()
_after = [node_data(n) for n in _scene_nodes]
check("bulk: the apply wrote tags and cleared the quick launch on EVERY selected node",
      all(tags == ["prod", "web"] and ql == [] and comment == f"c{i}"
          for i, (tags, comment, ql) in enumerate(_after)), str(_after))

_undo_text = _win.undo_stack.undoText()
_win.undo_stack.undo()
app.processEvents()
check("bulk: ONE undo restores every card byte for byte (not one entry per node)",
      [node_data(n) for n in _scene_nodes] == _before and "3" in _undo_text
      and _win.undo_stack.count() == 1, f"{_undo_text} / {_win.undo_stack.count()}")
_win.undo_stack.redo()
app.processEvents()
check("bulk: the redo re-applies the same triple",
      [node_data(n) for n in _scene_nodes] == _after)
check("bulk: the command is NOT destructive (no Undo affordance is armed)",
      CmdEditSelected(_win, []).offers_undo() is False)

_dlg = BulkEditDialog(3, None)
check("bulk dialog: every field STARTS at 'leave unchanged' (the safe default)",
      all(_dlg.state_of(f) == "unchanged"
          for f in ("tags", "comment", "quick_launch")))
check("bulk dialog: the value widgets are enabled only in the 'replace' state",
      _dlg.tags_edit.isEnabled() is False
      and (_dlg.set_state("tags", "set") or _dlg.tags_edit.isEnabled() is True)
      and _dlg.state_of("tags") == "set")
_dlg.set_state("comment", "clear")
_dlg.set_state("quick_launch", "unchanged")
check("bulk dialog: changes() reports a payload ONLY for the 'replace' fields",
      _dlg.changes()["comment"] == ("clear", None)
      and _dlg.changes()["quick_launch"] == ("unchanged", None))
_dlg.deleteLater()
close_window(_win)

check("bulk: the action is registered and carries an EMPTY default",
      HR.default_sequence("edit.selected") == ""
      and HR.action_family("edit.selected") == "edit")
check("bulk: the map's multi-selection context menu carries the row",
      "_bulk_edit_selection" in open(os.path.join(ROOT, "graphics", "map_view.py"),
                                     encoding="utf-8").read())


# ════════════════════════════════════════════════════════════
# 2. The card density (task 2)
# ════════════════════════════════════════════════════════════
print("== §2 the card density ==")

check("density: the vocabulary is the declared pair and a broken value is 'normal'",
      theme.DENSITIES == ("normal", "compact")
      and theme.resolve_density("COMPACT ") == "compact"
      and theme.resolve_density("huge") == "normal" and theme.resolve_density(None) == "normal")
check("density: it is a NON-colour flag (no Theme field moved)",
      "density" not in {f.name for f in __import__("dataclasses").fields(theme.Theme)})

from ui.settings_dialog import (apply_density_setting, density_from_settings,  # noqa: E402
                                load_theme_settings, SettingsDialog)

_stored = load_theme_settings()
check("density: the nested theme object carries the fourth value with 'normal' as the default",
      set(_stored) == {"mode", "accent", "motion", "density"}
      and _stored["density"] == "normal", str(_stored))
check("density: density_from_settings validates like the rest (a broken value = normal)",
      density_from_settings({"density": "compact"}) == "compact"
      and density_from_settings({"density": 7}) == "normal"
      and density_from_settings(None) == "normal")

_win2 = new_window()
_rich = _win2.scene.add_server(ServerData(
    id="den00001", alias="dense-1", host="10.72.0.1", user="root", os_name="Debian GNU/Linux 12",
    cpu="4", cpu_model="Xeon E5-2680", ram="32 GB", disk="468 GB", comment="a comment line",
    tags=["prod"]))
app.processEvents()
_normal_size = (_rich._current_width, _rich._current_height)
check("density(normal): the info plaque and the environment chip are visible",
      _rich._info.isVisible() and _rich._env_badge is not None and _rich._env_badge.isVisible(),
      f"{_rich._current_width}x{_rich._current_height}")

apply_density_setting({"density": "compact"})
_rich.sync_density()
app.processEvents()
_compact_size = (_rich._current_width, _rich._current_height)
check("density(compact): the info plaque collapses and the tag chip disappears",
      not _rich._info.isVisible()
      and (_rich._env_badge is None or not _rich._env_badge.isVisible()))
check("density(compact): the alias and the host stay on the card (non-empty, both visible)",
      _rich._alias.isVisible() and _rich._host_label.isVisible()
      and bool(_rich._alias.toPlainText().strip())
      and _rich._host_label.toPlainText().startswith("@"),
      f"{_rich._alias.toPlainText()!r} / {_rich._host_label.toPlainText()!r}")
check("density(compact): the width follows the name/host only (never the info block)",
      _compact_size[0] <= _normal_size[0] and _compact_size[0] >= _rich.MIN_NODE_WIDTH,
      f"{_normal_size} -> {_compact_size}")
check("density(compact): the height is the SAME formula with an empty info block "
      "(58 + 0 + 12, floored by MIN_NODE_HEIGHT)",
      _compact_size[1] == max(58 + 0 + 12, _rich.MIN_NODE_HEIGHT), str(_compact_size[1]))
check("density: the switch rides the ordinary refresh walk (refresh_theme re-lays the card out)",
      _rich.density() == "compact")

apply_density_setting({"density": "normal"})
_rich.refresh_theme()
app.processEvents()
check("density: switching back restores the expanded card (same size as before)",
      (_rich._current_width, _rich._current_height) == _normal_size and _rich._info.isVisible(),
      str((_rich._current_width, _rich._current_height)))

_static = SettingsDialog(None)
check("density: the 'Appearance' tab offers the choice and collect() keeps the 22 config keys",
      _static.density_combo.count() == 2
      and _static.density_combo.currentData() == "normal"
      and len(_static.collect()) == 22
      and _static.collect()["theme"]["density"] == "normal")
_static.deleteLater()
close_window(_win2)


# ════════════════════════════════════════════════════════════
# 3. The parallel links of one endpoint pair (task 3)
# ════════════════════════════════════════════════════════════
print("== §3 the parallel links ==")

check("links: the offset fan is 0, +1, −1, +2, −2 … (index 0 = the historical curve)",
      [pair_offset_steps(i) for i in range(5)] == [0.0, 1.0, -1.0, 2.0, -2.0],
      str([pair_offset_steps(i) for i in range(5)]))
check("links: a broken index is the first link (never an exception)",
      pair_offset_steps(None) == 0.0 and pair_offset_steps("x") == 0.0
      and pair_offset_steps(-3) == 0.0)

_win3 = new_window()
_a = _win3.scene.add_server(ServerData(id="pair0001", alias="pair-a", host="10.73.0.1", user="u"))
_b = _win3.scene.add_server(ServerData(id="pair0002", alias="pair-b", host="10.73.0.2", user="u"))
_a.setPos(0, 0)
_b.setPos(600, 0)
_first = _win3.scene.add_connection("pair0001", "pair0002")
check("links: the FIRST link of a pair is exactly the historical curve (offset 0)",
      _first is not None and _first.pair_index == 0 and _first.offset_px() == 0.0
      and _win3.scene.has_connection("pair0001", "pair0002"))
_second = _win3.scene.add_connection("pair0001", "pair0002")
check("links: a DUPLICATE of the same direction is CREATED, not refused in silence "
      "(the colleagues' 'sometimes it connects' report)",
      _second is not None and _second is not _first and _win3.scene.arrow_count() == 2)
_third = _win3.scene.add_connection("pair0002", "pair0001")
check("links: the reverse direction joins the SAME offset group",
      _third is not None
      and {a.pair_index for a in _win3.scene.arrows()} == {0, 1, 2},
      str([a.pair_index for a in _win3.scene.arrows()]))

_mids = [(a.pair_index, a.path().pointAtPercent(0.5))
         for a in _win3.scene.arrows()]
check("links: three links of one pair do NOT overlap (three distinct midpoints)",
      len({(round(p.x(), 3), round(p.y(), 3)) for _i, p in _mids}) == 3,
      str([(i, round(p.x(), 1), round(p.y(), 1)) for i, p in _mids]))
check("links: the offset step is the declared one (the neighbour sits PAIR_OFFSET_STEP/2 away)",
      abs(abs(_mids[1][1].y() - _mids[0][1].y()) - PAIR_OFFSET_STEP / 2.0) < 0.01,
      f"{_mids[0][1].y()} / {_mids[1][1].y()}")

_mid_second = _second.path().pointAtPercent(0.5)
check("links: the hit zone follows the offset path (contains() answers on the moved arc)",
      _second.contains(QPointF(_second.path().pointAtPercent(0.5)))
      and not _first.contains(QPointF(_mid_second)),
      "contains() of the neighbour on the second arc")

_win3.scene.remove_connection(_second)
check("links: removing one link renumbers the survivors (ONE owner of the index)",
      [a.pair_index for a in _win3.scene.arrows()] == [0, 1]
      and _win3.scene.pair_arrows("pair0001", "pair0002") == _win3.scene.arrows())

# The undo of a duplicate removes the link it created, not the first one of the pair
from modules.undo_commands import CmdAddRemoveConnection  # noqa: E402

_win3._push_command(CmdAddRemoveConnection(_win3, _win3.scene, "pair0001", "pair0002",
                                           "dup", "ssh", "add"))
_pinned = [a for a in _win3.scene.arrows() if a.label_text == "dup"]
check("links: the add command really landed as a third link", len(_pinned) == 1)
_win3.undo_stack.undo()
app.processEvents()
check("links: its undo removes THAT link (not the first match of the direction)",
      _win3.scene.arrow_count() == 2
      and not any(a.label_text == "dup" for a in _win3.scene.arrows()))
close_window(_win3)


# ════════════════════════════════════════════════════════════
# 4. The background image joins the undo stack (task 4)
# ════════════════════════════════════════════════════════════
print("== §4 the background commands ==")

from PySide6.QtGui import QPixmap  # noqa: E402

_img = os.path.join(WORK, "bg_v16.png")
_pm = QPixmap(120, 80)
_pm.fill()
_pm.save(_img)

_win4 = new_window()
_bg = _win4.scene.set_background_image(_img)
_win4._connect_background_signals(_bg)
_bg.setPos(100.0, 50.0)
_start = QPointF(_bg.pos())
_win4._commit_background_move(_bg, _start, QPointF(300.0, 250.0))
app.processEvents()
check("background: a finished MOVE gesture pushes CmdMoveBackground and applies it",
      _bg.pos().x() == 300.0 and _bg.pos().y() == 250.0
      and isinstance(_win4.undo_stack.command(_win4.undo_stack.index() - 1), CmdMoveBackground),
      f"{_bg.pos().x()}/{_bg.pos().y()}")
_win4.undo_stack.undo()
app.processEvents()
check("background: undo returns the image to the position it started from",
      (_bg.pos().x(), _bg.pos().y()) == (100.0, 50.0), str((_bg.pos().x(), _bg.pos().y())))
_win4.undo_stack.redo()
app.processEvents()
check("background: redo re-applies the move", (_bg.pos().x(), _bg.pos().y()) == (300.0, 250.0))

_size0 = _bg.size()
_win4._commit_background_resize(_bg, _size0[0], _size0[1], 240.0, 160.0)
app.processEvents()
check("background: a finished RESIZE gesture pushes CmdResizeBackground and applies it",
      _bg.size() == (240.0, 160.0)
      and isinstance(_win4.undo_stack.command(_win4.undo_stack.index() - 1),
                     CmdResizeBackground))
_win4.undo_stack.undo()
app.processEvents()
check("background: undo restores the size", _bg.size() == _size0, str(_bg.size()))
check("background: neither command is destructive (a move loses nothing)",
      CmdMoveBackground(_win4, _bg, _start, _start).offers_undo() is False
      and CmdResizeBackground(_win4, _bg, _size0, _size0).offers_undo() is False)
close_window(_win4)


# ════════════════════════════════════════════════════════════
# 5. The connection report (task 5)
# ════════════════════════════════════════════════════════════
print("== §5 the connection report ==")

check("report: the columns are declared ONCE (the field/eight captions)",
      len(CONNECTION_COLUMNS) == 8
      and [f for f, _k in CONNECTION_COLUMNS] == ["source_alias", "source_host",
                                                  "target_alias", "target_host", "type",
                                                  "direction", "bidirectional", "label"])
check("report: no link at all is an EMPTY report (the caller reports it, no header file)",
      connection_report_rows([]) == [] and connection_report_text([]) == "")

# A label that MUST be quoted + a comma in an alias (the RFC-4180 rules of the shared writer)
_win5 = new_window()
_n1 = _win5.scene.add_server(ServerData(id="rep00001", alias='web, "one"', host="10.74.0.1",
                                        user="u"))
_n2 = _win5.scene.add_server(ServerData(id="rep00002", alias="db-1", host="10.74.0.2", user="u"))
_n1.setPos(0, 0)
_n2.setPos(500, 0)
_arrow = _win5.scene.add_connection("rep00001", "rep00002", 'label, "quoted"', "database",
                                    bidirectional=True)
_rows = connection_report_rows(_win5.scene.arrows(), lambda key, **kw: key)
check("report: one header row + one row per link (the columns' own fields)",
      len(_rows) == 2 and len(_rows[0]) == 8 and len(_rows[1]) == 8, str(_rows))
check("report: the row carries both endpoints, the declared type, the direction and the flag",
      _rows[1][0] == 'web, "one"' and _rows[1][1] == "10.74.0.1"
      and _rows[1][2] == "db-1" and _rows[1][3] == "10.74.0.2"
      and _rows[1][4] == "database" and _rows[1][5] == 'web, "one" \u2192 db-1'
      and _rows[1][6] == "report.conn.yes" and _rows[1][7] == 'label, "quoted"',
      str(_rows[1]))
_text = connection_report_text(_win5.scene.arrows(), ",", lambda key, **kw: key)
check("report: the SHARED RFC-4180 writer quotes a comma, a quote and a line break",
      '"web, ""one"""' in _text and '"label, ""quoted"""' in _text
      and _text.endswith("\r\n"), repr(_text[-160:]))
check("report: the delimiter of the TSV form is the tab (same writer, same rows)",
      "\t" in connection_report_text(_win5.scene.arrows(), "\t", lambda key, **kw: key))
check("report: connection_record() survives a duck-typed (half-torn) arrow",
      connection_record(object())["source_alias"] == ""
      and connection_record(object())["bidirectional"] is False)
check("report: the action is in the registry with an EMPTY default and the File family",
      HR.default_sequence("file.export_connections") == ""
      and HR.action_family("file.export_connections") == "file")
check("report: the window owns the export entry point",
      callable(getattr(_win5, "_export_connections_table", None)))
close_window(_win5)


# ════════════════════════════════════════════════════════════
# 6. The auto-arrangement of a group (task 6)
# ════════════════════════════════════════════════════════════
print("== §6 the group arrangement ==")

_items = [("n1", 100.0, 100.0, 180.0, 130.0),
          ("n2", 340.0, 90.0, 180.0, 130.0),
          ("n3", 120.0, 300.0, 180.0, 130.0)]
_vertical = arrange_positions(_items, ARRANGE_VERTICAL, gap=20.0)
check("arrange: the vertical line is ONE column at the left edge of the bounding box, "
      "in the given (reading) order",
      [key for key, _x, _y in _vertical] == ["n1", "n2", "n3"]
      and [x for _k, x, _y in _vertical] == [100.0, 100.0, 100.0]
      and [y for _k, _x, y in _vertical] == [90.0, 240.0, 390.0], str(_vertical))
_horizontal = arrange_positions(_items, ARRANGE_HORIZONTAL, gap=20.0)
check("arrange: the horizontal line is ONE row at the top edge",
      [y for _k, _x, y in _horizontal] == [90.0, 90.0, 90.0]
      and [x for _k, x, _y in _horizontal] == [100.0, 300.0, 500.0], str(_horizontal))
_rows2 = arrange_positions(_items, ARRANGE_ROWS, per_line=2, gap=20.0)
check("arrange: the rows mode puts the typed COUNT on a line and starts the next row below",
      [(x, y) for _k, x, y in _rows2] == [(100.0, 90.0), (300.0, 90.0), (100.0, 240.0)],
      str(_rows2))
check("arrange: a broken row count is one card per row (never a division by zero)",
      arrange_positions(_items, ARRANGE_ROWS, per_line=0, gap=20.0)
      == arrange_positions(_items, ARRANGE_ROWS, per_line=1, gap=20.0)
      and arrange_positions([], ARRANGE_ROWS) == [])
check("arrange: an unknown mode resolves to the vertical line (pure validation)",
      resolve_arrange_mode("diagonal") == ARRANGE_VERTICAL
      and resolve_arrange_mode(None) == ARRANGE_VERTICAL
      and resolve_arrange_mode("ROWS ") == ARRANGE_ROWS)

_win6 = new_window()
_grp = _win6.scene.add_group(name="arr", x=0, y=0, width=900, height=900)
_gnodes = []
for i in range(3):
    n = _win6.scene.add_server(ServerData(id=f"arr{i:05d}", alias=f"arr-{i}",
                                          host=f"10.75.0.{i}", user="u",
                                          x=40 + i * 200, y=60 + i * 15))
    _gnodes.append(n)
_win6.scene.resync_group_members()
check("arrange: the fixture really holds the three cards",
      len(_grp.get_members()) == 3, str(len(_grp.get_members())))

_before_pos = [(n.data.id, n.pos().x(), n.pos().y()) for n in _gnodes]
_ok = _win6._arrange_group(_grp, ARRANGE_VERTICAL)
app.processEvents()
check("arrange: the window applies it as ONE command",
      _ok is True and isinstance(_win6.undo_stack.command(_win6.undo_stack.index() - 1),
                                 CmdArrangeGroup))
_after_pos = [(n.data.id, n.pos().x(), n.pos().y()) for n in _gnodes]
check("arrange: the cards now share one column (the x of every card is equal)",
      len({x for _i, x, _y in _after_pos}) == 1, str(_after_pos))
_win6.undo_stack.undo()
app.processEvents()
check("arrange: ONE undo returns every position byte for byte",
      [(n.data.id, n.pos().x(), n.pos().y()) for n in _gnodes] == _before_pos)
check("arrange: the command is NOT destructive (an arrangement loses nothing)",
      CmdArrangeGroup(_win6, _grp, []).offers_undo() is False)

_win6._arrange_group(_grp, ARRANGE_ROWS, 2)
app.processEvents()
_rows_pos = [(n.data.id, n.pos().x(), n.pos().y()) for n in _gnodes]
check("arrange(rows=2): the third card starts a second row",
      len({x for _i, x, _y in _rows_pos}) == 2
      and len({y for _i, _x, y in _rows_pos}) == 2, str(_rows_pos))

_win6.scene.clearSelection()
_grp.set_collapsed(True)
_folded_result = _win6._arrange_group(_grp, ARRANGE_VERTICAL)
check("arrange: a FOLDED group is REFUSED with a status line (no honest layout on the strip)",
      _folded_result is False
      and _win6.statusBar().currentMessage() == i18n.t("status.group_folded"),
      _win6.statusBar().currentMessage())
_grp.set_collapsed(False)
app.processEvents()
_empty_grp = _win6.scene.add_group(name="empty", x=3000, y=3000, width=200, height=200)
check("arrange: a group with fewer than two members is refused with the same honest status line",
      _win6._arrange_group(_empty_grp, ARRANGE_VERTICAL) is False
      and _win6.statusBar().currentMessage() == i18n.t("status.arrange_none"),
      _win6.statusBar().currentMessage())
check("arrange: the action is registered with the EXISTING edit family prefix",
      HR.default_sequence("edit.arrange_group") == ""
      and HR.action_family("edit.arrange_group") == "edit")
check("arrange: the group's context menu carries the row next to rename/fold/delete",
      "_ask_arrange_group" in open(os.path.join(ROOT, "graphics", "map_view.py"),
                                   encoding="utf-8").read())
close_window(_win6)


# ════════════════════════════════════════════════════════════
# 7. The activity panel's toolbar mirror (task 7)
# ════════════════════════════════════════════════════════════
print("== §7 the panel cluster of the toolbar ==")

_win7 = new_window()
_btn = _win7._view_toolbar_buttons.get("view.toggle_activity")
check("toolbar: the ACTIVITY panel has a mirror in the view cluster (the fifth member)",
      _btn is not None and _btn.isCheckable() is True
      and _btn.text() == i18n.t("view.toggle_activity"), str(_btn))
check("toolbar: the mirror carries NO sequence of its own (the menu item owns the hotkey)",
      _btn.shortcut().toString() == ""
      and _win7.act_show_activity in _win7._hotkey_targets["view.toggle_activity"])
check("toolbar: every panel of the cluster is present (sidebar / map / minimap / legend / activity)",
      set(_win7._view_toolbar_buttons) == {"view.toggle_sidebar", "view.toggle_map",
                                           "view.toggle_minimap", "view.toggle_legend",
                                           "view.toggle_activity"},
      str(sorted(_win7._view_toolbar_buttons)))

_before_state = _win7.act_show_activity.isChecked()
_btn.setChecked(not _before_state)
app.processEvents()
check("toolbar: the button DRIVES the owner action (button → menu item)",
      _win7.act_show_activity.isChecked() is (not _before_state),
      f"{_before_state} -> {_win7.act_show_activity.isChecked()}")
_win7.act_show_activity.setChecked(_before_state)
app.processEvents()
check("toolbar: the owner DRIVES the mirror (menu item → button, signals blocked, no loop)",
      _btn.isChecked() is _before_state, str(_btn.isChecked()))
close_window(_win7)


# ════════════════════════════════════════════════════════════
# 8. The release state of the topical theme
# ════════════════════════════════════════════════════════════
print("== §8 the release state ==")

_langs = {}
for _code in ("en", "ru", "zh", "de"):
    with open(os.path.join(ROOT, "i18n", f"{_code}.json"), encoding="utf-8-sig") as f:
        _langs[_code] = json.load(f)
_NEW_KEYS = ("bulk.title", "bulk.state.unchanged", "edit.bulk_edit",
             "ctx.arrange_group", "file.export_connections",
             "report.conn.direction", "report.conn.bidirectional",
             "settings.appearance.density.compact",
             "status.bulk_edited", "status.group_arranged")
check("i18n: every v1.6 key family is present and non-empty in all four languages",
      all(str(_langs[c].get(k) or "").strip() for k in _NEW_KEYS for c in _langs),
      str({k: [c for c in _langs if not str(_langs[c].get(k) or "").strip()]
           for k in _NEW_KEYS}))
check("i18n: the placeholders of the new sentences survive every language",
      all("{count}" in _langs[c]["bulk.title"] and "{count}" in _langs[c]["status.bulk_edited"]
          and "{count}" in _langs[c]["arrange.hint"]
          and "{count}" in _langs[c]["status.group_arranged"]
          and "{name}" in _langs[c]["status.group_arranged"]
          and "{file}" in _langs[c]["status.connections_exported"] for c in _langs))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("the release is v1.6 with 778 keys and 59 actions",
      __import__("version").APP_VERSION == "1.6"
      and __import__("_common").EXPECTED_I18N_KEYS == 778
      and len(HR.HOTKEY_ACTIONS) == 59 and len(HR.empty_default_action_ids()) == 36,
      f"{__import__('version').APP_VERSION}"
      f" / {__import__('_common').EXPECTED_I18N_KEYS}"
      f" / {len(HR.HOTKEY_ACTIONS)} / {len(HR.empty_default_action_ids())}")

finish()
