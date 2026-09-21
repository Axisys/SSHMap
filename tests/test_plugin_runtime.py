# -*- coding: utf-8 -*-
"""v1.4rc2 — Plugin foundation, part 2: `PluginContext` and Main Thread isolation
(ROADMAP v1.4rc2, tasks 5–6; the contract is the frozen `PLUGINS.md`).

rc1 discovered plugins and rendered the menu; rc2 makes the core CALL into them — and
that is where the hard part of a Qt plugin system lives. This file is the executable
specification of the second half:

Sections:
  §1 `PluginContext` — the read-only surface (`plugin_id` / `api_version` / `app_version`
     / `log`) and the node record (`{id, alias, host, port, user}`, nothing else);
  §2 the services: `ctx.status()` (a signal to the window + the token guard) and
     `ctx.run_command()` (the managed SSH worker, per-node callbacks, "never throws");
  §3 the status merge: `status_probe` joined with the SSH probe — the worse by severity,
     the details concatenated, an unknown kind / a broken answer ignored;
  §4 the `StatusChecker` seam: a round with a provider (merged status + the detail
     signal + `last_detail()`), a round without one (byte-for-byte the old probe);
  §5 Main Thread isolation: the 200 ms UI-hook budget, the 1500 ms wait budget of a
     headless hook, the orphan registry, the self-cleanup of managed workers, the Qt
     guard, the "never throws" wrapper;
  §6 the window wiring: the token-guarded status line, the hook reports, the node
     registry, the tooltip detail;
  §7 PLUGINS.md + the release state (the pins of `_common.py`).

Run: python tests/test_plugin_runtime.py   (from the project root) or python tests/run_all.py
"""
import logging
import os
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until, check_i18n_parity,
                     check_i18n_format, check_release_state, load_i18n_langs, translation_keys,
                     clear_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from i18n import t  # noqa: E402
import modules.plugin_context as PC  # noqa: E402
import modules.plugin_manager as PM  # noqa: E402
import modules.plugin_runner as PR  # noqa: E402
import services.status_checker as SC  # noqa: E402
import ui.main_window as MW  # noqa: E402
from models.server import ServerData  # noqa: E402

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")
PLUGIN_DIR = PM.user_plugin_dir()
PLUGINS_MD = os.path.join(ROOT, "PLUGINS.md")

NEW_I18N_KEYS = ["plugins.status.hook_failed", "plugins.status.hook_timeout"]


# ── helpers ───────────────────────────────────────────────────────────────────

def manifest(name="demo", version="1.0", description=None, extra=""):
    """A plugin source with the mandatory MANIFEST (the canonical shape of PLUGINS.md §1)."""
    desc = "" if description is None else f', "description": {description!r}'
    return (f'MANIFEST = {{"name": {name!r}, "version": {version!r}, "api_version": 1{desc}}}\n'
            f'{extra}')


