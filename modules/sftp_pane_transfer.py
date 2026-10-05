"""The TRANSFERS, the conflict question and the batch copy/move of ONE Files pane (wave 2).

`SftpPaneTransferMixin` owns what happens AFTER the user acts: the upload / download queues with
their overwrite question (`_queue_uploads` / `_queue_downloads` / `_ask_conflict`), the name prompt,
the copy / move batch over the destination pane (`_remote_batch` / `_queue_transfer_batch`) with its
counters and its ONE closing report, and the worker's task slots (`_on_task_*`) with the sentence
renderers they emit. `_queue_transfer_batch()` is the DISPATCH over the PAIR of providers
(`LOCAL_PANE.md` §5): a task id belongs to the provider that queued it, so the answer re-lists the
pane that really changed, through ITS OWN dialect.

Contract — `SFTP_PANES.md` §5-§6, `LOCAL_PANE.md` §5-§7; mechanism — `DOCUMENTATION.md` §59-§64.
"""

import os
import posixpath

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

try:  # the operation kinds, the machine codes and the tree bounds of the worker
    from .sftp_worker import (KIND_COPY, KIND_MOVE, KIND_NORMALIZE, KIND_READ, MAX_TREE_ENTRIES,
                              MOVE_ERROR_REFUSED, OP_KINDS, PARTIAL_CODE, READ_ERROR_BINARY,
                              READ_ERROR_TOO_LARGE, TREE_ERROR_TOO_BIG, local_name_problem,
                              parse_task_payload)
except ImportError:
    from sftp_worker import (KIND_COPY, KIND_MOVE, KIND_NORMALIZE, KIND_READ, MAX_TREE_ENTRIES,
                             MOVE_ERROR_REFUSED, OP_KINDS, PARTIAL_CODE, READ_ERROR_BINARY,
                             READ_ERROR_TOO_LARGE, TREE_ERROR_TOO_BIG, local_name_problem,
                             parse_task_payload)

try:  # the LOCAL provider's machine codes and its non-refusal listing note
    from . import local_fs_worker as local_fs
except ImportError:
    import local_fs_worker as local_fs


