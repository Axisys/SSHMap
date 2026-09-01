# -*- coding: utf-8 -*-
"""v1.0RC3 — Resize PTY + скроллбэк + dirty-рендер (ROADMAP v1.0RC3).

  * Скроллбэк на готовом pyte.HistoryScreen (TERMINAL.md §5.4, факт №7; ввод
    ТОЛЬКО с \\r\\n — факт №10): история растёт, prev/next page (страница =
    ceil(lines * ratio)), авто-возврат к live-строке при новом выводе (встроен
    в pyte before_event), границы (no-op наверху/снизу), лимит глубины;
  * Resize PTY — guard по смене сетки + дебаунс ~150 мс (TERMINAL.md §5.5,
    ROADMAP задача 6): фейковый channel считает вызовы resize_pty — 10 событий
    resize с одной сеткой → ровно 1 вызов PTY; начальный invoke_shell остаётся
    120×32, первый resizeEvent синхронизирует с окном; серия быстрых смен
    сетки коалесится в ОДИН вызов с последними размерами;
  * Клавиатура: Ctrl+Shift+PageUp/PageDown → скроллбэк (перехват ДО голых
    PageUp/PageDown — ловушка fall-through из ROADMAP), голые PgUp/PgDn
    остаются форвардом в shell (\\x1b[5~/\\x1b[6~ — семантика v1.0RC2, пейджинг
    less/man); Shift+PgUp без Ctrl и Ctrl+Alt+Shift+PgUp (AltGr-guard) не
    скроллят;
  * Колесо мыши: вверх → prev_page, вниз → next_page, no-op на границах;
    работает и при terminal_thread=None (локальная операция);
  * Dirty-рендер (ROADMAP задача 8): 33 мс-таймер удалён — _on_output →
    widget.update() напрямую (E2E через окно с фейковым потоком);
  * Мигание курсора: свой QTimer в TerminalWidget (старт showEvent, стоп
    hideEvent), переключение фазы меняет рендер блок-курсора;
  * Кнопка «Закрыть терминал» убрана (v1.0RC3): в окне нет QPushButton;
    close_terminal() сохранён (cleanup-путь MainWindow).

Запуск:  python tests/test_terminal_scroll.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, wait_until

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QTimer, QSize, QPointF, QPoint, QEventLoop
from PySide6.QtGui import QKeyEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton

app = QApplication(sys.argv)

import pyte

from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget


# ════════════════════════════════════════════════════════════
# 1. Скроллбэк: pyte.HistoryScreen (headless, без GUI; ввод только \\r\\n)
# ════════════════════════════════════════════════════════════
print("== HistoryScreen scrollback (headless) ==")

scr = TerminalScreen(columns=40, lines=32, history_lines=100)
check("TerminalScreen создаёт pyte.HistoryScreen",
      isinstance(scr.screen, pyte.HistoryScreen), type(scr.screen).__name__)

for i in range(50):
    scr.feed(f"line-{i:02d}\r\n".encode())   # факт №10: только \\r\\n

pos, size = scr.scroll_info()
check("после вывода: на live-строке (position == size)", pos == size, f"({pos}, {size})")
check("история растёт (top не пуст)", len(scr.screen.history.top) > 0,
      f"top_len={len(scr.screen.history.top)}")
check("at_bottom() — True на live-строке", scr.at_bottom() is True)

top_before = "".join(scr.screen.buffer[0][x].data for x in range(40))
moved = scr.scroll_up()
pos2, _ = scr.scroll_info()
top_after = "".join(scr.screen.buffer[0][x].data for x in range(40))
check("scroll_up() → True, позиция сместилась вверх", moved is True and pos2 < pos,
      f"({pos} -> {pos2})")
check("страница = ceil(lines * ratio) = 4 строки (32 × 0.1)", pos - pos2 == 4,
      f"delta={pos - pos2}")
check("видимый верхний ряд изменился (история подставлена)", top_before != top_after,
      f"before={top_before!r} after={top_after!r}")
check("at_bottom() — False после прокрутки вверх", scr.at_bottom() is False)

# Авто-возврат к live-строке при новом выводе (встроен в pyte before_event)
scr.feed(b"SNAP-MARKER\r\n")
pos3, _ = scr.scroll_info()
visible = "\n".join("".join(scr.screen.buffer[y][x].data for x in range(40))
                    for y in range(32))
check("новый вывод → авто-возврат к live (position == size)", pos3 == size,
      f"({pos3}, {size})")
check("новый вывод виден на экране", "SNAP-MARKER" in visible)

# Граница: верх истории — prev_page no-op
guard = 0
while scr.scroll_up() and guard < 100:
    guard += 1
top_pos, _ = scr.scroll_info()
check("верх истории: дальнейший scroll_up() → False (no-op)",
      scr.scroll_up() is False and scr.scroll_info()[0] == top_pos)

# Граница: live-строка — next_page no-op
while scr.scroll_down():
    pass
check("live-строка: at_bottom() снова True", scr.at_bottom() is True)
check("live-строка: дальнейший scroll_down() → False (no-op)", scr.scroll_down() is False)

# Лимит глубины истории (deque maxlen = history_lines)
scr_small = TerminalScreen(columns=20, lines=5, history_lines=10)
for i in range(60):
    scr_small.feed(f"s-{i:03d}\r\n".encode())
check("глубина истории ограничена (top <= history_lines)",
      len(scr_small.screen.history.top) <= 10,
      f"top_len={len(scr_small.screen.history.top)}")


# ════════════════════════════════════════════════════════════
# 2. Resize PTY: guard по сетке + дебаунс ~150 мс (offscreen-окно)
# ════════════════════════════════════════════════════════════
print("== resize PTY guard + debounce (offscreen) ==")


def spin(ms):
    """Прокрутка Qt event loop на ~ms (для дебаунс-таймеров)."""
    loop = QEventLoop()
    tmr = QTimer()
    tmr.setSingleShot(True)
    tmr.timeout.connect(loop.quit)
    tmr.start(ms)
    loop.exec()


class FakeChannel:
    """Фейковый paramiko-channel, считающий вызовы resize_pty (ROADMAP v1.0RC3)."""

    def __init__(self):
        self.closed = False
        self.calls = []   # [(width, height), ...]

    def resize_pty(self, width, height):
        self.calls.append((width, height))


import modules.ssh_terminal as ST
from models.server import ServerData

_orig_thread_cls = ST.SSHTerminalThread


class _FakeTerm(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        pass  # без сети


ST.SSHTerminalThread = _FakeTerm
win = None
chan = FakeChannel()
try:
    win = ST.SSHTerminalWindow(ServerData(id="rc3w", alias="T", host="127.0.0.1", user="u"), None)
    win.terminal_thread.channel = chan

    check("начальная сетка == invoke_shell 120×32 (до resizeEvent)",
          (win.tscreen.columns, win.tscreen.lines) == (120, 32),
          f"got=({win.tscreen.columns}, {win.tscreen.lines})")
    check("guard-состояние инициализировано под invoke_shell",
          (win._last_cols, win._last_rows) == (120, 32))

    # Первый resizeEvent (show → реальная геометрия окна) синхронизирует сетку.
    # Пересчёт отложен singleShot(0) — обработан внутри processEvents: layout уже
    # устоял, транзитный размер холста не участвует.
    win.show()
    app.processEvents()
    grid1 = (win.tscreen.columns, win.tscreen.lines)
    check("первый resizeEvent синхронизировал сетку с окном",
          grid1 != (120, 32) and grid1 == (win._last_cols, win._last_rows),
          f"grid={grid1} last=({win._last_cols}, {win._last_rows})")

    wait_until(lambda: len(chan.calls) >= 1, timeout_ms=2000)
    check("дебаунс истёк → ровно 1 вызов resize_pty с размерами сетки",
          chan.calls == [grid1], f"calls={chan.calls}")

    # 10 событий resize с ОДНОЙ и той же сеткой → guard: ни pyte.resize, ни PTY-сигнал
    sz = QSize(win.width(), win.height())
    for _ in range(10):
        win.resizeEvent(QResizeEvent(sz, sz))
    check("10 событий с одной сеткой: сразу — новых вызовов нет", len(chan.calls) == 1,
          f"calls={chan.calls}")
    spin(400)   # обрабатываем отложенные singleShot(0) и дебаунс — новых вызовов всё равно нет
    check("10 событий с одной сеткой → ровно 1 вызов PTY (итого)", len(chan.calls) == 1,
          f"calls={chan.calls}")
    check("сетка после 10 идентичных событий не изменилась",
          (win.tscreen.columns, win.tscreen.lines) == grid1)

    # Дебаунс коалесит серию быстрых смен сетки в ОДИН вызов с последними размерами
    win.resize(600, 400)
    app.processEvents()
    grid2 = (win.tscreen.columns, win.tscreen.lines)
    check("первая быстрая смена: pyte-сетка обновилась сразу", grid2 != grid1,
          f"grid={grid2}")
    win.resize(700, 500)
    app.processEvents()
    grid3 = (win.tscreen.columns, win.tscreen.lines)
    check("вторая быстрая смена: pyte-сетка снова обновилась", grid3 != grid2,
          f"grid={grid3}")
    wait_until(lambda: len(chan.calls) >= 2, timeout_ms=2000)
    spin(400)
    check("серия быстрых смен → один вызов PTY с ПОСЛЕДНИМИ размерами",
          len(chan.calls) == 2 and chan.calls[-1] == grid3, f"calls={chan.calls}")

    # Ручной pending при живом канале — debounce расходует его (один вызов)
    win._pending_pty = grid3
    win._pty_timer.start()
    spin(400)
    check("pending расходуется дебаунсом (канал жив)", win._pending_pty is None,
          f"pending={win._pending_pty}")

    # Мёртвый канал — resize_pty не шлётся (guard channel.closed)
    n_before = len(chan.calls)
    chan.closed = True
    win._last_cols, win._last_rows = 1, 1   # принудить «смену сетки»
    win.resizeEvent(QResizeEvent(sz, sz))
    spin(400)
    check("закрытый канал → resize_pty не вызывается", len(chan.calls) == n_before,
          f"calls={chan.calls}")
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 3. Клавиатура: Ctrl+Shift+PgUp/PgDn → скроллбэк, голые — в shell
# ════════════════════════════════════════════════════════════
print("== keyboard: Ctrl+Shift scroll vs bare forward ==")

sent = []


class FakeThread:
    def send_data(self, b):
        sent.append(b)

    def stop(self):
        pass


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier

scrk = TerminalScreen(columns=40, lines=10)
for i in range(40):
    scrk.feed(f"line-{i:02d}\r\n".encode())
wk = TerminalWidget(scrk, FakeThread())

# Ctrl+Shift+PageUp → скроллбэк (перехват ДО голых PageUp/PageDown)
sent.clear()
press_key(wk, Qt.Key.Key_PageUp, mod=CTRL | SHIFT)
check("Ctrl+Shift+PgUp: в shell ничего не уходит", sent == [], f"sent={sent!r}")
check("Ctrl+Shift+PgUp: скроллбэк вверх (не at_bottom)", scrk.at_bottom() is False)

# Ctrl+Shift+PageDown → обратно к live
sent.clear()
press_key(wk, Qt.Key.Key_PageDown, mod=CTRL | SHIFT)
check("Ctrl+Shift+PgDn: в shell ничего не уходит", sent == [], f"sent={sent!r}")
check("Ctrl+Shift+PgDn: возврат к live-строке", scrk.at_bottom() is True)

# Голые PageUp/PageDown — форвард в shell (семантика v1.0RC2: less/man пейджинг)
sent.clear()
press_key(wk, Qt.Key.Key_PageUp)
check("голый PgUp → b'\\x1b[5~' (в shell)", sent == [b"\x1b[5~"], f"sent={sent!r}")
sent.clear()
press_key(wk, Qt.Key.Key_PageDown)
check("голый PgDn → b'\\x1b[6~' (в shell)", sent == [b"\x1b[6~"], f"sent={sent!r}")

# Shift+PgUp БЕЗ Ctrl — тоже форвард (перехватывает только Ctrl+Shift)
sent.clear()
press_key(wk, Qt.Key.Key_PageUp, mod=SHIFT)
check("Shift+PgUp без Ctrl → b'\\x1b[5~' (форвард)", sent == [b"\x1b[5~"], f"sent={sent!r}")

# AltGr-guard: Ctrl+Alt+Shift+PgUp — ничего не шлётся и не скроллят
pos_before, _ = scrk.scroll_info()
sent.clear()
press_key(wk, Qt.Key.Key_PageUp, mod=CTRL | ALT | SHIFT)
check("Ctrl+Alt+Shift+PgUp (AltGr-guard): ничего не шлётся", sent == [], f"sent={sent!r}")
check("Ctrl+Alt+Shift+PgUp: скроллбэк не тронут", scrk.scroll_info()[0] == pos_before)


# ════════════════════════════════════════════════════════════
# 4. Колесо мыши — скроллбэк (включая terminal_thread=None)
# ════════════════════════════════════════════════════════════
print("== mouse wheel scrollback ==")


def wheel(w, dy):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)


scrw = TerminalScreen(columns=40, lines=10)
for i in range(40):
    scrw.feed(f"line-{i:02d}\r\n".encode())
ww = TerminalWidget(scrw, FakeThread())

top_before = "".join(scrw.screen.buffer[0][x].data for x in range(40))
wheel(ww, 120)    # вверх → prev_page
check("колесо вверх: скроллбэк (не at_bottom)", scrw.at_bottom() is False)
top_after = "".join(scrw.screen.buffer[0][x].data for x in range(40))
check("колесо вверх: видимый ряд изменился", top_before != top_after)

wheel(ww, -120)   # вниз → next_page (к live)
check("колесо вниз: возврат к live-строке", scrw.at_bottom() is True)

pos_b, _ = scrw.scroll_info()
top_now = "".join(scrw.screen.buffer[0][x].data for x in range(40))
wheel(ww, -120)   # на live — no-op
check("колесо вниз на live: no-op (позиция и экран не изменились)",
      scrw.scroll_info() == (pos_b, pos_b) and
      "".join(scrw.screen.buffer[0][x].data for x in range(40)) == top_now)

# terminal_thread=None — скроллбэк локален, работает без канала
scrn = TerminalScreen(columns=20, lines=5)
for i in range(30):
    scrn.feed(f"n-{i:02d}\r\n".encode())
wn = TerminalWidget(scrn, None)
wheel(wn, 120)
check("колесо при terminal_thread=None: скроллбэк работает", scrn.at_bottom() is False)


# ════════════════════════════════════════════════════════════
# 5. Dirty-рендер: 33 мс-таймер удалён, _on_output → update() напрямую
# ════════════════════════════════════════════════════════════
print("== dirty render (no 33ms timer) ==")


class _FakeTermOut(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        self.output_signal.emit(b"rc3-live\r\n")


ST.SSHTerminalThread = _FakeTermOut
win2 = None
try:
    win2 = ST.SSHTerminalWindow(ServerData(id="rc3w2", alias="T2", host="127.0.0.1", user="u"), None)
    check("33 мс render-таймер удалён (нет _render_timer/_dirty)",
          not hasattr(win2, "_render_timer") and not hasattr(win2, "_dirty"))
    win2.show()   # показанное окно реально перерисовывается (paintEvent)
    app.processEvents()
    wait_until(lambda: "rc3-live" in win2.widget.visible_text(), timeout_ms=1500)
    check("вывод отрендерился без таймера (E2E: queued signal → _on_output)",
          "rc3-live" in win2.widget.visible_text())
    # paint-хук: last_paint_stats["rows"] > 0 ⇔ paintEvent прошёл (в _paint)
    check("холст перерисован (paintEvent прошёл — last_paint_stats.rows > 0)",
          win2.widget.last_paint_stats["rows"] > 0,
          f"stats={win2.widget.last_paint_stats}")

    # Интеграция: экран окна — HistoryScreen со scroll API; кнопка закрытия убрана
    check("окно создаёт TerminalScreen на pyte.HistoryScreen",
          isinstance(win2.tscreen.screen, pyte.HistoryScreen))
    check("scroll API на экране окна", all(
        hasattr(win2.tscreen, m) for m in ("scroll_up", "scroll_down", "at_bottom", "scroll_info")))
    check("кнопка «Закрыть терминал» убрана: в окне нет QPushButton",
          win2.findChildren(QPushButton) == [])
    check("close_terminal() сохранён (cleanup-путь MainWindow)",
          callable(getattr(win2, "close_terminal", None)))
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win2 is not None:
        try:
            win2.close()
            app.processEvents()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 6. Мигание курсора: свой QTimer (showEvent старт / hideEvent стоп)
# ════════════════════════════════════════════════════════════
print("== cursor blink timer ==")


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


scr3 = TerminalScreen(columns=20, lines=5)
scr3.feed(b"X")   # курсор — на пустой ячейке (0,1)
wb = TerminalWidget(scr3, FakeThread())
cw, chh = wb.cell_size
wb.resize(cw * 20, chh * 5)

check("мигание — QTimer с BLINK_INTERVAL_MS",
      isinstance(wb._blink_timer, QTimer) and wb._blink_timer.interval() == TerminalWidget.BLINK_INTERVAL_MS,
      f"interval={getattr(wb._blink_timer, 'interval', lambda: None)()}")
check("до show(): таймер не активен", not wb._blink_timer.isActive())

wb.show()
app.processEvents()
check("showEvent → таймер мигания активен", wb._blink_timer.isActive())

# Реальное переключение фазы таймером (не вручную)
wait_until(lambda: not wb._cursor_visible, timeout_ms=1500)
check("таймер реально переключает фазу курсора", wb._cursor_visible is False)

# Рендер фаз: видимый курсор — блок CURSOR_COLOR; невидимая фаза — фон
cx_, cy_ = cw + cw // 2, chh // 2   # ячейка (row=0, col=1) — позиция курсора
wb._cursor_visible = True
wb.update()
app.processEvents()
px_on = pixel(wb.grab().toImage(), cx_, cy_)
wb._cursor_visible = False
wb.update()
app.processEvents()
px_off = pixel(wb.grab().toImage(), cx_, cy_)
check("видимая фаза: блок курсора CURSOR_COLOR #e2e8f0", px_on == (0xE2, 0xE8, 0xF0),
      f"px={px_on}")
check("невидимая фаза: курсор не рисуется (фон ≠ цвет курсора)",
      px_off != px_on and px_off == (0x0F, 0x17, 0x2A), f"px={px_off}")

wb.hide()
app.processEvents()
check("hideEvent → таймер мигания остановлен", not wb._blink_timer.isActive())
wb.show()
app.processEvents()
check("повторный show → таймер снова активен", wb._blink_timer.isActive())
wb.hide()
app.processEvents()

finish()
