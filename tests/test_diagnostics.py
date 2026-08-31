"""services/diagnostics.py: PingThread + ReverseDnsThread (v0.9.9.3).

ROADMAP v0.9.9.3 — фаза 0 серии «Гигиена main_window.py»: _PingThread/_ReverseDnsThread
перенесены из ui/main_window.py (были вложены прямо в методы _ping_node/_copy_node_info)
в services/diagnostics.py. НУЛЕВОЕ изменение поведения: те же сигналы
(finished_ping(bool, str), resolved(str)), те же командные строки ping'а (AUDIT v0.9.5.5 #4),
те же i18n-ключи; паттерн «модуль + колбэки» — MainWindow держит ссылки на потоки
(self._ping_thread/self._dns_thread) и подключает локальные замыкания.

  * перенесённые классы: подклассы QThread, сигналы с той же сигнатурой (emit из Python);
  * гигиена: вложенные Thread-классы из main_window.py исчезли, импорты — services.diagnostics;
  * ReverseDnsThread: успех (monkeypatch gethostbyaddr) + fallback на host при herror;
  * PingThread: ok/fail/exception-пути через фейковый subprocess.run + командная строка по ОС;
  * регрессия MainWindow (offscreen): _ping_node (старт/финиш, self-cleanup, guard AUDIT v0.7.2 #8),
    _copy_node_info(hostname) — буфер обмена + статус-бар + cleanup _dns_thread.

Запуск: python tests/test_diagnostics.py   (из корня проекта) или python tests/run_all.py
"""
import platform as _platform
import socket as _socket
import subprocess as _subprocess
import sys

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)

import ui.main_window as MW
from models.server import ServerData
import services.diagnostics as diag
from i18n import t as _t


# ══ 1. Перенесённые классы: API и сигнатуры сигналов ═══════════════
print("== v0.9.9.3 diagnostics: moved classes ==")

check("PingThread is a QThread subclass", issubclass(diag.PingThread, QThread))
check("ReverseDnsThread is a QThread subclass", issubclass(diag.ReverseDnsThread, QThread))

# Сигналы с той же сигнатурой, что у бывших вложенных классов: emit из Python
# (прямое подключение — синхронно) с неверным числом аргументов дал бы TypeError.
_ping_probe = diag.PingThread("probe-host")
_got_ping = []
_ping_probe.finished_ping.connect(lambda ok, text: _got_ping.append((ok, text)))
_ping_probe.finished_ping.emit(True, "x")
check("PingThread.finished_ping(bool, str) keeps its signature", _got_ping == [(True, "x")],
      str(_got_ping))

_dns_probe = diag.ReverseDnsThread("probe-host")
_got_dns = []
_dns_probe.resolved.connect(lambda name: _got_dns.append(name))
_dns_probe.resolved.emit("resolved-name")
check("ReverseDnsThread.resolved(str) keeps its signature", _got_dns == ["resolved-name"],
      str(_got_dns))

# ══ 2. Гигиена main_window.py: вложенные Thread-классы исчезли ═════
_mw_src_path = sys.modules[MW.__name__].__file__
with open(_mw_src_path, encoding="utf-8") as f:
    _mw_src = f.read()
check("main_window.py: no nested 'class _PingThread'", "class _PingThread" not in _mw_src)
check("main_window.py: no nested 'class _ReverseDnsThread'", "class _ReverseDnsThread" not in _mw_src)
check("main_window.py imports PingThread from services.diagnostics",
      "from services.diagnostics import PingThread" in _mw_src)
check("main_window.py imports ReverseDnsThread from services.diagnostics",
      "from services.diagnostics import ReverseDnsThread" in _mw_src)


# ══ 3. ReverseDnsThread: поведение (hermetic, без реального DNS) ════
print("== v0.9.9.3 diagnostics: ReverseDnsThread ==")

_real_gethostbyaddr = _socket.gethostbyaddr

# успех: резолв отдал имя
_socket.gethostbyaddr = lambda ip: ("diag-host.example", [], ["10.9.8.7"])
try:
    dns_ok = diag.ReverseDnsThread("10.9.8.7")
    _dns_name = {}
    dns_ok.resolved.connect(lambda name: _dns_name.update(name=name))
    dns_ok.start()
    wait_until(lambda: "name" in _dns_name, timeout_ms=5000)
    check("ReverseDnsThread resolves the name via gethostbyaddr",
          _dns_name.get("name") == "diag-host.example", str(_dns_name))
finally:
    dns_ok.wait(3000)

# сбой: DNS не отдал имя → fallback на сам host (как раньше, AUDIT v0.7.2 #6)
def _no_ptr(ip):
    raise _socket.herror("simulated: no PTR record")

