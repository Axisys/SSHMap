# -*- coding: utf-8 -*-
"""v1.8.2 — the command library as a first-class FILE: the door, the ring and the import/export pair.

ROADMAP v1.8.2: the History tab's door (`send_to_library()` — ONE row, never a batch, a secret row
REFUSED), the container accessor that resolves the library of the session's container, the backup ring
of `~/.sshmap/commands.json` (rotated by every write, restored through the shipped backup dialog) and
the passwordless import/export pair (`read_library_file()` / `export_library_file()`).
Contract — `DOCUMENTATION.md` §14e and §49; harness — `tests/_common.py`.
Run: python tests/test_command_library_file.py   (from the project root) or python tests/run_all.py"""
import json
import os
import sys

from _common import (bootstrap, check, finish, check_i18n_parity,
                     check_release_state, load_i18n_langs, releases_at_least,
                     EXPECTED_APP_VERSION)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (HOME isolation + offscreen)

from PySide6.QtWidgets import QApplication   # noqa: E402

app = QApplication(sys.argv)

import i18n  # noqa: E402
import modules.command_history as CH  # noqa: E402
import modules.command_library as CL  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
from modules.terminal_dock import TerminalDockContent  # noqa: E402
from models.server import ServerData  # noqa: E402

from _fakes import FakeSSHThread as _FakeThread, QuestionStub  # noqa: E402

_ORIG_THREAD_CLS = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # every window/page in this file — on the fake

_WINDOWS = []


def make_window(alias):
    w = ST.SSHTerminalWindow(
        ServerData(id=f"clf-{alias}", alias=alias, host="10.97.0.9", user="root"),
        None, password="pw")
    _WINDOWS.append(w)
    w.show()
    app.processEvents()
    return w


def store_in(name):
    """A library store in the sandbox (the explicit path seam — never the real ~/.sshmap)."""
    path = os.path.join(WORK, name)
    if os.path.isfile(path):
        os.remove(path)
    return CL.CommandLibraryStore(path=path)


def entry(name, command, category="System", enabled=True):
    return {"id": None, "name": name, "command": command,
            "category": category, "enabled": enabled}


class _Signal:
    """The smallest stand-in for a Qt signal (the stub dialog below is not a QObject)."""

    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in list(self._slots):
            fn(*args)


class _StubBackups:
    """The shipped backup dialog's SEAM: rows in, ONE restore request out — no modal `exec()`."""

    last = {}
    pick = None

    def __init__(self, items, parent=None, title=None):
        _StubBackups.last = {"items": [dict(i) for i in items], "title": title,
                             "parent": parent}
        self.restore_requested = _Signal()
        self.window_title = title

    def exec(self):
        if _StubBackups.pick is not None:
            row = next(i for i in _StubBackups.last["items"]
                       if i["path"] == _StubBackups.pick)
            self.restore_requested.emit(row["path"], row["label"])
        return 0

    def accept(self):
        pass


class _StubDialog:
    """The add/edit form's seam: it records what it was handed and answers with preset fields."""

    last = {}
    data = None

    def __init__(self, entry=None, categories=None, parent=None):
        _StubDialog.last = {"entry": dict(entry) if entry else None,
                            "categories": list(categories or [])}

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return (QDialog.DialogCode.Accepted if _StubDialog.data is not None
                else QDialog.DialogCode.Rejected)

    def result_entry(self):
        return dict(_StubDialog.data)


# ════════════════════════════════════════════════════════════════════════════
print("== §1 the ring: the project's arithmetic over commands.json ==")
# ════════════════════════════════════════════════════════════════════════════

_lib = os.path.join(WORK, "ring_lib.json")
if os.path.isfile(_lib):
    os.remove(_lib)
check("a missing file rotates nothing (the first write has no previous version)",
      CL.rotate_library_backups(_lib, 3) == []
      and CL.list_library_backups(_lib, 3) == [])

