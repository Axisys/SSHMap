# -*- coding: utf-8 -*-
"""v1.8.3 — the Plugins window: the plugin list, the server list and the session event ring.

The missing half of `run_on_nodes`: the plugins with their switch on the left, the servers to run on in the
middle and an event pane on the right, with a text export. §1 the ring and the PURE line builders (the
`modules/activity_log.py` shape — bounded, memory only, never persisted); §2 the three columns (the
persisted enable switch, the checked run targets, the newest-first rows, the export snapshot); §3 the TWO
DOORS of the run parameter (the global button keeps "every capable plugin", a row action names ONE id) and
the two empty sets; §4 the ONE tap, the chrome and the `ui_plugins_panel` key; §5 the release state."""
import inspect
import os
import shutil
import sys

from _common import (EXPECTED_I18N_KEYS, bootstrap, check, check_i18n_format, check_i18n_parity,
                     check_release_state, clear_cfg, finish, load_i18n_langs, read_cfg,
                     window_func_body, wait_for)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation, offscreen)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
import modules.plugin_manager as PM  # noqa: E402
import modules.plugin_runner as PR  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.plugins_panel as PP  # noqa: E402
import ui.theme_qss as TQ  # noqa: E402
from i18n import t as _t  # noqa: E402
from models.server import ServerData  # noqa: E402

_LANGS = load_i18n_langs(ROOT)
_PLUGIN_DIR = PM.user_plugin_dir()
_MANIFEST = 'MANIFEST = {"name": %r, "version": "1.0", "api_version": 1, "description": %r}\n'
_SRC = {}


def _src(*parts) -> str:
    """The source of a production file (read once) — the "it lives in ONE place" audits."""
    if parts not in _SRC:
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            _SRC[parts] = f.read()
    return _SRC[parts]


