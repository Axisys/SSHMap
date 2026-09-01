# -*- coding: utf-8 -*-
"""v1.0RC4: Диалог настройки «Быстрого запуска» для одного сервера.

Пункты Быстрого запуска — список ссылок/команд, привязанный к серверу
(models/server.py: ServerData.quick_launch). Отсюда он попадает в контекстное
меню (ПКМ по строке сайдбара и по узлу карты) как подменю «Быстрый запуск».

  * type="url"     — value открывается в браузере по умолчанию (webbrowser);
  * type="command" — value отправляется первой командой в SSH-терминал сервера.

Паттерн диалога — как у AddServerDialog: i18n через try-import с русским
fallback, get_entries() возвращает список dicts после accept().
"""
from typing import List, Optional

try:
    from ..models.server import ServerData, sanitize_quick_launch
except ImportError:
    from models.server import ServerData, sanitize_quick_launch

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QMessageBox, QAbstractItemView,
)


class QuickLaunchDialog(QDialog):
    """Настройка пунктов Быстрого запуска для одного сервера.

    get_entries() — список {"type": "url"|"command", "name": str, "value": str}
    (порядок = порядок в таблице). Вызывать после exec() == Accepted.
    """

    def __init__(self, parent=None, server_data: Optional[ServerData] = None):
        super().__init__(parent)

        # ── i18n support (паттерн AddServerDialog) ────────────────────────
        self._i18n_available = False
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()
            self._i18n_available = True
            alias = getattr(server_data, "alias", "") if server_data else ""
            self.setWindowTitle(__t("dialog.quick_launch", alias=alias or "?"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
            alias = getattr(server_data, "alias", "") if server_data else ""
            self.setWindowTitle(f"Быстрый запуск — {alias or '?'}")

        # Точки входа: сервер известен (свойства/контекст карты) или нет.
        self._server_data = server_data
        self.setMinimumWidth(520)

        # Текущий список пунктов (источник правды; таблица — его отображение)
        self._entries: List[dict] = []
        if server_data is not None:
            self._entries = [dict(e) for e in sanitize_quick_launch(
                getattr(server_data, "quick_launch", None))]

        self._build_ui()

    def _tr(self, key: str, **kw) -> str:
        """Перевод с fallback на сам ключ (без i18n — русские литералы в UI)."""
        if self._i18n_available:
            try:
                return self.t(key, **kw)
            except Exception:  # noqa: BLE001 — сбой i18n не роняет диалог
                pass
        return key

    def _build_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel(
            self._tr("dialog.quick_launch_desc") if self._i18n_available else
            "Ссылки открываются в браузере по умолчанию; команды отправляются\n"
            "первой командой в SSH-терминал сервера.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Таблица существующих пунктов ───────────────────────────────────
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            self._tr("ql.type") if self._i18n_available else "Тип",
            self._tr("ql.name") if self._i18n_available else "Название",
            self._tr("ql.value") if self._i18n_available else "Значение",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table)

        for e in self._entries:
            self._append_row(e["type"], e["name"], e["value"])

        # ── Строка добавления: [тип] [название] [значение] [Добавить] ──────
        self.type_combo = QComboBox()
        self.type_combo.addItem(
            self._tr("ql.type.url") if self._i18n_available else "Ссылка (URL)", "url")
        self.type_combo.addItem(
            self._tr("ql.type.command") if self._i18n_available else "Команда", "command")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Webmin, K9S, ...")
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText(
            self._tr("ql.value_hint_url") if self._i18n_available else "http://host:port/path")

        btn_add = QPushButton(
            self._tr("ql.add") if self._i18n_available else "Добавить")
        btn_add.clicked.connect(self._add_entry)

        add_row = QHBoxLayout()
        add_row.addWidget(self.type_combo)
        add_row.addWidget(self.name_edit, 1)
        add_row.addWidget(self.value_edit, 2)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        # ── Удалить выбранный + ОК/Отмена ──────────────────────────────────
        btn_remove = QPushButton(
            self._tr("ql.remove") if self._i18n_available else "Удалить")
        btn_remove.clicked.connect(self._remove_selected)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(btn_remove)
        bottom_row.addStretch()
        bottom_row.addWidget(btns)
        layout.addLayout(bottom_row)

        self._on_type_changed(0)  # плейсхолдер значения под тип "url"

    def _append_row(self, etype: str, name: str, value: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        type_label = (self._tr("ql.type.url") if etype == "url" else self._tr("ql.type.command")) \
            if self._i18n_available else ("Ссылка (URL)" if etype == "url" else "Команда")
        for col, text in enumerate((type_label, name, value)):
            self.table.setItem(row, col, QTableWidgetItem(text))

    def _on_type_changed(self, index: int):
        """Плейсхолдер поля значения зависит от выбранного типа."""
        if self.type_combo.currentData() == "command":
            self.value_edit.setPlaceholderText(
                self._tr("ql.value_hint_command") if self._i18n_available else "k9s, htop, docker ps ...")
        else:
            self.value_edit.setPlaceholderText(
                self._tr("ql.value_hint_url") if self._i18n_available else "http://host:port/path")

    def _warn(self, text: str):
        QMessageBox.warning(self,
                            self._tr("msg.error_title") if self._i18n_available else "Ошибка",
                            text)

    def _add_entry(self):
        """Валидация + добавление пункта в таблицу и список."""
        etype = self.type_combo.currentData() or "url"
        name = self.name_edit.text().strip()
        value = self.value_edit.text().strip()
        if not name:
            self._warn(self._tr("validation.ql_name_empty") if self._i18n_available
                       else "Название пункта не может быть пустым.")
            return
        if not value:
            self._warn(self._tr("validation.ql_value_empty") if self._i18n_available
                       else "Значение (URL или команда) не может быть пустым.")
            return
        if etype == "url" and not (value.lower().startswith("http://")
                                   or value.lower().startswith("https://")):
            self._warn(self._tr("validation.ql_url_scheme") if self._i18n_available
                       else "Ссылка должна начинаться с http:// или https://")
            return
        # Дубликаты (тип+название) не плодим — пункт уже есть
        for e in self._entries:
            if e["type"] == etype and e["name"].lower() == name.lower():
                self._warn(self._tr("validation.ql_duplicate", name=name) if self._i18n_available
                           else f"Пункт «{name}» уже добавлен.")
                return
        self._entries.append({"type": etype, "name": name, "value": value})
        self._append_row(etype, name, value)
        self.name_edit.clear()
        self.value_edit.clear()

    def _remove_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            del self._entries[row]
            self.table.removeRow(row)

    def get_entries(self) -> List[dict]:
        """Список пунктов (копии — внешнее изменение таблицы не влияет на модель)."""
        return [dict(e) for e in self._entries]
