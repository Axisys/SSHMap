# -*- coding: utf-8 -*-
"""v1.4 — the example plugins of `examples/plugins/` (the minimal one and the two monitors).

EVERY example file loads through the REAL discovery path of `PluginManager` (copied into the isolated
`~/.sshmap/plugins/`, then `discover()`), never a syntax check, and its hooks are driven; the newer
files are driven in DEPTH by `tests/test_plugin_examples_monitors.py` (the two proven monitors) and by
`tests/test_plugin_examples_local.py` (the two whose fact is local). §1 the whole folder as plugins
(the manifests, the hooks, the shared "a plugin never imports the core" predicate of `_common.py`);
§2 `hello` (Copy SSH command + Copy the plugins folder path); §3–§5 `disk_monitor`'s `df -hP` parser,
its atomic cache and the 90% threshold; §6 the collector on a fake context; §7 the reporter end to
end; §8 the release state (the examples add NO i18n key)."""
import json
import os
import re
import shutil
import sys
import threading
import time

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, translation_keys,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, clear_cfg,
                     wait_for as _wait_for,
                     releases_at_least, example_plugin_problems)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation inside)

from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import modules.plugin_manager as PM  # noqa: E402
import modules.plugin_runner as PR  # noqa: E402
import ui.main_window as MW  # noqa: E402
from models.server import ServerData  # noqa: E402

EXAMPLES_DIR = os.path.join(ROOT, "examples")
PLUGINS_SRC = os.path.join(EXAMPLES_DIR, "plugins")
HELLO_SRC = os.path.join(PLUGINS_SRC, "hello.py")
DISK_SRC = os.path.join(PLUGINS_SRC, "disk_monitor.py")
PORTS_SRC = os.path.join(PLUGINS_SRC, "open_ports.py")
VERSIONS_SRC = os.path.join(PLUGINS_SRC, "app_versions.py")
SYSTEMD_SRC = os.path.join(PLUGINS_SRC, "systemd_failed.py")
MAINTENANCE_SRC = os.path.join(PLUGINS_SRC, "maintenance.py")
CERTIFICATES_SRC = os.path.join(PLUGINS_SRC, "certificates.py")
WATCH_SRC = os.path.join(PLUGINS_SRC, "watch_command.py")
PLUGIN_DIR = PM.user_plugin_dir()
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")

# The EIGHT examples every section below installs (the rule of the folder is read from a file).
EXAMPLE_FILES = ((HELLO_SRC, "hello", (PM.HOOK_REGISTER_COMMANDS, PM.HOOK_NODE_CONTEXT_MENU)),
                 (DISK_SRC, "disk_monitor", (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES)),
                 (PORTS_SRC, "open_ports", (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES)),
                 (VERSIONS_SRC, "app_versions", (PM.HOOK_REGISTER_COMMANDS, PM.HOOK_RUN_ON_NODES)),
                 (SYSTEMD_SRC, "systemd_failed", (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES)),
                 (MAINTENANCE_SRC, "maintenance", (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES)),
                 (CERTIFICATES_SRC, "certificates", (PM.HOOK_STATUS_PROBE,)),
                 (WATCH_SRC, "watch_command", (PM.HOOK_REGISTER_COMMANDS, PM.HOOK_STATUS_PROBE,
                                               PM.HOOK_RUN_ON_NODES)))


# ── helpers ──────────────────────────────────────────────────────────────────

def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def clean_plugins():
    """Empty the user plugin folder (the copied examples, their cache, the import cache)."""
    if os.path.isdir(PLUGIN_DIR):
        for name in os.listdir(PLUGIN_DIR):
            try:
                os.remove(os.path.join(PLUGIN_DIR, name))
            except OSError:
                pass
    for key in [k for k in sys.modules if k.startswith(PM.LOCAL_MODULE_PREFIX)]:
        sys.modules.pop(key, None)


def install_examples():
    """Copy the EIGHT examples into the sandbox plugin folder — what a user does by hand."""
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


def safe_certificates():
    """Give `certificates` a canned, comfortably valid peer certificate.

    That example's `status_probe` opens a REAL TLS connection by design (the folder's rule allows the
    standard library), so the suite replaces the module's injectable `CONNECTOR` instead of letting a
    status round of this file reach the network. A certificate far in the future is "no opinion",
    which is what the checks of THIS file expect from it — its own lesson is
    `tests/test_plugin_examples_local.py`.
    """
    module = local("certificates")
    if module is None:
        return None
    moment = time.time() + 300 * 86400 + 3600
    module.CONNECTOR = lambda host, port, timeout=1.0: {
        "notAfter": time.strftime("%b %d %H:%M:%S %Y GMT", time.gmtime(moment))}
    return module


