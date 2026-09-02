

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

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QFormLayout, QLineEdit, QSpinBox,
    QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QComboBox,
)
from PySide6.QtCore import QCoreApplication, QEventLoop as _QEL  # v0.9.4-fix: неблокирующее закрытие


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
        
        self.resize(420, 430)  # v0.9.9.2: + секция «Внешний терминал»
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
        # Загружаем профили ДО построения UI, чтобы комбобокс был наполнен
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
            self.profile_combo.addItem("(ручной ввод)")
            btn_manage_profiles = QPushButton("Управление профилями…")  # UI polish: без эмодзи
            btn_manage_profiles.clicked.connect(self._open_profile_manager)

            combo_hbox = QHBoxLayout()
            combo_hbox.addWidget(self.profile_combo)
            combo_hbox.addStretch()
            combo_hbox.addWidget(btn_manage_profiles)
            profile_section.addRow("", combo_hbox)

        layout.addLayout(profile_section)

        # Separator
        sep = QLabel("─" * 50)
        sep.setStyleSheet("color: #334155;")
        layout.addWidget(sep)
        layout.addSpacing(6)

        # ── Server info (read-only) ──
        info_text = f"{self.t('ssh.server_info')} {self.server_data.host}"
        info_label = QLabel(f"<b>{info_text}</b>")
        info_label.setStyleSheet("font-weight: bold; color: #e2e8f0;")
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

        # UI polish: эмодзи из значений i18n (server.key, ssh.connect, ssh.test) убраны;
        # не добавлять их в коде — был баг с повторением («🔑 🔑 Ключ SSH»).
        key_btn = QPushButton(self.t("server.key"))
        key_btn.clicked.connect(self._select_key_file)
        key_layout = QHBoxLayout()
        key_layout.addWidget(self.key_path_edit)
        key_layout.addWidget(key_btn)
        form_layout.addRow("", key_layout)

        layout.addLayout(form_layout)

        # ── v0.9.9.2: внешний терминал — пресет + сброс к умолчанию ──────────
        # Пресет сохраняется в едином ~/.sshmap/config.json (load/save из модуля,
        # v1.1: миграция из legacy ~/.sshmap_settings.json) и применяется при
        # каждом запуске: detect_terminal() читает конфиг.
        try:
            from ..modules import external_terminal as _ext_term_mod
        except ImportError:  # плоский запуск из корня проекта
            from modules import external_terminal as _ext_term_mod
        self._ext_term_mod = _ext_term_mod

        ext_section = QFormLayout()
        ext_title = QLabel(self.t("ssh_ext.section"))
        ext_title.setStyleSheet("font-weight: bold; color: #e2e8f0;")
        ext_section.addRow("", ext_title)

        self.ext_terminal_combo = QComboBox()
        _choices = (_ext_term_mod.TERMINAL_CHOICES_WINDOWS if sys.platform == "win32"
                    else _ext_term_mod.TERMINAL_CHOICES_LINUX)
        for _tid in _choices:
            # i18n-метка пресета; при отсутствии ключа t() сам вернёт en/ключ.
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

        # Подключаем сохранение ПОСЛЕ установки начального индекса — чтобы просто
        # открытие диалога не писало в файл (эхо currentIndexChanged на init).
        self.ext_terminal_combo.currentIndexChanged.connect(self._on_ext_terminal_changed)
        self.ext_terminal_reset_btn.clicked.connect(self._reset_ext_terminal)
        layout.addLayout(ext_section)

        # ── Buttons ──
        btn_layout = QHBoxLayout()
        self.connect_btn = QPushButton(self.t("ssh.connect"))
        self.connect_btn.clicked.connect(self._connect_ssh)

        self.test_btn = QPushButton(self.t("ssh.test"))
        self.test_btn.clicked.connect(self._test_connection)

        # v0.8.2: кнопка «Открыть во внешнем терминале» — ssh-клиент ОС
        # в системном терминале; пароль не передаётся (безопасность).
        self.external_btn = QPushButton(self.t("ssh_ext.open_button"))
        self.external_btn.clicked.connect(self._open_external)

        cancel_btn = QPushButton(self.t("ssh.cancel"))
        cancel_btn.clicked.connect(self.reject)  # явный connect вместо kwarg-синтаксиса

        btn_layout.addWidget(self.test_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.connect_btn)
        btn_layout.addWidget(self.external_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # ── Status ──
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #94a3b8;")
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
        """v0.9.9.2: пресет внешнего терминала — сохранить сразу (merge-запись).

        Сохранённый id подхватит detect_terminal() при следующем запуске —
        и из этого диалога, и из ctx-меню MainWindow.
        """
        tid = self.ext_terminal_combo.itemData(index)
        if tid and getattr(self, "_ext_term_mod", None) is not None:
            self._ext_term_mod.save_external_terminal_setting(tid)

    def _reset_ext_terminal(self):
        """v0.9.9.2: «Сбросить к умолчанию» — готовый откат на auto."""
        for i in range(self.ext_terminal_combo.count()):
            if self.ext_terminal_combo.itemData(i) == "auto":
                self.ext_terminal_combo.setCurrentIndex(i)  # fire save при смене
                break
        # Явная запись — идемпотентный откат, даже если combo уже стоял на auto.
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
            server_id=self.server_data.id,  # для load_password из keyring
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
        """v0.8.2: открыть SSH-сессию в системном терминале ОС.

        Используются значения полей диалога (user/port/key), но пароль
        НЕ передаётся — ssh ОС запросит его сам (безопасность: argv виден
        в ps/диспетчере задач).
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

        # Запомнить введённые user/key/port в данных сервера, как это делает
        # обычное подключение после успеха — чтобы ctx-меню и следующий запуск
        # использовали актуальные значения.
        # v1.0-fix (audit #2): через undo-стек + dirty-маркер (хелпер MainWindow),
        # а не прямой записью в node.data: раньше Ctrl+Z не откатывал, при закрытии
        # без Ctrl+S изменения сгорали без диалога «сохранить?», и карточка не
        # перерисовывала строку SSH:<порт>.
        win = self.parent()
        if win is not None and hasattr(win, "_apply_ssh_dialog_fields"):
            win._apply_ssh_dialog_fields(self.server_data.id, user, key_path, port)
        else:
            # Нет родителя-MainWindow (headless-тесты) — прямой записью, как раньше.
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
        self.status_label.setText(message)
        if self._ssh_worker and self._ssh_worker.test_only:
            QMessageBox.information(self, self.t("msg.success_title"), 
                                  f"{self.t('ssh.test_ok')}\n\n{message}")
            return

        # Update server data from dialog fields
        self.server_data.user = self.user_edit.text().strip()
        self.server_data.key_path = self.key_path_edit.text().strip()
        self.server_data.ssh_port = self.port_edit.value()
        
        # Save password to keyring if it was provided via UI (not profile)
        password_from_ui = self.password_edit.text()
        if password_from_ui and self.server_data.id:
            try:
                # BUGFIX v0.9.5.6: двойной импорт (относительный + плоский) —
                # при запуске «python main.py» пакет dialogs top-level, и
                # «from ..services» падал ImportError, который ловил внешний
                # except Exception → ложное «keyring save failed» + предупреждение
                # пользователю (подключение при этом шло). Фолбэк — как у всех
                # остальных импортов этого файла.
                try:
                    from ..services.credential_manager import get_credential_manager
                except ImportError:
                    from services.credential_manager import get_credential_manager
                cm = get_credential_manager()
                # v0.9.4-fix: результат проверяется — выровнено с _do_save, где
                # тихая потеря пароля предупреждается. save_password возвращает
                # False при недоступном keyring (NoKeyringError и т.п. ловятся там).
                saved_ok = bool(cm.save_password(self.server_data.id, password_from_ui))
            except Exception as e:
                saved_ok = False  # credential manager failure is non-critical
                try:
                    from modules.logger import get_logger
                    get_logger(__name__).warning(f"keyring save failed: {e}")
                except Exception:
                    pass
            if not saved_ok:
                # Тот же i18n-ключ, что в _do_save (паритет поведения)
                QMessageBox.warning(
                    self,
                    self.t("msg.error_title"),
                    self.t("msg.credentials_save_failed", alias=self.server_data.alias))

        # v0.9.5.6: окно «Успех / SSH подключение установлено» УБРАНО — лишний
        # клик раздражал; подтверждение подключения — само терминальное окно,
        # а детали уже в status_label (message) и в статус-баре MainWindow.
        self.accept()

    def _on_worker_error(self, message: str):
        self.status_label.setText(f"\u2717 {message}")
        QMessageBox.critical(self, self.t("msg.ssh_error"), message)

    def _on_worker_finished(self):
        self._set_busy(False)
        self._ssh_worker = None

    def closeEvent(self, event):
        """Патч v0.6.x: поток не должен пережить диалог (его QObject parent).

        Worker создаётся с parent=self; если закрыть окно во время запроса,
        уничтожение объекта доставит success/error в мёртвое дерево объектов —
        предупреждения Qt и потенциальный краш. Все операции внутри worker имеют
        внутренние сетевые таймауты (socket 5 c / paramiko 15 c), поэтому
        ограниченный wait() здесь не висит бесконечно.
        """
        worker = getattr(self, "_ssh_worker", None)
        if worker is not None:
            # v0.9.4-fix: раньше wait(30000) замораживал GUI до 30 c при закрытии
            # окна во время подключения. Внутренние сетевые таймауты worker'а
            # (socket 5 c / paramiko 15 c) гарантируют скорое завершение, поэтому
            # ждём максимум 2 c с обработкой событий (GUI остаётся отзывчивым),
            # дальше — requestInterruption + короткие добивочные циклы.
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
                    worker.setParent(None)  # отвязать от диалога: QObject переживёт закрытие окна
        event.accept()