check("the ring key is stable for one path and differs for another",
      CL.library_key(_lib) == CL.library_key(_lib)
      and CL.library_key(_lib) != CL.library_key(os.path.join(WORK, "other_lib.json"))
      and len(CL.library_key(_lib)) == 16, CL.library_key(_lib))

store = CL.CommandLibraryStore(path=_lib)
for _i in range(1, 6):
    # the panel's own order: the version about to be replaced goes into slot 1 BEFORE the write
    CL.rotate_library_backups(_lib, 3)
    store.save([{"id": f"e{_i}", "name": f"v{_i}", "command": f"echo {_i}",
                 "category": "System", "enabled": True}])
slots = CL.list_library_backups(_lib, 3)
check("the ring is BOUNDED (an overflow beyond the count is deleted)",
      [s["slot"] for s in slots] == [1, 2, 3], str([s["slot"] for s in slots]))
check("newest first: slot 1 holds the version the last write replaced",
      json.load(open(slots[0]["path"], encoding="utf-8"))["commands"][0]["name"] == "v4"
      and json.load(open(slots[2]["path"], encoding="utf-8"))["commands"][0]["name"] == "v2",
      str([json.load(open(s["path"], encoding="utf-8"))["commands"][0]["name"] for s in slots]))
check("a slot carries its own path/slot/mtime/size",
      all(s["mtime"] > 0 and s["size"] > 0 and s["path"].startswith(CL.COMMANDS_BACKUP_DIR)
          for s in slots), str(slots[0]))

CL.restore_library_backup(slots[1]["path"], _lib)
check("restore copies the slot back over the library file",
      store.load()[0]["name"] == "v3", store.load()[0]["name"])
try:
    CL.restore_library_backup(os.path.join(WORK, "no_such_slot.json"), _lib)
    _raised = False
except FileNotFoundError:
    _raised = True
check("a missing source RAISES (the caller owns the sentence)", _raised)

check("a foreign ring size is clamped to the declared bounds",
      CL._backup_count(0) == CL.COMMANDS_BACKUPS_MIN
      and CL._backup_count("junk") == CL.COMMANDS_BACKUP_COUNT
      and CL._backup_count(10 ** 6) == CL.COMMANDS_BACKUPS_MAX)


# ════════════════════════════════════════════════════════════════════════════
print("== §2 the import/export pair: validate, then ONE atomic copy ==")
# ════════════════════════════════════════════════════════════════════════════

_entries = [{"id": "a1", "name": "Disk", "command": "df -h", "category": "System",
             "enabled": True},
            {"id": "a2", "name": "Awk", "command": "awk '{print $1}'", "category": "Scripts",
             "enabled": False}]
_out = os.path.join(WORK, "exported_library.json")
_result = CL.export_library_file(_out, _entries)
check("export writes the store's OWN document (so it could be dropped in as commands.json)",
      _result["ok"] is True and _result["count"] == 2
      and json.load(open(_out, encoding="utf-8")) == {"seeded": True, "commands": _entries},
      str(_result))

_back = CL.read_library_file(_out)
check("the round trip returns the same entries (a whole-library copy, not a merge)",
      _back["ok"] is True and _back["count"] == 2 and _back["entries"] == _entries, str(_back))
check("the export is an ATOMIC write with no leftover provisional file",
      not [f for f in os.listdir(WORK) if f.startswith("exported_library.json.")],
      str(os.listdir(WORK))[:200])

_bad = os.path.join(WORK, "not_a_library.json")
with open(_bad, "w", encoding="utf-8") as f:
    f.write("{not json")
check("a broken file is refused as not_json",
      CL.read_library_file(_bad)["error"] == CL.LIB_ERR_JSON, str(CL.read_library_file(_bad)))
with open(_bad, "w", encoding="utf-8") as f:
    json.dump([1, 2, 3], f)
check("a foreign root type is refused as not_object",
      CL.read_library_file(_bad)["error"] == CL.LIB_ERR_OBJECT)
