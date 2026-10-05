# -*- coding: utf-8 -*-
"""The cell-based terminal canvas — QWidget + QPainter over the pyte screen (`modules/terminal_screen.py`).

EVERY GLYPH IS PAINTED AT ITS OWN CELL: the glyph-to-cell mapping is the PURE `run_glyphs()`, the pen is
never left to the font's own widths and `font_grid_problems()` is the gate over `grid_metrics()`. The
cursor GEOMETRY is the PURE `cursor_shape_rect()` over the DECLARED `CURSOR_STYLES`
(`resolve_cursor_style()` reads the config); `FORMAT_CACHE_LIMIT` caps the format cache. The canvas is a
FACADE over its clusters — the key map and the ONE input point (`terminal_widget_input.py`), the mouse
family (`..._mouse.py`), the find bar (`..._find.py`), the transcript (`..._transcript.py`) and the local
selection (`..._selection.py`) — each resolving a facade global through `MODULE_FACADE_SEAMS` below.
`feed()` runs under the screen's lock, painting on the GUI thread; mechanism — `DOCUMENTATION.md` §14a,
§64."""

import math

# The full `wcwidth(3)` — the SAME library pyte 0.8.2 itself uses for grid layout
# (`pyte.screens`: `from wcwidth import wcwidth`); a hard dependency of pyte, so it is always present
# when pyte is. Since the fork's patch 0005 the grid measures a CELL with `wcswidth`: a cell may hold a
# grapheme cluster (a ZWJ emoji, a base + mark) and `wcswidth` is not a per-code-point sum — it knows
# the emoji ZWJ sequences, so the canvas must read the same table as `Screen.draw()`.
try:
    from wcwidth import wcswidth as _wcswidth, wcwidth as _wcwidth
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "The terminal canvas requires the 'wcwidth' package (installed together with pyte)"
    ) from e

try:
    from .terminal_screen import PALETTES, resolve_color
except ImportError:
    from modules.terminal_screen import PALETTES, resolve_color

# v1.6.4 (ROADMAP task 5): the pinned scrollback — the canvas reads the MODE of its screen
# (`terminal_scroll`) to decide whether new output may move the view and what "the user wants
# the live line again" means. The resolver is the screen module's (ONE declaration, one default).
try:
    from .terminal_screen import (SCROLL_MODE_DEFAULT as _SCROLL_MODE_DEFAULT,
                                  SCROLL_MODE_PIN as _SCROLL_MODE_PIN)
except ImportError:
    from modules.terminal_screen import (SCROLL_MODE_DEFAULT as _SCROLL_MODE_DEFAULT,
                                         SCROLL_MODE_PIN as _SCROLL_MODE_PIN)

# v1.2.3 (ROADMAP v1.2.3): multi-input — the broadcast hub of the input to all open sessions.
# There is no import cycle: multi_input knows nothing about terminal_widget.
try:
    from .multi_input import get_hub as _get_multi_hub
except ImportError:
    from modules.multi_input import get_hub as _get_multi_hub

# v1.3.3.4 (ROADMAP task 1): the floating find panel — the map_search_bar pattern. The panel itself
# is imported by `terminal_widget_find.py`, which owns `_ensure_find_bar()`.

# v1.5rc4 (ROADMAP task 5): the ONE visible-focus indicator of the three keyboard
# domains — the terminal canvas shows the same ring as the map and the sidebar, in the
# STRONG accent role of v1.5rc1 (never a new colour). The module imports only
# ui/theme + ui/theme_qss — no cycle with terminal_widget.
try:
    from ui import focus_ring as _focus_ring_mod
except ImportError:
    try:
        from ..ui import focus_ring as _focus_ring_mod
    except ImportError:  # a stripped build — the canvas simply has no ring
        _focus_ring_mod = None

# the app logger (lazy, the get_translator
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


