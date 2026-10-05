"""`ActivityMixin` — the activity panel: its window, its two taps and its visibility key (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: the `ui_activity_panel` visibility (default OFF), the panel's construction, the TWO taps of the
history ring of `modules/activity_log.py` (the status-bar messages and the Undo offer), the toggle and the
close that mirrors itself back into the View item. Mechanism — `DOCUMENTATION.md` §45."""
try:  # v1.5.2 (ROADMAP task 1): the in-memory activity ring the panel renders
    from ..modules import activity_log as _activity_mod
except ImportError:
    try:
        from modules import activity_log as _activity_mod
    except ImportError:  # flat layout: the modules/ directory itself is on sys.path
        try:
            import activity_log as _activity_mod
        except ImportError:  # a stripped build — the panel is simply unavailable
            _activity_mod = None


class ActivityMixin:
    """The activity panel: its window, its taps and its visibility key."""

    # ── the activity panel ──

    @staticmethod
    def _read_activity_visible() -> bool:
        """`ui_activity_panel` from config.json → the saved visibility (default OFF).

        Off by default: the panel is a diagnostic surface, and a first run must not open
        a second window. A broken value costs the default — never the panel.
        """
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the default (hidden) stands
            return False
        raw = cfg.get("ui_activity_panel")
        return bool(raw) if isinstance(raw, bool) else False

    def _save_activity_config(self, data: dict) -> None:
        """Merge-write the panel's own UI state (the `ui_legend` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the toggle
            pass

    def _setup_activity_panel(self):
        """Create the panel and install the TWO taps of the history (v1.5.2, task 1).

        (a) the logging tap is installed by `modules/logger.py` (beside the file
        handler) and needs nothing here; (b) the status-bar tap is this connection:
        `statusBar().messageChanged` for the ordinary transient messages and the
        `UndoStatusBar.offer_shown` signal for the destructive actions' sentences — the
        Undo offer never travels through `messageChanged` (it replaces the temporary
        message), and losing exactly those lines would empty the history of the events a
        user is most likely to look for. Nothing else is rewired.
        """
        try:
            from ui.activity_panel import ActivityPanel
        except ImportError:  # flat layout: the ui/ directory itself is on sys.path
            try:
                from activity_panel import ActivityPanel
            except ImportError:  # a stripped build — no panel, the app works as before
                return
        try:
            panel = ActivityPanel(parent=self)
            panel.on_hidden = self._on_activity_hidden
            self.activity_panel = panel
        except Exception as e:  # noqa: BLE001 — a history surface must not break startup
            if self.log:
                self.log.warning(f"Activity panel unavailable: {e}")
            return
        if bool(getattr(self, "_activity_enabled", False)):
            try:
                panel.set_visible(True)
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        try:
            bar = self.statusBar()
            bar.messageChanged.connect(self._record_activity_message)
            offer = getattr(bar, "offer_shown", None)
            if offer is not None:
                offer.connect(self._record_activity_message)
        except (RuntimeError, AttributeError, TypeError):
            pass  # a status bar without the signal is still a working status bar

    def _record_activity_message(self, text):
        """The status-bar tap: one transient UI message → the history (v1.5.2).

        Called on EVERY `messageChanged`, an empty text included (Qt emits
        `messageChanged("")` on every clear) — `record_status_message()` drops it. A
        failure here must never reach the status bar: the history is cosmetic.
        """
        if _activity_mod is None:
            return
        try:
            _activity_mod.record_status_message(text)
        except Exception:  # noqa: BLE001 — the history must not break a status message
            pass

    def _toggle_activity(self, checked: bool):
        """v1.5.2: show/hide the activity panel + persist `ui_activity_panel`.

        The panel instance lives for the whole session (the history survives closing
        it), so the toggle only shows/hides — `ui/activity_panel.py` explains why.
        """
        panel = getattr(self, "activity_panel", None)
        if panel is None:
            return
        visible = bool(checked)
        try:
            panel.set_visible(visible)
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._activity_enabled = visible
        self._save_activity_config({"ui_activity_panel": visible})

    def _on_activity_hidden(self):
        """The panel was closed by the user (its X): make the View item and its button tell the truth.

        The item OWNS the state, so the close is mirrored into it with BLOCKED signals
        (no `toggled` loop back into `set_visible`) and persisted — the next start
        opens the window only if it was left open. Because the signals are BLOCKED, the
        toolbar MIRROR never hears about the new state and has to be resynced EXPLICITLY
        (`_sync_view_toolbar()`), or it keeps showing "open" while the window is gone and a
        click on it flips the wrong way — the same resync `_reject_collapse_both()` needs.
        """
        self._activity_enabled = False
        self._save_activity_config({"ui_activity_panel": False})
        action = getattr(self, "act_show_activity", None)
        if action is None:
            return
        try:
            if action.isChecked():
                action.blockSignals(True)
                try:
                    action.setChecked(False)
                finally:
                    action.blockSignals(False)
        except RuntimeError:
            return  # Qt teardown — the action is already destroyed
        self._sync_view_toolbar("view.toggle_activity", False)
