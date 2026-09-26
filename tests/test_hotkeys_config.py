# -*- coding: utf-8 -*-
"""v1.3.2 — Configurable hotkeys (QKeySequenceEdit, action registry): the release's test.

ROADMAP v1.3.2:
  #1 The action registry (ui/hotkey_registry.py) — ONE declarative list
     {action_id: {label_i18n_key, default_sequence}} covering every existing global
     action; menu QActions/QShortcuts are created FROM it (no literal sequence is
     scattered across the modules);
  #2 The "Hotkeys" tab of SettingsDialog — a table [action | hotkey] with a
     QKeySequenceEdit per row; an empty sequence = the hotkey is disabled (the action
     stays available from the menu); two actions with the same sequence → both rows
     marked + a warning, saving is still possible;
  #3 Storage & application — the "hotkeys" key of ~/.sshmap/config.json (a dict
     action_id → "Ctrl+K", merge-write); applied at startup (after the UI construction)
     and live after the dialog's OK without a restart (QAction.setShortcut /
     QShortcut.setKey); an unknown key / a broken value → the default;
  #4 F12 multi-input — the sequence is configurable, the "install ONLY while the mode
     is on" rule (v1.2.3/v1.2.4-fix) is preserved;
  #5 The scope boundary — the terminal canvas's own keys (F1–F12, Ctrl+C/D/Z, arrows)
     are NOT in the registry (pinned in DOCUMENTATION.md; checked here as "no orphans").
  #6 i18n keys settings.hotkeys.* / settings.tab.hotkeys × en/ru/zh — parity 453 → 458.

v1.3.3.3 (ROADMAP task 1–4) grew the registry from 18 to 40 actions: `file.save_as`
gained Ctrl+Shift+S, the zoom family (Ctrl+0 / Ctrl+= / Ctrl+-) became actions, and the
remaining global actions (the exports, the backups, center/collapse/expand, the
selection operations, profile/logs/exit) entered the registry with an EMPTY default —
the "no hotkey, but assignable" value. This file keeps covering the STORAGE +
APPLICATION contract for the grown registry; the completeness audit, the real
shortcut firing and the dialog's reset button live in tests/test_actions_keyboard.py.
v1.3.3.7 added `file.export_svg` (the SVG export) as one more empty-default action — 41.
v1.4rc1 added `plugins.reload` (the plugin re-discovery) — 42, 20 of them empty-default.
v1.4rc3 added `plugins.run_on_nodes` (the `run_on_nodes` hook for the selection) — 43,
21 of them empty-default.
v1.4.1 added `file.import_ssh_config` (the second import path, File menu) — 44,
22 of them empty-default.

Run: python tests/test_hotkeys_config.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import re
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, read_cfg, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QKeySequenceEdit

app = QApplication(sys.argv)

import i18n
from i18n import t
import modules.multi_input as MI
import ui.main_window as MW
import ui.hotkey_registry as HR
from ui.settings_dialog import SettingsDialog

CFG_PATH = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")

# The v1.3.1.1 shortcuts + the v1.3.3.3 additions (task 1: file.save_as Ctrl+Shift+S;
# task 2: view.reset_zoom/zoom_in/zoom_out Ctrl+0 / Ctrl+= / Ctrl+-). The actions with
# an EMPTY default (task 3) are listed separately below — they are assignable, not
# pre-bound. Canonical PortableText: "Delete" is "Del".
EXPECTED_DEFAULTS = {
    "file.new": "Ctrl+N", "file.open": "Ctrl+O", "file.save": "Ctrl+S",
    "file.save_as": "Ctrl+Shift+S",
    "edit.undo": "Ctrl+Z", "edit.redo": "Ctrl+Shift+Z",
    "edit.add_server": "Ctrl+Shift+A", "edit.add_group": "Ctrl+Shift+G",
    "edit.add_connection": "Ctrl+Shift+C", "edit.properties": "Ctrl+I",
    "edit.duplicate": "Ctrl+D", "edit.delete": "Del",
    "node.ssh_connect": "Ctrl+Return", "node.edit_server": "Ctrl+E",
    "node.add_note": "Ctrl+Shift+N",
    "view.fit_map": "Ctrl+Shift+F", "view.find_on_map": "Ctrl+F",
    "view.reset_zoom": "Ctrl+0", "view.zoom_in": "Ctrl+=", "view.zoom_out": "Ctrl+-",
    "palette.open": "Ctrl+K", "view.multi_input": "F12",
    # v1.5rc3 (ROADMAP task 4): the cheat-sheet — the ONE new key of the release.
    "help.cheatsheet": "F1",
}

# v1.3.3.3 (task 3): the global actions that ship with NO hotkey (`default: ""`).
# Each of them must still be a REAL menu item (node.check_status: the Edit-menu item
# plus both context menus) and must appear as a row in the "Hotkeys" tab.
EMPTY_DEFAULT_IDS = {
    "node.check_status",
    "file.import_servers", "file.export_png", "file.export_drawio", "file.export_pdf",
    "file.export_svg",
    # v1.5.1: the two map-image actions (the 2× clipboard copy and the fixed-frame poster).
    "file.copy_map", "file.docs_frame",
    "file.backups", "file.restore_autosave", "file.exit",
    "edit.connect_selected", "edit.delete_selected",
    "view.center_map", "view.collapse_all", "view.expand_all",
    "view.set_background", "view.remove_background",
    "profile.manage", "help.open_logs", "help.about",
    # v1.4rc1: the plugin foundation — "Reload plugins" (the re-discovery of the sources).
    "plugins.reload",
    # v1.4rc3: the plugin foundation — "Run on selected servers" (the `run_on_nodes` hook
    # of every loaded plugin for the current selection).
    "plugins.run_on_nodes",
    # v1.4.1: the second import path — "Import from SSH Config…" (File menu).
    "file.import_ssh_config",
    # v1.4.2: the minimap panel — a checkable View item (the ROADMAP task 2).
    "view.toggle_minimap",
    # v1.4.5: the legend panel — a checkable View item + its toolbar mirror (task 4).
    "view.toggle_legend",
    # v1.5rc3: "Open the example map" — the Help item of the demo map (no key out of the box).
    "help.example",
    # v1.5rc4: "Focus the map" — the keyboard handover to the canvas (task 6); the ONE
    # new registry action of the release, an EMPTY default like its neighbours.
    "view.focus_map",
    # v1.5.2: the activity panel — the checkable View item of the history surface (task 3).
    "view.toggle_activity",
    # v1.5.3: the freshness pair — "Gather information" (the bounded batch for the
    # selection / all) and "Why is it offline?" (the reachability report). Both live on a
    # permanent Edit-menu item and are assignable, with no key out of the box.
    "node.collect_info", "node.diagnose",
    # v1.5.5: the inventory report of the LIST mode — "Copy List as TSV" and
    # "Export List…" (the visible server table leaves the application).
    "file.copy_list", "file.export_list",
    # v1.6: the bulk edit of the selection (tags / comment / quick launch in ONE undo
    # step), the auto-arrangement of a group's members and the connection report — all
    # three are permanent menu items (Edit / Edit / Export) with no key out of the box.
    "edit.selected", "edit.arrange_group", "file.export_connections",
}
def new_window():
    """A MainWindow with the autosave timer stopped (no event loop in the tests)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    return w


