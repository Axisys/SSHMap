# -*- coding: utf-8 -*-
"""v1.2.12 — Терминал: альтернативный экран (приватные режимы 47/1047/1048/1049).

Тематический тест темы релиза (ROADMAP v1.2.12, PYTE82_AUDIT.md пачка B):
SshmapHistoryScreen реализует альтернативный экран, которого нет в pyte 0.8.2
(режимы были инертными битами screen.mode со сдвигом <<5, обработчиков нет).
Семантика — по upstream PR #212 (закрыт без мерджа, автор dwgx; код pyte LGPL-3.0 —
атрибуция в комментарии к коду), дифференциально проверенная против tmux 3.6b
и GNU screen. Headless: синтетические последовательности байтов в TerminalScreen
(без Qt, без сети):

  * round-trip (главный): вывод shell → снимок G0 с цветами;
    \\x1b[?1049h\\x1b[2J\\x1b[H + «каркас TUI» → сетка = TUI; \\x1b[?1049l → сетка
    посимвольно равна G0 (включая fg/bg) и курсор;
  * матрица входов/выходов по ВСЕМ комбинациям {47, 1047, 1048, 1049}
    (вход a → выход b — всегда возврат к основному экрану) + повторный вход идемпотентен;
  * кросс-выход: 1049h … 47l → выход (один флаг in_alt, не четыре);
  * двойной вход: 1049h 1049h → основной экран не потерян, один выход возвращает;
  * курсор: (5,3) → 1049h (НЕ хомится) → TUI гоняет курсор → 1049l → снова (5,3);
    для 47/1047 — НЕ восстанавливается (закреплено по спецификации);
  * изоляция истории: 50+ строк в alt (скроллинг за край) → выход → TUI-строк
    в скроллбэке нет (как less в настоящем терминале);
  * RIS (ESC c — НЕ ESC [ c, это CSI DA) внутри alt → основной экран, всё чисто,
    режимы дефолтные;
  * resize в alt: вход при 120 колонках → resize(80) → выход → строки основного
    экрана обрезаны до 80 («переширокого» восстановления нет);
  * вход при просмотре истории: авто-возврат к live сработал, alt активен.

Запуск: python tests/test_alt_screen.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

import pyte
import pyte.screens as P

import modules.terminal_screen as TS
from modules.terminal_screen import SshmapHistoryScreen, TerminalScreen


def make(cols=120, lines=32, history_lines=1000):
    return TerminalScreen(columns=cols, lines=lines, history_lines=history_lines)


def rows(t):
    """Снимок сетки (rows из snapshot)."""
    return t.snapshot()[0]


def empty_grid(t):
    """Полностью дефолтная сетка columns×lines (пустой буфер)."""
    d = P.Char(data=" ", fg="default", bg="default")
    return [[d] * t.columns for _ in range(t.lines)]


# Вывод shell с цветами (SGR 1;32 / 1;34 / 34 / 93 / 256-цвет) — «основной экран».
SHELL = (b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ls\r\n"
         b"\x1b[0;34mdocs\x1b[0m  \x1b[93mnotes.txt\x1b[0m  \x1b[38;5;196mall.xml\x1b[0m\r\n"
         b"\x1b[1;32mroot@master\x1b[0m:\x1b[1;34m~\x1b[0m$ ")

# «Каркас TUI»: полный перерис + рамка + строки с цветами.
TUI_FRAME = (b"\x1b[2J\x1b[H"
             b"+-----------------------------+\r\n"
             b"| TUI frame (alt screen)      |\r\n"
             b"|\x1b[41m red bar \x1b[0m                    |\r\n"
             b"+-----------------------------+\r\n"
             b"\x1b[7;1H\x1b[36mcursor parked here\x1b[0m")


# ════════════════════════════════════════════════════════════
# 0. Wiring: константа, доступор, биты в mode
# ════════════════════════════════════════════════════════════
print("== wiring ==")

check("wiring: ALTSCREEN_MODES = (47, 1047, 1048, 1049) — private-коды ДО сдвига <<5",
      SshmapHistoryScreen.ALTSCREEN_MODES == (47, 1047, 1048, 1049),
      str(SshmapHistoryScreen.ALTSCREEN_MODES))

t = make()
check("wiring: свежий экран — in_alt_screen() False, screen.in_alt False",
      t.in_alt_screen() is False and t.screen.in_alt is False)
t.feed(b"\x1b[?1049h")
check("wiring: бит складывается в mode как раньше (1049 << 5 = 33568)",
      (1049 << 5) in t.screen.mode, str(sorted(t.screen.mode)))
t.feed(b"\x1b[?1049l")
check("wiring: после выхода бит снят", (1049 << 5) not in t.screen.mode)


# ════════════════════════════════════════════════════════════
# 1. Round-trip (главный): shell → G0 с цветами; TUI в alt; возврат посимвольно
# ════════════════════════════════════════════════════════════
print("== round-trip ==")

t = make()
t.feed(SHELL)
g0 = t.snapshot()   # (rows, cx, cy, hidden) — снимок с цветами ДО входа в alt

t.feed(b"\x1b[?1049h")
check("round-trip: 1049h → in_alt True", t.in_alt_screen() is True)
check("round-trip: рабочий буфер после входа ПУСТОЙ (TUI ещё не рисовал)",
      rows(t) == empty_grid(t))

t.feed(TUI_FRAME)
txt = "\n".join(t.screen.display)
check("round-trip: сетка = TUI (рамка + 'red bar'), shell-контента нет",
      "TUI frame (alt screen)" in txt and "red bar" in txt
      and "root@master" not in txt, txt[:80])

t.feed(b"\x1b[?1049l")
check("round-trip: 1049l → in_alt False", t.in_alt_screen() is False)
g1 = t.snapshot()
check("round-trip: сетка посимвольно равна G0 (включая fg/bg)", g1[0] == g0[0])
check("round-trip: курсор и hidden восстановлены", (g1[1], g1[2], g1[3]) == (g0[1], g0[2], g0[3]),
      f"got=({g1[1]},{g1[2]},{g1[3]}) want=({g0[1]},{g0[2]},{g0[3]})")


# ════════════════════════════════════════════════════════════
# 2. Матрица входов/выходов: все пары {47, 1047, 1048, 1049} + идемпотентность
# ════════════════════════════════════════════════════════════
print("== matrix ==")

MODES = (47, 1047, 1048, 1049)
matrix_ok = True
detail = ""
for a in MODES:
    for b in MODES:
        tm = make(80, 24)
        tm.feed(SHELL)
        r0 = rows(tm)
        tm.feed(("\x1b[?%dh" % a).encode())
        if not tm.in_alt_screen():
            matrix_ok = False
            detail = f"enter {a}: in_alt False"
            break
        tm.feed(b"\x1b[2J\x1b[H" + b"TUI " + str(a).encode() + b"\r\n")
        tm.feed(("\x1b[?%dl" % b).encode())
        if tm.in_alt_screen() or rows(tm) != r0:
            matrix_ok = False
            detail = f"{a}h→{b}l: in_alt={tm.in_alt_screen()} grid_changed={rows(tm) != r0}"
            break
    if not matrix_ok:
        break
check("матрица 4×4: вход a → выход b (любые комбинации) — всегда возврат к основному экрану",
      matrix_ok, detail)

# Повторный вход идемпотентен: второй h НЕ затирает сохранённый основной буфер.
tm = make(80, 24)
tm.feed(SHELL)
r0 = rows(tm)
tm.feed(b"\x1b[?1049h")
saved_ref = tm.screen._saved_buffer
tm.feed(b"\x1b[?1047h")   # повторный вход (другим кодом) — идемпотентно
check("повторный вход идемпотентен: сохранённый основной буфер не заменён",
      tm.screen._saved_buffer is saved_ref and tm.in_alt_screen() is True)
tm.feed(b"\x1b[?1049l")   # ОДИН выход возвращает
check("повторный вход: один выход возвращает основной экран",
      rows(tm) == r0 and tm.in_alt_screen() is False)

# Кросс-выход: 1049h … 47l → выход (один флаг in_alt, не четыре).
tm = make(80, 24)
tm.feed(SHELL)
r0 = rows(tm)
tm.feed(b"\x1b[?1049h")
check("кросс-выход: 1049h → in_alt True", tm.in_alt_screen() is True)
tm.feed(b"\x1b[?47l")
check("кросс-выход: 47l выходит из экрана, вошедшего через 1049h (один флаг)",
      tm.in_alt_screen() is False and rows(tm) == r0)

# Двойной вход: 1049h 1049h → основной экран не потерян, один выход возвращает.
tm = make(80, 24)
tm.feed(SHELL)
r0 = rows(tm)
tm.feed(b"\x1b[?1049h\x1b[?1049h")
check("двойной вход: in_alt True, основной буфер сохранён (один _saved_buffer)",
      tm.in_alt_screen() is True and isinstance(tm.screen._saved_buffer, dict))
tm.feed(b"\x1b[?1049l")
check("двойной вход: один выход возвращает основной экран",
      rows(tm) == r0 and tm.in_alt_screen() is False)


# ════════════════════════════════════════════════════════════
# 3. Курсор: 1048/1049 сохраняют/восстанавливают; 47/1047 — нет (по спецификации)
# ════════════════════════════════════════════════════════════
print("== cursor ==")

tm = make()
tm.feed(b"\x1b[4;6H")   # CUP 4;6 → (x=5, y=3)
check("курсор установлен в (5,3)", tm.snapshot()[1:3] == (5, 3))
tm.feed(b"\x1b[?1049h")
check("1049h: курсор НЕ хомится при входе (TUI сам шлёт CUP) — остаётся (5,3)",
      tm.snapshot()[1:3] == (5, 3), str(tm.snapshot()[1:3]))
tm.feed(b"\x1b[2J\x1b[H" + TUI_FRAME)   # TUI гоняет курсор: CUP 7;1 + вывод 18 символов → (18,6)
check("в alt: TUI утащил курсор в (18,6)", tm.snapshot()[1:3] == (18, 6), str(tm.snapshot()[1:3]))
tm.feed(b"\x1b[?1049l")
check("1049l: курсор снова (5,3) — сохранён отдельным полем _alt_cursor",
      tm.snapshot()[1:3] == (5, 3), str(tm.snapshot()[1:3]))

for m in (47, 1047):
    tm = make()
    tm.feed(b"\x1b[4;6H")
    tm.feed(("\x1b[?%dh" % m).encode())
    tm.feed(b"\x1b[2J\x1b[H\x1b[10;20H")   # TUI гоняет курсор → (19, 9)
    tm.feed(("\x1b[?%dl" % m).encode())
    check("курсор: %d — НЕ восстанавливается (спецификация xterm: только 1048/1049); "
          "остался в позиции TUI (19,9)" % m,
          tm.snapshot()[1:3] == (19, 9), str(tm.snapshot()[1:3]))


# ════════════════════════════════════════════════════════════
# 4. Изоляция истории: TUI-строки не попадают в скроллбэк (как less)
# ════════════════════════════════════════════════════════════
print("== history isolation ==")

tm = make(80, 10, history_lines=200)
for i in range(40):
    tm.feed(b"MAIN %d\r\n" % i)
top_before = len(tm.screen.history.top)
pos_before, size_before = tm.scroll_info()

tm.feed(b"\x1b[?1049h")
for i in range(60):          # 60 строк при 10-строчном alt — скроллинг за край
    tm.feed(b"TUI-%d\r\n" % i)
check("в alt: строки, ушедшие за край, НЕ попадают в history.top",
      len(tm.screen.history.top) == top_before,
      f"{len(tm.screen.history.top)} vs {top_before}")

tm.feed(b"\x1b[?1049l")
check("после выхода: история не выросла, позиция не изменилась",
      len(tm.screen.history.top) == top_before and tm.scroll_info() == (pos_before, size_before),
      str((len(tm.screen.history.top),) + tm.scroll_info()))

while tm.scroll_up():
    pass
check("скроллбэк: TUI-строк в истории НЕТ (как less в настоящем терминале)",
      "TUI-" not in "\n".join(tm.screen.display))


# ════════════════════════════════════════════════════════════
# 5. RIS (ESC c) внутри alt: полный сброс + выход, режимы дефолтные
# ════════════════════════════════════════════════════════════
print("== RIS in alt ==")

tm = make()
tm.feed(SHELL)
tm.feed(b"\x1b[?1049h" + TUI_FRAME)
check("RIS: до сброса — в alt, сетка = TUI", tm.in_alt_screen() is True
      and "TUI frame" in "\n".join(tm.screen.display))
tm.feed(b"\x1bc")   # RIS = ESC c (НЕ \x1b[c — это CSI DA)
check("RIS в alt: выход из alt (in_alt False)", tm.in_alt_screen() is False)
check("RIS в alt: основной экран чистится штатным reset() — сетка полностью дефолтная",
      rows(tm) == empty_grid(tm))
check("RIS в alt: режимы дефолтные (+LNM v1.2.11): mode == {DECAWM, DECTCEM, LNM}",
      tm.screen.mode == {pyte.modes.DECAWM, pyte.modes.DECTCEM, pyte.modes.LNM},
      str(sorted(tm.screen.mode)))
check("RIS в alt: история очищена штатно (top пуст, position == size)",
      len(tm.screen.history.top) == 0 and tm.scroll_info()[0] == tm.scroll_info()[1])


# ════════════════════════════════════════════════════════════
# 6. Resize в alt: выход клипует сохранённый буфер под текущую ширину
# ════════════════════════════════════════════════════════════
print("== resize in alt ==")

tm = make(120, 32)
tm.feed(b"A" * 100 + b"\r\nshort line\r\n")   # строка ШИРЕ будущей ширины (80)
tm.feed(b"\x1b[?1049h")
tm.resize(80, 32)                              # resize во время alt
check("resize в alt: сетка стала 80 колонок", tm.screen.columns == 80)
tm.feed(b"\x1b[2J\x1b[H" + b"B" * 80 + b"\r\n")
tm.feed(b"\x1b[?1049l")
disp = tm.screen.display
check("resize в alt: строки основного экрана обрезаны до 80 (row 0 = первые 80 'A')",
      disp[0] == "A" * 80 and len(disp[0]) == 80, repr(disp[0][:90]))
check("resize в alt: «переширокого» восстановления нет (все ключи строк < columns)",
      all(max(line, default=-1) < tm.screen.columns for line in tm.screen.buffer.values()))
check("resize в alt: содержимое сохранилось (row 1 = 'short line')",
      disp[1].startswith("short line"), repr(disp[1][:20]))


# ════════════════════════════════════════════════════════════
# 7. Вход при просмотре истории: авто-возврат к live сработал, alt активен
# ════════════════════════════════════════════════════════════
print("== entry while viewing history ==")

tm = make(80, 10, history_lines=200)
for i in range(50):
    tm.feed(b"HIST %d\r\n" % i)
check("вход при просмотре истории: откатились в историю (position < size)",
      tm.scroll_up() is True and tm.scroll_info()[0] < 200, str(tm.scroll_info()))
tm.feed(b"\x1b[?1049h" + TUI_FRAME)
check("вход при просмотре истории: авто-возврат к live сработал (position == size)",
      tm.scroll_info()[0] == 200, str(tm.scroll_info()))
check("вход при просмотре истории: alt активен, сетка = TUI",
      tm.in_alt_screen() is True and "TUI frame" in "\n".join(tm.screen.display))
tm.feed(b"\x1b[?1049l")
check("выход после входа из истории: основной экран на месте",
      tm.in_alt_screen() is False and "HIST" in "\n".join(tm.screen.display))


# ════════════════════════════════════════════════════════════
# 8. Состояние релиза + i18n-паритет (новых ключей нет — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_release_state(ROOT)
check_i18n_parity(load_i18n_langs(ROOT))

finish()
