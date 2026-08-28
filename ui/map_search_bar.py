# -*- coding: utf-8 -*-
"""v0.9.8 — строка поиска по карте (Ctrl+F): плавающая панель поверх canvas.

ROADMAP v0.9.8:
  #1 Ctrl+F → строка поиска поверх canvas: подсветка совпадающих узлов
     (alias/host/ip/comment).
  #2 Enter/Shift+Enter — переход между результатами с центрированием и
     кратковременной рамкой-акцентом (reveal_flash, паттерн пульса set_status).
  #3 Несовпавшие ноды затемняются (focus/dim), чтобы совпадения читались мгновенно.

Виджет НЕ содержит логику поиска: он только принимает ввод и эмитит сигналы —
какие узлы совпадают, что затемнять и куда центрировать решает MainWindow
(единый источник истины — ui/main_window.py). Тёмная тема в палитре приложения
(#0f172a фон карточки, #38bdf8 акцент, #e2e8f0 текст — те же цвета, что у узлов).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


def _t(key: str) -> str:
    """Безопасный i18n-хук (единообразно с map_view/server_node)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


# Тёмная тема панели (палитра приложения): карточка #0f172a на фоне canvas #020617,
# акцентная рамка #38bdf8 — тот же, что у совпадений/выделения MapView.
_BAR_STYLE = """
QWidget#MapSearchBar {
    background-color: #0f172a;
    border: 1px solid #38bdf8;
    border-radius: 8px;
}
QLineEdit {
    background-color: transparent;
    border: none;
    color: #e2e8f0;
    font-size: 13px;
    padding: 2px 4px;
    selection-background-color: #38bdf8;
}
QLabel {
    color: #94a3b8;
    font-size: 12px;
}
QPushButton {
    background-color: transparent;
    border: none;
    color: #94a3b8;
    font-size: 15px;
}
QPushButton:hover { color: #e2e8f0; }
"""


class _SearchLineEdit(QLineEdit):
    """Поле ввода с навигационными клавишами.

    Enter — следующий результат, Shift+Enter — предыдущий, Esc — закрыть панель.
    QLineEdit.returnPressed срабатывает и на Enter, и на Shift+Enter (и модификаторы
    не передаёт), поэтому keyPressEvent перехватываем сами.
    """

    next_pressed = Signal()
    prev_pressed = Signal()
    close_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self.prev_pressed.emit()
            else:
                self.next_pressed.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.close_pressed.emit()
            event.accept()  # без «бипа» — Esc осмысленное действие, а не ошибка
            return
        super().keyPressEvent(event)


class MapSearchBar(QWidget):
    """v0.9.8: плавающая строка поиска по карте (родитель — MapView).

    Состав: [поле ввода] [счётчик «k / N» | «Нет совпадений»] [×].
    Сигналы: query_changed(str) при каждом изменении текста; next_requested /
    prev_requested — Enter/Shift+Enter; close_requested — Esc или кнопка «×».
    """

    query_changed = Signal(str)
    next_requested = Signal()
    prev_requested = Signal()
    close_requested = Signal()

    PREFERRED_WIDTH = 420   # ширина панели, пока viewport не уже
    MIN_WIDTH = 280         # ниже — панель теряет читаемость

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapSearchBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_BAR_STYLE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self._line = _SearchLineEdit(self)
        self._line.setPlaceholderText(_t("search.map_placeholder"))
        self._line.textChanged.connect(self.query_changed.emit)
        self._line.next_pressed.connect(self.next_requested)
        self._line.prev_pressed.connect(self.prev_requested)
        self._line.close_pressed.connect(self.close_requested)

        # Счётчик: «k / N» при совпадениях, иначе текст «Нет совпадений».
        # _count_state — последнее состояние (current, total) для retranslate().
        self._count_state = None
        self._count = QLabel("", self)
        self._update_count_label()

        self._close_btn = QPushButton("×", self)
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_requested)

        layout.addWidget(self._line, 1)
        layout.addWidget(self._count)
        layout.addWidget(self._close_btn)
        self.hide()

    # ── Публичный API (MainWindow управляет состоянием) ────────────────

    @property
    def query(self) -> str:
        """Текущий текст запроса (без изменений)."""
        return self._line.text()

    def set_query(self, text: str):
        """Программно установить текст (эмитит query_changed при смене)."""
        if self._line.text() != text:
            self._line.setText(text)

    def set_count(self, current: int, total: int):
        """Счётчик «k / N» или «Нет совпадений» (i18n — актуальный на момент вызова)."""
        self._count_state = (int(current), int(total))
        self._update_count_label()

    def retranslate(self):
        """Повторно применить переводы (смена языка в MainWindow._switch_language)."""
        self._line.setPlaceholderText(_t("search.map_placeholder"))
        self._update_count_label()  # перерисовать счётчик на новом языке

    def focus_input(self):
        """Фокус на поле ввода + выделение всего текста (быстрая замена запроса)."""
        self._line.setFocus()
        self._line.selectAll()

    # ── Внутреннее ────────────────────────────────────────────────

    def _update_count_label(self):
        state = self._count_state
        if state is None:
            self._count.setText("")
            return
        current, total = state
        if total <= 0:
            self._count.setText(_t("search.no_results"))
            return
        try:
            self._count.setText(_t("search.count").format(cur=current, total=total))
        except Exception:  # noqa: BLE001 — форматирование упало — показываем числа как есть
            self._count.setText(f"{current} / {total}")
