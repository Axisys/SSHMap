"""NodeOpsMixin — кластер «операции над узлами и связями карты».

v1.1.4 (ROADMAP v1.1.4, задача 2): вынесен из ui/main_window.py в рамках серии
«Гигиена main_window.py». Паттерн «модуль + колбэки» (прецеденты v0.9.9.4 сайдбар,
v0.9.9.3 diagnostics): миксин — только методы, MainWindow остаётся фасадом,
публичный API не меняется; имена методов и точки вызова не трогались.

В кластер вошёл весь импорт из TXT (``_import_servers_from_txt`` + слоты потока
``_on_import_resolve_progress``/``_on_import_resolved`` и сборка
``_finish_import_from_txt``) — это одна фича, разорвать её по файлам нельзя.

Владение общим состоянием (AUDIT §3): узлы/связи живут на ``self.scene``,
undo-стек и ``_dirty`` — в ядре (MainWindow); потоки ping/DNS/import держатся
на инстансе (``self._ping_thread``/``self._dns_thread``/``self._import_resolve_thread``
+ контекст пачки ``self._import_pending/_import_path/_import_skipped``).
Миксин НЕ импортирует ui.main_window (цикл) — только duck-typing по инстансу;
диалоги (AddServerDialog/ConnectionDialog) берутся из модуля-фасада в момент
вызова (host_attr) — тестовый шов подмены ``MW.AddServerDialog``/``MW.ConnectionDialog``.

``_is_scene_point`` переехал сюда вместе с кластером (AUDIT §3: «модульные
глобальные едут в свой миксин или остаются в ядре»); main_window.py импортирует
его обратно — ``_add_group_at`` (группы, ядро) пользуется тем же guard'ом.
"""
from PySide6.QtWidgets import QDialog, QMessageBox, QApplication

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:  # v1.1.4: общий шов подмены глобальных модуля-фасада (см. mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


def _is_scene_point(value) -> bool:
    """v0.8.1: передана ли точка сцены (QPoint/QPointF), а не что-то другое.

    QAction.triggered передаёт Python-слоту bool `checked` — при прямом
    подключении действия (тулбар/меню) он приходит первым позиционным
    аргументом. Без этой проверки `_add_server(True)` падал на `center.x()`
    («'bool' object has no attribute 'x'»).
    """
    if value is None or isinstance(value, bool):
        return False
    x = getattr(value, "x", None)
    y = getattr(value, "y", None)
    return callable(x) and callable(y)


