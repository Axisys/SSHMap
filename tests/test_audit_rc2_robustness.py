# -*- coding: utf-8 -*-
"""v1.2.10rc2 — Аудит: робастность и гигиена кода (AUDIT.md ручной #5, авто #7, ручной #6).

Тематический тест релиза (ROADMAP v1.2.10rc2; offscreen/headless — без сети):

§1 server_data_from_dict с int-id (ручной #5e): явный "id": 123 в JSON → str("123");
   отсутствующий/пустой id — генерируется как раньше (регрессия); строковый id
   проходит без изменений.

§2 PingThread с хостом «-x» (ручной #5d): subprocess.run НЕ вызывается (mock),
   сигнал finished_ping(False, …) — Windows ping не поддерживает «--», а такой
   хост невалиден как DNS-имя и так; guard срабатывает ДО запуска процесса.
   Регрессия: обычный хост запускает subprocess как раньше.

§3 Поздние worker-сигналы на уничтоженный диалог (ручной #5c): closeEvent отвязал
   worker'а setParent(None) (стр. 497), C++-объект диалога уничтожен — поздний
   success/error БЕЗ RuntimeError (guard в слоте); worker доживает подключение,
   поздний emit обрабатывается event loop'ом без краха.

§4 delete_password при фейковом keyring.errors БЕЗ PasswordDeleteError (ручной #6):
   общий обработчик, возвращает False, без падения; класс на месте → True (то же
   поведение, что до фикса); NoKeyringError → True (регрессия). Явный `import keyring`
   в _try_init (авто #7) — source-проверка.

§5 file_dups-призрак (ручной #5b) + комментарий к ANSI_ESCAPE_RE (ручной #5a):
   source-проверки (код ANSI_ESCAPE_RE не меняется — защищён конвенцией).

§6 Состояние релиза + i18n-паритет (427 — новых ключей НЕТ).

Запуск:  python tests/test_audit_rc2_robustness.py   (из корня проекта) или python tests/run_all.py
"""
import os
import re
import sys
import threading
import time
import types

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import QThread, Qt, Signal as QtSignal
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import keyring as _kr_mod
import subprocess as _subprocess
import services.diagnostics as diag
from models.server import ServerData, server_data_from_dict
from services.credential_manager import CredentialManager


# ════════════════════════════════════════════════════════════
# 1. server_data_from_dict: int-id → str (AUDIT ручной #5e)
# ════════════════════════════════════════════════════════════
print("== §1 server_data_from_dict: int id → str ==")

d = server_data_from_dict({"id": 123, "alias": "a", "host": "h", "user": "u"})
check("int id 123 → '123' (str)", d.id == "123" and type(d.id) is str, repr(d.id))

d2 = server_data_from_dict({"id": "abcd1234", "alias": "a", "host": "h", "user": "u"})
check("строковый id проходит без изменений", d2.id == "abcd1234", repr(d2.id))

d3 = server_data_from_dict({"alias": "a", "host": "h", "user": "u"})
check("отсутствующий id — генерируется (регрессия)",
      isinstance(d3.id, str) and len(d3.id) == 8, repr(d3.id))

d4 = server_data_from_dict({"id": "", "alias": "a", "host": "h", "user": "u"})
check("пустой id — генерируется (регрессия)",
      isinstance(d4.id, str) and len(d4.id) == 8, repr(d4.id))


# ════════════════════════════════════════════════════════════
# 2. PingThread с хостом «-x»: guard ДО subprocess (AUDIT ручной #5d)
# ════════════════════════════════════════════════════════════
print("== §2 PingThread host '-x': no subprocess ==")


def _run_ping(host):
    """PingThread.run() напрямую, без start() — паттерн test_diagnostics.py."""
    got = []
    t = diag.PingThread(host)
    t.finished_ping.connect(lambda ok, text: got.append((ok, text)))
    t.run()
    return got


# Хост «-x»: subprocess запускать нельзя (Windows ping не знает «--»).
calls = []
_orig_run = _subprocess.run


def _boom(cmd, *a, **k):
    calls.append(cmd)
    raise AssertionError(f"subprocess.run вызван для хоста '-x': {cmd}")


_subprocess.run = _boom
try:
    got = _run_ping("-x")
finally:
    _subprocess.run = _orig_run
check("хост «-x»: subprocess.run не вызван", calls == [])
check("хост «-x»: finished_ping(False, …)", len(got) == 1 and got[0][0] is False, repr(got))

# Регрессия: обычный хост — subprocess запускается как раньше.
calls2 = []


class _FakeProc:
    returncode = 0
    stdout = b""


def _fake_ok(cmd, *a, **k):
    calls2.append(cmd)
    return _FakeProc()


_subprocess.run = _fake_ok
try:
    got2 = _run_ping("192.0.2.7")
