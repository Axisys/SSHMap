# -*- coding: utf-8 -*-
"""v1.2.13 — колесо мыши в полноэкранном TUI (SGR/X10 passthrough) (ROADMAP v1.2.13, PYTE82_AUDIT.md пачка C).

  * Headless-матрица режимов: DECSET 1000/1002/1003 × 1006 — mouse_tracking() ==
    (enabled, sgr); 1006 ОДИН → (False, True) (xterm-семантика: 1006 — только
    кодировка отчётов, без 1000/1002/1003 mouse-событий нет — исправление
    acceptance ROADMAP'а); \x1b[?…l — выключение; RIS (\x1bc) чистит режимы;
    htop-стиль переключения во время сессии (чтение на каждое событие — кэша нет);
  * Offscreen Qt с фейковым потоком (паттерн test_terminal_input.py): колесо при
    1006 → в send_data уходит РОВНО \x1b[<64;{col};{row}M (up=64, down=65 — ctlseqs:
    кнопки 4/5 = коды событий кнопок 1/2 + 64), при 1002 без 1006 → X10 \x1b[M +
    [96|97, 32+col, 32+row]; координаты зажаты в сетку; X10 дополнительно — в лимит
    протокола 223 (=255−32, ctlseqs «Extended coordinates»: расширения только через
    UTF-8 1005 / SGR 1006);
  * Alt без tracking → no-op (регрессия v1.2.12: в PTY ничего, скроллбэк не тронут,
    событие не потребляется — пропагация безвредна, предков-QScrollArea нет);
  * Passthrough приоритетнее terminal_wheel="off"; "off" без tracking — event.ignore
    + ничего не шлётся (регрессия v1.1.2RC3);
  * Скроллбэк-регрессия (без режимов): вверх → prev_page, вниз → next_page;
  * Мультинабор: байты колеса НЕ проходят hub.broadcast (координаты сессионно-локальны)
    — при активном хабе и чужой сессии в реестре их получает только источник;
  * terminal_thread=None + tracking — без исключений.

Запуск:  python tests/test_terminal_mouse.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, check_release_state, load_i18n_langs, check_i18n_parity

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QPointF, QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import pyte

from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget
from modules.multi_input import MultiInputHub


class FakeThread:
    """Фейковый SSHTerminalThread: send_data(b) — в список (паттерн test_terminal_input.py)."""

    def __init__(self):
        self.sent = []

    def send_data(self, b):
        self.sent.append(b)

    def stop(self):
        pass


def make_wheel(pos_x, pos_y, angle_dy=120):
    """Синтетическое QWheelEvent в координатах виджета (паттерн test_terminal_scroll.py)."""
    return QWheelEvent(QPointF(pos_x, pos_y), QPointF(pos_x, pos_y), QPoint(0, 0),
                       QPoint(0, angle_dy), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)


# ════════════════════════════════════════════════════════════
# 1. Headless: матрица mouse-режимов DECSET 1000/1002/1003 × 1006
# ════════════════════════════════════════════════════════════
print("== headless: mouse_tracking() mode matrix ==")

scr = TerminalScreen(columns=80, lines=24)
check("свежий экран: mouse_tracking() == (False, False)",
      scr.mouse_tracking() == (False, False), str(scr.mouse_tracking()))

# 1006 ОДИН — кодировка, не tracking (исправленное acceptance ROADMAP v1.2.13)
scr.feed(b"\x1b[?1006h")
check("1006 один → (False, True): SGR-кодировка без 1000/1002/1003 tracking не включает",
      scr.mouse_tracking() == (False, True), str(scr.mouse_tracking()))
scr.feed(b"\x1b[?1006l")

# Матрица: каждый tracking-режим × 1006
for n in (1000, 1002, 1003):
    s = TerminalScreen(columns=40, lines=10)
    s.feed(f"\x1b[?{n}h".encode())
    check(f"DECSET {n} один → (True, False)", s.mouse_tracking() == (True, False),
          str(s.mouse_tracking()))
    s.feed(b"\x1b[?1006h")
    check(f"DECSET {n}+1006 → (True, True)", s.mouse_tracking() == (True, True),
          str(s.mouse_tracking()))
    s.feed(f"\x1b[?{n}l".encode())
    check(f"{n} выключен, 1006 остался → (False, True)", s.mouse_tracking() == (False, True),
          str(s.mouse_tracking()))
    s.feed(b"\x1b[?1006l")
    check(f"все выключены → (False, False)", s.mouse_tracking() == (False, False),
          str(s.mouse_tracking()))

# Несколько tracking-режимов одновременно
s2 = TerminalScreen(columns=40, lines=10)
s2.feed(b"\x1b[?1000h\x1b[?1002h")
check("1000+1002 → (True, False)", s2.mouse_tracking() == (True, False), str(s2.mouse_tracking()))

# htop-стиль: включение/выключение во время сессии — чтение на каждое событие (кэша нет)
s3 = TerminalScreen(columns=40, lines=10)
s3.feed(b"\x1b[?1003h\x1b[?1006h")
check("htop-старт: 1003+1006 → (True, True)", s3.mouse_tracking() == (True, True),
      str(s3.mouse_tracking()))
s3.feed(b"\x1b[?1003l\x1b[?1006l")
check("htop-выход: повторное чтение того же экрана → (False, False) (кэша нет)",
      s3.mouse_tracking() == (False, False), str(s3.mouse_tracking()))

# RIS (\x1bc — НЕ \x1b[c): полный reset чистит mouse-режимы
s4 = TerminalScreen(columns=40, lines=10)
s4.feed(b"\x1b[?1003h\x1b[?1006h")
s4.feed(b"\x1bc")
check("RIS (\\x1bc): mouse-режимы сброшены → (False, False)",
      s4.mouse_tracking() == (False, False), str(s4.mouse_tracking()))


# ════════════════════════════════════════════════════════════
# 2. Offscreen Qt: SGR-passthrough (ровно \x1b[<64;{col};{row}M)
# ════════════════════════════════════════════════════════════
print("== offscreen: SGR passthrough ==")

scrw = TerminalScreen(columns=40, lines=12)
for i in range(30):
    scrw.feed(f"line-{i:02d}\r\n".encode())   # история есть (скроллбэк-регрессия ниже)
thread = FakeThread()
scrw.feed(b"\x1b[?1000h\x1b[?1006h")
w = TerminalWidget(scrw, thread)
cw, chh = w.cell_size

# Центр ячейки (col=5, row=3): пиксели (4*cw + cw//2, 2*chh + chh//2) → x//cw+1=5, y//chh+1=3
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
w.wheelEvent(ev)
check("колесо вверх при 1006: ровно b'\\x1b[<64;5;3M'", thread.sent == [b"\x1b[<64;5;3M"],
      repr(thread.sent))
check("событие потреблено (accept)", ev.isAccepted() is True)

thread.sent.clear()
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=-120)
w.wheelEvent(ev)
check("колесо вниз при 1006: ровно b'\\x1b[<65;5;3M'", thread.sent == [b"\x1b[<65;5;3M"],
      repr(thread.sent))

check("скроллбэк не тронут (at_bottom)", scrw.at_bottom() is True)

# Позиция мыши ЗА сетью (виджет шире/выше сетки на остаток округления метрик) → кламп в [1..40]×[1..12]
thread.sent.clear()
ev = make_wheel(cw * 42 + cw // 2, chh * 15 + chh // 2, angle_dy=120)
w.wheelEvent(ev)
check("координаты за сетью зажаты: b'\\x1b[<64;40;12M'", thread.sent == [b"\x1b[<64;40;12M"],
      repr(thread.sent))


# ════════════════════════════════════════════════════════════
# 3. Offscreen Qt: X10-passthrough (\x1b[M + [96|97, 32+col, 32+row])
# ════════════════════════════════════════════════════════════
print("== offscreen: X10 passthrough ==")

scrx = TerminalScreen(columns=40, lines=12)
threadx = FakeThread()
scrx.feed(b"\x1b[?1002h")   # tracking БЕЗ 1006 → X10
wx = TerminalWidget(scrx, threadx)
cw, chh = wx.cell_size

ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wx.wheelEvent(ev)
check("X10 вверх: ровно b'\\x1b[M' + [96, 37, 35]",
      threadx.sent == [b"\x1b[M" + bytes([96, 32 + 5, 32 + 3])], repr(threadx.sent))

threadx.sent.clear()
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=-120)
wx.wheelEvent(ev)
check("X10 вниз: ровно b'\\x1b[M' + [97, 37, 35]",
      threadx.sent == [b"\x1b[M" + bytes([97, 32 + 5, 32 + 3])], repr(threadx.sent))

check("скроллбэк не тронут (at_bottom)", scrx.at_bottom() is True)


# ════════════════════════════════════════════════════════════
# 4. X10-лимит протокола 223 (ультраширокая сетка >223 колонки)
# ════════════════════════════════════════════════════════════
print("== X10 protocol limit 223 (ultrawide grid) ==")

scrwide = TerminalScreen(columns=260, lines=12)   # сетка шире протокольного лимита
threadw = FakeThread()
scrwide.feed(b"\x1b[?1000h")   # X10 (без 1006)
ww = TerminalWidget(scrwide, threadw)
cw, chh = ww.cell_size

# Ячейка col=230 (>223) → клампится в 223: байт = 32+223 = 255
ev = make_wheel(cw * 229 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
ww.wheelEvent(ev)
check("X10: col=230 > 223 → кламп в лимит протокола (байт 255)",
      threadw.sent == [b"\x1b[M" + bytes([96, 255, 35])], repr(threadw.sent))

# SGR на той же сетке — без клампа (лимитов нет)
threadw.sent.clear()
scrwide.feed(b"\x1b[?1006h")
ev = make_wheel(cw * 229 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
ww.wheelEvent(ev)
check("SGR на той же широкой сетке: без клампа — b'\\x1b[<64;230;3M'",
      threadw.sent == [b"\x1b[<64;230;3M"], repr(threadw.sent))


# ════════════════════════════════════════════════════════════
# 5. Alt-экран БЕЗ tracking → no-op (регрессия гейта v1.2.12)
# ════════════════════════════════════════════════════════════
print("== alt screen without tracking: no-op ==")

scra = TerminalScreen(columns=40, lines=12)
threada = FakeThread()
wa = TerminalWidget(scra, threada)
for i in range(30):
    scra.feed(f"a-{i:02d}\r\n".encode())
pos_before = scra.scroll_info()
scra.feed(b"\x1b[?1049h")   # alt-экран, mouse-режимы НЕ включены
check("в alt (in_alt_screen True)", scra.in_alt_screen() is True)

ev = make_wheel(5, 5, angle_dy=120)
ev.setAccepted(False)   # синтетический QWheelEvent рождается accepted=True (нюанс PySide6) — сбрасываем для наблюдения
wa.wheelEvent(ev)
check("alt без tracking: в PTY ничего не уходит", threada.sent == [], repr(threada.sent))
check("alt без tracking: скроллбэк не тронут", scra.scroll_info() == pos_before)
check("alt без tracking: событие НЕ потреблено (пропагация, как в v1.2.12)",
      ev.isAccepted() is False)
scra.feed(b"\x1b[?1049l")

# Alt + tracking → passthrough (TUI с mouse-режимами владеет сеткой и ждёт отчёты)
threada.sent.clear()
scra.feed(b"\x1b[?1049h\x1b[?1003h\x1b[?1006h")
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wa.wheelEvent(ev)
check("alt + tracking: колесо уходит в PTY (SGR)", threada.sent == [b"\x1b[<64;5;3M"],
      repr(threada.sent))
scra.feed(b"\x1b[?1003l\x1b[?1006l\x1b[?1049l")


# ════════════════════════════════════════════════════════════
# 6. Passthrough приоритетнее terminal_wheel="off" (+ регрессия "off")
# ════════════════════════════════════════════════════════════
print("== wheel_mode='off' vs passthrough ==")

scro = TerminalScreen(columns=40, lines=12)
threado = FakeThread()
wo = TerminalWidget(scro, threado, wheel_mode="off")
for i in range(30):
    scro.feed(f"o-{i:02d}\r\n".encode())
scro.feed(b"\x1b[?1000h\x1b[?1006h")

ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wo.wheelEvent(ev)
check("tracking + 'off': passthrough приоритетнее — байты в PTY",
      threado.sent == [b"\x1b[<64;5;3M"], repr(threado.sent))
check("...и скроллбэк не тронут", scro.at_bottom() is True)

# 'off' БЕЗ tracking — регрессия v1.1.2RC3: event.ignore, ничего не шлётся, нет скролла
scro.feed(b"\x1b[?1000l\x1b[?1006l")
threado.sent.clear()
pos_before = scro.scroll_info()
ev = make_wheel(5, 5, angle_dy=120)
wo.wheelEvent(ev)
check("'off' без tracking: event.ignore (не потреблено)", ev.isAccepted() is False)
check("'off' без tracking: в PTY ничего не уходит", threado.sent == [], repr(threado.sent))
check("'off' без tracking: скроллбэк не тронут", scro.scroll_info() == pos_before)


# ════════════════════════════════════════════════════════════
# 7. Скроллбэк-регрессия (без mouse-режимов — поведение v1.0RC3)
# ════════════════════════════════════════════════════════════
print("== scrollback regression (no modes) ==")

scrs = TerminalScreen(columns=40, lines=12)
threads_ = FakeThread()
ws = TerminalWidget(scrs, threads_)
for i in range(30):
    scrs.feed(f"s-{i:02d}\r\n".encode())

ev = make_wheel(5, 5, angle_dy=120)
ws.wheelEvent(ev)
check("без режимов: колесо вверх → скроллбэк (не at_bottom)", scrs.at_bottom() is False)
check("без режимов: в PTY ничего не уходит", threads_.sent == [], repr(threads_.sent))

ev = make_wheel(5, 5, angle_dy=-120)
ws.wheelEvent(ev)
check("колесо вниз → возврат к live-строке", scrs.at_bottom() is True)


# ════════════════════════════════════════════════════════════
# 8. Мультинабор: байты колеса НЕ проходят broadcast (сессионно-локальные координаты)
# ════════════════════════════════════════════════════════════
print("== multi-input: wheel bypasses hub.broadcast ==")

hub = MultiInputHub()   # явный хаб — тестовый шов (изоляция от singleton'а приложения)
thread_other = FakeThread()
page_other = type("_Page", (), {})()
page_other.widget = None                    # НЕ источник → broadcast бы её не пропустил
page_other.terminal_thread = thread_other

scrmi = TerminalScreen(columns=40, lines=12)
threadmi = FakeThread()
wmi = TerminalWidget(scrmi, threadmi, multi_hub=hub)
for i in range(30):
    scrmi.feed(f"m-{i:02d}\r\n".encode())
scrmi.feed(b"\x1b[?1000h\x1b[?1006h")

hub.set_session_provider(lambda: [page_other])
hub.set_active(True)
ev = make_wheel(cw * 4 + cw // 2, chh * 2 + chh // 2, angle_dy=120)
wmi.wheelEvent(ev)
check("колесо: байты в СВОЕЙ сессии", threadmi.sent == [b"\x1b[<64;5;3M"], repr(threadmi.sent))
check("колесо: НЕ broadcast'ится в другие сессии (координаты сессионно-локальны)",
      thread_other.sent == [], repr(thread_other.sent))
hub.reset()


# ════════════════════════════════════════════════════════════
# 9. terminal_thread=None + tracking — без исключений
# ════════════════════════════════════════════════════════════
print("== thread=None guard ==")

scrn = TerminalScreen(columns=40, lines=12)
wn = TerminalWidget(scrn, None)
scrn.feed(b"\x1b[?1003h")   # X10 tracking, потока нет
try:
    wn.wheelEvent(make_wheel(5, 5, angle_dy=120))
    ok = True
except Exception as e:  # noqa: BLE001
    ok = False
    print(f"  (исключение: {e!r})")
check("terminal_thread=None + tracking: колесо не роняет", ok)


# ════════════════════════════════════════════════════════════
# 10. Состояние релиза + i18n-паритет
# ════════════════════════════════════════════════════════════
print("== release state + i18n parity ==")

check_release_state(ROOT)
langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)

finish()
