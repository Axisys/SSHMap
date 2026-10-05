# -*- coding: utf-8 -*-
"""The Files PANEL of a terminal window, and the widget HANDOVER a session page performs.

`_FilesPanel` is the window's right-hand column: a `_CollapseStrip` plus a `QStackedWidget` with ONE
page per session, so a tab switch shows THAT session's own tree. `TerminalFilesPanelMixin` is the
PAGE's half — the Files widget detaches from the tab strip into the stack and comes back at the
shipped index — while the page keeps the OWNER (`page.sftp_tab` never changes) and the panel never
touches the tab itself. The mode is the config key `terminal_files_mode`; the declared floors, the
width memory and the four readers are `modules/terminal_config.py`'s. Mechanism — `DOCUMENTATION.md`
§63; the contract — `AGENTS.md` §4.3."""

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSplitter, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

try:
    from .command_library import (PANEL_BODY_MIN_WIDTH, _CollapseStrip, _WIDGET_MAX_WIDTH,
                                  _diamond_icon, hand_over_splitter_width)
except ImportError:  # flat launch from the project root
    from command_library import (PANEL_BODY_MIN_WIDTH, _CollapseStrip, _WIDGET_MAX_WIDTH,
                                 _diamond_icon, hand_over_splitter_width)

try:
    from .terminal_config import (FILES_PANEL_CONFIG_COLLAPSED, FILES_PANEL_MIN_PX,
                                  FILES_PANEL_WIDTH_DEFAULT, load_files_panel_settings)
except ImportError:  # flat launch from the project root
    from terminal_config import (FILES_PANEL_CONFIG_COLLAPSED, FILES_PANEL_MIN_PX,
                                 FILES_PANEL_WIDTH_DEFAULT, load_files_panel_settings)

# The shared lazy translator of the terminal family (the `command_library` pattern — the panel is on
# the window's construction path, so the i18n import stays lazy).
_t_cache = None

