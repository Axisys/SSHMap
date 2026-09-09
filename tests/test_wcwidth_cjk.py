# -*- coding: utf-8 -*-
"""v1.2.9 — полный wcwidth(3) для CJK (ROADMAP «Гигиена терминала», задача 2).

Заменяет эвристику `east_asian_width` W/F из v1.0RC1 (known limitation v1.0 закрыт):
ширина глифа — ТА ЖАЯ библиотека `wcwidth`, что сам pyte 0.8.2 для раскладки сетки
(pyte.screens: `from wcwidth import wcwidth`), поэтому классификация холста всегда
совпадает с тем, как pyte размещает глифы в ячейках (+ заглушка после широкого).

  * char_width() — полная таблица wcwidth(3): wide (CJK/Fullwidth/Hangul/кана/emoji) = 2;
    narrow И ambiguous (wcwidth(3): категория Ambiguous = узкая, C locale) = 1;
    нулевые (составные знаки, variation selectors) = 0; контрольные (-1) клампятся в 0;
    пустая строка (заглушка) = 0; мульти-символьная ячейка (NFC-кластер pyte) — сумма;
  * is_wide_char() — char_width == 2; сверка с библиотекой wcwidth по выборке;
    эвристика unicodedata.east_asian_width в модуле больше нет (гигиена);
  * E2E через реальный TerminalScreen: сетка раскладывается ровно по wcwidth
    («a中b» = [a][中][''][b], заглушка — ширина 0; суммарная ширина = wcswidth),
    NFC-составной кластер «e»+U+0301 → ОДНА ячейка 'é' шириной 1 (регрессия: старая
    эвристика считала составной знак узким → ширина была бы 2);
  * split_row_runs/word_units на CJK-строках: заглушка не входит ни в один run,
    широкий глиф в конце строки — без IndexError; «a中b» = одно слово на 4 ячейках
    (семантика v1.2.7 под полным wcwidth).

Headless: Qt-виджеты не создаются (TerminalScreen — headless-friendly, чистые функции
terminal_widget.py — без GUI). Запуск:  python tests/test_wcwidth_cjk.py   (из корня проекта)
или python tests/run_all.py
"""
import inspect

from _common import bootstrap, check, finish

ROOT, WORK = bootstrap()  # ДО импортов модулей приложения (HOME-изоляция и faulthandler внутри)

from wcwidth import wcwidth as _wcwidth, wcswidth as _wcswidth

from modules.terminal_screen import TerminalScreen
import modules.terminal_widget as TW
from modules.terminal_widget import char_width, is_wide_char, split_row_runs, word_units


# ════════════════════════════════════════════════════════════
# 1. char_width — полная таблица wcwidth(3) (wide/narrow/ambiguous/zero)
# ════════════════════════════════════════════════════════════
print("== char_width: таблица wcwidth(3) ==")

# WIDE = 2: CJK-идеографы, Fullwidth (EAW F), Hangul, кана, CJK-пунктуация, emoji.
WIDE_CHARS = {
    "中": "CJK-идеограф",
    "\uff21": "Fullwidth 'A' (EAW F)",
    "한": "Hangul-слог",
    "あ": "кана (hiragana)",
    "、": "ideographic comma (EAW W)",
    "\u3000": "fullwidth space (EAW F)",
    "\U0001F600": "emoji U+1F600",
}
for ch, name in WIDE_CHARS.items():
    check(f"wide: {name} → 2", char_width(ch) == 2, repr(char_width(ch)))

# NARROW = 1: ASCII и латиница.
NARROW_CHARS = {"a": "ASCII", "é": "precomposed é (U+00E9)", "\uff71": "halfwidth katakana 'a' (EAW H)"}
for ch, name in NARROW_CHARS.items():
    check(f"narrow: {name} → 1", char_width(ch) == 1, repr(char_width(ch)))

