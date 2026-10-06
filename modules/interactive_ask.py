# -*- coding: utf-8 -*-
"""The ONE way a WORKER thread asks the GUI a question — `AGENTS.md` §4.4, §4.8.

A host key is verified and a private key is unlocked INSIDE `connect()`, i.e. on the thread that runs the
connection, while the answer belongs to a dialog on the GUI thread. `ask()` closes that gap: it builds an
`AskRequest`, hands it to the installed answerer through a QUEUED Qt signal and waits on the request's own
event with a BOUNDED budget (§4.8 — a deferred call guards itself, and nothing waits forever).

The surface is INSTALLED (`set_answerer()`) by the application entry point, `main.py`. Without one —
a headless run, a suite, an embedder — `ask()` answers `None` at once and every caller resolves that
through its own DECLARED fallback: the shipped TOFU accept for a new host key, an honest refusal for a
credential. Mechanism — `DOCUMENTATION.md` §16."""

import threading

#: The question kinds. The answerer renders a dialog per kind; a caller never inspects another's kind.
KIND_HOST_KEY = "host_key"                # a NEW host key — accept + pin, or reject
KIND_CHANGED_KEY = "changed_key"          # a CHANGED host key — replace the stored one, or refuse
KIND_KEY_PASSPHRASE = "key_passphrase"    # the passphrase of an encrypted private key
KIND_SECOND_FACTOR = "second_factor"      # the keyboard-interactive prompt of a server

#: The budget of ONE ask. Generous on purpose (a human is reading a dialog) and bounded: a GUI that died
#: mid-question must not park a connect thread for its lifetime.
DEFAULT_ASK_TIMEOUT_S = 120.0


def _log():
    """A lazy logger — the module must import without the application (`_log()` pattern of §4.4)."""
    try:
        from modules.logger import get_logger
        return get_logger("modules.interactive_ask")
    except Exception:  # noqa: BLE001
        return None


class AskRequest:
    """ONE question in flight: what is asked, who answered, and the event the asker waits on."""

    __slots__ = ("kind", "fields", "done", "result", "answered")

    def __init__(self, kind, fields=None):
        self.kind = kind
        self.fields = dict(fields or {})
        self.done = threading.Event()
        self.result = None
        self.answered = False

    def answer(self, value):
        """Publish the answer and wake the asker. The LAST answer wins; a second one is ignored."""
        if self.answered:
            return
        self.answered = True
        self.result = value
        self.done.set()

    def __repr__(self):  # pragma: no cover — diagnostics only
        return f"<AskRequest {self.kind} answered={self.answered} result={self.result!r}>"


#: The installed surface. `set_answerer(None)` restores the declared no-surface fallback.
_answerer = None
_answerer_lock = threading.Lock()


def set_answerer(fn) -> None:
    """Install the GUI answerer (`fn(request) -> value`). `None` un-installs it (tests, shutdown)."""
    global _answerer
    with _answerer_lock:
        _answerer = fn


def get_answerer():
    """The installed answerer, or None when no interactive surface exists in this process."""
    with _answerer_lock:
        return _answerer


def has_answerer() -> bool:
    """Is there an interactive surface? The ONE question a caller asks before promising a prompt."""
    return get_answerer() is not None


def _deliver(request, answerer=None):
    """Run the answerer for ONE request; a raising surface is an UNANSWERED question, never a crash."""
    fn = answerer if answerer is not None else get_answerer()
    if fn is None:
        return None
    try:
        return fn(request)
    except Exception:  # noqa: BLE001 — a broken dialog must not kill the connect thread
        log = _log()
        if log:
            log.exception("The interactive answerer failed for %r", request.kind)
        return None


# ── The Qt bridge ────────────────────────────────────────────────────────────
# The answerer runs on the GUI thread, so a request from a worker is HANDED OVER, not called: the signal
# is emitted on the worker and delivered to an object whose thread affinity IS the GUI thread (a signal
# to a plain callable would run in the EMITTING thread — `AGENTS.md` §7 gotcha #20).

_qt_types = None
_bridge = None


def _qt():
    """`(QObject, Signal, Slot, QCoreApplication, QThread)` — imported once, lazily, or None."""
    global _qt_types
    if _qt_types is None:
        try:
            from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot
            _qt_types = (QObject, Signal, Slot, QCoreApplication, QThread)
        except Exception:  # noqa: BLE001 — no Qt at all: the fallback is the only answer
            _qt_types = False
    return _qt_types or None


def _get_bridge():
    """The ONE bridge object, living in the GUI thread; None without Qt or without a QApplication."""
    global _bridge
    if _bridge is not None:
        return _bridge
    types = _qt()
    if types is None:
        return None
    QObject, Signal, Slot, QCoreApplication, QThread = types
    app = QCoreApplication.instance()
    if app is None:
        return None

    class _AskBridge(QObject):
        """Carries one request across the thread boundary; the answer runs in ITS thread."""

        asked = Signal(object)

        def __init__(self):
            super().__init__()
            self.asked.connect(self._handle)   # the receiver IS this object: queued by affinity

        @Slot(object)
        def _handle(self, request):
            request.answer(_deliver(request))

    bridge = _AskBridge()
    try:
        if QThread.currentThread() is not app.thread():
            bridge.moveToThread(app.thread())
    except Exception:  # noqa: BLE001 — a bridge in the wrong thread still answers directly
        pass
    _bridge = bridge
    return _bridge


def reset_bridge() -> None:
    """Drop the cached bridge (the suite's seam: a QApplication that died between two tests)."""
    global _bridge
    _bridge = None


def ask(kind, timeout=None, **fields):
    """Ask the installed surface ONE question and answer its value; None when nobody could answer.

    `None` is the ONE "no answer" value and it is deliberately NOT a rejection: the caller decides what
    an absent surface means for its own question (the shipped accept for a host key, a refusal for a
    credential). On the GUI thread — or without Qt — the answerer runs INLINE.
    """
    answerer = get_answerer()
    if answerer is None:
        return None
    request = AskRequest(kind, fields)
    types = _qt()
    if types is None:
        return _deliver(request, answerer)
    app = types[3].instance()
    if app is None or types[4].currentThread() is app.thread():
        return _deliver(request, answerer)
    bridge = _get_bridge()
    if bridge is None:
        return _deliver(request, answerer)
    try:
        bridge.asked.emit(request)
    except Exception:  # noqa: BLE001 — a deleted bridge: answer inline rather than hang
        return _deliver(request, answerer)
    budget = DEFAULT_ASK_TIMEOUT_S if timeout is None else float(timeout)
    if not request.done.wait(budget):
        log = _log()
        if log:
            log.error("No answer for %r within %.0f s — the caller's fallback applies",
                      request.kind, budget)
        return None
    return request.result
