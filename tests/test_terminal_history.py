# -*- coding: utf-8 -*-
"""v1.5.7 — the command history: the terminal's third tab, one history per server.

ROADMAP v1.5.7:
  #1 `modules/command_history.py` — the store (`~/.sshmap/history/<key>.json`, one file per
     server, atomic, MERGE on every write), the PURE parser and the panel; the store is keyed
     by `ServerData.id`, so a renamed alias keeps its history;
  #2 the parser: bash (one command per line + the `HISTTIMEFORMAT` markers), zsh extended
     (`: <epoch>:<duration>;<command>`), empty lines dropped, the identity = the text after
     `strip()` ONLY, a duplicate keeps the LATEST timestamp and counts its repeats;
  #3 the two DECLARED caps — `MAX_CMD_CHARS` (skipped at import, counted in the report) and
     `MAX_ENTRIES_PER_SERVER` (the FIFO eviction cap);
  #4 the `History` tab of `TerminalSessionPage` (index 2), its `retranslate()` and
     `refresh_theme()`;
  #5 the context menu: import a file, import from the server, copy, send, dedup, clear
     (confirmed);
  #6 "Send to terminal" through the ONE `send_macro()` path (a bracketed paste for a multi-line
     entry, never the multi-input broadcast);
  #7 the application records what IT sent (the macro library, quick launch, this tab) and
     NOTHING is inferred from the typed input;
  #8 the import: a local file, and the server's `~/.bash_history` over the session's SFTP
     channel with the worker's own cap surfaced honestly.

Sections:
  §1 the pure parser (bash markers, zsh extended, the exact-text identity, the dedup rule);
  §2 the caps (MAX_CMD_CHARS at import, MAX_ENTRIES_PER_SERVER as the FIFO ring) + the pure
     helpers (`normalize_entry`, `merge_entries`, `dedup_entries`, `sorted_entries`);
  §3 the store (an atomic merge write, the two-session case, the corrupt file, the clear);
  §4 the tab (index 2, the titles, retranslate, the compact pane);
  §5 the tree sorted by the DATA (the epoch and the int, never the displayed text);
  §6 the context menu and the maintenance actions;
  §7 "Send to terminal" through `send_macro()` + the auto-record of what the app sent;
  §8 the import — a local file and the server's `~/.bash_history` (with the refusals);
  §9 the release state.

Run: python tests/test_terminal_history.py   (from the project root) or python tests/run_all.py
"""

import json
import os
import sys
import threading

from _common import (bootstrap, check, finish, wait_until, check_release_state,
                     EXPECTED_APP_VERSION, EXPECTED_I18N_KEYS, i18n_lang_codes,
                     load_i18n_langs, translation_keys)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + offscreen)

from PySide6.QtCore import QPoint   # noqa: E402
from PySide6.QtGui import QContextMenuEvent   # noqa: E402
from PySide6.QtWidgets import QApplication   # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import modules.command_history as CH  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
from modules.command_history import (  # noqa: E402
    CommandHistoryStore, MAX_CMD_CHARS, MAX_ENTRIES_PER_SERVER, SERVER_HISTORY_PATH,
    dedup_entries, format_last_used, history_key, history_path_for, merge_entries,
    normalize_entry, parse_history_text, sort_entries, sorted_entries,
)
from modules.sftp_worker import MAX_READ_BYTES, SftpWorker  # noqa: E402
from modules.sftp_tab import format_size  # noqa: E402
from modules.terminal_page import TerminalSessionPage  # noqa: E402
from models.server import ServerData  # noqa: E402

from _fakes import (EventLog, FakeSftpClient, FakeSftpFS, FakeSSHThread,  # noqa: E402
                    QuestionStub, wire_worker)

MAIN_THREAD_IDENT = threading.main_thread().ident
_ORIG_THREAD_CLS = ST.SSHTerminalThread
ST.SSHTerminalThread = FakeSSHThread   # every page in this file — on the fake (the seam)


class RecordingClient(FakeSftpClient):
    """FakeSftpClient + WHICH thread resolved the home (the "never on the GUI thread" proof)."""

    def __init__(self, fs):
        super().__init__(fs)
        self.normalize_idents = []

    def normalize(self, path):
        self.normalize_idents.append(threading.current_thread().ident)
        return super().normalize(path)


