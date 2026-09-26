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

v1.3.3.6 (ROADMAP "Projects: open, recover, remember"):
  * the RECENT list (``recent_projects`` in config.json — see ``_recent_projects``);
  * the recovery path of an UNREADABLE project file (``_recover_unreadable_project``):
    the backup ring + the autosave are consulted automatically, but NOTHING is
    written without an explicit "Restore" click.
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


# v1.3.3.6 (ROADMAP task 1): the MRU list of the project files. ``config.json`` key,
# newest first, deduplicated by the normalized absolute path, missing files pruned on
# read. The cap is deliberately small: the File menu is a way back to yesterday's map,
# not a file browser (a welcome screen with a longer list is NOT in v1.3.3.6).
RECENT_PROJECTS_KEY = "recent_projects"
RECENT_PROJECTS_MAX = 10


class ProjectIOMixin:
    """Project (file) methods: new/open/load/save/autosave/backups/restore."""

    def _new_project(self):
        # The title is built by a single method — earlier "[New project]"
        # was appended to an already full title and it grew with every call.
        self.scene.clear_all()
        self._project_file = None
        self._dirty = False
        # v1.5rc3: a fresh document is nobody's example
        self._example_project = False
        self._reset_undo_stack()  # v0.8.3: new project — a clean undo stack
        self._set_emulated_statuses({})  # v1.5: a fresh document emulates nothing
        self.refresh_sidebar()
        self._close_map_search_if_open()  # v0.9.8: context change — close the search
        self._sync_status_targets()  # v0.7.1: the scene is empty — the check plan is empty
        self._update_window_title()
        if self.log:
            self.log.info("New project created")

    # ── v1.5rc3 (ROADMAP task 1): the example map ───────────────────────────────

    def _open_example_map(self) -> bool:
        """Load the DEMO project (`storage/example_project.py`) through the ordinary path.

        The ONE entry point of both surfaces (the empty state's second button and
        `Help → Open the example map`). It never touches the disk: the factory builds the
        same dict a project file would hold and hands it to `_load_project_at()` — the
        very method File → Open, a drop, the MRU and the recovery path use. So the demo
        gets the whole ordinary treatment (the groups/notes/arrows are rebuilt by the
        format's own code, the view state is applied, the undo stack is rebased, the
        keyring is consulted, a status round starts) and cannot drift from the format.

        Two consequences of loading a project that is NOT a file, both deliberate:

          * `_project_file` stays empty, so File → Save asks for a name — the demo
            becomes the user's own project the moment they save it (nothing is ever
            written to `~/.sshmap/` behind their back, and the map is NOT added to the
            Recent list: a demo is not "yesterday's work");
          * `_example_project` marks the window (the title says so) until a new/open/save
            clears it — the map is never confused with a user file.

        v1.5 (ROADMAP): the demo carries EMULATED statuses. `DEMO_STATUSES` is declared in
        the factory and applied HERE, after the load, through the ordinary
        `ServerNode.set_status(..., emulated=True)` — and the skip set is installed BEFORE
        the load, so the round that a project load always starts cannot probe them (it
        would repaint them `offline` within seconds). Both halves are undone by every
        other load and by a save: the emulation never leaves the demo map, and nothing is
        ever serialized (a status is a measurement, not data).
        """
        try:
            from storage.example_project import build_example_project, DEMO_STATUSES
        except ImportError:  # flat layout without the package
            from example_project import build_example_project, DEMO_STATUSES
        try:
            raw = build_example_project()
        except Exception as e:  # noqa: BLE001 — a broken factory must not kill the window
            if self.log:
                self.log.exception("Could not build the example project")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.load_failed", error=str(e)))
            return False
        # BEFORE the load: `_load_project_at()` starts a probe round, and a target list
        # that still holds the demo's ids would overwrite the emulation it is about to get.
        self._set_emulated_statuses(DEMO_STATUSES)
        ok = bool(self._load_project_at("", skip_autosave_prompt=True, raw=raw, example=True))
        if ok:
            self._apply_emulated_statuses()
        else:
            self._set_emulated_statuses({})
        return ok

    # ── v1.5 (ROADMAP): the EMULATED statuses of the demo map ───────────────────

    def _set_emulated_statuses(self, statuses: dict) -> None:
        """Remember which node ids carry an EMULATED status and keep the checker in step.

        v1.5 (ROADMAP): ONE place owns the emulation state. `statuses` is the demo's
        declaration (`storage/example_project.DEMO_STATUSES`) while the example map is the
        open project, and an EMPTY mapping for every other project — so the skip set of
        `StatusChecker` (`set_skip_ids`, filtered in its `_subset()`) can never outlive the
        demo. The checker may be absent (a headless test, a stripped build): the state is
        kept either way, because it is what `_apply_emulated_statuses()` reads.
        """
        self._emulated_statuses = dict(statuses or {})
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return
        try:
            checker.set_skip_ids(self._emulated_statuses)
        except (AttributeError, RuntimeError):
            pass  # a stripped checker / Qt teardown — the emulation is a label, not a crash

    def _apply_emulated_statuses(self) -> int:
        """Paint the declared EMULATED statuses on the loaded cards (v1.5).

        Through the ORDINARY `set_status(..., emulated=True)` path: the card does
        everything else (the colour, the declared shape, the "demo" marker, the suppressed
        age) and this method owns nothing but the declaration. Called by
        `_open_example_map()` right after the load, when the map already holds the demo's
        nodes; returns how many cards were painted (the topical test's seam).
        """
        painted = 0
        for sid, status in dict(getattr(self, "_emulated_statuses", None) or {}).items():
            node = self.scene.get_node(sid)
            if node is None:
                continue  # a declaration for a node this project does not hold
            try:
                node.set_status(status, emulated=True)
            except (RuntimeError, AttributeError):
                continue  # Qt teardown — a repaint is cosmetic
            painted += 1
        if painted:
            self._update_counts_label()   # the counters tell the truth of the MAP
        return painted

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
                    # v1.4.2 (ROADMAP task 5): the FOLD state — optional keys, written
                    # only while a group is folded. The member badges arrive as ordinary
                    # server records with their saved positions, so the group is rebuilt
                    # with the flag alone (no re-layout: the file holds the grid).
                    collapsed=bool(raw_g.get("collapsed")),
                    expanded_width=raw_g.get("expanded_width"),
                    expanded_height=raw_g.get("expanded_height"),
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

    # ── v1.3.3.6 (ROADMAP task 1): Recent projects (MRU) ────────────────────
    #
    # Storage — the `recent_projects` key of ~/.sshmap/config.json (merge-write, like
    # every other settings key). The list is the raw material of the "File → Recent"
    # submenu: it is pruned on READ (a project moved or deleted on disk must not leave
    # a dead entry behind) and every read rebuilds it from the config, so the menu and
    # the config can never drift apart.

    def _recent_projects(self) -> list:
        """The MRU list: newest first, deduplicated, capped, missing files pruned.

        A broken value (not a list / not strings inside) is IGNORED — the same
        "broken config value → the default" rule as everywhere else. The result is
        never longer than RECENT_PROJECTS_MAX and never contains a path that does
        not exist on disk right now.
        """
        try:
            from i18n import load_config as _load_cfg
            raw = _load_cfg().get(RECENT_PROJECTS_KEY)
        except Exception:  # noqa: BLE001 — a broken config must not break the menu
            return []
        if not isinstance(raw, list):
            return []
        out, seen = [], set()
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                continue
            try:
                if not os.path.isfile(item):
                    continue  # pruned: the file was moved / deleted
            except OSError:
                continue
            norm = os.path.normcase(os.path.abspath(item))
            if norm in seen:
                continue  # deduplicated by the NORMALIZED ABSOLUTE path
            seen.add(norm)
            out.append(item)
            if len(out) >= RECENT_PROJECTS_MAX:
                break
        return out

    def _remember_recent_project(self, path: str) -> None:
        """Put `path` at the head of the MRU list (merge-write; never raises).

        Called by `_load_project_at()` (a successful open) and `_do_save()` (a
        successful save — Save As included: the new path becomes the head).
        """
        if not isinstance(path, str) or not path.strip():
            return
        try:
            entry = os.path.abspath(path)
            norm = os.path.normcase(entry)
            items = [p for p in self._recent_projects()
                     if os.path.normcase(os.path.abspath(p)) != norm]
            items.insert(0, entry)
            from i18n import save_config as _save_cfg
            _save_cfg({RECENT_PROJECTS_KEY: items[:RECENT_PROJECTS_MAX]})
        except Exception as e:  # noqa: BLE001 — the MRU is a convenience, never a condition
            if self.log:
                self.log.warning(f"Could not update the recent-projects list: {e}")

    def _clear_recent_projects(self) -> None:
        """Empty the MRU list (the "Clear the list" item of the Recent submenu)."""
        try:
            from i18n import save_config as _save_cfg
            _save_cfg({RECENT_PROJECTS_KEY: []})
        except Exception as e:  # noqa: BLE001 — a broken write must not break the menu
            if self.log:
                self.log.warning(f"Could not clear the recent-projects list: {e}")
        menu = getattr(self, "_recent_menu", None)
        if menu is not None:
            self._populate_recent_menu(menu)  # the submenu follows the click immediately

    def _populate_recent_menu(self, menu) -> None:
        """(Re)build the `File → Recent` submenu from the config.

        Called at construction and again on every `aboutToShow` (the v1.3.3.1
        language-submenu pattern), so a project opened by ANY path — the dialog, a
        drop, a recovery — is one click away the next time the menu is opened.
        Children are created MANUALLY (never the `QMenu.addAction(text, slot)`
        auto-connection: PySide6 6.11 emits `triggered` into a Python slot without
        the argument and cannot be disconnected, gotcha #10) and the rebuilt
        wrappers are re-registered in `MainWindow._qaction_guard` (gotcha #9 — an
        unguarded wrapper takes the C++ submenu down with it on GC). Never raises.
        """
        try:
            menu.clear()
            items = self._recent_projects()
            if not items:
                act_empty = menu.addAction(self.t("file.recent_empty"))
                act_empty.setEnabled(False)
            else:
                for p in items:
                    act = menu.addAction(os.path.basename(p))
                    act.setToolTip(p)  # the label is the file name — the path lives here
                    act.setData(p)
                    act.triggered.connect(
                        lambda checked=False, path=p: self._open_recent_project(path))
                menu.addSeparator()
                act_clear = menu.addAction(self.t("file.recent_clear"))
                act_clear.triggered.connect(
                    lambda checked=False: self._clear_recent_projects())
        except RuntimeError:
            return  # Qt teardown — the menu is already destroyed
        self._rebuild_qaction_guard()

    def _open_recent_project(self, path: str) -> bool:
        """Open a project from the Recent list — the very same path as File → Open."""
        if not isinstance(path, str) or not os.path.isfile(path):
            # pruned between the menu build and the click (the file just disappeared):
            # the rebuild drops the entry — that IS the feedback.
            menu = getattr(self, "_recent_menu", None)
            if menu is not None:
                self._populate_recent_menu(menu)
            return False
        return self._load_project_at(path)

    def _load_project_at(self, path: str, skip_autosave_prompt: bool = False,
                         raw: dict = None, example: bool = False) -> bool:
        """v0.9.7: the common load path (File→Open and restore from a backup/autosave).

        ROADMAP v0.9.7 #3: if the autosave is NEWER than the file on disk —
        offer to restore it BEFORE loading (answering "Yes" only replaces
        the in-memory content being loaded; the file on disk changes only
        on a later save). skip_autosave_prompt — the explicit restore path
        (the user already chose the source; a repeated prompt about a newer
        autosave would be disorienting).

        v1.3.3.6 (ROADMAP task 1/3): a successful load puts the path at the head of
        the `recent_projects` MRU; a load that RAISES no longer ends in a bare
        critical dialog — `_recover_unreadable_project` asks the backup ring and the
        autosave first (with consent). The recovery offer is keyed on the FILE being
        unreadable, not on any later failure: an error thrown while APPLYING an
        already-parsed project (the keyring, the sidebar, the view) must not offer to
        overwrite a perfectly good file — that keeps the historic dialog.

        v1.5rc3 (ROADMAP task 1): `raw` is an ALREADY-PARSED project and `example`
        marks the DEMO one (`_open_example_map`). A dict supplied by the caller skips
        the file reading, the autosave prompt and the recovery path — there is no file
        to read, no autosave to be newer and nothing to recover — and joins the SAME
        tail every other load uses. A demo has no path, so it enters neither the MRU
        nor `_project_file`; `_update_window_title()` is what tells the user that the
        map on screen is an example.

        v1.5 (ROADMAP): every load that is NOT the demo ends the emulation — the demo's
        `DEMO_STATUSES` may never survive into a user's project (it is installed by
        `_open_example_map()` before it calls this method).
        """
        if not example:
            self._set_emulated_statuses({})
        if raw is None:
            try:
                from storage.project import load_project as _load_project
                raw = _load_project(path)
            except Exception as e:  # noqa: BLE001 — the file cannot be read: recover, do not dead-end
                # v1.3.3.6 (task 3): the ring buffer and the autosave are consulted BEFORE
                # the critical dialog (which stays for the "nothing to restore" case).
                return self._recover_unreadable_project(path, e)

            try:
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
            except Exception as e:  # noqa: BLE001 — the prompt must not block a good file
                if self.log:
                    self.log.warning(f"Autosave prompt failed: {e}")

        try:
            server_count = len(raw.get('servers', []))

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
            # v1.5rc3 (ROADMAP task 1): a demo project carries no path — `_project_file`
            # stays empty (File → Save therefore asks for a name, and the demo is never
            # written anywhere behind the user's back), and the window says out loud that
            # it is an example (the title marker; cleared by the next new/open/save).
            self._project_file = path or None
            self._example_project = bool(example)
            self._dirty = False
            self._reset_undo_stack()  # v0.8.3: a load — a new undo reference point
            self._update_window_title()
            self.statusBar().showMessage(
                self.t("status.example_loaded") if example
                else self.t("status.project_loaded"))
            # v1.3.3.6 (task 1): a load IS the definition of "recent" — but only a FILE
            # is. An example is not "yesterday's work" and never joins the MRU.
            if path:
                self._remember_recent_project(path)

            if self.log:
                self.log.info("Project loaded", extra={"file": path, "servers": server_count,
                                                       "example": bool(example)})
            return True
        except Exception as e:
            # The file PARSED — something later failed (the keyring, the scene, the
            # tree). This is NOT a case for a recovery offer: replacing a readable
            # file with a backup would be data loss. The historic dialog stays.
            if self.log:
                self.log.exception(f"Failed to apply the loaded project {path}")
            QMessageBox.critical(
                self, self.t("msg.error_title"), self.t("msg.load_failed", error=str(e)))
            return False

    # ── v1.3.3.6 (ROADMAP task 3): recovery when the project cannot be read ──

    def _unreadable_sources(self, path: str) -> list:
        """The recovery material of an unreadable project, NEWEST first.

        The ring buffer of backups (`storage.autosave.list_backups` — slot 1 is the
        newest) and the last autosave (`read_autosave`/`autosave_mtime`); Qt-free, so
        the "is there anything to offer at all" decision is testable on its own. Only a
        source that really PARSES counts (`read_json` returns None for a corrupt one —
        for the autosave AND for each ring slot): offering a broken file as a rescue
        would just move the failure, and restoring one could loop the user straight
        back into this dialog. Item shape: ``{"label", "path", "mtime", "kind"}``.
        """
        out = []
        try:
            from storage import autosave as _as_mod
        except Exception:  # noqa: BLE001 — no storage module — no sources
            return out
        try:
            if _as_mod.read_autosave(path) is not None:
                out.append({
                    "label": self.t("backups.autosave"),
                    "path": _as_mod.autosave_path_for(path),
                    "mtime": float(_as_mod.autosave_mtime(path) or 0.0),
                    "kind": "autosave",
                })
        except Exception as e:  # noqa: BLE001 — one bad source must not hide the others
            if self.log:
                self.log.warning(f"Autosave lookup failed: {e}")
        try:
            for b in _as_mod.list_backups(path):
                if _as_mod.read_json(b["path"]) is None:
                    continue  # a corrupt slot is not a rescue
                out.append({
                    "label": self.t("backups.backup", n=b["slot"]),
                    "path": b["path"], "mtime": float(b["mtime"]), "kind": "backup",
                })
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Backup ring lookup failed: {e}")
        out.sort(key=lambda it: it["mtime"], reverse=True)
        return out

    def _recovery_prompt_text(self, error, source: dict) -> str:
        """The question of the recovery dialog — the source and its DATE spelled out.

        Split out of `_ask_recovery_source` on purpose: the text is the part a headless
        test can assert on (the slot name and its timestamp), while the dialog below is
        patched away.
        """
        try:
            from datetime import datetime as _dt
            when = _dt.fromtimestamp(source["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError, KeyError, TypeError):
            when = "-"
        return self.t("msg.project_unreadable", error=str(error),
                      source=source.get("label", ""), date=when)

    def _ask_recovery_source(self, error, source: dict) -> str:
        """The three-way recovery question → "restore" | "list" | "skip".

        The instance-level seam for the offscreen tests (the `_collect_node_info`
        pattern of tests/test_main_window_split.py): a modal QMessageBox with three
        custom buttons cannot be answered without an event loop, so the test replaces
        THIS method instead of driving the dialog.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(self.t("dialog.project_unreadable"))
        box.setText(self._recovery_prompt_text(error, source))
        btn_restore = box.addButton(self.t("msg.project_unreadable_restore"),
                                    QMessageBox.AcceptRole)
        btn_list = box.addButton(self.t("msg.project_unreadable_backups"),
                                 QMessageBox.ActionRole)
        box.addButton(self.t("msg.project_unreadable_skip"), QMessageBox.RejectRole)
        box.setDefaultButton(btn_restore)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_restore:
            return "restore"
        if clicked is btn_list:
            return "list"
        return "skip"

    def _recover_unreadable_project(self, path: str, error) -> bool:
        """Offer a restore when the project file cannot be read (v1.3.3.6, task 3).

        Returns True only when a restore happened AND the project loaded. NOTHING is
        overwritten without an explicit choice: "Restore" copies the chosen slot over
        the unreadable file and re-enters the normal load path; "Open the backup
        list…" hands the decision to the existing `BackupsDialog`; "Cancel" leaves the
        file exactly as it was found. With no source at all — the historic critical
        dialog, unchanged.
        """
        sources = self._unreadable_sources(path)
        if not sources:
            QMessageBox.critical(
                self, self.t("msg.error_title"), self.t("msg.load_failed", error=str(error)))
            return False
        newest = sources[0]
        if self.log:
            self.log.warning("Project file unreadable, offering recovery",
                             extra={"file": path, "source": newest.get("path", "")})
        choice = self._ask_recovery_source(error, newest)
        if choice == "restore":
            return self._restore_unreadable_from(newest, path)
        if choice == "list":
            # The ring of THIS file, not of the open project: the dialog is handed the
            # path that failed (a drop / a Recent item may differ from _project_file).
            self._show_backups_dialog(path)
        return False

    def _restore_unreadable_from(self, source: dict, target_path: str) -> bool:
        """Copy a recovery slot over the unreadable file and re-enter the load path.

        `restore_to_project()` + a re-entrant
        `_load_project_at(..., skip_autosave_prompt=True)` — the `_restore_from_source`
        mechanics with an explicit target (the file that failed to load is not
        necessarily the open project). Only ever called after an explicit "Restore".
        """
        try:
            from storage import autosave as _as_mod
            _as_mod.restore_to_project(source["path"], target_path)
        except Exception as e:  # noqa: BLE001 — the user must see the reason
            if self.log:
                self.log.exception(f"Failed to recover {target_path} from {source.get('path')}")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.restore_failed", error=str(e)))
            return False
        ok = self._load_project_at(target_path, skip_autosave_prompt=True)
        if ok:
            self.statusBar().showMessage(
                self.t("status.restored", source=source.get("label", "")))
            if self.log:
                self.log.info("Project recovered from an unreadable file",
                              extra={"file": target_path, "source": source.get("path", "")})
        return ok

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
        # v1.3.3.1 (ROADMAP task 6): FLUSH the pending note-text debounce FIRST.
        # The bug found by the v1.3.3 audit: typing in a note and pressing Ctrl+S
        # inside the 600 ms debounce wrote the new text to the JSON (to_dict() reads
        # the LIVE text) and THEN the pending CmdEditTextNote landed on the FRESH
        # undo stack — the title showed unsaved changes right after a save, and
        # Ctrl+Z reverted text that was already on disk. Committing here pushes the
        # command BEFORE the stack is reset (a new baseline), so the state is clean.
        commit = getattr(self, "_commit_note_text", None)
        if callable(commit):
            try:
                commit()
            except Exception as e:  # noqa: BLE001 — a failed flush must not block the save
                if self.log:
                    self.log.warning(f"Commit pending note text failed: {e}")
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
            # v1.5rc3 (ROADMAP task 1): the demo map became the user's OWN project the
            # moment it was written to a file — the title marker goes away with it.
            self._example_project = False
            # v1.5 (ROADMAP): and so does the EMULATION. Nothing was ever serialized (a
            # status is a measurement, not data), the file carries no status field and the
            # copy probes for real from here on; the cards keep what they show until the
            # first real result replaces it — always still marked as the demo's.
            self._set_emulated_statuses({})
            self._reset_undo_stack()  # v0.8.3: a save — a new undo reference point
            self._update_window_title()

            if unsaved_aliases:
                QMessageBox.warning(
                    self, self.t("msg.error_title"),
                    "\n".join(self.t("msg.credentials_save_failed", alias=a) for a in unsaved_aliases))

            self.statusBar().showMessage(self.t("status.project_saved"))
            # v1.3.3.6 (task 1): a successful save joins the MRU too — Save As makes the
            # NEW path the head (the previous path stays below it until it is pruned).
            self._remember_recent_project(path)

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

    def _backup_items(self, project_path: str = None) -> list:
        """v0.9.7 #2: rows for the backup dialog — autosave + ring slots (newest first).

        v1.3.3.6 (task 3): `project_path` defaults to the OPEN project, but the
        recovery path passes the file that failed to load (a drop / a Recent item is
        not necessarily `self._project_file`).
        """
        target = project_path if isinstance(project_path, str) and project_path \
            else self._project_file
        if not target:
            return []
        from storage import autosave as _as_mod
        items = []
        auto_path = _as_mod.autosave_path_for(target)
        if os.path.isfile(auto_path):
            try:
                st = os.stat(auto_path)
                items.append({
                    "label": self.t("backups.autosave"),
                    "path": auto_path, "mtime": st.st_mtime, "size": st.st_size,
                })
            except OSError:
                pass
        for b in _as_mod.list_backups(target):
            items.append({
                "label": self.t("backups.backup", n=b["slot"]),
                "path": b["path"], "mtime": b["mtime"], "size": b["size"],
            })
        return items

    def _show_backups_dialog(self, project_path: str = None):
        """v0.9.7 #2: the dialog with the ring buffer of backups (+ the latest autosave).

        v1.3.3.6 (task 3): an optional explicit target — the recovery path opens the
        list of the file it could not read. Called as a QAction slot it receives no
        argument (or a bool from an auto-connection), which the `isinstance` guard
        below turns back into the open project.
        """
        target = project_path if isinstance(project_path, str) and project_path \
            else self._project_file
        if not target:
            QMessageBox.information(
                self, self.t("msg.info_title"), self.t("msg.open_project_first"))
            return
        items = self._backup_items(target)
        if not items:
            QMessageBox.information(
                self, self.t("dialog.backups"), self.t("backups.empty"))
            return
        try:
            from dialogs.backups_dialog import BackupsDialog
        except ImportError:  # flat layout without the package (the main_window pattern)
            from backups_dialog import BackupsDialog
        dlg = BackupsDialog(items, parent=self)
        dlg.restore_requested.connect(
            lambda src, label, _t=target: self._restore_from_source(src, label, _t))
        dlg.exec()

    def _restore_from_source(self, src_path: str, label: str, target_path: str = None):
        """v0.9.7 #2/#3: the single restore path — backup/autosave → project file.

        Confirmation (with a warning about unsaved edits when dirty) → an
        atomic copy into the project file → a reload via _load_project_at
        (the same logic as File→Open: undo stack, dirty, keyring keys,
        statuses).

        v1.3.3.6 (task 3): `target_path` — the explicit target of a recovery restore
        (defaults to the open project file).
        """
        target = target_path if isinstance(target_path, str) and target_path \
            else self._project_file
        if not target:
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
            _as_mod.restore_to_project(src_path, target)
            ok = self._load_project_at(target, skip_autosave_prompt=True)
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
