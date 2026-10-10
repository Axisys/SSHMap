"""`MinimapMixin` — the minimap panel: its UI state, its placement and its camera bridge (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and the shared `_saved_position()` parser stays on
the window.

Owned here: the `ui_minimap*` UI state (`_read_minimap_settings()` / `_save_minimap_config()`), the
right-edge anchor with the fold, the yield to an open search bar, the save-as-it-moves gesture and the
camera bridge `_on_minimap_center()`. Mechanism — `DOCUMENTATION.md` §34."""
from PySide6.QtCore import QPoint


class MinimapMixin:
    """The minimap panel: its UI state, its placement and its camera bridge."""

    def _setup_minimap(self):
        """Create the minimap panel (a child of the MapView), its state and its wiring.

        The widget paints the scheme at fit scale and asks for a camera move through
        `center_requested`; the CAMERA stays here (the search-bar split: the widget owns
        no view logic). Visibility is the `ui_minimap` key of `~/.sshmap/config.json`
        (a UI state written by its owner — NOT a settings-hub key, like
        `ui_cmdlib_collapsed`), read once at startup with the default True.
        """
        try:
            from ui.minimap import MinimapWidget
        except ImportError:  # flat launch from the project root
            from minimap import MinimapWidget

        self.minimap = MinimapWidget(self.view)
        self.minimap.center_requested.connect(self._on_minimap_center)
        # v1.4.6: the title band folds the panel sideways; the WINDOW persists it and
        # re-places the panel (its width changed — it is anchored to the right edge).
        self.minimap.collapsed_changed.connect(self._on_minimap_collapsed_changed)
        # v1.4.6: the MOVE gesture (a long press, then a drag) — the panel reports where
        # it landed, the WINDOW remembers it (`ui_minimap_position`, the legend pattern).
        self.minimap.moved.connect(self._on_minimap_moved)
        # Reposition on every view resize / splitter drag (the map_search pattern).
        self.view.resized.connect(self._position_minimap)
        (self._minimap_enabled, self._minimap_collapsed,
         self._minimap_pos) = self._read_minimap_settings()
        # v1.5rc5 (N6): a saved position describes the EXPANDED panel — start from that width
        # so a window restored FOLDED still keeps the band on the right edge it hangs from.
        self._minimap_width = int(MinimapWidget.DEFAULT_WIDTH)
        self.minimap.set_collapsed(bool(self._minimap_collapsed))
        self._sync_minimap_visibility()
        self._position_minimap()

    def _minimap_wanted(self) -> bool:
        """The panel's visibility asks TWO questions (v1.9.7, ROADMAP task 6).

        The user's key AND "the map holds at least one card": a minimap of nothing navigates
        nowhere, so an empty canvas hides the panel WITHOUT touching the saved preference —
        `ui_minimap` keeps whatever the user chose, and the panel returns with the first card.
        """
        if not bool(getattr(self, "_minimap_enabled", True)):
            return False
        try:
            return len(list(self.scene.nodes())) > 0
        except (AttributeError, RuntimeError):
            return True   # the scene is not built yet / gone — the key alone decides

    def _sync_minimap_visibility(self):
        """Apply the two questions to the panel (idempotent, never throws).

        The comparison is `isHidden()` — the EXPLICIT state this method owns. `isVisible()` is
        false for every child of a window that has not been shown yet, and reading it here would
        leave the panel's own decision unset (it would appear with the window).
        """
        mini = getattr(self, "minimap", None)
        if mini is None:
            return
        try:
            wanted = self._minimap_wanted()
            if mini.isHidden() == (not wanted):
                return   # already in the wanted state — a hidden parent is not a decision
            mini.setVisible(wanted)
            if wanted:
                self._position_minimap()
                mini.refresh()   # hidden while the map changed — rebuild the layer
        except RuntimeError:
            pass  # Qt teardown — the panel is already destroyed

    def _read_minimap_settings(self):
        """`ui_minimap*` from the config → (visible, collapsed, position|None).

        v1.4.6: the panel's own UI state grew to the legend's trio — the visibility, the
        side fold (`ui_minimap_collapsed`) and the position (`ui_minimap_position`,
        `{x, y}`). A bool wins, anything else (missing/broken) → the default: the panel
        is visible, unfolded, in the top-right corner.
        """
        visible, collapsed, position = True, False, None
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the feature is simply on
            return visible, collapsed, position
        if isinstance(cfg.get("ui_minimap"), bool):
            visible = bool(cfg["ui_minimap"])
        if isinstance(cfg.get("ui_minimap_collapsed"), bool):
            collapsed = bool(cfg["ui_minimap_collapsed"])
        position = self._saved_position(cfg.get("ui_minimap_position"))
        return visible, collapsed, position

    def _on_minimap_collapsed_changed(self, collapsed: bool):
        """The minimap was folded/unfolded through its title band (v1.4.6).

        The state is written by the WINDOW (the widget owns no config) and the panel is
        re-placed: it is anchored to the RIGHT edge, so its x changed with its width.
        """
        self._minimap_collapsed = bool(collapsed)
        self._save_minimap_config({"ui_minimap_collapsed": bool(collapsed)})
        self._position_minimap()

    def _on_minimap_moved(self, position):
        """The user MOVED the panel (a long press, then a drag): remember where (v1.4.6).

        The widget has already moved itself; this only persists the spot — the
        `_on_legend_moved` pattern, which is what makes the panel stay detached from the
        corner across restarts (and what switches `_position_minimap()` from the default
        corner to the saved spot).

        v1.5 (ROADMAP): a drop within `SNAP_PX` of an anchored edge (RIGHT|TOP) instead
        RE-ANCHORS the panel — the saved position is cleared and the ordinary rules (the
        corner, the fold and the "below an open search bar" step) come back by themselves.
        """
        try:
            pos = QPoint(int(position.x()), int(position.y()))
        except (TypeError, ValueError, AttributeError):
            return
        if self._snap_panel(getattr(self, "minimap", None), pos, "rt"):
            self._minimap_pos = None
            self._save_minimap_config({"ui_minimap_position": {"x": None, "y": None}})
            self._position_minimap()   # the anchor it was dropped on, applied at once
            return
        self._minimap_pos = pos
        self._save_minimap_config({"ui_minimap_position": {"x": self._minimap_pos.x(),
                                                          "y": self._minimap_pos.y()}})

    def _save_minimap_config(self, data: dict) -> None:
        """Merge-write the minimap's own UI state (the `ui_legend*` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the gesture
            pass

    def _toggle_minimap(self, checked: bool):
        """v1.4.2: show/hide the minimap + persist `ui_minimap` (a merge write).

        v1.9.7 (ROADMAP task 6): the item writes the PREFERENCE; what is on screen is the two
        questions of `_minimap_wanted()` — so a user on an empty map is not shown a panel with
        nothing in it, and the choice they made is waiting for the first card.
        """
        mini = getattr(self, "minimap", None)
        if mini is None:
            return
        visible = bool(checked)
        self._minimap_enabled = visible
        try:
            self._sync_minimap_visibility()
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._save_minimap_config({"ui_minimap": visible})

    def _position_minimap(self):
        """v1.4.2: the panel in the TOP-RIGHT corner of the map (12 px inset).

        The top of the map belongs to the minimap (the map-collapse diamond sits in the
        BOTTOM-right corner). While the
        search bar is OPEN the panel moves BELOW it, so the two floating panels cannot
        overlap on a narrow window.

        v1.4.6: a SAVED position (`ui_minimap_position`, written by the move gesture)
        wins over the corner — and then the search-bar rule no longer applies: the user
        put the panel where they want it, and it is only CLAMPED into the view, so a
        hand-edited config or a shrunken window can never push it off-screen.

        v1.5rc5 (N6): with a saved position the RIGHT edge is preserved across a fold —
        the saved x is shifted by the width delta, so the band stays where the cursor
        clicked. `_minimap_width` is the last placed width and starts at the EXPANDED one
        (that is what a saved position describes, including a start with a folded panel).
        """
        mini = getattr(self, "minimap", None)
        view = getattr(self, "view", None)
        if mini is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            position = getattr(self, "_minimap_pos", None)
            if position is not None:
                width = int(mini.width())
                last_width = int(getattr(self, "_minimap_width", 0) or 0)
                # A saved position is the top-left of the EXPANDED panel; a fold keeps that left corner
                # while the width shrinks by BODY_WIDTH, which would throw the title band — the collapse
                # affordance itself — off the RIGHT edge it hangs from. The right edge is what the panel is
                # anchored to, so it is kept in BOTH states by shifting the remembered x by the width delta
                # (ONE attribute; the saved `{x, y}` keeps its meaning — no config-schema change).
                if last_width > 0 and last_width != width:
                    self._minimap_pos = QPoint(int(position.x()) + (last_width - width),
                                               int(position.y()))
                    position = self._minimap_pos
                self._minimap_width = width
                x = min(max(int(position.x()), 0), max(w - width, 0))
                y = min(max(int(position.y()), 0), max(h - mini.height(), 0))
            else:
                y = 12
                bar = getattr(self, "map_search", None)
                if bar is not None and bar.isVisible():
                    y = max(int(bar.geometry().bottom()) + 8, y)
                x = max(4, w - mini.width() - 12)
                self._minimap_width = int(mini.width())
            mini.move(int(x), int(y))
            if mini.isVisible():
                mini.raise_()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _on_minimap_center(self, point):
        """v1.4.2: the minimap asked for a camera move — clamp to the scene and centerOn.

        The inset margin of the fit can ask for a point outside the content, and a
        centerOn far outside the scene rect would fight the scrollbars: clamping keeps
        the camera inside the map.
        """
        try:
            x = float(point.x())
            y = float(point.y())
        except (TypeError, ValueError, AttributeError):
            return
        try:
            rect = self.scene.sceneRect()
            x = min(max(x, rect.left()), rect.right())
            y = min(max(y, rect.top()), rect.bottom())
            # v1.4.4 (ROADMAP task 1): dragging the minimap is manual control — a running
            # camera flight is cancelled (it would otherwise keep overriding the frame).
            self.view.stop_camera_flight()
            self.view.centerOn(x, y)
        except RuntimeError:
            pass  # Qt teardown — the view is gone