def wait_until(predicate, timeout_ms=6000):
    """The v1.4.1 suite cleanup: the shared boolean poll (see _common.wait_for)."""
    return _wait_for(predicate, timeout_ms=timeout_ms)


def menu_texts(menu):
    return [a.text() for a in menu.actions() if a.text()]


class FakeResult:
    """The core's `PluginRunResult` shape, built by hand (the collector needs no socket)."""

    def __init__(self, node, exit_code=-1, output="", error=""):
        self.node = node
        self.exit_code = exit_code
        self.output = output
        self.error = error


class FakeCtx:
    """A context that RECORDS what a plugin asked for — the collector's unit-test seam.

    The real `ctx.run_command` is a core service on a managed worker; here the answers are
    canned, so the whole collector (parsing, the cache write, the reports) is driven
    without a socket — the same spirit as the runner's injectable transport.
    """

    def __init__(self, answers=None, accept=True):
        self.answers = dict(answers or {})
        self.accept = accept
        self.statuses = []
        self.logs = []
        self.command = None
        self.nodes = None

    def status(self, text, timeout_ms=5000):
        self.statuses.append(str(text))
        return True

    def log(self, message):
        self.logs.append(str(message))

    def run_command(self, nodes, command, on_result=None, on_finished=None, timeout=None):
        if not self.accept:
            return False
        self.command = str(command)
        self.nodes = list(nodes)
        results = []
        for node in self.nodes:
            answer = self.answers.get(node.id)
            if answer is None:
                result = FakeResult(node, error="connection refused")
            elif isinstance(answer, str):
                result = FakeResult(node, error=answer)
            else:
                code, output = answer
                result = FakeResult(node, exit_code=code, output=output)
            results.append(result)
            if callable(on_result):
                on_result(node, result)
        if callable(on_finished):
            on_finished(results)
        return True


def node(node_id, alias="web-1", host="10.0.0.1"):
    """A plugin-visible node record (what a hook really receives)."""
    return PM.PluginNode(id=node_id, alias=alias, host=host, port=22, user="root")


DF_TABLE = ("Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1        98G   39G   54G  42% /\n"
            "/dev/sda2       200G  180G   12G  92% /var\n"
            "tmpfs           3.9G  1.1G  2.8G  29% /dev/shm\n")