_socket.gethostbyaddr = _no_ptr
try:
    dns_fail = diag.ReverseDnsThread("192.0.2.77")
    _dns_name2 = {}
    dns_fail.resolved.connect(lambda name: _dns_name2.update(name=name))
    dns_fail.start()
    wait_until(lambda: "name" in _dns_name2, timeout_ms=5000)
    check("ReverseDnsThread falls back to host when DNS fails",
          _dns_name2.get("name") == "192.0.2.77", str(_dns_name2))
finally:
    dns_fail.wait(3000)
    _socket.gethostbyaddr = _real_gethostbyaddr


# ══ 4. PingThread: поведение (hermetic, фейковый subprocess.run) ════
print("== v0.9.9.3 diagnostics: PingThread ==")

class _FakeProc:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


_real_run = _subprocess.run
HOST = "192.0.2.66"  # TEST-NET-1: в реальных прогонах недостижим (см. интеграцию ниже)

# ВАЖНО: фейк перехватывает только ping — остальные вызовы subprocess.run (например,
# platform._syscmd_ver → `cmd /c ver` внутри platform.system()) проходят на реальный run,
# иначе глобальный патч ломает платформенный кэш и тест падает не по своей вине.

def _pass_through(cmd, **kw):
    if not (isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]).lower() == "ping"):
        return _real_run(cmd, **kw)
    return None


# ok-путь: returncode 0 → finished_ping(True, i18n status.ping_ok) + командная строка по ОС
_captured = {}

def _fake_run_ok(cmd, **kw):
    passthrough = _pass_through(cmd, **kw)
    if passthrough is not None:
        return passthrough
    _captured.update(cmd=cmd, kw=kw)
    return _FakeProc(0)

_subprocess.run = _fake_run_ok
try:
    ping_ok = diag.PingThread(HOST)
    _res_ping = {}
    ping_ok.finished_ping.connect(lambda ok, text: _res_ping.update(ok=ok, text=text))
    ping_ok.start()
    wait_until(lambda: "text" in _res_ping, timeout_ms=5000)
    check("PingThread emits finished_ping(True, …) on returncode 0",
          _res_ping.get("ok") is True, str(_res_ping))
    check("PingThread ok-message is i18n status.ping_ok (not raw key)",
          _res_ping.get("text") == _t("status.ping_ok", host=HOST)
          and not _res_ping.get("text", "").startswith("status."),
          str(_res_ping))
    if _platform.system() == "Windows":
        check("PingThread cmd on Windows: ping -n 3 -w 3000 <host>",
              _captured.get("cmd") == ["ping", "-n", "3", "-w", "3000", HOST],
              str(_captured.get("cmd")))
        check("PingThread on Windows uses CREATE_NO_WINDOW",
              _captured.get("kw", {}).get("creationflags") == _subprocess.CREATE_NO_WINDOW,
              str(_captured.get("kw")))
    else:
        check("PingThread cmd on POSIX: ping -c 3 -W 3 -- <host>",
              _captured.get("cmd") == ["ping", "-c", "3", "-W", "3", "--", HOST],
              str(_captured.get("cmd")))
finally:
    ping_ok.wait(3000)

# fail-путь: returncode != 0 → finished_ping(False, i18n status.ping_failed + хвост вывода)
_LONG_OUT = ("Request to " + HOST + " timed out. \n") * 40  # > 400 байт — проверим обрезку

def _fake_run_fail(cmd, **kw):
    passthrough = _pass_through(cmd, **kw)
    if passthrough is not None:
        return passthrough
    return _FakeProc(1, _LONG_OUT.encode())

_subprocess.run = _fake_run_fail
try:
    ping_fail = diag.PingThread(HOST)
    _res_ping2 = {}
    ping_fail.finished_ping.connect(lambda ok, text: _res_ping2.update(ok=ok, text=text))
    ping_fail.start()
    wait_until(lambda: "text" in _res_ping2, timeout_ms=5000)
    check("PingThread emits finished_ping(False, …) on returncode 1",
          _res_ping2.get("ok") is False, str(_res_ping2))
    _expected_full = _t("status.ping_failed", host=HOST) + "\n" + _LONG_OUT[-400:]
    check("PingThread fail-message = i18n status.ping_failed + tail of stdout (400 chars)",
          _res_ping2.get("text") == _expected_full, str(_res_ping2)[:120])
finally:
    ping_fail.wait(3000)

# exception-путь: subprocess.run выбросил → finished_ping(False, … (exc))
def _fake_run_exc(cmd, **kw):
    if not (isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]).lower() == "ping"):
        return _real_run(cmd, **kw)
    raise _subprocess.TimeoutExpired(cmd, 15)

