"""v1.8.4 — the map arranges itself and answers: the whole-map layout, the reverse traversal, the inode fact.

§1 the PURE unit layout (`arrange_unit_positions()`, its determinism and the three modes); §2 the
WHOLE-MAP arrangement of the window (ONE `CmdArrangeMap`, a group riding together through its frame,
the refusal, the dialog's map scope and the entry point); §3 the REVERSE traversal over the live
connections (the pure `dependency_ids()`, the cycle, the bidirectional edge and the scene reader);
§4 the traversal as the SECOND CHANNEL of the map's single dim owner (`_apply_map_dimming()`, the
Ctrl+click gesture, the clearing paths); §5 the INODE fact (`df -i` parse, the declared alert line,
the model's optional field and its absence-tolerance on an older project and an older batch);
§6 the release state."""
import json
import os
import sys

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format, clear_cfg,
                     placeholder_names, viewport_point)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + offscreen Qt)

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import ui.main_window as MW  # noqa: E402
from models.server import ServerData, server_data_from_dict, server_data_to_dict  # noqa: E402
from modules.undo_commands import (CmdArrangeGroup, CmdArrangeMap,  # noqa: E402
                                   CmdMoveNodes)
from graphics.node_group import (ARRANGE_HORIZONTAL, ARRANGE_ROWS,  # noqa: E402
                                 ARRANGE_VERTICAL, arrange_unit_positions)
from graphics.map_scene import dependency_ids  # noqa: E402
from services.system_info_collector import (INFO_BATCH, INODE_ALERT_PERCENT,  # noqa: E402
                                            build_info_batch, inode_alert, inode_percent,
                                            inode_token, parse_inode_report, parse_info_output,
                                            resolve_inode_answer)
from dialogs.arrange_group_dialog import (SCOPE_GROUP, SCOPE_MAP,  # noqa: E402
                                          ArrangeGroupDialog)


def new_window():
    """A MainWindow with the autosave timer stopped (no event loop in the tests)."""
    clear_cfg()
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.show()
    app.processEvents()
    return w


def close_window(win):
    """Close a window WITHOUT its "unsaved changes?" prompt (an offscreen hang otherwise)."""
    try:
        win._dirty = False
        win._undo_baseline_dirty = False
        win.close()
        win.destroy()
    except Exception:  # noqa: BLE001 — the cleanup must not fail the topical file
        pass


def positions(scene):
    """{node id: (x, y)} of the whole map — the assertion unit of the layout sections."""
    return {n.data.id: (round(n.pos().x(), 3), round(n.pos().y(), 3)) for n in scene.nodes()}


def card(scene, node_id, alias, x, y):
    """One node at an explicit position (the layout fixtures need real geometry)."""
    return scene.add_server(ServerData(id=node_id, alias=alias, host="10.80.0.9",
                                       user="root", x=x, y=y))


def dimmed(scene):
    """{node id: dimmed} — the view state `_apply_map_dimming()` is the ONE writer of."""
    return {n.data.id: bool(getattr(n, "_dimmed", False)) for n in scene.nodes()}


def source(rel):
    """The text of one repository file (the structural half of §2/§4)."""
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as fh:
        return fh.read()


# ════════════════════════════════════════════════════════════
# 1. The pure unit layout (task 1)
# ════════════════════════════════════════════════════════════
print("== §1 the pure unit layout ==")

# Two free cards and one group (its frame AND two members share the unit "G").
UNITS = [
    ("a", 0.0, 0.0, 100.0, 50.0, ""),
    ("b", 140.0, 0.0, 100.0, 50.0, ""),
    ("g", 300.0, 0.0, 200.0, 120.0, "G"),
    ("m1", 320.0, 20.0, 100.0, 50.0, "G"),
    ("m2", 320.0, 80.0, 100.0, 50.0, "G"),
]

_vert = [(k, round(x, 3), round(y, 3))
         for k, x, y in arrange_unit_positions(UNITS, ARRANGE_VERTICAL, gap=20.0)]
check("§1 vertical: the units stack in ONE column, a unit is ONE cell (its own box)",
      _vert == [("a", 0.0, 0.0), ("b", 0.0, 70.0), ("g", 0.0, 140.0),
                ("m1", 20.0, 160.0), ("m2", 20.0, 220.0)],
      str(_vert))

_horiz = [(k, round(x, 3), round(y, 3))
          for k, x, y in arrange_unit_positions(UNITS, ARRANGE_HORIZONTAL, gap=20.0)]
check("§1 horizontal: one row at the top edge, the next unit after the unit's WIDTH + gap",
      _horiz == [("a", 0.0, 0.0), ("b", 120.0, 0.0), ("g", 240.0, 0.0),
                 ("m1", 260.0, 20.0), ("m2", 260.0, 80.0)],
      str(_horiz))

