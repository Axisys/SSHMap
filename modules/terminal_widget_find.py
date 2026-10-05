"""The FIND BAR of the terminal canvas (`TerminalWidget` wave).

`TerminalFindMixin` owns the search over the WHOLE document (the visible grid plus the scrollback): the
floating panel's lifecycle (`open_find` / `close_find` / `find_active`), the match list of the current
query (`_refresh_find_matches`), the counter, the wraparound step and the visible-cell spans the painter
highlights. The panel is only the input surface; the state is the canvas's, in ONE place.

Contract — `AGENTS.md` §4.3; mechanism — `DOCUMENTATION.md` §14a, §64.
"""

import re

try:  # the floating panel of the search (a child of the canvas, no cycle)
    from .terminal_find_bar import TerminalFindBar
except ImportError:
    from modules.terminal_find_bar import TerminalFindBar

try:  # the pinned-scrollback modes the close path restores by CONTENT
    from .terminal_screen import (SCROLL_MODE_DEFAULT as _SCROLL_MODE_DEFAULT,
                                  SCROLL_MODE_PIN as _SCROLL_MODE_PIN)
except ImportError:
    from modules.terminal_screen import (SCROLL_MODE_DEFAULT as _SCROLL_MODE_DEFAULT,
                                         SCROLL_MODE_PIN as _SCROLL_MODE_PIN)


class TerminalFindMixin:
    """The find panel, its matches and its own scrollback bookkeeping (mixed into `TerminalWidget`)."""
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

        v1.6.4 (ROADMAP task 5): the origin is captured TWICE — as pyte's position and as the
        CONTENT offset of the top visible line. Under `terminal_scroll = "pin"` the position
        drifts while output arrives (the pin holds the lines, the distance to the live end
        grows), so the offset is what Esc restores with; in the "live" mode the position is.
        """
        bar = self._ensure_find_bar()
        if self._find_saved_position is None:
            try:
                self._find_saved_position = self.tscreen.scroll_info()[0]
                self._find_saved_top = self.tscreen.history_top_len()
            except Exception:  # noqa: BLE001 — a screen under teardown: the restore is skipped
                self._find_saved_position = None
                self._find_saved_top = None
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

        v1.6.4 (ROADMAP task 5): under the pin the captured CONTENT offset is restored instead
        (`scroll_to_offset()`), so Esc lands on the same LINES it captured — the position
        arithmetic would land somewhere else after the output the pin let through.
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
                if getattr(self.tscreen, "scroll_mode", _SCROLL_MODE_DEFAULT) == _SCROLL_MODE_PIN \
                        and self._find_saved_top is not None:
                    self.tscreen.scroll_to_offset(self._find_saved_top)
                else:
                    self.tscreen.scroll_to_position(self._find_saved_position)
            except Exception:  # noqa: BLE001 — teardown race: the viewport restore is cosmetic
                pass
        self._find_saved_position = None
        self._find_saved_top = None
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
