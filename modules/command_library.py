# -*- coding: utf-8 -*-
"""v1.3 (ROADMAP v1.3): "Terminal macros" — the command/script library of the terminal panel.

Module composition:
  * CommandLibraryStore — the ~/.sshmap/commands.json store (pure Python, no Qt):
    an atomic write of the WHOLE document (tmp + fsync + os.replace, the i18n.save_config
    pattern, but WITHOUT merge — the file belongs entirely to this module); first run
    (no file) — a seed of 5 examples with seeded: true; a corrupt file / a foreign type —
    a log line + an EMPTY library (never raises and does NOT re-seed an existing file — user data is never overwritten);
  * CommandLibraryPanel — the panel left of the session tabs in both containers
    (SSHTerminalWindow and TerminalDockContent): the search + the "category → command" tree +
    the Add/Edit/Delete buttons; a double click or Enter on a command — the send of
    the macro to the ACTIVE session (page.widget.send_macro → a direct terminal_thread.send_data(),
    NOT via MultiInputHub.broadcast — the pre-approved ROADMAP v1.3 decision: an addressed
    action, not a broadcast); the collapse into a thin strip (the v1.2.4.1 technique) — the state
    in a single config key ui_cmdlib_collapsed for BOTH containers (a merge write via
    i18n.save_config; the terminal_wheel pattern: the config only, not in SettingsDialog.collect());
  * CommandLibraryDialog — the add/edit dialog (name/category/command/enabled);
    OK is blocked until the name and the command are non-empty.

Data: the document {"seeded": true, "commands": [{id, name, command, category, enabled}]}.
The two containers (window + dock) may live over the SAME file: the panel re-reads the file in
showEvent and after local changes; live synchronization between the panels — backlog.

Test seams: the store with an explicit path= (the panel constructor accepts store=); QMessageBox
and QMenu are taken as module attributes at call time (monkeypatch CL.QMessageBox works);
the context menu is built by the _build_context_menu(item) method — the tests trigger the QActions
without menu.exec().

Import discipline: ui.main_window is NOT imported (a cycle: main_window → the terminal
containers → this module) — the "◇" diamond and the collapse strip are duplicated locally
(the v1.2.4.1 technique, colors from ui/theme.py). session_tabs — a duck-typed QTabWidget
(a constructor parameter / set_session_tabs); send_macro is called dynamically on
page.widget — the panel does not know about TerminalSessionPage.
"""

import json
import os
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:  # v1.2.5: the central theme (the terminal_page/terminal_dock pattern)
    from ..ui import theme
except ImportError:
    from ui import theme


# ── i18n / config (cached helpers per the ssh_terminal.py pattern) ──────────

_t_cache = None


def get_translator():
    """Safe i18n helper — returns cached translator or fallback."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache


def _log():
    """The app logger (lazy, the terminal_widget._get_app_log pattern)."""
    try:
        from modules.logger import get_logger as _gl
        return _gl("modules.command_library")
    except Exception:
        return None


def _save_config(partial_update: dict) -> bool:
    """A merge write into ~/.sshmap/config.json (i18n.save_config; never raises)."""
    try:
        from i18n import save_config as _sc
        return bool(_sc(partial_update))
    except Exception:
        return False


def _load_collapse_state() -> bool:
    """ui_cmdlib_collapsed from the config (a read WITHOUT a write-back; the default — expanded)."""
    try:
        from i18n import load_config as _lc
        v = _lc().get("ui_cmdlib_collapsed")
        return bool(v) if isinstance(v, bool) else False
    except Exception:
        return False


# ── storage (pure Python, no Qt) ────────────────────────────────────────────

def _default_store_path() -> str:
    """~/.sshmap/commands.json — next to config.json (the same i18n directory)."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "commands.json")


