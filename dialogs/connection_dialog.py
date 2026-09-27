from typing import List, Dict, Optional, Callable, TYPE_CHECKING

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:
    from ..graphics.connection_arrow import CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE
except ImportError:
    from graphics.connection_arrow import CONNECTION_TYPES, DEFAULT_CONNECTION_TYPE

if TYPE_CHECKING:  # the `arrow` parameter of EditConnectionDialog (no runtime import needed)
    from graphics.connection_arrow import ConnectionArrow

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QCompleter, QLabel, QLineEdit, QDialogButtonBox,
    QCheckBox,
)


def _live_nodes(nodes: List[ServerNode], provider: Optional[Callable] = None) -> List[ServerNode]:
    """The nodes the pickers offer: the LIVE scene when a provider was handed in.

    v1.6.8 (ROADMAP task 3): the searchable pickers are fed "through a callback (the
    module + callbacks pattern: the dialog knows no scene)" — the window passes
    ``nodes_provider``, a zero-argument callable that reads the scene, and this dialog
    never learns what a scene is. A provider that fails or answers nothing leaves the
    list the caller already passed, so a dialog can never open with an EMPTY picker
    because of a broken callback.
    """
    if not callable(provider):
        return list(nodes or ())
    try:
        live = list(provider() or ())
    except Exception:  # noqa: BLE001 — a broken provider must not empty the dialog
        live = []
    return live or list(nodes or ())


