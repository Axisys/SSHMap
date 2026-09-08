# -*- coding: utf-8 -*-
"""v1.2.7 — Терминал: выделение двойным/тройным кликом + контекстное меню (ROADMAP v1.2.7).

  * word_units() (чистая функция, без GUI): слово = максимальный прогон небелых
    ячеек; пунктуация принадлежит слову ("foo,bar" — одно); заглушка широкого
    CJK-глифа (data=='') принадлежит слову ("a中b" — одно слово на 4 ячейках);
    пробелы/пустая строка → [];
  * двойной клик — выделение СЛОВА (offscreen, синтетические QMouseEvent;
    click-count считает сам виджет: QMouseEvent в PySide6 его не несёт):
    границы слова + selected_text(); клик по пробелу — бездействия; интервал
    больше DOUBLE_CLICK_MS → счётчик сбросился, простой клик сбрасывает выделение;
  * тройной клик — вся СТРОКА (0..columns-1);
  * drag после двойного клика — расширение от ДАЛЬНОГО конца слова (фиксатор
    _click_sel_end), отпускание при count>=2 НЕ затирает выделение;
  * контекстное меню ПКМ (_build_context_menu — тестовый шов, без menu.exec()):
    состав/порядок [Копировать | Вставить | Выделить всё], Копировать enabled
    только при выделении → буфер обмена, Вставить → bracketed-paste-блок в PTY
    (тот же путь, что Ctrl+V; пустой буфер → ничего; thread=None → disabled),
    Выделить всё → вся сетка; ПКМ не сбрасывает выделение; НАСТОЯЩИЙ путь ПКМ
    (contextMenuEvent с реальным QContextMenuEvent → menu.exec в глобальных
    координатах — регрессия v1.2.7-fix: globalPos() уже QPoint, .toPoint() ронял);
    подписи en/ru/zh;
  * i18n: +3 ключа terminal.menu.* × en/ru/zh, паритет 422 → 425, состояние релиза.

Acceptance ROADMAP v1.2.7: двойной клик выделяет слово, тройной — строку,
действия меню работают (копирование с выделением → буфер обмена, вставка → байты
в PTY); полный прогон сьюта exit 0.

Запуск:  python tests/test_terminal_selection_menu.py   (из корня проекта) или python tests/run_all.py
"""
import sys
import time

from _common import (bootstrap, check, finish, load_i18n_langs,
                     check_i18n_parity, check_release_state)

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from PySide6.QtCore import Qt, QEvent, QPointF, QPoint
from PySide6.QtGui import QMouseEvent, QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)

from modules.terminal_screen import TerminalScreen
import modules.terminal_widget as _tw
from modules.terminal_widget import TerminalWidget, selection_cells, word_units


sent = []


class FakeThread:
    def send_data(self, b):
        sent.append(b)

    def stop(self):
        pass


_NO_THREAD = object()   # сентинел: явный thread=None ≠ «не передан» (FakeThread по умолчанию)


def make_widget(cols=20, lines=5, thread=_NO_THREAD):
    scr = TerminalScreen(columns=cols, lines=lines)
    if thread is _NO_THREAD:
        thread = FakeThread()
    return scr, TerminalWidget(scr, thread)


# ── мышь: синтетические QMouseEvent (паттерн test_terminal_input.py) ──────────

def lmb_press(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                  Qt.KeyboardModifier.NoModifier))


def lmb_release(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))


def lmb_move(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
                                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier))


def rmb_press(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                  Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
                                  Qt.KeyboardModifier.NoModifier))


def rmb_release(w, r, c):
    cw_, ch_ = w.cell_size
    x, y = c * cw_ + cw_ // 2, r * ch_ + ch_ // 2
    w.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                    Qt.MouseButton.RightButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))


def double_click(w, r, c):
    """press/release + press/release в одной ячейке (внутри DOUBLE_CLICK_MS)."""
    lmb_press(w, r, c)
    lmb_release(w, r, c)
    lmb_press(w, r, c)
    lmb_release(w, r, c)


def triple_click(w, r, c):
    double_click(w, r, c)
    lmb_press(w, r, c)
    lmb_release(w, r, c)


# ════════════════════════════════════════════════════════════
# 1. word_units — чистая функция (без GUI)
# ════════════════════════════════════════════════════════════
print("== word_units (pure) ==")


