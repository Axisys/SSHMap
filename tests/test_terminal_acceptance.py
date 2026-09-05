# -*- coding: utf-8 -*-
"""v1.0 — Терминал v1, финал: полный acceptance всех RC + конфиг terminal_* (ROADMAP задачи 9–10).

Один прогон БЕЗ сети покрывает Acceptance v1.0 на симулированном TUI-выводе:
  * bash — промпт + `ls --color` (SGR 34/93/256/truecolor) через окно терминала;
  * vim  — скрытие курсора ESC[?25l, полноэкранный перерисов с цветами
           (known limitation: в pyte 0.8.2 нет альтернативного экрана, режим 1049
           отсутствует — предыдущий экран НЕ восстанавливается, зафиксировано тестом);
  * htop — повторяющиеся полноэкранные фреймы + dirty-рендер без таймера;
  * копирование — выделение мышью → буфер обмена; Ctrl+C при выделении = копирование,
    без выделения = \\x03 (SIGINT, «роняет top»);
  * Ctrl+V — bracketed paste из буфера единым блоком.
Плюс задача 9: ключи terminal_palette / terminal_font / terminal_font_size /
terminal_history_lines из ~/.sshmap/config.json (все опциональны, дефолты = текущее
поведение) + v1.1.1: terminal_max_open (лимит своих терминалов) и состояние релиза —
_common.check_release_state() (пин EXPECTED_APP_VERSION — в tests/_common.py),
TerminalScreen.render() (HTML) остаётся deprecated (удаление не раньше v1.2),
i18n-паритет — _common.check_i18n_parity() (пин EXPECTED_I18N_KEYS; +33 ключа v1.1,
+14 в v1.1.1, +2 в v1.1.2RC2: msg.confirm_delete_profile и status.import_resolving;
в v1.1.2RC3 новых ключей нет — terminal_wheel только конфиг; +2 в v1.1.2 final:
settings.statuses.max_parallel и status.auto_interval_hint; +21 в v1.1.3: sftp.*).

Запуск: python tests/test_terminal_acceptance.py   (из корня проекта) или python tests/run_all.py
"""
import json
import os
import sys

from _common import bootstrap, check, finish, wait_until, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

from PySide6.QtCore import Qt, QThread, QPointF, QEvent, Signal as QtSignal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import modules.ssh_terminal as ST
import modules.terminal_screen as TS
from modules.terminal_screen import PALETTES
from modules.terminal_widget import TerminalWidget
from models.server import ServerData

D = PALETTES["default"]
NORD = PALETTES["nord"]


# ── обвязка: фейковый SSH-поток (тот же API, что у SSHTerminalThread) ─────────
class _FakeChannel:
    closed = False

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)


class _FakeSSHThread(QThread):
    output_signal = QtSignal(bytes)
    error_signal = QtSignal(str)
    status_signal = QtSignal(str)
    closed_signal = QtSignal()
    connected_signal = QtSignal()

    def __init__(self, host, user, port, password="", key_path=""):
        super().__init__()
        self.channel = _FakeChannel()
        self.running = True

    def run(self):  # реальный SSH не нужен
        pass

    def stop(self):
        self.running = False

    def send_data(self, data_bytes):  # тот же API, что у реального SSHTerminalThread
        if not data_bytes:
            return
        if self.channel and not self.channel.closed:
            self.channel.send(data_bytes)


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeSSHThread

_windows = []


def make_window(alias):
    """Окно терминала с фейковым потоком + синхронизация сетки с окном."""
    w = ST.SSHTerminalWindow(
        ServerData(id=f"acc-{alias}", alias=alias, host="10.99.0.1", user="root"),
        None, password="pw")
    _windows.append(w)
    # v1.1.3: окно ПОКАЗАНО (как в продакшене — MainWindow.show()). Без show()
    # offscreen-окно обрабатывает resize() отложенно: поздний _sync_grid →
    # tscreen.resize() случился бы уже после нарисованного контента и сдвинул
    # его за край видимой сетки (vim/1049). show() заставляет layout устаканиться
    # ДО любого вывода.
    w.show()
    w.resize(700, 500)   # resizeEvent → singleShot(0) → _sync_grid (guard по сетке)
    wait_until(lambda: (w._last_cols, w._last_rows) != (120, 32), timeout_ms=3000)
    app.processEvents()
    return w


