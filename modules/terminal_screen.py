"""v0.8: TerminalScreen — ANSI-эмуляция терминала на pyte.

Полноценная замена «тупого» вывода QPlainTextEdit: pyte парсит все
escape-последовательности (CSI/OSC/режимы курсора, цвета) и держит сетку 120x32 —
ту же геометрию, что запрашивает SSHTerminalThread через invoke_shell(term='xterm',
width=120, height=32). Альтернативного экрана (режим 1049) в pyte 0.8.2 НЕТ
(проверено по установленной версии — TERMINAL.md факт №6): после vim/htop
предыдущий экран не восстанавливается, known limitation (ROADMAP v1.0).
→ ЗАКРЫТО v1.2.12 подклассом SshmapHistoryScreen (режимы 47/1047/1048/1049 —
см. секцию v1.2.12 ниже и PYTE82_AUDIT.md пачка B).

v1.0RC1: добавлен цветовой движок для посячейного холста (PALETTES +
resolve_color, TERMINAL.md §5.1) и snapshot() — снимок сетки для
TerminalWidget (modules/terminal_widget.py). Старый HTML-рендер render()
помечен deprecated с v1.0RC1 и удалён в v1.2.9 (ROADMAP «Гигиена терминала»).

v1.0RC3: pyte.Screen → pyte.HistoryScreen (TERMINAL.md §5.4) — готовый
скроллбэк (deque-история + prev_page()/next_page()) со встроенным авто-возвратом
к live-строке при новом выводе (before_event, проверено факт №7). scroll_up()/
scroll_down()/at_bottom() — под тем же lock'ом, что и feed(). Остальной API
(feed/resize/snapshot/render) без изменений — duck-typing.

v1.1.2RC3 (AUDIT U3): application_cursor_keys() — состояние DECCKM (приватный
режим 1) под тем же lock'ом, что и feed(): TerminalWidget по нему выбирает
последовательности стрелок (SS3 \x1bOA… при mc/vim/htop, CSI \x1b[A… в обычном
режиме). Проверенный факт pyte 0.8.2: приватные режимы хранятся в screen.mode
со сдвигом влево на 5 бит (set_mode(private=True): mode << 5) — DECCKM это 32,
а НЕ 1 (проверено прогоном на установленной версии).

v1.2.11 (PYTE82_AUDIT.md пачка A): SshmapHistoryScreen — подкласс pyte.HistoryScreen
с двумя override'ами совместимости с УСТАНОВЛЕННОЙ pyte 0.8.2. Механизм: Stream
привязывает методы экрана через getattr(listener, attr) при attach (streams.py,
create_dispatcher) → переопределения подкласса парсер подхватывает автоматически;
публичный API TerminalScreen не меняется (duck-typing). Проверенный факт №12
(прогоном на установленной pyte 0.8.2): Vim 9+ шлёт \x1b[?4m (private SGR,
upstream issue #202); в 0.8.2 это TypeError из feed() — Screen.select_graphic_rendition
не принимает private, и хвост чанка после последовательности теряется (парсер
сбрасывается; except Exception: return в _on_output глотает исключение). Подкласс
игнорирует private SGR; в master фикс уже вмержен (PR #203, 2025-09-02) — override с
той же семантикой оставляем до поднятия пина на pyte 0.8.3 (совместим и задокументирован;
при 0.8.3 пункт про 'bfightmagenta' в resolve_color() помечаем legacy — в master
опечатка BG_AIXTERM[105] уже исправлена). LNM (режим 20) включён по умолчанию:
голый LF = CR+LF (xterm-поведение; Screen.reset() сбрасывает mode на _DEFAULT_MODE
без LNM → явное восстановление после super().__init__ и в reset(); явные
\x1b[20h/\x1b[20l (SM/RM 20) от удалённой программы по-прежнему работают).

v1.2.12 (PYTE82_AUDIT.md пачка B): альтернативный экран в SshmapHistoryScreen —
приватные режимы 47/1047/1048/1049, которые в 0.8.2 были инертными битами
screen.mode со сдвигом <<5 (обработчиков нет). Семантика — по upstream PR #212
(закрыт без мерджа, автор dwgx; код pyte LGPL-3.0 — атрибуция автору PR в
комментарии к коду обязательна), дифференциально проверенная против tmux 3.6b
и GNU screen: ОДИН флаг in_alt (ESC[?47l выходит из экрана, вошедшего через
1049h); вход — сохранить основной буфер → рабочий = пустой новый (курсор НЕ
хомится — TUI сам шлёт CUP; повторный вход идемпотентен); выход — восстановить
сохранённый буфер с клипом под текущую ширину, альтерн-буфер отбросить
(содержимое не переживает round-trip — поведение обоих референс-эмуляторов
приоритетнее буквы xterm «without clearing»); курсор сохраняется/восстанавливается
только для 1048/1049 (xterm: 1049 = 1047+1048) отдельным полем _alt_cursor, а НЕ
стек savepoints (TUI внутри сессии сам гоняет ESC 7/ESC 8). Строки, ушедшие за
край альтерн-буфера (index/reverse_index при in_alt), не попадают в скроллбэк —
как less в настоящем терминале; RIS (ESC c — НЕ ESC [ c, это CSI DA) внутри alt →
полный сброс + выход.
Доступор: screen.in_alt + TerminalScreen.in_alt_screen() под тем же lock'ом, что
и feed(); пока in_alt — колесо мыши и Ctrl+Shift+PgUp/PgDn не скроллят историю
(гейт в TerminalWidget; полноценная маршрутизация колеса в TUI — v1.2.13).

v1.2.14 (PYTE82_AUDIT.md пачка D2): батчинг авто-возврата к live-строке — override
before_event в SshmapHistoryScreen. Для каждого события кроме prev_page/next_page
pyte крутил next_page() в цикле: при глубокой истории до ~250 итераций, каждая
O(lines) (замер D1 v1.2.12: 68–73 мс/чанк против ~42 на live-строке; feed идёт
через queued signal — блокировка GUI-потока). Теперь одна bulk-операция с той же
арифметикой, что в next_page (screens.py): mid = min(len(history.bottom), size −
position); top.extend(buffer[0:mid]); buffer сдвиг вверх; buffer[-mid:] — из
bottom.popleft(); position += mid; dirty = все строки — O(lines) один раз. Проверенный
факт (прогоном): инвариант len(history.bottom) == size − position → mid может
превышать lines (глубокая история); тогда избыток mid сверх lines возвращается из
главы bottom обратно в top (те же строки, что цикл переносил бы в промежуточных
итерациях) — итог идентичен циклу next_page(): position == size, bottom пуст, top
полностью восстановлен, buffer = live-экран. Обёртка вызывает self.before_event(event)
по имени → override подхватывается (before_event не входит в _wrapped); prev_page/
next_page — no-op, как в pyte.

Headless-friendly: сам класс Screen не требует Qt — тестируется без GUI.
Потокобезопасность: feed() из SSH-потока, snapshot()/application_cursor_keys
из GUI-потока (v1.1.2 final N13: мёртвое свойство cursor убрано — декларация
совпадает с кодом; курсор отдаёт snapshot()).
"""

