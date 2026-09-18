# -*- coding: utf-8 -*-
"""v1.4rc2 (plugin foundation, ROADMAP task 5): `PluginContext` — the only window into the core.

The frozen API v1 contract (`PLUGINS.md` §5) says that a plugin receives **no**
MainWindow, no scene, no `ServerData` internals, no keyring object and no paramiko
object: everything arrives through one small object, and everything on it is either a
read-only fact or a service the CORE performs on the plugin's behalf. This module is
that object.

**Read-only** (plain properties, no state a plugin can move):

    ctx.plugin_id     the plugin's own MANIFEST["name"]
    ctx.api_version   the API version of the context (1 — the group `sshmap.plugins/v1`)
    ctx.app_version   the running SSH Map version (`version.APP_VERSION`)
    ctx.log(message)  one line into ~/.sshmap/logs/sshmap.log, prefixed with the id

**Services** (all of them are performed by the core, never by the plugin):

    ctx.run_command(nodes, command, on_result=…, on_finished=…, timeout=…)
        non-interactive execution over SSH — the credentials are resolved by the CORE
        (`services/credential_manager.py`); per-node results arrive through callbacks
        and hold the output, the exit code and the error of that node. Interactive
        sessions are NOT available to plugins (PLUGINS.md §5).
    ctx.status(text, timeout_ms=…)
        a status-bar line; the core owns the widget and the token guard, so a stale
        asynchronous result can never overwrite a newer message.

**Node records** (PLUGINS.md §5): a plugin sees exactly `{id, alias, host, port, user}`
— `PluginNode` here. It is a frozen dataclass, so a plugin cannot reach the model
through it; `as_dict()` exists for a plugin that wants to serialize a node.

**No Qt, no window, no i18n.** The context talks to the core through a duck-typed
adapter (`core`): the methods are looked up at CALL time and every one of them may be
missing — a context built without an adapter is a valid, completely inert context
(that is what makes this module testable without an application). Nothing here raises:
a service that cannot be performed returns False and leaves a log line.

The adapter's methods (all optional):

    plugin_log(plugin_id, message) -> None
    plugin_status(plugin_id, text, timeout_ms) -> bool
    plugin_run_command(plugin_id, nodes, command, on_result, on_finished, timeout) -> bool

They are implemented by `modules/plugin_manager.py`, which owns the worker registry and
the Qt signals; the context itself stays a plain Python object.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# The record fields a plugin may see (PLUGINS.md §5) — nothing else is exposed.
NODE_FIELDS = ("id", "alias", "host", "port", "user")

DEFAULT_STATUS_TIMEOUT_MS = 5000      # the ordinary status-bar timeout
DEFAULT_COMMAND_TIMEOUT_S = 30.0      # per-node budget of `ctx.run_command`

CONTEXT_API_VERSION = 1               # the API version reported by `ctx.api_version`


@dataclass(frozen=True)
class PluginNode:
    """A node as a plugin sees it: `{id, alias, host, port, user}` — and nothing else.

    Frozen on purpose: a plugin cannot write back into the application's state through
    the context (PLUGINS.md §6, "Forbidden: touching the GUI outside the hooks").
    """

    id: str
    alias: str = ""
    host: str = ""
    port: int = 22
    user: str = ""

    def as_dict(self) -> Dict[str, object]:
        """The record as a plain dict (what a plugin gets / may serialize)."""
        return {name: getattr(self, name) for name in NODE_FIELDS}

    def label(self) -> str:
        """`alias (host)` — the human text a plugin shows; falls back to the id."""
        if self.alias and self.host:
            return f"{self.alias} ({self.host})"
        return self.alias or self.host or self.id


def node_record(node) -> PluginNode:
    """Coerce anything node-like into a `PluginNode` (never raises).

    Accepted: a `PluginNode`, a dict with the documented keys, a `ServerData`-like
    object (`id`/`alias`/`host`/`ssh_port`/`user`) and a plain 5-tuple
    `(id, alias, host, port, user)`. This is the boundary where the core's model is
    NARROWED to the contract's record — a plugin never receives the model itself.

    v1.4rc3: a MAP OBJECT (`graphics/server_node.ServerNode`) is accepted too — the two
    UI surfaces of `extend_node_context_menu` hand the core what Qt gave them (the map a
    card, the sidebar a node id), and the unwrapping belongs here, at the ONE boundary,
    rather than in every caller. A wrapper is recognized by its `data` attribute (the
    `ServerNode.data` -> `ServerData` pattern) and unwrapped once.
    """
    if isinstance(node, PluginNode):
        return node

    data = getattr(node, "data", None)
    if data is not None and not isinstance(node, (dict, tuple, list)) \
            and hasattr(data, "id"):
        node = data

    def _text(value) -> str:
        return "" if value is None else str(value)

    def _port(value) -> int:
        try:
            port = int(value) if value else 22
        except (TypeError, ValueError):
            port = 22
        return max(1, min(65535, port))

    if isinstance(node, dict):
        return PluginNode(
            id=_text(node.get("id")), alias=_text(node.get("alias")),
            host=_text(node.get("host")),
            port=_port(node.get("port") if node.get("port") is not None else node.get("ssh_port")),
            user=_text(node.get("user")),
        )
    if isinstance(node, (tuple, list)) and len(node) >= 3:
        padded = list(node) + [None] * (5 - len(node))
        return PluginNode(id=_text(padded[0]), alias=_text(padded[1]), host=_text(padded[2]),
                          port=_port(padded[3]), user=_text(padded[4]))
    return PluginNode(
        id=_text(getattr(node, "id", "")), alias=_text(getattr(node, "alias", "")),
        host=_text(getattr(node, "host", "")),
        port=_port(getattr(node, "ssh_port", getattr(node, "port", 22))),
        user=_text(getattr(node, "user", "")),
    )


def node_records(nodes) -> List[PluginNode]:
    """A list of `PluginNode` from one node-like value OR any iterable of them.

    A value that carries no id is not a node (the probe of an id-less target would be
    meaningless) — it is skipped, exactly as `_build_targets` skips it for the probes.
    v1.4rc3: a SINGLE node-like value (a map card, a `ServerData`, an id string) is
    accepted as well as an iterable — the same leniency `PluginManager.set_nodes()`
    needed, in the one place that does the narrowing.
    """
    source = nodes
    if source is None:
        return []
    if not isinstance(source, (list, tuple, set, frozenset, dict)):
        if getattr(source, "data", None) is not None or hasattr(source, "id") \
                or isinstance(source, str):
            source = [source]        # ONE node-like value, not a sequence of them
    out: List[PluginNode] = []
    try:
        items = list(source)
    except TypeError:                # not iterable and not node-like — nothing to narrow
        return []
    for node in items:
        try:
            record = node_record(node)
        except Exception:  # noqa: BLE001 — a broken record is skipped, not fatal
            continue
        if record.id:
            out.append(record)
    return out


@dataclass
class PluginRunResult:
    """The result of `ctx.run_command` for ONE node (output / exit code / error).

    `error` is the core's own failure text (a connection or authentication error, a
    timeout); `output` carries the command's stdout when the connection worked, and
    `exit_code` is the remote exit status (-1 when the command never ran).
    """

    node: PluginNode
    exit_code: int = -1
    output: str = ""
    error: str = ""

    @property
    def node_id(self) -> str:
        return self.node.id

    @property
    def ok(self) -> bool:
        """True only for a command that really ran and exited with 0."""
        return not self.error and self.exit_code == 0

    def as_dict(self) -> Dict[str, object]:
        """The record as a plain dict (the shape the Qt signal and the callbacks carry)."""
        return {"node_id": self.node.id, "alias": self.node.alias, "host": self.node.host,
                "user": self.node.user, "port": self.node.port,
                "exit_code": self.exit_code, "output": self.output, "error": self.error}


def run_result_from_dict(data) -> PluginRunResult:
    """Rebuild a `PluginRunResult` from `as_dict()` (the worker → GUI signal hop)."""
    if not isinstance(data, dict):
        return PluginRunResult(node=PluginNode(id=""))
    node = PluginNode(id=str(data.get("node_id") or ""), alias=str(data.get("alias") or ""),
                      host=str(data.get("host") or ""), port=int(data.get("port") or 22),
                      user=str(data.get("user") or ""))
    try:
        exit_code = int(data.get("exit_code", -1))
    except (TypeError, ValueError):
        exit_code = -1
    return PluginRunResult(node=node, exit_code=exit_code,
                           output=str(data.get("output") or ""),
                           error=str(data.get("error") or ""))


class PluginContext:
    """The window a plugin gets into the core (PLUGINS.md §5).

    `core` is the adapter (the plugin manager); every method of it is looked up at call
    time and may be absent — this class works standalone (all services then report
    "not available") and never raises into a plugin or into the caller.
    """

    def __init__(self, plugin_id: str, core=None, api_version: int = CONTEXT_API_VERSION):
        self._plugin_id = str(plugin_id or "")
        self._core = core
        self._api_version = int(api_version or CONTEXT_API_VERSION)
        self._app_version = ""

    # ── read-only facts ───────────────────────────────────────────────────────

    @property
    def plugin_id(self) -> str:
        """The plugin's own `MANIFEST["name"]` — the stable identity everywhere."""
        return self._plugin_id

    @property
    def api_version(self) -> int:
        """The API version of the context — 1 for the group `sshmap.plugins/v1`."""
        return self._api_version

    @property
    def app_version(self) -> str:
        """The running SSH Map version (`version.APP_VERSION`; "" when unreadable).

        Deliberately a FACT and not a compatibility check: the API version is the
        contract, the application version is information (PLUGINS.md §6).
        """
        if not self._app_version:
            try:
                from version import APP_VERSION
                self._app_version = str(APP_VERSION)
            except Exception:  # noqa: BLE001 — a bare script without version.py
                self._app_version = ""
        return self._app_version

    # ── services ──────────────────────────────────────────────────────────────

    def log(self, message) -> None:
        """One line into the application log, prefixed with the plugin id. Never raises."""
        try:
            handler = getattr(self._core, "plugin_log", None)
            if callable(handler):
                handler(self._plugin_id, str(message))
                return
        except Exception:  # noqa: BLE001 — logging must never break a plugin
            pass
        try:  # no adapter (or a broken one) — the module logger still records it
            from modules.logger import get_logger
            get_logger("modules.plugin_context").info(f"[plugin {self._plugin_id}] {message}")
        except Exception:  # noqa: BLE001
            pass

    def status(self, text, timeout_ms: int = DEFAULT_STATUS_TIMEOUT_MS) -> bool:
        """A status-bar line for the user (False — the service is not available here).

        The core owns the widget and the token guard: an asynchronous caller may call
        this from a worker thread (the signal hop is the core's business) and a stale
        result can never overwrite a newer message.
        """
        try:
            timeout = int(timeout_ms)
        except (TypeError, ValueError):
            timeout = DEFAULT_STATUS_TIMEOUT_MS
        try:
            handler = getattr(self._core, "plugin_status", None)
            if callable(handler):
                return bool(handler(self._plugin_id, str(text), max(0, timeout)))
        except Exception as e:  # noqa: BLE001
            self.log(f"status() failed: {type(e).__name__}: {e}")
        return False

    def run_command(self, nodes, command, on_result: Optional[Callable] = None,
                    on_finished: Optional[Callable] = None,
                    timeout: Optional[float] = None) -> bool:
        """Run a non-interactive command over SSH on the given nodes (False — refused).

        `nodes` — anything node-like (see `node_record`); `command` — the shell command.
        The credentials are resolved by the CORE (never by the plugin), the connection
        runs on a managed worker thread, and one node's failure never stops the others.

        `on_result(node, result)` is called for EVERY node the moment its result is
        known (`result` is a `PluginRunResult`: output / exit code / error);
        `on_finished(results)` is called once with the whole list. Both are called on the
        GUI thread (the core marshals them), so a plugin may touch its own Qt objects
        there — the two callbacks are the only place a plugin sees live progress.

        `timeout` — the per-node budget in seconds (default 30). Never raises: a refused
        or failed start is a log line and False.
        """
        records = node_records(nodes)
        text = "" if command is None else str(command)
        try:
            budget = float(timeout) if timeout is not None else DEFAULT_COMMAND_TIMEOUT_S
        except (TypeError, ValueError):
            budget = DEFAULT_COMMAND_TIMEOUT_S
        if not records or not text.strip():
            self.log("run_command() refused: no nodes or an empty command")
            return False
        try:
            handler = getattr(self._core, "plugin_run_command", None)
            if callable(handler):
                return bool(handler(self._plugin_id, records, text,
                                    on_result if callable(on_result) else None,
                                    on_finished if callable(on_finished) else None,
                                    max(0.2, budget)))
        except Exception as e:  # noqa: BLE001
            self.log(f"run_command() failed: {type(e).__name__}: {e}")
        return False

    # ── diagnostics ───────────────────────────────────────────────────────────

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return f"<PluginContext {self._plugin_id!r} api={self._api_version}>"


def build_context(plugin_id: str, core=None, api_version: int = CONTEXT_API_VERSION) -> PluginContext:
    """The one place a record's context is built (the manager calls this)."""
    return PluginContext(plugin_id, core=core, api_version=api_version)


__all__ = ["PluginContext", "PluginNode", "PluginRunResult",
           "node_record", "node_records", "build_context", "run_result_from_dict",
           "NODE_FIELDS", "CONTEXT_API_VERSION",
           "DEFAULT_STATUS_TIMEOUT_MS", "DEFAULT_COMMAND_TIMEOUT_S"]
