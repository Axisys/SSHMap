# -*- coding: utf-8 -*-
"""The cwd FOLLOW (OSC 7) of a terminal session — the two pure readers, the hook and the hold-back.

A shell REPORTS its working directory with the OSC 7 escape (`ESC ] 7 ; file://host/path`, BEL- or
ST-terminated) and the session's Files tab follows it. There is no environment to preset at spawn (ONE
session kind), so the hook is TYPED into the remote shell once, its echo is held back until the first
report answers it, and `parse_osc7()` / `osc7_report_end()` are the PURE readers over the raw bytes.
The constants and the two readers are RE-EXPORTED by `modules/terminal_page.py` (its shipped surface);
`TerminalPageCwdMixin` needs no facade global — this module IS the cluster. Mechanism — §64."""

import re
import time
import urllib.parse

from PySide6.QtCore import QTimer

# ── the Files tab follows the shell (OSC 7; `AGENTS.md` §4.3, `DOCUMENTATION.md` §64) ──
# A shell REPORTS its working directory with the OSC 7 escape (`ESC ] 7 ; file://host/path`,
# BEL- or ST-terminated). The application has ONE session kind (SSH), so there is no environment
# to preset at spawn: the session injects a ONE-TIME hook INVISIBLY (its echo held back),
# APPENDED to the user's `PROMPT_COMMAND` and, under zsh, through `precmd_functions+=`.
FOLLOW_CWD_CONFIG_KEY = "terminal_follow_cwd"
#: The bytes the follow TYPES into the remote shell. A PTY has no environment to preset, so the hook
#: is a command LINE — and a line a shell reads is a line it may record. The LEADING SPACE is the
#: only suppression available here, and it works exactly where the user's shell was already told to
#: ignore one (`HISTCONTROL=ignorespace`, zsh's `HIST_IGNORE_SPACE`); nothing more is claimed.
CWD_HOOK_COMMAND = (
    " _sshmap_cwd() { printf '\\033]7;file://%s%s\\033\\\\'"
    " \"${HOSTNAME:-localhost}\" \"$PWD\"; }; "
    "if [ -n \"${ZSH_VERSION:-}\" ]; then "
    "case \"${precmd_functions[*]:-}\" in *_sshmap_cwd*) ;; "
    "*) eval 'precmd_functions+=(_sshmap_cwd)';; esac; "
    "else case \"${PROMPT_COMMAND:-}\" in *_sshmap_cwd*) ;; "
    "*) PROMPT_COMMAND=\"_sshmap_cwd${PROMPT_COMMAND:+;$PROMPT_COMMAND}\";; esac; fi"
)
#: How long after `connected_signal` the hook goes out: the remote shell needs a moment to
#: reach its first prompt (the same reason the quick-launch command is deferred), and PTY
#: input is buffered by the kernel, so the hook is never lost.
CWD_HOOK_DELAY_MS = 400
#: The first report is what releases the hold-back; a shell that never answers costs the held
#: bytes back after this deadline (nothing is lost, the echo is simply shown).
CWD_HOLD_DEADLINE_MS = 4000
#: The hold-back buffer cap: a shell that floods (a `yes`-like startup script) must never
#: grow the queue without a bound — past this the held bytes are shown.
CWD_HOLD_MAX_BYTES = 256 * 1024
#: The bytes kept between two chunks so an OSC 7 split across a chunk boundary is still seen.
OSC7_CARRY_BYTES = 512
#: `ESC ] 7 ; <host><path>` terminated by BEL or ST (the two endings xterm accepts).
_OSC7_RE = re.compile(rb"\x1b\]7;([^\x07\x1b]*)(?:\x07|\x1b\\)")