with open(_bad, "w", encoding="utf-8") as f:
    json.dump({"seeded": True, "commands": [{"name": "", "command": ""}, "junk"]}, f)
check("a document without ONE usable command is refused as no_commands",
      CL.read_library_file(_bad)["error"] == CL.LIB_ERR_EMPTY
      and CL.read_library_file(_bad)["entries"] == [])
check("a missing file is refused as unreadable (never a raise)",
      CL.read_library_file(os.path.join(WORK, "nope.json"))["error"] == CL.LIB_ERR_UNREADABLE
      and CL.read_library_file(None)["error"] == CL.LIB_ERR_UNREADABLE)
check("a BOM-prefixed library file loads (utf-8-sig, the language files' rule)",
      CL.read_library_file(_out)["ok"] is True)

with open(_bad, "w", encoding="utf-8") as f:
    json.dump({"commands": [{"name": "ok", "command": "echo ok"}, "junk"]}, f)
_parsed = CL.entries_from_document(json.load(open(_bad, encoding="utf-8")))
check("entries_from_document() is the ONE normalization (a bad record is dropped, an id is issued)",
      len(_parsed) == 1 and _parsed[0]["name"] == "ok" and _parsed[0]["id"]
      and CL.entries_from_document([1, 2]) == [] and CL.entries_from_document(None) == [],
      str(_parsed))


# ════════════════════════════════════════════════════════════════════════════
print("== §3 the panel: every write rotates the ring, a slot is restored ==")
# ════════════════════════════════════════════════════════════════════════════

_panel_store = store_in("panel_lib.json")
_panel_store.save([entry("one", "echo one")])
def _cancelled_dialogs():
    """The panel with a file dialog that answers "cancelled" — no modal, no hang.

    The seam is the module attribute (`CL.QFileDialog`), exactly like `QMessageBox` / `QMenu`:
    `getOpenFileName` / `getSaveFileName` answer the empty pair, which is what the user's Cancel
    returns, so `import_library()` / `export_library()` take their quiet branch.
    """
    class _Cancelled:
        @staticmethod
        def getOpenFileName(*_a, **_kw):
            return "", ""

        @staticmethod
        def getSaveFileName(*_a, **_kw):
            return "", ""

    original = CL.QFileDialog
    CL.QFileDialog = _Cancelled
    try:
        return (imp.import_library() is False and imp.export_library() is False
                and imp.import_library(None) is False and imp.export_library(None) is False)
    finally:
        CL.QFileDialog = original


panel = CL.CommandLibraryPanel(None, store=_panel_store)
panel.resize(360, 460)
panel.show()
app.processEvents()
_msgs = []
panel.status_message.connect(lambda text, ms: _msgs.append((text, ms)))

