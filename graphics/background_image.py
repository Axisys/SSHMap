"""Фоновое изображение карты (v0.9.1): схема здания / план дата-центра ПОД всеми узлами.

BackgroundImage — QGraphicsPixmapItem с z = Z_VALUE (-10), ниже групп (-5),
стрелок (-2) и узлов (0). Позиция и размер — в координатах СЦЕНЫ; ручные жесты
в стиле StickyNote/NodeGroup (ItemIsMovable НЕ ставится — см. docstring
sticky_note.py про ScrollHandDrag):

    drag  — за любое место перемещает фон;
    resize — за правый нижний угол (CORNER_HIT px) меняет размер (пропорции
            НЕ сохраняются принудительно, но по умолчанию размер равен
            нативному размеру картинки, поэтому угол тянет «по картинке»).

В проекте (JSON "background") хранится ПУТЬ к изображению + геометрия:
{path, x, y, width, height}. Файл НЕ встраивается в JSON (проект остаётся
лёгким); при загрузке отсутствующий файл просто игнорируется с warning.

QGraphicsObject (не чистый QGraphicsPixmapItem-наследник без сигналов) —
нужны сигналы changed для dirty-маркера MainWindow, как у заметок/групп.
"""
import os

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


class BackgroundImage(QGraphicsObject):
    """Фоновое изображение под всеми элементами карты; drag + resize за угол."""

    Z_VALUE = -10.0          # ниже всего: группы -5, стрелки -2, узлы 0
    CORNER_HIT = 18.0        # зона «за угол» для resize (px, паттерн NodeGroup)
    MIN_SIZE = 64.0          # минимальная сторона при resize
    MAX_SIDE = 20000.0       # защита от абсурдных размеров
    BORDER_ALPHA = 90        # прозрачность тонкой рамки-подсказки

    # Сигналы для MainWindow (dirty-маркер проекта)
    moved = Signal()
    resized = Signal()

    def __init__(self, path: str, x: float = 0.0, y: float = 0.0,
                 width: float = None, height: float = None):
        super().__init__()
        self._path = str(path or "")
        self._pixmap = QPixmap(self._path)

        if self._pixmap.isNull():
            raise ValueError(f"Cannot load image: {self._path}")

        native_w = float(self._pixmap.width())
        native_h = float(self._pixmap.height())
        self._width = self._clamp_dim(width if width else native_w, native_w)
        self._height = self._clamp_dim(height if height else native_h, native_h)

        # Ручное перемещение/resize (паттерн StickyNote/NodeGroup)
        self._drag_mode = None
        self._drag_start_scene = None
        self._size_start = None

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(self.Z_VALUE)
        self.setPos(x, y)

    @staticmethod
    def _clamp_dim(value: float, fallback: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = float(fallback)
        return max(BackgroundImage.MIN_SIZE, min(BackgroundImage.MAX_SIDE, v))

    # ── Geometry ───────────────────────────────────────────────

    @property
    def path(self) -> str:
        return self._path

    def size(self):
        """Текущий размер (w, h) в координатах сцены."""
        return float(self._width), float(self._height)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._width, self._height)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self._width, self._height))
        return path

    def _in_corner(self, local: QPointF) -> bool:
        """Правый нижний угол — зона resize (паттерн NodeGroup/StickyNote)."""
        return (self._width - self.CORNER_HIT <= local.x() <= self._width and
                self._height - self.CORNER_HIT <= local.y() <= self._height)

    def set_bg_size(self, width: float, height: float):
        """Изменить размер фона (clamp MIN/MAX). Возвращает True, если изменился."""
        w = max(self.MIN_SIZE, min(self.MAX_SIDE, float(width)))
        h = max(self.MIN_SIZE, min(self.MAX_SIDE, float(height)))
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False
        self.prepareGeometryChange()
        self._width, self._height = w, h
        self.update()
        self.resized.emit()
        return True

    # ── Отрисовка ──────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap.isNull():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRectF(0, 0, self._width, self._height),
                           self._pixmap, QRectF(self._pixmap.rect()))

        # Тонкая полупрозрачная рамка — чтобы фон был различим на тёмной сетке
        color = QColor("#f59e0b") if self.isSelected() else QColor("#94a3b8")
        color.setAlpha(self.BORDER_ALPHA if not self.isSelected() else 180)
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0, 0, self._width, self._height))

    # ── Mouse (ручной drag/resize — паттерн NodeGroup) ──────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.boundingRect().contains(local):
                super().mousePressEvent(event)
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self._width, self._height)
            else:
                self._drag_mode = "move"
            self._drag_start_scene = scene_pos
            event.accept()  # НЕ передаём в сцену — ScrollHandDrag заберёт жест
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_mode and (event.buttons() & Qt.MouseButton.LeftButton):
            scene_pos = event.scenePos()
            if scene_pos is None:
                return
            if self._drag_mode == "move":
                delta = scene_pos - self._drag_start_scene
                if abs(delta.x()) + abs(delta.y()) > 0.5:
                    self.setPos(self.pos() + delta)
                    self.moved.emit()
                self._drag_start_scene = scene_pos
            else:  # resize за правый нижний угол
                w0, h0 = self._size_start or (self._width, self._height)
                start_local = self.mapFromScene(self._drag_start_scene or scene_pos)
                cur_local = self.mapFromScene(scene_pos)
                if abs(cur_local.x() - start_local.x()) + abs(cur_local.y() - start_local.y()) > 1.0:
                    self.set_bg_size(w0 + (cur_local.x() - start_local.x()),
                                     h0 + (cur_local.y() - start_local.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_mode = None
        self._drag_start_scene = None
        self._size_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Двойной клик ничего не делает (фон — пассивный слой), но жест не
        # проваливается в сцену, чтобы не начинать rubber-band.
        event.accept()

    # ── Hover: курсоры, паттерн NodeGroup ───────────────────────

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        if event.scenePos() is not None:
            local = self.mapFromScene(event.scenePos())
            if local is not None and self.boundingRect().contains(local):
                if self._in_corner(local):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    # ── Serialization (JSON "background") ───────────────────────

    def to_dict(self) -> dict:
        return {
            "path": self._path,
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self._width),
            "height": float(self._height),
        }

    @classmethod
    def try_from_dict(cls, raw: dict) -> "Optional[BackgroundImage]":
        """Создать фон из записи JSON или None (файла нет / битая запись).

        Отсутствующее изображение — НЕ ошибка загрузки проекта: предупреждение
        логируется вызывающей стороной, карта открывается без фона.
        """
        if not isinstance(raw, dict):
            return None
        path = str(raw.get("path") or "")
        if not path or not os.path.isfile(path):
            return None
        try:
            return cls(
                path=path,
                x=float(raw.get("x") or 0.0),
                y=float(raw.get("y") or 0.0),
                width=raw.get("width"),
                height=raw.get("height"),
            )
        except (TypeError, ValueError):
            return None


# Qt-импорты выше; хвост файла — сериализация/утилиты только.
