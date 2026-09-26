"""v0.8: TerminalScreen — an ANSI terminal emulator on pyte.

A full replacement for the "dumb" QPlainTextEdit output: pyte parses all
escape sequences (CSI/OSC/cursor modes, colors) and keeps a 120x32 grid —
the same geometry that SSHTerminalThread requests via invoke_shell(term='xterm',
width=120, height=32). The alternative screen (mode 1049) is NOT in pyte 0.8.2
(checked against the installed version — TERMINAL.md fact #6): after vim/htop
the previous screen is not restored, a known limitation (ROADMAP v1.0).
→ CLOSED in v1.2.12 by the SshmapHistoryScreen subclass (modes 47/1047/1048/1049 —
see the v1.2.12 section below and PYTE82_AUDIT.md batch B).

v1.0RC1: added a color engine for the per-cell canvas (PALETTES +
resolve_color, TERMINAL.md §5.1) and snapshot() — a grid snapshot for
TerminalWidget (modules/terminal_widget.py). The old HTML renderer render()
was marked deprecated in v1.0RC1 and removed in v1.2.9 (ROADMAP "Terminal hygiene").

v1.0RC3: pyte.Screen → pyte.HistoryScreen (TERMINAL.md §5.4) — a ready-made
scrollback (deque history + prev_page()/next_page()) with a built-in auto-return
to the live line on new output (before_event, verified as fact #7). scroll_up()/
scroll_down()/at_bottom() — under the same lock as feed(). The rest of the API
(feed/resize/snapshot/render) unchanged — duck typing.

v1.1.2RC3 (AUDIT U3): application_cursor_keys() — the DECCKM state (private
mode 1) under the same lock as feed(): TerminalWidget picks the arrow-key
sequences from it (SS3 \x1bOA… under mc/vim/htop, CSI \x1b[A… in normal
mode). Verified pyte 0.8.2 fact: private modes are stored in screen.mode
shifted left by 5 bits (set_mode(private=True): mode << 5) — DECCKM is 32,
NOT 1 (verified by a run on the installed version).

v1.2.11 (PYTE82_AUDIT.md batch A): SshmapHistoryScreen — a pyte.HistoryScreen
subclass with two compatibility overrides for the INSTALLED pyte 0.8.2.
Mechanism: Stream binds the screen methods via getattr(listener, attr) at
attach (streams.py, create_dispatcher) → the subclass overrides are picked up
by the parser automatically; the public TerminalScreen API is unchanged
(duck typing). Verified fact #12 (a run on the installed pyte 0.8.2): Vim 9+
sends \x1b[?4m (private SGR, upstream issue #202); in 0.8.2 that is a TypeError
from feed() — Screen.select_graphic_rendition does not accept private, and the
tail of the chunk after the sequence is lost (the parser resets; the
except Exception: return in _on_output swallows the exception). The subclass
ignores private SGR; in master the fix is already merged (PR #203, 2025-09-02) —
the override with the same semantics stays until the pin is raised to pyte 0.8.3
(compatible and documented; at 0.8.3 the 'bfightmagenta' item in resolve_color()
is marked legacy — in master the BG_AIXTERM[105] typo is already fixed).
LNM (mode 20) is ON by default: bare LF = CR+LF (xterm behavior; Screen.reset()
drops mode to _DEFAULT_MODE without LNM → an explicit restore after
super().__init__ and in reset(); explicit \x1b[20h/\x1b[20l (SM/RM 20) from a
remote program still work).

v1.2.12 (PYTE82_AUDIT.md batch B): the alternative screen in SshmapHistoryScreen —
private modes 47/1047/1048/1049, which in 0.8.2 were inert bits of screen.mode
with the <<5 shift (no handlers). Semantics — per upstream PR #212 (closed
without a merge, author dwgx; the pyte code is LGPL-3.0 — attribution to the PR
author in a code comment is mandatory), differentially checked against tmux 3.6b
and GNU screen: a SINGLE in_alt flag (ESC[?47l leaves the screen entered via
1049h); enter — save the main buffer → the working one = a fresh empty one
(the cursor is NOT homed — the TUI sends CUP itself; re-entering is
idempotent); leave — restore the saved buffer clipped to the current width,
drop the alt buffer (the content does not survive the round-trip — the behavior
of both reference emulators takes priority over the xterm wording "without
clearing"); the cursor is saved/restored only for 1048/1049 (xterm: 1049 =
1047+1048) in a separate _alt_cursor field, NOT a savepoint stack (the TUI
inside the session runs ESC 7/ESC 8 itself). Lines that scroll out of the alt
buffer (index/reverse_index while in_alt) do not enter the scrollback — like
less in a real terminal; RIS (ESC c — NOT ESC [ c, that is CSI DA) inside alt →
full reset + leave.
Access: screen.in_alt + TerminalScreen.in_alt_screen() under the same lock as
feed(); while in_alt — the mouse wheel and Ctrl+Shift+PgUp/PgDn do not scroll
history (the gate in TerminalWidget; full wheel routing in the TUI — v1.2.13).

v1.2.14 (PYTE82_AUDIT.md batch D2): batching of the auto-return to the live line —
a before_event override in SshmapHistoryScreen. For every event except
prev_page/next_page pyte spun next_page() in a loop: with a deep history up to
~250 iterations, each O(lines) (measurement D1 v1.2.12: 68–73 ms/chunk against
~42 on the live line; feed comes through a queued signal — blocking the GUI
thread). Now a single bulk operation with the same arithmetic as next_page
(screens.py): mid = min(len(history.bottom), size − position);
top.extend(buffer[0:mid]); the buffer shifts up; buffer[-mid:] — from
bottom.popleft(); position += mid; dirty = all lines — O(lines) once. Verified
fact (a run): the invariant len(history.bottom) == size − position → mid can
exceed lines (deep history); the surplus of mid over lines returns from the
HEAD of bottom back to top (the same lines the loop would have moved in the
intermediate iterations) — the result is identical to the next_page() loop:
position == size, bottom empty, top fully restored, buffer = the live screen.
The wrapper calls self.before_event(event) by name → the override is picked up
(before_event is not in _wrapped); prev_page/next_page — no-ops, as in pyte.

v1.3rc1 (PYTE82_AUDIT.md "managed fork"): pyte → a managed fork. The import seam —
one line `from third_party import pyte`: the vendored pyte 0.8.2 (the PyPI sdist
with provenance, sha256) + the explicit patches 0001–0009 in third_party/pyte/;
the single source of truth — third_party/pyte-patches/MANIFEST.md. The batch A
overrides (private SGR → patch 0001, LNM → patch 0002) and batch B (the
alternative screen → patch 0003) were removed from the subclass — now they are
patches of the fork; SshmapHistoryScreen keeps only the before_event batching
(D2). The behavior is unchanged: the existing terminal tests are green
unchanged (except the one-line import seam, v1.3rc1). Reverting to stock pyte
= one line back (import pyte) — see MANIFEST.md.

Headless-friendly: the Screen class itself requires no Qt — tested without a GUI.
Thread safety: feed() from the SSH thread, snapshot()/application_cursor_keys
from the GUI thread (v1.1.2 final N13: the dead cursor property was removed —
the declaration matches the code; the cursor comes from snapshot()).
"""

