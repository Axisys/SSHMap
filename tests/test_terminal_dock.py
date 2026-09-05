# -*- coding: utf-8 -*-
"""v1.2.2 — Терминалы как док окна карты (terminal.mode: windows/tabs, ROADMAP v1.2.2).

Тематический тест релиза v1.2.2 (конвенция «новый тематический файл»): offscreen,
ВСЕ без сети — фейковые потоки с тем же API, что у SSHTerminalThread (тестовый шов
ST.SSHTerminalThread).

§1 Ключ конфига terminal_mode: нет ключа → "windows" (дефолт, текущее поведение);
   "tabs" / " TABS " (strip+lower) → "tabs"; битое значение/чужой тип (int) → дефолт
   (валидация load_terminal_settings() по паттерну других ключей).

§2 Структура дока + spawn в режиме "tabs": MainWindow._spawn_terminal_window создаёт
   QDockWidget «Терминалы» (objectName terminals_dock, заголовок terminal.dock_title)
   с QTabWidget из TerminalSessionPage; карта остаётся центральным виджетом
   (self.view не трогается); второй узел — второй таб в ТОМ ЖЕ доке (+ статус
   terminal.session_new_tab); реестр хранит СЕССИИ.

§3 Применение без перезапуска: смена режима конфиг-ключом — новые сессии уходят в
   выбранный режим, открытые окна/док живут как есть до закрытия (tabs→windows:
   отдельное окно; windows→tabs: сессия в доке, старое окно живо).

§4 Cleanup в доке — постранично (v1.2): закрытие таба = cleanup ЛОКАЛЬНОЙ страницы
   (gate «ask» Cancel держит / Close закрывает только этот таб; сосед жив и печатает);
   закрытие ПОСЛЕДНЕГО таба → док прячется (не уничтожается); зелёная точка гаснет,
   когда закрыты ВСЕ сессии узла; крестик на табе — тот же путь.

§5 Статус-строка дока — только активный таб + авто-очистка по таймауту (token-guard):
   сообщения неактивных табов не доходят, переключение переподключает мост;
   SFTP-прогресс следует за активным табом; timeout_ms>0 → label очищается, более
   новое сообщение старым таймаутом не затирается; статус-бар КАРТЫ доковыми
   сессиями не трогается.

§6 Отрыв дока в окно и обратно: setFloating(True) — отдельное окно (isWindow),
   сессии печатают; setFloating(False) — обратно на карту, состояние не меняется.

§7 Шатдаун MainWindow: closeEvent закрывает ВСЕ сессии реестра (док + окна) —
   потоки стопнуты, реестр пуст, док скрыт, окно терминала уничтожено.

§8 Лимит terminal_max_open по СЕССИЯМ во всех контейнерах: 1 окно + 1 таб дока =
   лимит; Cancel → None; Close → старейшая (_force_close) закрывается в своём
   контейнере, новая сессия уходит в выбранный режим.

§9 i18n-паритет (404 = 400 + 4: terminal.dock_title + settings.terminal.mode.*)
   + состояние релиза (пин _common.py).

Запуск:  python tests/test_terminal_dock.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import threading
import time

from _common import (bootstrap, check, finish, wait_until,
                     load_i18n_langs, check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import QThread, Signal as QtSignal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QDockWidget, QTabWidget

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
    """Merge-запись в config.json (семантика i18n.save_config: существующие ключи
    сохраняются — смена одного режима не сбрасывает остальные)."""
    p = _cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cur = {}
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cur = data
        except (json.JSONDecodeError, OSError):
            pass
    cur.update(d)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cur, f)


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


def dot_color(node):
    return node._ssh_status.brush().color().name()


def spin(ms):
    """Обработать события ms (для таймерных проверок статус-строки)."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.005)


def _inside(w, root):
    """Живёт ли w в дереве под root (parentWidget-цепочка)."""
    p = w.parentWidget()
    while p is not None:
        if p is root:
            return True
        p = p.parentWidget()
    return False


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # все страницы/окна в этом файле — на фейке


