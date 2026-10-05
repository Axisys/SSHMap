"""`SceneCommandMixin` — the scene mutations that go through an UNDO COMMAND (AGENTS.md §4.1, §4.2).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: the notes family (their signal wiring and the ONE pending-text commit), the group family (the
gesture commits, the wiring and the FOLD), the background family (the same wiring, the two gestures and the
image of the map) and the group creation/rename/removal. Every mutation is pushed through
`self._push_command()` and the scene is touched only inside a command's `redo()`/`undo()`; a VIEW state
(the per-node collapse) is deliberately NOT here. Mechanism — `DOCUMENTATION.md` §23."""
from PySide6.QtWidgets import QFileDialog, QMessageBox

try:  # v0.8.1: node grouping (the frame's declared default size)
    from ..graphics.node_group import NodeGroup
except ImportError:
    from graphics.node_group import NodeGroup

try:  # v0.8.1: the scene-point predicate — it belongs to the node-ops cluster (the `_add_server` fix)
    from .main_window_node_ops import _is_scene_point
except ImportError:
    from main_window_node_ops import _is_scene_point


class SceneCommandMixin:
    """The notes, the groups and the background: the scene mutations that enter the undo stack."""

    def _connect_note_signals(self, note):
        """Wire the note's signals to the dirty marker and undo (v0.8.3: text editing)."""
        try:
            note.textEdited.connect(lambda *_a: self._on_note_text_edited(note))
            note.moved.connect(lambda *_a: self._mark_dirty())
            # v1.2.4: attachment to a server (drag onto a node / drag of an attached one)
            note.attachRequested.connect(
                lambda node, n=note: self._attach_note_to_node(n, node))
            note.detachRequested.connect(
                lambda *_a, n=note: self._detach_note(n))
        except Exception:
            pass  # re-wiring the same note — not critical

    def _on_note_text_edited(self, note):
        """v0.8.3: a text edit — restart the debounce; on silence -> an undo command."""
        self._mark_dirty()
        try:
            committed = self._note_committed.get(note.note_id)
            if committed is not None and note.text() == committed:
                self._note_edit_pending = None
                return  # the text matches the committed one (undo/redo restored it) — no command needed
        except RuntimeError:
            return
        if not self._note_edit_pending or self._note_edit_pending[0] is not note:
            # a new edit session of this note — capture the starting text
            try:
                start = self._note_committed.get(note.note_id, note.text())
            except RuntimeError:
                return
            self._note_edit_pending = (note, start)
        self._note_edit_timer.start()

    def _add_note_at(self, scene_pos=None) -> None:
        """Create a note at a scene point (center — under the cursor)."""
        if scene_pos is not None:
            x = float(scene_pos.x()) - 120.0   # ~half of the default width
            y = float(scene_pos.y()) - 80.0    # ~half of the default height
        else:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            x, y = float(center.x()) - 120.0, float(center.y()) - 80.0
        note = self.scene.add_note(x=x, y=y)
        # v0.8.3: creating a note — an undo command; the note itself is already added above
        # (add_note returned the object), but for undo it must be removed/restored by a command.
        from modules.undo_commands import CmdAddRemoveNote
        raw = {"id": note.note_id, "text": "", "x": float(note.pos().x()),
               "y": float(note.pos().y()),
               "width": float(note.rect().width()), "height": float(note.rect().height())}
        self._note_committed[note.note_id] = ""
        self._push_command(CmdAddRemoveNote(self, self.scene, raw, "add"))
        self._attach_note(note)
        if self.log:
            self.log.info("Note added", extra={"id": note.note_id})
        self.statusBar().showMessage(self.t("status.note_added"))
        self._mark_dirty()

    def _remove_note(self, note) -> bool:
        """Remove a note (a light object — no confirmation dialog)."""
        note_id = getattr(note, "note_id", None)
        if not note_id or self.scene.get_note_by_id(note_id) is None:
            return False
        from modules.undo_commands import CmdAddRemoveNote
        try:
            raw = note.to_dict()
        except RuntimeError:
            return False
        self._note_edit_pending = None  # the uncommitted edit goes away with the removal command
        self._push_command(CmdAddRemoveNote(self, self.scene, raw, "remove"))
        if self.log:
            self.log.info("Note deleted", extra={"id": note_id})
        self.statusBar().showMessage(self.t("status.note_deleted"))
        self._mark_dirty()
        return True

    def _attach_note_to_node(self, note, node) -> bool:
        """v1.2.4: attach a note to a node (menu / drag). An undo command."""
        if note is None or node is None:
            return False
        try:
            if note.scene() is None or getattr(note, "server_id", None) == node.data.id:
                return False  # already attached to this same node — a no-op
        except RuntimeError:
            return False
        from modules.undo_commands import CmdAttachNote
        self._push_command(CmdAttachNote(self, note, node.data.id, "attach"))
        if self.log:
            self.log.info("Note attached", extra={"note": note.note_id, "server": node.data.id})
        self.statusBar().showMessage(self.t("status.note_attached", alias=node.data.alias))
        self._mark_dirty()
        return True

    def _detach_note(self, note) -> bool:
        """v1.2.4: detach a note (menu / drag / server removal). An undo command."""
        sid = getattr(note, "server_id", None) if note is not None else None
        if not sid:
            return False
        from modules.undo_commands import CmdAttachNote
        self._push_command(CmdAttachNote(self, note, sid, "detach"))
        if self.log:
            self.log.info("Note detached", extra={"note": getattr(note, "note_id", None)})
        self.statusBar().showMessage(self.t("status.note_detached"))
        self._mark_dirty()
        return True

    def _commit_group_move(self, group, old_pos, new_pos):
        """v0.8.3-audit (#6): a group-move gesture finished -> CmdMoveGroup."""
        from modules.undo_commands import CmdMoveGroup
        self._push_command(CmdMoveGroup(self, group, old_pos, new_pos))
        self._mark_dirty()

    def _commit_group_resize(self, group, w0, h0, w1, h1):
        """v0.8.3-audit (#6): a group resize finished -> CmdResizeGroup."""
        from modules.undo_commands import CmdResizeGroup
        self._push_command(CmdResizeGroup(self, group, (w0, h0), (w1, h1)))
        self._mark_dirty()

    def _connect_group_signals(self, group):
        """Wire the group's signals: the dirty marker + undo commands
        (v0.8.3-audit #6: move/resize/rename enter the stack);
        renameRequested — to the rename dialog; v1.4.2: collapseRequested (the fold
        chevron) and collapsedChanged (the fold is persisted → the dirty marker)."""
        try:
            for sig in (group.moved, group.resized, group.titleChanged,
                        group.membershipChanged, group.collapsedChanged):
                sig.connect(lambda *_a: self._mark_dirty())
            # Undo commits of finished gestures (the node_drag_committed pattern)
            group.moveCommitted.connect(
                lambda op, np, g=group: self._commit_group_move(g, op, np))
            group.resizeCommitted.connect(
                lambda w0, h0, w1, h1, g=group: self._commit_group_resize(
                    g, w0, h0, w1, h1))
            # Double click on the title -> QInputDialog (the g closure — the source group)
            group.renameRequested.connect(
                lambda *_a, g=group: self._rename_group(g))
            # v1.4.2 (ROADMAP task 5): the fold chevron asks; the window pushes the
            # command (the group must not mutate itself — the renameRequested contract).
            group.collapseRequested.connect(
                lambda *_a, g=group: self._toggle_group_collapsed(g))
        except Exception:  # noqa: BLE001 — re-wiring is not critical
            pass

    def _toggle_group_collapsed(self, group) -> bool:
        """Fold or unfold a group as ONE undo step (the chevron / the context menu).

        The command redoes the fold itself (`_push_command` → `QUndoStack.push` →
        `redo()`), so nothing is mutated here — the v0.8.3 undo discipline.
        """
        if group is None:
            return False
        try:
            target = not group.is_collapsed()
        except (AttributeError, RuntimeError):
            return False
        from modules.undo_commands import CmdToggleGroupCollapse
        self._push_command(CmdToggleGroupCollapse(self, group, target))
        self._mark_dirty()
        return True

    def _connect_background_signals(self, bg):
        """Wire the background's signals: the dirty marker + the undo commands (v1.6, task 4).

        The incremental `moved`/`resized` signals keep the project dirty during the
        gesture; the COMPLETED `moveCommitted`/`resizeCommitted` ones push the ONE command
        of the gesture (the group's own wiring, `_connect_group_signals`). Before v1.6 the
        background geometry was the last mouse-driven object outside the undo stack.
        """
        try:
            bg.moved.connect(lambda *_a: self._mark_dirty())
            bg.resized.connect(lambda *_a: self._mark_dirty())
            bg.moveCommitted.connect(
                lambda op, np, b=bg: self._commit_background_move(b, op, np))
            bg.resizeCommitted.connect(
                lambda w0, h0, w1, h1, b=bg: self._commit_background_resize(b, w0, h0, w1, h1))
        except Exception:  # noqa: BLE001
            pass

    def _commit_background_move(self, background, old_pos, new_pos):
        """v1.6 (ROADMAP task 4): a background-move gesture finished -> CmdMoveBackground."""
        from modules.undo_commands import CmdMoveBackground
        self._push_command(CmdMoveBackground(self, background, old_pos, new_pos))
        self._mark_dirty()

    def _commit_background_resize(self, background, w0, h0, w1, h1):
        """v1.6 (ROADMAP task 4): a background resize finished -> CmdResizeBackground."""
        from modules.undo_commands import CmdResizeBackground
        self._push_command(CmdResizeBackground(self, background, (w0, h0), (w1, h1)))
        self._mark_dirty()

    def _set_background_image(self):
        """Choose and set the map background image (v0.9.1 #2/#3)."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("view.set_background"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        try:
            bg = self.scene.set_background_image(path)
        except Exception as e:  # noqa: BLE001 — a corrupt/unreadable image
            QMessageBox.critical(
                self, self.t("msg.error_title"),
                self.t("msg.background_failed", error=str(e)))
            return
        # By default the background is placed in the map's visible area
        try:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            w, h = bg.size()
            bg.setPos(center.x() - w / 2, center.y() - h / 2)
        except Exception:  # noqa: BLE001 — the view is unavailable (headless) — keep (0,0)
            pass
        self._connect_background_signals(bg)
        self._mark_dirty()
        self.statusBar().showMessage(self.t("status.background_set"))
        if self.log:
            self.log.info("Background image set", extra={"file": path})

    def _remove_background_image(self):
        """Remove the map background image (v0.9.1)."""
        if self.scene.background() is None:
            return
        self.scene.remove_background()
        self._mark_dirty()
        self.statusBar().showMessage(self.t("status.background_removed"))

    def _add_group_at(self, at_scene_pos=None) -> None:
        """Create a group (frame + title), centering it under the click point.

        `at_scene_pos` is optional: QAction.triggered sends a bool
        `checked` as the first argument — the position is accepted only if it really is
        a scene point (the same fix as on _add_server; regression_v081 #1). Nodes already
        under the frame become members automatically (MapScene.resync_group_members).
        """
        try:
            if _is_scene_point(at_scene_pos):
                center = at_scene_pos
            else:
                center = self.view.mapToScene(self.view.viewport().rect().center())

            base_name = self.t("group.default_name")
            used = {g.name for g in self.scene.groups()}
            name, n = base_name, 2
            while name in used:  # do not repeat existing group names
                name = f"{base_name} {n}"
                n += 1

            grp = self.scene.add_group(
                name=name,
                x=float(center.x()) - NodeGroup.DEFAULT_W / 2,
                y=float(center.y()) - NodeGroup.DEFAULT_H / 2)
            self._connect_group_signals(grp)
            if self.log:
                self.log.info("Group added", extra={"id": grp.group_id, "group_name": name})
            self.statusBar().showMessage(self.t("status.group_added"))
            self._mark_dirty()
        except Exception as e:
            if self.log:
                self.log.exception("Error adding group")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.add_failed", error=str(e)))

    def _rename_group(self, group) -> None:
        """Rename a group (a double click on the title / the context menu)."""
        if group is None:
            return
        try:
            from PySide6.QtWidgets import QInputDialog, QLineEdit
            text, ok = QInputDialog.getText(
                self,
                self.t("dialog.rename_group"),
                f"{self.t('group.name_label')} ",
                QLineEdit.Normal,
                group.name)
            if ok and str(text).strip():
                new_name = str(text).strip()
                if new_name != group.name:
                    # v0.8.3-audit (#6): renaming — via an undo command
                    from modules.undo_commands import CmdEditGroupName
                    self._push_command(
                        CmdEditGroupName(self, group, group.name, new_name))
                    self._mark_dirty()
                self.statusBar().showMessage(self.t("status.group_renamed"))
        except Exception:
            if self.log:
                self.log.exception(f"Error renaming group {group.name}")

    def _remove_group(self, group) -> bool:
        """Remove a group. Member servers stay on the map at the same positions —
        a group is a labeled container (a light object, no confirmation dialog)."""
        gid = getattr(group, "group_id", None)
        if not gid or self.scene.get_group_by_id(gid) is None:
            return False
        name = group.name
        self.scene.remove_group(group)
        if self.log:
            self.log.info("Group deleted", extra={"id": gid, "group_name": name})
        self.statusBar().showMessage(self.t("status.group_deleted"))
        self._mark_dirty()
        return True
