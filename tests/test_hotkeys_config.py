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

Run: python tests/test_hotkeys_config.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import re
import sys

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

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

# The v1.3.1.1 shortcuts — the contract of task 1 (canonical PortableText: "Delete" is "Del").
EXPECTED_DEFAULTS = {
    "file.new": "Ctrl+N", "file.open": "Ctrl+O", "file.save": "Ctrl+S",
    "edit.undo": "Ctrl+Z", "edit.redo": "Ctrl+Shift+Z",
    "edit.add_server": "Ctrl+Shift+A", "edit.add_group": "Ctrl+Shift+G",
    "edit.add_connection": "Ctrl+Shift+C", "edit.properties": "Ctrl+I",
    "edit.duplicate": "Ctrl+D", "edit.delete": "Del",
    "node.ssh_connect": "Ctrl+Return", "node.edit_server": "Ctrl+E",
    "node.add_note": "Ctrl+Shift+N",
    "view.fit_map": "Ctrl+Shift+F", "view.find_on_map": "Ctrl+F",
    "palette.open": "Ctrl+K", "view.multi_input": "F12",
}


def read_cfg():
    if not os.path.isfile(CFG_PATH):
        return {}
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_cfg(d):
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


def clear_cfg():
    try:
        os.remove(CFG_PATH)
    except OSError:
        pass


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


# ════════════════════════════════════════════════════════════
# 1. The registry: completeness, labels, no orphans (task 1)
# ════════════════════════════════════════════════════════════
print("== 1. the action registry ==")

ids = HR.action_ids()
check("registry: the 18 actions of the v1.3.1.1 hotkey set",
      set(ids) == set(EXPECTED_DEFAULTS), str(sorted(set(ids) ^ set(EXPECTED_DEFAULTS))))
check("registry: the defaults are exactly the v1.3.1.1 sequences",
      {a: HR.default_sequence(a) for a in ids} == EXPECTED_DEFAULTS,
      str({a: HR.default_sequence(a) for a in ids}))
check("registry: 'view.multi_input' is the only dynamic action",
      [a for a in ids if HR.is_dynamic(a)] == ["view.multi_input"])
check("registry: redo carries the legacy Ctrl+Y alias",
      HR.alt_sequences("edit.redo") == ("Ctrl+Y",)
      and HR.sequences_for("edit.redo", "Ctrl+Shift+Z") == ["Ctrl+Shift+Z", "Ctrl+Y"])
check("registry: a custom sequence drops the legacy alias (and non-defaults get none)",
      HR.sequences_for("edit.redo", "Ctrl+Alt+Z") == ["Ctrl+Alt+Z"]
      and HR.sequences_for("file.save", "Ctrl+Alt+S") == ["Ctrl+Alt+S"])

