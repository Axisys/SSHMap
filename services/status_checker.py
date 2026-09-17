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

In a headless environment without a running event loop the timers never fire —
child threads do not start, which makes the module safe for smoke tests.
"""
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, QTimer, Signal


STATUS_ONLINE = "online"    # green: TCP + SSH banner
STATUS_WARN = "warn"        # yellow: port open, but no banner
STATUS_OFFLINE = "offline"  # red: unreachable

DEFAULT_INTERVAL_MS = 30_000   # interval between periodic checks
DEFAULT_INTERVAL_SEC = 30      # the same, in seconds — default for the status_interval_sec key (v1.1)
PROBE_TIMEOUT_S = 3.0          # timeout of a single probe (connect + banner)

# v1.1.2 final (tasks 1–3): parallel probes and a soft auto-interval
DEFAULT_MAX_PARALLEL = 16      # default for the status_max_parallel key (ROADMAP: "default 16")
MAX_PARALLEL_LIMIT = 64        # clamp ceiling (dialog spinbox and validator — one range)
LARGE_MAP_THRESHOLD = 50       # N > 50 nodes → round interval doubles ("N > ~50")


def get_status_settings() -> dict:
    """v1.1 (ROADMAP task 4) + v1.1.2 final (task 2): status settings from ~/.sshmap/config.json.

    Source — i18n.load_config() (never raises, {} on error). Returns:
        {"interval_sec": int, "probe_timeout_sec": float, "max_parallel": int}
    Keys are OPTIONAL, defaults = the current v1.0 behavior (30 s / 3.0 s / 16):
        status_interval_sec      — round period (clamped 5..86400 s);
        status_probe_timeout_sec — timeout of a single probe (clamped 0.2..60 s);
        status_max_parallel      — ceiling of parallel probes per round
                                   (clamped 1..MAX_PARALLEL_LIMIT; v1.1.2 final).
    Corrupt values (non-numeric, bool) → default. Never raises.
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

    interval = int(_num(cfg.get("status_interval_sec"), DEFAULT_INTERVAL_SEC))
    interval = max(5, min(interval, 86400))
    timeout = _num(cfg.get("status_probe_timeout_sec"), PROBE_TIMEOUT_S)
    timeout = max(0.2, min(timeout, 60.0))
    # v1.1.2 final (task 2): ceiling of parallel probes — clamped as in the dialog (1..64)
    max_parallel = int(_num(cfg.get("status_max_parallel"), DEFAULT_MAX_PARALLEL))
    max_parallel = max(1, min(max_parallel, MAX_PARALLEL_LIMIT))
    return {"interval_sec": interval, "probe_timeout_sec": timeout,
            "max_parallel": max_parallel}


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


class _ProbeThread(QThread):
    """One check round: probes in parallel (ThreadPoolExecutor, v1.1.2 final),
    results — as they complete."""

    probed = Signal(str, str)  # (server_id, status)

    def __init__(self, targets, timeout: float = PROBE_TIMEOUT_S, parent=None,
                 cancel: "threading.Event | None" = None,
                 max_parallel: int = DEFAULT_MAX_PARALLEL):
        super().__init__(parent)
        self._targets = list(targets)  # [(id, host, port), ...]
        self._timeout = max(0.2, float(timeout))
        self._cancel = cancel
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
                    status = fut.result()
                except Exception:
                    status = STATUS_OFFLINE  # a probe must not crash the round
                if status is None:
                    continue  # probe cancelled before it started — no result (as before)
                self.probed.emit(futures[fut], status)

    def _probe_one(self, sid: str, host: str, port: int):
        """One probe in a pool worker (the network timeout is bounded by timeout).

        None — the round was cancelled BEFORE this probe started (the cancel flag was
        set while the probe was waiting for a worker): the node is assigned no result,
        the signal is not emitted — the same semantics as the sequential loop's
        "exit between nodes". Without this check cancellation would be useless: the
        submit loop hands all N tasks to the pool in microseconds, and the round would
        run out the whole ceil(N/mp) × timeout.
        """
        if self._cancel is not None and self._cancel.is_set():
            return None
        try:
            return probe_ssh(host, port, self._timeout)
        except Exception:
            return STATUS_OFFLINE  # a probe must not crash the round


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
        self._thread: _ProbeThread | None = None
        self._cancel = threading.Event()  # AUDIT v0.7.2 #5: cancel the current round

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

    def set_servers(self, servers):
        """Update the target list. `servers` — an iterable of (id, host, port)."""
        targets = []
        for sid, host, port in servers or ():
            if not sid or not host:
                continue  # without id/host the probe is meaningless
            try:
                p = int(port) if port else 22
            except (TypeError, ValueError):
                p = 22
            targets.append((sid, str(host).strip(), max(1, min(65535, p))))
        self._targets = targets

    def last_status(self, server_id: str) -> str:
        """The last determined status of the server ("" — never probed yet)."""
        return self._last_results.get(server_id, "")

    def start_round(self):
        """Start a check round. If the previous one is still running — do nothing."""
        if self._busy or not self._targets:
            return
        self._busy = True
        self._cancel.clear()  # new round — clear the previous round's cancel flag
        thread = _ProbeThread(self._targets, self._probe_timeout, parent=self,
                              cancel=self._cancel, max_parallel=self._max_parallel)
        results = []

        def _on_probed(sid: str, status: str):
            results.append((sid, status))
            self._last_results[sid] = status
            self.status_changed.emit(sid, status)

        def _on_done():
            self._busy = False
            if self._thread is thread:
                self._thread = None
            thread.deleteLater()
            # v1.1.2 final (task 3): the interval of the NEXT tick — for the current size
            # of the map (targets may have changed during the round: nodes added/removed).
            try:
                self._timer.setInterval(self.effective_interval_ms())
            except RuntimeError:
                pass  # Qt teardown — the timer's C++ object is already destroyed
            self.round_finished.emit(results)

        self._thread = thread
        thread.probed.connect(_on_probed)
        thread.finished.connect(_on_done)
        thread.start()

    def start(self):
        """Enable periodic checks + the first round a bit after startup.

        The first round via QTimer.singleShot(2000), not immediately: at app startup
        the event sequence is still unfolding, and in headless tests
        without an event loop the deferred call simply never happens (safe).
        """
        if not self._timer.isActive():
            self._timer.start()
            QTimer.singleShot(2000, self.start_round)

    def stop(self):
        """Stop the periodic checks and the current round.

        AUDIT v0.7.2 (high #5): an early return of the round is impossible — the cancel
        flag is set, the executor stops accepting new probes (the submitted ones
        run out their network timeout); then the thread is waited on with a margin of
        ceil(N/max_parallel) × timeout + 2 s (v1.1.2 final: the round is parallel —
        the margin used to be computed sequentially as N × timeout).
        """
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