def row_of(text, cols=20):
    """Строка pyte Char из текста (через реальный TerminalScreen — E2E-путь)."""
    scr = TerminalScreen(columns=cols, lines=2)
    scr.feed(text.encode("utf-8") + b"\r\n")
    rows, _cx, _cy, _hidden = scr.snapshot()
    return rows[0]


check("«hello world» → [(0,4),(6,10)]", word_units(row_of("hello world")) == [(0, 4), (6, 10)],
      repr(word_units(row_of("hello world"))))
check("пробелы по краям/подряд: «  ab  cd  » → [(2,3),(6,7)]",
      word_units(row_of("  ab  cd  ")) == [(2, 3), (6, 7)],
      repr(word_units(row_of("  ab  cd  "))))
check("пунктуация в слове: «foo,bar» → одно слово [(0,6)]",
      word_units(row_of("foo,bar")) == [(0, 6)], repr(word_units(row_of("foo,bar"))))
check("пустая строка → []", word_units(row_of("")) == [])
check("только пробелы → []", word_units(row_of("   ")) == [])
# CJK: широкий глиф = ячейка + заглушка (data=='') — заглушка ПРИНАДЛЕЖИТ слову
cjk_row = row_of("a中b")
check("CJK «a中b»: 4 ячейки (глиф+заглушка), одно слово [(0,3)]",
      [ch.data for ch in cjk_row[:4]] == ["a", "中", "", "b"] and word_units(cjk_row) == [(0, 3)],
      f"row={[ch.data for ch in cjk_row[:6]]} units={word_units(cjk_row)}")
check("CJK между словами: «x a中b y» → [(0,0),(2,5),(7,7)]",
      word_units(row_of("x a中b y")) == [(0, 0), (2, 5), (7, 7)],
      repr(word_units(row_of("x a中b y"))))

