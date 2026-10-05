"""The LOCAL SELECTION of the terminal canvas (`TerminalWidget` wave).

`TerminalSelectionMixin` owns the cell range the user marked with the mouse: the anchor/active pair with
its second storage discipline (the anchor is a CELL, never a character index), the pure `selection_cells()`
range, the copied text (one line per row, the trailing blanks trimmed) and the word / line / all
selectors behind the double, triple and menu gestures.

Contract — `AGENTS.md` §4.3; mechanism — `DOCUMENTATION.md` §14a, §64.
"""

from PySide6.QtWidgets import QApplication

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr


class TerminalSelectionMixin:
    """The local cell selection and the copy (mixed into `TerminalWidget`)."""
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
        return host_attr(self, "selection_cells")(self._sel_anchor, self._sel_active, cols)

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
        for start, end in host_attr(self, "word_units")(rows[row]):
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
