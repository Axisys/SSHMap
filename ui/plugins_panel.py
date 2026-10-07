# -*- coding: utf-8 -*-
"""The Plugins window — the plugin list, the server list and the session event ring (AGENTS.md §4.10).

A non-modal `QDialog` beside `ui/activity_panel.py`: the plugins with their persisted enable switch on the
left, the servers a run would target in the middle and the session's plugin events on the right — rows that
read like the Activity panel's, newest first, with a text export. The ring (`PluginEventRing`) is the ONLY
owner of those rows (bounded, memory only, never persisted) while the WINDOW owns the taps:
`PluginMixin._report_plugin_events()` copies the drained events in and `command_result` brings what a
plugin RAN. The event LINES stay English (they are logging lines) and the chrome is translated by
`retranslate()`; `plugin_event_line()` / `run_result_line()` / `plugin_events_text()` are PURE and the panel
never drains the manager. Mechanism — `DOCUMENTATION.md` §33."""

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:  # the manager is the MODEL of this window (the panel never imports the window module)
    from ..modules import plugin_manager as PM
except ImportError:
    try:
        from modules import plugin_manager as PM
    except ImportError:  # flat layout: the modules/ directory itself is on sys.path
        try:
            import plugin_manager as PM  # type: ignore
        except ImportError:  # a stripped build — the window lists nothing and runs nothing
            PM = None

try:  # the ONE vocabulary of the levels (the activity ring owns the status family's spelling)
    from ..modules import activity_log as AL
except ImportError:
    try:
        from modules import activity_log as AL
    except ImportError:
        try:
            import activity_log as AL  # type: ignore
        except ImportError:
            AL = None

try:  # the vector icons of the rows and the buttons (the three-step layout of the rest of ui/)
    from .icons import get_icon, refresh_button_icon
except ImportError:
    try:
        from ui.icons import get_icon, refresh_button_icon
    except ImportError:
        try:
            from icons import get_icon, refresh_button_icon
        except ImportError:  # a stripped build — the rows are text-only
            def get_icon(name):
                from PySide6.QtGui import QIcon
                return QIcon()

            def refresh_button_icon(button, name):
                return False


#: The bound of the session ring — the `modules/activity_log.py` number: a history, not an archive.
MAX_EVENTS = 200

#: The Source cell of a line the window itself states (a discovery round, a run summary).
SOURCE_WINDOW = "plugins"

#: How much of a run result's output the ring KEEPS (the runner's own cap is 1 MB; this is a history).
OUTPUT_KEEP = 2000

#: The two kinds only the window produces (the manager's own `EVENT_*` names are NOT repeated here).
KIND_RUN_STARTED = "run_started"
KIND_RUN_RESULT = "run_result"
KIND_RUN_FINISHED = "run_finished"
#: The plugin's OWN words: a `ctx.log()` line and a `ctx.status()` sentence (v1.8.3).
KIND_PLUGIN_MESSAGE = "plugin_message"
KIND_PLUGIN_STATUS = "plugin_status"

#: The level shown for a `ctx.status()` row — the activity ring's own spelling of "the interface
#: said so" (`modules/activity_log.py` owns the vocabulary; a missing module costs the fallback).
LEVEL_STATUS = getattr(AL, "LEVEL_STATUS", "UI")


def _t(key: str, **kw) -> str:
    """Safe i18n hook (the `ui/activity_panel.py` pattern)."""
    try:
        from i18n import t as _translate
        return _translate(key, **kw) if kw else _translate(key)
    except Exception:  # noqa: BLE001 — a missing i18n must not break the window
        return key


def _record_label(record) -> str:
    """The display name of a manager record ("" for none, the id as the fallback). Never raises."""
    if record is None:
        return ""
    label = getattr(record, "label", None)
    if callable(label):
        try:
            return str(label() or "")
        except Exception:  # noqa: BLE001 — a broken record is "no name", not a crash
            return ""
    return str(getattr(record, "name", "") or getattr(record, "plugin_id", "") or "")


