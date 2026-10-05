"""`BookmarksMixin` — the bookmarks panel: its UI state, its placement and the editor door (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and the shared `_saved_position()` parser stays on
the window.

Owned here: the `ui_bookmarks*` UI state (`_read_bookmarks_settings()` / `_save_bookmarks_config()`), the
top-left default that yields to the filter plaque, the re-anchoring drop, the reload-on-show toggle and the
"Edit bookmarks…" door that hands the store to `BookmarkEditDialog`. Mechanism — `DOCUMENTATION.md` §57."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QDialog


class BookmarksMixin:
    """The bookmarks panel: its UI state, its placement and the editor door."""

    #: The inset of the DEFAULT (top-left) position — the plaque's own margin. The plaque
    #: owns the corner and the panel STEPS BELOW it instead of fighting for the pixels (the
    #: "yield, never cover" rule of the floating-panel family).
    BOOKMARKS_MARGIN = 12

    # ── the bookmarks panel ──

    @staticmethod
    def _read_bookmarks_visible() -> bool:
        """`ui_bookmarks_panel` from config.json → the saved visibility (default OFF).

        OFF by default: the panel is a place a user OPENS to look a link up, not chrome a
        first run must carry (the `ui_activity_panel` rule), and the toolbar button plus the
        View item are its doors. A broken value costs the default — never the panel.
        """
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the default (hidden) stands
            return False
        raw = cfg.get("ui_bookmarks_panel")
        return bool(raw) if isinstance(raw, bool) else False

    def _read_bookmarks_settings(self):
        """`ui_bookmarks*` from config.json → (visible, collapsed, position|None).

        Every broken value falls back to its default (hidden, unfolded, the top-left corner)
        — a hand-edited config must never cost the panel or put it off-screen
        (`_position_bookmarks_panel` clamps a saved position into the view anyway).
        """
        visible, collapsed, position = self._read_bookmarks_visible(), False, None
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the panel is simply off
            return visible, collapsed, position
        if isinstance(cfg.get("ui_bookmarks_collapsed"), bool):
            collapsed = bool(cfg["ui_bookmarks_collapsed"])
        position = self._saved_position(cfg.get("ui_bookmarks_position"))
        return visible, collapsed, position

    def _save_bookmarks_config(self, data: dict) -> None:
        """Merge-write the panel's own UI state (the `ui_legend` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the toggle
            pass

    def _setup_bookmarks_panel(self):
        """Create the panel, apply the saved state and wire its persistence.

        Visibility, the folded state and the position live in `~/.sshmap/config.json`
        (`ui_bookmarks_panel`, `ui_bookmarks_collapsed`, `ui_bookmarks_position`) — UI state
        written by its owner, part of the SAME family as `ui_legend*` / `ui_minimap*`, so
        the settings hub's `collect()` does not move.
        """
        try:
            from ui.bookmark_panel import BookmarkPanel
        except ImportError:  # flat layout: the ui/ directory itself is on sys.path
            try:
                from bookmark_panel import BookmarkPanel
            except ImportError:  # a stripped build — no panel, the map works as before
                return
        try:
            panel = BookmarkPanel(self.view, opener=self._quick_launch_url)
        except Exception as e:  # noqa: BLE001 — a panel must not break the startup
            if self.log:
                self.log.warning(f"Bookmarks panel unavailable: {e}")
            return
        panel.moved.connect(self._on_bookmarks_moved)
        panel.collapsed_changed.connect(self._on_bookmarks_collapsed_changed)
        panel.manage_requested.connect(self._open_bookmarks_dialog)
        self.view.resized.connect(self._position_bookmarks_panel)
        visible, collapsed, position = self._read_bookmarks_settings()
        self._bookmarks_enabled = visible
        self._bookmarks_pos = position
        panel.set_collapsed(collapsed, persist=False)
        panel.setVisible(visible)
        self.bookmark_panel = panel
        self._position_bookmarks_panel()

    def _position_bookmarks_panel(self):
        """Place the panel: the saved position (clamped) or the top-left corner.

        The plaque owns the very corner (LEFT|TOP), so the default STEPS BELOW it while the
        plaque is on screen — the same yield the plaque performs for the search bar.
        """
        panel = getattr(self, "bookmark_panel", None)
        view = getattr(self, "view", None)
        if panel is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            position = getattr(self, "_bookmarks_pos", None)
            if position is None:
                x = self.BOOKMARKS_MARGIN
                y = self.BOOKMARKS_MARGIN
                plaque = getattr(self, "filter_plaque", None)
                if plaque is not None and plaque.isVisible():
                    geometry = plaque.geometry()
                    if geometry.right() >= x:
                        y = geometry.bottom() + self.BOOKMARKS_MARGIN
            else:
                x = min(max(int(position.x()), 0), max(w - panel.width(), 0))
                y = min(max(int(position.y()), 0), max(h - panel.height(), 0))
            panel.move(int(x), int(y))
            if panel.isVisible():
                panel.raise_()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _toggle_bookmarks(self, checked: bool):
        """Show/hide the bookmarks panel + persist `ui_bookmarks_panel` (a merge write)."""
        panel = getattr(self, "bookmark_panel", None)
        if panel is None:
            return
        visible = bool(checked)
        try:
            if visible:
                panel.reload()          # a panel that appears reads the file it shows
            panel.setVisible(visible)
            if visible:
                self._position_bookmarks_panel()
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._bookmarks_enabled = visible
        self._save_bookmarks_config({"ui_bookmarks_panel": visible})

    def _on_bookmarks_moved(self, position):
        """The user dragged the panel: remember where (a merge write of the position).

        A drop within `SNAP_PX` of an anchored edge (LEFT|TOP) instead RE-ANCHORS it — the
        saved position is cleared with the `{"x": null, "y": null}` sentinel and the
        documented corner (plus the plaque yield) comes back by itself.
        """
        try:
            pos = QPoint(int(position.x()), int(position.y()))
        except (TypeError, ValueError, AttributeError):
            return
        if self._snap_panel(getattr(self, "bookmark_panel", None), pos, "lt"):
            self._bookmarks_pos = None
            self._save_bookmarks_config({"ui_bookmarks_position": {"x": None, "y": None}})
            self._position_bookmarks_panel()
            return
        self._bookmarks_pos = pos
        self._save_bookmarks_config({"ui_bookmarks_position": {"x": pos.x(), "y": pos.y()}})

    def _on_bookmarks_collapsed_changed(self, collapsed: bool):
        """The panel was folded/unfolded: persist it and re-place (its height changed)."""
        self._save_bookmarks_config({"ui_bookmarks_collapsed": bool(collapsed)})
        self._position_bookmarks_panel()

    def _open_bookmarks_dialog(self):
        """The panel's "Edit bookmarks…" door — the editor dialog owns add/edit/reorder.

        The dialog WRITES through the same store the panel reads (`accept()` →
        `BookmarkStore.save_urls()`, which keeps every foreign entry of the file), and the
        panel RELOADS afterwards — the panel never edits the file itself. The status line
        reports what really happened, including the failure.
        """
        panel = getattr(self, "bookmark_panel", None)
        try:
            from ..dialogs.bookmark_edit_dialog import BookmarkEditDialog
        except ImportError:
            from dialogs.bookmark_edit_dialog import BookmarkEditDialog
        store = panel.store() if panel is not None else None
        try:
            dlg = BookmarkEditDialog(self, store=store)
        except Exception as e:  # noqa: BLE001 — a dialog failure must not break the panel
            if self.log:
                self.log.exception(f"Bookmarks editor failed: {e}")
            return
        if dlg.exec() != QDialog.Accepted:
            return
        if panel is not None:
            try:
                panel.reload()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        try:
            if dlg.save_failed:
                self.statusBar().showMessage(self.t("status.bookmarks_save_failed"), 6000)
            else:
                self.statusBar().showMessage(
                    self.t("status.bookmarks_saved", count=len(dlg.get_entries())), 4000)
        except Exception:  # noqa: BLE001 — a status line is cosmetic
            pass
        if self.log:
            self.log.info("Bookmarks updated", extra={"bookmarks": len(dlg.get_entries())})
