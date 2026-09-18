# -*- coding: utf-8 -*-
"""v1.3.3.3 (ROADMAP v1.3.3.3, task 6): the "About" window.

Help → About — the "where is what" window the application did not have. It answers
four questions in one place, and every answer comes from its single source of truth:

* **which version is this** — ``APP_NAME`` / ``APP_VERSION`` from ``version.py``
  (never a literal, never the window title: the About box is the one place a user
  reads the version off);
* **what may I do with it** — the license (MIT) and a pointer to the LICENSE file;
* **where does my data live** — the paths of ``~/.sshmap/config.json`` and
  ``~/.sshmap/logs/``, plus a button that opens the folder in the OS file manager
  (the "I need to send you my config" case);
* **what can I press** — the **hotkey cheat-sheet generated FROM the action registry**
  (``ui/hotkey_registry.py``): the LIVE values, i.e. what the user actually has
  configured, never a hardcoded list. It cannot drift and it costs nothing — the same
  registry that installs the shortcuts renders them here.

The dialog is read-only: it owns no settings and writes no config, so closing it is
the only outcome. The i18n keys are ``about.*``; like every UI container it owns a
``retranslate()`` (the v1.3.3.1 container rule) and swallows ``RuntimeError`` on the
teardown races.
"""

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QPlainTextEdit, QDialogButtonBox,
)

try:  # i18n — a top-level package (flat run from the project root)
    from i18n import t as _translate
except Exception:  # pragma: no cover - fallback path
    try:
        from .i18n import t as _translate
    except Exception:
        _translate = None

try:  # v1.3.3.3: the version — the single source of truth (never a literal here)
    from ..version import APP_NAME, APP_VERSION
except ImportError:
    try:
        from version import APP_NAME, APP_VERSION
    except ImportError:  # pragma: no cover - a stripped build
        APP_NAME, APP_VERSION = "SSH Map", "0.0.0"

try:  # v1.3.3.3: the hotkey cheat-sheet is generated from the action registry
    from .hotkey_registry import action_ids, action_label_key, configured_hotkeys
except ImportError:
    try:
        from hotkey_registry import action_ids, action_label_key, configured_hotkeys
    except ImportError:  # pragma: no cover - a stripped build: an empty cheat-sheet
        def action_ids():
            return []

        def action_label_key(_action_id):
            return ""

        def configured_hotkeys():
            return {}

LICENSE_NAME = "MIT"   # the project license (LICENSE in the project root)


def _t(key: str, **kw) -> str:
    """Safe translation (the ui/settings_dialog.py pattern): without i18n — the key."""
    if _translate is not None:
        try:
            return _translate(key, **kw) if kw else _translate(key)
        except Exception:  # noqa: BLE001 — an i18n failure must not break the dialog
            pass
    return key


def app_config_dir() -> str:
    """The application's data directory (``~/.sshmap``) — the config.json owner."""
    return os.path.join(os.path.expanduser("~"), ".sshmap")


def app_logs_dir() -> str:
    """The log directory (``~/.sshmap/logs``) — the RotatingFileHandler target."""
    return os.path.join(app_config_dir(), "logs")


def app_config_path() -> str:
    """The full path of ``~/.sshmap/config.json`` (may not exist yet)."""
    return os.path.join(app_config_dir(), "config.json")


def open_config_folder() -> bool:
    """Open the data folder in the OS file manager (the About button).

    A thin seam so the test can monkeypatch ONE function instead of the OS (the
    ``_open_log_file`` path does the same inline). The folder is created when it does
    not exist yet — a "show me where my data lives" button that opens nothing is
    worse than a directory that appears on demand (``~/.sshmap`` is created by the
    first settings write anyway). ``os.startfile`` on Windows, ``open`` on macOS and
    ``xdg-open`` elsewhere — the same three branches as the log-file opener.
    """
    path = app_config_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass  # not writable / already a file — the OS call reports the truth
    if sys.platform == "win32":
        os.startfile(path)          # noqa: S606 — a directory, not an executable
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')  # noqa: S605 — fixed literal prefix
    else:
        os.system(f'xdg-open "{path}"')  # noqa: S605 — fixed literal prefix
    return True


def cheatsheet() -> str:
    """The live hotkey cheat-sheet, rendered FROM the action registry.

    One ``<action name>  <sequence>`` line per action that HAS an effective sequence;
    the name is the action's i18n label (translated with the CURRENT language at call
    time — the dialog re-renders on ``retranslate()``), the sequence is the canonical
    PortableText of ``configured_hotkeys()`` (registry default merged with
    ``~/.sshmap/config.json``), so a user who re-bound Ctrl+S sees their own binding.

    Actions with an EMPTY sequence are skipped: the cheat-sheet answers "what can I
    press", and listing ~15 rows of "no hotkey" would bury the answer (they stay
    visible and assignable in Settings → Hotkeys). Sorted by the action name, not by
    the registry order: this is a reference the user scans by name.
    Never raises — an empty registry yields an empty string.
    """
    try:
        mapping = configured_hotkeys()
    except Exception:  # noqa: BLE001 — a broken registry must not break the About box
        return ""
    rows = []
    for action_id in action_ids():
        seq = str(mapping.get(action_id, "") or "").strip()
        if not seq:
            continue
        label_key = action_label_key(action_id)
        name = _t(label_key) if label_key else action_id
        rows.append((name or action_id, seq))
    rows.sort(key=lambda r: (r[0].lower(), r[1]))
    width = max((len(name) for name, _seq in rows), default=0)
    return "\n".join(f"{name.ljust(width)}   {seq}" for name, seq in rows)


