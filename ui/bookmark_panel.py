# -*- coding: utf-8 -*-
"""v1.6.7 (ROADMAP v1.6.7): the bookmarks panel — the fourth floating panel over the canvas.

The store of `modules/bookmarks.py` is invisible without a surface, and the surface is the
one the map already knows: a CHILD OF `MapView` (never a scene item), so it stays out of
every export, out of a rubber-band selection, out of `itemsBoundingRect()` and out of "fit
to content" — the legend / minimap / filter-plaque rule.

Built on what the three shipped panels prove, and inventing nothing new:

  * **a fold** — a click on the title band folds the panel down to that band, and the state
    is remembered by the WINDOW in `~/.sshmap/config.json` (`ui_bookmarks_collapsed`);
  * **a saved position** — a drag of the title band reports where the panel landed
    (`moved`) and the window persists it (`ui_bookmarks_position`), with the v1.5 snap
    (`SNAP_PX`) re-anchoring a drop that lands on the anchored edge;
  * **a filter row** — the case-insensitive substring of `modules/bookmarks.filter_entries()`
    (the PURE policy — the widget renders, it does not decide);
  * **one opener behind a callback** — a double click or Enter on a row calls the opener the
    WINDOW hands in (`SshMixin._quick_launch_url`), so the browser, its failure sentence and
    its status line keep ONE home ("module + callbacks, no imports of the window").

The rows carry the URL as the SECOND CHANNEL — the name on the first line and the address
under it in the muted tone — because a list of link NAMES is exactly what a team cannot
recognise; an entry of another type (`command`) is not listed at all (the panel's declared
scope, `modules/bookmarks.py`).

Import discipline: `ui.main_window` is never imported; the widget talks to the store and to
the callbacks it was given.
"""

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem,
)

try:  # v1.2.5: the central theme (ui/theme.py — palette/radii/fonts)
    from . import theme
except ImportError:  # flat layout: the ui/ directory itself is on sys.path
    import theme

try:  # the store and its ONE pure filter (the panel never re-implements either)
    from ..modules import bookmarks as BM
except ImportError:
    try:
        from modules import bookmarks as BM
    except ImportError:  # a stripped build — the panel degrades to an empty list
        BM = None


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the legend / activity-panel pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break the panel
        return key


def _url_role() -> int:
    """The item role holding the entry's URL (a Qt enum — read lazily, gotcha #7 hygiene)."""
    return int(Qt.ItemDataRole.UserRole)


class _BookmarkList(QListWidget):
    """The row list — its own Enter key, so ONE act is ONE path (gotcha #11).

    A `QListWidgetItem` double click emits BOTH `itemDoubleClicked` and `itemActivated`, so
    the widget connects only the first and intercepts Return/Enter here — exactly the
    `_CommandTree.entry_entered` pattern of `modules/command_library.py`.
    """

    entry_entered = Signal()

    def keyPressEvent(self, event):  # noqa: N802 — Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.entry_entered.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _BookmarkRowDelegate(QStyledItemDelegate):
    """One row, two lines: the NAME and the URL under it (the second channel).

    The background (selection / hover / alternating) is the style's own, so the theme keeps
    owning it; only the TEXT is drawn here, in the live theme tones — the name in
    `TEXT_PRIMARY`, the address a point smaller in `TEXT_MUTED`.
    """

    #: The gap between the two lines of a row.
    LINE_GAP = 1

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 — Qt API
        return QSize(int(option.rect.width()), int(BookmarkPanel.ROW_H))

    def paint(self, painter, option, index):
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        view_option.text = ""      # the style draws the FRAME, never the text
        widget = view_option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, view_option, painter, widget)

        rect = QRectF(option.rect)
        inset = float(BookmarkPanel.ROW_INSET)
        painter.save()
        try:
            name_font = QFont(option.font)
            url_font = QFont(option.font)
            try:
                url_font.setPointSizeF(max(url_font.pointSizeF() - 1.0, 6.0))
            except (TypeError, ValueError):  # pragma: no cover — a font without a point size
                pass
            half = (rect.height() - self.LINE_GAP) / 2.0

            painter.setFont(name_font)
            painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
            name_rect = QRectF(rect.left() + inset, rect.top(),
                               max(rect.width() - 2.0 * inset, 1.0), half)
            painter.drawText(
                name_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(name_font).elidedText(
                    str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                    Qt.TextElideMode.ElideRight, int(name_rect.width())))

            url = str(index.data(_url_role()) or "")
            if url:
                painter.setFont(url_font)
                painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
                url_rect = QRectF(rect.left() + inset, rect.top() + half + self.LINE_GAP,
                                  max(rect.width() - 2.0 * inset, 1.0), half)
                painter.drawText(
                    url_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(url_font).elidedText(
                        url, Qt.TextElideMode.ElideRight, int(url_rect.width())))
        finally:
            painter.restore()


