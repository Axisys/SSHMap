# -*- coding: utf-8 -*-
"""The LISTING and the address bar of ONE Files pane (`_SftpPane` wave 1).

`SftpPaneListingMixin` turns the provider's answer into rows and keeps the address bar honest:
the navigation (`go_up` / `_navigate` / `follow_directory` / `_relist`), the typed path resolved
by the SOURCE itself (`_on_path_entered` / `_on_normalize_ready`), the completer, the row
rendering with its "no preview" markers, the source header line, and the sort as a VIEW state
(`_sort_column` / `_sort_desc`) driven through Qt's own `sortItems()`. A task id belongs to the
PROVIDER that queued it, so a listing answers only its own (`SFTP_PANES.md` §2, `LOCAL_PANE.md`
§2-§3) and every path comes from the pane's ONE `PathDialect`.

Contract — `SFTP_PANES.md` §1-§2; mechanism — `DOCUMENTATION.md` §59, §66.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QTreeWidgetItem

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # v1.2.5: central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

#: v1.7.5: the LISTING's sort state is a VIEW state of the session (the pane's listing is rebuilt on
#: every navigation), never a config key: the column the header click chose and its direction. The
#: default IS the provider's own order (directories first, then case-insensitive by name), which is
#: why a listing nobody sorted is not re-ordered at all.
SORT_DEFAULT_COLUMN = 0
SORT_COLUMNS = (0, 1, 2)   # Name | Size | Modified — the three real sort keys of the pane


class SftpPaneListingMixin:
    """The listing, its navigation and its address bar (mixed into `_SftpPane`)."""

    @property
    def current_dir(self) -> str:
        """The currently shown directory (upload target) of THIS pane."""
        return self._current_dir

    # ── Navigation and listing ───────────────────────────────────────────

    def go_up(self):
        """".." — one level up (a no-op AT the root of this pane's source).

        The root test and the parent are the DIALECT's (v1.7.4rc1): `/` for a remote pane,
        a drive or a UNC share for a local one, so "go up" can never land on a path of the
        other source's spelling (LOCAL_PANE.md §2).
        """
        paths = self.paths
        if paths.is_root(self._current_dir):
            return
        parent = paths.dirname(self._current_dir) or paths.root()
        self._relist(parent)

    def _navigate(self, path: str):
        """Enter a directory (double-click on a directory row)."""
        self._relist(path)

    def follow_directory(self, path: str) -> bool:
        """v1.6.3 (ROADMAP task 5): the SHELL moved — move the listing with it.

        The caller is the session's OSC 7 scanner, so the path comes from the remote: an
        empty / relative / NUL-carrying report is refused here (a "no follow", never an
        error), a directory already on the screen is a no-op, and everything else goes
        through the ORDINARY `_relist()` — the same listing, the same staleness filter and
        the same `message` signal a click uses. Returns True when the view moved.

        v1.7.4rc1: a LOCAL pane NEVER follows — the report is a remote shell's path, so the
        follow stays the remote panes' alone (LOCAL_PANE.md §4). v1.8: an ELEVATED pane does not
        follow either — the report belongs to the LOGIN session's shell, while the listing shows
        another user's view (ELEVATED_PANE.md §3).
        """
        if self._waiting or self.provider is None \
                or self.source == host_attr(self, "SOURCE_LOCAL") \
                or bool(getattr(self, "elevated", False)):
            return False
        target = str(path or "")
        if not target.startswith("/") or "\x00" in target or target == self._current_dir:
            return False
        self._relist(target)
        return True

    def _relist(self, path: str):
        """Redraw the listing for the new current directory OF THIS PANE'S SOURCE."""
        paths = self.paths
        self._current_dir = str(path or "") or paths.root()
        self.tree.clear()
        self._up_item = None
        self._set_path_text(self._current_dir)
        self.btn_up.setEnabled(not paths.is_root(self._current_dir))
        provider = self.provider
        if provider is None:
            return
        tid = provider.queue_list(self._current_dir)
        if tid is not None:
            self._pending_lists[tid] = self._current_dir

    # ── v1.6.3 (ROADMAP task 4): the address bar ─────────────────────────────

    def _set_path_text(self, text: str):
        """Write the address bar WITHOUT echoing it back as an edit.

        `setText` on a QLineEdit does not emit `textEdited` (only `textChanged`), so no
        loop exists — the guard is here because the completer's directory bookkeeping is
        driven by `textEdited` alone and a programmatic write must never look like typing.
        """
        try:
            self.path_label.setText(text or "")
        except RuntimeError:
            pass  # Qt teardown — the bar is already destroyed

    def _on_path_entered(self):
        """Enter in the address bar: navigate through the SOURCE's own resolution.

        The text goes to the provider AS TYPED (a `~`, a relative path, a symlink are the
        source's business — a local guess would be a second, worse truth): the session's server
        for a remote pane, and the OS itself for a local one (`LocalFsWorker.queue_normalize`,
        LOCAL_PANE.md §2). A path that cannot be resolved answers `task_error` and is reported
        through the `message` signal, never as a traceback. The bar keeps the typed text until
        the answer arrives, so a failure leaves the user with what they typed.
        """
        provider = self.provider
        if provider is None:
            return
        typed = self.path_label.text() or ""
        if not typed.strip() or typed.strip() == _t("sftp.waiting_connection"):
            return
        tid = provider.queue_normalize(typed, self._current_dir)
        if tid is not None:
            self._normalize_tasks[tid] = typed

    def _on_normalize_ready(self, task_id: int, requested: str, resolved: str):
        """The server's REALPATH of a typed path → navigate there (v1.6.3)."""
        if self._normalize_tasks.pop(task_id, None) is None:
            return   # not this pane's task (v1.7rc1: the shared worker signals every pane)
        target = resolved or requested
        if not target:
            return
        self._relist(target)

    def _on_path_edited(self, text: str):
        """Feed the completer from the SAME async listing the pane already uses.

        The directory part of what is being typed decides the listing — at most ONE
        `queue_list()` per directory CHANGE (a keystroke inside the same directory costs
        nothing), its answer fills the model with the directories first (a trailing separator
        makes the completion continue into them) and the files after. A relative directory
        is resolved against the directory on the screen, exactly as Enter will resolve it.
        The split, the join and the separator are the DIALECT's (v1.7.4rc1), so a local pane
        completes `C:\\Users\\` the way the OS spells it (LOCAL_PANE.md §2).
        """
        provider = self.provider
        if provider is None:
            return
        paths = self.paths
        split = paths.dirname(text)
        directory = split or self._current_dir
        if split and not paths.is_absolute(split):
            directory = paths.join(self._current_dir, split)
        try:
            self.path_completer.setCompletionPrefix(paths.basename(text))
        except RuntimeError:
            return  # Qt teardown
        if directory == self._completer_dir:
            return
        self._completer_dir = directory
        tid = provider.queue_list(directory)
        if tid is not None:
            self._completer_lists[tid] = directory

    def _fill_completer(self, entries: list):
        """The completion model: directories first with a trailing SEPARATOR, then the files."""
        mark = self.paths.separator
        names = sorted(
            [(str(e.get("name", "")) + mark) if e.get("is_dir") else str(e.get("name", ""))
             for e in entries if e.get("name")],
            key=lambda n: (not n.endswith(mark), n.lower()))
        try:
            self.path_completer_model.setStringList(names)
        except RuntimeError:
            pass  # Qt teardown — the model is gone with the pane

    def _on_list_ready(self, task_id: int, remote_dir: str, entries: list):
        # v1.6.3: the completer's listing — it feeds the completion model and is NEVER
        # rendered (that directory is not on the screen); it is checked FIRST, because the
        # answer may belong to the directory the user is typing while the tree shows another.
        if self._completer_lists.pop(task_id, None) is not None:
            self._fill_completer(entries)
            return
        # v1.3.3.2: the pre-flight listing of a drop on a directory row — the answer
        # is NOT rendered (that directory is not on the screen), it only feeds the
        # conflict check of the batch that is waiting for it.
        pending = self._pending_batches.pop(task_id, None)
        if pending is not None:
            target, files = pending
            self._queue_uploads(files, target, {e["name"] for e in entries})
            self.message.emit(
                _t("sftp.drop_queued", count=len(files), dir=target))
            return
        # v1.7.3: the pre-flight listing of a PANE-to-pane drop — the same rule as above, for the
        # copy/move batch whose destination is not the directory on the screen.
        dropped = self._pending_drops.pop(task_id, None)
        if dropped is not None:
            items, kind, target, src = dropped
            self._queue_transfer_batch(items, kind, target, {e["name"] for e in entries},
                                       self, src)
            return
        requested = self._pending_lists.pop(task_id, None)
        # Staleness filter: render only the response for the CURRENT directory (navigation or
        # Refresh while an old listing was in flight — ignored), compared through the DIALECT:
        # the OS disk is case-insensitive, so `c:\users` IS `C:\Users` (LOCAL_PANE.md §2).
        paths = self.paths
        if requested is None or not paths.same(requested, self._current_dir) \
                or not paths.same(remote_dir, self._current_dir):
            return
        self.tree.clear()
        self._up_item = None
        if not paths.is_root(self._current_dir):
            up = host_attr(self, "_SftpRowItem")(self.tree)
            up.pinned = True          # v1.7.5: the ONE row no sort order may move
            up.setText(0, "..")
            up.setIcon(0, self._dir_icon())
            up.setData(0, self.PATH_ROLE, paths.dirname(self._current_dir) or paths.root())
            up.setData(0, self.ISDIR_ROLE, True)
            up.setData(0, self.SIZE_ROLE, 0)
            up.setData(0, self.MTIME_ROLE, 0)
            self._up_item = up
        for e in entries:
            self._add_entry_item(e)
        # v1.7.5: the rows arrive in the PROVIDER's order (directories first, then case-insensitive
        # by name) — which IS the default sort — so only a pane the user really sorted is re-ordered.
        if not self._sort_is_default():
            self.apply_sort()
        self._focus_first_row()
        # v1.7.3 (task 2): a directory the SERVER really answered for is what memory keeps — and
        # the restored hint has arrived, so it is no longer pending. A LOCAL pane has no
        # per-server memory: its directory belongs to the OS, not to a server (LOCAL_PANE.md §4).
        self._restore_dir = ""
        if self.source == host_attr(self, "SOURCE_REMOTE"):
            self._container.remember_dir(self._current_dir)

    def _focus_first_row(self):
        """Put the CURSOR on the first navigable row of a freshly rendered listing.

        A commander is driven by the keyboard, so a listing that came back with no current row
        would answer `Select a row first` to the first `F3`/`Enter` — the cursor lands on the
        first file or directory instead (never on the ".." row, which is navigation). Called
        after a listing is rendered; a row the user already picked is never moved. Never raises.
        """
        try:
            if self.tree.currentItem() is not None:
                return
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item is not None and item is not self._up_item and item.data(0, self.PATH_ROLE):
                    self.tree.setCurrentItem(item)
                    return
        except RuntimeError:
            pass  # Qt teardown — nothing to focus

    def _add_entry_item(self, entry: dict) -> QTreeWidgetItem:
        full = self.paths.join(self._current_dir, entry["name"])
        item = host_attr(self, "_SftpRowItem")(self.tree)
        item.setText(0, entry["name"])
        item.setIcon(0, self._dir_icon() if entry["is_dir"] else self._file_icon())
        item.setData(0, self.PATH_ROLE, full)
        item.setData(0, self.ISDIR_ROLE, bool(entry["is_dir"]))
        item.setData(0, self.SIZE_ROLE, int(entry.get("size") or 0))
        item.setData(0, self.MTIME_ROLE, int(entry.get("mtime") or 0))
        item.setText(1, "" if entry["is_dir"]
                    else host_attr(self, "format_size")(entry.get("size")))
        item.setText(2, "" if entry["is_dir"]
                    else host_attr(self, "format_mtime")(entry.get("mtime")))
        self._apply_preview_marker(item, full)   # v1.3.1.1: "no preview" markers
        return item

    def _dir_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    def _file_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    # ── v1.3.1.1: the "no preview" markers of the listing ────────────────

    def _apply_preview_marker(self, item: QTreeWidgetItem, path: str):
        """Mark a row the viewer cannot preview (a recoloured file icon + the
        reason in the tooltip); a previewable row is left with the plain icon and
        without a tooltip (the call is idempotent — it also CLEARS a stale mark).

        Directories are never marked. The name colour is deliberately untouched:
        an explicit setForeground() would overcome the selection colours of the
        style, while the recoloured glyph survives selection and does not rely on
        the colour alone (the tooltip spells the reason out).
        """
        if item.data(0, self.ISDIR_ROLE):
            return
        reason = host_attr(self, "preview_block_reason")(path, item.data(0, self.SIZE_ROLE),
                                                         self._blocked)
        if not reason:
            item.setIcon(0, self._file_icon())
            item.setToolTip(0, "")
            return
        item.setIcon(0, self._blocked_icon())
        item.setToolTip(0, self._blocked_tooltip(reason))

    def _blocked_tooltip(self, reason: str) -> str:
        """The reason of a marked row — the SAME texts the refusal itself shows."""
        if reason == host_attr(self, "READ_ERROR_TOO_LARGE"):
            return _t("sftp.viewer.too_large",
                      limit=host_attr(self, "format_size")(self.viewer_cap()))
        return _t("sftp.viewer.binary")

    def _blocked_icon(self):
        """The file icon of a marked row: the style's file glyph recoloured to the
        theme's "no preview" tone (cached).

        CompositionMode_SourceIn keeps the SHAPE and replaces the colour — the
        marker is visible as a shape, not only as a colour. A style that returns
        no pixmap for the standard icon (an exotic platform) falls back to the
        plain glyph: the tooltip still explains the row.
        """
        if self._blocked_icon_cache is not None:
            return self._blocked_icon_cache
        base = self._file_icon()
        pixmap = base.pixmap(16, 16)
        if pixmap.isNull():
            self._blocked_icon_cache = base
            return self._blocked_icon_cache
        pixmap = QPixmap(pixmap)   # a copy: the style may keep/share the pixmap
        painter = QPainter(pixmap)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(theme.SFTP_PREVIEW_BLOCKED))
        painter.end()
        self._blocked_icon_cache = QIcon(pixmap)
        return self._blocked_icon_cache

    def _mark_row(self, path: str):
        """Re-apply the marker of the row showing `path`; no such row in the
        current listing (another directory / a refreshed one) — nothing to do."""
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, self.PATH_ROLE) == path:
                    self._apply_preview_marker(item, path)
                    return
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── v1.7.5: the SOURCE HEADER LINE and the SORTABLE LISTING ──────────

    def header_text(self) -> str:
        """The pane's SOURCE HEADER LINE — the wording that names WHAT this pane reads (§3).

        A pane that reads the OS disk names itself (`sftp.local.this_computer`); an ELEVATED pane
        names the user it reads as (`ELEVATED_PANE.md` §3); a pane that reads a server names the
        SESSION (its alias — the label `set_session_info()` was given), with `user@host` as the
        fallback when the session was never identified and the shipped "waiting for connection"
        line when the pane belongs to nobody at all. An alias is DATA: it is never translated (no
        i18n key — the local wording is the shipped one).
        """
        if self._source == host_attr(self, "SOURCE_LOCAL"):
            return _t("sftp.local.this_computer")
        if bool(getattr(self, "elevated", False)):
            return _t("sftp.elevated.header", user=self.elevated_label())
        # The container's THREE readers answer "" for a pane nobody identified (a bare unit test),
        # so a foreign container needs no branch here — it is duck-typed like every other hook.
        try:
            label = self._container.session_label()
            user = self._container.session_user()
            host = self._container.session_host()
        except (AttributeError, RuntimeError):
            return _t("sftp.waiting_connection")
        if label:
            return str(label)
        if user and host:
            return f"{user}@{host}"
        if host:
            return str(host)
        return _t("sftp.waiting_connection")

    def _sync_header(self):
        """Show the SOURCE of this pane in its header line (the ONE writer of the widget). Never raises."""
        label = getattr(self, "header_label", None)
        if label is None:
            return
        try:
            text = self.header_text()
        except (AttributeError, RuntimeError, TypeError):
            return
        try:
            label.setText(text)
            label.setToolTip(text)
        except RuntimeError:
            pass  # Qt teardown — the label is already gone

    def source_header_label(self):
        """The header widget itself (the test seam of the clause above)."""
        return getattr(self, "header_label", None)

    def _on_header_clicked(self, column):
        """A click on a column header — the pane's ONE sort switch (v1.7.5).

        The same column flips the direction, another column starts ascending — the commander rule.
        Nothing else changes: the listing is NOT re-listed (the rows are already in memory) and no
        second sort table exists (the comparison lives on the ROW class).
        """
        try:
            column = int(column)
        except (TypeError, ValueError):
            return
        if column not in SORT_COLUMNS:
            return
        if column == self._sort_column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column, self._sort_desc = column, False
        self.apply_sort()

    def apply_sort(self):
        """Order the rows THE PANE'S WAY and show the direction on the header arrow.

        `sortItems()` is always asked for ASCENDING (the comparison on `_SftpRowItem` carries the
        real direction and the two GROUP rules); the indicator is then set to the REAL direction
        with the signals BLOCKED, so Qt's own handler cannot re-sort with the reversed comparator.
        Never raises.
        """
        tree = getattr(self, "tree", None)
        if tree is None:
            return
        try:
            tree.sortItems(self._sort_column, Qt.SortOrder.AscendingOrder)
        except (RuntimeError, TypeError, ValueError):
            return  # Qt teardown / an unsortable column — the listing keeps its order
        try:
            header = tree.header()
            header.blockSignals(True)
            try:
                header.setSortIndicatorShown(True)
                header.setSortIndicator(
                    self._sort_column,
                    Qt.SortOrder.DescendingOrder if self._sort_desc
                    else Qt.SortOrder.AscendingOrder)
            finally:
                header.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the arrow is cosmetic, the order is already right

    def _sort_is_default(self) -> bool:
        """True — the pane's order IS the provider's own (no re-sort needed after a listing)."""
        return (self._sort_column, self._sort_desc) == (SORT_DEFAULT_COLUMN, False)