# AMBIGUOUS = 1: категория Ambiguous в wcwidth(3) — УЗКАЯ (C locale). Старая эвристика
# east_asian_width W/F их тоже не считала широкими — поведение сохранено, теперь по
# полной таблице, а не по подмножеству.
AMBIGUOUS_CHARS = {
    "¿": "inverted '?'",
    "°": "degree sign",
    "\u2116": "numero sign №",
    "α": "greek alpha",
}
for ch, name in AMBIGUOUS_CHARS.items():
    check(f"ambiguous: {name} → 1 (узкая)", char_width(ch) == 1, repr(char_width(ch)))

# ZERO-WIDTH = 0: составные знаки и variation selectors. КЛЮЧЕВОЙ сдвиг против старой
# эвристики: у них EAW = 'A'/'M', W/F-проверка давала «узкий» (1) — кластер раздувался.
check("zero-width: combining acute U+0301 → 0", char_width("\u0301") == 0, repr(char_width("\u0301")))
check("zero-width: variation selector-1 U+FE0F → 0", char_width("\ufe0f") == 0, repr(char_width("\ufe0f")))

# Контрольные: wcwidth возвращает -1 — клампится в 0 (ячейка не несёт контрольных,
# но функция должна быть безопасна для любого содержимого).
check("control BEL U+0007 (-1) → кламп 0", char_width("\x07") == 0, repr(char_width("\x07")))

# Пустая строка — заглушка после широкого глифа (pyte: data == '') → 0.
check("пустая строка (заглушка) → 0", char_width("") == 0, repr(char_width("")))

# Мульти-символьная ячейка: pyte NFC-сливает составной знак в предыдущую ячейку —
# ширина = сумма по символам (ровно как посимвольный draw() pyte). «e»+U+0301 → «é»:
# 1 + 0 = 1. Старая эвристика: 1 + 1 = 2 (широкий! — регрессия закрыта v1.2.9).
cluster = "e\u0301"
check("NFC-кластер 'e'+U+0301 → 1 (а не 2 по старой эвристике)", char_width(cluster) == 1,
      repr(char_width(cluster)))

# ════════════════════════════════════════════════════════════
# 2. is_wide_char — та же таблица, что у pyte (библиотека wcwidth)
# ════════════════════════════════════════════════════════════
print("== is_wide_char: сверка с библиотекой wcwidth ==")

check("is_wide_char('中') — True", is_wide_char("中") is True)
check("is_wide_char('a') — False", is_wide_char("a") is False)
check("is_wide_char('¿') (ambiguous) — False", is_wide_char("¿") is False)
check("is_wide_char('') (заглушка) — False", is_wide_char("") is False)

# Выборка: классификация холста = классификация раскладки pyte (одна таблица).
SAMPLE = list(WIDE_CHARS) + list(NARROW_CHARS) + list(AMBIGUOUS_CHARS) + ["\u0301", "\ufe0f"]
_mismatch = [c for c in SAMPLE if is_wide_char(c) != (_wcwidth(c) == 2)]
check("is_wide_char == (wcwidth(ch) == 2) на выборке из %d символов" % len(SAMPLE),
      not _mismatch, repr(_mismatch))

# Гигиена: эвристика unicodedata.east_asian_width в модуле больше нет (задача 2) —
# ни импорта, ни обращения к атрибуту (исторические упоминания в docstring допустимы).
_src = inspect.getsource(TW)
check("эвристика unicodedata.east_asian_width из terminal_widget.py удалена",
      "import unicodedata" not in _src and ".east_asian_width" not in _src,
      "найдены остатки эвристики")

# ════════════════════════════════════════════════════════════
# 3. E2E через реальный TerminalScreen: сетка pyte = таблица wcwidth
# ════════════════════════════════════════════════════════════
print("== E2E: раскладка pyte == wcwidth ==")

scr = TerminalScreen(columns=20, lines=3)
scr.feed("a中b".encode("utf-8"))
rows, _cx, _cy, _hidden = scr.snapshot()
line0 = rows[0]

check("«a中b»: 4 ячейки занято — [a][中][''][b]",
      [c.data for c in line0[:4]] == ["a", "中", "", "b"],
      repr([c.data for c in line0[:6]]))
