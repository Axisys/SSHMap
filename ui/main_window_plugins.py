"""`PluginMixin` — the window half of the plugin API v1: the registry surfaces and the enable switch (AGENTS.md §4.1, §4.10).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import
the window module (a cycle) — it duck-types the instance. The manager (`modules/plugin_manager.py`) reports
FACTS (records and events) and this cluster turns them into a menu and into status-bar lines; the frozen
contract is `PLUGINS.md`, and the manager itself stays HEADLESS.

Owned here: the discovery entry point (`start_plugin_discovery()`, called once from `main.py`), the
per-plugin rows of the "Plugins" menu (`_populate_plugin_items()` — the DYNAMIC rows only), the
plugin-visible node registry, the context-menu hook (`_extend_node_context_menu()`, the ONE entry point of
BOTH surfaces) and the run/status/error reporting. Mechanism — `DOCUMENTATION.md` §33."""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction

try:  # v1.4rc1 (plugin foundation): discovery + the registry of the plugins
    from ..modules import plugin_manager as plugin_manager
except ImportError:
    from modules import plugin_manager as plugin_manager

try:  # v0.9.9.4/UI polish: the per-plugin row icon (the same three-step layout as the window's)
    from .icons import set_action_icon
except ImportError:
    try:
        from ui.icons import set_action_icon
    except ImportError:
        try:
            from icons import set_action_icon
        except ImportError:  # flat layout without ui/icons — text rows, as before
            def set_action_icon(action, name):  # noqa: N802 — stub with the same signature
                return False


