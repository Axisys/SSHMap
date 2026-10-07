"""`LayoutMixin` — the window's assembly: the splitter, the panels, the canvas and the three chrome policies (AGENTS.md §4.1, §4.18).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance and resolves the classes it instantiates on the facade
at call time (`host_attr`: `SidebarPanel`, `MapScene`, `MapView`, `UndoStatusBar`, `_CollapseStrip`,
`_StatusCounter`, `_ProblemsChip`, `STATUS_FILTER_ORDER`), which is also the `MW.<name>` test seam.

Owned here: `_setup_ui()` — the [panel | strip] containers, the sidebar, the map canvas, the status-bar
widgets and the FIRST pass of the toolbar/status-bar/overlay policies — and `resizeEvent()`, the ONE geometry
entry point that drives them. Mechanism — `DOCUMENTATION.md` §15, §36, §41."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSplitter, QToolButton, QWidget

try:  # v1.8rc3: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr

try:  # v1.2.5 / v1.4.3: the theme and its QSS half (both MODULES, never swapped as a name)
    from . import theme, theme_qss
except ImportError:
    try:
        from ui import theme, theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        import theme
        theme_qss = None


class LayoutMixin:
    """The window's assembly: the splitter, the panels, the canvas and the three chrome policies (AGENTS.md §4.1, §4.18)."""

    def _setup_ui(self):
        bar_cls = host_attr(self, "UndoStatusBar")
        sidebar_cls = host_attr(self, "SidebarPanel")
        scene_cls = host_attr(self, "MapScene")
        view_cls = host_attr(self, "MapView")
        strip_cls = host_attr(self, "_CollapseStrip")
        counter_cls = host_attr(self, "_StatusCounter")
        chip_cls = host_attr(self, "_ProblemsChip")
        filter_order = host_attr(self, "STATUS_FILTER_ORDER", ())
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # v1.5rc3 (ROADMAP task 2): the window's status bar is installed BEFORE anything
        # can post a message to it — the Undo affordance is a property of that bar (it
        # consumes the first message after `_push_command()` armed it), so every later
        # `self.statusBar()` call reaches the subclass. The callback is the window's own
        # undo; the bar itself knows nothing about the stack.
        if bar_cls is not None:
            try:
                _bar = bar_cls(self)
                _bar.set_undo_callback(self._undo)
                self.setStatusBar(_bar)
            except Exception as e:  # noqa: BLE001 — a status bar must not break startup
                if self.log:
                    self.log.warning(f"Undo status bar unavailable: {e}")

        # v1.3.3.6 (ROADMAP task 2): the window accepts a dropped project file
        # (dragEnterEvent/dragMoveEvent/dropEvent below). Until now only the SFTP tab
        # had this — dragging a .json onto the window did nothing at all.
        self.setAcceptDrops(True)

        # `self._splitter` — a facade reference (the panel collapse mechanics). Splitter children are
        # CONTAINERS `[panel | strip]`, not the widgets themselves: in the collapsed state the real widget
        # is hidden (0 px, native Qt) and a clickable ~18 px strip (`_CollapseStrip`) takes its place. The
        # handle cannot be dragged to zero (`setCollapsible(False)` + the container's `minimumWidth`), so a
        # panel cannot be "lost"; the state is driven by buttons/menus.
        splitter = QSplitter(Qt.Horizontal)
        self._splitter = splitter
        layout.addWidget(splitter)

        # Side panel — v0.9.9.4: the sidebar cluster (buttons, title, search,
        # tag filter, tree with status markers, context menu) is moved to
        # ui/sidebar.py (SidebarPanel). MainWindow remains a facade: self.tree /
        # self.tag_filter / self.search_edit / self.btn_* — references to the
        # panel's widgets; the public API and all window slots are unchanged.
        self.sidebar = sidebar_cls(
            translate_fn=self.t if self._i18n_available else None,
            actions={
                # Row context menu (ROADMAP v0.9.6): "select first,
                # then act" — as in the original _on_sidebar_context_menu closures.
                "ssh": lambda n: (self._select_node(n), self._connect_ssh_to_selected()),
                "external": lambda n: (self._select_node(n), self._connect_ssh_external(n)),
                # v1.6.8 (ROADMAP task 1): "Connect to…" — the row's own node is the
                # SOURCE of the connection the dialog will create, and the dialog is the
                # SAME one the Shift+drag gesture opens (`_add_connection`, pre-filled).
                "connect_to": lambda n: (self._select_node(n),
                                         self._add_connection(default_source_id=n.data.id)),
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
        self._sidebar_strip = strip_cls()
        _sb_lay.addWidget(self.sidebar)
        _sb_lay.addWidget(self._sidebar_strip)
        self._sidebar_strip.hide()
        splitter.addWidget(self._sidebar_container)

        # Map canvas
        self.scene = scene_cls()
        # v0.9.9.1: reentry guard for selection sync (instead of blockSignals — see _select_node)
        self._selection_syncing = False
        self.scene.selectionChanged.connect(self._sync_selection_state)
        # v1.4.4 (ROADMAP task 4): the scene reports the hover focus of an ARROW; the
        # window stays the ONE owner of the resulting dim (`_apply_map_dimming`).
        self.scene.hover_focus_changed.connect(self._on_hover_focus_changed)
        self.view = view_cls(self.scene, self)

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
        self._map_strip = strip_cls()
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
        # The WINDOW's own floor. The status bar's totals sentence made the layout ask for ~818 px, i.e.
        # the CHROME dictated how narrow the window could be — and an overflow policy for a bar that can
        # never get narrow is decoration. The explicit floor is what the policies work against: below
        # `MIN_WINDOW_WIDTH` nothing is squeezed any further (the chrome has given up its passive half by
        # then), and the sidebar/map minimums still hold.
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

        # v1.6.7 (ROADMAP task 4): the BOOKMARKS panel — the fourth floating panel of the
        # same family (a child of the view, out of the exports). Created AFTER the plaque,
        # because its default corner (LEFT|TOP) yields to the plaque by stepping below it.
        self._setup_bookmarks_panel()

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
        for _status in filter_order:
            _counter = counter_cls(_status, self)
            _counter.clicked.connect(self._on_status_filter_clicked)
            _counter.refresh_theme()
            self.statusBar().addPermanentWidget(_counter)
            self.status_filter_labels[_status] = _counter

        # v1.5.4 (ROADMAP task 2): the "problems only" lens — ONE transient toggle beside
        # the status counters whose click DIMS everything that is not warn/offline/stale.
        # It is UI state (memory only, never a config key) and it never changes the
        # counters: a lens is a view, not a fact.
        self._problems_only = False
        # v1.8.4 (ROADMAP task 2): the DEPENDENCY focus of the map — the node id a Ctrl+click
        # asked about ("" = no highlight), memory only, read back by `_apply_map_dimming()`
        # through `_dependency_ids()`. UI state like the lens above, never a config key.
        self._dependency_focus = ""
        self.problems_chip = chip_cls(self)
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
