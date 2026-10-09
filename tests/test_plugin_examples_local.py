# -*- coding: utf-8 -*-
"""v1.9.4 — the two examples whose fact is LOCAL (`examples/plugins/certificates.py`, `watch_command.py`).

Both load through the REAL discovery path of `PluginManager` (copied into the isolated
`~/.sshmap/plugins/`, then `discover()`) and are driven without a socket.
§1 the two files as plugins (the manifests, the hooks, the SHARED isolation predicate); §2
`certificates` — the plugin that NEVER calls `ctx.run_command` (the source read, its own settings, the
port rule); §3 its injected TLS connector and the horizon; §4 the real connector against a closed
local endpoint; §5 `watch_command` — the plugin whose settings ARE the fact (validation, the template,
the grouping); §6 its collector (the VERBATIM command, one call per distinct command); §7 its
reporter; §8 the release state."""
import ast
import json
import os
import shutil
import socket
import ssl
import sys
import time

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, translation_keys,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, clear_cfg,
                     example_plugin_problems, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import modules.plugin_manager as PM  # noqa: E402

EXAMPLES_DIR = os.path.join(ROOT, "examples")
PLUGINS_SRC = os.path.join(EXAMPLES_DIR, "plugins")
CERTIFICATES_SRC = os.path.join(PLUGINS_SRC, "certificates.py")
WATCH_SRC = os.path.join(PLUGINS_SRC, "watch_command.py")
PLUGIN_DIR = PM.user_plugin_dir()

EXAMPLE_FILES = ((CERTIFICATES_SRC, "certificates", (PM.HOOK_STATUS_PROBE,)),
                 (WATCH_SRC, "watch_command", (PM.HOOK_REGISTER_COMMANDS, PM.HOOK_STATUS_PROBE,
                                               PM.HOOK_RUN_ON_NODES)))


# ── helpers ──────────────────────────────────────────────────────────────────

def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def body(source, name):
    """The body of ONE top-level function of a plugin file (the source read of a hook)."""
    return source.split(f"def {name}")[1].split("\ndef ")[0]


def called_names(source):
    """Every name the file really CALLS (the AST — a docstring that NAMES a service is not a call)."""
    names = set()
    for item in ast.walk(ast.parse(source)):
        if not isinstance(item, ast.Call):
            continue
        target = item.func
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


def clean_plugins():
    """Empty the user plugin folder (the copied examples, their files, the import cache)."""
    if os.path.isdir(PLUGIN_DIR):
        for name in os.listdir(PLUGIN_DIR):
            try:
                os.remove(os.path.join(PLUGIN_DIR, name))
            except OSError:
                pass
    for key in [k for k in sys.modules if k.startswith(PM.LOCAL_MODULE_PREFIX)]:
        sys.modules.pop(key, None)


