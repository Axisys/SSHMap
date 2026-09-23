"""NodeOpsMixin — the "operations on the map's nodes and connections" cluster.

v1.1.4 (ROADMAP v1.1.4, task 2): moved out of ui/main_window.py as part of
the "main_window.py hygiene" series. "Module + callbacks" pattern
(precedents: v0.9.9.4 sidebar, v0.9.9.3 diagnostics): the mixin holds only
methods, MainWindow remains the facade, the public API is unchanged; method
names and call sites were not touched.

The cluster includes the entire TXT import (``_import_servers_from_txt`` +
the thread slots ``_on_import_resolve_progress``/``_on_import_resolved`` and
the assembly ``_finish_import_from_txt``) — it is one feature and cannot be
split across files.

Ownership of shared state (AUDIT §3): the nodes/connections live on
``self.scene``, the undo stack and ``_dirty`` — in the core (MainWindow);
the ping/DNS/import threads are held on the instance
(``self._ping_thread``/``self._dns_thread``/``self._import_resolve_thread``
+ the batch context ``self._import_pending/_import_path/_import_skipped``).
The mixin does NOT import ui.main_window (cycle) — duck-typing on the
instance only; the dialogs (AddServerDialog/ConnectionDialog) are taken
from the facade module at call time (host_attr) — the test seam for
``MW.AddServerDialog``/``MW.ConnectionDialog`` monkeypatching.

``_is_scene_point`` moved here with the cluster (AUDIT §3: "module-level
globals go to their own mixin or stay in the core"); main_window.py imports
it back — ``_add_group_at`` (groups, the core) uses the same guard.
"""
from PySide6.QtWidgets import QDialog, QMessageBox, QApplication

try:
    from ..graphics.server_node import ServerNode
except ImportError:
    from graphics.server_node import ServerNode

try:  # v1.1.4: the common seam for monkeypatching the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr


def _is_scene_point(value) -> bool:
    """v0.8.1: is a scene point (QPoint/QPointF) passed, and not something else.

    QAction.triggered passes the bool `checked` to a Python slot — when the
    action is connected directly (toolbar/menu) it arrives as the first
    positional argument. Without this check `_add_server(True)` crashed on
    `center.x()` ("'bool' object has no attribute 'x'").
    """
    if value is None or isinstance(value, bool):
        return False
    x = getattr(value, "x", None)
    y = getattr(value, "y", None)
    return callable(x) and callable(y)