_rows = [(k, round(x, 3), round(y, 3))
         for k, x, y in arrange_unit_positions(UNITS, ARRANGE_ROWS, per_line=2, gap=20.0)]
check("§1 rows: the typed COUNT of units per line (the row height is the tallest of the row)",
      _rows == [("a", 0.0, 0.0), ("b", 120.0, 0.0), ("g", 0.0, 70.0),
                ("m1", 20.0, 90.0), ("m2", 20.0, 150.0)],
      str(_rows))
check("§1 rows: a broken count is one unit per row (never a division by zero)",
      arrange_unit_positions(UNITS, ARRANGE_ROWS, per_line=0)
      == arrange_unit_positions(UNITS, ARRANGE_ROWS, per_line=1))
check("§1 the ordering is the caller's (the map hands its units over in reading order)",
      [k for k, _x, _y in _rows] == [m[0] for m in UNITS])

# The invariant of the whole feature: a unit is SHIFTED, never re-laid out.
_rel_before = [(round(m[1] - 300.0, 3), round(m[2] - 0.0, 3)) for m in UNITS if m[5] == "G"]
_after = dict((k, (x, y)) for k, x, y in _rows)
_rel_after = [(round(_after[k][0] - _after["g"][0], 3), round(_after[k][1] - _after["g"][1], 3))
              for k in ("g", "m1", "m2")]
check("§1 a unit RIDES by ONE delta: the frame's own shift is the members' shift",
      round(_after["g"][0] - 300.0, 3) == -300.0 and round(_after["m1"][0] - 320.0, 3) == -300.0
      and round(_after["g"][1] - 0.0, 3) == 70.0 and round(_after["m1"][1] - 20.0, 3) == 70.0
      and round(_after["m1"][1] - 20.0, 3) == round(_after["g"][1] - 0.0, 3),
      str((_after["g"], _after["m1"], _after["m2"])))
check("§1 ...so the relative placement INSIDE the unit is preserved byte for byte",
      _rel_before == _rel_after, str((_rel_before, _rel_after)))

check("§1 PURE and total: an empty input, a broken entry, a lone item and an unknown mode",
      arrange_unit_positions([], ARRANGE_ROWS) == []
      and arrange_unit_positions([("x",)], ARRANGE_ROWS) == []
      and arrange_unit_positions([("x", 1.0, 2.0, 3.0, 4.0, "")], "diagonal")
      == [("x", 1.0, 2.0)]
      and arrange_unit_positions([("k", 500.0, 600.0, 10.0, 10.0, "")], ARRANGE_ROWS)
      == [("k", 500.0, 600.0)],
      str(arrange_unit_positions([("x",)], ARRANGE_ROWS)))
check("§1 a second run answers the SAME layout (no hidden state, the id breaks a tie)",
      arrange_unit_positions(UNITS, ARRANGE_ROWS, 2)
      == arrange_unit_positions(UNITS, ARRANGE_ROWS, 2)
      and [k for k, _x, _y in arrange_unit_positions(
          [("b", 0.0, 0.0, 10.0, 10.0, ""), ("a", 0.0, 0.0, 10.0, 10.0, "")], ARRANGE_ROWS)]
      == ["b", "a"])
check("§1 two items of ONE unit move by the SAME delta (the unit id is the key)",
      (lambda res: res["m"] == (0.0, 0.0)
       and (round(res["n"][0] - res["m"][0], 3), round(res["n"][1] - res["m"][1], 3))
       == (50.0, 0.0) and res["z"][0] != 500.0)(
          dict((k, (round(x, 3), round(y, 3))) for k, x, y in arrange_unit_positions(
              [("m", 0.0, 0.0, 10.0, 10.0, "G"), ("n", 50.0, 0.0, 10.0, 10.0, "G"),
               ("z", 500.0, 0.0, 10.0, 10.0, "")], ARRANGE_HORIZONTAL))))


# ════════════════════════════════════════════════════════════
# 2. The window's whole-map arrangement (task 1)
# ════════════════════════════════════════════════════════════
print("== §2 the whole-map arrangement ==")

_win2 = new_window()
_sc2 = _win2.scene
check("§2 nothing to arrange on an EMPTY map (one status line, no command)",
      _win2._arrange_map(ARRANGE_ROWS, 2) is False
      and _win2.undo_stack.count() == 0
      and _win2.statusBar().currentMessage() == i18n.t("status.map_arrange_none"),
      _win2.statusBar().currentMessage())

card(_sc2, "s1", "one", 0.0, 0.0)
card(_sc2, "s2", "two", 400.0, 0.0)
_grp = _sc2.add_group("G", 600.0, 300.0, 300.0, 220.0)
card(_sc2, "s3", "three", 620.0, 320.0)
card(_sc2, "s4", "four", 620.0, 400.0)
check("§2 the fixture really holds one group of two members and two free cards",
      sorted(m.data.id for m in _grp.get_members()) == ["s3", "s4"],
      str(sorted(m.data.id for m in _grp.get_members())))

