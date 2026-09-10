# -*- coding: utf-8 -*-
"""v1.2.10rc1 — Аудит: потоки и teardown (AUDIT.md авто #2 + ручной #1 + находка верификации).

Тематический тест релиза (ROADMAP v1.2.10rc1; offscreen, фейковые потоки — без сети):

§1 DNS-guard (авто #2): два быстрых «Copy Hostname» → ОДИН ReverseDnsThread,
   повторный запрос игнорируется со статус-сообщением (без затирания работающего
   потока); поток создаётся с parent=MainWindow; после finished() — cleanup
   self._dns_thread + буфер обмена; guard снимается — следующий запрос стартует.

§2 closeEvent с висящим фейковым DNS-потоком (находка верификации): окно закрывается
   в wait-бюджете (~2 c, не зависает), переживший поток — в orphan-реестре
   services/diagnostics._orphan_threads (не оставлен на GC: «QThread: Destroyed
   while thread is still running»), реестр самочищается по finished().

§3 Шатдаун с 2 активными терминальными сессиями при terminal_close_behavior="ask"
   (ручной #1, реальный баг): НОЛЬ QMessageBox.question (шов ST.QMessageBox.question
   подменён) — «ask»-гейт пропускается через _force_close (путь лимита v1.1.1),
   главное окно закрыто; пережившие потоки — в ST._orphan_threads (N4-путь).

§4 Состояние релиза + i18n-паритет (427 — новых ключей НЕТ: guard-сообщение
   переиспользует существующий status.import_resolving).

Запуск:  python tests/test_audit_rc1_threads.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import QThread, Signal as QtSignal
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

import services.diagnostics as diag
import modules.ssh_terminal as ST
import ui.main_window as MW
from models.server import ServerData


# ════════════════════════════════════════════════════════════
# Обвязка: фейковые потоки (тот же API, что у реальных)
# ════════════════════════════════════════════════════════════

class _HangingDnsThread(QThread):
    """Фейковый ReverseDnsThread: run() висит до release() (недоступный резолвер —
    getaddrinfo доживает свой таймаут), МЕТОДА stop() НЕТ — ровно как у реального
    ReverseDnsThread/PingThread (находка верификации)."""

    resolved = QtSignal(str)

    def __init__(self, host_, parent=None):
        super().__init__(parent)
        self._host = host_
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # «getaddrinfo» — stop() не прерывает (его нет)
        try:
            self.resolved.emit(self._host)
        except RuntimeError:
            pass  # окно уже уничтожено — поздний emit без приёмников безопасен

    def release(self):
        self._release.set()


class _BlockingTermThread(QThread):
    """Фейковый SSHTerminalThread: run() блокируется до release(); stop() лишь
    выставляет running=False и НЕ прерывает run() — как paramiko-подключение
    с timeout 15 c (сценарий N4 v1.1.2RC1)."""

    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.host, self.user, self.port = host, user, port
        self.password, self.key_path = password, key_path
        self.client = None
        self.channel = None
        self.running = True
        self.stop_calls = 0
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # «подключение» — stop() не прерывает
        self.running = False
        try:
            self.closed_signal.emit()
        except RuntimeError:
            pass  # страница уже уничтожена — поздний emit без приёмников безопасен

    def stop(self):
        self.stop_calls += 1
        self.running = False     # НЕ прерывает run() (recv-цикл выходит сам за ~30 мс)

    def release(self):
        self._release.set()


def _cfg_path():
    return os.path.join(os.path.expanduser("~"), ".sshmap", "config.json")


def write_config(d):
    p = _cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)


def clear_config():
    try:
        os.remove(_cfg_path())
    except OSError:
        pass


# ════════════════════════════════════════════════════════════
# 1. DNS-guard (AUDIT авто #2): повторный «Copy Hostname» не затирает поток
# ════════════════════════════════════════════════════════════
print("== §1 DNS guard: second 'Copy Hostname' is ignored ==")

clear_config()
win = MW.MainWindow()
node = win.scene.add_server(ServerData(id="rc1-dns", alias="rc1", host="192.0.2.55", user="root"))

_orig_dns_cls = diag.ReverseDnsThread
diag.ReverseDnsThread = _HangingDnsThread   # шов: импорт внутри _copy_node_info — по модулю
th1 = th3 = None
try:
    # Первый «Copy Hostname» — поток стартует и висит (недоступный резолвер).
    win._copy_node_info(node, "hostname")
    th1 = win._dns_thread
    wait_until(lambda: th1 is not None and th1.isRunning(), timeout_ms=3000)
    check("первый Copy Hostname: ReverseDnsThread запущен",
          th1 is not None and th1.isRunning())
    check("поток создан с parent=MainWindow (v1.2.10rc1)", th1.parent() is win,
          repr(th1.parent()))

    # Второй быстрый «Copy Hostname» — guard: без затирания + статус-сообщение.
    win._copy_node_info(node, "hostname")
    check("guard: self._dns_thread НЕ затёрт (один поток)", win._dns_thread is th1,
          repr(win._dns_thread))
    _expected_guard = win.t("status.import_resolving", done=0, total=1)
    check("guard: статус-сообщение показано (существующий ключ — без новых i18n)",
          win.statusBar().currentMessage() == _expected_guard,
          win.statusBar().currentMessage())

    # Завершение: release → resolved → буфер обмена + cleanup self._dns_thread.
    th1.release()
    wait_until(lambda: win._dns_thread is None, timeout_ms=5000)
    check("после finished(): self._dns_thread очищен", win._dns_thread is None)
    check("резолвлённое имя скопировано в буфер", QApplication.clipboard().text() == "192.0.2.55",
          QApplication.clipboard().text())

    # Guard снят: следующий запрос стартует НОВЫЙ поток.
    win._copy_node_info(node, "hostname")
    th3 = win._dns_thread
    wait_until(lambda: th3 is not None and th3.isRunning(), timeout_ms=3000)
    check("после завершения: следующий Copy Hostname стартует новый поток",
          th3 is not None and th3 is not th1 and th3.isRunning())
finally:
    for _th in (th1, th3):   # release() ВСЕГДА — незакрытый фейк не даёт warning на выходе
        if _th is not None:
            try:
                _th.release()
            except RuntimeError:
                pass
    diag.ReverseDnsThread = _orig_dns_cls


# ════════════════════════════════════════════════════════════
# 2. closeEvent с висящим DNS-потоком (находка верификации):
#    окно закрывается в бюджете, поток — в orphan-реестре до finished()
# ════════════════════════════════════════════════════════════
print("== §2 closeEvent + hanging DNS thread → orphan registry ==")

clear_config()
win2 = MW.MainWindow()
fake = _HangingDnsThread("192.0.2.77", parent=win2)
win2._dns_thread = fake   # симуляция запроса, зависшего на недоступном резолвере
fake.start()
wait_until(lambda: fake.isRunning(), timeout_ms=3000)

try:
    _t0 = time.monotonic()
    win2.close()
    _elapsed = time.monotonic() - _t0

    check("окно закрылось в wait-бюджете (~2 c): closeEvent не завис",
          _elapsed < 4.0, f"{_elapsed:.2f}s")
    check("closeEvent реально дождался бюджета (поток всё ещё жив)",
          _elapsed >= 1.8, f"{_elapsed:.2f}s")
    check("переживший поток в orphan-реестре services.diagnostics (не оставлен на GC)",
          fake in diag._orphan_threads and fake.isRunning(),
          f"registry={len(diag._orphan_threads)} running={fake.isRunning()}")

    fake.release()
    wait_until(lambda: fake not in diag._orphan_threads, timeout_ms=8000)
    check("реестр самочищается по finished()",
          fake not in diag._orphan_threads and not fake.isRunning(),
          f"registry={len(diag._orphan_threads)} running={fake.isRunning()}")
finally:
    try:   # release() ВСЕГДА — незакрытый фейк не даёт warning на выходе из процесса
        fake.release()
    except RuntimeError:
        pass


# ════════════════════════════════════════════════════════════
# 3. Шатдаун: «ask»-гейт пропускается (AUDIT ручной #1, реальный баг)
# ════════════════════════════════════════════════════════════
print("== §3 shutdown with terminal_close_behavior='ask': zero dialogs ==")

write_config({"terminal_close_behavior": "ask"})

_orig_term_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _BlockingTermThread   # шов: класс потока — из модуля ssh_terminal
# НОЛЬ диалогов при шатдауне: QMessageBox.question подменяем ОДИН РАЗ (шов
# ST.QMessageBox — тот же класс, что MW.QMessageBox: атрибут ставится на сам класс,
# все вызовы QMessageBox.question в процессе уходят сюда). До фикса здесь были ровно
# 2 вызова — по одному «ask»-диалогу на активную сессию (AUDIT ручной #1).
_asked = []
_orig_q = ST.QMessageBox.question
ST.QMessageBox.question = staticmethod(
    lambda *a, **k: (_asked.append(a), QMessageBox.Close)[1])
th_a = th_b = None
try:
    win3 = MW.MainWindow()
    winA = ST.SSHTerminalWindow(
        ServerData(id="rc1-ta", alias="ta", host="10.99.1.1", user="root"), None, password="pw")
    winB = ST.SSHTerminalWindow(
        ServerData(id="rc1-tb", alias="tb", host="10.99.1.2", user="root"), None, password="pw")
    # compat-свойство window.page — live-ссылка на АКТИВНЫЙ таб: после закрытия
    # последнего таба оно вернёт None — страницы храним явно ДО close().
    page_a, page_b = winA.page, winB.page
    th_a, th_b = page_a.terminal_thread, page_b.terminal_thread
    wait_until(lambda: th_a.isRunning() and th_b.isRunning(), timeout_ms=3000)
    check("fixture: 2 активные терминальные сессии (потоки работают)",
          th_a.isRunning() and th_b.isRunning())
    check("fixture: gate 'ask' читан из конфига",
          page_a._close_behavior == "ask" and page_b._close_behavior == "ask")

    win3._terminal_windows.extend([page_a, page_b])   # реестр сессий MainWindow
    win3.show()
    app.processEvents()

    _t0 = time.monotonic()
    win3.close()
    _elapsed3 = time.monotonic() - _t0

    check("НОЛЬ QMessageBox.question — «ask»-гейт пропущен при шатдауне (до фикса: 2)",
          len(_asked) == 0, f"asked={len(_asked)}")
    check("главное окно закрыто", not win3.isVisible())
    check("обе сессии shut down'ы (page.shutdown)",
          page_a._shut_down is True and page_b._shut_down is True)
    check("stop() вызван на потоках каждой сессии",
          th_a.stop_calls >= 1 and th_b.stop_calls >= 1,
          f"stops={th_a.stop_calls}/{th_b.stop_calls}")
    check("пережившие потоки в ST._orphan_threads (N4-путь page.shutdown)",
          th_a in ST._orphan_threads and th_b in ST._orphan_threads,
          f"registry={len(ST._orphan_threads)}")
    check("шатдаун уложился в разумный бюджет", _elapsed3 < 15.0, f"{_elapsed3:.2f}s")

finally:
    # release() — ВСЕГДА (даже при FAIL): незакрытые фейки не должны давать
    # «QThread: Destroyed while thread is still running» на выходе из процесса.
    for _th in (th_a, th_b):
        if _th is not None:
            try:
                _th.release()
            except RuntimeError:
                pass  # C++-объект уже удалён — поток всё равно живёт до release/таймаута
    if th_a is not None and th_b is not None:
        wait_until(lambda: (not th_a.isRunning()) and (not th_b.isRunning()), timeout_ms=8000)
        check("ST orphan-реестр самочищается по finished()",
              th_a not in ST._orphan_threads and th_b not in ST._orphan_threads,
              f"registry={len(ST._orphan_threads)}")
    ST.QMessageBox.question = _orig_q
    ST.SSHTerminalThread = _orig_term_cls
    clear_config()


# ════════════════════════════════════════════════════════════
# 4. Состояние релиза + i18n-паритет (новых ключей НЕТ — 427)
# ════════════════════════════════════════════════════════════
print("== §4 release state + i18n parity ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
check_release_state(ROOT)

finish()