def make_main():
    """Offscreen-MainWindow с остановленным autosave-таймером (детерминизм)."""
    w = MW.MainWindow()
    w._autosave_timer.stop()
    w.show()
    app.processEvents()
    return w


# ════════════════════════════════════════════════════════════
# 1. Ключ конфига terminal_mode — валидация по паттерну других ключей
# ════════════════════════════════════════════════════════════
print("== 1. terminal_mode config validation ==")

clear_config()
check("нет ключа → дефолт 'windows' (текущее поведение)",
      ST.load_terminal_settings()["mode"] == "windows")
write_config({"terminal_mode": "tabs"})
check("'tabs' → 'tabs'", ST.load_terminal_settings()["mode"] == "tabs")
write_config({"terminal_mode": " TABS "})
check("' TABS ' (strip+lower) → 'tabs'", ST.load_terminal_settings()["mode"] == "tabs")
write_config({"terminal_mode": "garbage"})
check("битое значение → дефолт 'windows'", ST.load_terminal_settings()["mode"] == "windows")
write_config({"terminal_mode": 123})
check("чужой тип (int) → дефолт 'windows'", ST.load_terminal_settings()["mode"] == "windows")
write_config({"terminal_mode": "tabs", "terminal_max_open": 7})
_ts = ST.load_terminal_settings()
check("прочие ключи читаются параллельно (max_open=7, mode=tabs)",
      _ts["max_open"] == 7 and _ts["mode"] == "tabs")
clear_config()


# ════════════════════════════════════════════════════════════
# 2. Структура дока + spawn в режиме "tabs"
# ════════════════════════════════════════════════════════════
print("== 2. dock structure + spawn in tabs mode ==")

write_config({"terminal_mode": "tabs"})
mw = make_main()
check("до первой сессии дока нет (ленивое создание)",
      getattr(mw, "_terminals_dock", None) is None)

node_a = mw.scene.add_server(
    ServerData(id="td-a", alias="alpha", host="10.97.3.1", user="root"))
dock = mw._spawn_terminal_window(node_a)
app.processEvents()
check("первая сессия в режиме 'tabs' → док создан (QDockWidget)", isinstance(dock, QDockWidget))
check("док: objectName terminals_dock", dock.objectName() == "terminals_dock")
check("док: заголовок terminal.dock_title",
      dock.windowTitle() == i18n.t("terminal.dock_title"), repr(dock.windowTitle()))
content = dock.content
check("контент дока: QTabWidget из сессий (session_tabs, 1 таб)",
      isinstance(content.session_tabs, QTabWidget) and content.session_tabs.count() == 1)
check("контент дока: табы закрываемые (крестик на табе)",
      content.session_tabs.tabsClosable() is True)
page_a = content.session_tabs.widget(0)
check("таб — TerminalSessionPage; заголовок = alias узла; tooltip terminal.tab_close_tooltip",
      isinstance(page_a, TerminalSessionPage) and content.session_tabs.tabText(0) == "alpha"
      and content.session_tabs.tabToolTip(0) == i18n.t("terminal.tab_close_tooltip"),
      repr(content.session_tabs.tabText(0)))
check("страница привязана к хосту (контент дока): close_terminal → close_page",
      page_a._host_window is content)
check("карта остаётся центральным виджетом: self.view не тронут, док — рядом",
      _inside(mw.view, mw.centralWidget()) and len(mw.findChildren(QDockWidget)) == 1)

node_b = mw.scene.add_server(
    ServerData(id="td-b", alias="beta", host="10.97.3.2", user="root"))
dock2 = mw._spawn_terminal_window(node_b)
app.processEvents()
check("второй узел — второй таб в ТОМ ЖЕ доке (не новое окно)",
      dock2 is dock and content.session_tabs.count() == 2,
      f"tabs={content.session_tabs.count()}")
