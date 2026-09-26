# -*- coding: utf-8 -*-
"""v1.5rc3 — First run & confidence: the demo map, the undo affordance and the age of a status.

The third release of the 1.5 line "Design & confidence". v1.5rc1 fixed the palette and
v1.5rc2 gave every meaning a second channel; this rc answers the two questions the design
review left open: *how do I start* and *how old is what I am looking at*.

  §1 the DEMO MAP is built in code (`storage/example_project.py`): a valid project dict,
     five nodes, six connections covering all six types, one group, one note, tags — and
     RFC 5737 documentation addresses only, so a probe can only tell the truth;
  §2 the LOAD PATH: both entry points (the empty state's button and `Help → Open the
     example map`) open the SAME project through the ORDINARY path; the window says it is
     an example (the title marker, no `_project_file`, not in the MRU) and a save turns it
     into the user's own file;
  §3 the UNDO AFFORDANCE: `_push_command()` is the one place that offers it, a destructive
     command arms it, the action's own message carries the button, the click restores the
     map, and nothing outside the stack (a view state, a message with no command) offers
     anything;
  §4 STATUS FRESHNESS: the checker timestamps every result and owns the threshold
     (`max(2 × interval, 90 s)`), the card paints the stale mark in the idle tone with the
     declared shape and adds "checked N min ago" to the tooltip — and the STATUS itself is
     never touched (a stale online stays online);
  §5 the FIRST SCREEN: the empty state names the palette (its live hotkey) and the `?` key,
     the palette opens on a bounded "Start here" block, and `?` / F1 open the
     registry-derived cheat-sheet Help → About already renders;
  §6 the SCREENSHOT probe: the demo map really renders (the acceptance's "screenshot which
     doubles as the README source");
  §7 the release state (version, i18n parity + the 11 new keys, the registry, the hub).

Run: python tests/test_first_run.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import time

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, EXPECTED_I18N_KEYS)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen, faulthandler)

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])

from models.server import ServerData, server_data_from_dict  # noqa: E402
from graphics.server_node import ServerNode  # noqa: E402
import storage.example_project as EP  # noqa: E402
import ui.command_palette as CP  # noqa: E402
import ui.hotkey_sheet_dialog as HSD  # noqa: E402
import ui.main_window as MW  # noqa: E402
from i18n import t as _t, save_config as _save_config  # noqa: E402
from ui import status_shape, theme  # noqa: E402
from ui.about_dialog import cheatsheet  # noqa: E402
from ui.hotkey_registry import action_ids, configured_hotkeys, default_sequence  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402
from services.status_checker import StatusChecker, STALE_MIN_SEC  # noqa: E402
from modules.undo_commands import (  # noqa: E402
    CmdAddRemoveConnection, CmdAddRemoveNode, CmdAddRemoveNodeBatch, CmdAddRemoveNote,
    CmdAttachNote, CmdEditTextNote, CmdMoveNode, CmdToggleGroupCollapse,
)

# ── The harness: no modal box may ever block an offscreen run ────────────────
from _fakes import QuestionStub  # noqa: E402

boxes = []
answers = QuestionStub(
    QMessageBox.Yes,
    record=lambda title, text: boxes.append(("question", title))).install(MW)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical",)))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning",)))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information",)))

# The cheat-sheet dialog is a MODAL exec() — patched for the whole file (never a real event
# loop offscreen). The REAL dialog is still built, so its rendered text is measured.
_sheets = []
HSD.HotkeySheetDialog.exec = lambda self: _sheets.append(self) or 0


def make_main():
    """An offscreen MainWindow with the timers stopped and NO status checker.

    The demo map points at RFC 5737 addresses, so the ordinary load would start a real
    (if pointless) probe round — the suite is HERMETIC by default, so the checker is
    removed before the load: nothing in this file opens a socket. Freshness is measured
    on a checker DOUBLE in §4 instead.
    """
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w._freshness_timer.stop()
    w._status_checker = None
    w.resize(1100, 760)
    w.show()
    app.processEvents()
    return w


def load_example(win):
    """Both entry points go through `_open_example_map` — this is the one they call."""
    win._open_example_map()
    app.processEvents()
    return win


def _all_keys(obj):
    """Every dict key anywhere in a project dict (the format's own vocabulary)."""
    keys = set()
    if isinstance(obj, dict):
        keys |= set(obj)
        for value in obj.values():
            keys |= _all_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            keys |= _all_keys(value)
    return keys


def _has_key(obj, key):
    """Is `key` a dict KEY anywhere in the structure (not merely a word in a text)?"""
    return key in _all_keys(obj)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the demo map is built in code (a valid project, reserved addresses) ==")
# ════════════════════════════════════════════════════════════════════════════

_raw = EP.build_example_project()
check("§1 the factory returns a project DICT (no data file is shipped or read)",
      isinstance(_raw, dict)
      and os.path.isfile(os.path.join(ROOT, "storage", "example_project.py")),
      type(_raw).__name__)
check("§1 it carries every array of the project format",
      all(isinstance(_raw.get(k), list) for k in ("servers", "connections", "notes", "groups"))
      and _raw.get("background") is None, str(sorted(_raw)))
check("§1 the format version comes from version.py (never a literal)",
      _raw["version"] == __import__("version").VERSION_FORMAT, _raw["version"])

_servers = _raw["servers"]
check("§1 six servers, each with a unique FIXED id (a deterministic demo)",
      len(_servers) == 6 and len({s["id"] for s in _servers}) == 6
      and [s["id"] for s in EP.build_example_project()["servers"]] == [s["id"] for s in _servers],
      str([s["id"] for s in _servers]))
check("§1 the aliases are the documented set (the README/tests address them by name)",
      list(EP.example_aliases()) == [s["alias"] for s in _servers],
      str(EP.example_aliases()))
check("§1 every server carries TAGS (the demo shows the feature)",
      all(isinstance(s.get("tags"), list) and s["tags"] for s in _servers),
      str([s.get("tags") for s in _servers]))
check("§1 every server record survives the ORDINARY deserializer",
      all(isinstance(server_data_from_dict(s), ServerData) for s in _servers))
check("§1 no record carries a password (never serialized — §4.4)",
      all("password" not in s for s in _servers))
check("§1 NO status is baked into the FORMAT (the probes tell the truth)",
      not _has_key(_raw, "status"), str(sorted(_all_keys(_raw))))
# v1.6.5 (ROADMAP task 6): the demo's live sample of the release — ONE card the operator
# does not administer. It is the release's contract in data form: the flag, NO credentials
# at all (not even a user) and the opt-in ping left OFF.
_unmanaged_ids = set(EP.unmanaged_example_ids())
_unmanaged = [s for s in _servers if s["id"] in _unmanaged_ids]
check("§1 v1.6.5: the demo carries exactly ONE unmanaged card (the release's live sample)",
      len(_unmanaged_ids) == 1 and len(_unmanaged) == 1
      and _unmanaged[0].get("unmanaged") is True,
      str([(s["id"], s.get("unmanaged")) for s in _servers]))
check("§1 v1.6.5: it carries NO credentials and the opt-in ping is OFF",
      _unmanaged[0].get("user") == "" and _unmanaged[0].get("unmanaged_ping") is False
      and "password" not in _unmanaged[0] and "key_path" not in _unmanaged[0],
      str(_unmanaged[0]))
check("§1 v1.6.5: its host is a documentation address like every other card",
      EP.is_reserved_host(_unmanaged[0]["host"]), _unmanaged[0]["host"])
# v1.5 (ROADMAP): the demo DECLARES its statuses instead of measuring them — in code, not
# in the file — and every one of them is therefore EMULATED and marked as such.
check("§1 v1.5: the demo DECLARES one status per MANAGED node (in code, never in the file)",
      set(EP.DEMO_STATUSES) == {s["id"] for s in _servers} - _unmanaged_ids,
      str(sorted(EP.DEMO_STATUSES)))
check("§1 v1.5: the declaration shows all THREE statuses (the legend at a glance)",
      sorted(set(EP.DEMO_STATUSES.values())) == ["offline", "online", "warn"],
      str(sorted(set(EP.DEMO_STATUSES.values()))))
check("§1 v1.5: every declared value is a status the app knows",
      set(EP.DEMO_STATUSES.values()) <= set(theme.STATUS_COLORS))
check("§1 v1.5: the checker's skip set is DERIVED from the declaration (one source)",
      set(EP.demo_status_ids()) == set(EP.DEMO_STATUSES) and EP.demo_status_ids(),
      str(EP.demo_status_ids()))
check("§1 v1.5: the factory still returns the same dict — the declaration is not data",
      not any(v in EP.build_example_project()["servers"][0].values()
              for v in ("online", "warn")))

_hosts = [s["host"] for s in _servers]
check("§1 every host is an RFC 5737 documentation address",
      all(EP.is_reserved_host(h) for h in _hosts), str(_hosts))
check("§1 the addresses live in the 192.0.2.0/24 block the module names",
      EP.RESERVED_NETWORK == "192.0.2.0/24" and all(h.startswith("192.0.2.") for h in _hosts),
      EP.RESERVED_NETWORK)
check("§1 the rule REJECTS a real address and a name (it is not a no-op)",
      not EP.is_reserved_host("10.0.0.1") and not EP.is_reserved_host("example.com")
      and not EP.is_reserved_host(""))
check("§1 the addresses are also what the nodes report as `ip` (no second truth)",
      all(s.get("ip") == s["host"] for s in _servers), str([s.get("ip") for s in _servers]))
check("§1 the quick launch of the demo points at a documentation address too",
      all(EP.is_reserved_host(e["value"].split("//")[-1].split(":")[0].split("/")[0])
          for s in _servers for e in (s.get("quick_launch") or [])),
      str([e["value"] for s in _servers for e in (s.get("quick_launch") or [])]))

_conns = _raw["connections"]
_ids = {s["id"] for s in _servers}
check("§1 six connections — one of EVERY type the map knows",
      len(_conns) == 6 and {c["type"] for c in _conns} == set(theme.DARK.arrow_type_colors),
      str(sorted(c["type"] for c in _conns)))
check("§1 ...and each connection TYPE appears exactly once (a live legend sample)",
      len({c["type"] for c in _conns}) == len(_conns))
check("§1 every connection references an existing node and never itself",
      all(c["source_id"] in _ids and c["target_id"] in _ids
          and c["source_id"] != c["target_id"] for c in _conns))
check("§1 one group and one note (the demo frame and the tour text)",
      len(_raw["groups"]) == 1 and len(_raw["notes"]) == 1,
      f"groups={len(_raw['groups'])} notes={len(_raw['notes'])}")
check("§1 the tour note is TEXT (an i18n key), not an infrastructure record",
      isinstance(_raw["notes"][0]["text"], str) and len(_raw["notes"][0]["text"]) > 40,
      repr(_raw["notes"][0]["text"][:40]))
check("§1 the project round-trips through JSON unchanged (the format is the loader's)",
      json.loads(json.dumps(_raw)) == _raw)


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the load path: both entry points, ONE ordinary load ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
check("§2 a fresh window starts empty and shows the first-run hint",
      win.scene.node_count() == 0 and win.empty_state.is_state_visible())

win.empty_state.btn_example.click()
app.processEvents()
check("§2 the EMPTY-STATE button opens the demo map (through the ordinary load path)",
      win.scene.node_count() == len(_servers) and win.scene.arrow_count() == len(_conns),
      f"nodes={win.scene.node_count()} arrows={win.scene.arrow_count()}")
check("§2 ...and the hint disappears with the first card",
      not win.empty_state.is_state_visible())
check("§2 ...and the window marks the map as an example",
      win._example_project is True and _t("title.example") in win.windowTitle(),
      win.windowTitle())
check("§2 ...and it is NOT a user file: no path (Save asks for a name), not in the MRU",
      not win._project_file and win._recent_projects() == [],
      f"file={win._project_file!r} mru={win._recent_projects()}")
check("§2 the loaded map carries the EMULATED statuses of the declaration (v1.5)",
      {n.data.id: n.status for n in win.scene.nodes() if n.data.id not in _unmanaged_ids}
      == dict(EP.DEMO_STATUSES),
      str({n.data.id: n.status for n in win.scene.nodes()}))
check("§2 ...and EVERY one of them is marked as emulated (the honesty rule)",
      all(n.status_emulated and _t("node.status.emulated") in n.toolTip()
          for n in win.scene.nodes() if n.data.id not in _unmanaged_ids),
      str([(n.data.alias, n.status_emulated) for n in win.scene.nodes()]))
check("§2 ...and an emulated status carries NO age (it was never probed)",
      all(n.freshness_text() == "" and n.status_checked_at == 0.0
          for n in win.scene.nodes() if n.data.id not in _unmanaged_ids))
# v1.6.5 (ROADMAP task 6): the neighbour opens with the release's honest mark instead of a
# status — and it is what the demo's own skip set must protect (no round may probe it).
_neighbour = win.scene.get_node(sorted(_unmanaged_ids)[0])
check("§2 the unmanaged card opens UNCHECKED and MARKED, with no emulation at all",
      _neighbour is not None and _neighbour.status == "" and _neighbour.status_emulated is False
      and _neighbour._no_ssh_badge.isVisible()
      and _neighbour._no_ssh_badge.text() == _t("node.unmanaged")
      and _t("node.unmanaged.tooltip") in _neighbour.toolTip(),
      f"{_neighbour.status!r} {_neighbour.toolTip()!r}")
check("§2 the three status counters count the EMULATED map (the map, not a probe)",
      {s: win.status_filter_labels[s].text() for s in ("online", "warn", "offline")}
      == {s: _t(f"statusbar.filter.{s}",
                count=list(EP.DEMO_STATUSES.values()).count(s))
          for s in ("online", "warn", "offline")},
      str({s: win.status_filter_labels[s].text() for s in ("online", "warn", "offline")}))

_members = sorted(m.data.alias for g in win.scene.groups() for m in g.get_members())
check("§2 the group's membership is GEOMETRIC and holds exactly the web tier",
      _members == ["web-01", "web-02"], str(_members))
check("§2 ...and the other cards stay OUTSIDE the frame",
      win.scene.groups()[0].member_count() == 2, str(win.scene.groups()[0].member_count()))

# The Help item must reach the SAME method: reset the window, then trigger it.
win._new_project()
check("§2 a new project clears the example marker",
      win._example_project is False and _t("title.example") not in win.windowTitle(),
      win.windowTitle())
win.act_example_map.trigger()
app.processEvents()
check("§2 the HELP item opens the same project through the same path",
      win.scene.node_count() == len(_servers) and win._example_project is True,
      f"nodes={win.scene.node_count()} title={win.windowTitle()}")

_dump = win._serialize_project_data()
check("§2 the loaded map serializes back to a valid project (no drift from the format)",
      _dump["version"] == _raw["version"] and len(_dump["servers"]) == len(_servers)
      and all(EP.is_reserved_host(s["host"]) for s in _dump["servers"]))
_saved_path = os.path.join(WORK, "example_saved.json")
import ui.main_window_project_io as _PIO  # noqa: E402 — the QFileDialog seam of the mixin
_orig_save_dialog = _PIO.QFileDialog.getSaveFileName
_PIO.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_saved_path, ""))
_saved = win._save_project()          # the ORDINARY Save path (the demo has no file name)
_PIO.QFileDialog.getSaveFileName = _orig_save_dialog
check("§2 saving the demo (File → Save asks for a name) writes an ordinary project file",
      bool(_saved) and os.path.isfile(_saved_path), str(boxes[-1:]))
