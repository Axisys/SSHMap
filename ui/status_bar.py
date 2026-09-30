# -*- coding: utf-8 -*-
"""The status bar that can offer an UNDO (DOCUMENTATION.md §41; the contract is `AGENTS.md` §4.2).

The undo stack is disciplined but invisible: this module is the affordance — after a DESTRUCTIVE
change the bar shows the action's OWN message next to an "Undo" button.

Pinned: it is ARMED in ONE place (`MainWindow._push_command()` calls `arm_undo()`, so work that is
not on the stack can never offer a way back); the message CARRIES it (`showMessage()` is the surface
every action already reports through, so the bar CONSUMES the first message after the arming); it
CLEARS itself after `OFFER_TIMEOUT_MS`, and `clearMessage()` / `_reset_undo_stack()` drop it at once;
and the layout is Qt's own (ONE widget with a label and a `QToolButton` in the `addWidget()` slot,
which Qt hides while a temporary message shows). `showMessage` / `clearMessage` are overridden for
PYTHON call sites only, and `offer_shown(str)` is the second channel the activity tap listens to."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStatusBar, QToolButton, QWidget

try:  # the ONE QSS registry (v1.4.3): no hardcoded colour/radius in a widget
    from . import theme_qss
except ImportError:  # flat layout: the ui/ directory itself is on sys.path
    try:
        from ui import theme_qss
    except ImportError:
        theme_qss = None

try:  # the vector "undo" glyph (the one the Edit menu carries)
    from .icons import get_icon
except ImportError:
    try:
        from icons import get_icon
    except ImportError:  # a stripped build — the button stays text-only
        def get_icon(name):  # noqa: N802 — stub with the same signature
            return None


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the ui/empty_state.py pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break the status bar
        return key


# ── the status-bar OVERFLOW policy ───────────────────────────────────────────
# The parts are NOT equal: the multi-input plaque > the status counters + the zoom % >
# the totals pair, so the totals are given up first (the counters and the zoom only get
# crowded). The threshold is MEASURED from the bar's own `sizeHint()`s
# (`status_bar_needed_width()`), never typed; the decision is ONE pure `is_compact()`.

#: The room the bar keeps between its widgets and the window edge.
STATUS_BAR_SLACK = 24


def status_bar_needed_width(widgets) -> int:
    """The width the bar needs to show EVERY widget of ``widgets`` (0 — nothing to show).

    A pure sum over `sizeHint()` (never a hardcoded string width): the caller passes the
    widgets it wants counted, so the policy can leave out the multi-input plaque while the
    mode is off and include it while it is on — the plaque is the FIRST priority, so its
    presence must make the bar ask for more room.
    """
    total = 0
    for widget in widgets or ():
        if widget is None:
            continue
        try:
            hint = widget.sizeHint()
            if hint is None or hint.width() <= 0:
                continue
            total += int(hint.width())
        except RuntimeError:
            continue  # Qt teardown — that widget is already destroyed
    return total + (STATUS_BAR_SLACK if total else 0)


def is_compact(width, needed) -> bool:
    """The ONE decision of the overflow policy: is ``width`` short of ``needed``?

    Both numbers must be positive: an unknown geometry (0 before the first layout pass, a
    broken value) is NOT compact — a missing measurement must never hide a widget.
    """
    try:
        available = int(width)
        required = int(needed)
    except (TypeError, ValueError):
        return False
    if available <= 0 or required <= 0:
        return False
    return available < required


class UndoStatusBar(QStatusBar):
    """The status bar of the main window, with the undo affordance (v1.5rc3).

    Public surface: `arm_undo()` (called by `_push_command`), `set_undo_callback()`
    (the window wires it to `_undo`), `clear_offer()`, `refresh_theme()` and the two
    read-only accessors the topical test uses (`is_offer_visible` / `offer_text`).
    """

    #: How long the offer stays on screen (ms) — the `showMessage(..., timeout)` idea.
    OFFER_TIMEOUT_MS = 12_000

    #: v1.5.2: the offer's own message (the activity panel's status tap needs it — the
    #: offer never reaches `messageChanged`, see the module docstring).
    offer_shown = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MainStatusBar")
        #: armed by `arm_undo()`; consumed by the NEXT `showMessage()` call
        self._armed = False
        self._undo_callback = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_offer)

        # The offer: [message][Undo] in ONE widget, so the text and the button travel
        # together and Qt's temporary-message machinery hides both at once.
        self._offer = QWidget(self)
        self._offer.setObjectName("UndoOffer")
        row = QHBoxLayout(self._offer)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._offer_label = QLabel("", self._offer)
        self._offer_label.setObjectName("UndoOfferLabel")
        self._offer_btn = QToolButton(self._offer)
        self._offer_btn.setObjectName("UndoOfferButton")
        self._offer_btn.setAutoRaise(True)
        self._offer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._offer_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._offer_btn.setText(_t("edit.undo"))
        self._offer_btn.setToolTip(_t("status.undo_hint"))
        icon = get_icon("undo")
        try:
            if icon is not None and not icon.isNull():
                self._offer_btn.setIcon(icon)
        except (RuntimeError, AttributeError):
            pass  # a dead icon must not break the status bar
        self._offer_btn.clicked.connect(self._on_undo_clicked)
        row.addWidget(self._offer_label)
        row.addWidget(self._offer_btn)
        row.addStretch(1)
        # `addWidget` = the left slot of the status bar, AFTER the temporary message:
        # Qt hides it while a message is displayed, which is the "the next message
        # clears the offer" behaviour for free.
        self.addWidget(self._offer, 1)
        self._offer.hide()
        self.refresh_theme()

    # ── Arming / display ────────────────────────────────────────────────────────

    def arm_undo(self) -> None:
        """Arm the affordance: the NEXT `showMessage()` carries the Undo button.

        Idempotent — a destructive gesture that pushes several commands (a node
        removal pushes the note-detach commands first) arms once, and the message
        that follows is the same one either way.
        """
        self._armed = True

    def is_armed(self) -> bool:
        return bool(self._armed)

    def set_undo_callback(self, callback) -> None:
        """The action of the button (the window passes its `_undo`)."""
        self._undo_callback = callback if callable(callback) else None

    def showMessage(self, text, timeout: int = 0):  # noqa: N802 — Qt API
        """Show a message; a freshly armed offer makes it the offer's message.

        Every Python call site of the application lands here. An armed offer consumes
        the message (and is disarmed by it); any other message CLEARS a visible offer,
        so the button never outlives the sentence it belonged to. Qt's own internal
        calls (a statusTip on menu hover) bypass this override and never carry a
        button — which is correct.
        """
        if self._armed:
            self._armed = False
            self._show_offer(str(text))
            return
        self._hide_offer()
        super().showMessage(text, timeout)

    def clearMessage(self):  # noqa: N802 — Qt API
        """Clear both the temporary message and a visible offer."""
        self._armed = False
        self._hide_offer()
        super().clearMessage()

    def currentMessage(self):  # noqa: N802 — Qt API
        """The message on screen — the OFFER's text while the offer is up.

        The offer replaces the temporary message (Qt hides the normal widgets while one
        is displayed, which is why the two cannot coexist), so the offer's label IS the
        current message from the caller's point of view. Answering it here keeps every
        existing consumer — and every test that reads `currentMessage()` after an action
        — truthful instead of empty.
        """
        if self.is_offer_visible():
            text = self.offer_text()
            if text:
                return text
        return super().currentMessage()

    def clear_offer(self) -> None:
        """Drop the offer (the timeout slot and the explicit path). Idempotent."""
        self._armed = False
        self._hide_offer()

    def _show_offer(self, text: str) -> None:
        """Display [text][Undo] — the temporary message is cleared, we ARE the message."""
        try:
            super().clearMessage()
            self._offer_label.setText(text)
            self._offer.show()
            self._timer.start(self.OFFER_TIMEOUT_MS)
        except RuntimeError:
            pass  # Qt teardown — nothing to show
        try:
            # v1.5.2: the activity panel's tap — emitted AFTER the offer is up, so a
            # listener that reads the bar sees the state the message describes.
            self.offer_shown.emit(str(text))
        except (RuntimeError, TypeError):
            pass  # Qt teardown / a dead receiver — the offer itself is already shown

    def _hide_offer(self) -> None:
        try:
            self._timer.stop()
            self._offer.hide()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _on_undo_clicked(self):
        """Run the window's undo and drop the offer (the click is the whole gesture)."""
        self.clear_offer()
        callback = self._undo_callback
        if callback is None:
            return
        try:
            callback()
        except RuntimeError:
            pass  # Qt teardown — the window is closing
        except Exception:  # noqa: BLE001 — a failed undo must not break the status bar
            pass

    # ── Introspection (the topical test) + theme ────────────────────────────────

    def is_offer_visible(self) -> bool:
        """True while the [message][Undo] widget is up.

        The check is `isHidden()` — the OFFER's own state — not `isVisible()`: this
        widget is a child of a status bar, and a child of a window that was never shown
        (every offscreen test) reports `isVisible() == False` although it is not hidden
        at all. The question the caller asks is "is the affordance up", not "is it on a
        screen right now".
        """
        try:
            return not self._offer.isHidden()
        except RuntimeError:
            return False

    def offer_text(self) -> str:
        """The message the offer carries ("" — no offer)."""
        try:
            return self._offer_label.text()
        except RuntimeError:
            return ""

    def refresh_theme(self):
        """Re-apply the theme to the button and the label (a QSS string is a VALUE)."""
        if theme_qss is not None:
            theme_qss.refresh(self._offer_btn, "status.undo_button")
            theme_qss.refresh(self._offer_label, "status.bar_counts")
        self._offer_btn.setText(_t("edit.undo"))       # follows a language switch too
        self._offer_btn.setToolTip(_t("status.undo_hint"))
