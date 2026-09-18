# -*- coding: utf-8 -*-
"""v1.4rc1 (plugin foundation, ROADMAP "Plugin foundation" — the rc series): discovery + manager.

The plugin foundation opens the 1.4 line. This module is the FIRST half of it — rc1,
"discovery and manager": the core finds third-party code and keeps a registry of what
it found; the execution side (`PluginContext`, Main Thread isolation, the UI hooks)
arrives in rc2/rc3. The API v1 contract is FROZEN by specification before rc1 —
`PLUGINS.md` is the contract, this module implements its discovery half.

**Two discovery sources** (both are "a plugin is a Python module with a MANIFEST"):

1. **Standard entry points** — a plugin is an ordinary installed Python package
   (`pip install sshmap-<name>-plugin`) declaring

       [project.entry-points."sshmap.plugins/v1"]
       my-plugin = "my_plugin_module"

   This is how pytest/jupyter/flake8 find their plugins: no app-specific packaging
   and no registry file. The GROUP NAME CARRIES THE API VERSION (`/v1`) — a future
   API v2 is a NEW group (`sshmap.plugins/v2`) that lives next to this one, so
   installed plugins keep working (ROADMAP task 0).
2. **The user folder** `~/.sshmap/plugins/*.py` — "a file is a plugin": no packaging,
   no install, works for a user of an INSTALLED app (the v1.3.3.8 language-folder
   precedent). Each file is loaded as a module with a UNIQUE name
   (`sshmap_plugin_local_<stem>`), registered in `sys.modules` so a reload replaces
   it; a file whose name starts with `_` is skipped (a helper of another plugin).

**A module is a plugin if it carries** ``MANIFEST = {"name", "version",
"api_version": 1, "description"}`` — `name` IS the plugin's identity (the id used by
the config and by the "Plugins" menu), `version` is the author's string (the core
never parses it), `api_version` must equal `API_VERSION` and `description` is
optional (missing → ""). The optional HOOKS are `register_commands`,
`extend_node_context_menu`, `status_probe` and `run_on_nodes`; their presence is
recorded in `PluginRecord.hooks` — from rc2/rc3 the hooks a plugin declares are really
CALLED (rc2: `status_probe` + `run_on_nodes`, rc3: the two UI hooks).

**States.** `loaded` (usable) | `disabled` (the user switched it off in the
"Plugins" menu) | `error` (it could not be loaded). An error is NEVER fatal: the
plugin is reported (a log record + one event for the status bar) and the application
plus every other plugin keep working. The three reasons are machine values the UI
translates: `import` (the module could not be imported / the file could not be read),
`manifest` (no `MANIFEST`, not a dict, no usable `name`/`version`), `api_version`
(the manifest declares another API — the contract says the old group stays supported,
so a v2 plugin installed today is simply not a v1 plugin).

**Enable / disable** lives in the `plugins` key of `~/.sshmap/config.json`
(merge-write through `i18n.save_config`, the v1.3.2 hotkeys pattern):
`{"<plugin id>": false}` = switched off, a missing id / a broken value = ENABLED
(a new plugin is on by default), an unknown id in the file is ignored. Only the ids
of the plugins really discovered are written, so the key stays clean.

A DISABLED plugin is still IMPORTED — the core must read its `MANIFEST` to name it in
the menu (a folder plugin's file name is not the plugin's name). What "disabled"
stops is the plugin's HOOKS: rc2/rc3 never call into a disabled record. Documented
in `PLUGINS.md` (the author contract), pinned by `tests/test_plugins.py`.

**v1.4rc2 — the execution half (ROADMAP tasks 5–6).** The discovery above is unchanged;
what rc2 adds is the isolation machinery every call INTO a plugin goes through:

* `PluginContext` (`modules/plugin_context.py`) — the only window into the core, built
  per record by `build_context()` and handed to hooks as `ctx`; its services are the
  three adapter methods of this class (`plugin_log` / `plugin_status` /
  `plugin_run_command`), so the manager stays headless (no widget, no i18n) while the
  window owns the status bar and the token guard.
* **Main Thread discipline.** `call_ui_hook()` invokes a UI hook synchronously and TIMES
  it against the contract budget (200 ms — a slower hook is a warning in the log);
  `call_hook_watched()` invokes a headless hook from whatever worker thread is already
  running (the ordinary use is `status_probe` inside a `StatusChecker` round) and
  ABANDONS it after the wait budget instead of blocking the round; `run_on_nodes()`
  starts every `run_on_nodes` hook on a MANAGED QThread. Anything that outlives the wait
  budget (1500 ms — the v1.2 semantics) is registered in the orphan registry instead of
  being left to GC ("QThread: Destroyed while thread is still running").
* **Never throws.** One wrapper for every path into a plugin: an exception is a log line,
  an event and a status-bar report — never a crash of the host or of a neighbour plugin.
* **Qt objects the manager owns.** `guard(obj)` keeps a reference (the PySide6 6.11
  pitfall of `AGENTS.md` §7 gotcha #9: a dead QAction wrapper takes its C++ menu with
  it) — rc3 hands every QAction a UI hook creates to this guard.

**v1.4rc3 — the UI hooks (ROADMAP tasks 7–8).** The last two hooks become reachable:
`plugin_commands()` returns the `(plugin_id, PluginCommand)` pairs the palette renders
in its own section, `plugin_node_context_menu(menu, node)` lets every plugin append its
rows to a node context menu the window built (map and sidebar — one entry point), and
`plugin_run_on_nodes(nodes)` is the "Run on selected servers" action behind the menu
item. `PluginCommand` (frozen dataclass) is the record of a contributed command; the
coercion of what a hook returned (`plugin_commands()`) is deliberately lenient — a
hand-written plugin may return a nested list, a pair or a dict, and an unusable entry is
SKIPPED with a log line instead of breaking the palette.

"Never raises": every step of the discovery is wrapped — a broken plugin is a record
with a state, never an exception that reaches the startup. The module has no UI and
no i18n: it reports FACTS (records + events + signals), the window turns them into
strings.
"""

import importlib.metadata as importlib_metadata
import importlib.util
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

try:
    from modules.plugin_context import (PluginNode, build_context,
                                        node_record, node_records, run_result_from_dict)
except ImportError:  # a flat launch from inside modules/
    from plugin_context import (PluginNode, build_context,  # type: ignore
                                node_record, node_records, run_result_from_dict)


# ── The contract constants (the discovery half of the frozen API v1) ──────────────

API_VERSION = 1                       # the only API version this core speaks
ENTRY_POINT_GROUP = "sshmap.plugins/v1"   # the group name CARRIES the version (API v2 = /v2)
MANIFEST_ATTR = "MANIFEST"
MANIFEST_REQUIRED = ("name", "version")   # api_version is checked separately, description is optional

HOOK_REGISTER_COMMANDS = "register_commands"
HOOK_NODE_CONTEXT_MENU = "extend_node_context_menu"
HOOK_STATUS_PROBE = "status_probe"
HOOK_RUN_ON_NODES = "run_on_nodes"
HOOKS = (HOOK_REGISTER_COMMANDS, HOOK_NODE_CONTEXT_MENU, HOOK_STATUS_PROBE, HOOK_RUN_ON_NODES)

# Discovery sources (a record carries which one produced it).
SOURCE_ENTRY_POINT = "entry_point"
SOURCE_FOLDER = "folder"

# States.
STATE_LOADED = "loaded"
STATE_DISABLED = "disabled"
STATE_ERROR = "error"