def parse_osc7(data) -> str:
    """The directory of the LAST OSC 7 report in `data` ("" — none). PURE, no Qt.

    The payload is `file://<host><path>`: the `file://` scheme is required (anything else
    is a foreign report and means "no follow"), the host is everything up to the NEXT `/`
    and is deliberately ignored (the LISTING is the tab's own business), and the path is
    percent-DECODED (a directory with a space arrives as `%20`). A host-only payload, a
    report without the scheme and a path that is not absolute all answer "" — the shell on
    the other side is not ours to trust, so every degradation is "no follow", never an
    exception.
    """
    try:
        raw = bytes(data or b"")
    except Exception:  # noqa: BLE001 — a caller that hands over a str/None
        return ""
    last = None
    for last in _OSC7_RE.finditer(raw):
        pass
    if last is None:
        return ""
    payload = last.group(1)
    if not payload.startswith(b"file://"):
        return ""
    rest = payload[len(b"file://"):]     # <host><path> — the host may be empty
    cut = rest.find(b"/")
    if cut < 0:
        return ""
    try:
        path = urllib.parse.unquote(rest[cut:].decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — a malformed escape never breaks the session
        return ""
    if not path.startswith("/") or "\x00" in path:
        return ""
    return path

def osc7_report_end(data, after: int = 0) -> int:
    """The offset just PAST the first OSC 7 report that ends after `after` (-1 — none). PURE.

    `parse_osc7()` answers WHAT the last report says; this answers WHERE the first report that
    really arrived in this chunk ends — the boundary the echo hold-back needs: everything before
    it is the answer's own head (the tty's echo of the injected hook) and is DROPPED with the
    held bytes, while the tail (the new prompt, which bash prints AFTER `PROMPT_COMMAND` ran) is
    rendered as usual. `after` is the carry length: a report that ends inside the carry was
    already seen in an earlier chunk, so it is not an answer to a hook injected since.
    """
    try:
        raw = bytes(data or b"")
        start = max(0, int(after))
    except Exception:  # noqa: BLE001 — a caller that hands over a str/None
        return -1
    for match in _OSC7_RE.finditer(raw):
        if match.end() > start:
            return match.end()
    return -1

class TerminalPageCwdMixin:
    """The follow itself: the checkbox's state, the hook and the hold-back (mixed into the page)."""

    # ── v1.6.3 (ROADMAP task 5): the cwd follow (OSC 7) ─────────────────────

    def follow_cwd(self) -> bool:
        """Is this session following the shell's directory? (the checkbox's state)"""
        return bool(self._follow_cwd)

    def set_follow_cwd(self, enabled, persist: bool = False) -> bool:
        """Turn the follow on/off for THIS session (the checkbox / the config key).

        `persist=True` writes the ONE `terminal_follow_cwd` key through the ordinary
        merge-write (the settings-hub rule: an owner-written UI-state key). Turning it ON
        mid-session injects the hook if it never went out — a session that starts following
        late is not forced to reconnect. Never raises: a read-only HOME keeps the choice
        for the session.
        """
        self._follow_cwd = bool(enabled)
        tab = getattr(self, "sftp_tab", None)
        if tab is not None:
            tab.set_follow_cwd(self._follow_cwd)   # the checkbox is a VIEW of this state
        if not self._follow_cwd:
            # v1.6.4 fix: a follow turned OFF while its hook's echo is still held gives the held
            # bytes back at once — the output must never stay invisible because a switch moved.
            self._release_cwd_hold()
        if self._follow_cwd and not self._cwd_hook_sent:
            self._inject_cwd_hook()
        if persist:
            self._save_follow_cwd()
        return self._follow_cwd

    def _save_follow_cwd(self) -> bool:
        """Persist `terminal_follow_cwd` (the merge-write every config key uses). Never raises."""
        try:
            from i18n import save_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the session state
            return False
        try:
            return bool(save_config({FOLLOW_CWD_CONFIG_KEY: bool(self._follow_cwd)}))
        except Exception:  # noqa: BLE001 — a read-only HOME is not worth an error dialog
            return False

    def _on_follow_cwd_toggled(self, checked: bool):
        """The tab's checkbox changed → apply it to the session and persist it."""
        self.set_follow_cwd(checked, persist=True)

    def _on_connected_for_follow(self):
        """connected_signal: arm the ONE-TIME hook (deferred — the shell needs a prompt)."""
        if not self._follow_cwd:
            return
        QTimer.singleShot(CWD_HOOK_DELAY_MS, self._inject_cwd_hook)

    def _inject_cwd_hook(self) -> bool:
        """Send the OSC 7 hook ONCE, invisibly, over THIS session's channel.

        Directly through `terminal_thread.send_data()` — never the multi-input broadcast:
        one path typed into eight sessions would install eight hooks in eight shells.
        Returns True when the bytes went out. A dead channel, a follow that was turned off
        in the meantime and a repeated call are all ordinary False answers.
        """
        if self._cwd_hook_sent or not self._follow_cwd:
            return False
        thread = getattr(self, "terminal_thread", None)
        if thread is None or self._pty_channel() is None:
            return False   # not connected (yet) — the connected_signal path comes back
        self._cwd_hook_sent = True
        self._cwd_hold = bytearray()
        self._cwd_hold_deadline = time.monotonic() + CWD_HOLD_DEADLINE_MS / 1000.0
        try:
            thread.send_data((CWD_HOOK_COMMAND + "\n").encode("utf-8"))
        except Exception:  # noqa: BLE001 — a dead channel mid-teardown: no follow, no error
            self._cwd_hold = None
            return False
        QTimer.singleShot(CWD_HOLD_DEADLINE_MS, self._on_cwd_hold_timeout)
        return True

    def _scan_osc7(self, data) -> int:
        """Find an OSC 7 report in the RAW bytes, move the listing and answer WHERE it ends.

        The carry keeps the last `OSC7_CARRY_BYTES` bytes of the previous chunk, so a
        report split across two reads is still parsed. The FIRST report that really arrived in
        this chunk also releases the echo hold-back — DROPPING what is held (that is the hook's
        own echo); every later report only moves the listing, and a directory that did not
        change is a no-op.

        The return value is the offset in `data` just past that answering report (-1 — there was
        none), which is what `_hold_cwd_echo()` needs: the released hold must NOT let the echo
        through when the shell answered within the very same chunk. A report that lives entirely
        in the carry was already seen in an earlier chunk and is therefore not an answer —
        otherwise a shell that emits OSC 7 on its own would release the hold before the hook's
        echo has even been buffered. Never raises.
        """
        if not self._follow_cwd:
            return -1
        try:
            raw = bytes(data or b"")
        except Exception:  # noqa: BLE001 — a caller that hands over something odd
            return -1
        carry = self._cwd_carry
        chunk = carry + raw
        path = parse_osc7(chunk)
        self._cwd_carry = chunk[-OSC7_CARRY_BYTES:]
        if not path:
            return -1
        end = osc7_report_end(chunk, after=len(carry))
        if path != self._last_cwd:
            self._last_cwd = path
            self._apply_cwd(path)
        if end < 0:
            return -1          # a STALE report (seen before this chunk) — it answers nothing
        return max(0, end - len(carry))

    def _apply_cwd(self, path: str):
        """Move the Files tab to the directory the shell reported (the follow itself).

        Only a page with the SFTP tab and a LIVE worker can follow; a foreign path (the
        tab's own guard) and an unreachable server degrade to "no follow" — the report is a
        hint, never a command.
        """
        tab = getattr(self, "sftp_tab", None)
        if tab is None or getattr(tab, "worker", None) is None:
            return
        try:
            tab.follow_directory(path)
        except RuntimeError:
            pass  # Qt teardown — the tab is already destroyed

    def _hold_cwd_echo(self, data: bytes, cut: int = 0) -> bytes:
        """The hold-back of the hook's echo: the bytes to RENDER (b"" — nothing yet).

        While the hold is armed the output is buffered; the deadline (and the size cap)
        gives it BACK — a shell that never sends an OSC 7 costs nothing but a short pause,
        and its echo appears then. The first report DROPS the held bytes (that is exactly
        the hook's echo, which must never reach the canvas).

        `cut` is `_scan_osc7()`'s answer: the offset in `data` just past the report that
        released the hold. When it is set, the answer arrived WITHIN this chunk (the usual
        case — bash echoes the line and prints the next prompt in one read), so this chunk's
        head belongs to the echo and goes with the buffer: only `data[cut:]` — the new prompt,
        which bash writes AFTER `PROMPT_COMMAND` reported — is rendered.
        """
        buf = self._cwd_hold
        if buf is None:
            return data
        if cut > 0:
            self._cwd_hold = None
            return bytes(data[max(0, int(cut)):])
        if time.monotonic() >= self._cwd_hold_deadline:
            self._cwd_hold = None
            return bytes(buf) + bytes(data or b"")
        buf += bytes(data or b"")
        if len(buf) > CWD_HOLD_MAX_BYTES:
            self._cwd_hold = None
            return bytes(buf)   # a flooding shell is shown, never buffered forever
        return b""

    def _on_cwd_hold_timeout(self):
        """The deadline expired: give the held bytes BACK through the ordinary output path."""
        self._release_cwd_hold()

    def _release_cwd_hold(self) -> bytes:
        """Hand the held bytes back through the ordinary output path (idempotent). Never raises.

        The ONE release of a hold that was NOT answered by a report — the deadline of
        `_on_cwd_hold_timeout` and a follow that is turned OFF while the hold is armed both come
        here, so a hold can never outlive the reason it was taken for (the output must not stay
        invisible because a checkbox changed).
        """
        buf = self._cwd_hold
        if buf is None:
            return b""
        self._cwd_hold = None
        if not buf:
            return b""
        try:
            self._on_output(bytes(buf))
        except Exception:  # noqa: BLE001 — a teardown race: the bytes are dropped, not raised
            return b""
        return bytes(buf)
