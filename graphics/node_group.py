"""Группировка узлов (v0.8.1): кластер/папка на карте.

Группа — подписанная прямоугольная область ПОД узлами и стрелками (z = Z_VALUE,
ниже всех: «фон»-зона карты). Жесты — как у StickyNote (ручная обработка мыши,
ItemIsMovable НЕ ставится — см. docstring sticky_note.py про ScrollHandDrag):

    drag  — за любое место рамки перемещает группу; ВСЕ члены сдвигаются на тот же
            дельта-сдвиг (задача v0.8.1 #2: «серверы внутри группы автоматически
            перемещаются при изменении границы группы»);
    resize — за правый нижний угол (CORNER_HIT px): члены репозиционируются
            пропорционально новому размеру и клампятся внутрь рамки;
    double-click по верхней полосе (TITLE_ZONE_H) — сигнал renameRequested →
            диалог переименования в MainWindow.

Членство геометрическое: центр сервера внутри ВЕРХНЕЙ группы → он её член
(MapScene.resync_group_members() пересчитывает при любом движении/resize).
Поэтому в JSON (массив "groups") хранится только {id, name, x, y, width, height} —
членство не сериализуется и восстанавливается из геометрии при загрузке.

QGraphicsObject (а не QGraphicsItem) — по спецификации v0.8.1: нужны сигналы
(moved/resized/titleChanged/membershipChanged/renameRequested), которые поднимает
MainWindow на dirty-маркер проекта, как у заметок.
"""
import uuid
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QFontMetrics,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


