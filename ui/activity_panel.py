# -*- coding: utf-8 -*-
"""v1.5.2 (ROADMAP task 3): the activity panel — the HISTORY, never a second status bar.

The buffer of `modules/activity_log.py` is invisible without a surface, and the surface
has one rule to obey: the status bar and the SFTP progress line stay the "now", the
Plugins menu keeps the current records — **this panel lists what HAPPENED**. It is a
log view over a bounded ring, not a live status widget: a fact is displayed here as a
row with a time, and clearing the status bar (or finishing a transfer) does not remove
it, while a row never becomes the current state of anything.

Pinned decisions (ROADMAP v1.5.2, task 3):

  * **A non-modal WINDOW, not a floating panel.** The v1.5rc4 floating-panel priority
    resolver (`MainWindow._overlay_panel_rects()` + the "the collapse diamond is never
    covered" rule) governs the panels that live INSIDE the canvas — the legend, the
    minimap, the search bar, the first-run hint. A window keeps the new surface out of
    that rule entirely: it is not a child of `MapView`, so it cannot cover the diamond,
    cannot be dragged into an export and cannot fight the legend for a corner. The
    rejected alternative (a fifth floating panel) would have had to join the resolver
    for no benefit.
  * **It owns `retranslate()`** (the v1.3.3.1 invariant) — reached from
    `MainWindow._apply_ui_translations()`. Only the CHROME is translated (the window
    title, the level captions, the column headers, Clear); the event LINES stay English,
    because they are logging lines (the i18n cost is the chrome, never one key per event
    kind — `modules/activity_log.py` owns that rule).
  * **Visibility is ONE `config.json` key** (`ui_activity_panel`, written by its owner
    with a merge write — the `ui_legend`/`ui_minimap` pattern). The settings hub's
    `collect()` is untouched: this is UI state, not a preference.
  * **The newest first**, the ring's bound as the row cap, and a level filter whose
    policy is the PURE `activity_log.matches_level()` — the widget renders, it does not
    decide.

Threading: the buffer is written from worker threads (probes, SFTP, DNS), so the panel
never listens to it directly — `_ActivityBridge` (a QObject living in the GUI thread)
turns every append into ONE queued Qt signal, and the rows are rebuilt by a coalescing
timer (`REFRESH_MS`), which is what keeps a burst of 200 records from rebuilding the
view 200 times.
"""

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

try:  # the module is the ONE owner of the ring (the panel only renders it)
    from modules import activity_log as AL
except ImportError:  # flat layout: the project root is on sys.path
    import activity_log as AL  # type: ignore


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the ui/status_bar.py pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break the panel
        return key


class _ActivityBridge(QObject):
    """The GUI-thread half of the ring (v1.5.2): one queued signal per change.

    A `logging.Handler` runs in the thread that logged — copying the event straight into
    a `QTreeWidget` from there would be a cross-thread widget mutation. A signal emitted
    on a QObject that lives in the GUI thread is delivered QUEUED (Qt decides by
    comparing the emitting thread with the receiver's), so this tiny bridge is the whole
    marshalling layer. It detaches itself from the ring when its C++ object dies, which
    is what keeps a closed window from being kept alive by the buffer's listener list.
    """

    changed = Signal(object)

    def __init__(self, buffer, parent=None):
        super().__init__(parent)
        self._buffer = buffer
        self._callback = self._emit_changed     # a STABLE identity for remove_listener
        try:
            buffer.add_listener(self._callback)
            self.destroyed.connect(self._detach)
        except Exception:  # noqa: BLE001 — a dead buffer must not break the panel
            pass

    def _emit_changed(self, event):
        try:
            self.changed.emit(event)
        except RuntimeError:
            pass  # Qt teardown — the receiver is already gone

    def _detach(self, *_args):
        try:
            self._buffer.remove_listener(self._callback)
        except Exception:  # noqa: BLE001 — detaching is best effort
            pass


