# -*- coding: utf-8 -*-
"""v1.4.4 (ROADMAP) — the motion standards of SSHMap: durations, easing and the two gestures.

Before this module every animation was a one-off: `ServerNode._start_pulse()` built its
own `QVariantAnimation` with its own numbers, and "move the camera" was whatever
`centerOn()`/`fitInView()` happened to do — an instant jump. The two "cosmetic" backlog
items of v1.2.6 (smooth camera flights, hover focus/dim on arrows) are implemented on ONE
foundation instead: this module.

**The standards.** Three durations, one easing:

* `DURATION_FAST` = 150 ms — feedback the user is already watching (an accent, a hover);
* `DURATION_NORMAL` = 250 ms — the standard gesture: a camera flight, a reveal;
* `DURATION_SLOW` = 300 ms — the longest gesture (fitting a large map end to end).
* `EASING` = `OutQuad` — fast at the start, settling at the end: the motion reads as
  "the map answered immediately", not as a linear slide.

**Everything here is interruptible**, and that is the property the acceptance pins:

* a NEW camera flight never jumps — it reads the CURRENT scale/centre as its start
  (`fly_camera()` stops the old flight without applying its target first);
* the USER always wins — the wheel, a mouse press (a drag) and every instant navigation
  path (`.centerOn`, `MapView.fit_to_content`, `reset_zoom`, the zoom steps) call
  `stop_camera()`/`MapView.stop_camera_flight()` before they move the camera;
* `stop_camera()`/`stop_scale_in()` leave the item where it is (no snap) unless the
  caller asks for the finished state.

**No `QGraphicsOpacityEffect` anywhere** — the v1.2.10 audit pinned it: an effect is a
separate render layer, and the pain at 500 nodes was measured. The card scale-in therefore
uses the item's OWN `setScale()`/`setOpacity()`, and the completion restores both to unit
(the transform origin set for the gesture is restored too, so `boundingRect()`,
`card_rect_scene()` and every `edge_point()` are bit-for-bit what they were).

**The motion switch (v1.5rc1, ROADMAP task 6).** `set_motion_enabled(False)` ("Reduce
motion" in the Appearance tab / the `theme.motion` key of config.json) makes every gesture
apply its FINAL state at once: `fly_camera()` builds a zero-length flight (the camera
lands on the target, `is_flying()` is False) and `scale_in()` settles the item instead of
growing it. Nothing else changes — the destinations, the clamps and the geometry are the
same code path, which is why the v1.4.4 acceptance stays green with the flag off. The
module owns ONE flag (`_motion_enabled`, default ON = every release before this one).

The module is Qt-light on purpose: the pure geometry helpers stay free functions, and the
only Qt classes used are `QObject`/`QVariantAnimation`/`QPointF`/`QTransform`.
"""

from typing import Optional

from PySide6.QtCore import QObject, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QTransform

# ── The standards (one place — do not invent new numbers next to a call site) ──────
DURATION_FAST = 150     # ms — hover/accent-grade feedback
DURATION_NORMAL = 250   # ms — a camera flight, a reveal (the default of fly_camera)
DURATION_SLOW = 300     # ms — the longest gesture

EASING = QEasingCurve.Type.OutQuad

# The node scale-in (v1.4.4, ROADMAP task 3): 200 ms, scale 0.9 -> 1.0 plus a fade-in.
SCALE_IN_MS = 200
SCALE_IN_FROM = 0.9

# ── The motion switch (v1.5rc1, ROADMAP task 6) ───────────────────────────────────
# "Reduce motion": with it OFF a gesture applies its FINAL state at once. The default
# is ON — the behaviour of every release before this one — and a broken config value
# falls back to it (`set_motion_enabled` accepts nothing but a real False as "off").
_motion_enabled = True


def set_motion_enabled(enabled) -> bool:
    """Turn the animations on/off (v1.5rc1). Returns the resulting flag.

    Anything but a literal ``False`` reads as ON, so a missing/broken config value
    can never silently disable the motion of a user who never asked for it.
    """
    global _motion_enabled
    _motion_enabled = enabled is not False
    return _motion_enabled


def motion_enabled() -> bool:
    """Is the motion on (the default) or reduced?"""
    return _motion_enabled


