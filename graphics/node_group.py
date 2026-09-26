"""Node grouping (v0.8.1): a cluster/folder on the map.

v1.5.4 (ROADMAP task 1) — THE GROUP ANSWERS "WHERE IS THE PROBLEM". A group used to
know only `member_count()`: a frame around twenty cards said nothing about them, so a
red card inside a folded group was invisible. The group now carries an AGGREGATE of its
members' availability — the WORST status plus the counts — painted on the title band of
the frame (which the FOLD keeps: folding re-fits the frame, it does not remove the band)
and in the group's tooltip. The vocabulary of severity lives HERE (`STATUS_SEVERITY` /
`PROBLEM_STATUSES`, `worst_status()` / `aggregate_status()` / `is_in_trouble()`), because
the aggregate and the "problems only" lens of the same release must mean the same thing
by ONE declaration.

The aggregate is a VIEW FACT and is never serialized: `to_dict()` still writes only
`{id, name, x, y, width, height}` (+ the optional fold keys), and every value is read
LIVE from the members at paint time — a probe round changes a card and the next repaint
of its group tells the truth (`MapScene.refresh_group_aggregates()` is the nudge).

A group — a labeled rectangular area UNDER the nodes and arrows (z = Z_VALUE,
the lowest: the map's "background" zone). The gestures — as in StickyNote
(manual mouse handling, ItemIsMovable is NOT set — see the sticky_note.py
docstring about ScrollHandDrag):

    drag  — by any point of the frame it moves the group; ALL members are shifted
            by the same delta (task v0.8.1 #2: "the servers inside a group move
            automatically when the group boundary changes");
    resize — by the bottom-right corner (CORNER_HIT px): the members are repositioned
            proportionally to the new size and clamped inside the frame;
    a double click on the top band (TITLE_ZONE_H) — the renameRequested signal →
            the rename dialog in MainWindow.

Membership is geometric: a server center inside the TOPMOST group → it is its member
(MapScene.resync_group_members() recomputes on any move/resize).
That is why the JSON (the "groups" array) stores only {id, name, x, y, width, height} —
membership is not serialized and is restored from the geometry on load.

QGraphicsObject (not QGraphicsItem) — per the v0.8.1 spec: the signals
(moved/resized/titleChanged/membershipChanged/renameRequested) are needed, which
MainWindow turns into the project dirty marker, as with the notes.
"""
import uuid
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QFontMetrics,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.5.4 (ROADMAP task 1): the DECLARED status shapes — the mark of the aggregate
    from ..ui import status_shape
except ImportError:
    try:
        from ui import status_shape
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        status_shape = None


def _tint(hex_color: str, alpha: int) -> "QColor":
    """v1.2.5: a central theme color with opacity (the group fills)."""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the ui/empty_state.py pattern): the key itself without i18n."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break a paint
        return key


# ── v1.5.4 (ROADMAP task 1): the DECLARED severity of an availability status ──────
# The group aggregate and the "problems only" lens of the SAME release answer one
# question ("what needs attention here?") and therefore share ONE declaration: the
# severity order is ASCENDING (the LAST entry is the worst) and `PROBLEM_STATUSES`
# names what "in trouble" means. A status outside the tuple is not a datum at all —
# a card that was never probed carries "" and neither wins the aggregate nor counts.
STATUS_SEVERITY = ("online", "warn", "offline")
PROBLEM_STATUSES = ("warn", "offline")


def worst_status(statuses) -> str:
    """The WORST declared status among ``statuses`` ("" — none of them has one).

    The pick follows `STATUS_SEVERITY`, never the order of the members: an offline
    card wins over a warn one wherever the two sit in the iteration, which is what
    makes the aggregate of a group independent of its composition order.
    """
    worst = ""
    rank = -1
    for status in statuses or ():
        text = str(status or "")
        if text not in STATUS_SEVERITY:
            continue
        value = STATUS_SEVERITY.index(text)
        if value > rank:
            rank, worst = value, text
    return worst


def aggregate_status(statuses) -> dict:
    """The aggregate of a set of availability statuses — a PURE summary (v1.5.4).

    Returns ``{"worst": str, "counts": {status: n}, "total": int, "members": int}``: the
    worst declared status ("" when no member carries one), a count per DECLARED status,
    the number of members that really have a status and the number of MEMBERS. The two
    last numbers are deliberately separate — "a group with no members" and "a group whose
    members were never probed" are different facts and the caption says so
    (`group.status.empty` vs `group.status.unchecked`); an unchecked member is absent
    from `counts`/`total`, the "a filter is a view, not a fact" discipline.
    """
    values = [str(status or "") for status in (statuses or ())]
    counts = {status: 0 for status in STATUS_SEVERITY}
    total = 0
    for text in values:
        if text in counts:
            counts[text] += 1
            total += 1
    return {"worst": worst_status(values), "counts": counts, "total": total,
            "members": len(values)}


def is_in_trouble(status, stale: bool = False) -> bool:
    """Does this card need attention? — the ONE predicate of the release (v1.5.4).

    `warn` / `offline`, or a status whose datum has grown STALE (a result nothing
    refreshed is exactly the "the map is lying to me" case the lens exists for). An
    UNCHECKED card is deliberately not trouble: there is no measurement to call a
    problem, and dimming "never probed" as an incident would be a false alarm. The
    predicate is pure, so the topical test pins it without a window.
    """
    return bool(stale) or str(status or "") in PROBLEM_STATUSES