def make_store(name, server_id="srv-1"):
    """A store in the sandbox (the explicit path seam — never the real ~/.sshmap)."""
    return CommandHistoryStore(server_id, path=os.path.join(WORK, f"{name}.json"))


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def displayed(panel):
    """The commands of the rows on screen, top to bottom."""
    return panel.displayed_commands()


def worker_over(fs, home="/home/tester"):
    """A started SftpWorker over the fake FS + its event log (the viewer-test pattern)."""
    client = RecordingClient(fs) if home else FakeSftpClient(fs)
    if home:
        client.home = home
    worker = SftpWorker(client)
    log = EventLog()
    wire_worker(worker, log)
    worker.start()
    return worker, log, client


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the pure parser (bash markers, zsh extended, the identity) ==")
# ════════════════════════════════════════════════════════════════════════════

_entries, _report = parse_history_text("#1700000000\nls -la\nuptime\n#1700000500\ndf -h\n")
check("bash: one command per line, a marker timestamps the commands that FOLLOW it",
      [(e["cmd"], e["last"]) for e in _entries]
      == [("ls -la", 1700000000), ("uptime", 1700000000), ("df -h", 1700000500)]
      and _report == {"parsed": 3, "merged": 0, "skipped_long": 0, "skipped_empty": 0},
      f"{_entries} {_report}")

_entries, _report = parse_history_text("ls -la\n\n   \nLS\n")
check("blank and whitespace-only lines are dropped and counted as empty",
      [e["cmd"] for e in _entries] == ["ls -la", "LS"] and _report["skipped_empty"] == 2,
      f"{_entries} {_report}")

_entries, _report = parse_history_text("   ls -la   \ngrep  a\ngrep a\n")
check("the identity is the STRIPPED text only: no case folding, no inner-space collapsing",
      [e["cmd"] for e in _entries] == ["ls -la", "grep  a", "grep a"], str(_entries))

_entries, _report = parse_history_text("awk '{print $1}' \\\n    /var/log/x\n")
check("the parser does NOT join a backslash continuation — one command per line is the rule",
      [e["cmd"] for e in _entries] == ["awk '{print $1}' \\", "/var/log/x"], str(_entries))

_entries, _report = parse_history_text(": 1700000000:0;ls -la\n: 1700000500:12;echo a;echo b\n")
check("zsh extended: the epoch and the duration are parsed, ';' survives and an empty record "
      "counts as an empty line",
      [(e["cmd"], e["last"]) for e in _entries]
      == [("ls -la", 1700000000), ("echo a;echo b", 1700000500)]
      and parse_history_text(": 1700000000:0;\n")[0] == []
      and parse_history_text(": 1700000000:0;\n")[1]["skipped_empty"] == 1, str(_entries))

check("a line that is exactly '#' + digits is a MARKER; any other '#' line is a COMMAND",
      [e["cmd"] for e in parse_history_text("#1700000000\n#123\nls\n")[0]] == ["ls"]
      and [e["cmd"] for e in
           parse_history_text("#1700000000\n# a comment line\n## 123\n")[0]]
      == ["# a comment line", "## 123"])

_entries, _report = parse_history_text("ls -la\nls -la\nls -la\n#1700000000\nls -la\n")
check("a duplicate keeps the LATEST timestamp and counts its repeats",
      len(_entries) == 1 and _entries[0]["count"] == 4 and _entries[0]["last"] == 1700000000
      and _report["merged"] == 3, f"{_entries} {_report}")

check("an undated file keeps last=0 (never a made-up now) and the counters account for every "
      "non-marker line",
      parse_history_text("ls -la\n")[0][0]["last"] == 0
      and sum(parse_history_text("#1700000000\nls\n\n   \n#1700000005\nls\n")[1].values()) == 4)


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the declared caps and the pure helpers ==")
# ════════════════════════════════════════════════════════════════════════════

_long = "x" * (MAX_CMD_CHARS + 1)
_entries, _report = parse_history_text(f"ok\n{_long}\n{'y' * MAX_CMD_CHARS}\n")
check("a command over MAX_CMD_CHARS is SKIPPED at import (counted); a kept one is never cut",
      _report["skipped_long"] == 1 and _report["parsed"] == 2
      and _entries[1]["cmd"] == "y" * MAX_CMD_CHARS, str(_report))

_many = [{"cmd": f"cmd-{i:04d}", "last": 1000 + i, "count": 1}
         for i in range(MAX_ENTRIES_PER_SERVER + 5)]
