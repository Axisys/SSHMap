"""v1.5.3 — freshness everywhere: the collected facts get an age, and a red card answers "why".

The topical gate of the THIRD patch ON the released 1.5, and the file that pins the three
halves of the release:

  §1 the AGE of the collected facts (ROADMAP task 1): the optional `info_collected_at`
     field of `ServerData` (write-only-when-set, a missing key is a default, junk is
     refused), the "collected N ago" line and the idle-tone mark on the info plaque, the
     INDEPENDENCE of the info freshness from the status freshness, and the rule that the
     mark never changes a stored value;
  §2 the batch collection (ROADMAP task 2): the bounded queue with a parallelism CAP, the
     per-node guard (no node collected twice in parallel), one failure never stopping the
     rest, `cancel()` dropping everything not yet started, the pure summary helpers and the
     ONE window entry point ("gather information for the selection / all");
  §3 the reachability report (ROADMAP task 3): DNS → TCP → SSH banner → ICMP ping in the
     declared order, the FIRST failing step named in its own words (a DNS-only failure, a
     refused port, a silent port and a live SSH host each get their OWN sentence), the
     ICMP evidence, the tooltip/status-bar/activity routing, and the untouched STATUS;
  §4 the release state: the version/pins, the registry pair, the schema decision of task 1
     (`VERSION_FORMAT` stays 0.9) and the "no new contract" audit (no dependency, no config
     key of the hub, no new colour).

Everything runs offscreen and hermetic: the network seams of the report and the collector
factory of the batch are INJECTED, so no socket is opened and no SSH session is started.

Run: python tests/test_freshness.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import re
import sys
import time

from _common import (bootstrap, check, finish, load_i18n_langs, wait_for,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, check_i18n_parity,
                     check_i18n_format, check_release_state)

ROOT, WORK = bootstrap()  # HOME isolation + offscreen Qt + sys.path (BEFORE any app import)

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
from i18n import t  # noqa: E402
from models.server import (ServerData, server_data_from_dict, server_data_to_dict,  # noqa: E402
                           info_collected_epoch)
import version as _version  # noqa: E402

LANGS = load_i18n_langs(ROOT)
NOW = time.time()

NEW_KEYS = [
    # the age of the collected facts (task 1)
    "node.info.collected_now", "node.info.collected_min",
    "node.info.collected_hours", "node.info.collected_days",
    # the batch collection (task 2)
    "status.info_batch_progress", "status.info_batch_done",
    "status.info_batch_failed", "status.info_batch_none",
    # the reachability report (task 3)
    "ctx.diagnose", "status.diagnose_running", "diagnose.ok", "diagnose.dns_failed",
    "diagnose.dns_timeout", "diagnose.tcp_refused", "diagnose.tcp_timeout",
    "diagnose.tcp_failed", "diagnose.banner_silent", "diagnose.banner_foreign",
    "diagnose.ping_ok", "diagnose.ping_failed",
]

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the age of the collected facts (task 1) ==")
# ════════════════════════════════════════════════════════════════════════════

# ── the model: an OPTIONAL field with a refused value ────────────────────────
check("§1 ServerData carries the optional collection date (0.0 — not dated)",
      ServerData(id="x", alias="a", host="h", user="u").info_collected_at == 0.0)

_old = server_data_from_dict({"id": "old1", "alias": "A", "host": "h", "user": "u"})
check("§1 a project file WITHOUT the key loads unchanged and unmarked",
      _old.info_collected_at == 0.0 and "info_collected_at" not in
      server_data_to_dict(_old),
      str(server_data_to_dict(_old)))

_dated = server_data_from_dict({"id": "d1", "alias": "A", "host": "h", "user": "u",
                                "info_collected_at": 1700000000.5})
check("§1 a dated project file round-trips the timestamp",
      _dated.info_collected_at == 1700000000.5
      and server_data_to_dict(_dated)["info_collected_at"] == 1700000000.5)
check("§1 the date is never stored beside the password (nothing else changed)",
      set(server_data_to_dict(_dated)) == set(server_data_to_dict(_old)) | {"info_collected_at"}
      and "password" not in server_data_to_dict(_dated))

for _junk, _why in ((None, "an explicit null"), ("", "an empty string"),
                    ("abc", "a non-numeric string"), (float("nan"), "NaN"),
                    (float("inf"), "infinity"), (-5, "a negative epoch")):
    check(f"§1 info_collected_epoch refuses {_why}",
          info_collected_epoch(_junk) == 0.0, repr(_junk))
check("§1 info_collected_epoch accepts a numeric string (a hand-edited file)",
      info_collected_epoch("1700000000") == 1700000000.0)
_junk_file = server_data_from_dict({"id": "j1", "alias": "A", "host": "h", "user": "u",
                                    "info_collected_at": "not a date"})
check("§1 a junk value loads as 'not dated' (the load never breaks)",
      _junk_file.info_collected_at == 0.0)

# ── the card: the line, the mark, the untouched value ───────────────────────
from graphics.server_node import ServerNode  # noqa: E402

_card = ServerNode(ServerData(id="c1", alias="web-1", host="192.0.2.10", user="root",
                              os_name="Ubuntu 24.04 LTS", cpu="4 core", ram="8 gb"))
check("§1 a card without a date shows no age line",
      _card.info_freshness_text(now=NOW) == "" and _card.is_info_stale is False)
check("§1 a card without a date paints the info plaque in the LABEL tone",
      _card._info.defaultTextColor().name() == _card.COLOR_LABEL.name(),
      _card._info.defaultTextColor().name())

check("§1 a fresh collection reads 'just now'",
      _card.set_info_collected_at(NOW - 5) is False
      and _card.info_freshness_text(now=NOW) == t("node.info.collected_now"),
      _card.info_freshness_text(now=NOW))
check("§1 minutes are named in minutes",
      _card.info_freshness_text(now=NOW + 5 * 60) == t("node.info.collected_min", minutes=5),
      _card.info_freshness_text(now=NOW + 5 * 60))
check("§1 hours are named in hours",
      _card.info_freshness_text(now=NOW + 5 * 3600) == t("node.info.collected_hours", hours=5),
      _card.info_freshness_text(now=NOW + 5 * 3600))
check("§1 days are named in days",
      _card.info_freshness_text(now=NOW + 5 * 86400) == t("node.info.collected_days", days=5),
      _card.info_freshness_text(now=NOW + 5 * 86400))

_before = (_card.data.os_name, _card.data.cpu, _card.data.ram, _card.data.disk)
_card.set_info_collected_at(NOW + 3 * 86400)          # the fact is "3 days old" now
check("§1 an old fact keeps its VALUE — only the label moves",
      (_card.data.os_name, _card.data.cpu, _card.data.ram, _card.data.disk) == _before,
      str(_before))

_card.set_info_collected_at(NOW)
check("§1 the mark appears only once the threshold has passed",
      _card.refresh_info_freshness(now=NOW + ServerNode.INFO_STALE_AFTER_SEC - 60) is False
      and _card.is_info_stale is False)
check("§1 ...and the threshold is crossed a minute later",
      _card.refresh_info_freshness(now=NOW + ServerNode.INFO_STALE_AFTER_SEC + 60) is True
      and _card.is_info_stale is True)
check("§1 the stale mark is the IDLE tone (no new colour is invented)",
      _card._info.defaultTextColor().name() == _card.COLOR_DOT_IDLE.name(),
      _card._info.defaultTextColor().name())
check("§1 the stale facts keep their text (the plaque still says what was measured)",
      _card._info.toPlainText() != "" and _card.info_freshness_text(
          now=NOW + 8 * 86400) == t("node.info.collected_days", days=8))
check("§1 the age of the facts reaches the plaque tooltip",
      t("node.info.collected_now") in _card._info.toolTip()
      or t("node.info.collected_days", days=8) in _card._info.toolTip(),
      _card._info.toolTip())
check("§1 a refused date clears the mark again (never dated → never stale)",
      _card.set_info_collected_at(0) is True and _card.is_info_stale is False
      and _card.info_freshness_text() == "")

# ── the INFO freshness is INDEPENDENT of the status freshness ───────────────
_card.set_info_collected_at(NOW)
_card.set_status("online")
_card.set_checked_at(NOW - 10 * 3600, stale_after=90.0)
check("§1 the STATUS can be stale while the collected facts are fresh",
      _card.is_stale is True and _card.is_info_stale is False,
      f"status_stale={_card.is_stale} info_stale={_card.is_info_stale}")
_card.set_info_collected_at(NOW - 30 * 86400)
_card.set_checked_at(NOW, stale_after=90.0)
_card.refresh_freshness(now=NOW)
check("§1 ...and the other way round (old facts, fresh status)",
      _card.is_stale is False and _card.is_info_stale is True,
      f"status_stale={_card.is_stale} info_stale={_card.is_info_stale}")
check("§1 the INFO mark never changes the STATUS (the status is untouched)",
      _card.status == "online" and _card.status_checked_at == NOW)


# ── the window writes the date WITH the values ──────────────────────────────
from ui.main_window import MainWindow  # noqa: E402

_win = MainWindow()
_win._autosave_timer.stop()
_node = _win.scene.add_server(ServerData(id="fw1", alias="fw-1", host="192.0.2.20", user="root"))
_win._apply_info_result("fw1", {"os_name": "Debian GNU/Linux 12", "cpu_cores": "2",
                                "cpu_model": "Xeon", "ram_gb": "4 gb", "disk_gb": "40 gb"})
check("§1 the window writes the values AND the date in ONE path",
      _node.data.os_name == "Debian GNU/Linux 12" and _node.data.cpu == "2 core"
      and abs(_node.data.info_collected_at - time.time()) < 5.0,
      f"{_node.data.os_name} / {_node.data.info_collected_at}")
check("§1 ...and the card carries the age immediately",
      _node.info_freshness_text() == t("node.info.collected_now")
      and _node.info_collected_at == _node.data.info_collected_at,
      _node.info_freshness_text())
check("§1 the freshness tick is idempotent and never changes a value",
      _win._apply_node_info_freshness(_node) is False
      and _node.data.os_name == "Debian GNU/Linux 12")
_node.data.info_collected_at = time.time() - 30 * 86400
check("§1 the tick moves an aged fact to the mark (through the DATA, never a checker)",
      _win._apply_node_info_freshness(_node) is True and _node.is_info_stale is True
      and _node.data.os_name == "Debian GNU/Linux 12")
check("§1 a deleted node cannot be collected into (the write is guarded)",
      _win._apply_info_result("nope", {"os_name": "X"}) is False)
_dated_save = server_data_to_dict(_node.data)
check("§1 the saved project carries the date (write-only-when-set)",
      _dated_save.get("info_collected_at") is not None
      and _dated_save["info_collected_at"] > 0, str(_dated_save.get("info_collected_at")))

for _key in ("node.info.collected_now", "node.info.collected_min",
             "node.info.collected_hours", "node.info.collected_days"):
    check(f"§1 i18n/en carries {_key}", _key in LANGS["en"])


# ════════════════════════════════════════════════════════════════════════════
print("== §2 collecting for many nodes at once (task 2) ==")
# ════════════════════════════════════════════════════════════════════════════

from services import info_batch as IB  # noqa: E402
from services.info_batch import InfoBatch  # noqa: E402

check("§2 the batch log line names the collected / total pair (PURE)",
      IB.batch_log_line(5, 5) == "Info batch: 5 of 5 collected", IB.batch_log_line(5, 5))
check("§2 ...and NAMES the failures with their reason",
      IB.batch_log_line(3, 5, [("a", "db-1", "auth failed"), ("b", "web-2", "timed out")])
      == "Info batch: 3 of 5 collected — failed: db-1 (auth failed), web-2 (timed out)",
      IB.batch_log_line(3, 5, [("a", "db-1", "auth failed"), ("b", "web-2", "timed out")]))
check("§2 ...and reports a node that was already running as skipped",
      "1 already running" in IB.batch_log_line(2, 4, [("a", "db-1", "x")], skipped=1))
check("§2 a failure without a message still names the node",
      IB.batch_log_line(0, 1, [("a", "db-1", "")]) == "Info batch: 0 of 1 collected — failed: db-1")
check("§2 the failed-alias list is bounded",
      IB.failed_alias_list([("a", "x", ""), ("b", "y", ""), ("c", "z", ""), ("d", "w", "")])
      == "x, y, z, +1 more",
      IB.failed_alias_list([("a", "x", ""), ("b", "y", ""), ("c", "z", ""), ("d", "w", "")]))
check("§2 ...and is empty for a clean batch", IB.failed_alias_list([]) == "")
check("§2 the default cap is the declared one and the config key clamps",
      IB.DEFAULT_MAX_PARALLEL == 4 and IB.MAX_PARALLEL_LIMIT == 16
      and IB.get_batch_settings()["max_parallel"] == 4,
      str(IB.get_batch_settings()))
_dir = os.path.join(os.path.expanduser("~"), ".sshmap")
os.makedirs(_dir, exist_ok=True)
with open(os.path.join(_dir, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"info_max_parallel": 999}, f)
check("§2 a hand-edited cap is clamped, not obeyed",
      IB.get_batch_settings()["max_parallel"] == IB.MAX_PARALLEL_LIMIT,
      str(IB.get_batch_settings()))
with open(os.path.join(_dir, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"info_max_parallel": "junk"}, f)
check("§2 a broken cap falls back to the default",
      IB.get_batch_settings()["max_parallel"] == IB.DEFAULT_MAX_PARALLEL)
try:
    os.remove(os.path.join(_dir, "config.json"))
except OSError:
    pass


class _FakeCollector(QObject):
    """A collector double: it emits IN the calling thread, so the batch is deterministic."""

    info_ready = Signal(str, dict)
    info_failed = Signal(str, str)
    finished = Signal()

    registry: list = []
    active = 0
    peak = 0
    plans: dict = {}

    def __init__(self, data, password="", parent=None):
        super().__init__(parent)
        self.data = data
        self._running = False
        _FakeCollector.registry.append(self)

    def start(self):
        _FakeCollector.active += 1
        _FakeCollector.peak = max(_FakeCollector.peak, _FakeCollector.active)
        self._running = True
        plan = _FakeCollector.plans.get(self.data.id, "ok")
        if plan != "hold":
            self._finish(plan)

    def _finish(self, plan):
        self._running = False
        if plan == "fail":
            self.info_failed.emit(self.data.id, "auth failed")
        else:
            self.info_ready.emit(self.data.id, {"os_name": "Ubuntu 24.04 LTS",
                                                "cpu_cores": "4", "ram_gb": "8 gb"})
        _FakeCollector.active -= 1
        self.finished.emit()

    def release(self, plan="ok"):
        if self._running:
            self._finish(plan)

    def isRunning(self):
        return self._running

    def stop(self):
        self.release("ok")


def _reset_fakes():
    _FakeCollector.registry = []
    _FakeCollector.active = 0
    _FakeCollector.peak = 0
    _FakeCollector.plans = {}


def _data(sid, alias=None):
    return ServerData(id=sid, alias=alias or sid, host="192.0.2.1", user="root")


# ── the queue: the cap, the guard, one failure, cancel ──────────────────────
_reset_fakes()
_FakeCollector.plans = {f"s{i}": "hold" for i in range(5)}
_seen = []
_finished = []
_batch = InfoBatch(collector_factory=lambda d: _FakeCollector(d), max_parallel=2)
_batch.node_ready.connect(lambda sid, info: _seen.append(sid))
_batch.node_failed.connect(lambda sid, alias, err: _seen.append(sid))
_batch.finished.connect(lambda ok, fails, canc: _finished.append((ok, len(fails), canc)))
_accepted = _batch.start([(f"s{i}", f"alias{i}", _data(f"s{i}")) for i in range(5)])
check("§2 the queue accepts every node and starts no more than the cap",
      _accepted == 5 and _FakeCollector.peak == 2 and _batch.running_count == 2,
      f"accepted={_accepted} peak={_FakeCollector.peak} running={_batch.running_count}")
check("§2 the progress line counts the ACCEPTED nodes as its denominator",
      _batch.total == 5 and _batch.done == 0)
_FakeCollector.registry[0].release("ok")
check("§2 a settled node starts the next one (the queue drains under the cap)",
      _batch.running_count == 2 and _FakeCollector.peak == 2 and _batch.done == 1,
      f"running={_batch.running_count} peak={_FakeCollector.peak} done={_batch.done}")
for _collector in list(_FakeCollector.registry):
    _collector.release("ok")
for _round in range(10):                      # releasing one starts the next (the cap)
    _pending = [c for c in _FakeCollector.registry if c.isRunning()]
    if not _pending:
        break
    for _collector in _pending:
        _collector.release("ok")
check("§2 the batch finishes and reports the summary once",
      _batch.is_running is False and _finished == [(5, 0, 0)] and sorted(_seen) ==
      [f"s{i}" for i in range(5)],
      f"{_finished} {sorted(_seen)}")

_reset_fakes()
_batch = InfoBatch(collector_factory=lambda d: _FakeCollector(d), max_parallel=2)
_seen, _failed, _finished = [], [], []
_batch.node_ready.connect(lambda sid, info: _seen.append(sid))
_batch.node_failed.connect(lambda sid, alias, err: _failed.append(sid))
_batch.finished.connect(lambda ok, fails, canc: _finished.append((ok, len(fails), canc)))
_FakeCollector.plans = {"s1": "fail"}
_batch.start([(f"s{i}", f"alias{i}", _data(f"s{i}")) for i in range(3)])
check("§2 one node's failure never stops the rest",
      sorted(_seen) == ["s0", "s2"] and _failed == ["s1"]
      and _finished == [(2, 1, 0)],
      f"ok={sorted(_seen)} failed={_failed} summary={_finished}")

_reset_fakes()
_busy = {"s0"}
_batch = InfoBatch(collector_factory=lambda d: _FakeCollector(d), max_parallel=2,
                   is_busy=lambda sid: sid in _busy)
_accepted = _batch.start([(f"s{i}", f"alias{i}", _data(f"s{i}")) for i in range(3)])
check("§2 a node already being collected is SKIPPED (never collected twice in parallel)",
      _accepted == 2 and "s0" not in [c.data.id for c in _FakeCollector.registry],
      f"accepted={_accepted} {[c.data.id for c in _FakeCollector.registry]}")
check("§2 the SAME node twice in one call is collected once",
      InfoBatch(collector_factory=lambda d: _FakeCollector(d)).start(
          [("dup", "dup", _data("dup")), ("dup", "dup", _data("dup"))]) == 1)
_check_session = InfoBatch(collector_factory=lambda d: _FakeCollector(d))
_check_session.start([("a1", "a1", _data("a1"))])
check("§2 a NEW batch session does not inherit the previous run's 'already seen' set",
      _check_session.start([("a1", "a1", _data("a1"))]) == 1)

_reset_fakes()
_FakeCollector.plans = {f"s{i}": "hold" for i in range(4)}
_batch = InfoBatch(collector_factory=lambda d: _FakeCollector(d), max_parallel=2)
_finished = []
_batch.finished.connect(lambda ok, fails, canc: _finished.append((ok, len(fails), canc)))
_batch.start([(f"s{i}", f"alias{i}", _data(f"s{i}")) for i in range(4)])
_dropped = _batch.cancel()
check("§2 cancel drops everything not yet started",
      _dropped == 2 and _batch.running_count == 2 and _batch.is_running is True,
      f"dropped={_dropped} running={_batch.running_count}")
for _collector in list(_FakeCollector.registry):
    _collector.release("ok")
check("§2 the running collectors finish and the batch closes honestly",
      _finished == [(2, 0, 2)] and _batch.is_running is False,
      str(_finished))

_reset_fakes()
_batch = InfoBatch(collector_factory=lambda d: (_ for _ in ()).throw(RuntimeError("no ssh")),
                   max_parallel=2)
_finished = []
_batch.finished.connect(lambda ok, fails, canc: _finished.append((ok, len(fails), canc)))
_batch.start([("s1", "alias1", _data("s1"))])
check("§2 a collector that cannot even be built is that node's failure",
      _finished == [(0, 1, 0)], str(_finished))

# ── the window half: the scope, the actions, the registry ───────────────────
_nodes = [_win.scene.add_server(ServerData(id=f"sc{i}", alias=f"sc-{i}",
                                           host=f"192.0.2.{30 + i}", user="root"))
          for i in range(3)]
_win.scene.clearSelection()
app.processEvents()
check("§2 with nothing selected the action covers the WHOLE map (the 'all' half)",
      [n.data.id for n in _win._collect_info_scope()] ==
      [n.data.id for n in _win.scene.nodes()] and len(_win._collect_info_scope()) >= 4,
      str([n.data.alias for n in _win._collect_info_scope()]))
_nodes[0].setSelected(True)
app.processEvents()
check("§2 a single selected node means that node",
      [n.data.id for n in _win._collect_info_scope()] == ["sc0"])
_nodes[1].setSelected(True)
app.processEvents()
check("§2 a multi-selection means the selection (not the map)",
      sorted(n.data.id for n in _win._collect_info_scope()) == ["sc0", "sc1"])
_win.scene.clearSelection()
check("§2 a context-menu call means the clicked node",
      [n.data.id for n in _win._collect_info_scope(_nodes[2])] == ["sc2"])

from ui import hotkey_registry as HR  # noqa: E402
import ui.sidebar as SB  # noqa: E402

check("§2 the gather action is a registry action with an EMPTY default",
      "node.collect_info" in HR.action_ids()
      and HR.default_sequence("node.collect_info") == ""
      and HR.HOTKEY_ACTIONS["node.collect_info"]["label"] == "ctx.collect_info")
check("§2 the gather action has a permanent Edit-menu item (the hotkey target rule)",
      any(a.text().replace("&", "") == t("ctx.collect_info")
          for a in _win.findChildren(QAction))
      and _win._hotkey_targets.get("node.collect_info"))
check("§2 the sidebar row menu carries the gather row",
      any(e is not None and e[0] == "collect_info" for e in SB.CONTEXT_MENU_ITEMS)
      and "collect_info" in _win.sidebar._actions)
_src_map = open(os.path.join(ROOT, "graphics", "map_view.py"), encoding="utf-8").read()
check("§2 the map's node context menu carries it too (ONE method, two surfaces)",
      'ctx.collect_info' in _src_map and "_collect_info_many" in _src_map)

# the window's batch uses the INJECTED collector class (the service-module seam the
# single-node path already honours: `SIC.SystemInfoCollector = Fake`) and the guard
import services.system_info_collector as SIC  # noqa: E402

_reset_fakes()
_FakeCollector.plans = {"sc0": "hold", "sc1": "hold"}
_orig_collector_cls = SIC.SystemInfoCollector
SIC.SystemInfoCollector = _FakeCollector
try:
    _win._info_batch = None          # a fresh batch with the fake factory
    _win._info_collectors = {}
    _accepted = _win._collect_info_many(nodes=[_win.scene.get_node("sc0"),
                                              _win.scene.get_node("sc1")])
    check("§2 the window starts one batch for the selection (off the GUI thread)",
          _accepted == 2 and _win._info_batch is not None
          and [c.data.id for c in _FakeCollector.registry] == ["sc0", "sc1"],
          f"accepted={_accepted} {[c.data.id for c in _FakeCollector.registry]}")
    check("§2 every collector is registered in the ONE per-node registry",
          _win._info_is_busy("sc0") is True)
    check("§2 a second gather for the same node is skipped, not doubled",
          _win._collect_info_many(nodes=[_win.scene.get_node("sc0")]) == 0
          and len(_FakeCollector.registry) == 2,
          str(len(_FakeCollector.registry)))
    check("§2 the per-node guard answers for an unknown id too",
          _win._info_is_busy("nope") is False)
    # the collected values land on the card, dated
    _FakeCollector.registry[0].release("ok")
    _node0 = _win.scene.get_node("sc0")
    check("§2 a batch result writes the values and the date through the same path",
          _node0.data.os_name == "Ubuntu 24.04 LTS"
          and _node0.data.info_collected_at > 0
          and _node0.info_freshness_text() == t("node.info.collected_now"),
          f"{_node0.data.os_name} {_node0.info_freshness_text()}")
    check("§2 a finished collector LEAVES the registry (the guard cannot stick on)",
          _win._info_is_busy("sc0") is False, str(sorted(_win._info_collectors)))
    _win._shutdown_info_batch()
    check("§2 the shutdown cancels the queue and never raises",
          _win._info_batch.is_running is False)
finally:
    SIC.SystemInfoCollector = _orig_collector_cls


# ════════════════════════════════════════════════════════════════════════════
print("== §3 why is it red? — the reachability report (task 3) ==")
# ════════════════════════════════════════════════════════════════════════════

from services import diagnostics as DG  # noqa: E402

_src_diag = open(os.path.join(ROOT, "services", "diagnostics.py"), encoding="utf-8").read()
_diag_imports = set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", _src_diag, re.M))
check("§3 the report keeps the probe's 3 s budget",
      DG.REPORT_TIMEOUT_S == 3.0
      and __import__("services.status_checker", fromlist=["x"]).PROBE_TIMEOUT_S == 3.0,
      f"{DG.REPORT_TIMEOUT_S}")
check("§3 no new dependency: the module imports the standard library, Qt and the project",
      _diag_imports <= {"platform", "socket", "subprocess", "threading", "time",
                        "dataclasses", "typing", "PySide6", "i18n", "modules", "services",
                        "models"},
      str(sorted(_diag_imports)))
check("§3 the steps are DECLARED in the order the report runs them",
      DG.REPORT_STEP_ORDER == ("dns", "tcp", "banner", "ping"), str(DG.REPORT_STEP_ORDER))
check("§3 every verdict maps to the step it belongs to",
      all(DG.KIND_STEP[k] in ("", "dns", "tcp", "banner") for k in DG.REPORT_KINDS)
      and DG.KIND_STEP[DG.KIND_DNS_FAILED] == "dns"
      and DG.KIND_STEP[DG.KIND_TCP_REFUSED] == "tcp"
      and DG.KIND_STEP[DG.KIND_BANNER_SILENT] == "banner"
      and DG.KIND_STEP[DG.KIND_OK] == "")


def _fake_resolve(ip="192.0.2.10", error=""):
    return lambda host, timeout: (ip, error)


class _FakeSock:
    def __init__(self, banner):
        self._banner = banner
        self.closed = False

    def recv(self, size):
        if isinstance(self._banner, Exception):
            raise self._banner
        return self._banner

    def close(self):
        self.closed = True


def _fake_connect(banner=b"SSH-2.0-OpenSSH_9.6\r\n", error=""):
    def _connect(host, port, timeout):
        if error:
            return None, error
        return _FakeSock(banner), ""
    return _connect


#: Every step that runs is RECORDED, so "the first failing step stops the chain" and
#: "ICMP runs only after a failed TCP" are asserted on the calls, not on the wording.
_steps_called = []


def _record_connect(inner):
    def _connect(host, port, timeout):
        _steps_called.append("tcp")
        return inner(host, port, timeout)
    return _connect


def _record_ping(answer=False):
    def _ping(host, timeout):
        _steps_called.append("ping")
        return answer
    return _ping


def _record_resolve(ip, error=""):
    def _resolve(host, timeout):
        _steps_called.append("dns")
        return ip, error
    return _resolve


# ── the four acceptance scenarios ──────────────────────────────────────────
_steps_called.clear()
_ok_sock = _FakeSock(b"SSH-2.0-OpenSSH_9.6\r\n")
_dns = DG.diagnose_reachability("web-1.example", 22,
                                resolver=_record_resolve("", "bad name"),
                                connector=_record_connect(_fake_connect()),
                                pinger=_record_ping(False))
check("§3 a DNS-only failure is its OWN verdict (step 'dns')",
      _dns.kind == DG.KIND_DNS_FAILED and _dns.step == "dns" and _dns.ok is False
      and "bad name" in _dns.detail, f"{_dns.kind} {_dns.detail}")
check("§3 a failing DNS stops the chain BEFORE TCP and ICMP (the first failure is the answer)",
      _steps_called == ["dns"], str(_steps_called))
_dns_to = DG.diagnose_reachability("web-1.example", 22,
                                   resolver=_record_resolve("", "timeout"),
                                   connector=_record_connect(_fake_connect()),
                                   pinger=_record_ping(False))
check("§3 a hung resolver is a DIFFERENT verdict (dns_timeout)",
      _dns_to.kind == DG.KIND_DNS_TIMEOUT and _dns_to.kind != _dns.kind)

_steps_called.clear()
_refused = DG.diagnose_reachability("web-2.example", 22, resolver=_record_resolve("192.0.2.10"),
                                    connector=_record_connect(_fake_connect(error="Connection refused")),
                                    pinger=_record_ping(False))
check("§3 a closed port is named as refused (and the host is pinged for evidence)",
      _refused.kind == DG.KIND_TCP_REFUSED and _refused.step == "tcp"
      and _refused.ip == "192.0.2.10" and _refused.ping == "failed",
      f"{_refused.kind} {_refused.ping}")
check("§3 ...and the ICMP step really ran (only the TCP failure asks it)",
      _steps_called == ["dns", "tcp", "ping"], str(_steps_called))
_filtered = DG.diagnose_reachability("web-3.example", 22, resolver=_record_resolve("192.0.2.10"),
                                     connector=_record_connect(_fake_connect(error="timed out")),
                                     pinger=_record_ping(True))
check("§3 a silently dropped port is a TIMEOUT, and a live ICMP answers the 'firewall?' question",
      _filtered.kind == DG.KIND_TCP_TIMEOUT and _filtered.ping == "ok"
      and _filtered.kind != _refused.kind, f"{_filtered.kind} {_filtered.ping}")
_steps_called.clear()
_silent = DG.diagnose_reachability("web-4.example", 22, resolver=_record_resolve("192.0.2.10"),
                                   connector=_record_connect(_fake_connect(banner=b"")),
                                   pinger=_record_ping(False))
check("§3 a port that accepts but sends nothing is 'no SSH banner'",
      _silent.kind == DG.KIND_BANNER_SILENT and _silent.step == "banner")
check("§3 a live TCP connection does not need the ICMP step (the host already answered)",
      _steps_called == ["dns", "tcp"], str(_steps_called))
_silent_to = DG.diagnose_reachability("web-4.example", 22, resolver=_fake_resolve(),
                                      connector=_fake_connect(banner=TimeoutError("timed out")),
                                      pinger=_record_ping(False))
check("§3 a silent read and an empty read are the SAME verdict (no banner)",
      _silent_to.kind == DG.KIND_BANNER_SILENT)
_foreign = DG.diagnose_reachability("web-5.example", 8080, resolver=_fake_resolve(),
                                    connector=_fake_connect(banner=b"HTTP/1.1 400 Bad Request"),
                                    pinger=_record_ping(False))
check("§3 a foreign service is reported WITH what it said",
      _foreign.kind == DG.KIND_BANNER_FOREIGN and "HTTP/1.1" in _foreign.detail,
      _foreign.detail)
_diag_sock = _FakeSock(b"SSH-2.0-OpenSSH_9.6\r\n")
_live = DG.diagnose_reachability("web-6.example", 22, resolver=_fake_resolve(),
                                 connector=lambda h, p, t: (_diag_sock, ""),
                                 pinger=_record_ping(False))
check("§3 a live SSH host is 'ok' and quotes the banner",
      _live.kind == DG.KIND_OK and _live.ok is True and _live.step == ""
      and _live.detail.startswith("SSH-2.0"), _live.detail)
check("§3 a probe socket is CLOSED on the way out (the OK path included)",
      _diag_sock.closed is True)
check("§3 the four acceptance scenarios are FOUR different verdicts",
      len({_dns.kind, _refused.kind, _silent.kind, _live.kind}) == 4,
      str({_dns.kind, _refused.kind, _silent.kind, _live.kind}))
check("§3 every verdict has its OWN sentence in the language files",
      len({LANGS["en"][f"diagnose.{k}"] for k in DG.REPORT_KINDS}) == len(DG.REPORT_KINDS)
      and all(f"diagnose.{k}" in LANGS["en"] for k in DG.REPORT_KINDS),
      str(sorted(DG.REPORT_KINDS)))

# ── the sentence composition (the window owns the words) ───────────────────
_parts_dns = DG.report_parts(_dns)
_parts_live = DG.report_parts(_live)
check("§3 report_parts names the verdict key and its params",
      _parts_dns[0][0] == "diagnose.dns_failed" and _parts_dns[0][1]["host"] == "web-1.example"
      and _parts_live[0][0] == "diagnose.ok"
      and _parts_live[0][1]["banner"].startswith("SSH-2.0"),
      str(_parts_live))
check("§3 the ICMP evidence is a SECOND line, never the headline",
      DG.report_parts(_refused)[1] == ("diagnose.ping_failed", {"host": "web-2.example"})
      and DG.report_parts(_filtered)[1][0] == "diagnose.ping_ok"
      and len(DG.report_parts(_live)) == 1)
_sentence_dns = t(_parts_dns[0][0], **_parts_dns[0][1])
_sentence_refused = t(*DG.report_parts(_refused)[0][:1], **DG.report_parts(_refused)[0][1])
_sentence_silent = t(DG.report_parts(_silent)[0][0], **DG.report_parts(_silent)[0][1])
_sentence_live = t(_parts_live[0][0], **_parts_live[0][1])
check("§3 ...so four scenarios read as four different sentences",
      len({_sentence_dns, _sentence_refused, _sentence_silent, _sentence_live}) == 4,
      str([_sentence_dns, _sentence_refused, _sentence_silent, _sentence_live]))

# ── the ping guard and the thread wrapper ──────────────────────────────────
check("§3 ping_once refuses an argument-shaped host WITHOUT launching a process",
      DG.ping_once("-oops") is False)
_thread = DG.ReachabilityThread("diag-1", "192.0.2.99", 22,
                                resolver=_fake_resolve(), connector=_fake_connect(),
                                pinger=_record_ping(False))
_got = []
_thread.report_ready.connect(lambda sid, report: _got.append((sid, report)))
_thread.start()
check("§3 the report runs on a QThread and delivers (server_id, report)",
      wait_for(lambda: bool(_got), timeout_ms=5000)
      and _got[0][0] == "diag-1" and _got[0][1].kind == DG.KIND_OK, str(_got))

# ── the window routing: tooltip + status bar + the untouched status ────────
_diag_node = _win.scene.get_node("sc0")
_diag_node.set_status("offline")
_win._on_diagnose_report("sc0", _refused)
check("§3 the report reaches the CARD TOOLTIP",
      _diag_node.status_report == _win._diagnose_report_text(_refused)
      and t("diagnose.tcp_refused", ip="192.0.2.10", host="web-2.example", port=22)
      in _diag_node.toolTip(),
      _diag_node.toolTip())
check("§3 ...and the STATUS of the card is untouched (a report explains, it does not decide)",
      _diag_node.status == "offline", _diag_node.status)
check("§3 ...and the sentence reaches the status bar (the activity tap follows it)",
      _win.statusBar().currentMessage() == _win._diagnose_report_text(_refused).replace("\n", " — "),
      _win.statusBar().currentMessage())
_diag_node.set_status("online")
check("§3 a NEW probe result drops the old explanation (it described another state)",
      _diag_node.status_report == "" and t("diagnose.tcp_refused", ip="x", host="y", port=1)
      not in _diag_node.toolTip())

check("§3 the diagnose action is a registry action with an EMPTY default",
      "node.diagnose" in HR.action_ids() and HR.default_sequence("node.diagnose") == ""
      and HR.HOTKEY_ACTIONS["node.diagnose"]["label"] == "ctx.diagnose")
check("§3 the sidebar row menu carries the diagnose row",
      any(e is not None and e[0] == "diagnose" for e in SB.CONTEXT_MENU_ITEMS)
      and "diagnose" in _win.sidebar._actions)
_src_map = open(os.path.join(ROOT, "graphics", "map_view.py"), encoding="utf-8").read()
check("§3 the map's node context menu carries it too (ONE method, two surfaces)",
      'ctx.diagnose' in _src_map and "_diagnose_node" in _src_map)

# the per-node guard: a second report for the same node while the first runs is refused
class _NullSignal:
    """A `Signal` stand-in: the fake thread below is never really connected."""

    def connect(self, *_a, **_kw):
        pass


class _SlowThread:
    report_ready = _NullSignal()

    def __init__(self, *a, **kw):
        pass

    def isRunning(self):
        return True

    def start(self):
        pass


_orig_rt = DG.ReachabilityThread
DG.ReachabilityThread = _SlowThread
try:
    _win._diagnose_threads = {}
    check("§3 the first report starts",
          _win._diagnose_node(_win.scene.get_node("sc1")) is True)
    check("§3 a second report for the SAME node is refused with an honest message",
          _win._diagnose_node(_win.scene.get_node("sc1")) is False)
    check("§3 ...while another node is fine (one report per node, not one per window)",
          _win._diagnose_node(_win.scene.get_node("sc2")) is True)
    _win._diagnose_threads = {}
finally:
    DG.ReachabilityThread = _orig_rt


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the version pin is the version this file describes",
      EXPECTED_APP_VERSION == "1.6" and _version.APP_VERSION == "1.6",
      f"{EXPECTED_APP_VERSION} / {_version.APP_VERSION}")
check("§4 the i18n pin counts the SHIPPED release (661 + 20 of v1.5.3 + 11 of v1.5.4"
      " + 14 of v1.5.5 + 2 of v1.5.6 + 29 of v1.5.7)",
      EXPECTED_I18N_KEYS == 778, str(EXPECTED_I18N_KEYS))
check("§4 the 20 new keys are present and non-empty in every language",
      all(str(LANGS[c].get(k, "")).strip() for k in NEW_KEYS for c in LANGS)
      and len(NEW_KEYS) == 20,
      str([k for k in NEW_KEYS for c in LANGS if not str(LANGS[c].get(k, "")).strip()]))
check("§4 the placeholders of the new keys match en in every language",
      all({m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS[c][k])}
          == {m for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", LANGS["en"][k])}
          for k in NEW_KEYS for c in LANGS))
check("§4 the registry grew 52 -> 54 (the assignable set 29 -> 31: no key out of the box; the "
      "v1.5.5 inventory pair takes it to 56 / 33; the v1.6 trio to 59 / 36)",
      len(HR.HOTKEY_ACTIONS) == 59 and len(HR.empty_default_action_ids()) == 36
      and {"node.collect_info", "node.diagnose"} <= set(HR.empty_default_action_ids()),
      f"{len(HR.HOTKEY_ACTIONS)} / {len(HR.empty_default_action_ids())}")
check("§4 task 1's OPEN question is decided: the schema does NOT change",
      _version.VERSION_FORMAT == "0.9", _version.VERSION_FORMAT)
_req = [ln.split(">=")[0].strip() for ln in
        open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().splitlines()
        if ln.strip() and not ln.strip().startswith("#")]
check("§4 no new dependency (requirements.txt keeps its four)",
      _req == ["PySide6", "paramiko", "keyring", "wcwidth"], str(_req))

from ui.settings_dialog import SettingsDialog  # noqa: E402

_dlg = SettingsDialog(None)
_keys = _dlg.collect()
check("§4 the settings hub still collects exactly 22 keys (the cap is a performance key)",
      len(_keys) == 22 and "theme" in _keys and "info_max_parallel" not in _keys,
      str(sorted(_keys)))
_dlg.close()
_win._dirty = False
_win._undo_baseline_dirty = False
_win.close()

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)

finish()
