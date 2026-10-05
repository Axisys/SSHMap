"""`ViewMixin` — the map view's own commands: the camera, the zoom, the focus domains and the selection (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: the centring/fitting/zoom family with its "the map is collapsed" guard, the camera flight to a
card (`_fly_camera_to_node()`), the selection gesture and the collapse-all family, the three keyboard domains
(`_focus_map()` / `_focus_domain_step()` / `_active_terminal_canvas()`) and the arrow hover focus. The map
DIMMING those states feed stays with the window (its ONE owner). Mechanism — `DOCUMENTATION.md` §15, §35, §37."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

try:  # a string annotation must resolve to a name the module BINDS (tests/test_audit_v161.py §3)
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode


class ViewMixin:
    """The map view's own commands: the camera, the zoom, the focus domains and the selection (AGENTS.md §4.1)."""

    # ── v1.5rc4 (ROADMAP task 5/6): the keyboard domains ───────────────────────
    # The window has three of them — the map, the sidebar and (in `terminal_mode =
    # "tabs"`) the terminal dock — and each shows the SAME focus ring. "Focus the map"
    # (the ONE new registry action of the release) hands the keyboard to the canvas, and
    # `_focus_domain_step()` is what Ctrl+Tab calls to walk between the domains.

    def _focus_map(self):
        """View → Focus the map: hand the keyboard to the canvas (v1.5rc4, task 6)."""
        view = getattr(self, "view", None)
        if view is None:
            return
        if getattr(self, "_map_collapsed", False):
            return  # a collapsed map has no surface to focus (the View-action rule)
        try:
            view.setFocus(Qt.FocusReason.ShortcutFocusReason)
        except (RuntimeError, TypeError):
            pass  # Qt teardown — nothing to focus

    def _focus_domain_step(self, step: int = 1):
        """Move the keyboard to the next/previous keyboard domain (Ctrl+Tab).

        The domains are the sidebar's tree, the map canvas and the terminal canvas of the
        ACTIVE session (when the dock mode is on) — the three surfaces that show a focus
        ring. A domain that is not reachable (a collapsed map, no session, no sidebar) is
        skipped; an unknown widget loses to the first reachable one.
        """
        candidates = []
        tree = getattr(getattr(self, "sidebar", None), "tree", None)
        if tree is not None and tree.isVisible():
            candidates.append(tree)
        view = getattr(self, "view", None)
        if view is not None and view.isVisible() and not getattr(self, "_map_collapsed", False):
            candidates.append(view)
        session = self._active_terminal_canvas()
        if session is not None:
            candidates.append(session)
        if not candidates:
            return None
        current = QApplication.focusWidget()
        index = -1
        for position, widget in enumerate(candidates):
            if widget is current or (current is not None and widget.isAncestorOf(current)):
                index = position
                break
        target = candidates[(index + int(step)) % len(candidates)]
        try:
            target.setFocus(Qt.FocusReason.OtherFocusReason)
        except (RuntimeError, TypeError):
            return None
        return target

    def _active_terminal_canvas(self):
        """The canvas of the VISIBLE terminal session, or None (v1.5rc4).

        Windows mode and dock mode both keep their pages in `_terminal_windows` and both
        hold them in a `session_tabs` QTabWidget; the first live page that is the CURRENT
        tab of a visible container (a split pane counts — it is visible under the tabs) is
        "where the keys would go". Used by `_focus_domain_step` only — never by the
        session logic.
        """
        for page in list(getattr(self, "_terminal_windows", None) or []):
            try:
                canvas = getattr(page, "widget", None)
                if canvas is None or not canvas.isVisible():
                    continue
                window = getattr(page, "_host_window", None)
                container = window if window is not None else page.window()
                if container is None or not container.isVisible():
                    continue
                tabs = getattr(window, "session_tabs", None) if window is not None else None
                if tabs is None:
                    tabs = getattr(container, "session_tabs", None)
                if (tabs is not None and tabs.currentWidget() is not page
                        and not getattr(page, "_is_split_pane", False)):
                    continue   # a background tab — its canvas is not what the user sees
                return canvas
            except (RuntimeError, AttributeError):
                continue
        return None

    def _iter_server_nodes(self):
        """All ServerNodes in the scene (for collapse/expand all)."""
        scene = getattr(self, "scene", None)
        if scene is None:
            return []
        try:
            return [it for it in scene.items()
                    if isinstance(it, ServerNode)]
        except Exception:
            return []

    def _set_all_collapsed(self, collapsed: bool):
        """v0.8.4: collapse/expand all plaques; the state is saved into the project."""
        changed = False
        for node in self._iter_server_nodes():
            if bool(getattr(node.data, "collapsed", False)) != collapsed:
                node.toggle_collapsed()
                changed = True
        if changed:
            self._mark_dirty()

    def _collapse_all_servers(self):
        self._set_all_collapsed(True)

    def _expand_all_servers(self):
        self._set_all_collapsed(False)

    def _select_node(self, node: ServerNode, center: bool = False, smooth: bool = False):
        # v0.9.9.1: a reentry guard instead of scene.blockSignals — the other
        # selectionChanged slots keep working during the programmatic change; the echo
        # handler returns immediately on the flag, and the explicit sync below
        # is idempotent (a full state recompute, "tree = scene selection").
        self._selection_syncing = True
        try:
            self.scene.clearSelection()
            node.setSelected(True)
        finally:
            self._selection_syncing = False
        self._sync_selection_state()
        # v1.2.4.1 (task 5): the map is collapsed — centering is skipped (selection
        # and the accent still work; no exceptions and no auto-show of the map). All paths
        # are covered: "Show on map" (_reveal_node_on_map) and the search navigation Enter/Shift+Enter.
        if center and not getattr(self, "_map_collapsed", False):
            # v1.4.4 (ROADMAP task 2): `smooth=True` is the "Show on map" reveal — the camera
            # FLIES (ui/motion.py) instead of jumping; every other caller keeps the instant
            # centering (a search step and the palette want the result NOW, and their tests
            # compare the scroll state with a direct centerOn).
            if smooth and self._fly_camera_to_node(node):
                return
            self.view.stop_camera_flight()  # v1.4.4: an instant move cancels a running flight
            self.view.centerOn(node)

    # ── v1.4.4 (ROADMAP task 2): the camera flights ─────────────────────

    def _fly_camera_to_node(self, node: "ServerNode") -> bool:
        """Fly the camera to a node's CARD centre, keeping the current zoom (True — flying).

        The reveal is a "here it is", not a zoom change: the target SCALE is the live one,
        so the flight is a pure pan. The anchor is `card_rect_scene()` (the card without
        the v1.4.2 shadow halo) — the v1.4.2 rule for every consumer of a node's edge.
        """
        try:  # v1.4.4: the motion standards (ui/motion.py)
            from ui.motion import fly_camera
        except ImportError:  # flat launch from the project root
            try:
                from motion import fly_camera
            except ImportError:
                return False
        getter = getattr(node, "card_rect_scene", None)
        try:
            rect = getter() if callable(getter) else node.sceneBoundingRect()
        except (RuntimeError, AttributeError):
            return False
        return fly_camera(self.view, self.view.zoom, rect.center()) is not None

    def _on_hover_focus_changed(self, _arrow=None):
        """v1.4.4 (ROADMAP task 4): the arrow hover focus moved — recompute the ONE dim state.

        The arrow's hover is a REASON to re-evaluate the map, never a second writer of the
        dim: `_apply_map_dimming` merges the hover focus with the tag filter and the search.
        """
        self._apply_map_dimming()

    def _center_view(self):
        """UI polish: center on the map content, not on the origin.

        Before, centerOn(0, 0) — with nodes at negative coordinates the view went to
        an empty corner of the scene (a v0.8 review bug).
        v1.2.4.1 (task 5): the map is collapsed — a no-op (no exceptions, no auto-show).
        """
        if self._map_collapsed:
            return
        rect = self.view.content_bounding_rect()
        # v1.4.4 (ROADMAP task 1): "center the map" is an instant move — cancel a flight
        self.view.stop_camera_flight()
        if rect is None or rect.isEmpty():
            self.view.centerOn(0, 0)
            return
        self.view.centerOn(rect.center())

    def _fit_to_content(self):
        """UI polish: "Fit map" — all nodes and notes inside the visible area.

        v1.4.4 (ROADMAP task 2): the ACTION flies to the fit target (ui/motion.py — 250 ms,
        OutQuad, interruptible) instead of snapping; `MapView.fit_to_content()` stays the
        instant primitive for tools/tests and is the fallback when there is nothing to
        frame (an empty map → the same "nothing to fit" line) or the view has no geometry yet.
        v1.2.4.1 (task 5): the map is collapsed — a no-op (no exceptions, no auto-show).
        """
        if self._map_collapsed:
            return
        if not self.view.fly_to_content():
            self.statusBar().showMessage(self.t("status.fit_nothing"))

    def _on_zoom_changed(self, zoom: float):
        """UI polish: the zoom percentage in the status bar (the MapView.zoomChanged signal)."""
        try:
            self.zoom_label.setText(f"{int(round(zoom * 100))}%")
        except RuntimeError:
            pass  # Qt teardown — the status bar widget has already been destroyed

    def _reset_zoom(self):
        # AUDIT v0.7.2 (low #19): the public MapView method instead of poking view._zoom
        self.view.reset_zoom()

    # ── v1.3.3.3 (ROADMAP task 2): the zoom actions of the View menu ──────────────
    # The step API lives on MapView (zoom_in/zoom_out/_zoom_by); these two slots only
    # add the "the map is collapsed" guard that every view action of the window has
    # (v1.2.4.1 task 5: a view action on a collapsed map is a silent no-op).

    def _zoom_in(self):
        """View → Zoom In (Ctrl+=): one step in, anchored on the view centre."""
        if self._map_collapsed:
            return
        self.view.zoom_in()

    def _zoom_out(self):
        """View → Zoom Out (Ctrl+-): one step out, anchored on the view centre."""
        if self._map_collapsed:
            return
        self.view.zoom_out()