def write_cache(document):
    """Write the plugin's cache file directly (the corrupt / foreign / hand-made cases)."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    with open(os.path.join(PLUGIN_DIR, "disk_monitor.state.json"), "w",
              encoding="utf-8") as handle:
        if isinstance(document, str):
            handle.write(document)
        else:
            json.dump(document, handle)


def remove_cache():
    try:
        os.remove(os.path.join(PLUGIN_DIR, "disk_monitor.state.json"))
    except OSError:
        pass


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the examples as plugins: the REAL discovery path ==")
# ════════════════════════════════════════════════════════════════════════════

check("the EIGHT examples exist as plain files in examples/plugins/",
      all(os.path.isfile(src) for src, _stem, _hooks in EXAMPLE_FILES),
      [os.path.basename(src) for src, _s, _h in EXAMPLE_FILES if not os.path.isfile(src)])
check("examples/README.md explains what the folder is (and that it is not installed)",
      os.path.isfile(os.path.join(EXAMPLES_DIR, "README.md")))

# NOT auto-discovered: the repository folder is not one of the discovery sources, so an
# empty user folder finds nothing even though the files sit in the checkout.
_empty = new_manager()
check("the examples are NOT auto-discovered from the repository (an empty folder = no plugin)",
      _empty.records() == [] and all(_empty.get(stem) is None for _s, stem, _h in EXAMPLE_FILES),
      str([r.plugin_id for r in _empty.records()]))
check("the folder source is the user folder, not the checkout's examples/",
      PM.user_plugin_dir() != PLUGINS_SRC
      and os.path.basename(PM.user_plugin_dir()) == "plugins")

install_examples()
_manager = new_manager()
_records = {stem: _manager.get(stem) for _s, stem, _h in EXAMPLE_FILES}
hello = _manager.get("hello")
disk = _manager.get("disk_monitor")
check("a copied example is discovered by the real manager (no packaging, no install)",
      all(rec is not None and rec.ok is True for rec in _records.values()),
      str([(r.plugin_id, r.state) for r in _manager.records()]))
check("every manifest carries id, version, api_version and a description",
      all(rec.version == "1.0" and rec.api_version == PM.API_VERSION and rec.description
          for rec in _records.values())
      and "minimal" in hello.description and "disk usage" in disk.description
      and "systemd units" in _records["systemd_failed"].description
      and "certificate" in _records["certificates"].description,
      {stem: (rec.version, rec.api_version) for stem, rec in _records.items()})
check("every example declares its hooks and is really IMPORTED from the folder",
      all(_records[stem].hooks == hooks for _s, stem, hooks in EXAMPLE_FILES),
      {stem: rec.hooks for stem, rec in _records.items()})
check("every example is source=folder with its own file as the origin",
      all(rec.source == PM.SOURCE_FOLDER and rec.origin.endswith(f"{stem}.py")
          for stem, rec in _records.items()),
      {stem: rec.origin for stem, rec in _records.items()})
check("the imported modules are the files themselves (the discovery exec'd them)",
      all(local(stem) is not None and local(stem).MANIFEST["name"] == stem
          for _s, stem, _h in EXAMPLE_FILES),
      [stem for _s, stem, _h in EXAMPLE_FILES if local(stem) is None])

for _path, _stem, _hooks in EXAMPLE_FILES:
    _name = os.path.basename(_path)
    _src = read(_path)
    # The predicate lives in `tests/_common.py` ONCE: the monitors' own topical file reads it too.
    check(f"{_name}: NO import of the core, no path trick, no SSH library (the folder's rule)",
          example_plugin_problems(_name, _src) == [], example_plugin_problems(_name, _src))
    check(f"{_name}: every hook it claims is a callable in the file",
          all(callable(getattr(local(_stem), h, None)) for h in _hooks))
_manager.shutdown(500)

# ════════════════════════════════════════════════════════════════════════════
print("== §2 `hello` — the minimal plugin: a useful palette command + a context-menu row ==")
# ════════════════════════════════════════════════════════════════════════════

hello = _manager.get("hello")
_commands = [cmd for pid, cmd in _manager.plugin_commands() if pid == "hello"]
check("its `register_commands` reaches the palette as ONE command (the lenient pair shape)",
      len(_commands) == 1 and _commands[0].text == "Copy the plugins folder path",
      str([c.text for c in _commands]))
check("the record carries a callback the core can run (the pair's second element)",
      callable(_commands[0].callback))

_seen_status = []
_seen_logs = []
_manager.status_requested.connect(lambda pid, text, ms: _seen_status.append((pid, text)))
_manager.plugin_message.connect(lambda pid, text: _seen_logs.append((pid, text)))
_ctx = _manager._context_for(hello)
local("hello").COPIED.clear()
local("hello").PALETTE_RUNS.clear()
_manager.call_hook_wrapped("hello", PM.HOOK_REGISTER_COMMANDS, _commands[0].callback, _ctx)
_plugins_dir = os.path.join(os.path.expanduser("~"), ".sshmap", "plugins")
check("the palette callback receives the plugin's OWN context and computes its own data",
      local("hello").COPIED == [_plugins_dir]
      and QApplication.clipboard().text() == _plugins_dir,
      f"{local('hello').COPIED} / {QApplication.clipboard().text()!r}")
check("running it goes through the wrapper with the plugin's OWN context (ctx.plugin_id)",
      local("hello").PALETTE_RUNS == ["hello"], str(local("hello").PALETTE_RUNS))
check("it reports the copied line through `ctx.status` (a signal — the window owns the status bar)",
      _seen_status == [("hello", f"hello: copied {_plugins_dir}")], str(_seen_status))
check("it logs through `ctx.log` as well (the Plugins window shows the plugin's own words)",
      _seen_logs and _seen_logs[-1][0] == "hello" and "copied" in _seen_logs[-1][1],
      str(_seen_logs))

_menu = QMenu()
_asked = _manager.plugin_node_context_menu(_menu, node("n1", "web-1", "10.0.0.1"))
check("its `extend_node_context_menu` appends its row to a node menu",
      "Copy SSH command" in menu_texts(_menu) and _asked >= 1, str(menu_texts(_menu)))
local("hello").COPIED.clear()
next(a for a in _menu.actions() if a.text() == "Copy SSH command").trigger()
check("the row's action receives the node RECORDS the core narrowed (never the scene objects)",
      QApplication.clipboard().text() == "ssh -p 22 root@10.0.0.1",
      repr(QApplication.clipboard().text()))
check("the ssh line is BUILT from the record (`ssh -p <port> <user>@<host>`, a pure function)",
      local("hello").ssh_command(PM.PluginNode(id="n9", host="10.0.0.9", port=22, user=""))
      == "ssh -p 22 10.0.0.9"
      and local("hello").ssh_command(PM.PluginNode(id="n8", host="10.0.0.8", port=2222,
                                                   user="admin"))
      == "ssh -p 2222 admin@10.0.0.8",
      local("hello").ssh_command(PM.PluginNode(id="n8", host="10.0.0.8", port=2222,
                                               user="admin")))
_menu2 = QMenu()
_manager.plugin_node_context_menu(_menu2, [node("n2", "db", "10.0.0.2"),
                                           node("n3", "db2", "10.0.0.3")])
next(a for a in _menu2.actions() if a.text() == "Copy SSH command").trigger()
check("a multi-node click copies ONE line per record (the whole selection in one clipboard)",
      QApplication.clipboard().text() == "ssh -p 22 root@10.0.0.2\nssh -p 22 root@10.0.0.3",
      repr(QApplication.clipboard().text()))
check("this hook gets NO ctx — the clipboard call is the plugin's own Qt use (the lesson)",
      "def extend_node_context_menu(menu, nodes):" in read(HELLO_SRC)
      and "ctx" not in read(HELLO_SRC).split("def extend_node_context_menu")[1].split("\ndef ")[0])

# ════════════════════════════════════════════════════════════════════════════
print("== §3 `disk_monitor` — the `df -hP` parser (fixtures, no socket) ==")
# ════════════════════════════════════════════════════════════════════════════

disk_mod = local("disk_monitor")
check("the parser is a pure function of the answer (one place, no IO, no SSH library)",
      callable(disk_mod.parse_df) and callable(disk_mod.parse_percent)
      and example_plugin_problems("disk_monitor.py", read(DISK_SRC)) == [])

check("a normal `df -hP` table → the worst real filesystem (percent, mount)",
      disk_mod.parse_df(DF_TABLE) == (92, "/var"), str(disk_mod.parse_df(DF_TABLE)))
check("the worst of SEVERAL wins, wherever it sits in the table",
      disk_mod.parse_df("Filesystem  Size Used Avail Use% Mounted on\n"
                        "/dev/sda1    98G  95G  3.0G  97% /\n"
                        "/dev/sda2   200G  20G  180G  10% /var\n") == (97, "/"))
check("a mount point with a SPACE stays in one piece (`-P` writes it last)",
      disk_mod.parse_df("Filesystem  Size Used Avail Use% Mounted on\n"
                        "/dev/sdb1   500G 475G   25G  95% /mnt/my data\n")
      == (95, "/mnt/my data"))
check("the header alone is not a filesystem",
      disk_mod.parse_df("Filesystem      Size  Used Avail Use% Mounted on\n") is None)
check("pseudo-filesystems are ignored (a full tmpfs is not a full disk)",
      disk_mod.parse_df("Filesystem  Size Used Avail Use% Mounted on\n"
                        "tmpfs       3.9G 3.9G     0 100% /run\n"
                        "devtmpfs    7.8G    0  7.8G   0% /dev\n"
                        "overlay      50G  49G     0 100% /var/lib/docker/overlay2\n"
                        "none         50G  49G     0 100% /none\n") is None)
check("a truncated line / a `df:` warning is skipped, not guessed at",
      disk_mod.parse_df("Filesystem  Size Used Avail Use% Mounted on\n"
                        "df: /mnt/x: No such file or directory\n"
                        "/dev/sda1    98G  39G\n") is None)
check("an empty / missing answer is `None` (a node with no answer)",
      disk_mod.parse_df("") is None and disk_mod.parse_df(None) is None)
check("a locale-decimal `Use%` is read leniently (the `-P` guard)",
      disk_mod.parse_df("Filesystem  Size Used Avail Use% Mounted on\n"
                        "/dev/sda1    98G  39G   54G  92,5% /\n") == (92, "/"))
check("`Use%` outside 0..100 is clamped, never a crash",
      disk_mod.parse_percent("120%") == 100 and disk_mod.parse_percent("-5%") == 0)
check("a non-percentage value yields None (a header, a word, an empty cell)",
      disk_mod.parse_percent("Use%") is None and disk_mod.parse_percent("abc") is None
      and disk_mod.parse_percent("") is None and disk_mod.parse_percent(None) is None)
check("`parse_percent` accepts the stored integer form too (the cache round-trip)",
      disk_mod.parse_percent(92) == 92 and disk_mod.parse_percent(0) == 0)

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the plugin's own cache (atomic, bounded, disposable) ==")
# ════════════════════════════════════════════════════════════════════════════

check("the cache lives next to the plugin folder, not in the application's config",
      disk_mod.cache_path() == os.path.join(PLUGIN_DIR, "disk_monitor.state.json")
      and disk_mod.cache_path().endswith(disk_mod.CACHE_NAME),
      disk_mod.cache_path())
check("no application config is written by the plugin (its data is its own file)",
      "save_config" not in read(DISK_SRC) and "load_config" not in read(DISK_SRC))

remove_cache()
check("an absent cache is an empty mapping (never an exception)",
      disk_mod.load_cache() == {})
check("`save_cache` writes the document and `load_cache` reads it back",
      disk_mod.save_cache({"n1": {"alias": "web-1", "percent": 92, "mount": "/var",
                                  "ts": time.time()}}) is True
      and disk_mod.load_cache()["n1"]["percent"] == 92
      and disk_mod.load_cache()["n1"]["mount"] == "/var")
check("a node ABSENT from this round keeps its previous answer (a merge, not a replace)",
      disk_mod.save_cache({"n2": {"alias": "db-1", "percent": 30, "mount": "/",
                                  "ts": time.time()}}) is True
      and sorted(disk_mod.load_cache()) == ["n1", "n2"], str(sorted(disk_mod.load_cache())))
check("the write is ATOMIC — no temp file is left behind in the folder",
      [n for n in os.listdir(PLUGIN_DIR) if n.endswith(".tmp")] == []
      and [n for n in os.listdir(PLUGIN_DIR) if n.startswith(".disk_monitor-")] == [],
      str(os.listdir(PLUGIN_DIR)))
check("a record without a usable percentage is dropped, not stored",
      disk_mod.save_cache({"n3": {"alias": "x", "percent": "nope", "mount": "/"}}) is True
      and "n3" not in disk_mod.load_cache())
check("junk input is refused without raising",
      disk_mod.save_cache(["not", "a", "mapping"]) is False
      and disk_mod.save_cache(None) is False)

_records = {}
_now = time.time()
for index in range(disk_mod.MAX_RECORDS + 5):
    _records[f"node-{index:02d}"] = {"alias": f"h{index}", "percent": 50, "mount": "/",
                                     "ts": _now + index}
disk_mod.save_cache(_records)
_stored = disk_mod.load_cache()
check(f"the cache is bounded at MAX_RECORDS ({disk_mod.MAX_RECORDS}) records",
      len(_stored) == disk_mod.MAX_RECORDS, str(len(_stored)))
check("the pruning keeps the NEWEST records (the oldest are the ones that go)",
      f"node-{disk_mod.MAX_RECORDS + 4:02d}" in _stored
      and "node-00" not in _stored and "node-04" not in _stored,
      f"{sorted(_stored)[:2]} … {sorted(_stored)[-1:]}")

write_cache("{ this is not json at all")
check("a corrupt cache is `{}` — a probe round never breaks on it",
      disk_mod.load_cache() == {} and disk_mod.status_probe(node("n1")) is None)
write_cache([1, 2, 3])
check("a foreign document (a list root) is `{}` as well", disk_mod.load_cache() == {})
write_cache({"version": 1, "records": "nope"})
check("a document without a records mapping is `{}`", disk_mod.load_cache() == {})

_original_path = disk_mod.cache_path
disk_mod.cache_path = lambda: os.path.join(WORK, "cache_blocker", "disk.json")
with open(os.path.join(WORK, "cache_blocker"), "w", encoding="utf-8") as handle:
    handle.write("a FILE where a directory is needed")
check("a write that cannot happen returns False and never raises",
      disk_mod.save_cache({"n1": {"percent": 99, "mount": "/", "ts": time.time()}}) is False)
disk_mod.cache_path = _original_path

# ════════════════════════════════════════════════════════════════════════════
print("== §5 the reporter: the threshold, the exact detail, staleness ==")
# ════════════════════════════════════════════════════════════════════════════

disk_mod.save_cache({"low": {"alias": "low", "percent": 89, "mount": "/", "ts": time.time()},
                     "edge": {"alias": "edge", "percent": 90, "mount": "/var",
                              "ts": time.time()},
                     "high": {"alias": "high", "percent": 92, "mount": "/var",
                              "ts": time.time()},
                     "old": {"alias": "old", "percent": 99, "mount": "/",
                             "ts": time.time() - disk_mod.STALE_SECONDS - 60}})
check("89% → no opinion at all (a probe returns `None`, not a weaker status)",
      disk_mod.status_probe(node("low")) is None)
check("90% → `warn` — the boundary itself counts (>=, not >)",
      disk_mod.status_probe(node("edge")) == ("warn", "/var 90% (threshold 90)"),
      str(disk_mod.status_probe(node("edge"))))
check("the detail carries the offending mount point and its percentage",
      disk_mod.status_probe(node("high")) == ("warn", "/var 92% (threshold 90)"),
      str(disk_mod.status_probe(node("high"))))
check("the kind is one of the contract's three (the core merges by severity)",
      disk_mod.status_probe(node("high"))[0] in ("online", "warn", "offline"))
check("a STALE record is not an opinion any more",
      disk_mod.status_probe(node("old")) is None)
check("an unknown node is no opinion (a node that left the map)",
      disk_mod.status_probe(node("never-seen")) is None
      and disk_mod.status_probe(PM.PluginNode(id="")) is None)
check("the reporter reads the cache and touches NOTHING else (a probe runs per node per round)",
      "run_command" not in read(DISK_SRC).split("def status_probe")[1].split("\ndef ")[0]
      and example_plugin_problems("disk_monitor.py", read(DISK_SRC)) == [])
check("`fresh_record` honours an explicit clock (the staleness rule is testable)",
      disk_mod.fresh_record("high", now=time.time() + disk_mod.STALE_SECONDS + 10) is None
      and disk_mod.fresh_record("high") is not None)

# ════════════════════════════════════════════════════════════════════════════
print("== §6 the collector: `run_on_nodes` on a fake context (no socket) ==")
# ════════════════════════════════════════════════════════════════════════════

remove_cache()
disk_mod = local("disk_monitor")
check("the module under test is the one the discovery really exec'd",
      disk_mod is not None and disk_mod.MANIFEST["name"] == "disk_monitor")

_nodes = [node("n1", "web-1"), node("n2", "db-1", "10.0.0.2")]
_ctx = FakeCtx({"n1": (0, DF_TABLE), "n2": (0, "Filesystem Size Used Avail Use% Mounted on\n"
                                              "/dev/sdc1 400G 160G 240G 40% /data\n")})
disk_mod.run_on_nodes(_nodes, _ctx)
check("the collector runs exactly the documented command (`-P`: a fixed layout, no decimals)",
      _ctx.command == "df -hP" and disk_mod.COMMAND == "df -hP", str(_ctx.command))
check("one result per node was parsed into the cache",
      sorted(disk_mod.load_cache()) == ["n1", "n2"], str(sorted(disk_mod.load_cache())))
check("the WORST filesystem of each node is what is stored",
      disk_mod.load_cache()["n1"]["percent"] == 92
      and disk_mod.load_cache()["n1"]["mount"] == "/var"
      and disk_mod.load_cache()["n2"]["percent"] == 40
      and disk_mod.load_cache()["n2"]["mount"] == "/data"
      and disk_mod.load_cache()["n2"]["alias"] == "db-1",
      str(disk_mod.load_cache()))
check("the status line reports the nodes that answered and those over the threshold",
      _ctx.statuses == ["disk: 2 node(s), 1 over the threshold"], str(_ctx.statuses))
check("every node is logged with its worst mount (the per-node detail)",
      any("web-1" in line and "/var 92%" in line for line in _ctx.logs)
      and any("db-1" in line and "/data 40%" in line for line in _ctx.logs),
      str(_ctx.logs))
check("after the round the reporter warns for the full node and stays silent for the other",
      disk_mod.status_probe(node("n1")) == ("warn", "/var 92% (threshold 90)")
      and disk_mod.status_probe(node("n2")) is None)

_stamp_n2 = disk_mod.load_cache()["n2"]["ts"]
_ctx2 = FakeCtx({"n1": (0, DF_TABLE), "n2": "authentication failed"})
disk_mod.run_on_nodes(_nodes, _ctx2)
check("ONE node's failure is a result for THAT node — the neighbours still land in the cache",
      "n1" in disk_mod.load_cache() and "n2" in disk_mod.load_cache())
check("…and the failed node's PREVIOUS answer is kept, not refreshed (the cache merges)",
      disk_mod.load_cache()["n2"]["ts"] == _stamp_n2,
      f"{disk_mod.load_cache()['n2']['ts']} vs {_stamp_n2}")
check("the failure is logged per node, not swallowed",
      any("db-1" in line and "authentication failed" in line for line in _ctx2.logs),
      str(_ctx2.logs))
check("the status line counts what answered (2 nodes asked, 1 answered)",
      _ctx2.statuses == ["disk: 1 node(s), 1 over the threshold"], str(_ctx2.statuses))
check("the failure is summarised once at the end of the round",
      any("without an answer" in line and "n2" in line for line in _ctx2.logs),
      str(_ctx2.logs))

_ctx3 = FakeCtx({"n1": (0, "df: no such file\n")})
disk_mod.run_on_nodes([node("n1", "web-1")], _ctx3)
check("an unparseable answer is a result for that node, never an exception",
      any("no filesystem" in line for line in _ctx3.logs) and _ctx3.statuses
      == ["disk: 0 node(s), 0 over the threshold"], str(_ctx3.logs))

_ctx4 = FakeCtx()
disk_mod.run_on_nodes([], _ctx4)
check("an empty selection does nothing and says so", _ctx4.statuses == ["disk: nothing selected"]
      and _ctx4.command is None, str(_ctx4.statuses))
_ctx5 = FakeCtx({}, accept=False)
disk_mod.run_on_nodes(_nodes, _ctx5)
check("a REFUSED `run_command` is a log line and an honest status, not a crash",
      _ctx5.statuses == ["disk: nothing to do"]
      and any("refused" in line for line in _ctx5.logs), str(_ctx5.logs))

# ════════════════════════════════════════════════════════════════════════════
print("== §7 the reporter end to end: the real manager + the runner seam ==")
# ════════════════════════════════════════════════════════════════════════════

clean_plugins()
clear_cfg()
install_examples()
_manager = new_manager()
safe_certificates()
_manager.set_nodes([ServerData(id="srv-1", alias="web-1", host="10.0.0.10", user="root"),
                    ServerData(id="srv-2", alias="db-1", host="10.0.0.11", user="root")])

_ORIG_TRANSPORT = PR.run_command_over_ssh
_ORIG_CREDENTIALS = PR.default_credentials


def _fake_transport(node, command, timeout, credentials):
    """The runner's documented test seam: a canned `df -hP` per node, no network."""
    if node.id == "srv-2":
        return PR.PluginRunResult(node=node, error="connection timed out")
    return PR.PluginRunResult(node=node, exit_code=0, output=DF_TABLE)