_before = positions(_sc2)
_before_group = (round(_grp.pos().x(), 3), round(_grp.pos().y(), 3))
_before_rel = [(round(m.pos().x() - _grp.pos().x(), 3), round(m.pos().y() - _grp.pos().y(), 3))
               for m in _grp.get_members()]
check("§2 the arrangement is applied and reported",
      _win2._arrange_map(ARRANGE_VERTICAL) is True
      and _win2.statusBar().currentMessage() == i18n.t("status.map_arranged", count=4),
      _win2.statusBar().currentMessage())
check("§2 ONE undo step (a single command, and its text names the gesture)",
      _win2.undo_stack.count() == 1
      and isinstance(_win2.undo_stack.command(0), CmdArrangeMap)
      and _win2.undo_stack.command(0).text().startswith("Arrange"),
      _win2.undo_stack.command(0).text() if _win2.undo_stack.count() else "empty")
check("§2 ...and the command is NOT destructive (an arrangement loses nothing)",
      _win2.undo_stack.command(0).offers_undo() is False)

_after = positions(_sc2)
check("§2 the group's frame really moved onto the column of the free cards",
      round(_grp.pos().x(), 3) == _after["s1"][0] == 0.0
      and (round(_grp.pos().x(), 3), round(_grp.pos().y(), 3)) != _before_group,
      str((_before_group, (_grp.pos().x(), _grp.pos().y()), _after["s1"])))
_rel_after = [(round(m.pos().x() - _grp.pos().x(), 3), round(m.pos().y() - _grp.pos().y(), 3))
              for m in _grp.get_members()]
check("§2 a group RIDES TOGETHER: its members kept their places inside the frame",
      _rel_after == _before_rel and sorted(_after) == ["s1", "s2", "s3", "s4"],
      str((_before_rel, _rel_after)))
check("§2 the membership survived (the frame moved, nobody left the group)",
      sorted(m.data.id for m in _grp.get_members()) == ["s3", "s4"],
      str(sorted(m.data.id for m in _grp.get_members())))

_win2.undo_stack.undo()
check("§2 ONE Ctrl+Z returns every card AND the frame byte for byte",
      positions(_sc2) == _before
      and (round(_grp.pos().x(), 3), round(_grp.pos().y(), 3)) == _before_group,
      str((positions(_sc2), _before)))
_win2.undo_stack.redo()
check("§2 the redo lands on the SAME layout (the arrangement is deterministic)",
      positions(_sc2) == _after, str((positions(_sc2), _after)))
check("§2 a second arrangement of an already arranged map moves NOTHING (and pushes nothing)",
      _win2._arrange_map(ARRANGE_VERTICAL) is False
      and _win2.undo_stack.count() == 1 and positions(_sc2) == _after,
      f"stack={_win2.undo_stack.count()}")

_win2._arrange_map(ARRANGE_ROWS, 2)
_row_positions = positions(_sc2)
check("§2 the rows mode puts TWO units on a line (the third starts the next row)",
      _row_positions["s1"][1] == _row_positions["s2"][1]
      and _row_positions["s3"][1] > _row_positions["s1"][1],
      str(_row_positions))

# The single-unit refusal: a map whose cards all live in ONE group has nothing to line up.
_solo = new_window()
card(_solo.scene, "k1", "k-one", 0.0, 0.0)
card(_solo.scene, "k2", "k-two", 10.0, 10.0)
_solo.scene.add_group("Only", -20.0, -20.0, 300.0, 300.0)
check("§2 one UNIT (a group of cards) is refused with the same honest status line",
      _solo._arrange_map(ARRANGE_ROWS, 2) is False and _solo.undo_stack.count() == 0
      and _solo.statusBar().currentMessage() == i18n.t("status.map_arrange_none"),
      _solo.statusBar().currentMessage())

# The dialog: the SHARED question with the MAP scope (the group scope stays the default).
_dlg = ArrangeGroupDialog(4, None, SCOPE_MAP)
check("§2 the dialog's map scope carries its own title and hint (the group scope is the default)",
      _dlg.scope() == SCOPE_MAP
      and _dlg.windowTitle() == i18n.t("arrange.map.title")
      and ArrangeGroupDialog(4).scope() == SCOPE_GROUP
      and ArrangeGroupDialog(4).windowTitle() == i18n.t("arrange.title"),
      f"{_dlg.windowTitle()!r}")
check("§2 ...and the three modes are the SHIPPED question (default vertical, rows asks the count)",
      _dlg.mode() == ARRANGE_VERTICAL and _dlg.per_line() >= 1
      and _dlg.rows_spin.isEnabled() is False)
