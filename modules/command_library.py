# -*- coding: utf-8 -*-
""""Terminal macros" — the command/script library of the terminal panel (DOCUMENTATION.md §14e).
`CommandLibraryStore` owns `~/.sshmap/commands.json` — pure Python, no Qt: an atomic write of the WHOLE
document and deliberately NO merge, because the file belongs to this module alone; the first run seeds
five examples (`seeded: true`) and a corrupt file or a foreign type is a log line plus an EMPTY library.
The library FILE is first-class (ROADMAP v1.8.2): every write rotates the backup ring, a slot is
restored through the shipped backup dialog, the import/export pair carries the WHOLE library and
`add_from_history()` is where the History tab's door lands. `CommandLibraryPanel` is the panel left of
the session tabs in BOTH containers: the search, the "category → command" tree, the Add/Edit/Delete
buttons, the collapse into a thin strip whose state is the ONE key `ui_cmdlib_collapsed`, and a double
click / Enter that sends a macro to the ACTIVE session (`page.widget.send_macro` →
`terminal_thread.send_data()`, never the multi-input broadcast). `CommandLibraryDialog` is the add/edit
dialog; test seams: an explicit `path=` / `store=`, the module attributes `QMessageBox` / `QMenu` / `BackupsDialog`, read at call time."""

import hashlib
import json
import os
import shutil
import uuid

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

try:  # v1.9.8 (task 3): the vector icon set of the header's icon-only buttons
    from ..ui.icons import refresh_button_icon
except ImportError:
    try:
        from ui.icons import refresh_button_icon
    except ImportError:  # a stripped build — the buttons keep their text
        def refresh_button_icon(button, name):  # noqa: N802 — stub with the shipped signature
            return False


try:  # v1.2.5: the central theme (the terminal_page/terminal_dock pattern)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # the ONE atomic-write mechanism (`AGENTS.md` §4.4, `DOCUMENTATION.md` §71)
    from ..storage import atomic as _atomic
except ImportError:  # flat launch from the project root
    from storage import atomic as _atomic

try:  # the SHIPPED backup-list dialog (data in, one restore request out — the project ring's own)
    from ..dialogs.backups_dialog import BackupsDialog
except ImportError:  # flat launch from the project root
    try:
        from dialogs.backups_dialog import BackupsDialog
    except ImportError:  # a build without the dialogs package: the restore reports its refusal
        BackupsDialog = None


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
    """An atomic write of the WHOLE document through `storage/atomic.py` — the ONE mechanism.

    Deliberately NO merge: commands.json belongs entirely to this module — merging foreign keys is
    neither needed nor safe here. False on OSError; a failed write leaves no `*.tmp` behind."""
    return _atomic.write_json_atomic(path, doc)


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
        return entries_from_document(data)

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


def entries_from_document(data) -> list:
    """The entries of a DECODED library document — the ONE normalization of a document. PURE.

    `CommandLibraryStore.load()`, the import reader and the ring's own row builder all go through
    it, so a foreign file can never reach the library through a second, laxer path: a non-dict
    root, a missing / non-list `commands` and an unusable record answer the records that really
    are entries, in document order ([] for a document that carries none).
    """
    if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
        return []
    out = []
    for e in data["commands"]:
        norm = CommandLibraryStore._normalize(e)
        if norm is not None:
            out.append(norm)
    return out


# ── the library FILE: the backup ring and the import/export pair (ROADMAP v1.8.2) ────────────
# `~/.sshmap/commands.json` is a user file like the project file, so it gets the project file's ring
# (`storage/autosave.py` is the pattern: slot 1 is the version the last write replaced, every older
# slot moves +1, the overflow is deleted) plus the import/export pair the language files have. The
# mechanism is `DOCUMENTATION.md` §14e; the ring's arithmetic is the project's own, deliberately.

#: The ring's folder, beside the project's own (`~/.sshmap/backups/`).
COMMANDS_BACKUP_DIR = os.path.join(os.path.expanduser("~"), ".sshmap", "command_backups")