def _duration(ms) -> int:
    """The duration a gesture may use: its own, or 0 when the motion is reduced.

    Used by BOTH public gestures — the "final state at once" rule lives here, so a
    new gesture inherits it by asking for its duration through this function.
    """
    return max(0, int(ms)) if _motion_enabled else 0

# The attributes used to keep the live animations referenced. A QGraphicsItem is NOT a
# QObject, so a QVariantAnimation cannot be parented to it; remembering it on the item
# (and dropping the reference when it finishes) keeps it alive without a global registry.
_FLIGHT_ATTR = "_motion_camera_flight"
_SCALE_ATTR = "_motion_scale_anim"
_ORIGIN_ATTR = "_motion_scale_origin"


def _easing_curve() -> QEasingCurve:
    """A FRESH curve object per animation (a curve is a value; never hand out a shared one)."""
    return QEasingCurve(EASING)


# ── The camera: reading the state, writing the state ──────────────────────────────

def camera_scale(view) -> float:
    """The current scale of a QGraphicsView (1.0 — a view that cannot be read)."""
    try:
        return float(view.transform().m11())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 1.0


def camera_center(view) -> QPointF:
    """The scene point under the CENTRE of the viewport (QPointF(0,0) — unreadable view)."""
    try:
        viewport = view.viewport()
        return QPointF(view.mapToScene(viewport.rect().center()))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return QPointF(0.0, 0.0)


def zoom_bounds(view):
    """The view's own zoom range (`MapView.ZOOM_MIN`/`ZOOM_MAX`), with the 0.1..5.0 default."""
    return (float(getattr(view, "ZOOM_MIN", 0.1)), float(getattr(view, "ZOOM_MAX", 5.0)))


def clamp_scale(view, scale) -> float:
    """Clamp a target scale into the view's range; an unusable value → the current scale."""
    low, high = zoom_bounds(view)
    try:
        value = float(scale)
    except (TypeError, ValueError):
        return camera_scale(view)
    if value != value:  # NaN
        return camera_scale(view)
    return max(low, min(high, value))


def apply_camera(view, scale, center) -> bool:
    """Move the camera NOW (the one place that writes both halves of the transform).

    `MapView.apply_camera()` is the owner of the state (it also keeps `_zoom` and the
    status-bar percentage in sync); a duck-typed view without it gets the plain
    `QTransform` + `centerOn` pair.
    """
    setter = getattr(view, "apply_camera", None)
    if callable(setter):
        try:
            return bool(setter(float(scale), center))
        except (RuntimeError, TypeError):
            return False
    try:
        transform = QTransform()
        transform.scale(float(scale), float(scale))
        view.setTransform(transform)
        view.centerOn(center)
    except (AttributeError, RuntimeError, TypeError):
        return False
    return True


class CameraFlight(QObject):
    """ONE camera flight: scale + centre interpolated from the state at creation to the target.

    The start state is read in `__init__`, so a flight is always "from where we are now" —
    that is what makes a flight over a running one a restart instead of a jump.
    """

    def __init__(self, view, target_scale: float, target_center, ms: int = DURATION_NORMAL,
                 parent=None):
        super().__init__(parent)
        self._view = view
        self.start_scale = camera_scale(view)
        self.start_center = camera_center(view)
        self.target_scale = clamp_scale(view, target_scale)
        self.target_center = QPointF(target_center)
        self.duration_ms = max(0, int(ms))
        self._active = True
        self._anim: Optional[QVariantAnimation] = None
        if self.duration_ms > 0:
            anim = QVariantAnimation(self)
            anim.setDuration(self.duration_ms)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(_easing_curve())
            anim.valueChanged.connect(self._on_value)
            anim.finished.connect(self._on_finished)
            self._anim = anim
        else:
            self.progress(1.0)  # a zero-length flight is the instant move (no event loop needed)
            self._active = False

    @property
    def active(self) -> bool:
        """Is the flight still moving the camera?"""
        return self._active

    @property
    def animation(self):
        """The driving `QVariantAnimation` (None for a zero-length flight — the test seam)."""
        return self._anim

    def progress(self, fraction):
        """Apply the state at the RAW fraction (0..1) — linear, the easing lives in the animation.

        Public on purpose: a test drives the flight by hand instead of waiting on the
        event loop (the acceptance allows both).
        """
        if not self._active:
            return False
        try:
            t = float(fraction)
        except (TypeError, ValueError):
            return False
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        scale = self.start_scale + (self.target_scale - self.start_scale) * t
        center = QPointF(
            self.start_center.x() + (self.target_center.x() - self.start_center.x()) * t,
            self.start_center.y() + (self.target_center.y() - self.start_center.y()) * t,
        )
        if not apply_camera(self._view, scale, center):
            self.stop()
            return False
        return True

    def start(self) -> "CameraFlight":
        """Start the animation (a zero-length flight has already landed)."""
        if self._anim is not None and self._active:
            self._anim.start()
        return self

    def stop(self):
        """Cancel the flight and LEAVE the camera where it is (the new flight reads that state)."""
        self._active = False
        anim, self._anim = self._anim, None
        if anim is not None:
            try:
                anim.stop()
            except RuntimeError:
                pass  # Qt teardown — the animation is already destroyed

    def _on_value(self, value):
        if self._active:
            self.progress(value)

    def _on_finished(self):
        if not self._active:
            return
        self.progress(1.0)   # land exactly on the target (the eased curve ends at 1.0)
        self._active = False
        try:
            if getattr(self._view, _FLIGHT_ATTR, None) is self:
                setattr(self._view, _FLIGHT_ATTR, None)  # a landed flight no longer owns the camera
        except (AttributeError, RuntimeError):
            pass