import copy
import threading
from collections import defaultdict

try:
    import pyte
    from pyte.screens import Char, Margins, StaticDefaultDict
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Для v0.8 терминала требуется пакет 'pyte' (pip install pyte)"
    ) from e

# ── v1.0RC1: цветовой движок для посячейного холста (TERMINAL.md §5.1) ───────
# Проверенные факты pyte 0.8.2 (прогоном на установленной версии):
#   * SGR 33 → fg='brown', SGR 93 → fg='brightbrown' — жёлтый называется brown;
#   * 256-цвета И truecolor хранятся как hex-строки БЕЗ '#' ('ff0000', '0a141e') —
#     ветка isdigit() никогда не срабатывает, нужен hex-passthrough;
#   * опечатка самого pyte: BG_AIXTERM[105] = 'bfightmagenta' (SGR 4;105 → bg='bfightmagenta').
# Движок headless (без Qt) — тестируется без GUI (tests/test_terminal_colors.py).

DEFAULT_FG_HEX = "#e2e8f0"   # default-текст на тёмном фоне окна терминала
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
# 'default' — текущая xterm-подобная палитра: дефолты = текущий вид.
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


# ── v1.2.11 (PYTE82_AUDIT.md пачка A): совместимость с установленной pyte 0.8.2 ─
class SshmapHistoryScreen(pyte.HistoryScreen):
    """pyte.HistoryScreen + override'ы совместимости (факт №12, PYTE82_AUDIT.md)
    и альтернативный экран (v1.2.12, пачка B).

    * private SGR (CSI ? … m) — игнорируются: в 0.8.2 это TypeError из feed()
      (Vim 9+ шлёт \\x1b[?4m, upstream issue #202; фикс уже вмержен в master —
      PR #203, 2025-09-02). Override с той же семантикой оставляем до поднятия
      пина на pyte 0.8.3 (совместим и задокументирован);
    * LNM (режим 20) включён по умолчанию: голый LF = CR+LF (xterm-поведение).
      Screen.reset() сбрасывает mode на _DEFAULT_MODE БЕЗ LNM → явное восстановление
      в __init__ (ПОСЛЕ super().__init__) и в reset() (RIS ESC c — НЕ ESC [ c, это CSI DA); явные
      \\x1b[20h/\\x1b[20l (SM/RM 20) от удалённой программы по-прежнему работают;
    * альтернативный экран (v1.2.12): приватные режимы 47/1047/1048/1049 — в 0.8.2
      это инертные биты screen.mode (сдвиг <<5), обработчиков нет. Семантика — по
      upstream PR #212 (закрыт без мерджа, автор dwgx; код pyte LGPL-3.0 — атрибуция
      автору PR обязательна), дифференциально проверенная против tmux 3.6b и GNU
      screen: один флаг in_alt; вход — сохранить основной буфер → рабочий = пустой
      новый (курсор НЕ хомится, повторный вход идемпотентен); выход — восстановить
      сохранённый буфер с клипом под текущую ширину, альтерн-буфер отбросить; курсор
      только для 1048/1049 — отдельное поле _alt_cursor (НЕ стек savepoints); строки,
      ушедшие за край альтерн-буфера, не попадают в скроллбэк; RIS внутри alt →
      полный сброс + выход.

    Механизм подхвата: Stream привязывает методы экрана через getattr(listener, attr)
    при attach → парсер видит переопределения этого подкласса автоматически."""

    # Приватные коды ДО сдвига <<5 (в pyte.modes 0.8.2 констант для них нет —
    # проверено: там только LNM/IRM/DECTCEM/DECSCNM/DECOM/DECAWM/DECCOLM).
    ALTSCREEN_MODES = (47, 1047, 1048, 1049)

    def __init__(self, *args, **kwargs):
        # Состояние alt инициализируется ДО super().__init__: внутри конструктора
        # Screen.__init__ вызывается self.reset(), а override ниже читает in_alt.
        self.in_alt = False            # один флаг (не четыре): мы на альтерн-экране
        self._saved_buffer = None      # основной буфер, пока in_alt
        self._alt_cursor = None        # курсор для 1048/1049 (отдельное поле, НЕ savepoints)
        super().__init__(*args, **kwargs)
        self.mode.add(pyte.modes.LNM)   # xterm-поведение: голый LF = CR+LF

    def reset(self):
        if self.in_alt:                # RIS (ESC c) внутри alt: полный сброс + выход
            self.in_alt = False
            self._saved_buffer = None  # основной буфер всё равно чистится штатным reset()
            self._alt_cursor = None
        super().reset()                 # Screen.reset() сбрасывает mode на _DEFAULT_MODE
        self.mode.add(pyte.modes.LNM)   # …поэтому после RIS (ESC c) LNM возвращаем

    # ── v1.2.14 (PYTE82_AUDIT.md пачка D2): батчинг авто-возврата к live-строке ──
    def before_event(self, event):
        """Батчинг авто-возврата к live-строке (замер D1, v1.2.12: 68–73 мс/чанк).

        pyte.HistoryScreen.before_event для каждого события кроме prev_page/next_page
        крутит next_page() в цикле: при глубокой истории до ~250 итераций, каждая
        O(lines) (замер D1 v1.2.12: 68–73 мс/чанк против ~42 на live-строке — feed
        идёт через queued signal в GUI-потоке). Здесь — одна bulk-операция с той же
        арифметикой, что в HistoryScreen.next_page (screens.py):
        mid = min(len(history.bottom), size − position); top.extend(buffer[0:mid]);
        buffer сдвиг вверх; buffer[-mid:] — из bottom.popleft(); position += mid;
        dirty = все строки. O(lines) один раз вместо O(position/ratio × lines).

        Проверенный факт (прогоном на установленной pyte 0.8.2): инвариант
        len(history.bottom) == size − position (каждый prev_page/next_page переносит
        одно и то же число строк между buffer и bottom) → mid может превышать lines
        (глубокая история: 968 строк на 32-строчном экране). В этом случае наивный
        цикл next_page() ломается (range(lines − mid) пуст — сдвиг не происходит, а
        отрицательные индексы создали бы мусор в buffer): избыток mid сверх lines
        возвращается из ГЛАВЫ bottom обратно в top (те же строки, которые цикл
        переносил бы в промежуточных итерациях), а экран получает последние lines
        строк последовательности (buffer[take:] + остаток bottom). Итог идентичен
        циклу next_page(): position == size, bottom пуст, top полностью восстановлен,
        buffer = live-экран; при mid ≤ lines код совпадает с next_page() пословно.

        Механизм подхвата: обёртка HistoryScreen.__getattribute__ вызывает
        self.before_event(event) по имени → переопределение подкласса подхватывается
        (before_event не входит в _wrapped — конфликтов нет). prev_page/next_page —
        no-op, как в pyte: ручная прокрутка колесом/PgUp-PgDn авто-возврат НЕ трогает.
        """
        if event in ("prev_page", "next_page"):
            return
        h = self.history
        if h.position < h.size and h.bottom:
            mid = min(len(h.bottom), h.size - h.position)
            take = min(mid, self.lines)      # строк из buffer, которые уходят обратно в top
            h.top.extend(self.buffer[y] for y in range(take))
            if mid > take:                   # глубокая история: избыток — из главы bottom в top
                h.top.extend(h.bottom.popleft() for _ in range(mid - take))
            for y in range(self.lines - take):        # buffer сдвиг вверх (как в next_page)
                self.buffer[y] = self.buffer[y + take]
            for y in range(self.lines - take, self.lines):
                self.buffer[y] = h.bottom.popleft()   # нижние строки — из bottom
            self.history = h._replace(position=h.position + mid)
            self.dirty = set(range(self.lines))

    # ── v1.2.12: альтернативный экран (пачка B; семантика — upstream PR #212,
    #    закрыт без мерджа, автор dwgx; код pyte LGPL-3.0 — атрибуция обязательна) ──
    def set_mode(self, *modes, **kwargs):
        if kwargs.get("private") and any(m in self.ALTSCREEN_MODES for m in modes):
            self._enter_alt(save_cursor=any(m in (1048, 1049) for m in modes))
        super().set_mode(*modes, **kwargs)      # биты складываются в mode как раньше

    def reset_mode(self, *modes, **kwargs):
        if kwargs.get("private") and any(m in self.ALTSCREEN_MODES for m in modes):
            self._exit_alt(restore_cursor=any(m in (1048, 1049) for m in modes))
        super().reset_mode(*modes, **kwargs)

    def _enter_alt(self, save_cursor):
        if self.in_alt:
            return                  # повторный вход идемпотентен (основной не теряется)
        self._saved_buffer = self.buffer
        self.buffer = defaultdict(lambda: StaticDefaultDict[int, Char](self.default_char))
        self.dirty.update(range(self.lines))
        if save_cursor:             # только 1048/1049 (xterm: 1049 = 1047+1048)
            self._alt_cursor = copy.copy(self.cursor)
        self.in_alt = True          # курсор НЕ хомится — TUI сам шлёт CUP

    def _exit_alt(self, restore_cursor):
        if not self.in_alt:
            return
        saved = self._saved_buffer
        for line in saved.values():             # клип под текущую ширину (resize-безопасность;
            for x in [x for x in line if x >= self.columns]:   # те же границы, что в Screen.resize)
                line.pop(x, None)
        self.buffer = saved                     # альтерн-буфер отброшен: содержимое не
                                                # переживает round-trip (tmux/screen так же)
        self.in_alt = False
        self._saved_buffer = None
        self.dirty.update(range(self.lines))
        if restore_cursor and self._alt_cursor is not None:
            self.cursor = self._alt_cursor
            self._alt_cursor = None
            self.ensure_hbounds()               # кламп после возможного resize в alt
            self.ensure_vbounds()

    def index(self):
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == bottom and not self.in_alt:
            self.history.top.append(self.buffer[top])   # в alt — не сливаем в скроллбэк (less)
        pyte.Screen.index(self)

    def reverse_index(self):
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == top and not self.in_alt:
            self.history.bottom.append(self.buffer[bottom])
        pyte.Screen.reverse_index(self)

    def select_graphic_rendition(self, *attrs, private=False):
        if private:
            return  # private SGR (CSI ? … m) — игнорируем, как в pyte master (PR #203)
        super().select_graphic_rendition(*attrs)


