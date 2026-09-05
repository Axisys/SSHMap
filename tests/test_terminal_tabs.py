# -*- coding: utf-8 -*-
"""v1.2.1 — Несколько SSH-сессий табами в одном окне терминала (ROADMAP v1.2.1).

Тематический тест релиза v1.2.1 (конвенция «новый тематический файл»): offscreen,
ВСЕ без сети — фейковые потоки с тем же API, что у SSHTerminalThread (тестовый шов
ST.SSHTerminalThread).

§1 Структура окна: SSHTerminalWindow получает QTabWidget из страниц (центральный
   виджет session_tabs), табы закрываемые; заголовок таба — alias узла, tooltip —
   terminal.tab_close_tooltip; WA_DeleteOnClose/заголовок сохранены; compat-атрибуты —
   live-ссылки на АКТИВНЫЙ таб (win.page = текущий таб).

§2 Новая сессия = новый таб (существующий путь «подключиться к узлу»):
   MainWindow._spawn_terminal_window для уже открытого узла → то же окно + второй таб
   (статус-сообщение terminal.session_new_tab); другой узел — новое окно.

§3 Закрытие таба = существующая cleanup-логика на странице: gate «ask» confirm_close
   → единый teardown shutdown (поток стопнут, _shut_down); закрытие одного таба НЕ
   затрагивает соседний (сессия жива и печатает); закрытие ПОСЛЕДНЕГО таба закрывает
   окно (WA_DeleteOnClose E2E); крестик на табе (tabCloseRequested) — тот же путь.

§4 Error-путь в табовом окне: error_signal на одном табе → QMessageBox.critical +
   закрывается ТОЛЬКО этот таб; соседняя сессия жива и печатает.

§5 Лимит «4 своих терминала» (terminal_max_open) считается по СЕССИЯМ во всех окнах:
   2 таба (одно окно) + 1 сессия (другое окно) = лимит; Cancel → None, Close →
   старейшая сессия (_force_close) — закрывается ЕЁ таб, а окно с соседней сессией живёт.

§6 Мост «статус-бар» — только активный таб: сообщения неактивных табов в статус-бар
   не доходят; при переключении табов мост переподключается; SFTP-прогресс-бар следует
   за состоянием активного таба.

§7 i18n-паритет (400 = 398 + 2 terminal.*) + состояние релиза (пин _common.py).

Запуск:  python tests/test_terminal_tabs.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import threading

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QThread, Signal as QtSignal
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
from modules.terminal_page import TerminalSessionPage
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
    """Имитация paramiko-подключения: run() блокируется до release() — «живая» сессия
    для gate «ask» (stop() не прерывает, как реальный connect)."""

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

_windows = []


def make_window(alias, host="10.98.2.1", password="pw"):
    """Окно терминала с фейковым потоком (один таб)."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"tt-{alias}", alias=alias, host=host, user="root"),
        None, password=password)
    _windows.append(w)
    app.processEvents()
    return w


def dot_color(node):
    return node._ssh_status.brush().color().name()


# ════════════════════════════════════════════════════════════
# 1. Структура окна: QTabWidget из страниц сессий
# ════════════════════════════════════════════════════════════
print("== 1. window structure: QTabWidget of sessions ==")

clear_config()
w1 = make_window("struct")
check("окно: WA_DeleteOnClose сохранён",
      bool(w1.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)) is True)
check("окно: заголовок terminal.window_title (alias+host)",
      "struct" in w1.windowTitle() and "10.98.2.1" in w1.windowTitle(), w1.windowTitle())
check("окно: центральный виджет — QTabWidget из сессий (session_tabs)",
      isinstance(w1.centralWidget(), QTabWidget) and w1.session_tabs is w1.centralWidget())
check("окно: табы закрываемые (крестик на табе)",
      w1.session_tabs.tabsClosable() is True)
check("окно: первый таб — TerminalSessionPage (v1.2 compat: win.page)",
      isinstance(w1.session_tabs.widget(0), TerminalSessionPage)
      and w1.session_tabs.widget(0) is w1.page)
check("заголовок таба — alias узла", w1.session_tabs.tabText(0) == "struct",
      repr(w1.session_tabs.tabText(0)))
check("tooltip таба — terminal.tab_close_tooltip",
      w1.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      repr(w1.session_tabs.tabToolTip(0)))
