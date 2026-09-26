# -*- coding: utf-8 -*-
"""v1.4 — the two example plugins (`examples/plugins/hello.py`, `disk_monitor.py`).

ROADMAP tasks 11–12 (the base release `v1.4` of the plugin foundation) asked for the
release to ship something to SHOW: the frozen API v1 contract (`PLUGINS.md`) had been
implemented by three rcs and never exercised from the outside. This file is the
acceptance of those tasks — it loads BOTH example files through the REAL discovery path
of `PluginManager` (copy into the isolated `~/.sshmap/plugins/`, then `discover()`), not
through a syntax check, and drives their hooks.

Sections:
  §1 the examples as plugins: the real discovery, the manifests, the recorded hooks, the
     "a plugin never imports the core" rule (a source scan) and the packaging guard (they
     are NOT auto-discovered and NOT part of the installable set);
  §2 `hello`: the palette command (the lenient `(text, callback)` pair) and the node
     context-menu row on both surfaces, with the narrowed node records;
  §3 `disk_monitor`: the `df -hP` parser over fixtures — the header, the worst-of-several
     rule, a mount point with a SPACE, the pseudo-filesystem filter, a truncated line, an
     empty answer, a locale-decimal `Use%`, the 0–100 clamp;
  §4 the plugin's own cache: the atomic write, the merge, the record cap, a corrupt file,
     a foreign document, a write that cannot happen;
  §5 the threshold: 89 → no opinion, 90 → `warn`, the exact detail text, a stale record,
     an unknown node;
  §6 the COLLECTOR: `run_on_nodes` on a fake context (no socket) — the command, a per-node
     failure as a result for that node, the status line, the per-node log, the cache;
  §7 the REPORTER end to end: the real manager + the runner's documented transport seam,
     the merged opinion (the worse of the two), a disabled plugin, and the window's
     "Run on selected servers" pass;
  §8 the release state: the examples add NO i18n key (the pin is the shipped one), `examples/`
     documented, the suite index regenerated.

Run: python tests/test_plugin_examples.py   (from the project root) or python tests/run_all.py
"""
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
                     wait_for as _wait_for)

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
PLUGIN_DIR = PM.user_plugin_dir()
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")

# The rule of the folder (examples/README.md): an example plugin never imports the core —
# a user of an INSTALLED app has no repository checkout on sys.path.
CORE_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(modules|i18n|ui|graphics|models|services|storage|dialogs|third_party|version)\b",
    re.MULTILINE)


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
    """Copy BOTH examples into the sandbox plugin folder — what a user does by hand."""
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    for src in (HELLO_SRC, DISK_SRC):
        shutil.copyfile(src, os.path.join(PLUGIN_DIR, os.path.basename(src)))


def local(stem):
    """The imported module of a folder plugin (the discovery really exec'd the file)."""
    return sys.modules.get(PM.LOCAL_MODULE_PREFIX + stem)


def new_manager():
    manager = PM.PluginManager()
    manager.discover()
    return manager


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


def no_core_imports(source):
    """The rule of examples/README.md, read over the CODE (the prose may name the modules)."""
    return (CORE_IMPORT_RE.findall(source) == []
            and "import sys" not in source
            and "import importlib" not in source
            and "from importlib" not in source
            and "import paramiko" not in source
            and "import socket" not in source)


clear_cfg()
clean_plugins()

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the examples as plugins: the REAL discovery path ==")
# ════════════════════════════════════════════════════════════════════════════

check("both examples exist as plain files in examples/plugins/",
      os.path.isfile(HELLO_SRC) and os.path.isfile(DISK_SRC))
check("examples/README.md explains what the folder is (and that it is not installed)",
      os.path.isfile(os.path.join(EXAMPLES_DIR, "README.md")))

# NOT auto-discovered: the repository folder is not one of the discovery sources, so an
# empty user folder finds nothing even though the files sit in the checkout.
_empty = new_manager()
check("the examples are NOT auto-discovered from the repository (an empty folder = no plugin)",
      _empty.records() == [] and _empty.get("hello") is None
      and _empty.get("disk_monitor") is None,
      str([r.plugin_id for r in _empty.records()]))