def get_translator():
    """Safe i18n helper — a cached `t()` or the `[key]` fallback. Never raises."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:  # noqa: BLE001 — a build without i18n renders the key
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache

class _FilesPanel(QWidget):
    """v1.7.1 (ROADMAP v1.7.1): the right-hand FILES panel of the terminal window.

    The mirrored `CommandLibraryPanel`: a `_CollapseStrip` (24 px) plus a body, both members
    of ONE layout so the hidden one costs 0 px, and ONE owner-written config key for the
    fold. The body carries the panel's header (the tab's own title + the fold button) and a
    `QStackedWidget` with **ONE page per session** — the session's OWN Files widget, moved
    here by the window (`attach_page()`) while the mode is on.

    The panel owns the STACK and its chrome; it owns neither a session nor a listing. Every
    page-level read survives the move because the page keeps `page.sftp_tab`
    (`TerminalSessionPage.detach_files_tab()` / `attach_files_tab()`), and the panel never
    touches an SftpTab.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminalFilesPanel")
        t = get_translator()
        self._collapsed = False
        self._expanded_width = 0
        #: The width the OPEN panel asks for. It starts at the declared default, follows the
        #: divider the USER dragged (`_on_splitter_moved()`) and survives a fold and a close.
        #: Deliberately NOT a config key: the panel owns ONE `ui_*` key (the fold) and the
        #: MODE is the settings hub's `terminal_files_mode` (v1.7.1.1) — a width the user can
        #: drag is not worth a second one.
        self._panel_width = FILES_PANEL_WIDTH_DEFAULT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The folded state: the thin strip (a click anywhere — expand), the same widget the
        # left panel uses — ONE strip for both side panels of the application.
        self._strip = _CollapseStrip(self)
        self._strip.expand_requested.connect(lambda: self.set_collapsed(False))
        self._strip.setToolTip(t("terminal.files_panel_expand_tooltip"))
        layout.addWidget(self._strip)

        self._body = QWidget(self)
        self._body.setMinimumWidth(PANEL_BODY_MIN_WIDTH)
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(6, 6, 6, 6)
        bl.setSpacing(4)

        head = QHBoxLayout()
        # The panel is the Files view of the ACTIVE session, so its header names exactly what
        # the tab it replaced was called (`sftp.tab_files`) — no second spelling of "Files".
        self._title = QLabel(t("sftp.tab_files"))
        tf = self._title.font()
        tf.setBold(True)
        self._title.setFont(tf)
        self._collapse_btn = QToolButton()
        self._collapse_btn.setIcon(_diamond_icon())
        self._collapse_btn.setToolTip(t("terminal.files_panel_collapse_tooltip"))
        self._collapse_btn.clicked.connect(lambda: self.set_collapsed(True))
        head.addWidget(self._title, 1)
        head.addWidget(self._collapse_btn)
        bl.addLayout(head)

        # ONE page per SESSION (not per pane): the window re-parents a session's own Files
        # widget here when the mode is on and hands it back when the mode goes off.
        self.stack = QStackedWidget()
        bl.addWidget(self.stack, 1)
        layout.addWidget(self._body)

        # The stored fold. Applied without a write-back; the splitter arithmetic is a no-op
        # at construction time (the panel is not in a QSplitter yet) and is re-applied by the
        # window when the mode really opens.
        self.set_collapsed(bool(load_files_panel_settings()["collapsed"]), persist=False)

    # ── the sessions' pages ──────────────────────────────────────────────

    def attach_page(self, page, widget=None) -> bool:
        """Put ONE session's Files widget into the stack (`widget` — its `sftp_tab`).

        Idempotent: a widget that is already a page of the stack is only re-added when it
        came from another parent (a session re-created after a reconnect). Never raises.
        """
        widget = widget if widget is not None else getattr(page, "sftp_tab", None)
        if widget is None:
            return False
        try:
            if self.stack.indexOf(widget) < 0:
                self.stack.addWidget(widget)
            self.stack.setCurrentWidget(widget)
        except RuntimeError:
            return False   # Qt teardown — the stack is already gone
        return True

    def detach_page(self, page) -> bool:
        """Take ONE session's Files widget OUT of the stack (the page takes it back).

        The widget is not deleted and not re-parented: `QStackedWidget.removeWidget()` drops
        the PAGE. The caller either re-inserts it into the session's tab strip
        (`TerminalSessionPage.attach_files_tab()`) or it dies with the session. Never raises.
        """
        widget = getattr(page, "sftp_tab", None)
        if widget is None:
            return False
        try:
            if self.stack.indexOf(widget) < 0:
                return False
            self.stack.removeWidget(widget)
        except RuntimeError:
            return False   # Qt teardown
        return True

    def pages(self) -> list:
        """The Files widgets currently carried by the stack (for the teardown walks)."""
        try:
            return [self.stack.widget(i) for i in range(self.stack.count())]
        except RuntimeError:
            return []

    def set_current(self, page) -> bool:
        """Show the widget of `page` (the session the tab strip just switched to).

        The stack follows `session_tabs.currentChanged` — a tab switch must show THAT
        session's own tree, with its own browsed directory and its own viewer, which is the
        whole reason the panel is a stack of per-session pages instead of one shared tree.
        False — the page has no widget here (a split pane, a page without the SFTP tab).
        """
        widget = getattr(page, "sftp_tab", None)
        if widget is None:
            return False
        try:
            if self.stack.indexOf(widget) < 0:
                return False
            self.stack.setCurrentWidget(widget)
        except RuntimeError:
            return False   # Qt teardown
        return True

    # ── the fold (state — the single key ui_files_panel_collapsed) ────────

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, on: bool, persist: bool = True):
        """Fold/unfold the panel; the state — ONE config key, written by its OWNER.

        The `CommandLibraryPanel.set_collapsed()` twin, including the v1.5rc5 hand-over of
        the freed space: visibility and the `setMaximumWidth` cap alone left the width dead.
        """
        self._collapsed = bool(on)
        try:
            t = get_translator()
            self._strip.setVisible(bool(on))
            self._body.setVisible(not on)
            if on:
                self._strip.setToolTip(t("terminal.files_panel_expand_tooltip"))
            else:
                self._collapse_btn.setToolTip(t("terminal.files_panel_collapse_tooltip"))
        except RuntimeError:
            return   # the C++ object is already deleted (a close race)
        self.apply_width()
        if persist:
            try:
                from i18n import save_config
                save_config({FILES_PANEL_CONFIG_COLLAPSED: bool(on)})
            except Exception:  # noqa: BLE001 — a read-only HOME keeps the fold for the session
                pass

    def apply_width(self, want: int = None) -> bool:
        """Hand the panel its width (the fold's cap or the open width). False — no splitter.

        `want` (px) is the width the OPEN panel asks for; None means "the width this panel
        remembers" — the declared default the first time in a window, the user's divider drag
        afterwards. A folded panel always asks for its strip.
        """
        if self._collapsed:
            return self._apply_panel_width(True)
        if want is None:
            want = int(getattr(self, "_panel_width", 0) or 0) or FILES_PANEL_WIDTH_DEFAULT
        return self._apply_panel_width(False, want=want)

    def _host_splitter(self):
        """The QSplitter this panel is a member of (its parent after `addWidget`).

        The FIRST call also wires the divider watch (`splitterMoved`), which is how the panel
        learns the width the USER dragged — the splitter is known only after `addWidget()`, so
        the connection cannot live in `__init__`.
        """
        try:
            parent = self.parentWidget()
        except RuntimeError:
            return None
        if not isinstance(parent, QSplitter):
            return None
        if getattr(self, "_splitter_watch", None) is not parent:
            try:
                parent.splitterMoved.connect(self._on_splitter_moved)
            except (RuntimeError, TypeError):
                pass   # Qt teardown / a foreign splitter — the width memory simply stands still
            self._splitter_watch = parent
        return parent

    def _on_splitter_moved(self, _pos=None, _index=None):
        """The USER dragged a divider: the panel's live width becomes the one to come back to.

        It is the ONLY honest signal for it — a width read straight after `show()` is Qt's
        layout answer (the panel's minimum), and writing THAT into the memory would make the
        panel open at 200 px instead of the declared width.
        """
        if self._collapsed:
            return   # the strip's 24 px are not a width anybody chose
        try:
            width = int(self.width())
        except RuntimeError:
            return   # Qt teardown
        if width > _CollapseStrip.STRIP_WIDTH:
            self._panel_width = width

    def remember_width(self) -> int:
        """Remember the CURRENT width as the one to open with (the mode is going off)."""
        if not self._collapsed:
            self._on_splitter_moved()
        return int(getattr(self, "_panel_width", 0) or 0)

    def _apply_panel_width(self, collapsed: bool, want: int = None) -> bool:
        """The width cap of a folded panel + the hand-over of the freed space.

        The EXACT mirror of the left panel's arithmetic, sharing its ONE implementation
        (`hand_over_splitter_width`): the panel here is the LAST member of
        `[commands | terminal | files]`, so the delta goes to the two columns on its left.
        Never raises.
        """
        splitter = self._host_splitter()
        if splitter is None:
            return False
        try:
            sizes = list(splitter.sizes())
            index = splitter.indexOf(self)
            laid_out = index >= 0 and len(sizes) >= 2 and sum(sizes) > 0
            if collapsed:
                if laid_out and sizes[index] > _CollapseStrip.STRIP_WIDTH:
                    self._expanded_width = sizes[index]
                self._body.setMinimumWidth(0)
                self.setMaximumWidth(_CollapseStrip.STRIP_WIDTH)
                self.setMinimumWidth(_CollapseStrip.STRIP_WIDTH)
                if not laid_out:
                    return False
                return hand_over_splitter_width(splitter, index, _CollapseStrip.STRIP_WIDTH)
            self.setMaximumWidth(_WIDGET_MAX_WIDTH)
            self._body.setMinimumWidth(PANEL_BODY_MIN_WIDTH)
            if not laid_out:
                return False
            target = int(want or 0)
            if target <= 0:
                target = max(self.sizeHint().width(), PANEL_BODY_MIN_WIDTH)
            target = min(target, max(sum(sizes) - 1, _CollapseStrip.STRIP_WIDTH))
            # The floor is asked for only as far as the width really allows: a window too
            # narrow for both floors keeps a smaller panel instead of an unsatisfiable pair.
            self.setMinimumWidth(min(FILES_PANEL_MIN_PX, target))
            self._expanded_width = target
            self._panel_width = target   # the width the OPEN panel comes back to
            return hand_over_splitter_width(splitter, index, target)
        except RuntimeError:
            return False   # Qt teardown — the splitter is already destroyed

    # ── live i18n / theme (the container rule) ───────────────────────────

    def retranslate(self):
        """Re-text the panel's own chrome (`sftp.tab_files` + the two fold tooltips)."""
        try:
            self._title.setText(get_translator()("sftp.tab_files"))
            self._collapse_btn.setToolTip(get_translator()("terminal.files_panel_collapse_tooltip"))
            self._strip.setToolTip(get_translator()("terminal.files_panel_expand_tooltip"))
        except RuntimeError:
            pass   # Qt teardown — the panel is already destroyed

    def refresh_theme(self):
        """Re-apply the theme to the hand-painted strip and the fold button (a VALUE)."""
        for widget in (getattr(self, "_strip", None), getattr(self, "_collapse_btn", None)):
            if widget is None:
                continue
            try:
                widget.update()
            except RuntimeError:
                continue

    def release_floors(self):
        """Drop the panel's own floors — the mode is OFF (a hidden member pins nothing).

        The mirror of the window's `_reset_files_panel_floors()` for the panel's OWN
        `setMinimumWidth`/`setMaximumWidth` pair (Qt gotcha #13: a maximum that lives past
        its state breaks the size accounting of a later hide/show).
        """
        try:
            self.setMinimumWidth(0)
            self.setMaximumWidth(_WIDGET_MAX_WIDTH)
            self._body.setMinimumWidth(PANEL_BODY_MIN_WIDTH)
        except RuntimeError:
            pass   # Qt teardown