#: The DECLARED bound of the ring. Not a config key: the project's `backup_count` sizes the PROJECT
#: ring, and this file must not silently borrow a number that describes another file.
COMMANDS_BACKUP_COUNT = 10
COMMANDS_BACKUPS_MIN = 1
COMMANDS_BACKUPS_MAX = 100

#: The longest NAME the History door pre-fills out of a row (the first line of its command).
SUGGESTED_NAME_MAX = 60

#: How wide the panel's Name column may grow when it is measured from the content (v1.9.8): a very
#: long name is the tooltip's job, not a column that pushes the command off the panel.
CMDLIB_NAME_COLUMN_MAX = 280

#: The machine reasons of `read_library_file()` / `export_library_file()` — data, never a UI string
#: (the language pair's shape: the caller renders them in its own language).
LIB_ERR_UNREADABLE = "unreadable"
LIB_ERR_JSON = "not_json"
LIB_ERR_OBJECT = "not_object"
LIB_ERR_EMPTY = "no_commands"
LIB_ERR_WRITE = "write_failed"


def library_key(path) -> str:
    """Stable key of a library file: `sha1[:16]` of the normalized absolute path (the project ring)."""
    norm = os.path.normcase(os.path.abspath(str(path)))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def library_backup_path(path, slot) -> str:
    """The path of ONE ring slot of a library file; slot 1 is the newest."""
    return os.path.join(COMMANDS_BACKUP_DIR, f"{library_key(path)}_{int(slot):03d}.json")


def _atomic_copy(src: str, dst: str) -> None:
    """An atomic file copy through the ONE mechanism; a failed copy leaves no `*.tmp` behind."""
    _atomic.publish_atomic(dst, lambda temp: shutil.copy2(src, temp))


def rotate_library_backups(path, count: int = COMMANDS_BACKUP_COUNT) -> list:
    """Shift the ring and put the CURRENT file into slot 1 — taken BEFORE a library write.

    The project ring's arithmetic (`storage/autosave.rotate_backups`): the slots receive the version
    the write is about to replace, and the leftovers beyond `count` are deleted. A missing file (the
    very first write) rotates nothing. Never raises: the ring is a safety net, so a read-only HOME
    must not stop the library from being saved.
    """
    try:
        if not os.path.isfile(path):
            return []
        count = _backup_count(count)
        for slot in range(count, 1, -1):
            src = library_backup_path(path, slot - 1)
            if os.path.isfile(src):
                _atomic_copy(src, library_backup_path(path, slot))
        for slot in range(count + 1, COMMANDS_BACKUPS_MAX + 1):
            extra = library_backup_path(path, slot)
            if os.path.isfile(extra):
                try:
                    os.remove(extra)
                except OSError:
                    pass
        _atomic_copy(path, library_backup_path(path, 1))
        return list_library_backups(path, count)
    except (OSError, TypeError, ValueError):
        return []


def _backup_count(count) -> int:
    """A usable ring size: the declared default for a foreign value, clamped to the bounds."""
    try:
        value = int(count)
    except (TypeError, ValueError):
        value = COMMANDS_BACKUP_COUNT
    return max(COMMANDS_BACKUPS_MIN, min(value, COMMANDS_BACKUPS_MAX))


def list_library_backups(path, count: int = COMMANDS_BACKUP_COUNT) -> list:
    """The ring slots that exist, newest first: `[{path, slot, mtime, size}, …]`."""
    items = []
    for slot in range(1, _backup_count(count) + 1):
        slot_path = library_backup_path(path, slot)
        if not os.path.isfile(slot_path):
            continue
        try:
            st = os.stat(slot_path)
        except OSError:
            continue
        items.append({"path": slot_path, "slot": slot, "mtime": st.st_mtime, "size": st.st_size})
    return items


