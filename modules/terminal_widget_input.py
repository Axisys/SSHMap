"""The INPUT and the KEY MAP of the terminal canvas (`TerminalWidget` wave).

`TerminalInputMixin` owns the ONE input point of a session: the xterm key table (`keyPressEvent` with
`_F_KEY_SEQUENCES`), the `Tab`/`Shift+Tab` interception and the `ShortcutOverride` claim
(`event` / `_CLAIMED_KEYS` / `_owns_shortcut`), the bracketed paste, `send_macro()` and the multi-input
broadcast (`_send` / `_resolve_multi_hub` / `_multi_*` / the per-session exclusion). Nothing here may
raise into the session and nothing may truncate.

Contract — `AGENTS.md` §4.3; mechanism — `DOCUMENTATION.md` §14a, §64.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

# xterm sequences for F1–F12 (the xterm table: DOCUMENTATION.md §14a):
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


class TerminalInputMixin:
    """The key map, the ONE input point and the multi-input broadcast (mixed into `TerminalWidget`)."""
    # ── Tab/Shift+Tab — Qt 6 intercepts BEFORE keyPressEvent ────
    def event(self, e):
        """Tab/Shift+Tab left
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

        the canvas must
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

    # ── the key family the canvas claims from window-level QActions ──
    # Every Ctrl+… combination (the xterm control codes — Ctrl+C/D/Z/V, the canvas's own Ctrl+Shift+F /
    # Ctrl+Shift+PgUp/PgDn), the function keys (F12 = the multi-input exit) and Delete (`\x1b[3~`). A
    # plain letter cannot collide with a QAction sequence (all of §4.9's defaults carry Ctrl/Shift/Alt),
    # so typing is deliberately NOT claimed, nor are the Alt-only combinations (the menubar mnemonics).
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
        * Ctrl+Shift+PageUp/PageDown → SCROLLBACK (DOCUMENTATION.md §14a): the
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
        * Tab → \\t / Shift+Tab → \\x1b[Z : on the real events they are
          intercepted EARLIER — in event() (the Qt 6 focus-change mechanism does not pass
          them to keyPressEvent; without this the focus left for the window buttons and
          \\t never reached the shell);
        * the AltGr guard (DOCUMENTATION.md §14a): the Ctrl+Alt combinations (on Windows
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
            # the AltGr guard (DOCUMENTATION.md §14a): the Ctrl+Alt combinations (on Windows
            # AltGr = Ctrl+Alt) must not go out as control codes.
            if mod & Qt.KeyboardModifier.AltModifier:
                event.ignore()
                return
            # v1.0RC3: Ctrl+Shift+PageUp/PageDown → the scrollback (DOCUMENTATION.md §14a).
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
            return host_attr(self, "_get_multi_hub")()
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
        mode everything typed is duplicated.

        v1.6.4 (ROADMAP task 5): typing (and pasting) is USER INTENT — under
        `terminal_scroll = "pin"` the view returns to the live line here, because the user is
        asking the shell for an answer. Output never does this; that is the whole point of the
        pin. The release happens before the transport guard, so it is the user's keystroke that
        is honoured and not "a keystroke that happened to reach a live channel".
        """
        self._release_pin()
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
                # a DEBUG line per broadcast —
                # the log shows how many sessions actually received the bytes (0 →
                # an empty registry/dead threads; N>0 → the bytes went to all the live ones).
                _log = host_attr(self, "_get_app_log")()
                if _log is not None:
                    _log.debug(
                        f"multi-input broadcast: {len(data)}B -> {sent} session(s)")
            except Exception:
                pass  # a broadcast failure must not break the input of the active session

    def _bracketed_paste(self):
        """Ctrl+V — the bracketed paste (carried over from v0.9.4): a multi-line clipboard
        arrives at the shell as a SINGLE block, not as line-by-line input.

        v1.7.5.1 (N44): the wrapper is CONDITIONAL. It is applied only while the application on the
        other end has enabled DECSET 2004 (read through the session's screen), because the protocol
        asks for it — a `sudo`/`passwd` prompt reads the tty without readline and would otherwise
        receive the escape bytes as part of the password. The clipboard is also stripped of the two
        markers, so pasted content can never close the paste early and let the rest arrive as typed
        input.
        """
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text()
        if not text:
            return
        try:
            payload = host_attr(self, "strip_paste_markers")(
                text.replace("\r\n", "\n").replace("\r", "\n"))
            data = payload.encode("utf-8")
            if self._paste_mode_enabled():
                data = b"\x1b[200~" + data + b"\x1b[201~"
            self._send(data)
        except Exception:
            pass

    def _paste_mode_enabled(self) -> bool:
        """Has the remote application asked for the bracketed-paste wrapper? (v1.7.5.1, N44)

        DEFAULT OFF: before the first prompt the mode is unknown, and RAW is the conservative
        direction — a wrong wrapper corrupts a password, a missing one merely types the block.
        """
        screen = getattr(self, "tscreen", None)
        reader = getattr(screen, "bracketed_paste_enabled", None)
        if not callable(reader):
            return False
        try:
            return bool(reader())
        except Exception:  # noqa: BLE001 — a screen read must never break a paste
            return False

    def send_macro(self, text) -> bool:
        """v1.3 (ROADMAP v1.3): send a command library macro to the PTY of THIS session.

        The sending — DIRECTLY to terminal_thread.send_data(), NOT through _send(): the
        macro is addressed ONLY to the active session (the pre-approved ROADMAP v1.3
        decision) — the multi-input broadcast would have duplicated it to all the open
        sessions (the precedent: the wheel passthrough of v1.2.13). The payload is built
        by build_macro_payload() (single-line — raw + \\n; multi-line — the bracketed
        paste). Never raises; False — an empty payload, no thread, or a dead/closed channel.

        v1.5.7: this is the ONE path every explicit send of the application goes through (the
        macro library, the History tab's "Send to terminal", the page's own `send_macro()`), so
        the COMMAND HISTORY of the session is fed from here — through the optional
        `command_sent_hook` the owning page installs (`TerminalSessionPage.record_sent_command`).
        The canvas stays Qt-light and knows no store: a hook that raises costs the history entry,
        never the send. Typed input is deliberately NOT recorded — the canvas sees raw bytes.
        """
        payload = host_attr(self, "build_macro_payload")(
            text, bracketed_paste=self._paste_mode_enabled())
        if not payload or self.terminal_thread is None:
            return False
        channel = getattr(self.terminal_thread, "channel", None)
        if channel is None or channel.closed:
            return False
        try:
            self.terminal_thread.send_data(payload)
        except Exception:   # noqa: BLE001 — a dead channel/thread mid-teardown
            return False
        hook = getattr(self, "command_sent_hook", None)
        if callable(hook):
            try:
                hook(text)
            except Exception:   # noqa: BLE001 — the history must never break a send
                pass
        return True

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