_capped = sort_entries(_many)
check(f"the FIFO cap keeps {MAX_ENTRIES_PER_SERVER} entries and drops the least recently used",
      len(_capped) == MAX_ENTRIES_PER_SERVER
      and _capped[0]["cmd"] == f"cmd-{MAX_ENTRIES_PER_SERVER + 4:04d}"
      and all(e["cmd"] != "cmd-0000" for e in _capped), f"{len(_capped)} {_capped[0]}")

check("normalize_entry drops an unusable record and repairs a broken last/count",
      normalize_entry(None) is None and normalize_entry({"cmd": ""}) is None
      and normalize_entry({"cmd": _long}) is None and normalize_entry({"cmd": 5}) is None
      and normalize_entry({"cmd": "ls", "last": "x", "count": 0})
      == {"cmd": "ls", "last": 0, "count": 1, CH.SECRET_FIELD: False})

_merged = merge_entries([{"cmd": "ls", "last": 100, "count": 2}],
                        [{"cmd": "ls", "last": 300, "count": 1},
                         {"cmd": "df", "last": 50, "count": 1}])
check("merge_entries keeps the latest timestamp, sums the repeats and sorts newest first",
      [(e["cmd"], e["last"], e["count"]) for e in _merged]
      == [("ls", 300, 3), ("df", 50, 1)], str(_merged))

_folded, _removed = dedup_entries([{"cmd": "ls", "last": 1, "count": 1},
                                   {"cmd": "ls", "last": 2, "count": 1},
                                   {"cmd": "df", "last": 0, "count": 1}])
check("dedup_entries folds the duplicates and is quiet on a clean list",
      _removed == 1 and len(_folded) == 2
      and [e for e in _folded if e["cmd"] == "ls"][0]["count"] == 2
      and dedup_entries([{"cmd": "ls", "last": 1, "count": 1}])[1] == 0, str(_folded))

_rows = [{"cmd": "old", "last": 1700000000, "count": 1},
         {"cmd": "new", "last": 1800000000, "count": 9},
         {"cmd": "ten", "last": 1900000000, "count": 10},
         {"cmd": "undated", "last": 0, "count": 3}]
check("sorted_entries reads the DATA (the epoch, the int) and format_last_used marks an "
      "undated entry while rendering a dated one numerically",
      [e["cmd"] for e in sorted_entries(_rows, 1, True)] == ["ten", "new", "old", "undated"]
      and [e["cmd"] for e in sorted_entries(_rows, 2, False)]
      == ["old", "undated", "new", "ten"]
      and format_last_used(0, i18n.t) == i18n.t("terminal.history.last_unknown")
      and format_last_used(None, i18n.t) == i18n.t("terminal.history.last_unknown")
      and format_last_used(1700000000, i18n.t).startswith("2023-11-1"),
      f"{[e['cmd'] for e in sorted_entries(_rows, 2)]} {format_last_used(1700000000)}")


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the store ==")
# ════════════════════════════════════════════════════════════════════════════

store_a = make_store("a")
check("a missing file is an EMPTY history, and a read never creates it (never seeded)",
      store_a.load() == [] and not os.path.exists(store_a.path))

store_a.record("df -h", timestamp=1700000000)
check("record() writes the declared document atomically (the file exists and parses)",
      os.path.isfile(store_a.path)
      and json.loads(read_text(store_a.path))
      == {"format": CH.FORMAT_VERSION,
          "commands": [{"cmd": "df -h", "last": 1700000000, "count": 1}]},
      read_text(store_a.path))

store_a.record("uptime", timestamp=1700000500)
store_a.record("df -h", timestamp=1700000900)
check("a repeated command moves its timestamp and grows its count",
      [(e["cmd"], e["last"], e["count"]) for e in store_a.load()]
      == [("df -h", 1700000900, 2), ("uptime", 1700000500, 1)], str(store_a.load()))

# The SPLIT PANE case: two stores over ONE file must not lose each other's commands.
CommandHistoryStore("srv-1", path=store_a.path).record("whoami", timestamp=1700001000)
check("a write RE-READS and MERGES — a second session of the same node loses nothing",
      sorted(e["cmd"] for e in store_a.load()) == ["df -h", "uptime", "whoami"],
      str(store_a.load()))

_corrupt = make_store("corrupt")
with open(_corrupt.path, "w", encoding="utf-8") as f:
    f.write("{ this is not json")