def install_examples():
    """Copy the two examples into the sandbox plugin folder — what a user does by hand."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    for src, _stem, _hooks in EXAMPLE_FILES:
        shutil.copyfile(src, os.path.join(PLUGIN_DIR, os.path.basename(src)))


def local(stem):
    """The imported module of a folder plugin (the discovery really exec'd the file)."""
    return sys.modules.get(PM.LOCAL_MODULE_PREFIX + stem)


def new_manager():
    manager = PM.PluginManager()
    manager.discover()
    return manager


def node(node_id, alias="web-1", host="10.0.0.1"):
    """A plugin-visible node record (what a hook really receives)."""
    return PM.PluginNode(id=node_id, alias=alias, host=host, port=22, user="root")


class FakeResult:
    """The core's `PluginRunResult` shape, built by hand (the collectors need no socket)."""

    def __init__(self, node, exit_code=-1, output="", error=""):
        self.node = node
        self.exit_code = exit_code
        self.output = output
        self.error = error


class FakeCtx:
    """A context that RECORDS what a plugin asked for — the collectors' unit-test seam.

    Every `run_command` call is kept as `(command, [node ids])`, because the whole lesson of
    `watch_command` is HOW MANY calls a fleet costs: ONE per DISTINCT command, never one per
    node and never one per node per fact.
    """

    def __init__(self, answers=None, accept=True):
        self.answers = dict(answers or {})
        self.accept = accept
        self.statuses = []
        self.logs = []
        self.calls = []
        self.timeout = None

    def status(self, text, timeout_ms=5000):
        self.statuses.append(str(text))
        return True

    def log(self, message):
        self.logs.append(str(message))

    def run_command(self, nodes, command, on_result=None, on_finished=None, timeout=None):
        if not self.accept:
            return False
        self.calls.append((str(command), [item.id for item in list(nodes)]))
        self.timeout = timeout
        results = []
        for item in list(nodes):
            answer = self.answers.get(item.id)
            if answer is None:
                result = FakeResult(item, error="connection refused")
            elif isinstance(answer, str):
                result = FakeResult(item, error=answer)
            else:
                code, output = answer
                result = FakeResult(item, exit_code=code, output=output)
            results.append(result)
            if callable(on_result):
                on_result(item, result)
        if callable(on_finished):
            on_finished(results)
        return True


def write_plugin_file(name, text):
    """Write one of the plugin's own files directly (the hand-made / corrupt cases)."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    with open(os.path.join(PLUGIN_DIR, name), "w", encoding="utf-8") as handle:
        handle.write(text)


def remove_plugin_file(name):
    try:
        os.remove(os.path.join(PLUGIN_DIR, name))
    except OSError:
        pass


def certificate_in(days):
    """A peer certificate this many days away (an hour of slack keeps the flooring stable)."""
    moment = time.time() + days * 86400 + 3600
    return {"notAfter": time.strftime("%b %d %H:%M:%S %Y GMT", time.gmtime(moment))}


def certificate_ago(seconds):
    """A peer certificate whose `notAfter` was this many seconds ago (the past-side boundary)."""
    return {"notAfter": time.strftime("%b %d %H:%M:%S %Y GMT", time.gmtime(time.time() - seconds))}


NOT_AFTER = "Sep  1 12:00:00 2026 GMT"
NOT_AFTER_EPOCH = float(ssl.cert_time_to_seconds(NOT_AFTER))


def remove_config(module):
    remove_plugin_file(module.CONFIG_NAME)


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the two local examples as plugins: the REAL discovery path ==")
# ════════════════════════════════════════════════════════════════════════════

check("both files exist in examples/plugins/",
      all(os.path.isfile(src) for src, _stem, _hooks in EXAMPLE_FILES),
      [os.path.basename(src) for src, _s, _h in EXAMPLE_FILES if not os.path.isfile(src)])

_empty = new_manager()
check("they are NOT auto-discovered from the repository (an empty folder = no plugin)",
      _empty.records() == [] and all(_empty.get(stem) is None for _s, stem, _h in EXAMPLE_FILES),
      str([r.plugin_id for r in _empty.records()]))

install_examples()
_manager = new_manager()
_records = {stem: _manager.get(stem) for _s, stem, _h in EXAMPLE_FILES}
check("a copied example is discovered by the real manager (no packaging, no install)",
      all(rec is not None and rec.ok is True for rec in _records.values()),
      str([(r.plugin_id, r.state) for r in _manager.records()]))
check("the manifests are declared in the files and the hooks are the recorded ones",
      all(_records[stem].hooks == hooks and _records[stem].version == "1.0"
          and _records[stem].api_version == PM.API_VERSION
          and _records[stem].source == PM.SOURCE_FOLDER
          for _s, stem, hooks in EXAMPLE_FILES),
      {stem: (rec.hooks, rec.version) for stem, rec in _records.items()})
check("the imported modules are the files themselves (the discovery exec'd them)",
      all(local(stem) is not None and local(stem).MANIFEST["name"] == stem
          for _s, stem, _h in EXAMPLE_FILES))
for _path, _stem, _hooks in EXAMPLE_FILES:
    _name = os.path.basename(_path)
    check(f"{_name}: NO core import, no path trick, no SSH library (the SHARED predicate)",
          example_plugin_problems(_name, read(_path)) == [],
          example_plugin_problems(_name, read(_path)))
    check(f"{_name}: every hook it claims is a callable in the file",
          all(callable(getattr(local(_stem), h, None)) for h in _hooks))
_manager.shutdown(500)

cert_mod = local("certificates")
watch_mod = local("watch_command")

# ════════════════════════════════════════════════════════════════════════════
print("== §2 `certificates` — the example that never calls `ctx.run_command` ==")
# ════════════════════════════════════════════════════════════════════════════

_cert_source = read(CERTIFICATES_SRC)
check("the plugin never asks the core to run anything (no `ctx.run_command` CALL in the AST)",
      "run_command" not in called_names(_cert_source) and not hasattr(cert_mod, "run_on_nodes"),
      str(sorted(called_names(_cert_source))))
check("its fact comes from the STANDARD LIBRARY — `ssl` + `socket`, no dependency, no core import",
      "import ssl" in _cert_source and "import socket" in _cert_source
      and example_plugin_problems("certificates.py", _cert_source) == [])
check("it owns NO cache: the probe reads the fact live (unlike a collector/reporter plugin)",
      not hasattr(cert_mod, "CACHE_NAME") and not hasattr(cert_mod, "load_cache")
      and "save_config" not in _cert_source)
check("the connector is one INJECTABLE module attribute (the seam the gate replaces)",
      cert_mod.CONNECTOR is cert_mod.default_connector
      and callable(cert_mod.default_connector) and "CONNECTOR = default_connector" in _cert_source)
check("the plugin's own settings live beside the plugin folder, not in the application's config",
      cert_mod.config_path() == os.path.join(PLUGIN_DIR, cert_mod.CONFIG_NAME))
check("no settings file is a valid state: the shipped defaults stand",
      cert_mod.load_config() == {"default_port": 443, "horizon_days": 21, "nodes": {}},
      str(cert_mod.load_config()))
check("a port is read through ONE validator (a string is accepted, junk and 0 are not)",
      cert_mod.clean_port("8443") == 8443 and cert_mod.clean_port(0) is None
      and cert_mod.clean_port(70000) is None and cert_mod.clean_port("https") is None
      and cert_mod.clean_port(None) is None)
write_plugin_file(cert_mod.CONFIG_NAME, json.dumps(
    {"default_port": "8443", "horizon_days": 5, "nodes": {"srv-1": 9443, "10.0.0.9": 443,
                                                          "junk": "nope"}}))
_settings = cert_mod.load_config()
check("a stored settings file is validated on read (a junk port is dropped, a number is read)",
      _settings == {"default_port": 8443, "horizon_days": 5,
                    "nodes": {"srv-1": 9443, "10.0.0.9": 443}}, str(_settings))
check("the port of a node is its OWN entry by id, then by host, else the default",
      cert_mod.port_for(node("srv-1"), _settings) == 9443
      and cert_mod.port_for(node("zz", host="10.0.0.9"), _settings) == 443
      and cert_mod.port_for(node("zz", host="10.0.0.8"), _settings) == 8443)
check("an out-of-range horizon falls back to the shipped one (a typo cannot disable the check)",
      cert_mod.HORIZON_RANGE == (1, 3650) and cert_mod.DEFAULT_HORIZON_DAYS == 21)
for _bad_horizon in (0, 99999, "soon", None):
    write_plugin_file(cert_mod.CONFIG_NAME, json.dumps({"horizon_days": _bad_horizon}))
    check(f"a horizon of {_bad_horizon!r} is refused for the shipped one",
          cert_mod.load_config()["horizon_days"] == cert_mod.DEFAULT_HORIZON_DAYS,
          str(cert_mod.load_config()))
write_plugin_file(cert_mod.CONFIG_NAME, json.dumps({"horizon_days": "7"}))
check("a numeric STRING horizon is read (a hand-edited file)", cert_mod.load_config()["horizon_days"] == 7)
write_plugin_file(cert_mod.CONFIG_NAME, "{ not json at all")
check("a corrupt settings file costs the tuning, never the run",
      cert_mod.load_config()["default_port"] == 443 and cert_mod.load_config()["nodes"] == {})
write_plugin_file(cert_mod.CONFIG_NAME, json.dumps([1, 2, 3]))
check("a foreign document (a list root) is the shipped default as well",
      cert_mod.load_config() == {"default_port": 443, "horizon_days": 21, "nodes": {}})
remove_config(cert_mod)

# ════════════════════════════════════════════════════════════════════════════
print("== §3 `certificates` — the injected connector, the horizon, the detail ==")
# ════════════════════════════════════════════════════════════════════════════

check("the days left are read from the certificate's own `notAfter` (an explicit clock)",
      cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH - 200 * 86400) == 200
      and cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH + 3 * 86400) == -3
      and cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH) == 0)
check("a certificate without a usable date is `None`, never a guess",
      cert_mod.days_left({}) is None and cert_mod.days_left(None) is None
      and cert_mod.days_left({"notAfter": "not a date"}) is None
      and cert_mod.days_left("a string") is None)
check("the expiry VERDICT is its own pure fact, with the same no-data rule as the days",
      cert_mod.has_expired({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH - 1) is False
      and cert_mod.has_expired({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH) is True
      and cert_mod.has_expired({}) is None and cert_mod.has_expired(None) is None
      and cert_mod.has_expired({"notAfter": "not a date"}) is None
      and cert_mod.has_expired("a string") is None,
      str(cert_mod.has_expired({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH)))
check("the day count is truncated TOWARD ZERO: minutes past the date are still the SAME day",
      cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH + 300) == 0
      and cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH + 12 * 3600) == 0
      and cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH + 25 * 3600) == -1
      and cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH - 300) == 0,
      str([cert_mod.days_left({"notAfter": NOT_AFTER}, now=NOT_AFTER_EPOCH + _s)
           for _s in (300, 12 * 3600, 25 * 3600, -300)]))
check("the one day the two `0` cases meet reads its OWN sentence (expired today)",
      cert_mod.detail_text(0, 443, expired=True) == "certificate expired today (443/tcp)"
      and cert_mod.detail_text(0, 443, expired=False) == "certificate expires today (443/tcp)"
      and cert_mod.detail_text(0, 443) == "certificate expires today (443/tcp)",
      cert_mod.detail_text(0, 443, expired=True))
check("the detail is the ONE line of the card, in its three shapes",
      cert_mod.detail_text(12, 443) == "certificate expires in 12 day(s) (443/tcp)"
      and cert_mod.detail_text(0, 8443) == "certificate expires today (8443/tcp)"
      and cert_mod.detail_text(-3, 443) == "certificate expired 3 day(s) ago (443/tcp)",
      cert_mod.detail_text(12, 443))
check("the detail is bounded by MAX_DETAIL_CHARS (a tooltip line, not a paragraph)",
      len(cert_mod.detail_text(123456789, 443)) <= cert_mod.MAX_DETAIL_CHARS
      and cert_mod.MAX_DETAIL_CHARS > 0)

_seen = []
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: (_seen.append((host, port, timeout))
                                                      or certificate_in(200))
check("a comfortably valid certificate is `None` — the plugin never reassures a card",
      cert_mod.status_probe(node("srv-1", host="10.0.0.1")) is None)
check("the connector is asked with the node's host, the RESOLVED port and the probe budget",
      _seen == [("10.0.0.1", 443, cert_mod.PROBE_TIMEOUT_S)], str(_seen))
check("the budget is sized to the core's own probe budget (1500 ms abandons a probe)",
      cert_mod.PROBE_TIMEOUT_S <= PM.STATUS_PROBE_BUDGET_MS / 1000.0,
      f"{cert_mod.PROBE_TIMEOUT_S} vs {PM.STATUS_PROBE_BUDGET_MS} ms")

_seen.clear()
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: (_seen.append((host, port)) or
                                                      certificate_in(10))
check("inside the horizon the card warns with the days and the port",
      cert_mod.status_probe(node("srv-1", host="10.0.0.1"))
      == ("warn", "certificate expires in 10 day(s) (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1", host="10.0.0.1"))))
check("the kind is one of the contract's three (the core merges by severity)",
      cert_mod.status_probe(node("srv-1"))[0] in ("online", "warn", "offline"))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_in(0)
check("a certificate that expires TODAY is already a warning (the boundary counts)",
      cert_mod.status_probe(node("srv-1")) == ("warn", "certificate expires today (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_ago(3 * 86400 + 3600)
check("an ALREADY expired certificate still warns (the handshake succeeded, the date did not)",
      cert_mod.status_probe(node("srv-1"))
      == ("warn", "certificate expired 3 day(s) ago (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_ago(300)
check("five minutes past the date reads the SAME-DAY sentence, not a whole day ago",
      cert_mod.status_probe(node("srv-1")) == ("warn", "certificate expired today (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_ago(12 * 3600)
check("twelve hours past it is still the same day",
      cert_mod.status_probe(node("srv-1")) == ("warn", "certificate expired today (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_ago(25 * 3600)
check("twenty-five hours past it is exactly ONE whole day",
      cert_mod.status_probe(node("srv-1")) == ("warn", "certificate expired 1 day(s) ago (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_in(21)
check("exactly the horizon still warns (the rule is `<=`, the day the user asked about)",
      cert_mod.status_probe(node("srv-1"))
      == ("warn", "certificate expires in 21 day(s) (443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_in(22)
check("…and the day after the horizon is no opinion at all",
      cert_mod.status_probe(node("srv-1")) is None)

write_plugin_file(cert_mod.CONFIG_NAME, json.dumps({"horizon_days": 3, "nodes": {"srv-1": 9443}}))
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_in(5)
check("the horizon is the USER's setting, and the port of the node is the configured one",
      cert_mod.status_probe(node("srv-1")) is None)
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_in(2)
check("a shorter horizon turns the same certificate into a warning, on the configured port",
      cert_mod.status_probe(node("srv-1"))
      == ("warn", "certificate expires in 2 day(s) (9443/tcp)"),
      str(cert_mod.status_probe(node("srv-1"))))
remove_config(cert_mod)


def _refused(host, port, timeout=1.0):
    raise OSError("connection refused")


cert_mod.CONNECTOR = _refused
check('an unreachable port or a refused handshake is "no data", never a certificate verdict',
      cert_mod.status_probe(node("srv-1")) is None)
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: None
check("a connector that answers nothing is `None` as well (a foreign endpoint)",
      cert_mod.status_probe(node("srv-1")) is None)
check("a node without a host is `None` before any socket is opened",
      cert_mod.status_probe(PM.PluginNode(id="srv-x", host="")) is None
      and cert_mod.status_probe(PM.PluginNode(id="")) is None)
cert_mod.CONNECTOR = lambda host, port, timeout=1.0: certificate_in(1)
check("the reporter never raises, whatever the endpoint does (a probe runs per node per round)",
      cert_mod.status_probe(PM.PluginNode(id="srv-1", host="10.0.0.1"))[0] == "warn")

# ════════════════════════════════════════════════════════════════════════════
print("== §4 `certificates` — the REAL connector against a closed local endpoint ==")
# ════════════════════════════════════════════════════════════════════════════

_probe_socket = socket.socket()
_probe_socket.bind(("127.0.0.1", 0))
_closed_port = _probe_socket.getsockname()[1]
_probe_socket.close()
try:
    cert_mod.default_connector("127.0.0.1", _closed_port, 0.5)
    _raised = ""
except OSError as exc:                 # a refusal or a timeout — both are "no data"
    _raised = type(exc).__name__
check("the shipped connector really opens a socket (a closed port raises instead of answering)",
      bool(_raised), f"raised={_raised!r}")
cert_mod.CONNECTOR = cert_mod.default_connector
check("…and the probe turns that failure into `None` (a firewall is not an expiring certificate)",
      cert_mod.status_probe(PM.PluginNode(id="srv-1", host="127.0.0.1")) is None)

# ════════════════════════════════════════════════════════════════════════════
print("== §5 `watch_command` — the settings ARE the fact (validation, template, grouping) ==")
# ════════════════════════════════════════════════════════════════════════════

_watch_source = read(WATCH_SRC)
check("its settings live in its OWN file beside its cache (API v1 registers no settings section)",
      watch_mod.config_path() == os.path.join(PLUGIN_DIR, watch_mod.CONFIG_NAME)
      and watch_mod.cache_path() == os.path.join(PLUGIN_DIR, watch_mod.CACHE_NAME)
      and "save_config" not in _watch_source)
ENTRY = {"command": "uptime", "warn_pattern": "load average: [1-9]", "detail": "load is high"}
check("an entry needs BOTH a command and a usable regex (a typo cannot warn about nothing)",
      watch_mod._clean_entry(ENTRY) == ENTRY
      and watch_mod._clean_entry({"command": "", "warn_pattern": "x"}) is None
      and watch_mod._clean_entry({"command": "uptime"}) is None
      and watch_mod._clean_entry({"command": "uptime", "warn_pattern": "["}) is None
      and watch_mod._clean_entry("a string") is None and watch_mod._clean_entry(None) is None)
check("a regex and a command are bounded (a settings file cannot grow a run forever)",
      watch_mod.compiled("a" * (watch_mod.MAX_PATTERN_CHARS + 1)) is None
      and watch_mod.compiled("ok") is not None and watch_mod.compiled("") is None
      and watch_mod._clean_entry({"command": "x" * (watch_mod.MAX_COMMAND_CHARS + 1),
                                  "warn_pattern": "ok"}) is None)
check("a missing settings file is an empty map, never a crash",
      watch_mod.load_config() == {"default": None, "nodes": {}}, str(watch_mod.load_config()))
write_plugin_file(watch_mod.CONFIG_NAME, json.dumps(
    {"default": {"command": "date", "warn_pattern": "never", "detail": ""},
     "nodes": {"n1": ENTRY, "10.0.0.2": dict(ENTRY, command="free -m"), "junk": {"command": ""}}}))
_watch_settings = watch_mod.load_config()
check("every entry is validated on read and a broken one is DROPPED, not guessed at",
      sorted(_watch_settings["nodes"]) == ["10.0.0.2", "n1"]
      and _watch_settings["default"]["command"] == "date", str(_watch_settings))
check("a node is matched by its ID, then its host, else the `default` entry (or nothing)",
      watch_mod.entry_for(node("n1"), _watch_settings)["command"] == "uptime"
      and watch_mod.entry_for(node("zz", host="10.0.0.2"), _watch_settings)["command"] == "free -m"
      and watch_mod.entry_for(node("zz", host="10.0.0.3"), _watch_settings)["command"] == "date"
      and watch_mod.entry_for(node("zz", host="10.0.0.3"),
                              {"default": None, "nodes": {}}) is None)
_nodes = [node("n1"), node("n2", "db", "10.0.0.2"), node("n3", "x", "10.0.0.3")]
_groups, _skipped = watch_mod.group_by_command(_nodes, _watch_settings)
check("the run PLAN groups the nodes by DISTINCT command (one call per command, not per node)",
      [(cmd, [item.id for item, _e in pairs]) for cmd, pairs in _groups]
      == [("uptime", ["n1"]), ("free -m", ["n2"]), ("date", ["n3"])], str(_groups))
check("a node with no entry is REPORTED, never run against the wrong command",
      _skipped == [] and watch_mod.group_by_command(_nodes, {"default": None, "nodes": {}})
      == ([], ["n1", "n2", "n3"]))
check("the grouping really collapses a fleet (three nodes, ONE command, ONE call)",
      len(watch_mod.group_by_command([node("a"), node("b"), node("c")],
                                     {"default": ENTRY, "nodes": {}})[0]) == 1)
check("the matched detail is the user's string, else the first matching line of the answer",
      watch_mod.evaluate(ENTRY, "load average: 4.20, 3.10") == "load is high"
      and watch_mod.evaluate({"command": "x", "warn_pattern": "boom", "detail": ""},
                             "a\nboom here\nb") == "boom here"
      and watch_mod.evaluate(ENTRY, "load average: 0.10") is None
      and watch_mod.evaluate(None, "anything") is None)
check("the regex searches a BOUNDED answer (a 1 MB capture cannot be a probe's problem)",
      watch_mod.MAX_OUTPUT_CHARS < 1000000 and watch_mod.MAX_OUTPUT_CHARS > 1000
      and watch_mod.evaluate({"command": "x", "warn_pattern": "needle", "detail": ""},
                             "x" * watch_mod.MAX_OUTPUT_CHARS + "needle") is None)
check("a detail is bounded like a tooltip line",
      len(watch_mod.evaluate({"command": "x", "warn_pattern": "boom", "detail": "d" * 500},
                             "boom")) <= watch_mod.MAX_DETAIL_CHARS)
remove_plugin_file(watch_mod.CONFIG_NAME)

_ctx_template = FakeCtx()
check("the Ctrl+K door seeds the settings file and reports where it landed",
      watch_mod.register_commands(_ctx_template)[0][0].startswith("Watch: write the config")
      and watch_mod.write_template(_ctx_template) is True
      and os.path.isfile(watch_mod.config_path())
      and "template written" in _ctx_template.statuses[-1],
      str(_ctx_template.statuses))
check("the template is INERT — an empty command is refused, so a seed runs nothing",
      watch_mod.load_config() == {"default": None, "nodes": {}}, str(watch_mod.load_config()))
check("an EXISTING settings file is the user's own and is never overwritten",
      watch_mod.write_template(_ctx_template) is False
      and "already exists" in _ctx_template.statuses[-1], str(_ctx_template.statuses))
remove_plugin_file(watch_mod.CONFIG_NAME)

# ════════════════════════════════════════════════════════════════════════════
print("== §6 `watch_command`'s collector: the VERBATIM command, one call per command ==")
# ════════════════════════════════════════════════════════════════════════════

HOSTILE = {"command": "uptime && id; echo $HOME", "warn_pattern": "load", "detail": "high"}
write_plugin_file(watch_mod.CONFIG_NAME, json.dumps({"nodes": {"n1": HOSTILE, "n2": ENTRY}}))
_ctx = FakeCtx({"n1": (0, "load average: 9.00\n"), "n2": (0, "load average: 0.10\n")})
watch_mod.run_on_nodes([node("n1"), node("n2", "db", "10.0.0.2")], _ctx)
check("the user's command runs VERBATIM — the plugin interpolates NOTHING into it",
      [command for command, _ids in _ctx.calls] == ["uptime && id; echo $HOME", "uptime"]
      and "load is high" not in _ctx.calls[0][0] and "10.0.0.1" not in _ctx.calls[0][0],
      str(_ctx.calls))
check("one call per DISTINCT command, each with exactly the nodes of that entry",
      [(cmd, ids) for cmd, ids in _ctx.calls] == [("uptime && id; echo $HOME", ["n1"]),
                                                  ("uptime", ["n2"])], str(_ctx.calls))
check("one result per node was parsed into the plugin's own cache",
      sorted(watch_mod.load_cache()) == ["n1", "n2"], str(sorted(watch_mod.load_cache())))
check("a match stores the detail, a non-match stores the fact that it did NOT match",
      watch_mod.load_cache()["n1"]["matched"] is True
      and watch_mod.load_cache()["n1"]["detail"] == "high"
      and watch_mod.load_cache()["n2"]["matched"] is False
      and watch_mod.load_cache()["n2"]["detail"] == "", str(watch_mod.load_cache()))
check("the summary lands ONCE, after the LAST group answered (the shared counter)",
      _ctx.statuses == ["watch: 2 node(s), 1 matching"], str(_ctx.statuses))
check("every node is logged with its own verdict (the per-node detail)",
      any("web-1" in line and "high" in line for line in _ctx.logs)
      and any("db" in line and "no match" in line for line in _ctx.logs), str(_ctx.logs))

_ctx2 = FakeCtx({"n1": (0, "load average: 9.00\n"), "n2": "authentication failed"})
watch_mod.run_on_nodes([node("n1"), node("n2", "db", "10.0.0.2")], _ctx2)
check("ONE node's failure is a result for THAT node — the neighbours still land in the cache",
      "n1" in watch_mod.load_cache() and "n2" in watch_mod.load_cache())
check("the failure is logged per node and summarised once at the end",
      any("db" in line and "authentication failed" in line for line in _ctx2.logs)
      and any("without an answer" in line and "n2" in line for line in _ctx2.logs),
      str(_ctx2.logs))
check("the summary counts what answered (2 nodes asked, 1 answered)",
      _ctx2.statuses == ["watch: 1 node(s), 1 matching"], str(_ctx2.statuses))

_ctx3 = FakeCtx({"n3": (0, "anything\n")})
watch_mod.run_on_nodes([node("n3", "x", "10.0.0.9")], _ctx3)
check("a run whose nodes have no entry asks the core for NOTHING and says why",
      _ctx3.calls == [] and _ctx3.statuses == ["watch: nothing configured"]
      and any("no node of this run has an entry" in line for line in _ctx3.logs),
      f"{_ctx3.calls} {_ctx3.statuses} {_ctx3.logs}")
remove_plugin_file(watch_mod.CONFIG_NAME)
_ctx4 = FakeCtx()
watch_mod.run_on_nodes([], _ctx4)
check("an empty selection does nothing and says so",
      _ctx4.statuses == ["watch: nothing selected"] and _ctx4.calls == [], str(_ctx4.statuses))
write_plugin_file(watch_mod.CONFIG_NAME, json.dumps({"nodes": {"n1": ENTRY, "n2": ENTRY}}))
_ctx5 = FakeCtx({}, accept=False)
watch_mod.run_on_nodes([node("n1"), node("n2", "db", "10.0.0.2")], _ctx5)
check("a REFUSED `run_command` is a log line and an honest summary, not a crash",
      any("refused" in line for line in _ctx5.logs)
      and _ctx5.statuses == ["watch: 0 node(s), 0 matching"], f"{_ctx5.logs} {_ctx5.statuses}")
remove_plugin_file(watch_mod.CONFIG_NAME)

# ════════════════════════════════════════════════════════════════════════════
print("== §7 `watch_command`'s reporter: the cached verdict, the staleness ==")
# ════════════════════════════════════════════════════════════════════════════

remove_plugin_file(watch_mod.CACHE_NAME)
watch_mod.save_cache({"hit": {"alias": "hit", "command": "uptime", "matched": True,
                              "detail": "load is high", "ts": time.time()},
                      "miss": {"alias": "miss", "command": "uptime", "matched": False,
                               "detail": "", "ts": time.time()},
                      "silent": {"alias": "silent", "command": "uptime", "matched": True,
                                 "detail": "", "ts": time.time()},
                      "old": {"alias": "old", "command": "uptime", "matched": True,
                              "detail": "stale", "ts": time.time() - watch_mod.STALE_SECONDS - 60}})
check("a matched watch warns with the user's OWN detail",
      watch_mod.status_probe(node("hit")) == ("warn", "load is high"),
      str(watch_mod.status_probe(node("hit"))))
check("a watch that did NOT match adds NO opinion at all (never an `online` of its own)",
      watch_mod.status_probe(node("miss")) is None)
check("a match without a detail still carries ONE sentence (the card never shows an empty warning)",
      watch_mod.status_probe(node("silent")) == ("warn", watch_mod.DETAIL_FALLBACK),
      str(watch_mod.status_probe(node("silent"))))
check("a STALE record is not an opinion any more", watch_mod.status_probe(node("old")) is None)
check("an unknown node is no opinion (a node that left the map)",
      watch_mod.status_probe(node("never-seen")) is None
      and watch_mod.status_probe(PM.PluginNode(id="")) is None)
check("the kind is one of the contract's three (the core merges by severity)",
      watch_mod.status_probe(node("hit"))[0] in ("online", "warn", "offline"))
check("`fresh_record` honours an explicit clock (the staleness rule is testable)",
      watch_mod.fresh_record("hit", now=time.time() + watch_mod.STALE_SECONDS + 10) is None
      and watch_mod.fresh_record("hit") is not None)
check("the reporter reads the cache and touches NOTHING else (a probe runs per node per round)",
      "run_command" not in body(_watch_source, "status_probe")
      and "load_config" not in body(_watch_source, "status_probe"))
write_plugin_file(watch_mod.CACHE_NAME, "{ this is not json at all")
check("a corrupt cache is `{}` — a probe round never breaks on it",
      watch_mod.load_cache() == {} and watch_mod.status_probe(node("hit")) is None)
write_plugin_file(watch_mod.CACHE_NAME, json.dumps([1, 2, 3]))
check("a foreign document (a list root) is `{}` as well", watch_mod.load_cache() == {})
_original_path = watch_mod.cache_path
watch_mod.cache_path = lambda: os.path.join(WORK, "watch_blocker", "watch.json")
with open(os.path.join(WORK, "watch_blocker"), "w", encoding="utf-8") as handle:
    handle.write("a FILE where a directory is needed")
check("a blocked cache write is a `False`, never an exception",
      watch_mod.save_cache({"hit": {"matched": True, "detail": "x", "ts": time.time()}}) is False)
watch_mod.cache_path = _original_path
remove_plugin_file(watch_mod.CACHE_NAME)

# ════════════════════════════════════════════════════════════════════════════
print("== §8 the release state: the folder adds NO i18n key ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
check("the two local examples contribute no translation key (a plugin's text is the AUTHOR's)",
      not any(value in ("load is high", "reboot required", "certificate expires in 10 day(s)")
              for data in _langs.values() for value in data.values()))
check("the parity pin is the shipped one (the folder contributes nothing — the releases move it)",
      all(len(translation_keys(data)) == EXPECTED_I18N_KEYS for data in _langs.values()),
      str({code: len(translation_keys(data)) for code, data in _langs.items()}))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("their own prefixes stay outside the parity policy",
      all(fragment not in json.dumps(_langs["en"]) for fragment in
          ("watch: ", "certificate ", "load is high", "warn_pattern")))
check("the release is this file's version or a LATER one (the file describes v1.9.4)",
      releases_at_least(EXPECTED_APP_VERSION, "1.9.4"), EXPECTED_APP_VERSION)
check_release_state(ROOT)
check("examples/README.md documents all EIGHT example files (the folder's ONE table)",
      all(stem in read(os.path.join(EXAMPLES_DIR, "README.md"))
          for stem in ("hello", "disk_monitor", "systemd_failed", "maintenance", "certificates",
                       "open_ports", "app_versions", "watch_command")),
      [stem for stem in ("hello", "disk_monitor", "systemd_failed", "maintenance", "certificates",
                         "open_ports", "app_versions", "watch_command")
       if stem not in read(os.path.join(EXAMPLES_DIR, "README.md"))])
check("the folder's README states the isolation rule the shared predicate audits",
      "never imports the core" in read(os.path.join(EXAMPLES_DIR, "README.md")))
check("the suite map lists this topical file (tests/INDEX.md regenerated)",
      "test_plugin_examples_local.py" in read(os.path.join(ROOT, "tests", "INDEX.md")))

clean_plugins()
clear_cfg()
finish()
