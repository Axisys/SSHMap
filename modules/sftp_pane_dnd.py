"""The DRAG & DROP and the ROW CONTEXT MENU of ONE Files pane (wave 2).

`SftpPaneDndMixin` owns the two gestures of a listing that are not a plain click: the drag & drop of
a row INTO a pane (`eventFilter` / `dragEnterEvent` / `dropEvent` / `_on_pane_drop`, told apart by
`PANE_DRAG_MIME`) and the right-click row menu (`_build_context_menu` with its
`Send to ▸ <session>` submenu, its labels REBUILT at every open). A drop resolves the directory
under the cursor and hands the batch to the shipped copy/move machinery; the menu only TRIGGERS the
shipped operations and the relay.

Contract — `SFTP_PANES.md` §4, §4a; mechanism — `DOCUMENTATION.md` §59-§63.
"""

import sys

from PySide6.QtCore import QEvent, Qt

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:  # AGENTS.md §4.1: the ONE seam for a facade global — a mixin never imports the facade module
    from ..ui.mixin_support import host_attr
except ImportError:
    from ui.mixin_support import host_attr

try:  # the copy/move kinds of the batch a drop queues
    from .sftp_worker import KIND_COPY, KIND_MOVE
except ImportError:
    from sftp_worker import KIND_COPY, KIND_MOVE

try:  # the cross-session relay of `Send to…` and its declared ceiling
    from . import sftp_send as send
except ImportError:  # flat launch from the project root
    import sftp_send as send