_before = read_text(_corrupt.path)
check("a corrupt file yields an empty history and a READ never rewrites it",
      _corrupt.load() == [] and read_text(_corrupt.path) == _before)

_dirty = make_store("dirty")
with open(_dirty.path, "w", encoding="utf-8") as f:
    json.dump({"format": 1, "commands": [
        {"cmd": "ls", "last": 10, "count": 1},
        {"cmd": "ls", "last": 20, "count": 4},
        {"cmd": "df", "last": 5, "count": 1}]}, f)
_folded, _removed = _dirty.remove_duplicates()
check("remove_duplicates folds a hand-edited file (0 when there is nothing to do) and clear() "
      "empties the history through a valid document",
      _removed == 1 and len(_folded) == 2
      and [e for e in _dirty.load() if e["cmd"] == "ls"][0]["count"] == 5
      and _dirty.remove_duplicates()[1] == 0
      and _dirty.clear() is True and _dirty.load() == [], str(_folded))

check("the file key is per id, stable for that id, sha1-based and cannot escape the folder",
      history_key("srv-1") == history_key("srv-1") != history_key("srv-2")
      and os.path.basename(history_path_for("srv-1")) == history_key("srv-1") + ".json"
      and "/" not in history_key("../../etc/passwd")
      and os.path.basename(history_path_for("../../etc/passwd", directory="/tmp"))
      == history_key("../../etc/passwd") + ".json")


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the tab (index 2) + the compact pane ==")
# ════════════════════════════════════════════════════════════════════════════

node = ServerData(id="hist-1", alias="web-1", host="10.77.0.1", user="root")
page = TerminalSessionPage(node)
app.processEvents()
check("the session has THREE tabs (Terminal | Files | History) and the panel is index 2",
      [page.tabs.tabText(i) for i in range(page.tabs.count())]
      == [i18n.t("sftp.tab_terminal"), i18n.t("sftp.tab_files"), i18n.t("terminal.tab_history")]
      and page.tabs.widget(2) is page.history_tab
      and page.history_tab.store is page.command_history,
      str([page.tabs.tabText(i) for i in range(page.tabs.count())]))

pane = TerminalSessionPage(node, with_sftp=False, with_status_line=False)
app.processEvents()
pane.record_sent_command("echo pane")
check("a SPLIT PANE keeps its compact rule (ONE tab, no History tab) yet still owns the store",
      pane.tabs.count() == 1 and pane.history_tab is None and pane.sftp_tab is None
      and isinstance(pane.command_history, CommandHistoryStore)
      and [e["cmd"] for e in pane.command_history.load()] == ["echo pane"],
      str(pane.command_history.load()))

i18n.set_language("ru")
page.retranslate()
app.processEvents()
_ru_ok = (page.tabs.tabText(2) == i18n.t("terminal.tab_history")
          and page.tabs.tabText(1) == i18n.t("sftp.tab_files")
          and page.history_tab.tree.headerItem().text(2) == i18n.t("terminal.history.col_count")
          and page.history_tab.filter_edit.placeholderText()
          == i18n.t("terminal.history.filter_placeholder"))
i18n.set_language("en")
page.retranslate()
app.processEvents()
page.refresh_theme()
check("retranslate() re-texts the History tab and the panel (both ways) and refresh_theme() "
      "reaches the panel's info label",
      _ru_ok and page.tabs.tabText(2) == i18n.t("terminal.tab_history")
      and page.history_tab.tree.headerItem().text(1) == i18n.t("terminal.history.col_last")
      and page.history_tab.info_label.styleSheet() == f"color: {CH.theme.TEXT_MUTED};",
      f"{page.tabs.tabText(2)} {page.history_tab.info_label.styleSheet()}")

# ════════════════════════════════════════════════════════════════════════════
print("== §5 the tree sorted by the DATA, not by the displayed text ==")
# ════════════════════════════════════════════════════════════════════════════

panel = CH.CommandHistoryPanel(store=make_store("sort", "sort-node"))
panel.store.merge([{"cmd": "old", "last": 1700000000, "count": 1},
                   {"cmd": "new", "last": 1800000000, "count": 9},
                   {"cmd": "ten", "last": 1900000000, "count": 10},
                   {"cmd": "undated", "last": 0, "count": 3}])
