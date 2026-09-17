"""Sticky Notes — free-standing text notes on the map (v0.7.2).

A QGraphicsProxyWidget with a QTextEdit inside: the note is both a scene
graphics object (draggable, resizable by the corner) and a real input widget
(double click — edit mode, like regular sticky notes).

Why manual mouse handling instead of ItemIsMovable: QGraphicsProxyWidget
forwards events to the child QTextEdit, and it "eats" them (cursor/selection),
so a scene-level drag in Qt does not start. Two-mode behavior:

    normal    — left click+drag moves the note, the bottom-right corner —
                resizes it; the widget has no focus (does not intercept input);
    edit mode — double click enables StrongFocus on the QTextEdit and events
                are passed on (caret placement, selection); focusOut returns
                the note to normal mode.

Keyboard Delete removes the selected note only when the focus is NOT inside
the editor (in edit mode keys go to the widget — Delete erases characters).

v1.2.4-fix (tester feedback): an attached note can be moved — a drag does NOT
detach it, the anchor line follows live (dragUpdated signal → the scene
recomputes the offset and the path); detaching — via the context menu / undo /
deleting the server. The note body is drawn in paint() as a rounded rect
(the editor is transparent) — QSS border-radius alone does not clip the widget
background, and the corners "stuck out" as a square.
"""
import uuid
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QRectF, Signal, QEvent
from PySide6.QtGui import (QFont, QBrush, QColor, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import QGraphicsProxyWidget, QTextEdit, QGraphicsItem

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme


def _t(key: str) -> str:
    """Safe i18n hook: returns the key itself when i18n is unavailable."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


class StickyNote(QGraphicsProxyWidget):
    """A note on the map: dragging, resize by the corner, double click — text.

    v1.2.4-fix: an attached note can be moved (a drag does not detach it) — the anchor
    line follows live via dragUpdated → MapScene.on_note_drag_updated.
    """

    MIN_W, MIN_H = 140.0, 90.0
    MAX_W, MAX_H = 1200.0, 800.0
    CORNER_HIT = 16.0      # "grab the corner" zone for resize (px from the bottom-right)

    # v1.2.4-fix: a muted palette on tester feedback (the classic
    # #fef08a/#ca8a04 is too bright); it reads on the dark map but does not "cut in".
    # v1.2.5: the values — from the central theme (ui/theme.py), unchanged.
    BG_COLOR = theme.NOTE_BG
    BORDER_COLOR = theme.NOTE_BORDER
    TEXT_COLOR = theme.NOTE_TEXT
    CORNER_RADIUS = theme.RADIUS_NOTE   # rounding of the note window corners (v1.2.4-fix: was 4 px)

    textEdited = Signal()  # the text changed (MainWindow marks the project dirty)
    moved = Signal()       # the note was moved with the mouse (also a dirty reason)
    # v1.2.4: attaching to a server — signals for MainWindow
    attachRequested = Signal(object)  # release over a ServerNode → the window attaches the note
    detachRequested = Signal()        # fallback path; never emitted from a drag (v1.2.4-fix:
                                      # dragging an attached note moves it, detach — menu/undo)
    # v1.2.4-fix: live geometry during a drag (move AND resize), every step —
    # the scene recomputes the anchor offset and the anchor-line path of the attached note
    dragUpdated = Signal(object)  # emitted with the note itself (self)

    def __init__(self, text: str = "", x: float = 0.0, y: float = 0.0,
                 width: float = 240.0, height: float = 160.0, note_id: Optional[str] = None):
        editor = QTextEdit()
        super().__init__()
        self.setWidget(editor)

        self.note_id = note_id or str(uuid.uuid4())[:8]
        # v1.2.4: the id of the attached server (None — a free note); state on the item,
        # serialized via to_dict() (the "server_id" key is written only when set)
        self.server_id: Optional[str] = None
        # v1.2.4-fix: the note's position offset from the node anchor (top-right corner + 12 px).
        # (0,0) — the note is exactly at the anchor (a fresh attach/menu); !=0 — the user moved
        # the attached note. Driven by MapScene (on_note_drag_updated / attach keep_position);
        # not serialized — on load it is computed from the stored x/y.
        self.anchor_offset: Tuple[float, float] = (0.0, 0.0)
        self._editing = False
        self._drag_mode = None  # None | "move" | "resize"
        self._drag_start_scene = None
        self._size_start: Tuple[float, float] = (width, height)
        self._moved_this_drag = False

        # ── Editor look (the sticker) ────────────────────────
        # v1.2.4-fix: the background/border/rounding is drawn by this item's paint() (see it),
        # the editor — TEXT ONLY on a transparent background. A QSS background alone
        # is not clipped to border-radius (the widget background is drawn as a square) — the
        # rounded corners "stuck out" as a square beyond the border.
        editor.setAcceptRichText(False)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        editor.setFont(QFont(theme.FONT_UI, 10))
        editor.setStyleSheet(
            "QTextEdit { background: transparent; color: %s;"
            " border: none; padding: 6px; }"
            % self.TEXT_COLOR
        )
        editor.setPlaceholderText(_t("note.placeholder"))
        # Normal mode: the widget does NOT take focus — the note handles the clicks
        # (move/resize), not the QTextEdit. A double click enters edit mode.
        editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._loading = True
        editor.setPlainText(text or "")
        self._loading = False

        editor.textChanged.connect(self._on_editor_text_changed)
        # Qt6: the focusIn/focusOut signals no longer exist on QWidget — we catch FocusOut
        # via eventFilter (exit edit mode on focus loss)
        editor.installEventFilter(self)

        self.setPos(x, y)
        w, h = self._clamp_size(width, height)
        self.resize(w, h)
        # ItemIsSelectable — for Delete removal and highlighting; ItemIsMovable is NOT
        # set: we move it manually (see the module docstring).
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

    # ── Geometry helpers ───────────────────────────────────────

    @classmethod
    def _clamp_size(cls, w: float, h: float):
        w = max(cls.MIN_W, min(cls.MAX_W, float(w)))
        h = max(cls.MIN_H, min(cls.MAX_H, float(h)))
        return w, h

    def set_note_size(self, width: float, height: float):
        """Change the note size (bounded by MIN/MAX)."""
        w, h = self._clamp_size(width, height)
        if abs(w - self.rect().width()) < 0.5 and abs(h - self.rect().height()) < 0.5:
            return
        self.prepareGeometryChange()
        self.resize(w, h)

    def boundingRect(self) -> QRectF:
        """Explicit geometry (uniform with ServerNode; see its boundingRect)."""
        return QRectF(0, 0, self.rect().width(), self.rect().height())

    def text(self) -> str:
        return self.widget().toPlainText()

    def set_text(self, value: str):
        """Set the text without the textEdited signal (loading from a file)."""
        self._loading = True
        self.widget().setPlainText(value or "")
        self._loading = False

    # ── Dirty marking ──────────────────────────────────────────

    def _on_editor_text_changed(self):
        if not getattr(self, "_loading", False) and self.scene() is not None:
            self.textEdited.emit()

    # ── Edit mode (double click / focusOut) ────────────────────

    def enter_edit_mode(self):
        """Enter the text editing mode."""
        if self._editing:
            return
        self._editing = True
        ed = self.widget()
        ed.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        ed.setFocus()

    def exit_edit_mode(self):
        if not self._editing:
            return
        self._editing = False
        ed = self.widget()
        ed.clearFocus()
        ed.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def editing(self) -> bool:
        return self._editing

    # ── Event filter (Qt6: no focusOut signal — we catch the widget event) ──

    def eventFilter(self, obj, event):
        if (self.widget() is not None and obj is self.widget()
                and event.type() == QEvent.Type.FocusOut):
            # The focus left the editor — return the note to normal mode
            self.exit_edit_mode()
        return super().eventFilter(obj, event)

    # ── Mouse handling (manual move/resize, see the docstring) ──

    def _in_corner(self, pos) -> bool:
        r = self.rect()
        return (r.width() - self.CORNER_HIT <= pos.x() <= r.width()) and \
               (r.height() - self.CORNER_HIT <= pos.y() <= r.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Edit mode: events — to the editor (caret/selection)
            if self._editing:
                super().mousePressEvent(event)
                return
            scene_pos = event.scenePos()
            local = self.mapFromScene(scene_pos) if scene_pos is not None else None
            if local is None or not self.rect().contains(local):
                super().mousePressEvent(event)  # a click outside the note — the standard path
                return
            self.setSelected(True)
            if self._in_corner(local):
                self._drag_mode = "resize"
                self._size_start = (self.rect().width(), self.rect().height())
                self._drag_start_scene = scene_pos  # the press point — the size baseline
            else:
                self._drag_mode = "move"
                self._drag_start_scene = scene_pos
            self._moved_this_drag = False
            event.accept()  # do NOT pass it to the QTextEdit — otherwise it would hijack the drag
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_mode and (event.buttons() & Qt.MouseButton.LeftButton):
            scene_pos = event.scenePos()
            if scene_pos is None:
                return
            if self._drag_mode == "move":
                delta = scene_pos - self._drag_start_scene
                if not self._moved_this_drag and abs(delta.x()) + abs(delta.y()) > 1.0:
                    self._moved_this_drag = True
                    # v1.2.4-fix: dragging an attached note does NOT detach it (tester
                    # feedback) — the note can be moved, the anchor line follows live
                self.prepareGeometryChange()
                # Incremental shift (the start is updated) — no cumulative drift
                self.setPos(self.pos() + delta)
                self._drag_start_scene = scene_pos
            else:  # resize by the bottom-right corner
                w0, h0 = self._size_start
                start_local = self.mapFromScene(self._drag_start_scene or scene_pos)
                cur_local = self.mapFromScene(scene_pos)
                if abs(cur_local.x() - start_local.x()) + abs(cur_local.y() - start_local.y()) > 1.0:
                    self.set_note_size(w0 + (cur_local.x() - start_local.x()),
                                       h0 + (cur_local.y() - start_local.y()))
            # v1.2.4-fix: live geometry — the scene updates the offset/line of the attached note
            try:
                self.dragUpdated.emit(self)
            except RuntimeError:  # Qt teardown
                pass
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            mode = self._drag_mode
            self._drag_mode = None
            self._drag_start_scene = None
            if mode == "move" and self._moved_this_drag and self.scene() is not None:
                self.moved.emit()  # a move — an unsaved change
                # v1.2.4 (D6): release over a ServerNode → attach to it. items()
                # (not itemAt) — the note itself is under the cursor, the node may be UNDER it.
                # v1.2.4-fix: for an ALREADY attached note this is re-attaching to ANOTHER node
                # (server_id != node.data.id); releasing over its OWN node — a no-op
                # (the note stays where it was dragged to).
                node = self._find_node_at_release(event.scenePos())
                if node is not None and getattr(self, "server_id", None) != node.data.id:
                    try:
                        self.attachRequested.emit(node)
                    except RuntimeError:  # Qt teardown
                        pass
        super().mouseReleaseEvent(event)

    def _find_node_at_release(self, scene_pos):
        """v1.2.4: the ServerNode under the release point (hit-test + walking parentItem).

        Duck-typing by the `data.id` attribute — without importing ServerNode (a risk of a
        circular import; only ServerNode carries self.data, see server_node.py).
        scene.items() returns ALL objects under the point — the note itself is in the list
        and is simply skipped.
        """
        if scene_pos is None:
            return None
        scene = self.scene()
        if scene is None:
            return None
        try:
            items = list(scene.items(scene_pos))
        except RuntimeError:  # Qt teardown
            return None
        for item in items:
            n = item
            while n is not None:
                data = getattr(n, "data", None)
                if data is not None and getattr(data, "id", None):
                    return n
                n = n.parentItem()
        return None

    def paint(self, painter: QPainter, option, widget=None):
        """The note body — a rounded rect (v1.2.4-fix), then the transparent editor.

        QGraphicsProxyWidget draws ONLY the widget image; the QSS background of the
        QTextEdit is not clipped to border-radius (the background is drawn as a square,
        and the corners "stuck out" beyond the border). Therefore: background+border —
        here (QPainterPath), the text — on top (the editor with a transparent background).
        adjusted(1) + a 2 px pen — the stroke is entirely inside the boundingRect, with no
        clipping at the item edge.
        """
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1),
                            self.CORNER_RADIUS, self.CORNER_RADIUS)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(self.BORDER_COLOR), 2))
        painter.setBrush(QBrush(QColor(self.BG_COLOR)))
        painter.drawPath(path)
        super().paint(painter, option, widget)

    def mouseDoubleClickEvent(self, event):
        """Double click — enter the editing mode (the caret under the cursor)."""
        if self._editing:
            # Already editing — a regular double click in the text (selecting a word)
            super().mouseDoubleClickEvent(event)
            return
        local = self.mapFromScene(event.scenePos()) if event.scenePos() is not None else None
        if local is not None and self.rect().contains(local):
            self.enter_edit_mode()
            # Pass it on — the caret will land under the cursor
            super().mouseDoubleClickEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    # ── Hover: cursors (drag / resize corner) ────────────────────

    def hoverMoveEvent(self, event):
        if not self._editing and event.scenePos() is not None:
            local = self.mapFromScene(event.scenePos())
            if local is not None and self.rect().contains(local):
                if self._in_corner(local):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().hoverMoveEvent(event)

    def hoverEnterEvent(self, event):
        if not self._editing:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    # ── Serialization (v0.7.2: the "notes" array in the project JSON) ───

    def to_dict(self) -> dict:
        d = {
            "id": self.note_id,
            "text": self.text(),
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "width": float(self.rect().width()),
            "height": float(self.rect().height()),
        }
        # v1.2.4 (D9): the key is written ONLY when set — clean files for free notes;
        # older app versions simply do not read an unknown key
        if getattr(self, "server_id", None):
            d["server_id"] = str(self.server_id)
        return d

    @classmethod
    def from_dict(cls, raw: dict) -> "StickyNote":
        """Create a note from a JSON entry (extra/corrupt keys — defaults)."""
        try:
            x = float(raw.get("x") or 0.0)
            y = float(raw.get("y") or 0.0)
            w = float(raw.get("width") or 240.0)
            h = float(raw.get("height") or 160.0)
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, 240.0, 160.0
        note_id = str(raw.get("id") or "")[:8] or None
        return cls(
            text=str(raw.get("text") or ""),
            x=x, y=y, width=w, height=h, note_id=note_id,
        )