# The machine reasons of an error state — translated by the UI (the i18n.language.*
# precedent: the module reports the reason, the caller builds the sentence).
ERROR_IMPORT = "import"
ERROR_MANIFEST = "manifest"
ERROR_API_VERSION = "api_version"

# The events of a discovery round (a queue the window drains; see drain_events()).
EVENT_LOADED = "loaded"
EVENT_ERROR = "error"
EVENT_DISABLED = "disabled"
EVENT_ENABLED = "enabled"
EVENT_RELOADED = "reloaded"
# v1.4rc2: the events of the EXECUTION half — a hook that raised or was abandoned.
EVENT_HOOK_ERROR = "hook_error"
EVENT_HOOK_TIMEOUT = "hook_timeout"

CONFIG_KEY = "plugins"                # ~/.sshmap/config.json
USER_PLUGIN_DIRNAME = "plugins"       # ~/.sshmap/plugins/
LOCAL_MODULE_PREFIX = "sshmap_plugin_local_"
EVENTS_KEPT = 64                      # a bounded event queue (the window may never drain)
DETAIL_MAX = 400                      # the technical detail kept for the tooltip / the log

# ── v1.4rc2: the budgets of the Main Thread discipline (PLUGINS.md §6) ────────────
HOOK_WAIT_BUDGET_MS = 1500            # a headless hook outliving this is an ORPHAN + a report
UI_HOOK_BUDGET_MS = 200               # a UI hook slower than this is a warning in the log
STATUS_PROBE_BUDGET_MS = 1500         # one plugin's `status_probe` (it runs inside a probe round)
STATUS_DETAIL_MAX = 200               # one plugin's node detail (a tooltip line, not a log)
COMMAND_TIMEOUT_S = 30.0              # the per-node budget of `ctx.run_command`


def _log():
    """The app logger (lazy — the discovery must work in a bare headless script)."""
    try:
        from modules.logger import get_logger
        return get_logger("modules.plugin_manager")
    except Exception:  # noqa: BLE001
        return None


def _log_line(level: str, message: str) -> None:
    """Log without ever raising (the logger may be uninitialized)."""
    logger = _log()
    if logger is None:
        return
    try:
        getattr(logger, level)(message)
    except Exception:  # noqa: BLE001
        pass


def user_plugin_dir() -> str:
    """`~/.sshmap/plugins` — the folder-plugin source (NOT created here)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", USER_PLUGIN_DIRNAME)


def ensure_user_plugin_dir() -> bool:
    """Create `~/.sshmap/plugins` on demand (True = it exists afterwards). Never raises.

    Called by the affordances that need a real folder (an "open the folder" action),
    never by the discovery: a missing folder is simply "no folder plugins".
    """
    try:
        os.makedirs(user_plugin_dir(), exist_ok=True)
        return True
    except OSError:
        return False


def local_plugin_files() -> List[str]:
    """The `*.py` files of the user folder, sorted (`[]` when the folder is absent).

    Files starting with `_` are skipped — the same convention as the suite: a private
    helper of a plugin that is not itself a plugin.
    """
    folder = user_plugin_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names
            if n.endswith(".py") and not n.startswith("_")]


def entry_points(group: str = ENTRY_POINT_GROUP) -> list:
    """The installed entry points of the plugin group ([] on any failure).

    Python 3.10+: `entry_points(group=…)` filters directly. The older dict-like shape
    (a `{group: [EntryPoint, …]}` mapping) is handled as a fallback, so the discovery
    works on any interpreter the application supports. Never raises.
    """
    try:
        found = importlib_metadata.entry_points(group=group)
    except TypeError:                     # a pre-3.10 signature (a mapping was returned)
        try:
            all_points = importlib_metadata.entry_points()
            found = list(getattr(all_points, "get", lambda *_a: []) (group, []))
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001 — a broken installation must not break the startup
        return []
    try:
        return list(found)
    except TypeError:
        return []


@dataclass
class PluginRecord:
    """One discovered plugin — the manager's unit of state.

    `plugin_id` is the MANIFEST `name` (the author's stable identity: the config key
    and the menu row are keyed by it); for an ERROR before the manifest could be read
    it falls back to the entry-point name / the file stem, so a broken plugin still
    has something to show in the menu and in the log.

    v1.4rc2 adds `context` — the `PluginContext` built for this record (the `ctx` a hook
    receives). It is built for a LOADED record only and is deliberately excluded from
    the comparison/repr of the record (it carries a reference to the manager).
    """

    plugin_id: str
    name: str = ""
    version: str = ""
    description: str = ""
    api_version: int = 0
    source: str = SOURCE_FOLDER
    origin: str = ""                  # the file path / "module:value" of the entry point
    state: str = STATE_LOADED
    enabled: bool = True              # the stored user switch (a new plugin is ON by default)
    error: str = ""                   # "" | ERROR_IMPORT | ERROR_MANIFEST | ERROR_API_VERSION
    detail: str = ""                  # the technical detail (a shortened exception text)
    hooks: Tuple[str, ...] = ()
    module: object = field(default=None, repr=False, compare=False)
    context: object = field(default=None, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        """Loaded and enabled — the only records a hook may be called on (rc2/rc3)."""
        return self.state == STATE_LOADED

    @property
    def failed(self) -> bool:
        return self.state == STATE_ERROR

    def label(self) -> str:
        """What the "Plugins" menu shows: the plugin's name (the id as the fallback)."""
        return self.name or self.plugin_id


class _HookWorker(QThread):
    """v1.4rc2: ONE headless hook invocation on a MANAGED worker thread (ROADMAP task 6).

    The ordinary use is `run_on_nodes(nodes, ctx)` — the "run this on the selected
    servers" scenario, whose real work (`ctx.run_command`) is itself another managed
    thread. The worker never touches a widget: it calls the plugin and reports the
    outcome through two signals that the manager connects (delivered queued to the GUI
    thread, because the worker object lives there).
    """

    hook_ok = Signal(str, str)                 # (plugin_id, hook)
    hook_error = Signal(str, str, str)         # (plugin_id, hook, short error text)

    def __init__(self, rec: PluginRecord, hook_name: str, args: tuple, parent=None):
        super().__init__(parent)
        self._rec = rec
        self._hook_name = hook_name
        self._args = args

    @property
    def plugin_id(self) -> str:
        return self._rec.plugin_id

    @property
    def hook_name(self) -> str:
        return self._hook_name

    def run(self):
        fn = getattr(self._rec.module, self._hook_name, None)
        if not callable(fn):
            return
        try:
            fn(*self._args)
        except BaseException as exc:  # noqa: BLE001 — "never throws" (PLUGINS.md §6)
            detail = _short_exc(exc)
            _log_line("error", f"plugin {self._rec.plugin_id!r}: hook {self._hook_name} "
                               f"raised {detail}")
            try:
                self.hook_error.emit(self._rec.plugin_id, self._hook_name, detail)
            except RuntimeError:
                pass
        else:
            try:
                self.hook_ok.emit(self._rec.plugin_id, self._hook_name)
            except RuntimeError:
                pass


def _short_exc(exc) -> str:
    """`TypeName: message`, flattened and capped — never a secret, never a traceback."""
    text = " ".join(str(exc).split())
    detail = f"{type(exc).__name__}: {text}".strip().rstrip(":")
    return detail[:DETAIL_MAX] + "…" if len(detail) > DETAIL_MAX else detail


# ── v1.4rc3: the records of the UI hooks (PLUGINS.md §3) ─────────────────────────