_subprocess.run = _fake_run_exc
try:
    ping_exc = diag.PingThread(HOST)
    _res_ping3 = {}
    ping_exc.finished_ping.connect(lambda ok, text: _res_ping3.update(ok=ok, text=text))
    ping_exc.start()
    wait_until(lambda: "text" in _res_ping3, timeout_ms=5000)
    # str(TimeoutExpired(cmd, 15)) — «Command […] timed out after 15 seconds» (все платформы)
    check("PingThread emits finished_ping(False, …) when subprocess.run raises",
          _res_ping3.get("ok") is False
          and _res_ping3.get("text", "").startswith(_t("status.ping_failed", host=HOST))
          and "timed out" in _res_ping3.get("text", ""),
          str(_res_ping3)[:160])
finally:
    ping_exc.wait(3000)
    _subprocess.run = _real_run


# ══ 5. Регрессия MainWindow (offscreen): связка «модуль + колбэки» ══
print("== v0.9.9.3 diagnostics: MainWindow regression ==")

win = MW.MainWindow()
_node = win.scene.add_server(ServerData(id="diagnode", alias="diag", host=HOST, user="root"))
check("fixture: node on scene + window has _ping_thread/_dns_thread slots",
      _node is not None and hasattr(win, "_ping_thread") and hasattr(win, "_dns_thread"))

# 5a. _ping_node — реальный (быстрый) ping TEST-NET-хоста: поток стартует и завершается.
# Headless-герметичность: при неудаче слот показывает МОДАЛЬНЫЙ QMessageBox.information()
# — в offscreen его никто не закроет (паттерн test_context_menus.py).
_real_qmb_info = QMessageBox.information
_ping_dialog_calls = []
QMessageBox.information = staticmethod(lambda *a, **kw: (_ping_dialog_calls.append(a), 0)[1])
try:
    win._ping_node(_node)
    check("_ping_node starts a services.diagnostics.PingThread",
          win._ping_thread is not None and type(win._ping_thread).__module__ == diag.__name__,
          repr(type(win._ping_thread)))
    check("_ping_node shows ping_running in status bar on start",
          HOST in (win.statusBar().currentMessage() or ""),
          win.statusBar().currentMessage())
    wait_until(lambda: win._ping_thread is None, timeout_ms=25000)
    check("_ping_node thread finishes and clears self._ping_thread", win._ping_thread is None)
    check("failed ping → modal info dialog with host in text (stubbed offscreen)",
          len(_ping_dialog_calls) == 1 and HOST in _ping_dialog_calls[0][2],
          str(_ping_dialog_calls)[:160])
finally:
    QMessageBox.information = _real_qmb_info

# 5b. Guard AUDIT v0.7.2 #8: повторный ping во время работающего игнорируется.
class _FakeRunningThread:
    def isRunning(self):
        return True

_fake_busy = _FakeRunningThread()
win._ping_thread = _fake_busy
try:
    win._ping_node(_node)
    check("guard: second _ping_node while one runs is ignored (no new thread)",
          win._ping_thread is _fake_busy, repr(win._ping_thread))
    check("guard: status bar shows ping_running for the busy host",
          HOST in (win.statusBar().currentMessage() or ""),
          win.statusBar().currentMessage())
finally:
    win._ping_thread = None

# 5c. _copy_node_info(hostname) — обратный DNS через ReverseDnsThread: буфер + статус-бар.
_socket.gethostbyaddr = lambda ip: ("diag-win-host", [], [HOST])
try:
    win._copy_node_info(_node, "hostname")
    check("_copy_node_info(hostname) starts a services.diagnostics.ReverseDnsThread",
          win._dns_thread is not None and type(win._dns_thread).__module__ == diag.__name__,
          repr(type(win._dns_thread)))
    wait_until(lambda: QApplication.clipboard().text() == "diag-win-host", timeout_ms=8000)
    check("_copy_node_info(hostname) copies resolved name to clipboard",
          QApplication.clipboard().text() == "diag-win-host",
          QApplication.clipboard().text())
    check("…and cleans self._dns_thread after completion", win._dns_thread is None)
    check("…with copied_to_clipboard status message",
          "diag-win-host" in (win.statusBar().currentMessage() or ""),
          win.statusBar().currentMessage())
finally:
    _socket.gethostbyaddr = _real_gethostbyaddr

# 5d. _copy_node_info(ip) — синхронный путь без сети (fallback на host при пустом ip).
win._copy_node_info(_node, "ip")
check("_copy_node_info(ip) copies host fallback synchronously (no thread)",
      QApplication.clipboard().text() == HOST and win._dns_thread is None,
      QApplication.clipboard().text())

finish()
