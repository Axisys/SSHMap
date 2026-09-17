# -*- coding: utf-8 -*-
"""v1.1: Settings dialog (hub) — ROADMAP v1.1, tasks 1–6; v1.1.1 — options around the hub.

QTabWidget "General / Terminal / Statuses / Autosave / Map / Hotkeys / Language":
centralized application settings + entry points (the "Settings" menu and the
⚙ sidebar button — in ui/main_window.py / ui/sidebar.py). Each next idea from
the ROADMAP is added as a field/checkbox in an existing tab, not as a new
UI version.

Storage — a SINGLE ~/.sshmap/config.json (i18n.save_config, atomic
merge-write); all keys are optional, defaults = current behavior:
  * General:          external_terminal (v1.1: moved from ~/.sshmap_settings.json,
                     migration on read — modules/external_terminal.py, task 7)
                     + v1.1.1: ui_font_family/ui_font_size (UI font, live),
                     ui_show_sidebar_buttons (the sidebar button block);
  * Terminal:         terminal_palette / terminal_font_size / terminal_history_lines
                     (v1.0 keys) + terminal_close_behavior (v1.1: "close"|"ask")
                     + v1.1.1: terminal_font (family; read since v1.0, UI for
                     the first time), terminal_max_open (own-terminals limit,
                     default 4)
                      + v1.2.2: terminal_mode ("windows" default | "tabs" — the dock on the map);
  * Statuses:         status_interval_sec / status_probe_timeout_sec (v1.1; defaults
                     30 s / 3.0 s — v1.0 behavior, services/status_checker.py);
  * Autosave:         autosave_enabled / autosave_interval_sec / backup_count (v0.9.7);
  * Map:              v1.1.1: ui_node_double_click ("properties"|"connect"),
                     ui_show_connection_type (type on the connection plaque);
  * Language:         language — applied immediately (signal language_changed →
                     MainWindow._switch_language; the "Help → Language" item is kept).
  * Hotkeys (v1.3.2): hotkeys — a nested dict action_id → sequence string
                     ("" = the hotkey is disabled); the rows come from the action
                     registry ui/hotkey_registry.py, the action NAMES reuse the
                     existing menu i18n keys. Collected on OK and applied live by
                     MainWindow._apply_hotkeys (QAction.setShortcut/QShortcut.setKey).

v1.1.1: load_ui_settings() — the ui_* key validator (the get_status_settings
pattern); live application without a restart — MainWindow
(_apply_settings_from_dialog): QApplication.setFont, the font of open
terminal windows, sidebar button visibility, double-click mode, connection
plaque redraw.

Signals (the module pattern — like ui/sidebar.py: the dialog does not know
about MainWindow):
    applied()            — the config was saved on OK; MainWindow applies
                           autosave (QTimer), statuses (StatusChecker) and
                           the v1.1.1 options (fonts/buttons/double-click/
                           plaques) live; the terminal reads the config on
                           the next window creation;
    language_changed(str)— the language choice in the "Language" tab
                           (immediately, before OK).

i18n: keys settings.* × en/ru/zh; the string registry — in retranslate()
(a language change inside the open dialog updates its own labels).
"""

import sys

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QPushButton, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QKeySequenceEdit,
)

try:  # v1.2.5: central theme (colors/radii/fonts — ui/theme.py); no literals in the UI code
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # i18n — top-level package (flat run from the project root)
    from i18n import t as _translate
except Exception:  # pragma: no cover - fallback path
    try:
        from .i18n import t as _translate
    except Exception:
        _translate = None

try:  # v1.1 (task 7): a single source — config.json; the migration is inside the module
    from ..modules.external_terminal import (
        TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
        load_external_terminal_setting,
    )
except ImportError:
    try:
        from modules.external_terminal import (
            TERMINAL_CHOICES_WINDOWS, TERMINAL_CHOICES_LINUX,
            load_external_terminal_setting,
        )
    except ImportError:  # flat layout without the module — the "General" tab without the combo
        TERMINAL_CHOICES_WINDOWS = ["auto"]
        TERMINAL_CHOICES_LINUX = ["auto"]
        def load_external_terminal_setting():  # noqa: N802
            return "auto"


