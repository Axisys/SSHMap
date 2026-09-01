"""v0.8: TerminalScreen — ANSI-эмуляция терминала на pyte.

Полноценная замена «тупого» вывода QPlainTextEdit: pyte парсит все
escape-последовательности (CSI/OSC/режимы курсора, цвета) и держит сетку 120x32 —
ту же геометрию, что запрашивает SSHTerminalThread через invoke_shell(term='xterm',
width=120, height=32). Альтернативного экрана (режим 1049) в pyte 0.8.2 НЕТ
(проверено по установленной версии — TERMINAL.md факт №6): после vim/htop
предыдущий экран не восстанавливается, known limitation (ROADMAP v1.0).

v1.0RC1: добавлен цветовой движок для посячейного холста (PALETTES +
resolve_color, TERMINAL.md §5.1) и snapshot() — снимок сетки для
TerminalWidget (modules/terminal_widget.py). Старый HTML-рендер render()
помечен deprecated (удаление не раньше v1.2, ROADMAP v1.0).

v1.0RC3: pyte.Screen → pyte.HistoryScreen (TERMINAL.md §5.4) — готовый
скроллбэк (deque-история + prev_page()/next_page()) со встроенным авто-возвратом
к live-строке при новом выводе (before_event, проверено факт №7). scroll_up()/
scroll_down()/at_bottom() — под тем же lock'ом, что и feed(). Остальной API
(feed/resize/snapshot/render) без изменений — duck-typing.

Headless-friendly: сам класс Screen не требует Qt — тестируется без GUI.
Потокобезопасность: feed() из SSH-потока, snapshot()/render()/cursor из GUI-потока.
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


# ── v1.0RC1: цветовой движок для посячейного холста (TERMINAL.md §5.1) ───────
# Проверенные факты pyte 0.8.2 (прогоном на установленной версии):
#   * SGR 33 → fg='brown', SGR 93 → fg='brightbrown' — жёлтый называется brown;
#   * 256-цвета И truecolor хранятся как hex-строки БЕЗ '#' ('ff0000', '0a141e') —
#     ветка isdigit() никогда не срабатывает, нужен hex-passthrough;
#   * опечатка самого pyte: BG_AIXTERM[105] = 'bfightmagenta' (SGR 4;105 → bg='bfightmagenta').
# Движок headless (без Qt) — тестируется без GUI (tests/test_terminal_colors.py).

DEFAULT_FG_HEX = "#e2e8f0"   # default-текст (то же, что _DEFAULT_FG в HTML-пути)
DEFAULT_BG_HEX = "#0f172a"   # фон окна терминала (стиль QPlainTextEdit v0.8)

# ── v1.0RC3: параметры скроллбэка HistoryScreen (TERMINAL.md §5.4) ───────────
# history — глубина deque-истории (строк); ratio — размер «страницы» для
# prev_page()/next_page() = ceil(lines * ratio): ratio=0.1 при 32 строках даёт
# ~4 строки за тик колеса/нажатие Ctrl+Shift+PgUp/PgDn. Ключ конфига
# terminal_history_lines подключён в финале v1.0 (ROADMAP задача 9,
# load_terminal_settings() в modules/ssh_terminal.py) — дефолт = поведение ПОСЛЕ
# RC3 (скроллбэк включён); явный 0 — отключение скроллбэка пользователем.
DEFAULT_HISTORY_LINES = 1000
SCROLL_RATIO = 0.1

# Палитры: ОБЯЗАТЕЛЬНЫЕ ключи black…white + br_* (8+8) — иначе SGR 33/93 и
# bright-цвета уходят в default (критическая ошибка №2 из TERMINAL.md §3).
# 'default' — текущая xterm-подобная палитра (_PALETTE16): дефолты = текущий вид.
# default_fg/default_bg — цвет текста и фон экрана (reverse сводится к ним).
ANSI_COLOR_NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")

PALETTES = {
    "default": {
        "default_fg": "#e2e8f0", "default_bg": "#0f172a",
        "black": "#2e3440", "red": "#cd3131", "green": "#0dbc79", "yellow": "#e5e510",
        "blue": "#2472c8", "magenta": "#bc3fbc", "cyan": "#11a8cd", "white": "#e5e5e5",
        "br_black": "#555555", "br_red": "#f14c4c", "br_green": "#23d18b", "br_yellow": "#f5f543",
        "br_blue": "#3b8eea", "br_magenta": "#d670d6", "br_cyan": "#29b8db", "br_white": "#ffffff",
    },
    "nord": {
        "default_fg": "#d8dee9", "default_bg": "#2e3440",
        "black": "#3b4252", "red": "#bf616a", "green": "#a3be8c", "yellow": "#ebcb8b",
        "blue": "#81a1c1", "magenta": "#b48ead", "cyan": "#8fbcbb", "white": "#e5e9f0",
        "br_black": "#4c566a", "br_red": "#bf616a", "br_green": "#a3be8c", "br_yellow": "#ebcb8b",
        "br_blue": "#81a1c1", "br_magenta": "#b48ead", "br_cyan": "#8fbcbb", "br_white": "#eceff4",
    },
    "dracula": {
        "default_fg": "#f8f8f2", "default_bg": "#282a36",
        "black": "#282a36", "red": "#ff5555", "green": "#50fa7b", "yellow": "#f1fa8c",
        "blue": "#bd93f9", "magenta": "#ff79c6", "cyan": "#8be9fd", "white": "#f8f8f2",
        "br_black": "#6272a4", "br_red": "#ff6e6e", "br_green": "#69ff94", "br_yellow": "#ffffa5",
        "br_blue": "#d6acff", "br_magenta": "#ff92df", "br_cyan": "#a4ffff", "br_white": "#ffffff",
    },
    "tokyo_night": {
        "default_fg": "#c0caf5", "default_bg": "#1a1b26",
        "black": "#15161e", "red": "#f7768e", "green": "#9ece6a", "yellow": "#e0af68",
        "blue": "#7aa2f7", "magenta": "#bb9af7", "cyan": "#7dcfff", "white": "#c0caf5",
        "br_black": "#414868", "br_red": "#f7768e", "br_green": "#9ece6a", "br_yellow": "#e0af68",
        "br_blue": "#7aa2f7", "br_magenta": "#bb9af7", "br_cyan": "#7dcfff", "br_white": "#c0caf5",
    },
}


def resolve_color(value, palette=None, default_hex=DEFAULT_FG_HEX):
    """pyte-цвет → hex '#rrggbb' (TERMINAL.md §5.1).

    value: None/'default' | имя ('brown', 'brightred', …) | 6-hex без '#'
    (в pyte 0.8.2 и 256-цвета, и truecolor хранятся именно так — passthrough).
    Особые случаи: 'brown'/'brightbrown' — жёлтый (SGR 33/93); 'bfightmagenta' —
    опечатка самого pyte для bright magenta (BG_AIXTERM[105], SGR 4;105).
    Неизвестное имя → default_hex.
    """
    pal = PALETTES["default"] if palette is None else palette
    if value in (None, "default"):
        return default_hex
    v = str(value)
    # 256-цвет / truecolor: hex без '#' — passthrough
    if len(v) == 6:
        try:
            int(v, 16)
            return "#" + v
        except ValueError:
            pass
    name = v.lower()
    if name == "bfightmagenta":      # опечатка pyte (SGR 4;105) → bright magenta
        return pal.get("br_magenta", default_hex)
    if name.startswith("bright"):
        base = name[len("bright"):]
        if base == "brown":          # SGR 93 — bright yellow
            base = "yellow"
        return pal.get("br_" + base, pal.get(base, default_hex))
    if name == "brown":              # SGR 33 — в pyte жёлтый называется brown
        return pal.get("yellow", default_hex)
    return pal.get(name, default_hex)


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
    """Сетка columns x lines на pyte + потокобезопасный вход.

    v1.0RC3: screen — pyte.HistoryScreen (скроллбэк, TERMINAL.md §5.4)."""

    def __init__(self, columns=120, lines=32, history_lines=DEFAULT_HISTORY_LINES):
        self.columns = columns
        self.lines = lines
        # v1.0RC3: HistoryScreen вместо Screen — готовый скроллбэк (deque-история)
        # + авто-возврат к live-строке при новом выводе (before_event).
        self.screen = pyte.HistoryScreen(columns, lines,
                                         history=int(history_lines), ratio=SCROLL_RATIO)
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

    # ── v1.0RC3: скроллбэк (HistoryScreen, TERMINAL.md §5.4) ───────────────
    def scroll_up(self):
        """Страница истории вверх (prev_page). True — позиция изменилась.

        На верхней границе (position <= lines или история пуста) pyte делает
        no-op → False. Вызывается из GUI-потока (колесо/Ctrl+Shift+PgUp);
        под тем же lock'ом, что и feed() — SSH-поток не может изменить буфер
        посреди страницы."""
        with self._lock:
            scr = self.screen
            before = scr.history.position
            scr.prev_page()
            return scr.history.position != before

    def scroll_down(self):
        """Страница вниз, к live-строке (next_page). True — позиция изменилась."""
        with self._lock:
            scr = self.screen
            before = scr.history.position
            scr.next_page()
            return scr.history.position != before

    def at_bottom(self):
        """Мы на live-строке? (history.position == history.size — курсор виден,
        скролл вниз запрещён; TERMINAL.md §5.4)."""
        with self._lock:
            return self.screen.history.position == self.screen.history.size

    def scroll_info(self):
        """(position, size) для тестов/отладки."""
        with self._lock:
            h = self.screen.history
            return h.position, h.size

    # ── рендер для GUI-потока ──────────────────────────
    def snapshot(self):
        """v1.0RC1: снимок экрана для посячейного холста (TerminalWidget, GUI-поток).

        Возвращает (rows, cursor_x, cursor_y, cursor_hidden): rows — список
        lines списков Char шириной columns (пустые ячейки — default-Char pyte),
        курсор зажат в границы сетки (cursor.x может быть == columns после wrap).
        Читается под тем же lock'ом, что и feed(): SSH-поток не может изменить
        буфер посреди paintEvent. Работает и с pyte.HistoryScreen (v1.0RC3) —
        duck-typing по buffer/cursor/lines/columns.
        """
        with self._lock:
            scr = self.screen
            rows = [[scr.buffer[y][x] for x in range(scr.columns)]
                    for y in range(scr.lines)]
            cx = min(scr.cursor.x, scr.columns - 1)
            cy = min(scr.cursor.y, scr.lines - 1)
            return rows, cx, cy, bool(scr.cursor.hidden)

    def render(self):
        """DEPRECATED (v1.0RC1): HTML-рендер для QPlainTextEdit — заменён
        TerminalWidget (modules/terminal_widget.py, посячейный холст QWidget+QPainter;
        новый код использует snapshot() + resolve_color()). Оставлен до v1.2
        (ROADMAP v1.0: «удалить не раньше v1.2»); сьют от него не зависит.

        Возвращает (html_lines: list[str], cursor_x, cursor_y).

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
