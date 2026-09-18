# -*- coding: utf-8 -*-
"""v1.0RC4 — Quick launch (server links/commands): the release's themed test.

The feature (at the colleagues' request, outside the original ROADMAP v1.0):
  * ServerData.quick_launch — a list of items {"type": "url"|"command", "name", "value"};
    stored in the project JSON as the "quick_launch" array (backward-compat: the old files
    are read as an empty list, the broken records are dropped);
  * the right click on the server (the sidebar row AND the map node) — the "Quick launch" submenu FIRST
    (above "Connect via SSH"): the items + a separator + "Configure…";
  * a URL opens in the default browser (webbrowser); a command is sent
    as the first command into the server's SSH terminal (SSHTerminalWindow(initial_command=...),
    the send after connected_signal with the INITIAL_COMMAND_DELAY_MS delay);
  * the configuration — the "Quick launch…" button in the server properties (below
    "Manage profiles…") + "Configure…" from the submenu; the changes via the undo stack.

Run: python tests/test_quick_launch.py   (from the project root) or python tests/run_all.py
"""
import json
import os
import sys
import traceback

from _common import (bootstrap, check, finish, wait_until, viewport_point, load_i18n_langs,
                     check_i18n_parity)

ROOT, WORK = bootstrap()  # BEFORE the app module imports

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
import graphics.map_view as MV
import modules.ssh_terminal as ST
from models.server import (ServerData, server_data_from_dict,
                           server_data_to_dict, sanitize_quick_launch)
from i18n import t as it

from _fakes import (CaptureMenu as _CaptureMenu, FakeTermWin as _FakeTermWin,
                    FakeSSHThread as _FakeSSHThreadBase)

# ══ 1. The model: ServerData.quick_launch + the serialization ═══════════════════════
print("== model ==")

d_def = ServerData(id="qlm1", alias="def", host="h", user="u")
check("default quick_launch is []", d_def.quick_launch == [])

raw_ql = {
    "id": "qlm2", "alias": "master", "host": "192.168.3.76", "user": "ubuntu",
    "quick_launch": [
        {"type": "url", "name": "Webmin", "value": "http://192.168.3.76:10000/"},
        {"type": "command", "name": "K9S", "value": "k9s"},
    ],
}
d_ql = server_data_from_dict(raw_ql)
check("from_dict keeps entries in order",
      d_ql.quick_launch == [
          {"type": "url", "name": "Webmin", "value": "http://192.168.3.76:10000/"},
          {"type": "command", "name": "K9S", "value": "k9s"}], str(d_ql.quick_launch))

check("from_dict without the key → [] (the old projects)",
      server_data_from_dict({"id": "qlm3", "alias": "old", "host": "h"}).quick_launch == [])

bad = sanitize_quick_launch([
    "not-a-dict", 42,
    {"type": "url"},                      # empty name/value → a drop
    {"name": "NoValue", "value": ""},     # empty → a drop
    {"type": "ftp", "name": "X", "value": "ftp://x"},  # an unknown type → url
    {"type": "URL ", "name": " Spaced ", "value": " https://a.b /"},
])
check("sanitize drops broken entries and normalizes types/whitespace",
      bad == [{"type": "url", "name": "X", "value": "ftp://x"},
              {"type": "url", "name": "Spaced", "value": "https://a.b /"}], str(bad))

d_pw = ServerData(id="qlm4", alias="pw", host="h", user="u", password="secret",
                  quick_launch=[{"type": "command", "name": "K9S", "value": "k9s"}])
sd = server_data_to_dict(d_pw)
check("to_dict: quick_launch serialized, password stripped",
      sd.get("quick_launch") == [{"type": "command", "name": "K9S", "value": "k9s"}]
      and "password" not in sd, str(sd.keys()))

# ══ 2. The QuickLaunchDialog: the prefill, the add, the validation, the remove ═══
print("== dialog ==")

from dialogs.quick_launch_dialog import QuickLaunchDialog

