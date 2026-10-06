# -*- coding: utf-8 -*-
""""Terminals" as a dock of the map window, for `terminal_mode = "tabs"` (AGENTS.md §4.3).

`TerminalDockContent` is an embeddable session container — the analogue of `SSHTerminalWindow` for
`MainWindow`: the session area is the `QSplitter [session_tabs | split_host]` of the SAME controller the
window builds (`modules/terminal_split.py`, `DOCUMENTATION.md` §14g) plus the dock's own status line. The
contract is the window's: one tab per session, the node alias on the tab, `confirm_close()` → the
idempotent `shutdown()` on close, and the LAST tab only emits `last_tab_closed` (the container outlives
its sessions). `TerminalsDock` is the detachable QDockWidget: floated — a separate window, docked — back
on the map, so ONE mechanism yields both display modes. Test seams are the page's: the thread class and
`QMessageBox` are taken from the `ssh_terminal` module at call time."""
import itertools

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QProgressBar,
    QDockWidget, QSplitter,
)

try:
    from .terminal_page import TerminalSessionPage
except ImportError:
    from modules.terminal_page import TerminalSessionPage

# v1.7rc1 (ROADMAP v1.7rc1, task 3): the Files Commander control of the tab-bar corner —
# the SAME widget the standalone terminal window uses. v1.7.2 (task 2): the corner also
# carries the SPLIT button, because the dock is a container too.
try:
    from .sftp_tab import CommanderCorner
except ImportError:
    from modules.sftp_tab import CommanderCorner

# v1.6.4 (ROADMAP task 4): the ACTIVITY mark of an inactive session — the SAME renderer the
# terminal window uses (the page module owns it, both containers call it).
try:
    from .terminal_page import refresh_session_activity, render_session_activity
except ImportError:
    from modules.terminal_page import refresh_session_activity, render_session_activity

# v1.7.2 (ROADMAP v1.7.2, task 2): the SPLIT — ONE controller for both containers, and the
# parent-chain hook lookup that reaches `MainWindow._adopt_split_session` through the dock.
try:
    from .terminal_split import TerminalSplit, find_host_hook, CONTAINER_DOCK