import math
import threading

# v1.3rc1 (PYTE82_AUDIT.md "managed fork"): the import seam — the only place in
# the code that knows about the fork: the vendored pyte 0.8.2 + the explicit
# patches 0001–0004 in third_party/pyte/ (provenance, sha256 tables, policy —
# third_party/pyte-patches/MANIFEST.md). Reverting to stock pyte = one line back (import pyte).
from third_party import pyte

# ── v1.0RC1: the per-cell color engine (TERMINAL.md §5.1) ────────────────────
# Verified pyte 0.8.2 facts (a run on the installed version):
#   * SGR 33 → fg='brown', SGR 93 → fg='brightbrown' — yellow is called brown;
#   * the 256-colors AND truecolor are stored as hex strings WITHOUT '#' ('ff0000',
#     '0a141e') — the isdigit() branch never fires, a hex passthrough is needed;
#   * a typo in pyte itself: BG_AIXTERM[105] = 'bfightmagenta' (SGR 4;105 → bg='bfightmagenta').
# The engine is headless (no Qt) — tested without a GUI (tests/test_terminal_colors.py).

DEFAULT_FG_HEX = "#e2e8f0"   # the default text on the dark terminal window background
DEFAULT_BG_HEX = "#0f172a"   # the terminal window background (the QPlainTextEdit v0.8 style)