def _atomic_write_json(path: str, doc) -> bool:
    """An atomic write of the WHOLE document (tmp + flush + fsync + os.replace).

    The i18n.save_config() pattern, but WITHOUT merge: commands.json belongs entirely
    to this module — merging foreign keys is neither needed nor safe here. False on OSError."""
    d = os.path.dirname(path)
    tmp = path + ".tmp"
    try:
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # an atomic rename (one file system)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _seed_entries() -> list:
    """The first-run seed: 5 examples (v1.3.3.4: the NAMES are i18n keys).

    v1.3.3.4 (ROADMAP task 4): the five names were the only user-visible English
    literals of the application that were not i18n keys — and they land in
    `~/.sshmap/commands.json`, i.e. in the user's own content file, on the very
    first run of a ru/zh/de user. The names now come from `terminal.cmdlib.seed.*`
    (resolved through the cached translator, i.e. in the ACTIVE language at the
    moment of the first seeding).

    The seeding happens ONLY when the file does not exist (see load()): the stored
    library is the user's own text and is NEVER re-translated — switching the
    language afterwards leaves an existing `commands.json` exactly as it is
    (the ROADMAP requirement of task 4). The CATEGORIES stay plain literals on
    purpose: they are content of a user-editable file (like the commands
    themselves — "df -h" is not translated either), and the ROADMAP fixes the key
    set of this version at the five NAMES.

    The last entry — a multi-line script (awk with a line continuation): a live example
    of the macros going to the PTY as a bracketed-paste block, not as line-by-line input."""
    t = get_translator()
    seeds = [
        (t("terminal.cmdlib.seed.tail_nginx"),
         "tail -f /var/log/nginx/error.log", "Logs"),
        (t("terminal.cmdlib.seed.restart_docker"),
         "systemctl restart docker", "Services"),
        (t("terminal.cmdlib.seed.top_processes"),
         "top -bn1 | head -n 20", "System"),
        (t("terminal.cmdlib.seed.disk_usage"),
         "df -h", "System"),
        (t("terminal.cmdlib.seed.sum_column"),
         "awk '{s+=$1} END {print \"total: \" s}' \\\n    /var/log/nginx/access.log",
         "Scripts"),
    ]
    return [{"id": uuid.uuid4().hex[:12], "name": name, "command": cmd,
             "category": cat, "enabled": True} for (name, cmd, cat) in seeds]


class CommandLibraryStore:
    """The command library store (~/.sshmap/commands.json).

    The document format: {"seeded": true, "commands": [{id, name, command, category,
    enabled}, ...]}. path — explicit (a test seam) or the default. load()/save()
    never raise; corrupt data → an empty library + a log line."""

    def __init__(self, path: str = None):
        self.path = path or _default_store_path()

    # ── reading ─────────────────────────────────────────────────────────────

    def load(self) -> list:
        """The library as a list of normalized entries.

        * no file → FIRST RUN: a seed of 5 examples, the document is written (seeded: true),
          the seed is returned (if the write fails — the seed is returned in memory);
        * corrupt JSON / a foreign top-level type → a log line + [] (the file exists —
          it must NOT be re-seeded: this is user data, even if damaged);
        * invalid entries (not a dict, an empty name/command) are dropped one by one."""
        if not os.path.isfile(self.path):
            seeded = _seed_entries()
            if not _atomic_write_json(self.path, {"seeded": True, "commands": seeded}):
                lg = _log()
                if lg is not None:
                    lg.warning(f"command library: seed write failed for {self.path}")
            return [dict(e) for e in seeded]
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            lg = _log()
            if lg is not None:
                lg.warning(f"command library: corrupt file {self.path} — starting empty")
            return []
        if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
            lg = _log()
            if lg is not None:
                lg.warning(f"command library: unexpected document type in {self.path} — starting empty")
            return []
        out = []
        for e in data["commands"]:
            norm = self._normalize(e)
            if norm is not None:
                out.append(norm)
        return out

    @staticmethod
    def _normalize(e):
        """An entry → {id, name, command, category, enabled} or None (invalid)."""
        if not isinstance(e, dict):
            return None
        name = e.get("name")
        command = e.get("command")
        name = name.strip() if isinstance(name, str) else ""
        command = command if isinstance(command, str) else ""
        if not name or not command:
            return None   # without a name/command the entry is useless — drop it
        cid = e.get("id")
        if not (isinstance(cid, str) and cid):
            cid = uuid.uuid4().hex[:12]
        category = e.get("category")
        category = category.strip() if isinstance(category, str) else ""
        enabled = e.get("enabled", True)
        return {"id": cid, "name": name, "command": command,
                "category": category, "enabled": bool(enabled)}

    # ── writing ─────────────────────────────────────────────────────────────

    def save(self, commands: list) -> bool:
        """An atomic write of the WHOLE document. False on an I/O error (the file is untouched)."""
        doc = {"seeded": True, "commands": [dict(c) for c in commands]}
        return _atomic_write_json(self.path, doc)