class SftpPaneTransferMixin:
    """The transfers, the conflict question and the batch copy/move (mixed into `_SftpPane`)."""
    def _on_task_error(self, task_id: int, kind: str, message: str):
        """task_error: for a "read" task the message is a MACHINE code — the pane
        turns it into an i18n hint (the window's status bar stays silent about
        reads: terminal_page skips them, the pane owns the message).

        The QUEUE is untouched (the worker contract): a refusal of one file does
        not break the listing or the transfers.

        v1.3.1.1: a refusal is also a FACT for the session — only the worker sees
        the content, so its verdict marks the row (a null byte inside a `.txt`
        cannot be guessed from the name) and the mark survives re-listing.

        v1.7rc1: the ONE worker signals EVERY pane, so a pane that does not own the task
        returns at once — otherwise the other pane would report a stranger's failure (or
        draw a stranger's row).

        v1.7.4rc1: a LOCAL provider reports its refusals as MACHINE payloads too, so the
        operation and normalize branches of a local pane render `local_error_text()` — the
        listing note of a skipped entry (`KIND_LIST_PARTIAL`) is the one answer that is NOT a
        failure and comes BEFORE every task map (the listing itself has already arrived).
        """
        if kind == local_fs.KIND_LIST_PARTIAL:
            self.message.emit(host_attr(self, "local_error_text")(message))
            return
        if kind == KIND_READ:
            if task_id not in self._read_tasks:
                return   # another pane's read (or the command history's) — not ours
            path = self._read_tasks.pop(task_id, "")
            if task_id == self._last_read:
                self._last_read = None
            if path and message in (READ_ERROR_BINARY, READ_ERROR_TOO_LARGE):
                self._blocked[path] = message
                self._mark_row(path)
            self.message.emit(self._read_error_text(message, path))
        elif kind in OP_KINDS:
            # v1.3.3.2: a file operation failed (the queue lives on) — the pane owns
            # the message (the page stays silent about the operation kinds), and the
            # listing is NOT refreshed: nothing changed on the server.
            if self._op_tasks.pop(task_id, None) is None:
                return   # another pane's operation
            if kind in (KIND_COPY, KIND_MOVE):
                # v1.7rc2: a remote copy/move — the machine payload becomes a translated
                # sentence (a partial tree, a refused rename, a tree over its bound) and
                # the batch counts ONE failure (the v1.1.3 rule: the rest goes on).
                self.message.emit(self._remote_error_text(message))
                self._answer_batch_task(task_id, "failed")
            else:
                self.message.emit(self._op_error_text(message))
        elif kind in ("upload", "download") and self.source == host_attr(self, "SOURCE_LOCAL") \
                and task_id in self._own_transfers:
            # v1.7.4rc2: the LOCAL engine's transfers ride the PANE's own signal — there is no
            # session page listening to it — so a refused local copy is said here, and only for
            # a task THIS pane queued (a remote upload keeps the window's status line).
            self.message.emit(self._op_error_text(message))
        elif kind == KIND_NORMALIZE:
            # v1.6.3: the address bar asked for a path the server cannot resolve — the bar
            # keeps the typed text (nothing navigated) and the reason is a sentence.
            typed = self._normalize_tasks.pop(task_id, None)
            if typed is None:
                return   # another pane's normalize
            self.message.emit(_t("sftp.path_error", path=typed, error=message)
                              if self.source == host_attr(self, "SOURCE_REMOTE")
                              else _t("sftp.path_error", path=typed,
                                      error=host_attr(self, "local_error_text")(message)))
        elif kind == "list":
            # v1.3.3.2: the pre-flight listing of a drop on a row failed (the
            # directory vanished / no permission) — the batch is dropped, the pane
            # reports the reason instead of uploading into nowhere.
            failed_dir = self._pending_lists.pop(task_id, None)
            # v1.7.3 (task 2): the REMEMBERED directory may be the one that is gone — a restored
            # path is a hint, so the pane says so and opens the shipped starting directory.
            if failed_dir and failed_dir == self._restore_dir:
                self._restore_dir = ""
                self._restored = True
                self.message.emit(_t("sftp.dir_missing", path=failed_dir,
                                     fallback=self.paths.root()))
                self._relist(self.paths.root())
                self._on_task_finished(task_id)
                return
            pending = self._pending_batches.pop(task_id, None)
            if pending is not None:
                self.message.emit(self._op_error_text(message))
            if self._pending_drops.pop(task_id, None) is not None:
                self.message.emit(self._op_error_text(message))
        self._on_task_finished(task_id)

    def _op_error_text(self, message: str) -> str:
        """The sentence of a failed operation, in the source's own vocabulary (v1.7.4rc1).

        A LOCAL refusal is a machine payload with the OS's own text inside it, and the one place
        that knows how to spell it is `local_error_text()`; a remote task_error is already the
        server's sentence and goes through the shipped generic key unchanged. A REFUSED NAME
        (v1.7.5.1, N40) is named in the user's language by the ONE `name_refusal_text()`, and a
        DIRECTORY download that stopped in the middle (a `PARTIAL` payload) keeps its counters —
        a refusal inside that payload is rendered by the same helper.
        """
        refusal = host_attr(self, "name_refusal_text")(message)
        if refusal:
            return refusal
        data = parse_task_payload(message)
        if data and str(data.get("code") or "") == PARTIAL_CODE:
            path = str(data.get("path") or "")
            failed = str(data.get("error") or "")
            return _t("sftp.cmd.partial", name=self.paths.basename(path) or path,
                      copied=int(data.get("copied") or 0),
                      error=host_attr(self, "name_refusal_text")(failed) or failed)
        if self.source == host_attr(self, "SOURCE_LOCAL"):
            return host_attr(self, "local_error_text")(message)
        return _t("sftp.op.error", error=message)

    def _read_error_text(self, code: str, path: str = "") -> str:
        """READ_ERROR_* → the translated hint.

        Any OTHER message is a real failure reported by the worker (a path or
        permission error, str(exception)) — it goes through the same translated
        line with the file name, so the reader always gets a readable sentence.

        v1.7.5: a `too_large` verdict names the pane's OWN ceiling — the read is truncated at it,
        so this answer can only come from a read that could not be truncated.
        """
        if code == READ_ERROR_BINARY:
            return _t("sftp.viewer.binary")
        if code == READ_ERROR_TOO_LARGE:
            return _t("sftp.viewer.too_large", limit=host_attr(self, "format_size")(self.viewer_cap()))
        return _t("sftp.viewer.read_failed",
                  name=posixpath.basename(path) if path else "?",
                  error=code or "unknown error")

    # ── Operations (buttons) ─────────────────────────────────────────────

    def _on_upload(self):
        if self._refuse_elevated_write() or self._refuse_without_provider():
            return
        files, _ = host_attr(self, "QFileDialog").getOpenFileNames(
            self, _t("sftp.upload_dialog_title"))
        if not files:
            return   # the dialog was cancelled
        self._queue_uploads(files, self._current_dir,
                            self._names_in_current_dir())

    def _on_download(self):
        if self._refuse_without_provider():
            return
        items = [i for i in self.tree.selectedItems()
                 if not i.data(0, self.ISDIR_ROLE)]
        if not items:
            self.message.emit(_t("sftp.no_selection"))
            return
        local_dir = host_attr(self, "QFileDialog").getExistingDirectory(
            self, _t("sftp.download_dir_title"))
        if not local_dir:  # dialog cancelled — quietly do nothing
            return
        self._queue_downloads(items, local_dir)

    def _refuse_without_provider(self) -> bool:
        """No bound provider → the shipped "waiting" sentence, and True (the caller returns).

        A LOCAL pane always has its provider, so this is the REMOTE pane's waiting state
        (`SFTP_PANES.md` §1, unchanged); `_waiting` is the declared flag the path bar follows.
        """
        if self._waiting or self.provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return True
        return False

    def _on_cancel(self):
        # v1.7.3: a running `Send to…` is cancelled with the queue it uses — the relay drops its
        # spool on the way out (a cancel must never leave a plaintext copy behind).
        cancel_sends = getattr(self._container, "cancel_sends", None)
        if callable(cancel_sends):
            try:
                cancel_sends()
            except RuntimeError:
                pass   # Qt teardown — the container is already gone
        provider = self.provider
        if provider is not None:
            try:
                provider.cancel()
            except (RuntimeError, AttributeError):
                pass   # Qt teardown — the provider is already gone

    # ── v1.3.3.2: the batch + the overwrite conflict (ROADMAP task 2) ────

    def _names_in_current_dir(self) -> set:
        """The names the CURRENT listing shows.

        The conflict check must never be a guess, and the tree is exactly what the
        server last answered for the shown directory (a row of another directory
        cannot be in it).
        """
        names = set()
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is self._up_item:
                    continue
                names.add(item.text(0))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        return names

    def _ask_conflict(self, name: str, target: str, remaining: int, facts: str = ""):
        """The overwrite question — a method so a test can replace the whole policy."""
        return host_attr(self, "ask_conflict")(self, name, target, remaining, facts)

    def _conflict_decision(self, name: str, target: str, remaining: int):
        """The decision of ONE conflict → `(action, apply_all)`.

        action ∈ `"overwrite" | "skip" | "rename"`; a cancelled dialog — and any
        broken answer of a replaced seam — is a SKIP: the destination is left alone
        and the batch goes on. `apply_all` asks to reuse the decision for the REST
        of this batch (never for "rename": a batch rename needs a name per file).
        """
        try:
            action, apply_all = self._ask_conflict(name, target, remaining)
        except Exception:   # noqa: BLE001 — a dialog must never break a transfer
            return "skip", False
        if action not in ("overwrite", "skip", "rename"):
            return "skip", False
        if action == "rename":
            return action, False
        return action, bool(apply_all)

    def _prompt_name(self, title: str, current: str = "") -> str:
        """The name input of New folder / Rename (QInputDialog — a module attribute:
        `STAB.QInputDialog = <fake>` is the test seam).

        Returns the validated name; "" — cancelled or invalid (empty, ".", "..",
        a path separator): the caller quietly does nothing. The worker never sees a
        name it would have to sanitize.

        The separator rule is the REMOTE one (a POSIX server accepts `:` and a trailing dot); a
        LOCAL pane asks the platform's OWN rule instead (v1.7.5.1, N40), so a name typed here can
        no longer open an alternate data stream or lose its last character.
        """
        try:
            text, ok = host_attr(self, "QInputDialog").getText(self, title, _t("sftp.op.name_prompt"),
                                            text=current)
        except Exception:   # noqa: BLE001 — a dialog must never break the pane
            return ""
        if not ok:
            return ""
        name = (text or "").strip()
        if self.source == host_attr(self, "SOURCE_LOCAL"):
            if local_name_problem(name):
                self.message.emit(_t("sftp.op.invalid_name"))
                return ""
            return name
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            self.message.emit(_t("sftp.op.invalid_name"))
            return ""
        return name

    def _queue_uploads(self, files: list, target_dir: str, known: set):
        """Queue a batch of local files into target_dir, resolving the conflicts.

        `known` — the names already present in target_dir (from a LISTING of that
        directory: the current listing for the Upload button and for a drop on the
        body, the pre-flight listing for a drop on a directory row). "Apply to all"
        of the dialog is remembered for the REST of this batch only — the question is
        asked ONCE per batch, whichever pane started it.

        v1.7.4rc2: the PROVIDER is the pane's own, so the same body runs for a local
        pane as well (LOCAL_PANE.md §7): an Explorer drop on the OS disk is a LOCAL
        copy of every file into the directory on the screen, and a drop on a remote
        pane is the shipped upload.

        v1.8: an ELEVATED pane refuses the whole batch at this ONE door (`ELEVATED_PANE.md` §5) —
        the pre-flight listing of a drop reaches the uploads here, so the refusal sits here too.
        """
        if self._refuse_elevated_write():
            return
        provider = self.provider
        if provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        apply_all = ""
        total = len(files)
        for index, local_path in enumerate(files):
            name = os.path.basename(local_path)
            if name in known:
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, target_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        continue   # cancelled → this file is skipped
                    name = new_name
            self._remember_transfer(provider.queue_upload(local_path, target_dir,
                                                          remote_name=name))

    def _queue_downloads(self, items: list, local_dir: str):
        """Queue a batch of local files into local_dir, resolving the conflicts.

        The local existence check is a plain `os.path.exists` — no listing and no
        network, so it can never be stale.

        v1.7.4rc2: the provider is the pane's own here too, so a LOCAL pane's
        "Download" is a copy into the chosen directory through the local engine
        (LOCAL_PANE.md §5) — the signature of the provider method is the shipped one.
        """
        provider = self.provider
        if provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        apply_all = ""
        total = len(items)
        for index, item in enumerate(items):
            remote_path = item.data(0, self.PATH_ROLE)
            name = self.paths.basename(remote_path)
            # v1.7.5.1 (N40): a server-offered NAME that is PATH SYNTAX on this platform is refused
            # BEFORE the conflict question and before a task is queued — the worker checks the same
            # rule at `open()` (the authoritative gate), but a 500-file batch must not pay 500 round
            # trips to learn what one PURE predicate knew. One sentence, and the batch goes on.
            if self.source == host_attr(self, "SOURCE_REMOTE"):
                problem = local_name_problem(name)
                if problem:
                    self.message.emit(_t("sftp.name_refused", name=name))
                    continue
            if os.path.exists(os.path.join(local_dir, name)):
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, local_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        continue
                    name = new_name
            self._remember_transfer(provider.queue_download(remote_path, local_dir,
                                                            item.data(0, self.SIZE_ROLE),
                                                            local_name=name))

    def _remember_transfer(self, task_id):
        """v1.7rc1: remember a transfer THIS pane queued.

        The "Cancel" button is per pane while the QUEUE is one: only the pane that
        started the transfer lights its button up, so a pane never offers to cancel a
        batch the user began in the other one (the click still cancels the SHARED queue —
        that is what "Cancel" means).
        """
        if task_id is not None:
            self._own_transfers.add(task_id)

    # ── v1.7rc2: the remote copy / move of a batch (ROADMAP v1.7rc2) ─────

    def _rows_for_batch(self) -> list:
        """The rows a copy/move batch acts on (v1.7rc2).

        The SELECTION is the batch — the classic commander behaviour, and the reason the
        overwrite question can be answered "apply to all" ONCE for the whole run. An empty
        selection falls back to the CURRENT row (one click selects a row anyway); the ".."
        row and any row without a path are never part of a batch.
        """
        rows = []
        try:
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item is self._up_item or not item.data(0, self.PATH_ROLE):
                    continue
                if item.isSelected():
                    rows.append(item)
        except RuntimeError:
            return []   # Qt teardown — the tree is already gone
        if not rows:
            current = self._current_row()
            if current is not None:
                rows = [current]
        return rows

    def _remote_batch(self, kind: str, target_pane):
        """Queue ONE copy/move batch of the selection into the OTHER pane's directory.

        The destination directory IS the other pane's listing, so the conflict check needs
        no listing of its own (the shipped `_names_in_current_dir()` rule: what the source
        last answered for that directory). A DIRECTORY row is part of the batch — a copy and
        a move carry a tree recursively — and a row whose destination would be ITSELF is
        skipped, because copying or moving a file onto itself is not an operation. The
        overwrite/skip/rename question is asked through the SHIPPED machinery and its "apply
        to all" answer holds for the rest of this batch only.

        v1.7.3: the body moved into `_queue_transfer_batch()` — the pane-to-pane drop needs
        exactly the same batch over a SOURCE LIST that is not the selection.

        v1.7.4rc2: that body is the DISPATCH over the PAIR of providers (LOCAL_PANE.md §5) —
        the ONE question, the shipped counters and the ONE closing report are the same for
        all four cases, and only the provider that runs a transfer changes.
        """
        rows = self._rows_for_batch()
        if not rows:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        items = [(row.data(0, self.PATH_ROLE), row.text(0),
                  int(row.data(0, self.SIZE_ROLE) or 0)) for row in rows]
        self._queue_transfer_batch(items, kind, target_pane.current_dir,
                                   target_pane._names_in_current_dir(), target_pane)

    def _pane_source(self, pane) -> str:
        """The source a pane reads — asked of the PANE, never assumed (v1.7.4rc2)."""
        local = host_attr(self, "SOURCE_LOCAL")
        return local if getattr(pane, "source", host_attr(self, "SOURCE_REMOTE")) == local \
            else host_attr(self, "SOURCE_REMOTE")

    def _batch_provider(self, target_pane, src: str = ""):
        """The provider that RUNS a batch from `src` into `target_pane` (v1.7.4rc2).

        A REMOTE destination is always the SESSION's transport: the container's shipped worker
        carries the source pane's own copy AND the bytes of a LOCAL source out (`queue_upload`) —
        the local provider has no network, no credential and no channel. A LOCAL destination with
        a local source is that pane's own engine; with a remote source the download half still
        rides the session's worker (LOCAL_PANE.md §5).
        """
        src = str(src or self.source)
        dst = self._pane_source(target_pane)
        if dst == host_attr(self, "SOURCE_LOCAL") and src == host_attr(self, "SOURCE_LOCAL"):
            return getattr(target_pane, "provider", None) or self.provider
        return self.worker

    def _queue_transfer_batch(self, items: list, kind: str, target_dir: str, known: set,
                              target_pane=None, source: str = ""):
        """ONE copy/move batch of `(source, row_name, size)` triples into `target_dir`.

        `known` is the destination's listing as it is on the screen (never a guess), the ".."
        row and a pathless row are never part of a batch, a row that already IS the destination
        is skipped, and the ONE closing report counts copied / skipped / failed.

        v1.7.4rc2: a task id belongs to the PROVIDER that queued it, so the destination (its pane
        and its directory) is remembered per task in `_op_targets` and the answer re-lists the
        pane that really changed through ITS OWN dialect — a remote answer never re-lists a local
        pane and the other way round. `source` names where the ITEMS came from when the DESTINATION
        pane queues them (a pane-to-pane drop): the dialect of a row's path is the dialect of the
        pane that produced it, never the one that received it.
        """
        target_pane = target_pane if target_pane is not None else self
        # v1.8: `ELEVATED_PANE.md` §5 — a copy or a move with an elevated pane at EITHER end is
        # the ONE refusal of the read-only surface, and the four rows of §5 keep their meaning.
        if self._elevated_batch_refused(target_pane):
            return
        local = host_attr(self, "SOURCE_LOCAL")
        src = local if str(source or self.source) == local else host_attr(self, "SOURCE_REMOTE")
        dst = self._pane_source(target_pane)
        if kind == KIND_MOVE and src != dst:
            # LOCAL_PANE.md §5 declares an upload / a download for a transfer that CROSSES the two
            # sources and a move only INSIDE one of them: a silent copy where the user asked for a
            # move is worse than ONE sentence, and F5 is right there for the copy.
            self.message.emit(_t("sftp.local.move_cross_source"))
            return
        provider = self._batch_provider(target_pane, src)
        if provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        # The answers of a batch arrive at the pane BOUND to the provider that runs it (§1), so a
        # cross-source upload is COUNTED by the remote pane while the conflict question and the
        # report stay where the user acted: a local pane never hears the session's transport.
        owner = self
        if provider is not self.provider:
            owner = self._container.pane_for_provider(provider) or self
        total = len(items)
        skipped = 0
        queued = []
        apply_all = ""
        src_paths = host_attr(self, "dialect_for")(src)
        dest_paths = target_pane.paths
        for index, (source_path, row_name, size) in enumerate(items):
            if not source_path:
                skipped += 1
                continue
            name = src_paths.basename(source_path) or str(row_name or "")
            if dest_paths.same(dest_paths.join(target_dir, name), source_path):
                skipped += 1   # the row already IS the destination — never an operation
                continue
            if name in known:
                if apply_all:
                    action = apply_all
                else:
                    action, to_all = self._conflict_decision(
                        name, target_dir, total - index - 1)
                    if to_all:
                        apply_all = action
                if action == "skip":
                    skipped += 1
                    continue
                if action == "rename":
                    new_name = self._prompt_name(_t("sftp.op.rename"), name)
                    if not new_name:
                        skipped += 1
                        continue
                    name = new_name
            queued.append((source_path, name, int(size or 0)))
        batch_id = owner._open_batch(kind, len(queued), skipped)
        for source_path, name, size in queued:
            task_id = self._queue_batch_item(provider, src, dst, kind, source_path, target_dir,
                                             name, size)
            if task_id is None:
                owner._count_batch(batch_id, "failed")   # the provider is gone — still an answer
                continue
            owner._op_batches[task_id] = batch_id
            owner._op_targets[task_id] = (target_pane, target_dir)
            owner._queue_op(task_id, kind)
            if kind == KIND_COPY or src != dst:
                # the progress bar + the Cancel button: a copy always reports, and a cross-source
                # transfer is an upload / a download whatever the batch calls it (v1.7.4rc2).
                self._remember_transfer(task_id)
        if not queued:
            owner._finish_batch(batch_id)   # everything was skipped — the report says so
            return
        self.message.emit(_t("sftp.cmd.batch_started", count=len(queued), dir=target_dir))

    def _queue_batch_item(self, provider, src: str, dst: str, kind: str, source: str,
                          target_dir: str, name: str, size: int):
        """Queue ONE item of a batch on the provider that owns the SOURCE (LOCAL_PANE.md §5).

        Three cases use three SHIPPED methods and no new transport: local→remote is the session
        worker's `queue_upload`, remote→local its `queue_download` (atomic, `<name>.part`), and a
        pair of one source is the shipped copy / move of that provider — the remote `queue_copy` /
        `queue_move` or the local engine of `modules/local_fs_worker.py`.
        """
        if dst == host_attr(self, "SOURCE_REMOTE") and src == host_attr(self, "SOURCE_LOCAL"):
            return provider.queue_upload(source, target_dir, remote_name=name)
        if dst == host_attr(self, "SOURCE_LOCAL") and src == host_attr(self, "SOURCE_REMOTE"):
            return provider.queue_download(source, target_dir, size, local_name=name)
        if kind == KIND_COPY:
            return provider.queue_copy(source, target_dir, name)
        return provider.queue_move(source, target_dir, name)

    def _open_batch(self, kind: str, total: int, skipped: int) -> int:
        """Open a batch record and return its id (the counters of ONE report, v1.7rc2)."""
        self._batch_seq += 1
        self._batches[self._batch_seq] = {"op": kind, "total": int(total), "done": 0,
                                          "failed": 0, "skipped": int(skipped), "answers": 0}
        return self._batch_seq

    def _count_batch(self, batch_id, key: str):
        """Count ONE answer of a batch; the last answer emits the ONE report (v1.7rc2).

        Every queued item produces exactly one answer (done / failed / cancelled — a
        cancelled item counts as failed, it was not transferred), so the report cannot be
        emitted early or stay silent.
        """
        record = self._batches.get(batch_id)
        if record is None:
            return
        record[key] = int(record.get(key, 0)) + 1
        record["answers"] = int(record.get("answers", 0)) + 1
        if record["answers"] >= record["total"]:
            self._finish_batch(batch_id)

    def _finish_batch(self, batch_id):
        """Emit the ONE closing report of a batch and forget it (v1.7rc2)."""
        record = self._batches.pop(batch_id, None)
        if record is None:
            return
        key = "sftp.cmd.copy_report" if record.get("op") == KIND_COPY else "sftp.cmd.move_report"
        self.message.emit(_t(key, done=record.get("done", 0), skipped=record.get("skipped", 0),
                             failed=record.get("failed", 0)))

    def _answer_batch_task(self, task_id, outcome: str):
        """Count the answer of ONE queued copy/move task into its batch (v1.7rc2)."""
        batch_id = self._op_batches.pop(task_id, None)
        if batch_id is None:
            return   # not a batch task of this pane (another pane's, or already counted)
        self._count_batch(batch_id, outcome)

    def _remote_error_text(self, message: str) -> str:
        """The task_error of a copy/move → a translated sentence (v1.7rc2).

        The worker reports a MACHINE payload for the three cases it knows (`parse_task_payload`):
        a PARTIALLY transferred tree (with its counters), a REFUSED cross-directory rename (the
        sentence names the fallback: copy + delete) and a tree over its declared bound.

        v1.7.4rc2: a copy or a move of the OS DISK travels the same way from the local engine, so
        its own codes are rendered through the ONE local table before the generic sentence.
        """
        data = parse_task_payload(message)
        code = data.get("code") if data else None
        if code == PARTIAL_CODE:
            copied = data.get("copied", 0)
            path = str(data.get("path") or "")
            failed = str(data.get("error") or "")
            return _t("sftp.cmd.partial", name=self.paths.basename(path) or path,
                      copied=copied, error=host_attr(self, "name_refusal_text")(failed) or failed)
        if code == MOVE_ERROR_REFUSED:
            return _t("sftp.cmd.move_refused", error=str(data.get("error") or ""))
        if code == TREE_ERROR_TOO_BIG:
            return _t("sftp.cmd.tree_too_big",
                      limit=int(data.get("limit") or MAX_TREE_ENTRIES))
        if code in local_fs.LOCAL_ERROR_KEYS:
            return host_attr(self, "local_error_text")(message)
        refusal = host_attr(self, "name_refusal_text")(message)
        if refusal:
            return refusal
        return _t("sftp.op.error", error=message)

    # ── Transfer state (the "Cancel" button) ─────────────────────────────

    def _on_task_started(self, task_id: int, kind: str, _label: str):
        if kind in ("upload", "download", "copy") and task_id in self._own_transfers:
            self._transfer_tasks.add(task_id)
            self.btn_cancel.setEnabled(True)

    def _on_task_done(self, task_id: int, detail: str):
        """task_done: an OPERATION refreshes the listing (v1.3.3.2) and reports the
        result; a transfer and a read keep their v1.1.3/v1.3.1 handling.

        v1.7rc2: a remote copy/move reports through its BATCH (one closing report instead
        of one line per file) and re-lists EVERY pane showing a directory it touched — the
        destination changed, and a move also emptied the source.

        v1.7.4rc2: the re-list goes to the pane that really CHANGED, through ITS OWN dialect
        (`_op_targets`, LOCAL_PANE.md §5): `detail` is a local path when the destination is the
        OS disk, so the shipped `posixpath.dirname()` would send a remote pane to a Windows path.

        v1.8: a transfer that rode the pane's OWN engine reports itself — the OS disk and the
        ELEVATED client have no session page listening to them (`ELEVATED_PANE.md` §3).
        """
        kind = self._op_tasks.pop(task_id, None)
        if kind in (KIND_COPY, KIND_MOVE):
            pane, dest_dir = self._op_targets.get(task_id) or (None, "")
            pane = pane if pane is not None else self
            try:
                changed = pane.paths.dirname(detail) or dest_dir
            except (RuntimeError, AttributeError):
                changed = dest_dir
            self._container.relist_pane(pane, changed)
            if kind == KIND_MOVE:
                self._container.relist_pane(self, self._current_dir)
            self._answer_batch_task(task_id, "done")
            self._on_task_finished(task_id)
            return
        own_engine = task_id in self._own_transfers and (
            self.source == host_attr(self, "SOURCE_LOCAL") or bool(getattr(self, "elevated", False)))
        if kind is None and own_engine:
            # A transfer of the pane's own engine (the local one, or the elevated client): the
            # directory ON THE SCREEN changed and no session page re-lists it, so the pane does.
            self._relist(self._current_dir)
            if bool(getattr(self, "elevated", False)):
                name = self.paths.basename(detail) or detail
                self.message.emit(_t("sftp.transfer_done", name=name))
            self._on_task_finished(task_id)
            return
        if kind is not None:
            self.message.emit(_t("sftp.op.done", name=detail))
            self._relist(self._current_dir)
        self._on_task_finished(task_id)

    def _on_task_cancelled(self, task_id: int, _kind: str):
        kind = self._op_tasks.pop(task_id, None)
        # A cancelled pre-flight listing: its batch will never be queued (the
        # bookkeeping must not leak into the next transport).
        self._pending_batches.pop(task_id, None)
        if kind in (KIND_COPY, KIND_MOVE):
            # v1.7rc2: the item was not transferred — it counts as a failure of its batch
            # (the window's status bar has already said "Transfer cancelled").
            self._answer_batch_task(task_id, "failed")
        self._on_task_finished(task_id)

    def _on_task_finished(self, task_id: int):
        # v1.3.1: a read task that ended without an answer (cancelled) leaves no trace.
        self._read_tasks.pop(task_id, None)
        # v1.6.3: the same for the address bar's tasks and the completer's listings.
        self._normalize_tasks.pop(task_id, None)
        self._completer_lists.pop(task_id, None)
        # v1.7.4rc2: the destination of a batch task is forgotten with its answer.
        self._op_targets.pop(task_id, None)
        self._own_transfers.discard(task_id)
        if task_id in self._transfer_tasks:
            self._transfer_tasks.discard(task_id)
            if not self._transfer_tasks:
                self.btn_cancel.setEnabled(False)