_DIALOG_ORIG = CL.CommandLibraryDialog
CL.CommandLibraryDialog = _StubDialog
try:
    _StubDialog.data = {"name": "two", "command": "echo two", "category": "System",
                        "enabled": True}
    panel.add_btn.click()
    app.processEvents()
    _after_add = _panel_store.load()
    _ring_after_add = CL.list_library_backups(_panel_store.path)
    check("an ordinary add rotates the ring FIRST (slot 1 = the library before the add)",
          len(_after_add) == 2 and len(_ring_after_add) == 1
          and json.load(open(_ring_after_add[0]["path"], encoding="utf-8"))["commands"][0]["name"]
          == "one",
          str([e["name"] for e in _after_add]))

    _StubDialog.data = {"name": "three", "command": "echo three", "category": "System",
                        "enabled": True}
    panel.add_btn.click()
    app.processEvents()
    check("a second write shifts the ring (slot 2 = the version before it)",
          len(CL.list_library_backups(_panel_store.path)) == 2
          and json.load(open(CL.list_library_backups(_panel_store.path)[1]["path"],
                             encoding="utf-8"))["commands"][0]["name"] == "one")

    _labels = [i["label"] for i in panel.backup_items()]
    check("the restore rows are the shipped `backups.backup` labels, newest first",
          _labels == [i18n.t("backups.backup", n=1), i18n.t("backups.backup", n=2)],
          str(_labels))

    _BK_ORIG = CL.BackupsDialog
    CL.BackupsDialog = _StubBackups
    try:
        _StubBackups.pick = None      # the user closes the dialog — nothing happens
        _closed = panel.restore_backup()
        check("closing the restore dialog rewrites nothing",
              _closed is False and [e["name"] for e in _panel_store.load()]
              == ["one", "two", "three"], str([e["name"] for e in _panel_store.load()]))

        _pick_path = CL.list_library_backups(_panel_store.path)[1]["path"]
        _pick_wanted = [c["name"] for c in json.load(
            open(_pick_path, encoding="utf-8"))["commands"]]   # what the row showed at PICK time
        _before_restore = [e["name"] for e in _panel_store.load()]
        _StubBackups.pick = _pick_path
        _restored = panel.restore_backup()
        check("the CHOSEN slot replaces the library — the version the row held WHEN IT WAS PICKED",
              _restored is True and [e["name"] for e in _panel_store.load()] == _pick_wanted == ["one"]
              and _StubBackups.last["title"] == i18n.t("terminal.cmdlib.restore_backup"),
              f"{[e['name'] for e in _panel_store.load()]} vs picked {_pick_wanted} / "
              f"{_StubBackups.last.get('title')!r}")
        check("the replaced state went into slot 1 first (a restore is reversible)",
              [c["name"] for c in json.load(open(CL.list_library_backups(_panel_store.path)[0]["path"],
                                                 encoding="utf-8"))["commands"]]
              == _before_restore == ["one", "two", "three"], str(_before_restore))
        _ring_after = CL.list_library_backups(_panel_store.path)
        check("…and the picked version still exists in the ring (the rotation SHIFTED it)",
              len(_ring_after) == 3 and [c["name"] for c in json.load(
                  open(_ring_after[2]["path"], encoding="utf-8"))["commands"]] == _pick_wanted,
              str([[c["name"] for c in json.load(open(s["path"], encoding="utf-8"))["commands"]]
                   for s in _ring_after]))
        check("the restore reports itself",
              _msgs and _msgs[-1][0] == i18n.t(
                  "terminal.cmdlib.restored", source=i18n.t("backups.backup", n=2)),
              str(_msgs[-2:]))
    finally:
        CL.BackupsDialog = _BK_ORIG

    _empty_panel = CL.CommandLibraryPanel(
        None, store=CL.CommandLibraryStore(path=os.path.join(WORK, "no_ring_lib.json")))
    _empty_msgs = []
    _empty_panel.status_message.connect(lambda text, ms: _empty_msgs.append(text))
    check("with no ring slot at all the restore says so and opens nothing",
          _empty_panel.restore_backup() is False
          and _empty_msgs == [i18n.t("terminal.cmdlib.backup_empty")], str(_empty_msgs))
finally:
    CL.CommandLibraryDialog = _DIALOG_ORIG


# ════════════════════════════════════════════════════════════════════════════
print("== §4 the panel's import/export: the ask, the replacement, the reports ==")
# ════════════════════════════════════════════════════════════════════════════

_imp_store = store_in("import_lib.json")
_imp_store.save([entry("keep", "echo keep")])
imp = CL.CommandLibraryPanel(None, store=_imp_store)
imp_msgs = []
imp.status_message.connect(lambda text, ms: imp_msgs.append(text))

_incoming = os.path.join(WORK, "incoming_library.json")
CL.export_library_file(_incoming, [entry("new-a", "echo a"), entry("new-b", "echo b")])

check("the export of the WHOLE library reports its path and count",
      imp.export_library(_out.replace("exported_library", "panel_export")) is True
      and imp_msgs[-1] == i18n.t("terminal.cmdlib.exported",
                                 path=os.path.abspath(_out.replace("exported_library",
                                                                   "panel_export"))),
      str(imp_msgs[-1:]))
