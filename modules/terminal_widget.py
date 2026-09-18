# -*- coding: utf-8 -*-
"""v1.0RC1: TerminalWidget — the cell-based canvas of the terminal (QWidget + QPainter).

Replaces the HTML rendering (QPlainTextEdit + TerminalScreen.render(), deprecated since v1.0RC1):
paintEvent draws **runs** of identical formatting (not per-character drawText),
colors — via resolve_color() from modules/terminal_screen.py (TERMINAL.md §5.1,
verified pyte 0.8.2 facts: brown/brightbrown, hex passthrough of the 256 colors and
truecolor, the 'bfightmagenta' typo).

The cursor — a block via swap (TERMINAL.md §3.13): fill the cell with the cursor color +
redraw the glyph with the background color (NOT an XOR inversion — on colored cells it
gives "soapy" tints); honors screen.cursor.hidden (ESC[?25l/h — vim hides the cursor).
Wide glyphs (CJK): double width, the "placeholder" (data == '') is skipped
(TERMINAL.md fact #11; v1.2.9: the full wcwidth(3) — the same wcwidth package table
that pyte 0.8.2 itself uses for grid layout, instead of the
east_asian_width W/F heuristic of v1.0RC1).

The format cache (fg,bg,attributes) → (QPen,QBrush,QFont) with a size limit
(512 entries, cleared on overflow — TERMINAL.md §5.1); reverse is reduced to
an fg/bg swap BEFORE the key, so visually identical cells land in one cache entry.

v1.0RC2 — the keyboard (the full table) + mouse selection/copy:
* keyboard: F1–F12 (xterm sequences), PageUp/PageDown, Home/End/Delete
  (the semantics of the old SSHTerminalTextEdit preserved), explicit Ctrl+C→\\x03 /
  Ctrl+D→\\x04 without a selection, the Ctrl+V bracketed paste (carried over from v0.9.4),
  the AltModifier guard (AltGr does not go out as control codes — TERMINAL.md §3.12);
* selection: LMB press/move/release → anchor/end in (row, col); the pure function
  selection_cells() (TERMINAL.md §5.2, the regression for draft error #4 —
  the coordinates are ALWAYS (row, col), not (col, row)); Ctrl+C with a selection copies
  to the clipboard (the v0.9.3 semantics preserved), without a selection — SIGINT;
* highlighting — a semi-transparent overlay over the selected cells (the glyphs are visible).

Threading: paintEvent and snapshot() — the GUI thread; feed() from the SSH thread under the lock
v1.0RC3 — scrollback + dirty rendering:
* the mouse wheel and Ctrl+Shift+PageUp/PageDown → tscreen.scroll_up()/scroll_down()
  (pyte.HistoryScreen, TERMINAL.md §5.4); the "Ctrl+Shift → scroll" interception sits
  BEFORE the bare PageUp/PageDown check — those remain a forward to the shell
  (\\x1b[5~/\\x1b[6~, the v1.0RC2 semantics: less/man paging, the Windows
  Terminal/GNOME/xterm convention); the auto-return to the live line on new output is
  built into pyte (before_event) and only needs update() from _on_output;
* the cursor blink — a dedicated QTimer (BLINK_INTERVAL_MS), stopped when
  the window is hidden (hideEvent); the canvas repaints on the dirty flag:
  _on_output → widget.update() directly, no 30 FPS timer needed.

Threading: paintEvent and snapshot() — the GUI thread; feed() from the SSH thread under the lock
v1.1.2RC3 — the arrows according to the DECCKM state (AUDIT U3: "the arrows do not work in mc"):
the arrows and Home/End are sent as SS3 (\x1bOA…\x1bOD, \x1bOH/\x1bOF) when the application
enabled Application Cursor Keys Mode (smkx \x1b[?1h — mc/vim/htop do this
at startup), and as CSI (\x1b[A…\x1b[D, \x1b[H/\x1b[F) in normal mode. The state
is read from tscreen.application_cursor_keys() (pyte 0.8.2: DECCKM = 32 in
screen.mode — private modes are stored with the <<5 shift; the canonical check
"1 in screen.mode" does not work). + wheel: the wheel_mode parameter from the
terminal_wheel config — "scrollback" (the default) | "off" (the wheel does not scroll the local
scrollback, event.ignore); v1.2.13: if a TUI enabled mouse tracking (DECSET
1000/1002/1003), the wheel goes to the PTY as an SGR/X10 report — the passthrough takes precedence over "off".

v1.2.7 — selection by double/triple-click + the context menu (RMB):
* a double-click — select the WORD on the line (word_units() — a pure function:
  a word = the maximal run of non-space cells; the placeholder of a wide CJK glyph
  belongs to the word), a triple-click — the whole LINE (0..columns-1); the clicks are counted
  by the widget itself (the cell + the DOUBLE_CLICK_MS interval) — QMouseEvent in PySide6 carries
  no click-count, and the synthetic test events do not have one either; a drag after a
  double/triple-click extends the selection from the FAR end of the word/line
  (_click_sel_end), an LMB release with count>=2 does NOT wipe the selection;
* RMB — the context menu (contextMenuEvent → _build_context_menu(), the test
  seam): Copy (enabled only with a selection, the same path copy_selection()),
  Paste into the PTY (the same bracketed paste as Ctrl+V: a single
  \x1b[200~…\x1b[201~ block via _send — the multi-input duplicates it just like a key),
  Select All (select_all() — the whole visible grid); the labels — the i18n keys
  terminal.menu.* × en/ru/zh (get_translator, the cache following the ssh_terminal.py pattern).

v1.2.12 — the alternate screen (PYTE82_AUDIT.md batch B): while tscreen.in_alt_screen()
(a TUI owns the grid — vim/htop/mc/less), the mouse wheel and Ctrl+Shift+PageUp/PageDown
do NOT scroll the history (the no-op gate).

v1.2.13 — the wheel in a fullscreen TUI (PYTE82_AUDIT.md batch C): if
tscreen.mouse_tracking() (DECSET 1000/1002/1003) — the wheel goes to the PTY as an
xterm mouse report: SGR (\x1b[<64;{col};{row}M, with 1006; up=64/down=65) or X10
(\x1b[M + [96|97, 32+col, 32+row]; the coordinates are clamped to the grid and to the protocol
limit of 223). Sending — DIRECTLY to terminal_thread.send_data(), NOT through _send(): the coordinates
are session-local, the multi-input must not broadcast them. The alt screen without tracking
stays a no-op (v1.2.12); the passthrough takes precedence over wheel_mode="off".

Threading: paintEvent and snapshot() — the GUI thread; feed() from the SSH thread under the lock
of TerminalScreen — a race in the middle of a frame is excluded.

v1.3.3.4 (ROADMAP "Terminal: working with the output") — the canvas learns to work
with what it shows:
* SEARCH IN THE SCROLLBACK (task 1): Ctrl+Shift+F opens the floating find panel
  (modules/terminal_find_bar.py — the map_search_bar pattern), a case-insensitive
  LITERAL search (re.escape — regex search is explicitly NOT in this version) over
  the visible grid AND the history. The document comes from TerminalScreen.text_lines()
  (history.top → buffer → history.bottom: the same line sequence at any scroll
  position, so a match index is stable) and TerminalScreen.scroll_to_line() brings
  the target line into view with pyte's own pages. Enter/Shift+Enter walk the
  matches with wraparound, the panel shows "k / N", Esc closes the panel and
  RESTORES the history position the search started from. The key lives in this
  widget (the terminal's own keys are the xterm protocol — §14a scope boundary:
  nothing is added to the hotkey registry) and while the panel has the keyboard no
  byte can reach the PTY;
* CLEAR THE SCROLLBACK / RESET THE SCREEN (task 2): two LOCAL context-menu actions
  (TerminalScreen.clear_history() / reset_local()) — not one byte goes to the
  channel;
* SAVE TRANSCRIPT… (task 3): a checkable context-menu item (terminal.menu.save_transcript)
  opens a file dialog and starts a TEE of the session output — the page calls
  write_transcript(data) on the same bytes it feeds to pyte, so the file holds the
  raw stream (exactly the fed bytes, the `script(1)` semantics; ANSI included).
  stop_transcript() is safe to call twice — the page closes it from its idempotent
  shutdown() and no write ever raises into the session teardown;
* EXCLUDING A SESSION FROM MULTI-INPUT (task 5): the checkable terminal.multi_exclude
  item sets the in-memory per-session flag `multi_excluded`; MultiInputHub.broadcast()
  skips such a session and the container badge shows it (terminal.multi_excluded_badge).
  The state is deliberately NOT persisted (a session is short-lived) and the mode's
  own rules (F12, the registry entry, the plaque counter) are unchanged.
"""

import math
import re
import time

# v1.2.9 (ROADMAP "terminal hygiene"): the full wcwidth(3) — the SAME library
# that pyte 0.8.2 itself uses for grid layout (pyte.screens: `from wcwidth import
# wcwidth`); a hard dependency of pyte, so it is always present when pyte is.
try:
    from wcwidth import wcwidth as _wcwidth
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "The terminal canvas requires the 'wcwidth' package (installed together with pyte)"
    ) from e