warned = []
_real_warn = QMessageBox.warning
QMessageBox.warning = staticmethod(lambda *a, **k: (warned.append(a), 0)[1])
try:
    src = ServerData(id="qld1", alias="master-node", host="192.168.3.76", user="ubuntu",
                     quick_launch=[
                         {"type": "url", "name": "Webmin", "value": "http://192.168.3.76:10000/"},
                         {"type": "command", "name": "K9S", "value": "k9s"}])
    dlg = QuickLaunchDialog(None, server_data=src)
    check("dialog prefills the table from server_data",
          dlg.table.rowCount() == 2
          and dlg.table.item(0, 1).text() == "Webmin"
          and dlg.table.item(1, 2).text() == "k9s",
          f"rows={dlg.table.rowCount()}")
    check("dialog title carries the server alias (i18n dialog.quick_launch)",
          dlg.windowTitle() == it("dialog.quick_launch", alias="master-node"),
          repr(dlg.windowTitle()))
    check("get_entries returns copies of the loaded list",
          dlg.get_entries() == src.quick_launch and dlg.get_entries() is not src.quick_launch)

    # Validation: an empty name → a warning, the item is not added
    dlg.name_edit.setText("")
    dlg.value_edit.setText("http://x")
    dlg._add_entry()
    check("empty name rejected (warning, no row)",
          len(warned) == 1 and dlg.table.rowCount() == 2, f"warned={len(warned)}")

    # Validation: an empty value
    dlg.name_edit.setText("Grafana")
    dlg.value_edit.setText("   ")
    dlg._add_entry()
    check("empty value rejected", len(warned) == 2 and dlg.table.rowCount() == 2,
          f"warned={len(warned)}")

    # Validation: a URL without http(s)://
    dlg.value_edit.setText("ftp://192.168.3.76/pub")
    dlg._add_entry()
    check("non-http(s) URL rejected", len(warned) == 3 and dlg.table.rowCount() == 2,
          f"warned={len(warned)}")

    # A duplicate (type+name)
    dlg.type_combo.setCurrentIndex(0)  # url
    dlg.name_edit.setText("Webmin")
    dlg.value_edit.setText("http://192.168.3.76:10000/")
    dlg._add_entry()
    check("duplicate (type+name) rejected", len(warned) == 4 and dlg.table.rowCount() == 2,
          f"warned={len(warned)}")

    # A correct URL addition
    dlg.name_edit.setText("Grafana")
    dlg.value_edit.setText("http://192.168.3.76:3000")
    dlg._add_entry()
    check("valid URL added and fields cleared",
          dlg.table.rowCount() == 3 and dlg.name_edit.text() == "" and dlg.value_edit.text() == "")

    # Adding a command (the type — the second item of the combobox)
    dlg.type_combo.setCurrentIndex(1)
    check("type combo offers url+command",
          [dlg.type_combo.itemData(i) for i in range(dlg.type_combo.count())] == ["url", "command"])
    dlg.name_edit.setText("Docker")
    dlg.value_edit.setText("docker ps")
    dlg._add_entry()
    entries = dlg.get_entries()
    check("command entry added with type=command",
          {"type": "command", "name": "Docker", "value": "docker ps"} in entries, str(entries))

    # Removing the selected row (the first — Webmin)
    dlg.table.selectRow(0)
    dlg._remove_selected()
    check("remove selected row drops the entry",
          dlg.table.rowCount() == 3
          and all(e["name"] != "Webmin" for e in dlg.get_entries()), str(dlg.get_entries()))

    # A new server (server_data=None) — an empty dialog, no crashes
    dlg_new = QuickLaunchDialog(None, server_data=None)
    check("dialog for a NEW server starts empty", dlg_new.table.rowCount() == 0)
finally:
    QMessageBox.warning = _real_warn

# ══ 3. The server properties (AddServerDialog): the button + the list save ═══════
print("== add_server_dialog integration ==")

from dialogs.add_server_dialog import AddServerDialog

node_src = ServerData(id="qld2", alias="master-node", host="192.168.3.76", user="ubuntu",
                      quick_launch=[{"type": "command", "name": "K9S", "value": "k9s"}])
asdlg = AddServerDialog(None, edit_data=node_src)
from PySide6.QtWidgets import QPushButton
ql_btn = next((b for b in asdlg.findChildren(QPushButton)
               if b.text() == it("ql.configure_button")), None)