# ── v1.0RC3: HistoryScreen scrollback parameters (TERMINAL.md §5.4) ──────────
# history — the depth of the deque history (lines); ratio — the "page" size for
# prev_page()/next_page() = ceil(lines * ratio): ratio=0.1 at 32 lines gives
# ~4 lines per wheel tick / Ctrl+Shift+PgUp/PgDn press. The config key
# terminal_history_lines was wired up in the v1.0 final (ROADMAP task 9,
# load_terminal_settings() in modules/ssh_terminal.py) — the default = the
# behavior AFTER RC3 (scrollback ON); an explicit 0 — the user disabling it.
DEFAULT_HISTORY_LINES = 1000
SCROLL_RATIO = 0.1

# ── v1.3.3.4 (ROADMAP task 1): the safety bound of the find bar's navigation ──
# scroll_to_line()/scroll_to_position() move the viewport with pyte's own pages
# (~10% of the grid each, SCROLL_RATIO). A page that does not move the border is
# the edge of the history and ends the loop; this constant is the second belt —
# a guard against a hypothetical pyte page that reports no progress. The real
# budget per call is derived from the CURRENT history depth (_scroll_step_budget:
# enough pages to cross the whole deque + a small margin), so a deep scrollback
# (terminal_history_lines up to 1_000_000) stays fully searchable while the loop
# remains finite; MAX_SCROLL_STEPS is the hard ceiling of that budget.
MAX_SCROLL_STEPS = 200_000

# Palettes: the REQUIRED keys black…white + br_* (8+8) — otherwise the SGR 33/93
# and the bright colors fall to default (critical error #2 from TERMINAL.md §3).
# 'default' — the current xterm-like palette: the defaults = the current look.
# default_fg/default_bg — the text color and the screen background (reverse folds to them).
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
    """pyte color → hex '#rrggbb' (TERMINAL.md §5.1).

    value: None/'default' | a name ('brown', 'brightred', …) | a 6-hex without '#'
    (in pyte 0.8.2 both the 256-colors and truecolor are stored exactly like that —
    passthrough). Special cases: 'brown'/'brightbrown' — yellow (SGR 33/93);
    'bfightmagenta' — a typo in pyte itself for bright magenta (BG_AIXTERM[105],
    SGR 4;105). An unknown name → default_hex.
    """
    pal = PALETTES["default"] if palette is None else palette
    if value in (None, "default"):
        return default_hex
    v = str(value)
    # 256-color / truecolor: hex without '#' — passthrough
    if len(v) == 6:
        try:
            int(v, 16)
            return "#" + v
        except ValueError:
            pass
    name = v.lower()
    if name == "bfightmagenta":      # a pyte typo (SGR 4;105) → bright magenta
        return pal.get("br_magenta", default_hex)
    if name.startswith("bright"):
        base = name[len("bright"):]
        if base == "brown":          # SGR 93 — bright yellow
            base = "yellow"
        return pal.get("br_" + base, pal.get(base, default_hex))
    if name == "brown":              # SGR 33 — in pyte yellow is called brown
        return pal.get("yellow", default_hex)
    return pal.get(name, default_hex)