class TerminalScreen:
    """Сетка columns x lines на pyte + потокобезопасный вход.

    v1.0RC3: screen — pyte.HistoryScreen (скроллбэк, TERMINAL.md §5.4).
    v1.2.11: screen — SshmapHistoryScreen (подкласс, совместимость с pyte 0.8.2).
    v1.2.12: + in_alt_screen() — состояние альтернативного экрана под lock'ом."""

    def __init__(self, columns=120, lines=32, history_lines=DEFAULT_HISTORY_LINES):
        self.columns = columns
        self.lines = lines
        # v1.0RC3: HistoryScreen вместо Screen — готовый скроллбэк (deque-история)
        # + авто-возврат к live-строке при новом выводе (before_event).
        # v1.2.11: подкласс SshmapHistoryScreen (private SGR + LNM, пачка A).
        self.screen = SshmapHistoryScreen(columns, lines,
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

    # ── v1.1.2RC3 (AUDIT U3): состояние DECCKM для ввода ────────────────────
    def application_cursor_keys(self):
        """Включён ли DECCKM (Application Cursor Keys Mode, приватный режим 1)?

        Полноэкранные TUI (mc/vim/htop) при запуске шлют smkx \\x1b[?1h и дальше
        ОЖИДАЮТ стрелки в SS3-форме (\\x1bOA…\\x1bOD), а не CSI (\\x1b[A…).
        TerminalWidget по этому флагу выбирает последовательность для стрелок
        и Home/End (AUDIT U3: «в mc не работают стрелки»).

        ВАЖНО (проверено прогоном на установленной pyte 0.8.2): приватные режимы
        хранятся в screen.mode со сдвигом влево на 5 бит — set_mode(private=True)
        делает mode << 5. DECCKM это **32**, а не 1: каноническая из интернета
        проверка «1 in screen.mode» никогда не срабатывает (после \\x1b[?1h в
        режиме появляется 32; по умолчанию включены DECAWM=7<<5=224,
        DECTCEM=25<<5=800 и — с v1.2.11 — LNM=20: {224, 800, 20}). pyte.modes
        константы DECCKM в 0.8.2 нет.

        Читается под тем же lock'ом, что и feed(): SSH-поток может менять режимы
        параллельно с GUI-потоком (smkx/rmkx приходят в выводе приложения).
        """
        with self._lock:
            return (1 << 5) in self.screen.mode

    # ── v1.2.12 (PYTE82_AUDIT.md пачка B): состояние альтернативного экрана ──
    def in_alt_screen(self):
        """Включён ли альтернативный экран (приватные режимы 47/1047/1048/1049)?

        Читается под тем же lock'ом, что и feed(): SSH-поток может менять режимы
        параллельно с GUI-потоком (htop/vim шлют \\x1b[?1049h при старте и
        \\x1b[?1049l при выходе). Пока in_alt — TerminalWidget НЕ скроллит
        историю колесом мыши и Ctrl+Shift+PgUp/PgDn (гейт); колесо в TUI уходит
        в PTY только при включённом mouse tracking (v1.2.13, mouse_tracking())."""
        with self._lock:
            return self.screen.in_alt

    # ── v1.2.13 (PYTE82_AUDIT.md пачка C): состояние mouse tracking ──────────
    def mouse_tracking(self):
        """(enabled, sgr) — включён ли xterm mouse tracking и используется ли SGR-формат.

        enabled — включён любой из DECSET 1000/1002/1003 (button / button-motion /
        all-motion tracking); sgr — включён DECSET 1006 (SGR extended encoding).

        ВАЖНО (проверено прогоном на установленной pyte 0.8.2): приватные режимы
        хранятся в screen.mode со сдвигом влево на 5 бит — set_mode(private=True)
        делает mode << 5: после \\x1b[?1000h\\x1b[?1006h в режиме есть 32000 и 32192.
        DECSET 1006 ОДИН не включает tracking — он только меняет кодировку отчётов
        (реальный xterm без 1000/1002/1003 mouse-события не генерирует) →
        feed(b'\\x1b[?1006h') даёт (False, True), а НЕ (True, True).

        Читается под тем же lock'ом, что и feed(), на КАЖДОЕ событие колеса:
        TUI меняет режимы во время сессии (htop включает 1003+1006 при старте и
        выключает при выходе) — кэшировать нельзя. RIS (\\x1bc) сбрасывает все
        приватные режимы → после полного reset снова (False, False) (проверено).
        """
        with self._lock:
            mode = self.screen.mode
            enabled = any((n << 5) in mode for n in (1000, 1002, 1003))
            return enabled, (1006 << 5) in mode

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

    # v1.2.9 (ROADMAP «Гигиена терминала»): deprecated HTML-рендер render()
    # (v1.0RC1) УДАЛЁН вместе с хелперами _color()/_esc_html() — мёртвый код с
    # v1.0RC1, окном никогда не создавался; рендер — TerminalWidget.snapshot().

    # v1.1.2 final (N13): мёртвое свойство cursor() УДАЛЕНО — вызывающих в коде
    # не было (AUDIT: только внутренние чтения screen.cursor.* под lock'ом).
    # Курсор для рендера отдаёт snapshot() — под тем же lock'ом, что и feed().
