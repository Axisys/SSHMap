# -*- coding: utf-8 -*-
"""v1.2.4 — Мультинабор: E2E на РЕАЛЬНЫХ SSH-каналах (paramiko), без фейковых потоков.

Почему отдельный файл: тематический test_multi_input.py доказывает цепочку
TerminalWidget.keyPressEvent → _send → hub.broadcast → page.terminal_thread.send_data()
на фейках (тот же API, что у SSHTerminalThread). Этот файл закрывает последний
непокрытый отрезок — НАСТОЯЩИЙ paramiko: реальный Transport/Channel на стороне
сервера (in-process echo-shell), реальный SSHTerminalThread клиента, реальная
аутентификация и known_hosts-пиннинг. Инцидент v1.2.4: ручное тестирование не
подтвердило broadcast при живых сессиях — E2E фиксирует поведение на реальных
каналах и ловит регрессии в send_data/живости потоков, которые фейки не видят.

§1 Window-режим (как у пользователя: terminal_mode=windows), 3 терминала:
   включение через путь меню (_toggle_multi_input(True)) → клавиша в активном
   виджете → те же байты во ВСЕХ остальных реальных каналах; источник получает
   ровно один раз (нет эха). Режим выключен → дублей нет (поведение v1.2.2).
   Плюс «реальный путь событий» (v1.2.4-fix): клавиши postEvent'ом через Qt
   event loop (focus + QWidget::event) — не только прямые keyPressEvent-вызовы.

§2 Док-режим (terminal_mode=tabs, TerminalDockContent): 2 сессии в доке —
   broadcast во все остальные табы дока.

§3 Диагностика (v1.2.4-fix): смена состояния режима пишется в лог приложения
   (INFO «Multi-input mode enabled/disabled»), broadcast — DEBUG-строка на каждый
   ввод; файл лога под изолированным HOME проверяется по содержимому.

Запуск:  python tests/test_multi_input_e2e.py   (из корня проекта) или python tests/run_all.py
Сеть не нужна: SSH-сервер живёт в процессе (paramiko ServerInterface, echo-shell).
"""
import os
import socket
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import paramiko  # noqa: E402
import i18n  # noqa: E402
import modules.ssh_terminal as ST  # noqa: E402
from models.server import ServerData  # noqa: E402
import ui.main_window as MW  # noqa: E402
from modules.multi_input import get_hub  # noqa: E402
from modules.logger import setup_logging, get_log_file_path  # noqa: E402

setup_logging()   # лог в изолированный HOME (~/.sshmap/logs/sshmap.log) — нужен для §3


# ════════════════════════════════════════════════════════
# Обвязка: in-process SSH echo-сервер (реальные paramiko transport/channel)
# ════════════════════════════════════════════════════════

HOST_KEY = paramiko.RSAKey.generate(2048)


class EchoServer(paramiko.ServerInterface):
    """Echo-shell: весь ввод клиента возвращается обратно (как bash-эхо).

    ВАЖНО (проверено прогоном, paramiko 5.0): для channel REQUEST'ов (pty/shell)
    результат должен быть TRUTHY — OPEN_SUCCEEDED == 0 (falsy!) дал бы
    CHANNEL_FAILURE, и клиент сам закрывал канал («Channel closed.»)."""

    def __init__(self):
        self.shell_channel = None
        self.data_log = []   # весь ввод клиента (для assert'ов broadcast'а)

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pw, ph, modes):
        return True

    def check_channel_shell_request(self, channel):
        self.shell_channel = channel
        try:
            channel.send(b"\r\nECHO-SHELL READY\r\n")
        except Exception:
            pass
        return True


SERVERS = []       # EchoServer на соединение (порядок accept'ов)
TRANSPORTS = []    # живые ссылки: без них GC убьёт Transport вместе с каналом


def _handle(conn):
    """Одно соединение — свой поток (accept-цикл не блокируется)."""
    try:
        transport = paramiko.Transport(conn)
        transport.add_server_key(HOST_KEY)
        srv = EchoServer()
        SERVERS.append(srv)
        TRANSPORTS.append(transport)
        transport.start_server(server=srv)
        # auth + open channel + shell request приходят ПОСЛЕ start_server — ждём
        deadline = time.time() + 20
        while srv.shell_channel is None and time.time() < deadline:
            if not transport.is_active():
                break
            time.sleep(0.05)
        chan = srv.shell_channel
        if chan is None:
            return
        while not chan.closed:
            if chan.recv_ready():
                data = chan.recv(4096)
                if data:
                    srv.data_log.append(data)
                    chan.sendall(data)   # echo обратно в терминал клиента
            else:
                time.sleep(0.02)
    except Exception:
        pass  # сервер-обвязка: сбой соединения не должен ронять тест


_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_listener.bind(("127.0.0.1", 0))
PORT = _listener.getsockname()[1]
_listener.listen(8)


