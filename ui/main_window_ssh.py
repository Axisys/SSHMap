"""SshMixin — the "SSH connections and terminal windows" cluster.

v1.1.4 (ROADMAP v1.1.4, task 3): extracted from ui/main_window.py as part of the
"main_window.py hygiene" series. The "module + callbacks" pattern (precedents:
the v0.9.9.4 sidebar, the v0.9.9.3 diagnostics): the mixin — methods only,
MainWindow remains the facade, the public API is unchanged; method names and
call sites were not touched.

The cluster also takes in the whole "Quick launch" block
(``_open_quick_launch_dialog``, ``_run_quick_launch_entry``, ``_quick_launch_url``,
``_quick_launch_command``) — it lives on the same connect/terminal path
(initial_command).

v1.1.3 (SFTP) has already been released — the sftp_worker.py/sftp_tab.py code is
in place, so the SSH cluster moves together with it (ROADMAP "Order").

Ownership of shared state (AUDIT §3, pinned down by this comment):
  * ``self._terminal_windows`` — registry of open terminal SESSIONS
    (v1.2: TerminalSessionPage from modules/terminal_page.py, not windows — the
    node's green dot goes out only when ALL of the node's sessions are closed;
    the "4 of your own terminals" limit is counted by sessions across all
    windows; v1.2.1: one window can host several of the node's sessions as
    tabs — _spawn_terminal_window reuses the node's live window via
    window.add_session(), otherwise creates a new window; v1.2.2: in "tabs"
    mode (terminal_mode) sessions open as a TAB in the "Terminals" dock —
    _ensure_terminals_dock; the registry/limit/green dot are still counted by
    SESSIONS regardless of the container; v1.2.3: the same registry is the
    provider of the multi-input hub modules/multi_input.py (broadcasting input
    to all open sessions));
  * ``self._terminals_dock`` — the "Terminals" dock (v1.2.2, lazy creation;
    modules/terminal_dock.TerminalsDock), None until the "tabs" mode was used;
  * ``self._ssh_connected_nodes`` — ids of nodes with an active session (green dot);
  * ``self._info_collectors`` — registry of SystemInfoCollector by server_id.
The mixin does NOT import ui.main_window (cycle) — only duck-typing on the
instance; SSHTerminalWindow/SSHConnectDialog/_ext_term are taken from the
facade module at call time (host_attr) — a test seam for swapping
``MW.SSHTerminalWindow``/``MW.SSHConnectDialog``/``MW._ext_term`` (otherwise
an offscreen run would hang on the real modals).
"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence  # v1.2.3: multi-input F12 shortcut (QAction)
from PySide6.QtWidgets import QDialog, QMessageBox

try:  # v1.1.4: shared seam for swapping the facade module's globals (see mixin_support)
    from .mixin_support import host_attr
except ImportError:
    from mixin_support import host_attr

try:  # v1.2.3 (ROADMAP v1.2.3): multi-input — highlight of the session containers
    from ..modules.multi_input import apply_container_highlight as _apply_multi_highlight
except ImportError:
    from modules.multi_input import apply_container_highlight as _apply_multi_highlight


class SshMixin:
    """SSH methods: dialog, terminal windows, automatic info collection, quick launch."""

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

    def _find_terminal_window_for(self, node_id):
        """v1.2.1 (task 1): the node's live terminal window — so that a new
        session can be opened as a TAB in it. The registry holds sessions (pages);
        the page knows its host (set_host_window). A dead C++ object / a fake
        without _host_window -> None (duck-typing, RuntimeError does not crash)."""
        for s in list(getattr(self, "_terminal_windows", [])):
            try:
                sd = getattr(s, "server_data", None)
                if sd is None or getattr(sd, "id", None) != node_id:
                    continue
                w = getattr(s, "_host_window", None)
                if w is None:
                    continue
                w.windowTitle()  # alive check (C++ object not removed)
                return w
            except RuntimeError:
                continue  # C++ object removed during teardown — keep looking
        return None

    def _ensure_terminals_dock(self):
        """v1.2.2 (task 2): the "Terminals" dock in MainWindow — lazy creation.

        The first session in "tabs" mode creates a QDockWidget with
        TerminalDockContent (a QTabWidget of pages, modules/terminal_dock.py) in
        the right area and shows it; repeated calls return the same dock (if it
        was hidden — show it again). The map remains the central widget:
        self.view is not touched. The dock has no WA_DeleteOnClose — the
        container outlives its sessions (per-page teardown, page.shutdown())."""
        dock = getattr(self, "_terminals_dock", None)
        if dock is None:
            try:
                from modules.terminal_dock import TerminalsDock
            except ImportError:
                from ..modules.terminal_dock import TerminalsDock
            dock = TerminalsDock(self)
            self._terminals_dock = dock
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            # v1.3: Qt expands a NEW dock to the minimum (~300px), and the
            # command library panel (min. 86px + the splitter handle) squeezed
            # the terminal to ~14 columns — explicit starting width on FIRST
            # creation (repeated show does not reset the size; the user can drag).
            self.resizeDocks([dock], [520], Qt.Orientation.Horizontal)
        else:
            try:
                dock.show()   # the dock may have been hidden (last tab / the close button in the title bar)
            except RuntimeError:
                pass  # C++ object already destroyed (close race) — the dock is not needed
        return dock

    def _spawn_terminal_window(self, node: "ServerNode", password: str = None,
                               initial_command: str = ""):
        """v1.0RC4: creating a terminal window + bookkeeping (single path).

        Extracted from _run_ssh_connect (v0.9.5.6) so that "Quick launch" with a
        command could open a terminal WITHOUT the SSH dialog (the password is
        already in the keyring / key auth): the connection indicator, the
        tracking (_terminal_windows/_forget_terminal_window) and show() — exactly
        like the regular connect path.

        v1.1.1 (item 3): the limit on your own terminals (terminal_max_open,
        default 4) — on reaching it NO refusal: a suggestion to close the
        OLDEST session / cancel. Returns None if the user canceled (the calling
        code must not report an "opened" terminal).

        v1.2 (ROADMAP task 4): the registry registers SESSIONS
        (TerminalSessionPage), not windows — the limit is counted by sessions
        across ALL windows; the teardown of the oldest one on the limit — via
        the page (page.close_terminal -> the host's close_page).

        v1.2.1 (task 1): a new session = a new tab — if the node already has a
        live terminal window (_find_terminal_window_for), the session is opened
        there via window.add_session() (the tab title — the node's alias, the
        status message terminal.session_new_tab); otherwise — a new window with
        a single tab (v1.2 behavior).

        v1.2.2 (tasks 2/4): the display mode from the terminal_mode key
        ("windows" default | "tabs"): in "tabs" mode a new session opens as a
        TAB in the "Terminals" dock (_ensure_terminals_dock, lazy creation) —
        node-window reuse does not apply; applied WITHOUT a restart: new
        sessions go to the chosen mode, open windows/dock keep living as they
        are until closed.
        """
        try:
            from modules.ssh_terminal import load_terminal_settings as _load_ts
        except ImportError:
            from ..modules.ssh_terminal import load_terminal_settings as _load_ts
        ts_cfg = _load_ts()
        max_open = ts_cfg["max_open"]
        mode = ts_cfg["mode"]   # v1.2.2: "windows" (default, current behavior) | "tabs"
        if len(self._terminal_windows) >= max_open and self._terminal_windows:
            oldest = self._terminal_windows[0]  # creation order — list order (sessions)
            alias = getattr(getattr(oldest, "server_data", None), "alias", "?")
            reply = QMessageBox.question(
                self, self.t("msg.terminal_limit_title"),
                self.t("msg.terminal_limit_close_oldest", limit=max_open, alias=alias),
                QMessageBox.Close | QMessageBox.Cancel, QMessageBox.Cancel)
            if reply != QMessageBox.Close:
                return None  # canceled — do not open a new terminal
            try:
                oldest._force_close = True  # the "ask" behavior does not ask again
                oldest.close_terminal()
            except Exception:  # noqa: BLE001 — the session/window may have already vanished (teardown)
                pass
            self._forget_terminal_window(oldest)  # immediately from the registry (destroyed still on its way)
        node.update_appearance()
        node.set_ssh_connected(True)
        self._ssh_connected_nodes.add(node.data.id)  # v0.9.4-fix: indicator reset on terminal close
        if mode == "tabs":
            # v1.2.2 (task 2): a new session -> the "Terminals" dock on the map
            # (lazy creation / repeated show). Open "windows"-mode windows keep
            # living as they are — node-window reuse does not apply here (task 4).
            dock = self._ensure_terminals_dock()
            content = dock.content
            had_tabs = content.session_tabs.count() > 0
            page = content.add_session(
                node.data, password=password, initial_command=initial_command)
            terminal_window = dock
            if had_tabs:   # joining an already open container — as in v1.2.1
                try:
                    self.statusBar().showMessage(
                        self.t("terminal.session_new_tab", alias=node.data.alias), 4000)
                except Exception:  # noqa: BLE001 — the status bar is cosmetic during teardown
                    pass
        else:
            win_cls = host_attr(self, "SSHTerminalWindow")
            if win_cls is None:
                raise RuntimeError("SSHTerminalWindow is not available in the MainWindow module")
            # v1.2.1 (task 1): a new session = a new tab — if the node already
            # has a live terminal window, open the session there (the tab title
            # — the node's alias); otherwise — a new window with a single tab
            # (v1.2 behavior).
            existing = self._find_terminal_window_for(node.data.id)
            if existing is not None and hasattr(existing, "add_session"):
                page = existing.add_session(
                    node.data, password=password, initial_command=initial_command)
                terminal_window = existing
                try:
                    self.statusBar().showMessage(
                        self.t("terminal.session_new_tab", alias=node.data.alias), 4000)
                except Exception:  # noqa: BLE001 — the status bar is cosmetic during teardown
                    pass
            else:
                terminal_window = win_cls(
                    node.data, self, password=password, initial_command=initial_command)
                page = getattr(terminal_window, "page", None) or terminal_window
        # v1.2: we register the SESSION (the page), not the window; a fake
        # without .page — itself (the host_attr test seam: swapping
        # MW.SSHTerminalWindow).
        session = page
        session.destroyed.connect(lambda *_a, s=session: self._forget_terminal_window(s))
        self._terminal_windows.append(session)
        terminal_window.show()
        # v1.2.3 (ROADMAP task 2): in multi-input mode a new session is
        # highlighted immediately (frame / "MULTI" badge) + the plaque counter
        # is updated.
        self._multi_refresh_ui()
        return terminal_window

    def _apply_ssh_dialog_fields(self, node_id: str, user: str, key_path: str, ssh_port: int):
        """v1.0-fix (audit #2): apply user/key/port from the SSH dialog to the node
        via the undo stack + a dirty marker (single path).

        Used by the regular connect (_run_ssh_connect) and "Open in external
        terminal" (SSHConnectDialog._open_external): the latter used to write
        directly to node.data — Ctrl+Z did not roll it back, on close without
        Ctrl+S the changes were lost without a "save?" dialog, and the card did
        not redraw the SSH:<port> line.
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
        """v0.9.5.6: the SSH dialog -> on success: update the node data, the
        indicator, automatic info collection and the terminal window.

        Shared path for "Connect via SSH" from the toolbar / context menu
        (prefill="") and from the server properties dialog (prefill_password —
        the password from the properties fields, so the user does not retype it).
        v1.0RC4: initial_command — the first command for the terminal (quick
        launch with a command and no keyring password).
        """
        dlg_cls = host_attr(self, "SSHConnectDialog")
        if dlg_cls is None:
            raise RuntimeError("SSHConnectDialog is not available in the MainWindow module")
        dlg = dlg_cls(node.data, self)
        if prefill_password:
            dlg.password_edit.setText(prefill_password)
        if dlg.exec() != QDialog.Accepted:
            return
        # v0.9.4-fix: edits to user/key_path/ssh_port from the dialog go through
        # the undo stack and mark the project dirty (previously they were written
        # directly to node.data — lost on exit without Ctrl+S and not rolled
        # back). v1.0-fix (audit #2): a single helper _apply_ssh_dialog_fields —
        # "Open in external terminal" uses it too. v1.1.2RC1 (N1): this is now
        # the REAL sole field write on the regular path — the dialog
        # (_on_worker_success) no longer writes to node.data itself, so old/new
        # here differ and CmdEditNodeData is pushed: Ctrl+Z rolls back the
        # user/key/port change made by a successful connect.
        self._apply_ssh_dialog_fields(
            node.data.id, dlg.user_edit.text().strip(),
            dlg.key_path_edit.text().strip(), dlg.port_edit.value())
        # AUDIT v0.7.2 (medium #7): the password is NOT stored in the model — we
        # pass it directly to the terminal window below; the dialog itself has
        # already written it to the keyring (_on_worker_success), so nothing is
        # lost when saving the project.

        # v1.0RC4: the connection indicator + window tracking — in
        # _spawn_terminal_window (a single path for the regular connect and
        # quick launch with a command).
        if self.log:
            self.log.info("SSH connected", extra={"alias": node.data.alias, "host": node.data.host})
        self.statusBar().showMessage(self.t("status.ssh_connected", alias=node.data.alias))

        # v0.9: automatic server info collection after a successful connect
        # (the dialog's password has not been lost yet; NOT via StatusChecker —
        # that one is designed to work without authentication)
        if getattr(node.data, "os_name", "") == "" and \
                hasattr(dlg, "password_edit"):
            self._collect_node_info(
                node, password=dlg.password_edit.text(), auto=True)

        # Open interactive terminal (password — explicitly, see AUDIT v0.7.2
        # medium #7; v1.0RC4: initial_command — the first quick launch command,
        # if there was one)
        self._spawn_terminal_window(
            node, password=dlg.password_edit.text(), initial_command=initial_command)

    # ── v0.9: automatic server info collection (Linux) ───────────────────

    def _collect_node_info(self, node, password: str = "", auto: bool = False):
        """Run SystemInfoCollector for the node.

        auto=True — a quiet auto-start after a successful SSH connect (no error
        messages, only the status bar).
        """
        try:
            from services.system_info_collector import SystemInfoCollector
        except ImportError as e:
            if self.log:
                self.log.warning(f"SystemInfoCollector unavailable: {e}")
            return
        sid = node.data.id
        # Guard: do not spawn parallel collections for the same node
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
        """Collection result: write to node.data + dirty + redraw."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # the node was deleted while collecting
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
            return  # quiet mode — do not scare the user on a regular connect
        try:
            self.statusBar().showMessage(
                self.t("status.info_failed", error=error), 8000)
        except Exception:
            pass

    def _connect_ssh_external(self, node=None):
        """v0.8.2: open an SSH session in the OS's system terminal
        (wt/cmd/gnome-terminal).

        The password is NOT passed (visible in ps) — the OS's ssh will ask for
        it itself / key auth.
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

    # ── v1.0RC4: quick launch (links/commands on the server) ───────────────

    def _open_quick_launch_dialog(self, node=None):
        """Configure the quick launch entries for a server.

        Entry points: the "Quick launch -> Configure…" submenu (right-click on a
        sidebar row / a map node) and the button in the server properties
        (AddServerDialog). Changes — via the undo stack (CmdEditNodeData), like
        any data edit.
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
        """Run a quick launch entry.

        type="url"     -> the default browser (webbrowser);
        type="command" -> the first command in the server's SSH terminal.
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
        except Exception as e:  # noqa: BLE001 — an entry failure does not crash the menu
            if self.log:
                self.log.exception(f"Quick launch failed for {node.data.alias}")
            QMessageBox.critical(self, self.t("msg.error_title"),
                                 self.t("msg.ql_open_failed", error=str(e)))

    def _quick_launch_url(self, url: str, name: str):
        """URL entry — open in the default browser (stdlib webbrowser)."""
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
            # v1.0-fix: the "name" key cannot go into extra — it is a built-in
            # LogRecord attribute (the logger name), makeRecord() dies with
            # KeyError; hence the spurious "Quick launch failed" after a
            # successful URL open.
            self.log.info("Quick launch URL opened", extra={"ql_name": name, "url": url})

    def _quick_launch_command(self, node, cmd: str, name: str):
        """Command entry — the first command in the server's SSH terminal.

        The password is already in the keyring (or key auth) -> the terminal
        opens directly, without a dialog; no credentials at all — the regular
        SSH dialog, and after the connect the same command is sent to the
        terminal (initial_command).
        """
        data = node.data
        pwd = ""
        try:
            from services.credential_manager import get_credential_manager
            pwd = get_credential_manager().load_password(data.id) or ""
        except Exception:  # noqa: BLE001 — the keyring is unavailable: the dialog path
            pwd = ""
        if pwd or (data.key_path or "").strip():
            # v1.1.1: None — the user canceled on the terminal limit; the
            # "command sent" status would be false in this case.
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
            # v1.0-fix: the same KeyError — the "name" key is reserved by LogRecord.
            self.log.info("Quick launch command started",
                          extra={"alias": data.alias, "ql_name": name})

    def _forget_terminal_window(self, session):
        """v1.2 (ROADMAP task 4): the registry holds SESSIONS
        (TerminalSessionPage), not windows — a window can also come here
        (resolved to its .page).

        v0.9.4-fix: the terminal was closed -> dim the node's green SSH dot
        (previously the indicator burned forever after the first connect).
        Since v1.2 the dot goes out only when ALL of the node's sessions are
        closed — counted by the registry's sessions.
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
                    # all of the node's sessions are closed — remove the indicator
                    self._ssh_connected_nodes.discard(sid)
                    node = self.scene.get_node(sid) if hasattr(self.scene, "get_node") else None
                    if node is not None:
                        node.set_ssh_connected(False)
        except RuntimeError:
            pass  # C++ object already destroyed during teardown — fine
        # v1.2.3 (ROADMAP task 4): a dead session was removed from the registry
        # on the regular path — the "MULTI: N sessions" plaque counter is
        # updated, the broadcast keeps working for the rest (dead threads are
        # additionally filtered by the hub by liveness).
        self._multi_refresh_ui()

    # ── v1.2.3: multi-input (ROADMAP v1.2.3) ────────────────────────────────
    # The mode state lives in the hub modules/multi_input.py (a process
    # singleton), which MainWindow holds as self._multi_hub and passes to
    # TerminalWidget by default; the registry of open sessions — provider =
    # self._terminal_windows (the same one as for the green dot / the limit).
    # Methods here: the UI reaction to a state change and the registry hooks.
    # The broadcast itself lives at the single input point
    # (TerminalWidget._send -> hub.broadcast) — the mixin does not touch it.

    def _toggle_multi_input(self, checked=None):
        """v1.2.3 (tasks 2/3): toggle multi-input — the "View" menu item
        (a checkable QAction; v1.2.4-fix: wired to toggled(bool) — in PySide6 6.11
        triggered via QMenu.addAction(text, slot) does NOT pass the state to
        the Python slot) or the exit button on the plaque (an explicit False).

        checked=None — a REAL toggle (the fallback path for no-arg calls; before
        v1.2.4-fix there was a no-op "keep the current state" branch here);
        True/False — an explicit state. The hub itself notifies the listeners
        -> _on_multi_changed (UI)."""
        hub = getattr(self, "_multi_hub", None)
        if hub is None:
            return  # a window without a hub (a test fake) — nothing to do
        target = (not hub.active) if checked is None else bool(checked)
        hub.set_active(target)

    def _on_multi_changed(self, active: bool):
        """v1.2.3: a hub state change -> UI (tasks 2/3).

        * QAction: the check + the F12 shortcut are ENABLED only in the mode
          (F12 — exit; the mode is off -> the shortcut is disabled and the key
          goes to the shell as \\x1b[24~);
        * the status bar plaque "MULTI: N sessions" + the exit button —
          visibility;
        * the highlight of ALL open containers (frame + the tabs' "MULTI"
          badges, the window title) or its reset;
        * the status message (status.multi_enabled / status.multi_disabled)."""
        act = getattr(self, "act_multi_input", None)
        if act is not None:
            try:
                act.setChecked(active)
                # F12 — exit from the mode only: the QAction shortcut lives ONLY
                # in the mode (QAction has no setShortcutEnabled; an empty
                # QKeySequence = no shortcut -> F12 goes to the focused widget,
                # to the shell as \x1b[24~ per the TerminalWidget RC2 mapping).
                act.setShortcut(QKeySequence("F12") if active else QKeySequence())
            except RuntimeError:
                pass  # C++ object already removed (close race) — nothing to update
        count = len(getattr(self, "_terminal_windows", []))
        try:
            label = getattr(self, "_multi_label", None)
            plaque = getattr(self, "_multi_plaque", None)
            if label is not None:
                label.setText(self.t("terminal.multi_status", count=count))
            if plaque is not None:
                plaque.setVisible(active)
        except RuntimeError:
            pass  # C++ object already removed (close race) — nothing to update
        for s in list(getattr(self, "_terminal_windows", [])):
            try:
                host = getattr(s, "_host_window", None)
            except RuntimeError:
                continue  # the page was destroyed during teardown — skip
            if host is None:
                continue
            try:
                _apply_multi_highlight(host, active)
            except RuntimeError:
                pass  # the container was already destroyed (close race) — skip
        try:
            key = "status.multi_enabled" if active else "status.multi_disabled"
            self.statusBar().showMessage(self.t(key), 4000)
        except Exception:  # noqa: BLE001 — the status bar is cosmetic during teardown
            pass

    def _multi_refresh_ui(self):
        """v1.2.3 (task 4): the registry changed (a session opened/closed) ->
        the plaque counter + the container highlight. Called from
        _spawn_terminal_window / _forget_terminal_window; the mode is off —
        no-op (the plaque is hidden, nothing to highlight). Idempotent:
        reapplying the badges/frame — the same line."""
        hub = getattr(self, "_multi_hub", None)
        if hub is None or not hub.active:
            return
        count = len(getattr(self, "_terminal_windows", []))
        try:
            label = getattr(self, "_multi_label", None)
            plaque = getattr(self, "_multi_plaque", None)
            if label is not None:
                label.setText(self.t("terminal.multi_status", count=count))
            if plaque is not None:
                plaque.setVisible(True)
        except RuntimeError:
            pass  # C++ object already removed (close race) — nothing to update
        for s in list(getattr(self, "_terminal_windows", [])):
            try:
                host = getattr(s, "_host_window", None)
            except RuntimeError:
                continue  # the page was destroyed during teardown — skip
            if host is None:
                continue
            try:
                _apply_multi_highlight(host, True)
            except RuntimeError:
                pass  # the container was already destroyed (close race) — skip

    def _multi_shutdown(self):
        """v1.2.3: application exit — the mode is turned off, the provider is
        unbound (the registry dies together with the window; a dangling callable
        would keep the dead window alive)."""
        hub = getattr(self, "_multi_hub", None)
        if hub is None:
            return
        try:
            hub.set_active(False)
            provider = getattr(self, "_multi_provider", None)
            if provider is not None and hub.session_provider is provider:
                hub.set_session_provider(None)
        except Exception:  # noqa: BLE001 — multi-input must not block exit
            pass
