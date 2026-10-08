# -*- coding: utf-8 -*-
"""`TerminalSessionPage` — an SSH session as a reusable widget (AGENTS.md §4.3; DOCUMENTATION.md §14b).

The whole session — terminal thread, pyte screen, canvas, SFTP tab and the command history — moved into
a QWidget that does not know about `QMainWindow`: the terminal window and the dock are thin containers
around it, and a split pane is a second page of the same class.

ALL teardown lives in the ONE idempotent `shutdown()`: the PTY debounce timer stops FIRST (a
`resize_pty` into a dead channel), the SFTP worker is stopped BEFORE the terminal thread (it depends on
that transport, and a worker outliving its budget goes to the orphan registry), then the thread's
signals are unbound and `stop()` + `wait(1500)` runs — a thread that outlives the wait goes to
`_orphan_threads` (a live QThread without a QObject parent must not be left to GC). A `RuntimeError` on
a C++ object never blocks the close. The host learns everything through `status_message` / `progress_*`, and every status write goes through ONE method (`_set_status_text`, `session_status` + the bridge), so the HOST is the single status surface and a split pane's state is its second text. Seams: the thread class and `QMessageBox` are fetched from `ssh_terminal` at call time."""

import time

from PySide6.QtCore import Qt, QEvent, QRectF, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget

try:
    from .terminal_screen import SCROLL_MODE_PIN, TerminalScreen
except ImportError:
    from modules.terminal_screen import SCROLL_MODE_PIN, TerminalScreen

try:
    from .terminal_widget import TerminalWidget
except ImportError:
    from modules.terminal_widget import TerminalWidget

try:
    from .sftp_worker import OP_KINDS, SftpWorker, register_orphan_sftp_worker
except ImportError:
    from modules.sftp_worker import OP_KINDS, SftpWorker, register_orphan_sftp_worker

try:
    from .sftp_tab import SftpTab, format_size, name_refusal_text as sftp_name_refusal_text
except ImportError:
    from modules.sftp_tab import (SftpTab, format_size,
                                  name_refusal_text as sftp_name_refusal_text)

try:  # v1.5.7 (ROADMAP task 1): the per-server COMMAND history (the third tab)
    from .command_history import CommandHistoryPanel, CommandHistoryStore, history_key
except ImportError:
    from modules.command_history import (CommandHistoryPanel, CommandHistoryStore,
                                         history_key)

try:  # v1.9: the production-tag guard of a multi-line paste (the page owns the node's tags)
    from .production_guard import VERB_PASTE, confirm as guard_confirm, guard_tag, node_tags
except ImportError:
    from production_guard import (VERB_PASTE, confirm as guard_confirm, guard_tag,
                                  node_tags)

try:  # v1.2.5: the central theme (status labels — ui/theme.py)
    from ..ui import theme
except ImportError:
    from ui import theme

try:  # v1.4.3 (ROADMAP task 4): the ONE QSS registry
    from ..ui import theme_qss
except ImportError:
    try:
        from ui import theme_qss
    except ImportError:  # flat layout: the ui/ directory itself is on sys.path
        theme_qss = None

# The page's CLUSTERS (the facade over the mixins): the Files-widget handover and the two bridges —
# the SFTP task family and the OSC 7 follow. A mixin resolves a facade global at call time
# (`host_attr`, `MODULE_FACADE_SEAMS` below) and never imports this module. The OSC 7 constants and
# its two PURE readers come back with the mixin (the shipped `TP.parse_osc7` / `TP.CWD_HOOK_COMMAND`).
try:
    from .terminal_files_panel import TerminalFilesPanelMixin
    from .terminal_page_cwd import (CWD_HOOK_COMMAND, FOLLOW_CWD_CONFIG_KEY, TerminalPageCwdMixin,
                                    osc7_report_end, parse_osc7)
    from .terminal_page_sftp import TerminalPageSftpMixin
except ImportError:  # flat launch from the project root
    from terminal_files_panel import TerminalFilesPanelMixin
    from terminal_page_cwd import (CWD_HOOK_COMMAND, FOLLOW_CWD_CONFIG_KEY, TerminalPageCwdMixin,
                                   osc7_report_end, parse_osc7)
    from terminal_page_sftp import TerminalPageSftpMixin


def _st_module():
    """The ssh_terminal module at call time (a test seam for attribute substitution).

    Lazy import: terminal_page does not import ssh_terminal at module level
    (SSHTerminalWindow imports THIS module — a direct import would create a cycle
    when starting from terminal_page).
    """
    try:
        from . import ssh_terminal as _st
    except ImportError:
        import ssh_terminal as _st
    return _st


def get_translator():
    """Safe i18n helper — returns cached translator or fallback (as in ssh_terminal)."""
    mod = _st_module()
    return mod.get_translator()


def _log():
    """The app logger (lazy — the command_history / terminal_widget pattern).

    v1.5.7: the output path uses it for a FEED FAILURE — a swallowed emulator error would otherwise
    cost the repaint silently, and silence is what made the symptom unguessable from outside.
    """
    try:
        from modules.logger import get_logger as _gl
        return _gl("modules.terminal_page")
    except Exception:
        return None


# ── v1.3.3.4 (ROADMAP task 6): the transfer rate / ETA — the detachable task 7 of
# v1.3.3.2, which its own changelog handed to this version. Two pure helpers ARE the
# whole computation: the formatting of a duration and a sliding-window meter fed by
# the progress signals of the SFTP worker (the sftp.progress line itself is unchanged
# — the rate/ETA is appended to it, so a broken/absent measurement is invisible).

# ── the Ctrl+wheel font zoom ───────────────────────
# The GESTURE belongs to the canvas (`TerminalWidget.wheelEvent`), the CONSEQUENCE to the page: the PTY
# grid must follow the new cell metrics at once, the new size is written into the SAME
# `terminal_font_size` key the settings hub owns — DEBOUNCED, because a wheel is a stream of events and
# the §4.2 `CmdEditTextNote` rule is one write per gesture — and the status line says which size is in force.
FONT_SIZE_CONFIG_KEY = "terminal_font_size"
#: The debounce of the write (the `COMMAND_WIDTH_SAVE_DEBOUNCE_MS` / `CmdEditTextNote` value).
FONT_SIZE_SAVE_DEBOUNCE_MS = 600


# ── the ACTIVITY mark of an inactive session ─────────────────────────────────
# A session off screen keeps producing output; the mark says "there is new output here"
# without touching the session's own state and clears when the tab is focused. The RULE
# lives once on the page (`note_output()`), the RENDERING with the tab strip, shared by
# both containers. The mark is a SHAPE (a filled dot) in the STRONG ACCENT role.

#: The size of the mark (px) — the fixed icon slot of every tab title.
ACTIVITY_ICON_PX = 10

#: `(on, tone)` → QIcon. A pixmap is a VALUE (§4.6): the key carries the theme tone, so a
#: theme switch repaints the mark instead of keeping the old colour.
_activity_icon_cache = {}


def activity_tab_icon(on: bool) -> QIcon:
    """The tab icon of one session: the mark (a filled dot) or the transparent fixed slot.

    An UNMARKED tab gets a fully transparent pixmap of the SAME size — the icon column exists
    on every tab, which is what keeps the width of a tab from changing when output arrives.
    Never raises: a mark is cosmetic.
    """
    tone = str(getattr(theme, "ACCENT_STRONG", "") or getattr(theme, "accent_strong", ""))
    key = (bool(on), tone)
    icon = _activity_icon_cache.get(key)
    if icon is not None:
        return icon
    try:
        pixmap = QPixmap(ACTIVITY_ICON_PX, ACTIVITY_ICON_PX)
        pixmap.fill(Qt.GlobalColor.transparent)
        if on:
            color = QColor(tone)
            painter = QPainter(pixmap)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                inset = ACTIVITY_ICON_PX * 0.12
                painter.drawEllipse(QRectF(inset, inset,
                                           ACTIVITY_ICON_PX - 2 * inset,
                                           ACTIVITY_ICON_PX - 2 * inset))
            finally:
                painter.end()
        icon = QIcon(pixmap)
    except Exception:  # noqa: BLE001 — a mark is cosmetic: it may never break a container
        icon = QIcon()
    _activity_icon_cache[key] = icon
    return icon


def session_tab_tooltip(page, t) -> str:
    """The tab tooltip of ONE session — the activity sentence plus the REMOTE title.

    The tooltip is the shipped SECOND channel of the activity mark (marked → "new output", otherwise
    "close session"), and v1.7.2 adds the title the remote program set over `OSC 0`/`OSC 2` as its
    own line: the tab TEXT stays the node alias, so this is where "which of my eight shells is this?"
    is answered. A page without a remote title (or without the property) gets the shipped sentence
    alone. Never raises.
    """
    head = t("terminal.tab_new_output") if getattr(page, "has_activity", False) \
        else t("terminal.tab_close_tooltip")
    try:
        remote = str(getattr(page, "remote_title", "") or "").strip()
    except RuntimeError:
        remote = ""      # Qt teardown — the page is already gone
    if not remote:
        return head
    return f"{head}\n{t('terminal.tab_remote_title', title=remote)}"


def render_session_activity(tabs, page, t) -> bool:
    """Draw (or clear) the activity mark + the tooltip of ONE session's tab. Never raises.

    `tabs` is a container's QTabWidget, `page` a `TerminalSessionPage`, `t` the translator.
    A page without a tab (the SPLIT PANE) answers False — it has no tab strip to mark, and the
    amber frame of the pane is the multi-input's own channel, not this one's.

    The tooltip is the mark's SECOND channel: while marked it says what the dot means, an
    unmarked tab carries the ordinary "close session" text back, and a remote title travels on
    its own line (`session_tab_tooltip()`). Re-applying is idempotent, so the same helper serves
    the first paint, the clear-on-focus, a language switch, a theme switch and a title change.
    """
    try:
        index = tabs.indexOf(page)
        if index < 0:
            return False
        on = bool(getattr(page, "has_activity", False))
        tabs.setTabIcon(index, activity_tab_icon(on))
        tabs.setTabToolTip(index, session_tab_tooltip(page, t))
        return True
    except RuntimeError:
        return False   # Qt teardown — the tab strip is already gone


