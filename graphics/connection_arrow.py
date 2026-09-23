"""Connection arrows between nodes (v0.7).

Bezier curves from the edge of a node to the edge of a node + typed connections
with a color code: SSH / VPN / HTTP / Database / NFS / Kubernetes.

**v1.5rc2 (ROADMAP task 1): a type is no longer a colour alone.** Every type also
carries a declared PEN style (`theme.ARROW_TYPE_STYLES`: a dash pattern, a width and
a "double rail" flag), and this item paints from that declaration — so the six types
stay apart in greyscale, in print and for a colour-vision deficiency. The style is
read through `type_style()` (the ACTIVE theme, on every switch) and `arrow_style()`
is the public read for the topical gate.
"""
import math

try:
    from .server_node import ServerNode
except ImportError:
    from server_node import ServerNode

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsTextItem,
)


def _t(key: str, **kwargs) -> str:
    """Safe i18n hook: returns the key itself when i18n is unavailable."""
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
    """v1.1.1 (ROADMAP item 6): the "always show the type on the connection label" option.

    The ui_show_connection_type key from ~/.sshmap/config.json (default False —
    the v1.1 behavior: only the label on the plate, the type is carried by the
    color). Useful for PNG/PDF export, where color is less noticeable. It is read
    on every re-render of the label text — after OK in the settings dialog
    MainWindow calls refresh_label() on the arrows.
    """
    try:
        from i18n import load_config
        v = load_config().get("ui_show_connection_type")
        return bool(v) if isinstance(v, bool) else False
    except Exception:
        return False


def label_display_text(ctype: str, label: str) -> str:
    """Connection label text taking the "type on the label" option into account (v1.1.1).

    Option off — only the label (as in v1.1). On — "SSH · <label>"; without a
    label — the type itself ("SSH"), so the type is visible on each exported
    connection.
    """
    text = (label or "").strip()
    if not _show_type_on_label():
        return text
    type_name = _t(f"connection.type.{ctype}")
    return f"{type_name} · {text}" if text else type_name


# ── Connection types (v0.7): id → base arrow color ────────────────
# SSH keeps the v0.6 green and remains the default type —
# old projects without the "type" field load as SSH connections.
# v1.2.5: colors — the central theme (ui/theme.py); CONNECTION_TYPES — the same
# dict (declaration order = combobox order in the connection dialog).
# v1.4.3 (ROADMAP task 5): a LIVE map — reading it, iterating it or asking for a
# key resolves the ACTIVE theme, so the arrows follow a theme switch without
# keeping a stale snapshot (the pre-v1.4.3 module constant was captured at
# import time and could never move). `==` compares by value; `is` no longer
# holds (the acceptance test asserts the VALUES, not the identity).
class _LiveConnectionTypes:
    """``{type_id: colour}`` of the ACTIVE theme, with the old dict's API."""

    __slots__ = ()

    def _source(self) -> dict:
        return theme.ARROW_TYPE_COLORS

    def __getitem__(self, key):
        return self._source()[key]

    def __contains__(self, key) -> bool:
        return key in self._source()

    def __iter__(self):
        return iter(self._source())

    def __len__(self) -> int:
        return len(self._source())

    def get(self, key, default=None):
        return self._source().get(key, default)

    def keys(self):
        return self._source().keys()

    def values(self):
        return self._source().values()

    def items(self):
        return self._source().items()

    def __eq__(self, other):
        return self._source() == other

    def __repr__(self):  # pragma: no cover - debugging aid
        return repr(self._source())


CONNECTION_TYPES = _LiveConnectionTypes()

DEFAULT_CONNECTION_TYPE = "ssh"


def type_style(ctype: str):
    """The DECLARED pen style of a connection type (v1.5rc2, ROADMAP task 1).

    Read from the ACTIVE theme on every call (`theme.ARROW_TYPE_STYLES` — the
    declaration next to `arrow_type_colors`), with the default type's style for an
    unknown id, so a consumer never has to know the table's keys.
    """
    return theme.arrow_type_style(ctype)


def type_color(ctype: str) -> QColor:
    """Base color of the connection type; unknown type → the default color."""
    return QColor(CONNECTION_TYPES.get(ctype, CONNECTION_TYPES[DEFAULT_CONNECTION_TYPE]))