def feed(win, data):
    """Симуляция вывода SSH-канала: через output_signal → _on_output (feed+update)."""
    win.terminal_thread.output_signal.emit(data)
    app.processEvents()


def emit_out(win, data, until_substr=None, timeout_ms=3000):
    feed(win, data)
    if until_substr is not None:
        wait_until(lambda: until_substr in win.widget.visible_text(), timeout_ms=timeout_ms)


# ── пиксельные проверки (паттерн tests/test_terminal_colors.py) ───────────────
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


def close_enough(rgb, ref, tol=32):
    return all(abs(a - b) <= tol for a, b in zip(rgb, ref))


def ink_count(img, cw, chh, x, y, ref_hex, tol=48):
    """Число пикселей ячейки (row=y, col=x), близких к ref (чернила/фон глифа)."""
    ref = hex_rgb(ref_hex)
    n = 0
    for yy in range(y * chh, (y + 1) * chh):
        for xx in range(x * cw, (x + 1) * cw):
            if close_enough(pixel(img, xx, yy), ref, tol):
                n += 1
    return n


def grab(win):
    w = win.widget
    cw, chh = w.cell_size
    img = w.grab().toImage()
    return img, cw, chh


# ── конфиг ~/.sshmap/config.json (HOME изолирован bootstrap'ом) ───────────────
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
# 0. Состояние релиза (пины — tests/_common.py: EXPECTED_APP_VERSION)
# ════════════════════════════════════════════════════════════
print("== release state ==")
check_release_state(ROOT)

_render_doc = (TS.TerminalScreen.render.__doc__ or "") if hasattr(TS.TerminalScreen, "render") else ""
check("TerminalScreen.render() (HTML) на месте и помечен DEPRECATED (удаление не раньше v1.2)",
      callable(getattr(TS.TerminalScreen, "render", None)) and "DEPRECATED" in _render_doc)

check_i18n_parity(load_i18n_langs(ROOT))

# ════════════════════════════════════════════════════════════
# 1. bash: промпт + ls --color (SGR 34/93/256/truecolor) через окно
# ════════════════════════════════════════════════════════════
print("== bash ==")

clear_config()
win = make_window("bash")
# Ввод — только \r\n (факт №10: LNM не включён, голый \n не возвращает каретку).
bash_out = (
    b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ls --color=auto\r\n"
    # row 1: docs(0–3, SGR 34) '  ' notes.txt(6–14, SGR 93) '  ' all.xml(17–23, 38;5;196)
    #        '  ' secret.key(26–35, 38;2;200;100;50)
    b"\x1b[0;34mdocs\x1b[0m  \x1b[93mnotes.txt\x1b[0m  \x1b[38;5;196mall.xml\x1b[0m"
    b"  \x1b[38;2;200;100;50msecret.key\x1b[0m\r\n"
    b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ "
)
emit_out(win, bash_out, until_substr="secret.key")

txt = win.widget.visible_text()
check("bash: промпт + вывод ls видны на холсте",
      all(s in txt for s in ("root@master", "ls --color=auto", "docs",
                             "notes.txt", "all.xml", "secret.key")), txt[:120])

img, cw, chh = grab(win)
check("bash: промпт — зелёные чернила (SGR 1;32)",
      ink_count(img, cw, chh, 0, 0, D["green"]) >= 5,
      f"ink={ink_count(img, cw, chh, 0, 0, D['green'])}")
check("bash: 'docs' — синие чернила (SGR 34)",
      ink_count(img, cw, chh, 0, 1, D["blue"]) >= 5,
      f"ink={ink_count(img, cw, chh, 0, 1, D['blue'])}")
