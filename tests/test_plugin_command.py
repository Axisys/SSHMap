# -*- coding: utf-8 -*-
"""v1.9.3 — the CORE-owned command dialog: the door, its targets and the rows it produces.

`plugins.run_on_nodes` can only fire a hook a plugin already declares, so a command of the USER's own
needs a door of its own: this file drives the ONE dialog (`dialogs/plugin_command_dialog.py`) over the
SHIPPED `PluginManager.plugin_run_command()`. §1 the dialog's answer (the targets, the command, the
gate); §2 the door (`MainWindow._open_plugin_command_dialog()` — the checked servers, the two
refusals, the identity it reports under and the window it reveals); §3 the CORE-run rows of the
session ring; §4 the menu row, the keys and the release state."""
import os
import sys

from _common import (EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, bootstrap, check, check_i18n_format,
                     check_i18n_parity, check_release_state, clear_cfg, finish, load_i18n_langs,
                     read_cfg, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
import modules.plugin_manager as PM  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.main_window as MW  # noqa: E402
from dialogs.plugin_command_dialog import PluginCommandDialog, ask_plugin_command  # noqa: E402
from i18n import t as _t  # noqa: E402
from models.server import ServerData  # noqa: E402

_LANGS = load_i18n_langs(ROOT)
_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — the "it lives in ONE place" audits."""
    if parts not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            _SRC[parts] = f.read()
    return _SRC[parts]


def make_window():
    """An offscreen window with the timers stopped and NO status checker (hermetic)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()
    win._freshness_timer.stop()
    win._status_checker = None
    return win


def add_node(win, node_id, host="192.0.2.10"):
    """Feed the plugin node registry with ONE real card (the registry follows the map)."""
    win.scene.add_server(ServerData(id=node_id, alias=f"node-{node_id[1:]}", host=host,
                                    user="root", x=20.0 + 80.0 * len(win.scene.nodes()), y=20.0))
    win.refresh_sidebar()


_NODES = [PM.PluginNode(id="s1", alias="web-1", host="192.0.2.11", port=22, user="root"),
          PM.PluginNode(id="s2", alias="db-1", host="192.0.2.12", port=2222, user="deploy")]


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the dialog: the targets, the command and the gate ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
dlg = PluginCommandDialog(_NODES)
check("§1 the dialog is ONE non-modal window that ASKS (it never runs anything itself)",
      isinstance(dlg, QDialog) and dlg.isModal() is False
      and not hasattr(dlg, "plugin_run_command") and not hasattr(dlg, "manager")
      and "def ask_plugin_command(" in _src("dialogs", "plugin_command_dialog.py"))
check("§1 it lists the targets it was HANDED, in the caller's order",
      dlg.target_list.count() == 2 and dlg.target_count() == 2 and dlg.node_ids() == ["s1", "s2"]
      and dlg.target_list.item(0).text() == "web-1 (192.0.2.11)")
check("§1 ...with the account and the address as the row's tooltip (what the run really opens)",
      dlg.target_list.item(1).toolTip() == "deploy@192.0.2.12:2222",
      repr(dlg.target_list.item(1).toolTip()))
check("§1 the field is the ONE thing the user fills and the answer starts EMPTY",
      dlg.command() == "")
check("§1 the OK button is refused while the field holds only whitespace",
      dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled() is False
      and (dlg.set_command("   "),
           dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled())[-1] is False
      and (dlg.set_command("uptime"),
           dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled())[-1] is True)
check("§1 the command is TRIMMED at its edges and never normalised inside (a shell owns its spacing)",
      (dlg.set_command('  echo "a   b"  '), dlg.command())[-1] == 'echo "a   b"',
      repr((dlg.set_command('  echo "a   b"  '), dlg.command())[-1]))
check("§1 the hint states the target rule and the list names how many servers it holds",
      dlg.hint_label.text() == _t("plugins.command.hint")
      and dlg.targets_label.text() == _t("plugins.command.targets", count=2))
check("§1 the note NAMES the per-node budget the runner applies (no frozen adjective)",
      str(int(PM.COMMAND_TIMEOUT_S)) in dlg.note_label.text(),
      f"{dlg.note_label.text()!r} / {PM.COMMAND_TIMEOUT_S}")
check("§1 every piece of chrome is an i18n key (the code carries no literal text)",
      dlg.windowTitle() == _t("plugins.command.title")
      and dlg.buttons.button(dlg.buttons.StandardButton.Ok).text() == _t("plugins.command.run"))
_id_only = PluginCommandDialog([PM.PluginNode(id="s9")])
check("§1 a target without an alias falls back to the id (a row is never blank)",
      _id_only.target_list.item(0).text() == "s9"
      and _id_only.target_list.item(0).toolTip() == "@:22")
_id_only.deleteLater()


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the door: the checked servers, the two refusals and the identity ==")
# ════════════════════════════════════════════════════════════════════════════

win = make_window()
add_node(win, "s1", "192.0.2.11")
add_node(win, "s2", "192.0.2.12")
win._populate_plugin_items()          # what `aboutToShow` does before the menu is painted
panel = win.plugins_panel

_asked, _runs = [], []
_real_ask = MW.ask_plugin_command
_real_run = win._plugin_manager.plugin_run_command


def _fake_ask(nodes, parent=None, timeout_s=None):
    _asked.append([getattr(n, "id", "") for n in nodes])
    return "uptime -a"


def _fake_run(plugin_id, nodes, command, **kwargs):
    _runs.append((plugin_id, command, [getattr(n, "id", "") for n in nodes]))
    return True


MW.ask_plugin_command = _fake_ask
win._plugin_manager.plugin_run_command = _fake_run
try:
    check("§2 with nothing checked the door targets the WHOLE registry (the shipped scope)",
          win._open_plugin_command_dialog() is True and _asked[-1] == ["s1", "s2"]
          and _runs[-1] == (PM.CORE_RUN_ID, "uptime -a", ["s1", "s2"]), str(_runs))
    check("§2 a CORE-owned run reports under the manager's ONE constant — never a plugin's id",
          _runs[-1][0] == PM.CORE_RUN_ID == "core"
          and win._plugin_manager.get(PM.CORE_RUN_ID) is None
          and win._plugin_label(PM.CORE_RUN_ID) == "core", str(PM.CORE_RUN_ID))
    check("§2 the door REVEALS the window whose ring holds the answer (through the item that OWNS it)",
          panel.is_shown() and win.act_plugins_window.isChecked()
          and read_cfg({}).get("ui_plugins_panel") is True, str(read_cfg({}).get("ui_plugins_panel")))
    check("§2 ...and the status line counts the servers the command was sent to",
          win.statusBar().currentMessage() == _t("plugins.command.status.started", count=2),
          repr(win.statusBar().currentMessage()))

    panel.set_checked_nodes(["s2"])
    check("§2 the CHECKED rows are the target list (the window's own scope, not the map selection)",
          win._open_plugin_command_dialog() is True and _asked[-1] == ["s2"]
          and _runs[-1][2] == ["s2"], str(_asked))

    # A CHECKED server that LEFT the map is refused — never silently widened (AGENTS.md §4.10).
    win.scene.remove_server("s2")
    win.refresh_sidebar()
    panel.refresh_servers()
    win.statusBar().clearMessage()
    check("§2 a checked server that left the map is REFUSED with the SHIPPED sentence — nothing runs",
          win._open_plugin_command_dialog() is False and len(_runs) == 2
          and win.statusBar().currentMessage() == _t("plugins.selection_gone"),
          f"{len(_runs)} runs / {win.statusBar().currentMessage()!r}")
    check("§2 ...and the same rule is declared ONCE (the door asks the panel, it never re-derives it)",
          panel._checked_ids == {"s2"} and panel.checked_nodes() == []
          and "def resolve_targets(" in _src("ui", "plugins_panel.py")
          and "resolve_targets" in _src("ui", "main_window_plugins.py"))

    # A cancelled dialog changes nothing at all.
    add_node(win, "s2", "192.0.2.12")
    panel.set_checked_nodes([])
    win.act_plugins_window.setChecked(False)
    app.processEvents()
    win.statusBar().clearMessage()
    MW.ask_plugin_command = lambda nodes, parent=None, timeout_s=None: None
    check("§2 a cancelled dialog changes NOTHING (no run, no status line, no reveal)",
          win._open_plugin_command_dialog() is False and len(_runs) == 2
          and not panel.is_shown() and win.statusBar().currentMessage() in ("", None),
          f"{len(_runs)} runs / {win.statusBar().currentMessage()!r}")

    # A registry with no server at all is the shipped "nothing to run on" sentence.
    win.scene.remove_server("s1")
    win.scene.remove_server("s2")
    win.refresh_sidebar()
    win._populate_plugin_items()
    win.statusBar().clearMessage()
    check("§2 with no server in the registry the door says so with the SHIPPED sentence",
          win._open_plugin_command_dialog() is False and len(_runs) == 2
          and win.statusBar().currentMessage() == _t("plugins.no_selection"),
          repr(win.statusBar().currentMessage()))

    # A runner that refuses is REPORTED (never a silent no-op).
    add_node(win, "s1", "192.0.2.11")
    win._populate_plugin_items()
    MW.ask_plugin_command = _fake_ask
    win._plugin_manager.plugin_run_command = lambda *a, **k: False
    win.statusBar().clearMessage()
    check("§2 a runner that REFUSES the call is reported instead of silently doing nothing",
          win._open_plugin_command_dialog() is False
          and win.statusBar().currentMessage() == _t("plugins.command.failed"),
          repr(win.statusBar().currentMessage()))

    # v1.9.6: a False start caused by the COMMAND GUARD has its OWN sentence — the door reads the
    # manager's verdict instead of blaming the start (and never claims "sent to N servers").
    MW.ask_plugin_command = lambda nodes, parent=None, timeout_s=None: "rm -rf /var"
    win._plugin_manager.plugin_run_command = _real_run      # the REAL boundary, guard included
    _pm = sys.modules["modules.plugin_manager"]
    _orig_gate = _pm.command_confirm
    _pm.command_confirm = lambda command, token, **kw: False
    try:
        win.statusBar().clearMessage()
        panel.clear()
        check("§2 a command the guard REFUSED says which refusal it was (not `command.failed`)",
              win._open_plugin_command_dialog() is False
              and win.statusBar().currentMessage() == _t("plugins.command.guard_refused",
                                                         token="rm -rf", count=1),
              repr(win.statusBar().currentMessage()))
        check("§2 ...so the status line never claims 'sent to N servers' about a refused run",
              win.statusBar().currentMessage()
              != _t("plugins.command.status.started", count=1))
        check("§2 ...and the refusal is a row of the Plugins window's ring (a result, not a silence)",
              any("Run refused" in row[3] for row in panel.event_rows())
              and any("0 node(s)" in row[3] for row in panel.event_rows()),
              str(panel.event_rows()[:2]))
    finally:
        _pm.command_confirm = _orig_gate
        win._plugin_manager.plugin_run_command = _fake_run
finally:
    MW.ask_plugin_command = _real_ask
    win._plugin_manager.plugin_run_command = _real_run


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the CORE-run rows land in the session ring (the shipped taps) ==")
# ════════════════════════════════════════════════════════════════════════════

panel.clear()
win._plugin_manager.command_result.emit(PM.CORE_RUN_ID, "s1", {
    "node_id": "s1", "alias": "node-1", "host": "192.0.2.11", "exit_code": 0,
    "output": "up 3 days"})
app.processEvents()
check("§3 a CORE-run answer is a row of the session ring, sourced on the core",
      panel.row_count() == 1 and panel.event_rows()[0][2] == PM.CORE_RUN_ID
      and panel.event_rows()[0][3] == "core @ node-1: exit 0"
      and panel.event_tree.topLevelItem(0).toolTip(3) == "up 3 days",
      str(panel.event_rows()))
win._plugin_manager.command_finished.emit(PM.CORE_RUN_ID, [{}])
app.processEvents()
check("§3 ...and the end of it is ONE summary row (the tap carries both, no new plumbing)",
      panel.event_rows()[0][3] == "Run finished: core — 1 node(s)", str(panel.event_rows()[0]))
check("§3 the identity is the manager's own constant, so the rows can never claim a plugin ran them",
      _runs[-1][0] == PM.CORE_RUN_ID
      and all(e.source != "" for e in panel.ring.events())
      and PM.CORE_RUN_ID in _src("modules", "plugin_manager.py"))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the menu row, the keys and the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the door is a row of the Plugins menu and costs NO shortcut (the v1.8.3 window's rule)",
      win.act_plugins_command.text() == _t("plugins.command.open")
      and win.act_plugins_command.shortcut().isEmpty()
      and "plugins.command.open" not in HR.action_ids()
      and "plugins.command.open" in _src("ui", "main_window_menubar.py"))
check("§4 it is enabled by the REGISTRY alone (its runner is the core's own — no plugin needed)",
      win.act_plugins_command.isEnabled() is True
      and (win.scene.remove_server("s1"), win.refresh_sidebar(), win._populate_plugin_items(),
           win.act_plugins_command.isEnabled())[-1] is False,
      str(win._plugin_manager.node_records()))
check("§4 the dialog reaches the mixin through the declared facade seam (a test substitutes it there)",
      callable(getattr(MW, "ask_plugin_command", None))
      and MW.ask_plugin_command in MW.MODULE_FACADE_SEAMS
      and "host_attr(self, \"ask_plugin_command\")" in _src("ui", "main_window_plugins.py"))

_NEW_KEYS = ("plugins.command.open", "plugins.command.title", "plugins.command.hint",
             "plugins.command.label", "plugins.command.placeholder", "plugins.command.targets",
             "plugins.command.note", "plugins.command.run", "plugins.command.failed",
             "plugins.command.status.started")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in _LANGS.items()}
