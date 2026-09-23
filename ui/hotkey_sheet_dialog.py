# -*- coding: utf-8 -*-
"""v1.5rc3 (ROADMAP task 4): the keyboard cheat-sheet as a window of its own.

Help → About already renders the live hotkey cheat-sheet from the action registry
(`ui/about_dialog.py:cheatsheet()`). This dialog is the SECOND way in — the `?` key
and the `Help → Keyboard shortcuts` item — for the moment the user wants the list and
nothing else: same single source of truth (the registry in `ui/hotkey_registry.py`,
merged with the user's own `hotkeys` config), so the two surfaces can never drift.

Read-only and stateless: it owns no settings, writes no config, and the registry is
re-read on every construction and on `retranslate()` — a user who rebinds Ctrl+S sees
their own binding, and a language switch re-texts the action NAMES, because those are
i18n labels read at call time.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QDialogButtonBox,
)

try:  # the ONE renderer of the cheat-sheet (Help → About builds the same text)
    from .about_dialog import cheatsheet
except ImportError:  # flat layout: the ui/ directory itself is on sys.path
    try:
        from about_dialog import cheatsheet
    except ImportError:  # pragma: no cover - a stripped build: an empty sheet
        def cheatsheet():
            return ""


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the ui/about_dialog.py pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break the dialog
        return key


class HotkeySheetDialog(QDialog):
    """The registry-derived hotkey list (Help → Keyboard shortcuts / the `?` key)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(460, 560)
        self.setWindowTitle(_t("help.cheatsheet"))
        layout = QVBoxLayout(self)

        self.hint_label = QLabel(_t("hotkeys.sheet_hint"))
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.sheet_view = QPlainTextEdit()
        self.sheet_view.setReadOnly(True)
        self.sheet_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.sheet_view, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_btn = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_btn.setText(_t("settings.cancel"))  # the About box reuses it too
        self.buttons.rejected.connect(self.reject)
        row.addWidget(self.buttons)
        layout.addLayout(row)

        self.refresh_sheet()

    # ── The sheet ───────────────────────────────────────────────────────────────

    def refresh_sheet(self) -> str:
        """Re-render the cheat-sheet from the registry; returns the text (the seam)."""
        text = ""
        try:
            text = cheatsheet()
        except Exception:  # noqa: BLE001 — the dialog must open even with no registry
            text = ""
        try:
            self.sheet_view.setPlainText(text)
        except RuntimeError:
            pass  # Qt teardown — the view is already destroyed
        return text

    def sheet_text(self) -> str:
        """The rendered sheet (the topical test's accessor — no widget poking)."""
        try:
            return self.sheet_view.toPlainText()
        except RuntimeError:
            return ""

    def retranslate(self):
        """Re-text the chrome and the action names (a language switch). Idempotent."""
        try:
            self.setWindowTitle(_t("help.cheatsheet"))
            self.hint_label.setText(_t("hotkeys.sheet_hint"))
            self.close_btn.setText(_t("settings.cancel"))
        except RuntimeError:
            return  # Qt teardown — nothing to re-text
        self.refresh_sheet()