_dlg.set_mode(ARRANGE_ROWS)
_dlg.rows_spin.setValue(4)
check("§2 the map scope answers the same pair the group's does",
      (_dlg.mode(), _dlg.per_line()) == (ARRANGE_ROWS, 4), str((_dlg.mode(), _dlg.per_line())))
_dlg.deleteLater()

check("§2 the whole-map command MIRRORS the group's (its own CmdMoveNodes subclass)",
      issubclass(CmdArrangeMap, CmdMoveNodes) and issubclass(CmdArrangeGroup, CmdMoveNodes)
      and CmdArrangeMap is not CmdArrangeGroup
      and CmdArrangeMap.__mro__[1] is CmdMoveNodes and CmdArrangeGroup.__mro__[1] is CmdMoveNodes)
_mv2 = source("graphics/map_view.py")
check("§2 the empty map's menu carries the map's own row, wired to the window's entry point",
      'ctx.arrange_map' in _mv2 and "_ask_arrange_map" in _mv2
      and callable(getattr(_win2, "_ask_arrange_map", None)))
_menu2 = _win2.view.build_context_menu(QPointF(3000.0, 3000.0))
_row2 = [a for a in _menu2.actions() if a.text() == i18n.t("ctx.arrange_map")]
check("§2 ...and the row really exists in the QMenu the view builds (its own seam)",
      len(_row2) == 1, str([a.text() for a in _menu2.actions() if a.text()]))
_called2 = []
_orig_ask2 = _win2._ask_arrange_map
_win2._ask_arrange_map = lambda: (_called2.append(1), True)[1]
try:
    _row2[0].trigger()
    app.processEvents()
finally:
    _win2._ask_arrange_map = _orig_ask2
check("§2 ...and triggering it calls the window's ONE entry point", _called2 == [1], str(_called2))
_menu2.deleteLater()

# The door reads the map's top level ONCE and hands that reading to the layout below it.
_walks = []
_orig_units = _win2._arrange_map_units
_expected_rows = len(_orig_units()[1])


def _counted_units():
    _walks.append(1)
    return _orig_units()


class _FakeArrangeDialog:
    """The dialog seam: it answers the ROWS mode, and records the rows count it was asked for."""

    asked = None

    def __init__(self, count, parent=None, scope=None):
        _FakeArrangeDialog.asked = (count, scope)

    def exec(self):
        return QDialog.Accepted

    def mode(self):
        return ARRANGE_ROWS

    def per_line(self):
        return 2

    def deleteLater(self):
        pass


_orig_dlg2 = MW.ArrangeGroupDialog
_win2._arrange_map_units = _counted_units
MW.ArrangeGroupDialog = _FakeArrangeDialog
try:
    _win2._ask_arrange_map()
finally:
    MW.ArrangeGroupDialog = _orig_dlg2
    _win2._arrange_map_units = _orig_units
check("§2 the arrange DOOR reads the map's top level exactly ONCE (ONE reading, handed down)",
      len(_walks) == 1, f"{len(_walks)} walks")
check("§2 ...and the dialog is asked with that reading's own row count",
      _FakeArrangeDialog.asked == (_expected_rows, SCOPE_MAP), str(_FakeArrangeDialog.asked))
close_window(_solo)
close_window(_win2)


# ════════════════════════════════════════════════════════════
# 3. The reverse traversal over the connections (task 2)
# ════════════════════════════════════════════════════════════
print("== §3 the reverse traversal ==")

# a -> b -> c: "a depends on b", "b depends on c", so stopping c breaks a AND b.
_chain = [("a", "b", False), ("b", "c", False)]
check("§3 the walk goes BACKWARDS along the arrows (who leans on the clicked node)",
      dependency_ids(_chain, "c") == ["a", "b", "c"], str(dependency_ids(_chain, "c")))
check("§3 ...and a node nothing points at answers its own id alone",
      dependency_ids(_chain, "a") == ["a"], str(dependency_ids(_chain, "a")))
check("§3 the answer is the TRANSITIVE closure, not just the direct neighbours",
      dependency_ids([("a", "b", False), ("b", "c", False), ("c", "d", False)], "d")
      == ["a", "b", "c", "d"])
check("§3 a CYCLE terminates (every node is visited once)",
      dependency_ids([("a", "b", False), ("b", "a", False)], "a") == ["a", "b"]
      and dependency_ids([("a", "a", False)], "a") == ["a"])
check("§3 a BIDIRECTIONAL edge is readable both ways",
      dependency_ids([("a", "b", True)], "b") == ["a", "b"]
      and dependency_ids([("a", "b", True)], "a") == ["a", "b"]
      and dependency_ids([("a", "b", False)], "a") == ["a"])