def read_library_bytes(source_path) -> bytes:
    """The RAW bytes of ONE ring slot — read BEFORE the ring rotates (RAISES; the caller owns the sentence).

    A restore publishes what the user SAW in the dialog, so the slot is read as bytes: a document that
    was re-serialized on the way back is not the file the row named (its formatting, its key order and
    any record the current normalization would drop belong to the SLOT). The read has to happen before
    `rotate_library_backups()`: that call shifts `i → i+1` and rewrites slot 1, so the picked path holds
    its NEIGHBOUR's content afterwards — and a picked OLDEST slot would be overwritten before it was read.
    """
    with open(source_path, "rb") as fh:
        return fh.read()


def _write_library_bytes(path, payload: bytes) -> None:
    """The `write_temp` of a restore: the slot's own bytes, nothing re-serialized."""
    with open(path, "wb") as fh:
        fh.write(payload)


def restore_library_payload(payload: bytes, path) -> None:
    """Publish a slot's PAYLOAD over the library file — the ONE writer of a restore (RAISES).

    Through the ONE atomic writer (`AGENTS.md` §4.4), so a reader sees the whole document or the
    previous one; the caller owns the sentence a failure produces.
    """
    _atomic.publish_atomic(path, lambda temp: _write_library_bytes(temp, payload))


def restore_library_backup(source_path, path) -> None:
    """Copy one ring slot over the library file ATOMICALLY; RAISES (the caller owns the sentence)."""
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Command library backup not found: {source_path}")
    restore_library_payload(read_library_bytes(source_path), path)


def suggested_name(command) -> str:
    """The NAME the History door pre-fills — the FIRST line of the command, capped. PURE.

    A history row is a command, not a name: its first line is what a user recognizes in the tree,
    and the cap keeps a 4 KB one-liner out of the name field. A non-string / an empty text answers "".
    """
    if not isinstance(command, str):
        return ""
    for line in command.splitlines():
        if line.strip():
            return line.strip()[:SUGGESTED_NAME_MAX].strip()
    return ""


