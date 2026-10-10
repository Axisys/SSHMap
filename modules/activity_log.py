# -*- coding: utf-8 -*-
"""The activity history the interface never kept (DOCUMENTATION.md §45): a bounded, memory-only ring
buffer of what just happened, filled by TWO thin taps that rewire no existing emitter.
  * the logging tap — ONE `logging.Handler` (`ActivityLogHandler`) installed by `modules/logger.py`
    beside the rotating file handler, so a module already calling `get_logger(__name__)` reaches the
    buffer for free;
  * the status-bar tap — `record_status_message()` from the ONE connection to `statusBar().messageChanged`
    and to `UndoStatusBar.offer_shown` (the Undo offer never travels through `messageChanged`).
Pinned: MEMORY ONLY (nothing is serialized — `sshmap.log` stays the durable record), BOUNDED
(`MAX_EVENTS = 200`), the line stays ENGLISH (the panel translates the chrome), a repeated fact is
ONE event with a counter (`REPEAT_WINDOW_S`), and NO secret can enter a record — the taps copy a
message and never inspect an object, which `tests/test_activity_panel.py` scans the call sites for.
Qt-free and import-safe (stdlib only — `modules/logger.py` imports it at startup); the UI half is `ui/activity_panel.py`, a QObject bridge to the GUI thread."""

import collections
import logging
import threading
import time

#: The hard bound of the ring. A history, not an archive: the panel shows what is
#: still relevant, and 200 lines cover several rounds of work on a busy map.
MAX_EVENTS = 200

#: The level the tap records. DEBUG stays in the file only: the panel is for facts a
#: user can act on, and the debug channel of this application is verbose (a missing
#: i18n key, a theme probe) — a ring of 200 debug lines would be a wall of noise.
ACTIVITY_LEVEL = logging.INFO

#: The two families of a record (the panel filters by level, this is what tells a
#: LOGGING line from a sentence the interface showed the user).
FAMILY_LOG = "log"
FAMILY_STATUS = "status"

#: The level shown for a status-bar message — it is not a logging level at all.
LEVEL_STATUS = "UI"

#: The source shown for a status-bar message (the second tap). English, like every
#: other event line: the chrome is translated, the LINES are not (the module docstring).
SOURCE_STATUS_BAR = "status bar"

#: The level filter keys of the panel (`ui/activity_panel.py` renders the captions).
LEVEL_KEYS = ("all", "info", "warning", "error", "status")

#: The stamp of a row — the DATE is part of it: a post-incident review reads a history,
#: and a clock time alone cannot say which day a line belongs to (the two panels share it).
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

#: The filter key of a logging level (the SECOND half of `matches_level`: the panel renders a
#: level CELL through the same vocabulary its filter uses).
LEVEL_FILTER_KEYS = {"INFO": "info", "WARNING": "warning", "ERROR": "error", "CRITICAL": "error"}

#: A repeat of the same fact inside this window is a COUNTER, not a new event.
REPEAT_WINDOW_S = 2.0


def stamp_text(timestamp, fmt: str = STAMP_FORMAT) -> str:
    """ONE timestamp → the row's stamp cell (the PURE renderer the two panels share). Never raises.

    A local time with the DATE in it: the activity ring and the Plugins window's session ring
    both list facts a reader returns to after the fact, and a bare clock time cannot say which
    day a line belongs to.
    """
    try:
        return time.strftime(fmt or STAMP_FORMAT, time.localtime(float(timestamp)))
    except (TypeError, ValueError, OSError):
        return ""


def level_key(event) -> str:
    """The panel's FILTER key of an event — the ONE mapping of a level onto that vocabulary.

    PURE, and the mirror image of `matches_level()`: the filter goes key → predicate, this goes
    event → key, so the cell a user reads and the filter that shows it can never spell a level
    differently. A status-bar message is its own family; an unknown logging level is "info".
    """
    if event is None:
        return "all"
    if str(getattr(event, "family", FAMILY_LOG)) == FAMILY_STATUS \
            or str(getattr(event, "level", "")) == LEVEL_STATUS:
        return "status"
    return LEVEL_FILTER_KEYS.get(str(getattr(event, "level", "")).upper(), "info")


