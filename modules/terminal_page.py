# -*- coding: utf-8 -*-
"""v1.2 (ROADMAP v1.2): TerminalSessionPage — an SSH session as a reusable widget.

Refactor "window → page": the whole session (terminal thread + pyte screen +
terminal canvas + status line + SFTP tab) was moved out of SSHTerminalWindow
into a QWidget that does not know about QMainWindow. The terminal window became
a thin wrapper (WA_DeleteOnClose, title, geometry — see modules/ssh_terminal.py),
and on this page the rest of the v1.2.x series is built: tabs in one window
(v1.2.1) and a dock in the map window (v1.2.2).

A single teardown method — `shutdown()` (idempotent): every teardown path
(window close, session error, MainWindow shutdown, the "4 own terminals" limit)
goes through it. The deliberate v1.1.x guards are kept:
  * the PTY debounce timer is stopped FIRST (resize_pty shrieks into a dead channel);
  * the SFTP worker is disconnected and stopped BEFORE the terminal thread (it
    depends on the thread's transport); a worker wait that does not finish goes
    to the orphan worker registry;
  * the thread's signals are disconnected from the page, then stop() + wait(1500);
    a thread that outlives the wait (paramiko blocks up to ~15 s on connect) goes
    to the module-level orphan thread registry `_orphan_threads` (v1.1.2RC1 N4) —
    a live QThread without a QObject parent must not be left to GC;
  * RuntimeError on C++ objects does not block the close (teardown robustness).

Bridge to the host (window/dock): the Qt signals `status_message`/`progress_*` —
the page does NOT know where they go. In `windows` mode SSHTerminalWindow attaches
them to its status bar and QProgressBar — the display is identical to v1.1.x.
**v1.4.7 follow-up (the maintainer's request): the page stopped drawing its own
status line** — it duplicated in a row of the session the text the host's status
bar was already showing. Every status write goes through ONE method
(`_set_status_text`) into `session_status` + the bridge, so the host is the single
status surface and the split pane's state becomes a SECOND text of the same bar.

Test seams (the v1.1.4 host_attr pattern): the thread class and QMessageBox are
fetched from the ssh_terminal module at call time — monkeypatching
`ST.SSHTerminalThread`/`ST.QMessageBox.question` in tests works unchanged.
"""

import time

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget

try:
    from .terminal_screen import TerminalScreen
except ImportError:
    from modules.terminal_screen import TerminalScreen

try:
    from .terminal_widget import TerminalWidget
except ImportError:
    from modules.terminal_widget import TerminalWidget

try:
    from .sftp_worker import OP_KINDS, SftpWorker, register_orphan_sftp_worker
except ImportError:
    from modules.sftp_worker import OP_KINDS, SftpWorker, register_orphan_sftp_worker

try:
    from .sftp_tab import SftpTab, format_size
except ImportError:
    from modules.sftp_tab import SftpTab, format_size

try:  # v1.5.7 (ROADMAP task 1): the per-server COMMAND history (the third tab)
    from .command_history import CommandHistoryPanel, CommandHistoryStore
except ImportError:
    from modules.command_history import CommandHistoryPanel, CommandHistoryStore

try:  # v1.2.5: the central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None


def _st_module():
    """The ssh_terminal module at call time (a test seam for attribute substitution).

    Lazy import: terminal_page does not import ssh_terminal at module level
    (SSHTerminalWindow imports THIS module — a direct import would create a cycle
    when starting from terminal_page).
    """
    try:
        from . import ssh_terminal as _st
    except ImportError:
        import ssh_terminal as _st
    return _st


def get_translator():
    """Safe i18n helper — returns cached translator or fallback (as in ssh_terminal)."""
    mod = _st_module()
    return mod.get_translator()


def _log():
    """The app logger (lazy — the command_history / terminal_widget pattern).

    v1.5.7: the output path uses it for a FEED FAILURE — a swallowed emulator error used to
    cost the repaint silently, and silence is what made the symptom unguessable from outside.
    """
    try:
        from modules.logger import get_logger as _gl
        return _gl("modules.terminal_page")
    except Exception:
        return None


# ── v1.3.3.4 (ROADMAP task 6): the transfer rate / ETA — the detachable task 7 of
# v1.3.3.2, which its own changelog handed to this version. Two pure helpers ARE the
# whole computation: the formatting of a duration and a sliding-window meter fed by
# the progress signals of the SFTP worker (the sftp.progress line itself is unchanged
# — the rate/ETA is appended to it, so a broken/absent measurement is invisible).

def format_duration(seconds) -> str:
    """A duration in seconds → "M:SS" / "H:MM:SS" ("" — no usable value).

    A pure function (unit-tested without a GUI): the ETA is derived from measured
    throughput and is therefore an estimate — it is rendered as a plain clock
    reading, never as "about N minutes" (no word forms to translate).
    """
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class TransferMeter:
    """v1.3.3.4 (ROADMAP task 6): the throughput (bytes/s) and the ETA of one SFTP task.

    A SLIDING WINDOW of (time, bytes-done) samples (default 4 s): the average since
    the start of a 100 MB transfer is useless after a stall, while the average over
    the last few seconds follows the link. The clock is injectable (`clock=`) — the
    tests drive the meter without sleeping. `update()` returns (rate, eta) or None
    while there is nothing honest to show (a single sample, a zero/negative delta
    between the samples, a stalled transfer); an unknown total gives (rate, None),
    so a rate can still be displayed.
    """

    WINDOW_SEC = 4.0     # how far back the rate is measured
    MIN_SAMPLES = 2      # one sample is not a measurement

    def __init__(self, clock=time.monotonic, window_sec: float = None):
        self._clock = clock
        self._window = self.WINDOW_SEC if window_sec is None else float(window_sec)
        self._samples = []       # [(t, done)] — oldest first

    def update(self, done: int, total: int, now: float = None):
        """Feed one progress sample → (bytes_per_sec, eta_seconds | None), or None."""
        t = self._clock() if now is None else float(now)
        done = int(done)
        total = int(total) if total else 0
        self._samples.append((t, done))
        while len(self._samples) > self.MIN_SAMPLES and t - self._samples[0][0] > self._window:
            self._samples.pop(0)
        if len(self._samples) < self.MIN_SAMPLES:
            return None
        t0, d0 = self._samples[0]
        dt = t - t0
        moved = done - d0
        if dt <= 0 or moved <= 0:
            return None      # no time passed / nothing moved — a rate would be a guess
        rate = moved / dt
        eta = ((total - done) / rate) if (total > done and rate > 0) else None
        return rate, eta

    def reset(self):
        """Forget the samples (a new task on the same id / a finished transfer)."""
        self._samples = []


