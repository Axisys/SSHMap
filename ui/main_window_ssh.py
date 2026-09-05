"""SshMixin — кластер «SSH-подключения и терминальные окна».

v1.1.4 (ROADMAP v1.1.4, задача 3): вынесен из ui/main_window.py в рамках серии
«Гигиена main_window.py». Паттерн «модуль + колбэки» (прецеденты v0.9.9.4 сайдбар,
v0.9.9.3 diagnostics): миксин — только методы, MainWindow остаётся фасадом,
публичный API не меняется; имена методов и точки вызова не трогались.

В кластер вошёл весь блок «Быстрый запуск» (``_open_quick_launch_dialog``,
``_run_quick_launch_entry``, ``_quick_launch_url``, ``_quick_launch_command``) —
он живёт на том же пути подключения/терминала (initial_command).

v1.1.3 (SFTP) уже выпущен — код sftp_worker.py/sftp_tab.py на месте, поэтому
SSH-кластер переносится вместе с ним (ROADMAP «Порядок»).

Владение общим состоянием (AUDIT §3, зафиксировано комментарием):
  * ``self._terminal_windows`` — реестр открытых СЕССИЙ терминала
    (v1.2: TerminalSessionPage из modules/terminal_page.py, а не окна — зелёная
    точка узла гаснет только когда закрыты ВСЕ сессии узла, лимит «4 своих
    терминала» считается по сессиям);
  * ``self._ssh_connected_nodes`` — id узлов с активной сессией (зелёная точка);
  * ``self._info_collectors`` — реестр SystemInfoCollector по server_id.
Миксин НЕ импортирует ui.main_window (цикл) — только duck-typing по инстансу;
SSHTerminalWindow/SSHConnectDialog/_ext_term берутся из модуля-фасада в момент
вызова (host_attr) — тестовый шов подмены ``MW.SSHTerminalWindow``/
``MW.SSHConnectDialog``/``MW._ext_term`` (иначе offscreen-прогон зависал бы на
настоящих модалках).
"""
import copy

from PySide6.QtWidgets import QDialog, QMessageBox

try:  # v1.1.4: общий шов подмены глобальных модуля-фасада (см. mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


