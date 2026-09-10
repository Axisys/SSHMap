# -*- coding: utf-8 -*-
"""v1.2.11 — Терминал: совместимость pyte 0.8.2 (private SGR + LNM) (ROADMAP v1.2.11,
PYTE82_AUDIT.md пачка A).

Headless (без Qt): подкласс SshmapHistoryScreen(pyte.HistoryScreen) в
modules/terminal_screen.py — два override'а:
  * private SGR (CSI ? … m) игнорируются: проверенный факт №12 — в pyte 0.8.2
    \\x1b[?4m (Vim 9+, upstream issue #202) → TypeError из feed(), и хвост чанка
    ПОСЛЕ последовательности теряется (парсер сбрасывается; except Exception: return
    в _on_output глотает исключение). В master фикс уже вмержен (PR #203, 2025-09-02) —
    override с той же семантикой остаётся до поднятия пина на pyte 0.8.3;
  * LNM (режим 20) включён по умолчанию: голый LF = CR+LF (xterm-поведение).
    Screen.reset() сбрасывает mode на _DEFAULT_MODE БЕЗ LNM → явное восстановление
    в __init__ и в reset() (после RIS ESC c); явные \\x1b[20h/\\x1b[20l (SM/RM 20)
    от удалённой программы по-прежнему работают.

Примечание: в PYTE82_AUDIT.md/ROADMAP последовательности записаны как \\x1b[2h/\\x1b[2l —
опечатка плана; LNM это режим 20 (pyte.modes.LNM = 20), и pyte 0.8.2 переключает его
ровно SM/RM 20 (проверено прогоном: \\x1b[2l трогает бит 2, а не 20).

v1.2.12 (поправка): RIS — это ESC c (\\x1bc), а НЕ ESC [ c (\\x1b[c) — последнее
pyte 0.8.2 парсит как CSI DA (report_device_attributes, no-op): проверено прогоном,
\\x1b[c Screen.reset() не вызывает вовсе. Проверка «LNM после RIS» ниже исправлена
на реальные байты + закреплён факт про \\x1b[c (ранее check был ложноположительным).

Запуск: python tests/test_pyte_compat.py   (из корня проекта) или python tests/run_all.py
"""
import sys

from _common import bootstrap, check, finish, load_i18n_langs, check_i18n_parity, check_release_state

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения

import pyte

from modules.terminal_screen import TerminalScreen, SshmapHistoryScreen


def lines(scr):
    """screen.display → список строк без хвостовых пробелов (headless-снимок)."""
    return [line.rstrip() for line in scr.screen.display]


# ════════════════════════════════════════════════════════════
# 1. Подкласс на месте: TerminalScreen создаёт SshmapHistoryScreen
# ════════════════════════════════════════════════════════════
print("== SshmapHistoryScreen wiring (headless) ==")

scr = TerminalScreen(columns=40, lines=5, history_lines=10)
check("TerminalScreen создаёт SshmapHistoryScreen",
      isinstance(scr.screen, SshmapHistoryScreen), type(scr.screen).__name__)
check("…и это по-прежнему pyte.HistoryScreen (duck-typing скроллбэка)",
      isinstance(scr.screen, pyte.HistoryScreen))
check("LNM включён в дефолтном mode после конструктора",
      pyte.modes.LNM in scr.screen.mode, str(sorted(scr.screen.mode)))


# ════════════════════════════════════════════════════════════
# 2. Private SGR (A1): \x1b[?4m — без TypeError, хвост чанка сохранён
# ════════════════════════════════════════════════════════════
print("== private SGR (Vim 9+) ==")

scr2 = TerminalScreen(columns=40, lines=5, history_lines=10)
disp_before = lines(scr2)
mode_before = set(scr2.screen.mode)
cur_before = (scr2.screen.cursor.x, scr2.screen.cursor.y, scr2.screen.cursor.hidden)
detail_exc = ""
try:
    scr2.feed(b"\x1b[?4m")          # Vim 9+ (upstream issue #202): в 0.8.2 — TypeError из feed()
except Exception as e:              # noqa: BLE001
    detail_exc = repr(e)
check("feed(b'\\x1b[?4m') — исключений нет (в 0.8.2 было TypeError)", detail_exc == "", detail_exc)
check("display не изменился", lines(scr2) == disp_before, repr(lines(scr2)))
check("mode не изменился", set(scr2.screen.mode) == mode_before, str(sorted(scr2.screen.mode)))
check("cursor не изменился (x, y, hidden)",
      (scr2.screen.cursor.x, scr2.screen.cursor.y, scr2.screen.cursor.hidden) == cur_before,
      f"{(scr2.screen.cursor.x, scr2.screen.cursor.y, scr2.screen.cursor.hidden)} vs {cur_before}")