def refresh_session_activity(container) -> int:
    """Re-render the activity mark of EVERY tab of a container (a language/theme switch).

    The container is duck-typed by `session_tabs` (the `modules/multi_input.py` rule), so the
    terminal window and the dock share this one walk. Returns how many tabs were re-rendered.
    """
    try:
        tabs = container.session_tabs
        count = int(tabs.count())
    except (AttributeError, RuntimeError, TypeError):
        return 0
    done = 0
    for i in range(count):
        try:
            page = tabs.widget(i)
        except RuntimeError:
            break   # Qt teardown mid-walk
        if page is not None and render_session_activity(tabs, page, get_translator()):
            done += 1
    return done


# ── v1.9.1 (ROADMAP v1.9.1): the SESSION ROWS a container puts on its surfaces ──
# A session whose channel died is a page the user would otherwise close and open again;
# `TerminalSessionPage.reconnect()` is the ONE re-arm path that brings it back. The row that fires
# it belongs to the SESSION, so its label, tooltip and STATE RULE ("enabled iff the session can be
# re-armed") are declared ONCE here — the tab-bar CORNER keeps its two controls (AGENTS.md §4.12).


def tmux_attach_command(name) -> str:
    """The `tmux attach` command line of a session name — PURE (v1.9.1).

    `sh_quote()` (`services/system_info_collector.py`) is the SHIPPED quoting rule of this
    codebase: the name travels as ONE single-quoted word, so a space, a quote or a shell
    metacharacter can never become a second word of the command. An empty name answers "" —
    there is nothing to attach to, and the caller refuses it with ONE sentence.
    """
    clean = str(name or "").strip()
    if not clean:
        return ""
    try:
        from services.system_info_collector import sh_quote
    except ImportError:  # flat launch from the project root
        from system_info_collector import sh_quote
    return "tmux attach -t " + sh_quote(clean)


def ask_tmux_name(parent=None) -> str:
    """The session-name field of `Attach tmux session…` — the ONE dialog (v1.9.1).

    `QInputDialog` is read from the `ssh_terminal` module at call time — the same live-namespace
    seam as `ST.QMessageBox` (`AGENTS.md` §4.1), so a suite substitutes it on that module and no
    container grows a dialog of its own. A cancelled field answers "" (the caller does nothing).
    """
    try:
        dialog = _st_module().QInputDialog
        t = get_translator()
        text, ok = dialog.getText(parent, t("terminal.attach_tmux_title"),
                                  t("terminal.attach_tmux_prompt"))
    except Exception:  # noqa: BLE001 — a dialog must never break a container
        return ""
    return str(text or "").strip() if ok else ""


def add_session_actions(menu, page, on_reconnect, on_tmux) -> tuple:
    """Append the Reconnect / Attach tmux rows of `page` to `menu` — the ONE builder (v1.9.1).

    Both containers build their menus per right click (the `_build_context_menu` test seam), which
    is what makes the enabled state a READ of the session at that moment instead of something an
    action has to keep in step: a LIVE session disables Reconnect, an ended one enables it. The
    actions belong to the menu (`menu.addAction()`, so Qt keeps them alive) and the handlers
    receive the page they act on — the tab a user right-clicked is not always the active one.
    Never raises. Answers `(act_reconnect, act_tmux)`.
    """
    t = get_translator()
    can = getattr(page, "can_reconnect", None)
    try:
        reconnectable = bool(callable(can) and can())
    except Exception:  # noqa: BLE001 — a dying C++ object is simply not reconnectable
        reconnectable = False
    act_reconnect = menu.addAction(t("terminal.reconnect"))
    act_reconnect.setToolTip(t("terminal.reconnect_tooltip"))
    act_reconnect.setEnabled(reconnectable)
    act_reconnect.triggered.connect(lambda _checked=False: on_reconnect(page))
    act_tmux = menu.addAction(t("terminal.attach_tmux"))
    act_tmux.setToolTip(t("terminal.attach_tmux_tooltip"))
    act_tmux.setEnabled(page is not None)
    act_tmux.triggered.connect(lambda _checked=False: on_tmux(page))
    return act_reconnect, act_tmux


def format_duration(seconds) -> str:
    """A duration in seconds → "M:SS" / "H:MM:SS" ("" — no usable value).

    A pure function (unit-tested without a GUI): the ETA is derived from measured
    throughput and is therefore an estimate — it is rendered as a plain clock
    reading, never as "about N minutes" (no word forms to translate).
    """
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class TransferMeter:
    """v1.3.3.4 (ROADMAP task 6): the throughput (bytes/s) and the ETA of one SFTP task.

    A SLIDING WINDOW of (time, bytes-done) samples (default 4 s): the average since
    the start of a 100 MB transfer is useless after a stall, while the average over
    the last few seconds follows the link. The clock is injectable (`clock=`) — the
    tests drive the meter without sleeping. `update()` returns (rate, eta) or None
    while there is nothing honest to show (a single sample, a zero/negative delta
    between the samples, a stalled transfer); an unknown total gives (rate, None),
    so a rate can still be displayed.
    """

    WINDOW_SEC = 4.0     # how far back the rate is measured
    MIN_SAMPLES = 2      # one sample is not a measurement

    def __init__(self, clock=time.monotonic, window_sec: float = None):
        self._clock = clock
        self._window = self.WINDOW_SEC if window_sec is None else float(window_sec)
        self._samples = []       # [(t, done)] — oldest first

    def update(self, done: int, total: int, now: float = None):
        """Feed one progress sample → (bytes_per_sec, eta_seconds | None), or None."""
        t = self._clock() if now is None else float(now)
        done = int(done)
        total = int(total) if total else 0
        self._samples.append((t, done))
        while len(self._samples) > self.MIN_SAMPLES and t - self._samples[0][0] > self._window:
            self._samples.pop(0)
        if len(self._samples) < self.MIN_SAMPLES:
            return None
        t0, d0 = self._samples[0]
        dt = t - t0
        moved = done - d0
        if dt <= 0 or moved <= 0:
            return None      # no time passed / nothing moved — a rate would be a guess
        rate = moved / dt
        eta = ((total - done) / rate) if (total > done and rate > 0) else None
        return rate, eta

    def reset(self):
        """Forget the samples (a new task on the same id / a finished transfer)."""
        self._samples = []