check(f"§4 the {len(_NEW_KEYS)} new keys are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§4 ...and they are the keys the CODE really asks for (the family is the door's own vocabulary)",
      all(f'"{key}"' in _src("dialogs", "plugin_command_dialog.py")
          or f'"{key}"' in _src("ui", "main_window_plugins.py")
          or f'"{key}"' in _src("ui", "main_window_menubar.py") for key in _NEW_KEYS),
      str([k for k in _NEW_KEYS
           if not any(f'"{k}"' in _src(*p) for p in (("dialogs", "plugin_command_dialog.py"),
                                                     ("ui", "main_window_plugins.py"),
                                                     ("ui", "main_window_menubar.py")))]))
check("§4 the two placeholders survive in every language (a count and a budget)",
      all("{count}" in data["plugins.command.targets"]
          and "{count}" in data["plugins.command.status.started"]
          and "{seconds}" in data["plugins.command.note"] for data in _LANGS.values()),
      str({c: _LANGS[c]["plugins.command.note"] for c in _LANGS}))
check("§4 the release moved, the SCHEMA did not and the pin counts the thirteen new keys "
      "(plus v1.9.6's three: the command guard)",
      releases_at_least(EXPECTED_APP_VERSION, "1.9.3") and EXPECTED_I18N_KEYS == 1051 + 10 + 3 + 3
      and __import__("version").VERSION_FORMAT == "0.9", str(EXPECTED_I18N_KEYS))
check_i18n_parity(_LANGS)
check_i18n_format(_LANGS)
check_release_state(ROOT)
check("§4 the topical file is listed by the suite map (tests/INDEX.md regenerated)",
      "test_plugin_command" in open(os.path.join(ROOT, "tests", "INDEX.md"),
                                    encoding="utf-8").read())

i18n.set_language("en")
win._dirty = False
win.close()
finish()
