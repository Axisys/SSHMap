# -*- coding: utf-8 -*-
"""v1.4rc1 — Plugin foundation, part 1: discovery and manager (ROADMAP v1.4rc1, the rc series).

The FIRST rc of the 1.4 line implements the frozen API v1 contract (PLUGINS.md) up to
discovery: two sources (the standard entry-point group `sshmap.plugins/v1` and the user
folder `~/.sshmap/plugins/*.py`), a MANIFEST check (`name`/`version`/`api_version`, the
optional `description`), three states (`loaded`/`disabled`/`error`), the enable/disable
switch in `plugins` of `~/.sshmap/config.json`, the `Plugins` menu (+ `Reload`) and the
status-bar reports. The HOOKS are validated and recorded from here on, but NOT called —
that is rc2/rc3.

Sections:
  §1 the folder source: discovery, the MANIFEST fields, a `_`-prefixed file, sys.modules;
  §2 the MANIFEST check: no manifest / not a dict / no name / no version / a foreign
     api_version / an optional description — each a state, never an exception;
  §3 a broken plugin is not fatal: the app and the OTHER plugins live on, the log gets
     a record (the ROADMAP wording), a broken entry point raises nothing;
  §4 the entry-point source (monkeypatched importlib.metadata.entry_points) + the name
     conflict rule (the packaged plugin wins, the local file is skipped with a log line);
  §5 enable/disable: the default, the persisted switch, a broken/unknown config value,
     a fresh manager honouring the file, foreign config keys surviving;
  §6 reload: a new file appears, a CHANGED file is really re-read (no import cache),
     a removed file disappears, the round event carries the count;
  §7 the window: the "Plugins" menu (position, the rows, the error row, the empty
     placeholder, no duplicate rows after a rebuild), the toggle, "Reload" as a registry
     action, the status-bar lines, the menu title following a language switch;
  §8 the wiring: main.py runs the discovery after MainWindow and before app.exec();
  §9 the frozen contract: PLUGINS.md pins the group name / API version / the folder;
  §10 i18n parity + format, the new keys, the release state (the pins of _common.py).

Run: python tests/test_plugins.py   (from the project root) or python tests/run_all.py
"""
import importlib
import importlib.metadata
import json
import logging
import os
import sys

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, translation_keys)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import i18n  # noqa: E402
from i18n import t  # noqa: E402
import modules.plugin_manager as PM  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
PLUGIN_DIR = PM.user_plugin_dir()
PLUGINS_MD = os.path.join(ROOT, "PLUGINS.md")

NEW_I18N_KEYS = ["menu.plugins", "plugins.reload", "plugins.empty",
                 "plugins.status.loaded", "plugins.status.error",
                 "plugins.status.enabled", "plugins.status.disabled",
                 "plugins.status.reloaded"]


# ── helpers ───────────────────────────────────────────────────────────────────

