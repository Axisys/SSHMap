# -*- coding: utf-8 -*-
"""v1.0RC4 — Быстрый запуск (ссылки/команды на сервер): тематический тест релиза.

Фича (по просьбе коллег, вне исходного ROADMAP v1.0):
  * ServerData.quick_launch — список пунктов {"type": "url"|"command", "name", "value"};
    хранится в JSON проекта как массив "quick_launch" (backward-compat: старые файлы
    читаются пустым списком, битые записи отбрасываются);
  * ПКМ по серверу (строка сайдбара И узел карты) — подменю «Быстрый запуск» ПЕРВЫМ
    пунктом (выше «Подключиться по SSH»): пункты + разделитель + «Настроить…»;
  * URL открывается в браузере по умолчанию (webbrowser); команда отправляется
    первой командой в SSH-терминал сервера (SSHTerminalWindow(initial_command=...),
    отправка после connected_signal с задержкой INITIAL_COMMAND_DELAY_MS);
  * настройка — кнопка «Быстрый запуск…» в свойствах сервера (под «Управление
    профилями…») + «Настроить…» из подменю; изменения через undo-стек.

Запуск: python tests/test_quick_launch.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import traceback

from _common import bootstrap, check, finish, wait_until, viewport_point

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

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

# ══ 1. Модель: ServerData.quick_launch + сериализация ═══════════════════════
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

check("from_dict without the key → [] (старые проекты)",
      server_data_from_dict({"id": "qlm3", "alias": "old", "host": "h"}).quick_launch == [])

bad = sanitize_quick_launch([
    "not-a-dict", 42,
    {"type": "url"},                      # пустые name/value → drop
    {"name": "NoValue", "value": ""},     # пусто → drop
    {"type": "ftp", "name": "X", "value": "ftp://x"},  # неизвестный type → url
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

# ══ 2. Диалог QuickLaunchDialog: prefill, добавление, валидация, удаление ═══
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

    # Валидация: пустое название → warning, пункт не добавлен
    dlg.name_edit.setText("")
    dlg.value_edit.setText("http://x")
    dlg._add_entry()
    check("empty name rejected (warning, no row)",
          len(warned) == 1 and dlg.table.rowCount() == 2, f"warned={len(warned)}")

    # Валидация: пустое значение
    dlg.name_edit.setText("Grafana")
    dlg.value_edit.setText("   ")
    dlg._add_entry()
    check("empty value rejected", len(warned) == 2 and dlg.table.rowCount() == 2,
          f"warned={len(warned)}")

    # Валидация: URL без http(s)://
    dlg.value_edit.setText("ftp://192.168.3.76/pub")
    dlg._add_entry()
    check("non-http(s) URL rejected", len(warned) == 3 and dlg.table.rowCount() == 2,
          f"warned={len(warned)}")

    # Дубликат (тип+название)
    dlg.type_combo.setCurrentIndex(0)  # url
    dlg.name_edit.setText("Webmin")
    dlg.value_edit.setText("http://192.168.3.76:10000/")
    dlg._add_entry()
    check("duplicate (type+name) rejected", len(warned) == 4 and dlg.table.rowCount() == 2,
          f"warned={len(warned)}")

    # Корректное добавление URL
    dlg.name_edit.setText("Grafana")
    dlg.value_edit.setText("http://192.168.3.76:3000")
    dlg._add_entry()
    check("valid URL added and fields cleared",
          dlg.table.rowCount() == 3 and dlg.name_edit.text() == "" and dlg.value_edit.text() == "")

    # Добавление команды (тип — второй элемент комбобокса)
    dlg.type_combo.setCurrentIndex(1)
    check("type combo offers url+command",
          [dlg.type_combo.itemData(i) for i in range(dlg.type_combo.count())] == ["url", "command"])
    dlg.name_edit.setText("Docker")
    dlg.value_edit.setText("docker ps")
    dlg._add_entry()
    entries = dlg.get_entries()
    check("command entry added with type=command",
          {"type": "command", "name": "Docker", "value": "docker ps"} in entries, str(entries))

    # Удаление выбранной строки (первая — Webmin)
    dlg.table.selectRow(0)
    dlg._remove_selected()
    check("remove selected row drops the entry",
          dlg.table.rowCount() == 3
          and all(e["name"] != "Webmin" for e in dlg.get_entries()), str(dlg.get_entries()))

    # Новый сервер (server_data=None) — пустой диалог, без падений
    dlg_new = QuickLaunchDialog(None, server_data=None)
    check("dialog for a NEW server starts empty", dlg_new.table.rowCount() == 0)
finally:
    QMessageBox.warning = _real_warn

# ══ 3. Свойства сервера (AddServerDialog): кнопка + сохранение списка ═══════
print("== add_server_dialog integration ==")

from dialogs.add_server_dialog import AddServerDialog

node_src = ServerData(id="qld2", alias="master-node", host="192.168.3.76", user="ubuntu",
                      quick_launch=[{"type": "command", "name": "K9S", "value": "k9s"}])
asdlg = AddServerDialog(None, edit_data=node_src)
from PySide6.QtWidgets import QPushButton
ql_btn = next((b for b in asdlg.findChildren(QPushButton)
               if b.text() == it("ql.configure_button")), None)
check("properties dialog has the 'Быстрый запуск…' button", ql_btn is not None,
      str([b.text() for b in asdlg.findChildren(QPushButton)]))

# Правка ДРУГИХ полей не сбрасывает quick_launch (регрессия на обнуление)
asdlg.alias.setText("master-node-2")
got = asdlg.get_data()
check("get_data preserves quick_launch when the dialog was not opened",
      got.quick_launch == [{"type": "command", "name": "K9S", "value": "k9s"}],
      str(got.quick_launch))

# Кнопка открывает QuickLaunchDialog и подхватывает результат (фейк диалога)
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

# ══ 4. MainWindow E2E: сайдбар — подменю первым, URL → webbrowser ═══════════
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
class _CaptureMenu(MW.QMenu):
    def exec(self, *a, **k):
        captured.append(self); return 0
    def exec_(self, *a, **k):
        captured.append(self); return 0

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
            check("sidebar: 'Быстрый запуск' submenu is the FIRST item (above SSH)",
                  first.menu() is not None and first.text() == it("ctx.quick_launch"),
                  f"first={first.text()!r}")
            if first.menu() is not None:
                ql_actions = list(first.menu().actions())
                ql_items = [a.text() for a in ql_actions if not a.isSeparator()]
                check("sidebar submenu: Webmin, K9S, separator, 'Настроить…'",
                      ql_items == ["Webmin", "K9S", it("ql.configure")]
                      and sum(1 for a in ql_actions if a.isSeparator()) == 1, str(ql_items))
                # URL-пункт → webbrowser.open (monkeypatch)
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

# ══ 5. MainWindow E2E: карта — подменю первым, команда → терминал ═══════════
print("== main window: map menu + command run ==")

captured_m = []
class _CaptureMapMenu(MV.QMenu):
    def exec(self, *a, **k):
        captured_m.append(self); return 0
    def exec_(self, *a, **k):
        captured_m.append(self); return 0

class _DummySignal:
    def connect(self, *a, **k): pass

fake_windows = []
class _FakeTermWin:
    def __init__(self, server_data, parent=None, password=None, initial_command=""):
        self.server_data = server_data
        self.password = password
        self.initial_command = initial_command
        self.destroyed = _DummySignal()
        fake_windows.append(self)
    def show(self): pass

_orig_mv_menu = MV.QMenu
_orig_mw_win = MW.SSHTerminalWindow
MV.QMenu = _CaptureMapMenu
MW.SSHTerminalWindow = _FakeTermWin
try:
    # key_path задан → прямой запуск терминала без SSH-диалога (key auth)
    n_ql.data.key_path = r"C:\keys\test.pem"
    center = n_ql.sceneBoundingRect().center()
    local = viewport_point(win.view, center)  # Qt 6.11: mapFromScene может дать QPointF
    evt = QContextMenuEvent(QContextMenuEvent.Mouse, local, QPoint(0, 0))
    captured_m.clear()
    win.view.contextMenuEvent(evt)
    app.processEvents()
    mmenu = captured_m[-1] if captured_m else None
    check("map context menu captured on right-click of the node", mmenu is not None)
    if mmenu:
        mfirst = mmenu.actions()[0]
        check("map: 'Быстрый запуск' submenu is the FIRST item (above SSH)",
              mfirst.menu() is not None and mfirst.text() == it("ctx.quick_launch"),
              f"first={mfirst.text()!r}")
        if mfirst.menu() is not None:
            mq_actions = list(mfirst.menu().actions())
            ql_items = [a.text() for a in mq_actions if not a.isSeparator()]
            check("map submenu: Webmin, K9S, separator, 'Настроить…'",
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

# ══ 6. SSHTerminalWindow: initial_command уходит в канал после подключения ══
print("== terminal window: initial command delivery ==")

from PySide6.QtCore import QThread, Signal as QtSignal

class _FakeChannel:
    closed = False
    def __init__(self): self.sent = None
    def send(self, data): self.sent = data

class _FakeSSHThread(QThread):
    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()
    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host, self.user, self.port = host, user, port
        self.password, self.key_path = password, key_path
        self.channel = _FakeChannel()
        self.running = True
    def run(self):  # реальный SSH не нужен
        pass
    def stop(self):
        self.running = False
    def send_data(self, data_bytes):  # тот же API, что у реального SSHTerminalThread
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            self.channel.send(data_bytes)

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread
try:
    tdata = ServerData(id="qlt1", alias="term", host="10.30.0.99", user="root",
                       ssh_port=22)
    twin = ST.SSHTerminalWindow(tdata, None, password="pw123", initial_command="k9s")
    check("window passes password to the thread", twin.terminal_thread.password == "pw123")
    # До connected_signal команда НЕ уходит
    check("no data sent before connected_signal", twin.terminal_thread.channel.sent is None)
    twin.terminal_thread.connected_signal.emit()
    wait_until(lambda: twin.terminal_thread.channel.sent is not None, timeout_ms=2000)
    check("after connected_signal the first command reaches the channel ('k9s\\n')",
          twin.terminal_thread.channel.sent == b"k9s\n",
          repr(twin.terminal_thread.channel.sent))
    # Повторный emit — ровно одна отправка (guard _initial_command): ждём, пока
    # сработает и второй таймер (500 мс), и убеждаемся, что канал не получил дубль.
    twin.terminal_thread.connected_signal.emit()
    from PySide6.QtTest import QTest
    QTest.qWait(700)
    app.processEvents()
    check("re-emit of connected_signal does not resend the command",
          twin.terminal_thread.channel.sent == b"k9s\n")
    twin.close()
finally:
    ST.SSHTerminalThread = _orig_thread_cls

# Окно БЕЗ initial_command — connected_signal никто не слушает, падений нет
ST.SSHTerminalThread = _FakeSSHThread
try:
    twin2 = ST.SSHTerminalWindow(tdata, None)
    twin2.terminal_thread.connected_signal.emit()
    app.processEvents()
    check("window without initial_command ignores connected_signal", True)
    twin2.close()
finally:
    ST.SSHTerminalThread = _orig_thread_cls

# ══ 7. Настройка из подменю: undo-стек + персистентность в JSON ═════════════
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

# Персистентность: сохранение проекта пишет "quick_launch" в JSON
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

# До фикса extra={"name": name} в log.info() коллидировал со встроенным атрибутом
# LogRecord.name (имя логгера) → makeRecord() бросал KeyError ПОСЛЕ успешного
# открытия URL/запуска команды; _run_quick_launch_entry ловил его как
# «Quick launch failed for …» + QMessageBox.critical, хотя фича сработала.
import webbrowser as _wb_mod
opened_urls = []
_real_wb_open = _wb_mod.open
_wb_mod.open = staticmethod(lambda url, **k: (opened_urls.append(url), True)[1])
try:
    win._quick_launch_url("http://example.com/", "TestURL")   # до фикса — KeyError из logging
    app.processEvents()
    check("url entry: логирование без KeyError (extra 'name' → 'ql_name')",
          opened_urls == ["http://example.com/"], str(opened_urls))
finally:
    _wb_mod.open = _real_wb_open

spawned_calls = []
_orig_spawn = win._spawn_terminal_window
win._spawn_terminal_window = lambda node, password=None, initial_command="": \
    spawned_calls.append((node.data.alias, initial_command))
try:
    n_ql.data.key_path = r"C:\keys\test.pem"   # key auth → прямой запуск терминала
    win._quick_launch_command(n_ql, "k9s", "K9S")  # до фикса — KeyError из logging
    app.processEvents()
    check("command entry: логирование без KeyError (extra 'name' → 'ql_name')",
          spawned_calls == [("master", "k9s")], str(spawned_calls))
finally:
    win._spawn_terminal_window = _orig_spawn

# ══ 8. i18n: 22 новых ключа × en/ru/zh, наборы идентичны (373 на язык; +33 в v1.1) ══════
print("== i18n ==")
langs = {}
for code in ("en", "ru", "zh"):
    with open(os.path.join(ROOT, "i18n", f"{code}.json"), encoding="utf-8") as f:
        langs[code] = json.load(f)
new_keys = ["ctx.quick_launch", "ql.configure", "ql.configure_button",
            "dialog.quick_launch", "dialog.quick_launch_desc", "ql.type",
            "ql.type.url", "ql.type.command", "ql.name", "ql.value",
            "ql.value_hint_url", "ql.value_hint_command", "ql.add", "ql.remove",
            "validation.ql_name_empty", "validation.ql_value_empty",
            "validation.ql_url_scheme", "validation.ql_duplicate",
            "status.ql_opened", "status.ql_command", "msg.ql_no_browser",
            "msg.ql_open_failed"]
missing = [k for k in new_keys if any(not langs[c].get(k, "").strip() for c in ("en", "ru", "zh"))]
check("22 новых ключа v1.0RC4 есть и не пусты в en/ru/zh", not missing, str(missing))
check("key sets identical across en/ru/zh (373 keys each)",
      set(langs["en"]) == set(langs["ru"]) == set(langs["zh"])
      and all(len(d) == 373 for d in langs.values()),
      str({c: len(d) for c, d in langs.items()}))

# Cleanup: dirty сбрасываем — иначе closeEvent уйдёт в диалог сохранения.
try:
    win._dirty = False
    win.close(); win.destroy()
except Exception:
    pass

finish()
