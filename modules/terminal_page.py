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

Test seams (the v1.1.4 host_attr pattern): the thread class and QMessageBox are
fetched from the ssh_terminal module at call time — monkeypatching
`ST.SSHTerminalThread`/`ST.QMessageBox.question` in tests works unchanged.
"""

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget

try:
    from .terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES
except ImportError:
    from modules.terminal_screen import TerminalScreen, DEFAULT_HISTORY_LINES

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

try:  # v1.2.5: the central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


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


class TerminalSessionPage(QWidget):
    """v1.2: an SSH session as a reusable widget.

    Composition: terminal_thread (SSHTerminalThread) + tscreen (TerminalScreen) +
    widget (TerminalWidget, the canvas) + the status line (status_label) + a
    QTabWidget [Terminal | Files] (SftpTab, a lazy worker). The terminal_* config
    is read from config.json at creation time (load_terminal_settings — defaults
    = the v1.0 behaviour).

    The host (SSHTerminalWindow / a future dock) creates the page with a parent
    and may:
      * attach the bridge signals status_message/progress_* to its own UI;
      * call set_host_window(w) — close_terminal() will close this session's tab
        on the host (v1.2.1: the last tab closes the window);
      * run the teardown through shutdown() (a single method, idempotent).
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
                 initial_command: str = ""):
        super().__init__(parent)
        self.server_data = server_data
        self._host_window = None     # the host window (SSHTerminalWindow); close_terminal() closes it
        self._force_close = False    # v1.1.1: the limit path — a confirmed decision, "ask" does not ask again
        self._shut_down = False      # shutdown() is idempotent (all teardown paths go through one method)

        t = get_translator()
        layout = QVBoxLayout(self)

        self.status_label = QLabel(t("terminal.initializing"))
        # v1.2.5: the colour — from the central theme (ui/theme.py); the value is unchanged
        self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 4px 0;")
        layout.addWidget(self.status_label)

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
        self.tabs = QTabWidget()
        self.tabs.addTab(self.widget, t("sftp.tab_terminal"))
        self.sftp_tab = SftpTab()
        self.tabs.addTab(self.sftp_tab, t("sftp.tab_files"))
        layout.addWidget(self.tabs)

        # v1.1.3: the SFTP state (the worker is lazy; a task registry for the progress text).
        # Visualisation — the bridge signals progress_* (in windows mode the window
        # attaches them to its QProgressBar in the status bar — the v1.1.x look).
        self._sftp_worker = None
        self._sftp_tasks = {}      # task_id → (kind, label)
        self._sftp_busy = 0        # how many uploads/downloads are in flight
        self.tabs.currentChanged.connect(self._on_tab_changed)
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
        self.widget.setFocus()

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the page's own strings in the current language.

        The two tab titles of the inner QTabWidget (`Terminal | Files`); every
        string already has an i18n key (ZERO new keys) and the module translator is
        looked up at call time — no cache to invalidate. The status label carries the
        LIVE session state (connecting/opened/closed — emitted by the thread), so it
        is deliberately left alone; the SFTP tab re-texts itself. Never raises — the
        dead-C++-object discipline of every container method.
        """
        try:
            t = get_translator()
            self.tabs.setTabText(0, t("sftp.tab_terminal"))
            self.tabs.setTabText(1, t("sftp.tab_files"))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        sftp_tab = getattr(self, "sftp_tab", None)
        if sftp_tab is not None:
            try:
                sftp_tab.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the tab is already destroyed

    # ── Host ────────────────────────────────────────────────────────────────

    def set_host_window(self, window):
        """The host window (SSHTerminalWindow): close_terminal() will close it, and
        QMessageBox will get it as their parent. Without a host — teardown directly."""
        self._host_window = window

    def send_macro(self, text) -> bool:
        """v1.3 (ROADMAP v1.3): a command-library macro → the terminal canvas
        (widget.send_macro: a direct send_data of its own session, not a broadcast).
        RuntimeError — a close race (the C++ object was destroyed) → False."""
        try:
            return self.widget.send_macro(text)
        except RuntimeError:
            return False

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
        try:
            self.sftp_tab.close_viewer()
        except RuntimeError:
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
        # straight into the tab — it will die together with the page).
        _dissig(self.sftp_tab.message, self._on_sftp_tab_message)

    # ── v1.0RC3: dirty rendering without a timer (ROADMAP task 8) ───────────

    def eventFilter(self, obj, event):
        """v1.2: a canvas resize (inside the tab) → a grid recompute. Before —
        SSHTerminalWindow.resizeEvent; the grid-change guard and the debounce are the same."""
        if obj is self.widget and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._sync_grid)
        return super().eventFilter(obj, event)

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
        the behaviour of a plain click and of Ctrl+C does not change."""
        try:
            pos_before = self.tscreen.scroll_info()[0]
            self.tscreen.feed(data)
        except Exception:
            return
        # v1.1.2RC3 (N7): a history position change ⇔ an auto-return to live (feed() —
        # the only path that changes the position without a manual scroll). An active
        # selection on the "old" screen is reset before copying.
        try:
            if self.tscreen.scroll_info()[0] != pos_before \
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
        """A recompute of the visible grid (after the layout settled)."""
        try:
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

    def _on_pty_debounce(self):
        """The debounce expired — resize_pty with the LAST grid (only a live channel)."""
        if self._pending_pty is None:
            return
        cols, rows = self._pending_pty
        self._pending_pty = None
        thread = getattr(self, "terminal_thread", None)
        channel = getattr(thread, "channel", None) if thread is not None else None
        if channel is None or channel.closed:
            return
        try:
            channel.resize_pty(width=cols, height=rows)
        except Exception:
            pass  # the channel died during the debounce — nothing to do

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self.status_message.emit(text, 0)   # v1.1.x: statusBar().showMessage(text) (sticky)

    def _show_error(self, error: str):
        t = get_translator()
        self.status_label.setText(f"{t('terminal.error_prefix')} {error}")
        box = _st_module().QMessageBox   # test seam (ST.QMessageBox)
        box.critical(
            self._host_window,
            t("msg.ssh_error"),
            f"{t('terminal.error_prefix')} {error}",
        )
        self.close_terminal()

    def _on_closed(self):
        t = get_translator()
        self.status_label.setText(t("terminal.session_closed"))
        self.status_message.emit(t("terminal.session_closed"), 0)

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
        switch to the tab).
        """
        t = get_translator()
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
        """A switch to the "Files" tab — a lazy SFTP start (idempotent)."""
        if self.tabs.widget(index) is self.sftp_tab:
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
        else:  # total unknown — name only (an indeterminate bar)
            self.progress_update.emit(done, 0)
            if kind == "read":
                text = t("sftp.viewer.reading", name=label)
            else:
                key = "sftp.uploading" if kind == "upload" else "sftp.downloading"
                text = t(key, name=label)
        self.status_message.emit(text, 0)

    def _on_sftp_task_done(self, task_id: int, detail: str):
        t = get_translator()
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
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        self.status_message.emit(t("sftp.transfer_cancelled"), 5000)

    def _on_sftp_worker_finished(self):
        """The worker stopped on its own (the transport died — the session
        closed/crashed): a state reset; the tab returns to "waiting", a restart —
        on the next switch to it, if a live connection appears."""
        try:
            self._sftp_worker = None
            self._sftp_tasks.clear()
            self._sftp_busy = 0
            self.progress_hidden.emit()
            self.sftp_tab.set_worker(None)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