def build_macro_payload(text, bracketed_paste: bool = True) -> bytes:
    """v1.3 (ROADMAP v1.3): a command library macro → the payload for the PTY. A pure function.

    A single-line macro — the raw text + a trailing \\n (the Quick Launch path
    semantics: the shell receives "command\\n" and executes the line). A
    multi-line one — a bracketed-paste wrapper \\x1b[200~…\\x1b[201~ with a
    GUARANTEED trailing \\n (the whole block arrives at the shell as ONE input,
    not as line-by-line execution — the semantics of _bracketed_paste());
    CRLF/CR are normalized to \\n. Empty/whitespace-only text — b""
    (send_macro never sends such a payload). Never raises.

    `bracketed_paste` (v1.7.5.1, N44) is the ADDITIVE argument the caller with a screen passes:
    the wrapper is what the protocol asks for, so it is applied only while the application has
    enabled DECSET 2004 (`TerminalScreen.bracketed_paste_enabled()`). The default stays True, which
    is the shipped output for the callers that have no screen to ask.
    """
    if not isinstance(text, str) or not text.strip():
        return b""
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in norm:
        if not norm.endswith("\n"):
            norm += "\n"   # the trailing \\n is guaranteed (without doubling)
        if not bracketed_paste:
            return norm.encode("utf-8")
        return b"\x1b[200~" + norm.encode("utf-8") + b"\x1b[201~"
    return norm.encode("utf-8") + b"\n"


# The paste markers themselves, stripped from a clipboard before it is wrapped (v1.7.5.1, N44): a
# clipboard carrying `\x1b[201~` would END the paste early and the rest would arrive as TYPED input.
PASTE_MARKERS = ("\x1b[200~", "\x1b[201~")


def strip_paste_markers(text) -> str:
    """Drop the bracketed-paste markers from a clipboard. PURE — never a partial escape left behind."""
    out = str(text if text is not None else "")
    for marker in PASTE_MARKERS:
        out = out.replace(marker, "")
    return out


from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPen,
)
from PySide6.QtWidgets import QFileDialog, QMenu, QSizePolicy, QWidget

# The canvas FACADE over its clusters: the key map and the ONE input point, the mouse family, the find
# bar, the transcript and the local selection. The module-level helpers a mixin resolves at call time
# through `host_attr` stay HERE (`PURE_HELPERS` below and this module's own globals) — a mixin never
# imports the facade module, which would be a cycle.
try:
    from .terminal_widget_input import TerminalInputMixin
    from .terminal_widget_mouse import TerminalMouseMixin
    from .terminal_widget_find import TerminalFindMixin
    from .terminal_widget_transcript import TerminalTranscriptMixin
    from .terminal_widget_selection import TerminalSelectionMixin
except ImportError:  # flat launch from the project root
    from terminal_widget_input import TerminalInputMixin
    from terminal_widget_mouse import TerminalMouseMixin
    from terminal_widget_find import TerminalFindMixin
    from terminal_widget_transcript import TerminalTranscriptMixin
    from terminal_widget_selection import TerminalSelectionMixin


def _fmt_key(ch):
    """The cell formatting key — the raw pyte Char attributes (without the palette).

    The italic field in pyte 0.8.2 is named **italics** (not italic — the field itself:
    `third_party/pyte-patches/MANIFEST.md`). A run is the maximal sequence of cells with the
    same key; resolve_color() is a pure function of (fg, bg, palette), so the
    colors are consistent within a run.
    """
    return (ch.fg, ch.bg, bool(ch.bold), bool(ch.italics),
            bool(ch.underscore), bool(ch.strikethrough), bool(ch.reverse))


def char_width(data: str) -> int:
    """The full width of a character per wcwidth(3): 0 — zero width (combining/control),
    1 — narrow, 2 — wide (CJK/Fullwidth/emoji).

    v1.2.9 (ROADMAP "terminal hygiene"): replaces the east_asian_width W/F heuristic
    of v1.0RC1 — the v1.0 known limitation is closed. The SAME `wcwidth` library
    that pyte 0.8.2 itself uses (pyte.screens: `from wcwidth import wcwidth`)
    for grid layout, so the wide/narrow classification of the canvas always
    matches how pyte places glyphs in the cells (+ the placeholder after a wide one).
    An empty string (a placeholder) → 0; non-printable control characters (-1) are clamped to 0.
    data — the contents of a SINGLE cell. v1.5.7.1 (pyte fork patch 0005): pyte stores a
    GRAPHEME CLUSTER in one cell now (a ZWJ emoji, a base + mark, an NFC-merged pair), and its
    grid width comes from `wcswidth(cluster)` — NOT from the per-code-point sum (the wcwidth
    package makes a ZWJ family two cells, the sum says four). A multi-code-point cell therefore
    measures `wcswidth` too; a single code point keeps `wcwidth` (the 0.8.2 table).
    """
    if not data:
        return 0
    if len(data) > 1:
        w = _wcswidth(data)
        return 0 if w < 0 else w
    w = _wcwidth(data)
    return 0 if w < 0 else w


