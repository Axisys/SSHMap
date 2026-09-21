"""v0.8.3: Undo/Redo — QUndoCommand classes for map operations.

Undo boundaries: node status changes (v0.7.1), coordinates during project
load, and autogather results (v0.9) do NOT enter the stack. Group
move/resize DO enter the stack (CmdMoveGroup/CmdResizeGroup below;
AUDIT v0.8.3 #6) — as does node movement (CmdMoveNode). Note text
editing — CmdEditTextNote; moving/resizing the StickyNote itself is
outside of undo.

Contract for all commands: the scene is modified ONLY inside redo()/undo() —
QUndoStack.push() calls redo() by itself, so the entry points in MainWindow
do not perform the operation manually; they only assemble the command and push it.

After each application the command invokes win._post_undo_refresh() —
the sidebar/counters/status-check plan get synchronized with the actual
scene state, regardless of whether the change came from the user,
undo, or redo.

LIFO invariant: Qt undoes commands strictly in reverse order, so
removing a node (which captures its arrows) cannot be undone before
the undo of operations on those arrows — references to objects remain valid.
"""
import copy
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoCommand


class _MapCommand(QUndoCommand):
    """Base: holds a reference to the window (for the refresh hook and i18n)."""

    def __init__(self, win, text: str = ""):
        super().__init__(text)
        self._win = win

    def _refresh(self):
        """Synchronize the window UI with the scene state after application."""
        try:
            self._win._post_undo_refresh()
        except Exception:  # noqa: BLE001 — refresh is cosmetic, don't break undo
            pass


# ── MoveNode: node movement (merges drags within a single gesture) ──

class CmdMoveNode(_MapCommand):
    """Moves a single node. Merging: a chain of commands for the same node
    (a mouse gesture produces exactly one command per release, but programmatic
    setPos chains get merged) is collapsed into the first command."""

    MOVE_ID = 1  # id() > 0 enables Qt's mergeWith

    def __init__(self, win, node, old_pos: QPointF, new_pos: QPointF):
        super().__init__(win, "Move node")
        self._node = node
        self._old = QPointF(old_pos)
        self._new = QPointF(new_pos)

    def id(self) -> int:  # noqa: N802 — Qt API
        return self.MOVE_ID

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, CmdMoveNode) or other._node is not self._node:
            return False
        # Absorb the subsequent position — the whole gesture is undone by a single undo
        self._new = QPointF(other._new)
        return True

    def _apply(self, pos: QPointF):
        try:
            if self._node.scene() is not None:
                self._node.setPos(pos)  # itemChange keeps data/arrows/groups in sync
        except RuntimeError:
            pass  # Qt teardown — the item was destroyed, nothing to apply

    def redo(self):
        self._apply(self._new)

    def undo(self):
        self._apply(self._old)


# ── MoveNodes: moving multiple selected nodes (v0.9.3) ──

class CmdMoveNodes(_MapCommand):
    """v0.9.3: moves MULTIPLE selected nodes in a single gesture.

    One group-drag gesture → one undo command (not N separate
    CmdMoveNode instances). moves — a list of (node, old_pos, new_pos);
    nodes are stored by reference, positions as copies of QPointF.
    No merging: a gesture produces exactly one command.
    """

    def __init__(self, win, moves):
        super().__init__(win, "Move servers")
        self._moves = [(node, QPointF(old), QPointF(new)) for node, old, new in moves]

    def _apply(self, use_old: bool):
        for node, old, new in self._moves:
            try:
                if node.scene() is not None:
                    node.setPos(old if use_old else new)
            except RuntimeError:
                pass  # Qt teardown — the item was destroyed

    def redo(self):
        self._apply(False)

    def undo(self):
        self._apply(True)


# ── MoveGroup: group movement (merges drags within a single gesture) ──
# AUDIT v0.8.3 (#6): previously group move/resize/rename only went into the
# dirty marker — Ctrl+Z after moving a group rolled nothing back.