class NodeOpsMixin:
    """Методы узлов/связей: add/import/duplicate/delete/connect/copy/ping."""

    def _add_server(self, at_scene_pos=None):
        """Создать сервер (атрибут `at_scene_pos` — точка клика из контекстного меню)."""
        data = None  # чтобы except-ветка не падала на несуществующей переменной (бывш. AUDIT.md)
        try:
            dlg_cls = host_attr(self, "AddServerDialog")
            if dlg_cls is None:
                raise RuntimeError("AddServerDialog недоступен в модуле MainWindow")
            dlg = dlg_cls(self)
            if dlg.exec() == QDialog.Accepted:
                data = dlg.get_data()
                # Позиция: точка клика (ПКМ-меню, v0.7.2) или центр видимой области.
                # v0.8.1: принимаем позицию только если это действительно точка —
                # QAction.triggered (тулбар/меню) шлёт в слот bool `checked`, который
                # раньше попадал сюда как at_scene_pos и ронял `center.x()`.
                if _is_scene_point(at_scene_pos):
                    center = at_scene_pos
                else:
                    center = self.view.mapToScene(self.view.viewport().rect().center())
                # Ревью-фикс v0.8.0 (#1): оффсеты — половины базового размера узла
                # (MIN_NODE_WIDTH=180 / MIN_NODE_HEIGHT=130 → 90/65), чтобы новый узел
                # центрировался под точкой клика, а не смещался вправо-вниз от курсора.
                data.x = center.x() - ServerNode.MIN_NODE_WIDTH / 2
                data.y = center.y() - ServerNode.MIN_NODE_HEIGHT / 2
                # v0.8.3: узел создаёт команда undo (push сам выполняет redo)
                from modules.undo_commands import CmdAddRemoveNode
                self._push_command(CmdAddRemoveNode(self, self.scene, data, "add"))
                node = self.scene.get_node(data.id)
                self.refresh_sidebar()
                self._sync_status_targets()  # v0.7.1: новый узел — в план проверок
                if self.log:
                    self.log.info("Server added", extra={"alias": data.alias, "host": data.host})
                self.statusBar().showMessage(self.t("status.server_added", alias=data.alias))
                self._mark_dirty()  # ← unsaved changes
                # v0.9.5.6: «Подключиться по SSH» из диалога добавления — узел
                # уже создан, сразу открываем SSH-диалог (пароль предзаполнен).
                if getattr(dlg, "_connect_after_accept", False):
                    self._run_ssh_connect(node, prefill_password=dlg.password.text())
        except Exception as e:
            if self.log:
                self.log.exception(f"Error adding server {getattr(data, 'alias', '?')}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.add_failed", error=str(e)))

    def _import_servers_from_txt(self):
        """v0.9.5.5: массовый импорт серверов из текстового файла.

        Формат: по одному хосту в строке (IP или DNS-имя), '#'/'//' — комментарии.
        IP → host=IP; имя → резолвим в IP (поле `ip`), host остаётся именем.
        Дубликаты (уже на карте или повтор в файле) пропускаются. Один узел undo —
        вся пачка добавляется/откатывается одной командой CmdAddRemoveNodeBatch.

        v1.1.2RC2 (N6): DNS-резолв имён — вне GUI-потока (HostResolverThread,
        прогресс в статус-баре): файл с десятками имён при недоступном резолвере
        не замораживает интерфейс. IP-адреса резолва не требуют — добавляются сразу.
        """
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.import_servers"), "",
            "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.import_servers_failed", error=str(e)))
            return

        from services.host_importer import parse_hosts_file, is_ip_address
        entries, file_dups = parse_hosts_file(text), []
        # Дедупликация строк файла (без учёта регистра)
        seen, unique_entries = set(), []
        for e in entries:
            if e.lower() in seen:
                continue
            seen.add(e.lower())
            unique_entries.append(e)

        # Хосты/IP, уже присутствующие на карте — тоже дубликаты
        existing = set()
        for node in self.scene.nodes():
            d = node.data
            existing.add((d.host or "").lower())
            if d.ip:
                existing.add(d.ip.lower())

        pending, skipped = [], len(file_dups)
        for entry in unique_entries:
            if entry.lower() in existing:
                skipped += 1
                continue
            pending.append(entry)
            existing.add(entry.lower())

        if not pending:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.import_servers_result", added=0, skipped=skipped))
            return

        dns_entries = [e for e in pending if not is_ip_address(e)]
        if not dns_entries:
            # Только IP-адреса — резолв не нужен, собираем синхронно (без потока)
            self._finish_import_from_txt(pending, {}, path, skipped)
            return

        # v1.1.2RC2 (N6): имена — в отдельный поток; GUI остаётся отзывчивым,
        # прогресс резолва виден в статус-баре. Контекст пачки держим на окне —
        # resolved_map придёт queued-сигналом уже после возврата из этого метода.
        from services.host_importer import HostResolverThread
        thread = HostResolverThread(dns_entries, parent=self)
        self._import_resolve_thread = thread  # держим ссылку — поток не должен стать orphan'ом
        self._import_pending = pending
        self._import_path = path
        self._import_skipped = skipped
        thread.progress.connect(self._on_import_resolve_progress)
        thread.resolved_map.connect(self._on_import_resolved)
        self.statusBar().showMessage(
            self.t("status.import_resolving", done=0, total=len(dns_entries)))
        thread.start()

    def _on_import_resolve_progress(self, done: int, total: int):
        """v1.1.2RC2 (N6): прогресс DNS-резолва импорта — в статус-баре."""
        try:
            self.statusBar().showMessage(
                self.t("status.import_resolving", done=done, total=total))
        except RuntimeError:
            pass  # Qt teardown — окно уже уничтожено

    def _on_import_resolved(self, resolved_map):
        """v1.1.2RC2 (N6): резолв завершён (GUI-поток) — собираем узлы и добавляем."""
        thread = getattr(self, "_import_resolve_thread", None)
        if thread is not None:
            self._import_resolve_thread = None
            try:
                thread.deleteLater()  # run() завершён — поток можно отдать Qt
            except RuntimeError:
                pass  # Qt teardown
        pending = list(getattr(self, "_import_pending", None) or [])
        path = getattr(self, "_import_path", None) or ""
        skipped = int(getattr(self, "_import_skipped", 0) or 0)
        self._import_pending = None
        self._import_path = None
        self._import_skipped = 0
        if not pending:
            return  # окно закрылось во время резолва (stop()) — импорт не доведён
        try:
            self._finish_import_from_txt(pending, dict(resolved_map or {}), path, skipped)
        except RuntimeError:
            pass  # Qt teardown — виджеты уже уничтожены

    def _finish_import_from_txt(self, pending, resolved_map, path, skipped):
        """v1.1.2RC2 (N6): сборка ServerData + раскладка сеткой + одна undo-команда.

        `resolved_map` — {имя: IP или None} из HostResolverThread; IP-адреса в
        нём отсутствуют (резолва не требовали) и берутся как есть.
        """
        import uuid as _uuid
        from services.host_importer import is_ip_address
        from models.server import ServerData

        added_data = []
        for entry in pending:
            if is_ip_address(entry):
                host, ip = entry, entry
            else:
                host, ip = entry, resolved_map.get(entry) or ""
            data = ServerData(
                id=str(_uuid.uuid4())[:8],
                alias=entry,
                host=host,
                user="",
                password="",
                ip=ip,
            )
            added_data.append(data)

        # Раскладка импортированных узлов сеткой от центра видимой области
        center = self.view.mapToScene(self.view.viewport().rect().center())
        col_w, row_h, cols = ServerNode.MIN_NODE_WIDTH + 30, ServerNode.MIN_NODE_HEIGHT + 30, 6
        for i, data in enumerate(added_data):
            r, c = divmod(i, cols)
            data.x = center.x() - 90 + c * col_w
            data.y = center.y() - 65 + r * row_h

        from modules.undo_commands import CmdAddRemoveNodeBatch
        self._push_command(CmdAddRemoveNodeBatch(self, self.scene, added_data, "add"))
        self.refresh_sidebar()
        self._sync_status_targets()
        self._mark_dirty()
        if self.log:
            self.log.info(f"Imported {len(added_data)} servers from {path}")
        self.statusBar().showMessage(
            self.t("status.servers_imported", count=len(added_data)), 5000)
        QMessageBox.information(self, self.t("msg.success_title"),
                                self.t("msg.import_servers_result",
                                       added=len(added_data), skipped=skipped))

    def _add_connection(self, default_source_id=None, default_target_id=None):
        """Создать связь: диалог с выбором узлов, метки и типа (v0.7).

        Параметры prefill используются drag-режимом MapView (Shift+перетаскивание).
        """
        nodes = list(self.scene.nodes())
        if len(nodes) < 2:
            QMessageBox.information(self, self.t("msg.info_title"), 
                                  self.t("validation.min_servers"))
            return

        try:
            dlg_cls = host_attr(self, "ConnectionDialog")
            if dlg_cls is None:
                raise RuntimeError("ConnectionDialog недоступен в модуле MainWindow")
            dlg = dlg_cls(
                nodes, self,
                default_source_id=default_source_id,
                default_target_id=default_target_id,
            )
            if dlg.exec() == QDialog.Accepted:
                # get_connection() возвращает id узлов (строки), а не объекты ServerNode;
                # 4-й элемент — тип связи (v0.7)
                src, tgt, lbl, ctype = dlg.get_connection()
                if src == tgt:
                    QMessageBox.warning(self, self.t("msg.error_title"), 
                                      self.t("validation.self_connection"))
                    return
                # v0.8.3: связь создаёт undo-команда (push сам выполняет redo)
                from modules.undo_commands import CmdAddRemoveConnection
                self._push_command(CmdAddRemoveConnection(
                    self, self.scene, src, tgt, lbl, ctype, "add"))
                if not self.scene.has_connection(src, tgt):
                    # команда не смогла создать (узлы исчезли?) — как раньше, предупреждение
                    QMessageBox.warning(self, self.t("msg.error_title"),
                                        self.t("validation.connection_error"))
                    return
                arrow = None
                if self.log:
                    src_node = self.scene.get_node(src)
                    tgt_node = self.scene.get_node(tgt)
                    if src_node and tgt_node:
                        self.log.info("Connection added", extra={"source": src_node.data.alias, "target": tgt_node.data.alias})
                self.statusBar().showMessage(self.t("status.connection_added"))
                self._update_counts_label()  # UI polish: счётчик связей в статус-баре
                self._mark_dirty()  # ← unsaved changes
        except Exception as e:
            if self.log:
                self.log.exception("Error adding connection")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.create_connection_failed", error=str(e)))

    def _duplicate_node(self, node: "ServerNode", offset: float = 40.0):
        """Ctrl+D / ПКМ: копия узла (все поля, кроме id) со смещением.

        Пароль в JSON не хранится — он лежит в keyring по server_id, поэтому
        для копии загружаем пароль исходника и сохраняем под НОВЫМ id.
        Возвращает новый ServerNode или None (узел не найден).
        """
        if node is None or node.scene() is None:
            return None
        import copy as _copy
        data = _copy.deepcopy(node.data)
        data.x = float(node.data.x) + offset
        data.y = float(node.data.y) + offset
        # новый уникальный id
        import uuid as _uuid
        while True:
            new_id = str(_uuid.uuid4())[:8]
            if not self.scene.has_node(new_id):
                break
        data.id = new_id
        # v0.9.3: пароль из keyring по server_id нового узла (задача #1)
        try:
            from services.credential_manager import get_credential_manager
            cm = get_credential_manager()
            pw = cm.load_password(node.data.id)
            if pw:
                cm.save_password(new_id, pw)
        except Exception:  # noqa: BLE001 — keyring недоступен: копия без пароля
            pass
        from modules.undo_commands import CmdAddRemoveNode
        self._push_command(CmdAddRemoveNode(self, self.scene, data, "add"))
        new_node = self.scene.get_node(new_id)
        self.refresh_sidebar()
        self._sync_status_targets()
        self.statusBar().showMessage(
            self.t("status.server_duplicated", alias=data.alias)
            if self._i18n_available else f"Duplicated: {data.alias}")
        self._mark_dirty()  # ← unsaved changes
        return new_node

    def _duplicate_selected_node(self):
        """Ctrl+D: продублировать выделенный узел; новый узел становится выделенным."""
        node = self.scene.get_selected_node()
        if not node:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return None
        new_node = self._duplicate_node(node)
        if new_node is not None:
            self._select_node(new_node)
        return new_node

    def selected_nodes(self) -> list:
        """v0.9.3: все выделенные узлы карты (в порядке сцены)."""
        try:
            return [i for i in self.scene.selectedItems() if isinstance(i, ServerNode)]
        except RuntimeError:
            return []

    def _delete_selected_nodes(self):
        """v0.9.3: удалить ВСЕ выделенные узлы (каждый через guarded-путь)."""
        nodes = self.selected_nodes()
        if not nodes:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return False
        # одно подтверждение на всю группу
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Подтверждение",
            self.t("msg.confirm_delete_many").format(count=len(nodes))
            if self._i18n_available else f"Удалить серверы ({len(nodes)})?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        deleted = 0
        for node in list(nodes):
            if node.scene() is None:
                continue  # уже удалён вместе со своей стрелкой ранее в цикле
            if not self._ensure_worker_done(node.data.id):
                continue
            alias = node.data.alias
            arrows = [
                (a.source.data.id, a.target.data.id, a.label_text, a.connection_type)
                for a in self.scene.arrows()
                if a.source is node or a.target is node
            ]
            from modules.undo_commands import CmdAddRemoveNode
            self._push_command(CmdAddRemoveNode(self, self.scene, node.data, "remove", arrows))
            deleted += 1
            if self.log:
                self.log.info("Server deleted (multi)",
                              extra={"alias": alias, "host": node.data.host})
        if deleted:
            self.refresh_sidebar()
            self._sync_status_targets()
            self.statusBar().showMessage(
                self.t("status.servers_deleted_multi", count=deleted)
                if self._i18n_available else f"Deleted {deleted} servers")
            self._mark_dirty()  # ← unsaved changes
        return True

    def _connect_selected_nodes(self):
        """v0.9.3: создать связи между всеми парами выделенных узлов (полный граф).

        Каждый узел соединяется с каждым (без петель и дублей); тип связи —
        по умолчанию, метка пустая. Undo откатывает всё одной командой.
        """
        nodes = self.selected_nodes()
        if len(nodes) < 2:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("validation.min_servers"))
            return False
        ids = [n.data.id for n in nodes]
        created = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                src, tgt = ids[i], ids[j]
                if self.scene.has_connection(src, tgt):
                    continue
                arrow = self.scene.add_connection(src, tgt)
                if arrow is not None:
                    created.append((src, tgt))
        if not created:
            return False
        from modules.undo_commands import CmdConnectSelected
        self._push_command(CmdConnectSelected(self, self.scene, created))
        self._update_counts_label()
        self.statusBar().showMessage(
            self.t("status.connections_created_multi", count=len(created))
            if self._i18n_available else f"Created {len(created)} connections")
        self._mark_dirty()  # ← unsaved changes
        return True

    def _copy_node_info(self, node: "ServerNode", what: str = "ip"):
        """Скопировать IP или hostname узла в буфер обмена (v0.7.3).

        AUDIT v0.7.2 (средняя #6): обратный DNS (gethostbyaddr) выполняется в отдельном
        потоке — при недоступном резолвере GUI-поток раньше замерзал на таймауте DNS.
        v0.9.9.3: поток вынесен в services/diagnostics.py (ReverseDnsThread).
        """
        if node is None:
            return

        def _copy(value: str, what_: str):
            QApplication.clipboard().setText(value)
            self.statusBar().showMessage(self.t("status.copied_to_clipboard", value=value))
            if self.log:
                self.log.info(f"Copied {what_} to clipboard", extra={"alias": node.data.alias})

        if what == "hostname":
            host = node.data.host
            from services.diagnostics import ReverseDnsThread  # v0.9.9.3: был вложенным классом

            thread = ReverseDnsThread(host)

            def _on_dns_done(name):
                if getattr(self, "_dns_thread", None) is thread:
                    self._dns_thread = None
                _copy(name, "hostname")

            thread.resolved.connect(_on_dns_done)
            self._dns_thread = thread  # держим ссылку — поток не должен стать orphan'ом
            thread.start()
            return

        # "ip" и прочие варианты: сетевых вызовов нет — синхронно (и так ожидает smoke-тест)
        _copy(node.data.ip.strip() or node.data.host, what)

    def _ping_node(self, node: "ServerNode"):
        """Ping узла в отдельном потоке без блокировки GUI (v0.7.3).

        Windows: `ping -n 3`, POSIX: `ping -c 3`. Результат — в статус-бар.
        v0.9.9.3: поток вынесен в services/diagnostics.py (PingThread).
        """
        if node is None:
            return

        # AUDIT v0.7.2 (средняя #8): не затираем ещё работающий ping — повторный запрос
        # игнорируем (раньше ссылка перезаписывалась, а старый поток оставался orphan'ом).
        if self._ping_thread is not None and self._ping_thread.isRunning():
            self.statusBar().showMessage(self.t("status.ping_running", host=node.data.host))
            return

        from services.diagnostics import PingThread  # v0.9.9.3: был вложенным классом
        ping_thread = PingThread(node.data.host)

        def _on_ping_done(ok, text):
            if ok:
                self.statusBar().showMessage(text)
            else:
                QMessageBox.information(self, self.t("msg.info_title"), text)
            # Чистим ссылку только на СВОЙ поток: запоздалый старый ping не должен
            # обнулять ссылку уже запущенного нового (AUDIT v0.7.2, средняя #8).
            if getattr(self, "_ping_thread", None) is ping_thread:
                self._ping_thread = None

        ping_thread.finished_ping.connect(_on_ping_done)
        self._ping_thread = ping_thread
        ping_thread.start()
        self.statusBar().showMessage(self.t("status.ping_running", host=node.data.host))

    def _edit_connection(self, arrow):
        """Диалог изменения метки и типа связи (v0.7.3)."""
        if arrow is None:
            return
        try:
            from dialogs.connection_dialog import EditConnectionDialog
            dlg = EditConnectionDialog(arrow, self)
            if dlg.exec() == QDialog.Accepted:
                label, ctype = dlg.get_connection()
                # v0.8.3: правка связи (метка/тип) — undo-команда
                from modules.undo_commands import CmdEditConnection
                self._push_command(CmdEditConnection(
                    self, arrow, arrow.label_text, arrow.connection_type, label, ctype))
                self.statusBar().showMessage(self.t("status.connection_updated"))
                self._mark_dirty()  # ← unsaved changes
        except Exception as e:
            if self.log:
                self.log.exception("Error editing connection")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.update_failed", error=str(e)))

    def _remove_connection(self, arrow) -> bool:
        """Удалить связь с подтверждением (v0.7.3). Возвращает True при удалении."""
        if arrow is None:
            return False
        src_alias = arrow.source.data.alias
        tgt_alias = arrow.target.data.alias
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Подтверждение",
            self.t("msg.confirm_delete_connection").format(src=src_alias, tgt=tgt_alias)
            if self._i18n_available else f"Удалить связь '{src_alias}' → '{tgt_alias}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return False
        # v0.8.3: удаление связи — undo-команда
        from modules.undo_commands import CmdAddRemoveConnection
        src_id = arrow.source.data.id
        tgt_id = arrow.target.data.id
        lbl = arrow.label_text
        ctype = arrow.connection_type
        self._push_command(CmdAddRemoveConnection(self, self.scene, src_id, tgt_id,
                                                  lbl, ctype, "remove"))
        self.statusBar().showMessage(self.t("status.connection_deleted"))
        self._update_counts_label()  # UI polish: счётчик связей в статус-баре
        self._mark_dirty()  # ← unsaved changes
        if self.log:
            self.log.info("Connection deleted",
                          extra={"source": src_alias, "target": tgt_alias})
        return True

    def _ensure_worker_done(self, server_id: str) -> bool:
        """Патч v0.6.x: дождаться завершения SSHWorker перед удалением узла.

        Если поток всё ещё выполняется и не успевает завершиться за таймаут —
        показать предупреждение и отменить удаление (иначе success/error могли бы
        прилететь в уничтоженный диалог / данные удалённого узла).
        """
        try:
            from modules.ssh_worker import wait_for_worker as _wait_worker
            if not _wait_worker(server_id, 5000):
                QMessageBox.warning(self, self.t("msg.error_title"), self.t("msg.worker_busy"))
                return False
        except Exception:
            pass  # реестр недоступен — не блокируем удаление из-за этого
        return True

    def _remove_node_guarded(self, node: "ServerNode") -> bool:
        """Единый путь удаления узла: подтверждение → guard SSHWorker → remove.

        Используется кнопкой сайдбара, клавишей Delete (MapView) и контекстным
        меню узла (v0.7.3). Возвращает True, если удаление произошло.
        """
        reply = QMessageBox.question(
            self, 
            self.t("dialog.confirm_delete") if self._i18n_available else "Подтверждение",
            f"{self.t('msg.confirm_delete').format(alias=node.data.alias)}" if self._i18n_available else f"Удалить сервер '{node.data.alias}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        if not self._ensure_worker_done(node.data.id):
            return False
        alias = node.data.alias
        host = node.data.host
        # v0.8.3: захват стрелок узла ДО удаления — undo восстановит их вместе с узлом
        arrows = [
            (a.source.data.id, a.target.data.id, a.label_text, a.connection_type)
            for a in self.scene.arrows()
            if a.source is node or a.target is node
        ]
        from modules.undo_commands import CmdAddRemoveNode
        self._push_command(CmdAddRemoveNode(self, self.scene, node.data, "remove", arrows))
        self.refresh_sidebar()
        self._sync_status_targets()  # v0.7.1: узла больше нет — убрать из плана проверок
        if self.log:
            self.log.info("Server deleted", extra={"alias": alias, "host": host})
        self.statusBar().showMessage(self.t("status.server_deleted", alias=alias))
        self._mark_dirty()  # ← unsaved changes
        return True