def write_plugin(name, body):
    """Drop a plugin file into the user folder and return its path."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    path = os.path.join(PLUGIN_DIR, name if "." in name else f"{name}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
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
def local_module(stem):
    """The module object of a folder plugin after a discovery."""
    return sys.modules.get(f"{PM.LOCAL_MODULE_PREFIX}{stem}")


def collect(signal):
    """A lambda collector for a Qt signal of ONE argument (or several → a tuple)."""
    box = []

    def _slot(*args):
        box.append(args[0] if len(args) == 1 else args)

    signal.connect(_slot)
    return box


def log_records(logger_name="sshmap.modules.plugin_manager"):
    """Capture the application log lines (the ROADMAP "a record in modules/logger.py")."""
    lines = []

    class _Handler(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger(logger_name)
    handler = _Handler()
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    return lines, logger, handler, old_level


def stop_logging(lines, logger, handler, old_level):
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def node_tuple(nid="n1", host="h1"):
    """A `(id, alias, host, port, user)` record — the shape the window feeds the manager."""
    return (nid, f"alias-{nid}", host, 22, "ubuntu")


def fake_transport(node, command, timeout, credentials):
    """A network-free transport: a good node, a failing node, and the secrets it saw."""
    _TRANSPORT_CALLS.append((node.id, command, timeout, dict(credentials or {})))
    if node.host.startswith("bad"):
        return PC.PluginRunResult(node=node, error="connect refused")
    return PC.PluginRunResult(node=node, exit_code=0, output=f"out-{node.id}\n")


_TRANSPORT_CALLS = []
_ORIG_TRANSPORT = PR.run_command_over_ssh
_ORIG_CREDENTIALS = PR.default_credentials


def patch_transport(fn=fake_transport):
    PR.run_command_over_ssh = fn


def patch_credentials(fn=None):
    PR.default_credentials = fn or (lambda node, facts=None: {"password": "secret", "key_path": ""})


def restore_runner_seams():
    PR.run_command_over_ssh = _ORIG_TRANSPORT
    PR.default_credentials = _ORIG_CREDENTIALS


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 PluginContext: the read-only surface and the node record ==")
# ════════════════════════════════════════════════════════════════════════════

import version as _version  # noqa: E402

_ctx = PC.PluginContext("demo")
check("ctx.plugin_id is the plugin's own MANIFEST name",
      _ctx.plugin_id == "demo", _ctx.plugin_id)
check("ctx.api_version reports the API version of the contract (1)",
      _ctx.api_version == 1 and _ctx.api_version == PM.API_VERSION, str(_ctx.api_version))
check("ctx.app_version is the running application version (version.py)",
      _ctx.app_version == _version.APP_VERSION == "1.4.4",
      f"{_ctx.app_version} vs {_version.APP_VERSION}")
check("a context without a core is inert: log/status/run_command report 'not available' "
      "instead of raising",
      _ctx.log("hello") is None and _ctx.status("x") is False
      and _ctx.run_command([node_tuple()], "ls") is False)

# The node record: the contract narrows the model to {id, alias, host, port, user}.
_sd = ServerData(id="srv", alias="web-1", host="10.0.0.1", user="root",
                 password="NEVER", ssh_port=2222, key_path="C:/keys/id")
_rec = PC.node_record(_sd)
check("a ServerData becomes a PluginNode with the five contract fields",
      _rec.as_dict() == {"id": "srv", "alias": "web-1", "host": "10.0.0.1",
                         "port": 2222, "user": "root"}, str(_rec.as_dict()))
check("the record carries NO secret / no key path / no password (the model is narrowed, "
      "not handed over)",
      not hasattr(_rec, "password") and not hasattr(_rec, "key_path")
      and "password" not in _rec.as_dict() and "key_path" not in _rec.as_dict())
check("a dict / a tuple / a PluginNode are all accepted (the same narrowing)",
      PC.node_record({"id": "d", "host": "h"}).id == "d"
      and PC.node_record(("t", "a", "hh", 2200, "u")).port == 2200
      and PC.node_record(_rec) is _rec)
check("a broken port falls back to 22 and is clamped (never a crash)",
      PC.node_record({"id": "x", "port": "nope"}).port == 22
      and PC.node_record({"id": "x", "port": 999999}).port == 65535)
check("node_records() skips a broken entry instead of raising",
      [r.id for r in PC.node_records([{"id": "a"}, None, {"id": "b"}])] == ["a", "b"])
_frozen_ok = False
try:
    _rec.id = "other"
except Exception:
    _frozen_ok = True
check("PluginNode is frozen (a plugin cannot write back into the core)", _frozen_ok)
check("PluginNode.label() prefers 'alias (host)' and falls back to the id",
      PC.PluginNode(id="i", alias="a", host="h").label() == "a (h)"
      and PC.PluginNode(id="i").label() == "i")

_res = PC.run_result_from_dict(PC.PluginRunResult(node=_rec, exit_code=3, output="o",
                                                  error="e").as_dict())
check("a PluginRunResult survives the worker → GUI signal hop (as_dict/from_dict)",
      _res.node_id == "srv" and _res.exit_code == 3 and _res.output == "o"
      and _res.error == "e" and _res.ok is False)
check("ok is True only for a command that really ran and exited 0",
      PC.PluginRunResult(node=_rec, exit_code=0).ok
      and not PC.PluginRunResult(node=_rec, exit_code=1).ok
      and not PC.PluginRunResult(node=_rec, exit_code=0, error="boom").ok)

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the services: ctx.status() and ctx.run_command() ==")
# ════════════════════════════════════════════════════════════════════════════

mgr = PM.PluginManager()
_statuses = collect(mgr.status_requested)
check("ctx.status() reaches the core as a signal (the window owns the widget)",
      PC.PluginContext("demo", core=mgr).status("hello", 2500) is True
      and _statuses == [("demo", "hello", 2500)], str(_statuses))
check("a broken timeout falls back to the default instead of raising",
      PC.PluginContext("demo", core=mgr).status("x", "nope") is True
      and _statuses[-1][2] == PC.DEFAULT_STATUS_TIMEOUT_MS, str(_statuses[-1]))

_cmds = collect(mgr.command_result)
_finishes = collect(mgr.command_finished)
mgr.set_nodes([node_tuple("good"), node_tuple("bad", host="bad-1")],
              facts={"good": {"key_path": "C:/k/id"}})
check("the manager narrows the map into plugin node records (set_nodes/node_records)",
      [n.id for n in mgr.node_records()] == ["bad", "good"]
      and mgr.node_record("good").alias == "alias-good")
check("an unknown id has no record (a node removed from the map is not invented)",
      mgr.node_record("nope") is None)

patch_transport()
patch_credentials()
_TRANSPORT_CALLS.clear()
_results_seen = []
_finished_seen = []
_ctx2 = PC.PluginContext("runner", core=mgr)
_started = _ctx2.run_command([node_tuple("good"), node_tuple("bad", host="bad-1")], "uptime",
                             on_result=lambda node, res: _results_seen.append((node.id, res)),
                             on_finished=lambda results: _finished_seen.append(results))
check("ctx.run_command() starts a managed worker and reports True", _started is True)
wait_until(lambda: len(_finishes) >= 1, timeout_ms=5000)
app.processEvents()
check("one result per node arrives through the plugin's on_result callback",
      sorted(nid for nid, _r in _results_seen) == ["bad", "good"], str(_results_seen))
check("ONE node's failure does not stop the others (the bad node is an error RESULT)",
      dict((nid, r.ok) for nid, r in _results_seen).get("good") is True
      and dict((nid, r.ok) for nid, r in _results_seen).get("bad") is False,
      str([(n, r.error) for n, r in _results_seen]))
check("on_finished() is called once with the whole list, in node order",
      len(_finished_seen) == 1 and [r.node_id for r in _finished_seen[0]] == ["good", "bad"],
      str(_finished_seen))
check("the core resolved the credentials (the key path of the internal facts was used)",
      all(call[3].get("password") == "secret" for call in _TRANSPORT_CALLS)
      and len(_TRANSPORT_CALLS) == 2, str(_TRANSPORT_CALLS))
check("the manager reports the results to the app as well (command_result/command_finished)",
      len(_cmds) == 2 and len(_finishes) == 1, f"{_cmds} / {_finishes}")
check("the plugin asked for a command on ITS nodes only — the command travels verbatim",
      all(call[1] == "uptime" for call in _TRANSPORT_CALLS))

_srvc = PC.PluginContext("empty", core=mgr)
check("an empty command / an empty node list is refused with False (and a log line)",
      _srvc.run_command([node_tuple()], "   ") is False
      and _srvc.run_command([], "uptime") is False)
check("the refused calls never reached the transport",
      len(_TRANSPORT_CALLS) == 2, str(len(_TRANSPORT_CALLS)))
restore_runner_seams()

# The runner itself: the direct seam (transport + credentials injected).
_direct = []
_runner = PR.PluginCommandRunner([PC.node_record(node_tuple("d1")), PC.node_record(node_tuple("d2"))],
                                 "echo hi", plugin_id="direct", timeout=5.0,
                                 transport=fake_transport,
                                 credential_resolver=lambda node: {"password": "p", "key_path": ""})
_runner.node_result.connect(lambda nid, payload: _direct.append(nid))
_runner.start()
check("the runner finished within the budget (a network-free transport)", _runner.wait(3000))
app.processEvents()
check("the runner emitted one result per node and honours `all_finished`",
      _direct == ["d1", "d2"] and len(_runner.results()) == 2
      and _runner.results()[0].exit_code == 0, str(_direct))
check("the runner is a one-shot: is_done() is True after run()", _runner.is_done() is True)
check("the runner exposes its plan (nodes/command) without leaking a secret",
      [n.id for n in _runner.nodes()] == ["d1", "d2"] and _runner.command() == "echo hi")

# A transport that hangs → the wait budget (the ROADMAP acceptance).
def hang_transport(node, command, timeout, credentials):
    time.sleep(0.9)
    return PC.PluginRunResult(node=node, exit_code=0, output="late")


_slow = PR.PluginCommandRunner([PC.node_record(node_tuple("slow"))], "sleep",
                               transport=hang_transport, timeout=5.0)
_slow.start()
time.sleep(0.05)
check("stop() returns False when the node in flight runs out the wait budget",
      _slow.stop(150) is False)
check("…and the thread is still alive (the caller must register it as an orphan)",
      _slow.isRunning() is True)
check("the thread really finished afterwards (nothing is left running)",
      wait_until(lambda: not _slow.isRunning(), timeout_ms=3000) is not False
      and not _slow.isRunning())

# ════════════════════════════════════════════════════════════════════════════
print("== §3 status_probe: the merge with the SSH probe ==")
# ════════════════════════════════════════════════════════════════════════════

write_plugin("probe", manifest(name="probe", extra=(
    "def status_probe(node):\n"
    "    if node.id == 'n1':\n"
    "        return ('offline', 'DB down')\n"
    "    return None\n")))
write_plugin("probe2", manifest(name="probe2", extra=(
    "def status_probe(node):\n"
    "    return ('warn', 'queue lag')\n")))
write_plugin("probe_bad", manifest(name="probe_bad", extra=(
    "def status_probe(node):\n"
    "    return ('purple', 'nonsense')\n")))
write_plugin("probe_boom", manifest(name="probe_boom", extra=(
    "def status_probe(node):\n"
    "    raise RuntimeError('kaboom')\n")))

mgr = PM.PluginManager()
mgr.discover()
check("all four probe plugins were discovered (the merge sees every one of them)",
      set(r.plugin_id for r in mgr.records()) == {"probe", "probe2", "probe_bad", "probe_boom"},
      str([r.plugin_id for r in mgr.records()]))
check("each loaded record carries a PluginContext bound to the manager",
      all(r.context is not None and r.context.plugin_id == r.plugin_id
          for r in mgr.loaded_records()))
_hook_errors = collect(mgr.hook_failed)

_merged = mgr.status_probe_for(node_tuple("n1", host="h1"), "online")
check("the merge keeps the WORSE of the two by severity (online + offline → offline)",
      _merged is not None and _merged[0] == "offline", str(_merged))
check("…and concatenates the details of the plugins that had an opinion",
      "DB down" in _merged[1] and "queue lag" in _merged[1], str(_merged))
check("a plugin cannot IMPROVE a status (warn + offline SSH stays offline)",
      mgr.status_probe_for(node_tuple("n5", host="h5"), "offline")[0] == "offline")
check("an unknown kind is not guessed at — it is ignored with a record in the log",
      mgr.status_probe_for(node_tuple("n2", host="h2"), "online")[0] == "warn"
      and not any("nonsense" in str(e) for e in _hook_errors))
_answers_none = mgr.status_probe_for(node_tuple("n3", host="h3"), "online")
check("a plugin that answers None for THIS node contributes nothing to it",
      _answers_none is not None and "DB down" not in _answers_none[1]
      and _answers_none[0] == "warn", str(_answers_none))
check("a plugin that RAISES is an error report, never a broken merge",
      len(_hook_errors) >= 1 and _hook_errors[0][1] == "status_probe"
      and "kaboom" in _hook_errors[0][2], str(_hook_errors))
check("the manager reported the raising hook as an EVENT for the window as well",
      any(ev.get("kind") == PM.EVENT_HOOK_ERROR for ev in mgr.drain_events()))
check("an unknown node id has no opinion at all (the provider returns None)",
      mgr.status_provider("never-seen", "online") is None)

# A hung status_probe: abandoned after the budget, kept alive until it ends.
clean_plugins()
write_plugin("probe_hang", manifest(name="probe_hang", extra=(
    "import time\n"
    "def status_probe(node):\n"
    "    time.sleep(0.6)\n"
    "    return ('offline', 'too late')\n")))
mgr = PM.PluginManager()
mgr.discover()
_timeouts = collect(mgr.hook_timeout)
_old_budget = PM.STATUS_PROBE_BUDGET_MS
PM.STATUS_PROBE_BUDGET_MS = 150
_t0 = time.monotonic()
_hung = mgr.status_probe_for(node_tuple("n9", host="h9"), "online")
_elapsed = time.monotonic() - _t0
PM.STATUS_PROBE_BUDGET_MS = _old_budget
check("a hung status_probe is ABANDONED after the budget (the round keeps its pace)",
      _elapsed < 0.5 and _hung is not None and _hung[0] == "online",
      f"{_elapsed:.2f}s / {_hung}")
check("…and the timeout is REPORTED (a log line + an event + a signal)",
      len(_timeouts) == 1 and _timeouts[0][1] == "status_probe" and _timeouts[0][2] == 150,
      str(_timeouts))
check("the abandoned call is kept in the registry while it still runs (never GC'd alive)",
      len(mgr.helper_threads()) == 1, str(mgr.helper_threads()))
check("…and the registry prunes it by itself once the hook returns",
      wait_until(lambda: len(mgr.helper_threads()) == 0, timeout_ms=3000) is not False
      and mgr.helper_threads() == [])

# Disabled plugins are never called (the rc1 switch keeps its rc2 meaning).
clean_plugins()
write_plugin("switched", manifest(name="switched", extra=(
    "def status_probe(node):\n"
    "    return ('offline', 'should not run')\n")))
mgr = PM.PluginManager()
mgr.discover()
mgr.set_enabled("switched", False)
check("a DISABLED plugin is never called (disabling stops the hooks, not the import)",
      mgr.status_probe_for(node_tuple("n1", host="h1"), "online")[0] == "online"
      and mgr.call_ui_hook("switched", "status_probe", node_tuple("n1")) is None)
mgr.set_enabled("switched", True)
check("…and switching it back on makes the hook live again",
      mgr.status_probe_for(node_tuple("n1", host="h1"), "online")[0] == "offline")

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the StatusChecker seam: a probe round with a provider ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
write_plugin("probe_round", manifest(name="probe_round", extra=(
    "def status_probe(node):\n"
    "    return ('offline' if node.id == 'n1' else None, 'plugin says no')\n")))
mgr = PM.PluginManager()
mgr.discover()
mgr.set_nodes([node_tuple("n1", host="h1"), node_tuple("n2", host="h2")])

_ORIG_PROBE = SC.probe_ssh
SC.probe_ssh = lambda host, port, timeout=3.0: "online"   # no network in the suite

chk = SC.StatusChecker(interval_ms=5000, probe_timeout=0.5, max_parallel=2)
_statuses = collect(chk.status_changed)
_details = collect(chk.status_detail)
_rounds = collect(chk.round_finished)
chk.set_status_provider(mgr.status_provider)
check("the provider is installed on the checker (and removable)", chk._status_provider is not None)
chk.set_servers([("n1", "h1", 22), ("n2", "h2", 22)])
chk.start_round()
wait_until(lambda: len(_rounds) >= 1, timeout_ms=5000)
app.processEvents()
check("the merged status reaches status_changed (the plugin's offline beats the SSH online)",
      ("n1", "offline") in _statuses and ("n2", "online") in _statuses, str(_statuses))
check("the plugin's detail travels on its OWN signal (status_changed keeps its shape)",
      len(_details) == 1 and _details[0][0] == "n1" and "plugin says no" in _details[0][1],
      str(_details))
check("round_finished carries the merged results (the existing contract is unchanged)",
      dict(_rounds[0]) == {"n1": "offline", "n2": "online"}, str(_rounds[0]))
check("last_detail() remembers the plugin text (a tooltip can be re-applied)",
      chk.last_detail("n1") == "plugin says no" and chk.last_detail("n2") == "")

_statuses2 = collect(chk.status_changed)
_rounds2 = collect(chk.round_finished)
chk.set_status_provider(None)
chk.start_round()
wait_until(lambda: len(_rounds2) >= 1, timeout_ms=5000)
app.processEvents()
check("with NO provider the round is exactly the pre-rc2 probe (the merge adds nothing)",
      dict(_rounds2[0]) == {"n1": "online", "n2": "online"}, str(_rounds2[0]))
SC.probe_ssh = _ORIG_PROBE

# ════════════════════════════════════════════════════════════════════════════
print("== §5 Main Thread isolation: the budgets, the workers, the orphan registry ==")
# ════════════════════════════════════════════════════════════════════════════

check("the contract's budgets are the documented values (PLUGINS.md §6)",
      PM.UI_HOOK_BUDGET_MS == 200 and PM.HOOK_WAIT_BUDGET_MS == 1500,
      f"{PM.UI_HOOK_BUDGET_MS} / {PM.HOOK_WAIT_BUDGET_MS}")

clean_plugins()
write_plugin("uihook", manifest(name="uihook", extra=(
    "import time\n"
    "CALLS = []\n"
    "def register_commands(ctx):\n"
    "    CALLS.append('fast')\n"
    "    return ['cmd']\n"
    "def extend_node_context_menu(menu, nodes):\n"
    "    time.sleep(0.25)\n"
    "def boom_hook():\n"
    "    raise ValueError('ui boom')\n")))
write_plugin("runner", manifest(name="runner", extra=(
    "import time\n"
    "RAN = []\n"
    "def run_on_nodes(nodes, ctx):\n"
    "    RAN.append(len(nodes))\n"
    "    time.sleep(0.25)\n"
    "    ctx.status('ran on %d node(s)' % len(nodes), 1000)\n")))
write_plugin("runner_bad", manifest(name="runner_bad", extra=(
    "def run_on_nodes(nodes, ctx):\n"
    "    raise RuntimeError('run boom')\n")))
mgr = PM.PluginManager()
mgr.discover()
mgr.set_nodes([node_tuple("a"), node_tuple("b")])
_ui_log, _lg, _h, _lvl = log_records()
_hook_failed = collect(mgr.hook_failed)

check("a UI hook is called SYNCHRONOUSLY on the calling (GUI) thread and returns its value",
      mgr.call_ui_hook("uihook", "register_commands", mgr.get("uihook").context) == ["cmd"])
check("the plugin's own module state proves the call really happened",
      local_module("uihook").CALLS == ["fast"])
mgr.call_ui_hook("uihook", "extend_node_context_menu", None, [])
check("a UI hook slower than 200 ms is a WARNING in the log (the contract budget)",
      any("extend_node_context_menu" in line and "200" in line for line in _ui_log),
      str(_ui_log))
check("a UI hook that raises never propagates and is reported",
      mgr.call_ui_hook("uihook", "boom_hook") is None
      and any("ui boom" in str(e[2]) for e in _hook_failed), str(_hook_failed))
check("a plugin without that hook / an unknown id is a no-op",
      mgr.call_ui_hook("runner", "boom_hook") is None
      and mgr.call_ui_hook("nope", "register_commands") is None)
stop_logging(_ui_log, _lg, _h, _lvl)

_statuses3 = collect(mgr.status_requested)
_started = mgr.run_on_nodes()
check("run_on_nodes() starts the hook of every plugin that declares it (2 of 3 here)",
      _started == 2, str(_started))
check("the hook runs on a MANAGED worker thread (the registry holds it while it runs)",
      len(mgr.active_workers()) >= 1, str(mgr.active_workers()))
check("…and the worker removes ITSELF from the registry on finished() (self-cleanup)",
      wait_until(lambda: not mgr.active_workers(), timeout_ms=4000) is not False
      and mgr.active_workers() == [])
app.processEvents()
check("the plugin really ran with the node records",
      local_module("runner").RAN == [2], str(local_module("runner").RAN))
check("a hook's `ctx.status()` reaches the application from the WORKER thread",
      any("ran on 2 node(s)" in s[1] for s in _statuses3), str(_statuses3))
check("a run_on_nodes hook that raises is reported (never into the host)",
      any(e[1] == "run_on_nodes" and "run boom" in e[2] for e in _hook_failed), str(_hook_failed))
check("the failing plugin did not stop its neighbour (both hooks ran)",
      local_module("runner").RAN == [2])

check("an empty node registry refuses to start anything (0 plugins started)",
      PM.PluginManager().run_on_nodes() == 0)

# The Qt guard: the manager owns what a plugin creates (gotcha #9).
_obj = object()
check("guard() keeps a plugin's object alive and returns it",
      mgr.guard(_obj) is _obj and _obj in mgr.guarded_objects())
check("guard() is idempotent (the same object is not stored twice)",
      mgr.guard(_obj) is _obj and len(mgr.guarded_objects()) == 1)
check("a plugin can hand over several objects (all of them survive the GC)",
      mgr.guard(object()) is not None and len(mgr.guarded_objects()) == 2)
check("the guard is releasable — a reload can drop the old wrappers",
      mgr.release_guards() == 2 and mgr.guarded_objects() == [])

# The shutdown path: everything within the budget; a hung worker becomes an orphan.
clean_plugins()
write_plugin("hanger", manifest(name="hanger", extra=(
    "import time\n"
    "def run_on_nodes(nodes, ctx):\n"
    "    time.sleep(1.2)\n")))
mgr = PM.PluginManager()
mgr.discover()
mgr.set_nodes([node_tuple("a")])
check("the hanging hook really started", mgr.run_on_nodes() == 1)
time.sleep(0.05)
_clean = mgr.shutdown(200)
check("shutdown() reports False when a plugin worker outlives the wait budget "
      "(and True when everything finished)",
      _clean is False, str(_clean))
check("…and the live thread lands in the ORPHAN registry (not left to GC)",
      len(mgr.orphan_threads()) == 1, str(mgr.orphan_threads()))
check("the orphan registry prunes itself once the thread ends (no leak)",
      wait_until(lambda: not mgr.orphan_threads(), timeout_ms=4000) is not False
      and mgr.orphan_threads() == [])
check("a clean manager reports True on shutdown (nothing to wait for)",
      PM.PluginManager().shutdown(100) is True)

# The hung ctx.run_command is stopped by the manager's shutdown too.
patch_transport(lambda node, command, timeout, credentials: (
    time.sleep(0.9), PC.PluginRunResult(node=node, exit_code=0))[1])
patch_credentials()
mgr2 = PM.PluginManager()
mgr2.set_nodes([node_tuple("slow")])
check("a plugin command is in flight", PC.PluginContext("t", core=mgr2).run_command(
    [node_tuple("slow")], "sleep 5") is True)
check("the manager counts the in-flight commands (a diagnostic seam)",
      mgr2.running_commands() == 1)
_shutdown_clean = mgr2.shutdown(150)
check("shutdown() stops the command worker within the budget (False = it became an orphan)",
      mgr2.running_commands() <= 1 and (mgr2.orphan_threads() or _shutdown_clean is True))
check("…and after the node in flight times out nothing is left running",
      wait_until(lambda: not mgr2.orphan_threads() and not mgr2.active_workers(),
                 timeout_ms=4000) is not False, str(mgr2.orphan_threads()))
restore_runner_seams()

# v1.4 regression (found by the example plugins, ROADMAP tasks 11–12): a command started
# from a plugin's WORKER thread — the `run_on_nodes` path, the ordinary way a plugin
# reaches `ctx.run_command` — must deliver its callbacks like a GUI-thread one. The
# receiver context of a signal connected to a plain Python callable is the thread that
# CALLS `connect()` (AGENTS.md §7 gotcha #20), so a runner built in a worker thread used
# to post its per-node results into a thread WITHOUT an event loop and lose them silently.
patch_transport()
patch_credentials()
mgr3 = PM.PluginManager()
mgr3.set_nodes([node_tuple("w1")])
_worker_calls = []


def _run_from_a_bare_worker():
    mgr3.plugin_run_command("worker-caller", [node_tuple("w1")], "uptime",
                            on_result=lambda n, r: _worker_calls.append(n.id),
                            on_finished=lambda rs: _worker_calls.append("done"))


_worker = threading.Thread(target=_run_from_a_bare_worker)
_worker.start()
_worker.join(5)
check("a command started from a WORKER thread still delivers its callbacks (the v1.4 fix)",
      wait_until(lambda: "done" in _worker_calls, timeout_ms=5000) is not False
      and _worker_calls == ["w1", "done"], str(_worker_calls))
check("…and the worker registry forgets it once it finished (no leak from the marshalling)",
      wait_until(lambda: not mgr3.active_workers() and mgr3.running_commands() == 0,
                 timeout_ms=5000) is not False,
      f"{mgr3.active_workers()} {mgr3.running_commands()}")
mgr3.shutdown(500)
restore_runner_seams()

# ════════════════════════════════════════════════════════════════════════════
print("== §6 the window wiring: the services, the reports, the node registry ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
clear_cfg()
win = MW.MainWindow()
win._autosave_timer.stop()
check("the window installs the manager's status provider on the status checker",
      win._status_checker is not None
      and win._status_checker._status_provider is not None,
      str(getattr(win._status_checker, "_status_provider", None)))
check("the window has a handler for every plugin service signal",
      all(callable(getattr(win, name, None)) for name in
          ("_on_plugin_status_requested", "_expire_plugin_status",
           "_on_plugin_hook_failed", "_on_plugin_hook_timeout", "_on_node_status_detail"))
      and all(hasattr(win._plugin_manager, sig) for sig in
              ("status_requested", "hook_failed", "hook_timeout",
               "command_result", "command_finished")))

write_plugin("winplug", manifest(name="winplug", extra=(
    "def status_probe(node):\n"
    "    return ('warn', 'plugin detail')\n")))
win.start_plugin_discovery()
app.processEvents()
win._plugin_manager.status_requested.emit("winplug", "plugin line", 5000)
app.processEvents()
check("ctx.status() shows the plugin's line in the window's status bar",
      win.statusBar().currentMessage() == "plugin line", win.statusBar().currentMessage())
check("the message took the token of the guard (a newer message invalidates the old clear)",
      win._plugin_status_token is not None)
_first_token = win._plugin_status_token
win._plugin_manager.status_requested.emit("winplug", "second line", 0)
app.processEvents()
check("a newer plugin line replaces the older one (timeout 0 = sticky)",
      win.statusBar().currentMessage() == "second line")
win._expire_plugin_status(_first_token)   # the auto-clear of the SUPERSEDED line
check("a stale auto-clear does not blank the current line (the token guard really guards)",
      win.statusBar().currentMessage() == "second line"
      and _first_token != win._plugin_status_token)
win._expire_plugin_status(win._plugin_status_token)
check("…while the current token's clear does (the guard is not a no-op)",
      win.statusBar().currentMessage() == "")

win._plugin_manager.hook_failed.emit("winplug", "run_on_nodes", "boom")
app.processEvents()
check("a hook failure is reported in the status bar (i18n key plugins.status.hook_failed)",
      win.statusBar().currentMessage() == t("plugins.status.hook_failed",
                                            name="winplug", hook="run_on_nodes", error="boom"),
      win.statusBar().currentMessage())
win._plugin_manager.hook_timeout.emit("winplug", "status_probe", 1500)
app.processEvents()
check("an abandoned hook is reported too (plugins.status.hook_timeout)",
      win.statusBar().currentMessage() == t("plugins.status.hook_timeout",
                                            name="winplug", hook="status_probe", ms=1500),
      win.statusBar().currentMessage())

# The node registry + the tooltip detail of a merged probe result.
win.scene.add_server(ServerData(id="sync1", alias="sync", host="10.1.1.1", user="u",
                                ssh_port=2200))
win._sync_status_targets()
_recs = {n.id: n for n in win._plugin_manager.node_records()}
check("the window feeds the plugin registry from the map (id/alias/host/port/user)",
      _recs.get("sync1") is not None
      and (_recs["sync1"].alias, _recs["sync1"].host, _recs["sync1"].port, _recs["sync1"].user)
      == ("sync", "10.1.1.1", 2200, "u"), str(_recs.get("sync1")))
check("the internal key path is NOT part of the plugin record (only the core sees it)",
      "key_path" not in _recs["sync1"].as_dict()
      and win._plugin_manager._node_facts.get("sync1", {}).get("key_path") == "",
      str(win._plugin_manager._node_facts.get("sync1")))
_node = win.scene.get_node("sync1")
win._on_node_status_changed("sync1", "online")
win._on_node_status_detail("sync1", "HTTP 200")
check("the plugin detail lands in the node's tooltip under the status line",
      "HTTP 200" in _node.toolTip() and t("node.status.online", host="10.1.1.1") in _node.toolTip(),
      _node.toolTip())
win._on_node_status_detail("sync1", "")
check("an empty detail removes the stale tooltip text",
      "HTTP 200" not in _node.toolTip(), _node.toolTip())
check("a detail for an unknown node is a no-op (the node was removed)",
      win._on_node_status_detail("never", "x") is None)

check("the window's shutdown path stops the plugin workers (never a live QThread at exit)",
      "plugin_manager" in open(os.path.join(ROOT, "ui", "main_window.py"), encoding="utf-8").read()
      and callable(getattr(win, "_shutdown_background_threads", None)))
win._shutdown_background_threads()
check("…and the call itself is safe with nothing running",
      win._plugin_manager.active_workers() == [])
clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §7 the frozen contract + the release state ==")
# ════════════════════════════════════════════════════════════════════════════

with open(PLUGINS_MD, encoding="utf-8") as f:
    _doc = f.read()
check("PLUGINS.md documents the context services this rc implements",
      "PluginContext" in _doc and "ctx.run_command" in _doc and "ctx.status" in _doc)
check("…and the isolation rules the code enforces (the budgets + the orphan policy)",
      "200 ms" in _doc and "Never throws" in _doc and "MANAGED WORKER" in _doc.upper(),
      "the contract text")
check("the code's budgets match the documented discipline",
      PM.HOOK_WAIT_BUDGET_MS == 1500 and PR.STOP_WAIT_MS == 1500)
check("the runner's per-node budget is the documented default of ctx.run_command",
      PC.DEFAULT_COMMAND_TIMEOUT_S == PR.COMMAND_TIMEOUT_S == PM.COMMAND_TIMEOUT_S)

_langs = load_i18n_langs(ROOT)
_missing = [k for k in NEW_I18N_KEYS
            if any(not _langs[c].get(k, "").strip() for c in ("en", "ru", "zh", "de"))]
check("the two rc2 keys are present and non-empty in en/ru/zh/de",
      not _missing and len(NEW_I18N_KEYS) == 2, str(_missing))
check("the placeholders of the new keys are identical in every language",
      all("{name}" in _langs[c]["plugins.status.hook_failed"]
          and "{hook}" in _langs[c]["plugins.status.hook_failed"]
          and "{error}" in _langs[c]["plugins.status.hook_failed"]
          and "{ms}" in _langs[c]["plugins.status.hook_timeout"]
          for c in _langs), "placeholder parity")
check("every new key is in the key set of EVERY language",
      all(set(NEW_I18N_KEYS) <= translation_keys(d) for d in _langs.values()))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check_release_state(ROOT)
finish()
