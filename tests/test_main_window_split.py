# -*- coding: utf-8 -*-
"""v1.1.4: гигиена main_window.py — разрез на миксины (acceptance ROADMAP v1.1.4).

Тематический тест разреза: offscreen-MainWindow + прогон каждого кластера:
  * структура: все методы плана определены в ProjectIOMixin/NodeOpsMixin/SshMixin
    (не в MainWindow.__dict__), MRO-порядок, миксины НЕ импортируют main_window
    (цикл), шов host_attr видит подмены модуля-фасада (MW.<имя> = Fake);
  * ProjectIOMixin: save/load/restore — _save_project_as → _autosave_tick →
    _restore_from_autosave → _load_project_at во втором окне;
  * NodeOpsMixin: add/duplicate/delete node — _add_server (фейковый AddServerDialog,
    включая bool-гард v0.8.1), _duplicate_selected_node, групповое _delete_selected_nodes;
  * SshMixin: ssh-dialog flow — _run_ssh_connect с фейковыми SSHConnectDialog/
    SSHTerminalWindow: поля через undo-стек, индикатор, реестр окон,
    _forget_terminal_window; быстрый запуск живёт в том же миксине.

Запуск: python tests/test_main_window_split.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import re
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog

app = QApplication(sys.argv)

# Сеть в тестах запрещена: пробы статусов возвращают результат мгновенно
# (иначе _load_project_at → start_round плодил бы потоки с сетевыми таймаутами).
import services.status_checker as _SC
_SC.probe_ssh = lambda host, port, timeout=3.0: "offline"

from storage import autosave as AS
from models.server import ServerData
from modules.undo_commands import CmdEditNodeData
import ui.main_window as MW
import ui.main_window_project_io as PI
import ui.main_window_node_ops as NO
import ui.main_window_ssh as SS
from ui.mixin_support import host_attr

# ── QMessageBox: без модалок в offscreen, вызовы логируются; question — управляемый ──
boxes = []
question_replies = []  # очередь готовых ответов для question()


def _fake_question(*a, **k):
    boxes.append(("question", str(a[1]) if len(a) > 1 else ""))
    return question_replies.pop(0) if question_replies else QMessageBox.Yes


# QMessageBox — один класс на все модули (main_window и миксины импортируют его
# из PySide6): патч через MW.QMessageBox действует везде, включая перенесённые методы.
MW.QMessageBox.question = staticmethod(_fake_question)
MW.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(("critical", str(a[1]), str(a[2]))))
MW.QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(("warning", str(a[1]), str(a[2]))))
MW.QMessageBox.information = staticmethod(lambda *a, **k: boxes.append(("information", str(a[1]), str(a[2]))))


def make_window():
    """Offscreen-MainWindow с остановленным autosave-таймером (тики вызываем руками)."""
    win = MW.MainWindow()
    win._autosave_timer.stop()  # детерминизм: _autosave_tick ниже вызывается явно
    return win


# ══ 1. Структура: кластеры в миксинах, MainWindow — фасад ═══════════════════
print("== 1. structure: clusters live in mixins ==")

_mro = [c.__name__ for c in MW.MainWindow.__mro__]
check("MRO: MainWindow → ProjectIOMixin → NodeOpsMixin → SshMixin → QMainWindow",
      _mro[:5] == ["MainWindow", "ProjectIOMixin", "NodeOpsMixin", "SshMixin", "QMainWindow"],
      str(_mro[:6]))

# Полный список методов плана (ROADMAP v1.1.4, задачи 1–3; quick launch — в SSH-кластере)
PLAN = {
    "ProjectIOMixin": [
        "_new_project", "_import_project_raw", "_open_project", "_load_project_at",
        "_save_project", "_save_project_as", "_serialize_project_data", "_do_save",
        "_autosave_tick", "_restore_from_autosave", "_backup_items",
        "_show_backups_dialog", "_restore_from_source",
    ],
    "NodeOpsMixin": [
        "_add_server", "_import_servers_from_txt", "_duplicate_node",
        "_duplicate_selected_node", "_delete_selected_nodes", "_remove_node_guarded",
        "_ensure_worker_done", "_connect_selected_nodes", "_add_connection",
        "_edit_connection", "_remove_connection", "_copy_node_info", "_ping_node",
    ],
    "SshMixin": [
        "_connect_ssh_to_selected", "_run_ssh_connect", "_spawn_terminal_window",
        "_forget_terminal_window", "_apply_ssh_dialog_fields", "_connect_ssh_external",
        "_collect_node_info", "_on_info_ready", "_on_info_failed",
        "_open_quick_launch_dialog", "_run_quick_launch_entry",
        "_quick_launch_url", "_quick_launch_command",
    ],
}

_bad = []
for mixin_name, methods in PLAN.items():
    for m in methods:
        fn = getattr(MW.MainWindow, m, None)
        if fn is None:
            _bad.append(f"{m}: отсутствует")
        elif m in MW.MainWindow.__dict__:
            _bad.append(f"{m}: остался в MainWindow.__dict__")
        elif fn.__qualname__.split(".")[0] != mixin_name:
            _bad.append(f"{m}: владелец {fn.__qualname__}")
check(f"все методы плана ({sum(len(v) for v in PLAN.values())}) определены в своих миксинах",
      not _bad, "; ".join(_bad[:6]))

# AUDIT §3: миксины НЕ импортируют main_window (цикл) — только duck-typing.
_circ = []
for mod in (PI, NO, SS):
    with open(mod.__file__, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if re.match(r"\s*(from|import)\b", line) and "main_window" in line:
                _circ.append(f"{os.path.basename(mod.__file__)}:{i}: {line.strip()}")
check("миксины не импортируют main_window (нет цикла)", not _circ, "; ".join(_circ))

win0 = make_window()
check("host_attr видит атрибут модуля-фасада",
      host_attr(win0, "SSHConnectDialog") is MW.SSHConnectDialog)


class _Sentinel:  # маркер подмены
    pass


_orig_dlg = MW.SSHConnectDialog
MW.SSHConnectDialog = _Sentinel
try:
    check("host_attr видит тестовую подмену (шов для offscreen)",
          host_attr(win0, "SSHConnectDialog") is _Sentinel)
finally:
    MW.SSHConnectDialog = _orig_dlg

# ══ 2. ProjectIOMixin: save / load / restore ════════════════════════════════
print("== 2. ProjectIOMixin: save/load/restore ==")

path = os.path.join(WORK, "split_io.json")
win0.scene.add_server(ServerData(id="splita1", alias="SplitA", host="10.6.0.1", user="root"))
win0.scene.add_server(ServerData(id="splitb2", alias="SplitB", host="10.6.0.2", user="root"))
win0._mark_dirty()

_orig_savefn = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))
try:
    saved = win0._save_project_as()
finally:
    QFileDialog.getSaveFileName = _orig_savefn
check("_save_project_as: сохранено, _project_file установлен",
      saved is True and win0._project_file == path)
check("_save_project_as: dirty-маркер сброшен",
      not win0._dirty and " [*]" not in win0.windowTitle(), win0.windowTitle())
with open(path, encoding="utf-8") as f:
    disk = json.load(f)
check("JSON на диске: оба узла (паролей нет)",
      {s["id"] for s in disk["servers"]} == {"splita1", "splitb2"}
      and all(not s.get("password") for s in disk["servers"]), str(disk["servers"]))

# автосохранение: третий узел + ручной тик (таймер остановлен)
win0.scene.add_server(ServerData(id="splitc3", alias="SplitC", host="10.6.0.3", user="root"))
win0._mark_dirty()
win0._autosave_tick()
auto_path = AS.autosave_path_for(path)
check("_autosave_tick: файл автосохранения появился", os.path.isfile(auto_path), auto_path)

# restore: третий узел удаляем из памяти, восстанавливаем из автосохранения
win0.scene.remove_server("splitc3")
question_replies.append(QMessageBox.Yes)  # подтверждение восстановления
win0._restore_from_autosave()
check("_restore_from_autosave: сцена снова с тремя узлами",
      win0.scene.node_count() == 3, str(win0.scene.node_count()))
with open(path, encoding="utf-8") as f:
    disk2 = json.load(f)
check("restore: содержимое автосохранения записано в файл проекта",
      {s["id"] for s in disk2["servers"]} == {"splita1", "splitb2", "splitc3"},
      str([s["id"] for s in disk2["servers"]]))

# load во втором окне (общий путь Файл→Открыть)
win2 = make_window()
loaded = win2._load_project_at(path)
check("_load_project_at: загружено, _project_file установлен",
      loaded is True and win2._project_file == path)
check("_load_project_at: узлы восстановлены, dirty сброшен",
      win2.scene.node_count() == 3 and not win2._dirty,
      f"nodes={win2.scene.node_count()} dirty={win2._dirty}")

# ══ 3. NodeOpsMixin: add / duplicate / delete node ══════════════════════════
print("== 3. NodeOpsMixin: add/duplicate/delete ==")

winN = make_window()
winN.show()
app.processEvents()


class _FakeAddDlg:
    """Фейк AddServerDialog: подменяется на модуле-фасад (MW.AddServerDialog),
    миксин берёт его через host_attr в момент вызова."""
    instances = []

    def __init__(self, parent=None):
        self._data = ServerData(
            id=f"splitadd{len(_FakeAddDlg.instances) + 1:02d}",
            alias="SplitAdd", host="10.7.0.1", user="root")
        self._connect_after_accept = False
        _FakeAddDlg.instances.append(self)

    def exec(self):
        return QDialog.Accepted

    def get_data(self):
        return self._data


_orig_add = MW.AddServerDialog
MW.AddServerDialog = _FakeAddDlg
try:
    winN._add_server()      # путь тулбара (без позиции)
    winN._add_server(True)  # регрессия v0.8.1: bool из QAction.triggered — без падения
finally:
    MW.AddServerDialog = _orig_add
check("_add_server (миксин): два узла на сцене", winN.scene.node_count() == 2,
      str(winN.scene.node_count()))
check("_add_server: dirty + по команде undo на узел",
      winN._dirty and winN.undo_stack.count() == 2,
      f"dirty={winN._dirty} undo={winN.undo_stack.count()}")

# дублирование выделенного (Ctrl+D)
na = winN.scene.get_node("splitadd01")
winN._select_node(na)
ndup = winN._duplicate_selected_node()
check("_duplicate_selected_node: копия создана (новый id, те же поля)",
      ndup is not None and ndup.data.id != "splitadd01"
      and ndup.data.alias == "SplitAdd" and ndup.data.host == "10.7.0.1",
      f"id={ndup.data.id if ndup else None}")
check("дубликат смещён на +40/+40",
      ndup is not None
      and abs(ndup.data.x - na.data.x - 40.0) < 1e-6
      and abs(ndup.data.y - na.data.y - 40.0) < 1e-6,
      f"orig=({na.data.x},{na.data.y}) dup=({ndup.data.x if ndup else None},{ndup.data.y if ndup else None})")
check("дубликат стал выделенным", winN.scene.get_selected_node() is ndup)

# групповое удаление всех трёх (один вопрос на всю группу)
for node in winN.scene.nodes():
    node.setSelected(True)
check("мультивыделение: три узла выбраны", len(winN.selected_nodes()) == 3,
      str(len(winN.selected_nodes())))
question_replies.append(QMessageBox.Yes)
ok = winN._delete_selected_nodes()
check("_delete_selected_nodes (миксин): все удалены",
      ok is True and winN.scene.node_count() == 0, str(winN.scene.node_count()))
check("групповое удаление: dirty-маркер установлен", winN._dirty)

# ══ 4. SshMixin: ssh-dialog flow ════════════════════════════════════════════
print("== 4. SshMixin: ssh-dialog flow ==")

winS = make_window()
winS.show()
app.processEvents()
ns = winS.scene.add_server(
    ServerData(id="splitssh1", alias="SplitSSH", host="10.8.0.1", user="root"))


class _FL:  # мини-заглушка QLineEdit
    def __init__(self, v): self._v = v
    def text(self): return self._v
    def setText(self, v): self._v = v


class _FS:  # мини-заглушка QSpinBox
    def __init__(self, v): self._v = v
    def value(self): return self._v


class _FakeSSHDialog:
    def __init__(self, data, parent=None):
        self.user_edit = _FL("split-user")
        self.key_path_edit = _FL("/keys/split.pem")
        self.port_edit = _FS(2244)
        self.password_edit = _FL("SplitPw123")

    def exec(self):
        return QDialog.Accepted


class _DummySignal:
    def connect(self, *a, **k): pass


spawned_terms = []


class _FakeTermWin:
    def __init__(self, server_data, parent=None, password=None, initial_command=""):
        self.server_data = server_data
        self.password = password
        self.initial_command = initial_command
        self.destroyed = _DummySignal()
        spawned_terms.append(self)

    def show(self): pass


# автосбор информации — логируем вместо реального коллектора (сеть в тестах запрещена)
collect_calls = []
winS._collect_node_info = lambda node, password="", auto=False: \
    collect_calls.append((node.data.id, password, auto))

_orig_sshdlg, _orig_termwin = MW.SSHConnectDialog, MW.SSHTerminalWindow
MW.SSHConnectDialog = _FakeSSHDialog
MW.SSHTerminalWindow = _FakeTermWin
try:
    winS._run_ssh_connect(ns)
finally:
    MW.SSHConnectDialog = _orig_sshdlg
    MW.SSHTerminalWindow = _orig_termwin

check("ssh flow: поля диалога применены к узлу (_apply_ssh_dialog_fields)",
      ns.data.user == "split-user" and ns.data.ssh_port == 2244
      and ns.data.key_path == "/keys/split.pem",
      f"user={ns.data.user!r} port={ns.data.ssh_port} key={ns.data.key_path!r}")
_top = winS.undo_stack.command(winS.undo_stack.count() - 1) if winS.undo_stack.count() else None
check("ssh flow: поля прошли через undo-стек (CmdEditNodeData)",
      isinstance(_top, CmdEditNodeData), f"{type(_top).__name__ if _top else None}")
check("ssh flow: узел в _ssh_connected_nodes (индикатор подключения)",
      ns.data.id in winS._ssh_connected_nodes)
check("ssh flow: терминальное окно создано и зарегистрировано",
      len(spawned_terms) == 1 and len(winS._terminal_windows) == 1,
      f"spawned={len(spawned_terms)} registry={len(winS._terminal_windows)}")
if spawned_terms:
    check("ssh flow: пароль передан окну, в модели не хранится",
          spawned_terms[0].password == "SplitPw123" and ns.data.password == "")
check("ssh flow: автосбор информации после подключения (auto=True, с паролем)",
      collect_calls == [("splitssh1", "SplitPw123", True)], str(collect_calls))
winS._forget_terminal_window(spawned_terms[0])
check("_forget_terminal_window: реестр очищен", winS._terminal_windows == [])

# без выделения — information, без падения
boxes.clear()
winS.scene.clear_all()
winS._connect_ssh_to_selected()
check("без выделения: information показан, исключения нет",
      any(b[0] == "information" for b in boxes), str(boxes))

finish()