check("§3 an unknown start, an empty graph and junk edges are total",
      dependency_ids([], "x") == ["x"]
      and dependency_ids([("a", "b", False)], "") == []
      and dependency_ids([("a",)], "a") == ["a"]
      and dependency_ids(None, "z") == ["z"])
check("§3 the ids come back sorted (a set-like fact two runs cannot disagree on)",
      dependency_ids([("z", "m", False), ("y", "m", False), ("x", "y", False)], "m")
      == sorted(dependency_ids([("z", "m", False), ("y", "m", False), ("x", "y", False)], "m"))
      and dependency_ids([("z", "m", False), ("y", "m", False), ("x", "y", False)], "m")
      == ["m", "x", "y", "z"],
      str(dependency_ids([("z", "m", False), ("y", "m", False), ("x", "y", False)], "m")))

_win3 = new_window()
_sc3 = _win3.scene
for _sid in ("t1", "t2", "t3", "t4"):
    card(_sc3, _sid, _sid.upper(), 0.0, 0.0)
_sc3.add_connection("t1", "t2")
_sc3.add_connection("t2", "t3")
check("§3 the scene reads its LIVE arrows as the graph (the triples the walk consumes)",
      _sc3.connection_pairs() == [("t1", "t2", False), ("t2", "t3", False)],
      str(_sc3.connection_pairs()))
check("§3 the scene answers the closure of a node id",
      _sc3.dependency_closure("t3") == ["t1", "t2", "t3"]
      and _sc3.dependency_closure("t4") == ["t4"],
      str(_sc3.dependency_closure("t3")))
check("§3 the scene's own reader is the PURE one over its live pairs",
      _sc3.dependency_closure("t3") == dependency_ids(_sc3.connection_pairs(), "t3"))


# ════════════════════════════════════════════════════════════
# 4. The traversal is the SECOND CHANNEL of the one dim owner (task 2)
# ════════════════════════════════════════════════════════════
print("== §4 the dependency highlight ==")

check("§4 nothing is highlighted before the gesture (the channel is OFF)",
      _win3._dependency_ids() == set() and _win3._dependency_root() == "")
check("§4 the gesture sets the highlight and REPORTS the answer",
      _win3._toggle_dependency_focus("t3") is True
      and _win3.statusBar().currentMessage()
      == i18n.t("status.map_dependents", count=2, alias="T3"),
      _win3.statusBar().currentMessage())
check("§4 the closure is the one the scene answers", _win3._dependency_ids() == {"t1", "t2", "t3"})
_dim4 = dimmed(_sc3)
check("§4 the closure GLOWS and the rest of the map recedes (the dim owner's second channel)",
      _dim4 == {"t1": False, "t2": False, "t3": False, "t4": True}, str(_dim4))
check("§4 the closure also carries the accent frame the search uses",
      all(bool(getattr(_sc3.get_node(i), "_search_matched", False)) for i in ("t1", "t2", "t3"))
      and not bool(getattr(_sc3.get_node("t4"), "_search_matched", False)))
check("§4 the gesture is NOT a scene mutation (no command, no data written)",
      _win3.undo_stack.count() == 0 and _sc3.get_node("t1").data.x == 0.0)

check("§4 a second press on the SAME card drops it (a toggle)",
      _win3._toggle_dependency_focus("t3") is False and _win3._dependency_ids() == set()
      and dimmed(_sc3) == {"t1": False, "t2": False, "t3": False, "t4": False},
      str(dimmed(_sc3)))

_win3._toggle_dependency_focus("t4")
check("§4 a card nothing points AT is an answer too (and the map says which one)",
      _win3.statusBar().currentMessage()
      == i18n.t("status.map_dependents_none", alias="T4")
      and dimmed(_sc3) == {"t1": True, "t2": True, "t3": True, "t4": False},
      f"{_win3.statusBar().currentMessage()} / {dimmed(_sc3)}")
check("§4 the clearing writer drops it and reports that it was ON",
      _win3._clear_dependency_focus() is True
      and _win3._clear_dependency_focus() is False
      and dimmed(_sc3) == {"t1": False, "t2": False, "t3": False, "t4": False})
check("§4 an unknown node id is refused (a highlight over nothing would dim the whole map)",
      _win3._set_dependency_focus("nope") is False and _win3._dependency_ids() == set())

# The stale-root rule: a highlighted node that LEAVES the map turns the channel off by itself.
_win3._toggle_dependency_focus("t3")
_sc3.remove_server("t3")
check("§4 a root that leaves the map turns the highlight OFF (never a map dimmed forever)",
      _win3._dependency_ids() == set())
_win3._apply_map_dimming()
check("§4 ...and the next dim pass clears what the dead root had lit",
      dimmed(_sc3) == {"t1": False, "t2": False, "t4": False}, str(dimmed(_sc3)))
