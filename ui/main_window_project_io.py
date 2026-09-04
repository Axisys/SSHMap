"""ProjectIOMixin — кластер «проект: создание/загрузка/сохранение/автосохранение/бэкапы».

v1.1.4 (ROADMAP v1.1.4, задача 1): вынесен из ui/main_window.py в рамках серии
«Гигиена main_window.py». Паттерн «модуль + колбэки» (прецеденты v0.9.9.4 сайдбар,
v0.9.9.3 diagnostics): миксин — только методы, MainWindow остаётся фасадом,
публичный API не меняется; имена методов и точки вызова не трогались.

Владение общим состоянием (AUDIT §3, зафиксировано комментарием):
  * ``self._project_file`` — путь открытого файла проекта (None = новый несохранённый);
  * ``self._dirty`` — маркер несохранённых изменений (« [*]» в заголовке);
  * ``self._autosave_timer`` — QTimer автосохранения (создаётся в MainWindow.__init__,
    тик — ``_autosave_tick`` ниже).
Миксин НЕ импортирует ui.main_window (цикл) — только duck-typing по инстансу.
"""
import os

from PySide6.QtWidgets import QMessageBox, QFileDialog

try:
    from ..models.server import server_data_from_dict
except ImportError:
    from models.server import server_data_from_dict

try:
    from ..graphics.node_group import NodeGroup
    from ..graphics.connection_arrow import DEFAULT_CONNECTION_TYPE
except ImportError:
    from graphics.node_group import NodeGroup
    from graphics.connection_arrow import DEFAULT_CONNECTION_TYPE