def write_plugin(stem, name, body):
    """Drop a plugin file into the user folder; returns its path."""
    os.makedirs(_PLUGIN_DIR, exist_ok=True)
    path = os.path.join(_PLUGIN_DIR, f"{stem}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write((_MANIFEST % (name, f"{name} test plugin")) + body)
    return path


def clean_plugins():
    """Empty the user plugin folder (and the import cache of its modules)."""
    if os.path.isdir(_PLUGIN_DIR):
        for name in os.listdir(_PLUGIN_DIR):
            try:
                os.remove(os.path.join(_PLUGIN_DIR, name))
            except OSError:
                pass
    for key in [k for k in sys.modules if k.startswith(PM.LOCAL_MODULE_PREFIX)]:
        sys.modules.pop(key, None)


def local(name):
    """The imported module of a folder plugin (its own state proves a call happened)."""
    return sys.modules.get(PM.LOCAL_MODULE_PREFIX + name)


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


def event(**extra):
    """A manager-shaped event dict (the drain payload the ring renders)."""
    payload = {"kind": "", "record": None}
    payload.update(extra)
    return payload


def row_of(panel, label):
    """The plugin row of `label` (the row a test acts on)."""
    for index in range(panel.plugin_tree.topLevelItemCount()):
        item = panel.plugin_tree.topLevelItem(index)
        if item.text(0) == label:
            return item
    return None


_PANEL_SRC = _src("ui", "plugins_panel.py")
#: The ring's own code (the class up to the widget) — the "nothing is persisted" region.
_ring_source = _PANEL_SRC[_PANEL_SRC.index("class PluginEventRing"):_PANEL_SRC.index("class PluginsPanel")]


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the ring and the PURE line builders ==")
# ════════════════════════════════════════════════════════════════════════════

check("§1 the bound is DECLARED once (the Activity ring's number) and it is a flat 200",
      PP.MAX_EVENTS == 200 and PP.PluginEventRing().max_events == 200, str(PP.MAX_EVENTS))
_ring = PP.PluginEventRing()
check("§1 a fresh ring is empty and nothing is invented",
      len(_ring) == 0 and _ring.events() == [] and _ring.newest_first() == []
      and _ring.snapshot() == [] and _ring.max_events == 200)
for _i in range(250):
    _ring.append("test", "INFO", "tests", f"row {_i}")
check("§1 the ring never grows past the bound and drops the OLDEST row",
      len(_ring) == 200 and _ring.events()[0].text == "row 50"
      and _ring.events()[-1].text == "row 249", str(len(_ring)))
check("§1 newest_first is the display order and the cells carry level, source and time",
      _ring.newest_first()[0].text == "row 249" and _ring.newest_first()[0].level == "INFO"
      and _ring.newest_first()[0].source == "tests"
      and _ring.newest_first()[0].time_text() != "")
check("§1 the sequence numbers are monotonic and the readers hand out COPIES",
      [e.seq for e in _ring.events()] == sorted({e.seq for e in _ring.events()})
      and _ring.events() is not _ring.events() and _ring.snapshot() is not _ring.snapshot()
      and (_ring.snapshot().clear() or len(_ring) == 200))
check("§1 an EMPTY text is not a fact (a padding line is never a row)",
      _ring.append("test", "INFO", "tests", "") is None
      and _ring.append("test", "INFO", "tests", "   ") is None and len(_ring) == 200)
check("§1 the message is flattened to ONE line (a row is a line, not a paragraph)",
      _ring.append("test", "INFO", "tests", "two\nlines\there").text == "two lines here")
_seq_before = _ring.snapshot()[-1].seq
_ring.clear()
check("§1 clear() empties the whole history while the sequence keeps counting up",
      len(_ring) == 0 and _ring.append("test", "INFO", "tests", "after").seq > _seq_before)
check("§1 the ring is MEMORY ONLY — no file, no config and no JSON in the ring's own code",
      "open(" not in _ring_source and "json" not in _ring_source
      and "save_config" not in _ring_source and "logging" not in _ring_source)
_needle = "secret-plugins-ring-4c17"
PP.PluginEventRing().append("test", "INFO", "tests", _needle)
_hits = []
for _root_dir, _dirs, _files in os.walk(os.path.expanduser("~")):
    for _name in _files:
        try:
            with open(os.path.join(_root_dir, _name), "r", encoding="utf-8", errors="ignore") as _f:
                if _needle in _f.read():
                    _hits.append(os.path.join(_root_dir, _name))
        except OSError:
            continue
check("§1 ...so no file under ~ carries an event (whoever wants the data saves it)", not _hits,
      str(_hits))

# The pure event line: every kind of the manager's own vocabulary, in ENGLISH.
_rec = PM.PluginRecord(plugin_id="demo", name="Demo", version="1.0", state=PM.STATE_LOADED)
check("§1 a LOADED event renders in English with the plugin as the source cell",
      PP.plugin_event_line(event(kind=PM.EVENT_LOADED, record=_rec))
      == ("INFO", "Demo", "Plugin loaded: Demo", ""),
      str(PP.plugin_event_line(event(kind=PM.EVENT_LOADED, record=_rec))))
_bad = PM.PluginRecord(plugin_id="broken", name="Broken", state=PM.STATE_ERROR,
                       error=PM.ERROR_IMPORT, detail="SyntaxError: nope")
check("§1 a FAILED plugin is an ERROR row and its technical reason is the tooltip",
      PP.plugin_event_line(event(kind=PM.EVENT_ERROR, record=_bad))
      == ("ERROR", "Broken", "Plugin failed to load: Broken (SyntaxError: nope)",
          "SyntaxError: nope"),
      str(PP.plugin_event_line(event(kind=PM.EVENT_ERROR, record=_bad))))
check("§1 the three remaining discovery kinds render their own sentence",
      PP.plugin_event_line(event(kind=PM.EVENT_ENABLED, record=_rec))[2] == "Plugin enabled: Demo"
      and PP.plugin_event_line(event(kind=PM.EVENT_DISABLED, record=_rec))[2]
      == "Plugin disabled: Demo"
      and PP.plugin_event_line(event(kind=PM.EVENT_RELOADED, count=3))[2:] == ("Plugins reloaded: 3", ""))
check("§1 a round-level line has no plugin: the SOURCE cell is the window's own name",
      PP.plugin_event_line(event(kind=PM.EVENT_RELOADED, count=1))[1] == PP.SOURCE_WINDOW)
check("§1 a hook that raised and a hook that ran out of budget are ERROR rows",
      PP.plugin_event_line(event(kind=PM.EVENT_HOOK_ERROR, record=_rec, hook="run_on_nodes",
                                 error="boom"))[2]
      == "Plugin Demo: run_on_nodes failed (boom)"
      and PP.plugin_event_line(event(kind=PM.EVENT_HOOK_TIMEOUT, record=_rec, hook="status_probe",
                                     budget_ms=1500))[2]
      == "Plugin Demo: status_probe did not finish within 1500 ms — abandoned")
check("§1 an UNKNOWN kind is REPORTED, never dropped (a new event cannot become invisible)",
      PP.plugin_event_line(event(kind="brand_new"))[2] == "Plugin event: brand_new"
      and PP.plugin_event_line(None)[2] == "Plugin event: "
      and PP.plugin_event_line(event(kind=PM.EVENT_LOADED, record=None))[2] == "Plugin loaded: ?")
check("§1 the event vocabulary is the manager's own constants (no second list of kinds)",
      PP.plugin_event_line(event(kind=PM.EVENT_HOOK_TIMEOUT, record=_rec, hook="h"))[0] == "ERROR"
      and PM.EVENT_HOOK_TIMEOUT in _src("modules", "plugin_manager.py"))

# The pure run lines: what a plugin RAN, never what it concluded.
_ok = {"node_id": "s1", "alias": "web-1", "host": "192.0.2.10", "exit_code": 0, "output": "up 3 days"}
check("§1 a successful node answer names the node and the exit code, output as the tooltip",
      PP.run_result_line("Demo", _ok) == ("INFO", "Demo", "Demo @ web-1: exit 0", "up 3 days"),
      str(PP.run_result_line("Demo", _ok)))
check("§1 a non-zero exit is a WARNING (the command ran — the answer is the code)",
      PP.run_result_line("Demo", {**_ok, "exit_code": 3})[:3]
      == ("WARNING", "Demo", "Demo @ web-1: exit 3"))
check("§1 an ERROR result carries the core's own reason and no exit code",
      PP.run_result_line("Demo", {"node_id": "s2", "error": "AuthenticationException: denied"})[:3]
      == ("ERROR", "Demo", "Demo @ s2: AuthenticationException: denied"))
check("§1 a deep producer is CAPPED for the ring (the runner's 1 MB is about the transfer)",
      len(PP.run_result_line("Demo", {**_ok, "output": "x" * 9000})[3]) == PP.OUTPUT_KEEP
      and PP.OUTPUT_KEEP < PR.OUTPUT_MAX and PR.OUTPUT_MAX == 1_000_000,
      f"keep={PP.OUTPUT_KEEP} runner={PR.OUTPUT_MAX}")
check("§1 the run's start and its end are ONE round line each",
      PP.run_started_line(2, 5) == ("INFO", PP.SOURCE_WINDOW,
                                    "Run started: 2 plugin(s) on 5 server(s)", "")
      and PP.run_finished_line("Demo", 5) == ("INFO", "Demo", "Run finished: Demo — 5 node(s)", ""))

# The export writer: TEXT only, one line per visible row, in the order given.
_r2 = PP.PluginEventRing()
_r2.append("k", "INFO", "plugins", "first line")
_r2.append("k", "ERROR", "demo", "second line", "the detail")
_text_out = PP.plugin_events_text(_r2.newest_first())
check("§1 the export writes ONE line per row, in the order handed over (newest first here)",
      _text_out.splitlines()[0].endswith("second line")
      and _text_out.splitlines()[1].endswith("first line")
      and _text_out.count("\n") == 2, repr(_text_out))
check("§1 a line carries the clock, the level, the source and the message",
      all(part in _text_out for part in ("INFO", "ERROR", "plugins", "demo", "first line"))
      and _r2.newest_first()[0].time_text() in _text_out)
check("§1 it is TEXT: the message leaves byte for byte, with no quoting and no CRLF",
      PP.plugin_events_text([PP.PluginEvent(1, 0.0, "k", "INFO", "src", 'a,b "c"')])
      .endswith('  a,b "c"\n')
      and '""' not in PP.plugin_events_text([PP.PluginEvent(1, 0.0, "k", "INFO", "src", 'a"b')])
      and "\r" not in PP.plugin_events_text(_r2.newest_first())
      and PP.plugin_events_text([]) == "")


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the three columns: the switch, the run targets and the event pane ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("alpha", "alpha", "X = 1\n")                    # discovered, no hook
write_plugin("beta", "beta", "RAN = {'nodes': []}\n"        # discovered, capable
                            "def run_on_nodes(nodes, ctx):\n"
                            "    RAN['nodes'].append(sorted(n.id for n in nodes))\n")
write_plugin("broken", "broken", "def broken(:\n")          # a file that cannot load
win = make_window()
add_node(win, "s1", "192.0.2.11")
add_node(win, "s2", "192.0.2.12")
win.start_plugin_discovery()
panel = win.plugins_panel
win.act_plugins_window.setChecked(True)      # the window on screen: its empty states are visible
app.processEvents()
check("§2 the window builds the panel (a non-modal QDialog owned by the window)",
      isinstance(panel, QDialog) and panel.isModal() is False and panel.parent() is win)
check("§2 ...so it never joins the map's floating-panel resolver (a window, not a fifth panel)",
      "plugins_panel" not in window_func_body("_overlay_panel_rects", ROOT)
      and panel.parent() is not win.view)
check("§2 it owns retranslate() and refresh_theme() (the container invariants)",
      callable(getattr(panel, "retranslate", None))
      and callable(getattr(panel, "refresh_theme", None)))
check("§2 the plugin rows are the manager's records, in its own order",
      [row[0] for row in panel.plugin_rows()] == ["alpha", "beta", "broken"],
      str(panel.plugin_rows()))
check("§2 ...with the VERSION cell filled and the persisted switch as the checkmark",
      panel.plugin_rows()[0][1] == "1.0" and panel.plugin_checked() == ["alpha", "beta"],
      f"{panel.plugin_rows()} / {panel.plugin_checked()}")
_broken_row = row_of(panel, "broken")
check("§2 ...and a FAILED plugin is listed, unchecked and NOT switchable (a lie is worse)",
      _broken_row.checkState(0) == Qt.CheckState.Unchecked
      and not bool(_broken_row.flags() & Qt.ItemFlag.ItemIsEnabled)
      and "SyntaxError" in _broken_row.toolTip(0), _broken_row.toolTip(0))
check("§2 the tooltip is the WINDOW's rule (one fact: the menu row and this row agree)",
      panel.tooltip_for == win._plugin_tooltip
      and row_of(panel, "alpha").toolTip(0)
      == win._plugin_tooltip(win._plugin_manager.get("alpha")))
check("§2 the row icons are applied by the panel itself (the theme walk has something to re-apply)",
      not row_of(panel, "alpha").icon(0).isNull())
check("§2 the server rows are the plugin-visible registry, not the scene",
      [row[:3] for row in panel.server_rows()]
      == [("node-1", "192.0.2.11", "root"), ("node-2", "192.0.2.12", "root")],
      str(panel.server_rows()))
check("§2 nothing is checked by default (an empty selection means the whole registry)",
      panel.checked_nodes() == [] and panel.set_checked_nodes(["s2"]) == 1
      and [n.id for n in panel.checked_nodes()] == ["s2"])
check("§2 a checkmark survives a rebuild (the target list is the user's, not the data's)",
      (panel.refresh_servers(), [n.id for n in panel.checked_nodes()])[-1] == ["s2"])
check("§2 ...and a node that left the map simply drops out of the list",
      (win.scene.remove_server("s2"), win.refresh_sidebar(), panel.refresh_servers(),
       panel.checked_nodes())[-1] == [])

# The enable switch: the panel and the menu write the SAME config key.
row_of(panel, "beta").setCheckState(0, Qt.CheckState.Unchecked)
app.processEvents()
check("§2 the row's checkmark IS the persisted plugin switch (the `plugins` config key)",
      read_cfg({}).get("plugins", {}).get("beta") is False
      and win._plugin_manager.get("beta").enabled is False
      and panel.plugin_checked() == ["alpha"], str(read_cfg({}).get("plugins")))
check("§2 ...and it is the SAME fact the Plugins menu renders once IT is rebuilt (the lazy rows)",
      (win._populate_plugin_items(), app.processEvents(),
       [a.text() for a in win._plugin_menu.actions() if a.isCheckable()
        and a is not win.act_plugins_window] == ["alpha", "beta", "broken"]
       and [a.isChecked() for a in win._plugin_menu.actions() if a.isCheckable()
            and a is not win.act_plugins_window] == [True, False, False])[-1])
row_of(panel, "beta").setCheckState(0, Qt.CheckState.Checked)
app.processEvents()
check("§2 switching it back on is written again (the round trip is honest)",
      read_cfg({}).get("plugins", {}).get("beta") is True
      and panel.plugin_checked() == ["alpha", "beta"])

# The event pane: the ring, newest first, and the English lines.
panel.clear()
panel.record_events([event(kind=PM.EVENT_LOADED, record=win._plugin_manager.get("alpha")),
                     event(kind=PM.EVENT_RELOADED, count=3)])
check("§2 record_events() copies the drained events into the ring (the manager's order kept)",
      len(panel.ring) == 2 and panel.ring.events()[0].kind == PM.EVENT_LOADED
      and panel.ring.events()[1].text == "Plugins reloaded: 3")
check("§2 the pane lists them NEWEST first with the four Activity cells",
      len(panel.event_rows()[0]) == 4 and panel.event_rows()[0][3] == "Plugins reloaded: 3"
      and panel.event_rows()[1][2] == "alpha" and panel.row_count() == 2,
      str(panel.event_rows()))
check("§2 a row's tooltip is its DETAIL (the technical reason behind the line)",
      panel.event_tree.topLevelItem(0).toolTip(3) == "Plugins reloaded: 3"
      and panel.record_run_result("alpha", {"node_id": "s1", "exit_code": 0,
                                            "output": "the captured text"}) is not None
      and panel.event_tree.topLevelItem(0).toolTip(3) == "the captured text")
panel.clear()
check("§2 an empty ring shows the sentence instead of an empty table",
      panel.row_count() == 0 and panel.event_tree.isVisible() is False
      and panel.event_empty.isVisible() is True)
check("§2 ...and the three empty columns each say their own thing",
      panel.plugin_empty.text() == _t("plugins.empty")
      and panel.server_empty.text() == _t("plugins.window.empty_servers")
      and panel.event_empty.text() == _t("plugins.window.empty_events"))

# The export takes a SNAPSHOT of the same ring.
panel.clear()
panel.record_events([event(kind=PM.EVENT_LOADED, record=win._plugin_manager.get("alpha"))])
_path = os.path.join(WORK, "plugin_log.txt")
check("§2 the export writes exactly the rows ON SCREEN (the ring, not a second buffer)",
      panel.export_to_path(_path) == ""
      and open(_path, encoding="utf-8").read() == panel.export_text()
      and "Plugin loaded: alpha" in open(_path, encoding="utf-8").read(),
      open(_path, encoding="utf-8").read())
panel.clear()
check("§2 ...so an emptied history exports nothing (what leaves is what is displayed)",
      panel.export_text() == "" and panel.export_to_path(_path) == ""
      and open(_path, encoding="utf-8").read() == "")
check("§2 the writer is UTF-8 TEXT through the ordinary save dialog (no quoting machinery copied)",
      'encoding="utf-8"' in _PANEL_SRC
      and "list_table_text" not in _PANEL_SRC and "list_quote_cell" not in _PANEL_SRC
      and "RFC 4180" not in _PANEL_SRC)
_asked = []
_original_dialog = PP.QFileDialog


class _FakeDialog:
    """A save dialog that must never be reached with an empty history (the guard's seam)."""

    @staticmethod
    def getSaveFileName(*args, **kwargs):
        _asked.append(True)
        return "", ""


PP.QFileDialog = _FakeDialog
try:
    panel._on_export_clicked()
finally:
    PP.QFileDialog = _original_dialog
check("§2 the Export button does not even open a dialog for an empty log", _asked == [], str(_asked))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the TWO doors of the run parameter, and the two empty sets ==")
# ════════════════════════════════════════════════════════════════════════════

check("§3 the manager's own entry points take the ADDITIVE selection (API v1 stays frozen)",
      "plugin_ids" in inspect.signature(PM.PluginManager.run_on_nodes).parameters
      and "plugin_ids" in inspect.signature(PM.PluginManager.plugin_run_on_nodes).parameters
      and inspect.signature(PM.PluginManager.run_on_nodes).parameters["plugin_ids"].default is None)
check("§3 ...and the plugin-facing contract is untouched (no new hook, no new context call)",
      PM.HOOKS == ("register_commands", "extend_node_context_menu", "status_probe", "run_on_nodes")
      and "def run_command" in _src("modules", "plugin_context.py"))

add_node(win, "s2", "192.0.2.12")    # s2 is back: two nodes again
panel.clear()
panel.set_checked_nodes([])
local("beta").RAN["nodes"].clear()
check("§3 the global button keeps the shipped semantics: every capable plugin starts",
      panel.run_plugins(None) == 1
      and wait_for(lambda: bool(local("beta").RAN["nodes"])) is not False,
      str(local("beta").RAN["nodes"]))
check("§3 ...and with nothing checked the WHOLE registry is the target",
      local("beta").RAN["nodes"][-1] == ["s1", "s2"], str(local("beta").RAN["nodes"]))
check("§3 the run leaves a round line in the session ring (what was started, on how many)",
      any(row[3].startswith("Run started: 1 plugin(s) on 2 server(s)")
          for row in panel.event_rows()), str(panel.event_rows()[:1]))
check("§3 ...and the status bar names the scope with the SHIPPED sentence (no new key)",
      win.statusBar().currentMessage() == _t("plugins.status.run_on_nodes", count=2),
      repr(win.statusBar().currentMessage()))

local("beta").RAN["nodes"].clear()
panel.set_checked_nodes(["s2"])
panel.run_plugins(None)
wait_for(lambda: bool(local("beta").RAN["nodes"]))
check("§3 a CHECKED server is the target list (the panel's own scope, not the map selection)",
      local("beta").RAN["nodes"][-1] == ["s2"], str(local("beta").RAN["nodes"]))
check("§3 ...and the status line counts the servers really handed over",
      win.statusBar().currentMessage() == _t("plugins.status.run_on_nodes", count=1),
      repr(win.statusBar().currentMessage()))

# A CHECKED server that LEFT the map is refused — never silently replaced by the whole registry.
local("beta").RAN["nodes"].clear()
win.scene.remove_server("s2")
win.refresh_sidebar()
panel.refresh_servers()
check("§3 a checked server that left the map does NOT widen the run to every server",
      panel.checked_nodes() == [] and panel._checked_ids == {"s2"}
      and panel.run_plugins(None) == 0 and local("beta").RAN["nodes"] == [],
      f"checked={panel.checked_nodes()} ids={panel._checked_ids} "
      f"ran={local('beta').RAN['nodes']}")
check("§3 ...and the refusal says so with ONE sentence (the release's fourth key)",
      win.statusBar().currentMessage() == _t("plugins.selection_gone"),
      repr(win.statusBar().currentMessage()))
add_node(win, "s2", "192.0.2.12")    # s2 is back, and the rest of the file keeps its state
panel.set_checked_nodes(["s2"])
check("§3 ...while a genuinely EMPTY selection still means the whole registry",
      panel.set_checked_nodes([]) == 0 and panel._checked_ids == set()
      and panel.checked_nodes() == [])
panel.set_checked_nodes(["s2"])

write_plugin("gamma", "gamma", "RAN = {'nodes': []}\n"
                             "def run_on_nodes(nodes, ctx):\n"
                             "    RAN['nodes'].append(sorted(n.id for n in nodes))\n")
win._reload_plugins()
app.processEvents()
local("beta").RAN["nodes"].clear()
local("gamma").RAN["nodes"].clear()
check("§3 the ROW action is the second door: it names ONE plugin id",
      panel.run_plugins(["gamma"]) == 1
      and wait_for(lambda: bool(local("gamma").RAN["nodes"])) is not False
      and local("beta").RAN["nodes"] == [],
      f"beta={local('beta').RAN['nodes']} gamma={local('gamma').RAN['nodes']}")
check("§3 ...so the persisted switch is NEVER reused as the run selection (config vs intent)",
      win._plugin_manager.get("beta").enabled is True
      and win._plugin_manager.get("alpha").enabled is True
      and panel.run_plugins(["gamma"]) == 1 and len(panel.plugin_checked()) >= 2)
_menu = panel.build_plugin_menu(row_of(panel, "gamma"))
check("§3 the row menu carries the ONE action (a row action is never a batch)",
      _menu is not None and [_a.text() for _a in _menu.actions()]
      == [_t("plugins.window.run_one")], str(_menu and [_a.text() for _a in _menu.actions()]))
check("§3 ...and a plugin that cannot run gets no menu at all (never an empty popup)",
      panel.build_plugin_menu(row_of(panel, "alpha")) is None
      and panel.build_plugin_menu(row_of(panel, "broken")) is None
      and panel.build_plugin_menu(None) is None)
check("§3 the menu action is a real door (it starts exactly that plugin)",
      (local("gamma").RAN["nodes"].clear(),
       [_a for _a in _menu.actions()][0].trigger(), app.processEvents(),
       wait_for(lambda: bool(local("gamma").RAN["nodes"])))[-1] is not False,
      str(local("gamma").RAN["nodes"]))

# The two empty sets: no capable plugin / no server at all.
clean_plugins()
write_plugin("plain", "plain", "X = 1\n")
win._reload_plugins()
app.processEvents()
panel.clear()
check("§3 with no plugin implementing the hook nothing starts and the hint is the answer",
      panel.run_plugins(None) == 0
      and win.statusBar().currentMessage() == _t("plugins.run_hint")
      and panel.run_btn.isEnabled() is False
      and not [r for r in panel.event_rows() if r[3].startswith("Run started")],
      repr(win.statusBar().currentMessage()))
write_plugin("gamma", "gamma", "RAN = {'nodes': []}\n"
                             "def run_on_nodes(nodes, ctx):\n"
                             "    RAN['nodes'].append(sorted(n.id for n in nodes))\n")
win._reload_plugins()
app.processEvents()
win.scene.remove_server("s1")
win.scene.remove_server("s2")
win.refresh_sidebar()
panel.refresh()
check("§3 with no server in the registry nothing starts and the empty state says why",
      panel.run_plugins(None) == 0
      and win.statusBar().currentMessage() == _t("plugins.no_selection")
      and panel.run_btn.isEnabled() is False
      and panel.server_empty.isVisible() and not panel.server_tree.isVisible(),
      repr(win.statusBar().currentMessage()))
check("§3 the run button follows the menu item's rule exactly (a capable plugin AND servers)",
      panel.run_btn.isEnabled() == bool(win._plugin_manager.node_records())
      and win.act_plugins_run.isEnabled() == bool(win._plugin_manager.node_records()))


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the ONE tap, the chrome and the ui_plugins_panel key ==")
# ════════════════════════════════════════════════════════════════════════════

add_node(win, "s1", "192.0.2.11")
panel.clear()
win.start_plugin_discovery()
check("§4 the DRAIN copies into the ring and the window shows it (the ONE consumer's branch)",
      bool(panel.ring.events()) and any("Plugin loaded: gamma" in e.text for e in panel.ring.events())
      and isinstance(panel.ring.events()[0], PP.PluginEvent))
win.statusBar().clearMessage()
win._plugin_manager._push_event(PM.EVENT_ENABLED, win._plugin_manager.get("gamma"))
win._report_plugin_events()
check("§4 with the window OPEN the drain writes NO status line (one home per fact)",
      win.statusBar().currentMessage() in ("", None)
      and any("Plugin enabled: gamma" in e.text for e in panel.ring.events()),
      repr(win.statusBar().currentMessage()))
win.act_plugins_window.setChecked(False)
app.processEvents()
win._plugin_manager._push_event(PM.EVENT_DISABLED, win._plugin_manager.get("gamma"))
win._report_plugin_events()
check("§4 with the window CLOSED the same event becomes the status line (and is still a row)",
      win.statusBar().currentMessage() == _t("plugins.status.disabled", name="gamma")
      and any("Plugin disabled: gamma" in e.text for e in panel.ring.events()),
      repr(win.statusBar().currentMessage()))
check("§4 the panel NEVER drains (the destructive queue has ONE consumer)",
      "drain_events" not in _src("ui", "plugins_panel.py")
      and "_report_plugin_events" in _src("ui", "main_window_plugins.py")
      and "record_events" in _src("ui", "plugins_panel.py"))

panel.clear()
_emit = {"node_id": "s1", "alias": "node-1", "host": "192.0.2.11", "exit_code": 0,
         "output": "line one\nline two"}
win._plugin_manager.command_result.emit("gamma", "s1", _emit)
app.processEvents()
check("§4 `command_result` is TAPPED: a per-node answer becomes a structured session row",
      any("gamma @ node-1: exit 0" in row[3] for row in panel.event_rows()), str(panel.event_rows()))
check("§4 ...with the captured output as the tooltip (what the plugin RAN, never a conclusion)",
      panel.event_tree.topLevelItem(0).toolTip(3) == "line one\nline two",
      repr(panel.event_tree.topLevelItem(0).toolTip(3)))
win._plugin_manager.command_finished.emit("gamma", [_emit, _emit])
app.processEvents()
check("§4 ...and the end of the run is ONE summary row (the count of the nodes it walked)",
      panel.event_rows()[0][3] == "Run finished: gamma — 2 node(s)", panel.event_rows()[0][3])
win._plugin_manager.command_result.emit("gamma", "s2", {"node_id": "s2",
                                                        "error": "SSHException: refused"})
app.processEvents()
check("§4 a failed answer is an ERROR row (the reason travels on the line itself)",
      panel.event_rows()[0][1] == "ERROR" and "SSHException: refused" in panel.event_rows()[0][3],
      str(panel.event_rows()[0]))
panel.clear()
win._plugin_manager.plugin_message.emit("gamma", "disk: web-01 — /opt 96%")
app.processEvents()
check("§4 `ctx.log()` is TAPPED: the plugin's OWN words become a row of the window",
      panel.event_rows()[0][1] == "INFO" and panel.event_rows()[0][2] == "gamma"
      and panel.event_rows()[0][3] == "disk: web-01 — /opt 96%", str(panel.event_rows()[:1]))
check("§4 ...while the durable record of the same line stays the prefixed LOG entry",
      "_log_line(\"info\"" in _src("modules", "plugin_manager.py")
      and "plugin_message.emit" in _src("modules", "plugin_manager.py"))
win.statusBar().clearMessage()
win._plugin_manager.status_requested.emit("gamma", "disk: 2 node(s), 1 over the threshold", 5000)
app.processEvents()
check("§4 `ctx.status()` reaches BOTH homes (the plugin ASKED for the bar; the ring keeps it)",
      win.statusBar().currentMessage() == "disk: 2 node(s), 1 over the threshold"
      and panel.event_rows()[0][3] == "disk: 2 node(s), 1 over the threshold"
      and panel.event_rows()[0][1] == PP.LEVEL_STATUS, str(panel.event_rows()[:1]))

# The chrome: translated, while the event lines stay English.
panel.clear()
panel.record_events([event(kind=PM.EVENT_LOADED, record=win._plugin_manager.get("gamma"))])
_en_title = panel.windowTitle()
i18n.set_language("ru")
win._apply_ui_translations()
app.processEvents()
check("§4 retranslate() re-texts the chrome (title, captions, buttons, the four headers)",
      panel.windowTitle() == _t("plugins.window.title") == _LANGS["ru"]["plugins.window.title"]
      and panel.windowTitle() != _en_title
      and panel.run_btn.text() == _LANGS["ru"]["plugins.window.run"]
      and panel.event_tree.headerItem().text(3) == _LANGS["ru"]["plugins.window.col.message"]
      and panel.server_tree.headerItem().text(0) == _LANGS["ru"]["plugins.window.col.server"],
      f"{panel.windowTitle()!r} / {panel.run_btn.text()!r}")
check("§4 ...and the event LINES stay English (a logging line has no key per event kind)",
      panel.event_rows()[0][3] == "Plugin loaded: gamma", str(panel.event_rows()[:1]))
i18n.set_language("en")
win._apply_ui_translations()
app.processEvents()

# The theme walk: the panel opts in, so the application's switch reaches it.
_calls = []
_real_hook = panel.refresh_theme
panel.refresh_theme = lambda: (_calls.append(True), _real_hook())[-1]
try:
    TQ._refresh_tree(panel)
finally:
    panel.refresh_theme = _real_hook
check("§4 the theme walk reaches the window (it owns a refresh_theme() hook)", _calls == [True])
check("§4 ...and re-applying it keeps the painted icons (a switch never blanks a row)",
      (panel.refresh_theme(), not panel.plugin_tree.topLevelItem(0).icon(0).isNull())[-1])

# The visibility key: ONE key, the item owns the state and the close mirrors it.
clear_cfg()
check("§4 the window is hidden by default and the key is READ, not assumed",
      win.act_plugins_window.isChecked() is False and panel.is_shown() is False
      and read_cfg({}).get("ui_plugins_panel") in (None, False))
win.act_plugins_window.setChecked(True)
app.processEvents()
check("§4 the Plugins-menu item shows it and the state is PERSISTED under ONE key",
      panel.is_shown() and win._plugins_window_enabled is True
      and read_cfg({}).get("ui_plugins_panel") is True
      and [k for k in read_cfg({}) if k.startswith("ui_plugins")] == ["ui_plugins_panel"],
      str(sorted(read_cfg({}))))
check("§4 ...and the panel re-read its sources on the way in (the rows are never stale)",
      bool(panel.plugin_rows()) and bool(panel.server_rows()))
panel.close()
app.processEvents()
check("§4 closing the window hides it, keeps the ring and unchecks the item",
      panel.is_shown() is False and win.act_plugins_window.isChecked() is False
      and win._plugins_window_enabled is False
      and read_cfg({}).get("ui_plugins_panel") is False and len(panel.ring) > 0,
      str(read_cfg({})))
check("§4 ...without a second toggle loop (the close mirrors with BLOCKED signals)",
      panel.is_shown() is False and win.act_plugins_window.isChecked() is False)
_second = make_window()
check("§4 a NEW window reads the saved state back (the key is the only owner)",
      _second._plugins_window_enabled is False and _second.act_plugins_window.isChecked() is False
      and _second.plugins_panel.is_shown() is False)
_second.plugins_panel.ring.append("k", "INFO", "tests", "a line of the session")
_second.act_plugins_window.setChecked(True)
app.processEvents()
check("§4 re-opening shows the SAME session ring (the history lives until the process ends)",
      _second.plugins_panel.is_shown() and _second.plugins_panel.row_count() == 1
      and _second.plugins_panel.event_rows()[0][3] == "a line of the session")
_second.plugins_panel.close()
_second._dirty = False
_second.close()
check("§4 the new surface costs no shortcut and no toolbar button (a window, not a view toggle)",
      "plugins.window.open" not in HR.action_ids()
      and "view.toggle_plugins" not in HR.action_ids()
      and callable(getattr(win, "_toggle_plugins_window", None))
      and callable(getattr(win, "_on_plugins_window_hidden", None)))
check("§4 the two new taps are declared on the MANAGER (a fact of the core, not a UI invention)",
      "plugin_message = Signal(str, str)" in _src("modules", "plugin_manager.py")
      and "_on_plugin_message" in _src("ui", "main_window_plugins.py")
      and "record_plugin_status" in _src("ui", "main_window_plugins.py"))

# The field's own scenario: the SHIPPED example, run from the window, must report "/opt 96%" HERE
# and not only in the Activity history (its `ctx.log()` lines are the plugin's whole answer).
clean_plugins()
shutil.copy(os.path.join(ROOT, "examples", "plugins", "disk_monitor.py"),
            os.path.join(_PLUGIN_DIR, "disk_monitor.py"))
win._reload_plugins()
app.processEvents()
_DF = ("Filesystem      Size  Used Avail Use% Mounted on\n"
       "/dev/sda1        40G   12G   27G  31% /\n"
       "/dev/sda3       100G   95G    2G  96% /opt\n")
_real_transport = PR.run_command_over_ssh
PR.run_command_over_ssh = lambda node, command, timeout, creds: PR.PluginRunResult(
    node=node, exit_code=0, output=_DF, error="")
try:
    panel.clear()
    panel.set_checked_nodes(["s1"])
    check("§4 the shipped example runs from the window (ONE plugin, the checked server)",
          panel.run_plugins(["disk_monitor"]) == 1)
    wait_for(lambda: any("/opt 96%" in row[3] for row in panel.event_rows()), timeout_ms=5000)
finally:
    PR.run_command_over_ssh = _real_transport
check("§4 ...and its per-node REPORT is a row of the window (a run is not a bare `exit 0`)",
      any("/opt 96%" in row[3] and row[2] == "disk_monitor" for row in panel.event_rows()),
      str(panel.event_rows()[:4]))
check("§4 ...next to the CORE's own row for the same node (what ran + what it said)",
      any("disk_monitor @ node-1: exit 0" in row[3] for row in panel.event_rows()),
      str(panel.event_rows()))
check("§4 ...and its summary sentence is a row too (the plugin asked the bar for it)",
      any("/opt" not in row[3] and "over the threshold" in row[3] for row in panel.event_rows()),
      str(panel.event_rows()[:2]))


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_release_state(ROOT)
check("§5 the i18n pin counts the shipped release (v1.8.2's 1003 + this window's twenty-three)",
      EXPECTED_I18N_KEYS >= 1026, str(EXPECTED_I18N_KEYS))
check_i18n_parity(_LANGS)
check_i18n_format(_LANGS)

_NEW_KEYS = ("plugins.window.open", "plugins.window.title", "plugins.window.plugins",
             "plugins.window.servers", "plugins.window.events", "plugins.window.run",
             "plugins.window.run_one", "plugins.window.clear", "plugins.window.export",
             "plugins.window.empty_servers", "plugins.window.empty_events",
             "plugins.window.checked_hint", "plugins.window.col.plugin",
             "plugins.window.col.version", "plugins.window.col.server", "plugins.window.col.host",
             "plugins.window.col.user", "plugins.window.col.port", "plugins.window.col.time",
             "plugins.window.col.level", "plugins.window.col.source",
             "plugins.window.col.message", "plugins.window.status.exported")
_missing = {code: [k for k in _NEW_KEYS if not str(data.get(k) or "").strip()]
            for code, data in _LANGS.items()}
check(f"§5 the {len(_NEW_KEYS)} new keys are present and non-empty in every language",
      not any(_missing.values()), str({c: v for c, v in _missing.items() if v}))
check("§5 ...and they are the keys the CODE really asks for (the window's own vocabulary)",
      all(part in _src("ui", "plugins_panel.py") for part in
          ('"plugins.window.title"', '"plugins.window.plugins"', '"plugins.window.servers"',
           '"plugins.window.events"', '"plugins.window.run"', '"plugins.window.run_one"',
           '"plugins.window.clear"', '"plugins.window.export"', '"plugins.window.empty_servers"',
           '"plugins.window.empty_events"', '"plugins.window.checked_hint"',
           '"plugins.window.col.plugin"', '"plugins.window.col.version"',
           '"plugins.window.col.server"', '"plugins.window.col.host"', '"plugins.window.col.user"',
           '"plugins.window.col.port"', '"plugins.window.col.time"', '"plugins.window.col.level"',
           '"plugins.window.col.source"', '"plugins.window.col.message"',
           '"plugins.window.status.exported"'))
      and '"plugins.window.open"' in _src("ui", "main_window_menubar.py"))
check("§5 the export sentence carries its {file} placeholder in every language",
      all("{file}" in _LANGS[c]["plugins.window.status.exported"] for c in _LANGS))
check("§5 the release moved and the SCHEMA did not (VERSION_FORMAT stays 0.9)",
      __import__("_common").releases_at_least(__import__("version").APP_VERSION, "1.8.3")
      and __import__("version").VERSION_FORMAT == "0.9"
      and all(f"{d}>=" in _src("requirements.txt")
              for d in ("PySide6", "paramiko", "keyring", "wcwidth")))
check("§5 no new dependency and no second config file (the four pinned ones only)",
      len([ln for ln in _src("requirements.txt").splitlines()
           if ln.strip() and not ln.startswith("#")]) == 4
      and "toml" not in _src("requirements.txt"))
check("§5 the topical file is listed by the suite map (tests/INDEX.md regenerated)",
      "test_plugins_panel" in open(os.path.join(ROOT, "tests", "INDEX.md"), encoding="utf-8").read())

win._dirty = False
win.close()
finish()
