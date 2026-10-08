# -*- coding: utf-8 -*-
"""`1.8rc3` — waves 1–3 of the MainWindow split: the mixins, the facade and the structural pins.

The three waves moved 19 clusters of `ui/main_window.py` (the statuses, the plugins, the settings
appliers, the scene commands, the exports, the floating panels, the minimap, the legend, the activity
and bookmarks panels, the sidebar, the menubar, the toolbar, the status bar, the panel mechanism, the
view commands, the theme, the re-text walk and the window assembly) into `ui/main_window_*.py` mixins
with NO behaviour change — the same bodies, the same public names, the same `MW.<name>` seams. This
file pins the STRUCTURE: the family, the MRO, the one-owner rule, the cycle, the headers, the seams.
"""
import ast
import os
import re
import sys

from _common import (bootstrap, check, finish, check_i18n_parity, check_i18n_format,
                     check_release_state, load_i18n_langs, window_family_files,
                     window_family_sources, window_func_body, window_func_owner,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, releases_at_least)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import ui.main_window as MW  # noqa: E402
import ui.main_window_node_ops as MWO  # noqa: E402
import ui.main_window_status as MWST  # noqa: E402
import ui.main_window_plugins as MWPL  # noqa: E402
import ui.main_window_settings as MWSE  # noqa: E402
import ui.main_window_scene as MWSC  # noqa: E402
import ui.main_window_exports as MWEX  # noqa: E402
import ui.main_window_overlays as MWOV  # noqa: E402
import ui.main_window_minimap as MWMM  # noqa: E402
import ui.main_window_legend as MWLE  # noqa: E402
import ui.main_window_activity as MWAC  # noqa: E402
import ui.main_window_bookmarks as MWBK  # noqa: E402
import ui.main_window_sidebar as MWSB  # noqa: E402
import ui.main_window_menubar as MWMB  # noqa: E402
import ui.main_window_toolbar as MWTB  # noqa: E402
import ui.main_window_statusbar as MWSBR  # noqa: E402
import ui.main_window_panels as MWPN  # noqa: E402
import ui.main_window_view as MWVW  # noqa: E402
import ui.main_window_theme as MWTH  # noqa: E402
import ui.main_window_i18n as MWI1  # noqa: E402
import ui.main_window_layout as MWLY  # noqa: E402
from ui.mixin_support import host_attr  # noqa: E402
from version import APP_VERSION, VERSION_FORMAT  # noqa: E402

LANGS = load_i18n_langs(ROOT)