# ════════════════════════════════════════════════════════════
# 2. Двойной клик — выделение слова (offscreen)
# ════════════════════════════════════════════════════════════
print("== double-click → word ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
cw, chh = w.cell_size
w.resize(cw * 20, chh * 5)

# Первый (простой) клик — выделения нет; второй в интервале — слово
lmb_press(w, 0, 7)      # count=1
lmb_release(w, 0, 7)    # простой клик (press/release в одной ячейке) → сброс
check("простой клик → выделения нет", not w.has_selection())
lmb_press(w, 0, 7)      # count=2 (та же ячейка, внутри DOUBLE_CLICK_MS) → _select_word
check("двойной клик (press): выделение активно", w.has_selection())
check("клик-счётчик == 2", w._click_count == 2, f"count={w._click_count}")
check("границы слова «world» = (0,6)-(0,10)",
      (w._sel_anchor, w._sel_active) == ((0, 6), (0, 10)),
      f"got=({w._sel_anchor}, {w._sel_active})")
check("selected_text() == «world»", w.selected_text() == "world", repr(w.selected_text()))
lmb_release(w, 0, 7)    # отпускание при count>=2 НЕ затирает выделение
check("отпускание после двойного клика → выделение живёт",
      (w._sel_anchor, w._sel_active) == ((0, 6), (0, 10)) and w.has_selection(),
      f"got=({w._sel_anchor}, {w._sel_active})")

# Двойной клик по пробелу — бездействия (выделение не меняется/не создаётся)
w.clear_selection()
double_click(w, 0, 15)
check("двойной клик по пробелу → бездействия", not w.has_selection())

# Интервал больше DOUBLE_CLICK_MS → счётчик сбросился: «двойной» = два простых клика
w.clear_selection()
lmb_press(w, 0, 7)
lmb_release(w, 0, 7)
w._last_click_ms = time.monotonic() * 1000.0 - 2000.0   # симуляция паузы (мс; тест-хук)
lmb_press(w, 0, 7)
check("пауза > DOUBLE_CLICK_MS → count сбросился на 1", w._click_count == 1,
      f"count={w._click_count}")
lmb_release(w, 0, 7)
check("простой клик после паузы → сброс выделения", not w.has_selection())

# ════════════════════════════════════════════════════════════
# 3. Тройной клик — выделение строки (offscreen)
# ════════════════════════════════════════════════════════════
print("== triple-click → line ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
w.resize(cw * 20, chh * 5)

triple_click(w, 1, 2)
check("тройной клик: выделение активно", w.has_selection())
check("границы строки = (1,0)-(1,19)",
      (w._sel_anchor, w._sel_active) == ((1, 0), (1, 19)),
      f"got=({w._sel_anchor}, {w._sel_active})")
check("selected_text() == «second line» (хвостовые пробелы обрезаны)",
      w.selected_text() == "second line", repr(w.selected_text()))

# Тройной клик на последней строке — clamp строк не нужен, но границы сетки точные
triple_click(w, 4, 19)
check("тройной клик на пустой строке 4 → (4,0)-(4,19), текст «»",
      (w._sel_anchor, w._sel_active) == ((4, 0), (4, 19)) and w.selected_text() == "",
      f"got=({w._sel_anchor}, {w._sel_active}) text={w.selected_text()!r}")

# ════════════════════════════════════════════════════════════
# 4. Drag после двойного клика — от дальнего конца слова (offscreen)
# ════════════════════════════════════════════════════════════
print("== drag after double-click ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
w.resize(cw * 20, chh * 5)

lmb_press(w, 0, 7)
lmb_release(w, 0, 7)
lmb_press(w, 0, 7)      # count=2: слово (0,6)-(0,10); клик у левого края → фиксатор правый конец
check("фиксатор drag'а = дальний (правый) конец слова", w._click_sel_end == (0, 10),
      f"got={w._click_sel_end}")
lmb_move(w, 2, 3)        # drag вниз-влево: якорь = фиксатор, конец = (2,3)
check("drag: якорь переехал в фиксатор", w._sel_anchor == (0, 10), f"got={w._sel_anchor}")
lmb_release(w, 2, 3)
exp = selection_cells((0, 10), (2, 3), 20)
check("drag после двойного клика → ячейки selection_cells((0,10),(2,3))",
      w._selected_cells() == exp and w.has_selection(), f"got={w._selected_cells()}")

# Клик у правого края слова → фиксатор левый конец
w.clear_selection()
lmb_press(w, 0, 9)
lmb_release(w, 0, 9)
lmb_press(w, 0, 9)      # «world»: col=9, start=6, end=10 → 9-6=3 > 10-9=1 → фиксатор (0,6)
check("клик у правого края → фиксатор левый конец слова", w._click_sel_end == (0, 6),
      f"got={w._click_sel_end}")
lmb_release(w, 0, 9)

# ════════════════════════════════════════════════════════════
# 5. Контекстное меню ПКМ (тестовый шов _build_context_menu)
# ════════════════════════════════════════════════════════════
print("== context menu (RMB) ==")

scr, w = make_widget(cols=20, lines=5)
scr.feed(b"hello world\r\nsecond line\r\nthird row")
w.resize(cw * 20, chh * 5)
cb = app.clipboard()

# Состав и порядок: [Копировать | Вставить | Выделить всё] (en — дефолт)
menu = w._build_context_menu()
check("меню — QMenu с 3 пунктами", isinstance(menu, QMenu) and len(menu.actions()) == 3,
      f"actions={len(menu.actions())}")
texts = [a.text() for a in menu.actions()]
check("порядок/подписи en: Copy | Paste | Select All",
      texts == ["Copy", "Paste", "Select All"], repr(texts))

# Копировать — disabled БЕЗ выделения
act_copy, act_paste, act_all = menu.actions()
check("Копировать без выделения → disabled", not act_copy.isEnabled())

# Выделение словом → enabled; триггер → буфер обмена (Acceptance)
double_click(w, 0, 7)
menu = w._build_context_menu()
act_copy = menu.actions()[0]
check("Копировать при выделении → enabled", act_copy.isEnabled())
cb.setText("")
sent.clear()
act_copy.trigger()
check("триггер Копировать → буфер == «world»", cb.text() == "world", repr(cb.text()))
check("триггер Копировать → в PTY ничего не ушло", sent == [], f"sent={sent!r}")

# ПКМ не сбрасывает выделение (press/release RightButton — мимо логики ЛКМ)
rmb_press(w, 0, 7)
rmb_release(w, 0, 7)
check("ПКМ → выделение не сброшено", w.has_selection() and w.selected_text() == "world")

# v1.2.7-fix (регрессия ручного тестирования): НАСТОЯЩИЙ путь ПКМ — contextMenuEvent
# с реальным QContextMenuEvent обязан вызвать menu.exec() в глобальных координатах.
# Раньше .toPoint() на QPoint (globalPos() у QContextMenuEvent уже возвращает QPoint,
# а не QPointF) бросал AttributeError, который except глотал молча → «ПКМ ничего не
# делает». Spy через модульный глобал _tw.QMenu: присваивание класс-атрибута
# QMenu.exec = f в PySide6 6.11 — тихий no-op (проверено), а _build_context_menu
# берёт QMenu из глобала своего модуля.
_ctx_exec_calls = []


class _SpyCtxMenu(QMenu):
    def exec(self, pos=None):  # noqa: A003 — сигнатура QMenu.exec
        _ctx_exec_calls.append(pos)
        return 0


_saved_qmenu = _tw.QMenu
_tw.QMenu = _SpyCtxMenu
try:
    w.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                         QPoint(12, 34), QPoint(567, 89)))
finally:
    _tw.QMenu = _saved_qmenu
check("настоящий путь ПКМ: contextMenuEvent → menu.exec вызван (регрессия v1.2.7-fix)",
      len(_ctx_exec_calls) == 1, f"calls={_ctx_exec_calls!r}")
check("настоящий путь ПКМ: exec получил глобальные координаты события",
      bool(_ctx_exec_calls) and _ctx_exec_calls[0] == QPoint(567, 89),
      f"got={_ctx_exec_calls!r}")

# Вставить в PTY — bracketed-paste-блок (тот же путь, что Ctrl+V; Acceptance: байты в PTY)
cb.setText("ls -la\r\npwd")
sent.clear()
menu = w._build_context_menu()
act_paste = menu.actions()[1]
check("Вставить при живом потоке → enabled", act_paste.isEnabled())
act_paste.trigger()
check("триггер Вставить → ровно \\x1b[200~ls -la\\npwd\\x1b[201~ в PTY",
      sent == [b"\x1b[200~ls -la\npwd\x1b[201~"], f"sent={sent!r}")

cb.setText("")
sent.clear()
w._build_context_menu().actions()[1].trigger()
check("Вставить с пустым буфером → ничего не шлётся", sent == [], f"sent={sent!r}")

# Выделить всё — вся видимая сетка (Acceptance)
w.clear_selection()
menu = w._build_context_menu()
act_all = menu.actions()[2]
check("Выделить всё всегда enabled", act_all.isEnabled())
act_all.trigger()
check("select_all: границы (0,0)-(4,19)",
      (w._sel_anchor, w._sel_active) == ((0, 0), (4, 19)),
      f"got=({w._sel_anchor}, {w._sel_active})")
# Пустые строки 3–4 входят в прямоугольник → две пустые строки хвостом (semantics drag'а)
check("selected_text() = все строки, \\n, хвосты обрезаны",
      w.selected_text() == "hello world\nsecond line\nthird row\n\n", repr(w.selected_text()))

# thread=None: Вставить disabled (ввод отключён), Копировать/Выделить всё работают
scr0, w0 = make_widget(thread=None)
menu0 = w0._build_context_menu()
check("thread=None: Вставить → disabled", not menu0.actions()[1].isEnabled())
check("thread=None: Выделить всё → enabled", menu0.actions()[2].isEnabled())
menu0.actions()[2].trigger()
check("thread=None: select_all работает локально",
      (w0._sel_anchor, w0._sel_active) == ((0, 0), (4, 19)),
      f"got=({w0._sel_anchor}, {w0._sel_active})")

# Подписи меню на ru/zh (i18n terminal.menu.*)
import i18n as _i18n
saved_lang = _i18n.get_current_language()
try:
    _i18n.set_language("ru")
    texts_ru = [a.text() for a in w._build_context_menu().actions()]
    check("подписи ru: Копировать | Вставить | Выделить всё",
          texts_ru == ["Копировать", "Вставить", "Выделить всё"], repr(texts_ru))
    _i18n.set_language("zh")
    texts_zh = [a.text() for a in w._build_context_menu().actions()]
    check("подписи zh: 复制 | 粘贴 | 全选",
          texts_zh == ["复制", "粘贴", "全选"], repr(texts_zh))
finally:
    _i18n.set_language(saved_lang)

# ════════════════════════════════════════════════════════════
# 6. i18n-паритет + состояние релиза
# ════════════════════════════════════════════════════════════
print("== i18n parity + release state ==")

langs = load_i18n_langs(ROOT)
check_i18n_parity(langs)
for code in ("en", "ru", "zh"):
    for key in ("terminal.menu.copy", "terminal.menu.paste", "terminal.menu.select_all"):
        check(f"i18n {code}: {key} не пуст", bool(langs[code].get(key)),
              repr(langs[code].get(key)))
check_release_state(ROOT)

finish()