def _serve():
    # ВАЖНО (v1.2.4-fix): ПОТОК НА СОЕДИНЕНИЕ — _handle блокируется в recv-цикле
    # до закрытия канала; однопоточный accept-цикл обслужил бы только ПЕРВОГО
    # клиента, остальные ждали бы баннер («Error reading SSH protocol banner»).
    while True:
        try:
            conn, _addr = _listener.accept()
        except OSError:
            return  # сокет закрыт (выход) — accept-цикл завершён
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


threading.Thread(target=_serve, daemon=True).start()


# Тестовый шов (паттерн v1.1.x): QMessageBox из ssh_terminal берётся в момент
# вызова — подменяем на НЕМОДАЛЬНЫЙ фейк, чтобы ошибка сессии не блокировала
# offscreen-прогон; все вызовы фиксируем (check: диалогов быть не должно).
DIALOGS = []


class _FakeBox:
    Close = 1
    Cancel = 0

    @staticmethod
    def question(*args, **kwargs):
        DIALOGS.append(("question", args))
        return _FakeBox.Close

    @staticmethod
    def critical(*args, **kwargs):
        DIALOGS.append(("critical", args))
        return _FakeBox.Close

    @staticmethod
    def information(*args, **kwargs):
        DIALOGS.append(("information", args))
        return _FakeBox.Close


ST.QMessageBox = _FakeBox


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


def type_text(widget, text):
    """Клавиши в единственной точке ввода (keyPressEvent → _send).

    Физическая клавиатура идёт тем же путём: шорткаты приложения — только
    F12 (в режиме)/Ctrl+Z/Ctrl+Y/Ctrl+K, ни один не перехватывает печатные
    клавиши/Enter/Backspace (аудит setShortcut/QKeySequence по ui/)."""
    for ch in text:
        widget.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, ord(ch.upper()),
            Qt.KeyboardModifier.NoModifier, ch))
    widget.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, int(Qt.Key.Key_Return),
        Qt.KeyboardModifier.NoModifier, "\r"))


def all_logs():
    return [b"".join(s.data_log) for s in SERVERS]


# ════════════════════════════════════════════════════════
# 1. Window-режим: 3 реальных терминала, broadcast во все остальные
# ════════════════════════════════════════════════════════
print("== 1. windows mode, 3 real SSH terminals ==")

hub_app = get_hub()   # singleton процесса (тот же, что у виджетов и MainWindow)
hub_app.reset()

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("окно держит хаб singleton + provider", mw._multi_hub is hub_app
      and hub_app.session_provider is not None)

nodes, wins = [], {}
for alias in ("e2e-a", "e2e-b", "e2e-c"):
    node = mw.scene.add_server(ServerData(
        id=f"e2e-{alias}", alias=alias, host="127.0.0.1", user="root",
        password="e2e-pass", ssh_port=PORT))
    wins[alias] = mw._spawn_terminal_window(node)
    nodes.append(node)
    app.processEvents()


def all_connected():
    return len(mw._terminal_windows) == 3 and all(
        getattr(s.terminal_thread, "channel", None) is not None
        and not s.terminal_thread.channel.closed
        for s in mw._terminal_windows)


wait_until(all_connected, timeout_ms=25000)
check("3 сессии в реестре + все РЕАЛЬНЫЕ каналы открыты (paramiko)",
      all_connected() and len(SERVERS) == 3,
      f"registry={len(mw._terminal_windows)} servers={len(SERVERS)}")
check("ошибок сессий нет (диалогов не было)", DIALOGS == [], repr(DIALOGS))

# включение — путь checkable QAction («Вид» → Multi Input)
mw._toggle_multi_input(True)
app.processEvents()
check("режим включён: хаб активен, плашка «MULTI: 3 sessions»",
      hub_app.active is True and not mw._multi_plaque.isHidden()
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=3),
      repr(mw._multi_label.text()))

pages = {s.server_data.alias: s for s in mw._terminal_windows}
type_text(pages["e2e-a"].widget, "hello-multi")
wait_until(lambda: all(b"hello-multi\r" in log for log in all_logs()),
           timeout_ms=5000)

logs = all_logs()
check("broadcast: те же байты во ВСЕХ реальных каналах (3 сервера)",
      all(b"hello-multi\r" in log for log in logs), repr(logs))
check("каждый канал получил ввод ровно один раз (нет дублей/эха)",
      all(log.count(b"hello-multi\r") == 1 for log in logs), repr(logs))

# режим выключен → поведение v1.2.2: только активная сессия
mw._toggle_multi_input(False)
app.processEvents()
for s in SERVERS:
    s.data_log.clear()
type_text(pages["e2e-a"].widget, "solo-only")
wait_until(lambda: any(b"solo-only\r" in log for log in all_logs()), timeout_ms=5000)
logs = all_logs()
got = [i for i, log in enumerate(logs) if b"solo-only\r" in log]
check("режим выключен: байты получили ровно ОДИН канал (источник), дублей нет",
      len(got) == 1 and all(b"solo-only\r" not in log or i in got
                            for i, log in enumerate(logs)), repr(logs))

