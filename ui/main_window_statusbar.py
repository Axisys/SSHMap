"""`StatusBarMixin` — the status bar's widgets, their overflow policy and the "problems only" lens (AGENTS.md §4.1, §4.18).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: the two permanent widget classes (`_StatusCounter`, `_ProblemsChip`) with `STATUS_FILTER_ORDER`
and `_WIDGET_MAX_WIDTH`, the MEASURED overflow threshold (`_sync_status_bar_overflow()` with its two pure
helpers), the counters' composition hook (`_update_counts_label()`) and the transient lens the chip toggles
(`_set_problems_only()` / `_sync_problems_chip()`). The map DIMMING the lens drives stays with the window
(its ONE owner). The facade re-exports the four names for the suite. Mechanism — `DOCUMENTATION.md` §15, §36."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel

try:  # v1.8rc3: the toolbar's panel cluster and the ONE "in trouble" predicate of the lens
    from ..graphics.node_group import is_in_trouble as node_in_trouble
except ImportError:
    from graphics.node_group import is_in_trouble as node_in_trouble

try:  # v1.4.3: the ONE QSS registry (a QSS string is a VALUE — re-applied by refresh_theme)
    from . import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None

try:  # v1.5rc4: the status-bar overflow policy — the ONE pure decision plus the measured width
    from .status_bar import is_compact as status_bar_is_compact
    from .status_bar import status_bar_needed_width
except ImportError:
    try:
        from status_bar import is_compact as status_bar_is_compact
        from status_bar import status_bar_needed_width
    except ImportError:  # a stripped build — no overflow policy
        status_bar_is_compact = None
        status_bar_needed_width = None


# ── v1.4.5 (ROADMAP task 3): the clickable status counters of the status bar ───

# The order the three status counters appear in (the same order the cards, the dots
# and the status bar text have always used).
STATUS_FILTER_ORDER = ("online", "warn", "offline")

class _StatusCounter(QLabel):
    """One status counter of the status bar — a CLICKABLE filter (v1.4.5, task 3).

    The counters were passive text ("Online: 3 | Warn: 1 | Offline: 2") next to the
    server/connection totals. Split out of one label into three widgets they can carry
    a click: the WINDOW owns what the click means (the sidebar status filter), the
    widget only reports it — the `_CollapseStrip` pattern.

    Signals:
        clicked(str) — the status this counter stands for ("online"/"warn"/"offline").
    """

    clicked = Signal(str)

    def __init__(self, status: str, parent=None):
        super().__init__("", parent)
        self.status = str(status)
        self._active = False
        self.setObjectName(f"StatusCounter_{self.status}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def is_active(self) -> bool:
        """Is the sidebar currently filtered by THIS status?"""
        return bool(self._active)

    def set_active(self, active: bool) -> None:
        """Mark the counter as the applied filter (bold) or as a plain counter."""
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self.refresh_theme()

    def refresh_theme(self):
        """Re-apply the counter's stylesheet (a QSS string is a value — v1.4.3)."""
        if theme_qss is None:
            return
        theme_qss.refresh(self, "status.bar_filter_active" if self._active
                          else "status.bar_filter")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                self.clicked.emit(self.status)
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone
            event.accept()
            return
        super().mousePressEvent(event)

