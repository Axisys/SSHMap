# -*- coding: utf-8 -*-
"""v1.9.2 — the two PROVEN examples (`examples/plugins/open_ports.py`, `app_versions.py`).

Both load through the REAL discovery path of `PluginManager` (copied into the isolated
`~/.sshmap/plugins/`, then `discover()`) and are driven without a socket.
§1 the two files as plugins (the manifests, the hooks, the SHARED isolation predicate); §2
`open_ports`'s `ss -tulpn` parser over fixtures (the header, a dual-stack pair, the loopback-vs-public
binding, the `State` column, a service name, junk, the cap); §3 its atomic bounded cache; §4 its
reporter (a reachable watch port → `warn`, loopback → `online`, staleness, no SSH in a probe); §5 its
collector on a fake context; §6 `app_versions`'s generated probe and its allowlist over a HOSTILE
catalog; §7 its pure reader (the version line, the comparison, the report); §8 the probe budget
DERIVED from the live catalog; §9 the baseline file and the cache; §10 the release state."""
import json
import os
import shutil
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
PORTS_SRC = os.path.join(PLUGINS_SRC, "open_ports.py")
VERSIONS_SRC = os.path.join(PLUGINS_SRC, "app_versions.py")
PLUGIN_DIR = PM.user_plugin_dir()

EXAMPLE_FILES = ((PORTS_SRC, "open_ports", (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES)),
                 (VERSIONS_SRC, "app_versions", (PM.HOOK_REGISTER_COMMANDS, PM.HOOK_RUN_ON_NODES)))


# ── helpers ──────────────────────────────────────────────────────────────────

def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def clean_plugins():
    """Empty the user plugin folder (the copied examples, their caches, the import cache)."""
    if os.path.isdir(PLUGIN_DIR):
        for name in os.listdir(PLUGIN_DIR):
            try:
                os.remove(os.path.join(PLUGIN_DIR, name))
            except OSError:
                pass
    for key in [k for k in sys.modules if k.startswith(PM.LOCAL_MODULE_PREFIX)]:
        sys.modules.pop(key, None)


def install_examples():
    """Copy the two proven examples into the sandbox plugin folder — what a user does by hand."""
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

    `run_command` is a core service on a managed worker in the application; here the answers are
    canned, so the whole collector (parsing, the cache write, the reports) is driven without a
    socket — the same spirit as the runner's injectable transport. `timeout` is recorded too: it is
    the budget the core is asked for, and one release fixed a DECLARED one.
    """

    def __init__(self, answers=None, accept=True):
        self.answers = dict(answers or {})
        self.accept = accept
        self.statuses = []
        self.logs = []
        self.command = None
        self.nodes = None
        self.timeout = None

    def status(self, text, timeout_ms=5000):
        self.statuses.append(str(text))
        return True

    def log(self, message):
        self.logs.append(str(message))

    def run_command(self, nodes, command, on_result=None, on_finished=None, timeout=None):
        if not self.accept:
            return False
        self.command = str(command)
        self.timeout = timeout
        self.nodes = list(nodes)
        results = []
        for item in self.nodes:
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
    """Write one of the plugin's own data files directly (the hand-made / corrupt cases)."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    with open(os.path.join(PLUGIN_DIR, name), "w", encoding="utf-8") as handle:
        handle.write(text)


def remove_plugin_file(name):
    try:
        os.remove(os.path.join(PLUGIN_DIR, name))
    except OSError:
        pass


SS_TABLE = (
    "Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
    'tcp   LISTEN 0      128    0.0.0.0:22         0.0.0.0:*         users:(("sshd",pid=987,fd=3))\n'
    'tcp   LISTEN 0      128    [::]:22            [::]:*            users:(("sshd",pid=987,fd=4))\n'
    'tcp   LISTEN 0      80     127.0.0.1:3306     0.0.0.0:*         users:(("mysqld",pid=1234,fd=21))\n'
    "udp   UNCONN 0      0      0.0.0.0:68         0.0.0.0:*\n")

clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the two proven examples as plugins: the REAL discovery path ==")
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

ports_mod = local("open_ports")
versions_mod = local("app_versions")

# ════════════════════════════════════════════════════════════════════════════
print("== §2 `open_ports` — the `ss -tulpn` parser (fixtures, no socket) ==")
# ════════════════════════════════════════════════════════════════════════════

_parsed = ports_mod.parse_ss(SS_TABLE)
check("the parser is a pure function of the answer (no IO, no SSH library)",
      ports_mod.parse_ss("") == [] and ports_mod.parse_ss(None) == [])
check("a dual-stack listener collapses to ONE row (the most EXPOSED binding wins)",
      [(row["port"], row["proto"]) for row in _parsed] == [(22, "tcp"), (68, "udp"), (3306, "tcp")],
      str([(row["port"], row["proto"]) for row in _parsed]))
check("the kept binding of `0.0.0.0:22` + `[::]:22` is the global one, with its process name",
      _parsed[0]["address"] == "0.0.0.0" and _parsed[0]["scope"] == "global"
      and _parsed[0]["process"] == "sshd", str(_parsed[0]))
check("the program name is read out of the `users:((…,pid=…,fd=…))` column",
      _parsed[2]["process"] == "mysqld" and _parsed[2]["scope"] == "local", str(_parsed[2]))
check("`127.0.0.1:3306` beside `0.0.0.0:3306` keeps the PUBLIC binding (the loopback one is dropped)",
      [(row["port"], row["address"]) for row in ports_mod.parse_ss(
          "tcp LISTEN 0 128 127.0.0.1:5432 0.0.0.0:*\n"
          "tcp LISTEN 0 128 0.0.0.0:5432   0.0.0.0:*\n")] == [(5432, "0.0.0.0")])