def write_plugin(name, body):
    """Drop a plugin file into the user folder and return its path.

    A name without a dot gets the `.py` suffix (the ordinary call); a name that carries
    a suffix is written verbatim, so the "a foreign file is ignored" case is expressible.
    """
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    if "." not in name:
        name = f"{name}.py"
    path = os.path.join(PLUGIN_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def manifest(name="demo", version="1.0", api=1, description=None, extra=""):
    """A plugin source with a MANIFEST (the canonical shape of PLUGINS.md §1)."""
    desc = "" if description is None else f', "description": {description!r}'
    return (f'MANIFEST = {{"name": {name!r}, "version": {version!r}, '
            f'"api_version": {api}{desc}}}\n{extra}')


def clean_plugins():
    """Empty the user plugin folder (and the import cache of its modules)."""
    if os.path.isdir(PLUGIN_DIR):
        for n in os.listdir(PLUGIN_DIR):
            try:
                os.remove(os.path.join(PLUGIN_DIR, n))
            except OSError:
                pass
    for key in [k for k in sys.modules if k.startswith(PM.LOCAL_MODULE_PREFIX)]:
        sys.modules.pop(key, None)


def clear_cfg():
    try:
        os.remove(CONFIG_FILE)
    except OSError:
        pass


def new_manager():
    """A fresh manager (a test sees exactly the plugins the section just wrote)."""
    return PM.PluginManager()


def new_window():
    win = MW.MainWindow()
    win._autosave_timer.stop()
    return win


def plugin_log_records():
    """Capture the manager's log lines (the ROADMAP "a record in modules/logger.py")."""
    lines = []

    class _Handler(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger("sshmap.modules.plugin_manager")
    handler = _Handler()
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    return lines, logger, handler, old_level


class FakeEntryPoint:
    """The importlib.metadata.EntryPoint surface the discovery uses."""

    def __init__(self, name, value, target=None, error=None):
        self.name = name
        self.value = value
        self._target = target
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._target


_FAKE_EPS = []


def fake_entry_points(group=None):
    """The monkeypatched importlib.metadata.entry_points (group filtering included)."""
    if group is None:
        return {"sshmap.plugins/v1": list(_FAKE_EPS)}
    return [ep for ep in _FAKE_EPS if group == PM.ENTRY_POINT_GROUP]


_ORIG_ENTRY_POINTS = importlib.metadata.entry_points


def patch_entry_points():
    importlib.metadata.entry_points = fake_entry_points


def restore_entry_points():
    importlib.metadata.entry_points = _ORIG_ENTRY_POINTS


def plugin_module(name, **attrs):
    """An in-memory "module" object for a fake entry point."""
    mod = type(sys)(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the folder source: discovery and the MANIFEST fields ==")
# ════════════════════════════════════════════════════════════════════════════

check("the plugin folder is NOT created by the import of the manager (no empty directory)",
      not os.path.isdir(PLUGIN_DIR), PLUGIN_DIR)
check("an absent folder discovers nothing and does not raise",
      new_manager().discover() == [] and not os.path.isdir(PLUGIN_DIR))

write_plugin("demo", manifest(description="Demo plugin",
                              extra='def status_probe(node):\n    return None\n\n'
                                    'def run_on_nodes(nodes, ctx):\n    return None\n'))
write_plugin("_helper", "NOT_A_PLUGIN = True\n")   # a private helper — not a plugin
write_plugin("notes.txt", "not python\n")          # not a .py file — ignored

mgr = new_manager()
records = mgr.discover()
check("a folder plugin with a MANIFEST is discovered and loaded",
      len(records) == 1 and records[0].plugin_id == "demo"
      and records[0].state == PM.STATE_LOADED, str([(r.plugin_id, r.state) for r in records]))
rec = records[0]
check("the record carries the manifest: name/version/api_version/description",
      rec.name == "demo" and rec.version == "1.0" and rec.api_version == 1
      and rec.description == "Demo plugin", str(rec))
check("the record says which source produced it and where it lives",
      rec.source == PM.SOURCE_FOLDER and rec.origin == os.path.join(PLUGIN_DIR, "demo.py"),
      f"{rec.source} / {rec.origin}")
check("the HOOKS present on the module are recorded (they are not called in rc1)",
      rec.hooks == (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES), str(rec.hooks))
check("a file starting with _ is skipped (a private helper is not a plugin)",
      all(r.plugin_id != "_helper" for r in records))
check("a non-.py file is ignored by the discovery",
      all(not r.origin.endswith(".txt") for r in records))
check("the module is imported under the documented unique name",
      f"{PM.LOCAL_MODULE_PREFIX}demo" in sys.modules,
      str([k for k in sys.modules if k.startswith(PM.LOCAL_MODULE_PREFIX)]))
check("a healthy discovery raises no error state and reports the plugin as enabled",
      not any(r.failed for r in records) and mgr.is_enabled("demo")
      and mgr.loaded_records() == [rec])
check("records()/get()/discovered() expose the registry the menu renders",
      mgr.records() == [rec] and mgr.get("demo") is rec and mgr.get("nope") is None
      and mgr.discovered() is True)

clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the MANIFEST check: every defect is a state, never an exception ==")
# ════════════════════════════════════════════════════════════════════════════

write_plugin("nomanifest", "X = 1\n")
records = new_manager().discover()
check("a module without MANIFEST → the error state with the reason 'manifest'",
      len(records) == 1 and records[0].state == PM.STATE_ERROR
      and records[0].error == PM.ERROR_MANIFEST
      and records[0].plugin_id == "nomanifest",
      str([(r.plugin_id, r.state, r.error) for r in records]))
check("a failed plugin is neither ok nor switchable (ok/failed are the usable predicates)",
      records[0].ok is False and records[0].failed is True and records[0].enabled is True
      and records[0].hooks == (),
      f"ok={records[0].ok} failed={records[0].failed} enabled={records[0].enabled}")

clean_plugins()
write_plugin("notadict", "MANIFEST = ['demo', '1.0']\n")
rec = new_manager().discover()[0]
check("a MANIFEST that is not a dict → 'manifest'",
      rec.error == PM.ERROR_MANIFEST and "list" in rec.detail, rec.detail)

clean_plugins()
write_plugin("noname", 'MANIFEST = {"version": "1.0", "api_version": 1}\n')
rec = new_manager().discover()[0]
check("a MANIFEST without a usable \"name\" → 'manifest'",
      rec.error == PM.ERROR_MANIFEST and "name" in rec.detail, rec.detail)

clean_plugins()
write_plugin("noversion", 'MANIFEST = {"name": "noversion", "api_version": 1}\n')
rec = new_manager().discover()[0]
check("a MANIFEST without a usable \"version\" → 'manifest'",
      rec.error == PM.ERROR_MANIFEST and "version" in rec.detail, rec.detail)

clean_plugins()
write_plugin("foreign", manifest(name="foreign", version="2.0", api=2))
rec = new_manager().discover()[0]
check("a foreign api_version → the error state with the reason 'api_version'",
      rec.state == PM.STATE_ERROR and rec.error == PM.ERROR_API_VERSION
      and rec.plugin_id == "foreign", f"{rec.state}/{rec.error}")
check("the foreign plugin keeps its identity from the manifest (the menu can name it)",
      rec.name == "foreign" and rec.version == "2.0")

clean_plugins()
write_plugin("nodesc", manifest(name="nodesc", description=None))
rec = new_manager().discover()[0]
check("a missing description is legal (it is the only optional MANIFEST key)",
      rec.state == PM.STATE_LOADED and rec.description == "" and rec.api_version == 1)

clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §3 a broken plugin never breaks the app or its neighbours ==")
# ════════════════════════════════════════════════════════════════════════════

write_plugin("good", manifest(name="good"))
write_plugin("syntax", "def broken(:\n")
write_plugin("raises", "raise RuntimeError('boom at import')\n")
write_plugin("missing_dep", "import definitely_not_installed_xyz  # noqa: F401\n")

_lines, _logger, _handler, _old_level = plugin_log_records()
try:
    mgr = new_manager()
    records = mgr.discover()
finally:
    _logger.removeHandler(_handler)
    _logger.setLevel(_old_level)

states = {r.plugin_id: r for r in records}
check("the good plugin is still loaded next to three broken ones (one plugin cannot hurt another)",
      states["good"].state == PM.STATE_LOADED and len(records) == 4,
      str([(r.plugin_id, r.state) for r in records]))
check("a syntax error → 'import' with the exception text in the detail",
      states["syntax"].error == PM.ERROR_IMPORT and "SyntaxError" in states["syntax"].detail,
      states["syntax"].detail)
check("an exception raised at import time → 'import' (never propagated to the caller)",
      states["raises"].error == PM.ERROR_IMPORT and "boom at import" in states["raises"].detail,
      states["raises"].detail)
check("a missing third-party dependency → 'import' (a normal ImportError)",
      states["missing_dep"].error == PM.ERROR_IMPORT
      and "definitely_not_installed_xyz" in states["missing_dep"].detail,
      states["missing_dep"].detail)
check("a half-imported failed module does not stay in sys.modules (a later reload is clean)",
      f"{PM.LOCAL_MODULE_PREFIX}syntax" not in sys.modules
      and f"{PM.LOCAL_MODULE_PREFIX}missing_dep" not in sys.modules)
check("every failure left a record in the application log (ROADMAP rc1 task 1)",
      len([line for line in _lines if "failed to load" in line]) == 3
      and all(any(name in line for name in ("syntax", "raises", "missing_dep"))
              for line in _lines if "failed to load" in line),
      str(_lines[:3]))
check("the manager survives the broken set: the app keeps the good plugin enabled",
      mgr.is_enabled("good") and not mgr.is_enabled("syntax"))

clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the entry-point source + the conflict rule ==")
# ════════════════════════════════════════════════════════════════════════════

_good_mod = plugin_module("sshmap_fake_ep_good",
                          MANIFEST={"name": "ep-good", "version": "2.5", "api_version": 1,
                                    "description": "from a package"},
                          register_commands=lambda ctx: [])

_FAKE_EPS[:] = [
    FakeEntryPoint("sshmap-hello-plugin", "sshmap_fake_ep_good", target=_good_mod),
    FakeEntryPoint("broken-ep", "nowhere.at.all", error=ImportError("no module named nowhere")),
    FakeEntryPoint("foreign-ep", "sshmap_foreign",
                   target=plugin_module("sshmap_foreign",
                                        MANIFEST={"name": "ep-foreign", "version": "9",
                                                  "api_version": 7})),
]
patch_entry_points()
try:
    records = new_manager().discover()
    _ep_records = list(records)
finally:
    restore_entry_points()

by_id = {r.plugin_id: r for r in _ep_records}
check("an installed package entry point of the group is discovered and loaded",
      by_id.get("ep-good") is not None and by_id["ep-good"].state == PM.STATE_LOADED,
      str([(r.plugin_id, r.state) for r in _ep_records]))
check("the entry-point record carries the manifest and the source 'entry_point'",
      by_id["ep-good"].source == PM.SOURCE_ENTRY_POINT
      and by_id["ep-good"].version == "2.5"
      and by_id["ep-good"].description == "from a package"
      and by_id["ep-good"].hooks == ("register_commands",),
      str(by_id["ep-good"]))
check("a failing ep.load() → 'import' keyed by the ENTRY POINT name (no manifest to read)",
      by_id["broken-ep"].error == PM.ERROR_IMPORT and by_id["broken-ep"].plugin_id == "broken-ep",
      str(by_id["broken-ep"]))
check("an entry-point plugin with a foreign api_version → 'api_version'",
      by_id["ep-foreign"].error == PM.ERROR_API_VERSION)

# The conflict rule: the packaged plugin wins, the local file is skipped with a log line.
write_plugin("hello_local", manifest(name="ep-good", version="0.1"))
_lines, _logger, _handler, _old_level = plugin_log_records()
patch_entry_points()
try:
    conflict_records = new_manager().discover()
finally:
    restore_entry_points()
    _logger.removeHandler(_handler)
    _logger.setLevel(_old_level)
_ids = sorted(r.plugin_id for r in conflict_records)
check("a local file with the id of a PACKAGED plugin loses (one identity, one row)",
      _ids.count("ep-good") == 1 and len(conflict_records) == 3, str(_ids))
check("the winner is the packaged plugin (the local version is not what was recorded)",
      [r.version for r in conflict_records if r.plugin_id == "ep-good"] == ["2.5"],
      str([(r.plugin_id, r.version) for r in conflict_records]))
check("the skipped local file left a log line naming it and the winner",
      any("skipped" in line and "ep-good" in line for line in _lines), str(_lines))

# A discovery must survive entry_points() itself blowing up (a broken installation).
_ORIG = importlib.metadata.entry_points
importlib.metadata.entry_points = lambda **kw: (_ for _ in ()).throw(RuntimeError("broken metadata"))
try:
    records = new_manager().discover()
finally:
    importlib.metadata.entry_points = _ORIG
check("an entry_points() failure is swallowed (the folder source still works)",
      [r.plugin_id for r in records] == ["ep-good"], str([r.plugin_id for r in records]))

clean_plugins()
_FAKE_EPS[:] = []

# ════════════════════════════════════════════════════════════════════════════
print("== §5 enable / disable: the switch in config.json ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
write_plugin("switch", manifest(name="switch"))
mgr = new_manager()
mgr.discover()
check("a discovered plugin is ENABLED by default (a new plugin is on)",
      mgr.is_enabled("switch") and mgr.get("switch").state == PM.STATE_LOADED)

check("set_enabled(False) moves the record to 'disabled' and returns True",
      mgr.set_enabled("switch", False) is True
      and mgr.get("switch").state == PM.STATE_DISABLED and not mgr.is_enabled("switch"))
with open(CONFIG_FILE, encoding="utf-8") as f:
    stored = json.load(f)
check("the switch is persisted in the `plugins` key of config.json",
      stored.get("plugins") == {"switch": False}, str(stored.get("plugins")))
check("a DISABLED plugin is still imported (the manifest is how the menu names it)",
      f"{PM.LOCAL_MODULE_PREFIX}switch" in sys.modules)

mgr.set_enabled("switch", True)
with open(CONFIG_FILE, encoding="utf-8") as f:
    stored = json.load(f)
check("switching it back writes the enabled state",
      stored.get("plugins") == {"switch": True} and mgr.is_enabled("switch"))

i18n.save_config({"language": "en", "terminal_palette": "nord"})
mgr.set_enabled("switch", False)
cfg = i18n.load_config()
check("the merge-write preserves the FOREIGN config keys (the v1.3.2 rule)",
      cfg.get("language") == "en" and cfg.get("terminal_palette") == "nord"
      and cfg.get("plugins") == {"switch": False}, str(sorted(cfg)))

fresh = new_manager()
fresh.discover()
check("a fresh manager honours the saved switch (it survives a restart)",
      fresh.get("switch").state == PM.STATE_DISABLED and not fresh.is_enabled("switch"))

i18n.save_config({"plugins": {"switch": "nope"}})
rec = new_manager()
rec.discover()
check("a BROKEN stored value falls back to the default (enabled), never to a crash",
      rec.get("switch").state == PM.STATE_LOADED)

i18n.save_config({"plugins": {"switch": True, "ghost-plugin": False}})
rec = new_manager()
rec.discover()
check("an unknown id in the file is ignored; the known one is applied",
      rec.get("switch").state == PM.STATE_LOADED and rec.get("ghost-plugin") is None)
rec.set_enabled("switch", False)
check("the write drops the unknown id (only discovered plugins are keyed — the save_hotkeys rule)",
      i18n.load_config().get("plugins") == {"switch": False},
      str(i18n.load_config().get("plugins")))

write_plugin("errored", "MANIFEST = 42\n")
rec = new_manager()
rec.discover()
check("set_enabled on an UNKNOWN id is refused (False, no write)",
      rec.set_enabled("no-such-plugin", False) is False)
check("set_enabled on an ERROR record is refused (a broken plugin has nothing to switch)",
      rec.set_enabled("errored", False) is False
      and rec.get("errored").state == PM.STATE_ERROR)
check("the refused switches never reached the file",
      i18n.load_config().get("plugins") == {"switch": False},
      str(i18n.load_config().get("plugins")))

clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §6 reload: the folder is re-read, not cached ==")
# ════════════════════════════════════════════════════════════════════════════

write_plugin("first", manifest(name="first"))
mgr = new_manager()
mgr.discover()
check("precondition: one plugin before the reload",
      [r.plugin_id for r in mgr.records()] == ["first"])
mgr.drain_events()

write_plugin("second", manifest(name="second"))
records = mgr.reload()
check("a new .py is picked up by Reload without a restart",
      sorted(r.plugin_id for r in records) == ["first", "second"],
      str([r.plugin_id for r in records]))
events = mgr.drain_events()
check("the reload round queues one event per plugin plus the round report",
      [e["kind"] for e in events] == [PM.EVENT_LOADED, PM.EVENT_LOADED, PM.EVENT_RELOADED],
      str([e["kind"] for e in events]))
check("the round report carries the plugin count",
      [e.get("count") for e in events if e["kind"] == PM.EVENT_RELOADED] == [2])

write_plugin("first", manifest(name="first", extra="CHANGED = True\n"))
mgr.reload()
check("a CHANGED file is really re-read (the module object is replaced, not cached)",
      getattr(sys.modules[f"{PM.LOCAL_MODULE_PREFIX}first"], "CHANGED", False) is True)
os.remove(os.path.join(PLUGIN_DIR, "second.py"))
records = mgr.reload()
check("a removed file disappears from the registry",
      [r.plugin_id for r in records] == ["first"], str([r.plugin_id for r in records]))
check("drain_events() empties the queue (no repeated status lines)",
      isinstance(mgr.drain_events(), list) and mgr.drain_events() == [])

clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §7 the window: the Plugins menu, the switch, the status lines ==")
# ════════════════════════════════════════════════════════════════════════════

clear_cfg()
clean_plugins()
win = new_window()
_titles = [a.text() for a in win.menuBar().actions()]
check("the 'Plugins' menu exists BETWEEN 'Settings' and 'Help' (next to the settings hub)",
      t("menu.plugins") in _titles
      and _titles.index(t("menu.plugins")) == _titles.index(t("menu.settings")) + 1
      and _titles.index(t("menu.plugins")) == _titles.index(t("menu.help")) - 1,
      str(_titles))
check("with nothing discovered the menu holds the disabled placeholder naming the folder",
      [a.text() for a in win._plugin_menu.actions()][0] == t("plugins.empty")
      and win._plugin_menu.actions()[0].isEnabled() is False,
      str([a.text() for a in win._plugin_menu.actions()]))
check("the placeholder names the folder a user must drop a file into",
      "~/.sshmap/plugins/" in t("plugins.empty"), t("plugins.empty"))

write_plugin("uiplugin", manifest(name="uiplugin", version="3.1", description="A UI plugin",
                                  extra="def register_commands(ctx):\n    return []\n"))
write_plugin("uibroken", "def broken(:\n")
win.start_plugin_discovery()
app.processEvents()
_broken_rec = win._plugin_manager.get("uibroken")
_error_text = t("plugins.status.error", name="uibroken", error=_broken_rec.detail)
check("the startup round reports the load ERROR in the status bar (the one-time message)",
      win.statusBar().currentMessage() == _error_text, win.statusBar().currentMessage())
check("…while a successfully loaded plugin stays quiet at startup (the menu already lists it)",
      t("plugins.status.loaded", name="uiplugin") not in win.statusBar().currentMessage())
_rows = {a.text(): a for a in win._plugin_menu.actions() if a.isCheckable()}
check("every discovered plugin got a checkable row (loaded + the broken one)",
      set(_rows) == {"uiplugin", "uibroken"}, str(sorted(_rows)))
check("the loaded plugin's row is checked and enabled",
      _rows["uiplugin"].isChecked() and _rows["uiplugin"].isEnabled())
check("the FAILED plugin's row is present but disabled and unchecked (the reason in the tooltip)",
      not _rows["uibroken"].isChecked() and not _rows["uibroken"].isEnabled()
      and "SyntaxError" in _rows["uibroken"].toolTip(),
      _rows["uibroken"].toolTip())
check("the loaded row's tooltip carries the plugin's version and description",
      _rows["uiplugin"].toolTip() == "v3.1 — A UI plugin", _rows["uiplugin"].toolTip())
check("the placeholder is gone once something was discovered",
      t("plugins.empty") not in [a.text() for a in win._plugin_menu.actions()])
check("the permanent 'Reload' item survived the rebuild (a row rebuild never removes it)",
      win.act_plugins_reload is not None and t("plugins.reload") in
      [a.text() for a in win._plugin_menu.actions()]
      and len([a for a in win._plugin_menu.actions() if a.text() == "uiplugin"]) == 1)

_rows["uiplugin"].setChecked(False)
app.processEvents()
check("unchecking a row switches the plugin off in the manager",
      win._plugin_manager.get("uiplugin").state == PM.STATE_DISABLED)
check("…and persists it in config.json",
      i18n.load_config().get("plugins", {}).get("uiplugin") is False,
      str(i18n.load_config().get("plugins")))
check("…and reports it in the status bar (plugins.status.disabled)",
      win.statusBar().currentMessage() == t("plugins.status.disabled", name="uiplugin"),
      win.statusBar().currentMessage())
_rows2 = {a.text(): a for a in win._plugin_menu.actions() if a.isCheckable()}
_rows2["uiplugin"].setChecked(True)
app.processEvents()
check("checking it back reports plugins.status.enabled and rewrites the config",
      win.statusBar().currentMessage() == t("plugins.status.enabled", name="uiplugin")
      and i18n.load_config().get("plugins", {}).get("uiplugin") is True,
      win.statusBar().currentMessage())

_toggle_count = len([a for a in win._plugin_menu.actions()])
win._populate_plugin_items()
win._populate_plugin_items()
app.processEvents()
check("a repeated rebuild does not duplicate the rows (nor lose Reload)",
      len([a for a in win._plugin_menu.actions()]) == _toggle_count
      and t("plugins.reload") in [a.text() for a in win._plugin_menu.actions()],
      str([a.text() for a in win._plugin_menu.actions()]))

check("'Reload' is a registry action with a real target (the keyboard can reach it)",
      "plugins.reload" in HR.action_ids() and HR.default_sequence("plugins.reload") == ""
      and win.act_plugins_reload in win._hotkey_targets.get("plugins.reload", []))

write_plugin("later", manifest(name="later"))
win.act_plugins_reload.trigger()
app.processEvents()
check("the menu item really re-runs the discovery (a dropped-in file appears)",
      "later" in {a.text() for a in win._plugin_menu.actions() if a.isCheckable()},
      str([a.text() for a in win._plugin_menu.actions()]))
check("a round with a failure keeps the ERROR as the visible status message (not hidden by the round)",
      win.statusBar().currentMessage() == _error_text, win.statusBar().currentMessage())
os.remove(os.path.join(PLUGIN_DIR, "uibroken.py"))
win.act_plugins_reload.trigger()
app.processEvents()
check("a clean reload reports plugins.status.reloaded with the plugin count",
      win.statusBar().currentMessage() == t("plugins.status.reloaded", count=2),
      win.statusBar().currentMessage())

_i18n_ru = load_i18n_langs(ROOT)["ru"]
i18n.set_language("ru")
win._apply_ui_translations()
check("the menu title follows a language switch (the container rule of AGENTS §4.5)",
      win._plugin_menu.title() == _i18n_ru["menu.plugins"],
      f"{win._plugin_menu.title()!r} vs {_i18n_ru['menu.plugins']!r}")
i18n.set_language("en")
win._apply_ui_translations()
check("…and back", win._plugin_menu.title() == "Plugins", win._plugin_menu.title())

win._command_palette._collect_commands()
_palette_labels = [c[0] for c in win._command_palette._commands]
check("the palette (Ctrl+K) picks up the new action and skips the checkable rows",
      t("plugins.reload") in _palette_labels
      and not any(a.isCheckable() and a.text() in _palette_labels
                  for a in win._plugin_menu.actions()),
      str(_palette_labels[-3:]))
clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §8 the wiring: main.py discovers after MainWindow, before app.exec() ==")
# ════════════════════════════════════════════════════════════════════════════

with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
    _main_src = f.read()


def _main_line(statement):
    """The 1-based line of an EXACT statement in main.py (comments never match)."""
    for i, line in enumerate(_main_src.splitlines(), 1):
        if line.strip() == statement:
            return i
    return -1


_main_window_line = _main_line("win = MainWindow()")
_discovery_line = _main_line("win.start_plugin_discovery()")
_loop_line = _main_line("sys.exit(app.exec())")
check("main.py runs the discovery (ROADMAP rc1: after MainWindow creation, before app.exec())",
      _discovery_line > 0 and _main_window_line > 0 and _loop_line > 0,
      f"lines: MainWindow={_main_window_line} discovery={_discovery_line} loop={_loop_line}")
check("the call sits after the MainWindow creation and before the event loop",
      _main_window_line < _discovery_line < _loop_line,
      f"{_main_window_line} < {_discovery_line} < {_loop_line}")
check("the startup path is defensive (a failure is logged, never raised)",
      "Plugin discovery did not run" in _main_src)

# ════════════════════════════════════════════════════════════════════════════
print("== §9 the frozen contract: PLUGINS.md ==")
# ════════════════════════════════════════════════════════════════════════════

with open(PLUGINS_MD, encoding="utf-8") as f:
    _plugins_doc = f.read()
check("PLUGINS.md exists and pins the API version + the entry-point group of the code",
      PM.ENTRY_POINT_GROUP in _plugins_doc and PM.API_VERSION == 1
      and '"api_version": 1' in _plugins_doc,
      PM.ENTRY_POINT_GROUP)
check("the documented MANIFEST keys are the ones the code validates",
      all(k in _plugins_doc for k in ("name", "version", "api_version", "description"))
      and PM.MANIFEST_REQUIRED == ("name", "version"))
check("the documented hook names are the ones the code records",
      all(h in _plugins_doc for h in PM.HOOKS), str(PM.HOOKS))
check("the folder and the config key of the contract match the code",
      "~/.sshmap/plugins" in _plugins_doc and PM.CONFIG_KEY == "plugins")
check("the in-process isolation limitation is documented (ROADMAP: hard isolation is NOT a goal)",
      "segfault" in _plugins_doc.lower() and "in-process" in _plugins_doc.lower())
check("the document marks the rc1 implementation status (examples — rc3)",
      "rc1" in _plugins_doc and "rc3" in _plugins_doc)

# ════════════════════════════════════════════════════════════════════════════
print("== §10 i18n + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
_missing = [k for k in NEW_I18N_KEYS
            if any(not _langs[c].get(k, "").strip() for c in ("en", "ru", "zh", "de"))]
check("the new plugin keys are present and non-empty in en/ru/zh/de",
      not _missing and len(NEW_I18N_KEYS) == 8, str(_missing))
check("the status keys keep their placeholders in every discovered language",
      all("{name}" in _langs[c]["plugins.status.loaded"]
          and "{name}" in _langs[c]["plugins.status.error"]
          and "{error}" in _langs[c]["plugins.status.error"]
          and "{count}" in _langs[c]["plugins.status.reloaded"]
          for c in _langs), "placeholder parity")
check("every new key is in the key set of EVERY language (none missing, none extra)",
      all(set(NEW_I18N_KEYS) <= translation_keys(d) for d in _langs.values()))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check_release_state(ROOT)

restore_entry_points()
finish()