check("properties dialog has the 'Quick Launch…' button", ql_btn is not None,
      str([b.text() for b in asdlg.findChildren(QPushButton)]))

# Editing OTHER fields does not reset quick_launch (a regression on the zeroing)
asdlg.alias.setText("master-node-2")
got = asdlg.get_data()
check("get_data preserves quick_launch when the dialog was not opened",
      got.quick_launch == [{"type": "command", "name": "K9S", "value": "k9s"}],
      str(got.quick_launch))

# The button opens the QuickLaunchDialog and picks up the result (a dialog fake)
import dialogs.quick_launch_dialog as QLD_MOD
_real_ql_dlg = QLD_MOD.QuickLaunchDialog
class _FakeQLDlg:
    def __init__(self, parent=None, server_data=None):
        self.server_data = server_data
    def exec(self):
        return QDialog.Accepted
    def get_entries(self):
        return [{"type": "url", "name": "HomeAssistant", "value": "http://192.168.3.76:32110"}]
QLD_MOD.QuickLaunchDialog = _FakeQLDlg
try:
    asdlg._open_quick_launch()
finally:
    QLD_MOD.QuickLaunchDialog = _real_ql_dlg
check("_open_quick_launch stores the dialog result",
      asdlg.get_data().quick_launch == [
          {"type": "url", "name": "HomeAssistant", "value": "http://192.168.3.76:32110"}],
      str(asdlg.get_data().quick_launch))

# ══ 4. The MainWindow E2E: the sidebar — the submenu first, the URL → webbrowser ═══════════
print("== main window: sidebar menu + url run ==")

win = MW.MainWindow()
win.show(); app.processEvents()

d_node = server_data_from_dict(raw_ql)  # Webmin (url) + K9S (command)
n_ql = win.scene.add_server(d_node)
win.refresh_sidebar(); app.processEvents()

def _row_center(item):
    r = win.tree.visualItemRect(item)
    return QPoint(int(r.center().x()), int(r.center().y()))

def _item_for(node_id):
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.data(0, Qt.UserRole) == node_id:
            return item
    return None

captured = []
_CaptureMenu.captured = captured   # _fakes.CaptureMenu: intercepting exec/exec_ offscreen

_orig_menu_cls = MW.QMenu
MW.QMenu = _CaptureMenu
try:
    item = _item_for(d_node.id)
    check("tree row exists for the quick-launch node", item is not None)
    if item:
        captured.clear()
        win.tree.customContextMenuRequested.emit(_row_center(item))
        app.processEvents()
        menu = captured[-1] if captured else None
        check("sidebar context menu captured", menu is not None)
        if menu:
            first = menu.actions()[0]
            check("sidebar: 'Quick Launch' submenu is the FIRST item (above SSH)",
                  first.menu() is not None and first.text() == it("ctx.quick_launch"),
                  f"first={first.text()!r}")
            if first.menu() is not None:
                ql_actions = list(first.menu().actions())
                ql_items = [a.text() for a in ql_actions if not a.isSeparator()]
                check("sidebar submenu: Webmin, K9S, separator, 'Configure…'",
                      ql_items == ["Webmin", "K9S", it("ql.configure")]
                      and sum(1 for a in ql_actions if a.isSeparator()) == 1, str(ql_items))
                # The URL item → webbrowser.open (a monkeypatch)
                import webbrowser
                opened = []
                _real_open = webbrowser.open
                webbrowser.open = staticmethod(lambda url, **k: (opened.append(url), True)[1])
                try:
                    first.menu().actions()[0].trigger()  # Webmin
                    app.processEvents()
                finally:
                    webbrowser.open = _real_open
                check("url entry opens in the default browser (webbrowser.open)",
                      opened == ["http://192.168.3.76:10000/"], str(opened))
finally:
    MW.QMenu = _orig_menu_cls

# ══ 5. The MainWindow E2E: the map — the submenu first, the command → the terminal ═══════════
print("== main window: map menu + command run ==")

captured_m = []
_CaptureMenu.captured = captured_m

fake_windows = []
_FakeTermWin.spawned = fake_windows

