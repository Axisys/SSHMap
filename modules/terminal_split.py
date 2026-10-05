# -*- coding: utf-8 -*-
"""The SESSION SPLIT of a terminal container — ONE controller, owned by ONE session (AGENTS.md §4.3).

A container's session area is the vertical `QSplitter [session_tabs | split_host]` and the host may
hold a SECOND full session of the SAME node. This module owns the layout, the ratio, the pixel floor
(`SPLIT_MIN_ROWS` built from the live cell metrics), the open/close/MOVE transitions, the action
mirror and the persistence payload, so BOTH containers — the standalone window and the dock — build
the same construct instead of one of them keeping the furniture on the window. The mechanism, the
floor arithmetic and the owner rule are `DOCUMENTATION.md` §14g; the contract is `AGENTS.md` §4.3.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSplitter, QPushButton, QVBoxLayout, QWidget


def get_translator():
    """Safe i18n helper — the shared lazy cached translator of the terminal family."""
    try:
        from i18n import t as _func
    except Exception:  # noqa: BLE001 — a build without i18n keeps the code, not a crash
        return lambda k, **kw: f"[{k}]"
    return lambda key, **kwargs: (_func(key, **kwargs) if kwargs else _func(key))


#: The `terminal_mode` values that are SESSION CONTAINERS, declared by the container itself
#: (`CONTAINER_KIND`): the merge and the `"single"` mode walk the registry for the windows only.
CONTAINER_WINDOW = "window"
CONTAINER_DOCK = "dock"

# ── the split state and its geometry ─────────────────────────────────────────
# The ratio is a FRACTION of the height, so a window resize keeps the proportion; the pixel floor is
# derived from the canvas metrics (`SPLIT_MIN_ROWS` rows + the pane's own chrome), never a magic
# number. The two config KEYS and their reader are the terminal family's config surface, declared
# once in `modules/terminal_config.py` and re-exported HERE (the shipped `SP.<name>` surface).
try:
    from .terminal_config import (SPLIT_CONFIG_BOOL, SPLIT_CONFIG_RATIO, SPLIT_RATIO_DEFAULT,
                                  SPLIT_RATIO_MAX, SPLIT_RATIO_MIN, load_split_settings)
except ImportError:  # flat launch from the project root
    from terminal_config import (SPLIT_CONFIG_BOOL, SPLIT_CONFIG_RATIO, SPLIT_RATIO_DEFAULT,
                                 SPLIT_RATIO_MAX, SPLIT_RATIO_MIN, load_split_settings)

SPLIT_MIN_ROWS = 4                               # the floor: 4 rows of the canvas

#: The split surface this module RE-EXPORTS (`ST.<name>` / `SP.<name>` in the shipped suite): the
#: declaration IS the seam, so a name read only by a caller is not a dead import (`AGENTS.md` §4.3).
MODULE_FACADE_SEAMS = (SPLIT_CONFIG_BOOL, SPLIT_CONFIG_RATIO, SPLIT_RATIO_DEFAULT,
                       SPLIT_RATIO_MIN, SPLIT_RATIO_MAX, load_split_settings)


def find_host_hook(widget, name):
    """The duck-typed host hook `name` on `widget`'s PARENT CHAIN (None — nobody answers it).

    The `AGENTS.md` §4.1 rule applied to a container: `modules/*` never imports `ui.main_window`, so
    a container asks its ancestors at call time. The standalone window finds the hook on its parent
    immediately; the dock content sits under `TerminalsDock`, so the walk is what makes ONE hook
    serve both containers. Never raises.
    """
    node = widget
    hops = 0
    while node is not None and hops < 32:
        try:
            fn = getattr(node, name, None)
        except RuntimeError:
            return None
        if callable(fn):
            return fn
        try:
            node = node.parent()
        except (RuntimeError, AttributeError):
            return None
        hops += 1
    return None


class TerminalSplit:
    """The split of ONE container: the host widget, the vertical splitter, the pane and its owner.

    The container INSTANTIATES it (`TerminalSplit(self)`) after its `session_tabs` exists and adds
    `splitter` to its own layout; the shipped attribute surface stays on the container as delegates
    (`split_host`, `_v_splitter`, `_split_on`, `split_pane`, `act_split`, `btn_split`,
    `set_split_enabled()`), which is what keeps the shipped split tests byte for byte true.

    The container answers the duck-typed hooks this class asks for — `add_session(split=True)`,
    `split_server_data(page)`, `split_password(page)`, `register_split_session(page)`,
    `attach_split_pane(pane)` / `detach_split_pane(pane)` and `refresh_bridge()`; a container that
    does not implement one simply gets the no-op (the `AGENTS.md` §4.3 robustness rule).
    """

    def __init__(self, container, persist_toggle: bool = False):
        self.container = container
        self.tabs = container.session_tabs
        #: Does a toggle write the two keys itself? The window persists them in `closeEvent` (the
        #: shipped one-write-per-window rule); the dock, which has no close of its own, writes them
        #: on the gesture — the `ui_cmdlib_collapsed` precedent.
        self.persist_toggle = bool(persist_toggle)

        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # NOT collapsible on either side (the divider can never "lose" a pane) and the floors are
        # applied with `setMinimumHeight` + `setSizes` only — Qt gotcha #13: `setMaximum*` on a
        # splitter member breaks the size accounting after hide/show.
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self.host)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.splitterMoved.connect(self.on_moved)
        # A hidden splitter member costs no geometry — the single-pane look is the default.
        self.host.hide()

        config = load_split_settings()
        self.pane = None            # the SECOND session (None while the split is off)
        self.on = False             # is a pane open at all (the pane survives a tab switch)
        self.owner_page = None      # the session the pane was opened FOR
        self.ratio = config["ratio"]
        self.act = None
        self.btn = None

    # ── the action: ONE source of truth, two views (the `act_split` pattern) ──

    def build_action(self):
        """Create the checkable QAction (`terminal.split`) and the corner BUTTON that mirrors it.

        The window adds the action to its context menu and the button to its tab-bar corner; the
        dock does the same through its own corner. A QPushButton has no `setDefaultAction` in
        PySide6, so the button is wired by hand and the ACTION stays the single source of truth.
        """
        t = get_translator()
        act = QAction(t("terminal.split"), self.container)
        act.setCheckable(True)
        act.setToolTip(t("terminal.split_tooltip"))
        btn = QPushButton(t("terminal.split"))
        btn.setCheckable(True)
        btn.setToolTip(t("terminal.split_tooltip"))
        btn.clicked.connect(self.on_button_clicked)
        act.toggled.connect(self.on_toggled)
        self.act, self.btn = act, btn
        return act, btn

    def retranslate(self):
        """Re-text the action and its button (one label, one tooltip, two views). Never raises."""
        t = get_translator()
        for widget in (self.act, self.btn):
            if widget is None:
                continue
            try:
                widget.setText(t("terminal.split"))
            except RuntimeError:
                continue   # Qt teardown — this view is gone
        self.update_tooltip()

    def update_tooltip(self):
        """The tooltip names the OWNER of the pane — the second channel, no third checkmark.

        A pane belongs to the session it was opened for, and the alias of that session is the one
        fact the checkmark cannot show while the pane is off screen: the sentence gains it whenever a
        pane is open. Reuses the shipped `terminal.split_tooltip` key (no new string).
        """
        t = get_translator()
        text = t("terminal.split_tooltip")
        alias = ""
        if self.pane is not None:
            data = getattr(self.owner_page, "server_data", None)
            alias = str(getattr(data, "alias", "") or "")
        if alias:
            text = f"{text} — {alias}"
        for widget in (self.act, self.btn):
            if widget is None:
                continue
            try:
                widget.setToolTip(text)
            except RuntimeError:
                continue   # Qt teardown — this view is gone

    def on_toggled(self, checked: bool):
        """`act_split.toggled` — the ONE entry point of the toggle."""
        self.set_enabled(checked, persist=self.persist_toggle)

    def on_button_clicked(self, _checked=False):
        """The BUTTON asks the ACTION (one source of truth): the click does not set the state."""
        act, btn = self.act, self.btn
        if act is None or btn is None:
            return
        try:
            act.setChecked(bool(btn.isChecked()))
        except RuntimeError:
            pass   # teardown — the action is gone

    def sync_button(self, checked=None):
        """Keep the corner button in step with the action WITHOUT re-entering the slot."""
        act, btn = self.act, self.btn
        if btn is None:
            return
        try:
            if checked is None:
                checked = bool(act.isChecked()) if act is not None else False
            btn.blockSignals(True)
            btn.setChecked(bool(checked))
            btn.blockSignals(False)
        except RuntimeError:
            pass   # teardown — the button is gone

    def sync_action(self, checked: bool):
        """Show the state on the action (and the button) with the signals BLOCKED (no re-entry)."""
        checked = bool(checked)
        act = self.act
        if act is not None:
            try:
                act.blockSignals(True)
                act.setChecked(checked)
                act.blockSignals(False)
            except RuntimeError:
                pass   # teardown — the action is gone
        self.sync_button(checked)

    # ── the OWNER rule: the split belongs to the ACTIVE session ──────────────

    @property
    def active_page(self):
        """The session the split speaks for — the CURRENT TAB (a pane belongs to its owner).

        Deliberately NOT the focused pane: with the keyboard inside the pane the answer stays the
        session the pane was opened for, so the checkmark does not flip off the moment the user
        clicks into the second shell. Never raises.
        """
        try:
            return self.tabs.currentWidget()
        except RuntimeError:
            return None

    def owns_active(self) -> bool:
        """Is the pane open for the session the container is showing right now?"""
        return self.pane is not None and self.owner_page is self.active_page

    def sync_owner(self):
        """Show the ACTIVE session's ownership in the action — the ONE place that mirrors it.

        Re-read on every tab change and on every focus change (the `_sync_commander()` discipline):
        the signals stay blocked, so switching to a session that does not own the pane unchecks the
        control WITHOUT closing anything — the pane keeps running (it is a session).
        """
        self.sync_action(self.owns_active())
        self.update_tooltip()

    # ── open / close / MOVE ─────────────────────────────────────────────────

    def set_enabled(self, on: bool, persist: bool = False) -> bool:
        """The ONE split switch. Returns True when the requested state was REACHED.

        ON — a pane opens for the ACTIVE session; while a FOREIGN session owns the pane it is MOVED
        (the old pane passes its own `confirm_close()` gate first — a Cancel leaves it where it is,
        and the answer is False). OFF — the pane closes through the same gate; a Cancel keeps it.
        Called from `act_split.toggled` and by the containers' own close paths.
        """
        on = bool(on)
        active = self.active_page
        if on:
            if self.owns_active():
                self.sync_action(True)      # already open for this session — nothing to do
                return True
            if self.pane is not None and not self.close_pane():
                self.sync_action(False)     # the gate was cancelled — the foreign pane stays
                return False
            self.open_pane(active)
            if self.pane is None:
                self.sync_action(False)     # the pane could not be created
                return False
            self.sync_action(True)
        else:
            if self.pane is not None and not self.close_pane():
                self.sync_action(self.owns_active())
                return False
            self.sync_action(False)
        if persist:
            self.persist_state()
        return True

    def open_pane(self, page=None):
        """Create and show the pane for `page` (the active session by default). Idempotent."""
        if self.pane is not None:
            return self.pane
        if page is None:
            page = self.active_page
        data = self._server_data(page)
        password = self._password(page)
        pane = self._container_call("add_session", data, password=password,
                                    initial_command="", split=True)
        if pane is None:
            return None
        self.pane = pane
        self.owner_page = page
        self.on = True              # BEFORE show(): the resize events of the layout arrive first
        try:
            self.host.show()
        except RuntimeError:
            self.pane = None
            return None             # C++ teardown — nothing to show
        self.apply_sizes()
        # The layout of a just-shown pane settles after the event cycle (the page's own
        # singleShot(0) grid sync is the same pattern) — a second pass on the real size.
        try:
            QTimer.singleShot(0, self.apply_sizes)
        except RuntimeError:
            pass                    # teardown race — the immediate pass above already ran
        self._container_call("register_split_session", pane)
        # The container's own half of the transition: the pane's status surface and the keyboard
        # bridge (the window's second status text, the dock's status line).
        self._container_call("attach_split_pane", pane)
        self.update_tooltip()
        return pane

    def close_pane(self) -> bool:
        """Tear the pane down; False — the "ask" gate was cancelled (the pane stays)."""
        self.remember_ratio()
        pane = self.pane
        if pane is None:
            try:
                self.host.hide()
            except RuntimeError:
                pass
            self.on = False
            self.owner_page = None
            return True
        try:
            if not pane.confirm_close():
                return False
        except RuntimeError:
            pass                    # C++ teardown — close without asking (as everywhere else)
        self._container_call("detach_split_pane", pane)
        try:
            pane.shutdown()
        except Exception:  # noqa: BLE001 — teardown robustness
            pass
        self.pane = None
        self.on = False
        self.owner_page = None
        self.reset_floors(pane)
        try:
            self.host.layout().removeWidget(pane)
        except (RuntimeError, AttributeError):
            pass                    # the host was already destroyed (a close race)
        try:
            pane.setParent(None)
            pane.deleteLater()
        except RuntimeError:
            pass                    # teardown race — the page dies with its parent anyway
        try:
            self.host.hide()
        except RuntimeError:
            pass
        self.update_tooltip()
        # The bridge returns to the ACTIVE tab (the pane it pointed at is gone).
        self._container_call("refresh_bridge")
        return True

    # ── the geometry: a FRACTION of the height and a floor built from the metrics ──

    def min_height(self) -> int:
        """The size floor of the pane, in PIXELS — `SPLIT_MIN_ROWS` rows of the LIVE canvas.

        The floor is BUILT, not guessed: the pane's canvas gets a minimum height of
        `SPLIT_MIN_ROWS` rows measured from the live cell metrics (`widget.cell_size`) and the pane's
        own CHROME is measured from the live geometry (`pane.height() - pane.widget.height()`); before
        the first layout the inner tab bar and the layout margins are the fallback. The result is
        returned AND installed as an explicit `minimumHeight` by `apply_sizes()` (an explicit minimum
        overrides `minimumSizeHint` — that is what turns the floor into the splitter's own limit).
        Never raises.
        """
        pane = self.pane
        if pane is None:
            return 0
        row_h = 16
        try:
            row_h = max(1, int(pane.widget.cell_size[1]))
        except (RuntimeError, AttributeError, TypeError, IndexError):
            row_h = 16               # a dying C++ object — a sane default for the single pass
        canvas_floor = int(row_h * SPLIT_MIN_ROWS)
        try:
            pane.widget.setMinimumHeight(canvas_floor)
        except (RuntimeError, AttributeError):
            pass                     # C++ teardown — the splitter floor below is best-effort then
        chrome = 0
        try:
            chrome = int(pane.height()) - int(pane.widget.height())
        except (RuntimeError, TypeError):
            chrome = 0
        if chrome <= 0:
            try:
                bar = pane.tabs.tabBar()
                bar_h = 0 if bar.isHidden() else int(bar.sizeHint().height())
                chrome = bar_h + 16  # + the layout margins and the QTabWidget frame
            except (RuntimeError, AttributeError, TypeError):
                chrome = 0
        return canvas_floor + max(0, chrome)

    def current_ratio(self):
        """The pane's CURRENT share of the splitter height (None — nothing to measure).

        None while the split is OFF or while the host is hidden (its size is 0): a ratio measured on
        a hidden member would be 0 and would OVERWRITE the proportion the user left behind.
        """
        if self.pane is None:
            return None
        try:
            sizes = self.splitter.sizes()
        except RuntimeError:
            return None
        if len(sizes) < 2:
            return None
        total = sum(sizes)
        if total <= 0 or sizes[1] <= 0:
            return None
        return sizes[1] / float(total)

    def remember_ratio(self):
        """Fold the live proportion into `self.ratio` (clamped) — the value the next open uses."""
        ratio = self.current_ratio()
        if ratio is None:
            return None
        self.ratio = max(SPLIT_RATIO_MIN, min(SPLIT_RATIO_MAX, ratio))
        return self.ratio

    def on_moved(self, _pos=None, _index=None):
        """The user dragged the divider — the new proportion becomes THE ratio."""
        self.remember_ratio()

    def apply_sizes(self):
        """The two geometry answers: the pane's FRACTION of the height and both panes' FLOORS.

        Applied on open, on every container resize and after the user drags the divider. A container
        too short for two floors splits evenly instead of producing negative sizes. Never raises.
        """
        if self.pane is None:
            return
        try:
            total = self.splitter.height() - self.splitter.handleWidth()
        except RuntimeError:
            return
        if total <= 0:
            return                   # not laid out yet (the deferred pass / the resize will do it)
        floor = self.min_height()
        bottom = int(round(total * self.ratio))
        if total > 2 * floor:
            bottom = max(floor, min(bottom, total - floor))
        else:
            bottom = max(1, total // 2)   # too short for two floors — split evenly
        top = max(1, total - bottom)
        try:
            self.host.setMinimumHeight(floor)
            self.tabs.setMinimumHeight(floor)
            self.splitter.setSizes([top, bottom])
        except RuntimeError:
            pass                     # C++ teardown — nothing to size

    def reset_floors(self, pane=None):
        """Drop the floors of `apply_sizes` with the pane (the single-pane window minimum returns).

        `pane` is passed explicitly by `close_pane` (there it is already detached from `self.pane`).
        """
        target = pane if pane is not None else self.pane
        try:
            if target is not None:
                target.widget.setMinimumHeight(0)
        except (RuntimeError, AttributeError):
            pass                     # C++ teardown — nothing to reset
        try:
            self.host.setMinimumHeight(0)
            self.tabs.setMinimumHeight(0)
        except RuntimeError:
            pass                     # C++ teardown — nothing to reset

    # ── the persistence payload ─────────────────────────────────────────────

    def state_payload(self) -> dict:
        """The two CONFIG keys of the split, merged into the container's own write."""
        self.remember_ratio()
        return {
            SPLIT_CONFIG_BOOL: bool(self.on and self.pane is not None),
            SPLIT_CONFIG_RATIO: round(float(self.ratio), 4),
        }

    def persist_state(self) -> bool:
        """Write the two keys through the ordinary merge-write (the dock's own close). Never raises."""
        try:
            from i18n import save_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the session state
            return False
        try:
            return bool(save_config(self.state_payload()))
        except Exception:  # noqa: BLE001 — a read-only HOME is not worth an error dialog
            return False

    # ── the container hooks (duck-typed, never raising) ─────────────────────

    def _container_call(self, name, *args, **kwargs):
        """Call ONE container hook; a missing hook or a dead object answers None.

        The name is tried AS GIVEN and then with a leading underscore — a container may keep its
        half of the transition private (`_register_split_session`, `_attach_split_pane`) exactly as
        the shipped window did, and the controller must not care which spelling it chose.
        """
        fn = getattr(self.container, name, None)
        if not callable(fn):
            fn = getattr(self.container, "_" + name, None)
        if not callable(fn):
            return None
        try:
            return fn(*args, **kwargs)
        except (RuntimeError, AttributeError):
            return None
        except Exception:  # noqa: BLE001 — one hook must not break the transition
            return None

    def _server_data(self, page):
        """The node of the pane — the OWNER session's data (fallback: the page's own)."""
        return self._hook_value("split_server_data", page) or getattr(page, "server_data", None)

    def _password(self, page):
        """The credentials of the pane — the SAME node and the SAME password as its session."""
        return self._hook_value("split_password", page) or ""

    def _hook_value(self, name, *args):
        """The value of ONE container hook (the name, then the underscore spelling)."""
        for candidate in (name, "_" + name):
            fn = getattr(self.container, candidate, None)
            if not callable(fn):
                continue
            try:
                return fn(*args)
            except (RuntimeError, AttributeError):
                continue
        return None


def container_windows(sessions, kind=CONTAINER_WINDOW):
    """The DISTINCT live containers of `kind` behind a session registry, in creation order.

    The registry holds SESSIONS (§4.3): the host of a page is its container, a pane shares its
    container with its owner, and a container without the declared `CONTAINER_KIND` (a foreign fake,
    a test double) is skipped rather than guessed at. Dead C++ objects are filtered. Never raises.
    """
    out, seen = [], set()
    for session in list(sessions or []):
        try:
            host = getattr(session, "_host_window", None)
            if host is None or id(host) in seen:
                continue
            if getattr(host, "CONTAINER_KIND", None) != kind:
                continue
            host.windowTitle()      # alive check (the C++ object is not removed)
        except RuntimeError:
            continue
        seen.add(id(host))
        out.append(host)
    return out
