# -*- coding: utf-8 -*-
"""v0.9.8 — map search bar (Ctrl+F): floating panel over the canvas.

ROADMAP v0.9.8:
  #1 Ctrl+F → search bar over the canvas: highlight matching nodes
     (alias/host/ip/comment).
  #2 Enter/Shift+Enter — move between results with centering and a
     brief accent frame (reveal_flash, the set_status pulse pattern).
  #3 Non-matching nodes are dimmed (focus/dim) so matches are read
     instantly.

The widget holds NO search logic: it only accepts input and emits
signals — which nodes match, what to dim and where to center is decided
by MainWindow (single source of truth — ui/main_window.py). The dark
theme follows the app palette (theme.WINDOW_BG card background,
theme.ACCENT accent, theme.TEXT_PRIMARY text — the same colors the
nodes use; v1.2.5: central theme constants in ui/theme.py).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from . import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None


def _t(key: str) -> str:
    """Safe i18n hook (consistent with map_view/server_node)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


# Dark panel theme (app palette): a WINDOW_BG card on the CANVAS_BG canvas,
# ACCENT border — the same one used for MapView matches/selection.
# v1.4.3 (ROADMAP task 4): the QSS moved into the ONE registry
# (ui/theme_qss.py, the "search_bar" entry) — the widget applies it at
# construction and re-applies it from refresh_theme() after a theme switch.


def _bar_style() -> str:
    """The card's stylesheet from the registry ("" without the ui package)."""
    if theme_qss is None:
        return ""
    return theme_qss.style("search_bar")


class _SearchLineEdit(QLineEdit):
    """Input field with navigation keys.

    Enter — next result, Shift+Enter — previous, Esc — close the panel.
    QLineEdit.returnPressed fires on both Enter and Shift+Enter (and does
    not pass modifiers), so we intercept keyPressEvent ourselves.
    """

    next_pressed = Signal()
    prev_pressed = Signal()
    close_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self.prev_pressed.emit()
            else:
                self.next_pressed.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.close_pressed.emit()
            event.accept()  # no "beep" — Esc is a meaningful action, not an error
            return
        super().keyPressEvent(event)


class MapSearchBar(QWidget):
    """v0.9.8: floating map search bar (parent — MapView).

    Layout: [input field] ["k / N" counter | "No matches"] [×].
    Signals: query_changed(str) on every text change; next_requested /
    prev_requested — Enter/Shift+Enter; close_requested — Esc or the "×" button.
    """

    query_changed = Signal(str)
    next_requested = Signal()
    prev_requested = Signal()
    close_requested = Signal()

    PREFERRED_WIDTH = 420   # panel width while the viewport is wider
    MIN_WIDTH = 280         # below this the panel loses readability

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapSearchBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_bar_style())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self._line = _SearchLineEdit(self)
        self._line.setPlaceholderText(_t("search.map_placeholder"))
        self._line.textChanged.connect(self.query_changed.emit)
        self._line.next_pressed.connect(self.next_requested)
        self._line.prev_pressed.connect(self.prev_requested)
        self._line.close_pressed.connect(self.close_requested)

        # Counter: "k / N" when there are matches, otherwise the "No matches" text.
        # _count_state — the last state (current, total) for retranslate().
        self._count_state = None
        self._count = QLabel("", self)
        self._update_count_label()

        self._close_btn = QPushButton("×", self)
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_requested)

        layout.addWidget(self._line, 1)
        layout.addWidget(self._count)
        layout.addWidget(self._close_btn)
        self.hide()

    # ── Public API (MainWindow controls the state) ────────────────

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-read the card's stylesheet.

        A QSS string is a VALUE: the switch has to hand the widget a new one (the
        registry builder is the one place that knows how). Called by
        `MainWindow.refresh_theme()`.
        """
        if theme_qss is None:
            return
        theme_qss.refresh(self, "search_bar")

    @property
    def query(self) -> str:
        """Current query text (as-is)."""
        return self._line.text()

    def set_query(self, text: str):
        """Set the text programmatically (emits query_changed on change)."""
        if self._line.text() != text:
            self._line.setText(text)

    def set_count(self, current: int, total: int):
        """The "k / N" counter or "No matches" (i18n — current at call time)."""
        self._count_state = (int(current), int(total))
        self._update_count_label()

    def retranslate(self):
        """Re-apply translations (language switch in MainWindow._switch_language)."""
        self._line.setPlaceholderText(_t("search.map_placeholder"))
        self._update_count_label()  # redraw the counter in the new language

    def focus_input(self):
        """Focus the input field + select all text (quick query replacement)."""
        self._line.setFocus()
        self._line.selectAll()

    # ── Internal ────────────────────────────────────────────────

    def _update_count_label(self):
        state = self._count_state
        if state is None:
            self._count.setText("")
            return
        current, total = state
        if total <= 0:
            self._count.setText(_t("search.no_results"))
            return
        try:
            self._count.setText(_t("search.count").format(cur=current, total=total))
        except Exception:  # noqa: BLE001 — formatting failed — show the numbers as-is
            self._count.setText(f"{current} / {total}")