try:
    from .terminal_screen import PALETTES, resolve_color
except ImportError:
    from modules.terminal_screen import PALETTES, resolve_color

# v1.2.3 (ROADMAP v1.2.3): multi-input — the broadcast hub of the input to all open sessions.
# There is no import cycle: multi_input knows nothing about terminal_widget.
try:
    from .multi_input import get_hub as _get_multi_hub
except ImportError:
    from modules.multi_input import get_hub as _get_multi_hub

# v1.3.3.4 (ROADMAP task 1): the floating find panel — the map_search_bar pattern.
# The module imports only ui/theme (pure data) — no cycle with terminal_widget.
try:
    from .terminal_find_bar import TerminalFindBar
except ImportError:
    from modules.terminal_find_bar import TerminalFindBar

# v1.2.4-fix (multi-input diagnostics): the app logger (lazy, the get_translator
# pattern) — a DEBUG line per broadcast in _send. Without setup_logging
# no records are emitted (the 'sshmap' namespace has no handlers) — safe for tests.
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
            _log_cache["log"] = False  # the logger is unavailable — stay silent from here on
    return _log_cache["log"] or None


# v1.2.7: i18n for the context menu (the cache follows the get_translator pattern
# from modules/ssh_terminal.py — the module is on the hot path, the i18n import is lazy).
_t_cache = None


def get_translator():
    """Safe i18n helper: a cached t() or the "[key]" fallback.

    The terminal.menu.* keys are used ONLY in _build_context_menu(); before
    v1.2.7 the i18n module was not imported at all."""
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


def build_macro_payload(text) -> bytes:
    """v1.3 (ROADMAP v1.3): a command library macro → the payload for the PTY. A pure function.

    A single-line macro — the raw text + a trailing \\n (the Quick Launch path
    semantics: the shell receives "command\\n" and executes the line). A
    multi-line one — a bracketed-paste wrapper \\x1b[200~…\\x1b[201~ with a
    GUARANTEED trailing \\n (the whole block arrives at the shell as ONE input,
    not as line-by-line execution — the semantics of _bracketed_paste());
    CRLF/CR are normalized to \\n. Empty/whitespace-only text — b""
    (send_macro never sends such a payload). Never raises."""
    if not isinstance(text, str) or not text.strip():
        return b""
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in norm:
        if not norm.endswith("\n"):
            norm += "\n"   # the trailing \\n is guaranteed (without doubling)
        return b"\x1b[200~" + norm.encode("utf-8") + b"\x1b[201~"
    return norm.encode("utf-8") + b"\n"


from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPen,
)
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSizePolicy, QWidget


def _fmt_key(ch):
    """The cell formatting key — the raw pyte Char attributes (without the palette).

    The italic field in pyte 0.8.2 is named **italics** (not italic — TERMINAL.md
    fact #1, draft error #1). A run is the maximal sequence of cells with the
    same key; resolve_color() is a pure function of (fg, bg, palette), so the
    colors are consistent within a run.
    """
    return (ch.fg, ch.bg, bool(ch.bold), bool(ch.italics),
            bool(ch.underscore), bool(ch.strikethrough), bool(ch.reverse))


def char_width(data: str) -> int:
    """The full width of a character per wcwidth(3): 0 — zero width (combining/control),
    1 — narrow, 2 — wide (CJK/Fullwidth).

    v1.2.9 (ROADMAP "terminal hygiene"): replaces the east_asian_width W/F heuristic
    of v1.0RC1 — the v1.0 known limitation is closed. The SAME `wcwidth` library
    that pyte 0.8.2 itself uses (pyte.screens: `from wcwidth import wcwidth`)
    for grid layout, so the wide/narrow classification of the canvas always
    matches how pyte places glyphs in the cells (+ the placeholder after a wide one).
    An empty string (a placeholder) → 0; non-printable control characters (-1) are clamped to 0.
    data — the contents of a SINGLE cell: usually one character, but pyte NFC-merges
    combining marks into the preceding cell (a multi-character grapheme cluster),
    so the width = the per-character sum (exactly like pyte's per-character draw());
    on the grid it is always 0/1/2.
    """
    if not data:
        return 0
    total = 0
    for ch in data:
        w = _wcwidth(ch)
        total += 0 if w < 0 else w
    return total


def is_wide_char(data: str) -> bool:
    """Is the glyph wide (double width, CJK/Fullwidth)?

    v1.2.9: the full wcwidth(3) via the `wcwidth` library (the same one pyte 0.8.2 uses),
    instead of the east_asian_width W/F heuristic (v1.0RC1). Important: in pyte 0.8.2 the
    glyph itself is stored with len(data)==1 ("wide" cannot be determined from the data) —
    the WIDE one is the FOLLOWING "placeholder" cell with data==''; split_row_runs skips it.
    """
    return char_width(data) == 2


