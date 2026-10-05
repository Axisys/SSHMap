# -*- coding: utf-8 -*-
"""The mc/far WALK of a Files pane and its pane-scoped keys (`_SftpPane` wave 1).

`SftpPaneWalkMixin` holds the key map of ONE pane: `F3`-`F8` as `WidgetWithChildrenShortcut`
`QAction`s OWNED by the pane (so the terminal canvas keeps its own claim on the F-keys) and the
FOCUS walk (`Tab`, `Enter`, `Insert`/`Space`, `Backspace`, `Left`) read by ONE decision point,
`_on_pane_key()`. The pane is the keyboard domain, never a second registry entry (`AGENTS.md`
§4.9); the state the walk reads (`_pane_actions`, `_up_item`, `_secondary`) is built by the
facade's `__init__`, and the container's hooks (`focus_other_pane`, `close_preview`,
`preview_in_other_pane`) are duck-typed.

Contract — `SFTP_PANES.md` §3, §3a, §4a; mechanism — `DOCUMENTATION.md` §59-§63.
"""
from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QTreeWidgetItem

try:
    from i18n import t as _t
except Exception:  # noqa: BLE001 — import outside the project tree (flat run)
    def _t(key, **kwargs):  # type: ignore
        return key

try:
    from .sftp_worker import KIND_COPY, KIND_MOVE
except ImportError:
    from sftp_worker import KIND_COPY, KIND_MOVE

#: The pane-scoped key map (SFTP_PANES.md "The key map"). ONE `QAction` per row, owned
#: by the PANE with `Qt.WidgetWithChildrenShortcut`: the key fires while the keyboard is
#: inside THAT pane and nowhere else, so the terminal canvas keeps its own claim on the
#: F-keys and the window's action registry stays the home of the GLOBAL actions (§4.9).
#: `F4` is deliberately absent — the application has no remote editing at all.
PANE_SHORTCUTS = (
    ("F3", "_cmd_view"),
    ("F5", "_cmd_copy"),
    ("F6", "_cmd_move_rename"),
    ("F7", "_cmd_mkdir"),
    ("F8", "_cmd_delete"),
)

#: The ROW the SECOND pane shows where the first one keeps its buttons. In the two-pane view the
#: shipped button row belongs to the FIRST pane (the mc/far look: the commander has ONE button row and
#: the panes are nothing but listings), so the right pane spends that line on the key HINTS of the keys
#: it really answers — the classic commander's bottom line. The pairs travel with `PANE_SHORTCUTS` (the
#: same keys, in the same order) and the two that are not F-keys close the row. A tuple, never a table.
PANE_HINTS = (
    ("F3", "sftp.hint.view"),
    ("F5", "sftp.hint.copy"),
    ("F6", "sftp.hint.move"),
    ("F7", "sftp.hint.mkdir"),
    ("F8", "sftp.hint.delete"),
    ("Tab", "sftp.cmd.switch_pane"),
    ("Ins", "sftp.hint.mark"),
    ("Enter", "sftp.hint.open"),
)

#: The hint row's own layout (v1.7rc3): the separator between two entries and the elide
#: mode of the label — the row is ONE line and never grows with the pane's width or with
#: the number of entries (a wrapped second line would move the listing under the cursor).
HINT_SEPARATOR = "  ·  "