class ActivityEvent:
    """One recorded fact.

    Deliberately a plain mutable object with a tiny surface (not a frozen dataclass):
    the buffer bumps `repeats` and re-stamps the position of the event it coalesced,
    and it does that under its own lock.

    Attributes:
        seq: the monotonic id (assigned by the buffer, newest = highest).
        timestamp: `time.time()` of the FIRST occurrence (a repeat keeps it: the row
            answers "when did this start", which is what a reader asks).
        level: a logging level name ("INFO"/"WARNING"/"ERROR") or `LEVEL_STATUS`.
        source: the short module name ("services.status_checker") or
            `SOURCE_STATUS_BAR`.
        message: the event text, English, one line.
        family: `FAMILY_LOG` or `FAMILY_STATUS`.
        repeats: how many times the same fact arrived in the window (>= 1).
    """

    __slots__ = ("seq", "timestamp", "level", "source", "message", "family", "repeats")

    def __init__(self, seq: int, timestamp: float, level: str, source: str,
                 message: str, family: str = FAMILY_LOG, repeats: int = 1):
        self.seq = int(seq)
        self.timestamp = float(timestamp)
        self.level = str(level)
        self.source = str(source or "")
        self.message = str(message)
        self.family = str(family or FAMILY_LOG)
        self.repeats = int(repeats)

    def time_text(self, fmt: str = STAMP_FORMAT) -> str:
        """The stamp of the event — DATE and clock (the panel's first column). Never raises."""
        return stamp_text(self.timestamp, fmt)

    def is_status(self) -> bool:
        """True for a status-bar message (the second tap)."""
        return self.family == FAMILY_STATUS

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return (f"ActivityEvent(seq={self.seq}, {self.level}, {self.source!r}, "
                f"{self.message!r}, repeats={self.repeats})")


