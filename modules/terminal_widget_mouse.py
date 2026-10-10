"""The MOUSE family of the terminal canvas (`TerminalWidget` wave).

`TerminalMouseMixin` owns every mouse surface of the canvas: the ONE xterm encoder (`_send_mouse`) behind
the ONE predicate (`_mouse_reports_to_pty`) with `Shift` as the local override, the wheel (the `Ctrl`
font zoom first, then the mouse report, then the scrollback), the local press/drag/release gestures, the
right-click context menu and the `OSC 8` link (the hover, the hit test and the ONE opener door —
`Ctrl`+click while the application tracks the mouse, a plain click while it does not). Every report goes
to the session's channel DIRECTLY — never through `_send()`: the coordinates are session-local.

Contract — `AGENTS.md` §4.3; mechanism — `DOCUMENTATION.md` §14a, §64.
"""

import time

from PySide6.QtCore import Qt

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr


class TerminalMouseMixin:
    """The mouse protocol, the local gestures and the context menu (mixed into `TerminalWidget`)."""
    def wheelEvent(self, event):
        """The mouse wheel: v1.2.13 — the TUI mouse tracking first, then the scrollback.

        The v1.6.4 routing (ROADMAP tasks 3 and 5) — read top to bottom, the FIRST match wins:
        0. `Ctrl` + the wheel (without `Alt` — the AltGr guard of the keyboard path) is the
           FONT ZOOM (task 3): ±1 pt through `zoom_font()`, clamped to the range the
           `terminal_font_size` key validates. The branch sits BEFORE every routing decision
           below on purpose: the gesture is free (nothing in the canvas ever read a modifier),
           and it must work in a tracking TUI and with `terminal_wheel = "off"` as well.
        1. `Shift` held — the LOCAL override: the application's tracking is BYPASSED and
           the event takes the local path below, so a TUI that left DECSET 1000/1002/1003
           and 1006 behind (a crash, a kill — nothing clears them) cannot hijack the wheel:
           `Shift` + the wheel is the local scrollback and nothing else.
        2. `tscreen.mouse_tracking_mode()` — the application waits for mouse reports → the
           wheel goes to the PTY through `_send_mouse()`: SGR (\\x1b[<64;{col};{row}M with
           1006, up=64/down=65) or X10 (\\x1b[M + [96|97, 32+col, 32+row]). The coordinates
           are the 1-based cell, clamped to the grid and (X10) to the protocol limit of 223.
           The passthrough takes precedence over wheel_mode="off".
        3. in_alt_screen() WITHOUT tracking → a no-op (v1.2.12: a TUI owns the grid,
           the history does not scroll; the event is not consumed — the ancestor
           QScrollAreas are not in the containers, the propagation is harmless).
        4. Otherwise — the current v1.0RC3 behavior: the history scrollback (up → prev_page,
           down → next_page; at the edges pyte is a no-op), wheel_mode="off" →
           event.ignore(). The scrollback under "off" stays on Ctrl+Shift+PageUp/PageDown.
           Under `terminal_scroll = "pin"` this is also the way BACK to the live line: the
           wheel down reaches the bottom and the pin has nothing left to hold (task 5).

        The modes are read on EVERY event (a TUI toggles them during a session —
        htop enables 1003+1006 at start, disables them on exit; caching is not allowed).
        The auto-return to the live line on new output is built into pyte (before_event) — in
        the "pin" mode it is the session's own bulk return-and-restore instead; the window's
        `_on_output` calls widget.update(), so the snapshot is visible immediately.
        """
        mods = event.modifiers()
        if (mods & Qt.KeyboardModifier.ControlModifier) \
                and not (mods & Qt.KeyboardModifier.AltModifier):
            self.zoom_font(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        mode, sgr = self.tscreen.mouse_tracking_mode()   # v1.6.3: read on every event
        local = self._mouse_local_override(event)
        if mode and not local:
            self._send_wheel_to_pty(event, sgr)
            event.accept()
            return
        if not mode and self.tscreen.in_alt_screen():
            return  # the alt screen without tracking — a no-op (v1.2.12)
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

        v1.6.3 (ROADMAP task 2): the encoder is the ONE `_send_mouse()` — this method is
        the wheel's door into it (the button is the wheel's own code, the flag is a press).
        The coordinates come from `_event_cell()` (the 1-based cell, clamped to the grid).
        The sending is DIRECTLY to `terminal_thread.send_data()`, NOT through `_send()`:
        the wheel is addressed to THIS session (its coordinates), the multi-input broadcast
        to all open sessions would have delivered someone else's TUI reports with foreign
        coordinates — a deliberate decision, pinned by a test.
        """
        col, row = self._event_cell(event)
        up = event.angleDelta().y() > 0
        self._send_mouse(self.MOUSE_WHEEL_UP if up else self.MOUSE_WHEEL_DOWN,
                         col, row, True)

    # ── the mouse family ─────────────────────────
    # The canvas tracked the xterm mouse modes already and answered only the WHEEL: a press, a drag
    # and a release were eaten by the local selection with nothing sent, so a TUI that asked for the
    # mouse received half of the protocol. The encoder is ONE method now (`_send_mouse`) and the
    # decision "report to the application or work locally" is ONE predicate (`_mouse_reports_to_pty`).

    MOUSE_BUTTON_LEFT = 0
    MOUSE_BUTTON_MIDDLE = 1
    MOUSE_BUTTON_RIGHT = 2
    MOUSE_BUTTON_NONE = 3        # "no button" — the 1003 motion report
    MOUSE_MOTION_FLAG = 32       # ctlseqs: a motion report is the button code + 32
    MOUSE_WHEEL_UP = 64
    MOUSE_WHEEL_DOWN = 65
    MOUSE_X10_LIMIT = 223        # 32 + 223 = 255 — the X10 byte ceiling

    def _event_cell(self, event):
        """The 1-based (col, row) of a mouse event, clamped to the grid.

        The widget can be wider/taller than the pyte grid by the rounding remainder of the
        font metrics, so the answer is clamped to [1..columns]×[1..lines]. Shared by the
        wheel, the press/release and the motion reports (the v1.2.13 arithmetic, unchanged).
        """
        cols, lines = self.tscreen.columns, self.tscreen.lines
        pos = event.position()
        col = max(1, min(int(pos.x() // max(1, self._cell_w)) + 1, cols))
        row = max(1, min(int(pos.y() // max(1, self._cell_h)) + 1, lines))
        return col, row

    def _send_mouse(self, button, col, row, press: bool = True):
        """ONE xterm mouse report → the PTY (v1.6.3) — the whole press/release/motion family.

        `button` is the xterm button EVENT code with the motion flag already added by the
        caller (0/1/2 — left/middle/right, 3 — "no button", 64/65 — the wheel). `press`
        is True for a press AND for a motion ('M' in SGR) and False for a RELEASE (SGR:
        'm'; X10: the code + 3 — ctlseqs encodes a release as the button plus three).
        The coordinates are 1-based and clamped to the grid; X10 has no room beyond 223
        and is clamped to that ceiling (32 + 223 = 255), SGR has no limit. The bytes go
        DIRECTLY to `terminal_thread.send_data()` — never through `_send()`: the
        coordinates are session-local, so the multi-input hub must not broadcast them
        (the v1.2.13 rule). Never raises: a dead channel mid-teardown drops the report.
        """
        if self.terminal_thread is None:
            return
        # v1.9.6: a mouse report is not text this canvas typed — the forward-only line buffer of the
        # multi-input command guard can no longer be trusted (AGENTS.md §4.30).
        self._guard_line_invalidate()
        cols, lines = self.tscreen.columns, self.tscreen.lines
        col = max(1, min(int(col), cols))
        row = max(1, min(int(row), lines))
        button = max(0, min(int(button), 255 - 32))
        _mode, sgr = self.tscreen.mouse_tracking_mode()
        if sgr:
            data = (b"\x1b[<" + str(button).encode("ascii") + b";"
                    + str(col).encode("ascii") + b";" + str(row).encode("ascii")
                    + (b"M" if press else b"m"))
        else:
            code = button if press else button + 3
            code = min(code, 255 - 32)
            col = min(col, self.MOUSE_X10_LIMIT)
            row = min(row, self.MOUSE_X10_LIMIT)
            data = b"\x1b[M" + bytes([32 + code, 32 + col, 32 + row])
        try:
            self.terminal_thread.send_data(data)
        except Exception:
            pass  # a dead channel/thread mid-teardown — the report silently does not go out

    @staticmethod
    def _xterm_button(button):
        """A Qt mouse button → the xterm event code (None — a button we do not report)."""
        if button == Qt.MouseButton.LeftButton:
            return TerminalMouseMixin.MOUSE_BUTTON_LEFT
        if button == Qt.MouseButton.MiddleButton:
            return TerminalMouseMixin.MOUSE_BUTTON_MIDDLE
        if button == Qt.MouseButton.RightButton:
            return TerminalMouseMixin.MOUSE_BUTTON_RIGHT
        return None

    @staticmethod
    def _held_button(buttons):
        """The xterm code of the button held during a motion (3 — none, the 1003 case)."""
        if buttons & Qt.MouseButton.LeftButton:
            return TerminalMouseMixin.MOUSE_BUTTON_LEFT
        if buttons & Qt.MouseButton.MiddleButton:
            return TerminalMouseMixin.MOUSE_BUTTON_MIDDLE
        if buttons & Qt.MouseButton.RightButton:
            return TerminalMouseMixin.MOUSE_BUTTON_RIGHT
        return TerminalMouseMixin.MOUSE_BUTTON_NONE

    def _mouse_local_override(self, event) -> bool:
        """`Shift` held → the LOCAL path wins (v1.6.3, ROADMAP task 3).

        The ONE hatch out of a TUI that went away without its own disable: the tracked
        bits stay in `screen.mode` (xterm clears nothing either) and the LOCAL wheel must
        never depend on the remote's honesty, so `Shift` + the wheel scrolls the local
        scrollback and `Shift` + a drag makes the local selection. Never raises.
        """
        try:
            return bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        except Exception:  # noqa: BLE001 — a synthetic event without modifiers
            return False

    def _mouse_reports_to_pty(self, event, report_motion: bool = False) -> bool:
        """Should this mouse event go to the PTY instead of the local selection?

        True when the application asked for the mouse (DECSET 1000/1002/1003), `Shift` is
        NOT held and the mode covers the event: a press/release is reported under all three
        modes, a motion only under 1002 (while a button is held) or 1003 (any motion). The
        caller sends the bytes — this predicate only decides.
        """
        if self._mouse_local_override(event):
            return False
        mode, _sgr = self.tscreen.mouse_tracking_mode()
        if not mode:
            return False
        if not report_motion:
            return True
        if mode == 1003:
            return True
        return mode == 1002 and bool(event.buttons())

    # ── v1.9: the `OSC 8` link — the hit test, the hover and the ONE opener ────

    def link_uri_at(self, pos) -> str:
        """The `OSC 8` URI under a widget point; `""` for no link, no grid or a stale view.

        The cell comes from `_cell_at()` (the ONE cell mapping) and the URI from ONE row of the LIVE
        grid (`TerminalScreen.row_cells()`, the targeted read beside `snapshot()`) — a pointer
        crossing the canvas asks about a row, never about the whole screen. The PURE `link_span()` is
        the run rule the hover, the underline and the click share. Never raises: a half-torn-down
        screen answers "no link" instead of taking a paint down.
        """
        try:
            row, col = self._cell_at(pos)
            span = host_attr(self, "link_span")(self.tscreen.row_cells(row), col)
            return span[2] if span else ""
        except Exception:  # noqa: BLE001 — a dying screen is "no link", never a crash
            return ""

    def open_link(self, uri) -> bool:
        """Open an `OSC 8` target through the ONE allowlist; True when the OS was really asked.

        `models.server.is_launchable_url()` is the SHIPPED predicate (`http`/`https` — the quick-launch
        row and the bookmarks ask the same one, `AGENTS.md` §4.4), so a `file:` link a REMOTE program
        sent is REFUSED here rather than translated: that path belongs to the server, and opening it as
        this computer's path is the confusion the allowlist exists to prevent. A refusal is silent —
        a link is not a command and there is no status line to spend on it.
        """
        text = str(uri or "").strip()
        if not text:
            return False
        try:
            if not host_attr(self, "is_launchable_url")(text):
                return False
            return bool(host_attr(self, "QDesktopServices").openUrl(host_attr(self, "QUrl")(text)))
        except Exception:  # noqa: BLE001 — an opener failure is a refused link
            return False

    def _open_link_at(self, event) -> bool:
        """A click that belongs to a link; True when the event is CONSUMED (v1.9).

        The gesture: `Ctrl`+click whenever the application is tracking the mouse (the modifier that
        says "this click is LOCAL" for a link — `Shift` stays the shipped selection override) and a
        PLAIN click while it is not. A cell without a link — and a click that the tracking application
        owns — fall through to the ordinary press path, so the selection and the xterm report are
        untouched.
        """
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        tracking, _sgr = self.tscreen.mouse_tracking_mode()
        if tracking and not ctrl:
            return False
        uri = self.link_uri_at(event.position().toPoint())
        if not uri:
            return False
        self.open_link(uri)
        return True

    def _refresh_hover(self, pos):
        """The link hover under the pointer (v1.9) — a CELL and the pointing hand, never the URI."""
        try:
            row, col = self._cell_at(pos)
        except Exception:  # noqa: BLE001 — a dying screen has no hover
            row, col = None, None
        cell = (row, col) if self.link_uri_at(pos) else None
        if cell == self._hover_cell:
            return
        self._hover_cell = cell
        self._set_link_cursor(cell is not None)
        self.update()

    def _set_link_cursor(self, on: bool):
        """The pointing hand while a link is under the pointer, the default otherwise. Never raises."""
        try:
            if on:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
        except Exception:  # noqa: BLE001 — a widget mid-teardown
            pass

    def leaveEvent(self, event):
        """The pointer left the canvas — the link hover goes with it (v1.9)."""
        if self._hover_cell is not None:
            self._hover_cell = None
            self._set_link_cursor(False)
            self.update()
        super().leaveEvent(event)

    # ── mouse: LMB press → drag → release (v1.0RC2; v1.2.7 — double/triple-click) ─
    def mousePressEvent(self, event):
        # v1.9: the `OSC 8` link comes FIRST — a cell that carries one CONSUMES the press (so a link
        # is never also a selection start and never an xterm report), and every other cell is
        # untouched by this branch.
        if event.button() == Qt.MouseButton.LeftButton and self._open_link_at(event):
            event.accept()
            return
        # v1.6.3 (ROADMAP task 2): the application asked for the mouse → the press is
        # REPORTED and no local selection starts. Shift (the local override) sends it to
        # the branch below instead.
        if self._mouse_reports_to_pty(event):
            button = self._xterm_button(event.button())
            if button is not None:
                col, row = self._event_cell(event)
                self._send_mouse(button, col, row, True)
                event.accept()
                return
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
        # v1.9: the link hover follows the pointer — a LOCAL, non-consuming effect, so it is
        # refreshed before the routing below (a tracking TUI still gets its motion report).
        self._refresh_hover(event.position().toPoint())
        # v1.6.3 (ROADMAP task 2): a MOTION reaches the application under 1002 (while a
        # button is held) or 1003 (any motion) — the report is the held button + 32, and
        # "no button" is 3. Under 1000 a motion is not part of the protocol and falls
        # through to the local drag.
        if self._mouse_reports_to_pty(event, report_motion=True):
            col, row = self._event_cell(event)
            self._send_mouse(self._held_button(event.buttons()) + self.MOUSE_MOTION_FLAG,
                             col, row, True)
            event.accept()
            return
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
        # v1.6.3 (ROADMAP task 2): the release closes the report the application is
        # waiting for (SGR 'm' / the X10 code + 3) — the local selection is never touched.
        if self._mouse_reports_to_pty(event):
            button = self._xterm_button(event.button())
            if button is not None:
                col, row = self._event_cell(event)
                self._send_mouse(button, col, row, False)
                event.accept()
                return
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
        t = host_attr(self, "get_translator")()
        menu = host_attr(self, "QMenu")(self)
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
            # QContextMenuEvent.globalPos() already
            # returns a QPoint (unlike QMouseEvent.globalPosition() → a QPointF) —
            # the extra .toPoint() raised an AttributeError that the old except
            # swallowed silently: "the right-click does nothing" without a single visible
            # error. The coordinates — as they are.
            menu.exec(event.globalPos())
        except Exception as e:  # noqa: BLE001 — a GUI component must not crash the app
            _log = host_attr(self, "_get_app_log")()
            if _log is not None:
                _log.error(f"contextMenuEvent: menu.exec failed: {e}")
        event.accept()
