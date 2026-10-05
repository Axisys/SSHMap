"""`PanelsMixin` — the sidebar/map panel mechanism: the 18 px strip, the splitter and the LIST mode (AGENTS.md §4.1, §4.12).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: the ONE "collapse into a thin strip" mechanism and its three control paths (the menu item, the
corner button and the strip click all converge on `_set_panel_collapsed()`), the 18 px invariant with the
divider's affordance (`_sync_splitter_handle()`), the LIST mode (`_sync_list_mode()`), the saved panel widths
(`_apply_splitter_state_from_config()`) and the two window-internal graphics the mechanism needs —
`_diamond_icon()` and `_CollapseStrip`, both re-exported by the facade. Mechanism —
`DOCUMENTATION.md` §15, §36."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

try:  # v1.2.5: the central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.4.3: the Qt half of the theme — a QSS string is a VALUE
    from . import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:
        theme_qss = None

try:  # v1.3.3.6: the panel widths — base64 QSplitter.saveState()
    from ..modules.window_geometry import restore_splitter_state
except ImportError:
    from modules.window_geometry import restore_splitter_state


# ── v1.2.4.1: collapsing the sidebar/map into a thin strip (ROADMAP v1.2.4.1) ──

def _diamond_icon():
    """Vector "◇" diamond on a 20×20 canvas (corner collapse buttons).

    instead of "›"/"‹" chevrons — a single diamond on both
    panels (sidebar and map — both at the bottom right; the top of the map is reserved
    for the minimap). Same technique as ui/icons.py (QPainterPath on a transparent QPixmap),
    but the icon lives locally: per the spec only the sidebar_panel/map_panel
    pair goes into _DRAWERS (the "View" menu items), while the button/strip diamonds
    are window-internal graphics.
    """
    pm = QPixmap(20, 20)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    # read at CALL time — the icon is rebuilt by refresh_theme()
    # (before the fix this read a value captured at import time and the diamond
    # stayed dark-theme pale after a switch to LIGHT).
    pen = QPen(QColor(theme.ICON_COLOR), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(10.0, 4.5)
    path.lineTo(15.5, 10.0)
    path.lineTo(10.0, 15.5)
    path.lineTo(4.5, 10.0)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


class _CollapseStrip(QWidget):
    """Thin clickable strip of a collapsed panel (~18 px; ROADMAP v1.2.4.1, task 1).

    A click ANYWHERE expands the panel (expand_requested); inside — the "◇" diamond
    at the bottom right (instead of the chevron, QA request) + a tooltip
    (set by MainWindow).
    The real panel widget is hidden at the same time: a hidden child takes 0px —
    native Qt, no custom layout. Colors — the app's dark Fusion palette
    (theme.WINDOW_BG / theme.BASE_BG, v1.2.5): the strip reads well on both the sidebar and the map background.
    """

    expand_requested = Signal()
    STRIP_WIDTH = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.STRIP_WIDTH)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.expand_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # v1.2.5: colors — from the central theme (ui/theme.py); values unchanged.
        p.fillRect(self.rect(), QColor(theme.SURFACE_ALT if self._hover else theme.BASE_BG))
        # "◇" diamond at the bottom right (QA request — instead of the chevron;
        # the same spot as the expanded panel's corner button — the diamond is "at the bottom"
        # both before and after collapsing).
        pen = QPen(QColor(theme.ICON_COLOR), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = float(self.width()) - 9.0, float(self.height()) - 12.0
        path = QPainterPath()
        path.moveTo(cx, cy - 4.5)
        path.lineTo(cx + 4.5, cy)
        path.lineTo(cx, cy + 4.5)
        path.lineTo(cx - 4.5, cy)
        path.closeSubpath()
        p.drawPath(path)
        p.end()

# The upper bound of a QWidget's width. QWIDGETSIZE_MAX is a C macro in qwidget.h and
# is therefore not exposed by PySide6 — the value is the documented one.
_WIDGET_MAX_WIDTH = 16777215


class PanelsMixin:
    """The sidebar/map panel mechanism: the 18 px strip, the splitter and the LIST mode (AGENTS.md §4.1, §4.12)."""

    def _style_collapse_btn(self, btn) -> None:
        """v1.5.6 (ROADMAP task 4): give a panel collapse button its FRAME.

        The two "◇" corners are plain QToolButtons — no `setAutoRaise` — and their look
        comes from the ONE `collapse.button` entry of the QSS registry (a QSS string is a
        VALUE, so it is re-applied by `_refresh_icons()` on a theme switch, next to the
        icon ink). Never raises: a cosmetic style must not be able to break the chrome.
        """
        if btn is None or theme_qss is None:
            return
        try:
            theme_qss.refresh(btn, "collapse.button")
        except RuntimeError:
            pass  # Qt teardown — the button is already destroyed

    # ── v1.2.4.1 (ROADMAP v1.2.4.1): ONE "collapse into a thin strip" mechanism ──
    # The three control points of each panel (corner button, strip click,
    # "View" menu item) all go through one checkable QAction: a Qt click inverts checked itself,
    # buttons/strips call action.toggle() — all paths emit toggled(bool) into the slots below.

    def _toggle_sidebar(self, checked: bool = True):
        """v1.1.1 (item 5) -> v1.2.4.1: compatibility — checked = expanded.

        Before: setVisible on the whole sidebar (a single widget in the QSplitter). Now:
        an expanded<->collapsed toggle — a collapsed sidebar does not lose its data
        (search/tag filter/tree survive, refresh_sidebar works); in its place
        is a ~18px strip.
        """
        if self._set_panel_collapsed("sidebar", not checked) == "forbidden":
            self._reject_collapse_both("sidebar")

    def _on_sidebar_toggled(self, checked: bool):
        """v1.2.4.1: menu item "View -> Sidebar" (toggled; checked = expanded)."""
        if self._set_panel_collapsed("sidebar", not checked) == "forbidden":
            self._reject_collapse_both("sidebar")

    def _on_map_toggled(self, checked: bool):
        """v1.2.4.1: menu item "View -> Map" (toggled; checked = expanded)."""
        if self._set_panel_collapsed("map", not checked) == "forbidden":
            self._reject_collapse_both("map")

    def _reject_collapse_both(self, which: str):
        """refuse to collapse the SECOND panel.

        All three control paths converge on a checkable QAction, and on refusal Qt has
        already inverted checked (or a programmatic setChecked did) — the checkbox is
        restored to the actual state with signals blocked (the
        pattern: the checkbox and the mechanism stay in sync) + a status-bar hint.
        """
        act = getattr(self, "act_show_sidebar" if which == "sidebar" else "act_show_map", None)
        if act is not None:
            try:
                act.blockSignals(True)
                act.setChecked(True)  # the panel stays expanded
            finally:
                act.blockSignals(False)
        # v1.4.6: the toolbar mirror was told by `toggled` — and that signal is blocked
        # on this path, so it has to be told explicitly (a refused collapse must not
        # leave the toolbar button showing a state the window is not in).
        self._sync_view_toolbar(
            "view.toggle_sidebar" if which == "sidebar" else "view.toggle_map", True)
        try:
            self.statusBar().showMessage(self.t("status.collapse_both_forbidden"))
        except Exception:  # noqa: BLE001 — the hint must not break the refusal
            pass

    def _set_panel_collapsed(self, which: str, collapsed: bool) -> str:
        """v1.2.4.1 (task 1): collapse/expand the sidebar or the map into a strip.

        `which` — "sidebar" | "map"; `collapsed` — the target state (True = strip).
        Idempotent: a no-op if the panel is already in the target state (toggled/trigger
        may arrive again). In the collapsed state the real widget is hidden (a hidden
        container child takes 0px — native Qt); a clickable strip is shown; the container
        width is fixed by setSizes + minimumWidth=18. On expand
        the panel's OWN width from BEFORE the collapse is restored (saved on the
        first collapse of the current cycle); if the other panel is also collapsed — it
        stays a strip (18px) and the expanded one takes the rest of the space. The state
        is persistent: ui_sidebar_collapsed / ui_map_collapsed in config.json
        (a merge-write via i18n.save_config) — it survives a restart.

        both panels SIMULTANEOUSLY collapsed are
        NOT ALLOWED — at least one (the sidebar or the map) is always expanded, otherwise
        the window is a "shell" of two strips (even with the "Terminals" dock open).
        Collapsing the second panel is forbidden for ALL control paths (button/strip/menu/
        programmatic setChecked — they all converge on toggled). Returns "changed" / "noop" / "forbidden".

        v1.4.5 (ROADMAP task 5): the collapsed container is capped at the strip width
        (`setMaximumWidth`) and the divider handle is DISABLED while a panel is a strip —
        `minimumWidth` alone would let the handle stretch it into empty space. Both
        invariants are applied by
        `_sync_splitter_handle()` at the END of this method, so every control path and
        every resize source (handle, window resize, dock, state restore) agrees.

        v1.4.6 (ROADMAP task 2): the MAP's collapsedness is also the LIST MODE — the
        sidebar container is the full window width in that state, and the tree fills it
        with the server parameters (`sidebar.list.*`, see `_sync_list_mode()`). The
        trigger is deliberately this method and not the QAction: the diamond, the strip,
        the menu item, the startup config, the settings dialog and the splitter restore
        all converge here. The state stays `ui_map_collapsed` in config.json — the mode
        IS the collapsedness, so nothing new has to be persisted.
        """
        if which == "sidebar":
            panel, strip = self.sidebar, self._sidebar_strip
            container = self._sidebar_container
            key, flag_attr = "ui_sidebar_collapsed", "_sidebar_collapsed"
            min_w = self.SIDEBAR_MIN_WIDTH
            other_flag = "_map_collapsed"
        elif which == "map":
            panel, strip = self.view, self._map_strip
            container = self._map_container
            key, flag_attr = "ui_map_collapsed", "_map_collapsed"
            min_w = self.MAP_MIN_WIDTH
            other_flag = "_sidebar_collapsed"
        else:
            return "noop"
        if getattr(self, flag_attr) == bool(collapsed):
            self._sync_splitter_handle()
            self._sync_list_mode()
            return "noop"  # already in the target state — a no-op
        if collapsed and getattr(self, other_flag, False):
            self._sync_splitter_handle()
            self._sync_list_mode()
            return "forbidden"  # the other panel is already a strip — both cannot be collapsed

        try:
            w_strip = _CollapseStrip.STRIP_WIDTH
            sizes = self._splitter.sizes()
            own_w = sizes[0] if which == "sidebar" else sizes[1]
            if collapsed:
                saved_attr = f"_saved_panel_width_{which}"
                # Save the width only if the other panel is expanded: otherwise the "own"
                # width is overstated (the other is a 18px strip) and restoring it on the
                # second expand would squeeze the first to its minimum. Without the save —
                # the 250/950 default on expand (a sensible fallback).
                if getattr(self, saved_attr, None) is None \
                        and not getattr(self, other_flag, False):
                    setattr(self, saved_attr, int(own_w))  # the width BEFORE collapsing
                panel.hide()
                strip.show()
                self._apply_collapsed_strip_sizes(which)
            else:
                container.setMinimumWidth(min_w)
                panel.show()
                strip.hide()
                saved = getattr(self, f"_saved_panel_width_{which}", None)
                setattr(self, f"_saved_panel_width_{which}", None)
                total = max(self._splitter.width(), 2 * w_strip + 10)
                x_w = int(saved) if saved else (250 if which == "sidebar" else 950)
                if getattr(self, other_flag, False):
                    # the other panel is collapsed — it stays a strip (the 18px invariant)
                    if which == "sidebar":
                        self._splitter.setSizes([x_w, w_strip])
                    else:
                        self._splitter.setSizes([w_strip, x_w])
                else:
                    if which == "sidebar":
                        self._splitter.setSizes([x_w, total - x_w])
                    else:
                        self._splitter.setSizes([total - x_w, x_w])
        except RuntimeError:
            self._sync_splitter_handle()
            self._sync_list_mode()
            return "noop"  # Qt teardown — the C++ object is already destroyed

        setattr(self, flag_attr, bool(collapsed))
        # v1.4.5 (ROADMAP task 5): the width caps (the collapsed one is exactly a strip
        # wide) and the handle's enabled state — ONE place, every control path.
        self._sync_splitter_handle()
        # v1.4.6 (ROADMAP task 2): the map's collapsedness IS the list mode — the
        # sidebar switches to the wide table (and back) from this one place.
        self._sync_list_mode()
        try:
            from i18n import save_config as _save_cfg
            _save_cfg({key: bool(collapsed)})
        except Exception:  # noqa: BLE001 — persistence must not break the toggle
            pass
        return "changed"

    def _sync_splitter_handle(self) -> None:
        """v1.4.5 (ROADMAP task 5): the 18px invariant + the divider's affordance.

        The drift this fixes: a collapsed container was pinned only by `minimumWidth`,
        which is a HINT to the QSplitter — dragging the handle (or an external resize
        of the window/dock) stretched the strip into empty space while the mechanics
        (`_sidebar_collapsed`/`_map_collapsed`) kept saying "collapsed", and the panel
        widths diverged from the saved state.

        Two things are enforced here, for BOTH panels symmetrically:

          * **the width cap** — a collapsed container gets
            `setMaximumWidth(_CollapseStrip.STRIP_WIDTH)`, an expanded one releases it
            (`_WIDGET_MAX_WIDTH`). Any resize source then has exactly one possible
            outcome: the expanded panel takes the whole delta and the strip stays 18 px;
          * **the affordance** — `splitter.handle(0)` is ENABLED only while BOTH panels
            are expanded (there is nothing to resize otherwise), with a tooltip that
            says so. Applied at the end of `_set_panel_collapsed` (all control paths
            converge there), after the collapse state is applied from the config and
            after the splitter state is restored.
        """
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        try:
            both_expanded = (not getattr(self, "_sidebar_collapsed", False)
                             and not getattr(self, "_map_collapsed", False))
            handle = splitter.handle(0)
            if handle is not None:
                handle.setEnabled(both_expanded)
                handle.setToolTip(self.t("view.splitter_handle_tooltip"))
            for flag, container in (("_sidebar_collapsed", getattr(self, "_sidebar_container", None)),
                                    ("_map_collapsed", getattr(self, "_map_container", None))):
                if container is None:
                    continue
                if getattr(self, flag, False):
                    container.setMaximumWidth(_CollapseStrip.STRIP_WIDTH)
                else:
                    container.setMaximumWidth(_WIDGET_MAX_WIDTH)
        except RuntimeError:
            pass  # Qt teardown — the splitter or a container is already destroyed

    def _sync_list_mode(self) -> None:
        """v1.4.6 (ROADMAP task 2): the map's collapsedness IS the sidebar's LIST mode.

        With the map collapsed the sidebar container takes the whole window width
        (QSplitter redistributes), so `SidebarPanel.set_list_mode(True)` turns the tree
        into the table of server parameters — and back on expansion. This is the ONE
        reader of the collapse flag for the layout: the panel owns WHAT the list looks
        like, this method only reports the state (never the reverse).

        Idempotent and cheap by construction: `set_list_mode()` answers False when the
        layout already matches, so the repeated calls from the collapse control paths,
        the startup config and the settings dialog never rebuild the tree twice. Only a
        REAL switch refreshes the rows (`refresh_sidebar()` — the one composition hook
        every add/remove/import/load/undo already passes through).

        v1.5.5 (ROADMAP task 2): the two INVENTORY actions follow the mode. "Copy List" and
        "Export List…" report the TABLE, so they are enabled exactly while the table exists
        — a disabled item (the `act_backups` pattern for "no project is open") is the honest
        affordance for "there is no list on screen right now"; the enable state is applied on
        EVERY call, not only on a real switch, because the actions are built after the first
        `_sync_list_mode()` of the startup path.
        """
        panel = getattr(self, "sidebar", None)
        if panel is None:
            return
        try:
            list_mode = bool(getattr(self, "_map_collapsed", False))
            for action in (getattr(self, "act_copy_list", None),
                           getattr(self, "act_export_list", None)):
                if action is not None:
                    action.setEnabled(list_mode)
            if panel.set_list_mode(list_mode):
                self.refresh_sidebar()
        except RuntimeError:
            pass  # Qt teardown — the panel or its tree is already destroyed

    def _apply_collapsed_strip_sizes(self, which: str) -> None:
        """Force the [strip | expanded panel] sizes of a COLLAPSED panel.

        v1.2.4.1 had this arithmetic inline in `_set_panel_collapsed`; v1.3.3.6
        (ROADMAP task 4) reuses it after the splitter-state restore, so a saved layout
        can never resurrect the width of a panel the user collapsed before closing the
        window. The caller guarantees the OTHER panel is expanded (collapsing both is
        forbidden — `_set_panel_collapsed` returns "forbidden").

        v1.4.5 (ROADMAP task 5): the collapsed container is ALSO capped at the strip
        width (`setMaximumWidth`) — with only `minimumWidth` + `setSizes` a later
        resize (the window, the dock, the handle) would stretch the strip again.
        """
        w_strip = _CollapseStrip.STRIP_WIDTH
        container = self._sidebar_container if which == "sidebar" else self._map_container
        container.setMinimumWidth(w_strip)
        container.setMaximumWidth(w_strip)
        total = max(self._splitter.width(), 2 * w_strip + 10)
        if which == "sidebar":
            self._splitter.setSizes([w_strip, total - w_strip])
        else:
            self._splitter.setSizes([total - w_strip, w_strip])

    def _apply_splitter_state_from_config(self) -> None:
        """v1.3.3.6 (ROADMAP task 4): restore the panel widths — applied LAST.

        The ORDER is the contract (the v1.4.5 splitter-handle rules build on it):
        this runs AFTER `restore_window_geometry()`/`restoreState()` (early in
        `__init__`) and AFTER the collapsed-panel states applied by
        `_apply_ui_options_from_config()`, and it re-applies the 18px strip sizes of
        every panel that is collapsed — a saved layout must not resurrect a width the
        user collapsed away.

        A missing key / a broken value leaves the 250/950 defaults of `_setup_ui`
        untouched (`restore_splitter_state` returns False and never raises).

        v1.4.5 (ROADMAP task 5): the width caps and the handle's enabled state are
        re-applied afterwards in EVERY case (a restored layout must not re-enable a
        divider next to a collapsed panel).

        v1.4.6 (ROADMAP task 2): the LIST mode is re-applied here too — the collapsed
        map may have come from the config (a restored layout never carries the mode),
        and the column set must already be the wide one when the first rows are built.
        """
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        try:
            if not restore_splitter_state("ui_splitter_state", splitter):
                return
            for which, flag in (("sidebar", "_sidebar_collapsed"),
                                ("map", "_map_collapsed")):
                if getattr(self, flag, False):
                    self._apply_collapsed_strip_sizes(which)
        except RuntimeError:
            pass  # Qt teardown — the splitter is already destroyed
        finally:
            self._sync_splitter_handle()
            self._sync_list_mode()