# The wave's PLAN: the five new files, their mixin, their methods — the ONE table this file audits.
WAVE = {
    "ui/main_window_status.py": ("StatusMixin", MWST.StatusMixin, [
        "_shutdown_status_checker", "start_status_checks", "_status_skip_ids", "_refuse_unmanaged",
        "_sync_status_targets", "_on_node_status_detail", "_on_node_status_changed",
        "_apply_node_freshness", "_refresh_status_freshness", "_apply_node_info_freshness",
        "_freshness_tick"]),
    "ui/main_window_plugins.py": ("PluginMixin", MWPL.PluginMixin, [
        "start_plugin_discovery", "_reload_plugins", "_populate_plugin_items", "_sync_plugin_nodes",
        "_plugin_records_with_hook", "_extend_node_context_menu", "_run_plugins_on_nodes",
        "_plugin_tooltip", "_on_plugin_toggled", "_report_plugin_events", "_plugin_label",
        "_on_plugin_status_requested", "_expire_plugin_status", "_on_plugin_hook_failed",
        "_on_plugin_hook_timeout"]),
    "ui/main_window_settings.py": ("SettingsMixin", MWSE.SettingsMixin, [
        "_apply_ui_options_from_config", "_apply_settings_from_dialog"]),
    "ui/main_window_scene.py": ("SceneCommandMixin", MWSC.SceneCommandMixin, [
        "_connect_note_signals", "_on_note_text_edited", "_add_note_at", "_remove_note",
        "_attach_note_to_node", "_detach_note", "_commit_group_move", "_commit_group_resize",
        "_connect_group_signals", "_toggle_group_collapsed", "_connect_background_signals",
        "_commit_background_move", "_commit_background_resize", "_set_background_image",
        "_remove_background_image", "_add_group_at", "_rename_group", "_remove_group"]),
    "ui/main_window_exports.py": ("ExportMixin", MWEX.ExportMixin, [
        "_ask_export_palette", "_export_map_image", "_export_map_drawio", "_export_map_pdf",
        "_export_map_svg", "_copy_map_image", "_export_docs_frame", "_list_report_rows",
        "_report_table_unavailable", "_export_connections_table", "_export_problems_table",
        "_copy_list_table", "_export_list_table"]),
}
# The wave-2 PLAN: the six floating-panel / sidebar files, their mixin and their methods. `_snap_panel`,
# `_saved_position` and `SNAP_PX` STAY in the facade — the three movable panels share them.
WAVE2 = {
    "ui/main_window_overlays.py": ("OverlaysMixin", MWOV.OverlaysMixin, [
        "_sync_overlay_priority", "_sync_legend_suppression", "legend_suppressed",
        "_setup_filter_plaque", "_sync_filter_plaque", "_position_filter_plaque", "_on_filter_clear",
        "_setup_map_search", "_toggle_map_search", "_open_map_search", "_close_map_search",
        "_position_map_search_bar", "_map_search_nodes", "_on_map_search_query", "_map_search_step",
        "_close_map_search_if_open", "_connect_hint_text", "_setup_empty_state", "_sync_empty_state",
        "_position_empty_state", "_position_map_collapse_btn", "_overlay_panel_rects",
        "_collapse_btn_candidates"]),
    "ui/main_window_minimap.py": ("MinimapMixin", MWMM.MinimapMixin, [
        "_setup_minimap", "_read_minimap_settings", "_on_minimap_collapsed_changed", "_on_minimap_moved",
        "_save_minimap_config", "_toggle_minimap", "_position_minimap", "_on_minimap_center"]),
    "ui/main_window_legend.py": ("LegendMixin", MWLE.LegendMixin, [
        "_setup_legend", "_read_legend_settings", "_position_legend", "_toggle_legend",
        "_on_legend_moved", "_on_legend_collapsed_changed", "_save_legend_config"]),
    "ui/main_window_activity.py": ("ActivityMixin", MWAC.ActivityMixin, [
        "_read_activity_visible", "_save_activity_config", "_setup_activity_panel",
        "_record_activity_message", "_toggle_activity", "_on_activity_hidden"]),
    "ui/main_window_bookmarks.py": ("BookmarksMixin", MWBK.BookmarksMixin, [
        "_read_bookmarks_visible", "_read_bookmarks_settings", "_save_bookmarks_config",
        "_setup_bookmarks_panel", "_position_bookmarks_panel", "_toggle_bookmarks",
        "_on_bookmarks_moved", "_on_bookmarks_collapsed_changed", "_open_bookmarks_dialog"]),
    "ui/main_window_sidebar.py": ("SidebarMixin", MWSB.SidebarMixin, [
        "_on_tree_item_clicked", "_on_tree_item_double_click", "_on_sidebar_context_menu",
        "_reveal_node_on_map", "refresh_sidebar", "_active_tag_filter", "_on_tag_filter_changed",
        "_on_status_filter_clicked", "_update_sidebar_status_marker"]),
}
# The wave-3 PLAN: the menubar, the toolbar, the status bar, the panel mechanism, the view commands,
# the theme, the re-text walk and the window assembly — the "wave 3 + the close" slot, which finishes
# the split and leaves the facade under 2 000 lines. `_snap_panel` / `_saved_position` / `SNAP_PX` STAY
# in the facade (the three movable panels share them), and so do the assembly's own lifecycle and the
# map's ONE dim owner.
WAVE3 = {
    "ui/main_window_menubar.py": ("MenubarMixin", MWMB.MenubarMixin, [
        "_add_menu_action", "_setup_menubar", "_rebuild_qaction_guard", "_populate_language_menu",
        "_reload_languages"]),
    "ui/main_window_toolbar.py": ("ToolbarMixin", MWTB.ToolbarMixin, [
        "_setup_toolbar", "_toolbar_full_width", "_sync_toolbar_overflow",
        "toolbar_overflow_active", "_mark_toolbar_mirror", "_wire_view_toolbar_button",
        "_on_view_toolbar_toggled", "_sync_view_toolbar", "_panel_switch_actions",
        "createPopupMenu"]),
    "ui/main_window_statusbar.py": ("StatusBarMixin", MWSBR.StatusBarMixin, [
        "_sync_status_bar_overflow", "_status_bar_permanent_widgets",
        "_status_bar_overflow_needed", "status_bar_compact", "_update_counts_label",
        "_sync_problems_chip", "_trouble_nodes", "_on_problems_chip_clicked",
        "_set_problems_only", "problems_only"]),
    "ui/main_window_panels.py": ("PanelsMixin", MWPN.PanelsMixin, [
        "_toggle_sidebar", "_on_sidebar_toggled", "_on_map_toggled", "_reject_collapse_both",
        "_set_panel_collapsed", "_sync_splitter_handle", "_sync_list_mode",
        "_apply_collapsed_strip_sizes", "_apply_splitter_state_from_config",
        "_style_collapse_btn"]),
    "ui/main_window_view.py": ("ViewMixin", MWVW.ViewMixin, [
        "_focus_map", "_focus_domain_step", "_active_terminal_canvas", "_center_view",
        "_fit_to_content", "_on_zoom_changed", "_reset_zoom", "_zoom_in", "_zoom_out",
        "_iter_server_nodes", "_set_all_collapsed", "_collapse_all_servers",
        "_expand_all_servers", "_select_node", "_fly_camera_to_node",
        "_on_hover_focus_changed"]),
    "ui/main_window_theme.py": ("ThemeMixin", MWTH.ThemeMixin, [
        "refresh_theme", "apply_theme", "_refresh_icons", "_install_color_scheme_watch",
        "_theme_mode_from_config", "_on_system_color_scheme_changed"]),
    "ui/main_window_i18n.py": ("I18nMixin", MWI1.I18nMixin, [
        "_apply_ui_translations", "_switch_language", "_register_i18n"]),
    "ui/main_window_layout.py": ("LayoutMixin", MWLY.LayoutMixin, [
        "_setup_ui", "resizeEvent"]),
}
#: every planned file of the split, all three waves — the tables the structural checks walk
WAVES = {**WAVE, **WAVE2, **WAVE3}
PLANNED_MRO = ["MainWindow", "ProjectIOMixin", "NodeOpsMixin", "SshMixin", "StatusMixin", "PluginMixin",
               "SettingsMixin", "SceneCommandMixin", "ExportMixin", "OverlaysMixin", "MinimapMixin",
               "LegendMixin", "ActivityMixin", "BookmarksMixin", "SidebarMixin", "MenubarMixin",
               "ToolbarMixin", "StatusBarMixin", "PanelsMixin", "ViewMixin", "ThemeMixin", "I18nMixin",
               "LayoutMixin", "QMainWindow"]


