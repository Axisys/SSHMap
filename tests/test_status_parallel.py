"""v1.1.2 final — Parallel status probes (release theme, ROADMAP v1.1.2 final).

The acceptance test of the series: the fake probes (the monkeypatched probe_ssh) without the network:
  * the counting of the parallel calls (max_active ≤ max_parallel and > 1),
    the round is shorter than the sequential one;
  * the results arrive AS THEY BECOME READY (not in the order of the target list);
  * the semantics of _busy are unchanged: True during the round, a repeated start_round()
    is ignored, after round_finished False and a new round starts;
  * the cancellation (stop()) on a parallel round: the exit within one timeout, not
    ceil(N/mp) × timeout; the ones cancelled before the probe start give no result;
  * the status_max_parallel key: the default 16, the clamp 1..64, the broken values → the default,
    set_max_parallel on the fly;
  * the soft auto-interval (task 3): N > LARGE_MAP_THRESHOLD (50) → the interval
    is doubled (effective_interval_ms, the timer is updated after the round and in
    set_interval), the E2E hint in the MainWindow status bar;
  * the "Statuses" dialog: the max_parallel spin (1..64, the prefill from the config),
    collect() — 18 keys (+status_max_parallel);
  * i18n: +2 keys × en/ru/zh — the parity 375 → 377;
  * the release state: APP_VERSION == "1.1.3", the pyproject cross-check, the requirements header.

Run: python tests/test_status_parallel.py   (from the project root) or python tests/run_all.py
"""
import os
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

# Network is forbidden in tests: the probes — a fake with controlled delays and a counter
# parallel calls (a monkeypatch of the module global — _probe_one reads it).
import services.status_checker as SC
from services.status_checker import (
    StatusChecker, get_status_settings,
    DEFAULT_MAX_PARALLEL, MAX_PARALLEL_LIMIT, LARGE_MAP_THRESHOLD)

_probe_lock = threading.Lock()
_active = {"n": 0}          # now in the probes (the pool workers)
_max_active = {"n": 0}      # the peak of parallelism per round
_calls = {"n": 0}           # the total calls of the fake probe
_delays = {}                # host -> delay, seconds (a controlled readiness order)


def _fake_probe(host, port, timeout=3.0):
    with _probe_lock:
        _active["n"] += 1
        _max_active["n"] = max(_max_active["n"], _active["n"])
        _calls["n"] += 1
    time.sleep(_delays.get(host, 0.0))
    with _probe_lock:
        _active["n"] -= 1
    return "offline"


SC.probe_ssh = _fake_probe


def _reset_counters():
    with _probe_lock:
        _max_active["n"] = 0
        _calls["n"] = 0


def _run_round(chk, timeout_ms=8000):
    """One round on the real event loop until round_finished (the test_status_checker pattern)."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    rounds = []
    chk.round_finished.connect(lambda r: (rounds.append(r), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)  # a guard against the test hanging
    t0 = time.time()
    chk.start_round()
    loop.exec()
    return rounds, time.time() - t0


def _targets(n, prefix="p", delay=0.0):
    """n targets with unique hosts; each one's delay — from _delays[host]."""
    out = []
    for i in range(n):
        h = f"h{prefix}{i}"
        _delays[h] = delay  # the key — EXACTLY host (the fake reads _delays.get(host))
        out.append((f"{prefix}{i}", h, 22))
    return out


# ══ 1. Counting the parallel calls (task 1: ThreadPoolExecutor) ══════════
print("== parallelism ==")
chk = StatusChecker(interval_ms=5000, probe_timeout=0.5, max_parallel=4, parent=None)
_reset_counters()
chk.set_servers(_targets(8, delay=0.25))
rounds, elapsed = _run_round(chk)
res_map = dict(rounds[0]) if rounds else {}
check("the round is finished: all the 8 targets are in round_finished", len(res_map) == 8, str(res_map))
check("all the results are offline (the fake)", all(v == "offline" for v in res_map.values()), str(res_map))
with _probe_lock:
    peak = _max_active["n"]
    total_calls = _calls["n"]
