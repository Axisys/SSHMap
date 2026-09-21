"""Sidebar panel (server list) — v0.9.9.4.

The sidebar cluster was moved out of ui/main_window.py (phase 1 of the
"main_window.py hygiene" series): action buttons, title, search field,
tag filter, the server tree with status markers, and the per-row context
menu composition.

"Module + callbacks" pattern (like services/diagnostics.py in v0.9.9.3):
the panel knows neither MainWindow nor MapScene — everything comes from
outside:
  * translate_fn(key, **kw) — i18n callback; the panel's own string
    registry is re-applied in retranslate() on language switch (regression
    for the v0.9.2 bug — sidebar strings are not lost/left in the old
    language);
  * actions — a dict of context menu callbacks {action key: callable(node)};
  * button clicks — panel signals; MainWindow wires up its own slots.

MainWindow remains the facade (public API unchanged): self.tree /
self.tag_filter / self.search_edit / self.btn_* — references to the
panel's widgets, refresh_sidebar()/_sync_selection_state()/_on_tree_item_clicked()
etc. — window methods. The context menu object is CREATED by MainWindow
(QMenu — module-level global, the test seam for monkeypatching); the panel
only fills it with items (fill_context_menu).
"""
from PySide6.QtCore import Qt, QSize, Signal
# v1.1.2RC2 (N9): QColor removed from imports — after deleting the dead
# setItemData(..., Qt.DecorationRole) the panel has no remaining uses
from PySide6.QtGui import QIcon, QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QTreeWidget, QTreeWidgetItem, QPushButton, QToolButton,
)

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:  # UI polish: vector icons (ui/icons.py) — emoji replacement, consistent with the toolbar
    from .icons import get_icon, refresh_button_icon
except ImportError:
    try:
        from icons import get_icon, refresh_button_icon
    except ImportError:  # flat layout without ui/icons — text-only buttons, as before
        def get_icon(name):  # noqa: N802 — stub with the same signature
            return None

        def refresh_button_icon(button, name):  # noqa: N802 — stub
            return False


# Context menu action keys (order and separators — ROADMAP v0.9.6, item 1).
# "Card" actions are deliberately NOT duplicated (ROADMAP #2): the drag
# connection and panel collapse/expand live only in the map context, where
# they make sense.
CONTEXT_MENU_ITEMS = (
    ("ssh", "ctx.ssh_connect"),
    ("external", "ctx.ssh_external"),
    None,  # separator
    ("edit", "ctx.edit_server"),
    None,
    ("copy_ip", "ctx.copy_ip"),
    ("copy_hostname", "ctx.copy_hostname"),
    ("ping", "ctx.ping"),
    ("collect_info", "ctx.collect_info"),
    # v1.3.3.3 (ROADMAP task 5): the on-demand status round — the same entry point as
    # on the map; the row's node is the fallback when nothing is selected.
    ("check_status", "ctx.check_status"),
    None,
    ("reveal", "ctx.reveal_on_map"),
    None,
    ("delete", "ctx.delete_server"),
)

# Panel buttons: (attribute, icon, i18n key, fallback) — order as in the
# original _setup_ui.
# v1.1: 6th button "Settings" (hub, ROADMAP v1.1 task 2) — a vector gear
# from ui/icons.py; retranslate() below iterates _BUTTONS — the new tuple
# is picked up.
_BUTTONS = (
    ("btn_add", "add_server", "btn.add_server", "Add Server"),
    ("btn_connect", "connection", "btn.add_connection", "Add Connection"),
    ("btn_connect_ssh", "ssh", "btn.connect_ssh", "Connect via SSH"),
    ("btn_props", "properties", "btn.properties", "Properties"),
    ("btn_delete", "delete", "btn.delete", "Delete"),
    ("btn_settings", "settings", "btn.settings", "Settings"),
)