def plugin_event_line(event) -> tuple:
    """One drained manager event → `(level, source, text, detail)` in ENGLISH.

    PURE: the manager's own event dict in, the rendered cells out. The wording belongs to the WINDOW
    rather than to an i18n key, because an event row is a logging line and reads the same in every
    language (§4.10); the DETAIL is the tooltip (a technical reason, never a sentence). An unknown kind
    is REPORTED instead of dropped, so a new event of the core cannot become an invisible row.
    """
    ev = event if isinstance(event, dict) else {}
    kind = str(ev.get("kind") or "")
    rec = ev.get("record")
    label = _record_label(rec) or str(ev.get("plugin_id") or "") or "?"
    if PM is None:
        return "INFO", SOURCE_WINDOW, kind, ""
    detail = str(getattr(rec, "detail", "") or getattr(rec, "error", "") or "")
    if kind == PM.EVENT_LOADED:
        return "INFO", label, f"Plugin loaded: {label}", detail
    if kind == PM.EVENT_ERROR:
        return "ERROR", label, f"Plugin failed to load: {label} ({detail})", detail
    if kind == PM.EVENT_ENABLED:
        return "INFO", label, f"Plugin enabled: {label}", detail
    if kind == PM.EVENT_DISABLED:
        return "INFO", label, f"Plugin disabled: {label}", detail
    if kind == PM.EVENT_RELOADED:
        return "INFO", SOURCE_WINDOW, f"Plugins reloaded: {int(ev.get('count') or 0)}", ""
    if kind == PM.EVENT_HOOK_ERROR:
        hook = str(ev.get("hook") or "")
        return ("ERROR", label, f"Plugin {label}: {hook} failed ({str(ev.get('error') or '')})", "")
    if kind == PM.EVENT_HOOK_TIMEOUT:
        hook = str(ev.get("hook") or "")
        return ("ERROR", label,
                f"Plugin {label}: {hook} did not finish within {int(ev.get('budget_ms') or 0)} ms "
                f"— abandoned", "")
    return "INFO", SOURCE_WINDOW, f"Plugin event: {kind}", detail


def run_started_line(started, count) -> tuple:
    """A run was started → `(level, source, text, detail)` in ENGLISH. PURE."""
    return ("INFO", SOURCE_WINDOW,
            f"Run started: {int(started)} plugin(s) on {int(count)} server(s)", "")


def run_result_line(label, payload) -> tuple:
    """One per-node `PluginRunResult` → `(level, source, text, detail)` in ENGLISH.

    PURE. What a run report answers is the NODE and the EXIT CODE; the captured output travels as the
    row's DETAIL (the tooltip) and is capped at `OUTPUT_KEEP` — the runner's own 1 MB cap is about the
    transfer, this one is about the ring's memory.
    """
    data = payload if isinstance(payload, dict) else {}
    name = str(label or "?")
    node = str(data.get("alias") or data.get("host") or data.get("node_id") or "?")
    try:
        code = int(data.get("exit_code", -1))
    except (TypeError, ValueError):
        code = -1
    error = " ".join(str(data.get("error") or "").split())
    output = str(data.get("output") or "")[:OUTPUT_KEEP]
    if error:
        return "ERROR", name, f"{name} @ {node}: {error}", output
    if code != 0:
        return "WARNING", name, f"{name} @ {node}: exit {code}", output
    return "INFO", name, f"{name} @ {node}: exit 0", output


def run_finished_line(label, count) -> tuple:
    """The END of one plugin's run → `(level, source, text, detail)` in ENGLISH. PURE."""
    return ("INFO", str(label or "?"), f"Run finished: {label or '?'} — {int(count)} node(s)", "")


def plugin_events_text(events) -> str:
    """The export body — ONE line per event, in the order given (the caller passes what is ON SCREEN).

    PURE: records in, one string out. TEXT only on purpose: the plan leaves a CSV export to a decision
    of its own (a declared column set and the RFC-4180 quoting promoted out of `ui/sidebar.py`), so
    nothing here quotes, pads or delimits a field.
    """
    out = []
    for event in events or ():
        text = " ".join(str(getattr(event, "text", "") or "").split())
        if not text:
            continue
        out.append(f"{event.time_text()}  {str(getattr(event, 'level', '') or ''):<7}  "
                   f"{getattr(event, 'source', '')}  {text}")
    return "".join(line + "\n" for line in out)


class PluginEvent:
    """One row of the session ring — a plain record with a tiny surface (never a frozen dataclass).

    `text` is the MESSAGE cell (English, one line); `detail` is the tooltip behind it (the technical
    reason, the captured output). The ring stamps `seq` and `timestamp`; `time_text()` renders the
    clock cell the way the Activity panel's rows do.
    """

    __slots__ = ("seq", "timestamp", "kind", "level", "source", "text", "detail")

    def __init__(self, seq: int, timestamp: float, kind: str, level: str, source: str,
                 text: str, detail: str = ""):
        self.seq = int(seq)
        self.timestamp = float(timestamp)
        self.kind = str(kind or "")
        self.level = str(level or "INFO")
        self.source = str(source or "")
        self.text = str(text or "")
        self.detail = str(detail or "")

    def time_text(self, fmt: str = "%H:%M:%S") -> str:
        """The clock time of the event (the first column). Never raises."""
        try:
            return time.strftime(fmt, time.localtime(self.timestamp))
        except (ValueError, OSError):
            return ""

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return (f"PluginEvent(seq={self.seq}, {self.level}, {self.source!r}, {self.text!r})")