def status_caption(summary, translate=None) -> str:
    """The aggregate as ONE line of words (v1.5.4) — the plaque and the tooltip text.

    Composed, not declared as a sentence: the COUNTS are numbers and the status WORDS
    are the existing `legend.status.*` keys (there is no fourth spelling of
    online/warn/offline in this application). The rules, in order:

      * no member at all → `group.status.empty` ("an empty group says so");
      * members that were never checked → `group.status.unchecked` (an untouched group
        must not be dressed up as an incident);
      * otherwise the PROBLEMS, worst first (`Offline 2 · Warn 1`) — and when there
        is no problem at all, the healthy count (`Online 5`), so a fully green group
        still says how many cards answered.

    `translate` is injectable for the pure test (it defaults to the i18n hook).
    """
    t = translate if callable(translate) else _t
    data = summary or {}
    counts = data.get("counts") or {}
    try:
        members = int(data.get("members", data.get("total") or 0))
    except (TypeError, ValueError):
        members = 0
    if members <= 0:
        return t("group.status.empty")
    worst = str(data.get("worst") or "")
    if not worst:
        return t("group.status.unchecked")
    parts = []
    for status in ("offline", "warn"):
        try:
            count = int(counts.get(status) or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            word = t(f"legend.status.{status}")
            parts.append(f"{word} {count}")
    if not parts:
        try:
            count = int(counts.get("online") or 0)
        except (TypeError, ValueError):
            count = 0
        parts.append(f"{t('legend.status.online')} {count}")
    return " · ".join(parts)


# ── v1.6 (ROADMAP task 6): the auto-arrangement of a group's members ─────────────
# The geometry is a PURE function (the `sidebar.list_sort_key()` precedent): the layout
# of a group is measured without a widget, so the topical gate can pin every mode and
# the window only has to turn the answer into ONE undo command. The three modes are the
# plan's: a vertical line, a horizontal line, and rows whose COUNT the user types.
ARRANGE_VERTICAL = "vertical"
ARRANGE_HORIZONTAL = "horizontal"
ARRANGE_ROWS = "rows"
ARRANGE_MODES = (ARRANGE_VERTICAL, ARRANGE_HORIZONTAL, ARRANGE_ROWS)
#: The air between two cards of an arrangement (scene px) — the same order of magnitude
#: as the group's own MEMBER_MARGIN / BADGE_GAP, so an arranged group still reads as one.
ARRANGE_GAP = 24.0


def resolve_arrange_mode(value) -> str:
    """A stored/dialog mode id → one of ``ARRANGE_MODES`` (a broken value = vertical)."""
    text = str(value or "").strip().lower()
    return text if text in ARRANGE_MODES else ARRANGE_VERTICAL


def arrange_positions(items, mode: str, per_line: int = 0,
                      gap: float = ARRANGE_GAP, origin=None) -> list:
    """The target positions of an arrangement — PURE (no Qt item, no scene).

    ``items`` is an iterable of ``(key, x, y, width, height)`` — the KEY is whatever the
    caller wants back (a node id in the application), the rest is the card's geometry in
    scene coordinates. The result is a list of ``(key, x, y)`` in the SAME order, i.e.
    the reading order the caller handed over (the group's grid order: alias, then id).

    The three modes:

      * ``vertical``   — one column at the left edge of the bounding box;
      * ``horizontal`` — one row at the top edge;
      * ``rows``       — ``per_line`` cards per row (a count below 1 means 1), the rows
                         starting at the left edge, the row height = the TALLEST card of
                         that row (an arrangement must not overlap cards of different
                         heights, and the compact density lets them differ).

    The anchor is the top-left corner of the members' own bounding box unless the caller
    passes ``origin``; the frame of the group is deliberately NOT part of the arithmetic
    — the arrangement MOVES cards and never resizes the group (the declared boundary of
    the task), and the geometric membership rule decides who stays inside.
    """
    cells = []
    for item in items or ():
        try:
            key, x, y, width, height = item[0], float(item[1]), float(item[2]), \
                float(item[3]), float(item[4])
        except (TypeError, ValueError, IndexError):
            continue  # a broken entry is skipped, the rest of the group still arranges
        cells.append((key, float(x), float(y), max(width, 1.0), max(height, 1.0)))
    if not cells:
        return []
    if origin is None:
        base_x = min(cell[1] for cell in cells)
        base_y = min(cell[2] for cell in cells)
    else:
        try:
            base_x, base_y = float(origin[0]), float(origin[1])
        except (TypeError, ValueError, IndexError):
            base_x = min(cell[1] for cell in cells)
            base_y = min(cell[2] for cell in cells)

    step = max(float(gap if gap is not None else ARRANGE_GAP), 0.0)
    resolved = resolve_arrange_mode(mode)
    positions = []
    if resolved == ARRANGE_VERTICAL:
        y = base_y
        for key, _x, _y, _w, height in cells:
            positions.append((key, base_x, y))
            y += height + step
        return positions
    if resolved == ARRANGE_HORIZONTAL:
        x = base_x
        for key, _x, _y, width, _h in cells:
            positions.append((key, x, base_y))
            x += width + step
        return positions
    # rows
    try:
        columns = max(int(per_line or 0), 1)
    except (TypeError, ValueError):
        columns = 1
    x = base_x
    y = base_y
    row_height = 0.0
    column = 0
    for key, _x, _y, width, height in cells:
        positions.append((key, x, y))
        row_height = max(row_height, height)
        column += 1
        if column >= columns:
            x = base_x
            y += row_height + step
            row_height = 0.0
            column = 0
        else:
            x += width + step
    return positions


class NodeGroup(QGraphicsObject):
    """A cluster/folder on the map: a frame + a title, drag/resize, server membership.

    **v1.4.2 (ROADMAP task 5) — the FOLD.** A chevron in the title band (and a
    context-menu pair of the window) folds the group: every member card becomes its
    v0.8.4 BADGE and the badges are laid out in a grid inside the frame, which is then
    re-fitted to the grid. Unfolding restores the frame size, every member's position
    and its previous badge flag from the snapshot taken at the fold. While folded the
    members are NOT draggable (a folded group is a summary view; a manual move would be
    undone by the very next unfold) — the GROUP still drags as a whole, and a corner
    resize re-lays the badges out instead of scaling them.

    The state is PERSISTED (`collapsed` + `expanded_width`/`expanded_height`, written
    only while folded) and travels through `CmdToggleGroupCollapse` as one undo step —
    the fold moves real node positions, so it is not a pure view state like the per-node
    collapse. Known limitation: after a save+reload the pre-fold CARD arrangement is
    gone (the folded grid is what was saved); unfolding then restores the frame size and
    un-badges the members where they lie.
    """

    Z_VALUE = -5.0     # below the nodes (z=0) and the arrows (z=-2) — the map's "background" zone
    MIN_W, MIN_H = 160.0, 100.0
    MAX_W, MAX_H = 2400.0, 1600.0
    DEFAULT_W, DEFAULT_H = 480.0, 320.0

    CORNER_HIT = 18.0      # "grab the corner" zone for resize (px from the bottom-right, as with the notes)
    TITLE_ZONE_H = 28.0    # the top band: a double click — rename
    MEMBER_MARGIN = 8.0    # the minimum inset of the members from the frame when clamping on resize
    # v1.4.2: the fold (the grid of badges + the chevron's click zone in the title band)
    BADGE_GAP = 8.0        # the gap between two badges of a folded group
    CHEVRON_ZONE = 26.0    # the chevron's click zone in the RIGHT corner of the title band
    # v1.5.4 (ROADMAP task 1): the aggregate plaque of the title band — the worst
    # member status as a SHAPE + the counts as words. A fixed slot at the right end of
    # the band (before the chevron), so the title elides into what is left instead of
    # fighting it; `AGGREGATE_MIN_SPAN` is the room below which the plaque is dropped
    # entirely (a two-character group on a 160 px frame has no room for a second text).
    AGGREGATE_MARK = 10.0
    AGGREGATE_GAP = 5.0
    AGGREGATE_RIGHT_PAD = 6.0
    AGGREGATE_MIN_SPAN = 46.0

    CORNER_RADIUS = theme.RADIUS_GROUP   # rounding of the frame (in one style with the node card)

    # v1.2.5: colors — from the central theme (ui/theme.py); values unchanged.
    # v1.4.3 (ROADMAP task 5): LIVE descriptors / lazily computed values — a
    # class read resolves the ACTIVE theme on every access, and the group's own
    # `refresh_theme()` re-runs `paint()` through `update()`.
    COLOR_BORDER = theme.ThemeColor("group_border")    # violet-600 — distinct from the nodes' blue
    COLOR_HOVER = theme.ThemeColor("group_hover")      # violet-400
    COLOR_SELECTED = theme.ThemeColor("selection_amber")  # the same amber as the node selection (a single palette)
    # The fills are the frame colours with alpha — computed lazily from the
    # ACTIVE theme (a nearly transparent fill: the grid shows through).
    COLOR_FILL = theme.ThemeValue(lambda: _tint(theme.GROUP_BORDER, 16))
    COLOR_FILL_HOVER = theme.ThemeValue(lambda: _tint(theme.GROUP_BORDER, 28))
    COLOR_FILL_SELECTED = theme.ThemeValue(lambda: _tint(theme.SELECTION_AMBER, 20))
    COLOR_TITLE = theme.ThemeColor("group_title")      # violet-300 — reads on the dark map

    moved = Signal()               # the group was moved (a dirty reason for MainWindow)
    resized = Signal()             # the size changed (a corner drag or set_group_size)
    titleChanged = Signal(str)     # the title was renamed (the new name — the argument)
    membershipChanged = Signal()   # the member composition changed (a user dragged a node into/out of the group)
    renameRequested = Signal()     # a double click on the title → MainWindow opens the dialog
    # v1.4.2: a click on the fold chevron → MainWindow pushes CmdToggleGroupCollapse (the
    # group never mutates itself — the same "ask, do not act" split as renameRequested)
    collapseRequested = Signal()
    # v1.4.2: the folded state changed (the dirty marker — the fold is persisted)
    collapsedChanged = Signal(bool)
    # v0.8.3-audit (#6): completed gestures — for the undo commands (the node_drag_committed pattern)
    moveCommitted = Signal(object, object)   # (the old position as a QPointF, the new one)
    resizeCommitted = Signal(float, float, float, float)  # (w0, h0, w1, h1)

    def __init__(self, x: float = 0.0, y: float = 0.0, width: Optional[float] = None,
                 height: Optional[float] = None, name: str = "",
                 group_id: Optional[str] = None,
                 collapsed: bool = False,
                 expanded_width=None, expanded_height=None):
        super().__init__()

        self.group_id = (str(group_id)[:8] if group_id else "") or None
        if self.group_id is None:
            self.group_id = str(uuid.uuid4())[:8]  # the same pattern as with the notes/servers

        self._name = str(name or "").strip()
        w, h = self._clamp_size(
            width if width else self.DEFAULT_W, height if height else self.DEFAULT_H)
        self._width, self._height = float(w), float(h)

        # Members: ServerNode (NOT child QGraphicsItems — independent scene objects;
        # their data.x/data.y stay SCENE coordinates and are saved correctly in the JSON).
        self._members = set()

        # v1.4.2 (ROADMAP task 5): the fold state.
        # `_collapsed`            — the flag (persisted);
        # `_expanded_state`       — the session snapshot {node_id: (x, y, collapsed, movable)};
        # `_expanded_size`        — the frame size to return to on unfold (persisted, so a
        #                           group restored from a file can unfold sensibly);
        # `_laying_out`           — the re-entry guard of the badge grid.
        self._collapsed = bool(collapsed)
        self._expanded_state = None
        self._expanded_size = None
        # v1.4.2: the badge grid must not be re-laid out in the MIDDLE of a bulk move or
        # of an unfold — the members of a group are shifted one by one, so every
        # intermediate resync would otherwise see a half-moved composition and rewrite
        # the grid (the "a folded group drags as a whole" regression).
        self._suspend_layout = False
        if self._collapsed:
            try:
                ew = float(expanded_width)
                eh = float(expanded_height)
                if ew > 0.0 and eh > 0.0:
                    self._expanded_size = (ew, eh)
            except (TypeError, ValueError):
                self._expanded_size = None
        self._laying_out = False

        # Manual move/resize (the StickyNote pattern: otherwise ScrollHandDrag would steal the gesture)
        self._drag_mode = None        # None | "move" | "resize"
        self._drag_start_scene = None
        self._size_start = None
        # v0.8.3-audit (#6): the geometry at the start of the gesture — for moveCommitted/resizeCommitted
        self._gesture_start_pos = None    # the QPointF of the group position
        self._hover = False
        self._applying_move = False   # our own setPos in _apply_move — do not duplicate the shift in itemChange

        # ItemIsMovable is NOT set (see the module docstring); selection only.
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(self.Z_VALUE)
        self.setPos(x, y)

        self._display_name = ""
        self._update_title_text()
        # v1.4.2: a member captured while the group is folded joins the grid (a session
        # fold only — a group restored folded from a file keeps its saved arrangement)
        self.membershipChanged.connect(self._on_membership_changed)
        # v1.5.4 (ROADMAP task 1): the aggregate of the group changed with the composition
        self.membershipChanged.connect(self._on_membership_changed_aggregate)

    # ── Geometry helpers (the StickyNote/ServerNode pattern: explicit geometry) ──

    @classmethod
    def _clamp_size(cls, w: float, h: float):
        w = max(cls.MIN_W, min(cls.MAX_W, float(w)))
        h = max(cls.MIN_H, min(cls.MAX_H, float(h)))
        return w, h

    @property
    def name(self) -> str:
        """The group name (the title above the frame)."""
        return self._name

    def set_title(self, text: str):
        """Rename the group. An empty name is allowed (the title is not drawn)."""
        new = str(text or "").strip()
        if new == self._name:
            return
        self._name = new
        self._update_title_text()
        self.titleChanged.emit(new)

    def size(self):
        """Current size (w, h) in scene coordinates."""
        return float(self._width), float(self._height)

    def boundingRect(self) -> QRectF:
        """Explicit group geometry (uniform with ServerNode/StickyNote)."""
        return QRectF(0, 0, self._width, self._height)

    def shape(self) -> QPainterPath:
        """The hit area — the whole frame: a click anywhere in the zone lands on the group."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._width, self._height),
                            self.CORNER_RADIUS, self.CORNER_RADIUS)
        return path

    def _in_corner(self, local: QPointF) -> bool:
        """The bottom-right corner — the resize zone (as with the notes)."""
        return (self._width - self.CORNER_HIT <= local.x() <= self._width and
                self._height - self.CORNER_HIT <= local.y() <= self._height)

    def _in_title_zone(self, local: QPointF) -> bool:
        """The top band — the double-click zone for renaming (the chevron zone excluded)."""
        if self._in_chevron(local):
            return False  # v1.4.2: the fold chevron lives in the right corner of the band
        return 0.0 <= local.x() <= self._width and 0.0 <= local.y() <= self.TITLE_ZONE_H

    def _in_chevron(self, local: QPointF) -> bool:
        """v1.4.2: is the local point inside the fold chevron's click zone?"""
        try:
            return self.chevron_rect().contains(QPointF(local))
        except (TypeError, AttributeError):
            return False

    def chevron_rect(self) -> QRectF:
        """v1.4.2: the fold chevron's click zone — the RIGHT corner of the title band.

        The ServerNode pattern (a chevron in the top-right corner of the card), so the
        fold is discoverable without opening a menu; the same click is available as the
        `ctx.collapse_group`/`ctx.expand_group` pair of the context menu.
        """
        z = self.CHEVRON_ZONE
        return QRectF(max(self._width - z, 0.0), 0.0, z, self.TITLE_ZONE_H)

    def _chevron_path(self) -> QPainterPath:
        """The chevron glyph: ▾ while folded ("can be unfolded") / ▴ while expanded."""
        path = QPainterPath()
        cx = self._width - self.CHEVRON_ZONE / 2.0
        cy = self.TITLE_ZONE_H / 2.0
        if self._collapsed:
            path.moveTo(cx - 5.0, cy - 2.0)
            path.lineTo(cx + 5.0, cy - 2.0)
            path.lineTo(cx, cy + 4.0)
        else:
            path.moveTo(cx - 5.0, cy + 2.0)
            path.lineTo(cx + 5.0, cy + 2.0)
            path.lineTo(cx, cy - 4.0)
        path.closeSubpath()
        return path

    def set_frame_size(self, width: float, height: float, resync: bool = True) -> bool:
        """v1.4.2: set the FRAME size only — the members are NOT touched.

        The shared half of the fold (`_layout_badges` re-fits the frame around the badge
        grid) and of `set_group_size` in its folded branch; the expanded branch keeps its
        own proportional member scaling and does not come through here.
        Returns True if the size really changed. `resync=False` is for a caller that
        lays the members out itself right afterwards.
        """
        w, h = self._clamp_size(width, height)
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False
        self.prepareGeometryChange()
        self._width, self._height = float(w), float(h)
        self._update_title_text()  # the title eliding depends on the width
        if resync:
            self._resync_members()
        self.update()
        return True

    def set_group_size(self, width: float, height: float) -> bool:
        """Change the group size (clamped MIN/MAX).

        Task v0.8.1 #2: the members move automatically when the boundary changes —
        their positions are scaled proportionally to the new size (sx/sy from the
        top-left corner), then clamped inside the frame with MEMBER_MARGIN, so they
        do not "fall out" of the folder even if the group became smaller than a node.

        v1.4.2 (ROADMAP task 5): a FOLDED group is the exception — its badges are a grid,
        so a resize re-lays the grid out (the column count follows the new width) instead
        of scaling cards that are not cards at the moment.

        Returns True if the size really changed.
        """
        if self._collapsed:
            if not self.set_frame_size(width, height, resync=False):
                return False
            self._layout_badges()
            self.resized.emit()
            return True

        w, h = self._clamp_size(width, height)
        if abs(w - self._width) < 0.5 and abs(h - self._height) < 0.5:
            return False

        old_w, old_h = self._width, self._height
        sx, sy = w / old_w, h / old_h
        gpos = self.pos()

        # First OUR OWN geometry: the intermediate resyncs (from the members' setPos below)
        # will see the new frame already — the membership does not "flicker" on a group expansion.
        m = self.MEMBER_MARGIN
        self.prepareGeometryChange()
        self._width, self._height = float(w), float(h)

        for node in list(self._members):
            # v1.4.2 (ROADMAP task 4): the member geometry is its CARD rect
            # (`card_rect_scene()`), not the painted boundingRect — the drop-shadow halo
            # would otherwise shift and inflate every proportional reposition.
            r = node.card_rect_scene()  # a node — an independent scene item: scene coordinates
            lx = (r.left() - gpos.x()) * sx
            ly = (r.top() - gpos.y()) * sy
            nw, nh = r.width(), r.height()
            max_lx = max(m, w - nw - m)   # a node wider than the group → anchored at the top-left corner
            max_ly = max(m, h - nh - m)
            lx = min(max(lx, m), max_lx)
            ly = min(max(ly, m), max_ly)
            node.setPos(gpos.x() + lx, gpos.y() + ly)

        self._update_title_text()  # the title eliding depends on the width

        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()  # other nodes may have ended up under the frame / left it
        self.update()
        self.resized.emit()
        return True

    def _apply_move(self, delta: QPointF):
        """Shift the group AND all members by delta (task v0.8.1 #2 — the drag part).

        v1.4.2: the whole shift is atomic for the badge grid (`_suspend_layout`) — the
        members move one by one, and a re-layout triggered by an intermediate resync
        would fight the very move it is part of.
        """
        if abs(delta.x()) < 0.5 and abs(delta.y()) < 0.5:
            return
        self.prepareGeometryChange()
        self._applying_move = True
        self._suspend_layout = True
        try:
            self.setPos(self.pos() + delta)
            for node in list(self._members):
                # ServerNode.itemChange syncs data.x/data.y and the connection arrows by itself
                node.setPos(node.pos() + delta)
            sc = self.scene()
            if sc is not None and hasattr(sc, "resync_group_members"):
                sc.resync_group_members()  # other nodes may have ended up under the frame
        finally:
            self._suspend_layout = False
            self._applying_move = False
        self.moved.emit()

    def itemChange(self, change, value):
        """An external (programmatic) setPos — the members follow the group the same way.

        An interactive drag goes through _apply_move() with the _applying_move flag — there
        the member shift is already done manually; without the flag itemChange catches only
        programmatic moves (tests/scripts), and there is no duplication.

        As with ServerNode, the hook is called BEFORE the position is applied: the frame for
        the resync is computed from value explicitly (the moving_group override in MapScene).
        v1.4.2: the same atomicity as in _apply_move (the badge grid is not re-laid mid-move).
        """
        if change == QGraphicsItem.ItemPositionChange and not getattr(self, "_applying_move", False):
            try:
                dx = float(value.x()) - float(self.pos().x())
                dy = float(value.y()) - float(self.pos().y())
            except Exception:  # noqa: BLE001 — an unexpected value type — hand it to the standard path
                return super().itemChange(change, value)
            if abs(dx) + abs(dy) > 0.5:
                result = super().itemChange(change, value)  # accept → Qt applies the position
                self._suspend_layout = True
                try:
                    for node in list(self._members):
                        node.setPos(node.pos() + QPointF(dx, dy))
                    sc = self.scene()
                    if sc is not None and hasattr(sc, "resync_group_members"):
                        target_rect = QRectF(float(value.x()), float(value.y()),
                                             self._width, self._height)
                        sc.resync_group_members(moving_group=(self, target_rect))
                finally:
                    self._suspend_layout = False
                return result
        return super().itemChange(change, value)

    # ── Membership (ServerNode objects; exclusivity — one node in one group) ──

    def get_members(self) -> List:
        """The member list (no order guaranteed)."""
        return list(self._members)

    def member_count(self) -> int:
        return len(self._members)

    def has_member(self, node) -> bool:
        return node in self._members

    def add_member(self, node):
        """Add a member. Exclusivity: a node cannot be in two groups —
        if needed we remove it from its old one (the topmost group wins)."""
        if node is None or node in self._members:
            return
        sc = self.scene()
        if sc is not None and hasattr(sc, "_groups"):
            for other in list(sc._groups):
                if other is not self and node in other._members:
                    other.remove_member(node)  # removes the old group's membershipChanged
        self._members.add(node)
        self.membershipChanged.emit()

    def remove_member(self, node):
        """Remove a member (a no-op if it was not there)."""
        if node in self._members:
            self._members.discard(node)
            self.membershipChanged.emit()

    def clear_members(self):
        """Clear the composition with a single signal (deleting a group / rebuilding the scene)."""
        if self._members:
            self._members.clear()
            self.membershipChanged.emit()

    def refresh_aggregate(self) -> None:
        """Repaint the aggregate and refresh its words (v1.5.4) — the scene's nudge.

        Called when something the aggregate is built from has changed outside the group's
        own signals: a probe result on a member (`MapScene.refresh_group_aggregates(node)`)
        or a membership change (the group's own `membershipChanged` slot). The values are
        read live in `paint()`, so this only asks for a repaint — never raises.
        """
        try:
            self.update()
            self._apply_tooltip()
        except RuntimeError:
            pass  # Qt teardown — the item is already destroyed

    # ── v1.5.4 (ROADMAP task 1): the group AGGREGATE — "where is the problem" ────────

    def status_summary(self) -> dict:
        """The aggregate of the members' statuses, read LIVE (v1.5.4).

        Never cached: the members ARE the source of truth, so a probe result needs no
        bookkeeping in the group — only a repaint (`MapScene.refresh_group_aggregates()`
        is the nudge, and the NEXT paint reads the new values by itself).
        """
        statuses = []
        for member in list(self._members):
            statuses.append(getattr(member, "status", ""))
        return aggregate_status(statuses)

    def worst_member_status(self) -> str:
        """The worst member status ("" — no member carries one)."""
        return str(self.status_summary().get("worst") or "")

    def status_caption(self) -> str:
        """The aggregate as ONE line of words — the tooltip and the plaque text."""
        return status_caption(self.status_summary())

    def _aggregate_font(self) -> QFont:
        """The plaque's font: the group title one point smaller (a caption, not a title)."""
        return QFont(theme.FONT_UI, 8)

    def aggregate_rects(self):
        """``(mark_rect, text_rect)`` of the aggregate plaque in LOCAL coordinates.

        Both are empty when the aggregate is not painted (a frame with no room for it).
        The topical test reads this instead of re-deriving the geometry, so the paint
        and the test cannot disagree about where the mark sits.
        """
        summary = self.status_summary()
        text = self.status_caption()
        if not text:
            return QRectF(), QRectF()
        fm = QFontMetrics(self._aggregate_font())
        worst = str(summary.get("worst") or "")
        mark_w = (self.AGGREGATE_MARK + self.AGGREGATE_GAP) if worst else 0.0
        right = float(self._width) - self.CHEVRON_ZONE - self.AGGREGATE_RIGHT_PAD
        avail = right - 14.0 - mark_w
        if avail < self.AGGREGATE_MIN_SPAN:
            return QRectF(), QRectF()
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(avail))
        text_w = float(fm.horizontalAdvance(shown))
        top = 3.0
        height = self.TITLE_ZONE_H - 6.0
        text_rect = QRectF(right - text_w, top, text_w, height)
        if not worst:
            return QRectF(), text_rect
        mark_rect = QRectF(text_rect.left() - self.AGGREGATE_GAP - self.AGGREGATE_MARK,
                           top + (height - self.AGGREGATE_MARK) / 2.0,
                           self.AGGREGATE_MARK, self.AGGREGATE_MARK)
        return mark_rect, text_rect

    def _aggregate_tone(self):
        """The ink of the aggregate: the worst status' colour, or the muted tone.

        Never a new colour — the tone of the worst status is the one its own card frame
        uses (`Theme.status_colors`). A group whose members carry no status at all (or
        none at all) reads in `text_muted`, the "nothing to report" tone.
        """
        worst = self.worst_member_status()
        if worst:
            return QColor(theme.STATUS_COLORS.get(worst) or theme.TEXT_MUTED)
        return QColor(theme.TEXT_MUTED)

    def _paint_aggregate(self, painter: QPainter):
        """Paint the aggregate plaque: the declared SHAPE of the worst status + the counts.

        The second channel of the 1.5 line applied to a group: the shape comes from the
        SAME declaration the cards and the legend draw (`theme.STATUS_SHAPES` through
        `ui/status_shape.py`), the words carry the numbers and the tone repeats the
        severity. A group with no members shows the "no members" caption with no mark.
        """
        mark_rect, text_rect = self.aggregate_rects()
        text = self.status_caption()
        if not text:
            return
        worst = self.worst_member_status()
        tone = self._aggregate_tone()
        if mark_rect.width() > 0.0 and status_shape is not None:
            try:
                status_shape.paint_shape(painter, mark_rect, worst, tone)
            except Exception:  # noqa: BLE001 — a mark is cosmetic; the words stay
                pass
        fm = QFontMetrics(self._aggregate_font())
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(int(text_rect.width()), 1))
        painter.setFont(self._aggregate_font())
        painter.setPen(QPen(tone))
        painter.drawText(text_rect,
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         shown)

    # ── v1.4.2 (ROADMAP task 5): the FOLD — the members become a grid of badges ──────

    def is_collapsed(self) -> bool:
        """Is the group folded (its members shown as badges)?"""
        return bool(self._collapsed)

    @property
    def collapsed(self) -> bool:
        """The folded flag (the persisted state — `is_collapsed()` in property form)."""
        return bool(self._collapsed)

    def set_collapsed(self, collapsed: bool) -> bool:
        """Fold (True) or unfold (False); idempotent. Returns True if the state changed.

        The API `CmdToggleGroupCollapse` drives — the group never folds itself on a click
        (`collapseRequested` asks the window, which pushes the command).
        """
        return self.collapse() if collapsed else self.expand()

    def collapse(self) -> bool:
        """Fold the group: badge every member, lay the badges out, re-fit the frame.

        The snapshot (`_expanded_state` + `_expanded_size`) is taken FIRST, so `expand()`
        can restore the exact arrangement; a repeated call is a no-op.
        """
        if self._collapsed:
            return False
        self._expanded_size = (float(self._width), float(self._height))
        self._expanded_state = {}
        self._collapsed = True
        self._fold_members()
        self._layout_badges()
        self.update()
        self.collapsedChanged.emit(True)
        return True

    def expand(self) -> bool:
        """Unfold the group: restore the frame size and every member's arrangement.

        Without a snapshot (a group restored FOLDED from a project file, whose pre-fold
        card layout was never saved) the members are un-badged WHERE THEY LIE and only
        the frame size is restored — the documented v1.4.2 limitation.
        """
        if not self._collapsed:
            return False
        state = self._expanded_state or {}
        # `_collapsed` goes False BEFORE the loop: the members are un-badged one by one, and
        # a resync triggered by an intermediate setPos must not see a "folded" group and
        # re-fold the very members this call is restoring (the v1.4.2 expand regression).
        self._collapsed = False
        self._suspend_layout = True
        try:
            if self._expanded_size:
                self.set_frame_size(self._expanded_size[0], self._expanded_size[1], resync=False)
            gpos = self.pos()
            for member in list(self._members):
                data = getattr(member, "data", None)
                if data is None:
                    continue
                entry = state.get(str(getattr(data, "id", "") or ""))
                if entry is not None:
                    lx, ly, was_collapsed, was_movable = entry
                    data.collapsed = bool(was_collapsed)
                else:
                    data.collapsed = False
                    was_movable = True
                try:
                    member.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, bool(was_movable))
                    if entry is not None:
                        # the snapshot holds LOCAL offsets from the frame's top-left corner,
                        # so a group dragged while folded unfolds into its CURRENT place
                        member.setPos(gpos.x() + float(lx), gpos.y() + float(ly))
                except RuntimeError:
                    continue  # Qt teardown — the item is gone
                updater = getattr(member, "update_appearance", None)
                if callable(updater):
                    updater()
            self._resync_members()
        finally:
            self._suspend_layout = False
        self._expanded_state = None
        self._expanded_size = None
        self.update()
        self.collapsedChanged.emit(False)
        return True

    def _fold_members(self):
        """Switch every member into its v0.8.4 badge and freeze it (no dragging while folded).

        Called by `collapse()` and by a membership change of a session-owned fold; the
        snapshot entry is added only when one is due (`_expanded_state` is not None).
        """
        for member in list(self._members):
            data = getattr(member, "data", None)
            if data is None:
                continue
            if self._expanded_state is not None:
                try:
                    movable = bool(member.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
                    gpos = self.pos()
                    self._expanded_state.setdefault(
                        str(getattr(data, "id", "") or ""),
                        (float(member.pos().x()) - float(gpos.x()),
                         float(member.pos().y()) - float(gpos.y()),
                         bool(getattr(data, "collapsed", False)), movable))
                except RuntimeError:
                    continue
            if not getattr(data, "collapsed", False):
                data.collapsed = True
            try:
                member.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            except RuntimeError:
                continue
            updater = getattr(member, "update_appearance", None)
            if callable(updater):
                updater()

    @staticmethod
    def _grid_sort_key(member) -> tuple:
        """A STABLE reading order of the badge grid: alias (lower-cased), then id.

        Deliberately not the current position: a re-layout after an undo (or a resize of
        a folded group) must reproduce the same grid, and a position-derived order would
        shuffle as soon as the layout itself moved the cards.
        """
        data = getattr(member, "data", None)
        return (str(getattr(data, "alias", "") or "").lower(),
                str(getattr(data, "id", "") or ""))

    @staticmethod
    def _badge_size(member) -> tuple:
        """(width, height) a member occupies while folded (the badge metrics)."""
        try:
            width = float(getattr(member, "_current_width", 0.0) or 0.0)
        except (TypeError, ValueError):
            width = 0.0
        try:
            height = float(getattr(member, "COLLAPSED_HEIGHT", 0.0) or 0.0)
        except (TypeError, ValueError):
            height = 0.0
        return max(width, 60.0), max(height, 1.0)

    def _resync_members(self):
        """Recompute the membership of the scene (the group's frame just changed)."""
        sc = self.scene()
        if sc is not None and hasattr(sc, "resync_group_members"):
            sc.resync_group_members()

    def _layout_badges(self) -> bool:
        """Lay the members' badges out in a grid inside the frame and re-fit the frame.

        The grid: a uniform column width (the widest badge), `BADGE_GAP` between the
        cells, the first row under the title band, `MEMBER_MARGIN` insets. The column
        count starts from what the CURRENT width takes and grows until the grid fits
        `MAX_H`, so a wide group gets a table and a narrow one a column. Every badge is
        placed INSIDE the new frame — that is what preserves the geometric membership.
        Returns False when there is nothing to lay out (or on re-entry).
        """
        if self._laying_out:
            return False
        members = [m for m in self._members if getattr(m, "data", None) is not None]
        if not members:
            return False
        self._laying_out = True
        try:
            members.sort(key=self._grid_sort_key)
            m = self.MEMBER_MARGIN
            gap = self.BADGE_GAP
            top = self.TITLE_ZONE_H + m
            col_w = max(self._badge_size(x)[0] for x in members)
            badge_h = max(self._badge_size(x)[1] for x in members)
            n = len(members)

            columns = int(max(1.0, (self._width - 2.0 * m + gap) // (col_w + gap)))
            columns = max(1, min(columns, n))
            cols, need_w, need_h = columns, 0.0, 0.0
            for candidate in range(columns, n + 1):
                rows = (n + candidate - 1) // candidate
                need_w = 2.0 * m + candidate * col_w + (candidate - 1) * gap
                need_h = top + rows * badge_h + (rows - 1) * gap + m
                cols = candidate
                if need_h <= self.MAX_H:
                    break

            self.set_frame_size(max(need_w, self.MIN_W), max(need_h, self.MIN_H), resync=False)
            gpos = self.pos()
            for i, member in enumerate(members):
                row, col = divmod(i, cols)
                member.setPos(gpos.x() + m + col * (col_w + gap),
                              gpos.y() + top + row * (badge_h + gap))
            self._resync_members()
        finally:
            self._laying_out = False
        self.update()
        return True

    def _on_membership_changed(self):
        """v1.4.2: a member joined/left while the group is folded.

        A SESSION fold re-lays the grid (and badges the newcomer); a group restored
        folded from a FILE keeps its saved arrangement — there is no snapshot, and a
        re-layout would destroy exactly the positions the file stored. A bulk move
        (`_apply_move` / a programmatic setPos) and the unfold itself are ATOMIC: the
        grid is not touched while they run (`_suspend_layout`).
        """
        if (not self._collapsed or self._laying_out or self._suspend_layout
                or self._expanded_state is None):
            return
        self._fold_members()
        self._layout_badges()

    def _on_membership_changed_aggregate(self):
        """v1.5.4: a member joined/left — the AGGREGATE changed, so repaint.

        The aggregate is read live at paint time, so the only thing a composition
        change needs is a repaint: without it a group that just lost its only offline
        member would keep the red frame until something else asked for a repaint.
        """
        self.refresh_aggregate()

    # ── Title ──────────────────────────────────────────────

    def _title_font(self) -> QFont:
        return QFont(theme.FONT_UI, 9, QFont.Bold)

    def _update_title_text(self):
        """Elide a long name to the frame width (the full name — in the tooltip; the ServerNode pattern)."""
        fm = QFontMetrics(self._title_font())
        max_w = max(int(self._width - 28), 1)
        if self._name and fm.horizontalAdvance(self._name) > max_w:
            self._display_name = fm.elidedText(self._name, Qt.TextElideMode.ElideRight, max_w)
        else:
            self._display_name = self._name
        self._apply_tooltip()

    def _apply_tooltip(self):
        """The group's tooltip: the full name (when the band elided it) + the aggregate words.

        The WORDS of the aggregate live here, not only in the painted plaque — the 1.5
        line's rule ("the tooltips keep the words"), so the shape+counts caption is never
        a riddle. A group with neither a name nor members keeps an empty tooltip.
        """
        lines = []
        if self._name and self._display_name != self._name:
            lines.append(self._name)
        caption = self.status_caption()
        if caption:
            lines.append(caption)
        try:
            self.setToolTip("\n".join(lines))
        except RuntimeError:
            pass  # Qt teardown — the item is already destroyed

    # ── Rendering (all the graphics in paint() — no child items:
    #      a single hit object, the standard drag works over the whole frame area) ──

    def _state_colors(self):
        """(pen_color, pen_width, fill, title_color) for the current state.

        v1.5.4 (ROADMAP task 1): in the ORDINARY state the frame takes the colour of the
        group's WORST member status when that is a problem (`warn` / `offline`) — the
        "trouble first" signal the feature exists for. It is a REDUNDANT channel: the
        aggregate plaque carries the same fact as a declared SHAPE and as words, so a
        greyscale print and a colour-vision deficiency read it too. Selection and hover
        are INTERACTIONS and always win over the aggregate; a group without trouble (or
        without members) keeps its violet frame exactly as before.
        """
        if self.isSelected():
            return (self.COLOR_SELECTED, 2.5, self.COLOR_FILL_SELECTED,
                    QColor(theme.GROUP_TITLE_SELECTED))
        if self._hover:
            color = QColor(self.COLOR_HOVER)
            color.setAlpha(170)
            return (color, 2.0, self.COLOR_FILL_HOVER, QColor(theme.GROUP_TITLE_HOVER))
        worst = self.worst_member_status()
        if worst in PROBLEM_STATUSES:
            status_color = theme.STATUS_COLORS.get(worst)
            if status_color:
                return (QColor(status_color), 2.0, self.COLOR_FILL, self.COLOR_TITLE)
        return (self.COLOR_BORDER, 1.5, self.COLOR_FILL, self.COLOR_TITLE)

    def paint(self, painter: QPainter, option, widget=None):
        w, h = self._width, self._height
        if w <= 2 or h <= 2:
            return
        pen_color, pen_width, fill, title_color = self._state_colors()

        path = QPainterPath()
        # A 1 px inset — the frame is entirely inside the boundingRect (Qt clips to it)
        path.addRoundedRect(1.0, 1.0, w - 2.0, h - 2.0, self.CORNER_RADIUS, self.CORNER_RADIUS)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(pen_color, pen_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawPath(path)

        # The title in the top band (see _update_title_text for the eliding)
        if self._display_name:
            painter.setFont(self._title_font())
            painter.setPen(QPen(title_color))
            painter.drawText(
                QRectF(14.0, 3.0, max(w - 28.0 - self.CHEVRON_ZONE, 1.0), self.TITLE_ZONE_H - 6.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._display_name)

        # v1.5.4 (ROADMAP task 1): the aggregate plaque — the worst member status and the
        # counts, in the right end of the SAME band (so the group FOLD, which re-fits the
        # frame and keeps the band, keeps the aggregate as well).
        self._paint_aggregate(painter)

        # v1.4.2: the fold chevron in the right corner of the title band (▾ folded /
        # ▴ expanded) — always visible, so the fold is discoverable without a menu.
        chevron_pen = QPen(title_color, 1.6)
        chevron_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(chevron_pen)
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPath(self._chevron_path())

        # The resize-corner marker — visible on hover/selection (a "drag by this corner" hint)
        if self._hover or self.isSelected():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(pen_color))
            r = theme.RADIUS_RESIZE_MARK
            painter.drawRoundedRect(QRectF(w - 16.0, h - 16.0, 10.0, 10.0), r, r)

    # ── Theme (v1.4.3, ROADMAP task 5) ───────────────────────────────────

    def refresh_theme(self):
        """Re-read the theme and repaint (v1.4.3).

        The group paints everything in `paint()` from live descriptors, so the
        only thing a switch has to do is ask for a repaint — the method exists so
        that the window's theme walk treats every scene item the same way.
        """
        self.update()

    # ── Mouse (manual move/resize — the StickyNote pattern) ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.boundingRect().contains(local):
                super().mousePressEvent(event)  # a click outside the group — the standard path
                return
            # v1.4.2: the fold chevron — the group ASKS (the window pushes the undo
            # command); checked BEFORE the move/resize branch so a click on it can never
            # start a drag or a resize.
            if self._in_chevron(local):
                self.setSelected(True)
                try:
                    self.collapseRequested.emit()
                except RuntimeError:
                    pass  # Qt teardown — the receiver is gone
                event.accept()
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self._width, self._height)
                self._drag_start_scene = scene_pos
            else:
                self._drag_mode = "move"
                self._drag_start_scene = scene_pos
            # v0.8.3-audit (#6): remember the start-of-gesture geometry (for undo)
            self._gesture_start_pos = QPointF(self.pos())
            event.accept()  # do NOT pass it to the scene — otherwise ScrollHandDrag would steal the gesture
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
                # Incremental shift (the start is updated) — no cumulative drift (StickyNote)
                self._drag_start_scene = scene_pos
            else:  # resize by the bottom-right corner
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
            # v0.8.3-audit (#6): the gesture is complete → a signal for the window's undo command.
            # Emitted only on a real geometry change (otherwise an empty stack entry).
            try:
                if mode == "move" and start_pos is not None:
                    end_pos = QPointF(self.pos())
                    if ((end_pos - start_pos).manhattanLength() > 0.5):
                        self.moveCommitted.emit(QPointF(start_pos), end_pos)
                elif mode == "resize" and start_size is not None:
                    cur = (self._width, self._height)
                    if abs(cur[0] - start_size[0]) + abs(cur[1] - start_size[1]) > 0.5:
                        self.resizeCommitted.emit(start_size[0], start_size[1], cur[0], cur[1])
            except Exception:  # noqa: BLE001 — the undo signal must not kill the release
                pass
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """A double click on the title — a rename request (MainWindow shows the dialog)."""
        scene_pos = event.scenePos()
        local = self.mapFromScene(scene_pos) if scene_pos is not None else None
        if local is not None and self._in_title_zone(local):
            self.renameRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ── Hover: cursors (drag / resize corner), as with the notes ──────

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

    # ── Serialization (v0.8.1: the "groups" array in the project JSON) ───
    # Membership is NOT stored — the geometric invariant recomputes it on load.

    def to_dict(self) -> dict:
        """The `groups` record. v1.4.2: the fold state is written ONLY while folded
        (the optional-field pattern — an old file has no such keys and loads unfolded,
        an older application ignores them)."""
        data = {
            "id": self.group_id,
            "name": self._name,
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self._width),
            "height": float(self._height),
        }
        if self._collapsed:
            data["collapsed"] = True
            if self._expanded_size:
                data["expanded_width"] = float(self._expanded_size[0])
                data["expanded_height"] = float(self._expanded_size[1])
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> "NodeGroup":
        """Create a group from a JSON entry (corrupt values — defaults; the StickyNote pattern).

        v1.4.2: `collapsed` + the pre-fold frame size are read back. A FOLDED group is
        rebuilt WITHOUT re-laying the badges out — the saved member positions ARE the
        grid (the loader adds them afterwards), only the flag and the unfold size are
        restored.
        """
        try:
            x = float(raw.get("x") or 0.0)
            y = float(raw.get("y") or 0.0)
            w = float(raw.get("width") or cls.DEFAULT_W)
            h = float(raw.get("height") or cls.DEFAULT_H)
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, cls.DEFAULT_W, cls.DEFAULT_H
        group_id = str(raw.get("id") or "")[:8] or None
        collapsed = bool(raw.get("collapsed"))
        expanded_w = raw.get("expanded_width") if collapsed else None
        expanded_h = raw.get("expanded_height") if collapsed else None
        return cls(
            name=str(raw.get("name") or ""),
            x=x, y=y, width=w, height=h, group_id=group_id,
            collapsed=collapsed, expanded_width=expanded_w, expanded_height=expanded_h,
        )
