import os
import sys
import copy
import itertools
from typing import Optional, List, Dict

try:
    from ..graphics.map_scene import MapScene
    from ..graphics.map_view import MapView
    from ..graphics.server_node import ServerNode
    # v1.5.4 (ROADMAP tasks 1/2): the ONE declaration of "in trouble" — the group
    # aggregate and the "problems only" lens must mean the same thing by construction
    from ..graphics.node_group import is_in_trouble as node_in_trouble
except ImportError:
    from graphics.map_scene import MapScene
    from graphics.map_view import MapView
    from graphics.server_node import ServerNode
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

try:  # v1.6.5 (ROADMAP tasks 4/5): the ONE gate of an unmanaged card (the menu rows ask it)
    from ..ui import unmanaged as _unmanaged_gate
except ImportError:  # flat launch from the project root
    try:
        from ui import unmanaged as _unmanaged_gate
    except ImportError:  # flat layout without ui/unmanaged — nothing is ever gated
        _unmanaged_gate = None

# AddServerDialog / ConnectionDialog / SSHConnectDialog / SSHTerminalWindow / _ext_term are TEST
# SUBSTITUTION POINTS (`MW.<name> = Fake`): the methods moved to the mixins
# (`NodeOpsMixin._add_server`/_add_connection, `SshMixin._run_ssh_connect`/_spawn_terminal_window/
# _connect_ssh_external) resolve them from THIS module at call time (`host_attr`), so the imports stay
# here even when the core no longer uses them directly (`AGENTS.md` §4.1).

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
except ImportError:
    from sidebar import SidebarPanel

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


from PySide6.QtCore import Qt, QTimer, Signal, QPoint  # QPoint — the shared `_saved_position()` parser
from PySide6.QtGui import (
    QAction,    # v1.4rc1: the per-plugin rows of the "Plugins" menu (insertAction)
    QMouseEvent,
    QUndoStack,  # v0.8.3: undo/redo
    QKeySequence,  # v1.3.2: an empty sequence = the multi-input hotkey is not installed
    QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,  # v1.2.4.1: collapse strips/diamonds
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter,
    QLabel,  # the status-bar/permanent labels (the sidebar tree lives in ui/sidebar.py)
    QToolBar, QMessageBox, QDialog, QMenu, QDockWidget,
    QFileDialog,  # the class-level test seam every export path is swapped through (MODULE_FACADE_SEAMS)
    QApplication, QToolButton,  # QToolButton — exit button on the multi-input plaque (v1.2.3)
)

# v1.1.4 (ROADMAP): the window is a FACADE — 22 clusters live in `ui/main_window_*.py` mixins (the
# project I/O, the node/connection ops, the SSH/terminals, the statuses, the plugins, the settings,
# the scene commands, the exports, the floating panels, the minimap, the legend, the activity and
# bookmarks panels, the sidebar, the menubar, the toolbar, the status bar, the panels, the view,
# the theme, the re-text walk and the assembly). The mixins NEVER import this module — duck typing.
try:
    from .main_window_project_io import ProjectIOMixin
    from .main_window_node_ops import NodeOpsMixin
    from .main_window_ssh import SshMixin
    from .main_window_status import StatusMixin
    from .main_window_plugins import PluginMixin
    from .main_window_settings import SettingsMixin
    from .main_window_scene import SceneCommandMixin
    from .main_window_exports import ExportMixin
    from .main_window_overlays import OverlaysMixin
    from .main_window_minimap import MinimapMixin
    from .main_window_legend import LegendMixin
    from .main_window_activity import ActivityMixin
    from .main_window_bookmarks import BookmarksMixin
    from .main_window_sidebar import SidebarMixin
    from .main_window_menubar import MenubarMixin
    from .main_window_toolbar import (ToolbarMixin, _VIEW_TOOLBAR_ACTIONS,
                                      _VIEW_TOOLBAR_ITEMS)
    from .main_window_statusbar import (StatusBarMixin, STATUS_FILTER_ORDER, _ProblemsChip,
                                        _StatusCounter)
    from .main_window_panels import PanelsMixin, _CollapseStrip, _WIDGET_MAX_WIDTH, _diamond_icon
    from .main_window_view import ViewMixin
    from .main_window_theme import ThemeMixin
    from .main_window_i18n import I18nMixin
    from .main_window_layout import LayoutMixin