check("an IPv6 endpoint is read through its brackets (`[::1]:6379` → host `::1`)",
      ports_mod.split_endpoint("[::1]:6379") == ("::1", "6379")
      and ports_mod.host_scope("::1") == "local"
      and ports_mod.host_scope("::") == "global")
check("`split_endpoint` keeps a bare IPv6 host whole and an endpoint without a port intact",
      ports_mod.split_endpoint("::") == ("::", "")
      and ports_mod.split_endpoint("no-port") == ("no-port", "")
      and ports_mod.split_endpoint("*:https") == ("*", "https"))
check("a SERVICE name is read as its port (`*:https` → 443), the `-n` guard",
      ports_mod.parse_port("https") == 443 and ports_mod.parse_port("ssh") == 22
      and ports_mod.parse_port("mongod") == 27017)
check("a port outside 0..65535 / a non-port token yields None, never a guess",
      ports_mod.parse_port("99999") is None and ports_mod.parse_port("") is None
      and ports_mod.parse_port(None) is None and ports_mod.parse_port("nope") is None)
check("`-l`'s round is read through the State column (`tcp LISTEN …` → the local endpoint)",
      [(row["port"], row["proto"]) for row in ports_mod.parse_ss(
          "tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n")] == [(22, "tcp")])
check("a build that leaves the State field BLANK shifts no column (the layout is re-read)",
      [(row["port"], row["proto"]) for row in ports_mod.parse_ss(
          "tcp 0 128 0.0.0.0:22 0.0.0.0:*\n")] == [(22, "tcp")])
check("the `Netid …` header, a message `ss` wrote and a truncated line are skipped",
      ports_mod.parse_ss("Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
                         "ss: command not found\n"
                         "tcp LISTEN 0\n") == [])
check("a service-name row keeps its scope (the tooltip never lies about exposure)",
      ports_mod.parse_ss("tcp LISTEN 0 128 *:https *:*\n")[0]["scope"] == "global"
      and ports_mod.parse_ss("tcp LISTEN 0 128 127.0.0.1:6379 0.0.0.0:*\n")[0]["scope"] == "local")
_capped = ports_mod.parse_ss("\n".join(
    f"tcp LISTEN 0 128 0.0.0.0:{port} 0.0.0.0:*" for port in range(1, ports_mod.MAX_PORTS_PER_NODE + 6)))
check(f"the list is capped at MAX_PORTS_PER_NODE ({ports_mod.MAX_PORTS_PER_NODE})",
      len(_capped) == ports_mod.MAX_PORTS_PER_NODE, str(len(_capped)))
check("the cap drops the HIGHEST ports (the low ones are what a reader scans for)",
      _capped[0]["port"] == 1 and _capped[-1]["port"] == ports_mod.MAX_PORTS_PER_NODE,
      f"{_capped[0]['port']} … {_capped[-1]['port']}")
check("`normalise_ports` refuses junk without raising",
      ports_mod.normalise_ports([None, "x", {"port": "nope"}, {"port": 70000}]) == [])

# ════════════════════════════════════════════════════════════════════════════
print("== §3 `open_ports`'s own cache (atomic, merged, bounded, disposable) ==")
# ════════════════════════════════════════════════════════════════════════════

remove_plugin_file(ports_mod.CACHE_NAME)
check("the cache lives next to the plugin folder, not in the application's config",
      ports_mod.cache_path() == os.path.join(PLUGIN_DIR, ports_mod.CACHE_NAME)
      and "save_config" not in read(PORTS_SRC),
      ports_mod.cache_path())
check("an absent cache is an empty mapping (never an exception)", ports_mod.load_cache() == {})
check("`save_cache` writes the document and `load_cache` reads it back",
      ports_mod.save_cache({"n1": {"alias": "web-1", "ts": time.time(),
                                   "ports": [{"proto": "tcp", "port": 22, "address": "0.0.0.0",
                                              "scope": "global", "process": "sshd"}]}}) is True
      and ports_mod.load_cache()["n1"]["ports"][0]["port"] == 22
      and ports_mod.load_cache()["n1"]["alias"] == "web-1")
check("a node ABSENT from this round keeps its previous answer (a merge, not a replace)",
      ports_mod.save_cache({"n2": {"alias": "db-1", "ts": time.time(), "ports": []}}) is True
      and sorted(ports_mod.load_cache()) == ["n1", "n2"], str(sorted(ports_mod.load_cache())))
check("the write is ATOMIC — no temp file is left behind in the folder",
      [n for n in os.listdir(PLUGIN_DIR) if n.startswith(".open_ports-")] == [],
      str(os.listdir(PLUGIN_DIR)))
check("a junk port entry is dropped from a stored record, not stored",
      ports_mod.save_cache({"n3": {"alias": "x", "ts": time.time(),
                                   "ports": [{"port": "nope"}, {"port": 443, "proto": "tcp"}]}}) is True
      and [row["port"] for row in ports_mod.load_cache()["n3"]["ports"]] == [443])
_records_all = {}
_now = time.time()
for index in range(ports_mod.MAX_RECORDS + 5):
    _records_all[f"node-{index:02d}"] = {"alias": f"h{index}", "ts": _now + index, "ports": []}
ports_mod.save_cache(_records_all)
check(f"the cache is bounded at MAX_RECORDS ({ports_mod.MAX_RECORDS}) records",
      len(ports_mod.load_cache()) == ports_mod.MAX_RECORDS, str(len(ports_mod.load_cache())))
check("the pruning keeps the NEWEST records (the oldest are the ones that go)",
      f"node-{ports_mod.MAX_RECORDS + 4:02d}" in ports_mod.load_cache()
      and "node-00" not in ports_mod.load_cache())