class SidebarPanel(QWidget):
    """Sidebar: buttons, title, search, tag filter, server tree (v0.9.9.4).

    Signals (MainWindow wires up its own slots):
        add_server_clicked / add_connection_clicked / connect_ssh_clicked /
        show_properties_clicked / delete_selected_clicked — button clicks;
        settings_clicked — "Settings" button click (v1.1, settings hub);
    tree events (itemClicked/itemDoubleClicked/customContextMenuRequested)
    are available directly on self.tree.
    """

    add_server_clicked = Signal()
    add_connection_clicked = Signal()
    connect_ssh_clicked = Signal()
    show_properties_clicked = Signal()
    delete_selected_clicked = Signal()
    settings_clicked = Signal()  # v1.1: ⚙ "Settings" button (6th in _BUTTONS)
    collapse_clicked = Signal()  # v1.2.4.1: corner button (the "◇" rhombus) — collapse the sidebar into a strip

    def __init__(self, translate_fn=None, actions=None, show_title: bool = True,
                 parent=None):
        """
        :param translate_fn: i18n callback (key, **kw) -> str; None — i18n
            unavailable (strings stay the English fallback literals from construction).
        :param actions: {action key: callable(node)} for the context menu;
            all keys from CONTEXT_MENU_ITEMS are required.
        :param show_title: whether to create the "Servers" title (MainWindow
            passes _i18n_available — earlier the label was created only when
            i18n was available).
        """
        super().__init__(parent)
        self._translate = translate_fn
        self._actions = dict(actions or {})
        missing = [entry[0] for entry in CONTEXT_MENU_ITEMS
                   if entry is not None and entry[0] not in self._actions]
        if missing:
            raise ValueError(f"SidebarPanel: no callbacks for actions {missing}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Server title label (only when i18n is available — as before) ────────
        self.title_label = None
        if show_title:
            self.title_label = QLabel(self._tr("server.title"))
            layout.addWidget(self.title_label)

        # ── Search field ────────────────────────────────────────────────────────
        self.search_edit = QLineEdit()
        if translate_fn is not None:
            try:
                self.search_edit.setPlaceholderText(self._translate("search.placeholder"))
            except Exception:  # noqa: BLE001 — placeholder is cosmetic
                pass
        else:
            self.search_edit.setPlaceholderText("Search by alias / host / IP...")
        layout.addWidget(self.search_edit)

        # ── v0.9.4: tag filter ────────────────────────────────────────────
        # Items: [0] = "All tags" (filter off), then the unique tags of all
        # map servers; rebuilt in sync_tag_filter_items (without resetting the selection).
        self.tag_filter = QComboBox()
        layout.addWidget(self.tag_filter)

        # ── Server tree ────────────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # Review fix v0.8.0 (#3): colored status markers in the tree (16×16 —
        # exactly fits the dot pixmap; a single size independent of style/platform).
        self.tree.setIconSize(QSize(16, 16))
        layout.addWidget(self.tree)
        # Icon cache for the status dots ("", "online", "warn", "offline")
        self._status_dot_icons = {}

        # v0.9.6: server tree context menu (right-click on a sidebar row).
        # CustomContextMenu policy + customContextMenuRequested signal — Qt's
        # standard path for QTreeWidget (the widget has no overridable
        # contextMenuEvent without intercepting viewport events; the signal
        # carries the position in tree coordinates, itemAt(pos) gives the row).
        # The slot handler lives in MainWindow.
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # ── Buttons (always created, i18n applied when a callback is present) ──
        for attr, icon_name, i18n_key, ru_fallback in _BUTTONS:
            btn = QPushButton(ru_fallback)
            self._set_btn_icon(btn, icon_name)
            btn.setMinimumHeight(34)  # UI polish: uniform sidebar buttons
            # v1.1.2RC2 (U1, user feedback): left alignment — indent from the
            # left edge, icon, text. QPushButton centers its content by
            # default; QStyle does not allow setting alignment without a
            # stylesheet, so — minimal CSS (frame/background stay native,
            # styling is only content positioning).
            btn.setStyleSheet("QPushButton { text-align: left; padding-left: 12px; }")
            if translate_fn is not None:
                try:
                    # Emojis/prefixes are already contained in the translation
                    # values themselves; re-adding them here would duplicate
                    # (there was " - - 添加连接" etc.)
                    btn.setText(self._translate(i18n_key))
                except Exception:  # noqa: BLE001 — keep the English fallback labels
                    pass
            setattr(self, attr, btn)
            layout.addWidget(btn)

        self.btn_add.clicked.connect(self.add_server_clicked)
        self.btn_connect.clicked.connect(self.add_connection_clicked)
        self.btn_connect_ssh.clicked.connect(self.connect_ssh_clicked)
        self.btn_props.clicked.connect(self.show_properties_clicked)
        self.btn_delete.clicked.connect(self.delete_selected_clicked)
        self.btn_settings.clicked.connect(self.settings_clicked)  # v1.1: settings hub

        # ── v1.2.4.1 (ROADMAP task 2): collapse button — bottom row, right corner ──
        # The icon (vector rhombus "◇", v1.2.4.1-fix) and tooltip are set by MainWindow (i18n + ui/icons);
        # here — only the widget and the collapse_clicked signal ("module + callbacks" pattern).
        self.collapse_btn = QToolButton()
        self.collapse_btn.setAutoRaise(True)
        self.collapse_btn.setToolTip("Sidebar")  # fallback without i18n (like the buttons above)
        _row = QHBoxLayout()
        _row.addStretch(1)
        _row.addWidget(self.collapse_btn)
        layout.addLayout(_row)
        self.collapse_btn.clicked.connect(self.collapse_clicked)

    # ── i18n (callback + retranslate — regression for the v0.9.2 bug) ─────────────────

    def _tr(self, key: str, **kw) -> str:
        """Translate via the passed callback; without one — the key itself."""
        if self._translate is not None:
            try:
                return self._translate(key, **kw)
            except Exception:  # noqa: BLE001 — an i18n failure must not break the panel
                pass
        return key

    def retranslate(self):
        """Re-apply translations to the panel's own strings (language switch).

        Regression for the v0.9.2 bug: before v0.9.9.4 the sidebar strings
        (buttons, title, search placeholder, "All tags" in the tag filter)
        were set only at construction time and stayed in the old language
        after switching. The string registry — here; the panel does not
        import the i18n module (the translate_fn callback).
        Called from MainWindow._apply_ui_translations().
        """
        if self._translate is None:
            return  # i18n unavailable — the English fallback literals from construction
        try:
            if self.title_label is not None:
                self.title_label.setText(self._tr("server.title"))
            self.search_edit.setPlaceholderText(self._tr("search.placeholder"))
            for attr, _icon, key, _ru in _BUTTONS:
                getattr(self, attr).setText(self._tr(key))
            # Tag filter: item 0's label ("All tags") — without resetting the selection.
            # setCurrentIndex to the same index does not emit a signal (Qt); a
            # repeated refresh_sidebar is idempotent anyway.
            idx = self.tag_filter.currentIndex()
            self.tag_filter.setItemText(0, self._tr("filter.all_tags"))
            if idx > 0:
                self.tag_filter.setCurrentIndex(idx)
        except RuntimeError:
            pass  # Qt teardown — the widgets are already destroyed

    # ── Buttons ─────────────────────────────────────────────────────────────────

    def set_buttons_visible(self, visible: bool) -> None:
        """v1.1.1 (ROADMAP item 5): show/hide the sidebar button block.

        The ui_show_sidebar_buttons key (default True — v1.1 behavior). The
        layout reflows itself: hidden buttons take no space, the tree/search
        grow. The whole sidebar is hidden separately (MainWindow: the
        "View → Sidebar" menu item); this method only touches the button
        block.
        """
        for attr, _icon, _key, _ru in _BUTTONS:
            btn = getattr(self, attr, None)
            if btn is not None:
                try:
                    btn.setVisible(bool(visible))
                except RuntimeError:
                    pass  # Qt teardown — the widget is already destroyed

    def _set_btn_icon(self, btn, name):
        """UI polish: a vector icon on the button (no-op without ui/icons).

        v1.4.3-fix: the icon NAME is remembered on the button — a QPushButton keeps
        its own copy of the pixmap, so `refresh_theme()` has to re-apply the icon by
        name after a theme switch (the registry's in-place repaint does not reach it).
        """
        try:
            icon = get_icon(name)
            if icon is not None and not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QSize(18, 18))
                btn._sshmap_icon_name = name
        except Exception:  # noqa: BLE001 — the icon is cosmetic, don't break the sidebar
            pass

    def refresh_theme(self):
        """v1.4.3-fix: re-apply the theme to the panel's own icons.

        The tree's status markers are painted fresh on every `refresh_rows()`, so
        only the six action buttons carry a cached pixmap. Never raises.
        """
        for attr, icon_name, _key, _fallback in _BUTTONS:
            btn = getattr(self, attr, None)
            if btn is None:
                continue
            name = getattr(btn, "_sshmap_icon_name", icon_name)
            try:
                refresh_button_icon(btn, name)
            except RuntimeError:
                continue  # Qt teardown — the button is already destroyed

    # ── Tree: row construction (refresh from MainWindow) ──────────────────────

    def active_tag_filter(self) -> str:
        """The tag selected in the combobox, or "" ("All tags")."""
        data = self.tag_filter.currentData()
        return str(data) if data else ""

    def refresh_rows(self, nodes, query: str = ""):
        """Rebuild the tree rows: search (query) + the active tag filter.

        `nodes` — an iterable of ServerNode (MainWindow passes scene.nodes());
        the panel does not depend on the scene — only on the node data.
        """
        self.tree.clear()
        active_tag = self.active_tag_filter()
        for node in nodes:
            haystack = " ".join([
                node.data.alias,
                node.data.host,
                node.data.ip,
                node.data.comment,
                # v0.9.4: search matches tags too
                " ".join(getattr(node.data, "tags", None) or []),
            ]).lower()
            if query and query not in haystack:
                continue
            if active_tag and active_tag not in (getattr(node.data, "tags", None) or []):
                continue

            item = QTreeWidgetItem()
            item.setText(0, f"{node.data.alias}  ({node.data.host})")
            item.setData(0, Qt.UserRole, node.data.id)
            # Review fix v0.8.0 (#3): colored status marker for the node (online/warn/offline/not checked)
            self.apply_status_marker(item, node.status, node.data.host or "")
            # v0.9.4: the tag caption at the end of the row ("[tag1, tag2]", up to 3 tags).
            # v1.1.2RC2 (N8): setForeground(0, palette().windowText()) REMOVED — under
            # the "gray" comment it painted the WHOLE row with the standard text
            # color (visual no-op: the color was indistinguishable from the default).
            tags = getattr(node.data, "tags", None) or []
            if tags:
                item.setText(0, item.text(0) + f"  [{', '.join(tags[:3])}]")
            self.tree.addTopLevelItem(item)

    def sync_tag_filter_items(self, nodes):
        """Rebuild the unique tag list in the combobox, preserving the selection.

        Called from refresh_sidebar (MainWindow) — the currentIndexChanged
        signal must not loop the rebuild (signals are blocked while filling).
        """
        all_tags = sorted({
            t.strip()
            for n in nodes
            for t in (getattr(n.data, "tags", None) or [])
            if t and t.strip()
        }, key=str.lower)
        current = self.active_tag_filter()
        try:
            all_label = self._translate("filter.all_tags") if self._translate else "All tags"
        except Exception:  # noqa: BLE001 — as before: fallback to the English literal
            all_label = "All tags"
        if not all_label:
            all_label = "All tags"
        combo = self.tag_filter
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(all_label, "")
            # v1.1.2RC2 (N9): setItemData(QColor, Qt.DecorationRole) REMOVED — the
            # standard style reads DecorationRole as QIcon, QColor never rendered
            # (dead code); the "● tag" in the text is a plain text-color glyph, the
            # tag color is carried by the card.
            for tag in all_tags:
                combo.addItem(f"● {tag}", tag)
            idx = combo.findData(current) if current else 0
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        except RuntimeError:
            pass  # Qt teardown
        finally:
            combo.blockSignals(False)

    # ── Status markers (review fix v0.8.0, #3) ──────────────────────────────

    def _status_dot_icon(self, status: str) -> QIcon:
        """Colored dot for a tree row — the same palette as the dots on the cards."""
        icon = self._status_dot_icons.get(status)
        if icon is not None:
            return icon
        color = ServerNode.STATUS_COLORS.get(status, ServerNode.COLOR_DOT_IDLE)
        pm = QPixmap(16, 16)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(3, 3, 10, 10)
        painter.end()
        icon = QIcon(pm)
        self._status_dot_icons[status] = icon
        return icon

    def apply_status_marker(self, item: QTreeWidgetItem, status: str, host: str = "") -> None:
        """Put the status dot + tooltip (i18n node.status.*) on a tree row."""
        item.setIcon(0, self._status_dot_icon(status))
        if status and status in ServerNode.STATUS_COLORS:
            tip = self._tr(f"node.status.{status}", host=host or "")
            # i18n returned the "key" (no translation) — show the status without the key
            item.setToolTip(0, tip if not tip.startswith("[") else f"{status}: {host}")
        else:
            item.setToolTip(0, "")  # not checked — no tooltip

    def update_status_marker(self, server_id: str, status: str, host: str = "") -> None:
        """Update the row's marker in place (without a full tree rebuild)."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == server_id:
                self.apply_status_marker(item, status, host)
                return
        # No row (e.g. filtered out by the search) — the next refresh_sidebar
        # will build it with the current marker.

    # ── Context menu (composition v0.9.6; the QMenu object is created by MainWindow) ─────

    def fill_context_menu(self, menu, node) -> None:
        """Fill the QMenu with the node's action items (order — ROADMAP v0.9.6).

        `menu` is created by MainWindow (QMenu — module-level global in
        main_window; this keeps the test seam for monkeypatching the menu
        class), parent/ownership too. Each item is connected to a callback
        from self._actions: callable(node).

        v1.0RC4: first item — the "Quick Launch" submenu (if the consumer
        passed the ql_entry/ql_configure callbacks; without them the menu is
        as in v0.9.6 — backward-compat for old calling code).
        """
        self._fill_quick_launch(menu, node)
        for entry in CONTEXT_MENU_ITEMS:
            if entry is None:
                menu.addSeparator()
                continue
            action_key, i18n_key = entry
            act = menu.addAction(self._tr(i18n_key))
            callback = self._actions[action_key]
            # checked — the bool from QAction.triggered; we pass only the node to the callback.
            act.triggered.connect(lambda checked=False, n=node, cb=callback: cb(n))

    def _fill_quick_launch(self, menu, node) -> None:
        """v1.0RC4: the "Quick Launch" submenu — the FIRST menu item (above SSH).

        Composition: the server.data.quick_launch entries (links/commands),
        then a separator and "Configure…". Without entries — only
        "Configure…" (the feature stays discoverable). Callbacks from
        self._actions (optional, outside CONTEXT_MENU_ITEMS):
          * "ql_entry"     — callable(node, entry): open the link/send the command;
          * "ql_configure" — callable(node): the configuration dialog.
        If neither is present — the submenu is not built (old consumers unchanged).
        """
        cb_entry = self._actions.get("ql_entry")
        cb_config = self._actions.get("ql_configure")
        if cb_entry is None and cb_config is None:
            return  # the consumer does not know about Quick Launch — the menu is as in v0.9.6
        entries = list(getattr(node.data, "quick_launch", None) or [])
        sub = menu.addMenu(self._tr("ctx.quick_launch"))
        # v1.0RC4-fix (PySide6 6.11/shiboken — the same bug as _qaction_guard in
        # main_window.py v0.9.8): the local `sub` wrapper dies when the method
        # returns, but MainWindow shows the menu only AFTER the return
        # (menu.exec). When a Python QAction wrapper with an attached QMenu
        # dies (GC), PySide6 destroys the C++ submenu behind it — the "Quick
        # Launch" item disappeared from the menu or fell over with
        # RuntimeError. We keep the references (QAction + QMenu) on the parent
        # menu's wrapper: they live exactly as long as the ephemeral menu.
        _guard = getattr(menu, "_sshmap_ql_guard", None)
        if _guard is None:
            _guard = menu._sshmap_ql_guard = []
        _ql_action = next((a for a in menu.actions() if a.menu() is sub), None)
        if _ql_action is not None:
            _guard.append(_ql_action)
        _guard.append(sub)
        for e in entries:
            if cb_entry is None:
                break  # only configuration is available — entries are not shown
            name = str(e.get("name") or e.get("value") or "?")
            act = sub.addAction(name)
            # checked — the bool from QAction.triggered; we close over both the node and the entry.
            act.triggered.connect(
                lambda checked=False, n=node, en=e, cb=cb_entry: cb(n, en))
        if entries:
            sub.addSeparator()
        if cb_config is not None:
            act_cfg = sub.addAction(self._tr("ql.configure"))
            act_cfg.triggered.connect(
                lambda checked=False, n=node, cb=cb_config: cb(n))
        menu.addSeparator()  # Quick Launch is separated from the "production" menu (like on the map)
