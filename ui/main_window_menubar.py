"""`MenubarMixin` — the window's menu bar: its construction, its translated items and the language submenu (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and `set_action_icon` / `_diamond_icon` are resolved on
the facade at call time (`host_attr`), the seam a stripped build and the suite swap.

Owned here: `_add_menu_action()` (the ONE translated-item factory), `_setup_menubar()` with every menu of the
window, `_rebuild_qaction_guard()` (gotcha #9) and the two halves of the language submenu
(`_populate_language_menu()` / `_reload_languages()`). The Plugins menu's rows and the recent-projects list
belong to their own clusters. Mechanism — `DOCUMENTATION.md` §15, §31."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu

try:  # v1.8rc3: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


class MenubarMixin:
    """The window's menu bar: its construction, its translated items and the language submenu (AGENTS.md §4.1)."""

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
                host_attr(self, "set_action_icon")(action, icon_name)  # the theme walk finds it by this name
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
        self.act_add_connection = self._add_menu_action(
            edit_menu, "edit.add_connection", self._add_connection, "edit.add_connection")
        # v1.6.8 (ROADMAP task 2): the action NAMES the gesture. The tooltip carries the
        # SAME sentence the first screen's hint shows — ONE key, ONE composer
        # (`empty_state.connect_hint_text()`), so the two surfaces cannot drift apart.
        self.act_add_connection.setToolTip(self._connect_hint_text())
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
        # The two on-demand answers: "Gather information" — one bounded batch for the SELECTION
        # (or the whole map), off the GUI thread, reusing the `ctx.collect_info` label so the
        # context menus and this permanent Edit item read the same; "Why is it offline?" — the
        # reachability report (DNS → TCP → banner → ping), whose sentence lands in the card
        # tooltip, the status bar and the activity history. Both are PERMANENT items.
        self._add_menu_action(edit_menu, "ctx.collect_info", self._collect_info_many,
                              "node.collect_info")
        self._add_menu_action(edit_menu, "ctx.diagnose", self._diagnose_node,
                              "node.diagnose")

        # Export menu — the ONE home of everything that LEAVES the application. It is a
        # CONTAINER, not a new family: the actions keep their ids and their `file.*` keys, because
        # a `config.json` `hotkeys` value is keyed by the ACTION ID (a rename would drop every
        # user's binding silently). Three groups by SUBJECT: the map images, the clipboard/poster
        # paths and the DATA reports, which are enabled only while the table exists (§41).
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
        # The THIRD report of the DATA family — the servers that need attention
        # (`storage/export_problems.py`, the DECLARED predicate). It is the connection report's SIBLING,
        # not a filter of the inventory: the lens dims the CANVAS and the inventory export is EXACTLY what
        # is on screen, so a report over a third subject keeps both promises. One registry action with an
        # EMPTY default, riding the same writer and the same format question.
        self.act_export_problems = self._add_menu_action(
            export_menu, "file.export_problems", self._export_problems_table,
            "file.export_problems")

        # Profile menu
        profile_menu = menubar.addMenu(self.t("menu.profile") if self._i18n_available else "Profile")
        self._register_i18n(profile_menu, "menu.profile")
        self._add_menu_action(profile_menu, "profile.manage", self._open_profile_manager,
                              "profile.manage")
        # v1.8.1 (ROADMAP v1.8.1): the known-hosts surface — the readable view of what the TOFU
        # policy recorded, with "delete this fingerprint" and "replace it with the server's".
        self._add_menu_action(profile_menu, "hostkey.manage", self._open_known_hosts_manager,
                              "hostkey.manage")

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
        # Show/hide the WHOLE sidebar as an expanded↔collapsed toggle (checked = expanded) — ONE
        # "collapse into a thin strip" mechanism for both panels: the item, the corner button and
        # the collapsed panel's strip all go through ONE QAction (`toggle()` → `toggled`).
        # Connecting to `toggled(bool)`, not `triggered`, is the `act_multi_input` pattern:
        # PySide6 6.11 emits `triggered` WITHOUT state from `addAction(text, slot)`.
        self.act_show_sidebar = view_menu.addAction(
            self.t("view.toggle_sidebar") if self._i18n_available else "Sidebar / Map")
        self.act_show_sidebar.setCheckable(True)
        self.act_show_sidebar.setChecked(True)
        host_attr(self, "set_action_icon")(self.act_show_sidebar, "sidebar_panel")  # v1.2.4.1: the pair's icon
        self.act_show_sidebar.toggled.connect(self._on_sidebar_toggled)
        self._register_i18n(self.act_show_sidebar, "view.toggle_sidebar")
        # v1.4.6: the toolbar MIRROR of the same toggle (created in _setup_toolbar, which
        # runs BEFORE this method — the pair is wired here, like the v1.4.5 legend one).
        self._wire_view_toolbar_button("view.toggle_sidebar", self.act_show_sidebar)
        # v1.2.4.1 (task 3): the map — the same pattern (created manually, the pair's icon).
        self.act_show_map = view_menu.addAction(
            self.t("view.toggle_map") if self._i18n_available else "Map / List")
        self.act_show_map.setCheckable(True)
        self.act_show_map.setChecked(True)
        host_attr(self, "set_action_icon")(self.act_show_map, "map_panel")
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
        host_attr(self, "set_action_icon")(self.act_show_minimap, "minimap")
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
        host_attr(self, "set_action_icon")(self.act_show_legend, "legend")
        self.act_show_legend.toggled.connect(self._toggle_legend)
        self._register_i18n(self.act_show_legend, "view.toggle_legend")
        self._register_hotkey_target("view.toggle_legend", self.act_show_legend)
        self._wire_view_toolbar_button("view.toggle_legend", self.act_show_legend)
        # v1.6.7 (ROADMAP task 4): the BOOKMARKS panel — the same "created manually +
        # toggled(bool)" pattern and the same registry rule (an EMPTY default: assignable,
        # no key taken from anyone). The panel is already built by `_setup_ui` (which runs
        # BEFORE this method) and its saved visibility was read in the constructor, so the
        # item simply joins that state; the toolbar mirror is created in `_setup_toolbar`.
        self.act_show_bookmarks = view_menu.addAction(
            self.t("view.toggle_bookmarks") if self._i18n_available else "Bookmarks")
        self.act_show_bookmarks.setCheckable(True)
        self.act_show_bookmarks.setChecked(bool(getattr(self, "_bookmarks_enabled", False)))
        host_attr(self, "set_action_icon")(self.act_show_bookmarks, "bookmarks")
        self.act_show_bookmarks.toggled.connect(self._toggle_bookmarks)
        self._register_i18n(self.act_show_bookmarks, "view.toggle_bookmarks")
        self._register_hotkey_target("view.toggle_bookmarks", self.act_show_bookmarks)
        self._wire_view_toolbar_button("view.toggle_bookmarks", self.act_show_bookmarks)
        # The ACTIVITY panel — the same "created manually + toggled(bool)" pattern and the same
        # registry rule (an EMPTY default: assignable, no key taken from anyone). It JOINS the
        # toolbar's view cluster (`_setup_toolbar` runs before this method, so the pair is joined
        # here like the four toggles above): the activity history is a surface a user glances at as
        # often as the legend.
        self.act_show_activity = view_menu.addAction(
            self.t("view.toggle_activity") if self._i18n_available else "Activity panel")
        self.act_show_activity.setCheckable(True)
        self.act_show_activity.setChecked(bool(getattr(self, "_activity_enabled", False)))
        host_attr(self, "set_action_icon")(self.act_show_activity, "activity")
        self.act_show_activity.toggled.connect(self._toggle_activity)
        self._register_i18n(self.act_show_activity, "view.toggle_activity")
        self._register_hotkey_target("view.toggle_activity", self.act_show_activity)
        self._wire_view_toolbar_button("view.toggle_activity", self.act_show_activity)
        # v1.2.4.1 (task 2): corner collapse buttons — the same QAction (toggle()).
        # the icon — a "◇" diamond on both panels, both
        # at the bottom right (the sidebar's bottom row / the map's right BOTTOM corner — the top is
        # reserved for the minimap per the new discussions).
        self.sidebar.collapse_btn.setIcon(host_attr(self, "_diamond_icon")())
        self._style_collapse_btn(self.sidebar.collapse_btn)   # v1.5.6: the FRAME (task 4)
        if self._i18n_available:
            self.sidebar.collapse_btn.setToolTip(self.t("view.toggle_sidebar"))
        self.sidebar.collapse_clicked.connect(lambda: self.act_show_sidebar.toggle())
        self._map_collapse_btn.setIcon(host_attr(self, "_diamond_icon")())
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
        # Multi-input — a checkable item; F12 = EXIT from the mode (not Esc — that goes to the shell as
        # `\x1b!`). `ApplicationShortcut`: the key is caught regardless of where the focus is (map /
        # terminal window / dock). While the mode is off the QAction has NO shortcut (`QKeySequence()` is
        # empty; a QAction has no `setShortcutEnabled`), so F12 goes to the shell as `\x1b[24~`; in the mode
        # `_on_multi_changed` attaches F12 and the canvas mapping is paused.
        view_menu.addSeparator()
        # The item is NOT created via `_add_menu_action`: its auto-connection
        # (`QMenu.addAction(text, slot)`) fires `triggered` into the Python slot WITHOUT arguments
        # in PySide6 6.11, and `disconnect()` cannot remove such a connection — so the QAction is
        # built manually and connected to `toggled(bool)`, which carries the state and stays in sync.
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

        # ── the "Plugins" menu ──────────────────────────────────────────────
        # BETWEEN "Settings" and "Help". The manager holds the records, this menu renders
        # them: one checkable row per discovered plugin (the enable/disable switch — persisted
        # in `plugins` of config.json) plus "Reload"; the rows are rebuilt on aboutToShow and
        # created MANUALLY with an explicit toggled(bool) — `PLUGINS.md`, `DOCUMENTATION.md` §33.
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
        # v1.8.3 (ROADMAP task 1): the Plugins WINDOW — the door to the window, in the permanent
        # group (below the separator) and the checkable OWNER of its `ui_plugins_panel` visibility
        # (the `view.toggle_activity` rule: the item owns the state, the panel follows it). Built
        # manually with an explicit toggled(bool): an auto-connected QMenu slot fires WITHOUT
        # arguments in PySide6 6.11 and cannot be disconnected again (gotcha #10).
        self.act_plugins_window = QAction(
            self.t("plugins.window.open") if self._i18n_available else "Plugins window…",
            self._plugin_menu)
        self.act_plugins_window.setCheckable(True)
        self.act_plugins_window.setChecked(bool(getattr(self, "_plugins_window_enabled", False)))
        self.act_plugins_window.toggled.connect(self._toggle_plugins_window)
        self._register_i18n(self.act_plugins_window, "plugins.window.open")
        host_attr(self, "set_action_icon")(self.act_plugins_window, "plugin")
        self._plugin_menu.insertAction(self.act_plugins_reload, self.act_plugins_window)
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
        # The submenu is not frozen at construction: it is (re)built from `get_available_languages()`
        # every time it is ABOUT TO BE SHOWN (aboutToShow), so an `i18n/<code>.json` dropped in
        # afterwards appears without a restart. An explicit "Rescan the language files" item makes the
        # behaviour discoverable and re-reads the ACTIVE file — `_build_language_menu()`.
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

        # ── a guard for QActions with menus (PySide6 6.11 / shiboken) ──
        # When the Python wrapper of a QAction with an ATTACHED QMenu dies (GC of a temporary from
        # menubar.actions()/act.menu()), PySide6 destroys the C++ QMenu behind it with everything
        # in it — opening the palette or switching the language would kill all but the last menu.
        # Keeping those QActions in `self._qaction_guard` makes them immortal, so the menus live on.
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
