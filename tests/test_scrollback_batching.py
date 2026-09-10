# -*- coding: utf-8 -*-
"""v1.2.14 — Скроллбэк: батчинг авто-возврата к live-строке (PYTE82_AUDIT.md пачка D2).

Тематический тест темы релиза (ROADMAP v1.2.14): pyte.HistoryScreen.before_event
для каждого события SSH-потока кроме prev_page/next_page крутил next_page() в цикле —
при глубокой истории до ~250 итераций, каждая O(lines) (замер D1 v1.2.12: 68–73 мс/чанк
против ~42 на live-строке; feed идёт через queued signal в GUI-потоке). Теперь — одна
bulk-операция с той же арифметикой, что в next_page (screens.py): O(lines) один раз.

Headless: синтетические последовательности байтов + реальный htop-чанк (19 КБ) в
TerminalScreen (без Qt, без сети). Функциональные ассерты; время — только в отчёте
замера, БЕЗ жёстких ms-ассертов (ROADMAP v1.2.14):

  * wiring: override before_event существует и подхватывается обёрткой по имени
    (before_event не входит в HistoryScreen._wrapped);
  * базовый авто-возврат (k ≤ lines): страница вверх → событие → position == size;
  * глубокая история + чанк (D1-сценарий): 120×32, history=1000, ~1050 строк,
    пользователь у верхней границы (position=32/1000) → подача htop-чанка — позиция
    вернулась к size, bottom пуст, сетка посимвольно равна референсу без прокрутки
    (включая fg/bg и курсор); время чанка — в отчёте;
  * эквивалентность циклу next_page(): несколько геометрий (k ≤ lines И k >> lines) —
    полное состояние (position, top, bottom, buffer посимвольно, курсор) идентично
    штатному циклу pyte;
  * prev_page/next_page — no-op: ручная прокрутка колесом/PgUp-PgDn пошагово,
    авто-возвратом не сбрасывается;
  * границы: событие на live-строке (no-op), пустая история, history_lines=0,
    два чанка подряд, вход в alt из глубокой истории (регрессия v1.2.12).

Запуск: python tests/test_scrollback_batching.py   (из корня проекта) или python tests/run_all.py
"""
import math
import sys
import time

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

import pyte  # noqa: E402

import modules.terminal_screen as TS  # noqa: E402
from modules.terminal_screen import SshmapHistoryScreen, TerminalScreen  # noqa: E402
from _bench_history import load_chunk  # noqa: E402  (тот же htop-чанк, что в замере D1)


def to_top(t):
    """scroll_up() до верхней границы истории (no-op на границе)."""
    guard = 0
    while t.scroll_up() and guard < 10000:
        guard += 1


def line_key(line):
    """Строка pyte → сравниваемый ключ: ((col, data, fg, bg), ...) по возрастанию col."""
    return tuple((x, line[x].data, line[x].fg, line[x].bg) for x in sorted(line))


def full_state(t):
    """Полное состояние HistoryScreen для сравнения bulk-пути с циклом pyte."""
    scr = t.screen
    return {
        "pos": (scr.history.position, scr.history.size),
        "top": [line_key(l) for l in scr.history.top],
        "bottom": [line_key(l) for l in scr.history.bottom],
        "buffer": [line_key(scr.buffer[y]) for y in range(scr.lines)],
        "cursor": (scr.cursor.x, scr.cursor.y, bool(scr.cursor.hidden)),
    }


def grid_key(t):
    """Снимок сетки для «сетка корректна»: (rows с data/fg/bg, курсор)."""
    rows, cx, cy, hidden = t.snapshot()
    return ([[ (ch.data, ch.fg, ch.bg) for ch in row ] for row in rows], (cx, cy, hidden))


# ════════════════════════════════════════════════════════════
# 0. Wiring: override существует и подхватывается обёрткой по имени
# ════════════════════════════════════════════════════════════
print("== wiring ==")