except ImportError:
    from terminal_split import TerminalSplit, find_host_hook, CONTAINER_DOCK

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

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None


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

    Composition: the vertical `QSplitter [session_tabs | split_host]` of the SAME controller the
     standalone window builds (v1.7.2, task 2) + a status line (`status_label` + `sftp_progress`).
     Pages are created with parent=session_tabs (destroyed together with the container) and bound to
     the content via set_host_window(self) — the page's close_terminal() calls close_page(self), i.e.
     the same path as in SSHTerminalWindow (v1.2.1). The split PANE is an ordinary page built
     `with_sftp=False` and marked `_is_split_pane`, so the limit, the green dot and the multi-input
     provider treat it exactly as they treat the window's pane.

    Signal bridge of the ACTIVE page: status_message → status_label
    (timeout_ms > 0 — timer-based auto-clear with a token-guard),
    progress_busy/update/hidden → sftp_progress. On tab switch the bridge is
    reconnected; messages of inactive tabs do not reach the status line
    (v1.2.1 behavior).
    """

    # v1.2.2: the last tab was closed — the container is empty (TerminalsDock hides the dock)
    last_tab_closed = Signal()

    #: The container KIND the session registry filters on (`terminal_split.container_windows`):
    #: a dock is never a merge target and never the `"single"` mode's window.
    CONTAINER_KIND = CONTAINER_DOCK

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # v1.2.2 (task 2): a QTabWidget of TerminalSessionPage — each tab = one
        # SSH session; tabs are closable: closing a tab = cleanup of the LOCAL page.
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.session_tabs.currentChanged.connect(self._on_current_tab_changed)

        # v1.7.2 (task 2): the DOCK's split — the SAME construct as the window's, so the session
        # area is `V[session_tabs | split_host]` here too. The dock has no close of its own, so the
        # controller writes the two shared keys on the gesture (the `ui_cmdlib_collapsed` rule).
        self.split = TerminalSplit(self, persist_toggle=True)
        self.split_host = self.split.host
        self._v_splitter = self.split.splitter
        self.act_split, self.btn_split = self.split.build_action()

        # v1.7rc1 (ROADMAP v1.7rc1, task 3): the Files Commander control in the corner of the
        # dock's tab bar, with the split BUTTON beside it (v1.7.2, task 2: the dock is a
        # container too). The mode a session shows is the SESSION's (`SftpTab.commander`), kept
        # in step by `_sync_commander()`.
        self.commander = CommanderCorner(self, split_button=self.btn_split)
        self.commander.act.toggled.connect(self._on_commander_toggled)
        self.session_tabs.setCornerWidget(self.commander, Qt.Corner.TopRightCorner)

        # The "Terminal Macros" panel to the left of the tabs — the same one as in SSHTerminalWindow
        # (QSplitter [cmdlib_panel | V(session_tabs | split_host)]; a single config key
        # `ui_cmdlib_collapsed` for both containers). The panel's status messages go to the DOCK's
        # status line via the existing `_on_page_status_message` bridge (token-guard; the `(str, int)`
        # signature matches).
        self.cmdlib_panel = CommandLibraryPanel(self.session_tabs, parent=self)
        self.cmdlib_panel.status_message.connect(self._on_page_status_message)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.cmdlib_panel)
        splitter.addWidget(self.split.splitter)
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
        # v1.4.3 (ROADMAP task 4): the style comes from the ONE registry
        # (ui/theme_qss.py) — the constructor and refresh_theme() share it.
        if theme_qss is not None:
            self.status_label.setStyleSheet(theme_qss.style("status.sftp_row"))
        else:
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

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to the dock content.

        The container's own status label plus every session it holds (the pages
        own their canvases, status lines, SFTP tabs and find bars). Never raises.
        """
        if theme_qss is not None:
            try:
                theme_qss.refresh(self.status_label, "status.sftp_row")
            except RuntimeError:
                pass  # Qt teardown — the label is already destroyed
        for page in self._all_pages():
            hook = getattr(page, "refresh_theme", None)
            if not callable(hook):
                continue
            try:
                hook()
            except RuntimeError:
                continue
            except Exception:  # noqa: BLE001 — one session must not stop the rest
                continue
        # v1.6.4 (ROADMAP task 4): the activity mark is a PIXMAP — a VALUE (§4.6): re-render it
        # in the new theme tone instead of keeping the old colour on the tab.
        refresh_session_activity(self)

    def retranslate(self):
        """v1.3.3.1: re-text the content and its sessions in the current language.

        The close tooltip of every tab, everything each page owns (the
        `Terminal | Files` titles, the SFTP buttons/headers) and the container's own
        "Terminal macros" panel. Every string already has an i18n key (ZERO new
        keys); the module translator is looked up at call time — no cache to
        invalidate. The dock's own title belongs to `TerminalsDock.retranslate()`.
        Never raises — the dead-C++-object discipline of every container method.
        """
        t = get_translator()
        try:
            for i in range(self.session_tabs.count()):
                self.session_tabs.setTabToolTip(i, t("terminal.tab_close_tooltip"))
        except RuntimeError:
            return  # the C++ object was already destroyed (a close race)
        for page in self._all_pages():
            try:
                page.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the page is already destroyed
        # v1.6.4 (ROADMAP task 4): the activity mark's TOOLTIP is translated text — re-render
        # the tabs so an inactive session's sentence follows the language switch.
        refresh_session_activity(self)
        # v1.7rc1: the Files Commander control of the corner (its label and its tooltip).
        commander = getattr(self, "commander", None)
        if commander is not None:
            commander.retranslate()
        # v1.7.2 (task 2): the dock's own split action and its corner button.
        self.split.retranslate()
        # v1.3.3.1: the "Terminal macros" panel belongs to the CONTAINER (the dock
        # owns one, the window owns another), so it is re-texted here.
        cmdlib = getattr(self, "cmdlib_panel", None)
        if cmdlib is not None:
            try:
                cmdlib.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed

    # ── v1.2.2: tabs = sessions (SSHTerminalWindow contract, v1.2.1) ─────────

    def _all_pages(self) -> list:
        """Every live session of this container — the tabs AND the split pane."""
        try:
            pages = [self.session_tabs.widget(i) for i in range(self.session_tabs.count())]
        except RuntimeError:
            pages = []  # the C++ object was already destroyed (a close race)
        pane = self.split.pane
        if pane is not None:
            pages.append(pane)
        return [p for p in pages if p is not None]

    def add_session(self, server_data, password: str = None,
                    initial_command: str = "", split: bool = False) -> "TerminalSessionPage":
        """A new session = a new tab (the existing "connect to node" path).

        The page is created with parent=session_tabs, bound to the host
        (set_host_window(self) — close_page lives on the content) and added as
        a tab: title — the node alias, tooltip — terminal.tab_close_tooltip.
        The new tab is activated explicitly (Qt: addTab makes only the FIRST
        tab current).

        `split=True` (v1.7.2, task 2) — the SPLIT PANE instead of a tab: the SAME page the window's
        pane is (no SFTP tab, no status line, the `_is_split_pane` marker), created in `split_host`
        and NOT activated as a tab. The caller — the ONE split action — shows the host.
        """
        t = get_translator()
        if split:
            page = TerminalSessionPage(
                server_data, parent=self.split_host, with_sftp=False,
                with_status_line=False, split=True,
                password=password, initial_command=initial_command)
            page.set_host_window(self)
            page._is_split_pane = True
            self._wire_page(page)
            try:
                self.split_host.layout().addWidget(page)
            except (RuntimeError, AttributeError):
                pass  # the host was already destroyed (a close race) — the page lives on
            return page
        page = TerminalSessionPage(
            server_data, parent=self.session_tabs,
            password=password, initial_command=initial_command)
        page.set_host_window(self)
        self._wire_page(page)
        idx = self.session_tabs.addTab(page, server_data.alias)
        self.session_tabs.setCurrentIndex(idx)
        # v1.6.4 (ROADMAP task 4): the FIXED icon slot (a transparent mark) + the ordinary close
        # tooltip of a fresh tab, through the ONE renderer both containers share.
        render_session_activity(self.session_tabs, page, t)
        return page

    def _wire_page(self, page):
        """v1.7.2 (task 2): let the container follow the FOCUS of a canvas (the window's rule).

        `focusChanged` is the application-level signal the window already uses — here it is the
        dock's own slot, so a pane that holds the keyboard keeps the bridge (and the corner
        control) even while the dock is embedded in the map window. Never raises.
        """
        try:
            page.widget.installEventFilter(self)
        except (RuntimeError, AttributeError):
            pass  # a test double without a canvas / a dead C++ object

    def eventFilter(self, obj, event):
        """A canvas FocusIn re-points the dock's status bridge at the session just clicked."""
        if event.type() == QEvent.Type.FocusIn:
            self._refresh_bridge()
        return super().eventFilter(obj, event)

    def close_page(self, page):
        """Close ONE tab — cleanup of the LOCAL page (the "ask" confirm_close gate
        → unified teardown shutdown); neighboring tabs are untouched. Closing the
        LAST tab does NOT destroy the container: the last_tab_closed signal
        (TerminalsDock hides the dock; the next session in "tabs" mode will show it).

        v1.7.2 (task 2): the SPLIT PANE has no tab, so its own close paths (a session error →
        `page.close_terminal()` → here) are routed to the ONE split teardown through the action.
        """
        idx = self.session_tabs.indexOf(page)
        if idx < 0:
            if page is self.split.pane:
                self.split.set_enabled(False)
            return  # the tab was already removed (teardown race) / the pane's own path
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
        if self.session_tabs.count() == 0 and self.split.pane is None:
            self.last_tab_closed.emit()

    # ── v1.7.2 (task 2): the dock's SPLIT — the same controller as the window's ──

    def active_session(self):
        """The session the USER is in — the FOCUSED split pane, otherwise the current tab.

        The command library of the dock asks for it, so a macro lands in the pane the user
        clicked, exactly as in the standalone window (v1.3.3.5 semantics).
        """
        pane = self.focused_split_pane()
        if pane is not None:
            return pane
        try:
            return self.session_tabs.currentWidget()
        except RuntimeError:
            return None

    def command_library(self):
        """The container's ONE command library panel — the hook the History tab resolves.

        The macro panel is one per CONTAINER while the History tab is per SESSION, so the tab walks
        its parent chain (`modules/command_history.container_library`) and asks this hook — the
        mirror of the shipped `active_session` seam, where the library asks the container.
        """
        return getattr(self, "cmdlib_panel", None)

    def focused_split_pane(self):
        """The split pane while the keyboard focus is INSIDE it (None otherwise). Never raises."""
        pane = self.split.pane
        if pane is None:
            return None
        try:
            focus = QApplication.focusWidget()
        except RuntimeError:
            return None
        if focus is None:
            return None
        try:
            if focus is pane or pane.isAncestorOf(focus):
                return pane
        except RuntimeError:
            return None
        return None

    def split_server_data(self, page=None):
        """The node of the pane — the OWNER session's data (fallback: the first tab's)."""
        if page is None:
            page = self.session_tabs.currentWidget()
        data = getattr(page, "server_data", None)
        if data is not None:
            return data
        try:
            first = self.session_tabs.widget(0)
        except RuntimeError:
            first = None
        return getattr(first, "server_data", None)

    def split_password(self, page=None):
        """The credentials of the pane — the SAME session's password (never the model's)."""
        if page is None:
            page = self.session_tabs.currentWidget()
        thread = getattr(page, "terminal_thread", None)
        return getattr(thread, "password", "") or ""

    def register_split_session(self, page):
        """Hand the pane to the host registry through the PARENT CHAIN (dock → MainWindow)."""
        sink = find_host_hook(self, "_adopt_split_session")
        if sink is None:
            return
        try:
            sink(page)
        except Exception:  # noqa: BLE001 — the registry must never break the split
            pass

    def attach_split_pane(self, pane) -> bool:
        """The pane is open: its live status joins the dock's ONE status line and the bridge."""
        try:
            pane.status_message.connect(self._on_page_status_message)
        except (RuntimeError, AttributeError):
            pass  # a test double / a teardown race — the pane simply has no line
        try:
            self._on_page_status_message(pane.session_status, 0)
        except (RuntimeError, AttributeError):
            pass  # a test double without the property — no line to render
        self._refresh_bridge()
        return True

    def detach_split_pane(self, pane) -> bool:
        """The pane is closing — its status connection leaves with it (idempotent)."""
        try:
            pane.status_message.disconnect(self._on_page_status_message)
        except (TypeError, RuntimeError):
            pass  # not connected / the C++ object was already destroyed
        return True

    def _refresh_bridge(self):
        """The bridge target — the FOCUSED pane if the keyboard is in it, else the current tab."""
        pane = self.focused_split_pane()
        if pane is not None:
            self._set_bridged_page(pane)
            return
        try:
            cur = self.session_tabs.currentWidget()
        except RuntimeError:
            cur = None
        self._set_bridged_page(cur)

    # ── v1.7rc1 (ROADMAP v1.7rc1, task 3): the Files Commander of the ACTIVE session ──

    def _commander_tab(self):
        """The Files tab of the VISIBLE session (None — no session on screen / a split pane)."""
        page = self._bridged_page
        return getattr(page, "sftp_tab", None)

    def _on_commander_toggled(self, on: bool):
        """The corner control asked for the two-pane view of the visible session."""
        tab = self._commander_tab()
        ok = False
        if tab is not None:
            try:
                ok = bool(tab.set_commander(bool(on)))
            except (RuntimeError, AttributeError):
                ok = False
        if ok and on:
            page = self._bridged_page
            hook = getattr(page, "show_files_tab", None)
            if callable(hook):
                try:
                    hook()   # the panes live in the Files tab — bring them on screen
                except RuntimeError:
                    pass  # Qt teardown — the page is already destroyed
        if not ok:
            self._sync_commander(force_off=True)

    def _sync_commander(self, force_off: bool = False):
        """Show the visible session's mode in the corner control (the ONE place).

        The action's signals are blocked while the state is written, so a tab switch
        re-shows a session's own mode without re-entering the slot that owns it. Never
        raises — a re-text or a close race must not break the container.
        """
        corner = getattr(self, "commander", None)
        if corner is None:
            return
        tab = None if force_off else self._commander_tab()
        try:
            corner.set_enabled(tab is not None)
            corner.set_state(bool(tab is not None and tab.commander))
        except RuntimeError:
            pass  # Qt teardown — the corner is gone

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
        # v1.7.2 (task 3): the split action mirrors the ACTIVE session — re-read on every switch,
        # before the focused-pane branch returns (the pane keeps its owner's answer).
        self.split.sync_owner()
        self._set_bridged_page(page)
        # v1.6.1 (ROADMAP task 8): the tab the user just switched TO owns the keyboard —
        # a fresh session is usable without a click on the canvas. Duck-typed hook: a page
        # that cannot take the focus (a split pane) answers False and is left alone.
        claim = getattr(page, "claim_focus", None)
        if callable(claim):
            try:
                claim()
            except RuntimeError:
                pass  # Qt teardown (a close race)

    def _set_bridged_page(self, page):
        """Bridge of the ACTIVE tab's signals into the dock's status line; on tab
        switch — reconnection (inactive tabs' messages do not arrive). SFTP
        progress is synchronized with the active tab's state.

        v1.6.4 (ROADMAP task 4): the bridged page IS the visible session, so the activity mark
        of an inactive tab is cleared here — one place for the tab switch (idempotent).
        """
        old = self._bridged_page
        if old is not None and old is not page and old is not self.split.pane:
            try:
                old.status_message.disconnect(self._on_page_status_message)
                old.progress_busy.disconnect(self._on_page_progress_busy)
                old.progress_update.disconnect(self._on_page_progress_update)
                old.progress_hidden.disconnect(self.sftp_progress.hide)
            except (TypeError, RuntimeError):
                pass  # the slot was not connected / the C++ object deleted — nothing to do
        self._bridged_page = page
        if page is None:
            self._sync_commander()
            return
        # v1.6.4 (ROADMAP task 4): the visible session has no "new output" to announce.
        clear = getattr(page, "set_activity", None)
        if callable(clear):
            try:
                clear(False)
            except RuntimeError:
                pass  # Qt teardown — the page is already destroyed
        try:
            if page is not self.split.pane:
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
        # v1.7rc1: the corner control follows the visible session (its own mode, its label).
        self._sync_commander()

    # ── v1.6.4 (ROADMAP task 4): the activity mark of an inactive session ────

    def session_is_visible(self, page) -> bool:
        """The container's answer to "is `page` the session on screen?" — the mark's ONE rule.

        v1.7.2 (task 2): the dock has a split pane now, so the rule is the window's — the FOCUSED
        pane wins over the current tab. Never raises.
        """
        pane = self.focused_split_pane()
        if pane is not None:
            return page is pane
        try:
            return self.session_tabs.currentWidget() is page
        except RuntimeError:
            return False

    def session_activity_changed(self, page):
        """Re-render ONE session's tab: the activity mark and its tooltip (idempotent)."""
        render_session_activity(self.session_tabs, page, get_translator())

    def session_title_changed(self, page):
        """The remote program set a new `OSC 0`/`OSC 2` title — re-render that tab's TOOLTIP.

        The dock names the container `terminal.dock_title` (its title is not a session's), so the
        remote title lives on the session's own tab tooltip — the same second channel the window
        uses. Never raises.
        """
        try:
            render_session_activity(self.session_tabs, page, get_translator())
        except RuntimeError:
            pass  # Qt teardown — the tab strip is already gone

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

    def retranslate(self):
        """v1.3.3.1: re-text the dock title (`terminal.dock_title`) and its content."""
        try:
            self.setWindowTitle(get_translator()("terminal.dock_title"))
        except RuntimeError:
            return  # the C++ object was already destroyed (a close race)
        try:
            self.content.retranslate()
        except RuntimeError:
            pass  # Qt teardown — the content is already destroyed

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): pass the theme switch down to the dock content."""
        try:
            self.content.refresh_theme()
        except RuntimeError:
            pass  # Qt teardown — the content is already destroyed