def _owner_of(obj):
    """The `__qualname__` of a function OR of a property's getter (a mixin may own either)."""
    return getattr(obj.fget if isinstance(obj, property) else obj, "__qualname__", "")

# ════════════════════════════════════════════════════════════════════════════
print("== §1 the family and the MRO ==")
# ════════════════════════════════════════════════════════════════════════════

_family = window_family_files(ROOT)
check("§1 the family is the facade plus its mixins (ONE glob, so a new mixin joins by itself)",
      _family[0] == "ui/main_window.py" and all(f.startswith("ui/main_window") for f in _family)
      and len(_family) == 23 and set(WAVES) <= set(_family), str(_family))
check("§1 the nineteen wave files exist, one class each, named as the plan says",
      all(os.path.isfile(os.path.join(ROOT, rel)) for rel in WAVES)
      and all(cls.__name__ == name for rel, (name, cls, _m) in WAVES.items()),
      str([(rel, name, cls.__name__) for rel, (name, cls, _m) in WAVES.items()]))
check(f"§1 the MRO is the planned one ({' → '.join(PLANNED_MRO[:5])} → … → QMainWindow)",
      [c.__name__ for c in MW.MainWindow.__mro__][:24] == PLANNED_MRO,
      str([c.__name__ for c in MW.MainWindow.__mro__][:25]))
