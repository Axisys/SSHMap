# -*- coding: utf-8 -*-
"""v1.5.7 (ROADMAP v1.5.7): the COMMAND history — the terminal's third tab, one history per server.

The session grows a **History** tab after `Terminal` and `Files`: the commands of THIS server,
kept between sessions. The module has the `modules/command_library.py` shape — store + panel +
pure functions, no import of the window — and is composed of three parts:

  * **the PURE parser** — `parse_history_text(text)` (no Qt, no I/O): the text of a history file
    in, the entries + a report out. The rules are DECLARED, not guessed: bash (one command per
    line, plus the `HISTTIMEFORMAT` markers `#<epoch>` whose timestamp belongs to the commands
    that FOLLOW them), zsh extended (`: <epoch>:<duration>;<command>`) and the empty lines
    dropped. The identity of an entry is the command text after `strip()` ONLY — no case folding
    and no inner-whitespace collapsing (that would silently corrupt commands: `grep  a` is not
    `grep a`). A duplicate keeps the LATEST timestamp and counts its repeats.
  * **`CommandHistoryStore`** — `~/.sshmap/history/<key>.json`, ONE file per server, keyed by
    `ServerData.id` (the same identity the keyring uses, so a renamed alias or a changed host
    keeps its history). A write RE-READS AND MERGES the document, it never overwrites it from
    memory: two sessions of one node (a tab and a split pane) share the file. A corrupt file is a
    log line + an empty history — user data is never re-seeded and a read never writes.
  * **`CommandHistoryPanel`** — the tab: the filter, the three-column tree (command / last used /
    count) and the counts line, the right-click menu (import a local file, import the server's
    `~/.bash_history` over the session's SFTP channel, copy, send to the terminal, merge the
    duplicates, clear).

**Naming (do not skip it).** In this codebase the word "history" already means the pyte
SCROLLBACK (`TerminalScreen.history`, `terminal_history_lines`). The owner of THIS module is the
COMMAND history and is therefore `command_history` / `cmd_history` everywhere; the existing keys
and constants are not renamed (i18n is additive only).

**What is recorded, and what is deliberately NOT.** The application records exactly what IT sent
(the macro library, quick launch, the "Send to terminal" of this tab — the ONE `send_macro()`
path, plus the server import, which is a read). **Nothing is inferred from the typed input**: the
canvas sees raw bytes and keys, not the shell's line editing (arrows, backspace, Tab completion,
`Ctrl+R`), so a reconstruction of a typed command would be a guess. That is a documented
non-goal, not a bug.

**Security.** `~/.sshmap/history/*.json` is a plain-text file and its entries may carry secrets
(a token or a password passed as an argument of a command). It is never logged, never written
into the project file and never exported.
"""

import hashlib
import json
import os
import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QLineEdit, QMenu, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:  # the central theme (the terminal_page / command_library pattern)
    from ..ui import theme
except ImportError:
    from ui import theme


# ── i18n (the cached-translator pattern of modules/ssh_terminal.py) ─────────

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
    """The app logger (lazy, the command_library._log pattern)."""
    try:
        from modules.logger import get_logger as _gl
        return _gl("modules.command_history")
    except Exception:
        return None


def _format_size(n) -> str:
    """The human size (the `modules/sftp_tab.format_size` of the SFTP family), lazily imported.

    The panel names the worker's own read cap in its refusal message, so it shows the SAME
    number in the SAME form as the Files tab — one formatting rule for both surfaces.
    """
    try:
        from .sftp_tab import format_size
    except ImportError:
        from sftp_tab import format_size
    return format_size(n)


# ── the two DECLARED caps (no config key, no settings tab) ──────────────────

#: A longer entry is SKIPPED (at import — and counted in its report; at record — quietly
#: ignored, because a 4 KB "command" is a script, not a line a user re-runs). The full text of a
#: stored entry is NEVER silently truncated: the table elides for display and keeps the whole
#: string in its tooltip.
MAX_CMD_CHARS = 4096

#: The FIFO eviction cap of ONE server's file (the bounded-ring precedent of
#: `modules/activity_log.py`): a big import cannot put tens of thousands of rows into a
#: `QTreeWidget`. The entry that leaves is the one used longest ago.
MAX_ENTRIES_PER_SERVER = 2000

#: The document format of one history file.
FORMAT_VERSION = 1

#: The file imported by "Import from the server…" — the ONE path of this version. The `~/`
#: prefix is expanded ON THE WORKER THREAD (`SftpWorker._expand_home`), because the SFTP
#: protocol has no tilde expansion of its own.
SERVER_HISTORY_PATH = "~/.bash_history"


