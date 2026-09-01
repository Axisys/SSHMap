import sys

try:
    from .ui.main_window import MainWindow
except ImportError:
    from ui.main_window import MainWindow


def main():
    # ── Setup logging (before anything else) ──────────────────
    log = None  # чтобы при сбое логгера код ниже не падал с NameError
    try:
        from modules.logger import setup_logging, get_log_file_path
        log = setup_logging()

        log.info("=" * 60)
        # AUDIT v0.8.3 (#1): версия централизована в version.py — лог берёт её
        # оттуда, рассинхронизация с релизом больше невозможна.
        try:
            from version import APP_NAME, APP_VERSION
        except ImportError:
            from .version import APP_NAME, APP_VERSION
        # v1.0-fix (audit #10): фичевая строка релиза больше не хардкодится здесь —
        # она устаревала на каждом следующем релизе; версия берётся из version.py,
        # описание релиза — в CHANGELOG.md/DOCUMENTATION.md.
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

        # Тёмная палитра
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#0f172a"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#e2e8f0"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#1e293b"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#334155"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#e2e8f0"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#334155"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e2e8f0"))
        app.setPalette(pal)

        win = MainWindow()
        win.show()

        # v0.7.1: периодические проверки статусов узлов (online/warn/offline) —
        # запускаем один раз после show(): первый раунд через ~2 c, далее по QTimer.
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
        # v1.0-fix (audit #10): фатальная ошибка после создания QApplication раньше
        # глоталась и процесс завершался с кодом 0 — теперь ненулевой exit code,
        # чтобы лаунчер/CI могли обнаружить сбой запуска.
        sys.exit(1)


if __name__ == "__main__":
    main()
