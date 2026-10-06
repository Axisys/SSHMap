# -*- coding: utf-8 -*-
"""The trust surface's two windows: the host-key question and the known-hosts manager (AGENTS.md §4.4).

`HostKeyDialog` is the moment the declared TOFU policy never had — the algorithm and the SHA256
fingerprint of a key that is about to be trusted, with Accept / Replace / Reject — and the same window
serves the CHANGED case by showing the stored fingerprint beside the one the server presents now.

`KnownHostsManagerDialog` is the surface over `~/.sshmap/known_hosts`: the list of what is recorded,
"delete this fingerprint" and "replace it with the key the server offers now" (an UNAUTHENTICATED key
read, because a fingerprint cannot be turned back into a key).

Mechanism — `DOCUMENTATION.md` §16; the store itself — `modules/host_key_policy.py`."""

from typing import List, Dict

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:
    from ..modules import host_key_policy as _hkp
except ImportError:
    from modules import host_key_policy as _hkp

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

#: The budget of the unauthenticated key read the manager performs (one TCP connect + one KEX).
PROBE_TIMEOUT_S = 10.0


def host_key_rows(entries) -> List[Dict[str, str]]:
    """`{host: {keytype: key}}` → `[{"host", "keytype", "fingerprint"}]`, sorted (PURE).

    The ONE row model of the manager, so the table, the tests and any future export read the same
    three facts. A key whose fingerprint cannot be produced still gets a row — the entry EXISTS, and
    hiding it would be the worse answer.
    """
    rows: List[Dict[str, str]] = []
    try:
        items = dict(entries or {}).items()
    except Exception:  # noqa: BLE001 — a broken store object is an empty list, never a crash
        return rows
    for host, keys in items:
        try:
            key_items = dict(keys or {}).items()
        except Exception:  # noqa: BLE001
            continue
        for keytype, key in key_items:
            rows.append({"host": str(host), "keytype": str(keytype),
                         "fingerprint": _hkp.fingerprint(key)})
    rows.sort(key=lambda r: (r["host"].lower(), r["keytype"]))
    return rows


class _HostKeyProbe(QThread):
    """ONE unauthenticated read of the key a server presents now (the manager's "replace")."""

    probed = Signal(object, str)   # (the key or None, the error text)

    def __init__(self, host: str, port, parent=None):
        super().__init__(parent)
        self.setObjectName("HostKeyProbe")
        self.host = host
        self.port = port

    def run(self):
        key, error = _hkp.read_server_host_key(self.host, self.port, timeout=PROBE_TIMEOUT_S)
        self.probed.emit(key, error or "")


class HostKeyDialog(QDialog):
    """Accept or refuse ONE host key — the first connection, or a key that CHANGED.

    `expected` empty means "unknown host"; a non-empty one switches the window into the changed-key
    reading (both fingerprints, the stronger wording) and the accept button says REPLACE, because
    that is what the answer does to the store.
    """

    def __init__(self, parent=None, host: str = "", port=22, keytype: str = "",
                 fingerprint: str = "", expected: str = ""):
        super().__init__(parent)
        self.t = None
        self._i18n_available = False
        try:
            from i18n import t as __t
            self.t = __t
            self._i18n_available = True
        except Exception:  # noqa: BLE001 — no i18n: the keys themselves are shown
            self.t = lambda key, **kw: key.format(**kw) if kw else key

        self.changed = bool(expected)
        self.setWindowTitle(self.t("hostkey.title_changed" if self.changed else "hostkey.title_new"))
        self.setMinimumWidth(520)
        self._build_ui(host, port, keytype, fingerprint, expected)

    def _build_ui(self, host, port, keytype, fingerprint, expected):
        layout = QVBoxLayout(self)

        headline = QLabel(self.t("hostkey.title_changed" if self.changed else "hostkey.title_new"))
        headline.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(headline)

        note = QLabel(self.t("hostkey.changed_note" if self.changed else "hostkey.new_note"))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(note)
        layout.addSpacing(6)

        endpoint = QLabel(f"{self.t('hostkey.host_label')} <b>{host}:{port}</b>")
        layout.addWidget(endpoint)
        algorithm = QLabel(f"{self.t('hostkey.keytype_label')} <b>{keytype or '?'}</b>")
        layout.addWidget(algorithm)

        presented = QLabel(f"{self.t('hostkey.fingerprint_label')}\n{fingerprint}")
        presented.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        presented.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")
        layout.addWidget(presented)

        if self.changed:
            stored = QLabel(f"{self.t('hostkey.expected_label')}\n{expected}")
            stored.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            stored.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            layout.addWidget(stored)

        layout.addSpacing(8)
        buttons = QHBoxLayout()
        reject = QPushButton(self.t("hostkey.reject"))
        reject.clicked.connect(self.reject)
        accept = QPushButton(self.t("hostkey.replace" if self.changed else "hostkey.accept"))
        accept.setDefault(True)
        accept.clicked.connect(self.accept)
        buttons.addWidget(reject)
        buttons.addStretch()
        buttons.addWidget(accept)
        layout.addLayout(buttons)

    def asked_host_key(self) -> bool:
        """The answer in the vocabulary of the policy: True — trust (and pin/replace) this key."""
        return self.result() == QDialog.DialogCode.Accepted


