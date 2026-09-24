# -*- coding: utf-8 -*-
"""v1.3 — "Terminal macros": a command/script library in the terminal panel (ROADMAP v1.3).

The thematic test of the release v1.3 (the "new thematic file" convention): offscreen,
ALL without the network — the fake threads with the same API as SSHTerminalThread (the test seam
ST.SSHTerminalThread), the explicit store paths under WORK, the QMessageBox/dialog — the monkeypatch
of the attributes of the module command_library.

§1 CommandLibraryStore: the first run — 5 the seeds + seeded:true; the round-trip save/load;
   a broken file → an EMPTY library without exceptions and WITHOUT the reseed; a foreign top
   type (an array) → []; the invalid records are dropped one by one; after the removal of all
   commands the file is not reseeded.

§2 build_macro_payload (a pure function): the single-line — raw + \n; the multi-line —
   the bracketed-paste wrapper with a guaranteed terminating \n (without a double); the CRLF/CR
   is normalized to \n; the empty text → b"".

§3 send_macro (widget/page): the exact bytes into the channel (the single-line, the multi-line);
   a dead channel (closed=True) → False + 0 bytes; terminal_thread=None → False.

§4 The container window: the central widget — the QSplitter [cmdlib_panel | session_tabs],
   setCollapsible(False) on both sides; the collapse by the button → the config true; a new
   window starts collapsed by the config; the click on the strip → expanded + false;
   persist=False does not write the config.

§5 The container dock: the same structure; ONE key ui_cmdlib_collapsed shared with the window
   (the dock honors the state written by the "window").

§6 The send via the panel: the double click — the exact bytes + the status sent_to({alias});
   Enter — the same; a disabled record → 0 bytes and silence; no the active session
   (the panel without tabs / an empty QTabWidget) → the status no_active_session without exceptions;
   a dead channel → no_active_session.

§7 The search: by the name and the text of the command, case-insensitive; a category without matches
   is hidden; "no matches" — the info label; an empty library — the info label.

§8 The CRUD: the add/edit via the dialog (the stub exec), the duplicate/toggle/copy/delete — the actions
   of the context menu (the test seam _build_context_menu without exec()); the delete with
   the confirmation Yes/No (the monkeypatch of the QMessageBox); the OK of the dialog is disabled until there is no
   name+command; by a category all the actions are disabled.

§9 The i18n parity (446 = 427 + 19: terminal.cmdlib.*) + the release state (the pin _common.py).

Run:  python tests/test_command_library.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys

from _common import (bootstrap, check, finish, load_i18n_langs, check_i18n_parity,
                     check_release_state, cfg_path, merge_cfg, clear_cfg, read_cfg)

ROOT, WORK = bootstrap()  # BEFORE the app module imports (the HOME isolation and faulthandler inside)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QSplitter, QTabWidget

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
import modules.command_library as CL
import modules.terminal_widget as TW
from modules.terminal_dock import TerminalDockContent
from modules.terminal_screen import TerminalScreen
from models.server import ServerData


# ════════════════════════════════════════════════
# The harness: fake threads (the same API as SSHTerminalThread) — _fakes.py
# ════════════════════════════════════════════════

from _fakes import FakeSSHThread as _FakeThread


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # all the pages/windows in this file — on the fake

_windows = []
def _commands_path():
    return os.path.join(os.path.expanduser("~"), ".sshmap", "commands.json")


def clear_commands():
    try:
        os.remove(_commands_path())
    except OSError:
        pass


def make_window(alias, host="10.97.0.1"):
    w = ST.SSHTerminalWindow(
        ServerData(id=f"cl-{alias}", alias=alias, host=host, user="root"),
        None, password="pw")
    _windows.append(w)
    w.show()
    app.processEvents()
    return w


def find_child(tree, name):
    """The command record by name (only the visible ones)."""
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if top.isHidden():
            continue
        for j in range(top.childCount()):
            ch = top.child(j)
            if ch.text(0) == name and not ch.isHidden():
                return ch
    return None


def double_click_item(tree, item):
    """The double click by the coordinates of the record.

    NOT QTest.mouseDClick: in PySide6 6.11 offscreen its synthetic MouseDoubleClick
    is NOT accepted by the item-views ("Mouse event "MouseDClick" not accepted" — verified
    on the bare QTreeWidget), and the manual press/release/MouseButtonDblClick/release through
    qApp.sendEvent(viewport, …) works stock (itemDoubleClicked is emitted)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    pos = tree.visualItemRect(item).center()

    def _ev(ty, btn):
        return QMouseEvent(ty, pos, pos, Qt.MouseButton.LeftButton, btn,
                           Qt.KeyboardModifier.NoModifier)

    app.sendEvent(tree.viewport(), _ev(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
    app.sendEvent(tree.viewport(), _ev(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))
    app.sendEvent(tree.viewport(), _ev(QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton))
    app.sendEvent(tree.viewport(), _ev(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))


def act_by_text(menu, label):
    for a in menu.actions():
        if a.text() == label:
            return a
    return None


def visible_children(tree):
    out = []
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if top.isHidden():
            continue
        for j in range(top.childCount()):
            ch = top.child(j)
            if not ch.isHidden():
                out.append(ch.text(0))
    return out


# ════════════════════════════════════════════════
# 1. CommandLibraryStore: seeding, round-trip, corrupted data
# ════════════════════════════════════════════════
print("== 1. store: seed / round-trip / corruption ==")

s1 = os.path.join(WORK, "cmds_seed.json")
if os.path.isfile(s1):
    os.remove(s1)
st1 = CL.CommandLibraryStore(path=s1)
lib = st1.load()
check("the first run: 5 seeds", len(lib) == 5, str(len(lib)))
check("the seeds: the fields id/name/command/category/enabled",
      all(set(e) == {"id", "name", "command", "category", "enabled"} for e in lib))
check("the seeds are enabled + unique ids",
      all(e["enabled"] is True for e in lib) and len({e["id"] for e in lib}) == 5)
with open(s1, encoding="utf-8") as f:
    doc = json.load(f)
check("the document: seeded=true + commands[]",
      doc.get("seeded") is True and isinstance(doc.get("commands"), list))
check("the seeds include a multi-line script (awk)", any("\n" in e["command"] for e in lib))

# round-trip
lib2 = st1.load()
added = {"id": "rt-1", "name": "RT", "command": "echo rt", "category": "RT", "enabled": False}
st1.save(lib2 + [added])
lib3 = CL.CommandLibraryStore(path=s1).load()
check("round-trip save→load (including the disabled record)",
      len(lib3) == len(lib2) + 1 and lib3[-1]["name"] == "RT" and lib3[-1]["enabled"] is False)

# a corrupt file → empty, no exceptions, no reseeding
with open(s1, "w", encoding="utf-8") as f:
    f.write("not json {{{")
try:
    lib4 = CL.CommandLibraryStore(path=s1).load()
    ok_corrupt = True
except Exception:   # noqa: BLE001
    ok_corrupt = False
check("a corrupt file → an empty library without exceptions", ok_corrupt and lib4 == [])
with open(s1, encoding="utf-8") as f:
    check("a corrupt file is not reseeded (the content is kept)", f.read() == "not json {{{")

# a foreign top-level type
with open(s1, "w", encoding="utf-8") as f:
    json.dump([1, 2, 3], f)
check("a foreign top-level type (an array) → []", CL.CommandLibraryStore(path=s1).load() == [])

# invalid records are discarded one by one
with open(s1, "w", encoding="utf-8") as f:
    json.dump({"seeded": True, "commands": [
        {"name": "good", "command": "echo g"},   # without an id → it is generated
        {"name": "", "command": "x"},            # an empty name → discard
        "junk",                                  # not a dict → discard
        {"name": "no-cmd"},                      # no command → discard
    ]}, f)
lib5 = CL.CommandLibraryStore(path=s1).load()
check("the invalid records are discarded ('good' is left, the id is generated)",
      len(lib5) == 1 and lib5[0]["name"] == "good" and bool(lib5[0]["id"]), str(lib5))

# after deleting all the commands — the file is not reseeded (it exists)
check("save([]) → the document is written", CL.CommandLibraryStore(path=s1).save([]) is True)
lib6 = CL.CommandLibraryStore(path=s1).load()
with open(s1, encoding="utf-8") as f:
    doc6 = json.load(f)
check("an empty library is not reseeded (the file exists)", lib6 == [] and doc6["commands"] == [])


# ════════════════════════════════════════════════
# 2. build_macro_payload: single-line / multi-line / normalization
# ════════════════════════════════════════════════
print("== 2. build_macro_payload ==")

check("a single line → raw + \\n", TW.build_macro_payload("df -h") == b"df -h\n")
check("multi-line → bracketed paste + a trailing \\n",
      TW.build_macro_payload("a\nb") == b"\x1b[200~a\nb\n\x1b[201~")
check("CRLF is normalized to \\n (multi-line)",
      TW.build_macro_payload("a\r\nb") == b"\x1b[200~a\nb\n\x1b[201~")
check("CR is normalized to \\n (multi-line)",
      TW.build_macro_payload("a\rb") == b"\x1b[200~a\nb\n\x1b[201~")
check("the trailing \\n is not doubled",
      TW.build_macro_payload("a\nb\n") == b"\x1b[200~a\nb\n\x1b[201~")
check("empty text → b\"\"", TW.build_macro_payload("") == b"")
check("whitespace only → b\"\"", TW.build_macro_payload("   \n  ") == b"")


# ════════════════════════════════════════════════
# 3. send_macro (widget/page): the exact bytes, a dead channel
# ════════════════════════════════════════════════
print("== 3. widget.send_macro: exact bytes / dead channel ==")

bw = TW.TerminalWidget(TerminalScreen(80, 24), None)
check("terminal_thread=None → False", bw.send_macro("df -h") is False)

clear_cfg()
clear_commands()
w3 = make_window("send3")
page3 = w3.page
ch3 = page3.terminal_thread.channel
ok1 = page3.widget.send_macro("df -h")
check("a single line: True + the exact bytes (df -h\\n)",
      ok1 is True and ch3.sent == [b"df -h\n"], repr(ch3.sent))
awk_entry = next(e for e in w3.cmdlib_panel._entries if e["name"] == "Sum column (awk)")
expected_awk = (b"\x1b[200~awk '{s+=$1} END {print \"total: \" s}' \\\n"
                b"    /var/log/nginx/access.log\n\x1b[201~")
ok2 = page3.widget.send_macro(awk_entry["command"])
check("multi-line: True + the bracketed-paste block (the exact bytes)",
      ok2 is True and ch3.sent[-1] == expected_awk, repr(ch3.sent[-1]))
ch3.closed = True
check("a dead channel (closed=True) → False + 0 bytes",
      page3.widget.send_macro("df -h") is False and len(ch3.sent) == 2)


# ════════════════════════════════════════════════
# 4. The container window: QSplitter [panel | tabs] + collapsing
# ════════════════════════════════════════════════
print("== 4. window container: QSplitter + collapse ==")

clear_cfg()
clear_commands()
wA = make_window("structA")
check("the window: the central widget is a QSplitter (v1.3)", isinstance(wA.centralWidget(), QSplitter))
spA = wA.centralWidget()
check("splitter: [cmdlib_panel | QSplitter(session_tabs | split_host)] (v1.3.3.5: the terminal split)",
      spA.widget(0) is wA.cmdlib_panel and spA.count() == 2
      and spA.widget(1) is wA._v_splitter
      and wA._v_splitter.widget(0) is wA.session_tabs
      and wA._v_splitter.widget(1) is wA.split_host)
check("setCollapsible(False) on both sides (the panel cannot be lost)",
      not spA.isCollapsible(0) and not spA.isCollapsible(1))
check("by default: the panel is expanded (no key; the strip is hidden, the body is visible)",
      wA.cmdlib_panel.is_collapsed() is False
      and not wA.cmdlib_panel._strip.isVisible() and wA.cmdlib_panel._body.isVisible())

wA.cmdlib_panel._collapse_btn.click()
app.processEvents()
check("a click on the button → collapsed (the strip is visible, the body is hidden)",
      wA.cmdlib_panel.is_collapsed() is True
      and wA.cmdlib_panel._strip.isVisible() and not wA.cmdlib_panel._body.isVisible())
check("the state is written to the config (ui_cmdlib_collapsed=true)",
      read_cfg({}).get("ui_cmdlib_collapsed") is True)

wB = make_window("structB")
check("a new window starts collapsed per the config", wB.cmdlib_panel.is_collapsed() is True)

QTest.mouseClick(wB.cmdlib_panel._strip, Qt.MouseButton.LeftButton)
app.processEvents()
check("a click on the strip → expanded", wB.cmdlib_panel.is_collapsed() is False)
check("the state is written to the config (ui_cmdlib_collapsed=false)",
      read_cfg({}).get("ui_cmdlib_collapsed") is False)

wA.cmdlib_panel.set_collapsed(True, persist=False)
check("set_collapsed(persist=False): the state is switched, the config is untouched",
      wA.cmdlib_panel.is_collapsed() is True and read_cfg({}).get("ui_cmdlib_collapsed") is False)
wA.cmdlib_panel.set_collapsed(False)   # return it (it will write false — as-is)


# ════════════════════════════════════════════════
# 5. The dock container: the same structure + a shared collapsing key
# ════════════════════════════════════════════════
print("== 5. dock container: structure + shared collapse key ==")

merge_cfg({"ui_cmdlib_collapsed": True})   # the state written by the "window"
dc = TerminalDockContent()
dc.resize(700, 400)
dc.show()
app.processEvents()
check("the dock: the splitter [cmdlib_panel | session_tabs] is in the layout",
      isinstance(dc.layout().itemAt(0).widget(), QSplitter))
spD = dc.layout().itemAt(0).widget()
check("the dock: splitter.widget(0)=panel, widget(1)=session_tabs",
      spD.widget(0) is dc.cmdlib_panel and spD.widget(1) is dc.session_tabs)
check("the dock: setCollapsible(False) on both sides",
      not spD.isCollapsible(0) and not spD.isCollapsible(1))
check("the dock: it honours the shared key (it starts collapsed)", dc.cmdlib_panel.is_collapsed() is True)

QTest.mouseClick(dc.cmdlib_panel._strip, Qt.MouseButton.LeftButton)
app.processEvents()
check("the dock: a click on the strip → expanded + the config is false",
      dc.cmdlib_panel.is_collapsed() is False and read_cfg({}).get("ui_cmdlib_collapsed") is False)
dc.cmdlib_panel._collapse_btn.click()
app.processEvents()
check("the dock: the button → collapsed + the config is true (the same key as the window)",
      dc.cmdlib_panel.is_collapsed() is True and read_cfg({}).get("ui_cmdlib_collapsed") is True)


# ════════════════════════════════════════════════
# 6. Sending via the panel: double click / Enter / disabled / no session
# ════════════════════════════════════════════════
print("== 6. panel send: dblclick / Enter / disabled / no session ==")

clear_cfg()
clear_commands()
wS = make_window("send")
panelS = wS.cmdlib_panel
pageS = wS.page
chS = pageS.terminal_thread.channel
msgs = []
panelS.status_message.connect(lambda text, ms: msgs.append((text, ms)))

item = find_child(panelS.tree, "Disk usage")
check("the seed 'Disk usage' is in the tree", item is not None)
double_click_item(panelS.tree, item)
app.processEvents()
check("a double click → the exact bytes (df -h\\n)", chS.sent == [b"df -h\n"], repr(chS.sent))
check("the status sent_to({alias}) + a timeout of 4000",
      bool(msgs) and msgs[-1] == (i18n.t("terminal.cmdlib.sent_to", alias="send"), 4000), str(msgs))

item_awk = find_child(panelS.tree, "Sum column (awk)")
double_click_item(panelS.tree, item_awk)
app.processEvents()
check("multi-line: the bracketed-paste block is in the channel", chS.sent[-1] == expected_awk, repr(chS.sent[-1]))

panelS.tree.setCurrentItem(find_child(panelS.tree, "Disk usage"))
QTest.keyClick(panelS.tree, Qt.Key.Key_Return)
app.processEvents()
check("Enter → the command is sent (the 3rd chunk)", len(chS.sent) == 3 and chS.sent[-1] == b"df -h\n",
      repr(chS.sent))

# a disabled record — silence + 0 bytes
item_d = find_child(panelS.tree, "Restart Docker")
menu = panelS._build_context_menu(item_d)
act_by_text(menu, i18n.t("terminal.cmdlib.toggle_enabled")).trigger()
app.processEvents()
check("toggle: 'Restart Docker' is disabled in the file",
      all(not e["enabled"] for e in panelS._entries if e["name"] == "Restart Docker"))
n_before = len(chS.sent)
item_d2 = find_child(panelS.tree, "Restart Docker")
double_click_item(panelS.tree, item_d2)
app.processEvents()
check("a disabled record: 0 bytes and silence (no new statuses)",
      len(chS.sent) == n_before and len(msgs) == 3, f"sent={len(chS.sent)} msgs={len(msgs)}")

# no active session: the panel without tabs / an empty QTabWidget — the status without exceptions
p_no = CL.CommandLibraryPanel(
    None, store=CL.CommandLibraryStore(path=os.path.join(WORK, "cmds_nosess.json")))
msgs_no = []
p_no.status_message.connect(lambda text, ms: msgs_no.append((text, ms)))
try:
    p_no.send_entry({"id": "x", "name": "n", "command": "c", "category": "", "enabled": True})
    ok_nosess = True
except Exception:   # noqa: BLE001
    ok_nosess = False
check("no tabs → no_active_session without exceptions",
      ok_nosess and msgs_no == [(i18n.t("terminal.cmdlib.no_active_session"), 4000)], str(msgs_no))

p_empty = CL.CommandLibraryPanel(
    QTabWidget(), store=CL.CommandLibraryStore(path=os.path.join(WORK, "cmds_nosess.json")))
msgs_e = []
p_empty.status_message.connect(lambda text, ms: msgs_e.append((text, ms)))
p_empty.send_entry({"id": "x", "name": "n", "command": "c", "category": "", "enabled": True})
check("an empty QTabWidget → no_active_session",
      msgs_e == [(i18n.t("terminal.cmdlib.no_active_session"), 4000)])

# a dead channel — the status without exceptions
chS.closed = True
item_dead = find_child(panelS.tree, "Disk usage")
double_click_item(panelS.tree, item_dead)
app.processEvents()
check("a dead channel: 0 bytes + no_active_session",
      len(chS.sent) == 3 and msgs[-1] == (i18n.t("terminal.cmdlib.no_active_session"), 4000),
      f"sent={len(chS.sent)} last={msgs[-1] if msgs else None}")


# ════════════════════════════════════════════════
# 7. Search: name/command, case-insensitive, info labels
# ════════════════════════════════════════════════
print("== 7. search filter + info labels ==")

s7 = os.path.join(WORK, "cmds_search.json")
if os.path.isfile(s7):
    os.remove(s7)
p7 = CL.CommandLibraryPanel(None, store=CL.CommandLibraryStore(path=s7))
p7.resize(320, 420)
p7.show()
app.processEvents()
check("the panel: the tree is built from the seeds (5 commands)", len(visible_children(p7.tree)) == 5,
      str(visible_children(p7.tree)))

p7.search.setText("docker")
app.processEvents()
check("a search by the name ('docker')", visible_children(p7.tree) == ["Restart Docker"],
      str(visible_children(p7.tree)))
p7.search.setText("DOCKER")
app.processEvents()
check("case-insensitive ('DOCKER')", visible_children(p7.tree) == ["Restart Docker"])
p7.search.setText("df -h")
app.processEvents()
check("a search by the command text ('df -h')", visible_children(p7.tree) == ["Disk usage"],
      str(visible_children(p7.tree)))
p7.search.setText("zzz_no_such")
app.processEvents()
check("no matches: nothing is visible + the no_matches info label",
      visible_children(p7.tree) == [] and p7.info_label.text() == i18n.t("terminal.cmdlib.no_matches"),
      p7.info_label.text())
p7.search.setText("")
app.processEvents()
check("a cleared search → all 5 are back", len(visible_children(p7.tree)) == 5)

# an empty library — the "empty" info label
s7b = os.path.join(WORK, "cmds_empty.json")
if os.path.isfile(s7b):
    os.remove(s7b)
CL.CommandLibraryStore(path=s7b).save([])   # the file exists, commands []
p7b = CL.CommandLibraryPanel(None, store=CL.CommandLibraryStore(path=s7b))
p7b.resize(320, 420)
p7b.show()
app.processEvents()
check("an empty library: an empty tree + the empty info label",
      p7b.tree.topLevelItemCount() == 0 and p7b.info_label.text() == i18n.t("terminal.cmdlib.empty"),
      p7b.info_label.text())


# ════════════════════════════════════════════════
# 8. CRUD: the dialog + the context menu actions
# ════════════════════════════════════════════════
print("== 8. CRUD: dialog + context menu actions ==")

s8 = os.path.join(WORK, "cmds_crud.json")
if os.path.isfile(s8):
    os.remove(s8)
store8 = CL.CommandLibraryStore(path=s8)
p8 = CL.CommandLibraryPanel(None, store=store8)
p8.resize(320, 420)
p8.show()
app.processEvents()

# the stub dialog (exec → Accepted with the preset fields; no modal)
_STUB = {"data": None}


class _StubDialog:
    last = {}

    def __init__(self, entry=None, categories=None, parent=None):
        _StubDialog.last = {"entry": entry, "categories": list(categories or [])}

    def exec(self):
        return (QDialog.DialogCode.Accepted if _STUB["data"] is not None
                else QDialog.DialogCode.Rejected)

    def result_entry(self):
        return dict(_STUB["data"])


_orig_dlg = CL.CommandLibraryDialog
CL.CommandLibraryDialog = _StubDialog
try:
    # ADD
    _STUB["data"] = {"name": "My Test Cmd", "command": "echo hello",
                     "category": "Custom", "enabled": True}
    p8.add_btn.click()
    app.processEvents()
    lib8 = store8.load()
    added = [e for e in lib8 if e["name"] == "My Test Cmd"]
    check("add: the record is written to the file (name/command/category/enabled)",
          len(added) == 1 and added[0]["command"] == "echo hello"
          and added[0]["category"] == "Custom" and added[0]["enabled"] is True, str(lib8))
    check("add: the existing categories are passed to the dialog",
          _StubDialog.last["entry"] is None and "Logs" in _StubDialog.last["categories"],
      str(_StubDialog.last))

    # EDIT (the button on the selected record)
    item = find_child(p8.tree, "My Test Cmd")
    p8.tree.setCurrentItem(item)
    _STUB["data"] = {"name": "My Test Cmd 2", "command": "echo hello2",
                     "category": "Custom", "enabled": False}
    p8.edit_btn.click()
    app.processEvents()
    lib8 = store8.load()
    edited = [e for e in lib8 if e["name"] == "My Test Cmd 2"]
    check("edit: the fields are updated in the file (name/command/enabled)",
          len(edited) == 1 and edited[0]["command"] == "echo hello2"
          and edited[0]["enabled"] is False, str(lib8))

    # DUPLICATE (a context menu action — a test seam without exec())
    item = find_child(p8.tree, "My Test Cmd 2")
    menu = p8._build_context_menu(item)
    n_before = len(store8.load())
    act_by_text(menu, i18n.t("terminal.cmdlib.duplicate")).trigger()
    app.processEvents()
    lib8 = store8.load()
    dups = [e for e in lib8 if e["name"] == "My Test Cmd 2"]
    check("duplicate: +1 record, a new id",
          len(lib8) == n_before + 1 and len(dups) == 2 and len({e["id"] for e in dups}) == 2,
      str(lib8))

    # TOGGLE (a context menu action)
    item = find_child(p8.tree, "Disk usage")
    menu = p8._build_context_menu(item)
    act_by_text(menu, i18n.t("terminal.cmdlib.toggle_enabled")).trigger()
    app.processEvents()
    lib8 = store8.load()
    check("toggle: 'Disk usage' is disabled in the file",
          all(not e["enabled"] for e in lib8 if e["name"] == "Disk usage"))

    # COPY (a context menu action → the clipboard)
    item = find_child(p8.tree, "My Test Cmd 2")
    menu = p8._build_context_menu(item)
    act_by_text(menu, i18n.t("terminal.cmdlib.copy")).trigger()
    app.processEvents()
    cb = QApplication.clipboard()
    check("copy: the command text is in the clipboard",
          cb is not None and cb.text() == "echo hello2", repr(cb.text() if cb else None))

    # DELETE with confirmation (QMessageBox — a monkeypatch of the module attribute)
    _orig_qmb = CL.QMessageBox

    class _FakeQMB:
        Yes, No = 1, 2
        reply = Yes   # in the class body the name _FakeQMB is not bound yet — we take the constant directly
        calls = []

        @classmethod
        def question(cls, *a, **kw):
            cls.calls.append((a, kw))
            return cls.reply

    CL.QMessageBox = _FakeQMB
    try:
        item = find_child(p8.tree, "My Test Cmd 2")
        menu = p8._build_context_menu(item)
        act_by_text(menu, i18n.t("terminal.cmdlib.delete")).trigger()
        app.processEvents()
        lib8 = store8.load()
        left = [e for e in lib8 if e["name"] == "My Test Cmd 2"]
        check("delete (Yes): one of the duplicates is removed from the file", len(left) == 1, str(lib8))
        check("delete: the name of the record is in the confirmation",
              bool(_FakeQMB.calls)
              and i18n.t("terminal.cmdlib.confirm_delete", name="My Test Cmd 2") in str(_FakeQMB.calls[0][0]))

        _FakeQMB.reply = _FakeQMB.No
        item = find_child(p8.tree, "My Test Cmd 2")
        menu = p8._build_context_menu(item)
        act_by_text(menu, i18n.t("terminal.cmdlib.delete")).trigger()
        app.processEvents()
        lib8 = store8.load()
        check("delete (No): the record is kept",
              len([e for e in lib8 if e["name"] == "My Test Cmd 2"]) == 1)

        # the context menu by category — all the actions are disabled
        top = p8.tree.topLevelItem(0)
        menu = p8._build_context_menu(top)
        check("the context menu by category: all the actions are disabled",
              all(not a.isEnabled() for a in menu.actions()))
        # The POLICY is what makes the gesture exist: without it the right click is a plain
        # contextMenuEvent the tree ignores, so it travels up to the container (where the
        # terminal window answered it with its own "Split Terminal" menu and the dock with
        # nothing) and the documented "right-click the library" affordance never opened.
        check("the tree carries the CustomContextMenu policy (the right-click reaches the panel)",
              p8.tree.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu,
              str(p8.tree.contextMenuPolicy()))
    finally:
        CL.QMessageBox = _orig_qmb
finally:
    CL.CommandLibraryDialog = _orig_dlg

# the dialog itself (not a stub): OK is disabled until there is a name+command; result_entry
dlg = CL.CommandLibraryDialog(None, categories=["A", "B"])
check("the dialog: OK is disabled with empty fields", dlg._ok.isEnabled() is False)
dlg.name_edit.setText("only name")
app.processEvents()
check("the dialog: OK is disabled without a command", dlg._ok.isEnabled() is False)
dlg.command_edit.setPlainText("echo 1")
app.processEvents()
check("the dialog: OK is enabled with a name+command", dlg._ok.isEnabled() is True)
r = dlg.result_entry()
check("the dialog: result_entry (name/category/command/enabled)",
      r == {"name": "only name", "category": "", "command": "echo 1", "enabled": True}, str(r))

dlg2 = CL.CommandLibraryDialog(
    {"id": "e1", "name": "N", "command": "C\n", "category": "K", "enabled": False},
    categories=["A"])
check("the dialog: the edit mode — the fields are pre-filled (the command is not trimmed)",
      dlg2.name_edit.text() == "N" and dlg2.command_edit.toPlainText() == "C\n"
      and dlg2.category_edit.currentText() == "K" and dlg2.enabled_check.isChecked() is False)


# ════════════════════════════════════════════════
# 9. i18n parity (446 = 427 + 19: terminal.cmdlib.*) + release state
# ════════════════════════════════════════════════
print("== 9. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