class BookmarkPanel(QFrame):
    """The bookmarks panel: the fold, the filter and the rows, over the canvas.

    Signals:
        collapsed_changed(bool) — the panel folded/unfolded (the window persists it);
        moved(QPoint) — a drag of the title band finished here (the window persists it);
        manage_requested() — the "Edit bookmarks…" button (the WINDOW owns the dialog).
    """

    collapsed_changed = Signal(bool)
    moved = Signal(QPoint)
    manage_requested = Signal()

    WIDTH = 250            # the panel's fixed width
    HEADER_H = 22          # the title band (also the collapsed height)
    ROW_H = 34             # one row: the name and the URL under it
    ROW_INSET = 4          # the inner inset of a row's text
    PADDING = 6            # the inner inset of the card
    FILTER_H = 24          # the filter field
    LIST_H = 150           # the visible rows area
    BTN_H = 24             # the "Edit bookmarks…" button
    SPACING = 4            # the vertical rhythm of the body
    RADIUS = float(theme.RADIUS_SEARCH_BAR)   # one style with the search bar / minimap
    #: How far the pointer must travel before a press on the title band counts as a DRAG
    #: (below it the gesture is the FOLD — one band, two gestures, declared once).
    DRAG_THRESHOLD = 4

    def __init__(self, view, store=None, opener=None, parent=None):
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._store = store
        self._opener = opener
        self._entries = []            # every URL entry of the store
        self._collapsed = False
        self._dragging = False
        self._press_pos = None
        self._drag_offset = QPoint(0, 0)
        self._labels = {}

        self.setObjectName("BookmarkPanel")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self.WIDTH)

        self.filter = QLineEdit(self)
        self.filter.setObjectName("BookmarkFilter")
        self.filter.textChanged.connect(self._on_filter_changed)

        self.list = _BookmarkList(self)
        self.list.setObjectName("BookmarkList")
        self.list.setItemDelegate(_BookmarkRowDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QListWidget.EditTrigger.NoEditTriggers)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list.entry_entered.connect(self._on_entry_entered)

        self.manage_btn = QPushButton(self)
        self.manage_btn.setObjectName("BookmarkManageBtn")
        self.manage_btn.clicked.connect(self._on_manage_clicked)

        self.retranslate()
        self._apply_height()
        self.reload()

    # ── Text (cached; the paint path never calls i18n) ──────────────────────

    def _make_font(self, delta: float, bold: bool = False) -> QFont:
        """The panel's font: the UI font one point smaller, optionally bold."""
        font = QFont(self.font())
        try:
            font.setPointSizeF(max(font.pointSizeF() + delta, 7.0))
        except (TypeError, ValueError):  # pragma: no cover — a font without a point size
            pass
        font.setBold(bool(bold))
        return font

    def _chrome_keys(self) -> tuple:
        """The translated strings of the panel, in ONE declaration."""
        return ("bookmarks.title", "bookmarks.tooltip", "bookmarks.filter_placeholder",
                "bookmarks.empty", "bookmarks.no_matches", "bookmarks.manage",
                "bookmarks.manage_tooltip")

    def retranslate(self):
        """Re-read every string of the panel (a language switch). Idempotent, never raises."""
        self._labels = {key: _t(key) for key in self._chrome_keys()}
        self._title_font = self._make_font(-1.0, bold=True)
        try:
            self.setToolTip(self._labels.get("bookmarks.tooltip", ""))
            self.filter.setPlaceholderText(self._labels.get("bookmarks.filter_placeholder", ""))
            self.filter.setToolTip(self._labels.get("bookmarks.filter_placeholder", ""))
            self.manage_btn.setText(self._labels.get("bookmarks.manage", ""))
            self.manage_btn.setToolTip(self._labels.get("bookmarks.manage_tooltip", ""))
        except RuntimeError:
            return  # Qt teardown — nothing to re-text
        self.update()

    def refresh_theme(self):
        """Re-read the theme: every colour of the panel is resolved in `paintEvent`."""
        try:
            self.update()
            self.list.viewport().update()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    # ── The data ────────────────────────────────────────────────────────────

    def store(self):
        """The store the panel talks to (the module-level singleton by default)."""
        if self._store is None and BM is not None:
            self._store = BM.get_bookmark_store()
        return self._store

    def set_opener(self, opener):
        """Install the ONE opener (`SshMixin._quick_launch_url`) behind a callback."""
        self._opener = opener

    def reload(self):
        """Re-read the store and rebuild the rows (after an edit, or at startup)."""
        store = self.store()
        try:
            entries = store.load_urls() if store is not None else []
        except Exception:  # noqa: BLE001 — a broken store shows an empty panel
            entries = []
        self._entries = [dict(e) for e in entries]
        self.refresh_rows()

    def set_entries(self, entries):
        """Install the URL entries directly (the test seam — no store involved)."""
        self._entries = [dict(e) for e in (entries or [])]
        self.refresh_rows()

    def entries(self) -> list:
        """Every URL entry the panel holds (unfiltered)."""
        return [dict(e) for e in self._entries]

    def visible_entries(self) -> list:
        """The entries the FILTER keeps right now (the pure policy of the store module)."""
        text = ""
        try:
            text = self.filter.text()
        except RuntimeError:
            return list(self._entries)
        if BM is None:
            return list(self._entries)
        return [dict(e) for e in BM.filter_entries(self._entries, text)]

    def refresh_rows(self):
        """Rebuild the rows from the entries the filter keeps. The test seam."""
        rows = self.visible_entries()
        try:
            self.list.setUpdatesEnabled(False)
            self.list.clear()
            for entry in rows:
                item = QListWidgetItem(str(entry.get("name") or ""))
                item.setData(_url_role(), str(entry.get("value") or ""))
                item.setToolTip(str(entry.get("value") or ""))
                self.list.addItem(item)
            if rows:
                self.list.setCurrentRow(0)
        except RuntimeError:
            return  # Qt teardown — the list is already destroyed
        finally:
            try:
                self.list.setUpdatesEnabled(True)
            except RuntimeError:
                pass
        self._sync_empty_state()
        self.update()

    def _sync_empty_state(self) -> str:
        """The message the panel shows in the rows area ("" while there are rows).

        ONE sentence, chosen by ONE rule: an EMPTY store says "no bookmarks yet", a filter
        that kept nothing says so — the `activity.empty` / `no matches` split.
        """
        try:
            has_rows = self.list.count() > 0
            self.list.setVisible(has_rows)
        except RuntimeError:
            return ""
        if has_rows:
            self._message_key = ""
        elif self._entries:
            self._message_key = "bookmarks.no_matches"
        else:
            self._message_key = "bookmarks.empty"
        return self._message_key

    def message_key(self) -> str:
        """The key of the sentence currently shown in the rows area ("" = rows on screen)."""
        return str(getattr(self, "_message_key", "") or "")

    def _on_filter_changed(self, _text: str):
        """The user typed in the filter — rebuild the rows (the policy is the store's)."""
        self.refresh_rows()

    # ── The ONE opener ──────────────────────────────────────────────────────

    def open_row(self, row: int) -> bool:
        """Open the entry of `row` (of the VISIBLE rows) through the opener callback.

        False when the row does not exist or no opener is installed — a panel without an
        opener is a panel that lists links and nothing else.
        """
        rows = self.visible_entries()
        if not (0 <= int(row) < len(rows)):
            return False
        opener = self._opener
        if not callable(opener):
            return False
        entry = rows[int(row)]
        try:
            opener(str(entry.get("value") or ""), str(entry.get("name") or ""))
        except Exception:  # noqa: BLE001 — the opener reports its own failures
            return False
        return True

    def _on_item_double_clicked(self, item):
        """A double click on a row opens it (the ONLY connection to that signal)."""
        if item is not None:
            self.open_row(self.list.row(item))

    def _on_entry_entered(self):
        """Enter on the list opens the current row (the `entry_entered` hook)."""
        self.open_row(self.list.currentRow())

    def _on_manage_clicked(self):
        """The "Edit bookmarks…" button — the WINDOW owns the editor dialog."""
        try:
            self.manage_requested.emit()
        except RuntimeError:
            pass  # Qt teardown — the receiver is gone

    # ── Geometry ────────────────────────────────────────────────────────────

    def body_height(self) -> int:
        """The height of the body (0 while folded)."""
        if self._collapsed:
            return 0
        return (self.FILTER_H + self.SPACING + self.LIST_H + self.SPACING + self.BTN_H
                + self.PADDING)

    def _apply_height(self):
        """Fix the widget's height and place the three children by hand."""
        try:
            self.setFixedHeight(self.HEADER_H + self.body_height())
            self._layout_children()
        except RuntimeError:
            return  # Qt teardown — the widget is already destroyed

    def _layout_children(self):
        """Place the filter, the list and the button inside the card (no QLayout)."""
        width = max(self.width() - 2 * self.PADDING, 1)
        y = self.HEADER_H
        for widget, height in ((self.filter, self.FILTER_H), (self.list, self.LIST_H),
                               (self.manage_btn, self.BTN_H)):
            widget.setGeometry(self.PADDING, y, width, height)
            widget.setVisible(not self._collapsed)
            y += height + self.SPACING

    def resizeEvent(self, event):  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._layout_children()

    def is_collapsed(self) -> bool:
        return bool(self._collapsed)

    def set_collapsed(self, collapsed: bool, persist: bool = True):
        """Fold/unfold the panel. Emits `collapsed_changed` only on a real change.

        `persist=False` is the construction path: the window applies the SAVED state and
        must not write it back (the legend's `set_collapsed` rule)."""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_height()
        self.update()
        if persist:
            try:
                self.collapsed_changed.emit(collapsed)
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone

    def header_rect(self) -> QRectF:
        """The title band (the fold affordance AND the drag handle)."""
        return QRectF(0.0, 0.0, float(self.width()), float(self.HEADER_H))

    # ── Interaction ─────────────────────────────────────────────────────────

    @staticmethod
    def _event_pos(event):
        """The event position as a QPoint (the legend's `position()`/`pos()` pattern)."""
        position = getattr(event, "position", None)
        if callable(position):
            try:
                return position().toPoint()
            except Exception:  # noqa: BLE001 — an older binding without position()
                pass
        return event.pos()

    def mousePressEvent(self, event):  # noqa: N802 — Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = self._event_pos(event)
        if not self.header_rect().contains(float(point.x()), float(point.y())):
            super().mousePressEvent(event)
            return
        self._press_pos = point
        self._drag_offset = point
        self._dragging = False
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 — Qt API
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        point = self._event_pos(event)
        if not self._dragging:
            moved = (point - self._press_pos).manhattanLength()
            if moved < self.DRAG_THRESHOLD:
                event.accept()
                return
            self._dragging = True
        target = self.pos() + (point - self._drag_offset)
        parent = self.parentWidget()
        if parent is not None:
            target.setX(min(max(target.x(), 0), max(parent.width() - self.width(), 0)))
            target.setY(min(max(target.y(), 0), max(parent.height() - self.height(), 0)))
        self.move(target)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt API
        if self._press_pos is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        dragging = self._dragging
        self._press_pos = None
        self._dragging = False
        if dragging:
            try:
                self.moved.emit(QPoint(self.pos()))
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone
        else:
            self.set_collapsed(not self._collapsed)
        event.accept()

    # ── Rendering ───────────────────────────────────────────────────────────

    def paintEvent(self, event):  # noqa: N802 — Qt API
        width, height = float(self.width()), float(self.height())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            path.addRoundedRect(QRectF(1.0, 1.0, max(width - 2.0, 1.0), max(height - 2.0, 1.0)),
                                self.RADIUS, self.RADIUS)
            painter.setPen(QPen(QColor(theme.SURFACE_ALT), 1.0))
            painter.setBrush(QBrush(QColor(theme.WINDOW_BG)))
            painter.drawPath(path)

            painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
            painter.setFont(getattr(self, "_title_font", self._make_font(-1.0, bold=True)))
            fm = QFontMetrics(painter.font())
            title_rect = QRectF(self.PADDING, 0.0, max(width - 2.0 * self.PADDING, 1.0),
                                float(self.HEADER_H))
            painter.drawText(
                title_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm.elidedText(self._labels.get("bookmarks.title", _t("bookmarks.title")),
                              Qt.TextElideMode.ElideRight,
                              int(title_rect.width()) - 14))
            self._paint_chevron(painter, width)
            if self._collapsed:
                return
            # The message of the rows area (no rows on screen — the empty / no-match state).
            key = self.message_key()
            if key:
                painter.setFont(self._make_font(-1.0))
                painter.setPen(QPen(QColor(theme.TEXT_MUTED)))
                message_rect = QRectF(self.PADDING, float(self.HEADER_H),
                                      max(width - 2.0 * self.PADDING, 1.0), float(self.LIST_H))
                painter.drawText(message_rect,
                                 int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                                 self._labels.get(key, _t(key)))
        finally:
            painter.end()

    def _paint_chevron(self, painter, width: float):
        """The fold marker of the title band: down (expanded) or right (folded)."""
        cx, cy = width - self.PADDING - 4.0, self.HEADER_H / 2.0
        path = QPainterPath()
        if self._collapsed:
            path.moveTo(cx - 2.0, cy - 4.0)
            path.lineTo(cx + 2.5, cy)
            path.lineTo(cx - 2.0, cy + 4.0)
        else:
            path.moveTo(cx - 4.0, cy - 2.0)
            path.lineTo(cx, cy + 2.5)
            path.lineTo(cx + 4.0, cy - 2.0)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    # ── Introspection (the topical test) ────────────────────────────────────

    def row_count(self) -> int:
        """How many rows are displayed right now."""
        try:
            return int(self.list.count())
        except RuntimeError:
            return 0

    def rows_text(self) -> list:
        """The displayed rows as (name, url) pairs (the test seam)."""
        out = []
        try:
            for index in range(self.list.count()):
                item = self.list.item(index)
                out.append((item.text(), str(item.data(_url_role()) or "")))
        except RuntimeError:
            return out
        return out
