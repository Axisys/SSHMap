# -*- coding: utf-8 -*-
"""v1.0RC2 — клавиатура + выделение/копирование (ROADMAP v1.0RC2).

  * selection_cells (чистая функция, без GUI): однострочное/многострочное/
    инвертированные границы/одна ячейка/вся сетка/зажим колонок; regression на
    ошибку черновика №4 (TERMINAL.md §3) — координаты ВСЕГДА (row, col),
    построчный порядок: колоночная интерпретация черновика ((col, row)) не даёт
    тот же набор ячеек;
  * клавиатура (offscreen-виджет + фейковый thread): полная таблица F1–F12
    (xterm-последовательности SS3/CSI), PageUp/PageDown, Home/End/Delete
    (семантика старого SSHTerminalTextEdit сохранена), базовый набор RC1
    (печатные/utf-8/Return/Backspace/Tab/Esc/стрелки); Ctrl+C без выделения →
    b'\\x03' (Acceptance: «Ctrl+C роняет top»); Ctrl+D → \\x04, Ctrl+Z → \\x1a;
    AltGr-guard (Ctrl+Alt зажат → ничего не шлётся — TERMINAL.md §3.12);
  * bracketed paste Ctrl+V (перенос из v0.9.4): многострочный буфер с
    смешанными EOL — ЕДИНЫЙ блок \\x1b[200~...\\x1b[201~ с нормализованными
    переводами строк; пустой буфер → ничего не шлётся;
  * выделение мышью + копирование (offscreen, синтетические QMouseEvent):
    drag ЛКМ в обе стороны, простой клик = сброс выделения, Ctrl+C при
    выделении → копирование мульти-строчного текста в буфер (Acceptance),
    без выделения → \\x03; drag за пределы сетки → clamp; полупрозрачная
    подсветка рендерится (пиксели + stats).

Запуск:  python tests/test_terminal_input.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from modules.terminal_screen import TerminalScreen
from modules.terminal_widget import TerminalWidget, selection_cells


# ════════════════════════════════════════════════════════════
# 1. selection_cells — чистая функция (regression на ошибку черновика №4)
# ════════════════════════════════════════════════════════════
print("== selection_cells (pure) ==")

check("однострочное: (2,1)-(2,5) → 5 ячеек",
      selection_cells((2, 1), (2, 5), 10) == [(2, c) for c in range(1, 6)],
      repr(selection_cells((2, 1), (2, 5), 10)))

exp_multi = ([(1, c) for c in range(3, 8)] +
             [(r, c) for r in (2, 3) for c in range(8)] +
             [(4, c) for c in range(0, 8)])
check("многострочное: (1,3)-(4,7) cols=8 — первая с col 3, средние всю ширину, последняя до col 7",
      selection_cells((1, 3), (4, 7), 8) == exp_multi,
      f"got={selection_cells((1, 3), (4, 7), 8)}")

check("инвертированные границы: (4,7)-(1,3) → тот же набор",
      selection_cells((4, 7), (1, 3), 8) == exp_multi,
      f"got={selection_cells((4, 7), (1, 3), 8)}")

check("одна ячейка: (0,0)-(0,0)", selection_cells((0, 0), (0, 0), 5) == [(0, 0)])

check("вся сетка 3x10 → 30 ячеек",
      len(selection_cells((0, 0), (2, 9), 10)) == 30
      and selection_cells((0, 0), (2, 9), 10)[-1] == (2, 9))

check("зажим колонок: c2=99 → cols-1",
      selection_cells((0, 0), (1, 99), 8) == [(r, c) for r in (0, 1) for c in range(8)],
      f"got={selection_cells((0, 0), (1, 99), 8)}")

# REGRESSION на ошибку №4 (TERMINAL.md §3): черновик хранил (col, row) и сравнивал
# кортежно — колоночный порядок. start=(0,5), end=(2,1), cols=8: построчно это
# строка 0 с col 5..7, строка 1 целиком, строка 2 до col 1 (13 ячеек).
cells4 = selection_cells((0, 5), (2, 1), 8)
exp4 = ([(0, c) for c in range(5, 8)] + [(1, c) for c in range(8)]
        + [(2, c) for c in range(2)])
check("regression №4: построчный порядок (row-major), а не колоночный",
      cells4 == exp4, f"got={cells4}")
check("regression №4: ячейки колоночной интерпретации черновика отсутствуют",
      (3, 0) not in cells4 and (0, 6) in cells4 and len(cells4) == 13, f"got={cells4}")

check("columns=0 → [] (defensive)", selection_cells((0, 0), (2, 5), 0) == [])


# ════════════════════════════════════════════════════════════
# 2. Клавиатура: полная таблица (offscreen + фейковый thread)
# ════════════════════════════════════════════════════════════
print("== keyboard (offscreen) ==")

sent = []


class FakeThread:
    def send_data(self, b):
        sent.append(b)

    def stop(self):
        pass


def make_widget(cols=20, lines=5, thread=None):
    scr = TerminalScreen(columns=cols, lines=lines)
    return scr, TerminalWidget(scr, thread if thread is not None else FakeThread())


def press_key(w, key, text="", mod=Qt.KeyboardModifier.NoModifier):
    w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, int(key), mod, text))


CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier

scr, w = make_widget()

# F1–F12 — полная таблица (xterm: F1–F4 SS3, F5–F12 CSI)
f_keys = [Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3, Qt.Key.Key_F4,
          Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7, Qt.Key.Key_F8,
          Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11, Qt.Key.Key_F12]
f_expect = [b"\x1bOP", b"\x1bOQ", b"\x1bOR", b"\x1bOS", b"\x1b[15~", b"\x1b[17~",
            b"\x1b[18~", b"\x1b[19~", b"\x1b[20~", b"\x1b[21~", b"\x1b[23~", b"\x1b[24~"]
for i, (k, e) in enumerate(zip(f_keys, f_expect), 1):
    sent.clear()
    press_key(w, k)
    check(f"F{i} → {e!r}", sent == [e], f"sent={sent!r}")

# PageUp/PageDown/Home/End/Delete (Home/End/Delete — семантика SSHTerminalTextEdit)
for label, k, e in (("PageUp", Qt.Key.Key_PageUp, b"\x1b[5~"),
                    ("PageDown", Qt.Key.Key_PageDown, b"\x1b[6~"),
                    ("Home", Qt.Key.Key_Home, b"\x1b[H"),
                    ("End", Qt.Key.Key_End, b"\x1b[F"),
                    ("Delete", Qt.Key.Key_Delete, b"\x1b[3~")):
    sent.clear()
    press_key(w, k)
    check(f"{label} → {e!r}", sent == [e], f"sent={sent!r}")

# Базовый набор (перенос из RC1): печатные/utf-8 и служебные
for ch in ("a", "é"):
    sent.clear()
    press_key(w, ord(ch), text=ch)
    check(f"печатный {ch!r} → utf-8", sent == [ch.encode("utf-8")], f"sent={sent!r}")

for label, k, e in (("Return", Qt.Key.Key_Return, b"\r"),
                    ("Enter", Qt.Key.Key_Enter, b"\r"),
                    ("Backspace", Qt.Key.Key_Backspace, b"\x7f"),
                    ("Tab", Qt.Key.Key_Tab, b"\t"),
                    ("Esc", Qt.Key.Key_Escape, b"\x1b"),
                    ("Left", Qt.Key.Key_Left, b"\x1b[D"),
                    ("Right", Qt.Key.Key_Right, b"\x1b[C"),
                    ("Up", Qt.Key.Key_Up, b"\x1b[A"),
                    ("Down", Qt.Key.Key_Down, b"\x1b[B")):
    sent.clear()
    press_key(w, k)
    check(f"{label} → {e!r}", sent == [e], f"sent={sent!r}")

# Ctrl+C БЕЗ выделения → SIGINT (Acceptance: «Ctrl+C роняет top»)
sent.clear()
press_key(w, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C без выделения → b'\\x03'", sent == [b"\x03"], f"sent={sent!r}")

# Ctrl+D / Ctrl+Z (явные, как в RC1)
for label, k, e in (("Ctrl+D", Qt.Key.Key_D, b"\x04"), ("Ctrl+Z", Qt.Key.Key_Z, b"\x1a")):
    sent.clear()
    press_key(w, k, mod=CTRL)
    check(f"{label} → {e!r}", sent == [e], f"sent={sent!r}")

# AltGr-guard (TERMINAL.md §3.12): на Windows AltGr = Ctrl+Alt — ничего не шлётся
for label, k in (("C", Qt.Key.Key_C), ("D", Qt.Key.Key_D), ("V", Qt.Key.Key_V),
                 ("Z", Qt.Key.Key_Z), ("2", Qt.Key.Key_2)):
    sent.clear()
    press_key(w, k, mod=CTRL | ALT)
    check(f"AltGr-guard: Ctrl+Alt+{label} → ничего не шлётся", sent == [], f"sent={sent!r}")

# terminal_thread=None — ввод отключён, без исключений
scr0, w0 = make_widget(thread=None)
try:
    press_key(w0, Qt.Key.Key_Return)
    press_key(w0, Qt.Key.Key_F1)
    press_key(w0, ord("x"), text="x")
    check("terminal_thread=None: клавиши не роняют и ничего не шлют", True)
except Exception as e:
    check("terminal_thread=None: клавиши не роняют и ничего не шлют", False, repr(e))


# ════════════════════════════════════════════════════════════
# 3. Bracketed paste Ctrl+V (перенос из v0.9.4)
# ════════════════════════════════════════════════════════════
print("== bracketed paste Ctrl+V ==")

scr, w = make_widget()
cb = app.clipboard()
cb.setText("one\r\ntwo\nthree")   # смешанные EOL — нормализуются в \n
sent.clear()
press_key(w, Qt.Key.Key_V, mod=CTRL)
check("Ctrl+V: многострочный буфер — ЕДИНЫЙ блок с нормализованными переводами",
      sent == [b"\x1b[200~one\ntwo\nthree\x1b[201~"], f"sent={sent!r}")

cb.setText("")
sent.clear()
press_key(w, Qt.Key.Key_V, mod=CTRL)
check("Ctrl+V с пустым буфером → ничего не шлётся", sent == [], f"sent={sent!r}")


# ════════════════════════════════════════════════════════════
# 4. Выделение мышью + копирование (синтетические QMouseEvent)
# ════════════════════════════════════════════════════════════
print("== mouse selection + copy ==")


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


scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
cw, chh = w.cell_size
w.resize(cw * 20, chh * 5)

# drag (0,0) → (2,4): строка 0 целиком, строка 1 целиком, строка 2 до col 4
press_lmb(w, 0, 0)
move_lmb(w, 1, 2)
release_lmb(w, 2, 4)
exp_sel = selection_cells((0, 0), (2, 4), 20)
check("drag (0,0)→(2,4): выделение активно", w.has_selection())
check("якорь/конец хранятся как (row, col)",
      (w._sel_anchor, w._sel_active) == ((0, 0), (2, 4)),
      f"got=({w._sel_anchor}, {w._sel_active})")
check("ячейки выделения = selection_cells()", w._selected_cells() == exp_sel,
      f"got={w._selected_cells()}")

# Acceptance: копирование мульти-строчного выделения
exp_text = "hello world\nsecond line\nthird"   # строка 2 cols 0..4 → 'third' (5 символов)
check("selected_text: мульти-строчный текст, \\n, хвостовые пробелы обрезаны",
      w.selected_text() == exp_text, repr(w.selected_text()))

sent.clear()
ok = w.copy_selection()
check("copy_selection() → True", ok is True)
check("буфер обмена == мульти-строчное выделение", app.clipboard().text() == exp_text,
      repr(app.clipboard().text()))

# Ctrl+C при выделении — копирует (semantics v0.9.3), в канал ничего не уходит
sent.clear()
press_key(w, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C при выделении → в канал ничего", sent == [], f"sent={sent!r}")
check("Ctrl+C при выделении → буфер обновлён", app.clipboard().text() == exp_text)

# Инвертированный drag (2,4) → (0,0): те же ячейки
w.clear_selection()
press_lmb(w, 2, 4)
move_lmb(w, 1, 0)
release_lmb(w, 0, 0)
check("инвертированный drag (2,4)→(0,0) → те же ячейки", w._selected_cells() == exp_sel,
      f"got={w._selected_cells()}")

# Простой клик (без drag) — сброс выделения; Ctrl+C снова SIGINT
w.clear_selection()
press_lmb(w, 1, 3)
release_lmb(w, 1, 3)
check("простой клик (без drag) → выделения нет", not w.has_selection())
sent.clear()
press_key(w, Qt.Key.Key_C, mod=CTRL)
check("Ctrl+C после простого клика → b'\\x03' (роняет top)", sent == [b"\x03"],
      f"sent={sent!r}")

# Drag за пределы сетки — clamp к последней ячейке (4,19)
w.clear_selection()
press_lmb(w, 0, 0)
far = QPointF(30 * cw, 30 * chh)   # далеко за границей виджета/сетки
w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, far, far, Qt.MouseButton.NoButton,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
check("drag за пределы сетки → clamp к (4,19)", w._sel_active == (4, 19),
      f"got={w._sel_active}")
w.clear_selection()


# ════════════════════════════════════════════════════════════
# 5. Подсветка выделения (offscreen-рендер)
# ════════════════════════════════════════════════════════════
print("== selection highlight (offscreen) ==")


def pixel(img, x, y):
    p = img.pixel(x, y)
    return ((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF)


scr2, w2 = make_widget(cols=20, lines=5)   # пустой экран — чистый фон
cw2, chh2 = w2.cell_size
w2.resize(cw2 * 20, chh2 * 5)
img_base = w2.grab().toImage()
px_base = pixel(img_base, 5 * cw2 + cw2 // 2, 2 * chh2 + chh2 // 2)

press_lmb(w2, 1, 0)
move_lmb(w2, 2, 5)
release_lmb(w2, 3, 9)   # (1,0)-(3,9): строка 1 всю ширину (20), строка 2 всю (20), строка 3 до col 9 (10)
img_sel = w2.grab().toImage()
px_sel = pixel(img_sel, 5 * cw2 + cw2 // 2, 2 * chh2 + chh2 // 2)
check("подсветка: выбранный пиксель отличается от фона", px_sel != px_base,
      f"base={px_base} sel={px_sel}")
r_, g_, b_ = px_sel
check("подсветка: синеватый оверлей (b > r и b > g на тёмном фоне)",
      b_ > r_ + 20 and b_ > g_ + 20, f"sel={px_sel}")
check("paint stats: подсчитаны ячейки выделения (20+20+10 = 50)",
      w2.last_paint_stats["selection_cells"] == 50, f"stats={w2.last_paint_stats}")


# ════════════════════════════════════════════════════════════
# 6. Интеграция: SSHTerminalWindow → TerminalWidget с API выделения
# ════════════════════════════════════════════════════════════
print("== SSHTerminalWindow integration ==")
import modules.ssh_terminal as ST
from models.server import ServerData


class _FakeTerm(ST.SSHTerminalThread):
    def __init__(self, *a, **k):
        super().__init__("127.0.0.1", "u", 9, "", "")

    def run(self):
        pass  # без сети


_orig_thread_cls = ST.SSHTerminalThread
ST.SSHTerminalThread = _FakeTerm
win = None
try:
    win = ST.SSHTerminalWindow(ServerData(id="rc2w", alias="T", host="127.0.0.1", user="u"), None)
    check("окно создаёт TerminalWidget с API выделения/копирования",
          isinstance(win.widget, TerminalWidget)
          and all(hasattr(win.widget, m) for m in
                  ("has_selection", "copy_selection", "selected_text",
                   "clear_selection", "_selected_cells")))
finally:
    ST.SSHTerminalThread = _orig_thread_cls
    if win is not None:
        try:
            win.close()
            app.processEvents()
        except Exception:
            pass

finish()
