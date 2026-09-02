"""Стрелки связей между узлами (v0.7).

Кривые Безье от края ноды к краю ноды + типизация связей с цветовой кодировкой:
SSH / VPN / HTTP / Database / NFS / Kubernetes.
"""
import math

try:
    from .server_node import ServerNode
except ImportError:
    from server_node import ServerNode

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsTextItem,
)


def _t(key: str, **kwargs) -> str:
    """Безопасный i18n-хук: при недоступности i18n возвращает сам ключ."""
    try:
        from i18n import t as _translate
        return _translate(key, **kwargs)
    except Exception:
        tpl = key
        try:
            return tpl.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return tpl


def _show_type_on_label() -> bool:
    """v1.1.1 (ROADMAP пункт 6): опция «всегда показывать тип на плашке связи».

    Ключ ui_show_connection_type из ~/.sshmap/config.json (дефолт False — поведение
    v1.1: на плашке только метка, тип несёт цвет). Удобно для экспорта PNG/PDF,
    где цвет менее заметен. Читается при каждом перерисовывании текста метки —
    после ОК в диалоге настроек MainWindow вызывает refresh_label() на стрелках.
    """
    try:
        from i18n import load_config
        v = load_config().get("ui_show_connection_type")
        return bool(v) if isinstance(v, bool) else False
    except Exception:
        return False


def label_display_text(ctype: str, label: str) -> str:
    """Текст плашки связи с учётом опции «тип на плашке» (v1.1.1).

    Опция выключена — только метка (как в v1.1). Включена — «SSH · <метка>»;
    без метки — сам тип («SSH»), чтобы на экспорте тип был виден у каждой связи.
    """
    text = (label or "").strip()
    if not _show_type_on_label():
        return text
    type_name = _t(f"connection.type.{ctype}")
    return f"{type_name} · {text}" if text else type_name


# ── Типы связей (v0.7): id → базовый цвет стрелки ────────────────
# SSH сохраняет зелёный цвет v0.6 и остаётся типом по умолчанию —
# старые проекты без поля "type" загружаются как SSH-связи.
CONNECTION_TYPES = {
    "ssh": "#34d399",        # зелёный — по умолчанию
    "vpn": "#60a5fa",        # синий
    "http": "#fbbf24",       # янтарный
    "database": "#a78bfa",   # фиолетовый
    "nfs": "#f472b6",        # розовый
    "kubernetes": "#22d3ee", # бирюзовый (Kubernetes)
}

DEFAULT_CONNECTION_TYPE = "ssh"


def type_color(ctype: str) -> QColor:
    """Базовый цвет типа связи; неизвестный тип → цвет по умолчанию."""
    return QColor(CONNECTION_TYPES.get(ctype, CONNECTION_TYPES[DEFAULT_CONNECTION_TYPE]))


def edge_point(rect: QRectF, center: QPointF, toward: QPointF) -> QPointF:
    """Точка пересечения луча (из `center` в сторону `toward`) с границей rect.

    Используется для «стрелки от края к краю»: пучок выходит из границы узла,
    а не из его центра (бывш. AUDIT.md / док §7, проблема #7).
    """
    dx = toward.x() - center.x()
    dy = toward.y() - center.y()
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return QPointF(center)
    candidates = []
    if dx > 0:
        candidates.append((rect.right() - center.x()) / dx)
    elif dx < 0:
        candidates.append((rect.left() - center.x()) / dx)
    if dy > 0:
        candidates.append((rect.bottom() - center.y()) / dy)
    elif dy < 0:
        candidates.append((rect.top() - center.y()) / dy)
    t = max(0.0, min(candidates)) if candidates else 1.0
    return QPointF(center.x() + dx * t, center.y() + dy * t)


def build_curve(p0: QPointF, p3: QPointF):
    """Кубическая кривая Безье из p0 в p3 с симметричным изгибом.

    Возвращает (path, c1, c2). Изгиб растёт с дистанцией, но ограничен;
    направление выбирается перпендикуляром k сегменту p0→p3, поэтому A→B и B→A
    прогибаются на противоположные стороны — двунаправленные связи не перекрываются.
    """
    path = QPainterPath()
    path.moveTo(p0)
    dx = p3.x() - p0.x()
    dy = p3.y() - p0.y()
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-6:
        path.lineTo(p3)
        return path, QPointF(p0), QPointF(p3)
    nx = -dy / seg_len   # нормаль (поворот на +90°): для B→A укажет в противоположную сторону
    ny = dx / seg_len
    bend = min(48.0, max(12.0, seg_len * 0.15))
    qx = (p0.x() + p3.x()) / 2.0 + nx * bend
    qy = (p0.y() + p3.y()) / 2.0 + ny * bend
    # Квадратичная Безье с контрольной точкой q → точное кубическое представление:
    c1 = QPointF(p0.x() / 3.0 + qx * 2.0 / 3.0, p0.y() / 3.0 + qy * 2.0 / 3.0)
    c2 = QPointF(p3.x() / 3.0 + qx * 2.0 / 3.0, p3.y() / 3.0 + qy * 2.0 / 3.0)
    path.cubicTo(c1, c2, p3)
    return path, c1, c2