# Регрессия на потерю хвоста чанка: после private SGR парсер должен жить дальше.
scr3 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr3.feed(b"AB\x1b[?4mCD\r\n")
check("хвост чанка сохранён: b'AB\\x1b[?4mCD\\r\\n' → строка \"ABCD\"",
      lines(scr3)[0] == "ABCD", repr(lines(scr3)[0]))

# Private SGR с несколькими параметрами — тоже игнорится.
scr3b = TerminalScreen(columns=40, lines=5, history_lines=10)
scr3b.feed(b"X\x1b[?4;11mY\r\n")
check("private SGR с параметрами (\\x1b[?4;11m): хвост сохранён → \"XY\"",
      lines(scr3b)[0] == "XY", repr(lines(scr3b)[0]))

# Обычный (не-приватный) SGR не задет override'ом.
scr4 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr4.feed(b"\x1b[31mR\x1b[0m")
check("обычный SGR работает: \\x1b[31m → fg='red'", scr4.screen.buffer[0][0].fg == "red",
      repr(scr4.screen.buffer[0][0].fg))
check("SGR 0 сбрасывает rendition (страховка основного пути)",
      scr4.screen.buffer[0][1].fg == "default", repr(scr4.screen.buffer[0][1].fg))


# ════════════════════════════════════════════════════════════
# 3. LNM по умолчанию (A2): голый LF = CR+LF; явные SM/RM 20 и RIS
# ════════════════════════════════════════════════════════════
print("== LNM default ==")

scr5 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr5.feed(b"ab\ncd")
check("голый LF = CR+LF: b'ab\\ncd' → [\"ab\", \"cd\"]",
      lines(scr5)[:2] == ["ab", "cd"], repr(lines(scr5)[:2]))

# Явное выключение LNM удалённой программой (RM 20): голый LF снова без CR.
scr6 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr6.feed(b"\x1b[20lab\ncd")
check("после \\x1b[20l: LNM выключен (mode не содержит 20)",
      pyte.modes.LNM not in scr6.screen.mode, str(sorted(scr6.screen.mode)))
check("после \\x1b[20l: голый LF без CR — cd со смещением x=2",
      lines(scr6)[:2] == ["ab", "  cd"], repr(lines(scr6)[:2]))

# Явное включение (SM 20) возвращает xterm-поведение.
scr6.feed(b"\x1b[20h")
check("после \\x1b[20h: LNM снова в mode", pyte.modes.LNM in scr6.screen.mode,
      str(sorted(scr6.screen.mode)))
scr6.feed(b"ef\ngh")
check("после \\x1b[20h: голый LF снова CR+LF — \"gh\" с x=0 на новой строке",
      lines(scr6)[1:3] == ["  cdef", "gh"], repr(lines(scr6)[1:3]))

# RIS (ESC c — НЕ ESC [ c): полный сброс — LNM возвращается (reset() подкласса).
scr7 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr7.feed(b"\x1bcab\ncd")
check("после RIS (\\x1bc): LNM восстановлен", pyte.modes.LNM in scr7.screen.mode,
      str(sorted(scr7.screen.mode)))
check("после RIS: голый LF снова CR+LF → [\"ab\", \"cd\"]",
      lines(scr7)[:2] == ["ab", "cd"], repr(lines(scr7)[:2]))

# v1.2.12 (проверено прогоном): \\x1b[c — это CSI DA, а не RIS: Screen.reset()
# не вызывается вовсе (экран НЕ чистится). Закрепляем факт — чтобы опечатка
# «ESC [ c» больше не маскировалась ложноположительным check'ом.
scr8 = TerminalScreen(columns=40, lines=5, history_lines=10)
scr8.feed(b"stale\r\n")
scr8.feed(b"\x1b[c")
check("\\x1b[c (CSI DA) НЕ сбрасывает экран (это не RIS)",
      "stale" in scr8.screen.display[0], repr(scr8.screen.display[0]))


# ════════════════════════════════════════════════════════════
# 4. Состояние релиза + i18n-паритет (новых ключей нет — 427)
# ════════════════════════════════════════════════════════════
print("== release state ==")

check_i18n_parity(load_i18n_langs(ROOT))
check_release_state(ROOT)

finish()