class KnownHostsManagerDialog(QDialog):
    """The `~/.sshmap/known_hosts` surface: what is stored, delete one fingerprint, replace one."""

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.t = None
        self._i18n_available = False
        try:
            from i18n import t as __t
            self.t = __t
            self._i18n_available = True
        except Exception:  # noqa: BLE001
            self.t = lambda key, **kw: key.format(**kw) if kw else key

        self.store = store if store is not None else _hkp.get_store()
        self._probe = None
        self.setWindowTitle(self.t("hostkey.manager_title"))
        self.setMinimumSize(680, 440)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel(self.t("hostkey.manager_title"))
        title.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel(self.t("hostkey.manager_desc"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(desc)

        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {theme.SELECTION_AMBER};")
        self.warning.hide()
        layout.addWidget(self.warning)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([
            self.t("hostkey.col_host"), self.t("hostkey.col_keytype"),
            self.t("hostkey.col_fingerprint")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(self.table)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.btn_replace = QPushButton(self.t("hostkey.manager_replace"))
        self.btn_replace.clicked.connect(self._on_replace)
        self.btn_delete = QPushButton(self.t("hostkey.manager_delete"))
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh = QPushButton(self.t("hostkey.manager_refresh"))
        self.btn_refresh.clicked.connect(self.refresh)
        buttons.addWidget(self.btn_replace)
        buttons.addWidget(self.btn_delete)
        buttons.addWidget(self.btn_refresh)
        buttons.addStretch()
        layout.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        layout.addWidget(close)

    # ── the list ─────────────────────────────────────────────

    def refresh(self):
        """Re-read the store and rebuild the table (the ONE read path of this dialog)."""
        self.rows = host_key_rows(self.store.entries())
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            self.table.setItem(index, 0, QTableWidgetItem(row["host"]))
            self.table.setItem(index, 1, QTableWidgetItem(row["keytype"]))
            self.table.setItem(index, 2, QTableWidgetItem(row["fingerprint"]))
        if self.store.load_failed:
            self.warning.setText(self.t("hostkey.manager_unreadable", path=self.store.path))
            self.warning.show()
        else:
            self.warning.hide()
        if not self.rows:
            self.status.setText(self.t("hostkey.manager_empty"))
        elif self.status.text() == self.t("hostkey.manager_empty"):
            self.status.setText("")
        self._sync_buttons()

    def selected_row(self):
        """The `{host, keytype, fingerprint}` of the selected row, or None."""
        index = self.table.currentRow()
        if index < 0 or index >= len(self.rows):
            return None
        return self.rows[index]

    def _sync_buttons(self):
        enabled = self.selected_row() is not None
        self.btn_replace.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    # ── the two operations ───────────────────────────────────

    def _on_delete(self):
        row = self.selected_row()
        if row is None:
            return
        reply = QMessageBox.question(
            self, self.t("hostkey.manager_delete"),
            self.t("hostkey.manager_confirm_delete", host=row["host"], keytype=row["keytype"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.store.remove(row["host"], row["keytype"]):
            self.status.setText(self.t("hostkey.manager_deleted", host=row["host"]))
        else:
            self.status.setText(self.t("hostkey.manager_delete_failed", path=self.store.path))
        self.refresh()

    def _on_replace(self):
        row = self.selected_row()
        if row is None:
            return
        host, port = _split_entry(row["host"])
        self.btn_replace.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.status.setText(self.t("hostkey.manager_probing", host=host))
        self._probe = _HostKeyProbe(host, port, self)
        self._probe.probed.connect(self._on_probed)
        self._probe.finished.connect(self._on_probe_done)
        self._probe.start()

    def _on_probe_done(self):
        self._probe = None
        self.btn_refresh.setEnabled(True)
        self._sync_buttons()

    def _on_probed(self, key, error):
        row = self.selected_row()
        if row is None:
            return
        host, _port = _split_entry(row["host"])
        if key is None:
            self.status.setText("")
            QMessageBox.warning(self, self.t("hostkey.manager_replace"),
                                self.t("hostkey.manager_probe_failed",
                                       host=host, port=_split_entry(row["host"])[1], error=error))
            return
        fresh = _hkp.fingerprint(key)
        if fresh == row["fingerprint"]:
            self.status.setText(self.t("hostkey.manager_unchanged"))
            return
        reply = QMessageBox.question(
            self, self.t("hostkey.manager_replace"),
            self.t("hostkey.manager_confirm_replace", host=row["host"],
                   keytype=key.get_name(), old=row["fingerprint"], new=fresh),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            self.status.setText("")
            return
        if self.store.pin(row["host"], key.get_name(), key):
            self.status.setText(self.t("hostkey.manager_replaced", host=row["host"]))
        else:
            self.status.setText(self.t("hostkey.manager_delete_failed", path=self.store.path))
        self.refresh()

    def closeEvent(self, event):
        """A probe outlives nothing: the thread is bounded by its own socket timeout."""
        probe = self._probe
        if probe is not None and probe.isRunning():
            probe.wait(int((PROBE_TIMEOUT_S + 2) * 1000))
        event.accept()


def _split_entry(entry_name: str):
    """`[host]:port` / `host` → `(host, port)` — the ONE reader of the store's entry spelling."""
    text = str(entry_name or "")
    if text.startswith("[") and "]:" in text:
        host, _, port = text[1:].partition("]:")
        try:
            return host, int(port)
        except ValueError:
            return host, 22
    return text, 22
