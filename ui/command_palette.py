# -*- coding: utf-8 -*-
"""v0.9.2: Палитра команд (Ctrl+K).

Быстрые действия без мыши: fuzzy-поиск по всем действиям приложения
(пункты меню) + по серверам проекта (выбор → центрирование карты на узле).

Дизайн:
- CommandPalette(QDialog, Qt.Popup-подобное окно без заголовка): строка ввода
  сверху + QListWidget результатов.
- Команды собираются из QAction главного окна (меню уже несёт i18n и слоты)
  плюс динамический блок серверов (пересобирается при каждом открытии).
- Фильтрация — простая subsequence fuzzy (без внешних зависимостей):
  "cns" матчит "Connect via SSH"; чем плотнее совпадение, тем выше ранг.
- Enter — выполнить первую/выделенную команду; Esc — закрыть.

i18n: ключи palette.* × en/ru/zh; названия действий берутся из уже
переведённых текстов QAction (дублирования переводов нет).
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QWidget, QHBoxLayout, QLabel,
)

try:
    # Пакетный запуск (из корня проекта).
    # v0.9.4-fix: i18n экспортирует t(), а не translate() — прежний импорт
    # молча падал и палитра показывала сырые ключи вместо переводов.
    from i18n import t as _translate
except Exception:  # pragma: no cover - плоский запуск
    try:
        from .i18n import t as _translate  # пакетный запуск как подпакета
    except Exception:
        _translate = None


def _t(key: str) -> str:
    if _translate is not None:
        try:
            return _translate(key)
        except Exception:
            pass
    return key


def fuzzy_score(pattern: str, text: str):
    """Subsequence-fuzzy: вернуть (score, matched) или None.

    score — чем меньше, тем лучше (плотные совпадения выгоднее).
    Регистр не важен; разделители слов дают бонус.
    """
    p, s = pattern.lower(), text.lower()
    if not p:
        return (1000, True)
    score = 0
    idx = 0
    last = -2
    for ch in p:
        found = s.find(ch, idx)
        if found < 0:
            return None
        gap_penalty = 0 if found == last + 1 else min(found - idx, 10)
        score += gap_penalty
        if found == 0 or s[found - 1] in " ._-\t":
            score -= 3  # бонус за начало слова
        last = found
        idx = found + 1
    return (score - (len(s) - len(p)) // 20, True)


class CommandPalette(QDialog):
    """Палитра команд: поиск по действиям и серверам (Ctrl+K)."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.mw = main_window
        self._commands = []      # [(label, kind, callable)]
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        # v0.9.3 fix: тексты обвязки (заголовок/плейсхолдер/hint) теперь
        # переустанавливаются при каждом открытии — см. retranslate_ui();
        # раньше они застывали на языке, активном в момент создания палитры.
        self.setWindowTitle(_t("palette.title"))
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(_t("palette.placeholder"))
        self.input.textChanged.connect(self._refilter)
        layout.addWidget(self.input)

        self.listw = QListWidget(self)
        self.listw.itemActivated.connect(self._run_current)
        layout.addWidget(self.listw)

        hint_row = QHBoxLayout()
        self._hint_label = QLabel(_t("palette.hint"), self)
        self._hint_label.setStyleSheet("color: gray;")
        hint_row.addWidget(self._hint_label)
        layout.addLayout(hint_row)

        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                row = self.listw.currentRow()
                self.listw.setCurrentRow(min(row + 1, self.listw.count() - 1))
                return True
            if key == Qt.Key_Up:
                row = self.listw.currentRow()
                self.listw.setCurrentRow(max(row - 1, 0))
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._run_current()
                return True
            if key == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    # ── Сбор команд ─────────────────────────────────────────────

    def _collect_commands(self):
        cmds = []

        # 1) Действия меню главного окна (уже переведены через i18n).
        seen = set()

        def walk(menu):
            for act in menu.actions():
                menu_child = act.menu()
                if menu_child is not None:
                    walk(menu_child)
                    continue
                text = act.text().replace("&", "").strip()
                if not text or text in ("-",):
                    continue
                slot = _qaction_slot(act)
                if slot is None:
                    continue
                ident = id(act)
                if ident in seen:
                    continue
                seen.add(ident)
                cmds.append((text, "action", lambda a=act: a.trigger()))

        bar = self.mw.menuBar()
        for top in bar.actions():
            child = top.menu()
            if child is not None:
                walk(child)

        # 2) Серверы проекта → «центрирование на узле».
        try:
            servers = self.mw.scene.nodes()
        except Exception:
            servers = []
        for node in servers:
            label = "{} — {} ({})".format(
                _t("palette.kind_server"),
                getattr(node.data, "alias", "") or "",
                getattr(node.data, "host", "") or "",
            )
            cmds.append((label, "server",
                         lambda n=node: self._reveal_node(n)))

        self._commands = cmds

    @staticmethod
    def _reveal_node(node):
        """Центрировать вид на узле + акцент выделения."""
        mw = node.scene().views()[0].window() if node.scene().views() else None
        scene = node.scene()
        scene.clearSelection()
        node.setSelected(True)
        if mw is not None and hasattr(mw, "view"):
            mw.view.centerOn(node)

    # ── Показ / фильтрация / запуск ─────────────────────────────

    def retranslate_ui(self):
        """v0.9.3 fix: перевести статичную обвязку заново (команды и так
        пересобираются из QAction при каждом открытии — см. open_palette)."""
        self.setWindowTitle(_t("palette.title"))
        self.input.setPlaceholderText(_t("palette.placeholder"))
        self._hint_label.setText(_t("palette.hint"))

    def open_palette(self):
        """Открыть палитру: собрать актуальные команды, сбросить фильтр."""
        self.retranslate_ui()
        self._collect_commands()
        self.input.clear()
        self._refilter("")
        # По центру родительского окна
        parent = self.parent() or self.mw
        geo = parent.geometry()
        self.resize(520, 420)
        self.move(geo.center() - QPoint(self.width() // 2, self.height() // 2))
        self.input.setFocus()
        return self.exec()

    def _refilter(self, text=""):
        text = self.input.text().strip()
        self.listw.clear()
        scored = []
        for label, kind, fn in self._commands:
            res = fuzzy_score(text, label)
            if res is None:
                continue
            scored.append((res[0], kind, label, fn))
        scored.sort(key=lambda x: (x[0], x[2].lower()))
        for _, kind, label, fn in scored[:50]:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, fn)
            # v0.9.3 fix: эмодзи «🖥/⚡» убраны — проект сознательно перешёл на
            # векторные иконки (ui/icons.py, Segoe UI Emoji рендерится плохо).
            try:
                from ui.icons import get_icon
                icon = get_icon("add_server" if kind == "server" else "connection")
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
            except Exception:  # noqa: BLE001 — иконка косметика, не роняем палитру
                pass
            self.listw.addItem(item)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _run_current(self):
        item = self.listw.currentItem()
        if item is None:
            self.accept()
            return
        fn = item.data(Qt.UserRole)
        self.accept()
        if callable(fn):
            fn()


def _qaction_slot(act):
    """Достать вызываемый слот QAction без приватных API PyQt.

    PyQt6 не отдаёт слот напрямую; вместо этого оборачиваем trigger(),
    а отключённые действия пропускаем по isEnabled при выполнении.
    """
    if not act.isCheckable() and act.menu() is None:
        return act
    return None