# ── collapsing: a local copy of v1.2.4.1 (no ui.main_window import) ──────────────

def _diamond_icon(size: int = 20):
    """A vector "◇" diamond on a size×size canvas (the panel collapse button).

    A local copy of the ui/main_window._diamond_icon() technique (v1.2.4.1-fix):
    a QPainterPath on a transparent QPixmap, colors — ui/theme.py. The duplication is deliberate:
    command_library does not import ui.main_window (a cycle)."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(theme.ICON_COLOR), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    s = float(size) / 20.0
    path = QPainterPath()
    path.moveTo(10.0 * s, 4.5 * s)
    path.lineTo(15.5 * s, 10.0 * s)
    path.lineTo(10.0 * s, 15.5 * s)
    path.lineTo(4.5 * s, 10.0 * s)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


class _CollapseStrip(QWidget):
    """The thin clickable strip of the collapsed panel (v1.3; the v1.2.4.1 technique).

    A click ANYWHERE = expand (expand_requested); the "◇" diamond at the bottom right +
    a tooltip (set by the panel). The real body is hidden (hide()) at the same time: a hidden
    container member takes 0px — native Qt, no custom layout. Colors — the app's dark
    palette (theme.BASE_BG / theme.SURFACE_ALT)."""

    expand_requested = Signal()
    STRIP_WIDTH = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.STRIP_WIDTH)
        self.setMinimumHeight(60)
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.SURFACE_ALT if self._hover else theme.BASE_BG))
        # The "◇" diamond at the bottom right (the same point as the expanded panel's button).
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


class _CommandTree(QTreeWidget):
    """The QTreeWidget of the command library (v1.3).

    Enter/Return on the selected entry — the explicit entry_entered signal. We do NOT use
    the native itemActivated for sending: in Qt 6.11 it is emitted after a double
    click as well (right after itemDoubleClicked) — connecting to it would have doubled
    the sending (checked with a probe: dblclick → doubleClicked+activated, Enter → activated only).
    The other keys — the stock QTreeWidget behavior."""

    entry_entered = Signal(object)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and not (event.modifiers() & ~Qt.KeyboardModifier.NoModifier):
            item = self.currentItem()
            if item is not None:
                self.entry_entered.emit(item)
                event.accept()
                return  # without super(): the native activated is not emitted, the editor does not open
        super().keyPressEvent(event)


# ── the add/edit dialog ─────────────────────────────────────────────────────

class CommandLibraryDialog(QDialog):
    """v1.3: the library command dialog (name / category / command / enabled).

    entry=None — the add mode, otherwise — the edit mode (the fields are pre-filled).
    The category — an editable QComboBox with the existing categories
    (new ones are typed freely). OK is blocked until the name AND the command are non-empty
    (a double guard: the disabled button + the check in _on_accept). The command is NOT
    stripped at the edges (the trailing line breaks matter — build_macro_payload
    normalizes them on send)."""

    def __init__(self, entry: dict = None, categories: list = None, parent=None):
        super().__init__(parent)
        t = get_translator()
        self.setWindowTitle(t("terminal.cmdlib.edit") if entry else t("terminal.cmdlib.add"))
        form = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.category_edit = QComboBox()
        self.category_edit.setEditable(True)
        for c in (categories or []):
            self.category_edit.addItem(c)
        self.command_edit = QPlainTextEdit()
        self.command_edit.setFixedHeight(120)
        self.enabled_check = QCheckBox(t("terminal.cmdlib.enabled"))
        self.enabled_check.setChecked(True)

        form.addRow(t("terminal.cmdlib.name"), self.name_edit)
        form.addRow(t("terminal.cmdlib.category"), self.category_edit)
        form.addRow(t("terminal.cmdlib.command"), self.command_edit)
        form.addRow("", self.enabled_check)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        form.addWidget(box)

        if entry:
            self.name_edit.setText(entry.get("name", ""))
            cat = entry.get("category", "")
            if cat and cat not in (categories or []):
                self.category_edit.addItem(cat)
            self.category_edit.setCurrentText(cat)
            self.command_edit.setPlainText(entry.get("command", ""))
            self.enabled_check.setChecked(bool(entry.get("enabled", True)))
        else:
            # The add mode: the category is NOT pre-filled with the first of the list —
            # an editable QComboBox would show items[0] by default; an empty text
            # is allowed (a new category is typed freely).
            self.category_edit.setCurrentText("")

        self._ok = box.button(QDialogButtonBox.StandardButton.Ok)
        self.name_edit.textChanged.connect(self._validate)
        self.command_edit.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        try:
            ok = bool(self.name_edit.text().strip()) \
                and bool(self.command_edit.toPlainText().strip())
            self._ok.setEnabled(ok)
        except RuntimeError:
            pass  # the C++ object is already deleted (a close race)

    def _on_accept(self):
        """The double guard: OK is disabled anyway while the fields are empty."""
        if not (self.name_edit.text().strip() and self.command_edit.toPlainText().strip()):
            return
        self.accept()

    def result_entry(self) -> dict:
        """{name, category, command, enabled} — the panel issues the id (a new one / its own)."""
        return {
            "name": self.name_edit.text().strip(),
            "category": self.category_edit.currentText().strip(),
            "command": self.command_edit.toPlainText(),
            "enabled": bool(self.enabled_check.isChecked()),
        }


# ── the library panel ───────────────────────────────────────────────────────

class CommandLibraryPanel(QWidget):
    """v1.3 (ROADMAP v1.3): the "Terminal macros" panel — the command/script library.

    The left part of the QSplitter in both containers (SSHTerminalWindow / TerminalDockContent):
    the header + the collapse button, the search, the "category → command" tree
    (2 columns: the name, the command text; disabled entries — in the muted color),
    the Add/Edit/Delete buttons. A double click or Enter on a command — the send
    to the ACTIVE session (session_tabs.currentWidget() → page.widget.send_macro):
    a direct terminal_thread.send_data(), NOT via MultiInputHub.broadcast
    (the pre-approved ROADMAP v1.3 decision). The action summary — the status_message
    (str, int) signal into the containers' existing bridges (_on_page_status_message).

    Collapsing: the _CollapseStrip strip (the v1.2.4.1 technique), the state — a single
    config key ui_cmdlib_collapsed for BOTH containers (a merge write; read
    at creation without a re-save; not in SettingsDialog.collect() —
    the terminal_wheel pattern). The file is re-read in showEvent and after local
    changes (two containers over one file; live synchronization — backlog).

    Test seams: store= (an explicit path), session_tabs duck-typed, QMessageBox/QMenu —
    module attributes (monkeypatch CL.QMessageBox), _build_context_menu(item) — the menu
    without exec()."""

    status_message = Signal(str, int)   # (text, timeout_ms); 0 — sticky

    def __init__(self, session_tabs=None, store: CommandLibraryStore = None, parent=None):
        super().__init__(parent)
        t = get_translator()
        self._store = store if store is not None else CommandLibraryStore()
        self.session_tabs = session_tabs   # duck-typed QTabWidget (set_session_tabs)
        # v1.3.3.5 (ROADMAP task 6): the container may host MORE than the tabs (the
        # terminal window's split pane) and knows which session the user is in — it
        # installs a callable here (SSHTerminalWindow.active_session); without one the
        # active session stays session_tabs.currentWidget() (the v1.3 behaviour).
        self._active_session_provider = None
        self._entries = []                 # the current state (from the file)
        self._by_id = {}                   # id → the live entry (item.data stores ONLY the id — see _rebuild_tree)
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The collapsed state: the thin strip (a click anywhere — expand).
        self._strip = _CollapseStrip(self)
        self._strip.expand_requested.connect(lambda: self.set_collapsed(False))
        self._strip.setToolTip(t("terminal.cmdlib.expand_tooltip"))
        layout.addWidget(self._strip)

        # The expanded body. The minimum width is 86 (not the "convenient" 180): the total
        # minimum of the terminal window — 546 (the session tabs) + the panel + the margin ≈ 636,
        # which is BELOW 640 — the saved v1.2.x window geometry (e.g. 640×480) is restored
        # without a clamp to a larger size (checked: body min 96 → the window clamps to 646).
        # By default the panel is wider (sizeHint ≈ 270); 86 — only the lower bound
        # of the QSplitter divider drag.
        self._body = QWidget(self)
        self._body.setMinimumWidth(86)
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(6, 6, 6, 6)
        bl.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel(t("terminal.cmdlib.title"))
        self._title = title   # v1.3.3.1: retranslate() re-texts the panel header
        tf = title.font()
        tf.setBold(True)
        title.setFont(tf)
        self._collapse_btn = QToolButton()
        self._collapse_btn.setIcon(_diamond_icon())
        self._collapse_btn.setToolTip(t("terminal.cmdlib.collapse_tooltip"))
        self._collapse_btn.clicked.connect(lambda: self.set_collapsed(True))
        head.addWidget(title, 1)
        head.addWidget(self._collapse_btn)
        bl.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("terminal.cmdlib.search_placeholder"))
        self.search.textChanged.connect(self._apply_filter)
        bl.addWidget(self.search)

        self.tree = _CommandTree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([t("terminal.cmdlib.name"), t("terminal.cmdlib.command")])
        self.tree.setRootIsDecorated(True)
        # A double click — the mouse path; Enter/Return — entry_entered (see _CommandTree:
        # the native itemActivated is NOT connected — in Qt 6.11 it duplicates the dblclick).
        self.tree.itemDoubleClicked.connect(self._activate_item)
        self.tree.entry_entered.connect(self._activate_item)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        bl.addWidget(self.tree, 1)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        bl.addWidget(self.info_label)

        btns = QHBoxLayout()
        self.add_btn = QPushButton(t("terminal.cmdlib.add"))
        self.edit_btn = QPushButton(t("terminal.cmdlib.edit"))
        self.del_btn = QPushButton(t("terminal.cmdlib.delete"))
        for b in (self.add_btn, self.edit_btn, self.del_btn):
            btns.addWidget(b)
        bl.addLayout(btns)

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.del_btn.clicked.connect(self._on_delete)

        layout.addWidget(self._body)

        # The initial state — from the config (a read without a write-back).
        self.set_collapsed(_load_collapse_state(), persist=False)

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the panel in the current language.

        The tooltips (strip/collapse), the header title, the search placeholder, the
        two tree column headers, the Add/Edit/Delete buttons — plus the tree and the
        info label, which carry translated CATEGORY names ("Uncategorised" for an
        empty category) and the empty/no-matches hint. Every string already has an
        i18n key (ZERO new keys); the module translator is looked up at call time, so
        its cache needs no invalidation. Never raises — the dead-C++-object
        discipline of every container method.
        """
        t = get_translator()
        try:
            self._strip.setToolTip(t("terminal.cmdlib.expand_tooltip"))
            self._title.setText(t("terminal.cmdlib.title"))
            self._collapse_btn.setToolTip(t("terminal.cmdlib.collapse_tooltip"))
            self.search.setPlaceholderText(t("terminal.cmdlib.search_placeholder"))
            self.tree.setHeaderLabels([t("terminal.cmdlib.name"),
                                       t("terminal.cmdlib.command")])
            self.add_btn.setText(t("terminal.cmdlib.add"))
            self.edit_btn.setText(t("terminal.cmdlib.edit"))
            self.del_btn.setText(t("terminal.cmdlib.delete"))
        except RuntimeError:
            return  # the C++ object is already deleted (a close race)
        # The collapse state also owns the two tooltips (set_collapsed re-applies the
        # one that belongs to the current state) — cheap and idempotent.
        try:
            self.set_collapsed(self._collapsed, persist=False)
        except RuntimeError:
            pass  # the C++ object is already deleted (a close race)
        # The tree carries translated category names + the info label carries the
        # empty/no-matches hint — rebuild both in the new language (the same path
        # showEvent uses: a re-read of the store + a rebuild).
        try:
            self.reload()
        except RuntimeError:
            pass  # the C++ object is already deleted (a close race)

    # ── host / data ─────────────────────────────────────────────────────────

    def set_session_tabs(self, tabs):
        """The duck-typed session QTabWidget (the active one = currentWidget())."""
        self.session_tabs = tabs

    def set_active_session_provider(self, provider):
        """v1.3.3.5 (ROADMAP task 6): the container's "what is the active session" callable.

        A container with a SPLIT pane (the terminal window) has more than the tabs and
        owns the focus rule, so it passes `active_session` here; the panel stays
        duck-typed (it never learns about pages/branches — it just asks). `None`
        restores the v1.3 behaviour: the active session is the current TAB.
        """
        self._active_session_provider = provider if callable(provider) else None

    def _active_page(self):
        """The session a macro must go to (the container first, the current tab after)."""
        provider = getattr(self, "_active_session_provider", None)
        if callable(provider):
            try:
                page = provider()
                if page is not None:
                    return page
            except Exception:   # noqa: BLE001 — a container teardown race / a fake
                pass
        tabs = self.session_tabs
        if tabs is None:
            return None
        try:
            return tabs.currentWidget()
        except RuntimeError:
            return None  # the C++ object was already destroyed (a close race)

    def reload(self):
        """Re-read the file and rebuild the tree (showEvent + after changes)."""
        self._entries = self._store.load()
        self._rebuild_tree()

    def showEvent(self, event):
        super().showEvent(event)
        # Two containers may live over one file (window + dock): on show
        # we take the state from the disk. Cheap (a few dozen entries); live synchronization — backlog.
        try:
            self.reload()
        except Exception:   # noqa: BLE001 — show must not crash
            pass

    def _rebuild_tree(self):
        t = get_translator()
        self.tree.clear()
        # IMPORTANT (checked on PySide6 6.11): item.setData(…, UserRole, dict) stores
        # a COPY of the object — each .data() returns a new dict, the mutations do not reach
        # self._entries. So the item stores ONLY the id (a string is copied by
        # value), and the live entry is taken from self._by_id/_entries by id.
        self._by_id = {e["id"]: e for e in self._entries}
        by_cat, order = {}, []
        for e in self._entries:
            cat = e["category"] or t("terminal.cmdlib.category")
            if cat not in by_cat:
                by_cat[cat] = []
                order.append(cat)
            by_cat[cat].append(e)
        muted = QColor(theme.TEXT_MUTED)
        for cat in sorted(order):
            top = QTreeWidgetItem([cat, ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for e in by_cat[cat]:
                child = QTreeWidgetItem([e["name"], e["command"]])
                child.setData(0, Qt.ItemDataRole.UserRole, e["id"])
                if not e.get("enabled", True):
                    child.setForeground(0, muted)   # disabled — muted
                    child.setForeground(1, muted)
                top.addChild(child)
        self.tree.expandAll()
        self._apply_filter()

    def _entry_for_item(self, item):
        """The live entry (from self._by_id) by the id from item.data; None — a category/none."""
        if item is None:
            return None
        eid = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(eid, str):
            return None
        return self._by_id.get(eid)

    def _apply_filter(self):
        """A search by the name OR the command text (case-insensitive); the non-matching
        entries and the categories without matches are hidden. The info label: an empty
        library / no matches."""
        t = get_translator()
        q = self.search.text().strip().lower()
        total_shown = 0
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            shown = 0
            for j in range(top.childCount()):
                child = top.child(j)
                e = self._entry_for_item(child) or {}
                hay = (str(e.get("name", "")) + " " + str(e.get("command", ""))).lower()
                match = not q or q in hay
                child.setHidden(not match)
                if match:
                    shown += 1
            top.setHidden(shown == 0)
            total_shown += shown
        if not self._entries and not q:
            self.info_label.setText(t("terminal.cmdlib.empty"))
        elif total_shown == 0:
            self.info_label.setText(t("terminal.cmdlib.no_matches"))
        else:
            self.info_label.setText("")

    # ── sending the macro to the active session ─────────────────────────────

    def _current_entry(self):
        """The live entry of the current selection (None — a category is selected/nothing)."""
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return None  # the C++ object is already deleted (a close race)
        return self._entry_for_item(item)

    def _activate_item(self, item):
        """A double click / Enter on an entry — send (on a category — a no-op)."""
        entry = self._entry_for_item(item)
        if entry is not None:
            self.send_entry(entry)

    def send_entry(self, entry: dict):
        """Send the command to the ACTIVE session (ROADMAP v1.3).

        The active session — the container's `active_session` if it installed one
        (v1.3.3.5: the terminal window's SPLIT pane, i.e. the pane the user clicked —
        ROADMAP task 6), otherwise `session_tabs.currentWidget()` (the v1.3 rule); the
        send — a dynamic call of page.widget.send_macro(text) (a direct
        terminal_thread.send_data(), NOT the multi-input broadcast). A disabled entry —
        a quiet no-op. No active / a dead session — a status message, no exceptions."""
        t = get_translator()
        if not entry or not entry.get("enabled", True):
            return   # a disabled entry is not sent (muted in the tree)
        page = self._active_page()
        ok = False
        alias = ""
        if page is not None:
            widget = getattr(page, "widget", None)
            fn = getattr(widget, "send_macro", None)
            if callable(fn):
                try:
                    ok = bool(fn(str(entry.get("command", ""))))
                except Exception:   # noqa: BLE001 — a container teardown race
                    ok = False
            try:
                sd = getattr(page, "server_data", None)
                alias = str(getattr(sd, "alias", "") or "")
            except Exception:
                alias = ""
        if ok:
            self.status_message.emit(t("terminal.cmdlib.sent_to", alias=alias), 4000)
        else:
            self.status_message.emit(t("terminal.cmdlib.no_active_session"), 4000)

    # ── CRUD ────────────────────────────────────────────────────────────────

    def _existing_categories(self) -> list:
        return sorted({e["category"] for e in self._entries if e["category"]})

    def _commit(self):
        """Save the state to the disk; on failure — re-read the file (the disk stays
        the source of truth, the local changes are discarded) + a status message."""
        if not self._store.save(self._entries):
            t = get_translator()
            try:
                self.status_message.emit(
                    t("msg.save_failed", error="commands.json"), 8000)
            except RuntimeError:
                pass  # the C++ object is already deleted (a close race)
        self.reload()

    def _on_add(self):
        dlg = CommandLibraryDialog(None, categories=self._existing_categories(),
                                   parent=self.window() or self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.result_entry()
            self._entries.append({
                "id": uuid.uuid4().hex[:12], "name": d["name"],
                "command": d["command"], "category": d["category"],
                "enabled": d["enabled"],
            })
            self._commit()

    def _on_edit(self):
        e = self._current_entry()
        if e is None:
            return
        dlg = CommandLibraryDialog(e, categories=self._existing_categories(),
                                   parent=self.window() or self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.result_entry()
            e.update({"name": d["name"], "command": d["command"],
                      "category": d["category"], "enabled": d["enabled"]})
            self._commit()

    def _edit_entry(self, e):
        """Edit a specific entry (the context menu)."""
        dlg = CommandLibraryDialog(e, categories=self._existing_categories(),
                                   parent=self.window() or self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.result_entry()
            e.update({"name": d["name"], "command": d["command"],
                      "category": d["category"], "enabled": d["enabled"]})
            self._commit()

    def _duplicate_entry(self, e):
        """A duplicate: a new id, the same fields (the name without a suffix — the i18n key
        for "(copy)" is not defined; the user renames it in the dialog if they want)."""
        new = dict(e)
        new["id"] = uuid.uuid4().hex[:12]
        self._entries.append(new)
        self._commit()

    def _toggle_entry(self, e):
        e["enabled"] = not e.get("enabled", True)
        self._commit()

    def _copy_entry(self, e):
        """The command text → the clipboard (quietly; the offscreen clipboard works fine)."""
        try:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(str(e.get("command", "")))
        except Exception:   # noqa: BLE001 — the clipboard is not critical
            pass

    def _delete_entry(self, e):
        """Delete with a confirmation (QMessageBox — a module attribute: a test seam)."""
        t = get_translator()
        box = QMessageBox   # the monkeypatch CL.QMessageBox works in the tests
        reply = box.question(
            self.window() or self,
            t("terminal.cmdlib.delete"),
            t("terminal.cmdlib.confirm_delete", name=e.get("name", "")),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return
        try:
            self._entries.remove(e)
        except ValueError:
            pass  # already removed (a double call)
        self._commit()

    def _on_delete(self):
        e = self._current_entry()
        if e is not None:
            self._delete_entry(e)

    # ── the context menu (test seam: QActions without exec()) ───────────────

    def _on_context_menu(self, pos):
        try:
            item = self.tree.itemAt(pos)
        except RuntimeError:
            return  # the C++ object is already deleted (a close race)
        if item is None:
            return
        menu = self._build_context_menu(item)
        if menu is not None:
            menu.exec(self.tree.mapToGlobal(pos))

    def _build_context_menu(self, item):
        """The entry context menu (on a category — all disabled). A test seam:
        called directly, the tests trigger the QActions without menu.exec()."""
        t = get_translator()
        menu = QMenu(self)
        e = self._entry_for_item(item)   # the live entry by id (item.data stores only the id)
        is_entry = e is not None

        act_edit = menu.addAction(t("terminal.cmdlib.edit"))
        act_dup = menu.addAction(t("terminal.cmdlib.duplicate"))
        act_toggle = menu.addAction(t("terminal.cmdlib.toggle_enabled"))
        act_copy = menu.addAction(t("terminal.cmdlib.copy"))
        act_del = menu.addAction(t("terminal.cmdlib.delete"))
        for a in (act_edit, act_dup, act_toggle, act_copy, act_del):
            a.setEnabled(is_entry)
        if is_entry:
            act_edit.triggered.connect(lambda: self._edit_entry(e))
            act_dup.triggered.connect(lambda: self._duplicate_entry(e))
            act_toggle.triggered.connect(lambda: self._toggle_entry(e))
            act_copy.triggered.connect(lambda: self._copy_entry(e))
            act_del.triggered.connect(lambda: self._delete_entry(e))
        return menu

    # ── collapsing (state — the single key ui_cmdlib_collapsed) ─────────────

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, on: bool, persist: bool = True):
        """Collapse/expand the panel. The state — ONE config key
        ui_cmdlib_collapsed for both containers (an i18n.save_config merge write;
        the terminal_wheel pattern: the config only, not in SettingsDialog.collect()).
        persist=False — a change without a write (the initial application from the config)."""
        self._collapsed = bool(on)
        try:
            t = get_translator()
            # The strip is visible ONLY in the collapsed state (the body — only in the expanded one):
            # both members of one layout, the hidden one takes 0px — native Qt.
            self._strip.setVisible(on)
            self._body.setVisible(not on)
            if on:
                self._strip.setToolTip(t("terminal.cmdlib.expand_tooltip"))
            else:
                self._collapse_btn.setToolTip(t("terminal.cmdlib.collapse_tooltip"))
        except RuntimeError:
            return  # the C++ object is already deleted (a close race)
        if persist:
            _save_config({"ui_cmdlib_collapsed": on})