class ActivityBuffer:
    """The bounded, thread-safe ring of `ActivityEvent`s (v1.5.2).

    Thread-safe on purpose: records arrive from the probe threads, the SFTP worker, the
    DNS resolver and the GUI thread. `append()` is the only writer; `events()` /
    `newest_first()` hand out COPIES, so a reader can never mutate the ring by accident.
    """

    def __init__(self, max_events: int = MAX_EVENTS):
        try:
            bound = int(max_events)
        except (TypeError, ValueError):
            bound = MAX_EVENTS
        self._max = max(1, bound)
        self._events = collections.deque(maxlen=self._max)
        self._lock = threading.RLock()
        self._seq = 0
        self._listeners = []

    # ── Reading ────────────────────────────────────────────────────────────────

    @property
    def max_events(self) -> int:
        """The bound — the ring never holds more than this (the ROADMAP acceptance)."""
        return self._max

    def events(self) -> list:
        """Every event, OLDEST first (a copy — the ring is not handed out)."""
        with self._lock:
            return list(self._events)

    def newest_first(self) -> list:
        """Every event, NEWEST first — the order the panel lists them in."""
        with self._lock:
            return list(reversed(self._events))

    def last(self):
        """The newest event, or None (the single item — the coalescing seam)."""
        with self._lock:
            return self._events[-1] if self._events else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    # ── Writing ────────────────────────────────────────────────────────────────

    def append(self, message, level: str = "INFO", source: str = "",
               family: str = FAMILY_LOG):
        """Record one fact; returns the event (None for an empty message).

        A repeat of the newest event — same family, level, source and text within
        `REPEAT_WINDOW_S` — bumps its counter instead of adding a row. The listeners
        are notified AFTER the lock is released: a listener that reads the buffer (or
        the panel that rebuilds its rows from it) must not deadlock against a worker
        thread that is appending.
        """
        text = str(message if message is not None else "").strip()
        if not text:
            return None
        now = time.time()
        with self._lock:
            newest = self._events[-1] if self._events else None
            if (newest is not None and newest.message == text
                    and newest.level == str(level) and newest.source == str(source or "")
                    and newest.family == str(family or FAMILY_LOG)
                    and (now - newest.timestamp) <= REPEAT_WINDOW_S):
                newest.repeats += 1
                event = newest
            else:
                self._seq += 1
                event = ActivityEvent(self._seq, now, level, source, text, family)
                self._events.append(event)   # the deque drops the oldest at the bound
            listeners = list(self._listeners)
        self._notify(listeners, event)
        return event

    def clear(self) -> None:
        """Drop the whole history (the panel's Clear) and notify the listeners."""
        with self._lock:
            self._events.clear()
            listeners = list(self._listeners)
        self._notify(listeners, None)

    # ── Listeners (the UI half) ────────────────────────────────────────────────

    def add_listener(self, callback) -> bool:
        """Register `callback(event)`; an event of `None` means "the ring changed".

        Called from the appending thread — a GUI listener must marshal (the
        `ui/activity_panel.py` bridge does it with a Signal).
        """
        if not callable(callback):
            return False
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
        return True

    def remove_listener(self, callback) -> bool:
        """Unregister a listener (the panel does it when it is destroyed)."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)
                return True
        return False

    def _notify(self, listeners, event) -> None:
        """Call every listener; a broken one must never break the appender."""
        for callback in listeners:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 — a listener is a consumer, not a gate
                pass


# ── The process-wide ring ─────────────────────────────────────────────────────
# ONE buffer per process (the ROADMAP task 1: "the SAME buffer"). The handler resolves
# it at EMIT time instead of holding a reference, so `reset_activity_buffer()` (the
# suite's seam) really swaps what the taps write into.

_BUFFER = ActivityBuffer()


def get_activity_buffer() -> ActivityBuffer:
    """The process-wide ring (never None — module-level state, the singleton rule)."""
    return _BUFFER


def reset_activity_buffer(max_events: int = MAX_EVENTS) -> ActivityBuffer:
    """Replace the ring with a fresh one and return it (the SUITE seam).

    The application never calls this. The topical test needs a clean ring per section,
    and the logger/tap resolve the buffer by name on every write, so a swap is enough —
    a listener registered on the OLD ring is simply gone with it.
    """
    global _BUFFER
    _BUFFER = ActivityBuffer(max_events)
    return _BUFFER


def _short_source(name) -> str:
    """`sshmap.services.status_checker` → `services.status_checker` (the Source column)."""
    text = str(name or "")
    for prefix in ("sshmap.",):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


class ActivityLogHandler(logging.Handler):
    """The logging tap: every record of the app's logger tree → the ring (v1.5.2).

    Attached to the `sshmap` logger by `modules/logger.py:setup_logging()` (beside the
    rotating file handler) and by `install_activity_handler()` — ONE seam, so no module
    has to know that a panel exists. `emit()` never raises and never formats a
    traceback: the event line is ONE line (the exception's type and text are appended
    when a record carries one).
    """

    def __init__(self, level: int = ACTIVITY_LEVEL):
        super().__init__(level)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            get_activity_buffer().append(self.event_text(record),
                                         level=record.levelname,
                                         source=_short_source(record.name),
                                         family=FAMILY_LOG)
        except Exception:  # noqa: BLE001 — a history tap must never break a log call
            pass

    @staticmethod
    def event_text(record: logging.LogRecord) -> str:
        """The ONE line of a record: its formatted message (+ the exception's short form)."""
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 — a broken format string of a foreign record
            text = str(getattr(record, "msg", ""))
        exc = getattr(record, "exc_info", None)
        if exc:
            try:
                exc_type, exc_value = exc[0], exc[1]
                name = getattr(exc_type, "__name__", "")
                text = f"{text} — {name}: {exc_value}" if text else f"{name}: {exc_value}"
            except Exception:  # noqa: BLE001 — a malformed exc_info tuple
                pass
        return str(text).strip()


def install_activity_handler(logger_name: str = "sshmap",
                             level: int = ACTIVITY_LEVEL):
    """Install the ONE logging tap on `logger_name` (idempotent); None when impossible.

    Called by `setup_logging()` in the application. A logger refuses to create a record
    at a level its effective configuration disallows, so the tap also makes sure the
    logger can HEAR it: the package logger is raised to DEBUG when it is stricter than
    `level` (the headless suite has no logging configuration at all, and a panel that
    silently misses INFO lines would be a lie). `setup_logging()` already sets DEBUG, so
    in the application this changes nothing.
    """
    try:
        target = logging.getLogger(logger_name)
    except Exception:  # noqa: BLE001 — logging itself failed: no tap
        return None
    for handler in list(target.handlers):
        if isinstance(handler, ActivityLogHandler):
            return handler
    handler = ActivityLogHandler(level)
    try:
        target.addHandler(handler)
        if not target.isEnabledFor(level):
            target.setLevel(logging.DEBUG)
    except Exception:  # noqa: BLE001 — a broken handler must not break the startup
        return None
    return handler


def record_status_message(text, source: str = SOURCE_STATUS_BAR):
    """The status-bar tap: one transient UI message → one history record (v1.5.2).

    Called from the ONE slot the window connects to `statusBar().messageChanged` (and
    to `UndoStatusBar.offer_shown`). An EMPTY text is not a fact — Qt emits
    `messageChanged("")` on every `clearMessage()`, which must not become a row.
    """
    message = str(text if text is not None else "").strip()
    if not message:
        return None
    return get_activity_buffer().append(message, level=LEVEL_STATUS, source=source,
                                        family=FAMILY_STATUS)


def matches_level(event, key) -> bool:
    """Does `event` pass the panel's level filter `key` (v1.5.2)?

    PURE, so the topical test pins the policy without a widget: `all` matches
    everything, `status` is the status-bar family, and the three logging keys match that
    family by level (a CRITICAL record counts as an ERROR — it is the same "something
    failed" question, and it must not be reachable only through "all"). A key that is
    NOT one of `LEVEL_KEYS` is a broken caller and hides NOTHING — a filter must never
    drop a row by accident.
    """
    if event is None:
        return False
    value = str(key or "all").lower()
    if value not in LEVEL_KEYS or value == "all":
        return True
    if value == "status":
        return event.family == FAMILY_STATUS
    if event.family != FAMILY_LOG:
        return False
    if value == "info":
        return event.level == "INFO"
    if value == "warning":
        return event.level == "WARNING"
    return event.level in ("ERROR", "CRITICAL")