PR.run_command_over_ssh = _fake_transport
PR.default_credentials = lambda node, facts=None: {"password": "secret", "key_path": ""}
try:
    # `ctx.run_command` called from a plugin's WORKER thread (the regression the dogfooding found). The
    # receiver context of a signal connected to a plain Python callable is the thread that calls
    # `connect()` (`AGENTS.md` §7 gotcha #20), so a runner built inside a `run_on_nodes` worker would post
    # its results into a thread with no event loop — and lose them silently. Calling the service from a
    # bare `threading.Thread` is the smallest reproduction of that path.
    _from_worker = []

    def _call_from_a_worker():
        _manager.plugin_run_command(
            "probe", [PM.PluginNode(id="srv-3", alias="w3", host="10.0.0.12")], "df -hP",
            on_result=lambda n, r: _from_worker.append(n.id),
            on_finished=lambda rs: _from_worker.append("done"))

    _thread = threading.Thread(target=_call_from_a_worker)
    _thread.start()
    _thread.join(5)
    check("a command started from a WORKER thread still delivers its callbacks (the v1.4 fix)",
          wait_until(lambda: "done" in _from_worker) is not False
          and _from_worker == ["srv-3", "done"], str(_from_worker))

    _started = _manager.plugin_run_on_nodes(None)
    check("`run_on_nodes` starts EVERY capable example on the registry's nodes (one per plugin)",
          _started == 6, str(_started))
    check("the round really finished — the cache has the answer and nothing is left running",
          wait_until(lambda: "srv-1" in local("disk_monitor").load_cache()) is not False
          and wait_until(lambda: _manager.active_workers() == []
                         and _manager.running_commands() == 0) is not False,
          f"{sorted(local('disk_monitor').load_cache())} "
          f"{_manager.running_commands()} {_manager.active_workers()}")
    check("the collector's cache reached the disk through the REAL path",
          "srv-1" in local("disk_monitor").load_cache()
          and "srv-2" not in local("disk_monitor").load_cache(),
          str(sorted(local("disk_monitor").load_cache())))
    check("the merged opinion of a node with a full disk is `warn` + the mount detail",
          _manager.status_provider("srv-1", "online")
          == ("warn", "/var 92% (threshold 90)"),
          str(_manager.status_provider("srv-1", "online")))
    check("the WORSE of the two statuses wins — a full disk never hides an offline host",
          _manager.status_provider("srv-1", "offline")[0] == "offline"
          and _manager.status_probe_for(node("srv-1"), "online")[0] == "warn")
    check("a node without a cached answer adds NO plugin opinion (the SSH probe stands alone)",
          _manager.status_provider("srv-2") is None
          and _manager.status_probe_for(node("srv-2")) is None
          and _manager.status_provider("unknown-id", "online") is None,
          f"{_manager.status_provider('srv-2')} / {_manager.status_provider('unknown-id', 'online')}")
    check("a DISABLED plugin contributes no status (the switch stops the hooks)",
          _manager.set_enabled("disk_monitor", False) is True
          and _manager.status_provider("srv-1") is None
          and _manager.status_provider("srv-1", "online") == ("online", ""))
    _manager.set_enabled("disk_monitor", True)
    check("…and re-enabling brings the opinion back", _manager.status_provider("srv-1") is not None)