check("§4 an arrow that disappears leaves the closure (read LIVE, never cached)",
      _win3._set_dependency_focus("t2") is True and _win3._dependency_ids() == {"t1", "t2"},
      str(_win3._dependency_ids()))
_win3._clear_dependency_focus()

# The gesture itself: the view asks the window, and the press is NOT consumed (the shipped
# Ctrl+click multi-selection keeps working).
_mv4 = source("graphics/map_view.py")
_press = _mv4[_mv4.index("def mousePressEvent(self, event: QMouseEvent):"):]
_press = _press[:_press.index("\n    def ", 1)]
check("§4 the view calls the window's OWN writers (the dim state has ONE owner)",
      "_toggle_dependency_focus" in _press and "_clear_dependency_focus" in _press
      and "dependents = self._dependency_ids()" in source("ui/main_window.py"))
_branch = _press[_press.index("_toggle_dependency_focus"):_press.index("Shift+LMB on a node")]
check("§4 the Ctrl+click branch does NOT return early (Qt's own multi-selection is preserved)",
      "return" not in _branch, _branch[:120])
check("§4 Esc is the second key that drops it, and the map menu needs no new global action",
      _mv4.count("_clear_dependency_focus") >= 2
      and "depends_on" not in source("ui/hotkey_registry.py"))
close_window(_win3)

# The gesture through the REAL mouse path (QtTest — a hand-made QMouseEvent is unreliable).
_win4 = new_window()
_sc4 = _win4.scene
_d1 = card(_sc4, "d1", "d-one", 0.0, 0.0)
card(_sc4, "d2", "d-two", 500.0, 0.0)
card(_sc4, "d3", "d-three", 900.0, 0.0)
_sc4.add_connection("d2", "d1")
_sc4.add_connection("d3", "d2")
_vp4 = _win4.view.viewport()
_center4 = viewport_point(_win4.view, _d1.card_rect_scene().center())
QTest.mousePress(_vp4, Qt.LeftButton, stateKey=Qt.ControlModifier, pos=_center4)
app.processEvents()
QTest.mouseRelease(_vp4, Qt.LeftButton, stateKey=Qt.ControlModifier, pos=_center4)
app.processEvents()
check("§4 the real Ctrl+click (QTest) sets the highlight over the live arrows",
      _win4._dependency_root() == "d1" and _win4._dependency_ids() == {"d1", "d2", "d3"}
      and _win4.statusBar().currentMessage()
      == i18n.t("status.map_dependents", count=2, alias="d-one"),
      f"{_win4._dependency_root()} / {sorted(_win4._dependency_ids())}")
check("§4 ...and it really did NOT swallow the click: Qt's multi-selection ran as shipped",
      "d-one" in [n.data.alias for n in _sc4.selectedItems() if getattr(n, "data", None)])
QTest.mouseRelease(_vp4, Qt.LeftButton, pos=_center4)
QTest.mousePress(_vp4, Qt.LeftButton, pos=_center4)
app.processEvents()
check("§4 a plain click on the card drops the highlight",
      _win4._dependency_root() == "" and _win4._dependency_ids() == set())
close_window(_win4)


# ════════════════════════════════════════════════════════════
# 5. The inode fact (task 3)
# ════════════════════════════════════════════════════════════
print("== §5 the inode fact ==")

_INODES = """Filesystem     Inodes  IUsed   IFree IUse% Mounted on
/dev/sda1     6553600 320000 6233600    5% /
/dev/sdb1    26214400 26214400      0 100% /opt
tmpfs         131072    1200  129872    1% /run
"""
_rows5 = parse_inode_report(_INODES)
check("§5 the `df -i -P` table parses (the header skipped, the rest of the line is the mount)",
      _rows5 == [("/dev/sda1", 6553600, 320000, 6233600, "5%", "/"),
                 ("/dev/sdb1", 26214400, 26214400, 0, "100%", "/opt"),
                 ("tmpfs", 131072, 1200, 129872, "1%", "/run")],
      str(_rows5))
check("§5 a filesystem with NO inode table (`-` in every column) is dropped, never invented",
      parse_inode_report("Filesystem Inodes IUsed IFree IUse% Mounted on\n"
                         "- - - - - /dev/shm\n") == []
      and parse_inode_report("Filesystem Inodes IUsed IFree IUse% Mounted on\n"
                             "/dev/shm - - - - /dev/shm\n") == []
      and parse_inode_report("") == [])
check("§5 the token reader refuses junk and an impossible percentage",
      inode_token("100%") == "100%" and inode_token(" 7 % ") == "7%"
      and inode_token("-") == "" and inode_token(None) == "" and inode_token("junk") == ""
      and inode_token("101%") == "" and inode_token("0") == "0%"
      and inode_percent("100%") == 100 and inode_percent("") is None)

