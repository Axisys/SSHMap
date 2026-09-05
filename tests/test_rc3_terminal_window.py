# -*- coding: utf-8 -*-
"""v1.1.2RC3 — Окна терминала (ROADMAP v1.1.2RC3, AUDIT §4/§5).

Секция 1 — U3 «в mc не работают стрелки» (реализовано досрочно, до RC3-выпуска):
корневая причина подтверждена — полноэкранные TUI (mc/vim/htop) при запуске шлют
smkx \\x1b[?1h (DECCKM, Application Cursor Keys Mode) и дальше ОЖИДАЮТ стрелки в
SS3-форме (\\x1bOA…\\x1bOD), а не CSI (\\x1b[A…). Старый обработчик шёл жёстко
CSI — mc их не понимал («не работают»), а в bash под mc те же байты листали
историю (симптом из замечаний пользователей). Фикс: TerminalWidget выбирает
последовательность по tscreen.application_cursor_keys() (стрелки + Home/End;
PageUp/PageDown/Delete DECCKM не зависят — всегда CSI ~).

Проверенный факт pyte 0.8.2 (прогон на установленной версии): приватные режимы
хранятся в screen.mode со сдвигом влево на 5 бит (set_mode(private=True):
mode << 5) — DECCKM это **32**, а не 1; каноническая из интернета проверка
«1 in screen.mode» никогда не срабатывает. По умолчанию включены DECAWM
(7<<5=224, авто-wrap) и DECTCEM (25<<5=800, курсор виден). pyte.modes в 0.8.2
константы DECCKM нет.

Секции 2–4 — U3 клавиатура/потокобезопасность (CSI по умолчанию, SS3 при DECCKM,
feed из SSH-потока параллельно с чтением режима).

Секция 5 — N7: сброс выделения, когда новый вывод авто-возвращает скроллбэк к live.
Детект: pyte HistoryScreen.before_event() при ЛЮБОМ событии кроме prev/next_page
снапает position обратно к size (авто-возврат), а feed() — единственный путь,
меняющий позицию без ручного скролла; значит pos_before != pos_after ⇔ авто-возврат
состоялся → widget.clear_selection(). Обоснование: координаты выделения (row, col)
зафиксированы в release на ИСТОРИЧЕСКОМ экране, а после возврата они указывают на
ДРУГИЕ ячейки live-экрана — Ctrl+C скопировал бы чужой текст. Без нового вывода /
без активного выделения поведение простого клика и Ctrl+C не меняется (регрессии
проверены: выделение при live-выводе живёт; Ctrl+C с выделением копирует, без —
\x03).

Секция 6 — U3 остаток: wheel-passthrough через конфиг terminal_wheel
("scrollback" дефолт | "off"). pyte 0.8.2 не трекает mouse-режимы DECSET
1000/1002/1006, поэтому полный SGR-passthrough колеса в полноэкранное TUI отложен
на v1.2+ (слепая пересылка засорит shell без mouse-режима). "off": wheelEvent
игнорирует событие — локальный скроллбэк колесом не скроллится, в PTY ничего не
уходит; скроллбэк остаётся на Ctrl+Shift+PageUp/PageDown. Ключ только конфиг
(решение по ROADMAP v1.1.2RC3: без UI в диалоге настроек, i18n-паритет 375
не меняется; с v1.1.2 final паритет 377 — см. tests/test_status_parallel.py).

Секция 7 — U2: сохранение/восстановление размеров окон (modules/window_geometry.py):
при закрытии saveGeometry()/saveState() → base64 → ~/.sshmap/config.json
(ui_window_geometry_main / ui_window_geometry_terminal), при старте MainWindow и
создании окна терминала — restore. Битое значение / нет ключа → no-op + дефолтный
размер; обе функции никогда не бросают (teardown-safe). Offscreen-виртуальный экран
800×800: тестовые размеры ≤ 700×500, сверяется РАЗМЕР (позиция дрейфует +5 на
симулированном menubar'е), дефолт свежего QMainWindow — 640×480, поэтому round-trip
проверяется с не-дефолтным 700×500.

Секция 8 — состояние релиза: APP_VERSION == "1.1.3" (пин обновлён на финал серии),
пины pyproject/requirements.

Запуск:  python tests/test_rc3_terminal_window.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys
import threading
import time

from _common import bootstrap, check, finish, wait_until, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QEvent, QThread, QPoint, QPointF, QSize, Signal as QtSignal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMainWindow

app = QApplication(sys.argv)

import modules.ssh_terminal as ST
from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from modules.ssh_terminal import load_terminal_settings
from modules.window_geometry import save_window_geometry, restore_window_geometry
from models.server import ServerData
import ui.main_window as MW


# ════════════════════════════════════════════════════════════
# 1. U3: факт хранения DECCKM в pyte + TerminalScreen.application_cursor_keys()
# ════════════════════════════════════════════════════════════
print("== U3: DECCKM state in pyte (headless) ==")

scr = TerminalScreen(columns=80, lines=24)
check("свежий экран: DECCKM выключен", scr.application_cursor_keys() is False)
# Проверенный факт pyte 0.8.2: по умолчанию в режиме DECAWM (7<<5=224) + DECTCEM (25<<5=800)
check("факт pyte 0.8.2: дефолтный mode = {224, 800} (DECAWM+DECTCEM)",
      scr.screen.mode == {224, 800}, f"got={scr.screen.mode}")

scr.feed(b"\x1b[?1h")   # smkx — включение DECCKM (так делает mc при запуске)
check("после \\x1b[?1h: application_cursor_keys() True", scr.application_cursor_keys() is True)
check("факт pyte 0.8.2: DECCKM хранится как 32 (1<<5), а не 1",
      32 in scr.screen.mode and 1 not in scr.screen.mode, f"got={scr.screen.mode}")

scr.feed(b"\x1b[?1l")   # rmkx — выключение DECCKM
check("после \\x1b[?1l: application_cursor_keys() False", scr.application_cursor_keys() is False)
check("32 исчез из mode", 32 not in scr.screen.mode, f"got={scr.screen.mode}")

# Составная последовательность (несколько режимов сразу — как в реальных init-блоках TUI)
scr.feed(b"\x1b[?1;25h")
check("составная \\x1b[?1;25h: DECCKM True (32 и 800 в режиме)",
      scr.application_cursor_keys() is True and {32, 800} <= scr.screen.mode,
      f"got={scr.screen.mode}")
scr.feed(b"\x1b[?1l")   # снять DECCKM для чистоты дальше


# ════════════════════════════════════════════════════════════
# 2. U3: клавиатура offscreen — CSI по умолчанию (регрессия v1.0RC2)
# ════════════════════════════════════════════════════════════
print("== U3: keyboard, DECCKM off (CSI regression) ==")

sent = []


class FakeThread:
    def send_data(self, b):
        sent.append(b)

    def stop(self):
        pass


def make_widget(cols=20, lines=5, thread=None):
    s = TerminalScreen(columns=cols, lines=lines)
    return s, TerminalWidget(s, thread if thread is not None else FakeThread())


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


scr, w = make_widget()

# Обычный режим (bash): стрелки и Home/End — CSI (семантика v1.0RC2 сохранена)
for label, k, e in (("Up", Qt.Key.Key_Up, b"\x1b[A"),
                    ("Down", Qt.Key.Key_Down, b"\x1b[B"),
                    ("Left", Qt.Key.Key_Left, b"\x1b[D"),
                    ("Right", Qt.Key.Key_Right, b"\x1b[C"),
                    ("Home", Qt.Key.Key_Home, b"\x1b[H"),
                    ("End", Qt.Key.Key_End, b"\x1b[F")):
    sent.clear()
    press_key(w, k)
    check(f"DECCKM off: {label} → {e!r}", sent == [e], f"sent={sent!r}")


# ════════════════════════════════════════════════════════════
# 3. U3: клавиатура offscreen — SS3 при DECCKM (сценарий mc)
# ════════════════════════════════════════════════════════════
print("== U3: keyboard, DECCKM on (SS3, mc scenario) ==")

# «Запуск mc»: приложение шлёт smkx в PTY-вывод — pyte фиксирует режим
scr.feed(b"\x1b[?1h")

for label, k, e in (("Up", Qt.Key.Key_Up, b"\x1bOA"),
                    ("Down", Qt.Key.Key_Down, b"\x1bOB"),
                    ("Left", Qt.Key.Key_Left, b"\x1bOD"),
                    ("Right", Qt.Key.Key_Right, b"\x1bOC"),
                    ("Home", Qt.Key.Key_Home, b"\x1bOH"),
                    ("End", Qt.Key.Key_End, b"\x1bOF")):
    sent.clear()
    press_key(w, k)
    check(f"DECCKM on: {label} → {e!r}", sent == [e], f"sent={sent!r}")

# DECCKM НЕ зависит: PageUp/PageDown/Delete всегда CSI ~, F1–F4 всегда SS3 (это
# их обычное кодирование), F5 — CSI; Enter/Backspace не меняются.
for label, k, e in (("PageUp", Qt.Key.Key_PageUp, b"\x1b[5~"),
                    ("PageDown", Qt.Key.Key_PageDown, b"\x1b[6~"),
                    ("Delete", Qt.Key.Key_Delete, b"\x1b[3~"),
                    ("F1", Qt.Key.Key_F1, b"\x1bOP"),
                    ("F4", Qt.Key.Key_F4, b"\x1bOS"),
                    ("F5", Qt.Key.Key_F5, b"\x1b[15~"),
                    ("Enter", Qt.Key.Key_Return, b"\r"),
                    ("Backspace", Qt.Key.Key_Backspace, b"\x7f")):
    sent.clear()
    press_key(w, k)
    check(f"DECCKM on: {label} не зависит от режима → {e!r}", sent == [e], f"sent={sent!r}")

# «Выход из mc»: rmkx — обратно CSI (shell снова в обычном режиме)
scr.feed(b"\x1b[?1l")
for label, k, e in (("Up", Qt.Key.Key_Up, b"\x1b[A"),
                    ("Home", Qt.Key.Key_Home, b"\x1b[H")):
    sent.clear()
    press_key(w, k)
    check(f"после \\x1b[?1l: {label} снова → {e!r}", sent == [e], f"sent={sent!r}")

# Цикл mc-сессий: состояние следует за выводом приложения (вкл/выкл/вкл)
seq_seen = []
for payload in (b"\x1b[?1h", b"\x1b[?1l", b"\x1b[?1h"):
    scr.feed(payload)
    sent.clear()
    press_key(w, Qt.Key.Key_Up)
    seq_seen.append(sent[0] if sent else None)
check("цикл smkx/rmkx: Up следует за режимом (SS3/CSI/SS3)",
      seq_seen == [b"\x1bOA", b"\x1b[A", b"\x1bOA"], f"got={seq_seen!r}")

# terminal_thread=None + DECCKM on — ввод отключён: без исключений, байтов нет
# (прямо None, а не FakeThread из make_widget!)
scr0 = TerminalScreen(columns=20, lines=5)
w0 = TerminalWidget(scr0, None)
scr0.feed(b"\x1b[?1h")
try:
    sent.clear()
    press_key(w0, Qt.Key.Key_Up)
    check("thread=None + DECCKM on: без исключений, ничего не шлётся", sent == [])
except Exception as e:
    check("thread=None + DECCKM on: без исключений, ничего не шлётся", False, repr(e))


# ════════════════════════════════════════════════════════════
# 4. U3: потокобезопасность — feed() из SSH-потока параллельно с чтением режима
# ════════════════════════════════════════════════════════════
print("== U3: thread-safety smoke ==")

scr_t = TerminalScreen(columns=80, lines=24)
stop_flag = {"go": True}


def _feed_loop():
    # Имитация PTY-вывода: приложение часто переключает режимы (smkx/rmkx)
    while stop_flag["go"]:
        scr_t.feed(b"\x1b[?1h")
        scr_t.feed(b"\x1b[?1l")


t = threading.Thread(target=_feed_loop, daemon=True)
t.start()
errors = []
try:
    for _ in range(300):
        scr_t.application_cursor_keys()
except Exception as e:  # pragma: no cover
    errors.append(repr(e))
stop_flag["go"] = False
t.join(timeout=5.0)
check("feed из другого потока + чтение DECCKM: без исключений/зависаний",
      not t.is_alive() and not errors, f"errors={errors!r} alive={t.is_alive()}")


# ════════════════════════════════════════════════════════════
# 5. N7: сброс выделения при авто-возврате скроллбэка к live
# ════════════════════════════════════════════════════════════
print("== N7: selection cleared on auto-return to live ==")


class _FakeChannel:
    closed = False

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)


class _FakeSSHThread(QThread):
    """Тот же API, что у SSHTerminalThread; run() — pass (реальный SSH не нужен)."""
    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.channel = _FakeChannel()
        self.running = True

    def run(self):
        pass

    def stop(self):
        self.running = False

    def send_data(self, data_bytes):
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            self.channel.send(data_bytes)


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread   # все окна терминала в этом файле — на фейке

_term_windows = []


def make_term_win(alias):
    """Окно терминала с фейковым потоком + синхронизация сетки (паттерн acceptance)."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"rc3-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password="pw")
    _term_windows.append(w)
    w.resize(700, 500)   # resizeEvent → singleShot(0) → _sync_grid (guard по сетке)
    wait_until(lambda: (w._last_cols, w._last_rows) != (120, 32), timeout_ms=3000)
    app.processEvents()
    return w


