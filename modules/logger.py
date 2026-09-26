"""Centralized logging for SSH Map.

Usage in any module:
    from modules.logger import get_logger
    log = get_logger(__name__)
    log.info("Server added", extra={"server": "web-1"})
    log.error("Connection failed", exc_info=True)

All logs go to: ~/.sshmap/logs/ (created automatically)

v1.5.2 (ROADMAP task 1): a THIRD handler is installed beside the file and console
ones — `activity_log.ActivityLogHandler`, the thin tap that pushes every record into
the in-memory ring the activity panel renders (`modules/activity_log.py`). It is
installed HERE, in the ONE place that already owns the logger tree, so no module has to
know that a panel exists; the ring itself is memory-only, so `setup_logging()` stays the
only durable destination (~/.sshmap/logs/sshmap.log).
"""

import logging
import os
import sys


LOG_DIR = os.path.join(os.path.expanduser("~"), ".sshmap", "logs")
LOG_FILE = os.path.join(LOG_DIR, "sshmap.log")
MAX_LOG_SIZE_MB = 5  # Rotate after this size


def _console_stream():
    """The first stream a console handler can really use, or None.

    `sys.stdout` and `sys.stderr` are BOTH `None` under `pythonw.exe` (and under a
    detached GUI launch on any platform) — a `StreamHandler` built on either one
    swallows every record it is handed. A stream without a usable `write` is treated
    as absent for the same reason.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "write"):
            return stream
    return None


def setup_logging(level: int = logging.DEBUG) -> logging.Logger:
    """Configure root logger for SSH Map. Call once from main.py."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root_logger = logging.getLogger("sshmap")
    root_logger.setLevel(level)

    # Prevent duplicate handlers on re-init
    if root_logger.handlers:
        return root_logger

    # ── File handler (rotating) ───────────────────────────────
    try:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except ImportError:
        # Fallback if RotatingFileHandler unavailable (rare)
        file_handler = logging.FileHandler(
            LOG_FILE, encoding="utf-8"
        )

    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # ── Console handler (WARNING+: only warnings and errors) ──
    # v1.6.1 (ROADMAP task 5): a GUI started by pythonw.exe has NO console — `sys.stdout`
    # AND `sys.stderr` are None, and `StreamHandler(None)` then writes into a None stream,
    # so every WARNING+ died inside `emit()` → `handleError()`. Take the first stream that
    # really EXISTS and install no console handler when neither does: the rotating FILE
    # handler is the durable record either way, and setup_logging() never raises.
    console_stream = _console_stream()
    if console_stream is not None:
        console_handler = logging.StreamHandler(console_stream)
        console_handler.setLevel(logging.WARNING)  # Only warnings+errors on console
        console_formatter = logging.Formatter(
            "[%(levelname)-7s] %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # ── v1.5.2 (ROADMAP task 1): the activity tap ─────────────
    # The panel's history is fed from the SAME records the file gets — no emitter is
    # rewired, and the ring is bounded/memory-only (`modules/activity_log.py`). A
    # failure here costs the panel, never the logging: setup_logging() still returns.
    try:
        from modules.activity_log import install_activity_handler
    except ImportError:  # flat layout: the modules/ directory itself is on sys.path
        try:
            from activity_log import install_activity_handler
        except ImportError:
            install_activity_handler = None
    if install_activity_handler is not None:
        try:
            install_activity_handler()
        except Exception:  # noqa: BLE001 — a history tap must not break the startup
            pass

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under 'sshmap' namespace.

    Recommended usage in modules:
        log = get_logger(__name__)
        log.info("Something happened")
    """
    return logging.getLogger(f"sshmap.{name}")


def get_log_file_path() -> str:
    """Return path to the log file for display in status bar."""
    return LOG_FILE
