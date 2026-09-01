from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QPointF

try:
    from .server_node import ServerNode
except ImportError:
    from server_node import ServerNode

try:
    from .connection_arrow import (
        build_curve, edge_point, type_color, DEFAULT_CONNECTION_TYPE, ConnectionArrow,
    )
except ImportError:
    from connection_arrow import (
        build_curve, edge_point, type_color, DEFAULT_CONNECTION_TYPE, ConnectionArrow,
    )

try:
    from .sticky_note import StickyNote  # v0.7.2
except ImportError:
    try:
        from sticky_note import StickyNote
    except ImportError:
        StickyNote = None

try:
    from .node_group import NodeGroup  # v0.8.1: группы узлов (кластеры/папки)
except ImportError:
    try:
        from node_group import NodeGroup
    except ImportError:
        NodeGroup = None


if TYPE_CHECKING:
    from ..graphics.map_scene import MapScene


from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QWheelEvent, QKeyEvent, QMouseEvent, QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsView, QGraphicsPathItem, QMenu


def _t(key: str) -> str:
    """Безопасный i18n-хук (единообразно с server_node/connection_arrow)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


class MapView(QGraphicsView):
    """Вид карты: зум, панорамирование и (v0.7) создание связей перетаскиванием."""

    connect_drag_started = Signal()   # началось Shift-перетаскивание связи от узла
    connect_drag_finished = Signal()  # завершено (создана связь или отменено)
    zoomChanged = Signal(float)       # UI polish: текущий зум — для % в статус-баре
    # v0.8.3: завершён жест перетаскивания узла (node, old_scene_pos, new_scene_pos)
    node_drag_committed = Signal(object, object, object)
    # v0.9.3: завершён жест ГРУППОВОГО перетаскивания — список
    # [(node, old_pos: QPointF, new_pos: QPointF)] для одной undo-команды
    nodes_drag_committed = Signal(list)
    # v0.9.9.1: изменился размер вида (плавающие панели поверх viewport —
    # строка поиска — переставляются при ресайзе окна / драге сплиттера)
    resized = Signal()

    def __init__(self, scene: "MapScene", parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor("#020617")))
        self._zoom = 1.0

        # ── Drag-режим создания связи (v0.7) ─────────────
        self._connect_source: Optional[ServerNode] = None
        self._rubber_band: Optional[QGraphicsPathItem] = None

        # v0.8.3: активный жест перемещения узла (для undo-команды CmdMoveNode)
        self._move_drag_node: Optional[ServerNode] = None
        self._move_drag_old = None  # QPointF — позиция до начала жеста

        # ── v0.9.3: мультивыделение + групповой drag ──────────────
        # Рамка выделения (Ctrl+ЛКМ по пустому месту): QGraphicsRectItem в сцене.
        self._rubber_select_item = None          # QGraphicsRectItem рамки
        self._rubber_select_origin = None        # QPointF стартовой точки сцены
        self._rubber_saved_selection = []        # выделение на старте Ctrl+драга
        # Групповой drag: позиции всех выделенных узлов до жеста
        self._group_drag_olds = []               # [(node, QPointF), ...]

    # UI polish: допустимый диапазон зума (общий для колеса, fit и восстановления).
    ZOOM_MIN = 0.1
    ZOOM_MAX = 5.0

    @property
    def zoom(self) -> float:
        """Текущий коэффициент зума (публичный доступ; AUDIT v0.7.2, низкая #19)."""
        return self._zoom

    def _notify_zoom(self):
        """UI polish: сообщить о текущем зуме (статус-бар показывает %)."""
        try:
            self.zoomChanged.emit(float(self._zoom))
        except RuntimeError:
            pass  # Qt teardown — слоты уже уничтожены (паттерн из _sync_selection_state)

    def reset_zoom(self):
        """Сбросить зум к 100% и очистить трансформацию (AUDIT v0.7.2, низкая #19)."""
        self.resetTransform()
        self._zoom = 1.0
        self._notify_zoom()

    def resizeEvent(self, event):
        """v0.9.9.1: уведомить о смене размера — плавающие панели поверх viewport
        (строка поиска) переставляются при ресайзе окна и драге сплиттера."""
        super().resizeEvent(event)
        self.resized.emit()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        zoom_factor = 1.15 if delta > 0 else 0.87
        new_zoom = self._zoom * zoom_factor
        if self.ZOOM_MIN < new_zoom < self.ZOOM_MAX:
            self._zoom = new_zoom
            self.scale(zoom_factor, zoom_factor)
            self._notify_zoom()

    # ── UI polish: «вписать карту» и восстановление сохранённого вида ──

    def content_bounding_rect(self):
        """Общий boundingRect узлов и заметок (None, если карта пуста)."""
        scene = self.scene()
        if scene is None:
            return None
        items = scene.nodes() if hasattr(scene, "nodes") else []
        items += [n for n in getattr(scene, "_notes", [])]
        rect = None
        for item in items:
            r = item.sceneBoundingRect()
            if r.isEmpty():
                continue
            rect = QRectF(r) if rect is None else rect.united(QRectF(r))
        return rect

    def fit_to_content(self, margin: float = 80.0) -> bool:
        """Вписать содержимое карты в область вида (KeepAspectRatio).

        Возвращает False, если контента нет. Зум приводится в диапазон
        [ZOOM_MIN, ZOOM_MAX], как у колеса; _zoom синхронизируется с трансформацией.
        """
        rect = self.content_bounding_rect()
        if rect is None or rect.isEmpty():
            return False
        self.fitInView(rect.adjusted(-margin, -margin, margin, margin),
                       Qt.AspectRatioMode.KeepAspectRatio)
        # fitInView меняет трансформацию мимо _zoom — пересчитываем и клэмпаем
        target = float(self.transform().m11())
        if target < self.ZOOM_MIN or target > self.ZOOM_MAX:
            clamped = max(self.ZOOM_MIN, min(self.ZOOM_MAX, target))
            center = rect.center()
            self.resetTransform()
            self.translate(center.x(), center.y())
            self.scale(clamped, clamped)
            self.translate(-center.x(), -center.y())
            target = clamped
        self._zoom = target
        self._notify_zoom()
        return True

    def set_zoom_and_center(self, zoom: float, center_x: float, center_y: float):
        """Применить сохранённый в проекте зум и центр (UI polish: раньше игнорировались)."""
        try:
            z = float(zoom)
            cx = float(center_x)
            cy = float(center_y)
        except (TypeError, ValueError):
            return  # битые значения из чужого файла — оставляем текущий вид
        if not (self.ZOOM_MIN <= z <= self.ZOOM_MAX):
            z = max(self.ZOOM_MIN, min(self.ZOOM_MAX, z))
        self.resetTransform()
        self.scale(z, z)
        self._zoom = z
        self.centerOn(cx, cy)
        self._notify_zoom()

    # ── v0.7.2: динамический drag-режим (перетаскивание нод/заметок) ──
    # При ScrollHandDrag левый драг ВСЕГДА панорамирует canvas — Items с
    # ItemIsMovable мышью не двигаются (проверено эмпирически). Поэтому на
    # нажатии над перемещаемым объектом временно переключаемся в NoDrag, а
    # после отпускания возвращаем ScrollHandDrag.

    def _item_at_scene(self, scene_pos):
        if self.scene() is None:
            return None
        return self.scene().itemAt(scene_pos, self.transform())

    @staticmethod
    def _is_movable_item(item) -> bool:
        """Является ли item (или его родительская группа) перемещаемым объектом."""
        while item is not None:
            if isinstance(item, ServerNode):
                return True  # ItemIsMovable — штатный Qt-drag в режиме NoDrag
            if StickyNote is not None and isinstance(item, StickyNote):
                return True  # ручное перемещение в mousePressEvent самой заметки
            if NodeGroup is not None and isinstance(item, NodeGroup):  # v0.8.1: группы
                return True  # ручное перемещение в mousePressEvent самой группы (паттерн заметок)
            item = item.parentItem()
        return False

    def _find_node_at(self, scene_pos) -> Optional[ServerNode]:
        """ServerNode под точкой сцены (с учётом дочерних элементов группы)."""
        if self.scene() is None:
            return None
        item = self.scene().itemAt(scene_pos, self.transform())
        while item is not None:
            if isinstance(item, ServerNode):
                return item
            item = item.parentItem()
        return None

    def _classify_at(self, scene_pos):
        """Вернуть (node, arrow, note) — верхний объект каждого вида под точкой."""
        node = arrow = note = None
        if self.scene() is None:
            return node, arrow, note
        for item in self.scene().items(scene_pos):
            # стрелка — напрямую (у неё нет групп-родителей)
            if arrow is None and isinstance(item, ConnectionArrow):
                arrow = item
            n = item
            while n is not None:
                if node is None and isinstance(n, ServerNode):
                    node = n
                    break
                if note is None and StickyNote is not None and isinstance(n, StickyNote):
                    note = n
                    break
                n = n.parentItem()
        return node, arrow, note

    def _cancel_connect_drag(self):
        """Убрать резиновую нить и сбросить состояние drag-режима."""
        if self._rubber_band is not None and self._rubber_band.scene() is not None:
            self._rubber_band.scene().removeItem(self._rubber_band)
        self._rubber_band = None
        self._connect_source = None
        self.unsetCursor()

    def mousePressEvent(self, event: QMouseEvent):
        # Shift+ЛКМ по узлу → создаём связь перетаскиванием (v0.7).
        # Не передаём событие дальше: узел не двигается и панорама не стартует.
        if (event.button() == Qt.LeftButton
                and bool(event.modifiers() & Qt.ShiftModifier)
                and self._connect_source is None):
            # PySide6/Qt6 mapToScene не биндит QPointF-версию — используем QPoint
            scene_pos = self.mapToScene(event.position().toPoint())
            node = self._find_node_at(scene_pos)
            if node is not None:
                self._connect_source = node
                pen = QPen(type_color(DEFAULT_CONNECTION_TYPE), 2, Qt.DashLine)
                self._rubber_band = QGraphicsPathItem()
                self._rubber_band.setPen(pen)
                self._rubber_band.setZValue(100)
                if self.scene() is not None:
                    self.scene().addItem(self._rubber_band)
                self.setCursor(Qt.CrossCursor)
                self.connect_drag_started.emit()
                return
        # v0.7.2: нажатие над перемещаемым объектом (узел/заметка) — временно NoDrag,
        # иначе ScrollHandDrag забрал бы жест под панорамирование и ничего не двигалось.
        if event.button() == Qt.LeftButton and self._connect_source is None:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._is_movable_item(self._item_at_scene(scene_pos)):
                self.setDragMode(QGraphicsView.NoDrag)
            # v0.8.3: старт жеста перемещения узла — запоминаем исходную позицию
            node = self._find_node_at(scene_pos)
            if node is not None:
                self._move_drag_node = node
                from PySide6.QtCore import QPointF
                self._move_drag_old = QPointF(node.pos())
                # v0.9.3: если узел уже входит в мультивыделение — это ГРУППОВОЙ
                # drag (двигаются все выделенные). Позиции до жеста — для undo.
                if node.isSelected() and len([i for i in self.scene().selectedItems()
                                              if isinstance(i, ServerNode)]) > 1:
                    self._group_drag_olds = [
                        (n, QPointF(n.pos()))
                        for n in self.scene().selectedItems()
                        if isinstance(n, ServerNode)
                    ]
                else:
                    self._group_drag_olds = []
            # v0.9.3: Ctrl+ЛКМ по пустому месту → рамка выделения (rubber band).
            elif bool(event.modifiers() & Qt.ControlModifier):
                from PySide6.QtWidgets import QGraphicsRectItem
                self._start_rubber_select(scene_pos,
                                          event.modifiers() & Qt.ShiftModifier)
                return  # панораму не стартуем
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._connect_source is not None and self._rubber_band is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            src_rect = self._connect_source.sceneBoundingRect()
            p0 = edge_point(src_rect, src_rect.center(), scene_pos)
            path, _, _ = build_curve(p0, scene_pos)
            self._rubber_band.setPath(path)
        # v0.9.3: обновление рамки выделения
        elif self._rubber_select_item is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            self._update_rubber_select(scene_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        # v0.9.3: рамка выделения завершена — фиксируем выделение
        if self._rubber_select_item is not None and event.button() == Qt.LeftButton:
            self._finish_rubber_select()
            return  # нажатие не передавалось в Qt — отпускание тоже забираем
        if (self._connect_source is not None and event.button() == Qt.LeftButton):
            source = self._connect_source
            scene_pos = self.mapToScene(event.position().toPoint())
            target = self._find_node_at(scene_pos)
            self._cancel_connect_drag()
            self.connect_drag_finished.emit()
            if target is not None and target is not source:
                # MainWindow создаёт связь через предзаполненный диалог (тип + метка).
                win = self.window()
                if hasattr(win, "_add_connection"):
                    win._add_connection(
                        default_source_id=source.data.id,
                        default_target_id=target.data.id,
                    )
            return  # нажатие не передавалось в Qt — и отпускание забираем сами
        # v0.7.2: жест над перемещаемым объектом завершён — возвращаем панорамирование
        if self.dragMode() == QGraphicsView.NoDrag:
            # v0.8.3: узел реально сдвинулся — сообщаем окну (команда CmdMoveNode)
            node = getattr(self, "_move_drag_node", None)
            if node is not None:
                old = getattr(self, "_move_drag_old", None)
                self._move_drag_node = None
                self._move_drag_old = None
                try:
                    new = node.pos()
                    if old is not None and (abs(new.x() - old.x()) > 0.5
                                            or abs(new.y() - old.y()) > 0.5):
                        # v0.9.3: групповой drag → ОДНА команда на все выделенные;
                        # одиночный drag → прежний сигнал с одним узлом.
                        olds = getattr(self, "_group_drag_olds", [])
                        self._group_drag_olds = []
                        moved = [(n, o, QPointF(n.pos())) for n, o in olds
                                 if n.scene() is not None]
                        if len(moved) > 1 and any(
                                abs(n.pos().x() - o.x()) > 0.5 or abs(n.pos().y() - o.y()) > 0.5
                                for n, o, _ in moved):
                            self.nodes_drag_committed.emit(moved)
                        elif abs(new.x() - old.x()) > 0.5 or abs(new.y() - old.y()) > 0.5:
                            self.node_drag_committed.emit(node, old, QPointF(new))
                except RuntimeError:
                    pass  # Qt teardown — жест не завершён штатно, команды не будет
            else:
                self._group_drag_olds = []
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._rubber_select_item is not None:
            # Esc во время рамки выделения — отмена без изменения выделения
            self._finish_rubber_select()
            return
        if self._connect_source is not None:
            # Любая клавиша во время drag-режима (в т.ч. Esc/Delete) — отмена drag'а;
            # удаление узлов здесь намеренно НЕ выполняем.
            self._cancel_connect_drag()
            self.connect_drag_finished.emit()
            return
        if event.key() == Qt.Key_Delete:
            # Удалить выделенный узел (патч v0.6.x / v0.7.3: единый guarded-путь —
            # подтверждение + ожидание завершения SSHWorker до remove_server)
            scene = self.scene()
            node = None
            note = None
            group = None  # v0.8.1: выделенная группа (кластер/папка)
            for item in scene.selectedItems() if scene else []:
                if isinstance(item, ServerNode):
                    node = item
                elif StickyNote is not None and isinstance(item, StickyNote):
                    note = item  # может быть несколько — берём первый
                elif NodeGroup is not None and isinstance(item, NodeGroup):
                    group = item  # v0.8.1: берём первую выделенную группу
            if node:
                win = self.window()
                if hasattr(win, "_remove_node_guarded"):
                    win._remove_node_guarded(node)
                else:  # фолбэк для сцен без MainWindow (тесты/внешние хостеры)
                    scene.remove_server(node.data.id)
                    parent_widget = self.parent()
                    if hasattr(parent_widget, 'refresh_sidebar'):
                        parent_widget.refresh_sidebar()
            elif note is not None:
                # v0.7.2: выделенная заметка — лёгкий объект, удаляется без
                # подтверждения. (Если фокус внутри её QTextEdit, клавиши до
                # view не доходят — Delete стирает символы, заметку не трогает.)
                win = self.window()
                if hasattr(win, "_remove_note"):
                    win._remove_note(note)
                elif scene is not None:
                    scene.remove_note(note.note_id)
            elif group is not None and NodeGroup is not None:
                # v0.8.1: выделенная группа — лёгкий объект (серверы остаются на карте),
                # удаляется без подтверждения, как заметка.
                win = self.window()
                if hasattr(win, "_remove_group"):
                    win._remove_group(group)
                elif scene is not None and hasattr(scene, "remove_group"):
                    scene.remove_group(group)
        super().keyPressEvent(event)

    # ── v0.7.2/v0.7.3: контекстное меню на карте (ПКМ) ─────────────

    @staticmethod
    def _event_point(event):
        """QPoint позиции события в версии-agnostic форме.

        Qt6/PySide6: у событий есть position() (QPointF) и legacy pos(); в разных
        версиях биндингов доступен то один, то другой вариант — пробуем оба.
        """
        position = getattr(event, "position", None)
        if callable(position):
            try:
                return position().toPoint()
            except Exception:
                pass  # legacy-биндинг без position() — ниже event.pos()
        return event.pos()

    @classmethod
    def _event_global_point(cls, event):
        """QPoint глобальной позиции события (для QMenu.exec)."""
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            try:
                return global_position().toPoint()
            except Exception:
                pass  # legacy-биндинг без globalPosition() — ниже event.globalPos()
        return event.globalPos()

    # ── v0.9.3: рамка выделения (Ctrl+ЛКМ по пустому месту) ─────────

    def _start_rubber_select(self, scene_pos, additive: bool = False):
        """Начать рисование рамки выделения. Shift добавляет к текущему
        выделению, без Shift — заменяет его."""
        from PySide6.QtWidgets import QGraphicsRectItem
        self._rubber_select_origin = scene_pos
        self._rubber_saved_selection = list(self.scene().selectedItems()) \
            if additive else []
        pen = QPen(QColor("#38bdf8"), 0)  # cosmetic pen — толщина не зависит от зума
        self._rubber_select_item = QGraphicsRectItem()
        self._rubber_select_item.setPen(pen)
        self._rubber_select_item.setBrush(QBrush(QColor(56, 189, 248, 30)))
        self._rubber_select_item.setZValue(200)
        self.scene().addItem(self._rubber_select_item)
        self.setCursor(Qt.CrossCursor)

    def _update_rubber_select(self, scene_pos):
        """Обновить геометрию рамки + live-выделение пересекаемых узлов."""
        origin = self._rubber_select_origin
        rect = QRectF(origin, scene_pos).normalized()
        self._rubber_select_item.setRect(rect)
        # live: подсвечиваем узлы под рамкой прямо во время драга
        base_ids = {id(n) for n in getattr(self, "_rubber_saved_selection", [])}
        for item in self.scene().items():
            if isinstance(item, ServerNode):
                hit = rect.intersects(item.sceneBoundingRect())
                want = hit or (id(item) in base_ids)
                if item.isSelected() != want:
                    item.setSelected(want)

    def _finish_rubber_select(self):
        """Убрать рамку; итоговое выделение уже установлено в _update_rubber_select."""
        if self._rubber_select_item is not None:
            sc = self._rubber_select_item.scene()
            if sc is not None:
                sc.removeItem(self._rubber_select_item)
            self._rubber_select_item = None
        self._rubber_select_origin = None
        self._rubber_saved_selection = []
        self.unsetCursor()

    def contextMenuEvent(self, event):
        """ПКМ: пустое место — добавить заметку/сервер; объект — действия над ним."""
        scene = self.scene()
        if scene is None:
            super().contextMenuEvent(event)
            return
        scene_pos = self.mapToScene(self._event_point(event))

        win = self.window()
        node, arrow, note = self._classify_at(scene_pos)
        menu = QMenu(self)

        if note is not None and StickyNote is not None:
            # Заметка (v0.7.2): редактирование — двойным кликом, здесь только удаление
            act_del = menu.addAction(_t("ctx.delete_note"))
            # v0.8.1: QAction.triggered передаёт bool `checked` первым аргументом —
            # без явного параметра он бы затёр замыкание n (crash в _remove_note).
            def _del_note(checked=False, n=note):
                w = self.window()
                if hasattr(w, "_remove_note"):
                    w._remove_note(n)
                elif scene is not None:
                    scene.remove_note(n.note_id)
            act_del.triggered.connect(_del_note)

        # ── v0.7.3: контекстное меню узла ──────────────────────────
        if node is not None:
            win_node = node  # локальная ссылка для замыканий
            # v1.0RC4: Быстрый запуск — ПЕРВЫЙ пункт (выше «Подключиться по SSH»).
            # Подменю: пункты node.data.quick_launch + разделитель + «Настроить…».
            # Без пунктов — только «Настроить…» (discoverability). Паттерн hasattr —
            # как у остальных действий: MapView не знает о MainWindow.
            if hasattr(win, "_run_quick_launch_entry") or \
                    hasattr(win, "_open_quick_launch_dialog"):
                ql_entries = list(getattr(win_node.data, "quick_launch", None) or [])
                ql_sub = menu.addMenu(_t("ctx.quick_launch"))
                for e in ql_entries:
                    if not hasattr(win, "_run_quick_launch_entry"):
                        break
                    act_ql = ql_sub.addAction(str(e.get("name") or e.get("value") or "?"))
                    def _ql(checked=False, n=win_node, en=e):  # checked — bool из triggered
                        w = self.window()
                        if hasattr(w, "_run_quick_launch_entry"):
                            w._run_quick_launch_entry(n, en)
                    act_ql.triggered.connect(_ql)
                if ql_entries:
                    ql_sub.addSeparator()
                if hasattr(win, "_open_quick_launch_dialog"):
                    act_qc = ql_sub.addAction(_t("ql.configure"))
                    def _ql_cfg(checked=False, n=win_node):  # checked — bool из triggered
                        w = self.window()
                        if hasattr(w, "_open_quick_launch_dialog"):
                            w._open_quick_launch_dialog(n)
                    act_qc.triggered.connect(_ql_cfg)
                menu.addSeparator()  # Быстрый запуск отделён от «боевого» меню узла
            if hasattr(win, "_connect_ssh_to_selected"):
                act_ssh = menu.addAction(_t("ctx.ssh_connect"))
                # v0.8.1: первый параметр — bool `checked` из QAction.triggered; без него
                # PySide вызывает _ssh(True) и затёрло бы замыкание win_node (crash в
                # MainWindow._select_node: 'bool' object has no attribute 'setSelected').
                def _ssh(checked=False, n=win_node):
                    w = self.window()
                    w._select_node(n)          # SSH-диалог берёт выделенный узел
                    w._connect_ssh_to_selected()
                act_ssh.triggered.connect(_ssh)
            # v0.8.2: подключение в системном терминале ОС
            if hasattr(win, "_connect_ssh_external"):
                act_ext = menu.addAction(_t("ctx.ssh_external"))
                def _ssh_ext(checked=False, n=win_node):  # checked — bool из triggered
                    w = self.window()
                    w._select_node(n)
                    w._connect_ssh_external(n)
                act_ext.triggered.connect(_ssh_ext)
            if hasattr(win, "_edit_node"):
                act_edit = menu.addAction(_t("ctx.edit_server"))
                act_edit.triggered.connect(lambda _=False, n=win_node: self.window()._edit_node(n))
            # v0.9: автосбор данных о сервере (Linux) по SSH
            if hasattr(win, "_collect_node_info"):
                act_info = menu.addAction(_t("ctx.collect_info"))
                act_info.triggered.connect(
                    lambda _=False, n=win_node: self.window()._collect_node_info(n))
            # v0.8.4 (бывш. DESIGN.md §D): свернуть/развернуть плашку
            if hasattr(win_node, "toggle_collapsed"):
                act_col = menu.addAction(
                    _t("ctx.expand_server") if getattr(win_node.data, "collapsed", False)
                    else _t("ctx.collapse_server"))
                act_col.triggered.connect(lambda _=False, n=win_node: self._toggle_and_mark(n))
            menu.addSeparator()
            if hasattr(win, "_copy_node_info"):
                act_ip = menu.addAction(_t("ctx.copy_ip"))
                act_ip.triggered.connect(lambda _=False, n=win_node: self.window()._copy_node_info(n, "ip"))
                act_host = menu.addAction(_t("ctx.copy_hostname"))
                act_host.triggered.connect(lambda _=False, n=win_node: self.window()._copy_node_info(n, "hostname"))
                act_ping = menu.addAction(_t("ctx.ping"))
                act_ping.triggered.connect(lambda _=False, n=win_node: self.window()._ping_node(n))
            menu.addSeparator()
            if hasattr(win, "_duplicate_node"):
                # v0.9.3: дублирование узла (копия полей + keyring-пароль под новым id)
                act_dup = menu.addAction(_t("ctx.duplicate_server"))
                act_dup.triggered.connect(
                    lambda _=False, n=win_node: self.window()._duplicate_node(n))
            if hasattr(win, "_remove_node_guarded"):
                act_delnode = menu.addAction(_t("ctx.delete_server"))
                act_delnode.triggered.connect(
                    lambda _=False, n=win_node: self.window()._remove_node_guarded(n))

        # ── v0.9.3: групповые операции над мультивыделением ─────────
        if node is not None and hasattr(win, "selected_nodes"):
            try:
                multi = len([i for i in scene.selectedItems()
                             if isinstance(i, ServerNode)]) > 1
            except RuntimeError:
                multi = False
            if multi:
                menu.addSeparator()
                if hasattr(win, "_connect_selected_nodes"):
                    act_conn = menu.addAction(_t("edit.connect_selected"))
                    def _conn_sel(checked=False):  # checked — bool из triggered
                        w = self.window()
                        if hasattr(w, "_connect_selected_nodes"):
                            w._connect_selected_nodes()
                    act_conn.triggered.connect(_conn_sel)
                if hasattr(win, "_delete_selected_nodes"):
                    act_delmulti = menu.addAction(_t("edit.delete_selected"))
                    def _del_sel(checked=False):
                        w = self.window()
                        if hasattr(w, "_delete_selected_nodes"):
                            w._delete_selected_nodes()
                    act_delmulti.triggered.connect(_del_sel)

        # ── v0.7.3: контекстное меню стрелки (связи) ───────────────
        if arrow is not None and node is None:
            win_arrow = arrow
            if hasattr(win, "_edit_connection"):
                act_editc = menu.addAction(_t("ctx.edit_connection"))
                act_editc.triggered.connect(
                    lambda _=False, a=win_arrow: self.window()._edit_connection(a))
            if hasattr(win, "_remove_connection"):
                act_delconn = menu.addAction(_t("ctx.delete_connection"))
                act_delconn.triggered.connect(
                    lambda _=False, a=win_arrow: self.window()._remove_connection(a))

        if node is None and arrow is None:
            # Пустое место (v0.7.2 — заметка; в точке клика). Группа под точкой (v0.8.1):
            # действия над ней дописываются ниже — клик по «фону» папки тоже её выбор.
            if hasattr(win, "_add_server"):
                p = scene_pos
                act_srv = menu.addAction(_t("btn.add_server"))
                # v0.8.1: `checked` — bool из QAction.triggered; раньше он затирал
                # замыкание p, и MainWindow._add_server получал True вместо точки клика.
                def _add_server(checked=False, p=p):
                    w = self.window()
                    fn = getattr(w, "_add_server", None)
                    if callable(fn):
                        try:
                            fn(p)  # позиция точки клика (сигнатура принимает опционально)
                        except TypeError:
                            fn()
                act_srv.triggered.connect(_add_server)
            if hasattr(win, "_add_note_at"):
                p = scene_pos
                act_note = menu.addAction(_t("ctx.add_note"))
                def _add_note(checked=False, p=p):  # v0.8.1: см. _add_server выше
                    w = self.window()
                    if hasattr(w, "_add_note_at"):
                        w._add_note_at(p)
                act_note.triggered.connect(_add_note)
            if NodeGroup is not None and hasattr(win, "_add_group_at"):
                # v0.8.1: новая группа в точке клика (узлы под рамкой захватятся сами)
                p = scene_pos
                act_grp = menu.addAction(_t("ctx.add_group"))
                def _add_group(checked=False, p=p):  # v0.8.1: checked — см. выше
                    w = self.window()
                    fn = getattr(w, "_add_group_at", None)
                    if callable(fn):
                        try:
                            fn(p)
                        except TypeError:
                            fn()
                act_grp.triggered.connect(_add_group)

            # ── v0.8.1: контекстное меню группы (клик по её фону/заголовку) ──
            grp = None
            scene_obj = self.scene()
            if NodeGroup is not None and scene_obj is not None \
                    and hasattr(scene_obj, "find_group_at"):
                grp = scene_obj.find_group_at(scene_pos)
            if grp is not None:
                win_grp = grp  # локальная ссылка для замыканий (паттерн node/arrow выше)
                menu.addSeparator()
                act_rg = menu.addAction(_t("ctx.rename_group"))
                def _rename(checked=False, g=win_grp):  # v0.8.1: checked — bool из triggered
                    w = self.window()
                    if hasattr(w, "_rename_group"):
                        w._rename_group(g)
                act_rg.triggered.connect(_rename)
                act_dg = menu.addAction(_t("ctx.delete_group"))
                def _del_grp(checked=False, g=win_grp):  # v0.8.1: checked — bool из triggered
                    w = self.window()
                    if hasattr(w, "_remove_group"):
                        w._remove_group(g)
                    elif scene is not None and hasattr(scene, "remove_group"):
                        scene.remove_group(g)
                act_dg.triggered.connect(_del_grp)

        if not menu.isEmpty():
            # AUDIT v0.7.2 (средняя #9): не глотаем исключения целиком — «pass» молча
            # превращал любую ошибку в «меню просто не открылось». Координаты уже
            # приведены к QPoint явным хелпером выше; если что-то всё же пойдёт не так,
            # пусть это будет видно (лог + traceback), а не незаметно.
            try:
                menu.exec(self._event_global_point(event))
            except Exception as e:  # noqa: BLE001 — GUI-компонент не должен ронять приложение
                # v1.0-fix (audit #11): логгер вместо print в stderr, как во всём остальном коде.
                try:
                    from modules.logger import get_logger
                    get_logger(__name__).error(f"contextMenuEvent: menu.exec failed: {e}")
                except Exception:  # noqa: BLE001 — сбой логгера не должен ломать контекстное меню
                    pass
        else:
            super().contextMenuEvent(event)

    def _toggle_and_mark(self, node):
        """v0.8.4 (бывш. DESIGN.md §D): toggle_collapsed + пометить проект изменённым."""
        node.toggle_collapsed()
        w = self.window()
        if hasattr(w, "_mark_dirty"):
            w._mark_dirty()
