"""Векторные иконки интерфейса (замена эмодзи, UI polish).

Все иконки рисуются QPainterPath на прозрачном QPixmap: кроссплатформенно
(не зависят от эмодзи-шрифтов), чётко при любом DPI/зуме и в едином стиле —
монохромный контур 20×20. Используется для кнопок сайдбара, тулбара и меню:
QAction/QPushButton получают QIcon из get_icon(name).
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# Базовый цвет иконок (slate-300) — читается на тёмной палитре Fusion (#1e293b).
ICON_COLOR = "#cbd5e1"
ICON_SIZE = 20


def _canvas(size: int = ICON_SIZE):
    """Прозрачный QPixmap + подготовленный QPainter (антиалиасинг, контурный стиль)."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(ICON_COLOR), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return pm, p


def _icon(pm, painter) -> QIcon:
    painter.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


# ── Рисовальщики (канвас 20×20, рабочая область ~3..17) ─────────────

def _draw_new(p):
    """Документ: страница со срезанным углом и сгибом."""
    path = QPainterPath()
    path.moveTo(6.5, 3.0)
    path.lineTo(12.0, 3.0)
    path.lineTo(14.5, 5.5)
    path.lineTo(14.5, 17.0)
    path.lineTo(6.5, 17.0)
    path.closeSubpath()
    p.drawPath(path)
    fold = QPainterPath()
    fold.moveTo(12.0, 3.0)
    fold.lineTo(12.0, 5.5)
    fold.lineTo(14.5, 5.5)
    p.drawPath(fold)


def _draw_open(p):
    """Папка."""
    path = QPainterPath()
    path.moveTo(3.0, 6.0)
    path.lineTo(7.5, 6.0)
    path.lineTo(9.0, 8.0)
    path.lineTo(17.0, 8.0)
    path.lineTo(17.0, 16.5)
    path.lineTo(3.0, 16.5)
    path.closeSubpath()
    p.drawPath(path)


