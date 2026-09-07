# -*- coding: utf-8 -*-
"""v1.2.3 — Мультинабор (broadcast ввода активной сессии во все остальные открытые, ROADMAP v1.2.3).

Тематический тест релиза v1.2.3 (конвенция «новый тематический файл»): offscreen,
ВСЕ без сети — фейковые потоки с тем же API, что у SSHTerminalThread (тестовый шов
ST.SSHTerminalThread). Архитектура: весь пользовательский ввод проходит через одну
точку — TerminalWidget.keyPressEvent() → _send(bytes) → terminal_thread.send_data();
хаб (modules/multi_input.py, singleton процесса) вешается ровно на эту точку.

§1 Хаб юнит (MultiInputHub/_thread_alive): слушатели уведомляются ТОЛЬКО при реальной
   смене состояния; toggle; broadcast — источник пропускается (нет эха), мёртвые
   потоки фильтруются, мёртвый C++-объект в реестре не роняет broadcast; reset.

§2 Включение режима через MainWindow: 3 сессии (window-режим); checkable QAction
   «Вид» (_toggle_multi_input(True)) → отметка + F12-шорткат (ApplicationShortcut,
   живёт только в режиме), плашка статус-бара «MULTI: N сессий» со счётчиком и
   кнопкой выхода, бейджи вкладок «MULTI · <alias>», рамка QTabWidget (objectName),
   префикс заголовка окна terminal.multi_title_prefix, статус-сообщение.

§3 Broadcast в единственной точке ввода (задача 1): клавиша в активном виджете →
   те же байты в send_data() ВСЕХ остальных потоков; источник получает ровно один
   раз (байты от клавиатуры, а не из вывода — эха по определению нет); режим выключен
   → дублей нет (поведение v1.2.2).

§4 F12-выход (задача 3): в режиме — F12 НЕ доходит до shell (RC2-маппинг \\x1b[24~
   приостанавливается), режим выключается, шорткат снимается с QAction; вне режима —
   F12 уходит в shell как \\x1b[24~ (маппинг восстановлен). Esc выходом НЕ является:
   в режиме он дублируется в shell как \\x1b (как любой ввод).

§5 Ctrl+V (bracketed paste) в мультирежиме тоже дублируется (задача 4): единый блок
   \\x1b[200~…\\x1b[201~ во все потоки (иначе «набралось» не везде).

§6 Мёртвая сессия (задача 4): закрытое окно убрано из реестра штатным путём
   (destroyed → _forget_terminal_window), счётчик плашки обновлён, broadcast
   продолжается в оставшиеся; мёртвый поток (channel closed) байты не получает.

§7 Тестовый шов: явный multi_hub в конструкторе TerminalWidget — изоляция от
   singleton'а приложения (broadcast идёт через свой хаб, приложение не трогается).

§8 i18n-паритет en/ru/zh (411 = 404 + 7: terminal.multi_* ×4, view.multi_input,
   status.multi_enabled/disabled) + состояние релиза (пин _common.py).

Запуск:  python tests/test_multi_input.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import (bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QThread, Signal as QtSignal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import i18n
import modules.ssh_terminal as ST
from modules.multi_input import (MultiInputHub, _thread_alive, MULTI_FRAME_OBJECT_NAME)
from modules.terminal_page import TerminalSessionPage
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════
# Обвязка: фейковые потоки (тот же API, что у SSHTerminalThread)
# ════════════════════════════════════════════════════════

class _FakeChannel:
    """Канал-заглушка: send() копит байты; closed — имитация error → close."""

    def __init__(self):
        self.closed = False
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


def key_event(key, text="", mod=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text)


class _Page:
    """Дак-тип записи реестра (как TerminalSessionPage: .widget + .terminal_thread)."""

    def __init__(self, thread, widget=None):
        self.terminal_thread = thread
        self.widget = widget


def dot_color(node):
    return node._ssh_status.brush().color().name()


# ════════════════════════════════════════════════════════
# 1. Хаб юнит: состояние, слушатели, broadcast, живость потоков
# ════════════════════════════════════════════════════════
print("== 1. MultiInputHub unit ==")

hub = MultiInputHub()   # изолированный экземпляр (singleton приложения не трогаем)

check("старт: режим выключен, реестра нет",
      hub.active is False and hub.session_provider is None)

seen = []
hub.add_listener(seen.append)
hub.set_active(True)
hub.set_active(True)   # повтор без смены — уведомления не дублируются
check("слушатель уведомлён ТОЛЬКО при реальной смене состояния", seen == [True], repr(seen))
check("toggle: True → False + уведомление", hub.toggle() is False and seen == [True, False])

t_a = _FakeThread("h1", "u", 22)
t_b = _FakeThread("h2", "u", 22)
t_c = _FakeThread("h3", "u", 22)
w_a, w_b, w_c = object(), object(), object()
pages = [_Page(t_a, w_a), _Page(t_b, w_b), _Page(t_c, w_c)]
hub.set_session_provider(lambda: list(pages))
hub.set_active(True)

n = hub.broadcast(b"hello", source_widget=w_a)
check("broadcast: получателей 2 (источник пропущен)", n == 2, f"n={n}")
check("те же байты во ВСЕХ остальных потоках",
      t_b.channel.sent == [b"hello"] and t_c.channel.sent == [b"hello"],
      f"b={t_b.channel.sent!r} c={t_c.channel.sent!r}")
check("источник broadcast'ом не получает (его байты идут через собственный send_data)",
      t_a.channel.sent == [])

# мёртвая сессия: channel closed (error → close) — фильтруется по живости
t_c.channel.closed = True
n = hub.broadcast(b"x", source_widget=w_a)
check("мёртвый поток (channel closed) отфильтрован: получатель 1, мёртвому не шлём",
      n == 1 and t_b.channel.sent[-1] == b"x" and t_c.channel.sent == [b"hello"],
      f"n={n} c={t_c.channel.sent!r}")

# broadcast никогда не бросает: мёртвый C++-объект в реестре молча пропускается
class _BrokenPage:
    @property
    def widget(self):
        raise RuntimeError("Internal C++ object already deleted")

pages.append(_BrokenPage())
try:
    n = hub.broadcast(b"z", source_widget=w_a)
    check("мёртвый C++-объект в реестре: broadcast не бросает, остальные получают",
          n == 1 and t_b.channel.sent[-1] == b"z")
except Exception as e:  # noqa: BLE001
    check("мёртвый C++-объект в реестре: broadcast не бросает, остальные получают", False, repr(e))

# _thread_alive — живость для broadcast (задача 4)
check("_thread_alive: открытый канал → True", _thread_alive(t_a) is True)
t_dead = _FakeThread("h9", "u", 22)
t_dead.channel.closed = True
check("_thread_alive: закрытый канал → False", _thread_alive(t_dead) is False)


class _StoppedThread:
    def isRunning(self):
        return False

    def send_data(self, d):
        pass


check("_thread_alive: нет канала + поток остановлен → False", _thread_alive(_StoppedThread()) is False)


class _TestDouble:
    """Тест-дубль без channel/isRunning — считается живым (его send_data безопасен)."""

    def __init__(self):
        self.sent = []

    def send_data(self, d):
        self.sent.append(d)


check("_thread_alive: тест-дубль (без channel/isRunning) → True", _thread_alive(_TestDouble()) is True)

n_seen = len(seen)   # [True, False, True] — смена на True перед broadcast'ом тоже уведомляла
hub.reset()
check("reset: режим выключен, реестра нет",
      hub.active is False and hub.session_provider is None)
hub.set_active(True)
check("после reset: слушатели очищены (смена состояния без уведомлений)",
      len(seen) == n_seen and hub.active is True)


# ════════════════════════════════════════════════════════
# 2. Включение режима через MainWindow (QAction «Вид» + UI)
# ════════════════════════════════════════════════════════
print("== 2. MainWindow: enable mode + UI ==")

_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeThread   # все сессии в этом файле — на фейке

hub_app = MW._multi_input_mod.get_hub()   # singleton процесса (тот же, что у виджетов)
hub_app.reset()   # свежее состояние; окно ниже заново зарегистрирует provider+слушатель

mw = MW.MainWindow()
mw._autosave_timer.stop()
mw.show()
app.processEvents()

check("окно держит хаб singleton + provider — реестр сессий",
      mw._multi_hub is hub_app and mw._multi_hub.session_provider is not None)
check("режим до включения выключен: плашка скрыта, шортката F12 нет",
      hub_app.active is False and mw._multi_plaque.isHidden()
      and mw.act_multi_input.shortcut() == QKeySequence())

nodes = []
wins = {}
for i, alias in enumerate(("alpha", "beta", "gamma")):
    node = mw.scene.add_server(
        ServerData(id=f"mi-{alias}", alias=alias, host=f"10.98.{i}.1", user="root"))
    wins[alias] = mw._spawn_terminal_window(node)
    nodes.append(node)
    app.processEvents()

check("3 сессии в реестре (window-режим: по окну на узел)",
      len(mw._terminal_windows) == 3
      and all(isinstance(s, TerminalSessionPage) for s in mw._terminal_windows),
      f"registry={len(mw._terminal_windows)}")

mw._toggle_multi_input(True)   # путь checkable QAction (triggered передаёт состояние)

check("режим включён (состояние хаба)", hub_app.active is True)
check("QAction: отметка + F12-шорткат (ApplicationShortcut — ловит клавишу где бы фокус ни был)",
      mw.act_multi_input.isChecked() is True
      and mw.act_multi_input.shortcut() == QKeySequence("F12")
      and mw.act_multi_input.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut)
check("плашка статус-бара видна + счётчик «MULTI: 3 сессий»",
      mw._multi_plaque.isHidden() is False
      and mw._multi_label.text() == i18n.t("terminal.multi_status", count=3),
      repr(mw._multi_label.text()))
check("кнопка выхода на плашке подключена и переведена (tooltip)",
      mw._multi_exit_btn.toolTip() == i18n.t("terminal.multi_exit_button"))
win_a = wins["alpha"]
check("бейдж таба «MULTI · <alias>»",
      win_a.session_tabs.tabText(0) == i18n.t("terminal.multi_tab_badge", alias="alpha"),
      repr(win_a.session_tabs.tabText(0)))
check("рамка QTabWidget: objectName-селектор + QSS (amber)",
      win_a.session_tabs.objectName() == MULTI_FRAME_OBJECT_NAME
      and "border" in win_a.session_tabs.styleSheet())
check("префикс заголовка окна terminal.multi_title_prefix",
      win_a.windowTitle().startswith(i18n.t("terminal.multi_title_prefix")),
      repr(win_a.windowTitle()))
check("статус-сообщение status.multi_enabled",
      mw.statusBar().currentMessage() == i18n.t("status.multi_enabled"),
      repr(mw.statusBar().currentMessage()))


# ════════════════════════════════════════════════════════
# 3. Broadcast в единственной точке ввода (задача 1)
# ════════════════════════════════════════════════════════
print("== 3. broadcast at the single input point ==")

page_a = wins["alpha"].page
w_a = page_a.widget
threads = {alias: wins[alias].page.terminal_thread for alias in wins}


def clear_sent():
    for t in threads.values():
        t.channel.sent.clear()


clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_A, "a"))
check("клавиша в активной сессии → те же байты во ВСЕХ остальных потоках",
      threads["beta"].channel.sent == [b"a"] and threads["gamma"].channel.sent == [b"a"],
      f"beta={threads['beta'].channel.sent!r} gamma={threads['gamma'].channel.sent!r}")
check("источник получает ровно ОДИН раз (нет эха: байты от клавиатуры, не из вывода)",
      threads["alpha"].channel.sent == [b"a"], repr(threads["alpha"].channel.sent))

# служебные клавиши проходят той же точкой — Return исполняется везде
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_Return, "\r"))
check("Return дублируется (Enter исполняется везде)",
      threads["alpha"].channel.sent == [b"\r"] and threads["beta"].channel.sent == [b"\r"]
      and threads["gamma"].channel.sent == [b"\r"])

# режим выключен → поведение v1.2.2: ввод только в активную сессию
hub_app.set_active(False)
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_B, "b"))
check("режим выключен: дублей нет (ввод только в активную сессию)",
      threads["alpha"].channel.sent == [b"b"]
      and threads["beta"].channel.sent == [] and threads["gamma"].channel.sent == [])
check("выход из режима сбросил UI: плашка скрыта, бейдж/рамка/заголовок к исходным",
      mw._multi_plaque.isHidden() is True
      and win_a.session_tabs.tabText(0) == "alpha"
      and win_a.session_tabs.styleSheet() == ""
      and win_a.session_tabs.objectName() == ""
      and not win_a.windowTitle().startswith(i18n.t("terminal.multi_title_prefix")),
      f"title={win_a.windowTitle()!r} tab={win_a.session_tabs.tabText(0)!r}")


# ════════════════════════════════════════════════════════
# 4. F12-выход (задача 3): не Esc — Esc уходит в shell как \\x1b
# ════════════════════════════════════════════════════════
print("== 4. F12 exit ==")

mw._toggle_multi_input(True)
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12 в режиме: НЕ доходит до shell (RC2-маппинг \\x1b[24~ приостановлен)",
      all(t.channel.sent == [] for t in threads.values()),
      f"sent={[t.channel.sent for t in threads.values()]}")
check("F12 выключает режим", hub_app.active is False)
check("QAction: отметка снята, F12-шорткат снят (клавиша свободна)",
      mw.act_multi_input.isChecked() is False
      and mw.act_multi_input.shortcut() == QKeySequence())

clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12 вне режима: RC2-маппинг восстановлен (\\x1b[24~ в shell)",
      threads["alpha"].channel.sent == [b"\x1b[24~"], repr(threads["alpha"].channel.sent))
check("вне режима дублей нет", threads["beta"].channel.sent == [] and threads["gamma"].channel.sent == [])

# Esc — НЕ выход: в режиме он обычный ввод (\\x1b), дублируется как всё остальное
mw._toggle_multi_input(True)
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_Escape, ""))
check("Esc в режиме: не выход — уходит в shell как \\x1b и дублируется во все сессии",
      hub_app.active is True and threads["alpha"].channel.sent == [b"\x1b"]
      and threads["beta"].channel.sent == [b"\x1b"] and threads["gamma"].channel.sent == [b"\x1b"],
      f"sent={[t.channel.sent for t in threads.values()]}")
mw._toggle_multi_input(False)


# ════════════════════════════════════════════════════════
# 5. Ctrl+V (bracketed paste) в мультирежиме тоже дублируется (задача 4)
# ════════════════════════════════════════════════════════
print("== 5. Ctrl+V bracketed paste broadcast ==")

mw._toggle_multi_input(True)
app.clipboard().setText("line1\nline2")
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_V, "", Qt.KeyboardModifier.ControlModifier))
expected = b"\x1b[200~" + "line1\nline2".encode("utf-8") + b"\x1b[201~"
check("Ctrl+V в мультирежиме: единый bracketed-paste-блок во ВСЕХ потоках",
      threads["alpha"].channel.sent == [expected]
      and threads["beta"].channel.sent == [expected]
      and threads["gamma"].channel.sent == [expected],
      f"alpha={threads['alpha'].channel.sent!r}")
mw._toggle_multi_input(False)


# ════════════════════════════════════════════════════════
# 6. Мёртвая сессия: реестр штатным путём, broadcast без поломки (задача 4)
# ════════════════════════════════════════════════════════
print("== 6. dead session ==")

mw._toggle_multi_input(True)
page_b = wins["beta"].page
win_b = wins["beta"]
win_b.close()   # WA_DeleteOnClose: destroyed → _forget_terminal_window (штатный путь)
app.processEvents()

check("закрытая сессия убрана из реестра штатным путём",
      len(mw._terminal_windows) == 2 and all(s is not page_b for s in mw._terminal_windows),
      f"registry={len(mw._terminal_windows)}")
check("зелёная точка мёртвого узла погасла (все сессии узла закрыты)",
      dot_color(nodes[1]) != "#22c55e", dot_color(nodes[1]))
check("счётчик плашки обновлён: 2 сессии",
      mw._multi_label.text() == i18n.t("terminal.multi_status", count=2),
      repr(mw._multi_label.text()))

clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_C, "c"))
check("broadcast продолжается в оставшиеся (мёртвая сессия не ломает режим)",
      threads["gamma"].channel.sent == [b"c"] and threads["alpha"].channel.sent == [b"c"],
      f"gamma={threads['gamma'].channel.sent!r}")

# мёртвый поток (канал закрыт) в реестре — байты в него не уходят
t_g = threads["gamma"]
t_g.channel.closed = True   # имитация error → close без закрытия окна
clear_sent()
w_a.keyPressEvent(key_event(Qt.Key.Key_D, "d"))
check("мёртвый поток (channel closed) байты не получает",
      t_g.channel.sent == [] and threads["alpha"].channel.sent == [b"d"],
      f"gamma={t_g.channel.sent!r}")
mw._toggle_multi_input(False)


# ════════════════════════════════════════════════════════
# 7. Тестовый шов: явный multi_hub в конструкторе TerminalWidget
# ════════════════════════════════════════════════════════
print("== 7. explicit multi_hub seam (isolation) ==")

iso = MultiInputHub()   # изолированный хаб — не singleton приложения
t_iso_other = _FakeThread("h-iso", "u", 22)
tw = TerminalWidget(TerminalScreen(columns=120, lines=32), _FakeThread("h-src", "u", 22),
                    multi_hub=iso)
iso.set_session_provider(lambda: [_Page(t_iso_other, object())])
iso.set_active(True)
tw.keyPressEvent(key_event(Qt.Key.Key_Q, "q"))
check("явный multi_hub: broadcast через СВОЙ хаб", t_iso_other.channel.sent == [b"q"],
      repr(t_iso_other.channel.sent))
check("singleton приложения не затронут (изоляция)", hub_app.active is False)

# F12 на виджете с явным хабом — выход из ЕГО режима (не приложения)
t_iso_other.channel.sent.clear()
tw.keyPressEvent(key_event(Qt.Key.Key_F12, ""))
check("F12: выход из режима явного хаба, байты не ушли",
      iso.active is False and t_iso_other.channel.sent == [])


# ════════════════════════════════════════════════════════
# 8. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════
print("== 8. i18n parity + release state ==")

MULTI_KEYS = (
    "terminal.multi_status",
    "terminal.multi_exit_button",
    "terminal.multi_tab_badge",
    "terminal.multi_title_prefix",
    "view.multi_input",
    "status.multi_enabled",
    "status.multi_disabled",
)
langs = load_i18n_langs(ROOT)
check("v1.2.3: 7 новых ключей есть и не пусты в en/ru/zh",
      all(k in langs[c] and str(langs[c][k]).strip() for c in ("en", "ru", "zh") for k in MULTI_KEYS))
check("плейсхолдеры форматируются ({count}/{alias})",
      i18n.t("terminal.multi_status", count=5) == "MULTI: 5 sessions"
      and "{alias}" not in i18n.t("terminal.multi_tab_badge", alias="x"))
check_i18n_parity(langs)   # v1.2.3: +7 ключей (404 → 411)
check_release_state(ROOT)

# ── уборка: выход приложения — режим выключается, provider отвязывается ──────
try:
    mw.close()
except Exception:
    pass
app.processEvents()
check("шатдаун MainWindow: режим выключен, provider отвязан",
      hub_app.active is False and hub_app.session_provider is None)

ST.SSHTerminalThread = _orig_thread_cls
finish()