@dataclass(frozen=True)
class PluginCommand:
    """One command a plugin contributes to the command palette (PLUGINS.md §3).

    `text` is the AUTHOR's string — never an i18n key (the core does not translate a
    plugin's text; §7 of the contract). `callback` is called with the plugin context
    when the user runs the command; `description` is optional (a palette hint) and
    `keywords` is optional extra search text. The record is frozen: the core never
    edits what a plugin declared.
    """

    text: str
    callback: object = None
    description: str = ""
    keywords: str = ""

    @property
    def searchable(self) -> str:
        """The text the palette's fuzzy search looks at (`text` + the optional hints)."""
        return " ".join(p for p in (self.text, self.keywords, self.description) if p)


def plugin_commands(value) -> List[PluginCommand]:
    """Coerce whatever `register_commands` returned into a flat list of `PluginCommand`.

    The contract (PLUGINS.md §3) is `-> [PluginCommand]`, and a plugin written by hand
    may return a nested list, a tuple, a `(text, callback)` pair or a small dict — a
    lenient reading costs nothing and turns a typo into a SKIPPED entry (with a log
    line) instead of a broken palette. Anything without usable text is dropped; the
    input is never mutated and nothing raises.
    """
    out: List[PluginCommand] = []

    def _coerce(item):
        if item is None:
            return
        if isinstance(item, PluginCommand):
            if item.text.strip():
                out.append(item)
            return
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("label") or "").strip()
            if text:
                out.append(PluginCommand(text=text, callback=item.get("callback"),
                                         description=str(item.get("description") or ""),
                                         keywords=str(item.get("keywords") or "")))
            return
        if isinstance(item, (list, tuple)):
            if item and not isinstance(item[0], (list, tuple, dict, PluginCommand)):
                # the compact `(text, callback)` pair (a lenient reading of the contract)
                text = str(item[0] or "").strip()
                if text:
                    out.append(PluginCommand(text=text,
                                             callback=item[1] if len(item) > 1 else None))
                return
            for sub in item:          # a nested list of commands
                _coerce(sub)
            return
        _log_line("warning", f"register_commands returned an unusable entry "
                             f"({type(item).__name__}) — skipped")

    if isinstance(value, (list, tuple)):
        for item in value:
            try:
                _coerce(item)
            except Exception:  # noqa: BLE001 — one bad entry never kills the list
                continue
    elif value is not None:
        _log_line("warning", f"register_commands returned {type(value).__name__} "
                             f"instead of a list — ignored")
    return out


# v1.4rc2: the severity ladder of the status merge (PLUGINS.md §3 — "the worse of the
# two by severity"). online < warn < offline, exactly the StatusChecker semantics.
SEVERITY = {"online": 0, "warn": 1, "offline": 2}


def _thread_running(thread) -> bool:
    """True while a thread really runs (QThread.isRunning / Thread.is_alive). Never raises."""
    try:
        if hasattr(thread, "isRunning"):
            return bool(thread.isRunning())
        if hasattr(thread, "is_alive"):
            return bool(thread.is_alive())
    except RuntimeError:
        return False  # Qt teardown — the C++ object is already destroyed
    except Exception:  # noqa: BLE001
        return False
    return False


