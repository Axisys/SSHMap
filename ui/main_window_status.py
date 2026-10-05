"""`StatusMixin` — the node statuses, their probe rounds and the two freshness clocks (AGENTS.md §4.1, §4.8).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import
the window module (a cycle) — it duck-types the instance.

Owned here: the probe target list with its ONE skip set (`_sync_status_targets()` / `_status_skip_ids()`,
the filter `StatusChecker.set_skip_ids()` consumes), the programmatic unmanaged gate (`_refuse_unmanaged()`),
the two result slots, and the freshness family — the repaint tick (`FRESHNESS_TICK_MS`,
`_refresh_status_freshness()`) that never starts a round and never changes a status, plus the two marks it
carries (a STATUS's age, whose source of truth is the checker, and the COLLECTED FACTS' age).
Mechanism — `DOCUMENTATION.md` §19."""
try:  # v1.6.5 (ROADMAP tasks 3/4): the ONE predicate of an unmanaged card
    from ..models.server import is_unmanaged as _is_unmanaged
except ImportError:  # flat launch from the project root
    from models.server import is_unmanaged as _is_unmanaged


class StatusMixin:
    """The statuses, the probe targets and the two freshness marks (node statuses off the GUI thread)."""

    def _shutdown_status_checker(self, *_args):
        """v1.5rc3: the `destroyed` slot — stop the probe timer and the current round.

        Written as a method rather than an inline lambda because the checker can be
        ABSENT: `__init__` leaves `_status_checker = None` when the module is
        unavailable, and an embedder (or a test) may replace it. The old lambda assumed
        a live checker and raised on teardown — exactly the moment nothing may raise.
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return
        try:
            checker.shutdown()
        except Exception as e:  # noqa: BLE001 — a teardown path never raises
            if self.log:
                self.log.warning(f"StatusChecker shutdown failed: {e}")

    def start_status_checks(self):
        """v0.7.1: start periodic status checks (called once)."""
        checker = getattr(self, "_status_checker", None)
        if checker is not None and not checker.is_busy:
            try:
                self._sync_status_targets()
                checker.start()
            except Exception as e:
                if self.log:
                    self.log.warning(f"StatusChecker start failed: {e}")

    def _status_skip_ids(self) -> set:
        """The ids a status round must NEVER probe — the ONE source of the skip set (v1.6.5).

        Two families meet here and they are the same RULE ("this node has no measurement to
        make"): the demo map's EMULATED nodes (v1.5 — their status is declared by
        `storage/example_project.py`, not measured) and every UNMANAGED card (v1.6.5 — a
        server this user does not administer has no login to probe with, and painting it
        `offline` would be a claim about a measurement nobody can make).

        `StatusChecker.set_skip_ids()` filters in its `_subset()`, so the periodic timer, the
        round a project load starts and the on-demand "Check statuses now" all obey ONE
        filter without a second rule. Reading the SCENE is what makes a card switched to
        unmanaged (or back) take effect on the next round: `_sync_status_targets()` re-installs
        the set on every project load and after every node edit.
        """
        ids = {str(sid) for sid in (getattr(self, "_emulated_statuses", None) or {})}
        try:
            ids |= {str(n.data.id) for n in self.scene.nodes() if _is_unmanaged(n.data)}
        except (AttributeError, RuntimeError):
            pass  # no scene yet / Qt teardown — the emulated half is still correct
        return ids

    def _refuse_unmanaged(self, target, label_key: str = "") -> bool:
        """The ONE programmatic gate: True — the action was refused AND the user was told.

        Every entry point that cannot work without a login asks THIS question first (the SSH
        family, the external terminal, the info collection, the status round, the
        reachability report and a quick-launch COMMAND). `target` is a `ServerNode` or a bare
        `ServerData`; `label_key` names the verb so the sentence can say WHICH one was
        refused, and without it the generic `status.unmanaged_blocked` is used.

        The two MENU builders do not call this: they ask `ui/unmanaged.action_blocked()`
        while building and DISABLE the row, so the function-level gate is the second half of
        a single policy (a disabled row explains itself up front; a programmatic call — a
        hotkey, the palette, a double-click — reaches no row and must answer in the status
        bar instead).
        """
        if not _is_unmanaged(target):
            return False
        try:
            if label_key:
                text = self.t("unmanaged.blocked", action=self.t(label_key))
            else:
                text = self.t("status.unmanaged_blocked")
            self.statusBar().showMessage(text, 5000)
        except (RuntimeError, AttributeError):
            pass  # Qt teardown / a stripped window — the refusal itself already happened
        return True

    def _sync_status_targets(self):
        """Update the StatusChecker target list to match the current scene nodes.

        v1.3.3.3 (task 5): the normalization lives in ``status_checker._build_targets``
        — the on-demand round of "Check statuses now" builds its list with the same
        helper instead of a drifting copy.
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return
        try:
            from services.status_checker import _build_targets as _mk
        except ImportError:  # flat layout
            from status_checker import _build_targets as _mk
        try:
            _nodes = list(self.scene.nodes())
            checker.set_servers(_mk([
                (n.data.id, n.data.host, n.data.ssh_port or 22)
                for n in _nodes
            ]))
            # The SAME pass keeps the emulation in step: the demo's declared ids are never probed and
            # any other project clears the set (installed by `_open_example_map()` before the load and
            # cleared by every ordinary load / new project / save). `_set_emulated_statuses` owns the
            # write; this call repeats it so a checker built AFTER the state cannot miss it. The set is
            # `_status_skip_ids()` — the emulated ids AND every unmanaged card, read from the live scene.
            checker.set_skip_ids(self._status_skip_ids())
            # The SAME pass feeds the plugin registry — a `status_probe` / `run_on_nodes` hook sees exactly
            # the nodes the map holds (narrowed to {id, alias, host, port, user} by the manager,
            # `PLUGINS.md` §5). The internal facts carry the private key path, which is deliberately NOT
            # part of the plugin-visible record but IS needed by the core's credential resolver for
            # `ctx.run_command`.
            try:
                self._plugin_manager.set_nodes(
                    [(n.data.id, n.data.alias, n.data.host, n.data.ssh_port or 22, n.data.user)
                     for n in _nodes],
                    facts={n.data.id: {"key_path": getattr(n.data, "key_path", "") or ""}
                           for n in _nodes})
            except Exception as e:  # noqa: BLE001 — a plugin never breaks the probes
                if self.log:
                    self.log.warning(f"Plugin node registry not synced: {e}")
        except Exception as e:
            if self.log:
                self.log.warning(f"StatusChecker set_servers failed: {e}")
            return
        # v1.1.2 final (task 3): large map (N > LARGE_MAP_THRESHOLD) —
        # the check interval doubles (StatusChecker.effective_interval_ms);
        # a one-time status-bar hint when the threshold is crossed upward.
        try:
            if checker.is_large_map():
                if not getattr(self, "_auto_interval_hinted", False):
                    self._auto_interval_hinted = True
                    self.statusBar().showMessage(
                        self.t("status.auto_interval_hint", servers=checker.target_count), 8000)
            else:
                self._auto_interval_hinted = False  # below the threshold again — the hint may fire once more
        except (AttributeError, RuntimeError):
            pass  # Qt teardown — the status bar is already destroyed

    def _on_node_status_detail(self, server_id: str, detail: str):
        """v1.4rc2 (plugin foundation, rc2): the plugin detail of a merged status.

        `StatusChecker.status_detail` carries what a plugin's `status_probe` contributed
        (`PLUGINS.md` §3 — "appended to the node's tooltip"). It travels AFTER
        `status_changed`, so the node already has its colour; the detail only refines the
        tooltip. An empty detail removes a stale one.
        """
        node = self.scene.get_node(server_id)
        if node is None:
            return  # node already removed — it needs no tooltip
        try:
            # v1.5: the detail refines the CURRENT status, so it must not un-mark an
            # EMULATED one (the flag belongs to the status, not to this call).
            node.set_status(node.status, detail, emulated=node.status_emulated)
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"status detail failed for {server_id}: {e}")

    def _on_node_status_changed(self, server_id: str, status: str):
        """Handle the probe result for a single node."""
        node = self.scene.get_node(server_id)
        if node is None:
            return  # node already removed — it needs no status
        try:
            node.set_status(status)
            # v1.5rc3 (ROADMAP task 3): the result is dated. The checker owns WHEN the
            # probe answered and how old a result may get (`stale_threshold_s()`); the
            # card owns how it is painted and worded. Nothing here derives a STATUS
            # from the age — freshness is a label on the existing fact.
            self._apply_node_freshness(node)
        except Exception as e:
            if self.log:
                self.log.warning(f"set_status failed for {server_id}: {e}")
        else:
            self._update_counts_label()  # UI polish: online/warn/offline in the status bar
            # Review fix v0.8.0 (#3): the tree row marker is updated in place
            # (node.status — the actual status after set_status; unknowns are ignored)
            self._update_sidebar_status_marker(server_id)
            # v1.4.5 (ROADMAP task 3): a status change can move a node in or out of an
            # ACTIVE status filter — the in-place marker update would leave the filtered
            # tree stale, so the rows are rebuilt (only while a filter is on).
            if getattr(self, "_status_filter", ""):
                try:
                    self.refresh_sidebar()
                except RuntimeError:
                    pass  # Qt teardown — the window is closing
            elif getattr(self, "_problems_only", False):
                # v1.5.4 (ROADMAP task 2): the LENS reads the status too — a card that
                # just went red must light up (and a card that recovered must recede)
                # without a rebuild of the sidebar, which no status filter asked for.
                try:
                    self._apply_map_dimming()
                except Exception:  # noqa: BLE001 — the lens is cosmetic on teardown
                    pass

    #: How often the age of every shown status is re-evaluated (ms). Purely a repaint
    #: tick: it never starts a probe round (`StatusChecker` owns rounds) and never
    #: changes a status — it only moves a card from "fresh" to "stale" once the datum
    #: has really aged past `stale_threshold_s()`. The walk is bounded by the map size
    #: and does nothing at all while a node was never checked.
    FRESHNESS_TICK_MS = 30_000

    def _apply_node_freshness(self, node) -> bool:
        """Give ONE card the age of its status (the checker is the source of truth).

        Called right after a result arrives and by the freshness tick. Returns True when
        the card's stale state changed. A missing/never-checked datum leaves the card
        untouched: it has nothing to age (`set_checked_at(0.0)` clears the mark).
        """
        checker = getattr(self, "_status_checker", None)
        if checker is None:
            return False
        try:
            checked_at = checker.last_checked_at(node.data.id)
            return bool(node.set_checked_at(checked_at, checker.stale_threshold_s()))
        except (RuntimeError, AttributeError):
            return False  # Qt teardown / a test double without the method

    def _refresh_status_freshness(self):
        """Re-evaluate the age of every shown status (the freshness tick).

        Refresh NEVER changes a status and NEVER starts a round: it re-reads the
        timestamps the checker already recorded and repaints what has grown old. A
        status that cannot be refreshed (no checker, a headless test) is simply left as
        it is — the map is honest either way, it just says less.

        v1.5.3 (ROADMAP task 1): the SAME tick re-reads the age of the COLLECTED FACTS.
        They are dated in the data itself (`info_collected_at`), so no checker is involved
        and the two families stay independent: this second walk only repaints a plaque
        whose measurement has crossed `ServerNode.INFO_STALE_AFTER_SEC` (a week) — a fresh
        status never hides an old hardware line and the other way round.
        """
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return  # the scene is not created yet / already destroyed
        checker = getattr(self, "_status_checker", None)
        for node in nodes:
            if checker is not None:
                self._apply_node_freshness(node)
            self._apply_node_info_freshness(node)
        # v1.5.4 (ROADMAP task 2): a datum that has just grown STALE is a NEW problem —
        # the chip re-counts and, while the lens is on, the dimming follows (nothing else
        # is touched: a lens is a view, and the counters keep their totals).
        try:
            self._sync_problems_chip()
            if getattr(self, "_problems_only", False):
                self._apply_map_dimming()
        except (AttributeError, RuntimeError):
            pass  # Qt teardown / a window without the v1.5.4 pieces

    def _apply_node_info_freshness(self, node) -> bool:
        """Give ONE card the age of its collected facts (the data is the source of truth).

        Called by the freshness tick. Returns True when the mark changed. A card without a
        date (0.0 — never collected / an old project file) is left untouched and unmarked.
        """
        try:
            return bool(node.set_info_collected_at(
                getattr(node.data, "info_collected_at", 0.0)))
        except (RuntimeError, AttributeError):
            return False  # Qt teardown / a test double without the v1.5.3 hook

    def _freshness_tick(self):
        """The QTimer slot — never raises (a repaint is cosmetic)."""
        try:
            self._refresh_status_freshness()
        except Exception as e:  # noqa: BLE001
            if self.log:
                self.log.warning(f"Status freshness tick failed: {e}")