class NodeGroup(QGraphicsObject):
    """Кластер/папка на карте: рамка + заголовок, drag/resize, членство серверов."""

    Z_VALUE = -5.0     # ниже узлов (z=0) и стрелок (z=-2) — «фон»-зона карты
    MIN_W, MIN_H = 160.0, 100.0
    MAX_W, MAX_H = 2400.0, 1600.0
    DEFAULT_W, DEFAULT_H = 480.0, 320.0

    CORNER_HIT = 18.0      # зона «за угол» для resize (px от правого нижнего, как у заметок)
    TITLE_ZONE_H = 28.0    # верхняя полоса: двойной клик — переименование
    MEMBER_MARGIN = 8.0    # мин. отступ членов от рамки при клампе на resize

    CORNER_RADIUS = 12.0   # скругление рамки (в едином стиле с карточкой узла)

    COLOR_BORDER = QColor("#7c3aed")       # violet-600 — отличается от синего узлов (#3b82f6)
    COLOR_HOVER = QColor("#a78bfa")        # violet-400
    COLOR_SELECTED = QColor("#f59e0b")     # тот же янтарь, что выделение узла (единая палитра)
    COLOR_FILL = QColor(124, 58, 237, 16)        # почти прозрачная заливка — сетка видна сквозь
    COLOR_FILL_HOVER = QColor(124, 58, 237, 28)
    COLOR_FILL_SELECTED = QColor(245, 158, 11, 20)
    COLOR_TITLE = QColor("#c4b5fd")          # violet-300 — читается на тёмной карте

    moved = Signal()               # группу переместили (dirty-причина для MainWindow)
    resized = Signal()             # размер изменён (drag за угол или set_group_size)
    titleChanged = Signal(str)     # заголовок переименован (новое имя — аргумент)
    membershipChanged = Signal()   # состав членов изменился (человек перетащил узел в/из группы)
    renameRequested = Signal()     # двойной клик по заголовку → MainWindow откроет диалог
    # v0.8.3-audit (#6): завершённые жесты — для undo-команд (паттерн node_drag_committed)
    moveCommitted = Signal(object, object)   # (QPointF старая поз., QPointF новая)
    resizeCommitted = Signal(float, float, float, float)  # (w0, h0, w1, h1)

    def __init__(self, x: float = 0.0, y: float = 0.0, width: Optional[float] = None,
                 height: Optional[float] = None, name: str = "",
                 group_id: Optional[str] = None):
        super().__init__()

        self.group_id = (str(group_id)[:8] if group_id else "") or None
        if self.group_id is None:
            self.group_id = str(uuid.uuid4())[:8]  # тот же паттерн, что у заметок/серверов

        self._name = str(name or "").strip()
        w, h = self._clamp_size(
            width if width else self.DEFAULT_W, height if height else self.DEFAULT_H)
        self._width, self._height = float(w), float(h)

        # Члены: ServerNode (НЕ дочерние QGraphicsItem — независимые объекты сцены;
        # их data.x/data.y остаются координатами СЦЕНЫ и корректно сохраняются в JSON).
        self._members = set()

        # Ручное перемещение/resize (паттерн StickyNote: ScrollHandDrag иначе забирает жест)
        self._drag_mode = None        # None | "move" | "resize"
        self._drag_start_scene = None
        self._size_start = None
        # v0.8.3-audit (#6): геометрия на начало жеста — для moveCommitted/resizeCommitted
        self._gesture_start_pos = None    # QPointF позиции группы
        self._hover = False
        self._applying_move = False   # наш собственный setPos в _apply_move — не дублировать shift в itemChange

        # ItemIsMovable НЕ ставим (см. модульный docstring); только выделение.
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(self.Z_VALUE)
        self.setPos(x, y)

        self._display_name = ""
        self._update_title_text()

    # ── Geometry helpers (паттерн StickyNote/ServerNode: явная геометрия) ──

    @classmethod
    def _clamp_size(cls, w: float, h: float):
        w = max(cls.MIN_W, min(cls.MAX_W, float(w)))
        h = max(cls.MIN_H, min(cls.MAX_H, float(h)))
        return w, h

    @property
    def name(self) -> str:
        """Имя группы (заголовок над рамкой)."""
        return self._name

    def set_title(self, text: str):
        """Переименовать группу. Пустое имя допускается (заголовок не рисуется)."""
        new = str(text or "").strip()
        if new == self._name:
            return
        self._name = new
        self._update_title_text()
        self.titleChanged.emit(new)

    def size(self):
        """Текущий размер (w, h) в координатах сцены."""
        return float(self._width), float(self._height)

    def boundingRect(self) -> QRectF:
        """Явная геометрия группы (единообразно с ServerNode/StickyNote)."""
        return QRectF(0, 0, self._width, self._height)

    def shape(self) -> QPainterPath:
        """Hit-область — вся рамка: клик в любом месте зоны попадает в группу."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._width, self._height),
                            self.CORNER_RADIUS, self.CORNER_RADIUS)
        return path

    def _in_corner(self, local: QPointF) -> bool:
        """Правый нижний угол — зона resize (как у заметок)."""
        return (self._width - self.CORNER_HIT <= local.x() <= self._width and
                self._height - self.CORNER_HIT <= local.y() <= self._height)

    def _in_title_zone(self, local: QPointF) -> bool:
        """Верхняя полоса — зона двойного клика для переименования."""
        return 0.0 <= local.x() <= self._width and 0.0 <= local.y() <= self.TITLE_ZONE_H

    def set_group_size(self, width: float, height: float) -> bool:
        """Изменить размер группы (clamp MIN/MAX).

        Задача v0.8.1 #2: члены автоматически перемещаются при изменении границы —
        их позиции масштабируются пропорционально новому размеру (sx/sy от левого
        верхнего угла), затем клампятся внутрь рамки с MEMBER_MARGIN, чтобы не
        «выпасть» из папки даже если группа стала меньше узла.

        Возвращает True, если размер реально изменился.
        """
        w, h = self._clamp_size(width, height)
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False

        old_w, old_h = self._width, self._height
        sx, sy = w / old_w, h / old_h
        gpos = self.pos()

        # Сначала СВОЯ геометрия: промежуточные resync-и (от setPos членов ниже) увидят
        # уже новую рамку — состав членства не «мигает» при расширении группы.
        m = self.MEMBER_MARGIN
        self.prepareGeometryChange()
        self._width, self._height = float(w), float(h)

        for node in list(self._members):
            r = node.sceneBoundingRect()  # узел — независимый item сцены: координаты сцены
            lx = (r.left() - gpos.x()) * sx
            ly = (r.top() - gpos.y()) * sy
            nw, nh = r.width(), r.height()
            max_lx = max(m, w - nw - m)   # узел шире группы → якорь в левом верхнем углу
            max_ly = max(m, h - nh - m)
            lx = min(max(lx, m), max_lx)
            ly = min(max(ly, m), max_ly)
            node.setPos(gpos.x() + lx, gpos.y() + ly)

        self._update_title_text()  # elide заголовка зависит от ширины

        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()  # другие узлы могли оказаться под рамкой / выйти из неё
        self.update()
        self.resized.emit()
        return True

    def _apply_move(self, delta: QPointF):
        """Сдвинуть группу И всех членов на delta (задача v0.8.1 #2 — drag-часть)."""
        if abs(delta.x()) < 0.5 and abs(delta.y()) < 0.5:
            return
        self.prepareGeometryChange()
        self._applying_move = True
        try:
            self.setPos(self.pos() + delta)
        finally:
            self._applying_move = False
        for node in list(self._members):
            # ServerNode.itemChange синхронизирует data.x/data.y и стрелки связей сам
            node.setPos(node.pos() + delta)
        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()  # под рамкой могли оказаться другие узлы
        self.moved.emit()

    def itemChange(self, change, value):
        """Внешний (программный) setPos — члены следуют за группой так же.

        Интерактивный drag идёт через _apply_move() с флагом _applying_move — там
        сдвиг членов уже сделан вручную; без флага itemChange ловит только
        программные перемещения (тесты/скрипты), и дублирования не происходит.

        Как и у ServerNode, хук вызывается ДО применения позиции: рамку для resync
        считаем от value явно (moving_group-override в MapScene).
        """
        if change == QGraphicsItem.ItemPositionChange and not getattr(self, "_applying_move", False):
            try:
                dx = float(value.x()) - float(self.pos().x())
                dy = float(value.y()) - float(self.pos().y())
            except Exception:  # noqa: BLE001 — неожиданный тип value — отдаём стандартному пути
                return super().itemChange(change, value)
            if abs(dx) + abs(dy) > 0.5:
                result = super().itemChange(change, value)  # принять → Qt применит позицию
                for node in list(self._members):
                    node.setPos(node.pos() + QPointF(dx, dy))
                sc = self.scene()
                if sc is not None and hasattr(sc, "resync_group_members"):
                    target_rect = QRectF(float(value.x()), float(value.y()),
                                         self._width, self._height)
                    sc.resync_group_members(moving_group=(self, target_rect))
                return result
        return super().itemChange(change, value)

    # ── Членство (ServerNode-объекты; эксклюзивность — один узел в одной группе) ──

    def get_members(self) -> List:
        """Список членов (порядок не гарантирован)."""
        return list(self._members)

    def member_count(self) -> int:
        return len(self._members)

    def has_member(self, node) -> bool:
        return node in self._members

    def add_member(self, node):
        """Добавить члена. Эксклюзивность: узел не может быть в двух группах —
        при необходимости снимаем его с прежней (верхняя группа побеждает)."""
        if node is None or node in self._members:
            return
        sc = self.scene()
        if sc is not None and hasattr(sc, "_groups"):
            for other in list(sc._groups):
                if other is not self and node in other._members:
                    other.remove_member(node)  # снимает membershipChanged прежней группы
        self._members.add(node)
        self.membershipChanged.emit()

    def remove_member(self, node):
        """Убрать члена (no-op, если его не было)."""
        if node in self._members:
            self._members.discard(node)
            self.membershipChanged.emit()

    def clear_members(self):
        """Очистить состав одним сигналом (удаление группы / пересборка сцены)."""
        if self._members:
            self._members.clear()
            self.membershipChanged.emit()

    # ── Заголовок ──────────────────────────────────────────────

    def _title_font(self) -> QFont:
        return QFont("Segoe UI", 9, QFont.Bold)

    def _update_title_text(self):
        """Elide длинного имени под ширину рамки (полное имя — в tooltip; паттерн ServerNode)."""
        fm = QFontMetrics(self._title_font())
        max_w = max(int(self._width - 28), 1)
        if self._name and fm.horizontalAdvance(self._name) > max_w:
            self._display_name = fm.elidedText(self._name, Qt.TextElideMode.ElideRight, max_w)
            self.setToolTip(self._name)
        else:
            self._display_name = self._name
            self.setToolTip("")

    # ── Отрисовка (вся графика в paint() — без дочерних items:
    #      единый hit-объект, стандартный drag работает по всей площади рамки) ──

    def _state_colors(self):
        """(pen_color, pen_width, fill, title_color) для текущего состояния."""
        if self.isSelected():
            return (self.COLOR_SELECTED, 2.5, self.COLOR_FILL_SELECTED, QColor("#fde68a"))
        if self._hover:
            color = QColor(self.COLOR_HOVER)
            color.setAlpha(170)
            return (color, 2.0, self.COLOR_FILL_HOVER, QColor("#e9d5ff"))
        return (self.COLOR_BORDER, 1.5, self.COLOR_FILL, self.COLOR_TITLE)

    def paint(self, painter: QPainter, option, widget=None):
        w, h = self._width, self._height
        if w <= 2 or h <= 2:
            return
        pen_color, pen_width, fill, title_color = self._state_colors()

        path = QPainterPath()
        # Инсет 1 px — рамка целиком внутри boundingRect (Qt клипует по нему)
        path.addRoundedRect(1.0, 1.0, w - 2.0, h - 2.0, self.CORNER_RADIUS, self.CORNER_RADIUS)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(pen_color, pen_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawPath(path)

        # Заголовок в верхней полосе (elide см. _update_title_text)
        if self._display_name:
            painter.setFont(self._title_font())
            painter.setPen(QPen(title_color))
            painter.drawText(
                QRectF(14.0, 3.0, max(w - 28.0, 1.0), self.TITLE_ZONE_H - 6.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._display_name)

        # Маркер resize-угла — виден при hover/выделении (подсказка «за этот угол тянуть»)
        if self._hover or self.isSelected():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(pen_color))
            painter.drawRoundedRect(QRectF(w - 16.0, h - 16.0, 10.0, 10.0), 3.0, 3.0)

    # ── Mouse (ручное перемещение/resize — паттерн StickyNote) ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.boundingRect().contains(local):
                super().mousePressEvent(event)  # клик мимо группы — стандартный путь
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self._width, self._height)
                self._drag_start_scene = scene_pos
            else:
                self._drag_mode = "move"
                self._drag_start_scene = scene_pos
            # v0.8.3-audit (#6): запомнить геометрию начала жеста (для undo)
            self._gesture_start_pos = QPointF(self.pos())
            event.accept()  # НЕ передаём в сцену — иначе ScrollHandDrag заберёт жест
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
                    self._apply_move(delta)
                # Пошаговый сдвиг (старт обновляется) — без накопительной ошибки (StickyNote)
                self._drag_start_scene = scene_pos
            else:  # resize за правый нижний угол
                w0, h0 = self._size_start or (self._width, self._height)
                start_local = self.mapFromScene(self._drag_start_scene or scene_pos)
                cur_local = self.mapFromScene(scene_pos)
                if abs(cur_local.x() - start_local.x()) + abs(cur_local.y() - start_local.y()) > 1.0:
                    self.set_group_size(w0 + (cur_local.x() - start_local.x()),
                                        h0 + (cur_local.y() - start_local.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            mode = self._drag_mode
            start_pos = self._gesture_start_pos
            start_size = self._size_start
            self._drag_mode = None
            self._drag_start_scene = None
            self._size_start = None
            self._gesture_start_pos = None
            # v0.8.3-audit (#6): жест завершён → сигнал для undo-команды окна.
            # Эмиссия только при реальном изменении геометрии (иначе пустой шаг стека).
            try:
                if mode == "move" and start_pos is not None:
                    end_pos = QPointF(self.pos())
                    if ((end_pos - start_pos).manhattanLength() > 0.5):
                        self.moveCommitted.emit(QPointF(start_pos), end_pos)
                elif mode == "resize" and start_size is not None:
                    cur = (self._width, self._height)
                    if abs(cur[0] - start_size[0]) + abs(cur[1] - start_size[1]) > 0.5:
                        self.resizeCommitted.emit(start_size[0], start_size[1], cur[0], cur[1])
            except Exception:  # noqa: BLE001 — undo-сигнал не роняет release
                pass
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Двойной клик по заголовку — запрос переименования (MainWindow покажет диалог)."""
        scene_pos = event.scenePos()
        local = self.mapFromScene(scene_pos) if scene_pos is not None else None
        if local is not None and self._in_title_zone(local):
            self.renameRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ── Hover: курсоры (drag / resize-угол), как у заметок ──────

    def hoverEnterEvent(self, event):
        self._hover = True
        if not self.isSelected():
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
        self._hover = False
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)

    # ── Serialization (v0.8.1: массив "groups" в JSON проекта) ───
    # Членство НЕ хранится — геометрический инвариант пересчитывает его при загрузке.

    def to_dict(self) -> dict:
        return {
            "id": self.group_id,
            "name": self._name,
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self._width),
            "height": float(self._height),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "NodeGroup":
        """Создать группу из записи JSON (битые значения — дефолты; паттерн StickyNote)."""
        try:
            x = float(raw.get("x") or 0.0)
            y = float(raw.get("y") or 0.0)
            w = float(raw.get("width") or cls.DEFAULT_W)
            h = float(raw.get("height") or cls.DEFAULT_H)
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, cls.DEFAULT_W, cls.DEFAULT_H
        group_id = str(raw.get("id") or "")[:8] or None
        return cls(
            name=str(raw.get("name") or ""),
            x=x, y=y, width=w, height=h, group_id=group_id,
        )