panel.reload()
check("the default order is the newest first, and every direction reads the epoch / the int "
      "(never the rendered cell)",
      displayed(panel) == ["ten", "new", "old", "undated"]
      and (panel.set_sort(2, CH.Qt.SortOrder.AscendingOrder) or displayed(panel))
      == ["old", "undated", "new", "ten"]
      and (panel.set_sort(1, CH.Qt.SortOrder.AscendingOrder) or displayed(panel))
      == ["undated", "old", "new", "ten"]
      and (panel.set_sort(0, CH.Qt.SortOrder.AscendingOrder) or displayed(panel))
      == ["new", "old", "ten", "undated"], str(displayed(panel)))

panel.set_sort(1, CH.Qt.SortOrder.AscendingOrder)
panel.on_section_clicked(1)
_flip = panel.sort_state() == (1, CH.Qt.SortOrder.DescendingOrder)
panel.on_section_clicked(2)
check("a header click flips the CURRENT column and a NEW one takes its first direction",
      _flip and panel.sort_state() == (2, CH.Qt.SortOrder.DescendingOrder)
      and displayed(panel) == ["ten", "new", "undated", "old"], str(panel.sort_state()))

panel.filter_edit.setText("ten")
check("the filter hides the non-matching rows; the counts and the no-matches lines follow",
      displayed(panel) == ["ten"]
      and panel.info_label.text() == i18n.t("terminal.history.counts", total=4, shown=1)
      and (panel.filter_edit.setText("no-such-command") or True)
      and panel.info_label.text() == i18n.t("terminal.history.no_matches"),
      panel.info_label.text())
panel.filter_edit.setText("")


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the context menu and the maintenance actions ==")
# ════════════════════════════════════════════════════════════════════════════

_menu = panel._build_context_menu(panel.tree.topLevelItem(0))
_texts = [a.text() for a in _menu.actions() if not a.isSeparator()]
check("the menu carries the seven items, in order, all translated; a row enables Copy/Delete",
      _texts == [i18n.t("terminal.history.import_file"),
                 i18n.t("terminal.history.import_server"),
                 i18n.t("terminal.history.copy"),
                 i18n.t("terminal.history.send"),
                 i18n.t("terminal.cmdlib.delete"),
                 i18n.t("terminal.history.dedup"),
                 i18n.t("terminal.history.clear")]
      and [a.isEnabled() for a in _menu.actions() if not a.isSeparator()][2:5]
      == [True, False, True],
      str(_texts))

# The GESTURE, not only the menu: the POLICY is what makes Qt emit `customContextMenuRequested`
# at all — under the default one the right click is a plain contextMenuEvent this widget
# ignores, so it travels UP to the container (where the terminal window answered it with its own
# "Split Terminal" menu and the dock answered nothing) and this tab's menu never opened. The
# proof is a REAL QContextMenuEvent, not a hand-emitted signal.
_popups = []
panel._popup_menu = lambda item, pos: _popups.append(item)
_row = panel.tree.topLevelItem(0)
for _target, _pos in ((panel.tree.viewport(), panel.tree.visualItemRect(_row).center()),
                      (panel.tree.viewport(), QPoint(10, panel.tree.viewport().height() - 2))):
    QApplication.sendEvent(_target, QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, _pos, _target.mapToGlobal(_pos)))
    app.processEvents()
panel._on_panel_context_menu(QPoint(10, panel.tree.viewport().height() + 20))
check("the right click is OURS: both widgets carry the CustomContextMenu policy and a REAL "
      "event reaches the builder (a row → that row, below the rows → the two imports)",
      panel.tree.contextMenuPolicy() == CH.Qt.ContextMenuPolicy.CustomContextMenu
      and panel.contextMenuPolicy() == CH.Qt.ContextMenuPolicy.CustomContextMenu
      and len(_popups) == 3 and _popups[0] is _row
      and _popups[1] is None and _popups[2] is None,
      f"{panel.tree.contextMenuPolicy()} / {panel.contextMenuPolicy()} / {_popups}")

panel_ro = CH.CommandHistoryPanel(store=make_store("ro", "ro-node"))
_enabled = {a.text(): a.isEnabled()
            for a in panel_ro._build_context_menu(None).actions() if not a.isSeparator()}