class PluginMixin:
    """The "Plugins" menu, its rows and the plugin node registry (the window half of `PLUGINS.md`)."""

    def start_plugin_discovery(self):
        """Discover the plugins — called ONCE from main.py, after show(), before app.exec().

        The ROADMAP places the discovery exactly there: the window exists (so a load
        error can be reported in its status bar) while the event loop has not started
        yet (so the registry is complete before the first frame the user sees). Never
        raises: a plugin must not be able to break the startup (ROADMAP rc1 task 1).
        """
        try:
            self._plugin_manager.discover()
        except Exception as e:  # noqa: BLE001 — the discovery is wrapped internally too
            if self.log:
                self.log.warning(f"Plugin discovery failed: {e}")
        self._populate_plugin_items()
        self._report_plugin_events()
        if self.log:
            self.log.info(f"Plugins: {len(self._plugin_manager.loaded_records())} loaded "
                          f"of {len(self._plugin_manager.records())} discovered")

    def _reload_plugins(self):
        """`Plugins → Reload` (a registry action): re-run the discovery and re-render.

        This is what makes a dropped-in `~/.sshmap/plugins/<name>.py` usable without a
        restart — every folder plugin is exec'd fresh (a changed file is really re-read).
        """
        try:
            self._plugin_manager.reload()
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Plugin reload failed: {e}")
        self._populate_plugin_items()
        self._report_plugin_events()

    def _populate_plugin_items(self):
        """(Re)build the per-plugin rows of the "Plugins" menu from the manager's records.

        Called at construction and on every `aboutToShow` (the v1.3.3.1 pattern: the
        list is never frozen at construction). Only the DYNAMIC rows are removed —
        `_plugin_rows` holds them, so the permanent "Run"/"Reload" items and their
        separator survive every rebuild. An error record is shown too: disabled and
        unchecked, with the failure in its tooltip (the user must see that the file was
        found and why it did not load). With no records at all — a disabled placeholder
        naming the folder, so the feature is discoverable. Never raises.

        v1.4rc3: the pass also (a) re-feeds the plugin node registry (the same narrowing
        the startup discovery does, so a node added later is visible to `run_on_nodes`)
        and (b) enables "Run on selected servers" only while a plugin implements the hook
        — otherwise the item would be a silent no-op.
        """
        self._sync_plugin_nodes()
        menu = getattr(self, "_plugin_menu", None)
        if menu is None:
            return
        try:
            for act in self._plugin_rows:
                menu.removeAction(act)          # exactly the rows of the previous build
            self._plugin_rows = []
            before = self._plugin_sep if self._plugin_sep is not None else self.act_plugins_reload
            records = self._plugin_manager.records()
            run_records = [r for r in records
                           if plugin_manager.HOOK_RUN_ON_NODES in r.hooks]
            if not records:
                placeholder = QAction(self.t("plugins.empty"), menu)
                placeholder.setEnabled(False)   # informative, not a command
                menu.insertAction(before, placeholder)
                self._plugin_rows.append(placeholder)
            else:
                for rec in records:
                    act = QAction(rec.label(), menu)
                    act.setCheckable(True)
                    act.setChecked(rec.ok)
                    act.setToolTip(self._plugin_tooltip(rec))
                    try:  # v1.4rc3: the puzzle glyph (a menu of plugins reads as one family)
                        set_action_icon(act, "plugin")  # follows the theme too
                    except Exception:  # noqa: BLE001 — the icon is cosmetic
                        pass
                    if rec.failed:
                        act.setEnabled(False)   # found, but not loadable — nothing to switch
                    else:
                        act.toggled.connect(
                            lambda checked, pid=rec.plugin_id: self._on_plugin_toggled(pid, checked))
                    menu.insertAction(before, act)
                    self._plugin_rows.append(act)
                if run_records and not self._plugin_manager.node_records():
                    # v1.4rc3: a plugin-ready action with no nodes to act on — say so
                    # instead of leaving a disabled item without a reason.
                    hint = QAction(self.t("plugins.run_hint"), menu)
                    hint.setEnabled(False)
                    menu.insertAction(before, hint)
                    self._plugin_rows.append(hint)
            # The permanent "Run" item follows the plugins that can serve it AND the
            # registry it would act on — an enabled item with no servers in the plugin
            # registry can only answer "nothing to run on".
            run_act = getattr(self, "act_plugins_run", None)
            if run_act is not None:
                run_act.setEnabled(bool(run_records)
                                   and bool(self._plugin_manager.node_records()))
        except RuntimeError:
            return  # Qt teardown — the menu is already destroyed
        # The rebuilt rows are QActions of a menu that the palette walks with temporary
        # wrappers (gotcha #9) — keep them in the guard like the language submenu's children.
        self._rebuild_qaction_guard()

    def _sync_plugin_nodes(self):
        """v1.4rc3: refresh the plugin-visible node registry from the CURRENT map.

        The startup discovery (`start_plugin_discovery`) feeds the registry once; a
        project opened or edited afterwards would otherwise leave a plugin looking at a
        stale map (an empty one at startup). The pass is cheap, idempotent and runs on
        every "Plugins" menu open — the same place the palette takes its records from.
        The internal `key_path` FACTS travel separately (the credential resolver of
        `ctx.run_command` needs them, a plugin never sees them). Never raises.
        """
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return
        facts = {}
        for node in nodes:
            key_path = getattr(node.data, "key_path", "") or ""
            if key_path:
                facts[node.data.id] = {"key_path": key_path}
        try:
            self._plugin_manager.set_nodes([n.data for n in nodes], facts=facts)
        except Exception as e:  # noqa: BLE001 — a plugin registry must never break the menu
            if self.log:
                self.log.warning(f"Plugin node registry refresh failed: {e}")
        # The registry may have just become EMPTY (the last node removed, a new project):
        # the "Run on selected servers" item must follow immediately, or the user keeps an
        # enabled item that can only answer "nothing to run on" (every refresh_sidebar
        # path lands here, the menu open included).
        run_act = getattr(self, "act_plugins_run", None)
        if run_act is not None:
            try:
                run_act.setEnabled(bool(self._plugin_manager.node_records())
                                   and bool(self._plugin_records_with_hook(
                                       plugin_manager.HOOK_RUN_ON_NODES)))
            except RuntimeError:
                pass  # Qt teardown

    def _plugin_records_with_hook(self, hook_name: str) -> list:
        """The loaded plugins that declare a hook ([] — no plugin, no hook)."""
        try:
            return [r for r in self._plugin_manager.loaded_records() if hook_name in r.hooks]
        except Exception:  # noqa: BLE001 — a broken manager must not break a context menu
            return []

    def _extend_node_context_menu(self, menu, node=None):
        """v1.4rc3 (ROADMAP task 7): let every plugin add rows to a node context menu.

        The ONE entry point behind both surfaces of the contract ("the node context menu
        of the map or of the sidebar", PLUGINS.md §3): the caller passes the live QMenu
        and either the clicked `ServerNode` (map) or its node id (sidebar); the manager
        narrows whatever it gets to the frozen `{id, alias, host, port, user}` records.

        The hooks run synchronously on the GUI thread inside the contract's 200 ms budget
        and are wrapped by the manager ("never throws"): a plugin that raises contributes
        nothing and is reported, the menu still opens. The QActions a plugin created are
        the manager's to keep alive, so the guard is re-run right after the call
        (gotcha #9: a dead Python QAction wrapper takes the C++ menu down with it).

        Returns the number of plugins asked. Never raises.
        """
        if menu is None:
            return 0
        asked = 0
        try:
            asked = int(self._plugin_manager.plugin_node_context_menu(menu, node))
        except Exception as e:  # noqa: BLE001 — a plugin must not be able to kill the menu
            if self.log:
                self.log.warning(f"Plugin context menu hook failed: {e}")
        if asked:
            # The rows a plugin created live in a menu built outside the i18n registry:
            # keep their wrappers in the guard (gotcha #9), then re-run the rebuild so the
            # two sources end up in one list. A context menu of a window without plugins
            # pays for none of this.
            try:
                self._plugin_menu_actions.extend(list(menu.actions()))
                if len(self._plugin_menu_actions) > 200:      # bounded: context menus are ephemeral
                    del self._plugin_menu_actions[:-100]
            except RuntimeError:
                pass  # the menu died under us — nothing to guard
            self._rebuild_qaction_guard()
        return asked

    def _run_plugins_on_nodes(self):
        """v1.4rc3 (task 8): "Run on selected servers" — the `run_on_nodes` hook.

        Scope: the CURRENT selection; with nothing selected the whole map is the target
        (the action stays useful, and the status line says which scope was used). The
        manager starts one managed worker per plugin that declares the hook — the work
        itself (`ctx.run_command`) runs on its own managed workers, so nothing blocks the
        GUI thread (PLUGINS.md §6). The status line reports how many plugins started and
        on how many nodes; a plugin reports its own results through `ctx.status()`.

        Never raises: a broken plugin is a log line + a status report, and the action
        with no capable plugin is a no-op (the menu item is disabled in that case).
        """
        try:
            nodes = list(self.selected_nodes())
        except Exception:  # noqa: BLE001 — a selection problem must not break the action
            nodes = []
        try:
            if nodes:
                started = int(self._plugin_manager.plugin_run_on_nodes(nodes))
            else:
                started = int(self._plugin_manager.plugin_run_on_nodes(None))
            if started:
                # The scope really used: the selection, or the whole map when there is
                # none — the count comes from what the plugins were actually given.
                count = len(nodes) if nodes else len(self._plugin_manager.node_records())
                self.statusBar().showMessage(
                    self.t("plugins.status.run_on_nodes", count=count), 8000)
            else:
                # Nothing could run: no node in the plugin registry (an unsaved map) or
                # no plugin implementing the hook — the status line says which. The
                # `plugins.run_hint` wording is reused deliberately (one key, one fact:
                # "add a server to use plugin commands on nodes").
                self.statusBar().showMessage(
                    self.t("plugins.no_selection")
                    if not self._plugin_manager.node_records()
                    else self.t("plugins.run_hint"), 8000)
        except Exception as e:  # noqa: BLE001 — an action must never crash the window
            if self.log:
                self.log.warning(f"Plugin run_on_nodes failed: {e}")

    def _plugin_tooltip(self, rec) -> str:
        """The tooltip of one plugin row: the version + the description, or the failure.

        The plugin's own strings (name/version/description) are the author's text — they
        are NOT i18n keys (the frozen contract: plugin strings stay outside the parity
        policy, `PLUGINS.md`). Only the failure sentence is translated.
        """
        if rec.failed:
            return self.t("plugins.status.error",
                          name=rec.label(), error=rec.detail or rec.error)
        text = f"v{rec.version}" if rec.version else ""
        if rec.description:
            text = f"{text} — {rec.description}" if text else rec.description
        return text

    def _on_plugin_toggled(self, plugin_id: str, enabled: bool):
        """The enable/disable switch of one plugin row (persisted in config.json)."""
        try:
            ok = bool(self._plugin_manager.set_enabled(plugin_id, enabled))
        except Exception as e:  # noqa: BLE001 — a switch must not break the window
            ok = False
            if self.log:
                self.log.warning(f"Plugin switch failed for {plugin_id!r}: {e}")
        if not ok:
            # The model did not move (an unknown id / a failed plugin) — put the checkbox
            # back to the state the manager really holds instead of leaving a lie on screen.
            self._populate_plugin_items()
            return
        self._report_plugin_events()

    def _report_plugin_events(self):
        """Turn the manager's events into status-bar lines (ROADMAP rc1: loaded/error/disabled).

        One line per event, in order (a QStatusBar keeps the last one); when the round
        carried an ERROR it is re-shown at the end, so a broken plugin stays the visible
        message instead of being overwritten by the round report. The "loaded" line is
        shown only for a RELOAD round — at startup the menu already says what is on and
        a status line per plugin would outlive its own usefulness. Never raises.
        """
        try:
            events = self._plugin_manager.drain_events()
        except Exception:  # noqa: BLE001
            return
        if not events:
            return
        lines = []                # [(text, timeout_ms)]
        first_error = None
        reloading = any(ev.get("kind") == plugin_manager.EVENT_RELOADED for ev in events)
        for ev in events:
            kind, rec = ev.get("kind"), ev.get("record")
            if kind == plugin_manager.EVENT_ERROR and rec is not None:
                text = self.t("plugins.status.error",
                              name=rec.label(), error=rec.detail or rec.error)
                first_error = first_error or (text, 10000)
                lines.append((text, 10000))
            elif kind == plugin_manager.EVENT_LOADED and rec is not None and reloading:
                lines.append((self.t("plugins.status.loaded", name=rec.label()), 5000))
            elif kind == plugin_manager.EVENT_ENABLED and rec is not None:
                lines.append((self.t("plugins.status.enabled", name=rec.label()), 5000))
            elif kind == plugin_manager.EVENT_DISABLED and rec is not None:
                lines.append((self.t("plugins.status.disabled", name=rec.label()), 5000))
            elif kind == plugin_manager.EVENT_HOOK_ERROR:
                # v1.4rc2: a hook that raised — drained from the queue (the signal path
                # has already shown it live; a drain must not lose it either).
                pid = rec.plugin_id if rec is not None else ""
                lines.append((self.t("plugins.status.hook_failed",
                                     name=self._plugin_label(pid),
                                     hook=str(ev.get("hook", "")),
                                     error=str(ev.get("error", ""))), 10000))
            elif kind == plugin_manager.EVENT_HOOK_TIMEOUT:
                # v1.4rc2: a hook that was abandoned after its budget.
                pid = rec.plugin_id if rec is not None else ""
                lines.append((self.t("plugins.status.hook_timeout",
                                     name=self._plugin_label(pid),
                                     hook=str(ev.get("hook", "")),
                                     ms=int(ev.get("budget_ms", 0))), 10000))
            elif kind == plugin_manager.EVENT_RELOADED:
                lines.append((self.t("plugins.status.reloaded", count=int(ev.get("count", 0))), 5000))
        if not lines:
            return
        if first_error is not None:
            lines.append(first_error)   # a failure must be the message that stays
        try:
            for text, timeout in lines:
                self.statusBar().showMessage(text, timeout)
        except RuntimeError:
            pass  # Qt teardown — the status bar is already destroyed

    def _plugin_label(self, plugin_id: str) -> str:
        """The display name of a plugin id (the id itself when the record is gone)."""
        try:
            rec = self._plugin_manager.get(plugin_id)
            if rec is not None:
                return rec.label()
        except Exception:  # noqa: BLE001
            pass
        return plugin_id or "?"

    def _on_plugin_status_requested(self, plugin_id: str, text: str, timeout_ms: int):
        """v1.4rc2: `ctx.status()` — a status-bar line with the TOKEN GUARD.

        A plugin may call this from a worker thread (the manager's signal carries it to
        the GUI thread). The guard is the v1.2.2 pattern of the dock's status line: every
        message takes a fresh token and the pending auto-clear of an older one is
        invalidated, so a slow asynchronous result can never blank a newer message.
        """
        try:
            message = str(text)
            if not message:
                return
            token = next(self._plugin_status_tokens)
            self._plugin_status_token = token
            self.statusBar().showMessage(message, max(0, int(timeout_ms)))
            if int(timeout_ms) > 0:
                QTimer.singleShot(int(timeout_ms), lambda tk=token: self._expire_plugin_status(tk))
        except (RuntimeError, TypeError, ValueError):
            pass  # Qt teardown / a broken timeout — a plugin line must never break the UI

    def _expire_plugin_status(self, token):
        """The auto-clear of a plugin status line — only if nothing newer arrived."""
        try:
            if token == self._plugin_status_token:
                self.statusBar().clearMessage()
        except RuntimeError:
            pass  # Qt teardown

    def _on_plugin_hook_failed(self, plugin_id: str, hook_name: str, detail: str):
        """v1.4rc2: a hook raised — the user hears about it (the contract's "never throws")."""
        try:
            self.statusBar().showMessage(
                self.t("plugins.status.hook_failed", name=self._plugin_label(plugin_id),
                       hook=hook_name, error=detail), 10000)
        except (RuntimeError, AttributeError):
            pass

    def _on_plugin_hook_timeout(self, plugin_id: str, hook_name: str, budget_ms: int):
        """v1.4rc2: a hook was abandoned after its budget — the app keeps living."""
        try:
            self.statusBar().showMessage(
                self.t("plugins.status.hook_timeout", name=self._plugin_label(plugin_id),
                       hook=hook_name, ms=int(budget_ms)), 10000)
        except (RuntimeError, AttributeError):
            pass