finally:
    PR.run_command_over_ssh = _ORIG_TRANSPORT
    PR.default_credentials = _ORIG_CREDENTIALS
    _manager.shutdown(1500)

# The user-visible pass: the window's "Run on selected servers" over the example plugin.
local("disk_monitor").save_cache({})
_win = MW.MainWindow()
_win._autosave_timer.stop()
_win.scene.add_server(ServerData(id="w-1", alias="web-1", host="10.0.0.20",
                                 user="root", x=40.0, y=40.0))
_win.refresh_sidebar()
_win.start_plugin_discovery()
safe_certificates()          # the window re-exec'd the folder: the canned TLS connector is re-armed
app.processEvents()
check("the window discovers the example plugins on startup",
      all(_win._plugin_manager.get(stem) is not None and _win._plugin_manager.get(stem).ok
          for _s, stem, _h in EXAMPLE_FILES),
      str([(r.plugin_id, r.state) for r in _win._plugin_manager.records()]))
_win._command_palette._collect_commands()
check("`hello` really feeds the Ctrl+K palette of the WINDOW (the author's text verbatim)",
      "Copy the plugins folder path" in [c[0] for c in _win._command_palette._commands]
      and [c[1] for c in _win._command_palette._commands
           if c[0] == "Copy the plugins folder path"] == ["plugin"],
      str([c[0] for c in _win._command_palette._commands][-5:]))