check("the parallelism really was (the peak > 1 the simultaneous probes)", peak >= 2, f"peak={peak}")
check("the max_parallel=4 ceiling is not exceeded (the peak ≤ 4)", peak <= 4, f"peak={peak}")
check("exactly 8 calls of the fake probe (no duplicates)", total_calls == 8, str(total_calls))
# A sequential loop: 8 × 0.25 = 2.0 s; parallel (4 workers): ~0.5–0.7 s
check("the round is shorter than the sequential one (elapsed < 1.6 s at the baseline 2.0 s)",
      elapsed < 1.6, f"elapsed={elapsed:.2f}s")
chk.stop()

# ══ 2. The results as they become ready (as_completed, not the list order) ══════
print("== results as they complete ==")
chk2 = StatusChecker(interval_ms=5000, probe_timeout=0.6, max_parallel=4, parent=None)
_reset_counters()
# The ORDER OF FOLLOWING of the targets: from slow to fast (t0 — the longest).
for i, d in enumerate((0.5, 0.3, 0.15, 0.05)):
    _delays[f"hq{i}"] = d
chk2.set_servers([(f"q{i}", f"hq{i}", 22) for i in range(4)])
order = []
times = []
chk2.status_changed.connect(lambda sid, st: (order.append(sid), times.append(time.time())))
rounds, elapsed = _run_round(chk2)
check("all the 4 results are delivered", len(order) == 4, str(order))
check("the fast probe arrived FIRST (not the first in the list of the targets)", order[:1] == ["q3"], str(order))
check("the slow probe arrived LAST (the first in the list of the targets)", order[-1:] == ["q0"], str(order))
if len(times) >= 2:
    check("the results are spread in time as they become ready (the spread ≥ 0.15 s)",
          times[-1] - times[0] >= 0.15, f"spread={times[-1] - times[0]:.2f}s")
else:
    check("the results are spread in time as they become ready (the spread ≥ 0.15 s)", False, str(times))
chk2.stop()

# ══ 3. The _busy semantics are unchanged (task 1: a repeated start is ignored) ══
print("== _busy semantics ==")
chk3 = StatusChecker(interval_ms=5000, probe_timeout=0.6, max_parallel=2, parent=None)
_reset_counters()
chk3.set_servers(_targets(2, prefix="b", delay=0.5))
chk3.start_round()
check("during the round is_busy == True (synchronously, before the thread)", chk3.is_busy is True)
thread_before = chk3._thread
chk3.start_round()  # a repeated launch during an active round — it must be ignored
check("the repeated start_round() did not create the second thread", chk3._thread is thread_before,
      f"{chk3._thread} vs {thread_before}")
rounds, elapsed = _run_round(chk3)  # we wait for the round_finished of the first round
with _probe_lock:
    calls_after_r1 = _calls["n"]
check("the round ran exactly 2 probes (the ignore did not add the calls)", calls_after_r1 == 2, str(calls_after_r1))
check("after the round_finished is_busy == False", chk3.is_busy is False)
rounds2, _ = _run_round(chk3)  # a new round after the release — it starts
with _probe_lock:
    calls_after_r2 = _calls["n"]
check("the next round ran (the 2 more probes)", calls_after_r2 == 4, str(calls_after_r2))
chk3.stop()

# ══ 4. The cancellation on a parallel round (stop()) ═══════════════════════════════
print("== cancel ==")
chk4 = StatusChecker(interval_ms=5000, probe_timeout=0.5, max_parallel=2, parent=None)
_reset_counters()
# 6 targets × 0.5 s at mp=2: without cancellation a round ≥ 1.5 s (3 batches); with one — ~0.5 s.
chk4.set_servers(_targets(6, prefix="c", delay=0.5))
emitted = []
chk4.status_changed.connect(lambda sid, st: emitted.append(sid))
t0 = time.time()
chk4.start_round()
time.sleep(0.1)          # we let the round start (all 6 tasks are already in the pool)
chk4.stop()              # the cancellation + waiting for the thread (blocks until the thread finish)
elapsed_cancel = time.time() - t0
check("stop() finished the round faster than the full parallel cycle (< 1.3 s at the baseline ≥ 1.5 s)",
      elapsed_cancel < 1.3, f"elapsed={elapsed_cancel:.2f}s")
