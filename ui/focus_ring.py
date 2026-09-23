# -*- coding: utf-8 -*-
"""v1.5rc4 (ROADMAP task 5): the VISIBLE focus of the three keyboard domains.

The v1.5 line closed the gap between what the map SHOWS and what the chrome SAYS; the
last thing the chrome never answered is "where do my keys go?". The window has three
keyboard domains — the **map**, the **sidebar** and the **terminal** — and until now
nothing on screen told the user which of them owns the keyboard: in
``terminal_mode = "tabs"`` the session shares the window with the map, so "does Ctrl+F
search the map or reach the shell?" had no visible answer at all.

This module is that answer, in ONE place, following the two rules of the line:

  * **the tone is not new.** It is ``theme.ACCENT_STRONG`` — the v1.5rc1 role for INK
    on a surface ("the accent family exists to be readable"), never a fresh colour and
    never the decorative ``accent`` (which measured 1.96:1 as ink on a LIGHT surface
    — the very number the v1.5rc1 gate was written for). A ring therefore reads on both
    instances by construction, and ``tests/test_chrome.py`` pins the colour to that one
    field instead of to a literal;
  * **one indicator, three consumers.** ``FocusRing`` owns the state
    (``set_active()`` / ``is_active()``) and the two ways a domain can show it:

      - ``paint(painter, rect)`` — a 2 px frame drawn by a CUSTOM canvas (``MapView``
        paints it over the viewport, ``TerminalWidget`` over its cell grid);
      - ``styled_widget`` — a STANDARD widget (the sidebar's ``QTreeWidget``) that
        carries the same frame as a stylesheet, from the ONE QSS registry
        (``theme_qss`` — the "no hardcoded QSS in a widget" rule of §4.6).

The width is a declared constant (``RING_WIDTH``) and the two registry names
(``STYLE_ACTIVE`` / ``STYLE_INACTIVE``) keep the frame's thickness in BOTH states, so
switching the focus on never reflows the layout the user is looking at.

The ring NEVER forces a repaint of a whole window: it repaints the widgets it is attached
to, and it is deliberately silent when nothing changed (the ``set_active`` early return) —
a focus walk over a large map must not cost a repaint per Keystroke that is not a focus
change.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.4.3: the ONE QSS registry (the standard-widget half of the indicator)
    from . import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None

#: The frame thickness, in pixels — the SAME value in both states (a focus change must
#: not move the layout) and the same for all three domains. The number is declared by
#: the QSS registry (`theme_qss.FOCUS_RING_WIDTH`), because the standard-widget half of
#: the indication is a stylesheet and the two halves must agree.
RING_WIDTH = int(getattr(theme_qss, "FOCUS_RING_WIDTH", 2))

#: The QSS registry names of the standard-widget half (stylesheets are VALUES — §4.6).
STYLE_ACTIVE = "focus.widget"
STYLE_INACTIVE = "focus.widget_off"


def ring_color() -> str:
    """The ONE colour of the focus indication — the STRONG accent (v1.5rc1 role).

    Never a literal and never the decorative accent: the ring is a line the user must be
    able to see on the canvas, on the window surface and inside a terminal card alike.
    """
    return str(theme.ACCENT_STRONG)


def ring_pen(width: int = RING_WIDTH) -> QPen:
    """A pen of the ring (built at call time — the colour follows a theme switch)."""
    pen = QPen(QColor(ring_color()), float(width))
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    return pen


def paint_ring(painter, rect) -> bool:
    """Draw the focus frame of ``rect`` into ``painter`` (False — nothing to draw).

    The ONE painter of the indication: the two custom canvases call it and neither of
    them owns a copy of the geometry. The frame is drawn INSIDE the rectangle (the
    half-width inset), so a widget's outermost pixels are never clipped away, and
    ``NoBrush`` guarantees it never covers what the domain is showing.
    """
    if painter is None or rect is None:
        return False
    try:
        area = QRectF(rect)
    except (TypeError, ValueError):
        return False
    if area.isEmpty():
        return False
    half = RING_WIDTH / 2.0
    painter.save()
    try:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(ring_pen())
        painter.drawRect(area.adjusted(half, half, -half, -half))
    finally:
        painter.restore()
    return True


class FocusRing:
    """The focus state of ONE keyboard domain, and the two ways to show it.

    ``FocusRing(styled_widget=tree)`` — a standard widget: the frame is a stylesheet
    from the QSS registry (applied with ``setStyleSheet`` DIRECTLY, never through
    ``theme_qss.refresh()``: that helper hides and shows the widget, and re-showing a
    widget clears the focus we are reacting to). ``FocusRing()`` — a custom canvas: the
    owner paints through ``paint(painter, rect)``.

    Public surface: ``set_active()`` (True only on a real change), ``is_active()``,
    ``owner`` / ``styled_widget``, ``apply()`` (re-apply the stylesheet — the
    ``refresh_theme()`` path) and ``paint()``.
    """

    def __init__(self, owner=None, styled_widget=None):
        self.owner = owner
        self.styled_widget = styled_widget
        self._active = False
        if styled_widget is not None:
            self.apply()

    # ── state ────────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """True while this domain owns the keyboard (the ring is being shown)."""
        return bool(self._active)

    def set_active(self, active) -> bool:
        """Turn the ring on/off; returns True only when the state really changed."""
        active = bool(active)
        if active == self._active:
            return False
        self._active = active
        self.apply()
        self._repaint()
        return True

    def follow(self, widget) -> bool:
        """Adopt ``widget.hasFocus()`` as the state (the focus-event one-liner)."""
        try:
            return self.set_active(bool(widget.hasFocus()))
        except RuntimeError:
            return False  # Qt teardown — the widget is already destroyed

    # ── the standard-widget half ─────────────────────────────────────────────

    def apply(self):
        """(Re-)apply the stylesheet of the current state to ``styled_widget``.

        Safe for a widget-less ring (the custom canvases) and never raises: a cosmetic
        frame must not be able to break a focus event during teardown.
        """
        widget = self.styled_widget
        if widget is None or theme_qss is None:
            return
        try:
            widget.setStyleSheet(theme_qss.style(STYLE_ACTIVE if self._active
                                                 else STYLE_INACTIVE))
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def refresh_theme(self):
        """Re-apply after a theme switch (the colour of the ring is read live)."""
        self.apply()
        self._repaint()

    # ── the custom-canvas half ───────────────────────────────────────────────

    def paint(self, painter, rect) -> bool:
        """Paint the ring into an active ``QPainter`` (False — inactive/nothing to do)."""
        if not self._active:
            return False
        return paint_ring(painter, rect)

    # ── internals ────────────────────────────────────────────────────────────

    def _repaint(self):
        """Ask the owner (or the styled widget) to repaint — never the whole window."""
        for target in (self.owner, self.styled_widget):
            if target is None:
                continue
            try:
                target.update()
            except (RuntimeError, AttributeError):
                continue