write_plugin_file(ports_mod.CACHE_NAME, "{ this is not json at all")
check("a corrupt cache is `{}` — a probe round never breaks on it",
      ports_mod.load_cache() == {} and ports_mod.status_probe(node("n1")) is None)
write_plugin_file(ports_mod.CACHE_NAME, json.dumps([1, 2, 3]))
check("a foreign document (a list root) is `{}` as well", ports_mod.load_cache() == {})
_original_path = ports_mod.cache_path
ports_mod.cache_path = lambda: os.path.join(WORK, "ports_blocker", "ports.json")
with open(os.path.join(WORK, "ports_blocker"), "w", encoding="utf-8") as handle:
    handle.write("a FILE where a directory is needed")
check("a write that cannot happen returns False and never raises",
      ports_mod.save_cache({"n1": {"port": 1, "ts": time.time(), "ports": []}}) is False)
ports_mod.cache_path = _original_path

# ════════════════════════════════════════════════════════════════════════════
print("== §4 `open_ports`'s reporter: the detail, the watchlist, staleness ==")
# ════════════════════════════════════════════════════════════════════════════


def ports_record(port, scope="global", proto="tcp", process=""):
    return {"proto": proto, "port": port, "address": "0.0.0.0" if scope != "local" else "127.0.0.1",
            "scope": scope, "process": process}


ports_mod.save_cache({
    "clean": {"alias": "clean", "ts": time.time(),
              "ports": [ports_record(22, process="sshd"), ports_record(80),
                        ports_record(443), ports_record(3306, scope="local", process="mysqld"),
                        ports_record(5432, scope="local")]},
    "risky": {"alias": "risky", "ts": time.time(),
              "ports": [ports_record(22, process="sshd"), ports_record(3306, process="mysqld"),
                        ports_record(6379, process="redis-server"), ports_record(5432, scope="local")]},
    "quiet": {"alias": "quiet", "ts": time.time(), "ports": [ports_record(5432, scope="local")]},
    "empty": {"alias": "empty", "ts": time.time(), "ports": []},
    "old": {"alias": "old", "ts": time.time() - ports_mod.STALE_SECONDS - 60,
            "ports": [ports_record(3306, process="mysqld")]}})
check("a node with only SAFE or loopback sockets reports `online` plus the reachable list",
      ports_mod.status_probe(node("clean")) == ("online", "3 open: 22/tcp, 80/tcp, 443/tcp "
                                                          "(+2 on loopback)"),
      str(ports_mod.status_probe(node("clean"))))
check("a reachable WATCHLISTED port turns the card `warn` and names the process",
      ports_mod.status_probe(node("risky")) == ("warn", "exposed 3306/tcp (mysqld), "
                                                         "6379/tcp (redis-server) - 3 open"),
      str(ports_mod.status_probe(node("risky"))))
check("a loopback-only database is NEVER a hit (`127.0.0.1:3306` is how it should be bound)",
      ports_mod.watch_hits([ports_record(3306, scope="local")]) == ()
      and ports_mod.status_probe(node("quiet")) == ("online", "nothing reachable (+1 on loopback)"),
      str(ports_mod.status_probe(node("quiet"))))
check("a node with no listening socket says so instead of inventing a detail",
      ports_mod.status_probe(node("empty")) == ("online", "no listening socket"),
      str(ports_mod.status_probe(node("empty"))))
check("a STALE record is no opinion any more", ports_mod.status_probe(node("old")) is None)
check("an unknown node is no opinion (a node that left the map)",
      ports_mod.status_probe(node("never-seen")) is None
      and ports_mod.status_probe(PM.PluginNode(id="")) is None)
check("the kind is one of the contract's three (the core merges by severity)",
      ports_mod.status_probe(node("risky"))[0] in ("online", "warn", "offline"))
check("`fresh_record` honours an explicit clock (the staleness rule is testable)",
      ports_mod.fresh_record("risky", now=time.time() + ports_mod.STALE_SECONDS + 10) is None
      and ports_mod.fresh_record("risky") is not None)
check("the reporter reads the cache and touches NOTHING else (a probe runs per node per round)",
      "run_command" not in read(PORTS_SRC).split("def status_probe")[1].split("\ndef ")[0])
check("the two text readers are bounded and readable (the tooltip line)",
      ports_mod.format_ports([ports_record(port) for port in range(10)]) ==
      "0/tcp, 1/tcp, 2/tcp, 3/tcp, 4/tcp, 5/tcp, 6/tcp, 7/tcp (+2 more)"
      and ports_mod.warn_text({"ports": [ports_record(port) for port in range(6)]},
                              [ports_record(1), ports_record(2), ports_record(3),
                               ports_record(4), ports_record(5)]) ==
      "exposed 1/tcp, 2/tcp, 3/tcp, 4/tcp (+1 more) - 6 open")
check("the Plugins window's DATA line names the whole cached list (an export is a file, not a card)",
      ports_mod.log_text({"ports": [ports_record(port) for port in range(12)]}) ==
      "12 socket(s): " + ", ".join(f"{port}/tcp" for port in range(12))
      and ports_mod.format_ports([ports_record(port) for port in range(12)]) ==
      "0/tcp, 1/tcp, 2/tcp, 3/tcp, 4/tcp, 5/tcp, 6/tcp, 7/tcp (+4 more)",
      ports_mod.log_text({"ports": [ports_record(port) for port in range(12)]}))
check("…and each row carries its SCOPE, the fact the tooltip only counts",
      ports_mod.log_text({"ports": [ports_record(22), ports_record(68, proto="udp"),
                                    ports_record(3306, scope="local")]})
      == "3 socket(s): 22/tcp, 68/udp, 3306/tcp (loopback)",
      ports_mod.log_text({"ports": [ports_record(22), ports_record(68, proto="udp"),
                                    ports_record(3306, scope="local")]}))
