# -*- coding: utf-8 -*-
"""v1.4rc2 (plugin foundation, ROADMAP tasks 5–6): the managed SSH worker of `ctx.run_command`.

`PluginContext.run_command()` is a **service the core performs** (PLUGINS.md §5): the
plugin hands over node records and a shell command, and the core does the rest —
resolving the credentials, opening the connection, running the command, reporting one
result per node. This module is that worker.

**One-shot QThread, per-node results.** `PluginCommandRunner` walks the node list in
order and emits `node_result(node_id, dict)` the moment a node's result is known
(output / exit code / error), then `all_finished(list)` once. A failure on one node is
a RESULT for that node — the loop continues with the rest, so one unreachable server can
never hide the answer from its neighbours (the acceptance of ROADMAP rc2).

**Credentials are the core's business.** The default resolver reads the password from
the OS keyring by node id (`services/credential_manager.py` — the same allowlist
singleton the rest of the app uses) and the private key path from the internal node
FACTS the window registers; the password is passed to paramiko and is never logged,
never serialized and never handed to a plugin. Both the resolver and the network
transport are injectable seams — that is how the suite tests the whole worker without a
socket (`tests/test_plugin_runtime.py`).

**A bounded life.** `stop(wait_ms)` sets the cancel flag (a node that has not started is
skipped) and waits for the thread with a budget; the connection uses one timeout for
connect/auth/banner and one for the channel, so the worker cannot hang forever on a
black-holed host. The manager owns the registry this thread is registered in
(ROADMAP rc2 task 6: the worker registry + the orphan registry).

The module has no UI, no i18n and no window: it reports FACTS and never raises.
"""

import threading
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from modules.plugin_context import PluginNode, PluginRunResult, node_record

COMMAND_TIMEOUT_S = 30.0      # per-node budget (connect + command) — the `timeout=` default
STOP_WAIT_MS = 1500           # the wait budget of `stop()` (the v1.2 orphan-registry budget)
OUTPUT_MAX = 1_000_000        # a cap on the captured stdout/stderr (bytes of text)
ERROR_MAX = 300               # an error text is a tooltip line, not a log dump


def _short(text, limit: int = ERROR_MAX) -> str:
    """One-line, length-capped text (a result travels to a status bar and a tooltip)."""
    flat = " ".join(str(text or "").split())
    return flat[:limit] + "…" if len(flat) > limit else flat


def default_credentials(node: PluginNode, node_facts: Optional[Dict[str, dict]] = None) -> dict:
    """The core's credential resolution for one node: `{"password": …, "key_path": …}`.

    The password comes from the OS keyring (by node id, the allowlist singleton of
    `services/credential_manager.py`); the private key path comes from the internal node
    FACTS the window registered (it is deliberately NOT part of the plugin-visible node
    record). Never raises and never logs a secret.
    """
    password = ""
    try:
        from services.credential_manager import get_credential_manager
        password = get_credential_manager().load_password(node.id) or ""
    except Exception:  # noqa: BLE001 — no keyring → the app still works (key/agent auth)
        password = ""
    facts = (node_facts or {}).get(node.id) or {}
    try:
        key_path = str(facts.get("key_path") or "")
    except Exception:  # noqa: BLE001
        key_path = ""
    return {"password": password, "key_path": key_path}


