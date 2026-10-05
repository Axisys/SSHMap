"""`ThemeMixin` — the live theme switch: the repaint walk, the icon ink and the "Auto" follow (AGENTS.md §4.6).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and `theme_qss` / the icon facades / `_diamond_icon` are
resolved on the facade at call time (`host_attr`), so a stripped build keeps the None semantics.

Owned here: `refresh_theme()` (the ONE walk over everything the window owns — the status bar, the counters,
the map, the minimap and the terminal containers), `apply_theme()` (the entry point every switch uses), the
vector-icon repaint (`_refresh_icons()`), and the platform colour-scheme watch of the `auto` mode. The
translator cache is NEVER invalidated here. Mechanism — `DOCUMENTATION.md` §15, §31."""

from PySide6.QtGui import QAction

try:  # v1.2.5: the central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.8rc3: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


class ThemeMixin:
    """The live theme switch: the repaint walk, the icon ink and the "Auto" follow (AGENTS.md §4.6)."""

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4/5): re-apply the theme to everything this window owns.

        Called by `ui/theme_qss.apply_theme()` (and safe to call directly). The
        window is the only object that can reach all the pieces, so it walks what
        it owns and nothing else:

          * the status-bar styles from the registry (they are QSS strings, and a
            QSS string is a value);
          * the MAP — `MapScene.refresh_theme()` repaints the grid/background and
            asks every item that defines the hook (nodes, arrows, notes, groups);
          * the minimap (a child of the view, but owned by the window) — its
            cached colour layer has to be rebuilt;
          * the terminal CONTAINERS and their sessions (status labels, the SFTP
            tabs, the find bars) through the same registry walk the language
            switch uses.

        The QPalette and the application-wide QSS are applied by `apply_theme()`
        BEFORE this method is called, so the standard controls already follow.
        Every stage is fault-isolated: a theme switch is cosmetic and must never
        raise out of a half-closed session.
        """
        theme_qss = host_attr(self, "theme_qss")
        if theme_qss is not None:
            for widget, key in ((getattr(self, "counts_label", None), "status.bar_counts"),
                                (getattr(self, "zoom_label", None), "status.bar_zoom")):
                if widget is not None:
                    theme_qss.refresh(widget, key)
        # v1.5rc3 (ROADMAP task 2): the status bar owns the Undo affordance — a QSS
        # string and a text are VALUES, so its own refresh re-applies both.
        try:
            _bar = self.statusBar()
            hook = getattr(_bar, "refresh_theme", None)
            if callable(hook):
                hook()
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed
        # v1.4.5 (ROADMAP task 3): the clickable status counters (their ACTIVE styling
        # is the widget's own state — `refresh_theme()` picks the right registry entry).
        # v1.5.4 (ROADMAP task 2): the "problems only" chip belongs to the same family
        # (its QSS is a VALUE too, and `set_active` only re-applies it on a real change).
        for counter in list((getattr(self, "status_filter_labels", {}) or {}).values()) \
                + [getattr(self, "problems_chip", None)]:
            if counter is None:
                continue
            try:
                counter.refresh_theme()
            except RuntimeError:
                continue  # Qt teardown — this counter is already destroyed
        self._refresh_icons()
        try:
            self._multi_label.setStyleSheet(
                f"color: {theme.SELECTION_AMBER}; font-weight: bold;")
        except (AttributeError, RuntimeError):
            pass
        scene = getattr(self, "scene", None)
        if scene is not None:
            try:
                scene.refresh_theme()
            except Exception as e:  # noqa: BLE001 — the map must not break the switch
                if self.log:
                    self.log.warning(f"Theme: the scene refresh failed: {e}")
        view = getattr(self, "view", None)
        if view is not None:
            try:
                view.refresh_theme()
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log.warning(f"Theme: the view refresh failed: {e}")
        mini = getattr(self, "minimap", None)
        if mini is not None:
            try:
                mini.refresh_theme()
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log.warning(f"Theme: the minimap refresh failed: {e}")
        # The terminal containers (windows mode: the sessions; tabs mode: the dock) —
        # the SAME walk as _apply_ui_translations, for the same reason (a session may
        # be torn down under the switch).
        for session in list(getattr(self, "_terminal_windows", None) or ()):
            try:
                host = getattr(session, "_host_window", None) or session
                hook = getattr(host, "refresh_theme", None)
                if callable(hook):
                    hook()
            except RuntimeError:
                continue  # Qt teardown — this session is gone
            except Exception:  # noqa: BLE001 — one container must not stop the rest
                continue
        dock = getattr(self, "_terminals_dock", None)
        if dock is not None:
            try:
                hook = getattr(dock, "refresh_theme", None)
                if callable(hook):
                    hook()
            except RuntimeError:
                pass
            except Exception:  # noqa: BLE001
                pass
        # The floating panels are children of the view but owned here: the map search
        # bar (v0.9.8), the minimap (v1.4.2), the legend (v1.4.5), the first-run
        # empty state (v1.4.5) and the bookmarks panel (v1.6.7) — all repaint from the
        # live theme.
        for widget in (getattr(self, "map_search", None), getattr(self, "legend", None),
                       getattr(self, "empty_state", None),
                       getattr(self, "filter_plaque", None),
                       getattr(self, "bookmark_panel", None)):
            hook = getattr(widget, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass  # Qt teardown — the panel is already destroyed
                except Exception:  # noqa: BLE001
                    pass

    # ── v1.4.3 (ROADMAP task 6): the theme of the settings hub ────────────────────

    def apply_theme(self, instance=None):
        """Make `instance` (or the saved theme) ACTIVE and repaint the application.

        The one entry point of a theme switch: the settings dialog calls it after
        its OK (through `_apply_settings_from_dialog`) and `main.py` calls it with
        the theme the config holds, BEFORE the window is built, so nothing is ever
        constructed with the wrong palette.
        """
        theme_qss = host_attr(self, "theme_qss")
        if theme_qss is not None:
            theme_qss.apply_theme(instance if instance is not None else theme.THEME)
        elif instance is not None:
            theme.set_theme(instance)
        return theme.THEME

    # ── v1.5rc1 (ROADMAP task 6): "Auto (system)" follows the platform live ──────

    def _install_color_scheme_watch(self) -> bool:
        """Listen to the platform's colour scheme (v1.5rc1) — True when installed.

        The "Auto" mode is not a snapshot: Qt reports a change of the OS theme
        through `QStyleHints.colorSchemeChanged`, and a window in `auto` must
        follow it without a restart. Installed once per window (the flag makes it
        idempotent) and never fatal — a platform without the hint keeps the mode
        the config resolved at startup, which is the pre-v1.5rc1 behaviour.
        """
        if getattr(self, "_color_scheme_hints", None) is not None:
            return False
        try:
            from PySide6.QtGui import QGuiApplication
            hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
            if hints is None:
                return False
            hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
            self._color_scheme_hints = hints
            return True
        except Exception as e:  # noqa: BLE001 — the hint is optional
            if getattr(self, "log", None):
                self.log.debug(f"Auto theme: no colorScheme hint ({e})")
            return False

    def _theme_mode_from_config(self) -> str:
        """The stored `theme.mode` (v1.5rc1) — DARK when the config cannot be read."""
        try:
            from ui.settings_dialog import load_theme_settings
        except ImportError:  # flat launch from the project root
            try:
                from settings_dialog import load_theme_settings
            except ImportError:
                return theme.MODE_DARK
        try:
            return load_theme_settings().get("mode") or theme.MODE_DARK
        except Exception:  # noqa: BLE001 — a broken config must not break the window
            return theme.MODE_DARK

    def _on_system_color_scheme_changed(self, *_args):
        """The OS flipped dark↔light: only an `auto` window follows it (v1.5rc1).

        Deliberately narrow: it re-reads the theme key and re-applies the THEME
        (not `_apply_settings_from_dialog`, which would re-apply every setting for
        a change that is about one colour).
        """
        if self._theme_mode_from_config() != theme.MODE_AUTO:
            return  # an explicit dark/light choice is the user's, not the platform's
        try:
            from ui.settings_dialog import load_theme_settings, theme_from_settings
        except ImportError:  # flat launch from the project root
            try:
                from settings_dialog import load_theme_settings, theme_from_settings
            except ImportError:
                return
        try:
            self.apply_theme(theme_from_settings(load_theme_settings()))
        except Exception as e:  # noqa: BLE001 — a cosmetic follow must never break
            if getattr(self, "log", None):
                self.log.warning(f"Auto theme: the follow-up apply failed: {e}")

    def _refresh_icons(self):
        """re-paint the vector icons in the ACTIVE theme's colour.

        A QIcon handed to a QAction/QPushButton keeps the pixels it was painted
        with, and nothing repaints it when the theme changes — the toolbar, the
        menus, the sidebar buttons and the palette showed dark-theme pale glyphs
        on LIGHT (reported after v1.4.3 shipped).

        `ui/icons.py` keeps ONE QIcon object per name (implicitly shared), so
        `refresh_all()` re-paints them IN PLACE and every widget already holding
        one shows the new pixmap; the QActions are then re-set for the widgets
        that cache a QIcon per action. The two "◇" diamonds draw a fresh pixmap
        (they are window-internal, not in the registry) and are re-applied here.
        Never raises: a broken icon must not break a theme switch.
        """
        icons_mod = host_attr(self, "_icons_mod")
        count = 0
        try:
            if icons_mod is not None:
                count = icons_mod.refresh_all()
            for action in self.findChildren(QAction):
                if host_attr(self, "refresh_action_icon")(action):
                    count += 1
        except RuntimeError:
            pass  # Qt teardown — an action of a closing window is already destroyed
        except Exception as e:  # noqa: BLE001 — cosmetic
            if self.log:
                self.log.warning(f"Theme: the icon refresh failed: {e}")
        # The sidebar's six action buttons hold their own copy of the pixmap.
        sidebar = getattr(self, "sidebar", None)
        hook = getattr(sidebar, "refresh_theme", None)
        if callable(hook):
            try:
                hook()
            except RuntimeError:
                pass  # Qt teardown
            except Exception as e:  # noqa: BLE001 — cosmetic
                if self.log:
                    self.log.warning(f"Theme: the sidebar icon refresh failed: {e}")
        # The two hand-drawn diamonds (the collapse buttons of both panels).
        for btn in (getattr(getattr(self, "sidebar", None), "collapse_btn", None),
                    getattr(self, "_map_collapse_btn", None)):
            if btn is None:
                continue
            try:
                btn.setIcon(host_attr(self, "_diamond_icon")())
                # v1.5.6 (ROADMAP task 4): the FRAME is a QSS VALUE of the same kind —
                # the `collapse.button` entry is re-applied with the icon ink.
                self._style_collapse_btn(btn)
            except RuntimeError:
                continue  # Qt teardown
        # The command palette builds its rows on open — re-theme the OPEN one.
        palette = getattr(self, "_command_palette", None)
        if palette is not None:
            hook = getattr(palette, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass
        return count
