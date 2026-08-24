"""v0.8: TerminalScreen — ANSI-эмуляция терминала на pyte.

Полноценная замена «тупого» вывода QPlainTextEdit: pyte парсит все
escape-последовательности (CSI/OSC/режимы курсора, цвета, альтернативный
экран 1049) и держит сетку 120x32 — ту же геометрию, что запрашивает
SSHTerminalThread через invoke_shell(term='xterm', width=120, height=32).
Рендер: экран перерисовывается как HTML с цветами SGR в QTextEdit,
позиция курсора возвращается отдельным значением.

Headless-friendly: сам класс Screen не требует Qt — тестируется без GUI.
Потокобезопасность: feed() из SSH-потока, render()/cursor из GUI-потока.
"""

import threading

try:
    import pyte
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Для v0.8 терминала требуется пакет 'pyte' (pip install pyte)"
    ) from e

# Палитра xterm-подобная: индексы 0–15 → hex, 16–255 — через pyte.graphics.FG_BG_256
_PALETTE16 = [
    "#2e3440", "#cd3131", "#0dbc79", "#e5e510",
    "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
    "#555555", "#f14c4c", "#23d18b", "#f5f543",
    "#3b8eea", "#d670d6", "#29b8db", "#ffffff",
]
_DEFAULT_FG = "#e2e8f0"   # светлый текст на тёмном фоне окна терминала
_DEFAULT_BG = None        # фон задаёт стиль QPlainTextEdit (#0f172a)

# имя цвета pyte ('red', 'brown', ...) → индекс базовой палитры
_NAME_TO_IDX = {name: i for i, name in enumerate(
    ["black", "red", "green", "brown", "blue", "magenta", "cyan", "white"])}


def _color(value):
    """Значение цвета pyte → hex-строка или None (default)."""
    if value in (None, "default"):
        return None
    if isinstance(value, int):
        return _PALETTE16[value] if value < 16 else "#" + pyte.graphics.FG_BG_256[value]
    # строка: либо имя ('red'), либо hex-строка pyte 256-цвета ('ff0000')
    if value.startswith("#"):
        return value
    if len(value) == 6:
        try:
            int(value, 16)
            return "#" + value
        except ValueError:
            pass
    idx = _NAME_TO_IDX.get(value)
    if idx is not None:
        return _PALETTE16[idx]
    if value.startswith("bright"):  # 'brightred' и т.п.
        base = value[len("bright"):]
        idx = _NAME_TO_IDX.get(base)
        if idx is not None:
            return _PALETTE16[idx + 8]
    return None


def _esc_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TerminalScreen:
    """Сетка columns x lines на pyte + потокобезопасный вход."""

    def __init__(self, columns=120, lines=32):
        self.columns = columns
        self.lines = lines
        self.screen = pyte.Screen(columns, lines)
        self.stream = pyte.ByteStream(self.screen)   # принимает байты, utf-8 внутри
        self._lock = threading.Lock()

    # ── вход из SSH-потока ─────────────────────────────
    def feed(self, data: bytes):
        with self._lock:
            self.stream.feed(data)

    def resize(self, columns, lines):
        with self._lock:
            self.columns, self.lines = columns, lines
            self.screen.resize(lines, columns)

    # ── рендер для GUI-потока ──────────────────────────
    def render(self):
        """Возвращает (html_lines: list[str], cursor_x, cursor_y).

        html_lines — готовые строки HTML (<span style=color:…>),
        текст внутри экранирован; хвостовые пробелы строк обрезаны.
        """
        with self._lock:
            scr = self.screen
            out = []
            for y in range(scr.lines):
                line = scr.buffer[y]
                spans = []          # [(text, fg_hex|None, bg_hex|None, bold)]
                cur = [None, None, False]
                buf = []

                def flush():
                    if buf:
                        spans.append(("".join(buf), cur[0], cur[1], cur[2]))
                        buf.clear()

                for x in range(scr.columns):
                    ch = line[x]
                    fg = _color(ch.fg) if ch.fg not in (None, "default") else None
                    bg = _color(ch.bg) if ch.bg not in (None, "default") else None
                    if ch.reverse:
                        fg, bg = bg or _DEFAULT_FG, fg or "#0f172a"  # инверсия default-цветов
                    if [fg, bg, bool(ch.bold)] != cur:
                        flush()
                        cur = [fg, bg, bool(ch.bold)]
                    buf.append(ch.data)
                flush()

                html = []
                for text, fg, bg, bold in spans:
                    stripped = text.rstrip()
                    if not stripped:
                        continue
                    styles = []
                    if fg:
                        styles.append(f"color:{fg}")
                    if bg:
                        styles.append(f"background-color:{bg}")
                    if bold:
                        styles.append("font-weight:bold")
                    esc = _esc_html(stripped)
                    html.append(f'<span style="{";".join(styles)}">{esc}</span>'
                                if styles else esc)
                out.append("".join(html))

            cx = min(scr.cursor.x, scr.columns - 1)
            cy = min(scr.cursor.y, scr.lines - 1)
            return out, cx, cy

    @property
    def cursor(self):
        """(x, y) позиции курсора pyte."""
        return self.screen.cursor.x, self.screen.cursor.y