check("a reachable WATCHLISTED row is marked `exposed` with the process `ss -p` reported",
      ports_mod.log_text({"ports": [ports_record(22, process="sshd"),
                                    ports_record(6379, process="redis-server"),
                                    ports_record(5432, scope="local", process="postgres")]})
      == "3 socket(s): 22/tcp, 6379/tcp redis-server (exposed), 5432/tcp (loopback)")
check("an empty record and the per-node cap are honest (the cap is the CACHE's, not the tooltip's)",
      ports_mod.log_text({"ports": []}) == "no listening socket"
      and ports_mod.log_text({"ports": []}, limit=4) == "no listening socket"
      and ports_mod.log_text({"ports": [ports_record(port)
                                        for port in range(ports_mod.MAX_PORTS_PER_NODE + 3)]})
      .endswith("(+3 more)")
      and ports_mod.log_text({"ports": [ports_record(port) for port in range(6)]},
                             limit=4) == "6 socket(s): 0/tcp, 1/tcp, 2/tcp, 3/tcp (+2 more)")

# ════════════════════════════════════════════════════════════════════════════
print("== §5 `open_ports`'s collector: `run_on_nodes` on a fake context ==")
# ════════════════════════════════════════════════════════════════════════════

remove_plugin_file(ports_mod.CACHE_NAME)
_nodes = [node("n1", "web-1"), node("n2", "db-1", "10.0.0.2")]
RISKY_TABLE = ('tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1,fd=3))\n'
               'tcp LISTEN 0 128 0.0.0.0:3306 0.0.0.0:* users:(("mysqld",pid=2,fd=21))\n')
_ctx = FakeCtx({"n1": (0, SS_TABLE), "n2": (0, RISKY_TABLE)})
ports_mod.run_on_nodes(_nodes, _ctx)
check("the collector runs exactly the documented command",
      _ctx.command == "ss -tulpn" and ports_mod.COMMAND == "ss -tulpn", str(_ctx.command))
check("one result per node was parsed into the cache",
      sorted(ports_mod.load_cache()) == ["n1", "n2"], str(sorted(ports_mod.load_cache())))
check("the normalised sockets are what is stored (the exposed binding, the process name)",
      [(row["port"], row["scope"]) for row in ports_mod.load_cache()["n1"]["ports"]]
      == [(22, "global"), (68, "global"), (3306, "local")]
      and ports_mod.load_cache()["n2"]["ports"][1]["process"] == "mysqld")
check("the status line counts what answered and how many are exposed",
      _ctx.statuses == ["ports: 2 node(s), 1 with a watchlisted port exposed"],
      str(_ctx.statuses))
check("every node is logged with its socket count (the per-node detail)",
      any("web-1" in line and "3 listening socket(s)" in line for line in _ctx.logs)
      and any("db-1" in line and "1 watchlisted and reachable" in line for line in _ctx.logs),
      str(_ctx.logs))
check("…and the DATA line of every node rides the same log (the window renders and exports it)",
      any(line == "ports: web-1 (10.0.0.1) — 3 socket(s): 22/tcp, 68/udp, 3306/tcp (loopback)"
          for line in _ctx.logs)
      and any(line == "ports: db-1 (10.0.0.2) — 2 socket(s): 22/tcp, 3306/tcp mysqld (exposed)"
              for line in _ctx.logs),
      str(_ctx.logs))
_wide = "".join(f"tcp LISTEN 0 128 0.0.0.0:{port} 0.0.0.0:*\n" for port in range(1, 13))
_ctx_wide = FakeCtx({"n1": (0, _wide)})
ports_mod.run_on_nodes([node("n1", "web-1")], _ctx_wide)
check("a node with more sockets than a TOOLTIP holds still exports its whole list",
      any(line == "ports: web-1 (10.0.0.1) — 12 socket(s): "
                  + ", ".join(f"{port}/tcp" for port in range(1, 13))
          for line in _ctx_wide.logs)
      and ports_mod.status_probe(node("n1")) == ("online", "12 open: 1/tcp, 2/tcp, 3/tcp, 4/tcp, "
                                                           "5/tcp, 6/tcp, 7/tcp, 8/tcp (+4 more)"),
      str(_ctx_wide.logs[-1]))
check("after the round the reporter warns for the exposed node and details the other",
      ports_mod.status_probe(node("n2"))[0] == "warn"
      and ports_mod.status_probe(node("n1"))[0] == "online")

_ctx2 = FakeCtx({"n1": (0, SS_TABLE), "n2": "authentication failed"})
ports_mod.run_on_nodes(_nodes, _ctx2)
check("ONE node's failure is a result for THAT node — the neighbours still land in the cache",
      "n1" in ports_mod.load_cache() and "n2" in ports_mod.load_cache())
check("the failure is logged per node and summarised once at the end",
      any("db-1" in line and "authentication failed" in line for line in _ctx2.logs)
      and any("without an answer" in line and "n2" in line for line in _ctx2.logs),
      str(_ctx2.logs))
check("the status line counts what answered (2 nodes asked, 1 answered)",
      _ctx2.statuses == ["ports: 1 node(s), 0 with a watchlisted port exposed"], str(_ctx2.statuses))

_ctx3 = FakeCtx({"n1": (0, "ss: command not found\n")})
remove_plugin_file(ports_mod.CACHE_NAME)
ports_mod.run_on_nodes([node("n1", "web-1")], _ctx3)
check("an answer with NO socket row is a FAILURE, never a cached 'nothing is listening'",
      any("no socket" in line for line in _ctx3.logs)
      and "n1" not in ports_mod.load_cache()
      and _ctx3.statuses == ["ports: 0 node(s), 0 with a watchlisted port exposed"],
      str(_ctx3.logs))