check("on an EMPTY history the imports stay reachable, the rest is disabled and it says so",
      _enabled[i18n.t("terminal.history.import_file")] is True
      and _enabled[i18n.t("terminal.history.import_server")] is True
      and _enabled[i18n.t("terminal.history.copy")] is False
      and _enabled[i18n.t("terminal.history.send")] is False
      and _enabled[i18n.t("terminal.cmdlib.delete")] is False
      and _enabled[i18n.t("terminal.history.dedup")] is False
      and _enabled[i18n.t("terminal.history.clear")] is False
      and panel_ro.info_label.text() == i18n.t("terminal.history.empty"),
      f"{_enabled} | {panel_ro.info_label.text()}")

_msgs = []
panel.status_message.connect(lambda text, ms: _msgs.append(text))
panel.copy_entry({"cmd": "ten", "last": 1, "count": 10})
check("Copy puts the full command text on the clipboard and reports itself; an already merged "
      "history has nothing for 'Remove duplicates' to do",
      QApplication.clipboard().text() == "ten"
      and _msgs and _msgs[-1] == i18n.t("terminal.history.copied")
      and panel.remove_duplicates() == 0
      and _msgs[-1] == i18n.t("terminal.history.dedup_none"), str(_msgs))

# v1.5.7: the per-row Delete (the tester's request) — a re-read-then-write like every other path.
_del = make_store("delete", "del-node")
_del.merge([{"cmd": "keep me", "last": 2, "count": 1},
            {"cmd": "drop me", "last": 1, "count": 1}])
_left, _gone = _del.remove("drop me")
check("store.remove() drops exactly ONE row (and a second call is a quiet no-op)",
      _gone is True and [e["cmd"] for e in _left] == ["keep me"]
      and _del.remove("drop me") == (_del.load(), False)
      and [e["cmd"] for e in _del.load()] == ["keep me"],
      str(_left))

panel_del = CH.CommandHistoryPanel(store=make_store("del-panel", "del-panel"))
panel_del.import_text("#1700000000\nalpha\n#1700000100\nbeta\n")
_del_msgs = []
panel_del.status_message.connect(lambda text, ms: _del_msgs.append(text))
with QuestionStub().install(CH) as _stub2:
    _stub2.answer = CH.QMessageBox.No
    _no_del = panel_del.delete_entry({"cmd": "alpha", "last": 1, "count": 1}) is False
    _stub2.answer = CH.QMessageBox.Yes
    _yes_del = (panel_del.delete_entry({"cmd": "alpha", "last": 1, "count": 1}) is True
                and [e["cmd"] for e in panel_del.entries()] == ["beta"]
                and _del_msgs[-1] == i18n.t("terminal.history.deleted"))
check("Delete asks first (naming the command): 'No' keeps the row, 'Yes' removes it and reports",
      _no_del and _yes_del
      and [c[1] for c in _stub2.calls]
      == [i18n.t("terminal.history.confirm_delete", cmd="alpha")] * 2,
      f"{_no_del} {_yes_del} {_stub2.calls}")

with QuestionStub().install(CH) as _stub:
    _stub.answer = CH.QMessageBox.No
    _no_keeps = panel.clear_history() is False and len(panel.entries()) == 4
    _stub.answer = CH.QMessageBox.Yes
    _yes_clears = (panel.clear_history() is True and panel.entries() == []
                   and _msgs[-1] == i18n.t("terminal.history.cleared"))
check("Clear history asks first: 'No' keeps everything, 'Yes' empties the store and reports",
      _no_keeps and _yes_clears
      and _stub.calls and _stub.calls[0][1] == i18n.t("terminal.history.confirm_clear"),
      f"{_no_keeps} {_yes_clears} {_stub.calls}")


# ════════════════════════════════════════════════════════════════════════════
print("== §7 Send to terminal + the auto-record of what the application sent ==")
# ════════════════════════════════════════════════════════════════════════════

MULTI = "awk '{s+=$1} END {print s}' \\\n    /var/log/x"
_send_msgs = []
page.history_tab.status_message.connect(lambda text, ms: _send_msgs.append(text))
page.command_history.clear()
page.history_tab.import_text("#1700000000\nls -la\n#1700000100\nwhoami\n")

_chan = page.terminal_thread.channel
_chan.sent.clear()
page.history_tab.send_entry({"cmd": "ls -la", "last": 0, "count": 1})
check("Send to terminal puts the RAW line + \\n on the wire and reports the alias",
      _chan.sent == [b"ls -la\n"] and _send_msgs
      and _send_msgs[-1] == i18n.t("terminal.cmdlib.sent_to", alias="web-1"),
      f"{_chan.sent} {_send_msgs}")