win._update_window_title()   # the title refresh the next window event performs
check("§2 ...and it is the USER's file from that moment on (the marker is gone)",
      win._example_project is False and win._project_file == _saved_path
      and _t("title.example") not in win.windowTitle()
      and os.path.basename(_saved_path) in win.windowTitle(), win.windowTitle())
check("§2 ...and a saved FILE does join the MRU (only a file is 'recent')",
      os.path.abspath(_saved_path) in [os.path.abspath(p) for p in win._recent_projects()],
      str(win._recent_projects()))
check("§2 the saved demo is a readable project (the ordinary loader accepts it)",
      json.load(open(_saved_path, encoding="utf-8"))["servers"][0]["host"].startswith("192.0.2."))
_disk = json.load(open(_saved_path, encoding="utf-8"))
check("§2 v1.5: the saved copy carries NO status field anywhere (a status is a measurement)",
      not _has_key(_disk, "status"), str(sorted(_all_keys(_disk)))[:200])
check("§2 v1.5: 'save as' DROPS the emulation — the copy is an ordinary project",
      win._emulated_statuses == {} and win._example_project is False,
      f"emulated={win._emulated_statuses}")
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §2b v1.5: the emulated statuses are MARKED and never outlive the demo ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
load_example(win)
_nodes_by_id = {n.data.id: n for n in win.scene.nodes()}
_emulated_node = _nodes_by_id[EP.WEB2]