wait_until(lambda: not chk4.is_busy, timeout_ms=3000)
check("after the stop() is_busy == False (the finished-signal is delivered)", chk4.is_busy is False)
# In flight at the cancellation there was one batch (mp=2): ≤ 2 results; the other probes
# canceled before the start — they have no results (the "not checked" semantics is preserved).
check("the cancelled before the probe start gave no results (delivered < 6, ≤ 2)",
      len(emitted) < 6 and len(emitted) <= 2, str(emitted))

# ══ 5. The status_max_parallel key: the config + the setters (task 2) ════════════════
print("== status_max_parallel config ==")
from i18n import save_config as _save_cfg, load_config as _load_cfg


def _clear_cfg():
    for p in (os.path.join(os.path.expanduser("~"), ".sshmap", "config.json"),):
        try:
            os.remove(p)
        except OSError:
            pass


_clear_cfg()
st = get_status_settings()
check("no config → the max_parallel default 16 (the ROADMAP 'default 16')",
      st["max_parallel"] == DEFAULT_MAX_PARALLEL == 16, str(st))
_save_cfg({"status_max_parallel": 32})
st = get_status_settings()
check("the valid value is read (32)", st["max_parallel"] == 32, str(st))
_save_cfg({"status_max_parallel": 0})
st = get_status_settings()
check("the clamp from below: 0 → 1", st["max_parallel"] == 1, str(st))
_save_cfg({"status_max_parallel": 9999})
st = get_status_settings()
check(f"the clamp from above: 9999 → {MAX_PARALLEL_LIMIT}", st["max_parallel"] == MAX_PARALLEL_LIMIT, str(st))
_save_cfg({"status_max_parallel": "abc"})
st = get_status_settings()
check("the broken value (str) → the default 16", st["max_parallel"] == 16, str(st))
_save_cfg({"status_max_parallel": True})
st = get_status_settings()
check("the bool → the default 16 (the _num pattern)", st["max_parallel"] == 16, str(st))

chk5 = StatusChecker(interval_ms=5000, probe_timeout=0.3, max_parallel=8, parent=None)
check("the constructor: the max_parallel=8 is read", chk5.max_parallel == 8, str(chk5.max_parallel))
chk5.set_max_parallel(3)
check("set_max_parallel(3) on the fly", chk5.max_parallel == 3, str(chk5.max_parallel))
chk5.set_max_parallel(10**6)
check(f"set_max_parallel: the clamp from above → {MAX_PARALLEL_LIMIT}", chk5.max_parallel == MAX_PARALLEL_LIMIT)
chk5.set_max_parallel("junk")
check("set_max_parallel: the broken value → the default 16", chk5.max_parallel == 16)
chk5.stop()

# ══ 6. The soft auto-interval for the large maps (task 3) ═════════════════════
print("== auto interval for large maps ==")
chk6 = StatusChecker(interval_ms=30_000, probe_timeout=0.2, max_parallel=16, parent=None)
check("N=50 — NOT a large map (the threshold: N > 50)", not chk6.is_large_map()
      and chk6.target_count == 0)
chk6.set_servers(_targets(50, prefix="m"))
check("N=50: the effective interval = the base one (30 s)",
      not chk6.is_large_map() and chk6.effective_interval_ms() == 30_000,
      f"eff={chk6.effective_interval_ms()}")
chk6.set_servers(_targets(51, prefix="m"))
check("N=51: the large map → the interval is doubled (60 s)",
      chk6.is_large_map() and chk6.effective_interval_ms() == 60_000,
      f"eff={chk6.effective_interval_ms()}")
_reset_counters()
_run_round(chk6)  # a round of 51 targets (the fake is instant)
check("after the round the timer really is switched to the doubled interval",
      chk6._timer.interval() == 60_000, str(chk6._timer.interval()))
chk6.set_interval(20_000)
check("set_interval with the large map: the timer is the EFFECTIVE one at once (40 s)",
      chk6.interval_ms == 20_000 and chk6._timer.interval() == 40_000,
      f"base={chk6.interval_ms} timer={chk6._timer.interval()}")