class _LabelLineEdit(QLineEdit):
    """QLineEdit with an INPUT limit that does not truncate already-set text.

    v1.1.1 (ROADMAP item 6): Qt setMaxLength() TRUNCATES the current text when the
    limit is set (verified on PySide6 6.11: both orders — setText→setMaxLength and
    setMaxLength→setText result in truncation), and old projects with labels longer
    than 20 characters lost their tail in EditConnectionDialog ("limit only for input"
    — old labels are read unchanged). So the limit is enforced by a guard on
    textChanged: programmatic setText (loading an old label) passes through as-is,
    while user input pushing the text past max(limit, length at load time) is cut
    from the tail. maxLength() reports the set value.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._input_max = 16777215   # Qt default — no limit
        self._loaded_len = 0         # text length at programmatic setText (old label)
        self._guarding = False
        self.textChanged.connect(self._enforce_input_limit)
        # Text from the CONSTRUCTOR arrived before textChanged was connected — treat it
        # as a loaded (old) label, otherwise the guard would cut input by the limit
        # instead of by its length.
        self._loaded_len = len(self.text())

    def setMaxLength(self, n: int):
        """Remember the input limit without truncating existing text (Qt does)."""
        self._input_max = max(0, int(n))

    def maxLength(self) -> int:
        return self._input_max

    def setText(self, text: str):
        # Programmatic set (loading an old label) — exempt from the input limit;
        # guard flag: textChanged from super().setText() arrives BEFORE _loaded_len
        # is updated and without the flag would cut the loaded label itself.
        self._guarding = True
        super().setText(text)
        self._loaded_len = len(text)
        self._guarding = False

    def _enforce_input_limit(self, text: str):
        if self._guarding:
            return
        ceiling = max(self._input_max, self._loaded_len)
        if len(text) <= ceiling:
            return
        # Excess from input (typing/paste) — cut from the tail; cursor stays within the allowed range.
        self._guarding = True
        cur = min(self.cursorPosition(), ceiling)
        super().setText(text[:ceiling])
        self.setCursorPosition(cur)
        self._guarding = False


def match_index(texts: List[str], query: str) -> int:
    """The index a settled query MEANS (v1.6.8) — the ONE search rule of the pickers (PURE).

    Three tiers, in order:

      1. an EXACT text wins (`"web-1 (10.0.0.1)"` typed or picked) — never ambiguous;
      2. otherwise the FIRST case-insensitive SUBSTRING match, on the alias OR the host,
         because that is exactly the filter the popup itself applies (`MatchContains`):
         a fragment a user typed means the server it names, and the scene's order makes
         the answer deterministic;
      3. otherwise ``-1`` — nothing carries the query, and the caller keeps the previous
         selection and says so.

    A blank query answers ``-1`` as well: an empty field is not a query.
    """
    text = str(query or "")
    if not text.strip():
        return -1
    for i, candidate in enumerate(texts):
        if str(candidate) == text:
            return i
    needle = text.casefold()
    for i, candidate in enumerate(texts):
        if needle in str(candidate).casefold():
            return i
    return -1


class ConnectionDialog(QDialog):
    """Dialog for creating a connection between two nodes.

    v0.7: added connection type selection (QComboBox) and source/target prefill
    capability — used by the "drag" mode from MapView.

    v1.6.8 (ROADMAP task 3): **the two pickers can be TYPED into.** The two fields stay
    the DISPLAY of the selection (`self.source` / `self.target` keep their contract —
    `currentData()` is still the node id the command writes), and the CHOOSING becomes
    searchable: ONE `QCompleter` per field over the item text, which is
    `"<alias> (<host>)"`, so a query matches the **alias OR the host** as a
    case-insensitive SUBSTRING (`Qt.MatchContains` — the `SftpTab` address bar's
    completer is the shipped precedent). Typing the first character opens the popup.

    **A query that matches nothing never empties the picker.** The last VALID index is
    remembered while the user types, and settling the field on a text no node carries
    restores that selection and REPORTS the fact in one sentence
    (`connection.no_match`) — the row `_no_match_label`, hidden until it happens. An
    empty picker would leave the dialog with no source at all, which is precisely the
    state a search field must never be able to produce.
    """

    def __init__(self, nodes: List[ServerNode], parent=None,
                 default_source_id: Optional[str] = None,
                 default_target_id: Optional[str] = None,
                 default_type: str = DEFAULT_CONNECTION_TYPE,
                 nodes_provider: Optional[Callable] = None):
        super().__init__(parent)

        # ── i18n support ────────────────────────────────
        self._i18n_available = False

        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()  # Use already-set global language (restored from config)
            self._i18n_available = True

            self.setWindowTitle(__t("dialog.add_connection"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop

        self.setMinimumWidth(300)
        layout = QFormLayout(self)

        #: The last index the user really CHOSE, per field (v1.6.8). An editable combo
        #: drops `currentIndex` to -1 while a partial query is typed, so the previous
        #: selection is remembered HERE — it is what a no-match query restores.
        self._last_valid: Dict[str, int] = {"source": 0, "target": 0}

        self.source = QComboBox()
        self.target = QComboBox()
        self.label = QLineEdit()
        # v1.1.1 (ROADMAP item 6): 20-character limit — for INPUT only (new dialog);
        # hint in i18n (connection.label_hint).
        self.label.setMaxLength(20)
        if self._i18n_available:
            self.label.setPlaceholderText(self.t("connection.label_hint"))

        # Connection type (v0.7): order = declaration order in CONNECTION_TYPES
        self.type_combo = QComboBox()
        for cid in CONNECTION_TYPES:
            display = self.t(f"connection.type.{cid}") if self._i18n_available else cid
            self.type_combo.addItem(display, cid)

        # v1.2.6: bidirectional connection (arrowheads on both ends). The checkbox has
        # ITS OWN label — addRow(widget) stretches it across both form columns.
        self.bidirectional_check = QCheckBox(
            self.t("connection.bidirectional") if self._i18n_available else "Bidirectional")

        # v1.6.8 (ROADMAP task 3): the node list comes from the LIVE scene through the
        # caller's callback; the fallback is the list it passed in.
        self._node_map: Dict[str, ServerNode] = {}
        for n in _live_nodes(nodes, nodes_provider):
            text = f"{n.data.alias} ({n.data.host})"
            self._node_map[n.data.id] = n
            self.source.addItem(text, n.data.id)
            self.target.addItem(text, n.data.id)

        # Prefill source/target (drag mode, v0.7)
        if default_source_id is not None:
            idx = self.source.findData(default_source_id)
            if idx >= 0:
                self.source.setCurrentIndex(idx)
        if default_target_id is not None:
            idx = self.target.findData(default_target_id)
            if idx >= 0:
                self.target.setCurrentIndex(idx)
        else:
            # v1.6.8: "Connect to…" (the map/sidebar row) hands in the SOURCE alone, and
            # the target used to stay on item 0 — which IS the source for the first card,
            # so the dialog opened on its own refusal (`validation.self_connection`). The
            # default target is the first node that is NOT the chosen source; an explicit
            # `default_target_id` (the drag path) still wins untouched.
            source_id = self.source.currentData()
            if source_id is not None and self.target.currentData() == source_id:
                idx = next((i for i in range(self.target.count())
                            if self.target.itemData(i) != source_id), -1)
                if idx >= 0:
                    self.target.setCurrentIndex(idx)

        # Default type (or from old projects / drag mode)
        type_idx = self.type_combo.findData(
            default_type if default_type in CONNECTION_TYPES else DEFAULT_CONNECTION_TYPE)
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)

        # v1.6.8: the search of the two pickers — installed AFTER the prefill, so the
        # remembered "last valid index" starts on the dialog's real opening selection.
        self._install_search(self.source, "source")
        self._install_search(self.target, "target")

        # The no-match answer, in its own row: hidden until a query keeps nothing.
        self.no_match_label = QLabel("")
        self.no_match_label.setWordWrap(True)
        self.no_match_label.hide()

        layout.addRow(self.t("connection.from") if self._i18n_available else "From:", self.source)
        layout.addRow(self.t("connection.to") if self._i18n_available else "To:", self.target)
        layout.addRow(self.no_match_label)
        layout.addRow(self.t("connection.label") if self._i18n_available else "Label:", self.label)
        layout.addRow(
            self.t("connection.type_label") if self._i18n_available else "Connection type:",
            self.type_combo,
        )
        # v1.2.6: checkbox spans the full form width (label — the checkbox's own text)
        layout.addRow(self.bidirectional_check)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    # ── v1.6.8 (ROADMAP task 3): the searchable pickers ──────────────────────────

    def _install_search(self, combo: QComboBox, kind: str) -> None:
        """Make ONE picker typeable: a `QCompleter` over `alias` AND `host`.

        The completion model IS the combo's own model — the item text carries the alias
        and the host in the dialog's declared format, so ONE string serves both keys and
        there is no second list to keep in sync. `MatchContains` + `CaseInsensitive` is
        the substring rule the plan fixes (the SftpTab precedent), and the popup opens on
        the FIRST keystroke because that is `PopupCompletion`'s own behaviour.
        """
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter(combo.model(), combo)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        combo.setCompleter(completer)
        # The chosen completion is a real CHOICE — it settles the field at once. The
        # `[str]` overload is named explicitly: PySide6 also exposes the QModelIndex
        # form, and an untyped lambda would leave Qt to guess which one it is.
        completer.activated[str].connect(
            lambda text, c=combo: self._choose_text(c, text))
        # Every index the user really lands on is remembered (a typed partial query makes
        # Qt report -1 — that is the state the no-match answer must survive).
        combo.currentIndexChanged.connect(
            lambda idx, k=kind: self._remember_index(k, idx))
        combo.lineEdit().editingFinished.connect(lambda c=combo: self.settle_picker(c))
        self._remember_index(kind, combo.currentIndex())

    def _remember_index(self, kind: str, index: int) -> None:
        """Remember the last REAL selection of a picker (`-1` is a typed query)."""
        if index is not None and int(index) >= 0:
            self._last_valid[kind] = int(index)

    def _kind_of(self, combo: QComboBox) -> str:
        """Which of the two pickers this is (the `_last_valid` key)."""
        return "target" if combo is self.target else "source"

    def _choose_text(self, combo: QComboBox, text: str) -> None:
        """A completion was activated: select the node it names (`-1` — nothing)."""
        idx = match_index(self._texts(combo), text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self._hide_no_match()

    @staticmethod
    def _texts(combo: QComboBox) -> List[str]:
        """The item texts of ONE picker (the model the search reads and the test drives)."""
        return [combo.itemText(i) for i in range(combo.count())]

    def settle_picker(self, combo: QComboBox) -> None:
        """Resolve what is in a picker: a real node, or the PREVIOUS one + a sentence.

        Called when the field is left (Enter or focus out) and from `get_connection()`,
        so a typed query can never reach the command as `None`: the pure `match_index()`
        resolves it (exact, then the first substring match), and a query NOTHING carries
        restores the last valid selection and says so — the dialog's own answer, never an
        empty picker.
        """
        kind = self._kind_of(combo)
        text = combo.currentText()
        idx = match_index(self._texts(combo), text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self._remember_index(kind, idx)
            self._hide_no_match()
            return
        kept = int(self._last_valid.get(kind, 0) or 0)
        if 0 <= kept < combo.count():
            combo.setCurrentIndex(kept)
        if str(text or "").strip():
            # An EMPTY field is not a query — the display simply returns to the last real
            # selection and there is nothing to report.
            self._report_no_match(text, combo.itemText(kept) if kept >= 0 else "")

    def _report_no_match(self, query: str, kept: str) -> None:
        """Say that a query kept the previous selection (ONE sentence, `{query}`/`{name}`)."""
        try:
            self.no_match_label.setText(self.t("connection.no_match", query=query, name=kept))
            self.no_match_label.show()
        except RuntimeError:
            pass  # Qt teardown — the dialog is already gone

    def _hide_no_match(self) -> None:
        try:
            self.no_match_label.hide()
        except RuntimeError:
            pass  # Qt teardown

    def get_connection(self):
        """Returns (source_id, target_id, label, connection_type, bidirectional).

        v1.2.6: the 5th element — bidirectional mode (bool); before v1.2.6 it had 4 elements.

        v1.6.8: the two pickers are SETTLED first, so a half-typed query can never leave
        the dialog as `None` — the answer is the same node the OK button displays.
        """
        self.settle_picker(self.source)
        self.settle_picker(self.target)
        return (
            self.source.currentData(),
            self.target.currentData(),
            self.label.text(),
            self.type_combo.currentData(),
            self.bidirectional_check.isChecked(),
        )


class EditConnectionDialog(QDialog):
    """Dialog for editing an existing connection (v0.7.3).

    Unlike ConnectionDialog, the nodes cannot be changed (source/target are shown
    read-only) — only the label and the connection type are edited.
    """

    def __init__(self, arrow: "ConnectionArrow", parent=None):
        super().__init__(parent)

        # ── i18n support (consistent with ConnectionDialog) ──
        self._i18n_available = False
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()
            self._i18n_available = True
            self.setWindowTitle(__t("dialog.edit_connection"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop

        self.setMinimumWidth(300)
        layout = QFormLayout(self)

        # Source/Target — read-only (the connection between specific nodes does not change)
        src_text = f"{arrow.source.data.alias} ({arrow.source.data.host})"
        tgt_text = f"{arrow.target.data.alias} ({arrow.target.data.host})"
        self.source = QLineEdit(src_text)
        self.source.setReadOnly(True)
        self.target = QLineEdit(tgt_text)
        self.target.setReadOnly(True)

        # v1.1.1 (ROADMAP item 6): 20-character limit — for INPUT only. _LabelLineEdit:
        # Qt setMaxLength() immediately truncates existing text (verified on PySide6 6.11),
        # so old projects with long labels are read unchanged, while the limit is
        # enforced by a guard on input (see the class).
        self.label = _LabelLineEdit(getattr(arrow, "label_text", "") or "")
        self.label.setMaxLength(20)
        if self._i18n_available:
            self.label.setPlaceholderText(self.t("connection.label_hint"))
        self.type_combo = QComboBox()
        for cid in CONNECTION_TYPES:
            display = self.t(f"connection.type.{cid}") if self._i18n_available else cid
            self.type_combo.addItem(display, cid)
        type_idx = self.type_combo.findData(
            arrow.connection_type if arrow.connection_type in CONNECTION_TYPES
            else DEFAULT_CONNECTION_TYPE)
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)

        # v1.2.6: bidirectional mode — prefilled from the arrow's state (getattr guard:
        # an object without the attribute, e.g. a test double, reads as the default).
        self.bidirectional_check = QCheckBox(
            self.t("connection.bidirectional") if self._i18n_available else "Bidirectional")
        self.bidirectional_check.setChecked(bool(getattr(arrow, "bidirectional", False)))

        layout.addRow(
            self.t("connection.from") if self._i18n_available else "From:",
            self.source)
        layout.addRow(
            self.t("connection.to") if self._i18n_available else "To:",
            self.target)
        layout.addRow(
            self.t("connection.label") if self._i18n_available else "Label:",
            self.label)
        layout.addRow(
            self.t("connection.type_label") if self._i18n_available else "Connection type:",
            self.type_combo)
        # v1.2.6: checkbox spans the full form width (label — the checkbox's own text)
        layout.addRow(self.bidirectional_check)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_connection(self):
        """Returns (label, connection_type, bidirectional) — the nodes are fixed.

        v1.2.6: the 3rd element — bidirectional mode (bool); before v1.2.6 it had 2 elements.
        """
        return (self.label.text(), self.type_combo.currentData(),
                self.bidirectional_check.isChecked())