p1 = w1.page
check("страница привязана к хосту (set_host_window)", p1._host_window is w1)
check("compat: win.widget/tscreen/terminal_thread — live-ссылки на активный таб",
      w1.widget is w1.page.widget and w1.tscreen is w1.page.tscreen
      and w1.terminal_thread is w1.page.terminal_thread)
check("compat: win.tabs/sftp_tab/status_label — live-ссылки (внутренние табы сессии)",
      w1.tabs is w1.page.tabs and w1.sftp_tab is w1.page.sftp_tab
      and w1.status_label is w1.page.status_label)

# add_session: второй таб того же узла — активный, мост переключился
p2 = w1.add_session(
    ServerData(id="tt-struct-b", alias="struct", host="10.98.2.1", user="root"), password="pw")
app.processEvents()
check("add_session: второй таб добавлен и стал активным (Qt: addTab не активирует)",
      w1.session_tabs.count() == 2 and w1.session_tabs.currentWidget() is p2)
check("add_session: заголовок второго таба — alias узла",
      w1.session_tabs.tabText(1) == "struct")
check("compat: win.page — теперь АКТИВНЫЙ таб", w1.page is p2)

# ── закрытие НЕпоследнего таба не закрывает окно; последний таб → WA_DeleteOnClose ──
w1.close_page(w1.session_tabs.widget(0))   # struct (таб 0) — сосед p2 жив
app.processEvents()
check("close_page: закрытие НЕпоследнего таба оставляет окно с соседним табом",
      alive(w1) and w1.session_tabs.count() == 1 and w1.session_tabs.widget(0) is p2,
      f"tabs={w1.session_tabs.count() if alive(w1) else '?'}")
w1.close_page(p2)   # последний таб → окно закрывается целиком
wait_until(lambda: not alive(w1), timeout_ms=4000)
check("close_page: закрытие ПОСЛЕДНЕГО таба уничтожило окно (WA_DeleteOnClose)",
      not alive(w1))


# ════════════════════════════════════════════════════════════
# 2. Новая сессия = новый таб (существующий путь «подключиться к узлу»)
# ════════════════════════════════════════════════════════════
print("== 2. new session = new tab (existing connect path) ==")

mw = MW.MainWindow()
mw.show()
app.processEvents()

node_a = mw.scene.add_server(
    ServerData(id="tt-a", alias="alpha", host="10.98.3.1", user="root"))
win_a1 = mw._spawn_terminal_window(node_a)
check("первое подключение: новое окно с одним табом (поведение v1.2)",
      win_a1 is not None and win_a1.session_tabs.count() == 1
      and len(mw._terminal_windows) == 1,
      f"registry={len(mw._terminal_windows)}")

win_a2 = mw._spawn_terminal_window(node_a)
app.processEvents()
check("второе подключение к тому же узлу — новый таб в ТОМ ЖЕ окне (v1.2.1)",
      win_a2 is win_a1 and win_a1.session_tabs.count() == 2,
      f"tabs={win_a1.session_tabs.count() if alive(win_a1) else '?'}")
check("реестр хранит СЕССИИ (TerminalSessionPage), а не окна",
      len(mw._terminal_windows) == 2
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows)
      and all(s is not win_a1 and s is not win_a2 for s in mw._terminal_windows),
      f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
check("заголовки табов — alias узла (оба таба)",
      win_a1.session_tabs.tabText(0) == "alpha" and win_a1.session_tabs.tabText(1) == "alpha",
      f"{win_a1.session_tabs.tabText(0)!r}/{win_a1.session_tabs.tabText(1)!r}")
check("зелёная точка узла горит (2 активные сессии)", dot_color(node_a) == "#22c55e",
      dot_color(node_a))
check("статус-сообщение: terminal.session_new_tab (alias в тексте)",
      mw.statusBar().currentMessage() == i18n.t("terminal.session_new_tab", alias="alpha"),
      repr(mw.statusBar().currentMessage()))

node_b = mw.scene.add_server(
    ServerData(id="tt-b", alias="beta", host="10.98.3.2", user="root"))
