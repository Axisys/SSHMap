"""`ToolbarMixin` — the toolbar, its overflow policy and the checkable view-toggle mirrors (AGENTS.md §4.1, §4.9).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and `QMenu` / `set_action_icon` are resolved on the
facade at call time (`host_attr`), which is the `MW.<name>` test seam.

Owned here: the pinned toolbar with its `»` overflow menu and its MEASURED threshold
(`TOOLBAR_OVERFLOW_*`, `_toolbar_full_width()`, `_sync_toolbar_overflow()`), the mirror rule
(`_mark_toolbar_mirror()`) and the three-step wiring of a view toggle to the menu item that OWNS its state
(`_wire_view_toolbar_button()` / `_on_view_toolbar_toggled()` / `_sync_view_toolbar()`), plus the toolbar's
own right-click menu. `_VIEW_TOOLBAR_ITEMS` / `_VIEW_TOOLBAR_ACTIONS` live here; the facade re-exports them.
Mechanism — `DOCUMENTATION.md` §15, §41."""

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDockWidget, QMenu, QToolBar, QToolButton

try:  # v1.8rc3: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


# ── the VIEW toggles of the toolbar ──────────────────────────────────────────
# (action id, icon name, i18n key, the literal fallback of the key) — ONE group at the right end
# of the toolbar, in the order the surfaces sit in the window: the sidebar, the map (whose
# collapsedness is the LIST mode), the minimap, the legend, the activity panel, the Plugins
# window. A button MIRRORS its checkable item — the item owns the hotkey, the state and the text.
_VIEW_TOOLBAR_ITEMS = (
    ("view.toggle_sidebar", "sidebar_panel", "view.toggle_sidebar", "Sidebar / Map"),
    ("view.toggle_map", "map_panel", "view.toggle_map", "Map / List"),
    ("view.toggle_minimap", "minimap", "view.toggle_minimap", "Minimap"),
    ("view.toggle_legend", "legend", "view.toggle_legend", "Legend"),
    # v1.6.7 (ROADMAP task 4): the BOOKMARKS panel — the sixth member of the cluster, next
    # to the legend because both are floating panels over the canvas.
    ("view.toggle_bookmarks", "bookmarks", "view.toggle_bookmarks", "Bookmarks"),
    ("view.toggle_activity", "activity", "view.toggle_activity", "Activity panel"),
    # The PLUGINS window — the LAST surface of the window and the seventh mirror of the cluster
    # (the panel frame with a "P"). It adds no registry action: the shipped `plugins.window.open`
    # item of the Plugins menu stays the owner.
    ("plugins.window.open", "plugins_panel", "plugins.window.open", "Plugins window…"),
)

# action id → the MainWindow attribute holding the OWNER QAction (the wiring in
# `_setup_menubar` + the two generic slots below; the buttons themselves live in
# `self._view_toolbar_buttons`).
_VIEW_TOOLBAR_ACTIONS = {
    "view.toggle_sidebar": "act_show_sidebar",
    "view.toggle_map": "act_show_map",
    "view.toggle_minimap": "act_show_minimap",
    "view.toggle_legend": "act_show_legend",
    "view.toggle_bookmarks": "act_show_bookmarks",
    "view.toggle_activity": "act_show_activity",
    "plugins.window.open": "act_plugins_window",
}