class CmdMoveGroup(_MapCommand):
    """Moves a group (its members follow automatically). Merges a chain of
    incremental moves from a single gesture into the first command
    (the CmdMoveNode pattern)."""

    MOVE_GROUP_ID = 2  # unique id ≠ CmdMoveNode.MOVE_ID

    def __init__(self, win, group, old_pos: QPointF, new_pos: QPointF):
        super().__init__(win, "Move group")
        self._group = group
        self._old = QPointF(old_pos)
        self._new = QPointF(new_pos)

    def id(self) -> int:  # noqa: N802 — Qt API
        return self.MOVE_GROUP_ID

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, CmdMoveGroup) or other._group is not self._group:
            return False
        self._new = QPointF(other._new)
        return True

    def _apply(self, pos: QPointF):
        try:
            grp = self._group
            if grp.scene() is None:
                return
            delta = QPointF(pos.x() - grp.pos().x(), pos.y() - grp.pos().y())
            # _apply_move moves the group AND its members + resync; the
            # itemChange path (_applying_move=False) does the same for
            # programmatic setPos.
            if hasattr(grp, "_apply_move"):
                grp._apply_move(delta)
            else:
                grp.setPos(pos)
        except RuntimeError:
            pass  # Qt teardown — the item was destroyed

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()


# ── ResizeGroup: group resizing ──────────────────────────────────

class CmdResizeGroup(_MapCommand):
    """Resizes a group by a corner. Members are repositioned by set_group_size itself."""

    def __init__(self, win, group, old_size, new_size):
        super().__init__(win, "Resize group")
        self._group = group
        self._old = tuple(old_size)   # (w, h)
        self._new = tuple(new_size)

    def _apply(self, size):
        try:
            if self._group.scene() is not None:
                self._group.set_group_size(size[0], size[1])
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()


# ── ToggleGroupCollapse: folding a group into badges (v1.4.2) ────

class CmdToggleGroupCollapse(_MapCommand):
    """v1.4.2 (ROADMAP task 5): fold a group's members into badges, or unfold them.

    Why this IS an undo step while the v0.8.4 per-node collapse is not: the fold MOVES
    the member cards and re-fits the frame — it is a real geometry change, and a Ctrl+Z
    that skipped it would leave the stack pointing at the wrong step. The GROUP owns the
    two states: `collapse()` snapshots the arrangement and `expand()` restores it, so
    this command only decides WHICH one to apply — and a redo after an undo re-snapshots
    whatever the current arrangement is, which keeps the chain consistent.

    The title is fixed at construction (a QUndoCommand's text is read by the stack/menu);
    a group whose C++ object is gone (a deleted node, a cleared scene) is a silent no-op
    (the `_MapCommand` contract).
    """

    def __init__(self, win, group, collapsed: bool):
        super().__init__(win, "Collapse group" if collapsed else "Expand group")
        self._group = group
        self._collapsed = bool(collapsed)

    def _apply(self, collapsed: bool):
        try:
            grp = self._group
            if grp.scene() is None:
                return
            grp.set_collapsed(bool(collapsed))
        except RuntimeError:
            pass  # Qt teardown — the item was destroyed, nothing to apply

    def redo(self):
        self._apply(self._collapsed)
        self._refresh()

    def undo(self):
        self._apply(not self._collapsed)
        self._refresh()


# ── EditGroupName: group renaming ────────────────────────────────
class CmdEditGroupName(_MapCommand):
    """Edits the group title (double-click / context menu)."""

    def __init__(self, win, group, old_name: str, new_name: str):
        super().__init__(win, "Rename group")
        self._group = group
        self._old = old_name
        self._new = new_name

    def _apply(self, name: str):
        try:
            if self._group.scene() is not None:
                self._group.set_title(name)
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()


# ── AddRemoveNode: server create/remove (with its arrows) ────────