check("wiring: SshmapHistoryScreen переопределяет before_event",
      SshmapHistoryScreen.before_event is not pyte.HistoryScreen.before_event,
      f"{SshmapHistoryScreen.before_event.__qualname__}")
check("wiring: before_event НЕ входит в HistoryScreen._wrapped (обёртка вызывает его по имени)",
      "before_event" not in pyte.HistoryScreen._wrapped,
      str(sorted(a for a in pyte.HistoryScreen._wrapped if "event" in a)))

# Функционально: парсер реально вызывает override подкласса при каждом событии.
_t0 = TerminalScreen(columns=40, lines=10)
for i in range(30):
    _t0.feed(b"w-%02d\r\n" % i)
to_top(_t0)
assert _t0.scroll_info()[0] < 1000, "тестовая прокрутка вверх не сработала"
_calls = []
_orig_before = SshmapHistoryScreen.before_event


def _spy(self, event):
    _calls.append(event)
    _orig_before(self, event)


SshmapHistoryScreen.before_event = _spy
try:
    _t0.feed(b"SPY\r\n")
finally:
    SshmapHistoryScreen.before_event = _orig_before
check("wiring: обёртка Stream вызывает before_event подкласса по имени (события прошли через spy)",
      "draw" in _calls and len(_calls) > 1, f"events={_calls[:8]}…")
check("wiring: после события — авто-возврат к live (position == size)",
      _t0.scroll_info()[0] == _t0.scroll_info()[1], str(_t0.scroll_info()))


# ════════════════════════════════════════════════════════════
# 1. Базовый авто-возврат (k ≤ lines) — поведение v1.0RC3 сохранено
# ════════════════════════════════════════════════════════════
print("== basic auto-return (k <= lines) ==")

t = TerminalScreen(columns=40, lines=32, history_lines=100)
for i in range(50):
    t.feed(b"line-%02d\r\n" % i)
check("базовый: откатились на страницу (position < size)", t.scroll_up() is True and t.at_bottom() is False,
      str(t.scroll_info()))
t.feed(b"SNAP-MARKER\r\n")
check("базовый: новое событие → авто-возврат к live (position == size)",
      t.at_bottom() is True, str(t.scroll_info()))
visible = "\n".join(t.screen.display)
check("базовый: новый вывод виден на live-строке", "SNAP-MARKER" in visible)


# ════════════════════════════════════════════════════════════
# 2. Глубокая история + чанк (D1-сценарий): позиция к size, сетка корректна
# ════════════════════════════════════════════════════════════
print("== deep history + htop chunk (D1 scenario) ==")

COLUMNS, LINES, HIST = 120, 32, 1000
chunk, chunk_src = load_chunk()


def build_deep(n_lines=1050):
    t = TerminalScreen(COLUMNS, LINES, history_lines=HIST)
    for i in range(n_lines):
        t.feed(b"history line %d\r\n" % i)
    return t


# Замер (время — только в отчёте, без ms-ассертов).
t_timed = build_deep()
to_top(t_timed)
pos, size = t_timed.scroll_info()
page = max(1, int(math.ceil(LINES * TS.SCROLL_RATIO)))
expected_pages = (size - pos) / float(page)
check("глубокая история: пользователь у верхней границы (position == lines)",
      pos == LINES and size == HIST, f"({pos}, {size})")

REPEATS = 3
best_ms = None
for _ in range(REPEATS):
    to_top(t_timed)                     # худший случай перед каждым замером
    t0 = time.perf_counter()
    t_timed.feed(chunk)
    dt = (time.perf_counter() - t0) * 1000.0
    best_ms = dt if best_ms is None else min(best_ms, dt)
print(f"  отчёт замера: htop-чанк {len(chunk)} B ({chunk_src}) у верхней границы "
      f"(position={pos}/{size}, ожидаемых next_page ≈ {expected_pages:.0f}) → "
      f"{best_ms:.2f} мс/чанк (лучший из {REPEATS}; без батчинга было 68–73 мс — замер D1 v1.2.12)")