check("§1 MainWindow itself defines no wave method (the facade half of the one-owner rule)",
      not any(m in MW.MainWindow.__dict__ for _rel, (_n, _c, methods) in WAVES.items()
              for m in methods))
check("§1 the nineteen classes are the SHIPPED objects the window resolves (not a private copy)",
      all(isinstance(cls, type) and issubclass(MW.MainWindow, cls)
          for _rel, (_n, cls, _m) in WAVES.items()))
check("§1 the shared snap machinery STAYS in the facade (three panels share it)",
      all(name in MW.MainWindow.__dict__
          for name in ("SNAP_PX", "_snap_panel", "_saved_position"))
      and not any(name in window_family_sources(ROOT)[rel]
                  for rel in WAVE2 for name in ("def _snap_panel", "def _saved_position")))

# ════════════════════════════════════════════════════════════════════════════
print("== §2 the one-owner rule, method by method ==")
# ════════════════════════════════════════════════════════════════════════════

_family_src = window_family_sources(ROOT)
_owner_problems = []
for rel, (name, cls, methods) in WAVES.items():
    for method in methods:
        fn = getattr(MW.MainWindow, method, None)
        if fn is None:
            _owner_problems.append(f"{method}: missing on the window")
        elif method not in cls.__dict__:
            _owner_problems.append(f"{method}: not defined in {name}")
        elif _owner_of(fn).split(".")[0] != name:
            _owner_problems.append(f"{method}: owner {_owner_of(fn)}")
        elif not any(isinstance(node, ast.ClassDef) and node.name == name
                     and any(isinstance(sub, ast.FunctionDef) and sub.name == method
                             for sub in node.body)
                     for node in ast.parse(_family_src[rel]).body):
            _owner_problems.append(f"{method}: {rel} does not define it on {name}")
check(f"§2 every one of the {sum(len(m) for _r, (_n, _c, m) in WAVES.items())} wave methods "
      f"has ONE owner", not _owner_problems, "; ".join(_owner_problems[:6]))
check("§2 the AST reader of the family still finds EVERY wave method (its pins travel with the code)",
      all(window_func_owner(m, ROOT) for _rel, (_n, _c, methods) in WAVES.items() for m in methods))
# The family reader returns the FIRST file that defines a name, so a name two family files share is a
# hazard for a BODY pin. The wave keeps exactly one — the status bar's widget class and the theme walk
# both re-apply a QSS string — and it is DECLARED here so a future wave that adds another fails loudly.
check("§2 the ONE name the family defines twice is the declared `refresh_theme` pair",
      window_func_owner("refresh_theme", ROOT) == "ui/main_window_statusbar.py"
      and "def refresh_theme" in _family_src["ui/main_window_theme.py"]
      and "def refresh_theme" in _family_src["ui/main_window_statusbar.py"],
      window_func_owner("refresh_theme", ROOT))
check("§2 the method counts are the plan's (11 / 15 / 2 / 18 / 13 | 23 / 8 / 7 / 6 / 9 / 9 | "
      "5 / 10 / 10 / 10 / 16 / 6 / 3 / 2)",
      [len(methods) for _rel, (_n, _c, methods) in WAVE.items()] == [11, 15, 2, 18, 13]
      and [len(methods) for _rel, (_n, _c, methods) in WAVE2.items()] == [23, 8, 7, 6, 9, 9]
      and [len(methods) for _rel, (_n, _c, methods) in WAVE3.items()] == [5, 10, 10, 10, 16, 6, 3, 2],
      str({rel: len(m) for rel, (_n, _c, m) in WAVES.items()}))
check("§2 the scene mixin takes the scene-point predicate from its SIBLING, never a second copy",
      "from .main_window_node_ops import _is_scene_point" in _family_src["ui/main_window_scene.py"]
      and "def _is_scene_point" not in _family_src["ui/main_window_scene.py"]
      and hasattr(MWO, "_is_scene_point"))
