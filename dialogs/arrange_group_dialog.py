# -*- coding: utf-8 -*-
"""v1.6 (ROADMAP task 6): the arrangement question of a group.

ONE dialog for the three modes the plan declares — a vertical line, a horizontal line
and rows — because the rows mode is the only one that ASKS anything: the COUNT. The
dialog therefore opens on ``vertical`` (the no-question default), and the count field
is enabled only while the rows mode is selected, so pressing Enter twice is a vertical
line and never a silent "rows of 3".

The geometry itself is not here: `graphics.node_group.arrange_positions()` is the pure
half, and the window turns its answer into ONE undo command (`CmdArrangeGroup`).
"""
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton,
    QSpinBox, QVBoxLayout,
)

try:  # the pure mode vocabulary of the geometry (no Qt there)
    from ..graphics.node_group import (ARRANGE_HORIZONTAL, ARRANGE_MODES, ARRANGE_ROWS,
                                       ARRANGE_VERTICAL)
except ImportError:
    from graphics.node_group import (ARRANGE_HORIZONTAL, ARRANGE_MODES, ARRANGE_ROWS,
                                     ARRANGE_VERTICAL)

#: The default of the rows mode (how many cards per line the spinbox starts at).
ROWS_DEFAULT = 3


class ArrangeGroupDialog(QDialog):
    """Ask HOW to arrange a group's members (v1.6, ROADMAP task 6).

    `mode()` and `per_line()` are the whole answer; both are valid by construction (the
    radios are a closed set, the spinbox carries its own range), so the caller never
    validates anything and a cancelled dialog changes nothing.
    """

    def __init__(self, count: int = 0, parent=None):
        super().__init__(parent)
        self._count = max(int(count or 0), 0)
        self._i18n_available = False
        try:
            from i18n import t as __t
            self.t = __t
            self._i18n_available = True
            self.setWindowTitle(__t("arrange.title"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
            self.setWindowTitle("Arrange group members")
        self.setMinimumWidth(340)

        self._build_ui()

    def _tr(self, key: str, **kw) -> str:
        """Translation with the English literal as the fallback (the dialog convention)."""
        if self._i18n_available:
            try:
                return self.t(key, **kw)
            except Exception:  # noqa: BLE001 — an i18n failure must not break the dialog
                pass
        return key

    def _build_ui(self):
        layout = QVBoxLayout(self)
        head = QLabel(self._tr("arrange.hint", count=self._count))
        head.setWordWrap(True)
        layout.addWidget(head)

        self._group = QButtonGroup(self)
        self.vertical_radio = QRadioButton(self._tr("arrange.mode.vertical"))
        self.horizontal_radio = QRadioButton(self._tr("arrange.mode.horizontal"))
        self.rows_radio = QRadioButton(self._tr("arrange.mode.rows"))
        for index, (radio, mode) in enumerate((
                (self.vertical_radio, ARRANGE_VERTICAL),
                (self.horizontal_radio, ARRANGE_HORIZONTAL),
                (self.rows_radio, ARRANGE_ROWS))):
            radio.setProperty("mode", mode)
            self._group.addButton(radio, index)
            layout.addWidget(radio)
        self.vertical_radio.setChecked(True)

        rows_row = QHBoxLayout()
        rows_row.addSpacing(24)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 50)
        self.rows_spin.setValue(ROWS_DEFAULT)
        rows_row.addWidget(self.rows_spin)
        rows_row.addWidget(QLabel(self._tr("arrange.mode.rows.unit")))
        rows_row.addStretch(1)
        layout.addLayout(rows_row)

        note = QLabel(self._tr("arrange.note"))
        note.setWordWrap(True)
        layout.addWidget(note)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.rows_radio.toggled.connect(self._sync_rows_enabled)
        self._sync_rows_enabled(False)

    def _sync_rows_enabled(self, _checked: bool = False):
        """The count is a question only the rows mode asks (the plan's boundary)."""
        try:
            self.rows_spin.setEnabled(self.rows_radio.isChecked())
        except RuntimeError:
            pass  # Qt teardown

    def mode(self) -> str:
        """The chosen arrangement mode — one of ``ARRANGE_MODES``."""
        for radio in (self.vertical_radio, self.horizontal_radio, self.rows_radio):
            try:
                if radio.isChecked():
                    return str(radio.property("mode") or ARRANGE_VERTICAL)
            except RuntimeError:
                break
        return ARRANGE_VERTICAL

    def set_mode(self, mode: str):
        """Select a mode programmatically (the topical test's seam)."""
        wanted = str(mode or "").strip().lower()
        for radio in (self.vertical_radio, self.horizontal_radio, self.rows_radio):
            if str(radio.property("mode")) == wanted:
                radio.setChecked(True)
                break
        self._sync_rows_enabled(self.rows_radio.isChecked())

    def per_line(self) -> int:
        """The cards per row (meaningful in the rows mode only)."""
        try:
            return int(self.rows_spin.value())
        except RuntimeError:
            return ROWS_DEFAULT
