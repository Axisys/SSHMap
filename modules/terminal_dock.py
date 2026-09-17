# -*- coding: utf-8 -*-
"""v1.2.2 (ROADMAP v1.2.2): "Terminals" as a dock of the map window (terminal.mode = "tabs").

TerminalDockContent — an embeddable session container, the analog of
SSHTerminalWindow (v1.2.1 session_tabs) but for MainWindow: a QTabWidget of
TerminalSessionPage + its own status line (label + SFTP progress bar). The
contract is the same: each tab = one session, tab title — the node alias,
tooltip — terminal.tab_close_tooltip; closing a tab = cleanup of the LOCAL
page (the "ask" confirm_close gate → unified teardown shutdown, neighboring
tabs are untouched). Difference from the window: closing the LAST tab does
NOT destroy the container — the last_tab_closed signal (TerminalsDock hides
the dock); sessions are closed page by page, the container outlives them.

The "status bar" bridge — only the ACTIVE tab (v1.2.1 pattern), but into the
dock's OWN status line, not the map's status bar: when the dock is floated
into a separate window, messages and progress follow the container and do not
conflict with MainWindow's status bar.

TerminalsDock(QDockWidget) — a detachable dock (default flags
Movable|Closable|Floatable): float → a separate window with tabs, back →
back on the map; from a single mechanism come both "tabs" and "windows". The
map remains the central widget of MainWindow — self.view is untouched.
WA_DeleteOnClose is NOT set: the container lives until MainWindow closes
(created lazily on the first session in "tabs" mode; recreating it on mode
switches is not needed).

Test seams — the same as for the page (v1.2): the thread class and QMessageBox
are taken from the ssh_terminal module at call time
(TerminalSessionPage._st_module()).
"""
import itertools

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QProgressBar,
    QDockWidget, QSplitter,
)

try:
    from .terminal_page import TerminalSessionPage
except ImportError:
    from modules.terminal_page import TerminalSessionPage

# v1.3 (ROADMAP v1.3): the "Terminal Macros" panel — the same one as in
# SSHTerminalWindow (a single config key ui_cmdlib_collapsed for both containers).
try:
    from .command_library import CommandLibraryPanel
except ImportError:
    from modules.command_library import CommandLibraryPanel

try:  # v1.2.5: central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


def _st_module():
    """The ssh_terminal module at call time (a test seam for attribute substitution)."""
    try:
        from . import ssh_terminal as _st
    except ImportError:
        import ssh_terminal as _st
    return _st


def get_translator():
    """Safe i18n helper — as in terminal_page/ssh_terminal."""
    return _st_module().get_translator()