check("§2b the marker is a TEXT badge on the card (a second channel, not a colour alone)",
      _emulated_node._demo_badge is not None and _emulated_node._demo_badge.isVisible()
      and _emulated_node._demo_badge.text() == _t("node.status.emulated"),
      repr(getattr(_emulated_node._demo_badge, "text", lambda: "")()))
check("§2b ...placed in the card's free band and INSIDE the card",
      _emulated_node._demo_badge.boundingRect().translated(
          _emulated_node._demo_badge.pos()).right() <= _emulated_node._current_width
      and _emulated_node._demo_chip.path().boundingRect().top()
      >= 0.0 and _emulated_node._demo_chip.path().boundingRect().bottom() <= 18.0,
      str(_emulated_node._demo_chip.path().boundingRect()))
_demo_rect = _emulated_node._demo_chip.path().boundingRect()
_dot_rect = _emulated_node._status_dot.path().boundingRect().translated(
    _emulated_node._status_dot.pos())
_alias_rect = _emulated_node._alias.boundingRect().translated(_emulated_node._alias.pos())
check("§2b ...clear of the status marks, the alias and the tag badge (measured, not guessed)",
      not _demo_rect.intersects(_dot_rect) and not _demo_rect.intersects(_alias_rect)
      and not _demo_rect.intersects(_emulated_node._env_chip.path().boundingRect()),
      f"marker={_demo_rect} dot={_dot_rect} alias={_alias_rect} "
      f"tag={_emulated_node._env_chip.path().boundingRect()}")
