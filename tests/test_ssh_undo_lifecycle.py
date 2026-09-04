# -*- coding: utf-8 -*-
"""v1.1.2RC1 — SSH-путь: undo, paramiko-дефолты, жизненный цикл потока (тема релиза).

ROADMAP v1.1.2RC1 (пункты AUDIT §5, проверенные на v1.1.1):
  N1    правки user/key/port при успешном SSH-подключении идут через undo-стек:
        прямые записи в server_data из SSHConnectDialog._on_worker_success() убраны —
        единственный путь MainWindow._apply_ssh_dialog_fields → CmdEditNodeData;
        регрессия: смена user/port в диалоге → подключение → Ctrl+Z откатывает.
  N2    пресет «conhost» внешнего терминала убран (conhost.exe не лаунчер, /c не
        принимает): TERMINAL_CHOICES_WINDOWS/detect/build_command; старое значение
        конфига "conhost" трактуется как "cmd" (backward-compat, файл не перезаписывается).
  N5    password-ветка SSHWorker: look_for_keys=False, allow_agent=False (паритет с
        ssh_terminal.py) — без опроса локальных ключей/agent до попытки пароля.
  N4    жизненный цикл потока при закрытии окна во время подключения: guard
        `if self.running` перед error_signal.emit() в except-ветках run() + реестр
        орфано-потоков (поток, переживший closeEvent wait(1500), держится до finished()).
  бонус-N11 CmdAddRemoveNode(mode="add"): стэш keyring-пароля при создании команды и
        восстановление в redo — после Ctrl+Z→Ctrl+Y дублирования копия снова с паролем.

Запуск: python tests/test_ssh_undo_lifecycle.py   (из корня проекта) или python tests/run_all.py
"""
import json as _json
import os
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QUndoStack

app = QApplication(sys.argv)


def _drain_events(ms=300):
    """Прокрутить event loop ms миллисекунд — доставить queued-сигналы из потоков."""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


from models.server import ServerData

# ════════════════════════════════════════════════════════════
# N1. SSH-диалог не пишет в node.data напрямую; правки user/key/port
#     идут через undo-стек (CmdEditNodeData), Ctrl+Z откатывает
# ════════════════════════════════════════════════════════════
print("== N1: ssh dialog fields via undo stack ==")
from dialogs.ssh_connect_dialog import SSHConnectDialog

_n1_data = ServerData(id="n1srv00", alias="N1", host="10.0.0.1", user="root")
_n1_dlg = SSHConnectDialog(_n1_data, None)
_n1_dlg.user_edit.setText("changed-user")
_n1_dlg.port_edit.setValue(2222)
_n1_dlg.key_path_edit.setText("/keys/n1.pem")


class _FakeWorkerN1:
    test_only = False


_n1_dlg._ssh_worker = _FakeWorkerN1()
try:
    _n1_dlg._on_worker_success("connected ok")
except Exception as e:  # noqa: BLE001 — ключевое: success-путь не падает без записей
    check("N1: _on_worker_success runs without direct writes", False, repr(e))
else:
    check("N1: _on_worker_success runs without direct writes", True)
check("N1: dialog accepted after success", _n1_dlg.result() == QDialog.Accepted)
check("N1: server_data NOT written by the dialog itself (user)",
      _n1_data.user == "root", f"user={_n1_data.user!r}")
check("N1: server_data NOT written by the dialog itself (port/key)",
      _n1_data.ssh_port == 22 and _n1_data.key_path == "",
      f"port={_n1_data.ssh_port} key={_n1_data.key_path!r}")

# E2E: MainWindow._run_ssh_connect — единственный путь через _apply_ssh_dialog_fields
import ui.main_window as MW
from modules.undo_commands import CmdEditNodeData


class _FL:
    """Мини-заглушка QLineEdit для фейка диалога."""
    def __init__(self, v): self._v = v
    def text(self): return self._v
    def setText(self, v): self._v = v


class _FS:
    """Мини-заглушка QSpinBox."""
    def __init__(self, v): self._v = v
    def value(self): return self._v


class _FakeSSHDialogN1:
    def __init__(self, data, parent=None):
        self.data = data
        self.user_edit = _FL("changed-user")
        self.key_path_edit = _FL("/keys/n1.pem")
        self.port_edit = _FS(2222)
        self.password_edit = _FL("pw-e2e")

    def exec(self):
        return QDialog.Accepted


