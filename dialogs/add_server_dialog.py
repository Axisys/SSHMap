import uuid
from typing import Optional, List

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from ..models.profile import load_profiles, get_profile_by_id
except ImportError:
    from models.profile import load_profiles, get_profile_by_id

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QSpinBox,
    QFileDialog, QDialogButtonBox, QHBoxLayout, QVBoxLayout,
    QLabel, QComboBox,
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
                        else "(ручной ввод)")
        self.profile_combo.addItem(manual_label)
        for p in self._profiles:
            self.profile_combo.addItem(p["name"])
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        btn_manage_profiles = QPushButton(
            (self.t("profile.manage_button") if self._i18n_available
             else "Управление профилями…"))  # UI polish: без эмодзи
        btn_manage_profiles.clicked.connect(self._open_profile_manager)

        combo_hbox = QHBoxLayout()
        combo_hbox.addWidget(self.profile_combo)
        combo_hbox.addStretch()
        combo_hbox.addWidget(btn_manage_profiles)

        label_text = (self.t("profile.select_profile_hint") if self._i18n_available
                      else "Выберите профиль для автозаполнения логина и пароля:")
        profile_section.addRow("", QLabel(label_text))
        if self._i18n_available:
            try:
                from i18n import t as __t2
                self.profile_label = QLabel(__t2("profile.selector_label"))
                profile_section.addRow("", self.profile_label)
            except Exception:
                pass
        profile_section.addRow("", combo_hbox)

        main_layout.addLayout(profile_section)

        # Separator
        sep = QLabel("─" * 50)
        sep.setStyleSheet("color: #334155;")
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
        layout.addRow(self.t("server.user"), self.user)
        layout.addRow(self.t("server.password"), self.password)
        layout.addRow(self.t("server.port"), self.port)

        # Key path button (UI polish: эмодзи из значения i18n server.key убраны)
        key_btn = QPushButton(self.t("server.key"))
        key_btn.clicked.connect(self._select_key_file)
        key_hbox = QHBoxLayout()
        key_hbox.addWidget(self.key_path)
        key_hbox.addWidget(key_btn)
        layout.addRow("", key_hbox)

        self.os_name = QLineEdit()  # v0.9: ОС (вручную или из автосбора)
        self.cpu = QLineEdit()
        self.ram = QLineEdit()
        self.disk = QLineEdit()
        self.ip = QLineEdit()
        self.comment = QLineEdit()
        # v0.9.4: теги — ввод через запятую («prod, web»); парсинг в get_data()
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

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        main_layout.addWidget(btns)

    def _on_ok(self):
        """Валидация перед закрытием: host обязателен."""
        if not self.host.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.t("msg.error_title"), self.t("validation.empty_host"))
            return
        self.accept()

    def _on_profile_changed(self, index: int):
        """When user selects a profile from the combo → auto-fill user + password."""
        if index <= 0 or not self._profiles:
            return  # "(ручной ввод)" selected, keep current values
        profile = self._profiles[index - 1]  # offset by 1 because of "(ручной ввод)" item
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
        self.password.setText(d.password)  # loaded from server JSON (plain text for server creds)
        self.port.setValue(d.ssh_port or 22)
        self.key_path.setText(d.key_path or "")
        self.os_name.setText(d.os_name)  # v0.9
        self.cpu.setText(d.cpu)
        self.ram.setText(d.ram)
        self.disk.setText(d.disk)
        self.ip.setText(d.ip)
        self.comment.setText(d.comment)
        self.tags_edit.setText(", ".join(getattr(d, "tags", None) or []))  # v0.9.4

        # Try to match current user against loaded profiles and auto-select
        self._ensure_profiles_loaded()
        for i, p in enumerate(self._profiles):
            if p["user"] == d.user:
                self.profile_combo.setCurrentIndex(i + 1)  # +1 because "(ручной ввод)" is index 0
                break

    def get_data(self) -> ServerData:
        sid = self._data.id if self._data else str(uuid.uuid4())[:8]
        return ServerData(
            id=sid,
            alias=self.alias.text() or "Server",
            host=self.host.text(),
            user=self.user.text(),
            password=self.password.text(),  # plaintext from UI (server credentials are per-server)
            key_path=self.key_path.text(),
            ssh_port=self.port.value(),
            x=self._data.x if self._data else 0,
            y=self._data.y if self._data else 0,
            os_name=self.os_name.text(),  # v0.9
            cpu_model=getattr(self._data, "cpu_model", "") if self._data else "",
            cpu=self.cpu.text(),
            ram=self.ram.text(),
            disk=self.disk.text(),
            ip=self.ip.text(),
            comment=self.comment.text(),
            tags=self._parse_tags(),  # v0.9.4
        )

    def _parse_tags(self) -> list:
        """v0.9.4: строку «prod, web» → ['prod', 'web'] (дубликаты/пустые долой)."""
        seen, out = set(), []
        for part in self.tags_edit.text().split(","):
            tag = part.strip()
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                out.append(tag)
        return out
