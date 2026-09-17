# -*- coding: utf-8 -*-
"""v1.2.3 (ROADMAP v1.2.3): Multi-input — broadcast of the active session's input to all other open sessions.

Single input point (architecture with no refactoring): **all** user input
goes through `TerminalWidget.keyPressEvent()` → `_send(bytes)` →
`terminal_thread.send_data()`. The hub is attached exactly to this point: when
the mode is enabled, `_send` sends the same bytes to `send_data()` of all other
live sessions in the registry (v1.2 — `MainWindow._terminal_windows` holds
TerminalSessionPage). Ctrl+V (bracketed paste) goes through the same `_send` —
it is duplicated too (otherwise the "typed" text would not appear everywhere).

The source — only the focused window/tab: the bytes come from the keyboard of
the focused widget, not from output — there is no echo by definition (broadcast
does not re-transmit foreign output and does not send back to the source). A
session that died during typing (error → close) is removed from the registry
the standard way (`_forget_terminal_window` on `destroyed`), and broadcast
additionally filters threads by liveness — a dead channel receives no bytes.

UI (MainWindow/SshMixin): a checkable QAction in the "View" menu + F12 — EXIT
the mode (not Esc: Esc goes to the shell as \\x1b!) — when the mode is enabled
the RC2 mapping F12→\\x1b[24~ is suspended (the key does not reach the shell),
when disabled F12 works as before; a "MULTI: N sessions" badge in the status bar
with an exit button; highlight — tab badges "MULTI · <alias>" + a container
frame (apply_container_highlight, windows and dock).

Test seams: an explicit `multi_hub` in the TerminalWidget constructor (isolation
from the module hub); `hub.reset()` — state reset between sections of a test file.

Diagnostics (v1.2.4-fix, the "manual test did not confirm broadcast" incident):
a mode state change → INFO in the application log; each broadcast → a DEBUG line
(in TerminalWidget._send); the mode is enabled but the bytes went nowhere
(empty registry / all threads dead) → a rate-limited WARNING with details —
visible in the console too.
"""

import time

try:  # v1.2.5: central theme (ui/theme.py — pure data, no PySide6)
    from ..ui import theme
except ImportError:
    from ui import theme

_t_cache = None


def get_translator():
    """Safe i18n helper — returns the cached translator or a fallback (as in ssh_terminal)."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache


# ── Highlight: the "MULTI" frame/badge color + the frame objectName (QSS selector) ─────
# v1.2.5: the amber accent — from the central theme (the same one as node/group selection);
# the MULTI_ACCENT name is kept (used in the MainWindow status-bar badge QSS).
MULTI_ACCENT = theme.SELECTION_AMBER              # amber — the mode frame/badge
MULTI_FRAME_OBJECT_NAME = "sshmap_multi_frame"    # QSS selector for the container only


def _thread_alive(thread) -> bool:
    """Is the terminal thread alive for broadcasting (ROADMAP v1.2.3, task 4).

    Alive — the channel is open (a real SSHTerminalThread during a session) OR the
    thread is still running (QThread.isRunning()). Dead: a closed channel
    (error → close, stop()) — no bytes are sent to it. A test double without
    channel/isRunning counts as alive (its send_data() is safe). Never raises."""
    try:
        ch = getattr(thread, "channel", None)
        if ch is not None and not bool(getattr(ch, "closed", False)):
            return True
        is_running = getattr(thread, "isRunning", None)
        if callable(is_running):
            return bool(is_running())
        return True
    except Exception:
        return False


class MultiInputHub:
    """The multi-input mode state + broadcast of input to all open sessions.

    `provider` — callable() → list of open sessions (the v1.2 registry:
    TerminalSessionPage objects with `.terminal_thread` and `.widget`); None —
    broadcast disabled.
    `listeners` — UI callbacks (active: bool) on a state change (MainWindow:
    QAction, the status-bar badge, container highlight, status message). One
    process — one hub (get_hub()); TerminalWidget takes it by default.
    """

    def __init__(self):
        self._active = False
        self._provider = None
        self._listeners = []
        # v1.2.4-fix: rate-limited WARNING "0 receivers" (do not spam on every key)
        self._last_zero_warn = 0.0

    # ── mode state ────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return self._active

    @property
    def session_provider(self):
        return self._provider

    def set_session_provider(self, provider):
        """The open-sessions registry (callable() → list[page]); None — broadcast disabled."""
        self._provider = provider

    def add_listener(self, callback):
        """A UI callback (active: bool) on a state change; idempotent."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback):
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass  # was not connected — nothing to do

    def set_active(self, on: bool):
        """Toggle the mode on/off; listeners are notified ONLY on a real change.

        Diagnostics (v1.2.4-fix): a state change is logged at INFO — in the log
        file (~/.sshmap/logs/sshmap.log) you can see whether the mode was ENABLED
        and when it was disabled (F12 / menu / the badge ✕ button). Never raises."""
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        try:
            from modules.logger import get_logger as _get_log
            _get_log("modules.multi_input").info(
                f"Multi-input mode {'enabled' if on else 'disabled'}")
        except Exception:
            pass  # the logger is unavailable — the state change matters more than logging it
        for cb in list(self._listeners):
            try:
                cb(on)
            except Exception:
                pass  # a UI callback under teardown must not break the state change

    def toggle(self) -> bool:
        """Toggle the mode; returns the new state."""
        self.set_active(not self._active)
        return self._active

    # ── broadcast (the single input point) ────────────────────────────────
    def broadcast(self, data: bytes, source_widget=None) -> int:
        """The same bytes — to send_data() of all other live sessions in the registry.

        source_widget — the TerminalWidget the bytes came from (the focused
        window/tab): its session is skipped (it already received them via
        _send). Returns the number of receivers. Never raises: a dead
        C++ object/thread in the registry is silently skipped (the registry
        itself is updated by the standard teardown — destroyed →
        _forget_terminal_window), the other sessions keep receiving input."""
        if not data or self._provider is None:
            return 0
        try:
            pages = list(self._provider())
        except Exception:
            return 0
        sent = 0
        others = 0   # sessions besides the source (for the "0 receivers" diagnostic)
        dead = 0     # of those — dead threads/channels
        for page in pages:
            try:
                widget = getattr(page, "widget", None)
                if widget is not None and widget is source_widget:
                    continue  # the source — the focused window/tab (already received it)
                others += 1
                thread = getattr(page, "terminal_thread", None)
                if thread is None or not _thread_alive(thread):
                    dead += 1
                    continue  # a dead session (error → close) — do not send into a dead channel
                thread.send_data(data)
                sent += 1
            except Exception:
                continue  # a C++ object under teardown — skip it, the others receive it
        if sent == 0 and others > 0:
            self._warn_zero_receivers(others, dead)
        return sent

    def _warn_zero_receivers(self, others: int, dead: int):
        """v1.2.4-fix (diagnostics): the mode is enabled but the bytes went nowhere.

        This is the silent-failure scenario of the "I type — nothing in the second
        terminal" manual test: a WARNING (visible in the console too) with details —
        how many sessions are in the registry besides the source and how many of them
        are dead. Rate-limited to 5 s so fast typing does not spam the log; never
        raises."""
        now = time.monotonic()
        if now - self._last_zero_warn < 5.0:
            return
        self._last_zero_warn = now
        try:
            from modules.logger import get_logger as _get_log
            _get_log("modules.multi_input").warning(
                f"multi-input: active but 0 receivers "
                f"(other sessions={others}, dead threads={dead}) — "
                f"input is NOT being duplicated")
        except Exception:
            pass  # the logger is unavailable — the broadcast matters more than logging it

    def reset(self):
        """Test seam: a full state reset (mode disabled, no registry)."""
        self._active = False
        self._provider = None
        self._listeners = []
        self._last_zero_warn = 0.0