check("the palette also carries the two plugins that only collect (their own Ctrl+K rows)",
      "Versions: re-check every known server" in [c[0] for c in _win._command_palette._commands],
      str([c[0] for c in _win._command_palette._commands][-8:]))
check("its `run_on_nodes` enables the menu item (an empty cache does not change that)",
      _win.act_plugins_run.isEnabled() is True)
PR.run_command_over_ssh = lambda node, command, timeout, credentials: PR.PluginRunResult(
    node=node, exit_code=0, output=DF_TABLE)
# The menu door starts EVERY capable example (six of the eight now), so the status bar is a race
# between their own lines: the SIGNAL is collected and the bar is checked to be one of them.
_seen_lines = []
_win._plugin_manager.status_requested.connect(lambda pid, text, ms: _seen_lines.append(str(text)))
try:
    _win.act_plugins_run.trigger()
    check("the menu round reports through the plugins' OWN status lines",
          wait_until(lambda: any(line.startswith("disk: ") for line in _seen_lines)) is not False,
          str(_seen_lines))
    check("the Disk Space Monitor's summary is the shipped one (1 node, 1 over the threshold)",
          "disk: 1 node(s), 1 over the threshold" in _seen_lines, str(_seen_lines))
    check("the status bar shows one of those lines (the window owns the widget)",
          _win.statusBar().currentMessage() in _seen_lines,
          f"{_win.statusBar().currentMessage()!r} / {_seen_lines}")