def is_wide_char(data: str) -> bool:
    """Is the glyph wide (double width, CJK/Fullwidth/emoji)?

    v1.2.9: the full wcwidth(3) via the `wcwidth` library (the same one pyte 0.8.2 uses),
    instead of the east_asian_width W/F heuristic (v1.0RC1). Important: pyte stores the WIDE
    glyph itself in the cell ("wide" cannot be read off the widest cell alone) — the second
    half is the FOLLOWING "placeholder" cell with data==''; split_row_runs skips it.
    v1.5.7.1 (patch 0005): the wide cell may hold a whole grapheme cluster (a ZWJ emoji is
    `wcswidth == 2`), which `char_width()` measures with the same table the grid uses.
    """
    return char_width(data) == 2


# ── the GLYPH GRID ──────────────────────────────────────────────────────────
# A run is painted GLYPH BY GLYPH: with ONE `drawText` at the run's starting x the pen would advance
# with the FONT's own glyph widths while the grid reserves `ceil(advance("M"))` per cell — the
# correctness of every row rests on an invariant nobody checked, and `terminal_font` is free text. The
# canvas draws at `(start_col + k) * cell_w`, and `font_grid_problems()` is the gate of that grid.
FONT_GRID_SAMPLE = ("M", "i", "W", " ", "\u2500", "\u2502", "\u250c", "\u253c",
                    "\u2588", "\u2591", "\u30b3")
#: The run length the drift of `font_grid_problems()` is expressed over (cells).
FONT_GRID_RUN_CELLS = 100
#: How far a glyph may sit off the cell before it is a defect: sub-pixel rounding is
#: the font engine's own business, a half pixel is a wandering column.
FONT_GRID_TOLERANCE_PX = 0.01


def glyph_label(ch: str) -> str:
    """A printable label for one sample glyph: the character itself, or `U+XXXX`."""
    try:
        if len(ch) == 1 and 0x20 <= ord(ch) < 0x7f:
            return ch
    except TypeError:
        return "?"
    return " ".join(f"U+{ord(c):04X}" for c in str(ch))


class FontGridMetrics:
    """The metrics `font_grid_problems()` reads: the cell width and one glyph's advance.

    A tiny adapter, so the gate can be driven by a SYNTHETIC non-integral object (the
    RED case of the topical test) exactly like it is driven by the live widget font.
    """

    __slots__ = ("cell_w", "_advance")

    def __init__(self, cell_w, advance):
        self.cell_w = max(1, int(cell_w))
        self._advance = advance

    def advance(self, ch: str) -> float:
        """The advance the painter's pen moves for `ch` (the font's own width)."""
        return float(self._advance(ch))


def font_grid_problems(metrics, sample=FONT_GRID_SAMPLE):
    """The glyphs of `sample` whose ADVANCE does not match the cell — the grid gate.

    `metrics` answers `cell_w` (the reserved cell width in pixels) and
    `advance(ch)` (the width the font itself gives that glyph) — `FontGridMetrics`
    over a live `QFontMetricsF`, or any object with the same two members. Returns ONE
    tuple per offending glyph:

        (label, advance, cell_w, drift_px, drift_cells)

    where `drift_px` is `advance − cell_w` (the per-glyph error) and `drift_cells` is
    the SAME drift accumulated over a `FONT_GRID_RUN_CELLS`-cell run, expressed in
    cells — the number the acceptance of the version quotes ("a 100-cell run drifts
    +0.00 px"). A glyph within `FONT_GRID_TOLERANCE_PX` is not reported, so the
    shipped font answers an EMPTY list and a font that is not integral answers rows.
    Pure (no Qt) — the topical test runs it against both objects.
    """
    cell_w = max(1, int(getattr(metrics, "cell_w", 1)))
    problems = []
    for ch in sample:
        try:
            advance = float(metrics.advance(ch))
        except Exception:  # noqa: BLE001 — an unmeasurable glyph is not a grid defect
            continue
        drift_px = advance - float(cell_w)
        if abs(drift_px) <= FONT_GRID_TOLERANCE_PX:
            continue
        problems.append((glyph_label(ch), advance, cell_w, drift_px,
                         drift_px * FONT_GRID_RUN_CELLS / float(cell_w)))
    return problems


