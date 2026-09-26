import uuid
from typing import Optional, List

try:
    from ..models.server import ServerData, sanitize_quick_launch
except ImportError:
    from models.server import ServerData, sanitize_quick_launch

try:
    from ..models.profile import load_profiles, get_profile_by_id
except ImportError:
    from models.profile import load_profiles, get_profile_by_id

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.6.5 (ROADMAP task 4): the ONE gate of an unmanaged card
    from ..ui.unmanaged import refusal_text as _refusal_text
except ImportError:
    try:
        from ui.unmanaged import refusal_text as _refusal_text
    except ImportError:  # flat layout without ui/unmanaged — the dialog still opens
        _refusal_text = None

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QSpinBox,
    QFileDialog, QDialogButtonBox, QHBoxLayout, QVBoxLayout,
    QLabel, QComboBox, QCheckBox,
)


class AddServerDialog(QDialog):
    def __init__(self, parent=None, edit_data: Optional[ServerData] = None):
        super().__init__(parent)
        
        # ── i18n support ────────────────────────────────
        self._i18n_available = False
        
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()  # Use already-set global language (restored from config)
            self._i18n_available = True
            
            if edit_data is None:
                self.setWindowTitle(__t("dialog.add_server"))
            else:
                self.setWindowTitle(__t("dialog.properties"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop

        self.setMinimumWidth(420)
        self._data = edit_data
        # v0.9.5.6: True after the "Connect via SSH" click — the data is saved
        # (as with OK) and MainWindow then opens the SSH dialog.
        self._connect_after_accept = False
        # v1.0RC4: Quick launch — the current list of entries (source of truth for
        # get_data()); initialized from edit_data, otherwise editing OTHER fields
        # of the server would reset the configured entries (ServerData.quick_launch).
        self._quick_launch_entries = [dict(e) for e in sanitize_quick_launch(
            getattr(edit_data, "quick_launch", None))] if edit_data is not None else []
        # v1.6.5 (ROADMAP task 1): the KNOB of the unmanaged card. The checkbox owns the
        # visible state; `_credential_stash` keeps what the disabled credential fields held
        # so that unchecking the box really gives them BACK (clearing without a stash would
        # silently destroy what the user had already typed).
        self._credential_stash: Optional[dict] = None
        # v1.6.5 (ROADMAP task 5): the OPT-IN ICMP check of an unmanaged card — it is only
        # meaningful while the box above is ticked, and it is OFF for a new card.
        self._unmanaged_ping_enabled = False
        
        # ── Profile data (loaded lazily, cached in instance) ──
        # Each entry: {"id": str, "name": str} — password fetched from keyring on demand
        self._profiles: List[dict] = []

        self._build_ui()
        if edit_data:
            self._load_data(edit_data)

    def _ensure_profiles_loaded(self):
        """Load profiles into cache once (without passwords)."""
        if not self._profiles:
            for p in load_profiles():
                self._profiles.append({
                    "id": p.id,
                    "name": f"{p.name} ({p.user})",
                    "user": p.user,
                    # password intentionally NOT stored here — fetched from keyring on demand
                })

    def _get_profile_password(self, profile_id: str) -> Optional[str]:
        """Fetch the password for a profile from keyring."""
        try:
            full = get_profile_by_id(profile_id)
            return getattr(full, 'password', None) if full else None
        except Exception:
            return None

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # ── Profile selector (top section) ──
        # Load profiles FIRST so they are available for the combo box.
        self._ensure_profiles_loaded()

        profile_section = QFormLayout()

        # Create the profile combo once — always visible, regardless of i18n.
        self.profile_combo = QComboBox()
        manual_label = (self.t("profile.manual_input") if self._i18n_available
                        else "(manual input)")
        self.profile_combo.addItem(manual_label)
        for p in self._profiles:
            self.profile_combo.addItem(p["name"])
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        btn_manage_profiles = QPushButton(
            (self.t("profile.manage_button") if self._i18n_available
             else "Manage Profiles…"))  # UI polish: no emojis
        btn_manage_profiles.clicked.connect(self._open_profile_manager)

        combo_hbox = QHBoxLayout()
        combo_hbox.addWidget(self.profile_combo)
        combo_hbox.addStretch()
        combo_hbox.addWidget(btn_manage_profiles)

        label_text = (self.t("profile.select_profile_hint") if self._i18n_available
                      else "Select profile for auto-fill login and password:")
        profile_section.addRow("", QLabel(label_text))
        if self._i18n_available:
            try:
                from i18n import t as __t2
                self.profile_label = QLabel(__t2("profile.selector_label"))
                profile_section.addRow("", self.profile_label)
            except Exception:
                pass
        profile_section.addRow("", combo_hbox)

        # v1.0RC4: Quick launch — under the "Manage profiles…" button (naming
        # decision: the button repeats the context-menu item name instead of the
        # abstract "Settings" — 1:1 with the "Quick launch" submenu).
        btn_quick_launch = QPushButton(
            (self.t("ql.configure_button") if self._i18n_available
             else "Quick Launch…"))  # UI polish: no emojis
        btn_quick_launch.clicked.connect(self._open_quick_launch)
        profile_section.addRow("", btn_quick_launch)

        main_layout.addLayout(profile_section)

        # Separator (v1.2.5: color — from the central theme ui/theme.py)
        sep = QLabel("─" * 50)
        sep.setStyleSheet(f"color: {theme.SURFACE_ALT};")
        main_layout.addWidget(sep)
        main_layout.addSpacing(6)

        # ── Server properties form ──
        layout = QFormLayout()

        self.alias = QLineEdit()
        self.host = QLineEdit()
        self.user = QLineEdit()  # auto-filled from profile, editable for manual override
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.key_path = QLineEdit()
        self.port = QSpinBox()
        self.port.setValue(22)
        self.port.setRange(1, 65535)

        layout.addRow(self.t("server.alias"), self.alias)
        layout.addRow(self.t("server.host"), self.host)

        # v1.6.5 (ROADMAP tasks 1/5): the KIND of the card and its ONE opt-in.
        # "Unmanaged server (no SSH access)": the card describes a box this user does not
        # administer, so the credential fields below are disabled AND cleared, the keyring
        # is never written for it and no SSH verb reaches it (the gate of `ui/unmanaged.py`).
        # The second box is the reachability check — DEFAULT OFF, and meaningful only while
        # the first one is ticked (with it off no network call happens for the card at all).
        self.unmanaged = QCheckBox(
            self.t("dialog.unmanaged") if self._i18n_available
            else "Unmanaged server (no SSH access)")
        self.unmanaged.setToolTip(
            self.t("dialog.unmanaged.tooltip") if self._i18n_available
            else "No credentials are stored, the card is never probed and its menu has no SSH verbs.")
        self.unmanaged.toggled.connect(self._on_unmanaged_toggled)
        layout.addRow("", self.unmanaged)

        self.unmanaged_ping = QCheckBox(
            self.t("dialog.unmanaged_ping") if self._i18n_available
            else "Allow a reachability check (ping)")
        self.unmanaged_ping.setToolTip(
            self.t("dialog.unmanaged_ping.tooltip") if self._i18n_available
            else "One ICMP ping, on request, from the card's menu. The answer is a manual note — never a status.")
        layout.addRow("", self.unmanaged_ping)

        layout.addRow(self.t("server.user"), self.user)
        layout.addRow(self.t("server.password"), self.password)
        layout.addRow(self.t("server.port"), self.port)

        # Key path button (UI polish: emojis removed from the i18n server.key value)
        key_btn = QPushButton(self.t("server.key"))
        key_btn.clicked.connect(self._select_key_file)
        self.key_btn = key_btn   # v1.6.5: the credential family is disabled as ONE group
        key_hbox = QHBoxLayout()
        key_hbox.addWidget(self.key_path)
        key_hbox.addWidget(key_btn)
        layout.addRow("", key_hbox)

        self.os_name = QLineEdit()  # v0.9: OS (manual or auto-collected)
        self.cpu = QLineEdit()
        self.ram = QLineEdit()
        self.disk = QLineEdit()
        self.ip = QLineEdit()
        self.comment = QLineEdit()
        # v0.9.4: tags — comma-separated input ("prod, web"); parsed in get_data()
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(
            self.t("server.tags_hint") if self._i18n_available else "prod, staging, dev")

        layout.addRow(self.t("server.os"), self.os_name)
        layout.addRow(self.t("server.cpu"), self.cpu)
        layout.addRow(self.t("server.ram"), self.ram)
        layout.addRow(self.t("server.disk"), self.disk)
        layout.addRow(self.t("server.ip"), self.ip)
        layout.addRow(self.t("server.comment"), self.comment)
        layout.addRow(self.t("server.tags") if self._i18n_available else "Tags:", self.tags_edit)

        main_layout.addLayout(layout)

        # v0.9.5.6: "Connect via SSH" button — on the left; OK/Cancel — on the right
        # (QDialogButtonBox keeps the standard order).
        btn_row = QHBoxLayout()
        self.ssh_connect_btn = QPushButton(
            self.t("ssh.connect") if self._i18n_available else "Connect via SSH")
        self.ssh_connect_btn.clicked.connect(self._on_connect_ssh)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)

        btn_row.addWidget(self.ssh_connect_btn)
        btn_row.addStretch()
        btn_row.addWidget(btns)
        main_layout.addLayout(btn_row)

        # v1.6.5 (ROADMAP tasks 1/5): the FORM opens in the state the two checkboxes say —
        # a NEW card is managed, so the credential family is editable and the opt-in ping is
        # disabled (it only means something for an unmanaged card). Applied ONCE here, after
        # every widget the state touches exists; `_load_data()` re-applies it for an edit.
        self._apply_unmanaged_state(self.unmanaged.isChecked())

    def _on_unmanaged_toggled(self, checked: bool) -> None:
        """v1.6.5 (ROADMAP task 1): the kind of the card changed.

        Ticking the box TAKES the credentials away — the four fields are cleared (they
        would otherwise be written to the keyring by the save path) and kept in
        `_credential_stash`; unticking it GIVES THEM BACK, so a user who ticked the box by
        accident loses nothing. The disabling itself is `_apply_unmanaged_state()`.
        """
        checked = bool(checked)
        if checked:
            self._credential_stash = {
                "user": self.user.text(),
                "password": self.password.text(),
                "key_path": self.key_path.text(),
                "port": self.port.value(),
            }
            self.user.clear()
            self.password.clear()
            self.key_path.clear()
            self.port.setValue(22)
        elif self._credential_stash is not None:
            stash = self._credential_stash
            self._credential_stash = None
            self.user.setText(stash.get("user", ""))
            self.password.setText(stash.get("password", ""))
            self.key_path.setText(stash.get("key_path", ""))
            try:
                self.port.setValue(int(stash.get("port", 22) or 22))
            except (TypeError, ValueError):
                self.port.setValue(22)
        self._apply_unmanaged_state(checked)

    def _apply_unmanaged_state(self, checked: bool) -> None:
        """Reflect the flag in the FORM: the credential family off, the opt-in usable.

        The rule is ONE state for the whole credential family (user / password / port /
        private key + the key picker) plus the profile selector, which exists to auto-fill
        exactly those two fields; the reachability checkbox is enabled by the flag and
        starts OFF, and the dialog's own "Connect via SSH" door is closed with the SAME
        refusal sentence the menus use (the gate's ONE wording).
        """
        for widget in (getattr(self, "user", None), getattr(self, "password", None),
                       getattr(self, "port", None), getattr(self, "key_path", None),
                       getattr(self, "key_btn", None), getattr(self, "profile_combo", None)):
            if widget is None:
                continue
            try:
                widget.setEnabled(not checked)
            except RuntimeError:
                pass  # Qt teardown — the widget is already destroyed
        ping_box = getattr(self, "unmanaged_ping", None)
        if ping_box is not None:
            try:
                ping_box.setEnabled(checked)
                if not checked:
                    ping_box.setChecked(False)   # a managed card has no opt-in to grant
            except RuntimeError:
                pass
        button = getattr(self, "ssh_connect_btn", None)
        if button is not None:
            label = self.t("ssh.connect") if self._i18n_available else "Connect via SSH"
            try:
                button.setEnabled(not checked)
                button.setToolTip(self._refusal(label) if checked else "")
            except RuntimeError:
                pass

    def _refusal(self, label: str) -> str:
        """The refusal sentence of a closed door (the gate's ONE template; "" — no i18n)."""
        if _refusal_text is None:
            return ""
        return _refusal_text(self.t, label)

    def _on_ok(self):
        """Validate before closing: host is required."""
        if not self.host.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.t("msg.error_title"), self.t("validation.empty_host"))
            return
        self.accept()

    def _on_connect_ssh(self):
        """v0.9.5.6: "Connect via SSH" — save the data and open the SSH dialog.

        Same validation as OK (host is required); the _connect_after_accept flag
        is read by MainWindow after accept() — it triggers the connection.
        """
        if not self.host.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.t("msg.error_title"), self.t("validation.empty_host"))
            return
        self._connect_after_accept = True
        self.accept()

    def _on_profile_changed(self, index: int):
        """When user selects a profile from the combo → auto-fill user + password."""
        if index <= 0 or not self._profiles:
            return  # manual-input item selected, keep current values
        # v1.6.5 (ROADMAP task 1): an unmanaged card has no credentials to fill in — the
        # selector is disabled for it, and this guard keeps a programmatic setCurrentIndex
        # from sneaking a login into the two fields.
        if self.unmanaged.isChecked():
            return
        profile = self._profiles[index - 1]  # offset by 1 because of the manual-input item
        self.user.setText(profile["user"])
        # Fetch password from keyring (not stored in plain dict)
        pw = self._get_profile_password(profile["id"])
        if pw:
            self.password.setText(pw)

    def _open_profile_manager(self):
        """Open the Profile Manager dialog."""
        try:
            from ..dialogs.profile_manager_dialog import ProfileManagerDialog
        except ImportError:
            from dialogs.profile_manager_dialog import ProfileManagerDialog

        dlg = ProfileManagerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            # Refresh profiles list after manager closes (user may have added/edited/deleted)
            self._profiles.clear()
            for p in load_profiles():
                self._profiles.append({
                    "id": p.id,
                    "name": f"{p.name} ({p.user})",
                    "user": p.user,
                })
            # Rebuild combo
            old_current = self.profile_combo.currentIndex()
            self.profile_combo.clear()
            self.profile_combo.addItem(self.t("profile.manual_input"))
            for prof in self._profiles:
                self.profile_combo.addItem(prof["name"])
            # Restore selection if possible
            if old_current > 0 and old_current - 1 < len(self._profiles):
                self.profile_combo.setCurrentIndex(old_current)

    def _open_quick_launch(self):
        """v1.0RC4: open the Quick launch configuration dialog for this server.

        Works when adding a new server too (edit_data=None — empty list);
        the result is stored in self._quick_launch_entries and flows into get_data().
        """
        try:
            from ..dialogs.quick_launch_dialog import QuickLaunchDialog
        except ImportError:
            from dialogs.quick_launch_dialog import QuickLaunchDialog

        dlg = QuickLaunchDialog(self, server_data=self._data)
        if dlg.exec() == QDialog.Accepted:
            self._quick_launch_entries = [dict(e) for e in dlg.get_entries()]

    def _select_key_file(self):
        """Open file dialog to select SSH key."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.select_key"), "", 
            "SSH Keys (*.pem *.key *.ppk);;" + self.t("filter.all_files")
        )
        if path:
            self.key_path.setText(path)

    def _load_data(self, d: ServerData):
        self.alias.setText(d.alias)
        self.host.setText(d.host)
        self.user.setText(d.user)
        self.password.setText(d.password)  # password loaded via CredentialManager (keyring); never stored in JSON
        self.port.setValue(d.ssh_port or 22)
        self.key_path.setText(d.key_path or "")
        self.os_name.setText(d.os_name)  # v0.9
        self.cpu.setText(d.cpu)
        self.ram.setText(d.ram)
        self.disk.setText(d.disk)
        self.ip.setText(d.ip)
        self.comment.setText(d.comment)
        self.tags_edit.setText(", ".join(getattr(d, "tags", None) or []))  # v0.9.4

        # v1.6.5 (ROADMAP tasks 1/5): the kind of the card. The box is set BEFORE the state
        # is applied (a programmatic setChecked fires `toggled`, which would stash and clear
        # the credentials that `_load_data` has just put in — so the stash is discarded and
        # the state applied ONCE, explicitly, after the two flags are in).
        self.unmanaged.setChecked(bool(getattr(d, "unmanaged", False)))
        self._credential_stash = None
        self.unmanaged_ping.setChecked(bool(getattr(d, "unmanaged", False))
                                      and bool(getattr(d, "unmanaged_ping", False)))
        self._apply_unmanaged_state(self.unmanaged.isChecked())

        # Try to match current user against loaded profiles and auto-select
        self._ensure_profiles_loaded()
        for i, p in enumerate(self._profiles):
            if p["user"] == d.user:
                self.profile_combo.setCurrentIndex(i + 1)  # +1 because the manual-input item is index 0
                break

    def get_data(self) -> ServerData:
        sid = self._data.id if self._data else str(uuid.uuid4())[:8]
        # v1.6.5 (ROADMAP tasks 1/5): an UNMANAGED card carries NO credentials and NO port
        # of its own, whatever the widgets happen to hold (they are disabled and cleared,
        # but a programmatic path must not be able to sneak a login into the model — the
        # save path writes `node.data.password` into the keyring). The opt-in ICMP flag is
        # read only for such a card: a managed one has no exception to grant.
        unmanaged = bool(self.unmanaged.isChecked())
        return ServerData(
            id=sid,
            # v1.2.10 (manual AUDIT #3): validation checks non-emptiness AFTER strip, while the value
            # was saved with spaces — a terminal connection to " 192.168.1.5" failed on DNS
            # (terminal_page.py passes host as-is); the same fix also closes the SystemInfoCollector path.
            alias=self.alias.text().strip() or "Server",
            host=self.host.text().strip(),
            user="" if unmanaged else self.user.text().strip(),
            password="" if unmanaged else self.password.text(),  # plaintext from UI (server credentials are per-server)
            key_path="" if unmanaged else self.key_path.text(),
            ssh_port=22 if unmanaged else self.port.value(),
            x=self._data.x if self._data else 0,
            y=self._data.y if self._data else 0,
            # v1.0-fix (audit #1): collapsed was not passed earlier — in a new ServerData
            # it was always False, and any edit via "Properties" (even without changing
            # a single field) silently expanded a collapsed node.
            collapsed=self._data.collapsed if self._data else False,
            os_name=self.os_name.text(),  # v0.9
            cpu_model=getattr(self._data, "cpu_model", "") if self._data else "",
            cpu=self.cpu.text(),
            ram=self.ram.text(),
            disk=self.disk.text(),
            ip=self.ip.text(),
            comment=self.comment.text(),
            tags=self._parse_tags(),  # v0.9.4
            quick_launch=[dict(e) for e in self._quick_launch_entries],  # v1.0RC4
            unmanaged=unmanaged,  # v1.6.5
            unmanaged_ping=bool(unmanaged and self.unmanaged_ping.isChecked()),  # v1.6.5
        )

    def _parse_tags(self) -> list:
        """v0.9.4: "prod, web" string → ['prod', 'web'] (duplicates/empties removed)."""
        seen, out = set(), []
        for part in self.tags_edit.text().split(","):
            tag = part.strip()
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                out.append(tag)
        return out