_ctx4 = FakeCtx()
ports_mod.run_on_nodes([], _ctx4)
check("an empty selection does nothing and says so",
      _ctx4.statuses == ["ports: nothing selected"] and _ctx4.command is None,
      str(_ctx4.statuses))
_ctx5 = FakeCtx({}, accept=False)
ports_mod.run_on_nodes(_nodes, _ctx5)
check("a REFUSED `run_command` is a log line and an honest status, not a crash",
      _ctx5.statuses == ["ports: nothing to do"] and any("refused" in line for line in _ctx5.logs),
      str(_ctx5.logs))

# ════════════════════════════════════════════════════════════════════════════
print("== §6 `app_versions` — the generated probe and the shell allowlist ==")
# ════════════════════════════════════════════════════════════════════════════

remove_plugin_file(versions_mod.BASELINE_NAME)
remove_plugin_file(versions_mod.CACHE_NAME)
_script = versions_mod.build_probe_script()
check("the probe is ONE POSIX-sh script that COLLECTS evidence and ends with its own marker",
      _script.startswith("# sshmap app_versions") and _script.rstrip().endswith("exit 0")
      and versions_mod.PROBE_MARKER in _script)
check("coreutils' own `timeout` is preferred over a PATH lookup (an MSYS `timeout.exe`)",
      "if [ -x /usr/bin/timeout ]; then TMO=/usr/bin/timeout" in _script)
check("it reads ONLY argv[0] of an ABSOLUTE path (a shell mentioning the path is not the app)",
      'case "$exe" in /*) ;; *) continue ;; esac' in _script
      and 'case "${exe##*/}" in' in _script)
check("every catalog app is probed with its OWN flags, in order",
      "for f in -v; do probe nginx running" in _script
      and "for f in --version -v; do probe grafana installed" in _script)
check("`probe_completed` is the marker reader (a truncated answer is caught)",
      versions_mod.probe_completed("V|x|absent|||\n" + versions_mod.PROBE_MARKER + "\n") is True
      and versions_mod.probe_completed("V|x|absent|||\n") is False)

HOSTILE = {
    "evil; rm -rf /": {"names": ["nginx"], "flags": ["-v"], "paths": ["/usr/sbin/nginx"],
                       "cmds": ["nginx"]},
    "inject": {"names": ["a$(id)"], "flags": ["--version; rm -rf /"], "paths": ["/usr/bin/x`id`"],
               "cmds": ["x; rm -rf /"]},
    "mixed": {"names": ["nginx"], "flags": ["--version; rm -rf /", "-v"],
              "paths": ["/usr/sbin/nginx; id"], "cmds": ["nginx"]},
    "safe": {"names": ["loki"], "flags": ["--version"], "paths": ["/usr/local/bin/loki"],
             "cmds": ["loki"]},
}
_hostile_script = versions_mod.build_probe_script(HOSTILE)
check("an app ID the shell could act on is DROPPED entirely (the allowlist, not quoting)",
      "evil" not in _hostile_script and "rm -rf" not in _hostile_script)
check("an injected name / path / cmd leaves nothing to run (the entry is skipped)",
      "$(id)" not in _hostile_script and "`id`" not in _hostile_script
      and "x; rm -rf /" not in _hostile_script)
check("an injected FLAG is dropped and the app keeps its safe attempts (the safe app is probed)",
      "--version; rm -rf /" not in _hostile_script and "for f in -v; do probe mixed" in _hostile_script
      and "for f in --version; do probe safe installed" in _hostile_script)
check("`_clean_app` answers None for an entry with no usable token at all",
      versions_mod._clean_app("inject", HOSTILE["inject"]) is None
      and versions_mod._clean_app("evil; rm -rf /", HOSTILE["evil; rm -rf /"]) is None)
check("the three token predicates accept the shipped catalog and refuse the injected shapes",
      versions_mod.SAFE_ID_RE.match("loki-linux-amd64") is not None
      and versions_mod.SAFE_FLAG_RE.match("-version") is not None
      and versions_mod.SAFE_PATH_RE.match("/opt/wso2/alloy/alloy-linux-amd64") is not None
      and versions_mod.SAFE_FLAG_RE.match("--version; rm -rf /") is None
      and versions_mod.SAFE_PATH_RE.match("/usr/bin/x`id`") is None)
check("a user's flag list is capped at MAX_FLAGS (a baseline cannot grow the script forever)",
      len(versions_mod._clean_app("x", {"cmds": ["x"],
                                        "flags": ["-a", "-b", "-c", "-d"]})["flags"])
      == versions_mod.MAX_FLAGS)
check("the shipped catalog is the eight apps the MANIFEST describes",
      sorted(versions_mod.catalog()) == ["alloy", "grafana", "loki", "nginx", "prometheus",
                                         "promtail", "telegraf", "tempo"],
      str(sorted(versions_mod.catalog())))

# ════════════════════════════════════════════════════════════════════════════
print("== §7 `app_versions` — the pure reader over the evidence ==")
# ════════════════════════════════════════════════════════════════════════════

check("the FIRST dotted number of a version line is the version (every real wording)",
      versions_mod.parse_version("nginx version: nginx/1.30.2") == "1.30.2"
      and versions_mod.parse_version("grafana version 13.1.1") == "13.1.1"
      and versions_mod.parse_version("prometheus, version 3.12.0 (branch: HEAD, revision: 9f2)")
      == "3.12.0"
      and versions_mod.parse_version("alloy, version v1.15.1 (branch: HEAD)") == "1.15.1")