win_b = mw._spawn_terminal_window(node_b)
app.processEvents()
check("другой узел — НОВОЕ окно (не таб в чужом окне)",
      win_b is not None and win_b is not win_a1 and win_b.session_tabs.count() == 1
      and len(mw._terminal_windows) == 3,
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 3. Закрытие таба = существующая cleanup-логика на странице
# ════════════════════════════════════════════════════════════
print("== 3. closing a tab = existing page cleanup ==")

page_a1 = win_a1.session_tabs.widget(0)
page_a2 = win_a1.session_tabs.widget(1)

# ── закрытие одного таба не затрагивает соседний ─────────────────────────────
win_a1.close_page(page_a1)
wait_until(lambda: len(mw._terminal_windows) == 2, timeout_ms=4000)
app.processEvents()
check("закрыт один таб → реестр 2 (destroyed-сигнал страницы)",
      len(mw._terminal_windows) == 2 and not alive(page_a1),
      f"registry={len(mw._terminal_windows)}")
check("окно живо с соседним табом (не уничтожено)",
      alive(win_a1) and win_a1.session_tabs.count() == 1
      and win_a1.session_tabs.widget(0) is page_a2)
check("закрытая сессия: поток стопнут + единый shutdown",
      page_a1.terminal_thread.stop_calls >= 1 and page_a1._shut_down is True,
      f"stop={page_a1.terminal_thread.stop_calls} shut_down={page_a1._shut_down}")
check("зелёная точка горит, пока жива вторая сессия узла", dot_color(node_a) == "#22c55e",
      dot_color(node_a))
check("соседний таб не затронут: сессия не shut down", page_a2._shut_down is False)
page_a2.terminal_thread.output_signal.emit(b"still alive\r\n")
app.processEvents()
check("соседний таб не затронут: вывод всё ещё рендерится на холсте",
      "still alive" in page_a2.widget.visible_text(),
      repr(page_a2.widget.visible_text())[:80])

# ── последний таб закрывает окно (WA_DeleteOnClose E2E) ──────────────────────
win_a1.close_page(win_a1.session_tabs.widget(0))
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("последний таб → окно уничтожено (WA_DeleteOnClose)", not alive(win_a1))
check("зелёная точка погасла (все сессии узла закрыты)", dot_color(node_a) == "#64748b",
      dot_color(node_a))
check("_ssh_connected_nodes: id узла сброшен после всех сессий",
      node_a.data.id not in mw._ssh_connected_nodes)

# ── крестик на табе: tabCloseRequested → тот же путь ─────────────────────────
win_b.session_tabs.tabCloseRequested.emit(0)
wait_until(lambda: not alive(win_b), timeout_ms=4000)
app.processEvents()
check("крестик на табе (tabCloseRequested): последний таб закрыт → окно уничтожено",
      not alive(win_b) and len(mw._terminal_windows) == 0,
      f"registry={len(mw._terminal_windows)}")

# ── gate «ask» при закрытии таба: Cancel держит / Close закрывает ────────────
write_config({"terminal_close_behavior": "ask"})
ST.SSHTerminalThread = _BlockingThread
node_c = mw.scene.add_server(
    ServerData(id="tt-c", alias="gamma", host="10.98.3.3", user="root"))
win_c1 = mw._spawn_terminal_window(node_c)
mw._spawn_terminal_window(node_c)   # два таба в одном окне (v1.2.1)
app.processEvents()
page_c1 = win_c1.session_tabs.widget(0)
page_c2 = win_c1.session_tabs.widget(1)
wait_until(lambda: page_c1.terminal_thread.isRunning(), timeout_ms=3000)

asked = []
_q_result = [QMessageBox.StandardButton.Cancel]
_orig_question = ST.QMessageBox.question


def _fake_question(*a, **k):
    asked.append(a[1] if len(a) > 1 else None)
    return _q_result[0]


ST.QMessageBox.question = staticmethod(_fake_question)
try:
    asked.clear()
    win_c1.close_page(page_c1)   # «ask» + активная сессия → подтверждение
    app.processEvents()
    check("«ask» + Cancel при закрытии таба: таб остаётся открытым",
          len(asked) == 1 and alive(win_c1) and win_c1.session_tabs.count() == 2
          and page_c1._shut_down is False, f"asked={asked}")

    _q_result[0] = QMessageBox.StandardButton.Close
    asked.clear()
    win_c1.close_page(page_c1)   # «ask» + Close → teardown ТОЛЬКО этого таба
    wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
    app.processEvents()
    check("«ask» + Close при закрытии таба: закрыт только этот таб (сосед жив)",
          len(asked) == 1 and alive(win_c1) and win_c1.session_tabs.count() == 1
          and not alive(page_c1), f"asked={asked}")
finally:
    ST.QMessageBox.question = _orig_question

# cleanup «ask»-секции: отпустить блокирующиеся потоки, закрыть остаток
page_c1.terminal_thread.release()
page_c2.terminal_thread.release()
wait_until(lambda: (not page_c1.terminal_thread.isRunning()
                    and not page_c2.terminal_thread.isRunning()), timeout_ms=8000)
ST.SSHTerminalThread = _FakeThread
clear_config()
if alive(win_c1):
    win_c1.close()   # сессии завершены — без диалога; последний таб → окно
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("cleanup ask-секции: все сессии закрыты, реестр пуст",
      len(mw._terminal_windows) == 0, f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 4. Error-путь в табовом окне: закрывается только таб с ошибкой
# ════════════════════════════════════════════════════════════
print("== 4. error path in a tabbed window ==")

clear_config()
node_d = mw.scene.add_server(
    ServerData(id="tt-d", alias="delta", host="10.98.3.4", user="root"))
win_d1 = mw._spawn_terminal_window(node_d)
mw._spawn_terminal_window(node_d)   # два таба в одном окне
app.processEvents()
page_d1 = win_d1.session_tabs.widget(0)
page_d2 = win_d1.session_tabs.widget(1)

crit_calls = []
_orig_critical = ST.QMessageBox.critical
ST.QMessageBox.critical = staticmethod(lambda *a, **k: crit_calls.append(a))
try:
    page_d1.terminal_thread.error_signal.emit("boom-d")
    app.processEvents()
    check("error → QMessageBox.critical (parent — хост-окно)",
          len(crit_calls) == 1 and crit_calls[0][0] is win_d1, str(crit_calls)[:120])
finally:
    ST.QMessageBox.critical = _orig_critical

wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("error: закрыт ТОЛЬКО таб с ошибкой (реестр 1)",
      len(mw._terminal_windows) == 1 and not alive(page_d1),
      f"registry={len(mw._terminal_windows)}")
check("error: окно живо с соседней сессией",
      alive(win_d1) and win_d1.session_tabs.count() == 1
      and win_d1.session_tabs.widget(0) is page_d2)
check("error: соседняя сессия не shut down", page_d2._shut_down is False)
page_d2.terminal_thread.output_signal.emit(b"delta alive\r\n")
app.processEvents()
check("error: соседний таб всё ещё печатает",
      "delta alive" in page_d2.widget.visible_text(),
      repr(page_d2.widget.visible_text())[:80])

win_d1.close_page(page_d2)   # последний таб → окно
wait_until(lambda: not alive(win_d1), timeout_ms=4000)
app.processEvents()
check("error-путь: закрытие последнего таба → окно уничтожено", not alive(win_d1))


# ════════════════════════════════════════════════════════════
# 5. Лимит «своих терминалов» — по СЕССИЯМ во всех окнах
# ════════════════════════════════════════════════════════════
print("== 5. limit counts sessions across all windows ==")

write_config({"terminal_max_open": 3})
node_e = mw.scene.add_server(
    ServerData(id="tt-e", alias="eps", host="10.98.3.5", user="root"))
win_e1 = mw._spawn_terminal_window(node_e)   # таб 1
mw._spawn_terminal_window(node_e)            # таб 2 (то же окно)
node_f = mw.scene.add_server(
    ServerData(id="tt-f", alias="fio", host="10.98.3.6", user="root"))
win_f = mw._spawn_terminal_window(node_f)    # новое окно, сессия 3
app.processEvents()
check("лимит: 3 сессии (2 таба в одном окне + 1 в другом)",
      len(mw._terminal_windows) == 3 and win_e1 is not None
      and win_e1.session_tabs.count() == 2 and win_f is not win_e1,
      f"registry={len(mw._terminal_windows)}")

_limit_result = [QMessageBox.StandardButton.Cancel]
_orig_mw_question = MW.QMessageBox.question
asked5 = []


def _mw_fake_question(*a, **k):
    asked5.append(a[1] if len(a) > 1 else None)
    return _limit_result[0]


MW.QMessageBox.question = staticmethod(_mw_fake_question)
try:
    node_g = mw.scene.add_server(
        ServerData(id="tt-g", alias="gma", host="10.98.3.7", user="root"))
    asked5.clear()
    w_cancel = mw._spawn_terminal_window(node_g)
    check("лимит (сессии во всех окнах): Cancel → None, реестр не изменился (3)",
          w_cancel is None and len(asked5) == 1 and len(mw._terminal_windows) == 3,
          f"asked={asked5} registry={len(mw._terminal_windows)}")

    _limit_result[0] = QMessageBox.StandardButton.Close
    asked5.clear()
    oldest_sess = mw._terminal_windows[0]   # первый таб окна eps
    node_h = mw.scene.add_server(
        ServerData(id="tt-h", alias="eta", host="10.98.3.8", user="root"))
    w_new = mw._spawn_terminal_window(node_h)
    check("лимит: Close → диалог про старейшую сессию", len(asked5) == 1, str(asked5))
    check("лимит: _force_close поставлен на старейшую сессию (против повторного 'ask')",
          getattr(oldest_sess, "_force_close", False) is True)
    wait_until(lambda: oldest_sess not in mw._terminal_windows, timeout_ms=4000)
    app.processEvents()
    check("лимит: закрыт таб старейшей сессии — её окно живо с соседней (v1.2.1)",
          alive(win_e1) and win_e1.session_tabs.count() == 1
          and oldest_sess not in mw._terminal_windows,
          f"tabs={win_e1.session_tabs.count() if alive(win_e1) else '?'}")
    check("лимит: реестр снова 3 — старейшая убрана, новая сессия в новом окне",
          w_new is not None and len(mw._terminal_windows) == 3
          and mw._terminal_windows[-1] is w_new.page and w_new is not win_e1,
          f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
finally:
    MW.QMessageBox.question = _orig_mw_question
clear_config()

# cleanup: закрыть все оставшиеся окна (сессии)
for ww in (win_e1, win_f, w_new):
    if alive(ww):
        ww.close()
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("cleanup лимит-секции: все сессии закрыты, реестр пуст",
      len(mw._terminal_windows) == 0, f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 6. Мост «статус-бар» — только активный таб
# ════════════════════════════════════════════════════════════
print("== 6. status bridge: active tab only ==")

clear_config()
node_i = mw.scene.add_server(
    ServerData(id="tt-i", alias="iota", host="10.98.3.9", user="root"))
win_i1 = mw._spawn_terminal_window(node_i)
mw._spawn_terminal_window(node_i)   # два таба; активный — второй (add_session)
app.processEvents()
page_i1 = win_i1.session_tabs.widget(0)
page_i2 = win_i1.session_tabs.widget(1)
check("мост: после add_session активен НОВЫЙ таб",
      win_i1.session_tabs.currentWidget() is page_i2)

page_i2.status_message.emit("iota-2", 0)
app.processEvents()
check("мост: сообщение АКТИВНОГО таба → статус-бар окна",
      win_i1.statusBar().currentMessage() == "iota-2",
      repr(win_i1.statusBar().currentMessage()))

win_i1.session_tabs.setCurrentIndex(0)   # переключение на первый таб
app.processEvents()
page_i2.status_message.emit("iota-2-late", 0)   # неактивный таб — не мостится
app.processEvents()
check("мост: сообщение НЕАКТИВНОГО таба в статус-бар не доходит",
      win_i1.statusBar().currentMessage() == "iota-2",
      repr(win_i1.statusBar().currentMessage()))
page_i1.status_message.emit("iota-1", 0)
app.processEvents()
check("мост: после переключения — сообщение активного таба в статус-баре",
      win_i1.statusBar().currentMessage() == "iota-1",
      repr(win_i1.statusBar().currentMessage()))

# SFTP-прогресс-бар следует за состоянием активного таба
page_i1.progress_busy.emit()
app.processEvents()
check("мост: progress_busy на активном табе → бар виден (индетерминированный)",
      not win_i1._sftp_progress.isHidden() and win_i1._sftp_progress.maximum() == 0)
win_i1.session_tabs.setCurrentIndex(1)   # таб без передач
app.processEvents()
check("мост: переключение на таб без передач → бар скрыт",
      win_i1._sftp_progress.isHidden())

win_i1.close()   # оба таба (дефолт 'close' — без диалога)
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("окно с двумя табами закрылось целиком, реестр пуст",
      len(mw._terminal_windows) == 0 and not alive(win_i1),
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 7. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════════
print("== 7. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # v1.2.1: +2 terminal.* ключа (398 → 400)
for code in ("en", "ru", "zh"):
    check(f"i18n {code}: новые ключи tab_close_tooltip/session_new_tab не пусты",
          bool(langs[code].get("terminal.tab_close_tooltip"))
          and bool(langs[code].get("terminal.session_new_tab")))
check_release_state(ROOT)

finish()