class CmdAddRemoveNode(_MapCommand):
    """Adds (mode='add') or removes (mode='remove') a node.

    On removal all incoming/outgoing arrows are captured — undo
    restores the node together with them. Node data is stored as a single object:
    a repeated redo after undo creates the node with the same id, which keeps
    references from other commands (arrows created after the addition) valid.
    """

    def __init__(self, win, scene, data, mode: str = "add",
                 arrows: Optional[List[Tuple]] = None):
        super().__init__(win, "Add server" if mode == "add" else "Delete server")
        self._scene = scene
        self._data = data          # single ServerData (id is stable across undo/redo)
        self._mode = mode
        # v1.2.6: 5-tuples (source_id, target_id, label, ctype, bidirectional);
        # pre-v1.2.6 4-tuples are supported (restore reads bidir as False).
        self._arrows = list(arrows or [])
        # v0.9.4-fix (orphaned passwords): when a node is removed its password is
        # deleted from the keyring; so that Ctrl+Z can bring it back, we read it
        # into memory in advance.
        # v1.1.2RC1 (bonus-N11): the stash is also needed in "add" mode — duplicating
        # a node copies the keyring password under a new id BEFORE pushing the
        # command; undo ("add") deletes the record, and redo must RESTORE it
        # (previously a copy left after Ctrl+Z→Ctrl+Y remained without a password).
        # For a fresh addition there is no keyring record yet — load_password
        # returns None, the stash is empty, restore is a no-op.
        self._stashed_password: Optional[str] = None
        try:
            from services.credential_manager import get_credential_manager
            self._stashed_password = get_credential_manager().load_password(data.id)
        except Exception:
            self._stashed_password = None

    def _delete_keyring_password(self):
        try:
            from services.credential_manager import get_credential_manager
            get_credential_manager().delete_password(self._data.id)
        except Exception:
            pass

    def _restore_keyring_password(self):
        if self._stashed_password:
            try:
                from services.credential_manager import get_credential_manager
                get_credential_manager().save_password(self._data.id, self._stashed_password)
            except Exception:
                pass

    def redo(self):
        if self._mode == "add":
            # v1.4.4 (ROADMAP task 3): the appearing node plays the 200 ms scale-in
            # (ui/motion.py — the item's OWN setScale/setOpacity, never an opacity effect).
            self._scene.add_server(self._data, animate=True)
            # v1.1.2RC1 (bonus-N11): restore the keyring password stashed when the
            # command was created (duplication scenario: undo deleted the record —
            # redo restores it).
            self._restore_keyring_password()
        else:
            self._scene.remove_server(self._data.id)
            self._delete_keyring_password()
        self._refresh()

    def undo(self):
        if self._mode == "add":
            self._scene.remove_server(self._data.id)
            self._delete_keyring_password()
        else:
            self._scene.add_server(self._data)
            self._restore_keyring_password()
            for rec in self._arrows:
                # v1.2.6: stash — 5-tuples (src, tgt, label, ctype, bidir); old
                # 4-tuples (calls prior to v1.2.6) are read as one-directional.
                src, tgt, lbl, ctype = rec[0], rec[1], rec[2], rec[3]
                bidir = bool(rec[4]) if len(rec) > 4 else False
                if (self._scene.has_node(src) and self._scene.has_node(tgt)
                        and not self._scene.has_connection(src, tgt)):
                    self._scene.add_connection(src, tgt, lbl, ctype, bidirectional=bidir)
        self._refresh()


# ── AddRemoveNodeBatch: a batch of nodes in one command (v0.9.5.5, import from TXT) ──