check("«a中b»: ширина ячеек 1/2/0/1",
      [char_width(c.data) for c in line0[:4]] == [1, 2, 0, 1],
      repr([char_width(c.data) for c in line0[:4]]))
check("«a中b»: суммарная ширина = wcswidth(«a中b») = 4",
      sum(char_width(c.data) for c in line0[:4]) == _wcswidth("a中b") == 4,
      repr(sum(char_width(c.data) for c in line0[:4])))
check("«a中b»: широкий глиф — is_wide_char по data ячейки",
      is_wide_char(line0[1].data) and not is_wide_char(line0[2].data))

# NFC-кластер: pyte сливает «e»+U+0301 в ОДНУ ячейку 'é' — ширина 1, а не 2.
scr2 = TerminalScreen(columns=20, lines=3)
scr2.feed("e\u0301b".encode("utf-8"))
rows2, _cx2, _cy2, _h2 = scr2.snapshot()
line2 = rows2[0]
check("«e»+U+0301+b: NFC-слияние — ячейка 0 = 'é' (2 символа)", line2[0].data == "é",
      repr(line2[0].data))
check("«e»+U+0301+b: ширина слиянной ячейки = 1 (старая эвристика дала бы 2)",
      char_width(line2[0].data) == 1, repr(char_width(line2[0].data)))
check("«e»+U+0301+b: 'b' в следующей ячейке", line2[1].data == "b", repr(line2[1].data))

# Ambiguous-символы занимают ровно по ОДНОЙ ячейке (не раздуваются до широких).
scr3 = TerminalScreen(columns=20, lines=3)
scr3.feed("¿°\u2116α".encode("utf-8"))
rows3, _cx3, _cy3, _h3 = scr3.snapshot()
line3 = rows3[0]
check("«¿°№α»: 4 символа = ровно 4 ячейки (ambiguous не широкие)",
      [c.data for c in line3[:4]] == ["¿", "°", "\u2116", "α"] and line3[4].data == " ",
      repr([c.data for c in line3[:5]]))

# ════════════════════════════════════════════════════════════
# 4. split_row_runs / word_units на CJK-строках (чистые функции)
# ════════════════════════════════════════════════════════════
print("== split_row_runs / word_units: CJK ==")

runs = split_row_runs(line0)
check("«a中b»: 3 runs — [a] | [中 wide] | [b…]", len(runs) == 3, repr(runs))
check("«a中b»: широкий run — (1, '中', True)", runs[1] == (1, "中", True), repr(runs[1]))
check("«a中b»: заглушка (x=2) не входит ни в один run",
      all(r[0] != 2 for r in runs) and "".join(r[1] for r in runs).replace(" ", "") == "a中b",
      repr(runs))

# Широкий глиф в КОНЦЕ строки: x += 2 выходит за len(row) — без IndexError.
scr4 = TerminalScreen(columns=6, lines=3)
scr4.feed("     中".encode("utf-8"))
rows4, _cx4, _cy4, _h4 = scr4.snapshot()
runs4 = split_row_runs(rows4[0])
check("широкий глиф в конце строки (x=5, cols=6): без IndexError", len(runs4) >= 1, repr(runs4))
check("широкий глиф в конце строки: последний run — (5, '中', True)",
      runs4[-1] == (5, "中", True), repr(runs4[-1]))

# word_units (v1.2.7): заглушка широкого глифа принадлежит СЛОВУ — «a中b» = одно
# слово на 4 ячейках (0..3), а не два слова с разрывом на заглушке.
units = word_units(line0)
check("«a中b»: одно слово на 4 ячейках [(0, 3)]", units == [(0, 3)], repr(units))

# Разделитель-пробел вокруг CJK: «中 a» — два слова (заглушка в первом).
scr5 = TerminalScreen(columns=10, lines=3)
scr5.feed("中 a".encode("utf-8"))
rows5, _cx5, _cy5, _h5 = scr5.snapshot()
units5 = word_units(rows5[0])
check("«中 a»: два слова [(0, 1), (3, 3)]", units5 == [(0, 1), (3, 3)], repr(units5))

finish()
