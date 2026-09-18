# PLUGINS.md — the SSH Map plugin foundation (API v1)

> **Status.** This document is the **frozen API v1 contract** of the plugin foundation
> (ROADMAP `v1.4rc1 → v1.4`, the rc series). It was pinned BEFORE the first rc, in the
> same way `PYTE82_AUDIT.md` froze the pyte fork: **the rc series implements this
> contract, it does not change it.** A behaviour that is not described here is not part
> of API v1; a change to what IS described here belongs to **API v2**, which ships as a
> new entry-point group (`sshmap.plugins/v2`) next to this one — installed v1 plugins
> keep working.
>
> **What each rc ships.** **rc1:** discovery + the manager (`modules/plugin_manager.py`)
> and the `Plugins` menu (a switch per plugin + `Reload`). **rc2 (SHIPPED):**
> `PluginContext` (`modules/plugin_context.py`), `ctx.run_command` on its managed worker
> (`modules/plugin_runner.py`), `ctx.status`, the `status_probe` merge inside a
> `StatusChecker` round and the Main Thread isolation (the 200 ms / 1500 ms budgets, the
> worker and orphan registries, the Qt guard). **rc3 (SHIPPED):** the UI hooks in the
> interface — `register_commands` reaches the Ctrl+K palette and `extend_node_context_menu`
> the node context menu of the map and of the sidebar — plus "Run on selected servers"
> (`run_on_nodes` behind the Plugins-menu item) and the worked examples of §10. **Every
> hook of API v1 is now called by the core.**
>
> **v1.4 (SHIPPED — the base release of the line).** The API v1 contract is complete and
> exercised from the OUTSIDE: the repository ships two WORKING example plugins in
> `examples/plugins/` (`hello.py` — the minimal two-hook plugin; `disk_monitor.py` — the
> Disk Space Monitor: `run_on_nodes` collects `df -hP` into the plugin's own atomic cache
> and `status_probe` warns from it). They are examples, not shipped plugins: not installed,
> never auto-discovered, and they add no i18n key (§7). Dogfooding them found and fixed a
> real defect of the rc line: a command started from a `run_on_nodes` **worker** thread
> used to lose its results (`ctx.run_command` builds its runner on the manager's thread
> now — §5 and §6 keep their promise that the callbacks arrive on the GUI thread). The
> contract itself did not change: API v1 is exactly what rc1 froze.

---

## 1. What a plugin is

A plugin is an ordinary Python module that carries a `MANIFEST` dictionary and,
optionally, some of the four hook functions. Nothing else is required: no base class,
no registration call, no decorator — the core finds the module itself.

```python
# ~/.sshmap/plugins/hello.py  (or my_plugin/__init__.py inside an installed package)
MANIFEST = {
    "name": "hello",              # REQUIRED — the plugin's identity (unique)
    "version": "1.0",             # REQUIRED — the author's own version string
    "api_version": 1,             # REQUIRED — must be 1 for this contract
    "description": "Says hello",  # optional — shown in the tooltip
}

def register_commands(ctx):
    return []
```

`name` is the plugin's identity everywhere: the key of the enable/disable switch in
`~/.sshmap/config.json`, the row in the `Plugins` menu and the label in the log. Two
plugins with the same `name` are a conflict — see §4.

## 2. Two ways to ship one

| | Entry point (a package) | Folder (one file) |
|---|---|---|
| How | `pip install sshmap-hello-plugin` | drop `hello.py` into `~/.sshmap/plugins/` |
| Declaration | `[project.entry-points."sshmap.plugins/v1"]`<br>`hello = "sshmap_hello_plugin"` | the file itself |
| For | distribution, dependencies, a real version | experiments, private scripts, an installed copy of the app |

The **entry point group name carries the API version**: `sshmap.plugins/v1`. This is the
standard mechanism (`importlib.metadata.entry_points`) that pytest, Jupyter and flake8
use — an installed plugin needs no cooperation from the application.

A **folder plugin is a single file** and is loaded as a top-level module with a
generated name (`sshmap_plugin_local_<file stem>`), *not* as a package: a relative
import has nothing to resolve against. A file whose name starts with `_` is ignored (a
private helper next to a plugin). `Plugins → Reload` re-reads the folder — a changed
file is picked up without a restart; an import cache is never consulted.

## 3. The hooks (all optional)

Every hook is optional: a plugin may implement any subset, and a module without hooks is
a valid plugin. Each call into a plugin is wrapped by the core — **a hook that raises
never propagates into the application** (the exception is logged and the plugin's work
is abandoned for that call only).

