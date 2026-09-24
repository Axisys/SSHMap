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
from PySide6.QtCore import Qt, QEvent, QSize, Signal
# v1.1.2RC2 (N9): QColor removed from imports — after deleting the dead
# setItemData(..., Qt.DecorationRole) the panel has no remaining uses
from PySide6.QtGui import QIcon, QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QComboBox,
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

try:  # v1.5rc2 (ROADMAP task 2): the DECLARED status shapes — the row marker's mark
    from . import status_shape
except ImportError:
    try:
        from ui import status_shape
    except ImportError:  # flat layout without ui/status_shape — the v1.4.x round dot
        status_shape = None

try:  # v1.5rc4 (ROADMAP task 5): the ONE visible-focus indicator of the keyboard domains
    from . import focus_ring
except ImportError:
    try:
        from ui import focus_ring
    except ImportError:  # flat layout without ui/focus_ring — the panel simply has no frame
        focus_ring = None


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
    # v1.5.3 (ROADMAP task 3): "why is it offline?" — the on-demand reachability report
    # (DNS → TCP → banner → ICMP ping). It sits next to the status round because it is the
    # question that round raises: a red row, and no answer beyond "offline".
    ("diagnose", "ctx.diagnose"),
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

# ── v1.4.5 (ROADMAP task 1): the compact action grid ─────────────────────────
# Six full-width rows took roughly a quarter of the sidebar's height and read as
# "heavy" next to the map. The SAME six buttons (same attributes, same signals,
# same i18n keys — _BUTTONS is untouched, so `set_buttons_visible`, `retranslate`
# and MainWindow's public `btn_*` references keep working) now sit in a
# two-column × three-row grid: three dense rows instead of six. Every cell keeps
# its icon and its text (the cell elides a long label — the tooltip carries the
# full one).
_BUTTON_COLUMNS = 2             # 2 columns × 3 rows = the 6 buttons
_COMPACT_BUTTON_HEIGHT = 28     # the dense row height (the v1.1.2RC2 34px was a full-width row)
_COMPACT_BUTTON_ICON = 16       # the icon size of a compact cell
# **A QPushButton's minimumSizeHint IS its sizeHint** (the full label + icon + padding), so
# two columns of buttons would have made the SIDEBAR's own minimum ~428 px — wider than its
# documented 160 px minimum and wider than the 250 px default the splitter starts with.
# An explicit small minimum overrides that hint: a cell shrinks and Qt elides its text
# (the tooltip carries the full label).
_COMPACT_BUTTON_MIN_WIDTH = 40
_COMPACT_BUTTON_QSS = "QPushButton { text-align: left; padding-left: 6px; padding-right: 2px; }"

# The statuses the status bar can filter the tree by (v1.4.5, ROADMAP task 3) —
# the same three the cards and the status dots know.
_STATUS_FILTERS = ("online", "warn", "offline")

# ── v1.4.6 (ROADMAP v1.4.6, task 1): the LIST layout of the sidebar tree ─────
# Collapsing the map used to leave a dead ~18 px strip, while the sidebar CONTAINER
# stretched to the whole window width with a single-column tree inside it — the "wide
# window" for the server parameters already existed, only the tree ignored it. In that
# mode the tree becomes the table the width deserves: one column per ServerData field,
# headers shown, every column draggable (QTreeWidget's own section behaviour).
# (field key, i18n header key) — the cells are built by `list_cell_values()`.
LIST_COLUMNS = (
    ("alias", "sidebar.list.alias"),
    ("host", "sidebar.list.host"),
    ("status", "sidebar.list.status"),
    ("os", "sidebar.list.os"),
    ("cpu", "sidebar.list.cpu"),
    ("ram", "sidebar.list.ram"),
    ("disk", "sidebar.list.disk"),
    ("tags", "sidebar.list.tags"),
)
# The `status` column of the table: a probe result must refresh its TEXT in place
# (`update_status_marker` — a full rebuild of the rows would lose the scroll position).
_LIST_STATUS_COLUMN = 2
# The opening widths of the columns — a starting point, not a constraint: the sections
# stay interactive (the QTreeWidget default), so the user drags them.
_LIST_COLUMN_WIDTHS = (190, 190, 80, 170, 170, 80, 80, 150)


