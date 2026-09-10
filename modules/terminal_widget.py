# -*- coding: utf-8 -*-
"""v1.0RC1: TerminalWidget — посячейный холст терминала (QWidget + QPainter).

Заменяет HTML-рендер (QPlainTextEdit + TerminalScreen.render(), deprecated с v1.0RC1):
paintEvent рисует **runs** одинакового форматирования (не по-символьные drawText),
цвета — через resolve_color() из modules/terminal_screen.py (TERMINAL.md §5.1,
проверенные факты pyte 0.8.2: brown/brightbrown, hex-passthrough 256-цветов и
truecolor, опечатка 'bfightmagenta').

Курсор — блок через свап (TERMINAL.md §3.13): залить ячейку цветом курсора +
перерисовать глиф цветом фона (НЕ XOR-инверсия — на цветных ячейках даёт
«мыльные» оттенки); уважает screen.cursor.hidden (ESC[?25l/h — vim прячет курсор).
Широкие глифы (CJK): двойная ширина, «заглушка» (data == '') пропускается
(TERMINAL.md факт №11; v1.2.9: полный wcwidth(3) — та же таблица пакета wcwidth,
что сам pyte 0.8.2 использует для раскладки сетки, вместо эвристики
east_asian_width W/F из v1.0RC1).

Кэш форматов (fg,bg,атрибуты) → (QPen,QBrush,QFont) с ограничением размера
(512 записей, clear при переполнении — TERMINAL.md §5.1); reverse сводится к
свапу fg/bg ДО ключа, поэтому визуально одинаковые ячейки попадают в один кэш.

v1.0RC2 — клавиатура (полная таблица) + выделение мышью/копирование:
* клавиатура: F1–F12 (xterm-последовательности), PageUp/PageDown, Home/End/Delete
  (семантика старого SSHTerminalTextEdit сохранена), явные Ctrl+C→\\x03 /
  Ctrl+D→\\x04 при отсутствии выделения, bracketed paste Ctrl+V (перенос из v0.9.4),
  guard на AltModifier (AltGr не уходит как управляющие коды — TERMINAL.md §3.12);
* выделение: ЛКМ press/move/release → якорь/конец в (row, col); чистая функция
  selection_cells() (TERMINAL.md §5.2, regression на ошибку черновика №4 —
  координаты ВСЕГДА (row, col), а не (col, row)); Ctrl+C при выделении копирует
  в буфер обмена (семантика v0.9.3 сохранена), без выделения — SIGINT;
* подсветка — полупрозрачный оверлей поверх выбранных ячеек (глифы видны).

Потоки: paintEvent и snapshot() — GUI-поток; feed() из SSH-потока под lock'ом
v1.0RC3 — скроллбэк + dirty-рендер:
* колесо мыши и Ctrl+Shift+PageUp/PageDown → tscreen.scroll_up()/scroll_down()
  (pyte.HistoryScreen, TERMINAL.md §5.4); перехват «Ctrl+Shift → скролл» стоит
  ДО проверки голых PageUp/PageDown — те остаются форвардом в shell
  (\\x1b[5~/\\x1b[6~, семантика v1.0RC2: пейджинг less/man, конвенция Windows
  Terminal/GNOME/xterm); авто-возврат к live-строке при новом выводе — встроен
  в pyte (before_event) и требует только update() из _on_output;
* мигание курсора — свой QTimer (BLINK_INTERVAL_MS), останавливается при
  скрытом окне (hideEvent); холст перерисовывается по dirty-флагу:
  _on_output → widget.update() напрямую, 30 FPS-таймер не нужен.

Потоки: paintEvent и snapshot() — GUI-поток; feed() из SSH-потока под lock'ом
v1.1.2RC3 — стрелки по состоянию DECCKM (AUDIT U3: «в mc не работают стрелки»):
стрелки и Home/End шлются в SS3 (\x1bOA…\x1bOD, \x1bOH/\x1bOF), когда приложение
включило Application Cursor Keys Mode (smkx \x1b[?1h — mc/vim/htop делают это
при запуске), и в CSI (\x1b[A…\x1b[D, \x1b[H/\x1b[F) в обычном режиме. Состояние
читается с tscreen.application_cursor_keys() (pyte 0.8.2: DECCKM = 32 в
screen.mode — приватные режимы хранятся со сдвигом <<5; каноническая проверка
«1 in screen.mode» не работает). + колесо: параметр wheel_mode из конфига
terminal_wheel — "scrollback" (дефолт) | "off" (колесо не скроллит локальный
скроллбэк, event.ignore); v1.2.13: если TUI включил mouse tracking (DECSET
1000/1002/1003), колесо уходит в PTY как SGR/X10-отчёт — passthrough приоритетнее "off".

v1.2.7 — выделение двойным/тройным кликом + контекстное меню (ПКМ):
* двойной клик — выделение СЛОВА на строке (word_units() — чистая функция:
  слово = максимальный прогон небелых ячеек; заглушка широкого CJK-глифа
  принадлежит слову), тройной — вся СТРОКА (0..columns-1); клики считает сам
  виджет (ячейка + интервал DOUBLE_CLICK_MS) — QMouseEvent в PySide6 не несёт
  click-count, и синтетические события тестов его не имеют; drag после двойного/
  тройного клика расширяет выделение от ДАЛЬНОГО конца слова/строки
  (_click_sel_end), отпускание ЛКМ при count>=2 НЕ затирает выделение;
* ПКМ — контекстное меню (contextMenuEvent → _build_context_menu(), тестовый
  шов): Копировать (enabled только при выделении, тот же путь copy_selection()),
  Вставить в PTY (тот же bracketed paste, что Ctrl+V: единый блок
  \x1b[200~…\x1b[201~ через _send — мультинабор дублирует как и клавишу),
  Выделить всё (select_all() — вся видимая сетка); подписи — i18n-ключи
  terminal.menu.* × en/ru/zh (get_translator, кэш по паттерну ssh_terminal.py).

v1.2.12 — альтернативный экран (PYTE82_AUDIT.md пачка B): пока tscreen.in_alt_screen()
(TUI владеет сеткой — vim/htop/mc/less), колесо мыши и Ctrl+Shift+PageUp/PageDown
НЕ скроллят историю (гейт no-op).

v1.2.13 — колесо в полноэкранном TUI (PYTE82_AUDIT.md пачка C): если
tscreen.mouse_tracking() (DECSET 1000/1002/1003) — колесо уходит в PTY как
xterm mouse-отчёт: SGR (\x1b[<64;{col};{row}M, при 1006; up=64/down=65) или X10
(\x1b[M + [96|97, 32+col, 32+row]; координаты зажаты в сетку и в лимит протокола
223). Отправка — НАПРЯМУЮ terminal_thread.send_data(), НЕ через _send(): координаты
сессионно-локальны, мультинабор их broadcast'ить не должен. Alt без tracking
остаётся no-op (v1.2.12); passthrough приоритетнее wheel_mode="off".

Потоки: paintEvent и snapshot() — GUI-поток; feed() из SSH-потока под lock'ом
TerminalScreen — race посреди кадра исключён.
"""

import math
import time

