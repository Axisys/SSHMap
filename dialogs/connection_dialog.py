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


class _LabelLineEdit(QLineEdit):
    """QLineEdit с лимитом ВВОДА, который не обрезает уже установленный текст.

    v1.1.1 (ROADMAP пункт 6): Qt setMaxLength() ОБРЕЗАЕТ текущий текст при установке
    лимита (проверено на PySide6 6.11: оба порядка — setText→setMaxLength и
    setMaxLength→setText дают обрезку), и старые проекты с метками длиннее 20 символов
    теряли хвост в EditConnectionDialog («лимит только на ввод» — старые метки читаются
    без изменений). Поэтому лимит держит guard на textChanged: программный setText
    (загрузка старой метки) проходит как есть, пользовательский ввод, выводящий текст
    за max(лимит, длина при загрузке), обрезается хвостом. maxLength() отчитывает
    установленное значение.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._input_max = 16777215   # дефолт Qt — без лимита
        self._loaded_len = 0         # длина текста при программном setText (старая метка)
        self._guarding = False
        self.textChanged.connect(self._enforce_input_limit)
        # Текст из КОНСТРУКТОРА прошёл до подключения textChanged — считаем его
        # загруженной (старой) меткой, иначе guard обрежет ввод по лимиту, а не
        # по её длине.
        self._loaded_len = len(self.text())

    def setMaxLength(self, n: int):
        """Запомнить лимит ввода, не обрезая существующий текст (Qt это делает)."""
        self._input_max = max(0, int(n))

    def maxLength(self) -> int:
        return self._input_max

    def setText(self, text: str):
        # Программная установка (загрузка старой метки) — не под лимит ввода;
        # guard-флаг: textChanged от super().setText() долетает ДО обновления
        # _loaded_len и без флага обрезал бы саму загружаемую метку.
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
        # Избыток от ввода (печать/вставка) — обрезаем хвост; курсор — в пределах допустимого.
        self._guarding = True
        cur = min(self.cursorPosition(), ceiling)
        super().setText(text[:ceiling])
        self.setCursorPosition(cur)
        self._guarding = False


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
        # v1.1.1 (ROADMAP пункт 6): лимит 20 символов — только на ВВОД (новый диалог);
        # подсказка в i18n (connection.label_hint).
        self.label.setMaxLength(20)
        if self._i18n_available:
            self.label.setPlaceholderText(self.t("connection.label_hint"))

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

        # v1.1.1 (ROADMAP пункт 6): лимит 20 символов — только на ВВОД. _LabelLineEdit:
        # Qt setMaxLength() сразу обрезает существующий текст (проверено PySide6 6.11),
        # поэтому старые проекты с длинными метками читаются без изменений, а лимит
        # держит guard на вводе (см. класс).
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