check("§2 the class-level facts moved with their cluster (no second truth in the facade)",
      MW.MainWindow.FRESHNESS_TICK_MS == 30_000
      and "FRESHNESS_TICK_MS = " not in _family_src["ui/main_window.py"]
      and "FRESHNESS_TICK_MS = 30_000" in _family_src["ui/main_window_status.py"]
      and MW.MainWindow._export_use_current_theme is False
      and "_export_use_current_theme = " not in _family_src["ui/main_window.py"]
      and "_export_use_current_theme = False" in _family_src["ui/main_window_exports.py"]
      and MW.MainWindow.TOOLBAR_OVERFLOW_SLACK == 32
      and MW.MainWindow.TOOLBAR_OVERFLOW_COMFORT == 1.5
      and "TOOLBAR_OVERFLOW_SLACK = " not in _family_src["ui/main_window.py"]
      and "TOOLBAR_OVERFLOW_SLACK = 32" in _family_src["ui/main_window_toolbar.py"],
      "the four class attributes and their owners")
_moved_module_names = {
    "ui/main_window_panels.py": ("def _diamond_icon", "class _CollapseStrip",
                                 "_WIDGET_MAX_WIDTH = "),
    "ui/main_window_toolbar.py": ("_VIEW_TOOLBAR_ITEMS = (", "_VIEW_TOOLBAR_ACTIONS = {"),
    "ui/main_window_statusbar.py": ("STATUS_FILTER_ORDER = (", "class _StatusCounter",
                                    "class _ProblemsChip"),
}
_facade_src = _family_src["ui/main_window.py"]
check("§2 the module-level widgets and tables moved with their cluster, not copied",
      all(marker in _family_src[rel]
          for rel, markers in _moved_module_names.items() for marker in markers)
      and all(marker not in _facade_src
              for markers in _moved_module_names.values() for marker in markers),
      str(sorted(_moved_module_names)))
check("§2 ...and the facade RE-EXPORTS the eight names the suite reads on `MW`",
      all(n in MW.__dict__ for n in ("_CollapseStrip", "_diamond_icon", "_WIDGET_MAX_WIDTH",
                                     "STATUS_FILTER_ORDER", "_StatusCounter", "_ProblemsChip",
                                     "_VIEW_TOOLBAR_ITEMS", "_VIEW_TOOLBAR_ACTIONS"))
      and MW._CollapseStrip.STRIP_WIDTH == 18 and len(MW._VIEW_TOOLBAR_ITEMS) == 6,
      str([n for n in ("_CollapseStrip", "_diamond_icon", "_WIDGET_MAX_WIDTH",
                       "STATUS_FILTER_ORDER", "_StatusCounter", "_ProblemsChip",
                       "_VIEW_TOOLBAR_ITEMS", "_VIEW_TOOLBAR_ACTIONS") if n not in MW.__dict__]))

# ════════════════════════════════════════════════════════════════════════════
print("== §3 the cycle, the headers and the declared seams ==")
# ════════════════════════════════════════════════════════════════════════════

_FACADE_IMPORT = re.compile(
    r"^\s*(?:from\s+(?:\.{1,2}|ui\.)?main_window\s+import\b"
    r"|from\s+(?:\.+|ui)\s+import\s+main_window\b"
    r"|import\s+(?:ui\.)?main_window\b)")
_cycles = [f"{rel}:{i}" for rel, src in window_family_sources(ROOT).items()
           if rel != "ui/main_window.py"
           for i, line in enumerate(src.splitlines(), 1) if _FACADE_IMPORT.match(line)]
check("§3 no mixin imports the facade (the gate is blind to a sibling mixin, and §1 of the "
      "split test proves it is RED on the real shape)", not _cycles, ", ".join(_cycles))
_headers = {}
for rel in WAVES:
    tree = ast.parse(window_family_sources(ROOT)[rel])
    doc = tree.body[0]
    _headers[rel] = (doc.value.end_lineno - doc.value.lineno + 1
                     if isinstance(doc, ast.Expr) else 0)