class ActivityPanel(QDialog):
    """The activity history window (v1.5.2) — non-modal, read-only, memory-backed."""

    #: How long the panel waits before rebuilding its rows (ms) — the burst coalescer.
    #: A probe round or an import posts dozens of records within a few milliseconds;
    #: without the wait the same rows would be built dozens of times.
    REFRESH_MS = 80

    #: The column widths (px) of the four columns; the message column stretches.
    COLUMN_WIDTHS = (72, 78, 190)

    def __init__(self, buffer=None, parent=None):
        super().__init__(parent)
        self._buffer = buffer if buffer is not None else AL.get_activity_buffer()
        self._dirty = False
        #: The window sets this to keep its View-menu item in step with a user close.
        self.on_hidden = None

        self.setModal(False)
        self.resize(780, 420)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.level_combo = QComboBox(self)
        for key in AL.LEVEL_KEYS:      # the order of LEVEL_KEYS is the combo's order
            self.level_combo.addItem(key, key)
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        row.addWidget(self.level_combo)
        row.addStretch(1)
        self.clear_btn = QPushButton(self)
        self.clear_btn.clicked.connect(self.clear)
        row.addWidget(self.clear_btn)
        layout.addLayout(row)

        self.empty_label = QLabel(self)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label, 1)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("ActivityTree")
        self.tree.setColumnCount(4)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        header = self.tree.header()
        for index, width in enumerate(self.COLUMN_WIDTHS):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(index, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        layout.addWidget(self.tree, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self._bridge = _ActivityBridge(self._buffer, self)
        self._bridge.changed.connect(self._on_changed)

        self.retranslate()
        self.refresh()

    # ── The chrome (translated) ────────────────────────────────────────────────

    def retranslate(self):
        """Re-text the CHROME only (a language switch). Idempotent, never raises.

        The event LINES are deliberately untouched: they are logging lines, and the
        module docstring pins why (the chrome is the i18n cost of the panel).
        """
        try:
            self.setWindowTitle(_t("activity.title"))
            self.clear_btn.setText(_t("activity.clear"))
            self.empty_label.setText(_t("activity.empty"))
            for index, key in enumerate(AL.LEVEL_KEYS):
                self.level_combo.setItemText(index, _t(f"activity.level.{key}"))
            self.tree.setHeaderLabels([_t("activity.col.time"), _t("activity.col.level"),
                                       _t("activity.col.source"),
                                       _t("activity.col.message")])
        except RuntimeError:
            return  # Qt teardown — nothing to re-text
        self.clear_btn.setToolTip(_t("activity.clear"))

    def current_level(self) -> str:
        """The active level-filter key ("all" … — `activity_log.LEVEL_KEYS`)."""
        try:
            data = self.level_combo.currentData()
        except RuntimeError:
            return "all"
        return str(data or "all")

    def set_level(self, key: str) -> None:
        """Switch the level filter programmatically (the window / test seam)."""
        try:
            index = self.level_combo.findData(str(key))
            if index >= 0 and index != self.level_combo.currentIndex():
                self.level_combo.setCurrentIndex(index)   # emits → _on_level_changed
                return
        except RuntimeError:
            return  # Qt teardown
        self.refresh()

    def _on_level_changed(self, _index: int):
        """The user picked a filter — rebuild the rows (the policy is the buffer's)."""
        self.refresh()

    # ── The history ────────────────────────────────────────────────────────────

    def _on_changed(self, _event=None):
        """One record changed the ring (any thread) → refresh AFTER the burst.

        While the panel is hidden the rebuild is skipped entirely and only the dirty
        flag is set: nothing is displayed, and the next `set_visible(True)` reads the
        ring anyway.
        """
        self._dirty = True
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        if not self._timer.isActive():
            self._timer.start(self.REFRESH_MS)

    def refresh(self):
        """Rebuild the rows from the ring (newest first, filtered). The test seam."""
        self._timer.stop()
        self._dirty = False
        try:
            events = self._buffer.newest_first()
        except Exception:  # noqa: BLE001 — a broken buffer shows an empty panel
            events = []
        key = self.current_level()
        rows = [event for event in events if AL.matches_level(event, key)]
        try:
            self.tree.setUpdatesEnabled(False)
            self.tree.clear()
            for event in rows:
                item = QTreeWidgetItem(self.tree)
                item.setText(0, event.time_text())
                item.setText(1, event.level)
                item.setText(2, event.source)
                item.setText(3, self._message_text(event))
                for column in range(4):
                    item.setToolTip(column, event.message)
        except RuntimeError:
            return  # Qt teardown — the tree is already destroyed
        finally:
            try:
                self.tree.setUpdatesEnabled(True)
            except RuntimeError:
                pass
        try:
            has_rows = bool(rows)
            self.tree.setVisible(has_rows)
            self.empty_label.setVisible(not has_rows)
        except RuntimeError:
            pass

    @staticmethod
    def _message_text(event) -> str:
        """The message cell: the line, plus the repeat counter of a coalesced burst."""
        text = event.message
        if getattr(event, "repeats", 1) > 1:
            text = f"{text}  ×{event.repeats}"
        return text

    def clear(self):
        """Clear the HISTORY (the ring itself, not only the view)."""
        try:
            self._buffer.clear()
        except Exception:  # noqa: BLE001 — clearing is best effort
            pass
        self.refresh()

    # ── Visibility (the window owns the config key) ────────────────────────────

    def set_visible(self, visible: bool):
        """Show/hide the window; showing always re-reads the ring."""
        if visible:
            self.refresh()
            self.show()
            self.raise_()
            self.activateWindow()
        else:
            self.hide()

    def is_shown(self) -> bool:
        """`isHidden()` — the v1.5rc3 status-bar rule: a child of a never-shown window
        reports `isVisible() == False` although it is not hidden at all, so the question
        "did the user close it" is asked of the HIDDEN state."""
        try:
            return not self.isHidden()
        except RuntimeError:
            return False

    def closeEvent(self, event):  # noqa: N802 — Qt API
        """The user closed the window: hide it (the history survives) and tell the owner.

        The window keeps the panel instance for the whole session on purpose: reopening
        it shows the same history, and the ring is the only owner of the data. The owner
        is notified so the View-menu item (which owns the state and the hotkey) can
        follow the close instead of lying about it.
        """
        self.hide()
        event.accept()
        callback = self.on_hidden
        if callable(callback):
            try:
                callback()
            except Exception:  # noqa: BLE001 — a broken callback must not break a close
                pass

    # ── Introspection (the topical test) ───────────────────────────────────────

    def row_count(self) -> int:
        """How many rows are displayed right now."""
        try:
            return int(self.tree.topLevelItemCount())
        except RuntimeError:
            return 0

    def rows_text(self) -> list:
        """The displayed rows as tuples of their four cells (the test seam)."""
        out = []
        try:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                out.append(tuple(item.text(column) for column in range(4)))
        except RuntimeError:
            return out
        return out

    def has_live_surface(self) -> bool:
        """False — the panel is HISTORY, never a second status bar (the contract).

        The check exists so the topical test can assert the rule instead of a comment:
        the panel must own no progress bar and no "current status" widget. It renders
        rows of the ring and nothing else.
        """
        from PySide6.QtWidgets import QProgressBar, QStatusBar

        try:
            return bool(self.findChildren(QProgressBar)) or isinstance(self, QStatusBar)
        except RuntimeError:
            return False