def _anchor_rect(node) -> QRectF:
    """v1.4.2 (ROADMAP task 4): the node's CARD rect in scene coordinates.

    The single anchor of an arrow end. `card_rect_scene()` is the v1.4.2 API of
    ServerNode (the card without the shadow halo); the fallback covers a duck-typed
    node (a stand-in in a test) and keeps the pre-v1.4.2 behaviour for it.
    """
    getter = getattr(node, "card_rect_scene", None)
    if callable(getter):
        return QRectF(getter())
    return QRectF(node.sceneBoundingRect())


def edge_point(rect: QRectF, center: QPointF, toward: QPointF) -> QPointF:
    """The point where the ray (from `center` toward `toward`) intersects the rect boundary.

    Used for the "edge-to-edge arrow": the beam leaves the node boundary
    instead of its center (former AUDIT.md / doc §7, problem #7).
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
    """A cubic Bezier curve from p0 to p3 with a symmetric bend.

    Returns (path, c1, c2). The bend grows with distance, but is bounded;
    the direction is chosen perpendicular to the p0→p3 segment, so A→B and B→A
    bend to opposite sides — bidirectional connections do not overlap.
    """
    path = QPainterPath()
    path.moveTo(p0)
    dx = p3.x() - p0.x()
    dy = p3.y() - p0.y()
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-6:
        path.lineTo(p3)
        return path, QPointF(p0), QPointF(p3)
    nx = -dy / seg_len   # normal (a +90° rotation): for B→A it points the opposite way
    ny = dx / seg_len
    bend = min(48.0, max(12.0, seg_len * 0.15))
    qx = (p0.x() + p3.x()) / 2.0 + nx * bend
    qy = (p0.y() + p3.y()) / 2.0 + ny * bend
    # A quadratic Bezier with control point q → the exact cubic representation:
    c1 = QPointF(p0.x() / 3.0 + qx * 2.0 / 3.0, p0.y() / 3.0 + qy * 2.0 / 3.0)
    c2 = QPointF(p3.x() / 3.0 + qx * 2.0 / 3.0, p3.y() / 3.0 + qy * 2.0 / 3.0)
    path.cubicTo(c1, c2, p3)
    return path, c1, c2


def curve_midpoint(p0: QPointF, c1: QPointF, c2: QPointF, p3: QPointF) -> QPointF:
    """The point of the cubic Bezier at t=0.5 (label positioning)."""
    return QPointF(
        (p0.x() + 3 * c1.x() + 3 * c2.x() + p3.x()) / 8.0,
        (p0.y() + 3 * c1.y() + 3 * c2.y() + p3.y()) / 8.0,
    )


class ConnectionArrow(QGraphicsPathItem):
    """A curved arrow (cubic Bezier) from the edge of one node to the edge of another."""

    # v1.4.3 (ROADMAP task 5): live colours — a class read resolves the ACTIVE
    # theme, and `refresh_theme()` re-applies the pens/brushes of the live item.
    # COLOR_IDLE is the default type's colour (computed lazily, so the descriptor
    # may sit above `type_color`); COLOR_HOVER keeps the v0.6 compatibility tone.
    COLOR_IDLE = theme.ThemeValue(
        lambda: QColor(CONNECTION_TYPES[DEFAULT_CONNECTION_TYPE]))
    COLOR_HOVER = theme.ThemeColor("arrow_hover_compat")  # kept for v0.6 compatibility

    def __init__(self, source: ServerNode, target: ServerNode, label: str = "",
                 ctype: str = DEFAULT_CONNECTION_TYPE, bidirectional: bool = False, parent=None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self.label_text = label
        # Unknown type (e.g. from someone else's / an old project file) → default
        if ctype not in CONNECTION_TYPES:
            ctype = DEFAULT_CONNECTION_TYPE
        self.connection_type = ctype
        self._base_color = type_color(ctype)
        # v1.5rc2 (ROADMAP task 1): the DECLARED pen style of this type — the dash
        # pattern, the stroke width and the "double rail" flag, re-read by
        # refresh_theme() like every other theme-derived value of this item.
        self._style = type_style(ctype)
        # v1.2.6: bidirectional connection — arrowheads on BOTH ends of the curve
        # (two-way data exchange); standard mode — the target end only.
        self.bidirectional = bool(bidirectional)
        # UI polish: curve control points for the extended hit-testing zone (contains());
        # None until the first successful update_position() — contains() is in basic mode then.
        self._curve_pts = None
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setZValue(-2)
        self.setToolTip(_t(f"connection.type.{self.connection_type}"))

        # v1.5rc2: the CASING of a double line — a narrower stroke in the surface
        # colour laid over the middle of the main stroke, so the type reads as two
        # rails. It is a child item (painted after the parent's own path) with a
        # negative z, i.e. under the arrowheads and the label plaque.
        self._casing = QGraphicsPathItem(self)
        self._casing.setZValue(-1)
        self._casing.setPen(QPen(Qt.PenStyle.NoPen))

        self._arrow_head = QGraphicsPathItem(self)
        # v1.2.6: the arrowhead at the SOURCE node (bidirectional mode); in standard
        # mode the path is empty — the item is invisible but lives with its parent (no leaks).
        self._arrow_head_src = QGraphicsPathItem(self)

        # UI polish: rounded label background (a PathItem instead of a RectItem)
        self._label_bg = QGraphicsPathItem(self)
        self._label_bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._apply_label_bg_color()

        # Label text (v1.1.1: taking the "type on the label" option into account — label_display_text)
        self._label = QGraphicsTextItem(label_display_text(ctype, label), self)
        self._label.setFont(QFont(theme.FONT_MONO, 9))

        self._apply_visual_state()
        self.update_position()

    def _apply_visual_state(self):
        """v1.5rc2 (ROADMAP task 1): the stroke is built from the DECLARED style.

        The COLOUR comes from the type (the hover lightens it, as since v0.7); the
        GEOMETRY — the dash pattern, the width and the double rail — comes from
        `theme.ARROW_TYPE_STYLES`, so the six types are told apart by a second
        channel and not by hue alone. The hover adds `ARROW_HOVER_WIDTH_DELTA` to
        the declared width (instead of replacing it), so a wide type stays the
        widest one while it is hovered.
        """
        style = self._style
        if self._hover:
            color = QColor(self._base_color).lighter(145)
            width = style.width + theme.ARROW_HOVER_WIDTH_DELTA
        else:
            color = QColor(self._base_color)
            width = style.width
        pen = QPen(color, width)
        if style.dash:
            # Flat caps make the declared rhythm literal — with Qt's default square
            # cap every dash would grow by half the stroke width.
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setDashPattern([float(v) for v in style.dash])
        self.setPen(pen)
        self._arrow_head.setPen(QPen(color, 1.5))
        self._arrow_head.setBrush(QBrush(color))
        # v1.2.6: the second arrowhead keeps the same styling (in standard mode the path is empty)
        self._arrow_head_src.setPen(QPen(color, 1.5))
        self._arrow_head_src.setBrush(QBrush(color))
        self._label.setDefaultTextColor(color)
        self._apply_casing(width)

    def _apply_casing(self, width: float):
        """v1.5rc2: the inner stroke that turns the line into TWO rails.

        `double` is drawn as the main stroke PLUS a narrower stroke in the SURFACE
        colour over its middle — the same convention as the label plaque
        (`CANVAS_BG`), so a double line costs one extra path and no geometry. Any
        other style clears the pen (the casing path is empty for it anyway).
        """
        if not self._style.double:
            self._casing.setPen(QPen(Qt.PenStyle.NoPen))
            return
        self._casing.setPen(QPen(QColor(theme.CANVAS_BG),
                                 max(float(width) * theme.ARROW_CASING_RATIO, 0.8)))

    def _apply_label_bg_color(self):
        """v1.4.3: the label plaque — CANVAS_BG at 190 alpha, read from the ACTIVE theme."""
        color = QColor(theme.CANVAS_BG)
        color.setAlpha(190)
        self._label_bg.setBrush(QBrush(color))

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 5): re-read the theme for this arrow.

        The type colour of this arrow is a VALUE taken when the type was set, so
        a theme switch has to hand it the new one; the label plaque, the DECLARED
        pen style (v1.5rc2 — the table is theme data too) and the geometry follow.
        Called by `MapScene.refresh_theme()` (the window's `apply_theme()` walks the
        scene) and by the print-friendly export of v1.5rc2, which swaps the active
        instance for the duration of a render — never by the paint code.
        """
        self._base_color = type_color(self.connection_type)
        self._style = type_style(self.connection_type)
        self._apply_label_bg_color()
        self._apply_visual_state()
        self.update_position()
        self.update()

    def arrow_style(self):
        """The declared style this arrow paints with (v1.5rc2 — the topical test's seam)."""
        return self._style

    # ── Geometry (v0.7): Bezier + edge-to-edge ───────────────────

    def _compute_geometry(self):
        """Returns (path, p0, p3, c1, c2), or None in the degenerate case.

        v1.4.2 (ROADMAP task 4): the ends are computed from the node's CARD rect
        (`card_rect_scene()`), not from its painted boundingRect — since the drop-shadow
        became a halo on all four sides, the boundingRect is `SHADOW_BLUR` bigger than
        the card and the arrow tips would stop short of it. The fallback keeps a
        duck-typed source/target (a fake node in a test) working.
        """
        src_rect = _anchor_rect(self.source)
        tgt_rect = _anchor_rect(self.target)
        src_center = src_rect.center()
        tgt_center = tgt_rect.center()

        if math.hypot(tgt_center.x() - src_center.x(),
                      tgt_center.y() - src_center.y()) < 1e-6:
            return None  # the nodes are at the same point — nothing to draw (instant during a drag)

        p0 = edge_point(src_rect, src_center, tgt_center)
        p3 = edge_point(tgt_rect, tgt_center, src_center)
        path, c1, c2 = build_curve(p0, p3)
        return path, p0, p3, c1, c2

    def update_position(self):
        geom = self._compute_geometry()
        if geom is None:
            return  # degenerate case — keep the previous path
        path, p0, p3, c1, c2 = geom
        self.setPath(path)
        # v1.5rc2: the casing of a double line follows the SAME path (empty for every
        # other style, so the item is invisible without being removed).
        self._casing.setPath(path if self._style.double else QPainterPath())
        # UI polish: remember the control points for contains() — the hit-testing zone
        self._curve_pts = (p0, c1, c2, p3)

        # The arrowhead is oriented along the tangent to the end of the curve (direction p3 - c2);
        # the tip — exactly on the boundary of the target node. The filled triangle covers
        # the end of the line, so no gap is needed.
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

        # v1.2.6: bidirectional mode — the second arrowhead at the start of the curve (p0).
        # Orientation AGAINST the direction of travel: the tip exactly on the boundary of
        # the source node, the wings — on the side of the curve (hence "+" instead of "-"
        # as with the target arrowhead): the arrowhead points AT its own node, and both
        # ends give ←——→. With "-" the triangle pointed toward the target and its body
        # went under the node (the arrows have zValue -2) — visually the second arrowhead
        # was invisible. Standard mode — an empty path (the item is invisible).
        if self.bidirectional:
            sx = c1.x() - p0.x()
            sy = c1.y() - p0.y()
            if math.hypot(sx, sy) < 1e-9:
                sx, sy = p3.x() - p0.x(), p3.y() - p0.y()
            s_angle = math.atan2(sy, sx)
            src_head = QPainterPath()
            src_head.moveTo(p0)
            src_head.lineTo(
                QPointF(p0.x() + math.cos(s_angle - math.pi / 6) * arrow_size,
                        p0.y() + math.sin(s_angle - math.pi / 6) * arrow_size))
            src_head.lineTo(
                QPointF(p0.x() + math.cos(s_angle + math.pi / 6) * arrow_size,
                        p0.y() + math.sin(s_angle + math.pi / 6) * arrow_size))
            src_head.closeSubpath()
            self._arrow_head_src.setPath(src_head)
        else:
            self._arrow_head_src.setPath(QPainterPath())

        # The label — in the middle of the curve, offset to the side opposite the bend
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
        # UI polish: rounded background under the label text (PySide6: addRoundedRect() → None,
        # the path is built via an object — as in ServerNode._rounded)
        r = theme.RADIUS_ARROW_LABEL
        bg_path = QPainterPath()
        bg_path.addRoundedRect(label_x - 6, label_y - 2,
                               label_rect.width() + 12, label_rect.height() + 4, r, r)
        self._label_bg.setPath(bg_path)
        # v1.4.3: the plaque colour follows the ACTIVE theme on EVERY geometry
        # recompute (a theme switch moves the colour and then calls this method —
        # the arrow has no other hook that runs on a switch).
        self._apply_label_bg_color()

    # ── Type and label ─────────────────────────────────────────────

    # UI polish: the hit-testing zone is wider than the visible stroke (see contains()).
    HIT_HALF_WIDTH = 5.0

    def contains(self, localPoint):
        """Extended click/hover zone around the curve (UI polish).

        Why not shape().strokeToFill(): in PySide6/Qt 6.11 QPainterPath has no
        strokeToFill/strokedPath (not bound), and a fill-only contains() does NOT catch
        a point exactly on a thin unfilled line — verified empirically: scene.items()
        and scene.itemAt() at a point on the curve returned nothing, and the right mouse
        button on the arrow did not work. So the distance to the curve is computed by
        ourselves from the stored control points (a single cubic Bezier — see
        update_position). Bonus: a 1.8 px line is physically hard to click with a mouse
        — a ~10 px band fixes that too.
        """
        pts = getattr(self, "_curve_pts", None)
        if pts is None or localPoint is None:
            return super().contains(localPoint)
        p0, c1, c2, p3 = pts
        px = float(localPoint.x())
        py = float(localPoint.y())
        hw = self.HIT_HALF_WIDTH
        # The number of samples grows with the chord length (step <= ~4 px), with a ceiling.
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
        """Change the connection type (color + DECLARED style + tooltip). Unknown types are ignored."""
        if ctype not in CONNECTION_TYPES or ctype == self.connection_type:
            return
        self.connection_type = ctype
        self._base_color = type_color(ctype)
        self._style = type_style(ctype)   # v1.5rc2: the dash pattern / width / double rail
        self.setToolTip(_t(f"connection.type.{ctype}"))
        self._apply_visual_state()
        # `_apply_visual_state` builds the pens, but the PATHS of the casing follow the
        # style (a double line needs the curve, a single one an empty path) — and the
        # geometry is also how the label plaque is repositioned.
        self.update_position()
        # v1.1.1: the type on the label may have appeared/changed — rebuild the label text
        self.refresh_label()

    def set_bidirectional(self, flag: bool):
        """v1.2.6: enable/disable the bidirectional mode (arrowheads on both ends).

        Idempotent for the same value; toggling recomputes the geometry — the second
        arrowhead appears/disappears without recreating the item.
        """
        flag = bool(flag)
        if flag == self.bidirectional:
            return
        self.bidirectional = flag
        self.update_position()

    def set_label(self, text: str):
        self.label_text = text
        self.refresh_label()

    def refresh_label(self):
        """v1.1.1: rebuild the label text (the "type on the label" option) and the geometry."""
        self._label.setPlainText(label_display_text(self.connection_type, self.label_text))
        self.update_position()

    def hoverEnterEvent(self, event):
        self._hover = True
        self._apply_visual_state()
        self._report_hover_focus(True)   # v1.4.4 (ROADMAP task 4)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._apply_visual_state()
        self._report_hover_focus(False)  # v1.4.4 (ROADMAP task 4)
        super().hoverLeaveEvent(event)

    def _report_hover_focus(self, focused: bool):
        """v1.4.4 (ROADMAP task 4): report the hover to the SCENE, which owns the focus state.

        The arrow only REPORTS (the `MapSearchBar` split: a widget emits, the window decides).
        `MapScene.set_hover_focus_arrow()`/`clear_hover_focus()` are idempotent and the scene
        drops the focus by itself when the hovered arrow dies (`remove_connection`), so a fast
        hover/un-hover can never leave a stuck dim behind.
        """
        scene = self.scene()
        if scene is None:
            return  # not on a map (a bare item in a unit test) — nothing to focus
        try:
            if focused:
                setter = getattr(scene, "set_hover_focus_arrow", None)
                if callable(setter):
                    setter(self)
            else:
                clearer = getattr(scene, "clear_hover_focus", None)
                if callable(clearer):
                    clearer(self)
        except RuntimeError:
            pass  # Qt teardown — the scene is already destroyed