### `register_commands(ctx) -> [PluginCommand]` — *(rc3)*
Contributes commands to the **command palette** (Ctrl+K) and to the action registry
("Settings → Hotkeys"). `PluginCommand` is a small frozen record — `text` (the author's
string, NOT an i18n key), `callback` (called with the plugin's own `ctx` when the user
runs the command), optional `description` and optional `keywords` (extra search text):
`PluginCommand(text="Say hello", callback=fn, description="…")`. The record also accepts
a plain `(text, callback)` pair or a `{"text": …, "callback": …}` dict, and a nested list
is flattened — the reading is deliberately lenient; an entry without usable text is
skipped with a log line. Plugin commands live in their own palette section (after
"servers"), so a plugin can never shadow a core command. The callbacks run through the
core's wrapper: a command that raises is a log line plus a status-bar line, never a
broken palette.

### `extend_node_context_menu(menu, nodes) -> None` — *(rc3)*
Called while the node context menu of the map or of the sidebar is being built;
`menu` is a live `QMenu`, `nodes` are lightweight node records (see §5), never the
scene objects. The plugin adds its QActions; **the manager owns every QAction it
creates** (see §6) — the plugin must keep the wrapper alive the ordinary way (a
reference on its module or on a returned list) or hand it to the manager's guard.

### `status_probe(node) -> (kind, detail) | None` — *(rc2)*
Runs inside the ordinary `StatusChecker` round (the parallel `ThreadPoolExecutor`), one
call per node, **in a worker thread — never on the GUI thread**. Returns
`(kind, detail)` where `kind ∈ {"online", "warn", "offline"}` and `detail` is an
optional string (an HTTP code, a container count) that is appended to the node's
tooltip; `None` means "no opinion" and the SSH probe's result stands. When both speak,
the result is **the worse of the two by severity** and the details are concatenated.

### `run_on_nodes(nodes, ctx) -> None` — *(rc2)*
The headless hook: "run this on the selected servers". It receives node records and the
context; the actual execution goes through `ctx.run_command()` (§5), which the core runs
on managed worker threads.

## 4. Discovery, states and conflicts

Discovery runs ONCE at startup — after the main window exists and before the event loop
(`main.py`), plus on every `Plugins → Reload`. Sources are read in this order:
**entry points first, then the folder**, each sorted by name.

* the **folder plugin loses** a name conflict against an installed plugin (the packaged
  one wins, the local file is skipped with a log line) — one identity cannot be switched
  half-way;
* a plugin that cannot be loaded goes into the **error** state: a record in the log
  (`~/.sshmap/logs/sshmap.log`) and one status-bar line. The reasons are `import`
  (the file/module could not be imported), `manifest` (no `MANIFEST`, not a dictionary,
  no usable `name`/`version`) and `api_version` (the manifest declares another API —
  install a v1 plugin or wait for the `sshmap.plugins/v2` group). **A broken plugin
  never affects the application or the other plugins** — it is listed in the menu,
  disabled, with the reason in its tooltip;
* a plugin disabled by the user is still **imported** (the core must read its `MANIFEST`
  to name it) but **never called**: disabling stops the hooks, not the import;
* the switch lives in `plugins` of `~/.sshmap/config.json`:
  `{"hello": false}`. A missing id is ENABLED (a new plugin is on by default), an
  unknown id is ignored, a broken value falls back to the default.

## 5. `PluginContext` — the only window into the core

A plugin does **not** receive the main window, the scene, `ServerData`, the keyring or a
paramiko object. Everything arrives through the context, and everything on it is
either a read-only fact or a service:

| Read-only | |
|---|---|
| `ctx.app_version` | the running SSH Map version (`version.APP_VERSION`) |
| `ctx.api_version` | the API version of the context (1) |
| `ctx.plugin_id` | the plugin's own `MANIFEST["name"]` |
| `ctx.log(message)` | a line into `~/.sshmap/logs/sshmap.log`, prefixed with the plugin id |

| Service | |
|---|---|
| `ctx.run_command(nodes, command)` | *(rc2)* non-interactive execution over SSH — the credentials are resolved by the CORE (`services/credential_manager.py`); per-node results (output, exit code, error) arrive through callbacks. Interactive sessions are NOT available to plugins |
| `ctx.status(text, timeout_ms=…)` | *(rc2)* a status-bar line (the core owns the widget and the token guard: a stale async result cannot overwrite a newer message) |

The callbacks of `ctx.run_command` (rc2): `on_result(node, result)` is called for EVERY
node as soon as its answer is known — `result` carries `output`, `exit_code` and `error`,
and one node's failure is a result for that node, never a reason to stop the others —
and `on_finished(results)` is called once with the whole list, in node order. Both are
delivered on the GUI thread, so a plugin may touch its own Qt objects there; a node whose
connection fails simply reports the error in its own result. `timeout` (seconds, default
30) bounds ONE node's connect + command. The core marshals the call itself onto its own
thread, so this holds whether `run_command` is called from a palette command (the GUI
thread) or from a `run_on_nodes` hook (a worker thread).