def active_flight(view) -> Optional[CameraFlight]:
    """The flight currently owning the camera of this view, or None."""
    try:
        flight = getattr(view, _FLIGHT_ATTR, None)
    except RuntimeError:
        return None  # Qt teardown — the view is already destroyed
    return flight if isinstance(flight, CameraFlight) else None


def is_flying(view) -> bool:
    """Is a camera flight running on this view right now?"""
    flight = active_flight(view)
    return bool(flight is not None and flight.active)


def stop_camera(view) -> bool:
    """Cancel the view's flight (True — one was running). The camera does not move.

    The USER's wheel/drag and every instant navigation path call this (through
    `MapView.stop_camera_flight()`): manual control always wins over an animation.
    """
    flight = active_flight(view)
    if flight is None:
        return False
    try:
        setattr(view, _FLIGHT_ATTR, None)
    except (AttributeError, RuntimeError):
        pass
    flight.stop()
    return True


def fly_camera(view, target_scale, target_center, ms: int = DURATION_NORMAL):
    """Fly the camera to `target_scale` + `target_center` over `ms` (default 250 ms, OutQuad).

    Returns the `CameraFlight` (or None when the view/target is unusable). The start state
    is the CURRENT one, and an already running flight is stopped — never fast-forwarded —
    so chaining two flights cannot produce a jump.

    v1.5rc1: with the motion reduced (`set_motion_enabled(False)`) the duration becomes 0,
    which lands the camera on the target inside this call — the same clamps, the same
    "from where we are" start, no frames.
    """
    if view is None:
        return None
    try:
        center = QPointF(target_center)
    except (TypeError, ValueError):
        return None
    stop_camera(view)
    flight = CameraFlight(view, target_scale, center, _duration(ms))
    try:
        setattr(view, _FLIGHT_ATTR, flight)
    except (AttributeError, RuntimeError):
        return None
    return flight.start()


# ── The node scale-in ─────────────────────────────────────────────────────────────

def _item_center(item) -> QPointF:
    """The CARD centre of a node in ITEM coordinates (the fallback — the painted rect).

    Scaling around the centre (not around the item's origin, which is the top-left
    corner) keeps every geometric consequence of the card stable while the node grows:
    the group membership and the pinned-note anchor are computed from the centre.
    """
    for name in ("card_rect", "boundingRect"):
        getter = getattr(item, name, None)
        if callable(getter):
            try:
                rect = getter()
            except (RuntimeError, TypeError):
                continue
            try:
                if not rect.isEmpty():
                    return QPointF(rect.center())
            except AttributeError:
                continue
    return QPointF(0.0, 0.0)


def _item_origin(item) -> QPointF:
    """The current transform origin of the item (QPointF(0,0) — unreadable)."""
    try:
        return QPointF(item.transformOriginPoint())
    except (AttributeError, RuntimeError, TypeError):
        return QPointF(0.0, 0.0)