def read_library_file(source_path) -> dict:
    """Validate ONE library file → `{"ok", "error", "path", "count", "entries"}`. Never raises.

    The language pair's shape (`i18n.import_language_file`): validate FIRST, hand the caller the data
    after — a file that fails any check never reaches the library. The accepted document is the
    store's OWN (`{"seeded": true, "commands": […]}`), so an exported library imports back unchanged,
    and a document without ONE usable command is refused rather than applied as an empty library.
    """
    result = {"ok": False, "error": LIB_ERR_UNREADABLE, "path": "", "count": 0, "entries": []}
    try:
        source = os.path.abspath(os.path.expanduser(str(source_path or "")))
    except (TypeError, ValueError):
        return result
    if not source or not os.path.isfile(source):
        return result
    try:
        with open(source, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except ValueError:   # json.JSONDecodeError / UnicodeDecodeError are ValueErrors
        result["error"] = LIB_ERR_JSON
        return result
    except OSError:
        return result
    if not isinstance(data, dict):
        result["error"] = LIB_ERR_OBJECT
        return result
    entries = entries_from_document(data)
    if not entries:
        result["error"] = LIB_ERR_EMPTY
        return result
    result.update({"ok": True, "error": "", "path": source,
                   "count": len(entries), "entries": entries})
    return result


def export_library_file(destination_path, entries) -> dict:
    """Write the WHOLE library to `destination_path` ATOMICALLY → `{"ok", "error", "path", "count"}`.

    The store's own document is written, so an exported file imports back unchanged AND could be
    dropped in as `commands.json` itself. A library carries no passwords by construction (§4.4), so
    nothing is stripped here. Never raises.
    """
    result = {"ok": False, "error": LIB_ERR_WRITE, "path": "", "count": 0}
    try:
        destination = os.path.abspath(os.path.expanduser(str(destination_path or "")))
    except (TypeError, ValueError):
        return result
    if not destination:
        return result
    doc = {"seeded": True, "commands": [dict(c) for c in (entries or [])]}
    if not _atomic_write_json(destination, doc):
        return result
    result.update({"ok": True, "error": "", "path": destination,
                   "count": len(doc["commands"])})
    return result


# ── collapsing: a local copy of v1.2.4.1 (no ui.main_window import) ──────────────

def _diamond_icon(size: int = 20):
    """A vector "◇" diamond on a size×size canvas (the panel collapse button).

    A local copy of the ui/main_window._diamond_icon() technique :
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


def hand_over_splitter_width(splitter, index: int, want: int) -> bool:
    """Give member `index` the width `want` and hand the delta to the OTHER members.

    v1.5rc5 (N8) wrote this arithmetic for the collapsed command panel; v1.7.1 makes it the
    ONE arithmetic of a collapsible SIDE PANEL, because the terminal window has two of them
    (the command library on the left, the Files tree of `modules/ssh_terminal.py` on the
    right) and a collapsed member may not simply be left at its old size: visibility and the
    `setMaximumWidth` cap alone left the freed pixels dead, so the panel's neighbours never
    received them (measured: 365 px in the dock).

    The shares of the other members are kept in PROPORTION, so a three-member splitter
    (`[commands | terminal | files]`) hands the delta to the two columns that are really
    there instead of dropping it into the member the caller never named — `setSizes()` with a
    SHORT list zeroes the members it does not mention (measured on Qt 6.11: `setSizes([24, 500])`
    on a three-member splitter gives `[41, 851, 0]`), which is exactly the bug a mirrored copy
    of the two-member arithmetic would have shipped. Returns True when a `setSizes()` call was
    made — False for a member that is not in the splitter / a splitter that is not laid out.
    Never raises: every Qt call is guarded (the caller may be under teardown).
    """
    try:
        count = int(splitter.count())
        sizes = list(splitter.sizes())
    except (RuntimeError, AttributeError, TypeError):
        return False
    if count < 2 or len(sizes) != count or not (0 <= index < count):
        return False
    others = [i for i in range(count) if i != index]
    if not others:
        return False
    wanted = max(0, int(want))
    rest_total = max(sum(sizes) - wanted, 0)
    rest_now = sum(max(0, sizes[i]) for i in others)
    new = [0] * count
    new[index] = wanted
    for i in others:
        share = (rest_total * max(0, sizes[i]) / rest_now) if rest_now > 0 \
            else rest_total / len(others)
        new[i] = int(share)
    # The rounding of the proportional shares may leave a few pixels unassigned — they go to
    # the LAST other member, so the caller's `want` is exact and no column silently shrinks.
    new[others[-1]] += max(0, sum(sizes) - sum(new))
    try:
        splitter.setSizes(new)
    except RuntimeError:
        return False   # Qt teardown — the splitter is already destroyed
    return True


# The upper bound of a QWidget's width. QWIDGETSIZE_MAX is a C macro in qwidget.h and is
# therefore not exposed by PySide6 — the documented value (`ui/main_window._WIDGET_MAX_WIDTH`,
# duplicated here because `modules/*` must not import `ui/main_window`; the same reason the
# "◇" diamond and the collapse strip are local).
_WIDGET_MAX_WIDTH = 16777215

#: The documented lower bound of the splitter divider next to an EXPANDED panel — the width
#: the body takes back when the collapsed strip is released (v1.7.1: named, because the Files
#: panel of the terminal window mirrors this bound and the two must not drift).
PANEL_BODY_MIN_WIDTH = 86


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

    The MODE is the ID: an `entry` that carries one is the stored record being edited (the title
    says so), while an `entry` WITHOUT one is a NEW record whose fields are PRE-FILLED — the form the
    History tab's door opens (`add_from_history()`), and `entry=None` is the empty add form.
    The category — an editable QComboBox with the existing categories
    (new ones are typed freely). OK is blocked until the name AND the command are non-empty
    (a double guard: the disabled button + the check in _on_accept). The command is NOT
    stripped at the edges (the trailing line breaks matter — build_macro_payload
    normalizes them on send)."""

    def __init__(self, entry: dict = None, categories: list = None, parent=None):
        super().__init__(parent)
        t = get_translator()
        editing = bool(entry) and bool(entry.get("id"))
        self.setWindowTitle(t("terminal.cmdlib.edit") if editing else t("terminal.cmdlib.add"))
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
    v1.5rc5 (N8): the collapse also applies the §36 WIDTH CAP to this splitter member and
    hands the freed space to the other one — visibility alone left the panel wide, so the
    terminal never received it (see `_apply_splitter_width`).

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
        self._expanded_width = 0           # v1.5rc5 (N8): the width to come back to on expand

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The collapsed state: the thin strip (a click anywhere — expand).
        self._strip = _CollapseStrip(self)
        self._strip.expand_requested.connect(lambda: self.set_collapsed(False))
        self._strip.setToolTip(t("terminal.cmdlib.expand_tooltip"))
        layout.addWidget(self._strip)

        # The expanded body. The minimum width is 86 (not a "convenient" 180): the total minimum of the
        # terminal window — 546 (the session tabs) + the panel + the margin ≈ 636 — stays BELOW 640, so the
        # saved v1.2.x window geometry (e.g. 640×480) is restored without a clamp to a larger size (checked:
        # a body min of 96 clamps the window to 646). By default the panel is wider (`sizeHint` ≈ 270);
        # 86 is only the lower bound of the QSplitter divider drag.
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
        # v1.8.2: the library FILE — the ring's restore and the import/export pair. ONE QToolButton
        # with a QMenu whose actions are built ONCE here and re-texted by retranslate(); the menu and
        # the actions stay on the panel, because a dying Python QAction wrapper destroys its QMenu
        # (Qt gotcha #9). The button's own label is a glyph — nothing to translate.
        self._file_btn = QToolButton()
        # v1.9.8 (task 3): the icon-only buttons of this header carry a GLYPH and a tooltip — the
        # shipped "…" was a text character no icon walk could re-theme.
        refresh_button_icon(self._file_btn, "menu_dots")
        self._file_btn.setToolTip(t("terminal.cmdlib.file_menu_tooltip"))
        self._file_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._file_menu = QMenu(self._file_btn)
        self.act_restore_backup = self._file_menu.addAction(t("terminal.cmdlib.restore_backup"))
        self.act_import_library = self._file_menu.addAction(t("terminal.cmdlib.import"))
        self.act_export_library = self._file_menu.addAction(t("terminal.cmdlib.export"))
        self.act_restore_backup.triggered.connect(self.restore_backup)
        self.act_import_library.triggered.connect(self.import_library)
        self.act_export_library.triggered.connect(self.export_library)
        self._file_btn.setMenu(self._file_menu)
        head.addWidget(self._file_btn)
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
        # The POLICY is what makes the signal exist: with the default `Qt.DefaultContextMenu`
        # the right click is a contextMenuEvent this widget ignores, so it travels up to the
        # container — which is why the documented "right-click the library" gesture does
        # nothing here (and answered "Split Terminal" in the terminal window).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to the panel.

        The info label's colour is re-read (a QSS string is a value) and the two
        hand-painted widgets — the collapse strip and the collapse button — are
        repainted, because their colours are read inside `paintEvent`. Never
        raises: the container may be closing under the switch.
        """
        try:
            self.info_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        except RuntimeError:
            return  # Qt teardown — the label is already destroyed
        for widget in (getattr(self, "_strip", None), getattr(self, "_collapse_btn", None)):
            if widget is None:
                continue
            try:
                widget.update()
            except RuntimeError:
                continue
        # v1.9.8 (task 3): the header's two painted ICONS follow the theme too — a pixmap is a
        # value, so the tone has to be re-applied, not only the widget repainted.
        try:
            self._collapse_btn.setIcon(QIcon())
            self._collapse_btn.setIcon(_diamond_icon())
            refresh_button_icon(self._file_btn, "menu_dots")
        except RuntimeError:
            pass  # Qt teardown — the buttons are already destroyed

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
            self._file_btn.setToolTip(t("terminal.cmdlib.file_menu_tooltip"))
            self.act_restore_backup.setText(t("terminal.cmdlib.restore_backup"))
            self.act_import_library.setText(t("terminal.cmdlib.import"))
            self.act_export_library.setText(t("terminal.cmdlib.export"))
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

    def event(self, event):
        """v1.5rc5 (N8): (re-)apply the collapsed width when the panel joins its splitter.

        The panel is CONSTRUCTED before the container puts it into the QSplitter, so the
        state applied from the config at construction cannot touch the splitter — the
        ParentChange event is the moment the host exists, and it arrives before the
        splitter is shown, i.e. before the first layout pass.
        """
        if event.type() == QEvent.Type.ParentChange:
            try:
                if self._collapsed:
                    self._apply_splitter_width(True)
            except RuntimeError:
                pass  # Qt teardown
        return super().event(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Two containers may live over one file (window + dock): on show
        # we take the state from the disk. Cheap (a few dozen entries); live synchronization — backlog.
        try:
            self.reload()
        except Exception:   # noqa: BLE001 — show must not crash
            pass
        # v1.5rc5 (N8): the splitter is laid out by now — hand the freed space over
        # explicitly, so a panel restored from the config as collapsed is already 24 px.
        self._apply_splitter_width(self._collapsed)

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
                # v1.9.8 (task 3): the row's FULL text travels as its tooltip — an elided name was
                # unreadable without opening Edit (the command is the second half of the same fact).
                child.setToolTip(0, str(e["name"]))
                child.setToolTip(1, str(e["command"]))
                if not e.get("enabled", True):
                    child.setForeground(0, muted)   # disabled — muted
                    child.setForeground(1, muted)
                top.addChild(child)
        self.tree.expandAll()
        self._fit_name_column()
        self._apply_filter()

    def _fit_name_column(self):
        """Size the Name column from the CONTENT (the shipped seed needs 120–288 px).

        The literal 100 px this replaces elided every one of the five seeded commands; the cap
        keeps a very long name from pushing the command column off the panel, and the second
        column keeps the rest of the width. Never raises.
        """
        try:
            self.tree.resizeColumnToContents(0)
            if int(self.tree.columnWidth(0)) > CMDLIB_NAME_COLUMN_MAX:
                self.tree.setColumnWidth(0, CMDLIB_NAME_COLUMN_MAX)
        except RuntimeError:
            pass  # Qt teardown — the tree is already destroyed

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

    def _commit(self) -> bool:
        """Rotate the ring, then save; False — re-read the file (the disk stays the source of truth).

        The ORDER is the project's (`MainWindow._do_save()`): the version the write is about to
        replace goes into slot 1 BEFORE the write, so every library change — an edit, a delete or
        the import of a whole file — is one restore away.
        """
        rotate_library_backups(self._store.path)
        if not self._store.save(self._entries):
            t = get_translator()
            try:
                self.status_message.emit(
                    t("msg.save_failed", error="commands.json"), 8000)
            except RuntimeError:
                pass  # the C++ object is already deleted (a close race)
            self.reload()
            return False
        self.reload()
        return True

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

    # ── the library FILE: the door's landing, the ring and the import/export pair (v1.8.2) ──

    def add_from_history(self, command: str, name: str = "") -> bool:
        """The History tab's door lands HERE: the SHIPPED add form, PRE-FILLED, written by this panel.

        The write stays here — the store rewrites the whole document, so a second writer beside the
        panel IS the `N51` race. The door hands in an ID-LESS entry, which `CommandLibraryDialog`
        reads as "a NEW record, pre-filled" (the command and a name — a history row carries no name,
        so `suggested_name()` takes the first line of the command); the CATEGORY stays a choice the
        shipped form makes.
        """
        t = get_translator()
        if not isinstance(command, str) or not command.strip():
            return False
        dlg = CommandLibraryDialog(
            {"name": (name or "").strip() or suggested_name(command),
             "command": command, "category": "", "enabled": True},
            categories=self._existing_categories(), parent=self.window() or self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        d = dlg.result_entry()
        self._entries.append({
            "id": uuid.uuid4().hex[:12], "name": d["name"],
            "command": d["command"], "category": d["category"],
            "enabled": d["enabled"],
        })
        ok = self._commit()
        if ok:
            try:
                self.status_message.emit(t("terminal.cmdlib.saved", name=d["name"]), 4000)
            except RuntimeError:
                pass  # the C++ object is already deleted (a close race)
        return ok

    def backup_items(self) -> list:
        """The rows of the restore dialog: the ring slots that really PARSE, newest first.

        A corrupt slot is not a rescue (the project's `_unreadable_sources()` rule), so it is not
        offered; the label is the shipped `backups.backup` one the project's own dialog uses.
        """
        t = get_translator()
        items = []
        for slot in list_library_backups(self._store.path):
            if not read_library_file(slot["path"])["ok"]:
                continue
            items.append({"label": t("backups.backup", n=slot["slot"]),
                          "path": slot["path"], "mtime": slot["mtime"],
                          "size": slot["size"]})
        return items

    def restore_backup(self) -> bool:
        """Offer the ring and copy the chosen slot over the library — the ONE explicit ask.

        The ORDER is the whole mechanism: the chosen slot's bytes are read FIRST, then the ring
        rotates, then those bytes are published. `rotate_library_backups()` shifts `i → i+1` and
        rewrites slot 1 with the CURRENT file, so a path read AFTER the rotation answers the slot's
        NEIGHBOUR — and a picked oldest slot is overwritten by the shift before it is read at all,
        which loses it. The state being replaced then goes into slot 1, so a restore is itself
        reversible. The dialog and its "Restore" button ARE the confirmation (the row names the slot).
        """
        t = get_translator()
        items = self.backup_items()
        if not items:
            self.status_message.emit(t("terminal.cmdlib.backup_empty"), 6000)
            return False
        if BackupsDialog is None:
            return False
        chosen = {}
        dlg = BackupsDialog(items, parent=self.window() or self,
                            title=t("terminal.cmdlib.restore_backup"))

        def _take(source, label):
            chosen["path"], chosen["label"] = str(source), str(label)
            dlg.accept()   # the click IS the decision — the dialog closes on it

        dlg.restore_requested.connect(_take)
        dlg.exec()
        if not chosen:
            return False
        try:
            payload = read_library_bytes(chosen["path"])
        except OSError as e:
            self.status_message.emit(
                t("terminal.cmdlib.restore_failed", error=str(e)), 8000)
            return False
        rotate_library_backups(self._store.path)
        try:
            restore_library_payload(payload, self._store.path)
        except OSError as e:
            self.status_message.emit(
                t("terminal.cmdlib.restore_failed", error=str(e)), 8000)
            return False
        self.reload()
        self.status_message.emit(
            t("terminal.cmdlib.restored", source=chosen["label"]), 5000)
        return True

    def import_library(self, path: str = None) -> bool:
        """Replace THIS library with a foreign file — AFTER the user confirmed the replacement.

        An export is a copy of the WHOLE library, so the pair round-trips; a merge-by-name is a
        decision of its own and is deliberately NOT taken here. The write goes through `_commit()`,
        so the library being replaced is rotated into the ring first.
        """
        t = get_translator()
        if not path:
            try:
                path, _selected = QFileDialog.getOpenFileName(
                    self.window() or self, t("terminal.cmdlib.import"), "",
                    "JSON (*.json);;All files (*)")
            except Exception:   # noqa: BLE001 — a Qt teardown race
                return False
        if not path:
            return False
        result = read_library_file(path)
        if not result["ok"]:
            self.status_message.emit(
                t("terminal.cmdlib.import_failed", error=result["error"]), 8000)
            return False
        box = QMessageBox   # the monkeypatch CL.QMessageBox works in the tests
        reply = box.question(
            self.window() or self, t("terminal.cmdlib.import"),
            t("terminal.cmdlib.import_confirm", count=result["count"]),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return False
        self._entries = [dict(e) for e in result["entries"]]
        if not self._commit():
            return False
        self.status_message.emit(t("terminal.cmdlib.imported", count=result["count"]), 6000)
        return True

    def export_library(self, path: str = None) -> bool:
        """Write the WHOLE library to a file the user picks (one atomic copy, no secrets in it)."""
        t = get_translator()
        if not path:
            try:
                path, _selected = QFileDialog.getSaveFileName(
                    self.window() or self, t("terminal.cmdlib.export"), "commands.json",
                    "JSON (*.json);;All files (*)")
            except Exception:   # noqa: BLE001 — a Qt teardown race
                return False
        if not path:
            return False
        path = str(path)
        if not path.lower().endswith(".json"):
            path += ".json"
        result = export_library_file(path, self._entries)
        if not result["ok"]:
            self.status_message.emit(
                t("terminal.cmdlib.export_failed", error=result["error"]), 8000)
            return False
        self.status_message.emit(t("terminal.cmdlib.exported", path=result["path"]), 6000)
        return True

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
        persist=False — a change without a write (the initial application from the config).

        v1.5rc5 (N8): the collapse also HANDS THE FREED SPACE OVER. Visibility alone left
        the splitter member at its old width, so the terminal never received the freed area
        (measured: 365 px dead in the dock). The §36 idiom is applied here — the width cap
        while collapsed, released on expand — which both containers inherit from this ONE
        class. The cap lives ONLY while collapsed (Qt gotcha #13: a permanent maximum on a
        splitter member breaks the size accounting after a hide/show cycle).
        """
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
        self._apply_splitter_width(bool(on))
        if persist:
            _save_config({"ui_cmdlib_collapsed": on})

    def _host_splitter(self):
        """The QSplitter this panel is a member of (its parent after `addWidget`)."""
        try:
            parent = self.parentWidget()
        except RuntimeError:
            return None
        return parent if isinstance(parent, QSplitter) else None

    def _apply_splitter_width(self, collapsed: bool):
        """v1.5rc5 (N8): the §36 width cap + the explicit hand-over of the freed space.

        Collapsed — the panel is capped to the strip and the OTHER member receives the
        delta; expanded — the cap is released and the width remembered before the collapse
        is restored. The hand-over itself is the SHARED `hand_over_splitter_width()` (v1.7.1:
        the terminal window's Files panel is the second collapsible side panel, and a
        three-member splitter `[commands | terminal | files]` must not lose the delta into a
        member the old two-member arithmetic never named). Every Qt call is guarded: the panel
        may already be under teardown.
        """
        splitter = self._host_splitter()
        if splitter is None:
            return
        try:
            sizes = list(splitter.sizes())
            index = splitter.indexOf(self)
            laid_out = index >= 0 and len(sizes) >= 2 and sum(sizes) > 0
            if collapsed:
                # Remember the width to come back to, then hand it over. The hidden body's
                # own 86 px minimum would fight the cap, so it is capped too.
                if laid_out and sizes[index] > _CollapseStrip.STRIP_WIDTH:
                    self._expanded_width = sizes[index]
                self._body.setMinimumWidth(0)
                self.setMaximumWidth(_CollapseStrip.STRIP_WIDTH)
                self.setMinimumWidth(_CollapseStrip.STRIP_WIDTH)
                if laid_out:
                    hand_over_splitter_width(splitter, index, _CollapseStrip.STRIP_WIDTH)
            else:
                self.setMaximumWidth(_WIDGET_MAX_WIDTH)
                self.setMinimumWidth(0)
                self._body.setMinimumWidth(PANEL_BODY_MIN_WIDTH)   # the divider's lower bound
                if laid_out:
                    want = int(getattr(self, "_expanded_width", 0) or 0)
                    if want <= 0:
                        want = max(self.sizeHint().width(), PANEL_BODY_MIN_WIDTH)
                    want = min(want, max(sum(sizes) - 1, _CollapseStrip.STRIP_WIDTH))
                    hand_over_splitter_width(splitter, index, want)
        except RuntimeError:
            pass  # Qt teardown — the splitter is already destroyed
