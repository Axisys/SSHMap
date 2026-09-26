"""Background checking of map node statuses (v0.7.1).

Status semantics:
    online  — TCP port is open AND the server sent an SSH banner ("SSH-x.y-...")
    warn    — port is open, but no banner within the timeout (non-SSH service / firewall)
    offline — unreachable (refused / timeout / DNS)

Probes run in a dedicated QThread (_ProbeThread), not via a QTimer in the
main thread: a synchronous socket.create_connection with timeout=3 s × N nodes
would block the GUI. The QTimer here only spreads the rounds over time
(interval is configurable, default 30 s); a concurrent re-launch of a
round is impossible (_busy flag).

v1.1.2 final: probes within a round run IN PARALLEL (ThreadPoolExecutor,
ceiling status_max_parallel, default 16): the worst case of a round used to be
N × timeout (100 offline ≈ 5 min), now ceil(N/max_parallel) × timeout
(≈ 20–30 s). Results arrive as they complete (as_completed →
probed signal in the QThread — the _busy/round_finished semantics are
unchanged). Soft auto-interval: N > LARGE_MAP_THRESHOLD (50) → the round
interval doubles (effective_interval_ms; there is no hard limit on the number
of servers — ROADMAP v1.1.2 final, task 3).

Cancellation: stop()/shutdown() set a threading.Event — a probe that has not
started yet (was waiting for a worker) returns immediately with no result
(the node is assigned no status, just like "skipped between nodes" in the old
sequential loop); in-flight probes run out their network timeout. Then the
thread is waited on with a margin of
ceil(N/max_parallel) × timeout + 2 s (upper bound; the actual exit takes
one timeout). Previously shutdown waited only probe_timeout + 2 s, which with
≥ 2 nodes is shorter than a whole round — the QObject was destroyed together
with a running QThread (AUDIT v0.7.2, high #5).

v1.4rc2 (plugin foundation, rc2): an optional PLUGIN STATUS PROVIDER joins a probe. The
manager installs it with `set_status_provider(provider)`; the provider is called inside
the pool worker (a worker thread — never the GUI thread, PLUGINS.md §6) with
`(server_id, ssh_status)` and returns `(kind, detail) | None`. The round keeps the WORSE
of the two by severity and the plugin's detail travels on its own `status_detail` signal
(a tooltip line on the card); a hung plugin is abandoned by the manager's hook budget, so
it cannot hang a round. With no provider installed the round is exactly the pre-rc2 probe.

v1.5rc3 (ROADMAP task 3): every result is TIMESTAMPED. `_on_probed` records
`time.time()` per server and `_on_done` records the end of the round, so the window can
ask "how old is this datum" (`last_checked_at` / `last_round_at`) and paint the stale mark
once `stale_threshold_s()` — `max(2 × the effective interval, STALE_MIN_SEC)` — has
passed. The timestamps are FACTS about the round; the checker itself never repaints
anything (the GUI half lives in `graphics/server_node.py` + `ui/main_window.py`).

v1.5 (ROADMAP): the checker can be told to never probe a set of ids (`set_skip_ids`) —
the DEMO map's nodes, whose status is EMULATED by `storage/example_project.py`. The
filter lives in `_subset()`, so every round obeys it; the checker still knows nothing
about emulation, and with no skip set it behaves exactly as before.

In a headless environment without a running event loop the timers never fire —
child threads do not start, which makes the module safe for smoke tests.

v1.5.2 (ROADMAP task 2): the round had NO logging call at all — a probe result reached
the card and the status bar and left nothing behind (the "history the interface never
kept"). `start_round()`'s `_on_done` now writes ONE summary record per round into
`~/.sshmap/logs/sshmap.log` AND into the activity ring the panel renders. It is a
SUMMARY on purpose: the per-node answers are already on the cards, and a hundred-node
map must not turn one round into a hundred log lines.

v1.6.6 (ROADMAP task 1/2): the cadence has a THIRD state — **manual only**, selected by
`status_interval_sec = 0` (`MANUAL_INTERVAL_SEC`, a DECLARED sentinel, so one setting keeps
one home and no second key appears). In that mode NOTHING starts a round by itself: `start()`
arms neither the timer nor the deferred first round, a project load is refused by the ONE
guard in `MainWindow._load_project_at()`, and `set_manual_only(True)` stops a running timer
immediately. The deferred first round becomes a GUARDED slot (`_deferred_first_round()`) —
a `QTimer.singleShot` cannot be un-armed, so the slot re-asks the mode when it fires. The
MANUAL doors are untouched: "Check statuses now" and the node context menu still call
`start_round()`, `_subset()`, `is_busy` and the skip set behave exactly as they do
automatically. Because "two missed rounds" means nothing where there are no rounds, the
freshness horizon of that mode is the DECLARED `MANUAL_STALE_SEC` (one day) instead of
`max(2 × the interval, STALE_MIN_SEC)` — the freshness tick keeps running either way, so a
green card that was true yesterday is not presented as a current fact.
"""
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, QTimer, Signal

