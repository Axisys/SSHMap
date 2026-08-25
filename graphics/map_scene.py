from typing import Optional, List, Dict

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

from .server_node import ServerNode
from .connection_arrow import ConnectionArrow, DEFAULT_CONNECTION_TYPE
try:
    from .sticky_note import StickyNote
except ImportError:  # плоский импорт (запуск из корня)
    from sticky_note import StickyNote

try:
    from .node_group import NodeGroup  # v0.8.1: группировка узлов (кластеры/папки)
except ImportError:
    from node_group import NodeGroup

try:
    from .background_image import BackgroundImage  # v0.9.1: фон-изображение
except ImportError:
    from background_image import BackgroundImage

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene


class MapScene(QGraphicsScene):
    """Главная сцена карты."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._nodes: Dict[str, ServerNode] = {}
        self._arrows: List[ConnectionArrow] = []
        # v0.7.2: независимые заметки (не связаны с серверами)
        self._notes: List[StickyNote] = []
        # v0.8.1: группы узлов (кластеры/папки на карте). Порядок в списке — порядок
        # добавления; при одинаковом z верхняя группа = последняя добавленная.
        self._groups: List[NodeGroup] = []
        # v0.9.1: фоновое изображение (схема здания / план дата-центра) — не более одного.
        self._background: Optional[BackgroundImage] = None
        # UI polish: адаптивная сетка — базовый шаг 20 px в координатах сцены; при зуме
        # ВЫШЕ (scale < 1) шаг удваивается, пока интервал на экране не вернётся к базовому.
        # Инвариант: интервал на экране всегда ∈ [16, 32) px — плотность постоянна, а при
        # зуме >= 1 сетка как и раньше (ровно 20 px). Без адаптации при зуме 0.1 рисовалось
        # в ~5 раз лишних линий по каждой оси (тормоз + визуальный шум).
        self._grid_size = 20
        self._grid_min_screen_px = float(self._grid_size) * 0.8   # 16 px
        self._grid_major_every = 5
        self._grid_color = QColor("#0f172a")      # minor-линии (тёмные)
        self._grid_major_color = QColor("#1e293b")  # major-линии (чуть светлее)

    # ── AUDIT v0.8.3 (#5): публичные итераторы вместо обращений к _nodes/_arrows ──

    def nodes(self) -> List[ServerNode]:
        """Все узлы карты (копия списка — безопасно мутировать во время обхода)."""
        return list(self._nodes.values())

    def arrows(self) -> List[ConnectionArrow]:
        """Все стрелки-связи (копия списка)."""
        return list(self._arrows)

    def get_node(self, node_id: str) -> Optional[ServerNode]:
        """Узел по id или None."""
        return self._nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def node_count(self) -> int:
        return len(self._nodes)

    def arrow_count(self) -> int:
        return len(self._arrows)

    def groups(self) -> List[NodeGroup]:
        """Все группы (v0.8.1; копия списка)."""
        return list(self._groups)

    def _current_grid_step(self, scale: float) -> int:
        """Шаг сетки в координатах сцены для текущего масштаба вида.

        При scale >= 1 — базовый шаг (сетка как раньше); при уменьшении зума шаг
        удваивается до возврата интервала на экране к базовому (инвариант [0.8, 2)×base).
        """
        if scale <= 0:
            scale = 1.0
        step = self._grid_size
        while scale < 1.0 and step * scale < self._grid_min_screen_px:
            step *= 2
        return step

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QBrush(QColor("#020617")))

        # Масштаб вида (m11) — из первого вью; без вью рисуем базовый шаг.
        scale = 1.0
        views = self.views()
        if views:
            try:
                s = float(views[0].transform().m11())
                if s > 0:
                    scale = s
            except Exception:  # noqa: BLE001 — без трансформации рисуем как есть
                pass

        step = self._current_grid_step(scale)
        minor_pen = QPen(self._grid_color)
        minor_pen.setWidth(1)
        major_pen = QPen(self._grid_major_color)
        major_pen.setWidth(1)

        left = int(rect.left()) // step * step
        top = int(rect.top()) // step * step
        # Major-линии фиксируем по координатам сцены (кратные step*5), а не по счётчику
        # от края видимого rect — иначе при панорамировании «светлые» линии бежали бы.
        for x in range(left, int(rect.right()), step):
            painter.setPen(major_pen if (x // step) % self._grid_major_every == 0 else minor_pen)
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()), step):
            painter.setPen(major_pen if (y // step) % self._grid_major_every == 0 else minor_pen)
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def add_server(self, data: ServerData) -> ServerNode:
        # AUDIT v0.7.2 (низкая #17): коллизия uuid[:8] — перегенерируем id вместо тихого
        # затирания существующей ноды (у заметок такая проверка уже была в add_note).
        if data.id in self._nodes:
            import uuid as _uuid
            while True:
                new_id = str(_uuid.uuid4())[:8]
                if new_id not in self._nodes:
                    break
            data.id = new_id
        node = ServerNode(data)
        self.addItem(node)
        self._nodes[data.id] = node
        # v0.8.1: новый узел оказался под рамкой группы → автоматически её член
        # (геометрический инвариант см. resync_group_members). Дёшево: только если группы есть.
        if self._groups:
            self.resync_group_members()
        return node

    def remove_server(self, node_id: str):
        if node_id in self._nodes:
            node = self._nodes[node_id]
            # v0.8.1: узел уходит с карты — снимаем его из членства групп (члены
            # остаются на своих местах; состав просто обновляется)
            for g in list(self._groups):
                if node in g.get_members():
                    g.remove_member(node)
            # Удалить связанные стрелки
            arrows_to_remove = [a for a in self._arrows
                                if a.source == node or a.target == node]
            for a in arrows_to_remove:
                self.removeItem(a)
                getattr(a, 'deleteLater', lambda: None)()  # v0.9.3 fix: убираем C++-объект (иначе утечка до конца сессии)
                self._arrows.remove(a)
            self.removeItem(node)
            getattr(node, 'deleteLater', lambda: None)()  # v0.9.3 fix: карточка+тень+пульс+тексты — иначе живут вечно
            del self._nodes[node_id]

    def add_connection(self, source_id: str, target_id: str, label: str = "",
                       ctype: str = DEFAULT_CONNECTION_TYPE) -> Optional[ConnectionArrow]:
        if source_id not in self._nodes or target_id not in self._nodes:
            return None
        if self.has_connection(source_id, target_id):
            return None  # дубль связи не создаём
        src = self._nodes[source_id]
        tgt = self._nodes[target_id]
        arrow = ConnectionArrow(src, tgt, label, ctype)
        self.addItem(arrow)
        self._arrows.append(arrow)
        return arrow

    def has_connection(self, source_id: str, target_id: str) -> bool:
        """Проверить, существует ли уже связь между узлами (в том же направлении)."""
        for a in self._arrows:
            if a.source.data.id == source_id and a.target.data.id == target_id:
                return True
        return False

    # ── v0.7.3: удаление связи ─────────────────────────────────

    def remove_connection(self, arrow: ConnectionArrow) -> bool:
        """Удалить связь по ссылке на стрелку (контекстное меню, v0.7.3).

        Возвращает True, если стрелка была найдена и удалена.
        """
        if arrow in self._arrows:
            self.removeItem(arrow)
            getattr(arrow, 'deleteLater', lambda: None)()  # v0.9.3 fix: C++-объект не должен жить до смерти сцены (deleteLater доступен у QObject-наследников)
            self._arrows.remove(arrow)
            return True
        return False

    def update_connections_for_node(self, node: ServerNode):
        for arrow in self._arrows:
            if arrow.source == node or arrow.target == node:
                arrow.update_position()

    def get_selected_node(self):
        """Возвращает выделенный ServerNode или None."""
        for item in self.selectedItems():
            if isinstance(item, ServerNode):
                return item
        return None

    # ── v0.7.2: заметки (Sticky Notes) ───────────────────────────

    def add_note(self, text: str = "", x: float = 0.0, y: float = 0.0,
                 width: float = 240.0, height: float = 160.0,
                 note_id: Optional[str] = None) -> StickyNote:
        """Создать заметку на сцене (позиция — левый верхний угол)."""
        if note_id is not None and any(n.note_id == note_id for n in self._notes):
            # дубль id при загрузке битого файла — генерируем новый, не теряем заметку
            note_id = None
        note = StickyNote(text=text, x=x, y=y, width=width, height=height, note_id=note_id)
        self.addItem(note)
        self._notes.append(note)
        return note

    def remove_note(self, note_id: str):
        """Удалить заметку по id (no-op, если её нет)."""
        for i, n in enumerate(self._notes):
            if n.note_id == note_id:
                self.removeItem(n)
                getattr(n, 'deleteLater', lambda: None)()  # v0.9.3 fix: QTextEdit внутри заметки — тяжёлый C++-объект
                del self._notes[i]
                return

    def get_note_by_id(self, note_id: str) -> Optional[StickyNote]:
        for n in self._notes:
            if n.note_id == note_id:
                return n
        return None

    # ── v0.8.1: группы узлов (кластеры/папки на карте) ───────────

    def add_group(self, name: str = "", x: float = 0.0, y: float = 0.0,
                  width: Optional[float] = None, height: Optional[float] = None,
                  group_id: Optional[str] = None) -> NodeGroup:
        """Создать группу (рамка + заголовок) в точке сцены (левый верхний угол).

        Узлы, уже лежащие под рамкой, автоматически становятся членами (resync).
        Коллизия id — перегенерируем (паттерн add_server/add_note), запись не теряем.
        """
        if group_id is not None and any(g.group_id == group_id for g in self._groups):
            import uuid as _uuid
            while True:
                new_id = str(_uuid.uuid4())[:8]
                if new_id not in {g.group_id for g in self._groups}:
                    break
            group_id = new_id
        grp = NodeGroup(
            name=name, x=x, y=y,
            width=width if width is not None else NodeGroup.DEFAULT_W,
            height=height if height is not None else NodeGroup.DEFAULT_H,
            group_id=group_id)
        self.addItem(grp)
        self._groups.append(grp)
        self.resync_group_members()  # авто-захват узлов под рамкой (задача v0.8.1 #2)
        return grp

    def remove_group(self, group: NodeGroup) -> bool:
        """Удалить группу. Серверы-члены ОСТАЮТСЯ на карте в тех же позициях —
        группы это контейнер-подпись, а не владелец узлов."""
        if group in self._groups:
            group.clear_members()  # один сигнал, без N пересигналов
            self.removeItem(group)
            getattr(group, 'deleteLater', lambda: None)()  # v0.9.3 fix: рамка+заголовок группы — тоже C++-объекты
            self._groups.remove(group)
            # Узел, чей центр был в этой группе, может оказаться под рамкой другой
            # (нижележащей) группы — инвариант восстанавливаем.
            if self._nodes and self._groups:
                self.resync_group_members()
            return True
        return False

    def remove_group_by_id(self, group_id: str) -> bool:
        grp = self.get_group_by_id(group_id)
        if grp is None:
            return False
        return self.remove_group(grp)

    def get_group_by_id(self, group_id: str) -> Optional[NodeGroup]:
        for g in self._groups:
            if g.group_id == group_id:
                return g
        return None

    def find_group_at(self, scene_pos) -> Optional[NodeGroup]:
        """Верхняя группа под точкой сцены (позднее добавленные — поверх)."""
        try:  # contains(qreal x, qreal y) — не зависит от QPoint/QPointF-варианта биндинга
            px = float(scene_pos.x())
            py = float(scene_pos.y())
        except Exception:  # noqa: BLE001 — не точка (например, bool из QAction.triggered)
            return None
        for g in reversed(self._groups):
            try:
                if QRectF(g.sceneBoundingRect()).contains(px, py):
                    return g
            except RuntimeError:  # Qt teardown — item уже уничтожен
                continue
        return None

    def get_selected_group(self) -> Optional[NodeGroup]:
        """Возвращает выделенную группу или None (аналог get_selected_node)."""
        for item in self.selectedItems():
            if isinstance(item, NodeGroup):
                return item
        return None

    def resync_group_members(self, node_overrides=None, moving_group=None) -> bool:
        """v0.8.1: пересчитать членство по геометрическому инварианту.

        Узел — член ВЕРХНЕЙ группы, в которую попадает центр его карточки; вне всех
        групп — не член ни одной (эксклюзивность). Вызывается при любом движении/
        resize узлов и групп, поэтому в JSON членство хранить не нужно: оно
        восстанавливается из геометрии. Возвращает True, если состав изменился.

        node_overrides  — {node_id: QRectF}: целевые rect узлов, чьё перемещение ещё
                          НЕ применено Qt (itemChange-хук вызывается до setPos).
        moving_group    — (NodeGroup, QRectF): целевая рамка группы в процессе её
                          перемещения (тот же pre-apply момент).
        """
        if not self._groups:
            return False  # без групп пересчитывать нечего (дешёвый выход на горячем пути)

        moving_grp, moving_rect = (moving_group or (None, None))

        desired = {}  # node_id -> NodeGroup | None (по одному — верхней группе)
        for nid, node in list(self._nodes.items()):
            r = QRectF(node_overrides[nid]) if (node_overrides and nid in node_overrides) \
                else node.sceneBoundingRect()
            if r.isEmpty():
                continue
            center = r.center()
            cx, cy = float(center.x()), float(center.y())
            grp = None
            for g in reversed(self._groups):  # верхняя (позднее добавленная) побеждает
                try:
                    if g is moving_grp and moving_rect is not None:
                        gr = QRectF(moving_rect)  # рамка ещё не применена Qt — цель из overrides
                    else:
                        gr = QRectF(g.sceneBoundingRect())
                    if gr.contains(cx, cy):
                        grp = g
                        break
                except RuntimeError:  # Qt teardown
                    continue
            desired[nid] = grp

        current = {}  # node_id -> группа из живых составов (инвариант эксклюзивности)
        for g in self._groups:
            for n in list(g.get_members()):
                if getattr(n, "data", None) is not None and hasattr(n.data, "id"):
                    current[n.data.id] = g

        changed = False
        for nid, grp in desired.items():
            cur = current.get(nid)  # None — узел не состоит ни в одной группе
            if cur is grp:
                continue
            node = self._nodes.get(nid)
            if node is None:
                continue
            if cur is not None:
                cur.remove_member(node)   # снимает membershipChanged (dirty-маркер окна)
                changed = True
            if grp is not None:
                grp.add_member(node)      # add_member сам гарантирует эксклюзивность
                changed = True
        return changed

    def clear_all(self):
        self.clear()  # убирает и узлы, и стрелки, и заметки, и группы, и фон (все QGraphicsItem)
        self._nodes.clear()
        self._arrows.clear()
        self._notes.clear()
        self._groups.clear()  # v0.8.1: составы групп живут в самих items — они удалены
        self._background = None  # v0.9.1

    # ── v0.9.1: фоновое изображение + экспорт карты ──────────────

    def background(self) -> Optional[BackgroundImage]:
        """Текущий фон (или None)."""
        return self._background

    def set_background_image(self, path: str) -> BackgroundImage:
        """Установить фоновое изображение (заменяет предыдущее).

        Размер по умолчанию — нативный размер картинки, позиция (0, 0);
        двигать/масштабировать можно мышью (drag / правый нижний угол).
        Бросает ValueError, если файл не читается как изображение.
        """
        self.remove_background()
        bg = BackgroundImage(path)
        self.addItem(bg)
        self._background = bg
        return bg

    def remove_background(self):
        """Убрать фоновое изображение (no-op, если его нет)."""
        if self._background is not None:
            sc_item = self._background.scene()
            if sc_item is not None:
                self.removeItem(self._background)
            getattr(self._background, 'deleteLater', lambda: None)()  # v0.9.3 fix: pixmap не должен висеть до смерти сцены
            self._background = None

    def render_to_pixmap(self, scale: float = 2.0, padding: float = 60.0,
                         use_view_rect=None) -> "QPixmap":
        """Отрендерить карту в QPixmap (v0.9.1 #1).

        Область — itemsBoundingRect (+padding), т.е. вся карта целиком,
        независимо от текущего зума/панорамирования окна. Фон-изображение
        входит в результат (это часть карты); сетка drawBackground не рисуется —
        рендер идёт через QGraphicsScene.render на чистый pixmap.
        """
        from PySide6.QtGui import QPixmap, QColor

        src = self.itemsBoundingRect().adjusted(
            -float(padding), -float(padding), float(padding), float(padding))
        if src.isEmpty():
            src = QRectF(-400, -300, 800, 600)

        w = max(int(src.width() * scale), 1)
        h = max(int(src.height() * scale), 1)
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor("#0b1220"))  # тот же тон тёмной темы (фон сцены)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.render(painter, target=QRectF(pixmap.rect()), source=src)
        painter.end()
        return pixmap