check("bash: 'notes.txt' — bright-жёлтые чернила (SGR 93 → br_yellow)",
      ink_count(img, cw, chh, 6, 1, D["br_yellow"]) >= 5,
      f"ink={ink_count(img, cw, chh, 6, 1, D['br_yellow'])}")
check("bash: 'all.xml' — 256-цвет #ff0000 (38;5;196, hex-passthrough)",
      ink_count(img, cw, chh, 17, 1, "#ff0000") >= 5,
      f"ink={ink_count(img, cw, chh, 17, 1, '#ff0000')}")
check("bash: 'secret.key' — truecolor #c86432 (38;2;200;100;50)",
      ink_count(img, cw, chh, 26, 1, "#c86432", tol=24) >= 5,
      f"ink={ink_count(img, cw, chh, 26, 1, '#c86432', tol=24)}")
win.close()

# ════════════════════════════════════════════════════════════
# 2. vim: ESC[?25l + полноэкранный перерис; known limitation — нет режима 1049
# ════════════════════════════════════════════════════════════
print("== vim ==")

win = make_window("vim")
# Курсор в конце — на ПУСТОЙ строке 4: пиксельные проверки курсора должны идти по
# ячейке без глифов (в offscreen-окружении шрифт без глифов рисует «тофу» цветом
# default_fg, который совпадает с CURSOR_COLOR — на строках с текстом проверка
# была бы некорректной).
emit_out(win, b"\x1b[?25l\x1b[2J\x1b[H\x1b[41m vim session \x1b[0m\r\nvim content line\x1b[5H",
         until_substr="vim session")

rows, cx, cy, hidden = win.tscreen.snapshot()
check("vim: курсор скрыт (ESC[?25l)", hidden is True)
check("vim: курсор на пустой строке 4 (позиция для пиксельной проверки)",
      (cx, cy) == (0, 4), f"cursor=({cx},{cy})")

img, cw, chh = grab(win)
cur_ink = ink_count(img, cw, chh, cx, cy, TerminalWidget.CURSOR_COLOR, tol=16)
check("vim: блок-курсор НЕ рисуется, пока скрыт", cur_ink == 0, f"ink={cur_ink}")
red_bg = ink_count(img, cw, chh, 5, 0, D["red"], tol=32)
check("vim: SGR 41 — красный фон строки ' vim session '", red_bg >= 10, f"ink={red_bg}")