try:  # v1.5.2: the round summary (the activity history, ROADMAP task 2)
    from modules.logger import get_logger
except ImportError:  # pragma: no cover — the package layout (sshmap.services.*)
    from ..modules.logger import get_logger

log = get_logger(__name__)


STATUS_ONLINE = "online"    # green: TCP + SSH banner
STATUS_WARN = "warn"        # yellow: port open, but no banner
STATUS_OFFLINE = "offline"  # red: unreachable

# v1.4rc2 (plugin foundation, rc2): the severity ladder of the status merge with a
# plugin's `status_probe` (PLUGINS.md §3 — "the worse of the two by severity").
SEVERITY = {STATUS_ONLINE: 0, STATUS_WARN: 1, STATUS_OFFLINE: 2}

DEFAULT_INTERVAL_MS = 30_000   # interval between periodic checks
DEFAULT_INTERVAL_SEC = 30      # the same, in seconds — default for the status_interval_sec key (v1.1)
PROBE_TIMEOUT_S = 3.0          # timeout of a single probe (connect + banner)

# v1.6.6 (ROADMAP task 1): the cadence's DECLARED range and its third state. The range is
# the clamp the key has always had (`5..86400`); `MANUAL_INTERVAL_SEC = 0` is the SENTINEL
# that selects "manual only" — NOT a second config key, so the setting keeps ONE home.
# `resolve_interval_sec()` is the PURE reader: exactly 0 means manual, every other value
# (a missing, negative, non-numeric or out-of-range one included) keeps the ordinary clamp,
# so a corrupt value degrades to a REAL interval rather than to a silent mode change.
MANUAL_INTERVAL_SEC = 0        # the sentinel: no round starts by itself
MIN_INTERVAL_SEC = 5
MAX_INTERVAL_SEC = 86400

# v1.1.2 final (tasks 1–3): parallel probes and a soft auto-interval
DEFAULT_MAX_PARALLEL = 16      # default for the status_max_parallel key (ROADMAP: "default 16")
MAX_PARALLEL_LIMIT = 64        # clamp ceiling (dialog spinbox and validator — one range)
LARGE_MAP_THRESHOLD = 50       # N > 50 nodes → round interval doubles ("N > ~50")

# v1.5rc3 (ROADMAP task 3): status FRESHNESS. A status is a fact with a timestamp, and
# the map must not present an old fact as a current one. The threshold is a FLOOR as
# well as a multiple: `max(2 × the effective interval, STALE_MIN_SEC)` — with the 30 s
# default that is 90 s, and a user who shortens the interval to 5 s still gets a
# meaningful "this is old" (10 s would be noise, not a signal). Freshness NEVER changes
# a status and never starts a round: it only repaints the mark and the tooltip line
# (see ServerNode.refresh_freshness).
STALE_MIN_SEC = 90.0

# v1.6.6 (ROADMAP task 1): the horizon of the MANUAL mode. "Two missed rounds" is not a
# sentence that means anything where there are no rounds, and marking a 90-second-old manual
# check stale would be noise rather than a signal — so the manual mode answers this DECLARED
# horizon instead. It is deliberately LONG (one day): the age of a status is the only clock
# the manual mode has, and it has to be patient enough to be a signal and short enough that a
# green card is never presented as a current fact for a whole week.
MANUAL_STALE_SEC = 86400.0


def round_summary(results) -> str:
    """The ONE line a finished round leaves in the log (v1.5.2, ROADMAP task 2).

    PURE, so the topical test pins the sentence without a probe: the counts by status in
    the fixed order online → warn → offline, plus `?` for an answer that is none of the
    three (a plugin's merged kind is validated elsewhere — a summary must never lose a
    probed node silently). Example:

        "Status round: 5 probed — online 3, warn 1, offline 1"
    """
    counts = {STATUS_ONLINE: 0, STATUS_WARN: 0, STATUS_OFFLINE: 0}
    other = 0
    total = 0
    for item in results or ():
        try:
            _sid, status = item
        except (TypeError, ValueError):
            continue
        total += 1
        if status in counts:
            counts[status] += 1
        else:
            other += 1
    parts = [f"{name} {counts[name]}" for name in (STATUS_ONLINE, STATUS_WARN, STATUS_OFFLINE)]
    if other:
        parts.append(f"other {other}")
    return f"Status round: {total} probed — " + ", ".join(parts)