# Функциональное сравнение: свежая пара экранов, чанк ровно ОДИН раз.
t_deep = build_deep()
t_ref = build_deep()                    # референс: БЕЗ прокрутки — чанк на live-строке
to_top(t_deep)
t_deep.feed(chunk)
t_ref.feed(chunk)

check("глубокая история + чанк: позиция вернулась к size (live-строка)",
      t_deep.at_bottom() is True, str(t_deep.scroll_info()))
check("глубокая история + чанк: bottom пуст (все строки возвращены в top/buffer)",
      len(t_deep.screen.history.bottom) == 0, f"bottom_len={len(t_deep.screen.history.bottom)}")
check("глубокая история + чанк: top полностью восстановлен (== capacity)",
      len(t_deep.screen.history.top) == HIST, f"top_len={len(t_deep.screen.history.top)}")
check("глубокая история + чанк: сетка корректна — полное состояние (pos/top/bottom/buffer/cursor) "
      "идентично референсу без прокрутки",
      full_state(t_deep) == full_state(t_ref))


# ════════════════════════════════════════════════════════════
# 3. Эквивалентность штатному циклу pyte next_page() (полное состояние)
# ════════════════════════════════════════════════════════════
print("== equivalence with pyte next_page() loop ==")


def twin_case(cols, lines, hist, printed, ups, label):
    """Два идентичных экрана: A — bulk-авто-возврат событием; B — штатный цикл
    next_page() до live. Полное состояние после одинакового чанка должно совпасть."""
    ta = TerminalScreen(columns=cols, lines=lines, history_lines=hist)
    tb = TerminalScreen(columns=cols, lines=lines, history_lines=hist)
    for i in range(printed):
        payload = b"row-%04d\r\n" % i
        ta.feed(payload)
        tb.feed(payload)
    for _ in range(ups):
        if not ta.scroll_up():
            break
    # A: bulk-путь — одно событие триггерит авто-возврат, затем обрабатывает чанк
    ta.feed(b"END-MARK\r\n")
    # B: референс — штатный цикл pyte (next_page через обёртку; before_event no-op для него)
    while tb.screen.history.position < tb.screen.history.size:
        tb.screen.next_page()
    tb.feed(b"END-MARK\r\n")
    ok = full_state(ta) == full_state(tb) and ta.at_bottom() is True
    check(f"эквивалентность ({label}): bulk-возврат == цикл next_page() (pos/top/bottom/buffer/cursor)",
          ok, f"A={ta.scroll_info()} B={tb.scroll_info()}")
    return ok


twin_case(40, 32, 100, 50, 1, "k=4 <= lines=32")
twin_case(40, 32, 100, 80, 5, "k=20 <= lines=32")
twin_case(20, 5, 50, 200, 9999, "k=45 >> lines=5 (мелкая сетка)")
twin_case(120, 32, 1000, 1050, 9999, "D1: k=968 >> lines=32 (худший случай)")
twin_case(80, 24, 300, 400, 77, "k=77 > lines=24 (частичная прокрутка)")


# ════════════════════════════════════════════════════════════
# 4. prev_page/next_page — no-op: ручная прокрутка не сбрасывается авто-возвратом
# ════════════════════════════════════════════════════════════
print("== manual paging is not hijacked ==")

tp = TerminalScreen(columns=40, lines=10, history_lines=50)
for i in range(30):
    tp.feed(b"n-%02d\r\n" % i)
tp.scroll_up()
tp.scroll_up()                        # страница = ceil(10*0.1) = 1 строка → position 48
check("ручная прокрутка: откатились на 2 страницы (position == size − 2)",
      tp.scroll_info() == (48, 50), str(tp.scroll_info()))
tp.screen.next_page()                 # колесо вниз — ОДНА страница, не весь путь до live
check("ручная прокрутка: next_page — пошагово (одна страница, НЕ прыжок к live)",
      tp.scroll_info()[0] == 49, str(tp.scroll_info()))
tp.feed(b"Y\r\n")                     # только событие возвращает остаток пути
check("ручная прокрутка: следующее событие доводит до live", tp.at_bottom() is True,
      str(tp.scroll_info()))


