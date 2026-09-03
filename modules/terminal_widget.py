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
(TERMINAL.md факт №11; эвристика east_asian_width W/F, полный wcwidth — v1.2+).

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
скроллбэк, event.ignore; SGR-passthrough — v1.2+).

Потоки: paintEvent и snapshot() — GUI-поток; feed() из SSH-потока под lock'ом
TerminalScreen — race посреди кадра исключён.
"""

import math
import unicodedata

try:
    from .terminal_screen import PALETTES, resolve_color
except ImportError:
    from modules.terminal_screen import PALETTES, resolve_color

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPen,
)
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget


def _fmt_key(ch):
    """Ключ форматирования ячейки — сырые атрибуты pyte Char (без палитры).

    Поле курсива в pyte 0.8.2 называется **italics** (не italic — TERMINAL.md
    факт №1, ошибка черновика №1). run — максимальная последовательность ячеек
    с одинаковым ключом; resolve_color() — чистая функция от (fg,bg,палитра),
    поэтому внутри run цвета консистентны.
    """
    return (ch.fg, ch.bg, bool(ch.bold), bool(ch.italics),
            bool(ch.underscore), bool(ch.strikethrough), bool(ch.reverse))


def is_wide_char(data: str) -> bool:
    """Эвристика широкого глифа (CJK): east_asian_width W/F (stdlib, без зависимостей).

    Known limitation (ROADMAP v1.0): полный wcwidth — v1.2+. Важно: в pyte 0.8.2
    сам глиф хранится с len(data)==1 («широкий» по data не определить) — широкой
    является СЛЕДУЮЩАЯ ячейка-«заглушка» с data==''; её пропускает split_row_runs.
    """
    if not data:
        return False
    return unicodedata.east_asian_width(data[0]) in ("W", "F")


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
    v1.0RC3 — скроллбэк колесом/Ctrl+Shift+PgUp/PgDn + мигание курсора).

    tscreen — TerminalScreen (pyte.HistoryScreen + lock); terminal_thread — объект с
    send_data(bytes) (SSHTerminalThread; None — ввод отключён, рендер и скроллбэк
    работают).
    """

    FORMAT_CACHE_LIMIT = 512      # лимит кэша форматов (TERMINAL.md §5.1)
    CURSOR_COLOR = "#e2e8f0"      # блок-курсор: цвет default-текста (классический вид)
    SELECTION_COLOR = (59, 130, 246, 90)   # v1.0RC2: оверлей выделения (RGBA, alpha≈35%)
    BLINK_INTERVAL_MS = 530       # v1.0RC3: период мигания курсора (ROADMAP задача 8)

    def __init__(self, tscreen, terminal_thread=None, parent=None,
                 palette_name="default", format_cache_limit=FORMAT_CACHE_LIMIT,
                 wheel_mode="scrollback"):
        super().__init__(parent)
        self.tscreen = tscreen
        self.terminal_thread = terminal_thread
        # v1.1.2RC3 (AUDIT U3): режим колеса из конфига terminal_wheel —
        # "scrollback" (дефолт, поведение v1.0RC3: колесо = локальный скроллбэк)
        # | "off" (колесо не перехватывается для скроллбэка; SGR-passthrough в
        # приложение — v1.2+). Неизвестное значение → дефолт.
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
                if not text.strip():
                    continue  # run из пробелов — фон уже залит
                ch0 = row[x]
                fg, bg = self._resolved_colors(ch0)
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

    # ── клавиатура: полная таблица v1.0RC2 ────────────────
    def keyPressEvent(self, event):
        """Полная таблица клавиатуры (v1.0RC2, ROADMAP задача 4; v1.0RC3 — скроллбэк).

        * F1–F12 — xterm-последовательности (_F_KEY_SEQUENCES);
        * Ctrl+Shift+PageUp/PageDown → СКОЛЛБЭК (v1.0RC3, TERMINAL.md §5.4): перехват
          стоит ДО проверки голых PageUp/PageDown — иначе fall-through из Ctrl-ветки
          шлёт \\x1b[5~/\\x1b[6~ в shell (ловушка из ROADMAP v1.0RC3 задача 7);
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
        * AltGr-guard (TERMINAL.md §3.12): Ctrl+Alt-комбинации (на Windows
          AltGr = Ctrl+Alt) НЕ уходят как управляющие коды — ignore.
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
        if key == Qt.Key.Key_Tab:
            self._send(b"\t")
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

    def _send(self, data: bytes):
        if data and self.terminal_thread is not None:
            try:
                self.terminal_thread.send_data(data)
            except Exception:
                pass

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
        """Колесо мыши — скроллбэк: вверх → prev_page, вниз → next_page.

        На границах (верх истории / live-строка) pyte делает no-op — позиция не
        меняется и холст не перерисовывается. Авто-возврат к live при новом
        выводе — встроен в pyte (before_event); _on_output окна вызывает
        widget.update(), поэтому снап виден сразу.

        v1.1.2RC3 (AUDIT U3, остаток): режим из конфига terminal_wheel
        (_wheel_mode). "off": колесо НЕ скроллит локальный скроллбэк — событие
        не потребляется (event.ignore), в PTY ничего не шлётся; полный
        SGR-passthrough колеса в полноэкранное TUI отложен на v1.2+ (pyte 0.8.2
        не трекает mouse-режимы DECSET 1000/1002/1006 — слепая пересылка
        засорит shell без mouse-режима). Скроллбэк при "off" остаётся на
        Ctrl+Shift+PageUp/PageDown."""
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

    # ── мышь: ЛКМ press → drag → release (v1.0RC2) ──────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._sel_anchor = self._cell_at(event.position().toPoint())
            self._sel_active = self._sel_anchor   # простой клик — пока не выделение
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._sel_anchor is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._sel_active = self._cell_at(event.position().toPoint())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._sel_anchor is not None:
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