# ── the pure parser ─────────────────────────────────────────────────────────

#: zsh extended history: `: <epoch>:<duration>;<command>`.
_ZSH_EXTENDED_RE = re.compile(r"^:\s*(\d+):(\d+);(.*)$", re.S)

#: the bash HISTTIMEFORMAT marker: a line that is EXACTLY `#` + digits. Any other `#` line is a
#: command (a shell comment is a command line in a history file, and `#123` is not a marker).
_BASH_TS_RE = re.compile(r"^#(\d+)$")


def parse_history_text(text):
    """The text of a history file → `(entries, report)`. A pure function, no Qt, no I/O.

    Entries are `{"cmd", "last", "count"}` in the FILE order of their first appearance; the
    caller sorts them for display. The report carries four counters — `parsed` (distinct
    commands), `merged` (accepted lines folded onto a command already seen), `skipped_long`
    (over `MAX_CMD_CHARS`) and `skipped_empty` (blank lines and a zsh record without a command);
    the four together account for every line that is not a timestamp marker.

    A timestamp marker belongs to the commands that FOLLOW it (bash), exactly as
    `HISTTIMEFORMAT` stores it; a zsh record carries its own. Without any timestamp an entry
    keeps `last = 0` — "not dated" is a truthful value, never a made-up `now`.
    """
    report = {"parsed": 0, "merged": 0, "skipped_long": 0, "skipped_empty": 0}
    entries = []
    by_cmd = {}
    current_ts = 0
    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            report["skipped_empty"] += 1
            continue
        marker = _BASH_TS_RE.match(line.strip())
        if marker is not None:
            current_ts = int(marker.group(1))
            continue
        ts = current_ts
        extended = _ZSH_EXTENDED_RE.match(line)
        if extended is not None:
            ts = int(extended.group(1))
            line = extended.group(3)
        cmd = line.strip()
        if not cmd:
            report["skipped_empty"] += 1
            continue
        if len(cmd) > MAX_CMD_CHARS:
            report["skipped_long"] += 1
            continue
        entry = by_cmd.get(cmd)
        if entry is None:
            entry = {"cmd": cmd, "last": int(ts), "count": 1}
            by_cmd[cmd] = entry
            entries.append(entry)
            report["parsed"] += 1
        else:
            entry["last"] = max(entry["last"], int(ts))
            entry["count"] += 1
            report["merged"] += 1
    return entries, report


