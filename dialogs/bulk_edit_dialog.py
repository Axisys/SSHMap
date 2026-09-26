# -*- coding: utf-8 -*-
"""v1.6 (ROADMAP task 1): the BULK EDIT of the selection.

A map of hundreds of cards needs a way to say "these twelve servers are production
now" in one gesture. This dialog is the ask; the answer is ONE undo command
(`modules/undo_commands.CmdEditSelected`, the `CmdAddRemoveNodeBatch` precedent — per
node before/after values, one entry in the stack).

**Every field is TRI-STATE, and "leave unchanged" is the DEFAULT.** The three states
are the only vocabulary the dialog has:

  * ``unchanged`` — the field is not touched on ANY node (nothing is written, so a
    per-server value survives a bulk edit of the other two fields);
  * ``set``       — every selected node gets the value typed here;
  * ``clear``     — every selected node loses the field.

The dialog is deliberately dumb: it collects three states and hands them over. The
PURE half that turns them into real values — `bulk_change_values()` — sits next to it,
so the round trip is testable without a window, and `changes_for()` is what tells the
window that a node would really change (a node whose new triple equals its old one
never enters the command).

The fields are exactly the three per-server fields the v1.6 plan names (tags, comment,
quick launch): the hardware facts and the identity of a server are not a bulk material.
"""
import copy
from typing import List, Optional

try:  # v1.6: the quick-launch entry sanitizer (models/server.py)
    from ..models.server import sanitize_quick_launch
except ImportError:
    from models.server import sanitize_quick_launch

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QDialogButtonBox,
)

#: The three states of every field (the vocabulary of `changes()`).
STATE_UNCHANGED = "unchanged"
STATE_SET = "set"
STATE_CLEAR = "clear"
FIELD_STATES = (STATE_UNCHANGED, STATE_SET, STATE_CLEAR)

#: The three fields a bulk edit owns, in the dialog's row order.
FIELD_TAGS = "tags"
FIELD_COMMENT = "comment"
FIELD_QUICK_LAUNCH = "quick_launch"
BULK_FIELDS = (FIELD_TAGS, FIELD_COMMENT, FIELD_QUICK_LAUNCH)


# ── the PURE half: states → values ───────────────────────────────────────────────

def parse_tags(text) -> List[str]:
    """``"web, prod ,web"`` → ``["web", "prod"]`` — trimmed, de-duplicated, order kept.

    The split is on commas (the same separator the sidebar, the filter and the tag
    chips already use), the case-insensitive duplicate rule matches
    `sanitize_quick_launch`'s sibling in `models/server.py`, and the FIRST spelling of
    a tag wins (a user's own capitalisation is data).
    """
    out: List[str] = []
    seen = set()
    for chunk in str(text or "").split(","):
        tag = chunk.strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def _state_of(value):
    """``(state, payload)`` out of one `changes()` entry — tolerant of a bare state."""
    if isinstance(value, (tuple, list)):
        state = str(value[0] if value else STATE_UNCHANGED)
        payload = value[1] if len(value) > 1 else None
        return state, payload
    return str(value or STATE_UNCHANGED), None


def bulk_change_values(data, changes) -> dict:
    """The (tags, comment, quick_launch) triple a node ENDS UP with — PURE.

    ``data`` is a `ServerData` (or any object with the three attributes); ``changes`` is
    the mapping the dialog produced: ``{field: (state, payload)}``. A field that is not
    in ``changes`` — and every field at ``unchanged`` — keeps the node's own value, which
    is the whole point of the tri-state: a bulk edit of the comment must not wipe the
    tags of eleven servers.

    The result is a NEW dict with fresh lists (never a reference into ``data``), so the
    command's before/after snapshots cannot alias the model.
    """
    result = {
        "tags": list(getattr(data, "tags", None) or []),
        "comment": str(getattr(data, "comment", "") or ""),
        "quick_launch": copy.deepcopy(list(getattr(data, "quick_launch", None) or [])),
    }
    for field, value in (changes or {}).items():
        if field not in BULK_FIELDS:
            continue
        state, payload = _state_of(value)
        if state == STATE_UNCHANGED:
            continue
        if state == STATE_CLEAR:
            result[field] = [] if field in (FIELD_TAGS, FIELD_QUICK_LAUNCH) else ""
            continue
        if state != STATE_SET:
            continue  # an unknown state is "leave unchanged", never a silent write
        if field == FIELD_TAGS:
            result[FIELD_TAGS] = parse_tags(payload)
        elif field == FIELD_COMMENT:
            result[FIELD_COMMENT] = str(payload or "")
        else:
            entry = payload if isinstance(payload, dict) else None
            result[FIELD_QUICK_LAUNCH] = [dict(entry)] if entry else []
    return result