check("§2b the status keeps its DECLARED colour and shape (the emulation fakes no channel)",
      _emulated_node.status == "warn"
      and _emulated_node._status_dot.brush().color().name()
      == QColor(theme.STATUS_COLORS["warn"]).name()
      and round(_emulated_node._status_dot.path().boundingRect().width(), 3)
      == round(status_shape.shape_path("warn", 14.0).boundingRect().width(), 3))
check("§2b the tooltip names the emulation (and NOT an age)",
      _t("node.status.emulated") in _emulated_node.toolTip()
      and _t("node.status.checked_now") not in _emulated_node.toolTip(),
      _emulated_node.toolTip())
_emulated_node.set_checked_at(time.time(), 90.0)
check("§2b even a pushed timestamp cannot age an emulated status (the refusal is ONE place)",
      _emulated_node.status_checked_at == 0.0 and _emulated_node.freshness_text() == ""
      and _emulated_node.is_stale is False)

# The checker: the declared ids are never targets — not in a full round, not on demand.
_st = StatusChecker(interval_ms=30_000)
win._status_checker = _st
win._sync_status_targets()
check("§2b the periodic plan holds every node EXCEPT the emulated and the unmanaged ones",
      len(_st._subset()) == win.scene.node_count() - len(EP.DEMO_STATUSES) - len(_unmanaged_ids)
      and all(t[0] not in EP.DEMO_STATUSES for t in _st._subset())
      and all(t[0] not in _unmanaged_ids for t in _st._subset()),
      str(_st._subset()))
check("§2b an on-demand round of the emulated selection is EMPTY (no probe at all)",
      _st._subset(list(EP.DEMO_STATUSES)) == [], str(_st._subset(list(EP.DEMO_STATUSES))))
