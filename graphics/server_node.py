import functools
from typing import Optional

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from ..modules.ssh_worker import SSHWorker
except ImportError:
    from modules.ssh_worker import SSHWorker

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

from PySide6.QtCore import Qt, QPointF, QRectF, QVariantAnimation
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QFontMetrics, QPixmap, QTransform)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItemGroup, QGraphicsItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsTextItem,
)


def _t(key: str) -> str:
    """Safe i18n hook: returns the key itself if i18n is unavailable."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


# ── v1.4.2 (ROADMAP task 3): the card drop-shadow — ONE cached pixmap per SIZE ──────
# The v1.2.5 shadow was a single QGraphicsPathItem: a hard-edged strip that extended the
# card only DOWNWARD (SHADOW_BOTTOM = 3), so sceneBoundingRect() could double as the
# arrow/note anchor. The v1.4.2 halo covers all four sides, and a per-item
# QGraphicsDropShadowEffect is FORBIDDEN here — every effect is a separate render layer,
# and the pain at 500 nodes was pinned by the v1.2.10 audit. The soft falloff is painted
# ONCE per distinct card size into a QPixmap and shared by every card of that size
# (a bounded LRU — 500 cards have a handful of distinct widths/heights).
SHADOW_BLUR = 9.0          # the halo's thickness on every side, in scene px
SHADOW_DY = 3.0            # the shadow sits a little lower than the card
SHADOW_LAYERS = 9          # the "blur" = N inflated rounded rects with a low alpha each
SHADOW_LAYER_ALPHA = 12    # per layer; the overlap accumulates to the v1.2.5 tone (~110)
SHADOW_CACHE_SIZE = 64     # at most this many distinct card SIZES keep a pixmap


@functools.lru_cache(maxsize=SHADOW_CACHE_SIZE)
def _shadow_pixmap(width: int, height: int, radius: float) -> QPixmap:
    """The soft shadow of a card of this size (v1.4.2) — the cache key is the SIZE.

    The pixmap is `SHADOW_BLUR` wider than the card on every side (+`SHADOW_DY` at the
    bottom), and the card's top-left corner sits exactly at `(SHADOW_BLUR, SHADOW_BLUR)`
    inside it — that is what the `_shadow` item's position relies on. The falloff is
    built by drawing the card-shaped rounded rect `SHADOW_LAYERS` times, each time
    inflated by `SHADOW_BLUR/LAYERS` and with `SHADOW_LAYER_ALPHA` — the inner layers
    overlap the outer ones, so the alpha grows towards the card and the edge fades.

    `lru_cache` is the whole point of the feature (the v1.2.10 audit): a cache HIT
    costs nothing, a MISS paints ~9 paths once. A QPixmap needs a live QGuiApplication,
    and this function is only ever reached from a card being built — i.e. after one.
    """
    blur = int(SHADOW_BLUR)
    w = max(int(width), 1)
    h = max(int(height), 1)
    pm = QPixmap(w + 2 * blur, h + 2 * blur + int(SHADOW_DY))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        layer = QColor(0, 0, 0)
        layer.setAlpha(SHADOW_LAYER_ALPHA)
        painter.setBrush(QBrush(layer))
        dy = float(SHADOW_DY)
        r = max(float(radius), 0.0)
        for i in range(SHADOW_LAYERS, 0, -1):
            grow = SHADOW_BLUR * i / SHADOW_LAYERS
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(blur - grow, blur - grow + dy, w + 2 * grow, h + 2 * grow),
                r + grow * 0.5, r + grow * 0.5)
            painter.drawPath(path)
    finally:
        painter.end()
    return pm


def shadow_cache_info():
    """The `lru_cache` stats of the shadow pixmaps (v1.4.2 — the topical test)."""
    return _shadow_pixmap.cache_info()


def clear_shadow_cache():
    """Drop the cached shadow pixmaps (tests / a theme switch; harmless in the app)."""
    _shadow_pixmap.cache_clear()


class ServerNode(QGraphicsItemGroup):
    """Visual server node on the map."""

    MIN_NODE_WIDTH = 180
    MIN_NODE_HEIGHT = 130
    # v0.8.4 (former DESIGN.md §D): collapsed badge height — a single line:
    # [icon] alias @host … [●status][SSH dot][▾chevron]
    COLLAPSED_HEIGHT = 46
    # Review fix v0.8.0 (#4): card width cap — a long alias/host/comment
    # no longer stretches the node endlessly; text that doesn't fit is elided (…),
    # the full text is available in the tooltip (hover over the shortened label).
    MAX_NODE_WIDTH = 360

    # Elide layout: where the labels start (see _build_appearance) and the gap to the
    # indicator-dots zone on the right [W-DOT_ZONE_LEFT, W-10] — the dots have z=5 and,
    # without the cap, would cover the tail of a long alias/host (noted in the v0.8 review).
    LABEL_X = 55.0            # x of the alias / host labels
    INFO_X = 10.0             # x of the info block
    DOT_ZONE_LEFT = 46.0      # left edge of the status dot: W - 46 (see update_appearance)
    ELIDE_GAP = 4.0           # gap from the end of the text to the dots
    # UI polish v0.9.x: the server icon is a bit large in both modes — we scale
    # circle+glyph to 70% (40 px -> 28 px) around the center of the original circle (30, 30).
    ICON_SCALE = 0.70
    # v0.8.4: vertical centering of the dots in the collapsed line (tuning:
    # raised and shifted left so they don't overlap the chevron).
    COLLAPSED_DOT_Y = -7.0
    COLLAPSED_DOT_DX = -21.0  # leftward shift of the dots relative to the expanded position
    # Collapsed line: the icon is raised to visually center with the text.
    COLLAPSED_ICON_DY = -8.0

    # UI polish: card corner radius and the drop-shadow.
    # v1.4.2 (ROADMAP task 3): the shadow is a CACHED PIXMAP HALO (see _shadow_pixmap):
    # it extends the card on all four sides, so boundingRect() is inflated by
    # SHADOW_BLUR everywhere (+ SHADOW_DY at the bottom — the shadow sits lower).
    # SHADOW_BOTTOM is kept as the DERIVED total ("how much taller the boundingRect is
    # than the card", 2*BLUR + DY) — the v0.8.4 collapse checks and the suite read it.
    # The ANCHORS (arrows, pinned notes, group membership) no longer come from the
    # boundingRect: they use card_rect()/card_rect_scene() (task 4).
    CORNER_RADIUS = theme.RADIUS_NODE
    SHADOW_BLUR = SHADOW_BLUR
    SHADOW_DY = SHADOW_DY
    SHADOW_BOTTOM = 2 * SHADOW_BLUR + SHADOW_DY

    # v1.2.5: all colors — from the central theme (ui/theme.py); values unchanged.
    COLOR_BG = QColor(theme.NODE_BG)
    COLOR_BORDER = QColor(theme.NODE_BORDER)
    COLOR_SELECTED = QColor(theme.SELECTION_AMBER)
    COLOR_HOVER = QColor(theme.NODE_HOVER)
    # v0.9.6: "Reveal on map" accent (sidebar) — a flash frame. Light blue,
    # distinct from the amber selection (#f59e0b): the node is already selected, and the
    # flash should read as a separate "here it is" signal. Same theme ACCENT as the
    # MapView rectangle-selection frame — one app-wide accent.
    REVEAL_COLOR = QColor(theme.ACCENT)
    # v0.9.8: map search (Ctrl+F) — a static frame on matching nodes.
    # Same theme ACCENT (one accent): matches are read instantly, while the current
    # search result is additionally highlighted in amber + the reveal_flash.
    SEARCH_MATCH_COLOR = QColor(theme.ACCENT)
    COLOR_TEXT = QColor(theme.NODE_TEXT)
    COLOR_LABEL = QColor(theme.NODE_LABEL)
    # UI polish: the gray indicator-dot color until checked.
    # (v1.4.2: the old flat shadow color is gone — the halo is painted by
    #  `_shadow_pixmap()` from a black layer color, see the module constants.)
    COLOR_DOT_IDLE = QColor(theme.DOT_IDLE)

    # v0.7.1: frame colors by availability status (StatusChecker).
    # warn — yellow, distinct from the amber COLOR_SELECTED:
    # at any moment either the selection or the status is shown.
    # v1.2.5: values — from the central theme (ui/theme.py).
    STATUS_COLORS = {k: QColor(v) for k, v in theme.STATUS_COLORS.items()}

    # v0.9.4: tag/environment-role colors. Known roles — fixed colors;
    # arbitrary tags — a deterministic palette color by name hash.
    # v1.2.5: values — from the central theme (ui/theme.py).
    TAG_PALETTE = [QColor(c) for c in theme.TAG_PALETTE]
    TAG_COLORS = {k: QColor(v) for k, v in theme.TAG_COLORS.items()}
    # Tag strip on the card: vertical segments along the left edge.
    TAG_STRIP_WIDTH = 5.0

    @staticmethod
    def tag_color(tag: str) -> QColor:
        """Tag color: known role — its own color, others — by hash from the palette.

        zlib.crc32, not hash(): hash() for strings is salted per-process — the colors
        of arbitrary tags would change from run to run.
        """
        import zlib
        key = (tag or "").strip().lower()
        c = ServerNode.TAG_COLORS.get(key)
        if c is not None:
            return QColor(c)
        h = zlib.crc32(key.encode("utf-8"))
        return QColor(ServerNode.TAG_PALETTE[h % len(ServerNode.TAG_PALETTE)])

    def __init__(self, data: ServerData, parent=None):
        super().__init__(parent)
        self.data = data
        self._current_width = self.MIN_NODE_WIDTH
        self._current_height = self.MIN_NODE_HEIGHT  
        
        self._selected = False
        self._hover = False
        # v0.7.1: availability status (online/warn/offline) — "" until checked
        self._status = ""
        # v1.4rc2 (plugin foundation, rc2): the plugin detail merged into the status
        # tooltip ("" — the status-only tooltip of v0.7.1)
        self._status_detail = ""
        # v0.9.8: map search (Ctrl+F) — True if the node matches the active query
        self._search_matched = False

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setPos(data.x, data.y)

        self._ssh_worker: Optional[SSHWorker] = None
        # v0.9.4: tag-strip segments (created lazily in _rebuild_tag_strip)
        self._tag_segments: list = []
        # v0.7.1: status-change pulse animation — overlay fade-out (opacity 1 -> 0).
        # The QPropertyAnimation(target=QGraphicsItem) variant doesn't work in PySide6 6.11:
        # the C++ QGraphicsItem* has no meta-object property introspection ("non-existing
        # property opacity"), so we use QVariantAnimation + valueChanged.
        self._pulse_anim: Optional[QVariantAnimation] = None

        self._build_appearance()
        # v0.9.4: tag strip at creation (update_appearance may not change
        # the geometry and thus not call _rebuild_frame_paths)
        self._rebuild_tag_strip()

    def _build_appearance(self):
        # v1.4.2 (ROADMAP task 3): the drop-shadow — a cached PIXMAP HALO, not a path item
        # and not a QGraphicsDropShadowEffect (one render layer per item at 500 cards was
        # the v1.2.10 pain). The pixmap comes from the shared per-SIZE cache; the item is
        # mouse-transparent (a halo is not a hit zone) and sits under the card.
        self._shadow = QGraphicsPixmapItem(self)
        self._shadow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._shadow.setZValue(-2)
        self._apply_shadow(self._current_width, self._current_height)

        # Node background (rounded; the pen is the selection/status frame, see _state_pen).
        # QGraphicsRectItem replaced with PathItem: rounded corners (UI polish),
        # pen/brush work the same for PathItem.
        self._bg = QGraphicsPathItem(self)
        self._bg.setPen(QPen(Qt.transparent, 2))
        self._bg.setBrush(QBrush(self.COLOR_BG))
        self._bg.setZValue(-1)

        # v0.7.1: "pulse" overlay on status change — a frame over the background (rounded).
        # Fade-out opacity 1 -> 0 (QVariantAnimation), then hidden.
        self._pulse = QGraphicsPathItem(self)
        self._pulse.setPen(QPen(self.STATUS_COLORS["offline"], 3))
        self._pulse.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._pulse.setZValue(-0.5)
        self._pulse.hide()

        # Icon: circle + vector "server" glyph (UI polish: emoji removed —
        # Segoe UI Emoji renders monochrome/squares on Linux and pixelates on zoom;
        # QPainterPath is cross-platform and crisp at any scale).
        self._icon = QGraphicsEllipseItem(10, 10, 40, 40, self)
        self._icon.setPen(QPen(self.COLOR_BORDER, 2))
        self._icon.setBrush(QBrush(QColor(theme.NODE_ICON_BG)))

        glyph_pen = QPen(self.COLOR_TEXT, 1.6)
        glyph_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._glyph = QGraphicsPathItem(self)
        self._glyph.setPen(glyph_pen)
        self._glyph.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._glyph.setZValue(2)
        self._set_server_glyph()
        # UI polish v0.9.x: shrunk icon — scale both the circle and the glyph
        # around the circle center so the glyph stays centered.
        icon_tr = QTransform()
        icon_tr.translate(30.0, 30.0)
        icon_tr.scale(self.ICON_SCALE, self.ICON_SCALE)
        icon_tr.translate(-30.0, -30.0)
        self._icon.setTransform(icon_tr)
        self._glyph.setTransform(icon_tr)

        # Alias
        self._alias = QGraphicsTextItem(self.data.alias or "Unnamed", self)
        self._alias.setFont(QFont(theme.FONT_UI, 11, QFont.Bold))
        self._alias.setDefaultTextColor(self.COLOR_TEXT)
        self._alias.setPos(55, 18)

        # Availability status dot (UI polish): left of the SSH dot — in the collapsed view
        # and at a small zoom it reads faster than the 2px frame. Gray — until checked.
        self._status_dot = QGraphicsEllipseItem(0, 23, 14, 14, self)
        self._status_dot.setPen(QPen(Qt.PenStyle.NoPen))
        self._status_dot.setBrush(QBrush(self.COLOR_DOT_IDLE))
        self._status_dot.setZValue(5)

        # SSH status indicator (green dot - connected)
        self._ssh_status = QGraphicsEllipseItem(0, 23, 14, 14, self)
        self._ssh_status.setPen(QPen(Qt.PenStyle.NoPen))
        self._ssh_status.setBrush(QBrush(self.COLOR_DOT_IDLE))  # Gray - not connected
        self._ssh_status.setZValue(5)

        # Text plaque (initialization); background — rounded (UI polish)
        self._info = QGraphicsTextItem("", self)
        self._info.setFont(QFont(theme.FONT_MONO, 8))
        self._info.setDefaultTextColor(self.COLOR_LABEL)
        self._info_bg = QGraphicsPathItem(self)
        self._info_bg.setPen(QPen(Qt.PenStyle.NoPen))
        _info_bg_color = QColor(theme.WINDOW_BG)   # v1.2.5: WINDOW_BG + alpha (info-plaque backing)
        _info_bg_color.setAlpha(150)
        self._info_bg.setBrush(QBrush(_info_bg_color))
        self._info_bg.setZValue(0)
        self._info.setZValue(1)

        # Host under the alias
        self._host_label = QGraphicsTextItem(f"@{self.data.host}", self)
        self._host_label.setFont(QFont(theme.FONT_MONO, 8))
        self._host_label.setDefaultTextColor(QColor(theme.DOT_IDLE))
        self._host_label.setPos(55, 36)

        # UI polish: the decorative "SSH button" (🔒) was removed — it wasn't clickable and
        # was misleading; SSH connection is via double-click / RMB menu.

        # v0.8.4 (former DESIGN.md §D): collapse chevron in the top-right corner.
        # Position/geometry are set in update_appearance() for the current mode.
        self._chevron = QGraphicsPathItem(self)
        self._chevron.setPen(QPen(self.COLOR_LABEL, 1.8))
        self._chevron.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._chevron.setZValue(5)

        # Initial height and positions calculation
        self.update_appearance()

    def _set_server_glyph(self):
        """Vector "server" glyph inside the round icon (two units + LEDs)."""
        r = theme.RADIUS_NODE_GLYPH_UNIT
        path = QPainterPath()
        path.addRoundedRect(QRectF(21, 22, 18, 7), r, r)
        path.addRoundedRect(QRectF(21, 31, 18, 7), r, r)
        for cy in (25.5, 34.5):
            path.addEllipse(QPointF(36.5, float(cy)), 0.9, 0.9)
        self._glyph.setPath(path)

    @staticmethod
    def _rounded(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
        """Rounded rectangle. PySide6 nuance: addRoundedRect() returns None
        (in Qt C++ it's QPainterPath&), so we build the path via a separate object."""
        path = QPainterPath()
        path.addRoundedRect(float(x), float(y), max(float(w), 1.0), max(float(h), 1.0),
                            float(r), float(r))
        return path

    def _apply_shadow(self, width: float, height: float):
        """v1.4.2: give the shadow item the cached pixmap of THIS card size.

        The cache is keyed by whole pixels (a 0.4 px difference must not cost a miss),
        and the card's top-left corner sits at (SHADOW_BLUR, SHADOW_BLUR) inside the
        pixmap — hence the item's position. The pixmap is generated once per distinct
        size and SHARED by every card of that size (the memory story of the feature);
        an unchanged size reaches `lru_cache` and costs nothing.
        """
        pixmap = _shadow_pixmap(int(round(float(width))), int(round(float(height))),
                                float(self.CORNER_RADIUS))
        if self._shadow.pixmap().cacheKey() != pixmap.cacheKey():
            self._shadow.setPixmap(pixmap)
        self._shadow.setPos(-SHADOW_BLUR, -SHADOW_BLUR)

    def _rebuild_frame_paths(self, width: float, height: float):
        """Rebuild the rounded background/pulse paths and the shadow pixmap on a size change."""
        r = self.CORNER_RADIUS
        self._bg.setPath(self._rounded(0, 0, width, height, r))
        # v1.4.2: the shadow is a cached pixmap halo around the whole card
        self._apply_shadow(width, height)
        # Pulse follows the background (v0.7.1) — the same rounded frame
        self._pulse.setPath(self._rounded(0, 0, width, height, r))

        # v0.9.4: tag strip along the left edge (rebuild the segments)
        if getattr(self, "_tag_segments", None) is not None:
            self._rebuild_tag_strip()

    def _rebuild_tag_strip(self):
        """v0.9.4: a vertical strip of colored segments from data.tags.

        The segments split the card height evenly (max 4 visible tags — beyond that
        the strip loses readability); drawn over the background (z=-0.8), under the content.
        """
        tags = (getattr(self.data, "tags", None) or [])[:4]
        n_needed = len(tags)
        while len(self._tag_segments) < n_needed:
            from PySide6.QtWidgets import QGraphicsRectItem
            item = QGraphicsRectItem(self)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setZValue(-0.8)
            self._tag_segments.append(item)
        h_total = max(float(self._current_height), 1.0)
        seg_h = h_total / n_needed if n_needed else 0.0
        for i, item in enumerate(self._tag_segments):
            if i < n_needed:
                item.setRect(0.0, i * seg_h, self.TAG_STRIP_WIDTH, seg_h + 0.01)
                item.setBrush(QBrush(ServerNode.tag_color(tags[i])))
                item.show()
            else:
                item.hide()

    def refresh_tags(self):
        """v0.9.4: public hook to update the strip after editing data.tags."""
        self._rebuild_tag_strip()
        self.update()

    def _state_pen(self):
        if self._selected:
            return QPen(self.COLOR_SELECTED, 3)
        # v0.9.8: map-search match — accent frame (below the selection:
        # the current search result is selected and "glowing" amber at the same time).
        if self._search_matched:
            return QPen(self.SEARCH_MATCH_COLOR, 3)
        if self._hover:
            color = QColor(self.COLOR_HOVER)
            color.setAlpha(160)
            return QPen(color, 2)
        # v0.7.1: availability status — the default frame color
        status_color = self.STATUS_COLORS.get(self._status)
        if status_color is not None:
            return QPen(status_color, 2)
        return QPen(Qt.transparent, 2)

    def _apply_visual_state(self):
        self._bg.setPen(self._state_pen())

    def update_appearance(self):
        """Rebuild the text elements when the data changes.

        Review fix v0.8.0 (#4): the card width is bounded by the range
        [MIN_NODE_WIDTH, MAX_NODE_WIDTH]. A long alias/host/comment no longer
        stretches the node endlessly: text that doesn't fit the final width is
        elided (…), the full text — in the tooltip of the shortened label. Alias and host
        additionally don't go under the indicator dots on the right [W-46, W-10].

        Algorithm: the width is computed from the full text with the same formula as before,
        but capped at MAX_NODE_WIDTH; then (in a single pass) the text that doesn't fit the
        final width is shortened to it. Single pass — a deliberate decision:
        "shrink and recompute the width" doesn't converge to a clean fixed point
        (elidedText leaves a gap to the limit), and a card stretched by a single
        long field is still wider than MIN — but the visible information
        is maximal and the geometry is deterministic for any font/platform.

        v0.8.4 (former DESIGN.md §D): when data.collapsed, one line is drawn —
        _info/_info_bg/_host_label are hidden, alias is merged with host ("alias @host"), height —
        COLLAPSED_HEIGHT. The indicator dots stay visible (the most valuable in the
        collapsed view). prepareGeometryChange() is required before a size change.
        """
        if getattr(self.data, "collapsed", False):
            self._update_appearance_collapsed()
            return
        self._show_expanded()
        alias_text = self.data.alias or "Unnamed"
        host_text = f"@{self.data.host}"

        info_lines = []
        # v0.9: OS on the first line (main source — auto-collection, but the field is editable)
        if getattr(self.data, "os_name", ""):
            os_line = self.data.os_name
            if getattr(self.data, "cpu_model", ""):
                os_line += f" · {self.data.cpu_model}"
            info_lines.append(os_line)
        if self.data.cpu: info_lines.append(f"CPU: {self.data.cpu}")
        if self.data.ram: info_lines.append(f"RAM: {self.data.ram}")
        if self.data.disk: info_lines.append(f"DISK: {self.data.disk}")
        if self.data.ip: info_lines.append(f"IP: {self.data.ip}")
        if self.data.ssh_port != 22: info_lines.append(f"SSH:{self.data.ssh_port}")
        # UI polish: the emoji prefix on the comment was removed (consistent style without emoji)
        if self.data.comment: info_lines.append(self.data.comment)

        fm_alias = QFontMetrics(self._alias.font())
        fm_host = QFontMetrics(self._host_label.font())
        fm_info = QFontMetrics(self._info.font())

        def _set_texts(a_text, h_text, i_lines):
            self._alias.setPlainText(a_text)
            self._host_label.setPlainText(h_text)
            self._info.setPlainText("\n".join(i_lines) if i_lines else _t("node.no_data"))

        def _needed_width() -> int:
            """Width formula as before the fix: right edge of content + 24 px."""
            alias_right = self._alias.pos().x() + self._alias.boundingRect().width()
            host_right = self._host_label.pos().x() + self._host_label.boundingRect().width()
            info_width = self._info.boundingRect().width()
            content_right = max(alias_right, host_right, 10 + info_width)
            return int(content_right + 24)

        def _clamp(w: float) -> int:
            return min(max(int(w), self.MIN_NODE_WIDTH), int(self.MAX_NODE_WIDTH))

        # First pass — full text (we also measure the QGraphicsTextItem "markup":
        # boundingRect.width() = horizontalAdvance + constant dock margins ~8 px).
        _set_texts(alias_text, host_text, info_lines)
        overhead = max(0.0, self._alias.boundingRect().width() - fm_alias.horizontalAdvance(alias_text))

        width = _clamp(_needed_width())
        label_max = max(int(width - self.LABEL_X - self.DOT_ZONE_LEFT - self.ELIDE_GAP - overhead), 1)
        info_max = max(int(width - self.INFO_X - 24.0 - overhead), 1)

        # Alias / host: elide to the zone free of dots; full text — in the tooltip
        if fm_alias.horizontalAdvance(alias_text) > label_max:
            self._alias.setPlainText(
                fm_alias.elidedText(alias_text, Qt.TextElideMode.ElideRight, label_max))
            self._alias.setToolTip(alias_text)
        else:
            self._alias.setToolTip("")

        if fm_host.horizontalAdvance(host_text) > label_max:
            self._host_label.setPlainText(
                fm_host.elidedText(host_text, Qt.TextElideMode.ElideRight, label_max))
            self._host_label.setToolTip(host_text)
        else:
            self._host_label.setToolTip("")

        # Info block (line by line); full multi-line text — in the tooltip, if anything was shortened.
        # Under the MAX cap, short lines stay full — only overflow is cut.
        if info_lines:
            elided = []
            any_elided = False
            for line in info_lines:
                lw = fm_info.horizontalAdvance(line)
                if lw > info_max:
                    elided.append(fm_info.elidedText(line, Qt.TextElideMode.ElideRight, info_max))
                    any_elided = True
                else:
                    elided.append(line)
            self._info.setPlainText("\n".join(elided))
            self._info.setToolTip("\n".join(info_lines) if any_elided else "")
        else:
            self._info.setToolTip("")

        # New geometry calculation (height — from the actual info block; elide doesn't
        # wrap lines, so the line count doesn't depend on the shortening).
        # v0.9 fix: the old formula "70 + lines*fm.height()/2" was tuned for ~4
        # lines; with the OS line added (6 lines) the content spilled past the card.
        # Now height = info-block position (58) + its height + the bottom margin.
        info_rect_h = self._info.boundingRect().height()
        needed_height = 58 + info_rect_h + 12

        new_width = _clamp(width)
        new_height = max(int(needed_height), self.MIN_NODE_HEIGHT)

        # If the geometry changed — notify the scene before repainting.
        # v1.4.2: the boundingRect includes the shadow halo — prepareGeometryChange
        # is required for both width and height changes, as before.
        if new_width != self._current_width or new_height != self._current_height:
            self.prepareGeometryChange()  
            self._current_width = new_width
            self._current_height = new_height
            self._rebuild_frame_paths(self._current_width, self._current_height)

        # Position the text block under the icon/host; the plaque background — a rounded path
        self._info.setPos(10, 58)
        info_rect = self._info.boundingRect()
        info_w = max(info_rect.width() + 10, self._current_width - 12)
        info_h = info_rect.height() + 8
        self._info_bg.setPath(self._rounded(6, 56, info_w, info_h, 6.0))

        # Indicator dots on the right: [status][SSH] (UI polish), 14 px each with a gap
        self._status_dot.setPos(self._current_width - 46, 23)
        self._ssh_status.setPos(self._current_width - 24, 23)
        # Chevron — from the CURRENT width (the geometry may have changed above)
        self._chevron.setPath(self._chevron_path(down=False))
        self._apply_visual_state()

        # Sync the connection arrows with the node's new geometry
        if self.scene():
            self.scene().update_connections_for_node(self)

    # ── v0.8.4 (former DESIGN.md §D): collapsing the badge into a single line ─────────────

    def _chevron_path(self, down: bool) -> QPainterPath:
        """Chevron glyph: ▾ (collapsed — can be expanded) / ▴ (expanded)."""
        path = QPainterPath()
        cx = float(self._current_width) - 16.0
        cy = 23.0
        if down:
            path.moveTo(cx - 5, cy - 2)
            path.lineTo(cx + 5, cy - 2)
            path.lineTo(cx, cy + 4)
        else:
            path.moveTo(cx - 5, cy + 2)
            path.lineTo(cx + 5, cy + 2)
            path.lineTo(cx, cy - 4)
        path.closeSubpath()
        return path

    def _show_expanded(self):
        """Show the elements of the expanded card and restore the separate host."""
        self._info.show()
        self._info_bg.show()
        self._host_label.show()
        self._alias.setPos(55, 18)  # restore the position after the collapsed line (y=12)
        # Return the icon to its base position after the collapsed view
        self._icon.setPos(0, 0)
        self._glyph.setPos(0, 0)
        # Restore the original (large) alias font after the collapsed line.
        if hasattr(self, "_alias_font_expanded"):
            self._alias.setFont(QFont(self._alias_font_expanded))

    def _set_geometry(self, width: int, height: int):
        """Geometry change shared by both modes (prepareGeometryChange before resizing)."""
        if width != self._current_width or height != self._current_height:
            self.prepareGeometryChange()
            self._current_width = width
            self._current_height = height
            self._rebuild_frame_paths(width, height)

    def _update_appearance_collapsed(self):
        """Collapsed view: a single line [icon] alias @host … [●status][SSH][▾].

        _info/_info_bg/_host_label are hidden; the indicator dots stay visible.
        The width is computed from the combined "alias @host" text with the same limits
        [MIN_NODE_WIDTH, MAX_NODE_WIDTH] and elide to the dot-free zone. The arrows
        rebuild themselves: the tail calls scene().update_connections_for_node(),
        and edge_point() works from the boundingRect — no extra wiring needed.
        """
        self._info.hide()
        self._info_bg.hide()
        self._host_label.hide()

        # v0.8.4: small font for the collapsed line (a large 11pt alias can't be read
        # on one line) — keep the original so the expanded view doesn't degrade.
        if not hasattr(self, "_alias_font_expanded"):
            self._alias_font_expanded = QFont(self._alias.font())
        small = QFont(self._alias_font_expanded)
        small.setPointSizeF(max(small.pointSizeF() - 3.0, 7.0))
        self._alias.setFont(small)

        alias_text = (self.data.alias or "Unnamed")
        combined = f"{alias_text} @{self.data.host}" if self.data.host else alias_text
        fm_alias = QFontMetrics(self._alias.font())
        self._alias.setPlainText(combined)
        overhead = max(0.0,
                       self._alias.boundingRect().width() - fm_alias.horizontalAdvance(combined))
        width = min(max(int(fm_alias.horizontalAdvance(combined)
                          + self.LABEL_X + self.DOT_ZONE_LEFT + self.ELIDE_GAP + 24.0
                          + overhead), self.MIN_NODE_WIDTH), int(self.MAX_NODE_WIDTH))

        label_max = max(int(width - self.LABEL_X - self.DOT_ZONE_LEFT - self.ELIDE_GAP - overhead), 1)
        if fm_alias.horizontalAdvance(combined) > label_max:
            elided = fm_alias.elidedText(combined, Qt.TextElideMode.ElideRight, label_max)
            self._alias.setPlainText(elided)
            self._alias.setToolTip(combined)
        else:
            self._alias.setToolTip("")

        # Vertical centering of the line within COLLAPSED_HEIGHT; the chevron is set AFTER
        # _set_geometry — the path is computed from the new width (otherwise it's drawn from the old one
        # and "drifts" past the edge / vanishes on a geometry change).
        self._alias.setPos(55, 12)

        self._set_geometry(width, self.COLLAPSED_HEIGHT)
        self._chevron.setPath(self._chevron_path(down=True))
        # UI polish: dots raised and shifted left so they don't cover the chevron
        dot_y = self.COLLAPSED_DOT_Y
        dot_dx = self.COLLAPSED_DOT_DX
        self._status_dot.setPos(self._current_width - 46 + dot_dx, dot_y)
        self._ssh_status.setPos(self._current_width - 24 + dot_dx, dot_y)
        # Icon: raise it toward the text line (collapsed view only)
        icon_dy = self.COLLAPSED_ICON_DY
        self._icon.setPos(0, icon_dy)
        self._glyph.setPos(0, icon_dy)
        self._apply_visual_state()
        if self.scene():
            self.scene().update_connections_for_node(self)

    def toggle_collapsed(self):
        """Toggle the badge's collapsed state and rebuild the view."""
        self.data.collapsed = not bool(getattr(self.data, "collapsed", False))
        self.update_appearance()
        self.update()

    def chevron_rect(self) -> QRectF:
        """Chevron click zone in the node's local coordinates (for mousePressEvent)."""
        return QRectF(float(self._current_width) - 30.0, 8.0, 28.0, 30.0)

    def mousePressEvent(self, event):
        """Click on the chevron — toggle (no drag/panning); everything else — the standard path.

        MapView itself switches to NoDrag over ItemIsMovable objects, so
        accepting the event is enough — the node drag is preserved at the same time.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # QGraphicsSceneMouseEvent has no .position() — only .pos()
            local = QPointF(event.pos())
            if self.chevron_rect().contains(local):
                self.toggle_collapsed()
                event.accept()
                return
        super().mousePressEvent(event)

    def boundingRect(self) -> QRectF:
        """Explicit node geometry: the card + the shadow halo (v1.4.2).

        QGraphicsItemGroup in PySide6/Qt6 doesn't recompute boundingRect from child
        elements automatically (verified: it stays zero), so sceneBoundingRect()
        gave the top-left corner point — the v0.6 arrows effectively went "from the corner".
        The rect is the CARD inflated by the cached shadow halo on all four sides
        (SHADOW_BLUR; + SHADOW_DY at the bottom, because the shadow sits lower) — Qt
        clips child elements by it, so the pixmap item needs the room. The size change
        is protected by prepareGeometryChange() in update_appearance().

        This rect IS "everything the item paints" (fit/zoom, the rubber band, the export).
        The ANCHORS are `card_rect_scene()` (v1.4.2, task 4) — they must not move when
        the shadow's blur changes.
        """
        return QRectF(-SHADOW_BLUR, -SHADOW_BLUR,
                      self._current_width + 2 * SHADOW_BLUR,
                      self._current_height + 2 * SHADOW_BLUR + SHADOW_DY)

    def card_rect(self) -> QRectF:
        """v1.4.2 (ROADMAP task 4): the card WITHOUT the shadow halo — the anchor rect.

        Until v1.4.1 the shadow was a 3 px strip below the card, so the boundingRect
        could double as the anchor of the arrows and of the pinned notes. With the halo
        that shortcut would leave every arrow tip 9 px away from the card, so the anchors
        ask for THIS rect (via `card_rect_scene()`); the boundingRect keeps meaning
        "everything the item paints".
        """
        return QRectF(0.0, 0.0, float(self._current_width), float(self._current_height))

    def card_rect_scene(self) -> QRectF:
        """v1.4.2: `card_rect()` in scene coordinates — the single anchor of the map.

        Consumers: `ConnectionArrow._compute_geometry` (both ends), the pinned-note
        anchor (`MapScene.attach_note_to_node` / `update_note_anchor_for_node` /
        `_update_note_anchor_line`), the geometric group membership
        (`MapScene.resync_group_members`), `NodeGroup.set_group_size` and the `MapView`
        Shift-drag rubber band. Falls back to the painted rect if the C++ object is gone
        (Qt teardown).
        """
        try:
            return self.mapRectToScene(self.card_rect())
        except (RuntimeError, AttributeError):
            return QRectF(self.sceneBoundingRect())

    def set_shadow_visible(self, visible: bool):
        """v1.4.2: show/hide the shadow halo of this card.

        Used by the VECTOR export (`MapScene.render_to_svg`): a QGraphicsPixmapItem is
        written into an SVG as a base64 PNG, which would break the v1.3.3.7 promise
        ("the SVG is vector text, not a raster blob"). PNG/PDF keep the halo — they are
        raster formats anyway.
        """
        try:
            self._shadow.setVisible(bool(visible))
        except RuntimeError:
            pass  # Qt teardown — the item is already destroyed

    def _apply_content_opacity(self):
        """UI polish: dim the card content of offline nodes (frame and dots stay bright)."""
        opacity = 0.55 if self._status == "offline" else 1.0
        for item in (self._icon, self._glyph, self._alias, self._host_label, self._info):
            item.setOpacity(opacity)

    # ── v0.9.4: dimming a node via the tag filter ──

    DIM_OPACITY = 0.25  # nodes not matching the filter — barely visible

    def set_dimmed(self, dimmed: bool):
        """Tag filter: a semi-transparent card for non-matching nodes (and the reverse).

        Unlike the offline dimming (content), here the WHOLE item is muted —
        so non-matching nodes recede into the background entirely. The selection is preserved.
        """
        dimmed = bool(dimmed)
        if getattr(self, "_dimmed", False) == dimmed:
            return
        self._dimmed = dimmed
        self.setOpacity(self.DIM_OPACITY if dimmed else 1.0)

    # ── v0.9.8: map search (Ctrl+F) — highlight of matches ──

    def set_search_match(self, matched: bool):
        """v0.9.8: map search — an accent frame on the matched node (and removing it).

        The highlight — a static pen in _state_pen (priority: selection > match
        > hover > status). Separate from reveal_flash (a short-lived flash overlay)
        and set_dimmed (the whole item's opacity for non-matches). No-op for the same value.
        """
        matched = bool(matched)
        if self._search_matched == matched:
            return
        self._search_matched = matched
        self._apply_visual_state()

    @property
    def search_matched(self) -> bool:
        """v0.9.8: the node matches the active map-search query."""
        return self._search_matched

    def set_ssh_connected(self, connected: bool):
        """Set the SSH connection status."""
        color = QColor(theme.STATUS_ONLINE) if connected else QColor(theme.DOT_IDLE)
        self._ssh_status.setBrush(QBrush(color))

    def set_status(self, status: str, detail: str = ""):
        """v0.7.1: set the availability status (online/warn/offline).

        Updates the frame color (via _state_pen) and starts a short
        pulse animation of the overlay on status change. Unknown statuses
        are ignored; a repeated call with the same status — no-op (the pulse is not
        restarted), EXCEPT for the tooltip detail below.

        v1.4rc2 (plugin foundation, rc2): `detail` is the optional text a plugin's
        `status_probe` contributed to the merged result (`PLUGINS.md` §3 — "appended to
        the node's tooltip"). It travels on its own signal and can arrive after the
        status, so a changed detail updates the tooltip without restarting the pulse;
        an empty detail keeps the status-only tooltip of v0.7.1.
        """
        if status not in self.STATUS_COLORS:
            return
        detail = str(detail or "")
        if status == self._status:
            if detail != self._status_detail:
                self._status_detail = detail
                self._apply_status_tooltip(status)
            return
        color = self.STATUS_COLORS[status]
        self._status = status
        self._status_detail = detail

        self._apply_status_tooltip(status)

        # UI polish: the availability dot (reads faster than the frame at a small zoom)
        # + dimming the card content for offline nodes
        self._status_dot.setBrush(QBrush(color))
        self._apply_content_opacity()

        # Static frame + pulse (overlay fade-out: opacity 1 -> 0)
        self._apply_visual_state()
        self._start_pulse(color)

    def _apply_status_tooltip(self, status: str):
        """v0.7.1/v1.4rc2: the status tooltip, with a plugin's detail appended when present."""
        try:
            from i18n import t as _translate
            tip = _translate(f"node.status.{status}", host=self.data.host or "")
        except Exception:
            tip = f"{status}: {self.data.host}"
        if tip.startswith("["):  # i18n unavailable — the English literal of en.json
            tip = f"{status} — {self.data.host}"
        if self._status_detail:
            tip = f"{tip}\n{self._status_detail}"
        self.setToolTip(tip)

    def _start_pulse(self, color: QColor):
        """v0.7.1/v0.9.6: start the fade-out overlay of a frame in the given color.

        Shared path for the status-change pulse (set_status) and the "Reveal on
        map" accent (reveal_flash). The _pulse overlay follows the card geometry
        (_rebuild_frame_paths rebuilds its path), so the collapsed/expanded
        modes work without extra effort.
        """
        self._pulse.setPen(QPen(color, 3))
        if self._pulse_anim is None:
            from PySide6.QtCore import QEasingCurve
            anim = QVariantAnimation()
            anim.setDuration(900)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)

            def _on_value(v, item=self._pulse):
                try:
                    item.setOpacity(float(v))
                    self.update()
                except RuntimeError:
                    pass  # Qt teardown: the node was removed during the pulse, the C++ item is gone

            def _on_finished(item=self._pulse):
                try:
                    item.hide()
                except RuntimeError:
                    pass  # Qt teardown — see _on_value above

            anim.valueChanged.connect(_on_value)
            anim.finished.connect(_on_finished)
            self._pulse_anim = anim  # the reference keeps the animation alive (no-parent binding)
        self._pulse.show()
        self._pulse.setOpacity(1.0)
        anim = self._pulse_anim
        anim.stop()
        anim.start()

    def reveal_flash(self):
        """v0.9.6: the "Reveal on map" accent from the sidebar — a flash frame (900 ms).

        The same pattern as the set_status pulse (a ready overlay + QVariantAnimation),
        but in REVEAL_COLOR and WITHOUT changing the status: reveal is a navigational
        signal, not an availability probe result.
        """
        try:
            self._start_pulse(self.REVEAL_COLOR)
        except RuntimeError:
            pass  # Qt teardown: the C++ item is destroyed, the call came from live Python

    @property
    def status(self) -> str:
        """Current availability status ("" — not yet checked)."""
        return self._status

    def reset_status(self):
        """v0.7.1: reset the status (e.g. after changing the node's host/port)."""
        if not self._status:
            return
        self._status = ""
        self._status_detail = ""   # v1.4rc2: the plugin detail goes with the status
        self.setToolTip("")
        # UI polish: the dot — gray (not checked), the content — full brightness
        self._status_dot.setBrush(QBrush(self.COLOR_DOT_IDLE))
        self._apply_content_opacity()
        self._apply_visual_state()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            new_pos = value
            self.data.x = new_pos.x()
            self.data.y = new_pos.y()
            if self.scene():
                self.scene().update_connections_for_node(self)
                # v0.8.1: the node moved — group membership is recomputed by geometry
                # (the card center entered/left the frame). IMPORTANT: itemChange is called BEFORE
                # the new position is applied (Qt veto hook — verified with a probe):
                # self.pos()/sceneBoundingRect() inside are still the OLD ones, so we pass the target rect
                # explicitly via overrides; otherwise the membership would "lag" by one step.
                if hasattr(self.scene(), "resync_group_members"):
                    try:
                        dx = float(new_pos.x()) - float(self.pos().x())
                        dy = float(new_pos.y()) - float(self.pos().y())
                        target_rect = QRectF(self.sceneBoundingRect()).translated(dx, dy)
                        self.scene().resync_group_members({self.data.id: target_rect})
                    except Exception:  # noqa: BLE001 — membership is secondary to the move
                        pass
        return super().itemChange(change, value)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_visual_state()
        self.setSelected(selected)

    def hoverEnterEvent(self, event):
        self._hover = True
        self._apply_visual_state()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._apply_visual_state()
        super().hoverLeaveEvent(event)