def values_of(data) -> dict:
    """The CURRENT triple of a node, in the same shape `bulk_change_values` returns."""
    return bulk_change_values(data, {})


def changes_for(data, changes):
    """``(old, new)`` for one node, or None when the bulk edit changes nothing.

    The window builds one entry per node the dialog really changes — a node that already
    carries the values never enters the undo command, so Ctrl+Z after a bulk edit cannot
    report "edited 12 servers" while touching three.
    """
    old = values_of(data)
    new = bulk_change_values(data, changes)
    return None if new == old else (old, new)


# ── the dialog ───────────────────────────────────────────────────────────────────

class BulkEditDialog(QDialog):
    """Edit tags / comment / quick launch for the whole selection (v1.6, task 1).

    The tri-state widget of a field is ONE combo (unchanged / replace / clear) plus the
    editor of the value, which is enabled only in the "replace" state — so the dialog
    itself says what it will do, and an accidental click cannot write anything: the
    default state of every row is "leave unchanged".
    """

    def __init__(self, count: int = 0, parent=None):
        super().__init__(parent)
        self._count = max(int(count or 0), 0)
        self._i18n_available = False
        try:
            from i18n import t as __t
            self.t = __t
            self._i18n_available = True
            self.setWindowTitle(__t("bulk.title", count=self._count))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
            self.setWindowTitle(f"Bulk edit — {self._count} servers")
        self.setMinimumWidth(560)

        self._state_combos = {}
        self._editors = {}
        self._build_ui()

    def _tr(self, key: str, **kw) -> str:
        """Translation with the English literal as the fallback (the dialog convention)."""
        if self._i18n_available:
            try:
                return self.t(key, **kw)
            except Exception:  # noqa: BLE001 — an i18n failure must not break the dialog
                pass
        return key

    def _state_combo(self, field: str) -> QComboBox:
        """The tri-state combo of one field (the DEFAULT is "leave unchanged")."""
        combo = QComboBox()
        for state, key in ((STATE_UNCHANGED, "bulk.state.unchanged"),
                           (STATE_SET, "bulk.state.set"),
                           (STATE_CLEAR, "bulk.state.clear")):
            combo.addItem(self._tr(key), state)
        combo.setCurrentIndex(0)   # unchanged — the safe default of every row
        self._state_combos[field] = combo
        return combo

    def _build_ui(self):
        layout = QVBoxLayout(self)
        hint = QLabel(self._tr("bulk.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setColumnStretch(2, 1)

        # ── tags ───────────────────────────────────────────────────────────
        self.tags_combo = self._state_combo(FIELD_TAGS)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(self._tr("bulk.tags.hint"))
        self._editors[FIELD_TAGS] = self.tags_edit
        grid.addWidget(self._state_combo(FIELD_TAGS), 0, 0)
        grid.addWidget(QLabel(self._tr("bulk.field.tags")), 0, 1)
        grid.addWidget(self.tags_edit, 0, 2)

        # ── comment ────────────────────────────────────────────────────────
        self.comment_combo = self._state_combo(FIELD_COMMENT)
        self.comment_edit = QLineEdit()
        self._editors[FIELD_COMMENT] = self.comment_edit
        grid.addWidget(self._state_combo(FIELD_COMMENT), 1, 0)
        grid.addWidget(QLabel(self._tr("bulk.field.comment")), 1, 1)
        grid.addWidget(self.comment_edit, 1, 2)

        # ── quick launch ───────────────────────────────────────────────────
        # ONE entry for every selected node (a bulk edit of a LIST is a replacement, not
        # a merge — the honest shape: "give all of these the same link/command").
        self.ql_combo = self._state_combo(FIELD_QUICK_LAUNCH)
        self.ql_name_edit = QLineEdit()
        self.ql_name_edit.setPlaceholderText(self._tr("ql.name"))
        self.ql_value_edit = QLineEdit()
        self.ql_value_edit.setPlaceholderText(self._tr("ql.value_hint_url"))
        self.ql_type_combo = QComboBox()
        self.ql_type_combo.addItem(self._tr("ql.type.url"), "url")
        self.ql_type_combo.addItem(self._tr("ql.type.command"), "command")
        self.ql_type_combo.currentIndexChanged.connect(self._on_ql_type_changed)
        ql_row = QHBoxLayout()
        ql_row.addWidget(self.ql_name_edit, 2)
        ql_row.addWidget(self.ql_value_edit, 3)
        ql_row.addWidget(self.ql_type_combo, 1)
        grid.addWidget(self.ql_combo, 2, 0)
        grid.addWidget(QLabel(self._tr("bulk.field.quick_launch")), 2, 1)
        grid.addLayout(ql_row, 2, 2)

        layout.addLayout(grid)
        layout.addStretch(1)

        for field, combo in self._state_combos.items():
            combo.currentIndexChanged.connect(
                lambda _idx, f=field: self._sync_enabled(f))

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        for field in BULK_FIELDS:
            self._sync_enabled(field)

    def _on_ql_type_changed(self, _index: int):
        """The value placeholder follows the entry type (the quick-launch editor rule)."""
        if self.ql_type_combo.currentData() == "command":
            self.ql_value_edit.setPlaceholderText(self._tr("ql.value_hint_command"))
        else:
            self.ql_value_edit.setPlaceholderText(self._tr("ql.value_hint_url"))

    def _sync_enabled(self, field: str):
        """The value widgets are usable only in the "replace" state."""
        state = self.state_of(field)
        enabled = state == STATE_SET
        try:
            editor = self._editors.get(field)
            if editor is not None:
                editor.setEnabled(enabled)
            if field == FIELD_QUICK_LAUNCH:
                self.ql_name_edit.setEnabled(enabled)
                self.ql_value_edit.setEnabled(enabled)
                self.ql_type_combo.setEnabled(enabled)
        except RuntimeError:
            pass  # Qt teardown

    # ── the collected answer ───────────────────────────────────────────────

    def state_of(self, field: str) -> str:
        """The state the user picked for one field ("" — an unknown field)."""
        combo = self._state_combos.get(field)
        if combo is None:
            return ""
        try:
            return str(combo.currentData() or STATE_UNCHANGED)
        except RuntimeError:
            return STATE_UNCHANGED

    def set_state(self, field: str, state: str):
        """Select a state programmatically (the topical test's seam, and a future preset)."""
        combo = self._state_combos.get(field)
        if combo is None:
            return
        index = next((i for i in range(combo.count()) if combo.itemData(i) == state), 0)
        combo.setCurrentIndex(index)
        self._sync_enabled(field)

    def changes(self) -> dict:
        """``{field: (state, payload)}`` — the answer `bulk_change_values()` consumes.

        A field left at "leave unchanged" is present with its state and a ``None``
        payload, so a caller never has to guess whether a missing key means "unchanged"
        or "the dialog had no such row".
        """
        out = {}
        for field in BULK_FIELDS:
            state = self.state_of(field)
            payload = None
            if state == STATE_SET:
                if field == FIELD_TAGS:
                    payload = self.tags_edit.text()
                elif field == FIELD_COMMENT:
                    payload = self.comment_edit.text()
                else:
                    payload = self.quick_launch_entry()
            out[field] = (state, payload)
        return out

    def quick_launch_entry(self) -> Optional[dict]:
        """The single quick-launch entry the dialog describes (None — no name or value)."""
        name = self.ql_name_edit.text().strip()
        value = self.ql_value_edit.text().strip()
        if not name or not value:
            return None
        etype = str(self.ql_type_combo.currentData() or "url")
        entries = sanitize_quick_launch([{"type": etype, "name": name, "value": value}])
        return entries[0] if entries else None
