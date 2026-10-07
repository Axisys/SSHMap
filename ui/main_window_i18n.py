"""`I18nMixin` — the re-text walk the window owns: the widget registry and the language switch (AGENTS.md §4.5).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: `_register_i18n()` (the ONE registry a widget joins to be re-texted) and the two walks that
consume it — `_apply_ui_translations()`, whose every stage is fault-isolated (a container dying mid-switch
must not abort the rest), and `_switch_language()`, the language-menu path with its checkmark. The hotkey
registry, the window title and the command palette stay with the facade. Mechanism —
`DOCUMENTATION.md` §15, §17."""

from PySide6.QtWidgets import QMenu, QMessageBox


class I18nMixin:
    """The re-text walk the window owns: the widget registry and the language switch (AGENTS.md §4.5)."""

    def _register_i18n(self, widget, key: str):
        """Remember a widget (QMenu/QAction) and its translation key for re-application."""
        self._menu_i18n.append((widget, key))

    def _apply_ui_translations(self):
        """Translate the menus, toolbar, and service labels to the current language.

        v1.3.3.1 (ROADMAP task 1): every stage is individually fault-isolated. The
        re-text is a CROSS-CUTTING walk over widgets that may die at any moment (a
        terminal window closing mid-switch, a torn-down container) — before, one
        broken widget aborted the whole method, so the terminal containers stayed in
        the previous language. A re-text is cosmetic: it must never break the switch.
        """
        for widget, key in self._menu_i18n:
            if widget is None:
                continue
            try:
                if isinstance(widget, QMenu):
                    widget.setTitle(self.t(key))
                else:
                    widget.setText(self.t(key))
            except RuntimeError:
                pass  # Qt teardown — one menu/action is already destroyed
        # v1.5rc4 (ROADMAP task 2): the toolbar's "»" overflow button keeps its glyph and
        # only its TOOLTIP is translated (it is not in `_menu_i18n`, which re-texts).
        if self._i18n_available:
            for _widget in (getattr(self, "_toolbar_overflow_action", None),
                            getattr(self, "_toolbar_overflow_btn", None)):
                if _widget is None:
                    continue
                try:
                    _widget.setToolTip(self.t("toolbar.more"))
                except RuntimeError:
                    pass  # Qt teardown — the action/button is already destroyed
        # v0.9.9.4: sidebar strings (buttons, title, placeholder, "All tags") —
        # the panel registry; retranslate via the i18n callback (regression on the v0.9.2 bug:
        # these strings were not updated on language switch before).
        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.2.2: the "Terminals" dock may have been created before the language switch — translate its title
        dock = getattr(self, "_terminals_dock", None)
        if dock is not None:
            try:
                dock.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the dock is already destroyed
            except AttributeError:
                try:
                    dock.setWindowTitle(self.t("terminal.dock_title"))
                except RuntimeError:
                    pass  # Qt teardown — the dock is already destroyed
        # The terminal CONTAINERS follow the language too — the twin of the terminal-font loop in
        # `_apply_settings_from_dialog`: same registry, same dead-C++-object discipline (a session
        # being torn down must not break the switch). The registry stores SESSIONS in windows mode
        # and the DOCK in tabs mode; both own `retranslate()`, and the page's HOST re-texts what the
        # page cannot reach (the window title, the tabs' close tooltips). Both calls are idempotent.
        for _session in list(getattr(self, "_terminal_windows", [])):
            try:
                _session.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the session/dock content is already destroyed
            except AttributeError:
                pass  # a session object without retranslate() (a test double) — skip it
            except Exception:  # noqa: BLE001 — one container must not abort the re-text
                if self.log:
                    self.log.warning("retranslate failed for a terminal session", exc_info=True)
            _host = getattr(_session, "_host_window", None)
            if _host is None or _host is dock:
                continue  # no host / the dock was already re-texted above
            try:
                _host.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the host window is already destroyed
            except AttributeError:
                pass  # a host without retranslate() (a test double) — skip it
            except Exception:  # noqa: BLE001 — one window must not abort the re-text
                if self.log:
                    self.log.warning("retranslate failed for a terminal window", exc_info=True)
        # v1.2.3: multi-input plaque — the exit button tooltip in the new language
        _multi_btn = getattr(self, "_multi_exit_btn", None)
        if _multi_btn is not None:
            try:
                _multi_btn.setToolTip(self.t("terminal.multi_exit_button"))
            except RuntimeError:
                pass  # Qt teardown — the plaque is already destroyed
        # v1.2.4.1: tooltips of the corner collapse buttons and the collapsed-panel strips
        _sb_panel = getattr(self, "sidebar", None)
        if _sb_panel is not None:
            try:
                _sb_panel.collapse_btn.setToolTip(self.t("view.toggle_sidebar"))
            except (RuntimeError, AttributeError):
                pass  # Qt teardown / a panel without the button — the tooltip is not critical
        for _widget, _key in ((getattr(self, "_map_collapse_btn", None), "view.toggle_map"),
                              (getattr(self, "_sidebar_strip", None), "view.strip_sidebar_tooltip"),
                              (getattr(self, "_map_strip", None), "view.strip_map_tooltip"),
                              (getattr(self, "legend", None), "legend.tooltip")):
            if _widget is not None:
                try:
                    _widget.setToolTip(self.t(_key))
                except RuntimeError:
                    pass  # Qt teardown — the widget is already destroyed
        # v1.5rc3 (ROADMAP task 2): the Undo button of the status bar is re-texted by its
        # own refresh (it also re-applies the registry QSS — the v1.4.3 rule).
        try:
            _bar = self.statusBar()
            _hook = getattr(_bar, "refresh_theme", None)
            if callable(_hook):
                _hook()
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed
        # v1.4.5 (ROADMAP task 4): the legend paints its rows from a label cache.
        _legend = getattr(self, "legend", None)
        if _legend is not None:
            try:
                _legend.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.6.7 (ROADMAP task 4): the bookmarks panel (its title band, the filter's
        # placeholder, the button and the two sentences of an empty / filtered list).
        _bookmarks = getattr(self, "bookmark_panel", None)
        if _bookmarks is not None:
            try:
                _bookmarks.retranslate()
                self._position_bookmarks_panel()   # the captions changed width — re-place it
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.5.4 (ROADMAP task 3): the active-filter plaque — it BUILDS its captions from
        # the live filter state, so a re-text is one call (the values never move).
        _plaque = getattr(self, "filter_plaque", None)
        if _plaque is not None:
            try:
                _plaque.retranslate()
                self._position_filter_plaque()  # the captions changed width — re-place it
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.5.2 (ROADMAP task 3): the activity panel — the CHROME only (its title, the
        # level captions, the column headers, Clear). The event LINES are logging lines
        # and stay English: one key per event kind would be an i18n cost with no reader.
        _activity = getattr(self, "activity_panel", None)
        if _activity is not None:
            try:
                _activity.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.8.3 (ROADMAP task 1): the Plugins window — the CHROME only (its title, the column
        # captions, the three buttons and the headers). The event LINES are logging lines and stay
        # English: one key per event kind would be an i18n cost with no reader (§4.10).
        _plugins_window = getattr(self, "plugins_panel", None)
        if _plugins_window is not None:
            try:
                _plugins_window.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the window is already destroyed
        # v1.4.5 (ROADMAP task 2): the first-run hint (its button text + the paint).
        _empty = getattr(self, "empty_state", None)
        if _empty is not None:
            try:
                _empty.retranslate()
                self._position_empty_state()   # the sentence changed width — re-place it
            except RuntimeError:
                pass  # Qt teardown — the hint is already destroyed
        # v1.4.5 (ROADMAP task 3): the counters (their labels + tooltips) and, with them,
        # the empty state / the status markers of the composition.
        try:
            self._update_counts_label()
        except RuntimeError:
            pass  # Qt teardown — the status bar is already gone
        # v1.4.5 (ROADMAP task 5): the divider's tooltip.
        try:
            _handle = self._splitter.handle(0)
            if _handle is not None:
                _handle.setToolTip(self.t("view.splitter_handle_tooltip"))
        except (AttributeError, RuntimeError):
            pass  # Qt teardown / a splitter without handles
        try:
            self.statusBar().showMessage(self.t("status.ready"))
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed

    def _switch_language(self, language_code: str):
        """Switch application language and re-apply to all UI elements."""
        try:
            from i18n import set_language as _set_lang

            # Set the new language
            success = _set_lang(language_code)

            if success:
                self.current_language = language_code

                # Translate the menus/toolbar/labels by the registered keys
                self._apply_ui_translations()

                # v0.9.8: the map search panel — the placeholder and counter in the new language
                _map_bar = getattr(self, "map_search", None)
                if _map_bar is not None:
                    try:
                        _map_bar.retranslate()
                    except Exception:  # noqa: BLE001 — the panel is cosmetic on teardown
                        pass

                # v1.4.2: the minimap panel — its tooltip is its only text
                _mini = getattr(self, "minimap", None)
                if _mini is not None:
                    try:
                        _mini.retranslate()
                    except Exception:  # noqa: BLE001 — the panel is cosmetic on teardown
                        pass

                # The window title (accounting for the project file and the [*] marker)
                self._update_window_title()

                # Mark the active language in the Language submenu.
                # v0.9.8 bugfix: do NOT walk via action.menu() — see _qaction_guard above:
                # temporary Python wrappers of QActions with an attached QMenu dropped the C++ menu
                # (PySide6 6.11). The submenu is taken straight from the i18n registry — safe.
                lang_menu = None
                for w, k in self._menu_i18n:
                    if k == "lang.menu":
                        lang_menu = w
                        break
                if lang_menu is not None:
                    try:
                        for sub in list(lang_menu.actions()):
                            if sub.data() is not None:
                                sub.setChecked(sub.data() == language_code)
                    except RuntimeError:
                        pass  # Qt teardown — the submenu is already destroyed; nothing to mark

                if self.log:
                    self.log.info(f"Language switched to {language_code}")
            else:
                QMessageBox.warning(self, self.t("msg.error_title"), 
                                   f"{self.t('lang.switch_failed')}: {language_code}")
        except Exception:
            if self.log:
                self.log.exception(f"Error switching language to {language_code}")