check("§5 the answer describes the SAME filesystem the mount answer named",
      resolve_inode_answer(_rows5, "/opt") == "100%"
      and resolve_inode_answer(_rows5, "/") == "5%"
      and resolve_inode_answer(_rows5, "/run") == "1%")
check("§5 a mount `df` printed no row for falls back to the ROOT row (the one path always asked)",
      resolve_inode_answer(_rows5, "/var") == "5%"
      and resolve_inode_answer(_rows5, "/var") == resolve_inode_answer(_rows5, "/")
      and resolve_inode_answer([row for row in _rows5 if row[5] != "/"], "/var") == "100%")
check("§5 a REFUSED mount answers '' (the inode fact belongs to the answer it sits beside)",
      resolve_inode_answer(_rows5, "") == "" and resolve_inode_answer(_rows5, None) == ""
      and resolve_inode_answer([], "/opt") == "")

check(f"§5 the alert line is DECLARED and PURE ({INODE_ALERT_PERCENT} %)",
      inode_alert("100%") is True and inode_alert(str(INODE_ALERT_PERCENT) + "%") is True
      and inode_alert("89%") is False and inode_alert("") is False
      and inode_alert("junk") is False and inode_alert("50%", threshold=10) is True)

check("§5 the batch carries the read ONCE, in its own marked section",
      build_info_batch("/opt").count("df -i -P") == 1
      and "---INODES---" in INFO_BATCH
      and INFO_BATCH.index("---INODES---") > INFO_BATCH.index("---DISKMOUNT---"))
check("§5 ...and the requested data mount reaches BOTH reads (the space one and this one)",
      build_info_batch("/my data").count("'/my data'") == 3,
      str(build_info_batch("/my data").count("'/my data'")))

_MOUNT = """---DISK---
Filesystem Type 1B-blocks Avail Mounted on
/dev/sda1 ext4 107374182400 42949672960 /
/dev/sdb1 ext4 64424509440 51539607552 /opt
---DISKMOUNT---
present
---INODES---
""" + _INODES + "---END---\n"
_info5 = parse_info_output(_MOUNT)
check("§5 the parsed collection carries the inode fact beside the mount pair",
      _info5.get("disk_inodes") == "100%" and _info5.get("disk_path") == "/opt"
      and _info5.get("disk_free") == "48 gb",
      str(_info5))

# An OLDER BATCH (written before the section existed) says NOTHING about inodes.
_legacy = _MOUNT.replace("---INODES---\n" + _INODES, "")
check("§5 an older BATCH (no section) leaves the fact alone instead of clearing it",
      "disk_inodes" not in parse_info_output(_legacy)
      and parse_info_output(_legacy).get("disk_path") == "/opt",
      str(parse_info_output(_legacy)))
# A REFUSED mount clears it with the pair it belongs to.
_net = _MOUNT.replace("/dev/sdb1 ext4 64424509440 51539607552 /opt",
                      "/dev/sdb1 nfs4 64424509440 51539607552 /opt")
check("§5 a mount the space read REFUSED carries no inode figure",
      parse_info_output(_net).get("disk_inodes") == ""
      and parse_info_output(_net).get("disk_path") == "",
      str(parse_info_output(_net).get("disk_note")))

# The model: an OPTIONAL field (`VERSION_FORMAT` does not move) and its absence-tolerance.
_old = server_data_from_dict({"id": "old1", "alias": "A", "host": "h", "user": "u"})
check("§5 an OLDER PROJECT loads the field as '' (additive, and it is not written back)",
      _old.disk_inodes == "" and "disk_inodes" not in server_data_to_dict(_old))
check("§5 a measured figure round-trips through the JSON",
      server_data_from_dict({**server_data_to_dict(_old), "disk_inodes": "100%"}).disk_inodes
      == "100%")
check("§5 a foreign value degrades to '' (the optional-text rule of the family)",
      server_data_from_dict({"id": "j1", "alias": "A", "host": "h", "user": "u",
                             "disk_inodes": 22}).disk_inodes == ""
      and server_data_from_dict({"id": "j2", "alias": "A", "host": "h", "user": "u",
                                 "disk_inodes": None}).disk_inodes == ""
      and server_data_from_dict({"id": "j3", "alias": "A", "host": "h", "user": "u",
                                 "disk_inodes": " 4% "}).disk_inodes == "4%")

_win5 = new_window()
card(_win5.scene, "i1", "inode-host", 0.0, 0.0)
_win5._apply_info_result("i1", _info5)
_node5 = _win5.scene.get_node("i1")
check("§5 the ONE write path stores the fact with the mount pair it belongs to",
      _node5.data.disk_inodes == "100%" and _node5.data.disk_path == "/opt",
      str((_node5.data.disk_inodes, _node5.data.disk_path)))
check("§5 the card NAMES the exhausted table on the mount's own line (the second sentence)",
      _node5._disk_mount_line()
      == i18n.t("node.disk_mount_inodes", mount="/opt", free="48 gb", size="60 gb", pct="100"),
      _node5._disk_mount_line())
