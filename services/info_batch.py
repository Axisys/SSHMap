# -*- coding: utf-8 -*-
"""v1.5.3 (ROADMAP task 2): collect the system info of MANY nodes at once.

Until this release the application could ask ONE server for its hardware
(`MainWindow._collect_node_info` → `SystemInfoCollector`, one QThread per node) and the
only automatic fill happened after a successful connect. A hundred-node map therefore had
no way to answer "refresh everything", which is the question the freshness work of the
same release asks out loud.

`InfoBatch` is that missing layer and it is deliberately HEADLESS (no window, no i18n, no
scene): it owns a **bounded queue** with a **parallelism cap** — the `StatusChecker`
pattern (`ThreadPoolExecutor` there, a queue of live QThreads here, because a collector
IS a QThread) — plus the per-node guard the single-node path already had
(`MainWindow._info_collectors`). Facts it guarantees:

* at most `max_parallel` collectors run at once; the rest WAIT in the queue;
* a node that is already being collected is SKIPPED, never collected twice in parallel;
* one node's failure never stops the others (`node_failed` is a report, not an abort);
* `cancel()` stops everything that has not started yet (a running collector is one
  unauthenticated-free SSH session with a bounded wait — `SystemInfoCollector.stop()` —
  so it is allowed to run out and its result is still reported);
* the outcome is ONE summary (`batch_log_line`) plus per-node signals, so the caller can
  put a live progress line in the status bar and a final sentence naming the failures.

The module is Qt-light (QObject + signals, no widgets) and free of i18n: the LOG line is
English (the log-file policy), and the user-facing sentences are composed by the window
from the counts this class reports.
"""
from typing import Dict, List, Tuple

from PySide6.QtCore import QObject, Signal

try:  # the logging tap of v1.5.2 — the batch summary reaches the activity ring
    from modules.logger import get_logger
except ImportError:  # pragma: no cover — the package layout (sshmap.services.*)
    from ..modules.logger import get_logger

log = get_logger(__name__)

#: The default ceiling of parallel collectors. Four is a deliberate number: a collector
#: opens a real SSH session and runs a command batch, so it is an order of magnitude
#: heavier than a status probe (whose cap is `status_max_parallel`, default 16). A map of
#: 200 nodes costs ceil(200/4) × the per-node time instead of 200 sessions at once.
DEFAULT_MAX_PARALLEL = 4
MIN_PARALLEL = 1
MAX_PARALLEL_LIMIT = 16          # the clamp ceiling (and the settings-dialog range, if one ever exists)

#: The optional config key (`~/.sshmap/config.json`). NOT a settings-hub key: it belongs to
#: the same family as `status_max_parallel` (a performance knob with a sane default), but a
#: hub row for it is not part of this release — the reader accepts the key and clamps it.
CONFIG_KEY = "info_max_parallel"

#: How many failing aliases a summary NAMES before it says "+N more" (a status-bar line
#: must stay readable; the full list is in the log record).
FAILED_NAMES_LIMIT = 3


def get_batch_settings() -> dict:
    """The batch settings from `~/.sshmap/config.json` (never raises).

    `{"max_parallel": int}` — the key is OPTIONAL (missing / broken → 4, clamped
    1..`MAX_PARALLEL_LIMIT`). The reader mirrors `status_checker.get_status_settings()`:
    a broken config may cost performance, never a startup.
    """
    cfg: dict = {}
    try:
        from i18n import load_config
        cfg = load_config() or {}
    except Exception:  # noqa: BLE001 — the config is optional, the default matters more
        pass
    value = cfg.get(CONFIG_KEY)
    if isinstance(value, bool) or value is None:
        value = DEFAULT_MAX_PARALLEL
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = DEFAULT_MAX_PARALLEL
    return {"max_parallel": max(MIN_PARALLEL, min(number, MAX_PARALLEL_LIMIT))}