def curve_midpoint(p0: QPointF, c1: QPointF, c2: QPointF, p3: QPointF) -> QPointF:
    """Точка кубической Безье при t=0.5 (позиционирование метки)."""
    return QPointF(
        (p0.x() + 3 * c1.x() + 3 * c2.x() + p3.x()) / 8.0,
        (p0.y() + 3 * c1.y() + 3 * c2.y() + p3.y()) / 8.0,
    )


class ConnectionArrow(QGraphicsPathItem):
    """Кривая стрелка (cubic Bezier) от края одного узла к краю другого."""

    COLOR_IDLE = QColor(CONNECTION_TYPES[DEFAULT_CONNECTION_TYPE])
    COLOR_HOVER = QColor("#6ee7b7")  # сохранено для совместимости с v0.6

    def __init__(self, source: ServerNode, target: ServerNode, label: str = "",
                 ctype: str = DEFAULT_CONNECTION_TYPE, parent=None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self.label_text = label
        # Неизвестный тип (например, из чужого/старого файла проекта) → дефолт
        if ctype not in CONNECTION_TYPES:
            ctype = DEFAULT_CONNECTION_TYPE
        self.connection_type = ctype
        self._base_color = type_color(ctype)
        # UI polish: контрольные точки кривой для расширенной зоны hit-testing (contains());
        # None до первого успешного update_position() — contains() тогда в базовом режиме.
        self._curve_pts = None
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setZValue(-2)
        self.setToolTip(_t(f"connection.type.{self.connection_type}"))

        self._arrow_head = QGraphicsPathItem(self)

        # UI polish: скруглённый фон метки (PathItem вместо RectItem)
        self._label_bg = QGraphicsPathItem(self)
        self._label_bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._label_bg.setBrush(QBrush(QColor(2, 6, 23, 190)))

        # Текст метки (v1.1.1: с учётом опции «тип на плашке» — label_display_text)
        self._label = QGraphicsTextItem(label_display_text(ctype, label), self)
        self._label.setFont(QFont("Consolas", 9))

        self._apply_visual_state()
        self.update_position()

    def _apply_visual_state(self):
        if self._hover:
            color = QColor(self._base_color).lighter(145)
            width = 2.4
        else:
            color = QColor(self._base_color)
            width = 1.8
        self.setPen(QPen(color, width))
        self._arrow_head.setPen(QPen(color, 1.5))
        self._arrow_head.setBrush(QBrush(color))
        self._label.setDefaultTextColor(color)

    # ── Геометрия (v0.7): Безье + край-к-краю ───────────────────

    def _compute_geometry(self):
        """Возвращает (path, p0, p3, c1, c2) или None в вырожденном случае."""
        src_rect = self.source.sceneBoundingRect()
        tgt_rect = self.target.sceneBoundingRect()
        src_center = src_rect.center()
        tgt_center = tgt_rect.center()

        if math.hypot(tgt_center.x() - src_center.x(),
                      tgt_center.y() - src_center.y()) < 1e-6:
            return None  # узлы в одной точке — нечего рисовать (мгновенно при перетаскивании)

        p0 = edge_point(src_rect, src_center, tgt_center)
        p3 = edge_point(tgt_rect, tgt_center, src_center)
        path, c1, c2 = build_curve(p0, p3)
        return path, p0, p3, c1, c2

    def update_position(self):
        geom = self._compute_geometry()
        if geom is None:
            return  # вырожденный случай — держим предыдущий путь
        path, p0, p3, c1, c2 = geom
        self.setPath(path)
        # UI polish: запоминаем контрольные точки для contains() — зоны hit-testing
        self._curve_pts = (p0, c1, c2, p3)

        # Наконечник ориентирован по касательной к концу кривой (направление p3 - c2);
        # кончик — ровно на границе целевого узла. Заполненный треугольник перекрывает
        # конец линии, поэтому зазор не нужен.
        tx = p3.x() - c2.x()
        ty = p3.y() - c2.y()
        if math.hypot(tx, ty) < 1e-9:
            tx, ty = p3.x() - p0.x(), p3.y() - p0.y()
        angle = math.atan2(ty, tx)
        arrow_size = 12
        tip = QPointF(p3)
        left = QPointF(
            tip.x() - math.cos(angle - math.pi / 6) * arrow_size,
            tip.y() - math.sin(angle - math.pi / 6) * arrow_size,
        )
        right = QPointF(
            tip.x() - math.cos(angle + math.pi / 6) * arrow_size,
            tip.y() - math.sin(angle + math.pi / 6) * arrow_size,
        )
        head_path = QPainterPath()
        head_path.moveTo(tip)
        head_path.lineTo(left)
        head_path.lineTo(right)
        head_path.closeSubpath()
        self._arrow_head.setPath(head_path)

        # Метка — в середине кривой, со смещением на сторону, противоположную изгибу
        mid = curve_midpoint(p0, c1, c2, p3)
        dx_seg = p3.x() - p0.x()
        dy_seg = p3.y() - p0.y()
        seg_len = math.hypot(dx_seg, dy_seg) or 1.0
        nx = -dy_seg / seg_len
        ny = dx_seg / seg_len
        label_center = QPointF(mid.x() - nx * 14, mid.y() - ny * 14)
        label_rect = self._label.boundingRect()
        label_x = label_center.x() - label_rect.width() / 2
        label_y = label_center.y() - label_rect.height() / 2
        self._label.setPos(label_x, label_y)
        # UI polish: скруглённый фон под текстом метки (PySide6: addRoundedRect() → None,
        # путь собираем через объект — как в ServerNode._rounded)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(label_x - 6, label_y - 2,
                               label_rect.width() + 12, label_rect.height() + 4, 5.0, 5.0)
        self._label_bg.setPath(bg_path)

    # ── Тип и метка ─────────────────────────────────────────────

    # UI polish: зона hit-testing шире видимого штриха (см. contains()).
    HIT_HALF_WIDTH = 5.0

    def contains(self, localPoint):
        """Расширенная зона клика/ховера вокруг кривой (UI polish).

        Почему не shape().strokeToFill(): в PySide6/Qt 6.11 у QPainterPath нет
        strokeToFill/strokedPath (не пробиндены), а fill-only contains() точку ровно
        на тонкой линии без заливки НЕ ловит — проверено эмпирически: scene.items()
        и scene.itemAt() в точке кривой возвращали пусто, и ПКМ по стрелке не работал.
        Поэтому расстояние до кривой считаем сами по сохранённым контрольным точкам
        (единая кубическая Безье — см. update_position). Бонус: линия 1.8 px
        физически трудно кликается мышью — лента ~10 px исправляет и это.
        """
        pts = getattr(self, "_curve_pts", None)
        if pts is None or localPoint is None:
            return super().contains(localPoint)
        p0, c1, c2, p3 = pts
        px = float(localPoint.x())
        py = float(localPoint.y())
        hw = self.HIT_HALF_WIDTH
        # Число сэмплирований растёт с длиной хорды (шаг <= ~4 px), с потолком.
        seg_len = math.hypot(p3.x() - p0.x(), p3.y() - p0.y()) or 1.0
        n = max(64, min(512, int(seg_len / 4.0)))
        for i in range(1, n + 1):
            t = i / n
            mt = 1.0 - t
            x = (mt * mt * mt) * p0.x() + (3 * mt * mt * t) * c1.x() \
                + (3 * mt * t * t) * c2.x() + (t * t * t) * p3.x()
            y = (mt * mt * mt) * p0.y() + (3 * mt * mt * t) * c1.y() \
                + (3 * mt * t * t) * c2.y() + (t * t * t) * p3.y()
            if (x - px) ** 2 + (y - py) ** 2 <= hw * hw:
                return True
        return False

    def set_type(self, ctype: str):
        """Сменить тип связи (цвет + tooltip). Неизвестные типы игнорируются."""
        if ctype not in CONNECTION_TYPES or ctype == self.connection_type:
            return
        self.connection_type = ctype
        self._base_color = type_color(ctype)
        self.setToolTip(_t(f"connection.type.{ctype}"))
        self._apply_visual_state()
        # v1.1.1: тип на плашке мог появиться/измениться — пересобираем текст метки
        self.refresh_label()

    def set_label(self, text: str):
        self.label_text = text
        self.refresh_label()

    def refresh_label(self):
        """v1.1.1: пересобрать текст плашки (опция «тип на плашке») и геометрию."""
        self._label.setPlainText(label_display_text(self.connection_type, self.label_text))
        self.update_position()

    def hoverEnterEvent(self, event):
        self._hover = True
        self._apply_visual_state()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._apply_visual_state()
        super().hoverLeaveEvent(event)
