from typing import List, Dict, Optional

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:
    from ..graphics.connection_arrow import CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE
except ImportError:
    from graphics.connection_arrow import CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox,
)


class ConnectionDialog(QDialog):
    """Диалог создания связи между двумя узлами.

    v0.7: добавлен выбор типа связи (QComboBox) и возможность префилла
    source/target — используется режимом «перетаскивание» из MapView.
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

        # Тип связи (v0.7): порядок = порядок объявления в CONNECTION_TYPES
        self.type_combo = QComboBox()
        for cid in CONNECTION_TYPES:
            display = self.t(f"connection.type.{cid}") if self._i18n_available else cid
            self.type_combo.addItem(display, cid)

        self._node_map: Dict[str, ServerNode] = {}
        for n in nodes:
            text = f"{n.data.alias} ({n.data.host})"
            self._node_map[n.data.id] = n
            self.source.addItem(text, n.data.id)
            self.target.addItem(text, n.data.id)

        # Префилл source/target (drag-режим, v0.7)
        if default_source_id is not None:
            idx = self.source.findData(default_source_id)
            if idx >= 0:
                self.source.setCurrentIndex(idx)
        if default_target_id is not None:
            idx = self.target.findData(default_target_id)
            if idx >= 0:
                self.target.setCurrentIndex(idx)

        # Тип по умолчанию (или из старых проектов / drag-режима)
        type_idx = self.type_combo.findData(
            default_type if default_type in CONNECTION_TYPES else DEFAULT_CONNECTION_TYPE)
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)

        layout.addRow(self.t("connection.from") if self._i18n_available else "От:", self.source)
        layout.addRow(self.t("connection.to") if self._i18n_available else "К:", self.target)
        layout.addRow(self.t("connection.label") if self._i18n_available else "Метка:", self.label)
        layout.addRow(
            self.t("connection.type_label") if self._i18n_available else "Тип связи:",
            self.type_combo,
        )

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_connection(self):
        """Возвращает (source_id, target_id, label, connection_type)."""
        return (
            self.source.currentData(),
            self.target.currentData(),
            self.label.text(),
            self.type_combo.currentData(),
        )


class EditConnectionDialog(QDialog):
    """Диалог редактирования существующей связи (v0.7.3).

    В отличие от ConnectionDialog узлы менять нельзя (source/target показаны
    read-only) — редактируются только метка и тип связи.
    """

    def __init__(self, arrow: "ConnectionArrow", parent=None):
        super().__init__(parent)

        # ── i18n support (единообразно с ConnectionDialog) ──
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

        # Source/Target — read-only (связь между конкретными узлами не меняется)
        src_text = f"{arrow.source.data.alias} ({arrow.source.data.host})"
        tgt_text = f"{arrow.target.data.alias} ({arrow.target.data.host})"
        self.source = QLineEdit(src_text)
        self.source.setReadOnly(True)
        self.target = QLineEdit(tgt_text)
        self.target.setReadOnly(True)

        self.label = QLineEdit(getattr(arrow, "label_text", "") or "")
        self.type_combo = QComboBox()
        for cid in CONNECTION_TYPES:
            display = self.t(f"connection.type.{cid}") if self._i18n_available else cid
            self.type_combo.addItem(display, cid)
        type_idx = self.type_combo.findData(
            arrow.connection_type if arrow.connection_type in CONNECTION_TYPES
            else DEFAULT_CONNECTION_TYPE)
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)

        layout.addRow(
            self.t("connection.from") if self._i18n_available else "От:",
            self.source)
        layout.addRow(
            self.t("connection.to") if self._i18n_available else "К:",
            self.target)
        layout.addRow(
            self.t("connection.label") if self._i18n_available else "Метка:",
            self.label)
        layout.addRow(
            self.t("connection.type_label") if self._i18n_available else "Тип связи:",
            self.type_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_connection(self):
        """Возвращает (label, connection_type) — узлы фиксированы."""
        return (self.label.text(), self.type_combo.currentData())