class _ProblemsChip(QLabel):
    """The "problems only" toggle of the status bar (v1.5.4, ROADMAP task 2).

    The lens has to be reachable from somewhere, and the v1.4.5 status counters are the
    precedent the ROADMAP names: a CLICKABLE piece of the status bar beside the three
    status counters, transient by construction (nothing is written to `config.json`), so
    a restart never leaves the map dimmed for no visible reason. It is deliberately NOT a
    registry action — it is not a menu item, and the counters next to it are not either.

    The count is a TOTAL (the servers that need attention right now), never the filtered
    view: the counters keep telling the whole truth while a lens is on. The WINDOW owns
    what the click means and what the count is; this widget only reports the click and
    paints its active state — the `_StatusCounter` split.
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._active = False
        self.setObjectName("ProblemsChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def is_active(self) -> bool:
        """Is the "problems only" lens on?"""
        return bool(self._active)

    def set_active(self, active: bool) -> None:
        """Mark the chip as the applied lens (bold) or as a plain counter."""
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self.refresh_theme()

    def refresh_theme(self):
        """Re-apply the chip's stylesheet (a QSS string is a value — v1.4.3)."""
        if theme_qss is None:
            return
        theme_qss.refresh(self, "status.bar_filter_active" if self._active
                          else "status.bar_filter")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                self.clicked.emit()
            except RuntimeError:
                pass  # Qt teardown — the receiver is gone
            event.accept()
            return
        super().mousePressEvent(event)


