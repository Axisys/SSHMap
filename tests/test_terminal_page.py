# -*- coding: utf-8 -*-
"""v1.2 — Рефактор TerminalSessionPage (окно → страница) + трекинг по сессиям.

Тематический тест релиза v1.2 (ROADMAP v1.2, конвенция «новый тематический файл»):

§1 Конструкция страницы: TerminalSessionPage — сессия как переиспользуемый
   виджет (thread + screen + терминальный холст + статус-строка + SFTP-вкладка),
   конфиг terminal_* из config.json, тестовый шов класса потока (ST.SSHTerminalThread).

§2 ВСЕ teardown-пути — через единый метод page.shutdown() (идемпотентен):
   a) штатный путь: таймер PTY остановлен, сигналы потока/worker'а отвязаны
      (поздние emit без приёмников — no-op), поток стопнут, реестр орфано-потоков пуст;
   b) орфано-путь (v1.1.2RC1 N4): поток «подключается» (блокируется до 15 c в
      реальности) — shutdown() ждёт wait(1500), не дождался → реестр _orphan_threads,
      поздний finished() самочищает реестр;
   c) SFTP-worker: ленивый старт на живом transport'е, shutdown() — стоп в бюджете,
      сигналы отвязаны (паттерн test_sftp_tab §6);
   d) error-путь: error_signal → QMessageBox.critical + статус-строка + close_terminal
      (без хоста — teardown напрямую);
   e) close_terminal() с хост-окном — окно закрывается штатным путём.

§3 confirm_close — gate «ask» (terminal_close_behavior): "close" без диалога;
   "ask" + активная сессия → Cancel держит / Close закрывает; _force_close (путь
   лимита v1.1.1) и завершённая сессия — без диалога.

§4 Регрессия жизненного цикла окна (режим `windows` = v1.1.x): тонкая обёртка
   (WA_DeleteOnClose, заголовок, геометрия window_geometry.py), compat-свойства
   live-ссылаются на страницу, ресайз холста → синхронизация сетки через eventFilter
   (раньше resizeEvent окна), мост «статус-бар страницы → статус-бар окна»
   (sticky-текст + SFTP-прогресс), round-trip ui_window_geometry_terminal,
   WA_DeleteOnClose E2E (C++-объект уничтожен после close).

§5 Трекинг по СЕССИЯМ в MainWindow (ROADMAP задача 4): реестр _terminal_windows
   хранит TerminalSessionPage, а не окна; зелёная точка узла гаснет только когда
   закрыты ВСЕ сессии узла; лимит «4 своих терминала» (terminal_max_open) считается
   по сессиям — Close закрывает старейшую (_force_close), Cancel — None.

§6 i18n-паритет (новых ключей в v1.2 нет — 398) + состояние релиза (pin _common.py).

Запуск:  python tests/test_terminal_page.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import threading

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QThread, QSize, Signal as QtSignal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

import modules.ssh_terminal as ST
import modules.terminal_page as TP
import modules.sftp_worker as SWORK
from modules.terminal_page import TerminalSessionPage
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# Обвязка: фейковые потоки (тот же API, что у SSHTerminalThread)
# ════════════════════════════════════════════════════════════

class _FakeChannel:
    closed = False

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)


class _FakeThread(QThread):
    """Idle-поток: run() — pass (реальный SSH не нужен)."""
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
        self.channel = _FakeChannel()
        self.running = True
        self.stop_calls = 0

    def run(self):
        pass

    def stop(self):
        self.stop_calls += 1
        self.running = False

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            self.channel.send(data_bytes)


class _BlockingThread(_FakeThread):
    """Имитация paramiko-подключения: run() блокируется до release() и НЕ реагирует
    на stop() — как реальный connect с timeout 15 c (сценарий N4 v1.1.2RC1)."""

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__(host, user, port, password, key_path)
        self.channel = None
        self._release = threading.Event()

    def run(self):
        self._release.wait(30)   # «подключение» — stop() не прерывает (как paramiko)
        self.running = False
        try:
            self.closed_signal.emit()
        except RuntimeError:
            pass  # страница уже уничтожена — поздний emit без приёмников безопасен

    def release(self):
        self._release.set()


class _FakeSftpAttr:
    def __init__(self, filename, is_dir, size, mtime):
        self.filename = filename
        self.st_mode = 0o40755 if is_dir else 0o100644
        self.st_size = size
        self.st_mtime = mtime


class _FakeSftpFS:
    def __init__(self):
        self.dirs = {"/"}
        self.files = {}

    def add_file(self, path, data, mtime=1700000000):
        self.files[path] = bytes(data)


class _FakeSftpFile:
    def __init__(self, fs, path, mode):
        self._fs, self._path, self._pos = fs, path, 0

    def read(self, n=-1):
        buf = self._fs.files.get(self._path, b"")
        end = len(buf) if n < 0 else min(len(buf), self._pos + n)
        data = bytes(buf[self._pos:end])
        self._pos = end
        return data

    def write(self, data):
        buf = self._fs.files.setdefault(self._path, bytearray())
        buf.extend(data)

    def close(self):
        pass


class _FakeSftpClient:
    """Минимальный фейк paramiko SFTPClient (listdir_attr/open/close/get_channel)."""

    def __init__(self, fs):
        self._fs = fs
        self._closed = False

    def listdir_attr(self, path):
        out = []
        for f in sorted(self._fs.files):
            if os.path.dirname(f) == (path or "/"):
                out.append(_FakeSftpAttr(os.path.basename(f), False, len(self._fs.files[f]), 0))
        return out

    def open(self, path, mode="r"):
        return _FakeSftpFile(self._fs, path, mode)

    def get_channel(self):
        return self

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


class _FakeTransport:
    def is_active(self):
        return True


class _FakeSshClient:
    """Поверхность paramiko SSHClient для _ensure_sftp: get_transport/open_sftp."""

    def __init__(self, sftp_client):
        self._sftp = sftp_client
        self._tr = _FakeTransport()

    def get_transport(self):
        return self._tr

    def open_sftp(self):
        return self._sftp

    def close(self):
        pass


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


def alive(w):
    """Жив ли C++-объект (WA_DeleteOnClose: после accept — уже уничтожен)."""
    try:
        w.windowTitle()
        return True
    except RuntimeError:  # Internal C++ object already deleted
        return False


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # все страницы/окна в этом файле — на фейке

_pages, _windows = [], []


def make_page(alias, password=None, initial_command=""):
    """Страница с фейковым потоком (parent=None — standalone, без хост-окна)."""
    p = TerminalSessionPage(
        ServerData(id=f"tp-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password=password, initial_command=initial_command)
    _pages.append(p)
    app.processEvents()
    return p


# ════════════════════════════════════════════════════════════
# 1. Конструкция страницы: сессия как переиспользуемый виджет
# ════════════════════════════════════════════════════════════
print("== page construction ==")

clear_config()
data_pw = ServerData(id="tp-pw", alias="pw", host="10.99.0.2", user="root", password="nodepw")
p1 = make_page("pw", password="explicit")
check("страница — QWidget со сессией (server_data сохранён)",
      p1.server_data is data_pw or p1.server_data.alias == "pw")
check("тестовый шов: поток создан классом ST.SSHTerminalThread (подменённым)",
      isinstance(p1.terminal_thread, _FakeThread), type(p1.terminal_thread).__name__)
check("параметр password приоритетнее node.data.password (AUDIT v0.7.2 средняя #7)",
      p1.terminal_thread.password == "explicit")
p1b = make_page("pw2", password=None)
data_pw2 = ServerData(id="tp-pw3", alias="pw3", host="10.99.0.3", user="root", password="nodepw3")
p1c = TerminalSessionPage(data_pw2, None)   # password=None → node.data.password
_pages.append(p1c)
check("password=None → пароль из node.data (модель не обязана хранить его)",
      p1c.terminal_thread.password == "nodepw3", p1c.terminal_thread.password)

p1d = make_page("grid")
check("pyte-экран 120×32 (геометрия invoke_shell)",
      p1d.tscreen.columns == 120 and p1d.tscreen.lines == 32,
      f"{p1d.tscreen.columns}x{p1d.tscreen.lines}")
check("терминальный холст — TerminalWidget", isinstance(p1d.widget, TerminalWidget))
check("QTabWidget [Терминал | Файлы] (v1.1.3)", p1d.tabs.count() == 2
      and p1d.tabs.widget(0) is p1d.widget and p1d.tabs.widget(1) is p1d.sftp_tab)
check("статус-строка: terminal.initializing",
      p1d.status_label.text() != "" , p1d.status_label.text())

# Конфиг terminal_* — читается при создании страницы (load_terminal_settings)
write_config({"terminal_wheel": "off", "terminal_palette": "nord",
              "terminal_font": "Consolas", "terminal_font_size": 12,
              "terminal_history_lines": 50})
pcfg = make_page("cfg")
check("конфиг: terminal_wheel='off' → widget._wheel_mode", pcfg.widget._wheel_mode == "off")
check("конфиг: палитра nord применена к холсту", pcfg.widget._palette_name == "nord",
      pcfg.widget._palette_name)
check("конфиг: шрифт Consolas 12 применён",
      pcfg.widget._font.family() == "Consolas" and pcfg.widget._font.pointSize() == 12,
      f"{pcfg.widget._font.family()} pt{pcfg.widget._font.pointSize()}")
for _ in range(200):
    pcfg.tscreen.feed(b"x\r\n")
pos, size = pcfg.tscreen.scroll_info()
check("конфиг: глубина истории 50 (terminal_history_lines)", size == 50 and pos == 50,
      f"pos={pos} size={size}")
clear_config()


# ════════════════════════════════════════════════════════════
# 2. Teardown: все пути — через единый метод shutdown()
# ════════════════════════════════════════════════════════════
print("== teardown paths (single shutdown method) ==")

# ── a) штатный путь: idle-поток ─────────────────────────────────────────────
pa = make_page("td-a")
app.processEvents()
text_before = pa.widget.visible_text()
pa.shutdown()
check("a: _shut_down=True (метод отработал)", pa._shut_down is True)
check("a: PTY-дебаунс-таймер остановлен", not pa._pty_timer.isActive())
check("a: поток стопнут (stop() вызван)", pa.terminal_thread.stop_calls >= 1,
      f"calls={pa.terminal_thread.stop_calls}")
# Сигналы потока отвязаны: поздний emit без приёмников — no-op
pa.terminal_thread.output_signal.emit(b"late output\r\n")
app.processEvents()
check("a: output_signal после shutdown не меняет экран (слоты отвязаны)",
      pa.widget.visible_text() == text_before, repr(pa.widget.visible_text())[:80])
# Идемпотентность: повторный teardown — no-op без исключений
try:
    pa.shutdown()
    check("a: двойной shutdown() — idempotent no-op", True)
except Exception as e:  # noqa: BLE001
    check("a: двойной shutdown() — idempotent no-op", False, repr(e))
check("a: реестр орфано-потоков пуст (idle-поток дожил в бюджете)",
      pa.terminal_thread not in ST._orphan_threads)

# ── b) орфано-путь (N4 v1.1.2RC1): поток «подключается» дольше wait(1500) ────
ST.SSHTerminalThread = _BlockingThread
pb = make_page("td-b")
wait_until(lambda: pb.terminal_thread.isRunning(), timeout_ms=3000)
check("b: поток работает («подключение» в процессе)", pb.terminal_thread.isRunning())
pb.shutdown()   # stop() + wait(1500) — поток блокирован → переживает ожидание
th_b = pb.terminal_thread
check("b: переживший wait(1500) поток в реестре _orphan_threads (N4)",
      th_b in ST._orphan_threads and th_b.isRunning(),
      f"registry={len(ST._orphan_threads)} running={th_b.isRunning()}")
check("b: stop() вызван (running=False, но paramiko-блокировка продолжается)",
      th_b.stop_calls >= 1 and th_b.running is False)
th_b.release()   # «подключение завершилось» — поздний finished() самочищает реестр
wait_until(lambda: th_b not in ST._orphan_threads, timeout_ms=8000)
check("b: finished() → реестр самочищен (поток не уничтожен на GC)",
      th_b not in ST._orphan_threads and th_b.isFinished(),
      f"registry={len(ST._orphan_threads)} finished={th_b.isFinished()}")
ST.SSHTerminalThread = _FakeThread

# ── c) SFTP-worker: ленивый старт + shutdown в бюджете ──────────────────────
fs_c = _FakeSftpFS()
fs_c.add_file("/a.txt", b"hello")
pc = make_page("td-c")
pc.terminal_thread.client = _FakeSshClient(_FakeSftpClient(fs_c))   # «подключено»
check("c: worker ленивый — до open_sftp не создан", pc._sftp_worker is None)
check("c: _ensure_sftp() открыл SFTP на общем transport'е и запустил worker",
      pc._ensure_sftp() is True and pc._sftp_worker is not None
      and pc._sftp_worker.isRunning())
worker_c = pc._sftp_worker
pc.shutdown()
check("c: worker остановлен в бюджете shutdown(wait_ms=2500)",
      not worker_c.isRunning(), f"running={worker_c.isRunning()}")
check("c: idle-worker не ушёл в реестр орфано-worker'ов",
      worker_c not in SWORK._orphan_workers, f"registry={len(SWORK._orphan_workers)}")
# Сигналы worker'а отвязаны: поздний emit — no-op
worker_c.task_started.emit(99, "list", "/late")
app.processEvents()
check("c: task_started после shutdown не меняет состояние страницы (слоты отвязаны)",
      pc._sftp_tasks == {} and pc._sftp_busy == 0,
      f"tasks={pc._sftp_tasks} busy={pc._sftp_busy}")

# ── d) error-путь: error_signal → critical + статус + close_terminal ─────────
crit_calls = []
_orig_critical = ST.QMessageBox.critical
ST.QMessageBox.critical = staticmethod(lambda *a, **k: crit_calls.append(a))
try:
    pd = make_page("td-d")
    pd.terminal_thread.error_signal.emit("boom")
    app.processEvents()
    check("d: error_signal → QMessageBox.critical (parent — хост-окно / None)",
          len(crit_calls) == 1 and crit_calls[0][0] is None, str(crit_calls)[:120])
    check("d: статус-строка получила текст ошибки", "boom" in pd.status_label.text(),
          pd.status_label.text())
    check("d: error → close_terminal (без хоста — teardown напрямую)",
          pd._shut_down is True and pd.terminal_thread.stop_calls >= 1)
finally:
    ST.QMessageBox.critical = _orig_critical

# ── e) close_terminal() с хост-окном: окно закрывается штатным путём ─────────
pe_win = ST.SSHTerminalWindow(
    ServerData(id="tp-td-e", alias="td-e", host="10.99.0.4", user="root"), None, password="pw")
_windows.append(pe_win)
check("e: страница привязана к хост-окну (set_host_window)",
      pe_win.page._host_window is pe_win)
pe_win.show()
app.processEvents()
pe_win.page.close_terminal()   # стоп потока + close() хоста → closeEvent → shutdown
wait_until(lambda: not alive(pe_win), timeout_ms=4000)
check("e: page.close_terminal() закрыло хост-окно (WA_DeleteOnClose)",
      not alive(pe_win))


# ════════════════════════════════════════════════════════════
# 3. confirm_close — gate «ask» (terminal_close_behavior)
# ════════════════════════════════════════════════════════════
print("== confirm_close 'ask' gate ==")

asked = []
_q_result = [QMessageBox.StandardButton.Cancel]
_orig_question = ST.QMessageBox.question


def _fake_question(*a, **k):
    asked.append(a[1] if len(a) > 1 else None)
    return _q_result[0]


ST.QMessageBox.question = staticmethod(_fake_question)
try:
    # "close" (дефолт v1.0/v1.1) — без диалога
    clear_config()
    pg1 = make_page("ask-close")
    check("close_behavior дефолт 'close'", getattr(pg1, "_close_behavior", None) == "close")
    asked.clear()
    check("'close' + активная сессия: без диалога → True",
          pg1.confirm_close() is True and len(asked) == 0, str(asked))

    # "ask" + активная сессия: Cancel → False (окно живёт), Close → True
    write_config({"terminal_close_behavior": "ask"})
    ST.SSHTerminalThread = _BlockingThread
    pg2 = make_page("ask-live")
    wait_until(lambda: pg2.terminal_thread.isRunning(), timeout_ms=3000)
    asked.clear()
    _q_result[0] = QMessageBox.StandardButton.Cancel
    check("'ask' + активная сессия + Cancel → False (теardown не запущен)",
          pg2.confirm_close() is False and len(asked) == 1 and pg2._shut_down is False,
          f"asked={asked}")
    _q_result[0] = QMessageBox.StandardButton.Close
    check("'ask' + активная сессия + Close → True", pg2.confirm_close() is True)

    # _force_close (путь лимита v1.1.1): решение подтверждено — без диалога
    asked.clear()
    pg2._force_close = True
    check("'ask' + _force_close: без диалога → True",
          pg2.confirm_close() is True and len(asked) == 0, str(asked))
    pg2.terminal_thread.release()
    wait_until(lambda: not pg2.terminal_thread.isRunning(), timeout_ms=5000)
    ST.SSHTerminalThread = _FakeThread

    # "ask", но сессия уже завершена → без диалога
    write_config({"terminal_close_behavior": "ask"})
    pg3 = make_page("ask-dead")
    pg3.terminal_thread.wait(2000)   # гарантированно неактивная сессия (без гонки)
    asked.clear()
    check("'ask' + завершённая сессия: без диалога → True",
          pg3.confirm_close() is True and len(asked) == 0, str(asked))
finally:
    ST.QMessageBox.question = _orig_question
    clear_config()


# ════════════════════════════════════════════════════════════
# 4. Регрессия жизненного цикла окна (режим `windows` = v1.1.x)
# ════════════════════════════════════════════════════════════
print("== window lifecycle regression (thin wrapper) ==")

clear_config()
wv = ST.SSHTerminalWindow(
    ServerData(id="tp-win", alias="win", host="10.99.0.5", user="root"), None, password="pw")
_windows.append(wv)
check("окно: WA_DeleteOnClose сохранён",
      bool(wv.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)) is True)
check("окно: заголовок terminal.window_title (alias+host)",
      "win" in wv.windowTitle() and "10.99.0.5" in wv.windowTitle(), wv.windowTitle())
check("окно: центральный виджет — TerminalSessionPage",
      isinstance(wv.centralWidget(), TerminalSessionPage) and wv.centralWidget() is wv.page)
check("окно: compat server_data (BUGFIX v0.9.5.5 сохранён)",
      wv.server_data.alias == "win")

# Compat-свойства — live-ссылки на сессию страницы
check("compat: win.widget/tscreen/terminal_thread — те же объекты, что у страницы",
      wv.widget is wv.page.widget and wv.tscreen is wv.page.tscreen
      and wv.terminal_thread is wv.page.terminal_thread)
check("compat: win.tabs/sftp_tab/status_label/_sftp_worker — live-ссылки",
      wv.tabs is wv.page.tabs and wv.sftp_tab is wv.page.sftp_tab
      and wv.status_label is wv.page.status_label
      and wv._sftp_worker is None)

# Ресайз холста (внутри таба) → синхронизация сетки через eventFilter страницы
# (раньше — resizeEvent окна); guard по смене сетки + дебаунс ~150 мс.
# ВАЖНО: show() ДО resize — offscreen откладывает геометрию скрытого top-level
# до первого show (проверено: скрытое окно НЕ получает resizeEvent ни в v1.1.x,
# ни в v1.2 — синхронизация сетки происходит на show/resize видимого окна;
# продакшен-путь _spawn_terminal_window всегда show() сразу после создания).
wv.show()
app.processEvents()
wv.resize(700, 500)
wait_until(lambda: (wv.page._last_cols, wv.page._last_rows) != (120, 32), timeout_ms=4000)
app.processEvents()
check("ресайз окна → сетка пересчитана (eventFilter страницы)",
      (wv.page._last_cols, wv.page._last_rows) != (120, 32),
      f"grid={wv.page._last_cols}x{wv.page._last_rows}")
check("compat: win._last_cols/_last_rows — live-свойства страницы",
      (wv._last_cols, wv._last_rows) == (wv.page._last_cols, wv.page._last_rows))
wv._pending_pty = (50, 20)   # setter compat-свойства
check("compat: win._pending_pty get/set — live-свойство страницы",
      wv._pending_pty == (50, 20) and wv.page._pending_pty == (50, 20))
wv.page._pending_pty = None
check("close_terminal() сохранён на окне (cleanup-путь MainWindow)",
      callable(getattr(wv, "close_terminal", None)))

# Мост «статус-бар страницы → статус-бар окна» (вид v1.1.x)
wv.page.status_message.emit("bridge message", 0)
app.processEvents()
check("мост: status_message(sticky) → statusBar().currentMessage()",
      wv.statusBar().currentMessage() == "bridge message",
      repr(wv.statusBar().currentMessage()))
wv.page.status_message.emit("timed message", 5000)
app.processEvents()
check("мост: status_message с таймаутом → showMessage(text, ms)",
      wv.statusBar().currentMessage() == "timed message")
check("мост: SFTP-прогресс-бар в статус-баре окна, скрыт",
      wv._sftp_progress.isHidden())
wv.page.progress_busy.emit()
app.processEvents()
check("мост: progress_busy → бар виден (индетерминированный)",
      not wv._sftp_progress.isHidden() and wv._sftp_progress.maximum() == 0)
wv.page.progress_update.emit(5, 10)
app.processEvents()
check("мост: progress_update(5,10) → range/value",
      wv._sftp_progress.maximum() == 10 and wv._sftp_progress.value() == 5,
      f"max={wv._sftp_progress.maximum()} val={wv._sftp_progress.value()}")
wv.page.progress_hidden.emit()
app.processEvents()
check("мост: progress_hidden → бар скрыт", wv._sftp_progress.isHidden())

# ── геометрия: closeEvent сохраняет, новое окно восстанавливает (U2) ─────────
clear_config()
wv.resize(640, 480)   # дефолт окна терминала — 800×600, восстановление видно
app.processEvents()
wv.close()
wait_until(lambda: not alive(wv), timeout_ms=4000)
with open(_cfg_path(), encoding="utf-8") as f:
    _val = json.load(f).get("ui_window_geometry_terminal")
check("геометрия: closeEvent записал ui_window_geometry_terminal {geometry, state}",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}, f"got={_val!r}")
wv2 = ST.SSHTerminalWindow(
    ServerData(id="tp-win2", alias="win2", host="10.99.0.6", user="root"), None, password="pw")
_windows.append(wv2)
app.processEvents()
check("геометрия: новое окно восстановило 640×480 (дефолт 800×600)",
      wv2.size() == QSize(640, 480), f"got={wv2.size()}")

# ── WA_DeleteOnClose E2E: show + close → C++-объект уничтожен ───────────────
wv3 = ST.SSHTerminalWindow(
    ServerData(id="tp-win3", alias="win3", host="10.99.0.7", user="root"), None, password="pw")
_windows.append(wv3)
wv3.show()
app.processEvents()
check("WA_DeleteOnClose: окно живо до close()", alive(wv3))
wv3.close()
wait_until(lambda: not alive(wv3), timeout_ms=4000)
check("WA_DeleteOnClose: после close C++-объект уничтожен", not alive(wv3))
clear_config()


# ════════════════════════════════════════════════════════════
# 5. Трекинг по СЕССИЯМ в MainWindow (ROADMAP задача 4)
# ════════════════════════════════════════════════════════════
print("== session tracking in MainWindow ==")

clear_config()
mw = MW.MainWindow()
mw.show()
app.processEvents()


def dot_color(node):
    return node._ssh_status.brush().color().name()


# ── две сессии одного узла: точка гаснет только когда закрыты ВСЕ ───────────
node1 = mw.scene.add_server(
    ServerData(id="sess-a", alias="sessA", host="10.98.1.1", user="root"))
win_s1 = mw._spawn_terminal_window(node1)
win_s2 = mw._spawn_terminal_window(node1)
app.processEvents()
check("реестр хранит СЕССИИ (TerminalSessionPage), а не окна",
      len(mw._terminal_windows) == 2
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows)
      and all(s is not win_s1 and s is not win_s2 for s in mw._terminal_windows),
      f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
check("зелёная точка узла горит (2 активные сессии)", dot_color(node1) == "#22c55e",
      dot_color(node1))

win_s1.close()   # первая сессия закрыта — вторая жива
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("закрыта одна из двух сессий → реестр 1 (destroyed-сигнал страницы)",
      len(mw._terminal_windows) == 1 and not alive(win_s1))
check("зелёная точка горит, пока жива вторая сессия узла", dot_color(node1) == "#22c55e",
      dot_color(node1))

win_s2.close()   # все сессии узла закрыты
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("закрыты ВСЕ сессии узла → реестр пуст", len(mw._terminal_windows) == 0)
check("зелёная точка погасла (все сессии закрыты)", dot_color(node1) == "#64748b",
      dot_color(node1))
check("_ssh_connected_nodes: id узла сброшен после всех сессий",
      node1.data.id not in mw._ssh_connected_nodes)

# ── лимит «своих терминалов» считается по СЕССИЯМ (terminal_max_open) ────────
write_config({"terminal_max_open": 2})
node2 = mw.scene.add_server(
    ServerData(id="sess-b", alias="sessB", host="10.98.1.2", user="root"))
w_a = mw._spawn_terminal_window(node2)
w_b = mw._spawn_terminal_window(node2)
app.processEvents()
check("лимит: 2 сессии открыты (terminal_max_open=2)", len(mw._terminal_windows) == 2)

_limit_result = [QMessageBox.StandardButton.Cancel]
_orig_mw_question = MW.QMessageBox.question


def _mw_fake_question(*a, **k):
    asked.append(a[1] if len(a) > 1 else None)
    return _limit_result[0]


MW.QMessageBox.question = staticmethod(_mw_fake_question)
try:
    # Cancel → None, реестр не тронут
    node3 = mw.scene.add_server(
        ServerData(id="sess-c", alias="sessC", host="10.98.1.3", user="root"))
    asked.clear()
    w_cancel = mw._spawn_terminal_window(node3)
    check("лимит: Cancel → None, реестр не изменился (2 сессии)",
          w_cancel is None and len(asked) == 1 and len(mw._terminal_windows) == 2,
          f"asked={asked} registry={len(mw._terminal_windows)}")

    # Close → старейшая СЕССИЯ закрыта (_force_close), новая зарегистрирована
    _limit_result[0] = QMessageBox.StandardButton.Close
    asked.clear()
    oldest_sess = mw._terminal_windows[0]
    w_oldest_win = w_a   # окно старейшей сессии (порядок создания)
    node4 = mw.scene.add_server(
        ServerData(id="sess-d", alias="sessD", host="10.98.1.4", user="root"))
    w_new = mw._spawn_terminal_window(node4)
    check("лимит: Close → диалог про старейшую сессию", len(asked) == 1, str(asked))
    check("лимит: _force_close поставлен на старейшую сессию (против повторного 'ask')",
          getattr(oldest_sess, "_force_close", False) is True)
    wait_until(lambda: not alive(w_oldest_win), timeout_ms=4000)
    app.processEvents()
    check("лимит: окно старейшей сессии закрыто (page.close_terminal → closeEvent)",
          not alive(w_oldest_win))
    check("лимит: реестр снова 2 — старейшая убрана, новая сессия зарегистрирована",
          w_new is not None and len(mw._terminal_windows) == 2
          and oldest_sess not in mw._terminal_windows
          and mw._terminal_windows[-1] is w_new.page,
          f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
finally:
    MW.QMessageBox.question = _orig_mw_question
clear_config()


# ════════════════════════════════════════════════════════════
# 6. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════════
print("== i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # в v1.2 новых ключей нет — паритет 398 без изменений
check_release_state(ROOT)

finish()