def canon(text):
    """The canonical (PortableText) form Qt itself yields — "Ctrl+Shift+Alt+S" → "Ctrl+Alt+Shift+S"."""
    return QKeySequence(text).toString()


def action_sequences(window, action_id):
    """The installed sequences of every registered target of an action.

    A DISABLED target contributes an empty string (an empty QKeySequence) — that is
    how the UI reports "no hotkey" for both a QAction (setShortcuts([])) and a
    QShortcut (an empty key).
    """
    out = []
    for obj in window._hotkey_targets.get(action_id, []):
        if isinstance(obj, QShortcut):
            out.append(obj.key().toString())
        else:
            seqs = [s.toString() for s in obj.shortcuts()]
            out.extend(seqs or [""])
    return out


ALL_IDS = sorted(set(EXPECTED_DEFAULTS) | EMPTY_DEFAULT_IDS)

# ════════════════════════════════════════════════════════════
# 1. The registry: completeness, labels, no orphans (task 1)
# ════════════════════════════════════════════════════════════
print("== 1. the action registry ==")

ids = HR.action_ids()
check("registry: the grown action set (23 sequenced + 36 empty-default; v1.5rc3 adds F1, "
      "v1.5rc4 adds view.focus_map, v1.5.1 the two map-image actions, v1.5.3 the "
      "freshness pair, v1.5.5 the inventory pair, v1.6 the bulk edit / arrangement / "
      "connection report trio)",
      set(ids) == set(ALL_IDS) and len(ids) == 59,
      str(sorted(set(ids) ^ set(ALL_IDS))))