def _t(key: str, **kw) -> str:
    """Safe translation (like in ui/command_palette.py): without i18n — the key itself."""
    if _translate is not None:
        try:
            return _translate(key, **kw) if kw else _translate(key)
        except Exception:  # noqa: BLE001 — an i18n failure must not break the dialog
            pass
    return key


def load_ui_settings():
    """v1.1.1 (ROADMAP v1.1.1): reads and validates the ui_* keys from ~/.sshmap/config.json.

    The same pattern as get_status_settings()/get_autosave_settings() — each
    domain reads its own keys; the source is i18n.load_config() (never
    fails). Returns:
      {"font_family": str,            # "" — not set (the system font)
       "font_size": int | None,       # None — not set (the system size; 0 = the same)
       "node_double_click": str,      # "properties" (default) | "connect"
       "show_sidebar_buttons": bool,  # default True — the sidebar button block is visible
       "show_connection_type": bool}  # default False — the type on the connection plaque is not drawn
    Invalid values (foreign type, out of range) → default. Never raises.
    """
    defaults = {"font_family": "", "font_size": None,
                "node_double_click": "properties",
                "show_sidebar_buttons": True, "show_connection_type": False}
    try:
        from i18n import load_config
    except Exception:
        return dict(defaults)
    cfg = load_config()

    v = cfg.get("ui_font_family")
    if isinstance(v, str):
        defaults["font_family"] = v.strip()

    v = cfg.get("ui_font_size")
    if isinstance(v, int) and not isinstance(v, bool) and 6 <= v <= 72:
        defaults["font_size"] = v     # broken/0/out of range → the system size (default)

    v = cfg.get("ui_node_double_click")
    if isinstance(v, str) and v.strip().lower() in ("properties", "connect"):
        defaults["node_double_click"] = v.strip().lower()  # broken/foreign → "properties"

    v = cfg.get("ui_show_sidebar_buttons")
    if isinstance(v, bool):
        defaults["show_sidebar_buttons"] = v

    v = cfg.get("ui_show_connection_type")
    if isinstance(v, bool):
        defaults["show_connection_type"] = v

    return defaults