# ── Реальный путь событий (v1.2.4-fix): клавиши через Qt event loop ───────────
# Прямые вызовы keyPressEvent() выше обходят фокус и цепочку QWidget::event();
# postEvent + setFocus ближе к физической клавиатуре (событие идёт через
# очередь Qt → QWidget::event() → keyPressEvent). Шорткаты приложения на
# печатные клавиши/Enter не зарегистрированы (аудит QKeySequence по ui/:
# Ctrl+K палитра, F12 — только в режиме и только ВЫХОД) — перехвата нет.
mw._toggle_multi_input(True)
app.processEvents()
for s in SERVERS:
    s.data_log.clear()
src_w = pages["e2e-a"].widget
src_w.activateWindow()
src_w.setFocus()
app.processEvents()
for ch in "realpath":
    QApplication.postEvent(src_w, QKeyEvent(
        QKeyEvent.Type.KeyPress, ord(ch.upper()),
        Qt.KeyboardModifier.NoModifier, ch))
QApplication.postEvent(src_w, QKeyEvent(QKeyEvent.Type.KeyPress,
                                       int(Qt.Key.Key_Return),
                                       Qt.KeyboardModifier.NoModifier, "\r"))
wait_until(lambda: all(b"realpath\r" in b"".join(s.data_log) for s in SERVERS),
           timeout_ms=5000)
logs = all_logs()
check("реальный путь событий (postEvent+focus через Qt loop): broadcast во все каналы",
      all(b"realpath\r" in log for log in logs), repr(logs))
mw._toggle_multi_input(False)
app.processEvents()

try:
    mw.close()
except Exception:
    pass
app.processEvents()


# ════════════════════════════════════════════════════════
# 2. Док-режим (terminal_mode=tabs): broadcast во все табы дока
# ════════════════════════════════════════════════════════
print("== 2. tabs (dock) mode, 2 real sessions ==")

_orig_load_ts = ST.load_terminal_settings


def _tabs_mode(*_a, **_kw):
    d = _orig_load_ts()
    d["mode"] = "tabs"
    return d


ST.load_terminal_settings = _tabs_mode
n_before = len(SERVERS)

mw2 = MW.MainWindow()
mw2._autosave_timer.stop()
mw2.show()
app.processEvents()
check("хаб общий для всех окон (singleton процесса)", get_hub() is mw2._multi_hub)

for alias in ("dock-a", "dock-b"):
    node = mw2.scene.add_server(ServerData(
        id=f"dock-{alias}", alias=alias, host="127.0.0.1", user="root",
        password="e2e-pass", ssh_port=PORT))
    mw2._spawn_terminal_window(node)
    app.processEvents()

wait_until(lambda: len(mw2._terminal_windows) == 2 and all(
    getattr(s.terminal_thread, "channel", None) is not None
    and not s.terminal_thread.channel.closed
    for s in mw2._terminal_windows), timeout_ms=25000)
check("док-режим: 2 сессии в реестре + каналы открыты",
      len(mw2._terminal_windows) == 2 and len(SERVERS) == n_before + 2,
      f"registry={len(mw2._terminal_windows)} servers={len(SERVERS)}")

dock_pages = {s.server_data.alias: s for s in mw2._terminal_windows}
mw2._toggle_multi_input(True)
app.processEvents()
src_alias = sorted(dock_pages)[0]
type_text(dock_pages[src_alias].widget, "dock-broadcast")
wait_until(lambda: all(b"dock-broadcast\r" in log for log in
                       (b"".join(s.data_log) for s in SERVERS[n_before:])),
           timeout_ms=5000)
check("док-режим: broadcast во ВСЕ остальные табы дока",
      all(b"dock-broadcast\r" in b"".join(s.data_log) for s in SERVERS[n_before:]),
      repr([b"".join(s.data_log) for s in SERVERS[n_before:]]))

mw2._toggle_multi_input(False)
try:
    mw2.close()
except Exception:
    pass
app.processEvents()
ST.load_terminal_settings = _orig_load_ts


# ════════════════════════════════════════════════════════
# 3. Диагностика (v1.2.4-fix): смена режима и broadcast — в файле лога
# ════════════════════════════════════════════════════════
print("== 3. diagnostics in app log ==")

try:
    with open(get_log_file_path(), encoding="utf-8") as f:
        log_text = f.read()
except OSError as e:
    log_text = ""
    check("файл лога читается", False, repr(e))

check("лог: смена состояния режима записана (enabled + disabled)",
      "Multi-input mode enabled" in log_text
      and "Multi-input mode disabled" in log_text)
check("лог: broadcast-строки на каждый ввод в режиме (DEBUG)",
      "multi-input broadcast:" in log_text
      and "-> 2 session(s)" in log_text,   # 3 сессии − источник = 2 получателя
      f"log tail: {log_text[-400:]!r}" if log_text else "(empty)")

finish()