check("the application RECORDED what it sent — the timestamp moved and the count grew",
      {e["cmd"] for e in page.command_history.load()} == {"ls -la", "whoami"}
      and page.command_history.load()[0]["cmd"] == "ls -la"
      and [e for e in page.command_history.load() if e["cmd"] == "ls -la"][0]["count"] == 2,
      str(page.command_history.load()))

# A multi-line command can only come from the application itself (the parser is line-based):
# a macro with a line continuation, recorded and then sent from the tab.
page.command_history.record(MULTI)
page.history_tab.reload()
_chan.sent.clear()
page.history_tab.send_entry({"cmd": MULTI, "last": 0, "count": 1})
check("the app's multi-line command is ONE entry and arrives as ONE bracketed paste",
      MULTI in {e["cmd"] for e in page.history_tab.entries()}
      and _chan.sent == [b"\x1b[200~awk '{s+=$1} END {print s}' \\\n    /var/log/x\n\x1b[201~"],
      str(_chan.sent))

# The macro-library path: CommandLibraryPanel calls TerminalWidget.send_macro directly
# (never page.send_macro) — the canvas hook must cover it.
_chan.sent.clear()
page.command_history.clear()
page.widget.send_macro("systemctl restart docker")
_macro_ok = ([e["cmd"] for e in page.command_history.load()] == ["systemctl restart docker"]
             and page.widget.command_sent_hook == page.record_sent_command)
_chan.closed = True
_send_msgs.clear()
_dead_ok = (page.history_tab.send_entry({"cmd": "whoami", "last": 0, "count": 1}) is False
            and _send_msgs[-1] == i18n.t("terminal.cmdlib.no_active_session"))
_chan.closed = False
check("a macro-library send is recorded too (the ONE canvas hook knows the store), and a send "
      "into a DEAD session answers False and reports instead of raising",
      _macro_ok and _dead_ok
      and [e["cmd"] for e in page.command_history.load()] == ["systemctl restart docker"],
      f"{page.command_history.load()} {_send_msgs}")


# ════════════════════════════════════════════════════════════════════════════
print("== §8 the import — a local file and the server's ~/.bash_history ==")
# ════════════════════════════════════════════════════════════════════════════

_local = os.path.join(WORK, "bash_history.txt")
with open(_local, "w", encoding="utf-8") as f:
    f.write("#1700000000\nls -la\n#1700000500\ndf -h\ndf -h\n\n")
_import_msgs = []
page.history_tab.status_message.connect(lambda text, ms: _import_msgs.append(text))
page.command_history.clear()
page.history_tab.reload()
check("a LOCAL file import works with no session and no network, deduplicated, with its report",
      page.history_tab.import_file(_local) is True
      and sorted(e["cmd"] for e in page.history_tab.entries()) == ["df -h", "ls -la"]
      and _import_msgs[-1].startswith(
          i18n.t("terminal.history.import_report", parsed=2, merged=1,
                 skipped_long=0, skipped_empty=1))
      and _local in _import_msgs[-1], _import_msgs[-1])
check("an unreadable file is reported, not raised",
      page.history_tab.import_file(os.path.join(WORK, "no-such-history")) is False
      and _import_msgs[-1].startswith(i18n.t("terminal.history.import_failed", error="")),
      _import_msgs[-1])

# ── the server import through the REAL worker over the fake SFTP FS ──
_fs = FakeSftpFS()
_fs.add_dir("/home/tester")
_fs.add_file("/home/tester/.bash_history",
             b"#1700000000\nuname -a\n#1700000600\nfree -m\nfree -m\n")
_worker, _log, _client = worker_over(_fs)
page._sftp_worker = _worker
page.command_history.clear()
page.history_tab.reload()
_import_msgs.clear()
check("Import from the server queues the declared path over the session's worker",
      page.history_tab.import_from_server() is True)
wait_until(lambda: page.history_tab.tree.topLevelItemCount() >= 2, timeout_ms=8000)
app.processEvents()
check("the server's ~/.bash_history was read over the worker and merged into the store",
      sorted(e["cmd"] for e in page.history_tab.entries()) == ["free -m", "uname -a"]
      and any(SERVER_HISTORY_PATH in m for m in _import_msgs),
      f"{page.history_tab.entries()} {_import_msgs}")