check("§2b v1.6.5: the unmanaged card is in the skip set too (ONE rule, two families)",
      _unmanaged_ids <= _st._skip_ids
      and _st._subset(list(_unmanaged_ids)) == [],
      f"skip={sorted(_st._skip_ids)}")
check("§2b ...so a round over the demo alone never starts (nothing to probe)",
      _st.start_round() is False and _st.is_busy is False)
_own = win.scene.add_server(ServerData(id="own-1", alias="mine", host="10.1.2.3", user="root"))
win._sync_status_targets()
check("§2b a node of the USER's own (not in the declaration) IS probed as always",
      [t[0] for t in _st._subset()] == ["own-1"]
      and _st._subset(["own-1"]) == [("own-1", "10.1.2.3", 22)],
      str(_st._subset()))
win.scene.remove_server(_own.data.id)
win._sync_status_targets()

# A REAL result replaces the emulation — the marker goes with it, in the same call.
win._on_node_status_changed(EP.WEB2, "offline")
check("§2b a real probe result replaces the emulated status AND its marker",
      _emulated_node.status == "offline" and _emulated_node.status_emulated is False
      and _emulated_node._demo_badge.isVisible() is False,
      f"status={_emulated_node.status} emulated={_emulated_node.status_emulated}")
check("§2b ...and the card is a plain card again (the age line is back on the menu)",
      _emulated_node.is_stale is False
      and _t("node.status.emulated") not in _emulated_node.toolTip(),
      _emulated_node.toolTip())

# Every ordinary load ends the emulation.
win._new_project()
check("§2b a new project drops the emulation state and the skip set",
      win._emulated_statuses == {} and _st._subset() == [] and _st._skip_ids == set(),
      f"emulated={win._emulated_statuses} skip={_st._skip_ids}")
check("§2b ...and the deleted cards took their badges with them",
      win.scene.node_count() == 0)
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the undo affordance: armed by _push_command(), carried by the message ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
load_example(win)
_nodes = {n.data.id: n for n in win.scene.nodes()}
_any_id = next(iter(_nodes))
_any = _nodes[_any_id]
_note = win.scene.notes()[0]


def _cmd(cls, mode):
    """Build a command of `cls` in `mode` — only what the classifier reads matters."""
    if cls is CmdAddRemoveNode:
        return cls(win, win.scene, _any.data, mode)
    if cls is CmdAddRemoveNodeBatch:
        return cls(win, win.scene, [_any.data], mode)
    if cls is CmdAddRemoveConnection:
        return cls(win, win.scene, _any_id, _any_id, "", "ssh", mode)
    if cls is CmdAddRemoveNote:
        return cls(win, win.scene, {"id": "n1", "text": "x"}, mode)
    if cls is CmdAttachNote:
        return cls(win, _note, _any_id, mode)
    return cls(win, mode)


check("§3 deleting a node OFFERS undo", _cmd(CmdAddRemoveNode, "remove").offers_undo())
check("§3 adding one does not (nothing was lost)",
      not _cmd(CmdAddRemoveNode, "add").offers_undo())
check("§3 a bulk import offers undo in BOTH directions (one gesture, many cards)",
      _cmd(CmdAddRemoveNodeBatch, "add").offers_undo()
      and _cmd(CmdAddRemoveNodeBatch, "remove").offers_undo())
check("§3 disconnecting offers undo; connecting does not",
      _cmd(CmdAddRemoveConnection, "remove").offers_undo()
      and not _cmd(CmdAddRemoveConnection, "add").offers_undo())
check("§3 deleting a note offers undo; adding one does not",
      _cmd(CmdAddRemoveNote, "remove").offers_undo()
      and not _cmd(CmdAddRemoveNote, "add").offers_undo())
check("§3 UNPINNING a note offers undo (it stops following its server)",
      _cmd(CmdAttachNote, "detach").offers_undo()
      and not _cmd(CmdAttachNote, "attach").offers_undo())
check("§3 a move / a text edit / a group fold never offer undo (no loss)",
      not CmdMoveNode(win, _any, _any.pos(), _any.pos()).offers_undo()
      and not CmdEditTextNote(win, _note, "", "x").offers_undo()
      and hasattr(CmdToggleGroupCollapse, "offers_undo"))
check("§3 the classifier is DECLARED on the command (one place, no scattered type list)",
      CmdAddRemoveNode.DESTRUCTIVE_MODES == ("remove",)
      and CmdAddRemoveNodeBatch.DESTRUCTIVE_MODES == ("add", "remove")
      and "offers_undo" in open(os.path.join(ROOT, "modules", "undo_commands.py"),
                                encoding="utf-8").read())

bar = win.statusBar()
bar.clearMessage()
check("§3 a fresh status bar offers nothing", not bar.is_offer_visible() and not bar.is_armed())
bar.showMessage("Ready again.")
check("§3 a plain message (no command behind it) shows no button",
      not bar.is_offer_visible(), bar.offer_text())
win._on_status_filter_clicked("offline")     # a VIEW state — outside the stack (§4.2)
check("§3 a view action (the status filter) never offers undo",
      not bar.is_offer_visible() and not bar.is_armed())
