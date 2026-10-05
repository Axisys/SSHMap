"""The TRANSCRIPT tee of the terminal canvas (`TerminalWidget` wave).

`TerminalTranscriptMixin` owns the local copy of the session's OUTPUT: the binary append
(`start_transcript` / `stop_transcript` / `write_transcript` — the `script(1)` semantics, the raw stream
ANSI sequences included), the suggested file name built from the host, and the checkable context-menu item
that asks for the path. A broken file stops the tee and never raises into the session.

Contract — `AGENTS.md` §4.3; mechanism — `DOCUMENTATION.md` §14a, §64.
"""

import time

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr


class TerminalTranscriptMixin:
    """The transcript tee, its file name and its menu item (mixed into `TerminalWidget`)."""
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
            _log = host_attr(self, "_get_app_log")()
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
            _log = host_attr(self, "_get_app_log")()
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
            path, _filter = host_attr(self, "QFileDialog").getSaveFileName(
                self, host_attr(self, "get_translator")()("terminal.menu.save_transcript"),
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