_orig_mv_menu = MV.QMenu
_orig_mw_win = MW.SSHTerminalWindow
MV.QMenu = _CaptureMenu
MW.SSHTerminalWindow = _FakeTermWin
try:
    # key_path is set → a direct terminal launch without the SSH dialog (key auth)
    n_ql.data.key_path = r"C:\keys\test.pem"
    center = n_ql.sceneBoundingRect().center()
    local = viewport_point(win.view, center)  # Qt 6.11: mapFromScene may return a QPointF
    evt = QContextMenuEvent(QContextMenuEvent.Mouse, local, QPoint(0, 0))
    captured_m.clear()
    win.view.contextMenuEvent(evt)
    app.processEvents()
    mmenu = captured_m[-1] if captured_m else None
    check("map context menu captured on right-click of the node", mmenu is not None)
    if mmenu:
        mfirst = mmenu.actions()[0]
        check("map: 'Quick Launch' submenu is the FIRST item (above SSH)",
              mfirst.menu() is not None and mfirst.text() == it("ctx.quick_launch"),
              f"first={mfirst.text()!r}")
        if mfirst.menu() is not None:
            mq_actions = list(mfirst.menu().actions())
            ql_items = [a.text() for a in mq_actions if not a.isSeparator()]
            check("map submenu: Webmin, K9S, separator, 'Configure…'",
                  ql_items == ["Webmin", "K9S", it("ql.configure")]
                  and sum(1 for a in mq_actions if a.isSeparator()) == 1, str(ql_items))
            fake_windows.clear()
            mfirst.menu().actions()[1].trigger()  # K9S (command)
            app.processEvents()
            check("command entry opens the terminal with initial_command='k9s'",
                  len(fake_windows) == 1
                  and fake_windows[0].initial_command == "k9s"
                  and fake_windows[0].server_data is n_ql.data,
                  f"n={len(fake_windows)} cmd={fake_windows and fake_windows[0].initial_command!r}")
finally:
    MV.QMenu = _orig_mv_menu
    MW.SSHTerminalWindow = _orig_mw_win

# ══ 6. SSHTerminalWindow: initial_command goes to the channel after the connection ══
print("== terminal window: initial command delivery ==")

class _FakeSSHThread(_FakeSSHThreadBase):
    RECORD = "last"   # the channel accumulates only the last send (the initial_command scenario)

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread
try:
    tdata = ServerData(id="qlt1", alias="term", host="10.30.0.99", user="root",
                       ssh_port=22)
    twin = ST.SSHTerminalWindow(tdata, None, password="pw123", initial_command="k9s")
    check("window passes password to the thread", twin.terminal_thread.password == "pw123")
    # Before connected_signal the command does NOT go
    check("no data sent before connected_signal", twin.terminal_thread.channel.sent is None)
    twin.terminal_thread.connected_signal.emit()
    wait_until(lambda: twin.terminal_thread.channel.sent is not None, timeout_ms=2000)
    check("after connected_signal the first command reaches the channel ('k9s\\n')",
          twin.terminal_thread.channel.sent == b"k9s\n",
          repr(twin.terminal_thread.channel.sent))
    # A repeated emit — exactly one send (the _initial_command guard): we wait until
    # the second timer (500 ms) will fire too, and we make sure the channel did not get a duplicate.
    twin.terminal_thread.connected_signal.emit()
    from PySide6.QtTest import QTest
    QTest.qWait(700)
    app.processEvents()
    check("re-emit of connected_signal does not resend the command",
          twin.terminal_thread.channel.sent == b"k9s\n")
    twin.close()
finally:
    ST.SSHTerminalThread = _orig_thread_cls

# A window WITHOUT initial_command — no one listens to connected_signal, no crashes
ST.SSHTerminalThread = _FakeSSHThread
try:
    twin2 = ST.SSHTerminalWindow(tdata, None)
    twin2.terminal_thread.connected_signal.emit()
    app.processEvents()
    check("window without initial_command ignores connected_signal", True)
    twin2.close()
finally:
    ST.SSHTerminalThread = _orig_thread_cls

# ══ 7. The setting from the submenu: the undo stack + the persistence in the JSON ═════════════
print("== configure dialog: undo + persistence ==")

class _FakeQLDlg2:
    def __init__(self, parent=None, server_data=None):
        self.server_data = server_data
    def exec(self):
        return QDialog.Accepted
    def get_entries(self):
        return [{"type": "url", "name": "Grafana", "value": "http://192.168.3.76:3000"}]