A **node record** exposed to plugins is exactly `{id, alias, host, port, user}` plus the
plugin's own data; a plugin that needs more asks the core for a service, it does not
reach for the model.

## 6. Isolation rules (what is allowed and what is not)

* **Main Thread discipline.** UI hooks (`register_commands`, `extend_node_context_menu`)
  are called synchronously, on the GUI thread, and must be FAST — no IO, no network, no
  `time.sleep`: the contract's budget is **200 ms**, and a slower hook is a warning in
  the log. Everything else (`status_probe`, `run_on_nodes`) runs on MANAGED worker
  threads: the core's registry plus the orphan registry (the v1.2 semantics — a wait
  budget, a thread that outlives it is registered instead of collected, self-cleanup on
  `finished()`). A hook that does not return within the budget is abandoned and
  reported; the application keeps living.
* **Qt objects.** A plugin that creates a QAction (or any QObject) hands the reference
  to the manager — the manager keeps every reference in its guard. A Python wrapper
  whose C++ object has an attached menu and dies takes the C++ menu with it (the
  PySide6 6.11 pitfall documented in `AGENTS.md` §7 gotcha #9).
* **Never throws.** Every call into a plugin is wrapped: an exception is a log line and
  a failed call, never a crash of the host and never a broken neighbour plugin.
* **Forbidden:** touching the GUI outside the hooks; blocking the GUI thread; importing
  `ui.main_window`; writing to `~/.sshmap/config.json` directly (use the context);
  reading or storing passwords in plain text (the keyring is the core's business);
  editing `third_party/pyte`; assuming a specific SSH Map version beyond
  `ctx.app_version` — the API version is the compatibility contract.
* **Documented limitation — in-process execution.** A plugin runs in the application's
  own process. Python gives no isolation from a **segfault in a C extension**: a plugin
  with a broken ABI can take the host down, exactly as a pytest plugin can. Hard
  isolation (a subprocess plus IPC) is a separate project and is explicitly NOT a goal
  of the 1.4 line. Install plugins you trust, as you trust the packages you pip-install.

## 7. Plugin strings and the application's translations

The strings a plugin shows (command text, menu item text, descriptions) are the
**author's** — the core never translates them and they are outside the i18n parity
policy (a plugin ships its own translations, or none). Only the core's own lines — the
`Plugins` menu, the load/error/disable status messages — are i18n keys.

## 8. What is NOT in API v1

An event bus; settings-dialog tabs or panels/docks contributed by a plugin; terminal
input/output interception; a plugin API for the map scene (drawing, layout); automatic
download or update of plugins; a marketplace; sandboxing. Some of these are on the
horizon (`ROADMAP.md` → "v1.5+ / horizon"); the rest are rejected.

## 9. Coming with rc3

*(Delivered — see §10: the package template, the "plugin in 20 minutes" walkthrough and
the author checklist. `PLUGINS.md` is now the complete author documentation; the
executable specifications are `tests/test_plugins.py` (discovery), `tests/test_plugin_runtime.py`
(the context and the isolation) and `tests/test_plugin_ui.py` (the UI hooks).)*

---

## 10. Writing a plugin — the 20-minute path

### 10.1 The folder plugin (no packaging, no install)

Drop one `.py` file into `~/.sshmap/plugins/`. `Plugins → Reload` picks it up — a
changed file is re-read (no restart, no import cache).

```python
# ~/.sshmap/plugins/k9s_launcher.py
MANIFEST = {
    "name": "k9s_launcher",          # the identity: the config key, the menu row, the log
    "version": "1.0",
    "api_version": 1,
    "description": "Runs k9s on the servers you select",
}

from PySide6.QtGui import QAction   # a plugin may use Qt — inside the hooks only
from modules.plugin_manager import PluginCommand   # the record of a palette command


def register_commands(ctx):
    """Ctrl+K: one command per plugin, in the palette's own section."""
    return [PluginCommand(text="Run k9s on the selection",
                          callback=lambda c: _launch(c),
                          description="opens k9s on every selected server",
                          keywords="k9s kubernetes tui")]


def extend_node_context_menu(menu, nodes):
    """The right-click menu of a server (map AND sidebar)."""
    act = QAction("k9s here", menu)
    act.triggered.connect(lambda: _launch_single(nodes[0]))
    menu.addAction(act)
    # The core keeps this QAction alive while the menu is open (PLUGINS.md §6) — a plugin
    # that also stores its own reference is welcome to, but it does not have to.


def status_probe(node):
    """One extra opinion per server, merged into the ordinary probe round."""
    if node.port == 6443:                      # a Kubernetes API port, say
        return ("online", "kube-apiserver")
    return None                                # "no opinion" — the SSH probe stands


def run_on_nodes(nodes, ctx):
    """Plugins → "Run on selected servers" (also assignable to a key)."""
    ctx.status(f"k9s: {len(nodes)} server(s)", 3000)
    ctx.run_command(nodes, "k9s --readonly",
                    on_result=lambda node, res: ctx.log(f"{node.alias}: {res.exit_code}"))


def _launch(ctx):
    _launch_many(ctx, None)                    # the whole registry, or the selection


def _launch_many(ctx, node):
    ...
```

Notes that save time:

* `register_commands` runs EVERY time the palette is opened and whenever the "Plugins"
  menu is rebuilt: return the list, do no IO there (the 200 ms budget, §6).
* the palette shows the command's `text` verbatim — it is the author's string, not an
  i18n key (§7);
* `extend_node_context_menu` is called while the menu is being built, on the GUI thread,
  with the node records of what the user right-clicked (the map passes the clicked card,
  the sidebar the row's id — both arrive narrowed, §5);
* `status_probe` runs in a WORKER thread inside the SSH round: no Qt, no widget, fast or
  it is abandoned;
* `run_on_nodes` runs on a managed worker thread; the work it starts through
  `ctx.run_command` gets its own managed worker and is waited for on shutdown.

### 10.2 The packaged plugin (an ordinary Python package)

```
sshmap-hello-plugin/
├── pyproject.toml
└── sshmap_hello_plugin/
    └── __init__.py        # the module with MANIFEST + the hooks
```

```toml
# sshmap-hello-plugin/pyproject.toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "sshmap-hello-plugin"
version = "0.1.0"
description = "A hello-world plugin for SSH Map"
requires-python = ">=3.10"

# THE declaration that makes it discoverable — the group name carries the API version.
[project.entry-points."sshmap.plugins/v1"]
hello = "sshmap_hello_plugin"
```

`pip install .` (or `pipx inject sshmap ./sshmap-hello-plugin`, or `pip install` from a
git URL) is the whole installation: SSH Map finds the package through the standard entry
points on the next start — no registration file, no cooperation from the application.
**A packaged plugin wins a name conflict** against a folder file with the same
`MANIFEST["name"]` (§4).

### 10.3 Dogfooding checklist (before you share a plugin)

| | Check |
|---|---|
| ☐ | `MANIFEST` has `name`, `version`, `api_version: 1`; `name` is unique and stable |
| ☐ | Hook names are spelled exactly as in §3 (`register_commands`, `extend_node_context_menu`, `status_probe`, `run_on_nodes`) |
| ☐ | The plugin imports cleanly when the app is NOT running (`python -c "import my_plugin"`) |
| ☐ | `Plugins → Reload` shows the plugin as checked; switching it off removes its commands/menu rows |
| ☐ | No IO, no network, no `time.sleep` inside `register_commands` / `extend_node_context_menu` (the 200 ms budget is logged as a warning) |
| ☐ | `status_probe` returns a `(kind, detail)` pair or `None`, with `kind` among `online` / `warn` / `offline`, and touches no Qt object |
| ☐ | Every command/menu action is reachable and does its work through `ctx` (`ctx.log` / `ctx.status` / `ctx.run_command`) |
| ☐ | `ctx.run_command` callbacks handle a per-node `error` (one server down must not break the run) |
| ☐ | No password, key path or paramiko object is stored, logged or sent anywhere by the plugin |
| ☐ | A broken state (an exception in a hook) is survivable: the app logs it and keeps working |
| ☐ | The plugin's user-visible strings are the author's own (translated by the plugin, if at all — §7) |

### 10.4 Working code in the repository

`examples/plugins/` holds two examples that really load (copy them into
`~/.sshmap/plugins/`, then `Plugins → Reload`):

| File | What it shows |
|---|---|
| `hello.py` | The minimal plugin: one palette command returned as a plain `(text, callback)` pair, one row in the node context menu. No import of the core — the shape a plugin of ten lines has. |
| `disk_monitor.py` | The first useful one, and the shape most real plugins take: `run_on_nodes` COLLECTS (`ctx.run_command` → `df -hP` → the plugin's own atomic cache) and `status_probe` REPORTS from that cache — no SSH inside a probe. |

`examples/README.md` explains how to use and edit them; `tests/test_plugin_examples.py`
loads both through the real discovery, drives their hooks and pins the "a plugin never
imports the core" rule with a source scan.

### 10.5 Where the core's own documents continue

* `DOCUMENTATION.md` §33 — the implementation notes (the manager, the context, the
  isolation machinery, the UI half and the Qt pitfall behind the guard);
* `ROADMAP.md` — what is planned beyond API v1 (an event bus, UI extensions, terminal
  interception: the `v1.5+ / horizon` list);
* `tests/test_plugins.py` / `tests/test_plugin_runtime.py` / `tests/test_plugin_ui.py` —
  the executable specification of what a plugin may rely on.
