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

v1.5rc3 (ROADMAP task 4): an EMPTY query is the first screen, so it opens with a
bounded **"Start here"** block — the actions this session already ran (newest first),
then the declared frequent set (`START_HERE_ACTION_IDS`) — and only then the ordinary
alphabetical list. The block is a caption row plus at most `START_HERE_MAX` commands;
the commands it offers are not repeated below it.

i18n: keys palette.* × en/ru/zh; action names are taken from the
already-translated QAction texts (no duplicate translations).
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QHBoxLayout, QLabel,
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


def _t(key: str, **kw) -> str:
    """Safe i18n hook. v1.6.5: it also carries the unmanaged gate's refusal template."""
    if _translate is not None:
        try:
            return _translate(key, **kw) if kw else _translate(key)
        except Exception:
            pass
    return key


try:  # v1.6.5 (ROADMAP task 4): the ONE gate of an unmanaged card
    from . import unmanaged
except ImportError:
    try:
        from ui import unmanaged
    except ImportError:  # flat layout without ui/unmanaged — no row is ever gated
        unmanaged = None


# v1.4rc3: the glyph of each palette section (a plugin command is not a core action).
_ICON_BY_KIND = {"server": "add_server", "plugin": "plugin"}

# ── v1.5rc3 (ROADMAP task 4): the "Start here" block ───────────────────────────────
# On an EMPTY query the palette used to be a plain alphabetical list of everything.
# The first screen now offers the handful of actions a user actually starts with —
# the ones they ran in this session first (recent), then the declared frequent set —
# under one header, before the alphabetical rest. Both lists are bounded, so the block
# answers "where do I begin" instead of "here are 60 rows".
START_HERE_ACTION_IDS = (
    "file.new", "file.open", "file.save",
    "edit.add_server", "edit.add_connection",
    "file.import_servers", "file.import_ssh_config",
    "view.fit_map", "view.find_on_map",
)
START_HERE_MAX = 8        # rows of the block (recent + frequent together)
PALETTE_RECENT_MAX = 5    # how many recently RUN actions the block remembers


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
        # v1.5rc3 (ROADMAP task 4): the "start here" machinery. `_action_ids` maps the
        # identity of a collected command's callable to its registry action id (the
        # palette walks QActions, which carry their id in `_hotkey_targets`), and
        # `_recent` is the session's list of recently RUN action ids, newest first.
        self._action_ids = {}    # id(callable) -> action_id
        self._recent = []        # [action_id, …] — bounded by PALETTE_RECENT_MAX
        self._start_here = []    # [(label, kind, callable)] — the block, built per open
        self._header_rows = 0    # 1 while the "Start here" header row is on screen
        # v1.6.5 (ROADMAP task 4): the node the gate asks about — the palette's commands
        # act on the SELECTION, so a row whose verb needs a login is disabled while an
        # unmanaged card is the one the selection holds.
        self._gate_target = None
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
        self._action_ids = {}
        by_action = {}          # action_id -> (label, kind, callable)

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
                runner = (lambda a=act: a.trigger())
                entry = (text, "action", runner)
                cmds.append(entry)
                # v1.5rc3: the registry id of this QAction (for the "start here" block);
                # the window's `_hotkey_targets` IS the action_id → QAction map.
                action_id = self._action_id_of(act)
                if action_id:
                    self._action_ids[id(runner)] = action_id
                    by_action.setdefault(action_id, entry)

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
        # v1.6.5 (ROADMAP task 4): the gate's subject — the selected card, when the window
        # has exactly one. Read HERE (the same pass that collects the rows) so the whole
        # palette is judged against ONE snapshot of the selection.
        try:
            self._gate_target = self.mw.scene.get_selected_node()
        except Exception:  # noqa: BLE001 — a window without a scene has nothing to gate
            self._gate_target = None
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
        self._build_start_here(by_action)

    def _action_id_of(self, act) -> str:
        """The registry id of a collected QAction ("" — not a registry action).

        `MainWindow._hotkey_targets` is the action_id → targets mapping the registry
        installs into, so it answers this without a second table. A toolbar MIRROR is
        not in it (v1.3.3.3: mirrors carry no sequence) — and a mirror is a duplicate
        of the menu item anyway, which the walk already collected.
        """
        targets = getattr(self.mw, "_hotkey_targets", None) or {}
        for action_id, objects in targets.items():
            for obj in objects:
                if obj is act:
                    return action_id
        return ""

    def _build_start_here(self, by_action: dict) -> None:
        """The bounded "Start here" block: the session's recent actions, then the frequent ones.

        Only actions the palette can really run (a menu QAction with a registry id)
        enter the block, so it can never offer a row that is missing from the menus of
        this build. An empty block is fine — the alphabetical list follows anyway.
        """
        ordered = [aid for aid in self._recent if aid in by_action]
        ordered += [aid for aid in START_HERE_ACTION_IDS
                    if aid in by_action and aid not in ordered]
        self._start_here = [by_action[aid] for aid in ordered[:START_HERE_MAX]]

    def _remember_action(self, action_id: str) -> None:
        """Remember a RUN action for the next "Start here" block (newest first, bounded)."""
        if not action_id:
            return
        self._recent = [action_id] + [a for a in self._recent if a != action_id]
        del self._recent[PALETTE_RECENT_MAX:]

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
            # v1.4.4 (ROADMAP task 1): the palette jumps to the node NOW — a running
            # camera flight (a sidebar reveal / a fit) is cancelled first, otherwise the
            # animation would keep moving the camera over the palette's centering.
            stopper = getattr(mw.view, "stop_camera_flight", None)
            if callable(stopper):
                stopper()
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
        self._header_rows = 0
        # v1.5rc3 (ROADMAP task 4): an EMPTY query is the first screen — it opens with
        # the bounded "Start here" block (a header row + up to START_HERE_MAX commands)
        # instead of dropping the user into the alphabetical middle of everything. A
        # typed query is a search and behaves exactly as it always did.
        skip = set()
        if not text and self._start_here:
            header = QListWidgetItem(_t("palette.start_here"))
            header.setFlags(Qt.ItemFlag.NoItemFlags)   # a caption, not a command
            self.listw.addItem(header)
            self._header_rows = 1
            for entry in self._start_here:
                self._add_row(entry)
                skip.add(id(entry[2]))
        scored = []
        for label, kind, fn in self._commands:
            if id(fn) in skip:
                continue     # already offered above — never list a command twice
            res = fuzzy_score(text, label)
            if res is None:
                continue
            scored.append((res[0], kind, label, fn))
        scored.sort(key=lambda x: (x[0], x[2].lower()))
        for _, kind, label, fn in scored[:50]:
            self._add_row((label, kind, fn))
        if self.listw.count():
            # Never land the cursor on the caption row (a NoItemFlags item is not a
            # command: Enter on it would close the palette without running anything).
            self.listw.setCurrentRow(min(self._header_rows, self.listw.count() - 1))

    def _add_row(self, entry):
        """Add one row of the list (the icon follows the kind; the action id rides along)."""
        label, kind, fn = entry
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, fn)
        # v1.5rc3: the registry id of this row ("" for a server/plugin row) — what
        # `_run_current()` feeds into the "recently used" list of the start-here block.
        action_id = self._action_ids.get(id(fn), "")
        item.setData(Qt.UserRole + 1, action_id)
        # v1.6.5 (ROADMAP task 4): a command that cannot work on the selected card is
        # DISABLED here and carries the gate's own sentence in its tooltip — the palette
        # filters through the SAME table the two context menus use, so it can neither offer
        # a verb the menus refuse nor refuse one they offer.
        if unmanaged is not None and action_id \
                and unmanaged.blocked_registry_action(action_id, self._gate_target):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip(unmanaged.refusal_text(_t, label))
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
        return item

    def refresh_theme(self):
        """v1.4.3-fix: re-apply the theme to the OPEN palette.

        The rows are rebuilt from `get_icon()` on every open, so a palette that is
        CLOSED follows the theme by itself. An OPEN one holds QListWidgetItems with
        their QIcons already attached (a QListWidgetItem does not share the QIcon
        object the registry re-paints), so the list is filtered again here — which
        rebuilds it with the new glyphs. Never raises.
        """
        try:
            self.listw.clear()
            self._refilter(self.input.text())
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / not fully built yet

    def _run_current(self):
        item = self.listw.currentItem()
        if item is None:
            self.accept()
            return
        fn = item.data(Qt.UserRole)
        action_id = item.data(Qt.UserRole + 1)
        # v1.6.5 (ROADMAP task 4): a gated row is disabled, and Enter on it is NOT a way
        # around the gate (the event filter calls this method directly, so Qt's own refusal
        # to activate a disabled item is not enough).
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            self.accept()
            return
        self.accept()
        # v1.5rc3 (ROADMAP task 4): a command that was really RUN is what the next
        # "Start here" block offers first (the caption row has no command — no record).
        self._remember_action(str(action_id or ""))
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