class AboutDialog(QDialog):
    """v1.3.3.3 (task 6): the About box — version, license, paths, cheat-sheet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(560, 520)
        self.setWindowTitle(_t("about.title"))
        layout = QVBoxLayout(self)

        # ── the identity block: name + version (version.py) + license ──────────
        self.title_label = QLabel(f"{APP_NAME} {APP_VERSION}")
        font = self.title_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label)

        self.license_label = QLabel(_t("about.license", license=LICENSE_NAME))
        self.license_label.setWordWrap(True)
        layout.addWidget(self.license_label)

        # ── the paths: config.json + logs/ (a grid so both labels line up) ─────
        grid = QGridLayout()
        self._lbl_config = QLabel(_t("about.config_path"))
        self.config_value = QLabel(app_config_path())
        self.config_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.config_value.setWordWrap(True)
        self._lbl_logs = QLabel(_t("about.logs_path"))
        self.logs_value = QLabel(app_logs_dir())
        self.logs_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.logs_value.setWordWrap(True)
        grid.addWidget(self._lbl_config, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.config_value, 0, 1)
        grid.addWidget(self._lbl_logs, 1, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.logs_value, 1, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # ── the cheat-sheet: rendered from the registry, read-only ─────────────
        self._lbl_hotkeys = QLabel(_t("about.hotkeys"))
        layout.addWidget(self._lbl_hotkeys)
        self.hotkeys_view = QPlainTextEdit()
        self.hotkeys_view.setReadOnly(True)
        self.hotkeys_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.hotkeys_view, 1)
        self._refresh_cheatsheet()

        # ── the buttons: open the data folder + Close ──────────────────────────
        row = QHBoxLayout()
        self.open_folder_btn = QPushButton(_t("about.open_config_dir"))
        self.open_folder_btn.clicked.connect(self._on_open_config_folder)
        row.addWidget(self.open_folder_btn)
        row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # Qt's Close button is stock text; the dialog owns its own label so the
        # language switch re-texts it (the settings hub pattern — settings.cancel
        # is reused: "Close"/"Закрыть" is the same word the user already knows).
        self.close_btn = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_btn.setText(_t("settings.cancel"))
        self.buttons.rejected.connect(self.reject)
        row.addWidget(self.buttons)
        layout.addLayout(row)

    # ── the cheat-sheet ─────────────────────────────────────────────────────────

    def _refresh_cheatsheet(self):
        """Render the registry cheat-sheet into the read-only view. Never raises."""
        try:
            self.hotkeys_view.setPlainText(cheatsheet())
        except RuntimeError:
            pass  # Qt teardown — the view is already destroyed

    def cheatsheet_text(self) -> str:
        """The rendered cheat-sheet (the test seam — no widget poking needed)."""
        try:
            return self.hotkeys_view.toPlainText()
        except RuntimeError:
            return ""

    # ── the config folder button ────────────────────────────────────────────────

    def _on_open_config_folder(self):
        """Open ``~/.sshmap`` in the OS file manager (a monkeypatchable seam).

        A failure is reported in the dialog itself instead of raising into the Qt
        event loop: this is a convenience button, and a headless / no-file-manager
        environment must not take the window down. The error reuses the existing
        ``msg.error_title`` key — a new string for a case the user cannot act on is
        not worth a key.
        """
        try:
            open_config_folder()
        except Exception as e:  # noqa: BLE001 — a UI convenience, never fatal
            try:
                self._lbl_hotkeys.setText(f'{_t("msg.error_title")}: {e}')
            except RuntimeError:
                pass

    # ── i18n (the v1.3.3.1 container rule) ──────────────────────────────────────

    def retranslate(self):
        """Re-text the dialog (a language switch while it is open). Idempotent."""
        try:
            self.setWindowTitle(_t("about.title"))
            self.license_label.setText(_t("about.license", license=LICENSE_NAME))
            self._lbl_config.setText(_t("about.config_path"))
            self._lbl_logs.setText(_t("about.logs_path"))
            self._lbl_hotkeys.setText(_t("about.hotkeys"))
            self.open_folder_btn.setText(_t("about.open_config_dir"))
            self.close_btn.setText(_t("settings.cancel"))
        except RuntimeError:
            return  # Qt teardown — nothing to re-text
        self._refresh_cheatsheet()   # the action NAMES follow the language too
