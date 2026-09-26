import os
import sys
import copy
import itertools
from typing import Optional, List, Dict

try:
    from ..graphics.map_scene import MapScene
    from ..graphics.map_view import MapView
    from ..graphics.server_node import ServerNode
    from ..graphics.node_group import NodeGroup  # v0.8.1: node grouping (clusters/folders)
    # v1.5.4 (ROADMAP tasks 1/2): the ONE declaration of "in trouble" — the group
    # aggregate and the "problems only" lens must mean the same thing by construction
    from ..graphics.node_group import is_in_trouble as node_in_trouble
except ImportError:
    from graphics.map_scene import MapScene
    from graphics.map_view import MapView
    from graphics.server_node import ServerNode
    from graphics.node_group import NodeGroup  # v0.8.1
    from graphics.node_group import is_in_trouble as node_in_trouble

try:
    from ..dialogs.add_server_dialog import AddServerDialog
    from ..dialogs.connection_dialog import ConnectionDialog
    from ..dialogs.ssh_connect_dialog import SSHConnectDialog
    # v1.4.1: the SSH-config import picker (used by NodeOpsMixin via host_attr — the test seam)
    from ..dialogs.ssh_config_import_dialog import SshConfigImportDialog
    # v1.5rc2: the export palette question (the print-friendly default + its opt-out)
    from ..dialogs.export_options_dialog import ExportOptionsDialog
    # v1.6 (ROADMAP tasks 1/6): the bulk edit of the selection and the group arrangement —
    # both are used by the mixin through host_attr (the MW.<name> test seam).
    from ..dialogs.bulk_edit_dialog import BulkEditDialog
    from ..dialogs.arrange_group_dialog import ArrangeGroupDialog
except ImportError:
    from dialogs.add_server_dialog import AddServerDialog
    from dialogs.connection_dialog import ConnectionDialog
    from dialogs.ssh_connect_dialog import SSHConnectDialog
    from dialogs.ssh_config_import_dialog import SshConfigImportDialog
    from dialogs.export_options_dialog import ExportOptionsDialog
    from dialogs.bulk_edit_dialog import BulkEditDialog
    from dialogs.arrange_group_dialog import ArrangeGroupDialog

# v1.1.4: AddServerDialog/ConnectionDialog/SSHConnectDialog/SSHTerminalWindow/_ext_term —
# TEST SUBSTITUTION POINTS (MW.<name> = Fake): methods moved to mixins
# (NodeOpsMixin._add_server/_add_connection, SshMixin._run_ssh_connect/
# _spawn_terminal_window/_connect_ssh_external) resolve them from THIS module at
# call time (host_attr, see ui/mixin_support.py) — so the imports stay here,
# even if the core no longer uses them directly (ConnectionDialog/SSHConnectDialog).

try:
    from ..modules.ssh_terminal import SSHTerminalWindow
except ImportError:
    from modules.ssh_terminal import SSHTerminalWindow

try:  # v0.8.2: external (system) terminal (v1.1.4: used by SshMixin via host_attr)
    from ..modules import external_terminal as _ext_term
except ImportError:
    try:
        from modules import external_terminal as _ext_term
    except ImportError:
        _ext_term = None

try:  # UI polish: vector icons (replacing emoji)
    from . import icons as _icons_mod
    from .icons import get_icon, refresh_action_icon, set_action_icon
except ImportError:
    try:
        from ui import icons as _icons_mod
        from ui.icons import get_icon, refresh_action_icon, set_action_icon
    except ImportError:
        try:
            import icons as _icons_mod
            from icons import get_icon, refresh_action_icon, set_action_icon
        except ImportError:  # flat layout without ui/icons — text buttons, as before
            _icons_mod = None

            def get_icon(name):  # noqa: N802 — stub with the same signature
                return None

            def set_action_icon(action, name):  # noqa: N802 — stub
                return False

            def refresh_action_icon(action):  # noqa: N802 — stub
                return False

try:  # v0.9.9.4: sidebar cluster (tree, tag filter, status markers, context menu)
    from .sidebar import SidebarPanel
    # v1.5.5 (ROADMAP task 2): the inventory report — the pure CSV/TSV writer of the table
    from .sidebar import list_delimiter, list_table_text
except ImportError:
    from sidebar import SidebarPanel
    from sidebar import list_delimiter, list_table_text

try:  # v1.6 (ROADMAP task 5): the connection report — the rows the pure writer consumes
    from ..storage.export_connections import connection_report_rows
except ImportError:
    try:
        from storage.export_connections import connection_report_rows
    except ImportError:  # flat layout without storage/ — the export reports itself unavailable
        connection_report_rows = None

try:  # v1.5rc3 (ROADMAP task 2): the status bar that can offer an Undo
    from .status_bar import UndoStatusBar
    # v1.5rc4 (ROADMAP task 1): the status-bar overflow policy — the ONE pure decision
    # plus the measured width the bar asks for
    from .status_bar import is_compact as status_bar_is_compact
    from .status_bar import status_bar_needed_width
except ImportError:  # flat layout: the ui/ directory itself is on sys.path
    try:
        from status_bar import UndoStatusBar
        from status_bar import is_compact as status_bar_is_compact
        from status_bar import status_bar_needed_width
    except ImportError:  # a stripped build — the plain QStatusBar (no affordance)
        UndoStatusBar = None
        status_bar_is_compact = None
        status_bar_needed_width = None

try:  # v1.1.2RC3 (AUDIT U2): window sizes — saveGeometry()/saveState() into config.json
    from ..modules.window_geometry import (
        save_window_geometry, restore_window_geometry,
        # v1.3.3.6 (ROADMAP task 4): the panel widths — base64 QSplitter.saveState()
        save_splitter_state, restore_splitter_state,
    )
except ImportError:
    from modules.window_geometry import (
        save_window_geometry, restore_window_geometry,
        save_splitter_state, restore_splitter_state,
    )

try:  # v1.2.3 (ROADMAP v1.2.3): multi-input — hub broadcasting input to all sessions
    from ..modules import multi_input as _multi_input_mod
except ImportError:
    from modules import multi_input as _multi_input_mod

try:  # v1.4rc1 (plugin foundation): discovery + the registry of the plugins
    from ..modules import plugin_manager as plugin_manager
except ImportError:
    from modules import plugin_manager as plugin_manager

try:  # v1.5.2 (ROADMAP task 1): the in-memory activity ring the panel renders
    from ..modules import activity_log as _activity_mod
except ImportError:
    try:
        from modules import activity_log as _activity_mod
    except ImportError:  # flat layout: the modules/ directory itself is on sys.path
        try:
            import activity_log as _activity_mod
        except ImportError:  # a stripped build — the panel is simply unavailable
            _activity_mod = None

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from . import theme
except ImportError:
    try:
        from ui import theme
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme

try:  # v1.4.3 (ROADMAP task 4): the Qt half of the theme — the QSS/palette + the live switch
    from . import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None


from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect  # QPoint/QRect — the floating-panel geometry (v1.4.5/v1.5rc4)
from PySide6.QtGui import (
    QFont,      # v1.1.1: UI font from config (QApplication.setFont)
    QAction,    # v1.4rc1: the per-plugin rows of the "Plugins" menu (insertAction)
    QMouseEvent,
    QUndoStack,  # v0.8.3: undo/redo
    QKeySequence,  # v1.3.2: an empty sequence = the multi-input hotkey is not installed
    QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,  # v1.2.4.1: collapse strips/diamonds
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter,
    QLabel, QTreeWidgetItem,  # QTreeWidgetItem — tree slot annotations (v0.9.9.4: tree in ui/sidebar.py)
    QToolBar, QMessageBox, QDialog, QFileDialog, QMenu,
    QApplication, QToolButton,  # QToolButton — exit button on the multi-input plaque (v1.2.3)
)

# v1.1.4 (ROADMAP): split into mixins — the "project I/O", "node/connection
# operations", and "SSH/terminals" clusters live in ui/main_window_*.py. MainWindow
# remains a facade: public API, method names, and call sites are unchanged;
# the mixins do NOT import main_window (circular) — duck-typing on the instance only.
try:
    from .main_window_project_io import ProjectIOMixin
    from .main_window_node_ops import NodeOpsMixin, _is_scene_point
    from .main_window_ssh import SshMixin
except ImportError:  # flat layout without the package (same pattern as the imports above)
    from main_window_project_io import ProjectIOMixin
    from main_window_node_ops import NodeOpsMixin, _is_scene_point
    from main_window_ssh import SshMixin


# ── v1.2.4.1: collapsing the sidebar/map into a thin strip (ROADMAP v1.2.4.1) ──

