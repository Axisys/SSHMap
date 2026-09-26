import functools
import time
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

try:  # v1.5rc2 (ROADMAP task 2): the DECLARED status shapes — the mark beside the colour
    from ..ui import status_shape
except ImportError:
    try:
        from ui import status_shape
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        status_shape = None

from PySide6.QtCore import Qt, QPointF, QRectF, QVariantAnimation
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QFontMetrics, QPixmap, QTransform)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItemGroup, QGraphicsItem,
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)


def _t(key: str, **kw) -> str:
    """Safe i18n hook: returns the key itself if i18n is unavailable."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:
        return key


# ── v1.5 (ROADMAP): the ENVIRONMENT badge — the declared vocabulary ────────────────
# The card carries its tags as a tone the SAME card already uses for availability
# (`Theme.tag_colors`: `prod` → `status_offline`, `staging` → `status_warn`, `dev` →
# `status_online`) and an arbitrary tag gets a `crc32` colour from `tag_palette`. That is
# meaning in a colour alone — rule 2 of the 1.5 line — so v1.5 added the second channel:
# the tag as TEXT in a chip, with the colour kept as a redundant tint.
#
# The COLOUR channel is the card's ICON — the brush of the circle the `_glyph` sits in — and
# the TEXT channel is the chip in the free band ABOVE the alias (the `y ≈ 2..17` band the
# measured layout leaves empty in both layouts): the chip keeps its own row, so it never
# competes with the name for one.
#
# The vocabulary is DECLARED here and its ORDER IS THE PRECEDENCE: a card tagged
# `["dev", "prod"]` is production, whatever order the user typed the tags in. `staging`
# is the name `Theme.tag_colors` uses; `stage` is accepted as its short form. A card whose
# tags carry none of these words still gets a header — `env_tag()` then falls back to the
# first tag the user wrote, and `tag_color()` gives it the `crc32` palette colour.
ENV_TAGS = ("prod", "staging", "stage", "dev", "test")


def env_tag(tags) -> str:
    """The card's PRIMARY tag — the environment it belongs to (v1.5).

    The DECLARED vocabulary WINS the pick and its order IS the precedence, so
    `["dev", "prod"]` is production and `["web", "prod"]` is too (a user's tag order must
    not decide what an environment is). A card whose tags carry none of the declared words
    falls back to the FIRST tag the user wrote — the header names the card's primary label,
    which is what makes the badge useful on maps that never used the vocabulary.

    Returns the tag AS THE USER WROTE IT (the colour lookup is case-insensitive, but a
    badge must not rename the user's own data), or "" for a card without tags — and such a
    card paints exactly like a pre-v1.5 card. Pure, so `tests/test_tags.py` pins the
    precedence without a window.
    """
    by_name = {}
    first = ""
    for tag in (tags or ()):
        text = str(tag or "").strip()
        if text:
            by_name.setdefault(text.lower(), text)
            if not first:
                first = text
    for known in ENV_TAGS:
        if known in by_name:
            return by_name[known]
    return first


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
    #: The alias is the card's headline and the ONE line a user reads from a distance, so it
    #: is a bold UI face (v1.5.6: 10 pt — a size STEP DOWN from the 11 pt the card used to
    #: carry, which buys roughly 10% more characters of the name before the elide).
    ALIAS_FONT_SIZE = 10
    # UI polish v0.9.x: the server icon is a bit large in both modes — we scale
    # circle+glyph to 70% (40 px -> 28 px) around the center of the original circle (30, 30).
    ICON_SCALE = 0.70
    # v0.8.4: vertical centering of the dots in the collapsed line (tuning:
    # raised and shifted left so they don't overlap the chevron).
    COLLAPSED_DOT_Y = -7.0
    COLLAPSED_DOT_DX = -21.0  # leftward shift of the dots relative to the expanded position
    # Collapsed line: the icon is raised to visually center with the text.
    COLLAPSED_ICON_DY = -8.0
    # v1.5rc2 (ROADMAP task 2): the box of the availability MARK — the shape is
    # `theme.STATUS_SHAPES[status]` (a filled dot / a ring / a triangle), drawn in the
    # status colour, and this box is the size the v1.4.x round dot already had.
    STATUS_DOT_SIZE = 14

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

    # v1.4.3 (ROADMAP task 5): the colours are LIVE descriptors, not values
    # captured at import time — a class attribute read (`node.COLOR_BG`,
    # `ServerNode.STATUS_COLORS["online"]`) resolves the ACTIVE theme on every
    # access, so `set_theme()` + a repaint is all the switch needs. Everything
    # BELOW in `_build_appearance` is therefore re-applied by `refresh_theme()`.
    COLOR_BG = theme.ThemeColor("node_bg")
    COLOR_BORDER = theme.ThemeColor("node_border")
    COLOR_SELECTED = theme.ThemeColor("selection_amber")
    COLOR_HOVER = theme.ThemeColor("node_hover")
    # v0.9.6: "Reveal on map" accent (sidebar) — a flash frame. Light blue,
    # distinct from the amber selection (#f59e0b): the node is already selected, and the
    # flash should read as a separate "here it is" signal. Same theme ACCENT as the
    # MapView rectangle-selection frame — one app-wide accent.
    REVEAL_COLOR = theme.ThemeColor("accent")
    # v0.9.8: map search (Ctrl+F) — a static frame on matching nodes.
    # Same theme ACCENT (one accent): matches are read instantly, while the current
    # search result is additionally highlighted in amber + the reveal_flash.
    SEARCH_MATCH_COLOR = theme.ThemeColor("accent")
    COLOR_TEXT = theme.ThemeColor("node_text")
    COLOR_LABEL = theme.ThemeColor("node_label")
    # UI polish: the gray indicator-dot color until checked.
    # (v1.4.2: the old flat shadow color is gone — the halo is painted by
    #  `_shadow_pixmap()` from a black layer color, see the module constants.)
    COLOR_DOT_IDLE = theme.ThemeColor("dot_idle")

    # v0.7.1: frame colors by availability status (StatusChecker).
    # warn — yellow, distinct from the amber COLOR_SELECTED:
    # at any moment either the selection or the status is shown.
    # v1.4.3: a live map of the ACTIVE theme's status colours.
    STATUS_COLORS = theme.ThemeMap("status_colors")

    # v0.9.4: tag/environment-role colors. Known roles — fixed colors;
    # arbitrary tags — a deterministic palette color by name hash.
    # v1.4.3: both are live views of the ACTIVE theme.
    TAG_PALETTE = theme.ThemeMap("tag_palette", as_list=True)
    TAG_COLORS = theme.ThemeMap("tag_colors")

    # ── v1.5 (ROADMAP): the two optional badges of the card ────────────────────────
    # THE FREE BAND — the top of the card carries both optional badges, and it is measured:
    # the alias sits at (55, 18), the host at (55, 36), the info plaque at (10, 58), the
    # status/SSH marks at (W-46, 23) / (W-24, 23) and the chevron's centre at (W-16, 23) —
    # so the band `y ≈ 2..17 × x = 55..W-10` is empty in the expanded layout, and neither
    # the height formula (`58 + info + 12`) nor `MIN_NODE_HEIGHT` changes because of a badge.
    ENV_BADGE_Y = 2.0              # the top of the band (above the alias)
    ENV_BADGE_FONT_SIZE = 7
    # The EMULATED marker shares the SAME band, right-aligned — the measured geometry left no
    # other home: the status/SSH marks really sit at y = 46..60 (the item's `y = 23` PLUS the
    # path's own +23) over the info plaque's top-right corner, so the band is the one place
    # where a marker cannot cover another channel (and it works in the collapsed layout too,
    # whose marks are raised to y = 16..30). `_apply_badges()` places this badge FIRST and the
    # environment chip elides into the room that is left, so the two can never collide.
    DEMO_BADGE_FONT_SIZE = 6
    #: The chips of a badge: the inner padding, the corner radius and the gap between the two
    #: badges of the band.
    BADGE_PAD_X = 3.0
    BADGE_PAD_Y = 1.0
    BADGE_RADIUS = 3.0
    BADGE_RIGHT_INSET = 10.0       # the right edge of the band (clear of the chevron)
    BADGE_GAP = 4.0                # the gap between the emulated marker and the tag badge
    BADGE_MIN_SPAN = 18.0          # less room than this — the tag badge is hidden, not "…"
    #: How many characters of the label must survive the elide for the chip to be worth
    #: drawing ("pro…" yes, "p…" no) — the font-independent half of `BADGE_MIN_SPAN`.
    BADGE_MIN_CHARS = 3

    # ── v1.5.3 (ROADMAP task 1): the AGE of the collected facts ───────────────────
    # The v1.5rc3 mechanism applied to the SECOND family of measured data. A status is a
    # fact with a timestamp (the checker owns WHEN and the threshold); the collected
    # hardware facts carry their own timestamp INSIDE the data (`info_collected_at`, the
    # collection path writes it) and their own horizon here — the manager of the two halves
    # is the same: the mark is painted in the IDLE tone, the tooltip names the age, and the
    # stored VALUE is never touched.
    # The threshold is deliberately NOT the status one: `max(2 × interval, 90 s)` answers
    # "did I miss a probe round", while hardware rarely moves — a week is the point where a
    # "DISK: 468.4 gb" line stops being a measurement and becomes a memory. The mark is a
    # LABEL: an old fact keeps its value, its card and its size.
    INFO_STALE_AFTER_SEC = 7 * 24 * 3600.0   # one week


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
        # v1.6 (ROADMAP task 2): the card density this card was laid out with — the
        # LIVE value of `ui/theme.py`, kept per item so `refresh_theme()` can see that
        # the switch moved and re-lay the card out (a value captured once is a bug in
        # this system; the re-read in `sync_density()` is the fix).
        self._density = theme.card_density()
        
        self._selected = False
        self._hover = False
        # v0.7.1: availability status (online/warn/offline) — "" until checked
        self._status = ""
        # v1.4rc2 (plugin foundation, rc2): the plugin detail merged into the status
        # tooltip ("" — the status-only tooltip of v0.7.1)
        self._status_detail = ""
        # v1.5rc3 (ROADMAP task 3): WHEN the status was determined (epoch seconds; 0.0
        # — never) and how old it may get before the mark is painted as stale. The
        # window feeds both (StatusChecker.last_checked_at / stale_threshold_s); the
        # card only ever reads them — freshness is a LABEL, never a status change.
        self._checked_at = 0.0
        self._stale_after = 0.0
        self._stale = False
        # v1.5 (ROADMAP): is the shown status EMULATED (the demo map)? An emulated status
        # is always MARKED as emulated, never carries a freshness line (it is not the
        # result of a probe) and can only be produced by the demo's own declaration.
        self._status_emulated = False
        # v1.5.3 (ROADMAP task 1): the age of the COLLECTED FACTS. `_info_at` mirrors
        # `data.info_collected_at` (the window feeds it after a collection and the freshness
        # tick re-reads it), `_info_stale` is the mark, `_info_tip_full` keeps the full
        # multi-line info text so the plaque tooltip can compose it with the age line.
        # Independent of the status freshness above: a card can have a fresh status and
        # year-old hardware lines, or the other way round.
        self._info_at = 0.0
        self._info_stale = False
        self._info_tip_full = ""
        # v1.5.3 (ROADMAP task 3): the "why" of the shown status — the sentence of the last
        # on-demand reachability report ("" — none was asked). It refines the status
        # tooltip; a NEW status from a probe clears it (fresh evidence replaces the old
        # explanation), a repeated one keeps it.
        self._status_report = ""
        # v1.5: the two OPTIONAL badges (the environment tag, the emulated marker) are
        # built ON FIRST USE — a card that needs neither carries no extra item at all.
        self._env_chip = None
        self._env_badge = None
        self._demo_chip = None
        self._demo_badge = None
        # v0.9.8: map search (Ctrl+F) — True if the node matches the active query
        self._search_matched = False

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setPos(data.x, data.y)

        self._ssh_worker: Optional[SSHWorker] = None
        # v0.7.1: status-change pulse animation — overlay fade-out (opacity 1 -> 0).
        # The QPropertyAnimation(target=QGraphicsItem) variant doesn't work in PySide6 6.11:
        # the C++ QGraphicsItem* has no meta-object property introspection ("non-existing
        # property opacity"), so we use QVariantAnimation + valueChanged.
        self._pulse_anim: Optional[QVariantAnimation] = None

        self._build_appearance()

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
        # v1.5.6 (ROADMAP task 3): the circle's BRUSH is the card's environment tone —
        # the primary tag's colour (`_apply_env_icon()`); a card without tags keeps the
        # neutral `NODE_ICON_BG` it always had.
        self._icon = QGraphicsEllipseItem(10, 10, 40, 40, self)
        self._icon.setPen(QPen(self.COLOR_BORDER, 2))
        self._apply_env_icon()

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
        self._alias.setFont(QFont(theme.FONT_UI, self.ALIAS_FONT_SIZE, QFont.Bold))
        self._alias.setDefaultTextColor(self.COLOR_TEXT)
        self._alias.setPos(55, 18)

        # Availability status dot (UI polish): left of the SSH dot — in the collapsed view
        # and at a small zoom it reads faster than the 2px frame. Gray — until checked.
        # v1.5rc2 (ROADMAP task 2): the mark is a QGraphicsPathItem, because a status is
        # a SHAPE now (filled dot / ring / triangle — `theme.STATUS_SHAPES`); the brush
        # still carries the status COLOUR, so every consumer of `.brush()` is unchanged.
        self._status_dot = QGraphicsPathItem(self)
        self._status_dot.setPen(QPen(Qt.PenStyle.NoPen))
        self._status_dot.setBrush(QBrush(self.COLOR_DOT_IDLE))
        self._status_dot.setZValue(5)
        self._apply_status_dot()

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

    # ── v1.5.6 (ROADMAP task 3): the ENVIRONMENT is a TONE on the card's ICON ─────────

    def env_icon_color(self) -> QColor:
        """The brush tone of the card's icon: the primary tag's colour, or the neutral one.

        The pick is `env_tag()` (the declared vocabulary, its precedence included); the
        tone is the SAME `tag_color()` the badge chip and the tag filter use, so the two
        channels of one tag can never disagree. A card WITHOUT tags answers the neutral
        `NODE_ICON_BG` — it paints exactly like a card from before v1.5.
        """
        text = env_tag(getattr(self.data, "tags", None))
        if not text:
            return QColor(theme.NODE_ICON_BG)
        return ServerNode.tag_color(text)

    def _apply_env_icon(self) -> None:
        """Paint the icon with the environment tone (BOTH card modes — the icon is always there)."""
        try:
            self._icon.setBrush(QBrush(self.env_icon_color()))
        except RuntimeError:
            pass  # Qt teardown — the item is already destroyed

    def refresh_tags(self):
        """v0.9.4: public hook to update the environment marks after editing data.tags.

        v1.5.6 (ROADMAP task 3): the tags reach the card through TWO channels — the ICON's
        tone and the chip's TEXT — so this hook re-applies both (the tag filter's own
        dimming is not part of the card).
        """
        self._apply_env_icon()
        self._apply_badges()
        self.update()

    # ── v1.5 (ROADMAP): the ENVIRONMENT badge and the EMULATED marker ──────────────

    def _ensure_badge_items(self):
        """Build the four optional badge items the first time a card needs one.

        A card that carries neither an environment tag nor an emulated status therefore
        carries NO extra item at all — the "a card without an env tag is byte-identical
        to today" rule holds literally, and a 500-card map pays for the badges it shows,
        not for the ones it could show.
        """
        if self._env_badge is not None:
            return
        self._env_chip = QGraphicsPathItem(self)
        self._env_chip.setPen(QPen(Qt.PenStyle.NoPen))
        self._env_chip.setZValue(4.8)
        self._env_chip.hide()
        self._env_badge = QGraphicsSimpleTextItem(self)
        self._env_badge.setFont(QFont(theme.FONT_MONO, self.ENV_BADGE_FONT_SIZE))
        self._env_badge.setZValue(4.9)
        self._env_badge.hide()
        self._demo_chip = QGraphicsPathItem(self)
        self._demo_chip.setPen(QPen(Qt.PenStyle.NoPen))
        self._demo_chip.setZValue(4.8)
        self._demo_chip.hide()
        self._demo_badge = QGraphicsSimpleTextItem(self)
        self._demo_badge.setFont(QFont(theme.FONT_MONO, self.DEMO_BADGE_FONT_SIZE))
        self._demo_badge.setZValue(4.9)
        self._demo_badge.hide()

    def _place_badge(self, chip, text_item, label: str, ink: str, tint, y: float,
                     x_right: float, x_left: float = None) -> float:
        """Draw one badge: a tinted chip behind the text — the text carries the meaning.

        The chip is the REDUNDANT channel (a light fill of the tag colour plus its
        1 px outline — the SAME tone the card's icon carries), the label is painted in `ink`
        — a theme tone the contrast gate holds at AA on the card, so no badge can ever
        create an ungated colour pair (rule 3 of the 1.5 line).

        `x_right` is the right edge of the badge; `x_left` (optional) is a left edge it
        starts from (the environment band). A label too wide for the room it has is elided —
        the full text goes to the item's tooltip. Returns the badge's width.
        """
        font = text_item.font()
        fm = QFontMetrics(font)
        right = float(x_right)
        left = float(x_left) if x_left is not None else None
        if left is not None:
            limit = max(int(right - left - 2.0 * self.BADGE_PAD_X), 1)
        else:
            limit = max(int(fm.horizontalAdvance(label)), 1)
        shown = label if fm.horizontalAdvance(label) <= limit else \
            fm.elidedText(label, Qt.TextElideMode.ElideRight, limit)
        if shown != label and not self._badge_readable(shown):
            # The room holds an ellipsis and little else: a chip reading "…" (or "p…") says
            # nothing while claiming the band. The caller draws NO badge instead — the same
            # "hidden, not '…'" rule as the span check, applied to what would really be
            # PRINTED (a width alone is font-dependent: a two-glyph prefix is short in a
            # narrow UI font and passes in a wide fallback one).
            chip.hide()
            text_item.hide()
            return 0.0
        text_item.setText(shown)
        text_item.setBrush(QBrush(QColor(ink)))
        text_item.setToolTip(label if shown != label else "")
        w = float(fm.horizontalAdvance(shown)) + 2.0 * self.BADGE_PAD_X
        rect = QRectF(0.0, 0.0, w, float(fm.height()) + 2.0 * self.BADGE_PAD_Y)
        x = (left if left is not None else right - w)
        chip.setPath(self._rounded(x, y, rect.width(), rect.height(), self.BADGE_RADIUS))
        color = QColor(tint)
        fill = QColor(color)
        fill.setAlpha(64)
        chip.setBrush(QBrush(fill))
        outline = QColor(color)
        outline.setAlpha(200)
        chip.setPen(QPen(outline, 1.0))
        chip.show()
        text_item.setPos(x + self.BADGE_PAD_X, y + self.BADGE_PAD_Y)
        text_item.show()
        return w

    def _badge_readable(self, shown: str) -> bool:
        """Does an ELIDED chip label still say something (v1.5.6)?

        A chip must keep at least `BADGE_MIN_CHARS` characters of the label before the
        ellipsis; below that it is noise that costs a band. Font-independent on purpose —
        the metric of "p…" depends on the family, the count of its letters does not.
        """
        text = str(shown or "")
        for marker in ("\u2026", "..."):
            if text.endswith(marker):
                text = text[:-len(marker)]
                break
        return len(text) >= int(self.BADGE_MIN_CHARS)

    def _apply_env_badge(self, width: float, reserved: float = 0.0):
        """The primary tag as TEXT in the free band ABOVE the alias (v1.5, ROADMAP task 3).

        The chip is the second channel of the tag: the card's ICON carries the TONE and the
        WORDS sit in the measured band over the alias, which leaves the alias row itself to
        the name (a chip on that row would have to shorten it). The pick and its precedence
        are `ENV_TAGS` / `env_tag()`; the colour is the SAME `tag_color()` the icon paints
        with, used as a redundant tint.

        `reserved` is the width the EMULATED marker already took from the right end of the
        band: the tag chip elides into what is left, and it is HIDDEN (never reduced to "…")
        when that is less than `BADGE_MIN_SPAN` or when the elided label would keep fewer
        than `BADGE_MIN_CHARS` characters. A card without tags — and every COLLAPSED card,
        whose single line has no second row — hides the chip and paints exactly like a
        pre-v1.5 card.
        """
        text = "" if (getattr(self.data, "collapsed", False) or self._is_compact()) \
            else env_tag(getattr(self.data, "tags", None))
        right = float(width) - self.BADGE_RIGHT_INSET - float(reserved or 0.0)
        if reserved:
            right -= self.BADGE_GAP
        if not text or right - self.LABEL_X < self.BADGE_MIN_SPAN:
            if self._env_badge is not None:
                self._env_badge.hide()
                self._env_chip.hide()
            return
        self._ensure_badge_items()
        self._place_badge(self._env_chip, self._env_badge, text, self.COLOR_LABEL,
                          self.tag_color(text), self.ENV_BADGE_Y, right, self.LABEL_X)

    def _apply_demo_badge(self, collapsed: bool) -> float:
        """The EMULATED marker — a status the demo map declares is always MARKED (v1.5).

        The honesty rule of the closing release: `node.status.emulated` sits in the card's
        free band, right-aligned, in the card's own label tone on a neutral `dot_idle` frame
        (the "this is not a fresh measurement" tone the stale mark already uses), so a
        colour-blind reader, a greyscale print and a screenshot all say the same thing.
        Returns the width it occupies (0.0 when it is hidden) — the tag badge yields to it.
        """
        if not self._status_emulated:
            if self._demo_badge is not None:
                self._demo_badge.hide()
                self._demo_chip.hide()
            return 0.0
        self._ensure_badge_items()
        return self._place_badge(self._demo_chip, self._demo_badge,
                                 _t("node.status.emulated"), self.COLOR_LABEL,
                                 theme.DOT_IDLE, self.ENV_BADGE_Y,
                                 float(self._current_width) - self.BADGE_RIGHT_INSET)

    def _apply_badges(self):
        """Re-place both optional badges for the CURRENT layout and width.

        The EMULATED marker goes first and reports the room it took: it may never be pushed
        aside (it is what keeps an emulated status honest), so the tag badge is the one that
        elides — or disappears, when the band has no room left for it.
        """
        collapsed = bool(getattr(self.data, "collapsed", False))
        try:
            reserved = self._apply_demo_badge(collapsed)
            self._apply_env_badge(self._current_width, reserved)
        except RuntimeError:
            pass  # Qt teardown — the items are already destroyed

    @property
    def status_emulated(self) -> bool:
        """v1.5: is the shown status an EMULATED (demo) one? Never true for a probe."""
        return bool(self._status_emulated)

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 5): re-apply every theme-dependent brush/pen.

        The colours this card paints with are read live (`ThemeColor` /
        `ThemeMap` descriptors), but a QBrush/QPen handed to a child item is a
        VALUE — it keeps what it was given, and a QGraphicsItem does not repaint
        itself just because a colour moved. This method is the one place that
        rebuilds those values; `MainWindow.apply_theme()` reaches every card
        through the scene. The status/SSH dots return to their current STATE
        (idle grey, or the status colour that is showing), never to a stale one.

        v1.6 (ROADMAP task 2): the CARD DENSITY rides the same walk — `sync_density()`
        re-lays the card out when the mode moved, before the brushes are re-applied
        (so a card switched to `compact` repaints in one pass).
        """
        self.sync_density()
        self._bg.setBrush(QBrush(self.COLOR_BG))
        self._pulse.setPen(QPen(self.STATUS_COLORS.get("offline", self.COLOR_BORDER), 3))
        self._icon.setPen(QPen(self.COLOR_BORDER, 2))
        # v1.5.6 (ROADMAP task 3): the icon's BRUSH is the environment tone — a value like
        # every other brush, so the switch re-resolves it (and the tag's own tone with it).
        self._apply_env_icon()
        _glyph_pen = QPen(self.COLOR_TEXT, 1.6)
        _glyph_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._glyph.setPen(_glyph_pen)
        self._alias.setDefaultTextColor(self.COLOR_TEXT)
        # v1.5.3 (ROADMAP task 1): the info plaque's tone is the card's STATE (the idle tone
        # once the facts are old) — a switch re-reads it through the same helper.
        self._apply_info_tone()
        self._host_label.setDefaultTextColor(QColor(theme.DOT_IDLE))
        _info_bg_color = QColor(theme.WINDOW_BG)
        _info_bg_color.setAlpha(150)
        self._info_bg.setBrush(QBrush(_info_bg_color))
        self._chevron.setPen(QPen(self.COLOR_LABEL, 1.8))
        # The dots keep their STATE: the status dot shows the status colour (the
        # idle grey when unchecked) and its DECLARED shape (v1.5rc2), the SSH dot
        # the connection state.
        self._apply_status_dot()
        self._ssh_status.setBrush(QBrush(self.COLOR_DOT_IDLE))
        self._apply_visual_state()
        # v1.5: the two badges are VALUES too (a chip brush/pen and an ink brush) — a
        # theme switch re-resolves both, including the tag colour of the environment chip
        # (`ServerNode.tag_color` reads the ACTIVE theme's tag maps).
        self._apply_badges()
        # The halo is a pixmap of one size and a neutral black layer — it has no
        # theme colour, but the cache is dropped with the switch so a caller that
        # wants a themed shadow later starts from a clean slate.
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

    # ── v1.5rc2 (ROADMAP task 2): the availability mark is a SHAPE ────────────────

    def _status_dot_path(self) -> QPainterPath:
        """The path of the availability mark for the CURRENT status.

        The shape comes from the declaration (`theme.STATUS_SHAPES` through
        `ui/status_shape.py`); an unchecked/unknown status gets the plain dot in the
        idle grey. The box keeps the local anchor of the v1.4.x `QGraphicsEllipseItem`
        (`rect = (0, 23, 14, 14)` + the two `setPos` calls of the expanded/collapsed
        layouts), so both layouts are untouched by the change of the item type.
        """
        size = float(self.STATUS_DOT_SIZE)
        if status_shape is not None:
            path = status_shape.shape_path(self._status, size)
        else:  # the flat-layout fallback: the round dot of v1.4.x
            path = QPainterPath()
            path.addEllipse(QRectF(0.0, 0.0, size, size))
        path.translate(0.0, 23.0)
        return path

    def _apply_status_dot(self):
        """Rebuild the mark: its SHAPE follows the status, its brush keeps the status colour.

        v1.5rc3 (ROADMAP task 3): a STALE datum keeps the DECLARED SHAPE of its status but
        is painted in the idle tone — the mark that means "no fresh information" (the same
        tone an unchecked card carries). The status itself is untouched, so the frame of
        the card keeps the online/warn/offline colour: the user sees WHAT was measured and
        that the measurement is old, in two channels, exactly as v1.5rc2 arranged them.
        """
        try:
            self._status_dot.setPath(self._status_dot_path())
        except RuntimeError:
            return  # Qt teardown — the item is already destroyed
        if self._stale and self._status:
            self._status_dot.setBrush(QBrush(self.COLOR_DOT_IDLE))
        else:
            self._status_dot.setBrush(
                QBrush(self.STATUS_COLORS.get(self._status, self.COLOR_DOT_IDLE)))

    # ── v1.5rc3 (ROADMAP task 3): how old the datum is ───────────────────────────

    def set_checked_at(self, timestamp: float, stale_after: float = 0.0) -> None:
        """Record WHEN this card's status was determined (epoch seconds) + the threshold.

        The window calls this with `StatusChecker.last_checked_at()` /
        `stale_threshold_s()` right after the status arrives, and `refresh_freshness()`
        again from its freshness tick. `timestamp <= 0` means "never checked" (the idle
        card). Never raises — a repaint is cosmetic.

        v1.5 (ROADMAP): an EMULATED status is not the result of a probe, so it can never
        carry an age — the timestamp is refused here (ONE place) and the freshness line
        stays empty, which is what keeps the demo from claiming a measurement.
        """
        if self._status_emulated:
            timestamp = 0.0
        try:
            self._checked_at = float(timestamp or 0.0)
        except (TypeError, ValueError):
            self._checked_at = 0.0
        try:
            self._stale_after = max(float(stale_after or 0.0), 0.0)
        except (TypeError, ValueError):
            self._stale_after = 0.0
        self.refresh_freshness()

    def refresh_freshness(self, now: float = None) -> bool:
        """Recompute the stale mark and the tooltip from the stored timestamp.

        Returns True when the STALE state changed (the topical test's seam). The
        threshold is the window's decision (`StatusChecker.stale_threshold_s()`), not a
        number invented here; a card that was never checked is never stale — it has no
        datum to be old. Called by the window's freshness tick and by `set_status`.

        v1.5: an EMULATED status is never stale either — there is no datum to age.
        """
        moment = time.time() if now is None else float(now)
        stale = bool(self._status) and not self._status_emulated \
            and self._checked_at > 0.0 \
            and self._stale_after > 0.0 and (moment - self._checked_at) > self._stale_after
        changed = (stale != self._stale)
        self._stale = stale
        if self._status:
            self._apply_status_dot()
            self._apply_status_tooltip(self._status)
        return changed

    @property
    def is_stale(self) -> bool:
        """v1.5rc3: the shown status is older than the threshold ("" status — False)."""
        return bool(self._stale)

    @property
    def status_checked_at(self) -> float:
        """v1.5rc3: epoch seconds of the shown status (0.0 — never checked)."""
        return float(self._checked_at)

    def freshness_text(self, now: float = None) -> str:
        """The "checked N min ago" line ("" when the card was never checked).

        Built here — not by the window — because it describes THIS card's datum; the
        i18n keys are `node.status.checked_now` / `node.status.checked_ago` ({minutes}).

        v1.5 (ROADMAP): an EMULATED status answers "" — an age would be a lie about a
        probe that never happened (the demo map's RFC 5737 addresses are never probed).
        """
        if self._checked_at <= 0.0 or self._status_emulated:
            return ""
        moment = time.time() if now is None else float(now)
        age = max(0.0, moment - self._checked_at)
        minutes = int(age // 60.0)
        if minutes < 1:
            return _t("node.status.checked_now")
        return _t("node.status.checked_ago", minutes=minutes)

    # ── v1.5.3 (ROADMAP task 1): how old the COLLECTED FACTS are ─────────────────

    def set_info_collected_at(self, timestamp) -> bool:
        """Record WHEN this card's collected facts were measured (epoch seconds).

        The window calls this with `data.info_collected_at` right after a collection and
        from its freshness tick; `0.0` (a missing / refused value) means "not dated" and
        clears the mark. Returns True when the STALE state changed (the topical test's
        seam). Never raises — a repaint is cosmetic.
        """
        try:
            moment = float(timestamp or 0.0)
        except (TypeError, ValueError):
            moment = 0.0
        self._info_at = moment if moment > 0.0 else 0.0
        return self.refresh_info_freshness()

    def refresh_info_freshness(self, now: float = None) -> bool:
        """Recompute the info mark + the plaque tooltip from the stored timestamp.

        The IDLE TONE is the whole mark (the v1.5rc3 pattern): no colour is invented, no
        value is rewritten and no geometry changes. A card that was never collected is
        never stale — there is no datum to age.
        """
        moment = time.time() if now is None else float(now)
        stale = bool(self._info_at > 0.0) \
            and (moment - self._info_at) > float(self.INFO_STALE_AFTER_SEC)
        changed = (stale != self._info_stale)
        self._info_stale = stale
        self._apply_info_tone()
        self._apply_info_tooltip()
        return changed

    @property
    def is_info_stale(self) -> bool:
        """v1.5.3: the collected facts are older than `INFO_STALE_AFTER_SEC`."""
        return bool(self._info_stale)

    @property
    def info_collected_at(self) -> float:
        """v1.5.3: epoch seconds of the collected facts (0.0 — never collected)."""
        return float(self._info_at)

    def info_freshness_text(self, now: float = None) -> str:
        """"collected … ago" — the age line of the info plaque ("" when not dated).

        Built here, not by the window, because it describes THIS card's datum (the
        `freshness_text()` rule of v1.5rc3). Three granularities on purpose: minutes for
        "just did it", hours for today, days for the fact that has become a memory
        (`node.info.collected_now` / `.min` / `.hours` / `.days`). The values are never
        touched — the sentence is a LABEL on them.
        """
        if self._info_at <= 0.0:
            return ""
        moment = time.time() if now is None else float(now)
        age = max(0.0, moment - self._info_at)
        if age < 60.0:
            return _t("node.info.collected_now")
        minutes = int(age // 60.0)
        if minutes < 60:
            return _t("node.info.collected_min", minutes=minutes)
        hours = int(age // 3600.0)
        if hours < 48:
            return _t("node.info.collected_hours", hours=hours)
        return _t("node.info.collected_days", days=int(age // 86400.0))

    def _apply_info_tone(self):
        """Paint the info plaque's text in the idle tone once the facts are old.

        The v1.5rc3 mark is the SAME channel for both families: the idle grey says "this
        is not current" while every value stays exactly where it was. A dead C++ object
        (Qt teardown) is a silent no-op.
        """
        try:
            self._info.setDefaultTextColor(
                self.COLOR_DOT_IDLE if self._info_stale else self.COLOR_LABEL)
        except RuntimeError:
            pass  # Qt teardown — the item is already destroyed

    def _apply_info_tooltip(self):
        """Compose the plaque tooltip: the full text (when it was elided) + the age line.

        The plaque's tooltip is the one place that already answers "what is written here"
        (the elided full line), so the age joins it instead of opening a second home; a
        non-elided, undated plaque keeps an empty tooltip exactly as before v1.5.3.
        """
        lines = []
        if self._info_tip_full:
            lines.append(self._info_tip_full)
        age = self.info_freshness_text()
        if age:
            lines.append(age)
        try:
            self._info.setToolTip("\n".join(lines))
        except RuntimeError:
            pass  # Qt teardown — see _apply_info_tone

    # ── v1.5.3 (ROADMAP task 3): why the status is what it is ────────────────────

    def set_status_report(self, text: str) -> None:
        """Attach the sentence of the last on-demand reachability report to the card.

        It rides the STATUS tooltip (below the plugin detail and the age) and is cleared by
        a NEW probe result: an explanation describes one state, and once the state changed
        the old explanation would be a claim about a measurement that no longer holds.
        """
        self._status_report = str(text or "")
        if self._status:
            self._apply_status_tooltip(self._status)

    @property
    def status_report(self) -> str:
        """v1.5.3: the last reachability report of this card ("" — none was asked)."""
        return self._status_report

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
        # v1.6 (ROADMAP task 2): the compact density — the alias, the host and the marks,
        # no info plaque and no tag chip. A per-node COLLAPSE wins over the density: it is
        # the user's own single-card choice (a view state, §4.2).
        if self._is_compact():
            self._update_appearance_compact()
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
        # v1.5.3 (ROADMAP task 1): the tooltip is COMPOSED in ONE place (_apply_info_tooltip) —
        # the full text when it was elided, plus the age of the datum.
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
            self._info_tip_full = "\n".join(info_lines) if any_elided else ""
        else:
            self._info_tip_full = ""
        self._apply_info_tone()
        self._apply_info_tooltip()

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
        # v1.5: the environment badge sits in the free band of THIS width (never in the
        # width formula — it elides to the band instead of stretching the card)
        self._apply_badges()
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

    # ── v1.6 (ROADMAP task 2): the CARD DENSITY ─────────────────────────────────

    def _is_compact(self) -> bool:
        """Is the ACTIVE card density the compact one? (read live, never cached)"""
        try:
            return theme.card_density() == theme.DENSITY_COMPACT
        except Exception:  # noqa: BLE001 — an unknown density means the historical card
            return False

    def density(self) -> str:
        """The density this card is laid out with (the topical gate's seam)."""
        return self._density

    def sync_density(self) -> bool:
        """Re-lay the card out when the ACTIVE density changed (v1.6, task 2).

        Returns True when it really rebuilt. Called from `refresh_theme()` — the ONE walk
        a density switch travels (`MainWindow.apply_theme()` → `MapScene.refresh_theme()`
        → every card), which is why the settings hub applies the choice through the
        ordinary theme signal instead of a private mechanism.
        """
        try:
            current = theme.card_density()
        except Exception:  # noqa: BLE001
            return False
        if current == self._density:
            return False
        self._density = current
        self.update_appearance()
        return True

    def is_compact_layout(self) -> bool:
        """True while the card is really painted in the compact layout (not collapsed)."""
        return bool(not getattr(self.data, "collapsed", False) and self._is_compact())

    def _clamp_width(self, width) -> int:
        """The card width inside [MIN_NODE_WIDTH, MAX_NODE_WIDTH] (ONE clamp for both modes)."""
        return min(max(int(width), self.MIN_NODE_WIDTH), int(self.MAX_NODE_WIDTH))

    def _show_compact(self):
        """The compact layout's item visibility and base positions (v1.6).

        The info plaque disappears (the field is not painted at all), the host stays under
        the alias and the two text items return to the expanded positions and font — the
        compact card is an EXPANDED card without the info block and without the tag chip,
        never a collapsed one (the alias and the host stay on their own lines).
        """
        self._info.hide()
        self._info_bg.hide()
        self._host_label.show()
        self._alias.setPos(55, 18)
        self._icon.setPos(0, 0)
        self._glyph.setPos(0, 0)
        if hasattr(self, "_alias_font_expanded"):
            self._alias.setFont(QFont(self._alias_font_expanded))

    def _update_appearance_compact(self):
        """The COMPACT card: alias, host and the status marks — no info plaque (v1.6, task 2).

        Why it is a mode of its own instead of "hide two items": the WIDTH of a card is
        computed from its content (the longest info line stretches it), so a dense map
        needs the info block to leave the measurement as well as the paint. The measured
        HEIGHT formula of the expanded card (`58 + info + 12`) holds here with an EMPTY
        info block — one `58 + 0 + 12` against the same `MIN_NODE_HEIGHT` floor — and the
        FREE BAND rule is untouched: a badge never enters the height.
        """
        self._show_compact()
        self._info_tip_full = ""
        self._apply_info_tooltip()

        alias_text = self.data.alias or "Unnamed"
        host_text = f"@{self.data.host}"
        fm_alias = QFontMetrics(self._alias.font())
        fm_host = QFontMetrics(self._host_label.font())
        self._alias.setPlainText(alias_text)
        self._host_label.setPlainText(host_text)
        overhead = max(0.0, self._alias.boundingRect().width()
                       - fm_alias.horizontalAdvance(alias_text))
        alias_right = self._alias.pos().x() + self._alias.boundingRect().width()
        host_right = self._host_label.pos().x() + self._host_label.boundingRect().width()
        width = self._clamp_width(max(alias_right, host_right) + 24)
        label_max = max(int(width - self.LABEL_X - self.DOT_ZONE_LEFT - self.ELIDE_GAP - overhead), 1)

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

        needed_height = 58 + 0 + 12          # the SAME formula with an empty info block
        self._set_geometry(width, max(int(needed_height), self.MIN_NODE_HEIGHT))

        self._status_dot.setPos(self._current_width - 46, 23)
        self._ssh_status.setPos(self._current_width - 24, 23)
        self._chevron.setPath(self._chevron_path(down=False))
        # The EMULATED marker stays (honesty is not a density), the tag chip is hidden
        # by `_apply_env_badge()` itself — one rule, wherever the badges are re-placed.
        self._apply_badges()
        self._apply_visual_state()
        if self.scene():
            self.scene().update_connections_for_node(self)

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
        # v1.5: the ENVIRONMENT chip is HIDDEN in the single-line layout (its band belongs to
        # the expanded card; the alias line carries the icon's tone instead), the EMULATED
        # marker follows the raised marks of that line
        self._apply_badges()
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

    def set_status(self, status: str, detail: str = "", emulated: bool = False):
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

        v1.5 (ROADMAP): `emulated` marks a status the DEMO MAP declared instead of
        measuring (`storage/example_project.DEMO_STATUSES`). An emulated status is drawn
        exactly like a real one — the same colour, the same declared shape — and is
        MARKED as emulated (the badge, the tooltip) and stripped of any age. ANY ordinary
        `set_status()` call clears the flag, so a probe result replaces an emulation and
        the marker goes with it; the project format still carries no status field at all.
        """
        if status not in self.STATUS_COLORS:
            return
        detail = str(detail or "")
        emulated = bool(emulated)
        if status == self._status:
            if detail != self._status_detail or emulated != self._status_emulated:
                self._status_detail = detail
                self._status_emulated = emulated
                self._apply_status_tooltip(status)
                self._apply_badges()
            return
        color = self.STATUS_COLORS[status]
        self._status = status
        self._status_detail = detail
        self._status_emulated = emulated
        # v1.5rc3: a NEW result is fresh by definition — the window refines this with
        # `set_checked_at()` immediately after (the timestamp of the round that produced
        # it); clearing it here keeps the mark honest for a caller that pushes a status
        # without one (a test, a plugin-driven path). v1.5: an emulated status refuses the
        # timestamp altogether (`set_checked_at`).
        self._checked_at = 0.0
        self._stale = False
        # v1.5.3 (ROADMAP task 3): a NEW status invalidates the old explanation — the
        # on-demand report described the state that just changed ("why is it red?" answered
        # for a card that is now green would be a stale claim about the present).
        self._status_report = ""

        self._apply_status_tooltip(status)

        # UI polish: the availability dot (reads faster than the frame at a small zoom)
        # + dimming the card content for offline nodes.
        # v1.5rc2: the mark is the DECLARED shape of this status (dot / ring / triangle).
        self._apply_status_dot()
        self._apply_content_opacity()
        # v1.5: the emulated marker belongs to the status that just arrived
        self._apply_badges()

        # Static frame + pulse (overlay fade-out: opacity 1 -> 0)
        self._apply_visual_state()
        self._start_pulse(color)
        self._notify_group_aggregate()

    def _notify_group_aggregate(self) -> None:
        """v1.5.4 (ROADMAP task 1): tell the MAP that this card's status changed.

        A group paints an AGGREGATE of its members (the worst status + the counts) and
        reads the values LIVE at paint time, so the only thing a status change needs is a
        repaint of the groups that hold the card. Asking the scene HERE — not at the
        window's status slot — is what makes every path behave the same: a probe result,
        an emulated demo status, a `reset_status()` after editing the host and a test
        fixture all end in `set_status`/`reset_status`. The `itemChange` hook already
        talks to the scene the same way (the geometric membership). Never raises.
        """
        try:
            scene = self.scene()
            hook = getattr(scene, "refresh_group_aggregates", None)
            if scene is not None and callable(hook):
                hook(self)
        except (AttributeError, RuntimeError):
            pass  # no scene yet / Qt teardown — the aggregate is cosmetic

    def _apply_status_tooltip(self, status: str):
        """v0.7.1/v1.4rc2/v1.5rc3/v1.5: the status tooltip — the plugin detail and the AGE.

        Lines, in order: the status sentence (`node.status.*` with the host), the plugin
        detail of a merged probe result (v1.4rc2) and the freshness line (v1.5rc3 —
        "checked 3 min ago"), so the tooltip answers "what is it" AND "how old is that".
        v1.5: an EMULATED status replaces the age line with the marker that NAMES the
        emulation — there is no probe behind it to date.
        """
        try:
            from i18n import t as _translate
            tip = _translate(f"node.status.{status}", host=self.data.host or "")
        except Exception:
            tip = f"{status}: {self.data.host}"
        if tip.startswith("["):  # i18n unavailable — the English literal of en.json
            tip = f"{status} — {self.data.host}"
        lines = [tip]
        if self._status_detail:
            lines.append(self._status_detail)
        if self._status_emulated:
            # The marker alone would be terse in a tooltip; the window's own title names the
            # map it belongs to, so the line composes the two EXISTING keys (no extra string).
            lines.append(_t("node.status.emulated") + " — " + _t("title.example"))
        else:
            age = self.freshness_text()
            if age:
                lines.append(age)
        # v1.5.3 (ROADMAP task 3): the "why" of this status — the last on-demand
        # reachability report. It joins the tooltip the status already owns (ONE home per
        # fact) and is dropped by the next probe result, which speaks about a NEW state.
        if self._status_report:
            lines.append(self._status_report)
        self.setToolTip("\n".join(lines))

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
        # v1.5rc3: so does the AGE — a new host/port has never been probed
        self._checked_at = 0.0
        self._stale = False
        # v1.5: and the EMULATED marker — the emulation is a property of the status
        self._status_emulated = False
        # v1.5.3 (ROADMAP task 3): the reachability report explained THIS status — it goes
        # with it (a new host/port has never been diagnosed).
        self._status_report = ""
        self.setToolTip("")
        # UI polish: the dot — gray (not checked), the content — full brightness
        # (v1.5rc2: the mark returns to the plain dot of an unchecked status)
        self._apply_status_dot()
        self._apply_content_opacity()
        self._apply_badges()
        self._apply_visual_state()
        # v1.5.4 (ROADMAP task 1): the card left every aggregate it belonged to
        self._notify_group_aggregate()

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