def press_lmb(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                  Qt.KeyboardModifier.NoModifier))


def move_lmb(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
                                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier))


def release_lmb(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))


def select_drag(w):
    """Реалистичный drag-выделение (0,0)→(2,4) — паттерн tests/test_terminal_input.py."""
    press_lmb(w, 0, 0)
    move_lmb(w, 1, 2)
    release_lmb(w, 2, 4)


CTRL = Qt.KeyboardModifier.ControlModifier

win_n7 = make_term_win("n7")
for i in range(60):   # ~60 строк истории — скроллбэк становится прокручиваемым
    win_n7.page._on_output(f"hist line {i:03d}\r\n".encode())  # v1.2: сессия на странице
app.processEvents()

pos_live, _size = win_n7.tscreen.scroll_info()
check("свежий вывод: мы на live-строке (at_bottom)", win_n7.tscreen.at_bottom(),
      f"info={win_n7.tscreen.scroll_info()}")

# Прокрутка в историю (GUI-путь: колесо/страница вверх) + выделение мышью
check("scroll_page_up: позиция ушла в историю", win_n7.widget.scroll_page_up() is True)
pos_up, _ = win_n7.tscreen.scroll_info()
check("позиция истории < live (position < size)", pos_up < pos_live,
      f"up={pos_up} live={pos_live}")