def failed_alias_list(failures, limit: int = FAILED_NAMES_LIMIT) -> str:
    """The names of the failed nodes, bounded: `"web-2, db-1, +2 more"` (PURE).

    `failures` — an iterable of `(sid, alias, error)`. The window plugs the result into
    `status.info_batch_failed`; an empty list yields an empty string (the caller then
    shows the success sentence alone).
    """
    names: List[str] = []
    for item in failures or ():
        try:
            alias = str(item[1] or item[0] or "?").strip()
        except (IndexError, TypeError):
            continue
        names.append(alias or "?")
    if not names:
        return ""
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = FAILED_NAMES_LIMIT
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f", +{len(names) - limit} more"


def batch_log_line(ok_count: int, total: int, failures=(), skipped: int = 0) -> str:
    """The ONE English line a finished batch leaves in the log / activity ring (PURE).

    Examples:

        "Info batch: 5 of 5 collected"
        "Info batch: 3 of 5 collected — failed: db-1 (auth failed), web-2 (timed out)"
        "Info batch: 2 of 4 collected — failed: db-1 (auth failed); 1 already running"
        "Info batch: 0 of 2 collected — cancelled before the first node started"

    A summary on purpose (the v1.5.2 rule): the per-node values are already on the cards,
    and a hundred-node batch must not turn into a hundred log lines.
    """
    try:
        ok_count = max(0, int(ok_count))
        total = max(0, int(total))
    except (TypeError, ValueError):
        ok_count, total = 0, 0
    parts = [f"Info batch: {ok_count} of {total} collected"]
    named = []
    for item in failures or ():
        try:
            alias = str(item[1] or item[0] or "?").strip() or "?"
            error = str(item[2] or "").strip()
        except (IndexError, TypeError):
            continue
        named.append(f"{alias} ({error})" if error else alias)
    if named:
        parts.append("failed: " + ", ".join(named))
    if skipped:
        parts.append(f"{int(skipped)} already running")
    if total == 0:
        parts.append("nothing to collect")
    return " — ".join(parts) if len(parts) > 1 else parts[0]


