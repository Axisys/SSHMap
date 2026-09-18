# -*- coding: utf-8 -*-
"""SSH Map example plugin — the minimal one: two UI hooks, no packaging, no core imports.

This file is an EXAMPLE, not a shipped plugin (see `examples/README.md`): copy it into
`~/.sshmap/plugins/` and use `Plugins → Reload`. It shows the whole author-facing
surface a small plugin needs and nothing else:

* `register_commands` puts one row into the command palette (Ctrl+K) — returned as a
  plain `(text, callback)` pair, the lenient shape `PLUGINS.md` §3 allows, so the file
  needs no import of the core at all;
* `extend_node_context_menu` adds one row to the right-click menu of a server — the
  same hook feeds the map AND the sidebar (the core hands over node RECORDS, §5).

**The rule every file of this folder follows: a plugin never imports the core.** An
installed application does not have this repository on `sys.path`, so
`from modules.plugin_manager import …` would work in a source checkout and break for a
real user — everything a plugin needs arrives through `ctx` and the hook arguments.

The plugin's own strings (command text, menu text, description) are the AUTHOR's: the
core never translates them and they are outside the i18n parity policy (`PLUGINS.md` §7).
"""

MANIFEST = {
    "name": "hello",              # the identity: the config key, the menu row, the log
    "version": "1.0",
    "api_version": 1,
    "description": "The minimal example: one palette command, one context-menu row",
}

from PySide6.QtGui import QAction   # a plugin may use Qt — inside the hooks only

PALETTE_RUNS = []   # the plugin's own state: it proves the command really ran
GREETED = []        # the aliases the context-menu row was used on


def register_commands(ctx):
    """Ctrl+K: one command, returned as a `(text, callback)` pair (a lenient shape)."""
    return [("Say hello", _say_hello)]


def _say_hello(ctx):
    """The callback runs with THIS plugin's context, inside the core's "never throws" wrapper."""
    PALETTE_RUNS.append(ctx.plugin_id)
    ctx.status("Hello from the example plugin", 3000)
    ctx.log("hello: the palette command ran")


def extend_node_context_menu(menu, nodes):
    """The right-click menu of a server — both surfaces, one hook (PLUGINS.md §3).

    `nodes` are narrowed records (`PluginNode`), never the scene objects; `menu` is the
    live QMenu the core built. The QAction belongs to the manager's guard (§6), so a
    plugin does not have to keep its own reference — storing it is welcome all the same.
    """
    act = QAction("Hello on this server", menu)
    act.triggered.connect(lambda: _greet(nodes))
    menu.addAction(act)


def _greet(nodes):
    """The row's action: it works with the records the core handed over."""
    GREETED.append([node.alias or node.id for node in nodes])
