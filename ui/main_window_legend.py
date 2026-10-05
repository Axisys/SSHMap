"""`LegendMixin` — the legend panel: its UI state, its placement and its fold (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and the shared `_saved_position()` parser stays on
the window.

Owned here: the `ui_legend*` UI state (`_read_legend_settings()` / `_save_legend_config()`), the
bottom-left default with `LEGEND_MARGIN`, the re-anchoring drop and the toggle the priority rule may
suppress without losing the user's choice. Mechanism — `DOCUMENTATION.md` §36."""
from PySide6.QtCore import QPoint


class LegendMixin:
    """The legend panel: its UI state, its placement and its fold."""

    LEGEND_MARGIN = 12          # the inset of the DEFAULT (bottom-left) position

    # ── the legend panel ──

    def _setup_legend(self):
        """Create the legend panel, apply the saved state and wire its persistence.

        Visibility, the folded state and the position live in `~/.sshmap/config.json`
        (`ui_legend`, `ui_legend_collapsed`, `ui_legend_position`) — UI state written by
        its owner, like `ui_minimap` (a merge write; a broken value falls back to the
        default). The panel is a child of the view: never a scene item, so it stays out
        of the exports and out of "fit to content".
        """
        try:
            from ui.legend import LegendWidget
        except ImportError:  # flat launch from the project root
            from legend import LegendWidget

        self.legend = LegendWidget(self.view)
        self.legend.moved.connect(self._on_legend_moved)
        self.legend.collapsed_changed.connect(self._on_legend_collapsed_changed)
        self.view.resized.connect(self._position_legend)
        visible, collapsed, position = self._read_legend_settings()
        self._legend_enabled = visible
        self._legend_pos = position
        self.legend.set_collapsed(collapsed)
        self.legend.setVisible(visible)
        self._position_legend()

    def _read_legend_settings(self):
        """`ui_legend*` from config.json → (visible, collapsed, position|None).

        Every broken value falls back to its default (visible, unfolded, the
        bottom-left corner) — a hand-edited config must never cost the panel or put it
        off-screen (`_position_legend` clamps a saved position into the view anyway).
        """
        visible, collapsed, position = True, False, None
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the panel is simply on
            return visible, collapsed, position
        if isinstance(cfg.get("ui_legend"), bool):
            visible = bool(cfg["ui_legend"])
        if isinstance(cfg.get("ui_legend_collapsed"), bool):
            collapsed = bool(cfg["ui_legend_collapsed"])
        position = self._saved_position(cfg.get("ui_legend_position"))
        return visible, collapsed, position

    def _position_legend(self):
        """Place the legend: the saved position (clamped into the view) or bottom-left.

        The top-right corner belongs to the minimap, the top-center to the search bar
        and the bottom-right to the map-collapse diamond — the bottom-left is the free
        one, and it is the default until the user drags the panel somewhere else.
        """
        legend = getattr(self, "legend", None)
        view = getattr(self, "view", None)
        if legend is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            position = getattr(self, "_legend_pos", None)
            if position is None:
                x = self.LEGEND_MARGIN
                y = max(self.LEGEND_MARGIN, h - legend.height() - self.LEGEND_MARGIN)
            else:
                x = min(max(int(position.x()), 0), max(w - legend.width(), 0))
                y = min(max(int(position.y()), 0), max(h - legend.height(), 0))
            legend.move(int(x), int(y))
            if legend.isVisible():
                legend.raise_()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _toggle_legend(self, checked: bool):
        """v1.4.5: show/hide the legend + persist `ui_legend` (a merge write).

        v1.5rc4 (ROADMAP task 7): while the first-run hint is on screen the legend yields
        to it — the user's choice is REMEMBERED (`_legend_enabled` + `ui_legend`) but the
        panel stays hidden until the hint goes away. A temporary suppression never
        overwrites a saved visibility.
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return
        visible = bool(checked)
        try:
            legend.setVisible(visible)
            if visible:
                self._position_legend()
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._legend_enabled = visible
        self._save_legend_config({"ui_legend": visible})
        self._sync_legend_suppression()

    def _on_legend_moved(self, position):
        """The user dragged the panel: remember where (a merge write of the position).

        v1.5 (ROADMAP): a drop within `SNAP_PX` of an anchored edge (LEFT|BOTTOM) instead
        RE-ANCHORS the panel — the saved position is cleared and the documented
        bottom-left corner (plus every rule that hangs off it) comes back by itself.
        """
        try:
            pos = QPoint(int(position.x()), int(position.y()))
        except (TypeError, ValueError, AttributeError):
            return
        if self._snap_panel(getattr(self, "legend", None), pos, "lb"):
            self._legend_pos = None
            self._save_legend_config({"ui_legend_position": {"x": None, "y": None}})
            self._position_legend()
            return
        self._legend_pos = pos
        self._save_legend_config({"ui_legend_position": {"x": self._legend_pos.x(),
                                                         "y": self._legend_pos.y()}})

    def _on_legend_collapsed_changed(self, collapsed: bool):
        """The panel was folded/unfolded: persist it and re-place (its height changed)."""
        self._save_legend_config({"ui_legend_collapsed": bool(collapsed)})
        self._position_legend()

    def _save_legend_config(self, data: dict) -> None:
        """Merge-write the legend's own UI state (the `ui_minimap` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the toggle
            pass