class CmdAddRemoveNodeBatch(_MapCommand):
    """Adds/removes MULTIPLE nodes as a single undo/redo step.

    Used by bulk server import (services.host_importer):
    Ctrl+Z rolls back the entire imported batch at once.
    """

    def __init__(self, win, scene, data_list, mode: str = "add"):
        super().__init__(win, f"Import {len(data_list)} servers" if mode == "add"
                         else f"Delete {len(data_list)} servers")
        self._scene = scene
        self._data_list = list(data_list)
        self._mode = mode
        # v0.9.4-fix style: on remove, stash keyring passwords in advance for undo
        self._stashed_passwords: List[Tuple[str, Optional[str]]] = []
        if mode == "remove":
            try:
                from services.credential_manager import get_credential_manager
                cm = get_credential_manager()
                for d in self._data_list:
                    self._stashed_passwords.append((d.id, cm.load_password(d.id)))
            except Exception:
                pass

    def _delete_passwords(self):
        try:
            from services.credential_manager import get_credential_manager
            cm = get_credential_manager()
            for d in self._data_list:
                cm.delete_password(d.id)
        except Exception:
            pass

    def _restore_passwords(self):
        try:
            from services.credential_manager import get_credential_manager
            cm = get_credential_manager()
            for sid, pwd in self._stashed_passwords:
                if pwd:
                    cm.save_password(sid, pwd)
        except Exception:
            pass

    def redo(self):
        for d in self._data_list:
            if self._mode == "add":
                if not self._scene.has_node(d.id):
                    # v1.4.4 (ROADMAP task 3): a bulk import is a row of appearing cards —
                    # every node of the batch plays the same 200 ms scale-in as a single add.
                    self._scene.add_server(d, animate=True)
            else:
                if self._scene.has_node(d.id):
                    self._scene.remove_server(d.id)
        if self._mode == "add":
            # Imported nodes have no passwords; delete is a no-op, called for symmetry
            self._delete_passwords()
        self._refresh()

    def undo(self):
        for d in self._data_list:
            if self._mode == "add":
                if self._scene.has_node(d.id):
                    self._scene.remove_server(d.id)
            else:
                if not self._scene.has_node(d.id):
                    self._scene.add_server(d)
        if self._mode == "add":
            self._delete_passwords()
        else:
            self._restore_passwords()
        self._refresh()


# ── AddRemoveConnection: connection create/remove ────────────────

class CmdAddRemoveConnection(_MapCommand):
    def __init__(self, win, scene, source_id: str, target_id: str,
                 label: str, ctype: str, mode: str = "add",
                 bidirectional: bool = False):
        # v1.2.6: bidirectional is at the tail of the signature (after mode)
        # so that old positional calls (mode as the 7th argument) don't break.
        super().__init__(win, "Add connection" if mode == "add" else "Delete connection")
        self._scene = scene
        self._src = source_id
        self._tgt = target_id
        self._label = label
        self._ctype = ctype
        self._mode = mode
        self._bidir = bool(bidirectional)

    def _find_arrow(self):
        for a in self._scene.arrows():
            if (a.source.data.id == self._src and a.target.data.id == self._tgt):
                return a
        return None

    def redo(self):
        if self._mode == "add":
            self._scene.add_connection(self._src, self._tgt, self._label, self._ctype,
                                       bidirectional=self._bidir)
        else:
            arrow = self._find_arrow()
            if arrow is not None:
                self._scene.remove_connection(arrow)
        self._refresh()

    def undo(self):
        if self._mode == "add":
            arrow = self._find_arrow()
            if arrow is not None:
                self._scene.remove_connection(arrow)
        else:
            self._scene.add_connection(self._src, self._tgt, self._label, self._ctype,
                                       bidirectional=self._bidir)
        self._refresh()


# ── ConnectSelected: connections between all selected nodes (v0.9.3) ──

class CmdConnectSelected(_MapCommand):
    """v0.9.3: creates a complete connection graph between the selected nodes in
    one operation ((source_id, target_id) pairs are already filtered by the
    entry point). Undo removes all created arrows, redo restores them."""

    def __init__(self, win, scene, pairs):
        super().__init__(win, "Connect servers")
        self._scene = scene
        self._pairs = list(pairs)

    def _apply(self, present: bool):
        for src, tgt in self._pairs:
            has = self._scene.has_connection(src, tgt)
            if present and not has:
                self._scene.add_connection(src, tgt)
            elif not present and has:
                for a in self._scene.arrows():
                    if a.source.data.id == src and a.target.data.id == tgt:
                        self._scene.remove_connection(a)
                        break

    def redo(self):
        self._apply(True)
        self._refresh()

    def undo(self):
        self._apply(False)
        self._refresh()


# ── AddRemoveNote: note create/remove ────────────────────────────