emit_out(win, b"\x1b[?25h")
rows, cx, cy, hidden = win.tscreen.snapshot()
check("vim: курсор снова виден (ESC[?25h)", hidden is False)
img, cw, chh = grab(win)
p = pixel(img, cx * cw + cw // 2, cy * chh + chh // 2)
check("vim: блок-курсор нарисован в позиции курсора",
      close_enough(p, hex_rgb(TerminalWidget.CURSOR_COLOR), tol=16), f"got={p}")

# known limitation (ROADMAP): pyte 0.8.2 не реализует альтернативный экран —
# ?1049h/?1049l игнорируются, «выход из vim» предыдущий экран НЕ восстанавливает.
emit_out(win, b"\x1b[?1049h\x1b[?1049l")
check("known limitation: режима 1049 нет — экран после 'vim' не восстанавливается",
      "vim session" in win.widget.visible_text())
win.close()

# ════════════════════════════════════════════════════════════
# 3. htop: повторяющиеся полноэкранные фреймы + dirty-рендер без таймера
# ════════════════════════════════════════════════════════════
print("== htop ==")

win = make_window("htop")


def _htop_frame(i):
    return (b"\x1b[2J\x1b[H\x1b[1mTASKS: 3\x1b[0m  \x1b[38;5;45mLOAD AVG: " + str(i).encode()
            + b"\x1b[0m\r\n\x1b[46m CPU bar " + b"#" * i + b" \x1b[0m\r\n\x1b[?25l")


for i in (1, 2, 3):
    emit_out(win, _htop_frame(i))

txt = win.widget.visible_text()
check("htop: отрендерился ПОСЛЕДНИЙ фрейм", "LOAD AVG: 3" in txt and "CPU bar ###" in txt,
      txt[:80])
check("htop: старые фреймы заменены (ESC[2J)", "LOAD AVG: 1" not in txt)

rows, cx, cy, hidden = win.tscreen.snapshot()
check("htop: курсор скрыт во время работы TUI", hidden is True)

img, cw, chh = grab(win)
cyan_bg = ink_count(img, cw, chh, 0, 1, D["cyan"], tol=32)
check("htop: SGR 46 — голубой фон полосы CPU", cyan_bg >= 10, f"ink={cyan_bg}")

check("dirty-рендер: 33 мс таймер удалён (нет _render_timer/_dirty)",
      not hasattr(win, "_render_timer") and not hasattr(win, "_dirty"))
check("dirty-рендер: paintEvent прошёл по выводу (last_paint_stats.rows > 0)",
      win.widget.last_paint_stats["rows"] > 0, str(win.widget.last_paint_stats))
win.close()

# ════════════════════════════════════════════════════════════
# 4. Копирование: выделение мышью + Ctrl+C (копирование/SIGINT) + Ctrl+V (bracketed paste)
# ════════════════════════════════════════════════════════════
print("== copy / Ctrl+C / Ctrl+V ==")

CTRL = Qt.KeyboardModifier.ControlModifier


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


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


win = make_window("copy")
emit_out(win, b"alpha beta gamma\r\ndelta epsilon zeta\r\neta theta iota kappa",
         until_substr="kappa")

# drag (0,0) → (1,4): строка 0 целиком + строка 1 с col 0 по col 4 ВКЛЮЧИТЕЛЬНО
w = win.widget
press_lmb(w, 0, 0)
move_lmb(w, 1, 2)
release_lmb(w, 1, 4)
check("копирование: выделение мышью активно", w.has_selection())
exp_sel = "alpha beta gamma\ndelta"
check("копирование: selected_text() — мульти-строчный текст (row-major)",
      w.selected_text() == exp_sel, repr(w.selected_text()))

sent_before = len(win.terminal_thread.channel.sent)
w.copy_selection()
cb = app.clipboard()
check("копирование: буфер обмена == выделению", cb.text() == exp_sel, repr(cb.text()))

press_key(w, Qt.Key.Key_C, mod=CTRL)  # Ctrl+C ПРИ выделении → копирование, не SIGINT
check("Ctrl+C при выделении: в канал ничего не уходит (копирование, а не \\x03)",
      len(win.terminal_thread.channel.sent) == sent_before,
      repr(win.terminal_thread.channel.sent[sent_before:]))
check("Ctrl+C при выделении: буфер обновлён", cb.text() == exp_sel)

w.clear_selection()
press_key(w, Qt.Key.Key_C, mod=CTRL)  # Ctrl+C БЕЗ выделения → SIGINT («роняет top»)
check("Ctrl+C без выделения → b'\\x03' (SIGINT)",
      win.terminal_thread.channel.sent[-1] == b"\x03",
      repr(win.terminal_thread.channel.sent[-1]))

cb.setText("restart\nservice nginx")  # Ctrl+V — bracketed paste единым блоком
press_key(w, Qt.Key.Key_V, mod=CTRL)
check("Ctrl+V: буфер уходит ЕДИНЫМ bracketed-блоком (\\x1b[200~…\\x1b[201~)",
      win.terminal_thread.channel.sent[-1] == b"\x1b[200~restart\nservice nginx\x1b[201~",
      repr(win.terminal_thread.channel.sent[-1]))
cb.setText("")
win.close()

# ════════════════════════════════════════════════════════════
# 5. Задача 9: ключи terminal_* из ~/.sshmap/config.json
# ════════════════════════════════════════════════════════════
print("== config: terminal_* keys ==")

from modules.ssh_terminal import load_terminal_settings

# v1.1: load_terminal_settings() дополнительно возвращает close_behavior
# ("close" по умолчанию; "ask" — подтверждение закрытия активной сессии);
# v1.1.1: + max_open (лимит своих терминалов, дефолт 4);
# v1.2.2: + mode (режим отображения: "windows" дефолт | "tabs" — док на карте).
clear_config()
s = load_terminal_settings()
check("нет конфига → дефолты (палитра default, pt 10, история 1000 — скроллбэк включён, close_behavior=close, max_open=4, wheel=scrollback, mode=windows)",
      s == {"palette": None, "font_family": "", "font_size": None,
            "history_lines": TS.DEFAULT_HISTORY_LINES, "close_behavior": "close",
            "max_open": 4, "wheel": "scrollback", "mode": "windows"}, str(s))

write_config({"terminal_palette": " nord ", "terminal_font": " Consolas ",
              "terminal_font_size": 12, "terminal_history_lines": 50})
s = load_terminal_settings()
check("валидные значения читаются (trim пробелов)",
      s == {"palette": "nord", "font_family": "Consolas", "font_size": 12,
            "history_lines": 50, "close_behavior": "close", "max_open": 4,
            "wheel": "scrollback", "mode": "windows"}, str(s))

write_config({"terminal_palette": 42, "terminal_font": 7,
              "terminal_font_size": "big", "terminal_history_lines": -5})
s = load_terminal_settings()
check("битые значения (чужие типы/вне диапазона) → дефолты",
      s == {"palette": None, "font_family": "", "font_size": None,
            "history_lines": TS.DEFAULT_HISTORY_LINES, "close_behavior": "close",
            "max_open": 4, "wheel": "scrollback", "mode": "windows"}, str(s))

# v1.1.1: terminal_max_open — лимит своих терминалов (дефолт 4, диапазон 1..32)
write_config({"terminal_max_open": 8})
check("v1.1.1: terminal_max_open=8 читается", load_terminal_settings()["max_open"] == 8)
write_config({"terminal_max_open": "many"})
check("v1.1.1: битое terminal_max_open (str) → дефолт 4",
      load_terminal_settings()["max_open"] == 4)
write_config({"terminal_max_open": 99})
check("v1.1.1: terminal_max_open вне диапазона (99) → дефолт 4",
      load_terminal_settings()["max_open"] == 4)

# v1.2.2: terminal_mode — режим отображения ("windows" дефолт | "tabs" — док на карте);
# валидация по паттерну остальных ключей (битое значение/чужой тип → дефолт)
write_config({"terminal_mode": "tabs"})
check("v1.2.2: terminal_mode='tabs' читается", load_terminal_settings()["mode"] == "tabs")
write_config({"terminal_mode": " TABS "})
check("v1.2.2: terminal_mode ' TABS ' (strip+lower) → 'tabs'",
      load_terminal_settings()["mode"] == "tabs")
write_config({"terminal_mode": 123})
check("v1.2.2: битый terminal_mode (int) → дефолт 'windows'",
      load_terminal_settings()["mode"] == "windows")

write_config({"terminal_close_behavior": " ask "})
check("v1.1: terminal_close_behavior='ask' читается (trim пробелов)",
      load_terminal_settings()["close_behavior"] == "ask")

write_config({"terminal_close_behavior": "yell"})
check("v1.1: битое terminal_close_behavior → дефолт 'close'",
      load_terminal_settings()["close_behavior"] == "close")

write_config({"terminal_history_lines": 0})
check("явный terminal_history_lines=0 — отключение скроллбэка (сознательный выбор)",
      load_terminal_settings()["history_lines"] == 0)

# v1.1.2RC3 (U3 остаток): terminal_wheel — "scrollback" (дефолт) | "off";
# полный SGR-passthrough колеса в TUI отложен на v1.2+ (pyte не трекает DECSET
# 1000/1002/1006). Ключ только конфиг — без UI в диалоге настроек.
write_config({"terminal_wheel": "off"})
check("v1.1.2RC3: terminal_wheel='off' читается", load_terminal_settings()["wheel"] == "off")
write_config({"terminal_wheel": "bogus"})
check("v1.1.2RC3: битое terminal_wheel → дефолт 'scrollback'",
      load_terminal_settings()["wheel"] == "scrollback")

# Окно с полным конфигом: палитра nord + Consolas 12 + глубина истории 50
write_config({"terminal_palette": "nord", "terminal_font": "Consolas",
              "terminal_font_size": 12, "terminal_history_lines": 50})
win = make_window("cfg")
check("конфиг: палитра nord применена к холсту", win.widget._palette_name == "nord",
      win.widget._palette_name)
check("конфиг: _bg_color = default_bg палитры nord",
      win.widget._bg_color.name().lower() == NORD["default_bg"],
      win.widget._bg_color.name())
img, cw, chh = grab(win)
# Пиксель — по ПОЛНОСТЬЮ пустой строке 15 (строка 0 занята блок-курсором в (0,0),
# строки с текстом в offscreen рисуют «тофу» — фон между глифами не детерминирован).
bg = pixel(img, cw // 2, 15 * chh + chh // 2)
check("конфиг: фон экрана на холсте = default_bg палитры nord (#2e3440)",
      close_enough(bg, hex_rgb(NORD["default_bg"]), tol=8), f"got={bg}")
check("конфиг: шрифт Consolas 12 применён",
      win.widget._font.family() == "Consolas" and win.widget._font.pointSize() == 12,
      f"{win.widget._font.family()} pt{win.widget._font.pointSize()}")
for _ in range(200):
    win.tscreen.feed(b"x\r\n")
pos, size = win.tscreen.scroll_info()
check("конфиг: глубина истории 50 (deque-лимит terminal_history_lines)",
      size == 50 and pos == 50, f"pos={pos} size={size}")
win.close()

# Неизвестная палитра → тихо остаётся "default" (set_palette() False)
write_config({"terminal_palette": "neon"})
win = make_window("cfgbad")
check("конфиг: неизвестная палитра → 'default' (без ошибки)",
      win.widget._palette_name == "default", win.widget._palette_name)
img, cw, chh = grab(win)
bg = pixel(img, cw // 2, 15 * chh + chh // 2)   # пустая строка — чистый фон
check("конфиг: фон остался default-палитрой (#0f172a)",
      close_enough(bg, hex_rgb(D["default_bg"]), tol=8), f"got={bg}")
win.close()

# Битые значения в окне → дефолты (pt 10, история 1000)
write_config({"terminal_palette": 42, "terminal_font_size": "big",
              "terminal_history_lines": -5})
win = make_window("cfgbad2")
check("конфиг: битые значения → шрифт pt 10 (дефолт)",
      win.widget._font.pointSize() == 10, f"pt{win.widget._font.pointSize()}")
for _ in range(1200):
    win.tscreen.feed(b"x\r\n")
pos, size = win.tscreen.scroll_info()
check("конфиг: битое terminal_history_lines → дефолт 1000 (скроллбэк включён)",
      size == TS.DEFAULT_HISTORY_LINES and pos == size, f"pos={pos} size={size}")
win.close()

# Конфига нет вовсе → поведение ПОСЛЕ RC3: HistoryScreen со встроенной глубиной
clear_config()
win = make_window("cfgnone")
for _ in range(1200):
    win.tscreen.feed(b"x\r\n")
pos, size = win.tscreen.scroll_info()
check("конфиг отсутствует → дефолт: скроллбэк включён, глубина 1000 (поведение RC3)",
      size == TS.DEFAULT_HISTORY_LINES and pos == size, f"pos={pos} size={size}")
win.close()

# ════════════════════════════════════════════════════════════
# Cleanup
# ════════════════════════════════════════════════════════════
ST.SSHTerminalThread = _orig_thread_cls
clear_config()
for w in _windows:
    try:
        w.close()
    except Exception:
        pass

finish()