def settle_scale_in(item, origin=None):
    """Put the item back to unit scale/opacity (the end state of the scale-in). A DIM is kept.

    The nodes that already hang off the card are re-anchored afterwards: an arrow (or a
    pinned note) that was created while the card was still small has its geometry computed
    from the SCALED rect, and the end of the gesture must not leave it short — the same
    `update_connections_for_node()` call every other geometry change of a node makes.
    """
    try:
        item.setScale(1.0)
        dimmed = bool(getattr(item, "_dimmed", False))
        item.setOpacity(float(getattr(item, "DIM_OPACITY", 1.0)) if dimmed else 1.0)
        if origin is not None:
            item.setTransformOriginPoint(origin)
        item.update()
    except (AttributeError, RuntimeError):
        pass  # Qt teardown — the item is already destroyed
    try:
        scene = item.scene()
    except (AttributeError, RuntimeError):
        return
    if scene is None:
        return
    updater = getattr(scene, "update_connections_for_node", None)
    if callable(updater):
        try:
            updater(item)   # the arrows + the pinned notes of this card
        except (RuntimeError, TypeError):
            pass


def scale_in(item, ms: int = SCALE_IN_MS, from_scale: float = SCALE_IN_FROM):
    """A new card APPEARS: `ms` (default 200) of scale `from_scale` → 1.0 and opacity 0 → 1.

    The item's OWN `setScale()`/`setOpacity()` — never a `QGraphicsOpacityEffect` (the
    v1.2.10 audit). The completion restores the transform origin, so nothing downstream
    (arrows, pinned notes, group membership, `boundingRect()`) is shifted by the gesture.

    Returns the driving `QVariantAnimation` (or None when the item is unusable, or when
    the motion is reduced — v1.5rc1: the item is then settled at once and there is no
    animation to return). The animation is remembered ON the item, because a
    QGraphicsItem cannot parent a QObject.
    """
    if item is None:
        return None
    try:
        from_scale = float(from_scale)
    except (TypeError, ValueError):
        from_scale = SCALE_IN_FROM
    origin = _item_origin(item)
    try:
        item.setTransformOriginPoint(_item_center(item))
        setattr(item, _ORIGIN_ATTR, origin)
    except (AttributeError, RuntimeError):
        return None
    state = {"done": False}

    def _apply(value):
        if state["done"]:
            return
        try:
            t = float(value)
        except (TypeError, ValueError):
            return
        try:
            item.setScale(from_scale + (1.0 - from_scale) * t)
            item.setOpacity(t)
        except RuntimeError:
            state["done"] = True  # the item died mid-flight — nothing left to animate

    def _finish():
        state["done"] = True
        settle_scale_in(item, origin)
        for attr in (_SCALE_ATTR, _ORIGIN_ATTR):
            try:
                setattr(item, attr, None)
            except (AttributeError, RuntimeError):
                pass

    duration = _duration(ms)
    if duration <= 0:
        _finish()
        return None
    anim = QVariantAnimation()
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(_easing_curve())
    anim.valueChanged.connect(_apply)
    anim.finished.connect(_finish)
    try:
        setattr(item, _SCALE_ATTR, anim)
    except (AttributeError, RuntimeError):
        return None
    _apply(0.0)   # the first frame is the START state (an event loop may be far away)
    anim.start()
    return anim


def active_scale_in(item):
    """The scale-in animation currently running on the item, or None."""
    try:
        anim = getattr(item, _SCALE_ATTR, None)
    except RuntimeError:
        return None
    return anim if isinstance(anim, QVariantAnimation) else None


def is_scaling_in(item) -> bool:
    """Is a scale-in animation running on this item?"""
    return active_scale_in(item) is not None


def stop_scale_in(item, settle: bool = True) -> bool:
    """Cancel the item's scale-in (True — one was running).

    `settle=True` (the default) puts the item back to unit scale/opacity: a cancelled
    appearance must not leave a half-sized card behind on the map.
    """
    anim = active_scale_in(item)
    if anim is None:
        return False
    try:
        origin = getattr(item, _ORIGIN_ATTR, None)
        setattr(item, _SCALE_ATTR, None)
        setattr(item, _ORIGIN_ATTR, None)
    except (AttributeError, RuntimeError):
        origin = None
    try:
        anim.stop()
    except RuntimeError:
        pass
    if settle:
        settle_scale_in(item, origin)
    return True