def _draw_save(p):
    """Дискета: корпус + шторка сверху + ярлык снизу."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(3.5, 3.0, 13.0, 14.0), 1.5, 1.5)
    p.drawPath(body)
    shutter = QPainterPath()
    shutter.addRect(QRectF(7.0, 3.0, 6.0, 4.5))
    p.drawPath(shutter)
    label = QPainterPath()
    label.addRect(QRectF(6.0, 10.5, 8.0, 6.5))
    p.drawPath(label)


def _draw_add_server(p):
    """Сервер: две стопки-юниты с индикаторами."""
    top = QPainterPath()
    top.addRoundedRect(QRectF(3.5, 4.0, 13.0, 5.0), 1.5, 1.5)
    p.drawPath(top)
    bottom = QPainterPath()
    bottom.addRoundedRect(QRectF(3.5, 11.0, 13.0, 5.0), 1.5, 1.5)
    p.drawPath(bottom)
    # LED-точки (штрих тонкого круга читается как точка)
    for cy in (6.5, 13.5):
        led = QPainterPath()
        led.addEllipse(QPointF(14.0, float(cy)), 0.7, 0.7)
        p.drawPath(led)


def _draw_connection(p):
    """Два узла и линия между ними."""
    a = QPainterPath()
    a.addEllipse(QPointF(5.8, 14.2), 2.6, 2.6)
    p.drawPath(a)
    b = QPainterPath()
    b.addEllipse(QPointF(14.2, 5.8), 2.6, 2.6)
    p.drawPath(b)
    line = QPainterPath()
    line.moveTo(7.6, 12.4)
    line.lineTo(12.4, 7.6)
    p.drawPath(line)


def _draw_ssh(p):
    """Терминал: рамка + приглашение «>_»."""
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(2.5, 3.5, 15.0, 13.0), 1.8, 1.8)
    p.drawPath(frame)
    prompt = QPainterPath()
    prompt.moveTo(6.0, 7.0)
    prompt.lineTo(9.2, 10.0)
    prompt.lineTo(6.0, 13.0)
    p.drawPath(prompt)
    cursor = QPainterPath()
    cursor.moveTo(11.5, 13.0)
    cursor.lineTo(14.8, 13.0)
    p.drawPath(cursor)


def _draw_properties(p):
    """Слайдеры (свойства/настройки)."""
    for y in (5.5, 10.0, 14.5):
        track = QPainterPath()
        track.moveTo(3.5, float(y))
        track.lineTo(16.5, float(y))
        p.drawPath(track)
    knobs = {5.5: 8.5, 10.0: 12.5, 14.5: 7.0}
    for y, kx in knobs.items():
        knob = QPainterPath()
        knob.addEllipse(QPointF(float(kx), float(y)), 1.6, 1.6)
        p.drawPath(knob)


def _draw_delete(p):
    """Корзина: крышка с ручкой + корпус со штифтами."""
    lid = QPainterPath()
    lid.moveTo(3.5, 6.0)
    lid.lineTo(16.5, 6.0)
    p.drawPath(lid)
    handle = QPainterPath()
    handle.moveTo(8.0, 6.0)
    handle.lineTo(8.0, 4.2)
    handle.lineTo(12.0, 4.2)
    handle.lineTo(12.0, 6.0)
    p.drawPath(handle)
    body = QPainterPath()
    body.moveTo(5.3, 6.0)
    body.lineTo(6.2, 16.8)
    body.lineTo(13.8, 16.8)
    body.lineTo(14.7, 6.0)
    p.drawPath(body)
    for x in (8.5, 11.5):
        rib = QPainterPath()
        rib.moveTo(float(x), 9.2)
        rib.lineTo(float(x), 13.8)
        p.drawPath(rib)


def _draw_fit(p):
    """Четыре угловые скобки «вписать по рамке»."""
    corners = (
        ((3.0, 7.5), (3.0, 3.0), (7.5, 3.0)),    # верх-лево
        ((12.5, 3.0), (17.0, 3.0), (17.0, 7.5)),  # верх-право
        ((3.0, 12.5), (3.0, 17.0), (7.5, 17.0)),  # низ-лево
        ((17.0, 12.5), (17.0, 17.0), (12.5, 17.0)),  # низ-право
    )
    for (x1, y1), (xm, ym), (x2, y2) in corners:
        path = QPainterPath()
        path.moveTo(float(x1), float(y1))
        path.lineTo(float(xm), float(ym))
        path.lineTo(float(x2), float(y2))
        p.drawPath(path)


def _draw_center(p):
    """Прицел: круг + перекрестие с зазорами."""
    ring = QPainterPath()
    ring.addEllipse(QPointF(10.0, 10.0), 4.5, 4.5)
    p.drawPath(ring)
    for x1, y1, x2, y2 in (
        (10.0, 1.8, 10.0, 3.6),
        (10.0, 16.4, 10.0, 18.2),
        (1.8, 10.0, 3.6, 10.0),
        (16.4, 10.0, 18.2, 10.0),
    ):
        tick = QPainterPath()
        tick.moveTo(float(x1), float(y1))
        tick.lineTo(float(x2), float(y2))
        p.drawPath(tick)


def _draw_undo(p):
    """Стрелка влево с хвостом-дугой (undo)."""
    arc = QPainterPath()
    arc.moveTo(6.0, 6.5)
    arc.arcTo(QRectF(4.0, 5.0, 12.0, 10.0), 90.0, -180.0)
    p.drawPath(arc)
    head = QPainterPath()
    head.moveTo(8.8, 2.8)
    head.lineTo(5.2, 6.5)
    head.lineTo(8.8, 10.2)
    p.drawPath(head)


def _draw_redo(p):
    """Зеркальный undo — стрелка вправо (redo)."""
    arc = QPainterPath()
    arc.moveTo(14.0, 6.5)
    arc.arcTo(QRectF(4.0, 5.0, 12.0, 10.0), 90.0, 180.0)
    p.drawPath(arc)
    head = QPainterPath()
    head.moveTo(11.2, 2.8)
    head.lineTo(14.8, 6.5)
    head.lineTo(11.2, 10.2)
    p.drawPath(head)


_DRAWERS = {
    "new": _draw_new,
    "open": _draw_open,
    "save": _draw_save,
    "add_server": _draw_add_server,
    "connection": _draw_connection,
    "ssh": _draw_ssh,
    "properties": _draw_properties,
    "delete": _draw_delete,
    "fit": _draw_fit,
    "center": _draw_center,
    "undo": _draw_undo,
    "redo": _draw_redo,
}


def get_icon(name: str) -> QIcon:
    """Иконка по имени; неизвестное имя — пустой QIcon (кнопка останется текстовой)."""
    drawer = _DRAWERS.get(name)
    if drawer is None:
        return QIcon()
    pm, painter = _canvas()
    try:
        drawer(painter)
    except Exception:  # noqa: BLE001 — иконка не должна ронять интерфейс
        painter.end()
        return QIcon()
    return _icon(pm, painter)
