from typing import List, Dict, Optional, TYPE_CHECKING

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:
    from ..graphics.connection_arrow import CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE
except ImportError:
    from graphics.connection_arrow import CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE

if TYPE_CHECKING:  # the `arrow` parameter of EditConnectionDialog (no runtime import needed)
    from graphics.connection_arrow import ConnectionArrow

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox, QCheckBox,
)


class _LabelLineEdit(QLineEdit):
    """QLineEdit with an INPUT limit that does not truncate already-set text.

    v1.1.1 (ROADMAP item 6): Qt setMaxLength() TRUNCATES the current text when the
    limit is set (verified on PySide6 6.11: both orders — setText→setMaxLength and
    setMaxLength→setText result in truncation), and old projects with labels longer
    than 20 characters lost their tail in EditConnectionDialog ("limit only for input"
    — old labels are read unchanged). So the limit is enforced by a guard on
    textChanged: programmatic setText (loading an old label) passes through as-is,
    while user input pushing the text past max(limit, length at load time) is cut
    from the tail. maxLength() reports the set value.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._input_max = 16777215   # Qt default — no limit
        self._loaded_len = 0         # text length at programmatic setText (old label)
        self._guarding = False
        self.textChanged.connect(self._enforce_input_limit)
        # Text from the CONSTRUCTOR arrived before textChanged was connected — treat it
        # as a loaded (old) label, otherwise the guard would cut input by the limit
        # instead of by its length.
        self._loaded_len = len(self.text())

    def setMaxLength(self, n: int):
        """Remember the input limit without truncating existing text (Qt does)."""
        self._input_max = max(0, int(n))

    def maxLength(self) -> int:
        return self._input_max

    def setText(self, text: str):
        # Programmatic set (loading an old label) — exempt from the input limit;
        # guard flag: textChanged from super().setText() arrives BEFORE _loaded_len
        # is updated and without the flag would cut the loaded label itself.
        self._guarding = True
        super().setText(text)
        self._loaded_len = len(text)
        self._guarding = False

    def _enforce_input_limit(self, text: str):
        if self._guarding:
            return
        ceiling = max(self._input_max, self._loaded_len)
        if len(text) <= ceiling:
            return
        # Excess from input (typing/paste) — cut from the tail; cursor stays within the allowed range.
        self._guarding = True
        cur = min(self.cursorPosition(), ceiling)
        super().setText(text[:ceiling])
        self.setCursorPosition(cur)
        self._guarding = False


class ConnectionDialog(QDialog):
    """Dialog for creating a connection between two nodes.

    v0.7: added connection type selection (QComboBox) and source/target prefill
    capability — used by the "drag" mode from MapView.
    """

    def __init__(self, nodes: List[ServerNode], parent=None,
                 default_source_id: Optional[str] = None,
                 default_target_id: Optional[str] = None,
                 default_type: str = DEFAULT_CONNECTION_TYPE):
        super().__init__(parent)

        # ── i18n support ────────────────────────────────
        self._i18n_available = False

        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()  # Use already-set global language (restored from config)
            self._i18n_available = True

            self.setWindowTitle(__t("dialog.add_connection"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop

        self.setMinimumWidth(300)
        layout = QFormLayout(self)

        self.source = QComboBox()
        self.target = QComboBox()
        self.label = QLineEdit()
        # v1.1.1 (ROADMAP item 6): 20-character limit — for INPUT only (new dialog);
        # hint in i18n (connection.label_hint).
        self.label.setMaxLength(20)
        if self._i18n_available:
            self.label.setPlaceholderText(self.t("connection.label_hint"))

        # Connection type (v0.7): order = declaration order in CONNECTION_TYPES
        self.type_combo = QComboBox()
        for cid in CONNECTION_TYPES:
            display = self.t(f"connection.type.{cid}") if self._i18n_available else cid
            self.type_combo.addItem(display, cid)

        # v1.2.6: bidirectional connection (arrowheads on both ends). The checkbox has
        # ITS OWN label — addRow(widget) stretches it across both form columns.
        self.bidirectional_check = QCheckBox(
            self.t("connection.bidirectional") if self._i18n_available else "Bidirectional")

        self._node_map: Dict[str, ServerNode] = {}
        for n in nodes:
            text = f"{n.data.alias} ({n.data.host})"
            self._node_map[n.data.id] = n
            self.source.addItem(text, n.data.id)
            self.target.addItem(text, n.data.id)

        # Prefill source/target (drag mode, v0.7)
        if default_source_id is not None:
            idx = self.source.findData(default_source_id)
            if idx >= 0:
                self.source.setCurrentIndex(idx)
        if default_target_id is not None:
            idx = self.target.findData(default_target_id)
            if idx >= 0:
                self.target.setCurrentIndex(idx)

        # Default type (or from old projects / drag mode)
        type_idx = self.type_combo.findData(
            default_type if default_type in CONNECTION_TYPES else DEFAULT_CONNECTION_TYPE)
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)

        layout.addRow(self.t("connection.from") if self._i18n_available else "From:", self.source)
        layout.addRow(self.t("connection.to") if self._i18n_available else "To:", self.target)
        layout.addRow(self.t("connection.label") if self._i18n_available else "Label:", self.label)
        layout.addRow(
            self.t("connection.type_label") if self._i18n_available else "Connection type:",
            self.type_combo,
        )
        # v1.2.6: checkbox spans the full form width (label — the checkbox's own text)
        layout.addRow(self.bidirectional_check)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_connection(self):
        """Returns (source_id, target_id, label, connection_type, bidirectional).

        v1.2.6: the 5th element — bidirectional mode (bool); before v1.2.6 it had 4 elements.
        """
        return (
            self.source.currentData(),
            self.target.currentData(),
            self.label.text(),
            self.type_combo.currentData(),
            self.bidirectional_check.isChecked(),
        )


class EditConnectionDialog(QDialog):
    """Dialog for editing an existing connection (v0.7.3).

    Unlike ConnectionDialog, the nodes cannot be changed (source/target are shown
    read-only) — only the label and the connection type are edited.
    """

    def __init__(self, arrow: "ConnectionArrow", parent=None):
        super().__init__(parent)

        # ── i18n support (consistent with ConnectionDialog) ──
        self._i18n_available = False
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()
            self._i18n_available = True
            self.setWindowTitle(__t("dialog.edit_connection"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop

        self.setMinimumWidth(300)
        layout = QFormLayout(self)

        # Source/Target — read-only (the connection between specific nodes does not change)
        src_text = f"{arrow.source.data.alias} ({arrow.source.data.host})"
        tgt_text = f"{arrow.target.data.alias} ({arrow.target.data.host})"
        self.source = QLineEdit(src_text)
        self.source.setReadOnly(True)
        self.target = QLineEdit(tgt_text)
        self.target.setReadOnly(True)

        # v1.1.1 (ROADMAP item 6): 20-character limit — for INPUT only. _LabelLineEdit:
        # Qt setMaxLength() immediately truncates existing text (verified on PySide6 6.11),
        # so old projects with long labels are read unchanged, while the limit is
        # enforced by a guard on input (see the class).
        self.label = _LabelLineEdit(getattr(arrow, "label_text", "") or "")
        self.label.setMaxLength(20)
        if self._i18n_available:
            self.label.setPlaceholderText(self.t("connection.label_hint"))
        self.type_combo = QComboBox()
        for cid in CONNECTION_TYPES:
            display = self.t(f"connection.type.{cid}") if self._i18n_available else cid
            self.type_combo.addItem(display, cid)
        type_idx = self.type_combo.findData(
            arrow.connection_type if arrow.connection_type in CONNECTION_TYPES
            else DEFAULT_CONNECTION_TYPE)
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)

        # v1.2.6: bidirectional mode — prefilled from the arrow's state (getattr guard:
        # an object without the attribute, e.g. a test double, reads as the default).
        self.bidirectional_check = QCheckBox(
            self.t("connection.bidirectional") if self._i18n_available else "Bidirectional")
        self.bidirectional_check.setChecked(bool(getattr(arrow, "bidirectional", False)))

        layout.addRow(
            self.t("connection.from") if self._i18n_available else "From:",
            self.source)
        layout.addRow(
            self.t("connection.to") if self._i18n_available else "To:",
            self.target)
        layout.addRow(
            self.t("connection.label") if self._i18n_available else "Label:",
            self.label)
        layout.addRow(
            self.t("connection.type_label") if self._i18n_available else "Connection type:",
            self.type_combo)
        # v1.2.6: checkbox spans the full form width (label — the checkbox's own text)
        layout.addRow(self.bidirectional_check)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_connection(self):
        """Returns (label, connection_type, bidirectional) — the nodes are fixed.

        v1.2.6: the 3rd element — bidirectional mode (bool); before v1.2.6 it had 2 elements.
        """
        return (self.label.text(), self.type_combo.currentData(),
                self.bidirectional_check.isChecked())