class StatusBarMixin:
    """The status bar's widgets, their overflow policy and the "problems only" lens (AGENTS.md §4.1, §4.18)."""

    # ── the status-bar overflow policy (the pinned priority — `ui/status_bar.py`) ──
    # The multi-input plaque, then the three CLICKABLE status counters and the zoom percentage,
    # and only then the "Servers / Connections" totals: the totals are the ONE thing that leaves
    # the bar, because the interactive part must not be the first to disappear. ONE method, ONE
    # threshold, and the widgets are only ever HIDDEN — a wide window gets the pair back untouched.

    def _sync_status_bar_overflow(self, width=None) -> bool:
        """Hide the totals on a window too narrow for the whole bar (True — compact).

        ``width=None`` asks the live window. The counters, the zoom label and the
        multi-input plaque are deliberately NOT touched: their visibility belongs to the
        filter state and to the multi-input mode, never to a resize. The bar's own
        `sizeHint()` sum is the threshold (`_status_bar_overflow_needed`), so the policy
        follows the live font and language.
        """
        compact = False
        if status_bar_is_compact is not None:
            try:
                needed = self._status_bar_overflow_needed()
                compact = bool(status_bar_is_compact(
                    self.width() if width is None else width, needed))
            except (TypeError, ValueError, RuntimeError):
                compact = bool(getattr(self, "_status_bar_compact", False))
        if compact == getattr(self, "_status_bar_compact", None):
            return compact
        self._status_bar_compact = compact
        counts = getattr(self, "counts_label", None)
        if counts is not None:
            try:
                counts.setVisible(not compact)
            except RuntimeError:
                pass  # Qt teardown — the label is already destroyed
        return compact

    def _status_bar_permanent_widgets(self) -> list:
        """The permanent widgets of the status bar, in the priority order of the policy.

        The multi-input plaque is counted ONLY while the mode shows it: it is the highest
        priority of the rule, so an ACTIVE plaque must make the bar ask for more room (and
        push the totals out earlier) — while an absent one must cost nothing.
        """
        widgets = [getattr(self, "counts_label", None)]
        for status in STATUS_FILTER_ORDER:
            widgets.append((getattr(self, "status_filter_labels", None) or {}).get(status))
        # v1.5.4 (ROADMAP task 2): the "problems only" chip belongs to the interactive
        # family the policy never gives up — it is a CONTROL, not passive text.
        widgets.append(getattr(self, "problems_chip", None))
        widgets.append(getattr(self, "zoom_label", None))
        plaque = getattr(self, "_multi_plaque", None)
        if plaque is not None:
            try:
                if plaque.isVisible():
                    widgets.append(plaque)
            except RuntimeError:
                pass  # Qt teardown — the plaque is already destroyed
        return widgets

    def _status_bar_overflow_needed(self) -> int:
        """How wide the bar must be to show everything (the measured threshold)."""
        if status_bar_needed_width is None:
            return 0
        return int(status_bar_needed_width(self._status_bar_permanent_widgets()))

    def status_bar_compact(self) -> bool:
        """True while the totals pair is hidden (the topical test's seam)."""
        return bool(getattr(self, "_status_bar_compact", False))

    # ── v1.5.4 (ROADMAP task 2): the "problems only" lens ───────────────────────

    def _on_problems_chip_clicked(self):
        """The status-bar chip: toggle the lens (the `_on_status_filter_clicked` pattern)."""
        self._set_problems_only(not bool(getattr(self, "_problems_only", False)))

    def _set_problems_only(self, active: bool, announce: bool = True) -> bool:
        """Turn the "problems only" lens on/off. Returns True when the state changed.

        TRANSIENT by construction: the flag lives in memory only (never a `config.json`
        key) — the v1.4.5 status-filter rule, because a restart must not leave the map
        dimmed for no visible reason. The counters are untouched (a lens is a view, not
        a fact), and the whole effect is delegated to the ONE dim owner.
        """
        active = bool(active)
        if active == bool(getattr(self, "_problems_only", False)):
            return False
        self._problems_only = active
        chip = getattr(self, "problems_chip", None)
        if chip is not None:
            try:
                chip.set_active(active)
            except RuntimeError:
                pass  # Qt teardown — the chip is already destroyed
        self._apply_map_dimming()
        if announce:
            try:
                self.statusBar().showMessage(
                    self.t("statusbar.problems.active") if active else self.t("status.ready"))
            except Exception:  # noqa: BLE001 — the hint must not break the lens
                pass
        return True

    @property
    def problems_only(self) -> bool:
        """v1.5.4: is the map showing only the servers that need attention?"""
        return bool(getattr(self, "_problems_only", False))

    def _trouble_nodes(self) -> list:
        """The nodes the lens keeps highlighted (warn / offline / stale) — the TOTALS."""
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return []
        return [n for n in nodes
                if node_in_trouble(getattr(n, "status", ""),
                                   bool(getattr(n, "is_stale", False)))]

    def _sync_problems_chip(self) -> int:
        """Re-text the chip with the number of servers that need attention (the TOTAL).

        The count is the whole truth, not the filtered view: a lens never rewrites a
        counter (the v1.4.5 rule). Called by the composition hook and by the freshness
        tick, because a datum that has just grown old IS a new problem.
        """
        chip = getattr(self, "problems_chip", None)
        count = len(self._trouble_nodes())
        if chip is None:
            return count
        try:
            chip.setText(self.t("statusbar.problems", count=count))
            chip.setToolTip(self.t("statusbar.problems.tooltip"))
            chip.set_active(bool(getattr(self, "_problems_only", False)))
        except RuntimeError:
            pass  # Qt teardown — the chip is already destroyed
        return count

    def _update_counts_label(self):
        """UI polish: the permanent counters of the status bar.

        v1.4.5 (ROADMAP task 3): the "Servers / Connections" pair and the three STATUS
        counters live in two kinds of widget — the status ones are CLICKABLE filters of
        the sidebar. The counters always show the TOTALS: the filter changes the tree,
        never the numbers (a filter is a view, not a fact). This is also the single
        composition hook the first-run empty state hangs on (`_sync_empty_state`).
        """
        try:
            nodes = list(self.scene.nodes())
            conns = self.scene.arrow_count()
        except (AttributeError, RuntimeError):
            return  # the scene is not created yet / already destroyed
        statuses = [getattr(n, "status", "") for n in nodes]
        self.counts_label.setText(
            self.t("status.counts", servers=len(nodes), connections=conns))
        active = getattr(self, "_status_filter", "")
        for status, counter in (getattr(self, "status_filter_labels", {}) or {}).items():
            try:
                counter.setText(self.t(f"statusbar.filter.{status}",
                                       count=statuses.count(status)))
                counter.setToolTip(self.t("statusbar.filter.tooltip"))
                counter.set_active(status == active)
            except RuntimeError:
                continue  # Qt teardown — this counter is already destroyed
        # v1.5.4 (ROADMAP task 2): the "problems only" chip counts the servers that need
        # attention — a TOTAL like the three status counters beside it, never the view.
        self._sync_problems_chip()
        self._sync_empty_state()
