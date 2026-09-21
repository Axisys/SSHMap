# -*- coding: utf-8 -*-
"""v1.3.3.4 (ROADMAP task 1): the find bar of the terminal — a floating panel over the canvas.

The `ui/map_search_bar.py` pattern (v0.9.8) applied to the terminal: a small
OVERLAY widget (a child of the canvas, outside every layout — NOT a new dock, not
a row of the session page) with an input field, a "k / N" counter and a close
button. The widget holds NO search logic: it accepts the input and emits signals;
what matches, where the viewport goes and how the matches are painted is decided
by `TerminalWidget` (the single source of truth, modules/terminal_widget.py).

Why an overlay and not a dock: the terminal canvas is the only text surface of the
application that had no search at all (the map and the command library both have
one), and a dock would steal a strip of the grid from the session — the panel must
cost the user nothing while it is closed (a hidden child of the canvas: 0 px) and
float above the output while it is open.

The keys are handled HERE, in the panel's own field (Enter — next match,
Shift+Enter — previous, Esc — close): the terminal's own keys are the xterm wire
protocol and must never be re-bound (§14a scope boundary) — the panel takes the
keyboard while it is open, so nothing typed into it can reach the PTY.

Colors — the central theme (ui/theme.py), the same card/accent pair as the map
search bar; the app palette is the only source (v1.2.5 rule).

v1.3.3.4: i18n keys `terminal.find.*` (placeholder / count / next / prev / close);
the empty state reuses `search.no_results` (the map bar's key — the same situation,
ZERO new keys).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None


def _t(key: str) -> str:
    """Safe i18n hook (consistent with map_search_bar/terminal_widget)."""
    try:
        from i18n import t as _translate
        return _translate(key)
    except Exception:
        return key


def _bar_style() -> str:
    """The card's stylesheet from the registry ("" without the ui package).

    v1.4.3 (ROADMAP task 4): the pre-v1.4.3 inline f-string moved into
    ui/theme_qss.py ("find_bar") so the initial styling and a theme switch share
    ONE builder. The panel keeps its own sizes (the canvas is a monospace
    surface); only the colours follow the theme.
    """
    if theme_qss is None:
        return ""
    return theme_qss.style("find_bar")


class _FindLineEdit(QLineEdit):
    """The input field of the panel: Enter — next, Shift+Enter — previous, Esc — close.

    QLineEdit.returnPressed fires for both Enter and Shift+Enter (and does not pass
    the modifiers), so the keys are intercepted here — the same reason and the same
    shape as in `ui/map_search_bar.py`.
    """

    next_pressed = Signal()
    prev_pressed = Signal()
    close_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.prev_pressed.emit()
            else:
                self.next_pressed.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close_pressed.emit()
            event.accept()   # no "beep" — Esc is a meaningful action, not an error
            return
        super().keyPressEvent(event)


class TerminalFindBar(QWidget):
    """v1.3.3.4: the floating find panel over the terminal canvas (parent — TerminalWidget).

    Layout: [input field] ["k / N" | "No matches"] [×].
    Signals: query_changed(str) on every text change; next_requested /
    prev_requested — Enter/Shift+Enter; close_requested — Esc or the "×" button.
    """

    query_changed = Signal(str)
    next_requested = Signal()
    prev_requested = Signal()
    close_requested = Signal()

    PREFERRED_WIDTH = 360   # panel width while the canvas is wider
    MIN_WIDTH = 220         # below this the counter loses readability
    MARGIN = 8              # inset from the canvas edges (px, both axes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TerminalFindBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_bar_style())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._line = _FindLineEdit(self)
        self._line.setPlaceholderText(_t("terminal.find.placeholder"))
        self._line.textChanged.connect(self.query_changed.emit)
        self._line.next_pressed.connect(self.next_requested)
        self._line.prev_pressed.connect(self.prev_requested)
        self._line.close_pressed.connect(self.close_requested)

        # The counter: "k / N" with matches, the "No matches" text otherwise.
        # _count_state — the last (current, total) for retranslate().
        self._count_state = None
        self._count = QLabel("", self)
        self._update_count_label()

        # The mouse route through the matches (Enter/Shift+Enter are the keyboard one):
        # two tiny buttons with the terminal.find.next/prev tooltips.
        self._prev_btn = QPushButton("▲", self)
        self._prev_btn.setFixedSize(20, 20)
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setToolTip(_t("terminal.find.prev"))
        self._prev_btn.clicked.connect(self.prev_requested)

        self._next_btn = QPushButton("▼", self)
        self._next_btn.setFixedSize(20, 20)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setToolTip(_t("terminal.find.next"))
        self._next_btn.clicked.connect(self.next_requested)

        self._close_btn = QPushButton("×", self)
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip(_t("terminal.find.close"))
        self._close_btn.clicked.connect(self.close_requested)

        layout.addWidget(self._line, 1)
        layout.addWidget(self._count)
        layout.addWidget(self._prev_btn)
        layout.addWidget(self._next_btn)
        layout.addWidget(self._close_btn)
        self.hide()

    # ── Public API (TerminalWidget controls the state) ─────────────────────

    @property
    def query(self) -> str:
        """The current query text (as-is)."""
        return self._line.text()

    def set_query(self, text: str):
        """Set the text programmatically (emits query_changed on a change)."""
        if self._line.text() != text:
            self._line.setText(text)

    def set_count(self, current: int, total: int):
        """The "k / N" counter or "No matches" (i18n — resolved at call time)."""
        self._count_state = (int(current), int(total))
        self._update_count_label()

    def retranslate(self):
        """Re-apply the translations (language switch — TerminalWidget.retranslate())."""
        self._line.setPlaceholderText(_t("terminal.find.placeholder"))
        self._close_btn.setToolTip(_t("terminal.find.close"))
        self._prev_btn.setToolTip(_t("terminal.find.prev"))
        self._next_btn.setToolTip(_t("terminal.find.next"))
        self._update_count_label()   # redraw the counter in the new language

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-read the card's stylesheet from the registry."""
        if theme_qss is None:
            return
        theme_qss.refresh(self, "find_bar")

    def focus_input(self):
        """Focus the field + select the text (a quick query replacement)."""
        self._line.setFocus()
        self._line.selectAll()

    def place(self, host_width: int, host_height: int):
        """Position the panel at the top right of a host_width × host_height canvas.

        The panel is a child of the canvas (outside the layout), so it is placed by
        hand — on every canvas resize and on every open. The width is clamped to the
        canvas: on a narrow terminal the panel shrinks instead of leaving the view.
        """
        width = max(self.MIN_WIDTH, min(self.PREFERRED_WIDTH, int(host_width) - 2 * self.MARGIN))
        self.setFixedWidth(width)
        self.adjustSize()
        x = max(self.MARGIN, int(host_width) - self.width() - self.MARGIN)
        self.move(x, self.MARGIN)

    # ── Internal ───────────────────────────────────────────────────────────

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
            self._count.setText(_t("terminal.find.count").format(cur=current, total=total))
        except Exception:  # noqa: BLE001 — a formatting failure: show the numbers as-is
            self._count.setText(f"{current} / {total}")