except ImportError:  # flat layout without the package (same pattern as the imports above)
    from main_window_project_io import ProjectIOMixin
    from main_window_node_ops import NodeOpsMixin
    from main_window_ssh import SshMixin
    from main_window_status import StatusMixin
    from main_window_plugins import PluginMixin
    from main_window_settings import SettingsMixin
    from main_window_scene import SceneCommandMixin
    from main_window_exports import ExportMixin
    from main_window_overlays import OverlaysMixin
    from main_window_minimap import MinimapMixin
    from main_window_legend import LegendMixin
    from main_window_activity import ActivityMixin
    from main_window_bookmarks import BookmarksMixin
    from main_window_sidebar import SidebarMixin
    from main_window_menubar import MenubarMixin
    from main_window_toolbar import (ToolbarMixin, _VIEW_TOOLBAR_ACTIONS,
                                     _VIEW_TOOLBAR_ITEMS)
    from main_window_statusbar import (StatusBarMixin, STATUS_FILTER_ORDER, _ProblemsChip,
                                       _StatusCounter)
    from main_window_panels import PanelsMixin, _CollapseStrip, _WIDGET_MAX_WIDTH, _diamond_icon
    from main_window_view import ViewMixin
    from main_window_theme import ThemeMixin
    from main_window_i18n import I18nMixin
    from main_window_layout import LayoutMixin

# The LIVE-NAMESPACE SEAMS, declared once: every name a `ui/main_window_*.py` mixin resolves on THIS
# module at call time (`host_attr`), every Qt facade a suite patches on the shared CLASS
# (`MW.QFileDialog`, `MW.QMenu`, `MW.QMessageBox`) and every cluster widget the mixins re-export. The
# declaration IS the seam — it keeps the name importable, it is the `MW.<name> = Fake` substitution
# point, and it stops a static analyser from reading a live seam as a dead import — so it comes LAST.
MODULE_FACADE_SEAMS = (
    # ── the dialogs and containers a suite substitutes on this module ──
    AddServerDialog, ConnectionDialog, SSHConnectDialog, SshConfigImportDialog,
    BulkEditDialog, ArrangeGroupDialog, ExportOptionsDialog, SSHTerminalWindow,
    # ── the Qt facades patched on the shared class (a module attribute would not reach them) ──
    QFileDialog, QMenu, QMessageBox,
    # ── the module-level facades the mixins resolve here (a stripped build sets some to None) ──
    _ext_term, set_action_icon, refresh_action_icon, _icons_mod, theme_qss,
    UndoStatusBar, status_bar_is_compact, status_bar_needed_width, SidebarPanel,
    MapScene, MapView, restore_splitter_state, theme,
    # ── the Qt classes a wave-3 mixin instantiates through the facade (the layout assembly, the ──
    # ── panels/statusbar widgets and the theme walk), so `MW.QWidget = Fake` stays possible ──
    Qt, Signal, QWidget, QHBoxLayout, QSplitter, QLabel, QToolBar, QDockWidget, QToolButton,
    QApplication, QAction, QKeySequence, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
    # ── the cluster widgets and tables the wave-3 mixins re-export (`MW._CollapseStrip`, ──
    # ── `MW._VIEW_TOOLBAR_ITEMS`), which the suite reads on the FACADE ──
    _CollapseStrip, _diamond_icon, _WIDGET_MAX_WIDTH, STATUS_FILTER_ORDER, _StatusCounter,
    _ProblemsChip, _VIEW_TOOLBAR_ITEMS, _VIEW_TOOLBAR_ACTIONS,
)


# ── dropping a project onto the window ────────────────────────────────────────
# Dragging a saved `.json`/`.sshmap` onto the window is the standard gesture of the platform. The drop
# is deliberately narrow — ONE local existing FILE with a project suffix — and it goes through
# `_load_project_at()` (the File → Open entry point), so every downstream rule (the autosave prompt,
# the undo reset, the status round, the MRU) is shared instead of re-implemented (`AGENTS.md` §4.1).

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


