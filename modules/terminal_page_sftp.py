# -*- coding: utf-8 -*-
"""The SFTP task BRIDGE of a terminal session — the worker, its slots and the progress line.

`TerminalPageSftpMixin` opens the SFTP channel over the session's OWN transport (no second
authentication), owns the transfer bookkeeping (`_sftp_tasks`, `_transfer_meters`, `_sftp_busy`) and
turns the worker's signals into the host's status/progress bridge. A facade global — the worker class,
the kind tables, the size/duration formatters, the name-refusal renderer and the translator — is
resolved through `host_attr()` (`ui/mixin_support.py`), so the mixin never imports `modules/terminal_page`
and the suite's substitution of `terminal_page.<name>` keeps working. Mechanism — §14b, §64."""

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

class TerminalPageSftpMixin:
    """The SFTP worker bridge (mixed into `TerminalSessionPage`)."""

    # The SFTP task kinds that feed the progress bridge (the busy counter, the QProgressBar and the
    # status-bar text): `read` is the viewer's read, whose OUTCOME the SFTP tab renders itself. The
    # file operations (mkdir/rename/delete) are outside this set on purpose — no bytes, no bar — and
    # a remote→remote COPY joins it (bytes, a total from stat, the rate/ETA meter) while a MOVE is a
    # rename (nothing to measure) — `DOCUMENTATION.md` §14.
    _SFTP_PROGRESS_KINDS = ("upload", "download", "read", "copy")

    # The i18n key that NAMES a transfer in flight — one mapping for the start line and for the
    # indeterminate-progress line, so a new kind cannot half-land.
    _SFTP_KIND_KEYS = {"upload": "sftp.uploading", "download": "sftp.downloading",
                       "read": "sftp.viewer.reading", "copy": "sftp.copying"}

    # ── v1.1.3: the SFTP tab (ROADMAP tasks 2-4) ────────────────────────────

    def _ensure_sftp(self) -> bool:
        """Open an SFTP channel over a live transport and start the worker.

        It reuses `terminal_thread.client.open_sftp()` — without a second
        authentication and a second known_hosts pass (ROADMAP task 3):
        the policy was already applied to the client at connect; open_sftp just
        opens a new channel on the same Transport. A lazy call: the first switch
        to the "Files" tab / connected_signal, if the user is already there.
        The session is not connected yet → False (the tab waits). The server's
        SFTP subsystem is unavailable → an error in the status (the
        status_message bridge), the worker is not created (a retry — on the next
        switch to the tab). v1.3.3.5: a page built WITHOUT the SFTP tab
        (`with_sftp=False`) never opens a channel — no Files tab exists to ask for it.
        """
        t = host_attr(self, "get_translator")()
        if getattr(self, "sftp_tab", None) is None:
            return False   # v1.3.3.5: a split pane is a command line — no SFTP channel
        worker = getattr(self, "_sftp_worker", None)
        if worker is not None and not worker.isFinished():
            return True
        thread = getattr(self, "terminal_thread", None)
        client = getattr(thread, "client", None) if thread is not None else None
        transport = None
        if client is not None:
            try:
                transport = client.get_transport()
            except Exception:
                transport = None
        if transport is None or not transport.is_active():
            return False
        try:
            sftp = client.open_sftp()
        except Exception as e:  # noqa: BLE001 — the SFTP subsystem may be disabled
            msg = t("sftp.open_failed", error=str(e))
            self.status_message.emit(
                msg if not msg.startswith("[") else f"Failed to open SFTP channel: {e}",
                8000)
            return False
        # WITHOUT a QObject parent: the window has WA_DeleteOnClose, and a hanging
        # transfer may outlive it — the orphan worker registry (the N4 v1.1.2RC1
        # pattern) keeps the thread alive until finished(); all slots are
        # disconnected in shutdown().
        new_worker = host_attr(self, "SftpWorker")(sftp)
        self._sftp_worker = new_worker
        new_worker.task_started.connect(self._on_sftp_task_started)
        new_worker.progress.connect(self._on_sftp_progress)
        new_worker.task_done.connect(self._on_sftp_task_done)
        new_worker.task_error.connect(self._on_sftp_task_error)
        new_worker.task_cancelled.connect(self._on_sftp_task_cancelled)
        new_worker.finished.connect(self._on_sftp_worker_finished)
        new_worker.start()
        self.sftp_tab.set_worker(new_worker)
        # v1.8: the SESSION's transport is published with the transport it belongs to — the
        # elevated pane of `ELEVATED_PANE.md` §2 opens its channel on it, and the pane may not
        # reach into this worker for the object.
        try:
            self.sftp_tab.set_transport(transport)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a bare stub — the elevation is simply not offered
        return True

    def _on_tab_changed(self, index: int):
        """A switch to the "Files" tab — a lazy SFTP start (idempotent).

        v1.3.3.5: on a page without the SFTP tab `self.sftp_tab` is None and no widget
        can be it, so the guard is a no-op by itself (kept for symmetry).
        """
        if self.sftp_tab is not None and self.tabs.widget(index) is self.sftp_tab:
            self._ensure_sftp()

    def _on_sftp_tab_message(self, msg: str):
        """A tab message (a file selection and the like) → the status_message bridge (5 s)."""
        self.status_message.emit(msg, 5000)

    def _on_connected_for_sftp(self):
        """connected_signal: open the channel the session is really going to need.

        Two triggers ask for it — the user was already sitting on "Files", or v1.7.1 shows
        the tree in the window's right-hand PANEL (where there is no Files tab to switch to).
        """
        try:
            if self._files_panel_on or self.tabs.currentWidget() is self.sftp_tab:
                self._ensure_sftp()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    def _transfer_kind_text(self, kind: str, label: str) -> str:
        """The status line naming a transfer in flight (v1.7rc2: ONE mapping for the
        start line and the indeterminate-progress line — `sftp.uploading` /
        `sftp.downloading` / `sftp.viewer.reading` / `sftp.copying`)."""
        key = self._SFTP_KIND_KEYS.get(kind, "sftp.downloading")
        return host_attr(self, "get_translator")()(key, name=label)

    def _on_sftp_task_started(self, task_id: int, kind: str, label: str):
        if self._shut_down:
            return   # v1.8rc6 (N56): a POSTED emission survives the disconnect() of the teardown
        t = host_attr(self, "get_translator")()
        self._sftp_tasks[task_id] = (kind, label)
        if kind in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy += 1
            self.progress_busy.emit()   # v1.1.x: setRange(0,0)+setValue(0)+show()
            self.status_message.emit(self._transfer_kind_text(kind, label), 0)
        elif kind in host_attr(self, "OP_KINDS"):
            pass   # v1.3.3.2: a file operation — the SFTP tab reports it itself
        else:  # list — without a progress bar
            self.status_message.emit(t("sftp.listing", path=label), 0)

    def _on_sftp_progress(self, task_id: int, done: int, total: int):
        if self._shut_down:
            return   # v1.8rc6 (N56): the posted-emission guard of the transfer family
        t = host_attr(self, "get_translator")()
        entry = self._sftp_tasks.get(task_id)
        if entry is None or entry[0] not in self._SFTP_PROGRESS_KINDS:
            return
        kind, label = entry
        if total > 0:
            self.progress_update.emit(done, total)   # v1.1.x: setRange(0,total)+setValue
            text = t("sftp.progress", name=label, pct=int(done * 100 // total),
                     done=host_attr(self, "format_size")(done),
                     total=host_attr(self, "format_size")(total))
            # v1.3.3.4 (ROADMAP task 6): the measured throughput and the ETA, appended
            # to the same line (an empty string while the meter has nothing honest to show).
            detail = self._transfer_detail(task_id, done, total)
            if detail:
                text = f"{text} · {detail}"
        else:  # total unknown — name only (an indeterminate bar)
            self.progress_update.emit(done, 0)
            text = self._transfer_kind_text(kind, label)
        self.status_message.emit(text, 0)

    def _transfer_detail(self, task_id: int, done: int, total: int) -> str:
        """v1.3.3.4 (ROADMAP task 6): "1.2 MB/s · ETA 0:42" — or "" while unmeasurable.

        The meter is created on the first sample of the task and dropped with it
        (SUCCESS, error and cancel all call _drop_transfer_meter). Never raises: a
        broken measurement costs the suffix, not the progress line.
        """
        try:
            meter = self._transfer_meters.get(task_id)
            if meter is None:
                meter = host_attr(self, "TransferMeter")()
                self._transfer_meters[task_id] = meter
            sample = meter.update(done, total)
            if sample is None:
                return ""
            rate, eta = sample
            if rate is None or rate <= 0:
                return ""
            t = host_attr(self, "get_translator")()
            parts = [t("sftp.rate", rate=host_attr(self, "format_size")(int(rate)))]
            eta_text = host_attr(self, "format_duration")(eta) if eta is not None else ""
            if eta_text:
                parts.append(t("sftp.eta", time=eta_text))
            return " · ".join(parts)
        except Exception:  # noqa: BLE001 — a cosmetic suffix must never break the transfer UI
            return ""

    def _drop_transfer_meter(self, task_id: int):
        """Forget the rate meter of a finished/failed/cancelled task."""
        try:
            self._transfer_meters.pop(task_id, None)
        except Exception:  # noqa: BLE001 — teardown race
            pass

    def _on_sftp_task_done(self, task_id: int, detail: str):
        if self._shut_down:
            return   # v1.8rc6 (N56): the posted-emission guard of the transfer family
        t = host_attr(self, "get_translator")()
        self._drop_transfer_meter(task_id)   # v1.3.3.4 (task 6): the meter dies with the task
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
            # v1.3.1: a read is reported by the SFTP tab itself (the preview panel),
            # not by a "transfer complete" line in the status bar.
            if entry[0] != "read":
                self.status_message.emit(t("sftp.transfer_done", name=entry[1]), 5000)

    def _on_sftp_task_error(self, task_id: int, kind: str, message: str):
        if self._shut_down:
            return   # v1.8rc6 (N56): the posted-emission guard of the transfer family
        t = host_attr(self, "get_translator")()
        self._drop_transfer_meter(task_id)   # v1.3.3.4 (task 6): the meter dies with the task
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        if kind == "read":
            # v1.3.1: the message of a read error is a MACHINE code — the SFTP tab
            # translates it (its message signal → the bridge); showing it here as
            # well would duplicate the hint with an untranslated code.
            return
        if kind in host_attr(self, "OP_KINDS"):
            # v1.3.3.2: a file operation — the SFTP tab wraps the server's error in
            # its own translated line (the same no-duplication rule as for "read").
            return
        refusal = host_attr(self, "sftp_name_refusal_text")(message)
        if refusal:
            # v1.7.5.1 (N40): a server name this platform cannot turn into a path — the ONE
            # renderer of that payload, so the sentence is the user's language, not JSON.
            self.status_message.emit(refusal, 8000)
            return
        prefix = t("terminal.error_prefix")
        self.status_message.emit(f"{prefix} {message}", 8000)

    def _on_sftp_task_cancelled(self, task_id: int, kind: str):
        if self._shut_down:
            return   # v1.8rc6 (N56): the posted-emission guard of the transfer family
        t = host_attr(self, "get_translator")()
        self._drop_transfer_meter(task_id)   # v1.3.3.4 (task 6): the meter dies with the task
        entry = self._sftp_tasks.pop(task_id, None)
        if entry is not None and entry[0] in self._SFTP_PROGRESS_KINDS:
            self._sftp_busy = max(0, self._sftp_busy - 1)
            if self._sftp_busy == 0:
                self.progress_hidden.emit()
        self.status_message.emit(t("sftp.transfer_cancelled"), 5000)

    def _on_sftp_worker_finished(self):
        """The worker stopped on its own (the transport died — the session
        closed/crashed): a state reset; the tab returns to "waiting", a restart —
        on the next switch to it, if a live connection appears. v1.3.3.5: a page
        without the SFTP tab has no worker to reset — the guard keeps it symmetrical."""
        try:
            self._sftp_worker = None
            self._sftp_tasks.clear()
            self._transfer_meters.clear()   # v1.3.3.4 (task 6): no live task — no meter
            self._sftp_busy = 0
            self.progress_hidden.emit()
            if getattr(self, "sftp_tab", None) is not None:
                self.sftp_tab.set_worker(None)
                # v1.8: the transport died with the worker — an elevation that rode it loses its
                # channel and is dropped by the pane (ELEVATED_PANE.md §4).
                self.sftp_tab.set_transport(None)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