QLD_MOD.QuickLaunchDialog = _FakeQLDlg2
try:
    before = [dict(e) for e in n_ql.data.quick_launch]
    win._open_quick_launch_dialog(n_ql)
    app.processEvents()
finally:
    QLD_MOD.QuickLaunchDialog = _real_ql_dlg

check("configure dialog applies the new list to the node",
      n_ql.data.quick_launch == [{"type": "url", "name": "Grafana",
                                  "value": "http://192.168.3.76:3000"}],
      str(n_ql.data.quick_launch))
check("configure marks the project dirty", bool(win._dirty))
win.undo_stack.undo()
check("undo restores the previous quick_launch list",
      n_ql.data.quick_launch == before, f"got={n_ql.data.quick_launch} want={before}")

# Persistence: saving the project writes "quick_launch" to the JSON
path = os.path.join(WORK, "ql_save.json")
ok_saved = win._do_save(path)
with open(path, encoding="utf-8") as f:
    saved = json.load(f)
s_ql = next(s for s in saved["servers"] if s["id"] == d_node.id)
check("_do_save writes quick_launch into the project JSON",
      ok_saved and s_ql.get("quick_launch") == before, str(s_ql.get("quick_launch")))
reloaded = server_data_from_dict(s_ql)
check("reload via server_data_from_dict restores the entries",
      reloaded.quick_launch == before, str(reloaded.quick_launch))

# ══ 7b. v1.0-fix: KeyError "name" in LogRecord (extra={"name": ...}) ═══════
print("== v1.0-fix: quick launch logging ==")

# Before the fix, extra={"name": name} in log.info() collided with the built-in attribute
# LogRecord.name (the logger name) → makeRecord() raised KeyError AFTER the successful
# opening a URL/launching a command; _run_quick_launch_entry caught it as
# "Quick launch failed for …" + QMessageBox.critical, although the feature worked.
import webbrowser as _wb_mod
opened_urls = []
_real_wb_open = _wb_mod.open
_wb_mod.open = staticmethod(lambda url, **k: (opened_urls.append(url), True)[1])
try:
    win._quick_launch_url("http://example.com/", "TestURL")   # before the fix — a KeyError from logging
    app.processEvents()
    check("url entry: the logging without a KeyError (extra 'name' → 'ql_name')",
          opened_urls == ["http://example.com/"], str(opened_urls))
finally:
    _wb_mod.open = _real_wb_open

spawned_calls = []
_orig_spawn = win._spawn_terminal_window
win._spawn_terminal_window = lambda node, password=None, initial_command="": \
    spawned_calls.append((node.data.alias, initial_command))
try:
    n_ql.data.key_path = r"C:\keys\test.pem"   # key auth → a direct terminal launch
    win._quick_launch_command(n_ql, "k9s", "K9S")  # before the fix — a KeyError from logging
    app.processEvents()
    check("command entry: the logging without a KeyError (extra 'name' → 'ql_name')",
          spawned_calls == [("master", "k9s")], str(spawned_calls))
finally:
    win._spawn_terminal_window = _orig_spawn

# ══ 8. i18n: 22 new keys × en/ru/zh (the parity — _common.check_i18n_parity) ══════
print("== i18n ==")
langs = load_i18n_langs(ROOT)
new_keys = ["ctx.quick_launch", "ql.configure", "ql.configure_button",
            "dialog.quick_launch", "dialog.quick_launch_desc", "ql.type",
            "ql.type.url", "ql.type.command", "ql.name", "ql.value",
            "ql.value_hint_url", "ql.value_hint_command", "ql.add", "ql.remove",
            "validation.ql_name_empty", "validation.ql_value_empty",
            "validation.ql_url_scheme", "validation.ql_duplicate",
            "status.ql_opened", "status.ql_command", "msg.ql_no_browser",
            "msg.ql_open_failed"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("the 22 new v1.0RC4 keys are present and non-empty in en/ru/zh", not missing, str(missing))
check_i18n_parity(langs)

# Cleanup: we reset dirty — otherwise closeEvent would go to the save dialog.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
