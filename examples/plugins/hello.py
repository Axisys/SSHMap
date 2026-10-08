# -*- coding: utf-8 -*-
"""SSH Map example plugin — the minimal one: two UI hooks, no packaging, no core imports.

This file is an EXAMPLE, not a shipped plugin (see `examples/README.md`): copy it into
`~/.sshmap/plugins/` and use "Plugins → Reload". Each hook does the smallest USEFUL thing and the
pair teaches the two shapes of API v1: `extend_node_context_menu(menu, nodes)` appends **Copy SSH
command** — the `ssh -p <port> <user>@<host>` line of the records the core narrowed, put on the
clipboard by an ordinary Qt call, in the hook that receives NO context — while `register_commands(ctx)`
returns **Copy the plugins folder path** as a plain `(text, callback)` pair: the callback DOES receive
the context, computes its own path and reports it through `ctx.status()`.

THE RULE every file of this folder follows: a plugin never imports the core (an installed app has no
checkout on `sys.path`), and its strings are the AUTHOR's — never i18n keys (`PLUGINS.md` §7)."""

MANIFEST = {
    "name": "hello",              # the identity: the config key, the menu row, the log
    "version": "1.0",
    "api_version": 1,
    "description": "The minimal example: copy an ssh command line, copy the plugins folder path",
}

import os                        # the standard library is the author's business; the CORE is not

from PySide6.QtGui import QAction        # a plugin may use Qt — inside the hooks only
from PySide6.QtWidgets import QApplication

PALETTE_RUNS = []   # the plugin's own state: it proves the command really ran
COPIED = []         # the lines this plugin put on the clipboard


def ssh_command(node) -> str:
    """ONE node record → the `ssh` line a user types: `ssh -p 2222 root@10.0.0.1`.

    A PURE function over the narrowed record (`{id, alias, host, port, user}` — `PLUGINS.md` §5), and
    the plugin computes the line ITSELF: the core hands over facts, never a built command. The port is
    always written (the record knows it) and the user is prefixed only when the record carries one,
    because `PluginNode` is frozen — there is no other way for a plugin to ask.
    """
    host = str(getattr(node, "host", "") or "").strip()
    try:
        port = int(getattr(node, "port", 22) or 22)
    except (TypeError, ValueError):
        port = 22
    user = str(getattr(node, "user", "") or "").strip()
    address = f"{user}@{host}" if user else host
    return f"ssh -p {port} {address}".strip()


def _copy(text, ctx=None):
    """The ONE clipboard write of this plugin (an ordinary Qt call — see the two hooks below)."""
    QApplication.clipboard().setText(text)
    COPIED.append(text)
    if ctx is not None:
        ctx.log(f"hello: copied {len(text)} character(s)")


def register_commands(ctx):
    """Ctrl+K: one command, returned as a `(text, callback)` pair (a lenient shape).

    The callback is called WITH this plugin's context, so the plugin computes its own data (here the
    folder a folder-plugin lives in) and reports the result — no IO, no core import, no Qt widget.
    """
    return [("Copy the plugins folder path", _copy_plugins_dir)]


def _copy_plugins_dir(ctx):
    """The palette callback: the plugin owns its path, `ctx.status()` shows the line it copied."""
    PALETTE_RUNS.append(ctx.plugin_id)
    path = os.path.join(os.path.expanduser("~"), ".sshmap", "plugins")
    _copy(path, ctx)
    ctx.status(f"hello: copied {path}", 4000)


def extend_node_context_menu(menu, nodes):
    """The right-click menu of a server — both surfaces, one hook (`PLUGINS.md` §3).

    `nodes` are narrowed records (`PluginNode`), never the scene objects, and this hook gets NO
    context: the row runs the ordinary Qt clipboard call itself. The QAction belongs to the manager's
    guard (§6), so a plugin does not have to keep its own reference — storing it is welcome all the same.
    """
    act = QAction("Copy SSH command", menu)
    act.triggered.connect(lambda: _copy_ssh_lines(nodes))
    menu.addAction(act)


def _copy_ssh_lines(nodes):
    """The row's action: one `ssh` line per selected record, the whole selection in ONE clipboard."""
    _copy("\n".join(ssh_command(node) for node in nodes or []))