win._on_status_filter_clicked("offline")     # reset the transient filter

win._push_command(CmdAddRemoveNode(win, win.scene, _any.data, "remove"))
check("§3 _push_command() ARMED the affordance (nothing shows before a message)",
      bar.is_armed() and not bar.is_offer_visible())
bar.showMessage("Server deleted: " + _any.data.alias)
check("§3 the action's OWN message carries the button",
      bar.is_offer_visible() and bar.offer_text() == "Server deleted: " + _any.data.alias,
      repr(bar.offer_text()))
check("§3 the offer auto-clears on its own (a running timeout)",
      bar._timer.isActive() and bar.OFFER_TIMEOUT_MS > 0, str(bar.OFFER_TIMEOUT_MS))
_deleted_count = win.scene.node_count()
bar._offer_btn.click()
app.processEvents()
check("§3 the click runs the window's undo — the node is back",
      win.scene.node_count() == _deleted_count + 1, str(win.scene.node_count()))
check("§3 ...and the offer is gone with it (a satisfied offer never stays)",
      not bar.is_offer_visible())

win._push_command(CmdAddRemoveNode(win, win.scene, _any.data, "remove"))
bar.showMessage("Server deleted again")
check("§3 the offer is up again", bar.is_offer_visible())
bar.clear_offer()                            # the timeout slot — the auto-clear path
check("§3 the timeout slot drops the offer", not bar.is_offer_visible())

win._push_command(CmdAddRemoveNode(win, win.scene, _any.data, "remove"))
bar.showMessage("Server deleted a third time")
bar.showMessage("Something else happened")
check("§3 a LATER message clears the offer (it belongs to ONE sentence)",
      not bar.is_offer_visible())
win._push_command(CmdAddRemoveNode(win, win.scene, _any.data, "remove"))
bar.showMessage("And once more")
check("§3 a NEW arming survives the message that consumed the previous offer",
      bar.is_offer_visible())
win._reset_undo_stack()                      # a save/load/new — the stack it pointed at is gone
check("§3 a rebased stack (save / load / new) drops the offer",
      not bar.is_offer_visible())

bar.clearMessage()
win._push_command(CmdMoveNode(win, _any, _any.pos(), _any.pos()))
check("§3 a NON-destructive push does not arm the offer", not bar.is_armed())
bar.showMessage("Moved the card")
check("§3 ...and that message shows no button", not bar.is_offer_visible())
check("§3 the window really installed its own status bar (the one that can offer)",
      type(bar).__name__ == "UndoStatusBar"
      and bar.isAncestorOf(bar._offer), type(bar).__name__)

# A TERMINAL action has no command at all — it can never offer a way back. The probe is
# the ordinary message path the terminal uses (`_on_plugin_status_requested` style).
bar.clearMessage()
bar.showMessage(_t("status.connected"), 4000)
check("§3 a terminal-style report (no command behind it) offers nothing",
      not bar.is_offer_visible() and not bar.is_armed())
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §4 status freshness: the age is a LABEL, never a status ==")
# ════════════════════════════════════════════════════════════════════════════

_st = StatusChecker(interval_ms=30_000)
check("§4 the threshold is max(2 × the round interval, the floor)",
      _st.stale_threshold_s() == STALE_MIN_SEC == 90.0, str(_st.stale_threshold_s()))
_st.set_interval(5_000)
check("§4 ...a short interval does not turn 'stale' into noise (the floor holds)",
      _st.stale_threshold_s() == STALE_MIN_SEC, str(_st.stale_threshold_s()))
_st.set_interval(120_000)
check("§4 ...a long interval stretches it (two missed rounds)",
      _st.stale_threshold_s() == 240.0, str(_st.stale_threshold_s()))
check("§4 a server that was never probed is NOT stale (there is no datum to age)",
      _st.last_checked_at("nope") == 0.0 and _st.is_stale("nope") is False)
check("§4 the checker TIMESTAMPS every result and every completed round",
      "_last_times[sid] = time.time()" in open(
          os.path.join(ROOT, "services", "status_checker.py"), encoding="utf-8").read())

node = ServerNode(ServerData(id="fresh01", alias="fresh", host="192.0.2.10", user="root"))
check("§4 a never-checked card has no age line and is not stale",
      node.freshness_text() == "" and node.is_stale is False
      and node.status_checked_at == 0.0)

node.set_status("online")
_threshold = 90.0
node.set_checked_at(time.time(), _threshold)
check("§4 a fresh result says 'just now' and keeps the status tone",
      _t("node.status.checked_now") in node.toolTip() and node.is_stale is False
      and node._status_dot.brush().color().name()
      == QColor(theme.STATUS_COLORS["online"]).name(), node.toolTip())
_fresh_rect = node._status_dot.path().boundingRect()

node.set_checked_at(time.time() - _threshold - 30.0, _threshold)
check("§4 an old result paints the STALE mark (the idle tone, not the status tone)",
      node.is_stale is True
      and node._status_dot.brush().color().name() == QColor(theme.DOT_IDLE).name(),
      node._status_dot.brush().color().name())