check("реестр хранит СЕССИИ (TerminalSessionPage), а не контейнеры",
      len(mw._terminal_windows) == 2
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows),
      f"registry={[type(s).__name__ for s in mw._terminal_windows]}")
check("зелёная точка горит на обоих узлах",
      dot_color(node_a) == "#22c55e" and dot_color(node_b) == "#22c55e",
      f"{dot_color(node_a)}/{dot_color(node_b)}")
check("статус-сообщение: terminal.session_new_tab (присоединение к открытому контейнеру)",
      mw.statusBar().currentMessage() == i18n.t("terminal.session_new_tab", alias="beta"),
      repr(mw.statusBar().currentMessage()))


# ════════════════════════════════════════════════════════════
# 3. Применение без перезапуска: новые сессии — в выбранный режим
# ════════════════════════════════════════════════════════════
print("== 3. apply without restart ==")

page_b = content.session_tabs.widget(1)

# tabs → windows: новая сессия — отдельное окно; доковые сессии живут как есть
write_config({"terminal_mode": "windows"})
node_c = mw.scene.add_server(
    ServerData(id="td-c", alias="gamma", host="10.97.3.3", user="root"))
win_c = mw._spawn_terminal_window(node_c)
app.processEvents()
check("tabs→windows: новая сессия — отдельное окно (поведение v1.2.1)",
      win_c is not None and win_c is not dock and win_c.session_tabs.count() == 1,
      f"win={type(win_c).__name__ if win_c else None}")
check("tabs→windows: доковые сессии живут как есть (не shut down)",
      page_a._shut_down is False and page_b._shut_down is False
      and content.session_tabs.count() == 2)
check("реестр: 3 сессии (2 в доке + 1 в окне)", len(mw._terminal_windows) == 3,
      f"registry={len(mw._terminal_windows)}")

# windows → tabs: сессия уходит в док; старое окно узла НЕ переиспользуется — живо
write_config({"terminal_mode": "tabs"})
win_c2 = mw._spawn_terminal_window(node_c)   # тот же узел, но режим уже "tabs"
app.processEvents()
check("windows→tabs: новая сессия — таб в доке (старое окно не переиспользуется)",
      win_c2 is dock and content.session_tabs.count() == 3,
      f"tabs={content.session_tabs.count()}")
check("windows→tabs: старое окно узла живо как есть со своим табом",
      alive(win_c) and win_c.session_tabs.count() == 1)
