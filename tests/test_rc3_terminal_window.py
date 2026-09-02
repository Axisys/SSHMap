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

Секции 2–3 (N7 сброс выделения при авто-возврате к live, U2 сохранение размеров)
добавятся по мере реализации RC3.

Запуск:  python tests/test_rc3_terminal_window.py   (из корня проекта) или python tests/run_all.py
"""
import sys
import threading
import time

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget


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

finish()