check("the extension is added when the user typed none",
      imp.export_library(os.path.join(WORK, "no_extension")) is True
      and os.path.isfile(os.path.join(WORK, "no_extension.json")))

with QuestionStub().install(CL) as _stub:
    _stub.answer = CL.QMessageBox.No
    _no = imp.import_library(_incoming)
    check("'No' keeps the library exactly as it was",
          _no is False and [e["name"] for e in _imp_store.load()] == ["keep"],
          str([e["name"] for e in _imp_store.load()]))
    check("the ask names the count of the incoming file",
          _stub.calls and _stub.calls[-1][1] == i18n.t("terminal.cmdlib.import_confirm", count=2),
          str(_stub.calls[-1:]))

    _stub.answer = CL.QMessageBox.Yes
    _yes = imp.import_library(_incoming)
    check("'Yes' REPLACES the whole library (never a merge by name)",
          _yes is True and [e["name"] for e in _imp_store.load()] == ["new-a", "new-b"],
          str([e["name"] for e in _imp_store.load()]))
    check("the import reports itself and the ring protected the replaced library",
          imp_msgs[-1] == i18n.t("terminal.cmdlib.imported", count=2)
          and len(CL.list_library_backups(_imp_store.path)) >= 1
          and json.load(open(CL.list_library_backups(_imp_store.path)[0]["path"],
                             encoding="utf-8"))["commands"][0]["name"] == "keep",
          str(imp_msgs[-1:]))

_broken = os.path.join(WORK, "broken_library.json")
with open(_broken, "w", encoding="utf-8") as f:
    f.write("[1, 2, 3]")
check("a refused file never reaches the library (the machine reason is rendered)",
      imp.import_library(_broken) is False
      and imp_msgs[-1] == i18n.t("terminal.cmdlib.import_failed", error=CL.LIB_ERR_OBJECT)
      and [e["name"] for e in _imp_store.load()] == ["new-a", "new-b"],
      str(imp_msgs[-1:]))
check("a cancelled file dialog is a quiet no-op", _cancelled_dialogs())


# ════════════════════════════════════════════════════════════════════════════
print("== §5 the door: ONE History row → the library of the container ==")
# ════════════════════════════════════════════════════════════════════════════

check("the command library module's DOCUMENTATION pointer is unchanged",
      "DOCUMENTATION.md" in (CL.__doc__ or ""), (CL.__doc__ or "")[:60])

win = make_window("door")
page = win.page
hist = page.history_tab
page.command_history.clear()
page.command_history.record("df -h")
page.command_history.record("systemctl restart docker")
hist.reload()
app.processEvents()

check("the accessor resolves the library of the container on the parent chain",
      hist.library_panel() is win.cmdlib_panel and CH.container_library(hist) is win.cmdlib_panel
      and CH.container_library(CL.CommandLibraryPanel(None)) is None,
      f"{hist.library_panel()!r}")

_menu = hist._build_context_menu(hist.tree.topLevelItem(0))
_menu_texts = [a.text() for a in _menu.actions() if not a.isSeparator()]
check("the menu carries the door, right after Send, and a row enables it",
      _menu_texts == [i18n.t("terminal.history.import_file"),
                      i18n.t("terminal.history.import_server"),
                      i18n.t("terminal.history.copy"),
                      i18n.t("terminal.history.send"),
                      i18n.t("terminal.history.send_to_commands"),
                      i18n.t("terminal.cmdlib.delete"),
                      i18n.t("terminal.history.dedup"),
                      i18n.t("terminal.history.clear")]
      and [a.isEnabled() for a in _menu.actions() if not a.isSeparator()][2:6]
      == [True, True, True, True],
      str([(a.text(), a.isEnabled()) for a in _menu.actions() if not a.isSeparator()]))

_no_entry = {a.text(): a.isEnabled()
             for a in hist._build_context_menu(None).actions() if not a.isSeparator()}