check("§3 every wave module carries a header inside the 12-line budget (AGENTS.md §12)",
      _headers and all(1 <= n <= 12 for n in _headers.values()), str(_headers))
check("§3 the facade kept NO wave section comment (the cluster's prose moved with the code)",
      all(marker not in _facade_src for marker in
          ("── v0.7.1: node statuses", "── v0.7.2: Sticky Notes", "── v0.8.1: node grouping",
           "── v1.5rc3 (ROADMAP task 3): status freshness", "── v0.9.1: export the map to an image",
           "── v1.5rc2 (ROADMAP task 3): the PRINT-FRIENDLY",
           "── v1.5.5 (ROADMAP tasks 2/3): the inventory report",
           "── v1.4.5 (ROADMAP task 4): the legend panel ─",
           "── v1.5.2 (ROADMAP task 3): the activity panel ─",
           "── the floating-panel priority rule ──", "── the active-filter plaque ──",
           "── the map search bar ──", "── the first-run hint ──",
           "── the map collapse diamond ──", "── the legend panel ──",
           "── the tree rows and the row menu ──", "── the filters of the sidebar ──",
           "── the row markers ──",
           "── v1.2.4.1: collapsing the sidebar/map into a thin strip",
           "── v1.4.5 (ROADMAP task 3): the clickable status counters",
           "── the VIEW toggles of the toolbar ──",
           "── v1.5rc4 (ROADMAP task 2): the toolbar overflow policy",
           "── the status-bar overflow policy", "── v1.5rc4 (ROADMAP task 5/6): the keyboard domains",
           "── v1.2.4.1 (ROADMAP v1.2.4.1): ONE \"collapse into a thin strip\" mechanism",
           "── v1.4.4 (ROADMAP task 2): the camera flights",
           "── v1.5.4 (ROADMAP task 2): the \"problems only\" lens",
           "── v1.6.1 (ROADMAP task 7): the toolbar's right-click menu",
           "── v1.3.3.3 (ROADMAP task 2): the zoom actions of the View menu",
           "── v1.4.3 (ROADMAP task 6): the theme of the settings hub",
           "── v1.5rc1 (ROADMAP task 6): \"Auto (system)\" follows the platform live",
           "── v1.3.3.1 (ROADMAP task 3): the language list without a restart")))
check("§3 ...and the wave-3 clusters really landed in their own file",
      all(marker in _family_src[rel] for rel, marker in
          (("ui/main_window_menubar.py", "── v1.3.3.1 (ROADMAP task 3): the language list"),
           ("ui/main_window_toolbar.py", "── the VIEW toggles of the toolbar ──"),
           ("ui/main_window_toolbar.py", "── v1.5rc4 (ROADMAP task 2): the toolbar overflow policy"),
           ("ui/main_window_toolbar.py", "── v1.6.1 (ROADMAP task 7): the toolbar's right-click menu"),
           ("ui/main_window_statusbar.py", "── v1.4.5 (ROADMAP task 3): the clickable status counters"),
           ("ui/main_window_statusbar.py", "── the status-bar overflow policy"),
           ("ui/main_window_statusbar.py", "── v1.5.4 (ROADMAP task 2): the \"problems only\" lens"),
           ("ui/main_window_panels.py", "── v1.2.4.1: collapsing the sidebar/map into a thin strip"),
           ("ui/main_window_panels.py", "── v1.2.4.1 (ROADMAP v1.2.4.1): ONE \"collapse"),
           ("ui/main_window_view.py", "── v1.5rc4 (ROADMAP task 5/6): the keyboard domains"),
           ("ui/main_window_view.py", "── v1.4.4 (ROADMAP task 2): the camera flights"),
           ("ui/main_window_view.py", "── v1.3.3.3 (ROADMAP task 2): the zoom actions of the View menu"),
           ("ui/main_window_theme.py", "── v1.4.3 (ROADMAP task 6): the theme of the settings hub"),
           ("ui/main_window_theme.py", "── v1.5rc1 (ROADMAP task 6): \"Auto (system)\" follows"))))
