# -*- coding: utf-8 -*-
"""v0.9.2: Command palette (Ctrl+K).

Mouse-free quick actions: fuzzy search across all application actions
(menu items) + project servers (select → center the map on the node).

Design:
- CommandPalette(QDialog, Qt.Popup-style frameless window): input line
  on top + a QListWidget with results.
- Commands are collected from the main window's QActions (the menus
  already carry i18n and slots) plus a dynamic servers block (rebuilt
  on every open).
- Filtering is simple subsequence fuzzy matching (no external deps):
  "cns" matches "Connect via SSH"; the tighter the match, the higher
  the rank.
- Enter runs the first/selected command; Esc closes the palette.

i18n: keys palette.* × en/ru/zh; action names are taken from the
already-translated QAction texts (no duplicate translations).
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QWidget, QHBoxLayout, QLabel,
)

try:
    # Package-style run (from the project root).
    # v0.9.4-fix: i18n exports t(), not translate() — the old import
    # silently failed and the palette showed raw keys instead of
    # translations.
    from i18n import t as _translate
except Exception:  # pragma: no cover - flat run
    try:
        from .i18n import t as _translate  # package-style run as a subpackage
    except Exception:
        _translate = None


def _t(key: str) -> str:
    if _translate is not None:
        try:
            return _translate(key)
        except Exception:
            pass
    return key


# v1.4rc3: the glyph of each palette section (a plugin command is not a core action).
_ICON_BY_KIND = {"server": "add_server", "plugin": "plugin"}


def fuzzy_score(pattern: str, text: str):
    """Subsequence fuzzy: return (score, matched) or None.

    score — lower is better (tighter matches win).
    Case-insensitive; word boundaries give a bonus.
    """
    p, s = pattern.lower(), text.lower()
    if not p:
        return (1000, True)
    score = 0
    idx = 0
    last = -2
    for ch in p:
        found = s.find(ch, idx)
        if found < 0:
            return None
        gap_penalty = 0 if found == last + 1 else min(found - idx, 10)
        score += gap_penalty
        if found == 0 or s[found - 1] in " ._-\t":
            score -= 3  # word-start bonus
        last = found
        idx = found + 1
    return (score - (len(s) - len(p)) // 20, True)


class CommandPalette(QDialog):
    """Command palette: search across actions and servers (Ctrl+K)."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.mw = main_window
        self._commands = []      # [(label, kind, callable)]
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        # v0.9.3 fix: the chrome texts (title/placeholder/hint) are
        # re-applied on every open — see retranslate_ui();
        # previously they were frozen in the language active when the
        # palette was created.
        self.setWindowTitle(_t("palette.title"))
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(_t("palette.placeholder"))
        self.input.textChanged.connect(self._refilter)
        layout.addWidget(self.input)

        self.listw = QListWidget(self)
        self.listw.itemActivated.connect(self._run_current)
        layout.addWidget(self.listw)

        hint_row = QHBoxLayout()
        self._hint_label = QLabel(_t("palette.hint"), self)
        self._hint_label.setStyleSheet("color: gray;")
        hint_row.addWidget(self._hint_label)
        layout.addLayout(hint_row)

        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                row = self.listw.currentRow()
                self.listw.setCurrentRow(min(row + 1, self.listw.count() - 1))
                return True
            if key == Qt.Key_Up:
                row = self.listw.currentRow()
                self.listw.setCurrentRow(max(row - 1, 0))
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._run_current()
                return True
            if key == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    # ── Collecting commands ─────────────────────────────────────

    def _collect_commands(self):
        cmds = []

        # 1) Main window menu actions (already translated via i18n).
        seen = set()

        def walk(menu):
            for act in menu.actions():
                menu_child = act.menu()
                if menu_child is not None:
                    walk(menu_child)
                    continue
                text = act.text().replace("&", "").strip()
                if not text or text in ("-",):
                    continue
                slot = _qaction_slot(act)
                if slot is None:
                    continue
                ident = id(act)
                if ident in seen:
                    continue
                seen.add(ident)
                cmds.append((text, "action", lambda a=act: a.trigger()))

        bar = self.mw.menuBar()
        # v0.9.8 bugfix (PySide6 6.11): keep the top-level QAction wrappers
        # in a list until the walk is finished — when a Python QAction
        # wrapper with an attached QMenu dies, PySide6 destroys the
        # underlying C++ menu (MainWindow._qaction_guard holds the same
        # guard globally; this is a local safety net for windows
        # without it).
        tops = list(bar.actions())
        for top in tops:
            child = top.menu()
            if child is not None:
                walk(child)

        # 2) Project servers → "center on node".
        try:
            servers = self.mw.scene.nodes()
        except Exception:
            servers = []
        for node in servers:
            label = "{} — {} ({})".format(
                _t("palette.kind_server"),
                getattr(node.data, "alias", "") or "",
                getattr(node.data, "host", "") or "",
            )
            cmds.append((label, "server",
                         lambda n=node: self._reveal_node(n)))

        # 3) v1.4rc3 (plugin foundation, task 7): the commands contributed by plugins.
        # The section comes AFTER the core ones, so a plugin can never shadow a built-in
        # command (PLUGINS.md §3). The manager calls `register_commands` synchronously
        # (a UI hook, budget 200 ms) and hands back frozen records; the callback is run
        # through the manager too (`call_hook_wrapped`), so an exception in plugin code
        # is a log line + a status-bar report, never a crash of the palette. `text` is
        # the AUTHOR's string — not an i18n key (PLUGINS.md §7).
        plugin_manager = getattr(self.mw, "_plugin_manager", None)
        if plugin_manager is not None:
            try:
                pairs = plugin_manager.plugin_commands()
            except Exception:  # noqa: BLE001 — a broken plugin must not break Ctrl+K
                pairs = []
            for plugin_id, cmd in pairs:
                cmds.append((cmd.text, "plugin",
                             lambda pid=plugin_id, c=cmd: self._run_plugin_command(pid, c)))

        self._commands = cmds

    def _run_plugin_command(self, plugin_id, cmd):
        """v1.4rc3: run ONE command a plugin contributed (through the manager's wrapper).

        The context is the PLUGIN's own (the command sees the same `ctx` its
        `register_commands` got) and the manager owns the timing budget and the "never
        throws" guarantee (`call_hook_wrapped`) — an exception in plugin code is a log
        line plus a status-bar report, never a broken palette. A command whose callback
        is not callable is a no-op. Returns True when the callback was invoked.
        """
        manager = getattr(self.mw, "_plugin_manager", None)
        callback = getattr(cmd, "callback", None)
        if manager is None or not callable(callback):
            return False
        rec = manager.get(plugin_id)
        ctx = getattr(rec, "context", None) if rec is not None else None
        manager.call_hook_wrapped(plugin_id, "register_commands", callback, ctx)
        return True

    @staticmethod
    def _reveal_node(node):
        """Center the view on the node + highlight it.

        v1.2.4.1 (task 5): map collapsed — centering is skipped (selection
        still works; no exceptions and no auto-showing the map).
        """
        mw = node.scene().views()[0].window() if node.scene().views() else None
        scene = node.scene()
        scene.clearSelection()
        node.setSelected(True)
        if mw is not None and hasattr(mw, "view") \
                and not getattr(mw, "_map_collapsed", False):
            mw.view.centerOn(node)

    # ── Show / filter / run ─────────────────────────────────────

    def retranslate_ui(self):
        """v0.9.3 fix: re-translate the static chrome (commands are
        rebuilt from QActions on every open anyway — see open_palette)."""
        self.setWindowTitle(_t("palette.title"))
        self.input.setPlaceholderText(_t("palette.placeholder"))
        self._hint_label.setText(_t("palette.hint"))

    def open_palette(self):
        """Open the palette: collect current commands, reset the filter."""
        self.retranslate_ui()
        self._collect_commands()
        self.input.clear()
        self._refilter("")
        # Center on the parent window
        parent = self.parent() or self.mw
        geo = parent.geometry()
        self.resize(520, 420)
        self.move(geo.center() - QPoint(self.width() // 2, self.height() // 2))
        self.input.setFocus()
        return self.exec()

    def _refilter(self, text=""):
        text = self.input.text().strip()
        self.listw.clear()
        scored = []
        for label, kind, fn in self._commands:
            res = fuzzy_score(text, label)
            if res is None:
                continue
            scored.append((res[0], kind, label, fn))
        scored.sort(key=lambda x: (x[0], x[2].lower()))
        for _, kind, label, fn in scored[:50]:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, fn)
            # v0.9.3 fix: the "🖥/⚡" emojis were removed — the project
            # deliberately moved to vector icons (ui/icons.py,
            # Segoe UI Emoji renders poorly).
            # v1.4rc3: the plugin commands get the puzzle glyph of the "Plugins" menu.
            try:
                from ui.icons import get_icon
                icon = get_icon(_ICON_BY_KIND.get(kind, "connection"))
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
            except Exception:  # noqa: BLE001 — icons are cosmetic, don't break the palette
                pass
            self.listw.addItem(item)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _run_current(self):
        item = self.listw.currentItem()
        if item is None:
            self.accept()
            return
        fn = item.data(Qt.UserRole)
        self.accept()
        if callable(fn):
            fn()


def _qaction_slot(act):
    """Get a callable slot for a QAction without PyQt private APIs.

    PyQt6 does not expose the slot directly; instead we wrap trigger(),
    and disabled actions are skipped via isEnabled at run time.
    """
    if not act.isCheckable() and act.menu() is None:
        return act
    return None
