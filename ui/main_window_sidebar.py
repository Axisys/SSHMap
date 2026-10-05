"""`SidebarMixin` — the window's half of the sidebar: the tree slots, the filters and the row menu (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance, and the row `QMenu` plus the counter order are
resolved on the facade at call time (`host_attr`), which is the test seam (`MW.QMenu = CaptureMenu`).

Owned here: the two row slots, the row context menu, "show on map", `refresh_sidebar()`, the tag filter's
window half, the sidebar status filter and the in-place status markers. The map DIMMING stays with the
window (its ONE owner). Mechanism — `DOCUMENTATION.md` §36, §37."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

try:  # a string annotation must resolve to a name the module BINDS (tests/test_audit_v161.py §3)
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:  # v1.1.4: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


class SidebarMixin:
    """The sidebar's window half: the tree slots, the filters and the row menu."""

    # ── the tree rows and the row menu ──

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

        menu = host_attr(self, "QMenu")(self)  # the panel fills it; the window shows it
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
            return  # the node is gone (deleted while the menu was open)
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

    # ── the filters of the sidebar ──

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

    def _on_status_filter_clicked(self, status: str):
        """A status counter was clicked: filter the sidebar by it, or reset on a repeat.

        The state is TRANSIENT (in memory only, never written to config.json): a
        restart must not leave a sidebar hiding servers for no visible reason. The
        signal is the same counter clicked a second time — a plain toggle, so "show me
        the offline ones" and "show me everything" are the same gesture.
        """
        status = str(status or "")
        if status not in host_attr(self, "STATUS_FILTER_ORDER", ()):
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

    # ── the row markers ──

    def _update_sidebar_status_marker(self, server_id: str) -> None:
        """Update the row marker in place (without a full tree rebuild)."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # the node is gone — nobody needs its status
        self.sidebar.update_status_marker(server_id, node.status, node.data.host or "")