check("§3 the facade KEEPS the two owners the wave must not move (the snap machinery and the "
      "ONE dim owner)",
      "── the map dimming: the ONE owner of the highlight state ──" in _facade_src
      and "── the floating panels re-attach by dropping on an edge ──" in _facade_src
      and "def _apply_map_dimming" in _facade_src and "def _snap_panel" in _facade_src)
_seams_raw = tuple(getattr(MW, "MODULE_FACADE_SEAMS", ()))
_seams = tuple(getattr(x, "__name__", x) for x in _seams_raw)
check("§3 the declared seams name the wave-1 facades (`MW.ExportOptionsDialog`, `MW.QFileDialog`)",
      "ExportOptionsDialog" in _seams and "QFileDialog" in _seams, str(_seams))
check("§3 ...and the wave-2 one the sidebar resolves (`MW.QMenu`, its row menu)",
      "QMenu" in _seams
      and 'host_attr(self, "QMenu")' in _family_src["ui/main_window_sidebar.py"], str(_seams))
_wave3_seams = (MW.AddServerDialog, MW.QMessageBox, MW.set_action_icon, MW.refresh_action_icon,
                MW._icons_mod, MW.theme_qss, MW.theme, MW.UndoStatusBar, MW.status_bar_is_compact,
                MW.status_bar_needed_width, MW.SidebarPanel, MW.MapScene, MW.MapView,
                MW.restore_splitter_state, MW.QWidget, MW.QToolBar, MW.QToolButton, MW.QDockWidget,
                MW.QAction, MW.QKeySequence, MW.QPixmap, MW.Signal)
check("§3 ...and the wave-3 ones — by IDENTITY, so an ALIASED import (`is_compact` as "
      "`status_bar_is_compact`) and a MODULE (`theme_qss`) count for what they are",
      all(any(seam is x for seam in _seams_raw) for x in _wave3_seams),
      str([getattr(x, "__name__", repr(x))[:40] for x in _wave3_seams
           if not any(seam is x for seam in _seams_raw)]))
check("§3 every wave-3 seam is REALLY resolved through `host_attr` at the call site",
      'host_attr(self, "set_action_icon")' in _family_src["ui/main_window_menubar.py"]
      and 'host_attr(self, "set_action_icon")' in _family_src["ui/main_window_toolbar.py"]
      and 'host_attr(self, "QMenu", QMenu)' in _family_src["ui/main_window_toolbar.py"]
      and 'host_attr(self, "STATUS_FILTER_ORDER", ())' in _family_src["ui/main_window_layout.py"]
      and 'host_attr(self, "_CollapseStrip")' in _family_src["ui/main_window_layout.py"]
      and 'host_attr(self, "theme_qss")' in _family_src["ui/main_window_theme.py"]
      and 'host_attr(self, "_icons_mod")' in _family_src["ui/main_window_theme.py"]
      and 'host_attr(self, "_diamond_icon")()' in _family_src["ui/main_window_theme.py"])
check("§3 the exports take the palette dialog through `host_attr`, never through a module global",
      "host_attr(self, \"ExportOptionsDialog\")" in window_family_sources(ROOT)[
          "ui/main_window_exports.py"]
      and "ExportOptionsDialog(" not in window_func_body("_ask_export_palette", ROOT).replace(
          "dialog_cls(", ""))

_sentinel = type("_Sentinel", (), {})
_orig_dialog = MW.ExportOptionsDialog
_win = MW.MainWindow()
_win._autosave_timer.stop()
_win._freshness_timer.stop()
_win._status_checker = None
try:
    MW.ExportOptionsDialog = _sentinel
    check("§3 `host_attr` really sees a swapped facade from the mixin (the test seam survives the move)",
          host_attr(_win, "ExportOptionsDialog") is _sentinel)
finally:
    MW.ExportOptionsDialog = _orig_dialog
check("§3 every wave method is reachable on the INSTANCE, not only on the class",
      all(callable(getattr(_win, m, None))
          or isinstance(getattr(type(_win), m, None), property)
          for _rel, (_n, _c, methods) in WAVES.items() for m in methods))