check("the ~/ path is expanded ON THE WORKER THREAD, and read_ready keeps the ASKED path",
      bool(_log.of_kind("read")) and _log.of_kind("read")[0][2] == SERVER_HISTORY_PATH
      and bool(_client.normalize_idents)
      and all(ident != MAIN_THREAD_IDENT for ident in _client.normalize_idents),
      f"{_log.of_kind('read')} {_client.normalize_idents}")

# The worker's own cap and its binary verdict, surfaced honestly.
_fs2 = FakeSftpFS()
_fs2.add_dir("/home/tester")
_fs2.add_file("/home/tester/.bash_history", b"x" * (MAX_READ_BYTES + 5))
_worker2, _log2, _client2 = worker_over(_fs2)
page._sftp_worker = _worker2
_import_msgs.clear()
_rebind_ok = page.history_tab.import_from_server() is True
wait_until(lambda: bool(_log2.of_kind("error")), timeout_ms=20000)
app.processEvents()
check("a new import rebinds the panel to the NEW worker, and a history file over the worker's "
      "cap is refused with the code AND an honest message",
      _rebind_ok and bool(_log2.of_kind("error")) and _log2.of_kind("error")[0][3] == "too_large"
      and any(m == i18n.t("terminal.history.server_too_large",
                          limit=format_size(MAX_READ_BYTES)) for m in _import_msgs),
      f"{_log2.of_kind('error')} {_import_msgs}")

_fs3 = FakeSftpFS()
_fs3.add_dir("/home/tester")
_fs3.add_file("/home/tester/.bash_history", b"\x00\x01binary\x00")
_worker3, _log3, _client3 = worker_over(_fs3)
page._sftp_worker = _worker3
_import_msgs.clear()
_no_channel = CH.CommandHistoryPanel(store=make_store("nc", "nc-node"))
_no_msgs = []
_no_channel.status_message.connect(lambda text, ms: _no_msgs.append(text))
page.history_tab.import_from_server()
wait_until(lambda: bool(_log3.of_kind("error")), timeout_ms=8000)
app.processEvents()
check("a 'binary' verdict gets its own message; a session-less panel says 'no channel'",
      any(m == i18n.t("terminal.history.server_binary") for m in _import_msgs)
      and _no_channel.import_from_server() is False
      and _no_msgs[-1] == i18n.t("terminal.history.server_no_channel"),
      f"{_import_msgs} {_no_msgs}")


# ════════════════════════════════════════════════════════════════════════════
print("== §9 the release state ==")
# ════════════════════════════════════════════════════════════════════════════

check("EXPECTED_APP_VERSION is the version this test file describes",
      EXPECTED_APP_VERSION == "1.6.6", EXPECTED_APP_VERSION)
check("the pin counts the shipped keys (+29 of v1.5.7: the tab, the panel chrome, the seven menu items "
      "with their reports and refusals, + the marked secret of v1.6.4) — "
      "708 + 29 + 41 + 4 + 4 + 3 + 11 + 11 = 811",
      EXPECTED_I18N_KEYS == 811, str(EXPECTED_I18N_KEYS))
check_release_state(ROOT)

_langs = load_i18n_langs(ROOT)
check("every discovered language carries the whole v1.5.7 command-history key family "
      "(+ the v1.6.4 marked-secret tooltip)",
      all(len([k for k in translation_keys(_langs[c]) if k.startswith("terminal.history.")])
          == 29 and "terminal.tab_history" in translation_keys(_langs[c])
          and str(_langs[c].get("terminal.tab_history", "")).strip()
          for c in i18n_lang_codes(ROOT)),
      str({c: len([k for k in translation_keys(_langs[c])
                   if k.startswith("terminal.history.")]) for c in i18n_lang_codes(ROOT)}))

# cleanup: the sessions and the workers of this file
i18n.set_language("en")
ST.SSHTerminalThread = _ORIG_THREAD_CLS
for _worker_x in (_worker, _worker2, _worker3):
    try:
        _worker_x.shutdown(wait_ms=2000)
    except Exception:   # noqa: BLE001 — teardown robustness
        pass
for _page_x in (page, pane):
    try:
        # The workers below are stopped EXPLICITLY and were attached to the page by hand (a
        # test-only shortcut — the real path is `_ensure_sftp()`), so the page is detached
        # before its shutdown: it has nothing to stop and no slots to unbind.
        _page_x._sftp_worker = None
        _page_x.shutdown()
    except Exception:   # noqa: BLE001 — teardown robustness
        pass
finish()