def resolve_interval_sec(value=DEFAULT_INTERVAL_SEC) -> int:
    """The round interval the key REALLY selects — 0 meaning "manual only" (v1.6.6).

    PURE, and the ONE reader of the `status_interval_sec` value (v1.1 + v1.6.6):
    exactly `0` is the DECLARED sentinel of the manual mode and is answered as `0`; every
    other usable number keeps the ordinary clamp (`MIN_INTERVAL_SEC..MAX_INTERVAL_SEC`).
    A MISSING (`None`), non-numeric, boolean, NaN / ±inf or out-of-range value answers the
    DEFAULT (`DEFAULT_INTERVAL_SEC`) — never the sentinel: a corrupt value must degrade to a
    real interval, because silently switching the probes OFF is the one failure this reader
    exists to prevent. A negative number is an ordinary out-of-range value (clamped to
    `MIN_INTERVAL_SEC`), not a way to select the manual mode.
    """
    if value is None or isinstance(value, bool):
        return DEFAULT_INTERVAL_SEC
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SEC
    if number != number or number in (float("inf"), float("-inf")):  # NaN / ±inf
        return DEFAULT_INTERVAL_SEC
    if number == MANUAL_INTERVAL_SEC:
        return MANUAL_INTERVAL_SEC
    return max(MIN_INTERVAL_SEC, min(int(number), MAX_INTERVAL_SEC))


def is_manual_interval(resolved_sec) -> bool:
    """Does a RESOLVED interval mean "manual only"? (PURE — the `0` sentinel, one place.)"""
    try:
        return int(resolved_sec) == MANUAL_INTERVAL_SEC
    except (TypeError, ValueError):
        return False


def get_status_settings() -> dict:
    """v1.1 (ROADMAP task 4) + v1.1.2 final (task 2): status settings from ~/.sshmap/config.json.

    Source — i18n.load_config() (never raises, {} on error). Returns:
        {"interval_sec": int, "manual": bool, "probe_timeout_sec": float, "max_parallel": int}
    Keys are OPTIONAL, defaults = the current v1.0 behavior (30 s / 3.0 s / 16):
        status_interval_sec      — round period (clamped 5..86400 s) OR the DECLARED `0`
                                   sentinel, which selects the MANUAL-only mode (v1.6.6);
        status_probe_timeout_sec — timeout of a single probe (clamped 0.2..60 s);
        status_max_parallel      — ceiling of parallel probes per round
                                   (clamped 1..MAX_PARALLEL_LIMIT; v1.1.2 final).
    Corrupt values (non-numeric, bool) → default. Never raises.

    v1.6.6 (ROADMAP task 1): the resolved PAIR is answered — `interval_sec` and the
    `manual` flag it implies (`resolve_interval_sec()` + `is_manual_interval()` are the ONE
    place that decides both), so no caller has to compare a number to a magic zero.
    """
    cfg: dict = {}
    try:
        from i18n import load_config
        cfg = load_config() or {}
    except Exception:  # noqa: BLE001 — the config is optional, defaults matter more
        pass

    def _num(value, default: float) -> float:
        try:
            if isinstance(value, bool):
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    interval = resolve_interval_sec(cfg.get("status_interval_sec"))
    timeout = _num(cfg.get("status_probe_timeout_sec"), PROBE_TIMEOUT_S)
    timeout = max(0.2, min(timeout, 60.0))
    # v1.1.2 final (task 2): ceiling of parallel probes — clamped as in the dialog (1..64)
    max_parallel = int(_num(cfg.get("status_max_parallel"), DEFAULT_MAX_PARALLEL))
    max_parallel = max(1, min(max_parallel, MAX_PARALLEL_LIMIT))
    return {"interval_sec": interval, "manual": is_manual_interval(interval),
            "probe_timeout_sec": timeout, "max_parallel": max_parallel}