finally:
    _subprocess.run = _orig_run
check("обычный хост: subprocess.run вызван один раз", len(calls2) == 1, repr(calls2))
check("обычный хост: finished_ping(True, …)", len(got2) == 1 and got2[0][0] is True, repr(got2))
check("хост на командной строке ping'а", "192.0.2.7" in calls2[0], repr(calls2[0]))


# ════════════════════════════════════════════════════════════
# 3. Поздние worker-сигналы на уничтоженный диалог (AUDIT ручной #5c)
# ════════════════════════════════════════════════════════════
print("== §3 late worker signals on destroyed dialog ==")

import dialogs.ssh_connect_dialog as SCD_mod


class _FakeWorker(QThread):
    """Фейковый SSHWorker (те же сигналы/конструктор): run() висит до release() —
    как paramiko-подключение, доживающее дольше 2 c wait-бюджета closeEvent."""

    success = QtSignal(str)
    error = QtSignal(str)

    def __init__(self, host, user, port, server_id, password="", key_path="",
                 test_only=False, parent=None):
        super().__init__(parent)
        self.test_only = test_only
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # «подключение» — живёт дольше бюджета closeEvent
        try:
            self.success.emit("late success")
        except RuntimeError:
            pass  # диалог уничтожен — поздний emit без приёмников безопасен

    def release(self):
        self._release.set()