def split_row_runs(row):
    """Splits a line into runs of identical formatting (a pure function).

    row — a list of pyte Char of length columns. Returns a list of tuples
    (x, text, is_wide): x — the starting cell of the run, text — the joined characters,
    is_wide=True — a single wide glyph (drawn at double width; the following
    placeholder is skipped). Placeholders (data == '') do not belong to any run.

    Unit-tested without a GUI (tests/test_terminal_colors.py) — the regression for the
    draft errors #13/#14 from TERMINAL.md §3 (the XOR cursor, the CJK glyph overlap).
    """
    runs = []
    n = len(row)
    x = 0
    while x < n:
        ch = row[x]
        if not ch.data:            # placeholder after a wide glyph — skip
            x += 1
            continue
        if is_wide_char(ch.data):
            runs.append((x, ch.data, True))
            x += 2                 # glyph + placeholder (at the end of the line — simply falls out of the loop)
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
    """The cells of the rectangular selection in (row, col) coordinates (TERMINAL.md §5.2).

    start/end — (row, col) of the beginning and the end of the selection, THE ORDER
    DOES NOT MATTER (a drag in any direction); columns — the grid width (the middle
    lines of the selection span the full width 0..columns-1). Returns a list of
    (row, col) in reading order: lines top to bottom, within a line left to right.
    A pure function — unit-tested without a GUI (tests/test_terminal_input.py).

    The coordinates are ALWAYS (row, col): tuple comparison = LINE-MAJOR order.
    The regression for draft error #4 (TERMINAL.md §3): there (col, row) was stored
    and compared as tuples — a column-major order, any selection spanning 2+ lines
    highlighted/copied the WRONG cells. The columns are clamped to [0, columns-1]
    (the rows — the caller's responsibility: the mouse is clamped via _cell_at).
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
    """The word ranges of a line: list[(start_col, end_col)], inclusive (v1.2.7).

    row_chars — a list of pyte Char of length columns (one line of a snapshot).
    A word — the maximal run of NON-SPACE cells: the only separators are whitespace
    characters (data.isspace()); punctuation BELONGS to the word ("foo,bar" — one
    word, as in xterm/Windows Terminal). The placeholder of a wide CJK glyph
    (data == '') belongs to the WORD: in pyte 0.8.2 a wide glyph occupies its cell
    + the following placeholder (TERMINAL.md fact #11), so "a中b" — one word
    over 4 cells, not two. A pure function — unit-tested without a GUI
    (tests/test_terminal_selection_menu.py).
    """
    n = len(row_chars)
    units = []
    x = 0
    while x < n:
        d = row_chars[x].data
        if not d or d.isspace():      # a space/empty — not the start of a word
            x += 1
            continue
        start = x
        x += 1
        while x < n:
            d2 = row_chars[x].data
            if d2 == "":              # placeholder after a wide glyph — inside the word
                x += 1
                continue
            if not d2.isspace():
                x += 1
                continue
            break                     # a space — the end of the word
        units.append((start, x - 1))
    return units


# xterm sequences for F1–F12 (the table from draft TERMINAL.md §6/phase 1):
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
    """The cell-based canvas of the pyte screen (v1.0RC1; v1.0RC2 — the keyboard + selection;
    v1.0RC3 — the wheel/Ctrl+Shift+PgUp/PgDn scrollback + the cursor blink;
    v1.2.3 — multi-input: the broadcast of the input to all open sessions;
    v1.2.7 — double/triple-click (word/line) + the right-click context menu;
    v1.2.13 — the wheel in a TUI: SGR/X10 passthrough when mouse tracking is on;
    v1.2.9-fix — Tab/Shift+Tab are intercepted in event(): the Qt 6 focus-change
    mechanism does not pass them to keyPressEvent, without the interception the focus
    left the terminal for the window buttons and \\t never reached the shell).

    tscreen — TerminalScreen (pyte.HistoryScreen + lock); terminal_thread — an object with
    send_data(bytes) (SSHTerminalThread; None — input disabled, rendering and scrollback
    work). multi_hub — the multi-input hub (modules/multi_input.py): None — the module
    default hub (get_hub()); an explicit instance — a test seam for isolation.
    """

    FORMAT_CACHE_LIMIT = 512      # the format cache limit (TERMINAL.md §5.1)
    CURSOR_COLOR = "#e2e8f0"      # the block cursor: the default text color (the classic look)
    SELECTION_COLOR = (59, 130, 246, 90)   # v1.0RC2: the selection overlay (RGBA, alpha≈35%)
    BLINK_INTERVAL_MS = 530       # v1.0RC3: the cursor blink period (ROADMAP task 8)
    DOUBLE_CLICK_MS = 500         # v1.2.7: the double/triple-click interval (the test hook)
    # v1.3.3.4 (ROADMAP task 1): the find-bar overlays. Values — the central theme
    # accents with the alpha of the SELECTION_COLOR precedent (theme.ACCENT for the
    # other matches, theme.SELECTION_AMBER for the CURRENT one — the same
    # amber/blue pair the map uses for "this one" vs "also matches").
    FIND_MATCH_COLOR = (56, 189, 248, 60)     # theme.ACCENT @ ~24%
    FIND_CURRENT_COLOR = (245, 158, 11, 130)  # theme.SELECTION_AMBER @ ~51%
    TRANSCRIPT_SUGGESTED_SUFFIX = ".log"      # the default name of a transcript

    def __init__(self, tscreen, terminal_thread=None, parent=None,
                 palette_name="default", format_cache_limit=FORMAT_CACHE_LIMIT,
                 wheel_mode="scrollback", multi_hub=None):
        super().__init__(parent)
        self.tscreen = tscreen
        self.terminal_thread = terminal_thread
        # v1.2.3 (ROADMAP task 1): the multi-input hub — None = the module default;
        # an explicit instance — a test seam (isolation from the app singleton).
        self._multi_hub = multi_hub
        # v1.1.2RC3 (AUDIT U3): the wheel mode from the terminal_wheel config —
        # "scrollback" (the default, the v1.0RC3 behavior: the wheel = the local scrollback)
        # | "off" (the wheel is not intercepted for the scrollback). An unknown value → the default.
        # v1.2.13: if a TUI enabled mouse tracking (DECSET 1000/1002/1003), the wheel
        # goes to the PTY as an SGR/X10 report — the passthrough takes precedence over "off".
        self._wheel_mode = wheel_mode if wheel_mode in ("scrollback", "off") else "scrollback"
        self._palette_name = palette_name if palette_name in PALETTES else "default"
        self._palette = dict(PALETTES[self._palette_name])
        self._format_cache_limit = int(format_cache_limit)
        self._format_cache = {}   # (fg,bg,bold,italics,underscore,strikethrough) → (QPen,QBrush,QFont)

        self._bg_color = QColor(self._palette["default_bg"])
        self._cursor_color = QColor(self.CURSOR_COLOR)
        self._selection_color = QColor(*self.SELECTION_COLOR)

        # v1.0RC2: the mouse selection — the anchor (press) and the active end (move/release),
        # the coordinates are ALWAYS (row, col); None — no selection.
        self._sel_anchor = None
        self._sel_active = None

        # v1.2.7: the double/triple-click accounting — by the widget itself (QMouseEvent in PySide6
        # carries no click-count; the synthetic test events do not have one either):
        # _click_count increments on a press in the same cell within DOUBLE_CLICK_MS,
        # otherwise it resets to 1. _click_sel_end — the "pinned" end for
        # the drag after a double/triple-click (the far end of the word/line);
        # None — the plain v1.0RC2 press/drag.
        self._click_count = 0
        self._last_click_cell = None
        self._last_click_ms = 0.0
        self._click_sel_end = None

        # v1.0RC3: the cursor blink — a dedicated QTimer (ROADMAP task 8): started in
        # showEvent, stopped in hideEvent (a hidden window does not blink).
        # _cursor_visible=True by default: a widget that is never shown
        # (the offscreen tests) always draws the cursor.
        self._cursor_visible = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(self.BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._toggle_cursor_blink)

        # v1.3.3.4 (ROADMAP task 1): the find bar. The panel is created LAZILY
        # (a session that never searches pays nothing — hide() on a child of the
        # canvas costs 0 px); _find_matches — list[(doc_index, col, length)] over
        # TerminalScreen.text_lines(); _find_current — the index in that list (-1 =
        # nothing to navigate); _find_saved_position — the history position captured
        # on open, restored by Esc ("Esc restores the state").
        self._find_bar = None
        self._find_query = ""
        self._find_matches = []
        self._find_current = -1
        self._find_saved_position = None

        # v1.3.3.4 (ROADMAP task 3): the transcript — a tee of the session output into
        # a local file. The state lives here (the menu that toggles it is this widget's
        # context menu) and the page feeds it in _on_output; the file is opened in
        # BINARY append mode, so the file holds exactly the fed bytes.
        self._transcript_file = None
        self._transcript_path = None
        self._transcript_guard = False   # re-entrancy guard of the checkable menu item
        self._transcript_host = ""       # the host name in the suggested file name

        # v1.3.3.4 (ROADMAP task 5): the per-session multi-input exclusion. In memory
        # only (a session is short-lived — the ROADMAP decision); the hub reads the
        # flag through getattr() in broadcast().
        self._multi_excluded = False

        # AUDIT v0.7.2 (low #18): the system monospace font (as in the HTML path),
        # point size 10 — the defaults = the current behavior.
        self._font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._font.setPointSize(10)
        self._update_metrics()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # the test hook: the stats of the last paint (runs vs per-character drawText)
        self.last_paint_stats = {"rows": 0, "runs": 0, "draw_text_calls": 0}

    # ── metrics/palette/font ──────────────────────────────
    def _update_metrics(self):
        fm = QFontMetricsF(self._font)
        self._cell_w = max(1, int(math.ceil(fm.horizontalAdvance("M"))))
        self._cell_h = max(1, int(math.ceil(fm.height())))
        self._ascent = int(math.ceil(fm.ascent()))

    @property
    def cell_size(self):
        """(width, height) of the cell in pixels."""
        return self._cell_w, self._cell_h

    def set_palette(self, name):
        """The palette switch (v1.0: the terminal_palette config key). False — unknown."""
        if name not in PALETTES:
            return False
        self._palette_name = name
        self._palette = dict(PALETTES[name])
        self._bg_color = QColor(self._palette["default_bg"])
        self._format_cache.clear()
        self.update()
        return True

    def set_font(self, family="", size=10):
        """The font switch (v1.0: the terminal_font/terminal_font_size config keys)."""
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

    # ── format cache (TERMINAL.md §5.1) ───────────────────
    def _format_for(self, fg_hex, bg_hex, bold, italics, underscore, strikethrough):
        """(fg,bg,attributes) → (QPen,QBrush,QFont); a size-limited cache.

        reverse is NOT in the key: it has already been reduced to an fg/bg swap
        before the call — visually identical cells land in one cache entry.
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
        """pyte Char → the concrete hex values (fg, bg); reverse — the swap AFTER the resolution."""
        pal = self._palette
        fg = resolve_color(ch.fg, pal, pal["default_fg"])
        bg = resolve_color(ch.bg, pal, pal["default_bg"])
        if ch.reverse:
            fg, bg = bg, fg
        return fg, bg

    # ── rendering: runs instead of per-character drawText ─
    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._paint(painter)
        except Exception as e:
            # The SSH output is an arbitrary stream; the rendering must not crash the window.
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

        # WA_OpaquePaintEvent: the full background (as in TERMINAL.md §5.3)
        painter.fillRect(self.rect(), QBrush(self._bg_color))

        for y, row in enumerate(rows):
            runs = split_row_runs(row)
            stats["runs"] += len(runs)
            for x, text, is_wide in runs:
                ch0 = row[x]
                fg, bg = self._resolved_colors(ch0)
                has_ink = bool(text.strip())
                # v1.2.10rc3 (a cosmetic audit bug): a whitespace-only run without ink —
                # a fillRect is still needed when the resolved bg ≠ the base fill: a TUI application
                # can explicitly paint an empty line with spaces in its own color (the
                # mc/mcedit viewer area — in a real xterm it is uniformly gray; in the pyte grid
                # such cells carry bg=<color>). The old assumption "the background is already filled"
                # was true only for the spaces with the default background.
                if not has_ink and bg == self._palette["default_bg"]:
                    continue  # spaces with the default background — the base fill already covers them
                pen, brush, font = self._format_for(
                    fg, bg, bool(ch0.bold), bool(ch0.italics),
                    bool(ch0.underscore), bool(ch0.strikethrough))
                painter.setFont(font)
                painter.setPen(pen)
                cell_x, cell_y = x * self._cell_w, y * self._cell_h
                # the wide glyphs — the double width (the font itself draws the glyph wide);
                # the placeholder was already skipped in split_row_runs
                run_cells = 2 if is_wide else len(text)
                painter.fillRect(cell_x, cell_y, run_cells * self._cell_w,
                                 self._cell_h, brush)
                if has_ink:
                    painter.drawText(cell_x, cell_y + self._ascent, text)
                    stats["draw_text_calls"] += 1
            stats["rows"] += 1

        # v1.0RC2: the selection — a semi-transparent overlay over the selected cells.
        # Drawn AFTER the text, so the glyphs are visible through the alpha (as in the
        # classic terminals). selection_cells() gives ONE contiguous range of
        # columns per line — one fillRect per line of the selection.
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

        # v1.3.3.4 (ROADMAP task 1): the find-bar matches — the same translucent
        # overlay technique as the selection (drawn after the text, so the glyphs
        # stay readable); the CURRENT match in amber, the others in the accent blue.
        find_rows = self._visible_find_cells()
        if find_rows:
            painter.setPen(Qt.PenStyle.NoPen)
            brush_other = QBrush(QColor(*self.FIND_MATCH_COLOR))
            brush_current = QBrush(QColor(*self.FIND_CURRENT_COLOR))
            for row, spans in find_rows.items():
                if not (0 <= row < len(rows)):
                    continue
                cell_y = row * self._cell_h
                for col, length, is_current in spans:
                    painter.fillRect(col * self._cell_w, cell_y,
                                     max(1, length) * self._cell_w, self._cell_h,
                                     brush_current if is_current else brush_other)
            stats["find_matches"] = sum(len(v) for v in find_rows.values())

        # The block cursor via swap (TERMINAL.md §3.13): fill the cell with the cursor color
        # + redraw the glyph with the background color; NOT drawn when screen.cursor.hidden
        # (ESC[?25l/h — vim hides the cursor, fact #8) or in the "invisible" phase of the blink
        # (v1.0RC3). When scrolling up into the history pyte hides the cursor itself
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
                painter.setPen(QPen(self._bg_color))  # the glyph — in the background color
                painter.drawText(cell_x, cell_y + self._ascent, ch.data)

        self.last_paint_stats = stats

    def visible_text(self):
        """The text of the visible grid (for tests/debugging); the placeholders give ''."""
        rows, _cx, _cy, _hidden = self.tscreen.snapshot()
        return "\n".join("".join(ch.data for ch in row) for row in rows)

    # ── v1.2.9-fix: Tab/Shift+Tab — Qt 6 intercepts BEFORE keyPressEvent ────
    def event(self, e):
        """v1.2.9-fix (a bug since v1.0RC2, caught in the field): Tab/Shift+Tab left
        the terminal for the window buttons/tabs; \\t never reached the shell — the bash
        autocompletion did not fire, the mc panels did not switch.

        The mechanism (the Qt 6 documentation, QWidget): "The Tab and Shift+Tab keys are only
        passed to the widget if they are not used by the focus-change mechanisms. To
        force those keys to be processed by your widget, you must reimplement
        QWidget::event()" — the bare Tab/Shift+Tab do NOT reach keyPressEvent: Qt itself
        walks the focus through the widget chain and marks the event handled. The
        Key_Tab branch in keyPressEvent (v1.0RC2) only worked on direct calls
        (the tests) — the real events bypassed it, so the bug survived from v1.0RC2 to
        v1.2.9 and the suite did not catch it (the tests called keyPressEvent directly).

        The interception: Tab → \\t, Shift+Tab → \\x1b[Z (xterm) + accept — the focus stays
        on the terminal. Ctrl/Meta+Tab is NOT intercepted (a fall-through into
        super().event() → keyPressEvent — the previous semantics); terminal_thread=None
        — also not intercepted (input disabled = the guard at the top of keyPressEvent).
        All the other events pass through super().event(e) unchanged.

        v1.3.3.4-fix (a real defect found while checking the find key): the canvas must
        OWN its keys whenever it has the focus — the §14a boundary is only true if Qt
        actually delivers them. In `terminal_mode = "tabs"` the session lives INSIDE the
        main window, whose window-level QActions claim Ctrl+F (map search), Ctrl+Shift+F
        (fit map), Ctrl+D (duplicate), Ctrl+Z (undo), Ctrl+S (save), Ctrl+K (palette),
        Delete (delete selection) and the rest of §4.9's defaults. Qt asks the FOCUS
        WIDGET first through a ShortcutOverride event, and a plain QWidget ignores it —
        so the QAction won and the shell never saw the key: Ctrl+D duplicated a map node
        instead of sending \\x04, Ctrl+Z undid the scene instead of SIGTSTP, Delete wiped
        the selection instead of \\x1b[3~, and Ctrl+Shift+F ran "fit map" instead of
        opening the find bar. In `windows` mode none of that happened (a separate
        terminal window has no such QActions) — the two modes contradicted each other.
        Accepting the override for the keys the canvas serves restores the terminal
        semantics in both: the CONTROL combinations and the function/Delete family stay
        with the focused session, while plain typing (which cannot collide) and the
        Alt-only combinations of the menubar mnemonics are NOT claimed.
        """
        if e.type() == QEvent.Type.ShortcutOverride and self._owns_shortcut(e):
            e.accept()   # the terminal owns this key — do not let a QAction fire
            return True
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

    # ── v1.3.3.4-fix: the key family the canvas claims from window-level QActions ──
    # Every Ctrl+… combination (the xterm control codes — Ctrl+C/D/Z/V, the canvas's
    # own Ctrl+Shift+F / Ctrl+Shift+PgUp/PgDn) plus the function keys (the xterm table,
    # F12 = the multi-input exit) and Delete (\\x1b[3~). A plain letter cannot collide
    # with a QAction sequence (all of §4.9's defaults carry Ctrl/Shift/Alt), so typing
    # is deliberately NOT claimed, and neither are the Alt-only combinations (the
    # menubar mnemonics stay reachable while a session has the focus).
    _CLAIMED_KEYS = frozenset({
        Qt.Key.Key_Delete,
        Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3, Qt.Key.Key_F4,
        Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7, Qt.Key.Key_F8,
        Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11, Qt.Key.Key_F12,
    })

    def _owns_shortcut(self, e) -> bool:
        """Does the canvas claim this key from the window-level QActions? (never raises)"""
        try:
            if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return True
            return e.key() in self._CLAIMED_KEYS
        except Exception:  # noqa: BLE001 — a broken event must not break the shortcut map
            return False

    # ── the keyboard: the full table v1.0RC2 ──────────────
    def keyPressEvent(self, event):
        """The full keyboard table (v1.0RC2, ROADMAP task 4; v1.0RC3 — the scrollback).

        * F1–F12 — the xterm sequences (_F_KEY_SEQUENCES);
        * Ctrl+Shift+PageUp/PageDown → SCROLLBACK (v1.0RC3, TERMINAL.md §5.4): the
          interception sits BEFORE the bare PageUp/PageDown check — otherwise the
          fall-through from the Ctrl branch sends \\x1b[5~/\\x1b[6~ to the shell
          (the trap from ROADMAP v1.0RC3 task 7);
          v1.2.12: on the alternate screen (in_alt_screen) — a no-op;
        * the bare PageUp/PageDown → \\x1b[5~/\\x1b[6~ — a forward to the shell (the
          v1.0RC2 semantics preserved: the less/man paging works, the Windows
          Terminal/GNOME/xterm convention);
        * the Left/Right/Up/Down arrows and Home/End — according to the DECCKM state
          (v1.1.2RC3, AUDIT U3): the normal mode → CSI (\\x1b[D/C/A/B, \\x1b[H/\\x1b[F),
          the Application Cursor Keys Mode (smkx \\x1b[?1h — mc/vim/htop) → SS3
          (\\x1bOD/OC/OA/OB, \\x1bOH/\\x1bOF); the choice — _cursor_key_seq() from
          tscreen.application_cursor_keys();
        * Home/End/Delete — the base semantics of the old SSHTerminalTextEdit
          (CSI \\x1b[H / \\x1b[F / \\x1b[3~ — "the semantics of the current code are
          preserved"; Delete/PageUp/PageDown do not depend on DECCKM);
        * Ctrl+C: with a selection — a copy to the clipboard (the v0.9.3 semantics),
          without a selection — \\x03 (SIGINT; acceptance: "Ctrl+C kills top");
        * Ctrl+D → \\x04, Ctrl+Z → \\x1a, Ctrl+V — the bracketed paste (v0.9.4);
        * Tab → \\t / Shift+Tab → \\x1b[Z (v1.2.9-fix): on the real events they are
          intercepted EARLIER — in event() (the Qt 6 focus-change mechanism does not pass
          them to keyPressEvent; without this the focus left for the window buttons and
          \\t never reached the shell);
        * the AltGr guard (TERMINAL.md §3.12): the Ctrl+Alt combinations (on Windows
          AltGr = Ctrl+Alt) do NOT go out as control codes — ignored;
        * F12 in multi-input mode (v1.2.3, ROADMAP task 3) — the EXIT from the mode,
          not a shell key: the RC2 mapping F12→\\x1b[24~ is suspended (the key does
          not reach the shell); the mode is off → F12 works as before (\\x1b[24~).
        """
        if self.terminal_thread is None:
            event.ignore()
            return
        key = event.key()
        mod = event.modifiers()

        if mod & Qt.KeyboardModifier.ControlModifier:
            # the AltGr guard (TERMINAL.md §3.12): the Ctrl+Alt combinations (on Windows
            # AltGr = Ctrl+Alt) must not go out as control codes.
            if mod & Qt.KeyboardModifier.AltModifier:
                event.ignore()
                return
            # v1.0RC3: Ctrl+Shift+PageUp/PageDown → the scrollback (TERMINAL.md §5.4).
            # The interception BEFORE the bare PageUp/PageDown below — without it the
            # fall-through sends \x1b[5~/\x1b[6~ to the shell (the ROADMAP v1.0RC3 task 7 trap).
            if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) \
                    and mod & Qt.KeyboardModifier.ShiftModifier:
                # v1.2.12: the alt screen (a TUI owns the grid) — a no-op; the wheel in a TUI
                # goes out only with mouse tracking (v1.2.13), the keys remain local.
                if self.tscreen.in_alt_screen():
                    return
                if key == Qt.Key.Key_PageUp:
                    self.scroll_page_up()
                else:
                    self.scroll_page_down()
                return
            # v1.3.3.4 (ROADMAP task 1): Ctrl+Shift+F — the find bar. The key belongs to
            # the CANVAS (§14a scope boundary): the terminal's own keys are the xterm
            # protocol and are NOT in the hotkey registry, so a plain Ctrl+F keeps going
            # to the shell as \x06 (the readline forward-char) exactly as before.
            if key == Qt.Key.Key_F and mod & Qt.KeyboardModifier.ShiftModifier:
                self.open_find()
                event.accept()
                return
            if key == Qt.Key.Key_C:
                # v0.9.3 semantics (preserved): Ctrl+C copies with a selection,
                # without a selection — SIGINT.
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

        # v1.2.3 (ROADMAP task 3): multi-input — F12 = the EXIT from the mode, not Esc
        # (Esc goes to the shell as \x1b!). When the mode is on the RC2 mapping
        # F12→\x1b[24~ is suspended: the key does not reach the shell, the mode
        # is switched off. The mode is off → a fall-through to the F1–F12 table as in v1.0RC2.
        if key == Qt.Key.Key_F12 and self._multi_active():
            self._multi_exit()
            event.accept()
            return

        seq = _F_KEY_SEQUENCES.get(key)      # F1–F12 (the full table, v1.0RC2)
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
            # CSI H in the normal mode (as in SSHTerminalTextEdit v0.8); under DECCKM —
            # SS3 H (\x1bOH), the xterm semantics (AUDIT U3).
            self._send(self._cursor_key_seq(b"H"))
            return
        if key == Qt.Key.Key_End:
            self._send(self._cursor_key_seq(b"F"))   # CSI F / SS3 F depending on DECCKM
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
        # Tab/Shift+Tab: on the REAL events they are intercepted earlier — in event()
        # (the Qt 6 focus-change mechanism does not hand them to keyPressEvent; see event()).
        # The branches are kept for the direct keyPressEvent calls (the test seam).
        if key == Qt.Key.Key_Tab:
            self._send(b"\t")
            return
        if key == Qt.Key.Key_Backtab:
            self._send(b"\x1b[Z")   # xterm Shift+Tab (mc, the reverse completion in bash)
            return
        if key == Qt.Key.Key_Escape:
            self._send(b"\x1b")
            return
        # The arrows — according to the DECCKM state (AUDIT U3): CSI \x1b[D/C/A/B in the
        # normal mode, SS3 \x1bOD/OC/OA/OB when mc/vim/htop enabled the Application
        # Cursor Keys Mode (smkx \x1b[?1h). Without this the arrows "do not work"
        # in mc (the app waits for SS3), and in the bash underneath they scroll history.
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
        """The cursor-key sequence for the DECCKM state (AUDIT U3).

        suffix — the byte suffix ("A"/"B"/"C"/"D" for the arrows, "H"/"F" for Home/End):
        the normal mode → CSI (\x1b[A…); the Application Cursor Keys Mode (DECCKM,
        private mode 1 — mc/vim/htop send smkx \x1b[?1h at startup) → SS3
        (\x1bOA…). The state — tscreen.application_cursor_keys(); there too
        the verified pyte 0.8.2 fact is recorded: DECCKM is stored in screen.mode
        as 32 (the private modes with the <<5 shift), not as 1.
        """
        if self.tscreen.application_cursor_keys():
            return b"\x1bO" + suffix
        return b"\x1b[" + suffix

    # ── v1.2.3: multi-input (the broadcast at the single input point) ────────
    def _resolve_multi_hub(self):
        """The multi-input hub of this widget: the explicit one (the constructor — the
        test seam, the attribute self._multi_hub) or the module default (get_hub — the
        singleton, the same one as MainWindow's). The name is NOT `_multi_hub`: the hub
        attribute would shadow the method of the same name in self.<name> (TypeError:
        'NoneType' is not callable)."""
        hub = self._multi_hub
        if hub is not None:
            return hub
        try:
            return _get_multi_hub()
        except Exception:
            return None  # the module is unavailable — input works as in v1.2.2

    def _multi_active(self) -> bool:
        """Whether the multi-input mode is on (for the F12 exit in keyPressEvent)."""
        try:
            hub = self._resolve_multi_hub()
            return bool(hub is not None and hub.active)
        except Exception:
            return False

    def _multi_exit(self):
        """The exit from the multi-input mode (F12 / UI): the hub's listeners reset the UI."""
        try:
            hub = self._resolve_multi_hub()
            if hub is not None:
                hub.set_active(False)
        except Exception:
            pass  # the hub is mid-teardown — the key simply does not go to the shell

    def _send(self, data: bytes):
        """The SINGLE point where the user input is sent (v1.2.3, ROADMAP task 1).

        The bytes go to send_data() of THIS session; when the multi-input mode is on —
        the same bytes are duplicated to ALL the other open sessions of the registry
        (hub.broadcast: the source is skipped, the dead threads are filtered out).
        From here pass both the printable keys and the service ones
        (Return/Backspace/Esc/the arrows), and the Ctrl+V bracketed paste — in the multi
        mode everything typed is duplicated."""
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
                # v1.2.4-fix (diagnostics): a DEBUG line per broadcast —
                # the log shows how many sessions actually received the bytes (0 →
                # an empty registry/dead threads; N>0 → the bytes went to all the live ones).
                _log = _get_app_log()
                if _log is not None:
                    _log.debug(
                        f"multi-input broadcast: {len(data)}B -> {sent} session(s)")
            except Exception:
                pass  # a broadcast failure must not break the input of the active session

    def _bracketed_paste(self):
        """Ctrl+V — the bracketed paste (carried over from v0.9.4): a multi-line clipboard
        arrives at the shell as a SINGLE block, not as line-by-line input."""
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

    def send_macro(self, text) -> bool:
        """v1.3 (ROADMAP v1.3): send a command library macro to the PTY of THIS session.

        The sending — DIRECTLY to terminal_thread.send_data(), NOT through _send(): the
        macro is addressed ONLY to the active session (the pre-approved ROADMAP v1.3
        decision) — the multi-input broadcast would have duplicated it to all the open
        sessions (the precedent: the wheel passthrough of v1.2.13). The payload is built
        by build_macro_payload() (single-line — raw + \\n; multi-line — the bracketed
        paste). Never raises; False — an empty payload, no thread, or a dead/closed channel."""
        payload = build_macro_payload(text)
        if not payload or self.terminal_thread is None:
            return False
        channel = getattr(self.terminal_thread, "channel", None)
        if channel is None or channel.closed:
            return False
        try:
            self.terminal_thread.send_data(payload)
            return True
        except Exception:   # noqa: BLE001 — a dead channel/thread mid-teardown
            return False

    # ── v1.0RC3: scrollback (wheel + Ctrl+Shift+PgUp/PgDn, TERMINAL.md §5.4) ──
    def scroll_page_up(self):
        """One page of the history up (Ctrl+Shift+PageUp / the wheel up).

        True — the position changed (a repaint); at the top edge pyte is a no-op.
        A local operation: it also works with terminal_thread=None."""
        if self.tscreen.scroll_up():
            self.update()
            return True
        return False

    def scroll_page_down(self):
        """One page down, toward the live line (Ctrl+Shift+PageDown / the wheel down)."""
        if self.tscreen.scroll_down():
            self.update()
            return True
        return False

    def wheelEvent(self, event):
        """The mouse wheel: v1.2.13 — the TUI mouse tracking first, then the scrollback.

        The check order (v1.2.13, PYTE82_AUDIT.md batch C):
        1. tscreen.mouse_tracking() — DECSET 1000/1002/1003 is on (a TUI waits for
           mouse reports) → the wheel goes to the PTY as an xterm report: SGR
           (\\x1b[<64;{col};{row}M, with 1006 — up=64/down=65) or X10
           (\\x1b[M + [96|97, 32+col, 32+row]). The coordinates — the 1-based cell from
           the mouse position, clamped to the grid; X10 additionally to the protocol limit of 223.
           Sending — directly terminal_thread.send_data(), NOT through _send() (the
           coordinates are session-local — the multi-input must not broadcast them).
           The passthrough takes precedence over wheel_mode="off".
        2. in_alt_screen() WITHOUT tracking → a no-op (v1.2.12: a TUI owns the grid,
           the history does not scroll; the event is not consumed — the ancestor
           QScrollAreas are not in the containers, the propagation is harmless).
        3. Otherwise — the current v1.0RC3 behavior: the history scrollback (up → prev_page,
           down → next_page; at the edges pyte is a no-op), wheel_mode="off" →
           event.ignore(). The scrollback under "off" stays on Ctrl+Shift+PageUp/PageDown.

        The modes are read on EVERY event (a TUI toggles them during a session —
        htop enables 1003+1006 at start, disables them on exit; caching is not allowed).
        The auto-return to the live line on new output is built into pyte (before_event);
        the window's _on_output calls widget.update(), so the snapshot is visible immediately.
        """
        enabled, sgr = self.tscreen.mouse_tracking()   # v1.2.13: read on every event
        if not enabled and self.tscreen.in_alt_screen():
            return  # the alt screen without tracking — a no-op (v1.2.12)
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
        """v1.2.13: the wheel → the PTY (an xterm mouse report, SGR/X10). Never raises.

        The coordinates — the 1-based cell from the mouse position (event.position() in
        the widget coordinates), clamped to the grid [1..columns]×[1..lines]: the widget
        can be wider/taller than the grid by the remainder of the font-metrics rounding.
        SGR (DECSET 1006): \\x1b[<64;{col};{row}M — wheel up = button 64, down = 65
        (ctlseqs: buttons 4/5 = the button event codes 1/2 + 64), no limits on the
        coordinates. X10: \\x1b[M + [96|97, 32+col, 32+row] — value+32 (up=96, down=97);
        the protocol limits the coordinates to 223 (=255−32) — they are clamped
        (ctlseqs "Extended coordinates": the extensions only via UTF-8 1005 /
        SGR 1006; on the ultra-wide grids of >223 columns the X10 report is inexact,
        SGR is not).

        The sending — DIRECTLY to terminal_thread.send_data(), NOT through _send(): the
        wheel is addressed to THIS session (its coordinates), the multi-input broadcast
        to all open sessions would have delivered someone else's TUI reports with foreign
        coordinates — a deliberate decision, pinned by a test.
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
            col = min(col, 223)   # the X10 protocol limit (see the docstring)
            row = min(row, 223)
            data = b"\x1b[M" + bytes([96 if up else 97, 32 + col, 32 + row])
        try:
            self.terminal_thread.send_data(data)
        except Exception:
            pass  # a dead channel/thread mid-teardown — the wheel silently does not go out

    # ══════════════════════════════════════════════════════════════════════════
    # v1.3.3.4 (ROADMAP task 1): the find bar — search in the visible grid AND
    # the history. The panel is only the input surface; the search, the counter
    # and the viewport movement are HERE (a single source of truth).
    # ══════════════════════════════════════════════════════════════════════════

    def _ensure_find_bar(self) -> TerminalFindBar:
        """The find panel (created on first use — a session that never searches pays nothing)."""
        bar = self._find_bar
        if bar is None:
            bar = TerminalFindBar(self)
            bar.query_changed.connect(self._on_find_query)
            bar.next_requested.connect(self.find_next)
            bar.prev_requested.connect(self.find_prev)
            bar.close_requested.connect(self.close_find)
            self._find_bar = bar
        return bar

    def open_find(self):
        """Open the find panel (Ctrl+Shift+F / the context menu) and focus its input.

        The history position is remembered here — Esc restores it, so a search never
        leaves the user somewhere else in the scrollback. A repeat call keeps the
        ALREADY CAPTURED position (the second Ctrl+Shift+F must not overwrite the
        origin with wherever the first search navigated to).
        """
        bar = self._ensure_find_bar()
        if self._find_saved_position is None:
            try:
                self._find_saved_position = self.tscreen.scroll_info()[0]
            except Exception:  # noqa: BLE001 — a screen under teardown: the restore is skipped
                self._find_saved_position = None
        bar.place(self.width(), self.height())
        bar.show()
        bar.raise_()
        if bar.query.strip():
            self._refresh_find_matches()   # recompute against the current document
        bar.focus_input()

    def close_find(self, restore: bool = True):
        """Close the panel (Esc / the × button); with restore — back to the pre-search view.

        The matches are dropped (nothing is highlighted any more) and the history
        position captured on open is re-applied through TerminalScreen.scroll_to_position()
        (the paging scrollback can only land on a page border — "the state before the
        search", not a pixel-exact restore). Never raises: a dead C++ object or a
        screen under teardown must not break the close path.
        """
        bar = self._find_bar
        if bar is not None:
            try:
                bar.hide()
            except RuntimeError:
                self._find_bar = None   # the C++ object is gone — stop touching it
                bar = None
        self._find_matches = []
        self._find_current = -1
        self._find_query = ""
        if bar is not None and bar.query:
            bar.set_query("")   # emits query_changed → the handler already cleared the state
        if restore and self._find_saved_position is not None:
            try:
                self.tscreen.scroll_to_position(self._find_saved_position)
            except Exception:  # noqa: BLE001 — teardown race: the viewport restore is cosmetic
                pass
        self._find_saved_position = None
        self.update()
        try:
            self.setFocus()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    @property
    def find_active(self) -> bool:
        """Is the find panel open? (the test/debug seam)

        isHidden(), not isVisible(): the panel is a CHILD of the canvas, so Qt reports
        it invisible while the session's window is not shown (the offscreen tests, a
        background tab) even though it is open; the hidden FLAG is the state the widget
        itself controls (hide() in __init__/close_find, show() in open_find) — the same
        check the multi-input plaque uses in the suite.
        """
        bar = self._find_bar
        if bar is None:
            return False
        try:
            return not bar.isHidden()
        except RuntimeError:
            return False

    def find_state(self) -> dict:
        """The state of the search: {"query", "current" (1-based), "total"} — the test seam.

        current is 0 while there is nothing to navigate (no query / no matches) —
        the panel then shows "No matches" (`terminal.find.count` is only rendered
        with a real pair).
        """
        current = self._find_current + 1 if self._find_current >= 0 else 0
        return {"query": self._find_query, "current": current,
                "total": len(self._find_matches)}

    def _on_find_query(self, text: str):
        """A change of the query → a fresh match list, the first match revealed."""
        self._find_query = text or ""
        self._refresh_find_matches()

    def _find_document_lines(self) -> list:
        """The searchable text: TerminalScreen.text_lines() (history + live grid)."""
        lines = self.tscreen.text_lines()
        return lines if isinstance(lines, list) else []

    def _refresh_find_matches(self):
        """Recompute the matches of the current query over the WHOLE scrollback document.

        A case-insensitive LITERAL search: the query is `re.escape`d, so a user's
        ".*" is a dot and a star, not a pattern (regex search is explicitly not in
        this version). re.IGNORECASE (not str.lower()) keeps the match OFFSETS valid
        in the ORIGINAL line even for the rare case where a lowercase mapping
        changes the string length. Every occurrence is collected (overlapping ones
        included — "aa" in "aaa" is two matches, as in every terminal's find).
        """
        query = self._find_query.strip()
        matches = []
        if query:
            try:
                pattern = re.compile(re.escape(query), re.IGNORECASE)
            except Exception:  # noqa: BLE001 — a broken pattern (never in practice): no matches
                pattern = None
            if pattern is not None:
                for index, line in enumerate(self._find_document_lines()):
                    for m in pattern.finditer(line):
                        matches.append((index, m.start(), m.end() - m.start()))
        self._find_matches = matches
        total = len(matches)
        self._find_current = 0 if total else -1
        if total:
            self._reveal_find_match()
        self._update_find_counter()
        self.update()

    def _update_find_counter(self):
        """Push "k / N" (or the empty state) into the panel — i18n resolved at call time."""
        bar = self._find_bar
        if bar is None:
            return
        total = len(self._find_matches)
        try:
            bar.set_count(self._find_current + 1 if total else 0, total)
        except RuntimeError:
            self._find_bar = None

    def _reveal_find_match(self):
        """Bring the current match into view (the viewport scrolls, the panel stays put)."""
        if not (0 <= self._find_current < len(self._find_matches)):
            return
        index = self._find_matches[self._find_current][0]
        try:
            self.tscreen.scroll_to_line(index)
        except Exception:  # noqa: BLE001 — a teardown race: the reveal is cosmetic
            return

    def find_next(self) -> bool:
        """Enter: the next match, wrapping around to the first one. False — no matches."""
        return self._step_find(+1)

    def find_prev(self) -> bool:
        """Shift+Enter: the previous match, wrapping around to the last one."""
        return self._step_find(-1)

    def _step_find(self, delta: int) -> bool:
        """Move by delta through the matches with WRAPAROUND (the acceptance of task 1)."""
        total = len(self._find_matches)
        if total <= 0:
            self._update_find_counter()
            return False
        self._find_current = (self._find_current + delta) % total
        self._reveal_find_match()
        self._update_find_counter()
        self.update()
        return True

    def _visible_find_cells(self):
        """{grid_row: [(col_start, length, is_current)]} — the matches on the VISIBLE grid.

        The document index maps to a grid row through TerminalScreen.history_top_len()
        (the number of history lines above the screen): reading it at PAINT time keeps
        the highlight glued to the text while the user scrolls with the wheel.
        """
        if not self._find_matches:
            return {}
        try:
            top_len = self.tscreen.history_top_len()
            lines = getattr(self.tscreen, "lines", 24)
        except Exception:  # noqa: BLE001 — a teardown race: no highlight
            return {}
        out = {}
        for i, (index, col, length) in enumerate(self._find_matches):
            row = index - top_len
            if 0 <= row < lines:
                out.setdefault(row, []).append((col, length, i == self._find_current))
        return out

    # ══════════════════════════════════════════════════════════════════════════
    # v1.3.3.4 (ROADMAP task 2): clear the scrollback / reset the screen — LOCAL
    # actions (the context menu), not one byte to the PTY.
    # ══════════════════════════════════════════════════════════════════════════

    def clear_scrollback(self) -> bool:
        """Drop the pyte history; the live grid stays as it is (TerminalScreen.clear_history()).

        The "scrollback disabled" semantics of `terminal_history_lines = 0` applied to
        the content that is already there: the history is emptied, the depth setting is
        not touched (new output accumulates again). The find state is dropped with it —
        a match index into a document that no longer exists is worse than no highlight.
        """
        self._drop_find_state()
        try:
            self.tscreen.clear_history()
        except Exception:  # noqa: BLE001 — a teardown race: the clear is a no-op
            return False
        self.update()
        return True

    def reset_screen(self) -> bool:
        """A full LOCAL re-init of the grid (the "the screen is a mess" case) + a repaint.

        pyte's reset (grid cleared, cursor homed, modes/margins/tabstops back to the
        defaults, history dropped) — the remote program is NOT told and keeps writing
        into the fresh grid. The find state is dropped together with the document.
        """
        self._drop_find_state()
        try:
            self.tscreen.reset_local()
        except Exception:  # noqa: BLE001 — a teardown race: the reset is a no-op
            return False
        self.update()
        return True

    def _drop_find_state(self):
        """Forget the matches (the document they index into is about to change)."""
        self._find_matches = []
        self._find_current = -1
        bar = self._find_bar
        if bar is not None:
            try:
                bar.set_count(0, 0)
            except RuntimeError:
                self._find_bar = None

    # ══════════════════════════════════════════════════════════════════════════
    # v1.3.3.4 (ROADMAP task 3): the transcript — a tee of the session output into
    # a local file. The page feeds it in _on_output (the single output path) and
    # closes it from shutdown(); nothing here ever raises into the session.
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def transcript_active(self) -> bool:
        """Is the session being written to a local file?"""
        return self._transcript_file is not None

    @property
    def transcript_path(self):
        """The path of the active transcript (None — no transcript)."""
        return self._transcript_path if self.transcript_active else None

    def start_transcript(self, path: str) -> bool:
        """Start (or restart) the tee into `path` — a BINARY append. False on an I/O error.

        Binary append: the file receives exactly the bytes that were fed to pyte
        (the `script(1)` semantics — the raw session stream, ANSI sequences
        included), which is also what the acceptance pins. An existing file is
        APPENDED to (a transcript of a second session of the same host is the
        common case), never truncated — a wrong path cannot destroy anything.
        """
        self.stop_transcript()
        if not path:
            return False
        try:
            f = open(path, "ab")
        except OSError as e:
            _log = _get_app_log()
            if _log is not None:
                _log.warning(f"transcript: cannot open {path}: {e}")
            return False
        self._transcript_file = f
        self._transcript_path = path
        return True

    def stop_transcript(self):
        """Close the transcript (idempotent, never raises) — the session teardown path."""
        f = self._transcript_file
        self._transcript_file = None
        self._transcript_path = None
        if f is None:
            return
        try:
            f.flush()
            f.close()
        except Exception:  # noqa: BLE001 — a full disk / a closed descriptor must not block the close
            pass

    def write_transcript(self, data: bytes):
        """Append the fed bytes to the transcript (a no-op without an active one).

        Called by TerminalSessionPage._on_output on the SAME bytes it feeds to pyte;
        every failure is swallowed and the transcript is stopped: a broken file must
        never raise into the session teardown (the ROADMAP requirement of task 3) and
        must not retry a dead descriptor on every chunk either. The write is FLUSHED
        right away — the point of a transcript is to be tail-able while the session
        runs (and a crash of the application must not cost the last block).
        """
        f = self._transcript_file
        if f is None or not data:
            return
        try:
            f.write(data)
            f.flush()
        except Exception:  # noqa: BLE001 — a disk error stops the tee, the session lives on
            _log = _get_app_log()
            if _log is not None:
                _log.warning("transcript: write failed — stopping the tee")
            self.stop_transcript()

    def _suggested_transcript_name(self) -> str:
        """The default file name of the dialog: sshmap-<host>-<YYYYmmdd-HHMMSS>.log."""
        host = getattr(self, "_transcript_host", "") or "session"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(host)) or "session"
        return f"sshmap-{safe}-{stamp}{self.TRANSCRIPT_SUGGESTED_SUFFIX}"

    def set_transcript_host(self, host: str):
        """The host name used in the suggested file name (the page knows its server)."""
        self._transcript_host = host or ""

    # ── v1.3.3.4 (ROADMAP task 5): the multi-input exclusion (in memory, per session) ──
    @property
    def multi_excluded(self) -> bool:
        """Is this session excluded from the multi-input broadcast? (read by the hub)"""
        return self._multi_excluded

    def set_multi_excluded(self, excluded: bool):
        """Exclude/include THIS session; the mode UI is refreshed without a state change.

        The flag is per session and in memory (the ROADMAP decision — not persisted);
        MultiInputHub.broadcast() reads it through getattr() and skips the session,
        and hub.refresh() makes the plaque counter and the tab badges follow (the mode
        is off — refresh() re-renders the hidden UI, which is a harmless no-op).
        """
        self._multi_excluded = bool(excluded)
        hub = self._resolve_multi_hub()
        if hub is not None:
            try:
                hub.refresh()   # the plaque counter + the "NO MULTI" badge follow
            except Exception:  # noqa: BLE001 — a UI refresh must not break the toggle
                pass

    # ── v1.3.3.1 (invariant): re-text on a language switch ─────────────────────
    def retranslate(self):
        """v1.3.3.4: re-text the find panel (the canvas keeps no other strings).

        The context menu is rebuilt on every right click and resolves its labels at
        that moment, so only the OPEN find panel needs to be re-texted. Never raises —
        the dead-C++-object discipline of every container method.
        """
        bar = self._find_bar
        if bar is None:
            return
        try:
            bar.retranslate()
        except RuntimeError:
            self._find_bar = None   # the C++ object is gone — stop touching it

    # ── v1.0RC3: the cursor blink (a dedicated QTimer, ROADMAP task 8) ─────
    def resizeEvent(self, event):
        """v1.3.3.4: keep the floating find panel at the top right of the canvas.

        The panel is a child of the widget but OUTSIDE the layout (it floats over the
        grid, the map_search_bar pattern), so Qt never repositions it — every real
        canvas resize (a window resize, a tab switch, a page without the command
        library panel) places it again.
        """
        super().resizeEvent(event)
        bar = self._find_bar
        if bar is None:
            return
        try:
            bar.place(self.width(), self.height())
        except RuntimeError:
            self._find_bar = None   # the C++ object is gone — stop touching it

    def showEvent(self, event):
        super().showEvent(event)
        self._cursor_visible = True      # reset the phase when the window is shown
        if not self._blink_timer.isActive():
            self._blink_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._blink_timer.stop()         # a hidden window does not blink (ROADMAP v1.0RC3)

    def _toggle_cursor_blink(self):
        self._cursor_visible = not self._cursor_visible
        self.update()

    # ── the mouse selection + the copy (v1.0RC2, task 5) ────
    def _cell_at(self, pos):
        """A pixel point → (row, col), clamped to the bounds of the tscreen grid."""
        cols = getattr(self.tscreen, "columns", 80)
        lines = getattr(self.tscreen, "lines", 24)
        x = max(0, pos.x()) // self._cell_w
        y = max(0, pos.y()) // self._cell_h
        return min(y, lines - 1), min(x, cols - 1)

    def has_selection(self):
        """Whether there is an active selection (a drag; a plain click is not a selection)."""
        return (self._sel_anchor is not None and self._sel_active is not None
                and self._sel_anchor != self._sel_active)

    def _selected_cells(self):
        """The cells of the current selection: list[(row, col)] via the pure selection_cells()."""
        if not self.has_selection():
            return []
        cols = getattr(self.tscreen, "columns", 80)
        return selection_cells(self._sel_anchor, self._sel_active, cols)

    def clear_selection(self):
        self._sel_anchor = None
        self._sel_active = None
        self._click_sel_end = None   # v1.2.7: the pin for the drag after a double/triple-click
        self.update()

    def selected_text(self):
        """The selection text for the clipboard: the lines are joined with \\n, the
        trailing spaces of the lines are trimmed (the wide-glyph placeholders give '' — harmless)."""
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
        """Ctrl+C with a selection — a copy to the system clipboard (the v0.9.3 semantics).
        True — copied; False — no selection / the clipboard is unavailable / the text is empty."""
        text = self.selected_text()
        if not text:
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True

    # ── mouse: LMB press → drag → release (v1.0RC2; v1.2.7 — double/triple-click) ─
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            # v1.2.7: the click counter (QMouseEvent carries no click-count — we count ourselves):
            # a press in the same cell within DOUBLE_CLICK_MS → count+1, otherwise 1.
            # IMPORTANT: time.monotonic() — SECONDS, DOUBLE_CLICK_MS — milliseconds
            # (the comparison without ×1000 would have given a "double-click" within 500 seconds).
            now_ms = time.monotonic() * 1000.0
            if (self._click_count > 0 and self._last_click_cell == cell
                    and now_ms - self._last_click_ms <= self.DOUBLE_CLICK_MS):
                self._click_count += 1
            else:
                self._click_count = 1
            self._last_click_cell = cell
            self._last_click_ms = now_ms

            if self._click_count >= 3:
                # a triple-click — the whole line (ROADMAP v1.2.7 task 1)
                self._select_line(cell)
            elif self._click_count == 2:
                # a double-click — the word under the cursor
                self._select_word(cell)
            else:
                self._sel_anchor = cell
                self._sel_active = cell       # a plain click — not a selection yet
                self._click_sel_end = None
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._sel_anchor is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            # v1.2.7: a drag AFTER a double/triple-click — the pinned end =
            # the far end of the word/line (_click_sel_end), the selection extends from it.
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
                # v1.2.7: a release after a double/triple-click does NOT wipe
                # the selection (a plain click below would have overwritten _sel_active with
                # the release position and reset the one-cell word). The drag was already
                # handled in mouseMoveEvent; here only the pin is reset.
                self._click_sel_end = None
                self.update()
                event.accept()
                return
            # The release position — the end of the selection (a drag can end without
            # an intermediate Move event).
            self._sel_active = self._cell_at(event.position().toPoint())
            # A plain click (a press/release in one cell) — clears the selection.
            if self._sel_active == self._sel_anchor:
                self._sel_anchor = None
                self._sel_active = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── v1.2.7: the double/triple-click (ROADMAP v1.2.7 task 1) ───────────────
    def _select_word(self, cell):
        """A double-click — select the word on the line under the cursor.

        A word — word_units() (the maximal run of non-space cells; the placeholder of
        a wide CJK glyph belongs to the word). A click on a space — a no-op: the
        current selection does not change. _click_sel_end — the far end of the word
        (the one nearer to the click is NOT pinned): a drag after a double-click extends
        the selection from it, as in xterm."""
        rows, _cx, _cy, _hidden = self.tscreen.snapshot()
        row, col = cell
        if not (0 <= row < len(rows)):
            return
        for start, end in word_units(rows[row]):
            if start <= col <= end:
                self._sel_anchor = (row, start)
                self._sel_active = (row, end)
                # the drag pin — the far end of the word from the click point
                self._click_sel_end = (row, end) if col - start < end - col else (row, start)
                return
        self._click_sel_end = None   # a click on a space — the selection does not change

    def _select_line(self, cell):
        """A triple-click — the whole line, 0..columns-1 (ROADMAP v1.2.7 task 1).

        The trailing whitespace on copy is trimmed by selected_text() (rstrip) anyway,
        so "the whole line" = the full visible column range. _click_sel_end —
        the far end of the line from the click point (the drag extends in both directions)."""
        cols = getattr(self.tscreen, "columns", 80)
        lines = getattr(self.tscreen, "lines", 24)
        row, col = cell
        r = max(0, min(int(row), lines - 1))
        self._sel_anchor = (r, 0)
        self._sel_active = (r, cols - 1)
        self._click_sel_end = (r, cols - 1) if col * 2 < cols else (r, 0)

    # ── v1.2.7: the right-click context menu (ROADMAP v1.2.7 task 2) ──────────
    def select_all(self):
        """Select all — the whole visible grid (the context menu, the Ctrl+A semantics)."""
        cols = getattr(self.tscreen, "columns", 80)
        lines = getattr(self.tscreen, "lines", 24)
        self._sel_anchor = (0, 0)
        self._sel_active = (lines - 1, cols - 1)
        self._click_sel_end = None
        self.update()

    def _build_context_menu(self):
        """The QMenu of the right-click context menu (v1.2.7; v1.3.3.4 — +4 items).

        The test seam: contextMenuEvent builds the menu with this method and only shows
        it — the tests call _build_context_menu() directly and trigger the QActions,
        without entering menu.exec() (the offscreen hang). The labels — the i18n
        `terminal.menu.*` / `terminal.find.*` / `terminal.multi_exclude` keys
        (en/ru/zh/de). Copy — enabled ONLY with a selection; Paste — only with a live
        thread (terminal_thread), the same path as Ctrl+V (_bracketed_paste → _send:
        the bracketed-paste block to the PTY + the multi-input broadcast).

        v1.3.3.4 (ROADMAP tasks 1–3, 5) — four items, all of them LOCAL:
          * Find… (Ctrl+Shift+F) — opens the floating find panel. Labelled with the
            panel's own placeholder key (the ROADMAP key set of this version has no
            separate menu string for it: terminal.find.placeholder reads
            "Find in terminal…", which is exactly what the menu says);
          * Clear scrollback / Reset screen — the two local actions of task 2 (no
            bytes to the PTY: pyte's history is dropped / the grid is re-initialized);
          * Save transcript… — CHECKABLE: on — a file dialog + a tee of the output,
            off — the file is closed (task 3; the checkmark IS the on/off state);
          * Exclude from multi-input — CHECKABLE, per session, in memory (task 5).
        """
        t = get_translator()
        menu = QMenu(self)
        act_find = menu.addAction(t("terminal.find.placeholder"))
        act_find.triggered.connect(self.open_find)
        menu.addSeparator()
        act_copy = menu.addAction(t("terminal.menu.copy"))
        act_copy.setEnabled(self.has_selection())
        act_copy.triggered.connect(self.copy_selection)
        act_paste = menu.addAction(t("terminal.menu.paste"))
        act_paste.setEnabled(self.terminal_thread is not None)
        act_paste.triggered.connect(self._bracketed_paste)
        act_all = menu.addAction(t("terminal.menu.select_all"))
        act_all.triggered.connect(self.select_all)
        menu.addSeparator()
        act_clear = menu.addAction(t("terminal.menu.clear_scrollback"))
        act_clear.triggered.connect(self.clear_scrollback)
        act_reset = menu.addAction(t("terminal.menu.reset_screen"))
        act_reset.triggered.connect(self.reset_screen)
        # The transcript toggle: created manually + connected to toggled(bool) — the
        # PySide6 6.11 gotcha #10 (addAction(text, slot) drops the state).
        act_tr = menu.addAction(t("terminal.menu.save_transcript"))
        act_tr.setCheckable(True)
        act_tr.setChecked(self.transcript_active)
        # The action is passed through the lambda: a cancelled dialog must put the
        # checkmark back, and the action is the only handle on it at that moment.
        act_tr.toggled.connect(lambda checked, a=act_tr: self.toggle_transcript(checked, action=a))
        menu.addSeparator()
        act_multi = menu.addAction(t("terminal.multi_exclude"))
        act_multi.setCheckable(True)
        act_multi.setChecked(self._multi_excluded)
        act_multi.toggled.connect(self.set_multi_excluded)
        return menu

    def toggle_transcript(self, on: bool, action=None):
        """The transcript menu item: on — ask for a file and start the tee; off — close it.

        The file dialog is a module attribute (QFileDialog) — the same seam as QMenu
        in the tests. A cancelled dialog (or an I/O error) puts the checkmark back
        without touching the previous state; the guard flag keeps that programmatic
        setChecked(False) from re-entering this method.
        """
        if self._transcript_guard:
            return
        if not on:
            self.stop_transcript()
            return
        try:
            path, _filter = QFileDialog.getSaveFileName(
                self, get_translator()("terminal.menu.save_transcript"),
                self._suggested_transcript_name(), "")
        except Exception:  # noqa: BLE001 — a native dialog failure must not break the terminal
            path = ""
        if path and self.start_transcript(path):
            return
        if action is not None:
            self._transcript_guard = True
            try:
                action.setChecked(False)
            except RuntimeError:
                pass  # the menu was already destroyed — nothing to reset
            finally:
                self._transcript_guard = False



    def contextMenuEvent(self, event):
        """The RMB — the context menu (v1.2.7). Never raises: a menu-build failure
        (a teardown race) is ignored; an exec failure is logged (not swallowed silently —
        the v0.7.2 audit pattern from map_view.py)."""
        try:
            menu = self._build_context_menu()
        except Exception:
            event.ignore()
            return
        if menu is None:
            event.ignore()
            return
        try:
            # v1.2.7-fix (manual testing): QContextMenuEvent.globalPos() already
            # returns a QPoint (unlike QMouseEvent.globalPosition() → a QPointF) —
            # the extra .toPoint() raised an AttributeError that the old except
            # swallowed silently: "the right-click does nothing" without a single visible
            # error. The coordinates — as they are.
            menu.exec(event.globalPos())
        except Exception as e:  # noqa: BLE001 — a GUI component must not crash the app
            _log = _get_app_log()
            if _log is not None:
                _log.error(f"contextMenuEvent: menu.exec failed: {e}")
        event.accept()