check("a usage line (an unknown flag) carries no version, so the next flag is tried",
      versions_mod.parse_version("Usage of /usr/local/bin/loki:") == ""
      and versions_mod.parse_version("") == "" and versions_mod.parse_version(None) == "")
check("the comparison is NUMERIC (a string compare would put 1.9 above 1.10)",
      versions_mod.version_key("1.9") < versions_mod.version_key("1.10")
      and versions_mod.version_key("v1.15.1") == (1, 15, 1)
      and versions_mod.compare_versions("3.7.0", "3.7.1") == "outdated"
      and versions_mod.compare_versions("2.0.1", "1.15.1") == "newer"
      and versions_mod.compare_versions("1.30.2", "1.30.2") == "ok"
      and versions_mod.compare_versions("", "1.0") == "unknown")

EVIDENCE = ("R|nginx|/usr/sbin/nginx\n"
            "V|nginx|running|/usr/sbin/nginx|-v|nginx version: nginx/1.30.2\n"
            "V|loki|installed|/usr/local/bin/loki|--version|Usage of /usr/local/bin/loki:\n"
            "V|loki|installed|/usr/local/bin/loki|-version|loki, version 3.7.1 (branch: release)\n"
            "V|grafana|running|/usr/share/grafana/bin/grafana|--version|Usage of grafana:\n"
            "V|tempo|absent|||\n"
            "V|unknownapp|running|/x|-v|whatever 1.0\n" + versions_mod.PROBE_MARKER + "\n")
_found = versions_mod.parse_probe(EVIDENCE)
check("the report is written from the CATALOG (an app the answer omits is `absent`)",
      sorted(_found) == sorted(versions_mod.DEFAULT_APPS)
      and _found["promtail"]["state"] == "absent" and _found["promtail"]["version"] == "")
check("a version that needed the SECOND flag wins (a usage line never hides a working attempt)",
      _found["loki"]["version"] == "3.7.1" and _found["loki"]["path"] == "/usr/local/bin/loki",
      str(_found["loki"]))
check("an attempt that printed no version still records the app's own state (running)",
      _found["grafana"]["state"] == "running" and _found["grafana"]["version"] == "",
      str(_found["grafana"]))
check("the BEST attempt is chosen: a version first, then the highest state",
      versions_mod.parse_probe("V|tempo|absent|||\n"
                               "V|tempo|installed|/opt/tempo|-v|tempo, version 2.0.1\n")["tempo"]
      == {"state": "installed", "path": "/opt/tempo", "line": "tempo, version 2.0.1",
          "version": "2.0.1"})
check("a line about an app the catalog does not know is ignored (never a phantom row)",
      "unknownapp" not in _found)
check("a `R|` line alone still records the running app (path kept, no version)",
      versions_mod.parse_probe("R|tempo|/opt/tempo/tempo\n")["tempo"] ==
      {"state": "running", "path": "/opt/tempo/tempo", "line": "", "version": ""})

_report = versions_mod.build_report(node("srv-1", "web-1"),
                                    {"nginx": {"state": "running", "path": "/usr/sbin/nginx",
                                               "line": "", "version": "1.30.2"},
                                     "loki": {"state": "running", "path": "/usr/local/bin/loki",
                                              "line": "", "version": "3.7.0"},
                                     "tempo": {"state": "installed", "path": "/opt/tempo/tempo",
                                               "line": "", "version": ""},
                                     "alloy": {"state": "absent", "path": "", "line": "",
                                               "version": ""}},
                                    {"expected": {"nginx": "1.30.2", "loki": "3.7.1",
                                                  "tempo": "2.0.1"}})
_label = "web-1 (10.0.0.1)"          # `PluginNode.label()` — the human text a plugin shows
check("the report lines are greppable: `[ok]`, `[outdated] a -> b` and the path",
      f"{_label}: nginx [ok] 1.30.2 (/usr/sbin/nginx)" in _report["lines"]
      and f"{_label}: loki [outdated] 3.7.0 -> 3.7.1 (/usr/local/bin/loki)" in _report["lines"],
      str(_report["lines"]))
check("an installed (not running) app says so in the same bracket and a version-less one is a drift",
      f"{_label}: tempo [version not detected, not running] (/opt/tempo/tempo)" in _report["lines"],
      str(_report["lines"]))
check("the summary names what is missing and counts the verdicts",
      _report["lines"][-1].startswith(f"{_label}: 3/4 found")
      and "missing: alloy" in _report["lines"][-1]
      and "outdated 1" in _report["lines"][-1], _report["lines"][-1])
check("`drift` counts what a user must act on (an outdated app and an unreadable version)",
      _report["drift"] == 2 and _report["found"] == 3, str(_report))
check("no baseline is a configuration state, not a defect (it must not cry wolf)",
      versions_mod.build_report(node("srv-1"), {"nginx": {"state": "running", "path": "/x",
                                                          "line": "", "version": "1.30.2"}},
                                {})["drift"] == 0)

# ════════════════════════════════════════════════════════════════════════════
print("== §8 the probe budget is DERIVED from the live catalog ==")
# ════════════════════════════════════════════════════════════════════════════

_attempts = sum(len(spec["flags"]) for spec in versions_mod.DEFAULT_APPS.values())
check("the shipped catalog's budget outlives its own worst case (flags x VERSION_TIMEOUT_S)",
      versions_mod.probe_timeout(versions_mod.DEFAULT_APPS)
      > _attempts * versions_mod.VERSION_TIMEOUT_S,
      f"{versions_mod.probe_timeout(versions_mod.DEFAULT_APPS)} vs {_attempts * versions_mod.VERSION_TIMEOUT_S}")