class NodeOpsMixin:
    """Node/connection methods: add/import/duplicate/delete/connect/copy/ping."""

    def _add_server(self, at_scene_pos=None):
        """Create a server (the `at_scene_pos` attribute — the click point from the context menu)."""
        data = None  # so the except branch does not fall over a nonexistent variable (former AUDIT.md)
        try:
            dlg_cls = host_attr(self, "AddServerDialog")
            if dlg_cls is None:
                raise RuntimeError("AddServerDialog is not available in the MainWindow module")
            dlg = dlg_cls(self)
            if dlg.exec() == QDialog.Accepted:
                data = dlg.get_data()
                # Position: the click point (right-click menu, v0.7.2) or the center of the visible area.
                # v0.8.1: accept the position only if it really is a point —
                # QAction.triggered (toolbar/menu) sends the bool `checked` to the slot,
                # which earlier landed here as at_scene_pos and crashed `center.x()`.
                if _is_scene_point(at_scene_pos):
                    center = at_scene_pos
                else:
                    center = self.view.mapToScene(self.view.viewport().rect().center())
                # Review fix v0.8.0 (#1): the offsets are half the base node size
                # (MIN_NODE_WIDTH=180 / MIN_NODE_HEIGHT=130 → 90/65), so the new node
                # is centered under the click point, not shifted down-right from the cursor.
                data.x = center.x() - ServerNode.MIN_NODE_WIDTH / 2
                data.y = center.y() - ServerNode.MIN_NODE_HEIGHT / 2
                # v0.8.3: the node is created by an undo command (the push itself performs the redo)
                from modules.undo_commands import CmdAddRemoveNode
                self._push_command(CmdAddRemoveNode(self, self.scene, data, "add"))
                node = self.scene.get_node(data.id)
                self.refresh_sidebar()
                self._sync_status_targets()  # v0.7.1: the new node — into the check plan
                if self.log:
                    self.log.info("Server added", extra={"alias": data.alias, "host": data.host})
                self.statusBar().showMessage(self.t("status.server_added", alias=data.alias))
                self._mark_dirty()  # ← unsaved changes
                # v0.9.5.6: "Connect via SSH" from the add dialog — the node
                # is already created; open the SSH dialog right away (the password is prefilled).
                if getattr(dlg, "_connect_after_accept", False):
                    self._run_ssh_connect(node, prefill_password=dlg.password.text())
        except Exception as e:
            if self.log:
                self.log.exception(f"Error adding server {getattr(data, 'alias', '?')}")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.add_failed", error=str(e)))

    def _import_servers_from_txt(self):
        """v0.9.5.5: bulk import of servers from a text file.

        Format: one host per line (IP or DNS name), '#'/'//' — comments.
        IP → host=IP; a name → resolved to an IP (the `ip` field), host stays
        the name. Duplicates (already on the map or repeated in the file) are
        skipped. A single undo unit — the whole batch is added/rolled back by
        one CmdAddRemoveNodeBatch command.

        v1.1.2RC2 (N6): the DNS name resolution — off the GUI thread
        (HostResolverThread, the progress in the status bar): a file with
        dozens of names with an unavailable resolver no longer freezes the
        interface. IP addresses need no resolution — they are added immediately.
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
            # v1.5.2 (ROADMAP task 2): a refused file was a dialog only — the history
            # keeps the reason too (the dialog is gone the moment it is dismissed).
            if self.log:
                self.log.warning(f"TXT import: {path} is unreadable — {e}")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.import_servers_failed", error=str(e)))
            return

        from services.host_importer import parse_hosts_file, is_ip_address
        # v1.2.10rc2 (AUDIT manual #5b): the file_dups ghost is removed — earlier a
        # variable living nearby was always equal to an empty list; the real
        # deduplication is done manually below (case-insensitive + hosts already
        # on the map).
        entries = parse_hosts_file(text)
        # Deduplication of the file lines (case-insensitive)
        seen, unique_entries = set(), []
        for e in entries:
            if e.lower() in seen:
                continue
            seen.add(e.lower())
            unique_entries.append(e)

        # Hosts/IPs already present on the map — also duplicates
        existing = set()
        for node in self.scene.nodes():
            d = node.data
            existing.add((d.host or "").lower())
            if d.ip:
                existing.add(d.ip.lower())

        pending, skipped = [], 0   # v1.2.10rc2 (#5b): the file_dups ghost is removed — the counter starts at zero
        for entry in unique_entries:
            if entry.lower() in existing:
                skipped += 1
                continue
            pending.append(entry)
            existing.add(entry.lower())

        if not pending:
            # v1.5.2 (ROADMAP task 2): "the import found nothing new" is a RESULT — it
            # reached a dialog and nothing else. The history keeps it.
            if self.log:
                self.log.info(f"TXT import: no new servers in {path} "
                              f"({skipped} duplicate(s) skipped)")
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.import_servers_result", added=0, skipped=skipped))
            return

        dns_entries = [e for e in pending if not is_ip_address(e)]
        if not dns_entries:
            # IP addresses only — no resolution needed, assemble synchronously (no thread)
            self._finish_import_from_txt(pending, {}, path, skipped)
            return

        # v1.1.2RC2 (N6): the names — to a separate thread; the GUI stays
        # responsive, the resolution progress is visible in the status bar.
        # The batch context is held on the window — resolved_map arrives as a
        # queued signal only after this method has returned.
        from services.host_importer import HostResolverThread
        thread = HostResolverThread(dns_entries, parent=self)
        self._import_resolve_thread = thread  # hold the reference — the thread must not become an orphan
        self._import_pending = pending
        self._import_path = path
        self._import_skipped = skipped
        thread.progress.connect(self._on_import_resolve_progress)
        thread.resolved_map.connect(self._on_import_resolved)
        self.statusBar().showMessage(
            self.t("status.import_resolving", done=0, total=len(dns_entries)))
        thread.start()

    def _on_import_resolve_progress(self, done: int, total: int):
        """v1.1.2RC2 (N6): the DNS resolution progress of the import — in the status bar."""
        try:
            self.statusBar().showMessage(
                self.t("status.import_resolving", done=done, total=total))
        except RuntimeError:
            pass  # Qt teardown — the window is already destroyed

    def _on_import_resolved(self, resolved_map):
        """v1.1.2RC2 (N6): the resolution is finished (GUI thread) — assemble the nodes and add them."""
        thread = getattr(self, "_import_resolve_thread", None)
        if thread is not None:
            self._import_resolve_thread = None
            try:
                thread.deleteLater()  # run() is done — the thread can be handed to Qt
            except RuntimeError:
                pass  # Qt teardown
        pending = list(getattr(self, "_import_pending", None) or [])
        path = getattr(self, "_import_path", None) or ""
        skipped = int(getattr(self, "_import_skipped", 0) or 0)
        self._import_pending = None
        self._import_path = None
        self._import_skipped = 0
        if not pending:
            return  # the window was closed during the resolution (stop()) — the import was not completed
        try:
            self._finish_import_from_txt(pending, dict(resolved_map or {}), path, skipped)
        except RuntimeError:
            pass  # Qt teardown — the widgets are already destroyed

    def _finish_import_from_txt(self, pending, resolved_map, path, skipped):
        """v1.1.2RC2 (N6): the ServerData assembly + the grid layout + one undo command.

        `resolved_map` — {name: IP or None} from HostResolverThread; IP
        addresses are absent from it (they needed no resolution) and are
        taken as-is.
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

        self._commit_import_batch(added_data, path)
        QMessageBox.information(self, self.t("msg.success_title"),
                                self.t("msg.import_servers_result",
                                       added=len(added_data), skipped=skipped))

    # ── v1.4.1: the shared half of every bulk import ─────────────────────────

    def _layout_imported_nodes(self, added_data):
        """Place an imported batch in a grid from the centre of the visible area.

        Shared by the TXT import (v0.9.5.5) and the SSH-config import (v1.4.1) —
        one placement rule for every import, so a new import cannot drift.
        """
        center = self.view.mapToScene(self.view.viewport().rect().center())
        col_w, row_h, cols = ServerNode.MIN_NODE_WIDTH + 30, ServerNode.MIN_NODE_HEIGHT + 30, 6
        for i, data in enumerate(added_data):
            r, c = divmod(i, cols)
            data.x = center.x() - 90 + c * col_w
            data.y = center.y() - 65 + r * row_h

    def _commit_import_batch(self, added_data, source_label):
        """Add a batch of ServerData as ONE undo command + the usual post-add refresh.

        Never raises on an empty list — the caller decides what to report.
        """
        if not added_data:
            return
        self._layout_imported_nodes(added_data)
        from modules.undo_commands import CmdAddRemoveNodeBatch
        self._push_command(CmdAddRemoveNodeBatch(self, self.scene, added_data, "add"))
        self.refresh_sidebar()
        self._sync_status_targets()
        self._mark_dirty()
        if self.log:
            self.log.info(f"Imported {len(added_data)} servers from {source_label}")
        self.statusBar().showMessage(
            self.t("status.servers_imported", count=len(added_data)), 5000)

    def _map_import_keys(self) -> set:
        """The `(host, port, user)` keys of the nodes already on the map.

        v1.4.1: the deduplication rule of the SSH-config import — the same
        machine reached with another login or on another port is another node,
        so the port and the user are part of the key (the TXT import compares
        host/ip alone: it has no port or user to compare).
        """
        keys = set()
        for node in self.scene.nodes():
            d = node.data
            keys.add(((d.host or "").strip().lower(),
                      int(d.ssh_port or 22),
                      (d.user or "").strip().lower()))
        return keys

    def _import_servers_from_ssh_config(self):
        """v1.4.1 (ROADMAP task 3): bulk import from the OpenSSH client config.

        `~/.ssh/config` → the parser (`services/ssh_config_importer.py`) →
        deduplication against the map (a host the map already knows is reported,
        never added twice) → the checkbox dialog → ONE `CmdAddRemoveNodeBatch`
        (the TXT-import precedent: Ctrl+Z rolls the whole import back at once).
        `Host/HostName/User/Port/IdentityFile` land in `alias/host/user/ssh_port/
        key_path`; a wildcard pattern, a `Match` block and an unreadable
        `Include` are reported by the dialog and imported by nobody.
        """
        from services.ssh_config_importer import (
            ERROR_MISSING, REASON_DUPLICATE, SshConfigError, SshConfigIssue,
            dedupe_hosts, default_config_path, load_ssh_config,
        )

        config_path = default_config_path()
        try:
            result = load_ssh_config(config_path)
        except SshConfigError as e:
            if e.code == ERROR_MISSING:
                QMessageBox.information(self, self.t("msg.info_title"),
                                        self.t("sshconfig.not_found", path=config_path))
            else:
                QMessageBox.critical(self, self.t("msg.error_title"),
                                     self.t("msg.import_servers_failed",
                                            error=e.detail or e.code))
            return

        fresh, duplicates = dedupe_hosts(result.hosts, self._map_import_keys())
        skipped = list(result.skipped) + [
            SshConfigIssue(subject=host.alias, reason=REASON_DUPLICATE,
                           detail=host.host, source=host.source, line=host.line)
            for host in duplicates
        ]
        if not fresh:
            # v1.5.2 (ROADMAP task 2): the "nothing new" result of the second import path.
            if self.log:
                self.log.info(f"SSH config import: no new servers in "
                              f"{result.path or config_path} ({len(skipped)} skipped)")
            QMessageBox.information(
                self, self.t("msg.info_title"),
                self.t("msg.import_ssh_config_result", added=0, skipped=len(skipped)))
            return

        try:
            dlg_cls = host_attr(self, "SshConfigImportDialog")
            if dlg_cls is None:
                raise RuntimeError("SshConfigImportDialog is not available in the MainWindow module")
            dlg = dlg_cls(fresh, skipped, result.notes, result.path, self)
            if dlg.exec() != QDialog.Accepted:
                return
            selected = list(dlg.selected_hosts())
        except Exception as e:  # noqa: BLE001 — the dialog must never kill the window
            if self.log:
                self.log.exception("SSH config import dialog failed")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.import_servers_failed", error=str(e)))
            return

        import uuid as _uuid
        from models.server import ServerData
        from services.host_importer import is_ip_address

        added_data = []
        for host in selected:
            host_name = str(host.host or host.alias)
            added_data.append(ServerData(
                id=str(_uuid.uuid4())[:8],
                alias=str(host.alias),
                host=host_name,
                user=str(host.user or ""),
                password="",
                key_path=str(host.key_path or ""),
                ssh_port=int(host.port or 22),
                # a HostName that IS an address gives the node its ip field for free
                ip=host_name if is_ip_address(host_name) else "",
            ))

        self._commit_import_batch(added_data, result.path or config_path)
        QMessageBox.information(
            self, self.t("msg.success_title"),
            self.t("msg.import_ssh_config_result",
                   added=len(added_data), skipped=len(skipped)))

    def _add_connection(self, default_source_id=None, default_target_id=None):
        """Create a connection: the dialog with the node, label and type choice (v0.7).

        The prefill parameters are used by the MapView drag mode (Shift+drag).
        """
        nodes = list(self.scene.nodes())
        if len(nodes) < 2:
            QMessageBox.information(self, self.t("msg.info_title"), 
                                  self.t("validation.min_servers"))
            return

        try:
            dlg_cls = host_attr(self, "ConnectionDialog")
            if dlg_cls is None:
                raise RuntimeError("ConnectionDialog is not available in the MainWindow module")
            dlg = dlg_cls(
                nodes, self,
                default_source_id=default_source_id,
                default_target_id=default_target_id,
            )
            if dlg.exec() == QDialog.Accepted:
                # get_connection() returns the node ids (strings), not ServerNode objects;
                # the 4th element — the connection type (v0.7), the 5th — the bidirectional mode (v1.2.6)
                src, tgt, lbl, ctype, bidir = dlg.get_connection()
                if src == tgt:
                    QMessageBox.warning(self, self.t("msg.error_title"), 
                                      self.t("validation.self_connection"))
                    return
                # v0.8.3: the connection is created by an undo command (the push itself performs the redo)
                from modules.undo_commands import CmdAddRemoveConnection
                self._push_command(CmdAddRemoveConnection(
                    self, self.scene, src, tgt, lbl, ctype, "add", bidirectional=bidir))
                if not self.scene.has_connection(src, tgt):
                    # the command could not create it (the nodes vanished?) — the warning, as before
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
                self._update_counts_label()  # UI polish: the connection counter in the status bar
                self._mark_dirty()  # ← unsaved changes
        except Exception as e:
            if self.log:
                self.log.exception("Error adding connection")
            QMessageBox.critical(self, self.t("msg.error_title"), self.t("msg.create_connection_failed", error=str(e)))

    def _duplicate_node(self, node: "ServerNode", offset: float = 40.0):
        """Ctrl+D / right click: a copy of the node (all fields except id) with an offset.

        The password is not stored in the JSON — it lives in the keyring by
        server_id, so for the copy we load the original's password and save
        it under the NEW id. Returns the new ServerNode or None (the node was
        not found).
        """
        if node is None or node.scene() is None:
            return None
        import copy as _copy
        data = _copy.deepcopy(node.data)
        data.x = float(node.data.x) + offset
        data.y = float(node.data.y) + offset
        # a new unique id
        import uuid as _uuid
        while True:
            new_id = str(_uuid.uuid4())[:8]
            if not self.scene.has_node(new_id):
                break
        data.id = new_id
        # v0.9.3: the password from the keyring by the new node's server_id (task #1)
        try:
            from services.credential_manager import get_credential_manager
            cm = get_credential_manager()
            pw = cm.load_password(node.data.id)
            if pw:
                cm.save_password(new_id, pw)
        except Exception:  # noqa: BLE001 — the keyring is unavailable: the copy has no password
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
        """Ctrl+D: duplicate the selected node; the new node becomes selected."""
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
        """v0.9.3: all selected map nodes (in scene order)."""
        try:
            return [i for i in self.scene.selectedItems() if isinstance(i, ServerNode)]
        except RuntimeError:
            return []

    # ── v1.3.3.3 (ROADMAP task 5): "Check statuses now" ─────────────────────────

    def _check_statuses_now(self, node: "ServerNode" = None) -> bool:
        """Run ONE status round for the selected nodes, on demand.

        The periodic rounds (``StatusChecker.start``, ~every 30 s) probe the WHOLE map;
        this is the explicit "check these right now" of the node context menu (the map
        and the sidebar both call it) and of the Edit-menu item. The nodes probed are
        the current SELECTION when there is one, otherwise the node the menu was opened
        on — so "check this one" and "check the selected five" are the same entry point.

        ``node`` is duck-typed on purpose: the menu/toolbar path connects the slot to
        ``QAction.triggered``, which delivers a bool ``checked`` as the first argument
        (gotchas #10/#12 of AGENTS.md, the ``_is_scene_point`` guard pattern) — anything
        that is not a node object is ignored and the selection decides.

        Not one byte of network traffic happens here: ``start_round`` spawns the
        existing ``_ProbeThread`` (``ThreadPoolExecutor``, cap ``status_max_parallel``)
        — the GUI thread only builds the target list. The interval/cancellation
        semantics are untouched (``_busy`` still refuses a second concurrent round, and
        a manual round does not restart the QTimer countdown).

        Returns True when a round was actually started. Never raises.
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return False
        targets = [(n.data.id, n.data.host, n.data.ssh_port or 22)
                   for n in self.selected_nodes()]
        if not targets:
            data = node.data if node is not None and not isinstance(node, bool) \
                and hasattr(node, "data") else None
            if data is not None:
                targets = [(data.id, data.host, data.ssh_port or 22)]
        if not targets:
            return False
        try:
            started = bool(checker.start_round([t[0] for t in targets]))
        except Exception as e:  # noqa: BLE001 — a probe must not break the menu action
            if self.log:
                self.log.warning(f"Check statuses now failed: {e}")
            return False
        if started:
            try:
                self.statusBar().showMessage(
                    self.t("status.check_now", count=len(targets)), 5000)
            except (RuntimeError, AttributeError):
                pass  # Qt teardown / no i18n — the round is already running
            if self.log:
                self.log.info(f"Manual status round started for {len(targets)} node(s)")
        return started

    def _delete_selected_nodes(self):
        """v0.9.3: delete ALL selected nodes (each via the guarded path)."""
        nodes = self.selected_nodes()
        if not nodes:
            QMessageBox.information(self, self.t("msg.info_title"),
                                    self.t("msg.select_server_edit"))
            return False
        # a single confirmation for the whole group; v1.2.4 (D7): + attached notes (the sum)
        attached_total = sum(
            len(self.scene.notes_attached_to(n.data.id)) for n in nodes)
        if self._i18n_available:
            confirm_text = self.t("msg.confirm_delete_many").format(count=len(nodes))
            if attached_total:
                confirm_text += "\n" + self.t("msg.delete_server_with_notes").format(
                    count=attached_total)
        else:
            confirm_text = f"Delete {len(nodes)} selected servers?\nEach will be checked for running SSH sessions."
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Confirm Deletion",
            confirm_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        deleted = 0
        for node in list(nodes):
            if node.scene() is None:
                continue  # already deleted with its arrow earlier in the loop
            if not self._ensure_worker_done(node.data.id):
                continue
            alias = node.data.alias
            # v1.2.4 (D7): this node's detach commands — BEFORE its removal (LIFO:
            # undo will first restore the node, then re-attach the notes)
            from modules.undo_commands import CmdAttachNote
            for n in list(self.scene.notes_attached_to(node.data.id)):
                self._push_command(CmdAttachNote(self, n, node.data.id, "detach"))
            arrows = [
                # v1.2.6: the 5th element — the bidirectional mode (undo restores the connection as it was)
                (a.source.data.id, a.target.data.id, a.label_text, a.connection_type,
                 bool(getattr(a, "bidirectional", False)))
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
        """v0.9.3: create connections between all pairs of selected nodes (a full graph).

        Each node is connected to each (no self-loops and no duplicates); the
        connection type — the default, the label is empty. Undo rolls back
        everything with a single command.
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
        """Copy the node's IP or hostname to the clipboard (v0.7.3).

        AUDIT v0.7.2 (medium #6): the reverse DNS (gethostbyaddr) runs in a
        separate thread — with an unavailable resolver the GUI thread earlier
        froze on the DNS timeout.
        v0.9.9.3: the thread was moved to services/diagnostics.py (ReverseDnsThread).
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
            from services.diagnostics import ReverseDnsThread  # v0.9.9.3: was a nested class

            # AUDIT v1.2.10 (auto #2): do not clobber a still-running DNS thread —
            # the same guard as for ping (_ping_node below): a second "Copy
            # Hostname" while the first request is alive (getaddrinfo may hang
            # until the resolver timeout) earlier overwrote self._dns_thread,
            # and the old thread became an orphan (closeEvent stops only the
            # CURRENT _dns_thread). We ignore it and show a status message.
            # i18n: no new keys — the existing status.import_resolving
            # ("Resolving host names… 0/1").
            if self._dns_thread is not None and self._dns_thread.isRunning():
                self.statusBar().showMessage(
                    self.t("status.import_resolving", done=0, total=1))
                return

            # v1.2.10rc1: parent=self — the thread's C++ object has an owner
            # while the window is alive (GC races on a live QThread are
            # excluded); a thread that outlives the shutdown wait budget is
            # registered in the orphan registry (services/diagnostics.
            # register_orphan_thread — the N4 pattern, like ssh_terminal's
            # _orphan_threads).
            thread = ReverseDnsThread(host, parent=self)

            def _on_dns_done(name):
                try:
                    if getattr(self, "_dns_thread", None) is thread:
                        self._dns_thread = None
                    _copy(name, "hostname")
                except RuntimeError:
                    # v1.2.10rc1 (AUDIT auto #2): the signal delivered after teardown —
                    # the statusBar()/clipboard() C++ objects are already deleted;
                    # a late emit without a live window is safe (the window is
                    # closed, there is nowhere to copy).
                    pass

            thread.resolved.connect(_on_dns_done)
            self._dns_thread = thread  # hold the reference — the thread must not become an orphan
            thread.start()
            return

        # "ip" and the other variants: no network calls — synchronous (the smoke test expects it anyway)
        _copy(node.data.ip.strip() or node.data.host, what)

    def _ping_node(self, node: "ServerNode"):
        """Ping the node in a separate thread without blocking the GUI (v0.7.3).

        Windows: `ping -n 3`, POSIX: `ping -c 3`. The result — in the status bar.
        v0.9.9.3: the thread was moved to services/diagnostics.py (PingThread).
        """
        if node is None:
            return

        # AUDIT v0.7.2 (medium #8): do not clobber a still-running ping — a
        # repeated request is ignored (earlier the reference was overwritten
        # and the old thread was left as an orphan).
        if self._ping_thread is not None and self._ping_thread.isRunning():
            self.statusBar().showMessage(self.t("status.ping_running", host=node.data.host))
            return

        from services.diagnostics import PingThread  # v0.9.9.3: was a nested class
        ping_thread = PingThread(node.data.host)

        def _on_ping_done(ok, text):
            if ok:
                self.statusBar().showMessage(text)
            else:
                QMessageBox.information(self, self.t("msg.info_title"), text)
            # Clear the reference only for OUR thread: a late old ping must not
            # null the reference of the already-started new one (AUDIT v0.7.2, medium #8).
            if getattr(self, "_ping_thread", None) is ping_thread:
                self._ping_thread = None

        ping_thread.finished_ping.connect(_on_ping_done)
        self._ping_thread = ping_thread
        ping_thread.start()
        self.statusBar().showMessage(self.t("status.ping_running", host=node.data.host))

    def _edit_connection(self, arrow):
        """The dialog for changing the connection label and type (v0.7.3)."""
        if arrow is None:
            return
        try:
            from dialogs.connection_dialog import EditConnectionDialog
            dlg = EditConnectionDialog(arrow, self)
            if dlg.exec() == QDialog.Accepted:
                # v1.2.6: the 3rd element — the bidirectional mode (it used to be a 2-tuple)
                label, ctype, bidir = dlg.get_connection()
                # v0.8.3: editing the connection (label/type/direction) — an undo command
                from modules.undo_commands import CmdEditConnection
                self._push_command(CmdEditConnection(
                    self, arrow,
                    arrow.label_text, arrow.connection_type,
                    bool(getattr(arrow, "bidirectional", False)),
                    label, ctype, bidir))
                self.statusBar().showMessage(self.t("status.connection_updated"))
                self._mark_dirty()  # ← unsaved changes
        except Exception as e:
            if self.log:
                self.log.exception("Error editing connection")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.update_failed", error=str(e)))

    def _remove_connection(self, arrow) -> bool:
        """Delete the connection with a confirmation (v0.7.3). Returns True if deleted."""
        if arrow is None:
            return False
        src_alias = arrow.source.data.alias
        tgt_alias = arrow.target.data.alias
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Confirm Deletion",
            self.t("msg.confirm_delete_connection").format(src=src_alias, tgt=tgt_alias)
            if self._i18n_available else f"Delete connection '{src_alias}' → '{tgt_alias}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return False
        # v0.8.3: deleting the connection — an undo command
        from modules.undo_commands import CmdAddRemoveConnection
        src_id = arrow.source.data.id
        tgt_id = arrow.target.data.id
        lbl = arrow.label_text
        ctype = arrow.connection_type
        self._push_command(CmdAddRemoveConnection(self, self.scene, src_id, tgt_id,
                                                  lbl, ctype, "remove"))
        self.statusBar().showMessage(self.t("status.connection_deleted"))
        self._update_counts_label()  # UI polish: the connection counter in the status bar
        self._mark_dirty()  # ← unsaved changes
        if self.log:
            self.log.info("Connection deleted",
                          extra={"source": src_alias, "target": tgt_alias})
        return True

    def _ensure_worker_done(self, server_id: str) -> bool:
        """The v0.6.x patch: wait for the SSHWorker to finish before deleting the node.

        If the thread is still running and does not finish in time — show a
        warning and cancel the deletion (otherwise success/error could land
        in a destroyed dialog / the data of a deleted node).
        """
        try:
            from modules.ssh_worker import wait_for_worker as _wait_worker
            if not _wait_worker(server_id, 5000):
                QMessageBox.warning(self, self.t("msg.error_title"), self.t("msg.worker_busy"))
                return False
        except Exception:
            pass  # the registry is unavailable — do not block the deletion over this
        return True

    def _remove_node_guarded(self, node: "ServerNode") -> bool:
        """The single node-deletion path: confirmation → SSHWorker guard → remove.

        Used by the sidebar button, the Delete key (MapView) and the node
        context menu (v0.7.3). Returns True if the deletion happened.
        """
        # v1.2.4 (D7): attached notes — extend the CONFIRMATION TEXT (not two dialogs)
        attached = self.scene.notes_attached_to(node.data.id)
        if self._i18n_available:
            confirm_text = self.t("msg.confirm_delete").format(alias=node.data.alias)
            if attached:
                confirm_text += "\n" + self.t("msg.delete_server_with_notes").format(
                    count=len(attached))
        else:
            confirm_text = f"Delete server '{node.data.alias}'?"
        reply = QMessageBox.question(
            self,
            self.t("dialog.confirm_delete") if self._i18n_available else "Confirm Deletion",
            confirm_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return False
        if not self._ensure_worker_done(node.data.id):
            return False
        alias = node.data.alias
        host = node.data.host
        # v1.2.4 (D7): the detach BEFORE the removal — LIFO: undo will first
        # restore the node, then re-attach the notes (the node is alive by then)
        from modules.undo_commands import CmdAttachNote
        for n in list(attached):
            self._push_command(CmdAttachNote(self, n, node.data.id, "detach"))
        # v0.8.3: capturing the node's arrows BEFORE the removal — undo will restore them with the node
        arrows = [
            # v1.2.6: the 5th element — the bidirectional mode (undo restores the connection as it was)
            (a.source.data.id, a.target.data.id, a.label_text, a.connection_type,
             bool(getattr(a, "bidirectional", False)))
            for a in self.scene.arrows()
            if a.source is node or a.target is node
        ]
        from modules.undo_commands import CmdAddRemoveNode
        self._push_command(CmdAddRemoveNode(self, self.scene, node.data, "remove", arrows))
        self.refresh_sidebar()
        self._sync_status_targets()  # v0.7.1: the node is gone — remove it from the check plan
        if self.log:
            self.log.info("Server deleted", extra={"alias": alias, "host": host})
        self.statusBar().showMessage(self.t("status.server_deleted", alias=alias))
        self._mark_dirty()  # ← unsaved changes
        return True