def _diamond_icon():
    """Vector "◇" diamond on a 20×20 canvas (corner collapse buttons).

    v1.2.4.1-fix (QA request): instead of "›"/"‹" chevrons — a single diamond on both
    panels (sidebar and map — both at the bottom right; the top of the map is reserved
    for the minimap). Same technique as ui/icons.py (QPainterPath on a transparent QPixmap),
    but the icon lives locally: per the spec only the sidebar_panel/map_panel
    pair goes into _DRAWERS (the "View" menu items), while the button/strip diamonds
    are window-internal graphics.
    """
    pm = QPixmap(20, 20)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    # v1.4.3-fix: read at CALL time — the icon is rebuilt by refresh_theme()
    # (before the fix this read a value captured at import time and the diamond
    # stayed dark-theme pale after a switch to LIGHT).
    pen = QPen(QColor(theme.ICON_COLOR), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(10.0, 4.5)
    path.lineTo(15.5, 10.0)
    path.lineTo(10.0, 15.5)
    path.lineTo(4.5, 10.0)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


class _CollapseStrip(QWidget):
    """Thin clickable strip of a collapsed panel (~18 px; ROADMAP v1.2.4.1, task 1).

    A click ANYWHERE expands the panel (expand_requested); inside — the "◇" diamond
    at the bottom right (v1.2.4.1-fix: instead of the chevron, QA request) + a tooltip
    (set by MainWindow).
    The real panel widget is hidden at the same time: a hidden child takes 0px —
    native Qt, no custom layout. Colors — the app's dark Fusion palette
    (theme.WINDOW_BG / theme.BASE_BG, v1.2.5): the strip reads well on both the sidebar and the map background.
    """

    expand_requested = Signal()
    STRIP_WIDTH = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.STRIP_WIDTH)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.expand_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # v1.2.5: colors — from the central theme (ui/theme.py); values unchanged.
        p.fillRect(self.rect(), QColor(theme.SURFACE_ALT if self._hover else theme.BASE_BG))
        # "◇" diamond at the bottom right (v1.2.4.1-fix: QA request — instead of the chevron;
        # the same spot as the expanded panel's corner button — the diamond is "at the bottom"
        # both before and after collapsing).
        pen = QPen(QColor(theme.ICON_COLOR), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = float(self.width()) - 9.0, float(self.height()) - 12.0
        path = QPainterPath()
        path.moveTo(cx, cy - 4.5)
        path.lineTo(cx + 4.5, cy)
        path.lineTo(cx, cy + 4.5)
        path.lineTo(cx - 4.5, cy)
        path.closeSubpath()
        p.drawPath(path)
        p.end()


# ── v1.4.5 (ROADMAP task 3): the clickable status counters of the status bar ───

# The order the three status counters appear in (the same order the cards, the dots
# and the status bar text have always used).
STATUS_FILTER_ORDER = ("online", "warn", "offline")

# The upper bound of a QWidget's width. QWIDGETSIZE_MAX is a C macro in qwidget.h and
# is therefore not exposed by PySide6 — the value is the documented one.
_WIDGET_MAX_WIDTH = 16777215

# ── v1.4.6 (ROADMAP follow-up): the VIEW toggles of the toolbar ───────────────
# (action id, icon name, i18n key, the literal fallback of the key) — ONE group at the
# right end of the toolbar, in the order the surfaces sit in the window: the sidebar, the
# map (whose collapsedness is the LIST mode), the minimap, the legend and the activity
# panel. Every button is a MIRROR of its checkable "View" item — the menu item owns the
# hotkey and the state (the v1.3.3.3 "ambiguous shortcut" rule), the button owns the click.
# v1.6 (ROADMAP task 7): the ACTIVITY switch joins the cluster — the deliverable is the
# CLUSTER, not one button: a new panel joins it by naming its action, with no second
# mechanism (the bookmark panel of the backlog is the next one).
_VIEW_TOOLBAR_ITEMS = (
    ("view.toggle_sidebar", "sidebar_panel", "view.toggle_sidebar", "Sidebar"),
    ("view.toggle_map", "map_panel", "view.toggle_map", "Map"),
    ("view.toggle_minimap", "minimap", "view.toggle_minimap", "Minimap"),
    ("view.toggle_legend", "legend", "view.toggle_legend", "Legend"),
    ("view.toggle_activity", "activity", "view.toggle_activity", "Activity"),
)

# action id → the MainWindow attribute holding the OWNER QAction (the wiring in
# `_setup_menubar` + the two generic slots below; the buttons themselves live in
# `self._view_toolbar_buttons`).
_VIEW_TOOLBAR_ACTIONS = {
    "view.toggle_sidebar": "act_show_sidebar",
    "view.toggle_map": "act_show_map",
    "view.toggle_minimap": "act_show_minimap",
    "view.toggle_legend": "act_show_legend",
    "view.toggle_activity": "act_show_activity",
}


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


# ── v1.3.3.6 (ROADMAP task 2): dropping a project onto the window ──────────────
# Dragging a saved `.json`/`.sshmap` onto the window is the standard gesture of the
# platform, and it went through nothing: `setAcceptDrops(True)` existed only on the
# SFTP tab (`modules/sftp_tab.py:293/419`). The drop is deliberately narrow — ONE
# existing local FILE with a project suffix — and it goes through `_load_project_at()`
# (the File → Open entry point), so every downstream rule (the autosave prompt, the
# undo reset, the status round, the MRU) is shared instead of re-implemented.

PROJECT_DROP_SUFFIXES = (".json", ".sshmap")


def _dropped_local_paths(mime_data) -> list:
    """Local file paths carried by a drop — no suffix filter, no existence filter.

    The `SftpTab._local_files` precedent narrowed to "is this even a local drag":
    a text drag (a URL/plain text from another application) is not a gesture this
    window advertises, so it is not accepted at all and the OS keeps its "no drop"
    cursor. Everything else reaches `dropEvent`, where the strict validation runs
    and a refusal can be EXPLAINED instead of silently ignored.
    """
    out = []
    if mime_data is None:
        return out
    try:
        if not mime_data.hasUrls():
            return out
        urls = mime_data.urls()
    except (AttributeError, RuntimeError):
        return out
    for url in urls:
        try:
            if url.isLocalFile():
                out.append(url.toLocalFile())
        except (AttributeError, RuntimeError):
            continue
    return out


def _project_drop_candidate(mime_data) -> str:
    """The ONE project file a drop carries — '' when the drop must be refused.

    Strict on purpose (ROADMAP task 2): exactly one path, it must be an existing
    FILE (a directory is refused) and carry a `.json`/`.sshmap` suffix (case
    insensitive — Windows hands out `MyMap.JSON`).
    """
    paths = _dropped_local_paths(mime_data)
    if len(paths) != 1:
        return ""
    path = paths[0]
    try:
        if not os.path.isfile(path):
            return ""  # a directory / a path that vanished mid-drag
    except OSError:
        return ""
    if os.path.splitext(path)[1].lower() not in PROJECT_DROP_SUFFIXES:
        return ""
    return path


class MainWindow(ProjectIOMixin, NodeOpsMixin, SshMixin, QMainWindow):
    # v1.5rc2 (ROADMAP task 3): the LAST export palette choice ("use the current
    # theme"), remembered for the SESSION only — the export palette is deliberately
    # NOT a config key (the hub's collect() contract stays 22 keys) — and read/written
    # by `_ask_export_palette()`. False = the print-friendly default.
    _export_use_current_theme = False

    def __init__(self):
        super().__init__()

        # ── v1.4.3 (ROADMAP task 6): the SAVED theme, before anything is built ──
        # `main.py` applies it too (even earlier, right after QApplication), but the
        # window does not depend on that: a MainWindow created directly (a test, an
        # embedder) must still come up in the user's theme — and every widget below
        # is then CONSTRUCTED with the right palette instead of being repainted
        # afterwards. A broken config can never leave the app themeless
        # (`theme_from_settings` never fails, `apply_theme` never raises).
        if theme_qss is not None:
            try:
                from ui.settings_dialog import (load_theme_settings, theme_from_settings,
                                                apply_motion_setting, apply_density_setting)
            except ImportError:  # flat launch from the project root
                try:
                    from settings_dialog import (load_theme_settings, theme_from_settings,
                                                 apply_motion_setting, apply_density_setting)
                except ImportError:
                    load_theme_settings = theme_from_settings = apply_motion_setting = None
                    apply_density_setting = None
            if load_theme_settings is not None:
                try:
                    _saved_theme = load_theme_settings()
                    theme_qss.apply_theme(theme_from_settings(_saved_theme),
                                          refresh_windows=False)
                    # v1.5rc1 (ROADMAP task 6): the motion flag of the SAME key —
                    # installed here as well, because a MainWindow built directly
                    # (a test, an embedder) never goes through main.py.
                    apply_motion_setting(_saved_theme)
                    # v1.6 (ROADMAP task 2): the card density of the same key — a window
                    # built directly must come up in the user's card mode too.
                    if apply_density_setting is not None:
                        apply_density_setting(_saved_theme)
                except Exception as e:  # noqa: BLE001 — the look must not break startup
                    print(f"[theme] the saved theme was not applied: {e}", flush=True)
        # v1.5rc1 (ROADMAP task 6): in the "Auto (system)" mode the window follows
        # the platform's colour scheme live. Installed once, guarded — a platform
        # without `QStyleHints.colorScheme` simply never emits.
        self._install_color_scheme_watch()

        # ── i18n: restore user's last language choice ──
        self._i18n_available = False
        
        try:
            from i18n import (
                set_language as _set_lang,
                get_last_language,  # Restore preferred language
            )
            
            # Use last saved language or fall back to default
            preferred = get_last_language()
            self.current_language = preferred
            _set_lang(preferred)
            
            from i18n import t as __t
            self.t = __t  # Make translate function available on instance
            self._i18n_available = True
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
        
        self.resize(1200, 850)

        # v1.1.2RC3 (AUDIT U2): restore the main window size/state from
        # config.json (saved in closeEvent). No key / a corrupt value ->
        # the default 1200×850 above; the geometry must not break startup.
        try:
            restore_window_geometry("ui_window_geometry_main", self)
        except Exception:  # noqa: BLE001
            pass

        self._project_file: Optional[str] = None
        # v1.5rc3 (ROADMAP task 1): is the map on screen the DEMO project? Set by
        # `_load_project_at(..., example=True)`, cleared by a new project, a file load
        # and the first save; it is what the title marker reads (`_update_window_title`).
        self._example_project: bool = False
        # v1.5 (ROADMAP): the node ids whose status is EMULATED by the demo map
        # (`storage/example_project.DEMO_STATUSES`), i.e. the set `StatusChecker` must
        # never probe. Empty for every ordinary project — the demo's emulation never
        # outlives it (`_set_emulated_statuses()` is the ONE writer).
        self._emulated_statuses: dict = {}
        self._dirty = False  # Unsaved-changes flag (the " [*]" marker in the title)
        # v1.2 (ROADMAP task 4): registry of open terminal SESSIONS
        # (modules/terminal_page.TerminalSessionPage), not windows — the node's green dot
        # goes out only when ALL of the node's sessions are closed; the "4 own
        # terminals" limit (v1.1.1) is counted per session. Name kept (v1.1.x API).
        self._terminal_windows: List = []
        # v1.2.3 (ROADMAP v1.2.3): multi-input — the mode state lives in the hub
        # (modules/multi_input.py, a process singleton), held by the window as
        # self._multi_hub; TerminalWidget picks up the same hub by default. The provider —
        # the session registry (the same one as the green dot/limit); UI reaction — the
        # _on_multi_changed listener (SshMixin). Shutdown — _multi_shutdown in the closeEvent path.
        self._multi_hub = _multi_input_mod.get_hub()
        self._multi_provider = lambda: list(getattr(self, "_terminal_windows", []))
        self._multi_hub.set_session_provider(self._multi_provider)
        self._multi_hub.add_listener(self._on_multi_changed)
        # v1.2.2: "Terminals" dock (terminal.mode = "tabs") — lazily created in
        # SshMixin._ensure_terminals_dock on the first session in "tabs" mode.
        self._terminals_dock = None
        # v0.9.4-fix: IDs of nodes with an active SSH session (for indicator reset)
        self._ssh_connected_nodes: set = set()
        self._ping_thread = None   # v0.7.3: ping thread (AUDIT v0.7.2 #8: guard against clobbering)
        self._dns_thread = None    # AUDIT v0.7.2 (#6): reverse-DNS thread for copy-hostname
        # v1.5.3 (ROADMAP tasks 2/3): the two new background registries of the release.
        # `_info_collectors` (created lazily by SshMixin._track_info_collector) is the ONE
        # per-node guard of the info family; `_info_batch` is the bounded queue behind
        # "gather information for the selection / all"; `_diagnose_threads` holds the live
        # reachability reports keyed by server id.
        self._info_batch = None
        self._diagnose_threads = {}
        # v1.1.2RC2 (N6): batch DNS resolution for TXT imports off the GUI thread —
        # thread + batch context (pending/path/skipped) awaiting resolved_map
        self._import_resolve_thread = None
        self._import_pending = None   # [entry, ...] file lines awaiting addition
        self._import_path = None      # path of the source TXT file (log/status)
        self._import_skipped = 0      # count of skipped duplicates
        self._menu_i18n: List[tuple] = []  # (widget: QMenu|QAction, key) — for re-translation
        self._sidebar_title: Optional[QLabel] = None

        # ── v1.3.2 (ROADMAP v1.3.2): configurable hotkeys ─────────
        # The registry (ui/hotkey_registry.py) is the single source of truth: every
        # QAction/QShortcut with a hotkey is registered here under its action_id
        # instead of carrying a literal sequence; _apply_hotkeys() (after the UI
        # construction and after the settings dialog's OK) installs the effective
        # sequences from ~/.sshmap/config.json ("hotkeys"). Initialized BEFORE
        # _setup_ui/_setup_toolbar/_setup_menubar — they fill the dict.
        self._hotkey_targets: Dict[str, list] = {}   # action_id -> [QAction|QShortcut, ...]
        self._hotkey_map: Dict[str, str] = {}        # action_id -> the effective sequence

        # ── v0.8.3: Undo/Redo ─────────────────────────────────────
        # The dirty marker is bound to cleanState/stack index: save/load sets a
        # new baseline; undo/redo update the window title themselves.
        self.undo_stack = QUndoStack(self)
        self._undo_baseline_dirty = False  # dirty reasons OUTSIDE undo (statuses, groups)
        self._note_committed = {}          # note_id -> last committed text (debounce)
        self._note_edit_timer = QTimer(self)
        self._note_edit_timer.setSingleShot(True)
        self._note_edit_timer.setInterval(600)  # ms of silence -> the EditTextNote command
        self._note_edit_timer.timeout.connect(self._commit_note_text)
        self._note_edit_pending = None     # (note, old_text) of the active edit

        # ── Logger (lazy import to avoid circular deps at module level) ──
        self._log: Optional[object] = None

        # v1.2.4.1: panel collapse state (menu item checked = expanded).
        # Initialized BEFORE _setup_ui: window methods (_select_node etc.) guard on
        # these flags; the value saved in config.json is applied in
        # _apply_ui_options_from_config (AFTER restore_window_geometry/restoreState).
        self._sidebar_collapsed = False
        self._map_collapsed = False

        # ── v1.5.2 (ROADMAP task 3): the activity panel ────────────
        # The saved visibility is read BEFORE _setup_menubar builds the checkable View
        # item (the ui_legend/ui_minimap pattern: the menu item is the OWNER of the
        # state, the panel is created right after the menubar and follows it). The ring
        # itself is the process-wide singleton of `modules/activity_log.py` — the panel
        # only renders it, so a window that is closed and reopened loses no history.
        self._activity_enabled = MainWindow._read_activity_visible()
        self.activity_panel = None

        # ── v1.4rc1 (plugin foundation, rc series): the plugin registry ─────
        # The manager is created HERE because the "Plugins" menu is built from it; the
        # DISCOVERY itself runs later — main.py calls start_plugin_discovery() after
        # show() and before app.exec() (ROADMAP rc1), so merely constructing a window
        # (every test does) never imports third-party code. The rows of the menu are
        # rebuilt from the records; `_plugin_rows` holds the dynamic QActions, so a
        # rebuild removes exactly its own items and never the permanent "Reload" item.
        self._plugin_manager = plugin_manager.PluginManager(self)
        self._plugin_menu = None
        self.act_plugins_reload = None
        self.act_plugins_run = None
        self._plugin_sep = None
        self._plugin_rows: List = []
        # v1.4rc3: the QActions a plugin added to a CONTEXT menu. They live outside the
        # i18n registry (the menu is built per right-click), so `_rebuild_qaction_guard()`
        # keeps their wrappers alive from here (gotcha #9) — bounded, because a context
        # menu is ephemeral and only the newest ones can still be on screen.
        self._plugin_menu_actions: List = []
        # v1.4rc2 (plugin foundation, rc2): the services of PluginContext — the manager
        # reports FACTS through signals, the window owns the widgets. `_plugin_status_*`
        # is the token guard of `ctx.status()` (the v1.2.2 pattern of the dock's status
        # line): a newer message always invalidates the pending auto-clear of an older
        # one, so an asynchronous plugin result can never blank a fresher message.
        self._plugin_status_tokens = itertools.count()
        self._plugin_status_token = None
        try:
            self._plugin_manager.status_requested.connect(self._on_plugin_status_requested)
            self._plugin_manager.hook_failed.connect(self._on_plugin_hook_failed)
            self._plugin_manager.hook_timeout.connect(self._on_plugin_hook_timeout)
        except Exception as e:  # noqa: BLE001 — a missing signal must not break the window
            if self.log:
                self.log.warning(f"Plugin service signals unavailable: {e}")

        self._setup_ui()
        self._setup_toolbar()
        self._setup_menubar()
        # v1.5.2 (ROADMAP task 3): the activity panel + the status-bar tap. AFTER the
        # menubar (the View item owns its visibility) and BEFORE the first
        # `_apply_ui_translations()` below, so the startup messages are already history.
        self._setup_activity_panel()
        # v1.3.2 (task 3): the hotkeys — applied at startup, AFTER the whole UI
        # (menus/toolbar/palette) exists; the same method runs after the dialog's OK.
        self._apply_hotkeys()
        self._update_window_title()

        # ── i18n: apply translation to UI after setup ──
        if self._i18n_available:
            try:
                self._apply_ui_translations()
            except Exception as e:
                if self.log:
                    self.log.warning(f"i18n UI update error: {e}")

        # ── v1.1.1: saved UI options at startup (fonts, sidebar buttons,
        #    double-click mode) — the same methods as applying them via the dialog's OK ──
        self._node_double_click_mode = "properties"  # default until the config is read
        try:
            self._apply_ui_options_from_config()
        except Exception as e:
            if self.log:
                self.log.warning(f"Apply UI options at startup failed: {e}")

        # ── v1.3.3.6 (ROADMAP task 4): the panel widths — the LAST piece of window
        #    state, applied AFTER restore_window_geometry()/restoreState() above and
        #    AFTER the collapsed-panel states of _apply_ui_options_from_config(). ──
        try:
            self._apply_splitter_state_from_config()
        except Exception as e:  # noqa: BLE001 — the widths must not break startup
            if self.log:
                self.log.warning(f"Restore splitter state failed: {e}")

        # ── v0.7.1: background node status checks (online/warn/offline) ──
        # Probes run in a separate thread — the GUI is not blocked.
        # v1.1 (ROADMAP task 4): interval/timeout — from ~/.sshmap/config.json
        # (status_interval_sec / status_probe_timeout_sec; defaults 30 s / 3.0 s =
        # v1.0 behavior); changed live from the settings dialog (_apply_settings_from_dialog).
        # v1.1.2 final: probes within a round run in parallel (ThreadPoolExecutor),
        # cap — status_max_parallel (default 16); for large maps (N > 50) the
        # interval doubles (effective_interval_ms + a status-bar hint).
        self._status_checker = None
        self._auto_interval_hinted = False  # v1.1.2 final: the large-interval hint — shown once
        try:
            from services.status_checker import StatusChecker as _StatusChecker, \
                get_status_settings as _get_status_cfg
            _st_cfg = _get_status_cfg()
            self._status_checker = _StatusChecker(
                interval_ms=int(_st_cfg["interval_sec"]) * 1000,
                probe_timeout=float(_st_cfg["probe_timeout_sec"]),
                max_parallel=int(_st_cfg["max_parallel"]), parent=self)
            self._status_checker.status_changed.connect(self._on_node_status_changed)
            # v1.4rc2 (plugin foundation, rc2): a plugin's `status_probe` joins the round.
            # The provider is called INSIDE the probe pool worker (a worker thread — the
            # PLUGINS.md §6 discipline); the merged status arrives on `status_changed` and
            # the plugin's detail (a tooltip line) on its own signal. With no plugin
            # implementing the hook the provider returns None and nothing changes.
            self._status_checker.status_detail.connect(self._on_node_status_detail)
            try:
                self._status_checker.set_status_provider(self._plugin_manager.status_provider)
            except Exception as e:  # noqa: BLE001 — the probes must run without plugins too
                if self.log:
                    self.log.warning(f"Plugin status provider not installed: {e}")
            # On window destruction — stop the timer and wait for the current round
            # so a probe thread is not killed in flight with its parent. The slot is a
            # METHOD (v1.5rc3): the checker may be absent (the constructor above has a
            # "StatusChecker unavailable" path, and a test/embedder may drop it), and the
            # previous inline lambda dereferenced it unconditionally.
            self.destroyed.connect(self._shutdown_status_checker)
            # Targets are synced immediately; starting the periodic checks happens once,
            # from main.py after window.show() (see start_status_checks()). In headless
            # tests without an event loop this guarantees no background threads.
            self._sync_status_targets()
        except Exception as e:
            if self.log:
                self.log.warning(f"StatusChecker unavailable: {e}")

        # ── v1.5rc3 (ROADMAP task 3): the freshness tick ──────────
        # A status is a fact with a timestamp, so the map re-reads the age of every
        # shown status a few times per minute. This timer starts NO probe round and
        # changes NO status (the v1.4rc2 plugin/status discipline is untouched): it
        # only moves a card to the stale mark once its datum has really aged past
        # `StatusChecker.stale_threshold_s()`. In a headless test without an event
        # loop it never fires — the module stays smoke-test safe.
        self._freshness_timer = QTimer(self)
        self._freshness_timer.setInterval(self.FRESHNESS_TICK_MS)
        self._freshness_timer.timeout.connect(self._freshness_tick)
        self._freshness_timer.start()

        # ── v0.9.7: autosave (ROADMAP #1) ────────────────────────
        # QTimer at the interval from ~/.sshmap/config.json (autosave_interval_sec,
        # default 60 s; autosave_enabled — on/off). A tick writes an autosave
        # ONLY when dirty and a project file is set (a new unsaved project has
        # nothing to restore — see _autosave_tick). The interval lives until restart;
        # the settings dialog arrives in v1.1 (ROADMAP).
        self._autosave_timer = QTimer(self)
        try:
            from storage.autosave import get_autosave_settings as _get_as
            _as_cfg = _get_as()
        except Exception:  # noqa: BLE001 — defaults matter more; the module is optional
            _as_cfg = {"enabled": True, "interval_sec": 60}
        self._autosave_enabled = bool(_as_cfg.get("enabled", True))
        self._autosave_timer.setInterval(int(_as_cfg.get("interval_sec", 60)) * 1000)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        if self._autosave_enabled:
            self._autosave_timer.start()

    def _shutdown_status_checker(self, *_args):
        """v1.5rc3: the `destroyed` slot — stop the probe timer and the current round.

        Written as a method rather than an inline lambda because the checker can be
        ABSENT: `__init__` leaves `_status_checker = None` when the module is
        unavailable, and an embedder (or a test) may replace it. The old lambda assumed
        a live checker and raised on teardown — exactly the moment nothing may raise.
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return
        try:
            checker.shutdown()
        except Exception as e:  # noqa: BLE001 — a teardown path never raises
            if self.log:
                self.log.warning(f"StatusChecker shutdown failed: {e}")

    def start_status_checks(self):
        """v0.7.1: start periodic status checks (called once)."""
        checker = getattr(self, "_status_checker", None)
        if checker is not None and not checker.is_busy:
            try:
                self._sync_status_targets()
                checker.start()
            except Exception as e:
                if self.log:
                    self.log.warning(f"StatusChecker start failed: {e}")

    # ── v0.7.1: node statuses ────────────────────────────────

    def _sync_status_targets(self):
        """Update the StatusChecker target list to match the current scene nodes.

        v1.3.3.3 (task 5): the normalization lives in ``status_checker._build_targets``
        — the on-demand round of "Check statuses now" builds its list with the same
        helper instead of a drifting copy.
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return
        try:
            from services.status_checker import _build_targets as _mk
        except ImportError:  # flat layout
            from status_checker import _build_targets as _mk
        try:
            _nodes = list(self.scene.nodes())
            checker.set_servers(_mk([
                (n.data.id, n.data.host, n.data.ssh_port or 22)
                for n in _nodes
            ]))
            # v1.5 (ROADMAP): the SAME pass keeps the emulation in step — the demo's
            # declared ids are never probed, and any other project clears the set (it is
            # installed by `_open_example_map()` before the load and cleared by every
            # ordinary load / new project / save). `_set_emulated_statuses` owns the write;
            # this call repeats it so a checker built AFTER the state cannot miss it.
            checker.set_skip_ids(getattr(self, "_emulated_statuses", None) or ())
            # v1.4rc2 (plugin foundation, rc2): the SAME pass feeds the plugin registry —
            # a `status_probe` / `run_on_nodes` hook sees exactly the nodes the map holds
            # (narrowed to {id, alias, host, port, user} by the manager, PLUGINS.md §5).
            # The internal facts carry the private key path, which is deliberately NOT
            # part of the plugin-visible record but IS needed by the core's credential
            # resolver for `ctx.run_command`.
            try:
                self._plugin_manager.set_nodes(
                    [(n.data.id, n.data.alias, n.data.host, n.data.ssh_port or 22, n.data.user)
                     for n in _nodes],
                    facts={n.data.id: {"key_path": getattr(n.data, "key_path", "") or ""}
                           for n in _nodes})
            except Exception as e:  # noqa: BLE001 — a plugin never breaks the probes
                if self.log:
                    self.log.warning(f"Plugin node registry not synced: {e}")
        except Exception as e:
            if self.log:
                self.log.warning(f"StatusChecker set_servers failed: {e}")
            return
        # v1.1.2 final (task 3): large map (N > LARGE_MAP_THRESHOLD) —
        # the check interval doubles (StatusChecker.effective_interval_ms);
        # a one-time status-bar hint when the threshold is crossed upward.
        try:
            if checker.is_large_map():
                if not getattr(self, "_auto_interval_hinted", False):
                    self._auto_interval_hinted = True
                    self.statusBar().showMessage(
                        self.t("status.auto_interval_hint", servers=checker.target_count), 8000)
            else:
                self._auto_interval_hinted = False  # below the threshold again — the hint may fire once more
        except (AttributeError, RuntimeError):
            pass  # Qt teardown — the status bar is already destroyed

    def _on_node_status_detail(self, server_id: str, detail: str):
        """v1.4rc2 (plugin foundation, rc2): the plugin detail of a merged status.

        `StatusChecker.status_detail` carries what a plugin's `status_probe` contributed
        (`PLUGINS.md` §3 — "appended to the node's tooltip"). It travels AFTER
        `status_changed`, so the node already has its colour; the detail only refines the
        tooltip. An empty detail removes a stale one.
        """
        node = self.scene.get_node(server_id)
        if node is None:
            return  # node already removed — it needs no tooltip
        try:
            # v1.5: the detail refines the CURRENT status, so it must not un-mark an
            # EMULATED one (the flag belongs to the status, not to this call).
            node.set_status(node.status, detail, emulated=node.status_emulated)
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"status detail failed for {server_id}: {e}")

    def _on_node_status_changed(self, server_id: str, status: str):
        """Handle the probe result for a single node."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # node already removed — it needs no status
        try:
            node.set_status(status)
            # v1.5rc3 (ROADMAP task 3): the result is dated. The checker owns WHEN the
            # probe answered and how old a result may get (`stale_threshold_s()`); the
            # card owns how it is painted and worded. Nothing here derives a STATUS
            # from the age — freshness is a label on the existing fact.
            self._apply_node_freshness(node)
        except Exception as e:
            if self.log:
                self.log.warning(f"set_status failed for {server_id}: {e}")
        else:
            self._update_counts_label()  # UI polish: online/warn/offline in the status bar
            # Review fix v0.8.0 (#3): the tree row marker is updated in place
            # (node.status — the actual status after set_status; unknowns are ignored)
            self._update_sidebar_status_marker(server_id)
            # v1.4.5 (ROADMAP task 3): a status change can move a node in or out of an
            # ACTIVE status filter — the in-place marker update would leave the filtered
            # tree stale, so the rows are rebuilt (only while a filter is on).
            if getattr(self, "_status_filter", ""):
                try:
                    self.refresh_sidebar()
                except RuntimeError:
                    pass  # Qt teardown — the window is closing
            elif getattr(self, "_problems_only", False):
                # v1.5.4 (ROADMAP task 2): the LENS reads the status too — a card that
                # just went red must light up (and a card that recovered must recede)
                # without a rebuild of the sidebar, which no status filter asked for.
                try:
                    self._apply_map_dimming()
                except Exception:  # noqa: BLE001 — the lens is cosmetic on teardown
                    pass

    # ── v1.5rc3 (ROADMAP task 3): status freshness ──────────────────────────────

    #: How often the age of every shown status is re-evaluated (ms). Purely a repaint
    #: tick: it never starts a probe round (`StatusChecker` owns rounds) and never
    #: changes a status — it only moves a card from "fresh" to "stale" once the datum
    #: has really aged past `stale_threshold_s()`. The walk is bounded by the map size
    #: and does nothing at all while a node was never checked.
    FRESHNESS_TICK_MS = 30_000

    def _apply_node_freshness(self, node) -> bool:
        """Give ONE card the age of its status (the checker is the source of truth).

        Called right after a result arrives and by the freshness tick. Returns True when
        the card's stale state changed. A missing/never-checked datum leaves the card
        untouched: it has nothing to age (`set_checked_at(0.0)` clears the mark).
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return False
        try:
            checked_at = checker.last_checked_at(node.data.id)
            return bool(node.set_checked_at(checked_at, checker.stale_threshold_s()))
        except (RuntimeError, AttributeError):
            return False  # Qt teardown / a test double without the method

    def _refresh_status_freshness(self):
        """Re-evaluate the age of every shown status (the freshness tick).

        Refresh NEVER changes a status and NEVER starts a round: it re-reads the
        timestamps the checker already recorded and repaints what has grown old. A
        status that cannot be refreshed (no checker, a headless test) is simply left as
        it is — the map is honest either way, it just says less.

        v1.5.3 (ROADMAP task 1): the SAME tick re-reads the age of the COLLECTED FACTS.
        They are dated in the data itself (`info_collected_at`), so no checker is involved
        and the two families stay independent: this second walk only repaints a plaque
        whose measurement has crossed `ServerNode.INFO_STALE_AFTER_SEC` (a week) — a fresh
        status never hides an old hardware line and the other way round.
        """
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return  # the scene is not created yet / already destroyed
        checker = getattr(self, "_status_checker", None)
        for node in nodes:
            if checker is not None:
                self._apply_node_freshness(node)
            self._apply_node_info_freshness(node)
        # v1.5.4 (ROADMAP task 2): a datum that has just grown STALE is a NEW problem —
        # the chip re-counts and, while the lens is on, the dimming follows (nothing else
        # is touched: a lens is a view, and the counters keep their totals).
        try:
            self._sync_problems_chip()
            if getattr(self, "_problems_only", False):
                self._apply_map_dimming()
        except (AttributeError, RuntimeError):
            pass  # Qt teardown / a window without the v1.5.4 pieces

    def _apply_node_info_freshness(self, node) -> bool:
        """Give ONE card the age of its collected facts (the data is the source of truth).

        Called by the freshness tick. Returns True when the mark changed. A card without a
        date (0.0 — never collected / an old project file) is left untouched and unmarked.
        """
        try:
            return bool(node.set_info_collected_at(
                getattr(node.data, "info_collected_at", 0.0)))
        except (RuntimeError, AttributeError):
            return False  # Qt teardown / a test double without the v1.5.3 hook

    def _freshness_tick(self):
        """The QTimer slot — never raises (a repaint is cosmetic)."""
        try:
            self._refresh_status_freshness()
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Status freshness tick failed: {e}")

    def _update_window_title(self):
        """Rebuild the window title: base title + project file + [*] marker."""
        # AUDIT v0.8.3 (#1): base — APP_NAME/APP_VERSION from version.py (the single
        # source of truth); the i18n key title.main_window is no longer a version source.
        try:
            from version import APP_NAME, APP_VERSION
        except ImportError:
            from .version import APP_NAME, APP_VERSION
        base = f"{APP_NAME} — v{APP_VERSION}"
        lang_code = (getattr(self, "current_language", "") or "").upper()
        title = f"{base} [{lang_code}]" if lang_code else base
        if self._project_file:
            title += f" — {os.path.basename(self._project_file)}"
        # v1.5rc3 (ROADMAP task 1): the demo map says so. It has no file name, so the
        # marker is what keeps it from being mistaken for a document of the user's; it
        # disappears with the first save (which makes the project their own) or with the
        # next new/open.
        if getattr(self, "_example_project", False):
            title += f" — {self.t('title.example')}"
        if self._dirty:
            title += " [*]"
        self.setWindowTitle(title)
        # v0.9.7: restoring from autosave/backups makes sense only for an
        # opened project file (the methods guard themselves — this is a UX hint).
        for act in (getattr(self, "act_restore_autosave", None),
                    getattr(self, "act_backups", None)):
            if act is not None:
                act.setEnabled(bool(self._project_file))

    def _register_i18n(self, widget, key: str):
        """Remember a widget (QMenu/QAction) and its translation key for re-application."""
        self._menu_i18n.append((widget, key))

    # ── v1.3.2 (ROADMAP v1.3.2): configurable hotkeys — the action registry ──────
    # ui/hotkey_registry.py is the single source of truth for the global shortcuts:
    # no literal "Ctrl+…" lives in this module any more. The methods below only
    # collect the targets and (re)install the effective sequences from config.json.

    def _register_hotkey_target(self, action_id: str, target) -> None:
        """v1.3.2 (task 1): bind a QAction/QShortcut to a registry action_id.

        Several targets per id are allowed and expected: undo/redo exist twice
        (the toolbar button + the Edit menu item) and both must follow the
        configured sequence.
        """
        self._hotkey_targets.setdefault(action_id, []).append(target)

    def _apply_hotkeys(self) -> None:
        """v1.3.2 (task 3): install the configured sequences — at startup and live.

        The source is ``hotkeys`` in ~/.sshmap/config.json (merge-write; a missing /
        broken value → the registry default, an empty string → the hotkey is
        disabled). Called after the UI construction and from
        ``_apply_settings_from_dialog`` — an OK in the settings dialog applies the new
        sequences WITHOUT a restart. Never raises: a broken registry/config must not
        break startup or the settings dialog.

        v1.3.3.3: ``self._hotkey_targets`` holds the MENU/shortcut-owning objects only —
        the toolbar buttons are mirrors marked by ``_mark_toolbar_mirror()`` and carry
        no sequence of their own. Registering both objects left two enabled QActions
        with one sequence, which Qt answers with an "Ambiguous shortcut overload" that
        fires NEITHER (the Ctrl+Shift+S regression found while writing
        tests/test_actions_keyboard.py).
        """
        try:
            try:
                from ui.hotkey_registry import configured_hotkeys, apply_to
            except ImportError:  # flat launch from the project root
                from hotkey_registry import configured_hotkeys, apply_to
            self._hotkey_map = configured_hotkeys()
            apply_to(self._hotkey_targets, self._hotkey_map)
        except Exception as e:  # noqa: BLE001 — the hotkeys must not break the window
            if self.log:
                self.log.warning(f"Apply hotkeys failed: {e}")
        # The dynamic action (multi-input) is owned by its mode: the key exists ONLY
        # while the mode is on (v1.2.3 / v1.2.4-fix rule, v1.3.2 task 4).
        try:
            self._sync_multi_shortcut()
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Apply multi-input hotkey failed: {e}")

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4/5): re-apply the theme to everything this window owns.

        Called by `ui/theme_qss.apply_theme()` (and safe to call directly). The
        window is the only object that can reach all the pieces, so it walks what
        it owns and nothing else:

          * the status-bar styles from the registry (they are QSS strings, and a
            QSS string is a value);
          * the MAP — `MapScene.refresh_theme()` repaints the grid/background and
            asks every item that defines the hook (nodes, arrows, notes, groups);
          * the minimap (a child of the view, but owned by the window) — its
            cached colour layer has to be rebuilt;
          * the terminal CONTAINERS and their sessions (status labels, the SFTP
            tabs, the find bars) through the same registry walk the language
            switch uses.

        The QPalette and the application-wide QSS are applied by `apply_theme()`
        BEFORE this method is called, so the standard controls already follow.
        Every stage is fault-isolated: a theme switch is cosmetic and must never
        raise out of a half-closed session.
        """
        if theme_qss is not None:
            for widget, key in ((getattr(self, "counts_label", None), "status.bar_counts"),
                                (getattr(self, "zoom_label", None), "status.bar_zoom")):
                if widget is not None:
                    theme_qss.refresh(widget, key)
        # v1.5rc3 (ROADMAP task 2): the status bar owns the Undo affordance — a QSS
        # string and a text are VALUES, so its own refresh re-applies both.
        try:
            _bar = self.statusBar()
            hook = getattr(_bar, "refresh_theme", None)
            if callable(hook):
                hook()
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed
        # v1.4.5 (ROADMAP task 3): the clickable status counters (their ACTIVE styling
        # is the widget's own state — `refresh_theme()` picks the right registry entry).
        # v1.5.4 (ROADMAP task 2): the "problems only" chip belongs to the same family
        # (its QSS is a VALUE too, and `set_active` only re-applies it on a real change).
        for counter in list((getattr(self, "status_filter_labels", {}) or {}).values()) \
                + [getattr(self, "problems_chip", None)]:
            if counter is None:
                continue
            try:
                counter.refresh_theme()
            except RuntimeError:
                continue  # Qt teardown — this counter is already destroyed
        self._refresh_icons()
        try:
            self._multi_label.setStyleSheet(
                f"color: {theme.SELECTION_AMBER}; font-weight: bold;")
        except (AttributeError, RuntimeError):
            pass
        scene = getattr(self, "scene", None)
        if scene is not None:
            try:
                scene.refresh_theme()
            except Exception as e:  # noqa: BLE001 — the map must not break the switch
                if self.log:
                    self.log.warning(f"Theme: the scene refresh failed: {e}")
        view = getattr(self, "view", None)
        if view is not None:
            try:
                view.refresh_theme()
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log.warning(f"Theme: the view refresh failed: {e}")
        mini = getattr(self, "minimap", None)
        if mini is not None:
            try:
                mini.refresh_theme()
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log.warning(f"Theme: the minimap refresh failed: {e}")
        # The terminal containers (windows mode: the sessions; tabs mode: the dock) —
        # the SAME walk as _apply_ui_translations, for the same reason (a session may
        # be torn down under the switch).
        for session in list(getattr(self, "_terminal_windows", None) or ()):
            try:
                host = getattr(session, "_host_window", None) or session
                hook = getattr(host, "refresh_theme", None)
                if callable(hook):
                    hook()
            except RuntimeError:
                continue  # Qt teardown — this session is gone
            except Exception:  # noqa: BLE001 — one container must not stop the rest
                continue
        dock = getattr(self, "_terminals_dock", None)
        if dock is not None:
            try:
                hook = getattr(dock, "refresh_theme", None)
                if callable(hook):
                    hook()
            except RuntimeError:
                pass
            except Exception:  # noqa: BLE001
                pass
        # The floating panels are children of the view but owned here: the map search
        # bar (v0.9.8), the minimap (v1.4.2), the legend (v1.4.5) and the first-run
        # empty state (v1.4.5) — all repaint from the live theme.
        for widget in (getattr(self, "map_search", None), getattr(self, "legend", None),
                       getattr(self, "empty_state", None),
                       getattr(self, "filter_plaque", None)):
            hook = getattr(widget, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass  # Qt teardown — the panel is already destroyed
                except Exception:  # noqa: BLE001
                    pass

    # ── v1.4.3 (ROADMAP task 6): the theme of the settings hub ────────────────────

    def apply_theme(self, instance=None):
        """Make `instance` (or the saved theme) ACTIVE and repaint the application.

        The one entry point of a theme switch: the settings dialog calls it after
        its OK (through `_apply_settings_from_dialog`) and `main.py` calls it with
        the theme the config holds, BEFORE the window is built, so nothing is ever
        constructed with the wrong palette.
        """
        if theme_qss is not None:
            theme_qss.apply_theme(instance if instance is not None else theme.THEME)
        elif instance is not None:
            theme.set_theme(instance)
        return theme.THEME

    # ── v1.5rc1 (ROADMAP task 6): "Auto (system)" follows the platform live ──────

    def _install_color_scheme_watch(self) -> bool:
        """Listen to the platform's colour scheme (v1.5rc1) — True when installed.

        The "Auto" mode is not a snapshot: Qt reports a change of the OS theme
        through `QStyleHints.colorSchemeChanged`, and a window in `auto` must
        follow it without a restart. Installed once per window (the flag makes it
        idempotent) and never fatal — a platform without the hint keeps the mode
        the config resolved at startup, which is the pre-v1.5rc1 behaviour.
        """
        if getattr(self, "_color_scheme_hints", None) is not None:
            return False
        try:
            from PySide6.QtGui import QGuiApplication
            hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
            if hints is None:
                return False
            hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
            self._color_scheme_hints = hints
            return True
        except Exception as e:  # noqa: BLE001 — the hint is optional
            if getattr(self, "log", None):
                self.log.debug(f"Auto theme: no colorScheme hint ({e})")
            return False

    def _theme_mode_from_config(self) -> str:
        """The stored `theme.mode` (v1.5rc1) — DARK when the config cannot be read."""
        try:
            from ui.settings_dialog import load_theme_settings
        except ImportError:  # flat launch from the project root
            try:
                from settings_dialog import load_theme_settings
            except ImportError:
                return theme.MODE_DARK
        try:
            return load_theme_settings().get("mode") or theme.MODE_DARK
        except Exception:  # noqa: BLE001 — a broken config must not break the window
            return theme.MODE_DARK

    def _on_system_color_scheme_changed(self, *_args):
        """The OS flipped dark↔light: only an `auto` window follows it (v1.5rc1).

        Deliberately narrow: it re-reads the theme key and re-applies the THEME
        (not `_apply_settings_from_dialog`, which would re-apply every setting for
        a change that is about one colour).
        """
        if self._theme_mode_from_config() != theme.MODE_AUTO:
            return  # an explicit dark/light choice is the user's, not the platform's
        try:
            from ui.settings_dialog import load_theme_settings, theme_from_settings
        except ImportError:  # flat launch from the project root
            try:
                from settings_dialog import load_theme_settings, theme_from_settings
            except ImportError:
                return
        try:
            self.apply_theme(theme_from_settings(load_theme_settings()))
        except Exception as e:  # noqa: BLE001 — a cosmetic follow must never break
            if getattr(self, "log", None):
                self.log.warning(f"Auto theme: the follow-up apply failed: {e}")

    def _refresh_icons(self):
        """v1.4.3-fix: re-paint the vector icons in the ACTIVE theme's colour.

        A QIcon handed to a QAction/QPushButton keeps the pixels it was painted
        with, and nothing repaints it when the theme changes — the toolbar, the
        menus, the sidebar buttons and the palette showed dark-theme pale glyphs
        on LIGHT (reported after v1.4.3 shipped).

        `ui/icons.py` keeps ONE QIcon object per name (implicitly shared), so
        `refresh_all()` re-paints them IN PLACE and every widget already holding
        one shows the new pixmap; the QActions are then re-set for the widgets
        that cache a QIcon per action. The two "◇" diamonds draw a fresh pixmap
        (they are window-internal, not in the registry) and are re-applied here.
        Never raises: a broken icon must not break a theme switch.
        """
        count = 0
        try:
            if _icons_mod is not None:
                count = _icons_mod.refresh_all()
            for action in self.findChildren(QAction):
                if refresh_action_icon(action):
                    count += 1
        except RuntimeError:
            pass  # Qt teardown — an action of a closing window is already destroyed
        except Exception as e:  # noqa: BLE001 — cosmetic
            if self.log:
                self.log.warning(f"Theme: the icon refresh failed: {e}")
        # The sidebar's six action buttons hold their own copy of the pixmap.
        sidebar = getattr(self, "sidebar", None)
        hook = getattr(sidebar, "refresh_theme", None)
        if callable(hook):
            try:
                hook()
            except RuntimeError:
                pass  # Qt teardown
            except Exception as e:  # noqa: BLE001 — cosmetic
                if self.log:
                    self.log.warning(f"Theme: the sidebar icon refresh failed: {e}")
        # The two hand-drawn diamonds (the collapse buttons of both panels).
        for btn in (getattr(getattr(self, "sidebar", None), "collapse_btn", None),
                    getattr(self, "_map_collapse_btn", None)):
            if btn is None:
                continue
            try:
                btn.setIcon(_diamond_icon())
                # v1.5.6 (ROADMAP task 4): the FRAME is a QSS VALUE of the same kind —
                # the `collapse.button` entry is re-applied with the icon ink.
                self._style_collapse_btn(btn)
            except RuntimeError:
                continue  # Qt teardown
        # The command palette builds its rows on open — re-theme the OPEN one.
        palette = getattr(self, "_command_palette", None)
        if palette is not None:
            hook = getattr(palette, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass
        return count

    def _apply_ui_translations(self):
        """Translate the menus, toolbar, and service labels to the current language.

        v1.3.3.1 (ROADMAP task 1): every stage is individually fault-isolated. The
        re-text is a CROSS-CUTTING walk over widgets that may die at any moment (a
        terminal window closing mid-switch, a torn-down container) — before, one
        broken widget aborted the whole method, so the terminal containers stayed in
        the previous language. A re-text is cosmetic: it must never break the switch.
        """
        for widget, key in self._menu_i18n:
            if widget is None:
                continue
            try:
                if isinstance(widget, QMenu):
                    widget.setTitle(self.t(key))
                else:
                    widget.setText(self.t(key))
            except RuntimeError:
                pass  # Qt teardown — one menu/action is already destroyed
        # v1.5rc4 (ROADMAP task 2): the toolbar's "»" overflow button keeps its glyph and
        # only its TOOLTIP is translated (it is not in `_menu_i18n`, which re-texts).
        if self._i18n_available:
            for _widget in (getattr(self, "_toolbar_overflow_action", None),
                            getattr(self, "_toolbar_overflow_btn", None)):
                if _widget is None:
                    continue
                try:
                    _widget.setToolTip(self.t("toolbar.more"))
                except RuntimeError:
                    pass  # Qt teardown — the action/button is already destroyed
        # v0.9.9.4: sidebar strings (buttons, title, placeholder, "All tags") —
        # the panel registry; retranslate via the i18n callback (regression on the v0.9.2 bug:
        # these strings were not updated on language switch before).
        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.2.2: the "Terminals" dock may have been created before the language switch — translate its title
        dock = getattr(self, "_terminals_dock", None)
        if dock is not None:
            try:
                dock.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the dock is already destroyed
            except AttributeError:
                try:
                    dock.setWindowTitle(self.t("terminal.dock_title"))
                except RuntimeError:
                    pass  # Qt teardown — the dock is already destroyed
        # v1.3.3.1 (ROADMAP task 1): the terminal CONTAINERS follow the language too.
        # The twin of the terminal-font loop in _apply_settings_from_dialog — same
        # registry, same dead-C++-object discipline: a session that is being torn
        # down must not break the switch. The registry stores SESSIONS (pages) in
        # windows mode and the DOCK in tabs mode; both own retranslate(), and both
        # re-text their own children — so nothing is missed either way. A page also
        # points at its host window (page._host_window — the v1.2.1 contract), and
        # the HOST owns the pieces the page cannot reach: the WINDOW TITLE and the
        # tabs' close tooltips — so the host is re-texted as well (both calls are
        # idempotent, the overlap costs nothing). The module translator cache
        # (_t_cache) is deliberately NOT invalidated: the cached lambda calls i18n.t()
        # at call time, and t() reads the current language on every call — so a
        # re-text picks the new language up.
        for _session in list(getattr(self, "_terminal_windows", [])):
            try:
                _session.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the session/dock content is already destroyed
            except AttributeError:
                pass  # a session object without retranslate() (a test double) — skip it
            except Exception:  # noqa: BLE001 — one container must not abort the re-text
                if self.log:
                    self.log.warning("retranslate failed for a terminal session", exc_info=True)
            _host = getattr(_session, "_host_window", None)
            if _host is None or _host is dock:
                continue  # no host / the dock was already re-texted above
            try:
                _host.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the host window is already destroyed
            except AttributeError:
                pass  # a host without retranslate() (a test double) — skip it
            except Exception:  # noqa: BLE001 — one window must not abort the re-text
                if self.log:
                    self.log.warning("retranslate failed for a terminal window", exc_info=True)
        # v1.2.3: multi-input plaque — the exit button tooltip in the new language
        _multi_btn = getattr(self, "_multi_exit_btn", None)
        if _multi_btn is not None:
            try:
                _multi_btn.setToolTip(self.t("terminal.multi_exit_button"))
            except RuntimeError:
                pass  # Qt teardown — the plaque is already destroyed
        # v1.2.4.1: tooltips of the corner collapse buttons and the collapsed-panel strips
        _sb_panel = getattr(self, "sidebar", None)
        if _sb_panel is not None:
            try:
                _sb_panel.collapse_btn.setToolTip(self.t("view.toggle_sidebar"))
            except (RuntimeError, AttributeError):
                pass  # Qt teardown / a panel without the button — the tooltip is not critical
        for _widget, _key in ((getattr(self, "_map_collapse_btn", None), "view.toggle_map"),
                              (getattr(self, "_sidebar_strip", None), "view.strip_sidebar_tooltip"),
                              (getattr(self, "_map_strip", None), "view.strip_map_tooltip"),
                              (getattr(self, "legend", None), "legend.tooltip")):
            if _widget is not None:
                try:
                    _widget.setToolTip(self.t(_key))
                except RuntimeError:
                    pass  # Qt teardown — the widget is already destroyed
        # v1.5rc3 (ROADMAP task 2): the Undo button of the status bar is re-texted by its
        # own refresh (it also re-applies the registry QSS — the v1.4.3 rule).
        try:
            _bar = self.statusBar()
            _hook = getattr(_bar, "refresh_theme", None)
            if callable(_hook):
                _hook()
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed
        # v1.4.5 (ROADMAP task 4): the legend paints its rows from a label cache.
        _legend = getattr(self, "legend", None)
        if _legend is not None:
            try:
                _legend.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.5.4 (ROADMAP task 3): the active-filter plaque — it BUILDS its captions from
        # the live filter state, so a re-text is one call (the values never move).
        _plaque = getattr(self, "filter_plaque", None)
        if _plaque is not None:
            try:
                _plaque.retranslate()
                self._position_filter_plaque()  # the captions changed width — re-place it
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.5.2 (ROADMAP task 3): the activity panel — the CHROME only (its title, the
        # level captions, the column headers, Clear). The event LINES are logging lines
        # and stay English: one key per event kind would be an i18n cost with no reader.
        _activity = getattr(self, "activity_panel", None)
        if _activity is not None:
            try:
                _activity.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        # v1.4.5 (ROADMAP task 2): the first-run hint (its button text + the paint).
        _empty = getattr(self, "empty_state", None)
        if _empty is not None:
            try:
                _empty.retranslate()
                self._position_empty_state()   # the sentence changed width — re-place it
            except RuntimeError:
                pass  # Qt teardown — the hint is already destroyed
        # v1.4.5 (ROADMAP task 3): the counters (their labels + tooltips) and, with them,
        # the empty state / the status markers of the composition.
        try:
            self._update_counts_label()
        except RuntimeError:
            pass  # Qt teardown — the status bar is already gone
        # v1.4.5 (ROADMAP task 5): the divider's tooltip.
        try:
            _handle = self._splitter.handle(0)
            if _handle is not None:
                _handle.setToolTip(self.t("view.splitter_handle_tooltip"))
        except (AttributeError, RuntimeError):
            pass  # Qt teardown / a splitter without handles
        try:
            self.statusBar().showMessage(self.t("status.ready"))
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed

    @property
    def log(self):
        """Lazy-imported logger."""
        if self._log is None:
            try:
                from modules.logger import get_logger as _get
                self._log = _get(__name__)
            except Exception:
                pass
        return self._log

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # v1.5rc3 (ROADMAP task 2): the window's status bar is installed BEFORE anything
        # can post a message to it — the Undo affordance is a property of that bar (it
        # consumes the first message after `_push_command()` armed it), so every later
        # `self.statusBar()` call reaches the subclass. The callback is the window's own
        # undo; the bar itself knows nothing about the stack.
        if UndoStatusBar is not None:
            try:
                _bar = UndoStatusBar(self)
                _bar.set_undo_callback(self._undo)
                self.setStatusBar(_bar)
            except Exception as e:  # noqa: BLE001 — a status bar must not break startup
                if self.log:
                    self.log.warning(f"Undo status bar unavailable: {e}")

        # v1.3.3.6 (ROADMAP task 2): the window accepts a dropped project file
        # (dragEnterEvent/dragMoveEvent/dropEvent below). Until now only the SFTP tab
        # had this — dragging a .json onto the window did nothing at all.
        self.setAcceptDrops(True)

        # v1.2.4.1: self._splitter — a facade reference (panel collapse mechanics).
        # Splitter children are CONTAINERS [panel | strip], not the widgets themselves: in
        # the collapsed state the real widget is hidden (0px, native Qt), and in its
        # place — a clickable ~18px strip (_CollapseStrip). The handle cannot be dragged
        # to zero (setCollapsible(False) + the container's minimumWidth) — a panel cannot
        # be "lost"; state is driven by buttons/menus (ROADMAP v1.2.4.1, task 6).
        splitter = QSplitter(Qt.Horizontal)
        self._splitter = splitter
        layout.addWidget(splitter)

        # Side panel — v0.9.9.4: the sidebar cluster (buttons, title, search,
        # tag filter, tree with status markers, context menu) is moved to
        # ui/sidebar.py (SidebarPanel). MainWindow remains a facade: self.tree /
        # self.tag_filter / self.search_edit / self.btn_* — references to the
        # panel's widgets; the public API and all window slots are unchanged.
        self.sidebar = SidebarPanel(
            translate_fn=self.t if self._i18n_available else None,
            actions={
                # Row context menu (ROADMAP v0.9.6): "select first,
                # then act" — as in the original _on_sidebar_context_menu closures.
                "ssh": lambda n: (self._select_node(n), self._connect_ssh_to_selected()),
                "external": lambda n: (self._select_node(n), self._connect_ssh_external(n)),
                "edit": lambda n: self._edit_node(n),
                "copy_ip": lambda n: self._copy_node_info(n, "ip"),
                "copy_hostname": lambda n: self._copy_node_info(n, "hostname"),
                "ping": lambda n: self._ping_node(n),
                # v1.5.3 (ROADMAP task 2): "Gather information" — the row's node, or the
                # whole selection when several rows are selected (the batch path).
                "collect_info": lambda n: self._collect_info_many(node=n),
                # v1.3.3.3 (task 5): one round for the selection (the row's node when
                # nothing is selected) — the map's context menu calls the same method.
                "check_status": lambda n: self._check_statuses_now(n),
                # v1.5.3 (task 3): the reachability report of the row's node.
                "diagnose": lambda n: self._diagnose_node(n),
                "reveal": lambda n: self._reveal_node_on_map(n),
                "delete": lambda n: self._remove_node_guarded(n),
                # v1.0RC4: Quick launch — a submenu as the first item (above SSH);
                # keys are optional (outside CONTEXT_MENU_ITEMS) — see SidebarPanel.
                "ql_entry": lambda n, e: self._run_quick_launch_entry(n, e),
                "ql_configure": lambda n: self._open_quick_launch_dialog(n),
            },
            show_title=self._i18n_available,  # before, the label was created only with i18n
        )

        # Facade references to the panel widgets (MainWindow public API — tests)
        self.tree = self.sidebar.tree
        self.tag_filter = self.sidebar.tag_filter
        self.search_edit = self.sidebar.search_edit
        self.btn_add = self.sidebar.btn_add
        self.btn_connect = self.sidebar.btn_connect
        self.btn_connect_ssh = self.sidebar.btn_connect_ssh
        self.btn_props = self.sidebar.btn_props
        self.btn_delete = self.sidebar.btn_delete
        self.btn_settings = self.sidebar.btn_settings  # v1.1: the ⚙ "Settings" button (the 6th)
        self._sidebar_title = self.sidebar.title_label  # None without i18n (as before)

        # Panel events — window slots (the same as before v0.9.9.4)
        self.search_edit.textChanged.connect(self.refresh_sidebar)
        self.tag_filter.currentIndexChanged.connect(self._on_tag_filter_changed)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_click)
        # v0.9.6: server tree context menu (right-click on a sidebar row);
        # the panel itself sets the CustomContextMenu policy at construction.
        self.tree.customContextMenuRequested.connect(self._on_sidebar_context_menu)

        # Panel buttons -> window slots
        self.sidebar.add_server_clicked.connect(self._add_server)
        self.sidebar.add_connection_clicked.connect(self._add_connection)
        self.sidebar.connect_ssh_clicked.connect(self._connect_ssh_to_selected)
        self.sidebar.show_properties_clicked.connect(self._show_properties)
        self.sidebar.delete_selected_clicked.connect(self._delete_selected)
        # v1.1: the ⚙ "Settings" button at the bottom of the sidebar -> the settings dialog (hub)
        self.sidebar.settings_clicked.connect(self._open_settings_dialog)

        # v1.2.4.1 (task 1): the sidebar container [sidebar | strip]. The strip — at
        # the right edge (splitter-handle side); hidden in the expanded state.
        self._sidebar_container = QWidget()
        _sb_lay = QHBoxLayout(self._sidebar_container)
        _sb_lay.setContentsMargins(0, 0, 0, 0)
        _sb_lay.setSpacing(0)
        self._sidebar_strip = _CollapseStrip()
        _sb_lay.addWidget(self.sidebar)
        _sb_lay.addWidget(self._sidebar_strip)
        self._sidebar_strip.hide()
        splitter.addWidget(self._sidebar_container)

        # Map canvas
        self.scene = MapScene()
        # v0.9.9.1: reentry guard for selection sync (instead of blockSignals — see _select_node)
        self._selection_syncing = False
        self.scene.selectionChanged.connect(self._sync_selection_state)
        # v1.4.4 (ROADMAP task 4): the scene reports the hover focus of an ARROW; the
        # window stays the ONE owner of the resulting dim (`_apply_map_dimming`).
        self.scene.hover_focus_changed.connect(self._on_hover_focus_changed)
        self.view = MapView(self.scene, self)

        # v0.8.3: undo stack — dirty by index, refresh after undo/redo
        self.undo_stack.indexChanged.connect(lambda *_a: self._on_stack_changed())
        self.undo_stack.cleanChanged.connect(lambda *_a: self._on_stack_changed())
        # Node movement: MapView reports the finished gesture -> a MoveNode command
        try:
            self.view.node_drag_committed.connect(self._commit_node_move)
            self.view.nodes_drag_committed.connect(self._commit_nodes_move)  # v0.9.3
        except Exception:  # noqa: BLE001 — without the signal the move simply won't reach undo
            pass

        # Mouse event filter for double-click on nodes
        self.view.viewport().installEventFilter(self)

        # v0.7: drag mode for creating a connection (Shift+drag a node) — a status-bar hint
        self.view.connect_drag_started.connect(
            lambda: self.statusBar().showMessage(self.t("hint.connect_drag")))
        self.view.connect_drag_finished.connect(
            lambda: self.statusBar().showMessage(self.t("status.ready")))

        # v1.2.4.1 (task 1): the map container [strip | view]. The strip — at the left
        # edge (splitter-handle side: target state [sidebar | map-strip]);
        # hidden in the expanded state. The "Terminals" dock — the window's QDockWidget,
        # unrelated to the splitter mechanics (assembled natively).
        self._map_container = QWidget()
        _mp_lay = QHBoxLayout(self._map_container)
        _mp_lay.setContentsMargins(0, 0, 0, 0)
        _mp_lay.setSpacing(0)
        self._map_strip = _CollapseStrip()
        _mp_lay.addWidget(self._map_strip)
        _mp_lay.addWidget(self.view)
        self._map_strip.hide()
        splitter.addWidget(self._map_container)
        splitter.setSizes([250, 950])

        # v1.2.4.1 (task 6): the handle cannot be dragged to zero manually — the
        # collapsed state is driven by buttons/menus; the containers' minimumWidth is
        # the lower bound of manual dragging (a collapsed container shrinks to 18px in _set_panel_collapsed).
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.SIDEBAR_MIN_WIDTH = 160
        self.MAP_MIN_WIDTH = 240
        # v1.5rc4 (ROADMAP tasks 1/2): the WINDOW's own floor. The status bar's totals
        # sentence made the layout ask for ~818 px, i.e. the CHROME dictated how narrow the
        # window could be — and an overflow policy for a bar that can never get narrow is
        # decoration. The explicit floor is what the policies work against: below
        # `MIN_WINDOW_WIDTH` nothing is squeezed any further (the chrome has already given
        # up its passive half by then), and the sidebar/map minimums still hold.
        self.MIN_WINDOW_WIDTH = 480
        self.setMinimumWidth(self.MIN_WINDOW_WIDTH)
        self._sidebar_container.setMinimumWidth(self.SIDEBAR_MIN_WIDTH)
        self._map_container.setMinimumWidth(self.MAP_MIN_WIDTH)

        # v1.2.4.1 (task 2): the map collapse corner button — an overlay QToolButton
        # on the MapView (the map_search pattern: a child of view, outside the layout),
        # repositioned on resizeEvent via the MapView.resized signal. The SIDEBAR
        # collapse button lives in the SidebarPanel's bottom row (self.sidebar.collapse_btn);
        # icon/tooltip/wiring — in _setup_menubar (after the QAction is created).
        self._map_collapse_btn = QToolButton(self.view)
        self._map_collapse_btn.setToolTip("Map")  # fallback without i18n
        self._style_collapse_btn(self._map_collapse_btn)   # v1.5.6: the button FRAME
        self.view.resized.connect(self._position_map_collapse_btn)
        # v1.5.6: the corner is the VIEWPORT's, and a scrollbar that appears or disappears
        # resizes it without resizing the view — so the placement follows the two ranges too.
        for _bar in (self.view.verticalScrollBar(), self.view.horizontalScrollBar()):
            _bar.rangeChanged.connect(lambda *_a: self._position_map_collapse_btn())
        self._position_map_collapse_btn()

        # v0.9.8: map search (Ctrl+F) — a floating bar over the canvas
        self._setup_map_search()

        # v1.4.2 (ROADMAP task 2): the minimap — a floating panel in the top-right corner
        self._setup_minimap()

        # v1.4.5 (ROADMAP task 2): the first-run empty state — a hint over the canvas
        # while the map has no servers (the card is mouse-transparent; the ONE button is
        # its own child of the view).
        self._setup_empty_state()

        # v1.4.5 (ROADMAP task 4): the legend — the 6 connection types + the 3 statuses.
        # Created BEFORE _setup_menubar (which owns the checkable View item and the
        # toolbar mirror): the panel is built here, its visibility/config applied here,
        # and the menu item simply joins the same state.
        self._setup_legend()

        # v1.5.4 (ROADMAP task 3): the active-filter plaque — the panel that NAMES the
        # filters which dim the map (the v1.4.5 panel pattern: a child of the view, out of
        # the exports). Created after the legend, because it yields its corner to no one
        # and simply joins the floating-panel priority resolver below.
        self._setup_filter_plaque()

        # Status bar
        if self._i18n_available:
            try:
                from i18n import t as __t
                self.statusBar().showMessage(__t("status.ready"))
            except Exception:
                pass
        else:
            self.statusBar().showMessage("Ready. Double-click for node properties.")

        # UI polish: permanent indicators on the right of the status bar — node/
        # connection/status counters and the zoom percentage (updated from MapView.zoomChanged).
        self.counts_label = QLabel("")
        # v1.5rc4 (ROADMAP task 1): the totals sentence is ~346 px and a QLabel's
        # `minimumSizeHint()` IS its size hint, so on its own it asks the bar for a very
        # wide window. An explicit 0 minimum lets the BAR shrink (the appended text is
        # then clipped rather than the bar refusing the size) — and the overflow policy
        # hides the label in exactly that band, so the clipped state is never on screen.
        self.counts_label.setMinimumWidth(0)
        # v1.4.3 (ROADMAP task 4): the status-bar styles come from the ONE QSS
        # registry (ui/theme_qss.py) and are re-applied by apply_theme()
        theme_qss.refresh(self.counts_label, "status.bar_counts")
        self.statusBar().addPermanentWidget(self.counts_label)

        # v1.4.5 (ROADMAP task 3): the status counters are LIVE — a click filters the
        # sidebar by that status, a second click resets it. The state is transient UI
        # (never persisted) and the counters always show the TOTALS: a filter is a view,
        # not a fact. The servers/connections pair stays in `counts_label` above.
        self._status_filter = ""            # "" | "online" | "warn" | "offline"
        self.status_filter_labels = {}      # status -> _StatusCounter
        for _status in STATUS_FILTER_ORDER:
            _counter = _StatusCounter(_status, self)
            _counter.clicked.connect(self._on_status_filter_clicked)
            _counter.refresh_theme()
            self.statusBar().addPermanentWidget(_counter)
            self.status_filter_labels[_status] = _counter

        # v1.5.4 (ROADMAP task 2): the "problems only" lens — ONE transient toggle beside
        # the status counters whose click DIMS everything that is not warn/offline/stale.
        # It is UI state (memory only, never a config key) and it never changes the
        # counters: a lens is a view, not a fact.
        self._problems_only = False
        self.problems_chip = _ProblemsChip(self)
        self.problems_chip.clicked.connect(self._on_problems_chip_clicked)
        self.problems_chip.refresh_theme()
        self.statusBar().addPermanentWidget(self.problems_chip)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        theme_qss.refresh(self.zoom_label, "status.bar_zoom")
        self.statusBar().addPermanentWidget(self.zoom_label)

        # v1.2.3 (ROADMAP task 3): the multi-input mode plaque "MULTI: N sessions" +
        # an exit button — a permanent widget on the right of the status bar; hidden
        # while the mode is off (_on_multi_changed/_multi_refresh_ui control visibility).
        self._multi_plaque = QWidget()
        _multi_row = QHBoxLayout(self._multi_plaque)
        _multi_row.setContentsMargins(8, 0, 4, 0)
        _multi_row.setSpacing(6)
        self._multi_label = QLabel("")
        self._multi_label.setStyleSheet(
            f"color: {theme.SELECTION_AMBER}; font-weight: bold;")
        self._multi_exit_btn = QToolButton()
        self._multi_exit_btn.setText("✕")
        self._multi_exit_btn.setToolTip(self.t("terminal.multi_exit_button"))
        # Exit button — NOT Esc (Esc goes to the shell as \x1b!): an explicit False.
        self._multi_exit_btn.clicked.connect(lambda: self._toggle_multi_input(False))
        _multi_row.addWidget(self._multi_label)
        _multi_row.addWidget(self._multi_exit_btn)
        self._multi_plaque.setVisible(False)
        self.statusBar().addPermanentWidget(self._multi_plaque)

        try:
            self.view.zoomChanged.connect(self._on_zoom_changed)
        except Exception:  # noqa: BLE001 — without the signal the status bar simply won't update
            pass
        self._update_counts_label()

        # v1.5rc4 (ROADMAP tasks 1/2/7): the chrome policies get their first pass HERE —
        # the widgets exist, the panels are placed and the saved visibility is applied, so
        # a window opened at a narrow width already shows the compact toolbar and status
        # bar and resolves the floating panels (every resize does the same from now on).
        self._sync_toolbar_overflow()
        self._sync_status_bar_overflow()
        self._sync_overlay_priority()

        if self.log:
            self.log.info("MainWindow UI initialized")

    # ── Unsaved changes tracking ─────────────────────
    
    def _mark_dirty(self):
        """Mark project as having unsaved changes."""
        self._dirty = True
        self._update_window_title()

    # ── v0.8.3: Undo/Redo ─────────────────────────────────────────

    def _push_command(self, command):
        """Single entry point: push a command onto the stack (redo runs itself).

        v1.5rc3 (ROADMAP task 2): this is ALSO the one place that offers an "Undo"
        back. The stack is the only thing that knows a command really landed, so the
        decision lives here and nowhere else: a DESTRUCTIVE change (a command whose
        `offers_undo()` is true — a removed node/connection/note, a detached note, a
        bulk import) arms the status-bar affordance, and the action's own message —
        which its caller shows a moment later — carries the button. Work that is NOT
        on the stack (the terminal, the SFTP tab, a view state, the background image)
        can never offer an Undo, because no command is pushed for it at all.
        """
        try:
            self.undo_stack.push(command)
        except Exception as e:
            if self.log:
                self.log.warning(f"undo push failed: {e}")
            return
        try:
            offers = getattr(command, "offers_undo", None)
            if callable(offers) and offers():
                arm = getattr(self.statusBar(), "arm_undo", None)
                if callable(arm):
                    arm()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a plain QStatusBar — the offer is a convenience

    def _commit_node_move(self, node, old_pos, new_pos):
        """v0.8.3: a node drag gesture finished -> a CmdMoveNode command."""
        from modules.undo_commands import CmdMoveNode
        self._push_command(CmdMoveNode(self, node, old_pos, new_pos))
        self._mark_dirty()

    def _commit_nodes_move(self, moves):
        """v0.9.3: a group drag finished -> ONE CmdMoveNodes command."""
        from modules.undo_commands import CmdMoveNodes
        if not moves:
            return
        self._push_command(CmdMoveNodes(self, moves))
        self._mark_dirty()

    def _on_stack_changed(self):
        """QUndoStack.indexChanged/canUndoChanged -> recompute the dirty marker."""
        try:
            self._dirty = self.undo_stack.canUndo() or self._undo_baseline_dirty
        except RuntimeError:
            # Qt teardown: the stack's C++ object is destroyed with the window (the
            # _sync_selection_state pattern) — no one left to update the title, and no need.
            return
        self._update_window_title()

    def _post_undo_refresh(self):
        """Sync the UI with the scene's actual state (after undo/redo)."""
        try:
            self.refresh_sidebar()
        except Exception:
            pass
        try:
            self._update_counts_label()
        except Exception:
            pass
        try:
            self._sync_status_targets()
        except Exception:
            pass

    def _undo(self):
        try:
            self.undo_stack.undo()
            self.statusBar().showMessage(
                self.t("status.undone", action=self.undo_stack.text(self.undo_stack.index()))
                if self._i18n_available else "Undo.")
        except Exception as e:
            if self.log:
                self.log.warning(f"undo failed: {e}")

    def _redo(self):
        try:
            self.undo_stack.redo()
            self.statusBar().showMessage(
                self.t("status.redone") if self._i18n_available else "Redo.")
        except Exception as e:
            if self.log:
                self.log.warning(f"redo failed: {e}")

    def _reset_undo_stack(self):
        """Reset the stack and the baseline (new/open/save/load)."""
        self.undo_stack.clear()
        self._note_committed.clear()
        for note in self.scene.notes():
            self._note_committed[note.note_id] = note.text()
        self._undo_baseline_dirty = False
        # v1.5rc3 (ROADMAP task 2): the stack this offer pointed at is gone (a save, a
        # load, a new project) — a visible "Undo" button must not survive it.
        try:
            drop = getattr(self.statusBar(), "clear_offer", None)
            if callable(drop):
                drop()
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a plain QStatusBar

    def _attach_note(self, note):
        """Wire the note's signals (undo text + dirty) — the creation and undo/redo paths."""
        self._connect_note_signals(note)
        self._note_committed[note.note_id] = note.text()

    def _commit_note_text(self):
        """Debounce a note text edit -> a CmdEditTextNote command."""
        pending = self._note_edit_pending
        self._note_edit_pending = None
        if not pending:
            return
        note, old_text = pending
        try:
            new_text = note.text()
        except RuntimeError:
            return
        committed = self._note_committed.get(note.note_id)
        if new_text == old_text or (committed is not None and new_text == committed):
            return  # nothing changed / already committed by a previous command
        from modules.undo_commands import CmdEditTextNote
        self._note_committed[note.note_id] = new_text
        self._push_command(CmdEditTextNote(self, note, committed if committed is not None else old_text, new_text))

    def closeEvent(self, event):
        """Ask to save on exit if there are unsaved changes."""
        # v1.3.3.1 (ROADMAP task 6): flush the pending note-text debounce BEFORE the
        # "unsaved changes" question and before the autosave timer stops. Otherwise a
        # note typed in the last 600 ms is not yet in the undo stack: the question
        # would be asked on a stale dirty state, and on "Discard" the debounce timer
        # could still fire into a window that is going away.
        try:
            self._commit_note_text()
        except Exception:  # noqa: BLE001 — the flush must not block the close
            pass

        # v1.1.2RC3 (AUDIT U2): save the window size/state BEFORE everything — even on
        # a cancelled close (event.ignore) the written values equal the current ones, and on
        # a normal exit the next start reads them (ui_window_geometry_main).
        try:
            save_window_geometry("ui_window_geometry_main", self)
        except Exception:  # noqa: BLE001 — geometry must not block closing
            pass

        # v1.3.3.6 (ROADMAP task 4): the panel widths — written right next to the
        # geometry and with the same "before everything" rule. `saveState()` covers the
        # dock/toolbar layout only, so the [sidebar | map] divider used to reset to
        # 250/950 on every start (ui_splitter_state).
        try:
            save_splitter_state("ui_splitter_state", getattr(self, "_splitter", None))
        except Exception:  # noqa: BLE001 — the widths must not block closing
            pass

        # v0.9.7: autosave stops BEFORE the dialog — while the user decides
        # (Save/Discard/Cancel) no writes to ~/.sshmap/autosave are needed.
        try:
            self._autosave_timer.stop()
        except Exception:  # noqa: BLE001 — teardown robustness (C++ object RuntimeError)
            pass

        # v0.9.4-fix: stopping background QThreads happens on ANY exit.
        # The call used to stand only at the end of a "clean" exit: all three dialog
        # branches returned early before shutdown, so with unsaved
        # changes (the most common case) the running SystemInfoCollector /
        # ping / DNS threads were destroyed with the QObject ->
        # "QThread: Destroyed while thread is still running".
        # Threads are stopped BEFORE the dialog — it may keep the window open
        # indefinitely, and background work is no longer needed at close time.
        self._shutdown_background_threads()

        if self._has_unsaved_changes:
            reply = QMessageBox.question(
                self, 
                self.t("dialog.save_changes") if self._i18n_available else "Save changes?",
                self.t("msg.save_on_exit") if self._i18n_available else "There are unsaved changes. Save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )
            if reply == QMessageBox.Save:
                # Close only if the save really succeeded —
                # otherwise the data would be lost silently (former AUDIT.md, critical #1 — see CHANGELOG.md).
                saved = self._save_project()
                event.accept() if saved else event.ignore()
                return
            elif reply == QMessageBox.Discard:
                event.accept()
                return
            else:
                event.ignore()
                return

        event.accept()

    def _shutdown_background_threads(self):
        """Stop collectors, ping/DNS threads, and terminal sessions.

        The pattern is borrowed from StatusChecker: stop() + a bounded wait() — the GUI
        thread is never blocked more than a couple of seconds per thread.
        """
        # v1.2.3 (ROADMAP v1.2.3): multi-input — the mode is turned off and the provider
        # unhooked BEFORE the sessions' teardown (highlight/plaque reset while
        # the containers are alive; a dangling callable does not hold a dead window).
        try:
            self._multi_shutdown()
        except Exception:  # noqa: BLE001 — multi-input must not block exit
            pass

        threads = []

        # Automatic system-info collection (SystemInfoCollector)
        # v1.5.3 (ROADMAP task 2): the BATCH first — it cancels everything not yet started
        # and waits (bounded) for the collectors it owns; the loop below then waits for the
        # survivors through the same `_info_collectors` registry it always used.
        try:
            self._shutdown_info_batch()
        except Exception:  # noqa: BLE001 — a teardown path never raises
            pass
        for coll in getattr(self, "_info_collectors", {}).values():
            stop = getattr(coll, "stop", None) or getattr(coll, "request_stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
            if hasattr(coll, "isRunning"):
                threads.append(coll)

        # Ping, reverse DNS, and import DNS resolution. v1.2.10rc1 (verification finding):
        # a stop() with a cancel flag exists ONLY on _import_resolve_thread
        # (HostResolverThread.stop, services/host_importer.py — sets an Event, the loop
        # exits between names); PingThread/ReverseDnsThread have NO stop() — the current
        # getaddrinfo/ping runs out its timeout. Threads that outlive the wait budget below
        # are registered in the orphan registry (services/diagnostics.register_orphan_thread).
        # v1.5.3 (ROADMAP task 3): the REACHABILITY reports join the same list — one
        # ReachabilityThread per running report, held in `_diagnose_threads` by server id.
        for attr in ("_ping_thread", "_dns_thread", "_import_resolve_thread"):
            th = getattr(self, attr, None)
            if th is not None and hasattr(th, "isRunning") and th.isRunning():
                stop = getattr(th, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
                threads.append(th)
        for th in list(getattr(self, "_diagnose_threads", {}).values()):
            try:
                if hasattr(th, "isRunning") and th.isRunning():
                    threads.append(th)
            except RuntimeError:
                continue  # the C++ object is already gone — nothing left to wait for

        # Terminal SESSIONS (v1.2: the registry stores pages, not windows): their teardown
        # does thread.stop()+wait() itself via page.shutdown(); here we only wait for
        # the remainder if the window has not been closed by the user yet. v1.2.1: close ALL
        # sessions, not just visible ones — in the tabbed window inactive tabs are "invisible"
        # (QStackedWidget hides them), but their threads must stop.
        terminal_waits = []
        for s in list(getattr(self, "_terminal_windows", [])):
            try:
                # v1.2.10rc1 (manual AUDIT #1): on shutdown the "ask" gate is skipped —
                # the thread is already stopped (stop_thread() inside close_terminal()); there is
                # nothing to decide. Before, with terminal_close_behavior="ask", a QMessageBox.question
                # was shown for each active session on exit, and "Cancel"
                # did not work (the window closed regardless of the answer). The same path as the
                # v1.1.1 limit: _force_close — a confirmed decision, no re-asking.
                s._force_close = True
                s.close_terminal()
                th = getattr(s, "terminal_thread", None)
                if th is not None and hasattr(th, "isRunning") and th.isRunning():
                    terminal_waits.append(th)
            except Exception:
                pass

        total_wait_ms = 2000
        per_thread = max(total_wait_ms // max(len(threads) + len(terminal_waits), 1), 200)
        deadline = __import__("time").monotonic() + total_wait_ms / 1000.0
        for th in threads + terminal_waits:
            remaining = int(max(deadline - __import__("time").monotonic(), 0.05) * 1000)
            try:
                th.wait(min(per_thread, remaining))
            except Exception:
                pass

        # v1.2.10rc1 (verification finding): ping/DNS/import-resolve threads that outlive
        # the wait budget (getaddrinfo/ping with an unreachable resolver) are registered in
        # the orphan registry — a live QThread without a strong referrer must not
        # be left to GC ("QThread: Destroyed while thread is still running" on all
        # exit paths). Terminal threads have their own N4 path (page.shutdown()
        # -> modules/ssh_terminal._orphan_threads) — not duplicated here.
        for th in threads:
            try:
                if hasattr(th, "isRunning") and th.isRunning():
                    from services.diagnostics import register_orphan_thread as _register_orphan
                    _register_orphan(th)
            except Exception:  # noqa: BLE001 — the registry must not block exit
                pass

        # v1.4rc2 (plugin foundation, rc2): the plugin workers. The manager owns them and
        # its shutdown() asks each one to stop, waits with the wait budget and registers
        # whatever outlives it in the orphan registry — a plugin thread must never be
        # destroyed with its parent ("QThread: Destroyed while thread is still running").
        try:
            manager = getattr(self, "_plugin_manager", None)
            shutdown = getattr(manager, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except Exception:  # noqa: BLE001 — a plugin must never block the exit
            pass

    @property
    def _has_unsaved_changes(self) -> bool:
        """Check if current project has unsaved changes."""
        return self._dirty

    def _resolve_server_node(self, item):
        while item is not None:
            if isinstance(item, ServerNode):
                return item
            item = item.parentItem()
        return None

    def eventFilter(self, source, event):
        """Handle double-click on any child element of a node."""
        if source == self.view.viewport() and event.type() == QMouseEvent.MouseButtonDblClick:
            # AUDIT v0.7.2 (medium #9): position() — the modern Qt6 API;
            # pos() is kept as a fallback for legacy bindings.
            try:
                local_pos = event.position().toPoint()
            except AttributeError:
                local_pos = event.pos()
            scene_pos = self.view.mapToScene(local_pos)
            item = self.scene.itemAt(scene_pos, self.view.transform())
            node = self._resolve_server_node(item)
            if node:
                self._on_node_double_click_direct(node)
                return True
        return super().eventFilter(source, event)

    # ── v1.3.3.6 (ROADMAP task 2): dropping a project onto the window ────────
    # `setAcceptDrops(True)` is called in `_setup_ui`. Nothing else in the main window
    # accepts drops (the SFTP tab of the "tabs"-mode dock does, natively takes
    # precedence and keeps working), so a local-file drag lands here.

    def dragEnterEvent(self, event):
        # Any local-file drag is ACCEPTED here so that a refused drop still reaches
        # `dropEvent` and can be explained; the strict validation is one step later.
        # The alternative (validating at enter time) shows nothing at all for two
        # files or a foreign suffix — the "silence" this task exists to remove.
        if _dropped_local_paths(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # The same answer as dragEnter — otherwise Qt resets the action before Drop
        # (the `SftpTab.dragMoveEvent` rule).
        if _dropped_local_paths(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = _project_drop_candidate(event.mimeData())
        if path:
            event.acceptProposedAction()
            # The ONE load entry point (File → Open, Recent, recovery): the autosave
            # prompt, the undo reset, the status round and the MRU behave identically.
            self._load_project_at(path)
            return
        event.ignore()
        self.statusBar().showMessage(self.t("msg.drop_project"), 8000)

    def _setup_toolbar(self):
        toolbar = QToolBar()
        # v1.1.2RC3 (AUDIT U2): objectName is needed by saveState()/restoreState() —
        # without it Qt writes "'objectName' not set for QToolBar" to stderr.
        toolbar.setObjectName("main_toolbar")
        self.addToolBar(toolbar)
        self._toolbar = toolbar

        # UI polish: all actions get vector icons (ui/icons.py, replacing emoji);
        # text-only actions in the toolbar would look out of place.
        # v1.3.3.3 (task 3): the 4th tuple element is the REGISTRY action_id — the
        # toolbar buttons of global actions join the "no orphans" audit and follow a
        # hotkey assigned to their action (before, Ctrl+Shift+A worked in the menu
        # and silently not on the toolbar button of the same action).
        #
        # v1.5rc4 (ROADMAP task 2): the PINNED set of the toolbar ────────────
        # The toolbar stopped repeating what the SIDEBAR and the PALETTE already own
        # (the pinned decision of the release — "the kept set is pinned at the start"):
        #
        #   * `edit.add_server` / `edit.add_connection` are GONE — the sidebar's own
        #     first two buttons (and every menu/palette entry) do the same job from a
        #     surface that is always on screen;
        #   * `file.save_as` is GONE — a rare variant of "Save" that stays in the File
        #     menu and in the palette.
        #
        # What remains is the pinned keep-set: the three file verbs, "Center" / "Fit",
        # undo/redo and the FIVE view toggles (the panel switches have no other
        # one-click surface; v1.6 adds the activity panel to the group). The first five
        # are OVERFLOWABLE — on a narrow window they move into the "»" menu instead of
        # being squeezed (the second pinned decision: overflow, not wrapping); undo/redo
        # and the toggles never move.
        _fallback = {
            "file.new_project": "New Project", "file.open": "Open...", "file.save": "Save",
            "view.center_map": "Center map", "view.fit_map": "Fit Map to Content",
        }
        groups = (
            (("file.new_project", self._new_project, "new", "file.new"),
             ("file.open", self._open_project, "open", "file.open"),
             ("file.save", self._save_project, "save", "file.save")),
            (("view.center_map", self._center_view, "center", "view.center_map"),
             ("view.fit_map", self._fit_to_content, "fit", "view.fit_map")),
        )
        self._toolbar_overflow_actions = []
        # The objects the overflow policy hides: a QToolButton for an action (the QAction
        # itself stays VISIBLE — it is also inside the "»" menu) and the separator's own
        # QAction (no other widget carries it). Both answer setVisible().
        self._toolbar_overflow_items = []
        for gi, group in enumerate(groups):
            if gi:
                self._toolbar_overflow_items.append(toolbar.addSeparator())
            for key, slot, icon_name, action_id in group:
                text = self.t(key) if self._i18n_available else _fallback[key]
                action = toolbar.addAction(text, slot)
                self._register_i18n(action, key)
                # v1.3.3.3 (task 3): every one of these also exists in a menu, and the
                # MENU item is the hotkey target — the toolbar button only mirrors the
                # same slot (see the note above _apply_hotkeys).
                self._mark_toolbar_mirror(action)
                try:
                    set_action_icon(action, icon_name)  # v1.4.3-fix: remembers the name for the theme walk
                except Exception:  # noqa: BLE001 — the icon is cosmetic; do not break the toolbar
                    pass
                self._toolbar_overflow_actions.append(action)
                widget = toolbar.widgetForAction(action)
                if widget is not None:
                    self._toolbar_overflow_items.append(widget)

        # v0.8.3: undo/redo in the toolbar (icons + text; enabled state driven by QUndoStack)
        # v1.3.2: the sequences come from the action registry — "edit.undo"/"edit.redo"
        # are registered as hotkey targets on their EDIT-MENU items; the toolbar buttons
        # are mirrors (a second target would make Ctrl+Z an "Ambiguous shortcut overload").
        # v1.5rc4: these two are NOT overflowable — undo is the one control a user reaches
        # for without looking, so it must never move into a menu.
        toolbar.addSeparator()
        self.act_undo = toolbar.addAction(
            self.t("edit.undo") if self._i18n_available else "Undo",
            self._undo)
        self._mark_toolbar_mirror(self.act_undo)
        self.act_undo.setEnabled(False)
        try:
            set_action_icon(self.act_undo, "undo")
        except Exception:
            pass
        self.undo_stack.canUndoChanged.connect(self.act_undo.setEnabled)

        self.act_redo = toolbar.addAction(
            self.t("edit.redo") if self._i18n_available else "Redo",
            self._redo)
        self._mark_toolbar_mirror(self.act_redo)
        self.act_redo.setEnabled(False)
        try:
            set_action_icon(self.act_redo, "redo")
        except Exception:
            pass
        self.undo_stack.canRedoChanged.connect(self.act_redo.setEnabled)

        # ── v1.4.5 (ROADMAP task 4) + v1.4.6: the VIEW toggles on the toolbar ──
        # FOUR checkable buttons in ONE group at the right end: the two splitter panels
        # ("Sidebar / Map" and "Map / List"), the minimap and the legend. Each MIRRORS its
        # checkable View item — the menu item owns the hotkey and the state, the button
        # owns the click (the v1.2.4.1 collapse-button pattern). The pairs are wired in
        # _setup_menubar, which runs AFTER this method and creates the QActions.
        # v1.5rc4: never overflowable — they are the only one-click surface of the four
        # panels, and a hidden panel is exactly what a user cannot find in a menu.
        toolbar.addSeparator()
        self._view_toolbar_buttons = {}
        for action_id, icon_name, key, fallback in _VIEW_TOOLBAR_ITEMS:
            text = self.t(key) if self._i18n_available else fallback
            btn = toolbar.addAction(text)
            btn.setCheckable(True)
            btn.setChecked(True)   # synced with its action/panel/config in _setup_menubar
            btn.setToolTip(text)
            self._register_i18n(btn, key)
            # A toolbar button is a MIRROR: it must not own the action's sequence
            # (two enabled QActions with one sequence fire NEITHER — v1.3.3.3).
            self._mark_toolbar_mirror(btn)
            try:
                set_action_icon(btn, icon_name)
            except Exception:  # noqa: BLE001 — the icon is cosmetic; do not break the toolbar
                pass
            self._view_toolbar_buttons[action_id] = btn
            btn.toggled.connect(
                lambda checked, aid=action_id: self._on_view_toolbar_toggled(aid, checked))
        # The v1.4.5 attribute survives the generalisation: it IS the legend's button.
        self._legend_toolbar_btn = self._view_toolbar_buttons["view.toggle_legend"]
        # v1.4.6: the minimap button (next to the legend) — the user asked for a switch
        # of the panel without opening the View menu.
        self._minimap_toolbar_btn = self._view_toolbar_buttons["view.toggle_minimap"]
        self._sidebar_toolbar_btn = self._view_toolbar_buttons["view.toggle_sidebar"]
        self._map_toolbar_btn = self._view_toolbar_buttons["view.toggle_map"]
        # v1.6 (ROADMAP task 7): the activity panel's button — the fifth member of the
        # cluster (the attribute survives for the same reason as the four above).
        self._activity_toolbar_btn = self._view_toolbar_buttons["view.toggle_activity"]

        # ── v1.5rc4 (ROADMAP task 2): the "»" OVERFLOW menu ────────────────────
        # Not Qt's own toolbar extension: that one is a popup of ICONS with no labels,
        # and this application's actions are named by words. The menu holds the very
        # SAME QActions the toolbar carries (an action may live in two widgets), so the
        # enablement, the icons and the menu/palette behaviour cannot diverge.
        #
        # The button is reached through an ACTION, not through `addWidget()`: a QToolBar
        # re-shows a widget item at layout time (measured — `hide()` on a widget item does
        # not survive the next layout pass), while `QAction.setVisible()` is the toolbar's
        # own visibility contract.
        overflow_action = toolbar.addAction("\u00bb")
        overflow_btn = toolbar.widgetForAction(overflow_action)
        if overflow_btn is None:   # a stripped style without a button — no overflow menu
            overflow_btn = QToolButton(toolbar)
            toolbar.addWidget(overflow_btn)
        self._toolbar_overflow_action = overflow_action
        self._toolbar_overflow_btn = overflow_btn
        overflow_btn.setObjectName("ToolbarOverflowButton")
        overflow_btn.setText("\u00bb")
        overflow_btn.setAutoRaise(True)
        # The TOOLTIP lives on the ACTION: Qt copies an action's tooltip onto its toolbar
        # button (measured — a tooltip set on the button alone is overwritten by that
        # sync), and the action is also what the language switch re-texts.
        overflow_action.setToolTip(
            self.t("toolbar.more") if self._i18n_available else "More actions")
        overflow_btn.setToolTip(overflow_action.toolTip())
        overflow_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        overflow_menu = QMenu(overflow_btn)
        for action in self._toolbar_overflow_actions:
            overflow_menu.addAction(action)
        overflow_menu.addSeparator()
        overflow_btn.setMenu(overflow_menu)
        self._toolbar_overflow_menu = overflow_menu
        overflow_action.setVisible(False)
        # `None` — "not computed yet", so the FIRST sync always applies (a window whose
        # width is still 0 must not be treated as "already wide").
        self._toolbar_compact = None
        # v1.5rc4: the "»" glyph is the button's TEXT, so the translated sentence can only
        # be a TOOLTIP — `_register_i18n` would replace the glyph itself. The re-text is
        # therefore done by hand in `_apply_ui_translations()` (the ACTION carries it).
        self._sync_toolbar_overflow(self.width())

    # ── v1.5rc4 (ROADMAP task 2): the toolbar overflow policy ──────────────────
    # Pinned: OVERFLOW, never wrapping; the keep-set is the five overflowable buttons plus
    # the core ones that never move (undo/redo and the four view toggles). ONE method
    # decides, and the threshold is MEASURED: the sum of what the toolbar's own widgets ask
    # for. A typed number would be wrong the moment a translation or the UI font grows.

    #: The room the toolbar keeps between its buttons and the window edge.
    TOOLBAR_OVERFLOW_SLACK = 32
    #: How much air the full set must have before the bar keeps it: the measured width
    #: times this factor. A pinned set that only fits edge-to-edge reads as "squeezed" —
    #: exactly what the release's second decision forbids — so the secondary buttons move
    #: into the "»" menu while the window is merely comfortable-narrow rather than only
    #: when it is physically impossible.
    TOOLBAR_OVERFLOW_COMFORT = 1.5

    def _toolbar_full_width(self) -> int:
        """The width the toolbar needs for the FULL pinned set (0 — no toolbar yet).

        The "»" button itself is NOT counted: it is the alternative to the set, not a
        member of it — counting it would make the measurement depend on the state it is
        supposed to decide.
        """
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None:
            return 0
        overflow_btn = getattr(self, "_toolbar_overflow_btn", None)
        total = 0
        try:
            actions = list(toolbar.actions())
        except RuntimeError:
            return 0
        for action in actions:
            widget = toolbar.widgetForAction(action)
            if widget is None or widget is overflow_btn:
                continue
            try:
                total += max(int(widget.sizeHint().width()), 8)
            except RuntimeError:
                continue  # Qt teardown — that widget is already destroyed
        return total + (self.TOOLBAR_OVERFLOW_SLACK if total else 0)

    def _sync_toolbar_overflow(self, width=None) -> bool:
        """Apply the toolbar overflow policy for ``width`` (the window's, by default).

        Returns True while the COMPACT state is in effect. Idempotent and never raises:
        every widget of the overflowable part is hidden or shown together with its
        separators, so the toolbar never shows a dangling divider.
        """
        try:
            value = int(self.width() if width is None else width)
        except (TypeError, ValueError):
            return bool(getattr(self, "_toolbar_compact", False))
        needed = self._toolbar_full_width()
        compact = 0 < value < max(int(needed * self.TOOLBAR_OVERFLOW_COMFORT), 1)
        if compact == getattr(self, "_toolbar_compact", None):
            return compact
        self._toolbar_compact = compact
        for item in getattr(self, "_toolbar_overflow_items", []):
            try:
                item.setVisible(not compact)
            except (RuntimeError, AttributeError):
                continue  # Qt teardown / an unexpected handle — the rest still applies
        # The "»" itself is the toolbar's own ACTION visibility (a widget item would be
        # re-shown by the next layout pass — see `_setup_toolbar`).
        overflow_action = getattr(self, "_toolbar_overflow_action", None)
        if overflow_action is not None:
            try:
                overflow_action.setVisible(compact)
            except RuntimeError:
                pass  # Qt teardown — the action is already destroyed
        return bool(compact)

    def toolbar_overflow_active(self) -> bool:
        """True while the toolbar is in its compact state (the topical test's seam)."""
        return bool(getattr(self, "_toolbar_compact", False))

    # ── v1.5rc4 (ROADMAP task 1): the status-bar overflow policy ───────────────
    # The pinned priority of the status bar (see `ui/status_bar.py`): the multi-input
    # plaque, then the three CLICKABLE status counters and the zoom percentage — and only
    # then the "Servers / Connections" totals. In this release the totals are the ONE
    # thing that leaves the bar, which is exactly the promise of the plan ("the v1.4.5
    # counters must not become the first thing to disappear — they are the interactive
    # part"). The policy is ONE method, the threshold is ONE number and the widgets are
    # only ever HIDDEN, never rebuilt — so a wide window gets the pair back untouched.

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
    # ── v1.5rc4 (ROADMAP task 7): the floating-panel priority rule ──────────────
    # Five panels float over the canvas (the search bar, the minimap, the legend, the
    # first-run hint and — since v1.5.4 — the active-filter plaque) plus the map-collapse
    # diamond, which is a child of the view too. Where they sit is decided in ONE place,
    # from the LIVE geometry:
    #
    #   1. the first-run hint WINS over the legend — while an empty map explains itself,
    #      the legend is suppressed (it explains a map that has nothing to explain yet);
    #   2. the minimap yields to the OPEN search bar (the v1.4.2 rule, kept: the panel
    #      steps below the bar);
    #   3. the collapse diamond is never covered by a panel — it is moved out of the way.
    #
    # The filter plaque joined the SAME resolution in v1.5.4 (it is a rect in
    # `_overlay_panel_rects()` and it yields to the bar the way the minimap does), so the
    # rule has one home and one call site instead of a second layout pass.
    #
    # The suppression is TEMPORARY and never touches the saved state: the legend's own
    # `ui_legend` key and `_legend_enabled` are the user's, and `_legend_suppressed` is
    # the window's. That separation is the point of the rule — a hint appearing on an
    # empty map must not silently turn the legend off for good.

    def _sync_overlay_priority(self):
        """Resolve the floating panels from the live geometry (v1.5rc4, task 7)."""
        self._sync_legend_suppression()
        # The minimap's own rule lives with its placement (`_position_minimap`), and the
        # diamond is placed by `_position_map_collapse_btn` — both are re-run here so ONE
        # call site keeps the panels consistent after any geometry change.
        self._position_minimap()
        # v1.5.4 (ROADMAP task 3): the filter plaque yields to an OPEN search bar (it steps
        # below it) — its placement is part of the same ONE resolution, so the bar opening
        # and closing move it without a second call site.
        self._position_filter_plaque()
        self._position_map_collapse_btn()

    def _sync_legend_suppression(self) -> bool:
        """Temporarily hide the legend while the first-run hint is on screen.

        Returns True while the legend is suppressed. The panel is hidden but its state
        (`_legend_enabled`, the config) is untouched; as soon as the hint goes away — the
        first server arrives, or a project is opened — the legend comes back exactly as
        the user left it.
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return False
        overlay = getattr(self, "empty_state", None)
        hint_up = bool(overlay is not None and overlay.is_state_visible())
        suppressed = bool(getattr(self, "_legend_suppressed", False))
        try:
            if hint_up and not suppressed and bool(getattr(self, "_legend_enabled", True)):
                legend.hide()
                self._legend_suppressed = True
                return True
            if not hint_up and suppressed:
                self._legend_suppressed = False
                if bool(getattr(self, "_legend_enabled", True)):
                    legend.setVisible(True)
                    self._position_legend()
        except RuntimeError:
            pass  # Qt teardown — the panel is already destroyed
        return bool(getattr(self, "_legend_suppressed", False))

    def legend_suppressed(self) -> bool:
        """True while the legend is hidden BY the priority rule (not by the user)."""
        return bool(getattr(self, "_legend_suppressed", False))

    # ── v1.5rc4 (ROADMAP task 5/6): the keyboard domains ───────────────────────
    # The window has three of them — the map, the sidebar and (in `terminal_mode =
    # "tabs"`) the terminal dock — and each shows the SAME focus ring. "Focus the map"
    # (the ONE new registry action of the release) hands the keyboard to the canvas, and
    # `_focus_domain_step()` is what Ctrl+Tab calls to walk between the domains.

    def _focus_map(self):
        """View → Focus the map: hand the keyboard to the canvas (v1.5rc4, task 6)."""
        view = getattr(self, "view", None)
        if view is None:
            return
        if getattr(self, "_map_collapsed", False):
            return  # a collapsed map has no surface to focus (the View-action rule)
        try:
            view.setFocus(Qt.FocusReason.ShortcutFocusReason)
        except (RuntimeError, TypeError):
            pass  # Qt teardown — nothing to focus

    def _focus_domain_step(self, step: int = 1):
        """Move the keyboard to the next/previous keyboard domain (Ctrl+Tab).

        The domains are the sidebar's tree, the map canvas and the terminal canvas of the
        ACTIVE session (when the dock mode is on) — the three surfaces that show a focus
        ring. A domain that is not reachable (a collapsed map, no session, no sidebar) is
        skipped; an unknown widget loses to the first reachable one.
        """
        candidates = []
        tree = getattr(getattr(self, "sidebar", None), "tree", None)
        if tree is not None and tree.isVisible():
            candidates.append(tree)
        view = getattr(self, "view", None)
        if view is not None and view.isVisible() and not getattr(self, "_map_collapsed", False):
            candidates.append(view)
        session = self._active_terminal_canvas()
        if session is not None:
            candidates.append(session)
        if not candidates:
            return None
        current = QApplication.focusWidget()
        index = -1
        for position, widget in enumerate(candidates):
            if widget is current or (current is not None and widget.isAncestorOf(current)):
                index = position
                break
        target = candidates[(index + int(step)) % len(candidates)]
        try:
            target.setFocus(Qt.FocusReason.OtherFocusReason)
        except (RuntimeError, TypeError):
            return None
        return target

    def _active_terminal_canvas(self):
        """The canvas of the VISIBLE terminal session, or None (v1.5rc4).

        Windows mode and dock mode both keep their pages in `_terminal_windows` and both
        hold them in a `session_tabs` QTabWidget; the first live page that is the CURRENT
        tab of a visible container (a split pane counts — it is visible under the tabs) is
        "where the keys would go". Used by `_focus_domain_step` only — never by the
        session logic.
        """
        for page in list(getattr(self, "_terminal_windows", None) or []):
            try:
                canvas = getattr(page, "widget", None)
                if canvas is None or not canvas.isVisible():
                    continue
                window = getattr(page, "_host_window", None)
                container = window if window is not None else page.window()
                if container is None or not container.isVisible():
                    continue
                tabs = getattr(window, "session_tabs", None) if window is not None else None
                if tabs is None:
                    tabs = getattr(container, "session_tabs", None)
                if (tabs is not None and tabs.currentWidget() is not page
                        and not getattr(page, "_is_split_pane", False)):
                    continue   # a background tab — its canvas is not what the user sees
                return canvas
            except (RuntimeError, AttributeError):
                continue
        return None

    def resizeEvent(self, event):
        """v1.5rc4 (ROADMAP tasks 1/2/7): a resize drives the THREE chrome policies.

        One entry point for the window's own geometry: the toolbar overflow (task 2), the
        status-bar overflow (task 1) and the floating-panel priority (task 7). Each of them
        is idempotent and decides from the live width, so a resize storm costs three
        comparisons and no rebuild. A resize that arrives before the widgets exist (the
        constructor applies the saved geometry early) is a no-op for each of them.
        """
        super().resizeEvent(event)
        try:
            width = int(event.size().width())
        except (AttributeError, TypeError, ValueError):
            width = None
        self._sync_toolbar_overflow(width)
        self._sync_status_bar_overflow(width)
        self._sync_overlay_priority()

    def _style_collapse_btn(self, btn) -> None:
        """v1.5.6 (ROADMAP task 4): give a panel collapse button its FRAME.

        The two "◇" corners are plain QToolButtons — no `setAutoRaise` — and their look
        comes from the ONE `collapse.button` entry of the QSS registry (a QSS string is a
        VALUE, so it is re-applied by `_refresh_icons()` on a theme switch, next to the
        icon ink). Never raises: a cosmetic style must not be able to break the chrome.
        """
        if btn is None or theme_qss is None:
            return
        try:
            theme_qss.refresh(btn, "collapse.button")
        except RuntimeError:
            pass  # Qt teardown — the button is already destroyed

    def _mark_toolbar_mirror(self, action) -> None:
        """v1.3.3.3: keep a toolbar button that MIRRORS a menu action shortcut-free.

        Every toolbar button duplicates a menu item one-to-one, and both QActions live
        in the same window. Registering BOTH as hotkey targets made
        ``_apply_hotkeys()`` give the same sequence to two enabled QActions — Qt then
        resolves the click with "Ambiguous shortcut overload" and fires NEITHER
        (verified offscreen: Ctrl+Shift+S was dead; v1.3.2 never hit this because the
        toolbar carried a literal ``setShortcut`` only for undo/redo, which Qt silently
        ignored as a duplicate).

        So: the MENU item owns the sequence, the toolbar button owns the click. This
        also removes a real duplication — ``toolbar.addAction(text, slot)`` used to
        auto-install Qt's own "Ctrl+S"-style shortcut from the action text.
        """
        try:
            action.setShortcut(QKeySequence())   # the same "no shortcut" value the registry uses
        except (RuntimeError, TypeError):
            pass  # Qt teardown / an unexpected wrapper — the button still clicks

    def _add_menu_action(self, menu, key: str, slot, action_id: str = "", icon_name: str = ""):
        """Add a translated menu item and register it for re-translation.

        v1.3.2 (ROADMAP v1.3.2, task 1): the shortcut is NOT a literal any more.
        With an ``action_id`` the QAction becomes a hotkey target of the action
        registry (``ui/hotkey_registry.py``) and receives its sequence from there in
        ``_apply_hotkeys()`` — at startup and live after the settings dialog's OK.
        Without an action_id the item has no hotkey at all.

        v1.3.3.3 (task 2): an optional vector ``icon_name`` (``ui/icons.py``) — the
        zoom items of the View menu carry one, like the toolbar buttons do. Unknown
        name / a missing ui.icons → the item simply stays text-only.
        """
        action = menu.addAction(self.t(key), slot)
        self._register_i18n(action, key)
        if icon_name:
            try:
                set_action_icon(action, icon_name)  # v1.4.3-fix: the theme walk finds it by this name
            except Exception:  # noqa: BLE001 — the icon is cosmetic; do not break the menu
                pass
        if action_id:
            self._register_hotkey_target(action_id, action)
        return action

    def _setup_menubar(self):
        menubar = self.menuBar()

        # File menu
        # v1.3.2: the Ctrl+N/O/S hints come from the hotkey registry (action_ids below).
        file_menu = menubar.addMenu(self.t("menu.file") if self._i18n_available else "File")
        self._register_i18n(file_menu, "menu.file")
        # v1.3.3.6 (ROADMAP task 1): "Recent" — the FIRST item of the File menu (the
        # gesture it replaces is the top of the menu: File → Open → dialog). Rebuilt
        # from `recent_projects` on every aboutToShow (the v1.3.3.1 language-submenu
        # pattern); the rebuild re-registers its QActions in `_qaction_guard`
        # (gotcha #9).
        self._recent_menu = file_menu.addMenu(
            self.t("file.recent") if self._i18n_available else "Recent")
        self._register_i18n(self._recent_menu, "file.recent")
        self._populate_recent_menu(self._recent_menu)
        self._recent_menu.aboutToShow.connect(
            lambda: self._populate_recent_menu(self._recent_menu))
        file_menu.addSeparator()
        self._add_menu_action(file_menu, "file.new_project", self._new_project, "file.new")
        self._add_menu_action(file_menu, "file.open", self._open_project, "file.open")
        self._add_menu_action(file_menu, "file.save", self._save_project, "file.save")
        # v1.3.3.3 (task 1): "Save As…" gets a home in the registry (Ctrl+Shift+S).
        self._add_menu_action(file_menu, "file.save_as", self._save_project_as, "file.save_as")
        # v0.9.7: autosave + a ring buffer of backups (ROADMAP v0.9.7 #2/#3) —
        # enabled state driven by _update_window_title (an open project file is required).
        self.act_restore_autosave = self._add_menu_action(
            file_menu, "file.restore_autosave", self._restore_from_autosave, "file.restore_autosave")
        self.act_backups = self._add_menu_action(
            file_menu, "file.backups", self._show_backups_dialog, "file.backups")
        # v0.9.5.5: bulk import of servers from a text file
        self._add_menu_action(file_menu, "file.import_servers", self._import_servers_from_txt,
                              "file.import_servers")
        # v1.4.1: bulk import from the OpenSSH client config (~/.ssh/config) — the
        # second import path of the same family; both add their batch as ONE undo command.
        self._add_menu_action(file_menu, "file.import_ssh_config",
                              self._import_servers_from_ssh_config, "file.import_ssh_config")
        file_menu.addSeparator()
        self._add_menu_action(file_menu, "file.exit", self.close, "file.exit")

        # Edit menu
        edit_menu = menubar.addMenu(self.t("menu.edit") if self._i18n_available else "Edit")
        self._register_i18n(edit_menu, "menu.edit")
        # v0.8.3: Undo/Redo — the first items of the "Edit" menu
        # v1.3.2: the sequences — from the registry (the menu shows the same ones as the toolbar)
        self._add_menu_action(edit_menu, "edit.undo", self._undo, "edit.undo")
        self._add_menu_action(edit_menu, "edit.redo", self._redo, "edit.redo")
        edit_menu.addSeparator()
        self._add_menu_action(edit_menu, "edit.add_server", self._add_server, "edit.add_server")
        self._add_menu_action(edit_menu, "edit.add_group", self._add_group_at, "edit.add_group")  # v0.8.1: node groups
        self._add_menu_action(edit_menu, "edit.add_connection", self._add_connection, "edit.add_connection")
        self._add_menu_action(edit_menu, "edit.properties", self._show_properties, "edit.properties")
        # v0.9.2: hotkeys for frequent actions on the selected node
        self._add_menu_action(edit_menu, "ctx.ssh_connect", self._connect_ssh_to_selected, "node.ssh_connect")
        self._add_menu_action(edit_menu, "ctx.edit_server", self._edit_selected_node, "node.edit_server")
        self._add_menu_action(edit_menu, "ctx.add_note", self._add_note_at_view_center, "node.add_note")
        self._add_menu_action(edit_menu, "edit.delete", self._delete_selected, "edit.delete")
        # v0.9.3: duplication + multi-selection group operations
        self._add_menu_action(edit_menu, "edit.duplicate", self._duplicate_selected_node, "edit.duplicate")
        edit_menu.addSeparator()
        self._add_menu_action(edit_menu, "edit.connect_selected", self._connect_selected_nodes,
                              "edit.connect_selected")
        # v1.6 (ROADMAP task 1): the BULK EDIT of the selection — tags / comment / quick
        # launch in ONE undo step. A permanent Edit-menu item, like the multi-selection
        # pair above: a context menu is rebuilt on every right click, so its QAction
        # cannot carry a configurable sequence. Enabled by `_sync_selection_state()`.
        self.act_bulk_edit = self._add_menu_action(
            edit_menu, "edit.bulk_edit", self._bulk_edit_selection, "edit.selected")
        self.act_bulk_edit.setEnabled(False)   # nothing is selected at construction time
        # v1.6 (ROADMAP task 6): the auto-arrangement of a GROUP's members. It sits next
        # to the group verbs of the context menu; the id keeps the `edit.` prefix so
        # `action_family()` files it under Edit in the "Hotkeys" tab (a `group.…` prefix
        # would fall back instead of joining the table).
        self.act_arrange_group = self._add_menu_action(
            edit_menu, "ctx.arrange_group", self._arrange_selected_group, "edit.arrange_group")
        self.act_arrange_group.setEnabled(False)   # no group is selected at construction
        self._add_menu_action(edit_menu, "edit.delete_selected", self._delete_selected_nodes,
                              "edit.delete_selected")
        # v1.3.3.3 (task 5): the on-demand status round — a permanent Edit-menu item
        # (the same method the map/sidebar context menus call), which is also what makes
        # the action a real hotkey target: a context menu is rebuilt on every right
        # click, so its QAction cannot carry a configurable sequence.
        self._add_menu_action(edit_menu, "ctx.check_status", self._check_statuses_now,
                              "node.check_status")
        # v1.5.3 (ROADMAP tasks 2/3): the two on-demand answers of the freshness release.
        # "Gather information" — one bounded batch for the SELECTION (or the whole map when
        # nothing is selected), off the GUI thread; it reuses the existing `ctx.collect_info`
        # label, so the sidebar/map context menus and this permanent Edit item read the same.
        # "Why is it offline?" — the reachability report (DNS → TCP → banner → ping) whose
        # sentence lands in the card tooltip, the status bar and the activity history.
        # Both are permanent menu items on purpose: a context menu is rebuilt on every right
        # click, so its QAction cannot carry a configurable sequence (the v1.3.3.3 rule).
        self._add_menu_action(edit_menu, "ctx.collect_info", self._collect_info_many,
                              "node.collect_info")
        self._add_menu_action(edit_menu, "ctx.diagnose", self._diagnose_node,
                              "node.diagnose")

        # Export menu
        # The ONE home of everything that LEAVES the application. It is a CONTAINER, not a
        # new family: the actions keep their ids and their `file.*` keys, because a
        # `config.json` `hotkeys` value is keyed by the ACTION ID (a rename would drop every
        # user's binding silently) and the Hotkeys tab groups by the id's family. Three
        # groups, separated by the SUBJECT of the report: the map IMAGE exports, the two
        # image paths of the clipboard/poster family, and the DATA reports (the inventory
        # table of the LIST mode). The two DATA items are ENABLED only while the table
        # exists (`_sync_list_mode` — the one place the mode changes).
        export_menu = menubar.addMenu(self.t("menu.export") if self._i18n_available else "Export")
        self._register_i18n(export_menu, "menu.export")
        # v0.9.1: export the map to an image (PNG/JPEG)
        self._add_menu_action(export_menu, "file.export_png", self._export_map_image,
                              "file.export_png")
        # v0.9.5: export the map to drawio (.drawio)
        self._add_menu_action(export_menu, "file.export_drawio", self._export_map_drawio,
                              "file.export_drawio")
        # v0.9.9.7: export the map to PDF (QPdfWriter on top of render_to_pixmap)
        self._add_menu_action(export_menu, "file.export_pdf", self._export_map_pdf,
                              "file.export_pdf")
        # v1.3.3.7: export the map to SVG (QSvgGenerator — the vector member of the set)
        self._add_menu_action(export_menu, "file.export_svg", self._export_map_svg,
                              "file.export_svg")
        # v1.5.1 (ROADMAP tasks 1/2): the two IMAGE paths of the same machinery — the 2×
        # render straight to the clipboard (the CURRENT theme, NO palette question) and the
        # fixed 1600×900 @2× poster of the documentation. Both are registry actions with an
        # EMPTY default, so the keyboard can reach them through the Hotkeys tab.
        export_menu.addSeparator()
        self._add_menu_action(export_menu, "file.copy_map", self._copy_map_image, "file.copy_map")
        self._add_menu_action(export_menu, "file.docs_frame", self._export_docs_frame,
                              "file.docs_frame")
        # v1.5.5 (ROADMAP tasks 2/3): the INVENTORY family — the server table of the LIST
        # mode leaves the application: the visible table to the clipboard as TSV (one paste
        # into a spreadsheet) and to a file as CSV or TSV. A different SUBJECT from the map
        # exports above (a report of the DATA, not a picture of the map), which is why the
        # two groups are separated.
        export_menu.addSeparator()
        self.act_copy_list = self._add_menu_action(
            export_menu, "file.copy_list", self._copy_list_table, "file.copy_list")
        self.act_export_list = self._add_menu_action(
            export_menu, "file.export_list", self._export_list_table, "file.export_list")
        # v1.6 (ROADMAP task 5): the SECOND report of the DATA family — "who talks to
        # whom" as a table (one row per arrow: two endpoints, the declared type, the
        # direction and the bidirectional flag). It rides the SAME pure RFC-4180 writer
        # the inventory report uses (`ui/sidebar.list_table_text`), so a label carrying a
        # comma, a quote or a line break cannot leave the application two different ways.
        self.act_export_connections = self._add_menu_action(
            export_menu, "file.export_connections", self._export_connections_table,
            "file.export_connections")

        # Profile menu
        profile_menu = menubar.addMenu(self.t("menu.profile") if self._i18n_available else "Profile")
        self._register_i18n(profile_menu, "menu.profile")
        self._add_menu_action(profile_menu, "profile.manage", self._open_profile_manager,
                              "profile.manage")

        # View menu
        view_menu = menubar.addMenu(self.t("menu.view") if self._i18n_available else "View")
        self._register_i18n(view_menu, "menu.view")
        self._add_menu_action(view_menu, "view.center_map", self._center_view, "view.center_map")
        # v1.5rc4 (ROADMAP task 6): "Focus the map" — the ONE new registry action of the
        # release ("at most ONE"): it hands the keyboard to the canvas, which then walks
        # its cards with Tab/arrows/Enter/Esc and shows the visible focus ring (task 5).
        # An EMPTY registry default: assignable, no key taken from anyone.
        self._add_menu_action(view_menu, "view.focus_map", self._focus_map, "view.focus_map")
        # v1.3.3.3 (task 2): the whole zoom family — a menu item + a vector icon + a
        # registry entry each (Reset zoom Ctrl+0 has NO use for an icon: reset is a
        # state, not a direction). The step API lives on MapView.
        self._add_menu_action(view_menu, "view.reset_zoom", self._reset_zoom, "view.reset_zoom")
        self._add_menu_action(view_menu, "view.zoom_in", self._zoom_in, "view.zoom_in", "zoom_in")
        self._add_menu_action(view_menu, "view.zoom_out", self._zoom_out, "view.zoom_out", "zoom_out")
        # UI polish: "Fit map" — fitInView by content (Ctrl+Shift+F: a bare F key
        # would conflict with typing into the sidebar search field)
        self._add_menu_action(view_menu, "view.fit_map", self._fit_to_content, "view.fit_map")
        # v0.9.8: map search (Ctrl+F) — a search bar over the canvas; the same
        # Ctrl argument as fit_map (bare F is taken by search-field typing)
        self._add_menu_action(view_menu, "view.find_on_map", self._toggle_map_search, "view.find_on_map")
        # v1.1.1 (item 5): show/hide the WHOLE sidebar; v1.2.4.1 (task 3): the item
        # becomes an expanded<->collapsed toggle (checked = expanded) — ONE
        # "collapse into a thin strip" mechanism for both panels: clicking the item, the corner
        # button, and the collapsed panel's strip all go through one QAction (toggle() -> toggled).
        # Connecting to toggled(bool), not triggered — the v1.2.4-fix pattern on
        # act_multi_input (PySide6 6.11: the auto-connection addAction(text, slot) emits
        # triggered WITHOUT state; an explicit connect passes the new state and fires
        # on a programmatic setChecked — the checkbox and the mechanism stay in sync).
        self.act_show_sidebar = view_menu.addAction(
            self.t("view.toggle_sidebar") if self._i18n_available else "Sidebar")
        self.act_show_sidebar.setCheckable(True)
        self.act_show_sidebar.setChecked(True)
        set_action_icon(self.act_show_sidebar, "sidebar_panel")  # v1.2.4.1: the pair's icon
        self.act_show_sidebar.toggled.connect(self._on_sidebar_toggled)
        self._register_i18n(self.act_show_sidebar, "view.toggle_sidebar")
        # v1.4.6: the toolbar MIRROR of the same toggle (created in _setup_toolbar, which
        # runs BEFORE this method — the pair is wired here, like the v1.4.5 legend one).
        self._wire_view_toolbar_button("view.toggle_sidebar", self.act_show_sidebar)
        # v1.2.4.1 (task 3): the map — the same pattern (created manually, the pair's icon).
        self.act_show_map = view_menu.addAction(
            self.t("view.toggle_map") if self._i18n_available else "Map")
        self.act_show_map.setCheckable(True)
        self.act_show_map.setChecked(True)
        set_action_icon(self.act_show_map, "map_panel")
        self.act_show_map.toggled.connect(self._on_map_toggled)
        self._register_i18n(self.act_show_map, "view.toggle_map")
        self._wire_view_toolbar_button("view.toggle_map", self.act_show_map)   # v1.4.6
        # v1.4.2 (ROADMAP task 2): the minimap — a checkable item next to the panel
        # toggles with the same "created manually + toggled(bool)" pattern. It is a
        # REGISTRY action with an EMPTY default (no hotkey out of the box, assignable in
        # "Settings → Hotkeys"); checked = the panel is shown (the config default is on).
        self.act_show_minimap = view_menu.addAction(
            self.t("view.toggle_minimap") if self._i18n_available else "Minimap")
        self.act_show_minimap.setCheckable(True)
        self.act_show_minimap.setChecked(bool(getattr(self, "_minimap_enabled", True)))
        set_action_icon(self.act_show_minimap, "minimap")
        self.act_show_minimap.toggled.connect(self._toggle_minimap)
        self._register_i18n(self.act_show_minimap, "view.toggle_minimap")
        self._register_hotkey_target("view.toggle_minimap", self.act_show_minimap)
        # v1.4.6: the minimap's own toolbar button (the user asked for a switch of the
        # panel next to the legend's — the View menu is not the only way any more).
        self._wire_view_toolbar_button("view.toggle_minimap", self.act_show_minimap)
        # v1.4.5 (ROADMAP task 4): the legend panel — the same "created manually +
        # toggled(bool)" pattern, the same registry rule (an EMPTY default: assignable,
        # no key out of the box) and a toolbar MIRROR created in _setup_toolbar (which
        # runs before this method — the pair is wired here, exactly like the two panel
        # collapse buttons wired above their own menu items).
        self.act_show_legend = view_menu.addAction(
            self.t("view.toggle_legend") if self._i18n_available else "Legend")
        self.act_show_legend.setCheckable(True)
        self.act_show_legend.setChecked(bool(getattr(self, "_legend_enabled", True)))
        set_action_icon(self.act_show_legend, "legend")
        self.act_show_legend.toggled.connect(self._toggle_legend)
        self._register_i18n(self.act_show_legend, "view.toggle_legend")
        self._register_hotkey_target("view.toggle_legend", self.act_show_legend)
        self._wire_view_toolbar_button("view.toggle_legend", self.act_show_legend)
        # v1.5.2 (ROADMAP task 3): the ACTIVITY panel — the same "created manually +
        # toggled(bool)" pattern and the same registry rule (an EMPTY default:
        # assignable, no key taken from anyone). v1.6 (ROADMAP task 7): it JOINS the
        # toolbar's view cluster — the panel switches became the deliverable of that
        # task, and the activity history is a surface a user glances at as often as the
        # legend (the cluster is wired in `_setup_toolbar`, which runs before this
        # method — the pair is joined here like the four toggles above).
        self.act_show_activity = view_menu.addAction(
            self.t("view.toggle_activity") if self._i18n_available else "Activity panel")
        self.act_show_activity.setCheckable(True)
        self.act_show_activity.setChecked(bool(getattr(self, "_activity_enabled", False)))
        set_action_icon(self.act_show_activity, "activity")
        self.act_show_activity.toggled.connect(self._toggle_activity)
        self._register_i18n(self.act_show_activity, "view.toggle_activity")
        self._register_hotkey_target("view.toggle_activity", self.act_show_activity)
        self._wire_view_toolbar_button("view.toggle_activity", self.act_show_activity)
        # v1.2.4.1 (task 2): corner collapse buttons — the same QAction (toggle()).
        # v1.2.4.1-fix (QA request): the icon — a "◇" diamond on both panels, both
        # at the bottom right (the sidebar's bottom row / the map's right BOTTOM corner — the top is
        # reserved for the minimap per the new discussions).
        self.sidebar.collapse_btn.setIcon(_diamond_icon())
        self._style_collapse_btn(self.sidebar.collapse_btn)   # v1.5.6: the FRAME (task 4)
        if self._i18n_available:
            self.sidebar.collapse_btn.setToolTip(self.t("view.toggle_sidebar"))
        self.sidebar.collapse_clicked.connect(lambda: self.act_show_sidebar.toggle())
        self._map_collapse_btn.setIcon(_diamond_icon())
        self._style_collapse_btn(self._map_collapse_btn)
        if self._i18n_available:
            self._map_collapse_btn.setToolTip(self.t("view.toggle_map"))
        self._map_collapse_btn.clicked.connect(lambda: self.act_show_map.toggle())
        # v1.2.4.1 (task 1): tooltips of the collapsed-panel strips.
        if self._i18n_available:
            self._sidebar_strip.setToolTip(self.t("view.strip_sidebar_tooltip"))
            self._map_strip.setToolTip(self.t("view.strip_map_tooltip"))
        self._sidebar_strip.expand_requested.connect(lambda: self.act_show_sidebar.toggle())
        self._map_strip.expand_requested.connect(lambda: self.act_show_map.toggle())
        # v0.8.4 (former DESIGN.md §D): bulk collapse — half of the feature's value
        # for large maps.
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "view.collapse_all", self._collapse_all_servers,
                              "view.collapse_all")
        self._add_menu_action(view_menu, "view.expand_all", self._expand_all_servers,
                              "view.expand_all")
        # v0.9.1: a map background image (a building diagram / a data-center layout)
        view_menu.addSeparator()
        self._add_menu_action(view_menu, "view.set_background", self._set_background_image,
                              "view.set_background")
        self._add_menu_action(view_menu, "view.remove_background", self._remove_background_image,
                              "view.remove_background")
        # v1.2.3 (ROADMAP tasks 2/3): multi-input — a checkable item; F12 = EXIT from
        # the mode (not Esc — that goes to the shell as \x1b!). ApplicationShortcut: the key
        # is caught regardless of where the focus is (map / terminal window / dock). While
        # the mode is off, the QAction has NO shortcut (QKeySequence() is empty; QAction
        # does not have setShortcutEnabled) — F12 goes to the shell as \x1b[24~ (the RC2
        # mapping of TerminalWidget); in the mode, _on_multi_changed attaches F12 and the mapping is paused.
        view_menu.addSeparator()
        # v1.2.4-fix (root cause of the "menu item does not work" incident): the item is
        # NOT created via _add_menu_action — its auto-connection QMenu.addAction(text, slot) in
        # PySide6 6.11 emits QAction.triggered into the Python slot WITHOUT arguments (empirically:
        # an explicit .triggered.connect passes the new state, the auto-connection does not),
        # and disconnect() CANNOT remove such a connection (RuntimeWarning,
        # the internal adapter) — the slot would remain dangling. checked=None fell into the
        # no-op branch: the mode could not be turned on or off from the menu at all (only the
        # checkbox moved; F12 was silent too — the shortcut is attached only in the active mode).
        # Therefore the QAction is created manually and connected to toggled(bool) — it carries
        # the new state (and fires on a programmatic setChecked: the checkbox and the hub stay
        # in sync). Regression: tests/test_menu_actions_regression.py.
        self.act_multi_input = view_menu.addAction(self.t("view.multi_input"))
        self._register_i18n(self.act_multi_input, "view.multi_input")
        self.act_multi_input.setCheckable(True)
        self.act_multi_input.setChecked(False)
        self.act_multi_input.toggled.connect(self._toggle_multi_input)
        # v1.3.2 (task 4): the sequence is configurable, the RULE is not — the key is
        # installed ONLY while the mode is on (QAction has no setShortcutEnabled; an
        # empty QKeySequence = no shortcut). The registry marks this action "dynamic":
        # apply_to() skips it and _sync_multi_shortcut() owns it (mode state included).
        self._register_hotkey_target("view.multi_input", self.act_multi_input)
        self.act_multi_input.setShortcut(QKeySequence())
        self.act_multi_input.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

        # v1.1 (ROADMAP task 2): the settings dialog (hub) — the "Settings" item BETWEEN
        # "View" and "Help". The item — a QAction INSIDE the menu (not a bare menubar action):
        # the command palette (Ctrl+K) walks all menu QActions and will pick it up automatically.
        settings_menu = menubar.addMenu(
            self.t("menu.settings") if self._i18n_available else "Settings")
        self._register_i18n(settings_menu, "menu.settings")
        self.act_settings = self._add_menu_action(
            settings_menu, "settings.open", self._open_settings_dialog)

        # ── v1.4rc1 (plugin foundation, rc series): the "Plugins" menu ─────
        # BETWEEN "Settings" and "Help" (next to the settings hub). The manager holds
        # the records, this menu renders them: one checkable row per discovered plugin
        # (the enable/disable switch — persisted in `plugins` of config.json) plus
        # "Reload" (a re-discovery of the folder: new/changed ~/.sshmap/plugins/*.py are
        # picked up without a restart). The rows are rebuilt on aboutToShow (the
        # v1.3.3.1 language-submenu pattern) and created MANUALLY with an explicit
        # toggled(bool) connection (gotcha #10: a checkable item must not use the
        # `QMenu.addAction(text, slot)` auto-connection); "Reload" is an ordinary
        # registry action, so the keyboard can reach it like any other menu item.
        self._plugin_menu = menubar.addMenu(
            self.t("menu.plugins") if self._i18n_available else "Plugins")
        self._register_i18n(self._plugin_menu, "menu.plugins")
        self.act_plugins_reload = self._add_menu_action(
            self._plugin_menu, "plugins.reload", self._reload_plugins, "plugins.reload")
        # v1.4rc3 (task 8): "Run on selected servers" — the entry point of the headless
        # `run_on_nodes` hook (rc2 machinery) for the CURRENT selection. A registry
        # action like every other global action (an EMPTY default: assignable in
        # "Settings → Hotkeys"), enabled only while a loaded plugin really implements
        # the hook — `_populate_plugin_items()` recomputes that on every menu open.
        self.act_plugins_run = self._add_menu_action(
            self._plugin_menu, "plugins.run_on_nodes", self._run_plugins_on_nodes,
            "plugins.run_on_nodes", "plugin")
        # The rows go ABOVE the separator, "Reload"/"Run" stay below it; the separator is
        # inserted before the permanent actions so a rebuild of the rows can never
        # destroy either of them (the language menu rebuilds its own children —
        # here the permanent pieces must survive `_populate_plugin_items`).
        self._plugin_sep = self._plugin_menu.insertSeparator(self.act_plugins_reload)
        self._populate_plugin_items()
        self._plugin_menu.aboutToShow.connect(self._populate_plugin_items)

        # Help menu
        help_menu = menubar.addMenu(self.t("menu.help") if self._i18n_available else "Help")
        self._register_i18n(help_menu, "menu.help")
        # v1.5rc3 (ROADMAP task 1): the demo map. The SECOND entry point of the same
        # project — the empty state's button is the first — and both call ONE method
        # (`_open_example_map`), which loads it through the ordinary project load path.
        self.act_example_map = self._add_menu_action(
            help_menu, "example.open", self._open_example_map, "help.example")
        # v1.5rc3 (ROADMAP task 4): the keyboard cheat-sheet — the SAME registry-derived
        # text Help → About renders (`ui/hotkey_sheet_dialog.py` reuses
        # `about_dialog.cheatsheet()`), reachable by F1 and, on the map, by `?`.
        self.act_cheatsheet = self._add_menu_action(
            help_menu, "help.cheatsheet", self._open_hotkey_sheet, "help.cheatsheet")
        self._add_menu_action(help_menu, "help.open_logs", self._open_log_file, "help.open_logs")
        # v1.3.3.3 (task 6): the About window — the version, the license, the paths and
        # the hotkey cheat-sheet generated FROM the registry. Registered in the action
        # registry as well (an empty default: assignable, no hotkey out of the box).
        self.act_about = self._add_menu_action(help_menu, "about.open", self._open_about_dialog,
                                               "help.about")

        # Language submenu (i18n)
        # v1.3.3.1 (ROADMAP task 3): the submenu is no longer frozen at construction —
        # it is (re)built from get_available_languages() every time it is ABOUT TO BE
        # SHOWN (aboutToShow), so an i18n/<code>.json dropped in afterwards appears
        # without a restart. An explicit "Rescan the language files" item makes the
        # behaviour discoverable (and re-reads the ACTIVE file, so an edited
        # translation is picked up too). See _build_language_menu()/_reload_languages().
        if self._i18n_available:
            try:
                self._lang_menu = help_menu.addMenu(self.t("lang.menu"))
                self._register_i18n(self._lang_menu, "lang.menu")
                self._populate_language_menu(self._lang_menu)
                # Rebuild the entries right before the menu opens (lang.reload keeps
                # its place at the bottom — _populate_language_menu appends it).
                self._lang_menu.aboutToShow.connect(
                    lambda: self._populate_language_menu(self._lang_menu))
            except Exception as e:
                if self.log:
                    self.log.warning(f"i18n lang menu error: {e}")

        # v0.9.2: the command palette (Ctrl+K) — a fuzzy search over actions and servers.
        self._setup_command_palette()

        # ── v0.9.8 bugfix (PySide6 6.11, shiboken): a guard for QActions with menus ──
        # Verified empirically (regression_v098 probes, offscreen AND native Windows):
        # when the Python wrapper of a QAction with an ATTACHED QMenu dies
        # (GC of a temporary object from menubar.actions()/act.menu()), PySide6 destroys
        # the C++ QMenu object behind it together with its entire contents. Without the
        # guard, opening the palette (Ctrl+K) or a language switch killed ALL menus
        # except the last one (the palette walks menubar.actions() with temporary wrappers).
        # PySide6 caches the wrappers (a repeat access — the same object), so keeping
        # all such QActions in self._qaction_guard makes them immortal, and therefore
        # the attached QMenus live on. This fixes both _switch_language and the palette,
        # and any future code that walks menus via action.menu().
        # v1.3.3.1: the language submenu is now REBUILT on aboutToShow — the helper is
        # called again after every rebuild, so the fresh QActions are guarded too.
        self._rebuild_qaction_guard()

    def _rebuild_qaction_guard(self):
        """v0.9.8 / v1.3.3.1: keep every QAction that owns an attached QMenu alive.

        The guard list (`self._qaction_guard`) is rebuilt from the i18n registry and
        the menubar — see the PySide6 6.11 pitfall above. Called at the end of
        `_setup_menubar()`, after `_populate_language_menu()` / `_populate_plugin_items()`
        rebuild their children and after a plugin extended a context menu (its QActions
        are created OUTSIDE this window, so without the guard a plugin that keeps no
        reference of its own would lose the row the moment the Python wrapper died).

        v1.4rc3: the registry is walked for QMenus as well as QActions. Until rc2 it held
        only leaf QActions and the "Plugins" menu — whose checkable rows are built by
        `_populate_plugin_items()` — went unguarded; the plugin menu is a QMenu of the
        registry and contributes all of its children, its submenus included (the
        `QMenu.addMenu()` wrapper is a child QAction of its parent, exactly the object
        gotcha #9 is about).
        """
        try:
            menubar = self.menuBar()

            def collect(menu, out, depth=0):
                if menu is None or depth > 8:
                    return
                for act in list(menu.actions()):
                    out.append(act)
                    child = act.menu()
                    if child is not None:
                        collect(child, out, depth + 1)

            guard = []
            for w, _key in self._menu_i18n:
                if isinstance(w, QMenu):
                    collect(w, guard)
            collect(menubar, guard)  # the top-level menus and their children
            # Context-menu rows a plugin created (`_extend_node_context_menu`).
            guard.extend(self._plugin_menu_actions)
            self._qaction_guard = guard
        except RuntimeError:
            pass  # Qt teardown — nothing to guard

    # ── v1.3.3.1 (ROADMAP task 3): the language list without a restart ───────

    def _populate_language_menu(self, menu):
        """(Re)build the `Help → Language` submenu from the DISCOVERED files.

        Called at construction and again on every `aboutToShow` (v1.3.3.1), so an
        `i18n/<code>.json` dropped into the folder after startup shows up when the
        menu is next opened — no restart, no code change. One `lang.reload` item
        ("Rescan the language files") is appended under a separator: it re-reads the
        available language files AND the active one, which makes the behaviour
        discoverable (`MainWindow._reload_languages()`).

        The children are QActions created MANUALLY (never the
        `QMenu.addAction(text, slot)` auto-connection — PySide6 6.11 emits
        `triggered` into a Python slot without the argument and cannot be
        disconnected, gotcha #10). Never raises.
        """
        try:
            from i18n import get_available_languages as _get_langs
            langs = _get_langs()
        except Exception as e:  # noqa: BLE001 — a broken i18n must not break the menu
            if self.log:
                self.log.warning(f"i18n lang menu error: {e}")
            return
        try:
            menu.clear()
            for lg in langs:
                action = menu.addAction(lg["name"])
                action.setCheckable(True)
                action.setChecked(lg["code"] == self.current_language)
                action.setData(lg["code"])  # the language code — for the checkmark on switch
                code = lg["code"]
                action.triggered.connect(lambda checked=False, c=code: self._switch_language(c))
            if langs:
                menu.addSeparator()
            act_reload = menu.addAction(self.t("lang.reload"))
            act_reload.triggered.connect(lambda checked=False: self._reload_languages())
        except RuntimeError:
            return  # Qt teardown — the menu is already destroyed
        # The rebuilt QActions own no QMenu themselves, but the guard must follow the
        # submenu contents (the palette walks the menus with temporary wrappers).
        self._rebuild_qaction_guard()

    def _reload_languages(self):
        """"Rescan the language files" (v1.3.3.1, ROADMAP task 3).

        Re-reads the ACTIVE language file (so an edited `i18n/<code>.json` is picked
        up without a restart) and re-texts the UI — an action switcher that did not
        exist before: the file list was only re-read by the menu rebuild. A file that
        disappeared is reported in the status bar; the current language keeps working
        from memory. Never raises.
        """
        try:
            from i18n import reload_current_language as _reload
            ok = bool(_reload())
        except Exception as e:  # noqa: BLE001 — a broken file must not break the window
            if self.log:
                self.log.warning(f"i18n language reload failed: {e}")
            ok = False
        if ok:
            self._apply_ui_translations()
            self._update_window_title()
        try:
            self.statusBar().showMessage(
                self.t("status.language_reloaded") if ok else self.t("lang.switch_failed"))
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        if self.log:
            self.log.info(f"i18n language files rescanned (active={self.current_language!r}, ok={ok})")

    # ── v1.4rc1 (plugin foundation, rc series): the "Plugins" menu ──────────────
    # The manager (modules/plugin_manager.py) reports FACTS — records and events; the
    # window turns them into a menu and into status-bar lines. This is the rc1 half of
    # the frozen API v1 contract (PLUGINS.md): discovery + manager + the enable/disable
    # switch. The hooks themselves (commands, the context menu, status probes, running
    # on selected servers) are rc2/rc3 — nothing here calls into a plugin.

    def start_plugin_discovery(self):
        """Discover the plugins — called ONCE from main.py, after show(), before app.exec().

        The ROADMAP places the discovery exactly there: the window exists (so a load
        error can be reported in its status bar) while the event loop has not started
        yet (so the registry is complete before the first frame the user sees). Never
        raises: a plugin must not be able to break the startup (ROADMAP rc1 task 1).
        """
        try:
            self._plugin_manager.discover()
        except Exception as e:  # noqa: BLE001 — the discovery is wrapped internally too
            if self.log:
                self.log.warning(f"Plugin discovery failed: {e}")
        self._populate_plugin_items()
        self._report_plugin_events()
        if self.log:
            self.log.info(f"Plugins: {len(self._plugin_manager.loaded_records())} loaded "
                          f"of {len(self._plugin_manager.records())} discovered")

    def _reload_plugins(self):
        """`Plugins → Reload` (a registry action): re-run the discovery and re-render.

        This is what makes a dropped-in `~/.sshmap/plugins/<name>.py` usable without a
        restart — every folder plugin is exec'd fresh (a changed file is really re-read).
        """
        try:
            self._plugin_manager.reload()
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Plugin reload failed: {e}")
        self._populate_plugin_items()
        self._report_plugin_events()

    def _populate_plugin_items(self):
        """(Re)build the per-plugin rows of the "Plugins" menu from the manager's records.

        Called at construction and on every `aboutToShow` (the v1.3.3.1 pattern: the
        list is never frozen at construction). Only the DYNAMIC rows are removed —
        `_plugin_rows` holds them, so the permanent "Run"/"Reload" items and their
        separator survive every rebuild. An error record is shown too: disabled and
        unchecked, with the failure in its tooltip (the user must see that the file was
        found and why it did not load). With no records at all — a disabled placeholder
        naming the folder, so the feature is discoverable. Never raises.

        v1.4rc3: the pass also (a) re-feeds the plugin node registry (the same narrowing
        the startup discovery does, so a node added later is visible to `run_on_nodes`)
        and (b) enables "Run on selected servers" only while a plugin implements the hook
        — otherwise the item would be a silent no-op.
        """
        self._sync_plugin_nodes()
        menu = getattr(self, "_plugin_menu", None)
        if menu is None:
            return
        try:
            for act in self._plugin_rows:
                menu.removeAction(act)          # exactly the rows of the previous build
            self._plugin_rows = []
            before = self._plugin_sep if self._plugin_sep is not None else self.act_plugins_reload
            records = self._plugin_manager.records()
            run_records = [r for r in records
                           if plugin_manager.HOOK_RUN_ON_NODES in r.hooks]
            if not records:
                placeholder = QAction(self.t("plugins.empty"), menu)
                placeholder.setEnabled(False)   # informative, not a command
                menu.insertAction(before, placeholder)
                self._plugin_rows.append(placeholder)
            else:
                for rec in records:
                    act = QAction(rec.label(), menu)
                    act.setCheckable(True)
                    act.setChecked(rec.ok)
                    act.setToolTip(self._plugin_tooltip(rec))
                    try:  # v1.4rc3: the puzzle glyph (a menu of plugins reads as one family)
                        set_action_icon(act, "plugin")  # v1.4.3-fix: follows the theme too
                    except Exception:  # noqa: BLE001 — the icon is cosmetic
                        pass
                    if rec.failed:
                        act.setEnabled(False)   # found, but not loadable — nothing to switch
                    else:
                        act.toggled.connect(
                            lambda checked, pid=rec.plugin_id: self._on_plugin_toggled(pid, checked))
                    menu.insertAction(before, act)
                    self._plugin_rows.append(act)
                if run_records and not self._plugin_manager.node_records():
                    # v1.4rc3: a plugin-ready action with no nodes to act on — say so
                    # instead of leaving a disabled item without a reason.
                    hint = QAction(self.t("plugins.run_hint"), menu)
                    hint.setEnabled(False)
                    menu.insertAction(before, hint)
                    self._plugin_rows.append(hint)
            # The permanent "Run" item follows the plugins that can serve it AND the
            # registry it would act on — an enabled item with no servers in the plugin
            # registry can only answer "nothing to run on".
            run_act = getattr(self, "act_plugins_run", None)
            if run_act is not None:
                run_act.setEnabled(bool(run_records)
                                   and bool(self._plugin_manager.node_records()))
        except RuntimeError:
            return  # Qt teardown — the menu is already destroyed
        # The rebuilt rows are QActions of a menu that the palette walks with temporary
        # wrappers (gotcha #9) — keep them in the guard like the language submenu's children.
        self._rebuild_qaction_guard()

    def _sync_plugin_nodes(self):
        """v1.4rc3: refresh the plugin-visible node registry from the CURRENT map.

        The startup discovery (`start_plugin_discovery`) feeds the registry once; a
        project opened or edited afterwards would otherwise leave a plugin looking at a
        stale map (an empty one at startup). The pass is cheap, idempotent and runs on
        every "Plugins" menu open — the same place the palette takes its records from.
        The internal `key_path` FACTS travel separately (the credential resolver of
        `ctx.run_command` needs them, a plugin never sees them). Never raises.
        """
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return
        facts = {}
        for node in nodes:
            key_path = getattr(node.data, "key_path", "") or ""
            if key_path:
                facts[node.data.id] = {"key_path": key_path}
        try:
            self._plugin_manager.set_nodes([n.data for n in nodes], facts=facts)
        except Exception as e:  # noqa: BLE001 — a plugin registry must never break the menu
            if self.log:
                self.log.warning(f"Plugin node registry refresh failed: {e}")
        # The registry may have just become EMPTY (the last node removed, a new project):
        # the "Run on selected servers" item must follow immediately, or the user keeps an
        # enabled item that can only answer "nothing to run on" (every refresh_sidebar
        # path lands here, the menu open included).
        run_act = getattr(self, "act_plugins_run", None)
        if run_act is not None:
            try:
                run_act.setEnabled(bool(self._plugin_manager.node_records())
                                   and bool(self._plugin_records_with_hook(
                                       plugin_manager.HOOK_RUN_ON_NODES)))
            except RuntimeError:
                pass  # Qt teardown

    def _plugin_records_with_hook(self, hook_name: str) -> list:
        """The loaded plugins that declare a hook ([] — no plugin, no hook)."""
        try:
            return [r for r in self._plugin_manager.loaded_records() if hook_name in r.hooks]
        except Exception:  # noqa: BLE001 — a broken manager must not break a context menu
            return []

    def _extend_node_context_menu(self, menu, node=None):
        """v1.4rc3 (ROADMAP task 7): let every plugin add rows to a node context menu.

        The ONE entry point behind both surfaces of the contract ("the node context menu
        of the map or of the sidebar", PLUGINS.md §3): the caller passes the live QMenu
        and either the clicked `ServerNode` (map) or its node id (sidebar); the manager
        narrows whatever it gets to the frozen `{id, alias, host, port, user}` records.

        The hooks run synchronously on the GUI thread inside the contract's 200 ms budget
        and are wrapped by the manager ("never throws"): a plugin that raises contributes
        nothing and is reported, the menu still opens. The QActions a plugin created are
        the manager's to keep alive, so the guard is re-run right after the call
        (gotcha #9: a dead Python QAction wrapper takes the C++ menu down with it).

        Returns the number of plugins asked. Never raises.
        """
        if menu is None:
            return 0
        asked = 0
        try:
            asked = int(self._plugin_manager.plugin_node_context_menu(menu, node))
        except Exception as e:  # noqa: BLE001 — a plugin must not be able to kill the menu
            if self.log:
                self.log.warning(f"Plugin context menu hook failed: {e}")
        if asked:
            # The rows a plugin created live in a menu built outside the i18n registry:
            # keep their wrappers in the guard (gotcha #9), then re-run the rebuild so the
            # two sources end up in one list. A context menu of a window without plugins
            # pays for none of this.
            try:
                self._plugin_menu_actions.extend(list(menu.actions()))
                if len(self._plugin_menu_actions) > 200:      # bounded: context menus are ephemeral
                    del self._plugin_menu_actions[:-100]
            except RuntimeError:
                pass  # the menu died under us — nothing to guard
            self._rebuild_qaction_guard()
        return asked

    def _run_plugins_on_nodes(self):
        """v1.4rc3 (task 8): "Run on selected servers" — the `run_on_nodes` hook.

        Scope: the CURRENT selection; with nothing selected the whole map is the target
        (the action stays useful, and the status line says which scope was used). The
        manager starts one managed worker per plugin that declares the hook — the work
        itself (`ctx.run_command`) runs on its own managed workers, so nothing blocks the
        GUI thread (PLUGINS.md §6). The status line reports how many plugins started and
        on how many nodes; a plugin reports its own results through `ctx.status()`.

        Never raises: a broken plugin is a log line + a status report, and the action
        with no capable plugin is a no-op (the menu item is disabled in that case).
        """
        try:
            nodes = list(self.selected_nodes())
        except Exception:  # noqa: BLE001 — a selection problem must not break the action
            nodes = []
        try:
            if nodes:
                started = int(self._plugin_manager.plugin_run_on_nodes(nodes))
            else:
                started = int(self._plugin_manager.plugin_run_on_nodes(None))
            if started:
                # The scope really used: the selection, or the whole map when there is
                # none — the count comes from what the plugins were actually given.
                count = len(nodes) if nodes else len(self._plugin_manager.node_records())
                self.statusBar().showMessage(
                    self.t("plugins.status.run_on_nodes", count=count), 8000)
            else:
                # Nothing could run: no node in the plugin registry (an unsaved map) or
                # no plugin implementing the hook — the status line says which. The
                # `plugins.run_hint` wording is reused deliberately (one key, one fact:
                # "add a server to use plugin commands on nodes").
                self.statusBar().showMessage(
                    self.t("plugins.no_selection")
                    if not self._plugin_manager.node_records()
                    else self.t("plugins.run_hint"), 8000)
        except Exception as e:  # noqa: BLE001 — an action must never crash the window
            if self.log:
                self.log.warning(f"Plugin run_on_nodes failed: {e}")

    def _plugin_tooltip(self, rec) -> str:
        """The tooltip of one plugin row: the version + the description, or the failure.

        The plugin's own strings (name/version/description) are the author's text — they
        are NOT i18n keys (the frozen contract: plugin strings stay outside the parity
        policy, `PLUGINS.md`). Only the failure sentence is translated.
        """
        if rec.failed:
            return self.t("plugins.status.error",
                          name=rec.label(), error=rec.detail or rec.error)
        text = f"v{rec.version}" if rec.version else ""
        if rec.description:
            text = f"{text} — {rec.description}" if text else rec.description
        return text

    def _on_plugin_toggled(self, plugin_id: str, enabled: bool):
        """The enable/disable switch of one plugin row (persisted in config.json)."""
        try:
            ok = bool(self._plugin_manager.set_enabled(plugin_id, enabled))
        except Exception as e:  # noqa: BLE001 — a switch must not break the window
            ok = False
            if self.log:
                self.log.warning(f"Plugin switch failed for {plugin_id!r}: {e}")
        if not ok:
            # The model did not move (an unknown id / a failed plugin) — put the checkbox
            # back to the state the manager really holds instead of leaving a lie on screen.
            self._populate_plugin_items()
            return
        self._report_plugin_events()

    def _report_plugin_events(self):
        """Turn the manager's events into status-bar lines (ROADMAP rc1: loaded/error/disabled).

        One line per event, in order (a QStatusBar keeps the last one); when the round
        carried an ERROR it is re-shown at the end, so a broken plugin stays the visible
        message instead of being overwritten by the round report. The "loaded" line is
        shown only for a RELOAD round — at startup the menu already says what is on and
        a status line per plugin would outlive its own usefulness. Never raises.
        """
        try:
            events = self._plugin_manager.drain_events()
        except Exception:  # noqa: BLE001
            return
        if not events:
            return
        lines = []                # [(text, timeout_ms)]
        first_error = None
        reloading = any(ev.get("kind") == plugin_manager.EVENT_RELOADED for ev in events)
        for ev in events:
            kind, rec = ev.get("kind"), ev.get("record")
            if kind == plugin_manager.EVENT_ERROR and rec is not None:
                text = self.t("plugins.status.error",
                              name=rec.label(), error=rec.detail or rec.error)
                first_error = first_error or (text, 10000)
                lines.append((text, 10000))
            elif kind == plugin_manager.EVENT_LOADED and rec is not None and reloading:
                lines.append((self.t("plugins.status.loaded", name=rec.label()), 5000))
            elif kind == plugin_manager.EVENT_ENABLED and rec is not None:
                lines.append((self.t("plugins.status.enabled", name=rec.label()), 5000))
            elif kind == plugin_manager.EVENT_DISABLED and rec is not None:
                lines.append((self.t("plugins.status.disabled", name=rec.label()), 5000))
            elif kind == plugin_manager.EVENT_HOOK_ERROR:
                # v1.4rc2: a hook that raised — drained from the queue (the signal path
                # has already shown it live; a drain must not lose it either).
                pid = rec.plugin_id if rec is not None else ""
                lines.append((self.t("plugins.status.hook_failed",
                                     name=self._plugin_label(pid),
                                     hook=str(ev.get("hook", "")),
                                     error=str(ev.get("error", ""))), 10000))
            elif kind == plugin_manager.EVENT_HOOK_TIMEOUT:
                # v1.4rc2: a hook that was abandoned after its budget.
                pid = rec.plugin_id if rec is not None else ""
                lines.append((self.t("plugins.status.hook_timeout",
                                     name=self._plugin_label(pid),
                                     hook=str(ev.get("hook", "")),
                                     ms=int(ev.get("budget_ms", 0))), 10000))
            elif kind == plugin_manager.EVENT_RELOADED:
                lines.append((self.t("plugins.status.reloaded", count=int(ev.get("count", 0))), 5000))
        if not lines:
            return
        if first_error is not None:
            lines.append(first_error)   # a failure must be the message that stays
        try:
            for text, timeout in lines:
                self.statusBar().showMessage(text, timeout)
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed

    def _plugin_label(self, plugin_id: str) -> str:
        """The display name of a plugin id (the id itself when the record is gone)."""
        try:
            rec = self._plugin_manager.get(plugin_id)
            if rec is not None:
                return rec.label()
        except Exception:  # noqa: BLE001
            pass
        return plugin_id or "?"

    def _on_plugin_status_requested(self, plugin_id: str, text: str, timeout_ms: int):
        """v1.4rc2: `ctx.status()` — a status-bar line with the TOKEN GUARD.

        A plugin may call this from a worker thread (the manager's signal carries it to
        the GUI thread). The guard is the v1.2.2 pattern of the dock's status line: every
        message takes a fresh token and the pending auto-clear of an older one is
        invalidated, so a slow asynchronous result can never blank a newer message.
        """
        try:
            message = str(text)
            if not message:
                return
            token = next(self._plugin_status_tokens)
            self._plugin_status_token = token
            self.statusBar().showMessage(message, max(0, int(timeout_ms)))
            if int(timeout_ms) > 0:
                QTimer.singleShot(int(timeout_ms), lambda tk=token: self._expire_plugin_status(tk))
        except (RuntimeError, TypeError, ValueError):
            pass  # Qt teardown / a broken timeout — a plugin line must never break the UI

    def _expire_plugin_status(self, token):
        """The auto-clear of a plugin status line — only if nothing newer arrived."""
        try:
            if token == self._plugin_status_token:
                self.statusBar().clearMessage()
        except RuntimeError:
            pass  # Qt teardown

    def _on_plugin_hook_failed(self, plugin_id: str, hook_name: str, detail: str):
        """v1.4rc2: a hook raised — the user hears about it (the contract's "never throws")."""
        try:
            self.statusBar().showMessage(
                self.t("plugins.status.hook_failed", name=self._plugin_label(plugin_id),
                       hook=hook_name, error=detail), 10000)
        except (RuntimeError, AttributeError):
            pass

    def _on_plugin_hook_timeout(self, plugin_id: str, hook_name: str, budget_ms: int):
        """v1.4rc2: a hook was abandoned after its budget — the app keeps living."""
        try:
            self.statusBar().showMessage(
                self.t("plugins.status.hook_timeout", name=self._plugin_label(plugin_id),
                       hook=hook_name, ms=int(budget_ms)), 10000)
        except (RuntimeError, AttributeError):
            pass

    def _setup_command_palette(self):
        """v0.9.2: create the command palette and the Ctrl+K hotkey."""
        try:
            from ui.command_palette import CommandPalette
        except ImportError:  # flat launch from the project root
            from command_palette import CommandPalette
        self._command_palette = CommandPalette(self, self)

        # v1.3.2 (task 1): the sequence comes from the hotkey registry ("palette.open",
        # Ctrl+K by default) — the QShortcut is created empty and registered as a target.
        from PySide6.QtGui import QShortcut, QKeySequence
        self._palette_shortcut = QShortcut(QKeySequence(), self)
        self._palette_shortcut.activated.connect(self._open_command_palette)
        self._register_hotkey_target("palette.open", self._palette_shortcut)

    def _open_command_palette(self):
        if getattr(self, "_command_palette", None) is not None:
            self._command_palette.open_palette()

    def _iter_server_nodes(self):
        """All ServerNodes in the scene (for collapse/expand all)."""
        scene = getattr(self, "scene", None)
        if scene is None:
            return []
        try:
            return [it for it in scene.items()
                    if isinstance(it, ServerNode)]
        except Exception:
            return []

    def _set_all_collapsed(self, collapsed: bool):
        """v0.8.4: collapse/expand all plaques; the state is saved into the project."""
        changed = False
        for node in self._iter_server_nodes():
            if bool(getattr(node.data, "collapsed", False)) != collapsed:
                node.toggle_collapsed()
                changed = True
        if changed:
            self._mark_dirty()

    def _collapse_all_servers(self):
        self._set_all_collapsed(True)

    def _expand_all_servers(self):
        self._set_all_collapsed(False)

    # ── v1.2.4.1 (ROADMAP v1.2.4.1): ONE "collapse into a thin strip" mechanism ──
    # The three control points of each panel (corner button, strip click,
    # "View" menu item) all go through one checkable QAction: a Qt click inverts checked itself,
    # buttons/strips call action.toggle() — all paths emit toggled(bool) into the slots below.

    def _toggle_sidebar(self, checked: bool = True):
        """v1.1.1 (item 5) -> v1.2.4.1: compatibility — checked = expanded.

        Before: setVisible on the whole sidebar (a single widget in the QSplitter). Now:
        an expanded<->collapsed toggle — a collapsed sidebar does not lose its data
        (search/tag filter/tree survive, refresh_sidebar works); in its place
        is a ~18px strip.
        """
        if self._set_panel_collapsed("sidebar", not checked) == "forbidden":
            self._reject_collapse_both("sidebar")

    def _on_sidebar_toggled(self, checked: bool):
        """v1.2.4.1: menu item "View -> Sidebar" (toggled; checked = expanded)."""
        if self._set_panel_collapsed("sidebar", not checked) == "forbidden":
            self._reject_collapse_both("sidebar")

    def _on_map_toggled(self, checked: bool):
        """v1.2.4.1: menu item "View -> Map" (toggled; checked = expanded)."""
        if self._set_panel_collapsed("map", not checked) == "forbidden":
            self._reject_collapse_both("map")

    def _reject_collapse_both(self, which: str):
        """v1.2.4.1-fix (QA request): refuse to collapse the SECOND panel.

        All three control paths converge on a checkable QAction, and on refusal Qt has
        already inverted checked (or a programmatic setChecked did) — the checkbox is
        restored to the actual state with signals blocked (the
        v1.2.4-fix pattern: the checkbox and the mechanism stay in sync) + a status-bar hint.
        """
        act = getattr(self, "act_show_sidebar" if which == "sidebar" else "act_show_map", None)
        if act is not None:
            try:
                act.blockSignals(True)
                act.setChecked(True)  # the panel stays expanded
            finally:
                act.blockSignals(False)
        # v1.4.6: the toolbar mirror was told by `toggled` — and that signal is blocked
        # on this path, so it has to be told explicitly (a refused collapse must not
        # leave the toolbar button showing a state the window is not in).
        self._sync_view_toolbar(
            "view.toggle_sidebar" if which == "sidebar" else "view.toggle_map", True)
        try:
            self.statusBar().showMessage(self.t("status.collapse_both_forbidden"))
        except Exception:  # noqa: BLE001 — the hint must not break the refusal
            pass

    def _set_panel_collapsed(self, which: str, collapsed: bool) -> str:
        """v1.2.4.1 (task 1): collapse/expand the sidebar or the map into a strip.

        `which` — "sidebar" | "map"; `collapsed` — the target state (True = strip).
        Idempotent: a no-op if the panel is already in the target state (toggled/trigger
        may arrive again). In the collapsed state the real widget is hidden (a hidden
        container child takes 0px — native Qt); a clickable strip is shown; the container
        width is fixed by setSizes + minimumWidth=18. On expand
        the panel's OWN width from BEFORE the collapse is restored (saved on the
        first collapse of the current cycle); if the other panel is also collapsed — it
        stays a strip (18px) and the expanded one takes the rest of the space. The state
        is persistent: ui_sidebar_collapsed / ui_map_collapsed in config.json
        (a merge-write via i18n.save_config) — it survives a restart.

        v1.2.4.1-fix (QA request): both panels SIMULTANEOUSLY collapsed are
        NOT ALLOWED — at least one (the sidebar or the map) is always expanded, otherwise
        the window is a "shell" of two strips (even with the "Terminals" dock open).
        Collapsing the second panel is forbidden for ALL control paths (button/strip/menu/
        programmatic setChecked — they all converge on toggled). Returns "changed" / "noop" / "forbidden".

        v1.4.5 (ROADMAP task 5): the collapsed container is capped at the strip width
        (`setMaximumWidth`) and the divider handle is DISABLED while a panel is a strip —
        the drift fix (a collapsed container used to be pinned only by `minimumWidth`,
        so the handle could stretch it into empty space). Both invariants are applied by
        `_sync_splitter_handle()` at the END of this method, so every control path and
        every resize source (handle, window resize, dock, state restore) agrees.

        v1.4.6 (ROADMAP task 2): the MAP's collapsedness is also the LIST MODE — the
        sidebar container is the full window width in that state, and the tree fills it
        with the server parameters (`sidebar.list.*`, see `_sync_list_mode()`). The
        trigger is deliberately this method and not the QAction: the diamond, the strip,
        the menu item, the startup config, the settings dialog and the splitter restore
        all converge here. The state stays `ui_map_collapsed` in config.json — the mode
        IS the collapsedness, so nothing new has to be persisted.
        """
        if which == "sidebar":
            panel, strip = self.sidebar, self._sidebar_strip
            container = self._sidebar_container
            key, flag_attr = "ui_sidebar_collapsed", "_sidebar_collapsed"
            min_w = self.SIDEBAR_MIN_WIDTH
            other_flag = "_map_collapsed"
        elif which == "map":
            panel, strip = self.view, self._map_strip
            container = self._map_container
            key, flag_attr = "ui_map_collapsed", "_map_collapsed"
            min_w = self.MAP_MIN_WIDTH
            other_flag = "_sidebar_collapsed"
        else:
            return "noop"
        if getattr(self, flag_attr) == bool(collapsed):
            self._sync_splitter_handle()
            self._sync_list_mode()
            return "noop"  # already in the target state — a no-op
        if collapsed and getattr(self, other_flag, False):
            self._sync_splitter_handle()
            self._sync_list_mode()
            return "forbidden"  # the other panel is already a strip — both cannot be collapsed

        try:
            w_strip = _CollapseStrip.STRIP_WIDTH
            sizes = self._splitter.sizes()
            own_w = sizes[0] if which == "sidebar" else sizes[1]
            if collapsed:
                saved_attr = f"_saved_panel_width_{which}"
                # Save the width only if the other panel is expanded: otherwise the "own"
                # width is overstated (the other is a 18px strip) and restoring it on the
                # second expand would squeeze the first to its minimum. Without the save —
                # the 250/950 default on expand (a sensible fallback).
                if getattr(self, saved_attr, None) is None \
                        and not getattr(self, other_flag, False):
                    setattr(self, saved_attr, int(own_w))  # the width BEFORE collapsing
                panel.hide()
                strip.show()
                self._apply_collapsed_strip_sizes(which)
            else:
                container.setMinimumWidth(min_w)
                panel.show()
                strip.hide()
                saved = getattr(self, f"_saved_panel_width_{which}", None)
                setattr(self, f"_saved_panel_width_{which}", None)
                total = max(self._splitter.width(), 2 * w_strip + 10)
                x_w = int(saved) if saved else (250 if which == "sidebar" else 950)
                if getattr(self, other_flag, False):
                    # the other panel is collapsed — it stays a strip (the 18px invariant)
                    if which == "sidebar":
                        self._splitter.setSizes([x_w, w_strip])
                    else:
                        self._splitter.setSizes([w_strip, x_w])
                else:
                    if which == "sidebar":
                        self._splitter.setSizes([x_w, total - x_w])
                    else:
                        self._splitter.setSizes([total - x_w, x_w])
        except RuntimeError:
            self._sync_splitter_handle()
            self._sync_list_mode()
            return "noop"  # Qt teardown — the C++ object is already destroyed

        setattr(self, flag_attr, bool(collapsed))
        # v1.4.5 (ROADMAP task 5): the width caps (the collapsed one is exactly a strip
        # wide) and the handle's enabled state — ONE place, every control path.
        self._sync_splitter_handle()
        # v1.4.6 (ROADMAP task 2): the map's collapsedness IS the list mode — the
        # sidebar switches to the wide table (and back) from this one place.
        self._sync_list_mode()
        try:
            from i18n import save_config as _save_cfg
            _save_cfg({key: bool(collapsed)})
        except Exception:  # noqa: BLE001 — persistence must not break the toggle
            pass
        return "changed"

    def _sync_splitter_handle(self) -> None:
        """v1.4.5 (ROADMAP task 5): the 18px invariant + the divider's affordance.

        The drift this fixes: a collapsed container was pinned only by `minimumWidth`,
        which is a HINT to the QSplitter — dragging the handle (or an external resize
        of the window/dock) stretched the strip into empty space while the mechanics
        (`_sidebar_collapsed`/`_map_collapsed`) kept saying "collapsed", and the panel
        widths diverged from the saved state.

        Two things are enforced here, for BOTH panels symmetrically:

          * **the width cap** — a collapsed container gets
            `setMaximumWidth(_CollapseStrip.STRIP_WIDTH)`, an expanded one releases it
            (`_WIDGET_MAX_WIDTH`). Any resize source then has exactly one possible
            outcome: the expanded panel takes the whole delta and the strip stays 18 px;
          * **the affordance** — `splitter.handle(0)` is ENABLED only while BOTH panels
            are expanded (there is nothing to resize otherwise), with a tooltip that
            says so. Applied at the end of `_set_panel_collapsed` (all control paths
            converge there), after the collapse state is applied from the config and
            after the splitter state is restored.
        """
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        try:
            both_expanded = (not getattr(self, "_sidebar_collapsed", False)
                             and not getattr(self, "_map_collapsed", False))
            handle = splitter.handle(0)
            if handle is not None:
                handle.setEnabled(both_expanded)
                handle.setToolTip(self.t("view.splitter_handle_tooltip"))
            for flag, container in (("_sidebar_collapsed", getattr(self, "_sidebar_container", None)),
                                    ("_map_collapsed", getattr(self, "_map_container", None))):
                if container is None:
                    continue
                if getattr(self, flag, False):
                    container.setMaximumWidth(_CollapseStrip.STRIP_WIDTH)
                else:
                    container.setMaximumWidth(_WIDGET_MAX_WIDTH)
        except RuntimeError:
            pass  # Qt teardown — the splitter or a container is already destroyed

    def _sync_list_mode(self) -> None:
        """v1.4.6 (ROADMAP task 2): the map's collapsedness IS the sidebar's LIST mode.

        With the map collapsed the sidebar container takes the whole window width
        (QSplitter redistributes), so `SidebarPanel.set_list_mode(True)` turns the tree
        into the table of server parameters — and back on expansion. This is the ONE
        reader of the collapse flag for the layout: the panel owns WHAT the list looks
        like, this method only reports the state (never the reverse).

        Idempotent and cheap by construction: `set_list_mode()` answers False when the
        layout already matches, so the repeated calls from the collapse control paths,
        the startup config and the settings dialog never rebuild the tree twice. Only a
        REAL switch refreshes the rows (`refresh_sidebar()` — the one composition hook
        every add/remove/import/load/undo already passes through).

        v1.5.5 (ROADMAP task 2): the two INVENTORY actions follow the mode. "Copy List" and
        "Export List…" report the TABLE, so they are enabled exactly while the table exists
        — a disabled item (the `act_backups` pattern for "no project is open") is the honest
        affordance for "there is no list on screen right now"; the enable state is applied on
        EVERY call, not only on a real switch, because the actions are built after the first
        `_sync_list_mode()` of the startup path.
        """
        panel = getattr(self, "sidebar", None)
        if panel is None:
            return
        try:
            list_mode = bool(getattr(self, "_map_collapsed", False))
            for action in (getattr(self, "act_copy_list", None),
                           getattr(self, "act_export_list", None)):
                if action is not None:
                    action.setEnabled(list_mode)
            if panel.set_list_mode(list_mode):
                self.refresh_sidebar()
        except RuntimeError:
            pass  # Qt teardown — the panel or its tree is already destroyed

    def _apply_collapsed_strip_sizes(self, which: str) -> None:
        """Force the [strip | expanded panel] sizes of a COLLAPSED panel.

        v1.2.4.1 had this arithmetic inline in `_set_panel_collapsed`; v1.3.3.6
        (ROADMAP task 4) reuses it after the splitter-state restore, so a saved layout
        can never resurrect the width of a panel the user collapsed before closing the
        window. The caller guarantees the OTHER panel is expanded (collapsing both is
        forbidden — `_set_panel_collapsed` returns "forbidden").

        v1.4.5 (ROADMAP task 5): the collapsed container is ALSO capped at the strip
        width (`setMaximumWidth`) — with only `minimumWidth` + `setSizes` a later
        resize (the window, the dock, the handle) could stretch the strip again, which
        is exactly the drift this release fixes.
        """
        w_strip = _CollapseStrip.STRIP_WIDTH
        container = self._sidebar_container if which == "sidebar" else self._map_container
        container.setMinimumWidth(w_strip)
        container.setMaximumWidth(w_strip)
        total = max(self._splitter.width(), 2 * w_strip + 10)
        if which == "sidebar":
            self._splitter.setSizes([w_strip, total - w_strip])
        else:
            self._splitter.setSizes([total - w_strip, w_strip])

    def _apply_splitter_state_from_config(self) -> None:
        """v1.3.3.6 (ROADMAP task 4): restore the panel widths — applied LAST.

        The ORDER is the contract (the v1.4.5 splitter-handle rules build on it):
        this runs AFTER `restore_window_geometry()`/`restoreState()` (early in
        `__init__`) and AFTER the collapsed-panel states applied by
        `_apply_ui_options_from_config()`, and it re-applies the 18px strip sizes of
        every panel that is collapsed — a saved layout must not resurrect a width the
        user collapsed away.

        A missing key / a broken value leaves the 250/950 defaults of `_setup_ui`
        untouched (`restore_splitter_state` returns False and never raises).

        v1.4.5 (ROADMAP task 5): the width caps and the handle's enabled state are
        re-applied afterwards in EVERY case (a restored layout must not re-enable a
        divider next to a collapsed panel).

        v1.4.6 (ROADMAP task 2): the LIST mode is re-applied here too — the collapsed
        map may have come from the config (a restored layout never carries the mode),
        and the column set must already be the wide one when the first rows are built.
        """
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        try:
            if not restore_splitter_state("ui_splitter_state", splitter):
                return
            for which, flag in (("sidebar", "_sidebar_collapsed"),
                                ("map", "_map_collapsed")):
                if getattr(self, flag, False):
                    self._apply_collapsed_strip_sizes(which)
        except RuntimeError:
            pass  # Qt teardown — the splitter is already destroyed
        finally:
            self._sync_splitter_handle()
            self._sync_list_mode()

    def _position_map_collapse_btn(self):
        """v1.2.4.1 (task 2): the map collapse button — the right BOTTOM corner of the MapView.

        v1.2.4.1-fix (QA request): it used to be in the right TOP corner — now at the bottom
        (the diamond is "at the bottom" both before and after collapsing); the top is
        reserved for the minimap per the new discussions. Repositioned on resizeEvent
        (the MapView.resized signal: a window resize, a splitter-handle drag,
        a "Terminals" dock size change) and whenever a scrollbar appears or disappears
        (their `rangeChanged` — the viewPORT is what the corner is measured against).

        v1.5rc4 (ROADMAP task 7): the third rule of the floating-panel priority — the
        diamond is NEVER covered by a panel. The corner is where the legend (bottom-left,
        draggable) and the minimap (right, draggable, free position) can land on a narrow
        window; the button therefore probes a few candidate spots around the panel that
        covers the corner and takes the first one that is free. Nothing else moves: the
        USER's panel position always wins over the window's own button.

        v1.5.6 (customer request): the corner is the VIEWPORT's, not the view's. The view's
        own rect INCLUDES the frame and the scrollbars, so the button used to be drawn ON
        TOP of the sliders; `viewport().geometry()` already excludes both. The extra
        `COLLAPSE_BTN_RAISE` lifts it out of the very corner, so the two collapse buttons
        (the sidebar's bottom row and this overlay) sit at visibly different levels.
        """
        btn = getattr(self, "_map_collapse_btn", None)
        view = getattr(self, "view", None)
        if btn is None or view is None:
            return
        try:
            vp = view.viewport()
            corner = vp.geometry()          # the view's coordinates WITHOUT frame/scrollbars
            w, h = corner.width(), corner.height()
            if w <= 0 or h <= 0:
                return
            bw = max(btn.sizeHint().width(), 24)
            bh = max(btn.sizeHint().height(), 24)
            x = max(4, corner.right() + 1 - bw - self.COLLAPSE_BTN_MARGIN)
            y = max(4, corner.bottom() + 1 - bh - self.COLLAPSE_BTN_MARGIN
                    - self.COLLAPSE_BTN_RAISE)
            panels = self._overlay_panel_rects(view)
            if panels:
                for candidate in self._collapse_btn_candidates(x, y, bw, bh, w, h, panels):
                    if not any(candidate.intersects(rect) for rect in panels):
                        x, y = candidate.x(), candidate.y()
                        break
            btn.move(int(x), int(y))
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _overlay_panel_rects(self, view) -> list:
        """The live rectangles of the VISIBLE floating panels (v1.5rc4, task 7).

        The view's own coordinates (every panel is a child of `MapView`), in the order the
        priority rule cares about: the first-run hint first (it is the temporary one), then
        the search bar, the minimap, the legend and — since v1.5.4 — the filter plaque (a
        panel that only exists while a filter dims the map). A panel that is hidden —
        including the legend suppressed by the priority rule itself — contributes nothing.
        """
        rects = []
        for name in ("empty_state", "map_search", "minimap", "legend", "filter_plaque"):
            panel = getattr(self, name, None)
            if panel is None:
                continue
            try:
                if panel.isVisible() and panel.width() > 0 and panel.height() > 0:
                    rects.append(QRect(panel.geometry()))
            except (RuntimeError, AttributeError):
                continue
        return rects

    @staticmethod
    def _collapse_btn_candidates(x, y, bw, bh, view_w, view_h, panels) -> list:
        """The candidate spots for the collapse diamond, nearest-to-the-corner first.

        The default corner, then the free space LEFT of the panel covering it, then ABOVE
        it, then above-left. Bounded on purpose: a button that chases the panels around a
        tiny window is worse than a button that stays in its corner.
        """
        candidates = [QRect(int(x), int(y), int(bw), int(bh))]
        for rect in panels:
            if not rect.intersects(candidates[0]):
                continue
            candidates.append(QRect(int(rect.left() - bw - 8), int(y), int(bw), int(bh)))
            candidates.append(QRect(int(x), int(rect.top() - bh - 8), int(bw), int(bh)))
            candidates.append(QRect(int(rect.left() - bw - 8), int(rect.top() - bh - 8),
                                    int(bw), int(bh)))
        return [c for c in candidates
                if c.left() >= 0 and c.top() >= 0
                and c.right() <= max(int(view_w), 1) and c.bottom() <= max(int(view_h), 1)]

    def _switch_language(self, language_code: str):
        """Switch application language and re-apply to all UI elements."""
        try:
            from i18n import set_language as _set_lang
            
            # Set the new language
            success = _set_lang(language_code)
            
            if success:
                self.current_language = language_code

                # Translate the menus/toolbar/labels by the registered keys
                self._apply_ui_translations()

                # v0.9.8: the map search panel — the placeholder and counter in the new language
                _map_bar = getattr(self, "map_search", None)
                if _map_bar is not None:
                    try:
                        _map_bar.retranslate()
                    except Exception:  # noqa: BLE001 — the panel is cosmetic on teardown
                        pass

                # v1.4.2: the minimap panel — its tooltip is its only text
                _mini = getattr(self, "minimap", None)
                if _mini is not None:
                    try:
                        _mini.retranslate()
                    except Exception:  # noqa: BLE001 — the panel is cosmetic on teardown
                        pass

                # The window title (accounting for the project file and the [*] marker)
                self._update_window_title()

                # Mark the active language in the Language submenu.
                # v0.9.8 bugfix: do NOT walk via action.menu() — see _qaction_guard above:
                # temporary Python wrappers of QActions with an attached QMenu dropped the C++ menu
                # (PySide6 6.11). The submenu is taken straight from the i18n registry — safe.
                lang_menu = None
                for w, k in self._menu_i18n:
                    if k == "lang.menu":
                        lang_menu = w
                        break
                if lang_menu is not None:
                    try:
                        for sub in list(lang_menu.actions()):
                            if sub.data() is not None:
                                sub.setChecked(sub.data() == language_code)
                    except RuntimeError:
                        pass  # Qt teardown — the submenu is already destroyed; nothing to mark

                if self.log:
                    self.log.info(f"Language switched to {language_code}")
            else:
                QMessageBox.warning(self, self.t("msg.error_title"), 
                                   f"{self.t('lang.switch_failed')}: {language_code}")
        except Exception as e:
            if self.log:
                self.log.exception(f"Error switching language to {language_code}")

    # ── v1.1: the settings dialog (hub) — ROADMAP v1.1, tasks 1–7 ────────────────
    # ── v1.1.1: options around the hub — applied live without a restart ────────

    def _apply_ui_options_from_config(self):
        """v1.1.1: apply the ui_* options from config.json (at startup and after the dialog's OK).

        * UI font — QApplication.setFont (family/size; empty/0 = system);
          applied to the widgets without a restart (Qt recomputes fonts not
          set explicitly on each widget).
        * The sidebar button block — SidebarPanel.set_buttons_visible (the layout
          reflows itself); the whole sidebar is hidden separately — the "View" menu item.
        * The node double-click mode — the self._node_double_click_mode cache
          ("properties" the default | "connect" -> _run_ssh_connect).
        """
        try:
            from ui.settings_dialog import load_ui_settings as _load_ui
        except ImportError:  # flat launch from the project root
            from settings_dialog import load_ui_settings as _load_ui
        ui_cfg = _load_ui()

        family = ui_cfg["font_family"]
        size = ui_cfg["font_size"]
        if family or size is not None:
            try:
                app = QApplication.instance()
                if app is not None:
                    f = QFont(app.font())
                    if family:
                        f.setFamily(family)
                    if size is not None:
                        f.setPointSize(int(size))
                    app.setFont(f)
            except Exception as e:  # noqa: BLE001 — the font must not break startup/apply
                if self.log:
                    self.log.warning(f"Apply UI font failed: {e}")

        panel = getattr(self, "sidebar", None)
        if panel is not None:
            try:
                panel.set_buttons_visible(ui_cfg["show_sidebar_buttons"])
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed

        self._node_double_click_mode = ui_cfg["node_double_click"]

        # v1.2.4.1 (task 4): the panel collapse state from config.json —
        # ui_sidebar_collapsed / ui_map_collapsed. Applied at startup AFTER
        # restoreState() (the method is called in __init__ after restore_window_geometry)
        # and after the settings dialog's OK (idempotent: _set_panel_collapsed is a no-op
        # if the state matches). setChecked(False) emits toggled -> the mechanism.
        try:
            from i18n import load_config as _load_cfg
            _cfg = _load_cfg()
            for attr, key in (("act_show_sidebar", "ui_sidebar_collapsed"),
                              ("act_show_map", "ui_map_collapsed")):
                act = getattr(self, attr, None)
                if act is not None and bool(_cfg.get(key, False)):
                    act.setChecked(False)  # checked = expanded -> collapse
        except Exception as e:  # noqa: BLE001 — the state must not break startup/apply
            if self.log:
                self.log.warning(f"Apply panel collapsed states failed: {e}")

        # v1.4.5 (ROADMAP task 5): the divider's affordance follows the state — with
        # no panel collapsed this is the plain "both expanded" sync (the tooltip and
        # the released width caps), with one collapsed the handle is disabled.
        # v1.4.6 (ROADMAP task 2): and the sidebar follows the map — a map collapsed
        # by the saved state (or by the settings dialog) opens in LIST mode.
        self._sync_splitter_handle()
        self._sync_list_mode()

    def _open_settings_dialog(self):
        """v1.1: open the settings dialog (the QTabWidget hub) — the "Settings" menu and the ⚙ button."""
        try:
            from ui.settings_dialog import SettingsDialog
        except ImportError:  # flat launch from the project root
            from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        # Dialog signals -> window slots (the dialog knows nothing about MainWindow — the sidebar.py pattern):
        # applied — apply autosave/statuses live; language_changed — the same
        # path as the "Help -> Language" item (set_language + a full UI retranslate).
        dlg.applied.connect(self._apply_settings_from_dialog)
        dlg.language_changed.connect(self._switch_language)
        # v1.4.3 (ROADMAP task 6): the "Appearance" tab applies the theme LIVE —
        # the dialog emits the chosen Theme instance and the window owns the switch
        # (Cancel re-emits the theme the dialog opened with, so a rejected dialog
        # changes nothing).
        dlg.theme_changed.connect(self.apply_theme)
        dlg.exec()

    def _apply_settings_from_dialog(self):
        """v1.1: apply the saved settings live (after the dialog's OK).

        * Autosave — the QTimer right now (interval + start/stop per enabled);
        * Statuses — StatusChecker.set_interval/set_probe_timeout/set_max_parallel
          (the next round; v1.1.2 final: parallel probes, cap 1..64);
        * v1.1.1: the UI font (QApplication.setFont), the open terminal windows' font
          (widget.set_font — without a restart), the sidebar buttons, the double-click
          mode, redrawing the connection plaques (the "type on plaque" option);
        * The terminal (palette/history/close behavior) and the external terminal
          read the config at the next window creation/launch — no action needed;
        * v1.2.2: terminal_mode ("windows"|"tabs") — applied WITHOUT a restart
          "to new sessions": _spawn_terminal_window reads the key on every call;
          open windows/the dock live on as-is until closed (task 4) — no action.
        * v1.3.2: the configurable hotkeys — _apply_hotkeys() reinstalls the sequences
          of the registered QActions/QShortcuts (QAction.setShortcut /
          QShortcut.setKey) from the "hotkeys" key; the F12 multi-input rule is kept.
        * v1.4.3 (ROADMAP task 6): the APPEARANCE — the `theme` key of config.json
          is read back and applied through `apply_theme()` (the mode + the accent
          hue). The "Appearance" tab already applied it live while the dialog was
          open; this is what makes the OK authoritative (and what covers a config
          edited by hand between the two).
        """
        # v1.4.3 (ROADMAP task 6): the theme first — every other option below is
        # applied to widgets whose colours the switch may have just changed.
        # v1.5rc1: the motion flag travels in the SAME nested key, so it is
        # installed here as well (`apply_motion_setting` reads `theme.motion`).
        try:
            from ui.settings_dialog import (load_theme_settings, theme_from_settings,
                                            apply_motion_setting, apply_density_setting)
        except ImportError:  # flat launch from the project root
            try:
                from settings_dialog import (load_theme_settings, theme_from_settings,
                                             apply_motion_setting, apply_density_setting)
            except ImportError:
                load_theme_settings = theme_from_settings = apply_motion_setting = None
                apply_density_setting = None
        if load_theme_settings is not None:
            try:
                _saved_theme = load_theme_settings()
                self.apply_theme(theme_from_settings(_saved_theme))
                apply_motion_setting(_saved_theme)
                # v1.6 (ROADMAP task 2): the card density rides the same nested key —
                # installed before the repaint walk below so the cards follow it there.
                if apply_density_setting is not None:
                    apply_density_setting(_saved_theme)
            except Exception as e:  # noqa: BLE001 — the look must not break applying
                if self.log:
                    self.log.warning(f"Apply theme settings failed: {e}")
        try:
            from storage.autosave import get_autosave_settings as _get_as
            _as_cfg = _get_as()
            self._autosave_enabled = bool(_as_cfg.get("enabled", True))
            self._autosave_timer.setInterval(int(_as_cfg["interval_sec"]) * 1000)
            if self._autosave_enabled:
                self._autosave_timer.start()
            else:
                self._autosave_timer.stop()
        except Exception as e:  # noqa: BLE001 — the timer must not break applying
            if self.log:
                self.log.warning(f"Apply autosave settings failed: {e}")
        checker = getattr(self, "_status_checker", None)
        if checker is not None:
            try:
                from services.status_checker import get_status_settings as _get_st
                _st_cfg = _get_st()
                checker.set_interval(int(_st_cfg["interval_sec"]) * 1000)
                checker.set_probe_timeout(float(_st_cfg["probe_timeout_sec"]))
                # v1.1.2 final (task 2): the parallel-probe cap — from the next round
                checker.set_max_parallel(int(_st_cfg["max_parallel"]))
            except Exception as e:  # noqa: BLE001 — the statuses must not break applying
                if self.log:
                    self.log.warning(f"Apply status settings failed: {e}")

        # v1.1.1 (item 1): the UI font + the sidebar buttons + the double-click mode
        try:
            self._apply_ui_options_from_config()
        except Exception as e:  # noqa: BLE001 — the options must not break applying
            if self.log:
                self.log.warning(f"Apply UI options failed: {e}")

        # v1.3.2 (task 3): the configurable hotkeys — QAction.setShortcut / QShortcut.setKey
        # on the already existing objects: the new sequences work without a restart.
        try:
            self._apply_hotkeys()
        except Exception as e:  # noqa: BLE001 — the hotkeys must not break applying
            if self.log:
                self.log.warning(f"Apply hotkeys failed: {e}")

        # v1.1.1 (item 1): the terminal font — into the ALREADY OPEN sessions without a restart
        # (v1.2: the registry stores pages — page.widget)
        try:
            from modules.ssh_terminal import load_terminal_settings as _load_ts
        except ImportError:
            from ..modules.ssh_terminal import load_terminal_settings as _load_ts
        term_cfg = _load_ts()
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            for s in list(getattr(self, "_terminal_windows", [])):
                try:
                    s.widget.set_font(
                        family=term_cfg["font_family"],
                        size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)
                except (RuntimeError, AttributeError):
                    pass  # Qt teardown / a session without a widget — skip it

        # v1.1.1 (item 6): the "type on plaque" option — redraw the scene's connection labels
        try:
            for arrow in list(getattr(self.scene, "_arrows", [])):
                arrow.refresh_label()
        except Exception:  # noqa: BLE001 — the plaques are cosmetic on teardown
            pass

        try:
            self.statusBar().showMessage(self.t("status.settings_saved"))
        except Exception:  # noqa: BLE001 — teardown robustness
            pass

    # ─────────────────────────────────────────────

    def _on_node_double_click_direct(self, node: ServerNode):
        """Handle double-click on a node."""
        # v1.1.1 (item 4): the mode from the ui_node_double_click key — "connect" opens
        # the SSH login dialog right away (a faster duplicate of the "Connect via
        # SSH" checkbox in the properties, which is not broken); the default "properties" — the v1.1 behavior.
        if getattr(self, "_node_double_click_mode", "properties") == "connect":
            self._run_ssh_connect(node)
            return
        try:
            dlg = AddServerDialog(self, edit_data=node.data)
            if dlg.exec() == QDialog.Accepted:
                new_data = dlg.get_data()
                # v0.8.3: editing the server data — an undo command (the id is preserved!)
                new_data.id = node.data.id
                old_data = copy.deepcopy(node.data)
                from modules.undo_commands import CmdEditNodeData
                self._push_command(CmdEditNodeData(self, node, old_data, new_data))
                self.refresh_sidebar()
                # v0.7.1: host/port may have changed — update the check plan and
                # reset the status (the old one is no longer relevant)
                node.reset_status()
                self._sync_status_targets()
                if self.log:
                    self.log.info("Server updated", extra={"alias": new_data.alias})
                self.statusBar().showMessage(self.t("status.server_updated", alias=new_data.alias))
                self._mark_dirty()  # ← unsaved changes
                # v0.9.5.6: "Connect via SSH" from the properties — the data is already
                # applied to the node (CmdEditNodeData); open the SSH dialog
                # with the password prefilled from the property fields.
                if getattr(dlg, "_connect_after_accept", False):
                    self._run_ssh_connect(node, prefill_password=dlg.password.text())
        except Exception as e:
            if self.log:
                self.log.exception(f"Error updating server {node.data.alias}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.update_failed", error=str(e)))

    def _select_node(self, node: ServerNode, center: bool = False, smooth: bool = False):
        # v0.9.9.1: a reentry guard instead of scene.blockSignals — the other
        # selectionChanged slots keep working during the programmatic change; the echo
        # handler returns immediately on the flag, and the explicit sync below
        # is idempotent (a full state recompute, "tree = scene selection").
        self._selection_syncing = True
        try:
            self.scene.clearSelection()
            node.setSelected(True)
        finally:
            self._selection_syncing = False
        self._sync_selection_state()
        # v1.2.4.1 (task 5): the map is collapsed — centering is skipped (selection
        # and the accent still work; no exceptions and no auto-show of the map). All paths
        # are covered: "Show on map" (_reveal_node_on_map) and the search navigation Enter/Shift+Enter.
        if center and not getattr(self, "_map_collapsed", False):
            # v1.4.4 (ROADMAP task 2): `smooth=True` is the "Show on map" reveal — the camera
            # FLIES (ui/motion.py) instead of jumping; every other caller keeps the instant
            # centering (a search step and the palette want the result NOW, and their tests
            # compare the scroll state with a direct centerOn).
            if smooth and self._fly_camera_to_node(node):
                return
            self.view.stop_camera_flight()  # v1.4.4: an instant move cancels a running flight
            self.view.centerOn(node)

    # ── v1.4.4 (ROADMAP task 2): the camera flights ─────────────────────

    def _fly_camera_to_node(self, node: "ServerNode") -> bool:
        """Fly the camera to a node's CARD centre, keeping the current zoom (True — flying).

        The reveal is a "here it is", not a zoom change: the target SCALE is the live one,
        so the flight is a pure pan. The anchor is `card_rect_scene()` (the card without
        the v1.4.2 shadow halo) — the v1.4.2 rule for every consumer of a node's edge.
        """
        try:  # v1.4.4: the motion standards (ui/motion.py)
            from ui.motion import fly_camera
        except ImportError:  # flat launch from the project root
            try:
                from motion import fly_camera
            except ImportError:
                return False
        getter = getattr(node, "card_rect_scene", None)
        try:
            rect = getter() if callable(getter) else node.sceneBoundingRect()
        except (RuntimeError, AttributeError):
            return False
        return fly_camera(self.view, self.view.zoom, rect.center()) is not None

    def _on_hover_focus_changed(self, _arrow=None):
        """v1.4.4 (ROADMAP task 4): the arrow hover focus moved — recompute the ONE dim state.

        The arrow's hover is a REASON to re-evaluate the map, never a second writer of the
        dim: `_apply_map_dimming` merges the hover focus with the tag filter and the search.
        """
        self._apply_map_dimming()

    def _sync_selection_state(self):
        # v0.9.9.1: reentry guard — while the programmatic selection change is in flight,
        # the echo of our own signals returns immediately (no recursion); the explicit call
        # after the change does a full idempotent recompute, so an external
        # change inside the sync window is not lost — the next alignment converges.
        if getattr(self, "_selection_syncing", False):
            return
        try:
            selected_node = self.scene.get_selected_node()
            # v0.9.3: multi-selection — a selection frame on EVERY selected
            # node, not just the first of selectedItems().
            for node in self.scene.nodes():
                try:
                    node.set_selected(node.isSelected())
                except RuntimeError:
                    pass  # Qt teardown — one item is destroyed

            selected_id = selected_node.data.id if selected_node else None
            # v0.9.9.1: no tree.blockSignals — the sync is idempotent by
            # state (a full recompute, not "apply a delta"), so the echo
            # during the alignment is harmless and the tree's own slots are not suppressed.
            self.tree.setCurrentItem(None)
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, Qt.UserRole) == selected_id:
                    self.tree.setCurrentItem(item)
                    break
            # v1.6 (ROADMAP tasks 1/6): the two selection-driven Edit items follow what is
            # selected — "Bulk edit" needs a card, "Arrange group members" needs a group.
            self._sync_bulk_actions()
        except RuntimeError:
            # PySide6/Qt teardown on process exit: the scene's C++ object is already
            # destroyed, yet the selectionChanged signal reached a live Python slot.
            # A normal state — silently ignore it (otherwise a traceback in the console).
            pass

    def _sync_bulk_actions(self):
        """Enable the two selection-driven v1.6 Edit items (the `act_backups` pattern).

        "Bulk edit selection…" is offered while at least one CARD is selected (a bulk of
        one is a legitimate edit and is what the keyboard path reaches), "Arrange group
        members…" while a GROUP is selected — the same method the context-menu rows call,
        so the two surfaces can never disagree about what is reachable. Never raises: a
        selection change can arrive during Qt teardown.
        """
        try:
            nodes = self.selected_nodes()
        except (AttributeError, RuntimeError):
            nodes = []
        try:
            group = self.scene.get_selected_group()
        except (AttributeError, RuntimeError):
            group = None
        for action, enabled in ((getattr(self, "act_bulk_edit", None), bool(nodes)),
                                (getattr(self, "act_arrange_group", None), group is not None)):
            if action is None:
                continue
            try:
                action.setEnabled(bool(enabled))
            except RuntimeError:
                pass  # Qt teardown — the QAction is already destroyed

    def _show_properties(self):
        node = self.scene.get_selected_node()
        if node:
            self._on_node_double_click_direct(node)
        else:
            QMessageBox.information(self, self.t("msg.info_title"), 
                                  self.t("msg.properties_select"))

    # ── v0.7.3: the node and arrow context menus ────────────────

    def _edit_node(self, node: "ServerNode"):
        """Edit a node (context menu / double click)."""
        if node is not None:
            self._on_node_double_click_direct(node)

    # ── v0.9.2: hotkeys for frequent actions on the selected node ─────

    def _edit_selected_node(self):
        """Ctrl+E: edit the server selected on the map."""
        node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return
        self._edit_node(node)

    def _add_note_at_view_center(self):
        """Ctrl+Shift+N: a note at the center of the map's visible area."""
        self._add_note_at()

    def _delete_selected(self):
        node = self.scene.get_selected_node()
        if node:
            self._remove_node_guarded(node)
            return
        # v0.8.1: a selected group — the servers stay on the map; only the frame is removed
        group = self.scene.get_selected_group()
        if group is not None:
            self._remove_group(group)

    # ── v0.7.2: Sticky Notes (notes on the map) ───────────────

    def _connect_note_signals(self, note):
        """Wire the note's signals to the dirty marker and undo (v0.8.3: text editing)."""
        try:
            note.textEdited.connect(lambda *_a: self._on_note_text_edited(note))
            note.moved.connect(lambda *_a: self._mark_dirty())
            # v1.2.4: attachment to a server (drag onto a node / drag of an attached one)
            note.attachRequested.connect(
                lambda node, n=note: self._attach_note_to_node(n, node))
            note.detachRequested.connect(
                lambda *_a, n=note: self._detach_note(n))
        except Exception:
            pass  # re-wiring the same note — not critical

    def _on_note_text_edited(self, note):
        """v0.8.3: a text edit — restart the debounce; on silence -> an undo command."""
        self._mark_dirty()
        try:
            committed = self._note_committed.get(note.note_id)
            if committed is not None and note.text() == committed:
                self._note_edit_pending = None
                return  # the text matches the committed one (undo/redo restored it) — no command needed
        except RuntimeError:
            return
        if not self._note_edit_pending or self._note_edit_pending[0] is not note:
            # a new edit session of this note — capture the starting text
            try:
                start = self._note_committed.get(note.note_id, note.text())
            except RuntimeError:
                return
            self._note_edit_pending = (note, start)
        self._note_edit_timer.start()

    def _add_note_at(self, scene_pos=None) -> None:
        """Create a note at a scene point (center — under the cursor)."""
        if scene_pos is not None:
            x = float(scene_pos.x()) - 120.0   # ~half of the default width
            y = float(scene_pos.y()) - 80.0    # ~half of the default height
        else:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            x, y = float(center.x()) - 120.0, float(center.y()) - 80.0
        note = self.scene.add_note(x=x, y=y)
        # v0.8.3: creating a note — an undo command; the note itself is already added above
        # (add_note returned the object), but for undo it must be removed/restored by a command.
        from modules.undo_commands import CmdAddRemoveNote, CmdEditTextNote
        raw = {"id": note.note_id, "text": "", "x": float(note.pos().x()),
               "y": float(note.pos().y()),
               "width": float(note.rect().width()), "height": float(note.rect().height())}
        self._note_committed[note.note_id] = ""
        self._push_command(CmdAddRemoveNote(self, self.scene, raw, "add"))
        self._attach_note(note)
        if self.log:
            self.log.info("Note added", extra={"id": note.note_id})
        self.statusBar().showMessage(self.t("status.note_added"))
        self._mark_dirty()

    def _remove_note(self, note) -> bool:
        """Remove a note (a light object — no confirmation dialog)."""
        note_id = getattr(note, "note_id", None)
        if not note_id or self.scene.get_note_by_id(note_id) is None:
            return False
        from modules.undo_commands import CmdAddRemoveNote
        try:
            raw = note.to_dict()
        except RuntimeError:
            return False
        self._note_edit_pending = None  # the uncommitted edit goes away with the removal command
        self._push_command(CmdAddRemoveNote(self, self.scene, raw, "remove"))
        if self.log:
            self.log.info("Note deleted", extra={"id": note_id})
        self.statusBar().showMessage(self.t("status.note_deleted"))
        self._mark_dirty()
        return True

    def _attach_note_to_node(self, note, node) -> bool:
        """v1.2.4: attach a note to a node (menu / drag). An undo command."""
        if note is None or node is None:
            return False
        try:
            if note.scene() is None or getattr(note, "server_id", None) == node.data.id:
                return False  # already attached to this same node — a no-op
        except RuntimeError:
            return False
        from modules.undo_commands import CmdAttachNote
        self._push_command(CmdAttachNote(self, note, node.data.id, "attach"))
        if self.log:
            self.log.info("Note attached", extra={"note": note.note_id, "server": node.data.id})
        self.statusBar().showMessage(self.t("status.note_attached", alias=node.data.alias))
        self._mark_dirty()
        return True

    def _detach_note(self, note) -> bool:
        """v1.2.4: detach a note (menu / drag / server removal). An undo command."""
        sid = getattr(note, "server_id", None) if note is not None else None
        if not sid:
            return False
        from modules.undo_commands import CmdAttachNote
        self._push_command(CmdAttachNote(self, note, sid, "detach"))
        if self.log:
            self.log.info("Note detached", extra={"note": getattr(note, "note_id", None)})
        self.statusBar().showMessage(self.t("status.note_detached"))
        self._mark_dirty()
        return True

    # ── v0.8.1: node grouping (clusters/folders on the map) ─────

    def _commit_group_move(self, group, old_pos, new_pos):
        """v0.8.3-audit (#6): a group-move gesture finished -> CmdMoveGroup."""
        from modules.undo_commands import CmdMoveGroup
        self._push_command(CmdMoveGroup(self, group, old_pos, new_pos))
        self._mark_dirty()

    def _commit_group_resize(self, group, w0, h0, w1, h1):
        """v0.8.3-audit (#6): a group resize finished -> CmdResizeGroup."""
        from modules.undo_commands import CmdResizeGroup
        self._push_command(CmdResizeGroup(self, group, (w0, h0), (w1, h1)))
        self._mark_dirty()

    def _connect_group_signals(self, group):
        """Wire the group's signals: the dirty marker + undo commands
        (v0.8.3-audit #6: move/resize/rename enter the stack);
        renameRequested — to the rename dialog; v1.4.2: collapseRequested (the fold
        chevron) and collapsedChanged (the fold is persisted → the dirty marker)."""
        try:
            for sig in (group.moved, group.resized, group.titleChanged,
                        group.membershipChanged, group.collapsedChanged):
                sig.connect(lambda *_a: self._mark_dirty())
            # Undo commits of finished gestures (the node_drag_committed pattern)
            group.moveCommitted.connect(
                lambda op, np, g=group: self._commit_group_move(g, op, np))
            group.resizeCommitted.connect(
                lambda w0, h0, w1, h1, g=group: self._commit_group_resize(
                    g, w0, h0, w1, h1))
            # Double click on the title -> QInputDialog (the g closure — the source group)
            group.renameRequested.connect(
                lambda *_a, g=group: self._rename_group(g))
            # v1.4.2 (ROADMAP task 5): the fold chevron asks; the window pushes the
            # command (the group must not mutate itself — the renameRequested contract).
            group.collapseRequested.connect(
                lambda *_a, g=group: self._toggle_group_collapsed(g))
        except Exception:  # noqa: BLE001 — re-wiring is not critical
            pass

    # ── v1.4.2 (ROADMAP task 5): the group fold ─────────────────────

    def _toggle_group_collapsed(self, group) -> bool:
        """Fold or unfold a group as ONE undo step (the chevron / the context menu).

        The command redoes the fold itself (`_push_command` → `QUndoStack.push` →
        `redo()`), so nothing is mutated here — the v0.8.3 undo discipline.
        """
        if group is None:
            return False
        try:
            target = not group.is_collapsed()
        except (AttributeError, RuntimeError):
            return False
        from modules.undo_commands import CmdToggleGroupCollapse
        self._push_command(CmdToggleGroupCollapse(self, group, target))
        self._mark_dirty()
        return True

    # ── v0.9.1: export the map to an image + a background image ────

    def _connect_background_signals(self, bg):
        """Wire the background's signals: the dirty marker + the undo commands (v1.6, task 4).

        The incremental `moved`/`resized` signals keep the project dirty during the
        gesture; the COMPLETED `moveCommitted`/`resizeCommitted` ones push the ONE command
        of the gesture (the group's own wiring, `_connect_group_signals`). Before v1.6 the
        background geometry was the last mouse-driven object outside the undo stack.
        """
        try:
            bg.moved.connect(lambda *_a: self._mark_dirty())
            bg.resized.connect(lambda *_a: self._mark_dirty())
            bg.moveCommitted.connect(
                lambda op, np, b=bg: self._commit_background_move(b, op, np))
            bg.resizeCommitted.connect(
                lambda w0, h0, w1, h1, b=bg: self._commit_background_resize(b, w0, h0, w1, h1))
        except Exception:  # noqa: BLE001
            pass

    def _commit_background_move(self, background, old_pos, new_pos):
        """v1.6 (ROADMAP task 4): a background-move gesture finished -> CmdMoveBackground."""
        from modules.undo_commands import CmdMoveBackground
        self._push_command(CmdMoveBackground(self, background, old_pos, new_pos))
        self._mark_dirty()

    def _commit_background_resize(self, background, w0, h0, w1, h1):
        """v1.6 (ROADMAP task 4): a background resize finished -> CmdResizeBackground."""
        from modules.undo_commands import CmdResizeBackground
        self._push_command(CmdResizeBackground(self, background, (w0, h0), (w1, h1)))
        self._mark_dirty()

    # ── v1.5rc2 (ROADMAP task 3): the PRINT-FRIENDLY export palette ───────────────

    def _ask_export_palette(self):
        """Ask which palette the export renders with — the ONE question all four exports share.

        v1.5rc2: an export must not print a dark page, so the DEFAULT is the
        print-friendly one (`theme.PALETTE_PRINT` — the LIGHT page with the
        high-contrast lines, `MapScene.export_palette()`); the dialog's checkbox is
        the opt-out that keeps the CURRENT look. Returns the palette id of the active
        theme, or None when the user cancelled (the export then writes nothing).

        The answer of the previous export is remembered on the instance for the rest
        of the session (never persisted), and the dialog is a module-level facade
        (`MW.ExportOptionsDialog`), i.e. the same test seam as `QFileDialog`.
        """
        try:
            dialog = ExportOptionsDialog(
                self, use_current_theme=bool(self._export_use_current_theme))
        except Exception:  # noqa: BLE001 — a dialog that cannot be built must not block the export
            return theme.PALETTE_PRINT
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            self._export_use_current_theme = dialog.use_current_theme()
            return dialog.chosen_palette()
        finally:
            getattr(dialog, "deleteLater", lambda: None)()

    def _export_map_image(self):
        """Export the map to PNG/JPEG (v0.9.1 #1): render the whole scene to a file.

        v1.5rc2: the render goes through `self._ask_export_palette()` — print-friendly
        (a light page) unless the user asked for the current theme.
        """
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_png"), "",
            "PNG Images (*.png);;JPEG Images (*.jpg)")
        if not path:
            return
        # The extension from the chosen filter, if the user did not type it
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            ext = ".jpg" if "JPEG" in (selected_filter or "") else ".png"
            path += ext
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            pixmap = self.scene.render_to_pixmap(scale=2.0, palette=palette)
            if not pixmap.save(path):
                raise OSError("QPixmap.save returned False")
            self.statusBar().showMessage(self.t("status.export_ok"))
            if self.log:
                self.log.info("Map exported", extra={"file": path, "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_drawio(self):
        """Export the map to draw.io (.drawio) — v0.9.5 #1–#4.

        v1.5rc2: the same palette question as the raster exports — the writer paints
        the print-friendly (light, high-contrast) palette by default and carries the
        DECLARED dash pattern of every connection type.
        """
        from storage.export_drawio import export_scene_to_drawio
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_drawio"), "",
            "draw.io Diagrams (*.drawio)")
        if not path:
            return
        if not path.lower().endswith(".drawio"):
            path += ".drawio"
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            cells = export_scene_to_drawio(self.scene, path, palette=palette)
            self.statusBar().showMessage(self.t("status.export_drawio_ok"))
            if self.log:
                self.log.info(
                    "Map exported to drawio",
                    extra={"file": path, "cells": cells, "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_pdf(self):
        """Export the map to PDF (v0.9.9.7): the open scene -> a file in one action.

        v1.5rc2: the print-friendly palette by default — a PDF is the format most
        likely to be printed.
        """
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_pdf"), "", "PDF Documents (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            size = self.scene.render_to_pdf(path, palette=palette)
            self.statusBar().showMessage(self.t("status.export_pdf_ok"))
            if self.log:
                self.log.info(
                    "Map exported to PDF", extra={"file": path, "bytes": size,
                                                  "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_map_svg(self):
        """Export the map to SVG (v1.3.3.7): the open scene -> a vector file.

        The same shape as the PDF/PNG paths (QFileDialog + the extension + the status
        bar/log + `msg.export_failed`), but the render itself is `render_to_svg`
        (`QSvgGenerator`) — the map leaves as VECTOR data, background and grid included.
        v1.5rc2: the palette question comes first, so an SVG of a DARK window is a
        light page by default too (the halos stay hidden — the vector contract).
        """
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.export_svg"), "", "SVG Images (*.svg)")
        if not path:
            return
        if not path.lower().endswith(".svg"):
            path += ".svg"
        palette = self._ask_export_palette()
        if palette is None:
            return
        try:
            size = self.scene.render_to_svg(path, palette=palette)
            self.statusBar().showMessage(self.t("status.export_svg_ok"))
            if self.log:
                self.log.info(
                    "Map exported to SVG", extra={"file": path, "bytes": size,
                                                  "palette": palette})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    # ── v1.5.1 (ROADMAP tasks 1/2): the two IMAGE paths of the map ────────────────

    def _copy_map_image(self):
        """Copy the map into the clipboard as an image (v1.5.1, ROADMAP task 1).

        The SAME 2× render as the PNG export, with `QApplication.clipboard()
        .setPixmap()` instead of the file dialog — and ONE deliberate difference: **the
        copy uses the CURRENT theme and asks NO palette question**. An export is a
        document (the v1.5rc2 print-friendly default), a copy is "what I am looking at";
        routing this action through the export palette dialog would turn a screenshot of
        the window into a light page behind a modal, which is the defect this comment
        exists to prevent. No dialog at all, so the action is a pure function of the
        scene and the active palette (the gate asserts the `PALETTE_THEME` render).

        An empty map is a valid copy (the render falls back to the fixed rect), and a
        failed render reports through `msg.export_failed` like every other export path.
        """
        try:
            pixmap = self.scene.render_to_pixmap(scale=2.0, palette=theme.PALETTE_THEME)
            QApplication.clipboard().setPixmap(pixmap)
            self.statusBar().showMessage(self.t("status.map_copied"))
            if self.log:
                self.log.info("Map copied to the clipboard",
                              extra={"width": pixmap.width(), "height": pixmap.height(),
                                     "palette": theme.PALETTE_THEME})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _export_docs_frame(self):
        """Save the map as a FIXED-FRAME documentation image (v1.5.1, ROADMAP task 2).

        The poster path: `MapScene.render_frame_to_pixmap()` renders the map inside a
        1600×900 LOGICAL frame at 2× (3200×1800 px), the content fitted and centred on
        the canvas background — the SAME size for every map, which is what makes it
        usable in a README, an issue report or a slide (the ordinary PNG export sizes
        itself to the content). The palette is the CURRENT theme (a poster is read on
        screen); the file is written with the PNG writer and reported in the status bar.

        The image holds the MAP only: the floating panels and the chrome are children of
        `MapView`, never scene items, so they cannot leak into a poster (see the method
        docstring). The subject for the shipped documentation is the EXAMPLE map — real
        topologies are gitignored and must never be published; the workflow (the
        destination, the README link and the refresh rule) is pinned in `DOCUMENTATION.md`
        §5 and `AGENTS.md` §2.
        """
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.docs_frame"), "",
            "PNG Images (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            pixmap = self.scene.render_frame_to_pixmap()
            if not pixmap.save(path):
                raise OSError("QPixmap.save returned False")
            self.statusBar().showMessage(
                self.t("status.docs_frame_saved", file=os.path.basename(path)))
            if self.log:
                self.log.info("Documentation image saved",
                              extra={"file": path, "width": pixmap.width(),
                                     "height": pixmap.height()})
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    # ── v1.5.5 (ROADMAP tasks 2/3): the inventory report ─────────────────────────

    def _list_report_rows(self) -> list:
        """The visible LIST table (the header row first) — or [] when there is no table.

        The ONE reader the two report actions share: the panel builds the rows (they ARE
        the cells `list_cell_values()` produced, in the order the user sorted them), so the
        report and the screen can never disagree about the columns or the content.
        """
        panel = getattr(self, "sidebar", None)
        if panel is None:
            return []
        try:
            return panel.list_report_rows()
        except RuntimeError:
            return []  # Qt teardown — the panel is already destroyed

    def _report_table_unavailable(self) -> None:
        """Say WHY there is nothing to report (the two actions share the sentence)."""
        try:
            self.statusBar().showMessage(self.t("status.list_empty"))
        except Exception:  # noqa: BLE001 — a hint must not break the action
            pass

    def _export_connections_table(self):
        """Export the map's CONNECTIONS as CSV or TSV (v1.6, ROADMAP task 5).

        The second DATA report, built on the SAME pure writer as the inventory export
        (`list_table_text()`): the rows come from `storage/export_connections.py`, the
        delimiter and the file dialog follow the sibling above, and the file is UTF-8 with
        a BOM for the same reason (aliases and labels in the user's own alphabet, opened by
        Excel). A map without a single connection reports that instead of writing a header.
        """
        try:
            arrows = list(self.scene.arrows())
        except (AttributeError, RuntimeError):
            arrows = []
        if connection_report_rows is None:
            return
        rows = connection_report_rows(arrows, self.t if self._i18n_available else None)
        if not rows:
            self.statusBar().showMessage(
                self.t("status.connections_empty") if self._i18n_available
                else "Nothing to report — the map has no connections")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_connections"), "",
            "CSV — Comma Separated Values (*.csv);;TSV — Tab Separated Values (*.tsv)")
        if not path:
            return
        fmt = "tsv" if "TSV" in (selected_filter or "") else "csv"
        lowered = str(path).lower()
        if lowered.endswith(".tsv"):
            fmt = "tsv"
        elif lowered.endswith(".csv"):
            fmt = "csv"
        else:
            path += f".{fmt}"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(list_table_text(rows, list_delimiter(fmt)))
            self.statusBar().showMessage(
                self.t("status.connections_exported", file=os.path.basename(path)))
            if self.log:
                self.log.info("Connection list exported",
                              extra={"file": path, "format": fmt, "rows": len(rows) - 1})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _copy_list_table(self):
        """Copy the VISIBLE server table to the clipboard as TSV (v1.5.5, ROADMAP task 2).

        TSV, not CSV, on purpose: the clipboard is for the next PASTE, and a spreadsheet
        splits tab-separated text into cells natively (a comma-separated paste lands in one
        column). The text comes from the pure `list_table_text()` — the SAME writer the file
        export uses, so a value with a comma, a quote or a line break cannot be copied
        differently from the way it is exported.
        """
        rows = self._list_report_rows()
        if not rows:
            self._report_table_unavailable()
            return
        text = list_table_text(rows, list_delimiter("tsv"))
        count = len(rows) - 1        # the header is not a server
        if self._copy_text_to_clipboard(text, "status.list_copied", count=count) and self.log:
            self.log.info("Server list copied to the clipboard",
                          extra={"rows": count, "columns": len(rows[0])})

    def _export_list_table(self):
        """Export the VISIBLE server table as CSV or TSV (v1.5.5, ROADMAP task 2).

        The ordinary save-dialog pattern of every export of this window (the extension from
        the chosen filter, the status bar on success, `msg.export_failed` on a failure), with
        ONE deliberate difference: the file is written as **UTF-8 with a BOM**. An inventory
        carries aliases, OS names and comments in the user's own alphabet, and the BOM is
        what makes Excel open such a CSV correctly instead of as mojibake — the report is the
        artefact a human passes on, not an internal file.

        The columns are the VISIBLE ones and the rows are the VISIBLE rows in their visible
        order (the filters and the sort included): an export is "what I am looking at",
        documented — the same rule the map's copy follows.
        """
        rows = self._list_report_rows()
        if not rows:
            self._report_table_unavailable()
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self.t("file.export_list"), "",
            "CSV — Comma Separated Values (*.csv);;TSV — Tab Separated Values (*.tsv)")
        if not path:
            return
        # The format follows the CHOSEN filter, and a typed extension wins over both.
        fmt = "tsv" if "TSV" in (selected_filter or "") else "csv"
        lowered = str(path).lower()
        if lowered.endswith(".tsv"):
            fmt = "tsv"
        elif lowered.endswith(".csv"):
            fmt = "csv"
        else:
            path += f".{fmt}"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(list_table_text(rows, list_delimiter(fmt)))
            self.statusBar().showMessage(
                self.t("status.list_exported", file=os.path.basename(path)))
            if self.log:
                self.log.info("Server list exported",
                              extra={"file": path, "format": fmt, "rows": len(rows) - 1})
        except Exception as e:  # noqa: BLE001 — a GUI action must not crash the app
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.export_failed", error=str(e)))

    def _set_background_image(self):
        """Choose and set the map background image (v0.9.1 #2/#3)."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("view.set_background"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        try:
            bg = self.scene.set_background_image(path)
        except Exception as e:  # noqa: BLE001 — a corrupt/unreadable image
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.background_failed", error=str(e)))
            return
        # By default the background is placed in the map's visible area
        try:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            w, h = bg.size()
            bg.setPos(center.x() - w / 2, center.y() - h / 2)
        except Exception:  # noqa: BLE001 — the view is unavailable (headless) — keep (0,0)
            pass
        self._connect_background_signals(bg)
        self._mark_dirty()
        self.statusBar().showMessage(self.t("status.background_set"))
        if self.log:
            self.log.info("Background image set", extra={"file": path})

    def _remove_background_image(self):
        """Remove the map background image (v0.9.1)."""
        if self.scene.background() is None:
            return
        self.scene.remove_background()
        self._mark_dirty()
        self.statusBar().showMessage(self.t("status.background_removed"))

    def _add_group_at(self, at_scene_pos=None) -> None:
        """Create a group (frame + title), centering it under the click point.

        `at_scene_pos` is optional: QAction.triggered sends a bool
        `checked` as the first argument — the position is accepted only if it really is
        a scene point (the same fix as on _add_server; regression_v081 #1). Nodes already
        under the frame become members automatically (MapScene.resync_group_members).
        """
        try:
            if _is_scene_point(at_scene_pos):
                center = at_scene_pos
            else:
                center = self.view.mapToScene(self.view.viewport().rect().center())

            base_name = self.t("group.default_name")
            used = {g.name for g in self.scene.groups()}
            name, n = base_name, 2
            while name in used:  # do not repeat existing group names
                name = f"{base_name} {n}"
                n += 1

            grp = self.scene.add_group(
                name=name,
                x=float(center.x()) - NodeGroup.DEFAULT_W / 2,
                y=float(center.y()) - NodeGroup.DEFAULT_H / 2)
            self._connect_group_signals(grp)
            if self.log:
                self.log.info("Group added", extra={"id": grp.group_id, "group_name": name})
            self.statusBar().showMessage(self.t("status.group_added"))
            self._mark_dirty()
        except Exception as e:
            if self.log:
                self.log.exception("Error adding group")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.add_failed", error=str(e)))

    def _rename_group(self, group) -> None:
        """Rename a group (a double click on the title / the context menu)."""
        if group is None:
            return
        try:
            from PySide6.QtWidgets import QInputDialog, QLineEdit
            text, ok = QInputDialog.getText(
                self,
                self.t("dialog.rename_group"),
                f"{self.t('group.name_label')} ",
                QLineEdit.Normal,
                group.name)
            if ok and str(text).strip():
                new_name = str(text).strip()
                if new_name != group.name:
                    # v0.8.3-audit (#6): renaming — via an undo command
                    from modules.undo_commands import CmdEditGroupName
                    self._push_command(
                        CmdEditGroupName(self, group, group.name, new_name))
                    self._mark_dirty()
                self.statusBar().showMessage(self.t("status.group_renamed"))
        except Exception as e:
            if self.log:
                self.log.exception(f"Error renaming group {group.name}")

    def _remove_group(self, group) -> bool:
        """Remove a group. Member servers stay on the map at the same positions —
        a group is a labeled container (a light object, no confirmation dialog)."""
        gid = getattr(group, "group_id", None)
        if not gid or self.scene.get_group_by_id(gid) is None:
            return False
        name = group.name
        self.scene.remove_group(group)
        if self.log:
            self.log.info("Group deleted", extra={"id": gid, "group_name": name})
        self.statusBar().showMessage(self.t("status.group_deleted"))
        self._mark_dirty()
        return True

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        node_id = item.data(0, Qt.UserRole)
        if node_id and self.scene.has_node(node_id):
            self._select_node(self.scene.get_node(node_id), center=False)

    def _on_tree_item_double_click(self, item: QTreeWidgetItem, column: int):
        """v0.9.9.4: select the row's node and reveal it on the map.

        v1.4.6 (ROADMAP task 3, the decision pinned with the release): in LIST mode
        (the map is collapsed) a row carries the server parameters and there is nothing
        to reveal — the double click therefore does what a double click on the node CARD
        does, the `ui_node_double_click` mode: "properties" opens the AddServer dialog
        prefilled (the only editor of server data — an inline edit of the table is out
        of scope by design) and "connect" opens the SSH connect dialog. The NARROW mode
        keeps the v0.9.9.4 semantics byte for byte (select + center on the map).
        """
        node_id = item.data(0, Qt.UserRole)
        if node_id and self.scene.has_node(node_id):
            node = self.scene.get_node(node_id)
            if getattr(self, "_map_collapsed", False):
                self._select_node(node, center=False)
                self._on_node_double_click_direct(node)
                return
            self._select_node(node, center=True)

    # ── v0.9.6: the server tree context menu (sidebar) ───────────────
    # v0.9.9.4: the item set, separators, and i18n labels — in the panel
    # (SidebarPanel.fill_context_menu); the QMenu object is created here (the module-global
    # main_window — a test seam for substitution), and the exec is on the window too.

    def _on_sidebar_context_menu(self, pos):
        """v0.9.6 (ROADMAP #1–#2): right-click a server in the tree — node actions.

        The set and order — per ROADMAP v0.9.6 (SidebarPanel.CONTEXT_MENU_ITEMS):
        Connect SSH, External terminal, Edit, Copy IP,
        Copy Hostname, Ping, Collect info, Show on map
        (centering + accent), Delete (the guarded path). i18n — reusing
        the map's ctx.* keys; the only new one is ctx.reveal_on_map. "Map-canvas"
        actions are deliberately NOT duplicated (ROADMAP #2): the drag connection
        and the collapse/expand plaque live only in the map context, where they make sense.
        """
        item = self.tree.itemAt(pos)
        if item is None:
            return  # a click off the rows — do not show the menu (an empty tree area)
        node_id = item.data(0, Qt.UserRole)
        if not node_id or not self.scene.has_node(node_id):
            return  # a row without a node (or the node is gone) — no actions
        node = self.scene.get_node(node_id)

        menu = QMenu(self)  # v0.9.9.4: the panel fills it; the window creates and shows it
        self.sidebar.fill_context_menu(menu, node)
        # v1.4rc3 (ROADMAP task 7): the plugin hooks append their rows to the SAME menu
        # (the frozen contract names "the node context menu of the map or of the
        # sidebar" as one surface). The panel passed the rows of the real tree, so the
        # node travels as its ID — the manager narrows it to a plugin node record.
        self._extend_node_context_menu(menu, node.data.id)

        try:
            menu.exec(self.tree.mapToGlobal(pos))
        except Exception as e:  # noqa: BLE001 — a GUI component must not crash the app
            if self.log:
                self.log.warning(f"sidebar context menu exec failed: {e}")

    def _reveal_node_on_map(self, node: "ServerNode"):
        """v0.9.6 (ROADMAP #1): "Show on map" — a smooth flight + an accent.

        Selecting the node (the tree row and the map frame are synced via
        _sync_selection_state); the camera — the `_select_node(center=True, smooth=True)`
        path, which v1.4.4 (ROADMAP task 2) turns into a `ui/motion.py` FLIGHT (250 ms,
        OutQuad, interruptible) instead of an instant jump; the accent — the
        ServerNode.reveal_flash flash frame (the set_status pulse pattern).
        """
        if node is None or node.scene() is None:
            return  # the node was removed while the menu was open
        self._select_node(node, center=True, smooth=True)
        flash = getattr(node, "reveal_flash", None)
        if callable(flash):
            try:
                flash()
            except Exception:  # noqa: BLE001 — the accent is cosmetic; the navigation already worked
                pass

    def refresh_sidebar(self):
        """v0.9.9.4 facade: the tree rows (search + tag filter + status markers)
        and the tag list — SidebarPanel; dimming/selection/counters — the window."""
        query = self.search_edit.text().strip().lower() if hasattr(self, 'search_edit') else ""
        nodes = self.scene.nodes()
        self.sidebar.refresh_rows(nodes, query)
        self.sidebar.sync_tag_filter_items(nodes)
        self._apply_map_dimming()  # v0.9.8: dimming = the tag filter AND the map search
        self._sync_selection_state()
        self._update_counts_label()  # UI polish: the status-bar counters track the composition

    # ── v0.9.4: the tag filter (sidebar + dimming on the map) ──

    def _active_tag_filter(self) -> str:
        """The tag selected in the combo box, or \"\" ("All tags")."""
        combo = getattr(self, "tag_filter", None)
        if combo is None or not hasattr(combo, "currentData"):
            return ""
        data = combo.currentData()
        return str(data) if data else ""

    def _on_tag_filter_changed(self, *_a):
        """A tag change in the filter -> redraw the tree and recompute the dimming."""
        if hasattr(self, "tree"):
            self.refresh_sidebar()

    def _hover_focus(self):
        """v1.4.4 (ROADMAP task 4): the arrow under the cursor (the scene's focus), or None."""
        try:
            getter = getattr(self.scene, "hover_focus_arrow", None)
            return getter() if callable(getter) else None
        except (AttributeError, RuntimeError):
            return None

    def _apply_map_dimming(self):
        """v0.9.4/v0.9.8/v1.4.4/v1.5.4: dimming + highlighting of the active filters on the map.

        A node "glows" only if it passes ALL active filters (the same semantics as in
        the sidebar — refresh_sidebar applies the query and the tag at once):
        - the v0.9.4 tag filter: nodes without the selected tag are dimmed;
        - the v0.9.8 map search (Ctrl+F): non-matches are dimmed,
          matches get the accent frame (ServerNode.set_search_match);
        - the v1.5.4 "problems only" LENS (ROADMAP task 2): everything that is not
          `warn` / `offline` / stale is dimmed — the lens COMPOSES with the two above
          instead of replacing them (one `and`, one owner);
        - the v1.4.4 arrow hover focus (ROADMAP task 4): hovering a connection highlights
          its TWO ends and dims everything else. It is merged HERE on purpose — this method
          is the single owner of the dim state, so the hover, the tag filter, the search and
          the lens cannot stack into a "stuck" opacity (the ROADMAP's "one owner" rule).
        The arrows are not touched: connections between dimmed nodes are read from context.
        The floating filter plaque (v1.5.4, task 3) is re-synced from the SAME place: this
        is the one call every filter change already passes through.
        """
        active = self._active_tag_filter()
        query = (getattr(self, "_map_search_query", "") or "").strip().lower()
        lens = bool(getattr(self, "_problems_only", False))
        focus = self._hover_focus()
        focus_ids = set()
        if focus is not None:
            for end in (getattr(focus, "source", None), getattr(focus, "target", None)):
                if end is not None:
                    focus_ids.add(id(end))
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return
        for node in nodes:
            tags = getattr(node.data, "tags", None) or []
            tag_ok = (not active) or active in tags
            if query:
                haystack = " ".join([
                    node.data.alias, node.data.host, node.data.ip, node.data.comment,
                ]).lower()
                match_ok = query in haystack
            else:
                match_ok = True
            # v1.5.4: the lens — "needs attention" is the DECLARED predicate shared with
            # the group aggregate (`graphics.node_group.is_in_trouble`), so the two can
            # never drift apart.
            problem_ok = (not lens) or node_in_trouble(
                getattr(node, "status", ""), bool(getattr(node, "is_stale", False)))
            dimmed = not (tag_ok and match_ok and problem_ok)
            matched = bool(query) and match_ok
            if focus is not None:
                # The hover focus wins: the two ends are read, the rest recedes — and the
                # accent frame belongs to the hovered ends alone while the hover lasts
                # (the search's own frames come back the moment the cursor leaves).
                if id(node) in focus_ids:
                    dimmed, matched = False, True
                else:
                    dimmed, matched = True, False
            try:
                node.set_dimmed(dimmed)
                node.set_search_match(matched)
            except (AttributeError, RuntimeError):
                pass
        self._sync_filter_plaque()

    # Backward-compat: the v0.9.4 name (external code/tests may reference it)
    _apply_map_tag_dimming = _apply_map_dimming

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

    # ── v1.5.4 (ROADMAP task 3): the floating plaque of the ACTIVE filters ───────

    #: The inset of the plaque's default (top-left) position — the legend's margin, so
    #: the two panels of the window share one spacing standard.
    FILTER_MARGIN = 12

    def _setup_filter_plaque(self):
        """Create the active-filter plaque (a child of the view) and wire its two signals.

        The widget owns no filter logic: it reports a click per row (`clear_requested`)
        and the window clears that ONE filter. Its placement hangs off `view.resized`
        like the other floating panels, and it starts hidden (no filter is active yet).
        """
        try:
            from ui.filter_plaque import FilterPlaque
        except ImportError:  # flat launch from the project root
            from filter_plaque import FilterPlaque

        self.filter_plaque = FilterPlaque(self.view)
        self.filter_plaque.clear_requested.connect(self._on_filter_clear)
        self.view.resized.connect(self._position_filter_plaque)
        self._position_filter_plaque()
        self._sync_filter_plaque()

    def _sync_filter_plaque(self) -> bool:
        """Show/hide and re-text the plaque from the LIVE filter state. True — visible.

        The window is the ONE owner of the filter state (the search query, the tag pick,
        the status filter and the lens), so the plaque is a pure projection of it: it
        appears exactly while at least one filter is active and disappears with the last
        × — which is what makes "a forgotten filter" impossible to mistake for deleted
        servers. Idempotent and cheap: the widget compares the RAW state and a repeated
        push costs one dict comparison.
        """
        plaque = getattr(self, "filter_plaque", None)
        if plaque is None:
            return False
        query = (getattr(self, "_map_search_query", "") or "").strip()
        try:
            changed = plaque.set_state(search=query, tag=self._active_tag_filter(),
                                       status=getattr(self, "_status_filter", "") or "",
                                       problems=bool(getattr(self, "_problems_only", False)))
            if plaque.is_empty():
                if plaque.isVisible():
                    plaque.hide()
                return False
            if not plaque.isVisible():
                plaque.setVisible(True)
                changed = True
            if changed:
                self._position_filter_plaque()
                plaque.raise_()
        except RuntimeError:
            return False  # Qt teardown — the panel is already destroyed
        return True

    def _position_filter_plaque(self):
        """Place the plaque in the TOP-LEFT corner, clear of the open search bar.

        The top-left is the one corner the other floating panels leave free (the search
        bar is top-centre, the minimap top-right, the legend bottom-left, the collapse
        diamond bottom-right). On a narrow window the centred search bar reaches into it,
        so the plaque STEPS BELOW the bar instead of fighting it for the pixels — the same
        "yield, never cover" idea the v1.5rc4 priority rule uses.
        """
        plaque = getattr(self, "filter_plaque", None)
        view = getattr(self, "view", None)
        if plaque is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            x = self.FILTER_MARGIN
            y = self.FILTER_MARGIN
            bar = getattr(self, "map_search", None)
            if bar is not None and bar.isVisible():
                geometry = bar.geometry()
                if geometry.left() < x + plaque.width() + self.FILTER_MARGIN:
                    y = geometry.bottom() + self.FILTER_MARGIN
            x = min(max(int(x), 0), max(w - plaque.width(), 0))
            y = min(max(int(y), 0), max(h - plaque.height(), 0))
            plaque.move(int(x), int(y))
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _on_filter_clear(self, kind: str):
        """The × of one plaque row: clear THAT filter and nothing else (v1.5.4).

        Every branch reuses the ordinary path of its own filter (the search panel's close,
        the tag combo, the status counter's toggle, the lens setter), so a plaque click
        behaves exactly like the gesture that turned the filter on — no second semantics
        to keep in sync.
        """
        kind = str(kind or "")
        if kind == "search":
            self._close_map_search()
        elif kind == "tag":
            combo = getattr(self, "tag_filter", None)
            if combo is not None:
                try:
                    combo.setCurrentIndex(0)   # "All tags" → _on_tag_filter_changed
                except (RuntimeError, AttributeError):
                    pass  # Qt teardown / a panel without the combo
        elif kind == "status":
            self._on_status_filter_clicked(getattr(self, "_status_filter", ""))
        elif kind == "problems":
            self._set_problems_only(False)

    # ── v0.9.8: map search (Ctrl+F) — ROADMAP v0.9.8 ────────────────

    def _setup_map_search(self):
        """v0.9.8: create a floating search bar over the canvas + the state.

        The panel — a child widget of the MapView (floats over the viewport, out of the scene's way).
        The Ctrl+F hotkey provides the "View -> Search map..." item (a QAction shortcut) —
        a separate QShortcut with the same sequence would create an ambiguous shortcut.
        The search logic lives here: match/dim/center — a single path.
        """
        try:
            from ui.map_search_bar import MapSearchBar
        except ImportError:  # flat launch from the project root
            from map_search_bar import MapSearchBar

        # The state (empty until the first query)
        self._map_search_query = ""
        self._map_search_matches = []
        self._map_search_index = -1

        self.map_search = MapSearchBar(self.view)
        self.map_search.query_changed.connect(self._on_map_search_query)
        self.map_search.next_requested.connect(lambda: self._map_search_step(+1))
        self.map_search.prev_requested.connect(lambda: self._map_search_step(-1))
        self.map_search.close_requested.connect(self._close_map_search)
        # Reposition the panel on a window resize (it is outside the layout, a child of the view).
        # v0.9.9.1: the MapView.resized signal was added — before, the connect fell into
        # an AttributeError and was silently swallowed by try/except (the panel kept its old x).
        self.view.resized.connect(self._position_map_search_bar)

    # ── v1.4.2 (ROADMAP task 2): the minimap — the big-picture panel over the canvas ──

    def _setup_minimap(self):
        """Create the minimap panel (a child of the MapView), its state and its wiring.

        The widget paints the scheme at fit scale and asks for a camera move through
        `center_requested`; the CAMERA stays here (the search-bar split: the widget owns
        no view logic). Visibility is the `ui_minimap` key of `~/.sshmap/config.json`
        (a UI state written by its owner — NOT a settings-hub key, like
        `ui_cmdlib_collapsed`), read once at startup with the default True.
        """
        try:
            from ui.minimap import MinimapWidget
        except ImportError:  # flat launch from the project root
            from minimap import MinimapWidget

        self.minimap = MinimapWidget(self.view)
        self.minimap.center_requested.connect(self._on_minimap_center)
        # v1.4.6: the title band folds the panel sideways; the WINDOW persists it and
        # re-places the panel (its width changed — it is anchored to the right edge).
        self.minimap.collapsed_changed.connect(self._on_minimap_collapsed_changed)
        # v1.4.6: the MOVE gesture (a long press, then a drag) — the panel reports where
        # it landed, the WINDOW remembers it (`ui_minimap_position`, the legend pattern).
        self.minimap.moved.connect(self._on_minimap_moved)
        # Reposition on every view resize / splitter drag (the map_search pattern).
        self.view.resized.connect(self._position_minimap)
        (self._minimap_enabled, self._minimap_collapsed,
         self._minimap_pos) = self._read_minimap_settings()
        # v1.5rc5 (N6): a saved position describes the EXPANDED panel — start from that width
        # so a window restored FOLDED still keeps the band on the right edge it hangs from.
        self._minimap_width = int(MinimapWidget.DEFAULT_WIDTH)
        self.minimap.set_collapsed(bool(self._minimap_collapsed))
        self.minimap.setVisible(bool(self._minimap_enabled))
        self._position_minimap()

    @staticmethod
    def _read_minimap_settings():
        """`ui_minimap*` from the config → (visible, collapsed, position|None).

        v1.4.6: the panel's own UI state grew to the legend's trio — the visibility, the
        side fold (`ui_minimap_collapsed`) and the position (`ui_minimap_position`,
        `{x, y}`). A bool wins, anything else (missing/broken) → the default: the panel
        is visible, unfolded, in the top-right corner.
        """
        visible, collapsed, position = True, False, None
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the feature is simply on
            return visible, collapsed, position
        if isinstance(cfg.get("ui_minimap"), bool):
            visible = bool(cfg["ui_minimap"])
        if isinstance(cfg.get("ui_minimap_collapsed"), bool):
            collapsed = bool(cfg["ui_minimap_collapsed"])
        position = MainWindow._saved_position(cfg.get("ui_minimap_position"))
        return visible, collapsed, position

    def _on_minimap_collapsed_changed(self, collapsed: bool):
        """The minimap was folded/unfolded through its title band (v1.4.6).

        The state is written by the WINDOW (the widget owns no config) and the panel is
        re-placed: it is anchored to the RIGHT edge, so its x changed with its width.
        """
        self._minimap_collapsed = bool(collapsed)
        self._save_minimap_config({"ui_minimap_collapsed": bool(collapsed)})
        self._position_minimap()

    def _on_minimap_moved(self, position):
        """The user MOVED the panel (a long press, then a drag): remember where (v1.4.6).

        The widget has already moved itself; this only persists the spot — the
        `_on_legend_moved` pattern, which is what makes the panel stay detached from the
        corner across restarts (and what switches `_position_minimap()` from the default
        corner to the saved spot).

        v1.5 (ROADMAP): a drop within `SNAP_PX` of an anchored edge (RIGHT|TOP) instead
        RE-ANCHORS the panel — the saved position is cleared and the ordinary rules (the
        corner, the fold and the "below an open search bar" step) come back by themselves.
        """
        try:
            pos = QPoint(int(position.x()), int(position.y()))
        except (TypeError, ValueError, AttributeError):
            return
        if self._snap_panel(getattr(self, "minimap", None), pos, "rt"):
            self._minimap_pos = None
            self._save_minimap_config({"ui_minimap_position": {"x": None, "y": None}})
            self._position_minimap()   # the anchor it was dropped on, applied at once
            return
        self._minimap_pos = pos
        self._save_minimap_config({"ui_minimap_position": {"x": self._minimap_pos.x(),
                                                          "y": self._minimap_pos.y()}})

    def _save_minimap_config(self, data: dict) -> None:
        """Merge-write the minimap's own UI state (the `ui_legend*` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the gesture
            pass

    def _toggle_minimap(self, checked: bool):
        """v1.4.2: show/hide the minimap + persist `ui_minimap` (a merge write)."""
        mini = getattr(self, "minimap", None)
        if mini is None:
            return
        visible = bool(checked)
        try:
            mini.setVisible(visible)
            if visible:
                self._position_minimap()
                mini.refresh()   # the panel may have been hidden while the map changed
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._save_minimap_config({"ui_minimap": visible})

    def _position_minimap(self):
        """v1.4.2: the panel in the TOP-RIGHT corner of the map (12 px inset).

        The top of the map was reserved for the minimap as early as the v1.2.4.1-fix
        comment (the map-collapse diamond sits in the BOTTOM-right corner). While the
        search bar is OPEN the panel moves BELOW it, so the two floating panels cannot
        overlap on a narrow window.

        v1.4.6: a SAVED position (`ui_minimap_position`, written by the move gesture)
        wins over the corner — and then the search-bar rule no longer applies: the user
        put the panel where they want it, and it is only CLAMPED into the view, so a
        hand-edited config or a shrunken window can never push it off-screen.

        v1.5rc5 (N6): with a saved position the RIGHT edge is preserved across a fold —
        the saved x is shifted by the width delta, so the band stays where the cursor
        clicked. `_minimap_width` is the last placed width and starts at the EXPANDED one
        (that is what a saved position describes, including a start with a folded panel).
        """
        mini = getattr(self, "minimap", None)
        view = getattr(self, "view", None)
        if mini is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            position = getattr(self, "_minimap_pos", None)
            if position is not None:
                width = int(mini.width())
                last_width = int(getattr(self, "_minimap_width", 0) or 0)
                # v1.5rc5 (N6): a saved position is the top-left of the EXPANDED panel, so a
                # fold used to keep that left corner while the width shrank by BODY_WIDTH and
                # threw the title band — the collapse affordance itself — 200 px off the RIGHT
                # edge it hangs from. The right edge is what the panel is anchored to, so it is
                # kept in BOTH states by shifting the remembered x by the width delta (ONE
                # attribute; the saved `{x, y}` keeps its meaning — no config-schema change).
                if last_width > 0 and last_width != width:
                    self._minimap_pos = QPoint(int(position.x()) + (last_width - width),
                                               int(position.y()))
                    position = self._minimap_pos
                self._minimap_width = width
                x = min(max(int(position.x()), 0), max(w - width, 0))
                y = min(max(int(position.y()), 0), max(h - mini.height(), 0))
            else:
                y = 12
                bar = getattr(self, "map_search", None)
                if bar is not None and bar.isVisible():
                    y = max(int(bar.geometry().bottom()) + 8, y)
                x = max(4, w - mini.width() - 12)
                self._minimap_width = int(mini.width())
            mini.move(int(x), int(y))
            if mini.isVisible():
                mini.raise_()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _on_minimap_center(self, point):
        """v1.4.2: the minimap asked for a camera move — clamp to the scene and centerOn.

        The inset margin of the fit can ask for a point outside the content, and a
        centerOn far outside the scene rect would fight the scrollbars: clamping keeps
        the camera inside the map.
        """
        try:
            x = float(point.x())
            y = float(point.y())
        except (TypeError, ValueError, AttributeError):
            return
        try:
            rect = self.scene.sceneRect()
            x = min(max(x, rect.left()), rect.right())
            y = min(max(y, rect.top()), rect.bottom())
            # v1.4.4 (ROADMAP task 1): dragging the minimap is manual control — a running
            # camera flight is cancelled (it would otherwise keep overriding the frame).
            self.view.stop_camera_flight()
            self.view.centerOn(x, y)
        except RuntimeError:
            pass  # Qt teardown — the view is gone

    # ── v1.4.5 (ROADMAP task 2): the first-run empty state ───────────────────────

    def _setup_empty_state(self):
        """Create the hint card over the canvas + its ONE button (a child of the view).

        The card itself is mouse-transparent (a click reaches the map — panning, the
        rubber band and the map context menu keep working behind the hint); the button
        is a SIBLING widget, because Qt's `WA_TransparentForMouseEvents` covers the
        children of the widget it is set on.
        """
        try:
            from ui.empty_state import EmptyStateOverlay
        except ImportError:  # flat launch from the project root
            from empty_state import EmptyStateOverlay

        self.empty_state = EmptyStateOverlay(self.view)
        self.empty_state.add_server_requested.connect(self._add_server)
        # v1.5.6 (ROADMAP task 2): the THIRD door of the first screen — an existing
        # project file. The widget only emits; the dialog and the load belong to the
        # window, and the door is the ORDINARY project-open path (the same one File → Open
        # and a dropped project use), so every downstream rule is shared.
        try:
            self.empty_state.open_map_requested.connect(self._open_project)
        except (RuntimeError, AttributeError):
            pass  # a stripped build without the signal — the other two doors still work
        # v1.5rc3 (ROADMAP task 1): the second button — the demo map. The SAME method the
        # Help item calls, so the two entry points cannot diverge (and both go through
        # the ordinary project load path).
        try:
            self.empty_state.example_requested.connect(self._open_example_map)
        except (RuntimeError, AttributeError):
            pass  # a stripped build without the signal — the title/import line still work
        # Reposition on every view resize / splitter drag (the minimap pattern).
        self.view.resized.connect(self._position_empty_state)
        self._empty_state_visible = None   # unknown until the first sync
        self._position_empty_state()
        self._sync_empty_state()

    def _sync_empty_state(self):
        """Show the hint while the map holds NO server; hide it from the first one on.

        Bound to the SCENE's node count (not to the sidebar's filtered rows): the hint
        explains the map, not a filter. Called from `_update_counts_label()` — the one
        place every composition change already passes through (add, remove, batch
        delete, import, project load, undo/redo).
        """
        overlay = getattr(self, "empty_state", None)
        if overlay is None:
            return
        try:
            empty = len(list(self.scene.nodes())) == 0
        except (AttributeError, RuntimeError):
            return  # the scene is not created yet / already destroyed
        if empty == getattr(self, "_empty_state_visible", None):
            return  # nothing changed — the hint is already in the right state
        self._empty_state_visible = empty
        try:
            overlay.set_state_visible(empty)
        except RuntimeError:
            return  # Qt teardown — the widget is already destroyed
        if empty:
            self._position_empty_state()
        # v1.5rc4 (ROADMAP task 7): the first-run hint is the reason the legend yields —
        # its appearance/disappearance is exactly where the priority must be re-resolved.
        self._sync_overlay_priority()

    def _position_empty_state(self):
        """Place the hint (and its button) in the middle of the view — a child, not a layout."""
        overlay = getattr(self, "empty_state", None)
        view = getattr(self, "view", None)
        if overlay is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            overlay.place(w, h)
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    # ── v1.4.5 (ROADMAP task 4): the legend panel ────────────────────────────────

    LEGEND_MARGIN = 12          # the inset of the DEFAULT (bottom-left) position

    # ── v1.5.6 (customer request): the map collapse button keeps out of the corner ──

    #: The inset of the map's collapse button from the VIEWPORT's bottom-right corner.
    #: The viewport already excludes the frame AND the scrollbars (the button used to be
    #: placed in the VIEW's corner, i.e. on top of the sliders), and the extra raise lifts
    #: it out of the very corner so the two collapse buttons sit at different levels.
    COLLAPSE_BTN_MARGIN = 8
    COLLAPSE_BTN_RAISE = 1

    # ── v1.5 (ROADMAP): the floating panels re-attach by dropping on an edge ──────

    #: How close a dropped panel's edge must land to the VIEW edge it is anchored to
    #: before the drop counts as "put me back": twice the 12 px default margin. A drag is
    #: otherwise PERMANENT — the saved position wins over the corner for good, hiding and
    #: showing a panel does not clear it — so this threshold is the ONE way back to the
    #: documented corner that needs no hand-edited `config.json`. An explicit "Reset panel
    #: positions" action was considered and REJECTED: the snap is the way back, and the
    #: step therefore costs no new i18n key, no new menu entry and no new hotkey.
    SNAP_PX = 24

    def _snap_panel(self, panel, position, edges: str) -> bool:
        """Re-anchor a dropped panel that landed at an edge it hangs from (v1.5).

        `edges` names the anchored edges of the panel: "lb" = LEFT|BOTTOM (the legend),
        "rt" = RIGHT|TOP (the minimap). A drop within `SNAP_PX` of ANY of them re-anchors
        the panel: the saved position is CLEARED with the `{"x": null, "y": null}`
        sentinel (`_saved_position()` already reads it as "no saved position", and
        `save_config()` is a merge and therefore cannot DELETE a key) and the ordinary
        placement of the panel runs, so every anchored rule comes back by itself — the
        documented corner, the fold that hangs off the edge, the minimap's step below an
        open search bar and the placement a resize recomputes.

        Pure geometry over the live widgets; returns True when the panel was re-anchored
        (the caller then skips the save and lets its own `_position_*` place it).
        """
        view = getattr(self, "view", None)
        if panel is None or view is None:
            return False
        try:
            w, h = view.width(), view.height()
            pw, ph = panel.width(), panel.height()
        except RuntimeError:
            return False  # Qt teardown — the widget is already destroyed
        if w <= 0 or h <= 0:
            return False
        x, y = int(position.x()), int(position.y())
        distance = {"l": x, "r": w - (x + pw), "t": y, "b": h - (y + ph)}
        return any(distance[edge] <= self.SNAP_PX for edge in edges if edge in distance)

    def _setup_legend(self):
        """Create the legend panel, apply the saved state and wire its persistence.

        Visibility, the folded state and the position live in `~/.sshmap/config.json`
        (`ui_legend`, `ui_legend_collapsed`, `ui_legend_position`) — UI state written by
        its owner, like `ui_minimap` (a merge write; a broken value falls back to the
        default). The panel is a child of the view: never a scene item, so it stays out
        of the exports and out of "fit to content".
        """
        try:
            from ui.legend import LegendWidget
        except ImportError:  # flat launch from the project root
            from legend import LegendWidget

        self.legend = LegendWidget(self.view)
        self.legend.moved.connect(self._on_legend_moved)
        self.legend.collapsed_changed.connect(self._on_legend_collapsed_changed)
        self.view.resized.connect(self._position_legend)
        visible, collapsed, position = self._read_legend_settings()
        self._legend_enabled = visible
        self._legend_pos = position
        self.legend.set_collapsed(collapsed)
        self.legend.setVisible(visible)
        self._position_legend()

    @staticmethod
    def _saved_position(raw):
        """A saved `{x, y}` (or `[x, y]`) UI position → QPoint, or None when unusable.

        Shared by the two movable floating panels — the legend (`ui_legend_position`)
        and the minimap (`ui_minimap_position`, v1.4.6). A broken value costs neither
        panel its default spot (both callers fall back to their own corner), and a
        `bool` is rejected although Python says `isinstance(True, int)` is true.
        """
        coords = None
        if isinstance(raw, dict):
            coords = (raw.get("x"), raw.get("y"))
        elif isinstance(raw, (list, tuple)) and len(raw) == 2:
            coords = (raw[0], raw[1])
        if coords is None:
            return None
        x, y = coords
        if (isinstance(x, (int, float)) and isinstance(y, (int, float))
                and not isinstance(x, bool) and not isinstance(y, bool)):
            return QPoint(int(x), int(y))
        return None

    @staticmethod
    def _read_legend_settings():
        """`ui_legend*` from config.json → (visible, collapsed, position|None).

        Every broken value falls back to its default (visible, unfolded, the
        bottom-left corner) — a hand-edited config must never cost the panel or put it
        off-screen (`_position_legend` clamps a saved position into the view anyway).
        """
        visible, collapsed, position = True, False, None
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the panel is simply on
            return visible, collapsed, position
        if isinstance(cfg.get("ui_legend"), bool):
            visible = bool(cfg["ui_legend"])
        if isinstance(cfg.get("ui_legend_collapsed"), bool):
            collapsed = bool(cfg["ui_legend_collapsed"])
        position = MainWindow._saved_position(cfg.get("ui_legend_position"))
        return visible, collapsed, position

    def _position_legend(self):
        """Place the legend: the saved position (clamped into the view) or bottom-left.

        The top-right corner belongs to the minimap, the top-center to the search bar
        and the bottom-right to the map-collapse diamond — the bottom-left is the free
        one, and it is the default until the user drags the panel somewhere else.
        """
        legend = getattr(self, "legend", None)
        view = getattr(self, "view", None)
        if legend is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            position = getattr(self, "_legend_pos", None)
            if position is None:
                x = self.LEGEND_MARGIN
                y = max(self.LEGEND_MARGIN, h - legend.height() - self.LEGEND_MARGIN)
            else:
                x = min(max(int(position.x()), 0), max(w - legend.width(), 0))
                y = min(max(int(position.y()), 0), max(h - legend.height(), 0))
            legend.move(int(x), int(y))
            if legend.isVisible():
                legend.raise_()
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _toggle_legend(self, checked: bool):
        """v1.4.5: show/hide the legend + persist `ui_legend` (a merge write).

        v1.5rc4 (ROADMAP task 7): while the first-run hint is on screen the legend yields
        to it — the user's choice is REMEMBERED (`_legend_enabled` + `ui_legend`) but the
        panel stays hidden until the hint goes away. A temporary suppression never
        overwrites a saved visibility.
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return
        visible = bool(checked)
        try:
            legend.setVisible(visible)
            if visible:
                self._position_legend()
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._legend_enabled = visible
        self._save_legend_config({"ui_legend": visible})
        self._sync_legend_suppression()

    def _on_legend_moved(self, position):
        """The user dragged the panel: remember where (a merge write of the position).

        v1.5 (ROADMAP): a drop within `SNAP_PX` of an anchored edge (LEFT|BOTTOM) instead
        RE-ANCHORS the panel — the saved position is cleared and the documented
        bottom-left corner (plus every rule that hangs off it) comes back by itself.
        """
        try:
            pos = QPoint(int(position.x()), int(position.y()))
        except (TypeError, ValueError, AttributeError):
            return
        if self._snap_panel(getattr(self, "legend", None), pos, "lb"):
            self._legend_pos = None
            self._save_legend_config({"ui_legend_position": {"x": None, "y": None}})
            self._position_legend()
            return
        self._legend_pos = pos
        self._save_legend_config({"ui_legend_position": {"x": self._legend_pos.x(),
                                                         "y": self._legend_pos.y()}})

    def _on_legend_collapsed_changed(self, collapsed: bool):
        """The panel was folded/unfolded: persist it and re-place (its height changed)."""
        self._save_legend_config({"ui_legend_collapsed": bool(collapsed)})
        self._position_legend()

    def _save_legend_config(self, data: dict) -> None:
        """Merge-write the legend's own UI state (the `ui_minimap` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the toggle
            pass

    # ── v1.5.2 (ROADMAP task 3): the activity panel ─────────────────────────────
    # The surface of the history `modules/activity_log.py` keeps: a NON-MODAL window
    # (never a fifth floating panel — see `ui/activity_panel.py`, the placement is
    # decided there), fed by the SAME ring the logging tap fills. The window owns the
    # visibility key and the two taps; the panel owns nothing but its rows.

    @staticmethod
    def _read_activity_visible() -> bool:
        """`ui_activity_panel` from config.json → the saved visibility (default OFF).

        Off by default: the panel is a diagnostic surface, and a first run must not open
        a second window. A broken value costs the default — never the panel.
        """
        try:
            from i18n import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 — without a config the default (hidden) stands
            return False
        raw = cfg.get("ui_activity_panel")
        return bool(raw) if isinstance(raw, bool) else False

    def _save_activity_config(self, data: dict) -> None:
        """Merge-write the panel's own UI state (the `ui_legend` pattern)."""
        try:
            from i18n import save_config
            save_config(dict(data))
        except Exception:  # noqa: BLE001 — a cosmetic state must not break the toggle
            pass

    def _setup_activity_panel(self):
        """Create the panel and install the TWO taps of the history (v1.5.2, task 1).

        (a) the logging tap is installed by `modules/logger.py` (beside the file
        handler) and needs nothing here; (b) the status-bar tap is this connection:
        `statusBar().messageChanged` for the ordinary transient messages and the
        `UndoStatusBar.offer_shown` signal for the destructive actions' sentences — the
        Undo offer never travels through `messageChanged` (it replaces the temporary
        message), and losing exactly those lines would empty the history of the events a
        user is most likely to look for. Nothing else is rewired.
        """
        try:
            from ui.activity_panel import ActivityPanel
        except ImportError:  # flat layout: the ui/ directory itself is on sys.path
            try:
                from activity_panel import ActivityPanel
            except ImportError:  # a stripped build — no panel, the app works as before
                return
        try:
            panel = ActivityPanel(parent=self)
            panel.on_hidden = self._on_activity_hidden
            self.activity_panel = panel
        except Exception as e:  # noqa: BLE001 — a history surface must not break startup
            if self.log:
                self.log.warning(f"Activity panel unavailable: {e}")
            return
        if bool(getattr(self, "_activity_enabled", False)):
            try:
                panel.set_visible(True)
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        try:
            bar = self.statusBar()
            bar.messageChanged.connect(self._record_activity_message)
            offer = getattr(bar, "offer_shown", None)
            if offer is not None:
                offer.connect(self._record_activity_message)
        except (RuntimeError, AttributeError, TypeError):
            pass  # a status bar without the signal is still a working status bar

    def _record_activity_message(self, text):
        """The status-bar tap: one transient UI message → the history (v1.5.2).

        Called on EVERY `messageChanged`, an empty text included (Qt emits
        `messageChanged("")` on every clear) — `record_status_message()` drops it. A
        failure here must never reach the status bar: the history is cosmetic.
        """
        if _activity_mod is None:
            return
        try:
            _activity_mod.record_status_message(text)
        except Exception:  # noqa: BLE001 — the history must not break a status message
            pass

    def _toggle_activity(self, checked: bool):
        """v1.5.2: show/hide the activity panel + persist `ui_activity_panel`.

        The panel instance lives for the whole session (the history survives closing
        it), so the toggle only shows/hides — `ui/activity_panel.py` explains why.
        """
        panel = getattr(self, "activity_panel", None)
        if panel is None:
            return
        visible = bool(checked)
        try:
            panel.set_visible(visible)
        except RuntimeError:
            return  # Qt teardown — the panel is already destroyed
        self._activity_enabled = visible
        self._save_activity_config({"ui_activity_panel": visible})

    def _on_activity_hidden(self):
        """The panel was closed by the user (its X): make the View item tell the truth.

        The item OWNS the state, so the close is mirrored into it with BLOCKED signals
        (no `toggled` loop back into `set_visible`) and persisted — the next start
        opens the window only if it was left open.
        """
        action = getattr(self, "act_show_activity", None)
        self._activity_enabled = False
        if action is None:
            return
        try:
            if action.isChecked():
                action.blockSignals(True)
                try:
                    action.setChecked(False)
                finally:
                    action.blockSignals(False)
        except RuntimeError:
            return  # Qt teardown — the action is already destroyed
        self._save_activity_config({"ui_activity_panel": False})

    def _wire_view_toolbar_button(self, action_id: str, action) -> None:
        """v1.4.6: keep a toolbar VIEW toggle in step with its checkable menu item.

        The menu item is the OWNER of the state (and of the hotkey); the button mirrors
        it — the v1.4.5 legend rule, now for all four toggles (the sidebar, the map, the
        minimap, the legend). Called from `_setup_menubar` right after each QAction
        exists; the initial sync uses BLOCKED signals, so wiring cannot drive the owner.
        """
        if action is None:
            return
        try:
            action.toggled.connect(
                lambda checked, aid=action_id: self._sync_view_toolbar(aid, checked))
        except (RuntimeError, AttributeError):
            return
        self._sync_view_toolbar(action_id, action.isChecked())

    def _on_view_toolbar_toggled(self, action_id: str, checked: bool) -> None:
        """A toolbar VIEW button was clicked — drive the checkable menu item (the owner)."""
        action = getattr(self, _VIEW_TOOLBAR_ACTIONS.get(action_id, ""), None)
        if action is None:
            return
        try:
            if action.isChecked() != bool(checked):
                action.setChecked(bool(checked))   # emits toggled → the owner slot
        except RuntimeError:
            pass  # Qt teardown — the action is already destroyed

    def _sync_view_toolbar(self, action_id: str, checked: bool) -> None:
        """Follow the owner: set the mirror's checkmark with blocked signals (no loop).

        The guard `action.isChecked() != checked` drops a STALE emission: the collapse
        rule refuses a second strip by restoring the owner's checkmark with BLOCKED
        signals (`_reject_collapse_both`), and the `toggled(False)` that caused the
        refusal is still being delivered to the other slots — without the guard the
        mirror would end up showing the state the window is NOT in. The owner's LIVE
        value is the truth, so this is the same "follow the owner" rule, not a special
        case (the refusal also resyncs explicitly, which this guard then confirms).
        """
        action = getattr(self, _VIEW_TOOLBAR_ACTIONS.get(action_id, ""), None)
        if action is not None:
            try:
                if action.isChecked() != bool(checked):
                    return  # a stale emission — the owner already moved on
            except RuntimeError:
                pass  # Qt teardown — fall through and try the button
        button = (getattr(self, "_view_toolbar_buttons", None) or {}).get(action_id)
        if button is None:
            return
        try:
            if button.isChecked() == bool(checked):
                return
            button.blockSignals(True)
            try:
                button.setChecked(bool(checked))
            finally:
                button.blockSignals(False)
        except RuntimeError:
            pass  # Qt teardown

    def _toggle_map_search(self):
        """v0.9.8: Ctrl+F / "View -> Search map..." — open or close the panel."""
        if self.map_search.isVisible():
            self._close_map_search()
        else:
            self._open_map_search()

    def _open_map_search(self):
        """v0.9.8: show the panel, place it at the top center of the viewport, focus the input.

        If the field still holds a query (closed with Esc, the text is kept — as in a browser),
        re-activate it: recompute the matches/counter against the current scene.
        Otherwise Enter would point at the cleared self._map_search_query while the panel
        showed the old text and counter — a desync.
        """
        self.map_search.show()
        self.map_search.raise_()
        self._position_map_search_bar()
        # v1.4.2: the minimap steps BELOW the search bar; v1.5rc4 (task 7): the ONE place
        # that resolves the floating panels also moves the collapse diamond out of the way.
        self._sync_overlay_priority()
        if self.map_search.query.strip():
            self._on_map_search_query(self.map_search.query)
        self.map_search.focus_input()
        self.statusBar().showMessage(self.t("hint.map_search"))

    def _close_map_search(self):
        """v0.9.8: close the panel and clear the search state (dimming + frames).

        The tag filter stays active — _apply_map_dimming will recompute
        the dimming by it (the query is already cleared above).
        """
        if getattr(self, "map_search", None) is not None:
            self.map_search.hide()
        # v1.4.2: the minimap returns to the top-right corner; v1.5rc4 (task 7): the same
        # ONE resolver re-places the diamond now that the bar is gone.
        self._sync_overlay_priority()
        self._map_search_query = ""
        self._map_search_matches = []
        self._map_search_index = -1
        self._apply_map_dimming()
        try:
            self.statusBar().showMessage(self.t("status.ready"))
        except Exception:  # noqa: BLE001 — the status bar is cosmetic on teardown
            pass

    def _position_map_search_bar(self):
        """v0.9.8: the panel at the top center of the viewport (a child of the view, outside the layout)."""
        bar = getattr(self, "map_search", None)
        if bar is None or not bar.isVisible():
            return
        vp = self.view.viewport()
        w = min(bar.PREFERRED_WIDTH, max(vp.width() - 16, bar.MIN_WIDTH))
        x = max(8, (vp.width() - w) // 2)
        h = max(bar.sizeHint().height(), 30)
        bar.setGeometry(int(x), 10, int(w), int(h))

    def _map_search_nodes(self, query: str):
        """v0.9.8: nodes matching the query (alias/host/ip/comment — as in the sidebar)."""
        q = (query or "").strip().lower()
        if not q:
            return []
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return []
        out = []
        for node in nodes:
            d = node.data
            haystack = " ".join([d.alias, d.host, d.ip, d.comment]).lower()
            if q in haystack:
                out.append(node)
        return out

    def _on_map_search_query(self, query: str):
        """v0.9.8: the query text changed — recompute the matches and the dimming.

        The counter points at the FIRST result (the browser-search pattern);
        centering/selection — only on Enter (ROADMAP #2).
        """
        self._map_search_query = query or ""
        matches = self._map_search_nodes(query)
        self._map_search_matches = matches
        self._map_search_index = 0 if matches else -1
        self._apply_map_dimming()
        self.map_search.set_count(self._map_search_index + 1, len(matches))

    def _map_search_step(self, direction: int):
        """v0.9.8: Enter/Shift+Enter — stepping through the results (with wrapping).

        Selecting the node (the sidebar row follows the selection via _sync_selection_state),
        the view.centerOn centering and the reveal_flash flash frame — the same ready path
        as the v0.9.6 "Show on map" (the set_status pulse pattern). The matches
        are recomputed fresh: nodes may have been added/removed since the query.
        """
        matches = self._map_search_nodes(self._map_search_query)
        if not matches:
            q = (self._map_search_query or "").strip()
            try:
                self.statusBar().showMessage(self.t("status.no_matches", query=q))
            except Exception:  # noqa: BLE001 — a formatting failure is not critical
                self.statusBar().showMessage(f"No matches: {q}")
            return
        n = len(matches)
        base = self._map_search_index if 0 <= self._map_search_index < n else -1
        idx = (base + direction) % n
        self._map_search_matches = matches
        self._map_search_index = idx
        node = matches[idx]
        self._select_node(node, center=True)
        flash = getattr(node, "reveal_flash", None)
        if callable(flash):
            try:
                flash()
            except Exception:  # noqa: BLE001 — the accent is cosmetic; the navigation already worked
                pass
        self.map_search.set_count(idx + 1, n)

    def _close_map_search_if_open(self):
        """v0.9.8: close the search on a project switch (an old query about new nodes is stale)."""
        bar = getattr(self, "map_search", None)
        if bar is not None and bar.isVisible():
            self._close_map_search()

    # ── Review fix v0.8.0 (#3): node status markers in the sidebar tree ──
    # v0.9.9.4: the dot icons and row markers — SidebarPanel (apply_status_marker /
    # update_status_marker); the window passes the panel the node's current status.

    def _update_sidebar_status_marker(self, server_id: str) -> None:
        """Update the row marker in place (without a full tree rebuild)."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # the node is gone — nobody needs its status
        self.sidebar.update_status_marker(server_id, node.status, node.data.host or "")

    def _center_view(self):
        """UI polish: center on the map content, not on the origin.

        Before, centerOn(0, 0) — with nodes at negative coordinates the view went to
        an empty corner of the scene (a v0.8 review bug).
        v1.2.4.1 (task 5): the map is collapsed — a no-op (no exceptions, no auto-show).
        """
        if self._map_collapsed:
            return
        rect = self.view.content_bounding_rect()
        # v1.4.4 (ROADMAP task 1): "center the map" is an instant move — cancel a flight
        self.view.stop_camera_flight()
        if rect is None or rect.isEmpty():
            self.view.centerOn(0, 0)
            return
        self.view.centerOn(rect.center())

    def _fit_to_content(self):
        """UI polish: "Fit map" — all nodes and notes inside the visible area.

        v1.4.4 (ROADMAP task 2): the ACTION flies to the fit target (ui/motion.py — 250 ms,
        OutQuad, interruptible) instead of snapping; `MapView.fit_to_content()` stays the
        instant primitive for tools/tests and is the fallback when there is nothing to
        frame (an empty map → the same "nothing to fit" line) or the view has no geometry yet.
        v1.2.4.1 (task 5): the map is collapsed — a no-op (no exceptions, no auto-show).
        """
        if self._map_collapsed:
            return
        if not self.view.fly_to_content():
            self.statusBar().showMessage(self.t("status.fit_nothing"))

    def _on_zoom_changed(self, zoom: float):
        """UI polish: the zoom percentage in the status bar (the MapView.zoomChanged signal)."""
        try:
            self.zoom_label.setText(f"{int(round(zoom * 100))}%")
        except RuntimeError:
            pass  # Qt teardown — the status bar widget has already been destroyed

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

    # ── v1.4.5 (ROADMAP task 3): the status filter of the sidebar ────────────────

    def _on_status_filter_clicked(self, status: str):
        """A status counter was clicked: filter the sidebar by it, or reset on a repeat.

        The state is TRANSIENT (in memory only, never written to config.json): a
        restart must not leave a sidebar hiding servers for no visible reason. The
        signal is the same counter clicked a second time — a plain toggle, so "show me
        the offline ones" and "show me everything" are the same gesture.
        """
        status = str(status or "")
        if status not in STATUS_FILTER_ORDER:
            return
        self._status_filter = "" if getattr(self, "_status_filter", "") == status else status
        panel = getattr(self, "sidebar", None)
        if panel is not None:
            panel.set_status_filter(self._status_filter)
        self.refresh_sidebar()   # re-filters the tree + re-styles the counters
        try:
            if self._status_filter:
                self.statusBar().showMessage(
                    self.t("statusbar.filter.active",
                           status=self.t(f"legend.status.{self._status_filter}")))
            else:
                self.statusBar().showMessage(self.t("status.ready"))
        except Exception:  # noqa: BLE001 — the hint must not break the filter
            pass

    def _reset_zoom(self):
        # AUDIT v0.7.2 (low #19): the public MapView method instead of poking view._zoom
        self.view.reset_zoom()

    # ── v1.3.3.3 (ROADMAP task 2): the zoom actions of the View menu ──────────────
    # The step API lives on MapView (zoom_in/zoom_out/_zoom_by); these two slots only
    # add the "the map is collapsed" guard that every view action of the window has
    # (v1.2.4.1 task 5: a view action on a collapsed map is a silent no-op).

    def _zoom_in(self):
        """View → Zoom In (Ctrl+=): one step in, anchored on the view centre."""
        if self._map_collapsed:
            return
        self.view.zoom_in()

    def _zoom_out(self):
        """View → Zoom Out (Ctrl+-): one step out, anchored on the view centre."""
        if self._map_collapsed:
            return
        self.view.zoom_out()

    def _open_hotkey_sheet(self):
        """v1.5rc3 (ROADMAP task 4): the keyboard cheat-sheet window.

        Help → Keyboard shortcuts (F1) and the `?` key of the map both land here. The
        text is NOT built here: `ui/hotkey_sheet_dialog.py` renders the registry through
        `about_dialog.cheatsheet()` — the same function Help → About uses, so the two
        surfaces cannot drift (no second source of truth for the hotkeys). Never raises:
        a broken dialog must not take the window down.
        """
        try:
            from ui.hotkey_sheet_dialog import HotkeySheetDialog
        except ImportError:  # flat launch from the project root
            try:
                from hotkey_sheet_dialog import HotkeySheetDialog
            except ImportError as e:
                if self.log:
                    self.log.warning(f"Hotkey sheet unavailable: {e}")
                return
        try:
            dlg = HotkeySheetDialog(self)
            dlg.exec()
        except Exception as e:  # noqa: BLE001 — a UI error must not break the window
            if self.log:
                self.log.warning(f"Hotkey sheet failed: {e}")

    def keyPressEvent(self, event):
        """v1.5rc3 (ROADMAP task 4): `?` opens the cheat-sheet.

        A bare printable key must NOT be a window QShortcut: it would steal "?" from
        every text field of the application (the map search, a note, the filter).
        Handled at the WINDOW instead, it arrives only when no focused widget wanted
        the key — Qt propagates an ignored key event up the parent chain, so a field
        that inserts text never reaches this method. `Esc`-style control keys and the
        configurable actions stay with the registry (`help.cheatsheet` ships F1).
        """
        try:
            if (event.key() == Qt.Key_Question
                    and not (event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier)):
                self._open_hotkey_sheet()
                event.accept()
                return
        except (RuntimeError, AttributeError):
            pass  # a degenerate event — fall through to the default handling
        super().keyPressEvent(event)

    def _open_about_dialog(self):
        """v1.3.3.3 (task 6): Help → About — the version, the license, the paths, the
        config-folder button and the hotkey cheat-sheet built FROM the registry.

        A modal dialog (like the settings hub); the dialog is self-contained and
        read-only — closing it is the only outcome. Never raises: a broken dialog must
        not take the window down.
        """
        try:
            from ui.about_dialog import AboutDialog
        except ImportError:  # flat launch from the project root
            try:
                from about_dialog import AboutDialog
            except ImportError as e:
                if self.log:
                    self.log.warning(f"About dialog unavailable: {e}")
                return
        try:
            dlg = AboutDialog(self)
            dlg.exec()
        except Exception as e:  # noqa: BLE001 — a UI error must not break the window
            if self.log:
                self.log.warning(f"About dialog failed: {e}")

    def _open_profile_manager(self):
        """Open the profile manager dialog."""
        try:
            from ..dialogs.profile_manager_dialog import ProfileManagerDialog
        except ImportError:
            from dialogs.profile_manager_dialog import ProfileManagerDialog

        dlg = ProfileManagerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.statusBar().showMessage(self.t("status.profile_updated"))
            if self.log:
                self.log.info("Profile manager closed (saved)")

    def _open_log_file(self):
        """Open the log file in default text editor."""
        try:
            from modules.logger import get_log_file_path as _get
            path = _get()
            # Open with default application for the OS
            import os, subprocess
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, self.t("dialog.open_logs"), f"Failed to open:{e}")