langs = load_i18n_langs(ROOT)
label_keys = {a: HR.action_label_key(a) for a in ids}
missing_labels = [(a, k) for a, k in label_keys.items()
                  if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("registry: every action label is an existing i18n key (en/ru/zh)", not missing_labels,
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
check("window: 18 registry actions are bound to real targets",
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
check("window: undo/redo — both targets (the toolbar button + the Edit menu item) follow the map",
      action_sequences(mw, "edit.undo") == ["Ctrl+Z", "Ctrl+Z"]
      and action_sequences(mw, "edit.redo") == ["Ctrl+Shift+Z", "Ctrl+Y"] * 2)

# The literal sequences must be gone from the UI modules (the registry is the only source).
src_literals = []
for name in ("main_window.py", "main_window_ssh.py", "map_search_bar.py", "settings_dialog.py"):
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

startup = mw._hotkey_map
check("load: an empty config yields the registry defaults",
      startup == EXPECTED_DEFAULTS, str(startup))

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
      "nope.id" not in effective and set(effective) == set(EXPECTED_DEFAULTS))
write_cfg({"hotkeys": "broken-not-a-dict"})
check("load: a non-dict 'hotkeys' value yields the defaults",
      HR.configured_hotkeys() == EXPECTED_DEFAULTS)

clear_cfg()
check("save: save_hotkeys() writes the 18 registry ids and returns True",
      HR.save_hotkeys({"file.save": "Ctrl+Alt+S"}) and
      set(read_cfg()["hotkeys"]) == set(EXPECTED_DEFAULTS))
check("save: normalized values (a broken mapping value is stored as the default)",
      read_cfg()["hotkeys"]["file.save"] == "Ctrl+Alt+S"
      and HR.save_hotkeys({"file.open": 42}) and read_cfg()["hotkeys"]["file.open"] == "Ctrl+O")
write_cfg({"language": "ru", "terminal_palette": "nord"})
HR.save_hotkeys({"file.save": "Ctrl+Alt+S"})
cfg = read_cfg()
check("save: the merge keeps the foreign config keys (language / terminal_palette)",
      cfg.get("language") == "ru" and cfg.get("terminal_palette") == "nord"
      and cfg["hotkeys"]["file.save"] == "Ctrl+Alt+S", str(sorted(cfg)))
check("save: the file stays valid JSON with the 'hotkeys' key",
      isinstance(read_cfg().get("hotkeys"), dict))

# ════════════════════════════════════════════════════════════
# 3. The "Hotkeys" tab of the settings dialog (task 2)
# ════════════════════════════════════════════════════════════
print("== 3. the settings dialog ==")

clear_cfg()
dlg = SettingsDialog(None)
check("dialog: 7 tabs with 'Hotkeys' between 'Map' and 'Language'",
      dlg.tabs.count() == 7
      and dlg.tabs.tabText(4) == t("settings.tab.map")
      and dlg.tabs.tabText(5) == t("settings.tab.hotkeys")
      and dlg.tabs.tabText(6) == t("settings.tab.language"),
      str([dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]))
check("dialog: one row per registry action, in the declaration order",
      dlg.hotkeys_table.rowCount() == len(ids)
      and [dlg.hotkeys_table.item(r, 0).text() for r in range(len(ids))]
      == [t(HR.action_label_key(a)) for a in ids])
check("dialog: the column headers [action | hotkey]",
      [dlg.hotkeys_table.horizontalHeaderItem(i).text() for i in (0, 1)]
      == [t("settings.hotkeys.action"), t("settings.hotkeys.sequence")])
check("dialog: a QKeySequenceEdit per row, prefilled with the effective sequence",
      all(isinstance(dlg.hotkeys_table.cellWidget(r, 1), QKeySequenceEdit)
          for r in range(len(ids)))
      and dlg.hotkey_edits["file.save"].keySequence().toString() == "Ctrl+S"
      and len(dlg.hotkey_edits) == len(ids))
check("dialog: the 'disable' hint is shown",
      dlg._lbl_hotkeys_disabled_hint.text() == t("settings.hotkeys.disabled_hint")
      and bool(dlg._lbl_hotkeys_disabled_hint.text()))
check("dialog: no conflict on the defaults (no warning, no mark)",
      dlg._lbl_hotkeys_conflict.text() == ""
      and not any("\u26a0" in dlg.hotkeys_table.item(r, 0).text() for r in range(len(ids))))

# A conflict: the same sequence on two rows → BOTH marked + the warning; saving still possible
dlg.hotkey_edits["edit.duplicate"].setKeySequence(QKeySequence("Ctrl+N"))
dlg._refresh_hotkey_conflicts()
conflict_ids = HR.find_conflicts(dlg.hotkey_sequences())
check("dialog: two actions with the same sequence are both detected as a conflict",
      conflict_ids == {"file.new", "edit.duplicate"}, str(conflict_ids))
check("dialog: both conflicting rows are marked, the others are not",
      "\u26a0" in dlg.hotkeys_table.item(ids.index("file.new"), 0).text()
      and "\u26a0" in dlg.hotkeys_table.item(ids.index("edit.duplicate"), 0).text()
      and not any("\u26a0" in dlg.hotkeys_table.item(ids.index(a), 0).text()
                  for a in ("file.save", "file.open")))
check("dialog: the conflict warning appears",
      dlg._lbl_hotkeys_conflict.text() == t("settings.hotkeys.conflict"))
collected = dlg.collect()
check("dialog: saving is still possible — collect() carries the conflicting values",
      collected["hotkeys"]["file.new"] == "Ctrl+N"
      and collected["hotkeys"]["edit.duplicate"] == "Ctrl+N")
check("dialog: collect() has exactly 20 config.json keys (v1.2.2: 19 + hotkeys)",
      len(collected) == 20 and "hotkeys" in collected, str(sorted(collected)))

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

# A prefill from the config (a saved value shows up in the table)
write_cfg({"hotkeys": {"file.save": "Ctrl+Alt+S"}})
dlg2 = SettingsDialog(None)
check("dialog: prefilled from ~/.sshmap/config.json",
      dlg2.hotkey_edits["file.save"].keySequence().toString() == "Ctrl+Alt+S"
      and dlg2.hotkey_edits["file.open"].keySequence().toString() == "Ctrl+O")

# The i18n of the dialog's own strings (a language switch inside the open dialog)
tab_titles = [dlg2.tabs.tabText(i) for i in range(7)]
i18n.set_language("ru")
dlg2.retranslate()
check("dialog: retranslate() updates the tab, the headers and the row names",
      dlg2.tabs.tabText(5) == i18n.t("settings.tab.hotkeys")
      and dlg2.tabs.tabText(5) != tab_titles[5]
      and dlg2.hotkeys_table.horizontalHeaderItem(0).text() == i18n.t("settings.hotkeys.action")
      and dlg2.hotkeys_table.item(0, 0).text() == i18n.t("file.new_project"))
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
      and action_sequences(mw4, "edit.redo") == ["Ctrl+Alt+R", "Ctrl+Alt+R"],
      str(action_sequences(mw4, "file.save")))
check("live: the QShortcut (the command palette) follows the table too",
      action_sequences(mw4, "palette.open") == ["Ctrl+Shift+K"]
      and mw4._palette_shortcut.key().toString() == "Ctrl+Shift+K")
check("live: the new values are persisted in config.json",
      read_cfg()["hotkeys"]["file.save"] == canon("Ctrl+Shift+Alt+S")
      and read_cfg()["hotkeys"]["edit.redo"] == "Ctrl+Alt+R"
      and read_cfg()["hotkeys"]["palette.open"] == "Ctrl+Shift+K")

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
               "settings.hotkeys.conflict"]
missing = [k for k in hotkey_keys
           if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("i18n: the 5 new v1.3.2 keys are present and non-empty in en/ru/zh",
      not missing, str(missing))
check_i18n_parity(langs)
check_release_state(ROOT)

clear_cfg()
finish()