def _facade_attr(name, default=None):
    """An attribute of the SHIPPED facade module at call time — the `modules.sftp_tab` seam.

    A `@staticmethod` of a mixin has no `self` for `host_attr()`, and the facade imports THIS module,
    so the module object is read from `sys.modules` (fully loaded by call time).
    """
    for mod_name in ("modules.sftp_tab", "sftp_tab"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            return getattr(mod, name, default)
    return default


class SftpPaneDndMixin:
    """The drag & drop and the row context menu (mixed into `_SftpPane`)."""
    # ── v1.3.3.2: the file operations (ROADMAP task 1) ───────────────────

    def _on_context_menu(self, pos):
        """The tree's context menu (the seam is `_build_context_menu(item)`)."""
        try:
            item = self.tree.itemAt(pos)
        except RuntimeError:
            return   # the C++ object is already deleted (a close race)
        self.activate()   # the row menu belongs to the pane it was opened in
        menu = self._build_context_menu(item)
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, item=None):
        """New folder / Rename / Delete / Copy remote path (a test seam: the tests
        trigger the QActions directly — `menu.exec()` never runs offscreen).

        Rename/Delete/Copy are enabled only for a REAL row of the current listing
        (never for the ".." row, never for empty space) — a disabled item is the
        hint, the actions themselves stay defensive.
        """
        menu = host_attr(self, "QMenu")(self)
        act_new = menu.addAction(_t("sftp.op.new_folder"))
        act_rename = menu.addAction(_t("sftp.op.rename"))
        act_delete = menu.addAction(_t("sftp.op.delete"))
        act_copy = menu.addAction(_t("sftp.op.copy_path"))
        # v1.7.3 (task 1): `Send to ▸ <session>` — the rows of the sessions open RIGHT NOW.
        sub = self._build_send_menu(item)
        if sub is not None:
            menu.addMenu(sub)
        menu.addSeparator()
        act_refresh = menu.addAction(_t("sftp.refresh"))

        real = (item is not None and item is not self._up_item
                and bool(item.data(0, self.PATH_ROLE)))
        for act in (act_rename, act_delete, act_copy):
            act.setEnabled(bool(real))

        act_new.triggered.connect(lambda: self._op_new_folder())
        act_refresh.triggered.connect(lambda: self._relist(self._current_dir))
        if real:
            act_rename.triggered.connect(lambda: self._op_rename(item))
            act_delete.triggered.connect(lambda: self._op_delete(item))
            act_copy.triggered.connect(lambda: self._op_copy_path(item))
        return menu

    # ── v1.7.3 (task 1): `Send to ▸ <session>` — the cross-session relay ──

    def _build_send_menu(self, item):
        """The `Send to ▸ <session>` submenu of one row (None — an empty space, no row at all).

        The sessions come from the CONTAINER's provider, so this module never learns where a window
        keeps its registry. A row that is not a FILE answers ONE sentence (a directory crosses
        through the two panes, the relay carries files) and a session list that is empty says so
        instead of offering a dead menu — both are DISABLED rows, which is the shipped hint rule.
        """
        if item is None or item is self._up_item or not item.data(0, self.PATH_ROLE):
            return None
        menu = host_attr(self, "QMenu")(_t("sftp.send.menu"), self)
        if item.data(0, self.ISDIR_ROLE):
            menu.addAction(_t("sftp.send.no_file")).setEnabled(False)
            return menu
        targets = self._container.send_targets() if self._container is not None else []
        if not targets:
            menu.addAction(_t("sftp.send.no_targets")).setEnabled(False)
            return menu
        for target in targets:
            label = target.label or target.host or "?"
            act = menu.addAction(f"{label} ({target.directory or '/'})")
            act.triggered.connect(lambda _checked=False, t=target, i=item: self._op_send_to(i, t))
        return menu

    def _op_send_to(self, item, target):
        """Send ONE file row to another session (the size gate, then the container's relay).

        A LOCAL row is refused with ONE sentence: the relay carries a row of a SERVER (its legs
        are the session's shipped download/upload pair), while a file of the OS disk crosses
        through the two panes with F5 (LOCAL_PANE.md §5) — two doors, each saying which one is
        which instead of quietly doing the wrong thing.
        """
        if self.worker is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        if self.source == host_attr(self, "SOURCE_LOCAL"):
            self.message.emit(_t("sftp.local.transfer_unavailable"))
            return
        path = item.data(0, self.PATH_ROLE) if item is not None else ""
        if not path or (item is not None and item.data(0, self.ISDIR_ROLE)):
            self.message.emit(_t("sftp.send.no_file"))
            return
        size = int(item.data(0, self.SIZE_ROLE) or 0)
        # The declared ceiling is checked BEFORE anything is transferred (the ask's own number).
        if not send.size_allowed(size):
            size_text = host_attr(self, "format_size")
            self.message.emit(_t("sftp.send.too_big", name=self.paths.basename(path),
                                 size=size_text(size), limit=size_text(send.MAX_SEND_BYTES)))
            return
        entry = {"path": path, "name": self.paths.basename(path), "size": size,
                 "mtime": int(item.data(0, self.MTIME_ROLE) or 0)}
        if self._container is None:
            return
        self._container.start_send(self, target, entry)

    # ── D&D: files from Explorer (v1.2.8) ────────────────────────────────

    _DRAG_TYPES = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)

    def eventFilter(self, obj, event):
        """Drag events on the pane's children are forwarded to the pane's OWN
        handlers. Returning True = the event is consumed (QTreeWidget does not
        process it "its own way").

        v1.3.3.2: the SOURCE widget of the event is remembered for the drop — the
        directory under the cursor is resolved in the tree's coordinates whatever
        child (viewport, header, button) received the event.

        v1.7rc1: a keyboard FocusIn anywhere inside the pane makes it the ACTIVE pane of
        the container (the event is NOT consumed — the widget keeps the focus).

        v1.7rc3: a KEY of the pane's walk (`Tab`/`Shift+Tab`, `Enter`, `Insert`/`Space`,
        `Backspace`, `Left`) is answered here too, so it fires from the address bar, a button
        or the hint row and not only from the tree. The completer's popup is the ONE exception:
        while it is open `Tab`/`Enter` complete the typed path (the shipped behaviour), so the
        popup's events are left to Qt.
        """
        etype = event.type()
        # `obj is self._container` is "the tab itself" — the shipped production path (with DragOnly
        # the tree's viewport refuses drops, so Qt hands them to the tab), where the point is in the
        # TAB's coordinates and is mapped back to the tree. The pane's OWN viewer counts as this pane
        # even while it is BORROWED by the other one (a re-parented widget is nobody's descendant any
        # more), so a key typed into the open panel still reaches the walk (`AGENTS.md` §4.24).
        mine = (obj is self or obj is self._container or self.isAncestorOf(obj)
                or obj is self.viewer or self.viewer.isAncestorOf(obj))
        # v1.7.5: the SOURCE header line takes no drop — it is a view of the source, not a target,
        # so a drag over it is left to Qt (a drop is resolved in the tree's viewport, §3).
        if etype in self._DRAG_TYPES and obj is getattr(self, "header_label", None):
            return False
        if etype in self._DRAG_TYPES and mine:
            self._drag_source = obj
            try:
                if etype == QEvent.Type.DragEnter:
                    self.dragEnterEvent(event)
                elif etype == QEvent.Type.DragMove:
                    self.dragMoveEvent(event)
                else:  # Drop
                    self.dropEvent(event)
            finally:
                self._drag_source = None
            return True
        if etype == QEvent.Type.FocusIn and mine:
            self.activate()
        # v1.7rc3: the walk of the two-pane view — the tree has its own `keyPressEvent` hook,
        # the pane answers for every OTHER widget it owns (Tab must switch the panes from the
        # address bar or a button as well).
        if etype == QEvent.Type.KeyPress and mine and obj is not self.tree and not self._popup_open():
            if self._on_pane_key(event):
                return True
        return False

    def _popup_open(self) -> bool:
        """True while the address bar's completer popup has the keyboard (v1.7rc3)."""
        try:
            popup = self.path_completer.popup()
            return popup is not None and popup.isVisible()
        except (RuntimeError, AttributeError):
            return False

    @staticmethod
    def local_files(mime_data) -> list:
        """The module function of the same name (the drag payload of a drop)."""
        return _facade_attr("local_files")(mime_data)

    def dragEnterEvent(self, event):
        # v1.7.3: a row of ANOTHER Files pane is a payload of its own (the private mime type) —
        # `local_files()` cannot see it and the drop below is a copy or a move.
        files = host_attr(self, "local_files")(event.mimeData())
        payload = host_attr(self, "pane_payload")(event.mimeData())
        if files or payload:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # Same answer as dragEnter — otherwise Qt will reset the action before Drop.
        files = host_attr(self, "local_files")(event.mimeData())
        payload = host_attr(self, "pane_payload")(event.mimeData())
        if files or payload:
            event.acceptProposedAction()

    def dropEvent(self, event):
        # v1.7.3 (task 3): a row dragged out of a pane and dropped INTO a pane is the v1.7rc2
        # copy (a MOVE with `Shift`) with a PANE as its destination.
        payload = host_attr(self, "pane_payload")(event.mimeData())
        if payload is not None:
            event.acceptProposedAction()
            self._on_pane_drop(payload, event)
            return
        target = self._drop_target_dir(event)
        files = host_attr(self, "local_files")(event.mimeData())
        if files:
            event.acceptProposedAction()
        self._on_drop(files, target)

    @staticmethod
    def _drop_is_move(event) -> bool:
        """Is this drop a MOVE? `Shift`+drop is one (the classic commander reading)."""
        try:
            if event.dropAction() == Qt.DropAction.MoveAction:
                return True
        except (AttributeError, RuntimeError):
            pass   # an exotic event object without the action — the modifier decides
        try:
            return bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        except (AttributeError, RuntimeError):
            return False

    def _on_pane_drop(self, payload: dict, event):
        """A row of a pane dropped into THIS pane: copy, or move with `Shift` (v1.7.3).

        TWO refusals are declared and each answers ONE sentence: the row may come from THIS pane
        (nothing to copy), and it may belong to ANOTHER session — there is no server-to-server
        path, so a file crosses between servers through `Send to…`, never through a drag.

        v1.7.4rc2: the payload DECLARES its source dialect, so the row's name is read with the
        dialect that really produced the path (a local path spells its separators the OS way) and
        the pre-flight listing of a destination that is not on the screen goes to THIS pane's
        provider — a local directory is the OS's business, never the session's.
        """
        if payload.get("pane") == id(self):
            self.message.emit(_t("sftp.cmd.drop_same_pane"))
            return
        if not self.session_key() or payload.get("session") != self.session_key():
            self.message.emit(_t("sftp.cmd.drop_other_session"))
            return
        if self._elevated_drop_refused(payload):
            return   # v1.8: the DRAGGING pane is elevated — the ONE refusal (ELEVATED_PANE.md §5)
        source = str(payload.get("path") or "")
        if not source:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        provider = self.provider
        if provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        items = [(source, host_attr(self, "dialect_for")(payload.get("source")).basename(source),
                  int(payload.get("size") or 0))]
        src = payload.get("source") or host_attr(self, "SOURCE_REMOTE")
        kind = KIND_MOVE if self._drop_is_move(event) else KIND_COPY
        target_dir = self._drop_target_dir(event) or self._current_dir
        if self.paths.same(target_dir, self._current_dir):
            self._queue_transfer_batch(items, kind, target_dir, self._names_in_current_dir(),
                                       self, src)
            return
        # The destination row is not on the screen: LIST it first (the shipped pre-flight rule) so
        # the conflict question is the source's own answer.
        task_id = provider.queue_list(target_dir)
        if task_id is None:
            self._queue_transfer_batch(items, kind, target_dir, set(), self, src)
            return
        self._pending_drops[task_id] = (items, kind, target_dir, src)

    def _item_under(self, event):
        """The listing row under a drag event (None — empty space / outside the tree).

        The event may arrive from any child (the pane's eventFilter forwards it): the
        point is mapped into the viewport's coordinates first, so the row is found
        regardless of who received the event.
        """
        try:
            pos = event.position().toPoint()
        except AttributeError:   # an older event object without position()
            pos = event.pos()
        source = self._drag_source or self
        try:
            if source is not self.tree.viewport():
                pos = self.tree.viewport().mapFrom(source, pos)
            return self.tree.itemAt(pos)
        except (RuntimeError, TypeError):
            return None   # the C++ object is gone / the source is not an ancestor

    def _drop_target_dir(self, event) -> str:
        """v1.3.3.2 (ROADMAP task 4): the directory UNDER THE CURSOR.

        A directory row (including "..") is the target; a file row and empty space
        keep the current directory — the second half of the "drop into a specific
        row" promise quoted in the goal of the version.
        """
        item = self._item_under(event)
        if item is not None and item.data(0, self.ISDIR_ROLE):
            return item.data(0, self.PATH_ROLE) or self._current_dir
        return self._current_dir

    def _on_drop(self, files: list, target_dir: str = ""):
        """Drop result: upload into the directory under the cursor.

        The conflict check must not be a guess, so a target directory that is NOT on
        the screen is LISTED first (a "list" task of the same queue) and the batch is
        queued when the answer arrives — see `_on_list_ready`.

        v1.7.4rc2: the queue is THIS pane's PROVIDER, so a drop of Explorer files on the local
        pane is a LOCAL copy of every file into the directory on the screen, while a drop on a
        remote pane stays the shipped upload (LOCAL_PANE.md §7).
        """
        target = target_dir or self._current_dir
        if not files:
            # No local files in the drag (directories/other data).
            self.message.emit(_t("sftp.drop_no_files"))
            return
        if self._refuse_elevated_write():
            return   # v1.8: a drop WRITES — the elevated pane refuses it (ELEVATED_PANE.md §5)
        provider = self.provider
        if provider is None:
            self.message.emit(_t("sftp.waiting_connection"))
            return
        if self.paths.same(target, self._current_dir):
            # The listing on the screen IS the answer of the source for that
            # directory — the conflict check needs nothing else.
            self._queue_uploads(files, target, self._names_in_current_dir())
        else:
            task_id = provider.queue_list(target)
            if task_id is not None:
                self._pending_batches[task_id] = (target, files)
                return   # the hint + the uploads follow the listing answer
            self._queue_uploads(files, target, set())
        self.message.emit(_t("sftp.drop_queued", count=len(files), dir=target))