class SettingsDialog(QDialog):
    """Settings dialog (hub): 6 tabs, saved to ~/.sshmap/config.json on OK."""

    applied = Signal()           # the config was saved — apply live (MainWindow)
    language_changed = Signal(str)  # the language choice in the "Language" tab (immediately)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("settings.title"))
        self.resize(500, 400)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_general_tab()
        self._build_terminal_tab()
        self._build_statuses_tab()
        self._build_autosave_tab()
        self._build_map_tab()
        self._build_hotkeys_tab()   # v1.3.2 (ROADMAP v1.3.2, task 2)
        self._build_language_tab()

        # ── OK/Cancel buttons (OK = saving config.json + the applied signal) ─────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.ok_btn = QPushButton(_t("settings.ok"))
        self.cancel_btn = QPushButton(_t("settings.cancel"))
        self.ok_btn.clicked.connect(self._on_accept)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    # ── "General" tab (v1.1: external_terminal — a single config.json) ─────────

    def _build_general_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.ext_term_combo = QComboBox()
        choices = (TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                   else TERMINAL_CHOICES_LINUX)
        for tid in choices:
            # i18n preset labels — the existing keys ssh_ext.preset.* (v0.9.9.2)
            self.ext_term_combo.addItem(_t(f"ssh_ext.preset.{tid}"), tid)
        cur = load_external_terminal_setting()
        idx = next((i for i in range(self.ext_term_combo.count())
                    if self.ext_term_combo.itemData(i) == cur), 0)
        self.ext_term_combo.setCurrentIndex(idx)
        self._lbl_ext_term = QLabel(_t("settings.general.external_terminal"))
        form.addRow(self._lbl_ext_term, self.ext_term_combo)

        # v1.1.1 (item 1): the interface font — family + size (pt); applied
        # live without a restart (MainWindow: QApplication.setFont on OK and at startup).
        ui_cfg = load_ui_settings()
        self.ui_font_family_edit = QLineEdit(ui_cfg["font_family"])
        self._lbl_ui_font_family = QLabel(_t("settings.general.ui_font_family"))
        form.addRow(self._lbl_ui_font_family, self.ui_font_family_edit)
        # 0 = the system size (specialValueText); the validator range is 6..72
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(0, 72)
        self.ui_font_size_spin.setValue(ui_cfg["font_size"] or 0)
        self.ui_font_size_spin.setSpecialValueText(_t("settings.ui_font_system"))
        self._lbl_ui_font_size = QLabel(_t("settings.general.ui_font_size"))
        form.addRow(self._lbl_ui_font_size, self.ui_font_size_spin)

        # v1.1.1 (item 5): the sidebar button block — show/hide (the layout
        # reflows itself); the whole sidebar is hidden by a separate "View"
        # menu item (MainWindow).
        self.sidebar_buttons_chk = QCheckBox(_t("settings.general.sidebar_buttons"))
        self.sidebar_buttons_chk.setChecked(ui_cfg["show_sidebar_buttons"])
        form.addRow("", self.sidebar_buttons_chk)

        self.tabs.addTab(tab, _t("settings.tab.general"))

    # ── "Terminal" tab (v1.0 keys + the new close behavior) ─────────────

    def _build_terminal_tab(self):
        try:
            from ..modules.ssh_terminal import load_terminal_settings
        except ImportError:
            from modules.ssh_terminal import load_terminal_settings
        cfg = load_terminal_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        # v1.2.2 (task 4): the terminal display mode — "windows" (default,
        # current behavior: separate windows) | "tabs" (the "Terminals" dock on the map).
        # Applied without a restart: new sessions go to the chosen mode,
        # open windows/the dock stay as-is until closed.
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(_t("settings.terminal.mode.windows"), "windows")
        self.mode_combo.addItem(_t("settings.terminal.mode.tabs"), "tabs")
        idx = next((i for i in range(self.mode_combo.count())
                    if self.mode_combo.itemData(i) == cfg["mode"]), 0)
        self.mode_combo.setCurrentIndex(idx)
        self._lbl_mode = QLabel(_t("settings.terminal.mode"))
        form.addRow(self._lbl_mode, self.mode_combo)

        self.palette_combo = QComboBox()
        self.palette_combo.addItem(_t("settings.terminal.palette.default"), "default")
        self.palette_combo.addItem(_t("settings.terminal.palette.nord"), "nord")
        self.palette_combo.addItem(_t("settings.terminal.palette.dracula"), "dracula")
        self.palette_combo.addItem(_t("settings.terminal.palette.tokyo_night"), "tokyo_night")
        cur_pal = cfg["palette"] or "default"
        idx = next((i for i in range(self.palette_combo.count())
                    if self.palette_combo.itemData(i) == cur_pal), 0)
        self.palette_combo.setCurrentIndex(idx)
        self._lbl_palette = QLabel(_t("settings.terminal.palette"))
        form.addRow(self._lbl_palette, self.palette_combo)

        # v1.1.1 (item 1): the terminal font family (monospace); empty —
        # the system monospace. The terminal_font key was read since v1.0,
        # the UI appears for the first time; live application — to open
        # windows (MainWindow on OK).
        self.term_font_family_edit = QLineEdit(cfg["font_family"])
        self._lbl_term_font_family = QLabel(_t("settings.terminal.font_family"))
        form.addRow(self._lbl_term_font_family, self.term_font_family_edit)

        # Font size: the same validator range (6–72 pt), default 10
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 72)
        self.font_size_spin.setValue(cfg["font_size"] or 10)
        self._lbl_font_size = QLabel(_t("settings.terminal.font_size"))
        form.addRow(self._lbl_font_size, self.font_size_spin)

        # v1.1.1 (item 3): the limit of own open terminals — when reached,
        # not a refusal but an offer to close the oldest session
        # (MainWindow._spawn_terminal_window).
        self.max_open_spin = QSpinBox()
        self.max_open_spin.setRange(1, 16)
        self.max_open_spin.setValue(cfg["max_open"])
        self._lbl_max_open = QLabel(_t("settings.terminal.max_open"))
        form.addRow(self._lbl_max_open, self.max_open_spin)

        # History depth: the validator range (0 = scrollback disabled)
        self.history_spin = QSpinBox()
        self.history_spin.setRange(0, 1_000_000)
        self.history_spin.setValue(cfg["history_lines"])
        self._lbl_history = QLabel(_t("settings.terminal.history_lines"))
        form.addRow(self._lbl_history, self.history_spin)

        # v1.1 (task 3): the session close behavior — a new key
        self.close_behavior_combo = QComboBox()
        self.close_behavior_combo.addItem(
            _t("settings.terminal.close_behavior.close"), "close")
        self.close_behavior_combo.addItem(
            _t("settings.terminal.close_behavior.ask"), "ask")
        idx = next((i for i in range(self.close_behavior_combo.count())
                    if self.close_behavior_combo.itemData(i) == cfg["close_behavior"]), 0)
        self.close_behavior_combo.setCurrentIndex(idx)
        self._lbl_close_behavior = QLabel(_t("settings.terminal.close_behavior"))
        form.addRow(self._lbl_close_behavior, self.close_behavior_combo)

        self.tabs.addTab(tab, _t("settings.tab.terminal"))

    # ── "Statuses" tab (the StatusChecker probe interval + timeout) ─────────────

    def _build_statuses_tab(self):
        try:
            from ..services.status_checker import (
                get_status_settings, MAX_PARALLEL_LIMIT as _MPL)
        except ImportError:
            from services.status_checker import (
                get_status_settings, MAX_PARALLEL_LIMIT as _MPL)
        st = get_status_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        self.status_interval_spin = QSpinBox()
        self.status_interval_spin.setRange(5, 3600)
        self.status_interval_spin.setValue(st["interval_sec"])
        self._lbl_status_interval = QLabel(_t("settings.statuses.interval"))
        form.addRow(self._lbl_status_interval, self.status_interval_spin)

        self.probe_timeout_spin = QDoubleSpinBox()
        self.probe_timeout_spin.setRange(0.2, 60.0)
        self.probe_timeout_spin.setDecimals(1)
        self.probe_timeout_spin.setValue(st["probe_timeout_sec"])
        self._lbl_probe_timeout = QLabel(_t("settings.statuses.timeout"))
        form.addRow(self._lbl_probe_timeout, self.probe_timeout_spin)

        # v1.1.2 final (task 2): the cap on parallel probes per round —
        # status_max_parallel (default 16; range = the clamp of get_status_settings).
        self.max_parallel_spin = QSpinBox()
        self.max_parallel_spin.setRange(1, _MPL)
        self.max_parallel_spin.setValue(st["max_parallel"])
        self._lbl_max_parallel = QLabel(_t("settings.statuses.max_parallel"))
        form.addRow(self._lbl_max_parallel, self.max_parallel_spin)

        self.tabs.addTab(tab, _t("settings.tab.statuses"))

    # ── "Autosave" tab (v0.9.7 keys) ────────────────────────────────

    def _build_autosave_tab(self):
        try:
            from ..storage.autosave import get_autosave_settings
        except ImportError:
            from storage.autosave import get_autosave_settings
        as_cfg = get_autosave_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        self.autosave_enabled_chk = QCheckBox(_t("settings.autosave.enabled"))
        self.autosave_enabled_chk.setChecked(as_cfg["enabled"])
        form.addRow("", self.autosave_enabled_chk)

        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setRange(5, 86400)
        self.autosave_interval_spin.setValue(as_cfg["interval_sec"])
        self._lbl_autosave_interval = QLabel(_t("settings.autosave.interval"))
        form.addRow(self._lbl_autosave_interval, self.autosave_interval_spin)

        self.backup_count_spin = QSpinBox()
        self.backup_count_spin.setRange(1, 100)
        self.backup_count_spin.setValue(as_cfg["backup_count"])
        self._lbl_backup_count = QLabel(_t("settings.autosave.backups"))
        form.addRow(self._lbl_backup_count, self.backup_count_spin)

        self.tabs.addTab(tab, _t("settings.tab.autosave"))

    # ── "Map" tab (v1.1.1: map options — node double click, connection plaque) ─

    def _build_map_tab(self):
        ui_cfg = load_ui_settings()

        tab = QWidget()
        form = QFormLayout(tab)

        # v1.1.1 (item 4): double click on a node — properties (default,
        # v1.1 behavior) or straight to the SSH login dialog (_run_ssh_connect).
        # The "Connect via SSH" checkbox in properties is not broken — the
        # new mode merely duplicates it faster.
        self.node_dblclick_combo = QComboBox()
        self.node_dblclick_combo.addItem(
            _t("settings.map.node_double_click.properties"), "properties")
        self.node_dblclick_combo.addItem(
            _t("settings.map.node_double_click.connect"), "connect")
        idx = next((i for i in range(self.node_dblclick_combo.count())
                    if self.node_dblclick_combo.itemData(i) == ui_cfg["node_double_click"]), 0)
        self.node_dblclick_combo.setCurrentIndex(idx)
        self._lbl_node_dblclick = QLabel(_t("settings.map.node_double_click"))
        form.addRow(self._lbl_node_dblclick, self.node_dblclick_combo)

        # v1.1.1 (item 6): the connection type on the plaque ("SSH · <label>") —
        # handy for PNG/PDF export, where color is less visible; off by default.
        self.show_conn_type_chk = QCheckBox(_t("settings.map.show_connection_type"))
        self.show_conn_type_chk.setChecked(ui_cfg["show_connection_type"])
        form.addRow("", self.show_conn_type_chk)

        self.tabs.addTab(tab, _t("settings.tab.map"))

    # ── "Hotkeys" tab (v1.3.2: the configurable hotkeys — the action registry) ──────

    def _build_hotkeys_tab(self):
        """v1.3.2 (ROADMAP task 2): a table [action | hotkey] over the action registry.

        One row per ``ui/hotkey_registry.py`` action (declaration order) with a
        QKeySequenceEdit; the action's NAME reuses the existing menu i18n key (no new
        strings for the list itself). An EMPTY sequence = the hotkey is disabled, the
        action stays available from the menu. Two actions with the same sequence are
        BOTH marked + the warning label appears — saving is still possible (Qt
        resolves the ambiguity at runtime, and the user may be mid-edit).
        """
        try:
            from ui.hotkey_registry import (
                action_ids, action_label_key, configured_hotkeys,
            )
        except ImportError:  # flat launch from the project root
            from hotkey_registry import (
                action_ids, action_label_key, configured_hotkeys,
            )
        # The registry/worker import path is fixed by the module, not by the dialog:
        # _apply_settings_from_dialog() in MainWindow does the actual installation.
        self._hotkey_ids = list(action_ids())
        current = configured_hotkeys()

        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.hotkeys_table = QTableWidget(len(self._hotkey_ids), 2, tab)
        self.hotkeys_table.setHorizontalHeaderLabels(
            [_t("settings.hotkeys.action"), _t("settings.hotkeys.sequence")])
        self.hotkeys_table.verticalHeader().setVisible(False)
        self.hotkeys_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hotkeys_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.hotkeys_table.setShowGrid(False)
        header = self.hotkeys_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.hotkey_edits = {}
        for row, action_id in enumerate(self._hotkey_ids):
            item = QTableWidgetItem(_t(action_label_key(action_id)))
            self.hotkeys_table.setItem(row, 0, item)
            edit = QKeySequenceEdit(QKeySequence(current.get(action_id, "")), self.hotkeys_table)
            try:  # Qt >= 6.4: the built-in "clear" button — one click to disable a hotkey
                edit.setClearButtonEnabled(True)
            except AttributeError:
                pass
            # keySequenceChanged carries the new QKeySequence; the slot ignores it and
            # re-reads every editor (the conflict set is global, one edit can clear it).
            edit.keySequenceChanged.connect(self._on_hotkey_changed)
            self.hotkeys_table.setCellWidget(row, 1, edit)
            self.hotkey_edits[action_id] = edit

        self._lbl_hotkeys_disabled_hint = QLabel(_t("settings.hotkeys.disabled_hint"))
        self._lbl_hotkeys_disabled_hint.setWordWrap(True)
        self._lbl_hotkeys_conflict = QLabel("")
        self._lbl_hotkeys_conflict.setWordWrap(True)

        layout.addWidget(self.hotkeys_table, 1)
        layout.addWidget(self._lbl_hotkeys_disabled_hint)
        layout.addWidget(self._lbl_hotkeys_conflict)

        self.tabs.addTab(tab, _t("settings.tab.hotkeys"))
        self._refresh_hotkey_conflicts()   # the saved config itself may already conflict

    def hotkey_sequences(self) -> dict:
        """The table's current values: {action_id: sequence string} ("" = disabled)."""
        return {aid: edit.keySequence().toString()
                for aid, edit in getattr(self, "hotkey_edits", {}).items()}

    def _on_hotkey_changed(self, *_args):
        """A QKeySequenceEdit changed — re-evaluate the conflicts (both rows are marked)."""
        self._refresh_hotkey_conflicts()

    def _refresh_hotkey_conflicts(self):
        """Mark the conflicting rows + show/hide the warning. Never raises."""
        try:
            try:
                from ui.hotkey_registry import action_label_key, find_conflicts
            except ImportError:
                from hotkey_registry import action_label_key, find_conflicts
            conflicts = find_conflicts(self.hotkey_sequences())
        except Exception:  # noqa: BLE001 — the marking is cosmetic
            return
        try:
            for row, action_id in enumerate(self._hotkey_ids):
                item = self.hotkeys_table.item(row, 0)
                if item is None:
                    continue
                marked = action_id in conflicts
                label = _t(action_label_key(action_id))
                item.setText(("\u26a0 " if marked else "") + label)
                item.setForeground(QColor(theme.STATUS_WARN if marked else theme.TEXT_PRIMARY))
            self._lbl_hotkeys_conflict.setText(
                _t("settings.hotkeys.conflict") if conflicts else "")
        except RuntimeError:
            pass  # Qt teardown — the table is already destroyed

    # ── "Language" tab (immediate application — before OK) ────────────────────────

    def _build_language_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.language_combo = QComboBox()
        try:
            from i18n import get_available_languages, get_current_language
            for lg in get_available_languages():
                self.language_combo.addItem(lg["name"], lg["code"])
            cur = get_current_language()
        except Exception:  # noqa: BLE001 — without i18n the combo is not built
            cur = ""
        idx = next((i for i in range(self.language_combo.count())
                    if self.language_combo.itemData(i) == cur), 0)
        self.language_combo.setCurrentIndex(idx)
        # Immediate application — AFTER setting the initial index (otherwise the
        # currentIndexChanged echo at construction time would switch the
        # language onto itself).
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._lbl_language = QLabel(_t("settings.language.label"))
        form.addRow(self._lbl_language, self.language_combo)
        self.tabs.addTab(tab, _t("settings.tab.language"))

    def _refresh_language_combo(self):
        """v1.3.3.1 (ROADMAP task 3): re-read the discovered languages at dialog open.

        The combo was built once at dialog construction; a language file dropped into
        `i18n/` afterwards must not need a restart — `showEvent` calls this. The
        current language is preselected, so the refresh does not fire
        `currentIndexChanged` for the already active language. Never raises.
        """
        combo = getattr(self, "language_combo", None)
        if combo is None:
            return
        try:
            from i18n import get_available_languages, get_current_language
            langs = get_available_languages()
            cur = get_current_language()
        except Exception:  # noqa: BLE001 — a broken i18n leaves the combo as it is
            return
        try:
            if [combo.itemData(i) for i in range(combo.count())] == [lg["code"] for lg in langs]:
                return  # nothing changed — do not touch the selection
            combo.blockSignals(True)   # a programmatic rebuild must not re-apply the language
            combo.clear()
            for lg in langs:
                combo.addItem(lg["name"], lg["code"])
            idx = next((i for i in range(combo.count())
                        if combo.itemData(i) == cur), 0)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown — the combo is already destroyed

    def showEvent(self, event):
        """v1.3.3.1: refreshing the language list is part of "open the dialog"."""
        super().showEvent(event)
        try:
            self._refresh_language_combo()
        except Exception:  # noqa: BLE001 — show must never crash
            pass

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_language_changed(self, index: int):
        """The "Language" tab: immediate application (set_language + UI retranslate)."""
        code = self.language_combo.itemData(index)
        if not code:
            return
        self.language_changed.emit(code)
        # The dialog's own labels are updated immediately (t() is already in the new language).
        try:
            self.retranslate()
        except RuntimeError:
            pass  # Qt teardown

    def _on_accept(self):
        """OK: save the collected values to config.json + the applied signal."""
        try:
            from i18n import save_config
            if not save_config(self.collect()):
                QMessageBox.warning(
                    self, _t("msg.error_title"),
                    _t("msg.save_failed", error="~/.sshmap/config.json"))
                return  # do not close silently — the user sees the error
        except Exception as e:
            # v1.2.10 (AUDIT auto #3): the quiet `return` left a "frozen" dialog without an explanation;
            # now — a log + a visible error, as in the save_config()==False branch above (the same i18n keys).
            try:
                from modules.logger import get_logger
                get_logger("ui.settings_dialog").warning(f"save_config failed: {e}")
            except Exception:
                pass
            QMessageBox.warning(
                self, _t("msg.error_title"),
                _t("msg.save_failed", error="~/.sshmap/config.json"))
            return
        self.applied.emit()
        self.accept()

    # ── Collecting values (config.json keys; language is NOT included — it is immediate) ───────

    def collect(self) -> dict:
        """The tab values → the ~/.sshmap/config.json keys (all valid by construction:
        the combos give fixed ids, the spinboxes — their own range).

        v1.1.1: +7 keys — the UI/terminal fonts (ui_font_family/ui_font_size/
        terminal_font), the terminal limit (terminal_max_open), the node
        double click (ui_node_double_click), the sidebar buttons
        (ui_show_sidebar_buttons) and the type on the connection plaque
        (ui_show_connection_type). ui_font_size = 0 — the system size
        (the load_ui_settings() validator reads the range 6..72, otherwise
        the default).
        v1.1.2 final: +1 key — status_max_parallel (the cap on parallel
        probes; the spinbox range = the validator clamp of
        get_status_settings()).
        v1.2.2: +1 key — terminal_mode ("windows"|"tabs"; the combo gives
        fixed ids).
        v1.3.2: +1 key — hotkeys (a nested dict action_id → sequence string;
        "" = the hotkey is disabled). The values come from the QKeySequenceEdit
        cells; MainWindow._apply_hotkeys() installs them live after the
        applied signal (no restart). Conflict rows are saved as-is by design.
        """
        return {
            "external_terminal": self.ext_term_combo.currentData() or "auto",
            # v1.2.2 (task 4): the terminal display mode
            "terminal_mode": self.mode_combo.currentData() or "windows",
            "terminal_palette": self.palette_combo.currentData() or "default",
            "terminal_font_size": int(self.font_size_spin.value()),
            "terminal_history_lines": int(self.history_spin.value()),
            "terminal_close_behavior": self.close_behavior_combo.currentData() or "close",
            "status_interval_sec": int(self.status_interval_spin.value()),
            "status_probe_timeout_sec": float(self.probe_timeout_spin.value()),
            # v1.1.2 final (task 2): the cap on parallel probes per round
            "status_max_parallel": int(self.max_parallel_spin.value()),
            "autosave_enabled": bool(self.autosave_enabled_chk.isChecked()),
            "autosave_interval_sec": int(self.autosave_interval_spin.value()),
            "backup_count": int(self.backup_count_spin.value()),
            # v1.1.1: fonts (UI + terminal) and the own-terminals limit
            "ui_font_family": self.ui_font_family_edit.text().strip(),
            "ui_font_size": int(self.ui_font_size_spin.value()),
            "terminal_font": self.term_font_family_edit.text().strip(),
            "terminal_max_open": int(self.max_open_spin.value()),
            # v1.1.1: map/sidebar options
            "ui_node_double_click": self.node_dblclick_combo.currentData() or "properties",
            "ui_show_sidebar_buttons": bool(self.sidebar_buttons_chk.isChecked()),
            "ui_show_connection_type": bool(self.show_conn_type_chk.isChecked()),
            # v1.3.2 (ROADMAP task 2/3): the configurable hotkeys — the table's values
            # ({} — a dialog built without the tab, a defensive fallback)
            "hotkeys": self.hotkey_sequences(),
        }

    # ── i18n: retranslating the dialog's own strings (a language change in the open dialog) ───

    def retranslate(self):
        """Re-apply translations to the dialog's strings (the registry — here)."""
        self.setWindowTitle(_t("settings.title"))
        self.tabs.setTabText(0, _t("settings.tab.general"))
        self.tabs.setTabText(1, _t("settings.tab.terminal"))
        self.tabs.setTabText(2, _t("settings.tab.statuses"))
        self.tabs.setTabText(3, _t("settings.tab.autosave"))
        self.tabs.setTabText(4, _t("settings.tab.map"))
        self.tabs.setTabText(5, _t("settings.tab.hotkeys"))   # v1.3.2
        self.tabs.setTabText(6, _t("settings.tab.language"))

        self._lbl_ext_term.setText(_t("settings.general.external_terminal"))
        for i in range(self.ext_term_combo.count()):
            tid = self.ext_term_combo.itemData(i)
            if tid:
                self.ext_term_combo.setItemText(i, _t(f"ssh_ext.preset.{tid}"))

        # v1.1.1: UI font + sidebar buttons ("General" tab)
        self._lbl_ui_font_family.setText(_t("settings.general.ui_font_family"))
        self._lbl_ui_font_size.setText(_t("settings.general.ui_font_size"))
        self.ui_font_size_spin.setSpecialValueText(_t("settings.ui_font_system"))
        self.sidebar_buttons_chk.setText(_t("settings.general.sidebar_buttons"))

        # v1.2.2: the display mode ("Terminal" tab)
        self._lbl_mode.setText(_t("settings.terminal.mode"))
        for i in range(self.mode_combo.count()):
            mid = self.mode_combo.itemData(i)
            key = {
                "windows": "settings.terminal.mode.windows",
                "tabs": "settings.terminal.mode.tabs",
            }.get(mid)
            if key:
                self.mode_combo.setItemText(i, _t(key))

        self._lbl_palette.setText(_t("settings.terminal.palette"))
        for i in range(self.palette_combo.count()):
            pid = self.palette_combo.itemData(i)
            key = {
                "default": "settings.terminal.palette.default",
                "nord": "settings.terminal.palette.nord",
                "dracula": "settings.terminal.palette.dracula",
                "tokyo_night": "settings.terminal.palette.tokyo_night",
            }.get(pid)
            if key:
                self.palette_combo.setItemText(i, _t(key))
        self._lbl_term_font_family.setText(_t("settings.terminal.font_family"))
        self._lbl_font_size.setText(_t("settings.terminal.font_size"))
        self._lbl_max_open.setText(_t("settings.terminal.max_open"))
        self._lbl_history.setText(_t("settings.terminal.history_lines"))
        self._lbl_close_behavior.setText(_t("settings.terminal.close_behavior"))
        for i in range(self.close_behavior_combo.count()):
            cid = self.close_behavior_combo.itemData(i)
            key = {
                "close": "settings.terminal.close_behavior.close",
                "ask": "settings.terminal.close_behavior.ask",
            }.get(cid)
            if key:
                self.close_behavior_combo.setItemText(i, _t(key))

        self._lbl_status_interval.setText(_t("settings.statuses.interval"))
        self._lbl_probe_timeout.setText(_t("settings.statuses.timeout"))
        self._lbl_max_parallel.setText(_t("settings.statuses.max_parallel"))

        self.autosave_enabled_chk.setText(_t("settings.autosave.enabled"))
        self._lbl_autosave_interval.setText(_t("settings.autosave.interval"))
        self._lbl_backup_count.setText(_t("settings.autosave.backups"))

        # v1.1.1: map options ("Map" tab)
        self._lbl_node_dblclick.setText(_t("settings.map.node_double_click"))
        for i in range(self.node_dblclick_combo.count()):
            cid = self.node_dblclick_combo.itemData(i)
            key = {
                "properties": "settings.map.node_double_click.properties",
                "connect": "settings.map.node_double_click.connect",
            }.get(cid)
            if key:
                self.node_dblclick_combo.setItemText(i, _t(key))
        self.show_conn_type_chk.setText(_t("settings.map.show_connection_type"))

        # v1.3.2: the "Hotkeys" tab — the headers, the hint, the warning and the
        # per-row action names (they reuse the existing menu i18n keys).
        self.hotkeys_table.setHorizontalHeaderLabels(
            [_t("settings.hotkeys.action"), _t("settings.hotkeys.sequence")])
        self._lbl_hotkeys_disabled_hint.setText(_t("settings.hotkeys.disabled_hint"))
        self._refresh_hotkey_conflicts()   # re-marks the rows + re-texts the warning

        self._lbl_language.setText(_t("settings.language.label"))

        self.ok_btn.setText(_t("settings.ok"))
        self.cancel_btn.setText(_t("settings.cancel"))