# ── v1.3rc1: managed fork — only the D2 auto-return batching in the subclass ───────────
class SshmapHistoryScreen(pyte.HistoryScreen):
    """pyte.HistoryScreen + the auto-return to the live line batching (batch D2, v1.2.14).

    v1.3rc1: the batch A overrides (private SGR — fork patch 0001; LNM on by
    default — patch 0002) and batch B (the alternative screen 47/1047/1048/1049 —
    patch 0003, the upstream PR #212 semantics, author dwgx) moved into the managed
    fork third_party/pyte/ (provenance/sha256/policy — third_party/pyte-patches/
    MANIFEST.md). Only before_event is left in the subclass: that is our
    optimization (not a break of the xterm semantics), so it lives in our code.

    The pickup mechanism: HistoryScreen.__getattribute__ calls
    self.before_event(event) by name → the subclass override is picked up
    (before_event is not in _wrapped — no conflicts). prev_page/next_page —
    no-ops, as in pyte."""

    # ── v1.2.14 (PYTE82_AUDIT.md batch D2): live-line auto-return batching ───────
    def before_event(self, event):
        """The auto-return to the live line batching (measurement D1, v1.2.12: 68–73 ms/chunk).

        pyte.HistoryScreen.before_event for every event except prev_page/next_page
        spins next_page() in a loop: with a deep history up to ~250 iterations,
        each O(lines) (measurement D1 v1.2.12: 68–73 ms/chunk against ~42 on the
        live line — feed comes through a queued signal in the GUI thread). Here —
        one bulk operation with the same arithmetic as HistoryScreen.next_page
        (screens.py):
        mid = min(len(history.bottom), size − position); top.extend(buffer[0:mid]);
        the buffer shifts up; buffer[-mid:] — from bottom.popleft();
        position += mid; dirty = all lines. O(lines) once instead of
        O(position/ratio × lines).

        Verified fact (a run on the installed pyte 0.8.2): the invariant
        len(history.bottom) == size − position (each prev_page/next_page moves the
        same number of lines between buffer and bottom) → mid can exceed lines
        (a deep history: 968 lines on a 32-line screen). In this case the naive
        next_page() loop breaks (range(lines − mid) is empty — no shift happens,
        and negative indices would create garbage in buffer): the surplus of mid
        over lines returns from the HEAD of bottom back to top (the same lines
        the loop would have moved in the intermediate iterations), and the screen
        gets the last lines of the sequence (buffer[take:] + the rest of bottom).
        The result is identical to the next_page() loop: position == size, bottom
        empty, top fully restored, buffer = the live screen; at mid ≤ lines the
        code matches next_page() word for word.

        The pickup mechanism: the HistoryScreen.__getattribute__ wrapper calls
        self.before_event(event) by name → the subclass override is picked up
        (before_event is not in _wrapped — no conflicts). prev_page/next_page —
        no-ops, as in pyte: a manual wheel/PgUp-PgDn scroll does NOT touch the
        auto-return.
        """
        if event in ("prev_page", "next_page"):
            return
        h = self.history
        if h.position < h.size and h.bottom:
            mid = min(len(h.bottom), h.size - h.position)
            take = min(mid, self.lines)      # the buffer lines that go back to top
            h.top.extend(self.buffer[y] for y in range(take))
            if mid > take:                   # a deep history: the surplus — from the head of bottom to top
                h.top.extend(h.bottom.popleft() for _ in range(mid - take))
            for y in range(self.lines - take):        # the buffer shifts up (as in next_page)
                self.buffer[y] = self.buffer[y + take]
            for y in range(self.lines - take, self.lines):
                self.buffer[y] = h.bottom.popleft()   # the bottom lines — from bottom
            self.history = h._replace(position=h.position + mid)
            self.dirty = set(range(self.lines))

    # v1.3rc1: the batch A/B overrides REMOVED — they became the fork patches
    # 0001/0002/0003 (third_party/pyte-patches/MANIFEST.md); the behavior is the same, the provenance is explicit.