class ProjectIOMixin:
    """Методы проекта (файл): new/open/load/save/autosave/backups/restore."""

    def _new_project(self):
        # Заголовок собирается единым методом — раньше сюда дописывался
        # «[Новый проект]» к уже полному заголовку и он нарастал с каждым разом.
        self.scene.clear_all()
        self._project_file = None
        self._dirty = False
        self._reset_undo_stack()  # v0.8.3: новый проект — чистый undo-стек
        self.refresh_sidebar()
        self._close_map_search_if_open()  # v0.9.8: смена контекста — поиск закрываем
        self._sync_status_targets()  # v0.7.1: сцена пуста — план проверок пуст
        self._update_window_title()
        if self.log:
            self.log.info("New project created")

    def _import_project_raw(self, raw: dict):
        """Импортировать уже загруженный JSON-проект в сцену.

        Вынесен из _open_project() для тестов и backward-compat: файлы v0.6
        не имеют поля "type" у связей — подставляется тип по умолчанию (SSH).
        """
        self.scene.clear_all()

        # v0.8.1: группы ДО узлов — членство геометрическое и пересчитывается в
        # MapScene.resync_group_members при каждом add_server, поэтому порядок не важен
        # для корректности; создаём раньше ещё и ради z-порядка (файловый = исходный).
        # Backward-compat: проекты до v0.8.1 не имеют ключа "groups" → пусто.
        for raw_g in raw.get('groups', []):
            if not isinstance(raw_g, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                grp = self.scene.add_group(
                    name=str(raw_g.get("name") or ""),
                    x=float(raw_g.get("x") or 0.0),
                    y=float(raw_g.get("y") or 0.0),
                    width=float(raw_g.get("width") or NodeGroup.DEFAULT_W),
                    height=float(raw_g.get("height") or NodeGroup.DEFAULT_H),
                    group_id=str(raw_g.get("id") or "")[:8] or None,
                )
            except (TypeError, ValueError):
                continue
            self._connect_group_signals(grp)

        for s in raw.get('servers', []):
            # v0.9.3 fix: per-record try/except, как у notes/groups выше и как
            # обещано в доках — одна битая запись не роняет загрузку всего проекта.
            if not isinstance(s, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                # Единый путь десериализации: сохраняет key_path и корректно
                # игнорирует лишние ключи (бывш. AUDIT.md, средняя #5 — см. CHANGELOG.md).
                server_data = server_data_from_dict(s)
            except (TypeError, ValueError, KeyError) as e:
                if self.log:
                    self.log.warning("Skipping broken server record on load", extra={"error": str(e)})
                continue
            self.scene.add_server(server_data)

        for c in raw.get('connections', []):
            # v0.9.3 fix: та же защита, что у servers — отсутствие source_id/target_id
            # в одной записи не должно убивать весь проект.
            if not isinstance(c, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                ctype = c.get("type", DEFAULT_CONNECTION_TYPE)  # v0.6: нет поля type → SSH
                src_id, tgt_id = c["source_id"], c["target_id"]
                arrow = self.scene.add_connection(src_id, tgt_id, c.get("label", ""), ctype)
            except KeyError as e:
                if self.log:
                    self.log.warning("Skipping broken connection record on load", extra={"error": str(e)})
                continue
            # v1.0-fix (audit #9): add_connection возвращает None и для дубля, и для
            # неизвестных id узлов — раньше битые ссылки отбрасывались без следа;
            # теперь warning в лог (дубль — штатный случай, не логируем).
            if arrow is None and not self.scene.has_connection(src_id, tgt_id):
                if self.log:
                    self.log.warning("Skipping connection with unknown node id on load",
                                     extra={"source_id": str(src_id), "target_id": str(tgt_id)})

        # v0.7.1: после загрузки проекта узлы попадают в план периодических
        # проверок; немедленный раунд запускает _open_project (user path), а не
        # здесь — чтобы headless-тесты без event loop не плодили фоновых потоков.
        self._sync_status_targets()

        # v0.7.2: заметки из файла. Backward-compat: проекты до v0.7.2 не имеют
        # ключа "notes" — raw.get(...) даёт пустой список, всё остаётся как было.
        for raw_note in raw.get('notes', []):
            if not isinstance(raw_note, dict):
                continue  # битая запись — пропускаем без падения загрузки
            try:
                note_id = str(raw_note.get("id") or "")[:8] or None
                note = self.scene.add_note(
                    text=str(raw_note.get("text") or ""),
                    x=float(raw_note.get("x") or 0.0),
                    y=float(raw_note.get("y") or 0.0),
                    width=float(raw_note.get("width") or 240.0),
                    height=float(raw_note.get("height") or 160.0),
                    note_id=note_id,
                )
            except (TypeError, ValueError):
                continue
            self._connect_note_signals(note)

        # v0.9.1: фон из файла. Backward-compat: проекты до v0.9.1 не имеют ключа
        # "background" → raw.get(...) = None, карта открывается без фона.
        # Отсутствующий файл изображения тоже не мешает загрузке (warning в лог).
        try:
            from graphics.background_image import BackgroundImage as _BgCls
        except ImportError:
            from background_image import BackgroundImage as _BgCls
        bg_raw = raw.get('background')
        if isinstance(bg_raw, dict):
            bg = _BgCls.try_from_dict(bg_raw)
            if bg is not None:
                self.scene.addItem(bg)
                self.scene._background = bg
                self._connect_background_signals(bg)
            elif self.log:
                self.log.warning("Background image missing on disk, skipped", extra={
                    "path": str(bg_raw.get("path") or "")})

        # v0.8.1: страховочный пересчёт членства групп после полной сборки сцены
        # (обычно состав уже корректен — resync шёл при каждом add_server/add_group).
        if self.scene.groups():
            self.scene.resync_group_members()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.open"), "", "JSON Files (*.json *.sshmap)")
        if not path:
            return
        self._load_project_at(path)

    def _load_project_at(self, path: str, skip_autosave_prompt: bool = False) -> bool:
        """v0.9.7: общий путь загрузки (Файл→Открыть и восстановление из бэкапа/autosave).

        ROADMAP v0.9.7 #3: если автосохранение СВЕЖЕЕ файла на диске — предложить
        восстановить его ПЕРЕД загрузкой (ответ «Да» подменяет только загружаемое в
        память содержимое; файл на диске меняется лишь при последующем сохранении).
        skip_autosave_prompt — путь явного восстановления (пользователь уже выбрал
        источник; повторный промпт о более свежем autosave был бы дезориентирующим).
        """
        try:
            from storage.project import load_project as _load_project
            raw = _load_project(path)

            # v0.9.7 #3: автосохранение новее файла → предложение восстановить
            if not skip_autosave_prompt:
                try:
                    from storage import autosave as _as_mod
                    if _as_mod.autosave_is_newer(path):
                        auto_raw = _as_mod.read_autosave(path)
                        if auto_raw is not None:
                            from datetime import datetime as _dt
                            ts = _dt.fromtimestamp(_as_mod.autosave_mtime(path)).strftime(
                                "%Y-%m-%d %H:%M:%S")
                            reply = QMessageBox.question(
                                self, self.t("dialog.autosave_found"),
                                self.t("msg.autosave_newer", time=ts),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                            if reply == QMessageBox.Yes:
                                raw = auto_raw  # загружаем автосохранение вместо файла
                except Exception as e:  # noqa: BLE001 — проверка опциональна, открытие не роняем
                    if self.log:
                        self.log.warning(f"Autosave check failed: {e}")

            server_count = len(raw.get('servers', []))
            conn_count = len(raw.get('connections', []))

            self._import_project_raw(raw)

            # UI polish: восстановить сохранённое состояние вида (zoom + center).
            # _do_save() эти поля в JSON пишет, а старый код при открытии их игнорировал.
            try:
                self.view.set_zoom_and_center(
                    raw.get("zoom"), raw.get("center_x", 0.0), raw.get("center_y", 0.0))
            except Exception as e:  # noqa: BLE001 — битые значения не мешают открытию
                if self.log:
                    self.log.warning(f"Failed to restore view state: {e}")

            # v0.7.1: сразу после загрузки — немедленный раунд проверок статусов
            checker = getattr(self, "_status_checker", None)
            if checker is not None and not checker.is_busy:
                try:
                    checker.start_round()
                except Exception as e:
                    if self.log:
                        self.log.warning(f"StatusChecker round failed: {e}")

            # Load passwords from keyring if available
            try:
                from services.credential_manager import get_credential_manager as _get_cm
                cm = _get_cm()
                for node in list(self.scene.nodes()):
                    sid = getattr(node.data, 'id', '')
                    cached_pw = cm.load_password(sid)
                    if cached_pw:
                        node.data.password = cached_pw
            except Exception as e:
                if self.log:
                    self.log.warning(f"Failed to load passwords from keyring: {e}")
                QMessageBox.warning(
                    self, self.t("msg.error_title"),
                    self.t("msg.passwords_from_keyring_load_failed"))

            self.refresh_sidebar()
            self._close_map_search_if_open()  # v0.9.8: новый проект — поиск закрываем
            self._project_file = path
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: загрузка — новая точка отсчёта undo
            self._update_window_title()
            self.statusBar().showMessage(self.t("status.project_loaded"))

            if self.log:
                self.log.info("Project loaded", extra={"file": path, "servers": server_count})
            return True
        except Exception as e:
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.load_failed", error=str(e)))
            return False

    def _save_project(self) -> bool:
        """Сохранить текущий проект. Возвращает True, если сохранение удалось."""
        if self._project_file:
            return self._do_save(self._project_file)
        return self._save_project_as()

    def _save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.save_as"), "", "JSON Files (*.json *.sshmap)")
        if not path:
            return False  # пользователь отменил — не ошибка, но и не сохранение
        saved = self._do_save(path)
        if saved:
            self._project_file = path
        return saved

    def _serialize_project_data(self) -> dict:
        """v0.9.7: текущая сцена → dict проекта JSON (общий для save и автосохранения).

        Сериализатор — storage.project.serialize_scene (формат один; паролей в
        нём нет: server_data_to_dict их вырезает, ключи — в keyring).
        """
        from storage.project import serialize_scene as _serialize
        center = self.view.mapToScene(
            self.view.viewport().rect().center())  # AUDIT v0.7.2 (низкая #19): публичное свойство zoom ниже
        return _serialize(
            nodes={n.data.id: n for n in self.scene.nodes()},
            arrows=self.scene.arrows(),
            zoom=self.view.zoom,
            center_x=center.x(),
            center_y=center.y(),
            notes=self.scene.notes(),  # v0.7.2: массив заметок (публичный итератор)
            groups=self.scene.groups(),  # v0.8.1: массив групп (кластеры)
            background=self.scene.background(),  # v0.9.1: фон-изображение
        )

    def _do_save(self, path: str) -> bool:
        """Сохранить проект в файл. Пароли уходят в keyring (JSON — только без них)."""
        try:
            server_count = self.scene.node_count()
            arrow_count = self.scene.arrow_count()

            # Save non-empty passwords to keyring BEFORE clearing.
            # Результат проверяем: если keyring недоступен, пароль НЕ сбрасываем —
            # иначе он тихо сгорал (бывш. AUDIT.md, средняя #12 — см. CHANGELOG.md).
            from services.credential_manager import get_credential_manager as _get_cm
            cm = _get_cm()
            unsaved_aliases = []
            for node in list(self.scene.nodes()):
                pw = getattr(node.data, 'password', '')
                sid = getattr(node.data, 'id', '')
                if pw:  # only save non-empty passwords to keyring
                    saved_to_store = cm.is_available and bool(cm.save_password(sid, pw))
                    if saved_to_store:
                        node.data.password = ""  # clear in memory — пароль в хранилище
                    else:
                        unsaved_aliases.append(getattr(node.data, 'alias', sid))

            data = self._serialize_project_data()

            # v0.9.7 #2: кольцевой буфер бэкапов — ДОС перезаписи файла: версия
            # «до сохранения» уходит в слот 1 (откат на предыдущие версии). Сбой
            # бэкапа НЕ блокирует сохранение (страховка, а не условие).
            if os.path.isfile(path):
                try:
                    from storage import autosave as _as_mod
                    _n_backups = _as_mod.get_autosave_settings()["backup_count"]
                    _as_mod.rotate_backups(path, _n_backups)
                except Exception as e:  # noqa: BLE001 — см. выше: страховка не роняет save
                    if self.log:
                        self.log.warning(f"Backup rotation failed: {e}")

            from storage.project import write_project_json as _write_json
            _write_json(path, data)

            # Сброс маркера несохранённых изменений (бывш. AUDIT.md, средняя #7 — см. CHANGELOG.md)
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: сохранение — новая точка отсчёта undo
            self._update_window_title()

            if unsaved_aliases:
                QMessageBox.warning(
                    self, self.t("msg.error_title"),
                    "\n".join(self.t("msg.credentials_save_failed", alias=a) for a in unsaved_aliases))

            self.statusBar().showMessage(self.t("status.project_saved"))

            if self.log:
                self.log.info("Project saved", extra={
                    "file": path,
                    "servers": server_count,
                    "connections": arrow_count,
                })
            return True
        except Exception as e:
            # Restore passwords from keyring on failure so they're not lost
            try:
                from services.credential_manager import get_credential_manager as _get_cm2
                cm = _get_cm2()
                for node in list(self.scene.nodes()):
                    sid = getattr(node.data, 'id', '')
                    cached_pw = cm.load_password(sid)
                    if cached_pw:
                        node.data.password = cached_pw
            except Exception:
                pass

            if self.log:
                self.log.exception(f"Failed to save project {path}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.save_failed", error=str(e)))
            return False

    # ── v0.9.7: автосохранение + бэкапы (ROADMAP v0.9.7) ─────────────────────

    def _autosave_tick(self):
        """v0.9.7 #1: тик таймера — автосохранение только при dirty и открытом файле.

        Новый несохранённый проект (_project_file is None) НЕ автосохраняется:
        восстановить его было бы не на какой файл (ROADMAP #3 привязана к «открытому
        файлу»). Пароли в автосохранение не попадают — serialize_scene идёт через
        server_data_to_dict, который их вырезает (см. models/server.py).
        """
        if not self._dirty or not self._project_file:
            return
        try:
            from storage import autosave as _as_mod
            data = self._serialize_project_data()
            path = _as_mod.write_autosave(self._project_file, data)
            if self.log:
                self.log.info("Autosaved", extra={"file": path})
            try:
                from datetime import datetime
                ts = datetime.now().strftime("%H:%M:%S")
                self.statusBar().showMessage(self.t("status.autosaved", time=ts))
            except Exception:  # noqa: BLE001 — статус-бар не критичен для автосохранения
                pass
        except Exception as e:  # noqa: BLE001 — автосохранение страховка, сбой молчим в лог
            if self.log:
                self.log.warning(f"Autosave failed: {e}")

    def _restore_from_autosave(self):
        """v0.9.7 #3 (ручной путь): восстановить последнее автосохранение поверх проекта."""
        if not self._project_file:
            QMessageBox.information(
                self, self.t("msg.info_title"), self.t("msg.open_project_first"))
            return
        from storage import autosave as _as_mod
        src = _as_mod.autosave_path_for(self._project_file)
        if not os.path.isfile(src):
            QMessageBox.information(
                self, self.t("dialog.backups"), self.t("backups.empty"))
            return
        self._restore_from_source(src, self.t("backups.autosave"))

    def _backup_items(self) -> list:
        """v0.9.7 #2: строки для диалога бэкапов — автосохранение + слоты кольца (свежие первыми)."""
        if not self._project_file:
            return []
        from storage import autosave as _as_mod
        items = []
        auto_path = _as_mod.autosave_path_for(self._project_file)
        if os.path.isfile(auto_path):
            try:
                st = os.stat(auto_path)
                items.append({
                    "label": self.t("backups.autosave"),
                    "path": auto_path, "mtime": st.st_mtime, "size": st.st_size,
                })
            except OSError:
                pass
        for b in _as_mod.list_backups(self._project_file):
            items.append({
                "label": self.t("backups.backup", n=b["slot"]),
                "path": b["path"], "mtime": b["mtime"], "size": b["size"],
            })
        return items

    def _show_backups_dialog(self):
        """v0.9.7 #2: диалог с кольцевым буфером бэкапов (+ последнее автосохранение)."""
        if not self._project_file:
            QMessageBox.information(
                self, self.t("msg.info_title"), self.t("msg.open_project_first"))
            return
        items = self._backup_items()
        if not items:
            QMessageBox.information(
                self, self.t("dialog.backups"), self.t("backups.empty"))
            return
        try:
            from dialogs.backups_dialog import BackupsDialog
        except ImportError:  # flat-раскладка без пакета (паттерн main_window)
            from backups_dialog import BackupsDialog
        dlg = BackupsDialog(items, parent=self)
        dlg.restore_requested.connect(self._restore_from_source)
        dlg.exec()

    def _restore_from_source(self, src_path: str, label: str):
        """v0.9.7 #2/#3: единый путь восстановления — бэкап/автосохранение → файл проекта.

        Подтверждение (с предупреждением о несохранённых правках при dirty) →
        атомарная копия в файл проекта → повторная загрузка через _load_project_at
        (та же логика, что Файл→Открыть: undo-стек, dirty, ключи keyring, статусы).
        """
        if not self._project_file:
            return
        msg = (self.t("msg.confirm_restore_dirty") if self._dirty
               else self.t("msg.confirm_restore"))
        reply = QMessageBox.question(
            self, self.t("dialog.backups"), msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        try:
            from storage import autosave as _as_mod
            _as_mod.restore_to_project(src_path, self._project_file)
            ok = self._load_project_at(self._project_file, skip_autosave_prompt=True)
            if not ok:
                return  # ошибка уже показана (msg.load_failed)
            self.statusBar().showMessage(self.t("status.restored", source=label))
            if self.log:
                self.log.info("Project restored", extra={"source": src_path})
        except Exception as e:  # noqa: BLE001 — пользователь должен увидеть причину
            if self.log:
                self.log.exception(f"Failed to restore from {src_path}")
            QMessageBox.critical(
                self, self.t("msg.error_title"), self.t("msg.restore_failed", error=str(e)))
