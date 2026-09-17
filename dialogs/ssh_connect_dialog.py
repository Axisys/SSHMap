

import sys
from typing import Optional, List, Dict

try:
    from ..models.server import ServerData
except ImportError:
    from models.server import ServerData

try:
    from ..modules.ssh_worker import SSHWorker
except ImportError:
    from modules.ssh_worker import SSHWorker

try:
    from ..models.profile import load_profiles as _load_profiles, get_profile_by_id as _get_pw
except ImportError:
    from models.profile import load_profiles as _load_profiles, get_profile_by_id as _get_pw

try:  # v1.2.5: central theme (palette/radii/fonts — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QFormLayout, QLineEdit, QSpinBox,
    QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QComboBox,
)
from PySide6.QtCore import QCoreApplication, QEventLoop as _QEL  # v0.9.4-fix: non-blocking close


class SSHConnectDialog(QDialog):
    """SSH connection dialog with profile auto-fill support."""
    
    # ── i18n helper ─────────────────────────────────────────────
    _i18n_available = False
    
    def __init__(self, server_data: ServerData, parent=None):
        super().__init__(parent)
        
        self._i18n_available = False
        
        try:
            from i18n import get_current_language as _get_lang, t as __t
            self.t = __t
            self.current_language = _get_lang()  # Use already-set global language (restored from config)
            self._i18n_available = True
            
            title = __t("dialog.ssh_connect").format(alias=server_data.alias)
            self.setWindowTitle(title)
        except Exception:
            def _noop(key, **kwargs):
                return key.format(**kwargs) if kwargs else key
            self.t = _noop
        
        self.resize(420, 430)  # v0.9.9.2: + "External terminal" section
        self.server_data = server_data
        self._ssh_worker: Optional[SSHWorker] = None
        # Profiles cached without passwords — fetched from keyring on demand
        self._profiles: List[Dict[str, str]] = []

        self._build_ui()

    def _ensure_profiles_loaded(self):
        """Load profiles into cache once (without passwords)."""
        if not self._profiles:
            for p in _load_profiles():
                self._profiles.append({
                    "id": p.id,
                    "name": f"{p.name} ({p.user})",
                    "user": p.user,
                    # password intentionally NOT stored here — fetched from keyring on demand
                })

    def _get_profile_password(self, profile_id: str) -> Optional[str]:
        """Fetch the password for a profile from keyring."""
        try:
            full = _get_pw(profile_id)
            return getattr(full, 'password', None) if full else None
        except Exception:
            return None

    def _build_ui(self):
        # Load profiles BEFORE building the UI so the combo box is populated
        self._ensure_profiles_loaded()

        layout = QVBoxLayout(self)

        # ── Profile selector (top section) ──
        profile_section = QFormLayout()

        if self._i18n_available:
            try:
                from i18n import t as __t
                self.profile_label = QLabel(__t("profile.selector_label"))
                self.profile_combo = QComboBox()
                self.profile_combo.addItem(self.t("profile.manual_input"))
                for p in self._profiles:
                    self.profile_combo.addItem(p["name"])
                self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

                btn_manage_profiles = QPushButton(__t("profile.manage_button"))
                btn_manage_profiles.clicked.connect(self._open_profile_manager)

                combo_hbox = QHBoxLayout()
                combo_hbox.addWidget(self.profile_combo)
                combo_hbox.addStretch()
                combo_hbox.addWidget(btn_manage_profiles)

                profile_section.addRow("", QLabel(self.t("profile.select_profile_hint")))
                profile_section.addRow("", self.profile_label)
                profile_section.addRow("", combo_hbox)
            except Exception:
                pass
        
        if not hasattr(self, 'profile_combo') or self.profile_combo is None:
            # Fallback UI without i18n
            self.profile_combo = QComboBox()
            self.profile_combo.addItem("(manual input)")
            btn_manage_profiles = QPushButton("Manage Profiles…")  # UI polish: no emojis
            btn_manage_profiles.clicked.connect(self._open_profile_manager)

            combo_hbox = QHBoxLayout()
            combo_hbox.addWidget(self.profile_combo)
            combo_hbox.addStretch()
            combo_hbox.addWidget(btn_manage_profiles)
            profile_section.addRow("", combo_hbox)

        layout.addLayout(profile_section)

        # Separator (v1.2.5: colors — from the central theme ui/theme.py)
        sep = QLabel("─" * 50)
        sep.setStyleSheet(f"color: {theme.SURFACE_ALT};")
        layout.addWidget(sep)
        layout.addSpacing(6)

        # ── Server info (read-only) ──
        info_text = f"{self.t('ssh.server_info')} {self.server_data.host}"
        info_label = QLabel(f"<b>{info_text}</b>")
        info_label.setStyleSheet(f"font-weight: bold; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(info_label)

        # ── Auth form ──
        form_layout = QFormLayout()

        self.user_edit = QLineEdit(self.server_data.user)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.key_path_edit = QLineEdit(self.server_data.key_path)
        self.port_edit = QSpinBox()
        self.port_edit.setValue(self.server_data.ssh_port or 22)
        self.port_edit.setRange(1, 65535)

        form_layout.addRow(self.t("ssh.username_label"), self.user_edit)
        form_layout.addRow(self.t("ssh.password_label"), self.password_edit)
        form_layout.addRow(self.t("ssh.port_label"), self.port_edit)

        # UI polish: emojis removed from the i18n values (server.key, ssh.connect, ssh.test);
        # don't add them in the code — there was a duplication bug ("🔑 🔑 SSH key").
        key_btn = QPushButton(self.t("server.key"))
        key_btn.clicked.connect(self._select_key_file)
        key_layout = QHBoxLayout()
        key_layout.addWidget(self.key_path_edit)
        key_layout.addWidget(key_btn)
        form_layout.addRow("", key_layout)

        layout.addLayout(form_layout)

        # ── v0.9.9.2: external terminal — preset + reset to default ──────────
        # The preset is saved in the single ~/.sshmap/config.json (load/save from the module,
        # v1.1: migration from legacy ~/.sshmap_settings.json) and applied on
        # every launch: detect_terminal() reads the config.
        try:
            from ..modules import external_terminal as _ext_term_mod
        except ImportError:  # flat launch from the project root
            from modules import external_terminal as _ext_term_mod
        self._ext_term_mod = _ext_term_mod

        ext_section = QFormLayout()
        ext_title = QLabel(self.t("ssh_ext.section"))
        ext_title.setStyleSheet(f"font-weight: bold; color: {theme.TEXT_PRIMARY};")
        ext_section.addRow("", ext_title)

        self.ext_terminal_combo = QComboBox()
        _choices = (_ext_term_mod.TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                    else _ext_term_mod.TERMINAL_CHOICES_LINUX)
        for _tid in _choices:
            # i18n label of the preset; if the key is missing, t() returns en/the key itself.
            self.ext_terminal_combo.addItem(self.t(f"ssh_ext.preset.{_tid}"), _tid)
        _cur = _ext_term_mod.load_external_terminal_setting()
        _idx = next((i for i in range(self.ext_terminal_combo.count())
                     if self.ext_terminal_combo.itemData(i) == _cur), 0)
        self.ext_terminal_combo.setCurrentIndex(_idx)

        self.ext_terminal_reset_btn = QPushButton(self.t("ssh_ext.reset"))
        ext_hbox = QHBoxLayout()
        ext_hbox.addWidget(self.ext_terminal_combo, 1)
        ext_hbox.addWidget(self.ext_terminal_reset_btn)
        ext_section.addRow(self.t("ssh_ext.preset_label"), ext_hbox)

        # Connect saving AFTER setting the initial index — so simply
        # opening the dialog doesn't write to the file (currentIndexChanged echo on init).
        self.ext_terminal_combo.currentIndexChanged.connect(self._on_ext_terminal_changed)
        self.ext_terminal_reset_btn.clicked.connect(self._reset_ext_terminal)
        layout.addLayout(ext_section)

        # ── Buttons ──
        btn_layout = QHBoxLayout()
        self.connect_btn = QPushButton(self.t("ssh.connect"))
        self.connect_btn.clicked.connect(self._connect_ssh)

        self.test_btn = QPushButton(self.t("ssh.test"))
        self.test_btn.clicked.connect(self._test_connection)

        # v0.8.2: "Open in external terminal" button — the OS ssh client
        # in the system terminal; the password is not passed (security).
        self.external_btn = QPushButton(self.t("ssh_ext.open_button"))
        self.external_btn.clicked.connect(self._open_external)

        cancel_btn = QPushButton(self.t("ssh.cancel"))
        cancel_btn.clicked.connect(self.reject)  # explicit connect instead of kwarg syntax

        btn_layout.addWidget(self.test_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.connect_btn)
        btn_layout.addWidget(self.external_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # ── Status ──
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self.status_label)

    def _on_profile_changed(self, index: int):
        """When profile selected → auto-fill user + password from keyring."""
        if index <= 0 or not self._profiles:
            return
        profile = self._profiles[index - 1]
        self.user_edit.setText(profile["user"])
        # Fetch password lazily from keyring (not cached)
        pw = self._get_profile_password(profile["id"])
        if pw:
            self.password_edit.setText(pw)

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
            for p in _load_profiles():
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
            if old_current > 0 and old_current - 1 < len(self._profiles):
                self.profile_combo.setCurrentIndex(old_current)

    def _on_ext_terminal_changed(self, index: int):
        """v0.9.9.2: external terminal preset — save immediately (merge-write).

        The saved id will be picked up by detect_terminal() on the next launch —
        both from this dialog and from the MainWindow context menu.
        """
        tid = self.ext_terminal_combo.itemData(index)
        if tid and getattr(self, "_ext_term_mod", None) is not None:
            self._ext_term_mod.save_external_terminal_setting(tid)

    def _reset_ext_terminal(self):
        """v0.9.9.2: "Reset to default" — a ready-made rollback to auto."""
        for i in range(self.ext_terminal_combo.count()):
            if self.ext_terminal_combo.itemData(i) == "auto":
                self.ext_terminal_combo.setCurrentIndex(i)  # fires save on change
                break
        # Explicit write — an idempotent rollback, even if the combo was already on auto.
        if getattr(self, "_ext_term_mod", None) is not None:
            self._ext_term_mod.save_external_terminal_setting("auto")

    def _select_key_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.select_key"), "",
            "SSH Keys (*.pem *.key *.ppk);;" + self.t("filter.all_files")
        )
        if path:
            self.key_path_edit.setText(path)

    def _set_busy(self, busy: bool):
        self.connect_btn.setEnabled(not busy)
        self.test_btn.setEnabled(not busy)
        self.status_label.setText("\u23f3..." if busy else "")

    def _start_worker(self, *, test_only: bool):
        host = self.server_data.host.strip()
        user = self.user_edit.text().strip()
        key_path = self.key_path_edit.text().strip()
        password = self.password_edit.text()
        port = self.port_edit.value()

        if not host:
            QMessageBox.warning(self, self.t("msg.error_title"), 
                               f"{self.t('server.host')} {self.t('validation.empty_host')}")
            return
        if not user:
            QMessageBox.warning(self, self.t("msg.error_title"), self.t("ssh.user_required"))
            return

        self._set_busy(True)
        
        status_msg = self.t("ssh.connecting") if test_only else self.t("ssh.connecting_ssh")
        self.status_label.setText(status_msg)
        
        # Pass server_id for credential manager lookup
        self._ssh_worker = SSHWorker(
            host=host,
            user=user,
            port=port,
            server_id=self.server_data.id,  # for load_password from the keyring
            password=password,
            key_path=key_path,
            test_only=test_only,
            parent=self,
        )
        self._ssh_worker.success.connect(self._on_worker_success)
        self._ssh_worker.error.connect(self._on_worker_error)
        self._ssh_worker.finished.connect(self._on_worker_finished)
        self._ssh_worker.start()

    def _test_connection(self):
        """Test TCP reachability of SSH port without blocking UI."""
        self._start_worker(test_only=True)

    def _connect_ssh(self):
        """Connect via SSH."""
        self._start_worker(test_only=False)

    def _open_external(self):
        """v0.8.2: open an SSH session in the OS system terminal.

        The dialog field values (user/port/key) are used, but the password
        is NOT passed — the OS ssh prompts for it itself (security: argv is visible
        in ps/Task Manager).
        """
        host = self.server_data.host.strip()
        if not host:
            QMessageBox.warning(self, self.t("msg.error_title"),
                                f"{self.t('server.host')} {self.t('validation.empty_host')}")
            return
        try:
            from ..modules import external_terminal as _ext
        except ImportError:
            from modules import external_terminal as _ext

        user = self.user_edit.text().strip()
        key_path = self.key_path_edit.text().strip()
        port = self.port_edit.value()

        # Remember the entered user/key/port in the server data, as the
        # regular connection does after success — so the context menu and the next launch
        # use the up-to-date values.
        # v1.0-fix (audit #2): via the undo stack + dirty marker (MainWindow helper),
        # not by writing directly to node.data: earlier Ctrl+Z didn't roll back, on close
        # without Ctrl+S the changes were lost without a "save?" dialog, and the card
        # didn't redraw the SSH:<port> line.
        win = self.parent()
        if win is not None and hasattr(win, "_apply_ssh_dialog_fields"):
            win._apply_ssh_dialog_fields(self.server_data.id, user, key_path, port)
        else:
            # No MainWindow parent (headless tests) — direct write, as before.
            self.server_data.user = user
            self.server_data.key_path = key_path
            self.server_data.ssh_port = port

        ok, err = _ext.connect_external(
            host=host,
            user=user,
            port=port,
            key_path=key_path or None,
        )
        if not ok:
            if err == "no_ssh_client":
                QMessageBox.warning(self, self.t("msg.error_title"),
                                    self.t("ssh_ext.no_ssh_client"))
            elif err == "no_terminal":
                QMessageBox.warning(self, self.t("msg.error_title"),
                                    self.t("ssh_ext.no_terminal"))
            else:
                QMessageBox.critical(self, self.t("msg.ssh_error"),
                                     self.t("ssh_ext.launch_failed"))
            return
        self.status_label.setText(self.t("ssh_ext.launched", alias=self.server_data.alias))

    def _on_worker_success(self, message: str):
        # v1.2.10rc2 (manual AUDIT #5c): the body is in try/except RuntimeError — a late
        # success after the dialog closed (closeEvent detached the worker via setParent(None),
        # line 497, and it lives out the connection) is delivered by a queued signal to an
        # already destroyed C++ widget: RuntimeError inside the Qt slot dispatch (PySide
        # prints and swallows it). The dialog is closed — nowhere to show it, the guard stays silent.
        try:
            self.status_label.setText(message)
            if self._ssh_worker and self._ssh_worker.test_only:
                QMessageBox.information(self, self.t("msg.success_title"),
                                      f"{self.t('ssh.test_ok')}\n\n{message}")
                return

            # v1.1.2RC1 (N1): direct writes to server_data REMOVED — earlier the dialog itself
            # wrote user/key_path/ssh_port (that's the same object as node.data), and
            # _apply_ssh_dialog_fields() in MainWindow compared old/new already equal →
            # CmdEditNodeData wasn't pushed, Ctrl+Z didn't roll back the login/key/port change.
            # Now the only path is the MainWindow helper AFTER accept():
            # _run_ssh_connect() → _apply_ssh_dialog_fields() (undo stack + dirty).

            # Save password to keyring if it was provided via UI (not profile)
            password_from_ui = self.password_edit.text()
            if password_from_ui and self.server_data.id:
                try:
                    # BUGFIX v0.9.5.6: dual import (relative + flat) —
                    # when launched as "python main.py" the dialogs package is top-level, and
                    # "from ..services" raised ImportError, which the outer
                    # except Exception caught → a false "keyring save failed" + a warning
                    # to the user (the connection still went through). The fallback — like all
                    # the other imports in this file.
                    try:
                        from ..services.credential_manager import get_credential_manager
                    except ImportError:
                        from services.credential_manager import get_credential_manager
                    cm = get_credential_manager()
                    # v0.9.4-fix: the result is checked — aligned with _do_save, where
                    # silent password loss is warned about. save_password returns
                    # False when the keyring is unavailable (NoKeyringError etc. are caught there).
                    saved_ok = bool(cm.save_password(self.server_data.id, password_from_ui))
                except Exception as e:
                    saved_ok = False  # credential manager failure is non-critical
                    try:
                        from modules.logger import get_logger
                        get_logger(__name__).warning(f"keyring save failed: {e}")
                    except Exception:
                        pass
                if not saved_ok:
                    # The same i18n key as in _do_save (behavior parity)
                    QMessageBox.warning(
                        self,
                        self.t("msg.error_title"),
                        self.t("msg.credentials_save_failed", alias=self.server_data.alias))

            # v0.9.5.6: the "Success / SSH connection established" window REMOVED — an extra
            # click was annoying; the confirmation of the connection is the terminal window itself,
            # and the details are already in status_label (message) and the MainWindow status bar.
            self.accept()
        except RuntimeError:
            pass  # the C++ object of the dialog/widgets is destroyed — a late signal is safe

    def _on_worker_error(self, message: str):
        # v1.2.10rc2 (manual AUDIT #5c): the same guard as in _on_worker_success —
        # a late error after the dialog closed (setParent(None) in closeEvent) must not
        # cause a RuntimeError inside the Qt slot dispatch.
        try:
            self.status_label.setText(f"\u2717 {message}")
            QMessageBox.critical(self, self.t("msg.ssh_error"), message)
        except RuntimeError:
            pass  # the C++ object of the dialog/widgets is destroyed — a late signal is safe

    def _on_worker_finished(self):
        self._set_busy(False)
        self._ssh_worker = None

    def closeEvent(self, event):
        """v0.6.x patch: the thread must not outlive the dialog (its QObject parent).

        The worker is created with parent=self; if the window is closed mid-request,
        object destruction delivers success/error into a dead object tree —
        Qt warnings and a potential crash. All operations inside the worker have
        internal network timeouts (socket 5 s / paramiko 15 s), so the
        bounded wait() here doesn't hang indefinitely.
        """
        worker = getattr(self, "_ssh_worker", None)
        if worker is not None:
            # v0.9.4-fix: earlier wait(30000) froze the GUI for up to 30 s on close
            # of the window during a connection. The worker's internal network timeouts
            # (socket 5 s / paramiko 15 s) guarantee quick completion, so
            # we wait at most 2 s with event processing (the GUI stays responsive),
            # then — requestInterruption + short finishing cycles.
            if worker.isRunning():
                deadline_ms = 2000
                while worker.isRunning() and deadline_ms > 0:
                    QCoreApplication.processEvents(_QEL.AllEvents, 50)
                    worker.wait(50)
                    deadline_ms -= 50
                if worker.isRunning():
                    try:
                        from modules.logger import get_logger as _get_log
                        _get_log(__name__).warning(
                            "SSHWorker still running at dialog close; "
                            "detaching (internal timeouts will finish it)")
                    except Exception:
                        pass
                    worker.setParent(None)  # detach from the dialog: the QObject outlives the window close
        event.accept()