check("§5 ...and the percentage is in the tooltip either way",
      _node5._disk_inodes_text() == i18n.t("node.disk_inodes", pct="100")
      and i18n.t("node.disk_inodes", pct="100") in _node5._info.toolTip(),
      _node5._info.toolTip())

_win5._apply_info_result("i1", dict(_info5, disk_inodes="7%"))
check("§5 below the alert line the card's line is the SHIPPED one, byte for byte",
      _node5._disk_mount_line()
      == i18n.t("node.disk_mount", mount="/opt", free="48 gb", size="60 gb")
      and _node5._disk_inodes_text() == i18n.t("node.disk_inodes", pct="7"),
      _node5._disk_mount_line())

_win5._apply_info_result("i1", {k: v for k, v in _info5.items() if k != "disk_inodes"})
check("§5 a collection SILENT about inodes leaves the stored figure alone",
      _node5.data.disk_inodes == "7%", _node5.data.disk_inodes)
_win5._apply_info_result("i1", {"disk_path": "", "disk_free": "", "disk_size": "",
                                "disk_note": "nfs4", "disk_inodes": ""})
check("§5 a refused mount CLEARS it with the pair (never a stale figure beside an empty answer)",
      _node5.data.disk_inodes == "" and _node5.data.disk_path == ""
      and _node5._disk_mount_line() == "",
      str((_node5.data.disk_inodes, _node5.data.disk_path)))
check("§5 an older PROJECT that never measured it renders no line and no tooltip line",
      server_data_from_dict(server_data_to_dict(
          ServerData(id="x9", alias="A", host="h", user="u"))).disk_inodes == "")
close_window(_win5)


# ════════════════════════════════════════════════════════════
# 6. The release state of the topical theme
# ════════════════════════════════════════════════════════════
print("== §6 the release state ==")

_langs = {}
for _code in ("en", "ru", "zh", "de"):
    with open(os.path.join(ROOT, "i18n", f"{_code}.json"), encoding="utf-8-sig") as f:
        _langs[_code] = json.load(f)
_NEW_KEYS = ("ctx.arrange_map", "arrange.map.title", "arrange.map.hint", "arrange.map.note",
             "status.map_arranged", "status.map_arrange_none", "status.map_dependents",
             "status.map_dependents_none", "node.disk_inodes", "node.disk_mount_inodes")
check("i18n: every v1.8.4 key is present and non-empty in all four languages",
      all(str(_langs[c].get(k) or "").strip() for k in _NEW_KEYS for c in _langs),
      str({k: [c for c in _langs if not str(_langs[c].get(k) or "").strip()]
           for k in _NEW_KEYS}))
check("i18n: the placeholders of the new sentences survive every language",
      all("{count}" in _langs[c]["arrange.map.hint"]
          and "{count}" in _langs[c]["status.map_arranged"]
          and "{count}" in _langs[c]["status.map_dependents"]
          and "{alias}" in _langs[c]["status.map_dependents"]
          and "{alias}" in _langs[c]["status.map_dependents_none"]
          and "{pct}" in _langs[c]["node.disk_inodes"]
          and {"mount", "free", "size", "pct"}
          <= placeholder_names(_langs[c]["node.disk_mount_inodes"])
          for c in _langs))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("the release carries the new keys and the pin of the run",
      __import__("_common").EXPECTED_I18N_KEYS >= 1036
      and __import__("_common").releases_at_least(
          __import__("version").APP_VERSION, "1.8.4"),
      f"{__import__('version').APP_VERSION} / {__import__('_common').EXPECTED_I18N_KEYS}")

# The roster edit AGENTS.md §4.2 states: the new arrangement makes it TWENTY commands.
_uc = source("modules/undo_commands.py")
_roster = [n for n in ("CmdMoveNode", "CmdMoveNodes", "CmdMoveGroup", "CmdResizeGroup",
                       "CmdEditGroupName", "CmdAddRemoveNode", "CmdAddRemoveNodeBatch",
                       "CmdAddRemoveConnection", "CmdConnectSelected", "CmdAddRemoveNote",
                       "CmdEditTextNote", "CmdAttachNote", "CmdEditConnection",
                       "CmdEditNodeData", "CmdToggleGroupCollapse", "CmdEditSelected",
                       "CmdMoveBackground", "CmdResizeBackground", "CmdArrangeGroup",
                       "CmdArrangeMap")
           if f"class {n}(" in _uc]
check("the undo roster is the TWENTY commands the contract counts",
      len(_roster) == 20, str(_roster))
check("the contract names the new count and the new command",
      "TWENTY commands" in source("AGENTS.md")
      and "CmdArrangeMap" in source("AGENTS.md"))

finish()