# v1.2.9 (ROADMAP «Гигиена терминала»): полный wcwidth(3) — ТА ЖЕ библиотека, что
# использует сам pyte 0.8.2 для раскладки сетки (pyte.screens: `from wcwidth import
# wcwidth`); жёсткая зависимость pyte, поэтому на месте всегда, когда есть pyte.
try:
    from wcwidth import wcwidth as _wcwidth
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Для терминального холста требуется пакет 'wcwidth' (устанавливается вместе с pyte)"
    ) from e

try:
    from .terminal_screen import PALETTES, resolve_color
except ImportError:
    from modules.terminal_screen import PALETTES, resolve_color

# v1.2.3 (ROADMAP v1.2.3): мультинабор — хаб broadcast'а ввода во все открытые сессии.
# Цикла импортов нет: multi_input не знает о terminal_widget.
try:
    from .multi_input import get_hub as _get_multi_hub
except ImportError:
    from modules.multi_input import get_hub as _get_multi_hub

# v1.2.4-fix (диагностика мультинабора): логгер приложения (лениво, паттерн
# get_translator) — DEBUG-строка на каждый broadcast в _send. Без setup_logging
# записи никуда не уходят (namespace 'sshmap' без хендлеров) — безопасно для тестов.
_log_cache = {"log": None}


def _get_app_log():
    if _log_cache["log"] is None:
        try:
            try:
                from .logger import get_logger as _gl
            except ImportError:
                from modules.logger import get_logger as _gl
            _log_cache["log"] = _gl("modules.terminal_widget")
        except Exception:
            _log_cache["log"] = False  # логгер недоступен — дальше молчим
    return _log_cache["log"] or None


# v1.2.7: i18n для контекстного меню (кэш по паттерну get_translator в
# modules/ssh_terminal.py — модуль на горячем пути, импорт i18n ленивый).
_t_cache = None


def get_translator():
    """Безопасный i18n-хелпер: кэшированный t() или fallback "[key]".

    Ключи terminal.menu.* используются ТОЛЬКО в _build_context_menu(); до v1.2.7
    модуль i18n не импортировал вовсе."""
    global _t_cache
    if _t_cache is None:
        try:
            from i18n import t as _func
            _t_cache = lambda key, **kwargs: (
                _func(key, **kwargs) if kwargs else _func(key)
            )
        except Exception:
            _t_cache = lambda k, **kw: f"[{k}]"
    return _t_cache

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPen,
)
from PySide6.QtWidgets import QApplication, QMenu, QSizePolicy, QWidget


def _fmt_key(ch):
    """Ключ форматирования ячейки — сырые атрибуты pyte Char (без палитры).

    Поле курсива в pyte 0.8.2 называется **italics** (не italic — TERMINAL.md
    факт №1, ошибка черновика №1). run — максимальная последовательность ячеек
    с одинаковым ключом; resolve_color() — чистая функция от (fg,bg,палитра),
    поэтому внутри run цвета консистентны.
    """
    return (ch.fg, ch.bg, bool(ch.bold), bool(ch.italics),
            bool(ch.underscore), bool(ch.strikethrough), bool(ch.reverse))


def char_width(data: str) -> int:
    """Полная ширина символа по wcwidth(3): 0 — нулевая (составные/контрольные),
    1 — узкий, 2 — широкий (CJK/Fullwidth).

    v1.2.9 (ROADMAP «Гигиена терминала»): заменяет эвристику east_asian_width W/F
    из v1.0RC1 — known limitation v1.0 закрыт. Используется ТА ЖЕ библиотека
    `wcwidth`, что и сам pyte 0.8.2 (pyte.screens: `from wcwidth import wcwidth`)
    для раскладки сетки, поэтому классификация «широкий/узкий» холста всегда
    совпадает с тем, как pyte размещает глифы в ячейках (+ заглушка после широкого).
    Пустая строка (заглушка) → 0; не-печатные контрольные (-1) клампятся в 0.
    data — содержимое ОДНОЙ ячейки: обычно один символ, но pyte NFC-сливает
    составные знаки в предыдущую ячейку (мульти-символьный графемный кластер),
    поэтому ширина = сумма по символам (ровно как посимвольный draw() pyte);
    в сетке это всегда 0/1/2.
    """
    if not data:
        return 0
    total = 0
    for ch in data:
        w = _wcwidth(ch)
        total += 0 if w < 0 else w
    return total


def is_wide_char(data: str) -> bool:
    """Широкий ли глиф (двойная ширина, CJK/Fullwidth).

    v1.2.9: полный wcwidth(3) через библиотеку `wcwidth` (та же, что у pyte 0.8.2),
    вместо эвристики east_asian_width W/F (v1.0RC1). Важно: в pyte 0.8.2 сам глиф
    хранится с len(data)==1 («широкий» по data не определить) — широкой является
    СЛЕДУЮЩАЯ ячейка-«заглушка» с data==''; её пропускает split_row_runs.
    """
    return char_width(data) == 2


def split_row_runs(row):
    """Разбивает строку на runs одинакового форматирования (чистая функция).

    row — список pyte Char длиной columns. Возвращает список кортежей
    (x, text, is_wide): x — ячейка начала run, text — склеенные символы,
    is_wide=True — одиночный широкий глиф (рисуется на двойную ширину; следующая
    заглушка пропускается). Заглушки (data == '') не входят ни в один run.

    Юнит-тестится без GUI (tests/test_terminal_colors.py) — regression на ошибки
    черновика №13/№14 из TERMINAL.md §3 (XOR-курсор, наложение CJK-глифов).
    """
    runs = []
    n = len(row)
    x = 0
    while x < n:
        ch = row[x]
        if not ch.data:            # заглушка после широкого глифа — пропуск
            x += 1
            continue
        if is_wide_char(ch.data):
            runs.append((x, ch.data, True))
            x += 2                 # глиф + заглушка (в конце строки — просто выход)
            continue
        key = _fmt_key(ch)
        x2 = x + 1
        while x2 < n and row[x2].data and not is_wide_char(row[x2].data) \
                and _fmt_key(row[x2]) == key:
            x2 += 1
        runs.append((x, "".join(c.data for c in row[x:x2]), False))
        x = x2
    return runs


def selection_cells(start, end, columns):
    """Ячейки прямоугольного выделения в координатах (row, col) (TERMINAL.md §5.2).

    start/end — (row, col) начала и конца выделения, ПОРЯДОК НЕ ВАЖЕН (drag в любую
    сторону); columns — ширина сетки (средние строки выделения занимают всю ширину
    0..columns-1). Возвращает список (row, col) в порядке чтения: по строкам сверху
    вниз, внутри строки слева направо. Чистая функция — юнит-тестится без GUI
    (tests/test_terminal_input.py).

    Координаты ВСЕГДА (row, col): сравнение кортежей = ПОСТРОЧНЫЙ порядок. Regression
    на ошибку черновика №4 (TERMINAL.md §3): там хранили (col, row) и сравнивали
    кортежно — колоночный порядок, любое выделение на 2+ строки подсвечивало/
    копировало НЕ ТЕ ячейки. Колонны зажаты в [0, columns-1] (строки — ответственность
    вызывающего: мышь клемпит через _cell_at).
    """
    if columns <= 0:
        return []
    (r1, c1), (r2, c2) = sorted((start, end))
    c1 = max(0, min(int(c1), columns - 1))
    c2 = max(0, min(int(c2), columns - 1))
    cells = []
    for r in range(r1, r2 + 1):
        lo = c1 if r == r1 else 0
        hi = c2 if r == r2 else columns - 1
        cells.extend((r, c) for c in range(lo, hi + 1))
    return cells