win = MW.MainWindow()
win.show()
app.processEvents()
_n1_node = win.scene.add_server(
    ServerData(id="n1e2e00", alias="N1E2E", host="10.9.9.9", user="root"))

_spawned = []
_orig_dlg_cls = MW.SSHConnectDialog
_orig_spawn = win._spawn_terminal_window
_orig_collect = win._collect_node_info
MW.SSHConnectDialog = _FakeSSHDialogN1
win._spawn_terminal_window = lambda *a, **k: _spawned.append((a, k)) or None
win._collect_node_info = lambda *a, **k: None
try:
    win._run_ssh_connect(_n1_node)
finally:
    MW.SSHConnectDialog = _orig_dlg_cls
    win._spawn_terminal_window = _orig_spawn
    win._collect_node_info = _orig_collect

check("N1 E2E: fields applied after successful connect (redo via push)",
      _n1_node.data.user == "changed-user" and _n1_node.data.ssh_port == 2222
      and _n1_node.data.key_path == "/keys/n1.pem",
      f"user={_n1_node.data.user!r} port={_n1_node.data.ssh_port} key={_n1_node.data.key_path!r}")
check("N1 E2E: terminal window spawned once", len(_spawned) == 1, str(len(_spawned)))
_top_cmd = win.undo_stack.command(win.undo_stack.count() - 1) if win.undo_stack.count() else None
check("N1 E2E: CmdEditNodeData on the undo stack",
      isinstance(_top_cmd, CmdEditNodeData), f"cmd={type(_top_cmd).__name__ if _top_cmd else None}")
win._undo()  # Ctrl+Z
check("N1 E2E: Ctrl+Z reverts user/key/port to the old values",
      _n1_node.data.user == "root" and _n1_node.data.ssh_port == 22
      and _n1_node.data.key_path == "",
      f"user={_n1_node.data.user!r} port={_n1_node.data.ssh_port} key={_n1_node.data.key_path!r}")
win._redo()  # Ctrl+Y
check("N1 E2E: Ctrl+Y re-applies the dialog fields",
      _n1_node.data.user == "changed-user" and _n1_node.data.ssh_port == 2222,
      f"user={_n1_node.data.user!r} port={_n1_node.data.ssh_port}")

# ════════════════════════════════════════════════════════════
# N2. Пресет «conhost» убран; старое значение конфига → "cmd"
# ════════════════════════════════════════════════════════════
print("== N2: conhost preset removed, backward-compat ==")
from modules import external_terminal as ET

check("N2: 'conhost' not in TERMINAL_CHOICES_WINDOWS",
      "conhost" not in ET.TERMINAL_CHOICES_WINDOWS, str(ET.TERMINAL_CHOICES_WINDOWS))
check("N2: Windows choices are auto/windows_terminal/cmd",
      ET.TERMINAL_CHOICES_WINDOWS == ["auto", "windows_terminal", "cmd"],
      str(ET.TERMINAL_CHOICES_WINDOWS))

_cfg_path = ET._settings_path()


def _write_cfg(d):
    os.makedirs(os.path.dirname(_cfg_path), exist_ok=True)
    with open(_cfg_path, "w", encoding="utf-8") as f:
        _json.dump(d, f)