class CmdAddRemoveNote(_MapCommand):
    def __init__(self, win, scene, raw: dict, mode: str = "add"):
        super().__init__(win, "Add note" if mode == "add" else "Delete note")
        self._scene = scene
        self._raw = dict(raw)   # {text,x,y,width,height[,id]}
        self._mode = mode
        self._note_id = raw.get("id")

    def redo(self):
        # Idempotency: the window already created the note before push — don't duplicate
        if self._mode == "add" and self._scene.get_note_by_id(self._note_id) is not None:
            self._refresh()
            return
        if self._mode == "add":
            note = self._scene.add_note(
                text=str(self._raw.get("text") or ""),
                x=float(self._raw.get("x") or 0.0),
                y=float(self._raw.get("y") or 0.0),
                width=float(self._raw.get("width") or 240.0),
                height=float(self._raw.get("height") or 160.0),
                note_id=self._note_id,
            )
            self._note_id = note.note_id  # id may have been generated on the first redo
            try:
                self._win._attach_note(note)  # signals + committed text
            except Exception:  # noqa: BLE001
                pass
        else:
            self._scene.remove_note(self._note_id)
        self._refresh()

    def undo(self):
        if self._mode == "add":
            self._scene.remove_note(self._note_id)
        else:
            note = self._scene.add_note(
                text=str(self._raw.get("text") or ""),
                x=float(self._raw.get("x") or 0.0),
                y=float(self._raw.get("y") or 0.0),
                width=float(self._raw.get("width") or 240.0),
                height=float(self._raw.get("height") or 160.0),
                note_id=self._note_id,
            )
            self._note_id = note.note_id
            try:
                self._win._attach_note(note)
            except Exception:  # noqa: BLE001
                pass
        self._refresh()


# ── EditTextNote: note text editing (debounce on the window side) ──

class CmdEditTextNote(_MapCommand):
    def __init__(self, win, note, old_text: str, new_text: str):
        super().__init__(win, "Edit note")
        self._note = note
        self._note_id = getattr(note, "note_id", None)
        self._old = old_text
        self._new = new_text

    def _resolve_note(self):
        """v1.0-fix (audit #8): the original C++ object may have been destroyed — in the
        sequence "create → edit text → delete", undoing the delete restores a NEW note
        with the same id, while self._note points at the old dead object. In that case
        we look up the current note by id — otherwise undo/redo were silently no-op
        (RuntimeError was swallowed) and the text edit was lost."""
        try:
            if self._note.scene() is not None:
                return self._note
        except RuntimeError:
            pass  # C++ object already deleted
        scene = getattr(self._win, "scene", None)
        if scene is None or not self._note_id:
            return None
        try:
            return scene.get_note_by_id(self._note_id)
        except Exception:  # noqa: BLE001 — the scene itself may be destroyed
            return None

    def _apply(self, value: str):
        note = self._resolve_note()
        if note is None:
            return  # no live note with this id — nothing to apply
        try:
            committed = getattr(self._win, "_note_committed", None)
            if committed is not None and self._note_id:
                committed[self._note_id] = value
            if note.text() == value:
                # v1.2.4-fix (tester feedback): the text already matches — a typical
                # debounce commit while typing is active (QUndoStack.push calls
                # redo by itself). set_text → setPlainText resets the document and
                # moves the cursor to the START of the note, breaking editing;
                # leave the widget alone.
                return
            note.set_text(value)
        except RuntimeError:
            pass  # destroyed between _resolve_note and set_text (WA_DeleteOnClose race)

    def redo(self):
        self._apply(self._new)

    def undo(self):
        self._apply(self._old)


# ── v1.2.4: AttachNote / DetachNote — pinning a note to a server ──