def normalize_entry(entry):
    """One stored record → `{"cmd", "last", "count"}` or None (an invalid record is dropped).

    The identity is the command text after `strip()` — the ONE normalization of this module. A
    record without a command, with a non-string command or with a command over the cap is
    unusable and is dropped one by one, like a broken `commands.json` entry.
    """
    if not isinstance(entry, dict):
        return None
    cmd = entry.get("cmd")
    if not isinstance(cmd, str):
        return None
    cmd = cmd.strip()
    if not cmd or len(cmd) > MAX_CMD_CHARS:
        return None
    try:
        last = int(entry.get("last") or 0)
    except (TypeError, ValueError):
        last = 0
    try:
        count = int(entry.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    return {"cmd": cmd, "last": max(0, last), "count": max(1, count)}


def sort_entries(entries):
    """The STORED order of a history: the most recently used first (stable, capped).

    A stable sort on `last` alone, so the entries that share a timestamp (a plain bash file
    without markers — every one of them is undated) keep the order they were read in.
    """
    out = sorted(entries, key=lambda e: -int(e.get("last") or 0))
    return out[:MAX_ENTRIES_PER_SERVER]


def merge_entries(base, incoming):
    """Two entry lists → ONE, newest-first, duplicates folded. A pure function.

    The ONE merge rule of the module, used by both write paths: the same command keeps the
    latest timestamp and the SUM of its repeats. The result is capped (FIFO eviction by the
    least recently used).
    """
    out, by_cmd = [], {}
    for entry in list(base or []) + list(incoming or []):
        norm = normalize_entry(entry)
        if norm is None:
            continue
        current = by_cmd.get(norm["cmd"])
        if current is None:
            copy = dict(norm)
            by_cmd[norm["cmd"]] = copy
            out.append(copy)
        else:
            current["last"] = max(int(current["last"]), norm["last"])
            current["count"] = int(current["count"]) + norm["count"]
    return sort_entries(out)


def dedup_entries(entries):
    """Collapse the duplicates of an entry list → `(entries, removed_count)`. A pure function.

    The store already merges on every write, so this exists for a hand-edited file (or one
    written by another tool): "Remove duplicates" of the context menu is exactly this function
    plus a write.

    The REPORTED count is the number of entries that were really FOLDED into another one
    (`normalize_entry()`'s identity is the command text); the per-server CAP of
    `sort_entries()` — a truncation, not a duplicate — is never reported as one.
    """
    given = list(entries or [])
    folded = merge_entries(given, [])
    seen, duplicates = set(), 0
    for entry in given:
        norm = normalize_entry(entry)
        if norm is None:
            continue  # an unusable row is DROPPED, never counted as a duplicate
        if norm["cmd"] in seen:
            duplicates += 1
        else:
            seen.add(norm["cmd"])
    return folded, duplicates


def format_last_used(timestamp, translate_fn=None) -> str:
    """The "Last used" cell of one entry: `2026-02-14 09:31`, or the "unknown" marker.

    A numeric, locale-neutral format on purpose (no translated month names to keep in four
    languages); `0` / a non-numeric / a negative value means "the file carried no timestamp" and
    renders the marker — the application never invents a date.
    """
    try:
        ts = float(timestamp or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts <= 0:
        return translate_fn("terminal.history.last_unknown") if translate_fn else ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return translate_fn("terminal.history.last_unknown") if translate_fn else ""


# ── the sort keys of the tree (the DATA, never the displayed cell) ──────────

#: The display order of the tree, one key per column, read from the ENTRY: the command by its
#: case-folded text (a header sort that read the cell would sort the same way here, but the key
#: still comes from the model), the timestamp by the EPOCH and the repeats by the INT. A text
#: sort of the last two columns would put `9` after `10` and would order the rendered dates of
#: two languages differently — the `list_sort_key()` rule of `ui/sidebar.py`.
SORT_KEYS = {
    0: lambda e: str(e["cmd"]).casefold(),
    1: lambda e: int(e.get("last") or 0),
    2: lambda e: int(e.get("count") or 0),
}


def sorted_entries(entries, column: int = 1, descending: bool = True) -> list:
    """The entries in the DISPLAY order of one column, by DATA. A pure function.

    Python's sort is stable, so the rows that share a key keep the order they came in (for the
    default "Last used" view that is the store's own newest-first order — the tie-break is the
    data's order, not an accident of insertion).
    """
    key = SORT_KEYS.get(int(column), SORT_KEYS[1])
    return sorted(entries, key=key, reverse=bool(descending))


# ── the store (pure Python, no Qt) ──────────────────────────────────────────

def default_history_dir() -> str:
    """`~/.sshmap/history/` — one file per server, next to config.json and logs/."""
    return os.path.join(os.path.expanduser("~"), ".sshmap", "history")


def history_key(server_id) -> str:
    """Stable file key of a server: `sha1(id)[:16]` (the `storage/autosave.project_key()` type).

    A KEY, never the id itself: an id may carry a slash, a colon, a Windows-reserved name or a
    character no file system accepts, and the history of such a node must still have a home. The
    identity is stable for the life of the node — a renamed alias or a changed host keeps its
    history.
    """
    return hashlib.sha1(str(server_id or "").encode("utf-8")).hexdigest()[:16]


def history_path_for(server_id, directory: str = None) -> str:
    """The path of one server's history file (an explicit directory — a test seam)."""
    return os.path.join(directory or default_history_dir(),
                        history_key(server_id) + ".json")


def _atomic_write_json(path: str, doc) -> bool:
    """The whole-document atomic write (tmp + flush + fsync + os.replace); False on OSError.

    The `command_library._atomic_write_json` / `storage.autosave.atomic_write_json` pattern —
    local, because `modules/*` owns its content file and answers a bool instead of raising.
    """
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


class CommandHistoryStore:
    """The command history of ONE server (`~/.sshmap/history/<key>.json`).

    The document: `{"format": 1, "commands": [{"cmd", "last", "count"}, …]}` — newest first.
    Every write RE-READS the file and MERGES the new entries into it, so two sessions of the
    same node cannot lose each other's commands. `load()` never writes: a corrupt file is a log
    line and an empty history, and it stays on disk until a write is really asked for.
    """

    def __init__(self, server_id, path: str = None, directory: str = None):
        self.server_id = str(server_id if server_id is not None else "")
        self._explicit_path = path
        self._directory = directory

    # ── paths ───────────────────────────────────────────────────────────────

    @property
    def path(self) -> str:
        """The file of this server (`path=` of the constructor wins — the test seam)."""
        return self._explicit_path or history_path_for(self.server_id, self._directory)

    # ── reading ─────────────────────────────────────────────────────────────

    def _read_entries(self) -> list:
        """The entries of the file, newest first. A missing/corrupt file → [] (never raises).

        A missing file is NOT an error and is NOT seeded: an empty history is the truthful state
        of a server nobody has recorded a command for yet.
        """
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            lg = _log()
            if lg is not None:
                lg.warning(f"command history: corrupt file {self.path} — starting empty")
            return []
        if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
            lg = _log()
            if lg is not None:
                lg.warning(
                    f"command history: unexpected document type in {self.path} — starting empty")
            return []
        out = []
        for record in data["commands"]:
            norm = normalize_entry(record)
            if norm is not None:
                out.append(norm)
        return sort_entries(out)

    def load(self) -> list:
        """The entries of this server, newest first (at most `MAX_ENTRIES_PER_SERVER`)."""
        return self._read_entries()

    # ── writing ─────────────────────────────────────────────────────────────

    def _write(self, entries) -> bool:
        """Write the whole document; False on an I/O error (the file is left untouched)."""
        doc = {"format": FORMAT_VERSION,
               "commands": [{"cmd": e["cmd"], "last": int(e["last"]), "count": int(e["count"])}
                            for e in entries]}
        return _atomic_write_json(self.path, doc)

    def merge(self, entries) -> list:
        """Re-read the file, fold `entries` into it, write the result; return the new list.

        The ONLY write path: the file is the truth and the caller's memory is a proposal, so a
        second session of the same node can write at any moment without losing commands.
        """
        merged = merge_entries(self._read_entries(), entries)
        if not self._write(merged):
            lg = _log()
            if lg is not None:
                lg.warning(f"command history: write failed for {self.path}")
            return self._read_entries()
        return merged

    def record(self, cmd, timestamp=None) -> list:
        """Record ONE command the application sent (an explicit timestamp — a test seam).

        The text is normalized like every entry (strip, the `MAX_CMD_CHARS` cap) and the
        timestamp is `now` by default. An empty or over-long command is ignored: it is not an
        entry of a command history.
        """
        ts = int(time.time() if timestamp is None else timestamp)
        norm = normalize_entry({"cmd": cmd, "last": ts, "count": 1})
        if norm is None:
            return self._read_entries()
        return self.merge([norm])

    def remove_duplicates(self):
        """Collapse the duplicates of the FILE → `(entries, removed_count)`; writes when needed."""
        entries = self._read_entries()
        folded, removed = dedup_entries(entries)
        if removed and not self._write(folded):
            return entries, 0
        return folded, removed

    def remove(self, cmd):
        """Forget ONE command → `(entries, removed)`. The same re-read-then-write rule.

        The identity is the SAME one the merge uses (the text after `strip()`), so a row the
        user sees is exactly the row that leaves the file. A command that is not there any
        more (a second session removed it a moment ago) answers False and leaves the file
        alone — the panel reloads either way.
        """
        target = normalize_entry({"cmd": cmd, "last": 0, "count": 1})
        if target is None:
            return self._read_entries(), False
        entries = self._read_entries()
        kept = [e for e in entries if e["cmd"] != target["cmd"]]
        if len(kept) == len(entries):
            return entries, False
        if not self._write(kept):
            return entries, False
        return kept, True

    def clear(self) -> bool:
        """Forget every command of this server (the confirmed "Clear history")."""
        return self._write([])


# ── the panel (the tab) ─────────────────────────────────────────────────────

class CommandHistoryPanel(QWidget):
    """v1.5.7: the "History" tab — the commands of THIS server, kept between sessions.

    Duck-typed against the session (the `command_library` pattern): `session` is the
    `TerminalSessionPage` that owns this tab. The panel uses exactly three things from it —
    `send_macro(text)` (the ONE send path, so the multi-input broadcast never duplicates the
    command), `server_data.alias` (the status line) and `ensure_sftp_worker()` (the lazily
    started SFTP channel behind "Import from the server…").

    Test seams (the command_library conventions): an explicit `store=`, `_build_context_menu(item)`
    (the tests trigger the QActions without `menu.exec()`) and the module attribute `QMessageBox`
    (monkeypatch `CH.QMessageBox`), plus `QFileDialog` for the file import.
    """

    status_message = Signal(str, int)   # (text, timeout_ms); 0 — sticky

    COL_COMMAND, COL_LAST, COL_COUNT = 0, 1, 2

    #: The direction a column takes when it is picked for the FIRST time: newest first and the
    #: most used first (the question a command history is opened with), A→Z for the text.
    FIRST_DIRECTION = {0: Qt.SortOrder.AscendingOrder,
                       1: Qt.SortOrder.DescendingOrder,
                       2: Qt.SortOrder.DescendingOrder}

    def __init__(self, store: CommandHistoryStore = None, session=None, parent=None):
        super().__init__(parent)
        t = get_translator()
        self._store = store if store is not None else CommandHistoryStore("")
        self._session = session
        self._entries = []
        self._worker = None            # the SFTP worker the pending server import was asked of
        self._server_task = None       # the task id of that import
        self._sort_column = self.COL_LAST
        self._sort_order = Qt.SortOrder.DescendingOrder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(t("terminal.history.filter_placeholder"))
        self.filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_edit)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("terminal.history.col_command"),
                                   t("terminal.history.col_last"),
                                   t("terminal.history.col_count")])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        # THE POLICY IS WHAT MAKES THE SIGNAL EXIST (the sftp_tab pattern): with the default
        # `Qt.DefaultContextMenu` a right click is a plain contextMenuEvent that this widget
        # ignores, so it travels UP to the container — where the terminal window answers it with
        # its own "Split Terminal" menu and the dock answers nothing at all. The panel takes the
        # policy too, so a right click on the EMPTY area of a fresh history still reaches the two
        # imports (the tree alone would leave that gesture to the container again).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_panel_context_menu)
        header = self.tree.header()
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.setSortIndicator(self._sort_column, self._sort_order)
        header.sectionClicked.connect(self.on_section_clicked)
        layout.addWidget(self.tree, 1)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.refresh_theme()
        self.reload()

    # ── the theme / the language ────────────────────────────────────────────

    def refresh_theme(self):
        """Re-apply the theme: the info label's colour is a VALUE (the §4.6 rule)."""
        try:
            self.info_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        except RuntimeError:
            pass  # Qt teardown — the label is already destroyed

    def retranslate(self):
        """Re-text the panel in the current language. Never raises (the dead-C++ discipline)."""
        t = get_translator()
        try:
            self.filter_edit.setPlaceholderText(t("terminal.history.filter_placeholder"))
            self.tree.setHeaderLabels([t("terminal.history.col_command"),
                                       t("terminal.history.col_last"),
                                       t("terminal.history.col_count")])
        except RuntimeError:
            return  # the C++ object is already deleted (a close race)
        self.reload()   # the cells carry the "unknown" marker and the counts sentence

    # ── data ────────────────────────────────────────────────────────────────

    @property
    def store(self) -> CommandHistoryStore:
        return self._store

    def entries(self) -> list:
        """The entries of the store, in the STORED order (newest first) — copies, never the live."""
        return [dict(e) for e in self._entries]

    def displayed_commands(self) -> list:
        """The commands of the rows ON SCREEN, top to bottom (the sort/order assertion)."""
        out = []
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is not None and not item.isHidden():
                    out.append(item.text(self.COL_COMMAND))
        except RuntimeError:
            return out   # Qt teardown
        return out

    def set_session(self, session):
        """The owning session (the terminal page)."""
        self._session = session

    def reload(self):
        """Re-read the store and rebuild the tree (show / record / import / a language switch)."""
        try:
            self._entries = self._store.load()
        except Exception:   # noqa: BLE001 — a broken store must not break the tab
            self._entries = []
        self._rebuild_tree()

    def _rebuild_tree(self):
        t = get_translator()
        try:
            self.tree.clear()
            rows = sorted_entries(self._entries, self._sort_column,
                                  self._sort_order == Qt.SortOrder.DescendingOrder)
        except RuntimeError:
            return  # Qt teardown
        for entry in rows:
            item = QTreeWidgetItem([entry["cmd"],
                                    format_last_used(entry["last"], t),
                                    str(entry["count"])])
            item.setToolTip(self.COL_COMMAND, entry["cmd"])   # the table elides, the tooltip is full
            item.setData(self.COL_COMMAND, Qt.ItemDataRole.UserRole, entry["cmd"])
            try:
                self.tree.addTopLevelItem(item)
            except RuntimeError:
                return  # Qt teardown mid-rebuild
        self._apply_filter()

    # ── the sorting (by DATA, driven by the header) ─────────────────────────

    def on_section_clicked(self, column: int):
        """A header click: the same column flips the direction, a new one takes its FIRST."""
        column = int(column)
        if column not in SORT_KEYS:
            return
        if column == self._sort_column:
            order = (Qt.SortOrder.AscendingOrder
                     if self._sort_order == Qt.SortOrder.DescendingOrder
                     else Qt.SortOrder.DescendingOrder)
        else:
            order = self.FIRST_DIRECTION[column]
        self.set_sort(column, order)

    def set_sort(self, column: int, order=None):
        """Apply a sort column + direction by DATA (the indicator first, then one rebuild)."""
        column = int(column)
        order = self.FIRST_DIRECTION.get(column, Qt.SortOrder.DescendingOrder) if order is None \
            else order
        self._sort_column, self._sort_order = column, order
        try:
            self.tree.header().setSortIndicator(column, order)
        except RuntimeError:
            pass  # Qt teardown
        self._rebuild_tree()

    def sort_state(self):
        """`(column, order)` — what the tree is sorted by right now."""
        return self._sort_column, self._sort_order

    # ── the filter / the counts ─────────────────────────────────────────────

    def _apply_filter(self):
        """Show the rows whose command matches the filter (case-insensitive); report the counts."""
        t = get_translator()
        try:
            query = self.filter_edit.text().strip().casefold()
        except RuntimeError:
            return  # Qt teardown
        shown = 0
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                hay = str(item.text(self.COL_COMMAND)).casefold()
                match = not query or query in hay
                item.setHidden(not match)
                if match:
                    shown += 1
        except RuntimeError:
            return  # Qt teardown
        total = len(self._entries)
        try:
            if not total:
                self.info_label.setText(t("terminal.history.empty"))
            elif not shown:
                self.info_label.setText(t("terminal.history.no_matches"))
            else:
                self.info_label.setText(
                    t("terminal.history.counts", total=total, shown=shown))
        except RuntimeError:
            pass  # Qt teardown

    # ── the current entry ───────────────────────────────────────────────────

    def _entry_for_item(self, item):
        """The live entry behind a row (by the command text — the identity of an entry)."""
        if item is None:
            return None
        try:
            cmd = item.text(self.COL_COMMAND)
        except RuntimeError:
            return None
        for entry in self._entries:
            if entry["cmd"] == cmd:
                return entry
        return None

    def _current_entry(self):
        """The entry behind the selected row (None — nothing selected)."""
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return None
        return self._entry_for_item(item)

    def _on_item_double_clicked(self, item, _column=0):
        if item is not None:
            self.send_entry(self._entry_for_item(item))

    # ── the send / the copy ─────────────────────────────────────────────────

    def send_entry(self, entry) -> bool:
        """Send one command to THIS session (the ONE `send_macro()` path — no broadcast).

        On success the row is re-read: the send went through the application's own record hook,
        so the timestamp and the count of this very entry have just moved.
        """
        t = get_translator()
        if not entry:
            return False
        session = self._session
        fn = getattr(session, "send_macro", None)
        ok = False
        if callable(fn):
            try:
                ok = bool(fn(entry["cmd"]))
            except Exception:   # noqa: BLE001 — a session teardown race
                ok = False
        try:
            alias = str(getattr(getattr(session, "server_data", None), "alias", "") or "")
        except Exception:   # noqa: BLE001 — a duck-typed session
            alias = ""
        if ok:
            self.reload()
            self.status_message.emit(t("terminal.cmdlib.sent_to", alias=alias), 4000)
        else:
            self.status_message.emit(t("terminal.cmdlib.no_active_session"), 4000)
        return ok

    def copy_entry(self, entry) -> bool:
        """Put one command on the clipboard (the macro panel's `_copy_entry` behaviour)."""
        if not entry:
            return False
        try:
            clipboard = QApplication.clipboard()
            if clipboard is None:
                return False
            clipboard.setText(entry["cmd"])
        except Exception:   # noqa: BLE001 — the clipboard is not critical
            return False
        self.status_message.emit(get_translator()("terminal.history.copied"), 3000)
        return True

    # ── the import ──────────────────────────────────────────────────────────

    def import_text(self, text, source: str = ""):
        """Parse `text` and merge it into the store → the report (a dict). Never raises.

        The ONE entry point of both imports: the local file reads its text and calls this, the
        server import decodes the bytes it got and calls this.
        """
        t = get_translator()
        entries, report = parse_history_text(text)
        if entries:
            self._store.merge(entries)
        self.reload()
        message = t("terminal.history.import_report",
                    parsed=report["parsed"], merged=report["merged"],
                    skipped_long=report["skipped_long"],
                    skipped_empty=report["skipped_empty"])
        if source:
            message = f"{message} — {source}"
        self.status_message.emit(message, 8000)
        return report

    def import_file(self, path: str = None) -> bool:
        """Import a LOCAL history file (works with no session and no network)."""
        t = get_translator()
        if not path:
            try:
                path, _selected = QFileDialog.getOpenFileName(
                    self.window() or self, t("terminal.history.import_file"), "")
            except Exception:   # noqa: BLE001 — a Qt teardown race
                return False
        if not path:
            return False
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        except OSError as e:
            self.status_message.emit(
                t("terminal.history.import_failed", error=str(e)), 8000)
            return False
        self.import_text(text, source=path)
        return True

    def import_from_server(self) -> bool:
        """Read `SERVER_HISTORY_PATH` over the session's SFTP channel (never on the GUI thread).

        The channel is the ONE the Files tab opens lazily: the panel asks the session for its
        worker (`ensure_sftp_worker()`), and the read itself runs inside the worker. Every
        refusal is an HONEST message: no channel, the worker's own caps (`MAX_READ_BYTES`, the
        binary verdict) and any other server error become a status line, never a traceback.
        """
        t = get_translator()
        worker = self._ensure_worker()
        if worker is None:
            self.status_message.emit(t("terminal.history.server_no_channel"), 6000)
            return False
        task_id = worker.queue_read(SERVER_HISTORY_PATH)
        if task_id is None:
            self.status_message.emit(t("terminal.history.server_no_channel"), 6000)
            return False
        self._server_task = int(task_id)
        self.status_message.emit(
            t("terminal.history.server_reading", path=SERVER_HISTORY_PATH), 0)
        return True

    def _ensure_worker(self):
        """The session's SFTP worker (started lazily) or None — rebinding our slots if it changed."""
        session = self._session
        ensure = getattr(session, "ensure_sftp_worker", None)
        worker = None
        if callable(ensure):
            try:
                worker = ensure()
            except Exception:   # noqa: BLE001 — a session teardown race
                worker = None
        if worker is self._worker:
            return worker
        self._unbind_worker()
        self._worker = worker
        if worker is not None:
            try:
                worker.read_ready.connect(self._on_server_read)
                worker.task_error.connect(self._on_server_error)
            except (RuntimeError, TypeError):
                self._worker = None
                return None
        return worker

    def _unbind_worker(self):
        """Drop our two slots from the previous worker (a dead one is a safe no-op)."""
        worker = self._worker
        self._worker = None
        self._server_task = None
        if worker is None:
            return
        for signal, slot in ((worker.read_ready, self._on_server_read),
                             (worker.task_error, self._on_server_error)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass  # not connected / the C++ object is gone

    def _on_server_read(self, task_id: int, remote_path: str, data: bytes):
        """The worker answered the history read → decode and merge it."""
        if self._server_task is None or int(task_id) != int(self._server_task):
            return  # another task of the same worker (the Files tab's read)
        self._server_task = None
        try:
            text = bytes(data).decode("utf-8-sig", errors="replace")
        except Exception:   # noqa: BLE001 — an unreadable payload must not raise into the GUI
            text = ""
        self.import_text(text, source=str(remote_path or SERVER_HISTORY_PATH))

    def _on_server_error(self, task_id: int, kind: str, message: str):
        """The worker REFUSED the read (binary / over the cap / the server's own error)."""
        if self._server_task is None or int(task_id) != int(self._server_task):
            return
        self._server_task = None
        t = get_translator()
        if kind == "read":
            if message == "too_large":
                try:
                    from .sftp_worker import MAX_READ_BYTES
                except ImportError:
                    from sftp_worker import MAX_READ_BYTES
                self.status_message.emit(
                    t("terminal.history.server_too_large",
                      limit=_format_size(MAX_READ_BYTES)), 8000)
                return
            if message == "binary":
                self.status_message.emit(t("terminal.history.server_binary"), 8000)
                return
        self.status_message.emit(
            t("terminal.history.server_failed",
              path=SERVER_HISTORY_PATH, error=str(message)), 8000)

    # ── the maintenance actions ─────────────────────────────────────────────

    def remove_duplicates(self) -> int:
        """Merge the duplicate rows of the FILE; report how many left (0 — nothing to merge)."""
        t = get_translator()
        _entries, removed = self._store.remove_duplicates()
        self.reload()
        if removed:
            self.status_message.emit(
                t("terminal.history.dedup_done", count=removed), 5000)
        else:
            self.status_message.emit(t("terminal.history.dedup_none"), 5000)
        return removed

    def delete_entry(self, entry) -> bool:
        """Forget ONE command after a confirmation (the macro panel's delete behaviour).

        The confirmation names the command — a history row is user data with no undo behind
        it, and the row is one click away from Copy/Send. Never raises.
        """
        t = get_translator()
        if not entry:
            return False
        cmd = str(entry.get("cmd", ""))
        box = QMessageBox   # the monkeypatch CH.QMessageBox works in the tests
        reply = box.question(
            self.window() or self,
            t("terminal.cmdlib.delete"),
            t("terminal.history.confirm_delete", cmd=cmd),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return False
        _entries, removed = self._store.remove(cmd)
        self.reload()
        if removed:
            self.status_message.emit(t("terminal.history.deleted"), 5000)
        return bool(removed)

    def clear_history(self) -> bool:
        """Forget every command of this server AFTER a confirmation (the macro delete pattern)."""
        t = get_translator()
        box = QMessageBox   # the monkeypatch CH.QMessageBox works in the tests
        reply = box.question(
            self.window() or self,
            t("terminal.history.clear"),
            t("terminal.history.confirm_clear"),
            box.Yes | box.No, box.No)
        if reply != box.Yes:
            return False
        ok = self._store.clear()
        self.reload()
        self.status_message.emit(t("terminal.history.cleared"), 5000)
        return bool(ok)

    # ── the context menu (test seam: the QActions without exec()) ───────────

    def _on_context_menu(self, pos):
        """A right click INSIDE the tree (the `CustomContextMenu` policy of `__init__`)."""
        try:
            item = self.tree.itemAt(pos)
        except RuntimeError:
            return  # the C++ object is already deleted (a close race)
        self._popup_menu(item, self.tree.mapToGlobal(pos))

    def _on_panel_context_menu(self, pos):
        """A right click on the PANEL itself (below the rows) — the imports stay reachable.

        A fresh history has no rows to right-click, and the two imports are exactly what a user
        opens that menu for; the panel therefore carries the same policy as its tree. A click
        that lands on the tree is consumed there (the event never reaches this handler), so the
        two paths cannot open two menus.
        """
        try:
            item = self.tree.itemAt(self.tree.viewport().mapFrom(self, pos))
        except RuntimeError:
            return  # the C++ object is already deleted (a close race)
        self._popup_menu(item, self.mapToGlobal(pos))

    def _popup_menu(self, item, global_pos):
        """Build and run the menu. The seam the tests replace (no modal menu offscreen)."""
        menu = self._build_context_menu(item)
        if menu is not None:
            menu.exec(global_pos)

    def _build_context_menu(self, item):
        """The tab's menu. A test seam: called directly, the QActions fire without `exec()`.

        The two imports are reachable from anywhere in the tab (the tree may be empty — the
        first thing a user does with a fresh history is import one), so the menu is never None.
        """
        t = get_translator()
        menu = QMenu(self)
        entry = self._entry_for_item(item)

        act_import = menu.addAction(t("terminal.history.import_file"))
        act_server = menu.addAction(t("terminal.history.import_server"))
        menu.addSeparator()
        act_copy = menu.addAction(t("terminal.history.copy"))
        act_send = menu.addAction(t("terminal.history.send"))
        # The label reuses the macro panel's `terminal.cmdlib.delete` — one word, one key.
        act_delete = menu.addAction(t("terminal.cmdlib.delete"))
        menu.addSeparator()
        act_dedup = menu.addAction(t("terminal.history.dedup"))
        act_clear = menu.addAction(t("terminal.history.clear"))

        has_entry = entry is not None
        act_copy.setEnabled(has_entry)
        act_send.setEnabled(has_entry and self._session is not None)
        act_delete.setEnabled(has_entry)
        act_dedup.setEnabled(bool(self._entries))
        act_clear.setEnabled(bool(self._entries))

        act_import.triggered.connect(lambda: self.import_file())
        act_server.triggered.connect(lambda: self.import_from_server())
        if has_entry:
            act_copy.triggered.connect(lambda: self.copy_entry(entry))
            act_send.triggered.connect(lambda: self.send_entry(entry))
            act_delete.triggered.connect(lambda: self.delete_entry(entry))
        act_dedup.triggered.connect(self.remove_duplicates)
        act_clear.triggered.connect(self.clear_history)
        return menu