check("registry: the sequenced defaults are the v1.3.1.1 set + the v1.3.3.3 additions "
      "+ help.cheatsheet (F1, v1.5rc3)",
      {a: HR.default_sequence(a) for a in ids if HR.default_sequence(a)} == EXPECTED_DEFAULTS,
      str({a: HR.default_sequence(a) for a in ids if HR.default_sequence(a)}))
check("registry: exactly the 36 remaining global actions carry an EMPTY default",
      {a for a in ids if not HR.default_sequence(a)} == EMPTY_DEFAULT_IDS
      and set(HR.empty_default_action_ids()) == EMPTY_DEFAULT_IDS,
      str(sorted(EMPTY_DEFAULT_IDS ^ {a for a in ids if not HR.default_sequence(a)})))
check("registry: an empty default really means [] (no sequence to install)",
      all(HR.sequences_for(a, "") == [] for a in EMPTY_DEFAULT_IDS))
check("registry: 'view.multi_input' is the only dynamic action",
      [a for a in ids if HR.is_dynamic(a)] == ["view.multi_input"])
check("registry: redo carries the legacy Ctrl+Y alias",
      HR.alt_sequences("edit.redo") == ("Ctrl+Y",)
      and HR.sequences_for("edit.redo", "Ctrl+Shift+Z") == ["Ctrl+Shift+Z", "Ctrl+Y"])
check("registry: a custom sequence drops the legacy alias (and non-defaults get none)",
      HR.sequences_for("edit.redo", "Ctrl+Alt+Z") == ["Ctrl+Alt+Z"]
      and HR.sequences_for("file.save", "Ctrl+Alt+S") == ["Ctrl+Alt+S"])
check("registry: default_hotkeys() is the full mapping the reset button writes",
      HR.default_hotkeys() == {a: HR.default_sequence(a) for a in ids}
      and set(HR.default_hotkeys()) == set(ids))