class TerminalDockContent(QWidget):
    """v1.2.2: session container for the "Terminals" dock (a QTabWidget of pages).

    Composition: session_tabs (QTabWidget, closable tabs) + a status line
    (status_label + sftp_progress). Pages are created with parent=session_tabs
    (destroyed together with the container) and bound to the content via
    set_host_window(self) — the page's close_terminal() calls close_page(self),
    i.e. the same path as in SSHTerminalWindow (v1.2.1).

    Signal bridge of the ACTIVE page: status_message → status_label
    (timeout_ms > 0 — timer-based auto-clear with a token-guard),
    progress_busy/update/hidden → sftp_progress. On tab switch the bridge is
    reconnected; messages of inactive tabs do not reach the status line
    (v1.2.1 behavior).
    """

    # v1.2.2: the last tab was closed — the container is empty (TerminalsDock hides the dock)
    last_tab_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        t = get_translator()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # v1.2.2 (task 2): a QTabWidget of TerminalSessionPage — each tab = one
        # SSH session; tabs are closable: closing a tab = cleanup of the LOCAL page.
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.session_tabs.currentChanged.connect(self._on_current_tab_changed)

        # v1.3 (ROADMAP v1.3): the "Terminal Macros" panel to the left of the tabs —
        # the same one as in SSHTerminalWindow (QSplitter [cmdlib_panel |
        # session_tabs]; a single config key ui_cmdlib_collapsed for both
        # containers). The panel's status messages go to the DOCK's status line
        # via the existing _on_page_status_message bridge (token-guard; the
        # (str, int) signature matches — no new bridge code).
        self.cmdlib_panel = CommandLibraryPanel(self.session_tabs, parent=self)
        self.cmdlib_panel.status_message.connect(self._on_page_status_message)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.cmdlib_panel)
        splitter.addWidget(self.session_tabs)
        # setCollapsible AFTER addWidget (Qt: the index would otherwise be out of range):
        # the panel cannot be "lost" by dragging the splitter handle to zero (v1.2.4.1).
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        layout.addWidget(splitter, 1)

        # The dock's own status line (not the map's status bar): when the dock is
        # floated into a window, the messages/progress follow the container.
        # Appearance — as in the terminal window: sticky text on the left, SFTP
        # progress on the right (hidden when there are no transfers).
        row = QHBoxLayout()
        self.status_label = QLabel("")
        # v1.2.5: color — from the central theme (ui/theme.py); value unchanged
        self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 2px 0;")
        self.sftp_progress = QProgressBar()
        self.sftp_progress.setFixedWidth(180)
        self.sftp_progress.setTextVisible(True)
        self.sftp_progress.setVisible(False)
        row.addWidget(self.status_label, 1)
        row.addWidget(self.sftp_progress)
        layout.addLayout(row)

        self._bridged_page = None      # the active page (status-line bridge)
        self._status_tokens = itertools.count()   # token-guard for label auto-clear
        self._status_token = None

    # ── v1.2.2: tabs = sessions (SSHTerminalWindow contract, v1.2.1) ─────────

    def add_session(self, server_data, password: str = None,
                    initial_command: str = "") -> "TerminalSessionPage":
        """A new session = a new tab (the existing "connect to node" path).

        The page is created with parent=session_tabs, bound to the host
        (set_host_window(self) — close_page lives on the content) and added as
        a tab: title — the node alias, tooltip — terminal.tab_close_tooltip.
        The new tab is activated explicitly (Qt: addTab makes only the FIRST
        tab current)."""
        t = get_translator()
        page = TerminalSessionPage(
            server_data, parent=self.session_tabs,
            password=password, initial_command=initial_command)
        page.set_host_window(self)
        idx = self.session_tabs.addTab(page, server_data.alias)
        self.session_tabs.setCurrentIndex(idx)
        try:
            self.session_tabs.setTabToolTip(idx, t("terminal.tab_close_tooltip"))
        except RuntimeError:
            pass  # C++ object already deleted (close race) — the tooltip is not critical
        return page

    def close_page(self, page):
        """Close ONE tab — cleanup of the LOCAL page (the "ask" confirm_close gate
        → unified teardown shutdown); neighboring tabs are untouched. Closing the
        LAST tab does NOT destroy the container: the last_tab_closed signal
        (TerminalsDock hides the dock; the next session in "tabs" mode will show it)."""
        idx = self.session_tabs.indexOf(page)
        if idx < 0:
            return  # the tab was already removed (teardown race)
        try:
            if not page.confirm_close():
                return  # "ask" + Cancel — the tab stays open
        except RuntimeError:
            pass  # C++ object already deleted — close without asking (as before)
        try:
            page.shutdown()
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        self.session_tabs.removeTab(idx)   # currentChanged → the bridge reconnects
        page.deleteLater()
        if self.session_tabs.count() == 0:
            self.last_tab_closed.emit()

    def _on_tab_close_requested(self, index: int):
        """The X on a tab (setTabsClosable) → close_page."""
        try:
            page = self.session_tabs.widget(index)
        except RuntimeError:
            return  # C++ object already deleted (close race)
        if page is not None:
            self.close_page(page)

    # ── v1.2.2: "status line" bridge — only the active tab (v1.2.1 pattern) ───

    def _on_current_tab_changed(self, index: int):
        try:
            page = (self.session_tabs.widget(index)
                    if 0 <= index < self.session_tabs.count() else None)
        except RuntimeError:
            page = None  # C++ object already deleted (close race)
        self._set_bridged_page(page)

    def _set_bridged_page(self, page):
        """Bridge of the ACTIVE tab's signals into the dock's status line; on tab
        switch — reconnection (inactive tabs' messages do not arrive). SFTP
        progress is synchronized with the active tab's state."""
        old = self._bridged_page
        if old is not None and old is not page:
            try:
                old.status_message.disconnect(self._on_page_status_message)
                old.progress_busy.disconnect(self._on_page_progress_busy)
                old.progress_update.disconnect(self._on_page_progress_update)
                old.progress_hidden.disconnect(self.sftp_progress.hide)
            except (TypeError, RuntimeError):
                pass  # the slot was not connected / the C++ object deleted — nothing to do
        self._bridged_page = page
        if page is None:
            return
        try:
            page.status_message.connect(self._on_page_status_message)
            page.progress_busy.connect(self._on_page_progress_busy)
            page.progress_update.connect(self._on_page_progress_update)
            page.progress_hidden.connect(self.sftp_progress.hide)
        except RuntimeError:
            return  # C++ object already deleted (close race) — nothing to bridge
        try:
            if getattr(page, "_sftp_busy", 0) > 0:
                self.sftp_progress.setRange(0, 0)   # until total arrives — busy
                self.sftp_progress.setValue(0)
                self.sftp_progress.show()
            else:
                self.sftp_progress.hide()
        except RuntimeError:
            pass  # C++ object already deleted (close race)

    def _on_page_status_message(self, text: str, timeout_ms: int):
        """The active page's message → the dock's status line. timeout_ms > 0 —
        timer-based auto-clear (token-guard: ANY new message, including sticky
        (timeout_ms = 0), invalidates the previous pending timeout)."""
        try:
            self.status_label.setText(text)
        except RuntimeError:
            return  # C++ object already deleted (close race)
        token = next(self._status_tokens)
        self._status_token = token
        if timeout_ms > 0:
            try:
                QTimer.singleShot(timeout_ms, lambda tk=token: self._expire_status(tk))
            except RuntimeError:
                pass  # C++ object already deleted (close race)

    def _expire_status(self, token):
        """The timeout expired — clear the label only if nothing newer arrived."""
        try:
            if token == self._status_token:
                self.status_label.setText("")
        except RuntimeError:
            pass  # C++ object already deleted (close race)

    def _on_page_progress_busy(self):
        try:
            self.sftp_progress.setRange(0, 0)   # until total arrives — busy
            self.sftp_progress.setValue(0)
            self.sftp_progress.show()
        except RuntimeError:
            pass  # C++ object already deleted (close race)

    def _on_page_progress_update(self, done: int, total: int):
        try:
            if total > 0:
                self.sftp_progress.setRange(0, total)
                self.sftp_progress.setValue(done)
            else:
                self.sftp_progress.setRange(0, 0)   # total unknown — busy
        except RuntimeError:
            pass  # C++ object already deleted (close race)