def run_glyphs(row, start, text):
    """The glyph of EVERY cell of a NARROW run — a cell may hold a grapheme cluster.

    A run's `text` is the join of the cell data (`split_row_runs`), and one cell of the
    pyte fork holds a whole cluster (patch 0005: a base + mark, a ZWJ emoji, an
    NFC-merged pair), so iterating over the CODE POINTS of `text` would drift the run by
    exactly the cells that carry more than one. Walking the row and consuming as many
    code points as each cell contributed keeps the glyph-to-cell mapping exact.
    Pure (the topical test reads it without a widget).
    """
    glyphs = []
    consumed = 0
    total = len(text)
    idx = start
    n = len(row)
    while consumed < total and idx < n:
        data = row[idx].data
        glyphs.append(data)
        consumed += len(data)
        idx += 1
    if consumed < total:
        glyphs.append(text[consumed:])   # a row out of step — never lose the ink
    return glyphs


def split_row_runs(row):
    """Splits a line into runs of identical formatting (a pure function).

    row — a list of pyte Char of length columns. Returns a list of tuples
    (x, text, is_wide): x — the starting cell of the run, text — the joined characters,
    is_wide=True — a single wide glyph (drawn at double width; the following
    placeholder is skipped). Placeholders (data == '') do not belong to any run.

    Unit-tested without a GUI (tests/test_terminal_colors.py) — the regression for the
    two pre-1.0 defects (the XOR cursor, the CJK glyph overlap).
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
    """The cells of the rectangular selection in (row, col) coordinates (DOCUMENTATION.md §14a).

    start/end — (row, col) of the beginning and the end of the selection, THE ORDER
    DOES NOT MATTER (a drag in any direction); columns — the grid width (the middle
    lines of the selection span the full width 0..columns-1). Returns a list of
    (row, col) in reading order: lines top to bottom, within a line left to right.
    A pure function — unit-tested without a GUI (tests/test_terminal_input.py).

    The coordinates are ALWAYS (row, col): tuple comparison = LINE-MAJOR order.
    The regression for the pre-1.0 (col, row) mistake: there (col, row) was stored
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
    + the following placeholder (MANIFEST.md), so "a中b" — one word
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


# ── v1.6.2 (ROADMAP task 4): the cursor SHAPES (pure geometry, no Qt) ────────
# The cursor was a full-cell block. It is one of three DECLARED shapes now, and the
# default is the thin blink line of Windows Terminal.
CURSOR_STYLE_BLOCK = "block"          # the historical painting: the whole cell, glyph swapped
CURSOR_STYLE_BAR = "bar"              # a thin vertical line at the LEFT edge of the cell
CURSOR_STYLE_UNDERLINE = "underline"  # a thin horizontal line at the BOTTOM edge of the cell
CURSOR_STYLES = (CURSOR_STYLE_BLOCK, CURSOR_STYLE_BAR, CURSOR_STYLE_UNDERLINE)

#: The shape a canvas uses when nothing else says otherwise (the `terminal_cursor_style`
#: default of `modules/ssh_terminal.py` refers to THIS constant, so the two cannot drift).
CURSOR_STYLE_DEFAULT = CURSOR_STYLE_BAR

#: The thickness of the two line shapes, in device pixels (the cell's own height/width for
#: the other dimension). 2 px is the Windows Terminal look at the usual 100 % scaling; the
#: clamp inside `cursor_shape_rect()` keeps the mark visible on a narrow cell.
CURSOR_BAR_WIDTH = 2
CURSOR_UNDERLINE_HEIGHT = 2


def resolve_cursor_style(style) -> str:
    """A configured (or foreign) value → one of `CURSOR_STYLES`.

    A missing / empty / unknown / non-string value answers `CURSOR_STYLE_DEFAULT`: the
    `terminal_wheel` / `resolution` rule — a broken setting is the default, never an error.
    Pure, no Qt.
    """
    if isinstance(style, str) and style.strip().lower() in CURSOR_STYLES:
        return style.strip().lower()
    return CURSOR_STYLE_DEFAULT


# ── v1.6.4 (ROADMAP task 3): Ctrl+wheel = the FONT ZOOM ─────────────────────
# The DECLARED point-size range of the canvas font. `terminal_font_size` validates a stored
# value against exactly this range (`modules/ssh_terminal.py: load_terminal_settings()`), so a
# zoom can never step outside what the settings hub can show and what a restart can restore.
FONT_SIZE_MIN = 6
FONT_SIZE_MAX = 72