class TerminalSessionPage(TerminalFilesPanelMixin, TerminalPageSftpMixin, TerminalPageCwdMixin,
                          QWidget):
    """v1.2: an SSH session as a reusable widget.

    Composition: terminal_thread (SSHTerminalThread) + tscreen (TerminalScreen) +
    widget (TerminalWidget, the canvas) + a QTabWidget [Terminal | Files | History]
    (SftpTab, a lazy worker; CommandHistoryPanel, the per-server command history) +
    the history STORE of this server. The terminal_* config is read from config.json at
    creation time (load_terminal_settings — defaults = the v1.0 behaviour).

    The host (SSHTerminalWindow / a future dock) creates the page with a parent
    and may:
      * attach the bridge signals status_message/progress_* to its own UI — **the
        HOST's status surface is the ONE place a session state is rendered**
        (the v1.4.7 follow-up: the page's own status line is a hidden label now);
      * call set_host_window(w) — close_terminal() will close this session's tab
        on the host (v1.2.1: the last tab closes the window);
      * run the teardown through shutdown() (a single method, idempotent).

    v1.3.3.5 (the terminal SPLIT): `with_sftp=False` builds a page WITHOUT the SFTP
    tab — the split pane is a command line (see __init__): `tabs` then holds the
    canvas alone and `sftp_tab` is None. The default (True) is every other caller —
    tabs and the dock are untouched. v1.4.7 follow-up: such a page ALSO hides its tab
    strip (one tab — nothing to switch) and has no status line, so a pane is its
    canvas + the QTabWidget frame; `with_status_line` is kept as the public ctor
    argument it has always been, no longer selecting a layout.
    v1.5.7: the same flag governs the THIRD tab — a pane never gets the command
    History tab (its layout budget is a command line, and it has no SFTP channel to
    import a history through); the history STORE and the record hook exist on every
    page, because what the application sends belongs to the server either way.
    """

    # v1.0RC3: resize PTY — a grid-change guard + a ~150 ms debounce before
    # channel.resize_pty (DOCUMENTATION.md §14b); the initial invoke_shell is 120×32,
    # the first canvas resize syncs it with the real size.
    PTY_RESIZE_DEBOUNCE_MS = 150

    # v1.0RC4: Quick Launch — a delay before sending the first command after
    # invoke_shell (login scripts/motd; PTY input is buffered, the command is
    # not lost).
    INITIAL_COMMAND_DELAY_MS = 500

    # ── Host bridge (window/dock): the page does not know where messages go ─
    status_message = Signal(str, int)   # (text, timeout_ms); 0 — sticky (no timeout)
    progress_busy = Signal()            # SFTP: show the indeterminate bar
    progress_update = Signal(int, int)  # SFTP: (done, total); total<=0 — indeterminate
    progress_hidden = Signal()          # SFTP: hide the bar

    def __init__(self, server_data, parent=None, password: str = None,
                 initial_command: str = "", with_sftp: bool = True,
                 with_status_line: bool = True, split: bool = False):
        super().__init__(parent)
        self.server_data = server_data
        self._host_window = None     # the host window (SSHTerminalWindow); close_terminal() closes it
        self._force_close = False    # v1.1.1: the limit path — a confirmed decision, "ask" does not ask again
        self._shut_down = False      # shutdown() is idempotent (all teardown paths go through one method)
        # v1.9.1: the session's SECOND state — `closed_signal` has arrived, so `reconnect()` may
        # run (a live session is never re-armed). The re-arm clears it; `shutdown()` ends the page.
        self._session_ended = False
        # The SPLIT marker — the page was created as the second pane of a terminal window
        # (`add_session(split=True)`), NOT as a tab. `MainWindow._terminal_windows` keeps it for the green
        # dot and the multi-input provider, while the `terminal_max_open` limit and
        # `_find_terminal_window_for()` skip it: a pane is a session, not a reason to refuse a new
        # terminal. The flag is a CONSTRUCTOR argument — the page must know from birth that it is a pane.
        self._is_split_pane = bool(split)
        # v1.6.1 (ROADMAP task 8): the keyboard claim — the session takes the focus once,
        # when it is really SHOWN (`claim_focus()`), never while it is still hidden.
        self._focus_claimed = False
        # v1.6.4 (ROADMAP task 4): the ACTIVITY mark — "this session produced output while you
        # were looking at another one". The session owns the STATE, the host owns the tab strip
        # (`note_output()` asks the host what "visible" means and the host re-renders).
        self._activity = False
        # v1.3.3.5: the multi-input badge of the pane — it has no tab in session_tabs,
        # so the highlight marks its inner `Terminal` tab instead (set_session_badge).
        self._session_badge = None

        # v1.3.3.5: the LIVE status text of the session (read by the host through the
        # `session_status` property and by `_apply_session_tab_title`).
        # v1.4.7 follow-up: it no longer owns a status LINE — the text lives in the
        # HOST's status surface alone (the `status_message` bridge below).
        self._session_status = ""
        self._with_status_line = bool(with_status_line)
        # v1.7.2 (task 6): the title the REMOTE program set (`OSC 0`/`OSC 2`, pyte's
        # `Screen.set_title`). Cached here because the host re-renders its surfaces only when it
        # really CHANGED; the reader is `TerminalScreen.title()` under the screen's lock.
        self._remote_title = ""

        t = get_translator()
        layout = QVBoxLayout(self)

        # The session state stops taking a row of the session: the old status line repeated, one row
        # above the `[Terminal | Files]` tabs, the very text the HOST's status bar already showed
        # through the `status_message` bridge — a duplicate that cost a row in every tab. The label
        # OBJECT is deliberately kept (the compatibility readers `page.status_label.text()`, the
        # window's compat property, `_split_min_height`) but is a HIDDEN child, never in the layout.
        self._session_status = t("terminal.initializing")
        self.status_label = QLabel(self._session_status, self)
        # v1.4.3 (ROADMAP task 4): the style comes from the ONE registry
        # (ui/theme_qss.py); refresh_theme() re-applies the same key.
        if theme_qss is not None:
            self.status_label.setStyleSheet(theme_qss.style("status.terminal_row"))
        else:
            self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding: 4px 0;")
        self.status_label.hide()

        # AUDIT v0.7.2 (medium #7): an explicit password takes priority over node.data.password —
        # the model is not polluted with plaintext before the keyring write/project save.
        if password is not None:
            pwd = password or ""
        else:
            pwd = getattr(server_data, 'password', '') or ""
        # v1.9.1: the credential the session was OPENED with stays on the page in memory — a re-arm
        # reuses it when the keyring holds nothing, so no second secret surface is ever opened (§4.4).
        self._session_password = pwd

        # Test seam: the thread class is fetched from the ssh_terminal module at
        # call time (monkeypatching ST.SSHTerminalThread in tests works unchanged).
        # The SAME builder creates the thread of a re-arm — one constructor for the two lives.
        self.terminal_thread = self._build_thread()

        # v1.0 final (ROADMAP task 9): terminal_* keys from ~/.sshmap/config.json —
        # all optional, defaults = the current behaviour (the RC4 look). UI — v1.1.
        term_cfg = _st_module().load_terminal_settings()
        # v1.1 (ROADMAP task 3): the session close behaviour — used in confirm_close().
        self._close_behavior = term_cfg["close_behavior"]

        # v0.8: the pyte screen — a 120x32 grid, the same geometry as invoke_shell;
        # the HistoryScreen scrollback depth — terminal_history_lines (default 1000).
        # v1.6.4 (ROADMAP task 5): the `terminal_scroll` MODE — "live" (the default) | "pin"
        # (the view keeps its lines while output arrives). It is read HERE, at session
        # creation, like the palette/font/cursor keys; the key is config-only.
        self.tscreen = TerminalScreen(columns=120, lines=32,
                                      history_lines=term_cfg["history_lines"],
                                      scroll_mode=term_cfg["scroll"])

        # v1.0RC1: a per-cell canvas (QWidget + QPainter) instead of QPlainTextEdit+HTML.
        # The font — system monospace pt 10, the 'default' palette = the current look;
        # runs/cursor/wide glyphs — see terminal_widget.py. v1.1.2RC3 (AUDIT U3):
        # the wheel mode from the config (terminal_wheel).
        self.widget = TerminalWidget(self.tscreen, self.terminal_thread,
                                     wheel_mode=term_cfg["wheel"],
                                     cursor_style=term_cfg["cursor"])
        # v1.3.3.4 (ROADMAP task 3): the transcript's suggested file name carries the
        # host — the page owns the server data, the canvas owns the menu that asks.
        self.widget.set_transcript_host(getattr(server_data, "host", "") or "")
        # v1.9: the production-tag guard of a multi-line paste — the page owns the node's tags.
        self.widget.guard_hook = self._guard_paste
        # v1.0 final: applying the config (an unknown palette → set_palette() False
        # → "default" stays; corrupt values were dropped in load_terminal_settings).
        if term_cfg["palette"] is not None:
            self.widget.set_palette(term_cfg["palette"])
        if term_cfg["font_family"] or term_cfg["font_size"] is not None:
            self.widget.set_font(
                family=term_cfg["font_family"],
                size=term_cfg["font_size"] if term_cfg["font_size"] is not None else 10)

        # The SFTP tab reuses the SAME transport (no second authentication or known_hosts pass)
        # and its worker is created lazily — on the first switch to "Files" / after
        # `connected_signal`. `with_sftp=False` builds the page WITHOUT it: the split pane is a
        # command line, and a second channel, worker and tree in ~130 px are pure cost.
        self._with_sftp = bool(with_sftp)
        # v1.7.1 (ROADMAP v1.7.1): the window may show this session's Files tree in a
        # right-hand panel instead of the Files TAB (`detach_files_tab()` /
        # `set_files_panel()`); the flag also decides the LAZY channel open, because the panel
        # mode has no tab switch to trigger it.
        self._files_panel_on = False
        self.tabs = QTabWidget()
        self.tabs.addTab(self.widget, t("sftp.tab_terminal"))
        self.sftp_tab = SftpTab() if self._with_sftp else None
        if self.sftp_tab is not None:
            # v1.7.3 (ROADMAP v1.7.3, task 1/2): the container is TOLD who this session is — the
            # `history_key()` of the server (the per-server directory memory is filed under it) and
            # the `(host, ssh_port, user)` triple that decides the server-side send path.
            self.sftp_tab.set_session_info(key=history_key(getattr(server_data, "id", "")),
                                           label=getattr(server_data, "alias", "") or "",
                                           host=getattr(server_data, "host", "") or "",
                                           port=getattr(server_data, "ssh_port", 22),
                                           # v1.7.5: the pane's SOURCE header line falls back to
                                           # `user@host` when the session has no alias.
                                           user=getattr(server_data, "user", "") or "")
            self.tabs.addTab(self.sftp_tab, t("sftp.tab_files"))

        # The COMMAND history — the THIRD tab of the session (`Terminal | Files | History`), one
        # history per server. The STORE exists on every page, because what the application sends
        # belongs to the server whether it went to a tab or to a split PANE; the TAB exists only on a
        # page with the SFTP channel (`with_sftp=True`), because "Import from the server…" has no
        # channel to read through on a compact pane (§4.3). The panel is duck-typed against this page.
        self.command_history = CommandHistoryStore(getattr(server_data, "id", ""))
        self.history_tab = None
        if self._with_sftp:
            self.history_tab = CommandHistoryPanel(store=self.command_history, session=self)
            self.tabs.addTab(self.history_tab, t("terminal.tab_history"))
            self.history_tab.status_message.connect(self._on_history_message)

        # The application records exactly what IT sent. The hook sits on the CANVAS, because that is the
        # ONE method (`TerminalWidget.send_macro`) every explicit send goes through — the macro library
        # calls it directly on `page.widget` and the page's own `send_macro()` (the History tab) reaches
        # it the same way. Typed input is deliberately NOT recorded (the canvas sees raw bytes and keys,
        # not the shell's line editing). Quick launch sends through `send_data()` and records itself.
        self.widget.command_sent_hook = self.record_sent_command
        # v1.6.4 (ROADMAP task 3): the Ctrl+wheel font zoom — the canvas owns the gesture, the
        # PAGE owns the consequence (the PTY grid, the debounced `terminal_font_size` write and
        # the status line), the same split as the command-sent hook above.
        self.widget.font_zoom_hook = self._on_font_zoomed

        # A page with a SINGLE tab does not show a tab STRIP at all — the split pane is a command line and
        # the strip spent a row of a ~140 px pane on one redundant title. The QTabWidget keeps its frame
        # (the pane still has its border) and the multi-input state of a pane is carried by the amber FRAME
        # on `split_host` (`multi_input.apply_container_highlight`); the badge kept on the hidden title is
        # state, not a plaque.
        if self.tabs.count() == 1:
            self.tabs.tabBar().hide()
        layout.addWidget(self.tabs)

        # v1.1.3: the SFTP state (the worker is lazy; a task registry for the progress text).
        # Visualisation — the bridge signals progress_* (in windows mode the window
        # attaches them to its QProgressBar in the status bar — the v1.1.x look).
        self._sftp_worker = None
        self._sftp_tasks = {}      # task_id → (kind, label)
        self._sftp_busy = 0        # how many uploads/downloads are in flight
        # v1.3.3.4 (ROADMAP task 6): task_id → TransferMeter (the rate/ETA of a transfer;
        # dropped with the task — see _on_sftp_task_done/error/cancelled).
        self._transfer_meters = {}
        self.tabs.currentChanged.connect(self._on_tab_changed)
        if self.sftp_tab is not None:
            self.sftp_tab.message.connect(self._on_sftp_tab_message)

        # v1.0RC3: resize PTY — a grid-change guard + a ~150 ms debounce. The canvas
        # lives inside the tab (not in the window's resizeEvent): the eventFilter on
        # the widget itself catches the REAL canvas resize — the recompute is
        # deferred with singleShot(0) until the layout settles (the v1.1.x pattern:
        # a transitional size must not change the grid).
        self._last_cols, self._last_rows = 120, 32
        self._pending_pty = None
        self._pty_timer = QTimer(self)
        self._pty_timer.setInterval(self.PTY_RESIZE_DEBOUNCE_MS)
        self._pty_timer.timeout.connect(self._on_pty_debounce)
        self.widget.installEventFilter(self)

        # v1.6.4 (ROADMAP task 3): the Ctrl+wheel zoom's ONE debounced config write — the
        # `CmdEditTextNote` pattern of AGENTS.md §4.2, restarted by every wheel notch.
        self._font_size_pending = None
        self._font_timer = QTimer(self)
        self._font_timer.setSingleShot(True)
        self._font_timer.setInterval(FONT_SIZE_SAVE_DEBOUNCE_MS)
        self._font_timer.timeout.connect(self._save_font_size)

        # Quick Launch — the first command is sent after the connection (`connected_signal`), not before:
        # on a failed authentication the command simply does not go out and the error is shown via the
        # regular error path. `_session_command` is what the session EXISTS for (a quick-launch command
        # or a `tmux attach`) and is what a re-arm sends again; `_initial_command` is the one-shot send
        # that is still pending (v1.9.1: the two are the same fact at birth).
        self._session_command = (initial_command or "").strip()
        self._initial_command = self._session_command
        self._initial_cmd_conn = None

        # ── v1.6.3 (ROADMAP task 5): the cwd follow (OSC 7) ─────────────────
        # The state of THIS session: the hook goes out ONCE (nothing in the canvas shows
        # it — its echo is held back until the first report), the hold-back is released by
        # the first OSC 7 or by the deadline, and everything degrades to "no follow".
        self._follow_cwd = bool(term_cfg.get("follow_cwd"))
        self._cwd_hook_sent = False
        self._cwd_hold = None          # bytearray while the hook's echo is held back
        self._cwd_hold_deadline = 0.0  # time.monotonic() reading the hold gives up at
        self._cwd_carry = b""          # the tail kept for an OSC 7 split across chunks
        self._last_cwd = ""            # the last directory the shell reported
        if self.sftp_tab is not None:
            self.sftp_tab.set_follow_cwd(self._follow_cwd)
            self.sftp_tab.follow_cwd_changed.connect(self._on_follow_cwd_toggled)

        # The thread's signals are bound and the session starts — the VERY wiring a re-arm runs
        # (`_wire_thread()`), so the birth and the second life can never drift apart.
        self._wire_thread()
        # This call is a NO-OP — the page is still HIDDEN here and Qt delivers no FocusIn to a hidden
        # container, so the keystrokes of a fresh session would go nowhere until the user clicked the
        # canvas. The real claim is the DEFERRED `claim_focus()`, armed by the first `showEvent` and by
        # the container's tab-current hook. A SPLIT PANE does not even arm it: with two shells on one
        # screen the choice of the target belongs to the user (`AGENTS.md` §4.3).
        if not self._is_split_pane:
            self.widget.setFocus()

    # ── v1.9.1 (ROADMAP v1.9.1): the ONE re-arm path of a session ───────────

    def _build_thread(self):
        """The session thread of THIS page — the ONE constructor of `terminal_thread`.

        The birth and every re-arm call it, so the two threads of a page describe the SAME
        endpoint, the SAME resolved settings and the SAME credential: the class is fetched from
        the `ssh_terminal` module at call time (the suite's seam) and the password travels only
        as an argument — never through the model, a file or a log (`AGENTS.md` §4.4).
        """
        thread_cls = _st_module().SSHTerminalThread
        return thread_cls(
            host=self.server_data.host,
            user=self.server_data.user,
            port=self.server_data.ssh_port or 22,
            password=getattr(self, "_session_password", ""),
            key_path=self.server_data.key_path,
        )

    def _wire_thread(self):
        """Bind the CURRENT thread's signals to this page and START it — ONE wiring path.

        `connected_signal` carries three slots: the lazy SFTP channel, the PTY grid the layout
        computed while connecting (`_flush_pty_grid`) and the cwd-follow hook (whose slot checks
        the flag itself, so the binding is unconditional and the teardown drops it by name). The
        Quick Launch connection exists only while a command is pending, which is why it is kept in
        `_initial_cmd_conn` — `shutdown()` disconnects it by that handle (PySide6 6.11 raises a
        RuntimeWarning for an unconnected slot).
        """
        thread = self.terminal_thread
        # The canvas sends through ITS OWN reference (the ONE input point, §4.3), so a re-arm hands
        # it the NEW thread — without this every keystroke, macro and mouse report of the second
        # life would still travel to the dead one.
        try:
            self.widget.terminal_thread = thread
        except (RuntimeError, AttributeError):
            pass  # a test double without a canvas / a dead C++ object
        thread.output_signal.connect(self._on_output)
        thread.error_signal.connect(self._show_error)
        thread.status_signal.connect(self._set_status)
        thread.closed_signal.connect(self._on_closed)
        # v1.1.3: the user may already be sitting on the "Files" tab during the connection —
        # open SFTP as soon as the client appears in the thread.
        thread.connected_signal.connect(self._on_connected_for_sftp)
        # v1.5.7: the PTY receives the grid the layout computed BEFORE the connection — the one
        # debounced resize that the missing channel refused (see _flush_pty_grid).
        thread.connected_signal.connect(self._flush_pty_grid)
        thread.connected_signal.connect(self._on_connected_for_follow)
        self._initial_cmd_conn = None
        if self._initial_command:
            self._initial_cmd_conn = thread.connected_signal.connect(self._send_initial_command)
        thread.start()

    def can_reconnect(self) -> bool:
        """May this page be re-armed? — the ONE state reader of the Reconnect row (v1.9.1).

        True exactly when `closed_signal` has arrived and the page is still alive: a LIVE session
        is never re-armed (the row is disabled) and a page whose `shutdown()` ran has no host left
        to report to. A container reads this at the moment it builds a menu, so the state is never
        cached in an action. Never raises.
        """
        if getattr(self, "_shut_down", False):
            return False
        return bool(getattr(self, "_session_ended", False))

    def reconnect(self) -> bool:
        """Bring THIS session back — the ONE re-arm path (v1.9.1, `AGENTS.md` §4.3).

        The page is REUSED: the screen (so the dead output stays as scrollback), the canvas, the
        SFTP tab, the registrations of the host and the credential are the session's own — only the
        THREAD is created again, through the ONE `_build_thread()` + `_wire_thread()` pair. The
        dead thread leaves through the shipped `stop()` + orphan registry, the marker line is
        written into the screen BEFORE the new life starts (it is the boundary the user sees), the
        session's own command (`_session_command`) is re-armed — a `tmux attach` comes back — and
        the PTY grid is handed over by the shipped `_flush_pty_grid()` on `connected_signal`.

        THREE refusals, each ONE status line and a False: a page already torn down, a session that
        is still LIVE, and a re-arm with no credential at all (no keyring entry, no credential this
        session was opened with and no key file — the keyring is READ, never asked (§4.4)).
        The host-key question is not re-asked for a key the store already pinned: the policy of
        `modules/ssh_connect.py` accepts a known key silently.
        """
        t = get_translator()
        if getattr(self, "_shut_down", False):
            return False
        if not self._session_ended:
            self._set_status_text(t("terminal.reconnect_live"))
            return False
        password = self._resolve_reconnect_password()
        key_path = (getattr(self.server_data, "key_path", "") or "").strip()
        if not password and not key_path:
            self._set_status_text(t("terminal.reconnect_no_credential"))
            return False
        old = getattr(self, "terminal_thread", None)
        if old is not None:
            try:
                old.stop()
                if old.isRunning():
                    _st_module().register_orphan_thread(old)
            except RuntimeError:
                pass  # Qt teardown of a dead thread — the new one is what matters
        self._session_password = password
        self._session_ended = False
        self._initial_command = self._session_command
        self._write_reconnect_marker(t)
        self.terminal_thread = self._build_thread()
        self._wire_thread()
        self._set_status_text(t("terminal.reconnecting",
                                alias=getattr(self.server_data, "alias", "")
                                or getattr(self.server_data, "host", "")))
        return True

    def _resolve_reconnect_password(self) -> str:
        """The secret a re-arm starts with — the keyring first, this session's own second.

        The page opens NO second secret surface (`AGENTS.md` §4.4): the STORED credential of this
        endpoint is re-read through the ONE scope rule, and when the store answers nothing the
        credential the session was opened with is reused. A key path needs no secret at all, which
        is why the caller refuses only when all three answers are empty. Never raises — an
        unavailable keyring is the shipped "no stored credential" path.
        """
        data = self.server_data
        stored = ""
        try:
            from services.credential_manager import get_credential_manager, node_scope
            stored = get_credential_manager().load_password(
                getattr(data, "id", ""), scope=node_scope(data)) or ""
        except Exception:  # noqa: BLE001 — the keyring is optional, exactly as in every other read
            stored = ""
        return stored or getattr(self, "_session_password", "") or ""

    def _write_reconnect_marker(self, t):
        """Write the ONE boundary line of a re-arm into the KEPT screen.

        The dead output is this session's scrollback, so the line that says "a new life starts here"
        is fed into pyte directly — NOT through `_on_output()`: nothing came from the network, the
        transcript keeps the remote stream alone, and the OSC 7 scan has no report to read. The
        canvas is repainted so the boundary is on screen before the new prompt arrives. Never raises.
        """
        marker = str(t("terminal.reconnect_marker") or "").strip()
        try:
            self.tscreen.feed(b"\r\n" + marker.encode("utf-8", "replace") + b"\r\n")
            self.widget.update()
        except Exception:  # noqa: BLE001 — a cosmetic line may never block the re-arm
            pass

    def attach_tmux(self, name) -> bool:
        """Ask this session for a `tmux attach` — the ONE entry both containers call (v1.9.1).

        The command is built by the PURE `tmux_attach_command()` (the SHIPPED `sh_quote()` is the
        quoting rule) and becomes the session's OWN command, so a later Reconnect attaches again —
        that is what "bring this session back" means to a shell that exists for a `tmux attach`.
        A LIVE session sends it at once through the ONE `send_macro()` (and the command history
        records it like any other explicit send); an ENDED one rides the re-arm instead. An empty
        name answers False — there is nothing to attach to.
        """
        cmd = tmux_attach_command(name)
        if not cmd:
            return False
        self._session_command = cmd
        if self._session_ended:
            self._initial_command = cmd
            return self.reconnect()
        sent = self.send_macro(cmd)
        if sent:
            self._set_status_text(get_translator()("terminal.attach_tmux_sent", name=str(name).strip()))
        return sent

    # ── v1.3.3.1 (ROADMAP task 1): live i18n — re-text on a language switch ──

    def retranslate(self):
        """v1.3.3.1: re-text the page's own strings in the current language.

        The tab titles of the inner QTabWidget (`Terminal | Files | History`; a page built with
        `with_sftp=False` has the `Terminal` tab alone) — the walk reads the tab COUNT and asks
        each page which widget it is, so a page with a different tab set re-texts exactly what
        it has; and v1.3.3.5: the `Terminal` title is re-composed by `_apply_session_tab_title()`
        — the multi-input badge a SPLIT PANE carries there AND its live status text, both of
        which must survive the switch. Every
        string already has an i18n key (ZERO new keys) and the module translator is
        looked up at call time — no cache to invalidate. The status label carries the
        LIVE session state (connecting/opened/closed — emitted by the thread), so it
        is deliberately left alone; the SFTP tab and the History panel re-text themselves. Never
        raises — the dead-C++-object discipline of every container method.
        """
        t = get_translator()
        try:
            tabs = self.tabs
            for i in range(tabs.count()):
                widget = tabs.widget(i)
                if widget is self.sftp_tab and self.sftp_tab is not None:
                    tabs.setTabText(i, t("sftp.tab_files"))
                elif widget is self.history_tab and self.history_tab is not None:
                    tabs.setTabText(i, t("terminal.tab_history"))
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        # v1.3.3.5: the inner `Terminal` title carries the multi-input badge of a SPLIT
        # PANE — re-composed here so a language switch re-texts the badge instead of dropping it.
        self._apply_session_tab_title()
        sftp_tab = getattr(self, "sftp_tab", None)
        if sftp_tab is not None:
            try:
                sftp_tab.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the tab is already destroyed
        # v1.5.7 (ROADMAP task 4): the History panel — its headers, its placeholder and the
        # `terminal.history.last_unknown` cells are all translated text.
        history_tab = getattr(self, "history_tab", None)
        if history_tab is not None:
            try:
                history_tab.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the tab is already destroyed
        # v1.3.3.4: the canvas's own strings (the find panel — if it is open)
        widget = getattr(self, "widget", None)
        if widget is not None:
            try:
                widget.retranslate()
            except RuntimeError:
                pass  # Qt teardown — the canvas is already destroyed

    def refresh_theme(self):
        """v1.4.3 (ROADMAP task 4): re-apply the theme to this session.

        The page's status label, the canvas (the find bar is its child), the SFTP tab and the
        History panel. The terminal's OUTPUT palette is deliberately out of the UI
        theme's scope (AGENTS.md §4.6) — a session keeps its colours. Never
        raises: a session may be closing under the switch.
        """
        if theme_qss is not None:
            try:
                theme_qss.refresh(self.status_label, "status.terminal_row")
            except RuntimeError:
                pass  # Qt teardown — the label is already destroyed
        widget = getattr(self, "widget", None)
        if widget is not None:
            hook = getattr(widget, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass
        for tab_name in ("sftp_tab", "history_tab"):   # v1.5.7: the panel joins the walk
            tab = getattr(self, tab_name, None)
            if tab is None:
                continue
            hook = getattr(tab, "refresh_theme", None)
            if callable(hook):
                try:
                    hook()
                except RuntimeError:
                    pass

    # ── v1.3.3.5 (ROADMAP task 6): the multi-input badge of a SPLIT PANE ─────

    def set_session_badge(self, key=None, **kwargs):
        """v1.3.3.5: mark THIS session's inner `Terminal` tab with the i18n key `key`.

        The container's multi-input highlight badges the TABS of `session_tabs`
        (modules/multi_input.py) — a split pane has no tab there, so the badge of the
        pane goes on the only title it owns (its `Terminal` tab). The KEY (plus its
        format kwargs) is stored instead of the rendered text, so the badge follows a
        language switch: `retranslate()` re-renders it in the new language. `key=None`
        restores the plain title. No new i18n key — the caller passes the SAME
        `terminal.multi_tab_badge` / `terminal.multi_excluded_badge`. Never raises.
        """
        self._session_badge = (str(key), dict(kwargs)) if key else None
        self._apply_session_tab_title()

    def _apply_session_tab_title(self):
        """Compose the inner `Terminal` tab title of THIS session (v1.3.3.5).

        Base — `sftp.tab_terminal`; plus the multi-input badge if the container set one
        (a split pane). **The LIVE status text is deliberately NOT part of it any more**
        (the v1.4.7 follow-up): the state of a session lives in the host's status
        surface alone, and the pane of a split — the only page whose tab strip is hidden
        (`__init__`) — keeps the badge as state while the amber frame carries it
        visibly. The badge is a KEY and is rendered with the current language. Never
        raises.
        """
        try:
            t = get_translator()
            title = t("sftp.tab_terminal")
            if self._session_badge is not None:
                key, kwargs = self._session_badge
                title = t(key, **kwargs) if kwargs else t(key)
            self.tabs.setTabText(0, title)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    # ── Host ────────────────────────────────────────────────────────────────

    def set_host_window(self, window):
        """The host window (SSHTerminalWindow): close_terminal() will close it, and
        QMessageBox will get it as their parent. Without a host — teardown directly."""
        self._host_window = window

    def send_macro(self, text) -> bool:
        """v1.3 (ROADMAP v1.3): a command-library macro → the terminal canvas
        (widget.send_macro: a direct send_data of its own session, not a broadcast).
        RuntimeError — a close race (the C++ object was destroyed) → False.

        v1.5.7 (ROADMAP task 6): this is the send path the History tab's "Send to terminal"
        uses, and the canvas records it through `command_sent_hook` — the timestamp and the
        count of the entry move as a result of the send, exactly as the ROADMAP requires."""
        try:
            return self.widget.send_macro(text)
        except RuntimeError:
            return False

    # ── v1.5.7 (ROADMAP task 7): the COMMAND history of this server ─────────

    def record_sent_command(self, text) -> bool:
        """Append what the APPLICATION sent to this server's command history (v1.5.7).

        Called by the canvas hook after a successful `TerminalWidget.send_macro()` and by the
        quick-launch path — the two places where the application knows the exact command line it
        put on the wire. **Nothing is inferred from the typed input**: the canvas sees raw bytes
        and key events, not the shell's line editing, so a reconstruction of what a user typed
        would be a guess (the documented non-goal of the version). An over-long or empty text is
        ignored by the store's own rules. Never raises — a history failure must not break a send.
        """
        store = getattr(self, "command_history", None)
        if store is None:
            return False
        try:
            store.record(text)
        except Exception:   # noqa: BLE001 — the history is bookkeeping, never a send path
            return False
        panel = getattr(self, "history_tab", None)
        if panel is not None:
            try:
                panel.reload()   # the new row / the moved timestamp is on screen at once
            except RuntimeError:
                pass  # Qt teardown — the panel is already destroyed
        return True

    # ── v1.6.4 (ROADMAP task 3): the Ctrl+wheel font zoom ───────────────────

    def _on_font_zoomed(self, size: int):
        """The canvas zoomed its font: the grid, the config key and the status line follow.

        The page's half of the gesture (the hook `TerminalWidget.font_zoom_hook`), three
        consequences in ONE call:
          * the GRID — `_sync_grid()` reads the canvas metrics the zoom has just changed, so
            pyte and (through the ordinary debounce) the PTY receive the new columns/rows; a
            font change is a grid change even though the WIDGET never resized;
          * the KEY — `terminal_font_size`, written by ONE debounced timer (a wheel is a stream
            of events and the §4.2 rule is one write per gesture);
          * the WORDS — the session's status line, through the page's single `_set_status_text`.
        Never raises: a view action of the canvas may not break on a page under teardown.
        """
        try:
            self._sync_grid()
        except RuntimeError:
            return  # Qt teardown — the canvas/page is already gone
        try:
            self._font_size_pending = int(size)
            self._font_timer.start()
        except RuntimeError:
            pass  # Qt teardown — the write is simply skipped
        self._set_status_text(get_translator()("terminal.font_zoom", size=int(size)))

    def _save_font_size(self) -> bool:
        """The debounce target: write the pending size into `~/.sshmap/config.json`.

        The `COMMAND_WIDTH_SAVE_DEBOUNCE_MS` / `_save_follow_cwd()` pattern: an owner-written
        key of an existing setting (the settings hub reads and writes the same one), a
        read-only HOME answers False and the session keeps the size either way.
        """
        size = getattr(self, "_font_size_pending", None)
        if size is None:
            return False
        try:
            from i18n import save_config
        except Exception:  # noqa: BLE001 — a build without i18n keeps the session's size
            return False
        try:
            return bool(save_config({FONT_SIZE_CONFIG_KEY: int(size)}))
        except Exception:  # noqa: BLE001 — a read-only HOME is not worth an error dialog
            return False

    # ── v1.6.4 (ROADMAP task 4): the activity mark of an inactive session ───

    def note_output(self) -> bool:
        """Note that THIS session produced output → the mark of an INACTIVE session.

        The ONE rule of the feature, asked once per fed output chunk (from `_on_output`): the
        session asks its HOST whether it is the session the user is looking at
        (`session_is_visible(page)` — only the container knows what "visible" means: the current
        tab of the dock, and in a window the current tab OR the focused split pane) and marks
        itself otherwise. A visible session CLEARS its mark here, which is the same call the tab
        switch makes — the rule and the clearing are one method, so they cannot disagree.

        The mark is the session's own state (`has_activity`); the tab strip belongs to the host,
        which re-renders when the state really changes. Returns True when the session ends up
        marked. Never raises — a mark is not worth a broken output path.
        """
        host = getattr(self, "_host_window", None)
        visible = False
        hook = getattr(host, "session_is_visible", None)
        if callable(hook):
            try:
                visible = bool(hook(self))
            except RuntimeError:
                visible = False
        return self.set_activity(not visible)

    def set_activity(self, on: bool) -> bool:
        """Set the activity mark and let the host re-render the tab. Idempotent, never raises.

        The host hook (`session_activity_changed(page)`) is duck-typed like every other host
        call of this page: a container without it simply keeps the state.
        """
        on = bool(on)
        if on == self._activity:
            return on
        self._activity = on
        host = getattr(self, "_host_window", None)
        hook = getattr(host, "session_activity_changed", None)
        if callable(hook):
            try:
                hook(self)
            except RuntimeError:
                pass   # Qt teardown — no tab strip left to mark
        return on

    @property
    def has_activity(self) -> bool:
        """Is there output this session produced while it was not the visible one?"""
        return bool(self._activity)

    # ── v1.7.2 (task 6): the title the REMOTE program set (OSC 0/OSC 2) ─────────

    @property
    def remote_title(self) -> str:
        """The window title the remote program asked for ("" — it never set one).

        pyte's `Screen.set_title()` has always stored `OSC 0`/`OSC 2`; this is the ONE reader the
        application has, and the host's tab tooltip and container title are its consumers (§4.3).
        """
        return self._remote_title

    def _sync_remote_title(self) -> bool:
        """Refresh the cached remote title; True when it really CHANGED.

        Called from the session's SINGLE output path (`_on_output`) right after pyte consumed the
        chunk: a title arrives WITH output, so the check belongs there and nowhere else. The host is
        notified through the duck-typed `session_title_changed(page)` — the same host contract every
        other page callback uses. Never raises.
        """
        try:
            title = str(self.tscreen.title() or "").strip()
        except (RuntimeError, AttributeError):
            return False      # Qt teardown / a screen without the reader — nothing to sync
        if title == self._remote_title:
            return False
        self._remote_title = title
        host = getattr(self, "_host_window", None)
        hook = getattr(host, "session_title_changed", None)
        if callable(hook):
            try:
                hook(self)
            except RuntimeError:
                pass          # Qt teardown — no tab strip and no title left to re-render
        return True

    def ensure_sftp_worker(self):
        """The SFTP worker of this session, started lazily — or None (v1.5.7).

        The ONE way the History tab reaches the channel the Files tab uses: the panel asks for
        the worker and queues its read into it, so the file of the server is read OFF the GUI
        thread. A page without the SFTP tab (`with_sftp=False`, the split pane) has no channel
        and answers None — its History tab does not exist either.
        """
        try:
            if self._ensure_sftp():
                return self._sftp_worker
        except RuntimeError:
            pass  # Qt teardown — the session is already going away
        return None

    def _on_history_message(self, msg: str, timeout: int):
        """A History-panel message → the page's status_message bridge (the SFTP tab pattern)."""
        try:
            self.status_message.emit(msg, timeout)
        except RuntimeError:
            pass  # Qt teardown — no host left to tell

    # ── v1.2: teardown — one method for all paths ───────────────────────────

    def confirm_close(self) -> bool:
        """The gate before teardown (v1.1, ROADMAP task 3): terminal_close_behavior.

        "ask": an active session (the SSH thread is still running) → a
        confirmation; a cancel — False (the host must event.ignore() and keep
        living). "close" (default) and an already-finished session — no dialog.
        _force_close (the v1.1.1 limit path: the "close the oldest" decision is
        already confirmed by the user) — also no dialog. Teardown robustness:
        RuntimeError on C++ objects does not block the close."""
        try:
            if getattr(self, "_close_behavior", "close") == "ask" \
                    and not getattr(self, "_force_close", False):
                _thread = self.terminal_thread
                if _thread is not None and _thread.isRunning():
                    t = get_translator()
                    box = _st_module().QMessageBox   # test seam (ST.QMessageBox)
                    reply = box.question(
                        self._host_window, t("msg.close_session_title"),
                        t("msg.confirm_close_session"),
                        box.Close | box.Cancel, box.Close)
                    if reply != box.Close:
                        return False
        except RuntimeError:
            pass  # a Qt teardown — close without asking (as before)
        return True

    def stop_thread(self):
        """Stop the thread WITHOUT waiting (the close_terminal path; wait() — in shutdown())."""
        try:
            thread = getattr(self, "terminal_thread", None)
            if thread is not None:
                thread.stop()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)

    def close_terminal(self):
        """Close the session (v1.2.1): stop the thread + close THIS session's tab
        on the host (window.close_page → confirm_close → shutdown; the last tab
        closes the window). The MainWindow._shutdown_background_threads path and
        the "4 own terminals" limit: in a tabbed window, closing a session does
        NOT touch the neighbouring tabs. Without a host / the host has no
        close_page (a fake) — teardown directly."""
        self.stop_thread()
        w = getattr(self, "_host_window", None)
        if w is not None:
            close_page_fn = getattr(w, "close_page", None)
            if callable(close_page_fn):
                try:
                    close_page_fn(self)
                    return
                except RuntimeError:
                    pass  # the host was already destroyed — teardown directly
        self.shutdown()

    def shutdown(self):
        """The SINGLE teardown method (v1.2, ROADMAP task 3): every teardown path
        (window close, session error, MainWindow shutdown, the limit path) goes
        through it. Idempotent (a repeated call — no-op).

        Order (the v1.1.x closeEvent order is kept):
          1. the SFTP worker FIRST (it depends on the terminal thread's transport):
             disconnect the page's slots, stop with a bounded wait; a wait that does
             not finish (a transfer stalled on a dead network) — the orphan worker
             registry keeps the thread alive until finished();
          2. stop the PTY debounce timer (resize_pty into a dead channel);
          3. disconnect the thread's signals from the page and stop() + wait(1500):
             the recv loop has msleep(30) — after stop() the thread exits in ~100 ms,
             the wait always makes it in practice; the window/page may be destroyed
             after this event (WA_DeleteOnClose), while paramiko may still be
             connecting for up to 15 s → a thread that outlives the wait is
             registered in the orphan thread registry `_orphan_threads`
             (v1.1.2RC1 N4): a live QThread without a QObject parent must not be
             left to GC, and late emits without receivers are a safe no-op.
        """
        if self._shut_down:
            return
        self._shut_down = True
        # v1.6.3: the cwd follow's hold-back is disarmed FIRST — a late chunk must not be
        # buffered by a session that is going away (nothing is lost: the bytes die with it).
        self._cwd_hold = None
        self._follow_cwd = False

        # IMPORTANT (verified by running, PySide6 6.11): signal.disconnect(receiver)
        # raises TypeError — the disconnection is done by the EXACT slot (bound
        # method); TypeError is caught only for "the slot was not connected"
        # (conditional connections).
        def _dissig(sig, slot):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass  # the slot was not connected — nothing to do

        # v1.1.3: the SFTP worker FIRST (it depends on the terminal thread's transport).
        sftp_worker = getattr(self, "_sftp_worker", None)
        if sftp_worker is not None:
            _dissig(sftp_worker.task_started, self._on_sftp_task_started)
            _dissig(sftp_worker.progress, self._on_sftp_progress)
            _dissig(sftp_worker.task_done, self._on_sftp_task_done)
            _dissig(sftp_worker.task_error, self._on_sftp_task_error)
            _dissig(sftp_worker.task_cancelled, self._on_sftp_task_cancelled)
            _dissig(sftp_worker.finished, self._on_sftp_worker_finished)
            # v1.8rc6 (N56): the transfer bookkeeping dies WITH the transport. The six slots above
            # are gone, so a transfer that is IN FLIGHT here can never deliver its done/error/
            # cancelled — the entries would outlive the worker that owned them. Cleared, not left.
            self._sftp_tasks.clear()
            self._transfer_meters.clear()
            self._sftp_busy = 0
            sftp_worker.shutdown(wait_ms=2500)
            if sftp_worker.isRunning():
                register_orphan_sftp_worker(sftp_worker)

        # v1.3.1 (ROADMAP task 4): the preview panel closes together with the session —
        # BEFORE the worker/thread teardown (the panel never outlives the transport it
        # was read through). Idempotent; a destroyed C++ object must not block the close.
        # v1.3.3.5: a page without the SFTP tab (`with_sftp=False`) has no panel at all.
        # `release()` is the tab's OWN teardown: it stops a LOCAL pane's provider (§4.8).
        sftp_tab = getattr(self, "sftp_tab", None)
        if sftp_tab is not None:
            try:
                sftp_tab.release()
            except RuntimeError:
                pass

        # v1.3.3.4 (ROADMAP task 3): the transcript is a local file of the SESSION — it
        # is closed here, on the single idempotent teardown path, so no tee survives a
        # closed session (the ROADMAP requirement: it must never raise into the teardown,
        # hence the broad guard: a full disk / a destroyed canvas must not block the close).
        try:
            self.widget.stop_transcript()
        except Exception:  # noqa: BLE001 — the file close must not block the session teardown
            pass

        try:
            self._pty_timer.stop()
        except Exception:
            pass  # a C++ object RuntimeError (teardown) — does not block the close

        thread = getattr(self, "terminal_thread", None)
        if thread is not None:
            _dissig(thread.output_signal, self._on_output)
            _dissig(thread.error_signal, self._show_error)
            _dissig(thread.status_signal, self._set_status)
            _dissig(thread.closed_signal, self._on_closed)
            # + connected_signal — it was not disconnected before;
            # on a close before the connect finished, the orphan thread would still
            # send the first Quick Launch command into the void after a successful
            # connection.
            _dissig(thread.connected_signal, self._on_connected_for_sftp)
            _dissig(thread.connected_signal, self._flush_pty_grid)
            # v1.6.3: the cwd follow's hook — an orphan thread must not install it after
            # the page is gone (the same reason the Quick Launch connection is dropped).
            _dissig(thread.connected_signal, self._on_connected_for_follow)
            # Quick Launch — only if the connection was made (the Connection object from __init__)
            if getattr(self, "_initial_cmd_conn", None) is not None:
                try:
                    thread.connected_signal.disconnect(self._initial_cmd_conn)
                except (TypeError, RuntimeError):
                    pass
            thread.stop()
            if thread.isRunning():
                thread.wait(1500)
                # v1.1.2RC1 (N4): the page may be destroyed after this event
                # (the window — WA_DeleteOnClose), while paramiko may still be connecting (up to 15 s).
                if thread.isRunning():
                    _st_module().register_orphan_thread(thread)

        # The "Files" tab's slot is disconnected too (the worker's list_ready goes
        # straight into the tab — it will die together with the page). v1.3.3.5: nothing
        # to unbind on a page built without the SFTP tab.
        if getattr(self, "sftp_tab", None) is not None:
            _dissig(self.sftp_tab.message, self._on_sftp_tab_message)
            # v1.6.3: the follow checkbox reports into this page — drop the connection with
            # the rest of the teardown.
            _dissig(self.sftp_tab.follow_cwd_changed, self._on_follow_cwd_toggled)

    # ── v1.0RC3: dirty rendering without a timer (ROADMAP task 8) ───────────

    def eventFilter(self, obj, event):
        """v1.2: a canvas resize (inside the tab) → a grid recompute. Before —
        SSHTerminalWindow.resizeEvent; the grid-change guard and the debounce are the same."""
        if obj is self.widget and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._sync_grid)
        return super().eventFilter(obj, event)

    def claim_focus(self) -> bool:
        """v1.6.1 (ROADMAP task 8): give the keyboard to THIS session's canvas.

        `setFocus()` called while the page is still HIDDEN never reaches the container —
        no `FocusIn` is delivered (the fact `modules/ssh_terminal.py` states at
        `_wire_page()`), so without the claim a fresh session opens with a blinking cursor and
        keystrokes that go nowhere until the user clicks the canvas. The claim is
        therefore ONE DEFERRED `setFocus` (singleShot(0), when the layout has run) and it
        is armed from the two places that know the session is really on screen: the first
        `showEvent` and the tab-current hook of the container.

        A SPLIT PANE is deliberately left alone — with two shells on one screen the choice
        of the target belongs to the user. Returns True when the request was made.
        """
        if getattr(self, "_is_split_pane", False) or self._shut_down:
            return False
        widget = getattr(self, "widget", None)
        if widget is None:
            return False
        try:
            QTimer.singleShot(0, self._claim_focus_now)
        except RuntimeError:
            return False  # Qt teardown — the canvas is already destroyed
        return True

    def _claim_focus_now(self):
        """The deferred half of `claim_focus()` — called by the event loop, GUARDS itself.

        The canvas may die between the schedule and the fire (the `WA_DeleteOnClose` race), and
        the callback is the only place the failure can be caught: an `except RuntimeError`
        around `singleShot()` protects the bound-method creation, never its invocation. A bare
        Qt method handed to the loop would let the exception escape whatever pumped the events
        (the `_sync_grid` shape is the rule).
        """
        try:
            self.widget.setFocus()
        except RuntimeError:
            pass  # the C++ object was already destroyed

    def showEvent(self, event):
        """v1.5.7: the first SHOW re-computes the grid, so a session never depends on a
        resize event to find out how big it is.

        A page that is shown without its canvas changing size (a dock tab revealed later, a
        window restored to the very geometry of the layout pass) would otherwise keep
        `invoke_shell`'s 120×32 as its only grid definition. Deferred with singleShot(0): at
        show time the layout has not run yet, and `_sync_grid` guards the not-laid-out case.

        v1.6.1 (ROADMAP task 8): the FIRST show also claims the keyboard (`claim_focus()`),
        deferred the same way. A LATER show (a tab switched back, a window re-shown) does not
        re-claim it — the container's tab hook is the place for that, and a minimise/restore
        must not move the focus the user placed somewhere else.
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_grid)
        if not self._focus_claimed:
            self._focus_claimed = True
            self.claim_focus()

    def _on_output(self, data: bytes):
        """A slot from the SSH thread (a queued signal — already in the GUI thread):
        raw bytes into pyte + a direct canvas update(). A 30 FPS timer is not
        needed: Qt coalesces several update() calls within one event cycle by
        itself; paintEvent reads the grid itself (TerminalWidget._paint). The
        scrollback auto-snap to the live line on new output — inside pyte
        (HistoryScreen.before_event), so new output is visible immediately, even
        if the user was viewing the history.

        v1.1.2RC3 (N7): if this output auto-returned the scrollback to live
        (the history position changed) — the selection is reset: the (row, col)
        coordinates were pinned on the HISTORICAL screen in the release, and after
        the return they point at OTHER cells of the live screen — Ctrl+C would
        copy someone else's text. Without new output / without an active selection,
        the behaviour of a plain click and of Ctrl+C does not change.

        v1.5.7: a failure INSIDE the emulator does not cost the repaint. A bare
        `return` would leave the canvas on the previous frame until the NEXT
        output arrived, which from the outside looks like "the full-screen application is gone
        but the prompt only appears when I press a key" (a TUI's exit sequence is followed by
        silence until the user types). The state is now whatever pyte managed to apply: it is
        repainted, and the failure is LOGGED instead of swallowed.

        v1.6.3 (ROADMAP task 5): the OSC 7 SCAN runs on the RAW bytes FIRST — a directory
        report is never delayed by the echo hold-back — and the hold-back itself follows:
        while the injected hook's echo is being suppressed the canvas, the transcript and
        pyte see NOTHING (the filtered stream); the first report drops the held bytes and a
        shell that never answers gets them back at the deadline or at the cap.

        v1.6.4 fix: the answer and the echo are usually in ONE chunk (bash echoes the line and
        prints the next prompt — report first, prompt after — within one read), so the scan
        answers WHERE that answer ends and the hold-back drops the head of the SAME chunk with
        the held bytes (`osc7_report_end()`); releasing the hold without filtering the chunk
        that released it was the leak that put the whole hook command on the screen.
        """
        cut = self._scan_osc7(data)
        data = self._hold_cwd_echo(data, cut)
        if not data:
            return
        pos_before = None
        try:
            pos_before = self.tscreen.scroll_info()[0]
            self.tscreen.feed(data)
        except Exception as exc:  # noqa: BLE001 — the canvas must repaint whatever state exists
            log = _log()
            if log is not None:
                log.warning(f"terminal: feed failed ({exc!r}) — repainting the current state")
        # v1.3.3.4 (ROADMAP task 3): the transcript tee. Inside the output path but
        # deliberately OUTSIDE the pyte block above: a broken file must not stop the
        # rendering (write_transcript swallows everything and stops the tee itself).
        try:
            self.widget.write_transcript(data)
        except Exception:  # noqa: BLE001 — the tee never breaks the session
            pass
        # N45: the terminal's OWN answers (a DSR/DA query the emulator replied to) go back on the
        # channel of THIS session, AFTER the chunk that produced them.
        self._send_terminal_reply(self.tscreen.take_pending_input())
        # N7: a history position change ⇔ an auto-return to live (`feed()` — the only path
        # that changes the position without a manual scroll), so a selection on the "old"
        # screen is reset before copying. Under `terminal_scroll = "pin"` the viewport does NOT
        # move — the chunk restores the very lines it held — so the guard is SKIPPED (the "live"
        # mode keeps the N7 rule); the move back to live is a USER action that drops it (§64).
        try:
            if pos_before is not None and self.tscreen.scroll_mode_id() != SCROLL_MODE_PIN \
                    and self.tscreen.scroll_info()[0] != pos_before \
                    and self.widget.has_selection():
                self.widget.clear_selection()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose close race)
        # v1.6.4 (ROADMAP task 4): the ACTIVITY mark of an INACTIVE session — the last step of
        # this path, after the canvas really has the new bytes (a page the user is not looking
        # at says so in its tab strip; the host decides what "visible" means).
        try:
            self.note_output()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose close race)
        # v1.7.2 (task 6): the remote title (`OSC 0`/`OSC 2`) rides on the SAME path — pyte has
        # just consumed the chunk, so a title it carried is one property read away, and the host
        # is told only when it really changed.
        try:
            self._sync_remote_title()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose close race)
        try:
            self.widget.update()
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose close race)

    def _send_terminal_reply(self, data: bytes) -> bool:
        """Put the terminal's OWN answer on the channel of THIS session (N45). Never raises.

        The FOURTH bypass of the ONE input point (`AGENTS.md` §4.3): a reply to a DSR/DA query is
        the TERMINAL's, not the user's. It must not travel through `TerminalWidget._send()` — the
        multi-input hub would copy a cursor-position answer into every live session — and it must
        not be recorded in the command history (`record_sent_command` is the macro path). A closed
        channel and a dead thread answer False quietly; the reply is a few bytes.
        """
        if not data:
            return False
        thread = self.terminal_thread
        if thread is None:
            return False
        channel = getattr(thread, "channel", None)
        if channel is not None and getattr(channel, "closed", False):
            return False
        try:
            thread.send_data(data)
            return True
        except Exception:  # noqa: BLE001 — a teardown race must not break the output path
            return False


    # ── v1.0RC3: resize PTY — a grid guard + debounce (ROADMAP task 6) ──────

    def _visible_grid(self):
        """(cols, rows) of the visible grid: the canvas size / the cell metrics."""
        cw, chh = self.widget.cell_size
        cols = max(2, self.widget.width() // cw)
        rows = max(1, self.widget.height() // chh)
        return cols, rows

    def _sync_grid(self):
        """A recompute of the visible grid (after the layout settled).

        v1.5.7: a canvas that is not laid out yet (width/height 0 — a page built into a
        hidden dock) is left alone. `_visible_grid()` clamps to 2×1, and pushing that into
        pyte/the PTY would destroy the session's grid for a frame (the showEvent hook makes
        this reachable in cases where no resize event would have been).
        """
        try:
            if self.widget.width() <= 0 or self.widget.height() <= 0:
                return  # not laid out yet — the Resize/showEvent path will come back
            cols, rows = self._visible_grid()
            if (cols, rows) == (self._last_cols, self._last_rows):
                return  # the grid did not change — no pyte.resize, no PTY signal
            self._last_cols, self._last_rows = cols, rows
            self.tscreen.resize(cols, rows)   # pyte: a no-op at the same size
            self.widget.update()              # the grid changed — repaint the canvas
            self._pending_pty = (cols, rows)
            self._pty_timer.start()           # restart the 150 ms countdown (debounce)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a WA_DeleteOnClose race on close)

    def _pty_channel(self):
        """The LIVE PTY channel of this session, or None (not connected / closed / gone)."""
        thread = getattr(self, "terminal_thread", None)
        channel = getattr(thread, "channel", None) if thread is not None else None
        if channel is None or getattr(channel, "closed", False):
            return None
        return channel

    def _send_pty_resize(self) -> bool:
        """Send the pending grid to the PTY. True — it went out; False — not possible yet."""
        pending = getattr(self, "_pending_pty", None)
        if pending is None:
            return False
        channel = self._pty_channel()
        if channel is None:
            return False
        self._pending_pty = None
        try:
            channel.resize_pty(width=pending[0], height=pending[1])
        except Exception:
            return False   # the channel died — nothing to do
        return True

    def _on_pty_debounce(self):
        """The debounce expired — resize_pty with the LAST grid (only a live channel).

        v1.5.7: a grid computed BEFORE the connection is never thrown away. The layout
        runs when the window appears — long before paramiko has authenticated — so the first
        (and, on a window nobody resizes, the ONLY) grid change must not be dropped right here:
        `_last_cols/_last_rows` would already be updated, no further Resize event follows, and the
        session keeps `invoke_shell`'s 120×32 for its whole life while the pyte grid holds the
        real canvas size. Every full-screen application then drew a 120×32 screen inside a
        differently sized canvas (the tester's "not full screen until I resize the window").
        The request now WAITS: it stays pending and `_flush_pty_grid()` sends it on connect.
        """
        if self._pending_pty is None:
            return
        if self._pty_channel() is None:
            return   # not connected yet — keep the pending value for the connect flush
        self._send_pty_resize()

    def _flush_pty_grid(self):
        """connected_signal: hand the PTY the grid the layout computed while connecting.

        The initial PTY is 120×32 (`invoke_shell`), the canvas has had its real size since the
        first layout pass, and that pass's debounced resize was refused by the missing channel.
        Making the PTY match the canvas is therefore the FIRST thing a connected session does —
        it is the SIGWINCH every TUI needs at startup, and without it the applications draw a
        120×32 screen inside a window of another size until the user happens to resize it.
        """
        try:
            self._send_pty_resize()
        except RuntimeError:
            pass  # Qt teardown — the session is already going away

    def _set_status(self, text: str):
        self._set_status_text(text)

    def _guard_paste(self, lines: int) -> bool:
        """v1.9: the production-tag guard for a MULTI-LINE paste into THIS session.

        The page is the ONE owner of the session's own tags (`server_data.tags`), so the canvas asks it
        through `widget.guard_hook`; the policy is PURE (`modules/production_guard.py`) and the dialog is
        that module's ONE `confirm()`. No guard tag on this node — the paste goes ahead untouched.
        """
        tag = guard_tag(node_tags(self.server_data))
        if not tag:
            return True
        alias = getattr(self.server_data, "alias", "") or getattr(self.server_data, "host", "")
        return guard_confirm(VERB_PASTE, tag, alias=alias, lines=lines, parent=self)

    def _set_status_text(self, text: str):
        """The SINGLE status write of the page (v1.3.3.5, completed in the v1.4.7 follow-up).

        The page owns NO status surface of its own any more (`__init__`: the old status
        line is a hidden, un-laid-out label), so the text goes exactly one way: into
        `_session_status` (the `session_status` property — what a host reads to render
        its own strip) and through the `status_message` bridge into the HOST's status
        bar / status strip. Routing EVERY status write through here is what makes the
        ERROR path readable too: a line written only to the modal dialog would leave the
        status bar on the previous text. Never raises: a
        dying C++ object must not break the status path.
        """
        self._session_status = text or ""
        try:
            self.status_label.setText(self._session_status)
        except RuntimeError:
            pass  # the C++ object was already destroyed (a close race)
        try:
            self.status_message.emit(self._session_status, 0)
        except RuntimeError:
            pass  # Qt teardown — no host left to tell

    @property
    def session_status(self) -> str:
        """The LIVE status text of this session ("" before the first write).

        The status of a session is DATA of the session and the display belongs to the
        host (a status bar with room for more than one session — the v1.4.7 follow-up
        renders the split pane's state next to the active session's).
        """
        return self._session_status

    def _show_error(self, error: str):
        t = get_translator()
        self._set_status_text(f"{t('terminal.error_prefix')} {error}")
        box = _st_module().QMessageBox   # test seam (ST.QMessageBox)
        box.critical(
            self._host_window,
            t("msg.ssh_error"),
            f"{t('terminal.error_prefix')} {error}",
        )
        self.close_terminal()

    def _on_closed(self):
        # v1.9.1: the ONE fact the Reconnect row reads — the session's channel is gone, so this
        # page can be brought back (`can_reconnect()`); the marker of a re-arm clears it again.
        self._session_ended = True
        # v1.4.7 follow-up: one write — `_set_status_text` IS the bridge now (the line
        # and the host's status surface were two writes of the same text before).
        self._set_status_text(get_translator()("terminal.session_closed"))

    # ── v1.0RC4: Quick Launch ───────────────────────────────────────────────

    def _send_initial_command(self):
        """v1.0RC4: send the first command (Quick Launch) to the shell after the connection.

        A deferred call (INITIAL_COMMAND_DELAY_MS): invoke_shell returns the channel
        immediately, while the remote shell may still be writing motd/login scripts;
        PTY input is buffered by the kernel, so the command will run once the prompt
        appears. Sent exactly once; a dead/closed channel — a quiet no-op.
        """
        def _do():
            try:
                cmd = getattr(self, "_initial_command", "")
                if not cmd:
                    return
                self._initial_command = ""  # only once
                thread = getattr(self, "terminal_thread", None)
                channel = getattr(thread, "channel", None) if thread is not None else None
                if channel is None or channel.closed:
                    return
                thread.send_data((cmd + "\n").encode("utf-8"))
                # v1.5.7 (ROADMAP task 7): quick launch is the second path the APPLICATION
                # knows the exact command of — it does not go through send_macro(), so it
                # records itself (the macro library and the History tab are covered by the
                # canvas hook).
                self.record_sent_command(cmd)
            except Exception:  # noqa: BLE001 — the window may have closed (WA_DeleteOnClose)
                pass
        QTimer.singleShot(self.INITIAL_COMMAND_DELAY_MS, _do)


# The LIVE-NAMESPACE SEAMS, declared once (`AGENTS.md` §4.1, §4.3): every name a `terminal_page_*`
# mixin resolves on THIS module at call time (`host_attr`). The declaration IS the seam — the name
# stays importable and it is the substitution point a suite patches (`TP.format_size = <fake>`), so a
# name read only by a mixin is not a dead import.
MODULE_FACADE_SEAMS = (
    get_translator, SftpWorker, OP_KINDS, format_size, sftp_name_refusal_text,
    TransferMeter, format_duration,
    # the OSC 7 cluster the suite reads on THIS module (`TP.parse_osc7`, `TP.CWD_HOOK_COMMAND`)
    parse_osc7, osc7_report_end, CWD_HOOK_COMMAND, FOLLOW_CWD_CONFIG_KEY,
)