class TerminalsDock(QDockWidget):
    """v1.2.2 (task 2): the "Terminals" dock in MainWindow (terminal.mode = "tabs").

    Detachable (default QDockWidget flags: Movable|Closable|Floatable): float →
    a separate window with tabs, back → back on the map — from a single
    mechanism come both "tabs" and "windows". The map remains the central
    widget of MainWindow (self.view is untouched).

    WA_DeleteOnClose is NOT set: closing the dock (the X in the title) only
    hides it — the sessions keep living (like a hidden window; the dock can be
    restored from the QMainWindow menubar's context menu). Closing the LAST tab
    also hides the dock (last_tab_closed → hide), not destroys: the next session
    in "tabs" mode will show the same container. Session teardown — page by page
    (page.shutdown()); the container outlives its sessions."""

    def __init__(self, main_window=None):
        t = get_translator()
        super().__init__(t("terminal.dock_title"), main_window)
        self.setObjectName("terminals_dock")
        self.content = TerminalDockContent(self)
        self.setWidget(self.content)
        self.setMinimumWidth(300)
        # v1.2.2 (task 3): the last tab was closed — the sessions were already
        # cleaned up page by page, the container is empty: hide the dock (do not
        # destroy it — see the docstring).
        self.content.last_tab_closed.connect(self.hide)