# ── Application singleton ───────────────────────────────────────────────────────
# MainWindow and TerminalWidget use ONE hub: the widget takes it by default when
# no explicit multi_hub was passed in the constructor. One process — one hub.
_default_hub = MultiInputHub()


def get_hub() -> MultiInputHub:
    """The default multi-input hub (a process singleton)."""
    return _default_hub


# ── Container highlight for sessions (frame + tab badges "MULTI") ─────────────

def apply_container_highlight(host, on: bool) -> bool:
    """Highlight/reset the sessions container (SSHTerminalWindow / TerminalDockContent).

    Both containers have `session_tabs` (a QTabWidget of pages with
    `.server_data.alias`) — duck-typing without importing ssh_terminal/
    terminal_dock (no cycle). On entry: tab badges "MULTI · <alias>" + a QTabWidget
    frame (objectName selector, so the page's INNER tabs [Terminal|Files] are not
    touched); for the window — the title prefix `terminal.multi_title_prefix`
    (the base is stored in `_multi_base_title`). On exit — everything is reset.
    Idempotent; a RuntimeError of a dead C++ object does not propagate
    (teardown robustness). True — applied."""
    try:
        tabs = getattr(host, "session_tabs", None)
        if tabs is None:
            return False
        t = get_translator()
        for i in range(tabs.count()):
            try:
                page = tabs.widget(i)
                alias = getattr(getattr(page, "server_data", None), "alias", "?")
            except RuntimeError:
                continue  # C++ object already deleted (close race) — skip the tab
            try:
                text = t("terminal.multi_tab_badge", alias=alias) if on else str(alias)
                tabs.setTabText(i, text)
            except RuntimeError:
                pass  # C++ object already deleted (close race) — the badge is not critical
        try:
            if on:
                tabs.setObjectName(MULTI_FRAME_OBJECT_NAME)
                tabs.setStyleSheet(
                    f"QTabWidget#{MULTI_FRAME_OBJECT_NAME} "
                    f"{{ border: 2px solid {MULTI_ACCENT}; }}")
            else:
                tabs.setObjectName("")   # symmetric reset: the frame selector is fully removed
                tabs.setStyleSheet("")
        except RuntimeError:
            pass  # C++ object already deleted (close race) — the frame is not critical
        base_title = getattr(host, "_multi_base_title", None)
        if base_title is not None:
            try:
                title = (t("terminal.multi_title_prefix") + base_title) if on else base_title
                host.setWindowTitle(title)
            except RuntimeError:
                pass  # C++ object already deleted (close race) — the title is not critical
        return True
    except Exception:
        return False