class MainWindow(ProjectIOMixin, NodeOpsMixin, SshMixin, StatusMixin, PluginMixin, SettingsMixin,
                 SceneCommandMixin, ExportMixin, OverlaysMixin, MinimapMixin, LegendMixin,
                 ActivityMixin, BookmarksMixin, SidebarMixin, MenubarMixin, ToolbarMixin,
                 StatusBarMixin, PanelsMixin, ViewMixin, ThemeMixin, I18nMixin, LayoutMixin,
                 QMainWindow):
    """The window FACADE: the assembly, the lifecycle and the undo core (AGENTS.md §4.1)."""

    def __init__(self):
        super().__init__()

        # ── the SAVED theme, before anything is built ──
        # `main.py` applies it too (even earlier, right after QApplication), but the window does not
        # depend on that: a MainWindow created directly (a test, an embedder) must still come up in the
        # user's theme, and every widget below is CONSTRUCTED with the right palette instead of being
        # repainted afterwards (`theme_from_settings` never fails, `apply_theme` never raises).
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
        # IDs of nodes with an active SSH session (for indicator reset)
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

        # ── configurable hotkeys ─────────
        # The registry (`ui/hotkey_registry.py`) is the single source of truth: every QAction/QShortcut with
        # a hotkey is registered under its action_id instead of carrying a literal sequence; `_apply_hotkeys()`
        # (after the UI construction and after the settings dialog's OK) installs the effective sequences from
        # `~/.sshmap/config.json` ("hotkeys"). Initialized BEFORE `_setup_ui`/`_setup_toolbar`/`_setup_menubar`.
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

        # ── the activity panel ────────────
        # The saved visibility is read BEFORE `_setup_menubar` builds the checkable View item (the
        # legend/minimap pattern: the menu item is the OWNER of the state, the panel follows it). The ring
        # itself is the process-wide singleton of `modules/activity_log.py` — the panel only renders it, so
        # a window that is closed and reopened loses no history.
        self._activity_enabled = MainWindow._read_activity_visible()
        self.activity_panel = None

        # ── the Plugins window ────────────
        # The saved visibility is read BEFORE `_setup_menubar` builds its checkable Plugins-menu item
        # (the `ui_activity_panel` rule) and the panel itself is built right AFTER the menubar. The
        # SESSION RING it owns lives as long as the process, so closing the window loses no history.
        self._plugins_window_enabled = MainWindow._read_plugins_window_visible()
        self.plugins_panel = None

        # ── the bookmarks panel ────────────
        # The saved visibility is read BEFORE `_setup_menubar` builds the checkable View item (the
        # `ui_activity_panel` rule: the menu item is the OWNER of the state, the panel follows it). The
        # store behind the panel is the module-level singleton of `modules/bookmarks.py` — the LIST is
        # application-level and lives outside every project (`AGENTS.md` §4.23).
        self._bookmarks_enabled = MainWindow._read_bookmarks_visible()
        self._bookmarks_pos = None
        self.bookmark_panel = None

        # ── the plugin registry ─────
        # The manager is created HERE because the "Plugins" menu is built from it; the DISCOVERY itself runs
        # later — main.py calls `start_plugin_discovery()` after `show()` and before `app.exec()`, so merely
        # constructing a window (every test does) never imports third-party code. The rows are rebuilt from
        # the records and `_plugin_rows` holds the dynamic QActions, so a rebuild removes only its own items.
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
        # v1.8.3 (ROADMAP task 1): the Plugins window + the two taps of its session ring — the
        # drained discovery events and the per-node answers of a plugin's run. AFTER the menubar
        # (the Plugins-menu item owns its visibility) and BEFORE `_apply_ui_translations()` below.
        self._setup_plugins_panel()
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

        # ── background node status checks (online/warn/offline) ──
        # Probes run in a separate thread, so the GUI is not blocked. Interval/timeout come from
        # `~/.sshmap/config.json` (`status_interval_sec` / `status_probe_timeout_sec`) and change
        # live from the settings dialog. Probes within a round run in parallel (ThreadPoolExecutor,
        # `status_max_parallel`, default 16); for large maps the interval doubles.
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
            # v1.6.6 (ROADMAP task 2): the checker is told the CADENCE the config declares
            # before anything can arm a round — `status_interval_sec = 0` is the manual-only
            # sentinel, and the mode has to be in place before `start_status_checks()` and
            # before any project load could start a round of its own.
            try:
                self._status_checker.set_manual_only(bool(_st_cfg.get("manual", False)))
            except Exception as e:  # noqa: BLE001 — the probes must run without the mode too
                if self.log:
                    self.log.warning(f"Manual-only status mode not applied: {e}")
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

        # ── the freshness tick ──────────
        # A status is a fact with a timestamp, so the map re-reads the age of every shown status a few
        # times per minute. This timer starts NO probe round and changes NO status: it only moves a card
        # to the stale mark once its datum has really aged past `StatusChecker.stale_threshold_s()`.
        # In a headless test without an event loop it never fires — the module stays smoke-test safe.
        self._freshness_timer = QTimer(self)
        self._freshness_timer.setInterval(self.FRESHNESS_TICK_MS)
        self._freshness_timer.timeout.connect(self._freshness_tick)
        self._freshness_timer.start()

        # ── autosave ────────────────────────
        # QTimer at the interval from `~/.sshmap/config.json` (`autosave_interval_sec`, default 60 s;
        # `autosave_enabled` — on/off). A tick writes an autosave ONLY when dirty and a project file is
        # set (a new unsaved project has nothing to restore — see `_autosave_tick`). The settings dialog
        # has its row in the hub.
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
        # while the mode is on (the v1.2.3 rule).
        try:
            self._sync_multi_shortcut()
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Apply multi-input hotkey failed: {e}")


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
                if self._i18n_available else "Undone.")
        except Exception as e:
            if self.log:
                self.log.warning(f"undo failed: {e}")

    def _redo(self):
        try:
            self.undo_stack.redo()
            self.statusBar().showMessage(
                self.t("status.redone") if self._i18n_available else "Redone.")
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
        # dock/toolbar layout only, so the [sidebar | map] divider needs its own key
        # (`ui_splitter_state`) or it starts at the default 250/950 on every start.
        try:
            save_splitter_state("ui_splitter_state", getattr(self, "_splitter", None))
        except Exception:  # noqa: BLE001 — the widths must not block closing
            pass

        # v1.7.3 (ROADMAP v1.7.3, task 2): the per-server directory memory of EVERY live Files
        # container — the terminal windows and the dock alike — goes out in ONE merged write here,
        # because the map is application-level and the close is the one moment every session is
        # still alive. Same rule as the geometry above: it must never block the close.
        try:
            self._save_remembered_dirs()
        except Exception:  # noqa: BLE001 — the memory must not block closing
            pass

        # v0.9.7: autosave stops BEFORE the dialog — while the user decides
        # (Save/Discard/Cancel) no writes to ~/.sshmap/autosave are needed.
        try:
            self._autosave_timer.stop()
        except Exception:  # noqa: BLE001 — teardown robustness (C++ object RuntimeError)
            pass

        # Stopping background QThreads happens on ANY exit, and the call stands on EVERY exit path
        # (the early dialog branches included): with unsaved changes the running
        # SystemInfoCollector / ping / DNS threads would otherwise be destroyed with the QObject
        # ("QThread: Destroyed while thread is still running"). The threads are stopped BEFORE the
        # dialog — it may keep the window open indefinitely.
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

        # Ping, reverse DNS and import DNS resolution. A `stop()` with a cancel flag exists ONLY on
        # `_import_resolve_thread` (`HostResolverThread.stop` — sets an Event, the loop exits
        # between names); `PingThread` / `ReverseDnsThread` have NO stop(), so the current
        # `getaddrinfo`/ping runs out its timeout and a thread that outlives the wait budget below
        # goes to the orphan registry, as do the reachability reports (`_diagnose_threads`).
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
                # On shutdown the "ask" gate is skipped — the thread is already stopped
                # (`stop_thread()` inside `close_terminal()`), so there is nothing to decide. With
                # `terminal_close_behavior="ask"` a QMessageBox.question per active session made "Cancel"
                # meaningless (the window closed regardless of the answer). The same path as the session
                # limit: `_force_close` — a confirmed decision, no re-asking.
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

        # ping/DNS/import-resolve threads that outlive the wait budget (`getaddrinfo`/ping with an
        # unreachable resolver) are registered in the orphan registry — a live QThread without a strong
        # referrer must not be left to GC ("QThread: Destroyed while thread is still running" on all exit
        # paths). Terminal threads have their own N4 path (`page.shutdown()` →
        # `modules/ssh_terminal._orphan_threads`) — not duplicated here.
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


    # ── v1.1: the settings dialog (hub) — ROADMAP v1.1, tasks 1–7 ────────────────

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
            # v1.6.5 (ROADMAP task 4): and so do the permanent Edit items of the SSH
            # family — an unmanaged card disables them in place.
            self._sync_gated_actions()
        except RuntimeError:
            # PySide6/Qt teardown on process exit: the scene's C++ object is already
            # destroyed, yet the selectionChanged signal reached a live Python slot.
            # A normal state — silently ignore it (otherwise a traceback in the console).
            pass

    def _sync_gated_actions(self):
        """Disable the Edit-menu verbs an UNMANAGED selection cannot serve (v1.6.5).

        The permanent Edit items of the SSH family ("Connect via SSH", "Gather information",
        "Check statuses now", "Why is it offline?") are the HOTKEY targets of the registry,
        so they live for the whole session and cannot be rebuilt per node the way a context
        menu is: they are enabled/disabled HERE, at the ONE moment the selection is synced —
        `ui/unmanaged.REGISTRY_ACTION_IDS` names them and the sentence is the gate's own, so
        a row disabled in this menu reads exactly like the one disabled in a context menu.
        A selection of several cards is left alone: the batch paths filter the unmanaged
        members themselves, and refusing the whole selection over one neighbour would be
        wrong. Never raises — a selection change can arrive during Qt teardown.
        """
        if _unmanaged_gate is None:
            return
        try:
            nodes = self.selected_nodes()
        except (AttributeError, RuntimeError):
            return
        target = nodes[0] if len(nodes) == 1 else None
        targets = getattr(self, "_hotkey_targets", None) or {}
        for action_id in _unmanaged_gate.REGISTRY_ACTION_IDS:
            blocked = target is not None and _unmanaged_gate.blocked_registry_action(action_id, target)
            for act in list(targets.get(action_id, ()) or ()):
                try:
                    act.setEnabled(not blocked)
                    act.setToolTip(
                        _unmanaged_gate.refusal_text(self.t, act.text().replace("&", "").strip())
                        if blocked else "")
                except (RuntimeError, AttributeError):
                    pass  # Qt teardown / a QShortcut without a text — the row is cosmetic

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


    # ── the map dimming: the ONE owner of the highlight state ──
    # The tag filter, the search, the lens and the arrow hover all write their state on the window;
    # `_apply_map_dimming()` merges them into ONE highlight decision.

    def _hover_focus(self):
        """v1.4.4 (ROADMAP task 4): the arrow under the cursor (the scene's focus), or None."""
        try:
            getter = getattr(self.scene, "hover_focus_arrow", None)
            return getter() if callable(getter) else None
        except (AttributeError, RuntimeError):
            return None

    # ── v1.8.4 (ROADMAP task 2): the DEPENDENCY focus — the reverse traversal ──────
    # The second channel of the dim state below: the ROOT is ONE node id and the closure of the
    # arrows that point AT it (`MapScene.dependency_closure()`) is recomputed on every dim pass
    # from the LIVE scene, so a deleted node or a loaded project drops the highlight by itself.

    def _dependency_root(self) -> str:
        """The node id the dependency highlight was asked about (`""` — none)."""
        return str(getattr(self, "_dependency_focus", "") or "")

    def _dependency_ids(self) -> set:
        """The node ids the dependency highlight covers — the live closure, `set()` if none.

        An empty set means "the channel is OFF": either nothing was asked or the root left the
        map (a delete, a project load) — and a highlight with nothing to show must never dim
        the whole map.
        """
        root = self._dependency_root()
        if not root:
            return set()
        try:
            if self.scene.get_node(root) is None:
                return set()
            return set(self.scene.dependency_closure(root))
        except (AttributeError, RuntimeError):
            return set()

    def _dependency_focus_text(self, node_id) -> str:
        """The status-bar ANSWER of the gesture — how many cards depend on this one.

        A card with no arrow into it is an answer too ("nothing depends on it"), so the line
        says which of the two happened; the translator is an ARGUMENT-safe read of the shipped
        keys (`status.map_dependents` / `status.map_dependents_none`).
        """
        try:
            node = self.scene.get_node(node_id)
            alias = str(getattr(getattr(node, "data", None), "alias", "") or "") or str(node_id)
        except (AttributeError, RuntimeError):
            alias = str(node_id)
        try:
            members = self._dependency_ids()
            count = max(len(members) - 1, 0)
        except (AttributeError, RuntimeError):
            count = 0
        if count <= 0:
            return (self.t("status.map_dependents_none", alias=alias) if self._i18n_available
                    else f"Nothing depends on «{alias}»")
        return (self.t("status.map_dependents", count=count, alias=alias)
                if self._i18n_available
                else f"{count} cards depend on «{alias}»")

    def _toggle_dependency_focus(self, node_id) -> bool:
        """Ctrl+click on a card: set the dependency highlight on it, or drop the same one.

        Answers True while a highlight is ON after the call. Never touches the scene: a
        highlight is a VIEW state (AGENTS.md §4.2), and the selection Qt performs on the same
        Ctrl+click is left exactly as it was.
        """
        wanted = str("" if node_id is None else node_id)
        if not wanted:
            return False
        if wanted == self._dependency_root():
            return self._set_dependency_focus("")
        if not self._set_dependency_focus(wanted):
            return False
        self.statusBar().showMessage(self._dependency_focus_text(wanted))
        return True

    def _set_dependency_focus(self, node_id) -> bool:
        """The ONE writer of the dependency root: store it, re-dim, report whether it is ON."""
        wanted = str("" if node_id is None else node_id)
        if wanted and wanted != self._dependency_root():
            try:
                if self.scene.get_node(wanted) is None:
                    return False
            except (AttributeError, RuntimeError):
                return False
        self._dependency_focus = wanted
        self._apply_map_dimming()
        return bool(self._dependency_ids())

    def _clear_dependency_focus(self) -> bool:
        """Drop the dependency highlight (a plain click, Esc, a loaded project). True if it was on."""
        if not self._dependency_root():
            return False
        self._dependency_focus = ""
        self._apply_map_dimming()
        return True

    def _apply_map_dimming(self):
        """v0.9.4/v0.9.8/v1.4.4/v1.5.4/v1.8.4: dimming + highlighting of the active filters on the map.

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
          the lens cannot stack into a "stuck" opacity (the ROADMAP's "one owner" rule);
        - the v1.8.4 DEPENDENCY focus (ROADMAP task 2): the same merge for the reverse
          traversal — the closure of a Ctrl+clicked card is read back and the rest recedes.
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
        dependents = self._dependency_ids()
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
            if dependents:
                # The dependency focus wins over the three filters (it is the question the
                # user just asked) and the accent frame marks the closure; it in turn yields
                # to the TRANSIENT arrow hover below.
                if str(getattr(node.data, "id", "")) in dependents:
                    dimmed, matched = False, True
                else:
                    dimmed, matched = True, False
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


    # ── the floating panels re-attach by dropping on an edge ──────────────────────

    #: How close a dropped panel's edge must land to the VIEW edge it is anchored to before the drop
    #: counts as "put me back": twice the 12 px default margin. A drag is otherwise PERMANENT — the
    #: saved position wins over the corner for good, and hiding/showing a panel does not clear it — so
    #: this threshold is the ONE way back to the documented corner that needs no hand-edited
    #: `config.json`. An explicit "Reset panel positions" action was considered and REJECTED.
    SNAP_PX = 24

    def _snap_panel(self, panel, position, edges: str) -> bool:
        """Re-anchor a dropped panel that landed at an edge it hangs from.

        `edges` names the anchored edges of the panel: "lb" = LEFT|BOTTOM (the legend),
        "rt" = RIGHT|TOP (the minimap), "lt" = LEFT|TOP (the bookmarks panel). A drop
        within `SNAP_PX` of ANY of them re-anchors the panel: the saved position is
        CLEARED with the `{"x": null, "y": null}` sentinel (`_saved_position()` already
        reads it as "no saved position", and `save_config()` is a merge and therefore
        cannot DELETE a key) and the ordinary placement of the panel runs, so every
        anchored rule comes back by itself — the documented corner, the fold that hangs
        off the edge, the minimap's step below an open search bar and the placement a
        resize recomputes.

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

    @staticmethod
    def _saved_position(raw):
        """A saved `{x, y}` (or `[x, y]`) UI position → QPoint, or None when unusable.

        Shared by the three movable floating panels — the legend (`ui_legend_position`),
        the minimap (`ui_minimap_position`) and the bookmarks panel
        (`ui_bookmarks_position`). A broken value costs no panel its default spot (each
        caller falls back to its own corner), and a `bool` is rejected although Python
        says `isinstance(True, int)` is true.
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

    def _open_known_hosts_manager(self):
        """v1.8.1: Profile → Known hosts — what `~/.sshmap/known_hosts` records, and its two edits.

        The store is the ONE owner of the file, so the dialog only asks it; the window stays the
        assembly and the dialog is self-contained. Never raises: a UI error must not break the window.
        """
        try:
            from .trust_surface import open_known_hosts_manager
        except ImportError:  # flat launch from the project root
            from ui.trust_surface import open_known_hosts_manager
        try:
            open_known_hosts_manager(self)
        except Exception as e:  # noqa: BLE001 — a UI error must not break the window
            if self.log:
                self.log.warning(f"Known-hosts manager failed: {e}")

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
            QMessageBox.warning(self, self.t("dialog.open_logs"),
                                self.t("msg.open_failed", error=e))