check("§4 ...but it is the SAME declared SHAPE (the second channel survives)",
      node._status_dot.path().boundingRect() == _fresh_rect,
      f"{node._status_dot.path().boundingRect()} vs {_fresh_rect}")
check("§4 the tooltip answers HOW OLD the datum is",
      _t("node.status.checked_ago", minutes=2) in node.toolTip(), node.toolTip())
check("§4 FRESHNESS NEVER CHANGES THE STATUS (a stale online stays online)",
      node.status == "online"
      and node._state_pen().color().name() == QColor(theme.STATUS_COLORS["online"]).name(),
      node.status)
check("§4 ...and the declared shape is still the one of that status",
      round(node._status_dot.path().boundingRect().width(), 3)
      == round(status_shape.shape_path("online", 14.0).boundingRect().width(), 3))
node.set_checked_at(0.0, _threshold)
check("§4 resetting the datum (a new host/port) removes the age again",
      node.is_stale is False and node.freshness_text() == "")
node.reset_status()
check("§4 ...and a status reset clears the timestamp with it",
      node.status_checked_at == 0.0)


class _StubChecker:
    """A checker double that answers only what freshness asks — and COUNTS round starts."""

    def __init__(self):
        self.started = 0
        self.checked_at = time.time()

    def last_checked_at(self, _sid):
        return self.checked_at

    def stale_threshold_s(self):
        return 90.0

    def start_round(self, *_a, **_k):
        self.started += 1
        return True


win = make_main()
load_example(win)
_probe_node = win.scene.nodes()[0]
_stub = _StubChecker()
win._status_checker = _stub
win._on_node_status_changed(_probe_node.data.id, "online")
check("§4 a result that just arrived is fresh (the window dated it from the checker)",
      _probe_node.is_stale is False
      and _t("node.status.checked_now") in _probe_node.toolTip(), _probe_node.toolTip())
_stub.checked_at = time.time() - 600.0        # ten minutes old — a stalled round
win._freshness_tick()
check("§4 the freshness TICK marks a stalled round as stale",
      _probe_node.is_stale is True, _probe_node.toolTip())
check("§4 ...and the status it labels is untouched", _probe_node.status == "online")
check("§4 the tick starts NO probe round by itself (it is a repaint, not a check)",
      _stub.started == 0, str(_stub.started))
check("§4 the tick is a repaint by construction (no round call in its code path)",
      "start_round" not in
      open(os.path.join(ROOT, "ui", "main_window.py"), encoding="utf-8").read()
      .split("def _refresh_status_freshness")[1].split("def ")[0])
_stub.checked_at = time.time()
win._freshness_tick()
check("§4 a new result takes the mark back (the tick is honest both ways)",
      _probe_node.is_stale is False)
check("§4 the timer is a slow repaint tick, not a probe loop",
      win.FRESHNESS_TICK_MS >= 10_000, str(win.FRESHNESS_TICK_MS))
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the first screen: the palette by name, the cheat-sheet on ? / F1 ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_hint = win.empty_state.palette_text()
check("§5 the empty state NAMES the command palette", bool(_hint.strip()), _hint)
check("§5 ...with the LIVE hotkey of the registry (not a literal in the widget)",
      default_sequence("palette.open") in _hint, _hint)
check("§5 ...and it names the `?` key of the cheat-sheet", "?" in _hint, _hint)
check("§5 the example button shares the first screen with the primary action",
      bool(win.empty_state.btn_example.text()) and bool(win.empty_state.btn_add_first.text())
      and win.empty_state.btn_example.geometry().width() > 0
      and win.empty_state.btn_example.geometry().right()
      <= win.empty_state.geometry().right(),
      f"{win.empty_state.btn_add_first.geometry()} {win.empty_state.btn_example.geometry()}")

pal = win._command_palette
pal._collect_commands()
pal.input.clear()
pal._refilter("")
check("§5 an empty query opens on the bounded 'Start here' block",
      pal.listw.item(0).text() == _t("palette.start_here"), repr(pal.listw.item(0).text()))
check("§5 the caption is not a command (it cannot be run)",
      not (pal.listw.item(0).flags() & Qt.ItemFlag.ItemIsEnabled))
check("§5 the block is BOUNDED", 0 < len(pal._start_here) <= CP.START_HERE_MAX,
      str(len(pal._start_here)))
check("§5 the cursor lands on the first real COMMAND, never on the caption",
      pal.listw.currentRow() == pal._header_rows and pal.listw.currentRow() > 0,
      str(pal.listw.currentRow()))
check("§5 no command of the block is listed twice",
      len({pal.listw.item(i).text() for i in range(pal.listw.count())})
      == pal.listw.count())
check("§5 the block offers ACTIONS (never a server or a plugin row)",
      bool(pal._start_here) and all(entry[1] == "action" for entry in pal._start_here))
pal.input.setText("save")
pal._refilter()
check("§5 a TYPED query is a search again (no caption, no block)",
      pal._header_rows == 0 and pal.listw.item(0).text() != _t("palette.start_here"),
      pal.listw.item(0).text())
pal.input.clear()
pal._refilter("")
pal._run_current()                            # runs the first command of the block
check("§5 running a command records it for the next block",
      bool(pal._recent) and pal._recent[0] in CP.START_HERE_ACTION_IDS, str(pal._recent))