def probe_ssh(host: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> str:
    """Synchronous SSH reachability probe. Call from a worker thread only!

    Connects to host:port and reads the first bytes: an SSH server sends the
    banner "SSH-x.y-" right after the TCP handshake. Got it — online; the
    connection was established but no data / foreign data — warn; cannot
    connect — offline.
    """
    if not host:
        return STATUS_OFFLINE
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            try:
                banner = sock.recv(32)
            except (socket.timeout, OSError):
                return STATUS_WARN  # connection is up, but no data within the timeout
            if not banner:
                return STATUS_WARN  # the server closed the connection without any bytes
            return STATUS_ONLINE if banner.lstrip().startswith(b"SSH-") else STATUS_WARN
    except (socket.timeout, OSError):
        return STATUS_OFFLINE


def _build_targets(servers) -> list:
    """Normalize an iterable of ``(id, host, port)`` into the probe target list.

    Shared by ``StatusChecker.set_servers`` and ``MainWindow._sync_status_targets``
    (v1.3.3.3, ROADMAP task 5: the manual round builds its targets with the SAME
    normalization instead of a second, drifting copy). An entry without an id or a
    host is dropped — the probe would be meaningless; a broken port falls back to 22
    and is clamped to the protocol range.
    """
    targets = []
    for sid, host, port in servers or ():
        if not sid or not host:
            continue
        try:
            p = int(port) if port else 22
        except (TypeError, ValueError):
            p = 22
        targets.append((sid, str(host).strip(), max(1, min(65535, p))))
    return targets


class _ProbeThread(QThread):
    """One check round: probes in parallel (ThreadPoolExecutor, v1.1.2 final),
    results — as they complete."""

    probed = Signal(str, str)  # (server_id, status)
    # v1.4rc2 (plugin foundation, rc2): the plugin detail of a merged result — a tooltip
    # line ("HTTP 503", "3 containers"). Emitted only when a plugin had something to say,
    # so the SSH-only path stays byte-for-byte what it was.
    detail = Signal(str, str)  # (server_id, plugin detail)

    def __init__(self, targets, timeout: float = PROBE_TIMEOUT_S, parent=None,
                 cancel: "threading.Event | None" = None,
                 max_parallel: int = DEFAULT_MAX_PARALLEL,
                 status_provider=None):
        super().__init__(parent)
        self._targets = list(targets)  # [(id, host, port), ...]
        self._timeout = max(0.2, float(timeout))
        self._cancel = cancel
        # v1.4rc2: the plugin status provider — `provider(server_id, ssh_status)` returns
        # `(kind, detail) | None` and is called INSIDE the pool worker (a worker thread,
        # never the GUI thread: the PLUGINS.md §6 discipline). The manager owns the hook
        # budget, so a hung plugin cannot hang the round.
        self._status_provider = status_provider
        try:
            mp = int(max_parallel)
        except (TypeError, ValueError):
            mp = DEFAULT_MAX_PARALLEL
        self._max_parallel = max(1, min(mp, MAX_PARALLEL_LIMIT))

    def run(self):
        # v1.1.2 final (task 1): ThreadPoolExecutor instead of a sequential loop.
        # Worst case of a round: ceil(N/max_parallel) × timeout (was N × timeout).
        # Cancellation is checked before each submission: submitted probes run out
        # their network timeout, new ones are not submitted; the executor waits for all
        # its workers (with block), so run() finishes only after the last probe.
        with ThreadPoolExecutor(max_workers=self._max_parallel) as pool:
            futures = {}
            for sid, host, port in self._targets:
                if self._cancel is not None and self._cancel.is_set():
                    break  # round cancelled (stop()/shutdown()) — do not submit new probes
                futures[pool.submit(self._probe_one, sid, host, port)] = sid
            # as_completed: results arrive AS THEY COMPLETE (not in the order of the
            # target list). The signal is emitted here — in the QThread, not in the pool
            # workers: queued delivery to the GUI thread and the probed → finished order
            # (FIFO of a single sender) are preserved unchanged.
            for fut in as_completed(futures):
                try:
                    answer = fut.result()
                except Exception:
                    answer = (STATUS_OFFLINE, "")  # a probe must not crash the round
                if answer is None:
                    continue  # probe cancelled before it started — no result (as before)
                if isinstance(answer, tuple):
                    status, detail = answer
                else:  # a foreign return shape (an exotic monkeypatch) — status only
                    status, detail = answer, ""
                if status is None:
                    continue
                self.probed.emit(futures[fut], status)
                if detail:
                    # v1.4rc2: after `probed`, so a receiver that reacts to the status
                    # (node.set_status) is already in the detail-aware state.
                    self.detail.emit(futures[fut], detail)

    def _probe_one(self, sid: str, host: str, port: int):
        """One probe in a pool worker (the network timeout is bounded by timeout).

        None — the round was cancelled BEFORE this probe started (the cancel flag was
        set while the probe was waiting for a worker): the node is assigned no result,
        the signal is not emitted — the same semantics as the sequential loop's
        "exit between nodes". Without this check cancellation would be useless: the
        submit loop hands all N tasks to the pool in microseconds, and the round would
        run out the whole ceil(N/mp) × timeout.

        v1.4rc2: the answer is `(status, plugin_detail)` — the SSH probe's result MERGED
        with the status plugins' opinions (the worse by severity, the details
        concatenated, `PLUGINS.md` §3). A plugin can only make a status worse, never
        better: the SSH probe is the transport-level truth.
        """
        if self._cancel is not None and self._cancel.is_set():
            return None
        try:
            status = probe_ssh(host, port, self._timeout)
        except Exception:
            status = STATUS_OFFLINE  # a probe must not crash the round
        detail = ""
        if self._status_provider is not None:
            try:
                merged = self._status_provider(sid, status)
            except Exception:
                merged = None  # a broken provider never breaks a round
            if merged:
                try:
                    merged_status, merged_detail = merged[0], merged[1]
                    if merged_status in SEVERITY:
                        status = merged_status
                    detail = str(merged_detail or "")
                except (IndexError, TypeError):
                    detail = ""
        return status, detail


class StatusChecker(QObject):
    """Periodic controller of node status checks.

    Signals:
        status_changed(server_id, str) — the status of a single server was determined
        round_finished(list)           — round finished; [(server_id, status), ...]

    Usage (MainWindow):
        checker = StatusChecker(parent=window)
        checker.status_changed.connect(on_status)
        checker.set_servers([(node.data.id, node.data.host, node.data.ssh_port), ...])
        checker.start()  # first round after ~2 s + a periodic QTimer
    """

    status_changed = Signal(str, str)
    round_finished = Signal(list)
    # v1.4rc2 (plugin foundation, rc2): the optional plugin detail of a merged probe
    # result — a tooltip line on the card. Emitted only when a plugin produced one.
    status_detail = Signal(str, str)

    def __init__(self, interval_ms: int = DEFAULT_INTERVAL_MS,
                 probe_timeout: float = PROBE_TIMEOUT_S,
                 max_parallel: int = DEFAULT_MAX_PARALLEL, parent=None):
        super().__init__(parent)
        self._interval = max(5000, int(interval_ms))  # no more often than once per 5 s
        self._probe_timeout = float(probe_timeout)
        try:
            mp = int(max_parallel)
        except (TypeError, ValueError):
            mp = DEFAULT_MAX_PARALLEL
        self._max_parallel = max(1, min(mp, MAX_PARALLEL_LIMIT))  # v1.1.2 final
        self._targets: list = []          # [(id, host, port), ...]
        self._busy = False                # is a round already running?
        self._last_results: dict = {}     # id -> last status
        self._last_details: dict = {}     # id -> last plugin detail (v1.4rc2)
        # v1.5rc3 (ROADMAP task 3): id -> epoch seconds of the last result, plus the end
        # of the last completed round. The window reads them to answer "checked N min ago"
        # and to paint the stale mark; a status itself is never derived from them.
        self._last_times: dict = {}
        self._last_round_at: float = 0.0
        self._status_provider = None      # v1.4rc2: provider(sid, ssh_status) -> (kind, detail)
        # v1.5 (ROADMAP): the ids the checker must NEVER probe while the DEMO map is the
        # open project — their status is EMULATED by `storage/example_project.py`, and a
        # round would repaint them `offline` within 30 s and turn the demo into a lie.
        # A skipped id is not a target at all (`_subset`), so no probe, no result, no
        # timestamp and no `status_changed` — the card keeps what the demo declared.
        self._skip_ids: set = set()
        self._thread: _ProbeThread | None = None
        self._cancel = threading.Event()  # AUDIT v0.7.2 #5: cancel the current round
        # v1.6.6 (ROADMAP task 2): the cadence's third state and whether periodic checking
        # was ever ASKED for. `_manual_only` is the live switch ("no round starts by itself");
        # `_enabled` remembers a `start()` that a `stop()` has not undone, so switching the
        # manual mode OFF resumes the periodic rounds the user had already enabled — and
        # switching it on BEFORE `start()` arms nothing later.
        self._manual_only = False
        self._enabled = False

        self._timer = QTimer(self)
        self._timer.setInterval(self.effective_interval_ms())
        self._timer.timeout.connect(self.start_round)

    @property
    def interval_ms(self) -> int:
        return self._interval

    @property
    def probe_timeout(self) -> float:
        """v1.1: timeout of a single probe (s) — for visibility in tests/dialog."""
        return self._probe_timeout

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def manual_only(self) -> bool:
        """v1.6.6 (ROADMAP task 2): is the checker in the manual-only mode?

        The ONE predicate of the mode, read by the two guards that decide whether a round may
        start by itself (`start()` and `MainWindow._load_project_at()`). Purely a MODE: the
        manual doors ("Check statuses now", the node context menu) never ask it.
        """
        return bool(self._manual_only)

    @property
    def max_parallel(self) -> int:
        """v1.1.2 final (task 2): ceiling of parallel probes per round (clamped 1..64)."""
        return self._max_parallel

    @property
    def target_count(self) -> int:
        """v1.1.2 final: number of targets in the current check plan."""
        return len(self._targets)

    def is_large_map(self) -> bool:
        """v1.1.2 final (task 3): "large map" — N > LARGE_MAP_THRESHOLD (50)."""
        return len(self._targets) > LARGE_MAP_THRESHOLD

    def effective_interval_ms(self) -> int:
        """v1.1.2 final (task 3): the effective round interval.

        A soft safeguard instead of a hard limit on the number of servers: for
        large maps (N > LARGE_MAP_THRESHOLD) the base interval doubles — a round
        of parallel probes is still longer than on a small map. There is no hard
        ceiling (150 real servers is a legitimate case; navigation for large maps
        exists — groups/tags/search/collapse).
        """
        return self._interval * 2 if self.is_large_map() else self._interval

    def set_interval(self, ms: int):
        """v1.1 (ROADMAP task 4): change the round interval on the fly (the "Statuses" dialog).

        Clamped as in the constructor (no more often than once per 5 s). Works while
        the timer is active too — QTimer.setInterval restarts the countdown.
        v1.1.2 final: the timer receives the EFFECTIVE interval (for large maps —
        doubled, effective_interval_ms()).
        """
        self._interval = max(5000, int(ms))
        try:
            self._timer.setInterval(self.effective_interval_ms())
        except RuntimeError:
            pass  # Qt teardown — the timer's C++ object is already destroyed

    def set_probe_timeout(self, seconds: float):
        """v1.1 (ROADMAP task 4): change the probe timeout (takes effect from the next round)."""
        self._probe_timeout = max(0.2, float(seconds))

    def set_max_parallel(self, n: int):
        """v1.1.2 final (task 2): change the ceiling of parallel probes on the fly.

        Clamped 1..MAX_PARALLEL_LIMIT; takes effect from the next round (the current
        one runs in its own executor). Corrupt value → default (the set_probe_timeout
        pattern).
        """
        try:
            mp = int(n)
        except (TypeError, ValueError):
            mp = DEFAULT_MAX_PARALLEL
        self._max_parallel = max(1, min(mp, MAX_PARALLEL_LIMIT))

    def set_manual_only(self, flag: bool) -> None:
        """v1.6.6 (ROADMAP task 2): the ONE live switch of the manual-only mode.

        ON — the periodic timer is stopped AT ONCE and no later `start()` will arm it, and no
        deferred first round will slip through (the slot re-asks this flag when it fires).
        OFF — a `start()` that a `stop()` has not undone resumes the periodic rounds, so
        un-ticking the box in the settings does not silently leave the map unmonitored until
        the next launch. Idempotent, safe BEFORE `start()` (nothing is armed either way) and
        safe on a torn-down Qt object (RuntimeError is swallowed, the flag is already set).

        The manual DOORS are deliberately untouched: `start_round()`, `_subset()`, `is_busy`,
        the results and the skip set behave exactly as they do in the automatic mode, so
        "Check statuses now" and the node context menu keep working.
        """
        flag = bool(flag)
        self._manual_only = flag
        try:
            if flag:
                self._timer.stop()
            elif self._enabled and not self._timer.isActive():
                self._timer.start()
        except RuntimeError:
            pass  # Qt teardown — the timer's C++ object is already destroyed

    def set_status_provider(self, provider) -> None:
        """v1.4rc2: install the plugin status provider (`provider(sid, ssh_status)`).

        The provider returns `(kind, detail) | None` and is called INSIDE the round's pool
        worker — a worker thread, never the GUI thread (PLUGINS.md §6). The plugin manager
        owns the hook budget, so a hung plugin cannot hang a round; a provider that raises
        is ignored (the SSH probe's own result stands). `None` removes it — the round is
        then exactly the pre-v1.4rc2 probe.
        """
        self._status_provider = provider if callable(provider) else None

    def last_detail(self, server_id: str) -> str:
        """v1.4rc2: the last plugin detail of the server ("" — none was ever reported)."""
        return self._last_details.get(server_id, "")

    # ── v1.5rc3 (ROADMAP task 3): the age of a result ───────────────────────────

    def stale_threshold_s(self) -> float:
        """How old a result may be before it is presented as stale (seconds).

        `max(2 × the EFFECTIVE round interval, STALE_MIN_SEC)` — the effective one, so
        a large map (whose interval the soft doubling already stretched) gets the same
        "two missed rounds" rule as a small one. The single place that decides it; the
        card only paints what it is told.

        v1.6.6 (ROADMAP task 1): in the MANUAL mode the answer is the DECLARED
        `MANUAL_STALE_SEC` (one day) instead. There are no rounds to miss, and the age of a
        status is then the ONLY clock — a threshold of 90 s would mark every manual check
        stale before the user had a chance to look at it.
        """
        if self._manual_only:
            return MANUAL_STALE_SEC
        return max(2.0 * float(self.effective_interval_ms()) / 1000.0, STALE_MIN_SEC)

    def last_checked_at(self, server_id: str) -> float:
        """Epoch seconds of the server's last result (0.0 — never probed in this run)."""
        try:
            return float(self._last_times.get(server_id, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def is_stale(self, server_id: str, now: float = None) -> bool:
        """Is the server's last result older than `stale_threshold_s()`?

        A server that was never probed is NOT stale — it has no datum to be old (the
        card shows its idle mark instead). Purely a question about TIME: the status
        itself is untouched, here and everywhere else.
        """
        checked = self.last_checked_at(server_id)
        if checked <= 0.0:
            return False
        moment = time.time() if now is None else float(now)
        return (moment - checked) > self.stale_threshold_s()

    def last_round_at(self) -> float:
        """Epoch seconds of the end of the last COMPLETED round (0.0 — none yet)."""
        return float(self._last_round_at or 0.0)

    def set_servers(self, servers):
        """Update the target list. `servers` — an iterable of (id, host, port)."""
        self._targets = _build_targets(servers)

    def set_skip_ids(self, server_ids) -> None:
        """v1.5 (ROADMAP): ids this checker must NEVER probe (the demo's emulated nodes).

        Called by the window with `storage.example_project.demo_status_ids()` while the
        example map is the open project and with NOTHING for every other project, so the
        emulation can never outlive the demo. The filter lives in `_subset()` — the ONE
        place that decides what a round holds — so the periodic timer, the round of a
        project load and the on-demand "Check statuses now" of the selection all obey it
        without a second rule. Purely a target filter: the checker still knows nothing
        about emulation, and a skipped node simply never produces a result.
        """
        self._skip_ids = {str(sid) for sid in (server_ids or ()) if sid}

    def _subset(self, server_ids=None) -> list:
        """The targets of a round: all of them, or only the given server ids.

        v1.3.3.3 (ROADMAP task 5): the on-demand round of the node context menu checks
        the SELECTION, not the map — ``server_ids=None`` keeps the periodic behaviour
        (every target), a list restricts it (an unknown id is skipped). The order
        follows the stored target list, so a manual round of the whole selection behaves
        exactly like a periodic one.

        v1.5 (ROADMAP): the SKIPPED ids (`set_skip_ids`) are dropped here, whatever the
        caller asked for — the demo's emulated nodes are never probed.
        """
        if self._skip_ids:
            if server_ids is None:
                return [t for t in self._targets if t[0] not in self._skip_ids]
            wanted = {str(sid) for sid in server_ids if sid}
            return [t for t in self._targets if t[0] in wanted and t[0] not in self._skip_ids]
        if server_ids is None:
            return list(self._targets)
        wanted = {str(sid) for sid in server_ids if sid}
        return [t for t in self._targets if t[0] in wanted]

    def last_status(self, server_id: str) -> str:
        """The last determined status of the server ("" — never probed yet)."""
        return self._last_results.get(server_id, "")

    def start_round(self, server_ids=None) -> bool:
        """Start a check round. If the previous one is still running — do nothing.

        v1.3.3.3 (ROADMAP task 5): an optional ``server_ids`` restricts the round to
        those servers (the "Check statuses now" action probes the selection). Returns
        True when a round really started — False for "already busy" / "nothing to
        probe", so the caller can tell the user the truth. The probes themselves are
        unchanged: a ``_ProbeThread`` with the same timeout/parallel cap/cancel flag,
        i.e. off the GUI thread.
        """
        if self._busy:
            return False
        targets = self._subset(server_ids)
        if not targets:
            return False
        self._busy = True
        self._cancel.clear()  # new round — clear the previous round's cancel flag
        thread = _ProbeThread(targets, self._probe_timeout, parent=self,
                              cancel=self._cancel, max_parallel=self._max_parallel,
                              status_provider=self._status_provider)
        results = []

        def _on_probed(sid: str, status: str):
            results.append((sid, status))
            self._last_results[sid] = status
            # v1.5rc3: the result is a fact WITH A TIME — the staleness clock starts here
            self._last_times[sid] = time.time()
            self.status_changed.emit(sid, status)

        def _on_detail(sid: str, detail: str):
            # v1.4rc2: the plugin detail of a merged result travels on its own signal, so
            # `status_changed` (and every existing receiver) keeps its exact semantics.
            self._last_details[sid] = detail
            self.status_detail.emit(sid, detail)

        def _on_done():
            self._busy = False
            if self._thread is thread:
                self._thread = None
            thread.deleteLater()
            # v1.5rc3 (ROADMAP task 3): the round is closed — its age is measurable
            self._last_round_at = time.time()
            # v1.1.2 final (task 3): the interval of the NEXT tick — for the current size
            # of the map (targets may have changed during the round: nodes added/removed).
            try:
                self._timer.setInterval(self.effective_interval_ms())
            except RuntimeError:
                pass  # Qt teardown — the timer's C++ object is already destroyed
            # v1.5.2 (ROADMAP task 2): the round summary — ONE record per round for the
            # log file AND the activity panel (the per-node answers live on the cards).
            # Guarded: a broken logging setup must never break a round's completion.
            try:
                log.info(round_summary(results))
            except Exception:  # noqa: BLE001 — the summary is a side channel
                pass
            self.round_finished.emit(results)

        self._thread = thread
        thread.probed.connect(_on_probed)
        thread.detail.connect(_on_detail)
        thread.finished.connect(_on_done)
        thread.start()
        return True

    def _deferred_first_round(self):
        """The 2 s deferred first round of `start()` — a GUARDED slot (v1.6.6, task 2).

        A `QTimer.singleShot` cannot be un-armed, so switching the manual mode ON inside the
        2 s window would otherwise let exactly one stray round through — the one promise the
        mode exists to keep. The slot therefore re-asks the mode when it FIRES instead of
        being cancelled: a callback on a dangling object is impossible, and "manual only"
        means the same thing whenever it was selected.
        """
        if self._manual_only:
            return
        self.start_round()

    def start(self):
        """Enable periodic checks + the first round a bit after startup.

        The first round via QTimer.singleShot(2000), not immediately: at app startup
        the event sequence is still unfolding, and in headless tests
        without an event loop the deferred call simply never happens (safe).

        v1.6.6 (ROADMAP task 2): in the MANUAL-only mode this arms NOTHING — no timer and no
        deferred round (`_deferred_first_round()` re-asks the flag anyway). Opening the
        application is not "check my servers now": the manual doors are the only way in.
        """
        self._enabled = True
        if self._manual_only:
            return
        if not self._timer.isActive():
            self._timer.start()
            QTimer.singleShot(2000, self._deferred_first_round)

    def stop(self):
        """Stop the periodic checks and the current round.

        AUDIT v0.7.2 (high #5): an early return of the round is impossible — the cancel
        flag is set, the executor stops accepting new probes (the submitted ones
        run out their network timeout); then the thread is waited on with a margin of
        ceil(N/max_parallel) × timeout + 2 s (v1.1.2 final: the round is parallel —
        the margin used to be computed sequentially as N × timeout).
        """
        self._enabled = False  # v1.6.6: a stopped checker is not resumed by set_manual_only(False)
        self._timer.stop()
        self._cancel.set()
        thread = self._thread
        if thread is not None and thread.isRunning():
            batches = (len(self._targets) + self._max_parallel - 1) // max(1, self._max_parallel)
            wait_ms = int(self._probe_timeout * 1000) * max(1, batches) + 2000
            if not thread.wait(wait_ms):
                try:
                    from modules.logger import get_logger as _gl
                    _gl("services.status_checker").warning(
                        f"Probe thread did not finish within {wait_ms} ms after cancel")
                except Exception:
                    pass

    def shutdown(self):
        """Full stop when MainWindow is destroyed (the destroyed signal).

        Timer + cancellation and waiting for the current round — so the probe thread
        is not destroyed on the fly together with its parent (AUDIT v0.7.2, high #5:
        previously we waited only probe_timeout + 2 s, which is shorter than a whole
        round with ≥ 2 nodes).
        """
        self.stop()