check("the folder source is the user folder, not the checkout's examples/",
      PM.user_plugin_dir() != PLUGINS_SRC
      and os.path.basename(PM.user_plugin_dir()) == "plugins")

install_examples()
_manager = new_manager()
hello = _manager.get("hello")
disk = _manager.get("disk_monitor")
check("a copied example is discovered by the real manager (no packaging, no install)",
      hello is not None and disk is not None and hello.ok is True and disk.ok is True,
      str([(r.plugin_id, r.state) for r in _manager.records()]))
check("the records carry the manifests of the files (id, version, api_version, description)",
      hello.version == "1.0" and hello.api_version == PM.API_VERSION
      and "minimal" in hello.description
      and disk.version == "1.0" and "disk usage" in disk.description,
      f"{hello.version}/{hello.api_version} | {disk.version}")
check("both declare their hooks and both are really IMPORTED from the folder",
      hello.hooks == (PM.HOOK_REGISTER_COMMANDS, PM.HOOK_NODE_CONTEXT_MENU)
      and disk.hooks == (PM.HOOK_STATUS_PROBE, PM.HOOK_RUN_ON_NODES),
      f"{hello.hooks} | {disk.hooks}")
check("both are source=folder with the file as the origin",
      hello.source == PM.SOURCE_FOLDER and disk.source == PM.SOURCE_FOLDER
      and hello.origin.endswith("hello.py") and disk.origin.endswith("disk_monitor.py"))
check("the imported modules are the files themselves (the discovery exec'd them)",
      local("hello") is not None and local("disk_monitor") is not None
      and local("hello").MANIFEST["name"] == "hello")

for _path, _name in ((HELLO_SRC, "hello.py"), (DISK_SRC, "disk_monitor.py")):
    _src = read(_path)
    check(f"{_name}: NO import of the core (the rule of examples/README.md)",
          CORE_IMPORT_RE.findall(_src) == [], str(CORE_IMPORT_RE.findall(_src)))
    check(f"{_name}: no sys.path / importlib trick either (an installed app has no checkout)",
          no_core_imports(_src))
    check(f"{_name}: every hook it claims is a callable in the file",
          all(callable(getattr(local(os.path.splitext(_name)[0]), h, None))
              for h in _manager.get(os.path.splitext(_name)[0]).hooks))
_manager.shutdown(500)

# ════════════════════════════════════════════════════════════════════════════
print("== §2 `hello` — the minimal plugin: a palette command + a context-menu row ==")
# ════════════════════════════════════════════════════════════════════════════

hello = _manager.get("hello")
_commands = [cmd for pid, cmd in _manager.plugin_commands() if pid == "hello"]
check("its `register_commands` reaches the palette as ONE command (the lenient pair shape)",
      len(_commands) == 1 and _commands[0].text == "Say hello",
      str([c.text for c in _commands]))
check("the record carries a callback the core can run (the pair's second element)",
      callable(_commands[0].callback))

_seen_status = []
_manager.status_requested.connect(lambda pid, text, ms: _seen_status.append((pid, text)))
_ctx = _manager._context_for(hello)
_manager.call_hook_wrapped("hello", PM.HOOK_REGISTER_COMMANDS, _commands[0].callback, _ctx)
check("running it goes through the wrapper with the plugin's OWN context",
      local("hello").PALETTE_RUNS == ["hello"], str(local("hello").PALETTE_RUNS))
check("the command reports through `ctx.status` (a signal — the window owns the status bar)",
      _seen_status == [("hello", "Hello from the example plugin")], str(_seen_status))

_menu = QMenu()
_asked = _manager.plugin_node_context_menu(_menu, node("n1", "web-1"))
check("its `extend_node_context_menu` appends its row to a node menu",
      "Hello on this server" in menu_texts(_menu) and _asked >= 1, str(menu_texts(_menu)))
_action = next(a for a in _menu.actions() if a.text() == "Hello on this server")
_action.trigger()
check("the row's action receives the node RECORDS the core narrowed (never the scene objects)",
      local("hello").GREETED == [["web-1"]], str(local("hello").GREETED))
