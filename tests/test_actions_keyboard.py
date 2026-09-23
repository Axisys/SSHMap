# -*- coding: utf-8 -*-
"""v1.3.3.3 — The action registry, completed: keyboard, on-demand operations, About.

ROADMAP v1.3.3.3 (the release's topical test):
  #1 `file.save_as` gets a home in the registry (the call site + "default": "Ctrl+Shift+S");
  #2 zoom becomes a first-class action — `view.reset_zoom` (Ctrl+0) + the NEW
     `view.zoom_in` / `view.zoom_out` (Ctrl+= / Ctrl+-), real View-menu items with two new
     vector icons (ui/icons.py — the project draws them) and a step API on MapView;
  #3 the REMAINING global actions enter the registry with an EMPTY default (assignable,
     no behaviour change) — the extended "no orphans" audit requires EVERY global action
     of the menus/sidebar/palette to be registered;
  #4 "Reset to defaults" in the "Hotkeys" tab — the registry defaults through the existing
     merge-write, foreign config keys survive, the button is idempotent;
  #5 "Check statuses now" — one call into the existing StatusChecker.start_round() path
     for the selection, from the map/sidebar context menus and the Edit menu;
  #6 the "About" window — version.py, the license, the two ~/.sshmap paths, a button that
     opens the config folder in the OS file manager and the hotkey cheat-sheet generated
     FROM the registry (the live values, never a hardcoded list).

The audit is split in two halves on purpose:
  * STRUCTURAL — every `_add_menu_action(..., action_id)` call site in ui/main_window.py
    must name a registry id (a source scan, so a menu item added without a registry entry
    fails here instead of silently living outside the keyboard);
  * BEHAVIOURAL — the sequences really fire on a LIVE window (QTest.keySequence, the same
    Qt shortcut machinery a user's keystroke goes through), the reset button restores and
    persists, the manual status round starts exactly one round off the GUI thread, and the
    About box renders the live version + the registry cheat-sheet.

Run: python tests/test_actions_keyboard.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import re
import sys
import inspect  # v1.3.3.3: the audit reads the live signature / the worker source

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, read_cfg, write_cfg, clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtGui import QAction, QKeySequence, QShortcut  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
from i18n import t  # noqa: E402
from _common import load_i18n_langs as _load_langs  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.about_dialog as AD  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402

langs = _load_langs(ROOT)   # the discovered language files (en/ru/zh/de today)
CFG_PATH = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")

NEW_DEFAULT_ACTIONS = {
    "file.save_as": "Ctrl+Shift+S",
    "view.reset_zoom": "Ctrl+0",
    "view.zoom_in": "Ctrl+=",
    "view.zoom_out": "Ctrl+-",
}

# v1.3.3.3 (task 3): the global actions that were OUTSIDE the registry and now carry an
# EMPTY default — assignable, no hotkey out of the box. The list is the ROADMAP's
# enumeration + `view.center_map` (found by the v1.3.3 third-party review) + the About
# item of task 6 + node.check_status of task 5.
EMPTY_DEFAULT_ACTIONS = {
    "node.check_status",
    "view.center_map", "view.collapse_all", "view.expand_all",
    "view.set_background", "view.remove_background",
    "edit.connect_selected", "edit.delete_selected",
    "file.import_servers", "file.export_png", "file.export_pdf", "file.export_drawio",
    "file.export_svg",
    "file.backups", "file.restore_autosave", "file.exit",
    "profile.manage", "help.open_logs", "help.about",
    # v1.4rc1 (the plugin foundation): the "Reload plugins" menu item of the new menu.
    "plugins.reload",
    # v1.4rc3 (the plugin foundation): "Run on selected servers" — the `run_on_nodes`
    # hook of every loaded plugin for the current selection.
    "plugins.run_on_nodes",
    # v1.4.1: the second import path — "Import from SSH Config…" (File menu).
    "file.import_ssh_config",
    # v1.4.2: the minimap panel — a checkable View item (ROADMAP task 2).
    "view.toggle_minimap",
    # v1.4.5: the legend panel — a checkable View item + its toolbar mirror (task 4).
    "view.toggle_legend",
    # v1.5rc3: "Open the example map" (the Help item of the demo map — the empty state's
    # second button calls the same window method). No key out of the box.
    "help.example",
}

# v1.3.3.3 i18n additions (13 keys: 477 → 490).
NEW_I18N_KEYS = [
    "view.zoom_in", "view.zoom_out",
    "settings.hotkeys.reset", "settings.hotkeys.reset_done",
    "ctx.check_status", "status.check_now",
    "about.open", "about.title", "about.license", "about.config_path",
    "about.logs_path", "about.hotkeys", "about.open_config_dir",
]
def new_window():
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.show()
    app.processEvents()
    return w


def fire(window, sequence):
    """A REAL keystroke through Qt's shortcut machinery (the user's own path)."""
    QTest.keySequence(window, QKeySequence(sequence))
    app.processEvents()


def menu_action(window, action_key):
    """The QAction of a registered menu item (via _menu_i18n — never action.menu())."""
    items = [w for w, k in window._menu_i18n if k == action_key]
    return items[-1] if items else None


class _FakeChecker:
    """The on-demand status path without a network or a thread."""

    def __init__(self, accept=True):
        self.rounds = []
        self.accept = accept

    def start_round(self, server_ids=None):
        self.rounds.append(list(server_ids) if server_ids is not None else None)
        return self.accept

    def shutdown(self):
        """MainWindow.destroyed connects self._status_checker.shutdown() — the double
        must survive the teardown path like the real StatusChecker does."""


# ════════════════════════════════════════════════════════════
# 1. The registry is complete (task 1–3): the structural "no orphans" audit
# ════════════════════════════════════════════════════════════
print("== 1. the registry is complete ==")

ids = HR.action_ids()
check("registry: 49 actions — the v1.3.2 set + Save As + the zoom family + the empty defaults "
      "(v1.3.3.7: +file.export_svg; v1.4rc1: +plugins.reload; v1.4rc3: +plugins.run_on_nodes; "
      "v1.4.1: +file.import_ssh_config; v1.4.2: +view.toggle_minimap; "
      "v1.4.5: +view.toggle_legend; v1.5rc3: +help.cheatsheet (F1) and +help.example; "
      "v1.5rc4: +view.focus_map — the ONE new action of that release)",
      len(ids) == 49 and len(set(ids)) == 49, str(len(ids)))
check("registry: the 4 new SEQUENCED actions carry exactly the promised defaults",
      {a: HR.default_sequence(a) for a in NEW_DEFAULT_ACTIONS} == NEW_DEFAULT_ACTIONS,
      str({a: HR.default_sequence(a) for a in NEW_DEFAULT_ACTIONS}))
check("registry: the promoted global actions ARE registered (task 3; v1.3.3.7: +file.export_svg)",
      EMPTY_DEFAULT_ACTIONS <= set(ids),
      str(sorted(EMPTY_DEFAULT_ACTIONS - set(ids))))
check("registry: each of them has an EMPTY default (no hotkey, so no behaviour change)",
      all(HR.default_sequence(a) == "" for a in EMPTY_DEFAULT_ACTIONS),
      str({a: HR.default_sequence(a) for a in sorted(EMPTY_DEFAULT_ACTIONS)}))
check("registry: no duplicate default sequence among the non-empty ones",
      len([s for s in HR.default_hotkeys().values() if s])
      == len(set(s for s in HR.default_hotkeys().values() if s)),
      str(sorted(s for s in HR.default_hotkeys().values() if s)))

# STRUCTURAL HALF of the audit — THREE passes:
#  (a) the parameter order of _add_menu_action() is read from the LIVE signature (no
#      literal positional assumption in this test);
#  (b) a source scan: the i18n keys of the call sites are exactly the menu keys the
#      application uses, and the action_id position carries a registry id;
#  (c) the runtime record of what the constructor ACTUALLY passed (the wrapper below) —
#      the authoritative "no global action lives outside the registry".
_add_params = list(inspect.signature(MW.MainWindow._add_menu_action).parameters)[2:]  # self, menu
_i18n_pos, _id_pos = _add_params.index("key"), _add_params.index("action_id")
with open(os.path.join(ROOT, "ui", "main_window.py"), encoding="utf-8") as f:
    _src = f.read()
_calls = [m.group(0) for m in re.finditer(r"_add_menu_action\([^()]*\)", _src)]
check("source audit: the menubar is built through _add_menu_action",
      len(_calls) >= 25, f"{len(_calls)} call sites")
check("source audit: the signature keeps the documented (menu, key, slot, action_id) order",
      (_add_params[_i18n_pos], _add_params[_id_pos]) == ("key", "action_id"), str(_add_params))

_lit_keys: set = set()
_lit_ids: set = set()
for _call in _calls:
    _lit = re.findall(r'"([a-z_]+\.[a-z_]+)"', _call)
    if _lit:
        _lit_keys.add(_lit[0])       # the first id-looking literal IS the i18n key
    if len(_lit) >= 2:
        _lit_ids.add(_lit[-1])       # the last one is the action_id (an icon name is not id-like)
check("source audit: the key position carries an i18n key that really exists",
      _lit_keys <= set(langs["en"]), str(sorted(_lit_keys - set(langs["en"]))))
check("source audit: every id-looking literal in the action_id position is registered",
      _lit_ids <= set(ids), str(sorted(_lit_ids - set(ids))))
check("source audit: the named ids cover every menu family (file/edit/view/profile/help)",
      {"file.save_as", "view.zoom_in", "view.zoom_out", "view.reset_zoom",
       "edit.connect_selected", "profile.manage", "help.open_logs", "help.about"} <= _lit_ids,
      str(sorted(_lit_ids)))

# (c) Runtime: wrap _add_menu_action BEFORE the window is built and record every call.
#      The four ids below are created MANUALLY (never through _add_menu_action) and are
#      therefore absent from the record: the two dynamic/multi-input ones (multi_input is
#      installed by the mode, palette.open is a QShortcut) and, since v1.4.2,
#      view.toggle_minimap — a CHECKABLE item, which must be connected to toggled(bool)
#      (the v1.2.4-fix pitfall: the auto-connection of addAction(text, slot) carries no
#      state), so it is built by hand and registered through _register_hotkey_target.
#      v1.4.5 adds view.toggle_legend to the same family (the checkable View item of the
#      legend panel, mirrored by a toolbar button).
_recorded = []
_orig_add_menu_action = MW.MainWindow._add_menu_action


def _recording_add_menu_action(self, menu, key, slot, action_id="", icon_name=""):
    _recorded.append((key, action_id))
    return _orig_add_menu_action(self, menu, key, slot, action_id, icon_name)


MW.MainWindow._add_menu_action = _recording_add_menu_action
try:
    clear_cfg()
    mw = new_window()
finally:
    MW.MainWindow._add_menu_action = _orig_add_menu_action

_duplicated = [k for k, _a in _recorded if k not in ("edit.undo", "edit.redo")
               and [x for x, _y in _recorded].count(k) > 1]
check("runtime audit: no menu item is added twice (the undo/redo pair excluded)",
      not _duplicated, str(_duplicated))
_no_id = [k for k, a in _recorded if not a and k != "settings.open"]
check("runtime audit: EVERY global action of the menubar carries an action_id (no orphans)",
      not _no_id, str(_no_id))
_bad_ids = sorted({a for _k, a in _recorded if a} - set(ids))
check("runtime audit: every action_id the menu passes is a registry action", not _bad_ids,
      str(_bad_ids))
check("runtime audit: the menubar covers the whole registry (every action has a menu item)",
      set(ids) <= {a for _k, a in _recorded}
      | {"view.multi_input", "palette.open", "view.toggle_minimap", "view.toggle_legend"},
      str(sorted(set(ids) - {a for _k, a in _recorded}
                 - {"view.multi_input", "palette.open", "view.toggle_minimap",
                    "view.toggle_legend"})))

check("window: EVERY registry action is bound to a real object (no unregistered id)",
      set(mw._hotkey_targets) == set(ids) and all(mw._hotkey_targets.values()),
      str(sorted(set(ids) ^ set(mw._hotkey_targets))))

# BEHAVIOURAL HALF: no orphan shortcut — every sequence present anywhere in the window
# belongs to the registry, and no sequence is installed twice (a duplicate makes Qt
# report "Ambiguous shortcut overload" and fire NEITHER — the toolbar-mirror regression).
_registered = set()
for _aid in ids:
    _registered.update(HR.sequences_for(_aid, mw._hotkey_map.get(_aid)))
_orphans = sorted({a.shortcut().toString() for a in mw.findChildren(QAction)
                   if a.shortcut().toString() and a.shortcut().toString() not in _registered}
                  | {sc.key().toString() for sc in mw.findChildren(QShortcut)
                     if sc.key().toString() and sc.key().toString() not in _registered})
check("window: no orphan shortcut anywhere in the window", not _orphans, str(_orphans))

_holder = {}
for _act in mw.findChildren(QAction):
    _seq = _act.shortcut().toString()
    if _seq:
        _holder.setdefault(_seq, []).append(_act)
_dups = sorted(s for s, acts in _holder.items()
               if len([x for x in acts if x.isEnabled()]) > 1)
check("window: no sequence is installed twice (the 'Ambiguous shortcut overload' guard)",
      not _dups, str(_dups))

# The source audit for leftover literal sequences (the v1.3.2 rule, extended to the new
# module) — the registry stays the single source of truth.
_src_literals = []
for _name in ("main_window.py", "main_window_ssh.py", "map_search_bar.py",
              "settings_dialog.py", "about_dialog.py"):
    with open(os.path.join(ROOT, "ui", _name), encoding="utf-8") as f:
        _mod = f.read()
    for _m in re.finditer(r'setShortcut(?:s)?\(\s*(\[[^\]]*\]|"[^"]*"|\'[^\']*\')', _mod):
        _src_literals.append((_name, _m.group(0)))
check("source: no literal setShortcut(...) sequences left in the UI modules",
      not _src_literals, str(_src_literals))

# ════════════════════════════════════════════════════════════
# 2. The shortcuts really FIRE on a live window (task 1–2)
# ════════════════════════════════════════════════════════════
print("== 2. the new shortcuts fire (a live window) ==")

check("window: the installed sequences are exactly the registry defaults",
      all(_seq == HR.default_sequence(_aid)
          for _aid in NEW_DEFAULT_ACTIONS
          for _seq in [a.shortcut().toString()
                       for a in mw._hotkey_targets[_aid] if isinstance(a, QAction)]),
      str({a: [x.shortcut().toString() for x in mw._hotkey_targets[a]] for a in NEW_DEFAULT_ACTIONS}))

# Ctrl+Shift+S → "Save As…"
_saved = []
_orig_save_as = mw._save_project_as
mw._save_project_as = lambda *a, **k: _saved.append(1)
try:
    fire(mw, "Ctrl+Shift+S")
finally:
    mw._save_project_as = _orig_save_as
check("Ctrl+Shift+S really fires 'Save As...' (task 1)", _saved == [1], str(_saved))

# Ctrl+= / Ctrl+- / Ctrl+0 → the view scale
mw.view.reset_zoom()
_z0 = mw.view.zoom
fire(mw, "Ctrl+=")
_z1 = mw.view.zoom
check("Ctrl+= really zooms IN by the MapView step",
      abs(_z0 - 1.0) < 1e-9 and abs(_z1 - _z0 * mw.view.ZOOM_STEP) < 1e-9 and _z1 > _z0,
      f"{_z0} -> {_z1}")
fire(mw, "Ctrl+=")
_z2 = mw.view.zoom
check("Ctrl+= is repeatable (a second press steps again)",
      abs(_z2 - _z1 * mw.view.ZOOM_STEP) < 1e-9, f"{_z1} -> {_z2}")
fire(mw, "Ctrl+-")
check("Ctrl+- really zooms OUT by the same step",
      abs(mw.view.zoom - _z1) < 1e-9, f"{_z2} -> {mw.view.zoom}")
fire(mw, "Ctrl+0")
check("Ctrl+0 really resets the view scale to exactly 1.0",
      abs(mw.view.zoom - 1.0) < 1e-9 and abs(mw.view.transform().m11() - 1.0) < 1e-9,
      str(mw.view.zoom))

# The view scale and the reported zoom stay in sync through the whole family, and the
# step anchors on the CENTRE of the viewport (the scene point under the centre stays put).
from PySide6.QtCore import QPointF  # noqa: E402

_centre_before = mw.view.mapToScene(mw.view.viewport().rect().center())
mw.view.reset_zoom()
fire(mw, "Ctrl+=")
_centre_after = mw.view.mapToScene(mw.view.viewport().rect().center())
_drift = max(abs(_centre_after.x() - _centre_before.x()),
             abs(_centre_after.y() - _centre_before.y()))
check("zoom: the step is anchored on the view centre (no drift of the content)",
      _drift <= 1.0, f"drift={_drift:.3f} scene units")
check("zoom: the MapView step API is public and next to reset_zoom/set_zoom_and_center",
      all(callable(getattr(mw.view, _m)) for _m in ("reset_zoom", "zoom_in", "zoom_out",
                                                    "set_zoom_and_center", "_zoom_by")))

# The two new icons exist, are drawn and are distinct (ui/icons.py — no emoji, no files)
from ui.icons import get_icon  # noqa: E402

_ink = {}
for _name in ("zoom_in", "zoom_out"):
    _icon = get_icon(_name)
    _img = _icon.pixmap(20, 20).toImage()
    _ink[_name] = sum(1 for y in range(_img.height()) for x in range(_img.width())
                      if _img.pixelColor(x, y).alpha() > 0)
    check(f"icon: '{_name}' is a drawn vector glyph (a transparent 20×20 canvas)",
          not _icon.isNull() and _icon.pixmap(20, 20).size().width() == 20 and _ink[_name] > 25,
          f"ink={_ink[_name]}")
check("icon: the zoom pair is two DIFFERENT glyphs (the +/- sign is really drawn)",
      get_icon("zoom_in").pixmap(20, 20).toImage()
      != get_icon("zoom_out").pixmap(20, 20).toImage())
check("menu: the two zoom items are real View-menu items carrying the new icons",
      menu_action(mw, "view.zoom_in") is not None
      and menu_action(mw, "view.zoom_out") is not None
      and not menu_action(mw, "view.zoom_in").icon().isNull()
      and not menu_action(mw, "view.zoom_out").icon().isNull())

# ════════════════════════════════════════════════════════════
# 3. An action with an EMPTY default: in the menu, in the tab, and a no-op until assigned
# ════════════════════════════════════════════════════════════
print("== 3. the empty default (task 3/4) ==")

check("empty default: the action is present in the menu and ENABLED (usable by mouse)",
      menu_action(mw, "file.import_servers") is not None
      and menu_action(mw, "file.import_servers").isEnabled()
      and menu_action(mw, "file.import_servers").shortcut().toString() == "",
      str(menu_action(mw, "file.import_servers")))
check("empty default: the object is still a registered hotkey target (a sequence can land)",
      len(mw._hotkey_targets["file.export_png"]) == 1
      and mw._hotkey_targets["file.export_png"][0].shortcut().toString() == "")

dlg = SettingsDialog(None)
check("empty default: the action appears as a row in the Hotkeys tab with an EMPTY field",
      dlg.hotkeys_table.rowCount() == len(ids) + len(dlg.hotkey_family_rows())
      and dlg.hotkey_edits["file.export_png"].keySequence().toString() == ""
      and dlg.hotkey_edits["help.about"].keySequence().toString() == ""
      and dlg.hotkey_edits["view.center_map"].keySequence().toString() == "")

# The toolbar mirror has no sequence of its own (a duplicate makes Qt fire neither).
_toolbar_dups = [a.text() for a in mw.findChildren(QAction)
                 if a.shortcut().toString()
                 and a in [x for x in mw._hotkey_targets.get("file.save", [])]]
check("toolbar: the toolbar mirror of a menu action carries no sequence of its own",
      len(mw._hotkey_targets.get("file.save", [])) == 1,
      str([a.text() for a in mw._hotkey_targets.get("file.save", [])]))

# Assign a sequence to an empty-default action → the keyboard reaches it; clear → it does not
write_cfg({"hotkeys": {"file.import_servers": "Ctrl+Alt+I"}})
mw2 = new_window()
check("assigned: an empty-default action accepts a user sequence",
      mw2._hotkey_targets["file.import_servers"][0].shortcut().toString() == "Ctrl+Alt+I",
      str(mw2._hotkey_targets["file.import_servers"][0].shortcut().toString()))
_fired = []
_orig_import = mw2._import_servers_from_txt
mw2._import_servers_from_txt = lambda *a, **k: _fired.append(1)
try:
    fire(mw2, "Ctrl+Alt+I")
finally:
    mw2._import_servers_from_txt = _orig_import
check("assigned: the assigned sequence really fires the action", _fired == [1], str(_fired))
check("empty default: without the assignment the SAME action cannot be triggered by the keyboard",
      HR.default_sequence("file.exit") == "" and HR.sequences_for("file.exit", "") == [])

# ════════════════════════════════════════════════════════════
# 4. "Reset to defaults" (task 4)
# ════════════════════════════════════════════════════════════
print("== 4. the reset button ==")

clear_cfg()
write_cfg({"language": "ru", "terminal_palette": "nord",
           "hotkeys": {"file.save": "Ctrl+Alt+S", "view.collapse_all": "Ctrl+Alt+C"}})
mw3 = new_window()
dlg3 = SettingsDialog(mw3)
dlg3.applied.connect(mw3._apply_settings_from_dialog)
check("reset: precondition — the table starts from the CUSTOM values",
      dlg3.hotkey_edits["file.save"].keySequence().toString() == "Ctrl+Alt+S"
      and dlg3.hotkey_edits["view.collapse_all"].keySequence().toString() == "Ctrl+Alt+C")

dlg3.reset_hotkeys_btn.click()
app.processEvents()
_defaults = HR.default_hotkeys()
check("reset: EVERY row is back to the registry default",
      all(dlg3.hotkey_edits[a].keySequence().toString() == _defaults[a] for a in ids),
      str({a: dlg3.hotkey_edits[a].keySequence().toString()
           for a in ("file.save", "view.collapse_all", "view.zoom_in")}))
check("reset: the user's own assignment on an empty-default action is cleared too",
      dlg3.hotkey_edits["view.collapse_all"].keySequence().toString() == "")
check("reset: the conflicts are re-evaluated (no warning on the defaults)",
      dlg3._lbl_hotkeys_conflict.text() == t("settings.hotkeys.reset_done"),
      repr(dlg3._lbl_hotkeys_conflict.text()))
check("reset: the LIVE window follows without a restart (the applied signal)",
      mw3._hotkey_targets["file.save"][0].shortcut().toString() == "Ctrl+S"
      and mw3._hotkey_targets["view.collapse_all"][0].shortcut().toString() == "",
      str(mw3._hotkey_targets["file.save"][0].shortcut().toString()))

_saved_cfg = read_cfg({})
check("reset: the defaults are written through the existing merge-write",
      _saved_cfg.get("hotkeys") == _defaults, str(sorted(_saved_cfg.get("hotkeys", {})))[:120])
check("reset: the FOREIGN keys of config.json survive (language / terminal_palette)",
      _saved_cfg.get("language") == "ru" and _saved_cfg.get("terminal_palette") == "nord",
      str(sorted(_saved_cfg)))
check("reset: an unknown id in the stored config is still ignored (the v1.3.2 rule)",
      "nope.id" not in _saved_cfg.get("hotkeys", {}) and set(_saved_cfg["hotkeys"]) == set(ids))

# Idempotent: a second click writes the very same mapping
_first = json.dumps(read_cfg({}), sort_keys=True)
dlg3.reset_hotkeys_btn.click()
app.processEvents()
check("reset: the button is idempotent (a second click changes nothing)",
      json.dumps(read_cfg({}), sort_keys=True) == _first
      and all(dlg3.hotkey_edits[a].keySequence().toString() == _defaults[a] for a in ids))
_dlg_fresh = SettingsDialog(None)   # kept in a variable: a temporary would be GC'd mid-check
check("reset: a fresh dialog sees the defaults (the round-trip through the file)",
      all(_dlg_fresh.hotkey_edits[a].keySequence().toString() == _defaults[a]
          for a in ("file.save", "view.collapse_all", "view.zoom_in")))

# A conflict is CLEARED by the reset (the custom value that collided is gone)
clear_cfg()
write_cfg({"hotkeys": {"file.open": "Ctrl+N"}})   # collides with the file.new default
_dlg_conflict = SettingsDialog(None)
check("reset: precondition — a stored conflict is visible in the table",
      t("settings.hotkeys.conflict") == _dlg_conflict._lbl_hotkeys_conflict.text(),
      repr(_dlg_conflict._lbl_hotkeys_conflict.text()))
_dlg_conflict.reset_hotkeys_btn.click()
app.processEvents()
check("reset: the reset clears the conflict as well",
      _dlg_conflict._lbl_hotkeys_conflict.text() == t("settings.hotkeys.reset_done")
      and HR.find_conflicts(_dlg_conflict.hotkey_sequences()) == set())

# ════════════════════════════════════════════════════════════
# 5. "Check statuses now" (task 5)
# ════════════════════════════════════════════════════════════
print("== 5. Check statuses now ==")

from models.server import ServerData  # noqa: E402
import ui.sidebar as SB  # noqa: E402

clear_cfg()
mw4 = new_window()
_nodes = [mw4.scene.add_server(ServerData(id=f"act-{i}", alias=f"act-{i}",
                                          host=f"10.98.0.{i}", user="root"))
          for i in (1, 2, 3)]
mw4.scene.clearSelection()
app.processEvents()

_fake = _FakeChecker()
mw4._status_checker = _fake
_started = mw4._check_statuses_now(_nodes[0])
check("check now: the clicked node is probed when nothing is selected (exactly ONE round)",
      _started is True and len(_fake.rounds) == 1 and _fake.rounds[0] == ["act-1"],
      str(_fake.rounds))

_fake.rounds.clear()
_nodes[0].setSelected(True)
_nodes[1].setSelected(True)
app.processEvents()
mw4._check_statuses_now(_nodes[2])
check("check now: with a selection, exactly the SELECTED ids are probed",
      len(_fake.rounds) == 1 and sorted(_fake.rounds[0]) == ["act-1", "act-2"],
      str(_fake.rounds))
check("check now: the clicked node is ignored while a selection exists",
      "act-3" not in _fake.rounds[0], str(_fake.rounds))

from services.status_checker import StatusChecker as _SC  # noqa: E402

_src_round = inspect.getsource(_SC.start_round)
check("check now: start_round() only builds the target list and starts the worker QThread",
      "_ProbeThread(" in _src_round and "thread.start()" in _src_round
      and "probe_ssh(" not in _src_round and "socket" not in _src_round,
      f"thread={' _ProbeThread(' in _src_round} start={'thread.start()' in _src_round}")
_src_probe = inspect.getsource(inspect.getmodule(_SC))
check("check now: the probing itself lives in the QThread (_ProbeThread.run), never in start_round",
      "class _ProbeThread(QThread)" in _src_probe
      and "def run(self):" in _src_probe and "ThreadPoolExecutor" in _src_probe)

# A busy checker reports the truth (the interval/cancellation semantics are untouched)
_busy = _FakeChecker(accept=False)
mw4._status_checker = _busy
check("check now: 'already busy' is reported, not silently swallowed",
      mw4._check_statuses_now(_nodes[0]) is False and len(_busy.rounds) == 1)

# The action is reachable from all three places: the Edit menu, the map menu, the sidebar
check("check now: the Edit-menu item exists and is a registered hotkey target",
      menu_action(mw4, "ctx.check_status") in mw4._hotkey_targets.get("node.check_status", []))
_mw_src = open(os.path.join(ROOT, "graphics", "map_view.py"), encoding="utf-8").read()
check("check now: the map's node context menu carries the entry",
      'ctx.check_status' in _mw_src and "_check_statuses_now" in _mw_src)
check("check now: the sidebar context menu carries the entry",
      any(e is not None and e[0] == "check_status" for e in SB.CONTEXT_MENU_ITEMS)
      and "check_status" in mw4.sidebar._actions,
      str(SB.CONTEXT_MENU_ITEMS))
_sb_actions = {k: (lambda node, _k=k: None) for k in
               ("ssh", "external", "edit", "copy_ip", "copy_hostname", "ping",
                "collect_info", "check_status", "reveal", "delete")}
_sidebar = SB.SidebarPanel(translate_fn=i18n.t, actions=_sb_actions)
from PySide6.QtWidgets import QMenu  # noqa: E402

_menu = QMenu()
_sidebar.fill_context_menu(_menu, _nodes[0])
_labels = [a.text().replace("&", "") for a in _menu.actions()]
check("check now: the sidebar menu shows the translated 'Check statuses now' item",
      t("ctx.check_status") in _labels, str(_labels))

# The selection semantics of the status CHECKER itself (the subset round)
from services.status_checker import StatusChecker  # noqa: E402

chk = StatusChecker(parent=None)
chk.set_servers([("s1", "10.0.0.1", 22), ("s2", "10.0.0.2", 22), ("s3", "10.0.0.3", 22)])
check("start_round(ids): the subset is filtered from the stored targets, order preserved",
      chk._subset(["s3", "s1"]) == [("s1", "10.0.0.1", 22), ("s3", "10.0.0.3", 22)],
      str(chk._subset(["s3", "s1"])))
check("start_round(None): the whole stored target list (the periodic behaviour)",
      chk._subset() == [("s1", "10.0.0.1", 22), ("s2", "10.0.0.2", 22), ("s3", "10.0.0.3", 22)])
check("start_round([]): nothing to probe — no round is started",
      chk._subset([]) == [] and chk.start_round([]) is False)
check("start_round(unknown ids): still no round (an unknown id is skipped)",
      chk.start_round(["nope"]) is False)

# ════════════════════════════════════════════════════════════
# 6. The About window (task 6)
# ════════════════════════════════════════════════════════════
print("== 6. About ==")

from version import APP_NAME, APP_VERSION  # noqa: E402

about = AD.AboutDialog(None)
check("about: the title and the version come from version.py (the single source of truth)",
      about.windowTitle() == t("about.title")
      and about.title_label.text() == f"{APP_NAME} {APP_VERSION}"
      and APP_VERSION in about.title_label.text(),
      about.title_label.text())
check("about: the license line names the license",
      AD.LICENSE_NAME == "MIT" and t("about.license", license="MIT") == about.license_label.text(),
      about.license_label.text())
check("about: the two ~/.sshmap paths are shown (config.json + logs/)",
      about.config_value.text() == os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
      and about.logs_value.text() == os.path.join(os.path.expanduser("~"), ".sshmap", "logs"),
      f"{about.config_value.text()} | {about.logs_value.text()}")
check("about: the section labels are i18n keys of all four built-in languages",
      about._lbl_config.text() == t("about.config_path")
      and about._lbl_logs.text() == t("about.logs_path")
      and about._lbl_hotkeys.text() == t("about.hotkeys"))

# The cheat-sheet is generated FROM the registry — the LIVE values, never a hardcoded list
_sheet = about.cheatsheet_text()
check("about: the cheat-sheet is not empty and lists the sequenced actions",
      bool(_sheet.strip()) and "Ctrl+S" in _sheet and "Ctrl+Shift+S" in _sheet
      and "Ctrl+0" in _sheet and "Ctrl+=" in _sheet and "Ctrl+-" in _sheet,
      repr(_sheet[:200]))
check("about: every listed line comes from the registry (name + live sequence)",
      all(any(seq and seq in line for seq in HR.default_hotkeys().values())
          for line in _sheet.splitlines()),
      repr(_sheet[:200]))
check("about: actions with an EMPTY sequence are not listed (the sheet answers 'what can I press')",
      t("file.exit") not in _sheet and t("help.open_logs") not in _sheet
      and t("file.export_png") not in _sheet,
      repr(_sheet))
check("about: the number of listed actions equals the registry's non-empty sequences",
      len(_sheet.splitlines()) == len([s for s in HR.default_hotkeys().values() if s]),
      f"{len(_sheet.splitlines())} lines")

# …and it follows the LIVE configuration: a user rebind changes the sheet, not a literal
write_cfg({"hotkeys": {"file.save": "Ctrl+Alt+S", "file.export_png": "Ctrl+Alt+P"}})
about_live = AD.AboutDialog(None)
_sheet_live = about_live.cheatsheet_text()
check("about: the cheat-sheet shows the CONFIGURED sequence, not the registry default",
      "Ctrl+Alt+S" in _sheet_live and "Ctrl+Alt+P" in _sheet_live,
      repr([ln for ln in _sheet_live.splitlines() if "Ctrl+Alt" in ln]))
check("about: an assigned empty-default action appears in the sheet once bound",
      t("file.export_png") in _sheet_live)

# The cheat-sheet follows a language switch (the action NAMES are translated at call time)
i18n.set_language("ru")
about_live.retranslate()
_sheet_ru = about_live.cheatsheet_text()
check("about: retranslate() re-renders the cheat-sheet in the new language",
      t("file.save") in _sheet_ru and "Ctrl+Alt+S" in _sheet_ru
      and about_live._lbl_hotkeys.text() == t("about.hotkeys"),
      repr(_sheet_ru[:120]))
i18n.set_language("en")
about_live.retranslate()

# The config-folder button — a monkeypatched OS call, never the real file manager
_opened = []
_orig_open = AD.open_config_folder
AD.open_config_folder = lambda: (_opened.append(1), True)[1]
try:
    about.open_folder_btn.click()
    app.processEvents()
finally:
    AD.open_config_folder = _orig_open
check("about: the button opens the config folder (a monkeypatched OS call)",
      _opened == [1], str(_opened))
check("about: open_config_folder() targets ~/.sshmap and creates it on demand",
      AD.app_config_dir() == os.path.join(os.path.expanduser("~"), ".sshmap")
      and AD.app_config_path().endswith(os.path.join(".sshmap", "config.json"))
      and AD.app_logs_dir().endswith(os.path.join(".sshmap", "logs")))

# v1.5rc5 (N1): the POSIX branches pass an ARGUMENT LIST to subprocess.call — the path is
# expanduser("~")-derived, so the historical `os.system(f'xdg-open "{path}"')` form was
# command injection through a `"` or a `;` in the home directory.
_n1_calls = []
_orig_subprocess_call = AD.subprocess.call
_orig_platform = AD.sys.platform
AD.subprocess.call = lambda argv, *a, **kw: (_n1_calls.append(argv), 0)[1]
try:
    for _plat in ("darwin", "linux"):
        AD.sys.platform = _plat
        _n1_calls.clear()
        AD.open_config_folder()
        _argv = _n1_calls[0] if _n1_calls else None
        check(f"N1: the {_plat} opener passes a LIST argv (no shell, no interpolation)",
              isinstance(_argv, list) and len(_argv) == 2
              and _argv[1] == AD.app_config_dir()
              and _argv[0] == ("open" if _plat == "darwin" else "xdg-open"),
              f"argv={_argv!r}")
finally:
    AD.subprocess.call = _orig_subprocess_call
    AD.sys.platform = _orig_platform
with open(AD.__file__, encoding="utf-8") as _ad_src:
    _ad_text = _ad_src.read()
check("N1: no os.system(...) / shell=True call is left in the module (the argv form only)",
      "os.system(" not in _ad_text and "shell=True" not in _ad_text)

# A failure of the OS call must not take the window down
def _boom():
    raise OSError("no file manager")


AD.open_config_folder = _boom
try:
    about.open_folder_btn.click()
    app.processEvents()
    _survived = True
finally:
    AD.open_config_folder = _orig_open
check("about: a failing OS call is reported, never raised into the event loop", _survived)

check("about: the Help menu item exists and is registered (task 6)",
      menu_action(mw4, "about.open") is not None
      and mw4.act_about is menu_action(mw4, "about.open")
      and menu_action(mw4, "about.open") in mw4._hotkey_targets["help.about"])

# The window opens the dialog through the Help menu (the real entry point)
_opened_dialogs = []
_orig_exec = AD.AboutDialog.exec


def _fake_exec(self):
    _opened_dialogs.append(self)
    return 0


AD.AboutDialog.exec = _fake_exec
try:
    menu_action(mw4, "about.open").trigger()
    app.processEvents()
finally:
    AD.AboutDialog.exec = _orig_exec
check("about: the Help-menu click opens the About dialog", len(_opened_dialogs) == 1,
      str(len(_opened_dialogs)))

clear_cfg()

# ════════════════════════════════════════════════════════════
# 7. i18n keys + the release state (the pins of _common.py)
# ════════════════════════════════════════════════════════════
print("== 7. i18n & release ==")

_missing = [k for k in NEW_I18N_KEYS
            if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh", "de"))]
check("i18n: the 13 new v1.3.3.3 keys are present and non-empty in en/ru/zh/de",
      not _missing and len(NEW_I18N_KEYS) == 13, str(_missing))
check("i18n: the About keys carry no placeholders at all (nothing to format)",
      all(not re.search(r"\{", langs[c][k])
          for k in NEW_I18N_KEYS
          if k not in ("about.license", "status.check_now")
          for c in ("en", "ru", "zh", "de")))
check("i18n: 'about.license' keeps its {license} placeholder in every language",
      all("{license}" in langs[c]["about.license"] for c in ("en", "ru", "zh", "de")))
check("i18n: 'status.check_now' keeps its {count} placeholder in every language",
      all("{count}" in langs[c]["status.check_now"] for c in ("en", "ru", "zh", "de")))
check_i18n_parity(langs)
check_i18n_format(langs)
check_release_state(ROOT)

finish()
