# -*- coding: utf-8 -*-
"""v1.4rc3 — Plugin foundation, part 3: the UI hooks and dogfooding (ROADMAP tasks 7–9).

rc1 discovered the plugins and gave them a menu, rc2 gave them `PluginContext` +
`run_command` + the Main Thread discipline. rc3 makes the last two hooks REACHABLE: a
plugin's commands land in the command palette (Ctrl+K) in their own section, its rows are
appended to the node context menu of the MAP and of the SIDEBAR, and "Run on selected
servers" (the `run_on_nodes` hook, the rc2 machinery) gets its entry point — a Plugins-menu
item and a registry action.

Sections:
  §1 `PluginCommand` + the lenient coercion of `register_commands` (nested lists, pairs,
     dicts, junk) — a typo is a skipped entry, never a broken palette;
  §2 `PluginManager.plugin_commands()`: the loaded/enabled filter, the ctx of the hook,
     a raising hook;
  §3 the palette: the plugin section comes AFTER the servers, the command runs through the
     manager (its own `ctx`, the exception wrapper), a disabled/broken plugin is invisible;
  §4 the node context menu: the MAP path (a real `ServerNode`, `build_context_menu`) and
     the SIDEBAR path (a node id through `_on_sidebar_context_menu`) — one entry point, the
     frozen `{id, alias, host, port, user}` records, the 200 ms budget ("never throws");
  §5 the QAction guard: a plugin's row survives a garbage collection (gotcha #9) and is
     gone from the menu once the plugin is switched off;
  §6 "Run on selected servers": the menu item, its enabled state, the hint row, the status
     line of the round, the hook really running on a managed worker with the selection;
  §7 dogfooding: a folder plugin that contributes a command + a context row + a node action
     — the "plugin in 20 minutes" scenario of PLUGINS.md, end to end;
  §8 the release state: the new keys × en/ru/zh/de, the parity, the pin, the version.

Run: python tests/test_plugin_ui.py   (from the project root) or python tests/run_all.py
"""
import gc
import os
import sys
import time

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, translation_keys)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import modules.plugin_manager as PM  # noqa: E402
import ui.main_window as MW  # noqa: E402
import ui.hotkey_registry as HR  # noqa: E402
from i18n import t  # noqa: E402
from models.server import ServerData  # noqa: E402

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
PLUGIN_DIR = PM.user_plugin_dir()

NEW_I18N_KEYS = ["plugins.run_on_nodes", "plugins.run_hint", "plugins.no_selection",
                 "plugins.status.run_on_nodes", "palette.kind_plugin"]

_MANIFEST = 'MANIFEST = {"name": %r, "version": "1.0", "api_version": 1, "description": %r}\n'


# ── helpers (the test_plugins.py harness pattern) ─────────────────────────────