select_drag(win_n7.widget)
check("выделение в истории активно", win_n7.widget.has_selection())

# Новый вывод → pyte before_event авто-возврат к live → N7 сбрасывает выделение
win_n7.page._on_output(b"new output line\r\n")  # v1.2: сессия на странице
app.processEvents()
pos_after, _ = win_n7.tscreen.scroll_info()
check("авто-возврат: позиция снова == live", pos_after == pos_live,
      f"after={pos_after} live={pos_live}")
check("N7: выделение сброшено после авто-возврата", not win_n7.widget.has_selection())

# Регрессия: Ctrl+C ПОСЛЕ N7-сброса — SIGINT (выделения уже нет)
win_n7.terminal_thread.channel.sent.clear()
press_key(win_n7.widget, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C после N7-сброса → b'\\x03'", win_n7.terminal_thread.channel.sent == [b"\x03"],
      f"sent={win_n7.terminal_thread.channel.sent!r}")

# Регрессия: вывод при live-позиции (без авто-возврата) — выделение ЖИВЁТ
select_drag(win_n7.widget)
check("выделение на live активно", win_n7.widget.has_selection())
win_n7.page._on_output(b"more output at live\r\n")  # v1.2: сессия на странице
app.processEvents()
check("вывод при live (позиция не менялась) → выделение сохранено",
      win_n7.widget.has_selection())

