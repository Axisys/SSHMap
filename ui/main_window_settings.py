"""`SettingsMixin` — the two appliers of the settings hub: at startup and after the dialog's OK (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import
the window module (a cycle) — it duck-types the instance. The hub itself is `ui/settings_dialog.py`
(which knows nothing about the window: the `ui/sidebar.py` pattern), and the dialog OPENER
(`_open_settings_dialog()`, the menu slot) stays on the window with the rest of the menubar cluster.

Owned here: the `ui_*` options applied live without a restart (the UI font through `QApplication.setFont`,
the sidebar buttons, the double-click mode, the collapse state and LIST mode) and the post-dialog pass —
the theme, the autosave timer, the status settings, the hotkeys, and the live terminal settings of the
ALREADY OPEN sessions. Mechanism — `DOCUMENTATION.md` §41."""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


class SettingsMixin:
    """The settings hub applied to a live window: the startup pass and the post-dialog pass."""

    def _apply_ui_options_from_config(self):
        """v1.1.1: apply the ui_* options from config.json (at startup and after the dialog's OK).

        * UI font — QApplication.setFont (family/size; empty/0 = system);
          applied to the widgets without a restart (Qt recomputes fonts not
          set explicitly on each widget).
        * The sidebar button block — SidebarPanel.set_buttons_visible (the layout
          reflows itself); the whole sidebar is hidden separately — the "View" menu item.
        * The node double-click mode — the self._node_double_click_mode cache
          ("properties" the default | "connect" -> _run_ssh_connect).
        """
        try:
            from ui.settings_dialog import load_ui_settings as _load_ui
        except ImportError:  # flat launch from the project root
            from settings_dialog import load_ui_settings as _load_ui
        ui_cfg = _load_ui()

        family = ui_cfg["font_family"]
        size = ui_cfg["font_size"]
        if family or size is not None:
            try:
                app = QApplication.instance()
                if app is not None:
                    f = QFont(app.font())
                    if family:
                        f.setFamily(family)
                    if size is not None:
                        f.setPointSize(int(size))
                    app.setFont(f)
            except Exception as e:  # noqa: BLE001 — the font must not break startup/apply
                if self.log:
                    self.log.warning(f"Apply UI font failed: {e}")

        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.set_buttons_visible(ui_cfg["show_sidebar_buttons"])
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed

        self._node_double_click_mode = ui_cfg["node_double_click"]

        # v1.2.4.1 (task 4): the panel collapse state from config.json —
        # ui_sidebar_collapsed / ui_map_collapsed. Applied at startup AFTER
        # restoreState() (the method is called in __init__ after restore_window_geometry)
        # and after the settings dialog's OK (idempotent: _set_panel_collapsed is a no-op
        # if the state matches). setChecked(False) emits toggled -> the mechanism.
        try:
            from i18n import load_config as _load_cfg
            _cfg = _load_cfg()
            for attr, key in (("act_show_sidebar", "ui_sidebar_collapsed"),
                              ("act_show_map", "ui_map_collapsed")):
                act = getattr(self, attr, None)
                if act is not None and bool(_cfg.get(key, False)):
                    act.setChecked(False)  # checked = expanded -> collapse
        except Exception as e:  # noqa: BLE001 — the state must not break startup/apply
            if self.log:
                self.log.warning(f"Apply panel collapsed states failed: {e}")

        # v1.4.5 (ROADMAP task 5): the divider's affordance follows the state — with
        # no panel collapsed this is the plain "both expanded" sync (the tooltip and
        # the released width caps), with one collapsed the handle is disabled.
        # v1.4.6 (ROADMAP task 2): and the sidebar follows the map — a map collapsed
        # by the saved state (or by the settings dialog) opens in LIST mode.
        self._sync_splitter_handle()
        self._sync_list_mode()

    def _apply_settings_from_dialog(self):
        """v1.1: apply the saved settings live (after the dialog's OK).

        * Autosave — the QTimer right now (interval + start/stop per enabled);
        * Statuses — StatusChecker.set_interval/set_probe_timeout/set_max_parallel
          (the next round; v1.1.2 final: parallel probes, cap 1..64);
        * v1.1.1: the UI font (QApplication.setFont), the open terminal windows' font
          (widget.set_font — without a restart), the sidebar buttons, the double-click
          mode, redrawing the connection plaques (the "type on plaque" option);
        * The terminal (palette/history/close behavior) and the external terminal
          read the config at the next window creation/launch — no action needed;
        * v1.2.2: terminal_mode ("windows"|"tabs") — applied WITHOUT a restart
          "to new sessions": _spawn_terminal_window reads the key on every call;
          open windows/the dock live on as-is until closed (task 4) — no action.
        * v1.3.2: the configurable hotkeys — _apply_hotkeys() reinstalls the sequences
          of the registered QActions/QShortcuts (QAction.setShortcut /
          QShortcut.setKey) from the "hotkeys" key; the F12 multi-input rule is kept.
        * v1.4.3 (ROADMAP task 6): the APPEARANCE — the `theme` key of config.json
          is read back and applied through `apply_theme()` (the mode + the accent
          hue). The "Appearance" tab already applied it live while the dialog was
          open; this is what makes the OK authoritative (and what covers a config
          edited by hand between the two).
        """
        # v1.4.3 (ROADMAP task 6): the theme first — every other option below is
        # applied to widgets whose colours the switch may have just changed.
        # v1.5rc1: the motion flag travels in the SAME nested key, so it is
        # installed here as well (`apply_motion_setting` reads `theme.motion`).
        try:
            from ui.settings_dialog import (load_theme_settings, theme_from_settings,
                                            apply_motion_setting, apply_density_setting)
        except ImportError:  # flat launch from the project root
            try:
                from settings_dialog import (load_theme_settings, theme_from_settings,
                                             apply_motion_setting, apply_density_setting)
            except ImportError:
                load_theme_settings = theme_from_settings = apply_motion_setting = None
                apply_density_setting = None
        if load_theme_settings is not None:
            try:
                _saved_theme = load_theme_settings()
                self.apply_theme(theme_from_settings(_saved_theme))
                apply_motion_setting(_saved_theme)
                # v1.6 (ROADMAP task 2): the card density rides the same nested key —
                # installed before the repaint walk below so the cards follow it there.
                if apply_density_setting is not None:
                    apply_density_setting(_saved_theme)
            except Exception as e:  # noqa: BLE001 — the look must not break applying
                if self.log:
                    self.log.warning(f"Apply theme settings failed: {e}")
        try:
            from storage.autosave import get_autosave_settings as _get_as
            _as_cfg = _get_as()
            self._autosave_enabled = bool(_as_cfg.get("enabled", True))
            self._autosave_timer.setInterval(int(_as_cfg["interval_sec"]) * 1000)
            if self._autosave_enabled:
                self._autosave_timer.start()
            else:
                self._autosave_timer.stop()
        except Exception as e:  # noqa: BLE001 — the timer must not break applying
            if self.log:
                self.log.warning(f"Apply autosave settings failed: {e}")
        checker = getattr(self, "_status_checker", None)
        if checker is not None:
            try:
                from services.status_checker import get_status_settings as _get_st
                _st_cfg = _get_st()
                # v1.6.6 (ROADMAP task 2): the mode is applied LIVE and BEFORE the interval —
                # switching it ON stops a running timer at once, switching it OFF resumes the
                # periodic rounds this window already had enabled (the checker remembers).
                checker.set_manual_only(bool(_st_cfg.get("manual", False)))
                checker.set_interval(int(_st_cfg["interval_sec"]) * 1000)
                checker.set_probe_timeout(float(_st_cfg["probe_timeout_sec"]))
                # v1.1.2 final (task 2): the parallel-probe cap — from the next round
                checker.set_max_parallel(int(_st_cfg["max_parallel"]))
            except Exception as e:  # noqa: BLE001 — the statuses must not break applying
                if self.log:
                    self.log.warning(f"Apply status settings failed: {e}")

        # v1.1.1 (item 1): the UI font + the sidebar buttons + the double-click mode
        try:
            self._apply_ui_options_from_config()
        except Exception as e:  # noqa: BLE001 — the options must not break applying
            if self.log:
                self.log.warning(f"Apply UI options failed: {e}")

        # v1.3.2 (task 3): the configurable hotkeys — QAction.setShortcut / QShortcut.setKey
        # on the already existing objects: the new sequences work without a restart.
        try:
            self._apply_hotkeys()
        except Exception as e:  # noqa: BLE001 — the hotkeys must not break applying
            if self.log:
                self.log.warning(f"Apply hotkeys failed: {e}")

        # v1.1.1 (item 1): the terminal font — into the ALREADY OPEN sessions without a restart
        # (v1.2: the registry stores pages — page.widget)
        try:
            from modules.ssh_terminal import load_terminal_settings as _load_ts
        except ImportError:
            from ..modules.ssh_terminal import load_terminal_settings as _load_ts
        term_cfg = _load_ts()
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            for s in list(getattr(self, "_terminal_windows", [])):
                try:
                    s.widget.set_font(
                        family=term_cfg["font_family"],
                        size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)
                except (RuntimeError, AttributeError):
                    pass  # Qt teardown / a session without a widget — skip it

        # v1.6.2 (ROADMAP task 4): the cursor shape of the ALREADY OPEN sessions — the second
        # live terminal setting (the font loop above is the twin: same walk, same silence on
        # a session that is already gone).
        for s in list(getattr(self, "_terminal_windows", [])):
            try:
                s.widget.set_cursor_style(term_cfg["cursor"])
            except (RuntimeError, AttributeError):
                pass  # Qt teardown / a session without a widget — skip it

        # v1.7.5 (ROADMAP v1.7.5, task 2): the reader's CEILING of the ALREADY OPEN sessions — the
        # third live terminal-side setting (the font and the cursor above are its twins). Every open
        # Files container is told, so its panes read with the new cap at once and the "no preview"
        # facts of the old cap are dropped.
        try:
            try:
                from modules.sftp_tab import resolve_viewer_max_bytes as _resolve_viewer_cap
            except ImportError:
                from ..modules.sftp_tab import resolve_viewer_max_bytes as _resolve_viewer_cap
            _viewer_cap = _resolve_viewer_cap()
            for s in list(getattr(self, "_terminal_windows", [])):
                _apply_cap = getattr(getattr(s, "sftp_tab", None), "apply_viewer_max_bytes", None)
                if callable(_apply_cap):
                    _apply_cap(_viewer_cap)
        except Exception as e:  # noqa: BLE001 — the cap must not break applying
            if self.log:
                self.log.warning(f"Apply viewer max bytes failed: {e}")

        # v1.1.1 (item 6): the "type on plaque" option — redraw the scene's connection labels
        try:
            for arrow in list(getattr(self.scene, "_arrows", [])):
                arrow.refresh_label()
        except Exception:  # noqa: BLE001 — the plaques are cosmetic on teardown
            pass

        try:
            self.statusBar().showMessage(self.t("status.settings_saved"))
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