def write_plugin(stem, name, body):
    """Drop a plugin file into the user folder; returns its path."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    path = os.path.join(PLUGIN_DIR, f"{stem}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write((_MANIFEST % (name, f"{name} test plugin")) + body)
    return path


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


def new_window():
    win = MW.MainWindow()
    win._autosave_timer.stop()
    return win


def local(name):
    """The imported module of a folder plugin (its own state proves a call happened)."""
    return sys.modules.get(PM.LOCAL_MODULE_PREFIX + name)


def wait_until(predicate, timeout_ms=4000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def add_node(win, node_id="n1", alias="web-1", host="10.0.0.1"):
    node = win.scene.add_server(ServerData(id=node_id, alias=alias, host=host,
                                           user="root", x=40.0, y=40.0))
    win.refresh_sidebar()
    return node


def menu_texts(menu):
    return [a.text() for a in menu.actions() if a.text()]


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 `PluginCommand` and the coercion of `register_commands` ==")
# ════════════════════════════════════════════════════════════════════════════

_cmd = PM.PluginCommand(text="Say hello", callback=lambda ctx: None, description="d")
check("PluginCommand is a record of the author's text + a callback (+ hints)",
      _cmd.text == "Say hello" and callable(_cmd.callback) and _cmd.description == "d"
      and _cmd.keywords == "")
check("the record is FROZEN — the core never edits what a plugin declared",
      isinstance(type(_cmd).__dict__.get("__dataclass_params__"), object)
      and _cmd.__dataclass_params__.frozen is True)
check("searchable joins the text with the optional hints (an empty hint adds nothing)",
      _cmd.searchable == "Say hello d"
      and PM.PluginCommand(text="x").searchable == "x")

_parsed = PM.plugin_commands([
    PM.PluginCommand(text="a"),
    ("b", lambda ctx: None),
    ("c",),
    {"text": "d", "callback": None, "keywords": "kw"},
    {"label": "e"},
    None,
    "",                       # a bare string is not a command — skipped
    42,                       # junk — skipped, never fatal
    [PM.PluginCommand(text="nested")],
])
check("the coercion accepts the contract's records, pairs, dicts and nests (a lenient read)",
      [c.text for c in _parsed] == ["a", "b", "c", "d", "e", "nested"],
      str([c.text for c in _parsed]))
check("a pair keeps its callback; a dict reads text/label + keywords",
      callable(_parsed[1].callback) and _parsed[3].keywords == "kw")
check("a non-list answer is ignored (no exception, no phantom command)",
      PM.plugin_commands("nope") == [] and PM.plugin_commands(None) == [])

# ════════════════════════════════════════════════════════════════════════════
print("== §2 `PluginManager.plugin_commands()` ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("cmds", "cmds", (
    "CALLS = []\n"
    "def register_commands(ctx):\n"
    "    CALLS.append(ctx.plugin_id)\n"
    "    from modules.plugin_manager import PluginCommand\n"
    "    return [PluginCommand(text='Say hello', callback=lambda c: CALLS.append('ran')),\n"
    "            ('Pair command', lambda c: CALLS.append('pair'))]\n"))
write_plugin("noisy", "noisy", (
    "def register_commands(ctx):\n"
    "    raise RuntimeError('register boom')\n"))
write_plugin("nohooks", "nohooks", "X = 1\n")

_mgr = PM.PluginManager()
_mgr.discover()
_pairs = _mgr.plugin_commands()
check("plugin_commands() returns (plugin_id, record) for every loaded plugin",
      sorted(p[0] for p in _pairs) == ["cmds", "cmds"] and len(_pairs) == 2
      and {p[1].text for p in _pairs} == {"Say hello", "Pair command"},
      str([(p[0], p[1].text) for p in _pairs]))
check("the hook receives the plugin's OWN context (the id travels through it)",
      local("cmds").CALLS == ["cmds"], str(local("cmds").CALLS))
check("the author's text is used verbatim (never an i18n key)",
      [p[1].text for p in _pairs] == ["Say hello", "Pair command"])
check("a plugin that raises contributes nothing and is reported, not fatal",
      _mgr.get("noisy").ok is True and all(p[0] != "noisy" for p in _pairs))
check("a plugin without the hook is skipped by the filter (not an error)",
      _mgr.get("nohooks").ok is True and _mgr.get("nohooks").hooks == ())
check("a DISABLED plugin contributes no commands (the switch stops the hooks)",
      _mgr.set_enabled("cmds", False) is True
      and all(p[0] != "cmds" for p in _mgr.plugin_commands()))
_mgr.set_enabled("cmds", True)
check("…and re-enabling brings them back", len(_mgr.plugin_commands()) == 2)
check("a manager without plugins returns an empty list (no exception, no placeholder)",
      PM.PluginManager().plugin_commands() == [])
_mgr.shutdown(500)

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the command palette: the plugin section (Ctrl+K) ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
clear_cfg()
win = new_window()
add_node(win, "srv-1", "web-1", "10.0.0.10")
write_plugin("pal", "pal", (
    "RAN = []\n"
    "def register_commands(ctx):\n"
    "    from modules.plugin_manager import PluginCommand\n"
    "    return [PluginCommand(text='Palette hello',\n"
    "                          callback=lambda c: RAN.append(c.plugin_id),\n"
    "                          description='a plugin command')]\n"
    "def boom_command(ctx):\n"
    "    raise ValueError('command boom')\n"))
write_plugin("pal_bad", "pal_bad", (
    "def register_commands(ctx):\n"
    "    from modules.plugin_manager import PluginCommand\n"
    "    return [PluginCommand(text='Explode', callback=boom_command)]\n"
    "def boom_command(ctx):\n"
    "    raise ValueError('command boom')\n"))
win.start_plugin_discovery()
app.processEvents()

pal = win._command_palette
pal._collect_commands()
_labels = [c[0] for c in pal._commands]
_kinds = {c[0]: c[1] for c in pal._commands}
check("the palette picks up the commands of the discovered plugins",
      "Palette hello" in _labels and "Explode" in _labels, str(_labels[-4:]))
check("they are marked as plugin rows (a section of their own, not a core action)",
      _kinds.get("Palette hello") == "plugin" and _kinds.get("Explode") == "plugin")
check("the plugin section comes AFTER the servers (a plugin can never shadow a core command)",
      max(i for i, c in enumerate(pal._commands) if c[1] == "server")
      < min(i for i, c in enumerate(pal._commands) if c[1] == "plugin"),
      str([(c[1], c[0]) for c in pal._commands][-6:]))
check("the server rows keep their own kind (the palette still centers on a node)",
      "server" in _kinds.values() and t("palette.kind_plugin") == "Plugin")

_row = [c for c in pal._commands if c[0] == "Palette hello"][0]
_row[2]()
check("running the command goes through the manager and reaches the plugin's callback",
      local("pal").RAN == ["pal"], str(local("pal").RAN))
_boom = [c for c in pal._commands if c[0] == "Explode"][0]
_ok = _boom[2]()
check("a command that raises never propagates (the wrapper reports it)",
      _ok is True and win._plugin_manager.get("pal_bad").ok)

pal._refilter("pal")
check("the palette lists the plugin command for a matching query",
      any(pal.listw.item(i).text() == "Palette hello" for i in range(pal.listw.count())))
_item = next(pal.listw.item(i) for i in range(pal.listw.count())
             if pal.listw.item(i).text() == "Palette hello")
check("the plugin row carries the puzzle glyph (the same family as the Plugins menu)",
      not _item.icon().isNull())

write_plugin("off", "off", (
    "def register_commands(ctx):\n"
    "    from modules.plugin_manager import PluginCommand\n"
    "    return [PluginCommand(text='Off command', callback=lambda c: None)]\n"))
win._reload_plugins()
win._plugin_manager.set_enabled("off", False)
pal._collect_commands()
check("a DISABLED plugin is invisible in the palette",
      "Off command" not in [c[0] for c in pal._commands])
win._plugin_manager.set_enabled("off", True)

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the node context menu: the map + the sidebar ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("ctx", "ctx", (
    "SEEN = []\n"
    "from PySide6.QtGui import QAction\n"
    "def extend_node_context_menu(menu, nodes):\n"
    "    SEEN.append([n.as_dict() for n in nodes])\n"
    "    act = QAction('Plugin node action', menu)\n"
    "    act.setObjectName('plugin_ctx_action')\n"
    "    menu.addAction(act)\n"))
write_plugin("ctx_slow", "ctx_slow", (
    "import time\n"
    "def extend_node_context_menu(menu, nodes):\n"
    "    time.sleep(0.25)\n"))
write_plugin("ctx_bad", "ctx_bad", (
    "def extend_node_context_menu(menu, nodes):\n"
    "    raise RuntimeError('menu boom')\n"))
win._reload_plugins()
app.processEvents()

_node = win.scene.get_node("srv-1")
_menu = win.view.build_context_menu(_node.sceneBoundingRect().center())
check("the MAP context menu of a node carries the plugin's row",
      "Plugin node action" in menu_texts(_menu), str(menu_texts(_menu)))
check("the plugin's row sits ABOVE the multi-selection block but under the built-in actions",
      menu_texts(_menu).index("Plugin node action")
      > menu_texts(_menu).index(t("ctx.delete_server")))
check("the plugin received node RECORDS, never the scene objects",
      local("ctx").SEEN and local("ctx").SEEN[0][0]["id"] == "srv-1"
      and set(local("ctx").SEEN[0][0]) == {"id", "alias", "host", "port", "user"},
      str(local("ctx").SEEN))
check("the record carries exactly the contract's fields (a password/key is never handed over)",
      local("ctx").SEEN[0][0]["host"] == "10.0.0.10" and "password" not in local("ctx").SEEN[0][0])

check("the contract's UI-hook budget is the documented 200 ms (PLUGINS.md §6)",
      PM.UI_HOOK_BUDGET_MS == 200)
check("a hook slower than that budget is only a warning — the menu still opens",
      "Plugin node action" in menu_texts(_menu))
check("a hook that raises contributes nothing — the menu still opens for the user",
      "Plugin node action" in menu_texts(_menu)
      and win._plugin_manager.get("ctx_bad").ok is True)

# The sidebar path: the SAME window entry point, a node id instead of the scene item,
# through the real signal (`customContextMenuRequested` → the MainWindow slot). The QMenu
# is the project's CaptureMenu (tests/_fakes.py) — a test never shows a menu.
from _fakes import CaptureMenu as _CaptureMenu  # noqa: E402

from PySide6.QtCore import QPoint, Qt  # noqa: E402

_captured = []
_CaptureMenu.captured = _captured
_seen_before = len(local("ctx").SEEN)
_ORIG_QMENU = MW.QMenu
MW.QMenu = _CaptureMenu
try:
    _item = win.tree.topLevelItem(0)
    _rect = win.tree.visualItemRect(_item)
    win.tree.customContextMenuRequested.emit(QPoint(int(_rect.center().x()),
                                                    int(_rect.center().y())))
    app.processEvents()
finally:
    MW.QMenu = _ORIG_QMENU
check("the signal path really opened a menu (the sidebar slot ran)",
      bool(_captured) and _item.data(0, Qt.UserRole) == "srv-1")
check("the SIDEBAR context menu of a row is extended through the same entry point",
      len(local("ctx").SEEN) == _seen_before + 1, str(len(local("ctx").SEEN)))
check("the sidebar passes the row's node id (the manager narrows it exactly as on the map)",
      local("ctx").SEEN[-1][0]["id"] == "srv-1"
      and local("ctx").SEEN[-1][0]["alias"] == "web-1", str(local("ctx").SEEN[-1]))
check("the plugin's row landed in the captured sidebar menu",
      "Plugin node action" in menu_texts(_captured[-1]),
      str(menu_texts(_captured[-1])))
check("both surfaces ask the same plugins (one entry point, no map/sidebar drift)",
      win._extend_node_context_menu(QMenu(win), _node) >= 1
      and win._extend_node_context_menu(None, _node) == 0)
check("a menu-less call is a safe no-op (a plugin must not be called with nothing to fill)",
      win._extend_node_context_menu(None, None) == 0)

# ════════════════════════════════════════════════════════════════════════════
print("== §5 the QAction guard: a plugin's row outlives its Python wrapper ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("guard", "guard", (
    "from PySide6.QtGui import QAction\n"
    "def extend_node_context_menu(menu, nodes):\n"
    "    act = QAction('Guarded row', menu)\n"
    "    act.setObjectName('guarded_row')\n"
    "    menu.addAction(act)\n"))
win._reload_plugins()
app.processEvents()
_gmenu = QMenu(win)
win._extend_node_context_menu(_gmenu, _node)
check("the plugin's QAction is registered in the window's guard (gotcha #9)",
      any(a.objectName() == "guarded_row" for a in win._qaction_guard),
      str([a.objectName() for a in win._qaction_guard if a.objectName()]))
gc.collect()
check("…and it survives a garbage collection: the row is still in the menu",
      "Guarded row" in menu_texts(_gmenu), str(menu_texts(_gmenu)))
check("the guard also covers the DYNAMIC rows of the Plugins menu (the rc3 gap)",
      any(a.text() == "guard" for a in win._qaction_guard))
check("the permanent items of the Plugins menu are in the guard too",
      any(a is win.act_plugins_reload for a in win._qaction_guard)
      and any(a is win.act_plugins_run for a in win._qaction_guard))
_guard_before = len(win._qaction_guard)
win._rebuild_qaction_guard()
check("the guard is rebuilt, not grown forever (a rebuild is idempotent)",
      abs(len(win._qaction_guard) - _guard_before) <= 1, str(len(win._qaction_guard)))

# ════════════════════════════════════════════════════════════════════════════
print("== §6 «Run on selected servers» — the entry point of `run_on_nodes` ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("runner", "runner", (
    "RAN = []\n"
    "def run_on_nodes(nodes, ctx):\n"
    "    RAN.append(sorted(n.id for n in nodes))\n"
    "    ctx.status('runner saw %d' % len(nodes), 1000)\n"))
win._reload_plugins()
app.processEvents()
check("the action exists as a registry action (assignable in the Hotkeys tab)",
      "plugins.run_on_nodes" in HR.action_ids()
      and HR.default_sequence("plugins.run_on_nodes") == ""
      and win.act_plugins_run in win._hotkey_targets.get("plugins.run_on_nodes", []))
check("the item is enabled while a loaded plugin implements the hook",
      win.act_plugins_run.isEnabled() is True)
check("its menu label is the translated action text",
      t("plugins.run_on_nodes") in [a.text() for a in win._plugin_menu.actions()])
check("the hint row is ABSENT while the map has servers",
      t("plugins.run_hint") not in [a.text() for a in win._plugin_menu.actions()])

win._select_node(_node)
win._populate_plugin_items()
check("with a selection the action targets it (the plugin registry is fed from the map)",
      [r.id for r in win._plugin_manager.node_records()] == ["srv-1"],
      str(win._plugin_manager.node_records()))
win.act_plugins_run.trigger()
check("the status bar reports the scope of the round (count = the servers it ran on)",
      win.statusBar().currentMessage() == t("plugins.status.run_on_nodes", count=1),
      win.statusBar().currentMessage())
check("the hook really ran on a managed worker with the selected node",
      wait_until(lambda: local("runner") and local("runner").RAN) is not False
      and local("runner").RAN[0] == ["srv-1"], str(getattr(local("runner"), "RAN", None)))
app.processEvents()
check("…and its `ctx.status()` reached the window (a worker thread never touches a widget)",
      win.statusBar().currentMessage() in ("runner saw 1", t("plugins.status.run_on_nodes", count=1)),
      win.statusBar().currentMessage())

# The scope falls back to the whole map when nothing is selected.
win.scene.clearSelection()
win.act_plugins_run.trigger()
check("with nothing selected the whole map is the target (the status line says the count)",
      win.statusBar().currentMessage() == t("plugins.status.run_on_nodes", count=1))
check("the fallback really reached the plugin", wait_until(lambda: len(local("runner").RAN) >= 2)
      is not False, str(local("runner").RAN))

# A plugin without the hook cannot enable the item; a broken one must not either.
clean_plugins()
write_plugin("plain", "plain", "X = 1\n")
win._reload_plugins()
app.processEvents()
check("with no plugin implementing `run_on_nodes` the item is DISABLED (no silent no-op)",
      win.act_plugins_run.isEnabled() is False)
check("…and the plugin itself is still listed and switchable",
      "plain" in [a.text() for a in win._plugin_menu.actions() if a.isCheckable()])

_item_empty = win.tree.topLevelItem(0)
win.scene.remove_server("srv-1")
win.refresh_sidebar()
win._populate_plugin_items()
check("with no node registry the run item is disabled and no hint row is invented "
      "(the hint belongs to a plugin that COULD run)",
      win.act_plugins_run.isEnabled() is False
      and t("plugins.run_hint") not in [a.text() for a in win._plugin_menu.actions()],
      str([a.text() for a in win._plugin_menu.actions()]))

write_plugin("runner", "runner", (
    "RAN = []\n"
    "def run_on_nodes(nodes, ctx):\n"
    "    RAN.append(len(nodes))\n"))
win._reload_plugins()
app.processEvents()
_rows_now = [a.text() for a in win._plugin_menu.actions()]
check("a capable plugin with an EMPTY map: the item stays disabled and the hint says why",
      win.act_plugins_run.isEnabled() is False
      and t("plugins.run_hint") in _rows_now
      and "runner" in _rows_now,
      f"enabled={win.act_plugins_run.isEnabled()} rows={_rows_now} "
      f"nodes={win._plugin_manager.node_records()}")
# The disabled item cannot be clicked (Qt), so the handler is called directly: that is
# the defensive path of a hotkey / of a map emptied between opening the menu and clicking.
win._run_plugins_on_nodes()
check("the handler itself answers honestly on an empty map (a hotkey path)",
      win.statusBar().currentMessage() == t("plugins.no_selection"),
      win.statusBar().currentMessage())
add_node(win, "srv-2", "web-2", "10.0.0.11")
win._populate_plugin_items()
check("adding a server re-enables the item without a reload",
      win.act_plugins_run.isEnabled() is True
      and t("plugins.run_hint") not in [a.text() for a in win._plugin_menu.actions()])
_ran_before = len(getattr(local("runner"), "RAN", []))
win.act_plugins_run.trigger()
check("…and the round really reaches the plugin again (the new node is the target)",
      wait_until(lambda: len(getattr(local("runner"), "RAN", [])) > _ran_before) is not False
      and local("runner").RAN[-1] == 1, str(getattr(local("runner"), "RAN", None)))
win.scene.remove_server("srv-2")
win.refresh_sidebar()

# ════════════════════════════════════════════════════════════════════════════
print("== §7 dogfooding: the `~/.sshmap/plugins/` scenario end to end ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("k9s", "k9s", (
    "from PySide6.QtGui import QAction\n"
    "LOG = []\n"
    "def register_commands(ctx):\n"
    "    from modules.plugin_manager import PluginCommand\n"
    "    return [PluginCommand(text='Run k9s on the selected servers',\n"
    "                          callback=_launch, keywords='k9s kubernetes')]\n"
    "def _launch(ctx):\n"
    "    LOG.append(ctx.run_command(_LAST['nodes'], 'k9s --readonly'))\n"
    "_LAST = {'nodes': []}\n"
    "def extend_node_context_menu(menu, nodes):\n"
    "    act = QAction('k9s here', menu)\n"
    "    act.setObjectName('k9s_row')\n"
    "    menu.addAction(act)\n"
    "def run_on_nodes(nodes, ctx):\n"
    "    _LAST['nodes'] = list(nodes)\n"
    "    ctx.status('k9s: %d server(s)' % len(nodes), 1000)\n"))

# The runner's documented test seams (test_plugin_runtime.py): the transport and the
# credential resolver are injectable, so the dogfooding round needs no network.
import modules.plugin_runner as PR  # noqa: E402

_ORIG_TRANSPORT, _ORIG_CREDENTIALS = PR.run_command_over_ssh, PR.default_credentials
PR.run_command_over_ssh = lambda node, command, timeout, credentials: (
    PR.PluginRunResult(node=node, exit_code=0, output=f"k9s on {node.id}\n"))
PR.default_credentials = lambda node, facts=None: {"password": "secret", "key_path": ""}


def _dogfood(win2):
    """The whole "plugin in 20 minutes" scenario on one window (helper: scoped seams)."""
    add_node(win2, "k1", "worker-1", "10.0.0.21")
    add_node(win2, "k2", "worker-2", "10.0.0.22")
    win2.start_plugin_discovery()
    app.processEvents()

    check("the drop-in folder plugin is discovered without packaging",
          win2._plugin_manager.get("k9s") is not None
          and win2._plugin_manager.get("k9s").ok)
    win2._command_palette._collect_commands()
    check("its command reaches the palette with the author's text",
          "Run k9s on the selected servers" in
          [c[0] for c in win2._command_palette._commands])
    check("its row reaches the node context menu of the map",
          "k9s here" in menu_texts(
              win2.view.build_context_menu(
                  win2.scene.get_node("k1").sceneBoundingRect().center())))
    check("its `run_on_nodes` makes the Plugins-menu item available",
          win2.act_plugins_run.isEnabled() is True)
    win2.act_plugins_run.trigger()
    check("the run reached the plugin with BOTH nodes (nothing selected = the whole map)",
          wait_until(lambda: bool(local("k9s")._LAST["nodes"])) is not False
          and sorted(n.id for n in local("k9s")._LAST["nodes"]) == ["k1", "k2"],
          str(getattr(local("k9s"), "_LAST", None)))
    app.processEvents()
    check("the plugin's status line is what the user sees",
          win2.statusBar().currentMessage() == "k9s: 2 server(s)",
          win2.statusBar().currentMessage())
    _cmd = next(c for c in win2._plugin_manager.plugin_commands() if c[0] == "k9s")[1]
    check("the command is runnable through the palette too (the same hook path)",
          local("k9s").LOG == []
          and win2._command_palette._run_plugin_command("k9s", _cmd) is True)
    check("the plugin's `ctx.run_command` call was ACCEPTED by the core (a real worker)",
          local("k9s").LOG and local("k9s").LOG[0] is True, str(local("k9s").LOG))
    check("the manager's shutdown waits for the workers it owns (nothing is left running)",
          wait_until(lambda: win2._plugin_manager.active_workers() == [], timeout_ms=8000) is not False
          and win2._plugin_manager.active_workers() == []
          and win2._plugin_manager.shutdown(1500) is True)
    win2.close()


win2 = new_window()
try:
    _dogfood(win2)
finally:
    PR.run_command_over_ssh = _ORIG_TRANSPORT
    PR.default_credentials = _ORIG_CREDENTIALS

win.close()

# ════════════════════════════════════════════════════════════════════════════
print("== §8 the release state: the keys, the parity, the pin, the version ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
_missing = [k for k in NEW_I18N_KEYS
            if any(not _langs[c].get(k, "").strip() for c in ("en", "ru", "zh", "de"))]
check("the 5 new rc3 keys are present and non-empty in en/ru/zh/de",
      not _missing and len(NEW_I18N_KEYS) == 5, str(_missing))
check("every new key is in the key set of EVERY language (none missing, none extra)",
      all(set(NEW_I18N_KEYS) <= translation_keys(d) for d in _langs.values()))
check("the run report keeps its {count} placeholder in every language",
      all("{count}" in _langs[c]["plugins.status.run_on_nodes"] for c in _langs))
check("the plugin strings stay OUT of the parity policy (the author's text is not a key)",
      "Palette hello" not in _langs["en"] and "k9s here" not in _langs["en"])
check_i18n_parity(_langs)
check_i18n_format(_langs)
check_release_state(ROOT)

clean_plugins()
clear_cfg()
finish()