langs = load_i18n_langs(ROOT)
label_keys = {a: HR.action_label_key(a) for a in ids}
missing_labels = [(a, k) for a, k in label_keys.items()
                  if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh", "de"))]
check("registry: every action label is an existing i18n key (en/ru/zh/de)", not missing_labels,
      str(missing_labels))

# normalize(): the storage form is canonical, "" = disabled, None = broken
check("normalize: canonical PortableText (Delete and Del are one sequence)",
      HR.normalize("Delete") == HR.normalize("Del") == "Del")
check("normalize: an empty string is the DISABLED value, not a broken one",
      HR.normalize("") == "" and HR.normalize("   ") == "")
check("normalize: a broken value is None (a non-string or an unparsable sequence)",
      HR.normalize(12) is None and HR.normalize(["Ctrl+K"]) is None
      and HR.normalize("Ctrl+NotAKey") is None)

clear_cfg()
mw = new_window()
check("window: all 59 registry actions are bound to real targets",
      set(mw._hotkey_targets) == set(ids) and all(mw._hotkey_targets.values()),
      str(sorted(set(ids) ^ set(mw._hotkey_targets))))

# "No orphans": every non-empty sequence of the window belongs to the registry map.
registered = set()
for aid in ids:
    registered.update(HR.sequences_for(aid, mw._hotkey_map.get(aid)))
orphans = sorted({a.shortcut().toString() for a in mw.findChildren(QAction)
                  if a.shortcut().toString()
                  and a.shortcut().toString() not in registered}
                 | {sc.key().toString() for sc in mw.findChildren(QShortcut)
                    if sc.key().toString() and sc.key().toString() not in registered})
check("window: no orphan shortcut — every sequence belongs to the registry", not orphans,
      str(orphans))
# v1.3.3.3: no DUPLICATE either — two enabled QActions with one sequence make Qt report
# "Ambiguous shortcut overload" and fire NEITHER (the toolbar-mirror regression found by
# tests/test_actions_keyboard.py while adding Ctrl+Shift+S).
_holder = {}
for _act in mw.findChildren(QAction):
    _seq = _act.shortcut().toString()
    if _seq:
        _holder.setdefault(_seq, []).append(_act)
_dups = sorted(s for s, acts in _holder.items()
               if len([x for x in acts if x.isEnabled()]) > 1)
check("window: no sequence is installed twice (no 'Ambiguous shortcut overload')",
      not _dups, str(_dups))
check("window: the registry defaults are installed (Ctrl+S / Ctrl+F / Ctrl+K / Ctrl+Shift+F)",
      action_sequences(mw, "file.save") == ["Ctrl+S"]
      and action_sequences(mw, "view.find_on_map") == ["Ctrl+F"]
      and action_sequences(mw, "view.fit_map") == ["Ctrl+Shift+F"]
      and action_sequences(mw, "palette.open") == ["Ctrl+K"],
      str({a: action_sequences(mw, a) for a in
           ("file.save", "view.find_on_map", "view.fit_map", "palette.open")}))
check("window: the v0.9.2 set is installed (Ctrl+Return / Ctrl+E / Ctrl+Shift+N) and Delete",
      action_sequences(mw, "node.ssh_connect") == ["Ctrl+Return"]
      and action_sequences(mw, "node.edit_server") == ["Ctrl+E"]
      and action_sequences(mw, "node.add_note") == ["Ctrl+Shift+N"]
      and action_sequences(mw, "edit.delete") == ["Del"])
check("window: the v1.3.3.3 defaults are installed (Save As + the zoom family)",
      action_sequences(mw, "file.save_as") == ["Ctrl+Shift+S"]
      and action_sequences(mw, "view.reset_zoom") == ["Ctrl+0"]
      and action_sequences(mw, "view.zoom_in") == ["Ctrl+="]
      and action_sequences(mw, "view.zoom_out") == ["Ctrl+-"],
      str({a: action_sequences(mw, a) for a in
           ("file.save_as", "view.reset_zoom", "view.zoom_in", "view.zoom_out")}))
check("window: an empty-default action is installed as NO hotkey (the menu item stays)",
      all(action_sequences(mw, a) == [""] for a in EMPTY_DEFAULT_IDS),
      str({a: action_sequences(mw, a) for a in sorted(EMPTY_DEFAULT_IDS)}))
check("window: undo/redo — the single Edit-menu target follows the map",
      action_sequences(mw, "edit.undo") == ["Ctrl+Z"]
      and action_sequences(mw, "edit.redo") == ["Ctrl+Shift+Z", "Ctrl+Y"])

# The literal sequences must be gone from the UI modules (the registry is the only source).
src_literals = []
for name in ("main_window.py", "main_window_ssh.py", "map_search_bar.py", "settings_dialog.py",
             "about_dialog.py"):
    with open(os.path.join(ROOT, "ui", name), encoding="utf-8") as f:
        src = f.read()
    for m in re.finditer(r'setShortcut(?:s)?\(\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\')', src):
        src_literals.append((name, m.group(0)))
check("source: no literal setShortcut(...) sequences left in the UI modules", not src_literals,
      str(src_literals))

# ════════════════════════════════════════════════════════════
# 2. Storage: load / save / merge / broken values (task 3)
# ════════════════════════════════════════════════════════════
print("== 2. storage & validation ==")

check("load: an empty config yields the registry defaults (empty ones included)",
      mw._hotkey_map == {a: HR.default_sequence(a) for a in ids}, str(mw._hotkey_map))

write_cfg({"hotkeys": {"file.save": "Ctrl+Alt+S", "edit.delete": ""},
           "language": "ru", "terminal_palette": "nord"})
effective = HR.configured_hotkeys()
check("load: a saved sequence replaces the default, an empty one disables the hotkey",
      effective["file.save"] == "Ctrl+Alt+S" and effective["edit.delete"] == ""
      and effective["file.open"] == "Ctrl+O", str(effective))

write_cfg({"hotkeys": {"file.save": 12, "file.open": "Ctrl+NotAKey", "nope.id": "Ctrl+Q"}})
effective = HR.configured_hotkeys()
check("load: a broken value (non-string / unparsable) falls back to the default",
      effective["file.save"] == "Ctrl+S" and effective["file.open"] == "Ctrl+O",
      str({k: effective[k] for k in ("file.save", "file.open")}))
check("load: an unknown action_id is ignored (a downgrade must not break the read)",
      "nope.id" not in effective and set(effective) == set(ALL_IDS))
write_cfg({"hotkeys": "broken-not-a-dict"})
check("load: a non-dict 'hotkeys' value yields the defaults",
      HR.configured_hotkeys() == {a: HR.default_sequence(a) for a in ids})

# v1.3.3.3: an ASSIGNED sequence on an action that ships with an empty default
write_cfg({"hotkeys": {"view.collapse_all": "Ctrl+Alt+C", "file.exit": "Ctrl+Q"}})
effective = HR.configured_hotkeys()
check("load: an empty-default action keeps a sequence the user assigned to it",
      effective["view.collapse_all"] == "Ctrl+Alt+C" and effective["file.exit"] == "Ctrl+Q"
      and effective["file.export_png"] == "", str(effective))

clear_cfg()
check("save: save_hotkeys() writes the 59 registry ids and returns True",
      HR.save_hotkeys({"file.save": "Ctrl+Alt+S"}) and
      set(read_cfg({})["hotkeys"]) == set(ALL_IDS))
check("save: normalized values (a broken mapping value is stored as the default)",
      read_cfg({})["hotkeys"]["file.save"] == "Ctrl+Alt+S"
      and HR.save_hotkeys({"file.open": 42}) and read_cfg({})["hotkeys"]["file.open"] == "Ctrl+O")
check("save: the empty defaults are written as \"\" (a documented value, not a hole)",
      read_cfg({})["hotkeys"]["help.open_logs"] == ""
      and read_cfg({})["hotkeys"]["node.check_status"] == "")
write_cfg({"language": "ru", "terminal_palette": "nord"})
HR.save_hotkeys({"file.save": "Ctrl+Alt+S"})
cfg = read_cfg({})
check("save: the merge keeps the foreign config keys (language / terminal_palette)",
      cfg.get("language") == "ru" and cfg.get("terminal_palette") == "nord"
      and cfg["hotkeys"]["file.save"] == "Ctrl+Alt+S", str(sorted(cfg)))
check("save: the file stays valid JSON with the 'hotkeys' key",
      isinstance(read_cfg({}).get("hotkeys"), dict))

# ════════════════════════════════════════════════════════════
# 3. The "Hotkeys" tab of the settings dialog (task 2)
# ════════════════════════════════════════════════════════════
print("== 3. the settings dialog ==")

clear_cfg()
dlg = SettingsDialog(None)
check("dialog: 8 tabs (v1.4.3: + Appearance) with 'Hotkeys' between 'Map' and 'Language'",
      dlg.tabs.count() == 8
      and dlg.tabs.tabText(1) == t("settings.tab.appearance")
      and dlg.tabs.tabText(5) == t("settings.tab.map")
      and dlg.tabs.tabText(6) == t("settings.tab.hotkeys")
      and dlg.tabs.tabText(7) == t("settings.tab.language"),
      str([dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]))
def hotkey_row_ids(dlg):
    """The action ids in TABLE order (v1.5rc4: the table is grouped by family, so the
    row index of an action is `dlg.hotkey_row(action_id)`, never its registry index)."""
    return [dlg._hotkey_rows[row][1] for row in dlg.hotkey_action_rows()]


def grouped_ids():
    """The registry's ids in the grouped order the tab shows (family, then declaration)."""
    grouped = HR.actions_by_family()
    return [aid for family in HR.family_order() for aid in grouped[family]]


check("dialog: one ACTION row per registry action, grouped by family (v1.5rc4)",
      dlg.hotkeys_table.rowCount() == len(ids) + len(dlg.hotkey_family_rows())
      and hotkey_row_ids(dlg) == grouped_ids()
      and all(dlg.hotkey_row(a) >= 0 for a in ids))
check("dialog: the column headers [action | hotkey]",
      [dlg.hotkeys_table.horizontalHeaderItem(i).text() for i in (0, 1)]
      == [t("settings.hotkeys.action"), t("settings.hotkeys.sequence")])
check("dialog: a QKeySequenceEdit per ACTION row, prefilled with the effective sequence",
      all(isinstance(dlg.hotkeys_table.cellWidget(r, 1), QKeySequenceEdit)
          for r in dlg.hotkey_action_rows())
      and dlg.hotkey_edits["file.save"].keySequence().toString() == "Ctrl+S"
      and dlg.hotkey_edits["file.save_as"].keySequence().toString() == "Ctrl+Shift+S"
      and dlg.hotkey_edits["view.zoom_in"].keySequence().toString() == "Ctrl+="
      and dlg.hotkey_edits["view.collapse_all"].keySequence().toString() == ""
      and len(dlg.hotkey_edits) == len(ids))
check("dialog: the 'disable' hint is shown",
      dlg._lbl_hotkeys_disabled_hint.text() == t("settings.hotkeys.disabled_hint")
      and bool(dlg._lbl_hotkeys_disabled_hint.text()))
check("dialog: no conflict on the defaults (no warning, no mark)",
      dlg._lbl_hotkeys_conflict.text() == ""
      and not any("\u26a0" in dlg.hotkeys_table.item(r, 0).text()
                  for r in dlg.hotkey_action_rows()))

# A conflict: the same sequence on two rows → BOTH marked + the warning; saving still possible
dlg.hotkey_edits["edit.duplicate"].setKeySequence(QKeySequence("Ctrl+N"))
dlg._refresh_hotkey_conflicts()
conflict_ids = HR.find_conflicts(dlg.hotkey_sequences())
check("dialog: two actions with the same sequence are both detected as a conflict",
      conflict_ids == {"file.new", "edit.duplicate"}, str(conflict_ids))
check("dialog: both conflicting rows are marked, the others are not",
      "\u26a0" in dlg.hotkeys_table.item(dlg.hotkey_row("file.new"), 0).text()
      and "\u26a0" in dlg.hotkeys_table.item(dlg.hotkey_row("edit.duplicate"), 0).text()
      and not any("\u26a0" in dlg.hotkeys_table.item(dlg.hotkey_row(a), 0).text()
                  for a in ("file.save", "file.open")))
check("dialog: the conflict warning appears",
      dlg._lbl_hotkeys_conflict.text() == t("settings.hotkeys.conflict"))
collected = dlg.collect()
check("dialog: saving is still possible — collect() carries the conflicting values",
      collected["hotkeys"]["file.new"] == "Ctrl+N"
      and collected["hotkeys"]["edit.duplicate"] == "Ctrl+N")
check("dialog: collect() has exactly 23 config.json keys (+ terminal_cursor_style, v1.6.2)",
      len(collected) == 23 and "hotkeys" in collected and "theme" in collected,
      str(sorted(collected)))

# Disabling a hotkey through the table (an empty QKeySequenceEdit)
dlg.hotkey_edits["edit.duplicate"].setKeySequence(QKeySequence())
dlg._refresh_hotkey_conflicts()
check("dialog: clearing a field disables the hotkey and clears the conflict",
      dlg.hotkey_sequences()["edit.duplicate"] == ""
      and HR.find_conflicts(dlg.hotkey_sequences()) == set()
      and dlg._lbl_hotkeys_conflict.text() == "")

# An empty sequence never conflicts with another empty one
dlg.hotkey_edits["file.open"].setKeySequence(QKeySequence())
dlg.hotkey_edits["edit.properties"].setKeySequence(QKeySequence())
dlg._refresh_hotkey_conflicts()
check("dialog: two disabled (empty) hotkeys are not a conflict",
      HR.find_conflicts(dlg.hotkey_sequences()) == set()
      and dlg.hotkey_sequences()["file.open"] == "" == dlg.hotkey_sequences()["edit.properties"])
check("dialog: the 33 empty-default rows are not a conflict among themselves",
      len([a for a in EMPTY_DEFAULT_IDS if dlg.hotkey_sequences()[a] == ""]) == 36
      and HR.find_conflicts(dlg.hotkey_sequences()) == set())

# A prefill from the config (a saved value shows up in the table)
write_cfg({"hotkeys": {"file.save": "Ctrl+Alt+S"}})
dlg2 = SettingsDialog(None)
check("dialog: prefilled from ~/.sshmap/config.json",
      dlg2.hotkey_edits["file.save"].keySequence().toString() == "Ctrl+Alt+S"
      and dlg2.hotkey_edits["file.open"].keySequence().toString() == "Ctrl+O")

# The i18n of the dialog's own strings (a language switch inside the open dialog)
tab_titles = [dlg2.tabs.tabText(i) for i in range(8)]
i18n.set_language("ru")
dlg2.retranslate()
check("dialog: retranslate() updates the tab, the headers, the reset button and the row names",
      dlg2.tabs.tabText(6) == i18n.t("settings.tab.hotkeys")
      and dlg2.tabs.tabText(6) != tab_titles[6]
      and dlg2.hotkeys_table.horizontalHeaderItem(0).text() == i18n.t("settings.hotkeys.action")
      and dlg2.reset_hotkeys_btn.text() == i18n.t("settings.hotkeys.reset")
      and dlg2.hotkeys_table.item(dlg2.hotkey_row("file.new"), 0).text()
      == i18n.t("file.new_project"))
i18n.set_language("en")

# ════════════════════════════════════════════════════════════
# 4. Live application: startup + after the dialog's OK (task 3)
# ════════════════════════════════════════════════════════════
print("== 4. application at startup and live ==")

write_cfg({"hotkeys": {"file.save": "Ctrl+Alt+S", "view.find_on_map": ""}})
mw2 = new_window()
check("startup: the saved sequence is installed, the rest keeps the defaults",
      action_sequences(mw2, "file.save") == ["Ctrl+Alt+S"]
      and action_sequences(mw2, "file.open") == ["Ctrl+O"])
check("startup: an empty sequence disables the hotkey but the QAction stays available",
      action_sequences(mw2, "view.find_on_map") == [""]
      and mw2.findChild(QAction) is not None)
menu_find = [a for a in mw2.findChildren(QAction)
             if a.text().replace("&", "") == t("view.find_on_map")]
check("startup: the disabled action is still in the menu (not removed, not hidden)",
      len(menu_find) == 1 and menu_find[0].isEnabled() and not menu_find[0].shortcut().toString())

write_cfg({"hotkeys": {"nope.id": "Ctrl+Q", "file.save": "Ctrl+Alt+S"}})
mw3 = new_window()
check("startup: an unknown action_id does not break the window (the defaults survive)",
      action_sequences(mw3, "file.open") == ["Ctrl+O"]
      and action_sequences(mw3, "file.save") == ["Ctrl+Alt+S"])

# v1.3.3.3 (task 3): an action with an empty default can be ASSIGNED through the config
write_cfg({"hotkeys": {"view.collapse_all": "Ctrl+Alt+C"}})
mw3b = new_window()
check("startup: an empty-default action becomes reachable once assigned",
      action_sequences(mw3b, "view.collapse_all") == ["Ctrl+Alt+C"]
      and action_sequences(mw3b, "view.expand_all") == [""])

# LIVE: the dialog's OK (the applied signal) → _apply_settings_from_dialog, no restart
clear_cfg()
mw4 = new_window()
before = action_sequences(mw4, "file.save")
dlg3 = SettingsDialog(mw4)
dlg3.applied.connect(mw4._apply_settings_from_dialog)   # the _open_settings_dialog wiring
dlg3.hotkey_edits["file.save"].setKeySequence(QKeySequence("Ctrl+Shift+Alt+S"))
dlg3.hotkey_edits["edit.redo"].setKeySequence(QKeySequence("Ctrl+Alt+R"))
dlg3.hotkey_edits["palette.open"].setKeySequence(QKeySequence("Ctrl+Shift+K"))
dlg3._on_accept()
check("live: OK changes the QAction sequences of the SAME window (no restart)",
      before == ["Ctrl+S"] and action_sequences(mw4, "file.save") == [canon("Ctrl+Shift+Alt+S")]
      and action_sequences(mw4, "edit.redo") == ["Ctrl+Alt+R"],
      str(action_sequences(mw4, "file.save")))
check("live: the QShortcut (the command palette) follows the table too",
      action_sequences(mw4, "palette.open") == ["Ctrl+Shift+K"]
      and mw4._palette_shortcut.key().toString() == "Ctrl+Shift+K")
check("live: the new values are persisted in config.json",
      read_cfg({})["hotkeys"]["file.save"] == canon("Ctrl+Shift+Alt+S")
      and read_cfg({})["hotkeys"]["edit.redo"] == "Ctrl+Alt+R"
      and read_cfg({})["hotkeys"]["palette.open"] == "Ctrl+Shift+K")

# A disabled hotkey applied live
dlg4 = SettingsDialog(mw4)
dlg4.applied.connect(mw4._apply_settings_from_dialog)
dlg4.hotkey_edits["palette.open"].setKeySequence(QKeySequence())
dlg4._on_accept()
check("live: clearing the palette field disables Ctrl+K without a restart",
      mw4._palette_shortcut.key().toString() == "")

# A NEW window picks the same values up at startup (the round-trip through the file)
mw5 = new_window()
check("startup: a freshly built window picks up the live-saved values",
      action_sequences(mw5, "file.save") == [canon("Ctrl+Shift+Alt+S")]
      and action_sequences(mw5, "palette.open") == [""])

# ════════════════════════════════════════════════════════════
# 5. F12 multi-input: configurable, but installed ONLY in the mode (task 4)
# ════════════════════════════════════════════════════════════
print("== 5. multi-input (F12) ==")

clear_cfg()
hub = MI.get_hub()
hub.reset()
mw6 = new_window()
check("multi: the mode is off → the key is NOT installed (the default F12 goes to the shell)",
      action_sequences(mw6, "view.multi_input") == [""])
mw6._toggle_multi_input(True)
app.processEvents()
check("multi: the mode is on → the default F12 is installed",
      action_sequences(mw6, "view.multi_input") == ["F12"]
      and mw6.act_multi_input.shortcut() == QKeySequence("F12"))
mw6._toggle_multi_input(False)
app.processEvents()
check("multi: leaving the mode removes the key again (the v1.2.3/v1.2.4-fix rule)",
      action_sequences(mw6, "view.multi_input") == [""])

write_cfg({"hotkeys": {"view.multi_input": "Ctrl+M"}})
mw7 = new_window()
check("multi: a configured sequence is respected — still installed only in the mode",
      action_sequences(mw7, "view.multi_input") == [""])
mw7._toggle_multi_input(True)
app.processEvents()
check("multi: the configured Ctrl+M is installed in the mode",
      mw7.act_multi_input.shortcut() == QKeySequence("Ctrl+M"))
mw7._toggle_multi_input(False)
app.processEvents()
check("multi: the configured key is removed on exit from the mode",
      mw7.act_multi_input.shortcut() == QKeySequence())

write_cfg({"hotkeys": {"view.multi_input": ""}})
mw8 = new_window()
mw8._toggle_multi_input(True)
app.processEvents()
check("multi: a DISABLED configured sequence → the mode has no key, the menu item still works",
      mw8.act_multi_input.shortcut() == QKeySequence() and mw8.act_multi_input.isChecked())
mw8._toggle_multi_input(False)
app.processEvents()

# A live change of the multi-input sequence (the dialog's OK)
clear_cfg()
mw9 = new_window()
mw9._toggle_multi_input(True)
app.processEvents()
dlg5 = SettingsDialog(mw9)
dlg5.applied.connect(mw9._apply_settings_from_dialog)
dlg5.hotkey_edits["view.multi_input"].setKeySequence(QKeySequence("Ctrl+Shift+M"))
dlg5._on_accept()
check("multi: OK re-installs the sequence of the ACTIVE mode without a restart",
      mw9.act_multi_input.shortcut() == QKeySequence("Ctrl+Shift+M"))
mw9._toggle_multi_input(False)
app.processEvents()
check("multi: after the live change the mode still owns the key (off → no shortcut)",
      mw9.act_multi_input.shortcut() == QKeySequence())

# The terminal canvas's own keys are NOT registry actions (the scope boundary, task 5)
check("scope: the terminal canvas keys are NOT configurable (not in the registry)",
      not any(a in ids for a in ("terminal.f12", "terminal.ctrl_c", "terminal.arrows"))
      and not any("terminal" in a for a in ids))

hub.reset()

# ════════════════════════════════════════════════════════════
# 6. i18n parity + the release state (the pins of _common.py)
# ════════════════════════════════════════════════════════════
print("== 6. i18n & release ==")

hotkey_keys = ["settings.tab.hotkeys", "settings.hotkeys.action",
               "settings.hotkeys.sequence", "settings.hotkeys.disabled_hint",
               "settings.hotkeys.conflict",
               # v1.3.3.3 (task 4)
               "settings.hotkeys.reset", "settings.hotkeys.reset_done"]
missing = [k for k in hotkey_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh", "de"))]
check("i18n: the hotkey-tab keys are present and non-empty in en/ru/zh/de",
      not missing, str(missing))
check_i18n_parity(langs)
check_release_state(ROOT)

clear_cfg()
finish()
