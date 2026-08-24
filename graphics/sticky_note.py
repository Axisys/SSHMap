"""Sticky Notes — свободные текстовые заметки на карте (v0.7.2).

QGraphicsProxyWidget с QTextEdit внутри: заметка — это и графический объект
сцены (перетаскивается, масштабируется за угол), и настоящий виджет ввода
(двойной клик — режим редактирования, как у обычных стикеров).

Почему ручная обработка мыши вместо ItemIsMovable: QGraphicsProxyWidget
пересылает события дочернему QTextEdit, а тот их «съедает» (курсор/выделение),
поэтому scene-level drag в Qt не стартует. Двухрежимное поведение:

    обычное   — левый клик+драг перемещает заметку, за правый нижний угол —
                изменение размера; виджет без фокуса (не перехватывает ввод);
    edit mode — двойной клик включает StrongFocus у QTextEdit и передаёт
                события дальше (постановка каретки, выделение); focusOut
                возвращает заметку в обычный режим.

Delete на клавиатуре удаляет выбранную заметку только когда фокус НЕ внутри
редактора (в edit mode клавиши идут виджету — Delete стирает символы).
"""
import uuid
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QRectF, Signal, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGraphicsProxyWidget, QTextEdit, QGraphicsItem


def _t(key: str) -> str:
    """Безопасный i18n-хук: при недоступности i18n возвращает сам ключ."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


class StickyNote(QGraphicsProxyWidget):
    """Заметка на карте: перетаскивание, resize за угол, двойной клик — текст."""

    MIN_W, MIN_H = 140.0, 90.0
    MAX_W, MAX_H = 1200.0, 800.0
    CORNER_HIT = 16.0      # зона «за угол» для resize (px от правого нижнего)

    BG_COLOR = "#fef08a"   # классический жёлтый стикер — читается на тёмной карте
    BORDER_COLOR = "#ca8a04"
    TEXT_COLOR = "#1c1917"

    textEdited = Signal()  # текст изменён (MainWindow помечает проект dirty)
    moved = Signal()       # заметку переместили мышью (тоже dirty-причина)

    def __init__(self, text: str = "", x: float = 0.0, y: float = 0.0,
                 width: float = 240.0, height: float = 160.0, note_id: Optional[str] = None):
        editor = QTextEdit()
        super().__init__()
        self.setWidget(editor)

        self.note_id = note_id or str(uuid.uuid4())[:8]
        self._editing = False
        self._drag_mode = None  # None | "move" | "resize"
        self._drag_start_scene = None
        self._size_start: Tuple[float, float] = (width, height)
        self._moved_this_drag = False

        # ── Внешний вид редактора (стикер) ────────────────────────
        editor.setAcceptRichText(False)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        editor.setFont(QFont("Segoe UI", 10))
        editor.setStyleSheet(
            "QTextEdit { background: %s; color: %s;"
            " border: 2px solid %s; border-radius: 4px; padding: 6px; }"
            % (self.BG_COLOR, self.TEXT_COLOR, self.BORDER_COLOR)
        )
        editor.setPlaceholderText(_t("note.placeholder"))
        # Обычный режим: виджет НЕ берёт фокус — клики обрабатывает заметка
        # (перемещение/resize), а не QTextEdit. Double-click включает edit mode.
        editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._loading = True
        editor.setPlainText(text or "")
        self._loading = False

        editor.textChanged.connect(self._on_editor_text_changed)
        # Qt6: сигналов focusIn/focusOut у QWidget больше нет — ловим FocusOut
        # через eventFilter (выход из edit mode при потере фокуса)
        editor.installEventFilter(self)

        self.setPos(x, y)
        w, h = self._clamp_size(width, height)
        self.resize(w, h)
        # ItemIsSelectable — для Delete-удаления и подсветки; ItemIsMovable НЕ
        # ставим: перемещение делаем вручную (см. модульный docstring).
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

    # ── Geometry helpers ───────────────────────────────────────

    @classmethod
    def _clamp_size(cls, w: float, h: float):
        w = max(cls.MIN_W, min(cls.MAX_W, float(w)))
        h = max(cls.MIN_H, min(cls.MAX_H, float(h)))
        return w, h

    def set_note_size(self, width: float, height: float):
        """Изменить размер заметки (с ограничением MIN/MAX)."""
        w, h = self._clamp_size(width, height)
        if abs(w - self.rect().width()) < 0.5 and abs(h - self.rect().height()) < 0.5:
            return
        self.prepareGeometryChange()
        self.resize(w, h)

    def boundingRect(self) -> QRectF:
        """Явная геометрия (единообразно с ServerNode; см. его boundingRect)."""
        return QRectF(0, 0, self.rect().width(), self.rect().height())

    def text(self) -> str:
        return self.widget().toPlainText()

    def set_text(self, value: str):
        """Установить текст без сигнала textEdited (загрузка из файла)."""
        self._loading = True
        self.widget().setPlainText(value or "")
        self._loading = False

    # ── Dirty marking ──────────────────────────────────────────

    def _on_editor_text_changed(self):
        if not getattr(self, "_loading", False) and self.scene() is not None:
            self.textEdited.emit()

    # ── Edit mode (двойной клик / focusOut) ────────────────────

    def enter_edit_mode(self):
        """Включить режим редактирования текста."""
        if self._editing:
            return
        self._editing = True
        ed = self.widget()
        ed.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        ed.setFocus()

    def exit_edit_mode(self):
        if not self._editing:
            return
        self._editing = False
        ed = self.widget()
        ed.clearFocus()
        ed.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def editing(self) -> bool:
        return self._editing

    # ── Event filter (Qt6: нет сигнала focusOut — ловим событие виджета) ──

    def eventFilter(self, obj, event):
        if (self.widget() is not None and obj is self.widget()
                and event.type() == QEvent.Type.FocusOut):
            # Фокус ушёл из редактора — возвращаем заметку в обычный режим
            self.exit_edit_mode()
        return super().eventFilter(obj, event)

    # ── Mouse handling (ручное перемещение/resize, см. docstring) ──

    def _in_corner(self, pos) -> bool:
        r = self.rect()
        return (r.width() - self.CORNER_HIT <= pos.x() <= r.width()) and \
               (r.height() - self.CORNER_HIT <= pos.y() <= r.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Edit mode: события — редактору (каретка/выделение)
            if self._editing:
                super().mousePressEvent(event)
                return
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.rect().contains(local):
                super().mousePressEvent(event)  # клик мимо заметки — стандартный путь
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self.rect().width(), self.rect().height())
                self._drag_start_scene = scene_pos  # точка нажатия — отсчёт размера
            else:
                self._drag_mode = "move"
                self._drag_start_scene = scene_pos
            self._moved_this_drag = False
            event.accept()  # НЕ передаём в QTextEdit — иначе он перехватит драг
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_mode and (event.buttons() & Qt.MouseButton.LeftButton):
            scene_pos = event.scenePos()
            if scene_pos is None:
                return
            if self._drag_mode == "move":
                delta = scene_pos - self._drag_start_scene
                if abs(delta.x()) + abs(delta.y()) > 1.0:
                    self._moved_this_drag = True
                self.prepareGeometryChange()
                # Пошаговый сдвиг (старт обновляется) — без накопительной ошибки
                self.setPos(self.pos() + delta)
                self._drag_start_scene = scene_pos
            else:  # resize за правый нижний угол
                w0, h0 = self._size_start
                start_local = self.mapFromScene(self._drag_start_scene or scene_pos)
                cur_local = self.mapFromScene(scene_pos)
                if abs(cur_local.x() - start_local.x()) + abs(cur_local.y() - start_local.y()) > 1.0:
                    self.set_note_size(w0 + (cur_local.x() - start_local.x()),
                                       h0 + (cur_local.y() - start_local.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            mode = self._drag_mode
            self._drag_mode = None
            self._drag_start_scene = None
            if mode == "move" and self._moved_this_drag and self.scene() is not None:
                self.moved.emit()  # перемещение — несохранённое изменение
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Двойной клик — включить режим редактирования (каретка под курсором)."""
        if self._editing:
            # Уже редактируем — обычный двойной клик в тексте (выделение слова)
            super().mouseDoubleClickEvent(event)
            return
        local = self.mapFromScene(event.scenePos()) if event.scenePos() is not None else None
        if local is not None and self.rect().contains(local):
            self.enter_edit_mode()
            # Прокатываем дальше — каретка встанет под курсором
            super().mouseDoubleClickEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    # ── Hover: курсоры (drag / resize-угол) ────────────────────

    def hoverMoveEvent(self, event):
        if not self._editing and event.scenePos() is not None:
            local = self.mapFromScene(event.scenePos())
            if local is not None and self.rect().contains(local):
                if self._in_corner(local):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().hoverMoveEvent(event)

    def hoverEnterEvent(self, event):
        if not self._editing:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    # ── Serialization (v0.7.2: массив "notes" в JSON проекта) ───

    def to_dict(self) -> dict:
        return {
            "id": self.note_id,
            "text": self.text(),
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self.rect().width()),
            "height": float(self.rect().height()),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "StickyNote":
        """Создать заметку из записи JSON (лишние/битые ключи — дефолты)."""
        try:
            x = float(raw.get("x") or 0.0)
            y = float(raw.get("y") or 0.0)
            w = float(raw.get("width") or 240.0)
            h = float(raw.get("height") or 160.0)
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, 240.0, 160.0
        note_id = str(raw.get("id") or "")[:8] or None
        return cls(
            text=str(raw.get("text") or ""),
            x=x, y=y, width=w, height=h, note_id=note_id,
        )