chk6.set_servers(_targets(10, prefix="m"))
check("N=10: back to the base interval (20 s)",
      not chk6.is_large_map() and chk6.effective_interval_ms() == 20_000)
_run_round(chk6)
check("after the round on the small map the timer is returned to the base one",
      chk6._timer.interval() == 20_000, str(chk6._timer.interval()))
chk6.stop()

# ══ 7. E2E: the hint in the MainWindow status bar at N > 50 (task 3) ════════
print("== main window hint ==")
import ui.main_window as MW
from models.server import ServerData

win = MW.MainWindow()
for i in range(51):
    win.scene.add_server(ServerData(id=f"big{i:02d}", alias=f"n{i}", host="10.9.9.9", user="u"))
win._sync_status_targets()
check("the MainWindow: the 51 target in the plan, the is_large_map is True",
      win._status_checker.target_count == 51 and win._status_checker.is_large_map(),
      str(win._status_checker.target_count))
check("the hint is shown once (the _auto_interval_hinted)", getattr(win, "_auto_interval_hinted", None) is True)
msg = win.statusBar().currentMessage()
check("the status bar: the hint with the number of the nodes (51)", "51" in msg and msg != "", msg)
win._sync_status_targets()  # a repeated sync at the same N — the hint is not duplicated
check("the repeated sync does not reset the flag (the hint is one-time)", win._auto_interval_hinted is True)
# Below the threshold again → the flag is reset, we can hint again
for n in list(win.scene.nodes()):
    win.scene.remove_server(n.data.id)
win._sync_status_targets()
check("after the scene is cleared the flag is reset (the threshold is crossed again — the hint is possible)",
      win._auto_interval_hinted is False and win._status_checker.target_count == 0)
win._dirty = False
win.close(); win.destroy()

# ══ 8. The "Statuses" dialog: the spin + collect() (task 2) ════════════════════════
print("== settings dialog ==")
import i18n as _i18n_mod
from ui.settings_dialog import SettingsDialog

_clear_cfg()
dlg = SettingsDialog(None)
check("the max_parallel spin exists, the range 1..64",
      hasattr(dlg, "max_parallel_spin") and dlg.max_parallel_spin.minimum() == 1
      and dlg.max_parallel_spin.maximum() == MAX_PARALLEL_LIMIT,
      f"min={getattr(dlg, 'max_parallel_spin', None) and dlg.max_parallel_spin.minimum()}")
check("the prefill without the config: the default 16", dlg.max_parallel_spin.value() == 16,
      str(dlg.max_parallel_spin.value()))
_save_cfg({"status_max_parallel": 32})
dlg2 = SettingsDialog(None)
check("the prefill from the config: 32", dlg2.max_parallel_spin.value() == 32, str(dlg2.max_parallel_spin.value()))
dlg2.retranslate()  # a language switch in an open dialog — the new label does not crash
check("retranslate: the label is translated (not the raw key)",
      dlg2._lbl_max_parallel.text() == _i18n_mod.t("settings.statuses.max_parallel")
      and dlg2._lbl_max_parallel.text() != "settings.statuses.max_parallel",
      dlg2._lbl_max_parallel.text())
c = dlg2.collect()
check("collect(): exactly 20 keys (17 + status_max_parallel v1.1.2 final + terminal_mode v1.2.2 + hotkeys v1.3.2)",
      len(c) == 20 and "status_max_parallel" in c and "terminal_mode" in c, str(sorted(c)))
check("collect(): status_max_parallel = the int from the spinbox",
      isinstance(c["status_max_parallel"], int) and c["status_max_parallel"] == 32, str(c.get("status_max_parallel")))
_clear_cfg()

# ══ 9. i18n: +2 keys × en/ru/zh — the parity 375 → 377 ════════════════════════
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = ["settings.statuses.max_parallel", "status.auto_interval_hint"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 2 new v1.1.2 final keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

# ══ 10. The release state (the pins — tests/_common.py: EXPECTED_APP_VERSION) ══════
print("== release state ==")
check_release_state(ROOT)

finish()