def _read_cfg():
    try:
        with open(_cfg_path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def _clear_cfg():
    try:
        os.remove(_cfg_path)
    except OSError:
        pass


# (a) старое значение в config.json → "cmd" (Windows), файл на диске НЕ перезаписывается
_clear_cfg()
_write_cfg({"external_terminal": "conhost"})
_v = ET.load_external_terminal_setting()
if sys.platform == "win32":
    check("N2: old config value 'conhost' reads as 'cmd'", _v == "cmd", f"got={_v!r}")
else:
    check("N2: old config value 'conhost' on non-Windows → 'auto' (not a Linux preset)",
          _v == "auto", f"got={_v!r}")
check("N2: config file NOT rewritten on read (backward-compat is read-only)",
      (_read_cfg() or {}).get("external_terminal") == "conhost", str(_read_cfg()))

# (b) миграция legacy-файла: "conhost" нормализуется в "cmd" ДО записи в config.json
_clear_cfg()
_legacy_path = ET._legacy_settings_path()
with open(_legacy_path, "w", encoding="utf-8") as f:
    _json.dump({"external_terminal": "conhost"}, f)
_v = ET.load_external_terminal_setting()
_cfg = _read_cfg() or {}
check("N2: legacy migration normalizes 'conhost' to 'cmd' in config.json",
      _cfg.get("external_terminal") == "cmd", str(_cfg))
if sys.platform == "win32":
    check("N2: migrated value loads as 'cmd'", _v == "cmd", f"got={_v!r}")
check("N2: legacy file removed after migration", not os.path.exists(_legacy_path))

# (c) detect_terminal с вынужденным старым значением — никогда не возвращает "conhost"
_write_cfg({"external_terminal": "conhost"})
_dt = ET.detect_terminal()
check("N2: detect_terminal never returns 'conhost'", _dt != "conhost", str(_dt))
if sys.platform == "win32":
    check("N2: forced 'conhost' resolves to 'cmd' (cmd.exe always present)",
          _dt == "cmd", f"got={_dt!r}")

# (d) build_command: "conhost" — алиас "cmd"; команды с conhost.exe больше нет
_c_cmd = ET.build_command("cmd", "h1", "root")
_c_con = ET.build_command("conhost", "h1", "root")
check("N2: build_command('conhost') is an alias of build_command('cmd')",
      _c_con == _c_cmd, f"conhost={_c_con} cmd={_c_cmd}")
check("N2: no command starts with conhost.exe anymore",
      _c_con[0] == "cmd.exe", str(_c_con[:3]))

# (e) комбобокс диалога не содержит «conhost»
_dlg_n2 = SSHConnectDialog(ServerData(id="n2srv00", alias="N2", host="10.0.0.2", user="u"), None)
_ids = [_dlg_n2.ext_terminal_combo.itemData(i) for i in range(_dlg_n2.ext_terminal_combo.count())]
check("N2: dialog combo has no 'conhost' item", "conhost" not in _ids, str(_ids))
_dlg_n2.deleteLater()

_clear_cfg()
try:
    os.remove(_legacy_path)
except OSError:
    pass

# ════════════════════════════════════════════════════════════
# N5. SSHWorker password-ветка: look_for_keys=False, allow_agent=False
# ════════════════════════════════════════════════════════════
print("== N5: paramiko password-branch flags ==")
import paramiko as _paramiko
from modules.ssh_worker import SSHWorker


class _RecClient:
    """Фейковый SSHClient: записывает kwargs connect(), сеть не трогает."""
    instances = []

    def __init__(self):
        self.connect_kwargs = None
        _RecClient.instances.append(self)

    def set_missing_host_key_policy(self, policy):
        pass

    def get_host_keys(self):
        return {}

    def connect(self, *a, **kw):
        self.connect_kwargs = dict(kw)

    def close(self):
        pass


_orig_ssh_client = _paramiko.SSHClient
_paramiko.SSHClient = _RecClient
try:
    # (a) password-ветка — целевая проверка N5
    w_pw = SSHWorker(host="127.0.0.1", user="u", port=22, server_id="", password="pw")
    w_pw.start()
    check("N5: password worker finished", bool(w_pw.wait(5000)))
    _inst = _RecClient.instances[-1]
    _kw = _inst.connect_kwargs or {}
    check("N5: password branch passes look_for_keys=False", _kw.get("look_for_keys") is False,
          str(_kw))
    check("N5: password branch passes allow_agent=False (parity with ssh_terminal.py)",
          _kw.get("allow_agent") is False, str(_kw))

    # (b) контрольные ветки не тронуты: key-ветка и «чистый» key/agent-fallback
    _RecClient.instances.clear()
    w_key = SSHWorker(host="127.0.0.1", user="u", port=22, server_id="",
                      password="", key_path="/k/key.pem")
    w_key.start()
    check("N5: key worker finished", bool(w_key.wait(5000)))
    _kw = (_RecClient.instances[-1].connect_kwargs or {})
    check("N5 (control): key branch keeps look_for_keys=False/allow_agent=True",
          _kw.get("look_for_keys") is False and _kw.get("allow_agent") is True, str(_kw))

    _RecClient.instances.clear()
    w_pure = SSHWorker(host="127.0.0.1", user="u", port=22, server_id="",
                       password="", key_path="")
    w_pure.start()
    check("N5: pure-key worker finished", bool(w_pure.wait(5000)))
    _kw = (_RecClient.instances[-1].connect_kwargs or {})
    check("N5 (control): pure-key branch keeps look_for_keys=True/allow_agent=True",
          _kw.get("look_for_keys") is True and _kw.get("allow_agent") is True, str(_kw))
finally:
    _paramiko.SSHClient = _orig_ssh_client

# ════════════════════════════════════════════════════════════
# N4. Жизненный цикл потока при закрытии окна во время подключения
# ════════════════════════════════════════════════════════════
print("== N4: thread lifecycle on window close ==")
import modules.ssh_terminal as ST


class _SlowClient:
    """connect() блокируется на event (с клампом 10 c), потом бросает исключение."""

    def __init__(self, blocker):
        self._b = blocker

    def set_missing_host_key_policy(self, policy):
        pass

    def get_host_keys(self):
        return {}

    def connect(self, *a, **kw):
        self._b["entered"] = True
        self._b["event"].wait(10)  # кламп: тест не зависнет при любом сбое
        raise Exception("connect boom (late)")

    def close(self):
        pass


class _FailClient:
    """connect() падает сразу — контрольный живой поток."""

    def set_missing_host_key_policy(self, policy):
        pass

    def get_host_keys(self):
        return {}

    def connect(self, *a, **kw):
        raise Exception("connect boom (live)")

    def close(self):
        pass


# (a) guard: stop() ДО ошибки → error_signal не эмитится (running=False)
_blocker = {"entered": False, "event": threading.Event()}
_paramiko.SSHClient = lambda: _SlowClient(_blocker)
try:
    t_guard = ST.SSHTerminalThread("127.0.0.1", "u", 22, password="pw")
    _errors_guard = []
    t_guard.error_signal.connect(_errors_guard.append)
    t_guard.start()
    wait_until(lambda: _blocker["entered"], timeout_ms=3000)
    check("N4 guard: thread entered (blocked) connect", _blocker["entered"])
    t_guard.stop()  # окно закрылось во время подключения
    _blocker["event"].set()  # поздняя ошибка — после stop()
    check("N4 guard: thread finished", bool(t_guard.wait(5000)))
    _drain_events()
    check("N4 guard: no error_signal after stop() (running=False)",
          _errors_guard == [], str(_errors_guard))

    # (b) контроль: живой поток (без stop) ошибку доставляет
    _paramiko.SSHClient = _FailClient
    t_live = ST.SSHTerminalThread("127.0.0.1", "u", 22, password="pw")
    _errors_live = []
    t_live.error_signal.connect(_errors_live.append)
    t_live.start()
    wait_until(lambda: len(_errors_live) >= 1, timeout_ms=5000)
    check("N4 (control): live thread emits error on connect failure",
          bool(_errors_live) and "connect boom (live)" in _errors_live[0], str(_errors_live))
    t_live.wait(3000)

    # (c) реестр орфано-потоков: окно закрыто во время подключения, поток жив
    _blocker2 = {"entered": False, "event": threading.Event()}
    _paramiko.SSHClient = lambda: _SlowClient(_blocker2)
    tw = ST.SSHTerminalWindow(
        ServerData(id="n4win00", alias="N4Win", host="127.0.0.1", user="u"), None)
    tw.show()
    wait_until(lambda: _blocker2["entered"], timeout_ms=5000)
    thread_ref = tw.terminal_thread
    check("N4 orphan: thread running before close", thread_ref.isRunning())
    tw.close()  # closeEvent: stop() + wait(1500) → поток всё ещё жив → в реестр
    app.processEvents()
    check("N4 orphan: still-running thread registered after close (not destroyed)",
          thread_ref in ST._orphan_threads and thread_ref.isRunning(),
          f"registry={len(ST._orphan_threads)} running={thread_ref.isRunning()}")
    _blocker2["event"].set()  # поздняя ошибка: guard молчит, поток завершается
    wait_until(lambda: thread_ref not in ST._orphan_threads, timeout_ms=8000)
    check("N4 orphan: registry self-cleans on finished()",
          thread_ref not in ST._orphan_threads and thread_ref.isFinished(),
          f"registry={len(ST._orphan_threads)} finished={thread_ref.isFinished()}")
finally:
    _paramiko.SSHClient = _orig_ssh_client

# ════════════════════════════════════════════════════════════
# Бонус-N11. CmdAddRemoveNode(mode="add"): стэш keyring-пароля + redo
# ════════════════════════════════════════════════════════════
print("== bonus-N11: keyring stash in CmdAddRemoveNode(add) ==")
from graphics.map_scene import MapScene
from modules.undo_commands import CmdAddRemoveNode
import services.credential_manager as _cm_mod


class _FakeCM:
    """In-memory credential manager (машина без wincred не влияет на тест)."""

    def __init__(self):
        self.store = {}

    def load_password(self, sid):
        return self.store.get(sid)

    def save_password(self, sid, pw):
        self.store[sid] = pw
        return True

    def delete_password(self, sid):
        self.store.pop(sid, None)
        return True


class _DummyWin:
    def _post_undo_refresh(self):
        pass


_fake_cm = _FakeCM()
_orig_get_cm = _cm_mod.get_credential_manager
_cm_mod.get_credential_manager = lambda: _fake_cm
try:
    scene = MapScene()
    stack = QUndoStack()

    # (a) сценарий дублирования: пароль уже скопирован под новым id ДО push'а команды
    scene.add_server(ServerData(id="orig1111", alias="Orig", host="10.0.0.1", user="u"))
    _fake_cm.store["dup2222"] = "secret-pw"  # имитация _duplicate_node
    cmd_dup = CmdAddRemoveNode(_DummyWin(), scene,
                               ServerData(id="dup2222", alias="Orig-copy",
                                          host="10.0.0.1", user="u"), "add")
    check("N11: password stashed at command creation (mode=add)",
          cmd_dup._stashed_password == "secret-pw", repr(cmd_dup._stashed_password))
    stack.push(cmd_dup)  # push сам выполняет redo
    check("N11: redo adds the node", scene.has_node("dup2222"))
    stack.undo()  # undo("add"): remove_server + delete keyring-пароля
    check("N11: undo removes node AND its keyring record",
          not scene.has_node("dup2222") and "dup2222" not in _fake_cm.store,
          str(_fake_cm.store))
    stack.redo()  # redo: узел обратно + пароль ВОССТАНОВЛЕН (Ctrl+Z→Ctrl+Y)
    check("N11: redo restores the copy WITH its password",
          scene.has_node("dup2222") and _fake_cm.store.get("dup2222") == "secret-pw",
          str(_fake_cm.store))

    # (b) свежее добавление: записи в keyring нет — стэш пустой, restore no-op
    cmd_new = CmdAddRemoveNode(_DummyWin(), scene,
                               ServerData(id="new3333", alias="New",
                                          host="10.0.0.2", user="u"), "add")
    check("N11: fresh add — empty stash (no keyring record)",
          cmd_new._stashed_password is None, repr(cmd_new._stashed_password))
    stack.push(cmd_new)
    stack.undo()
    stack.redo()
    check("N11: fresh add survives undo/redo without phantom password",
          scene.has_node("new3333") and "new3333" not in _fake_cm.store, str(_fake_cm.store))

    # (c) E2E: MainWindow._duplicate_node → Ctrl+Z → Ctrl+Y
    win2 = MW.MainWindow()
    win2.show()
    app.processEvents()
    node_a = win2.scene.add_server(
        ServerData(id="origAAAA", alias="OrigE2E", host="10.5.5.5", user="u"))
    _fake_cm.store["origAAAA"] = "orig-pw"
    new_node = win2._duplicate_node(node_a)
    check("N11 E2E: duplicate created + password copied under the new id",
          new_node is not None and _fake_cm.store.get(new_node.data.id) == "orig-pw",
          f"new_id={getattr(new_node, 'data', None) and new_node.data.id} store={_fake_cm.store}")
    if new_node is not None:
        _dup_id = new_node.data.id
        win2._undo()  # Ctrl+Z
        check("N11 E2E: undo removes the duplicate + its keyring record",
              not win2.scene.has_node(_dup_id) and _dup_id not in _fake_cm.store,
              str(_fake_cm.store))
        win2._redo()  # Ctrl+Y
        check("N11 E2E: redo brings the copy back WITH its password",
              win2.scene.has_node(_dup_id) and _fake_cm.store.get(_dup_id) == "orig-pw",
              str(_fake_cm.store))
finally:
    _cm_mod.get_credential_manager = _orig_get_cm

# ════════════════════════════════════════════════════════════
# Состояние релиза (пины — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

finish()