def cursor_shape_rect(style, x, y, width, height):
    """The rectangle the cursor is painted in, for a cell of `width × height` at `(x, y)`.

    Pure (no Qt, no widget) — the topical test reads the geometry HERE and the canvas only
    paints what this answers; it returns `(x, y, w, h)` in whole pixels. `block` is the whole
    cell; `bar` is `CURSOR_BAR_WIDTH` wide against the LEFT edge and the full height;
    `underline` is `CURSOR_UNDERLINE_HEIGHT` tall against the BOTTOM edge and the full width;
    any other value is the DECLARED default. The line shapes CLAMP to the cell (never 0 px:
    a cursor that vanishes is a worse lie than a thick one).
    """
    style = resolve_cursor_style(style)
    width, height = max(1, int(width)), max(1, int(height))
    if style == CURSOR_STYLE_BLOCK:
        return (int(x), int(y), width, height)
    if style == CURSOR_STYLE_UNDERLINE:
        line = max(1, min(int(CURSOR_UNDERLINE_HEIGHT), height))
        return (int(x), int(y) + height - line, width, line)
    line = max(1, min(int(CURSOR_BAR_WIDTH), width))
    return (int(x), int(y), line, height)


class TerminalWidget(TerminalInputMixin, TerminalMouseMixin, TerminalFindMixin,
                     TerminalTranscriptMixin, TerminalSelectionMixin, QWidget):
    """The cell-based canvas of the pyte screen (v1.0RC1; v1.0RC2 — the keyboard + selection;
    v1.0RC3 — the wheel/Ctrl+Shift+PgUp/PgDn scrollback + the cursor blink;
    v1.2.3 — multi-input: the broadcast of the input to all open sessions;
    v1.2.7 — double/triple-click (word/line) + the right-click context menu;
    v1.2.13 — the wheel in a TUI: SGR/X10 passthrough when mouse tracking is on;
    Tab/Shift+Tab are intercepted in event(): the Qt 6 focus-change
    mechanism does not pass them to keyPressEvent, without the interception the focus
    left the terminal for the window buttons and \\t never reached the shell).

    tscreen — TerminalScreen (pyte.HistoryScreen + lock); terminal_thread — an object with
    send_data(bytes) (SSHTerminalThread; None — input disabled, rendering and scrollback
    work). multi_hub — the multi-input hub (modules/multi_input.py): None — the module
    default hub (get_hub()); an explicit instance — a test seam for isolation.
    """

    FORMAT_CACHE_LIMIT = 512      # the format cache limit (DOCUMENTATION.md §14a)
    CURSOR_COLOR = "#e2e8f0"      # the cursor ink: the default text color (the classic look)
    # v1.6.2 (ROADMAP task 4): the cursor SHAPE. `CURSOR_STYLES` / `CURSOR_STYLE_DEFAULT` and
    # the geometry live at module level (`resolve_cursor_style()` / `cursor_shape_rect()`), so
    # the topical test reads them without a widget; the class only carries the ACTIVE value.
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
                 wheel_mode="scrollback", multi_hub=None,
                 cursor_style=CURSOR_STYLE_DEFAULT):
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
        # v1.6.2 (ROADMAP task 4): the cursor shape from the terminal_cursor_style config —
        # "block" (the historical slab) | "bar" (the default: the thin blinking line) |
        # "underline". An unknown value → the declared default (resolve_cursor_style()).
        self._cursor_style = resolve_cursor_style(cursor_style)
        self._palette_name = palette_name if palette_name in PALETTES else "default"
        self._palette = dict(PALETTES[self._palette_name])
        self._format_cache_limit = int(format_cache_limit)
        self._format_cache = {}   # (fg,bg,bold,italics,underscore,strikethrough) → (QPen,QBrush,QFont)

        # v1.5.7: the COMMAND HISTORY hook of this canvas. The owning page installs its own
        # recorder here (TerminalSessionPage.record_sent_command) and send_macro() calls it
        # after a successful send — the canvas itself knows no store and no i18n.
        self.command_sent_hook = None
        # v1.6.4 (ROADMAP task 3): the FONT ZOOM hook — Ctrl+wheel steps the point size and the
        # owning page persists it (ONE debounced timer, the §4.2 `CmdEditTextNote` pattern)
        # and reports the new size in the session's status line. The canvas owns the GESTURE
        # and the metrics; the config key and the words belong to the page (the
        # `command_sent_hook` split: the canvas stays free of stores and of i18n).
        self.font_zoom_hook = None

        self._bg_color = QColor(self._palette["default_bg"])
        self._cursor_color = QColor(self.CURSOR_COLOR)
        self._selection_color = QColor(*self.SELECTION_COLOR)

        # v1.0RC2: the mouse selection — the anchor (press) and the active end (move/release),
        # the coordinates are ALWAYS (row, col); None — no selection.
        self._sel_anchor = None
        self._sel_active = None

        # The double/triple-click accounting — by the widget itself (a QMouseEvent in PySide6 carries no
        # click-count, and the synthetic test events have none either): `_click_count` increments on a press
        # in the same cell within `DOUBLE_CLICK_MS`, otherwise it resets to 1. `_click_sel_end` — the
        # "pinned" end for the drag after a double/triple-click (the far end of the word/line); `None` —
        # the plain press/drag.
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

        # The find bar. The panel is created LAZILY (a session that never searches pays nothing — `hide()`
        # on a child of the canvas costs 0 px); `_find_matches` — `list[(doc_index, col, length)]` over
        # `TerminalScreen.text_lines()`; `_find_current` — the index in that list (-1 = nothing to
        # navigate); `_find_saved_position` — the history position captured on open, restored by Esc
        # ("Esc restores the state").
        self._find_bar = None
        self._find_query = ""
        self._find_matches = []
        self._find_current = -1
        self._find_saved_position = None
        # v1.6.4 (ROADMAP task 5): the CONTENT offset captured beside the position — what Esc
        # restores under `terminal_scroll = "pin"` (the position drifts there).
        self._find_saved_top = None

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
        # v1.5rc4 (ROADMAP task 5): the terminal is one of the three keyboard domains and
        # says so with the SAME ring the map and the sidebar show. In `terminal_mode =
        # "tabs"` the session shares the window with the map, so the ring is also the
        # answer to "where do my keys go?".
        self._focus_ring = (_focus_ring_mod.FocusRing(owner=self)
                            if _focus_ring_mod is not None else None)

    # ── metrics/palette/font ──────────────────────────────
    def _update_metrics(self):
        # v1.6.3 (ROADMAP task 1): KERNING OFF — the grid is fixed, and a kerned pair of
        # glyphs is drawn closer than the two cells it occupies, which is exactly the
        # drift the per-cell painting below exists to prevent. Set on the FONT (before the
        # metrics are read) so every cached QFont copy and every drawText shares it.
        self._font.setKerning(False)
        fm = QFontMetricsF(self._font)
        self._cell_w = max(1, int(math.ceil(fm.horizontalAdvance("M"))))
        self._cell_h = max(1, int(math.ceil(fm.height())))
        self._ascent = int(math.ceil(fm.ascent()))

    def grid_metrics(self) -> FontGridMetrics:
        """The live metrics of THIS canvas for `font_grid_problems()` (v1.6.3).

        The gate's data source: run it with the user's `terminal_font` /
        `terminal_font_size` (and the display scale) and the question the `mc` report
        asked — "does this font land on the cell?" — closes either way.
        """
        fm = QFontMetricsF(self._font)
        return FontGridMetrics(self._cell_w, fm.horizontalAdvance)

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

    # ── v1.6.4 (ROADMAP task 3): Ctrl+wheel = the font zoom ─────────────────

    def font_size(self) -> int:
        """The LIVE point size of the canvas font (the zoom's read seam)."""
        try:
            return int(self._font.pointSize())
        except (TypeError, ValueError):   # a broken QFont (never in practice) → the default
            return 10

    def zoom_font(self, step: int) -> int:
        """Step the font by `step` points, clamped to `FONT_SIZE_MIN..FONT_SIZE_MAX`.

        ONE `set_font()` call does the whole switch: the metrics (`_cell_w/_cell_h/_ascent`),
        the format cache and — through the page's hook — the PTY grid follow it in one step,
        so the grid of the emulator and the grid of the canvas can never disagree about the
        size of a cell. A step at either END of the range is a no-op that still answers the
        size in force; the hook is what persists the value and writes the status line.

        Returns the point size in force after the call. Never raises.
        """
        try:
            delta = int(step)
        except (TypeError, ValueError):
            return self.font_size()
        current = self.font_size()
        size = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, current + delta))
        if size != current:
            self.set_font(size=size)
        hook = getattr(self, "font_zoom_hook", None)
        if callable(hook):
            try:
                hook(size)
            except Exception:   # noqa: BLE001 — a zoom must never break on a page teardown
                pass
        return size

    # ── v1.6.2 (ROADMAP task 4): the cursor shape ───────────────────────────
    def cursor_style(self) -> str:
        """The ACTIVE shape — one of `CURSOR_STYLES`."""
        return self._cursor_style

    def set_cursor_style(self, style) -> str:
        """Apply a shape (`terminal_cursor_style`); an unknown value → the declared default.

        The blink phase and the hide rule are untouched — only the geometry of the mark
        changes — so the canvas only needs a repaint.
        """
        self._cursor_style = resolve_cursor_style(style)
        self.update()
        return self._cursor_style

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._cell_w * 80, self._cell_h * 24)

    # ── format cache (DOCUMENTATION.md §14a) ───────────────────
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

        # WA_OpaquePaintEvent: the full background (the canvas paints every pixel itself)
        painter.fillRect(self.rect(), QBrush(self._bg_color))

        for y, row in enumerate(rows):
            runs = split_row_runs(row)
            stats["runs"] += len(runs)
            for x, text, is_wide in runs:
                ch0 = row[x]
                fg, bg = self._resolved_colors(ch0)
                has_ink = bool(text.strip())
                # A whitespace-only run still needs a `fillRect` when the resolved bg ≠ the base fill: a TUI
                # can explicitly paint an empty line with spaces in its own colour (the mc/mcedit viewer
                # area — in a real xterm it is uniformly gray; in the pyte grid such cells carry
                # bg=<color>). The assumption "the background is already filled" holds only for the spaces
                # with the default background.
                if not has_ink and bg == self._palette["default_bg"]:
                    continue  # spaces with the default background — the base fill already covers them
                pen, brush, font = self._format_for(
                    fg, bg, bool(ch0.bold), bool(ch0.italics),
                    bool(ch0.underscore), bool(ch0.strikethrough))
                painter.setFont(font)
                painter.setPen(pen)
                cell_x, cell_y = x * self._cell_w, y * self._cell_h
                # the wide glyphs — the double width (the font itself draws the glyph wide);
                # the placeholder was already skipped in split_row_runs.
                # v1.6.3 (ROADMAP task 1): a NARROW run's cell count comes from its GLYPHS, not
                # from len(text) — one cell may hold a grapheme cluster (patch 0005).
                glyphs = [text] if is_wide else run_glyphs(row, x, text)
                run_cells = 2 if is_wide else len(glyphs)
                painter.fillRect(cell_x, cell_y, run_cells * self._cell_w,
                                 self._cell_h, brush)
                if has_ink:
                    # GLYPH BY GLYPH at its own cell. ONE `drawText` per run would advance the pen with
                    # the FONT's widths while the grid reserves `ceil(advance("M"))` per cell, so a font
                    # whose glyph advances differ from the cell shifted everything after the first such
                    # glyph — a wandering column in a box-drawing TUI. The batched `fillRect` per run and
                    # the per-run font/pen switch are unchanged; a WIDE glyph is one cell pair, one call.
                    for k, glyph in enumerate(glyphs):
                        painter.drawText((x + k) * self._cell_w,
                                         cell_y + self._ascent, glyph)
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

        # The cursor (`DOCUMENTATION.md` §64): the SHAPE is declared — the block fills the cell and swaps
        # the glyph, while the bar and the underline paint a thin line and leave the text alone. It is NOT
        # drawn when `screen.cursor.hidden` (`ESC[?25l/h` — vim hides it) or in the "invisible" phase of
        # the blink. When scrolling up into the history pyte hides the cursor itself (`after_event`:
        # hidden = not (position == size and DECTCEM)).
        if (not hidden and self._cursor_visible and rows
                and 0 <= cy < len(rows) and 0 <= cx < len(rows[cy])):
            ch = rows[cy][cx]
            cell_x, cell_y = cx * self._cell_w, cy * self._cell_h
            cur_x, cur_y, cur_w, cur_h = cursor_shape_rect(
                self._cursor_style, cell_x, cell_y, self._cell_w, self._cell_h)
            painter.fillRect(cur_x, cur_y, cur_w, cur_h, QBrush(self._cursor_color))
            # the glyph is swapped ONLY under the block: it is the shape that covers the cell,
            # and a bar over the first pixel of a letter must not repaint that letter.
            if self._cursor_style == CURSOR_STYLE_BLOCK and ch.data and ch.data != " ":
                fg, bg = self._resolved_colors(ch)
                _, _, font = self._format_for(
                    fg, bg, bool(ch.bold), bool(ch.italics),
                    bool(ch.underscore), bool(ch.strikethrough))
                painter.setFont(font)
                painter.setPen(QPen(self._bg_color))  # the glyph — in the background color
                painter.drawText(cell_x, cell_y + self._ascent, ch.data)

        self.last_paint_stats = stats

        # v1.5rc4 (ROADMAP task 5): the visible focus of the terminal domain. Painted
        # LAST (over the grid, the selection, the find marks and the cursor) with the ONE
        # shared painter, so the frame is identical to the map's and the sidebar's.
        if self._focus_ring is not None and self._focus_ring.is_active():
            self._focus_ring.paint(painter, self.rect())

    # ── v1.5rc4 (ROADMAP task 5): the VISIBLE FOCUS of the terminal ───────────
    # The canvas is a keyboard domain of its own (the xterm protocol of §14a): the ring
    # tells the user that the shell — not the map behind it in `terminal_mode = "tabs"` —
    # owns the keys. Drawn over the grid with the ONE shared painter (ui/focus_ring.py).

    def focus_ring_active(self) -> bool:
        """True while the canvas owns the keyboard (the topical test's seam)."""
        return bool(self._focus_ring is not None and self._focus_ring.is_active())

    def focusInEvent(self, event):
        """v1.5rc4: the canvas took the keyboard — show the focus ring."""
        if self._focus_ring is not None:
            self._focus_ring.set_active(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        """v1.5rc4: the keyboard went elsewhere — drop the focus ring."""
        if self._focus_ring is not None:
            self._focus_ring.set_active(False)
        super().focusOutEvent(event)

    def visible_text(self):
        """The text of the visible grid (for tests/debugging); the placeholders give ''."""
        rows, _cx, _cy, _hidden = self.tscreen.snapshot()
        return "\n".join("".join(ch.data for ch in row) for row in rows)


    # ── v1.0RC3: scrollback (wheel + Ctrl+Shift+PgUp/PgDn, DOCUMENTATION.md §14a) ──
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

    def _release_pin(self) -> bool:
        """v1.6.4 (ROADMAP task 5): the USER-INTENT half of the pinned scrollback.

        Under `terminal_scroll = "pin"` the view keeps the lines the user is reading while
        output arrives; typing (or pasting) means "I want to see what the shell answers", so
        the canvas returns to the live line HERE — through the screen's ONE bulk release. The
        wheel needs no call: scrolling DOWN to the bottom reaches the live line by itself and
        the pin has nothing left to hold.

        An active selection is dropped with the move — the v1.1.2RC3 (N7) reasoning
        the page's output guard applies: the (row, col) coordinates are pinned on
        the HISTORICAL grid, and Ctrl+C after the return would copy other cells. False — the
        mode is off or the view is already live (the "live" mode pays one attribute read).
        """
        if getattr(self.tscreen, "scroll_mode", _SCROLL_MODE_DEFAULT) != _SCROLL_MODE_PIN:
            return False
        release = getattr(self.tscreen, "scroll_to_live", None)
        if not callable(release):
            return False
        try:
            moved = bool(release())
        except Exception:   # noqa: BLE001 — a teardown race: the input path must not break
            return False
        if moved:
            self.clear_selection()
            self.update()
        return moved

    def pinned(self) -> bool:
        """Is this canvas reading the scrollback while the pin holds the view? (the test seam)"""
        return bool(getattr(self.tscreen, "pinned", lambda: False)())


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


    # ── v1.3.3.1 (invariant): the theme / language hooks of the canvas ─────────
    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to the canvas.

        The canvas paints its grid from the terminal's OWN output palette, which
        the UI theme deliberately does not touch (AGENTS.md §4.6) — so the only
        thing here is the floating find panel's stylesheet, which does come from
        the registry. A repaint is requested anyway: a switch changes the widget
        chrome around the canvas (the page's status line, the tabs), and a stale
        frame would show it. Never raises.

        v1.5rc4 (ROADMAP task 5): the VISIBLE-FOCUS ring repaints here too — its
        colour is read live from the ACTIVE theme (`theme.ACCENT_STRONG`), so a
        switch has to redraw it.
        """
        if self._focus_ring is not None:
            self._focus_ring.refresh_theme()
        bar = self._find_bar
        if bar is not None:
            hook = getattr(bar, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    self._find_bar = None   # the C++ object is gone — stop touching it
        self.update()

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


# The LIVE-NAMESPACE SEAMS, declared once (`AGENTS.md` §4.1, §4.3): every name a `terminal_widget_*.py`
# mixin resolves on THIS module at call time (`host_attr`). The declaration IS the seam — it keeps the
# name importable and it is the substitution point a suite patches (`TW.QFileDialog = <fake>`), so a
# name read only by a mixin is not a dead import. The PURE helpers the mixins need are the module's own
# functions (`selection_cells`, `word_units`, `build_macro_payload`, `strip_paste_markers`, …).
MODULE_FACADE_SEAMS = (
    QFileDialog, QMenu,
    _get_multi_hub, _get_app_log, get_translator,
    selection_cells, word_units, build_macro_payload, strip_paste_markers,
)


