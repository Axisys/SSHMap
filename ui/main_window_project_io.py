"""ProjectIOMixin — the "project: create/open/save/autosave/backups" cluster.

v1.1.4 (ROADMAP v1.1.4, task 1): moved out of ui/main_window.py as part of
the "main_window.py hygiene" series. "Module + callbacks" pattern
(precedents: v0.9.9.4 sidebar, v0.9.9.3 diagnostics): the mixin holds only
methods, MainWindow remains the facade, the public API is unchanged; method
names and call sites were not touched.

Ownership of shared state (AUDIT §3, pinned by this comment):
  * ``self._project_file`` — path of the open project file (None = new, unsaved);
  * ``self._dirty`` — unsaved-changes marker (" [*]" in the title);
  * ``self._autosave_timer`` — the autosave QTimer (created in
    MainWindow.__init__, tick — ``_autosave_tick`` below).
The mixin does NOT import ui.main_window (cycle) — duck-typing on the
instance only.
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
    """Project (file) methods: new/open/load/save/autosave/backups/restore."""

    def _new_project(self):
        # The title is built by a single method — earlier "[New project]"
        # was appended to an already full title and it grew with every call.
        self.scene.clear_all()
        self._project_file = None
        self._dirty = False
        self._reset_undo_stack()  # v0.8.3: new project — a clean undo stack
        self.refresh_sidebar()
        self._close_map_search_if_open()  # v0.9.8: context change — close the search
        self._sync_status_targets()  # v0.7.1: the scene is empty — the check plan is empty
        self._update_window_title()
        if self.log:
            self.log.info("New project created")

    def _import_project_raw(self, raw: dict):
        """Import an already-loaded JSON project into the scene.

        Extracted from _open_project() for tests and backward-compat: v0.6
        files have no "type" field on connections — the default type (SSH)
        is substituted.
        """
        self.scene.clear_all()

        # v0.8.1: groups BEFORE nodes — membership is geometric and is
        # recomputed in MapScene.resync_group_members on every add_server,
        # so the order does not affect correctness; groups are created
        # earlier also for the z-order (file order = original).
        # Backward-compat: projects before v0.8.1 have no "groups" key → empty.
        for raw_g in raw.get('groups', []):
            if not isinstance(raw_g, dict):
                continue  # broken record — skip without failing the load
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
            # v0.9.3 fix: per-record try/except, like for notes/groups above
            # and as promised in the docs — one broken record must not kill
            # the whole project load.
            if not isinstance(s, dict):
                continue  # broken record — skip without failing the load
            try:
                # The single deserialization path: preserves key_path and
                # correctly ignores extra keys (former AUDIT.md, medium #5 —
                # see CHANGELOG.md).
                server_data = server_data_from_dict(s)
            except (TypeError, ValueError, KeyError) as e:
                if self.log:
                    self.log.warning("Skipping broken server record on load", extra={"error": str(e)})
                continue
            self.scene.add_server(server_data)

        for c in raw.get('connections', []):
            # v0.9.3 fix: the same protection as for servers — a missing
            # source_id/target_id in one record must not kill the whole project.
            if not isinstance(c, dict):
                continue  # broken record — skip without failing the load
            try:
                ctype = c.get("type", DEFAULT_CONNECTION_TYPE)  # v0.6: no type field → SSH
                # v1.2.6: no bidirectional field (old files) → one-way;
                # a broken value (not a bool) is normalized via bool() without failing.
                bidir = bool(c.get("bidirectional", False))
                src_id, tgt_id = c["source_id"], c["target_id"]
                arrow = self.scene.add_connection(src_id, tgt_id, c.get("label", ""), ctype,
                                                  bidirectional=bidir)
            except KeyError as e:
                if self.log:
                    self.log.warning("Skipping broken connection record on load", extra={"error": str(e)})
                continue
            # v1.0-fix (audit #9): add_connection returns None both for a
            # duplicate and for unknown node ids — earlier broken references
            # were dropped without a trace; now there is a warning in the log
            # (a duplicate is a normal case — not logged).
            if arrow is None and not self.scene.has_connection(src_id, tgt_id):
                if self.log:
                    self.log.warning("Skipping connection with unknown node id on load",
                                     extra={"source_id": str(src_id), "target_id": str(tgt_id)})

        # v0.7.1: after a project load, the nodes enter the periodic check
        # plan; the immediate round is started by _open_project (user path),
        # not here — so headless tests without an event loop do not spawn
        # background threads.
        self._sync_status_targets()

        # v0.7.2: notes from the file. Backward-compat: projects before
        # v0.7.2 have no "notes" key — raw.get(...) gives an empty list,
        # everything stays as it was.
        for raw_note in raw.get('notes', []):
            if not isinstance(raw_note, dict):
                continue  # broken record — skip without failing the load
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
            # v1.2.4 (D8): pinned notes — optional "server_id" field.
            # Old files without the key → free notes; a broken reference
            # (node missing / not a string) → a warning in the log + the note
            # is free at its saved position. No undo command: the stack is
            # reset after the import (_reset_undo_stack).
            # v1.2.4-fix: the saved x/y of a pinned note is TRUSTED (it can be
            # moved with the mouse) — the offset from the anchor is computed
            # from it, so the note stays where it was left (keep_position=True).
            sid = raw_note.get("server_id")
            if isinstance(sid, str) and sid:
                srv = self.scene.get_node(sid)
                if srv is not None:
                    self.scene.attach_note_to_node(note, srv, keep_position=True)
                elif self.log:
                    self.log.warning("Note references missing server on load (kept free)",
                                     extra={"note": note.note_id, "server_id": sid})

        # v0.9.1: background from the file. Backward-compat: projects before
        # v0.9.1 have no "background" key → raw.get(...) = None, the map opens
        # without a background. A missing image file also does not block the
        # load (a warning in the log).
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

        # v0.8.1: a safety recompute of group membership after the scene is
        # fully assembled (usually the composition is already correct — resync
        # ran on every add_server/add_group).
        if self.scene.groups():
            self.scene.resync_group_members()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file.open"), "", "JSON Files (*.json *.sshmap)")
        if not path:
            return
        self._load_project_at(path)

    def _load_project_at(self, path: str, skip_autosave_prompt: bool = False) -> bool:
        """v0.9.7: the common load path (File→Open and restore from a backup/autosave).

        ROADMAP v0.9.7 #3: if the autosave is NEWER than the file on disk —
        offer to restore it BEFORE loading (answering "Yes" only replaces
        the in-memory content being loaded; the file on disk changes only
        on a later save). skip_autosave_prompt — the explicit restore path
        (the user already chose the source; a repeated prompt about a newer
        autosave would be disorienting).
        """
        try:
            from storage.project import load_project as _load_project
            raw = _load_project(path)

            # v0.9.7 #3: the autosave is newer than the file → offer a restore
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
                                raw = auto_raw  # load the autosave instead of the file
                except Exception as e:  # noqa: BLE001 — the check is optional, do not break opening
                    if self.log:
                        self.log.warning(f"Autosave check failed: {e}")

            server_count = len(raw.get('servers', []))
            conn_count = len(raw.get('connections', []))

            self._import_project_raw(raw)

            # UI polish: restore the saved view state (zoom + center).
            # _do_save() writes these fields to the JSON; the old code ignored
            # them on open.
            try:
                self.view.set_zoom_and_center(
                    raw.get("zoom"), raw.get("center_x", 0.0), raw.get("center_y", 0.0))
            except Exception as e:  # noqa: BLE001 — broken values must not block opening
                if self.log:
                    self.log.warning(f"Failed to restore view state: {e}")

            # v0.7.1: right after the load — an immediate status check round
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
            self._close_map_search_if_open()  # v0.9.8: a new project — close the search
            self._project_file = path
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: a load — a new undo reference point
            self._update_window_title()
            self.statusBar().showMessage(self.t("status.project_loaded"))

            if self.log:
                self.log.info("Project loaded", extra={"file": path, "servers": server_count})
            return True
        except Exception as e:
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.load_failed", error=str(e)))
            return False

    def _save_project(self) -> bool:
        """Save the current project. Returns True if the save succeeded."""
        if self._project_file:
            return self._do_save(self._project_file)
        return self._save_project_as()

    def _save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("file.save_as"), "", "JSON Files (*.json *.sshmap)")
        if not path:
            return False  # the user cancelled — not an error, but not a save either
        saved = self._do_save(path)
        if saved:
            self._project_file = path
        return saved

    def _serialize_project_data(self) -> dict:
        """v0.9.7: the current scene → a JSON project dict (shared by save and autosave).

        The serializer — storage.project.serialize_scene (one format; no
        passwords in it: server_data_to_dict strips them, the keys are in
        the keyring).
        """
        from storage.project import serialize_scene as _serialize
        center = self.view.mapToScene(
            self.view.viewport().rect().center())  # AUDIT v0.7.2 (low #19): the public zoom property below
        return _serialize(
            nodes={n.data.id: n for n in self.scene.nodes()},
            arrows=self.scene.arrows(),
            zoom=self.view.zoom,
            center_x=center.x(),
            center_y=center.y(),
            notes=self.scene.notes(),  # v0.7.2: the notes array (public iterator)
            groups=self.scene.groups(),  # v0.8.1: the groups array (clusters)
            background=self.scene.background(),  # v0.9.1: the background image
        )

    def _do_save(self, path: str) -> bool:
        """Save the project to a file. Passwords go to the keyring (the JSON has only the rest)."""
        try:
            server_count = self.scene.node_count()
            arrow_count = self.scene.arrow_count()

            # Save non-empty passwords to keyring BEFORE clearing.
            # The result is checked: if the keyring is unavailable the
            # password is NOT reset — otherwise it would silently vanish
            # (former AUDIT.md, medium #12 — see CHANGELOG.md).
            from services.credential_manager import get_credential_manager as _get_cm
            cm = _get_cm()
            unsaved_aliases = []
            for node in list(self.scene.nodes()):
                pw = getattr(node.data, 'password', '')
                sid = getattr(node.data, 'id', '')
                if pw:  # only save non-empty passwords to keyring
                    saved_to_store = cm.is_available and bool(cm.save_password(sid, pw))
                    if saved_to_store:
                        node.data.password = ""  # clear in memory — the password is in the store
                    else:
                        unsaved_aliases.append(getattr(node.data, 'alias', sid))

            data = self._serialize_project_data()

            # v0.9.7 #2: the ring buffer of backups — BEFORE overwriting the
            # file: the "pre-save" version goes to slot 1 (rollback to
            # previous versions). A backup failure does NOT block the save
            # (a safety net, not a condition).
            if os.path.isfile(path):
                try:
                    from storage import autosave as _as_mod
                    _n_backups = _as_mod.get_autosave_settings()["backup_count"]
                    _as_mod.rotate_backups(path, _n_backups)
                except Exception as e:  # noqa: BLE001 — see above: the safety net does not break save
                    if self.log:
                        self.log.warning(f"Backup rotation failed: {e}")

            from storage.project import write_project_json as _write_json
            _write_json(path, data)

            # Reset the unsaved-changes marker (former AUDIT.md, medium #7 — see CHANGELOG.md)
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: a save — a new undo reference point
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

    # ── v0.9.7: autosave + backups (ROADMAP v0.9.7) ─────────────────────

    def _autosave_tick(self):
        """v0.9.7 #1: the timer tick — autosave only when dirty and a file is open.

        A new unsaved project (_project_file is None) is NOT autosaved:
        there would be no file to restore it into (ROADMAP #3 is tied to
        the "open file"). Passwords do not enter the autosave —
        serialize_scene goes through server_data_to_dict, which strips them
        (see models/server.py).
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
            except Exception:  # noqa: BLE001 — the status bar is not critical for autosave
                pass
        except Exception as e:  # noqa: BLE001 — autosave is a safety net, log failures silently
            if self.log:
                self.log.warning(f"Autosave failed: {e}")

    def _restore_from_autosave(self):
        """v0.9.7 #3 (manual path): restore the latest autosave over the project."""
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
        """v0.9.7 #2: rows for the backup dialog — autosave + ring slots (newest first)."""
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
        """v0.9.7 #2: the dialog with the ring buffer of backups (+ the latest autosave)."""
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
        except ImportError:  # flat layout without the package (the main_window pattern)
            from backups_dialog import BackupsDialog
        dlg = BackupsDialog(items, parent=self)
        dlg.restore_requested.connect(self._restore_from_source)
        dlg.exec()

    def _restore_from_source(self, src_path: str, label: str):
        """v0.9.7 #2/#3: the single restore path — backup/autosave → project file.

        Confirmation (with a warning about unsaved edits when dirty) → an
        atomic copy into the project file → a reload via _load_project_at
        (the same logic as File→Open: undo stack, dirty, keyring keys,
        statuses).
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
                return  # the error was already shown (msg.load_failed)
            self.statusBar().showMessage(self.t("status.restored", source=label))
            if self.log:
                self.log.info("Project restored", extra={"source": src_path})
        except Exception as e:  # noqa: BLE001 — the user must see the reason
            if self.log:
                self.log.exception(f"Failed to restore from {src_path}")
            QMessageBox.critical(
                self, self.t("msg.error_title"), self.t("msg.restore_failed", error=str(e)))