def word_units(row_chars):
    """Диапазоны слов строки: list[(start_col, end_col)] включительно (v1.2.7).

    row_chars — список pyte Char длиной columns (одна строка snapshot'а).
    Слово — максимальный прогон НЕБЕЛЫХ ячеек: разделитель только пробельные
    символы (data.isspace()); пунктуация к слову ПРИНАДЛЕЖИТ ("foo,bar" — одно
    слово, как в xterm/Windows Terminal). Заглушка широкого CJK-глифа
    (data == '') принадлежит СЛОВОУ: в pyte 0.8.2 широкий глиф занимает ячейку
    + следующую заглушку (TERMINAL.md факт №11), поэтому "a中b" — одно слово
    на 4 ячейках, а не два. Чистая функция — юнит-тестится без GUI
    (tests/test_terminal_selection_menu.py).
    """
    n = len(row_chars)
    units = []
    x = 0
    while x < n:
        d = row_chars[x].data
        if not d or d.isspace():      # пробел/пусто — не начало слова
            x += 1
            continue
        start = x
        x += 1
        while x < n:
            d2 = row_chars[x].data
            if d2 == "":              # заглушка после широкого глифа — в слове
                x += 1
                continue
            if not d2.isspace():
                x += 1
                continue
            break                     # пробел — конец слова
        units.append((start, x - 1))
    return units


# xterm-последовательности F1–F12 (таблица из черновика TERMINAL.md §6/фаза 1):
# F1–F4 — SS3 (\x1bOP…\x1bOS), F5–F12 — CSI (\x1b[15~ … \x1b[24~).
_F_KEY_SEQUENCES = {
    Qt.Key.Key_F1: b"\x1bOP",
    Qt.Key.Key_F2: b"\x1bOQ",
    Qt.Key.Key_F3: b"\x1bOR",
    Qt.Key.Key_F4: b"\x1bOS",
    Qt.Key.Key_F5: b"\x1b[15~",
    Qt.Key.Key_F6: b"\x1b[17~",
    Qt.Key.Key_F7: b"\x1b[18~",
    Qt.Key.Key_F8: b"\x1b[19~",
    Qt.Key.Key_F9: b"\x1b[20~",
    Qt.Key.Key_F10: b"\x1b[21~",
    Qt.Key.Key_F11: b"\x1b[23~",
    Qt.Key.Key_F12: b"\x1b[24~",
}