# Регрессия: Ctrl+C с активным выделением — копирование, в PTY ничего (v0.9.3)
win_n7.terminal_thread.channel.sent.clear()
press_key(win_n7.widget, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C с выделением → в канал ничего", win_n7.terminal_thread.channel.sent == [])
check("буфер обмена получил текст выделения", app.clipboard().text() != "")
win_n7.widget.clear_selection()

# E2E: тот же путь через output_signal (queued-сигнал из SSH-потока)
check("scroll_page_up (E2E): в историю", win_n7.widget.scroll_page_up() is True)
select_drag(win_n7.widget)
win_n7.terminal_thread.output_signal.emit(b"signal-driven line\r\n")
app.processEvents()
check("E2E через output_signal: авто-возврат + сброс выделения",
      not win_n7.widget.has_selection())


# ════════════════════════════════════════════════════════════
# 6. U3 остаток: колесо — конфиг terminal_wheel ("scrollback" | "off")
# ════════════════════════════════════════════════════════════
print("== wheel: config validation + wheelEvent modes ==")


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


def read_cfg():
    with open(_cfg_path(), encoding="utf-8") as f:
        return json.load(f)


# ── валидация ключа (load_terminal_settings) ────────────────────────────────
clear_config()
check("wheel: без ключа → дефолт 'scrollback'", load_terminal_settings()["wheel"] == "scrollback")
write_config({"terminal_wheel": "off"})
check("wheel: 'off' → 'off'", load_terminal_settings()["wheel"] == "off")
write_config({"terminal_wheel": " OFF "})
check("wheel: ' OFF ' (strip+lower) → 'off'", load_terminal_settings()["wheel"] == "off")
write_config({"terminal_wheel": "garbage"})
check("wheel: битое значение → дефолт 'scrollback'",
      load_terminal_settings()["wheel"] == "scrollback")
write_config({"terminal_wheel": 123})
check("wheel: чужой тип (int) → дефолт 'scrollback'",
      load_terminal_settings()["wheel"] == "scrollback")


def wheel_event(dy):
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


# ── виджет: "off" — колесо не скроллит и не шлёт в PTY ──────────────────────
scr_off = TerminalScreen(columns=80, lines=24)
w_off = TerminalWidget(scr_off, FakeThread(), wheel_mode="off")
for i in range(60):
    scr_off.feed(f"line {i:03d}\r\n".encode())
check("wheel off: скроллбэк заполнен (scroll_up работает напрямую)",
      scr_off.scroll_up() is True)
pos_b, size_off = scr_off.scroll_info()
sent.clear()
ev_up = wheel_event(+120)
w_off.wheelEvent(ev_up)
pos_a, _ = scr_off.scroll_info()
check("wheel off: колесо вверх НЕ скроллит локальный скроллбэк", pos_b == pos_a,
      f"before={pos_b} after={pos_a}")
check("wheel off: событие не потреблено (event.ignore)", not ev_up.isAccepted())
check("wheel off: в PTY ничего не ушло", sent == [])
ev_dn = wheel_event(-120)
w_off.wheelEvent(ev_dn)
check("wheel off: колесо вниз тоже игнорируется, позиция та же",
      not ev_dn.isAccepted() and scr_off.scroll_info() == (pos_b, size_off))

# ── виджет: "scrollback" (дефолт) — колесо скроллит локальный скроллбэк ─────
scr_sb = TerminalScreen(columns=80, lines=24)
w_sb = TerminalWidget(scr_sb, FakeThread())   # wheel_mode не задан → дефолт
check("wheel: виджет без параметра — дефолтный режим 'scrollback'",
      w_sb._wheel_mode == "scrollback")
check("wheel: битое значение параметра → 'scrollback'",
      TerminalWidget(TerminalScreen(columns=80, lines=24), FakeThread(),
                     wheel_mode="bogus")._wheel_mode == "scrollback")
for i in range(60):
    scr_sb.feed(f"line {i:03d}\r\n".encode())
check("scrollback: на live-строке", scr_sb.at_bottom())
ev_up2 = wheel_event(+120)
w_sb.wheelEvent(ev_up2)
pos_up2, _ = scr_sb.scroll_info()
check("scrollback: колесо вверх скроллит в историю + accept",
      pos_up2 < _size and ev_up2.isAccepted(), f"pos={pos_up2}")
ev_dn2 = wheel_event(-120)
w_sb.wheelEvent(ev_dn2)
check("scrollback: колесо вниз возвращает к live + accept",
      scr_sb.at_bottom() and ev_dn2.isAccepted())

# ── окно терминала: режим читается из конфига при создании ──────────────────
write_config({"terminal_wheel": "off"})
win_w_off = ST.SSHTerminalWindow(
    ServerData(id="rc3-w-off", alias="w-off", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_w_off)
check("окно: terminal_wheel='off' → widget._wheel_mode == 'off'",
      win_w_off.widget._wheel_mode == "off")
clear_config()
win_w_def = ST.SSHTerminalWindow(
    ServerData(id="rc3-w-def", alias="w-def", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_w_def)
check("окно: без ключа → widget._wheel_mode == 'scrollback' (дефолт)",
      win_w_def.widget._wheel_mode == "scrollback")


# ════════════════════════════════════════════════════════════
# 7. U2: сохранение/восстановление размеров окон
# ════════════════════════════════════════════════════════════
print("== U2: window geometry save/restore ==")

_geo_windows = []


def plain_main_win():
    w = QMainWindow()   # без parent — держим ссылку, чтобы C++-объект не уехал в GC
    _geo_windows.append(w)
    app.processEvents()
    return w


# ── helper round-trip: save → restore в свежее окно (не-дефолтный размер) ───
clear_config()
w_a = plain_main_win()
w_a.resize(700, 500)   # дефолт QMainWindow — 640×480, значит восстановление видно
app.processEvents()
check("U2: save_window_geometry → True", save_window_geometry("rc3_test_key", w_a) is True)
_val = read_cfg().get("rc3_test_key")
check("U2: значение — dict {geometry, state} (base64-строки)",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}
      and bool(_val["geometry"]) and bool(_val["state"]), f"got={_val!r}")

w_b = plain_main_win()
check("U2: restore_window_geometry → True", restore_window_geometry("rc3_test_key", w_b) is True)
check("U2: восстановлен размер 700×500 (а не дефолт 640×480)",
      w_b.size() == QSize(700, 500), f"got={w_b.size()}")

# ── битые значения / чужой тип / нет ключа → no-op + False ──────────────────
write_config({"rc3_test_key": {"geometry": "!!!not-base64", "state": "zzz"}})
w_c = plain_main_win()
check("U2: битый base64 → False", restore_window_geometry("rc3_test_key", w_c) is False)
check("U2: битое значение — размер остался дефолтным 640×480",
      w_c.size() == QSize(640, 480), f"got={w_c.size()}")

write_config({"rc3_test_key": "just-a-string"})
w_d = plain_main_win()
check("U2: значение не dict → False", restore_window_geometry("rc3_test_key", w_d) is False)

clear_config()
w_e = plain_main_win()
check("U2: нет ключа → False + дефолтный размер",
      restore_window_geometry("rc3_test_key", w_e) is False
      and w_e.size() == QSize(640, 480), f"got={w_e.size()}")

# ── E2E окно терминала: closeEvent сохраняет, новое окно восстанавливает ─────
clear_config()
win_t1 = ST.SSHTerminalWindow(
    ServerData(id="rc3-geo-1", alias="geo-1", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_t1)
win_t1.resize(640, 480)   # дефолт окна терминала — 800×600, восстановление видно
app.processEvents()
_ev_close = QCloseEvent()
win_t1.closeEvent(_ev_close)
check("U2: closeEvent терминала принят (без 'ask'-диалога)", _ev_close.isAccepted())
_val = read_cfg().get("ui_window_geometry_terminal")
check("U2: ключ ui_window_geometry_terminal записан {geometry, state}",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}, f"got={_val!r}")

win_t2 = ST.SSHTerminalWindow(
    ServerData(id="rc3-geo-2", alias="geo-2", host="10.99.0.1", user="root"), None, password="pw")
_term_windows.append(win_t2)
app.processEvents()
check("U2: новое окно терминала восстановило 640×480 (дефолт 800×600)",
      win_t2.size() == QSize(640, 480), f"got={win_t2.size()}")

# ── E2E главное окно: closeEvent сохраняет, новый MainWindow восстанавливает ─
clear_config()
mw1 = MW.MainWindow()
_geo_windows.append(mw1)
mw1.resize(700, 500)   # дефолт главного окна — 1200×850 (offscreen: клампится к 800×800)
app.processEvents()
_ev_close2 = QCloseEvent()
mw1.closeEvent(_ev_close2)
check("U2: closeEvent MainWindow принят (_dirty=False → без диалога)", _ev_close2.isAccepted())
_val = read_cfg().get("ui_window_geometry_main")
check("U2: ключ ui_window_geometry_main записан {geometry, state}",
      isinstance(_val, dict) and set(_val) == {"geometry", "state"}, f"got={_val!r}")

mw2 = MW.MainWindow()
_geo_windows.append(mw2)
app.processEvents()
check("U2: новый MainWindow восстановил 700×500 (дефолт 1200×850)",
      mw2.size() == QSize(700, 500), f"got={mw2.size()}")

clear_config()


# ════════════════════════════════════════════════════════════
# 8. Состояние релиза (пины — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

finish()