finally:
    PR.run_command_over_ssh = _ORIG_TRANSPORT
_node = _win.scene.get_node("w-1")
_status, _detail = _win._plugin_manager.status_provider("w-1", "online")
_node.set_status(_status, _detail)
check("the card ends up `warn` and its tooltip carries the offending mount (the v1 result)",
      _node.status == "warn" and "/var 92%" in _node.toolTip(),
      f"{_node.status} | {_node.toolTip()!r}")
_win._plugin_manager.shutdown(1500)
_win.close()

# ════════════════════════════════════════════════════════════════════════════
print("== §8 the release state: the examples add NO i18n key ==")
# ════════════════════════════════════════════════════════════════════════════

_langs = load_i18n_langs(ROOT)
check("the examples contribute no translation key (a plugin's text is the AUTHOR's)",
      not any("Copy SSH command" == value or "Copy the plugins folder path" == value
              for data in _langs.values() for value in data.values()))
check("the parity pin is the shipped one (the examples contribute nothing — the releases "
      "move the pin, not this file; v1.6 left it at 778, v1.7rc1's five and v1.7rc2's eight moved it again)",
      EXPECTED_I18N_KEYS >= 854 and all(len(translation_keys(d)) == EXPECTED_I18N_KEYS
                                         for d in _langs.values()),
      str({c: len(translation_keys(d)) for c, d in _langs.items()}))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("the plugin strings of the examples stay outside the parity policy",
      all(fragment not in json.dumps(_langs["en"]) for fragment in
          ("disk: ", "threshold 90", "ports: ", "versions: ", "ssh -p ", "systemd: ",
           "maintenance: ", "reboot required", "watch: ")))
check("the release is the version this file ships with (the pin quotes the shipped one)",
      releases_at_least(EXPECTED_APP_VERSION, "1.7"), EXPECTED_APP_VERSION)
check_release_state(ROOT)
check("every example file is described in examples/README.md",
      all(stem in read(os.path.join(EXAMPLES_DIR, "README.md"))
          for _s, stem, _h in EXAMPLE_FILES),
      [stem for _s, stem, _h in EXAMPLE_FILES
       if stem not in read(os.path.join(EXAMPLES_DIR, "README.md"))])
check("the suite map lists this topical file (tests/INDEX.md regenerated)",
      "test_plugin_examples.py" in read(os.path.join(ROOT, "tests", "INDEX.md")))

clean_plugins()
clear_cfg()
finish()
