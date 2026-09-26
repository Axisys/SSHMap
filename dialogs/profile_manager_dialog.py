"""Profile Manager Dialog — manage reusable SSH profiles (login + password).

Access via Menu → Profiles → Manage profiles.
"""

from typing import Optional

try:
    from ..models.profile import (Profile, load_profiles, add_profile,
                                  update_profile, delete_profile, get_profile_password)
except ImportError:
    from models.profile import (Profile, load_profiles, add_profile,
                                update_profile, delete_profile, get_profile_password)

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QLabel, QMessageBox, QLineEdit, QDialogButtonBox,
    QHeaderView,
)


#: The FIXED mask of a stored password in the profile table (v1.6.1, ROADMAP task 6).
#: The cell still answers "a password is stored"; it deliberately does NOT answer HOW
#: LONG it is — `"•" * len(password)` put the length of a keyring secret on the screen
#: (and into every screenshot of the dialog), which the value mask alone cannot undo.
PASSWORD_MASK = "•" * 8


def password_cell_text(password, translate_fn=None) -> str:
    """The password cell of ONE profile row (pure): the FIXED mask, or the "none" caption.

    The same caption for every stored password — the length is not a readable fact here.
    """
    if password:
        return PASSWORD_MASK
    return translate_fn("profile.password_empty") if translate_fn else "(empty)"


class ProfileManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # ── i18n support ────────────────────────────────
        self._i18n_available = False
        
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()  # Use already-set global language (restored from config)
            self._i18n_available = True
            
            self.setWindowTitle(__t("dialog.manage_profiles"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
        
        self.setMinimumSize(520, 480)
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel(self.t("dialog.manage_profiles")) if self._i18n_available else QLabel("Manage SSH Profiles")
        title.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {theme.TEXT_PRIMARY};")  # v1.2.5: theme
        layout.addWidget(title)

        subtitle = QLabel(self.t("dialog.manage_profiles_desc")) if self._i18n_available else QLabel(
            "Profiles store a login/password pair and can be applied\n"
            "with one click to server properties."
        )
        subtitle.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 10pt;")  # v1.2.5: theme
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        
        if self._i18n_available:
            try:
                from i18n import t as __t
                self.table.setHorizontalHeaderLabels([__t("profile.name"), __t("server.user"), __t("server.password")])
            except Exception:
                pass
        
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)  # read-only, edit via buttons
        layout.addWidget(self.table)

        # Buttons row
        btn_layout = QHBoxLayout()

        # UI polish: emojis removed from the i18n dialog.* values — no prefixes added
        self.btn_add = QPushButton(self.t("dialog.add_profile") if self._i18n_available else "Add")
        self.btn_add.clicked.connect(lambda: self._on_edit_profile(None))

        self.btn_edit = QPushButton(self.t("dialog.edit_profile") if self._i18n_available else "Edit")
        self.btn_edit.clicked.connect(self._on_edit_selected)
        self.btn_edit.setEnabled(False)

        self.btn_delete = QPushButton(self.t("dialog.delete_profile") if self._i18n_available else "Delete")
        self.btn_delete.clicked.connect(self._on_delete_selected)
        self.btn_delete.setEnabled(False)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_edit)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Close button
        close_btn = QPushButton((self.t("ssh.cancel") if self._i18n_available else "Cancel"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        # Selection change handler — use itemClicked as reliable alternative
        self.table.itemClicked.connect(self._on_item_clicked)

    def _on_item_clicked(self, item: QTableWidgetItem):
        """Handle item click to enable/disable edit/delete buttons."""
        row = item.row()
        enabled = row >= 0
        self.btn_edit.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def refresh_table(self):
        profiles = load_profiles()
        self.table.setRowCount(len(profiles))
        for i, p in enumerate(profiles):
            name_item = QTableWidgetItem(p.name)
            user_item = QTableWidgetItem(p.user)
            # The password lives in the keyring — loaded for display only (masked).
            # v1.6.1 (task 6): a FIXED mask — the cell never reports the length.
            pw = get_profile_password(p.id) or ""
            pw_display = password_cell_text(pw, self.t)
            password_item = QTableWidgetItem(pw_display)
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, user_item)
            self.table.setItem(i, 2, password_item)

    def _on_edit_selected(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return
        profiles = load_profiles()
        profile = profiles[selected_row]
        self._on_edit_profile(profile)

    def _on_edit_profile(self, profile: Optional[Profile]):
        """Open the add/edit dialog for a single profile."""
        dlg = ProfileEditDialog(self, existing=profile)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_table()

    def _on_delete_selected(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return
        profiles = load_profiles()
        profile = profiles[selected_row]
        
        if self._i18n_available:
            try:
                # v1.1.2RC2 (N10): its own key for deleting a PROFILE — earlier this used
                # the server msg.confirm_delete ("Delete server ...?"), a crooked i18n branch.
                reply = QMessageBox.question(
                    self, (self.t("dialog.delete_profile") if self._i18n_available else "Delete"),
                    self.t("msg.confirm_delete_profile", alias=profile.name),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
            except Exception:
                reply = QMessageBox.question(
                    self, "Delete",
                    f"Delete profile '{profile.name}'? (Login {profile.user})",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
        else:
            reply = QMessageBox.question(
                self, "Delete",
                f"Delete profile '{profile.name}'? (Login {profile.user})",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
        if reply == QMessageBox.Yes:
            delete_profile(profile.id)
            self.refresh_table()

    def get_selected_profile(self) -> Optional[Profile]:
        """Return the currently selected profile from the table."""
        row = self.table.currentRow()
        if row < 0:
            return None
        profiles = load_profiles()
        return profiles[row] if row < len(profiles) else None


class ProfileEditDialog(QDialog):
    """Small dialog to add or edit a single profile."""

    def __init__(self, parent=None, existing: Optional[Profile] = None):
        super().__init__(parent)
        
        # ── i18n support ────────────────────────────────
        self._i18n_available = False
        
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()  # Use already-set global language (restored from config)
            self._i18n_available = True
            
            if existing is None:
                self.setWindowTitle(__t("dialog.add_profile"))
            else:
                self.setWindowTitle(__t("dialog.edit_profile"))
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
        
        self.existing = existing
        self.setMinimumWidth(360)
        
        # Set title based on edit vs add mode
        if existing is None:
            self.setWindowTitle(self.t("dialog.add_profile"))
        else:
            self.setWindowTitle(self.t("dialog.edit_profile"))
            
        self._build_ui()
        if existing:
            self.name_edit.setText(existing.name)
            self.user_edit.setText(existing.user)
            # The password is NOT prefilled: an empty field means "keep the current password"
            self.password_edit.setPlaceholderText(self.t("profile.password_keep_hint"))

    def _build_ui(self):
        layout = QVBoxLayout(self)

        name_label = QLabel((self.t("profile.name") if self._i18n_available else "Profile name:"))
        layout.addWidget(name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("admin, dev-team, production...")
        layout.addWidget(self.name_edit)

        user_label = QLabel((self.t("profile.username_label") if self._i18n_available else "SSH user (login):"))
        layout.addWidget(user_label)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("root, ubuntu, deploy...")
        layout.addWidget(self.user_edit)

        pw_label = QLabel((self.t("profile.password_optional") if self._i18n_available else "Password (optional):"))
        layout.addWidget(pw_label)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_edit)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_ok(self):
        name = self.name_edit.text().strip()
        user = self.user_edit.text().strip()
        password = self.password_edit.text()

        if not name:
            QMessageBox.warning(self, (self.t("msg.error_title") if self._i18n_available else "Error"), 
                              self.t("validation.name_empty"))
            return
        if not user:
            QMessageBox.warning(self, (self.t("msg.error_title") if self._i18n_available else "Error"), 
                              self.t("validation.user_empty"))
            return

        if self.existing is None:
            add_profile(name=name, user=user, password=password)
        else:
            # Empty field = "keep" (None), so we don't wipe the password from the keyring
            update_profile(
                profile_id=self.existing.id,
                name=name,
                user=user,
                password=None if password == "" else password
            )
        self.accept()