class PluginEventRing:
    """The bounded, memory-only ring of the Plugins window (the `modules/activity_log.py` shape).

    ONE owner of the event rows: the window appends what the manager reported and what a plugin RAN, the
    panel renders — newest first — and `snapshot()` hands the export a COPY. Nothing is persisted, so
    whoever wants the data saves it (`plugin_events_text()` is the writer the panel calls).
    """

    def __init__(self, max_events: int = MAX_EVENTS):
        try:
            bound = int(max_events)
        except (TypeError, ValueError):
            bound = MAX_EVENTS
        self._max = max(1, bound)
        self._events = []
        self._seq = 0

    @property
    def max_events(self) -> int:
        """The bound — the ring never holds more than this."""
        return self._max

    def append(self, kind, level, source, text, detail="") -> "PluginEvent":
        """Record one row; returns it (None for an empty text — an empty line is not a fact)."""
        message = " ".join(str(text if text is not None else "").split())
        if not message:
            return None
        self._seq += 1
        event = PluginEvent(self._seq, time.time(), kind, level, source, message, detail)
        self._events.append(event)
        if len(self._events) > self._max:      # the oldest row leaves at the bound
            del self._events[:-self._max]
        return event

    def events(self) -> list:
        """Every event, OLDEST first (a copy — the ring is not handed out)."""
        return list(self._events)

    def newest_first(self) -> list:
        """Every event, NEWEST first — the order the window lists them in."""
        return list(reversed(self._events))

    def snapshot(self) -> list:
        """A COPY of the whole ring (the export's input, taken once)."""
        return list(self._events)

    def clear(self) -> None:
        """Drop the whole session history."""
        self._events = []

    def __len__(self) -> int:
        return len(self._events)