def _alive(w):
    """Жив ли C++-объект (паттерн test_terminal_page.py: после уничтожения любой
    C++-вызов на Python-обёртке бросает «Internal C++ object already deleted»)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:
        return False


_orig_worker_cls = SCD_mod.SSHWorker
worker = None
try:
    SCD_mod.SSHWorker = _FakeWorker   # шов: имя класса в namespace модуля dialogs
    dlg = SCD_mod.SSHConnectDialog(
        ServerData(id="rc2late", alias="late", host="10.99.8.1", user="root"), None)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)   # C++-объект умрёт после close()
    dlg._start_worker(test_only=False)
    worker = dlg._ssh_worker
    wait_until(lambda: worker is not None and worker.isRunning(), timeout_ms=3000)
    check("fixture: фейковый worker запущен (parent=диалог)",
          worker is not None and worker.isRunning() and worker.parent() is dlg,
          repr(worker))

    # Закрытие диалога при живом worker'е: closeEvent ждёт ~2 c wait-бюджет и
    # отвязывает worker'а setParent(None) (стр. 497) — он переживёт диалог;
    # WA_DeleteOnClose уничтожает C++-объект после closeEvent.
    _t0 = time.monotonic()
    dlg.close()
    _el = time.monotonic() - _t0
    check("close() дождался бюджета (~2 c), не завис", 1.8 <= _el < 6.0, f"{_el:.2f}s")
    check("worker отвязан: parent == None (setParent(None))", worker.parent() is None)
    wait_until(lambda: not _alive(dlg), timeout_ms=4000)
    check("fixture: C++-объект диалога уничтожен", not _alive(dlg))

    # Поздний success/error на уничтоженный диалог: до фикса — RuntimeError из слота
    # (PySide печатает и глотает в Qt-диспетче), после — guard молча проглатывает.
    try:
        dlg._on_worker_success("late success")
        _ok_s, _err_s = True, ""
    except RuntimeError as e:
        _ok_s, _err_s = False, str(e)
    check("поздний _on_worker_success на уничтоженный диалог — без RuntimeError",
          _ok_s, _err_s)

    try:
        dlg._on_worker_error("late error")
        _ok_e, _err_e = True, ""
    except RuntimeError as e:
        _ok_e, _err_e = False, str(e)
    check("поздний _on_worker_error на уничтоженный диалог — без RuntimeError",
          _ok_e, _err_e)

    # E2E: worker доживает подключение и эмитит поздний success из своего потока;
    # Qt-соединения с мёртвым диалогом сняты при его уничтожении — доставка no-op,
    # event loop обрабатывает всё без краха процесса.
    worker.release()
    wait_until(lambda: not worker.isRunning(), timeout_ms=8000)
    check("worker завершён, процесс жив (поздний emit обработан)", not worker.isRunning())
finally:
    SCD_mod.SSHWorker = _orig_worker_cls
    if worker is not None:
        try:
            worker.release()   # ВСЕГДА — незакрытый фейк не даёт warning на выходе
        except RuntimeError:
            pass


# ════════════════════════════════════════════════════════════
# 4. delete_password: фейковый keyring.errors (AUDIT ручной #6 + авто #7)
# ════════════════════════════════════════════════════════════
print("== §4 delete_password with fake keyring.errors ==")


class _FakeBackend:
    """Фейковый бэкенд: delete_password всегда бросает заданное исключение."""

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def delete_password(self, service, username):
        self.calls += 1
        raise self._exc("fake failure")


def _make_cm(exc):
    cm = CredentialManager.__new__(CredentialManager)  # мимо _try_init — реальный keyring не в деле
    cm._keyring_backend = _FakeBackend(exc)
    cm._backend_available = True
    return cm


class _NoKeyringError(Exception):
    pass


def _swap_keyring_errors(fake_mod):
    """Подмена sys.modules['keyring.errors'] И атрибута пакета keyring (оба пути:
    `import keyring.errors` берёт из sys.modules, `keyring.errors.X` — через атрибут)."""
    orig_mod = sys.modules.get("keyring.errors")
    orig_attr = getattr(_kr_mod, "errors", None)
    sys.modules["keyring.errors"] = fake_mod
    _kr_mod.errors = fake_mod
    return (orig_mod, orig_attr)


def _restore_keyring_errors(saved):
    orig_mod, orig_attr = saved
    if orig_mod is not None:
        sys.modules["keyring.errors"] = orig_mod
    else:
        sys.modules.pop("keyring.errors", None)
    _kr_mod.errors = orig_attr


# (a) keyring БЕЗ PasswordDeleteError → общий обработчик, False, без падения.
fake_a = types.ModuleType("keyring.errors")
fake_a.NoKeyringError = _NoKeyringError   # PasswordDeleteError намеренно НЕТ
saved_a = _swap_keyring_errors(fake_a)
try:
    cm_a = _make_cm(RuntimeError)         # чужое исключение — не NoKeyringError
    res_a = cm_a.delete_password("rc2del")
    check("без PasswordDeleteError → общий обработчик, возвращает False",
          res_a is False, repr(res_a))
    check("бэкенд вызван (исключение из delete_password)", cm_a._keyring_backend.calls == 1)
finally:
    _restore_keyring_errors(saved_a)

# (b) keyring С PasswordDeleteError → True (то же поведение, что до фикса).
class _PasswordDeleteError(Exception):
    pass


fake_b = types.ModuleType("keyring.errors")
fake_b.NoKeyringError = _NoKeyringError
fake_b.PasswordDeleteError = _PasswordDeleteError
saved_b = _swap_keyring_errors(fake_b)
try:
    cm_b = _make_cm(_PasswordDeleteError)
    res_b = cm_b.delete_password("rc2del")
    check("PasswordDeleteError на месте → True (запись отсутствовала)",
          res_b is True, repr(res_b))
finally:
    _restore_keyring_errors(saved_b)

# (c) NoKeyringError → True (регрессия существующего поведения, реальный модуль).
import keyring.errors as _kre_real
cm_c = _make_cm(_kre_real.NoKeyringError)
res_c = cm_c.delete_password("rc2del")
check("NoKeyringError → True (удалять нечего)", res_c is True, repr(res_c))

# (d) авто #7: явный `import keyring` в _try_init — source-проверка.
_src_cm = open(os.path.join(ROOT, "services", "credential_manager.py"), encoding="utf-8").read()
_m = re.search(r"def _try_init\(self\):(.*?)(?=\n    @property|\n    def )", _src_cm, re.S)
_body = _m.group(1) if _m else ""
check("авто #7: явный 'import keyring' в _try_init (не только keyring.errors)",
      re.search(r"^\s+import keyring\s*$", _body, re.M) is not None)


# ════════════════════════════════════════════════════════════
# 5. Гигиена: file_dups-призрак + комментарий к ANSI_ESCAPE_RE (source)
# ════════════════════════════════════════════════════════════
print("== §5 hygiene: file_dups ghost + ANSI_ESCAPE_RE comment ==")

_src_ops = open(os.path.join(ROOT, "ui", "main_window_node_ops.py"), encoding="utf-8").read()
# Призрак — именно эти две конструкции (комментарий с историей упоминать вправе).
check("ручной #5b: file_dups-призрак убран (кодовых ссылок нет)",
      "entries, file_dups" not in _src_ops and "len(file_dups)" not in _src_ops)

_src_term = open(os.path.join(ROOT, "modules", "ssh_terminal.py"), encoding="utf-8").read()
_i = _src_term.find("ANSI_ESCAPE_RE = re.compile")
_head = _src_term[max(0, _i - 700):_i] if _i >= 0 else ""
check("ручной #5a: комментарий к ANSI_ESCAPE_RE — tests/test_core.py + «Не трогать»",
      "tests/test_core.py" in _head and "Не трогать" in _head, _head[-200:])


# ════════════════════════════════════════════════════════════
# 6. Состояние релиза + i18n-паритет (427 — новых ключей НЕТ)
# ════════════════════════════════════════════════════════════
print("== §6 release state + i18n parity ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
