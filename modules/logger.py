"""Centralized logging for SSH Map.

Usage in any module:
    from modules.logger import get_logger
    log = get_logger(__name__)
    log.info("Server added", extra={"server": "web-1"})
    log.error("Connection failed", exc_info=True)

All logs go to: ~/.sshmap/logs/ (created automatically)
"""

import logging
import os
import sys


LOG_DIR = os.path.join(os.path.expanduser("~"), ".sshmap", "logs")
LOG_FILE = os.path.join(LOG_DIR, "sshmap.log")
MAX_LOG_SIZE_MB = 5  # Rotate after this size


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

    # ── Console handler (DEBUG level only) ────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)  # Only warnings+errors on console
    console_formatter = logging.Formatter(
        "[%(levelname)-7s] %(name)s: %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

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