def list_cell_values(data, status_text: str = "") -> list:
    """v1.4.6 (ROADMAP task 1): the LIST-mode cells of ONE row, one per `LIST_COLUMNS`.

    Pure (a `ServerData` in, strings out — no Qt, no scene, no scene item), so the
    topical test can pin the mapping headlessly. The rules:

      * an empty field is an EMPTY cell — never the string "None" (the v0.9.4 tag
        caption and the card formatting are the only places allowed to invent text);
      * the host cell carries the IP in parentheses when the model has one and it
        differs (`host (ip)`) — this is the "host (IP)" column of the plan, one column
        instead of two near-identical ones;
      * the CPU cell falls back to `cpu_model`: the auto-collected data of
        SystemInfoCollector fills `cpu_model` while a manually typed one fills `cpu`;
      * the status cell is the caller's already TRANSLATED text (`""` = not checked yet
        — a status is a fact of the probe round, not of the project file);
      * the tags cell is the same comma-joined list the map cards show.
    """
    def _s(value) -> str:
        return str(value or "").strip()

    host, ip = _s(getattr(data, "host", "")), _s(getattr(data, "ip", ""))
    if ip and ip != host:
        host = f"{host} ({ip})" if host else ip
    cpu = _s(getattr(data, "cpu", "")) or _s(getattr(data, "cpu_model", ""))
    tags = getattr(data, "tags", None) or []
    return [
        _s(getattr(data, "alias", "")),
        host,
        str(status_text or ""),
        _s(getattr(data, "os_name", "")),
        cpu,
        _s(getattr(data, "ram", "")),
        _s(getattr(data, "disk", "")),
        ", ".join(str(t).strip() for t in tags if str(t).strip()),
    ]


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

        # v1.4.5 (ROADMAP task 3): the transient status filter — set by MainWindow
        # from the clickable status-bar counters ("" = no status filter).
        self._status_filter = ""

        # v1.4.6 (ROADMAP task 1): the LIST layout (the map is collapsed — the panel
        # stretches to the full window width and the tree carries the whole parameter
        # set). A LAYOUT flag, not data: the rows are rebuilt by `refresh_rows`, so the
        # mode switch never touches the model, the filters or the selection.
        self._list_mode = False

        # ── Server tree ────────────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # Review fix v0.8.0 (#3): colored status markers in the tree (16×16 —
        # exactly fits the dot pixmap; a single size independent of style/platform).
        self.tree.setIconSize(QSize(16, 16))
        layout.addWidget(self.tree)
        # Icon cache for the status dots ("", "online", "warn", "offline")
        self._status_dot_icons = {}

        # ── v1.5rc4 (ROADMAP task 5): the sidebar is a keyboard domain ─────────
        # The tree is where the keyboard lands when it is in the sidebar, so the tree
        # carries the visible focus frame — the SAME indicator the map and the terminal
        # canvas show (ui/focus_ring.py: one state, one colour, `theme.ACCENT_STRONG`).
        # The frame is applied DIRECTLY (not through `theme_qss.refresh()`, which hides
        # and re-shows the widget — re-showing a widget drops the focus we react to).
        self._focus_ring = (focus_ring.FocusRing(styled_widget=self.tree)
                            if focus_ring is not None else None)
        if self._focus_ring is not None:
            self.tree.installEventFilter(self)

        # v0.9.6: server tree context menu (right-click on a sidebar row).
        # CustomContextMenu policy + customContextMenuRequested signal — Qt's
        # standard path for QTreeWidget (the widget has no overridable
        # contextMenuEvent without intercepting viewport events; the signal
        # carries the position in tree coordinates, itemAt(pos) gives the row).
        # The slot handler lives in MainWindow.
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # ── Buttons (always created, i18n applied when a callback is present) ──
        # v1.4.5 (ROADMAP task 1): the compact 2×3 grid — the six full-width rows of
        # v1.1.2RC2 are three dense rows now; the buttons themselves (attributes,
        # icons, signals, i18n) are exactly the same objects as before.
        self.buttons_grid = QGridLayout()
        self.buttons_grid.setContentsMargins(0, 0, 0, 0)
        self.buttons_grid.setHorizontalSpacing(4)
        self.buttons_grid.setVerticalSpacing(4)
        for _index, (attr, icon_name, i18n_key, ru_fallback) in enumerate(_BUTTONS):
            btn = QPushButton(ru_fallback)
            self._set_btn_icon(btn, icon_name)
            btn.setMinimumHeight(_COMPACT_BUTTON_HEIGHT)  # v1.4.5: the dense row height
            # v1.4.5: and a small WIDTH minimum — see _COMPACT_BUTTON_MIN_WIDTH (without it
            # the two columns set the panel's minimum width to the sum of two full labels).
            btn.setMinimumWidth(_COMPACT_BUTTON_MIN_WIDTH)
            # v1.1.2RC2 (U1, user feedback): left alignment — indent from the
            # left edge, icon, text. QPushButton centers its content by
            # default; QStyle does not allow setting alignment without a
            # stylesheet, so — minimal CSS (frame/background stay native,
            # styling is only content positioning).
            # v1.4.5: the padding shrinks with the cell (the compact grid), the
            # alignment rule stays — it is what the U1 regression checks.
            btn.setStyleSheet(_COMPACT_BUTTON_QSS)
            if translate_fn is not None:
                try:
                    # Emojis/prefixes are already contained in the translation
                    # values themselves; re-adding them here would duplicate
                    # (there was " - - 添加连接" etc.)
                    btn.setText(self._translate(i18n_key))
                except Exception:  # noqa: BLE001 — keep the English fallback labels
                    pass
            # v1.4.5: a narrow cell elides the label — the tooltip carries it whole.
            btn.setToolTip(self._tr(i18n_key))
            setattr(self, attr, btn)
            self.buttons_grid.addWidget(btn, _index // _BUTTON_COLUMNS,
                                        _index % _BUTTON_COLUMNS)
        layout.addLayout(self.buttons_grid)

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

    # ── v1.5rc4 (ROADMAP task 5): the VISIBLE FOCUS of the sidebar ────────────
    # The panel is one of the three keyboard domains; the TREE is the widget the keyboard
    # lands in, so the tree carries the frame. The state follows the tree's own
    # FocusIn/FocusOut through an event filter (the panel owns the filter, the widget owns
    # nothing) — and it is deliberately a plain bool + one stylesheet swap, never a
    # hide/show (that would move the focus away the moment we react to it).

    def eventFilter(self, obj, event):
        """Follow the tree's focus (v1.5rc4, ROADMAP task 5) — everything else passes."""
        if obj is getattr(self, "tree", None) and self._focus_ring is not None:
            try:
                kind = event.type()
            except (RuntimeError, AttributeError):
                kind = None
            if kind == QEvent.Type.FocusIn:
                self._focus_ring.set_active(True)
            elif kind == QEvent.Type.FocusOut:
                self._focus_ring.set_active(False)
        return super().eventFilter(obj, event)

    def focus_indicator_active(self) -> bool:
        """True while the sidebar owns the keyboard (the topical test's seam)."""
        return bool(self._focus_ring is not None and self._focus_ring.is_active())

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
                btn = getattr(self, attr)
                btn.setText(self._tr(key))
                # v1.4.5: the tooltip carries the label a narrow compact cell elides.
                btn.setToolTip(self._tr(key))
            # Tag filter: item 0's label ("All tags") — without resetting the selection.
            # setCurrentIndex to the same index does not emit a signal (Qt); a
            # repeated refresh_sidebar is idempotent anyway.
            idx = self.tag_filter.currentIndex()
            self.tag_filter.setItemText(0, self._tr("filter.all_tags"))
            if idx > 0:
                self.tag_filter.setCurrentIndex(idx)
            # v1.4.6 (ROADMAP task 1): the LIST headers are i18n too — re-apply them
            # (the column WIDTHS are kept: `_apply_list_columns` resets them only when
            # the column count changes, i.e. on a real mode switch).
            self._apply_list_columns()
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
                btn.setIconSize(QSize(_COMPACT_BUTTON_ICON, _COMPACT_BUTTON_ICON))
                btn._sshmap_icon_name = name
        except Exception:  # noqa: BLE001 — the icon is cosmetic, don't break the sidebar
            pass

    def refresh_theme(self):
        """v1.4.3-fix: re-apply the theme to the panel's own icons.

        The tree's status markers are painted fresh on every `refresh_rows()`, so
        only the six action buttons carry a cached pixmap. Never raises.
        v1.5rc2: the STATUS MARKER cache is dropped here as well — it is keyed by
        status only, while the colour it bakes in moves with the theme (the row is
        repainted on the next `refresh_rows()`/`apply_status_marker`).
        v1.5rc4: the focus FRAME is a stylesheet VALUE of the same kind — its colour is
        read live from the theme, so it is re-applied here too.
        """
        self._status_dot_icons.clear()
        # v1.5rc4 (ROADMAP task 5): the focus frame is a stylesheet VALUE too (its colour
        # is read live from the theme) — re-apply it with the panel's other styles.
        if getattr(self, "_focus_ring", None) is not None:
            self._focus_ring.refresh_theme()
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

    # ── v1.4.5 (ROADMAP task 3): the transient status filter ─────────────────
    # The status bar OWNS this filter (its counters are the control); the panel only
    # holds the value and applies it while rebuilding the rows. It is combined with
    # the tag filter with AND — a row must pass BOTH. Deliberately NOT persisted:
    # a restart must never leave a sidebar hiding servers for no visible reason.

    def set_status_filter(self, status: str) -> None:
        """Set the active status filter ("" or one of _STATUS_FILTERS)."""
        value = str(status or "")
        self._status_filter = value if value in _STATUS_FILTERS else ""

    def active_status_filter(self) -> str:
        """The status the tree is filtered by, or "" (no status filter)."""
        return getattr(self, "_status_filter", "")

    # ── v1.4.6 (ROADMAP task 1): the adaptive columns — narrow vs LIST ────────
    # The panel OWNS what "list mode" looks like (its column set, its headers, its
    # cells); what CAUSES it — the map's collapsedness — belongs to MainWindow, which
    # only calls `set_list_mode()` (the "module + callbacks" pattern of this module:
    # the panel knows neither the window nor the splitter).

    def is_list_mode(self) -> bool:
        """True while the tree carries the wide LIST layout (v1.4.6)."""
        return bool(getattr(self, "_list_mode", False))

    def set_list_mode(self, enabled: bool) -> bool:
        """Switch the tree between the narrow view and the LIST layout; True if changed.

        `enabled` — the map is collapsed, so the sidebar container is the full window
        width and the tree becomes the table of server parameters (`LIST_COLUMNS`).
        Disabled — the v0.9.9.4 look: ONE column, no header, a status dot and the
        `[tags]` caption inside the row.

        Idempotent: the same mode twice changes nothing and returns False, so every
        control path of the collapse mechanism (the diamond, the strip, the menu item,
        the startup state, the settings dialog) may call it freely. The ROWS are not
        rebuilt here — the caller refreshes them with the ordinary `refresh_sidebar()`.
        """
        enabled = bool(enabled)
        if enabled == self.is_list_mode():
            return False
        self._list_mode = enabled
        try:
            self._apply_list_columns()
        except RuntimeError:
            pass  # Qt teardown — the tree is already destroyed
        return True

    def _apply_list_columns(self) -> None:
        """Apply the column set, the headers and the opening widths of the ACTIVE mode.

        Called by `set_list_mode()` (the mode changed) and by `retranslate()` (the
        headers are i18n). The opening widths are set only when the column COUNT
        changes: a language switch must not throw away widths the user dragged.
        """
        tree = self.tree
        if self.is_list_mode():
            wanted = len(LIST_COLUMNS)
            is_new_layout = tree.columnCount() != wanted
            tree.setColumnCount(wanted)
            tree.setHeaderLabels([self._tr(key) for _field, key in LIST_COLUMNS])
            tree.setHeaderHidden(False)
            if is_new_layout:
                for index, width in enumerate(_LIST_COLUMN_WIDTHS):
                    tree.setColumnWidth(index, width)
        else:
            # Back to the narrow view: ONE column, no header, no residual section.
            # `setHeaderLabels` only writes the columns it is given — the labels of the
            # dropped ones survive it (Qt), so they are cleared explicitly (a stale
            # "Host (IP)" must never sit behind the one-column view).
            header = tree.headerItem()
            for index in range(tree.columnCount()):
                header.setText(index, "")
            tree.setColumnCount(1)
            tree.setHeaderLabels([""])
            tree.setHeaderHidden(True)

    def _status_text(self, status: str) -> str:
        """The translated status of the LIST "Status" column ("" — never probed).

        The `legend.status.*` keys are reused on purpose: the same three words the
        legend and the status-filter hint already use — no fourth spelling of
        online/warn/offline in the translation files.
        """
        value = str(status or "")
        if value not in _STATUS_FILTERS:
            return ""
        return self._tr(f"legend.status.{value}")

    def refresh_rows(self, nodes, query: str = ""):
        """Rebuild the tree rows: search (query) + the active tag/status filters.

        `nodes` — an iterable of ServerNode (MainWindow passes scene.nodes());
        the panel does not depend on the scene — only on the node data.

        v1.4.6 (ROADMAP task 1): the row SHAPE follows the active mode — the narrow
        `alias (host) [tags]` caption, or one cell per `LIST_COLUMNS` entry. The
        filtering, the search and the public API are identical in both modes.
        """
        self.tree.clear()
        active_tag = self.active_tag_filter()
        active_status = self.active_status_filter()
        list_mode = self.is_list_mode()
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
            # v1.4.5 (ROADMAP task 3): the status filter — AND with the tag filter.
            if active_status and (getattr(node, "status", "") or "") != active_status:
                continue

            item = QTreeWidgetItem()
            # Column 0 carries the node id in BOTH modes — the click/double-click slots
            # and _sync_selection_state read it from there (never from another column).
            if list_mode:
                cells = list_cell_values(node.data, self._status_text(node.status))
                item.setText(0, cells[0])
                for column, value in enumerate(cells[1:], start=1):
                    if value:
                        item.setText(column, value)   # an empty field stays an empty cell
            else:
                item.setText(0, f"{node.data.alias}  ({node.data.host})")
            item.setData(0, Qt.UserRole, node.data.id)
            # Review fix v0.8.0 (#3): colored status marker for the node (online/warn/offline/not checked)
            self.apply_status_marker(item, node.status, node.data.host or "")
            # v0.9.4: the tag caption at the end of the row ("[tag1, tag2]", up to 3 tags).
            # v1.4.6: only in the NARROW mode — the LIST layout has a column of its own.
            # v1.1.2RC2 (N8): setForeground(0, palette().windowText()) REMOVED — under
            # the "gray" comment it painted the WHOLE row with the standard text
            # color (visual no-op: the color was indistinguishable from the default).
            tags = getattr(node.data, "tags", None) or []
            if tags and not list_mode:
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
        """The status mark of a tree row — the SHAPE and the colour of the cards (v1.5rc2).

        The shape comes from the declaration (`theme.STATUS_SHAPES` through
        `ui/status_shape.py`), the colour from the same palette the cards paint with,
        so a status is readable in greyscale here exactly as it is on the map.
        """
        icon = self._status_dot_icons.get(status)
        if icon is not None:
            return icon
        color = ServerNode.STATUS_COLORS.get(status, ServerNode.COLOR_DOT_IDLE)
        if status_shape is not None:
            icon = status_shape.shape_icon(status, color, 16)
        else:  # the flat-layout fallback: the round dot of v1.4.x
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
        """Put the status dot + tooltip (i18n node.status.*) on a tree row.

        v1.4.6 (ROADMAP task 3): in the LIST layout the row also carries the status as
        TEXT (the `sidebar.list.status` column) — a probe result must refresh it in
        place, without a full rebuild of the rows (the scroll position survives).
        """
        item.setIcon(0, self._status_dot_icon(status))
        if status and status in ServerNode.STATUS_COLORS:
            tip = self._tr(f"node.status.{status}", host=host or "")
            # i18n returned the "key" (no translation) — show the status without the key
            item.setToolTip(0, tip if not tip.startswith("[") else f"{status}: {host}")
        else:
            item.setToolTip(0, "")  # not checked — no tooltip
        if self.is_list_mode() and self.tree.columnCount() > _LIST_STATUS_COLUMN:
            item.setText(_LIST_STATUS_COLUMN, self._status_text(status))

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