class SshMixin:
    """Методы SSH: диалог, терминальные окна, автосбор информации, быстрый запуск."""

    def _connect_ssh_to_selected(self):
        """Connect via SSH to selected server."""
        node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                  self.t("msg.select_server_ssh"))
            return
        try:
            self._run_ssh_connect(node)
        except Exception as e:
            if self.log:
                self.log.exception(f"SSH connect error for {node.data.alias}")
            QMessageBox.critical(self, self.t("msg.ssh_error"), self.t("msg.connect_failed", error=str(e)))

    def _spawn_terminal_window(self, node: "ServerNode", password: str = None,
                               initial_command: str = ""):
        """v1.0RC4: создание терминального окна + учёт (единый путь).

        Вынесен из _run_ssh_connect (v0.9.5.6), чтобы «Быстрый запуск» с командой
        мог открыть терминал БЕЗ SSH-диалога (пароль уже в keyring / key auth):
        индикатор подключения, трекинг (_terminal_windows/_forget_terminal_window)
        и show() — ровно как штатный путь подключения.

        v1.1.1 (пункт 3): лимит своих терминалов (terminal_max_open, дефолт 4) —
        при достижении НЕ отказ: предложение закрыть СТАРЕЙШУЮ сессию / отмена.
        Возвращает None, если пользователь отменил (вызывающий код не должен
        сообщать об «открытом» терминале).

        v1.2 (ROADMAP задача 4): реестр регистрирует СЕССИИ (TerminalSessionPage),
        а не окна — лимит считается по сессиям; teardown старейшей при лимите —
        через страницу (page.close_terminal → closeEvent хост-окна → shutdown).
        """
        try:
            from modules.ssh_terminal import load_terminal_settings as _load_ts
        except ImportError:
            from ..modules.ssh_terminal import load_terminal_settings as _load_ts
        max_open = _load_ts()["max_open"]
        if len(self._terminal_windows) >= max_open and self._terminal_windows:
            oldest = self._terminal_windows[0]  # порядок создания — порядок списка (сессии)
            alias = getattr(getattr(oldest, "server_data", None), "alias", "?")
            reply = QMessageBox.question(
                self, self.t("msg.terminal_limit_title"),
                self.t("msg.terminal_limit_close_oldest", limit=max_open, alias=alias),
                QMessageBox.Close | QMessageBox.Cancel, QMessageBox.Cancel)
            if reply != QMessageBox.Close:
                return None  # отмена — новый терминал не открываем
            try:
                oldest._force_close = True  # «ask»-поведение не спрашивает повторно
                oldest.close_terminal()
            except Exception:  # noqa: BLE001 — сессия/окно могли уже исчезнуть (teardown)
                pass
            self._forget_terminal_window(oldest)  # сразу из реестра (destroyed ещё в пути)
        node.update_appearance()
        node.set_ssh_connected(True)
        self._ssh_connected_nodes.add(node.data.id)  # v0.9.4-fix: сброс индикатора при закрытии терминала
        win_cls = host_attr(self, "SSHTerminalWindow")
        if win_cls is None:
            raise RuntimeError("SSHTerminalWindow недоступен в модуле MainWindow")
        terminal_window = win_cls(
            node.data, self, password=password, initial_command=initial_command)
        # v1.2: регистрируем СЕССИЮ (страницу), а не окно; фейк без .page —
        # сам себя (тестовый шов host_attr: подмена MW.SSHTerminalWindow).
        session = getattr(terminal_window, "page", None) or terminal_window
        session.destroyed.connect(lambda *_a, s=session: self._forget_terminal_window(s))
        self._terminal_windows.append(session)
        terminal_window.show()
        return terminal_window

    def _apply_ssh_dialog_fields(self, node_id: str, user: str, key_path: str, ssh_port: int):
        """v1.0-fix (audit #2): применить user/key/port из SSH-диалога к узлу через
        undo-стек + dirty-маркер (единый путь).

        Используется штатным подключением (_run_ssh_connect) и «Открыть во внешнем
        терминале» (SSHConnectDialog._open_external): раньше последний писал напрямую
        в node.data — Ctrl+Z не откатывал, при закрытии без Ctrl+S изменения сгорали
        без диалога «сохранить?», карточка не перерисовывала строку SSH:<порт>.
        """
        from modules.undo_commands import CmdEditNodeData
        node = self.scene.get_node(node_id)
        if node is None:
            return
        old_data = copy.deepcopy(node.data)
        new_data = copy.deepcopy(node.data)
        new_data.user = user
        new_data.key_path = key_path
        new_data.ssh_port = ssh_port
        if (old_data.user, old_data.key_path, old_data.ssh_port) != \
                (new_data.user, new_data.key_path, new_data.ssh_port):
            self._push_command(CmdEditNodeData(self, node, old_data, new_data))
        else:
            self._mark_dirty()

    def _run_ssh_connect(self, node: "ServerNode", prefill_password: str = "",
                         initial_command: str = ""):
        """v0.9.5.6: SSH-диалог → при успехе: обновить данные узла, индикатор,
        автосбор информации и терминальное окно.

        Общий путь для «Подключиться по SSH» из тулбара/контекста (prefill="")
        и из диалога свойств сервера (prefill_password — пароль из полей свойств,
        чтобы пользователь не вставлял его повторно). v1.0RC4: initial_command —
        первая команда для терминала (Быстрый запуск с командой без keyring-пароля).
        """
        dlg_cls = host_attr(self, "SSHConnectDialog")
        if dlg_cls is None:
            raise RuntimeError("SSHConnectDialog недоступен в модуле MainWindow")
        dlg = dlg_cls(node.data, self)
        if prefill_password:
            dlg.password_edit.setText(prefill_password)
        if dlg.exec() != QDialog.Accepted:
            return
        # v0.9.4-fix: правки user/key_path/ssh_port из диалога идут через
        # undo-стек и помечают проект dirty (раньше писались напрямую в
        # node.data — терялись при выходе без Ctrl+S и не откатывались).
        # v1.0-fix (audit #2): единый хелпер _apply_ssh_dialog_fields — им же
        # пользуется «Открыть во внешнем терминале».
        # v1.1.2RC1 (N1): теперь это РЕАЛЬНО единственная запись полей штатного
        # пути — диалог (_on_worker_success) больше не пишет в node.data сам,
        # поэтому old/new здесь различаются и CmdEditNodeData пушится: Ctrl+Z
        # откатывает смену user/key/port, сделанную через успешное подключение.
        self._apply_ssh_dialog_fields(
            node.data.id, dlg.user_edit.text().strip(),
            dlg.key_path_edit.text().strip(), dlg.port_edit.value())
        # AUDIT v0.7.2 (средняя #7): пароль НЕ храним в модели — передаём его
        # напрямую терминальному окну ниже; сам диалог уже записал его в keyring
        # (_on_worker_success), так что ничего не теряется при сохранении проекта.

        # v1.0RC4: индикатор подключения + трекинг окна — в _spawn_terminal_window
        # (единый путь для штатного подключения и Быстрого запуска с командой).
        if self.log:
            self.log.info("SSH connected", extra={"alias": node.data.alias, "host": node.data.host})
        self.statusBar().showMessage(self.t("status.ssh_connected", alias=node.data.alias))

        # v0.9: автосбор данных о сервере после успешного подключения
        # (пароль из диалога ещё не потерян; НЕ через StatusChecker —
        # тот работает без аутентификации по дизайну)
        if getattr(node.data, "os_name", "") == "" and \
                hasattr(dlg, "password_edit"):
            self._collect_node_info(
                node, password=dlg.password_edit.text(), auto=True)

        # Open interactive terminal (пароль — явно, см. AUDIT v0.7.2 средняя #7;
        # v1.0RC4: initial_command — первая команда Быстрого запуска, если была)
        self._spawn_terminal_window(
            node, password=dlg.password_edit.text(), initial_command=initial_command)

    # ── v0.9: автосбор данных о сервере (Linux) ───────────────────

    def _collect_node_info(self, node, password: str = "", auto: bool = False):
        """Запустить SystemInfoCollector для узла.

        auto=True — тихий автозапуск после успешного SSH-подключения
        (без сообщений об ошибке, только статус-бар).
        """
        try:
            from services.system_info_collector import SystemInfoCollector
        except ImportError as e:
            if self.log:
                self.log.warning(f"SystemInfoCollector unavailable: {e}")
            return
        sid = node.data.id
        # Guard: не плодим параллельные сборы для одного узла
        old = getattr(self, "_info_collectors", {}).get(sid)
        if old is not None and old.isRunning():
            return
        if not hasattr(self, "_info_collectors"):
            self._info_collectors = {}
        collector = SystemInfoCollector(node.data, password=password, parent=self)
        self._info_collectors[sid] = collector

        def _ready(server_id, info, coll=collector):
            self._on_info_ready(server_id, info, coll)

        def _failed(server_id, error, coll=collector):
            self._on_info_failed(server_id, error, coll, auto=auto)

        collector.info_ready.connect(_ready)
        collector.info_failed.connect(_failed)
        collector.finished.connect(
            lambda *_a: self._info_collectors.pop(sid, None))
        collector.start()
        key = "status.info_running_auto" if auto else "status.info_running"
        try:
            self.statusBar().showMessage(self.t(key, alias=node.data.alias), 4000)
        except Exception:
            pass

    def _on_info_ready(self, server_id: str, info: dict, collector):
        """Результат сбора: записать в node.data + dirty + перерисовка."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # узел удалён, пока собирали
        d = node.data
        if info.get("os_name"):
            d.os_name = info["os_name"]
        if info.get("cpu_model"):
            d.cpu_model = info["cpu_model"]
        if info.get("cpu_cores"):
            d.cpu = f"{info['cpu_cores']} core"
        if info.get("ram_gb"):
            d.ram = info["ram_gb"]
        if info.get("disk_gb"):
            d.disk = info["disk_gb"]
        node.update_appearance()
        self.refresh_sidebar()
        self._mark_dirty()
        try:
            self.statusBar().showMessage(
                self.t("status.info_collected", alias=d.alias), 5000)
        except Exception:
            pass
        if self.log:
            self.log.info("System info collected",
                          extra={"alias": d.alias, "os": d.os_name})

    def _on_info_failed(self, server_id: str, error: str, collector,
                        auto: bool = False):
        node = self.scene.get_node(server_id)
        alias = node.data.alias if node is not None else server_id
        if self.log:
            self.log.warning(f"Info collection failed for {alias}: {error}")
        if auto:
            return  # тихий режим — не пугаем пользователя при обычном подключении
        try:
            self.statusBar().showMessage(
                self.t("status.info_failed", error=error), 8000)
        except Exception:
            pass

    def _connect_ssh_external(self, node=None):
        """v0.8.2: открыть SSH-сессию в системном терминале ОС (wt/cmd/gnome-terminal).

        Пароль НЕ передаётся (виден в ps) — ssh ОС спросит сам / key auth.
        """
        if node is None:
            node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                  self.t("msg.select_server_ssh"))
            return
        ext_term = host_attr(self, "_ext_term")
        if ext_term is None:
            return
        data = node.data
        ok, err = ext_term.connect_external(
            host=data.host.strip(),
            user=(data.user or "").strip(),
            port=data.ssh_port or 22,
            key_path=(data.key_path or "").strip() or None,
        )
        if not ok:
            if err == "no_ssh_client":
                QMessageBox.warning(self, self.t("msg.error_title"),
                                    self.t("ssh_ext.no_ssh_client"))
            elif err == "no_terminal":
                QMessageBox.warning(self, self.t("msg.error_title"),
                                    self.t("ssh_ext.no_terminal"))
            else:
                self.statusBar().showMessage(
                    self.t("ssh_ext.launch_failed"), 5000)
                QMessageBox.critical(self, self.t("msg.ssh_error"),
                                     self.t("ssh_ext.launch_failed"))
            return
        self.statusBar().showMessage(
            self.t("ssh_ext.launched", alias=data.alias), 5000)
        if self.log:
            self.log.info("SSH launched in external terminal",
                          extra={"alias": data.alias, "host": data.host})

    # ── v1.0RC4: Быстрый запуск (ссылки/команды на сервер) ───────────────

    def _open_quick_launch_dialog(self, node=None):
        """Настройка пунктов Быстрого запуска для сервера.

        Точки входа: подменю «Быстрый запуск → Настроить…» (ПКМ по строке
        сайдбара / узлу карты) и кнопка в свойствах сервера (AddServerDialog).
        Изменения — через undo-стек (CmdEditNodeData), как любая правка данных.
        """
        if node is None:
            node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.properties_select"))
            return
        try:
            from ..dialogs.quick_launch_dialog import QuickLaunchDialog
        except ImportError:
            from dialogs.quick_launch_dialog import QuickLaunchDialog
        dlg = QuickLaunchDialog(self, server_data=node.data)
        if dlg.exec() != QDialog.Accepted:
            return
        old_data = copy.deepcopy(node.data)
        new_data = copy.deepcopy(node.data)
        new_data.quick_launch = [dict(e) for e in dlg.get_entries()]
        if old_data.quick_launch != new_data.quick_launch:
            from modules.undo_commands import CmdEditNodeData
            self._push_command(CmdEditNodeData(self, node, old_data, new_data))
            self.refresh_sidebar()
            self._mark_dirty()  # ← unsaved changes
        if self.log:
            self.log.info("Quick launch updated",
                          extra={"alias": node.data.alias,
                                 "entries": len(new_data.quick_launch)})

    def _run_quick_launch_entry(self, node, entry):
        """Выполнить пункт Быстрого запуска.

        type="url"     → браузер по умолчанию (webbrowser);
        type="command" → первая команда в SSH-терминале сервера.
        """
        if node is None or not isinstance(entry, dict):
            return
        etype = str(entry.get("type", "url")).strip().lower()
        value = str(entry.get("value", "")).strip()
        name = str(entry.get("name") or value)
        if not value:
            return
        try:
            if etype == "command":
                self._quick_launch_command(node, value, name)
            else:
                self._quick_launch_url(value, name)
        except Exception as e:  # noqa: BLE001 — сбой пункта не роняет меню
            if self.log:
                self.log.exception(f"Quick launch failed for {node.data.alias}")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.ql_open_failed", error=str(e)))

    def _quick_launch_url(self, url: str, name: str):
        """URL-пункт — открыть в браузере по умолчанию (stdlib webbrowser)."""
        import webbrowser
        try:
            ok = webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.error(f"Quick launch URL failed: {e}")
            QMessageBox.warning(self, self.t("msg.error_title"),
                                self.t("msg.ql_open_failed", error=str(e)))
            return
        if not ok:
            QMessageBox.warning(self, self.t("msg.error_title"),
                                self.t("msg.ql_no_browser"))
            return
        try:
            self.statusBar().showMessage(self.t("status.ql_opened", name=name), 4000)
        except Exception:
            pass
        if self.log:
            # v1.0-fix: в extra нельзя ключ "name" — это встроенный атрибут
            # LogRecord (имя логгера), makeRecord() падает KeyError; отсюда
            # ложный "Quick launch failed" после успешного открытия URL.
            self.log.info("Quick launch URL opened", extra={"ql_name": name, "url": url})

    def _quick_launch_command(self, node, cmd: str, name: str):
        """Command-пункт — первая команда в SSH-терминале сервера.

        Пароль уже в keyring (или key auth) → терминал открывается напрямую,
        без диалога; учётных данных нет вообще — штатный SSH-диалог, и после
        подключения та же команда отправляется в терминал (initial_command).
        """
        data = node.data
        pwd = ""
        try:
            from services.credential_manager import get_credential_manager
            pwd = get_credential_manager().load_password(data.id) or ""
        except Exception:  # noqa: BLE001 — keyring недоступен: путь через диалог
            pwd = ""
        if pwd or (data.key_path or "").strip():
            # v1.1.1: None — пользователь отменил по лимиту терминалов; статус
            # «команда отправлена» в этом случае был бы ложным.
            if self._spawn_terminal_window(
                    node, password=pwd or None, initial_command=cmd) is not None:
                try:
                    self.statusBar().showMessage(
                        self.t("status.ql_command", name=name, alias=data.alias), 5000)
                except Exception:
                    pass
        else:
            self._run_ssh_connect(node, prefill_password="", initial_command=cmd)
        if self.log:
            # v1.0-fix: тот же KeyError — ключ "name" зарезервирован LogRecord.
            self.log.info("Quick launch command started",
                          extra={"alias": data.alias, "ql_name": name})

    def _forget_terminal_window(self, session):
        """v1.2 (ROADMAP задача 4): реестр хранит СЕССИИ (TerminalSessionPage),
        а не окна — сюда может прийти и окно (разрешается в его .page).

        v0.9.4-fix: терминал закрыт → гасим зелёную SSH-точку узла (раньше
        индикатор горел вечно после первого подключения). С v1.2 точка гаснет
        только когда закрыты ВСЕ сессии узла — подсчёт по сессиям реестра.
        """
        session = getattr(session, "page", None) or session
        self._terminal_windows = [s for s in self._terminal_windows if s is not session]
        try:
            sid = getattr(getattr(session, "server_data", None), "id", None)
            if sid:
                remaining = any(
                    getattr(s, "server_data", None) is not None
                    and getattr(s, "server_data").id == sid
                    for s in self._terminal_windows
                )
                if not remaining:
                    # все сессии узла закрыты — снимаем индикатор
                    self._ssh_connected_nodes.discard(sid)
                    node = self.scene.get_node(sid) if hasattr(self.scene, "get_node") else None
                    if node is not None:
                        node.set_ssh_connected(False)
        except RuntimeError:
            pass  # C++-объект уже уничтожен при teardown — нормально
