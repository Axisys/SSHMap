import sys

try:
    from .ui.main_window import MainWindow
except ImportError:
    from ui.main_window import MainWindow

# v1.4.3 (ROADMAP task 4): the saved theme is applied through the ONE builder
# (ui/theme_qss.py) before the window is built — the `theme` module itself is no
# longer read here, because the palette and the QSS are both the builder's job.
try:
    from .ui import theme_qss
    from .ui.settings_dialog import (load_theme_settings, theme_from_settings,
                                     apply_motion_setting, apply_density_setting)
except ImportError:
    from ui import theme_qss
    from ui.settings_dialog import (load_theme_settings, theme_from_settings,
                                    apply_motion_setting, apply_density_setting)


def main():
    # ── Setup logging (before anything else) ──────────────────
    log = None  # so that if logging fails, the code below does not crash with a NameError
    try:
        from modules.logger import setup_logging, get_log_file_path
        log = setup_logging()

        log.info("=" * 60)
        # AUDIT v0.8.3 (#1): the version is centralized in version.py — the log
        # reads it from there, so drift from the release is no longer possible.
        try:
            from version import APP_NAME, APP_VERSION
        except ImportError:
            from .version import APP_NAME, APP_VERSION
        # v1.0-fix (audit #10): the release feature line is no longer hardcoded here —
        # it went stale with every next release; the version comes from version.py,
        # the release description lives in CHANGELOG.md/DOCUMENTATION.md.
        log.info(f"{APP_NAME} v{APP_VERSION} starting up")
        log.info(f"Log file: {get_log_file_path()}")
    except Exception as e:
        print(f"[FATAL] Failed to setup logging: {e}", flush=True)

    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication(sys.argv)
        app.setStyle('Fusion')

        # v1.4.3 (ROADMAP task 4/6): the base palette AND the application QSS are
        # built from the ACTIVE theme — and the ACTIVE theme is the SAVED one,
        # applied BEFORE the window exists, so nothing is ever constructed with the
        # wrong palette. `ui/theme_qss.apply_theme()` is the ONE place that turns a
        # Theme into the application's look; every later switch is
        # `MainWindow.apply_theme()`.
        # v1.5rc1: an `auto` mode is resolved here too — the platform's colour
        # scheme decides, and `MainWindow` keeps following it live.
        _saved_theme = load_theme_settings()
        theme_qss.apply_theme(theme_from_settings(_saved_theme), app=app,
                              refresh_windows=False)
        # v1.5rc1 (ROADMAP task 6): the "Reduce motion" flag of the same key,
        # installed BEFORE the window exists so no gesture can start un-flagged.
        apply_motion_setting(_saved_theme)
        # v1.6 (ROADMAP task 2): the card density of the same nested key — installed
        # before the first card is built, so no card is ever born in the other mode.
        apply_density_setting(_saved_theme)

        win = MainWindow()
        win.show()

        # v1.4rc1 (plugin foundation, rc series): the plugin discovery — after the
        # window exists and BEFORE the event loop (ROADMAP rc1: "after MainWindow
        # creation, before app.exec()"). A broken plugin is reported in the status bar
        # and in the log; it can never stop the application (the call itself is
        # defensive as well — a plugin must not be able to break the startup).
        try:
            win.start_plugin_discovery()
        except Exception as e:
            if log is not None:
                log.warning(f"Plugin discovery did not run: {e}")

        # v0.7.1: periodic node status checks (online/warn/offline) —
        # started once after show(): the first round in ~2 s, then driven by QTimer.
        try:
            win.start_status_checks()
        except Exception as e:
            if log is not None:
                log.warning(f"Status checks did not start: {e}")

        if log is not None:
            log.info("MainWindow shown")
        sys.exit(app.exec())
    except Exception as e:
        if log is not None:
            log.exception("Fatal error during startup")
        else:
            import traceback
            traceback.print_exc()
        # v1.0-fix (audit #10): a fatal error after QApplication creation used to be
        # swallowed and the process exited with code 0 — now a non-zero exit code,
        # so a launcher/CI can detect a failed startup.
        sys.exit(1)


if __name__ == "__main__":
    main()