class TerminalFilesPanelMixin:
    """The PAGE's half of the Files panel: the widget handover and the mode's own consequences.

    The window re-parents a session's Files widget into its right-hand panel; the page keeps the
    OWNER (`self.sftp_tab` never changes, so every page-level read and the teardown keep working)
    and answers here for the two moments that are its own: the widget LEAVING the tab strip and the
    channel the panel needs. The mixin needs no facade global — the translator is this module's.
    """

    def show_files_tab(self) -> bool:
        """v1.7rc1 (ROADMAP v1.7rc1, task 3): bring the "Files" tab to the front.

        The door the Files Commander control opens: turning the two-pane view ON while the
        session shows the CANVAS would build panes nobody can see, so the container asks the
        page for the tab — and the ordinary `_on_tab_changed` path opens the SFTP channel
        lazily on the way. False when this page has no Files tab at all (a split pane is
        built `with_sftp=False`), which is exactly the "the action is disabled there" rule.
        v1.7.1: False too while the window shows the Files tree in its right-hand PANEL — the
        page has no Files tab then (`detach_files_tab()`) and nothing to bring to the front.
        """
        if self.sftp_tab is None or getattr(self, "_files_panel_on", False):
            return False
        try:
            self.tabs.setCurrentWidget(self.sftp_tab)
        except RuntimeError:
            return False  # Qt teardown — the C++ object is already gone
        return True

    def detach_files_tab(self):
        """Hand the Files widget over to a host panel: remove the TAB, return the WIDGET.

        None when this page has no Files tab (a split pane) or the panel is already off the
        strip. The widget keeps its parent until the caller re-parents it into the stack —
        `QTabWidget.removeWidget()` drops the TAB, never the object.
        """
        tab = getattr(self, "sftp_tab", None)
        if tab is None:
            return None
        try:
            index = self.tabs.indexOf(tab)
            if index < 0:
                return None
            self.tabs.removeTab(index)
        except RuntimeError:
            return None  # Qt teardown — the strip is already gone
        return tab

    def attach_files_tab(self) -> bool:
        """Take the Files widget back from a host panel: re-insert the TAB it lost.

        The position is the SHIPPED one (`Terminal | Files | History`, index 1), so the
        panel being switched off restores the exact strip the session had before it — the
        page's own tab order is not the host's business. Idempotent and teardown-safe.
        """
        tab = getattr(self, "sftp_tab", None)
        if tab is None:
            return False
        try:
            if self.tabs.indexOf(tab) >= 0:
                return True
            self.tabs.insertTab(1, tab, get_translator()("sftp.tab_files"))
        except RuntimeError:
            return False  # Qt teardown — the strip is already gone
        return True

    def set_files_panel(self, on: bool) -> bool:
        """The window shows (on) or hides this session's Files tree in its right panel.

        The ONE consequence the PAGE owns: the SFTP channel must be open even though the
        user never switched to a Files tab — a switch to the tab was the lazy-open trigger
        (`_on_tab_changed`) and the panel mode has no such tab, so the panel would otherwise
        sit in `sftp.waiting_connection` for the whole session. The channel is therefore
        opened HERE when the transport is already alive, and `_on_connected_for_sftp()` opens
        it for a session that is still connecting. Never raises.
        """
        on = bool(on)
        self._files_panel_on = on
        if not on:
            return self._files_panel_on
        try:
            self._ensure_sftp()
        except RuntimeError:
            pass  # Qt teardown — the session is already going away
        return self._files_panel_on

    @property

    def files_panel_on(self) -> bool:
        """Is this session's Files tree shown in a host panel (and therefore not in a tab)?"""
        return bool(getattr(self, "_files_panel_on", False))