# ════════════════════════════════════════════════════════════
# 5. Границы и регрессии
# ════════════════════════════════════════════════════════════
print("== edges & regressions ==")

# Событие на live-строке при полной истории — no-op bulk-пути, ничего не ломается.
te = TerminalScreen(columns=40, lines=10, history_lines=20)
for i in range(60):
    te.feed(b"e-%02d\r\n" % i)
g_before = grid_key(te)
te.feed(b"LIVE-EVENT\r\n")
check("live-строка + полная история: событие не меняет position (== size)",
      te.at_bottom() is True, str(te.scroll_info()))
check("live-строка + полная история: вывод виден, сетка жива",
      "LIVE-EVENT" in "\n".join(te.screen.display))

# Пустая история — событие без ошибок.
tf = TerminalScreen(columns=20, lines=5)
tf.feed(b"hello\r\n")
check("пустая история: событие без ошибок, position == size (0-строчный скроллбэк не сломан)",
      tf.at_bottom() is True, str(tf.scroll_info()))

# history_lines=0 — пользователь отключил скроллбэк (deque maxlen=0).
tg = TerminalScreen(columns=20, lines=5, history_lines=0)
for i in range(10):
    tg.feed(b"z-%d\r\n" % i)
check("history_lines=0: feed работает, position == size == 0",
      tg.scroll_info() == (0, 0), str(tg.scroll_info()))

# Два чанка подряд из глубокой истории — состояние не дрейфует.
th = TerminalScreen(columns=80, lines=16, history_lines=200)
trh = TerminalScreen(columns=80, lines=16, history_lines=200)
for i in range(150):
    p = b"m-%03d\r\n" % i
    th.feed(p)
    trh.feed(p)
trh.feed(chunk[:len(chunk) // 2])       # референс — без прокрутки, оба получанка подряд
to_top(th)
th.feed(chunk[:len(chunk) // 2])
check("два чанка подряд из глубокой истории: позиция на live после первого",
      th.at_bottom() is True, str(th.scroll_info()))
to_top(th)
th.feed(chunk[len(chunk) // 2:])
trh.feed(chunk[len(chunk) // 2:])
check("два чанка подряд из глубокой истории: позиция на live после второго",
      th.at_bottom() is True, str(th.scroll_info()))
check("два чанка подряд: сетка == референсу без прокрутки (нет дрейфа состояния)",
      grid_key(th) == grid_key(trh))

# Вход в alt из глубокой истории (регрессия v1.2.12 через bulk-путь).
ta = TerminalScreen(columns=80, lines=10, history_lines=200)
for i in range(50):
    ta.feed(b"HIST %d\r\n" % i)
to_top(ta)
ta.feed(b"\x1b[?1049h\x1b[2J\x1b[Halt-frame\r\n")
check("вход в alt из глубокой истории: bulk-авто-возврат сработал (position == size)",
      ta.scroll_info()[0] == 200, str(ta.scroll_info()))
check("вход в alt из глубокой истории: alt активен, сетка = TUI",
      ta.in_alt_screen() is True and "alt-frame" in "\n".join(ta.screen.display))
ta.feed(b"\x1b[?1049l")
check("выход из alt: основной экран на месте (HIST виден)",
      ta.in_alt_screen() is False and "HIST" in "\n".join(ta.screen.display))

# dirty после bulk-возврата — все строки (как в next_page).
td = TerminalScreen(columns=40, lines=10, history_lines=50)
for i in range(30):
    td.feed(b"d-%02d\r\n" % i)
to_top(td)
td.feed(b"Z\r\n")
check("dirty после bulk-возврата = все строки",
      td.screen.dirty == set(range(10)), f"dirty={sorted(td.screen.dirty)}")


# ════════════════════════════════════════════════════════════
# 6. Состояние релиза + i18n-паритет (новых ключей нет — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_release_state(ROOT)
check_i18n_parity(load_i18n_langs(ROOT))

finish()