class PluginManager(QObject):
    """Discovery + the registry of the plugins + the isolation machinery of rc2.

    "Module + callbacks" (the v1.1.4 precedent): the manager knows no window, no menu
    and no scene. It reports records and EVENTS; `MainWindow` renders the menu and the
    status-bar lines from them. `plugins_changed` is emitted after every round, so a
    future consumer (the command palette, rc3) can follow without polling.

    rc2 adds the signals of the execution half (`status_requested`, `hook_failed`,
    `hook_timeout`, `command_result`, `command_finished`) — FACTS the window renders —
    and the two registries of the contract: the MANAGED workers (a QThread the manager
    owns and stops on shutdown) and the ORPHANS (a thread that outlived its wait budget,
    kept alive until it really ends).
    """

    plugins_changed = Signal()
    # v1.4rc2: the services of `PluginContext`, as facts the window turns into widgets.
    status_requested = Signal(str, str, int)      # (plugin_id, text, timeout_ms)
    hook_failed = Signal(str, str, str)           # (plugin_id, hook, detail)
    hook_timeout = Signal(str, str, int)          # (plugin_id, hook, budget_ms)
    command_result = Signal(str, str, dict)       # (plugin_id, node_id, result)
    command_finished = Signal(str, list)          # (plugin_id, results)
    # v1.4: the manager marshals a command start onto ITS OWN thread. The receiver context
    # of a signal connected to a plain Python callable is the thread that calls `connect()`
    # (AGENTS.md §7 gotcha #20), so a runner built inside a `run_on_nodes` worker posts its
    # per-node results into a thread WITHOUT an event loop and they are lost forever — the
    # documented "the callbacks are delivered on the GUI thread" (PLUGINS.md §5) held only
    # for a GUI-thread caller. Emitted on the manager's thread this signal is a direct call;
    # emitted from a plugin's worker it is queued to the manager's thread, which is the one
    # that owns the workers and the event loop their signals need.
    command_requested = Signal(str, list, str, object, object, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: Dict[str, PluginRecord] = {}
        self._events: List[dict] = []
        self._discovered = False
        # v1.4rc2: the registry of the Main Thread discipline (PLUGINS.md §6).
        self._workers: List[QThread] = []            # managed QThreads (self-clean on finished())
        self._orphan_threads: List[object] = []      # outlived the wait budget — kept alive
        self._helper_threads: List[threading.Thread] = []  # watched sync calls (status_probe)
        self._qt_guard: List[object] = []            # QObjects a plugin created (gotcha #9)
        self._nodes: Dict[str, PluginNode] = {}      # the map as plugin node records
        self._node_facts: Dict[str, dict] = {}       # internal-only facts (key_path)
        self._running_commands = 0
        # v1.4: the marshalling of `ctx.run_command` onto this object's thread (see the
        # signal's own comment): a direct call from the GUI thread, a queued one from a
        # plugin's worker — the runner is ALWAYS built where the event loop lives.
        self.command_requested.connect(self._start_command_run)

    # ── the registry ──────────────────────────────────────────────────────────

    def records(self) -> List[PluginRecord]:
        """Every discovered plugin, sorted by id (stable menu order)."""
        return [self._records[k] for k in sorted(self._records)]

    def get(self, plugin_id: str) -> Optional[PluginRecord]:
        """The record of an id (None for an unknown one)."""
        return self._records.get(plugin_id)

    def loaded_records(self) -> List[PluginRecord]:
        """The records a hook may be called on (loaded + enabled) — the rc2/rc3 entry."""
        return [r for r in self.records() if r.ok]

    def is_enabled(self, plugin_id: str) -> bool:
        rec = self._records.get(plugin_id)
        return bool(rec is not None and rec.ok)

    def discovered(self) -> bool:
        """Has a discovery round run at least once (the menu's empty state depends on it)."""
        return self._discovered

    # ── discovery ─────────────────────────────────────────────────────────────

    def discover(self, reloading: bool = False) -> List[PluginRecord]:
        """(Re)build the registry from both sources. Returns the records.

        Entry points first, then the folder: on a NAME conflict the packaged plugin
        wins and the local file is skipped with a log line (ROADMAP rc1 task 1). The
        enable/disable state of `config.json` is applied to the fresh records, and one
        event per plugin (plus one for the round) is queued for the UI. Never raises.
        """
        found: Dict[str, PluginRecord] = {}

        for ep in self._sorted_entry_points():
            rec = self._record_from_entry_point(ep)
            if rec is None:
                continue
            if rec.plugin_id in found:
                _log_line("warning", f"plugin {rec.plugin_id!r} is declared by more than one "
                                     f"entry point — keeping {found[rec.plugin_id].origin}")
                continue
            found[rec.plugin_id] = rec

        for path in local_plugin_files():
            rec = self._record_from_file(path)
            if rec is None:
                continue
            if rec.plugin_id in found:
                # The packaged plugin wins (ROADMAP rc1 task 1) — a local override of an
                # installed plugin is NOT a feature: two plugins with one identity would
                # both be listed and both be switched by one config key.
                _log_line("warning", f"local plugin {path} skipped: the id {rec.plugin_id!r} "
                                     f"is already provided by {found[rec.plugin_id].origin}")
                continue
            found[rec.plugin_id] = rec

        self._records = found
        self._discovered = True
        self._apply_config_state()
        self._queue_round_events(reloading)
        try:
            self.plugins_changed.emit()
        except RuntimeError:
            pass  # Qt teardown — the signal has no receiver left
        _log_line("info", f"plugin discovery: {len(found)} found "
                          f"({len(self.loaded_records())} loaded, "
                          f"{sum(1 for r in found.values() if r.failed)} failed, "
                          f"{sum(1 for r in found.values() if r.state == STATE_DISABLED)} disabled)"
                          + (" [reload]" if reloading else ""))
        return self.records()

    def reload(self) -> List[PluginRecord]:
        """Re-run the discovery (the "Reload" menu item) — new/changed `.py` files are picked up.

        The folder half is why this exists: each file is exec'd fresh under its unique
        module name (see `_load_local_module`), so an edited plugin is really re-read
        without a restart (`sys.modules` is replaced, not consulted). An installed
        package is left to Python's import system, which is what `Reload` documents.
        """
        return self.discover(reloading=True)

    # ── enable / disable ──────────────────────────────────────────────────────

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """Switch a plugin on/off and persist it in `plugins` of `config.json`.

        Returns False for an unknown id or an ERROR record (a broken plugin has nothing
        to switch). The whole mapping of the CURRENT discovered ids is written (the
        `save_hotkeys` precedent) — a broken/unknown value in the file is dropped here.
        Never raises.
        """
        rec = self._records.get(plugin_id)
        if rec is None or rec.failed:
            return False
        wanted = bool(enabled)
        rec.enabled = wanted
        rec.state = STATE_LOADED if wanted else STATE_DISABLED
        saved = self._save_config_state()
        self._push_event(EVENT_ENABLED if wanted else EVENT_DISABLED, rec)
        try:
            self.plugins_changed.emit()
        except RuntimeError:
            pass
        _log_line("info", f"plugin {plugin_id!r} {'enabled' if wanted else 'disabled'}"
                          + ("" if saved else " (config.json write failed)"))
        return True

    # ── v1.4rc2: the nodes a plugin may see (PLUGINS.md §5) ───────────────────
    # The window feeds the current map here (the same pass that syncs the status
    # checker targets); `status_probe` and the node records of `run_on_nodes` come from
    # this registry, and the internal FACTS (a private key path — never part of the
    # plugin-visible record) are kept separately for the credential resolver.

    def set_nodes(self, nodes, facts: Optional[Dict[str, dict]] = None) -> List[PluginNode]:
        """Replace the plugin-visible node registry; returns the records stored.

        `nodes` — anything node-like (`ServerData`, a dict, a tuple, a `PluginNode`): it
        is NARROWED to `{id, alias, host, port, user}` here, at the boundary. `facts` —
        optional internal data per node id (today: `key_path`), used by the credential
        resolver of `ctx.run_command` and never exposed to a plugin. Never raises.
        """
        records: Dict[str, PluginNode] = {}
        for node in node_records(nodes):
            if node.id:
                records[node.id] = node
        self._nodes = records
        if isinstance(facts, dict):
            self._node_facts = {str(k): (v if isinstance(v, dict) else {}) for k, v in facts.items()}
        return list(records.values())

    def node_records(self) -> List[PluginNode]:
        """The current plugin-visible node records, sorted by id (a stable order)."""
        return [self._nodes[k] for k in sorted(self._nodes)]

    def node_record(self, node_id: str) -> Optional[PluginNode]:
        """One record by id (None for an unknown id — e.g. a node removed from the map)."""
        return self._nodes.get(node_id)

    # ── v1.4rc2: the PluginContext services (the adapter of modules/plugin_context.py) ──

    def plugin_log(self, plugin_id: str, message) -> None:
        """`ctx.log()` — one line into the application log, prefixed with the plugin id."""
        _log_line("info", f"[plugin {plugin_id}] {message}")

    def plugin_status(self, plugin_id: str, text, timeout_ms: int = 5000) -> bool:
        """`ctx.status()` — a status-bar line (a signal: the window owns the widget).

        Emitting from any thread is safe (Qt delivers it to the window's thread), which
        is what makes the service usable from a plugin's worker callback. The token guard
        lives in the window (`MainWindow._on_plugin_status_requested`).
        """
        try:
            timeout = int(timeout_ms)
        except (TypeError, ValueError):
            timeout = 5000
        try:
            self.status_requested.emit(str(plugin_id or ""), str(text), max(0, timeout))
            return True
        except RuntimeError:
            return False  # Qt teardown — no receiver left

    # ── v1.4rc3: the UI hooks (PLUGINS.md §3, ROADMAP task 7) ─────────────────
    # Two of the four hooks build UI, and the core builds it FOR the plugin: the
    # manager stays headless (no menu, no widget) and hands out exactly two things —
    # the RECORDS of the commands a plugin declared and a way to APPEND rows to a menu
    # the window already created. Everything Qt-shaped stays in the window, including
    # the QAction guard (gotcha #9: a dead Python wrapper takes its C++ menu with it).
    # Both paths call `call_ui_hook()` — synchronous, on the GUI thread, timed against
    # the contract's 200 ms budget, and "never throws" (an exception is a report).

    def plugin_commands(self) -> List[Tuple[str, PluginCommand]]:
        """`(plugin_id, command)` for every command of every loaded plugin, in order.

        The palette (Ctrl+K) renders one row per pair in its own section, AFTER the
        built-in commands — a plugin can never shadow a core command (PLUGINS.md §3).
        A plugin that is disabled, failed or has no `register_commands` hook is skipped;
        a hook that raises / is too slow is reported by `call_ui_hook()` and contributes
        nothing. Never raises.
        """
        out: List[Tuple[str, PluginCommand]] = []
        for rec in self._loaded_with_hook(HOOK_REGISTER_COMMANDS):
            ctx = self._context_for(rec)
            try:
                raw = self.call_ui_hook(rec, HOOK_REGISTER_COMMANDS, ctx)
            except Exception:  # noqa: BLE001 — call_ui_hook already wraps; belt and braces
                continue
            for cmd in plugin_commands(raw):
                out.append((rec.plugin_id, cmd))
        return out

    def plugin_node_context_menu(self, menu, node=None) -> int:
        """Let every loaded plugin append its rows to a node context menu (ROADMAP task 7).

        `menu` is the live `QMenu` the window (map) or the sidebar panel created;
        `node` is ONE node-like value (`ServerData`, a `PluginNode`, a node id) or an
        iterable of them. The menu is filled through `PluginManager.call_ui_hook()`,
        i.e. synchronously on the GUI thread inside the 200 ms budget.

        Returns how many plugins were asked. The QActions a hook creates belong to the
        MANAGER (PLUGINS.md §6): the caller must guard them (the window re-runs
        `_rebuild_qaction_guard()` right after this call), because a garbage-collected
        Python QAction wrapper destroys the C++ menu behind it (gotcha #9). Never raises.
        """
        if menu is None:
            return 0
        records = self._menu_node_records(node)
        asked = 0
        for rec in self._loaded_with_hook(HOOK_NODE_CONTEXT_MENU):
            try:
                self.call_ui_hook(rec, HOOK_NODE_CONTEXT_MENU, menu, records)
            except Exception:  # noqa: BLE001 — the hook path is wrapped; keep the menu alive
                continue
            asked += 1
        return asked

    def plugin_run_on_nodes(self, nodes=None) -> int:
        """Run "put this on the selected servers" — `run_on_nodes` on every loaded plugin.

        The window's entry point behind the "Run on selected servers" action: the nodes
        are the user's selection (or the whole registry when nothing is selected) and the
        manager starts ONE managed worker per plugin that declares the hook (rc2
        machinery — `ctx.run_command` inside the hook gets its own managed worker, and
        `shutdown()` waits for all of them). Returns the number of plugins started.

        An action the user triggered must never fail silently: with no plugin
        implementing the hook an ERROR line is logged (the status bar has nothing to
        report — the window disables the menu item in that case). Never raises.
        """
        started = int(self.run_on_nodes(nodes))
        if started == 0:
            _log_line("warning", "run_on_nodes: no loaded plugin implements the hook — "
                                 "nothing was run")
        return started

    def _loaded_with_hook(self, hook_name: str) -> List[PluginRecord]:
        """The loaded + enabled records that really declare a hook (stable id order)."""
        return [r for r in self.loaded_records() if hook_name in r.hooks]

    def _context_for(self, rec: PluginRecord):
        """The context of a record (built lazily) — what a hook receives as `ctx`."""
        return rec.context or build_context(rec.plugin_id, core=self, api_version=API_VERSION)

    def _menu_node_records(self, node) -> List[PluginNode]:
        """The records a context-menu hook sees, from whatever the caller has at hand.

        Three shapes reach this method: an iterable of nodes (a map multi-selection),
        ONE node-like value (a `ServerData`, a map `ServerNode`, a `PluginNode`) and a
        NODE ID (the sidebar knows nothing but the row's id). All of them end in
        `node_records()`; an id that the registry does not know (a node removed from the
        map while the menu was open) simply yields nothing.
        """
        if node is None:
            return []
        if isinstance(node, (list, tuple, set, frozenset)):
            return node_records(node)
        if isinstance(node, (PluginNode, dict)):
            return node_records([node])
        if isinstance(node, str):
            record = self._nodes.get(node)
            return [record] if record is not None else []
        return node_records([node])

    def plugin_run_command(self, plugin_id: str, nodes, command: str,
                           on_result=None, on_finished=None,
                           timeout: float = COMMAND_TIMEOUT_S) -> bool:
        """`ctx.run_command()` — one managed SSH worker per call (ROADMAP task 5).

        The credentials are resolved by the core (`modules/plugin_runner.py`), the results
        arrive per node, and the plugin's callbacks are invoked on the GUI thread. One
        node's failure is a RESULT for that node — the other nodes still run. False when
        the call could not start at all (no nodes, an empty command, a dead Qt object).

        v1.4: the call is MARSHALLED onto the manager's own thread (`command_requested`),
        because a plugin reaches this service from a `run_on_nodes` WORKER as often as
        from a GUI-thread command — and a runner built in a thread without an event loop
        would deliver its per-node results nowhere (AGENTS.md §7 gotcha #20). From the GUI
        thread the signal is a direct call, so nothing about the ordinary path changed.
        """
        records = node_records(nodes)
        if not records or not str(command or "").strip():
            return False
        try:
            budget = max(0.2, float(timeout))
        except (TypeError, ValueError):
            budget = COMMAND_TIMEOUT_S
        try:
            self.command_requested.emit(str(plugin_id or ""), records, str(command),
                                        on_result if callable(on_result) else None,
                                        on_finished if callable(on_finished) else None,
                                        budget)
        except RuntimeError:
            return False      # Qt teardown — the signal has no receiver left
        return True

    def _start_command_run(self, plugin_id: str, records: list, command: str,
                           on_result, on_finished, timeout: float) -> bool:
        """Build + start the runner — the slot of `command_requested` (the manager's thread).

        Everything that talks to Qt about the call happens here: the signals of the fresh
        `PluginCommandRunner` are connected in THIS thread (the rule that makes their
        delivery work at all), the worker joins the managed registry and the plugin's
        callbacks are wrapped so a plugin's own exception can never reach the host.
        """
        try:
            from modules.plugin_runner import PluginCommandRunner
        except ImportError:  # a flat launch from inside modules/
            from plugin_runner import PluginCommandRunner  # type: ignore

        try:
            runner = PluginCommandRunner(records, command, plugin_id=str(plugin_id or ""),
                                         timeout=timeout, node_facts=self._node_facts, parent=self)
        except Exception as e:  # noqa: BLE001 — a failed start is a log line, not an exception
            _log_line("warning", f"plugin {plugin_id!r}: run_command could not start: {e!r}")
            return False

        def _deliver(node_id: str, payload: dict):
            result = run_result_from_dict(payload)
            node = result.node
            try:
                self.command_result.emit(str(plugin_id or ""), str(node_id), dict(payload))
            except RuntimeError:
                pass
            if callable(on_result):
                try:
                    on_result(node, result)
                except BaseException as exc:  # noqa: BLE001 — the plugin's own callback
                    self._report_hook_error(str(plugin_id or ""), "run_command.on_result", exc)

        def _deliver_finished(payloads: list):
            results = [run_result_from_dict(p) for p in (payloads or [])]
            try:
                self.command_finished.emit(str(plugin_id or ""), list(payloads or []))
            except RuntimeError:
                pass
            if callable(on_finished):
                try:
                    on_finished(results)
                except BaseException as exc:  # noqa: BLE001 — the plugin's own callback
                    self._report_hook_error(str(plugin_id or ""), "run_command.on_finished", exc)

        runner.node_result.connect(_deliver)
        runner.all_finished.connect(_deliver_finished)
        self._running_commands += 1

        def _on_runner_done():
            self._running_commands = max(0, self._running_commands - 1)

        runner.finished.connect(_on_runner_done)
        self._register_worker(runner)
        runner.start()
        _log_line("info", f"plugin {plugin_id!r}: run_command on {len(records)} node(s) started")
        return True

    # ── v1.4rc2: calling INTO a plugin (the isolation rules, PLUGINS.md §6) ────

    def call_ui_hook(self, record, hook_name: str, *args):
        """Call a UI hook SYNCHRONOUSLY on the GUI thread, timed against the 200 ms budget.

        The contract's budget is a promise the core can check and the plugin cannot: a
        hook that takes longer is not interrupted (a synchronous call cannot be abandoned
        safely), it is a WARNING in the log — the author's signal that the hook does IO or
        network that belongs on a worker thread. Returns the hook's value, or None when the
        plugin has no such hook / it raised. Never throws.
        """
        rec = self._as_record(record)
        if rec is None or not rec.ok:
            return None
        fn = getattr(rec.module, hook_name, None)
        if not callable(fn):
            return None
        started = time.monotonic()
        try:
            return fn(*args)
        except BaseException as exc:  # noqa: BLE001 — a hook never propagates (PLUGINS.md §3)
            self._report_hook_error(rec.plugin_id, hook_name, exc)
            return None
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms > UI_HOOK_BUDGET_MS:
                _log_line("warning", f"plugin {rec.plugin_id!r}: UI hook {hook_name} took "
                                     f"{elapsed_ms} ms (the contract budget is "
                                     f"{UI_HOOK_BUDGET_MS} ms — no IO on the GUI thread)")

    def call_hook_wrapped(self, record, hook_name: str, callback, *args):
        """Call a PLUGIN-SUPPLIED callback (not a hook of the module) under the wrapper.

        `register_commands` hands the core its callbacks instead of running them: the
        palette runs the chosen one via this method, so the "never throws" rule applies
        to a plugin's own command exactly as it does to a hook — an exception is a log
        line and a report (`hook_failed` → a status-bar line), never a broken palette.
        The call is timed against the UI budget like any other GUI-thread call into a
        plugin. Returns the callback's value, or None when it is not callable / it raised.
        """
        rec = self._as_record(record)
        plugin_id = rec.plugin_id if rec is not None else str(record or "")
        if not callable(callback):
            return None
        started = time.monotonic()
        try:
            return callback(*args)
        except BaseException as exc:  # noqa: BLE001 — a plugin's code never propagates
            self._report_hook_error(plugin_id, hook_name, exc)
            return None
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms > UI_HOOK_BUDGET_MS:
                _log_line("warning", f"plugin {plugin_id!r}: {hook_name} callback took "
                                     f"{elapsed_ms} ms (the contract budget is "
                                     f"{UI_HOOK_BUDGET_MS} ms — no IO on the GUI thread)")

    def call_hook_watched(self, record, hook_name: str, *args,
                          budget_ms: int = HOOK_WAIT_BUDGET_MS):
        """Call a headless hook on a watched helper thread, ABANDON it after the budget.

        This is the shape `status_probe` needs: the caller is already a worker thread (a
        `StatusChecker` round) and must get an answer NOW — a hung plugin must not hang
        the round, the map updates, or the shutdown. The call runs on a plain
        `threading.Thread` (no Qt object is created there), the caller waits at most
        `budget_ms`, and a thread that outlives it becomes an ORPHAN: it is kept in the
        registry until it really ends and the timeout is reported (a log line, an event
        and a signal). Returns the hook's value, or None ("no opinion" / too slow / raised).
        """
        rec = self._as_record(record)
        if rec is None or not rec.ok:
            return None
        fn = getattr(rec.module, hook_name, None)
        if not callable(fn):
            return None
        box: Dict[str, object] = {}
        done = threading.Event()

        def _target():
            try:
                box["value"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001 — never propagates
                box["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=_target, daemon=True,
                                  name=f"sshmap-plugin-{rec.plugin_id}-{hook_name}")
        self._helper_threads.append(thread)
        try:
            thread.start()
        except RuntimeError as exc:  # a thread that cannot start at all
            self._helper_threads.remove(thread)
            self._report_hook_error(rec.plugin_id, hook_name, exc)
            return None
        finished = done.wait(max(0.0, float(budget_ms) / 1000.0))
        if not finished:
            self._report_hook_timeout(rec.plugin_id, hook_name, int(budget_ms))
            return None
        self._prune_helpers()
        error = box.get("error")
        if error is not None:
            self._report_hook_error(rec.plugin_id, hook_name, error)
            return None
        return box.get("value")

    def run_on_nodes(self, nodes=None) -> int:
        """Start the `run_on_nodes` hook of EVERY loaded plugin (a managed worker each).

        `nodes` defaults to the registry `set_nodes()` filled. Returns the number of
        plugins the call was started for (0 — no plugin implements the hook). The hooks
        run on managed QThreads; the work they start (`ctx.run_command`) has its own
        managed workers, and `shutdown()` waits for all of them with the wait budget.
        """
        records = node_records(nodes) if nodes is not None else self.node_records()
        if not records:
            return 0
        started = 0
        for rec in self._loaded_with_hook(HOOK_RUN_ON_NODES):
            worker = _HookWorker(rec, HOOK_RUN_ON_NODES,
                                 (records, self._context_for(rec)), parent=self)
            worker.hook_error.connect(self._on_hook_error)
            self._register_worker(worker)
            worker.start()
            started += 1
        if started:
            _log_line("info", f"run_on_nodes: started on {len(records)} node(s) "
                              f"for {started} plugin(s)")
        return started

    # ── v1.4rc2: the status_probe merge (PLUGINS.md §3) ───────────────────────

    def status_probe_for(self, node, ssh_status: str = "") -> Optional[Tuple[str, str]]:
        """The merged opinion of the plugins about ONE node — `(kind, detail)` or None.

        Called from a `StatusChecker` probe worker (never from the GUI thread). Every
        loaded plugin that declares `status_probe` is asked with the plugin-visible node
        record; a plugin that raises, hangs or answers with a foreign kind is skipped with
        its own report. `ssh_status` (the SSH probe's own result) joins the merge: the
        result is the WORSE of the two by severity and the details are concatenated.
        Returns None when no plugin had an opinion (the SSH probe's result stands alone).
        """
        rec = node_record(node)
        if not rec.id:
            return None
        kinds: List[str] = []
        details: List[str] = []
        if ssh_status in SEVERITY:
            kinds.append(ssh_status)
        for plugin_rec in self.loaded_records():
            if HOOK_STATUS_PROBE not in plugin_rec.hooks:
                continue
            answer = self.call_hook_watched(plugin_rec, HOOK_STATUS_PROBE, rec,
                                            budget_ms=STATUS_PROBE_BUDGET_MS)
            parsed = self._parse_probe_answer(plugin_rec.plugin_id, answer)
            if parsed is None:
                continue
            kind, detail = parsed
            kinds.append(kind)
            if detail:
                details.append(detail)
        if not kinds:
            return None
        worst = max(kinds, key=lambda k: SEVERITY.get(k, 0))
        detail = " · ".join(d for d in details if d)[:STATUS_DETAIL_MAX]
        return worst, detail

    def _parse_probe_answer(self, plugin_id: str, answer) -> Optional[Tuple[str, str]]:
        """`status_probe`'s answer → `(kind, detail)` or None ("no opinion").

        The contract (PLUGINS.md §3) allows `(kind, detail) | None`; a bare string is
        accepted as a kind-only answer for a lenient reading of it, while an unknown kind
        is NOT guessed at — it is a warning in the log and "no opinion", so a plugin can
        never invent a status the application does not have.
        """
        if answer is None:
            return None
        detail = ""
        if isinstance(answer, (tuple, list)) and answer:
            kind = str(answer[0] or "").strip().lower()
            if len(answer) > 1 and answer[1] is not None:
                detail = " ".join(str(answer[1]).split())
        elif isinstance(answer, str):
            kind = answer.strip().lower()
        else:
            _log_line("warning", f"plugin {plugin_id!r}: status_probe returned "
                                 f"{type(answer).__name__} — ignored")
            return None
        if kind not in SEVERITY:
            _log_line("warning", f"plugin {plugin_id!r}: status_probe returned the unknown "
                                 f"kind {kind!r} — ignored")
            return None
        return kind, detail[:STATUS_DETAIL_MAX]

    def status_provider(self, server_id: str, ssh_status: str = "") -> Optional[Tuple[str, str]]:
        """The `StatusChecker` seam: `(kind, detail)` for a server id (None = no opinion)."""
        node = self._nodes.get(str(server_id))
        if node is None:
            return None
        try:
            return self.status_probe_for(node, ssh_status)
        except Exception as e:  # noqa: BLE001 — a probe round must never break on a plugin
            _log_line("warning", f"status_probe merge failed for {server_id!r}: {e!r}")
            return None

    # ── v1.4rc2: the Qt guard (the manager owns what a plugin creates) ─────────

    def guard(self, obj):
        """Keep a reference to a QObject a plugin created (gotcha #9 pattern).

        PySide6 6.11 destroys the C++ object behind a dead Python wrapper — for a QAction
        with an attached QMenu that takes the whole menu down. A plugin handing its
        objects here (or the core doing it for a UI hook) keeps them immortal. Returns
        the object, so `act = manager.guard(QAction(...))` reads naturally.
        """
        if obj is not None and obj not in self._qt_guard:
            self._qt_guard.append(obj)
        return obj

    def guarded_objects(self) -> list:
        """The objects the manager currently keeps alive (a test/diagnostic seam)."""
        return list(self._qt_guard)

    def release_guards(self) -> int:
        """Drop every guarded reference (a plugin reload); returns how many were dropped."""
        count = len(self._qt_guard)
        self._qt_guard = []
        return count

    # ── v1.4rc2: the worker registries + shutdown ─────────────────────────────

    def _register_worker(self, thread: QThread) -> None:
        """Track a managed worker; it removes ITSELF on `finished()` (self-cleanup)."""
        self._workers.append(thread)

        def _cleanup(*_a, th=thread):
            try:
                if th in self._workers:
                    self._workers.remove(th)
            except Exception:  # noqa: BLE001
                pass

        try:
            thread.finished.connect(_cleanup)
        except Exception:  # noqa: BLE001 — an exotic object; the prune in shutdown() covers it
            pass

    def active_workers(self) -> list:
        """The managed workers still running (the registry, pruned)."""
        return [th for th in self._workers if _thread_running(th)]

    def orphan_threads(self) -> list:
        """The threads that outlived a wait budget and are kept alive until they end."""
        self._prune_orphans()
        return list(self._orphan_threads)

    def helper_threads(self) -> list:
        """The watched helper threads still alive (pruned on read) — a diagnostic seam.

        A `call_hook_watched` that timed out leaves its helper here until the hook really
        returns: the reference is what keeps a live thread from being collected.
        """
        self._prune_helpers()
        return list(self._helper_threads)

    def running_commands(self) -> int:
        """How many `ctx.run_command` calls are in flight (a diagnostic seam)."""
        return int(self._running_commands)

    def shutdown(self, wait_ms: int = HOOK_WAIT_BUDGET_MS) -> bool:
        """Stop every managed worker with a bounded wait (the ROADMAP rc2 acceptance).

        Each worker is asked to stop (`stop()` when it has one — the command runner does,
        `requestInterruption()` otherwise) and then waited on until the shared deadline.
        A thread that outlives it is moved into the ORPHAN registry instead of being
        destroyed with its parent ("QThread: Destroyed while thread is still running").
        Returns True when everything finished within the budget. Never raises.
        """
        self._prune_orphans()
        self._prune_helpers()
        budget_ms = max(1, int(wait_ms))
        deadline = time.monotonic() + budget_ms / 1000.0
        clean = True
        for thread in list(self._workers):
            try:
                stop = getattr(thread, "stop", None)
                if callable(stop):
                    try:
                        stop(min(budget_ms, max(1, int((deadline - time.monotonic()) * 1000))))
                    except TypeError:
                        stop()
                    except Exception:  # noqa: BLE001
                        pass
                elif hasattr(thread, "requestInterruption"):
                    thread.requestInterruption()
            except Exception:  # noqa: BLE001
                pass
            remaining = int(max(0.0, deadline - time.monotonic()) * 1000)
            finished = False
            try:
                finished = bool(thread.wait(max(1, remaining))) if _thread_running(thread) else True
            except Exception:  # noqa: BLE001
                finished = True
            if not finished:
                clean = False
                self._orphan(thread)
        for helper in list(self._helper_threads):
            if helper.is_alive():
                clean = False
                self._orphan(helper)
        # Everything that is still alive is an ORPHAN now: the orphan registry is the
        # only owner a live thread may have (the managed list must not hold a thread the
        # manager no longer waits for).
        self._workers = []
        _log_line("info", f"plugin workers stopped "
                          f"({len(self._orphan_threads)} orphan(s) kept alive)")
        return clean

    def _orphan(self, thread) -> None:
        """Register a live thread that outlived its budget (kept until it really ends)."""
        if thread not in self._orphan_threads:
            self._orphan_threads.append(thread)
            _log_line("warning", f"plugin worker did not finish within the wait budget — "
                                 f"registered as an orphan: {thread!r}")

    def _prune_orphans(self) -> None:
        """Drop orphans that finished (the self-cleanup the live ones cannot do for us)."""
        self._orphan_threads = [th for th in self._orphan_threads if _thread_running(th)]

    def _prune_helpers(self) -> None:
        """Drop watched helper threads that ended (a hung helper is kept until it does)."""
        self._helper_threads = [th for th in self._helper_threads if th.is_alive()]

    # ── v1.4rc2: the reports of a failed / abandoned hook ────────────────────

    def _on_hook_error(self, plugin_id: str, hook_name: str, detail: str) -> None:
        """A managed worker's hook raised (delivered queued to the GUI thread)."""
        rec = self._records.get(plugin_id)
        self._push_event(EVENT_HOOK_ERROR, rec, hook=hook_name, error=detail)
        try:
            self.hook_failed.emit(str(plugin_id), str(hook_name), str(detail))
        except RuntimeError:
            pass

    def _report_hook_error(self, plugin_id: str, hook_name: str, exc) -> None:
        """Report a synchronous / watched call that raised — log + event + signal."""
        detail = _short_exc(exc)
        _log_line("error", f"plugin {plugin_id!r}: hook {hook_name} raised {detail}")
        self._push_event(EVENT_HOOK_ERROR, self._records.get(plugin_id),
                         hook=hook_name, error=detail)
        try:
            self.hook_failed.emit(str(plugin_id), str(hook_name), detail)
        except RuntimeError:
            pass

    def _report_hook_timeout(self, plugin_id: str, hook_name: str, budget_ms: int) -> None:
        """Report a hook that was abandoned after the budget — log + event + signal."""
        _log_line("warning", f"plugin {plugin_id!r}: hook {hook_name} did not return within "
                             f"{budget_ms} ms — abandoned (the application keeps living)")
        self._push_event(EVENT_HOOK_TIMEOUT, self._records.get(plugin_id),
                         hook=hook_name, budget_ms=int(budget_ms))
        try:
            self.hook_timeout.emit(str(plugin_id), str(hook_name), int(budget_ms))
        except RuntimeError:
            pass

    def _as_record(self, record) -> Optional[PluginRecord]:
        """Accept a record or a plugin id (None when it is unknown / not loaded)."""
        if isinstance(record, PluginRecord):
            return record
        if isinstance(record, str):
            return self._records.get(record)
        return None

    # ── the event queue (the status-bar lines) ────────────────────────────────

    def drain_events(self) -> List[dict]:
        """Take the events queued since the last call (`{"kind", "record", "count"?}`)."""
        events, self._events = self._events, []
        return events

    def _push_event(self, kind: str, record: Optional[PluginRecord], **extra) -> None:
        payload = {"kind": kind, "record": record}
        payload.update(extra)
        self._events.append(payload)
        if len(self._events) > EVENTS_KEPT:      # bounded — a window that never drains
            del self._events[:-EVENTS_KEPT]

    # ── the sources (each returns a record or None = "not a plugin at all") ───

    def _sorted_entry_points(self) -> list:
        """The group's entry points in a deterministic order (by name, then value)."""
        points = entry_points()

        def key(ep):
            return (str(getattr(ep, "name", "")), str(getattr(ep, "value", "")))

        try:
            return sorted(points, key=key)
        except Exception:  # noqa: BLE001 — an exotic object in the list
            return points

    def _record_from_entry_point(self, ep) -> Optional[PluginRecord]:
        """Load one entry point → a record (an error record, never an exception)."""
        ep_name = str(getattr(ep, "name", "") or "?")
        try:
            value = str(getattr(ep, "value", "") or "")
        except Exception:  # noqa: BLE001
            value = ""
        origin = f"{ep_name} = {value}" if value else ep_name
        try:
            obj = ep.load()
        except BaseException as exc:  # noqa: BLE001 — a plugin's import may raise ANYTHING
            return self._error_record(ep_name, SOURCE_ENTRY_POINT, origin, ERROR_IMPORT, exc)
        return self._record_from_module(obj, ep_name, SOURCE_ENTRY_POINT, origin)

    def _record_from_file(self, path: str) -> Optional[PluginRecord]:
        """Load one `~/.sshmap/plugins/*.py` → a record."""
        fallback_id = os.path.splitext(os.path.basename(path))[0]
        try:
            module = self._load_local_module(path)
        except BaseException as exc:  # noqa: BLE001 — SyntaxError / ImportError / anything
            return self._error_record(fallback_id, SOURCE_FOLDER, path, ERROR_IMPORT, exc)
        return self._record_from_module(module, fallback_id, SOURCE_FOLDER, path)

    def _load_local_module(self, path: str):
        """Exec a folder plugin as a uniquely NAMED module (a reload really re-reads it).

        The name is `sshmap_plugin_local_<sanitized stem>`: stable for a file (so a
        reload REPLACES its `sys.modules` entry instead of leaking a new module on
        every round) and valid as an identifier (a file may be called `my-plugin.py`).
        The module is deliberately NOT a package: a folder plugin is ONE file, so a
        relative import has nothing to resolve against (`PLUGINS.md`, the author rules).
        """
        stem = os.path.splitext(os.path.basename(path))[0]
        safe = re.sub(r"\W", "_", stem) or "plugin"
        module_name = f"{LOCAL_MODULE_PREFIX}{safe}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot build an import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # A half-imported module must not stay in sys.modules (or a later file with
            # the same name would get the corpse back from the import cache).
            sys.modules.pop(module_name, None)
            raise
        return module

    def _record_from_module(self, obj, fallback_id: str, source: str, origin: str):
        """Validate the MANIFEST of a loaded object → a loaded record or an error record."""
        manifest = getattr(obj, MANIFEST_ATTR, None)
        if manifest is None:
            return self._error_record(fallback_id, source, origin, ERROR_MANIFEST,
                                      ValueError(f"no {MANIFEST_ATTR} attribute"))
        if not isinstance(manifest, dict):
            return self._error_record(fallback_id, source, origin, ERROR_MANIFEST,
                                      TypeError(f"{MANIFEST_ATTR} is {type(manifest).__name__}, not a dict"))

        name = manifest.get("name")
        version = manifest.get("version")
        if not isinstance(name, str) or not name.strip():
            return self._error_record(fallback_id, source, origin, ERROR_MANIFEST,
                                      ValueError(f"{MANIFEST_ATTR} has no usable \"name\""))
        if not isinstance(version, str) or not version.strip():
            return self._error_record(name.strip(), source, origin, ERROR_MANIFEST,
                                      ValueError(f"{MANIFEST_ATTR} has no usable \"version\""))
        plugin_id = name.strip()

        api = manifest.get("api_version")
        if api != API_VERSION:
            return self._error_record(plugin_id, source, origin, ERROR_API_VERSION,
                                      ValueError(f"api_version {api!r} != {API_VERSION}"),
                                      name=plugin_id, version=version.strip())

        description = manifest.get("description")
        hooks = tuple(h for h in HOOKS if callable(getattr(obj, h, None)))
        # v1.4rc2: the record's context — the ONLY object a hook receives besides its
        # arguments (PLUGINS.md §5). A disabled plugin still gets one: the switch stops
        # the hooks, not the record (and rc3's palette reads the commands of a plugin
        # union of loaded records only).
        context = build_context(plugin_id, core=self, api_version=API_VERSION)
        return PluginRecord(
            plugin_id=plugin_id,
            name=plugin_id,
            version=version.strip(),
            description=description.strip() if isinstance(description, str) else "",
            api_version=API_VERSION,
            source=source,
            origin=origin,
            state=STATE_LOADED,
            hooks=hooks,
            module=obj,
            context=context,
        )

    def _error_record(self, plugin_id: str, source: str, origin: str, reason: str, exc,
                      name: str = "", version: str = "") -> PluginRecord:
        """Build + LOG an error record (the "a record in modules/logger.py" of the ROADMAP).

        `name`/`version` are filled when the manifest WAS readable (a foreign api_version):
        a half-valid plugin still shows its own identity in the menu and in the log.
        """
        detail = f"{type(exc).__name__}: {exc}".strip()
        if len(detail) > DETAIL_MAX:
            detail = detail[:DETAIL_MAX] + "…"
        rec = PluginRecord(plugin_id=plugin_id or "?", name=name or plugin_id or "?",
                           version=version or "", source=source, origin=origin,
                           state=STATE_ERROR, error=reason, detail=detail)
        _log_line("error", f"plugin {rec.plugin_id!r} failed to load ({reason}, {source}) "
                           f"from {origin}: {detail}")
        return rec

    # ── the config (`plugins` in ~/.sshmap/config.json) ───────────────────────

    def _load_config_state(self) -> Dict[str, bool]:
        """The stored `plugins` mapping, cleaned: {id: bool} — unknown/broken entries dropped."""
        try:
            from i18n import load_config
            stored = load_config().get(CONFIG_KEY)
        except Exception:  # noqa: BLE001 — without i18n there is no config at all
            return {}
        if not isinstance(stored, dict):
            return {}
        clean: Dict[str, bool] = {}
        for key, value in stored.items():
            if isinstance(key, str) and isinstance(value, bool):
                clean[key] = value
        return clean

    def _apply_config_state(self) -> None:
        """The stored switches → the fresh records (a missing id = ENABLED, the default).

        The switch is applied to EVERY record, a failed one included: the user's choice is
        remembered even while a plugin is broken, so fixing the file cannot silently
        re-enable something that was switched off (the state of a failed record stays
        `error` — the switch only says what would happen once it loads).
        """
        stored = self._load_config_state()
        for plugin_id, rec in self._records.items():
            enabled = stored.get(plugin_id, True)
            rec.enabled = enabled
            if rec.failed:
                continue
            rec.state = STATE_LOADED if enabled else STATE_DISABLED

    def _save_config_state(self) -> bool:
        """Write the switches of the CURRENT records (merge-write; never raises).

        Every discovered id is written (the `save_hotkeys` precedent) — including a
        failed one, whose stored intent must survive the round.
        """
        payload = {r.plugin_id: bool(r.enabled) for r in self._records.values()}
        try:
            from i18n import save_config
            return bool(save_config({CONFIG_KEY: payload}))
        except Exception as e:  # noqa: BLE001 — saving must never break the menu
            _log_line("warning", f"saving the plugin state failed: {e!r}")
            return False

    # ── the events of a round ─────────────────────────────────────────────────

    def _queue_round_events(self, reloading: bool) -> None:
        """One event per plugin of the round + one for the round itself (the Reload report)."""
        for rec in self.records():
            if rec.failed:
                self._push_event(EVENT_ERROR, rec)
            elif rec.state == STATE_DISABLED:
                # A disabled plugin is reported only when the user asked for a reload:
                # at startup it would be one status line per switched-off plugin.
                if reloading:
                    self._push_event(EVENT_DISABLED, rec)
            else:
                self._push_event(EVENT_LOADED, rec)
        if reloading:
            self._push_event(EVENT_RELOADED, None, count=len(self._records))
