import sys

try:
    from .ui.main_window import MainWindow
except ImportError:
    from ui.main_window import MainWindow

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from .ui import theme
except ImportError:
    from ui import theme


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
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPalette, QColor

        app = QApplication(sys.argv)
        app.setStyle('Fusion')

        # Dark palette (v1.2.5: values come from the central theme ui/theme.py;
        # light theme/accent color in the future — reassigning the theme constants)
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(theme.WINDOW_BG))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(theme.TEXT_PRIMARY))
        pal.setColor(QPalette.ColorRole.Base, QColor(theme.BASE_BG))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.SURFACE_ALT))
        pal.setColor(QPalette.ColorRole.Text, QColor(theme.TEXT_PRIMARY))
        pal.setColor(QPalette.ColorRole.Button, QColor(theme.SURFACE_ALT))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(theme.TEXT_PRIMARY))
        app.setPalette(pal)

        win = MainWindow()
        win.show()

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
