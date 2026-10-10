"""`OverlaysMixin` — the floating panels over the canvas and their ONE priority resolver (AGENTS.md §4.1).

Methods only: `MainWindow` stays the facade and the public API is unchanged; the mixin does NOT import the
window module (a cycle) — it duck-types the instance.

Owned here: the floating-panel priority rule (`_sync_overlay_priority()` and the legend's temporary yield),
the map search bar with its state machine, the first-run hint, the active-filter plaque and the placement
of the map collapse diamond (`_position_map_collapse_btn()` with its two pure helpers). The shared helpers
`SNAP_PX` / `_snap_panel()` / `_saved_position()` deliberately STAY on the window — three panels use them.
Mechanism — `DOCUMENTATION.md` §29, §41, §43, §47."""
from PySide6.QtCore import QRect


class OverlaysMixin:
    """The floating panels over the canvas and the ONE priority resolver."""

    #: The inset of the plaque's default (top-left) position — the legend's margin, so
    #: the two panels of the window share one spacing standard.
    FILTER_MARGIN = 12

    #: The inset of the map's collapse button from the VIEWPORT's bottom-right corner.
    #: The viewport already excludes the frame AND the scrollbars (the VIEW's corner would
    #: put the button on top of the sliders), and the extra raise lifts
    #: it out of the very corner so the two collapse buttons sit at different levels.
    COLLAPSE_BTN_MARGIN = 8
    COLLAPSE_BTN_RAISE = 1

    # ── the floating-panel priority rule ──

    def _sync_overlay_priority(self):
        """Resolve the floating panels from the live geometry (v1.5rc4, task 7)."""
        self._sync_legend_suppression()
        # The minimap's own rule lives with its placement (`_position_minimap`), and the
        # diamond is placed by `_position_map_collapse_btn` — both are re-run here so ONE
        # call site keeps the panels consistent after any geometry change.
        self._position_minimap()
        # v1.5.4 (ROADMAP task 3): the filter plaque yields to an OPEN search bar (it steps
        # below it) — its placement is part of the same ONE resolution, so the bar opening
        # and closing move it without a second call site.
        self._position_filter_plaque()
        self._position_map_collapse_btn()

    def _sync_legend_suppression(self) -> bool:
        """Temporarily hide the legend while the first-run hint is on screen.

        Returns True while the legend is suppressed. The panel is hidden but its state
        (`_legend_enabled`, the config) is untouched; as soon as the hint goes away — the
        first server arrives, or a project is opened — the legend comes back exactly as
        the user left it.
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return False
        overlay = getattr(self, "empty_state", None)
        hint_up = bool(overlay is not None and overlay.is_state_visible())
        suppressed = bool(getattr(self, "_legend_suppressed", False))
        try:
            if hint_up and not suppressed and bool(getattr(self, "_legend_enabled", True)):
                legend.hide()
                self._legend_suppressed = True
                return True
            if not hint_up and suppressed:
                self._legend_suppressed = False
                if bool(getattr(self, "_legend_enabled", True)):
                    legend.setVisible(True)
                    self._position_legend()
        except RuntimeError:
            pass  # Qt teardown — the panel is already destroyed
        return bool(getattr(self, "_legend_suppressed", False))

    def legend_suppressed(self) -> bool:
        """True while the legend is hidden BY the priority rule (not by the user)."""
        return bool(getattr(self, "_legend_suppressed", False))

    # ── the active-filter plaque ──

    def _setup_filter_plaque(self):
        """Create the active-filter plaque (a child of the view) and wire its two signals.

        The widget owns no filter logic: it reports a click per row (`clear_requested`)
        and the window clears that ONE filter. Its placement hangs off `view.resized`
        like the other floating panels, and it starts hidden (no filter is active yet).
        """
        try:
            from ui.filter_plaque import FilterPlaque
        except ImportError:  # flat launch from the project root
            from filter_plaque import FilterPlaque

        self.filter_plaque = FilterPlaque(self.view)
        self.filter_plaque.clear_requested.connect(self._on_filter_clear)
        self.view.resized.connect(self._position_filter_plaque)
        self._position_filter_plaque()
        self._sync_filter_plaque()

    def _sync_filter_plaque(self) -> bool:
        """Show/hide and re-text the plaque from the LIVE filter state. True — visible.

        The window is the ONE owner of the filter state (the search query, the tag pick,
        the status filter and the lens), so the plaque is a pure projection of it: it
        appears exactly while at least one filter is active and disappears with the last
        × — which is what makes "a forgotten filter" impossible to mistake for deleted
        servers. Idempotent and cheap: the widget compares the RAW state and a repeated
        push costs one dict comparison.
        """
        plaque = getattr(self, "filter_plaque", None)
        if plaque is None:
            return False
        query = (getattr(self, "_map_search_query", "") or "").strip()
        try:
            changed = plaque.set_state(search=query, tag=self._active_tag_filter(),
                                       status=getattr(self, "_status_filter", "") or "",
                                       problems=bool(getattr(self, "_problems_only", False)))
            if plaque.is_empty():
                if plaque.isVisible():
                    plaque.hide()
                return False
            if not plaque.isVisible():
                plaque.setVisible(True)
                changed = True
            if changed:
                self._position_filter_plaque()
                plaque.raise_()
        except RuntimeError:
            return False  # Qt teardown — the panel is already destroyed
        return True

    def _position_filter_plaque(self):
        """Place the plaque in the TOP-LEFT corner, clear of the open search bar.

        The top-left is the one corner the other floating panels leave free (the search
        bar is top-centre, the minimap top-right, the legend bottom-left, the collapse
        diamond bottom-right). On a narrow window the centred search bar reaches into it,
        so the plaque STEPS BELOW the bar instead of fighting it for the pixels — the same
        "yield, never cover" idea the v1.5rc4 priority rule uses.
        """
        plaque = getattr(self, "filter_plaque", None)
        view = getattr(self, "view", None)
        if plaque is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            x = self.FILTER_MARGIN
            y = self.FILTER_MARGIN
            bar = getattr(self, "map_search", None)
            if bar is not None and bar.isVisible():
                geometry = bar.geometry()
                if geometry.left() < x + plaque.width() + self.FILTER_MARGIN:
                    y = geometry.bottom() + self.FILTER_MARGIN
            x = min(max(int(x), 0), max(w - plaque.width(), 0))
            y = min(max(int(y), 0), max(h - plaque.height(), 0))
            plaque.move(int(x), int(y))
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _on_filter_clear(self, kind: str):
        """The × of one plaque row: clear THAT filter and nothing else (v1.5.4).

        Every branch reuses the ordinary path of its own filter (the search panel's close,
        the tag combo, the status counter's toggle, the lens setter), so a plaque click
        behaves exactly like the gesture that turned the filter on — no second semantics
        to keep in sync.
        """
        kind = str(kind or "")
        if kind == "search":
            self._close_map_search()
        elif kind == "tag":
            combo = getattr(self, "tag_filter", None)
            if combo is not None:
                try:
                    combo.setCurrentIndex(0)   # "All tags" → _on_tag_filter_changed
                except (RuntimeError, AttributeError):
                    pass  # Qt teardown / a panel without the combo
        elif kind == "status":
            self._on_status_filter_clicked(getattr(self, "_status_filter", ""))
        elif kind == "problems":
            self._set_problems_only(False)

    # ── the map search bar ──

    def _setup_map_search(self):
        """v0.9.8: create a floating search bar over the canvas + the state.

        The panel — a child widget of the MapView (floats over the viewport, out of the scene's way).
        The Ctrl+F hotkey provides the "View -> Search map..." item (a QAction shortcut) —
        a separate QShortcut with the same sequence would create an ambiguous shortcut.
        The search logic lives here: match/dim/center — a single path.
        """
        try:
            from ui.map_search_bar import MapSearchBar
        except ImportError:  # flat launch from the project root
            from map_search_bar import MapSearchBar

        # The state (empty until the first query)
        self._map_search_query = ""
        self._map_search_matches = []
        self._map_search_index = -1

        self.map_search = MapSearchBar(self.view)
        self.map_search.query_changed.connect(self._on_map_search_query)
        self.map_search.next_requested.connect(lambda: self._map_search_step(+1))
        self.map_search.prev_requested.connect(lambda: self._map_search_step(-1))
        self.map_search.close_requested.connect(self._close_map_search)
        # Reposition the panel on a window resize (it is outside the layout, a child of the view).
        # v0.9.9.1: the MapView.resized signal was added — before, the connect fell into
        # an AttributeError and was silently swallowed by try/except (the panel kept its old x).
        self.view.resized.connect(self._position_map_search_bar)

    def _toggle_map_search(self):
        """v0.9.8: Ctrl+F / "View -> Search map..." — open or close the panel."""
        if self.map_search.isVisible():
            self._close_map_search()
        else:
            self._open_map_search()

    def _open_map_search(self):
        """v0.9.8: show the panel, place it at the top center of the viewport, focus the input.

        If the field still holds a query (closed with Esc, the text is kept — as in a browser),
        re-activate it: recompute the matches/counter against the current scene.
        Otherwise Enter would point at the cleared self._map_search_query while the panel
        showed the old text and counter — a desync.
        """
        self.map_search.show()
        self.map_search.raise_()
        self._position_map_search_bar()
        # v1.4.2: the minimap steps BELOW the search bar; v1.5rc4 (task 7): the ONE place
        # that resolves the floating panels also moves the collapse diamond out of the way.
        self._sync_overlay_priority()
        if self.map_search.query.strip():
            self._on_map_search_query(self.map_search.query)
        self.map_search.focus_input()
        self.statusBar().showMessage(self.t("hint.map_search"))

    def _close_map_search(self):
        """v0.9.8: close the panel and clear the search state (dimming + frames).

        The tag filter stays active — _apply_map_dimming will recompute
        the dimming by it (the query is already cleared above).
        """
        if getattr(self, "map_search", None) is not None:
            self.map_search.hide()
        # v1.4.2: the minimap returns to the top-right corner; v1.5rc4 (task 7): the same
        # ONE resolver re-places the diamond now that the bar is gone.
        self._sync_overlay_priority()
        self._map_search_query = ""
        self._map_search_matches = []
        self._map_search_index = -1
        self._apply_map_dimming()
        try:
            self._show_ready_status()
        except Exception:  # noqa: BLE001 — the status bar is cosmetic on teardown
            pass

    def _position_map_search_bar(self):
        """v0.9.8: the panel at the top center of the viewport (a child of the view, outside the layout)."""
        bar = getattr(self, "map_search", None)
        if bar is None or not bar.isVisible():
            return
        vp = self.view.viewport()
        w = min(bar.PREFERRED_WIDTH, max(vp.width() - 16, bar.MIN_WIDTH))
        x = max(8, (vp.width() - w) // 2)
        h = max(bar.sizeHint().height(), 30)
        bar.setGeometry(int(x), 10, int(w), int(h))

    def _map_search_nodes(self, query: str):
        """v0.9.8: nodes matching the query (alias/host/ip/comment — as in the sidebar)."""
        q = (query or "").strip().lower()
        if not q:
            return []
        try:
            nodes = list(self.scene.nodes())
        except (AttributeError, RuntimeError):
            return []
        out = []
        for node in nodes:
            d = node.data
            haystack = " ".join([d.alias, d.host, d.ip, d.comment]).lower()
            if q in haystack:
                out.append(node)
        return out

    def _on_map_search_query(self, query: str):
        """v0.9.8: the query text changed — recompute the matches and the dimming.

        The counter points at the FIRST result (the browser-search pattern);
        centering/selection — only on Enter (ROADMAP #2).
        """
        self._map_search_query = query or ""
        matches = self._map_search_nodes(query)
        self._map_search_matches = matches
        self._map_search_index = 0 if matches else -1
        self._apply_map_dimming()
        self.map_search.set_count(self._map_search_index + 1, len(matches))

    def _map_search_step(self, direction: int):
        """v0.9.8: Enter/Shift+Enter — stepping through the results (with wrapping).

        Selecting the node (the sidebar row follows the selection via _sync_selection_state),
        the view.centerOn centering and the reveal_flash flash frame — the same ready path
        as the v0.9.6 "Show on map" (the set_status pulse pattern). The matches
        are recomputed fresh: nodes may have been added/removed since the query.
        """
        matches = self._map_search_nodes(self._map_search_query)
        if not matches:
            q = (self._map_search_query or "").strip()
            try:
                self.statusBar().showMessage(self.t("status.no_matches", query=q))
            except Exception:  # noqa: BLE001 — a formatting failure is not critical
                self.statusBar().showMessage(f"No matches: {q}")
            return
        n = len(matches)
        base = self._map_search_index if 0 <= self._map_search_index < n else -1
        idx = (base + direction) % n
        self._map_search_matches = matches
        self._map_search_index = idx
        node = matches[idx]
        self._select_node(node, center=True)
        flash = getattr(node, "reveal_flash", None)
        if callable(flash):
            try:
                flash()
            except Exception:  # noqa: BLE001 — the accent is cosmetic; the navigation already worked
                pass
        self.map_search.set_count(idx + 1, n)

    def _close_map_search_if_open(self):
        """v0.9.8: close the search on a project switch (an old query about new nodes is stale)."""
        bar = getattr(self, "map_search", None)
        if bar is not None and bar.isVisible():
            self._close_map_search()

    # ── the first-run hint ──

    def _connect_hint_text(self) -> str:
        """The "how do I draw a connection?" sentence (v1.6.8, ROADMAP task 2).

        The connection gesture shipped in v0.7 and nobody found it, so the FIRST screen
        names it AND the "Add Connection" action carries the same words as its tooltip.
        ONE composer, ONE i18n key (`empty.state.connect_hint`, whose `{add_connection}`
        placeholder is filled with the action's own live label — the v1.4.5 rule): the
        hint and the tooltip are literally the same function, so they cannot drift.
        A stripped build without `ui/empty_state.py` answers "" and the tooltip stays empty.
        """
        try:
            from ui.empty_state import connect_hint_text
        except ImportError:  # flat launch from the project root
            try:
                from empty_state import connect_hint_text
            except ImportError:
                return ""
        try:
            return connect_hint_text()
        except Exception:  # noqa: BLE001 — a hint must never break the menu construction
            return ""

    def _setup_empty_state(self):
        """Create the hint card over the canvas + its ONE button (a child of the view).

        The card itself is mouse-transparent (a click reaches the map — panning, the
        rubber band and the map context menu keep working behind the hint); the button
        is a SIBLING widget, because Qt's `WA_TransparentForMouseEvents` covers the
        children of the widget it is set on.
        """
        try:
            from ui.empty_state import EmptyStateOverlay
        except ImportError:  # flat launch from the project root
            from empty_state import EmptyStateOverlay

        self.empty_state = EmptyStateOverlay(self.view)
        self.empty_state.add_server_requested.connect(self._add_server)
        # v1.9.7 (ROADMAP task 6): the TXT import is a DOOR of the first screen now. The widget
        # only emits; the file dialog and the import belong to the window, and the door is the
        # ORDINARY File → Import Servers from TXT… path, so every downstream rule is shared.
        try:
            self.empty_state.import_requested.connect(self._import_servers_from_txt)
        except (RuntimeError, AttributeError):
            pass  # a stripped build without the signal — the other doors still work
        # v1.5.6 (ROADMAP task 2): the THIRD door of the first screen — an existing
        # project file. The widget only emits; the dialog and the load belong to the
        # window, and the door is the ORDINARY project-open path (the same one File → Open
        # and a dropped project use), so every downstream rule is shared.
        try:
            self.empty_state.open_map_requested.connect(self._open_project)
        except (RuntimeError, AttributeError):
            pass  # a stripped build without the signal — the other two doors still work
        # v1.5rc3 (ROADMAP task 1): the second button — the demo map. The SAME method the
        # Help item calls, so the two entry points cannot diverge (and both go through
        # the ordinary project load path).
        try:
            self.empty_state.example_requested.connect(self._open_example_map)
        except (RuntimeError, AttributeError):
            pass  # a stripped build without the signal — the title/import line still work
        # Reposition on every view resize / splitter drag (the minimap pattern).
        self.view.resized.connect(self._position_empty_state)
        self._empty_state_visible = None   # unknown until the first sync
        self._position_empty_state()
        self._sync_empty_state()

    def _sync_empty_state(self):
        """Show the hint while the map holds NO server; hide it from the first one on.

        Bound to the SCENE's node count (not to the sidebar's filtered rows): the hint
        explains the map, not a filter. Called from `_update_counts_label()` — the one
        place every composition change already passes through (add, remove, batch
        delete, import, project load, undo/redo).
        """
        overlay = getattr(self, "empty_state", None)
        if overlay is None:
            return
        try:
            empty = len(list(self.scene.nodes())) == 0
        except (AttributeError, RuntimeError):
            return  # the scene is not created yet / already destroyed
        if empty == getattr(self, "_empty_state_visible", None):
            return  # nothing changed — the hint is already in the right state
        self._empty_state_visible = empty
        try:
            overlay.set_state_visible(empty)
        except RuntimeError:
            return  # Qt teardown — the widget is already destroyed
        if empty:
            self._position_empty_state()
        # v1.5rc4 (ROADMAP task 7): the first-run hint is the reason the legend yields —
        # its appearance/disappearance is exactly where the priority must be re-resolved.
        self._sync_overlay_priority()

    def _position_empty_state(self):
        """Place the hint (and its button) in the middle of the view — a child, not a layout."""
        overlay = getattr(self, "empty_state", None)
        view = getattr(self, "view", None)
        if overlay is None or view is None:
            return
        try:
            w, h = view.width(), view.height()
            if w <= 0 or h <= 0:
                return
            overlay.place(w, h)
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    # ── the map collapse diamond ──

    def _position_map_collapse_btn(self):
        """v1.2.4.1 (task 2): the map collapse button — the right BOTTOM corner of the MapView.

        The bottom corner, never the top (the diamond reads "at the bottom" in both
        states); the top is reserved for the minimap. Repositioned on resizeEvent
        (the MapView.resized signal: a window resize, a splitter-handle drag,
        a "Terminals" dock size change) and whenever a scrollbar appears or disappears
        (their `rangeChanged` — the viewPORT is what the corner is measured against).

        v1.5rc4 (ROADMAP task 7): the third rule of the floating-panel priority — the
        diamond is NEVER covered by a panel. The corner is where the legend (bottom-left,
        draggable) and the minimap (right, draggable, free position) can land on a narrow
        window; the button therefore probes a few candidate spots around the panel that
        covers the corner and takes the first one that is free. Nothing else moves: the
        USER's panel position always wins over the window's own button.

        v1.5.6 (customer request): the corner is the VIEWPORT's, not the view's. The view's
        own rect INCLUDES the frame and the scrollbars, which would put the button ON
        TOP of the sliders; `viewport().geometry()` excludes both. The extra
        `COLLAPSE_BTN_RAISE` lifts it out of the very corner, so the two collapse buttons
        (the sidebar's bottom row and this overlay) sit at visibly different levels.
        """
        btn = getattr(self, "_map_collapse_btn", None)
        view = getattr(self, "view", None)
        if btn is None or view is None:
            return
        try:
            vp = view.viewport()
            corner = vp.geometry()          # the view's coordinates WITHOUT frame/scrollbars
            w, h = corner.width(), corner.height()
            if w <= 0 or h <= 0:
                return
            bw = max(btn.sizeHint().width(), 24)
            bh = max(btn.sizeHint().height(), 24)
            x = max(4, corner.right() + 1 - bw - self.COLLAPSE_BTN_MARGIN)
            y = max(4, corner.bottom() + 1 - bh - self.COLLAPSE_BTN_MARGIN
                    - self.COLLAPSE_BTN_RAISE)
            panels = self._overlay_panel_rects(view)
            if panels:
                for candidate in self._collapse_btn_candidates(x, y, bw, bh, w, h, panels):
                    if not any(candidate.intersects(rect) for rect in panels):
                        x, y = candidate.x(), candidate.y()
                        break
            btn.move(int(x), int(y))
        except RuntimeError:
            pass  # Qt teardown — the widget is already destroyed

    def _overlay_panel_rects(self, view) -> list:
        """The live rectangles of the VISIBLE floating panels (v1.5rc4, task 7).

        The view's own coordinates (every panel is a child of `MapView`), in the order the
        priority rule cares about: the first-run hint first (it is the temporary one), then
        the search bar, the minimap, the legend — the bookmarks panel since v1.6.7 — and the
        filter plaque (a panel that only exists while a filter dims the map). A panel that is
        hidden — including the legend suppressed by the priority rule itself — contributes
        nothing.
        """
        rects = []
        for name in ("empty_state", "map_search", "minimap", "legend", "bookmark_panel",
                     "filter_plaque"):
            panel = getattr(self, name, None)
            if panel is None:
                continue
            try:
                if panel.isVisible() and panel.width() > 0 and panel.height() > 0:
                    rects.append(QRect(panel.geometry()))
            except (RuntimeError, AttributeError):
                continue
        return rects

    @staticmethod
    def _collapse_btn_candidates(x, y, bw, bh, view_w, view_h, panels) -> list:
        """The candidate spots for the collapse diamond, nearest-to-the-corner first.

        The default corner, then the free space LEFT of the panel covering it, then ABOVE
        it, then above-left. Bounded on purpose: a button that chases the panels around a
        tiny window is worse than a button that stays in its corner.
        """
        candidates = [QRect(int(x), int(y), int(bw), int(bh))]
        for rect in panels:
            if not rect.intersects(candidates[0]):
                continue
            candidates.append(QRect(int(rect.left() - bw - 8), int(y), int(bw), int(bh)))
            candidates.append(QRect(int(x), int(rect.top() - bh - 8), int(bw), int(bh)))
            candidates.append(QRect(int(rect.left() - bw - 8), int(rect.top() - bh - 8),
                                    int(bw), int(bh)))
        return [c for c in candidates
                if c.left() >= 0 and c.top() >= 0
                and c.right() <= max(int(view_w), 1) and c.bottom() <= max(int(view_h), 1)]