_menu2 = QMenu()
_manager.plugin_node_context_menu(_menu2, node("n2", "", "10.0.0.9"))
next(a for a in _menu2.actions() if a.text() == "Hello on this server").trigger()
check("an alias-less node is shown by its id (`n.alias or n.id`)",
      local("hello").GREETED[-1] == ["n2"], str(local("hello").GREETED[-1]))

# ════════════════════════════════════════════════════════════════════════════
print("== §3 `disk_monitor` — the `df -hP` parser (fixtures, no socket) ==")
# ════════════════════════════════════════════════════════════════════════════

disk_mod = local("disk_monitor")
check("the parser is a pure function of the answer (one place, no IO, no SSH library)",
      callable(disk_mod.parse_df) and callable(disk_mod.parse_percent)
      and no_core_imports(read(DISK_SRC)))

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
      and no_core_imports(read(DISK_SRC)))
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
    # The regression the dogfooding found (fixed in v1.4): `ctx.run_command` called from a
    # plugin's WORKER thread. The receiver context of a signal connected to a plain Python
    # callable is the thread that calls `connect()` (AGENTS.md §7 gotcha #20), so a runner
    # built inside a `run_on_nodes` worker used to post its results into a thread with no
    # event loop — and lose them silently. Calling the service from a bare `threading.Thread`
    # is the smallest reproduction of that path.
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
    check("`run_on_nodes` starts the example plugin on the registry's nodes",
          _started == 1, str(_started))
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
app.processEvents()
check("the window discovers the example plugin on startup",
      _win._plugin_manager.get("disk_monitor") is not None
      and _win._plugin_manager.get("disk_monitor").ok)
_win._command_palette._collect_commands()
check("`hello` really feeds the Ctrl+K palette of the WINDOW (the author's text verbatim)",
      "Say hello" in [c[0] for c in _win._command_palette._commands]
      and [c[1] for c in _win._command_palette._commands
           if c[0] == "Say hello"] == ["plugin"],
      str([c[0] for c in _win._command_palette._commands][-5:]))
check("its `run_on_nodes` enables the menu item (an empty cache does not change that)",
      _win.act_plugins_run.isEnabled() is True)
PR.run_command_over_ssh = lambda node, command, timeout, credentials: PR.PluginRunResult(
    node=node, exit_code=0, output=DF_TABLE)
try:
    _win.act_plugins_run.trigger()
    check("the round reports through the plugin's own status line",
          wait_until(lambda: _win.statusBar().currentMessage().startswith("disk: ")) is not False,
          _win.statusBar().currentMessage())
    check("the status line is the collector's summary (1 node, 1 over the threshold)",
          _win.statusBar().currentMessage() == "disk: 1 node(s), 1 over the threshold",
          _win.statusBar().currentMessage())
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
      not any("Say hello" == value or "Hello on this server" == value
              for data in _langs.values() for value in data.values()))
check("the parity pin is the shipped one (the examples contribute nothing — the releases "
      "move the pin, not this file; v1.5.7 left it at 737)",
      EXPECTED_I18N_KEYS == 737 and all(len(translation_keys(d)) == EXPECTED_I18N_KEYS
                                         for d in _langs.values()),
      str({c: len(translation_keys(d)) for c, d in _langs.items()}))
check_i18n_parity(_langs)
check_i18n_format(_langs)
check("the plugin strings of both examples stay outside the parity policy",
      "disk: " not in json.dumps(_langs["en"]) and "threshold 90" not in json.dumps(_langs["en"]))
check("the release is the version this file ships with (the pin quotes the shipped one)",
      EXPECTED_APP_VERSION == "1.5.7.1", EXPECTED_APP_VERSION)
check_release_state(ROOT)
check("the example file for these tasks is described in examples/README.md",
      "disk_monitor" in read(os.path.join(EXAMPLES_DIR, "README.md"))
      and "hello" in read(os.path.join(EXAMPLES_DIR, "README.md")))
check("the suite map lists this topical file (tests/INDEX.md regenerated)",
      "test_plugin_examples.py" in read(os.path.join(ROOT, "tests", "INDEX.md")))

clean_plugins()
clear_cfg()
finish()