class SftpPaneWalkMixin:
    """The pane-scoped keys and the mc/far walk of ONE Files pane (mixed into `_SftpPane`)."""

    def _build_pane_shortcuts(self):
        """The pane-scoped key map: ONE `WidgetWithChildrenShortcut` action per row.

        The context is what keeps the contract: the shortcut fires while the keyboard is
        inside THIS pane, so `F5` typed into the terminal canvas never reaches the pane
        and the canvas keeps sending it to the shell (§4.3).
        """
        for seq, slot_name in PANE_SHORTCUTS:
            slot = getattr(self, slot_name, None)
            if not callable(slot):
                continue
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            act.triggered.connect(slot)
            self.addAction(act)
            self._pane_actions.append((seq, act))

    def pane_shortcut(self, seq: str):
        """The QAction of a pane-scoped key (None — the key is not part of the map)."""
        for key, act in self._pane_actions:
            if key == seq:
                return act
        return None

    def set_pane_keys_enabled(self, on: bool):
        """Arm/disarm the pane-scoped keys of THIS pane (v1.7). Never raises.

        A pane CARRYING a borrowed panel is a PANEL and its own listing is off the screen
        (`present_viewer_in()` hides the tree), so its `F3`-`F8` would act on rows nobody can see —
        the keys are disarmed for as long as the panel is there and re-armed with the listing.
        """
        for _seq, act in self._pane_actions:
            try:
                act.setEnabled(bool(on))
            except RuntimeError:
                continue   # Qt teardown — the action's pane is already gone

    # ── v1.7rc3: the SECOND pane — the button row that moves out, the hints that move in ──

    @property
    def secondary(self) -> bool:
        """True — this pane is the RIGHT pane of the two-pane view. Set by the CONTAINER."""
        return bool(self.__dict__.get("_secondary", False))

    @secondary.setter
    def secondary(self, on):
        self._secondary = bool(on)
        self._sync_secondary_ui()

    def hint_text(self) -> str:
        """The key hints of this pane as ONE line (the commander's bottom line).

        Built from `PANE_HINTS` — the SAME keys the pane really binds (`PANE_SHORTCUTS`) plus
        the three that are not `QAction`s (the pane toggle, the mark key and the open key) —
        so the row can never advertise a key the pane does not answer, and a translation is
        read at call time (a language switch re-texts through `retranslate()`).
        """
        parts = []
        for key, label in PANE_HINTS:
            try:
                text = _t(label)
            except Exception:  # noqa: BLE001 — a build without i18n keeps the key itself
                text = label
            parts.append(f"{key} {text}")
        return HINT_SEPARATOR.join(parts)

    def _sync_secondary_ui(self):
        """Show the button row OR the hints row according to this pane's role. Never raises.

        The two rows share ONE line of the layout: the pane that keeps the buttons hides the
        hints, and the RIGHT pane of the two-pane view hides the buttons (the shipped row
        belongs to the first pane — the mc/far look) and shows the hints. The row is never
        BOTH and never NEITHER, so the listing never jumps by a line.

        v1.7rc3: a pane CARRYING a borrowed preview (`_viewer_borrowed`) is a PANEL, not a
        listing — it then shows NO row at all (and no address bar), because the row would act on
        a listing nobody can see.
        """
        secondary = self.secondary
        borrowed = bool(getattr(self, "_viewer_borrowed", False))
        try:
            self.buttons_bar.setVisible(not secondary and not borrowed)
            self.hints_label.setVisible(secondary and not borrowed)
            # v1.7.4rc1: the source switch belongs to the ADDRESS ROW, so it is visible exactly
            # while that row is — a pane carrying a borrowed preview is a panel and shows neither.
            switch = getattr(self, "source_switch", None)
            if switch is not None:
                switch.setVisible(not borrowed)
            if secondary:
                self.hints_label.setText(self.hint_text())
                self.hints_label.setToolTip(self.hint_text())
                # ONE line whose height is the button row's: switching panes must not resize the
                # listing by a few pixels (the ring's rule: a state change never reflows).
                height = self.buttons_bar.sizeHint().height()
                if height > 0:
                    self.hints_label.setFixedHeight(height)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a pane built before the row exists
        # The availability of the local source follows the ROLE of the pane (LOCAL_PANE.md §4):
        # only the second pane of the two-pane view may switch it.
        self._sync_source_availability()

    def focus_listing(self):
        """Give the keyboard to this pane's listing (the mc/far walk's landing point).

        The tree is the pane's keyboard domain, so a pane switch lands there and the arrows
        work at once; a listing with no current row gets its first navigable one, so `F3`/`F5`
        and the walk have a subject. Never raises.
        """
        try:
            self.tree.setFocus(Qt.FocusReason.OtherFocusReason)
        except (RuntimeError, AttributeError):
            return
        try:
            if self.tree.currentItem() is None:
                count = self.tree.topLevelItemCount()
                for i in range(count):
                    item = self.tree.topLevelItem(i)
                    if item is not None and item is not self._up_item:
                        self.tree.setCurrentItem(item)
                        break
        except RuntimeError:
            pass  # Qt teardown — nothing to select

    def _step_current_row(self, delta: int):
        """Move the current row by `delta` over the navigable rows of the listing.

        Only the rows a batch can act on take part (the ".." row is skipped — it is navigation,
        not a subject), which is what makes `Insert`/`Space` the mc/far MARK: the cursor walks
        the files and never lands on "..".

        Qt marks the row it is told to make CURRENT (`setCurrentItem` selects it and DROPS the
        rest of the selection), which is exactly the wrong half for a MARK: the walk therefore
        moves the CURRENT INDEX through the selection model (`CursorPosition` — no selection is
        touched at all), so a marked row stays marked while the cursor travels over it. The
        plain walk of `Enter`/`Left` never needs the selection half either. Never raises.
        """
        try:
            rows = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        except RuntimeError:
            return
        rows = [r for r in rows if r is not None and r is not self._up_item]
        current = self.tree.currentItem()
        if not rows:
            # an off-tree ".." row is the only thing on the screen: leave it, so a mark never
            # stays parked on navigation
            if current is self._up_item:
                self._move_cursor(self.tree.topLevelItem(0) if self.tree.topLevelItemCount()
                                  else None)
            return
        index = rows.index(current) if current in rows else -1
        if index < 0:
            index = 0 if delta > 0 else len(rows) - 1
        else:
            index = max(0, min(len(rows) - 1, index + delta))
        self._move_cursor(rows[index])

    def _move_cursor(self, item):
        """Make `item` the CURRENT row WITHOUT touching the selection (v1.7rc3). Never raises.

        `QTreeWidget.setCurrentItem()` selects the row and clears the rest of the selection —
        fine for a click, fatal for a MARK (`Insert` would unmark what it just marked and every
        earlier mark would be dropped on the next step). The cursor moves through the selection
        model instead, which is what the tree's own keyboard walk uses internally.
        """
        if item is None:
            return
        try:
            model = self.tree.selectionModel()
            index = self.tree.indexFromItem(item)
            if model is None or not index.isValid():
                return
            model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the model is gone

    def _set_row_marked(self, item, marked: bool):
        """Mark/unmark ONE row through the SELECTION MODEL (v1.7rc3). Never raises.

        `QTreeWidgetItem.setSelected()` is the item-level API and it does not reliably update the
        view's selection model on the CURRENT row (the mark of the row the cursor sits on is
        exactly what `Insert` toggles, so it is the one that matters). The model is the storage
        the batch READS (`tree.selectedItems()`), so the mark is written there.
        """
        if item is None:
            return
        try:
            model = self.tree.selectionModel()
            index = self.tree.indexFromItem(item)
            if model is None or not index.isValid():
                return
            flag = (QItemSelectionModel.SelectionFlag.Select if marked
                    else QItemSelectionModel.SelectionFlag.Deselect)
            model.select(index, flag | QItemSelectionModel.SelectionFlag.Rows)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown — the model is gone

    def _row_marked(self, item) -> bool:
        """True — THIS row carries the mark (read from the SAME selection model)."""
        if item is None:
            return False
        try:
            model = self.tree.selectionModel()
            index = self.tree.indexFromItem(item)
            if model is None or not index.isValid():
                return False
            return bool(model.isSelected(index))
        except (RuntimeError, AttributeError):
            return False

    def _mark_current_row(self):
        """v1.7rc3: `Insert`/`Space` — MARK the current row and step down (the mc/far mark).

        The mark IS the tree's selection (`ExtendedSelection`), which is what the batch of
        `F5`/`F6` reads (`_rows_for_batch()`), so marking needs no second state and no second
        truth. The cursor travels through `_move_cursor()` (never `setCurrentItem`, which would
        drop the marks already made), so the same key really means "mark" and "unmark" in turn.
        With no row at all the pane answers the shipped "select a row first" sentence.
        """
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return
        if item is None or item is self._up_item or not item.data(0, self.PATH_ROLE):
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._set_row_marked(item, not self._row_marked(item))
        # The mark walks DOWN, like every commander: the next key marks the next row.
        self._step_current_row(1)

    def _on_pane_key(self, event) -> bool:
        """v1.7rc3: the mc/far walk of the two-pane view; True — the pane consumed the key.

        ONE decision point for every widget of the pane: the tree calls it from its own
        `keyPressEvent`, the pane's `eventFilter` calls it for the address bar and the buttons,
        so `Tab` switches the panes from wherever the keyboard is (the buttons of the SHIPPED
        single-pane look sit in the tab order otherwise, and a `Tab` there would walk them one
        by one instead of changing the pane).

        Keys handled here: `Tab`/`Backtab` (the pane toggle), `Enter`/`Return` (the shipped
        double-click), `Insert`/`Space` (the mark), `Backspace` (one level up), `Left` (leave
        a directory for its parent row) and `Esc` (close the open preview — wherever it is
        shown). Everything else falls through to Qt — the arrows, the type-ahead and the
        selection modifiers are the tree's own and are deliberately not re-implemented.
        """
        if event is None or event.type() != QEvent.Type.KeyPress:
            return False
        try:
            key = int(event.key())
        except (AttributeError, TypeError, ValueError):
            return False
        mods = event.modifiers()
        plain = mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
        if key == int(Qt.Key.Key_Tab) and plain:
            return self._switch_pane(back=False)
        if key == int(Qt.Key.Key_Backtab) and mods in (
                Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            return self._switch_pane(back=True)
        if key == int(Qt.Key.Key_Escape) and mods == Qt.KeyboardModifier.NoModifier:
            # v1.7rc3: `Esc` leaves the preview. The panel may belong to the OTHER pane (the
            # mc preview of the two-pane view) — the container closes whichever one is open, so
            # the key works from the listing the file was opened from. False with no preview:
            # `Esc` stays the widget's own key (a completer popup, a dialog).
            return self._container.close_preview()
        if key in (int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter)) and plain:
            return self._open_current_row()
        if key in (int(Qt.Key.Key_Insert), int(Qt.Key.Key_Space)) and plain:
            self._mark_current_row()
            return True
        if key == int(Qt.Key.Key_Backspace) and plain:
            self.go_up()
            return True
        if key == int(Qt.Key.Key_Left) and plain:
            return self._leave_current_dir()
        return False

    def _switch_pane(self, back: bool) -> bool:
        """`Tab`/`Shift+Tab` — the pane toggle; True — the key is CONSUMED (v1.7).

        While the OTHER pane carries a borrowed panel there is no second LISTING to switch to — the
        panel is not a listing — so the key is consumed and NOTHING moves: the reading pane keeps
        its listing, its cursor and the keyboard (the contract's rule for the preview), instead of
        the focus walking onto a widget nobody can see.
        """
        if self._container.preview_in_other_pane(self):
            return True
        return bool(self._container.focus_other_pane(self, back=back))

    def _open_current_row(self) -> bool:
        """`Enter` — the shipped double-click on the current row (True — there was a row).

        A directory is entered, a file opens the read-only preview and ".." goes one level up;
        with no row the pane answers the shipped sentence, exactly like `F3`.
        """
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return True
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return True
        if item is self._up_item:
            self.go_up()
            return True
        self._on_item_double_clicked(item, 0)
        return True

    def _leave_current_dir(self) -> bool:
        """`Left` — leave a directory for its parent row instead of collapsing it (mc/far).

        True only when the current row IS a directory and its parent could be resolved: a file
        row, ".." and "/" answer False, so `Left` keeps Qt's own behaviour there (the selection
        moves one column left, which is what the shipped look does).
        """
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return False
        if item is None or item is self._up_item:
            return False
        if not item.data(0, self.ISDIR_ROLE):
            return False
        parent = self.paths.dirname(self._current_dir)
        if not parent or self.paths.same(parent, self._current_dir):
            return False
        self._relist(parent)
        return True

    def _current_row(self):
        """The row a pane-scoped key acts on: the CURRENT row of the listing (None — none)."""
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return None
        if item is None or item is self._up_item or not item.data(0, self.PATH_ROLE):
            return None
        return item

    def _cmd_view(self):
        """`F3` — view: the double-click behaviour on the current row (a directory is
        entered, a file opens the read-only preview, ".." goes up)."""
        try:
            item = self.tree.currentItem()
        except RuntimeError:
            return
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._on_item_double_clicked(item, 0)

    def _cmd_copy(self):
        """`F5` — copy the current row (or the whole selection) to the OTHER pane's directory.

        v1.7rc2 shipped the reserved half of the frozen contract; v1.7.4rc2 makes the
        destination a SOURCE as well — `_remote_batch()` dispatches over the pair of
        providers (LOCAL_PANE.md §5), so the file may cross to a server or come back from
        one. With ONE pane there is no destination, and the honest answer is ONE sentence
        (the corner control is what opens the second pane) — never a silent no-op.
        """
        target = self._container.other_pane(self)
        if target is None:
            self.message.emit(_t("sftp.cmd.copy_no_target"))
            return
        self._remote_batch(KIND_COPY, target)

    def _cmd_move_rename(self):
        """`F6` — move the row(s) to the other pane, or rename in place.

        The cross-directory MOVE (v1.7rc2) runs when the OTHER pane shows another
        directory; with a single pane — or when both panes are in the SAME directory — the
        shipped same-directory rename happens instead, so the key keeps the meaning it had
        in the single-listing tab. A move that would cross the two SOURCES is refused by
        the dispatch with ONE sentence (LOCAL_PANE.md §5 declares a copy there, and a
        silent copy is not a move).
        """
        target = self._container.other_pane(self)
        if target is not None and not self.paths.same(target.current_dir, self._current_dir):
            self._remote_batch(KIND_MOVE, target)
            return
        item = self._current_row()
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._op_rename(item)

    def _cmd_mkdir(self):
        """`F7` — new folder in THIS pane's current directory."""
        self._op_new_folder()

    def _cmd_delete(self):
        """`F8` — delete the current row (with the shipped confirmation)."""
        item = self._current_row()
        if item is None:
            self.message.emit(_t("sftp.cmd.no_selection"))
            return
        self._op_delete(item)

    # ── the tree's own open gesture — the SAME rule as `Enter` and `F3` ──

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        if not item.data(0, self.ISDIR_ROLE):
            self._open_viewer(item)   # v1.3.1: a file — the read-only preview
            return
        if item is self._up_item:
            self.go_up()
        else:
            self._navigate(item.data(0, self.PATH_ROLE))