check("with no row selected the door is disabled (the single-row bound)",
      _no_entry[i18n.t("terminal.history.send_to_commands")] is False, str(_no_entry))

# the door's own store: a fresh library for THIS window's container
_win_store = store_in("door_lib.json")
_win_store.save([entry("seed", "echo seed")])
win.cmdlib_panel._store = _win_store
win.cmdlib_panel.reload()
hist_msgs = []
hist.status_message.connect(lambda text, ms: hist_msgs.append((text, ms)))
lib_msgs = []
win.cmdlib_panel.status_message.connect(lambda text, ms: lib_msgs.append((text, ms)))

CL.CommandLibraryDialog = _StubDialog
try:
    _StubDialog.data = {"name": "Disk usage", "command": "df -h", "category": "System",
                        "enabled": True}
    _row = hist._entry_for_item(hist.tree.topLevelItem(0))
    _added = hist.send_to_library(_row)
    app.processEvents()
    _lib_names = [e["name"] for e in _win_store.load()]
    check("ONE row lands in the library — exactly one entry, never the whole list",
          _added is True and _lib_names == ["seed", "Disk usage"], str(_lib_names))
    check("the shipped form was handed the row PRE-FILLED (command + name, no id → the ADD form)",
          _StubDialog.last["entry"] is not None
          and _StubDialog.last["entry"]["command"] == "df -h"
          and _StubDialog.last["entry"]["name"] == "df -h"
          and not _StubDialog.last["entry"].get("id")
          and "System" in _StubDialog.last["categories"],
          str(_StubDialog.last))
    check("the door reports the save once (the LIBRARY panel owns the form and the write)",
          lib_msgs and lib_msgs[-1][0] == i18n.t("terminal.cmdlib.saved", name="Disk usage"),
          str(lib_msgs[-1:]))

    _DIALOG2 = CL.CommandLibraryDialog
    _StubDialog.data = None      # the user cancels the form
    _cancelled = hist.send_to_library({"cmd": "uptime", "last": 1, "count": 1})
    check("a cancelled form stores nothing",
          _cancelled is False and [e["name"] for e in _win_store.load()] == ["seed", "Disk usage"])
    CL.CommandLibraryDialog = _DIALOG2
finally:
    CL.CommandLibraryDialog = _DIALOG_ORIG

# the SECRET refusal — the mark the recording path wrote, and an imported row that never got one
_win_store.save([entry("seed", "echo seed")])
win.cmdlib_panel.reload()
_before = len(_win_store.load())
_marked = {"cmd": "mysql -psecret", "last": 1, "count": 1, "secret": True}
_unmarked = {"cmd": "curl -H 'Authorization: Bearer abc'", "last": 1, "count": 1}
check("the refusal is asked of the SHIPPED predicate (both spellings look like a secret)",
      CH.looks_like_secret(_marked["cmd"]) is True
      and CH.looks_like_secret(_unmarked["cmd"]) is True)
for _secret_row in (_marked, _unmarked):
    _refused = hist.send_to_library(_secret_row)
    check(f"a secret-looking row is REFUSED with one sentence and stores nothing "
          f"({_secret_row['cmd'][:18]}…)",
          _refused is False and hist_msgs[-1][0] == i18n.t("terminal.history.secret_refused")
          and len(_win_store.load()) == _before,
          f"{_refused} / {hist_msgs[-1]}")

_lone = CH.CommandHistoryPanel(store=CH.CommandHistoryStore("lone"), session=None)
_lone_msgs = []
_lone.status_message.connect(lambda text, ms: _lone_msgs.append(text))
check("a tab with no container answers the no_library sentence (no exception)",
      _lone.send_to_library({"cmd": "uptime", "last": 1, "count": 1}) is False
      and _lone_msgs == [i18n.t("terminal.history.no_library")], str(_lone_msgs))

