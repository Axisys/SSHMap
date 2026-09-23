# -*- coding: utf-8 -*-
"""v1.5rc2 (ROADMAP task 3): the export options dialog — the print-palette opt-out.

An export is a different medium from the screen, so the ROADMAP pinned the decision
at the START of the release: **print-friendly by default**. "Print-friendly" is not a
third palette to maintain — it is the LIGHT instance with the high-contrast lines
(`ui/theme.py export_theme(PALETTE_PRINT)`), which the v1.5rc1 contrast gate already
measured at AA. This dialog is the ONE place the user can opt out and keep the current
look, and it is deliberately minimal: a hint line and one checkbox.

The window keeps the CALLING side (which file, which status line); the dialog only
answers a palette id through :meth:`chosen_palette`, so the four export commands
(PNG/JPEG, PDF, SVG, drawio) share one question and one vocabulary.
"""

try:
    from ..i18n import t
except ImportError:
    try:
        from i18n import t
    except ImportError:  # flat layout without i18n — the keys as-is (main_window pattern)
        def t(key, **kwargs):
            return key.format(**kwargs) if kwargs else key

try:  # the palette ids (pure data — ui/theme.py imports no PySide6)
    from ..ui import theme
except ImportError:
    from ui import theme

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)


class ExportOptionsDialog(QDialog):
    """One hint + one checkbox: the print-friendly palette or the current theme.

    The checkbox is UNCHECKED by default (the print-friendly palette), and the caller
    may pass the choice of the previous export of the session (`use_current_theme`),
    so a user who exports ten maps in a row answers the question once.
    """

    def __init__(self, parent=None, use_current_theme: bool = False):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.export_options"))
        try:
            self.setModal(True)
        except RuntimeError:  # pragma: no cover — Qt teardown
            pass

        layout = QVBoxLayout(self)
        hint = QLabel(t("export.palette_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("ExportPaletteHint")
        layout.addWidget(hint)

        self.chk_current_theme = QCheckBox(t("export.use_current_theme"))
        self.chk_current_theme.setChecked(bool(use_current_theme))
        self.chk_current_theme.setToolTip(t("export.use_current_theme"))
        layout.addWidget(self.chk_current_theme)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.buttons = buttons

    # ── The answer (the only API the callers use) ────────────────────────────────

    def use_current_theme(self) -> bool:
        """Did the user ask for the CURRENT theme instead of the print-friendly page?"""
        return bool(self.chk_current_theme.isChecked())

    def chosen_palette(self) -> str:
        """The palette id (`ui/theme.py PALETTE_PRINT` / `PALETTE_THEME`) of this dialog."""
        return theme.PALETTE_THEME if self.use_current_theme() else theme.PALETTE_PRINT