class CmdAttachNote(_MapCommand):
    """Attach/detach a note from a node in one command (mode="attach"|"detach").

    attach: redo — server_id + position at the node corner + line; undo — detach +
            return to old_pos (the note's position BEFORE attaching).
    detach: redo — unpin from the node (the note stays in place); undo — attach again
            with keep_position=True (v1.2.4-fix: exact inverse action — the note
            doesn't jump to the corner but returns where it was detached from;
            offset is recalculated).
    No merging (id() not overridden → 0): each attach/detach is a separate
    undo step; the LIFO chain "detach + server removal" rolls back completely.
    """

    def __init__(self, win, note, node_id: str, mode: str = "attach"):
        super().__init__(win, "Attach note" if mode == "attach" else "Detach note")
        self._note = note
        self._note_id = getattr(note, "note_id", None)
        self._node_id = node_id
        self._mode = mode
        try:
            self._old_pos = QPointF(note.pos())  # position BEFORE attach (for undo)
        except RuntimeError:
            self._old_pos = QPointF(0.0, 0.0)

    def _resolve_note(self):
        """Audit #8 pattern (CmdEditTextNote): the C++ object may be destroyed — look up by id."""
        try:
            if self._note.scene() is not None:
                return self._note
        except RuntimeError:
            pass  # C++ object already deleted
        scene = getattr(self._win, "scene", None)
        if scene is None or not self._note_id:
            return None
        try:
            return scene.get_note_by_id(self._note_id)
        except Exception:  # noqa: BLE001 — the scene itself may be destroyed
            return None

    def _scene(self):
        return getattr(self._win, "scene", None)

    def redo(self):
        note, scene = self._resolve_note(), self._scene()
        if note is None or scene is None:
            return
        try:
            if self._mode == "attach":
                node = scene.get_node(self._node_id)
                if node is not None and getattr(note, "server_id", None) != self._node_id:
                    scene.attach_note_to_node(note, node)
            elif getattr(note, "server_id", None):
                scene.detach_note_from_node(note)
        except RuntimeError:
            pass  # Qt teardown — the item was destroyed
        self._refresh()

    def undo(self):
        note, scene = self._resolve_note(), self._scene()
        if note is None or scene is None:
            return
        try:
            if self._mode == "attach":
                if getattr(note, "server_id", None):
                    scene.detach_note_from_node(note)
                note.prepareGeometryChange()
                note.setPos(self._old_pos)
            else:
                node = scene.get_node(self._node_id)
                if node is not None and getattr(note, "server_id", None) != self._node_id:
                    # v1.2.4-fix: detach didn't move the note → undo returns it to the
                    # same place (keep_position), not to the node corner
                    scene.attach_note_to_node(note, node, keep_position=True)
        except RuntimeError:
            pass  # Qt teardown — the item was destroyed
        self._refresh()


# ── EditConnection: connection label/type editing ────────────────

class CmdEditConnection(_MapCommand):
    def __init__(self, win, arrow, old_label: str, old_type: str, old_bidir: bool,
                 new_label: str, new_type: str, new_bidir: bool):
        # v1.2.6: connection state is a triple (label, type, bidirectional)
        # instead of a pair; argument order for the old first-three /
        # last-two fields is unchanged.
        super().__init__(win, "Edit connection")
        self._arrow = arrow
        self._old = (old_label, old_type, bool(old_bidir))
        self._new = (new_label, new_type, bool(new_bidir))

    def _apply(self, label: str, ctype: str, bidir: bool):
        try:
            if self._arrow.scene() is None:
                return
            if label != self._arrow.label_text:
                self._arrow.set_label(label)
            if ctype != self._arrow.connection_type:
                self._arrow.set_type(ctype)
            # v1.2.6: bidirectional mode (set_bidirectional is idempotent, but
            # we compare explicitly — same pattern as set_type/set_label above)
            if bidir != bool(getattr(self._arrow, "bidirectional", False)):
                self._arrow.set_bidirectional(bidir)
        except RuntimeError:
            pass

    def redo(self):
        self._apply(*self._new)

    def undo(self):
        self._apply(*self._old)


# ── EditNodeData: server data editing via the properties dialog ──

class CmdEditNodeData(_MapCommand):
    def __init__(self, win, node, old_data, new_data):
        super().__init__(win, "Edit server")
        self._node = node
        self._old = old_data
        self._new = new_data

    def _apply(self, data):
        try:
            if self._node.scene() is None:
                return
            self._node.data = data
            self._node.update_appearance()
            # v0.9.4: tags may have changed — the bar is rebuilt (update_appearance
            # only touches it on a geometry change)
            self._node.refresh_tags()
            # host/port may have changed — the status is no longer valid (dialog pattern)
            self._node.reset_status()
        except RuntimeError:
            pass

    def redo(self):
        self._apply(self._new)
        self._refresh()

    def undo(self):
        self._apply(self._old)
        self._refresh()