class TerminalSessionPage(QWidget):
    """v1.2: an SSH session as a reusable widget.

    Composition: terminal_thread (SSHTerminalThread) + tscreen (TerminalScreen) +
    widget (TerminalWidget, the canvas) + a QTabWidget [Terminal | Files | History]
    (SftpTab, a lazy worker; CommandHistoryPanel, the per-server command history) +
    the history STORE of this server. The terminal_* config is read from config.json at
    creation time (load_terminal_settings — defaults = the v1.0 behaviour).

    The host (SSHTerminalWindow / a future dock) creates the page with a parent
    and may:
      * attach the bridge signals status_message/progress_* to its own UI — **the
        HOST's status surface is the ONE place a session state is rendered**
        (the v1.4.7 follow-up: the page's own status line is a hidden label now);
      * call set_host_window(w) — close_terminal() will close this session's tab
        on the host (v1.2.1: the last tab closes the window);
      * run the teardown through shutdown() (a single method, idempotent).

    v1.3.3.5 (the terminal SPLIT): `with_sftp=False` builds a page WITHOUT the SFTP
    tab — the split pane is a command line (see __init__): `tabs` then holds the
    canvas alone and `sftp_tab` is None. The default (True) is every other caller —
    tabs and the dock are untouched. v1.4.7 follow-up: such a page ALSO hides its tab
    strip (one tab — nothing to switch) and has no status line, so a pane is its
    canvas + the QTabWidget frame; `with_status_line` is kept as the public ctor
    argument it has always been, no longer selecting a layout.
    v1.5.7: the same flag governs the THIRD tab — a pane never gets the command
    History tab (its layout budget is a command line, and it has no SFTP channel to
    import a history through); the history STORE and the record hook exist on every
    page, because what the application sends belongs to the server either way.
    """

    # v1.0RC3: resize PTY — a grid-change guard + a ~150 ms debounce before
    # channel.resize_pty (TERMINAL.md §5.5); the initial invoke_shell is 120×32,
    # the first canvas resize syncs it with the real size.
    PTY_RESIZE_DEBOUNCE_MS = 150

    # v1.0RC4: Quick Launch — a delay before sending the first command after
    # invoke_shell (login scripts/motd; PTY input is buffered, the command is
    # not lost).
    INITIAL_COMMAND_DELAY_MS = 500

    # v1.3.1: the SFTP task kinds that feed the progress bridge (the busy counter,
    # the QProgressBar and the status-bar text). "read" is the viewer's read
    # (ROADMAP v1.3.1) — its OUTCOME is rendered by the SFTP tab itself.
    # v1.3.3.2: the file operations (OP_KINDS — mkdir/rename/delete) are outside
    # this set on purpose: no bytes, no bar, and the tab owns both the success and
    # the error message.
    _SFTP_PROGRESS_KINDS = ("upload", "download", "read")

    # ── Host bridge (window/dock): the page does not know where messages go ─
    status_message = Signal(str, int)   # (text, timeout_ms); 0 — sticky (no timeout)
    progress_busy = Signal()            # SFTP: show the indeterminate bar
    progress_update = Signal(int, int)  # SFTP: (done, total); total<=0 — indeterminate
    progress_hidden = Signal()          # SFTP: hide the bar

    def __init__(self, server_data, parent=None, password: str = None,
                 initial_command: str = "", with_sftp: bool = True,
                 with_status_line: bool = True, split: bool = False):
        super().__init__(parent)
        self.server_data = server_data
        self._host_window = None     # the host window (SSHTerminalWindow); close_terminal() closes it
        self._force_close = False    # v1.1.1: the limit path — a confirmed decision, "ask" does not ask again
        self._shut_down = False      # shutdown() is idempotent (all teardown paths go through one method)
        # v1.3.3.5 (ROADMAP task 2): the SPLIT marker — the page was created as the second
        # pane of a terminal window (add_session(split=True)), NOT as a tab. The registry
        # of MainWindow (_terminal_windows) keeps it for the green dot and the multi-input
        # provider, while the terminal_max_open limit and _find_terminal_window_for skip
        # it (ui/main_window_ssh.py): a pane is a session, not a reason to refuse a new
        # terminal. v1.6.1 (task 8): the flag is a CONSTRUCTOR argument — the page must know
        # from birth that it is a pane, because the keyboard claim below is decided HERE.
        self._is_split_pane = bool(split)
        # v1.6.1 (ROADMAP task 8): the keyboard claim — the session takes the focus once,
        # when it is really SHOWN (`claim_focus()`), never while it is still hidden.
        self._focus_claimed = False
        # v1.3.3.5: the multi-input badge of the pane — it has no tab in session_tabs,
        # so the highlight marks its inner `Terminal` tab instead (set_session_badge).
        self._session_badge = None

        # v1.3.3.5: the LIVE status text of the session (read by the host through the
        # `session_status` property and by `_apply_session_tab_title`).
        # v1.4.7 follow-up: it no longer owns a status LINE — the text lives in the
        # HOST's status surface alone (the `status_message` bridge below).
        self._session_status = ""
        self._with_status_line = bool(with_status_line)

        t = get_translator()
        layout = QVBoxLayout(self)

        # v1.4.7 follow-up (the maintainer's request): the session state stops taking a
        # row of the session. The old status line repeated, one row above the
        # `[Terminal | Files]` tabs, the very text the HOST's status bar already showed
        # through the `status_message` bridge — a duplicate that cost a row in every
        # tab and ~40 px of a ~140 px split pane. The label OBJECT is deliberately kept
        # (the compatibility readers `page.status_label.text()`, the window's compat
        # property, `_split_min_height`) but it is a HIDDEN child that is never added to
        # the layout, so it costs no height at all.
        self._session_status = t("terminal.initializing")
        self.status_label = QLabel(self._session_status, self)
        # v1.4.3 (ROADMAP task 4): the style comes from the ONE registry
        # (ui/theme_qss.py); refresh_theme() re-applies the same key.
        if theme_qss is not None:
            self.status_label.setStyleSheet(theme_qss.style("status.terminal_row"))
        else:
            self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 4px 0;")
        self.status_label.hide()

        # AUDIT v0.7.2 (medium #7): an explicit password takes priority over node.data.password —
        # the model is not polluted with plaintext before the keyring write/project save.
        if password is not None:
            pwd = password or ""
        else:
            pwd = getattr(server_data, 'password', '') or ""

        # Test seam: the thread class is fetched from the ssh_terminal module at
        # call time (monkeypatching ST.SSHTerminalThread in tests works unchanged).
        thread_cls = _st_module().SSHTerminalThread
        self.terminal_thread = thread_cls(
            host=server_data.host,
            user=server_data.user,
            port=server_data.ssh_port or 22,
            password=pwd,
            key_path=server_data.key_path,
        )

        # v1.0 final (ROADMAP task 9): terminal_* keys from ~/.sshmap/config.json —
        # all optional, defaults = the current behaviour (the RC4 look). UI — v1.1.
        term_cfg = _st_module().load_terminal_settings()
        # v1.1 (ROADMAP task 3): the session close behaviour — used in confirm_close().
        self._close_behavior = term_cfg["close_behavior"]

        # v0.8: the pyte screen — a 120x32 grid, the same geometry as invoke_shell;
        # the HistoryScreen scrollback depth — terminal_history_lines (default 1000).
        self.tscreen = TerminalScreen(columns=120, lines=32,
                                      history_lines=term_cfg["history_lines"])

        # v1.0RC1: a per-cell canvas (QWidget + QPainter) instead of QPlainTextEdit+HTML.
        # The font — system monospace pt 10, the 'default' palette = the current look;
        # runs/cursor/wide glyphs — see terminal_widget.py. v1.1.2RC3 (AUDIT U3):
        # the wheel mode from the config (terminal_wheel).
        self.widget = TerminalWidget(self.tscreen, self.terminal_thread,
                                     wheel_mode=term_cfg["wheel"])
        # v1.3.3.4 (ROADMAP task 3): the transcript's suggested file name carries the
        # host — the page owns the server data, the canvas owns the menu that asks.
        self.widget.set_transcript_host(getattr(server_data, "host", "") or "")
        # v1.0 final: applying the config (an unknown palette → set_palette() False
        # → "default" stays; corrupt values were dropped in load_terminal_settings).
        if term_cfg["palette"] is not None:
            self.widget.set_palette(term_cfg["palette"])
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            self.widget.set_font(
                family=term_cfg["font_family"],
                size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)

        # v1.1.3 (ROADMAP task 4): QTabWidget [Terminal | Files]. The SFTP tab
        # reuses the same transport (terminal_thread.client.open_sftp() —
        # without a second authentication and known_hosts pass); the worker is
        # created lazily — on the first switch to "Files" / after connected_signal.
        # v1.3.3.5 (the terminal SPLIT, ROADMAP task 4): `with_sftp=False` builds the
        # page WITHOUT the SFTP tab — the split pane is a COMMAND LINE, and a second
        # channel, a second worker and a file tree squeezed into ~130 px are pure cost
        # there. The flag also keeps the page's own layout minimum small, which is what
        # makes the 25% default of the split honest (the floor is then driven by the
        # canvas rows, not by the tree). Everything else keeps working unchanged:
        # `page.tabs` still exists (ONE tab — the canvas; the multi-input badge of a
        # pane lands on it) and `page.sftp_tab` is None (every reader is guarded below).
        self._with_sftp = bool(with_sftp)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.widget, t("sftp.tab_terminal"))
        self.sftp_tab = SftpTab() if self._with_sftp else None
        if self.sftp_tab is not None:
            self.tabs.addTab(self.sftp_tab, t("sftp.tab_files"))

        # v1.5.7 (ROADMAP task 1): the COMMAND history — the THIRD tab of the session
        # (`Terminal | Files | History`), one history per server. The STORE exists on every
        # page, because what the application sends belongs to the server whether it went to a
        # tab or to a split PANE; the TAB exists only on a page with the SFTP channel
        # (`with_sftp=True`), because the panel's "Import from the server…" has no channel to
        # read through on a compact pane and the pane's layout budget is deliberately small
        # (§4.3). The panel is duck-typed against this page: `send_macro()` (the ONE send
        # path), `server_data.alias` and `ensure_sftp_worker()`.
        self.command_history = CommandHistoryStore(getattr(server_data, "id", ""))
        self.history_tab = None
        if self._with_sftp:
            self.history_tab = CommandHistoryPanel(store=self.command_history, session=self)
            self.tabs.addTab(self.history_tab, t("terminal.tab_history"))
            self.history_tab.status_message.connect(self._on_history_message)

        # v1.5.7 (ROADMAP task 7): the application records exactly what IT sent. The hook sits
        # on the CANVAS, because that is the ONE method (`TerminalWidget.send_macro`) every
        # explicit send goes through — the macro library calls it directly on `page.widget`,
        # and the page's own `send_macro()` (the History tab) reaches it the same way. Typed
        # input is deliberately NOT recorded: the canvas sees raw bytes and keys, not the
        # shell's line editing. Quick launch sends through `terminal_thread.send_data()`, so it
        # records itself in `_send_initial_command()`.
        self.widget.command_sent_hook = self.record_sent_command

        # v1.4.7 follow-up (the maintainer's request): a page with a SINGLE tab does not
        # show a tab STRIP at all — the split pane is a command line, and the strip spent
        # a row of a ~140 px pane on one redundant title. The QTabWidget keeps its frame
        # (the pane still has its border) and the multi-input state of a pane is carried
        # by the amber FRAME on `split_host` (`multi_input.apply_container_highlight`);
        # the badge kept on the hidden title is state, not a plaque.
        if self.tabs.count() == 1:
            self.tabs.tabBar().hide()
        layout.addWidget(self.tabs)

        # v1.1.3: the SFTP state (the worker is lazy; a task registry for the progress text).
        # Visualisation — the bridge signals progress_* (in windows mode the window
        # attaches them to its QProgressBar in the status bar — the v1.1.x look).
        self._sftp_worker = None
        self._sftp_tasks = {}      # task_id → (kind, label)
        self._sftp_busy = 0        # how many uploads/downloads are in flight
        # v1.3.3.4 (ROADMAP task 6): task_id → TransferMeter (the rate/ETA of a transfer;
        # dropped with the task — see _on_sftp_task_done/error/cancelled).
        self._transfer_meters = {}
        self.tabs.currentChanged.connect(self._on_tab_changed)
        if self.sftp_tab is not None:
            self.sftp_tab.message.connect(self._on_sftp_tab_message)

        # v1.0RC3: resize PTY — a grid-change guard + a ~150 ms debounce. The canvas
        # lives inside the tab (not in the window's resizeEvent): the eventFilter on
        # the widget itself catches the REAL canvas resize — the recompute is
        # deferred with singleShot(0) until the layout settles (the v1.1.x pattern:
        # a transitional size must not change the grid).
        self._last_cols, self._last_rows = 120, 32
        self._pending_pty = None
        self._pty_timer = QTimer(self)
        self._pty_timer.setInterval(self.PTY_RESIZE_DEBOUNCE_MS)
        self._pty_timer.timeout.connect(self._on_pty_debounce)
        self.widget.installEventFilter(self)

        self.terminal_thread.output_signal.connect(self._on_output)
        self.terminal_thread.error_signal.connect(self._show_error)
        self.terminal_thread.status_signal.connect(self._set_status)
        self.terminal_thread.closed_signal.connect(self._on_closed)
        # v1.1.3: the user may already be sitting on the "Files" tab during the
        # connection — open SFTP as soon as the client appears in the thread.
        self.terminal_thread.connected_signal.connect(self._on_connected_for_sftp)
        # v1.5.7: the PTY receives the grid the layout computed BEFORE the connection —
        # the one debounced resize that the missing channel refused (see _flush_pty_grid).
        self.terminal_thread.connected_signal.connect(self._flush_pty_grid)

        # v1.0RC4: Quick Launch — the first command is sent after the connection
        # (connected_signal), not before: on a failed authentication the command
        # simply does not go out, the error is shown via the regular error path.
        # The Connection is kept — shutdown() disconnects ONLY if the connection
        # was made (PySide6 6.11: disconnecting an unconnected slot raises
        # RuntimeWarning).
        self._initial_command = (initial_command or "").strip()
        self._initial_cmd_conn = None
        if self._initial_command:
            self._initial_cmd_conn = self.terminal_thread.connected_signal.connect(
                self._send_initial_command)

        self.terminal_thread.start()
        # v1.6.1 (ROADMAP task 8): this call is a NO-OP — the page is still HIDDEN here and
        # Qt delivers no FocusIn to a hidden container, so the keystrokes of a fresh session
        # went nowhere until the user clicked the canvas. The real claim is the DEFERRED
        # `claim_focus()`, armed by the first `showEvent` and by the tab-current hook of the
        # container (see `claim_focus()`). A SPLIT PANE does not even arm it: with two shells
        # on one screen the choice of the target belongs to the user (and Qt would otherwise
        # hand the window's focus_child to a pane the user never touched).
        if not self._is_split_pane:
            self.widget.setFocus()

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the page's own strings in the current language.

        The tab titles of the inner QTabWidget (`Terminal | Files | History`; a page built with
        `with_sftp=False` has the `Terminal` tab alone) — the walk reads the tab COUNT and asks
        each page which widget it is, so a page with a different tab set re-texts exactly what
        it has; and v1.3.3.5: the `Terminal` title is re-composed by `_apply_session_tab_title()`
        — the multi-input badge a SPLIT PANE carries there AND its live status text, both of
        which must survive the switch. Every
        string already has an i18n key (ZERO new keys) and the module translator is
        looked up at call time — no cache to invalidate. The status label carries the
        LIVE session state (connecting/opened/closed — emitted by the thread), so it
        is deliberately left alone; the SFTP tab and the History panel re-text themselves. Never
        raises — the dead-C++-object discipline of every container method.
        """
        t = get_translator()
        try:
            tabs = self.tabs
            for i in range(tabs.count()):
                widget = tabs.widget(i)
                if widget is self.sftp_tab and self.sftp_tab is not None:
                    tabs.setTabText(i, t("sftp.tab_files"))
                elif widget is self.history_tab and self.history_tab is not None:
                    tabs.setTabText(i, t("terminal.tab_history"))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        # v1.3.3.5: the inner `Terminal` title carries the multi-input badge of a SPLIT
        # PANE — re-composed here so a language switch re-texts the badge instead of dropping it.
        self._apply_session_tab_title()
        sftp_tab = getattr(self, "sftp_tab", None)
        if sftp_tab is not None:
            try:
                sftp_tab.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the tab is already destroyed
        # v1.5.7 (ROADMAP task 4): the History panel — its headers, its placeholder and the
        # `terminal.history.last_unknown` cells are all translated text.
        history_tab = getattr(self, "history_tab", None)
        if history_tab is not None:
            try:
                history_tab.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the tab is already destroyed
        # v1.3.3.4: the canvas's own strings (the find panel — if it is open)
        widget = getattr(self, "widget", None)
        if widget is not None:
            try:
                widget.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the canvas is already destroyed

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to this session.

        The page's status label, the canvas (the find bar is its child), the SFTP tab and the
        History panel. The terminal's OUTPUT palette is deliberately out of the UI
        theme's scope (AGENTS.md §4.6) — a session keeps its colours. Never
        raises: a session may be closing under the switch.
        """
        if theme_qss is not None:
            try:
                theme_qss.refresh(self.status_label, "status.terminal_row")
            except RuntimeError:
                pass  # Qt teardown — the label is already destroyed
        widget = getattr(self, "widget", None)
        if widget is not None:
            hook = getattr(widget, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass
        for tab_name in ("sftp_tab", "history_tab"):   # v1.5.7: the panel joins the walk
            tab = getattr(self, tab_name, None)
            if tab is None:
                continue
            hook = getattr(tab, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass

    # ── v1.3.3.5 (ROADMAP task 6): the multi-input badge of a SPLIT PANE ─────

    def set_session_badge(self, key=None, **kwargs):
        """v1.3.3.5: mark THIS session's inner `Terminal` tab with the i18n key `key`.

        The container's multi-input highlight badges the TABS of `session_tabs`
        (modules/multi_input.py) — a split pane has no tab there, so the badge of the
        pane goes on the only title it owns (its `Terminal` tab). The KEY (plus its
        format kwargs) is stored instead of the rendered text, so the badge follows a
        language switch: `retranslate()` re-renders it in the new language. `key=None`
        restores the plain title. No new i18n key — the caller passes the SAME
        `terminal.multi_tab_badge` / `terminal.multi_excluded_badge`. Never raises.
        """
        self._session_badge = (str(key), dict(kwargs)) if key else None
        self._apply_session_tab_title()

    def _apply_session_tab_title(self):
        """Compose the inner `Terminal` tab title of THIS session (v1.3.3.5).

        Base — `sftp.tab_terminal`; plus the multi-input badge if the container set one
        (a split pane). **The LIVE status text is deliberately NOT part of it any more**
        (the v1.4.7 follow-up): the state of a session lives in the host's status
        surface alone, and the pane of a split — the only page whose tab strip is hidden
        (`__init__`) — keeps the badge as state while the amber frame carries it
        visibly. The badge is a KEY and is rendered with the current language. Never
        raises.
        """
        try:
            t = get_translator()
            title = t("sftp.tab_terminal")
            if self._session_badge is not None:
                key, kwargs = self._session_badge
                title = t(key, **kwargs) if kwargs else t(key)
            self.tabs.setTabText(0, title)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── Host ────────────────────────────────────────────────────────────────

    def set_host_window(self, window):
        """The host window (SSHTerminalWindow): close_terminal() will close it, and
        QMessageBox will get it as their parent. Without a host — teardown directly."""
        self._host_window = window

    def send_macro(self, text) -> bool:
        """v1.3 (ROADMAP v1.3): a command-library macro → the terminal canvas
        (widget.send_macro: a direct send_data of its own session, not a broadcast).
        RuntimeError — a close race (the C++ object was destroyed) → False.

        v1.5.7 (ROADMAP task 6): this is the send path the History tab's "Send to terminal"
        uses, and the canvas records it through `command_sent_hook` — the timestamp and the
        count of the entry move as a result of the send, exactly as the ROADMAP requires."""
        try:
            return self.widget.send_macro(text)
        except RuntimeError:
            return False

    # ── v1.5.7 (ROADMAP task 7): the COMMAND history of this server ─────────

    def record_sent_command(self, text) -> bool:
        """Append what the APPLICATION sent to this server's command history (v1.5.7).

        Called by the canvas hook after a successful `TerminalWidget.send_macro()` and by the
        quick-launch path — the two places where the application knows the exact command line it
        put on the wire. **Nothing is inferred from the typed input**: the canvas sees raw bytes
        and key events, not the shell's line editing, so a reconstruction of what a user typed
        would be a guess (the documented non-goal of the version). An over-long or empty text is
        ignored by the store's own rules. Never raises — a history failure must not break a send.
        """
        store = getattr(self, "command_history", None)
        if store is None:
            return False
        try:
            store.record(text)
        except Exception:   # noqa: BLE001 — the history is bookkeeping, never a send path
            return False
        panel = getattr(self, "history_tab", None)
        if panel is not None:
            try:
                panel.reload()   # the new row / the moved timestamp is on screen at once
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        return True

    def ensure_sftp_worker(self):
        """The SFTP worker of this session, started lazily — or None (v1.5.7).

        The ONE way the History tab reaches the channel the Files tab uses: the panel asks for
        the worker and queues its read into it, so the file of the server is read OFF the GUI
        thread. A page without the SFTP tab (`with_sftp=False`, the split pane) has no channel
        and answers None — its History tab does not exist either.
        """
        try:
            if self._ensure_sftp():
                return self._sftp_worker
        except RuntimeError:
            pass  # Qt teardown — the session is already going away
        return None

    def _on_history_message(self, msg: str, timeout: int):
        """A History-panel message → the page's status_message bridge (the SFTP tab pattern)."""
        try:
            self.status_message.emit(msg, timeout)
        except RuntimeError:
            pass  # Qt teardown — no host left to tell

    # ── v1.2: teardown — one method for all paths ───────────────────────────

    def confirm_close(self) -> bool:
        """The gate before teardown (v1.1, ROADMAP task 3): terminal_close_behavior.

        "ask": an active session (the SSH thread is still running) → a
        confirmation; a cancel — False (the host must event.ignore() and keep
        living). "close" (default) and an already-finished session — no dialog.
        _force_close (the v1.1.1 limit path: the "close the oldest" decision is
        already confirmed by the user) — also no dialog. Teardown robustness:
        RuntimeError on C++ objects does not block the close."""
        try:
            if getattr(self, "_close_behavior", "close") == "ask" \
                    and not getattr(self, "_force_close", False):
                _thread = self.terminal_thread
                if _thread is not None and _thread.isRunning():
                    t = get_translator()
                    box = _st_module().QMessageBox   # test seam (ST.QMessageBox)
                    reply = box.question(
                        self._host_window, t("msg.close_session_title"),
                        t("msg.confirm_close_session"),
                        box.Close | box.Cancel, box.Close)
                    if reply != box.Close:
                        return False
        except RuntimeError:
            pass  # a Qt teardown — close without asking (as before)
        return True

    def stop_thread(self):
        """Stop the thread WITHOUT waiting (the close_terminal path; wait() — in shutdown())."""
        try:
            thread = getattr(self, "terminal_thread", None)
            if thread is not None:
                thread.stop()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    def close_terminal(self):
        """Close the session (v1.2.1): stop the thread + close THIS session's tab
        on the host (window.close_page → confirm_close → shutdown; the last tab
        closes the window). The MainWindow._shutdown_background_threads path and
        the "4 own terminals" limit: in a tabbed window, closing a session does
        NOT touch the neighbouring tabs. Without a host / the host has no
        close_page (a fake) — teardown directly."""
        self.stop_thread()
        w = getattr(self, "_host_window", None)
        if w is not None:
            close_page_fn = getattr(w, "close_page", None)
            if callable(close_page_fn):
                try:
                    close_page_fn(self)
                    return
                except RuntimeError:
                    pass  # the host was already destroyed — teardown directly
        self.shutdown()

    def shutdown(self):
        """The SINGLE teardown method (v1.2, ROADMAP task 3): every teardown path
        (window close, session error, MainWindow shutdown, the limit path) goes
        through it. Idempotent (a repeated call — no-op).

        Order (the v1.1.x closeEvent order is kept):
          1. the SFTP worker FIRST (it depends on the terminal thread's transport):
             disconnect the page's slots, stop with a bounded wait; a wait that does
             not finish (a transfer stalled on a dead network) — the orphan worker
             registry keeps the thread alive until finished();
          2. stop the PTY debounce timer (resize_pty into a dead channel);
          3. disconnect the thread's signals from the page and stop() + wait(1500):
             the recv loop has msleep(30) — after stop() the thread exits in ~100 ms,
             the wait always makes it in practice; the window/page may be destroyed
             after this event (WA_DeleteOnClose), while paramiko may still be
             connecting for up to 15 s → a thread that outlives the wait is
             registered in the orphan thread registry `_orphan_threads`
             (v1.1.2RC1 N4): a live QThread without a QObject parent must not be
             left to GC, and late emits without receivers are a safe no-op.
        """
        if self._shut_down:
            return
        self._shut_down = True

        # IMPORTANT (verified by running, PySide6 6.11): signal.disconnect(receiver)
        # raises TypeError — the disconnection is done by the EXACT slot (bound
        # method); TypeError is caught only for "the slot was not connected"
        # (conditional connections).
        def _dissig(sig, slot):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass  # the slot was not connected — nothing to do

        # v1.1.3: the SFTP worker FIRST (it depends on the terminal thread's transport).
        sftp_worker = getattr(self, "_sftp_worker", None)
        if sftp_worker is not None:
            _dissig(sftp_worker.task_started, self._on_sftp_task_started)
            _dissig(sftp_worker.progress, self._on_sftp_progress)
            _dissig(sftp_worker.task_done, self._on_sftp_task_done)
            _dissig(sftp_worker.task_error, self._on_sftp_task_error)
            _dissig(sftp_worker.task_cancelled, self._on_sftp_task_cancelled)
            _dissig(sftp_worker.finished, self._on_sftp_worker_finished)
            sftp_worker.shutdown(wait_ms=2500)
            if sftp_worker.isRunning():
                register_orphan_sftp_worker(sftp_worker)

        # v1.3.1 (ROADMAP task 4): the preview panel closes together with the session —
        # BEFORE the worker/thread teardown (the panel never outlives the transport it
        # was read through). Idempotent; a destroyed C++ object must not block the close.
        # v1.3.3.5: a page without the SFTP tab (`with_sftp=False`) has no panel at all.
        sftp_tab = getattr(self, "sftp_tab", None)
        if sftp_tab is not None:
            try:
                sftp_tab.close_viewer()
            except RuntimeError:
                pass

        # v1.3.3.4 (ROADMAP task 3): the transcript is a local file of the SESSION — it
        # is closed here, on the single idempotent teardown path, so no tee survives a
        # closed session (the ROADMAP requirement: it must never raise into the teardown,
        # hence the broad guard: a full disk / a destroyed canvas must not block the close).
        try:
            self.widget.stop_transcript()
        except Exception:  # noqa: BLE001 — the file close must not block the session teardown
            pass

        try:
            self._pty_timer.stop()
        except Exception:
            pass  # a C++ object RuntimeError (teardown) — does not block the close

        thread = getattr(self, "terminal_thread", None)
        if thread is not None:
            _dissig(thread.output_signal, self._on_output)
            _dissig(thread.error_signal, self._show_error)
            _dissig(thread.status_signal, self._set_status)
            _dissig(thread.closed_signal, self._on_closed)
            # v1.0-fix (audit #6): + connected_signal — it was not disconnected before;
            # on a close before the connect finished, the orphan thread would still
            # send the first Quick Launch command into the void after a successful
            # connection.
            _dissig(thread.connected_signal, self._on_connected_for_sftp)
            _dissig(thread.connected_signal, self._flush_pty_grid)
            # Quick Launch — only if the connection was made (the Connection object from __init__)
            if getattr(self, "_initial_cmd_conn", None) is not None:
                try:
                    thread.connected_signal.disconnect(self._initial_cmd_conn)
                except (TypeError, RuntimeError):
                    pass
            thread.stop()
            if thread.isRunning():
                thread.wait(1500)
                # v1.1.2RC1 (N4): the page may be destroyed after this event
                # (the window — WA_DeleteOnClose), while paramiko may still be connecting (up to 15 s).
                if thread.isRunning():
                    _st_module().register_orphan_thread(thread)

        # The "Files" tab's slot is disconnected too (the worker's list_ready goes
        # straight into the tab — it will die together with the page). v1.3.3.5: nothing
        # to unbind on a page built without the SFTP tab.
        if getattr(self, "sftp_tab", None) is not None:
            _dissig(self.sftp_tab.message, self._on_sftp_tab_message)

    # ── v1.0RC3: dirty rendering without a timer (ROADMAP task 8) ───────────

    def eventFilter(self, obj, event):
        """v1.2: a canvas resize (inside the tab) → a grid recompute. Before —
        SSHTerminalWindow.resizeEvent; the grid-change guard and the debounce are the same."""
        if obj is self.widget and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._sync_grid)
        return super().eventFilter(obj, event)

    def claim_focus(self) -> bool:
        """v1.6.1 (ROADMAP task 8): give the keyboard to THIS session's canvas.

        `setFocus()` called while the page is still HIDDEN never reaches the container —
        no `FocusIn` is delivered (the fact `modules/ssh_terminal.py` states at
        `_wire_page()`), so a fresh session used to open with a blinking cursor and
        keystrokes that went nowhere until the user clicked the canvas. The claim is
        therefore ONE DEFERRED `setFocus` (singleShot(0), when the layout has run) and it
        is armed from the two places that know the session is really on screen: the first
        `showEvent` and the tab-current hook of the container.

        A SPLIT PANE is deliberately left alone — with two shells on one screen the choice
        of the target belongs to the user. Returns True when the request was made.
        """
        if getattr(self, "_is_split_pane", False) or self._shut_down:
            return False
        widget = getattr(self, "widget", None)
        if widget is None:
            return False
        try:
            QTimer.singleShot(0, widget.setFocus)
        except RuntimeError:
            return False  # Qt teardown — the canvas is already destroyed
        return True

    def showEvent(self, event):
        """v1.5.7: the first SHOW re-computes the grid, so a session never depends on a
        resize event to find out how big it is.

        A page that is shown without its canvas changing size (a dock tab revealed later, a
        window restored to the very geometry of the layout pass) would otherwise keep
        `invoke_shell`'s 120×32 as its only grid definition. Deferred with singleShot(0): at
        show time the layout has not run yet, and `_sync_grid` guards the not-laid-out case.

        v1.6.1 (ROADMAP task 8): the FIRST show also claims the keyboard (`claim_focus()`),
        deferred the same way. A LATER show (a tab switched back, a window re-shown) does not
        re-claim it — the container's tab hook is the place for that, and a minimise/restore
        must not move the focus the user placed somewhere else.
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_grid)
        if not self._focus_claimed:
            self._focus_claimed = True
            self.claim_focus()

    def _on_output(self, data: bytes):
        """A slot from the SSH thread (a queued signal — already in the GUI thread):
        raw bytes into pyte + a direct canvas update(). A 30 FPS timer is not
        needed: Qt coalesces several update() calls within one event cycle by
        itself; paintEvent reads the grid itself (TerminalWidget._paint). The
        scrollback auto-snap to the live line on new output — inside pyte
        (HistoryScreen.before_event), so new output is visible immediately, even
        if the user was viewing the history.

        v1.1.2RC3 (N7): if this output auto-returned the scrollback to live
        (the history position changed) — the selection is reset: the (row, col)
        coordinates were pinned on the HISTORICAL screen in the release, and after
        the return they point at OTHER cells of the live screen — Ctrl+C would
        copy someone else's text. Without new output / without an active selection,
        the behaviour of a plain click and of Ctrl+C does not change.

        v1.5.7: a failure INSIDE the emulator no longer costs the repaint. This path used to
        `return` on any exception — the canvas then kept the previous frame until the NEXT
        output arrived, which from the outside looks like "the full-screen application is gone
        but the prompt only appears when I press a key" (a TUI's exit sequence is followed by
        silence until the user types). The state is now whatever pyte managed to apply: it is
        repainted, and the failure is LOGGED instead of swallowed.
        """
        pos_before = None
        try:
            pos_before = self.tscreen.scroll_info()[0]
            self.tscreen.feed(data)
        except Exception as exc:  # noqa: BLE001 — the canvas must repaint whatever state exists
            log = _log()
            if log is not None:
                log.warning(f"terminal: feed failed ({exc!r}) — repainting the current state")
        # v1.3.3.4 (ROADMAP task 3): the transcript tee. Inside the output path but
        # deliberately OUTSIDE the pyte block above: a broken file must not stop the
        # rendering (write_transcript swallows everything and stops the tee itself).
        try:
            self.widget.write_transcript(data)
        except Exception:  # noqa: BLE001 — the tee never breaks the session
            pass
        # v1.1.2RC3 (N7): a history position change ⇔ an auto-return to live (feed() —
        # the only path that changes the position without a manual scroll). An active
        # selection on the "old" screen is reset before copying.
        try:
            if pos_before is not None and self.tscreen.scroll_info()[0] != pos_before \
                    and self.widget.has_selection():
                self.widget.clear_selection()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose close race)
        try:
            self.widget.update()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose close race)

    # ── v1.0RC3: resize PTY — a grid guard + debounce (ROADMAP task 6) ──────

    def _visible_grid(self):
        """(cols, rows) of the visible grid: the canvas size / the cell metrics."""
        cw, chh = self.widget.cell_size
        cols = max(2, self.widget.width() // cw)
        rows = max(1, self.widget.height() // chh)
        return cols, rows

    def _sync_grid(self):
        """A recompute of the visible grid (after the layout settled).

        v1.5.7: a canvas that is not laid out yet (width/height 0 — a page built into a
        hidden dock) is left alone. `_visible_grid()` clamps to 2×1, and pushing that into
        pyte/the PTY would destroy the session's grid for a frame (the showEvent hook makes
        this reachable in cases where no resize event would have been).
        """
        try:
            if self.widget.width() <= 0 or self.widget.height() <= 0:
                return  # not laid out yet — the Resize/showEvent path will come back
            cols, rows = self._visible_grid()
            if (cols, rows) == (self._last_cols, self._last_rows):
                return  # the grid did not change — no pyte.resize, no PTY signal
            self._last_cols, self._last_rows = cols, rows
            self.tscreen.resize(cols, rows)   # pyte: a no-op at the same size (fact #9)
            self.widget.update()              # the grid changed — repaint the canvas
            self._pending_pty = (cols, rows)
            self._pty_timer.start()           # restart the 150 ms countdown (debounce)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose race on close)

    def _pty_channel(self):
        """The LIVE PTY channel of this session, or None (not connected / closed / gone)."""
        thread = getattr(self, "terminal_thread", None)
        channel = getattr(thread, "channel", None) if thread is not None else None
        if channel is None or getattr(channel, "closed", False):
            return None
        return channel

    def _send_pty_resize(self) -> bool:
        """Send the pending grid to the PTY. True — it went out; False — not possible yet."""
        pending = getattr(self, "_pending_pty", None)
        if pending is None:
            return False
        channel = self._pty_channel()
        if channel is None:
            return False
        self._pending_pty = None
        try:
            channel.resize_pty(width=pending[0], height=pending[1])
        except Exception:
            return False   # the channel died — nothing to do
        return True

    def _on_pty_debounce(self):
        """The debounce expired — resize_pty with the LAST grid (only a live channel).

        v1.5.7: a grid computed BEFORE the connection is no longer thrown away. The layout
        runs when the window appears — long before paramiko has authenticated — so the first
        (and, on a window nobody resizes, the ONLY) grid change used to be dropped right here:
        `_last_cols/_last_rows` were already updated, no further Resize event followed, and the
        session kept `invoke_shell`'s 120×32 for its whole life while the pyte grid held the
        real canvas size. Every full-screen application then drew a 120×32 screen inside a
        differently sized canvas (the tester's "not full screen until I resize the window").
        The request now WAITS: it stays pending and `_flush_pty_grid()` sends it on connect.
        """
        if self._pending_pty is None:
            return
        if self._pty_channel() is None:
            return   # not connected yet — keep the pending value for the connect flush
        self._send_pty_resize()

    def _flush_pty_grid(self):
        """connected_signal: hand the PTY the grid the layout computed while connecting.

        The initial PTY is 120×32 (`invoke_shell`), the canvas has had its real size since the
        first layout pass, and that pass's debounced resize was refused by the missing channel.
        Making the PTY match the canvas is therefore the FIRST thing a connected session does —
        it is the SIGWINCH every TUI needs at startup, and without it the applications draw a
        120×32 screen inside a window of another size until the user happens to resize it.
        """
        try:
            self._send_pty_resize()
        except RuntimeError:
            pass  # Qt teardown — the session is already going away

    def _set_status(self, text: str):
        self._set_status_text(text)

    def _set_status_text(self, text: str):
        """The SINGLE status write of the page (v1.3.3.5, completed in the v1.4.7 follow-up).

        The page owns NO status surface of its own any more (`__init__`: the old status
        line is a hidden, un-laid-out label), so the text goes exactly one way: into
        `_session_status` (the `session_status` property — what a host reads to render
        its own strip) and through the `status_message` bridge into the HOST's status
        bar / status strip. Routing EVERY status write through here is what makes the
        ERROR path readable too: `_show_error` used to write the line nobody but the
        modal dialog saw while the status bar kept the previous text. Never raises: a
        dying C++ object must not break the status path.
        """
        self._session_status = text or ""
        try:
            self.status_label.setText(self._session_status)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        try:
            self.status_message.emit(self._session_status, 0)
        except RuntimeError:
            pass  # Qt teardown — no host left to tell

    @property
    def session_status(self) -> str:
        """The LIVE status text of this session ("" before the first write).

        The status of a session is DATA of the session and the display belongs to the
        host (a status bar with room for more than one session — the v1.4.7 follow-up
        renders the split pane's state next to the active session's).
        """
        return self._session_status

    def _show_error(self, error: str):
        t = get_translator()
        self._set_status_text(f"{t('terminal.error_prefix')} {error}")
        box = _st_module().QMessageBox   # test seam (ST.QMessageBox)
        box.critical(
            self._host_window,
            t("msg.ssh_error"),
            f"{t('terminal.error_prefix')} {error}",
        )
        self.close_terminal()

    def _on_closed(self):
        # v1.4.7 follow-up: one write — `_set_status_text` IS the bridge now (the line
        # and the host's status surface were two writes of the same text before).
        self._set_status_text(get_translator()("terminal.session_closed"))

    # ── v1.0RC4: Quick Launch ───────────────────────────────────────────────

    def _send_initial_command(self):
        """v1.0RC4: send the first command (Quick Launch) to the shell after the connection.

        A deferred call (INITIAL_COMMAND_DELAY_MS): invoke_shell returns the channel
        immediately, while the remote shell may still be writing motd/login scripts;
        PTY input is buffered by the kernel, so the command will run once the prompt
        appears. Sent exactly once; a dead/closed channel — a quiet no-op.
        """
        def _do():
            try:
                cmd = getattr(self, "_initial_command", "")
                if not cmd:
                    return
                self._initial_command = ""  # only once
                thread = getattr(self, "terminal_thread", None)
                channel = getattr(thread, "channel", None) if thread is not None else None
                if channel is None or channel.closed:
                    return
                thread.send_data((cmd + "\n").encode("utf-8"))
                # v1.5.7 (ROADMAP task 7): quick launch is the second path the APPLICATION
                # knows the exact command of — it does not go through send_macro(), so it
                # records itself (the macro library and the History tab are covered by the
                # canvas hook).
                self.record_sent_command(cmd)
            except Exception:  # noqa: BLE001 — the window may have closed (WA_DeleteOnClose)
                pass
        QTimer.singleShot(self.INITIAL_COMMAND_DELAY_MS, _do)

    # ── v1.1.3: the SFTP tab (ROADMAP tasks 2-4) ────────────────────────────

    def _ensure_sftp(self) -> bool:
        """Open an SFTP channel over a live transport and start the worker.

        It reuses `terminal_thread.client.open_sftp()` — without a second
        authentication and a second known_hosts pass (ROADMAP task 3):
        the policy was already applied to the client at connect; open_sftp just
        opens a new channel on the same Transport. A lazy call: the first switch
        to the "Files" tab / connected_signal, if the user is already there.
        The session is not connected yet → False (the tab waits). The server's
        SFTP subsystem is unavailable → an error in the status (the
        status_message bridge), the worker is not created (a retry — on the next
        switch to the tab). v1.3.3.5: a page built WITHOUT the SFTP tab
        (`with_sftp=False`) never opens a channel — no Files tab exists to ask for it.
        """
        t = get_translator()
        if getattr(self, "sftp_tab", None) is None:
            return False   # v1.3.3.5: a split pane is a command line — no SFTP channel
        worker = getattr(self, "_sftp_worker", None)
        if worker is not None and not worker.isFinished():
            return True
        thread = getattr(self, "terminal_thread", None)
        client = getattr(thread, "client", None) if thread is not None else None
        transport = None
        if client is not None:
            try:
                transport = client.get_transport()
            except Exception:
                transport = None
        if transport is None or not transport.is_active():
            return False
        try:
            sftp = client.open_sftp()
        except Exception as e:  # noqa: BLE001 — the SFTP subsystem may be disabled
            msg = t("sftp.open_failed", error=str(e))
            self.status_message.emit(
                msg if not msg.startswith("[") else f"Failed to open SFTP channel: {e}",
                8000)
            return False
        # WITHOUT a QObject parent: the window has WA_DeleteOnClose, and a hanging
        # transfer may outlive it — the orphan worker registry (the N4 v1.1.2RC1
        # pattern) keeps the thread alive until finished(); all slots are
        # disconnected in shutdown().
        new_worker = SftpWorker(sftp)
        self._sftp_worker = new_worker
        new_worker.task_started.connect(self._on_sftp_task_started)
        new_worker.progress.connect(self._on_sftp_progress)
        new_worker.task_done.connect(self._on_sftp_task_done)
        new_worker.task_error.connect(self._on_sftp_task_error)
        new_worker.task_cancelled.connect(self._on_sftp_task_cancelled)
        new_worker.finished.connect(self._on_sftp_worker_finished)
        new_worker.start()
        self.sftp_tab.set_worker(new_worker)
        return True

    def _on_tab_changed(self, index: int):
        """A switch to the "Files" tab — a lazy SFTP start (idempotent).

        v1.3.3.5: on a page without the SFTP tab `self.sftp_tab` is None and no widget
        can be it, so the guard is a no-op by itself (kept for symmetry).
        """
        if self.sftp_tab is not None and self.tabs.widget(index) is self.sftp_tab:
            self._ensure_sftp()

    def _on_sftp_tab_message(self, msg: str):
        """A tab message (a file selection and the like) → the status_message bridge (5 s)."""
        self.status_message.emit(msg, 5000)

    def _on_connected_for_sftp(self):
        """connected_signal: the user may already be sitting on "Files"."""
        try:
            if self.tabs.currentWidget() is self.sftp_tab:
                self._ensure_sftp()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    def _on_sftp_task_started(self, task_id: int, kind: str, label: str):
        t = get_translator()
        self._sftp_tasks[task_id] = (kind, label)
        if kind in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy += 1
            self.progress_busy.emit()   # v1.1.x: setRange(0,0)+setValue(0)+show()
            if kind == "read":          # v1.3.1: the viewer's read (SFTP tab)
                self.status_message.emit(t("sftp.viewer.reading", name=label), 0)
            else:
                key = "sftp.uploading" if kind == "upload" else "sftp.downloading"
                self.status_message.emit(t(key, name=label), 0)
        elif kind in OP_KINDS:
            pass   # v1.3.3.2: a file operation — the SFTP tab reports it itself
        else:  # list — without a progress bar
            self.status_message.emit(t("sftp.listing", path=label), 0)

    def _on_sftp_progress(self, task_id: int, done: int, total: int):
        t = get_translator()
        entry = self._sftp_tasks.get(task_id)
        if entry is None or entry[0] not in self._SFTP_PROGRESS_KINDS:
            return
        kind, label = entry
        if total > 0:
            self.progress_update.emit(done, total)   # v1.1.x: setRange(0,total)+setValue
            text = t("sftp.progress", name=label, pct=int(done * 100 // total),
                     done=format_size(done), total=format_size(total))
            # v1.3.3.4 (ROADMAP task 6): the measured throughput and the ETA, appended
            # to the same line (an empty string while the meter has nothing honest to show).
            detail = self._transfer_detail(task_id, done, total)
            if detail:
                text = f"{text} · {detail}"
        else:  # total unknown — name only (an indeterminate bar)
            self.progress_update.emit(done, 0)
            if kind == "read":
                text = t("sftp.viewer.reading", name=label)
            else:
                key = "sftp.uploading" if kind == "upload" else "sftp.downloading"
                text = t(key, name=label)
        self.status_message.emit(text, 0)

    def _transfer_detail(self, task_id: int, done: int, total: int) -> str:
        """v1.3.3.4 (ROADMAP task 6): "1.2 MB/s · ETA 0:42" — or "" while unmeasurable.

        The meter is created on the first sample of the task and dropped with it
        (SUCCESS, error and cancel all call _drop_transfer_meter). Never raises: a
        broken measurement costs the suffix, not the progress line.
        """
        try:
            meter = self._transfer_meters.get(task_id)
            if meter is None:
                meter = TransferMeter()
                self._transfer_meters[task_id] = meter
            sample = meter.update(done, total)
            if sample is None:
                return ""
            rate, eta = sample
            if rate is None or rate <= 0:
                return ""
            t = get_translator()
            parts = [t("sftp.rate", rate=format_size(int(rate)))]
            eta_text = format_duration(eta) if eta is not None else ""
            if eta_text:
                parts.append(t("sftp.eta", time=eta_text))
            return " · ".join(parts)
        except Exception:  # noqa: BLE001 — a cosmetic suffix must never break the transfer UI
            return ""

    def _drop_transfer_meter(self, task_id: int):
        """Forget the rate meter of a finished/failed/cancelled task."""
        try:
            self._transfer_meters.pop(task_id, None)
        except Exception:  # noqa: BLE001 — teardown race
            pass

    def _on_sftp_task_done(self, task_id: int, detail: str):
        t = get_translator()
        self._drop_transfer_meter(task_id)   # v1.3.3.4 (task 6): the meter dies with the task
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
            # v1.3.1: a read is reported by the SFTP tab itself (the preview panel),
            # not by a "transfer complete" line in the status bar.
            if entry[0] != "read":
                self.status_message.emit(t("sftp.transfer_done", name=entry[1]), 5000)

    def _on_sftp_task_error(self, task_id: int, kind: str, message: str):
        t = get_translator()
        self._drop_transfer_meter(task_id)   # v1.3.3.4 (task 6): the meter dies with the task
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        if kind == "read":
            # v1.3.1: the message of a read error is a MACHINE code — the SFTP tab
            # translates it (its message signal → the bridge); showing it here as
            # well would duplicate the hint with an untranslated code.
            return
        if kind in OP_KINDS:
            # v1.3.3.2: a file operation — the SFTP tab wraps the server's error in
            # its own translated line (the same no-duplication rule as for "read").
            return
        prefix = t("terminal.error_prefix")
        self.status_message.emit(f"{prefix} {message}", 8000)

    def _on_sftp_task_cancelled(self, task_id: int, kind: str):
        t = get_translator()
        self._drop_transfer_meter(task_id)   # v1.3.3.4 (task 6): the meter dies with the task
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        self.status_message.emit(t("sftp.transfer_cancelled"), 5000)

    def _on_sftp_worker_finished(self):
        """The worker stopped on its own (the transport died — the session
        closed/crashed): a state reset; the tab returns to "waiting", a restart —
        on the next switch to it, if a live connection appears. v1.3.3.5: a page
        without the SFTP tab has no worker to reset — the guard keeps it symmetrical."""
        try:
            self._sftp_worker = None
            self._sftp_tasks.clear()
            self._transfer_meters.clear()   # v1.3.3.4 (task 6): no live task — no meter
            self._sftp_busy = 0
            self.progress_hidden.emit()
            if getattr(self, "sftp_tab", None) is not None:
                self.sftp_tab.set_worker(None)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