pal._collect_commands()
pal._refilter("")
check("§5 ...and the recorded action comes FIRST in that block",
      pal._start_here[0][2] is not None and pal._recent[0] in CP.START_HERE_ACTION_IDS)

check("§5 the registry ships the cheat-sheet action with F1",
      configured_hotkeys().get("help.cheatsheet") == "F1",
      repr(configured_hotkeys().get("help.cheatsheet")))
check("§5 ...and 'Open the example map' is assignable with no default key",
      default_sequence("help.example") == "" and "help.example" in action_ids())
_sheets.clear()
win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Question,
                            Qt.KeyboardModifier.ShiftModifier, "?"))
check("§5 `?` opens the cheat-sheet", len(_sheets) == 1, str(len(_sheets)))
_sheets.clear()
win.act_cheatsheet.trigger()
check("§5 the Help item (F1) opens the same window", len(_sheets) == 1)
check("§5 the sheet is the registry-derived text Help → About already builds "
      "(no second source of truth)",
      bool(_sheets) and _sheets[-1].sheet_text() == cheatsheet()
      and "Ctrl+K" in _sheets[-1].sheet_text(),
      (_sheets[-1].sheet_text()[:60] if _sheets else "no sheet"))
check("§5 the sheet window re-reads the registry on retranslate (the container rule)",
      hasattr(HSD.HotkeySheetDialog, "retranslate")
      and hasattr(HSD.HotkeySheetDialog, "refresh_sheet"))
# A deliberately DISABLED palette key must not produce a broken sentence.
_save_config({"hotkeys": {"palette.open": ""}})
check("§5 a DISABLED palette hotkey still leaves a readable hint (the registry default)",
      "{" not in win.empty_state.palette_text()
      and default_sequence("palette.open") in win.empty_state.palette_text(),
      win.empty_state.palette_text())
_save_config({"hotkeys": {}})
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the screenshot probe: the demo map really renders ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_main()
_palette_before = theme.THEME
for server in _servers:
    win.scene.add_server(server_data_from_dict(server))
for conn in _conns:
    win.scene.add_connection(conn["source_id"], conn["target_id"], conn.get("label", ""),
                             conn["type"], bidirectional=bool(conn.get("bidirectional", False)))
win.scene.add_group(name="Web tier", x=-420.0, y=-260.0, width=550.0, height=240.0)
_shift = len(win.scene.notes())
_pixmap = win.scene.render_to_pixmap(scale=1.0)
check("§6 the demo map renders to a pixmap (the acceptance's screenshot)",
      _pixmap is not None and not _pixmap.isNull()
      and _pixmap.width() > 600 and _pixmap.height() > 300,
      f"{_pixmap.width()}x{_pixmap.height()}" if _pixmap is not None else "None")
_image = _pixmap.toImage()
_shots = os.path.join(WORK, "example_map.png")
_ok = _pixmap.save(_shots, "PNG")
check("§6 ...and the PNG lands on disk (the README source is one command away)",
      bool(_ok) and os.path.getsize(_shots) > 5000,
      str(os.path.getsize(_shots) if _ok else 0))
_corner = QColor(_image.pixel(2, 2))
check("§6 an export is PRINT-FRIENDLY by default: the page of a dark window is LIGHT",
      _corner.lightness() > 180, f"{_corner.name()} lightness={_corner.lightness()}")
_ink = sum(1 for x in range(0, _image.width(), 7) for y in range(0, _image.height(), 7)
           if QColor(_image.pixel(x, y)).lightness() < 160)
check("§6 ...and the map is really drawn on it (the strokes are there)", _ink > 50, str(_ink))
check("§6 the render gives the window its own palette back (no export leak)",
      theme.THEME is _palette_before, str(theme.THEME))
check("§6 the demo needs no image file: the render has no background dependency",
      win.scene.background() is None and _shift == len(win.scene.notes()))
win.close()


# ════════════════════════════════════════════════════════════════════════════
print("== §7 the release state (version, i18n, the registry, the hub) ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
_langs = load_i18n_langs(ROOT)
check_i18n_parity(_langs)
check_i18n_format(_langs)
for _key in ("help.cheatsheet", "hotkeys.sheet_hint", "example.open",
             "empty.state.palette_hint", "example.note_text", "title.example",
             "status.example_loaded", "status.undo_hint", "node.status.checked_now",
             "node.status.checked_ago", "palette.start_here"):
    check(f"§7 the key {_key} is in every discovered language",
          all(_key in _langs[code] for code in _langs), str(sorted(_langs)))
check(f"§7 the i18n pin is the shipped one ({EXPECTED_I18N_KEYS})",
      all(len([k for k in _langs[c] if k not in ("name", "partial")]) == EXPECTED_I18N_KEYS
          for c in _langs), str({c: len(_langs[c]) for c in sorted(_langs)}))
_hub = SettingsDialog(make_main())
check("§7 this version adds no config key beyond the terminal cursor shape (the hub collects 23)",
      len(_hub.collect()) == 23, str(sorted(_hub.collect())))
_hub.close()

finish()