class TerminalWidget(QWidget):
    """Посячейный холст pyte-экрана (v1.0RC1; v1.0RC2 — клавиатура + выделение;
    v1.0RC3 — скроллбэк колесом/Ctrl+Shift+PgUp/PgDn + мигание курсора;
    v1.2.3 — мультинабор: broadcast ввода во все открытые сессии;
    v1.2.7 — двойной/тройной клик (слово/строка) + контекстное меню ПКМ;
    v1.2.13 — колесо в TUI: SGR/X10 passthrough при включённом mouse tracking;
    v1.2.9-fix — Tab/Shift+Tab перехватываются в event(): focus-change-механизм
    Qt 6 не передаёт их keyPressEvent, без перехвата фокус уходил из терминала
    в кнопки окна и \\t не доходил до shell).

    tscreen — TerminalScreen (pyte.HistoryScreen + lock); terminal_thread — объект с
    send_data(bytes) (SSHTerminalThread; None — ввод отключён, рендер и скроллбэк
    работают). multi_hub — хаб мультинабора (modules/multi_input.py): None — модульный
    хаб по умолчанию (get_hub()); явный экземпляр — тестовый шов изоляции.
    """

    FORMAT_CACHE_LIMIT = 512      # лимит кэша форматов (TERMINAL.md §5.1)
    CURSOR_COLOR = "#e2e8f0"      # блок-курсор: цвет default-текста (классический вид)
    SELECTION_COLOR = (59, 130, 246, 90)   # v1.0RC2: оверлей выделения (RGBA, alpha≈35%)
    BLINK_INTERVAL_MS = 530       # v1.0RC3: период мигания курсора (ROADMAP задача 8)
    DOUBLE_CLICK_MS = 500         # v1.2.7: интервал двойного/тройного клика (тест-хук)

    def __init__(self, tscreen, terminal_thread=None, parent=None,
                 palette_name="default", format_cache_limit=FORMAT_CACHE_LIMIT,
                 wheel_mode="scrollback", multi_hub=None):
        super().__init__(parent)
        self.tscreen = tscreen
        self.terminal_thread = terminal_thread
        # v1.2.3 (ROADMAP задача 1): хаб мультинабора — None = модульный по умолчанию;
        # явный экземпляр — тестовый шов (изоляция от singleton'а приложения).
        self._multi_hub = multi_hub
        # v1.1.2RC3 (AUDIT U3): режим колеса из конфига terminal_wheel —
        # "scrollback" (дефолт, поведение v1.0RC3: колесо = локальный скроллбэк)
        # | "off" (колесо не перехватывается для скроллбэка). Неизвестное значение → дефолт.
        # v1.2.13: если TUI включил mouse tracking (DECSET 1000/1002/1003), колесо
        # уходит в PTY как SGR/X10-отчёт — passthrough приоритетнее "off".
        self._wheel_mode = wheel_mode if wheel_mode in ("scrollback", "off") else "scrollback"
        self._palette_name = palette_name if palette_name in PALETTES else "default"
        self._palette = dict(PALETTES[self._palette_name])
        self._format_cache_limit = int(format_cache_limit)
        self._format_cache = {}   # (fg,bg,bold,italics,underscore,strikethrough) → (QPen,QBrush,QFont)

        self._bg_color = QColor(self._palette["default_bg"])
        self._cursor_color = QColor(self.CURSOR_COLOR)
        self._selection_color = QColor(*self.SELECTION_COLOR)

        # v1.0RC2: выделение мышью — якорь (press) и активный конец (move/release),
        # координаты ВСЕГДА (row, col); None — выделения нет.
        self._sel_anchor = None
        self._sel_active = None

        # v1.2.7: учёт двойного/тройного клика — сам виджет (QMouseEvent в PySide6
        # не несёт click-count; синтетические события тестов его тоже не имеют):
        # _click_count растёт при press в той же ячейке внутри DOUBLE_CLICK_MS,
        # иначе сбрасывается на 1. _click_sel_end — «зафиксированный» конец для
        # drag'а после двойного/тройного клика (дальний конец слова/строки);
        # None — обычный press/drag v1.0RC2.
        self._click_count = 0
        self._last_click_cell = None
        self._last_click_ms = 0.0
        self._click_sel_end = None

        # v1.0RC3: мигание курсора — свой QTimer (ROADMAP задача 8): стартует в
        # showEvent, останавливается в hideEvent (скрытое окно не мигает).
        # _cursor_visible=True по умолчанию: никогда не показанный виджет
        # (offscreen-тесты) всегда рисует курсор.
        self._cursor_visible = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(self.BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._toggle_cursor_blink)

        # AUDIT v0.7.2 (низкая #18): системный моноширинный шрифт (как в HTML-пути),
        # point size 10 — дефолты = текущее поведение.
        self._font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._font.setPointSize(10)
        self._update_metrics()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Тест-хук: статистика последнего paint (runs vs по-символьные drawText)
        self.last_paint_stats = {"rows": 0, "runs": 0, "draw_text_calls": 0}

    # ── метрики/палитра/шрифт ─────────────────────────────
    def _update_metrics(self):
        fm = QFontMetricsF(self._font)
        self._cell_w = max(1, int(math.ceil(fm.horizontalAdvance("M"))))
        self._cell_h = max(1, int(math.ceil(fm.height())))
        self._ascent = int(math.ceil(fm.ascent()))

    @property
    def cell_size(self):
        """(ширина, высота) ячейки в пикселях."""
        return self._cell_w, self._cell_h

    def set_palette(self, name):
        """Смена палитры (v1.0: ключ terminal_palette из конфига). False — неизвестная."""
        if name not in PALETTES:
            return False
        self._palette_name = name
        self._palette = dict(PALETTES[name])
        self._bg_color = QColor(self._palette["default_bg"])
        self._format_cache.clear()
        self.update()
        return True

    def set_font(self, family="", size=10):
        """Смена шрифта (v1.0: ключи terminal_font/terminal_font_size из конфига)."""
        f = QFont(self._font)
        if family:
            f.setFamily(family)
        f.setPointSize(int(size))
        self._font = f
        self._update_metrics()
        self._format_cache.clear()
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._cell_w * 80, self._cell_h * 24)

    # ── кэш форматов (TERMINAL.md §5.1) ───────────────────
    def _format_for(self, fg_hex, bg_hex, bold, italics, underscore, strikethrough):
        """(fg,bg,атрибуты) → (QPen,QBrush,QFont); кэш с ограничением размера.

        reverse НЕ входит в ключ: он уже сведён к свапу fg/bg до вызова —
        визуально одинаковые ячейки попадают в одну запись кэша.
        """
        key = (fg_hex, bg_hex, bold, italics, underscore, strikethrough)
        fmt = self._format_cache.get(key)
        if fmt is None:
            if len(self._format_cache) >= self._format_cache_limit:
                self._format_cache.clear()
            pen = QPen(QColor(fg_hex))
            brush = QBrush(QColor(bg_hex))
            font = QFont(self._font)
            font.setBold(bold)
            font.setItalic(italics)
            font.setUnderline(underscore)
            font.setStrikeOut(strikethrough)
            fmt = (pen, brush, font)
            self._format_cache[key] = fmt
        return fmt

    def _resolved_colors(self, ch):
        """pyte Char → конкретные hex (fg, bg); reverse — свап ПОСЛЕ резолва."""
        pal = self._palette
        fg = resolve_color(ch.fg, pal, pal["default_fg"])
        bg = resolve_color(ch.bg, pal, pal["default_bg"])
        if ch.reverse:
            fg, bg = bg, fg
        return fg, bg

    # ── рендер: runs вместо по-символьных drawText ────────
    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._paint(painter)
        except Exception as e:
            # Вывод SSH — произвольный поток; рендер не должен ронять окно.
            try:
                from modules.logger import get_logger
                get_logger("modules.terminal_widget").warning(f"paint failed: {e}")
            except Exception:
                pass
        finally:
            painter.end()

    def _paint(self, painter):
        rows, cx, cy, hidden = self.tscreen.snapshot()
        stats = {"rows": 0, "runs": 0, "draw_text_calls": 0, "selection_cells": 0}

        # WA_OpaquePaintEvent: полный фон (как в TERMINAL.md §5.3)
        painter.fillRect(self.rect(), QBrush(self._bg_color))

        for y, row in enumerate(rows):
            runs = split_row_runs(row)
            stats["runs"] += len(runs)
            for x, text, is_wide in runs:
                ch0 = row[x]
                fg, bg = self._resolved_colors(ch0)
                has_ink = bool(text.strip())
                # v1.2.10rc3 (косметический баг аудита): whitespace-only run без чернил —
                # fillRect всё равно нужен, если резолвлённый bg ≠ базовой заливке: TUI-приложение
                # может явно красить пустую строку пробелами под своим цветом (область
                # просмотрщика mc/mcedit — в настоящем xterm она однородно серая; в сетке pyte
                # такие ячейки несут bg=<цвет>). Старая предпосылка «фон уже залит» была верна
                # только для пробелов с фоном по умолчанию.
                if not has_ink and bg == self._palette["default_bg"]:
                    continue  # пробелы с дефолтным фоном — базовая заливка уже покрывает
                pen, brush, font = self._format_for(
                    fg, bg, bool(ch0.bold), bool(ch0.italics),
                    bool(ch0.underscore), bool(ch0.strikethrough))
                painter.setFont(font)
                painter.setPen(pen)
                cell_x, cell_y = x * self._cell_w, y * self._cell_h
                # широкие глифы — двойная ширина (шрифт сам рисует глиф широким);
                # заглушка уже пропущена в split_row_runs
                run_cells = 2 if is_wide else len(text)
                painter.fillRect(cell_x, cell_y, run_cells * self._cell_w,
                                 self._cell_h, brush)
                if has_ink:
                    painter.drawText(cell_x, cell_y + self._ascent, text)
                    stats["draw_text_calls"] += 1
            stats["rows"] += 1

        # v1.0RC2: выделение — полупрозрачный оверлей поверх выбранных ячеек.
        # Рисуется ПОСЛЕ текста, поэтому глифы видны сквозь alpha (как в классических
        # терминалах). selection_cells() даёт на строку ОДИН непрерывный диапазон
        # колонок — по одному fillRect на строку выделения.
        sel = self._selected_cells()
        if sel:
            by_row = {}
            for r, c in sel:
                by_row.setdefault(r, []).append(c)
            painter.setPen(Qt.PenStyle.NoPen)
            brush_sel = QBrush(self._selection_color)
            for r, cs in by_row.items():
                if 0 <= r < len(rows):
                    lo, hi = min(cs), max(cs)
                    painter.fillRect(lo * self._cell_w, r * self._cell_h,
                                     (hi - lo + 1) * self._cell_w, self._cell_h,
                                     brush_sel)
            stats["selection_cells"] = len(sel)

        # Блок-курсор через свап (TERMINAL.md §3.13): залить ячейку цветом курсора
        # + перерисовать глиф цветом фона; НЕ рисуем при screen.cursor.hidden
        # (ESC[?25l/h — vim прячет курсор, факт №8) и в «невидимой» фазе мигания
        # (v1.0RC3). При скролле вверх в историю pyte сам прячет курсор
        # (after_event: hidden = not (position == size and DECTCEM)).
        if (not hidden and self._cursor_visible and rows
                and 0 <= cy < len(rows) and 0 <= cx < len(rows[cy])):
            ch = rows[cy][cx]
            cell_x, cell_y = cx * self._cell_w, cy * self._cell_h
            painter.fillRect(cell_x, cell_y, self._cell_w, self._cell_h,
                             QBrush(self._cursor_color))
            if ch.data and ch.data != " ":
                fg, bg = self._resolved_colors(ch)
                _, _, font = self._format_for(
                    fg, bg, bool(ch.bold), bool(ch.italics),
                    bool(ch.underscore), bool(ch.strikethrough))
                painter.setFont(font)
                painter.setPen(QPen(self._bg_color))  # глиф — цветом фона
                painter.drawText(cell_x, cell_y + self._ascent, ch.data)

        self.last_paint_stats = stats

    def visible_text(self):
        """Текст видимой сетки (для тестов/отладки); заглушки дают ''."""
        rows, _cx, _cy, _hidden = self.tscreen.snapshot()
        return "\n".join("".join(ch.data for ch in row) for row in rows)

    # ── v1.2.9-fix: Tab/Shift+Tab — Qt 6 перехватывает ДО keyPressEvent ─────
    def event(self, e):
        """v1.2.9-fix (баг с v1.0RC2, пойман в работе): Tab/Shift+Tab уходили
        из терминала в кнопки/табы окна; \\t не доходил до shell — bash-автозаполнение
        не срабатывало, в mc панели не переключались.

        Механизм (документация Qt 6, QWidget): «The Tab and Shift+Tab keys are only
        passed to the widget if they are not used by the focus-change mechanisms. To
        force those keys to be processed by your widget, you must reimplement
        QWidget::event()» — голые Tab/Shift+Tab к keyPressEvent НЕ доходят: Qt сам
        гоняет фокус по цепочке виджетов и помечает событие обработанным. Ветка
        Key_Tab в keyPressEvent (v1.0RC2) работала только при прямых вызовах
        (тесты) — реальные события её обходили, поэтому баг прожил с v1.0RC2 по
        v1.2.9 и сьютом не ловился (тесты звали keyPressEvent напрямую).

        Перехват: Tab → \\t, Shift+Tab → \\x1b[Z (xterm) + accept — фокус остаётся
        на терминале. Ctrl/Meta+Tab НЕ перехватывается (fall-through в
        super().event() → keyPressEvent — прежняя семантика); terminal_thread=None
        — тоже не перехватывается (ввод отключён = guard в начале keyPressEvent).
        Все остальные события проходят через super().event(e) без изменений."""
        if e.type() == QEvent.Type.KeyPress:
            key = e.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                mod = e.modifiers()
                if not (mod & Qt.KeyboardModifier.ControlModifier
                        or mod & Qt.KeyboardModifier.MetaModifier) \
                        and self.terminal_thread is not None:
                    self._send(b"\t" if key == Qt.Key.Key_Tab else b"\x1b[Z")
                    e.accept()
                    return True
        return super().event(e)

    # ── клавиатура: полная таблица v1.0RC2 ────────────────
    def keyPressEvent(self, event):
        """Полная таблица клавиатуры (v1.0RC2, ROADMAP задача 4; v1.0RC3 — скроллбэк).

        * F1–F12 — xterm-последовательности (_F_KEY_SEQUENCES);
        * Ctrl+Shift+PageUp/PageDown → СКОЛЛБЭК (v1.0RC3, TERMINAL.md §5.4): перехват
          стоит ДО проверки голых PageUp/PageDown — иначе fall-through из Ctrl-ветки
          шлёт \\x1b[5~/\\x1b[6~ в shell (ловушка из ROADMAP v1.0RC3 задача 7);
          v1.2.12: на альтернативном экране (in_alt_screen) — no-op;
        * голые PageUp/PageDown → \\x1b[5~/\\x1b[6~ — форвард в shell (семантика
          v1.0RC2 сохраняется: пейджинг less/man работает, конвенция Windows
          Terminal/GNOME/xterm);
        * стрелки Left/Right/Up/Down и Home/End — по состоянию DECCKM (v1.1.2RC3,
          AUDIT U3): обычный режим → CSI (\\x1b[D/C/A/B, \\x1b[H/\\x1b[F), Application
          Cursor Keys Mode (smkx \\x1b[?1h — mc/vim/htop) → SS3 (\\x1bOD/OC/OA/OB,
          \\x1bOH/\\x1bOF); выбор — _cursor_key_seq() от tscreen.application_cursor_keys();
        * Home/End/Delete — базовая семантика старого SSHTerminalTextEdit
          (CSI \\x1b[H / \\x1b[F / \\x1b[3~ — «семантика текущего кода сохраняется»;
          Delete/PageUp/PageDown DECCKM не зависят);
        * Ctrl+C: при выделении — копирование в буфер (semantics v0.9.3), без
          выделения — \\x03 (SIGINT; Acceptance: «Ctrl+C роняет top»);
        * Ctrl+D → \\x04, Ctrl+Z → \\x1a, Ctrl+V — bracketed paste (v0.9.4);
        * Tab → \\t / Shift+Tab → \\x1b[Z (v1.2.9-fix): в реальных событиях перехватываются
          РАНЬШЕ — в event() (focus-change-механизм Qt 6 не передаёт их keyPressEvent;
          без этого фокус уходил в кнопки окна, а \\t не доходил до shell);
        * AltGr-guard (TERMINAL.md §3.12): Ctrl+Alt-комбинации (на Windows
          AltGr = Ctrl+Alt) НЕ уходят как управляющие коды — ignore;
        * F12 в режиме мультинабора (v1.2.3, ROADMAP задача 3) — ВЫХОД из режима, а не
          клавиша shell: RC2-маппинг F12→\\x1b[24~ приостанавливается (клавиша не
          доходит до shell); режим выключен → F12 работает как раньше (\\x1b[24~).
        """
        if self.terminal_thread is None:
            event.ignore()
            return
        key = event.key()
        mod = event.modifiers()

        if mod & Qt.KeyboardModifier.ControlModifier:
            # AltGr-guard (TERMINAL.md §3.12): Ctrl+Alt-комбинации (на Windows
            # AltGr = Ctrl+Alt) не должны уходить как управляющие коды.
            if mod & Qt.KeyboardModifier.AltModifier:
                event.ignore()
                return
            # v1.0RC3: Ctrl+Shift+PageUp/PageDown → скроллбэк (TERMINAL.md §5.4).
            # Перехват ДО голых PageUp/PageDown ниже — без него fall-through шлёт
            # \x1b[5~/\x1b[6~ в shell (ловушка ROADMAP v1.0RC3 задача 7).
            if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) \
                    and mod & Qt.KeyboardModifier.ShiftModifier:
                # v1.2.12: alt-экран (TUI владеет сеткой) — no-op; колесо в TUI
                # уходит только при mouse tracking (v1.2.13), клавиши остаются локальными.
                if self.tscreen.in_alt_screen():
                    return
                if key == Qt.Key.Key_PageUp:
                    self.scroll_page_up()
                else:
                    self.scroll_page_down()
                return
            if key == Qt.Key.Key_C:
                # v0.9.3 semantics (сохранены): Ctrl+C копирует при выделении,
                # без выделения — SIGINT.
                if self.has_selection():
                    self.copy_selection()
                else:
                    self._send(b"\x03")
                return
            if key == Qt.Key.Key_V:
                self._bracketed_paste()
                return
            if key == Qt.Key.Key_D:
                self._send(b"\x04")
                return
            if key == Qt.Key.Key_Z:
                self._send(b"\x1a")
                return

        # v1.2.3 (ROADMAP задача 3): мультинабор — F12 = ВЫХОД из режима, не Esc
        # (Esc уходит в shell как \x1b!). При включённом режиме RC2-маппинг
        # F12→\x1b[24~ приостанавливается: клавиша не доходит до shell, режим
        # выключается. Режим выключен → fall-through на таблицу F1–F12 как в v1.0RC2.
        if key == Qt.Key.Key_F12 and self._multi_active():
            self._multi_exit()
            event.accept()
            return

        seq = _F_KEY_SEQUENCES.get(key)      # F1–F12 (полная таблица, v1.0RC2)
        if seq is not None:
            self._send(seq)
            return
        if key == Qt.Key.Key_PageUp:
            self._send(b"\x1b[5~")
            return
        if key == Qt.Key.Key_PageDown:
            self._send(b"\x1b[6~")
            return
        if key == Qt.Key.Key_Home:
            # CSI H в обычном режиме (как в SSHTerminalTextEdit v0.8); в DECCKM —
            # SS3 H (\x1bOH), семантика xterm (AUDIT U3).
            self._send(self._cursor_key_seq(b"H"))
            return
        if key == Qt.Key.Key_End:
            self._send(self._cursor_key_seq(b"F"))   # CSI F / SS3 F по DECCKM
            return
        if key == Qt.Key.Key_Delete:
            self._send(b"\x1b[3~")
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._send(b"\r")
            return
        if key == Qt.Key.Key_Backspace:
            self._send(b"\x7f")
            return
        # Tab/Shift+Tab: в РЕАЛЬНЫХ событиях перехватываются раньше — в event()
        # (focus-change-механизм Qt 6 не отдаёт их keyPressEvent; см. event()).
        # Ветки сохранены для прямых вызовов keyPressEvent (тестовый шов).
        if key == Qt.Key.Key_Tab:
            self._send(b"\t")
            return
        if key == Qt.Key.Key_Backtab:
            self._send(b"\x1b[Z")   # xterm Shift+Tab (mc, reverse-completion в bash)
            return
        if key == Qt.Key.Key_Escape:
            self._send(b"\x1b")
            return
        # Стрелки — по состоянию DECCKM (AUDIT U3): CSI \x1b[D/C/A/B в обычном
        # режиме, SS3 \x1bOD/OC/OA/OB, когда mc/vim/htop включили Application
        # Cursor Keys Mode (smkx \x1b[?1h). Без этого в mc стрелки «не работают»
        # (приложение ждёт SS3), а в bash под ним — листают историю.
        if key == Qt.Key.Key_Left:
            self._send(self._cursor_key_seq(b"D"))
            return
        if key == Qt.Key.Key_Right:
            self._send(self._cursor_key_seq(b"C"))
            return
        if key == Qt.Key.Key_Up:
            self._send(self._cursor_key_seq(b"A"))
            return
        if key == Qt.Key.Key_Down:
            self._send(self._cursor_key_seq(b"B"))
            return

        text = event.text()
        if text:
            self._send(text.encode("utf-8"))
            return
        event.ignore()

    def _cursor_key_seq(self, suffix: bytes) -> bytes:
        """Последовательность курсорной клавиши по состоянию DECCKM (AUDIT U3).

        suffix — байт-суффикс («A»/«B»/«C»/«D» у стрелок, «H»/«F» у Home/End):
        обычный режим → CSI (\x1b[A…); Application Cursor Keys Mode (DECCKM,
        приватный режим 1 — mc/vim/htop шлют smkx \x1b[?1h при запуске) → SS3
        (\x1bOA…). Состояние — tscreen.application_cursor_keys(); там же
        зафиксирован проверенный факт pyte 0.8.2: DECCKM хранится в screen.mode
        как 32 (приватные режимы со сдвигом <<5), а не как 1.
        """
        if self.tscreen.application_cursor_keys():
            return b"\x1bO" + suffix
        return b"\x1b[" + suffix

    # ── v1.2.3: мультинабор (broadcast в единственной точке ввода) ───────────
    def _resolve_multi_hub(self):
        """Хаб мультинабора этого виджета: явный (конструктор — тестовый шов,
        атрибут self._multi_hub) или модульный по умолчанию (get_hub — singleton,
        тот же, что у MainWindow). Имя НЕ `_multi_hub`: атрибут-хаб затеняет
        одноимённый метод в self.<имя> (TypeError: 'NoneType' is not callable)."""
        hub = self._multi_hub
        if hub is not None:
            return hub
        try:
            return _get_multi_hub()
        except Exception:
            return None  # модуль недоступен — ввод работает как в v1.2.2

    def _multi_active(self) -> bool:
        """Включён ли режим мультинабора (для F12-выхода в keyPressEvent)."""
        try:
            hub = self._resolve_multi_hub()
            return bool(hub is not None and hub.active)
        except Exception:
            return False

    def _multi_exit(self):
        """Выход из режима мультинабора (F12 / UI): слушатели хабa сбрасывают UI."""
        try:
            hub = self._resolve_multi_hub()
            if hub is not None:
                hub.set_active(False)
        except Exception:
            pass  # hub под teardown — клавиша просто не уходит в shell

    def _send(self, data: bytes):
        """ЕДИНСТВЕННАЯ точка отправки пользовательского ввода (v1.2.3, ROADMAP задача 1).

        Байты уходят в send_data() СВОЕЙ сессии; при включённом режиме мультинабора —
        те же байты дублируются во ВСЕ остальные открытые сессии реестра
        (hub.broadcast: источник пропускается, мёртвые потоки фильтруются). Отсюда
        проходят и печатные клавиши, и служебные (Return/Backspace/Esc/стрелки), и
        bracketed paste Ctrl+V — в мультирежиме дублируется всё, что набирается."""
        if not data or self.terminal_thread is None:
            return
        try:
            self.terminal_thread.send_data(data)
        except Exception:
            pass
        hub = self._resolve_multi_hub()
        if hub is not None and hub.active:
            try:
                sent = hub.broadcast(data, source_widget=self)
                # v1.2.4-fix (диагностика): DEBUG-строка на каждый broadcast —
                # в логе видно, сколько сессий реально получили байты (0 →
                # реестр пуст/мёртвые потоки; N>0 → байты ушли во все живые).
                _log = _get_app_log()
                if _log is not None:
                    _log.debug(
                        f"multi-input broadcast: {len(data)}B -> {sent} session(s)")
            except Exception:
                pass  # broadcast-сбой не должен ломать ввод в активной сессии

    def _bracketed_paste(self):
        """Ctrl+V — bracketed paste (перенос из v0.9.4): многострочный буфер
        приходит в shell ЕДИНЫМ блоком, а не построчным вводом."""
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text()
        if not text:
            return
        try:
            payload = text.replace("\r\n", "\n").replace("\r", "\n")
            self._send(b"\x1b[200~" + payload.encode("utf-8") + b"\x1b[201~")
        except Exception:
            pass

    # ── v1.0RC3: скроллбэк (колесо + Ctrl+Shift+PgUp/PgDn, TERMINAL.md §5.4) ──
    def scroll_page_up(self):
        """Страница истории вверх (Ctrl+Shift+PageUp / колесо вверх).

        True — позиция изменилась (перерисовка); на верхней границе pyte no-op.
        Локальная операция: работает и при terminal_thread=None."""
        if self.tscreen.scroll_up():
            self.update()
            return True
        return False

    def scroll_page_down(self):
        """Страница вниз, к live-строке (Ctrl+Shift+PageDown / колесо вниз)."""
        if self.tscreen.scroll_down():
            self.update()
            return True
        return False

    def wheelEvent(self, event):
        """Колесо мыши: v1.2.13 — сначала mouse tracking TUI, затем скроллбэк.

        Порядок проверок (v1.2.13, PYTE82_AUDIT.md пачка C):
        1. tscreen.mouse_tracking() — включён DECSET 1000/1002/1003 (TUI ждёт
           mouse-отчёты) → колесо уходит в PTY как xterm-отчёт: SGR
           (\\x1b[<64;{col};{row}M, при 1006 — up=64/down=65) или X10
           (\\x1b[M + [96|97, 32+col, 32+row]). Координаты — 1-based ячейка из позиции
           мыши, зажаты в сетку; X10 дополнительно в лимит протокола 223. Отправка —
           напрямую terminal_thread.send_data(), НЕ через _send() (координаты
           сессионно-локальны — мультинабор их broadcast'ить не должен). Passthrough
           приоритетнее wheel_mode="off".
        2. in_alt_screen() БЕЗ tracking → no-op (v1.2.12: TUI владеет сеткой,
           история не скролится; событие не потребляется — предков-QScrollArea в
           контейнерах нет, пропагация безвредна).
        3. Иначе — текущее поведение v1.0RC3: скроллбэк истории (вверх → prev_page,
           вниз → next_page; на границах pyte no-op), wheel_mode="off" →
           event.ignore(). Скроллбэк при "off" остаётся на Ctrl+Shift+PageUp/PageDown.

        Режимы читаются на КАЖДОЕ событие (TUI переключает их во время сессии —
        htop включает 1003+1006 при старте, выключает при выходе; кэшировать нельзя).
        Авто-возврат к live при новом выводе — встроен в pyte (before_event);
        _on_output окна вызывает widget.update(), поэтому снап виден сразу.
        """
        enabled, sgr = self.tscreen.mouse_tracking()   # v1.2.13: чтение на каждое событие
        if not enabled and self.tscreen.in_alt_screen():
            return  # alt без tracking — no-op (v1.2.12)
        if enabled:
            self._send_wheel_to_pty(event, sgr)
            event.accept()
            return
        if self._wheel_mode == "off":
            event.ignore()
            return
        if event.angleDelta().y() > 0:
            changed = self.tscreen.scroll_up()
        else:
            changed = self.tscreen.scroll_down()
        if changed:
            self.update()
        event.accept()

    def _send_wheel_to_pty(self, event, sgr):
        """v1.2.13: колесо → PTY (xterm mouse-отчёт, SGR/X10). Никогда не бросает.

        Координаты — 1-based ячейка из позиции мыши (event.position() в координатах
        виджета), зажаты в сетку [1..columns]×[1..lines]: виджет может быть шире/выше
        сетки на остаток округления метрик шрифта. SGR (DECSET 1006): \\x1b[<64;{col};{row}M —
        wheel up = кнопка 64, down = 65 (ctlseqs: кнопки 4/5 = коды событий кнопок
        1/2 + 64), лимитов на координаты нет. X10: \\x1b[M + [96|97, 32+col, 32+row] —
        значение+32 (up=96, down=97); протокол ограничивает координаты 223 (=255−32) —
        клампится (ctlseqs «Extended coordinates»: расширения только через UTF-8 1005 /
        SGR 1006; на ультрашироких сетках >223 колонки X10-отчёт неточен, SGR — нет).

        Отправка — НАПРЯМУЮ terminal_thread.send_data(), НЕ через _send(): колесо
        адресовано СВОЕЙ сессии (её координаты), broadcast мультинабора во все
        открытые сессии шёл бы чужим TUI отчёты с чужими координатами — осознанное
        решение, зафиксировано тестом.
        """
        if self.terminal_thread is None:
            return
        up = event.angleDelta().y() > 0
        cols, lines = self.tscreen.columns, self.tscreen.lines
        pos = event.position()
        col = max(1, min(int(pos.x() // max(1, self._cell_w)) + 1, cols))
        row = max(1, min(int(pos.y() // max(1, self._cell_h)) + 1, lines))
        if sgr:
            data = (b"\x1b[<" + str(64 if up else 65).encode("ascii") + b";"
                    + str(col).encode("ascii") + b";" + str(row).encode("ascii") + b"M")
        else:
            col = min(col, 223)   # X10-лимит протокола (см. docstring)
            row = min(row, 223)
            data = b"\x1b[M" + bytes([96 if up else 97, 32 + col, 32 + row])
        try:
            self.terminal_thread.send_data(data)
        except Exception:
            pass  # мёртвый канал/поток под teardown — колесо молча не уходит

    # ── v1.0RC3: мигание курсора (свой QTimer, ROADMAP задача 8) ───────────
    def showEvent(self, event):
        super().showEvent(event)
        self._cursor_visible = True      # сброс фазы при показе окна
        if not self._blink_timer.isActive():
            self._blink_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._blink_timer.stop()         # скрытое окно не мигает (ROADMAP v1.0RC3)

    def _toggle_cursor_blink(self):
        self._cursor_visible = not self._cursor_visible
        self.update()

    # ── выделение мышью + копирование (v1.0RC2, задача 5) ───
    def _cell_at(self, pos):
        """Пиксельная точка → (row, col), зажато в границы сетки tscreen."""
        cols = getattr(self.tscreen, "columns", 80)
        lines = getattr(self.tscreen, "lines", 24)
        x = max(0, pos.x()) // self._cell_w
        y = max(0, pos.y()) // self._cell_h
        return min(y, lines - 1), min(x, cols - 1)

    def has_selection(self):
        """Есть ли активное выделение (drag; простой клик — не выделение)."""
        return (self._sel_anchor is not None and self._sel_active is not None
                and self._sel_anchor != self._sel_active)

    def _selected_cells(self):
        """Ячейки текущего выделения: list[(row, col)] через чистую selection_cells()."""
        if not self.has_selection():
            return []
        cols = getattr(self.tscreen, "columns", 80)
        return selection_cells(self._sel_anchor, self._sel_active, cols)

    def clear_selection(self):
        self._sel_anchor = None
        self._sel_active = None
        self._click_sel_end = None   # v1.2.7: фиксатор drag'а после double/triple-click
        self.update()

    def selected_text(self):
        """Текст выделения для буфера обмена: строки склеены \\n, хвостовые
        пробелы строк обрезаны (заглушки широких глифов дают '' — не мешают)."""
        cells = self._selected_cells()
        if not cells:
            return ""
        rows, _cx, _cy, _hidden = self.tscreen.snapshot()
        by_row = {}
        for r, c in cells:
            by_row.setdefault(r, []).append(c)
        lines = []
        for r in sorted(by_row):
            if 0 <= r < len(rows):
                line = "".join(rows[r][c].data for c in sorted(by_row[r])
                               if 0 <= c < len(rows[r]))
                lines.append(line.rstrip())
        return "\n".join(lines)

    def copy_selection(self):
        """Ctrl+C при выделении — копирование в системный буфер (semantics v0.9.3).
        True — скопировано; False — выделения нет/буфер недоступен/текст пуст."""
        text = self.selected_text()
        if not text:
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True

    # ── мышь: ЛКМ press → drag → release (v1.0RC2; v1.2.7 — double/triple-click) ──
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            # v1.2.7: клик-счётчик (QMouseEvent не несёт click-count — считаем сами):
            # press в той же ячейке внутри DOUBLE_CLICK_MS → count+1, иначе 1.
            # ВАЖНО: time.monotonic() — СЕКУНДЫ, DOUBLE_CLICK_MS — миллисекунды
            # (сравнение без ×1000 дало бы «двойной клик» в течение 500 секунд).
            now_ms = time.monotonic() * 1000.0
            if (self._click_count > 0 and self._last_click_cell == cell
                    and now_ms - self._last_click_ms <= self.DOUBLE_CLICK_MS):
                self._click_count += 1
            else:
                self._click_count = 1
            self._last_click_cell = cell
            self._last_click_ms = now_ms

            if self._click_count >= 3:
                # тройной клик — вся строка (ROADMAP v1.2.7 задача 1)
                self._select_line(cell)
            elif self._click_count == 2:
                # двойной клик — слово под курсором
                self._select_word(cell)
            else:
                self._sel_anchor = cell
                self._sel_active = cell       # простой клик — пока не выделение
                self._click_sel_end = None
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._sel_anchor is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            # v1.2.7: drag ПОСЛЕ двойного/тройного клика — зафиксированный конец =
            # дальний конец слова/строки (_click_sel_end), выделение расширяется от него.
            if self._click_sel_end is not None:
                self._sel_anchor = self._click_sel_end
                self._click_sel_end = None
            self._sel_active = self._cell_at(event.position().toPoint())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._sel_anchor is not None:
            if self._click_count >= 2:
                # v1.2.7: отпускание после двойного/тройного клика НЕ затирает
                # выделение (простой клик ниже перезаписал бы _sel_active позицией
                # release'а и сбросил одно-ячеечное слово). Drag уже обработан в
                # mouseMoveEvent; здесь только сброс фиксатора.
                self._click_sel_end = None
                self.update()
                event.accept()
                return
            # Позиция отпускания — конец выделения (drag может закончиться без
            # промежуточного Move-события).
            self._sel_active = self._cell_at(event.position().toPoint())
            # Простой клик (press/release в одной ячейке) — сброс выделения.
            if self._sel_active == self._sel_anchor:
                self._sel_anchor = None
                self._sel_active = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── v1.2.7: двойной/тройной клик (ROADMAP v1.2.7 задача 1) ────────────────
    def _select_word(self, cell):
        """Двойной клик — выделение слова на строке под курсором.

        Слово — word_units() (максимальный прогон небелых ячеек; заглушка широкого
        CJK-глифа принадлежит слову). Клик по пробелу — бездействия: текущее
        выделение не меняется. _click_sel_end — дальний конец слова (ближе к клику
        НЕ фиксируем): drag после двойного клика расширяет выделение от него,
        как в xterm."""
        rows, _cx, _cy, _hidden = self.tscreen.snapshot()
        row, col = cell
        if not (0 <= row < len(rows)):
            return
        for start, end in word_units(rows[row]):
            if start <= col <= end:
                self._sel_anchor = (row, start)
                self._sel_active = (row, end)
                # фиксатор drag'а — дальний конец слова от точки клика
                self._click_sel_end = (row, end) if col - start < end - col else (row, start)
                return
        self._click_sel_end = None   # клик по пробелу — выделение не меняется

    def _select_line(self, cell):
        """Тройной клик — вся строка 0..columns-1 (ROADMAP v1.2.7 задача 1).

        Хвостовые пробелы при копировании и так обрезаются selected_text() (rstrip),
        поэтому «вся строка» = весь видимый диапазон колонок. _click_sel_end —
        дальний конец строки от точки клика (drag расширяет в обе стороны)."""
        cols = getattr(self.tscreen, "columns", 80)
        lines = getattr(self.tscreen, "lines", 24)
        row, col = cell
        r = max(0, min(int(row), lines - 1))
        self._sel_anchor = (r, 0)
        self._sel_active = (r, cols - 1)
        self._click_sel_end = (r, cols - 1) if col * 2 < cols else (r, 0)

    # ── v1.2.7: контекстное меню ПКМ (ROADMAP v1.2.7 задача 2) ────────────────
    def select_all(self):
        """Выделить всё — вся видимая сетка (контекстное меню, Ctrl+A-семантика)."""
        cols = getattr(self.tscreen, "columns", 80)
        lines = getattr(self.tscreen, "lines", 24)
        self._sel_anchor = (0, 0)
        self._sel_active = (lines - 1, cols - 1)
        self._click_sel_end = None
        self.update()

    def _build_context_menu(self):
        """QMenu контекстного меню ПКМ (v1.2.7): Копировать | Вставить | Выделить всё.

        Тестовый шов: contextMenuEvent создаёт меню этим методом и только показывает
        его — тесты вызывают _build_context_menu() напрямую и триггерят QAction'ы,
        не входя в menu.exec() (offscreen-зависание). Подписи — i18n terminal.menu.*
        (en/ru/zh). Копировать — enabled ТОЛЬКО при выделении; Вставить — только при
        живом потоке (terminal_thread), путь тот же, что Ctrl+V (_bracketed_paste →
        _send: bracketed-paste-блок в PTY + broadcast мультинабора)."""
        t = get_translator()
        menu = QMenu(self)
        act_copy = menu.addAction(t("terminal.menu.copy"))
        act_copy.setEnabled(self.has_selection())
        act_copy.triggered.connect(self.copy_selection)
        act_paste = menu.addAction(t("terminal.menu.paste"))
        act_paste.setEnabled(self.terminal_thread is not None)
        act_paste.triggered.connect(self._bracketed_paste)
        act_all = menu.addAction(t("terminal.menu.select_all"))
        act_all.triggered.connect(self.select_all)
        return menu

    def contextMenuEvent(self, event):
        """ПКМ — контекстное меню (v1.2.7). Никогда не бросает: сбой сборки меню
        (teardown-гонка) игнорируется; сбой exec'а логируется (не глотаем молча —
        паттерн аудита v0.7.2 из map_view.py)."""
        try:
            menu = self._build_context_menu()
        except Exception:
            event.ignore()
            return
        if menu is None:
            event.ignore()
            return
        try:
            # v1.2.7-fix (ручное тестирование): QContextMenuEvent.globalPos() уже
            # возвращает QPoint (в отличие от QMouseEvent.globalPosition() → QPointF) —
            # лишнее .toPoint() бросало AttributeError, которое старый except глотал
            # молча: «ПКМ ничего не делает» без единой видимой ошибки. Координаты —
            # как есть.
            menu.exec(event.globalPos())
        except Exception as e:  # noqa: BLE001 — GUI-компонент не должен ронять приложение
            _log = _get_app_log()
            if _log is not None:
                _log.error(f"contextMenuEvent: menu.exec failed: {e}")
        event.accept()