class ToolbarMixin:
    """The toolbar, its overflow policy and the checkable view-toggle mirrors (AGENTS.md §4.1, §4.9)."""

    def _setup_toolbar(self):
        toolbar = QToolBar()
        # v1.1.2RC3 (AUDIT U2): objectName is needed by saveState()/restoreState() —
        # without it Qt writes "'objectName' not set for QToolBar" to stderr.
        toolbar.setObjectName("main_toolbar")
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        # UI polish: all actions get vector icons (ui/icons.py, replacing emoji); text-only actions
        # in the toolbar would look out of place. The pinned keep-set is the three file verbs,
        # "Center" / "Fit", undo/redo and the five view toggles; the first five are OVERFLOWABLE into
        # the "»" menu on a narrow window, the rest never move. What the SIDEBAR or the PALETTE
        # already owns is NOT repeated here; the 4th tuple element is the REGISTRY action_id.
        _fallback = {
            "file.new_project": "New Project", "file.open": "Open...", "file.save": "Save",
            "view.center_map": "Center map", "view.fit_map": "Fit Map to Content",
        }
        groups = (
            (("file.new_project", self._new_project, "new", "file.new"),
             ("file.open", self._open_project, "open", "file.open"),
             ("file.save", self._save_project, "save", "file.save")),
            (("view.center_map", self._center_view, "center", "view.center_map"),
             ("view.fit_map", self._fit_to_content, "fit", "view.fit_map")),
        )
        self._toolbar_overflow_actions = []
        # The objects the overflow policy hides: a QToolButton for an action (the QAction
        # itself stays VISIBLE — it is also inside the "»" menu) and the separator's own
        # QAction (no other widget carries it). Both answer setVisible().
        self._toolbar_overflow_items = []
        for gi, group in enumerate(groups):
            if gi:
                self._toolbar_overflow_items.append(toolbar.addSeparator())
            for key, slot, icon_name, action_id in group:
                text = self.t(key) if self._i18n_available else _fallback[key]
                action = toolbar.addAction(text, slot)
                self._register_i18n(action, key)
                # v1.3.3.3 (task 3): every one of these also exists in a menu, and the
                # MENU item is the hotkey target — the toolbar button only mirrors the
                # same slot (see the note above _apply_hotkeys).
                self._mark_toolbar_mirror(action)
                try:
                    host_attr(self, "set_action_icon")(action, icon_name)  # remembers the name for the theme walk
                except Exception:  # noqa: BLE001 — the icon is cosmetic; do not break the toolbar
                    pass
                self._toolbar_overflow_actions.append(action)
                widget = toolbar.widgetForAction(action)
                if widget is not None:
                    self._toolbar_overflow_items.append(widget)

        # Undo/redo in the toolbar (icons + text; the enabled state is driven by `QUndoStack`). The
        # sequences come from the action registry — "edit.undo"/"edit.redo" are registered as hotkey
        # targets on their EDIT-MENU items, and the toolbar buttons are MIRRORS (a second target would make
        # Ctrl+Z an "Ambiguous shortcut overload"). These two are NOT overflowable — undo is the one control
        # a user reaches for without looking.
        toolbar.addSeparator()
        self.act_undo = toolbar.addAction(
            self.t("edit.undo") if self._i18n_available else "Undo",
            self._undo)
        self._mark_toolbar_mirror(self.act_undo)
        self.act_undo.setEnabled(False)
        try:
            host_attr(self, "set_action_icon")(self.act_undo, "undo")
        except Exception:
            pass
        self.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)

        self.act_redo = toolbar.addAction(
            self.t("edit.redo") if self._i18n_available else "Redo",
            self._redo)
        self._mark_toolbar_mirror(self.act_redo)
        self.act_redo.setEnabled(False)
        try:
            host_attr(self, "set_action_icon")(self.act_redo, "redo")
        except Exception:
            pass
        self.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)

        # ── the VIEW toggles on the toolbar ──
        # FOUR checkable buttons in ONE group at the right end: the two splitter panels ("Sidebar /
        # Map" and "Map / List"), the minimap and the legend. Each MIRRORS its checkable View
        # item — the item owns the hotkey and the state, the button the click (`_setup_menubar`
        # wires the pairs and runs AFTER this method). Never overflowable: a hidden panel is lost.
        toolbar.addSeparator()
        self._view_toolbar_buttons = {}
        for action_id, icon_name, key, fallback in _VIEW_TOOLBAR_ITEMS:
            text = self.t(key) if self._i18n_available else fallback
            btn = toolbar.addAction(text)
            btn.setCheckable(True)
            btn.setChecked(True)   # synced with its action/panel/config in _setup_menubar
            btn.setToolTip(text)
            self._register_i18n(btn, key)
            # A toolbar button is a MIRROR: it must not own the action's sequence
            # (two enabled QActions with one sequence fire NEITHER — v1.3.3.3).
            self._mark_toolbar_mirror(btn)
            try:
                host_attr(self, "set_action_icon")(btn, icon_name)
            except Exception:  # noqa: BLE001 — the icon is cosmetic; do not break the toolbar
                pass
            self._view_toolbar_buttons[action_id] = btn
            btn.toggled.connect(
                lambda checked, aid=action_id: self._on_view_toolbar_toggled(aid, checked))
        # The v1.4.5 attribute survives the generalisation: it IS the legend's button.
        self._legend_toolbar_btn = self._view_toolbar_buttons["view.toggle_legend"]
        # v1.4.6: the minimap button (next to the legend) — the user asked for a switch
        # of the panel without opening the View menu.
        self._minimap_toolbar_btn = self._view_toolbar_buttons["view.toggle_minimap"]
        self._sidebar_toolbar_btn = self._view_toolbar_buttons["view.toggle_sidebar"]
        self._map_toolbar_btn = self._view_toolbar_buttons["view.toggle_map"]
        # v1.6 (ROADMAP task 7): the activity panel's button — the fifth member of the
        # cluster (the attribute survives for the same reason as the four above).
        self._activity_toolbar_btn = self._view_toolbar_buttons["view.toggle_activity"]
        # v1.6.7 (ROADMAP task 4): the bookmarks panel's button — the sixth member of the
        # cluster (the attribute survives for the same reason as the five above).
        self._bookmarks_toolbar_btn = self._view_toolbar_buttons["view.toggle_bookmarks"]
        # The Plugins window's button — the seventh member, wired in `_setup_menubar` to the
        # shipped checkable `plugins.window.open` item of the Plugins menu (its OWNER).
        self._plugins_window_toolbar_btn = self._view_toolbar_buttons["plugins.window.open"]

        # ── the "»" OVERFLOW menu ───────────────────────────────────────────
        # Not Qt's own toolbar extension: that one is a popup of ICONS with no labels, and this
        # application's actions are named by words. The menu holds the very SAME QActions the
        # toolbar carries, so the enablement, the icons and the palette cannot diverge. The
        # button is reached through an ACTION (`QAction.setVisible()`), never `addWidget()` (§41).
        overflow_action = toolbar.addAction("\u00bb")
        overflow_btn = toolbar.widgetForAction(overflow_action)
        if overflow_btn is None:   # a stripped style without a button — no overflow menu
            overflow_btn = QToolButton(toolbar)
            toolbar.addWidget(overflow_btn)
        self._toolbar_overflow_action = overflow_action
        self._toolbar_overflow_btn = overflow_btn
        overflow_btn.setObjectName("ToolbarOverflowButton")
        overflow_btn.setText("\u00bb")
        overflow_btn.setAutoRaise(True)
        # The TOOLTIP lives on the ACTION: Qt copies an action's tooltip onto its toolbar
        # button (measured — a tooltip set on the button alone is overwritten by that
        # sync), and the action is also what the language switch re-texts.
        overflow_action.setToolTip(
            self.t("toolbar.more") if self._i18n_available else "More actions")
        overflow_btn.setToolTip(overflow_action.toolTip())
        overflow_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        overflow_menu = host_attr(self, "QMenu", QMenu)(overflow_btn)
        for action in self._toolbar_overflow_actions:
            overflow_menu.addAction(action)
        overflow_menu.addSeparator()
        overflow_btn.setMenu(overflow_menu)
        self._toolbar_overflow_menu = overflow_menu
        overflow_action.setVisible(False)
        # `None` — "not computed yet", so the FIRST sync always applies (a window whose
        # width is still 0 must not be treated as "already wide").
        self._toolbar_compact = None
        # v1.5rc4: the "»" glyph is the button's TEXT, so the translated sentence can only
        # be a TOOLTIP — `_register_i18n` would replace the glyph itself. The re-text is
        # therefore done by hand in `_apply_ui_translations()` (the ACTION carries it).
        self._sync_toolbar_overflow(self.width())

    # ── v1.5rc4 (ROADMAP task 2): the toolbar overflow policy ──────────────────
    # Pinned: OVERFLOW, never wrapping; the keep-set is the five overflowable buttons plus
    # the core ones that never move (undo/redo and the four view toggles). ONE method
    # decides, and the threshold is MEASURED: the sum of what the toolbar's own widgets ask
    # for. A typed number would be wrong the moment a translation or the UI font grows.

    #: The room the toolbar keeps between its buttons and the window edge.
    TOOLBAR_OVERFLOW_SLACK = 32
    #: How much air the full set must have before the bar keeps it: the measured width
    #: times this factor. A pinned set that only fits edge-to-edge reads as "squeezed" —
    #: exactly what the release's second decision forbids — so the secondary buttons move
    #: into the "»" menu while the window is merely comfortable-narrow rather than only
    #: when it is physically impossible.
    TOOLBAR_OVERFLOW_COMFORT = 1.5

    def _toolbar_full_width(self) -> int:
        """The width the toolbar needs for the FULL pinned set (0 — no toolbar yet).

        The "»" button itself is NOT counted: it is the alternative to the set, not a
        member of it — counting it would make the measurement depend on the state it is
        supposed to decide.
        """
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None:
            return 0
        overflow_btn = getattr(self, "_toolbar_overflow_btn", None)
        total = 0
        try:
            actions = list(toolbar.actions())
        except RuntimeError:
            return 0
        for action in actions:
            widget = toolbar.widgetForAction(action)
            if widget is None or widget is overflow_btn:
                continue
            try:
                total += max(int(widget.sizeHint().width()), 8)
            except RuntimeError:
                continue  # Qt teardown — that widget is already destroyed
        return total + (self.TOOLBAR_OVERFLOW_SLACK if total else 0)

    def _sync_toolbar_overflow(self, width=None) -> bool:
        """Apply the toolbar overflow policy for ``width`` (the window's, by default).

        Returns True while the COMPACT state is in effect. Idempotent and never raises:
        every widget of the overflowable part is hidden or shown together with its
        separators, so the toolbar never shows a dangling divider.
        """
        try:
            value = int(self.width() if width is None else width)
        except (TypeError, ValueError):
            return bool(getattr(self, "_toolbar_compact", False))
        needed = self._toolbar_full_width()
        compact = 0 < value < max(int(needed * self.TOOLBAR_OVERFLOW_COMFORT), 1)
        if compact == getattr(self, "_toolbar_compact", None):
            return compact
        self._toolbar_compact = compact
        for item in getattr(self, "_toolbar_overflow_items", []):
            try:
                item.setVisible(not compact)
            except (RuntimeError, AttributeError):
                continue  # Qt teardown / an unexpected handle — the rest still applies
        # The "»" itself is the toolbar's own ACTION visibility (a widget item would be
        # re-shown by the next layout pass — see `_setup_toolbar`).
        overflow_action = getattr(self, "_toolbar_overflow_action", None)
        if overflow_action is not None:
            try:
                overflow_action.setVisible(compact)
            except RuntimeError:
                pass  # Qt teardown — the action is already destroyed
        return bool(compact)

    def toolbar_overflow_active(self) -> bool:
        """True while the toolbar is in its compact state (the topical test's seam)."""
        return bool(getattr(self, "_toolbar_compact", False))

    def _mark_toolbar_mirror(self, action) -> None:
        """v1.3.3.3: keep a toolbar button that MIRRORS a menu action shortcut-free.

        Every toolbar button duplicates a menu item one-to-one, and both QActions live
        in the same window. Registering BOTH as hotkey targets made
        ``_apply_hotkeys()`` give the same sequence to two enabled QActions — Qt then
        resolves the click with "Ambiguous shortcut overload" and fires NEITHER
        (verified offscreen: Ctrl+Shift+S was dead; v1.3.2 never hit this because the
        toolbar carried a literal ``setShortcut`` only for undo/redo, which Qt silently
        ignored as a duplicate).

        So: the MENU item owns the sequence, the toolbar button owns the click. This
        also removes a real duplication — ``toolbar.addAction(text, slot)`` would
        auto-install Qt's own "Ctrl+S"-style shortcut from the action text.
        """
        try:
            action.setShortcut(QKeySequence())   # the same "no shortcut" value the registry uses
        except (RuntimeError, TypeError):
            pass  # Qt teardown / an unexpected wrapper — the button still clicks

    def _wire_view_toolbar_button(self, action_id: str, action) -> None:
        """v1.4.6: keep a toolbar VIEW toggle in step with its checkable menu item.

        The menu item is the OWNER of the state (and of the hotkey); the button mirrors
        it — the v1.4.5 legend rule, now for all four toggles (the sidebar, the map, the
        minimap, the legend). Called from `_setup_menubar` right after each QAction
        exists; the initial sync uses BLOCKED signals, so wiring cannot drive the owner.
        """
        if action is None:
            return
        try:
            action.toggled.connect(
                lambda checked, aid=action_id: self._sync_view_toolbar(aid, checked))
        except (RuntimeError, AttributeError):
            return
        self._sync_view_toolbar(action_id, action.isChecked())

    def _on_view_toolbar_toggled(self, action_id: str, checked: bool) -> None:
        """A toolbar VIEW button was clicked — drive the checkable menu item (the owner)."""
        action = getattr(self, _VIEW_TOOLBAR_ACTIONS.get(action_id, ""), None)
        if action is None:
            return
        try:
            if action.isChecked() != bool(checked):
                action.setChecked(bool(checked))   # emits toggled → the owner slot
        except RuntimeError:
            pass  # Qt teardown — the action is already destroyed

    def _sync_view_toolbar(self, action_id: str, checked: bool) -> None:
        """Follow the owner: set the mirror's checkmark with blocked signals (no loop).

        The guard `action.isChecked() != checked` drops a STALE emission: the collapse
        rule refuses a second strip by restoring the owner's checkmark with BLOCKED
        signals (`_reject_collapse_both`), and the `toggled(False)` that caused the
        refusal is still being delivered to the other slots — without the guard the
        mirror would end up showing the state the window is NOT in. The owner's LIVE
        value is the truth, so this is the same "follow the owner" rule, not a special
        case (the refusal also resyncs explicitly, which this guard then confirms).
        """
        action = getattr(self, _VIEW_TOOLBAR_ACTIONS.get(action_id, ""), None)
        if action is not None:
            try:
                if action.isChecked() != bool(checked):
                    return  # a stale emission — the owner already moved on
            except RuntimeError:
                pass  # Qt teardown — fall through and try the button
        button = (getattr(self, "_view_toolbar_buttons", None) or {}).get(action_id)
        if button is None:
            return
        try:
            if button.isChecked() == bool(checked):
                return
            button.blockSignals(True)
            try:
                button.setChecked(bool(checked))
            finally:
                button.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown

    # ── v1.6.1 (ROADMAP task 7): the toolbar's right-click menu ────────────────

    def _panel_switch_actions(self):
        """The checkable VIEW actions of the panel cluster, in the toolbar's own order.

        ONE source for the toolbar buttons (`_VIEW_TOOLBAR_ITEMS` /
        `_VIEW_TOOLBAR_ACTIONS`) and for the toolbar's own context menu, so the menu and
        the buttons cannot drift apart. An action whose LABEL is empty is skipped: a
        nameless row is never rendered anywhere (the `createPopupMenu()` rule).
        """
        out = []
        for action_id, _icon, _key, _fallback in _VIEW_TOOLBAR_ITEMS:
            action = getattr(self, _VIEW_TOOLBAR_ACTIONS.get(action_id, ""), None)
            if action is None:
                continue
            try:
                if not action.text().strip():
                    continue
            except RuntimeError:
                continue  # Qt teardown — the action is already destroyed
            out.append(action)
        return out

    def createPopupMenu(self):
        """The toolbar's right-click menu — built from rows that HAVE a name.

        Qt's own `QMainWindow::createPopupMenu()` lists the `toggleViewAction()` of every
        toolbar and dock; the main bar is a bare `QToolBar()` with no window title, so
        that row is a lone checkmark with an EMPTY label (v1.6.1, ROADMAP task 7). This
        override lists the PANEL switches instead — their labels come from the action
        registry, so the menu adds no i18n key — plus the dock rows that really carry a
        name. A widget that cannot be NAMED is not listed at all, and neither is the
        toolbar itself.
        """
        menu = host_attr(self, "QMenu", QMenu)(self)
        for action in self._panel_switch_actions():
            menu.addAction(action)
        named_docks = []
        for dock in self.findChildren(QDockWidget):
            action = dock.toggleViewAction()
            if action is None:
                continue
            try:
                if not action.text().strip():
                    continue
            except RuntimeError:
                continue
            named_docks.append(action)
        if named_docks:
            menu.addSeparator()  # the panels above, the containers below
            for action in named_docks:
                menu.addAction(action)
        return menu