check("the budget GROWS with the catalog (it can never go stale against a bigger baseline)",
      versions_mod.probe_timeout(dict(versions_mod.DEFAULT_APPS,
                                      extra={"cmds": ["extra"], "flags": ["--version"]}))
      - versions_mod.probe_timeout(versions_mod.DEFAULT_APPS)
      == versions_mod.VERSION_TIMEOUT_S,
      str(versions_mod.probe_timeout(dict(versions_mod.DEFAULT_APPS,
                                          extra={"cmds": ["extra"], "flags": ["--version"]}))))
check("an app with no flag list counts the shipped DEFAULT_FLAGS (never zero)",
      versions_mod.probe_timeout({"bare": {"cmds": ["x"]}})
      == len(versions_mod.DEFAULT_FLAGS) * versions_mod.VERSION_TIMEOUT_S
      + versions_mod.PROBE_MARGIN_S)
check("the constant it replaced is gone (a declared budget is what went stale)",
      not hasattr(versions_mod, "PROBE_TIMEOUT_S")
      and "PROBE_TIMEOUT_S" not in read(VERSIONS_SRC))
_timeout_ctx = FakeCtx({"n1": (0, "V|nginx|absent|||\n" + versions_mod.PROBE_MARKER + "\n")})
versions_mod.run_on_nodes([node("n1", "web-1")], _timeout_ctx)
check("the collector ASKS the core for the derived budget (`timeout=` of `ctx.run_command`)",
      _timeout_ctx.timeout == versions_mod.probe_timeout(), str(_timeout_ctx.timeout))
check("a bigger catalog raises the budget the collector asks for",
      versions_mod.probe_timeout(dict(versions_mod.DEFAULT_APPS,
                                      extra={"cmds": ["extra"], "flags": ["--version"]}))
      > versions_mod.probe_timeout(), "the live catalog is the shipped one")

# ════════════════════════════════════════════════════════════════════════════
print("== §9 `app_versions` — the collector, its cache and the baseline file ==")
# ════════════════════════════════════════════════════════════════════════════

check("the plugin's data lives next to the plugin folder (its own files, the core's config untouched)",
      versions_mod.plugin_dir() == PLUGIN_DIR
      and versions_mod.cache_path() == os.path.join(PLUGIN_DIR, versions_mod.CACHE_NAME)
      and versions_mod.baseline_path() == os.path.join(PLUGIN_DIR, versions_mod.BASELINE_NAME)
      and "save_config" not in read(VERSIONS_SRC))
check("a missing baseline is an empty document, never a crash", versions_mod.load_baseline() == {})
write_plugin_file(versions_mod.BASELINE_NAME, "{ not json")
check("a corrupt baseline costs the expectation, never the run",
      versions_mod.load_baseline() == {})

PROBE_ANSWER = ("R|nginx|/usr/sbin/nginx\n"
                "V|nginx|running|/usr/sbin/nginx|-v|nginx version: nginx/1.30.2\n"
                "V|grafana|running|/usr/share/grafana/bin/grafana|--version|grafana version 13.1.1\n"
                + versions_mod.PROBE_MARKER + "\n")
write_plugin_file(versions_mod.BASELINE_NAME, json.dumps({
    "expected": {"nginx": "1.31.0"},
    "nodes": {"web-1": {"grafana": "13.0.0"}},
    "apps": {"custom": {"names": ["custom"], "flags": ["--version"],
                        "paths": ["/opt/custom/custom"], "cmds": ["custom"]}},
    "junk": {"nope": 1}}))
_baseline = versions_mod.load_baseline()
check("the baseline is the USER's file: every block is validated on read, junk is dropped",
      _baseline["expected"] == {"nginx": "1.31.0"}
      and _baseline["nodes"] == {"web-1": {"grafana": "13.0.0"}}
      and "custom" in _baseline["apps"] and "junk" not in _baseline)
check("a user app joins the catalog (extensible without a code change, the safe tokens only)",
      "custom" in versions_mod.catalog()
      and "inject" not in versions_mod.catalog())
check("a per-node block WINS over the global map, and the ID is read last (a rename cannot lose it)",
      versions_mod.expected_versions(node("srv-1", "web-1"),
                                     _baseline)["grafana"] == "13.0.0"
      and versions_mod.expected_versions(node("srv-1", "web-1"),
                                         {"expected": {}, "nodes": {"web-1": {"nginx": "1"},
                                                                    "srv-1": {"nginx": "2"}}})
      ["nginx"] == "2")

remove_plugin_file(versions_mod.CACHE_NAME)
_collect_ctx = FakeCtx({"n1": (0, PROBE_ANSWER)})
versions_mod.run_on_nodes([node("n1", "web-1")], _collect_ctx)
check("the collector stores what the probe found, with the node facts a re-check needs",
      sorted(versions_mod.load_cache()) == ["n1"]
      and versions_mod.load_cache()["n1"]["node"]["host"] == "10.0.0.1"
      and versions_mod.load_cache()["n1"]["apps"]["nginx"]["version"] == "1.30.2")
check("the report leaves as `ctx.log()` lines (the Plugins window shows and exports them)",
      any(f"{_label}: nginx [outdated] 1.30.2 -> 1.31.0" in line for line in _collect_ctx.logs)
      and any(line.startswith(f"{_label}: 2/9 found") for line in _collect_ctx.logs),
      str(_collect_ctx.logs[:3]))
check("the status line counts the nodes and what needs a look",
      _collect_ctx.statuses == ["versions: 1 node(s), 1 to look at"], str(_collect_ctx.statuses))
check("`known_nodes()` is the re-check target: the recorded facts, newest first",
      [facts["id"] for facts in versions_mod.known_nodes()] == ["n1"],
      str(versions_mod.known_nodes()))