class PluginsPanel(QDialog):
    """The Plugins window (v1.8.3) — non-modal, three columns, session-lived."""

    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self._manager = manager
        #: The session ring — the ONLY owner of the event rows (memory only, never persisted).
        self.ring = PluginEventRing()
        #: The window's callbacks; a standalone panel leaves them None and still works.
        self.on_hidden = None       # callable() — the user closed the window
        self.on_status = None       # callable(text, timeout_ms) — the status bar of the window
        self.tooltip_for = None     # callable(record) -> str — the ONE plugin tooltip of the window
        self._building = False      # the guard: a programmatic rebuild never fires a switch
        self._checked_ids = set()   # the CHECKED servers (the run's target list, a view state)

        self.setModal(False)
        self.resize(1080, 560)
        self.setSizeGripEnabled(True)
        self._build_ui()
        self._apply_icons()
        self.retranslate()
        self.refresh()

    # ── the assembly ──────────────────────────────────────────────────────────

    def _make_tree(self, columns: int) -> QTreeWidget:
        """A flat, read-only tree of `columns` columns (the window lists, it never edits)."""
        tree = QTreeWidget(self)
        tree.setColumnCount(columns)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setAllColumnsShowFocus(True)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        tree.header().setStretchLastSection(True)
        return tree

    def _column(self, caption_attr: str, tree: QTreeWidget, empty_attr: str,
                widths=()) -> QWidget:
        """One column of the splitter: a caption, the tree and its empty-state sentence."""
        holder = QWidget(self)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(holder)
        setattr(self, caption_attr, caption)
        box.addWidget(caption)
        for index, width in enumerate(widths):
            tree.setColumnWidth(index, width)
        box.addWidget(tree, 1)
        empty = QLabel(holder)
        empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        setattr(self, empty_attr, empty)
        box.addWidget(empty)
        return holder

    def _build_ui(self):
        """Build the three columns and the button row (the chrome is re-texted by `retranslate()`)."""
        layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(self.splitter, 1)

        # ── the plugins (the persisted enable switch is the row's own checkmark) ──
        self.plugin_tree = self._make_tree(2)
        self.plugin_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plugin_tree.customContextMenuRequested.connect(self._on_plugin_menu_requested)
        self.plugin_tree.itemChanged.connect(self._on_plugin_item_changed)
        self.splitter.addWidget(self._column("plugin_caption", self.plugin_tree,
                                            "plugin_empty", (160, 60)))

        # ── the servers (a checked row is a run target; none checked = the whole registry) ──
        self.server_tree = self._make_tree(4)
        self.server_tree.itemChanged.connect(self._on_server_item_changed)
        self.splitter.addWidget(self._column("server_caption", self.server_tree,
                                            "server_empty", (105, 115, 65, 50)))

        # ── the events (the session ring, newest first — the Activity panel's four cells) ──
        self.event_tree = self._make_tree(4)
        self.splitter.addWidget(self._column("event_caption", self.event_tree,
                                            "event_empty", (66, 70, 130)))
        try:
            # The EVENT pane takes the largest share: the message column is the one a user reads.
            self.splitter.setSizes([225, 335, 560])
        except RuntimeError:
            pass  # Qt teardown — a splitter without sizes still lays out

        row = QHBoxLayout()
        self.run_btn = QPushButton(self)
        self.run_btn.clicked.connect(self._on_run_clicked)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        self.clear_btn = QPushButton(self)
        self.clear_btn.clicked.connect(self.clear)
        row.addWidget(self.clear_btn)
        self.export_btn = QPushButton(self)
        self.export_btn.clicked.connect(self._on_export_clicked)
        row.addWidget(self.export_btn)
        layout.addLayout(row)

    def _apply_icons(self):
        """Re-apply the vector icons the PANEL painted by hand (the rows and the three buttons).

        A widget keeps its OWN render of a pixmap, so a theme switch has to re-apply it — the
        `refresh_button_icon()` / `refresh_theme()` contract of `ui/theme_qss.py`. Never raises.
        """
        for button, name in ((self.run_btn, "plugin"), (self.clear_btn, "delete"),
                             (self.export_btn, "save")):
            try:
                refresh_button_icon(button, name)
            except RuntimeError:
                continue  # Qt teardown — this button is already destroyed
        try:
            for index in range(self.plugin_tree.topLevelItemCount()):
                item = self.plugin_tree.topLevelItem(index)
                item.setIcon(0, get_icon("plugin"))
        except RuntimeError:
            pass  # Qt teardown — the tree is already destroyed

    def refresh_theme(self):
        """The theme walk of this window (its own painted icons; the QSS follows the application)."""
        self._apply_icons()

    # ── the chrome (translated) ────────────────────────────────────────────────

    def retranslate(self):
        """Re-text the CHROME only (the title, the captions, the buttons, the column headers).

        The event LINES are deliberately untouched: they are logging lines and read the same in every
        language (the module docstring). Idempotent, never raises.
        """
        try:
            self.setWindowTitle(_t("plugins.window.title"))
            self.plugin_caption.setText(_t("plugins.window.plugins"))
            self.server_caption.setText(_t("plugins.window.servers"))
            self.event_caption.setText(_t("plugins.window.events"))
            self.run_btn.setText(_t("plugins.window.run"))
            self.run_btn.setToolTip(_t("plugins.window.checked_hint"))
            self.clear_btn.setText(_t("plugins.window.clear"))
            self.clear_btn.setToolTip(_t("plugins.window.clear"))
            self.export_btn.setText(_t("plugins.window.export"))
            self.export_btn.setToolTip(_t("plugins.window.export"))
            self.plugin_empty.setText(_t("plugins.empty"))
            self.server_empty.setText(_t("plugins.window.empty_servers"))
            self.event_empty.setText(_t("plugins.window.empty_events"))
            self.plugin_tree.setHeaderLabels([_t("plugins.window.col.plugin"),
                                              _t("plugins.window.col.version")])
            self.server_tree.setHeaderLabels([_t("plugins.window.col.server"),
                                              _t("plugins.window.col.host"),
                                              _t("plugins.window.col.user"),
                                              _t("plugins.window.col.port")])
            self.event_tree.setHeaderLabels([_t("plugins.window.col.time"),
                                             _t("plugins.window.col.level"),
                                             _t("plugins.window.col.source"),
                                             _t("plugins.window.col.message")])
        except RuntimeError:
            return  # Qt teardown — nothing to re-text

    # ── the model (the manager is the ONLY source of records and nodes) ────────

    def _manager_records(self) -> list:
        """The manager's records ([] — no manager, or a manager that refuses)."""
        try:
            return list(self._manager.records())
        except Exception:  # noqa: BLE001 — a broken source shows an empty column
            return []

    def _manager_nodes(self) -> list:
        """The plugin-visible node records ([] — no manager, or an empty project)."""
        try:
            return list(self._manager.node_records())
        except Exception:  # noqa: BLE001
            return []

    def _plugin_label(self, plugin_id) -> str:
        """The display name of a plugin id (the id itself when the record is gone)."""
        try:
            record = self._manager.get(str(plugin_id))
            label = _record_label(record)
            if label:
                return label
        except Exception:  # noqa: BLE001
            pass
        return str(plugin_id or "?")

    def _tooltip(self, record) -> str:
        """The tooltip of a plugin row — the WINDOW's rule when it handed one over.

        One fact, one home: the menu row and this row describe a plugin the same way, so the window
        injects its own `_plugin_tooltip()`; a standalone panel falls back to the failure sentence or
        to the version and the description.
        """
        callback = self.tooltip_for
        if callable(callback):
            try:
                text = callback(record)
                if text:
                    return str(text)
            except Exception:  # noqa: BLE001 — a broken callback falls back
                pass
        if bool(getattr(record, "failed", False)):
            return _t("plugins.status.error", name=_record_label(record),
                      error=str(getattr(record, "detail", "") or getattr(record, "error", "")))
        version = str(getattr(record, "version", "") or "")
        description = str(getattr(record, "description", "") or "")
        text = f"v{version}" if version else ""
        if text and description:
            return f"{text} — {description}"
        return text or description

    # ── the three columns ─────────────────────────────────────────────────────

    def refresh(self):
        """Rebuild every column from the sources (the test seam and the show path)."""
        self.refresh_plugins()
        self.refresh_servers()
        self.refresh_events()

    def refresh_plugins(self):
        """Rebuild the plugin rows: the label, the version and the persisted ENABLE switch.

        The checkmark IS the shipped switch (the menu row's rule — a record that is not `ok()` shows
        unchecked and an ERROR record cannot be switched at all), so the two surfaces can never
        disagree about what is on.
        """
        records = self._manager_records()
        self._building = True
        try:
            self.plugin_tree.setUpdatesEnabled(False)
            self.plugin_tree.clear()
            for record in records:
                item = QTreeWidgetItem(self.plugin_tree)
                item.setText(0, _record_label(record) or str(getattr(record, "plugin_id", "")))
                item.setText(1, str(getattr(record, "version", "") or ""))
                item.setData(0, Qt.ItemDataRole.UserRole, str(getattr(record, "plugin_id", "") or ""))
                item.setToolTip(0, self._tooltip(record))
                item.setIcon(0, get_icon("plugin"))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if bool(getattr(record, "ok", False))
                                   else Qt.CheckState.Unchecked)
                if bool(getattr(record, "failed", False)):
                    # Found, but not loadable: the row SAYS so (the tooltip) and has nothing to switch.
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        except RuntimeError:
            return  # Qt teardown — the tree is already destroyed
        finally:
            try:
                self.plugin_tree.setUpdatesEnabled(True)
            except RuntimeError:
                pass
            self._building = False
        self._toggle_empty(self.plugin_tree, self.plugin_empty)
        self._sync_run_enabled()

    def refresh_servers(self):
        """Rebuild the server rows from the plugin registry (a CHECKED row is a run target).

        The user's checkmarks SURVIVE a rebuild — they are the run's target list, not a view of the
        data — and a node that left the map simply drops out. New nodes arrive UNCHECKED: with nothing
        checked the whole registry is the target, which is the scope the menu action documents.
        """
        nodes = self._manager_nodes()
        self._building = True
        try:
            self.server_tree.setUpdatesEnabled(False)
            self.server_tree.clear()
            for node in nodes:
                node_id = str(getattr(node, "id", "") or "")
                item = QTreeWidgetItem(self.server_tree)
                item.setText(0, str(getattr(node, "alias", "") or getattr(node, "host", "")
                                    or node_id))
                item.setText(1, str(getattr(node, "host", "") or ""))
                item.setText(2, str(getattr(node, "user", "") or ""))
                item.setText(3, str(getattr(node, "port", "") or ""))
                item.setData(0, Qt.ItemDataRole.UserRole, node_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if node_id in self._checked_ids
                                   else Qt.CheckState.Unchecked)
        except RuntimeError:
            return  # Qt teardown
        finally:
            try:
                self.server_tree.setUpdatesEnabled(True)
            except RuntimeError:
                pass
            self._building = False
        self._toggle_empty(self.server_tree, self.server_empty)
        self._sync_run_enabled()

    def refresh_events(self):
        """Rebuild the event rows from the ring, NEWEST first (the window lists a history)."""
        events = self.visible_events()
        try:
            self.event_tree.setUpdatesEnabled(False)
            self.event_tree.clear()
            for event in events:
                item = QTreeWidgetItem(self.event_tree)
                item.setText(0, event.time_text())
                item.setText(1, event.level)
                item.setText(2, event.source)
                item.setText(3, event.text)
                for column in range(4):
                    item.setToolTip(column, event.detail or event.text)
        except RuntimeError:
            return  # Qt teardown
        finally:
            try:
                self.event_tree.setUpdatesEnabled(True)
            except RuntimeError:
                pass
        self._toggle_empty(self.event_tree, self.event_empty)

    @staticmethod
    def _toggle_empty(tree, label) -> None:
        """Show the empty-state sentence exactly while the tree has no row."""
        try:
            has_rows = bool(tree.topLevelItemCount())
            tree.setVisible(has_rows)
            label.setVisible(not has_rows)
        except RuntimeError:
            pass  # Qt teardown

    def _sync_run_enabled(self) -> None:
        """The global Run button follows the menu item's rule: a capable plugin AND servers."""
        try:
            capable = any(PM is not None and PM.HOOK_RUN_ON_NODES in (getattr(rec, "hooks", ()) or ())
                          and bool(getattr(rec, "ok", False)) for rec in self._manager_records())
            self.run_btn.setEnabled(bool(capable) and bool(self._manager_nodes()))
        except RuntimeError:
            pass  # Qt teardown

    # ── the two switches of the panel ─────────────────────────────────────────

    def _on_plugin_item_changed(self, item, column):
        """The ENABLE switch of one plugin row, persisted through the manager (the menu's rule)."""
        if self._building or column != 0 or item is None:
            return
        plugin_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        wanted = item.checkState(0) == Qt.CheckState.Checked
        try:
            moved = bool(self._manager.set_enabled(plugin_id, wanted))
        except Exception:  # noqa: BLE001 — a switch must never break the window
            moved = False
        if not moved:
            # The model did not move (an unknown id, a failed plugin) — put the checkmark back
            # instead of leaving a lie on screen (the shipped menu behaviour).
            self.refresh_plugins()

    def _on_server_item_changed(self, item, column):
        """A CHECKED server row joins the run's target list (a view state — nothing is persisted)."""
        if self._building or column != 0 or item is None:
            return
        node_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not node_id:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._checked_ids.add(node_id)
        else:
            self._checked_ids.discard(node_id)

    def checked_nodes(self) -> list:
        """The node records of the CHECKED rows, in the table's order ([] = the whole registry)."""
        ordered = []
        try:
            for index in range(self.server_tree.topLevelItemCount()):
                item = self.server_tree.topLevelItem(index)
                if item.checkState(0) == Qt.CheckState.Checked:
                    ordered.append(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
        except RuntimeError:
            return []
        by_id = {str(getattr(node, "id", "") or ""): node for node in self._manager_nodes()}
        return [by_id[node_id] for node_id in ordered if node_id in by_id]

    def set_checked_nodes(self, node_ids) -> int:
        """Check exactly `node_ids` (the test seam / a programmatic target list); returns how many."""
        wanted = {str(node_id) for node_id in (node_ids or ())}
        self._checked_ids = set(wanted)
        self.refresh_servers()
        return len(self.checked_nodes())

    # ── the session ring (the WINDOW drains; the panel only records) ───────────

    def record_events(self, events) -> int:
        """Copy the drained manager events into the ring (ONE row per event); returns how many.

        The manager's queue is DESTRUCTIVE and its only consumer is
        `PluginMixin._report_plugin_events()`, which calls this — the panel NEVER drains, so a second
        consumer can never steal a line from the status bar (the "no double display" rule of §4.10).
        """
        added = 0
        for event in events or ():
            level, source, text, detail = plugin_event_line(event)
            kind = str(event.get("kind") or "") if isinstance(event, dict) else ""
            if self.ring.append(kind, level, source, text, detail) is not None:
                added += 1
        if added:
            self.refresh_events()
        return added

    def record_run_result(self, plugin_id, payload) -> "PluginEvent":
        """One per-node answer of `ctx.run_command` → ONE row of the session ring.

        The core owns the runner and the manager re-emits every result on `command_result`, so the
        window's ONE tap turns a `PluginRunResult` into an event here with NO plugin API change. The
        row says what a plugin RAN (node, exit code, the captured text) — never what it concluded.
        """
        level, source, text, detail = run_result_line(self._plugin_label(plugin_id), payload)
        event = self.ring.append(KIND_RUN_RESULT, level, source, text, detail)
        if event is not None:
            self.refresh_events()
        return event

    def record_run_finished(self, plugin_id, count) -> "PluginEvent":
        """The end of one plugin's run → ONE summary row (the count of the nodes it walked)."""
        level, source, text, detail = run_finished_line(self._plugin_label(plugin_id), count)
        event = self.ring.append(KIND_RUN_FINISHED, level, source, text, detail)
        if event is not None:
            self.refresh_events()
        return event

    def record_plugin_message(self, plugin_id, message) -> "PluginEvent":
        """`ctx.log()` — the plugin's OWN line, verbatim, as a row of the session ring.

        A plugin's strings are NOT i18n keys (`PLUGINS.md`), so the line is copied as the author
        wrote it: the window is where those words are read, and the application log keeps the
        prefixed copy. Never raises.
        """
        text = str(message if message is not None else "").strip()
        if not text:
            return None
        event = self.ring.append(KIND_PLUGIN_MESSAGE, "INFO", self._plugin_label(plugin_id), text)
        if event is not None:
            self.refresh_events()
        return event

    def record_plugin_status(self, plugin_id, text) -> "PluginEvent":
        """`ctx.status()` — the sentence a plugin ASKED the interface to show, as a row too.

        This is the plugin's own request, not the core's reporting: the status bar still gets it
        (the plugin asked for it, and the token guard stays the window's), while the ring keeps it
        the way the Activity panel keeps every status message — the bar is the "now", a history is
        what is still readable later.
        """
        line = str(text if text is not None else "").strip()
        if not line:
            return None
        event = self.ring.append(KIND_PLUGIN_STATUS, LEVEL_STATUS,
                                 self._plugin_label(plugin_id), line)
        if event is not None:
            self.refresh_events()
        return event

    def visible_events(self) -> list:
        """The events ON SCREEN, newest first — the ONE source of the export (never a second buffer)."""
        return self.ring.newest_first()

    def clear(self):
        """Clear the session HISTORY (the ring itself, not only the rows)."""
        self.ring.clear()
        self.refresh_events()

    # ── the run doors ─────────────────────────────────────────────────────────

    def run_plugins(self, plugin_ids=None) -> int:
        """Start a run on the CHECKED servers — the panel's door to `run_on_nodes`.

        `plugin_ids=None` keeps the shipped "every capable plugin" semantics of the global button; a
        LIST runs exactly those ids, which is the row action's door (the persisted enable switch is
        CONFIG and is deliberately never reused as the run selection — §4.10). With no server checked
        the whole plugin registry is the target, the scope the menu action documents. Returns the
        number of plugins started (0 — nothing could run).
        """
        nodes = self.checked_nodes()
        if not nodes:
            nodes = self._manager_nodes()
        started = 0
        try:
            started = int(self._manager.plugin_run_on_nodes(nodes, plugin_ids=plugin_ids))
        except Exception:  # noqa: BLE001 — an action must never crash the window
            started = 0
        if started:
            level, source, text, detail = run_started_line(started, len(nodes))
            if self.ring.append(KIND_RUN_STARTED, level, source, text, detail) is not None:
                self.refresh_events()
            self._notify(_t("plugins.status.run_on_nodes", count=len(nodes)), 8000)
        else:
            self._notify(_t("plugins.run_hint") if nodes else _t("plugins.no_selection"), 8000)
        return started

    def _on_run_clicked(self):
        """The global button: the shipped "every capable plugin" semantics."""
        self.run_plugins(None)

    def build_plugin_menu(self, item):
        """The context menu of ONE plugin row (the test seam — the caller triggers the QAction).

        Returns None when the row cannot run anything (no record, a plugin without `run_on_nodes`), so
        the menu of a plain plugin is not an empty popup. The action is the SECOND door of the run
        parameter: it names ONE plugin id, while the persisted switch stays configuration.
        """
        if item is None or self._manager is None:
            return None
        plugin_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        try:
            record = self._manager.get(plugin_id)
        except Exception:  # noqa: BLE001
            record = None
        if record is None or not bool(getattr(record, "ok", False)):
            return None
        if PM is None or PM.HOOK_RUN_ON_NODES not in (getattr(record, "hooks", ()) or ()):
            return None
        menu = QMenu(self)
        action = menu.addAction(_t("plugins.window.run_one"))
        action.setEnabled(bool(self._manager_nodes()))
        action.triggered.connect(lambda _checked=False, pid=plugin_id: self.run_plugins([pid]))
        # gotcha #9: a dead Python QAction wrapper takes its C++ menu down with it — the menu is
        # kept alive for as long as a caller may still be showing it.
        self._row_menu = menu
        return menu

    def _on_plugin_menu_requested(self, point):
        """A right-click on a plugin row opens its own menu (a row action, never a batch)."""
        try:
            item = self.plugin_tree.itemAt(point)
        except RuntimeError:
            return  # Qt teardown
        menu = self.build_plugin_menu(item)
        if menu is None:
            return
        try:
            menu.exec(self.plugin_tree.viewport().mapToGlobal(point))
        except RuntimeError:
            pass  # Qt teardown — the menu is already destroyed

    # ── the export (a snapshot of the SAME ring, TEXT only) ────────────────────

    def export_text(self) -> str:
        """The export body: what is ON SCREEN right now (the ring snapshot, newest first)."""
        return plugin_events_text(self.visible_events())

    def export_to_path(self, path) -> str:
        """Write the on-screen log to `path` as UTF-8 TEXT; "" on success, else the reason.

        The snapshot is taken HERE and only here, so the caller's dialog cannot race a new event into
        the file, and the writer is the PURE `plugin_events_text()` — the panel owns no second buffer.
        """
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(self.export_text())
        except (OSError, UnicodeError) as exc:
            return str(exc)
        return ""

    def _on_export_clicked(self):
        """The "Export…" button: the ordinary save dialog over the ON-SCREEN rows."""
        if not self.visible_events():
            self._notify(_t("plugins.window.empty_events"), 5000)
            return
        path, _selected = QFileDialog.getSaveFileName(
            self, _t("plugins.window.export"), "", "Text (*.txt);;All files (*)")
        if not path:
            return
        if not os.path.splitext(str(path))[1]:
            path += ".txt"
        failure = self.export_to_path(path)
        if failure:
            QMessageBox.critical(self, _t("msg.error_title"),
                                 _t("msg.export_failed", error=failure))
            return
        self._notify(_t("plugins.window.status.exported", file=os.path.basename(path)), 8000)

    # ── visibility (the window owns the config key) ────────────────────────────

    def set_visible(self, visible: bool):
        """Show/hide the window; showing always re-reads the sources and the ring."""
        if visible:
            self.refresh()
            self.show()
            self.raise_()
            self.activateWindow()
        else:
            self.hide()

    def is_shown(self) -> bool:
        """`not isHidden()` — the rule of `ui/activity_panel.py` (a child of a never-shown
        window reports `isVisible() == False` while it is not hidden at all)."""
        try:
            return not self.isHidden()
        except RuntimeError:
            return False

    def closeEvent(self, event):  # noqa: N802 — Qt API
        """The user closed the window: hide it (the session ring survives) and tell the owner."""
        self.hide()
        event.accept()
        callback = self.on_hidden
        if callable(callback):
            try:
                callback()
            except Exception:  # noqa: BLE001 — a broken callback must not break a close
                pass

    def _notify(self, text, timeout_ms: int = 8000):
        """Hand one sentence to the window's status bar (the panel owns no bar). Never raises."""
        callback = self.on_status
        if not callable(callback):
            return
        try:
            callback(str(text), int(timeout_ms))
        except Exception:  # noqa: BLE001 — a status line is cosmetic
            pass

    # ── introspection (the topical test) ──────────────────────────────────────

    @staticmethod
    def _rows(tree, columns: int) -> list:
        """The rows of one tree as tuples of their cells (the test seam)."""
        out = []
        try:
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                out.append(tuple(item.text(column) for column in range(columns)))
        except RuntimeError:
            return out
        return out

    def plugin_rows(self) -> list:
        """The plugin rows as `(label, version)` tuples."""
        return self._rows(self.plugin_tree, 2)

    def plugin_checked(self) -> list:
        """The plugin ids whose ENABLE switch is on (the persisted state, read back from the rows)."""
        out = []
        try:
            for index in range(self.plugin_tree.topLevelItemCount()):
                item = self.plugin_tree.topLevelItem(index)
                if item.checkState(0) == Qt.CheckState.Checked:
                    out.append(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
        except RuntimeError:
            return out
        return out

    def server_rows(self) -> list:
        """The server rows as `(server, host, user, port)` tuples."""
        return self._rows(self.server_tree, 4)

    def event_rows(self) -> list:
        """The event rows as `(time, level, source, message)` tuples, newest first."""
        return self._rows(self.event_tree, 4)

    def row_count(self) -> int:
        """How many event rows are displayed right now."""
        try:
            return int(self.event_tree.topLevelItemCount())
        except RuntimeError:
            return 0