check("реестр: 4 сессии (3 в доке + 1 в окне)", len(mw._terminal_windows) == 4,
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 4. Cleanup в доке — постранично (v1.2)
# ════════════════════════════════════════════════════════════
print("== 4. cleanup in the dock — per page ==")

# ── закрытие НЕпоследнего таба не затрагивает соседний ───────────────────────
content.close_page(content.session_tabs.widget(0))   # alpha (таб 0)
wait_until(lambda: len(mw._terminal_windows) == 3, timeout_ms=4000)
app.processEvents()
check("закрыт таб в доке → реестр 3 (destroyed-сигнал страницы)",
      len(mw._terminal_windows) == 3 and not alive(page_a),
      f"registry={len(mw._terminal_windows)}")
page_b2 = content.session_tabs.widget(0)   # теперь beta первым
check("соседний таб не затронут: сессия не shut down", page_b2._shut_down is False)
page_b2.terminal_thread.output_signal.emit(b"beta alive\r\n")
app.processEvents()
check("соседний таб не затронут: вывод всё ещё рендерится на холсте",
      "beta alive" in page_b2.widget.visible_text(),
      repr(page_b2.widget.visible_text())[:80])
check("зелёная точка закрытого узла погасла (все его сессии закрыты)",
      dot_color(node_a) == "#64748b", dot_color(node_a))
check("зелёная точка узла с живой сессией горит", dot_color(node_b) == "#22c55e",
      dot_color(node_b))

# ── закрытие ПОСЛЕДНЕГО таба прячет док (не уничтожает) ──────────────────────
content.close_page(content.session_tabs.widget(0))   # beta
content.close_page(content.session_tabs.widget(0))   # gamma' (второй таб узла c)
wait_until(lambda: content.session_tabs.count() == 0, timeout_ms=4000)
app.processEvents()
check("последний таб → док ПРЯЧЕТСЯ (isHidden)", dock.isHidden())
check("док не уничтожен (контейнер переживает свои сессии — нет WA_DeleteOnClose)",
      alive(dock))
check("реестр после закрытия всех доковых табов: осталось окно-сессия",
      len(mw._terminal_windows) == 1, f"registry={len(mw._terminal_windows)}")

# ── новая сессия в режиме "tabs": скрытый док показывается снова ─────────────
mw._spawn_terminal_window(node_b)   # beta → док (скрыт после последнего таба)
app.processEvents()
check("новая сессия: скрытый док показан снова, 1 таб",
      not dock.isHidden() and content.session_tabs.count() == 1)

# ── крестик на табе: tabCloseRequested → тот же путь ─────────────────────────
content.session_tabs.tabCloseRequested.emit(0)
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("крестик на табе (tabCloseRequested): последний таб закрыт → док скрыт",
      dock.isHidden() and content.session_tabs.count() == 0,
      f"tabs={content.session_tabs.count()}")

# ── gate «ask» в доке: Cancel держит / Close закрывает только этот таб ───────
write_config({"terminal_close_behavior": "ask"})
ST.SSHTerminalThread = _BlockingThread
node_d = mw.scene.add_server(
    ServerData(id="td-d", alias="delta", host="10.97.3.4", user="root"))
node_e = mw.scene.add_server(
    ServerData(id="td-e", alias="eps", host="10.97.3.5", user="root"))
mw._spawn_terminal_window(node_d)
mw._spawn_terminal_window(node_e)
app.processEvents()
page_d = content.session_tabs.widget(0)
page_e = content.session_tabs.widget(1)
wait_until(lambda: page_d.terminal_thread.isRunning(), timeout_ms=3000)

asked = []
_q_result = [QMessageBox.StandardButton.Cancel]
_orig_question = ST.QMessageBox.question


def _fake_question(*a, **k):
    asked.append(a[1] if len(a) > 1 else None)
    return _q_result[0]


ST.QMessageBox.question = staticmethod(_fake_question)
try:
    asked.clear()
    content.close_page(page_d)   # «ask» + активная сессия → подтверждение
    app.processEvents()
    check("«ask» + Cancel при закрытии таба в доке: таб остаётся открытым",
          len(asked) == 1 and content.session_tabs.count() == 2
          and page_d._shut_down is False, f"asked={asked}")

    _q_result[0] = QMessageBox.StandardButton.Close
    asked.clear()
    content.close_page(page_d)   # «ask» + Close → teardown ТОЛЬКО этого таба
    wait_until(lambda: content.session_tabs.count() == 1, timeout_ms=4000)
    app.processEvents()
    check("«ask» + Close при закрытии таба в доке: закрыт только этот таб (сосед жив)",
          len(asked) == 1 and content.session_tabs.count() == 1
          and not alive(page_d) and page_e._shut_down is False, f"asked={asked}")
finally:
    ST.QMessageBox.question = _orig_question

# cleanup ask-секции: отпустить блокирующиеся потоки, закрыть остаток табов
page_d.terminal_thread.release()
page_e.terminal_thread.release()
wait_until(lambda: (not page_d.terminal_thread.isRunning()
                    and not page_e.terminal_thread.isRunning()), timeout_ms=8000)
ST.SSHTerminalThread = _FakeThread
clear_config()
content.close_page(content.session_tabs.widget(0))   # beta
content.close_page(content.session_tabs.widget(0))   # eps
wait_until(lambda: len(mw._terminal_windows) == 1, timeout_ms=4000)
app.processEvents()
check("cleanup ask-секции: доковые сессии закрыты (осталось окно gamma)",
      len(mw._terminal_windows) == 1 and dock.isHidden(),
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 5. Статус-строка дока — только активный таб + таймауты
# ════════════════════════════════════════════════════════════
print("== 5. dock status strip: active tab only ==")

write_config({"terminal_mode": "tabs"})   # режим "tabs" (ask-секция закончилась на clean-конфиге)
node_f = mw.scene.add_server(
    ServerData(id="td-f", alias="fio", host="10.97.3.6", user="root"))
node_g = mw.scene.add_server(
    ServerData(id="td-g", alias="gma", host="10.97.3.7", user="root"))
mw._spawn_terminal_window(node_f)
mw._spawn_terminal_window(node_g)
app.processEvents()
page_f = content.session_tabs.widget(0)
page_g = content.session_tabs.widget(1)
check("мост: после add_session активен НОВЫЙ таб",
      content.session_tabs.currentWidget() is page_g)

mw.statusBar().showMessage("map-marker", 60000)   # известный маркер статус-бара карты
page_g.status_message.emit("dock-g", 0)
app.processEvents()
check("сообщение АКТИВНОГО таба → статус-строка дока",
      content.status_label.text() == "dock-g", repr(content.status_label.text()))
check("статус-бар КАРТЫ доковыми сессиями не трогается (изоляция)",
      mw.statusBar().currentMessage() == "map-marker",
      repr(mw.statusBar().currentMessage()))

content.session_tabs.setCurrentIndex(0)   # переключение на первый таб
app.processEvents()
page_g.status_message.emit("late-g", 0)   # неактивный таб — не мостится
app.processEvents()
check("сообщение НЕАКТИВНОГО таба в статус-строку не доходит",
      content.status_label.text() == "dock-g", repr(content.status_label.text()))
page_f.status_message.emit("dock-f", 0)
app.processEvents()
check("после переключения — сообщение активного таба в строке",
      content.status_label.text() == "dock-f", repr(content.status_label.text()))

# timeout_ms>0 → авто-очистка; token-guard: более новое сообщение не затирается
page_f.status_message.emit("short", 250)
wait_until(lambda: content.status_label.text() == "", timeout_ms=2000)
check("timeout_ms>0: label авто-очищается", content.status_label.text() == "")
page_f.status_message.emit("a", 400)
app.processEvents()
page_f.status_message.emit("b", 0)   # более новое sticky-сообщение
spin(600)                            # таймаут "a" истёк — но label должен держать "b"
check("token-guard: старый таймаут не затирает более новое сообщение",
      content.status_label.text() == "b", repr(content.status_label.text()))

# SFTP-прогресс-бар следует за состоянием активного таба
page_f.progress_busy.emit()
app.processEvents()
check("progress_busy на активном табе → бар виден (индетерминированный)",
      not content.sftp_progress.isHidden() and content.sftp_progress.maximum() == 0)
content.session_tabs.setCurrentIndex(1)   # таб без передач
app.processEvents()
check("переключение на таб без передач → бар скрыт", content.sftp_progress.isHidden())

# cleanup: закрыть оба таба + окно gamma (реестр пуст, док скрыт)
win_c.close()
content.close_page(page_f)
content.close_page(page_g)
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("cleanup секции: все сессии закрыты, реестр пуст, док скрыт",
      len(mw._terminal_windows) == 0 and dock.isHidden() and not alive(win_c),
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 6. Отрыв дока в окно и обратно
# ════════════════════════════════════════════════════════════
print("== 6. detach dock to a window and back ==")

write_config({"terminal_mode": "tabs"})
node_h = mw.scene.add_server(
    ServerData(id="td-h", alias="eta", host="10.97.3.8", user="root"))
node_i = mw.scene.add_server(
    ServerData(id="td-i", alias="theta", host="10.97.3.9", user="root"))
mw._spawn_terminal_window(node_h)
mw._spawn_terminal_window(node_i)
app.processEvents()
check("док до отрыва: не плавающий (встроен в карту)", not dock.isFloating())

dock.setFloating(True)
app.processEvents()
check("setFloating(True): док — отдельное окно (isWindow)",
      dock.isFloating() and dock.isWindow())
page_h = content.session_tabs.widget(0)
page_h.terminal_thread.output_signal.emit(b"floating line\r\n")
app.processEvents()
check("сессия в оторванном доке печатает (холст рендерит)",
      "floating line" in page_h.widget.visible_text(),
      repr(page_h.widget.visible_text())[:80])

dock.setFloating(False)
app.processEvents()
check("setFloating(False): обратно на карту (не плавающий, док в окне карты)",
      not dock.isFloating() and len(mw.findChildren(QDockWidget)) == 1)
check("отрыв/возврат: состояние не меняется — реестр 2, сессии живы",
      len(mw._terminal_windows) == 2 and page_h._shut_down is False
      and content.session_tabs.count() == 2,
      f"registry={len(mw._terminal_windows)}")

# cleanup: закрыть оба таба
content.close_page(content.session_tabs.widget(0))
content.close_page(content.session_tabs.widget(0))
wait_until(lambda: len(mw._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("cleanup секции: реестр пуст", len(mw._terminal_windows) == 0,
      f"registry={len(mw._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 7. Шатдаун MainWindow: ВСЕ сессии реестра (док + окна)
# ════════════════════════════════════════════════════════════
print("== 7. MainWindow shutdown: all sessions (dock + windows) ==")

clear_config()
mw2 = make_main()
write_config({"terminal_mode": "tabs"})
n1 = mw2.scene.add_server(
    ServerData(id="td-s1", alias="sig-1", host="10.97.4.1", user="root"))
d2 = mw2._spawn_terminal_window(n1)      # доковый таб
write_config({"terminal_mode": "windows"})
n2 = mw2.scene.add_server(
    ServerData(id="td-s2", alias="sig-2", host="10.97.4.2", user="root"))
w2 = mw2._spawn_terminal_window(n2)      # отдельное окно
app.processEvents()
page_s1 = d2.content.session_tabs.widget(0)
page_s2 = w2.page
check("до шатдауна: 2 сессии в разных контейнерах (док + окно)",
      len(mw2._terminal_windows) == 2 and page_s1 is not None and page_s2 is not None,
      f"registry={len(mw2._terminal_windows)}")

_ev = QCloseEvent()
mw2.closeEvent(_ev)
wait_until(lambda: len(mw2._terminal_windows) == 0, timeout_ms=8000)
app.processEvents()
check("closeEvent: событие принято (нет несохранённых изменений)", _ev.isAccepted())
check("шатдаун: реестр пуст — закрыты ВСЕ сессии (док + окно)",
      len(mw2._terminal_windows) == 0, f"registry={len(mw2._terminal_windows)}")
check("шатдаун: потоки стопнуты (page.shutdown в обоих контейнерах)",
      page_s1.terminal_thread.stop_calls >= 1 and page_s2.terminal_thread.stop_calls >= 1
      and page_s1._shut_down is True and page_s2._shut_down is True)
check("шатдаун: док скрыт (все табы закрыты постранично)", d2.isHidden())
check("шатдаун: окно терминала уничтожено (WA_DeleteOnClose)", not alive(w2))
check("шатдаун: зелёные точки узлов погасли",
      dot_color(n1) == "#64748b" and dot_color(n2) == "#64748b")


# ════════════════════════════════════════════════════════════
# 8. Лимит terminal_max_open — по СЕССИЯМ во всех контейнерах
# ════════════════════════════════════════════════════════════
print("== 8. limit counts sessions across containers ==")

clear_config()
mw3 = make_main()
write_config({"terminal_max_open": 2, "terminal_mode": "windows"})
n1 = mw3.scene.add_server(
    ServerData(id="td-l1", alias="lim-1", host="10.97.5.1", user="root"))
w1 = mw3._spawn_terminal_window(n1)      # окно, сессия 1
write_config({"terminal_mode": "tabs"})
n2 = mw3.scene.add_server(
    ServerData(id="td-l2", alias="lim-2", host="10.97.5.2", user="root"))
d3 = mw3._spawn_terminal_window(n2)      # таб дока, сессия 2 → лимит (2)
app.processEvents()
check("лимит: 2 сессии в разных контейнерах (1 окно + 1 таб дока)",
      len(mw3._terminal_windows) == 2 and d3 is not None
      and d3.content.session_tabs.count() == 1,
      f"registry={len(mw3._terminal_windows)}")

_limit_result = [QMessageBox.StandardButton.Cancel]
_orig_mw_question = MW.QMessageBox.question
asked8 = []


def _mw_fake_question(*a, **k):
    asked8.append(a[1] if len(a) > 1 else None)
    return _limit_result[0]


MW.QMessageBox.question = staticmethod(_mw_fake_question)
try:
    n3 = mw3.scene.add_server(
        ServerData(id="td-l3", alias="lim-3", host="10.97.5.3", user="root"))
    asked8.clear()
    w_cancel = mw3._spawn_terminal_window(n3)
    check("лимит (сессии во всех контейнерах): Cancel → None, реестр не изменился (2)",
          w_cancel is None and len(asked8) == 1 and len(mw3._terminal_windows) == 2,
          f"asked={asked8} registry={len(mw3._terminal_windows)}")

    _limit_result[0] = QMessageBox.StandardButton.Close
    asked8.clear()
    oldest_sess = mw3._terminal_windows[0]   # окно-сессия (создана первой)
    n4 = mw3.scene.add_server(
        ServerData(id="td-l4", alias="lim-4", host="10.97.5.4", user="root"))
    w_new = mw3._spawn_terminal_window(n4)
    check("лимит: Close → диалог про старейшую сессию", len(asked8) == 1, str(asked8))
    check("лимит: _force_close поставлен на старейшую (против повторного 'ask')",
          getattr(oldest_sess, "_force_close", False) is True)
    wait_until(lambda: oldest_sess not in mw3._terminal_windows, timeout_ms=4000)
    app.processEvents()
    check("лимит: старейшая закрыта в СВОЁМ контейнере — окно уничтожено (последний таб)",
          not alive(w1) and oldest_sess not in mw3._terminal_windows)
    check("лимит: новая сессия ушла в выбранный режим (док), реестр снова 2",
          w_new is d3 and len(mw3._terminal_windows) == 2
          and d3.content.session_tabs.count() == 2,
          f"tabs={d3.content.session_tabs.count() if alive(d3) else '?'}")
finally:
    MW.QMessageBox.question = _orig_mw_question
clear_config()

# cleanup: закрыть все сессии mw3 (табы дока; окно уже уничтожено)
while d3.content.session_tabs.count() > 0:
    d3.content.close_page(d3.content.session_tabs.widget(0))
wait_until(lambda: len(mw3._terminal_windows) == 0, timeout_ms=4000)
app.processEvents()
check("cleanup лимит-секции: все сессии закрыты, реестр пуст",
      len(mw3._terminal_windows) == 0, f"registry={len(mw3._terminal_windows)}")


# ════════════════════════════════════════════════════════════
# 9. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════════
print("== 9. i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)   # v1.2.2: +4 ключа (400 → 404)
for code in ("en", "ru", "zh"):
    check(f"i18n {code}: новые ключи не пусты (dock_title/mode/*.windows/*.tabs)",
          all(langs[code].get(k, "").strip() for k in
              ("terminal.dock_title", "settings.terminal.mode",
               "settings.terminal.mode.windows", "settings.terminal.mode.tabs")))
check_release_state(ROOT)

finish()