_win.close()
del _win

# ════════════════════════════════════════════════════════════════════════════
print("== §4 the structural pins (a body is read WHEREVER the family defines it) ==")
# ════════════════════════════════════════════════════════════════════════════

check("§4 the reader finds a moved body (the pin that travels with the code)",
      window_func_owner("_copy_map_image", ROOT) == "ui/main_window_exports.py"
      and "PALETTE_THEME" in window_func_body("_copy_map_image", ROOT))
check("§4 ...and it finds a wave-2 body too (the floating panels left the facade)",
      window_func_owner("_position_map_collapse_btn", ROOT) == "ui/main_window_overlays.py"
      and window_func_owner("_on_legend_moved", ROOT) == "ui/main_window_legend.py"
      and window_func_owner("_on_minimap_moved", ROOT) == "ui/main_window_minimap.py"
      and window_func_owner("_on_bookmarks_moved", ROOT) == "ui/main_window_bookmarks.py"
      and window_func_owner("refresh_sidebar", ROOT) == "ui/main_window_sidebar.py"
      and window_func_owner("_record_activity_message", ROOT) == "ui/main_window_activity.py")
try:
    window_func_body("_no_such_method_8rc1", ROOT)
    _missing_raised = False
except KeyError:
    _missing_raised = True
check("§4 ...and it answers KeyError for a method no file of the family defines", _missing_raised)
_pin_files = ("tests/test_map_images.py", "tests/test_first_run.py", "tests/test_release_v15.py",
              "tests/test_activity_panel.py", "tests/test_bookmarks.py", "tests/test_problem_first.py",
              "tests/test_ui_requests.py")
_pin_text = {rel: open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()
             for rel in _pin_files}
check("§4 the converted pins call the FAMILY reader (not a hand-written file path)",
      all("window_func_body(" in src for src in _pin_text.values())
      and not any('_func_body("ui", "main_window.py"' in src for src in _pin_text.values()),
      "; ".join(f"{rel}: {src.count('window_func_body(')}" for rel, src in _pin_text.items()))
check("§4 no test of the suite slices the facade's text for a method body any more",
      not [name for name in sorted(os.listdir(os.path.join(ROOT, "tests")))
           if name.startswith("test_") and name.endswith(".py")
           and re.search(r'main_window\.py"[^\n]*\)[^\n]*\.split\("def _',
                         open(os.path.join(ROOT, "tests", name), encoding="utf-8").read())])

# ════════════════════════════════════════════════════════════════════════════
print("== §5 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check_i18n_parity(LANGS)
check_i18n_format(LANGS)
check_release_state(ROOT)
check("§5 the wave adds NO i18n key and NO schema move (a pure structure release; the release's own "
      "feature adds the elevated pane's TWENTY, v1.8.1 its 41 and v1.8.1.1 ONE) and v1.8.2 adds SIXTEEN: the library file — the History door, the backup ring and the import/export pair — and v1.8.3 adds TWENTY-THREE: the Plugins window (its chrome, its three columns and its export) and v1.8.4 adds TEN: the whole-map layout, the reverse traversal and the inode fact, and v1.9 adds FOUR: the production-tag guard — its title, the broadcast sentence and the paste sentence — and the notice of a checked selection that has left the map",
      EXPECTED_I18N_KEYS == 919 + 6 + 20 + 41 + 1 + 16 + 23 + 10 + 4 and VERSION_FORMAT == "0.9",
      f"{EXPECTED_I18N_KEYS} / {VERSION_FORMAT}")
check("§5 the pin names this release", releases_at_least(EXPECTED_APP_VERSION, "1.8"),
      EXPECTED_APP_VERSION)
check("§5 the shipped version is the one the pin names", APP_VERSION == EXPECTED_APP_VERSION,
      f"{APP_VERSION} / {EXPECTED_APP_VERSION}")
check("§5 the facade is UNDER 2 000 lines (the wave-3 acceptance the plan states)",
      len(_family_src["ui/main_window.py"].splitlines()) < 2000,
      f"{len(_family_src['ui/main_window.py'].splitlines())} lines")
finish()