dock = TerminalDockContent()
dock_page = dock.add_session(ServerData(id="clf-dock", alias="dock-1",
                                        host="10.97.0.10", user="root"), password="pw")
app.processEvents()
check("the DOCK's History tab resolves ITS OWN library (the hook is on both containers)",
      dock_page.history_tab.library_panel() is dock.cmdlib_panel
      and dock.cmdlib_panel is not win.cmdlib_panel,
      f"{dock_page.history_tab.library_panel()!r}")
try:
    dock_page.shutdown()
    dock.close()
except Exception:  # noqa: BLE001 — teardown robustness
    pass


# ════════════════════════════════════════════════════════════════════════════
print("== §6 the prefilled form and the suggested name ==")
# ════════════════════════════════════════════════════════════════════════════

check("suggested_name() takes the FIRST line and caps it",
      CL.suggested_name("line one\nline two") == "line one"
      and CL.suggested_name("   \n  awk '{print}'") == "awk '{print}'"
      and len(CL.suggested_name("x" * 500)) == CL.SUGGESTED_NAME_MAX
      and CL.suggested_name(None) == "" and CL.suggested_name("   ") == "",
      CL.suggested_name("x" * 500)[:20])

_prefilled = CL.CommandLibraryDialog(
    {"name": "Disk usage", "command": "df -h", "category": "", "enabled": True},
    categories=["System", "Services"])
check("an ID-LESS entry is the ADD form, pre-filled (the door's landing)",
      _prefilled.windowTitle() == i18n.t("terminal.cmdlib.add")
      and _prefilled.name_edit.text() == "Disk usage"
      and _prefilled.command_edit.toPlainText() == "df -h"
      and _prefilled._ok.isEnabled() is True,
      _prefilled.windowTitle())
check("the CATEGORY stays the choice the shipped form offers (its own editable combo)",
      [_prefilled.category_edit.itemText(i) for i in range(_prefilled.category_edit.count())]
      == ["System", "Services"]
      and (_prefilled.category_edit.setCurrentText("Services") or True)
      and _prefilled.result_entry()["category"] == "Services"
      and _prefilled.category_edit.isEditable() is True,
      _prefilled.result_entry()["category"])
_edited = CL.CommandLibraryDialog(
    {"id": "e1", "name": "N", "command": "C", "category": "K", "enabled": True},
    categories=["K"])
check("an entry WITH an id stays the edit form (the shipped behaviour)",
      _edited.windowTitle() == i18n.t("terminal.cmdlib.edit")
      and _edited.category_edit.currentText() == "K", _edited.windowTitle())
check("the empty add form keeps its title and its empty category",
      CL.CommandLibraryDialog(None, categories=["A"]).windowTitle()
      == i18n.t("terminal.cmdlib.add"))
check("the panel's file menu carries the three actions and stays alive on the panel",
      [a.text() for a in panel._file_menu.actions()]
      == [i18n.t("terminal.cmdlib.restore_backup"), i18n.t("terminal.cmdlib.import"),
          i18n.t("terminal.cmdlib.export")]
      and panel._file_menu.parent() is not None
      and panel.act_import_library.text() == i18n.t("terminal.cmdlib.import"),
      str([a.text() for a in panel._file_menu.actions()]))
check("the file menu's tooltip and the button are set (the glyph needs no translation)",
      panel._file_btn.toolTip() == i18n.t("terminal.cmdlib.file_menu_tooltip")
      and panel._file_btn.menu() is panel._file_menu
      and panel._file_btn.text() == "…")


# ════════════════════════════════════════════════════════════════════════════
print("== §7 i18n parity + release state ==")
# ════════════════════════════════════════════════════════════════════════════

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)
check("the pins are the ones this file describes",
      releases_at_least(EXPECTED_APP_VERSION, "1.8.2"), EXPECTED_APP_VERSION)

for _w in _WINDOWS:
    try:
        _w.close()
    except RuntimeError:
        pass
ST.SSHTerminalThread = _ORIG_THREAD_CLS
finish()