def run_command_over_ssh(node: PluginNode, command: str, timeout: float = COMMAND_TIMEOUT_S,
                         credentials: Optional[dict] = None) -> PluginRunResult:
    """The default transport: one paramiko connection + `exec_command` on ONE node.

    Returns a `PluginRunResult` for every outcome — a connection error, an
    authentication error, a changed host key and a timeout are RESULTS, never
    exceptions (the caller is a plugin's asynchronous callback, not an error handler).
    The known_hosts policy is the application's (`modules/host_key_policy.py`, TOFU with
    the MITM guard on a changed key), so a plugin command is exactly as safe as a
    connection made by the app itself.
    """
    credentials = credentials or {}
    password = str(credentials.get("password") or "")
    key_path = str(credentials.get("key_path") or "")
    client = None
    try:
        import paramiko
        from modules.host_key_policy import SshKnownHostsPolicy

        client = paramiko.SSHClient()
        policy = SshKnownHostsPolicy(hostname=node.host, port=node.port)
        policy.apply_to_client(client)

        kwargs = dict(hostname=node.host, username=node.user, port=node.port,
                      timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
        if key_path:
            kwargs.update(key_filename=key_path, look_for_keys=False, allow_agent=True)
            if password:
                kwargs["password"] = password
        elif password:
            kwargs.update(password=password, look_for_keys=False, allow_agent=False)
        else:
            kwargs.update(look_for_keys=True, allow_agent=True)
        client.connect(**kwargs)

        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        try:
            stdin.close()
        except Exception:  # noqa: BLE001 — a closed stdin is not an error
            pass
        output = stdout.read().decode("utf-8", errors="replace")[:OUTPUT_MAX]
        error_out = stderr.read().decode("utf-8", errors="replace")[:OUTPUT_MAX]
        try:
            exit_code = int(stdout.channel.recv_exit_status())
        except Exception:  # noqa: BLE001 — a channel without a status
            exit_code = -1
        if error_out.strip() and not output.strip():
            # A command that wrote only to stderr still ran: the text goes into `error`
            # (the plugin's only place for it) but the exit code is the truth.
            return PluginRunResult(node=node, exit_code=exit_code, output="",
                                   error=_short(error_out))
        return PluginRunResult(node=node, exit_code=exit_code, output=output,
                               error=_short(error_out) if exit_code not in (0, 1) else "")
    except BaseException as exc:  # noqa: BLE001 — a plugin command must not raise into the app
        name = type(exc).__name__
        text = str(exc)
        if "BadHostKey" in name:
            text = f"host key changed — refusing to connect: {text}"
        elif "Authentication" in name:
            text = f"authentication failed: {text}"
        return PluginRunResult(node=node, error=_short(f"{name}: {text}" if text else name))
    finally:
        try:
            if client is not None:
                client.close()
        except Exception:  # noqa: BLE001
            pass


class PluginCommandRunner(QThread):
    """One `ctx.run_command` call: the nodes of the call, in order, on a worker thread.

    Signals:
        node_result(str, dict)  — (node_id, `PluginRunResult.as_dict()`) per node
        all_finished(list)      — the list of result dicts, once, in node order

    Both are emitted from the worker thread and delivered to the GUI thread by Qt, so a
    plugin's `on_result` / `on_finished` callbacks may touch its own Qt objects.
    """

    node_result = Signal(str, dict)
    all_finished = Signal(list)

    def __init__(self, nodes, command: str, plugin_id: str = "",
                 timeout: float = COMMAND_TIMEOUT_S,
                 transport: Optional[Callable] = None,
                 credential_resolver: Optional[Callable] = None,
                 node_facts: Optional[Dict[str, dict]] = None,
                 parent=None):
        super().__init__(parent)
        self._nodes: List[PluginNode] = [node_record(n) for n in (nodes or ())]
        self._command = str(command or "")
        self.plugin_id = str(plugin_id or "")
        try:
            self._timeout = max(0.2, float(timeout))
        except (TypeError, ValueError):
            self._timeout = COMMAND_TIMEOUT_S
        self._transport = transport or run_command_over_ssh
        self._node_facts = dict(node_facts or {})
        self._credential_resolver = credential_resolver
        self._cancel = threading.Event()
        self._results: List[PluginRunResult] = []
        self._done = False

    # ── the plan ──────────────────────────────────────────────────────────────

    def nodes(self) -> List[PluginNode]:
        """The node records of this call (the order the results arrive in)."""
        return list(self._nodes)

    def command(self) -> str:
        """The command this call runs (read-only; no secret is ever involved)."""
        return self._command

    def results(self) -> List[PluginRunResult]:
        """The results known so far (the whole list once the thread finished)."""
        return list(self._results)

    def is_done(self) -> bool:
        """True once `run()` returned (the thread may still be finishing its signals)."""
        return self._done

    # ── cancellation (the wait-budget contract) ───────────────────────────────

    def cancel(self) -> None:
        """Ask the loop to stop: a node that has NOT started is skipped (never raises)."""
        self._cancel.set()

    def stop(self, wait_ms: int = STOP_WAIT_MS) -> bool:
        """Cancel + wait for the thread with a budget (True = it finished in time).

        A node in flight runs out its own network timeout, so the caller must treat
        False as "still running" — the runner's owner (the manager) registers such a
        thread in the orphan registry instead of letting it be collected alive.
        """
        self.cancel()
        try:
            if not self.isRunning():
                return True
            return bool(self.wait(int(wait_ms)))
        except RuntimeError:
            return True  # the C++ object is already gone — nothing is running

    # ── the worker ────────────────────────────────────────────────────────────

    def _credentials(self, node: PluginNode) -> dict:
        if self._credential_resolver is not None:
            try:
                resolved = self._credential_resolver(node)
                return dict(resolved) if isinstance(resolved, dict) else {}
            except Exception as e:  # noqa: BLE001 — a broken resolver is "no credentials"
                _log_line("warning", f"plugin {self.plugin_id!r}: credential resolution "
                                     f"failed for {node.id!r}: {type(e).__name__}: {e}")
                return {}
        return default_credentials(node, self._node_facts)

    def _run_one(self, node: PluginNode) -> PluginRunResult:
        if self._cancel.is_set():
            return PluginRunResult(node=node, error="cancelled")
        try:
            result = self._transport(node, self._command, self._timeout, self._credentials(node))
        except BaseException as exc:  # noqa: BLE001 — one node's error must not stop the rest
            return PluginRunResult(node=node, error=_short(f"{type(exc).__name__}: {exc}"))
        if not isinstance(result, PluginRunResult):
            return PluginRunResult(node=node, error=f"transport returned {type(result).__name__}")
        return result

    def run(self):  # noqa: C901 — a flat loop with early exits
        results: List[PluginRunResult] = []
        try:
            for node in self._nodes:
                if self._cancel.is_set():
                    break  # a node that has not started is skipped (the round is over)
                result = self._run_one(node)
                results.append(result)
                try:
                    self.node_result.emit(result.node_id, result.as_dict())
                except RuntimeError:
                    pass  # Qt teardown — the receiver is gone, the loop still completes
        finally:
            self._results = results
            self._done = True
            try:
                self.all_finished.emit([r.as_dict() for r in results])
            except RuntimeError:
                pass  # Qt teardown


def _log_line(level: str, message: str) -> None:
    """Log without ever raising (the logger may be uninitialized)."""
    try:
        from modules.logger import get_logger
        getattr(get_logger("modules.plugin_runner"), level)(message)
    except Exception:  # noqa: BLE001
        pass


__all__ = ["PluginCommandRunner", "run_command_over_ssh", "default_credentials",
           "COMMAND_TIMEOUT_S", "STOP_WAIT_MS"]