check("the cache merges (a node outside this round keeps its previous answer)",
      versions_mod.save_cache({"n2": {"node": {"id": "n2", "host": "10.0.0.2", "port": 22},
                                      "alias": "db-1", "apps": {}, "ts": time.time()}}) is True
      and sorted(versions_mod.load_cache()) == ["n1", "n2"])

_ctx_bad = FakeCtx({"n1": (0, "V|nginx|absent|||\n")})
versions_mod.run_on_nodes([node("n1", "web-1")], _ctx_bad)
check("a probe that did NOT reach its marker is a failure for that node, never a report",
      any("did not finish" in line for line in _ctx_bad.logs)
      and _ctx_bad.statuses == ["versions: 0 node(s), 0 to look at"], str(_ctx_bad.logs))
_ctx_err = FakeCtx({"n1": "authentication failed"})
versions_mod.run_on_nodes([node("n1", "web-1")], _ctx_err)
check("a failed connection is that node's result and is logged, not swallowed",
      any("no answer" in line and "authentication failed" in line for line in _ctx_err.logs),
      str(_ctx_err.logs))
_ctx_empty = FakeCtx()
versions_mod.run_on_nodes([], _ctx_empty)
check("an empty selection says so and asks the core for nothing",
      _ctx_empty.statuses == ["versions: nothing selected"] and _ctx_empty.command is None)

_commands = versions_mod.register_commands(_ctx_empty)
check("`register_commands` returns the two Ctrl+K rows as plain `(text, callback)` pairs",
      len(_commands) == 2 and all(isinstance(text, str) and callable(cb)
                                  for text, cb in _commands)
      and _commands[0][0].startswith("Versions: re-check")
      and _commands[1][0].startswith("Versions: write the baseline"),
      str([text for text, _cb in _commands]))

# The template is seeded from the LAST collection — so it is written while the cache still holds it.
remove_plugin_file(versions_mod.BASELINE_NAME)
_write_ctx = FakeCtx()
versions_mod._write_baseline(_write_ctx)
_template = versions_mod.load_baseline()
check("the Ctrl+K door writes the baseline template, seeded from the last collection",
      os.path.isfile(versions_mod.baseline_path())
      and _write_ctx.statuses and "baseline written" in _write_ctx.statuses[-1],
      str(_write_ctx.statuses))
check("the seed is the NEWEST version seen per app, and a never-seen app is an empty string",
      _template["expected"]["nginx"] == "1.30.2"
      and _template["expected"]["grafana"] == "13.1.1"
      and _template["expected"]["promtail"] == "",
      str({app: _template["expected"][app] for app in ("nginx", "grafana", "promtail")}))
check("the template names every app of the catalog and leaves the nodes / apps blocks empty",
      sorted(_template["expected"]) == sorted(versions_mod.catalog())
      and _template["nodes"] == {} and _template["apps"] == {})
_write_ctx.statuses.clear()
versions_mod._write_baseline(_write_ctx)
check("an EXISTING baseline is kept (it is the user's file, the plugin only SEEDS it)",
      "already exists" in _write_ctx.statuses[-1], str(_write_ctx.statuses))
remove_plugin_file(versions_mod.CACHE_NAME)
versions_mod._recheck_known(_ctx_empty)
check("the re-check door refuses politely while nothing is known (a palette has no map access)",
      _ctx_empty.statuses[-1].startswith("versions: no server is known yet"),
      str(_ctx_empty.statuses))

_many = {}
for _index in range(versions_mod.MAX_RECORDS + 5):
    _many[f"node-{_index:02d}"] = {"node": {"id": f"node-{_index:02d}", "host": "10.0.0.9"},
                                   "alias": f"h{_index}", "apps": {},
                                   "ts": time.time() + _index}
versions_mod.save_cache(_many)
check(f"the cache is bounded at MAX_RECORDS ({versions_mod.MAX_RECORDS}), newest first",
      len(versions_mod.load_cache()) == versions_mod.MAX_RECORDS
      and f"node-{versions_mod.MAX_RECORDS + 4:02d}" in versions_mod.load_cache()
      and "node-00" not in versions_mod.load_cache(), str(len(versions_mod.load_cache())))

# ════════════════════════════════════════════════════════════════════════════
print("== §10 the release state: the examples add NO i18n key ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
check("the two new examples contribute no translation key (a plugin's text is the AUTHOR's)",
      not any(value in ("Copy SSH command", "ports: nothing selected", "versions: nothing selected")
              for data in _langs.values() for value in data.values()))
check("the parity pin is the shipped one (the folder contributes nothing — the releases move it)",
      all(len(translation_keys(data)) == EXPECTED_I18N_KEYS for data in _langs.values()),
      str({code: len(translation_keys(data)) for code, data in _langs.items()}))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("their own prefixes stay outside the parity policy",
      all(fragment not in json.dumps(_langs["en"]) for fragment in
          ("ports: ", "versions: ", "watchlisted", "baseline file")))
check("the release is this file's version or a LATER one (the file describes v1.9.2)",
      releases_at_least(EXPECTED_APP_VERSION, "1.9.2"), EXPECTED_APP_VERSION)
check_release_state(ROOT)
check("examples/README.md documents all FOUR example files (the folder's ONE table)",
      all(stem in read(os.path.join(EXAMPLES_DIR, "README.md"))
          for stem in ("hello", "disk_monitor", "open_ports", "app_versions")))
check("the suite map lists this topical file (tests/INDEX.md regenerated)",
      "test_plugin_examples_monitors.py" in read(os.path.join(ROOT, "tests", "INDEX.md")))

clean_plugins()
clear_cfg()
finish()