class TerminalScreen:
    """A columns x lines grid on pyte + thread-safe input.

    v1.0RC3: screen — pyte.HistoryScreen (scrollback, TERMINAL.md §5.4).
    v1.2.11: screen — SshmapHistoryScreen (a subclass, compatibility with pyte 0.8.2).
    v1.2.12: + in_alt_screen() — the alternative screen state under the lock.
    v1.3rc1: pyte — the managed fork third_party/pyte (the import seam, MANIFEST.md);
             only the before_event batching is left in the subclass (D2)."""

    def __init__(self, columns=120, lines=32, history_lines=DEFAULT_HISTORY_LINES):
        self.columns = columns
        self.lines = lines
        # v1.0RC3: HistoryScreen instead of Screen — a ready-made scrollback (deque history)
        # + the auto-return to the live line on new output (before_event).
        # v1.2.11: the SshmapHistoryScreen subclass (private SGR + LNM, batch A).
        # v1.3rc1: pyte — the fork third_party/pyte; only the D2 batching is left in the subclass.
        self.screen = SshmapHistoryScreen(columns, lines,
                                          history=int(history_lines), ratio=SCROLL_RATIO)
        self.stream = pyte.ByteStream(self.screen)   # accepts bytes, utf-8 inside
        self._lock = threading.Lock()

    # ── input from the SSH thread ──────────────────────
    def feed(self, data: bytes):
        with self._lock:
            self.stream.feed(data)

    def resize(self, columns, lines):
        with self._lock:
            self.columns, self.lines = columns, lines
            self.screen.resize(lines, columns)

    # ── v1.0RC3: the scrollback (HistoryScreen, TERMINAL.md §5.4) ──────────
    def scroll_up(self):
        """A history page up (prev_page). True — the position changed.

        At the top edge (position <= lines or the history is empty) pyte does a
        no-op → False. Called from the GUI thread (the wheel / Ctrl+Shift+PgUp);
        under the same lock as feed() — the SSH thread cannot change the buffer
        in the middle of a page."""
        with self._lock:
            scr = self.screen
            before = scr.history.position
            scr.prev_page()
            return scr.history.position != before

    def scroll_down(self):
        """A page down, toward the live line (next_page). True — the position changed."""
        with self._lock:
            scr = self.screen
            before = scr.history.position
            scr.next_page()
            return scr.history.position != before

    def at_bottom(self):
        """Are we on the live line? (history.position == history.size — the cursor
        is visible, the scroll down is forbidden; TERMINAL.md §5.4)."""
        with self._lock:
            return self.screen.history.position == self.screen.history.size

    def scroll_info(self):
        """(position, size) for tests/debugging."""
        with self._lock:
            h = self.screen.history
            return h.position, h.size

    # ── v1.3.3.4 (ROADMAP task 1): the scrollback DOCUMENT of the find bar ────
    # pyte.HistoryScreen keeps three queues (the class docstring of the fork):
    # history.top — the lines ABOVE the screen (oldest first), buffer — the visible
    # grid, history.bottom — the lines BELOW it (non-empty only while the user has
    # scrolled back). The document below is the three of them in that order, so it
    # is the SAME line sequence at any scroll position — that is what makes a match
    # index stable while Enter/Shift+Enter move the viewport through it.

    def _row_text(self, row) -> str:
        """One pyte grid row → str (the cells are a SPARSE dict: the width comes from columns).

        Not `"".join(ch.data for ch in row)` — iterating a StaticDefaultDict yields
        the KEYS (x indices), not the Chars (the v1.3.3.4 probe); the snapshot() of
        the canvas indexes it the same way.
        """
        return "".join(row[x].data for x in range(self.columns))

    def text_lines(self) -> list:
        """The whole scrollback document: the history lines (oldest first) + the live grid.

        Read under the same lock as feed(): a search over a half-fed chunk would
        report a match in a line the canvas is about to repaint.
        """
        with self._lock:
            scr = self.screen
            lines = [self._row_text(row) for row in scr.history.top]
            lines.extend(self._row_text(scr.buffer[y]) for y in range(scr.lines))
            lines.extend(self._row_text(row) for row in scr.history.bottom)
            return lines

    def history_top_len(self) -> int:
        """How many lines of the document sit ABOVE the visible grid (the mapping origin).

        Document index → grid row: `row = doc_index - history_top_len()`. Read on
        every paint of the canvas (the value changes with every scroll page).
        """
        with self._lock:
            return len(self.screen.history.top)

    def _scroll_step_budget(self) -> int:
        """How many pyte pages may be moved in ONE navigation call (a locked screen).

        pyte's page is `ceil(lines * SCROLL_RATIO)` lines (4 on the default 32-row
        grid), so crossing a `history`-deep scrollback costs `history / page` pages.
        The budget is derived from the CURRENT depth with a small margin — enough for
        the whole deque whatever `terminal_history_lines` says — and capped by
        MAX_SCROLL_STEPS so a pathological value cannot spin forever.
        """
        h = self.screen.history
        page = max(1, int(math.ceil(self.screen.lines * SCROLL_RATIO)))
        return max(64, min(MAX_SCROLL_STEPS, h.size // page + 8))

    def scroll_to_line(self, index) -> bool:
        """Scroll the viewport until the document line `index` is visible. True — moved.

        The visible window is `buffer`, i.e. the document indices
        [len(top), len(top) + lines). The viewport is moved with pyte's own pages
        (prev_page/next_page — the same ~10% step as the wheel and Ctrl+Shift+PgUp/
        PgDn), so the scrollback arithmetic stays pyte's. A page that does not move
        the border means the edge of the history: the loop ends and the answer is
        False (a match cannot be revealed by scrolling even further), not a hang.
        """
        with self._lock:
            scr = self.screen
            target = max(0, int(index))
            moved = False
            for _ in range(self._scroll_step_budget()):
                top_len = len(scr.history.top)
                if target < top_len:
                    if not self._page_locked(scr, up=True):
                        break
                elif target >= top_len + scr.lines:
                    if not self._page_locked(scr, up=False):
                        break
                else:
                    break                 # already visible
                moved = True
            if moved:
                scr.dirty = set(range(scr.lines))
            return moved

    @staticmethod
    def _page_locked(scr, up: bool) -> bool:
        """One prev_page()/next_page() of an ALREADY LOCKED screen. False — the page was a no-op."""
        before = len(scr.history.top)
        if up:
            scr.prev_page()
        else:
            scr.next_page()
        return len(scr.history.top) != before

    def scroll_to_position(self, position) -> int:
        """Restore a history position captured earlier (the find bar's Esc). Returns the new one.

        `position` comes from scroll_info()[0]; the value is clamped to the valid
        range and the very same page loop as scroll_to_line() is used, so the
        restore always lands on a position pyte itself can reach (the pages are not
        fine-grained — the result may be a few lines off, which is exactly what
        "the state before the search" means for a paging scrollback).
        """
        with self._lock:
            scr = self.screen
            size = scr.history.size
            target = max(0, min(int(position), size))
            for _ in range(self._scroll_step_budget()):
                current = scr.history.position
                if current == target:
                    break
                if not self._page_locked(scr, up=current > target):
                    break                 # the edge of the history — as close as pyte gets
            scr.dirty = set(range(scr.lines))
            return scr.history.position

    # ── v1.3.3.4 (ROADMAP task 2): two LOCAL actions, no bytes to the PTY ────

    def clear_history(self) -> bool:
        """Drop the scrollback: the live grid is KEPT, the history (top+bottom) is emptied.

        The exact semantics of `terminal_history_lines = 0` for the content that is
        already there (new output accumulates again — the depth itself is not
        changed). The user is first snapped back to the live line (before_event —
        the bulk auto-return of the fork): otherwise the grid would keep showing
        historical rows whose history entry is gone. Local only: pyte's history
        queues are emptied, not one byte goes to the channel.
        """
        with self._lock:
            scr = self.screen
            h = scr.history
            if h.position < h.size:
                scr.before_event("clear_history")   # snap back to the live line (bulk restore)
            h = scr.history
            h.top.clear()
            h.bottom.clear()
            scr.history = h._replace(position=h.size)
            scr.dirty = set(range(scr.lines))
            return True

    def reset_local(self) -> bool:
        """A full LOCAL re-init of the grid (the "the screen is a mess" case).

        pyte's own reset: the grid is cleared, the cursor is homed with the default
        attributes, the margins/tabstops/charset and every private mode go back to
        their initial state (DECTCEM and LNM come from _DEFAULT_MODE — fork patch
        0002), the history is dropped. Nothing is sent to the channel and the
        remote program is not told: it will keep writing into the (now empty) grid
        and repaint it on its next output — the action is for a local screen that
        a partial redraw left unreadable.
        """
        with self._lock:
            self.screen.reset()
            self.screen.dirty = set(range(self.screen.lines))
            return True

    # ── v1.1.2RC3 (AUDIT U3): the DECCKM state for input ────────────────────
    def application_cursor_keys(self):
        """Is DECCKM (Application Cursor Keys Mode, private mode 1) ON?

        Full-screen TUIs (mc/vim/htop) send smkx \\x1b[?1h at startup and then
        EXPECT the arrows in the SS3 form (\\x1bOA…\\x1bOD), not CSI (\\x1b[A…).
        TerminalWidget picks the sequences for the arrows and Home/End from this
        flag (AUDIT U3: "the arrows do not work in mc").

        IMPORTANT (verified by a run on the installed pyte 0.8.2): private modes
        are stored in screen.mode shifted left by 5 bits — set_mode(private=True)
        does mode << 5. DECCKM is **32**, not 1: the canonical check from the
        internet, "1 in screen.mode", never fires (after \\x1b[?1h the mode gains
        32; ON by default are DECAWM=7<<5=224, DECTCEM=25<<5=800 and — since
        v1.2.11 — LNM=20: {224, 800, 20}). The pyte.modes DECCKM constant does not
        exist in 0.8.2.

        Read under the same lock as feed(): the SSH thread can change the modes in
        parallel with the GUI thread (smkx/rmkx come in the application output).
        """
        with self._lock:
            return (1 << 5) in self.screen.mode

    # ── v1.2.12 (PYTE82_AUDIT.md batch B): the alternative screen state ──────
    def in_alt_screen(self):
        """Is the alternative screen ON (private modes 47/1047/1048/1049)?

        Read under the same lock as feed(): the SSH thread can change the modes in
        parallel with the GUI thread (htop/vim send \\x1b[?1049h at startup and
        \\x1b[?1049l on exit). While in_alt — TerminalWidget does NOT scroll the
        history with the mouse wheel and Ctrl+Shift+PgUp/PgDn (the gate); the wheel
        in the TUI goes to the PTY only with mouse tracking ON (v1.2.13, mouse_tracking())."""
        with self._lock:
            return self.screen.in_alt

    # ── v1.2.13 (PYTE82_AUDIT.md batch C): the mouse tracking state ──────────
    def mouse_tracking(self):
        """(enabled, sgr) — is the xterm mouse tracking ON and the SGR format used.

        enabled — any of DECSET 1000/1002/1003 is ON (button / button-motion /
        all-motion tracking); sgr — DECSET 1006 is ON (SGR extended encoding).

        IMPORTANT (verified by a run on the installed pyte 0.8.2): private modes
        are stored in screen.mode shifted left by 5 bits — set_mode(private=True)
        does mode << 5: after \\x1b[?1000h\\x1b[?1006h the mode has 32000 and 32192.
        DECSET 1006 ALONE does not enable tracking — it only changes the report
        encoding (a real xterm without 1000/1002/1003 does not generate mouse-events) →
        feed(b'\\x1b[?1006h') gives (False, True), NOT (True, True).

        Read under the same lock as feed(), on EVERY wheel event: the TUI changes
        the modes during the session (htop enables 1003+1006 at startup and
        disables them on exit) — it cannot be cached. RIS (\\x1bc) resets all the
        private modes → after a full reset it is (False, False) again (verified).
        """
        with self._lock:
            mode = self.screen.mode
            enabled = any((n << 5) in mode for n in (1000, 1002, 1003))
            return enabled, (1006 << 5) in mode

    # ── v1.6.3 (ROADMAP task 2): WHICH tracking mode is on ───────────────────
    def mouse_tracking_mode(self):
        """(mode, sgr) — the HIGHEST mouse tracking mode the application asked for.

        mode — 0 (no tracking) | 1000 (a press and a release) | 1002 (motion while a
        button is held) | 1003 (any motion); sgr — DECSET 1006 is ON (the SGR extended
        encoding). 1003 wins over 1002 wins over 1000 when a program enabled several
        (xterm answers the most permissive one), which is what the canvas needs to decide
        whether a MOTION is reportable. Read under the same lock as feed() and on EVERY
        mouse event, like `mouse_tracking()` — a TUI toggles these during a session.
        """
        with self._lock:
            mode = self.screen.mode
            for n in (1003, 1002, 1000):
                if (n << 5) in mode:
                    return n, (1006 << 5) in mode
            return 0, (1006 << 5) in mode

    # ── rendering for the GUI thread ───────────────────
    def snapshot(self):
        """v1.0RC1: a screen snapshot for the per-cell canvas (TerminalWidget, the GUI thread).

        Returns (rows, cursor_x, cursor_y, cursor_hidden): rows — a list of lines
        lists of Char of width columns (the empty cells — the default Char of pyte),
        the cursor is clamped to the grid bounds (cursor.x can be == columns after a
        wrap). Read under the same lock as feed(): the SSH thread cannot change the
        buffer in the middle of a paintEvent. Works with pyte.HistoryScreen (v1.0RC3)
        too — duck typing by buffer/cursor/lines/columns.
        """
        with self._lock:
            scr = self.screen
            rows = [[scr.buffer[y][x] for x in range(scr.columns)]
                    for y in range(scr.lines)]
            cx = min(scr.cursor.x, scr.columns - 1)
            cy = min(scr.cursor.y, scr.lines - 1)
            return rows, cx, cy, bool(scr.cursor.hidden)

    # v1.2.9 (ROADMAP "Terminal hygiene"): the deprecated HTML renderer render()
    # (v1.0RC1) REMOVED together with the _color()/_esc_html() helpers — dead code
    # since v1.0RC1, never created by the window; the render — TerminalWidget.snapshot().

    # v1.1.2 final (N13): the dead cursor() property REMOVED — there were no callers
    # in the code (AUDIT: only the internal screen.cursor.* reads under the lock).
    # The cursor for the render comes from snapshot() — under the same lock as feed().