class InfoBatch(QObject):
    """A bounded queue of `SystemInfoCollector` runs — many nodes, one action (v1.5.3).

    Signals:
        progress(done, total, alias) — one node settled (ok or failed); `total` counts the
            nodes the batch ACCEPTED, so the progress line is honest from the first tick;
        node_ready(sid, info)        — a collector reported values (the window writes them);
        node_failed(sid, alias, err) — a collector reported a failure (the others continue);
        finished(ok, failures, cancelled) — the queue is empty and nothing runs any more;
            `failures` is `[(sid, alias, error), …]` and `cancelled` counts the nodes
            `cancel()` stopped before they started (they produced no result at all).

    The collector objects are created by the injected `collector_factory(data)`, registered
    through the optional `on_started(collector)` hook (the window's `_info_collectors`
    registry — the per-node guard AND the shutdown wait) and started on the GUI thread; the
    factory default is the real `SystemInfoCollector`, so production code passes nothing.
    """

    progress = Signal(int, int, str)
    node_ready = Signal(str, dict)
    node_failed = Signal(str, str, str)
    finished = Signal(int, list, int)

    def __init__(self, collector_factory=None, on_started=None, is_busy=None,
                 max_parallel: int = DEFAULT_MAX_PARALLEL, parent=None):
        super().__init__(parent)
        self._factory = collector_factory or _default_collector_factory
        self._on_started = on_started if callable(on_started) else None
        self._is_busy = is_busy if callable(is_busy) else None
        self._max_parallel = self._clamp(max_parallel)
        self._queue: List[Tuple[str, str, object]] = []
        self._running: Dict[str, object] = {}
        self._seen: set = set()
        self._aliases: Dict[str, str] = {}
        self._results: Dict[str, Tuple[bool, str]] = {}
        self._total = 0
        self._done = 0
        self._ok = 0
        self._failures: List[Tuple[str, str, str]] = []
        self._cancelled = 0
        self._skipped = 0
        self._running_flag = False

    @staticmethod
    def _clamp(value) -> int:
        if isinstance(value, bool) or value is None:
            return DEFAULT_MAX_PARALLEL
        try:
            number = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_PARALLEL
        return max(MIN_PARALLEL, min(number, MAX_PARALLEL_LIMIT))

    # ── state ──────────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Is a batch being worked on (queued or running)?"""
        return bool(self._running_flag)

    @property
    def total(self) -> int:
        """How many nodes this batch accepted (the denominator of the progress line)."""
        return int(self._total)

    @property
    def done(self) -> int:
        """How many accepted nodes have settled (ok or failed)."""
        return int(self._done)

    @property
    def running_count(self) -> int:
        """How many collectors are running right now (never above `max_parallel`)."""
        return len(self._running)

    @property
    def max_parallel(self) -> int:
        """The ceiling this batch obeys (clamped 1..`MAX_PARALLEL_LIMIT`)."""
        return int(self._max_parallel)

    def set_max_parallel(self, value) -> None:
        """Change the ceiling for the NEXT tick (the running collectors are untouched)."""
        self._max_parallel = self._clamp(value)

    # ── the queue ──────────────────────────────────────────────────────────────

    def start(self, items) -> int:
        """Queue `[(sid, alias, data), …]` and start as many collectors as the cap allows.

        Returns how many nodes were ACCEPTED. A node already collected by this batch or
        already running in the window's registry (`is_busy`) is skipped — the per-node
        guard of the task, so "collect the selection" twice cannot double-probe a host.
        A batch that is already running simply grows its queue; `finished` fires when the
        LAST node settles.
        """
        accepted = 0
        skipped = 0
        # A NEW batch session (nothing queued, nothing running) starts from a clean slate:
        # the counters describe THIS action, and the `_seen` set ("a node is collected once
        # per batch") is about the run, not about the lifetime of the object — the window
        # keeps ONE InfoBatch, and a second "gather information" click must not be answered
        # with "already collected" from the previous action.
        if not self._running_flag and not self._queue and not self._running:
            self._reset_session()
        for raw in items or ():
            try:
                sid, alias, data = raw[0], raw[1], raw[2]
            except (IndexError, TypeError):
                continue
            sid = str(sid or "")
            if not sid or sid in self._seen:
                continue
            self._seen.add(sid)
            busy = False
            if self._is_busy is not None:
                try:
                    busy = bool(self._is_busy(sid))
                except Exception:  # noqa: BLE001 — a broken guard must not stop the batch
                    busy = False
            if busy:
                skipped += 1
                continue
            alias = str(alias or sid)
            self._aliases[sid] = alias
            self._queue.append((sid, alias, data))
            accepted += 1
        self._total += accepted
        self._skipped += skipped
        if accepted:
            self._running_flag = True
        self._pump()
        return accepted

    def _reset_session(self) -> None:
        """Forget the previous batch session's bookkeeping (counters + the per-run `_seen`)."""
        self._seen.clear()
        self._aliases.clear()
        self._results.clear()
        self._failures = []
        self._total = 0
        self._done = 0
        self._ok = 0
        self._cancelled = 0
        self._skipped = 0

    def _pump(self):
        """Start collectors while the cap allows and the queue has work."""
        while self._queue and len(self._running) < self._max_parallel:
            sid, alias, data = self._queue.pop(0)
            try:
                collector = self._factory(data)
            except Exception as exc:  # noqa: BLE001 — a factory failure is that node's failure
                self._settle(sid, alias, False, str(exc))
                continue
            try:
                collector.info_ready.connect(
                    lambda _sid, info, _c=collector: self._on_ready(_sid, info, _c))
                collector.info_failed.connect(
                    lambda _sid, error, _c=collector: self._on_failed(_sid, error, _c))
                collector.finished.connect(
                    lambda _c=collector, _sid=sid: self._on_collector_finished(_c, _sid))
            except (AttributeError, RuntimeError) as exc:
                self._settle(sid, alias, False, f"collector signals unavailable: {exc}")
                continue
            self._running[sid] = collector
            if self._on_started is not None:
                try:
                    self._on_started(collector)
                except Exception:  # noqa: BLE001 — registration is bookkeeping
                    pass
            try:
                collector.start()
            except Exception as exc:  # noqa: BLE001 — a collector that cannot start fails
                self._settle(sid, alias, False, str(exc))

    def _on_ready(self, sid: str, info, collector):
        """A collector answered with values — remember it; the queue moves on its finish."""
        sid = str(sid)
        self._results[sid] = (True, "")
        self.node_ready.emit(sid, dict(info or {}))

    def _on_failed(self, sid: str, error, collector):
        """A collector answered with an error — a report, never an abort."""
        sid = str(sid)
        self._results[sid] = (False, str(error or ""))
        self.node_failed.emit(sid, self._alias_of(sid), str(error or ""))

    def _on_collector_finished(self, collector, sid):
        """One collector is done: drop it, count it, pump the queue, maybe finish."""
        sid = str(sid)
        ok, error = self._results.pop(sid, (False, "no result"))
        self._settle(sid, self._alias_of(sid), ok, error)

    def _settle(self, sid: str, alias: str, succeeded, error: str):
        """Finish ONE node: bookkeeping + the progress signal (+ the final summary)."""
        sid = str(sid)
        self._running.pop(sid, None)
        self._results.pop(sid, None)
        self._done += 1
        if succeeded:
            self._ok += 1
        else:
            self._failures.append((sid, alias, str(error or "")))
        self.progress.emit(self._done, self._total, alias)
        self._pump()
        self._maybe_finish()

    def _maybe_finish(self):
        if self._queue or self._running:
            return
        if not self._running_flag:
            return
        self._running_flag = False
        self._emit_log()
        self.finished.emit(int(self._ok), list(self._failures), int(self._cancelled))

    def _emit_log(self):
        """Write the ONE summary line (the v1.5.2 activity tap picks it up)."""
        try:
            log.info(batch_log_line(self._ok, self._total, self._failures, self._skipped))
        except Exception:  # noqa: BLE001 — a summary is a side channel
            pass

    def _alias_of(self, sid: str) -> str:
        """The alias of a node of THIS batch (the sid itself when it is unknown)."""
        return str(self._aliases.get(str(sid)) or sid)

    def cancel(self) -> int:
        """Stop everything that has NOT started yet. Returns the number of dropped nodes.

        A running collector has no cancel flag of its own (`SystemInfoCollector` is a
        one-shot thread with a bounded `stop()`), so it is allowed to finish and its
        result is still reported — the acceptance is "cancelling stops everything not yet
        started", and that is exactly what this does.
        """
        dropped = len(self._queue)
        self._queue.clear()
        self._cancelled += dropped
        self._maybe_finish()
        return dropped

    def shutdown(self, wait_ms: int = 3000) -> None:
        """Cancel the queue and wait (bounded) for the RUNNING collectors (window close).

        The collectors are also reachable through the window's `_info_collectors` registry,
        which `_shutdown_background_threads()` waits for; this is the batch's own half, so
        the object is never destroyed under a live QThread.
        """
        self.cancel()
        for collector in list(self._running.values()):
            stop = getattr(collector, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:  # noqa: BLE001 — a teardown path never raises
                    pass
            wait = getattr(collector, "wait", None)
            if callable(wait):
                try:
                    wait(int(wait_ms))
                except Exception:  # noqa: BLE001 — see above
                    pass
        self._running.clear()
        self._running_flag = False


def _default_collector_factory(data):
    """The production factory: the ordinary `SystemInfoCollector` (lazy import)."""
    try:
        from services.system_info_collector import SystemInfoCollector
    except ImportError:  # pragma: no cover — the package layout
        from ..services.system_info_collector import SystemInfoCollector
    return SystemInfoCollector(data, password="")
